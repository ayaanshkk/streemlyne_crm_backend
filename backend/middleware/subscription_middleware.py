"""
Subscription Middleware
Centralized per-request enforcement of tenant subscription status.

The auth decorator only authenticates and populates flask.g. This module owns
the subscription gate and the single exemption list used across the app.
"""

from functools import wraps

from flask import g, jsonify, request

from middleware.auth_middleware import _resolve_user_from_token
from services.subscription_service import SubscriptionService

EXPIRED_TENANT_ALLOWED_PATHS = {
    ("GET", "/api/subscriptions/me"),
    ("POST", "/api/subscriptions/me/checkout"),
    ("GET", "/api/subscriptions/plans"),
    ("POST", "/api/subscriptions/stripe/webhook"),
    ("GET", "/api/health"),
    ("GET", "/health"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/refresh"),
}


def is_allowed_for_expired(method: str, path: str) -> bool:
    return (method.upper(), path) in EXPIRED_TENANT_ALLOWED_PATHS


def _populate_request_context():
    """Resolve a Bearer token and seed flask.g for before_request checks."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1]
    user, employee, _tenant, err = _resolve_user_from_token(token)
    if err is not None:
        return None

    g.current_user = user
    g.current_employee = employee
    g.user_id = user.user_id
    g.employee_id = employee.employee_id
    g.tenant_id = employee.tenant_id
    return employee.tenant_id


# ---------------------------------------------------------------------------
# Option A: decorator
# ---------------------------------------------------------------------------

def subscription_required(f):
    """
    Route decorator that returns 403 for expired or canceled tenants.

    Must be applied *after* @auth_required so g.tenant_id is already set.

    Example:
        @app.route('/api/something')
        @auth_required
        @subscription_required
        def something():
            ...
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        tenant_id = getattr(g, "tenant_id", None)
        if not tenant_id:
            tenant_id = _populate_request_context()
        if is_allowed_for_expired(request.method, request.path):
            return f(*args, **kwargs)
        if tenant_id and not SubscriptionService.tenant_has_access(tenant_id):
            return _subscription_required_response()
        return f(*args, **kwargs)

    return decorated_function


# ---------------------------------------------------------------------------
# Option B: before_request hook
# ---------------------------------------------------------------------------

def enforce_subscription():
    """
    Flask before_request hook that gates every authenticated API request.

    Register once in app.py:
        from middleware.subscription_middleware import enforce_subscription
        app.before_request(enforce_subscription)

    Returns a 403 JSON response for expired/canceled tenants on non-exempt
    routes.  Returns None (Flask convention for "proceed") for all other cases.
    """
    if request.method == "OPTIONS" or is_allowed_for_expired(request.method, request.path):
        return None

    tenant_id = getattr(g, "tenant_id", None) or _populate_request_context()
    if not tenant_id:
        return None

    if not SubscriptionService.tenant_has_access(tenant_id):
        return _subscription_required_response()

    return None  # proceed


# ---------------------------------------------------------------------------
# Shared 403 response
# ---------------------------------------------------------------------------

def _subscription_required_response():
    """
    Return a machine-readable 403 for expired/canceled tenants.
    """
    return jsonify({
        "error":    "subscription_required",
        "message":  "Your subscription has expired. Please upgrade to continue.",
        "redirect": "/subscription-required",
    }), 403
