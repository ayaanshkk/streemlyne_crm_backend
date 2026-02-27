# C:\streemlyne_crm_backend\backend\models\tenancy.py
"""
Tenancy and Subscription Models for StreemLyne CRM
Handles multi-tenant architecture, subscriptions, and module management

SCHEMA: StreemLyne_MT
"""

import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db


# ============================================================
# EXPORTS
# ============================================================

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
    Multi-tenant master table
    
    Each tenant represents a company/organization using the system.
    All tenant-specific data links back to this table.
    
    SCHEMA: StreemLyne_MT.Tenant_Master
    """
    __tablename__ = 'Tenant_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}
    
    # Primary Key - SmallInteger as per new schema
    tenant_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    
    # Tenant Information
    tenant_company_name = db.Column(db.String(255), unique=True)
    tenant_contact_name = db.Column(db.String(255))
    
    # Dates
    onboarding_Date = db.Column(db.Date)
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)
    
    # Relationships
    clients = db.relationship('ClientMaster', back_populates='tenant', lazy='dynamic')
    employees = db.relationship('EmployeeMaster', back_populates='tenant', lazy='dynamic')
    services = db.relationship('ServicesMaster', back_populates='tenant', lazy='dynamic')
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
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


# ============================================================
# SUBSCRIPTION PLANS
# ============================================================

class SubscriptionPlan(db.Model):
    """
    Subscription plans available for tenants
    
    SCHEMA: StreemLyne_MT.Subscription_Plans
    """
    __tablename__ = 'Subscription_Plans'
    __table_args__ = {'schema': 'StreemLyne_MT'}
    
    subscription_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    
    # Plan Identification
    subscription_code = db.Column(db.String(50), unique=True, nullable=False)
    subscription_name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    
    # Plan Type
    is_base_plan = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    
    # Billing
    billing_cycle = db.Column(db.SmallInteger, nullable=False)  # 1=Monthly, 2=Quarterly, 3=Annual
    price = db.Column(db.Numeric(10, 2), nullable=False)
    currency_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'), nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)
    
    # Relationships
    currency = db.relationship('CurrencyMaster', backref='subscription_plans')
    module_mappings = db.relationship('SubscriptionModuleMapping', back_populates='subscription', lazy='dynamic')
    tenant_subscriptions = db.relationship('TenantSubscription', back_populates='subscription', lazy='dynamic')
    
    def __repr__(self):
        return f'<SubscriptionPlan {self.subscription_code}: {self.subscription_name}>'
    
    def to_dict(self):
        return {
            'subscription_id': self.subscription_id,
            'subscription_code': self.subscription_code,
            'subscription_name': self.subscription_name,
            'description': self.description,
            'is_base_plan': self.is_base_plan,
            'is_active': self.is_active,
            'billing_cycle': self.billing_cycle,
            'price': float(self.price) if self.price else None,
            'currency_id': self.currency_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


# ============================================================
# MODULE MASTER
# ============================================================

class ModuleMaster(db.Model):
    """
    System modules available for subscription
    
    SCHEMA: StreemLyne_MT.Module_Master
    """
    __tablename__ = 'Module_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}
    
    module_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    
    # Module Identification
    module_code = db.Column(db.String(50), unique=True, nullable=False)
    module_name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    
    # Module Type
    is_core = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    
    # Timestamps
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
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


# ============================================================
# MAPPING TABLES
# ============================================================

class SubscriptionModuleMapping(db.Model):
    """
    Maps which modules are included in each subscription plan
    
    SCHEMA: StreemLyne_MT.Subscription_Module_Mapping
    """
    __tablename__ = 'Subscription_Module_Mapping'
    __table_args__ = {'schema': 'StreemLyne_MT'}
    
    subscription_module_mapping_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    
    # Foreign Keys - Use BigInteger to match schema (schema uses bigint)
    subscription_id = db.Column(db.BigInteger, db.ForeignKey('StreemLyne_MT.Subscription_Plans.subscription_id'), nullable=False)
    module_id = db.Column(db.BigInteger, db.ForeignKey('StreemLyne_MT.Module_Master.module_id'), nullable=False)
    
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    
    # Relationships
    subscription = db.relationship('SubscriptionPlan', back_populates='module_mappings')
    module = db.relationship('ModuleMaster', back_populates='subscription_mappings')
    
    def __repr__(self):
        return f'<SubscriptionModuleMapping Sub:{self.subscription_id} Mod:{self.module_id}>'
    
    def to_dict(self):
        return {
            'subscription_module_mapping_id': self.subscription_module_mapping_id,
            'subscription_id': self.subscription_id,
            'module_id': self.module_id,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class TenantModuleMapping(db.Model):
    """
    Maps which modules are enabled for each tenant
    
    SCHEMA: StreemLyne_MT.Tenant_Module_Mapping
    """
    __tablename__ = 'Tenant_Module_Mapping'
    __table_args__ = {'schema': 'StreemLyne_MT'}
    
    tenant_module_mapping_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'))
    module_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Module_Master.module_id'))
    
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    
    # Relationships
    tenant = db.relationship('TenantMaster', back_populates='module_mappings')
    module = db.relationship('ModuleMaster', back_populates='tenant_mappings')
    
    def __repr__(self):
        return f'<TenantModuleMapping Tenant:{self.tenant_id} Mod:{self.module_id}>'
    
    def to_dict(self):
        return {
            'tenant_module_mapping_id': self.tenant_module_mapping_id,
            'tenant_id': self.tenant_id,
            'module_id': self.module_id,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class TenantSubscription(db.Model):
    """
    Tenant subscription history and current subscription
    
    SCHEMA: StreemLyne_MT.Tenant_Subscription
    """
    __tablename__ = 'Tenant_Subscription'
    __table_args__ = {'schema': 'StreemLyne_MT'}
    
    tenant_subscription_mapping_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    
    # Foreign Keys - Use BigInteger to match schema (schema uses bigint)
    tenant_id = db.Column(db.BigInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'))
    subscription_id = db.Column(db.BigInteger, db.ForeignKey('StreemLyne_MT.Subscription_Plans.subscription_id'))
    
    # Subscription Period
    subscription_start_date = db.Column(db.Date)
    subscription_end_date = db.Column(db.Date)
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    auto_renew = db.Column(db.Boolean, default=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime(timezone=False), nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)
    
    # Relationships
    tenant = db.relationship('TenantMaster', back_populates='subscriptions')
    subscription = db.relationship('SubscriptionPlan', back_populates='tenant_subscriptions')
    
    def __repr__(self):
        return f'<TenantSubscription Tenant:{self.tenant_id} Sub:{self.subscription_id}>'
    
    def to_dict(self):
        return {
            'tenant_subscription_mapping_id': self.tenant_subscription_mapping_id,
            'tenant_id': self.tenant_id,
            'subscription_id': self.subscription_id,
            'subscription_start_date': self.subscription_start_date.isoformat() if self.subscription_start_date else None,
            'subscription_end_date': self.subscription_end_date.isoformat() if self.subscription_end_date else None,
            'is_active': self.is_active,
            'auto_renew': self.auto_renew,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
