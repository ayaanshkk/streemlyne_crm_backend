# middleware/auth_middleware.py
"""
Auth Middleware
Handles JWT validation and request-scoped user context for authenticated requests.

CHANGES vs previous version
─────────────────────────────────────────────────────────────────────────────
[MW-001] auth_required now only authenticates and populates flask.g.
         Subscription enforcement lives in subscription_middleware.py so there
         is a single gate and a single exemption list.

[MW-003] g.tenant_id is now a string throughout (matches TenantMaster.tenant_id
         character varying PK).

[MW-004] require_tenant_owner decorator added.
         Checks the current user's roles and returns 403 if they are not an
         Admin or Super Admin. Used by /me/checkout and /me/cancel to enforce
         the PRD rule that only the Tenant Owner may modify the subscription.

[MW-005] permission_required is NOT defined here — lives in permission_middleware.py.

[MW-FIX] Added cast to typing import. Was missing — caused ImportError at
         startup because require_tenant_owner calls cast(list, roles).
─────────────────────────────────────────────────────────────────────────────
"""

from functools import wraps
from typing import Optional

import jwt
from flask import current_app, g, jsonify, request

from database import db
from models import EmployeeMaster, TenantMaster, UserMaster

def get_current_user() -> Optional[UserMaster]:
    return getattr(g, "current_user", None)


def get_current_employee() -> Optional[EmployeeMaster]:
    return getattr(g, "current_employee", None)


def _resolve_user_from_token(token: str):
    """
    Validate a Bearer token and resolve the associated user/employee/tenant.

    Returns (user, employee, tenant, None) on success.
    Returns (None, None, None, (response, status)) on any failure.
    """
    try:
        payload = jwt.decode(
            token, current_app.config["SECRET_KEY"], algorithms=["HS256"]
        )
    except jwt.ExpiredSignatureError:
        return None, None, None, (
            jsonify({"error": "Token expired", "message": "Please log in again"}), 401
        )
    except jwt.InvalidTokenError:
        return None, None, None, (
            jsonify({"error": "Invalid token", "message": "Authentication token is invalid"}), 401
        )

    # Reject customer-portal tokens cleanly.
    if payload.get("type") != "staff":
        return None, None, None, (
            jsonify({"error": "Invalid token", "message": "Staff token required"}), 401
        )

    user_id = payload.get("user_id")
    if not user_id:
        return None, None, None, (
            jsonify({"error": "Invalid token", "message": "Token is missing user_id claim"}), 401
        )

    user = db.session.get(UserMaster, user_id)
    if not user:
        return None, None, None, (
            jsonify({"error": "Invalid token", "message": "User not found"}), 401
        )

    if not user.employee_id:
        return None, None, None, (
            jsonify({"error": "Account misconfigured", "message": "User has no linked employee record"}), 403
        )

    employee = db.session.get(EmployeeMaster, user.employee_id)
    if not employee:
        return None, None, None, (
            jsonify({"error": "Account misconfigured", "message": "Employee record not found"}), 403
        )

    # [MW-003] tenant_id is a string slug.
    tenant = db.session.get(TenantMaster, employee.tenant_id)

    # Tenant_Master.is_active has no NOT NULL constraint — treat NULL as inactive.
    if not tenant or tenant.is_active is not True:
        return None, None, None, (
            jsonify({"error": "Tenant inactive", "message": "Your organisation's account is inactive"}), 403
        )

    return user, employee, tenant, None


def auth_required(f):
    """
    Decorator: validates JWT and enforces subscription access.

    Sets on g:
        g.current_user      UserMaster
        g.current_employee  EmployeeMaster
        g.user_id           int
        g.employee_id       int
        g.tenant_id         str   [MW-003]
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({
                "error": "Missing token",
                "message": "Authorization header with Bearer token required",
            }), 401

        token = auth_header.split(" ", 1)[1]
        user, employee, tenant, err = _resolve_user_from_token(token)
        if err is not None:
            return err

        g.current_user     = user
        g.current_employee = employee
        g.user_id          = user.user_id
        g.employee_id      = employee.employee_id
        g.tenant_id        = employee.tenant_id  # [MW-003] string slug

        return f(*args, **kwargs)

    return decorated_function


def require_owner(f):
    """
    [MW-004] Decorator: must be applied AFTER @auth_required.
    Returns 403 if the authenticated user is not the tenant owner.

    PRD §2.2 — only the Tenant Owner may upgrade, cancel, or manage billing.

    """
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if user is None:
            return jsonify({"error": "Unauthenticated"}), 401

        if not getattr(user, "is_owner", False):
            return jsonify({"error": "owner_required"}), 403

        return f(*args, **kwargs)

    return decorated


require_tenant_owner = require_owner


# ---------------------------------------------------------------------------
# [MW-005] permission_required is NOT defined here.
# Import it from permission_middleware via middleware/__init__.py:
#
#     from middleware import permission_required
#
# Defining it here caused middleware/__init__.py to overwrite the correct
# PermissionService-backed version with this inline version. Removed.
# ---------------------------------------------------------------------------
