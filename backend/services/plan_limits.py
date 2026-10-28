"""
services/plan_limits.py
-----------------------
Pure helpers for the subscription matrix (no Flask / SQLAlchemy imports, so
they are trivially unit-testable).  SubscriptionService uses these for all
limit maths; it only adds the database reads/writes on top.

Where the limits live
    The DATABASE (Subscription_Plans) is the source of truth, so changing a
    value there changes the app and the plan cards immediately:
      users            -> max_users
      contacts         -> max_customers
      ai_credits       -> max_ai_messages
      pipelines        -> max_pipelines
      forms            -> max_forms
      booking_pages    -> max_booking_pages
      automations      -> max_active_automations (active only)
      email_campaigns  -> max_email_campaign_sends (per month)
    PLAN_MATRIX below only supplies DEFAULTS for the five newer columns while
    they are still NULL (and seeds the SQL script).

Unlimited convention
    * Legacy columns (max_users, max_customers, max_ai_messages): NULL = unlimited
      (existing behaviour).
    * Newer columns: -1 = unlimited; NULL = "not set yet" -> PLAN_MATRIX default.
    * 0 is a real limit (nothing allowed).  A missing value is never 0.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

UNLIMITED = -1
UPGRADE_URL = "/dashboard/subscription"

# feature -> metadata.  `monthly` features use the tenant's billing period.
FEATURES: Dict[str, dict] = {
    "users":           {"label": "users",                "monthly": False},
    "contacts":        {"label": "contacts",             "monthly": False},
    "pipelines":       {"label": "pipelines",            "monthly": False},
    "forms":           {"label": "forms",                "monthly": False},
    "booking_pages":   {"label": "booking pages",        "monthly": False},
    "automations":     {"label": "active automations",   "monthly": False},
    "email_campaigns": {"label": "email campaign sends", "monthly": True},
    "ai_credits":      {"label": "AI credits",           "monthly": True},
}

# Subscription_Plans columns.  Legacy ones treat NULL as unlimited.
LEGACY_COLUMN = {"users": "max_users", "contacts": "max_customers", "ai_credits": "max_ai_messages"}
NEW_COLUMN = {
    "pipelines":       "max_pipelines",
    "forms":           "max_forms",
    "booking_pages":   "max_booking_pages",
    "automations":     "max_active_automations",
    "email_campaigns": "max_email_campaign_sends",
}

# Older API responses used these names in the "resource" key.
LEGACY_RESOURCE = {"contacts": "customers", "ai_credits": "ai_messages"}

# DEFAULT limits per plan (used while the newer columns are NULL, and to seed them),
# keyed by Subscription_Plans.subscription_code.
# Codes match the real rows (the Business / AI code contains spaces and a slash).
PLAN_MATRIX: Dict[str, Dict[str, int]] = {
    # FREE = the plan a tenant lands on after the 7-day trial.  users / contacts /
    # AI match the FREE row (AI credits = 0: AI not included); the other limits
    # are a PROPOSAL (confirm).
    "FREE": {"users": 1, "contacts": 25, "pipelines": 1, "forms": 1,
             "booking_pages": 1, "automations": 0,
             "email_campaigns": 0, "ai_credits": 0},
    "STARTER": {"users": 3, "contacts": 1000, "pipelines": 1, "forms": 1,
                "booking_pages": 1, "automations": 3,
                "email_campaigns": 500, "ai_credits": 100},
    "GROWTH": {"users": 5, "contacts": 2500, "pipelines": 3, "forms": 5,
               "booking_pages": 3, "automations": 15,
               "email_campaigns": 2500, "ai_credits": 500},
    "PROFESSIONAL": {"users": 10, "contacts": 5000, "pipelines": 15, "forms": 20,
            "booking_pages": 20, "automations": 30,
            "email_campaigns": 10000, "ai_credits": 1500},
    "BUSINESS / AI": {"users": 25, "contacts": 15000, "pipelines": UNLIMITED, "forms": UNLIMITED,
                    "booking_pages": UNLIMITED, "automations": UNLIMITED,
                    "email_campaigns": 25000, "ai_credits": 2500},
}

# Used only when a tenant has no subscription row at all: same as FREE.
NO_PLAN_LIMITS: Dict[str, Optional[int]] = dict(PLAN_MATRIX["FREE"])

# Features whose resources do not exist in this backend yet register a
# counter here (feature -> fn(tenant_id) -> int).  Until then usage is 0 and
# the status API reports tracked=False for that feature.
_COUNTERS: Dict[str, Callable[[str], int]] = {}


def register_usage_counter(feature: str, fn: Callable[[str], int]) -> None:
    if feature not in FEATURES:
        raise ValueError(f"Unknown feature '{feature}'")
    _COUNTERS[feature] = fn


def get_usage_counter(feature: str) -> Optional[Callable[[str], int]]:
    return _COUNTERS.get(feature)


def normalise_code(code) -> str:
    """'Business / AI
 ' -> 'BUSINESS / AI' (codes may carry stray whitespace)."""
    return " ".join(str(code or "").upper().split())


