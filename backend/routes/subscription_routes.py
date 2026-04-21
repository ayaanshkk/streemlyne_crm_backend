"""
Subscription Routes
Handles: Subscription_Plans, Tenant_Subscription, Subscription_Module_Mapping,
         Stripe Checkout, and Stripe Webhooks.

CHANGELOG (original)
─────────────────────────────────────────────────────────────────────────────
[SUB-R-001] All <int:tenant_id> URL converters changed to <string:tenant_id>.
[SUB-R-002] _plan_dict() includes stripe_price_id.
[SUB-R-003] _tenant_sub_dict() includes status, trial/Stripe fields.
[SUB-R-004] assign_subscription() / cancel routes route through SubscriptionService.
[SUB-R-005] GET /me — returns full subscription status.
[SUB-R-006] POST /me/checkout — Stripe Checkout Session or Custom sales URL.
[SUB-R-007] POST /me/cancel — self-service cancel at period end.
[SUB-R-008] POST /stripe/webhook — handles checkout.session.completed,
            invoice.paid, customer.subscription.deleted.
[SUB-R-009] @permission_required decorators restored on admin endpoints.

NEW in this revision
─────────────────────────────────────────────────────────────────────────────
[FIX-R-001] _handle_checkout_completed() — calls _reconcile_tenant_modules()
            after activating the subscription so Tenant_Module_Mapping is
            immediately correct after a successful Stripe checkout.

[FIX-R-002] _handle_subscription_deleted() — calls _reconcile_tenant_modules()
            with subscription_id=None to strip non-core module access when
            Stripe confirms deletion.

[FIX-R-003] assign_subscription() route — now calls
            svc.admin_assign_subscription() instead of svc.create_subscription().
            This allows sales to manually assign any plan (including Custom)
            to a tenant that already has an active trial or subscription.

[FIX-R-004] cancel_tenant_subscription() admin route — now uses period-end
            semantics matching the self-service cancel route (was calling
            svc.cancel_subscription() which previously did immediate
            deactivation; both routes now share the same PRD §4.5 behaviour).
─────────────────────────────────────────────────────────────────────────────

Environment variables required:
    STRIPE_SECRET_KEY      sk_live_… or sk_test_…
    STRIPE_WEBHOOK_SECRET  whsec_…
    STRIPE_SUCCESS_URL     http://localhost:3000/subscription/success?session_id={CHECKOUT_SESSION_ID}
    STRIPE_CANCEL_URL      http://localhost:3000/subscription-required
"""

import os
from datetime import date, datetime, timezone

from flask import Blueprint, abort, current_app, g, jsonify, request
from sqlalchemy.exc import IntegrityError

from database import db
from middleware import auth_required, permission_required, require_tenant_owner
from models import (
    ModuleMaster,
    SubscriptionModuleMapping,
    SubscriptionPlan,
    TenantMaster,
    TenantSubscription,
)
from services.subscription_service import SubscriptionService

# ---------------------------------------------------------------------------
# Optional Stripe import
# ---------------------------------------------------------------------------
try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    stripe = None
    STRIPE_AVAILABLE = False

subscription_bp = Blueprint("subscription", __name__, url_prefix="/subscriptions")


# =============================================================================
# SECTION 1: Self-service endpoints (current tenant)
# =============================================================================

@subscription_bp.route("/me", methods=["GET"])
@auth_required
def get_my_subscription():
    """
    [SUB-R-005] Return the full subscription status for the calling tenant.
    GET /api/subscriptions/me

    Exempt from the subscription gate so expired tenants can always read
    their status and know they need to upgrade.
    """
    svc    = SubscriptionService()
    status = svc.check_subscription_status(g.tenant_id)
    return jsonify(status), 200


