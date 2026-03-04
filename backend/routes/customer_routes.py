"""
DEPRECATED - Customer Routes

THIS FILE IS DEPRECATED. All functionality has been moved to client_routes.py.

Legacy route handlers for backwards compatibility. Use /api/clients instead.

Handles: ClientMaster CRUD (legacy compatibility aliases).

Schema alignment (StreemLyne_MT):
  Client_Master:
    client_id, tenant_id, client_company_name, client_contact_name,
    address, country_id, post_code, client_phone, client_email,
    client_website, default_currency_id, created_at

IMPORTANT — removed routes:
  The old /customers route had two conflicting POST handlers registered on the
  same path. These have been merged into a single handler here.

IMPORTANT — CustomerFormData:
  CustomerFormData is not part of the core StreemLyne_MT schema.
  It is treated as an app-level model. References are kept but guarded so the
  app still starts if the model/table is absent.

NOTE — stage management:
  Client_Master has no `stage` column. Stage belongs to Opportunity_Details
  (via stage_id FK → Stage_Master). The /customers/<id>/stage endpoint is
  retained for backwards compatibility but now correctly updates the linked
  opportunity's stage_id instead of a non-existent column.

MIGRATION GUIDE:
  - Replace /api/customers with /api/clients
  - Replace /api/customers/<id>/stage with PATCH /api/opportunities/<opportunity_id>/stage
  - Customer_Auth operations remain in /api/auth (unchanged)
"""

from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy.exc import IntegrityError
from database import db
from models import ClientMaster, OpportunityDetails
from middleware import auth_required, permission_required

customer_bp = Blueprint('customer', __name__, url_prefix='/api/customers')


# ─────────────────────────────────────────
# Clients – CRUD
# ─────────────────────────────────────────

@customer_bp.route('', methods=['GET'])
@auth_required
def list_customers():
    """
    List all clients for the current tenant.
    GET /api/customers
    Query params:
      name – partial match on client_company_name
    """
    name_q = request.args.get('name')
    query = ClientMaster.query.filter_by(tenant_id=g.tenant_id)

    if name_q:
        query = query.filter(ClientMaster.client_company_name.ilike(f'%{name_q}%'))

    clients = query.order_by(ClientMaster.created_at.desc()).all()
    return jsonify([_client_dict(c) for c in clients]), 200


@customer_bp.route('', methods=['POST'])
@auth_required
@permission_required('client.create')
def create_customer():
    """
    Create a new client.
    POST /api/customers
    Body:
    {
        "client_company_name": "Acme Ltd",   (required; also accepted as "name")
        "client_contact_name": "John Smith", (also accepted as "contact_name")
        "client_email":  "john@acme.com",    (also accepted as "email")
        "client_phone":  "555-0100",         (also accepted as "phone")
        "address":       "1 High Street",
        "post_code":     "SW1A 1AA",         (also accepted as "postcode")
        "country_id":    1,
        "default_currency_id": 1,
        "client_website": "https://acme.com"
    }
    Accepts legacy field aliases so existing front-end callers keep working.
    """
    data = request.get_json() or {}

    name = (
        data.get('client_company_name')
        or data.get('name')
        or ''
    ).strip()

    if not name:
        return jsonify({'error': 'client_company_name is required'}), 400

    client = ClientMaster(
        tenant_id=g.tenant_id,
        client_company_name=name,
        client_contact_name=data.get('client_contact_name') or data.get('contact_name'),
        client_email=(
            (data.get('client_email') or data.get('email') or '').lower().strip() or None
        ),
        client_phone=data.get('client_phone') or data.get('phone'),
        address=data.get('address'),
        post_code=data.get('post_code') or data.get('postcode'),
        country_id=data.get('country_id'),
        default_currency_id=data.get('default_currency_id'),
        client_website=data.get('client_website'),
    )

    try:
        db.session.add(client)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'A client with these details already exists'}), 409

    return jsonify(_client_dict(client)), 201


@customer_bp.route('/<int:customer_id>', methods=['GET'])
@auth_required
def get_customer(customer_id: int):
    """
    Retrieve a single client with their opportunities and form submissions.
    GET /api/customers/<customer_id>
    """
    client = _get_or_404(customer_id)

    opportunities = (
        OpportunityDetails.query
        .filter_by(client_id=client.client_id, tenant_id=g.tenant_id)
        .filter(OpportunityDetails.deleted_at.is_(None))
        .order_by(OpportunityDetails.created_at.desc())
        .all()
    )

    # CustomerFormData is an app-level model outside the core schema.
    # Guarded import so the app still starts when the table doesn't exist yet.
    form_submissions = []
    try:
        from models import CustomerFormData
        import json as _json
        entries = (
            CustomerFormData.query
            .filter_by(client_id=client.client_id, tenant_id=g.tenant_id)
            .order_by(CustomerFormData.submitted_at.desc())
            .all()
        )
        for f in entries:
            try:
                parsed = _json.loads(f.form_data)
            except Exception:
                parsed = {'raw': f.form_data}
            form_submissions.append({
                'id':           f.id,
                'client_id':    f.client_id,
                'token_used':   f.token_used,
                'submitted_at': f.submitted_at.isoformat() if f.submitted_at else None,
                'form_data':    parsed,
                'source':       'web_form',
            })
    except ImportError:
        pass

    result = _client_dict(client)
    result['opportunities'] = [
        {
            'opportunity_id':          o.opportunity_id,
            'opportunity_title':       o.opportunity_title,
            'opportunity_description': o.opportunity_description,
            'stage_id':                o.stage_id,
            'opportunity_value':       o.opportunity_value,
            'currency_id':             o.currency_id,
            'service_id':              o.service_id,
            'start_date':  o.start_date.isoformat()  if o.start_date  else None,
            'end_date':    o.end_date.isoformat()    if o.end_date    else None,
            'created_at':  o.created_at.isoformat()  if o.created_at  else None,
        }
        for o in opportunities
    ]
    result['form_submissions'] = form_submissions
    return jsonify(result), 200


@customer_bp.route('/<int:customer_id>', methods=['PUT'])
@auth_required
@permission_required('client.update')
def update_customer(customer_id: int):
    """
    Update a client record.
    PUT /api/customers/<customer_id>
    Accepts both canonical and legacy field names.
    """
    client = _get_or_404(customer_id)
    data = request.get_json() or {}

    # Each tuple: (model_attr, list_of_accepted_keys_in_priority_order)
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
    ]

    for attr, keys in field_map:
        for key in keys:
            if key in data and data[key] is not None:
                setattr(client, attr, data[key])
                break

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Update violates a data constraint'}), 409

    return jsonify({'message': 'Customer updated successfully', 'client': _client_dict(client)}), 200


@customer_bp.route('/<int:customer_id>', methods=['DELETE'])
@auth_required
@permission_required('client.delete')
def delete_customer(customer_id: int):
    """
    Delete a client.
    DELETE /api/customers/<customer_id>
    Returns 409 if the client is referenced by FK-constrained tables
    (e.g. Opportunity_Details, Customer_Auth).
    """
    client = _get_or_404(customer_id)

    try:
        db.session.delete(client)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'error': 'Cannot delete client — they are referenced by existing records'
        }), 409

    return jsonify({'message': 'Customer deleted successfully'}), 200


# ─────────────────────────────────────────
# Stage Management  (backwards-compat)
# ─────────────────────────────────────────

@customer_bp.route('/<int:customer_id>/stage', methods=['PATCH'])
@auth_required
@permission_required('client.update')
def update_customer_stage(customer_id: int):
    """
    Update the stage of the most-recent open opportunity for this client.
    PATCH /api/customers/<customer_id>/stage
    Body: { "stage_id": 3, "reason": "..." }

    NOTE: Client_Master has no stage column in the new schema.
    Stage is managed via Opportunity_Details.stage_id → Stage_Master.
    This endpoint applies the new stage_id to the latest non-deleted opportunity.
    If no opportunity exists, returns 404.
    """
    client = _get_or_404(customer_id)
    data = request.get_json() or {}

    stage_id = data.get('stage_id')
    if stage_id is None:
        return jsonify({'error': 'stage_id is required'}), 400

    opportunity = (
        OpportunityDetails.query
        .filter_by(client_id=client.client_id, tenant_id=g.tenant_id)
        .filter(OpportunityDetails.deleted_at.is_(None))
        .order_by(OpportunityDetails.created_at.desc())
        .first()
    )

    if not opportunity:
        return jsonify({
            'error': 'No open opportunity found for this client to update stage on'
        }), 404

    opportunity.stage_id = int(stage_id)
    db.session.commit()

    return jsonify({
        'message': 'Stage updated successfully',
        'customer_id': client.client_id,
        'opportunity_id': opportunity.opportunity_id,
        'new_stage_id': opportunity.stage_id,
    }), 200


# ─────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────

def _get_or_404(customer_id: int) -> ClientMaster:
    client = ClientMaster.query.filter_by(
        client_id=customer_id,
        tenant_id=g.tenant_id
    ).first()
    if not client:
        abort(404, description='Customer not found')
    return client


def _client_dict(c: ClientMaster) -> dict:
    """
    Returns both canonical schema names and legacy aliases so existing
    front-end code keeps working without changes.
    """
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
        # Legacy aliases (kept for front-end backwards compatibility)
        'id':       c.client_id,
        'name':     c.client_company_name,
        'email':    c.client_email,
        'phone':    c.client_phone,
        'postcode': c.post_code,
    }