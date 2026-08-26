# backend/routes/quotation_routes.py
from flask import Blueprint, request, jsonify, g, abort, send_file
from sqlalchemy.exc import IntegrityError
from database import db
from models import Quotation, QuotationItem, ClientMaster, TenantMaster
from middleware import auth_required
from datetime import datetime
from decimal import Decimal
import io

quotation_bp = Blueprint('quotation', __name__, url_prefix='/quotations')


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_or_404(quotation_id: int) -> "Quotation":
    q = Quotation.query.filter_by(
        quotation_id=quotation_id,
        tenant_id=g.tenant_id,
    ).first()
    if not q:
        abort(404, description='Quotation not found')
    return q


def _item_dict(item: "QuotationItem") -> dict:
    return {
        'item_id':              item.item_id,
        'quotation_id':         item.quotation_id,
        'item_name':            item.item_name,
        'description':          item.description,
        'quantity':             int(item.quantity) if item.quantity is not None else 1,
        'amount':               float(item.amount) if item.amount is not None else 0.0,
        'discounted_amount':    float(item.discounted_amount) if item.discounted_amount is not None else None,
        'discount_type':        item.discount_type,
        'discount_value':       float(item.discount_value) if item.discount_value is not None else 0.0,
        'discount_percent':     float(item.discount_percent) if item.discount_percent is not None else 0.0,
        'pricelist_id':         item.pricelist_id,
        'section':              item.section,
        'source':               item.source,
        'parent_item_id':       item.parent_item_id,
        'width':                item.width,
        'height':               item.height,
        'depth':                item.depth,
        'color':                item.color,
        'created_at':           item.created_at.isoformat() if item.created_at else None,
    }


def _quotation_dict(q: "Quotation", include_items: bool = True) -> dict:
    result = {
        'quotation_id':          q.quotation_id,
        'reference_number':      q.reference_number,
        'tenant_id':             q.tenant_id,
        'client_id':             q.client_id,
        'project_id':            q.project_id,
        'employee_id':           q.employee_id,
        'status':                q.status or 'Draft',
        'total':                 float(q.total) if q.total is not None else 0.0,
        'vat_percentage':        float(q.vat_percentage) if q.vat_percentage is not None else 20.0,
        'global_discount_percent': float(q.global_discount_percent) if q.global_discount_percent is not None else 0.0,
        'notes':                 q.notes,
        'valid_until':           q.valid_until.isoformat() if q.valid_until else None,
        'created_at':            q.created_at.isoformat() if q.created_at else None,
        'updated_at':            q.updated_at.isoformat() if q.updated_at else None,
        # Customer snapshot
        'customer_name':         q.customer_name,
        'customer_address':      q.customer_address,
        'customer_phone':        q.customer_phone,
        'customer_email':        q.customer_email,
        # Interior-design fields
        'room_name':             q.room_name,
        'room_type':             q.room_type,
        'door_type':             q.door_type,
        'door_style':            q.door_style,
        'door_colour':           q.door_colour,
        'carcass_colour':        q.carcass_colour,
        'panelwork_colour':      q.panelwork_colour,
        'filler_type':           q.filler_type,
        'section_discounts':     q.section_discounts or {},
    }

    # Fallback customer_name from client
    if not result['customer_name'] and q.client_id:
        client = ClientMaster.query.get(q.client_id)
        if client:
            result['customer_name'] = (
                client.client_contact_name or
                client.client_company_name or
                f"Client #{client.client_id}"
            )
        result['client_name'] = result['customer_name']

    if include_items:
        result['items'] = [_item_dict(i) for i in q.items.order_by('item_id').all()]

    return result


def _next_reference(tenant_id: str) -> str:
    """Generate next QT-XXXXX reference for this tenant."""
    from sqlalchemy import text
    row = db.session.execute(
        text("""
            SELECT reference_number FROM "StreemLyne_MT"."Quotations"
            WHERE tenant_id = :tid
            ORDER BY quotation_id DESC LIMIT 1
        """),
        {'tid': tenant_id}
    ).fetchone()
    if row and row[0] and row[0].startswith('QT-'):
        try:
            num = int(row[0].split('-')[1]) + 1
            return f"QT-{num:05d}"
        except (ValueError, IndexError):
            pass
    return 'QT-00001'


