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
    from services.payment_service import PaymentService

    try:
        result = PaymentService().create_checkout_session(g.tenant_id, plan)
    except ImportError as exc:
        return jsonify({"error": str(exc)}), 500
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        return jsonify({"error": message}), status_code
    except stripe.error.StripeError as exc:
        return jsonify({"error": "Stripe error", "message": str(exc)}), 502

    return jsonify(result), 200


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
        "message": "Subscription will be cancelled at the end of the current billing period.",
        "cancel_at": sub.subscription_end_date.isoformat() if sub.subscription_end_date else None,
        "cancel_at_period_end": True,
    }), 200


# =============================================================================
# SECTION 1B: Subscription Invoices (tenant)
# =============================================================================

@subscription_bp.route("/me/invoices", methods=["GET"])
@auth_required
@require_tenant_owner
def list_my_invoices():
    """
    List tenant's subscription invoices.
    GET /api/subscriptions/me/invoices

    Query params:
    - page: Page number (default: 1)
    - per_page: Items per page (default: 20, max: 100)
    - status: Filter by status (pending, paid, failed, void)
    """
    from services.invoice_service import InvoiceService

    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(1, int(request.args.get("per_page", 20))))
    status = request.args.get("status")

    svc = InvoiceService()
    result = svc.list_invoices(
        tenant_id=g.tenant_id,
        page=page,
        per_page=per_page,
        status=status,
    )
    return jsonify(result), 200


@subscription_bp.route("/me/invoices/<int:invoice_id>", methods=["GET"])
@auth_required
@require_tenant_owner
def get_my_invoice(invoice_id: int):
    """
    Get invoice details.
    GET /api/subscriptions/me/invoices/{invoice_id}

    Returns invoice details including line items if available.
    """
    from services.invoice_service import InvoiceService
    from models import SubscriptionInvoice

    invoice = db.session.get(SubscriptionInvoice, invoice_id)
    if not invoice or invoice.tenant_id != g.tenant_id:
        return jsonify({"error": "Invoice not found"}), 404

    return jsonify(invoice.to_dict()), 200


@subscription_bp.route("/me/invoices/<int:invoice_id>/pdf", methods=["GET"])
@auth_required
@require_tenant_owner
def get_my_invoice_pdf(invoice_id: int):
    """
    Download invoice PDF or generate it on-demand.
    GET /api/subscriptions/me/invoices/{invoice_id}/pdf

    Returns PDF file or generates it if not available.
    """
    import os
    from flask import send_file
    from services.invoice_service import InvoiceService
    from models import SubscriptionInvoice

    invoice = db.session.get(SubscriptionInvoice, invoice_id)
    if not invoice or invoice.tenant_id != g.tenant_id:
        return jsonify({"error": "Invoice not found"}), 404

    svc = InvoiceService()

    if invoice.invoice_pdf_url:
        backend_dir = os.path.dirname(current_app.config.get("UPLOAD_FOLDER", ""))
        pdf_path = os.path.join(backend_dir, invoice.invoice_pdf_url.lstrip("/\\"))
        pdf_path = os.path.normpath(pdf_path)
        if os.path.exists(pdf_path):
            return send_file(
                pdf_path,
                mimetype="application/pdf",
                as_attachment=True,
                download_name=f"invoice_{invoice.invoice_number}.pdf",
            )

    pdf_path = svc.generate_invoice_pdf(invoice_id)
    if pdf_path and os.path.exists(pdf_path):
        return send_file(
            pdf_path,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"invoice_{invoice.invoice_number}.pdf",
        )

    return jsonify({"error": "PDF not available"}), 404


# =============================================================================
# SECTION 1C: Payment Methods (tenant)
# =============================================================================

@subscription_bp.route("/me/payment-methods", methods=["GET"])
@auth_required
@require_tenant_owner
def list_my_payment_methods():
    """
    List stored payment methods for the tenant.
    GET /api/subscriptions/me/payment-methods

    Returns masked card details (brand, last4, expiry).
    """
    from services.payment_service import PaymentService

    svc = PaymentService()
    methods = svc.list_payment_methods(g.tenant_id)
    return jsonify(methods), 200


