# middleware/auth_middleware.py
"""
Auth Middleware
Handles JWT validation and subscription enforcement for every authenticated request.

CHANGES vs previous version
─────────────────────────────────────────────────────────────────────────────
[MW-001] Subscription gate added to auth_required.
         After JWT validation and tenant-active check, we now call
         SubscriptionService.tenant_has_access(tenant_id).
         Returns HTTP 402 with a redirect hint when the tenant's subscription
         is expired or cancelled so the frontend can redirect to
         /subscription-required.

[MW-002] SUBSCRIPTION_EXEMPT_PATHS — paths that bypass the subscription gate.
         Subscription-management endpoints (/api/subscriptions/me/*) and the
         Stripe webhook must be reachable even when the subscription is expired,
         otherwise an expired tenant can never upgrade or receive webhook events.

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
from typing import Optional, cast  # [MW-FIX] cast was missing — caused ImportError

import jwt
from flask import current_app, g, jsonify, request

from database import db
from models import EmployeeMaster, TenantMaster, UserMaster

# ---------------------------------------------------------------------------
# [MW-002] Paths that skip the subscription access gate.
# Matching is prefix-based: any request.path that STARTS WITH one of these
# strings will bypass the gate.
# ---------------------------------------------------------------------------
_SUBSCRIPTION_EXEMPT_PREFIXES = (
    "/api/subscriptions/me",        # GET status, POST checkout, POST cancel
    "/api/subscriptions/stripe",    # Stripe webhook — no auth at all
    "/api/subscriptions/plans",     # Plan catalogue — read-only reference data
    "/api/auth/",                   # All auth endpoints are public
    "/api/tenant/info",             # Own-tenant read (non-billing)
)

#: Role names that are considered "owners" for billing/subscription actions.
#: [MW-004] Defined at module level so it's shared with tests.
_OWNER_ROLE_NAMES = frozenset({"Admin", "Super Admin", "Tenant Owner"})


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


def _subscription_is_exempt(path: str) -> bool:
    """Return True if the request path should skip the subscription gate."""
    return any(path.startswith(prefix) for prefix in _SUBSCRIPTION_EXEMPT_PREFIXES)


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

        # ── [MW-001] Subscription gate ──────────────────────────────────────
        if not _subscription_is_exempt(request.path):
            from services.subscription_service import SubscriptionService
            if not SubscriptionService.tenant_has_access(employee.tenant_id):
                return jsonify({
                    "error": "Subscription required",
                    "message": (
                        "Your subscription has expired or been cancelled. "
                        "Please upgrade to continue using the application."
                    ),
                    "redirect": "/subscription-required",
                    "code": "SUBSCRIPTION_EXPIRED",
                }), 402
        # ───────────────────────────────────────────────────────────────────

        g.current_user     = user
        g.current_employee = employee
        g.user_id          = user.user_id
        g.employee_id      = employee.employee_id
        g.tenant_id        = employee.tenant_id  # [MW-003] string slug

        return f(*args, **kwargs)

    return decorated_function


def require_tenant_owner(f):
    """
    [MW-004] Decorator: must be applied AFTER @auth_required.
    Returns 403 if the authenticated user does not hold an owner-level role.

    PRD §2.2 — only the Tenant Owner may upgrade, cancel, or manage billing.

    Role names checked: Admin, Super Admin, Tenant Owner.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if user is None:
            return jsonify({"error": "Unauthenticated"}), 401

        # [MW-FIX] cast is now correctly imported at the top of this file.
        roles = cast(list, user.roles or [])
        role_names = {r.role_name for r in roles if hasattr(r, "role_name")}

        if not role_names.intersection(_OWNER_ROLE_NAMES):
            return jsonify({
                "error": "Forbidden",
                "message": "Only a tenant administrator can manage the subscription.",
            }), 403

        return f(*args, **kwargs)

    return decorated


# ---------------------------------------------------------------------------
# [MW-005] permission_required is NOT defined here.
# Import it from permission_middleware via middleware/__init__.py:
#
#     from middleware import permission_required
#
# Defining it here caused middleware/__init__.py to overwrite the correct
# PermissionService-backed version with this inline version. Removed.
# ---------------------------------------------------------------------------