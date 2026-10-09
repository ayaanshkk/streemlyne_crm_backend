from services.usage_service import check_customer_limit
from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy.exc import IntegrityError
from database import db
from models import ClientMaster, ClientInteractions
from middleware import auth_required, permission_required
from datetime import datetime, timezone
from services.subscription_service import SubscriptionService
from middleware.access_control import (
    require_write_access,
    check_record_ownership,
    handle_access_denied,
    AccessDenied,
)

client_bp = Blueprint('client', __name__, url_prefix='/clients')

TRIAL_CLIENT_LIMIT: int = 10


# ─────────────────────────────────────────
# Trial limit helper
# ─────────────────────────────────────────

def _check_trial_client_limit() -> dict | None:
    """
    [LIMIT-003] Check whether the tenant is on a trial and has hit the
    customer creation limit.

    Returns a dict with limit info if the limit IS reached (caller should
    return a 403 response), or None if the tenant is allowed to proceed.
    """
    svc    = SubscriptionService()
    status = svc.check_subscription_status(g.tenant_id)

    if status.get("status") != "trialing":
        return None

    current_count = (
        ClientMaster.query
        .filter_by(tenant_id=str(g.tenant_id))
        .count()
    )

    if current_count < TRIAL_CLIENT_LIMIT:
        return None

    return {
        "error":         "trial_limit_reached",
        "message":       f"Free trial is limited to {TRIAL_CLIENT_LIMIT} customers. "
                         f"Upgrade your plan to add more.",
        "limit":         TRIAL_CLIENT_LIMIT,
        "current_count": current_count,
        "is_trial":      True,
        "upgrade_url":   "/dashboard/subscription",
    }


# ─────────────────────────────────────────
# [LIMIT-002] Trial limit check endpoint
# NOTE: Must be registered BEFORE /<int:client_id> routes
# ─────────────────────────────────────────

@client_bp.route('/limit-check', methods=['GET'])
@auth_required
def check_client_limit():
    """
    [LIMIT-002] Return trial status and customer count for the tenant.
    GET /api/clients/limit-check

    Response (trial, under limit):
    { "is_trial": true, "limit": 10, "current_count": 7,
      "limit_reached": false, "remaining": 3 }

    Response (trial, limit hit):
    { "is_trial": true, "limit": 10, "current_count": 10,
      "limit_reached": true, "remaining": 0,
      "upgrade_url": "/dashboard/subscription" }

    Response (paid plan):
    { "is_trial": false, "limit": null, "current_count": 42,
      "limit_reached": false, "remaining": null }
    """
    svc      = SubscriptionService()
    status   = svc.check_subscription_status(g.tenant_id)
    is_trial = status.get("status") == "trialing"

    current_count = (
        ClientMaster.query
        .filter_by(tenant_id=str(g.tenant_id))
        .count()
    )

    if not is_trial:
        return jsonify({
            "is_trial":      False,
            "limit":         None,
            "current_count": current_count,
            "limit_reached": False,
            "remaining":     None,
        }), 200

    limit_reached = current_count >= TRIAL_CLIENT_LIMIT
    remaining     = max(0, TRIAL_CLIENT_LIMIT - current_count)

    return jsonify({
        "is_trial":      True,
        "limit":         TRIAL_CLIENT_LIMIT,
        "current_count": current_count,
        "limit_reached": limit_reached,
        "remaining":     remaining,
        **({"upgrade_url": "/dashboard/subscription"} if limit_reached else {}),
    }), 200


# ─────────────────────────────────────────
# Client Master – CRUD
# ─────────────────────────────────────────

@client_bp.route('', methods=['GET'])
@auth_required
def list_clients():
    """
    List all clients for the current tenant.
    GET /api/clients
    Query params:
      name       – partial match on client_company_name
      country_id – filter by country
    """
    query = ClientMaster.query.filter_by(tenant_id=g.tenant_id)

    name_q     = request.args.get('name')
    country_id = request.args.get('country_id', type=int)

    if name_q:
        query = query.filter(ClientMaster.client_company_name.ilike(f'%{name_q}%'))
    if country_id:
        query = query.filter_by(country_id=country_id)

    clients = query.order_by(ClientMaster.created_at.desc()).all()
    return jsonify([_client_dict(c) for c in clients]), 200


