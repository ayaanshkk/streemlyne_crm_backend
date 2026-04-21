"""
Seed System Data
Populates system configuration tables (modules, subscriptions, permissions, roles).
Run this AFTER seed_master_data.py.

CHANGES vs previous version
─────────────────────────────────────────────────────────────────────────────
[SEED-001] Subscription plan codes/names aligned with PRD and Design Doc:
           OLD: BASIC / PROFESSIONAL / ENTERPRISE  (USD)
           NEW: STARTER / PRO / CUSTOM             (GBP)

[SEED-002] GBP currency used for all plans (PRD §3: "Currency changed to £").

[SEED-003] stripe_price_id populated for STARTER and PRO from environment
           variables (STRIPE_PRICE_STARTER, STRIPE_PRICE_PRO).
           Custom plan intentionally has stripe_price_id = None — it is
           provisioned manually by the sales team with no Stripe Checkout flow.

[SEED-004] seed_subscription_plans() now UPSERTS: if a plan already exists,
           it updates price, currency, and stripe_price_id rather than
           silently skipping the row.  This makes the seed idempotent and
           lets teams re-run it after adding real Stripe price IDs.

[SEED-005] Module codes already matched backend (CRM_CORE, CLIENT_MGMT, …)
           and are unchanged.  The module-to-plan mappings have been updated
           to reference the new plan codes.
─────────────────────────────────────────────────────────────────────────────

Environment variables for Stripe price IDs (set before running in production):
    STRIPE_PRICE_STARTER   e.g. price_1ABC…
    STRIPE_PRICE_PRO       e.g. price_1DEF…
─────────────────────────────────────────────────────────────────────────────
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db
from models import (
    ModuleMaster, SubscriptionPlan, SubscriptionModuleMapping,
    PermissionCatalog, RoleMaster, RolePermissionMapping,
    CurrencyMaster,
)


def seed_modules():
    """Seed Module_Master — idempotent."""
    modules = [
        {
            'module_code': 'CRM_CORE',
            'module_name': 'CRM Core',
            'description': 'Core CRM functionality',
            'is_core':     True,
            'is_active':   True,
        },
        {
            'module_code': 'CLIENT_MGMT',
            'module_name': 'Client Management',
            'description': 'Manage clients and contacts',
            'is_core':     True,
            'is_active':   True,
        },
        {
            'module_code': 'OPPORTUNITY_MGMT',
            'module_name': 'Opportunity Management',
            'description': 'Sales pipeline and opportunities',
            'is_core':     True,
            'is_active':   True,
        },
        {
            'module_code': 'PROJECT_MGMT',
            'module_name': 'Project Management',
            'description': 'Project tracking and management',
            'is_core':     False,
            'is_active':   True,
        },
        {
            'module_code': 'PROPOSAL_MGMT',
            'module_name': 'Proposal Management',
            'description': 'Create and manage proposals',
            'is_core':     False,
            'is_active':   True,
        },
        {
            'module_code': 'INVOICE_MGMT',
            'module_name': 'Invoice Management',
            'description': 'Invoicing and billing',
            'is_core':     False,
            'is_active':   True,
        },
        {
            'module_code': 'REPORTING',
            'module_name': 'Reporting & Analytics',
            'description': 'Reports and dashboards',
            'is_core':     False,
            'is_active':   True,
        },
    ]

    for module_data in modules:
        existing = ModuleMaster.query.filter_by(module_code=module_data['module_code']).first()
        if not existing:
            db.session.add(ModuleMaster(**module_data))
            print(f"  ✓ Added module: {module_data['module_name']}")
        # No update needed — module definitions are stable

    db.session.commit()
    print("✓ Modules seeded")


def seed_subscription_plans():
    """
    Seed Subscription_Plans with STARTER / PRO / CUSTOM in GBP.

    [SEED-001] Plan catalogue aligned with PRD §4.4 and Design Doc §4.
    [SEED-002] Prices in GBP (British Pound).
    [SEED-003] stripe_price_id from env vars; null for Custom.
    [SEED-004] Upserts so re-running updates prices / stripe IDs.
    """
    # [SEED-002] Require GBP
    gbp = CurrencyMaster.query.filter_by(currency_code='GBP').first()
    if not gbp:
        print("✗ GBP currency not found. Please run seed_master_data.py first.")
        return

    # [SEED-003] Read Stripe price IDs from environment
    stripe_price_starter = os.environ.get('STRIPE_PRICE_STARTER') or None
    stripe_price_pro     = os.environ.get('STRIPE_PRICE_PRO')     or None

    if not stripe_price_starter:
        print("  ⚠  STRIPE_PRICE_STARTER not set — stripe_price_id will be null for Starter plan")
    if not stripe_price_pro:
        print("  ⚠  STRIPE_PRICE_PRO not set — stripe_price_id will be null for Pro plan")

    plans = [
        {
            'subscription_code': 'STARTER',
            'subscription_name': 'Starter',
            'description':       'Basic CRM usage — essential features for small teams',
            'is_base_plan':      True,    # Trial uses this plan
            'is_active':         True,
            'billing_cycle':     1,       # Monthly
            'price':             29.00,
            'currency_id':       gbp.currency_id,
            'stripe_price_id':   stripe_price_starter,  # null until set via env var
        },
        {
            'subscription_code': 'PRO',
            'subscription_name': 'Pro',
            'description':       'Advanced features for growing teams — Most Popular',
            'is_base_plan':      False,
            'is_active':         True,
            'billing_cycle':     1,
            'price':             79.00,
            'currency_id':       gbp.currency_id,
            'stripe_price_id':   stripe_price_pro,      # null until set via env var
        },
        {
            'subscription_code': 'CUSTOM',
            'subscription_name': 'Custom',
            'description':       'Bespoke plan configured by the sales team',
            'is_base_plan':      False,
            'is_active':         True,
            'billing_cycle':     1,
            'price':             0.00,
            'currency_id':       gbp.currency_id,
            # [SEED-003] Custom plan INTENTIONALLY has no stripe_price_id.
            # It is provisioned manually — no Stripe Checkout flow.
            'stripe_price_id':   None,
        },
    ]

    for plan_data in plans:
        existing = SubscriptionPlan.query.filter_by(
            subscription_code=plan_data['subscription_code']
        ).first()

        if not existing:
            db.session.add(SubscriptionPlan(**plan_data))
            print(f"  ✓ Added plan: {plan_data['subscription_name']}")
        else:
            # [SEED-004] Upsert: update mutable fields so re-runs are safe
            existing.subscription_name = plan_data['subscription_name']
            existing.description       = plan_data['description']
            existing.price             = plan_data['price']
            existing.currency_id       = plan_data['currency_id']
            existing.is_base_plan      = plan_data['is_base_plan']
            existing.is_active         = plan_data['is_active']
            # Only overwrite stripe_price_id if the env var is set,
            # so a previously configured value is not accidentally cleared.
            if plan_data['stripe_price_id'] is not None:
                existing.stripe_price_id = plan_data['stripe_price_id']
            print(f"  ↻ Updated plan: {plan_data['subscription_name']}")

    db.session.commit()
    print("✓ Subscription plans seeded")


def seed_subscription_modules():
    """
    Map modules to subscription plans.
    [SEED-005] Updated to reference STARTER / PRO / CUSTOM plan codes.
    """
    starter  = SubscriptionPlan.query.filter_by(subscription_code='STARTER').first()
    pro      = SubscriptionPlan.query.filter_by(subscription_code='PRO').first()
    custom   = SubscriptionPlan.query.filter_by(subscription_code='CUSTOM').first()

    if not (starter and pro and custom):
        print("✗ Subscription plans not found — run seed_subscription_plans() first")
        return

    core        = ModuleMaster.query.filter_by(module_code='CRM_CORE').first()
    client      = ModuleMaster.query.filter_by(module_code='CLIENT_MGMT').first()
    opportunity = ModuleMaster.query.filter_by(module_code='OPPORTUNITY_MGMT').first()
    project     = ModuleMaster.query.filter_by(module_code='PROJECT_MGMT').first()
    proposal    = ModuleMaster.query.filter_by(module_code='PROPOSAL_MGMT').first()
    invoice     = ModuleMaster.query.filter_by(module_code='INVOICE_MGMT').first()
    reporting   = ModuleMaster.query.filter_by(module_code='REPORTING').first()

    plan_modules = {
        starter.subscription_id:  [core, client, opportunity],
        pro.subscription_id:      [core, client, opportunity, project, proposal],
        custom.subscription_id:   [core, client, opportunity, project, proposal, invoice, reporting],
    }

    for sub_id, modules in plan_modules.items():
        for module in modules:
            if not module:
                continue
            exists = SubscriptionModuleMapping.query.filter_by(
                subscription_id=sub_id, module_id=module.module_id
            ).first()
            if not exists:
                db.session.add(SubscriptionModuleMapping(
                    subscription_id=sub_id,
                    module_id=module.module_id,
                ))

    db.session.commit()
    print("✓ Subscription-module mappings seeded")


def seed_permissions():
    """Seed Permission_Catalog — idempotent."""
    permissions = [
        # Tenant
        ('tenant.view',         'View tenants'),
        ('tenant.create',       'Create tenants'),
        ('tenant.update',       'Update tenants'),
        ('tenant.delete',       'Delete tenants'),
        ('tenant.deactivate',   'Deactivate tenants'),
        # Client
        ('client.view',         'View clients'),
        ('client.create',       'Create clients'),
        ('client.update',       'Update clients'),
        ('client.delete',       'Delete clients'),
        # Employee
        ('employee.view',       'View employees'),
        ('employee.create',     'Create employees'),
        ('employee.update',     'Update employees'),
        ('employee.delete',     'Delete employees'),
        # Subscription
        ('subscription.view',           'View subscriptions'),
        ('subscription.create',         'Create subscriptions'),
        ('subscription.cancel',         'Cancel subscriptions'),
        ('subscription.create_plan',    'Create/update subscription plans'),
        ('subscription.manage_modules', 'Map modules to plans'),
        # Module
        ('module.view',         'View modules'),
        ('module.assign',       'Assign modules to tenants'),
        ('module.revoke',       'Revoke modules from tenants'),
        # Role
        ('role.view',               'View roles'),
        ('role.create',             'Create roles'),
        ('role.update',             'Update roles'),
        ('role.delete',             'Delete roles'),
        ('role.assign_permission',  'Assign permissions to roles'),
    ]

    for code, description in permissions:
        if not PermissionCatalog.query.filter_by(permission_code=code).first():
            db.session.add(PermissionCatalog(permission_code=code, description=description))
            print(f"  ✓ Added permission: {code}")

    db.session.commit()
    print("✓ Permissions seeded")


def seed_roles():
    """Seed Role_Master — idempotent."""
    roles = [
        {'role_name': 'Super Admin',   'role_description': 'Full system access',       'is_system': True},
        {'role_name': 'Admin',         'role_description': 'Administrative access',    'is_system': True},
        {'role_name': 'Tenant Owner',  'role_description': 'Tenant billing owner',     'is_system': True},
        {'role_name': 'Manager',       'role_description': 'Management level access',  'is_system': False},
        {'role_name': 'Sales',         'role_description': 'Sales team access',        'is_system': False},
        {'role_name': 'Viewer',        'role_description': 'Read-only access',         'is_system': False},
    ]

    for role_data in roles:
        if not RoleMaster.query.filter_by(role_name=role_data['role_name']).first():
            db.session.add(RoleMaster(**role_data))
            print(f"  ✓ Added role: {role_data['role_name']}")

    db.session.commit()
    print("✓ Roles seeded")


def seed_role_permissions():
    """Assign all permissions to Super Admin and Admin roles."""
    all_permissions = PermissionCatalog.query.all()

    for role_name in ('Super Admin', 'Admin', 'Tenant Owner'):
        role = RoleMaster.query.filter_by(role_name=role_name).first()
        if not role:
            print(f"  ✗ Role '{role_name}' not found")
            continue

        for perm in all_permissions:
            exists = RolePermissionMapping.query.filter_by(
                role_id=role.role_id, permission_id=perm.permission_id
            ).first()
            if not exists:
                db.session.add(RolePermissionMapping(
                    role_id=role.role_id,
                    permission_id=perm.permission_id,
                ))

        print(f"  ✓ All permissions assigned to {role_name}")

    db.session.commit()
    print("✓ Role-permission mappings seeded")


def seed_system_data():
    """Main entry point — seeds all system configuration tables."""
    print("\n" + "=" * 50)
    print("SEEDING SYSTEM DATA")
    print("=" * 50 + "\n")

    try:
        seed_modules()
        seed_subscription_plans()
        seed_subscription_modules()
        seed_permissions()
        seed_roles()
        seed_role_permissions()

        print("\n" + "=" * 50)
        print("✓ ALL SYSTEM DATA SEEDED SUCCESSFULLY")
        print("=" * 50 + "\n")

    except Exception as e:
        print(f"\n✗ Error seeding system data: {e}")
        db.session.rollback()
        raise


if __name__ == '__main__':
    from app import app

    with app.app_context():
        seed_system_data()