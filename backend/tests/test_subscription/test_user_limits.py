from datetime import date, datetime, timedelta, timezone

import pytest
from flask import g

from models import (
    CurrencyMaster,
    EmployeeMaster,
    RoleMaster,
    SubscriptionPlan,
    TenantMaster,
    TenantSubscription,
    UserMaster,
    UserRoleMapping,
)
from services.employee_service import EmployeeService
from services.subscription_service import SubscriptionService, UserLimitExceeded


def _create_currency(session):
    currency = CurrencyMaster(
        currency_id=1,
        currency_name="Pound Sterling",
        currency_code="GBP",
        created_at=datetime.utcnow(),
    )
    session.add(currency)
    session.commit()
    return currency


def _create_tenant(session, tenant_id="limit-tenant"):
    tenant = TenantMaster(
        tenant_id=tenant_id,
        tenant_company_name=f"{tenant_id} Ltd",
        tenant_contact_name="Owner",
        onboarding_Date=date.today(),
        is_active=True,
    )
    session.add(tenant)
    session.commit()
    return tenant


def _create_plan(session, currency_id, code, name, *, price=49.0, max_users=None, is_base_plan=False):
    plan = SubscriptionPlan(
        subscription_id=session.query(SubscriptionPlan).count() + 1,
        subscription_code=code,
        subscription_name=name,
        description=f"{name} plan",
        is_base_plan=is_base_plan,
        is_active=True,
        billing_cycle=1,
        price=price,
        currency_id=currency_id,
        stripe_price_id=f"price_{code.lower()}",
        max_users=max_users,
    )
    session.add(plan)
    session.commit()
    return plan


def _create_subscription(session, tenant_id, plan, *, status="active"):
    now = datetime.now(timezone.utc)
    sub = TenantSubscription(
        tenant_subscription_mapping_id=session.query(TenantSubscription).count() + 1,
        tenant_id=tenant_id,
        subscription_id=plan.subscription_id,
        subscription_start_date=date.today(),
        subscription_end_date=date.today() + timedelta(days=30),
        is_active=True,
        auto_renew=False,
        status=status,
        trial_end_date=now + timedelta(days=7) if status == "trialing" else None,
        created_at=datetime.utcnow(),
    )
    session.add(sub)
    session.commit()
    return sub


def _create_employee(session, tenant_id, idx):
    employee = EmployeeMaster(
        employee_id=session.query(EmployeeMaster).count() + 1,
        tenant_id=tenant_id,
        employee_name=f"Employee {idx}",
        email=f"employee{idx}@example.com",
    )
    session.add(employee)
    session.commit()
    return employee


def _create_user(session, tenant_id, idx, *, is_active=True, is_invite_pending=False):
    employee = _create_employee(session, tenant_id, idx)
    user = UserMaster(
        user_id=session.query(UserMaster).count() + 1,
        employee_id=employee.employee_id,
        tenant_id=tenant_id,
        user_name=f"user{idx}",
        is_active=is_active,
        is_invite_pending=is_invite_pending,
    )
    user.set_password("Password123")
    session.add(user)
    session.commit()
    return user


@pytest.fixture
def owner_headers(session, app):
    currency = _create_currency(session)
    tenant = _create_tenant(session, "owner-tenant")
    plan = _create_plan(session, currency.currency_id, "PRO", "Pro", price=99.0, max_users=None)
    _create_subscription(session, tenant.tenant_id, plan)
    employee = _create_employee(session, tenant.tenant_id, 1)
    user = UserMaster(
        user_id=1,
        employee_id=employee.employee_id,
        tenant_id=tenant.tenant_id,
        user_name="owner",
    )
    user.set_password("Password123")
    session.add(user)
    role = RoleMaster(
        role_id=1,
        role_name="Super Admin",
        role_description="Owner",
        is_system=True,
    )
    session.add(role)
    session.commit()
    session.add(UserRoleMapping(user_id=user.user_id, role_id=role.role_id))
    session.commit()
    return {
        "Authorization": f"Bearer {user.generate_jwt_token(app.config['SECRET_KEY'])}",
        "Content-Type": "application/json",
    }


def test_plan_api_returns_user_limits_and_updated_prices(client, session, owner_headers):
    starter = SubscriptionPlan(
        subscription_id=session.query(SubscriptionPlan).count() + 1,
        subscription_code="STARTER",
        subscription_name="Starter",
        description="Starter plan",
        is_base_plan=True,
        is_active=True,
        billing_cycle=1,
        price=49.0,
        currency_id=1,
        max_users=250,
    )
    session.add(starter)
    session.commit()

    response = client.get("/api/subscriptions/plans", headers=owner_headers)

    assert response.status_code == 200
    plans = {plan["subscription_code"]: plan for plan in response.get_json()}
    assert plans["STARTER"]["price"] == 49.0
    assert plans["STARTER"]["max_users"] == 250
    assert plans["PRO"]["price"] == 99.0
    assert plans["PRO"]["max_users"] is None