@subscription_bp.route("/me/checkout", methods=["POST"])
@auth_required
@require_tenant_owner
def create_checkout_session():
    """
    [SUB-R-006] Create a Stripe Checkout Session (STARTER / PRO) or return
    a sales contact URL (CUSTOM).

    POST /api/subscriptions/me/checkout
    Body: { "plan_code": "STARTER" }

    Returns:
        STARTER/PRO: { "checkout_url": "https://checkout.stripe.com/…" }
        CUSTOM:      { "contact_url": "mailto:sales@…", "is_custom": true }

    Restricted to Tenant Owner (PRD §2.2).
    Exempt from subscription gate so expired tenants can upgrade.
    """
    data      = request.get_json() or {}
    plan_code = (data.get("plan_code") or "").strip().upper()

    if not plan_code:
        return jsonify({"error": "plan_code is required"}), 400

    plan = SubscriptionPlan.query.filter_by(
        subscription_code=plan_code, is_active=True
    ).first()
    if not plan:
        return jsonify({"error": f"Plan '{plan_code}' not found or inactive"}), 404

    # ── Custom plan: no Stripe — route to sales ──────────────────────────────
    if plan.subscription_code == "CUSTOM":
        sales_email = current_app.config.get("SALES_CONTACT_EMAIL", "sales@streemlyne.com")
        return jsonify({
            "is_custom":     True,
            "contact_url":   f"mailto:{sales_email}?subject=Custom%20Plan%20Enquiry",
            "contact_email": sales_email,
            "message":       "Contact our sales team to set up a custom plan.",
        }), 200

    # ── Stripe: STARTER / PRO ────────────────────────────────────────────────
    if not plan.stripe_price_id:
        current_app.logger.error(
            "[STRIPE] Paid plan %s is missing stripe_price_id", plan.subscription_code
        )
        return jsonify({
            "error":   "Plan is not configured for Stripe checkout",
            "message": f"Plan '{plan.subscription_code}' has no stripe_price_id configured.",
        }), 500

    if not STRIPE_AVAILABLE:
        return jsonify({"error": "stripe package not installed. Run: pip install stripe"}), 500

    stripe_key = (
        current_app.config.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY")
    )
    if not stripe_key:
        return jsonify({"error": "STRIPE_SECRET_KEY is not configured"}), 500

    stripe.api_key = stripe_key

    success_url = (
        current_app.config.get("STRIPE_SUCCESS_URL")
        or os.environ.get("STRIPE_SUCCESS_URL")
        or "http://localhost:3000/subscription/success?session_id={CHECKOUT_SESSION_ID}"
    )
    cancel_url = (
        current_app.config.get("STRIPE_CANCEL_URL")
        or os.environ.get("STRIPE_CANCEL_URL")
        or "http://localhost:3000/subscription-required"
    )

    tenant = db.session.get(TenantMaster, g.tenant_id)
    if not tenant:
        return jsonify({"error": "Tenant not found"}), 404

    try:
        if tenant.stripe_customer_id:
            customer_id = tenant.stripe_customer_id
        else:
            customer = stripe.Customer.create(
                name     = tenant.tenant_company_name,
                metadata = {"tenant_id": g.tenant_id},
            )
            customer_id = customer.id
            tenant.stripe_customer_id = customer_id
            db.session.commit()

        session = stripe.checkout.Session.create(
            customer             = customer_id,
            payment_method_types = ["card"],
            line_items           = [{"price": plan.stripe_price_id, "quantity": 1}],
            mode                 = "subscription",
            success_url          = success_url,
            cancel_url           = cancel_url,
            metadata             = {
                "tenant_id": g.tenant_id,
                "plan_code": plan.subscription_code,
            },
        )
    except stripe.error.StripeError as exc:
        current_app.logger.error(
            "[STRIPE] Checkout session error for tenant %s: %s", g.tenant_id, exc
        )
        return jsonify({"error": "Stripe error", "message": str(exc)}), 502

    return jsonify({"checkout_url": session.url}), 200