@client_bp.route('', methods=['POST'])
@auth_required
@require_write_access
def create_client():
    """
    Create a new client.
    POST /api/clients

    [LIMIT-004] Trial tenants are blocked once they reach TRIAL_CLIENT_LIMIT.
    Returns 403 { "error": "trial_limit_reached", ... } when the limit is hit.
    """
    # ── Limit check ───────────────────────────────────────────────────────────
    err = check_customer_limit(str(g.tenant_id))
    if err:
        return jsonify({"error": err, "limit_reached": True, "resource": "customers"}), 403
    # ─────────────────────────────────────────────────────────────────────────

    data = request.get_json() or {}

    name = (
        data.get('client_company_name')
        or data.get('name')
        or ''
    ).strip()

    if not name:
        return jsonify({'error': 'client_company_name is required'}), 400

    client = ClientMaster(
        created_by_employee_id = getattr(g, 'employee_id', None),
        tenant_id           = g.tenant_id,
        client_company_name = name,
        client_contact_name = data.get('client_contact_name') or data.get('contact_name'),
        client_email        = (
            (data.get('client_email') or data.get('email') or '').lower().strip() or None
        ),
        client_phone        = data.get('client_phone') or data.get('phone'),
        address             = data.get('address'),
        post_code           = data.get('post_code') or data.get('postcode'),
        country_id          = data.get('country_id'),
        default_currency_id = data.get('default_currency_id'),
        client_website      = data.get('client_website'),
        stage               = data.get('stage') or 'Lead',
    )

    try:
        db.session.add(client)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'A client with these details already exists'}), 409

    return jsonify(_client_dict(client)), 201


@client_bp.route('/<int:client_id>', methods=['GET'])
@auth_required
def get_client(client_id: int):
    """
    Retrieve a single client with their interaction history and opportunities.
    GET /api/clients/<client_id>
    """
    client = _get_or_404(client_id)

    interactions = (
        ClientInteractions.query
        .filter_by(client_id=client_id)
        .order_by(ClientInteractions.contact_date.desc())
        .all()
    )

    from models import OpportunityDetails
    opportunities = (
        OpportunityDetails.query
        .filter_by(client_id=client_id, tenant_id=g.tenant_id)
        .filter(OpportunityDetails.deleted_at.is_(None))
        .order_by(OpportunityDetails.created_at.desc())
        .all()
    )

    result = _client_dict(client)
    result['interactions'] = [_interaction_dict(i) for i in interactions]
    result['opportunities'] = [
        {
            'opportunity_id':          o.opportunity_id,
            'opportunity_title':       o.opportunity_title,
            'opportunity_description': o.opportunity_description,
            'stage_id':                o.stage_id,
            'opportunity_value':       o.opportunity_value,
            'currency_id':             o.currency_id,
            'service_id':              o.service_id,
            'start_date':              o.start_date.isoformat() if o.start_date else None,
            'end_date':                o.end_date.isoformat() if o.end_date else None,
            'created_at':              o.created_at.isoformat() if o.created_at else None,
        }
        for o in opportunities
    ]

    return jsonify(result), 200


@client_bp.route("/<int:client_id>", methods=["PUT"])
@auth_required
@require_write_access 
def update_client(client_id: int):
    """
    Update a client record.
    PUT /api/clients/<client_id>
    Accepts both canonical schema names and legacy field names.
    """
    client = _get_or_404(client_id)
    try:
        check_record_ownership(client)
    except AccessDenied as e:
        return handle_access_denied(e)

    data   = request.get_json() or {}

    field_map = [
        ('client_company_name', ['client_company_name', 'name']),
        ('client_contact_name', ['client_contact_name', 'contact_name']),
        ('client_email',        ['client_email', 'email']),
        ('client_phone',        ['client_phone', 'phone']),
        ('address',             ['address']),
        ('post_code',           ['post_code', 'postcode']),
        ('country_id',          ['country_id']),
        ('default_currency_id', ['default_currency_id']),
        ('client_website',      ['client_website']),
        ('stage',               ['stage']),
    ]

    for attr, keys in field_map:
        for key in keys:
            if key in data and data[key] is not None:
                setattr(client, attr, data[key])
                break

    try:
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        return jsonify({'error': 'Update violates a data constraint'}), 409

    return jsonify({'message': 'Client updated successfully', 'client': _client_dict(client)}), 200


