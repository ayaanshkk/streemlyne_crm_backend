"""
Payment Service
Handles payment processing, retry logic, and payment method management.

Part of the Subscription Module Implementation Plan - Phase 1 (HIGH PRIORITY)
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, date
from typing import Optional, List, Dict

from flask import current_app

from database import db
from models import (
    PaymentAttempt,
    TenantSubscription,
    TenantMaster,
    SubscriptionPlan,
    CurrencyMaster,
    SubscriptionInvoice,
)


class PaymentService:
    """Service for payment processing business logic."""

    def __init__(self):
        pass

    def create_checkout_session(self, tenant_id: str, plan: SubscriptionPlan) -> Dict:
        """
        Create a Stripe Checkout session for a paid subscription plan.

        Returns:
            Dict with the hosted checkout URL.
        """
        try:
            import stripe
        except ImportError:
            raise ImportError("stripe package not installed. Run: pip install stripe")

        if not plan.stripe_price_id:
            raise ValueError(
                f"Plan '{plan.subscription_code}' is not configured for Stripe checkout"
            )

        stripe_key = (
            current_app.config.get("STRIPE_SECRET_KEY")
            or os.environ.get("STRIPE_SECRET_KEY")
        )
        if not stripe_key:
            raise ValueError("STRIPE_SECRET_KEY is not configured")

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

        tenant = db.session.get(TenantMaster, tenant_id)
        if not tenant:
            raise ValueError(f"Tenant {tenant_id} not found")

        if tenant.stripe_customer_id:
            customer_id = tenant.stripe_customer_id
        else:
            customer = stripe.Customer.create(
                name=tenant.tenant_company_name,
                metadata={"tenant_id": tenant_id},
            )
            customer_id = customer.id
            tenant.stripe_customer_id = customer_id
            db.session.commit()

        try:
            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card"],
                line_items=[{"price": plan.stripe_price_id, "quantity": 1}],
                mode="subscription",
                success_url=success_url,
                cancel_url=cancel_url,
                client_reference_id=tenant_id,
                metadata={
                    "tenant_id": tenant_id,
                    "plan_code": plan.subscription_code,
                },
                idempotency_key=f"checkout:{tenant_id}:{plan.subscription_id}",
            )
        except stripe.error.StripeError as exc:
            current_app.logger.error(
                "[PAYMENT] Checkout session error for tenant %s: %s",
                tenant_id,
                exc,
            )
            raise

        return {"checkout_url": session.url}

    def log_payment_attempt(
        self,
        tenant_id: str,
        subscription_id: int,
        amount: float,
        currency_id: int,
        status: str,
        stripe_payment_intent_id: Optional[str] = None,
        invoice_id: Optional[int] = None,
        failure_reason: Optional[str] = None,
        failure_code: Optional[str] = None,
    ) -> PaymentAttempt:
        """
        Log a payment attempt for tracking and retry logic.

        Args:
            tenant_id: The tenant's unique identifier
            subscription_id: The subscription mapping ID
            amount: Payment amount
            currency_id: Currency ID
            status: 'succeeded', 'failed', 'pending', 'processing'
            stripe_payment_intent_id: Stripe payment intent ID if applicable
            invoice_id: Associated invoice ID if applicable
            failure_reason: Human-readable failure reason
            failure_code: Stripe failure code

        Returns:
            The created PaymentAttempt record
        """
        existing_attempts = (
            db.session.query(PaymentAttempt)
            .filter_by(
                tenant_id=tenant_id,
                subscription_id=subscription_id,
                stripe_payment_intent_id=stripe_payment_intent_id,
            )
            .count()
        )

        attempt = PaymentAttempt(
            tenant_id=tenant_id,
            subscription_id=subscription_id,
            stripe_payment_intent_id=stripe_payment_intent_id,
            invoice_id=invoice_id,
            attempt_number=existing_attempts + 1,
            amount=amount,
            currency_id=currency_id,
            status=status,
            failure_reason=failure_reason,
            failure_code=failure_code,
        )

        db.session.add(attempt)
        db.session.commit()

        return attempt

    def get_payment_history(
        self,
        tenant_id: str,
        page: int = 1,
        per_page: int = 20,
    ) -> Dict:
        """
        Get payment attempt history for a tenant.

        Returns:
            Dict with 'items', 'total', 'page', 'per_page', 'pages'
        """
        query = (
            db.session.query(PaymentAttempt)
            .filter_by(tenant_id=tenant_id)
            .order_by(PaymentAttempt.created_at.desc())
        )

        total = query.count()
        attempts = query.offset((page - 1) * per_page).limit(per_page).all()

        return {
            "items": [att.to_dict() for att in attempts],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page if per_page > 0 else 0,
        }

    def get_recent_attempts(
        self,
        tenant_id: str,
        limit: int = 5,
    ) -> List[PaymentAttempt]:
        """Get the most recent payment attempts for a tenant."""
        return (
            db.session.query(PaymentAttempt)
            .filter_by(tenant_id=tenant_id)
            .order_by(PaymentAttempt.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_failed_attempts_count(self, tenant_id: str, subscription_id: int) -> int:
        """Get the count of failed attempts for a subscription."""
        return (
            db.session.query(PaymentAttempt)
            .filter_by(
                tenant_id=tenant_id,
                subscription_id=subscription_id,
                status="failed",
            )
            .count()
        )

    def create_setup_intent(self, tenant_id: str) -> Dict:
        """
        Create a Stripe SetupIntent for adding/updating payment methods.

        Returns:
            Dict with client_secret and payment_method_types
        """
        try:
            import stripe
        except ImportError:
            raise ImportError("stripe package not installed. Run: pip install stripe")

        stripe_key = current_app.config.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY")
        if not stripe_key:
            raise ValueError("STRIPE_SECRET_KEY is not configured")

        stripe.api_key = stripe_key

        tenant = db.session.get(TenantMaster, tenant_id)
        if not tenant:
            raise ValueError(f"Tenant {tenant_id} not found")

        customer_id = None
        if tenant.stripe_customer_id:
            customer_id = tenant.stripe_customer_id
        else:
            customer = stripe.Customer.create(
                name=tenant.tenant_company_name,
                metadata={"tenant_id": tenant_id},
            )
            customer_id = customer.id
            tenant.stripe_customer_id = customer_id
            db.session.commit()

        try:
            setup_intent = stripe.SetupIntent.create(
                customer=customer_id,
                payment_method_types=["card"],
                metadata={"tenant_id": tenant_id},
                idempotency_key=f"setup-intent:{tenant_id}",
            )
        except stripe.error.StripeError as e:
            current_app.logger.error(f"[PAYMENT] SetupIntent error for tenant {tenant_id}: {e}")
            raise

        return {
            "client_secret": setup_intent.client_secret,
            "setup_intent_id": setup_intent.id,
            "payment_method_types": ["card"],
        }

    def create_customer_portal_session(
        self,
        tenant_id: str,
        return_url: Optional[str] = None,
    ) -> Dict:
        """
        Create a Stripe Billing Portal session for a tenant.
        """
        try:
            import stripe
        except ImportError:
            raise ImportError("stripe package not installed. Run: pip install stripe")

        stripe_key = current_app.config.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY")
        if not stripe_key:
            raise ValueError("STRIPE_SECRET_KEY is not configured")

        stripe.api_key = stripe_key

        tenant = db.session.get(TenantMaster, tenant_id)
        if not tenant or not tenant.stripe_customer_id:
            raise ValueError("Stripe customer not configured for tenant")

        default_return_url = (
            current_app.config.get("STRIPE_PORTAL_RETURN_URL")
            or os.environ.get("STRIPE_PORTAL_RETURN_URL")
            or "http://localhost:3000/subscription/manage"
        )

        session = stripe.billing_portal.Session.create(
            customer=tenant.stripe_customer_id,
            return_url=return_url or default_return_url,
        )
        return {"portal_url": session.url}

    def list_payment_methods(self, tenant_id: str) -> List[Dict]:
        """
        List stored payment methods for a tenant.

        Returns:
            List of payment method dicts with masked card details
        """
        try:
            import stripe
        except ImportError:
            return []

        stripe_key = current_app.config.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY")
        if not stripe_key:
            return []

        stripe.api_key = stripe_key

        tenant = db.session.get(TenantMaster, tenant_id)
        if not tenant or not tenant.stripe_customer_id:
            return []

        try:
            customer = stripe.Customer.retrieve(tenant.stripe_customer_id)
            payment_methods = stripe.PaymentMethod.list(
                customer=customer.id,
                type="card",
            )

            return [
                {
                    "id": pm.id,
                    "brand": pm.card.brand,
                    "last4": pm.card.last4,
                    "exp_month": pm.card.exp_month,
                    "exp_year": pm.card.exp_year,
                    "is_default": pm.id == customer.invoice_settings.default_payment_method,
                }
                for pm in payment_methods.data
            ]
        except stripe.error.StripeError as e:
            current_app.logger.error(f"[PAYMENT] List payment methods error for tenant {tenant_id}: {e}")
            return []

    def remove_payment_method(self, tenant_id: str, payment_method_id: str) -> bool:
        """
        Remove a payment method from a customer.

        Returns True if successful, False otherwise.
        """
        try:
            import stripe
        except ImportError:
            return False

        stripe_key = current_app.config.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY")
        if not stripe_key:
            return False

        stripe.api_key = stripe_key

        tenant = db.session.get(TenantMaster, tenant_id)
        if not tenant or not tenant.stripe_customer_id:
            return False

        active_subscription = (
            db.session.query(TenantSubscription)
            .filter_by(tenant_id=tenant_id, is_active=True)
            .order_by(TenantSubscription.created_at.desc())
            .first()
        )
        payment_methods = self.list_payment_methods(tenant_id)
        if active_subscription and len(payment_methods) <= 1:
            current_app.logger.warning(
                "[PAYMENT] Refusing to remove last payment method for tenant %s with active subscription",
                tenant_id,
            )
            return False

        try:
            stripe.Customer.modify(
                tenant.stripe_customer_id,
                invoice_settings={
                    "default_payment_method": None,
                },
            )

            stripe.PaymentMethod.detach(payment_method_id)
            return True
        except stripe.error.StripeError as e:
            current_app.logger.error(f"[PAYMENT] Remove payment method error for tenant {tenant_id}: {e}")
            return False

    def set_default_payment_method(self, tenant_id: str, payment_method_id: str) -> bool:
        """
        Set a payment method as the default for subscriptions.

        Returns True if successful, False otherwise.
        """
        try:
            import stripe
        except ImportError:
            return False

        stripe_key = current_app.config.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY")
        if not stripe_key:
            return False

        stripe.api_key = stripe_key

        tenant = db.session.get(TenantMaster, tenant_id)
        if not tenant or not tenant.stripe_customer_id:
            return False

        try:
            stripe.Customer.modify(
                tenant.stripe_customer_id,
                invoice_settings={
                    "default_payment_method": payment_method_id,
                },
            )
            return True
        except stripe.error.StripeError as e:
            current_app.logger.error(f"[PAYMENT] Set default payment method error for tenant {tenant_id}: {e}")
            return False

    def retry_payment(
        self,
        tenant_id: str,
        invoice_id: int,
    ) -> Dict:
        """
        Manually retry a failed payment for an invoice.

        Returns:
            Dict with success status and payment intent details or error
        """
        try:
            import stripe
        except ImportError:
            raise ImportError("stripe package not installed. Run: pip install stripe")

        invoice = db.session.get(SubscriptionInvoice, invoice_id)
        if not invoice:
            raise ValueError(f"Invoice {invoice_id} not found")

        if invoice.tenant_id != tenant_id:
            raise ValueError("Invoice does not belong to this tenant")

        if invoice.status == "paid":
            raise ValueError("Invoice is already paid")

        subscription = (
            db.session.query(TenantSubscription)
            .filter_by(tenant_subscription_mapping_id=invoice.subscription_id)
            .first()
        )
        if not subscription or not subscription.stripe_subscription_id:
            raise ValueError("No Stripe subscription found for this invoice")

        stripe_key = current_app.config.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY")
        if not stripe_key:
            raise ValueError("STRIPE_SECRET_KEY is not configured")

        stripe.api_key = stripe_key

        try:
            if invoice.stripe_invoice_id:
                invoice_stripe = stripe.Invoice.pay(invoice.stripe_invoice_id)
            else:
                upcoming = stripe.Invoice.upcoming(
                    subscription=subscription.stripe_subscription_id,
                )
                invoice_data = stripe.Invoice.create(
                    customer=upcoming.get("customer"),
                    auto_advance=True,
                    collection_method="charge_automatically",
                )
                invoice_stripe = stripe.Invoice.finalize_invoice(invoice_data.id)
                stripe.Invoice.pay(invoice_stripe.id)

            attempt = self.log_payment_attempt(
                tenant_id=tenant_id,
                subscription_id=subscription.tenant_subscription_mapping_id,
                amount=float(invoice.total_amount),
                currency_id=invoice.currency_id,
                status="succeeded",
                invoice_id=invoice_id,
            )

            invoice.status = "paid"
            invoice.paid_at = datetime.now(timezone.utc)
            invoice.stripe_invoice_id = invoice_stripe.id
            invoice.updated_at = datetime.utcnow()
            db.session.commit()

            self.update_subscription_payment_status(tenant_id, "active")

            from services.dunning_service import DunningService
            from services.invoice_service import InvoiceService
            from services.notification_service import NotificationService

            DunningService().cancel_scheduled_retries(tenant_id)
            NotificationService().send_payment_succeeded(
                tenant_id=tenant_id,
                amount=float(invoice.total_amount),
                currency=invoice.currency.currency_code if invoice.currency else "USD",
            )
            InvoiceService().send_invoice_email(invoice.invoice_id)

            return {
                "success": True,
                "invoice_id": invoice_id,
                "stripe_invoice_id": invoice_stripe.id,
                "payment_attempt_id": attempt.payment_attempt_id,
            }

        except stripe.error.CardError as e:
            current_app.logger.warning(f"[PAYMENT] Card error during retry for invoice {invoice_id}: {e}")

            attempt = self.log_payment_attempt(
                tenant_id=tenant_id,
                subscription_id=subscription.tenant_subscription_mapping_id,
                amount=float(invoice.total_amount),
                currency_id=invoice.currency_id,
                status="failed",
                invoice_id=invoice_id,
                failure_reason=e.user_message if hasattr(e, "user_message") else str(e),
                failure_code=e.code if hasattr(e, "code") else None,
            )

            invoice.status = "failed"
            invoice.updated_at = datetime.utcnow()
            db.session.commit()

            self.update_subscription_payment_status(tenant_id, "past_due")

            from services.dunning_service import DunningService
            from services.notification_service import NotificationService

            DunningService().schedule_retry(tenant_id, invoice_id, attempt.attempt_number)
            NotificationService().send_payment_failed(
                tenant_id=tenant_id,
                attempt_number=attempt.attempt_number,
                failure_reason=e.user_message if hasattr(e, "user_message") else str(e),
            )

            return {
                "success": False,
                "invoice_id": invoice_id,
                "error": str(e),
                "failure_code": e.code if hasattr(e, "code") else None,
                "payment_attempt_id": attempt.payment_attempt_id,
            }

        except stripe.error.StripeError as e:
            current_app.logger.error(f"[PAYMENT] Stripe error during retry for invoice {invoice_id}: {e}")
            raise

    def update_subscription_payment_status(self, tenant_id: str, status: str) -> Optional[TenantSubscription]:
        """
        Update the payment status on the tenant's subscription.

        Args:
            tenant_id: The tenant's unique identifier
            status: 'active', 'past_due', 'canceled'

        Returns:
            The updated TenantSubscription or None
        """
        subscription = (
            db.session.query(TenantSubscription)
            .filter_by(tenant_id=tenant_id, is_active=True)
            .order_by(TenantSubscription.created_at.desc())
            .first()
        )

        if not subscription:
            return None

        subscription.status = status
        subscription.is_active = status not in {"expired", "canceled"}
        if status == "active":
            subscription.payment_attempts = 0
            subscription.next_retry_date = None
        subscription.updated_at = datetime.utcnow()
        db.session.commit()

        return subscription

    def get_payment_summary(self, tenant_id: str) -> Dict:
        """
        Get a summary of payment status for a tenant.

        Returns:
            Dict with payment method info, recent attempts, and subscription status
        """
        payment_methods = self.list_payment_methods(tenant_id)

        recent_attempts = self.get_recent_attempts(tenant_id, limit=5)

        subscription = (
            db.session.query(TenantSubscription)
            .filter_by(tenant_id=tenant_id, is_active=True)
            .order_by(TenantSubscription.created_at.desc())
            .first()
        )

        failed_count = 0
        if subscription:
            failed_count = self.get_failed_attempts_count(
                tenant_id,
                subscription.tenant_subscription_mapping_id,
            )

        plan = subscription.subscription if subscription else None
        next_billing_date = None
        if subscription:
            if subscription.current_period_end:
                next_billing_date = subscription.current_period_end.isoformat()
            elif subscription.subscription_end_date:
                next_billing_date = subscription.subscription_end_date.isoformat()

        return {
            "has_payment_method": len(payment_methods) > 0,
            "payment_methods": payment_methods,
            "default_payment_method": next(
                (pm for pm in payment_methods if pm.get("is_default")),
                payment_methods[0] if payment_methods else None,
            ),
            "recent_attempts": [att.to_dict() for att in recent_attempts],
            "failed_attempts_count": failed_count,
            "subscription_status": subscription.status if subscription else None,
            "is_past_due": subscription.status == "past_due" if subscription else False,
            "next_retry_date": subscription.next_retry_date.isoformat() if subscription and subscription.next_retry_date else None,
            "next_billing_date": next_billing_date,
            "next_billing_amount": float(plan.price) if plan and plan.price is not None else None,
            "currency_code": plan.currency.currency_code if plan and plan.currency else None,
            "plan_name": plan.subscription_name if plan else None,
            "plan_code": plan.subscription_code if plan else None,
        }
