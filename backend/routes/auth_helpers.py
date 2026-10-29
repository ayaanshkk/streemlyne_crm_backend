# backend/routes/auth_helpers.py
"""
Adapter so the company/contact route files can keep using @token_required
and request.current_user on top of StreemLyne's existing auth_required.

WHY THE TENANT/EMPLOYEE OVERRIDE EXISTS
StreemLyne logins come from the main database (DATABASE_URL): tenant_id is a
string slug ("daniya-shaikh-1e2317") and employee_id is an id from THAT
database. The Companies/Contacts modules query the separate FAI database
(NEW_DATABASE_URL, schema streemLyne_mt_dev2), where tenant_id is an integer
and employee ids are a different set. The two databases' ids are unrelated, so
they can't be looked up against each other.

Until auth itself moves to the dev2 schema, point the new modules at a dev2
tenant/employee explicitly in backend/.env:

    DEV2_TENANT_ID=<tenant_id that owns the data in streemLyne_mt_dev2>
    DEV2_EMPLOYEE_ID=<an employee_id that exists in streemLyne_mt_dev2.Employee_Master>

(DEV2_EMPLOYEE_ID is what gets stored in created_by_user_id, so it must exist
there or the insert fails its foreign key.)

Once auth is migrated and already returns numeric ids, just remove both
variables and the real values are used.
"""
import os
from functools import wraps
from types import SimpleNamespace

from flask import g, jsonify, request

from middleware.auth_middleware import auth_required


def _env_int(name):
    value = (os.getenv(name) or "").strip()
    return int(value) if value.isdigit() else None


def token_required(f):
    @auth_required
    @wraps(f)
    def decorated(*args, **kwargs):
        tenant_id = _env_int("DEV2_TENANT_ID")
        if tenant_id is None:
            tenant_id = g.tenant_id  # only usable if auth already gives a numeric id

        employee_id = _env_int("DEV2_EMPLOYEE_ID")
        if employee_id is None:
            employee_id = g.employee_id

        if not str(tenant_id).isdigit():
            return jsonify({
                "error": "Tenant mapping not configured",
                "details": (
                    "Set DEV2_TENANT_ID (and DEV2_EMPLOYEE_ID) in backend/.env "
                    "to a tenant/employee that exists in streemLyne_mt_dev2, "
                    "then restart the backend."
                ),
            }), 500

        request.current_user = SimpleNamespace(
            user_id=g.user_id,
            employee_id=employee_id,
            tenant_id=int(tenant_id),
            user=g.current_user,
            employee=getattr(g, "current_employee", None),
        )
        return f(*args, **kwargs)

    return decorated


__all__ = ["token_required"]