# ── Routes ────────────────────────────────────────────────────────────────────

@quotation_bp.route('', methods=['GET'])
@auth_required
def list_quotations():
    client_id  = request.args.get('client_id',  type=int)
    project_id = request.args.get('project_id', type=int)
    status     = request.args.get('status')

    query = (
        Quotation.query
        .join(ClientMaster, Quotation.client_id == ClientMaster.client_id)
        .filter(ClientMaster.tenant_id == g.tenant_id)
    )
    if client_id:
        query = query.filter(Quotation.client_id == client_id)
    if project_id:
        query = query.filter(Quotation.project_id == project_id)
    if status:
        query = query.filter(Quotation.status == status)

    quotations = query.order_by(Quotation.created_at.desc()).all()
    return jsonify([_quotation_dict(q, include_items=False) for q in quotations]), 200


@quotation_bp.route('', methods=['POST'])
@auth_required
def create_quotation():
    data = request.get_json() or {}

    if not data.get('client_id'):
        return jsonify({'error': 'client_id is required'}), 400

    # Validate client belongs to tenant
    client = ClientMaster.query.filter_by(
        client_id=data['client_id'], tenant_id=g.tenant_id
    ).first()
    if not client:
        return jsonify({'error': 'Invalid client_id for this tenant'}), 400

    # Auto-snapshot customer details from client
    customer_name    = data.get('customer_name')    or client.client_contact_name or client.client_company_name
    customer_email   = data.get('customer_email')   or client.client_email
    customer_phone   = data.get('customer_phone')   or client.client_phone
    customer_address = data.get('customer_address') or client.address

    q = Quotation(
        tenant_id                = g.tenant_id,
        client_id                = data['client_id'],
        project_id               = data.get('project_id'),
        employee_id              = data.get('employee_id') or getattr(g, 'employee_id', None),
        reference_number         = _next_reference(g.tenant_id),
        status                   = data.get('status', 'Draft'),
        notes                    = data.get('notes'),
        vat_percentage           = Decimal(str(data.get('vat_percentage', 20))),
        global_discount_percent  = Decimal(str(data.get('global_discount_percent', 0))),
        valid_until              = datetime.fromisoformat(data['valid_until']) if data.get('valid_until') else None,
        customer_name            = customer_name,
        customer_email           = customer_email,
        customer_phone           = customer_phone,
        customer_address         = customer_address,
        room_name                = data.get('room_name'),
        room_type                = data.get('room_type', 'Kitchen'),
        door_type                = data.get('door_type', 'Carcass Only'),
        door_style               = data.get('door_style'),
        door_colour              = data.get('door_colour'),
        carcass_colour           = data.get('carcass_colour'),
        panelwork_colour         = data.get('panelwork_colour'),
        filler_type              = data.get('filler_type', 'Basic Slab'),
        section_discounts        = data.get('section_discounts', {}),
    )

    try:
        db.session.add(q)
        db.session.flush()

        items_data = data.get('items') or data.get('details') or []
        sub = Decimal('0')
        for item_data in items_data:
            item = QuotationItem(
                quotation_id   = q.quotation_id,
                item_name      = item_data.get('item_name') or item_data.get('service_name') or '',
                description    = item_data.get('description'),
                quantity       = int(item_data.get('quantity', 1)),
                amount         = Decimal(str(item_data.get('amount', 0))),
                color          = item_data.get('color'),
                pricelist_id   = item_data.get('pricelist_id'),
                section        = item_data.get('section'),
                source         = item_data.get('source', 'manual'),
                discount_type  = item_data.get('discount_type', 'none'),
                discount_value = Decimal(str(item_data.get('discount_value', 0))),
                discount_percent = Decimal(str(item_data.get('discount_percent', 0))),
                parent_item_id = item_data.get('parent_item_id'),
                width          = item_data.get('width'),
                height         = item_data.get('height'),
                depth          = item_data.get('depth'),
            )
            db.session.add(item)
            sub += item.amount * item.quantity

        # Calculate total
        discount_pct = q.global_discount_percent or Decimal('0')
        after_disc   = sub * (1 - discount_pct / 100)
        vat_pct      = q.vat_percentage or Decimal('20')
        q.total      = after_disc * (1 + vat_pct / 100)

        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        return jsonify({'error': 'Invalid reference — check client_id or project_id'}), 409

    return jsonify(_quotation_dict(q, include_items=True)), 201


