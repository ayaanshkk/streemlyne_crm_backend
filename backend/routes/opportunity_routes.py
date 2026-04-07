"""
Opportunity Routes
Handles: Opportunity_Details, Stage_Master

Schema alignment (StreemLyne_MT):
  Opportunity_Details:
    opportunity_id (PK), client_id (FK→Client_Master), opportunity_title (NOT NULL),
    opportunity_description, opportunity_date (date), opportunity_value (smallint),
    currency_id (FK→Currency_Master), stage_id (FK→Stage_Master, NOT NULL),
    opportunity_owner_employee_id (FK→Employee_Master),
    assigned_to_employee_id (FK→Employee_Master, integer),
    tenant_id (FK→Tenant_Master, bigint, NOT NULL),
    service_id (smallint), start_date, end_date, deleted_at (soft-delete),
    mpan_mpr, business_name, contact_person, tel_number, email, Misc_Col1

  Stage_Master:
    stage_id (PK), stage_name (UNIQUE, NOT NULL), stage_description,
    preceding_stage_id (nullable), stage_type (NOT NULL)

NOTE — pipeline view (GET /api/opportunities/pipeline):
  Returns a FLAT ARRAY (not grouped dict) with embedded 'customer' object and
  'job_workflow_stage' / 'estimated_value' / 'id' aliases so the kanban
  component (terminal-pipeline-view.tsx) works without change.

NOTE — stage update (PATCH /api/opportunities/<id>/stage):
  Also accepts PUT so the existing api.put() calls in the frontend work
  without needing to add a .patch() method to the api helper.
  Accepts stage_id (int), stage_name (string), or
  job_workflow_stage (string) so both backend and frontend conventions work.

NOTE — assignments:
  Assignments live on Opportunity_Details.assigned_to_employee_id (a single FK).
  The old assignment_routes.py pattern of a separate assignments table is replaced
  by the PATCH /assign endpoint here.
"""

from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy.exc import IntegrityError
from database import db
from models import OpportunityDetails, StageMaster, ClientMaster
from middleware import auth_required, permission_required
from datetime import datetime

opportunity_bp = Blueprint('opportunity', __name__, url_prefix='/opportunities')


# ─────────────────────────────────────────
# Opportunities – CRUD
# ─────────────────────────────────────────

@opportunity_bp.route('', methods=['GET'])
@auth_required
def list_opportunities():
    """
    List opportunities for the current tenant.
    GET /api/opportunities
    Query params:
      client_id       – filter by client
      stage_id        – filter by stage
      assigned_to     – filter by assigned_to_employee_id
      owner           – filter by opportunity_owner_employee_id
      service_id      – filter by service
      include_deleted – include soft-deleted records (default: false)
    """
    query = OpportunityDetails.query.filter_by(tenant_id=g.tenant_id)

    client_id       = request.args.get('client_id',   type=int)
    stage_id        = request.args.get('stage_id',    type=int)
    assigned_to     = request.args.get('assigned_to', type=int)
    owner           = request.args.get('owner',       type=int)
    service_id      = request.args.get('service_id',  type=int)
    include_deleted = request.args.get('include_deleted', 'false').lower() == 'true'

    if not include_deleted:
        query = query.filter(OpportunityDetails.deleted_at.is_(None))
    if client_id:
        query = query.filter_by(client_id=client_id)
    if stage_id:
        query = query.filter_by(stage_id=stage_id)
    if assigned_to:
        query = query.filter_by(assigned_to_employee_id=assigned_to)
    if owner:
        query = query.filter_by(opportunity_owner_employee_id=owner)
    if service_id:
        query = query.filter_by(service_id=service_id)

    opportunities = query.order_by(OpportunityDetails.created_at.desc()).all()
    return jsonify([_opportunity_dict(o) for o in opportunities]), 200


