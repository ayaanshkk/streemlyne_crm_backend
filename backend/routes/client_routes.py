"""
Client Routes
Handles: Client_Master, Client_Interactions

Schema alignment (StreemLyne_MT):
  Client_Master:
    client_id (PK), tenant_id (FK→Tenant_Master), client_company_name,
    client_contact_name, address, country_id (FK→Country_Master),
    post_code, client_phone, client_email, client_website,
    default_currency_id (FK→Currency_Master), created_at

  Client_Interactions:
    interaction_id (PK), client_id (FK→Client_Master), contact_date,
    contact_method (smallint), notes, next_steps, reminder_date, created_at

MULTI-TENANT ALIGNMENT:
  - Tenant_Master (tenant_id): Companies using the application
  - Client_Master (client_id): Customers created by each tenant  
  - Customer_Auth: User authentication (handled in auth_routes.py)
  
NOTE: This file includes legacy field aliases for backwards compatibility
with the deprecated customer_routes.py. All CRUD operations are unified here.
"""

from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy.exc import IntegrityError
from database import db
from models import ClientMaster, ClientInteractions
from middleware import auth_required, permission_required
from datetime import datetime

client_bp = Blueprint('client', __name__, url_prefix='/api/clients')


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
      name      – partial match on client_company_name
      country_id – filter by country
    """
    # Removed debug logging
    query = ClientMaster.query.filter_by(tenant_id=g.tenant_id)

    name_q = request.args.get('name')
    country_id = request.args.get('country_id', type=int)

    if name_q:
        query = query.filter(ClientMaster.client_company_name.ilike(f'%{name_q}%'))
    if country_id:
        query = query.filter_by(country_id=country_id)

    clients = query.order_by(ClientMaster.created_at.desc()).all()
    # Removed debug logging
    return jsonify([_client_dict(c) for c in clients]), 200


@client_bp.route('', methods=['POST'])
@auth_required
# @permission_required('client.create')
def create_client():
    """
    Create a new client.
    POST /api/clients
    Body:
    {
        "client_company_name": "Acme Ltd",       (required; also accepted as "name")
        "client_contact_name": "John Smith",     (also accepted as "contact_name")
        "client_email": "john@acme.com",         (also accepted as "email")
        "client_phone": "555-0100",              (also accepted as "phone")
        "address": "1 High Street",
        "post_code": "SW1A 1AA",                 (also accepted as "postcode")
        "country_id": 1,
        "default_currency_id": 1,
        "client_website": "https://acme.com"
    }
    Accepts both canonical schema names and legacy field names for backwards compatibility.
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
        client_website=data.get('client_website')
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
    Retrieve a single client with their interaction history, opportunities, and form submissions.
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


@client_bp.route('/<int:client_id>', methods=['PUT'])
@auth_required
# @permission_required('client.update')
def update_client(client_id: int):
    """
    Update a client record.
    PUT /api/clients/<client_id>
    Accepts both canonical schema names and legacy field names for backwards compatibility.
    """
    client = _get_or_404(client_id)
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

    return jsonify({'message': 'Client updated successfully', 'client': _client_dict(client)}), 200


@client_bp.route('/<int:client_id>', methods=['DELETE'])
@auth_required
# @permission_required('client.delete')
def delete_client(client_id: int):
    """
    Delete a client record.
    DELETE /api/clients/<client_id>

    Note: raises 409 if the client is referenced by Opportunity_Details,
    Customer_Auth, or other FK-constrained tables.
    """
    client = _get_or_404(client_id)

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
# Client Interactions – CRUD
# ─────────────────────────────────────────

@client_bp.route('/<int:client_id>/interactions', methods=['GET'])
@auth_required
def list_interactions(client_id: int):
    """
    List all interaction records for a client.
    GET /api/clients/<client_id>/interactions
    """
    _get_or_404(client_id)

    interactions = (
        ClientInteractions.query
        .filter_by(client_id=client_id)
        .order_by(ClientInteractions.contact_date.desc())
        .all()
    )
    return jsonify([_interaction_dict(i) for i in interactions]), 200


