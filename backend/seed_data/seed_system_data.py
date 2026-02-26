"""
Seed System Data
Populates system configuration tables (modules, subscriptions, permissions, roles)
Run this AFTER seed_master_data.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db
from models import (
    ModuleMaster, SubscriptionPlans, SubscriptionModuleMapping,
    PermissionCatalog, RoleMaster, RolePermissionMapping,
    CurrencyMaster
)


def seed_modules():
    """Seed module master data"""
    modules = [
        {
            'module_code': 'CRM_CORE',
            'module_name': 'CRM Core',
            'description': 'Core CRM functionality',
            'is_core': True,
            'is_active': True
        },
        {
            'module_code': 'CLIENT_MGMT',
            'module_name': 'Client Management',
            'description': 'Manage clients and contacts',
            'is_core': True,
            'is_active': True
        },
        {
            'module_code': 'OPPORTUNITY_MGMT',
            'module_name': 'Opportunity Management',
            'description': 'Sales pipeline and opportunities',
            'is_core': True,
            'is_active': True
        },
        {
            'module_code': 'PROJECT_MGMT',
            'module_name': 'Project Management',
            'description': 'Project tracking and management',
            'is_core': False,
            'is_active': True
        },
        {
            'module_code': 'PROPOSAL_MGMT',
            'module_name': 'Proposal Management',
            'description': 'Create and manage proposals',
            'is_core': False,
            'is_active': True
        },
        {
            'module_code': 'INVOICE_MGMT',
            'module_name': 'Invoice Management',
            'description': 'Invoicing and billing',
            'is_core': False,
            'is_active': True
        },
        {
            'module_code': 'REPORTING',
            'module_name': 'Reporting & Analytics',
            'description': 'Reports and dashboards',
            'is_core': False,
            'is_active': True
        }
    ]
    
    for module_data in modules:
        existing = ModuleMaster.query.filter_by(
            module_code=module_data['module_code']
        ).first()
        
        if not existing:
            module = ModuleMaster(**module_data)
            db.session.add(module)
            print(f"✓ Added module: {module_data['module_name']}")
    
    db.session.commit()
    print("✓ Modules seeded successfully")


def seed_subscription_plans():
    """Seed subscription plans"""
    # Get USD currency
    usd = CurrencyMaster.query.filter_by(currency_code='USD').first()
    if not usd:
        print("✗ USD currency not found. Please run seed_master_data.py first.")
        return
    
    plans = [
        {
            'subscription_code': 'BASIC',
            'subscription_name': 'Basic Plan',
            'description': 'Essential CRM features',
            'is_base_plan': True,
            'is_active': True,
            'billing_cycle': 1,  # Monthly
            'price': 29.99,
            'currency_id': usd.currency_id
        },
        {
            'subscription_code': 'PROFESSIONAL',
            'subscription_name': 'Professional Plan',
            'description': 'Advanced features for growing teams',
            'is_base_plan': False,
            'is_active': True,
            'billing_cycle': 1,
            'price': 79.99,
            'currency_id': usd.currency_id
        },
        {
            'subscription_code': 'ENTERPRISE',
            'subscription_name': 'Enterprise Plan',
            'description': 'Full-featured plan for large organizations',
            'is_base_plan': False,
            'is_active': True,
            'billing_cycle': 1,
            'price': 199.99,
            'currency_id': usd.currency_id
        }
    ]
    
    for plan_data in plans:
        existing = SubscriptionPlans.query.filter_by(
            subscription_code=plan_data['subscription_code']
        ).first()
        
        if not existing:
            plan = SubscriptionPlans(**plan_data)
            db.session.add(plan)
            print(f"✓ Added subscription plan: {plan_data['subscription_name']}")
    
    db.session.commit()
    print("✓ Subscription plans seeded successfully")


def seed_subscription_modules():
    """Map modules to subscription plans"""
    # Get plans
    basic = SubscriptionPlans.query.filter_by(subscription_code='BASIC').first()
    professional = SubscriptionPlans.query.filter_by(subscription_code='PROFESSIONAL').first()
    enterprise = SubscriptionPlans.query.filter_by(subscription_code='ENTERPRISE').first()
    
    if not (basic and professional and enterprise):
        print("✗ Subscription plans not found")
        return
    
    # Get modules
    core = ModuleMaster.query.filter_by(module_code='CRM_CORE').first()
    client = ModuleMaster.query.filter_by(module_code='CLIENT_MGMT').first()
    opportunity = ModuleMaster.query.filter_by(module_code='OPPORTUNITY_MGMT').first()
    project = ModuleMaster.query.filter_by(module_code='PROJECT_MGMT').first()
    proposal = ModuleMaster.query.filter_by(module_code='PROPOSAL_MGMT').first()
    invoice = ModuleMaster.query.filter_by(module_code='INVOICE_MGMT').first()
    reporting = ModuleMaster.query.filter_by(module_code='REPORTING').first()
    
    # Basic plan modules
    basic_modules = [core, client, opportunity]
    for module in basic_modules:
        if module:
            existing = SubscriptionModuleMapping.query.filter_by(
                subscription_id=basic.subscription_id,
                module_id=module.module_id
            ).first()
            
            if not existing:
                mapping = SubscriptionModuleMapping(
                    subscription_id=basic.subscription_id,
                    module_id=module.module_id
                )
                db.session.add(mapping)
    
    # Professional plan modules (includes all basic + more)
    professional_modules = [core, client, opportunity, project, proposal]
    for module in professional_modules:
        if module:
            existing = SubscriptionModuleMapping.query.filter_by(
                subscription_id=professional.subscription_id,
                module_id=module.module_id
            ).first()
            
            if not existing:
                mapping = SubscriptionModuleMapping(
                    subscription_id=professional.subscription_id,
                    module_id=module.module_id
                )
                db.session.add(mapping)
    
    # Enterprise plan (all modules)
    enterprise_modules = [core, client, opportunity, project, proposal, invoice, reporting]
    for module in enterprise_modules:
        if module:
            existing = SubscriptionModuleMapping.query.filter_by(
                subscription_id=enterprise.subscription_id,
                module_id=module.module_id
            ).first()
            
            if not existing:
                mapping = SubscriptionModuleMapping(
                    subscription_id=enterprise.subscription_id,
                    module_id=module.module_id
                )
                db.session.add(mapping)
    
    db.session.commit()
    print("✓ Subscription-module mappings seeded successfully")


def seed_permissions():
    """Seed permission catalog"""
    permissions = [
        # Tenant permissions
        ('tenant.view', 'View tenants'),
        ('tenant.create', 'Create tenants'),
        ('tenant.update', 'Update tenants'),
        ('tenant.delete', 'Delete tenants'),
        ('tenant.deactivate', 'Deactivate tenants'),
        
        # Client permissions
        ('client.view', 'View clients'),
        ('client.create', 'Create clients'),
        ('client.update', 'Update clients'),
        ('client.delete', 'Delete clients'),
        
        # Employee permissions
        ('employee.view', 'View employees'),
        ('employee.create', 'Create employees'),
        ('employee.update', 'Update employees'),
        ('employee.delete', 'Delete employees'),
        
        # Subscription permissions
        ('subscription.view', 'View subscriptions'),
        ('subscription.create', 'Create subscriptions'),
        ('subscription.cancel', 'Cancel subscriptions'),
        
        # Module permissions
        ('module.view', 'View modules'),
        ('module.assign', 'Assign modules to tenants'),
        ('module.revoke', 'Revoke modules from tenants'),
        
        # Role permissions
        ('role.view', 'View roles'),
        ('role.create', 'Create roles'),
        ('role.update', 'Update roles'),
        ('role.delete', 'Delete roles'),
        ('role.assign_permission', 'Assign permissions to roles'),
    ]
    
    for permission_code, description in permissions:
        existing = PermissionCatalog.query.filter_by(
            permission_code=permission_code
        ).first()
        
        if not existing:
            permission = PermissionCatalog(
                permission_code=permission_code,
                description=description
            )
            db.session.add(permission)
            print(f"✓ Added permission: {permission_code}")
    
    db.session.commit()
    print("✓ Permissions seeded successfully")


def seed_roles():
    """Seed role master data"""
    roles = [
        {
            'role_name': 'Super Admin',
            'role_description': 'Full system access',
            'is_system': True
        },
        {
            'role_name': 'Admin',
            'role_description': 'Administrative access',
            'is_system': True
        },
        {
            'role_name': 'Manager',
            'role_description': 'Management level access',
            'is_system': False
        },
        {
            'role_name': 'Sales',
            'role_description': 'Sales team access',
            'is_system': False
        },
        {
            'role_name': 'Viewer',
            'role_description': 'Read-only access',
            'is_system': False
        }
    ]
    
    for role_data in roles:
        existing = RoleMaster.query.filter_by(
            role_name=role_data['role_name']
        ).first()
        
        if not existing:
            role = RoleMaster(**role_data)
            db.session.add(role)
            print(f"✓ Added role: {role_data['role_name']}")
    
    db.session.commit()
    print("✓ Roles seeded successfully")


def seed_role_permissions():
    """Assign permissions to roles"""
    # Get Super Admin role
    super_admin = RoleMaster.query.filter_by(role_name='Super Admin').first()
    if not super_admin:
        print("✗ Super Admin role not found")
        return
    
    # Assign ALL permissions to Super Admin
    all_permissions = PermissionCatalog.query.all()
    for permission in all_permissions:
        existing = RolePermissionMapping.query.filter_by(
            role_id=super_admin.role_id,
            permission_id=permission.permission_id
        ).first()
        
        if not existing:
            mapping = RolePermissionMapping(
                role_id=super_admin.role_id,
                permission_id=permission.permission_id
            )
            db.session.add(mapping)
    
    db.session.commit()
    print("✓ Super Admin permissions assigned successfully")
    
    # Add more role-permission mappings as needed...


def seed_system_data():
    """Main function to seed all system data"""
    print("\n" + "="*50)
    print("SEEDING SYSTEM DATA")
    print("="*50 + "\n")
    
    try:
        seed_modules()
        seed_subscription_plans()
        seed_subscription_modules()
        seed_permissions()
        seed_roles()
        seed_role_permissions()
        
        print("\n" + "="*50)
        print("✓ ALL SYSTEM DATA SEEDED SUCCESSFULLY")
        print("="*50 + "\n")
        
    except Exception as e:
        print(f"\n✗ Error seeding system data: {e}")
        db.session.rollback()
        raise


if __name__ == '__main__':
    from app import app
    
    with app.app_context():
        seed_system_data()