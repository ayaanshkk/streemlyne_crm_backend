#C:\streemlyne_crm_backend\backend\routes\proposal_routes.py
from flask import Blueprint, request, jsonify, g, abort, send_file, current_app
from sqlalchemy.exc import IntegrityError
from database import db
from models import (ProposalMaster, ProposalDetails, ClientMaster,
                    CurrencyMaster, TenantMaster, ServicesMaster)
from middleware import auth_required, permission_required
from datetime import datetime, date
from decimal import Decimal
from fpdf import FPDF
import io


proposal_bp = Blueprint('proposal', __name__, url_prefix='/proposals')

# Status_Master quote statuses
QUOTE_STATUS_NAMES = {5: 'Draft', 6: 'Pending', 7: 'Sent', 8: 'Approved', 9: 'Rejected'}


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_date(value):
    """Accepts 'YYYY-MM-DD' (what <input type=date> sends) or None."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _validate_lines(lines):
    """Return an error string, or None when every line is valid."""
    for idx, item in enumerate(lines or []):
        if not item.get('service_name') and not item.get('service_id'):
            return f'Detail line {idx + 1} requires at least a service_name or service_id'
        if item.get('quantity') is None:
            return f'Detail line {idx + 1} requires quantity'
    return None


def _new_line(proposal_id: int, item: dict) -> ProposalDetails:
    """
    Build one row for Quotation_Details_new.

    The quote pages send the UNIT PRICE in `amount`.
      Rate         = unit price
      Total_Amount = quantity * rate  (model attribute: amount)
    Product_Variant_ID is filled by the before_insert listener in models.py.
    """
    qty  = _num(item.get('quantity'), 1.0)
    rate = _num(item.get('amount', item.get('rate')))

    name = item.get('service_name')
    if not name and item.get('service_id'):
        svc = ServicesMaster.query.get(item['service_id'])
        name = svc.service_title if svc else None

    return ProposalDetails(
        proposal_id  = proposal_id,
        service_id   = item.get('service_id') or None,   # None for Custom lines
        service_name = name or 'Item',                   # Item_Name is NOT NULL
        description  = item.get('description'),
        quantity     = qty,
        uom_id       = item.get('uom_id') or 1,          # UOM_ID is NOT NULL
        rate         = rate,
        line_discount= 0,                                # Discount_Amount is NOT NULL
        amount       = round(qty * rate, 2),
    )


def _get_or_404(proposal_id: int) -> ProposalMaster:
    proposal = ProposalMaster.query.filter_by(
        proposal_id=proposal_id,
        tenant_id=g.tenant_id,
    ).first()
    if not proposal:
        abort(404, description='Proposal not found')
    return proposal


# ─────────────────────────────────────────
# Proposals – CRUD
# ─────────────────────────────────────────

@proposal_bp.route('', methods=['GET'])
@auth_required
def list_proposals():
    """
    List proposals, scoped to the current tenant via Client_Master.
    GET /api/proposals
    Query params:
      client_id  – filter by client
      project_id – filter by project
    """
    client_id  = request.args.get('client_id',  type=int)
    project_id = request.args.get('project_id', type=int)

    query = (
        ProposalMaster.query
        .join(ClientMaster, ProposalMaster.client_id == ClientMaster.client_id)
        .filter(ClientMaster.tenant_id == g.tenant_id)
    )

    if client_id:
        query = query.filter(ProposalMaster.client_id == client_id)
    if project_id:
        query = query.filter(ProposalMaster.project_id == project_id)

    proposals = query.order_by(ProposalMaster.created_at.desc()).all()
    return jsonify([_proposal_dict(p, include_details=True) for p in proposals]), 200


@proposal_bp.route('', methods=['POST'])
@auth_required
# @permission_required('proposal.create')
def create_proposal():
    """
    Create a quote (Quotation_Master_new) with its lines (Quotation_Details_new).
    POST /api/proposals
    Body:
    {
        "client_id": 5,
        "sub_total": 10000.00,          (before discount)
        "discount_percent": 5.0,        (or discount_amount for a fixed discount)
        "discount_amount": 500.00,
        "total_amount": 11400.00,       (sub - discount + tax)
        "valid_until": "2026-11-27",
        "notes": "...",
        "details": [
            { "service_id": null, "service_name": "Item", "quantity": 10,
              "amount": 100.0, "uom_id": 1 }        (amount = unit price)
        ]
    }
    """
    data = request.get_json() or {}

    if data.get('total_amount') is None:
        return jsonify({'error': 'Missing required fields: total_amount'}), 400

    err = _validate_lines(data.get('details', []))
    if err:
        return jsonify({'error': err}), 400

    if data.get('client_id'):
        client = ClientMaster.query.filter_by(
            client_id=data['client_id'], tenant_id=g.tenant_id
        ).first()
        if not client:
            return jsonify({'error': 'Invalid client_id for this tenant'}), 400

    sub_total       = _num(data.get('sub_total'))
    discount_amount = _num(data.get('discount_amount'))
    discount_pct    = data.get('discount_percent')
    # Quotation_Master_new only stores a discount PERCENT, so a fixed discount
    # is converted to its equivalent percent (otherwise it is lost on reload).
    if discount_pct is None and discount_amount and sub_total:
        discount_pct = discount_amount / sub_total * 100

    # Order matters: sub_total and discount_amount must be set before total_amount.
    proposal = ProposalMaster(
        tenant_id        = g.tenant_id,
        client_id        = data.get('client_id'),
        project_id       = data.get('project_id'),
        currency_id      = data.get('currency_id'),
        sub_total        = Decimal(str(sub_total)),
        discount_amount  = discount_amount,
        total_amount     = Decimal(str(data['total_amount'])),
        discount_percent = discount_pct,
        valid_until      = _parse_date(data.get('valid_until')),
        notes            = data.get('notes'),
        # not columns in Quotation_Master_new – kept as plain attributes only
        tax_id           = data.get('tax_id'),
        customer_name    = data.get('customer_name'),
        company_details  = data.get('company_details'),
        payment_details  = data.get('payment_details'),
        tax_breakdown    = data.get('tax_breakdown'),
    )

    try:
        db.session.add(proposal)
        db.session.flush()   # get Quotation_ID before inserting lines

        for item in data.get('details', []):
            db.session.add(_new_line(proposal.proposal_id, item))

        # A new quotation moves the company's Opportunity leads to Proposal. This runs in
        # a savepoint so a pipeline problem can never stop the quotation from saving.
        if proposal.client_id:
            try:
                from routes.pipeline_routes import move_client_leads_to_proposal
                with db.session.begin_nested():
                    move_client_leads_to_proposal(g.tenant_id, proposal.client_id)
            except Exception:
                current_app.logger.exception('Could not move leads to Proposal after quotation create')

        db.session.commit()

    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'error': 'Invalid foreign key reference — check client_id, service_id or uom_id'
        }), 409

    return jsonify(_proposal_dict(proposal, include_details=True)), 201


@proposal_bp.route('/<int:proposal_id>', methods=['GET'])
@auth_required
def get_proposal(proposal_id: int):
    """GET /api/proposals/<proposal_id>"""
    proposal = _get_or_404(proposal_id)
    return jsonify(_proposal_dict(proposal, include_details=True)), 200


@proposal_bp.route('/<int:proposal_id>', methods=['PUT'])
@auth_required
# @permission_required('proposal.update')
def update_proposal(proposal_id: int):
    """
    Update a quote. If `details` is sent, the quote's lines are REPLACED by it
    (the edit page always sends the full list).
    PUT /api/proposals/<proposal_id>
    """
    proposal = _get_or_404(proposal_id)
    data = request.get_json() or {}

    if 'details' in data:
        err = _validate_lines(data['details'])
        if err:
            return jsonify({'error': err}), 400

    for field in ['currency_id', 'client_id', 'project_id', 'notes',
                  'tax_id', 'customer_name', 'company_details',
                  'payment_details', 'tax_breakdown']:
        if field in data:
            setattr(proposal, field, data[field])

    if 'valid_until' in data:
        proposal.valid_until = _parse_date(data['valid_until'])

    # Order matters: sub_total -> discount -> total_amount
    if 'sub_total' in data:
        proposal.sub_total = Decimal(str(_num(data['sub_total'])))

    if 'discount_percent' in data or 'discount_amount' in data:
        sub          = float(proposal.sub_total or 0)
        discount_pct = data.get('discount_percent')
        discount_amt = data.get('discount_amount')
        if discount_pct is None and discount_amt and sub:
            discount_pct = _num(discount_amt) / sub * 100
        proposal.discount_percent = discount_pct
        proposal.discount_amount  = _num(discount_amt) if discount_amt is not None else None

    if 'total_amount' in data:
        proposal.total_amount = Decimal(str(data['total_amount']))

    try:
        if 'details' in data:
            ProposalDetails.query.filter_by(
                proposal_id=proposal.proposal_id
            ).delete(synchronize_session=False)
            for item in data['details']:
                db.session.add(_new_line(proposal.proposal_id, item))

        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid foreign key reference — check client_id, service_id or uom_id'}), 409

    db.session.refresh(proposal)
    return jsonify({
        'message': 'Proposal updated',
        'proposal': _proposal_dict(proposal, include_details=True)
    }), 200


QUOTE_STATUS_IDS = {name: sid for sid, name in QUOTE_STATUS_NAMES.items()}


@proposal_bp.route('/<int:proposal_id>', methods=['PATCH'])
@auth_required
# @permission_required('proposal.update')
def patch_proposal_status(proposal_id: int):
    """
    Change a quote's status (used by the status dropdown on the quotes list).
    PATCH /api/proposals/<proposal_id>
    Body: { "status": "Sent" }   or   { "status_id": 7 }
    """
    proposal = _get_or_404(proposal_id)
    data = request.get_json() or {}

    status_id = data.get('status_id') or QUOTE_STATUS_IDS.get(data.get('status'))
    if status_id not in QUOTE_STATUS_NAMES:
        return jsonify({'error': f"Invalid status. Use one of: {', '.join(QUOTE_STATUS_IDS)}"}), 400

    proposal.status_id = status_id
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid status'}), 409

    return jsonify({
        'message': 'Status updated',
        'status': QUOTE_STATUS_NAMES[status_id],
        'proposal': _proposal_dict(proposal, include_details=False),
    }), 200


@proposal_bp.route('/<int:proposal_id>', methods=['DELETE'])
@auth_required
# @permission_required('proposal.delete')
def delete_proposal(proposal_id: int):
    """DELETE /api/proposals/<proposal_id> – lines are removed with it."""
    proposal = _get_or_404(proposal_id)

    try:
        db.session.delete(proposal)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'error': 'Cannot delete proposal — it is referenced by an invoice or training record'
        }), 409

    return jsonify({'message': 'Proposal deleted'}), 200


# ─────────────────────────────────────────
# Proposal Detail Lines – sub-resource
# ─────────────────────────────────────────

@proposal_bp.route('/<int:proposal_id>/details', methods=['GET'])
@auth_required
def list_detail_lines(proposal_id: int):
    """GET /api/proposals/<proposal_id>/details"""
    _get_or_404(proposal_id)
    details = ProposalDetails.query.filter_by(proposal_id=proposal_id).all()
    return jsonify([_detail_dict(d) for d in details]), 200


@proposal_bp.route('/<int:proposal_id>/details', methods=['POST'])
@auth_required
# @permission_required('proposal.update')
def add_detail_line(proposal_id: int):
    """
    POST /api/proposals/<proposal_id>/details
    Body: { "service_name": "Item", "quantity": 5, "amount": 100.0, "uom_id": 1 }
    (amount = unit price)
    """
    _get_or_404(proposal_id)
    data = request.get_json() or {}

    err = _validate_lines([data])
    if err:
        return jsonify({'error': err.replace('Detail line 1', 'Line')}), 400

    detail = _new_line(proposal_id, data)

    try:
        db.session.add(detail)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid service_id or uom_id'}), 409

    return jsonify({'message': 'Detail line added', 'detail': _detail_dict(detail)}), 201


@proposal_bp.route('/<int:proposal_id>/details/<int:detail_id>', methods=['PUT'])
@auth_required
# @permission_required('proposal.update')
def update_detail_line(proposal_id: int, detail_id: int):
    """PUT /api/proposals/<proposal_id>/details/<detail_id>"""
    _get_or_404(proposal_id)
    detail = ProposalDetails.query.filter_by(
        proposal_details_id=detail_id, proposal_id=proposal_id
    ).first()
    if not detail:
        abort(404, description='Detail line not found')

    data = request.get_json() or {}

    if 'quantity' in data:
        detail.quantity = _num(data['quantity'], 1.0)
    if 'amount' in data or 'rate' in data:
        detail.rate = _num(data.get('amount', data.get('rate')))
    if 'service_id' in data:
        detail.service_id = data['service_id'] or None
    if 'description' in data:
        detail.description = data['description']
    if data.get('service_name'):
        detail.service_name = data['service_name']
    if data.get('uom_id'):
        detail.uom_id = data['uom_id']

    # keep Total_Amount in step with quantity / rate
    detail.amount = round(
        float(detail.quantity or 0) * float(detail.rate or 0) - float(detail.line_discount or 0), 2
    )

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid service_id or uom_id'}), 409

    return jsonify({'message': 'Detail line updated', 'detail': _detail_dict(detail)}), 200


@proposal_bp.route('/<int:proposal_id>/details/<int:detail_id>', methods=['DELETE'])
@auth_required
# @permission_required('proposal.update')
def remove_detail_line(proposal_id: int, detail_id: int):
    """DELETE /api/proposals/<proposal_id>/details/<detail_id>"""
    _get_or_404(proposal_id)
    detail = ProposalDetails.query.filter_by(
        proposal_details_id=detail_id, proposal_id=proposal_id
    ).first()
    if not detail:
        abort(404, description='Detail line not found')

    db.session.delete(detail)
    db.session.commit()
    return jsonify({'message': 'Detail line removed'}), 200


# ─────────────────────────────────────────
# Serialisers
# ─────────────────────────────────────────

def _derived_tax(p: ProposalMaster):
    """Tax_Amount is stored on the quote; the rate is derived from it."""
    sub        = float(p.sub_total or 0)
    discount   = float(p.discount_amount or 0)
    tax_amount = float(p.tax_amount or 0)
    base       = sub - discount
    rate       = round(tax_amount / base * 100, 2) if base > 0 else 0.0
    return tax_amount, rate


def _proposal_dict(p: ProposalMaster, include_details: bool = True) -> dict:
    tax_amount, vat_rate = _derived_tax(p)

    result = {
        'quote_id':         p.quote_id,
        'proposal_id':      p.proposal_id,
        'client_id':        p.client_id,
        'project_id':       p.project_id,
        'tax_id':           p.tax_id,
        'currency_id':      p.currency_id,
        'discount_percent': p.discount_percent,
        'customer_name':    p.customer_name,
        'notes':            p.notes,
        'company_details':  p.company_details,
        'payment_details':  p.payment_details,
        'valid_until':      p.valid_until.isoformat() if p.valid_until else None,
        'created_at':       p.created_at.isoformat() if p.created_at else None,
        'updated_at':       p.updated_at.isoformat() if p.updated_at else None,
        'sub_total':        float(p.sub_total) if p.sub_total is not None else None,
        'total_amount':     float(p.total_amount) if p.total_amount is not None else None,
        'discount_amount':  float(p.discount_amount) if p.discount_amount is not None else None,
        'tax_amount':       tax_amount,
        'vat_rate':         vat_rate,
        'status_id':        p.status_id,
    }

    # Tax breakdown is not a column: rebuild it from the stored tax amount
    result['tax_breakdown'] = p.tax_breakdown or (
        [{'name': 'VAT', 'rate': vat_rate, 'amount': tax_amount}] if tax_amount else []
    )

    # names used by FAI's copy of the proposals pages
    result.update({
        'id':               p.proposal_id,
        'quotation_number': p.quote_id,
        'status':           QUOTE_STATUS_NAMES.get(p.status_id, 'Draft'),
        'grand_total':      result['total_amount'],
        'date':             result['created_at'],
        'customer_id':      p.client_id,
    })

    # customer_name is not stored: derive it from Client_Master
    if not result['customer_name'] and p.client_id:
        client = ClientMaster.query.get(p.client_id)
        if client:
            result['customer_name'] = (
                client.client_contact_name or
                client.client_company_name or
                f"Client #{client.client_id}"
            )

    if include_details:
        result['details'] = [_detail_dict(d) for d in p.proposal_details.all()]
    return result


def _detail_dict(d: ProposalDetails) -> dict:
    rate = float(d.rate or 0)
    return {
        'proposal_details_id': d.proposal_details_id,
        'proposal_id':         d.proposal_id,
        'service_id':          d.service_id,
        'service_name':        d.service_name,
        'description':         d.description,
        'uom_id':              d.uom_id,
        'quantity':            float(d.quantity or 0),
        # the quote pages read `amount` as the UNIT PRICE
        'amount':              rate,
        'unit_price':          rate,
        'rate':                rate,
        # Total_Amount of the line (quantity * rate)
        'line_total':          float(d.amount or 0),
    }


# ─────────────────────────────────────────
# PDF
# ─────────────────────────────────────────

@proposal_bp.route('/<int:proposal_id>/pdf', methods=['GET'])
@auth_required
def download_proposal_pdf(proposal_id: int):
    """GET /api/proposals/<proposal_id>/pdf"""
    proposal = _get_or_404(proposal_id)

    client   = ClientMaster.query.get(proposal.client_id) if proposal.client_id else None
    currency = CurrencyMaster.query.get(proposal.currency_id) if proposal.currency_id else None
    details  = proposal.proposal_details.all()

    currency_symbol = "£"  # default GBP
    if currency:
        symbol_map = {"GBP": "£", "USD": "$", "EUR": "€"}
        currency_symbol = symbol_map.get(currency.currency_code, (currency.currency_code or "") + " ")

    customer_name = (
        proposal.customer_name or
        (client.client_contact_name if client else None) or
        (client.client_company_name if client else None) or
        "N/A"
    )
    company_name = (client.client_company_name if client else "") or ""
    address      = (client.address   if client else "") or ""
    post_code    = (client.post_code if client else "") or ""
    email        = (client.client_email if client else "") or ""
    phone        = (client.client_phone if client else "") or ""

    sub_total       = float(proposal.sub_total or 0)
    discount_amount = float(proposal.discount_amount or 0)
    total_amount    = float(proposal.total_amount or 0)
    tax_amount, tax_rate = _derived_tax(proposal)   # stored tax, rate derived

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)

    # ── Tenant branding ───────────────────────────────────────────────
    tenant = TenantMaster.query.filter_by(tenant_id=g.tenant_id).first()
    logo_url             = tenant.logo_url if tenant else None
    company_name_display = (tenant.tenant_company_name if tenant else None) or "StreemLyne"

    # ── Header bar ────────────────────────────────────────────────────
    pdf.set_fill_color(30, 30, 30)
    pdf.rect(0, 0, 210, 32, 'F')

    logo_rendered = False
    if logo_url:
        try:
            import requests as _requests, tempfile, os as _os
            suffix = ".png" if "png" in logo_url.lower() else ".jpg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                response = _requests.get(logo_url, timeout=5)
                tmp.write(response.content)
                tmp_path = tmp.name
            pdf.image(tmp_path, x=8, y=4, h=22)
            _os.unlink(tmp_path)
            logo_rendered = True
        except Exception as e:
            print(f"[PDF] Logo load failed: {e}")

    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(36 if logo_rendered else 8, 7)
    pdf.cell(80, 8, company_name_display, ln=False)

    pdf.set_font("Helvetica", "B", 16)
    pdf.set_xy(140, 5)
    pdf.cell(0, 8, "QUOTE", ln=False)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(140, 14)
    pdf.cell(0, 5, f"#{proposal.quote_id or proposal.proposal_id}", ln=True)
    pdf.set_xy(140, 19)
    pdf.cell(0, 5, f"{proposal.created_at.strftime('%d %b %Y') if proposal.created_at else 'N/A'}")

    pdf.set_text_color(0, 0, 0)
    pdf.set_xy(15, 38)

    # ── Bill to / quote details ───────────────────────────────────────
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(85, 6, "BILL TO", ln=False, fill=True)
    pdf.cell(10, 6, "", ln=False)
    pdf.cell(85, 6, "QUOTE DETAILS", ln=True, fill=True)

    pdf.set_font("Helvetica", "", 9)
    left_lines  = [customer_name, company_name, address, post_code, email, phone]
    right_lines = [
        f"Status: {QUOTE_STATUS_NAMES.get(proposal.status_id, 'Draft')}",
        f"Tax: VAT ({tax_rate}%)" if tax_rate else "Tax: N/A",
        f"Currency: {currency.currency_code if currency else 'GBP'}",
    ]
    if proposal.valid_until:
        right_lines.append(f"Valid until: {proposal.valid_until.strftime('%d %b %Y')}")
    if proposal.notes:
        right_lines.append(f"Notes: {proposal.notes[:60]}")

    for i in range(max(len(left_lines), len(right_lines))):
        left_text  = left_lines[i]  if i < len(left_lines)  else ""
        right_text = right_lines[i] if i < len(right_lines) else ""
        pdf.set_x(15)
        pdf.cell(85, 5, left_text,  ln=False)
        pdf.cell(10, 5, "",         ln=False)
        pdf.cell(85, 5, right_text, ln=True)

    pdf.ln(6)

    # ── Line items ────────────────────────────────────────────────────
    pdf.set_fill_color(30, 30, 30)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(75, 7, "Description",   fill=True)
    pdf.cell(25, 7, "Qty",           fill=True, align="C")
    pdf.cell(20, 7, "UOM",           fill=True, align="C")
    pdf.cell(35, 7, f"Unit Price ({currency_symbol})", fill=True, align="R")
    pdf.cell(25, 7, f"Amount ({currency_symbol})",     fill=True, align="R", ln=True)

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 9)

    fill = False
    for d in details:
        pdf.set_fill_color(248, 248, 248) if fill else pdf.set_fill_color(255, 255, 255)
        item_name  = d.service_name or f"Service #{d.service_id}"
        qty        = float(d.quantity or 0)
        unit_price = float(d.rate or 0)      # Rate
        amount     = float(d.amount or 0)    # Total_Amount
        uom_label  = d.uom.uom_description if d.uom else ""

        x_before = pdf.get_x()
        y_before = pdf.get_y()
        pdf.multi_cell(75, 6, item_name, fill=fill)
        row_h = pdf.get_y() - y_before

        pdf.set_xy(x_before + 75, y_before)
        pdf.cell(25, row_h, f"{qty:g}",                            align="C", fill=fill, border=0)
        pdf.cell(20, row_h, uom_label,                             align="C", fill=fill, border=0)
        pdf.cell(35, row_h, f"{currency_symbol}{unit_price:,.2f}", align="R", fill=fill, border=0)
        pdf.cell(25, row_h, f"{currency_symbol}{amount:,.2f}",     align="R", fill=fill, border=0, ln=True)
        fill = not fill

    pdf.ln(4)

    # ── Totals ────────────────────────────────────────────────────────
    col_w = 45

    def totals_row(label, value, bold=False):
        pdf.set_font("Helvetica", "B" if bold else "", 10 if bold else 9)
        pdf.set_x(120)
        pdf.cell(col_w, 6, label, align="R")
        pdf.cell(col_w, 6, value, align="R", ln=True)

    totals_row("Subtotal:", f"{currency_symbol}{sub_total:,.2f}")
    if discount_amount:
        totals_row("Discount:", f"-{currency_symbol}{discount_amount:,.2f}")
    if tax_amount:
        totals_row(f"VAT ({tax_rate}%):", f"{currency_symbol}{tax_amount:,.2f}")

    pdf.set_draw_color(30, 30, 30)
    pdf.set_x(120)
    pdf.cell(90, 0.5, "", ln=True, fill=True, border="T")

    totals_row("TOTAL:", f"{currency_symbol}{total_amount:,.2f}", bold=True)

    # ── Payment details (only when supplied) ──────────────────────────
    if proposal.payment_details and isinstance(proposal.payment_details, dict):
        pdf.ln(8)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(0, 6, "PAYMENT DETAILS", fill=True, ln=True)
        pdf.set_font("Helvetica", "", 9)
        for k, v in proposal.payment_details.items():
            if v:
                pdf.cell(0, 5, f"{k.replace('_', ' ').title()}: {v}", ln=True)

    # ── Footer ────────────────────────────────────────────────────────
    pdf.set_y(-20)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, "Thank you for your business.", align="C", ln=True)

    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)

    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{proposal.quote_id or f'quote-{proposal.proposal_id}'}.pdf",
    )