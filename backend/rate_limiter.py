"""
rate_limiter.py
Flask-Limiter setup for the Subscription Module (and the whole app).

SETUP
─────
1. Install the package:
       pip install flask-limiter

2. Drop this file into backend/ alongside app.py.

3. In app.py, replace wherever you create/configure the Flask app with:

       from rate_limiter import configure_limiter, limiter

       app = Flask(__name__)
       # ... your existing config / blueprint registration ...
       configure_limiter(app)

4. That's it.  Default limits apply to every route.
   Use @limiter.limit("...") on individual routes to override.

STORAGE
───────
The default storage is in-process memory, which is fine for a single
worker.  For production (multiple gunicorn workers / containers) switch
to Redis:

    RATELIMIT_STORAGE_URI = "redis://localhost:6379/0"

Set that in your .env / config.py and it will be picked up automatically.

LIMITS IN USE
─────────────
Global default:    100 requests / minute  per user (or IP if no user)
Stripe webhook:    unlimited (Stripe's own retry logic handles back-off)
Checkout:          10 requests / minute   per user  (prevent session spam)
Cancel:            5  requests / minute   per user
Auth (login):      20 requests / minute   per IP    (brute-force protection)

PRD §8 requirement: "100 requests / minute per user".
"""

import os

from flask import Flask, g, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


# ---------------------------------------------------------------------------
# Key function: use authenticated user ID when available, else fall back to IP
# ---------------------------------------------------------------------------

def _rate_limit_key() -> str:
    """
    Use the authenticated user's ID as the rate-limit key so limits apply
    per-user rather than per-IP (which would penalise offices / shared NAT).
    Falls back to IP for unauthenticated requests (e.g. /auth/login).
    """
    user_id = getattr(g, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return get_remote_address()


# ---------------------------------------------------------------------------
# Limiter instance — imported by individual route files if needed
# ---------------------------------------------------------------------------

limiter = Limiter(
    key_func     = _rate_limit_key,
    default_limits = ["100 per minute"],
    storage_uri  = (
        os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    ),
    # Return 429 as JSON (not HTML) so the frontend can parse it
    on_breach    = None,   # replaced by the custom handler below
)


# ---------------------------------------------------------------------------
# Register on the app
# ---------------------------------------------------------------------------

def configure_limiter(app: Flask) -> None:
    """
    Attach the limiter to the app and register route-specific overrides.

    Call once after all blueprints are registered:

        from rate_limiter import configure_limiter
        configure_limiter(app)
    """
    limiter.init_app(app)

    # ── Route-specific overrides ────────────────────────────────────────────

    # Stripe webhook: exempt entirely — Stripe manages its own retry policy.
    limiter.exempt(
        app.view_functions.get("subscription.stripe_webhook")
    )

    # Checkout session: tighter limit to prevent session-creation spam
    _apply_if_exists(app, "subscription.create_checkout_session", "10 per minute")

    # Self-service cancel: very low — one cancel per subscription is normal
    _apply_if_exists(app, "subscription.cancel_my_subscription", "5 per minute")

    # Admin cancel: same
    _apply_if_exists(app, "subscription.cancel_tenant_subscription", "5 per minute")

    # Auth login: IP-based brute-force protection
    _apply_if_exists(app, "auth.login", "20 per minute", key_func=get_remote_address)
    _apply_if_exists(app, "auth.register", "10 per minute", key_func=get_remote_address)

    # ── Custom 429 JSON response ────────────────────────────────────────────
    @app.errorhandler(429)
    def ratelimit_handler(exc):
        return jsonify({
            "error":       "rate_limit_exceeded",
            "message":     "Too many requests. Please slow down.",
            "retry_after": exc.description,
        }), 429


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _apply_if_exists(app: Flask, endpoint: str, limit: str, key_func=None) -> None:
    """Apply a rate-limit override to a named view function if it exists."""
    view = app.view_functions.get(endpoint)
    if view is None:
        app.logger.warning(
            "[RATE_LIMITER] View function '%s' not found — skipping limit override",
            endpoint,
        )
        return
    kwargs = {"key_func": key_func} if key_func else {}
    limiter.limit(limit, **kwargs)(view)