@subscription_bp.route("/me/payment-methods", methods=["POST"])
@auth_required
@require_tenant_owner
def create_setup_intent():
    """
    Create a Stripe SetupIntent for adding a new payment method.
    POST /api/subscriptions/me/payment-methods

    Returns client_secret for Stripe Elements to collect card details.
    Flow:
    1. Create SetupIntent
    2. Return { client_secret, payment_method_types }
    3. Frontend uses Stripe Elements to collect card
    4. On success, confirm and attach to customer
    """
    from services.payment_service import PaymentService

    svc = PaymentService()
    try:
        result = svc.create_setup_intent(g.tenant_id)
        return jsonify(result), 200
    except ImportError as e:
        return jsonify({"error": str(e)}), 500
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@subscription_bp.route("/me/payment-methods/<payment_method_id>", methods=["DELETE"])
@auth_required
@require_tenant_owner
def remove_payment_method(payment_method_id: str):
    """
    Remove a payment method.
    DELETE /api/subscriptions/me/payment-methods/{payment_method_id}

    Cannot remove if it's the only method on an active subscription.
    """
    from services.payment_service import PaymentService

    svc = PaymentService()

    if not svc.remove_payment_method(g.tenant_id, payment_method_id):
        return jsonify({"error": "Failed to remove payment method"}), 400

    return jsonify({"message": "Payment method removed"}), 200


@subscription_bp.route("/me/payment-methods/<payment_method_id>/default", methods=["POST"])
@auth_required
@require_tenant_owner
def set_default_payment_method(payment_method_id: str):
    """
    Set a payment method as the default for subscriptions.
    POST /api/subscriptions/me/payment-methods/{payment_method_id}/default
    """
    from services.payment_service import PaymentService

    svc = PaymentService()

    if not svc.set_default_payment_method(g.tenant_id, payment_method_id):
        return jsonify({"error": "Failed to set default payment method"}), 400

    return jsonify({"message": "Default payment method updated"}), 200


# =============================================================================
# SECTION 1D: Payment History (tenant)
# =============================================================================

@subscription_bp.route("/me/payment-history", methods=["GET"])
@auth_required
@require_tenant_owner
def get_my_payment_history():
    """
    Get payment attempt history for the tenant.
    GET /api/subscriptions/me/payment-history

    Query params:
    - page: Page number (default: 1)
    - per_page: Items per page (default: 20)
    """
    from services.payment_service import PaymentService

    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(1, int(request.args.get("per_page", 20))))

    svc = PaymentService()
    result = svc.get_payment_history(
        tenant_id=g.tenant_id,
        page=page,
        per_page=per_page,
    )
    return jsonify(result), 200


@subscription_bp.route("/me/payment-summary", methods=["GET"])
@auth_required
@require_tenant_owner
def get_my_payment_summary():
    """
    Get payment summary including payment methods and recent attempts.
    GET /api/subscriptions/me/payment-summary
    """
    from services.payment_service import PaymentService

    svc = PaymentService()
    summary = svc.get_payment_summary(g.tenant_id)
    return jsonify(summary), 200


# =============================================================================
# SECTION 1E: Self-service billing utilities
# =============================================================================

@subscription_bp.route("/me/customer-portal", methods=["POST"])
@auth_required
@require_tenant_owner
def create_customer_portal_session():
    """
    Create a Stripe Billing Portal session for the tenant owner.
    POST /api/subscriptions/me/customer-portal
    """
    from services.payment_service import PaymentService

    data = request.get_json(silent=True) or {}
    return_url = data.get("return_url")

    try:
        result = PaymentService().create_customer_portal_session(
            tenant_id=g.tenant_id,
            return_url=return_url,
        )
    except ImportError as exc:
        return jsonify({"error": str(exc)}), 500
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        if not STRIPE_AVAILABLE or not isinstance(exc, stripe.error.StripeError):
            current_app.logger.error(
                "[STRIPE] Failed to create billing portal session for tenant %s: %s",
                g.tenant_id,
                exc,
            )
            return jsonify({"error": "Unable to create billing portal session"}), 500
        return jsonify({"error": "Stripe error", "message": str(exc)}), 502

    return jsonify(result), 200


