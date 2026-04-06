#C:\streemlyne_crm_backend\backend\routes\invoice_routes.py
"""
Invoice Routes
Handles: Invoice_Master, Invoice_Details

Schema alignment (StreemLyne_MT):
  Invoice_Master:
    invoice_id (PK), client_id (FK→Client_Master, nullable),
    project_id (FK→Project_Details, nullable),
    proposal_id (FK→Proposal_Master, nullable),
    invoice_number (NOT NULL, should be unique), billing_remarks,
    sub_total (real), vat (real), other_taxes (real),
    currency_id (FK→Currency_Master), tax_id (NOT NULL),
    total_amount (real, NOT NULL), discount_percent, discount_amount,
    payment_status (text, default='Not Paid'),
    created_at, updated_at

  Invoice_Details:
    invoice_details_id (PK), invoice_id (FK→Invoice_Master, NOT NULL),
    service_id (FK→Services_Master, nullable)
    service_name (text, nullable)
    unit_price   (real, nullable)
    quantity (real, nullable, default=1), uom_id (FK→UOM_Master, nullable),
    created_at, updated_at

Tenant scoping:
  Invoice_Master has no tenant_id column. Scoping is done via:
    - client_id  → Client_Master.tenant_id  (when client_id is set)
    - project_id → Project_Details.client_id → Client_Master.tenant_id  (fallback)

Invoice numbering:
  Format : INV-NNN  (e.g. INV-001, INV-042, INV-110, INV-1000)
  Scoping: sequential counter is per-tenant
  Source : GET /api/invoices/next-number  (atomic MAX+1 query)
"""

import re

from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from database import db
from models import InvoiceMaster, InvoiceDetails, ClientMaster, ProjectDetails
from middleware import auth_required
from datetime import datetime
from sqlalchemy import func

invoice_bp = Blueprint('invoice', __name__, url_prefix='/api/invoices')

_INVOICE_NUMBER_RE = re.compile(r'^INV-(\d+)$')


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

def _tenant_client_ids_subquery(tenant_id: int):
    return (
        db.session.query(ClientMaster.client_id)
        .filter(ClientMaster.tenant_id == tenant_id)
        .subquery()
    )


def _tenant_project_ids_subquery(tenant_id: int):
    return (
        db.session.query(ProjectDetails.project_id)
        .join(ClientMaster, ProjectDetails.client_id == ClientMaster.client_id)
        .filter(ClientMaster.tenant_id == tenant_id)
        .subquery()
    )


def _tenant_invoice_filter(tenant_id: int):
    """Return a SQLAlchemy filter expression that scopes invoices to a tenant."""
    return or_(
        InvoiceMaster.client_id.in_(_tenant_client_ids_subquery(tenant_id)),
        InvoiceMaster.project_id.in_(_tenant_project_ids_subquery(tenant_id)),
    )


def _get_or_404(invoice_id: int) -> InvoiceMaster:
    invoice = InvoiceMaster.query.filter(
        InvoiceMaster.invoice_id == invoice_id,
        _tenant_invoice_filter(g.tenant_id),
    ).first()
    if not invoice:
        abort(404, description='Invoice not found')
    return invoice

# ─────────────────────────────────────────
# Invoice number generation
# ─────────────────────────────────────────

def _next_invoice_number_for_tenant(tenant_id: int) -> str:
    """
    Atomically compute the next INV-NNN number for a given tenant.
    Runs inside the caller's transaction — no separate commit needed.
    """
    existing_numbers = (
        db.session.query(InvoiceMaster.invoice_number)
        .filter(_tenant_invoice_filter(tenant_id))
        .all()
    )

    max_sequence = 0
    for (number,) in existing_numbers:
        if number:
            match = _INVOICE_NUMBER_RE.match(number)
            if match:
                max_sequence = max(max_sequence, int(match.group(1)))

    return f"INV-{str(max_sequence + 1).zfill(3)}"


@invoice_bp.route('/next-number', methods=['GET'])
@auth_required
def get_next_invoice_number():
    """
    GET /api/invoices/next-number
    Response: { "invoice_number": "INV-007" }

    Read-only — does not reserve the number. The uniqueness constraint on
    invoice_number is the final guard; a 409 on POST means re-fetch and retry.
    """
    number = _next_invoice_number_for_tenant(g.tenant_id)
    return jsonify({'invoice_number': number}), 200


# ─────────────────────────────────────────
# Invoices – CRUD
# ─────────────────────────────────────────