@subscription_bp.route("/me/cancel", methods=["POST"])
@auth_required
@require_tenant_owner
def cancel_my_subscription():
    """
    [SUB-R-007] Cancel the calling tenant's subscription at period end.
    POST /api/subscriptions/me/cancel

    PRD §4.5: Access continues until the billing period ends.
    Restricted to Tenant Owner (PRD §2.2).
    """
    sub = (
        TenantSubscription.query
        .filter_by(tenant_id=g.tenant_id, is_active=True)
        .order_by(TenantSubscription.created_at.desc())
        .first()
    )
    if not sub:
        return jsonify({"error": "No active subscription found"}), 404

    # Stripe-managed plan: cancel at period end via Stripe API
    if sub.stripe_subscription_id and STRIPE_AVAILABLE:
        stripe_key = (
            current_app.config.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY")
        )
        if not stripe_key:
            return jsonify({"error": "STRIPE_SECRET_KEY is not configured"}), 500

        stripe.api_key = stripe_key
        try:
            stripe_sub = stripe.Subscription.modify(
                sub.stripe_subscription_id,
                cancel_at_period_end=True,
            )
            period_end_ts = stripe_sub.get("current_period_end")
            if period_end_ts:
                sub.current_period_end    = datetime.utcfromtimestamp(period_end_ts)
                sub.subscription_end_date = sub.current_period_end.date()

            sub.cancel_at_period_end = True
            sub.auto_renew           = False
            sub.updated_at           = datetime.utcnow()
            db.session.commit()
        except stripe.error.StripeError as exc:
            current_app.logger.error(
                "[STRIPE] Cancel error for tenant %s: %s", g.tenant_id, exc
            )
            return jsonify({"error": "Stripe error", "message": str(exc)}), 502

        return jsonify({
            "message":            "Subscription will be cancelled at the end of the current billing period.",
            "cancel_at":          sub.subscription_end_date.isoformat() if sub.subscription_end_date else None,
            "cancel_at_period_end": True,
        }), 200

    # Manual plan: preserve access until subscription_end_date
    if sub.subscription_end_date is None and sub.subscription:
        sub.subscription_end_date = SubscriptionService._calculate_end_date(
            date.today(),
            sub.subscription.billing_cycle or 1,
        )

    if sub.current_period_start is None and sub.subscription_start_date:
        sub.current_period_start = datetime.combine(
            sub.subscription_start_date, datetime.min.time()
        )
    if sub.current_period_end is None and sub.subscription_end_date:
        sub.current_period_end = datetime.combine(
            sub.subscription_end_date, datetime.max.time()
        )

    sub.cancel_at_period_end = True
    sub.auto_renew           = False
    sub.updated_at           = datetime.utcnow()
    db.session.commit()

    return jsonify({
        "message":            "Subscription will be cancelled at the end of the current billing period.",
        "cancel_at":          sub.subscription_end_date.isoformat() if sub.subscription_end_date else None,
        "cancel_at_period_end": True,
    }), 200


# =============================================================================
# SECTION 2: Stripe Webhook (no JWT auth)
# =============================================================================

@subscription_bp.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """
    [SUB-R-008] Receive and process Stripe webhook events.
    POST /api/subscriptions/stripe/webhook

    Handles:
        checkout.session.completed   → activate subscription + reconcile modules
        invoice.paid                 → renew / extend subscription
        customer.subscription.deleted → cancel + strip non-core modules
    """
    if not STRIPE_AVAILABLE:
        return jsonify({"error": "stripe package not installed"}), 500

    webhook_secret = (
        current_app.config.get("STRIPE_WEBHOOK_SECRET")
        or os.environ.get("STRIPE_WEBHOOK_SECRET")
    )
    stripe_key = (
        current_app.config.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY")
    )

    if not stripe_key:
        return jsonify({"error": "STRIPE_SECRET_KEY not configured"}), 500
    if not webhook_secret and not current_app.config.get("TESTING"):
        current_app.logger.error("[STRIPE] STRIPE_WEBHOOK_SECRET required for webhook verification")
        return jsonify({"error": "STRIPE_WEBHOOK_SECRET not configured"}), 500

    stripe.api_key = stripe_key

    payload    = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        else:
            import json
            event = stripe.Event.construct_from(json.loads(payload), stripe_key)
            current_app.logger.warning("[STRIPE] Webhook signature verification disabled (test mode)")
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        current_app.logger.warning("[STRIPE] Webhook signature error: %s", exc)
        return jsonify({"error": "Invalid webhook signature"}), 400

    event_type = event["type"]
    event_data = event["data"]["object"]
    current_app.logger.info("[STRIPE] Webhook received: %s", event_type)

    try:
        if event_type == "checkout.session.completed":
            _handle_checkout_completed(event_data)
        elif event_type == "invoice.paid":
            _handle_invoice_paid(event_data)
        elif event_type == "customer.subscription.deleted":
            _handle_subscription_deleted(event_data)
        else:
            current_app.logger.debug("[STRIPE] Unhandled event type: %s", event_type)
    except Exception as exc:
        current_app.logger.error("[STRIPE] Error processing %s: %s", event_type, exc)
        db.session.rollback()
        return jsonify({"error": str(exc)}), 500

    return jsonify({"received": True}), 200


