"""
Subscription Routes
Handles: Subscription_Plans, Tenant_Subscription, Subscription_Module_Mapping

Schema alignment (StreemLyne_MT):
  Subscription_Plans:
    subscription_id (PK), subscription_code (UNIQUE, NOT NULL),
    subscription_name (UNIQUE, NOT NULL), description, is_base_plan (NOT NULL),
    is_active (NOT NULL), billing_cycle (smallint, NOT NULL),
    price (numeric, NOT NULL), currency_id (FK→Currency_Master, NOT NULL),
    created_at, updated_at

  Tenant_Subscription:
    tenant_subscription_mapping_id (PK), tenant_id (FK→Tenant_Master),
    subscription_id (FK→Subscription_Plans), subscription_start_date,
    subscription_end_date, is_active, auto_renew, created_at, updated_at

  Subscription_Module_Mapping:
    subscription_module_mapping_id (PK),
    subscription_id (FK→Subscription_Plans, bigint),
    module_id (FK→Module_Master, bigint), created_at
"""

from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy.exc import IntegrityError
from database import db
from models import SubscriptionPlan, TenantSubscription, SubscriptionModuleMapping, ModuleMaster
from middleware import auth_required, permission_required
from datetime import datetime, date

subscription_bp = Blueprint('subscription', __name__, url_prefix='/api/subscriptions')


# ─────────────────────────────────────────
# Subscription Plans – catalogue CRUD
# ─────────────────────────────────────────

@subscription_bp.route('/plans', methods=['GET'])
@auth_required
def list_plans():
    """
    List all active subscription plans.
    GET /api/subscriptions/plans
    Query params:
      include_inactive=true  – include inactive plans (admin use)
    """
    include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'
    query = SubscriptionPlan.query
    if not include_inactive:
        query = query.filter_by(is_active=True)

    plans = query.order_by(SubscriptionPlan.subscription_name).all()
    return jsonify([_plan_dict(p) for p in plans]), 200


@subscription_bp.route('/plans/<int:subscription_id>', methods=['GET'])
@auth_required
def get_plan(subscription_id: int):
    """GET /api/subscriptions/plans/<subscription_id>"""
    plan = _plan_or_404(subscription_id)
    result = _plan_dict(plan)

    # Include modules bundled in this plan
    mappings = SubscriptionModuleMapping.query.filter_by(
        subscription_id=subscription_id
    ).all()
    module_ids = [m.module_id for m in mappings]
    modules = ModuleMaster.query.filter(
        ModuleMaster.module_id.in_(module_ids)
    ).all() if module_ids else []

    result['modules'] = [
        {'module_id': m.module_id, 'module_code': m.module_code, 'module_name': m.module_name}
        for m in modules
    ]
    return jsonify(result), 200


@subscription_bp.route('/plans', methods=['POST'])
@auth_required
# @permission_required('subscription.create_plan')
def create_plan():
    """
    Create a new subscription plan.
    POST /api/subscriptions/plans
    Body:
    {
        "subscription_code": "PRO",            (required, UNIQUE)
        "subscription_name": "Pro Plan",       (required, UNIQUE)
        "price": 99.00,                        (required)
        "currency_id": 1,                      (required, FK → Currency_Master)
        "billing_cycle": 1,                    (required, smallint — e.g. 1=monthly, 12=annual)
        "description": "...",
        "is_base_plan": false,
        "is_active": true
    }
    """
    data = request.get_json() or {}

    required = ['subscription_code', 'subscription_name', 'price', 'currency_id', 'billing_cycle']
    missing = [f for f in required if data.get(f) is None]
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400

    plan = SubscriptionPlan(
        subscription_code=data['subscription_code'].strip(),
        subscription_name=data['subscription_name'].strip(),
        description=data.get('description'),
        price=data['price'],
        currency_id=data['currency_id'],
        billing_cycle=int(data['billing_cycle']),
        is_base_plan=bool(data.get('is_base_plan', False)),
        is_active=bool(data.get('is_active', True))
    )

    try:
        db.session.add(plan)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'subscription_code or subscription_name already exists'}), 409

    return jsonify({'message': 'Plan created', 'plan': _plan_dict(plan)}), 201


@subscription_bp.route('/plans/<int:subscription_id>', methods=['PUT'])
@auth_required
# @permission_required('subscription.create_plan')
def update_plan(subscription_id: int):
    """
    Update a subscription plan.
    PUT /api/subscriptions/plans/<subscription_id>
    """
    plan = _plan_or_404(subscription_id)
    data = request.get_json() or {}

    for field in [
        'subscription_name', 'description', 'price',
        'currency_id', 'billing_cycle', 'is_base_plan', 'is_active'
    ]:
        if field in data:
            setattr(plan, field, data[field])

    plan.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'subscription_name already exists'}), 409

    return jsonify({'message': 'Plan updated', 'plan': _plan_dict(plan)}), 200


