"""
Job Routes  (remapped to new schema)
Previously used: Job, Customer models — neither exists in StreemLyne_MT.

MIGRATION MAPPING:
  Old model  → New schema table
  ─────────────────────────────────────────────────────────────
  Job        → Project_Details  (a "job" is a project post-win)
  Customer   → Client_Master
  job.stage  → Opportunity_Details.stage_id → Stage_Master
  job.job_workflow_stage → removed (no such column in new schema)

  Pipeline view (Closed Won customers) →
    OpportunityDetails filtered by a "Closed Won" stage_id

BACKWARDS COMPATIBILITY:
  URL paths /jobs/* are preserved so existing front-end callers keep working.
  Response shapes include legacy keys (id, title, stage, customer_name) alongside
  canonical schema keys (project_id, project_title, …).

NOTE:
  generate_job_reference is now a local helper (not imported from models).
  team_members / account_manager / priority / tags fields do not exist on
  Project_Details in the new schema; they are stored in Misc_Col1 as JSON
  so no data is lost. If you add dedicated columns later, update _misc_from_project
  and the create/update handlers accordingly.

Tenant scoping:
  Project_Details has no tenant_id column.
  client_id is NOT NULL → join path: Client_Master.tenant_id
  Pipeline endpoints (OpportunityDetails) already filter on tenant_id directly. ✅
"""

from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy.exc import IntegrityError
from database import db
from models import ProjectDetails, ClientMaster, OpportunityDetails, StageMaster
from middleware import auth_required, permission_required
from datetime import datetime, date
import json
import secrets
import string

job_bp = Blueprint('jobs', __name__, url_prefix='/api/jobs')


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

def _generate_job_reference(length: int = 8) -> str:
    """Generate a short alphanumeric job reference, e.g. JOB-A1B2C3D4."""
    chars = string.ascii_uppercase + string.digits
    suffix = ''.join(secrets.choice(chars) for _ in range(length))
    return f'JOB-{suffix}'


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, (datetime, date)):
        return value if isinstance(value, date) else value.date()
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        try:
            return datetime.fromisoformat(str(value)).date()
        except (ValueError, TypeError):
            return None


def _misc_to_dict(misc_col1: str | None) -> dict:
    """Deserialise the JSON stored in Misc_Col1."""
    if not misc_col1:
        return {}
    try:
        return json.loads(misc_col1)
    except (ValueError, TypeError):
        return {}


def _project_to_job_dict(p: ProjectDetails) -> dict:
    """Return a response dict with both legacy job keys and canonical project keys."""
    misc = _misc_to_dict(p.Misc_Col1)

    # Resolve client name via relationship if loaded, else leave None
    client_name = None
    if hasattr(p, 'client') and p.client:
        client_name = p.client.client_company_name

    return {
        # ── Canonical project fields ────────────────────────────────────
        'project_id':          p.project_id,
        'client_id':           p.client_id,
        'opportunity_id':      p.opportunity_id,
        'project_title':       p.project_title,
        'project_description': p.project_description,
        'start_date':          p.start_date.isoformat()   if p.start_date  else None,
        'end_date':            p.end_date.isoformat()     if p.end_date    else None,
        'employee_id':         p.employee_id,
        'address':             p.address,
        'created_at':          p.created_at.isoformat()  if p.created_at  else None,
        'updated_at':          p.updated_at.isoformat()  if p.updated_at  else None,
        # ── Legacy job aliases (kept for front-end compatibility) ───────
        'id':            p.project_id,
        'title':         p.project_title,
        'job_reference': misc.get('job_reference'),
        'stage':         misc.get('stage'),
        'priority':      misc.get('priority', 'Medium'),
        'job_type':      misc.get('job_type', 'General'),
        'customer_id':   p.client_id,
        'customer_name': client_name,
        'due_date':      p.end_date.isoformat()    if p.end_date    else None,
        'completion_date':    misc.get('completion_date'),
        'estimated_value':    misc.get('estimated_value'),
        'agreed_value':       misc.get('agreed_value'),
        'deposit_amount':     misc.get('deposit_amount'),
        'deposit_due_date':   misc.get('deposit_due_date'),
        'location':           p.address,
        'primary_contact':    misc.get('primary_contact'),
        'account_manager':    misc.get('account_manager'),
        'team_members':       misc.get('team_members', []),
        'tags':               misc.get('tags'),
        'notes':              misc.get('notes'),
        'description':        p.project_description,
        'requirements':       misc.get('requirements'),
    }


