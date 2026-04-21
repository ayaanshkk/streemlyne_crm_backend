"""
Subscription Service
Business logic for subscription management

CHANGELOG
─────────────────────────────────────────────────────────────────────────────
[SUB-001]  tenant_id type: int → str throughout.
[SUB-002]  billing_cycle mapping normalised: 1=Monthly, 3=Quarterly, 12=Annual.
[SUB-003]  create_trial_subscription() — provisions 7-day trial at tenant creation.
[SUB-004]  tenant_has_access() — per-request access gate for auth_middleware.
[SUB-005]  check_subscription_status() extended with new lifecycle fields.
[SUB-006]  TRIAL_PERIOD_DAYS constant defined at module level.

NEW in this revision
─────────────────────────────────────────────────────────────────────────────
[FIX-001]  _reconcile_tenant_modules() — single source of truth for
           Tenant_Module_Mapping.  Atomically replaces the tenant's module
           rows to exactly match Subscription_Module_Mapping for the given
           plan, always preserving core modules.  Called on every state
           transition so entitlements are always consistent.

[FIX-002]  create_trial_subscription() now calls _reconcile_tenant_modules()
           so trial tenants get the correct module set from day one.

[FIX-003]  create_subscription() now calls _reconcile_tenant_modules() and
           removes the old per-module loop that only added modules and never
           removed stale ones.

[FIX-004]  cancel_subscription() rewritten to use period-end semantics
           (sets cancel_at_period_end=True, does NOT flip is_active=False).
           PRD §4.5: "access continues until billing period ends."
           Status transitions to 'canceled' lazily via _sync_subscription_state()
           or via the customer.subscription.deleted webhook.

[FIX-005]  admin_assign_subscription() — new method for sales/admin to assign
           any plan (including Custom) to a tenant that may already have an
           active trial or subscription.  Safely deactivates the existing row
           before inserting the new one.  Fixes the collision in assign_subscription()
           route which was calling create_subscription() and hitting the
           "already has an active subscription" guard.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional, List, Dict

from dateutil.relativedelta import relativedelta

from models import TenantSubscription, SubscriptionPlan
from repositories import TenantRepository, PermissionRepository

# [SUB-006] Single source of truth for trial length.
TRIAL_PERIOD_DAYS: int = 7


class SubscriptionService:
    """Service for subscription business logic."""

    def __init__(self):
        self.tenant_repo     = TenantRepository()
        self.permission_repo = PermissionRepository()

    # =========================================================================
    # Public read methods
    # =========================================================================

    def get_active_subscription(self, tenant_id: str) -> Optional[TenantSubscription]:
        """Return the tenant's most recent active TenantSubscription row."""
        return self.tenant_repo.get_active_subscription(tenant_id)

    def get_subscription_plan(self, subscription_id: int) -> Optional[SubscriptionPlan]:
        """Return a SubscriptionPlan by PK."""
        return self.tenant_repo.session.query(SubscriptionPlan).get(subscription_id)

    def get_all_plans(self) -> List[SubscriptionPlan]:
        """Return all active subscription plans."""
        return self.permission_repo.get_active_subscription_plans()

    def check_subscription_status(self, tenant_id: str) -> Dict:
        """
        Return a full status dict for the tenant's subscription.

        [SUB-005] Includes: status, trial_end_date, days_remaining_in_trial,
        stripe_subscription_id, cancel_at_period_end.
        All pre-existing keys are preserved unchanged.
        """
        subscription = self.get_active_subscription(tenant_id)
        subscription = self._sync_subscription_state(subscription)

        if not subscription:
            return {
                "has_subscription":  False,
                "is_active":         False,
                "status":            None,
                "message":           "No active subscription",
            }

        plan          = self.get_subscription_plan(subscription.subscription_id)
        today         = date.today()
        days_remaining = (
            (subscription.subscription_end_date - today).days
            if subscription.subscription_end_date
            else None
        )

        return {
            # pre-existing keys
            "has_subscription":    True,
            "is_active":           subscription.is_active,
            "plan_name":           plan.subscription_name if plan else "Unknown",
            "plan_code":           plan.subscription_code if plan else None,
            "start_date":          subscription.subscription_start_date.isoformat() if subscription.subscription_start_date else None,
            "end_date":            subscription.subscription_end_date.isoformat() if subscription.subscription_end_date else None,
            "days_remaining":      days_remaining,
            "auto_renew":          subscription.auto_renew,
            "is_expiring_soon":    (days_remaining is not None and 0 <= days_remaining <= 7),
            "is_expired":          (days_remaining is not None and days_remaining < 0),
            # [SUB-005] new keys
            "status":                   subscription.status,
            "trial_end_date":           subscription.trial_end_date.isoformat() if subscription.trial_end_date else None,
            "days_remaining_in_trial":  subscription.days_remaining_in_trial(),
            "stripe_subscription_id":   subscription.stripe_subscription_id,
            "stripe_price_id":          plan.stripe_price_id if plan else None,
            "cancel_at_period_end":     subscription.cancel_at_period_end,
            "current_period_start":     subscription.current_period_start.isoformat() if subscription.current_period_start else None,
            "current_period_end":       subscription.current_period_end.isoformat() if subscription.current_period_end else None,
        }

    def can_access_module(self, tenant_id: str, module_code: str) -> bool:
        """
        Check if a tenant can access a specific module.

        Returns False when:
        - No subscription exists
        - Subscription is not currently active (expired / canceled)
        - Module is not mapped to the tenant
        """
        subscription = self.get_active_subscription(tenant_id)
        subscription = self._sync_subscription_state(subscription)
        if not subscription or not subscription.is_currently_active():
            return False

        module = self.permission_repo.get_module_by_code(module_code)
        if not module:
            return False

        return self.tenant_repo.has_module_access(tenant_id, module.module_id)

    # =========================================================================
    # [SUB-003] Trial provisioning
    # =========================================================================

    def create_trial_subscription(self, tenant_id: str) -> TenantSubscription:
        """
        Provision a 7-day trial for a newly created tenant.

        Must be called inside the same db.session transaction as the
        Tenant_Master INSERT.  Call db.session.flush() before this so the
        FK constraint is satisfied within the open transaction.

        [FIX-002] Now also seeds Tenant_Module_Mapping via
        _reconcile_tenant_modules() so trial tenants get the correct
        module access from day one.

        Raises:
            ValueError: No active base plan in Subscription_Plans.
                        Run seed_system_data.py before creating tenants.
        """
        from database import db

        now       = datetime.now(timezone.utc)
        trial_end = now + timedelta(days=TRIAL_PERIOD_DAYS)

        base_plan = (
            db.session.query(SubscriptionPlan)
            .filter_by(is_base_plan=True, is_active=True)
            .first()
        )
        if not base_plan:
            raise ValueError(
                "No active base plan found in Subscription_Plans. "
                "Run seed_system_data.py before creating tenants."
            )

        trial_sub = TenantSubscription(
            tenant_id               = tenant_id,
            subscription_id         = base_plan.subscription_id,
            subscription_start_date = now.date(),
            subscription_end_date   = trial_end.date(),
            is_active               = True,
            auto_renew              = False,
            created_at              = now,
            status                  = "trialing",
            trial_end_date          = trial_end,
            stripe_subscription_id  = None,
        )
        db.session.add(trial_sub)
        db.session.flush()  # ensure PK is assigned before reconciling modules

        # [FIX-002] Seed module access for the trial plan
        self._reconcile_tenant_modules(tenant_id, base_plan.subscription_id)

        # Caller commits atomically with the TenantMaster INSERT
        return trial_sub

    # =========================================================================
    # Paid subscription management
    # =========================================================================

    def create_subscription(
        self,
        tenant_id: str,
        subscription_code: str,
        auto_renew: bool = False,
    ) -> TenantSubscription:
        """
        Create a new paid subscription for a tenant (Stripe-confirmed upgrades).

        For the initial trial use create_trial_subscription().
        For admin/sales override of an existing subscription use
        admin_assign_subscription().

        [FIX-003] Module assignment is now handled by _reconcile_tenant_modules()
        which also removes modules that are no longer included in the new plan,
        replacing the old additive-only loop.

        Raises:
            ValueError: Plan not found, inactive, or tenant already has an
                        active subscription (use admin_assign_subscription to
                        override).
        """
        existing = self.get_active_subscription(tenant_id)
        if existing and existing.is_currently_active():
            raise ValueError(
                "Tenant already has an active subscription. "
                "Use admin_assign_subscription() to override."
            )

        plan = self.permission_repo.get_subscription_by_code(subscription_code)
        if not plan:
            raise ValueError(f"Subscription plan '{subscription_code}' not found")
        if not plan.is_active:
            raise ValueError(f"Subscription plan '{subscription_code}' is not active")

        start_date = date.today()
        end_date   = self._calculate_end_date(start_date, plan.billing_cycle)

        subscription = self.tenant_repo.create_subscription(
            tenant_id       = tenant_id,
            subscription_id = plan.subscription_id,
            start_date      = start_date,
            end_date        = end_date,
            auto_renew      = auto_renew,
        )

        # [FIX-003] Replace additive module loop with atomic reconciliation
        self._reconcile_tenant_modules(tenant_id, plan.subscription_id)

        return subscription

    def cancel_subscription(self, tenant_id: str) -> bool:
        """
        Cancel a tenant's active subscription at period end (PRD §4.5).

        [FIX-004] PREVIOUSLY: called tenant_repo.cancel_subscription() which
        flipped is_active=False immediately — violating PRD §4.5 which requires
        access to continue until the billing period ends.

        NOW: sets cancel_at_period_end=True and auto_renew=False.
        Access continues; status transitions to 'canceled' when either:
          - _sync_subscription_state() detects the period has passed, OR
          - Stripe sends customer.subscription.deleted webhook.

        If the subscription is still in trial, it is expired immediately
        (there is no "period end" concept for a free trial).

        Returns True if a subscription was found and updated, False otherwise.
        """
        from database import db

        sub = (
            db.session.query(TenantSubscription)
            .filter_by(tenant_id=tenant_id, is_active=True)
            .order_by(TenantSubscription.created_at.desc())
            .first()
        )
        if not sub:
            return False

        if sub.status == "trialing":
            # Trials have no paid period — expire immediately
            sub.status     = "expired"
            sub.is_active  = False
            sub.auto_renew = False
            # Remove non-core module access
            self._reconcile_tenant_modules(tenant_id, subscription_id=None)
        else:
            # Paid plan — preserve access until period ends
            sub.cancel_at_period_end = True
            sub.auto_renew           = False

        sub.updated_at = datetime.utcnow()
        db.session.commit()
        return True

    def renew_subscription(self, tenant_id: str) -> Optional[TenantSubscription]:
        """
        Manually renew a subscription for another billing cycle (admin use).

        Note: superseded by invoice.paid webhook for Stripe-managed plans.
        """
        current = self.get_active_subscription(tenant_id)
        if not current:
            raise ValueError("No active subscription found to renew")

        self.cancel_subscription(tenant_id)

        plan = self.get_subscription_plan(current.subscription_id)
        if not plan:
            return None

        return self.create_subscription(
            tenant_id         = tenant_id,
            subscription_code = plan.subscription_code,
            auto_renew        = current.auto_renew,
        )

    # =========================================================================
    # [FIX-005] Admin / sales override
    # =========================================================================

    def admin_assign_subscription(
        self,
        tenant_id: str,
        subscription_code: str,
        auto_renew: bool = False,
        stripe_subscription_id: Optional[str] = None,
    ) -> TenantSubscription:
        """
        Assign any plan to a tenant, even if they already have an active
        trial or subscription (admin / sales override).

        [FIX-005] Previously, assign_subscription() in the route called
        create_subscription() which raised ValueError when the tenant already
        had an active trial — blocking Custom-plan manual provisioning entirely.

        This method:
        1. Deactivates any existing active subscription (marks it
           'expired' for trials, 'canceled' for paid plans — does NOT delete).
        2. Creates the new subscription row with status='active'.
        3. Reconciles Tenant_Module_Mapping to the new plan.

        The whole operation is performed within a single db.session transaction.
        """
        from database import db

        plan = self.permission_repo.get_subscription_by_code(subscription_code)
        if not plan:
            raise ValueError(f"Subscription plan '{subscription_code}' not found")
        if not plan.is_active:
            raise ValueError(f"Subscription plan '{subscription_code}' is not active")

        # Deactivate existing active row (if any) without deleting it
        existing = (
            db.session.query(TenantSubscription)
            .filter_by(tenant_id=tenant_id, is_active=True)
            .order_by(TenantSubscription.created_at.desc())
            .first()
        )
        if existing:
            existing.is_active  = False
            existing.status     = "expired" if existing.status == "trialing" else "canceled"
            existing.auto_renew = False
            existing.updated_at = datetime.utcnow()
            db.session.flush()

        start_date = date.today()
        end_date   = self._calculate_end_date(start_date, plan.billing_cycle)
        now_utc    = datetime.now(timezone.utc)

        new_sub = TenantSubscription(
            tenant_id               = tenant_id,
            subscription_id         = plan.subscription_id,
            subscription_start_date = start_date,
            subscription_end_date   = end_date,
            is_active               = True,
            auto_renew              = auto_renew,
            created_at              = now_utc,
            status                  = "active",
            trial_end_date          = None,
            stripe_subscription_id  = stripe_subscription_id,
            cancel_at_period_end    = False,
            current_period_start    = datetime.utcnow(),
            current_period_end      = datetime.combine(end_date, datetime.max.time()),
        )
        db.session.add(new_sub)
        db.session.flush()

        # Sync module access to the new plan
        self._reconcile_tenant_modules(tenant_id, plan.subscription_id)

        db.session.commit()
        return new_sub

    # =========================================================================
    # [SUB-004] Per-request access gate
    # =========================================================================

    @staticmethod
    def tenant_has_access(tenant_id: str) -> bool:
        """
        Return True iff the tenant may use the application.

        Called on every authenticated request by subscription_middleware.py.
        One DB read + one optional write (lazy expiry transition).

        Allowed:   status == 'active'
                   status == 'trialing' AND trial_end_date not yet passed
        Denied:    status == 'expired' | 'canceled'
                   trialing but trial_end_date in the past (lazily expired here)
                   No subscription row at all
        """
        from database import db

        sub = (
            db.session.query(TenantSubscription)
            .filter_by(tenant_id=tenant_id)
            .order_by(TenantSubscription.created_at.desc())
            .first()
        )

        sub = SubscriptionService._sync_subscription_state(sub)
        if sub is None:
            return False

        return sub.is_currently_active()

    # =========================================================================
    # Private helpers
    # =========================================================================

    @staticmethod
    def _reconcile_tenant_modules(
        tenant_id: str,
        subscription_id: Optional[int],
    ) -> None:
        """
        Atomically replace Tenant_Module_Mapping to exactly match the
        modules defined for the given plan.

        [FIX-001] This is the single place that writes Tenant_Module_Mapping.
        All state transitions (trial, upgrade, admin assign, cancel, expiry)
        call this method so the table is always consistent.

        Rules:
        - Core modules (ModuleMaster.is_core=True) are ALWAYS kept.
        - Non-core modules are set to exactly Subscription_Module_Mapping
          rows for subscription_id.
        - subscription_id=None means cancellation/expiry — remove all
          non-core modules.

        Does NOT commit — caller is responsible for committing so that
        the subscription row update and the module reconciliation land
        in the same transaction.
        """
        from database import db
        from models import TenantModuleMapping, SubscriptionModuleMapping, ModuleMaster

        # Always-on: core module IDs
        core_ids: set[int] = {
            m.module_id
            for m in db.session.query(ModuleMaster)
            .filter_by(is_core=True, is_active=True)
            .all()
        }

        # Plan-specific module IDs (empty for cancellation)
        plan_ids: set[int] = set()
        if subscription_id is not None:
            plan_ids = {
                m.module_id
                for m in db.session.query(SubscriptionModuleMapping)
                .filter_by(subscription_id=subscription_id)
                .all()
            }

        target_ids = core_ids | plan_ids

        # Current tenant mappings
        existing_rows = (
            db.session.query(TenantModuleMapping)
            .filter_by(tenant_id=tenant_id)
            .all()
        )
        existing_map: dict[int, TenantModuleMapping] = {
            row.module_id: row for row in existing_rows
        }
        existing_ids = set(existing_map.keys())

        # Add missing mappings
        for mid in target_ids - existing_ids:
            db.session.add(TenantModuleMapping(
                tenant_id = tenant_id,
                module_id = mid,
            ))

        # Remove stale mappings (not in target set)
        for mid in existing_ids - target_ids:
            db.session.delete(existing_map[mid])

    @staticmethod
    def _calculate_end_date(start_date: date, billing_cycle: int) -> date:
        """
        [SUB-002] Calculate subscription end date.
            1  → +1 month
            3  → +3 months (quarterly)
            12 → +1 year   (annual)
            N  → +N months (fallback for future cycles)
        """
        if billing_cycle == 1:
            return start_date + relativedelta(months=1)
        elif billing_cycle == 3:
            return start_date + relativedelta(months=3)
        elif billing_cycle == 12:
            return start_date + relativedelta(years=1)
        else:
            return start_date + relativedelta(months=billing_cycle)

    @staticmethod
    def _sync_subscription_state(
        subscription: Optional[TenantSubscription],
    ) -> Optional[TenantSubscription]:
        """
        Lazily persist time-driven lifecycle transitions so expiry is
        reflected immediately without a background worker.

        Transitions handled:
        - trialing + trial_end_date passed  → expired
        - active + cancel_at_period_end + period ended → canceled + remove modules
        - active + end_date passed + no auto_renew    → expired
        """
        if subscription is None:
            return None

        from database import db

        now   = datetime.now(timezone.utc)
        today = now.date()

        def _as_utc(dt_value):
            if dt_value is None:
                return None
            if dt_value.tzinfo is None:
                return dt_value.replace(tzinfo=timezone.utc)
            return dt_value.astimezone(timezone.utc)

        changed = False

        # Trial expiry
        if subscription.status == "trialing" and subscription.trial_end_date:
            if now > _as_utc(subscription.trial_end_date):
                subscription.status     = "expired"
                subscription.is_active  = False
                subscription.auto_renew = False
                # Remove non-core module access on lazy expiry
                SubscriptionService._reconcile_tenant_modules(
                    subscription.tenant_id, subscription_id=None
                )
                changed = True

        # Cancel-at-period-end: period has now passed
        period_end_at = _as_utc(subscription.current_period_end)
        if subscription.cancel_at_period_end and period_end_at and now > period_end_at:
            subscription.status              = "canceled"
            subscription.is_active           = False
            subscription.auto_renew          = False
            subscription.cancel_at_period_end = False
            SubscriptionService._reconcile_tenant_modules(
                subscription.tenant_id, subscription_id=None
            )
            changed = True
        elif (
            subscription.cancel_at_period_end
            and subscription.subscription_end_date
            and today > subscription.subscription_end_date
        ):
            subscription.status              = "canceled"
            subscription.is_active           = False
            subscription.auto_renew          = False
            subscription.cancel_at_period_end = False
            SubscriptionService._reconcile_tenant_modules(
                subscription.tenant_id, subscription_id=None
            )
            changed = True

        # Active plan expired without auto-renew
        elif (
            subscription.status == "active"
            and subscription.subscription_end_date
            and today > subscription.subscription_end_date
            and not subscription.auto_renew
        ):
            subscription.status    = "expired"
            subscription.is_active = False
            SubscriptionService._reconcile_tenant_modules(
                subscription.tenant_id, subscription_id=None
            )
            changed = True

        if changed:
            subscription.updated_at = datetime.utcnow()
            db.session.commit()

        return subscription