def _handle_checkout_completed(session):
    """
    checkout.session.completed → activate subscription and reconcile modules.

    [FIX-R-001] After updating the subscription row, calls
    _reconcile_tenant_modules() so Tenant_Module_Mapping is correct
    immediately after a successful Stripe checkout — no manual sync needed.
    """
    tenant_id     = (session.get("metadata") or {}).get("tenant_id")
    plan_code     = (session.get("metadata") or {}).get("plan_code")
    stripe_sub_id = session.get("subscription")

    if not tenant_id:
        current_app.logger.warning(
            "[STRIPE] checkout.session.completed missing tenant_id metadata"
        )
        return

    sub = (
        TenantSubscription.query
        .filter_by(tenant_id=tenant_id)
        .order_by(TenantSubscription.created_at.desc())
        .first()
    )

    # Update plan if the checkout was for a different plan than the trial
    if sub and plan_code:
        plan = SubscriptionPlan.query.filter_by(subscription_code=plan_code).first()
        if plan:
            sub.subscription_id = plan.subscription_id

    if not sub:
        current_app.logger.warning(
            "[STRIPE] No TenantSubscription found for tenant %s", tenant_id
        )
        return

    sub.status                 = "active"
    sub.is_active              = True
    sub.cancel_at_period_end   = False
    sub.stripe_subscription_id = stripe_sub_id
    sub.subscription_start_date = date.today()
    sub.updated_at             = datetime.utcnow()

    if sub.subscription and sub.subscription.billing_cycle:
        from dateutil.relativedelta import relativedelta
        bc  = sub.subscription.billing_cycle
        end = (
            date.today() + relativedelta(years=1)
            if bc == 12
            else date.today() + relativedelta(months=bc or 1)
        )
        sub.subscription_end_date = end
        sub.current_period_start  = datetime.utcnow()
        sub.current_period_end    = datetime.combine(end, datetime.max.time())

    # [FIX-R-001] Reconcile module access to the activated plan
    SubscriptionService._reconcile_tenant_modules(tenant_id, sub.subscription_id)

    db.session.commit()
    current_app.logger.info(
        "[STRIPE] Tenant %s activated on plan %s", tenant_id, plan_code
    )


def _handle_invoice_paid(invoice):
    """
    invoice.paid → renew subscription and update billing period dates.

    Called for every successful recurring billing cycle after the first.
    Does not change module mappings (plan has not changed).
    """
    stripe_sub_id = invoice.get("subscription")
    if not stripe_sub_id:
        return

    sub = TenantSubscription.query.filter_by(
        stripe_subscription_id=stripe_sub_id
    ).first()
    if not sub:
        current_app.logger.warning(
            "[STRIPE] invoice.paid — no TenantSubscription for %s", stripe_sub_id
        )
        return

    period_start_ts = period_end_ts = None
    lines = invoice.get("lines", {}).get("data", [])
    if lines:
        period          = lines[0].get("period", {})
        period_start_ts = period.get("start")
        period_end_ts   = period.get("end")

    if period_start_ts:
        sub.current_period_start = datetime.utcfromtimestamp(period_start_ts)
    if period_end_ts:
        sub.current_period_end    = datetime.utcfromtimestamp(period_end_ts)
        sub.subscription_end_date = sub.current_period_end.date()
    else:
        # Fallback: calculate from billing_cycle
        plan = sub.subscription
        if plan:
            from dateutil.relativedelta import relativedelta
            bc  = plan.billing_cycle or 1
            end = (
                date.today() + relativedelta(years=1)
                if bc == 12
                else date.today() + relativedelta(months=bc)
            )
            sub.subscription_end_date = end
            current_app.logger.warning(
                "[STRIPE] invoice.paid no period data for %s — calculated from billing_cycle",
                stripe_sub_id,
            )

    sub.status    = "active"
    sub.is_active = True
    sub.updated_at = datetime.utcnow()

    db.session.commit()
    current_app.logger.info(
        "[STRIPE] Subscription %s renewed; period_end=%s",
        stripe_sub_id, sub.current_period_end,
    )


