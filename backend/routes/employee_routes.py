"""
Employee Routes
Handles: Employee_Master, Designation_Master

Schema alignment (StreemLyne_MT):
  Employee_Master:
    employee_id (PK), tenant_id (FK→Tenant_Master, bigint), employee_name,
    employee_designation_id (FK→Designation_Master, nullable),
    phone, email (UNIQUE), date_of_birth, date_of_joining,
    id_type, id_number, role_ids (varchar, comma-separated role IDs),
    created_on, updated_on, commission_percentage (real)

  Designation_Master:
    designation_id (PK), designation_description (UNIQUE), created_at

NOTE — role_ids:
  Employee_Master stores role_ids as a varchar (comma-separated) rather than
  a normalised FK. The User_Role_Mapping table is the canonical authorisation
  source; role_ids on Employee_Master is informational/legacy. Kept as-is.
"""

from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy.exc import IntegrityError
from database import db
from models import EmployeeMaster, DesignationMaster
from middleware import auth_required, permission_required
from datetime import datetime

employee_bp = Blueprint('employee', __name__, url_prefix='/api/employees')


# ─────────────────────────────────────────
# Employees – CRUD
# ─────────────────────────────────────────

@employee_bp.route('', methods=['GET'])
@auth_required
def list_employees():
    """
    List all employees for the current tenant.
    GET /api/employees
    Query params:
      designation_id – filter by employee_designation_id
      name           – partial match on employee_name
    """
    query = EmployeeMaster.query.filter_by(tenant_id=g.tenant_id)

    designation_id = request.args.get('designation_id', type=int)
    name_q         = request.args.get('name')

    if designation_id:
        query = query.filter_by(employee_designation_id=designation_id)
    if name_q:
        query = query.filter(EmployeeMaster.employee_name.ilike(f'%{name_q}%'))

    employees = query.order_by(EmployeeMaster.employee_name).all()
    return jsonify([_employee_dict(e) for e in employees]), 200


@employee_bp.route('', methods=['POST'])
@auth_required
@permission_required('employee.create')
def create_employee():
    """
    Create a new employee.
    POST /api/employees
    Body:
    {
        "employee_name": "Jane Doe",           (required)
        "email": "jane@example.com",           (optional, must be unique)
        "phone": "555-0100",
        "employee_designation_id": 2,          (FK → Designation_Master)
        "date_of_birth":  "1990-01-15",
        "date_of_joining": "2024-03-01",
        "id_type": "Passport",
        "id_number": "AB123456",
        "commission_percentage": 5.0
    }
    """
    data = request.get_json() or {}

    if not (data.get('employee_name') or '').strip():
        return jsonify({'error': 'employee_name is required'}), 400

    email = (data.get('email') or '').lower().strip() or None

    employee = EmployeeMaster(
        tenant_id=g.tenant_id,
        employee_name=data['employee_name'].strip(),
        email=email,
        phone=data.get('phone'),
        employee_designation_id=data.get('employee_designation_id'),
        date_of_birth=_parse_date(data.get('date_of_birth')),
        date_of_joining=_parse_date(data.get('date_of_joining')),
        id_type=data.get('id_type'),
        id_number=data.get('id_number'),
        commission_percentage=(
            float(data['commission_percentage'])
            if data.get('commission_percentage') is not None else None
        )
    )

    try:
        db.session.add(employee)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'An employee with this email already exists'}), 409

    return jsonify(_employee_dict(employee)), 201


@employee_bp.route('/<int:employee_id>', methods=['GET'])
@auth_required
def get_employee(employee_id: int):
    """
    Retrieve a single employee.
    GET /api/employees/<employee_id>
    """
    employee = _get_or_404(employee_id)
    return jsonify(_employee_dict(employee)), 200


@employee_bp.route('/<int:employee_id>', methods=['PUT'])
@auth_required
@permission_required('employee.update')
def update_employee(employee_id: int):
    """
    Update an employee record.
    PUT /api/employees/<employee_id>
    All fields are optional — only provided fields are changed.
    """
    employee = _get_or_404(employee_id)
    data = request.get_json() or {}

    # Simple scalar updates
    scalar_fields = [
        'employee_name', 'phone', 'employee_designation_id',
        'id_type', 'id_number', 'commission_percentage'
    ]
    for field in scalar_fields:
        if field in data:
            setattr(employee, field, data[field])

    # Email must stay unique across the entire table
    if 'email' in data:
        new_email = (data['email'] or '').lower().strip() or None
        if new_email and new_email != employee.email:
            if EmployeeMaster.query.filter(
                EmployeeMaster.email == new_email,
                EmployeeMaster.employee_id != employee_id
            ).first():
                return jsonify({'error': 'Email already in use by another employee'}), 409
        employee.email = new_email

    if 'date_of_birth' in data:
        employee.date_of_birth = _parse_date(data['date_of_birth'])
    if 'date_of_joining' in data:
        employee.date_of_joining = _parse_date(data['date_of_joining'])

    # updated_on is a timestamp column in Employee_Master
    employee.updated_on = datetime.utcnow()

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Update violates a uniqueness constraint'}), 409

    return jsonify({'message': 'Employee updated', 'employee': _employee_dict(employee)}), 200


