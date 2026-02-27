from functools import wraps
from typing import Optional

import jwt
from flask import current_app, g, jsonify, request

from database import db
from models import EmployeeMaster, UserMaster

_PUBLIC_ENDPOINTS = frozenset({"login", "register", "health", "static"})


def get_current_tenant_id() -> Optional[int]:
    return getattr(g, "tenant_id", None)


def inject_tenant_context() -> None:
    if request.method == "OPTIONS" or request.endpoint in _PUBLIC_ENDPOINTS:
        return

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return

    token = auth_header.split(" ", 1)[1]

    try:
        payload = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return

    user_id     = payload.get("user_id")
    tenant_id   = payload.get("tenant_id")
    employee_id = payload.get("employee_id")

    if tenant_id:
        g.tenant_id   = tenant_id
        g.user_id     = user_id
        g.employee_id = employee_id
        return

    if not user_id:
        return

    user = db.session.get(UserMaster, user_id)
    if not user or not user.employee_id:
        return

    employee = db.session.get(EmployeeMaster, user.employee_id)
    if not employee:
        return

    g.tenant_id   = employee.tenant_id
    g.user_id     = user.user_id
    g.employee_id = employee.employee_id


def tenant_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if get_current_tenant_id() is None:
            return jsonify({"error": "Tenant context not found", "message": "Invalid or missing authentication token"}), 401
        return f(*args, **kwargs)
    return decorated_function