def test_trial_tenant_blocks_eleventh_user(session, app):
    currency = _create_currency(session)
    tenant = _create_tenant(session)
    plan = _create_plan(session, currency.currency_id, "STARTER", "Starter", max_users=250, is_base_plan=True)
    _create_subscription(session, tenant.tenant_id, plan, status="trialing")
    for idx in range(1, 11):
        _create_user(session, tenant.tenant_id, idx)
    employee = _create_employee(session, tenant.tenant_id, 11)

    with app.test_request_context():
        g.tenant_id = tenant.tenant_id
        with pytest.raises(UserLimitExceeded) as exc:
            EmployeeService().create_user_account(employee.employee_id, "user11", "Password123")

    assert exc.value.usage["effective_user_limit"] == 10
    assert exc.value.usage["current_user_count"] == 10


def test_starter_blocks_user_after_250_total_users(session, app):
    currency = _create_currency(session)
    tenant = _create_tenant(session)
    plan = _create_plan(session, currency.currency_id, "STARTER", "Starter", max_users=250)
    _create_subscription(session, tenant.tenant_id, plan)
    for idx in range(1, 251):
        _create_user(session, tenant.tenant_id, idx)
    employee = _create_employee(session, tenant.tenant_id, 251)

    with app.test_request_context():
        g.tenant_id = tenant.tenant_id
        with pytest.raises(UserLimitExceeded):
            EmployeeService().create_user_account(employee.employee_id, "user251", "Password123")


def test_pro_allows_more_than_250_users(session, app):
    currency = _create_currency(session)
    tenant = _create_tenant(session)
    plan = _create_plan(session, currency.currency_id, "PRO", "Pro", price=99.0, max_users=None)
    _create_subscription(session, tenant.tenant_id, plan)
    for idx in range(1, 252):
        _create_user(session, tenant.tenant_id, idx)
    employee = _create_employee(session, tenant.tenant_id, 252)

    with app.test_request_context():
        g.tenant_id = tenant.tenant_id
        user = EmployeeService().create_user_account(employee.employee_id, "user252", "Password123")

    assert user.user_name == "user252"


def test_inactive_and_pending_users_count_toward_limit(session):
    currency = _create_currency(session)
    tenant = _create_tenant(session)
    plan = _create_plan(session, currency.currency_id, "STARTER", "Starter", max_users=2)
    _create_subscription(session, tenant.tenant_id, plan)
    _create_user(session, tenant.tenant_id, 1, is_active=False)
    _create_user(session, tenant.tenant_id, 2, is_invite_pending=True)

    usage = SubscriptionService().get_user_limit_usage(tenant.tenant_id)

    assert usage["current_user_count"] == 2
    assert usage["user_limit_reached"] is True


def test_over_limit_plan_change_allowed_but_next_user_is_blocked(session, app):
    currency = _create_currency(session)
    tenant = _create_tenant(session)
    pro = _create_plan(session, currency.currency_id, "PRO", "Pro", price=99.0, max_users=None)
    starter = _create_plan(session, currency.currency_id, "STARTER", "Starter", max_users=1)
    _create_subscription(session, tenant.tenant_id, pro)
    _create_user(session, tenant.tenant_id, 1)
    _create_user(session, tenant.tenant_id, 2)

    sub = SubscriptionService().admin_assign_subscription(tenant.tenant_id, "STARTER")
    employee = _create_employee(session, tenant.tenant_id, 3)

    assert sub.subscription_id == starter.subscription_id
    with app.test_request_context():
        g.tenant_id = tenant.tenant_id
        with pytest.raises(UserLimitExceeded):
            EmployeeService().create_user_account(employee.employee_id, "user3", "Password123")


def test_registration_returns_structured_user_limit_error(client, session):
    currency = _create_currency(session)
    tenant = _create_tenant(session)
    plan = _create_plan(session, currency.currency_id, "STARTER", "Starter", max_users=1)
    _create_subscription(session, tenant.tenant_id, plan)
    _create_user(session, tenant.tenant_id, 1)

    response = client.post(
        "/api/auth/register",
        json={
            "account_type": "join_company",
            "tenant_id": tenant.tenant_id,
            "first_name": "Blocked",
            "last_name": "User",
            "email": "blocked@example.com",
            "password": "Password123",
            "user_name": "blocked",
        },
    )

    assert response.status_code == 403
    data = response.get_json()
    assert data["error"] == "user_limit_reached"
    assert data["limit"] == 1
    assert data["current_count"] == 1
    assert data["upgrade_url"] == "/dashboard/subscription"


def test_new_tenant_registration_still_succeeds(client, session):
    currency = _create_currency(session)
    _create_plan(session, currency.currency_id, "STARTER", "Starter", max_users=250, is_base_plan=True)

    response = client.post(
        "/api/auth/register",
        json={
            "account_type": "company",
            "first_name": "New",
            "last_name": "Owner",
            "email": "new-owner@example.com",
            "password": "Password123",
            "company_name": "New Tenant Co",
        },
    )

    assert response.status_code == 201