@subscription_bp.route("/me/pause", methods=["GET"])
@auth_required
@require_tenant_owner
def get_pause_status():
    """
    Get the current subscription pause state for the tenant.
    GET /api/subscriptions/me/pause
    """
    from services.subscription_management_service import SubscriptionManagementService

    pause = SubscriptionManagementService().get_pause_status(g.tenant_id)
    return jsonify({"pause": pause}), 200


@subscription_bp.route("/me/pause", methods=["POST"])
@auth_required
@require_tenant_owner
def pause_my_subscription():
    """
    Pause an active paid subscription.
    POST /api/subscriptions/me/pause
    """
    from services.subscription_management_service import SubscriptionManagementService

    data = request.get_json(silent=True) or {}
    reason = data.get("reason")
    resume_at_raw = data.get("resume_at")
    resume_at = None
    if resume_at_raw:
        try:
            resume_at = datetime.fromisoformat(str(resume_at_raw).replace("Z", "+00:00"))
        except ValueError:
            return jsonify({"error": "resume_at must be a valid ISO timestamp"}), 400

    svc = SubscriptionManagementService()
    if not svc.pause_subscription(g.tenant_id, reason=reason, resume_date=resume_at):
        return jsonify({
            "error": "Unable to pause subscription",
            "message": "Only active paid subscriptions can be paused once at a time.",
        }), 400

    return jsonify({
        "message": "Subscription paused",
        "pause": svc.get_pause_status(g.tenant_id),
    }), 200


@subscription_bp.route("/me/resume", methods=["POST"])
@auth_required
@require_tenant_owner
def resume_my_subscription():
    """
    Resume a paused subscription.
    POST /api/subscriptions/me/resume
    """
    from services.subscription_management_service import SubscriptionManagementService

    svc = SubscriptionManagementService()
    if not svc.resume_subscription(g.tenant_id):
        return jsonify({"error": "No paused subscription found"}), 404

    return jsonify({"message": "Subscription resumed"}), 200


# =============================================================================
# SECTION 2: Stripe Webhook (no JWT auth)
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
        elif event_type == "invoice.payment_failed":
            _handle_payment_failed(event_data)
        elif event_type == "payment_intent.payment_failed":
            _handle_payment_intent_failed(event_data)
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
    sub.payment_attempts       = 0
    sub.next_retry_date        = None
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

    from services.invoice_service import InvoiceService
    from services.notification_service import NotificationService

    invoice_svc = InvoiceService()
    notification_svc = NotificationService()
    invoice_row = invoice_svc.create_or_update_from_stripe_invoice(
        tenant_id=sub.tenant_id,
        subscription=sub,
        stripe_invoice=invoice,
        status="paid",
    )

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

    paid_at_ts = (invoice.get("status_transitions") or {}).get("paid_at")
    invoice_row.status = "paid"
    invoice_row.paid_at = (
        datetime.utcfromtimestamp(paid_at_ts)
        if paid_at_ts
        else datetime.now(timezone.utc)
    )
    invoice_row.updated_at = datetime.utcnow()

    sub.status = "active"
    sub.is_active = True
    sub.payment_attempts = 0
    sub.next_retry_date = None
    sub.updated_at = datetime.utcnow()

    db.session.commit()

    notification_svc.send_payment_succeeded(
        tenant_id=sub.tenant_id,
        amount=float(invoice_row.total_amount),
        currency=invoice_row.currency.currency_code if invoice_row.currency else "USD",
    )
    notification_svc.send_subscription_renewed(
        tenant_id=sub.tenant_id,
        next_period_end=sub.subscription_end_date.isoformat() if sub.subscription_end_date else None,
    )
    invoice_svc.send_invoice_email(invoice_row.invoice_id)

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


