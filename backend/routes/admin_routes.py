"""
Admin Routes
Administrative endpoints for managing subscriptions, modules, roles, etc.
"""

from flask import Blueprint, request, jsonify
from middleware import auth_required, permission_required, get_current_user
from services import TenantService, SubscriptionService, PermissionService
from repositories import MasterRepository

admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')


# ============================================================
# TENANT MANAGEMENT
# ============================================================

@admin_bp.route('/tenants', methods=['GET'])
@auth_required
@permission_required('tenant.view')
def get_all_tenants():
    """Get all tenants (admin only)"""
    tenant_service = TenantService()
    tenants = tenant_service.get_all_active_tenants()
    return jsonify([
        {
            'tenant_id': t.tenant_id,
            'company_name': t.tenant_company_name,
            'contact_name': t.tenant_contact_name,
            'is_active': t.is_active,
            'onboarding_date': t.onboarding_date.isoformat() if t.onboarding_date else None
        }
        for t in tenants
    ]), 200


@admin_bp.route('/tenants/<int:tenant_id>', methods=['GET'])
@auth_required
@permission_required('tenant.view')
def get_tenant_details(tenant_id):
    """Get detailed tenant information"""
    tenant_service = TenantService()
    stats = tenant_service.get_tenant_statistics(tenant_id)
    
    if not stats:
        return jsonify({'error': 'Tenant not found'}), 404
    
    return jsonify(stats), 200


@admin_bp.route('/tenants', methods=['POST'])
@auth_required
@permission_required('tenant.create')
def create_tenant():
    """Create a new tenant"""
    data = request.get_json()
    
    required_fields = ['company_name']
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Missing required fields'}), 400
    
    try:
        tenant_service = TenantService()
        tenant = tenant_service.create_tenant(
            company_name=data['company_name'],
            contact_name=data.get('contact_name'),
            onboarding_date=data.get('onboarding_date')
        )
        
        return jsonify({
            'message': 'Tenant created successfully',
            'tenant_id': tenant.tenant_id
        }), 201
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@admin_bp.route('/tenants/<int:tenant_id>', methods=['PUT'])
@auth_required
@permission_required('tenant.update')
def update_tenant(tenant_id):
    """Update tenant information"""
    data = request.get_json()
    
    tenant_service = TenantService()
    tenant = tenant_service.update_tenant(tenant_id, **data)
    
    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404
    
    return jsonify({'message': 'Tenant updated successfully'}), 200


@admin_bp.route('/tenants/<int:tenant_id>/deactivate', methods=['POST'])
@auth_required
@permission_required('tenant.deactivate')
def deactivate_tenant(tenant_id):
    """Deactivate a tenant"""
    tenant_service = TenantService()
    success = tenant_service.deactivate_tenant(tenant_id)
    
    if not success:
        return jsonify({'error': 'Tenant not found'}), 404
    
    return jsonify({'message': 'Tenant deactivated successfully'}), 200


# ============================================================
# SUBSCRIPTION MANAGEMENT
# ============================================================

@admin_bp.route('/subscription-plans', methods=['GET'])
@auth_required
def get_subscription_plans():
    """Get all available subscription plans"""
    subscription_service = SubscriptionService()
    plans = subscription_service.get_all_plans()
    
    return jsonify([
        {
            'subscription_id': p.subscription_id,
            'code': p.subscription_code,
            'name': p.subscription_name,
            'description': p.description,
            'price': float(p.price) if p.price else None,
            'currency_id': p.currency_id,
            'billing_cycle': p.billing_cycle,
            'is_base_plan': p.is_base_plan,
            'is_active': p.is_active
        }
        for p in plans
    ]), 200


@admin_bp.route('/tenants/<int:tenant_id>/subscription', methods=['GET'])
@auth_required
@permission_required('subscription.view')
def get_tenant_subscription(tenant_id):
    """Get tenant's subscription status"""
    subscription_service = SubscriptionService()
    status = subscription_service.check_subscription_status(tenant_id)
    return jsonify(status), 200


@admin_bp.route('/tenants/<int:tenant_id>/subscription', methods=['POST'])
@auth_required
@permission_required('subscription.create')
def create_subscription(tenant_id):
    """Create a subscription for a tenant"""
    data = request.get_json()
    
    if 'subscription_code' not in data:
        return jsonify({'error': 'subscription_code is required'}), 400
    
    try:
        subscription_service = SubscriptionService()
        subscription = subscription_service.create_subscription(
            tenant_id=tenant_id,
            subscription_code=data['subscription_code'],
            auto_renew=data.get('auto_renew', False)
        )
        
        return jsonify({
            'message': 'Subscription created successfully',
            'subscription_id': subscription.tenant_subscription_mapping_id
        }), 201
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@admin_bp.route('/tenants/<int:tenant_id>/subscription/cancel', methods=['POST'])
@auth_required
@permission_required('subscription.cancel')
def cancel_subscription(tenant_id):
    """Cancel tenant's subscription"""
    subscription_service = SubscriptionService()
    success = subscription_service.cancel_subscription(tenant_id)
    
    if not success:
        return jsonify({'error': 'No active subscription found'}), 404
    
    return jsonify({'message': 'Subscription cancelled successfully'}), 200


# ============================================================
# MODULE MANAGEMENT
# ============================================================

@admin_bp.route('/modules', methods=['GET'])
@auth_required
def get_all_modules():
    """Get all available modules"""
    permission_service = PermissionService()
    modules = permission_service.repo.get_all_modules()
    
    return jsonify([
        {
            'module_id': m.module_id,
            'code': m.module_code,
            'name': m.module_name,
            'description': m.description,
            'is_core': m.is_core,
            'is_active': m.is_active
        }
        for m in modules
    ]), 200


