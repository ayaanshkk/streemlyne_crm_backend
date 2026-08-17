#C:\streemlyne_crm_backend\backend\routes\proposal_routes.py
from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy.exc import IntegrityError
from database import db
from models import ProposalMaster, ProposalDetails, ClientMaster
from middleware import auth_required, permission_required
from datetime import datetime
import json
from sqlalchemy import text
from decimal import Decimal
from flask import send_file
from fpdf import FPDF
import io
from models import TaxMaster, CurrencyMaster, TenantMaster


proposal_bp = Blueprint('proposal', __name__, url_prefix='/proposals')


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
      client_id  – filter by client (recommended for tenant isolation)
      project_id – filter by project
    """
    client_id  = request.args.get('client_id',  type=int)
    project_id = request.args.get('project_id', type=int)

    # Enforce tenant isolation by joining through Client_Master
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
    Create a new proposal with optional line items.
    POST /api/proposals
    Body:
    {
        "tax_id": 1,               (required, NOT NULL in schema)
        "total_amount": 9975.00,   (required, NOT NULL in schema)
        "client_id": 5,            (optional, FK → Client_Master)
        "project_id": 8,           (optional, FK → Project_Details)
        "currency_id": 1,
        "sub_total": 10000.00,
        "discount_percent": 5.0,
        "discount_amount": 500.00,
        "details": [
            { "service_id": 2, "quantity": 10.0, "uom_id": 3 }
        ]
    }
    """
    data = request.get_json() or {}

    required = ['total_amount']
    missing = [f for f in required if data.get(f) is None]
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400

    # Validate detail lines before writing anything
    for idx, item in enumerate(data.get('details', [])):
        if not item.get('service_name') and not item.get('service_id'):
            return jsonify({
                'error': f'Detail line {idx + 1} requires at least a service_name or service_id'
            }), 400
        if item.get('quantity') is None:
            return jsonify({'error': f'Detail line {idx + 1} requires quantity'}), 400

    # Verify client belongs to current tenant if supplied
    if data.get('client_id'):
        client = ClientMaster.query.filter_by(
            client_id=data['client_id'], tenant_id=g.tenant_id
        ).first()
        if not client:
            return jsonify({'error': 'Invalid client_id for this tenant'}), 400

    proposal = ProposalMaster(
        tenant_id        = g.tenant_id,
        client_id        = data.get('client_id'),
        project_id       = data.get('project_id'),
        tax_id           = data['tax_id'],
        sub_total = Decimal(str(data['sub_total'])) if data.get('sub_total') is not None else None,
        discount_amount = Decimal(str(data['discount_amount'])) if data.get('discount_amount') is not None else None,
        currency_id      = data.get('currency_id'),
        total_amount = Decimal(str(data['total_amount'])),
        discount_percent = data.get('discount_percent'),
        # ── previously silently dropped ───────────────────────────────────────
        customer_name    = data.get('customer_name'),
        notes            = data.get('notes'),
        company_details  = data.get('company_details'),
        payment_details  = data.get('payment_details'),
        tax_breakdown    = data.get('tax_breakdown'),   # ← new
    )

    try:
        db.session.add(proposal)
        db.session.flush()   # get proposal_id before inserting details

        for item in data.get('details', []):
            detail = ProposalDetails(
                proposal_id=proposal.proposal_id,
                service_id=item.get('service_id'),
                quantity = Decimal(str(item['quantity'])),
                amount = Decimal(str(item['amount'])) if item.get('amount') else None,
                uom_id=item['uom_id'],
                service_name=item.get('service_name'),
            )
            db.session.add(detail)

        db.session.commit()

    except IntegrityError as e:
        db.session.rollback()
        return jsonify({
            'error': 'Invalid foreign key reference — check project_id, service_id, or uom_id'
        }), 409

    return jsonify(_proposal_dict(proposal, include_details=True)), 201


@proposal_bp.route('/<int:proposal_id>', methods=['GET'])
@auth_required
def get_proposal(proposal_id: int):
    """
    Retrieve a proposal with its line items.
    GET /api/proposals/<proposal_id>
    """
    proposal = _get_or_404(proposal_id)
    return jsonify(_proposal_dict(proposal, include_details=True)), 200