@client_bp.route('/<int:client_id>/interactions', methods=['POST'])
@auth_required
# @permission_required('client.interaction.create')
def create_interaction(client_id: int):
    """
    Log a new interaction for a client.
    POST /api/clients/<client_id>/interactions
    Body:
    {
        "contact_date": "2025-06-01",   (required)
        "contact_method": 1,            (required, smallint → lookup value)
        "notes": "Called to discuss renewal",
        "next_steps": "Send proposal by Friday",
        "reminder_date": "2025-06-05"
    }
    """
    _get_or_404(client_id)
    data = request.get_json() or {}

    if not data.get('contact_date') or data.get('contact_method') is None:
        return jsonify({'error': 'contact_date and contact_method are required'}), 400

    interaction = ClientInteractions(
        client_id=client_id,
        contact_date=_parse_date(data['contact_date']),
        contact_method=int(data['contact_method']),
        notes=data.get('notes'),
        next_steps=data.get('next_steps'),
        reminder_date=_parse_date(data.get('reminder_date'))
    )

    db.session.add(interaction)
    db.session.commit()
    return jsonify(_interaction_dict(interaction)), 201


@client_bp.route('/<int:client_id>/interactions/<int:interaction_id>', methods=['PUT'])
@auth_required
# @permission_required('client.interaction.update')
def update_interaction(client_id: int, interaction_id: int):
    """
    Update a logged interaction.
    PUT /api/clients/<client_id>/interactions/<interaction_id>
    """
    _get_or_404(client_id)
    interaction = _get_interaction_or_404(interaction_id, client_id)
    data = request.get_json() or {}

    if 'contact_date' in data:
        interaction.contact_date = _parse_date(data['contact_date'])
    if 'contact_method' in data:
        interaction.contact_method = int(data['contact_method'])
    if 'notes' in data:
        interaction.notes = data['notes']
    if 'next_steps' in data:
        interaction.next_steps = data['next_steps']
    if 'reminder_date' in data:
        interaction.reminder_date = _parse_date(data['reminder_date'])

    db.session.commit()
    return jsonify({
        'message': 'Interaction updated',
        'interaction': _interaction_dict(interaction)
    }), 200


@client_bp.route('/<int:client_id>/interactions/<int:interaction_id>', methods=['DELETE'])
@auth_required
# @permission_required('client.interaction.delete')
def delete_interaction(client_id: int, interaction_id: int):
    """
    Delete an interaction record.
    DELETE /api/clients/<client_id>/interactions/<interaction_id>
    """
    _get_or_404(client_id)
    interaction = _get_interaction_or_404(interaction_id, client_id)
    db.session.delete(interaction)
    db.session.commit()
    return jsonify({'message': 'Interaction deleted'}), 200


# ─────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────

def _get_or_404(client_id: int) -> ClientMaster:
    """Fetch a Client_Master row scoped to the current tenant or abort 404."""
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
    """Parse an ISO date string to a Python date; returns None on failure."""
    if not value:
        return None
    if hasattr(value, 'date'):
        return value.date()
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


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
        'id':             c.client_id,
        'name':           c.client_company_name,
        'company_name':   c.client_company_name,
        'contact_name':   c.client_contact_name,
        'client_name':    c.client_contact_name or c.client_company_name,
        'display_name':   c.client_contact_name or c.client_company_name,
        'full_name':      c.client_contact_name or c.client_company_name,
        'email':          c.client_email,
        'phone':          c.client_phone,
        'postcode':       c.post_code,
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

@client_bp.route('/<int:client_id>/stage', methods=['PATCH'])
@auth_required
# @permission_required('client.update')
def update_client_stage(client_id: int):
    """
    Update a client's stage.
    PATCH /api/clients/<client_id>/stage
    Body:
    {
        "stage": "Qualified",
        "reason": "Customer responded positively",
        "updated_by": "current_user"
    }
    """
    client = _get_or_404(client_id)
    data = request.get_json() or {}

    new_stage = data.get('stage')
    reason = data.get('reason', '')
    updated_by = data.get('updated_by', 'system')

    if not new_stage:
        return jsonify({'error': 'stage is required'}), 400

    # Update the stage
    old_stage = client.stage if hasattr(client, 'stage') else None
    client.stage = new_stage

    # You can also log the change to an audit table if you have one
    # AuditLog.create(
    #     entity_type='Client',
    #     entity_id=client_id,
    #     action='update',
    #     changed_by=updated_by,
    #     change_summary=f'Stage changed from {old_stage} to {new_stage}. Reason: {reason}'
    # )

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Failed to update stage'}), 500

    return jsonify({
        'message': 'Stage updated successfully',
        'client': _client_dict(client),
        'old_stage': old_stage,
        'new_stage': new_stage
    }), 200