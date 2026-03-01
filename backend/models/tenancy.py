"""
Tenancy and Subscription Models for StreemLyne CRM
Handles multi-tenant architecture, subscriptions, and module management

SCHEMA: StreemLyne_MT
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db


__all__ = [
    'TenantMaster',
    'SubscriptionPlan',
    'ModuleMaster',
    'SubscriptionModuleMapping',
    'TenantModuleMapping',
    'TenantSubscription',
]


# ============================================================
# TENANT MASTER
# ============================================================

class TenantMaster(db.Model):
    """
    Multi-tenant master table.
    Each tenant represents a company/organisation using the system.
    All tenant-scoped data links back here via tenant_id.

    SCHEMA: StreemLyne_MT.Tenant_Master
    """
    __tablename__ = 'Tenant_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    tenant_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_company_name = db.Column(db.String(255), unique=True)
    tenant_contact_name = db.Column(db.String(255))
    onboarding_Date = db.Column(db.Date)
    is_active = db.Column(db.Boolean)                                    # No DB default — nullable in schema
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    # Core relationships
    clients = db.relationship('ClientMaster', back_populates='tenant', lazy='dynamic')
    employees = db.relationship('EmployeeMaster', back_populates='tenant', lazy='dynamic')
    services = db.relationship('ServicesMaster', back_populates='tenant', lazy='dynamic')

    # Tenancy relationships
    subscriptions = db.relationship('TenantSubscription', back_populates='tenant', lazy='dynamic')
    module_mappings = db.relationship('TenantModuleMapping', back_populates='tenant', lazy='dynamic')

    def __repr__(self):
        return f'<TenantMaster {self.tenant_id}: {self.tenant_company_name}>'

    def to_dict(self):
        return {
            'tenant_id': self.tenant_id,
            'tenant_company_name': self.tenant_company_name,
            'tenant_contact_name': self.tenant_contact_name,
            'onboarding_Date': self.onboarding_Date.isoformat() if self.onboarding_Date else None,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================
# SUBSCRIPTION PLANS
# ============================================================

class SubscriptionPlan(db.Model):
    """
    Subscription plans available for tenants.

    billing_cycle values:  1 = Monthly  |  2 = Quarterly  |  3 = Annual

    SCHEMA: StreemLyne_MT.Subscription_Plans
    """
    __tablename__ = 'Subscription_Plans'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    subscription_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    subscription_code = db.Column(db.String(50), unique=True, nullable=False)
    subscription_name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String)                                   # character varying in schema
    is_base_plan = db.Column(db.Boolean, nullable=False)                # NOT NULL, no DB default
    is_active = db.Column(db.Boolean, nullable=False)                   # NOT NULL, no DB default

    # Billing — billing_cycle: 1=Monthly, 2=Quarterly, 3=Annual
    billing_cycle = db.Column(db.SmallInteger, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    currency_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'),
        nullable=False
    )

    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    # Relationships
    currency = db.relationship('CurrencyMaster', backref='subscription_plans')
    module_mappings = db.relationship('SubscriptionModuleMapping', back_populates='subscription', lazy='dynamic')
    tenant_subscriptions = db.relationship('TenantSubscription', back_populates='subscription', lazy='dynamic')

    def __repr__(self):
        return f'<SubscriptionPlan {self.subscription_code}: {self.subscription_name}>'

    def get_billing_cycle_name(self):
        return {1: 'Monthly', 2: 'Quarterly', 3: 'Annual'}.get(self.billing_cycle, 'Unknown')

    def to_dict(self):
        return {
            'subscription_id': self.subscription_id,
            'subscription_code': self.subscription_code,
            'subscription_name': self.subscription_name,
            'description': self.description,
            'is_base_plan': self.is_base_plan,
            'is_active': self.is_active,
            'billing_cycle': self.billing_cycle,
            'billing_cycle_name': self.get_billing_cycle_name(),
            'price': float(self.price) if self.price is not None else None,
            'currency_id': self.currency_id,
            'currency_code': self.currency.currency_code if self.currency else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================
# MODULE MASTER
# ============================================================

class ModuleMaster(db.Model):
    """
    System modules that tenants can subscribe to.
    is_core=True modules are always enabled regardless of subscription.

    SCHEMA: StreemLyne_MT.Module_Master
    """
    __tablename__ = 'Module_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    module_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    module_code = db.Column(db.String(50), unique=True, nullable=False)
    module_name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String)                                   # character varying in schema
    is_core = db.Column(db.Boolean, nullable=False)                     # NOT NULL, no DB default
    is_active = db.Column(db.Boolean, nullable=False)                   # NOT NULL, no DB default
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    # Relationships
    subscription_mappings = db.relationship('SubscriptionModuleMapping', back_populates='module', lazy='dynamic')
    tenant_mappings = db.relationship('TenantModuleMapping', back_populates='module', lazy='dynamic')

    def __repr__(self):
        return f'<ModuleMaster {self.module_code}: {self.module_name}>'

    def to_dict(self):
        return {
            'module_id': self.module_id,
            'module_code': self.module_code,
            'module_name': self.module_name,
            'description': self.description,
            'is_core': self.is_core,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================
# SUBSCRIPTION MODULE MAPPING
# ============================================================

class SubscriptionModuleMapping(db.Model):
    """
    Defines which modules are bundled into each subscription plan.

    NOTE: subscription_id and module_id are BigInteger in the DDL
    to allow room for growth, even though Subscription_Plans and
    Module_Master use SmallInteger PKs.

    SCHEMA: StreemLyne_MT.Subscription_Module_Mapping
    """
    __tablename__ = 'Subscription_Module_Mapping'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    subscription_module_mapping_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    subscription_id = db.Column(
        db.BigInteger,
        db.ForeignKey('StreemLyne_MT.Subscription_Plans.subscription_id'),
        nullable=False
    )
    module_id = db.Column(
        db.BigInteger,
        db.ForeignKey('StreemLyne_MT.Module_Master.module_id'),
        nullable=False
    )
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    subscription = db.relationship('SubscriptionPlan', back_populates='module_mappings')
    module = db.relationship('ModuleMaster', back_populates='subscription_mappings')

    def __repr__(self):
        return f'<SubscriptionModuleMapping Sub:{self.subscription_id} Mod:{self.module_id}>'

    def to_dict(self):
        return {
            'subscription_module_mapping_id': self.subscription_module_mapping_id,
            'subscription_id': self.subscription_id,
            'module_id': self.module_id,
            'module_name': self.module.module_name if self.module else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================
# TENANT MODULE MAPPING
# ============================================================

class TenantModuleMapping(db.Model):
    """
    Tracks which modules are currently active for each tenant.
    Populated automatically when a tenant subscribes to a plan.

    SCHEMA: StreemLyne_MT.Tenant_Module_Mapping
    """
    __tablename__ = 'Tenant_Module_Mapping'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    tenant_module_mapping_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'))
    module_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Module_Master.module_id'))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    tenant = db.relationship('TenantMaster', back_populates='module_mappings')
    module = db.relationship('ModuleMaster', back_populates='tenant_mappings')

    def __repr__(self):
        return f'<TenantModuleMapping Tenant:{self.tenant_id} Mod:{self.module_id}>'

    def to_dict(self):
        return {
            'tenant_module_mapping_id': self.tenant_module_mapping_id,
            'tenant_id': self.tenant_id,
            'module_id': self.module_id,
            'module_code': self.module.module_code if self.module else None,
            'module_name': self.module.module_name if self.module else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================
# TENANT SUBSCRIPTION
# ============================================================

class TenantSubscription(db.Model):
    """
    Maps tenants to their active/historical subscription plans.

    NOTE: tenant_id and subscription_id are BigInteger in the DDL
    to match the parent table references in the schema.

    SCHEMA: StreemLyne_MT.Tenant_Subscription
    """
    __tablename__ = 'Tenant_Subscription'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    tenant_subscription_mapping_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(
        db.BigInteger,
        db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id')
    )
    subscription_id = db.Column(
        db.BigInteger,
        db.ForeignKey('StreemLyne_MT.Subscription_Plans.subscription_id')
    )
    subscription_start_date = db.Column(db.Date)
    subscription_end_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean)                                    # Nullable in schema — no default
    auto_renew = db.Column(db.Boolean)                                   # Nullable in schema — no default
    created_at = db.Column(db.DateTime(timezone=False), nullable=False, default=datetime.utcnow)  # NOT NULL; Python default required (no DB default in schema)
    updated_at = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', back_populates='subscriptions')
    subscription = db.relationship('SubscriptionPlan', back_populates='tenant_subscriptions')

    def __repr__(self):
        return f'<TenantSubscription Tenant:{self.tenant_id} Sub:{self.subscription_id}>'

    def is_currently_active(self):
        """Check if subscription is active and within its date range."""
        if not self.is_active:
            return False
        today = datetime.utcnow().date()
        if self.subscription_start_date and today < self.subscription_start_date:
            return False
        if self.subscription_end_date and today > self.subscription_end_date:
            return False
        return True

    def to_dict(self):
        return {
            'tenant_subscription_mapping_id': self.tenant_subscription_mapping_id,
            'tenant_id': self.tenant_id,
            'subscription_id': self.subscription_id,
            'subscription_name': self.subscription.subscription_name if self.subscription else None,
            'subscription_start_date': self.subscription_start_date.isoformat() if self.subscription_start_date else None,
            'subscription_end_date': self.subscription_end_date.isoformat() if self.subscription_end_date else None,
            'is_active': self.is_active,
            'auto_renew': self.auto_renew,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }