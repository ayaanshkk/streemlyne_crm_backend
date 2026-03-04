from functools import wraps

from flask import jsonify

from .auth_middleware import get_current_user
from services import PermissionService


def permission_required(permission_code: str):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if user is None:
                return jsonify({"error": "Unauthorized", "message": "Authentication required"}), 401

            if not PermissionService().user_has_permission(user, permission_code):
                return jsonify({"error": "Forbidden", "message": f"Permission required: {permission_code}"}), 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator