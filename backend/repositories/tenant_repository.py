# repositories/tenant_repository.py
"""
Tenant Repository
Handles tenant-related database operations.

CHANGES vs previous version
─────────────────────────────────────────────────────────────────────────────
[TR-001] deactivate_tenant / reactivate_tenant: tenant_id int → str.
         Uses db.session.get() (modern API) instead of .query().get().

[TR-002] get_tenant_modules / add_module_to_tenant / remove_module_from_tenant
         / has_module_access: tenant_id int → str throughout.
         These methods filter on TenantModuleMapping.tenant_id which is a
         String FK (character varying) — passing an int caused silent type
         coercion on PostgreSQL and would fail on strict drivers.

[TR-003] Subscription methods at the bottom were already correct (str) —
         no changes needed there.  Docstrings tightened for consistency.
─────────────────────────────────────────────────────────────────────────────
"""

from models import TenantMaster, TenantModuleMapping, TenantSubscription
from .base_repository import BaseRepository
from typing import List, Optional
from datetime import datetime


class TenantRepository(BaseRepository):
    """Repository for Tenant operations."""

    def __init__(self):
        super().__init__(TenantMaster)

    # =========================================================================
    # TENANT MASTER CRUD
    # =========================================================================

    def get_by_company_name(self, company_name: str) -> Optional[TenantMaster]:
        """Find tenant by company name."""
        return self.session.query(TenantMaster).filter(
            TenantMaster.tenant_company_name == company_name
        ).first()

    def get_active_tenants(self) -> List[TenantMaster]:
        """Return all tenants with is_active = True."""
        return self.session.query(TenantMaster).filter(
            TenantMaster.is_active == True
        ).all()

    def deactivate_tenant(self, tenant_id: str) -> bool:  # [TR-001] was int
        """
        Soft-deactivate a tenant (sets is_active = False).

        Returns True if the tenant was found and updated, False otherwise.
        """
        tenant = self.session.get(TenantMaster, tenant_id)  # [TR-001] db.session.get()
        if tenant:
            tenant.is_active  = False
            tenant.updated_at = datetime.utcnow()
            self.session.commit()
            return True
        return False

    def reactivate_tenant(self, tenant_id: str) -> bool:  # [TR-001] was int
        """
        Reactivate a previously deactivated tenant.

        Returns True if the tenant was found and updated, False otherwise.
        """
        tenant = self.session.get(TenantMaster, tenant_id)  # [TR-001] db.session.get()
        if tenant:
            tenant.is_active  = True
            tenant.updated_at = datetime.utcnow()
            self.session.commit()
            return True
        return False

    # =========================================================================
    # TENANT MODULE MAPPING
    # =========================================================================

    def get_tenant_modules(self, tenant_id: str) -> List[int]:  # [TR-002] was int
        """
        Return the list of module IDs currently enabled for a tenant.

        Args:
            tenant_id: String tenant slug (e.g. "acme-001").

        Returns:
            List of integer module IDs.
        """
        mappings = self.session.query(TenantModuleMapping).filter(
            TenantModuleMapping.tenant_id == tenant_id
        ).all()
        return [m.module_id for m in mappings]

    def add_module_to_tenant(self, tenant_id: str, module_id: int) -> bool:  # [TR-002] was int
        """
        Enable a module for a tenant.

        Returns True if the mapping was created, False if it already exists
        (idempotent — not an error to call twice).
        """
        existing = self.session.query(TenantModuleMapping).filter(
            TenantModuleMapping.tenant_id == tenant_id,
            TenantModuleMapping.module_id == module_id,
        ).first()

        if existing:
            return False

        mapping = TenantModuleMapping(tenant_id=tenant_id, module_id=module_id)
        self.session.add(mapping)
        self.session.commit()
        return True

    def remove_module_from_tenant(self, tenant_id: str, module_id: int) -> bool:  # [TR-002] was int
        """
        Disable a module for a tenant.

        Returns True if the mapping existed and was removed, False otherwise.
        """
        mapping = self.session.query(TenantModuleMapping).filter(
            TenantModuleMapping.tenant_id == tenant_id,
            TenantModuleMapping.module_id == module_id,
        ).first()

        if mapping:
            self.session.delete(mapping)
            self.session.commit()
            return True
        return False

    def has_module_access(self, tenant_id: str, module_id: int) -> bool:  # [TR-002] was int
        """
        Return True if the tenant currently has the given module enabled.

        Used by SubscriptionService.can_access_module() on every module-gated
        request — keep this query fast (single indexed lookup).
        """
        mapping = self.session.query(TenantModuleMapping).filter(
            TenantModuleMapping.tenant_id == tenant_id,
            TenantModuleMapping.module_id == module_id,
        ).first()
        return mapping is not None

    # =========================================================================
    # TENANT SUBSCRIPTION
    # =========================================================================

    def get_active_subscription(self, tenant_id: str) -> Optional[TenantSubscription]:
        """
        Return the most recent subscription row for this tenant.

        [TR-003] No change needed — already correct (str).

        IMPORTANT: Does NOT filter by is_active or status.  The caller
        (SubscriptionService) decides access based on the status field.
        Filtering here would hide expired/canceled rows from
        check_subscription_status(), making it impossible to tell the
        frontend WHY access is denied.
        """
        return (
            self.session.query(TenantSubscription)
            .filter(TenantSubscription.tenant_id == tenant_id)
            .order_by(TenantSubscription.created_at.desc())
            .first()
        )

    def create_subscription(
        self,
        tenant_id: str,
        subscription_id: int,
        start_date,
        end_date,
        auto_renew: bool = False,
    ) -> TenantSubscription:
        """
        Insert a new paid (active) subscription row.

        status is explicitly set to 'active' — this is NOT a trial row.
        For trial provisioning use SubscriptionService.create_trial_subscription().
        """
        subscription = TenantSubscription(
            tenant_id               = tenant_id,
            subscription_id         = subscription_id,
            subscription_start_date = start_date,
            subscription_end_date   = end_date,
            is_active               = True,
            auto_renew              = auto_renew,
            status                  = 'active',
            created_at              = datetime.utcnow(),
        )
        self.session.add(subscription)
        self.session.commit()
        return subscription

    def cancel_subscription(self, tenant_id: str) -> bool:
        """
        Mark the most recent subscription as canceled.

        Also sets status='canceled' so the middleware and frontend
        can distinguish canceled from expired.

        Returns True if a subscription was found and updated, False otherwise.
        """
        subscription = self.get_active_subscription(tenant_id)
        if subscription:
            subscription.is_active  = False
            subscription.status     = 'canceled'
            subscription.updated_at = datetime.utcnow()
            self.session.commit()
            return True
        return False