def _build_misc(data: dict, existing: dict | None = None) -> dict:
    """Merge job-specific fields into the misc dict."""
    base = existing.copy() if existing else {}
    for key in [
        'job_reference', 'stage', 'priority', 'job_type',
        'estimated_value', 'agreed_value', 'deposit_amount', 'deposit_due_date',
        'primary_contact', 'account_manager', 'tags', 'notes', 'requirements',
        'completion_date',
    ]:
        if key in data:
            base[key] = data[key]

    # team_members normalisation
    raw_team = data.get('team_members') or data.get('team_member')
    if raw_team is not None:
        if isinstance(raw_team, str):
            base['team_members'] = [
                p.strip() for p in raw_team.replace(' and ', ',').split(',') if p.strip()
            ]
        elif isinstance(raw_team, list):
            base['team_members'] = raw_team

    return base


# ─────────────────────────────────────────
# Jobs (Projects) – CRUD
# ─────────────────────────────────────────

@job_bp.route('', methods=['GET'])
@auth_required
def get_jobs():
    """
    List jobs (projects) scoped to the current tenant.
    GET /api/jobs
    Query params:
      ref          – match job_reference stored in Misc_Col1 JSON
      customer_id  – filter by client_id
      stage        – partial match on misc stage value
      priority     – partial match on misc priority value
      account_manager – partial match
      from_date / to_date – filter by project end_date (was due_date)

    Tenant isolation: join through Client_Master.tenant_id (client_id is NOT NULL).
    """
    query = (
        ProjectDetails.query
        .join(ClientMaster, ProjectDetails.client_id == ClientMaster.client_id)
        .filter(ClientMaster.tenant_id == g.tenant_id)
    )

    customer_id     = request.args.get('customer_id',     type=int)
    employee_id     = request.args.get('employee_id',     type=int)
    opportunity_id  = request.args.get('opportunity_id',  type=int)
    from_date_str   = request.args.get('from_date')
    to_date_str     = request.args.get('to_date')

    if customer_id:
        query = query.filter(ProjectDetails.client_id == customer_id)
    if employee_id:
        query = query.filter(ProjectDetails.employee_id == employee_id)
    if opportunity_id:
        query = query.filter(ProjectDetails.opportunity_id == opportunity_id)

    # Misc_Col1 is a varchar JSON blob — use ILIKE for loose filtering
    ref = request.args.get('ref')
    stage = request.args.get('stage')
    priority = request.args.get('priority')
    account_manager = request.args.get('account_manager')
    team_member = request.args.get('team_member') or request.args.get('team')

    if ref:
        query = query.filter(ProjectDetails.Misc_Col1.ilike(f'%{ref}%'))
    if stage:
        query = query.filter(ProjectDetails.Misc_Col1.ilike(f'%{stage}%'))
    if priority:
        query = query.filter(ProjectDetails.Misc_Col1.ilike(f'%{priority}%'))
    if account_manager:
        query = query.filter(ProjectDetails.Misc_Col1.ilike(f'%{account_manager}%'))
    if team_member:
        query = query.filter(ProjectDetails.Misc_Col1.ilike(f'%{team_member}%'))

    fd = _parse_date(from_date_str)
    td = _parse_date(to_date_str)
    if fd:
        query = query.filter(ProjectDetails.end_date >= fd)
    if td:
        query = query.filter(ProjectDetails.end_date <= td)

    projects = query.order_by(ProjectDetails.created_at.desc()).all()
    return jsonify([_project_to_job_dict(p) for p in projects]), 200


@job_bp.route('/<int:job_id>', methods=['GET'])
@auth_required
def get_job_by_id(job_id: int):
    """
    Retrieve a single job/project.
    GET /api/jobs/<job_id>
    """
    project = _get_or_404(job_id)
    return jsonify(_project_to_job_dict(project)), 200


