"""
services/usage_service.py
-------------------------
Thin compatibility layer over SubscriptionService's limit logic.

All counting, limit resolution and locking now live in
SubscriptionService / plan_limits so there is a single source of truth.
The functions below keep their original names and return types so existing
callers (routes, frontend) keep working.
"""

from datetime import datetime
from typing import Optional

from database import db
from models import AIUsageLog, SubscriptionPlan
from services.plan_limits import LimitExceeded
from services.subscription_service import SubscriptionService


def _svc() -> SubscriptionService:
    return SubscriptionService()


# -- Plan / period ----------------------------------------------------------

def get_active_plan(tenant_id: str) -> Optional[SubscriptionPlan]:
    """Return the SubscriptionPlan for the tenant's active/trialing subscription."""
    svc = _svc()
    sub = svc.get_active_subscription(tenant_id)
    if not sub:
        return None
    return svc.get_subscription_plan(sub.subscription_id)


def get_billing_window(tenant_id: str):
    """(period_start, period_end) of the current billing period (rolling 30 days if unknown)."""
    svc = _svc()
    return svc.get_period_window(svc.get_active_subscription(tenant_id))


# -- Usage counters (tenant-scoped) -----------------------------------------

def get_customer_count(tenant_id: str) -> int:
    return _svc().get_limit_usage(tenant_id, "contacts")["used"]


def get_user_count(tenant_id: str) -> int:
    return _svc().get_limit_usage(tenant_id, "users")["used"]


def get_ai_message_count(tenant_id: str) -> int:
    return _svc().get_limit_usage(tenant_id, "ai_credits")["used"]


# -- Snapshot ----------------------------------------------------------------

def get_usage_snapshot(tenant_id: str) -> dict:
    """
    Current usage + plan limits for a tenant.  Original keys are unchanged;
    "limits" adds every subscription-matrix feature.
    """
    svc = _svc()
    sub = svc.get_active_subscription(tenant_id)
    plan = svc.get_subscription_plan(sub.subscription_id) if sub else None
    period_start, period_end = svc.get_period_window(sub)
    limits = svc.get_all_limit_usage(tenant_id, sub, plan)

    def legacy(feature):
        u = limits[feature]
        limit = u["limit"]  # None = unlimited
        if limit is None:
            pct = 0
        elif limit == 0:
            pct = 100.0 if u["used"] else 0  # feature not included in the plan
        else:
            pct = round((u["used"] / limit) * 100, 1)
        return {"used": u["used"], "limit": limit, "pct": pct}

    return {
        "plan_name":    plan.subscription_name if plan else "Free",
        "plan_code":    plan.subscription_code if plan else "FREE",
        "period_start": period_start.isoformat() if period_start else None,
        "period_end":   period_end.isoformat()   if period_end   else None,
        "usage": {
            "customers":   legacy("contacts"),
            "users":       legacy("users"),
            "ai_messages": legacy("ai_credits"),
        },
        "limits": limits,
    }


# -- Limit checks -------------------------------------------------------------

def check_limit(tenant_id: str, feature: str) -> Optional[dict]:
    """None if one more is allowed, else the structured 403 payload
    (resource, current_usage, limit, upgrade_url)."""
    try:
        _svc().ensure_limit_available(str(tenant_id), feature)
        return None
    except LimitExceeded as exc:
        return exc.to_response()


def _message(payload: Optional[dict]) -> Optional[str]:
    return payload["error"] if payload else None


def check_customer_limit(tenant_id: str) -> Optional[str]:
    return _message(check_limit(tenant_id, "contacts"))


def check_user_limit(tenant_id: str) -> Optional[str]:
    return _message(check_limit(tenant_id, "users"))


def check_ai_limit(tenant_id: str) -> Optional[str]:
    """Read-only check.  AI routes should use SubscriptionService.reserve_ai_credit
    instead, which checks and consumes atomically."""
    return _message(check_limit(tenant_id, "ai_credits"))


# -- Warning thresholds (80% and 95%) ----------------------------------------

def get_usage_warnings(tenant_id: str) -> list[dict]:
    """Warnings for any resource above 80% (frontend banners)."""
    snapshot = get_usage_snapshot(tenant_id)
    warnings = []

    for resource, data in snapshot["usage"].items():
        limit = data["limit"]
        if limit is None or limit == 0:   # unlimited, or not included in the plan
            continue
        pct = data["pct"]
        used = data["used"]
        name = resource.replace("_", " ")

        if pct >= 95:
            warnings.append({
                "resource": resource, "level": "critical", "pct": pct,
                "used": used, "limit": limit,
                "message": f"You've used {pct}% of your {name} limit.",
            })
        elif pct >= 80:
            warnings.append({
                "resource": resource, "level": "warning", "pct": pct,
                "used": used, "limit": limit,
                "message": f"You're approaching your {name} limit ({used}/{limit}).",
            })

    return warnings


# -- Legacy recorder (kept for compatibility; no longer called by AI routes) ---

def record_ai_message(tenant_id: str, user_id: Optional[int] = None) -> None:
    """Unconditionally log one AI message.  Prefer reserve_ai_credit()."""
    db.session.add(AIUsageLog(tenant_id=tenant_id, user_id=user_id))
    db.session.commit()