def _handle_payment_failed(invoice):
    """
    invoice.payment_failed → log attempt, mark subscription past_due.

    Called when an automatic payment attempt fails. This triggers dunning
    if max retries haven't been reached.
    """
    stripe_sub_id = invoice.get("subscription")
    if not stripe_sub_id:
        current_app.logger.warning("[STRIPE] invoice.payment_failed — no subscription")
        return

    sub = TenantSubscription.query.filter_by(
        stripe_subscription_id=stripe_sub_id
    ).first()
    if not sub:
        current_app.logger.warning(
            "[STRIPE] invoice.payment_failed — no TenantSubscription for %s",
            stripe_sub_id,
        )
        return

    from services.dunning_service import DunningService
    from services.invoice_service import InvoiceService
    from services.payment_service import PaymentService

    failure_error = (
        invoice.get("last_finalization_error")
        or invoice.get("last_payment_error")
        or {}
    )
    failure_msg = failure_error.get("message", "Payment failed")
    failure_code = failure_error.get("code")

    payment_svc = PaymentService()
    invoice_svc = InvoiceService()
    dunning_svc = DunningService()

    plan = sub.subscription
    currency_id = plan.currency_id if plan else 1
    amount = float(invoice.get("amount_due", 0)) / 100
    invoice_row = invoice_svc.create_or_update_from_stripe_invoice(
        tenant_id=sub.tenant_id,
        subscription=sub,
        stripe_invoice=invoice,
        status="failed",
    )

    payment_svc.log_payment_attempt(
        tenant_id=sub.tenant_id,
        subscription_id=sub.tenant_subscription_mapping_id,
        amount=amount,
        currency_id=currency_id,
        status="failed",
        stripe_payment_intent_id=invoice.get("payment_intent"),
        invoice_id=invoice_row.invoice_id,
        failure_reason=failure_msg,
        failure_code=failure_code,
    )

    payment_svc.update_subscription_payment_status(sub.tenant_id, "past_due")
    dunning_result = dunning_svc.process_payment_failure(
        tenant_id=sub.tenant_id,
        invoice_id=invoice_row.invoice_id,
        failure_reason=failure_msg,
        failure_code=failure_code,
    )

    current_app.logger.warning(
        "[STRIPE] Payment failed for tenant %s (subscription %s): %s; action=%s",
        sub.tenant_id,
        stripe_sub_id,
        failure_msg,
        dunning_result.get("action"),
    )


def _handle_payment_intent_failed(payment_intent):
    """
    payment_intent.payment_failed → log attempt for manual retries.

    Called when a payment intent created for a manual operation fails.
    """
    stripe_pi_id = payment_intent.get("id")
    if not stripe_pi_id:
        return

    tenant_id = (payment_intent.get("metadata") or {}).get("tenant_id")
    if not tenant_id:
        current_app.logger.warning(
            "[STRIPE] payment_intent.payment_failed — no tenant_id in metadata"
        )
        return

    sub = (
        TenantSubscription.query
        .filter_by(tenant_id=tenant_id, is_active=True)
        .order_by(TenantSubscription.created_at.desc())
        .first()
    )
    if not sub:
        current_app.logger.warning(
            "[STRIPE] payment_intent.payment_failed — no active subscription for tenant %s",
            tenant_id,
        )
        return

    failure_msg = payment_intent.get("last_payment_error", {}).get("message", "Payment failed")
    failure_code = payment_intent.get("last_payment_error", {}).get("code")

    from services.dunning_service import DunningService
    from services.notification_service import NotificationService
    from services.payment_service import PaymentService
    payment_svc = PaymentService()
    notification_svc = NotificationService()
    dunning_svc = DunningService()

    plan = sub.subscription
    currency_id = plan.currency_id if plan else 1
    amount = float(payment_intent.get("amount", 0)) / 100
    metadata = payment_intent.get("metadata") or {}
    invoice_id = metadata.get("invoice_id")

    attempt = payment_svc.log_payment_attempt(
        tenant_id=tenant_id,
        subscription_id=sub.tenant_subscription_mapping_id,
        amount=amount,
        currency_id=currency_id,
        status="failed",
        stripe_payment_intent_id=stripe_pi_id,
        invoice_id=int(invoice_id) if invoice_id else None,
        failure_reason=failure_msg,
        failure_code=failure_code,
    )
    payment_svc.update_subscription_payment_status(tenant_id, "past_due")

    if invoice_id:
        dunning_svc.process_payment_failure(
            tenant_id=tenant_id,
            invoice_id=int(invoice_id),
            failure_reason=failure_msg,
            failure_code=failure_code,
        )
    else:
        notification_svc.send_payment_failed(
            tenant_id=tenant_id,
            attempt_number=attempt.attempt_number,
            failure_reason=failure_msg,
        )

    current_app.logger.warning(
        "[STRIPE] Payment intent failed for tenant %s: %s",
        tenant_id,
        failure_msg,
    )