@invoice_bp.route('', methods=['GET'])
@auth_required
def list_invoices():
    query = InvoiceMaster.query.filter(_tenant_invoice_filter(g.tenant_id))
    invoices = query.order_by(InvoiceMaster.created_at.desc()).all()

    invoice_ids = [i.invoice_id for i in invoices]

    details_map = {}

    if invoice_ids:
        # 🔹 Summary aggregation
        rows = (
            db.session.query(
                InvoiceDetails.invoice_id,
                func.string_agg(InvoiceDetails.service_name, ', ').label("summary"),
            )
            .filter(InvoiceDetails.invoice_id.in_(invoice_ids))
            .group_by(InvoiceDetails.invoice_id)
            .all()
        )

        for r in rows:
            details_map[r.invoice_id] = {
                "summary_description": r.summary or "",
            }

        # 🔹 First service name (correct order)
        first_rows = (
            db.session.query(InvoiceDetails)
            .filter(InvoiceDetails.invoice_id.in_(invoice_ids))
            .order_by(InvoiceDetails.invoice_id, InvoiceDetails.invoice_details_id)
            .all()
        )

        for d in first_rows:
            if d.invoice_id not in details_map:
                details_map[d.invoice_id] = {}

            if "first_service_name" not in details_map[d.invoice_id]:
                details_map[d.invoice_id]["first_service_name"] = d.service_name or ""

    # 🔥 FINAL RESPONSE BUILD (YOU WERE MISSING THIS)
    result = []

    for i in invoices:
        data = _invoice_dict(i, include_details=False)

        agg = details_map.get(i.invoice_id, {})

        data["summary_description"] = agg.get("summary_description", "")
        data["first_service_name"] = agg.get("first_service_name", "")

        result.append(data)

    return jsonify(result), 200

@invoice_bp.route('', methods=['POST'])
@auth_required
def create_invoice():
    """
    POST /api/invoices
    Body:
    {
        "invoice_number": "INV-007",    (required)
        "tax_id": 1,                    (required)
        "total_amount": 600.00,         (required)
        "client_id": 5,
        "project_id": 8,
        "proposal_id": 2,
        "billing_remarks": "Net 30",
        "currency_id": 1,
        "sub_total": 500.00,
        "vat": 100.00,                  (VAT amount in currency)
        "other_taxes": 0.00,            (other taxes total in currency)
        "payment_status": "Not Paid",
        "discount_percent": 0.0,
        "discount_amount": 0.0,
        "details": [
            {
                "service_name": "Supply and fit carpet",
                "unit_price": 500.00,
                "quantity": 1,
                "uom_id": 1
            }
        ]
    }
    """
    data = request.get_json() or {}

    required = ['invoice_number', 'tax_id', 'total_amount']
    missing = [f for f in required if data.get(f) is None]
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400

    client_id = data.get('client_id')
    if client_id:
        client = ClientMaster.query.filter_by(client_id=client_id, tenant_id=g.tenant_id).first()
        if not client:
            return jsonify({'error': 'Invalid client_id — not found for this tenant'}), 400

    project_id = data.get('project_id')
    if project_id:
        project = (
            ProjectDetails.query
            .join(ClientMaster, ProjectDetails.client_id == ClientMaster.client_id)
            .filter(ProjectDetails.project_id == project_id, ClientMaster.tenant_id == g.tenant_id)
            .first()
        )
        if not project:
            return jsonify({'error': 'Invalid project_id — not found for this tenant'}), 400

    for idx, item in enumerate(data.get('details', [])):
        if not item.get('service_name') and not item.get('description'):
            return jsonify({
                'error': f'Detail line {idx + 1} requires service_name or description'
            }), 400

    invoice = InvoiceMaster(
        client_id=client_id,
        project_id=project_id,
        proposal_id=data.get('proposal_id'),
        invoice_number=data['invoice_number'],
        billing_remarks=data.get('billing_remarks'),
        tax_id=data['tax_id'],
        currency_id=data.get('currency_id'),
        sub_total=data.get('sub_total'),
        # ── VAT & other taxes are now persisted ──────────────────────────────
        vat=float(data['vat']) if data.get('vat') is not None else 0.0,
        other_taxes=float(data['other_taxes']) if data.get('other_taxes') is not None else 0.0,
        # ─────────────────────────────────────────────────────────────────────
        total_amount=float(data['total_amount']),
        discount_percent=data.get('discount_percent'),
        discount_amount=data.get('discount_amount'),
        payment_status=data.get('payment_status', 'Not Paid'),
    )
    
    # Validate payment_status if provided
    valid_payment_statuses = ['Not Paid', 'Paid', 'Partial', 'Overdue']
    if data.get('payment_status') and data['payment_status'] not in valid_payment_statuses:
        return jsonify({'error': f"Invalid payment_status. Must be one of: {', '.join(valid_payment_statuses)}"}), 400

    try:
        db.session.add(invoice)
        db.session.flush()

        for item in data.get('details', []):
            service_name = item.get('service_name') or item.get('description')
            unit_price_raw = item.get('unit_price') if item.get('unit_price') is not None else item.get('amount')
            unit_price = float(unit_price_raw) if unit_price_raw is not None else None
            quantity = float(item['quantity']) if item.get('quantity') is not None else 1.0

            detail = InvoiceDetails(
                invoice_id=invoice.invoice_id,
                service_id=item.get('service_id'),
                service_name=service_name,
                unit_price=unit_price,
                quantity=quantity,
                uom_id=item.get('uom_id'),
            )
            db.session.add(detail)

        db.session.commit()

    except IntegrityError as e:
        db.session.rollback()
        if 'invoice_number' in str(e.orig).lower():
            return jsonify({'error': 'Invoice number already exists — fetch a new number and retry'}), 409
        return jsonify({'error': 'Invalid foreign key reference — check proposal_id, service_id, or uom_id'}), 409

    return jsonify(_invoice_dict(invoice, include_details=True)), 201