@quotation_bp.route('/<int:quotation_id>', methods=['GET'])
@auth_required
def get_quotation(quotation_id: int):
    q = _get_or_404(quotation_id)
    return jsonify(_quotation_dict(q, include_items=True)), 200


@quotation_bp.route('/<int:quotation_id>', methods=['PATCH'])
@auth_required
def patch_quotation(quotation_id: int):
    q = _get_or_404(quotation_id)
    data = request.get_json() or {}

    str_fields = ['status', 'notes', 'customer_name', 'customer_address',
                  'customer_phone', 'customer_email', 'room_name', 'room_type',
                  'door_type', 'door_style', 'door_colour', 'carcass_colour',
                  'panelwork_colour', 'filler_type']
    for field in str_fields:
        if field in data:
            setattr(q, field, data[field])

    dec_fields = ['vat_percentage', 'global_discount_percent', 'total']
    for field in dec_fields:
        if field in data and data[field] is not None:
            setattr(q, field, Decimal(str(data[field])))

    if 'valid_until' in data and data['valid_until']:
        q.valid_until = datetime.fromisoformat(data['valid_until'])
    if 'section_discounts' in data:
        q.section_discounts = data['section_discounts']
    if 'project_id' in data:
        q.project_id = data['project_id']

    # If items sent, replace them all
    if 'items' in data or 'details' in data:
        QuotationItem.query.filter_by(quotation_id=quotation_id).delete()
        items_data = data.get('items') or data.get('details') or []
        sub = Decimal('0')
        for item_data in items_data:
            item = QuotationItem(
                quotation_id   = q.quotation_id,
                item_name      = item_data.get('item_name') or item_data.get('service_name') or '',
                description    = item_data.get('description'),
                quantity       = int(item_data.get('quantity', 1)),
                amount         = Decimal(str(item_data.get('amount', 0))),
                color          = item_data.get('color'),
                pricelist_id   = item_data.get('pricelist_id'),
                section        = item_data.get('section'),
                source         = item_data.get('source', 'manual'),
                discount_type  = item_data.get('discount_type', 'none'),
                discount_value = Decimal(str(item_data.get('discount_value', 0))),
                discount_percent = Decimal(str(item_data.get('discount_percent', 0))),
                parent_item_id = item_data.get('parent_item_id'),
                width          = item_data.get('width'),
                height         = item_data.get('height'),
                depth          = item_data.get('depth'),
            )
            db.session.add(item)
            sub += item.amount * item.quantity

        # Recalculate total
        discount_pct = q.global_discount_percent or Decimal('0')
        after_disc   = sub * (1 - discount_pct / 100)
        vat_pct      = q.vat_percentage or Decimal('20')
        q.total      = after_disc * (1 + vat_pct / 100)

    q.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid foreign key reference'}), 409

    return jsonify(_quotation_dict(q, include_items=True)), 200


@quotation_bp.route('/<int:quotation_id>', methods=['PUT'])
@auth_required
def update_quotation(quotation_id: int):
    """Alias PUT → PATCH for frontend compatibility."""
    return patch_quotation(quotation_id)


@quotation_bp.route('/<int:quotation_id>', methods=['DELETE'])
@auth_required
def delete_quotation(quotation_id: int):
    q = _get_or_404(quotation_id)
    try:
        db.session.delete(q)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Cannot delete — quotation is referenced by an invoice'}), 409
    return jsonify({'message': 'Quotation deleted'}), 200


@quotation_bp.route('/<int:quotation_id>/items', methods=['GET'])
@auth_required
def list_items(quotation_id: int):
    _get_or_404(quotation_id)
    items = QuotationItem.query.filter_by(quotation_id=quotation_id).all()
    return jsonify([_item_dict(i) for i in items]), 200


