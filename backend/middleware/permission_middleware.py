"""
Permission Middleware
Checks user permissions before allowing access
"""

from functools import wraps
from flask import jsonify
from .auth_middleware import get_current_user, auth_required
from services import PermissionService


def permission_required(permission_code: str):
    """
    Decorator to require a specific permission
    
    Args:
        permission_code: Permission code (e.g., 'client.create')
    
    Usage:
        @app.route('/api/clients', methods=['POST'])
        @auth_required
        @permission_required('client.create')
        def create_client():
            # User has 'client.create' permission
            pass
    """
    def decorator(f):
        @wraps(f)
        @auth_required  # Ensure user is authenticated first
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if user is None:
                return jsonify({
                    'error': 'Unauthorized',
                    'message': 'Authentication required'
                }), 401
            
            # Check permission
            permission_service = PermissionService()
            has_permission = permission_service.user_has_permission(user, permission_code)
            
            if not has_permission:
                return jsonify({
                    'error': 'Forbidden',
                    'message': f'Permission required: {permission_code}'
                }), 403
            
            return f(*args, **kwargs)
        
        return decorated_function
    
    return decorator