@opportunity_bp.route('', methods=['POST'])
@auth_required
# @permission_required('opportunity.create')
def create_opportunity():
    """
    Create a new opportunity.
    POST /api/opportunities
    Body:
    {
        "opportunity_title": "Solar Panel Installation",  (required)
        "stage_id": 1,                                    (required, FK → Stage_Master)
        "client_id": 5,                                   (optional, FK → Client_Master)
        "opportunity_description": "...",
        "opportunity_date": "2025-06-01",
        "opportunity_owner_employee_id": 3,
        "assigned_to_employee_id": 4,
        "opportunity_value": 15000,
        "currency_id": 1,
        "service_id": 2,
        "start_date": "2025-07-01",
        "end_date": "2025-09-30",
        "mpan_mpr": "1234567890",
        "business_name": "Acme Factory",
        "contact_person": "Bob Smith",
        "tel_number": "555-0100",
        "email": "bob@acme.com"
    }
    """
    data = request.get_json() or {}

    if not (data.get('opportunity_title') or '').strip():
        return jsonify({'error': 'opportunity_title is required'}), 400
    if not data.get('stage_id'):
        return jsonify({'error': 'stage_id is required'}), 400

    opp = OpportunityDetails(
        tenant_id=g.tenant_id,
        client_id=data.get('client_id'),
        opportunity_title=data['opportunity_title'].strip(),
        opportunity_description=data.get('opportunity_description'),
        opportunity_date=_parse_date(data.get('opportunity_date')),
        opportunity_owner_employee_id=data.get('opportunity_owner_employee_id'),
        assigned_to_employee_id=data.get('assigned_to_employee_id'),
        stage_id=data['stage_id'],
        opportunity_value=data.get('opportunity_value'),
        currency_id=data.get('currency_id'),
        service_id=data.get('service_id'),
        start_date=_parse_date(data.get('start_date')),
        end_date=_parse_date(data.get('end_date')),
        mpan_mpr=data.get('mpan_mpr'),
        business_name=data.get('business_name'),
        contact_person=data.get('contact_person'),
        tel_number=data.get('tel_number'),
        email=data.get('email')
    )

    try:
        db.session.add(opp)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'error': 'Invalid reference — check stage_id, client_id, currency_id, or employee IDs'
        }), 409

    return jsonify(_opportunity_dict(opp)), 201


@opportunity_bp.route('/<int:opportunity_id>', methods=['GET'])
@auth_required
def get_opportunity(opportunity_id: int):
    """GET /api/opportunities/<opportunity_id>"""
    opp = _get_or_404(opportunity_id)
    return jsonify(_opportunity_dict(opp)), 200


@opportunity_bp.route('/<int:opportunity_id>', methods=['PUT'])
@auth_required
# @permission_required('opportunity.update')
def update_opportunity(opportunity_id: int):
    """
    Update an opportunity.
    PUT /api/opportunities/<opportunity_id>
    All fields are optional — only provided fields are changed.
    """
    opp = _get_or_404(opportunity_id)
    data = request.get_json() or {}

    scalar_fields = [
        'opportunity_title', 'opportunity_description', 'stage_id',
        'opportunity_value', 'currency_id', 'service_id',
        'opportunity_owner_employee_id', 'assigned_to_employee_id',
        'mpan_mpr', 'business_name', 'contact_person', 'tel_number', 'email'
    ]
    for field in scalar_fields:
        if field in data:
            setattr(opp, field, data[field])

    for date_field in ['opportunity_date', 'start_date', 'end_date']:
        if date_field in data:
            setattr(opp, date_field, _parse_date(data[date_field]))

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid reference — check stage_id, client_id, or employee IDs'}), 409

    return jsonify({'message': 'Opportunity updated', 'opportunity': _opportunity_dict(opp)}), 200


