"""
Seed Demo Tenant
Creates a demo tenant with sample data for testing.
"""

import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db
from models import (
    DesignationMaster,
    EmployeeMaster,
    RoleMaster,
    SubscriptionPlan,
    TenantMaster,
    UserMaster,
    UserRoleMapping,
)
from services import SubscriptionService, TenantService


DEMO_COMPANY_NAME = 'Demo Company'
DEMO_CONTACT_NAME = 'John Demo'
DEMO_TENANT_ID = 'demo-company'
DEMO_EMAIL = 'admin@demo.com'
DEMO_USERNAME = 'admin'
DEMO_PASSWORD = 'admin123'
DEMO_PLAN_CODE = 'PRO'


def _ensure_owner_role(user: UserMaster) -> None:
    """Attach an owner-capable role so demo billing flows work."""
    owner_role = RoleMaster.query.filter_by(role_name='Super Admin').first()
    if not owner_role:
        print("  ! Super Admin role not found; demo user will not have owner billing access")
        return

    existing_mapping = UserRoleMapping.query.filter_by(
        user_id=user.user_id,
        role_id=owner_role.role_id,
    ).first()
    if existing_mapping:
        return

    db.session.add(UserRoleMapping(user_id=user.user_id, role_id=owner_role.role_id))
    db.session.commit()
    print(f"  [ok] Linked demo user to role: {owner_role.role_name}")


def _ensure_demo_subscription(tenant: TenantMaster) -> None:
    """Upgrade the demo tenant to the seeded PRO plan."""
    pro_plan = SubscriptionPlan.query.filter_by(
        subscription_code=DEMO_PLAN_CODE,
        is_active=True,
    ).first()
    if not pro_plan:
        raise ValueError(
            "PRO plan not found. Run seed_system_data.py before seed_demo_tenant.py."
        )

    subscription_service = SubscriptionService()
    existing_subscription = subscription_service.get_active_subscription(tenant.tenant_id)

    start_date = date.today()
    end_date = SubscriptionService._calculate_end_date(
        start_date,
        pro_plan.billing_cycle or 1,
    )

    if not existing_subscription:
        subscription = subscription_service.create_subscription(
            tenant_id=tenant.tenant_id,
            subscription_code=DEMO_PLAN_CODE,
            auto_renew=True,
        )
        print(f"  [ok] Created demo subscription (ID: {subscription.tenant_subscription_mapping_id})")
        return

    existing_subscription.subscription_id = pro_plan.subscription_id
    existing_subscription.subscription_start_date = start_date
    existing_subscription.subscription_end_date = end_date
    existing_subscription.status = 'active'
    existing_subscription.is_active = True
    existing_subscription.auto_renew = True
    existing_subscription.trial_end_date = None
    existing_subscription.cancel_at_period_end = False
    existing_subscription.stripe_subscription_id = None
    existing_subscription.current_period_start = datetime.combine(
        start_date,
        datetime.min.time(),
    )
    existing_subscription.current_period_end = datetime.combine(
        end_date,
        datetime.max.time(),
    )
    existing_subscription.updated_at = datetime.utcnow()
    db.session.commit()
    print(f"  [ok] Updated demo subscription to {DEMO_PLAN_CODE}")


def seed_demo_tenant():
    """Create a demo tenant with sample employee, user, and PRO subscription."""
    print("\n" + "=" * 50)
    print("CREATING DEMO TENANT")
    print("=" * 50 + "\n")

    try:
        tenant = TenantMaster.query.filter_by(
            tenant_company_name=DEMO_COMPANY_NAME
        ).first()

        if not tenant:
            tenant = TenantService().create_tenant(
                company_name=DEMO_COMPANY_NAME,
                contact_name=DEMO_CONTACT_NAME,
                onboarding_date=date.today(),
                tenant_id=DEMO_TENANT_ID,
            )
            print(f"  [ok] Created demo tenant: {tenant.tenant_company_name} (ID: {tenant.tenant_id})")
        else:
            print(f"  [ok] Demo tenant already exists (ID: {tenant.tenant_id})")

        ceo_designation = DesignationMaster.query.filter_by(
            designation_description='CEO'
        ).first()

        employee = EmployeeMaster.query.filter_by(
            tenant_id=tenant.tenant_id,
            email=DEMO_EMAIL,
        ).first()
        if not employee:
            employee = EmployeeMaster(
                tenant_id=tenant.tenant_id,
                employee_name='Admin User',
                email=DEMO_EMAIL,
                phone='555-0100',
                employee_designation_id=(
                    ceo_designation.designation_id if ceo_designation else None
                ),
                date_of_joining=date.today(),
                role_ids='1',
            )
            db.session.add(employee)
            db.session.commit()
            print(f"  [ok] Created demo employee: {employee.employee_name} (ID: {employee.employee_id})")
        else:
            print(f"  [ok] Demo employee already exists (ID: {employee.employee_id})")

        user = UserMaster.query.filter_by(employee_id=employee.employee_id).first()
        if not user:
            user = UserMaster(
                employee_id=employee.employee_id,
                user_name=DEMO_USERNAME,
            )
            user.set_password(DEMO_PASSWORD)
            db.session.add(user)
            db.session.commit()
            print(f"  [ok] Created demo user: {user.user_name} (ID: {user.user_id})")
        else:
            print(f"  [ok] Demo user already exists (ID: {user.user_id})")

        _ensure_owner_role(user)
        _ensure_demo_subscription(tenant)

        print("\n" + "=" * 50)
        print("[ok] DEMO TENANT CREATED SUCCESSFULLY")
        print("=" * 50)
        print("\nLogin credentials:")
        print(f"  Username: {DEMO_USERNAME}")
        print(f"  Password: {DEMO_PASSWORD}")
        print(f"  Tenant ID: {tenant.tenant_id}")
        print()

    except Exception as e:
        print(f"\n[error] Error creating demo tenant: {e}")
        db.session.rollback()
        raise


if __name__ == '__main__':
    from app import app

    with app.app_context():
        seed_demo_tenant()
