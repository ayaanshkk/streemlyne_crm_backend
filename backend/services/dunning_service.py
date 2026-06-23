"""
Dunning Service
Handles payment retry scheduling and dunning process.

Part of the Subscription Module Implementation Plan - Phase 2 (MEDIUM PRIORITY)
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone, date
from typing import Optional, List, Dict

from flask import current_app

from database import db
from models import (
    TenantSubscription,
    SubscriptionPlan,
)


class DunningService:
    """Service for dunning (payment retry) business logic."""

    DEFAULT_RETRY_SCHEDULE = [3, 7]
    DEFAULT_MAX_RETRIES = 3

    def __init__(self):
        pass

    def get_dunning_config(self, plan_id: Optional[int] = None) -> Dict:
        """
        Get dunning configuration for a plan or default configuration.

        Args:
            plan_id: Optional plan ID to get plan-specific config

        Returns:
            Dict with retry_schedule, max_retries, grace_period_days
        """
        return {
            "retry_schedule": self.DEFAULT_RETRY_SCHEDULE,
            "max_retries": self.DEFAULT_MAX_RETRIES,
            "grace_period_days": 0,
        }

    def get_retry_date(
        self,
        tenant_id: str,
        subscription_id: int,
        attempt_number: int,
        plan_id: Optional[int] = None,
    ) -> datetime:
        """
        Calculate the next retry date based on dunning config and retry schedule.

        Args:
            tenant_id: The tenant's unique identifier
            subscription_id: The subscription mapping ID
            attempt_number: The current attempt number (1-based)

        Returns:
            datetime for when the next retry should occur
        """
        config = self.get_dunning_config(plan_id)

        retry_schedule = config.get("retry_schedule", self.DEFAULT_RETRY_SCHEDULE)
        if not retry_schedule or len(retry_schedule) == 0:
            retry_schedule = self.DEFAULT_RETRY_SCHEDULE

        schedule_index = min(attempt_number - 1, len(retry_schedule) - 1)
        days_until_retry = retry_schedule[schedule_index]

        now = datetime.now(timezone.utc)
        return now + timedelta(days=days_until_retry)

    def schedule_retry(
        self,
        tenant_id: str,
        invoice_id: int,
        attempt_number: int,
    ) -> Dict:
        """
        Schedule a payment retry for a failed invoice.

        Args:
            tenant_id: The tenant's unique identifier
            invoice_id: The subscription invoice ID
            attempt_number: The current attempt number

        Returns:
            Dict with retry details including scheduled datetime
        """
        sub = (
            TenantSubscription.query
            .filter_by(tenant_id=tenant_id, is_active=True)
            .order_by(TenantSubscription.created_at.desc())
            .first()
        )
        if not sub:
            raise ValueError("No active subscription found")

        config = self.get_dunning_config(sub.subscription_id)
        max_retries = config.get("max_retries", self.DEFAULT_MAX_RETRIES)
        grace_period_days = config.get("grace_period_days", 0) or 0

        if attempt_number >= max_retries:
            if grace_period_days > 0:
                expiry_at = datetime.now(timezone.utc) + timedelta(days=grace_period_days)
                return {
                    "scheduled": False,
                    "reason": "Max retries reached; grace period active",
                    "should_expire": False,
                    "grace_period_ends_at": expiry_at.isoformat(),
                }
            return {
                "scheduled": False,
                "reason": "Max retries reached",
                "should_expire": True,
            }

        retry_date = self.get_retry_date(
            tenant_id,
            sub.tenant_subscription_mapping_id,
            attempt_number,
            plan_id=sub.subscription_id,
        )

        return {
            "scheduled": True,
            "retry_date": retry_date.isoformat(),
            "attempt_number": attempt_number,
            "max_retries": max_retries,
        }

    def cancel_scheduled_retries(self, tenant_id: str) -> bool:
        """
        Cancel all scheduled retries for a tenant.

        Args:
            tenant_id: The tenant's unique identifier

        Returns:
            True if successful
        """
        sub = (
            TenantSubscription.query
            .filter_by(tenant_id=tenant_id, is_active=True)
            .order_by(TenantSubscription.created_at.desc())
            .first()
        )
        if not sub:
            return False

        return True

    def process_payment_failure(
        self,
        tenant_id: str,
        invoice_id: int,
        failure_reason: Optional[str] = None,
        failure_code: Optional[str] = None,
    ) -> Dict:
        """
        Process a payment failure and determine next steps.

        Args:
            tenant_id: The tenant's unique identifier
            invoice_id: The subscription invoice ID
            failure_reason: Human-readable failure reason
            failure_code: Stripe failure code

        Returns:
            Dict with action to take (retry, expire, etc.)
        """
        raise NotImplementedError(
            "Dunning is not implemented until Payment_Attempt and Dunning_Config "
            "exist in Supabase."
        )


    def _trigger_expiration_flow(self, tenant_id: str) -> None:
        """
        Trigger the subscription expiration flow.

        Called when max retries are exceeded.

        Args:
            tenant_id: The tenant's unique identifier
        """
        from services.subscription_service import SubscriptionService

        sub = (
            TenantSubscription.query
            .filter_by(tenant_id=tenant_id, is_active=True)
            .order_by(TenantSubscription.created_at.desc())
            .first()
        )
        if not sub:
            return

        sub.status = "expired"
        sub.is_active = False
        sub.auto_renew = False
        sub.updated_at = datetime.utcnow()

        SubscriptionService._reconcile_tenant_modules(tenant_id, subscription_id=None)

        db.session.commit()

        current_app.logger.warning(
            f"[DUNNING] Tenant {tenant_id} subscription expired due to payment failure"
        )

    def check_and_process_expirations(self) -> List[str]:
        """
        Check for subscriptions that should be expired and process them.

        This is called by a scheduled job.

        Returns:
            List of tenant IDs that were expired
        """
        return []

    def process_scheduled_retries(self) -> List[Dict]:
        """
        Retry payment for all past-due subscriptions whose retry window is due.
        """
        return []

    def send_renewal_reminders(self) -> List[str]:
        """
        Send subscription and trial reminders for tenants nearing renewal/expiry.
        """
        from services.notification_service import NotificationService

        today = date.today()
        notified: List[str] = []
        notification_svc = NotificationService()

        subs = (
            TenantSubscription.query
            .filter(TenantSubscription.is_active == True)
            .all()
        )

        for sub in subs:
            if sub.status == "trialing" and sub.trial_end_date:
                days_remaining = (sub.trial_end_date.date() - today).days
                if days_remaining in (1, 3):
                    notification_svc.send_trial_expiring(sub.tenant_id, days_remaining)
                    notified.append(sub.tenant_id)
                continue

            if sub.status != "active" or not sub.subscription_end_date:
                continue

            days_until_renewal = (sub.subscription_end_date - today).days
            if days_until_renewal in (1, 3):
                notification_svc.send_renewal_reminder(
                    sub.tenant_id,
                    days_until_renewal=days_until_renewal,
                    renewal_date=sub.subscription_end_date.isoformat(),
                )
                notified.append(sub.tenant_id)

        return notified

    def update_dunning_config(
        self,
        plan_id: Optional[int],
        retry_schedule: List[int],
        max_retries: int,
        grace_period_days: int = 0,
    ) -> Dict:
        """
        Create or update dunning configuration.

        Args:
            plan_id: Plan ID (None for default config)
            retry_schedule: List of days until each retry
            max_retries: Maximum number of retry attempts
            grace_period_days: Additional days after max retries

        Returns:
            The created or updated DunningConfig
        """
        raise NotImplementedError(
            "Dunning configuration is not implemented until Dunning_Config "
            "exists in Supabase."
        )

    def get_payment_attempt_summary(self, tenant_id: str) -> Dict:
        """
        Get a summary of payment attempts for a tenant.

        Args:
            tenant_id: The tenant's unique identifier

        Returns:
            Dict with attempt counts and totals
        """
        raise NotImplementedError(
            "Payment attempt summaries are not implemented until Payment_Attempt "
            "exists in Supabase."
        )