@opportunity_bp.route('/<int:opportunity_id>/stage', methods=['PATCH', 'PUT'])
@auth_required
# @permission_required('opportunity.update')
def update_stage(opportunity_id: int):
    """
    Update the pipeline stage (drag-and-drop kanban).
    PATCH /api/opportunities/<opportunity_id>/stage
    Also accepts PUT so api.put() calls in the frontend work without
    requiring a .patch() method on the api helper.

    Body — accepts any of:
      { "stage_id": 3 }                   ← preferred (integer FK)
      { "stage_name": "In Progress" }     ← name lookup (case-insensitive)
      { "job_workflow_stage": "Review" }  ← legacy alias from terminal-pipeline-view
    """
    opp = _get_or_404(opportunity_id)
    data = request.get_json() or {}

    stage = None

    # Resolve by ID (preferred)
    if data.get('stage_id') is not None:
        stage = db.session.get(StageMaster, int(data['stage_id']))
        if not stage:
            return jsonify({'error': f'stage_id {data["stage_id"]} does not exist'}), 400

    # Resolve by name or legacy alias
    elif data.get('stage_name') or data.get('job_workflow_stage'):
        name = data.get('stage_name') or data.get('job_workflow_stage')
        stage = StageMaster.query.filter(
            StageMaster.stage_name.ilike(name)
        ).first()
        if not stage:
            return jsonify({'error': f'Stage "{name}" not found in Stage_Master'}), 400

    else:
        return jsonify({'error': 'Provide stage_id (int), stage_name, or job_workflow_stage'}), 400

    old_stage_id = opp.stage_id
    opp.stage_id = stage.stage_id

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid stage_id'}), 409

    # Broadcast SSE if the application supports it
    try:
        from app import broadcast_sse_event
        broadcast_sse_event('workflow_stage_updated', {
            'opportunity_id': opp.opportunity_id,
            'old_stage_id':   old_stage_id,
            'new_stage_id':   opp.stage_id,
            'stage_name':     stage.stage_name,
            'timestamp':      datetime.utcnow().isoformat(),
        })
    except (ImportError, Exception):
        pass

    return jsonify({
        'message':        'Stage updated',
        'opportunity_id': opp.opportunity_id,
        'old_stage_id':   old_stage_id,
        'new_stage_id':   opp.stage_id,
        'stage_name':     stage.stage_name,
    }), 200


@opportunity_bp.route('/<int:opportunity_id>/assign', methods=['PATCH'])
@auth_required
# @permission_required('opportunity.assign')
def assign_opportunity(opportunity_id: int):
    """
    Assign (or unassign) an opportunity to an employee.
    PATCH /api/opportunities/<opportunity_id>/assign
    Body: { "employee_id": 7 }  (pass null to unassign)

    Replaces the old assignment_routes.py pattern.
    """
    opp = _get_or_404(opportunity_id)
    data = request.get_json() or {}

    opp.assigned_to_employee_id = data.get('employee_id')

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid employee_id'}), 409

    return jsonify({
        'message':                  'Opportunity assigned',
        'opportunity_id':           opp.opportunity_id,
        'assigned_to_employee_id':  opp.assigned_to_employee_id,
    }), 200


@opportunity_bp.route('/<int:opportunity_id>', methods=['DELETE'])
@auth_required
# @permission_required('opportunity.delete')
def delete_opportunity(opportunity_id: int):
    """
    Soft-delete an opportunity (sets deleted_at timestamp).
    DELETE /api/opportunities/<opportunity_id>
    """
    opp = _get_or_404(opportunity_id)
    opp.deleted_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'message': 'Opportunity deleted'}), 200


# ─────────────────────────────────────────
# Pipeline view  (consumed by terminal-pipeline-view.tsx)
# ─────────────────────────────────────────

