"""
Assignment Routes
Handles scheduling of tasks, meetings, calls, deliveries, and notes
against the calendar for the current tenant.

Endpoints:
  GET    /api/assignments              — list (filter by month, project_id, client_id)
  POST   /api/assignments              — create
  GET    /api/assignments/<id>         — get single
  PUT    /api/assignments/<id>         — update
  DELETE /api/assignments/<id>         — delete

Schema (assignments table):
  assignment_id, tenant_id, type, title, date, staff_name,
  project_id (FK → Project_Details), client_id (FK → Client_Master),
  estimated_hours, notes, priority, status, created_at, updated_at

Frontend field aliases:
  frontend.job_id      → backend.project_id
  frontend.customer_id → backend.client_id
  (both aliases are handled transparently in request parsing + response)
"""

from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy.exc import IntegrityError
from sqlalchemy import extract
from database import db
from models import Assignment
from middleware import auth_required
from datetime import datetime, date

assignment_bp = Blueprint('assignments', __name__, url_prefix='/api/assignments')

# Valid assignment types — matches frontend AssignmentType union
VALID_TYPES = {'meeting', 'call', 'task', 'delivery', 'note'}


# ─────────────────────────────────────────
# GET /api/assignments
# ─────────────────────────────────────────

@assignment_bp.route('', methods=['GET'])
@auth_required
def list_assignments():
    """
    List assignments for the current tenant.

    Query parameters:
      month       — YYYY-MM  filter to a specific calendar month (e.g. 2025-03)
      project_id  — integer  filter by linked project / job
      client_id   — integer  filter by linked client
      date        — YYYY-MM-DD  filter to exact date

    Returns array of assignment objects.
    """
    query = Assignment.query.filter_by(tenant_id=g.tenant_id)

    # ── Month filter (most common calendar use-case) ──────────────────────
    month_param = request.args.get('month')     # e.g. "2025-03"
    if month_param:
        try:
            year, month = month_param.split('-')
            query = query.filter(
                extract('year',  Assignment.date) == int(year),
                extract('month', Assignment.date) == int(month),
            )
        except (ValueError, AttributeError):
            return jsonify({'error': 'month must be in YYYY-MM format'}), 400

    # ── Exact date filter ─────────────────────────────────────────────────
    date_param = request.args.get('date')
    if date_param:
        try:
            parsed_date = datetime.strptime(date_param, '%Y-%m-%d').date()
            query = query.filter_by(date=parsed_date)
        except ValueError:
            return jsonify({'error': 'date must be in YYYY-MM-DD format'}), 400

    # ── Optional FK filters ───────────────────────────────────────────────
    project_id = request.args.get('project_id', type=int)
    if project_id:
        query = query.filter_by(project_id=project_id)

    # Accept both frontend aliases
    client_id = (
        request.args.get('client_id', type=int) or
        request.args.get('customer_id', type=int)
    )
    if client_id:
        query = query.filter_by(client_id=client_id)

    assignments = query.order_by(Assignment.date.asc()).all()
    return jsonify([_assignment_dict(a) for a in assignments]), 200


# ─────────────────────────────────────────
# POST /api/assignments
# ─────────────────────────────────────────

@assignment_bp.route('', methods=['POST'])
@auth_required
def create_assignment():
    """
    Create a new assignment.

    Required body fields:
      type   — meeting | call | task | delivery | note
      title  — display title
      date   — YYYY-MM-DD

    Optional body fields:
      staff_name, job_id (project_id alias), customer_id (client_id alias),
      estimated_hours, notes, priority, status
    """
    data = request.get_json() or {}

    # ── Validation ────────────────────────────────────────────────────────
    errors = {}
    if not (data.get('title') or '').strip():
        errors['title'] = 'title is required'
    if not data.get('date'):
        errors['date'] = 'date is required'
    assignment_type = data.get('type', 'task')
    if assignment_type not in VALID_TYPES:
        assignment_type = 'task'   # graceful fallback matching frontend behaviour
    if errors:
        return jsonify({'error': 'Validation failed', 'details': errors}), 400

    # ── Date parse ────────────────────────────────────────────────────────
    parsed_date = _parse_date(data['date'])
    if not parsed_date:
        return jsonify({'error': 'date must be in YYYY-MM-DD format'}), 400

    # ── Resolve FK aliases ────────────────────────────────────────────────
    # Frontend sends job_id; schema column is project_id
    # Frontend sends customer_id; schema column is client_id
    project_id = (
        data.get('project_id') or
        data.get('job_id')
    )
    client_id = (
        data.get('client_id') or
        data.get('customer_id')
    )

    a = Assignment(
        tenant_id       = g.tenant_id,
        type            = assignment_type,
        title           = data['title'].strip(),
        date            = parsed_date,
        staff_name      = data.get('staff_name'),
        project_id      = int(project_id) if project_id else None,
        client_id       = int(client_id)  if client_id  else None,
        estimated_hours = data.get('estimated_hours'),
        notes           = data.get('notes'),
        priority        = data.get('priority', 'Medium'),
        status          = data.get('status', 'Scheduled'),
    )

    try:
        db.session.add(a)
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        return jsonify({'error': 'Invalid project_id or client_id reference', 'detail': str(exc)}), 409

    return jsonify(_assignment_dict(a)), 201


