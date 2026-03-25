# tenant_middleware.py - StreemLyne_MT
# JWT is decoded here directly; UserMaster has no verify_jwt_token() method.
# Tenant context is resolved via: UserMaster → EmployeeMaster → TenantMaster

import jwt
from flask import g, request, jsonify, current_app
from functools import wraps

def require_tenant(f):
    """
    Decorator that:
      1. Validates the Bearer JWT
      2. Resolves UserMaster → EmployeeMaster → TenantMaster
      3. Populates Flask g with tenant_id, user_id, employee_id, user, tenant
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from models import UserMaster, EmployeeMaster, TenantMaster

        # ── 1. Extract token ──────────────────────────────────────────────
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "No authorization token"}), 401

        token = auth_header[len("Bearer "):]

        # ── 2. Decode JWT ─────────────────────────────────────────────────
        try:
            payload = jwt.decode(
                token,
                current_app.config["SECRET_KEY"],
                algorithms=["HS256"],
            )
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401

        user_id = payload.get("user_id")
        if not user_id:
            return jsonify({"error": "Token missing user_id claim"}), 401

        # ── 3. Load UserMaster ────────────────────────────────────────────
        user = UserMaster.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 401

        # ── 4. Resolve tenant via EmployeeMaster ──────────────────────────
        if not user.employee_id:
            return jsonify({"error": "User has no associated employee record"}), 403

        employee = EmployeeMaster.query.get(user.employee_id)
        if not employee:
            return jsonify({"error": "Employee record not found"}), 403

        # ── 5. Load and validate TenantMaster ─────────────────────────────
        tenant = TenantMaster.query.get(employee.tenant_id)
        if not tenant or not tenant.is_active:
            return jsonify({"error": "Tenant not found or inactive"}), 403

        # ── 6. Populate Flask g ───────────────────────────────────────────
        g.user_id     = user.user_id
        g.employee_id = employee.employee_id
        g.tenant_id   = tenant.tenant_id
        g.user        = user
        g.employee    = employee
        g.tenant      = tenant

        return f(*args, **kwargs)

    return decorated_function


def get_tenant_query(model_class):
    """
    Returns a SQLAlchemy query pre-filtered by the current tenant.
    Must be called inside a route protected by @require_tenant.
    """
    if not hasattr(g, "tenant_id"):
        raise RuntimeError(
            "Tenant context not set — wrap this route with @require_tenant"
        )
    return model_class.query.filter_by(tenant_id=g.tenant_id)


def check_role(required_role_id: int) -> bool:
    """
    Check whether the current employee holds a given role.
    EmployeeMaster.role_ids is a comma-separated string of role_id integers.
    """
    if not hasattr(g, "employee"):
        return False
    if not g.employee.role_ids:
        return False
    held_ids = [r.strip() for r in g.employee.role_ids.split(",")]
    return str(required_role_id) in held_ids
# Alias for backward compatibility
token_required = require_tenant