@client_bp.route('/<int:client_id>', methods=['PATCH'])
@auth_required
@require_write_access
def patch_client(client_id: int):
    """
    Partial update — stage change, pipeline drag-and-drop, etc.
    PATCH /api/clients/<client_id>
    Body: { "stage": "Qualified" }
    """
    client = _get_or_404(client_id)
    try:
        check_record_ownership(client)
    except AccessDenied as e:
        return handle_access_denied(e)
    data   = request.get_json() or {}

    if 'stage' in data:
        old_stage = client.stage
        new_stage = data['stage']
        if old_stage != new_stage:
            client.stage             = new_stage
            client.stage_updated_at  = datetime.now(timezone.utc)

    # Allow patching other simple fields too
    for field in ('client_company_name', 'client_contact_name',
                  'client_email', 'client_phone', 'address', 'post_code'):
        if field in data:
            setattr(client, field, data[field])

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Update violates a data constraint'}), 409

    return jsonify({
        'message':          'Client updated successfully',
        'client_id':        client.client_id,
        'stage':            client.stage,
        'stage_updated_at': client.stage_updated_at.isoformat() if client.stage_updated_at else None,
    }), 200


@client_bp.route('/<int:client_id>', methods=['DELETE'])
@auth_required
@require_write_access
def delete_client(client_id: int):
    """
    Delete a client record.
    DELETE /api/clients/<client_id>
    """
    client = _get_or_404(client_id)
    try:
        check_record_ownership(client)
    except AccessDenied as e:
        return handle_access_denied(e)

    try:
        db.session.delete(client)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'error': 'Cannot delete client — they are referenced by existing records'
        }), 409

    return jsonify({'message': 'Client deleted successfully'}), 200

# ─────────────────────────────────────────
# Pipeline endpoint
# ─────────────────────────────────────────

@client_bp.route('/pipeline', methods=['GET'])
@auth_required
def get_pipeline_data():
    """
    Returns customers formatted for pipeline/kanban view.
    GET /api/clients/pipeline
    """
    customers = ClientMaster.query.filter_by(tenant_id=g.tenant_id).all()

    pipeline_items = []
    for c in customers:
        pipeline_items.append({
            'id':   f'customer-{c.client_id}',
            'type': 'customer',
            'customer': {
                'id':                       str(c.client_id),
                'name':                     c.client_contact_name or c.client_company_name or 'Unknown',
                'company_name':             c.client_company_name,
                'address':                  c.address,
                'postcode':                 c.post_code,
                'phone':                    c.client_phone,
                'email':                    c.client_email,
                'contact_made':             'Unknown',
                'preferred_contact_method': None,
                'marketing_opt_in':         False,
                'stage':                    c.stage or 'Lead',
                'salesperson':              None,
                'notes':                    None,
                'industry':                 None,
                'company_size':             None,
                'status':                   'Active',
                'created_at':               c.created_at.isoformat() if c.created_at else None,
                'stage_updated_at':         c.stage_updated_at.isoformat() if c.stage_updated_at else None,
            },
            'stage':           c.stage or 'Lead',
            'estimated_value': None,
            'end_date':        None,
            'created_at':      c.created_at.isoformat() if c.created_at else None,
        })

    return jsonify(pipeline_items), 200

# ─────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────

