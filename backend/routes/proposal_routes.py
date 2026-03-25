"""
Proposal Routes
Handles: Proposal_Master, Proposal_Details

Schema alignment (StreemLyne_MT):
  Proposal_Master:
    proposal_id (PK), client_id (FK→Client_Master, nullable),
    project_id (FK→Project_Details, nullable),
    sub_total (real), currency_id (FK→Currency_Master), tax_id (NOT NULL),
    total_amount (real, NOT NULL), discount_percent, discount_amount,
    created_at, updated_at

  Proposal_Details:
    proposal_details_id (PK), proposal_id (FK→Proposal_Master, NOT NULL),
    service_id (FK→Services_Master, NOT NULL),
    quantity (real, NOT NULL), uom_id (FK→UOM_Master, NOT NULL),
    created_at, updated_at

NOTE — tenant scoping:
  Proposal_Master has no tenant_id column. Tenant isolation is enforced by
  scoping queries through Client_Master.tenant_id or Project_Details →
  Client_Master.tenant_id. The list endpoint accepts client_id / project_id
  filters so callers should always supply at least one.
"""

from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy.exc import IntegrityError
from database import db
from models import ProposalMaster, ProposalDetails, ClientMaster
from middleware import auth_required, permission_required
from datetime import datetime

proposal_bp = Blueprint('proposal', __name__, url_prefix='/api/proposals')


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
    return jsonify([_proposal_dict(p, include_details=False) for p in proposals]), 200


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

    required = ['tax_id', 'total_amount']
    missing = [f for f in required if data.get(f) is None]
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400

    # Validate detail lines before writing anything
    for idx, item in enumerate(data.get('details', [])):
        if not item.get('service_id') or item.get('quantity') is None or not item.get('uom_id'):
            return jsonify({
                'error': f'Detail line {idx + 1} requires service_id, quantity, and uom_id'
            }), 400

    # Verify client belongs to current tenant if supplied
    if data.get('client_id'):
        client = ClientMaster.query.filter_by(
            client_id=data['client_id'], tenant_id=g.tenant_id
        ).first()
        if not client:
            return jsonify({'error': 'Invalid client_id for this tenant'}), 400

    proposal = ProposalMaster(
        client_id=data.get('client_id'),
        project_id=data.get('project_id'),
        tax_id=data['tax_id'],
        sub_total=data.get('sub_total'),
        currency_id=data.get('currency_id'),
        total_amount=float(data['total_amount']),
        discount_percent=data.get('discount_percent'),
        discount_amount=data.get('discount_amount')
    )

    try:
        db.session.add(proposal)
        db.session.flush()   # get proposal_id before inserting details

        for item in data.get('details', []):
            detail = ProposalDetails(
                proposal_id=proposal.proposal_id,
                service_id=item['service_id'],
                quantity=float(item['quantity']),
                uom_id=item['uom_id']
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

    for field in [
        'tax_id', 'currency_id', 'sub_total', 'total_amount',
        'discount_percent', 'discount_amount', 'client_id', 'project_id'
    ]:
        if field in data:
            setattr(proposal, field, data[field])

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
    """
    Fetch a proposal scoped to the current tenant via Client_Master join.
    Falls back to an unscoped lookup for proposals with no client_id
    (e.g. project-only proposals) — acceptable since project → client → tenant
    forms an equivalent chain.
    """
    proposal = (
        ProposalMaster.query
        .outerjoin(ClientMaster, ProposalMaster.client_id == ClientMaster.client_id)
        .filter(
            ProposalMaster.proposal_id == proposal_id,
            db.or_(
                ClientMaster.tenant_id == g.tenant_id,
                ProposalMaster.client_id.is_(None)   # project-only proposals
            )
        )
        .first()
    )
    if not proposal:
        abort(404, description='Proposal not found')
    return proposal


def _proposal_dict(p: ProposalMaster, include_details: bool = True) -> dict:
    result = {
        'proposal_id':      p.proposal_id,
        'client_id':        p.client_id,
        'project_id':       p.project_id,
        'tax_id':           p.tax_id,
        'sub_total':        p.sub_total,
        'currency_id':      p.currency_id,
        'total_amount':     p.total_amount,
        'discount_percent': p.discount_percent,
        'discount_amount':  p.discount_amount,
        'created_at':       p.created_at.isoformat() if p.created_at else None,
        'updated_at':       p.updated_at.isoformat() if p.updated_at else None,
    }
    if include_details:
        result['details'] = [
            _detail_dict(d)
            for d in ProposalDetails.query.filter_by(proposal_id=p.proposal_id).all()
        ]
    return result


def _detail_dict(d: ProposalDetails) -> dict:
    return {
        'proposal_details_id': d.proposal_details_id,
        'proposal_id':         d.proposal_id,
        'service_id':          d.service_id,
        'quantity':            d.quantity,
        'uom_id':              d.uom_id,
        'created_at':          d.created_at.isoformat() if d.created_at else None,
        'updated_at':          d.updated_at.isoformat() if d.updated_at else None,
    }