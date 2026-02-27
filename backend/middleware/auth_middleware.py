"""
Authentication Middleware
Verifies JWT tokens and loads user information
"""

from functools import wraps
from flask import request, g, jsonify
import jwt
from typing import Optional
from models import UserMaster


def get_current_user() -> Optional[UserMaster]:
    """
    Get current authenticated user from Flask g context
    
    Returns:
        UserMaster instance or None
    """
    return getattr(g, 'current_user', None)


def auth_required(f):
    """
    Decorator to require authentication
    
    Verifies JWT token and loads user into g.current_user
    
    Usage:
        @app.route('/api/profile')
        @auth_required
        def get_profile():
            user = get_current_user()
            return jsonify(user.to_dict())
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get token from Authorization header
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({
                'error': 'Missing token',
                'message': 'Authorization header with Bearer token required'
            }), 401
        
        token = auth_header.split(' ')[1]
        
        try:
            from flask import current_app
            user = UserMaster.verify_jwt_token(token, current_app.config['SECRET_KEY'])

            
            if user is None:
                return jsonify({
                    'error': 'Invalid token',
                    'message': 'User not found or account inactive'
                }), 401
            
            # Load user into context
            g.current_user = user
            g.user_id = user.user_id
            
            # Load employee and tenant_id
            if user.employee:
                g.employee_id = user.employee.employee_id
                g.tenant_id = user.employee.tenant_id
            
            return f(*args, **kwargs)
            
        except jwt.ExpiredSignatureError:
            return jsonify({
                'error': 'Token expired',
                'message': 'Please log in again'
            }), 401
        except jwt.InvalidTokenError:
            return jsonify({
                'error': 'Invalid token',
                'message': 'Authentication token is invalid'
            }), 401
    
    return decorated_function