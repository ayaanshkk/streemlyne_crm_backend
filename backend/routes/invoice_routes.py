"""
Invoice Routes
Handles: Invoice_Master, Invoice_Details

Schema alignment (StreemLyne_MT):
  Invoice_Master:
    invoice_id (PK), client_id (FK→Client_Master, nullable),
    project_id (FK→Project_Details, nullable),
    proposal_id (FK→Proposal_Master, nullable),
    invoice_number (NOT NULL, should be unique), billing_remarks,
    sub_total (real), currency_id (FK→Currency_Master), tax_id (NOT NULL),
    total_amount (real, NOT NULL), discount_percent, discount_amount,
    created_at, updated_at

  Invoice_Details:
    invoice_details_id (PK), invoice_id (FK→Invoice_Master, NOT NULL),
    service_id (FK→Services_Master, NOT NULL),
    quantity (real, NOT NULL), uom_id (FK→UOM_Master, NOT NULL),
    created_at, updated_at

Tenant scoping:
  Invoice_Master has no tenant_id column. Scoping is done via:
    - client_id  → Client_Master.tenant_id  (when client_id is set)
    - project_id → Project_Details.client_id → Client_Master.tenant_id  (fallback)
  Both paths are checked together so invoices with only a project_id (no client_id)
  are still correctly isolated.
"""

from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from database import db
from models import InvoiceMaster, InvoiceDetails, ClientMaster, ProjectDetails
from middleware import auth_required, permission_required
from datetime import datetime

invoice_bp = Blueprint('invoice', __name__, url_prefix='/api/invoices')


# ─────────────────────────────────────────
# Invoices – CRUD
# ─────────────────────────────────────────

@invoice_bp.route('', methods=['GET'])
@auth_required
def list_invoices():
    """
    List invoices scoped to the current tenant.
    GET /api/invoices
    Query params: client_id, project_id, proposal_id

    Tenant isolation: Invoice_Master has no tenant_id. Scope via:
      client_id IN (Client_Master where tenant_id = g.tenant_id)
      OR project_id IN (Project_Details joined to Client_Master where tenant_id = g.tenant_id)
    """
    # Subquery: client_ids that belong to the current tenant
    tenant_client_ids = (
        db.session.query(ClientMaster.client_id)
        .filter(ClientMaster.tenant_id == g.tenant_id)
        .subquery()
    )

    # Subquery: project_ids whose client belongs to the current tenant
    tenant_project_ids = (
        db.session.query(ProjectDetails.project_id)
        .join(ClientMaster, ProjectDetails.client_id == ClientMaster.client_id)
        .filter(ClientMaster.tenant_id == g.tenant_id)
        .subquery()
    )

    query = InvoiceMaster.query.filter(
        or_(
            InvoiceMaster.client_id.in_(tenant_client_ids),
            InvoiceMaster.project_id.in_(tenant_project_ids),
        )
    )

    client_id   = request.args.get('client_id',   type=int)
    project_id  = request.args.get('project_id',  type=int)
    proposal_id = request.args.get('proposal_id', type=int)

    if client_id:
        query = query.filter(InvoiceMaster.client_id == client_id)
    if project_id:
        query = query.filter(InvoiceMaster.project_id == project_id)
    if proposal_id:
        query = query.filter(InvoiceMaster.proposal_id == proposal_id)

    invoices = query.order_by(InvoiceMaster.created_at.desc()).all()
    return jsonify([_invoice_dict(i, include_details=False) for i in invoices]), 200