@admin_bp.route('/tenants/<int:tenant_id>/modules', methods=['GET'])
@auth_required
@permission_required('module.view')
def get_tenant_modules(tenant_id):
    """Get modules enabled for a tenant"""
    tenant_service = TenantService()
    module_ids = tenant_service.get_tenant_modules(tenant_id)
    
    return jsonify({
        'tenant_id': tenant_id,
        'module_ids': module_ids
    }), 200


@admin_bp.route('/tenants/<int:tenant_id>/modules/<int:module_id>', methods=['POST'])
@auth_required
@permission_required('module.assign')
def enable_module(tenant_id, module_id):
    """Enable a module for a tenant"""
    tenant_service = TenantService()
    success = tenant_service.enable_module(tenant_id, module_id)
    
    if success:
        return jsonify({'message': 'Module enabled successfully'}), 200
    else:
        return jsonify({'error': 'Module already enabled'}), 400


@admin_bp.route('/tenants/<int:tenant_id>/modules/<int:module_id>', methods=['DELETE'])
@auth_required
@permission_required('module.revoke')
def disable_module(tenant_id, module_id):
    """Disable a module for a tenant"""
    tenant_service = TenantService()
    success = tenant_service.disable_module(tenant_id, module_id)
    
    if success:
        return jsonify({'message': 'Module disabled successfully'}), 200
    else:
        return jsonify({'error': 'Module not enabled'}), 404


# ============================================================
# ROLE & PERMISSION MANAGEMENT
# ============================================================

@admin_bp.route('/roles', methods=['GET'])
@auth_required
def get_all_roles():
    """Get all roles"""
    permission_service = PermissionService()
    roles = permission_service.get_all_roles()
    
    return jsonify([
        {
            'role_id': r.role_id,
            'name': r.role_name,
            'description': r.role_description,
            'is_system': r.is_system
        }
        for r in roles
    ]), 200


@admin_bp.route('/roles', methods=['POST'])
@auth_required
@permission_required('role.create')
def create_role():
    """Create a new role"""
    data = request.get_json()
    
    if 'role_name' not in data:
        return jsonify({'error': 'role_name is required'}), 400
    
    try:
        permission_service = PermissionService()
        role = permission_service.create_role(
            role_name=data['role_name'],
            role_description=data.get('role_description'),
            is_system=data.get('is_system', False)
        )
        
        return jsonify({
            'message': 'Role created successfully',
            'role_id': role.role_id
        }), 201
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@admin_bp.route('/roles/<int:role_id>/permissions', methods=['GET'])
@auth_required
def get_role_permissions(role_id):
    """Get permissions for a role"""
    permission_service = PermissionService()
    permissions = permission_service.get_role_permissions(role_id)
    
    return jsonify([
        {
            'permission_id': p.permission_id,
            'code': p.permission_code,
            'description': p.description
        }
        for p in permissions
    ]), 200


@admin_bp.route('/roles/<int:role_id>/permissions', methods=['POST'])
@auth_required
@permission_required('role.assign_permission')
def assign_permission(role_id):
    """Assign a permission to a role"""
    data = request.get_json()
    
    if 'permission_code' not in data:
        return jsonify({'error': 'permission_code is required'}), 400
    
    try:
        permission_service = PermissionService()
        success = permission_service.assign_permission_to_role(
            role_id, data['permission_code']
        )
        
        if success:
            return jsonify({'message': 'Permission assigned successfully'}), 200
        else:
            return jsonify({'error': 'Permission already assigned'}), 400
            
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@admin_bp.route('/permissions', methods=['GET'])
@auth_required
def get_all_permissions():
    """Get all permissions"""
    permission_service = PermissionService()
    permissions = permission_service.get_all_permissions()
    
    return jsonify([
        {
            'permission_id': p.permission_id,
            'code': p.permission_code,
            'description': p.description
        }
        for p in permissions
    ]), 200


# ============================================================
# MASTER DATA
# ============================================================

@admin_bp.route('/master-data/countries', methods=['GET'])
@auth_required
def get_countries():
    """Get all countries"""
    master_repo = MasterRepository()
    countries = master_repo.get_all_countries()
    
    return jsonify([
        {
            'country_id': c.country_id,
            'name': c.country_name,
            'isd_code': c.country_isd_code
        }
        for c in countries
    ]), 200


@admin_bp.route('/master-data/currencies', methods=['GET'])
@auth_required
def get_currencies():
    """Get all currencies"""
    master_repo = MasterRepository()
    currencies = master_repo.get_all_currencies()
    
    return jsonify([
        {
            'currency_id': c.currency_id,
            'name': c.currency_name,
            'code': c.currency_code
        }
        for c in currencies
    ]), 200


@admin_bp.route('/master-data/designations', methods=['GET'])
@auth_required
def get_designations():
    """Get all designations"""
    master_repo = MasterRepository()
    designations = master_repo.get_all_designations()
    
    return jsonify([
        {
            'designation_id': d.designation_id,
            'description': d.designation_description
        }
        for d in designations
    ]), 200


@admin_bp.route('/master-data/uoms', methods=['GET'])
@auth_required
def get_uoms():
    """Get all units of measurement"""
    master_repo = MasterRepository()
    uoms = master_repo.get_all_uoms()
    
    return jsonify([
        {
            'uom_id': u.uom_id,
            'description': u.uom_description
        }
        for u in uoms
    ]), 200