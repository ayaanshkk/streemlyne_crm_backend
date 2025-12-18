# tenant_middleware.py - StreemLyne Generic CRM
# Uses Flask-SQLAlchemy with db.session

from flask import g, request, jsonify, current_app
from functools import wraps

def require_tenant(f):
    """Decorator to ensure tenant context is set"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from models import User, Tenant
        
        # Get token from Authorization header
        auth_header = request.headers.get('Authorization', '')
        token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
        
        if not token:
            return jsonify({'error': 'No authorization token'}), 401
        
        # Verify user and get tenant
        user = User.verify_jwt_token(token, current_app.config['SECRET_KEY'])
        
        if not user:
            return jsonify({'error': 'Invalid token'}), 401
        
        # Set tenant context in Flask g
        g.tenant_id = user.tenant_id
        g.user_id = user.id
        g.user = user
        
        # Verify tenant is active
        tenant = Tenant.query.get(g.tenant_id)
        if not tenant or not tenant.is_active:
            return jsonify({'error': 'Tenant inactive'}), 403
        
        g.tenant = tenant
        
        return f(*args, **kwargs)
    
    return decorated_function

def check_feature(feature_name):
    """Check if current tenant has access to a feature"""
    if not hasattr(g, 'tenant'):
        return False
    return g.tenant.has_feature(feature_name)

def get_tenant_query(model_class):
    """Returns a query automatically filtered by tenant"""
    if not hasattr(g, 'tenant_id'):
        raise Exception("Tenant context not set! Use @require_tenant decorator")
    
    return model_class.query.filter_by(tenant_id=g.tenant_id)