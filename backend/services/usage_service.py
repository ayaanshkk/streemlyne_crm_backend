"""
services/usage_service.py
─────────────────────────
Central service for checking and recording usage limits.
Used by AI routes, customer creation routes, and team invite routes.
"""

from datetime import datetime
from typing import Optional

from database import db
from models import (
    AIUsageLog,
    ClientMaster,
    EmployeeMaster,
    TenantSubscription,
    SubscriptionPlan,
)


# ── Fetch active plan for a tenant ────────────────────────────────────────────

def get_active_plan(tenant_id: str) -> Optional[SubscriptionPlan]:
    """Return the SubscriptionPlan for the tenant's active/trialing subscription."""
    sub = (
        TenantSubscription.query
        .filter_by(tenant_id=tenant_id)
        .filter(TenantSubscription.status.in_(["trialing", "active"]))
        .first()
    )
    if not sub or not sub.subscription:
        return None
    return sub.subscription


def get_billing_window(tenant_id: str):
    """
    Return (period_start, period_end) for the current billing window.
    Falls back to rolling 30 days if no active subscription found.
    """
    sub = (
        TenantSubscription.query
        .filter_by(tenant_id=tenant_id)
        .filter(TenantSubscription.status.in_(["trialing", "active"]))
        .first()
    )
    if sub and sub.current_period_start and sub.current_period_end:
        return sub.current_period_start, sub.current_period_end

    # Fallback: rolling 30 days
    from datetime import timedelta
    now = datetime.utcnow()
    return now - timedelta(days=30), now


# ── Usage counters ────────────────────────────────────────────────────────────

def get_customer_count(tenant_id: str) -> int:
    return (
        ClientMaster.query
        .filter_by(tenant_id=tenant_id)
        .filter(ClientMaster.is_deleted.isnot(True))
        .count()
    )


def get_user_count(tenant_id: str) -> int:
    return (
        EmployeeMaster.query
        .filter_by(tenant_id=tenant_id)
        .count()
    )


def get_ai_message_count(tenant_id: str) -> int:
    period_start, period_end = get_billing_window(tenant_id)
    return (
        AIUsageLog.query
        .filter_by(tenant_id=tenant_id)
        .filter(AIUsageLog.created_at >= period_start)
        .filter(AIUsageLog.created_at <= period_end)
        .count()
    )


# ── Full usage snapshot ───────────────────────────────────────────────────────

def get_usage_snapshot(tenant_id: str) -> dict:
    """
    Returns current usage + plan limits for a tenant.
    Used by the /usage/me endpoint and the settings page.
    """
    plan           = get_active_plan(tenant_id)
    period_start, period_end = get_billing_window(tenant_id)

    customers_used  = get_customer_count(tenant_id)
    users_used      = get_user_count(tenant_id)
    ai_used         = get_ai_message_count(tenant_id)

    max_customers   = plan.max_customers   if plan else 25
    max_users       = plan.max_users       if plan else 1
    max_ai          = plan.max_ai_messages if plan else 100

    def pct(used, limit):
        if limit is None: return 0
        return round((used / limit) * 100, 1)

    return {
        "plan_name":   plan.subscription_name if plan else "Free",
        "plan_code":   plan.subscription_code if plan else "FREE",
        "period_start": period_start.isoformat() if period_start else None,
        "period_end":   period_end.isoformat()   if period_end   else None,
        "usage": {
            "customers":   { "used": customers_used, "limit": max_customers, "pct": pct(customers_used, max_customers) },
            "users":       { "used": users_used,     "limit": max_users,     "pct": pct(users_used,     max_users)     },
            "ai_messages": { "used": ai_used,        "limit": max_ai,        "pct": pct(ai_used,        max_ai)        },
        },
    }


# ── Limit checks (returns None if OK, error string if blocked) ────────────────

def check_customer_limit(tenant_id: str) -> Optional[str]:
    plan = get_active_plan(tenant_id)
    limit = plan.max_customers if plan else 25
    if limit is None:
        return None  # unlimited
    used = get_customer_count(tenant_id)
    if used >= limit:
        return f"Customer limit reached ({used}/{limit}). Please upgrade your plan."
    return None


def check_user_limit(tenant_id: str) -> Optional[str]:
    plan = get_active_plan(tenant_id)
    limit = plan.max_users if plan else 1
    if limit is None:
        return None  # unlimited
    used = get_user_count(tenant_id)
    if used >= limit:
        return f"User limit reached ({used}/{limit}). Please upgrade your plan."
    return None


def check_ai_limit(tenant_id: str) -> Optional[str]:
    plan = get_active_plan(tenant_id)
    limit = plan.max_ai_messages if plan else 100
    if limit is None:
        return None  # unlimited
    used = get_ai_message_count(tenant_id)
    if used >= limit:
        return f"AI message limit reached ({used}/{limit}). Please upgrade your plan."
    return None


# ── Warning thresholds (80% and 95%) ─────────────────────────────────────────

def get_usage_warnings(tenant_id: str) -> list[dict]:
    """
    Returns a list of warning dicts for any resource above 80%.
    Frontend uses this to show banners.
    """
    snapshot = get_usage_snapshot(tenant_id)
    warnings = []

    for resource, data in snapshot["usage"].items():
        limit = data["limit"]
        if limit is None:
            continue
        pct = data["pct"]
        used = data["used"]

        if pct >= 95:
            warnings.append({
                "resource": resource,
                "level":    "critical",   # red — almost out
                "pct":      pct,
                "used":     used,
                "limit":    limit,
                "message":  f"You've used {pct}% of your {resource.replace('_', ' ')} limit.",
            })
        elif pct >= 80:
            warnings.append({
                "resource": resource,
                "level":    "warning",    # amber — getting close
                "pct":      pct,
                "used":     used,
                "limit":    limit,
                "message":  f"You're approaching your {resource.replace('_', ' ')} limit ({used}/{limit}).",
            })

    return warnings


# ── Record AI usage ───────────────────────────────────────────────────────────

def record_ai_message(tenant_id: str, user_id: Optional[int] = None) -> None:
    """Call this every time a StreemAI message is processed."""
    log = AIUsageLog(tenant_id=tenant_id, user_id=user_id)
    db.session.add(log)
    db.session.commit()