# =============================================================================
# SECTION 3: Subscription Plans — catalogue CRUD (admin)
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
        "message": "Subscription renewed",
        "subscription": _tenant_sub_dict(renewed),
    }), 201


# =============================================================================
# SECTION 4B: Subscription Management (tenant self-service)
# =============================================================================

@subscription_bp.route("/me/downgrade", methods=["POST"])
@auth_required
@require_tenant_owner
def schedule_downgrade():
    """
    Schedule a plan downgrade at period end.
    POST /api/subscriptions/me/downgrade

    Body: { "plan_code": "STARTER" }
    Response: { "scheduled_for": "2024-02-01", "current_plan": "PRO", "new_plan": "STARTER" }
    """
    data = request.get_json() or {}
    new_plan_code = (data.get("plan_code") or "").strip().upper()

    if not new_plan_code:
        return jsonify({"error": "plan_code is required"}), 400

    from services.subscription_management_service import SubscriptionManagementService

    try:
        result = SubscriptionManagementService().schedule_downgrade(
            tenant_id=g.tenant_id,
            new_plan_code=new_plan_code,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        return jsonify({"error": message}), status_code

    return jsonify(result), 200


@subscription_bp.route("/me/pending-changes", methods=["GET"])
@auth_required
@require_tenant_owner
def get_pending_changes():
    """
    Get pending plan changes for the tenant.
    GET /api/subscriptions/me/pending-changes

    Returns pending downgrade info or null if none scheduled.
    """
    from services.subscription_management_service import SubscriptionManagementService

    pending = SubscriptionManagementService().get_pending_change(g.tenant_id)
    return jsonify({"pending_change": pending}), 200


@subscription_bp.route("/me/pending-changes", methods=["DELETE"])
@auth_required
@require_tenant_owner
def cancel_pending_downgrade():
    """
    Cancel pending downgrade.
    DELETE /api/subscriptions/me/pending-changes
    """
    from services.subscription_management_service import SubscriptionManagementService

    if not SubscriptionManagementService().cancel_downgrade(g.tenant_id):
        return jsonify({"error": "No pending change found"}), 404

    return jsonify({"message": "Pending change cancelled"}), 200


# =============================================================================
# SECTION 4C: Notification Preferences (tenant)
# =============================================================================

@subscription_bp.route("/me/notification-preferences", methods=["GET"])
@auth_required
@require_tenant_owner
def get_notification_preferences():
    """
    Get notification preferences for the tenant.
    GET /api/subscriptions/me/notification-preferences

    Returns per-type preferences (trial_expiring, payment_failed, etc.)
    """
    from services.notification_service import NotificationService

    prefs = NotificationService().get_preferences(g.tenant_id)
    return jsonify(prefs), 200


@subscription_bp.route("/me/notification-preferences", methods=["PUT"])
@auth_required
@require_tenant_owner
def update_notification_preferences():
    """
    Update notification preferences.
    PUT /api/subscriptions/me/notification-preferences

    Body: {
        "preferences": [
            { "notification_type": "trial_expiring", "email_enabled": true, "in_app_enabled": true }
        ]
    }
    """
    data = request.get_json() or {}
    preferences = data.get("preferences", [])

    if not isinstance(preferences, list):
        return jsonify({"error": "preferences must be a list"}), 400

    from services.notification_service import NotificationService

    NotificationService().update_preferences(g.tenant_id, preferences)
    return jsonify({"message": "Preferences updated"}), 200


@subscription_bp.route("/me/notification-history", methods=["GET"])
@auth_required
@require_tenant_owner
def get_notification_history():
    """
    Get recent notification history for the tenant owner.
    """
    from services.notification_service import NotificationService

    limit = min(100, max(1, int(request.args.get("limit", 50))))
    history = NotificationService().get_notification_history(g.tenant_id, limit=limit)
    return jsonify({"items": history, "total": len(history)}), 200


# =============================================================================
# SECTION 4D: Dunning & Payment History (admin)
# =============================================================================

@subscription_bp.route("/tenants", methods=["GET"])
@auth_required
@permission_required("subscription.view")
def list_tenant_subscriptions():
    """
    Admin list of tenant subscriptions with basic search and status filters.
    GET /api/subscriptions/tenants
    """
    from sqlalchemy import or_

    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(1, int(request.args.get("per_page", 20))))
    search = (request.args.get("search") or "").strip()
    status = (request.args.get("status") or "").strip().lower()

    query = (
        db.session.query(TenantSubscription)
        .join(TenantMaster, TenantMaster.tenant_id == TenantSubscription.tenant_id)
        .outerjoin(
            SubscriptionPlan,
            SubscriptionPlan.subscription_id == TenantSubscription.subscription_id,
        )
        .order_by(TenantSubscription.created_at.desc())
    )

    if status:
        query = query.filter(TenantSubscription.status == status)

    if search:
        like_term = f"%{search}%"
        query = query.filter(
            or_(
                TenantSubscription.tenant_id.ilike(like_term),
                TenantMaster.tenant_company_name.ilike(like_term),
                SubscriptionPlan.subscription_name.ilike(like_term),
                SubscriptionPlan.subscription_code.ilike(like_term),
            )
        )

    total = query.count()
    rows = query.offset((page - 1) * per_page).limit(per_page).all()

    return jsonify({
        "items": [_tenant_sub_dict(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if per_page else 0,
    }), 200

@subscription_bp.route("/tenants/<string:tenant_id>/payment-history", methods=["GET"])
@auth_required
@permission_required("subscription.view")
def get_tenant_payment_history(tenant_id: str):
    """
    Admin view of payment attempts for a tenant.
    GET /api/subscriptions/tenants/<tenant_id>/payment-history

    Query params: page, per_page
    """
    from services.payment_service import PaymentService

    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(1, int(request.args.get("per_page", 20))))

    svc = PaymentService()
    result = svc.get_payment_history(
        tenant_id=tenant_id,
        page=page,
        per_page=per_page,
    )
    return jsonify(result), 200


@subscription_bp.route("/tenants/<string:tenant_id>/retry-payment", methods=["POST"])
@auth_required
@permission_required("subscription.create")
def retry_payment_for_tenant(tenant_id: str):
    """
    Manually trigger payment retry for a tenant (admin).
    POST /api/subscriptions/tenants/<tenant_id>/retry-payment

    Body: { "invoice_id": 123 }
    """
    from services.payment_service import PaymentService

    data = request.get_json() or {}
    invoice_id = data.get("invoice_id")

    if not invoice_id:
        return jsonify({"error": "invoice_id is required"}), 400

    svc = PaymentService()
    try:
        result = svc.retry_payment(tenant_id, invoice_id)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"[ADMIN] retry_payment failed for tenant {tenant_id}: {e}")
        return jsonify({"error": "Payment retry failed"}), 500