@quotation_bp.route('/<int:quotation_id>/items', methods=['POST'])
@auth_required
def add_item(quotation_id: int):
    q = _get_or_404(quotation_id)
    data = request.get_json() or {}
    if not data.get('item_name'):
        return jsonify({'error': 'item_name is required'}), 400
    item = QuotationItem(
        quotation_id  = quotation_id,
        item_name     = data['item_name'],
        description   = data.get('description'),
        quantity      = int(data.get('quantity', 1)),
        amount        = Decimal(str(data.get('amount', 0))),
        section       = data.get('section'),
        source        = data.get('source', 'manual'),
        discount_type = data.get('discount_type', 'none'),
        discount_value = Decimal(str(data.get('discount_value', 0))),
    )
    db.session.add(item)
    db.session.commit()
    return jsonify(_item_dict(item)), 201


@quotation_bp.route('/<int:quotation_id>/items/<int:item_id>', methods=['PATCH'])
@auth_required
def update_item(quotation_id: int, item_id: int):
    _get_or_404(quotation_id)
    item = QuotationItem.query.filter_by(item_id=item_id, quotation_id=quotation_id).first()
    if not item:
        abort(404, description='Item not found')
    data = request.get_json() or {}
    for field in ['item_name', 'description', 'color', 'section', 'source',
                  'discount_type', 'width', 'height', 'depth']:
        if field in data:
            setattr(item, field, data[field])
    for field in ['quantity']:
        if field in data:
            setattr(item, field, int(data[field]))
    for field in ['amount', 'discount_value', 'discount_percent', 'discounted_amount']:
        if field in data and data[field] is not None:
            setattr(item, field, Decimal(str(data[field])))
    db.session.commit()
    return jsonify(_item_dict(item)), 200


@quotation_bp.route('/<int:quotation_id>/items/<int:item_id>', methods=['DELETE'])
@auth_required
def delete_item(quotation_id: int, item_id: int):
    _get_or_404(quotation_id)
    item = QuotationItem.query.filter_by(item_id=item_id, quotation_id=quotation_id).first()
    if not item:
        abort(404, description='Item not found')
    db.session.delete(item)
    db.session.commit()
    return jsonify({'message': 'Item deleted'}), 200


