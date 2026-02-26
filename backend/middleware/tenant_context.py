"""
Tenant Context Middleware
Extracts tenant_id from JWT and injects into Flask g context
"""

from functools import wraps
from flask import request, g, jsonify
import jwt
from typing import Optional
from models import UserMaster



def get_current_tenant_id() -> Optional[int]:
    """
    Get current tenant_id from Flask g context
    
    Returns:
        tenant_id or None if not set
    """
    return getattr(g, 'tenant_id', None)


def inject_tenant_context():
    """
    Extract tenant_id from JWT token and inject into Flask g context
    
    This should be called BEFORE processing any request that needs tenant isolation.
    Typically used as a before_request handler.
    
    Usage in app.py:
        @app.before_request
        def before_request():
            inject_tenant_context()
    """
    # Skip for OPTIONS requests (CORS preflight)
    if request.method == 'OPTIONS':
        return
    
    # Skip for certain public endpoints
    public_endpoints = ['login', 'register', 'health', 'static']
    if request.endpoint in public_endpoints:
        return
    
    # Get token from Authorization header
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        # No token provided - might be public endpoint
        return
    
    token = auth_header.split(' ')[1]
    
    try:
        # Decode JWT, commented out cuz error during testing
        # from config import Config
        # payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])

        from flask import current_app
        payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])

        
        # Extract tenant_id
        tenant_id = payload.get('tenant_id')
        if tenant_id:
            g.tenant_id = tenant_id
            g.user_id = payload.get('user_id')
            g.employee_id = payload.get('employee_id')
            
    except jwt.ExpiredSignatureError:
        # Token expired - let auth_required handle it
        pass
    except jwt.InvalidTokenError:
        # Invalid token - let auth_required handle it
        pass


def tenant_required(f):
    """
    Decorator to ensure tenant_id is present in request context
    
    Usage:
        @app.route('/api/clients')
        @tenant_required
        def get_clients():
            tenant_id = get_current_tenant_id()
            # ... fetch clients for tenant
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            return jsonify({
                'error': 'Tenant context not found',
                'message': 'Invalid or missing authentication token'
            }), 401
        
        return f(*args, **kwargs)
    
    return decorated_function