from datetime import date, datetime, timedelta, timezone

from services.notification_service import NotificationService

from models import (
    CurrencyMaster,
    EmployeeMaster,
    RoleMaster,
    SubscriptionInvoice,
    SubscriptionPlan,
    TenantMaster,
    TenantSubscription,
    UserMaster,
    UserRoleMapping,
)


def _create_billing_owner(session, app):
    currency = CurrencyMaster(
        currency_id=1,
        currency_name="Pound Sterling",
        currency_code="GBP",
        created_at=datetime.utcnow(),
    )
    tenant = TenantMaster(
        tenant_id="billing-tenant-extensions",
        tenant_company_name="Billing Extensions Tenant",
        tenant_contact_name="Owner User",
        onboarding_Date=date.today(),
        is_active=True,
    )
    session.add_all([currency, tenant])
    session.commit()

    employee = EmployeeMaster(
        employee_id=1,
        tenant_id=tenant.tenant_id,
        employee_name="Owner User",
        email="owner@example.com",
        phone="555-0001",
        date_of_joining=date.today(),
        role_ids="1",
    )
    session.add(employee)
    session.commit()

    user = UserMaster(
        user_id=1,
        employee_id=employee.employee_id,
        user_name="owner-user",
    )
    user.set_password("testpass123")
    session.add(user)
    session.commit()

    owner_role = RoleMaster(
        role_id=1,
        role_name="Super Admin",
        role_description="Owner role for billing tests",
        is_system=True,
    )
    session.add(owner_role)
    session.commit()

    session.add(UserRoleMapping(user_id=user.user_id, role_id=owner_role.role_id))
    session.commit()

    headers = {
        "Authorization": f"Bearer {user.generate_jwt_token(app.config['SECRET_KEY'])}",
        "Content-Type": "application/json",
    }

    return {
        "currency": currency,
        "tenant": tenant,
        "employee": employee,
        "user": user,
        "headers": headers,
    }


def _create_plan(
    session,
    currency_id: int,
    *,
    code: str,
    name: str,
    price: float = 29.0,
    stripe_price_id=None,
    is_base_plan: bool = False,
):
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
        stripe_price_id=stripe_price_id,
    )
    session.add(plan)
    session.commit()
    return plan


def _create_subscription(session, tenant_id: str, plan: SubscriptionPlan, *, status: str = "active"):
    subscription = TenantSubscription(
        tenant_subscription_mapping_id=session.query(TenantSubscription).count() + 1,
        tenant_id=tenant_id,
        subscription_id=plan.subscription_id,
        subscription_start_date=date.today(),
        subscription_end_date=date.today() + timedelta(days=30),
        is_active=True,
        auto_renew=True,
        status=status,
        current_period_start=datetime.utcnow(),
        current_period_end=datetime.utcnow() + timedelta(days=30),
        created_at=datetime.utcnow(),
    )
    session.add(subscription)
    session.commit()
    return subscription


