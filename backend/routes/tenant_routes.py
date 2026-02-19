from flask import Blueprint, jsonify, request
from models import Tenant
from database import db
from tenant_middleware import require_tenant as token_required

tenant_bp = Blueprint('tenant', __name__, url_prefix='/api/tenant')


@tenant_bp.route('/config', methods=['GET'])
@token_required
def get_tenant_config(current_user):
    """Get tenant configuration (for frontend)"""
    
    tenant = Tenant.query.get(current_user.tenant_id)
    
    return jsonify({
        'industry_template': tenant.industry_template,
        'enabled_modules': tenant.enabled_modules or {},
        'terminology': tenant.terminology or {},
        'pipeline_stages': tenant.pipeline_stages or {},
        'custom_fields_config': tenant.custom_fields_config or {}
    })


@tenant_bp.route('/config', methods=['PATCH'])
@token_required
def update_tenant_config(current_user):
    """Update tenant configuration (admin only)"""
    
    if current_user.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    tenant = Tenant.query.get(current_user.tenant_id)
    data = request.get_json()
    
    # Update industry template
    if 'industry_template' in data:
        tenant.industry_template = data['industry_template']
    
    # Update enabled modules
    if 'enabled_modules' in data:
        tenant.enabled_modules = data['enabled_modules']
    
    # Update terminology
    if 'terminology' in data:
        tenant.terminology = data['terminology']
    
    # Update pipeline stages
    if 'pipeline_stages' in data:
        tenant.pipeline_stages = data['pipeline_stages']
    
    db.session.commit()
    
    return jsonify(tenant.to_dict())


# ============================================================
# NEW SCHEMA - Using TenantMaster
# Add these functions to the BOTTOM of tenant_routes.py
# ============================================================

@tenant_bp.route('/new/info', methods=['GET'])
def get_new_tenant_info():
    """
    Get tenant info using new schema
    Requires tenant_id in query params or from JWT
    
    GET /api/tenant/new/info?tenant_id=1
    OR
    GET /api/tenant/new/info (with JWT token)
    """
    from middleware import auth_required, get_current_user
    from models import TenantMaster
    
    # Try to get tenant_id from query params
    tenant_id = request.args.get('tenant_id')
    
    # If not in params, try to get from JWT
    if not tenant_id:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            try:
                from middleware import get_current_user
                from flask import g
                
                # This will populate g.tenant_id
                from middleware import inject_tenant_context
                inject_tenant_context()
                
                tenant_id = getattr(g, 'tenant_id', None)
            except:
                pass
    
    if not tenant_id:
        return jsonify({'error': 'tenant_id required'}), 400
    
    # Get tenant from new schema
    tenant = TenantMaster.query.get(tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404
    
    return jsonify(tenant.to_dict()), 200


@tenant_bp.route('/new/modules', methods=['GET'])
def get_tenant_modules():
    """
    Get modules enabled for tenant
    
    GET /api/tenant/new/modules?tenant_id=1
    """
    from services import TenantService
    
    tenant_id = request.args.get('tenant_id', type=int)
    if not tenant_id:
        return jsonify({'error': 'tenant_id required'}), 400
    
    tenant_service = TenantService()
    module_ids = tenant_service.get_tenant_modules(tenant_id)
    
    return jsonify({
        'tenant_id': tenant_id,
        'module_ids': module_ids
    }), 200


@tenant_bp.route('/new/subscription', methods=['GET'])
def get_tenant_subscription():
    """
    Get tenant's subscription status
    
    GET /api/tenant/new/subscription?tenant_id=1
    """
    from services import SubscriptionService
    
    tenant_id = request.args.get('tenant_id', type=int)
    if not tenant_id:
        return jsonify({'error': 'tenant_id required'}), 400
    
    subscription_service = SubscriptionService()
    status = subscription_service.check_subscription_status(tenant_id)
    
    return jsonify(status), 200


@tenant_bp.route('/new/statistics', methods=['GET'])
def get_tenant_statistics():
    """
    Get tenant statistics
    
    GET /api/tenant/new/statistics?tenant_id=1
    """
    from services import TenantService
    
    tenant_id = request.args.get('tenant_id', type=int)
    if not tenant_id:
        return jsonify({'error': 'tenant_id required'}), 400
    
    tenant_service = TenantService()
    stats = tenant_service.get_tenant_statistics(tenant_id)
    
    if not stats:
        return jsonify({'error': 'Tenant not found'}), 404
    
    return jsonify(stats), 200