def resolve_limit(feature: str, plan) -> Optional[int]:
    """Return the numeric limit, or None when the feature is unlimited.

    Reads the plan's database columns (see module docstring).  With no plan the
    NO_PLAN_LIMITS defaults apply.
    """
    if feature not in FEATURES:
        raise ValueError(f"Unknown feature '{feature}'")
    if plan is None:
        return _normalise(NO_PLAN_LIMITS[feature])

    legacy = LEGACY_COLUMN.get(feature)
    if legacy:
        # Database value is authoritative; NULL = unlimited (existing convention).
        return _normalise(getattr(plan, legacy, None))

    value = getattr(plan, NEW_COLUMN[feature], None)
    if value is None:  # column not filled in yet: fall back to the default matrix
        row = PLAN_MATRIX.get(normalise_code(getattr(plan, "subscription_code", None)),
                              PLAN_MATRIX["STARTER"])
        value = row[feature]
    return _normalise(value)


def plan_limits_dict(plan) -> Dict[str, Optional[int]]:
    """All limits for a plan (None = unlimited), for API responses."""
    return {feature: resolve_limit(feature, plan) for feature in FEATURES}


def _normalise(value) -> Optional[int]:
    if value is None or value < 0:
        return None
    return int(value)


def build_usage(feature: str, used: int, limit: Optional[int], *,
                tracked: bool = True, plan_code: Optional[str] = None,
                period_start=None, period_end=None) -> dict:
    """Standard usage payload shared by the status API and error responses."""
    unlimited = limit is None
    remaining = None if unlimited else max(0, limit - used)
    return {
        "feature": feature,
        "label": FEATURES[feature]["label"],
        "plan_code": plan_code,
        "limit": limit,
        "used": used,
        "remaining": remaining,
        "limit_reached": False if unlimited else used >= limit,
        "is_unlimited": unlimited,
        "tracked": tracked,
        "period": "billing_period" if FEATURES[feature]["monthly"] else "lifetime",
        "period_start": period_start.isoformat() if period_start else None,
        "period_end": period_end.isoformat() if period_end else None,
    }


class LimitExceeded(ValueError):
    """Raised when creating/consuming `amount` more would exceed a plan limit."""

    def __init__(self, usage: dict, amount: int = 1):
        self.usage = usage
        self.amount = amount
        label = usage["label"]
        plan = usage.get("plan_code") or "your plan"
        if usage["limit"] == 0:
            msg = f"{label.capitalize()} are not included in the {plan} plan. Please upgrade your plan."
        else:
            msg = (f"{label.capitalize()} limit reached for {plan}: "
                   f"{usage['used']}/{usage['limit']} used. Please upgrade your plan.")
        super().__init__(msg)

    @property
    def feature(self) -> str:
        return self.usage["feature"]

    def to_response(self) -> dict:
        u = self.usage
        return {
            "error": str(self),
            "limit_reached": True,
            "resource": LEGACY_RESOURCE.get(u["feature"], u["feature"]),
            "feature": u["feature"],
            "current_usage": u["used"],
            "limit": u["limit"],
            "plan_code": u.get("plan_code"),
            "upgrade_url": UPGRADE_URL,
        }


def check_available(usage: dict, amount: int = 1) -> None:
    """Raise LimitExceeded unless `amount` more fits under the limit."""
    if usage["is_unlimited"]:
        return
    if usage["used"] + amount > usage["limit"]:
        raise LimitExceeded(usage, amount)