@job_bp.route('', methods=['POST'])
@auth_required
# @permission_required('project.create')
def create_job():
    """
    Create a new job (project).
    POST /api/jobs
    Body:
    {
        "customer_id": 5,              (required, maps to client_id — must belong to tenant)
        "opportunity_id": 12,          (required, FK → Opportunity_Details)
        "employee_id": 3,              (required, FK → Employee_Master)
        "title": "Kitchen Refit",      (required, also accepted as project_title)
        "start_date": "2025-07-01",    (required)
        "end_date": "2025-09-30",      (also accepted as due_date)
        "address": "1 High St",        (also accepted as location)
        "job_reference": "JOB-XYZ",    (auto-generated if omitted)
        "stage": "In Progress",
        "priority": "High",
        "job_type": "Residential",
        "estimated_value": 15000,
        "account_manager": "Alice",
        "primary_contact": "Bob",
        "team_members": ["Alice", "Bob"],
        "notes": "...",
        "description": "..."
    }
    """
    data = request.get_json() or {}

    client_id      = data.get('customer_id') or data.get('client_id')
    opportunity_id = data.get('opportunity_id')
    employee_id    = data.get('employee_id')
    title          = data.get('title') or data.get('project_title') or data.get('job_name')
    start_date     = _parse_date(data.get('start_date'))

    missing = []
    if not client_id:      missing.append('customer_id')
    if not opportunity_id: missing.append('opportunity_id')
    if not employee_id:    missing.append('employee_id')
    if not title:          missing.append('title')
    if not start_date:     missing.append('start_date')
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400

    # Validate client exists AND belongs to the current tenant
    client = ClientMaster.query.filter_by(
        client_id=client_id, tenant_id=g.tenant_id
    ).first()
    if not client:
        return jsonify({'error': 'Invalid customer_id — not found for this tenant'}), 400

    misc = _build_misc(data)
    if not misc.get('job_reference'):
        misc['job_reference'] = _generate_job_reference()

    project = ProjectDetails(
        client_id=client_id,
        opportunity_id=opportunity_id,
        project_title=title,
        project_description=data.get('description') or data.get('project_description'),
        start_date=start_date,
        end_date=_parse_date(data.get('end_date') or data.get('due_date')),
        employee_id=employee_id,
        address=data.get('address') or data.get('location'),
        Misc_Col1=json.dumps(misc)
    )

    try:
        db.session.add(project)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid foreign key reference — check opportunity_id or employee_id'}), 409

    return jsonify(_project_to_job_dict(project)), 201


@job_bp.route('/<int:job_id>', methods=['PUT'])
@auth_required
# @permission_required('project.update')
def update_job(job_id: int):
    """
    Update a job/project.
    PUT /api/jobs/<job_id>
    All fields optional — only provided fields are changed.
    """
    project = _get_or_404(job_id)
    data = request.get_json() or {}

    if 'title' in data or 'project_title' in data:
        project.project_title = data.get('title') or data.get('project_title')
    if 'description' in data or 'project_description' in data:
        project.project_description = data.get('description') or data.get('project_description')
    if 'employee_id' in data:
        project.employee_id = data['employee_id']
    if 'address' in data or 'location' in data:
        project.address = data.get('address') or data.get('location')

    for date_key, attr in [
        ('start_date', 'start_date'),
        ('end_date',   'end_date'),
        ('due_date',   'end_date'),
    ]:
        if date_key in data:
            parsed = _parse_date(data[date_key])
            if parsed:
                setattr(project, attr, parsed)

    # Merge misc fields
    existing_misc = _misc_to_dict(project.Misc_Col1)
    updated_misc  = _build_misc(data, existing=existing_misc)
    project.Misc_Col1 = json.dumps(updated_misc) if updated_misc else project.Misc_Col1

    project.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid foreign key reference'}), 409

    return jsonify({'message': 'Job updated successfully', 'job': _project_to_job_dict(project)}), 200


@job_bp.route('/<int:job_id>', methods=['DELETE'])
@auth_required
# @permission_required('project.delete')
def delete_job(job_id: int):
    """
    Delete a job/project.
    DELETE /api/jobs/<job_id>
    """
    project = _get_or_404(job_id)

    try:
        db.session.delete(project)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Cannot delete job — it is referenced by other records (e.g. invoices, contracts)'}), 409

    return jsonify({'message': 'Job deleted successfully'}), 200


# ─────────────────────────────────────────
# Pipeline  (replaces old Customer.stage view)
# Already correctly scoped via OpportunityDetails.tenant_id — no changes needed.
# ─────────────────────────────────────────

