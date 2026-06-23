"""
Tenant Service
Business logic for tenant management.

CHANGES vs previous version
─────────────────────────────────────────────────────────────────────────────
[TSVC-001] create_tenant() now:
           a) Accepts an optional tenant_id parameter (for tests/migrations).
              When not supplied, a unique slug is generated via
              _generate_tenant_id().
           b) After flushing the Tenant_Master INSERT, calls
              SubscriptionService.create_trial_subscription() inside the
              same transaction, so both rows commit atomically.
           c) Raises ValueError (not a silent duplicate) when the company
              name already exists, matching the route's error-handling
              expectation.

[TSVC-002] All tenant_id parameters changed from int → str throughout every
           method to match the varchar PK in Tenant_Master.

[TSVC-003] get_tenant() uses db.session.get() (SQLAlchemy 2.x style)
           instead of Query.get() which is deprecated.
─────────────────────────────────────────────────────────────────────────────
"""

from repositories import TenantRepository
from models import TenantMaster
from typing import List, Optional, Dict
from datetime import datetime, date
import re
import uuid


def _generate_tenant_id(company_name: str) -> str:
    """
    Derive a URL-safe string slug from company_name plus a random suffix.

    Example: "Acme Ltd" → "acme-ltd-a3f8c2"
    """
    slug = re.sub(r'[^a-z0-9]+', '-', company_name.lower()).strip('-')[:24]
    suffix = uuid.uuid4().hex[:6]
    return f"{slug}-{suffix}"


class TenantService:
    """Service for tenant business logic."""

    def __init__(self):
        self.repo = TenantRepository()

    def create_tenant(
        self,
        company_name: str,
        contact_name: str = None,
        onboarding_date: date = None,
        tenant_id: str = None,          # [TSVC-001] optional override (tests / migrations)
    ) -> TenantMaster:
        """
        Create a new tenant and provision a 7-day trial subscription atomically.

        [TSVC-001] Generates a string slug for tenant_id if one is not supplied,
        then flushes Tenant_Master, provisions the trial row, and commits both
        in a single transaction.  If no base plan exists in Subscription_Plans,
        the transaction is rolled back and a ValueError is raised — run
        seed_system_data.py before creating tenants.

        Args:
            company_name:    Company name (must be unique).
            contact_name:    Primary contact name.
            onboarding_date: Date of onboarding; defaults to today.
            tenant_id:       Override the generated slug (optional).

        Returns:
            Created TenantMaster instance.

        Raises:
            ValueError: company name already exists, or no base plan found.
        """
        from database import db

        existing = self.repo.get_by_company_name(company_name)
        if existing:
            raise ValueError(f"Tenant with company name '{company_name}' already exists")

        tid = tenant_id or _generate_tenant_id(company_name)

        tenant = TenantMaster(
            tenant_id=tid,
            tenant_company_name=company_name,
            tenant_contact_name=contact_name,
            onboarding_Date=onboarding_date or date.today(),
            is_active=True,
        )
        db.session.add(tenant)

        # Flush so the FK from Tenant_Subscription → Tenant_Master is satisfied
        # within the transaction without an intermediate commit.
        db.session.flush()

        # [TSVC-001] Provision 7-day trial — same transaction as the tenant INSERT.
        from services.subscription_service import SubscriptionService
        SubscriptionService().create_trial_subscription(tid)

        db.session.commit()
        return tenant

    def get_tenant(self, tenant_id: str) -> Optional[TenantMaster]:
        """Get tenant by ID. [TSVC-002] tenant_id is a string slug."""
        # [TSVC-003] SQLAlchemy 2.x style
        from database import db
        return db.session.get(TenantMaster, tenant_id)

    def get_all_active_tenants(self) -> List[TenantMaster]:
        """Get all active tenants."""
        return self.repo.get_active_tenants()

    def update_tenant(self, tenant_id: str, **updates) -> Optional[TenantMaster]:
        """
        Update tenant information.

        Args:
            tenant_id: String tenant slug.  [TSVC-002]
            **updates: Fields to update.

        Returns:
            Updated TenantMaster instance or None.
        """
        tenant = self.get_tenant(tenant_id)
        if not tenant:
            return None

        for key, value in updates.items():
            if hasattr(tenant, key):
                setattr(tenant, key, value)

        tenant.updated_at = datetime.utcnow()
        self.repo.session.commit()
        return tenant

    def deactivate_tenant(self, tenant_id: str) -> bool:
        """Deactivate a tenant. [TSVC-002]"""
        return self.repo.deactivate_tenant(tenant_id)

    def reactivate_tenant(self, tenant_id: str) -> bool:
        """Reactivate a tenant. [TSVC-002]"""
        return self.repo.reactivate_tenant(tenant_id)

    def get_tenant_modules(self, tenant_id: str) -> List[int]:
        """Get list of module IDs enabled for tenant. [TSVC-002]"""
        return self.repo.get_tenant_modules(tenant_id)

    def enable_module(self, tenant_id: str, module_id: int) -> bool:
        """
        Enable a module for a tenant.  [TSVC-002]

        Returns:
            True if successful, False if already enabled.
        """
        return self.repo.add_module_to_tenant(tenant_id, module_id)

    def disable_module(self, tenant_id: str, module_id: int) -> bool:
        """
        Disable a module for a tenant.  [TSVC-002]

        Returns:
            True if successful, False if not found.
        """
        return self.repo.remove_module_from_tenant(tenant_id, module_id)

    def has_module_access(self, tenant_id: str, module_id: int) -> bool:
        """Check if tenant has access to a module. [TSVC-002]"""
        return self.repo.has_module_access(tenant_id, module_id)

    def get_tenant_statistics(self, tenant_id: str) -> Dict:
        """
        Get statistics for a tenant.  [TSVC-002]

        Args:
            tenant_id: String tenant slug.

        Returns:
            Dictionary with statistics.
        """
        from repositories import EmployeeRepository
        from flask import g

        tenant = self.get_tenant(tenant_id)
        if not tenant:
            return {}

        g.tenant_id = tenant_id  # Set tenant context for repository scoping

        employee_repo = EmployeeRepository()
        employee_count = employee_repo.count(force_tenant=True)

        return {
            'tenant_id': tenant_id,
            'company_name': tenant.tenant_company_name,
            'is_active': tenant.is_active,
            'onboarding_date': tenant.onboarding_Date.isoformat() if tenant.onboarding_Date else None,
            'employee_count': employee_count,
            'enabled_modules': len(self.get_tenant_modules(tenant_id)),
            'created_at': tenant.created_at.isoformat() if tenant.created_at else None,
        }