def _get_or_404(client_id: int) -> ClientMaster:
    client = ClientMaster.query.filter_by(
        client_id=client_id,
        tenant_id=g.tenant_id
    ).first()
    if not client:
        abort(404, description='Client not found')
    return client


def _get_interaction_or_404(interaction_id: int, client_id: int) -> ClientInteractions:
    interaction = ClientInteractions.query.filter_by(
        interaction_id=interaction_id,
        client_id=client_id
    ).first()
    if not interaction:
        abort(404, description='Interaction not found')
    return interaction


def _parse_date(value):
    if not value:
        return None
    if hasattr(value, 'date'):
        return value.date()
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _client_dict(c: ClientMaster) -> dict:
    return {
        # Canonical schema fields
        'client_id':            c.client_id,
        'tenant_id':            c.tenant_id,
        'client_company_name':  c.client_company_name,
        'client_contact_name':  c.client_contact_name,
        'client_email':         c.client_email,
        'client_phone':         c.client_phone,
        'address':              c.address,
        'post_code':            c.post_code,
        'country_id':           c.country_id,
        'default_currency_id':  c.default_currency_id,
        'client_website':       c.client_website,
        'created_at':           c.created_at.isoformat() if c.created_at else None,
        'stage':                c.stage or 'Lead',
        'stage_updated_at':     c.stage_updated_at.isoformat() if c.stage_updated_at else None,
        # Legacy aliases
        'id':           c.client_id,
        'name':         c.client_company_name,
        'company_name': c.client_company_name,
        'contact_name': c.client_contact_name,
        'client_name':  c.client_contact_name or c.client_company_name,
        'display_name': c.client_contact_name or c.client_company_name,
        'full_name':    c.client_contact_name or c.client_company_name,
        'email':        c.client_email,
        'phone':        c.client_phone,
        'postcode':     c.post_code,
        'assigned_employee_id':   c.assigned_employee_id,
        'created_by_employee_id': c.created_by_employee_id,
    }

def _interaction_dict(i: ClientInteractions) -> dict:
    return {
        'interaction_id': i.interaction_id,
        'client_id':      i.client_id,
        'contact_date':   i.contact_date.isoformat() if i.contact_date else None,
        'contact_method': i.contact_method,
        'notes':          i.notes,
        'next_steps':     i.next_steps,
        'reminder_date':  i.reminder_date.isoformat() if i.reminder_date else None,
        'created_at':     i.created_at.isoformat() if i.created_at else None,
    }

# ─────────────────────────────────────────
# Documents
# ─────────────────────────────────────────

@client_bp.route('/<int:client_id>/documents', methods=['GET'])
@auth_required
def list_documents(client_id: int):
    """
    List all documents uploaded for a client.
    GET /api/clients/<client_id>/documents
    """
    _get_or_404(client_id)

    from models import CustomerDocuments
    docs = (
        CustomerDocuments.query
        .filter_by(client_id=client_id)
        .order_by(CustomerDocuments.uploaded_at.desc())
        .all()
    )

    return jsonify([
        {
            'id':         str(d.id),
            'filename':   d.file_name,
            'url':        d.file_url,
            'created_at': d.uploaded_at.isoformat() if d.uploaded_at else None,
            'notes':      None,
        }
        for d in docs
    ]), 200


@client_bp.route('/<int:client_id>/documents', methods=['POST'])
@auth_required
@require_write_access
def upload_document(client_id: int):
    """
    Upload a document for a client.
    POST /api/clients/<client_id>/documents  (multipart/form-data)
    """
    _get_or_404(client_id)

    from flask import current_app
    from werkzeug.utils import secure_filename
    from models import CustomerDocuments
    import os

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'error': 'No file provided'}), 400

    filename = secure_filename(file.filename)
    upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    client_folder = os.path.join(upload_folder, f'client_{client_id}')
    os.makedirs(client_folder, exist_ok=True)

    file.save(os.path.join(client_folder, filename))

    base_url = os.getenv('BACKEND_URL', 'http://127.0.0.1:5000')
    file_url = f"{base_url}/uploads/client_{client_id}/{filename}"

    doc = CustomerDocuments(
        client_id=client_id,
        file_name=filename,
        file_url=file_url,
    )
    db.session.add(doc)
    db.session.commit()

    return jsonify({
        'document': {
            'id':         str(doc.id),
            'filename':   doc.file_name,
            'url':        doc.file_url,
            'created_at': doc.uploaded_at.isoformat() if doc.uploaded_at else None,
            'notes':      None,
        }
    }), 201


