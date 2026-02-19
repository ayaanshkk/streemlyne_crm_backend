"""
Seed Demo Tenant
Creates a demo tenant with sample data for testing
"""

import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db
from models import (
    TenantMaster, EmployeeMaster, UserMaster,
    DesignationMaster, SubscriptionPlans
)
from flask import g


def seed_demo_tenant():
    """Create a demo tenant with sample employee and user"""
    print("\n" + "="*50)
    print("CREATING DEMO TENANT")
    print("="*50 + "\n")
    
    try:
        # Create tenant
        tenant = TenantMaster.query.filter_by(
            tenant_company_name='Demo Company'
        ).first()
        
        if not tenant:
            tenant = TenantMaster(
                tenant_company_name='Demo Company',
                tenant_contact_name='John Demo',
                onboarding_date=date.today(),
                is_active=True
            )
            db.session.add(tenant)
            db.session.commit()
            print(f"✓ Created demo tenant: {tenant.tenant_company_name} (ID: {tenant.tenant_id})")
        else:
            print(f"✓ Demo tenant already exists (ID: {tenant.tenant_id})")
        
        # Set tenant context
        g.tenant_id = tenant.tenant_id
        
        # Get CEO designation
        ceo_designation = DesignationMaster.query.filter_by(
            designation_description='CEO'
        ).first()
        
        # Create employee
        employee = EmployeeMaster.query.filter_by(
            tenant_id=tenant.tenant_id,
            email='admin@demo.com'
        ).first()
        
        if not employee:
            employee = EmployeeMaster(
                tenant_id=tenant.tenant_id,
                employee_name='Admin User',
                email='admin@demo.com',
                phone='555-0100',
                employee_designation_id=ceo_designation.designation_id if ceo_designation else None,
                date_of_joining=date.today(),
                role_ids='1'  # Super Admin role
            )
            db.session.add(employee)
            db.session.commit()
            print(f"✓ Created demo employee: {employee.employee_name} (ID: {employee.employee_id})")
        else:
            print(f"✓ Demo employee already exists (ID: {employee.employee_id})")
        
        # Create user account
        user = UserMaster.query.filter_by(
            employee_id=employee.employee_id
        ).first()
        
        if not user:
            user = UserMaster(
                employee_id=employee.employee_id,
                user_name='admin'
            )
            user.set_password('admin123')  # Change this in production!
            db.session.add(user)
            db.session.commit()
            print(f"✓ Created demo user: {user.user_name} (ID: {user.user_id})")
        else:
            print(f"✓ Demo user already exists (ID: {user.user_id})")
        
        # Assign subscription
        from services import SubscriptionService
        subscription_service = SubscriptionService()
        
        existing_subscription = subscription_service.get_active_subscription(tenant.tenant_id)
        if not existing_subscription:
            subscription = subscription_service.create_subscription(
                tenant_id=tenant.tenant_id,
                subscription_code='PROFESSIONAL',
                auto_renew=True
            )
            print(f"✓ Created demo subscription (ID: {subscription.tenant_subscription_mapping_id})")
        else:
            print("✓ Demo subscription already exists")
        
        print("\n" + "="*50)
        print("✓ DEMO TENANT CREATED SUCCESSFULLY")
        print("="*50)
        print(f"\nLogin credentials:")
        print(f"  Username: admin")
        print(f"  Password: admin123")
        print(f"  Tenant ID: {tenant.tenant_id}")
        print("\n")
        
    except Exception as e:
        print(f"\n✗ Error creating demo tenant: {e}")
        db.session.rollback()
        raise


if __name__ == '__main__':
    from app import app
    
    with app.app_context():
        seed_demo_tenant()