@invoice_bp.route('/<int:invoice_id>', methods=['GET'])
@auth_required
def get_invoice(invoice_id: int):
    invoice = _get_or_404(invoice_id)
    return jsonify(_invoice_dict(invoice, include_details=True)), 200


@invoice_bp.route('/<int:invoice_id>', methods=['PUT'])
@auth_required
def update_invoice(invoice_id: int):
    invoice = _get_or_404(invoice_id)
    data = request.get_json() or {}

    scalar_fields = [
        'billing_remarks', 'tax_id', 'currency_id',
        'sub_total', 'total_amount', 'discount_percent', 'discount_amount',
        # ── previously missing fields ────────────────────────────────────────
        'vat', 'other_taxes', 'payment_status',
        # ─────────────────────────────────────────────────────────────────────
    ]
    for field in scalar_fields:
        if field in data:
            setattr(invoice, field, data[field])
    
    # Validate payment_status if provided
    if 'payment_status' in data:
        valid_payment_statuses = ['Not Paid', 'Paid', 'Partial', 'Overdue']
        if data['payment_status'] not in valid_payment_statuses:
            return jsonify({'error': f"Invalid payment_status. Must be one of: {', '.join(valid_payment_statuses)}"}), 400

    if 'invoice_number' in data and data['invoice_number'] != invoice.invoice_number:
        conflict = InvoiceMaster.query.filter(
            InvoiceMaster.invoice_number == data['invoice_number'],
            InvoiceMaster.invoice_id != invoice_id,
            _tenant_invoice_filter(g.tenant_id),
        ).first()
        if conflict:
            return jsonify({'error': 'Invoice number already in use'}), 409
        invoice.invoice_number = data['invoice_number']

    invoice.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid foreign key reference'}), 409

    return jsonify({'message': 'Invoice updated', 'invoice': _invoice_dict(invoice, include_details=True)}), 200


@invoice_bp.route('/<int:invoice_id>', methods=['DELETE'])
@auth_required
def delete_invoice(invoice_id: int):
    invoice = _get_or_404(invoice_id)
    try:
        db.session.delete(invoice)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Cannot delete invoice — it is referenced by other records'}), 409
    return jsonify({'message': 'Invoice deleted'}), 200


# ─────────────────────────────────────────
# Invoice Detail Lines – sub-resource
# ─────────────────────────────────────────

@invoice_bp.route('/<int:invoice_id>/details', methods=['GET'])
@auth_required
def list_detail_lines(invoice_id: int):
    _get_or_404(invoice_id)
    details = InvoiceDetails.query.filter_by(invoice_id=invoice_id).all()
    return jsonify([_detail_dict(d) for d in details]), 200


@invoice_bp.route('/<int:invoice_id>/details', methods=['POST'])
@auth_required
def add_detail_line(invoice_id: int):
    """
    POST /api/invoices/<invoice_id>/details
    Body: { service_name, unit_price, quantity, uom_id, service_id }
    """
    _get_or_404(invoice_id)
    data = request.get_json() or {}

    service_name = data.get('service_name') or data.get('description') or None
    if not service_name and not data.get('service_id'):
        return jsonify({'error': 'Detail line requires service_name or service_id'}), 400

    unit_price_raw = data.get('unit_price') if data.get('unit_price') is not None else data.get('amount')
    unit_price = float(unit_price_raw) if unit_price_raw is not None else None
    quantity = float(data['quantity']) if data.get('quantity') is not None else 1.0

    detail = InvoiceDetails(
        invoice_id=invoice_id,
        service_id=data.get('service_id'),
        service_name=service_name,
        unit_price=unit_price,
        quantity=quantity,
        uom_id=data.get('uom_id'),
    )

    try:
        db.session.add(detail)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid service_id or uom_id'}), 409

    return jsonify({'message': 'Detail line added', 'detail': _detail_dict(detail)}), 201