# ─────────────────────────────────────────
# Tenant Subscriptions
# ─────────────────────────────────────────

@subscription_bp.route('/tenants/<int:tenant_id>', methods=['GET'])
@auth_required
# @permission_required('subscription.view')
def get_tenant_subscription(tenant_id: int):
    """
    Get active subscription(s) for a tenant.
    GET /api/subscriptions/tenants/<tenant_id>
    """
    subs = (
        TenantSubscription.query
        .filter_by(tenant_id=tenant_id, is_active=True)
        .order_by(TenantSubscription.subscription_start_date.desc())
        .all()
    )
    return jsonify([_tenant_sub_dict(s) for s in subs]), 200


@subscription_bp.route('/tenants/<int:tenant_id>', methods=['POST'])
@auth_required
# @permission_required('subscription.create')
def assign_subscription(tenant_id: int):
    """
    Assign a subscription plan to a tenant.
    POST /api/subscriptions/tenants/<tenant_id>
    Body:
    {
        "subscription_id": 2,           (required)
        "subscription_start_date": "2025-07-01",
        "subscription_end_date": "2026-06-30",
        "auto_renew": true
    }
    Also accepted: "subscription_code" instead of "subscription_id".
    """
    data = request.get_json() or {}

    # Resolve plan by id or code
    plan = None
    if data.get('subscription_id'):
        plan = SubscriptionPlan.query.get(int(data['subscription_id']))
    elif data.get('subscription_code'):
        plan = SubscriptionPlan.query.filter_by(
            subscription_code=data['subscription_code'], is_active=True
        ).first()

    if not plan:
        return jsonify({'error': 'Subscription plan not found'}), 404

    start = _parse_date(data.get('subscription_start_date')) or date.today()
    end   = _parse_date(data.get('subscription_end_date'))

    # Deactivate any existing active subscription for this tenant before creating new one
    TenantSubscription.query.filter_by(
        tenant_id=tenant_id, is_active=True
    ).update({'is_active': False, 'updated_at': datetime.utcnow()})

    sub = TenantSubscription(
        tenant_id=tenant_id,
        subscription_id=plan.subscription_id,
        subscription_start_date=start,
        subscription_end_date=end,
        is_active=True,
        auto_renew=bool(data.get('auto_renew', False)),
        created_at=datetime.utcnow()
    )

    try:
        db.session.add(sub)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid tenant_id or subscription_id'}), 409

    return jsonify({
        'message': 'Subscription assigned successfully',
        'subscription': _tenant_sub_dict(sub)
    }), 201


@subscription_bp.route('/tenants/<int:tenant_id>/cancel', methods=['POST'])
@auth_required
# @permission_required('subscription.cancel')
def cancel_tenant_subscription(tenant_id: int):
    """
    Cancel the active subscription for a tenant.
    POST /api/subscriptions/tenants/<tenant_id>/cancel
    """
    sub = TenantSubscription.query.filter_by(
        tenant_id=tenant_id, is_active=True
    ).first()

    if not sub:
        return jsonify({'error': 'No active subscription found for this tenant'}), 404

    sub.is_active    = False
    sub.auto_renew   = False
    sub.updated_at   = datetime.utcnow()
    db.session.commit()

    return jsonify({'message': 'Subscription cancelled successfully'}), 200


@subscription_bp.route('/tenants/<int:tenant_id>/renew', methods=['POST'])
@auth_required
# @permission_required('subscription.create')
def renew_tenant_subscription(tenant_id: int):
    """
    Manually renew a tenant's current subscription for another billing cycle.
    POST /api/subscriptions/tenants/<tenant_id>/renew
    """
    current = TenantSubscription.query.filter_by(
        tenant_id=tenant_id, is_active=True
    ).order_by(TenantSubscription.subscription_start_date.desc()).first()

    if not current:
        return jsonify({'error': 'No active subscription found to renew'}), 404

    plan = SubscriptionPlan.query.get(current.subscription_id)
    if not plan:
        return jsonify({'error': 'Associated plan not found'}), 500

    new_start = current.subscription_end_date or date.today()
    # billing_cycle is in months
    from dateutil.relativedelta import relativedelta
    new_end = new_start + relativedelta(months=plan.billing_cycle)

    current.is_active  = False
    current.updated_at = datetime.utcnow()

    renewed = TenantSubscription(
        tenant_id=tenant_id,
        subscription_id=plan.subscription_id,
        subscription_start_date=new_start,
        subscription_end_date=new_end,
        is_active=True,
        auto_renew=current.auto_renew,
        created_at=datetime.utcnow()
    )
    db.session.add(renewed)
    db.session.commit()

    return jsonify({
        'message': 'Subscription renewed',
        'subscription': _tenant_sub_dict(renewed)
    }), 201


