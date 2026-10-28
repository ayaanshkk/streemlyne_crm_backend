"""
Unit tests for the subscription limit logic (pure, no database needed):
    pytest tests/test_plan_limits.py

Limits come from the Subscription_Plans columns; PLAN_MATRIX only supplies
defaults for the five newer columns while they are NULL.  DB-level behaviour
(row locking, billing-period counts, tenant-scoped counts) is checked by hand
against the dev database.
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from services import plan_limits as pl  # noqa: E402


def db_plan(code, **overrides):
    """A plan shaped like a Subscription_Plans row with every column filled from
    PLAN_MATRIX (-1 = unlimited), like the SQL seed does."""
    m = pl.PLAN_MATRIX[code]
    cols = dict(
        subscription_code=code,
        max_users=m["users"], max_customers=m["contacts"], max_ai_messages=m["ai_credits"],
        max_pipelines=m["pipelines"], max_forms=m["forms"], max_booking_pages=m["booking_pages"],
        max_active_automations=m["automations"], max_email_campaign_sends=m["email_campaigns"],
    )
    cols.update(overrides)
    return SimpleNamespace(**cols)


def bare_plan(code, **legacy):
    """A plan whose five newer columns are still NULL (SQL not seeded yet)."""
    cols = dict(subscription_code=code, max_users=None, max_customers=None, max_ai_messages=None,
                max_pipelines=None, max_forms=None, max_booking_pages=None,
                max_active_automations=None, max_email_campaign_sends=None)
    cols.update(legacy)
    return SimpleNamespace(**cols)


EXPECTED = {  # None = unlimited
    "FREE":          dict(users=1,  contacts=25,    pipelines=1,    forms=1,    booking_pages=1,    automations=0,    email_campaigns=0,     ai_credits=0),
    "STARTER":       dict(users=3,  contacts=1000,  pipelines=1,    forms=1,    booking_pages=1,    automations=3,    email_campaigns=500,   ai_credits=100),
    "GROWTH":        dict(users=5,  contacts=2500,  pipelines=3,    forms=5,    booking_pages=3,    automations=15,   email_campaigns=2500,  ai_credits=500),
    "PROFESSIONAL":  dict(users=10, contacts=5000,  pipelines=15,   forms=20,   booking_pages=20,   automations=30,   email_campaigns=10000, ai_credits=1500),
    "BUSINESS / AI": dict(users=25, contacts=15000, pipelines=None, forms=None, booking_pages=None, automations=None, email_campaigns=25000, ai_credits=2500),
}


@pytest.mark.parametrize("code", EXPECTED)
def test_seeded_database_row_resolves_to_the_matrix(code):
    plan = db_plan(code)
    for feature, expected in EXPECTED[code].items():
        assert pl.resolve_limit(feature, plan) == expected, (code, feature)


def test_changing_the_database_value_changes_the_limit():
    plan = db_plan("STARTER", max_users=7, max_customers=1234, max_forms=9, max_ai_messages=42)
    assert pl.resolve_limit("users", plan) == 7
    assert pl.resolve_limit("contacts", plan) == 1234
    assert pl.resolve_limit("forms", plan) == 9
    assert pl.resolve_limit("ai_credits", plan) == 42


def test_plan_limits_dict_is_what_the_plan_cards_show():
    d = pl.plan_limits_dict(db_plan("STARTER", max_users=3))
    assert d["users"] == 3 and set(d) == set(pl.FEATURES)


@pytest.mark.parametrize("code", EXPECTED)
def test_accepts_up_to_limit_then_rejects_next(code):
    plan = db_plan(code)
    for feature in EXPECTED[code]:
        limit = pl.resolve_limit(feature, plan)
        if limit is None or limit == 0:
            continue
        pl.check_available(pl.build_usage(feature, limit - 1, limit))
        full = pl.build_usage(feature, limit, limit)
        assert full["limit_reached"] is True
        with pytest.raises(pl.LimitExceeded):
            pl.check_available(full)


def test_unlimited_minus_one_in_new_columns_is_never_blocked():
    limit = pl.resolve_limit("pipelines", db_plan("BUSINESS / AI"))
    assert limit is None
    usage = pl.build_usage("pipelines", 10_000_000, limit)
    assert usage["is_unlimited"] and usage["remaining"] is None and not usage["limit_reached"]
    pl.check_available(usage)


def test_null_legacy_column_means_unlimited_existing_convention():
    plan = db_plan("PROFESSIONAL", max_customers=None, max_users=None, max_ai_messages=None)
    assert pl.resolve_limit("contacts", plan) is None
    assert pl.resolve_limit("users", plan) is None
    assert pl.resolve_limit("ai_credits", plan) is None


def test_zero_is_a_real_limit_not_unlimited():
    plan = db_plan("FREE", max_ai_messages=0, max_forms=0)
    assert pl.resolve_limit("ai_credits", plan) == 0
    assert pl.resolve_limit("forms", plan) == 0
    with pytest.raises(pl.LimitExceeded):
        pl.check_available(pl.build_usage("forms", 0, 0))


def test_new_columns_null_fall_back_to_the_default_matrix_by_plan_code():
    # before the SQL is run / seeded, the five new limits use PLAN_MATRIX
    growth = bare_plan("GROWTH", max_users=5, max_customers=2500, max_ai_messages=500)
    assert pl.resolve_limit("pipelines", growth) == 3
    assert pl.resolve_limit("automations", growth) == 15
    assert pl.resolve_limit("email_campaigns", growth) == 2500
    # tolerant plan-code matching (real code has spaces and a slash)
    for code in ("BUSINESS / AI", "business / ai", " Business /  AI\n "):
        assert pl.resolve_limit("pipelines", bare_plan(code)) is None
    # unknown plan: Starter defaults, never unlimited or zero
    assert pl.resolve_limit("forms", bare_plan("PARTNER")) == pl.PLAN_MATRIX["STARTER"]["forms"]


def test_downgrade_below_current_usage_blocks_creation_without_deleting():
    usage = pl.build_usage("forms", 7, pl.resolve_limit("forms", db_plan("GROWTH")))
    assert usage["used"] == 7 and usage["remaining"] == 0 and usage["limit_reached"]
    with pytest.raises(pl.LimitExceeded):
        pl.check_available(usage)


def test_upgrade_reopens_capacity():
    usage = pl.build_usage("forms", 5, pl.resolve_limit("forms", db_plan("PROFESSIONAL")))
    assert usage["remaining"] == 15
    pl.check_available(usage)


def test_bulk_amount_cannot_overshoot():
    usage = pl.build_usage("contacts", 990, 1000)
    pl.check_available(usage, 10)
    with pytest.raises(pl.LimitExceeded):
        pl.check_available(usage, 11)


def test_no_plan_uses_free_defaults():
    assert pl.resolve_limit("users", None) == 1
    assert pl.resolve_limit("contacts", None) == 25
    assert pl.resolve_limit("ai_credits", None) == 0


def test_error_payload_has_resource_usage_limit_and_upgrade_guidance():
    exc = pl.LimitExceeded(pl.build_usage("contacts", 1000, 1000, plan_code="STARTER"))
    body = exc.to_response()
    assert body["limit_reached"] is True and body["resource"] == "customers"
    assert body["feature"] == "contacts" and body["current_usage"] == 1000 and body["limit"] == 1000
    assert body["plan_code"] == "STARTER" and body["upgrade_url"] and "upgrade" in body["error"].lower()


def test_feature_not_included_in_plan_says_so():
    limit = pl.resolve_limit("ai_credits", db_plan("FREE"))
    exc = pl.LimitExceeded(pl.build_usage("ai_credits", 0, limit, plan_code="FREE"))
    assert limit == 0 and "not included" in str(exc) and exc.to_response()["limit"] == 0


def test_status_payload_exposes_everything_the_frontend_needs():
    u = pl.build_usage("ai_credits", 40, 100, plan_code="STARTER")
    for key in ("limit", "used", "remaining", "limit_reached", "is_unlimited", "feature", "plan_code"):
        assert key in u
    assert u["remaining"] == 60 and u["period"] == "billing_period"


def test_usage_counters_are_called_per_tenant_for_isolation():
    seen, data = [], {"1": 3, "2": 9}

    def counter(tenant_id):
        seen.append(tenant_id)
        return data[tenant_id]

    pl.register_usage_counter("forms", counter)
    try:
        fn = pl.get_usage_counter("forms")
        assert fn("1") == 3 and fn("2") == 9 and seen == ["1", "2"]
    finally:
        pl._COUNTERS.pop("forms", None)


def test_register_rejects_unknown_feature():
    with pytest.raises(ValueError):
        pl.register_usage_counter("nope", lambda t: 0)
