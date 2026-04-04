# middleware/auth_middleware.py
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
    Returns (user, employee, tenant, None) on success.
    Returns (None, None, None, (response, status)) on any failure.
    """
    try:
        payload = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None, None, None, (jsonify({"error": "Token expired", "message": "Please log in again"}), 401)
    except jwt.InvalidTokenError:
        return None, None, None, (jsonify({"error": "Invalid token", "message": "Authentication token is invalid"}), 401)

    # Explicit type guard — rejects customer tokens cleanly rather than
    # falling through to a confusing "user not found" error.
    if payload.get("type") != "staff":
        return None, None, None, (jsonify({"error": "Invalid token", "message": "Staff token required"}), 401)

    user_id = payload.get("user_id")
    if not user_id:
        return None, None, None, (jsonify({"error": "Invalid token", "message": "Token is missing user_id claim"}), 401)

    user = db.session.get(UserMaster, user_id)
    if not user:
        return None, None, None, (jsonify({"error": "Invalid token", "message": "User not found"}), 401)

    if not user.employee_id:
        return None, None, None, (jsonify({"error": "Account misconfigured", "message": "User has no linked employee record"}), 403)

    employee = db.session.get(EmployeeMaster, user.employee_id)
    if not employee:
        return None, None, None, (jsonify({"error": "Account misconfigured", "message": "Employee record not found"}), 403)

    tenant = db.session.get(TenantMaster, employee.tenant_id)

    # FIX: Tenant_Master.is_active has no NOT NULL constraint in DDL — it can be NULL.
    # Treat NULL as inactive to fail safe. Only explicitly True passes.
    if not tenant or tenant.is_active is not True:
        return None, None, None, (jsonify({"error": "Tenant inactive", "message": "Your organisation's account is inactive"}), 403)

    return user, employee, tenant, None


def auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing token", "message": "Authorization header with Bearer token required"}), 401

        token = auth_header.split(" ", 1)[1]
        
        user, employee, tenant, err = _resolve_user_from_token(token)
        if err is not None:
            return err

        g.current_user     = user
        g.current_employee = employee
        g.user_id          = user.user_id
        g.employee_id      = employee.employee_id
        g.tenant_id        = employee.tenant_id   # BigInteger — safe for all filter comparisons

        return f(*args, **kwargs)

    return decorated_function