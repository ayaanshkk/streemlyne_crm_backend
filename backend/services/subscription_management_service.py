from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from models import TenantSubscription


class SubscriptionManagementService:
    """Self-service subscription changes beyond initial checkout/cancel."""

    def _get_active_subscription(self, tenant_id: str) -> Optional[TenantSubscription]:
        return (
            TenantSubscription.query
            .filter_by(tenant_id=tenant_id, is_active=True)
            .order_by(TenantSubscription.created_at.desc())
            .first()
        )

    def _get_active_pause(self, tenant_id: str) -> Optional[Dict]:
        return None

    def schedule_downgrade(self, tenant_id: str, new_plan_code: str) -> Dict:
        raise NotImplementedError(
            "Pending plan changes are not implemented until Pending_Plan_Change "
            "exists in Supabase."
        )

    def cancel_downgrade(self, tenant_id: str) -> bool:
        raise NotImplementedError(
            "Pending plan changes are not implemented until Pending_Plan_Change "
            "exists in Supabase."
        )

    def get_pending_change(self, tenant_id: str) -> Optional[Dict]:
        return None

    def apply_scheduled_changes(self) -> List[str]:
        """
        Apply all pending plan changes that have reached their effective date.
        """
        return []

    def pause_subscription(
        self,
        tenant_id: str,
        reason: Optional[str] = None,
        resume_date: Optional[datetime] = None,
    ) -> bool:
        raise NotImplementedError(
            "Subscription pause is not implemented until Subscription_Pause exists in Supabase."
        )

    def resume_subscription(self, tenant_id: str) -> bool:
        raise NotImplementedError(
            "Subscription pause is not implemented until Subscription_Pause exists in Supabase."
        )

    def get_pause_status(self, tenant_id: str) -> Optional[Dict]:
        return None