# ─────────────────────────────────────────
# GET /api/assignments/<id>
# ─────────────────────────────────────────

@assignment_bp.route('/<int:assignment_id>', methods=['GET'])
@auth_required
def get_assignment(assignment_id: int):
    """GET /api/assignments/<assignment_id>"""
    a = _get_or_404(assignment_id)
    return jsonify(_assignment_dict(a)), 200


# ─────────────────────────────────────────
# PUT /api/assignments/<id>
# ─────────────────────────────────────────

@assignment_bp.route('/<int:assignment_id>', methods=['PUT'])
@auth_required
def update_assignment(assignment_id: int):
    """
    Update an assignment.
    PUT /api/assignments/<assignment_id>
    Body: any subset of the create fields.
    """
    a = _get_or_404(assignment_id)
    data = request.get_json() or {}

    if 'type' in data and data['type'] in VALID_TYPES:
        a.type = data['type']

    if 'title' in data and data['title'].strip():
        a.title = data['title'].strip()

    if 'date' in data:
        parsed = _parse_date(data['date'])
        if not parsed:
            return jsonify({'error': 'date must be in YYYY-MM-DD format'}), 400
        a.date = parsed

    if 'staff_name' in data:
        a.staff_name = data['staff_name']

    # Accept both frontend aliases for the FK fields
    if 'project_id' in data or 'job_id' in data:
        raw = data.get('project_id') or data.get('job_id')
        a.project_id = int(raw) if raw else None

    if 'client_id' in data or 'customer_id' in data:
        raw = data.get('client_id') or data.get('customer_id')
        a.client_id = int(raw) if raw else None

    for field in ('estimated_hours', 'notes', 'priority', 'status'):
        if field in data:
            setattr(a, field, data[field])

    a.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        return jsonify({'error': 'Invalid project_id or client_id reference', 'detail': str(exc)}), 409

    return jsonify(_assignment_dict(a)), 200


# ─────────────────────────────────────────
# DELETE /api/assignments/<id>
# ─────────────────────────────────────────

@assignment_bp.route('/<int:assignment_id>', methods=['DELETE'])
@auth_required
def delete_assignment(assignment_id: int):
    """DELETE /api/assignments/<assignment_id>"""
    a = _get_or_404(assignment_id)
    db.session.delete(a)
    db.session.commit()
    return jsonify({'message': 'Assignment deleted'}), 200


# ─────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────

def _get_or_404(assignment_id: int) -> Assignment:
    """Fetch assignment scoped to current tenant or raise 404."""
    a = Assignment.query.filter_by(
        assignment_id=assignment_id,
        tenant_id=g.tenant_id,
    ).first()
    if not a:
        abort(404, description='Assignment not found')
    return a


def _parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    # Handle ISO datetime strings from frontend (e.g. "2025-03-15T00:00:00")
    raw = str(value).split('T')[0]
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _assignment_dict(a: Assignment) -> dict:
    """
    Serialise an Assignment to a dict.
    Exposes both schema names and frontend aliases so the frontend
    never needs to remap field names on reads.
    """
    return {
        # Primary key
        'id':             a.assignment_id,   # frontend alias
        'assignment_id':  a.assignment_id,

        # Core fields
        'type':           a.type,
        'title':          a.title,
        'date':           a.date.isoformat() if a.date else None,
        'staff_name':     a.staff_name,

        # FK fields — exposed with both schema name and frontend alias
        'project_id':     a.project_id,
        'job_id':         a.project_id,      # frontend alias
        'client_id':      a.client_id,
        'customer_id':    a.client_id,       # frontend alias

        # Optional fields
        'estimated_hours': a.estimated_hours,
        'notes':           a.notes,
        'priority':        a.priority,
        'status':          a.status,

        # Joined display fields (populated when relationship is loaded)
        'customer_name': (
            a.client.client_contact_name or a.client.client_company_name
            if a.client else None
        ),

        # Timestamps
        'created_at': a.created_at.isoformat() if a.created_at else None,
        'updated_at': a.updated_at.isoformat() if a.updated_at else None,
    }