@employee_bp.route('/<int:employee_id>', methods=['DELETE'])
@auth_required
@permission_required('employee.delete')
def delete_employee(employee_id: int):
    """
    Delete an employee.
    DELETE /api/employees/<employee_id>
    Returns 409 if the employee is referenced by FK-constrained tables
    (e.g. Opportunity_Details, Project_Details, Energy_Contract_Master).
    """
    employee = _get_or_404(employee_id)

    try:
        db.session.delete(employee)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'error': 'Cannot delete employee — they are referenced by existing opportunities, projects, or contracts'
        }), 409

    return jsonify({'message': 'Employee deleted'}), 200


# ─────────────────────────────────────────
# Designations – CRUD
# ─────────────────────────────────────────

@employee_bp.route('/designations', methods=['GET'])
@auth_required
def list_designations():
    """
    List all designations (global — not tenant-scoped in the schema).
    GET /api/employees/designations
    """
    designations = (
        DesignationMaster.query
        .order_by(DesignationMaster.designation_description)
        .all()
    )
    return jsonify([_designation_dict(d) for d in designations]), 200


@employee_bp.route('/designations', methods=['POST'])
@auth_required
@permission_required('employee.manage_designations')
def create_designation():
    """
    Create a new designation.
    POST /api/employees/designations
    Body: { "designation_description": "Senior Engineer" }
    """
    data = request.get_json() or {}
    desc = (data.get('designation_description') or '').strip()

    if not desc:
        return jsonify({'error': 'designation_description is required'}), 400

    designation = DesignationMaster(designation_description=desc)

    try:
        db.session.add(designation)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Designation already exists'}), 409

    return jsonify({
        'message': 'Designation created',
        'designation': _designation_dict(designation)
    }), 201


@employee_bp.route('/designations/<int:designation_id>', methods=['PUT'])
@auth_required
@permission_required('employee.manage_designations')
def update_designation(designation_id: int):
    """
    Rename a designation.
    PUT /api/employees/designations/<designation_id>
    Body: { "designation_description": "Lead Engineer" }
    """
    # FIXED: replaced deprecated DesignationMaster.query.get() with db.session.get()
    designation = db.session.get(DesignationMaster, designation_id)
    if not designation:
        abort(404, description='Designation not found')

    data = request.get_json() or {}
    desc = (data.get('designation_description') or '').strip()

    if not desc:
        return jsonify({'error': 'designation_description is required'}), 400

    designation.designation_description = desc

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Designation name already exists'}), 409

    return jsonify({'message': 'Designation updated', 'designation': _designation_dict(designation)}), 200


@employee_bp.route('/designations/<int:designation_id>', methods=['DELETE'])
@auth_required
@permission_required('employee.manage_designations')
def delete_designation(designation_id: int):
    """
    Delete a designation.
    DELETE /api/employees/designations/<designation_id>
    Returns 409 if any Employee_Master row references this designation.
    """
    # FIXED: replaced deprecated DesignationMaster.query.get() with db.session.get()
    designation = db.session.get(DesignationMaster, designation_id)
    if not designation:
        abort(404, description='Designation not found')

    try:
        db.session.delete(designation)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'error': 'Cannot delete designation — employees are still assigned to it'
        }), 409

    return jsonify({'message': 'Designation deleted'}), 200


# ─────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────

def _get_or_404(employee_id: int) -> EmployeeMaster:
    employee = EmployeeMaster.query.filter_by(
        employee_id=employee_id,
        tenant_id=g.tenant_id
    ).first()
    if not employee:
        abort(404, description='Employee not found')
    return employee


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


def _employee_dict(e: EmployeeMaster) -> dict:
    return {
        'employee_id':             e.employee_id,
        'tenant_id':               e.tenant_id,
        'employee_name':           e.employee_name,
        'email':                   e.email,
        'phone':                   e.phone,
        'employee_designation_id': e.employee_designation_id,
        # Resolve designation label if the relationship is loaded
        'designation': (
            e.designation.designation_description
            if hasattr(e, 'designation') and e.designation else None
        ),
        'date_of_birth':        e.date_of_birth.isoformat()  if e.date_of_birth  else None,
        'date_of_joining':      e.date_of_joining.isoformat() if e.date_of_joining else None,
        'id_type':              e.id_type,
        'id_number':            e.id_number,
        'commission_percentage': e.commission_percentage,
        'created_on':           e.created_on.isoformat()  if e.created_on  else None,
        'updated_on':           e.updated_on.isoformat()  if e.updated_on  else None,
    }

def _designation_dict(d: DesignationMaster) -> dict:
    return {
        'designation_id':          d.designation_id,
        'designation_description': d.designation_description,
        'created_at':              d.created_at.isoformat() if d.created_at else None,
    }