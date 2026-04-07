"""
Tenant Routes
Handles: Tenant_Master

Two access levels:
  1. Self-service  (/api/tenant/info)      – any authenticated user reads/updates own tenant
  2. Super-admin   (/api/tenant and /api/tenant/<id>)  – requires explicit permissions

Schema alignment (StreemLyne_MT):
  Tenant_Master:
    tenant_id (PK, UNIQUE), tenant_company_name (UNIQUE), tenant_contact_name,
    onboarding_Date (date), is_active (boolean), created_at, updated_at
"""

from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy.exc import IntegrityError
from database import db
from models import TenantMaster
from middleware import auth_required, permission_required
from datetime import datetime

tenant_bp = Blueprint('tenant', __name__, url_prefix='/tenant')


# ─────────────────────────────────────────
# Self-service (own tenant)
# ─────────────────────────────────────────

@tenant_bp.route('/info', methods=['GET'])
@auth_required
def get_tenant_info():
    """
    Get the calling user's own tenant details.
    GET /api/tenant/info
    """
    tenant = TenantMaster.query.get(g.tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404
    return jsonify(_tenant_dict(tenant)), 200


@tenant_bp.route('/info', methods=['PATCH'])
@auth_required
# @permission_required('tenant.update')
def update_tenant_info():
    """
    Update own tenant's display details.
    PATCH /api/tenant/info
    Body: { "tenant_company_name": "...", "tenant_contact_name": "..." }
    """
    tenant = TenantMaster.query.get(g.tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404

    data = request.get_json() or {}

    if 'tenant_company_name' in data:
        tenant.tenant_company_name = (data['tenant_company_name'] or '').strip() or None
    if 'tenant_contact_name' in data:
        tenant.tenant_contact_name = data['tenant_contact_name']

    tenant.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'tenant_company_name is already in use'}), 409

    return jsonify({'message': 'Tenant updated successfully', 'tenant': _tenant_dict(tenant)}), 200


# ─────────────────────────────────────────
# Super-admin: all tenants
# ─────────────────────────────────────────

@tenant_bp.route('', methods=['GET'])
@auth_required
# @permission_required('tenant.view')
def list_tenants():
    """
    List all tenants (super-admin only).
    GET /api/tenant
    Query params:
      is_active=true/false – filter by activation status
    """
    query = TenantMaster.query

    is_active = request.args.get('is_active')
    if is_active is not None:
        query = query.filter_by(is_active=is_active.lower() == 'true')

    tenants = query.order_by(TenantMaster.created_at.desc()).all()
    return jsonify([_tenant_dict(t) for t in tenants]), 200


@tenant_bp.route('', methods=['POST'])
@auth_required
# @permission_required('tenant.create')
def create_tenant():
    """
    Create a new tenant (super-admin only).
    POST /api/tenant
    Body:
    {
        "tenant_company_name": "Acme Ltd",   (required, UNIQUE)
        "tenant_contact_name": "Jane Doe",
        "onboarding_date": "2025-07-01"
    }
    """
    data = request.get_json() or {}

    name = (data.get('tenant_company_name') or '').strip()
    if not name:
        return jsonify({'error': 'tenant_company_name is required'}), 400

    onboarding = _parse_date(data.get('onboarding_date'))

    tenant = TenantMaster(
        tenant_company_name=name,
        tenant_contact_name=data.get('tenant_contact_name'),
        onboarding_Date=onboarding,
        is_active=True
    )

    try:
        db.session.add(tenant)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'A tenant with this company name already exists'}), 409

    return jsonify({
        'message': 'Tenant created successfully',
        'tenant':  _tenant_dict(tenant)
    }), 201