def _handle_subscription_deleted(stripe_sub):
    """
    customer.subscription.deleted → cancel and strip non-core module access.

    [FIX-R-002] Now calls _reconcile_tenant_modules(subscription_id=None)
    to remove all non-core module mappings when Stripe confirms deletion,
    so expired tenants cannot access any gated features.
    """
    stripe_sub_id = stripe_sub.get("id")
    if not stripe_sub_id:
        return

    sub = TenantSubscription.query.filter_by(
        stripe_subscription_id=stripe_sub_id
    ).first()
    if not sub:
        current_app.logger.warning(
            "[STRIPE] subscription.deleted — no record for %s", stripe_sub_id
        )
        return

    sub.status              = "canceled"
    sub.is_active           = False
    sub.auto_renew          = False
    sub.cancel_at_period_end = False
    sub.updated_at          = datetime.utcnow()

    period_end_ts = stripe_sub.get("current_period_end")
    if period_end_ts:
        sub.current_period_end    = datetime.utcfromtimestamp(period_end_ts)
        sub.subscription_end_date = sub.current_period_end.date()

    # [FIX-R-002] Remove non-core module access
    SubscriptionService._reconcile_tenant_modules(sub.tenant_id, subscription_id=None)

    db.session.commit()
    current_app.logger.info("[STRIPE] Tenant %s subscription canceled", sub.tenant_id)


# =============================================================================
# SECTION 3: Subscription Plans — catalogue CRUD (admin)
# =============================================================================

@subscription_bp.route("/plans", methods=["GET"])
@auth_required
def list_plans():
    """
    List subscription plans.
    GET /api/subscriptions/plans
    Query: include_inactive=true
    """
    include_inactive = request.args.get("include_inactive", "false").lower() == "true"
    query = SubscriptionPlan.query
    if not include_inactive:
        query = query.filter_by(is_active=True)
    plans = query.order_by(SubscriptionPlan.price).all()
    return jsonify([_plan_dict(p) for p in plans]), 200


@subscription_bp.route("/plans/<int:subscription_id>", methods=["GET"])
@auth_required
def get_plan(subscription_id: int):
    """GET /api/subscriptions/plans/<subscription_id>"""
    plan    = _plan_or_404(subscription_id)
    result  = _plan_dict(plan)
    modules = _modules_for_plan(subscription_id)
    result["modules"] = modules
    return jsonify(result), 200


@subscription_bp.route("/plans", methods=["POST"])
@auth_required
@permission_required("subscription.create_plan")
def create_plan():
    """
    Create a new subscription plan.
    POST /api/subscriptions/plans
    """
    data    = request.get_json() or {}
    missing = [
        f for f in ["subscription_code", "subscription_name", "price", "currency_id", "billing_cycle"]
        if data.get(f) is None
    ]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    plan = SubscriptionPlan(
        subscription_code = data["subscription_code"].strip(),
        subscription_name = data["subscription_name"].strip(),
        description       = data.get("description"),
        price             = data["price"],
        currency_id       = data["currency_id"],
        billing_cycle     = int(data["billing_cycle"]),
        is_base_plan      = bool(data.get("is_base_plan", False)),
        is_active         = bool(data.get("is_active", True)),
        stripe_price_id   = data.get("stripe_price_id") or None,
    )
    try:
        db.session.add(plan)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "subscription_code or subscription_name already exists"}), 409

    return jsonify({"message": "Plan created", "plan": _plan_dict(plan)}), 201


@subscription_bp.route("/plans/<int:subscription_id>", methods=["PUT"])
@auth_required
@permission_required("subscription.create_plan")
def update_plan(subscription_id: int):
    """
    Update a subscription plan.
    PUT /api/subscriptions/plans/<subscription_id>
    """
    plan = _plan_or_404(subscription_id)
    data = request.get_json() or {}

    for field in [
        "subscription_name", "description", "price",
        "currency_id", "billing_cycle", "is_base_plan", "is_active",
        "stripe_price_id",
    ]:
        if field in data:
            setattr(plan, field, data[field])

    plan.updated_at = datetime.utcnow()
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "subscription_name already exists"}), 409

    return jsonify({"message": "Plan updated", "plan": _plan_dict(plan)}), 200


# =============================================================================
# SECTION 4: Tenant Subscriptions — admin management
# =============================================================================