@client_bp.route('/<int:client_id>/documents/<int:doc_id>', methods=['DELETE'])
@auth_required
@require_write_access
def delete_document(client_id: int, doc_id: int):
    """
    Delete a document.
    DELETE /api/clients/<client_id>/documents/<doc_id>
    """
    _get_or_404(client_id)

    from flask import current_app
    from models import CustomerDocuments
    import os

    doc = CustomerDocuments.query.filter_by(id=doc_id, client_id=client_id).first()
    if not doc:
        return jsonify({'error': 'Document not found'}), 404

    # Remove physical file if stored locally
    try:
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        file_path = os.path.join(upload_folder, f'client_{client_id}', doc.file_name)
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass

    db.session.delete(doc)
    db.session.commit()
    return jsonify({'message': 'Document deleted'}), 200


# ─────────────────────────────────────────
# Financial Documents
# ─────────────────────────────────────────

@client_bp.route('/<int:client_id>/financial-documents', methods=['GET'])
@auth_required
def list_financial_documents(client_id: int):
    """
    Return all proposals (quotations) and invoices for a client,
    combined into a single list ordered newest first.

    GET /api/clients/<client_id>/financial-documents

    Uses the same tenant-scoping approach as proposal_routes and
    invoice_routes — both tables scope via Client_Master.tenant_id.

    Response shape matches the frontend FinancialDocument interface:
      { id, type, title, reference, total, amount_paid, balance,
        status, created_at }
    """
    # Verify client belongs to this tenant
    _get_or_404(client_id)

    from models import ProposalMaster, InvoiceMaster

    docs = []

    # ── Proposals / Quotations ────────────────────────────────────────────
    # proposal_routes scopes via Client_Master join; mirror that here.
    proposals = (
        ProposalMaster.query
        .filter_by(client_id=client_id)
        .order_by(ProposalMaster.created_at.desc())
        .all()
    )

    for p in proposals:
        total = float(p.total_amount) if p.total_amount is not None else 0.0
        docs.append({
            'id':          p.proposal_id,
            'type':        'quotation',
            'title':       f"Quote {p.quote_id or f'#{p.proposal_id}'}",
            'reference':   str(p.quote_id) if p.quote_id else f"#{p.proposal_id}",
            'total':       total,
            'amount_paid': 0.0,
            'balance':     total,
            'status':      'draft',
            'created_at':  p.created_at.isoformat() if p.created_at else None,
        })

    # ── Invoices ──────────────────────────────────────────────────────────
    # invoice_routes scopes via or_(client_id, project_id) through
    # Client_Master. For the customer detail page we only need client_id.
    invoices = (
        InvoiceMaster.query
        .filter_by(client_id=client_id)
        .order_by(InvoiceMaster.created_at.desc())
        .all()
    )

    for inv in invoices:
        total       = float(inv.total_amount) if inv.total_amount is not None else 0.0
        paid_status = (inv.payment_status or 'not paid').lower()
        amount_paid = total if paid_status == 'paid' else 0.0
        balance     = 0.0  if paid_status == 'paid' else total

        docs.append({
            'id':          inv.invoice_id,
            'type':        'invoice',
            'title':       f"Invoice #{inv.invoice_number}",
            'reference':   inv.invoice_number,
            'total':       total,
            'amount_paid': amount_paid,
            'balance':     balance,
            'status':      paid_status,
            'created_at':  inv.created_at.isoformat() if inv.created_at else None,
        })

    # Newest first across both types
    docs.sort(key=lambda d: d['created_at'] or '', reverse=True)

    return jsonify(docs), 200