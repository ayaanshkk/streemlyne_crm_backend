"""
Contract Routes
Handles: Energy_Contract_Master

Schema alignment (StreemLyne_MT):
  Energy_Contract_Master:
    energy_contract_master_id (PK), project_id (FK→Project_Details, nullable),
    employee_id (FK→Employee_Master, NOT NULL), supplier_id (FK→Supplier_Master, NOT NULL),
    contract_start_date (NOT NULL), contract_end_date (NOT NULL),
    terms_of_sale (NOT NULL), service_id (FK→Services_Master, NOT NULL),
    unit_rate real (NOT NULL), currency_id (FK→Currency_Master, nullable),
    document_details, created_at, updated_at, mpan_number
"""

from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy.exc import IntegrityError
from database import db
from models import EnergyContractMaster
from middleware import auth_required, permission_required
from datetime import datetime

contract_bp = Blueprint('contract', __name__, url_prefix='/api/contracts')


# ─────────────────────────────────────────
# Energy Contract Master – CRUD
# ─────────────────────────────────────────

@contract_bp.route('', methods=['GET'])
@auth_required
def list_contracts():
    """
    List energy contracts with optional filters.
    GET /api/contracts
    Query params:
      project_id  – filter by project
      employee_id – filter by employee
      supplier_id – filter by supplier
      service_id  – filter by service
    """
    query = EnergyContractMaster.query

    project_id  = request.args.get('project_id',  type=int)
    employee_id = request.args.get('employee_id', type=int)
    supplier_id = request.args.get('supplier_id', type=int)
    service_id  = request.args.get('service_id',  type=int)

    if project_id:
        query = query.filter_by(project_id=project_id)
    if employee_id:
        query = query.filter_by(employee_id=employee_id)
    if supplier_id:
        query = query.filter_by(supplier_id=supplier_id)
    if service_id:
        query = query.filter_by(service_id=service_id)

    contracts = query.order_by(EnergyContractMaster.created_at.desc()).all()
    return jsonify([_contract_dict(c) for c in contracts]), 200


@contract_bp.route('', methods=['POST'])
@auth_required
@permission_required('contract.create')
def create_contract():
    """
    Create a new energy contract.
    POST /api/contracts
    Body:
    {
        "employee_id": 3,                (required, FK → Employee_Master)
        "supplier_id": 2,                (required, FK → Supplier_Master)
        "service_id": 5,                 (required, FK → Services_Master)
        "contract_start_date": "2025-07-01",  (required)
        "contract_end_date":   "2026-06-30",  (required)
        "terms_of_sale": "Fixed",         (required)
        "unit_rate": 0.235,               (required)
        "project_id": 8,                  (optional, FK → Project_Details)
        "currency_id": 1,                 (optional, FK → Currency_Master)
        "mpan_number": "1234567890123",   (optional)
        "document_details": "..."         (optional)
    }
    """
    data = request.get_json() or {}

    required = [
        'employee_id', 'supplier_id', 'service_id',
        'contract_start_date', 'contract_end_date',
        'terms_of_sale', 'unit_rate'
    ]
    missing = [f for f in required if data.get(f) is None]
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400

    start = _parse_date(data['contract_start_date'])
    end   = _parse_date(data['contract_end_date'])
    if not start or not end:
        return jsonify({'error': 'Invalid date format — expected YYYY-MM-DD'}), 400
    if end <= start:
        return jsonify({'error': 'contract_end_date must be after contract_start_date'}), 400

    contract = EnergyContractMaster(
        project_id=data.get('project_id'),
        employee_id=data['employee_id'],
        supplier_id=data['supplier_id'],
        service_id=data['service_id'],
        contract_start_date=start,
        contract_end_date=end,
        terms_of_sale=data['terms_of_sale'],
        unit_rate=float(data['unit_rate']),
        currency_id=data.get('currency_id'),
        mpan_number=data.get('mpan_number'),
        document_details=data.get('document_details')
    )

    try:
        db.session.add(contract)
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        return jsonify({'error': 'Invalid foreign key reference — check employee_id, supplier_id, service_id, project_id'}), 409

    return jsonify(_contract_dict(contract)), 201


@contract_bp.route('/<int:contract_id>', methods=['GET'])
@auth_required
def get_contract(contract_id: int):
    """
    Retrieve a single energy contract.
    GET /api/contracts/<contract_id>
    """
    contract = _get_or_404(contract_id)
    return jsonify(_contract_dict(contract)), 200


@contract_bp.route('/<int:contract_id>', methods=['PUT'])
@auth_required
@permission_required('contract.update')
def update_contract(contract_id: int):
    """
    Update an energy contract.
    PUT /api/contracts/<contract_id>
    All fields are optional — only provided fields are changed.
    """
    contract = _get_or_404(contract_id)
    data = request.get_json() or {}

    scalar_fields = [
        'supplier_id', 'service_id', 'terms_of_sale',
        'unit_rate', 'currency_id', 'mpan_number', 'document_details'
    ]
    for field in scalar_fields:
        if field in data:
            setattr(contract, field, data[field])

    for date_field in ['contract_start_date', 'contract_end_date']:
        if date_field in data:
            parsed = _parse_date(data[date_field])
            if not parsed:
                return jsonify({'error': f'Invalid date for {date_field} — expected YYYY-MM-DD'}), 400
            setattr(contract, date_field, parsed)

    # Validate date range after applying updates
    if (contract.contract_end_date and contract.contract_start_date
            and contract.contract_end_date <= contract.contract_start_date):
        return jsonify({'error': 'contract_end_date must be after contract_start_date'}), 400

    contract.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid foreign key reference'}), 409

    return jsonify({'message': 'Contract updated', 'contract': _contract_dict(contract)}), 200


@contract_bp.route('/<int:contract_id>', methods=['DELETE'])
@auth_required
@permission_required('contract.delete')
def delete_contract(contract_id: int):
    """
    Delete an energy contract.
    DELETE /api/contracts/<contract_id>
    """
    contract = _get_or_404(contract_id)

    try:
        db.session.delete(contract)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Cannot delete contract — it is referenced by other records'}), 409

    return jsonify({'message': 'Contract deleted'}), 200


# ─────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────

def _get_or_404(contract_id: int) -> EnergyContractMaster:
    contract = EnergyContractMaster.query.get(contract_id)
    if not contract:
        abort(404, description='Contract not found')
    return contract


def _parse_date(value):
    """Parse an ISO date string; returns None on failure."""
    if not value:
        return None
    if hasattr(value, 'date'):
        return value.date()
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _contract_dict(c: EnergyContractMaster) -> dict:
    return {
        'energy_contract_master_id': c.energy_contract_master_id,
        'project_id':           c.project_id,
        'employee_id':          c.employee_id,
        'supplier_id':          c.supplier_id,
        'service_id':           c.service_id,
        'contract_start_date':  c.contract_start_date.isoformat() if c.contract_start_date else None,
        'contract_end_date':    c.contract_end_date.isoformat()   if c.contract_end_date   else None,
        'terms_of_sale':        c.terms_of_sale,
        'unit_rate':            c.unit_rate,
        'currency_id':          c.currency_id,
        'mpan_number':          c.mpan_number,
        'document_details':     c.document_details,
        'created_at':           c.created_at.isoformat()  if c.created_at  else None,
        'updated_at':           c.updated_at.isoformat()  if c.updated_at  else None,
    }