@subscription_bp.route("/tenants/<string:tenant_id>", methods=["GET"])
@auth_required
@permission_required("subscription.view")
def get_tenant_subscription(tenant_id: str):
    """
    Get subscription history for a tenant (admin).
    GET /api/subscriptions/tenants/<tenant_id>
    """
    subs = (
        TenantSubscription.query
        .filter_by(tenant_id=tenant_id)
        .order_by(TenantSubscription.created_at.desc())
        .all()
    )
    return jsonify([_tenant_sub_dict(s) for s in subs]), 200


@subscription_bp.route("/tenants/<string:tenant_id>", methods=["POST"])
@auth_required
@permission_required("subscription.create")
def assign_subscription(tenant_id: str):
    """
    Assign a subscription plan to a tenant (admin override).
    POST /api/subscriptions/tenants/<tenant_id>
    Body: { "subscription_code": "STARTER", "auto_renew": false }

    [FIX-R-003] Previously called svc.create_subscription() which raised
    ValueError when the tenant already had an active trial, blocking Custom-plan
    manual provisioning.  Now calls svc.admin_assign_subscription() which
    safely deactivates any existing subscription before creating the new one.
    """
    data = request.get_json() or {}

    plan = None
    if data.get("subscription_id"):
        plan = SubscriptionPlan.query.get(int(data["subscription_id"]))
    elif data.get("subscription_code"):
        plan = SubscriptionPlan.query.filter_by(
            subscription_code=data["subscription_code"], is_active=True
        ).first()

    if not plan:
        return jsonify({"error": "Subscription plan not found"}), 404

    try:
        svc          = SubscriptionService()
        subscription = svc.admin_assign_subscription(
            tenant_id         = tenant_id,
            subscription_code = plan.subscription_code,
            auto_renew        = bool(data.get("auto_renew", False)),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(
            "[SUBSCRIPTION] admin_assign_subscription failed for %s: %s", tenant_id, exc
        )
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "message":      "Subscription assigned successfully",
        "subscription": _tenant_sub_dict(subscription),
    }), 201


@subscription_bp.route("/tenants/<string:tenant_id>/cancel", methods=["POST"])
@auth_required
@permission_required("subscription.cancel")
def cancel_tenant_subscription(tenant_id: str):
    """
    Cancel the active subscription for a tenant (admin).
    POST /api/subscriptions/tenants/<tenant_id>/cancel

    [FIX-R-004] Previously used svc.cancel_subscription() which called
    tenant_repo.cancel_subscription() and deactivated immediately.
    Now uses the same period-end semantics as the self-service cancel route.
    """
    svc       = SubscriptionService()
    cancelled = svc.cancel_subscription(tenant_id)

    if not cancelled:
        return jsonify({"error": "No active subscription found for this tenant"}), 404

    # Return the cancel date so the admin UI can display it
    sub = (
        TenantSubscription.query
        .filter_by(tenant_id=tenant_id)
        .order_by(TenantSubscription.created_at.desc())
        .first()
    )

    return jsonify({
        "message":            "Subscription will be cancelled at the end of the current billing period.",
        "cancel_at":          sub.subscription_end_date.isoformat() if sub and sub.subscription_end_date else None,
        "cancel_at_period_end": True,
    }), 200