@quotation_bp.route('/<int:quotation_id>/pdf', methods=['GET'])
@auth_required
def download_quotation_pdf(quotation_id: int):
    from fpdf import FPDF
    q       = _get_or_404(quotation_id)
    client  = ClientMaster.query.get(q.client_id) if q.client_id else None
    tenant  = TenantMaster.query.filter_by(tenant_id=str(g.tenant_id)).first()
    items   = q.items.order_by('item_id').all()

    company_name    = (tenant.tenant_company_name if tenant else None) or 'StreemLyne'
    logo_url        = tenant.logo_url if tenant else None
    company_email   = tenant.company_email if tenant else None
    company_phone   = tenant.company_phone if tenant else None
    company_address = tenant.company_address if tenant else None
    vat_rate        = float(q.vat_percentage or 20)
    currency_symbol = '£'

    customer_name = (
        q.customer_name or
        (client.client_contact_name if client else None) or
        (client.client_company_name if client else None) or 'N/A'
    )

    total     = float(q.total or 0)
    sub_total = sum(float(i.amount or 0) * int(i.quantity or 1) for i in items)
    disc_pct  = float(q.global_discount_percent or 0)
    disc_amt  = sub_total * disc_pct / 100
    after     = sub_total - disc_amt
    vat_amt   = after * vat_rate / 100

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)

    # Header bar
    pdf.set_fill_color(30, 30, 30)
    pdf.rect(0, 0, 210, 32, 'F')

    logo_rendered = False
    if logo_url:
        try:
            import requests as _req, tempfile, os as _os
            suffix = '.png' if 'png' in logo_url.lower() else '.jpg'
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(_req.get(logo_url, timeout=5).content)
                tmp_path = tmp.name
            pdf.image(tmp_path, x=8, y=4, h=22)
            _os.unlink(tmp_path)
            logo_rendered = True
        except Exception as e:
            print(f'[PDF] Logo failed: {e}')

    pdf.set_text_color(255, 255, 255)
    pdf.set_font('Helvetica', 'B', 13)
    pdf.set_xy(36 if logo_rendered else 8, 7)
    pdf.cell(80, 8, company_name)
    pdf.set_font('Helvetica', 'B', 16)
    pdf.set_xy(140, 5)
    pdf.cell(0, 8, 'QUOTE')
    pdf.set_font('Helvetica', '', 9)
    pdf.set_xy(140, 14)
    pdf.cell(0, 5, f'#{q.reference_number}')
    pdf.set_xy(140, 19)
    pdf.cell(0, 5, q.created_at.strftime('%d %b %Y') if q.created_at else '')
    pdf.set_text_color(0, 0, 0)
    pdf.set_xy(15, 38)

    # Bill to / details
    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(85, 6, 'BILL TO', ln=False, fill=True)
    pdf.cell(10, 6, '', ln=False)
    pdf.cell(85, 6, 'QUOTE DETAILS', ln=True, fill=True)
    pdf.set_font('Helvetica', '', 9)
    left_lines  = [customer_name, q.customer_address or '', q.customer_phone or '', q.customer_email or '']
    right_lines = [
        f'Ref: {q.reference_number}',
        f'Status: {q.status or "Draft"}',
        f'VAT: {vat_rate}%',
    ]
    if q.valid_until:
        right_lines.append(f'Valid until: {q.valid_until.strftime("%d %b %Y")}')
    for i in range(max(len(left_lines), len(right_lines))):
        pdf.set_x(15)
        pdf.cell(85, 5, left_lines[i] if i < len(left_lines) else '')
        pdf.cell(10, 5, '')
        pdf.cell(85, 5, right_lines[i] if i < len(right_lines) else '', ln=True)
    pdf.ln(6)

    # Items table
    pdf.set_fill_color(30, 30, 30)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font('Helvetica', 'B', 9)
    pdf.cell(80, 7, 'Description', fill=True)
    pdf.cell(25, 7, 'Qty', fill=True, align='C')
    pdf.cell(40, 7, f'Unit Price ({currency_symbol})', fill=True, align='R')
    pdf.cell(30, 7, f'Amount ({currency_symbol})', fill=True, align='R', ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font('Helvetica', '', 9)
    fill = False
    for item in items:
        pdf.set_fill_color(248, 248, 248) if fill else pdf.set_fill_color(255, 255, 255)
        qty        = int(item.quantity or 1)
        unit_price = float(item.amount or 0)
        line_total = qty * unit_price
        x, y = pdf.get_x(), pdf.get_y()
        pdf.multi_cell(80, 6, item.item_name or '', fill=fill)
        row_h = pdf.get_y() - y
        pdf.set_xy(x + 80, y)
        pdf.cell(25, row_h, str(qty),                             align='C', fill=fill)
        pdf.cell(40, row_h, f'{currency_symbol}{unit_price:,.2f}', align='R', fill=fill)
        pdf.cell(30, row_h, f'{currency_symbol}{line_total:,.2f}', align='R', fill=fill, ln=True)
        fill = not fill

    pdf.ln(4)

    # Totals
    def row(label, value, bold=False):
        pdf.set_font('Helvetica', 'B' if bold else '', 9 if not bold else 10)
        pdf.set_x(120)
        pdf.cell(45, 6, label, align='R')
        pdf.cell(25, 6, value, align='R', ln=True)

    row('Subtotal:', f'{currency_symbol}{sub_total:,.2f}')
    if disc_amt:
        row('Discount:', f'-{currency_symbol}{disc_amt:,.2f}')
    row(f'VAT ({vat_rate}%):', f'{currency_symbol}{vat_amt:,.2f}')
    pdf.set_x(120)
    pdf.cell(70, 0.5, '', ln=True, border='T')
    row('TOTAL:', f'{currency_symbol}{total:,.2f}', bold=True)

    if q.notes:
        pdf.ln(6)
        pdf.set_font('Helvetica', 'B', 9)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(0, 6, 'NOTES', fill=True, ln=True)
        pdf.set_font('Helvetica', '', 9)
        pdf.multi_cell(0, 5, q.notes)

    # Footer
    pdf.set_y(-20)
    pdf.set_font('Helvetica', 'I', 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, 'Thank you for your business.', align='C', ln=True)

    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)
    filename = f'{q.reference_number}.pdf'
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=filename)