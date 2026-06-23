from datetime import date, datetime, timedelta, timezone

import pytest

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


@pytest.fixture
def billing_owner(session, app):
    currency = CurrencyMaster(
        currency_id=1,
        currency_name='Pound Sterling',
        currency_code='GBP',
        created_at=datetime.utcnow(),
    )
    tenant = TenantMaster(
        tenant_id='billing-tenant-001',
        tenant_company_name='Billing Tenant',
        tenant_contact_name='Owner User',
        onboarding_Date=date.today(),
        is_active=True,
    )
    session.add_all([currency, tenant])
    session.commit()

    employee = EmployeeMaster(
        employee_id=1,
        tenant_id=tenant.tenant_id,
        employee_name='Owner User',
        email='owner@example.com',
        phone='555-0001',
        date_of_joining=date.today(),
        role_ids='1',
    )
    session.add(employee)
    session.commit()

    user = UserMaster(
        user_id=1,
        employee_id=employee.employee_id,
        user_name='owner-user',
    )
    user.set_password('testpass123')
    session.add(user)
    session.commit()

    owner_role = RoleMaster(
        role_id=1,
        role_name='Super Admin',
        role_description='Owner role for billing tests',
        is_system=True,
    )
    session.add(owner_role)
    session.commit()

    session.add(UserRoleMapping(user_id=user.user_id, role_id=owner_role.role_id))
    session.commit()

    headers = {
        'Authorization': f"Bearer {user.generate_jwt_token(app.config['SECRET_KEY'])}",
        'Content-Type': 'application/json',
    }

    return {
        'currency': currency,
        'tenant': tenant,
        'employee': employee,
        'user': user,
        'headers': headers,
    }


def _create_plan(
    session,
    currency_id: int,
    *,
    code: str,
    name: str,
    stripe_price_id=None,
    is_base_plan: bool = False,
):
    plan = SubscriptionPlan(
        subscription_id=session.query(SubscriptionPlan).count() + 1,
        subscription_code=code,
        subscription_name=name,
        description=f'{name} plan',
        is_base_plan=is_base_plan,
        is_active=True,
        billing_cycle=1,
        price=29.00,
        currency_id=currency_id,
        stripe_price_id=stripe_price_id,
    )
    session.add(plan)
    session.commit()
    return plan


def test_checkout_returns_sales_contact_for_custom_plan(client, session, billing_owner):
    _create_plan(
        session,
        billing_owner['currency'].currency_id,
        code='CUSTOM',
        name='Custom',
        stripe_price_id=None,
    )

    response = client.post(
        '/api/subscriptions/me/checkout',
        json={'plan_code': 'CUSTOM'},
        headers=billing_owner['headers'],
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data['is_custom'] is True
    assert data['contact_url'].startswith('mailto:')


def test_checkout_rejects_paid_plan_without_stripe_price(client, session, billing_owner):
    _create_plan(
        session,
        billing_owner['currency'].currency_id,
        code='STARTER',
        name='Starter',
        stripe_price_id=None,
        is_base_plan=True,
    )

    response = client.post(
        '/api/subscriptions/me/checkout',
        json={'plan_code': 'STARTER'},
        headers=billing_owner['headers'],
    )

    assert response.status_code == 500
    data = response.get_json()
    assert data['error'] == 'Plan is not configured for Stripe checkout'


def test_manual_cancel_sets_pending_cancellation(client, session, billing_owner):
    plan = _create_plan(
        session,
        billing_owner['currency'].currency_id,
        code='PRO',
        name='Pro',
        stripe_price_id=None,
    )
    subscription = TenantSubscription(
        tenant_subscription_mapping_id=1,
        tenant_id=billing_owner['tenant'].tenant_id,
        subscription_id=plan.subscription_id,
        subscription_start_date=date.today(),
        subscription_end_date=date.today() + timedelta(days=30),
        is_active=True,
        auto_renew=True,
        status='active',
        created_at=datetime.utcnow(),
    )
    session.add(subscription)
    session.commit()

    response = client.post(
        '/api/subscriptions/me/cancel',
        headers=billing_owner['headers'],
    )

    session.refresh(subscription)

    assert response.status_code == 200
    data = response.get_json()
    assert data['cancel_at_period_end'] is True
    assert subscription.cancel_at_period_end is True
    assert subscription.is_active is True
    assert subscription.status == 'active'
    assert subscription.current_period_end is not None


def test_get_my_subscription_includes_period_and_cancel_fields(client, session, billing_owner):
    plan = _create_plan(
        session,
        billing_owner['currency'].currency_id,
        code='STARTER',
        name='Starter',
        stripe_price_id='price_starter_123',
        is_base_plan=True,
    )
    now = datetime.now(timezone.utc)
    current_period_start = datetime.utcnow()
    current_period_end = datetime.utcnow() + timedelta(days=30)
    subscription = TenantSubscription(
        tenant_subscription_mapping_id=1,
        tenant_id=billing_owner['tenant'].tenant_id,
        subscription_id=plan.subscription_id,
        subscription_start_date=date.today(),
        subscription_end_date=date.today() + timedelta(days=30),
        is_active=True,
        auto_renew=False,
        status='active',
        trial_end_date=now + timedelta(days=7),
        stripe_subscription_id='sub_123',
        cancel_at_period_end=True,
        current_period_start=current_period_start,
        current_period_end=current_period_end,
        created_at=datetime.utcnow(),
    )
    session.add(subscription)
    session.commit()

    response = client.get(
        '/api/subscriptions/me',
        headers=billing_owner['headers'],
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data['plan_code'] == 'STARTER'
    assert data['stripe_price_id'] == 'price_starter_123'
    assert data['cancel_at_period_end'] is True
    assert data['current_period_start'] == current_period_start.isoformat()
    assert data['current_period_end'] == current_period_end.isoformat()


def test_webhook_requires_secret_when_not_testing(client, app, monkeypatch):
    original_testing = app.config.get('TESTING')
    original_key = app.config.get('STRIPE_SECRET_KEY')
    original_secret = app.config.get('STRIPE_WEBHOOK_SECRET')

    app.config['TESTING'] = False
    app.config['STRIPE_SECRET_KEY'] = 'sk_test_123'
    app.config['STRIPE_WEBHOOK_SECRET'] = None
    monkeypatch.delenv('STRIPE_WEBHOOK_SECRET', raising=False)
    monkeypatch.setenv('STRIPE_SECRET_KEY', 'sk_test_123')

    try:
        response = client.post(
            '/api/subscriptions/stripe/webhook',
            data='{}',
            headers={'Content-Type': 'application/json'},
        )
    finally:
        app.config['TESTING'] = original_testing
        app.config['STRIPE_SECRET_KEY'] = original_key
        app.config['STRIPE_WEBHOOK_SECRET'] = original_secret

    assert response.status_code == 500
    assert response.get_json()['error'] == 'STRIPE_WEBHOOK_SECRET not configured'