# ─────────────────────────────────────────
# Subscription → Module Mapping
# ─────────────────────────────────────────

@subscription_bp.route('/plans/<int:subscription_id>/modules', methods=['GET'])
@auth_required
def get_plan_modules(subscription_id: int):
    """
    List modules included in a subscription plan.
    GET /api/subscriptions/plans/<subscription_id>/modules
    """
    _plan_or_404(subscription_id)
    mappings = SubscriptionModuleMapping.query.filter_by(
        subscription_id=subscription_id
    ).all()
    module_ids = [m.module_id for m in mappings]
    modules = ModuleMaster.query.filter(
        ModuleMaster.module_id.in_(module_ids)
    ).all() if module_ids else []

    return jsonify({
        'subscription_id': subscription_id,
        'module_ids':      module_ids,
        'modules': [
            {'module_id': m.module_id, 'module_code': m.module_code, 'module_name': m.module_name}
            for m in modules
        ]
    }), 200


@subscription_bp.route('/plans/<int:subscription_id>/modules/<int:module_id>', methods=['POST'])
@auth_required
# @permission_required('subscription.manage_modules')
def add_module_to_plan(subscription_id: int, module_id: int):
    """
    Add a module to a subscription plan.
    POST /api/subscriptions/plans/<subscription_id>/modules/<module_id>
    """
    _plan_or_404(subscription_id)

    if not ModuleMaster.query.get(module_id):
        return jsonify({'error': 'Module not found'}), 404

    if SubscriptionModuleMapping.query.filter_by(
        subscription_id=subscription_id, module_id=module_id
    ).first():
        return jsonify({'error': 'Module already included in this plan'}), 409

    mapping = SubscriptionModuleMapping(
        subscription_id=subscription_id,
        module_id=module_id
    )

    try:
        db.session.add(mapping)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Module already included in this plan'}), 409

    return jsonify({'message': 'Module added to plan'}), 201


@subscription_bp.route('/plans/<int:subscription_id>/modules/<int:module_id>', methods=['DELETE'])
@auth_required
# @permission_required('subscription.manage_modules')
def remove_module_from_plan(subscription_id: int, module_id: int):
    """
    Remove a module from a subscription plan.
    DELETE /api/subscriptions/plans/<subscription_id>/modules/<module_id>
    """
    mapping = SubscriptionModuleMapping.query.filter_by(
        subscription_id=subscription_id, module_id=module_id
    ).first()
    if not mapping:
        abort(404, description='Module not found in this plan')

    db.session.delete(mapping)
    db.session.commit()
    return jsonify({'message': 'Module removed from plan'}), 200


# ─────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────

def _plan_or_404(subscription_id: int) -> SubscriptionPlan:
    plan = SubscriptionPlan.query.get(subscription_id)
    if not plan:
        abort(404, description='Subscription plan not found')
    return plan


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, (date, datetime)):
        return value if isinstance(value, date) else value.date()
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _plan_dict(p: SubscriptionPlan) -> dict:
    return {
        'subscription_id':   p.subscription_id,
        'subscription_code': p.subscription_code,
        'subscription_name': p.subscription_name,
        'description':       p.description,
        'price':             float(p.price) if p.price is not None else None,
        'currency_id':       p.currency_id,
        'billing_cycle':     p.billing_cycle,
        'is_base_plan':      p.is_base_plan,
        'is_active':         p.is_active,
        'created_at':        p.created_at.isoformat()  if p.created_at  else None,
        'updated_at':        p.updated_at.isoformat()  if p.updated_at  else None,
    }


def _tenant_sub_dict(s: TenantSubscription) -> dict:
    return {
        'tenant_subscription_mapping_id': s.tenant_subscription_mapping_id,
        'tenant_id':              s.tenant_id,
        'subscription_id':        s.subscription_id,
        'subscription_start_date': s.subscription_start_date.isoformat() if s.subscription_start_date else None,
        'subscription_end_date':   s.subscription_end_date.isoformat()   if s.subscription_end_date   else None,
        'is_active':    s.is_active,
        'auto_renew':   s.auto_renew,
        'created_at':   s.created_at.isoformat()  if s.created_at  else None,
        'updated_at':   s.updated_at.isoformat()  if s.updated_at  else None,
    }