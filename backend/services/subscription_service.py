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
from flask import current_app, has_app_context

from database import db
from models import TenantMaster, TenantSubscription, SubscriptionPlan, UserMaster
from repositories import TenantRepository, PermissionRepository
from services.plan_limits import (
    FEATURES,
    LimitExceeded,
    build_usage,
    check_available,
    get_usage_counter,
    resolve_limit,
)

# [SUB-006] Single source of truth for trial length.
TRIAL_PERIOD_DAYS: int = 7
TRIAL_USER_LIMIT: int = 10


class UserLimitExceeded(ValueError):
    """Raised when a tenant has reached its subscription user limit."""

    def __init__(self, usage: Dict):
        self.usage = usage
        limit = usage.get("effective_user_limit")
        current_count = usage.get("current_user_count")
        plan_code = usage.get("plan_code") or "TRIAL"
        super().__init__(
            f"User limit reached for {plan_code}. "
            f"{current_count}/{limit} users are already assigned."
        )


class SubscriptionService:
    """Service for subscription business logic."""

    def __init__(self):
        self.tenant_repo     = TenantRepository()
        self.permission_repo = PermissionRepository()

    # =========================================================================
    # Public read methods
    # =========================================================================

    def get_active_subscription(self, tenant_id: str) -> Optional[TenantSubscription]:
        """Return the tenant's current subscription row, never leaving a tenant
        without a plan: a tenant with no row, a trial, or an expired/canceled
        subscription is put on the FREE plan (see _sync_subscription_state)."""
        subscription = self.tenant_repo.get_active_subscription(tenant_id)
        if subscription is None:
            return self._start_free_for_tenant_without_subscription(tenant_id)
        return self._sync_subscription_state(subscription)

    def _start_free_for_tenant_without_subscription(self, tenant_id: str) -> Optional[TenantSubscription]:
        from database import db

        try:
            if db.session.get(TenantMaster, tenant_id) is None:
                return None
            subscription = self._create_free_subscription(tenant_id)
            if subscription is not None:
                db.session.commit()
            return subscription
        except Exception:
            db.session.rollback()
            if has_app_context():
                current_app.logger.exception(
                    "[SUBSCRIPTION] Could not start FREE plan for tenant %s", tenant_id
                )
            return None

    def get_subscription_plan(self, subscription_id: int) -> Optional[SubscriptionPlan]:
        """Return a SubscriptionPlan by PK."""
        return self.tenant_repo.session.query(SubscriptionPlan).get(subscription_id)

    def get_all_plans(self) -> List[SubscriptionPlan]:
        """Return all active subscription plans."""
        return self.permission_repo.get_active_subscription_plans()

    def get_user_limit_usage(
        self,
        tenant_id: str,
        subscription: Optional[TenantSubscription] = None,
        plan: Optional[SubscriptionPlan] = None,
    ) -> Dict:
        """
        Return tenant user-limit usage for the current subscription.

        All User_Master rows for the tenant count toward the limit.  A NULL
        plan max_users means unlimited, except trialing tenants which use the
        fixed trial override.
        """
        subscription = subscription or self.get_active_subscription(tenant_id)
        if subscription:
            subscription = self._sync_subscription_state(subscription)
        if subscription and not plan:
            plan = self.get_subscription_plan(subscription.subscription_id)

        current_count = (
            db.session.query(UserMaster)
            .filter(UserMaster.tenant_id == str(tenant_id))
            .count()
        )
        status = subscription.status if subscription else None
        plan_max_users = resolve_limit("users", plan) if plan else None  # matrix by plan code

        effective_limit = plan_max_users   # no trials: every tenant follows its plan
        is_unlimited = effective_limit is None
        remaining = None if is_unlimited else max(0, effective_limit - current_count)
        limit_reached = False if is_unlimited else current_count >= effective_limit

        return {
            "plan_code": plan.subscription_code if plan else None,
            "max_users": plan_max_users,
            "effective_user_limit": effective_limit,
            "current_user_count": current_count,
            "remaining_user_slots": remaining,
            "user_limit_reached": limit_reached,
            "is_user_limit_unlimited": is_unlimited,
        }

    def ensure_user_limit_available(self, tenant_id: str) -> Dict:
        # Row lock serialises concurrent invites/sign-ups for the same tenant
        # until the caller's transaction commits (no-op if no subscription).
        self._lock_active_subscription(tenant_id)
        usage = self.get_user_limit_usage(tenant_id)
        if usage["user_limit_reached"]:
            raise UserLimitExceeded(usage)
        return usage

    # =========================================================================
    # Subscription matrix limits (contacts, pipelines, forms, booking pages,
    # automations, email campaigns, AI credits).  Users keep the existing
    # get_user_limit_usage() path so trial behaviour is unchanged.
    # =========================================================================

    def _lock_active_subscription(self, tenant_id: str) -> Optional[TenantSubscription]:
        """SELECT ... FOR UPDATE on the tenant's active subscription row."""
        subscription = self.get_active_subscription(tenant_id)
        if not subscription:
            return None
        return (
            db.session.query(TenantSubscription)
            .filter(
                TenantSubscription.tenant_subscription_mapping_id
                == subscription.tenant_subscription_mapping_id
            )
            .with_for_update()
            .first()
        )

    @staticmethod
    def get_period_window(subscription: Optional[TenantSubscription]):
        """Billing period used for monthly features (email, AI credits).

        Follows the subscription's current period (billing-anniversary), and
        falls back to a rolling 30 days when the period is not recorded --
        the same rule usage_service already used.
        """
        if subscription and subscription.current_period_start and subscription.current_period_end:
            return subscription.current_period_start, subscription.current_period_end
        now = datetime.utcnow()
        return now - timedelta(days=30), now

    def _count_feature_usage(self, tenant_id: str, feature: str, period) -> tuple:
        """Return (used, tracked) for a feature, always scoped to the tenant."""
        from models import AIUsageLog, ClientMaster  # local: avoid import cycles

        tid = str(tenant_id)
        if feature == "users":
            used = db.session.query(UserMaster).filter(UserMaster.tenant_id == tid).count()
            return used, True
        if feature == "contacts":
            used = (
                ClientMaster.query.filter_by(tenant_id=tid)
                .filter(ClientMaster.is_deleted.isnot(True))
                .count()
            )
            return used, True
        if feature == "ai_credits":
            start, end = period
            used = (
                AIUsageLog.query.filter_by(tenant_id=int(tid))
                .filter(AIUsageLog.created_at >= start)
                .filter(AIUsageLog.created_at <= end)
                .count()
            )
            return used, True
        counter = get_usage_counter(feature)
        if counter is None:
            return 0, False  # resource does not exist in this backend yet
        return int(counter(tid)), True

    def get_limit_usage(
        self,
        tenant_id: str,
        feature: str,
        subscription: Optional[TenantSubscription] = None,
        plan: Optional[SubscriptionPlan] = None,
    ) -> Dict:
        """Usage payload for one matrix feature (see plan_limits.build_usage)."""
        if feature not in FEATURES:
            raise ValueError(f"Unknown feature '{feature}'")
        subscription = subscription or self.get_active_subscription(tenant_id)
        if subscription and not plan:
            plan = self.get_subscription_plan(subscription.subscription_id)
        period = self.get_period_window(subscription)

        if feature == "users":
            # Reuse the existing logic, including the fixed trial override.
            u = self.get_user_limit_usage(tenant_id, subscription=subscription, plan=plan)
            return build_usage(
                "users", u["current_user_count"], u["effective_user_limit"],
                plan_code=u["plan_code"],
            )

        used, tracked = self._count_feature_usage(tenant_id, feature, period)
        monthly = FEATURES[feature]["monthly"]
        return build_usage(
            feature, used, resolve_limit(feature, plan),
            tracked=tracked,
            plan_code=plan.subscription_code if plan else None,
            period_start=period[0] if monthly else None,
            period_end=period[1] if monthly else None,
        )

    def get_all_limit_usage(self, tenant_id: str, subscription=None, plan=None) -> Dict[str, Dict]:
        subscription = subscription or self.get_active_subscription(tenant_id)
        if subscription and not plan:
            plan = self.get_subscription_plan(subscription.subscription_id)
        return {
            feature: self.get_limit_usage(tenant_id, feature, subscription, plan)
            for feature in FEATURES
        }

    def ensure_limit_available(self, tenant_id: str, feature: str, amount: int = 1) -> Dict:
        """Raise LimitExceeded unless `amount` more fits under the plan limit.

        Locks the tenant's subscription row so concurrent creates for the same
        tenant are serialised until the caller commits.  A downgrade below the
        current usage keeps blocking creation (used >= new limit).
        """
        self._lock_active_subscription(tenant_id)
        usage = self.get_limit_usage(tenant_id, feature)
        check_available(usage, amount)
        return usage

    def reserve_ai_credit(self, tenant_id: str, user_id: Optional[int] = None) -> int:
        """Atomically check the AI allowance and consume one credit.

        Check + insert happen under the subscription row lock in one
        transaction, so simultaneous requests cannot overspend.  Returns the
        AI_Usage_Log id so the caller can refund it with release_ai_credit().
        """
        from models import AIUsageLog

        try:
            self._lock_active_subscription(tenant_id)
            usage = self.get_limit_usage(tenant_id, "ai_credits")
            check_available(usage, 1)
            log = AIUsageLog(tenant_id=int(tenant_id), user_id=user_id)
            db.session.add(log)
            db.session.commit()  # releases the row lock
            return log.id
        except Exception:
            db.session.rollback()
            raise

    def release_ai_credit(self, tenant_id: str, log_id: int) -> None:
        """Refund a credit reserved by reserve_ai_credit (e.g. the AI call failed)."""
        from models import AIUsageLog

        try:
            AIUsageLog.query.filter_by(id=log_id, tenant_id=int(tenant_id)).delete()
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed to release AI credit %s", log_id)

    def _safe_limits(self, tenant_id: str, subscription, plan) -> Dict:
        """Limits block for the status API; must never break the status call."""
        try:
            return self.get_all_limit_usage(tenant_id, subscription, plan)
        except Exception:
            current_app.logger.exception("Failed to build limits for tenant %s", tenant_id)
            return {}

    def check_subscription_status(self, tenant_id: str) -> Dict:
        """
        Return a full status dict for the tenant's subscription.

        [SUB-005] Includes: status, trial_end_date, days_remaining_in_trial,
        stripe_subscription_id, cancel_at_period_end.
        All pre-existing keys are preserved unchanged.
        """
        subscription = self.get_active_subscription(tenant_id)
        current_app.logger.info(
            "[DEBUG] Raw subscription for %s: id=%s status=%s is_active=%s",
            tenant_id,
            subscription.tenant_subscription_mapping_id if subscription else None,
            subscription.status if subscription else None,
            subscription.is_active if subscription else None,
        )
        subscription = self._sync_subscription_state(subscription)
        current_app.logger.info(
            "[DEBUG] After sync for %s: status=%s is_active=%s",
            tenant_id,
            subscription.status if subscription else None,
            subscription.is_active if subscription else None,
        )

        paused_status = self._get_paused_subscription_status(tenant_id)
        if paused_status and (subscription is None or subscription.is_active is False):
            return paused_status

        if not subscription:
            usage = self.get_user_limit_usage(tenant_id, subscription=None, plan=None)
            return {
                "has_subscription":  False,
                "is_active":         False,
                "status":            None,
                "message":           "No active subscription",
                "limits":            self._safe_limits(tenant_id, None, None),
                **{key: value for key, value in usage.items() if key != "plan_code"},
            }

        plan          = self.get_subscription_plan(subscription.subscription_id)
        today         = date.today()
        days_remaining = (
            (subscription.subscription_end_date - today).days
            if subscription.subscription_end_date
            else None
        )
        usage = self.get_user_limit_usage(tenant_id, subscription=subscription, plan=plan)

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
            "pause":                    None,
            # subscription matrix: per-feature limit, used, remaining, reached, unlimited
            "limits":                   self._safe_limits(tenant_id, subscription, plan),
            **{key: value for key, value in usage.items() if key != "plan_code"},
        }

    def _get_paused_subscription_status(self, tenant_id: str) -> Optional[Dict]:
        return None

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

    def create_initial_subscription(self, tenant_id: str) -> TenantSubscription:
        """Subscription a brand-new tenant starts with: the FREE plan (no trial).

        The tenant stays on FREE until it buys a plan, and returns to FREE when a
        paid subscription ends.  Call inside the same transaction as the
        Tenant_Master INSERT, after flush().

        Raises:
            ValueError: no active FREE plan in Subscription_Plans.
        """
        subscription = self._create_free_subscription(tenant_id)
        if subscription is None:
            raise ValueError(
                "No active FREE plan found in Subscription_Plans "
                "(subscription_code = 'FREE', is_active = true)."
            )
        return subscription

    def _create_free_subscription(self, tenant_id: str) -> Optional[TenantSubscription]:
        from database import db

        free = (
            db.session.query(SubscriptionPlan)
            .filter(
                db.func.upper(db.func.trim(SubscriptionPlan.subscription_code)) == "FREE",
                SubscriptionPlan.is_active.is_(True),
            )
            .first()
        )
        if not free:
            return None

        now = datetime.now(timezone.utc)
        sub = TenantSubscription(
            tenant_id               = tenant_id,
            subscription_id         = free.subscription_id,
            subscription_start_date = now.date(),
            subscription_end_date   = None,      # FREE never lapses by date
            is_active               = True,
            auto_renew              = False,
            created_at              = now,
            status                  = "active",
            trial_end_date          = None,
            stripe_subscription_id  = None,
        )
        self._assign_sqlite_subscription_pk(sub)
        db.session.add(sub)
        db.session.flush()

        self._reconcile_tenant_modules(tenant_id, free.subscription_id)

        tenant = db.session.get(TenantMaster, tenant_id)
        if tenant and not tenant.stripe_customer_id:
            from services.payment_service import PaymentService

            try:
                PaymentService().ensure_stripe_customer(tenant, commit=False, require_stripe=False)
            except Exception as exc:
                if has_app_context():
                    current_app.logger.warning(
                        "[SUBSCRIPTION] Free provisioning skipped Stripe customer creation for tenant %s: %s",
                        tenant_id, exc,
                    )
        return sub

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
            # FREE is also a base plan now; the trial must run on a paid-tier plan
            .filter(db.func.upper(db.func.trim(SubscriptionPlan.subscription_code)) != "FREE")
            .order_by(SubscriptionPlan.subscription_id)
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
        self._assign_sqlite_subscription_pk(trial_sub)
        db.session.add(trial_sub)
        db.session.flush()  # ensure PK is assigned before reconciling modules

        # [FIX-002] Seed module access for the trial plan
        self._reconcile_tenant_modules(tenant_id, base_plan.subscription_id)

        tenant = db.session.get(TenantMaster, tenant_id)
        if tenant and not tenant.stripe_customer_id:
            from services.payment_service import PaymentService

            try:
                PaymentService().ensure_stripe_customer(
                    tenant,
                    commit=False,
                    require_stripe=False,
                )
            except Exception as exc:
                if has_app_context():
                    current_app.logger.warning(
                        "[SUBSCRIPTION] Trial provisioning skipped Stripe customer creation for tenant %s: %s",
                        tenant_id,
                        exc,
                    )

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
        self._assign_sqlite_subscription_pk(new_sub)
        db.session.add(new_sub)
        db.session.flush()

        # Sync module access to the new plan
        self._reconcile_tenant_modules(tenant_id, plan.subscription_id)

        db.session.commit()
        return new_sub

    def _assign_sqlite_subscription_pk(self, subscription: TenantSubscription) -> None:
        bind = db.session.get_bind()
        if not bind or bind.dialect.name != "sqlite":
            return
        if subscription.tenant_subscription_mapping_id is not None:
            return
        current_max = (
            db.session.query(db.func.max(TenantSubscription.tenant_subscription_mapping_id))
            .scalar()
            or 0
        )
        subscription.tenant_subscription_mapping_id = current_max + 1

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
    def _move_to_free_plan(subscription: TenantSubscription) -> bool:
        """Switch this subscription row to the active FREE plan (no commit).

        The same row is reused, so a later Stripe checkout upgrades it in place
        (the webhook updates the tenant's latest subscription row).
        Returns False when no active FREE plan exists.
        """
        from database import db

        free = (
            db.session.query(SubscriptionPlan)
            .filter(
                db.func.upper(db.func.trim(SubscriptionPlan.subscription_code)) == "FREE",
                SubscriptionPlan.is_active.is_(True),
            )
            .first()
        )
        if not free:
            return False

        subscription.subscription_id      = free.subscription_id
        subscription.status               = "active"
        subscription.is_active            = True
        subscription.auto_renew           = False
        subscription.cancel_at_period_end = False
        subscription.subscription_end_date = None   # FREE never lapses by date
        subscription.current_period_start = None
        subscription.current_period_end   = None
        subscription.trial_end_date       = None
        subscription.stripe_subscription_id = None  # the paid Stripe subscription is over
        SubscriptionService._reconcile_tenant_modules(
            subscription.tenant_id, free.subscription_id
        )
        return True

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

        # No trials: any leftover trial row (without a Stripe subscription)
        # becomes the FREE plan straight away.
        if (
            subscription.status == "trialing"
            and not subscription.stripe_subscription_id
            and SubscriptionService._move_to_free_plan(subscription)
        ):
            subscription.updated_at = datetime.utcnow()
            db.session.commit()
            return subscription

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
            and (
                subscription.current_period_end is None
                or now > _as_utc(subscription.current_period_end)
            )
        ):
            subscription.status    = "expired"
            subscription.is_active = False
            SubscriptionService._reconcile_tenant_modules(
                subscription.tenant_id, subscription_id=None
            )
            changed = True

        # A subscription that has ended (expired / canceled) returns the tenant
        # to the FREE plan until they buy again.
        if subscription.status in ("expired", "canceled", "cancelled"):
            if SubscriptionService._move_to_free_plan(subscription):
                changed = True

        if changed:
            subscription.updated_at = datetime.utcnow()
            db.session.commit()

        return subscription