@proposal_bp.route('/<int:proposal_id>', methods=['PUT'])
@auth_required
# @permission_required('proposal.update')
def update_proposal(proposal_id: int):
    """
    Update proposal header fields.
    PUT /api/proposals/<proposal_id>
    Detail lines are managed via the /details sub-resource.
    """
    proposal = _get_or_404(proposal_id)
    data = request.get_json() or {}

    # Non-numeric fields
    for field in [
        'tax_id', 'currency_id', 'client_id', 'project_id',
        'customer_name', 'notes', 'company_details', 'payment_details', 'tax_breakdown'
    ]:
        if field in data:
            setattr(proposal, field, data[field])

    # Numeric fields
    if 'sub_total' in data:
        proposal.sub_total = Decimal(str(data['sub_total'])) if data['sub_total'] is not None else None

    if 'total_amount' in data:
        proposal.total_amount = Decimal(str(data['total_amount']))

    if 'discount_amount' in data:
        proposal.discount_amount = Decimal(str(data['discount_amount'])) if data['discount_amount'] is not None else None

    if 'discount_percent' in data:
        proposal.discount_percent = data['discount_percent']


    proposal.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid foreign key reference — check client_id or project_id'}), 409

    return jsonify({
        'message': 'Proposal updated',
        'proposal': _proposal_dict(proposal, include_details=True)
    }), 200


@proposal_bp.route('/<int:proposal_id>', methods=['DELETE'])
@auth_required
# @permission_required('proposal.delete')
def delete_proposal(proposal_id: int):
    """
    Delete a proposal and all its line items.
    DELETE /api/proposals/<proposal_id>
    Line items are removed via DB cascade on proposal_id FK.
    """
    proposal = _get_or_404(proposal_id)

    try:
        db.session.delete(proposal)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'error': 'Cannot delete proposal — it is referenced by an invoice'
        }), 409

    return jsonify({'message': 'Proposal deleted'}), 200


# ─────────────────────────────────────────
# Proposal Detail Lines – sub-resource
# ─────────────────────────────────────────

@proposal_bp.route('/<int:proposal_id>/details', methods=['GET'])
@auth_required
def list_detail_lines(proposal_id: int):
    """
    List line items for a proposal.
    GET /api/proposals/<proposal_id>/details
    """
    _get_or_404(proposal_id)
    details = ProposalDetails.query.filter_by(proposal_id=proposal_id).all()
    # ── Fetch tenant for logo and company info ────────────────────────────
    tenant = TenantMaster.query.filter_by(tenant_id=str(g.tenant_id)).first()
    logo_url   = tenant.logo_url        if tenant else None
    company_name_display = (tenant.tenant_company_name if tenant else None) or "StreemLyne"
    company_email_display   = tenant.company_email    if tenant else None
    company_phone_display   = tenant.company_phone    if tenant else None
    company_address_display = tenant.company_address  if tenant else None
    company_website_display = tenant.company_website  if tenant else None

    return jsonify([_detail_dict(d) for d in details]), 200


@proposal_bp.route('/<int:proposal_id>/details', methods=['POST'])
@auth_required
# @permission_required('proposal.update')
def add_detail_line(proposal_id: int):
    """
    Add a line item to an existing proposal.
    POST /api/proposals/<proposal_id>/details
    Body: { "service_id": 3, "quantity": 5.0, "uom_id": 2 }
    """
    _get_or_404(proposal_id)
    data = request.get_json() or {}

    required = ['service_id', 'quantity', 'uom_id']
    missing = [f for f in required if data.get(f) is None]
    if missing:
        return jsonify({'error': f'Missing fields: {", ".join(missing)}'}), 400

    detail = ProposalDetails(
        proposal_id=proposal_id,
        service_id=item.get('service_id'),
        quantity=Decimal(str(data['quantity'])),
        amount=Decimal(str(data['amount'])) if data.get('amount') else None,
        uom_id=data['uom_id'],
        service_name=data.get('service_name'),
    )

    try:
        db.session.add(detail)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid service_id or uom_id'}), 409

    return jsonify({
        'message': 'Detail line added',
        'detail': _detail_dict(detail)
    }), 201


@proposal_bp.route('/<int:proposal_id>/details/<int:detail_id>', methods=['PUT'])
@auth_required
# @permission_required('proposal.update')
def update_detail_line(proposal_id: int, detail_id: int):
    """
    Update a proposal line item.
    PUT /api/proposals/<proposal_id>/details/<detail_id>
    Body: { "quantity": 7.0, "uom_id": 2, "service_id": 4 }
    """
    _get_or_404(proposal_id)
    detail = ProposalDetails.query.filter_by(
        proposal_details_id=detail_id, proposal_id=proposal_id
    ).first()
    if not detail:
        abort(404, description='Detail line not found')

    data = request.get_json() or {}
    for field in ['service_id', 'quantity', 'uom_id', 'service_name', 'description', 'amount']:
        if field in data:
            if field == 'amount':
                setattr(detail, field, Decimal(str(data[field])) if data[field] else None)
            else:
                setattr(detail, field, data[field])

    detail.updated_at = datetime.utcnow()

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
    """
    Remove a line item from a proposal.
    DELETE /api/proposals/<proposal_id>/details/<detail_id>
    """
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
# Private helpers
# ─────────────────────────────────────────

