from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from flask import current_app

from database import db
from models import PendingPlanChange, SubscriptionPause, SubscriptionPlan, TenantSubscription
from services.subscription_service import SubscriptionService


class SubscriptionManagementService:
    """Self-service subscription changes beyond initial checkout/cancel."""

    def _get_active_subscription(self, tenant_id: str) -> Optional[TenantSubscription]:
        return (
            TenantSubscription.query
            .filter_by(tenant_id=tenant_id, is_active=True)
            .order_by(TenantSubscription.created_at.desc())
            .first()
        )

    def _get_active_pause(self, tenant_id: str) -> Optional[SubscriptionPause]:
        return (
            SubscriptionPause.query
            .join(
                TenantSubscription,
                TenantSubscription.tenant_subscription_mapping_id == SubscriptionPause.tenant_subscription_mapping_id,
            )
            .filter(
                TenantSubscription.tenant_id == tenant_id,
                SubscriptionPause.is_active == True,
            )
            .order_by(SubscriptionPause.paused_at.desc())
            .first()
        )

    def schedule_downgrade(self, tenant_id: str, new_plan_code: str) -> Dict:
        sub = self._get_active_subscription(tenant_id)
        if not sub:
            raise ValueError("No active subscription found")

        current_plan = sub.subscription
        if not current_plan:
            raise ValueError("Current subscription has no plan")

        new_plan = SubscriptionPlan.query.filter_by(
            subscription_code=new_plan_code,
            is_active=True,
        ).first()
        if not new_plan:
            raise ValueError(f"Plan '{new_plan_code}' not found or inactive")
        if current_plan.subscription_code == new_plan.subscription_code:
            raise ValueError("Already on this plan")

        scheduled_for = (
            sub.subscription_end_date
            or (sub.current_period_end.date() if sub.current_period_end else None)
            or date.today()
        )

        pending = PendingPlanChange.query.filter_by(tenant_id=tenant_id).first()
        if pending:
            pending.current_plan_id = current_plan.subscription_id
            pending.new_plan_id = new_plan.subscription_id
            pending.scheduled_for = scheduled_for
            pending.updated_at = datetime.utcnow()
        else:
            pending = PendingPlanChange(
                tenant_id=tenant_id,
                current_plan_id=current_plan.subscription_id,
                new_plan_id=new_plan.subscription_id,
                scheduled_for=scheduled_for,
            )
            db.session.add(pending)

        db.session.commit()
        return {
            "scheduled_for": scheduled_for.isoformat() if scheduled_for else None,
            "current_plan": current_plan.subscription_name,
            "current_plan_code": current_plan.subscription_code,
            "new_plan": new_plan.subscription_name,
            "new_plan_code": new_plan.subscription_code,
        }

    def cancel_downgrade(self, tenant_id: str) -> bool:
        pending = PendingPlanChange.query.filter_by(tenant_id=tenant_id).first()
        if not pending:
            return False

        db.session.delete(pending)
        db.session.commit()
        return True

    def get_pending_change(self, tenant_id: str) -> Optional[Dict]:
        pending = PendingPlanChange.query.filter_by(tenant_id=tenant_id).first()
        return pending.to_dict() if pending else None

    def apply_scheduled_changes(self) -> List[str]:
        """
        Apply all pending plan changes that have reached their effective date.
        """
        today = date.today()
        applied_tenant_ids: List[str] = []
        pending_changes = (
            PendingPlanChange.query
            .filter(PendingPlanChange.scheduled_for <= today)
            .order_by(PendingPlanChange.scheduled_for.asc())
            .all()
        )

        stripe_available = False
        stripe = None
        stripe_key = current_app.config.get("STRIPE_SECRET_KEY")
        if stripe_key:
            try:
                import stripe as stripe_module
                stripe = stripe_module
                stripe.api_key = stripe_key
                stripe_available = True
            except ImportError:
                stripe_available = False

        for pending in pending_changes:
            sub = self._get_active_subscription(pending.tenant_id)
            new_plan = db.session.get(SubscriptionPlan, pending.new_plan_id)
            if not sub or not new_plan:
                db.session.delete(pending)
                continue

            if (
                stripe_available
                and sub.stripe_subscription_id
                and new_plan.stripe_price_id
            ):
                try:
                    stripe_sub = stripe.Subscription.retrieve(sub.stripe_subscription_id)
                    items = stripe_sub.get("items", {}).get("data", [])
                    if items:
                        stripe.Subscription.modify(
                            sub.stripe_subscription_id,
                            items=[{
                                "id": items[0]["id"],
                                "price": new_plan.stripe_price_id,
                            }],
                            proration_behavior="none",
                        )
                except Exception as exc:
                    current_app.logger.error(
                        "[SUBSCRIPTION] Failed to apply Stripe downgrade for tenant %s: %s",
                        pending.tenant_id,
                        exc,
                    )
                    continue

            sub.subscription_id = new_plan.subscription_id
            sub.subscription_start_date = today
            sub.subscription_end_date = SubscriptionService._calculate_end_date(
                today,
                new_plan.billing_cycle or 1,
            )
            sub.current_period_start = datetime.utcnow()
            sub.current_period_end = datetime.combine(
                sub.subscription_end_date,
                datetime.max.time(),
            )
            sub.updated_at = datetime.utcnow()

            SubscriptionService._reconcile_tenant_modules(
                pending.tenant_id,
                new_plan.subscription_id,
            )
            db.session.delete(pending)
            applied_tenant_ids.append(pending.tenant_id)

        if pending_changes:
            db.session.commit()

        return applied_tenant_ids

    def pause_subscription(
        self,
        tenant_id: str,
        reason: Optional[str] = None,
        resume_date: Optional[datetime] = None,
    ) -> bool:
        sub = self._get_active_subscription(tenant_id)
        if not sub or sub.status != "active":
            return False

        if not sub.subscription or float(sub.subscription.price or 0) <= 0:
            return False

        if self._get_active_pause(tenant_id):
            return False

        pause = SubscriptionPause(
            tenant_subscription_mapping_id=sub.tenant_subscription_mapping_id,
            paused_at=datetime.now(timezone.utc),
            resume_at=resume_date,
            pause_reason=reason,
            is_active=True,
        )
        db.session.add(pause)
        sub.is_active = False
        sub.updated_at = datetime.utcnow()
        db.session.commit()
        return True

    def resume_subscription(self, tenant_id: str) -> bool:
        pause = self._get_active_pause(tenant_id)
        if not pause:
            return False

        sub = db.session.get(TenantSubscription, pause.tenant_subscription_mapping_id)
        if not sub:
            return False

        pause.is_active = False
        pause.resume_at = datetime.now(timezone.utc)
        sub.is_active = True
        sub.status = "active"
        sub.updated_at = datetime.utcnow()
        db.session.commit()
        return True

    def get_pause_status(self, tenant_id: str) -> Optional[Dict]:
        pause = self._get_active_pause(tenant_id)
        if not pause:
            return None
        payload = pause.to_dict()
        payload["tenant_id"] = tenant_id
        return payload