@opportunity_bp.route('/pipeline', methods=['GET'])
@auth_required
def get_pipeline():
    """
    Return all active opportunities as a FLAT ARRAY with embedded client data.
    GET /api/opportunities/pipeline

    The response includes 'customer', 'job_workflow_stage', 'estimated_value',
    and 'id' aliases so the kanban component works without modification.

    Response shape:
    [
      {
        "id": "5",                            // str — kanban key
        "opportunity_id": 5,
        "opportunity_reference": "OPP-5",
        "opportunity_name": "Solar Install",  // == opportunity_title
        "opportunity_title": "Solar Install",
        "stage_id": 3,
        "stage": "In Progress",
        "job_workflow_stage": "In Progress",  // kanban alias
        "opportunity_value": 15000,
        "estimated_value": 15000,            // kanban alias
        "customer": {
          "id": "12",
          "name": "Bob Smith",
          "company_name": "Acme Ltd",
          "email": "bob@acme.com",
          "phone": "+44 ...",
          "address": "...",
          "stage": "In Progress"
        },
        ...
      }
    ]
    """
    opps = (
        OpportunityDetails.query
        .filter_by(tenant_id=g.tenant_id)
        .filter(OpportunityDetails.deleted_at.is_(None))
        .order_by(OpportunityDetails.created_at.desc())
        .all()
    )

    # Pre-load all stages to avoid N+1 queries
    all_stages: dict[int, StageMaster] = {
        s.stage_id: s for s in StageMaster.query.all()
    }

    result = []
    for opp in opps:
        stage      = all_stages.get(opp.stage_id)
        stage_name = stage.stage_name if stage else 'New'

        # Resolve client — use relationship if loaded, else direct query
        client_name         = None
        client_company_name = None
        client_email        = None
        client_phone        = None
        client_address      = None

        client_obj = getattr(opp, 'client', None)
        if client_obj:
            client_name         = client_obj.client_contact_name
            client_company_name = client_obj.client_company_name
            client_email        = client_obj.client_email
            client_phone        = client_obj.client_phone
            client_address      = client_obj.address
        elif opp.client_id:
            c = db.session.get(ClientMaster, opp.client_id)
            if c:
                client_name         = c.client_contact_name
                client_company_name = c.client_company_name
                client_email        = c.client_email
                client_phone        = c.client_phone
                client_address      = c.address

        display_name = client_name or client_company_name or (
            f'Client #{opp.client_id}' if opp.client_id else 'Unknown'
        )

        result.append({
            # ── PK + reference ─────────────────────────────────────────
            'id':                    str(opp.opportunity_id),   # string for kanban key
            'opportunity_id':        opp.opportunity_id,
            'opportunity_reference': f'OPP-{opp.opportunity_id}',

            # ── Title aliases ───────────────────────────────────────────
            'opportunity_name':  opp.opportunity_title,         # legacy alias
            'opportunity_title': opp.opportunity_title,

            # ── Stage (id + name aliases) ───────────────────────────────
            'stage_id':           opp.stage_id,
            'stage':              stage_name,
            'job_workflow_stage': stage_name,                   # kanban alias

            # ── Value aliases ───────────────────────────────────────────
            'opportunity_value': opp.opportunity_value,
            'estimated_value':   opp.opportunity_value,         # kanban alias

            # ── Other fields ────────────────────────────────────────────
            'currency_id':               opp.currency_id,
            'service_id':                opp.service_id,
            'assigned_to_employee_id':   opp.assigned_to_employee_id,
            'start_date':  opp.start_date.isoformat() if opp.start_date else None,
            'end_date':    opp.end_date.isoformat()   if opp.end_date   else None,
            'created_at':  opp.created_at.isoformat() if opp.created_at else None,

            # ── Embedded client (used by kanban cards) ──────────────────
            'customer': {
                'id':           str(opp.client_id) if opp.client_id else None,
                'name':         display_name,
                'company_name': client_company_name,
                'email':        client_email,
                'phone':        client_phone,
                'address':      client_address,
                'stage':        stage_name,                     # kanban needs this
            },
        })

    return jsonify(result), 200


# ─────────────────────────────────────────
# Stage Master – CRUD
# ─────────────────────────────────────────

@opportunity_bp.route('/stages', methods=['GET'])
@auth_required
def list_stages():
    """GET /api/opportunities/stages"""
    stages = StageMaster.query.order_by(StageMaster.stage_id).all()
    return jsonify([_stage_dict(s) for s in stages]), 200