@subscription_bp.route("/tenants/<string:tenant_id>/renew", methods=["POST"])
@auth_required
@permission_required("subscription.create")
def renew_tenant_subscription(tenant_id: str):
    """
    Manually renew a tenant's subscription for another billing cycle (admin).
    POST /api/subscriptions/tenants/<tenant_id>/renew
    """
    try:
        svc     = SubscriptionService()
        renewed = svc.renew_subscription(tenant_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404

    if not renewed:
        return jsonify({"error": "Could not renew subscription"}), 500

    return jsonify({
        "message":      "Subscription renewed",
        "subscription": _tenant_sub_dict(renewed),
    }), 201


# =============================================================================
# SECTION 5: Subscription → Module Mapping
# =============================================================================

@subscription_bp.route("/plans/<int:subscription_id>/modules", methods=["GET"])
@auth_required
def get_plan_modules(subscription_id: int):
    """GET /api/subscriptions/plans/<subscription_id>/modules"""
    _plan_or_404(subscription_id)
    return jsonify({
        "subscription_id": subscription_id,
        "modules":         _modules_for_plan(subscription_id),
    }), 200


@subscription_bp.route("/plans/<int:subscription_id>/modules/<int:module_id>", methods=["POST"])
@auth_required
@permission_required("subscription.manage_modules")
def add_module_to_plan(subscription_id: int, module_id: int):
    """POST /api/subscriptions/plans/<subscription_id>/modules/<module_id>"""
    _plan_or_404(subscription_id)
    if not ModuleMaster.query.get(module_id):
        return jsonify({"error": "Module not found"}), 404

    if SubscriptionModuleMapping.query.filter_by(
        subscription_id=subscription_id, module_id=module_id
    ).first():
        return jsonify({"error": "Module already included in this plan"}), 409

    mapping = SubscriptionModuleMapping(
        subscription_id=subscription_id, module_id=module_id
    )
    try:
        db.session.add(mapping)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Module already included in this plan"}), 409

    return jsonify({"message": "Module added to plan"}), 201


@subscription_bp.route("/plans/<int:subscription_id>/modules/<int:module_id>", methods=["DELETE"])
@auth_required
@permission_required("subscription.manage_modules")
def remove_module_from_plan(subscription_id: int, module_id: int):
    """DELETE /api/subscriptions/plans/<subscription_id>/modules/<module_id>"""
    mapping = SubscriptionModuleMapping.query.filter_by(
        subscription_id=subscription_id, module_id=module_id
    ).first()
    if not mapping:
        abort(404, description="Module not found in this plan")
    db.session.delete(mapping)
    db.session.commit()
    return jsonify({"message": "Module removed from plan"}), 200


# =============================================================================
# Private helpers
# =============================================================================

def _plan_or_404(subscription_id: int) -> SubscriptionPlan:
    plan = SubscriptionPlan.query.get(subscription_id)
    if not plan:
        abort(404, description="Subscription plan not found")
    return plan


def _modules_for_plan(subscription_id: int) -> list:
    mappings   = SubscriptionModuleMapping.query.filter_by(subscription_id=subscription_id).all()
    module_ids = [m.module_id for m in mappings]
    modules    = (
        ModuleMaster.query.filter(ModuleMaster.module_id.in_(module_ids)).all()
        if module_ids else []
    )
    return [
        {"module_id": m.module_id, "module_code": m.module_code, "module_name": m.module_name}
        for m in modules
    ]


def _plan_dict(p: SubscriptionPlan) -> dict:
    return {
        "subscription_id":   p.subscription_id,
        "subscription_code": p.subscription_code,
        "subscription_name": p.subscription_name,
        "description":       p.description,
        "price":             float(p.price) if p.price is not None else None,
        "currency_id":       p.currency_id,
        "billing_cycle":     p.billing_cycle,
        "is_base_plan":      p.is_base_plan,
        "is_active":         p.is_active,
        "stripe_price_id":   p.stripe_price_id,
        "created_at":        p.created_at.isoformat() if p.created_at else None,
        "updated_at":        p.updated_at.isoformat() if p.updated_at else None,
    }


def _tenant_sub_dict(s: TenantSubscription) -> dict:
    plan = s.subscription
    return {
        "tenant_subscription_mapping_id": s.tenant_subscription_mapping_id,
        "tenant_id":                      s.tenant_id,
        "subscription_id":                s.subscription_id,
        "plan_name":                      plan.subscription_name if plan else None,
        "plan_code":                      plan.subscription_code if plan else None,
        "stripe_price_id":                plan.stripe_price_id if plan else None,
        "subscription_start_date":        s.subscription_start_date.isoformat() if s.subscription_start_date else None,
        "subscription_end_date":          s.subscription_end_date.isoformat() if s.subscription_end_date else None,
        "is_active":                      s.is_active,
        "auto_renew":                     s.auto_renew,
        "status":                         s.status,
        "trial_end_date":                 s.trial_end_date.isoformat() if s.trial_end_date else None,
        "days_remaining_in_trial":        s.days_remaining_in_trial(),
        "stripe_subscription_id":         s.stripe_subscription_id,
        "cancel_at_period_end":           s.cancel_at_period_end,
        "current_period_start":           s.current_period_start.isoformat() if s.current_period_start else None,
        "current_period_end":             s.current_period_end.isoformat() if s.current_period_end else None,
        "created_at":                     s.created_at.isoformat() if s.created_at else None,
        "updated_at":                     s.updated_at.isoformat() if s.updated_at else None,
    }