@invoice_bp.route('/<int:invoice_id>/details/<int:detail_id>', methods=['PUT'])
@auth_required
def update_detail_line(invoice_id: int, detail_id: int):
    _get_or_404(invoice_id)
    detail = InvoiceDetails.query.filter_by(
        invoice_details_id=detail_id, invoice_id=invoice_id
    ).first()
    if not detail:
        abort(404, description='Detail line not found')

    data = request.get_json() or {}
    for field in ['service_id', 'quantity', 'uom_id', 'service_name', 'unit_price']:
        if field in data:
            setattr(detail, field, data[field])

    if 'description' in data and 'service_name' not in data:
        detail.service_name = data['description']
    if 'amount' in data and 'unit_price' not in data:
        detail.unit_price = float(data['amount'])

    if detail.quantity is None:
        detail.quantity = 1.0

    detail.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid service_id or uom_id'}), 409

    return jsonify({'message': 'Detail line updated', 'detail': _detail_dict(detail)}), 200


@invoice_bp.route('/<int:invoice_id>/details/<int:detail_id>', methods=['DELETE'])
@auth_required
def remove_detail_line(invoice_id: int, detail_id: int):
    _get_or_404(invoice_id)
    detail = InvoiceDetails.query.filter_by(
        invoice_details_id=detail_id, invoice_id=invoice_id
    ).first()
    if not detail:
        abort(404, description='Detail line not found')
    db.session.delete(detail)
    db.session.commit()
    return jsonify({'message': 'Detail line removed'}), 200


# ─────────────────────────────────────────
# Serialisers
# ─────────────────────────────────────────


def _invoice_dict(i: InvoiceMaster, include_details: bool = True) -> dict:
    result = {
        'invoice_id':       i.invoice_id,
        'client_id':        i.client_id,
        'project_id':       i.project_id,
        'proposal_id':      i.proposal_id,
        'invoice_number':   i.invoice_number,
        'billing_remarks':  i.billing_remarks,
        'tax_id':           i.tax_id,
        'currency_id':      i.currency_id,
        'sub_total':        i.sub_total,
        'vat':              float(i.vat) if i.vat is not None else 0.0,
        'other_taxes':      float(i.other_taxes) if i.other_taxes is not None else 0.0,
        'total_amount':     i.total_amount,
        'discount_percent': i.discount_percent,
        'discount_amount':  i.discount_amount,
        'payment_status':   i.payment_status or 'Not Paid',
        'created_at':       i.created_at.isoformat() if i.created_at else None,
        'updated_at':       i.updated_at.isoformat() if i.updated_at else None,
    }

    # ── Customer Name ─────────────────────────────────────────────
    if i.client_id:
        client = ClientMaster.query.get(i.client_id)
        if client:
            result['customer_name'] = (
                client.client_contact_name
                or client.client_company_name
                or f"Client #{client.client_id}"
            )

    if include_details:
        result['details'] = [
            _detail_dict(d)
            for d in InvoiceDetails.query
            .options(db.joinedload(InvoiceDetails.service))
            .filter_by(invoice_id=i.invoice_id).all()
        ]

    return result


def _detail_dict(d: InvoiceDetails) -> dict:
    display_name = d.service_name or (d.service.service_title if d.service else None)

    if d.unit_price is not None:
        line_total = d.unit_price * (d.quantity or 1)
    elif d.service and d.service.service_rate is not None:
        line_total = d.service.service_rate * (d.quantity or 1)
    else:
        line_total = 0.0

    return {
        'invoice_details_id': d.invoice_details_id,
        'invoice_id':         d.invoice_id,
        'service_id':         d.service_id,
        'service_name':       display_name,
        'service_title':      d.service.service_title if d.service else None,
        'unit_price':         d.unit_price,
        'service_rate':       d.service.service_rate if d.service else None,
        'line_total':         line_total,
        'created_at':         d.created_at.isoformat() if d.created_at else None,
        'updated_at':         d.updated_at.isoformat() if d.updated_at else None,
    }