@opportunity_bp.route('/stages', methods=['POST'])
@auth_required
# @permission_required('opportunity.manage_stages')
def create_stage():
    """
    POST /api/opportunities/stages
    Body: { "stage_name": "Negotiation", "stage_type": 1, ... }
    """
    data = request.get_json() or {}

    if not (data.get('stage_name') or '').strip():
        return jsonify({'error': 'stage_name is required'}), 400
    if data.get('stage_type') is None:
        return jsonify({'error': 'stage_type is required'}), 400

    stage = StageMaster(
        stage_name=data['stage_name'].strip(),
        stage_description=data.get('stage_description'),
        preceding_stage_id=data.get('preceding_stage_id'),
        stage_type=int(data['stage_type'])
    )

    try:
        db.session.add(stage)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Stage name already exists'}), 409

    return jsonify({'message': 'Stage created', 'stage': _stage_dict(stage)}), 201


@opportunity_bp.route('/stages/<int:stage_id>', methods=['PUT'])
@auth_required
# @permission_required('opportunity.manage_stages')
def update_stage_record(stage_id: int):
    """PUT /api/opportunities/stages/<stage_id>"""
    stage = db.session.get(StageMaster, stage_id)
    if not stage:
        abort(404, description='Stage not found')

    data = request.get_json() or {}
    for field in ['stage_name', 'stage_description', 'preceding_stage_id', 'stage_type']:
        if field in data:
            setattr(stage, field, data[field])

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Stage name already exists'}), 409

    return jsonify({'message': 'Stage updated', 'stage': _stage_dict(stage)}), 200


@opportunity_bp.route('/stages/<int:stage_id>', methods=['DELETE'])
@auth_required
# @permission_required('opportunity.manage_stages')
def delete_stage(stage_id: int):
    """DELETE /api/opportunities/stages/<stage_id>"""
    stage = db.session.get(StageMaster, stage_id)
    if not stage:
        abort(404, description='Stage not found')

    try:
        db.session.delete(stage)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Cannot delete stage — opportunities are still assigned to it'}), 409

    return jsonify({'message': 'Stage deleted'}), 200


# ─────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────

def _get_or_404(opportunity_id: int) -> OpportunityDetails:
    opp = OpportunityDetails.query.filter_by(
        opportunity_id=opportunity_id,
        tenant_id=g.tenant_id
    ).first()
    if not opp:
        abort(404, description='Opportunity not found')
    return opp


def _parse_date(value):
    if not value:
        return None
    if hasattr(value, 'date'):
        return value.date()
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _opportunity_dict(o: OpportunityDetails) -> dict:
    """Lean canonical dict — used by list/get/create/update endpoints."""
    return {
        'opportunity_id':                  o.opportunity_id,
        'tenant_id':                       o.tenant_id,
        'client_id':                       o.client_id,
        'opportunity_title':               o.opportunity_title,
        'opportunity_description':         o.opportunity_description,
        'opportunity_date':                o.opportunity_date.isoformat() if o.opportunity_date else None,
        'stage_id':                        o.stage_id,
        'opportunity_value':               o.opportunity_value,
        'currency_id':                     o.currency_id,
        'service_id':                      o.service_id,
        'opportunity_owner_employee_id':   o.opportunity_owner_employee_id,
        'assigned_to_employee_id':         o.assigned_to_employee_id,
        'start_date':                      o.start_date.isoformat() if o.start_date else None,
        'end_date':                        o.end_date.isoformat()   if o.end_date   else None,
        'mpan_mpr':                        o.mpan_mpr,
        'business_name':                   o.business_name,
        'contact_person':                  o.contact_person,
        'tel_number':                      o.tel_number,
        'email':                           o.email,
        'deleted_at':                      o.deleted_at.isoformat() if o.deleted_at else None,
        'created_at':                      o.created_at.isoformat() if o.created_at else None,
    }


def _stage_dict(s: StageMaster) -> dict:
    return {
        'stage_id':           s.stage_id,
        'stage_name':         s.stage_name,
        'stage_description':  s.stage_description,
        'preceding_stage_id': s.preceding_stage_id,
        'stage_type':         s.stage_type,
    }