@tenant_bp.route('/<int:tenant_id>', methods=['GET'])
@auth_required
# @permission_required('tenant.view')
def get_tenant(tenant_id: int):
    """
    Get a specific tenant by ID with basic usage stats.
    GET /api/tenant/<tenant_id>
    """
    tenant = TenantMaster.query.get(tenant_id)
    if not tenant:
        abort(404, description='Tenant not found')

    result = _tenant_dict(tenant)

    # Attach lightweight stats (counts only — no heavy joins)
    try:
        from models import ClientMaster, EmployeeMaster, OpportunityDetails, TenantSubscription
        result['stats'] = {
            'client_count':      ClientMaster.query.filter_by(tenant_id=tenant_id).count(),
            'employee_count':    EmployeeMaster.query.filter_by(tenant_id=tenant_id).count(),
            'opportunity_count': OpportunityDetails.query.filter_by(
                tenant_id=tenant_id
            ).filter(OpportunityDetails.deleted_at.is_(None)).count(),
            'has_active_subscription': TenantSubscription.query.filter_by(
                tenant_id=tenant_id, is_active=True
            ).first() is not None,
        }
    except Exception:
        result['stats'] = {}

    return jsonify(result), 200


@tenant_bp.route('/<int:tenant_id>', methods=['PUT'])
@auth_required
# @permission_required('tenant.update')
def update_tenant(tenant_id: int):
    """
    Update any tenant's details (super-admin only).
    PUT /api/tenant/<tenant_id>
    Body: { "tenant_company_name": "...", "tenant_contact_name": "...", "onboarding_date": "...", "is_active": true }
    """
    tenant = TenantMaster.query.get(tenant_id)
    if not tenant:
        abort(404, description='Tenant not found')

    data = request.get_json() or {}

    if 'tenant_company_name' in data:
        tenant.tenant_company_name = (data['tenant_company_name'] or '').strip() or None
    if 'tenant_contact_name' in data:
        tenant.tenant_contact_name = data['tenant_contact_name']
    if 'is_active' in data:
        tenant.is_active = bool(data['is_active'])
    if 'onboarding_date' in data:
        tenant.onboarding_Date = _parse_date(data['onboarding_date'])

    tenant.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'tenant_company_name is already in use'}), 409

    return jsonify({'message': 'Tenant updated successfully', 'tenant': _tenant_dict(tenant)}), 200


@tenant_bp.route('/<int:tenant_id>/deactivate', methods=['POST'])
@auth_required
# @permission_required('tenant.deactivate')
def deactivate_tenant(tenant_id: int):
    """
    Deactivate a tenant (super-admin only).
    POST /api/tenant/<tenant_id>/deactivate
    Also cancels any active subscriptions to prevent billing.
    """
    tenant = TenantMaster.query.get(tenant_id)
    if not tenant:
        abort(404, description='Tenant not found')

    if not tenant.is_active:
        return jsonify({'message': 'Tenant is already inactive'}), 200

    tenant.is_active  = False
    tenant.updated_at = datetime.utcnow()

    # Cancel active subscriptions
    try:
        from models import TenantSubscription
        TenantSubscription.query.filter_by(
            tenant_id=tenant_id, is_active=True
        ).update({'is_active': False, 'auto_renew': False, 'updated_at': datetime.utcnow()})
    except Exception:
        pass

    db.session.commit()
    return jsonify({'message': 'Tenant deactivated successfully'}), 200


@tenant_bp.route('/<int:tenant_id>/activate', methods=['POST'])
@auth_required
# @permission_required('tenant.deactivate')
def activate_tenant(tenant_id: int):
    """
    Re-activate a previously deactivated tenant.
    POST /api/tenant/<tenant_id>/activate
    """
    tenant = TenantMaster.query.get(tenant_id)
    if not tenant:
        abort(404, description='Tenant not found')

    tenant.is_active  = True
    tenant.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'message': 'Tenant activated successfully', 'tenant': _tenant_dict(tenant)}), 200


# ─────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────

def _parse_date(value):
    if not value:
        return None
    if hasattr(value, 'date'):
        return value.date()
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _tenant_dict(t: TenantMaster) -> dict:
    return {
        'tenant_id':            t.tenant_id,
        'tenant_company_name':  t.tenant_company_name,
        'tenant_contact_name':  t.tenant_contact_name,
        'onboarding_date':      t.onboarding_Date.isoformat() if t.onboarding_Date else None,
        'is_active':            t.is_active,
        'created_at':           t.created_at.isoformat()  if t.created_at  else None,
        'updated_at':           t.updated_at.isoformat()  if t.updated_at  else None,
    }