@invoice_bp.route('', methods=['POST'])
@auth_required
# @permission_required('invoice.create')
def create_invoice():
    """
    Create a new invoice with optional line items.
    POST /api/invoices
    Body:
    {
        "invoice_number": "INV-2025-001",  (required, must be unique within tenant)
        "tax_id": 1,                        (required)
        "total_amount": 10000.00,           (required)
        "client_id": 5,                     (optional FK → Client_Master — must belong to tenant)
        "project_id": 8,                    (optional FK → Project_Details — must belong to tenant)
        "proposal_id": 2,                   (optional FK → Proposal_Master)
        "billing_remarks": "Net 30",
        "currency_id": 1,
        "sub_total": 10000.00,
        "discount_percent": 0.0,
        "discount_amount": 0.0,
        "details": [
            { "service_id": 2, "quantity": 10.0, "uom_id": 3 }
        ]
    }
    """
    data = request.get_json() or {}

    required = ['invoice_number', 'tax_id', 'total_amount']
    missing = [f for f in required if data.get(f) is None]
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400

    # Validate FK ownership — client_id must belong to current tenant
    client_id = data.get('client_id')
    if client_id:
        client = (
            ClientMaster.query
            .filter_by(client_id=client_id, tenant_id=g.tenant_id)
            .first()
        )
        if not client:
            return jsonify({'error': 'Invalid client_id — not found for this tenant'}), 400

    # Validate FK ownership — project_id must belong to current tenant (via Client_Master)
    project_id = data.get('project_id')
    if project_id:
        project = (
            ProjectDetails.query
            .join(ClientMaster, ProjectDetails.client_id == ClientMaster.client_id)
            .filter(
                ProjectDetails.project_id == project_id,
                ClientMaster.tenant_id == g.tenant_id,
            )
            .first()
        )
        if not project:
            return jsonify({'error': 'Invalid project_id — not found for this tenant'}), 400

    # Validate detail lines before writing anything
    for idx, item in enumerate(data.get('details', [])):
        if not item.get('service_id') or item.get('quantity') is None or not item.get('uom_id'):
            return jsonify({
                'error': f'Detail line {idx + 1} requires service_id, quantity, and uom_id'
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
        total_amount=float(data['total_amount']),
        discount_percent=data.get('discount_percent'),
        discount_amount=data.get('discount_amount')
    )

    try:
        db.session.add(invoice)
        db.session.flush()   # get invoice_id before inserting details

        for item in data.get('details', []):
            detail = InvoiceDetails(
                invoice_id=invoice.invoice_id,
                service_id=item['service_id'],
                quantity=float(item['quantity']),
                uom_id=item['uom_id']
            )
            db.session.add(detail)

        db.session.commit()

    except IntegrityError as e:
        db.session.rollback()
        if 'invoice_number' in str(e.orig).lower():
            return jsonify({'error': 'Invoice number already exists'}), 409
        return jsonify({'error': 'Invalid foreign key reference — check proposal_id, service_id, or uom_id'}), 409

    return jsonify(_invoice_dict(invoice, include_details=True)), 201


@invoice_bp.route('/<int:invoice_id>', methods=['GET'])
@auth_required
def get_invoice(invoice_id: int):
    """
    Retrieve a single invoice with its line items.
    GET /api/invoices/<invoice_id>
    """
    invoice = _get_or_404(invoice_id)
    return jsonify(_invoice_dict(invoice, include_details=True)), 200


@invoice_bp.route('/<int:invoice_id>', methods=['PUT'])
@auth_required
# @permission_required('invoice.update')
def update_invoice(invoice_id: int):
    """
    Update invoice header fields.
    PUT /api/invoices/<invoice_id>
    Detail lines are managed via the /details sub-resource.
    """
    invoice = _get_or_404(invoice_id)
    data = request.get_json() or {}

    scalar_fields = [
        'billing_remarks', 'tax_id', 'currency_id',
        'sub_total', 'total_amount', 'discount_percent', 'discount_amount'
    ]
    for field in scalar_fields:
        if field in data:
            setattr(invoice, field, data[field])

    if 'invoice_number' in data and data['invoice_number'] != invoice.invoice_number:
        # Uniqueness check scoped to current tenant — prevents cross-tenant false collisions
        tenant_client_ids = (
            db.session.query(ClientMaster.client_id)
            .filter(ClientMaster.tenant_id == g.tenant_id)
            .subquery()
        )
        tenant_project_ids = (
            db.session.query(ProjectDetails.project_id)
            .join(ClientMaster, ProjectDetails.client_id == ClientMaster.client_id)
            .filter(ClientMaster.tenant_id == g.tenant_id)
            .subquery()
        )
        conflict = InvoiceMaster.query.filter(
            InvoiceMaster.invoice_number == data['invoice_number'],
            InvoiceMaster.invoice_id != invoice_id,
            or_(
                InvoiceMaster.client_id.in_(tenant_client_ids),
                InvoiceMaster.project_id.in_(tenant_project_ids),
            )
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
# @permission_required('invoice.delete')
def delete_invoice(invoice_id: int):
    """
    Delete an invoice and all its line items.
    DELETE /api/invoices/<invoice_id>
    Line items are removed via DB cascade on invoice_id FK.
    """
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
    """
    List line items for an invoice.
    GET /api/invoices/<invoice_id>/details
    """
    _get_or_404(invoice_id)
    details = InvoiceDetails.query.filter_by(invoice_id=invoice_id).all()
    return jsonify([_detail_dict(d) for d in details]), 200


@invoice_bp.route('/<int:invoice_id>/details', methods=['POST'])
@auth_required
# @permission_required('invoice.update')
def add_detail_line(invoice_id: int):
    """
    Add a line item to an existing invoice.
    POST /api/invoices/<invoice_id>/details
    Body: { "service_id": 3, "quantity": 5.0, "uom_id": 2 }
    """
    _get_or_404(invoice_id)
    data = request.get_json() or {}

    required = ['service_id', 'quantity', 'uom_id']
    missing = [f for f in required if data.get(f) is None]
    if missing:
        return jsonify({'error': f'Missing fields: {", ".join(missing)}'}), 400

    detail = InvoiceDetails(
        invoice_id=invoice_id,
        service_id=data['service_id'],
        quantity=float(data['quantity']),
        uom_id=data['uom_id']
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


@invoice_bp.route('/<int:invoice_id>/details/<int:detail_id>', methods=['PUT'])
@auth_required
# @permission_required('invoice.update')
def update_detail_line(invoice_id: int, detail_id: int):
    """
    Update a line item.
    PUT /api/invoices/<invoice_id>/details/<detail_id>
    Body: { "quantity": 7.0, "uom_id": 2, "service_id": 4 }
    """
    _get_or_404(invoice_id)
    detail = InvoiceDetails.query.filter_by(
        invoice_details_id=detail_id, invoice_id=invoice_id
    ).first()
    if not detail:
        abort(404, description='Detail line not found')

    data = request.get_json() or {}
    for field in ['service_id', 'quantity', 'uom_id']:
        if field in data:
            setattr(detail, field, data[field])

    detail.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid service_id or uom_id'}), 409

    return jsonify({'message': 'Detail line updated', 'detail': _detail_dict(detail)}), 200


@invoice_bp.route('/<int:invoice_id>/details/<int:detail_id>', methods=['DELETE'])
@auth_required
# @permission_required('invoice.update')
def remove_detail_line(invoice_id: int, detail_id: int):
    """
    Remove a line item from an invoice.
    DELETE /api/invoices/<invoice_id>/details/<detail_id>
    """
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
# Private helpers
# ─────────────────────────────────────────

def _get_or_404(invoice_id: int) -> InvoiceMaster:
    """
    Fetch an invoice by PK and verify it belongs to the current tenant.
    Tenant check: client_id or project_id must trace back to g.tenant_id via Client_Master.
    """
    tenant_client_ids = (
        db.session.query(ClientMaster.client_id)
        .filter(ClientMaster.tenant_id == g.tenant_id)
        .subquery()
    )
    tenant_project_ids = (
        db.session.query(ProjectDetails.project_id)
        .join(ClientMaster, ProjectDetails.client_id == ClientMaster.client_id)
        .filter(ClientMaster.tenant_id == g.tenant_id)
        .subquery()
    )
    invoice = InvoiceMaster.query.filter(
        InvoiceMaster.invoice_id == invoice_id,
        or_(
            InvoiceMaster.client_id.in_(tenant_client_ids),
            InvoiceMaster.project_id.in_(tenant_project_ids),
        )
    ).first()
    if not invoice:
        abort(404, description='Invoice not found')
    return invoice


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
        'total_amount':     i.total_amount,
        'discount_percent': i.discount_percent,
        'discount_amount':  i.discount_amount,
        'created_at':       i.created_at.isoformat() if i.created_at else None,
        'updated_at':       i.updated_at.isoformat() if i.updated_at else None,
    }
    if include_details:
        result['details'] = [
            _detail_dict(d)
            for d in InvoiceDetails.query.filter_by(invoice_id=i.invoice_id).all()
        ]
    return result


def _detail_dict(d: InvoiceDetails) -> dict:
    return {
        'invoice_details_id': d.invoice_details_id,
        'invoice_id':         d.invoice_id,
        'service_id':         d.service_id,
        'quantity':           d.quantity,
        'uom_id':             d.uom_id,
        'created_at':         d.created_at.isoformat() if d.created_at else None,
        'updated_at':         d.updated_at.isoformat() if d.updated_at else None,
    }