# =============================================================================
# SECTION 4E: Dunning Config (admin)
# =============================================================================

@subscription_bp.route("/config/dunning", methods=["GET"])
@auth_required
@permission_required("subscription.config")
def get_dunning_config():
    """
    Get dunning configuration.
    GET /api/subscriptions/config/dunning

    Returns retry schedule, max retries, grace period per plan.
    """
    from models import DunningConfig
    from services.dunning_service import DunningService

    configs = DunningConfig.query.order_by(DunningConfig.plan_id.asc().nullsfirst()).all()
    if configs:
        return jsonify([c.to_dict() for c in configs]), 200

    return jsonify([DunningService().get_dunning_config()]), 200


@subscription_bp.route("/config/dunning", methods=["PUT"])
@auth_required
@permission_required("subscription.config")
def update_dunning_config():
    """
    Update dunning configuration.
    PUT /api/subscriptions/config/dunning

    Body: {
        "plan_id": 1,
        "retry_schedule": [3, 7],
        "max_retries": 3,
        "grace_period_days": 0
    }
    """
    data = request.get_json() or {}
    from services.dunning_service import DunningService

    config = DunningService().update_dunning_config(
        plan_id=data.get("plan_id"),
        retry_schedule=data.get("retry_schedule", [3, 7]),
        max_retries=int(data.get("max_retries", 3)),
        grace_period_days=int(data.get("grace_period_days", 0)),
    )
    return jsonify({"message": "Dunning config updated", "config": config.to_dict()}), 200


# =============================================================================
# SECTION 5: Subscription → Module Mapping
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