@job_bp.route('/pipeline-opportunities', methods=['GET'])
@auth_required
def get_pipeline_opportunities():
    """
    Return opportunities in a specific stage for the jobs pipeline view.

    Old code queried Customer.stage == 'Closed Won'. In the new schema
    stage lives on Opportunity_Details.stage_id → Stage_Master.
    We resolve the stage by name so existing front-end consumers keep working.

    GET /api/jobs/pipeline-opportunities?stage=Closed Won
    """
    stage_name = request.args.get('stage', 'Closed Won')

    stage = StageMaster.query.filter(
        StageMaster.stage_name.ilike(stage_name)
    ).first()

    if not stage:
        return jsonify([]), 200   # Unknown stage → empty list (don't 404)

    opps = (
        OpportunityDetails.query
        .filter_by(tenant_id=g.tenant_id, stage_id=stage.stage_id)
        .filter(OpportunityDetails.deleted_at.is_(None))
        .order_by(OpportunityDetails.created_at.desc())
        .all()
    )

    items = []
    for o in opps:
        client_name = None
        client_email = None
        client_phone = None
        client_address = None
        if hasattr(o, 'client') and o.client:
            client_name    = o.client.client_company_name
            client_email   = o.client.client_email
            client_phone   = o.client.client_phone
            client_address = o.client.address

        items.append({
            'id':                   o.opportunity_id,
            'opportunity_id':       o.opportunity_id,
            'opportunity_name':     o.opportunity_title,
            'opportunity_reference': f'OPP-{o.opportunity_id}',
            'stage_id':             o.stage_id,
            'stage':                stage_name,
            'opportunity_value':    o.opportunity_value,
            'currency_id':          o.currency_id,
            'service_id':           o.service_id,
            'assigned_to_employee_id': o.assigned_to_employee_id,
            'start_date':           o.start_date.isoformat()  if o.start_date  else None,
            'end_date':             o.end_date.isoformat()    if o.end_date    else None,
            'created_at':           o.created_at.isoformat()  if o.created_at  else None,
            'client': {
                'client_id':   o.client_id,
                'name':        client_name,
                'email':       client_email,
                'phone':       client_phone,
                'address':     client_address,
            },
        })

    return jsonify(items), 200


@job_bp.route('/pipeline-opportunities/<int:opportunity_id>/stage', methods=['PUT'])
@auth_required
# @permission_required('opportunity.update')
def update_pipeline_opportunity_stage(opportunity_id: int):
    """
    Update the stage_id of an opportunity from the jobs pipeline view.
    PUT /api/jobs/pipeline-opportunities/<opportunity_id>/stage
    Body: { "stage_id": 3 }

    Old code used Customer.job_workflow_stage (varchar) — replaced with
    Opportunity_Details.stage_id (FK → Stage_Master).
    """
    opp = OpportunityDetails.query.filter_by(
        opportunity_id=opportunity_id, tenant_id=g.tenant_id
    ).first()
    if not opp:
        abort(404, description='Opportunity not found')

    data = request.get_json() or {}
    stage_id = data.get('stage_id')
    if stage_id is None:
        return jsonify({'error': 'stage_id is required'}), 400

    stage = db.session.get(StageMaster, int(stage_id))
    if not stage:
        return jsonify({'error': f'stage_id {stage_id} does not exist in Stage_Master'}), 400

    old_stage_id    = opp.stage_id
    opp.stage_id    = stage.stage_id

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
        'message':        'Stage updated successfully',
        'opportunity_id': opp.opportunity_id,
        'old_stage_id':   old_stage_id,
        'new_stage_id':   opp.stage_id,
        'stage_name':     stage.stage_name,
    }), 200


# ─────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────

def _get_or_404(job_id: int) -> ProjectDetails:
    """
    Fetch a project by PK and verify it belongs to the current tenant.
    Tenant check: join through Client_Master.tenant_id (client_id is NOT NULL).
    Replaces unscoped query.get().
    """
    project = (
        ProjectDetails.query
        .join(ClientMaster, ProjectDetails.client_id == ClientMaster.client_id)
        .filter(
            ProjectDetails.project_id == job_id,
            ClientMaster.tenant_id == g.tenant_id,
        )
        .first()
    )
    if not project:
        abort(404, description='Job not found')
    return project