def _get_or_404(proposal_id: int) -> ProposalMaster:
    proposal = ProposalMaster.query.filter_by(
        proposal_id=proposal_id,
        tenant_id=g.tenant_id,
    ).first()
    if not proposal:
        abort(404, description='Proposal not found')
    return proposal

def _proposal_dict(p: ProposalMaster, include_details: bool = True) -> dict:
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
        'tax_breakdown':    p.tax_breakdown,
        'created_at':       p.created_at.isoformat() if p.created_at else None,
        'updated_at':       p.updated_at.isoformat() if p.updated_at else None,
        'sub_total': float(p.sub_total) if p.sub_total is not None else None,
        'total_amount': float(p.total_amount) if p.total_amount is not None else None,
        'discount_amount': float(p.discount_amount) if p.discount_amount is not None else None,
    }

    # Fallback: derive customer_name from Client_Master if not stored directly
    if not result['customer_name'] and p.client_id:
        client = ClientMaster.query.get(p.client_id)
        if client:
            result['customer_name'] = (
                client.client_contact_name or
                client.client_company_name or
                f"Client #{client.client_id}"
            )

    if include_details:
        result['details'] = [
            _detail_dict(d)
            for d in p.proposal_details.all()
        ]
    return result
    



def _detail_dict(d: ProposalDetails) -> dict:
    return {
        'proposal_details_id': d.proposal_details_id,
        'proposal_id':         d.proposal_id,
        'service_id':          d.service_id,
        'service_name':        d.service_name,
        'uom_id':              d.uom_id,
        'created_at':          d.created_at.isoformat() if d.created_at else None,
        'updated_at':          d.updated_at.isoformat() if d.updated_at else None,
        'amount': float(d.amount) if d.amount is not None else None,
        'quantity': float(d.quantity),
    }