def test_invoice_detail_includes_line_items(client, session, app):
    owner = _create_billing_owner(session, app)
    plan = _create_plan(session, owner["currency"].currency_id, code="PRO", name="Pro")
    subscription = _create_subscription(session, owner["tenant"].tenant_id, plan)

    invoice = SubscriptionInvoice(
        invoice_id=1,
        tenant_id=owner["tenant"].tenant_id,
        subscription_id=subscription.tenant_subscription_mapping_id,
        invoice_number="SUB-INV-billing-tenant-extensions-202604-0001",
        amount=29.00,
        tax_amount=5.80,
        total_amount=34.80,
        currency_id=owner["currency"].currency_id,
        status="paid",
        period_start=date.today(),
        period_end=date.today() + timedelta(days=30),
        created_at=datetime.utcnow(),
        paid_at=datetime.now(timezone.utc),
    )
    session.add(invoice)
    session.commit()

    response = client.get(
        f"/api/subscriptions/me/invoices/{invoice.invoice_id}",
        headers=owner["headers"],
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["invoice_id"] == invoice.invoice_id
    assert len(payload["line_items"]) == 2
    assert payload["line_items"][0]["label"] == "Pro"
    assert payload["line_items"][1]["type"] == "tax"


def test_payment_summary_returns_next_billing_context(client, session, app):
    owner = _create_billing_owner(session, app)
    plan = _create_plan(session, owner["currency"].currency_id, code="STARTER", name="Starter", price=49.0)
    _create_subscription(session, owner["tenant"].tenant_id, plan)

    response = client.get(
        "/api/subscriptions/me/payment-summary",
        headers=owner["headers"],
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["plan_code"] == "STARTER"
    assert payload["plan_name"] == "Starter"
    assert payload["next_billing_amount"] == 49.0
    assert payload["currency_code"] == "GBP"
    assert payload["next_billing_date"] is not None


def test_pause_and_resume_subscription_flow(client, session, app):
    owner = _create_billing_owner(session, app)
    plan = _create_plan(session, owner["currency"].currency_id, code="PRO", name="Pro", price=79.0)
    subscription = _create_subscription(session, owner["tenant"].tenant_id, plan)

    pause_response = client.post(
        "/api/subscriptions/me/pause",
        json={"reason": "Seasonal hold"},
        headers=owner["headers"],
    )

    assert pause_response.status_code == 200
    session.refresh(subscription)
    assert subscription.is_active is False

    status_response = client.get("/api/subscriptions/me", headers=owner["headers"])
    assert status_response.status_code == 200
    status_payload = status_response.get_json()
    assert status_payload["status"] == "paused"
    assert status_payload["pause"]["pause_reason"] == "Seasonal hold"

    resume_response = client.post(
        "/api/subscriptions/me/resume",
        headers=owner["headers"],
    )
    assert resume_response.status_code == 200

    session.refresh(subscription)
    assert subscription.is_active is True
    assert subscription.status == "active"


def test_notification_preferences_and_history_routes(client, session, app):
    owner = _create_billing_owner(session, app)
    _create_plan(session, owner["currency"].currency_id, code="STARTER", name="Starter")

    update_response = client.put(
        "/api/subscriptions/me/notification-preferences",
        json={
            "preferences": [
                {
                    "notification_type": "trial_expiring",
                    "email_enabled": False,
                    "in_app_enabled": True,
                }
            ]
        },
        headers=owner["headers"],
    )
    assert update_response.status_code == 200

    with app.app_context():
        NotificationService().send_in_app(
            owner["tenant"].tenant_id,
            "trial_expiring",
            "Trial expires soon",
        )

    pref_response = client.get(
        "/api/subscriptions/me/notification-preferences",
        headers=owner["headers"],
    )
    assert pref_response.status_code == 200
    prefs = pref_response.get_json()
    trial_pref = next(item for item in prefs if item["notification_type"] == "trial_expiring")
    assert trial_pref["email_enabled"] is False
    assert trial_pref["in_app_enabled"] is True

    history_response = client.get(
        "/api/subscriptions/me/notification-history?limit=10",
        headers=owner["headers"],
    )
    assert history_response.status_code == 200
    history = history_response.get_json()
    assert history["total"] == 1
    assert history["items"][0]["notification_type"] == "trial_expiring"


def test_customer_portal_route_uses_payment_service(client, session, app, monkeypatch):
    owner = _create_billing_owner(session, app)

    from services.payment_service import PaymentService

    def fake_portal_session(self, tenant_id: str, return_url=None):
        assert tenant_id == owner["tenant"].tenant_id
        assert return_url == "http://localhost:3000/subscription/manage"
        return {"portal_url": "https://billing.stripe.test/session_123"}

    monkeypatch.setattr(PaymentService, "create_customer_portal_session", fake_portal_session)

    response = client.post(
        "/api/subscriptions/me/customer-portal",
        json={"return_url": "http://localhost:3000/subscription/manage"},
        headers=owner["headers"],
    )

    assert response.status_code == 200
    assert response.get_json()["portal_url"].startswith("https://billing.stripe.test/")
