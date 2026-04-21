"""
Subscription Middleware
Per-request enforcement of tenant subscription status.

Usage — Option A: decorate individual routes
────────────────────────────────────────────
    from middleware.subscription_middleware import subscription_required

    @app.route('/api/clients')
    @auth_required          # must come first — sets g.tenant_id
    @subscription_required  # then gate on subscription
    def list_clients():
        ...

Usage — Option B: register as a before_request hook (recommended)
──────────────────────────────────────────────────────────────────
    Add to app.py (or wherever the Flask app is created):

        from middleware.subscription_middleware import enforce_subscription
        app.before_request(enforce_subscription)

    enforce_subscription() reads g.tenant_id (set by auth_required) and
    returns a 402 for expired/canceled tenants on any non-exempt path.
    auth_required must run before it — put auth registration first.

Exempt paths
────────────
Routes listed in EXEMPT_PREFIXES are always allowed through so that
expired tenants can still read their status, attempt checkout, and
receive webhook events.

Add paths here if you need additional exemptions (e.g. a public health
check endpoint).
"""

from functools import wraps

from flask import Request, g, jsonify, request

from services.subscription_service import SubscriptionService

# ---------------------------------------------------------------------------
# Paths that skip the subscription gate.
# These must be reachable by expired / unauthenticated callers.
# ---------------------------------------------------------------------------
EXEMPT_PREFIXES: tuple[str, ...] = (
    # Subscription self-service — expired tenants must be able to read status
    # and initiate checkout
    "/api/subscriptions/me",
    "/api/subscriptions/plans",
    "/api/subscriptions/stripe/webhook",

    # Auth — unauthenticated callers must reach login / register
    "/api/auth/",

    # Health / infra
    "/api/health",
    "/health",
)


def _is_exempt(path: str) -> bool:
    """Return True if *path* is exempt from the subscription gate."""
    return any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES)


# ---------------------------------------------------------------------------
# Option A: decorator
# ---------------------------------------------------------------------------

def subscription_required(f):
    """
    Route decorator that returns 402 for expired or canceled tenants.

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

    Returns a 402 JSON response for expired/canceled tenants on non-exempt
    routes.  Returns None (Flask convention for "proceed") for all other cases.
    """
    # Only apply to authenticated requests (g.tenant_id set by auth_required)
    tenant_id = getattr(g, "tenant_id", None)
    if not tenant_id:
        return None  # unauthenticated — let auth_required handle it

    # Skip exempt paths
    if _is_exempt(request.path):
        return None

    if not SubscriptionService.tenant_has_access(tenant_id):
        return _subscription_required_response()

    return None  # proceed


# ---------------------------------------------------------------------------
# Shared 402 response
# ---------------------------------------------------------------------------

def _subscription_required_response():
    """
    Return a machine-readable 402 that the frontend intercepts in api.ts.

    The frontend's global 402 handler (src/lib/api.ts) already redirects to
    /subscription-required on this status code.  The body gives it extra
    context to distinguish 'expired trial' from 'canceled paid plan' if needed.
    """
    return jsonify({
        "error":    "subscription_required",
        "message":  "Your subscription has expired. Please upgrade to continue.",
        "redirect": "/subscription-required",
    }), 402