@proposal_bp.route('/<int:proposal_id>/pdf', methods=['GET'])
@auth_required
def download_proposal_pdf(proposal_id: int):
    """
    Generate and stream a quote PDF.
    GET /api/proposals/<proposal_id>/pdf
    """
    proposal = _get_or_404(proposal_id)

    # ── Resolve related data ──────────────────────────────────────────────────
    client   = ClientMaster.query.get(proposal.client_id) if proposal.client_id else None
    tax      = TaxMaster.query.get(proposal.tax_id)       if proposal.tax_id    else None
    currency = CurrencyMaster.query.get(proposal.currency_id) if proposal.currency_id else None
    details  = proposal.proposal_details.all()

    currency_symbol = "£"  # default GBP
    if currency:
        symbol_map = {"GBP": "£", "USD": "$", "EUR": "€"}
        currency_symbol = symbol_map.get(currency.currency_code, currency.currency_code + " ")

    tax_rate = float(tax.tax_rate) if tax else 0.0

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

    sub_total        = float(proposal.sub_total or 0)
    discount_amount  = float(proposal.discount_amount or 0)
    total_amount     = float(proposal.total_amount or 0)
    tax_amount       = round(sub_total * tax_rate / 100, 2)

    # ── Build PDF ─────────────────────────────────────────────────────────────
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)

    # Header bar
    # ── Fetch tenant for logo and company info ────────────────────────
    tenant = TenantMaster.query.filter_by(tenant_id=str(g.tenant_id)).first()
    logo_url              = tenant.logo_url            if tenant else None
    company_name_display  = (tenant.tenant_company_name if tenant else None) or "StreemLyne"
    company_email_display = tenant.company_email       if tenant else None
    company_phone_display = tenant.company_phone       if tenant else None
    company_address_display = tenant.company_address   if tenant else None

    # ── Header bar ────────────────────────────────────────────────────
    pdf.set_fill_color(30, 30, 30)
    pdf.rect(0, 0, 210, 32, 'F')

    # Logo
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

    # Company name
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(36 if logo_rendered else 8, 7)
    pdf.cell(80, 8, company_name_display, ln=False)

    # QUOTE label
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_xy(140, 5)
    pdf.cell(0, 8, "QUOTE", ln=False)

    # Quote number + date
    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(140, 14)
    pdf.cell(0, 5, f"#{proposal.quote_id or proposal.proposal_id}", ln=True)
    pdf.set_xy(140, 19)
    pdf.cell(0, 5, f"{proposal.created_at.strftime('%d %b %Y') if proposal.created_at else 'N/A'}")

    pdf.set_text_color(0, 0, 0)
    pdf.set_xy(15, 38)

    # Bill To
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(85, 6, "BILL TO", ln=False, fill=True)
    pdf.cell(10, 6, "", ln=False)  # gap
    pdf.cell(85, 6, "QUOTE DETAILS", ln=True, fill=True)

    pdf.set_font("Helvetica", "", 9)
    left_lines  = [customer_name, company_name, address, post_code, email, phone]
    right_lines = [
        f"Status: Draft",
        f"Tax: {tax.tax_name if tax else 'N/A'} ({tax_rate}%)",
        f"Currency: {currency.currency_code if currency else 'GBP'}",
    ]
    if proposal.notes:
        right_lines.append(f"Notes: {proposal.notes[:60]}")

    max_lines = max(len(left_lines), len(right_lines))
    for i in range(max_lines):
        left_text  = left_lines[i]  if i < len(left_lines)  else ""
        right_text = right_lines[i] if i < len(right_lines) else ""
        pdf.set_x(15)
        pdf.cell(85, 5, left_text,  ln=False)
        pdf.cell(10, 5, "",         ln=False)
        pdf.cell(85, 5, right_text, ln=True)

    pdf.ln(6)

    # Line items table header
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
        service_name = d.service_name or (d.service.service_title if d.service else f"Service #{d.service_id}")
        qty          = float(d.quantity)
        amount       = float(d.amount) if d.amount else 0.0
        unit_price   = round(amount / qty, 2) if qty else 0.0
        uom_label    = d.uom.uom_description if d.uom else ""

        # Multi-line service name
        x_before = pdf.get_x()
        y_before = pdf.get_y()
        pdf.multi_cell(75, 6, service_name, fill=fill)
        y_after = pdf.get_y()
        row_h = y_after - y_before

        pdf.set_xy(x_before + 75, y_before)
        pdf.cell(25, row_h, str(qty),                      align="C", fill=fill, border=0)
        pdf.cell(20, row_h, uom_label,                     align="C", fill=fill, border=0)
        pdf.cell(35, row_h, f"{currency_symbol}{unit_price:,.2f}", align="R", fill=fill, border=0)
        pdf.cell(25, row_h, f"{currency_symbol}{amount:,.2f}",     align="R", fill=fill, border=0, ln=True)
        fill = not fill

    pdf.ln(4)

    # Totals
    pdf.set_font("Helvetica", "", 9)
    col_w = 45

    def totals_row(label, value, bold=False):
        if bold:
            pdf.set_font("Helvetica", "B", 10)
        else:
            pdf.set_font("Helvetica", "", 9)
        pdf.set_x(120)
        pdf.cell(col_w, 6, label, align="R")
        pdf.cell(col_w, 6, value, align="R", ln=True)

    totals_row("Subtotal:",           f"{currency_symbol}{sub_total:,.2f}")
    if discount_amount:
        totals_row("Discount:",       f"-{currency_symbol}{discount_amount:,.2f}")
    if tax_rate:
        totals_row(f"Tax ({tax_rate}%):", f"{currency_symbol}{tax_amount:,.2f}")

    pdf.set_draw_color(30, 30, 30)
    pdf.set_x(120)
    pdf.cell(90, 0.5, "", ln=True, fill=True, border="T")

    totals_row("TOTAL:",              f"{currency_symbol}{total_amount:,.2f}", bold=True)

    # Payment details
    if proposal.payment_details:
        pdf.ln(8)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(0, 6, "PAYMENT DETAILS", fill=True, ln=True)
        pdf.set_font("Helvetica", "", 9)
        pd = proposal.payment_details
        if isinstance(pd, dict):
            for k, v in pd.items():
                if v:
                    pdf.cell(0, 5, f"{k.replace('_', ' ').title()}: {v}", ln=True)

    # Footer
    pdf.set_y(-20)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, "Thank you for your business.", align="C", ln=True)

    # ── Stream ────────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)

    filename = f"{proposal.quote_id or f'quote-{proposal.proposal_id}'}.pdf"
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )