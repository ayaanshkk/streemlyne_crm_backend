"""
Project Routes
Handles: Project_Details

Schema alignment (StreemLyne_MT):
  Project_Details:
    project_id (PK), client_id (FK→Client_Master, NOT NULL),
    opportunity_id (FK→Opportunity_Details, NOT NULL),
    project_title (NOT NULL), project_description,
    start_date (NOT NULL), end_date, employee_id (FK→Employee_Master, NOT NULL),
    created_at, updated_at, address, Misc_Col1 (varchar), Misc_Col2 (integer)

IMPORTANT — tenant scoping:
  Project_Details has NO tenant_id column. Tenant isolation is enforced by
  joining through Client_Master (which has tenant_id). The helper
  _get_or_404 performs this join so projects are never accessible
  cross-tenant.

Misc_Col1 usage:
  Non-schema job fields (job_reference, job_type, priority, assigned_team,
  primary_contact, salesperson, tags, notes, requirements) are stored as a
  JSON blob in Misc_Col1. This column is passed through in all responses
  and accepted in create/update so no data is ever silently dropped.
  The frontend parseMisc() helper unpacks it on read.
"""

from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from database import db
from models import ProjectDetails, ClientMaster
from middleware import auth_required, permission_required
from datetime import datetime

project_bp = Blueprint('project', __name__, url_prefix='/projects')


# ─────────────────────────────────────────
# Projects – CRUD
# ─────────────────────────────────────────

@project_bp.route('', methods=['GET'])
@auth_required
def list_projects():
    """
    List all projects for the current tenant.
    Tenant isolation enforced via Client_Master.tenant_id join.
    GET /api/projects
    Query params:
      client_id      – filter by client
      employee_id    – filter by responsible employee
      opportunity_id – filter by source opportunity
    """
    query = (
        ProjectDetails.query
        .join(ClientMaster, ProjectDetails.client_id == ClientMaster.client_id)
        .filter(ClientMaster.tenant_id == g.tenant_id)
    )

    client_id      = request.args.get('client_id',      type=int)
    employee_id    = request.args.get('employee_id',    type=int)
    opportunity_id = request.args.get('opportunity_id', type=int)

    if client_id:
        query = query.filter(ProjectDetails.client_id == client_id)
    if employee_id:
        query = query.filter(ProjectDetails.employee_id == employee_id)
    if opportunity_id:
        query = query.filter(ProjectDetails.opportunity_id == opportunity_id)

    projects = query.order_by(ProjectDetails.created_at.desc()).all()
    return jsonify([_project_dict(p) for p in projects]), 200


@project_bp.route('', methods=['POST'])
@auth_required
# @permission_required('project.create')
def create_project():
    """
    Create a new project from a won opportunity.
    POST /api/projects
    Body:
    {
        "client_id": 5,               (required, FK → Client_Master)
        "opportunity_id": 12,          (required, FK → Opportunity_Details)
        "project_title": "Solar Installation",  (required)
        "start_date": "2025-07-01",    (required)
        "employee_id": 3,              (required, FK → Employee_Master)
        "project_description": "...",
        "end_date": "2025-09-30",
        "address": "1 Industrial Park, London",
        "misc_col1": "{...}"           (optional JSON string – stores job_reference,
                                        job_type, priority, tags, notes, etc.)
    }
    """
    data = request.get_json() or {}

    required = ['client_id', 'opportunity_id', 'project_title', 'start_date', 'employee_id']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400

    client = ClientMaster.query.filter_by(
        client_id=data['client_id'], tenant_id=g.tenant_id
    ).first()
    if not client:
        return jsonify({'error': 'Invalid client_id for this tenant'}), 400

    start = _parse_date(data['start_date'])
    if not start:
        return jsonify({'error': 'Invalid start_date — expected YYYY-MM-DD'}), 400

    # Accept misc_col1 (frontend key) or Misc_Col1 (schema key)
    misc_col1 = data.get('misc_col1') or data.get('Misc_Col1') or None

    project = ProjectDetails(
        client_id=data['client_id'],
        opportunity_id=data['opportunity_id'],
        project_title=data['project_title'].strip(),
        project_description=data.get('project_description'),
        start_date=start,
        end_date=_parse_date(data.get('end_date')),
        employee_id=data['employee_id'],
        address=data.get('address'),
        Misc_Col1=misc_col1,
    )

    try:
        db.session.add(project)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'error': 'Invalid foreign key reference — check opportunity_id or employee_id'
        }), 409

    return jsonify(_project_dict(project)), 201


@project_bp.route('/<int:project_id>', methods=['GET'])
@auth_required
def get_project(project_id: int):
    """
    Retrieve a single project with linked energy contracts.
    GET /api/projects/<project_id>
    """
    project = _get_or_404(project_id)
    result  = _project_dict(project)

    try:
        from models import EnergyContractMaster
        contracts = EnergyContractMaster.query.filter_by(project_id=project_id).all()
        result['energy_contracts'] = [
            {
                'energy_contract_master_id': c.energy_contract_master_id,
                'supplier_id':        c.supplier_id,
                'service_id':         c.service_id,
                'terms_of_sale':      c.terms_of_sale,
                'unit_rate':          c.unit_rate,
                'currency_id':        c.currency_id,
                'mpan_number':        c.mpan_number,
                'contract_start_date': c.contract_start_date.isoformat() if c.contract_start_date else None,
                'contract_end_date':   c.contract_end_date.isoformat()   if c.contract_end_date   else None,
            }
            for c in contracts
        ]
    except Exception:
        result['energy_contracts'] = []

    return jsonify(result), 200


@project_bp.route('/<int:project_id>', methods=['PUT'])
@auth_required
# @permission_required('project.update')
def update_project(project_id: int):
    """
    Update a project.
    PUT /api/projects/<project_id>
    All fields optional — only provided fields are changed.
    Accepts misc_col1 / Misc_Col1 to overwrite the JSON blob.
    """
    project = _get_or_404(project_id)
    data = request.get_json() or {}

    for field in ['project_title', 'project_description', 'employee_id', 'address']:
        if field in data:
            setattr(project, field, data[field])

    for date_field in ['start_date', 'end_date']:
        if date_field in data:
            parsed = _parse_date(data[date_field])
            if parsed is not None or data[date_field] is None:
                setattr(project, date_field, parsed)

    # Update Misc_Col1 if either key variant is present in the payload
    if 'misc_col1' in data or 'Misc_Col1' in data:
        project.Misc_Col1 = data.get('misc_col1') or data.get('Misc_Col1')

    project.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid employee_id'}), 409

    return jsonify({'message': 'Project updated', 'project': _project_dict(project)}), 200


@project_bp.route('/<int:project_id>', methods=['DELETE'])
@auth_required
# @permission_required('project.delete')
def delete_project(project_id: int):
    """
    Delete a project.
    DELETE /api/projects/<project_id>
    Returns 409 if referenced by invoices, proposals, or contracts.
    """
    project = _get_or_404(project_id)

    try:
        db.session.delete(project)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'error': 'Cannot delete project — it is referenced by invoices, proposals, or energy contracts'
        }), 409

    return jsonify({'message': 'Project deleted'}), 200


# ─────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────

def _get_or_404(project_id: int) -> ProjectDetails:
    project = (
        ProjectDetails.query
        .join(ClientMaster, ProjectDetails.client_id == ClientMaster.client_id)
        .filter(
            ProjectDetails.project_id == project_id,
            ClientMaster.tenant_id == g.tenant_id
        )
        .first()
    )
    if not project:
        abort(404, description='Project not found')
    return project


def _parse_date(value):
    if not value:
        return None
    if hasattr(value, 'date'):
        return value.date()
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _project_dict(p: ProjectDetails) -> dict:
    """
    Serialise a Project_Details row.
    misc_col1 is included as a raw JSON string so the frontend parseMisc()
    helper can unpack job_reference, job_type, priority, assigned_team,
    primary_contact, salesperson, tags, and notes.
    """
    return {
        'project_id':          p.project_id,
        'client_id':           p.client_id,
        'opportunity_id':      p.opportunity_id,
        'project_title':       p.project_title,
        'project_description': p.project_description,
        'start_date':          p.start_date.isoformat()  if p.start_date  else None,
        'end_date':            p.end_date.isoformat()    if p.end_date    else None,
        'employee_id':         p.employee_id,
        'address':             p.address,
        'created_at':          p.created_at.isoformat()  if p.created_at  else None,
        'updated_at':          p.updated_at.isoformat()  if p.updated_at  else None,
        # Misc_Col1 pass-through — raw JSON string, lowercase key for frontend
        'misc_col1':           p.Misc_Col1,
    }