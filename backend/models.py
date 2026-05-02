"""
StreemLyne CRM - Unified Models Module

All SQLAlchemy models for the StreemLyne CRM system in a single file.
Organized by functional area for maintainability.

SCHEMA: StreemLyne_MT (multi-tenant schema)

SECTIONS:
    1. Tenancy & Subscriptions
    2. Master/Reference Data
    3. Core Business Models
    4. Proposals & Invoices
    5. Documents, Activities, Chat & Audit
    6. Assignments & Scheduling

CHANGES vs previous version
─────────────────────────────────────────────────────────────────────────────
[SUBSCRIPTION-001] TenantMaster.tenant_id
    SmallInteger (autoincrement) → String
    Matches schema: Tenant_Master.tenant_id character varying PRIMARY KEY.
    String IDs like "acme-001" are the canonical form used by the DB, the
    frontend (useTenantConfig), and every FK in the SQL schema.

[SUBSCRIPTION-002] TenantMaster.stripe_customer_id
    Column added (was mapped in SQL but missing from ORM).

[SUBSCRIPTION-003] SubscriptionPlan.billing_cycle semantics normalised
    1 = Monthly | 3 = Quarterly | 12 = Annual
    (Previous comment said 1/2/3; subscription_service.py treats 12 as annual,
    so 2 was a dead value. Now consistent with the service layer.)

[SUBSCRIPTION-004] SubscriptionPlan.stripe_price_id
    Column added (was in SQL schema but missing from ORM).
    Null for the Custom plan — Custom is provisioned manually with no Stripe link.

[SUBSCRIPTION-005] TenantSubscription.tenant_id
    BigInteger → String  (matches schema FK to Tenant_Master.tenant_id varchar)

[SUBSCRIPTION-006] TenantSubscription.status
    Column added as Enum('trialing','active','expired','canceled').
    Maps to the existing DB type StreemLyne_MT.subscription_status_enum.
    create_type=False prevents SQLAlchemy from trying to CREATE the type.

[SUBSCRIPTION-007] TenantSubscription.trial_end_date
    Column added (timestamp with time zone, nullable).

[SUBSCRIPTION-008] TenantSubscription.stripe_subscription_id
    Column added (varchar unique, nullable until Stripe checkout completes).

[SUBSCRIPTION-009] TenantSubscription.is_currently_active()
    Now also gates on status — trialing and active allow access;
    expired and canceled block access regardless of date range.

[SUBSCRIPTION-010] tenant_id FK type corrected to String on every model
    that carries a FK to Tenant_Master:
      TenantModuleMapping, EmployeeMaster, ServicesMaster, ClientMaster,
      CustomerAuth, OpportunityDetails, CaseDocuments, Activity,
      OpportunityNote, DocumentTemplate, FormSubmission, CustomerFormData,
      DataImport, AuditLog, VersionedSnapshot, ChatConversation,
      ChatMessage, ChatHistory, Assignment.
─────────────────────────────────────────────────────────────────────────────
"""

import sys
import os
import uuid
from datetime import datetime, date, timezone
from typing import cast
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import Enum as SAEnum, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db


# ============================================================================
# SECTION 1: TENANCY & SUBSCRIPTIONS
# ============================================================================

class TenantMaster(db.Model):
    """
    Multi-tenant master table.
    Each tenant represents a company/organisation using the system.
    All tenant-scoped data links back here via tenant_id.

    tenant_id is a human-readable string slug (e.g. "acme-001") — NOT an
    auto-increment integer.  This matches the DB schema (character varying PK)
    and the frontend hook useTenantConfig which already uses string IDs.
    """
    __tablename__ = 'Tenant_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    # [SUBSCRIPTION-001] was db.SmallInteger with autoincrement=True
    tenant_id            = db.Column(db.String, primary_key=True)
    tenant_company_name  = db.Column(db.String(255), unique=True)
    tenant_contact_name  = db.Column(db.String(255))
    onboarding_Date      = db.Column(db.Date)
    is_active            = db.Column(db.Boolean)
    created_at           = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    updated_at           = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)
    # [SUBSCRIPTION-002] was missing from ORM despite being in SQL schema
    stripe_customer_id   = db.Column(db.String(255), unique=True)

    # Relationships
    clients          = db.relationship('ClientMaster', back_populates='tenant', lazy='dynamic')
    employees        = db.relationship('EmployeeMaster', back_populates='tenant', lazy='dynamic')
    services         = db.relationship('ServicesMaster', back_populates='tenant', lazy='dynamic')
    subscriptions    = db.relationship('TenantSubscription', back_populates='tenant', lazy='dynamic')
    module_mappings  = db.relationship('TenantModuleMapping', back_populates='tenant', lazy='dynamic')

    def __repr__(self):
        return f'<TenantMaster {self.tenant_id}: {self.tenant_company_name}>'

    def to_dict(self):
        return {
            'tenant_id':           self.tenant_id,
            'tenant_company_name': self.tenant_company_name,
            'tenant_contact_name': self.tenant_contact_name,
            'onboarding_Date':     self.onboarding_Date.isoformat() if self.onboarding_Date else None,
            'is_active':           self.is_active,
            # [SUBSCRIPTION-002] included in serialisation
            'stripe_customer_id':  self.stripe_customer_id,
            'created_at':          self.created_at.isoformat() if self.created_at else None,
            'updated_at':          self.updated_at.isoformat() if self.updated_at else None,
        }


class SubscriptionPlan(db.Model):
    """
    Subscription plans available for tenants.

    billing_cycle values:
        1  = Monthly
        3  = Quarterly
        12 = Annual
    (Previously documented as 1/2/3; normalised to match subscription_service.py
    which already treats 12 as annual.  Value 2 was unused.)

    stripe_price_id is populated for Starter and Pro plans only.
    It is intentionally NULL for the Custom plan, which is provisioned
    manually by the sales team and has no Stripe Checkout flow.
    """
    __tablename__ = 'Subscription_Plans'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    subscription_id   = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    subscription_code = db.Column(db.String(50), unique=True, nullable=False)
    subscription_name = db.Column(db.String(100), unique=True, nullable=False)
    description       = db.Column(db.String)
    is_base_plan      = db.Column(db.Boolean, nullable=False)
    is_active         = db.Column(db.Boolean, nullable=False)
    # [SUBSCRIPTION-003] billing_cycle: 1=Monthly, 3=Quarterly, 12=Annual
    billing_cycle     = db.Column(db.SmallInteger, nullable=False)
    price             = db.Column(db.Numeric(10, 2), nullable=False)
    currency_id       = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'),
        nullable=False,
    )
    created_at        = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    updated_at        = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)
    # [SUBSCRIPTION-004] was in SQL schema but missing from ORM; null for Custom plan
    stripe_price_id   = db.Column(db.String(255))

    # Relationships
    currency            = db.relationship('CurrencyMaster', backref='subscription_plans')
    module_mappings     = db.relationship('SubscriptionModuleMapping', back_populates='subscription', lazy='dynamic')
    tenant_subscriptions = db.relationship('TenantSubscription', back_populates='subscription', lazy='dynamic')

    def __repr__(self):
        return f'<SubscriptionPlan {self.subscription_code}: {self.subscription_name}>'

    def get_billing_cycle_name(self):
        # [SUBSCRIPTION-003] was {1:'Monthly', 2:'Quarterly', 3:'Annual'}
        return {1: 'Monthly', 3: 'Quarterly', 12: 'Annual'}.get(self.billing_cycle, 'Unknown')

    def to_dict(self):
        return {
            'subscription_id':   self.subscription_id,
            'subscription_code': self.subscription_code,
            'subscription_name': self.subscription_name,
            'description':       self.description,
            'is_base_plan':      self.is_base_plan,
            'is_active':         self.is_active,
            'billing_cycle':     self.billing_cycle,
            'billing_cycle_name': self.get_billing_cycle_name(),
            'price':             float(self.price) if self.price is not None else None,
            'currency_id':       self.currency_id,
            'currency_code':     self.currency.currency_code if self.currency else None,
            # [SUBSCRIPTION-004] included in serialisation
            'stripe_price_id':   self.stripe_price_id,
            'created_at':        self.created_at.isoformat() if self.created_at else None,
            'updated_at':        self.updated_at.isoformat() if self.updated_at else None,
        }


# Backward-compatibility alias
SubscriptionPlans = SubscriptionPlan


class ModuleMaster(db.Model):
    """
    System modules that tenants can subscribe to.
    is_core=True modules are always enabled regardless of subscription.
    """
    __tablename__ = 'Module_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    module_id   = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    module_code = db.Column(db.String(50), unique=True, nullable=False)
    module_name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String)
    is_core     = db.Column(db.Boolean, nullable=False)
    is_active   = db.Column(db.Boolean, nullable=False)
    created_at  = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    # Relationships
    subscription_mappings = db.relationship('SubscriptionModuleMapping', back_populates='module', lazy='dynamic')
    tenant_mappings       = db.relationship('TenantModuleMapping', back_populates='module', lazy='dynamic')

    def __repr__(self):
        return f'<ModuleMaster {self.module_code}: {self.module_name}>'

    def to_dict(self):
        return {
            'module_id':   self.module_id,
            'module_code': self.module_code,
            'module_name': self.module_name,
            'description': self.description,
            'is_core':     self.is_core,
            'is_active':   self.is_active,
            'created_at':  self.created_at.isoformat() if self.created_at else None,
            'updated_at':  self.updated_at.isoformat() if self.updated_at else None,
        }


class SubscriptionModuleMapping(db.Model):
    """Defines which modules are bundled into each subscription plan."""
    __tablename__ = 'Subscription_Module_Mapping'
    __table_args__ = (
        db.UniqueConstraint('subscription_id', 'module_id', name='uq_subscription_module'),
        db.Index('ix_subscription_module_mapping_subscription_id', 'subscription_id'),
        db.Index('ix_subscription_module_mapping_module_id', 'module_id'),
        {'schema': 'StreemLyne_MT'},
    )

    subscription_module_mapping_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    subscription_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Subscription_Plans.subscription_id'),
        nullable=False,
    )
    module_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Module_Master.module_id'),
        nullable=False,
    )
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    subscription = db.relationship('SubscriptionPlan', back_populates='module_mappings')
    module       = db.relationship('ModuleMaster', back_populates='subscription_mappings')

    def __repr__(self):
        return f'<SubscriptionModuleMapping Sub:{self.subscription_id} Mod:{self.module_id}>'

    def to_dict(self):
        return {
            'subscription_module_mapping_id': self.subscription_module_mapping_id,
            'subscription_id': self.subscription_id,
            'module_id':       self.module_id,
            'module_name':     self.module.module_name if self.module else None,
            'created_at':      self.created_at.isoformat() if self.created_at else None,
        }


class TenantModuleMapping(db.Model):
    """Tracks which modules are currently active for each tenant."""
    __tablename__ = 'Tenant_Module_Mapping'
    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'module_id', name='uq_tenant_module'),
        db.Index('ix_tenant_module_mapping_tenant_id', 'tenant_id'),
        db.Index('ix_tenant_module_mapping_module_id', 'module_id'),
        {'schema': 'StreemLyne_MT'},
    )

    tenant_module_mapping_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    # [SUBSCRIPTION-010] was db.SmallInteger
    tenant_id = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'))
    module_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Module_Master.module_id'))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    tenant = db.relationship('TenantMaster', back_populates='module_mappings')
    module = db.relationship('ModuleMaster', back_populates='tenant_mappings')

    def __repr__(self):
        return f'<TenantModuleMapping Tenant:{self.tenant_id} Mod:{self.module_id}>'

    def to_dict(self):
        return {
            'tenant_module_mapping_id': self.tenant_module_mapping_id,
            'tenant_id':   self.tenant_id,
            'module_id':   self.module_id,
            'module_code': self.module.module_code if self.module else None,
            'module_name': self.module.module_name if self.module else None,
            'created_at':  self.created_at.isoformat() if self.created_at else None,
        }


class TenantSubscription(db.Model):
    """
    Maps tenants to their active/historical subscription plans.

    Lifecycle states (status column):
        trialing  — 7-day free trial, auto-created on tenant creation
        active    — paid subscription confirmed via Stripe webhook
        expired   — trial ended or retries exhausted with no recovery
        canceled  — subscription ended; access blocked after billing period

    Access rule (enforced by middleware):
        status in ('trialing', 'active')             → allow
        status in ('expired', 'canceled')            → block, redirect to /subscription-required
    """
    __tablename__ = 'Tenant_Subscription'
    __table_args__ = (
        db.Index('ix_tenant_subscription_tenant_id', 'tenant_id'),
        db.Index('ix_tenant_subscription_is_active', 'is_active'),
        db.Index('ix_tenant_subscription_subscription_end_date', 'subscription_end_date'),
        db.Index('idx_tenant_subscription_status', 'tenant_id', 'status'),
        db.Index('idx_tenant_subscription_trial_end', 'tenant_id', 'trial_end_date'),
        db.Index(
            'idx_tenant_subscription_access_gate',
            'tenant_id',
            'status',
            'trial_end_date',
        ),
        {'schema': 'StreemLyne_MT'},
    )

    tenant_subscription_mapping_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    # [SUBSCRIPTION-005] was db.BigInteger
    tenant_id         = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'))
    subscription_id   = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Subscription_Plans.subscription_id'))
    subscription_start_date = db.Column(db.Date)
    subscription_end_date   = db.Column(db.Date)
    is_active   = db.Column(db.Boolean)
    auto_renew  = db.Column(db.Boolean)
    created_at  = db.Column(db.DateTime(timezone=False), nullable=False, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    # [SUBSCRIPTION-006] Maps to existing DB type StreemLyne_MT.subscription_status_enum.
    # create_type=False: SQLAlchemy must NOT try to CREATE the type — it already exists.
    status = db.Column(
        SAEnum(
            'trialing', 'active', 'expired', 'canceled',
            name='subscription_status_enum',
            schema='StreemLyne_MT',
            create_type=False,
        ),
        nullable=False,
        default='trialing',
    )
    # [SUBSCRIPTION-007] timestamp with time zone — populated on trial creation
    trial_end_date = db.Column(db.DateTime(timezone=True))
    # [SUBSCRIPTION-008] populated by checkout.session.completed webhook; null until then
    stripe_subscription_id = db.Column(db.String(255), unique=True)
    cancel_at_period_end = db.Column(db.Boolean, default=False)
    current_period_start = db.Column(db.DateTime(timezone=False))
    current_period_end   = db.Column(db.DateTime(timezone=False))
    tenant       = db.relationship('TenantMaster', back_populates='subscriptions')
    subscription = db.relationship('SubscriptionPlan', back_populates='tenant_subscriptions')

    def __repr__(self):
        return f'<TenantSubscription Tenant:{self.tenant_id} Sub:{self.subscription_id} [{self.status}]>'

    def is_currently_active(self):
        """
        Return True only when the tenant should have full app access.

        [SUBSCRIPTION-009] Previously only checked is_active flag and date range.
        Now also gates on status so that expired/canceled subscriptions whose
        is_active flag was not yet cleared are still correctly blocked.
        """
        if self.status not in ('trialing', 'active'):
            return False

        if not self.is_active:
            return False

        now = datetime.now(timezone.utc)
        today = now.date()

        def _as_utc(dt_value):
            if dt_value is None:
                return None
            if dt_value.tzinfo is None:
                return dt_value.replace(tzinfo=timezone.utc)
            return dt_value.astimezone(timezone.utc)

        if self.status == 'trialing' and self.trial_end_date:
            if now > _as_utc(self.trial_end_date): # type: ignore
                return False

        if self.current_period_start and now < _as_utc(self.current_period_start): # pyright: ignore[reportOperatorIssue]
            return False
        if self.current_period_end and now > _as_utc(self.current_period_end): # pyright: ignore[reportOperatorIssue]
            return False
        if self.subscription_start_date and today < self.subscription_start_date:
            return False
        if self.subscription_end_date and today > self.subscription_end_date:
            return False

        return True

    def days_remaining_in_trial(self):
        """
        Return the number of whole days left in the trial, or None if not trialing.
        Useful for the trial banner ("Your trial ends in X days").
        """
        if self.status != 'trialing' or not self.trial_end_date:
            return None
        from datetime import timezone
        now = datetime.now(timezone.utc)
        delta = self.trial_end_date - now
        return max(0, delta.days)

    def to_dict(self):
        return {
            'tenant_subscription_mapping_id': self.tenant_subscription_mapping_id,
            'tenant_id':              self.tenant_id,
            'subscription_id':        self.subscription_id,
            'subscription_name':      self.subscription.subscription_name if self.subscription else None,
            'subscription_start_date': self.subscription_start_date.isoformat() if self.subscription_start_date else None,
            'subscription_end_date':   self.subscription_end_date.isoformat() if self.subscription_end_date else None,
            'is_active':              self.is_active,
            'auto_renew':             self.auto_renew,
            # [SUBSCRIPTION-006, 007, 008] now included in serialisation
            'status':                 self.status,
            'trial_end_date':         self.trial_end_date.isoformat() if self.trial_end_date else None,
            'days_remaining_in_trial': self.days_remaining_in_trial(),
            'stripe_subscription_id': self.stripe_subscription_id,
            'cancel_at_period_end': self.cancel_at_period_end,
            'current_period_start': self.current_period_start.isoformat() if self.current_period_start else None,
            'current_period_end':   self.current_period_end.isoformat() if self.current_period_end else None,
            'created_at':             self.created_at.isoformat() if self.created_at else None,
            'updated_at':             self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================================
# SECTION 2: MASTER/REFERENCE DATA
# ============================================================================

class CountryMaster(db.Model):
    """ISO country reference data."""
    __tablename__ = 'Country_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    country_id      = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    country_name    = db.Column(db.String(100), nullable=False, unique=True, index=True)
    country_isd_code = db.Column(db.String(10), nullable=False)
    created_at      = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<CountryMaster {self.country_name}>'

    def to_dict(self):
        return {
            'country_id':       self.country_id,
            'country_name':     self.country_name,
            'country_isd_code': self.country_isd_code,
            'created_at':       self.created_at.isoformat() if self.created_at else None,
        }


class CurrencyMaster(db.Model):
    """ISO currency reference data."""
    __tablename__ = 'Currency_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    currency_id   = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    currency_name = db.Column(db.String(100))
    currency_code = db.Column(db.String(10))
    created_at    = db.Column(db.DateTime(timezone=False))

    def __repr__(self):
        return f'<CurrencyMaster {self.currency_code}>'

    def format_amount(self, amount):
        return f'{self.currency_code} {amount:,.2f}'

    def to_dict(self):
        return {
            'currency_id':   self.currency_id,
            'currency_name': self.currency_name,
            'currency_code': self.currency_code,
            'created_at':    self.created_at.isoformat() if self.created_at else None,
        }


class DesignationMaster(db.Model):
    """Employee job-title/designation catalogue."""
    __tablename__ = 'Designation_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    designation_id          = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    designation_description = db.Column(db.String(100), nullable=False, unique=True)
    created_at              = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<DesignationMaster {self.designation_description}>'

    def to_dict(self):
        return {
            'designation_id':          self.designation_id,
            'designation_description': self.designation_description,
            'created_at':              self.created_at.isoformat() if self.created_at else None,
        }


class ServicesMaster(db.Model):
    """Tenant-scoped product/service catalogue."""
    __tablename__ = 'Services_Master'
    __table_args__ = (
        db.Index('idx_service_tenant_dates', 'tenant_id', 'date_from', 'date_to'),
        db.Index('idx_service_code_tenant', 'service_code', 'tenant_id'),
        {'schema': 'StreemLyne_MT'},
    )

    service_id          = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    # [SUBSCRIPTION-010] was db.SmallInteger
    tenant_id           = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    service_code        = db.Column(db.String(50), nullable=False)
    service_title       = db.Column(db.String(255), nullable=False)
    service_description = db.Column(db.String)
    service_rate        = db.Column(db.Float(precision=24))
    currency_id         = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'))
    supplier_id         = db.Column(db.SmallInteger)
    date_from           = db.Column(db.Date)
    date_to             = db.Column(db.Date)
    created_at          = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    tenant   = db.relationship('TenantMaster', back_populates='services')
    currency = db.relationship('CurrencyMaster', backref='services')

    def __repr__(self):
        return f'<ServicesMaster {self.service_code}: {self.service_title}>'

    def is_active(self, check_date=None):
        if check_date is None:
            check_date = datetime.utcnow().date()
        if self.date_from and check_date < self.date_from:
            return False
        if self.date_to and check_date > self.date_to:
            return False
        return True

    def to_dict(self):
        return {
            'service_id':          self.service_id,
            'tenant_id':           self.tenant_id,
            'service_code':        self.service_code,
            'service_title':       self.service_title,
            'service_description': self.service_description,
            'service_rate':        self.service_rate,
            'currency_id':         self.currency_id,
            'currency_code':       self.currency.currency_code if self.currency else None,
            'supplier_id':         self.supplier_id,
            'date_from':           self.date_from.isoformat() if self.date_from else None,
            'date_to':             self.date_to.isoformat() if self.date_to else None,
            'is_active':           self.is_active(),
            'created_at':          self.created_at.isoformat() if self.created_at else None,
        }


class UOMMaster(db.Model):
    """Unit-of-measure catalogue (kg, kWh, hours, etc.)."""
    __tablename__ = 'UOM_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    uom_id          = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    uom_description = db.Column(db.String(50), nullable=False, unique=True)
    created_at      = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<UOMMaster {self.uom_description}>'

    def to_dict(self):
        return {
            'uom_id':          self.uom_id,
            'uom_description': self.uom_description,
            'created_at':      self.created_at.isoformat() if self.created_at else None,
        }


class StageMaster(db.Model):
    """
    Workflow stage catalogue for opportunity/project pipelines.
    stage_type values: 1 = Opportunity | 2 = Project | 3 = General
    """
    __tablename__ = 'Stage_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    stage_id           = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    stage_name         = db.Column(db.String(100), nullable=False, unique=True)
    stage_description  = db.Column(db.String)
    preceding_stage_id = db.Column(db.SmallInteger)
    stage_type         = db.Column(db.SmallInteger, nullable=False)

    # Relationships
    opportunities = db.relationship('OpportunityDetails', back_populates='stage')

    def __repr__(self):
        return f'<StageMaster {self.stage_name}>'

    def get_stage_type_name(self):
        return {1: 'Opportunity', 2: 'Project', 3: 'General'}.get(self.stage_type, 'Unknown')

    def to_dict(self):
        return {
            'stage_id':           self.stage_id,
            'stage_name':         self.stage_name,
            'stage_description':  self.stage_description,
            'preceding_stage_id': self.preceding_stage_id,
            'stage_type':         self.stage_type,
            'stage_type_name':    self.get_stage_type_name(),
        }


class SupplierMaster(db.Model):
    """
    External supplier/vendor catalogue.
    supplier_provisions: 1=Energy | 2=Equipment | 3=Service | 4=Other
    """
    __tablename__ = 'Supplier_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    supplier_id           = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    supplier_company_name = db.Column(db.String(255), nullable=False)
    supplier_contact_name = db.Column(db.String(255))
    supplier_provisions   = db.Column(db.SmallInteger)
    created_at            = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<SupplierMaster {self.supplier_company_name}>'

    def get_provisions_name(self):
        return {
            1: 'Energy Supplier',
            2: 'Equipment Supplier',
            3: 'Service Provider',
            4: 'Other',
        }.get(self.supplier_provisions, 'Unknown')

    def to_dict(self):
        return {
            'supplier_id':           self.supplier_id,
            'supplier_company_name': self.supplier_company_name,
            'supplier_contact_name': self.supplier_contact_name,
            'supplier_provisions':   self.supplier_provisions,
            'supplier_provisions_name': self.get_provisions_name(),
            'created_at':            self.created_at.isoformat() if self.created_at else None,
        }


class RoleMaster(db.Model):
    """RBAC role catalogue. is_system=True roles are built-in."""
    __tablename__ = 'Role_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    role_id          = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    role_name        = db.Column(db.String(100), nullable=False, unique=True)
    role_description = db.Column(db.String)
    is_system        = db.Column(db.Boolean, nullable=False)
    created_at       = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    # Relationships
    role_permission_mappings = db.relationship(
        'RolePermissionMapping', back_populates='role',
        lazy='dynamic', cascade='all, delete-orphan',
    )

    def __repr__(self):
        return f'<RoleMaster {self.role_name}>'

    def get_permission_codes(self) -> list:
        return [rpm.permission.permission_code for rpm in self.role_permission_mappings.all() if rpm.permission]

    def to_dict(self):
        return {
            'role_id':          self.role_id,
            'role_name':        self.role_name,
            'role_description': self.role_description,
            'is_system':        self.is_system,
            'created_at':       self.created_at.isoformat() if self.created_at else None,
        }


class PermissionCatalog(db.Model):
    """System-wide permission catalogue."""
    __tablename__ = 'Permission_Catalog'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    permission_id   = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    permission_code = db.Column(db.String(100), nullable=False, unique=True)
    description     = db.Column(db.String)
    created_at      = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    # Relationships
    permission_role_mappings = db.relationship('RolePermissionMapping', back_populates='permission', lazy='dynamic')

    def __repr__(self):
        return f'<PermissionCatalog {self.permission_code}>'

    def to_dict(self):
        return {
            'permission_id':   self.permission_id,
            'permission_code': self.permission_code,
            'description':     self.description,
            'created_at':      self.created_at.isoformat() if self.created_at else None,
        }


class RolePermissionMapping(db.Model):
    """Joins roles to their granted permissions."""
    __tablename__ = 'Role_Permission_Mapping'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    role_permission_mapping_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    role_id       = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Role_Master.role_id'), nullable=False)
    permission_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Permission_Catalog.permission_id'), nullable=False)
    created_at    = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    edited_at     = db.Column(db.Date)

    role       = db.relationship('RoleMaster', back_populates='role_permission_mappings')
    permission = db.relationship('PermissionCatalog', back_populates='permission_role_mappings')

    def __repr__(self):
        return f'<RolePermissionMapping Role:{self.role_id} Perm:{self.permission_id}>'

    def to_dict(self):
        return {
            'role_permission_mapping_id': self.role_permission_mapping_id,
            'role_id':        self.role_id,
            'role_name':      self.role.role_name if self.role else None,
            'permission_id':  self.permission_id,
            'permission_code': self.permission.permission_code if self.permission else None,
            'created_at':     self.created_at.isoformat() if self.created_at else None,
            'edited_at':      self.edited_at.isoformat() if self.edited_at else None,
        }


class TaxMaster(db.Model):
    """Tax rates for proposals and invoices."""
    __tablename__ = 'Tax_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    tax_id          = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tax_name        = db.Column(db.String(100), nullable=False)
    tax_rate        = db.Column(db.Numeric(5, 2), nullable=False)
    tax_description = db.Column(db.String(255))
    is_active       = db.Column(db.Boolean, nullable=False, default=True)
    created_at      = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<TaxMaster {self.tax_name} ({self.tax_rate}%)>'

    def to_dict(self):
        return {
            'tax_id':          self.tax_id,
            'tax_name':        self.tax_name,
            'tax_rate':        float(self.tax_rate) if self.tax_rate else 0,
            'tax_description': self.tax_description,
            'is_active':       self.is_active,
            'created_at':      self.created_at.isoformat() if self.created_at else None,
        }


class ContactMethodMaster(db.Model):
    """Contact methods for client interactions."""
    __tablename__ = 'Contact_Method_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    contact_method_id   = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    method_name         = db.Column(db.String(50), nullable=False, unique=True)
    method_description  = db.Column(db.String(255))
    is_active           = db.Column(db.Boolean, nullable=False, default=True)
    created_at          = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<ContactMethodMaster {self.method_name}>'

    def to_dict(self):
        return {
            'contact_method_id':  self.contact_method_id,
            'method_name':        self.method_name,
            'method_description': self.method_description,
            'is_active':          self.is_active,
            'created_at':         self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================================
# SECTION 3: CORE BUSINESS MODELS
# ============================================================================

class ClientMaster(db.Model):
    """Tenant-scoped client (company) records."""
    __tablename__ = 'Client_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    client_id          = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    # [SUBSCRIPTION-010] was db.SmallInteger
    tenant_id          = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    country_id         = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Country_Master.country_id'))
    default_currency_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'))
    client_company_name = db.Column(db.String(255), nullable=False)
    client_contact_name = db.Column(db.String(255))
    address            = db.Column(db.String)
    post_code          = db.Column(db.String(20))
    client_phone       = db.Column(db.String(50))
    client_email       = db.Column(db.String(255))
    client_website     = db.Column(db.String(255))
    created_at         = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    stage              = db.Column(db.String(50), nullable=True)

    # Relationships
    tenant           = db.relationship('TenantMaster', back_populates='clients')
    country          = db.relationship('CountryMaster', backref='clients')
    default_currency = db.relationship('CurrencyMaster', backref='default_currency_clients')
    opportunities    = db.relationship('OpportunityDetails', back_populates='client', lazy='dynamic')
    interactions     = db.relationship('ClientInteractions', back_populates='client', lazy='dynamic')
    projects         = db.relationship('ProjectDetails', back_populates='client', lazy='dynamic')
    proposals        = db.relationship('ProposalMaster', back_populates='client', lazy='dynamic')
    invoices         = db.relationship('InvoiceMaster', back_populates='client', lazy='dynamic')
    customer_auths   = db.relationship('CustomerAuth', back_populates='client', lazy='dynamic')
    case_documents   = db.relationship('CaseDocuments', back_populates='client', lazy='dynamic')
    customer_documents = db.relationship('CustomerDocuments', back_populates='client', lazy='dynamic')

    def __repr__(self):
        return f'<ClientMaster {self.client_id}: {self.client_company_name}>'

    def to_dict(self):
        return {
            'client_id':            self.client_id,
            'tenant_id':            self.tenant_id,
            'client_company_name':  self.client_company_name,
            'client_contact_name':  self.client_contact_name,
            'address':              self.address,
            'country_id':           self.country_id,
            'country_name':         self.country.country_name if self.country else None,
            'post_code':            self.post_code,
            'client_phone':         self.client_phone,
            'client_email':         self.client_email,
            'client_website':       self.client_website,
            'default_currency_id':  self.default_currency_id,
            'default_currency_code': self.default_currency.currency_code if self.default_currency else None,
            'created_at':           self.created_at.isoformat() if self.created_at else None,
            'stage':                self.stage,
        }


class ClientInteractions(db.Model):
    """
    Log of all contact events with a client.
    contact_method: 1=Phone | 2=Email | 3=In-person | 4=Other
    """
    __tablename__ = 'Client_Interactions'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    interaction_id  = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    client_id       = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=False)
    contact_date    = db.Column(db.Date, nullable=False)
    contact_method  = db.Column(db.SmallInteger, nullable=False)
    notes           = db.Column(db.String)
    next_steps      = db.Column(db.String)
    reminder_date   = db.Column(db.Date)
    created_at      = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    client = db.relationship('ClientMaster', back_populates='interactions')

    def __repr__(self):
        return f'<ClientInteractions {self.interaction_id} for Client {self.client_id}>'

    def get_contact_method_name(self):
        return {1: 'Phone', 2: 'Email', 3: 'In-person', 4: 'Other'}.get(self.contact_method, 'Unknown')

    def to_dict(self):
        return {
            'interaction_id':     self.interaction_id,
            'client_id':          self.client_id,
            'contact_date':       self.contact_date.isoformat() if self.contact_date else None,
            'contact_method':     self.contact_method,
            'contact_method_name': self.get_contact_method_name(),
            'notes':              self.notes,
            'next_steps':         self.next_steps,
            'reminder_date':      self.reminder_date.isoformat() if self.reminder_date else None,
            'created_at':         self.created_at.isoformat() if self.created_at else None,
        }


class EmployeeMaster(db.Model):
    """Tenant-scoped employee records."""
    __tablename__ = 'Employee_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    employee_id             = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    # [SUBSCRIPTION-010] was db.BigInteger
    tenant_id               = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    employee_designation_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Designation_Master.designation_id'))
    employee_name           = db.Column(db.String(255), nullable=False)
    phone                   = db.Column(db.String(50))
    email                   = db.Column(db.String(255), unique=True)
    date_of_birth           = db.Column(db.Date)
    date_of_joining         = db.Column(db.Date)
    id_type                 = db.Column(db.String(50))
    id_number               = db.Column(db.String(100))
    role_ids                = db.Column(db.String(255))
    commission_percentage   = db.Column(db.Float(precision=24))
    created_on              = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    updated_on              = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    # Relationships
    tenant              = db.relationship('TenantMaster', back_populates='employees')
    designation         = db.relationship('DesignationMaster', backref='employees')
    owned_opportunities = db.relationship('OpportunityDetails', foreign_keys='OpportunityDetails.opportunity_owner_employee_id', back_populates='opportunity_owner')
    assigned_opportunities = db.relationship('OpportunityDetails', foreign_keys='OpportunityDetails.assigned_to_employee_id', back_populates='assigned_employee')
    managed_projects    = db.relationship('ProjectDetails', back_populates='employee')
    energy_contracts    = db.relationship('EnergyContractMaster', back_populates='employee')
    user                = db.relationship('UserMaster', back_populates='employee', uselist=False)

    def __repr__(self):
        return f'<EmployeeMaster {self.employee_id}: {self.employee_name}>'

    def get_roles(self) -> list:
        if not self.role_ids:
            return []
        try:
            return [int(rid.strip()) for rid in self.role_ids.split(',') if rid.strip()]
        except (ValueError, AttributeError):
            return []

    def add_role(self, role_id: int) -> None:
        current = self.get_roles()
        if role_id not in current:
            current.append(role_id)
            self.role_ids = ','.join(map(str, current))

    def remove_role(self, role_id: int) -> None:
        current = self.get_roles()
        if role_id in current:
            current.remove(role_id)
            self.role_ids = ','.join(map(str, current)) if current else None

    def to_dict(self):
        return {
            'employee_id':            self.employee_id,
            'tenant_id':              self.tenant_id,
            'employee_name':          self.employee_name,
            'employee_designation_id': self.employee_designation_id,
            'designation_name':       self.designation.designation_description if self.designation else None,
            'phone':                  self.phone,
            'email':                  self.email,
            'date_of_birth':          self.date_of_birth.isoformat() if self.date_of_birth else None,
            'date_of_joining':        self.date_of_joining.isoformat() if self.date_of_joining else None,
            'id_type':                self.id_type,
            'id_number':              self.id_number,
            'role_ids':               self.role_ids,
            'commission_percentage':  self.commission_percentage,
            'created_on':             self.created_on.isoformat() if self.created_on else None,
            'updated_on':             self.updated_on.isoformat() if self.updated_on else None,
        }


class UserMaster(db.Model):
    """Internal portal login accounts, linked 1:1 to EmployeeMaster."""
    __tablename__ = 'User_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    user_id     = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    employee_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'))
    user_name   = db.Column(db.String(100), unique=True)
    password    = db.Column(db.String(255))
    created_at  = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at  = db.Column(db.Date, onupdate=datetime.utcnow)
    tenant_id         = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'))
    is_active         = db.Column(db.Boolean, default=False)
    is_invite_pending = db.Column(db.Boolean, default=False)

    # Relationships
    employee = db.relationship('EmployeeMaster', back_populates='user')
    roles    = db.relationship('RoleMaster', secondary='StreemLyne_MT.User_Role_Mapping', backref='users')

    def __repr__(self):
        return f'<UserMaster {self.user_id}: {self.user_name}>'

    def set_password(self, password: str) -> None:
        self.password = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password, password)

    def generate_jwt_token(self, secret_key: str) -> str:
        from services.auth_service import generate_staff_token
        return generate_staff_token(user_id=self.user_id, employee_id=self.employee_id, secret_key=secret_key)

    @property
    def is_owner(self) -> bool:
        return any(
            r.role_name == 'Tenant Owner'
            for r in cast(list, self.roles or [])
            if hasattr(r, 'role_name')
        )

    def to_dict(self):
        # [MODEL-001] Read actual roles from User_Role_Mapping via the ORM
        # relationship (UserMaster.roles → RoleMaster, secondary=User_Role_Mapping).
        # self.roles is populated by SQLAlchemy when the relationship is loaded.
        role_names = [r.role_name for r in cast(list, self.roles or [])]
 
        return {
            'user_id':       self.user_id,
            'employee_id':   self.employee_id,
            'user_name':     self.user_name,
            'employee_name': self.employee.employee_name if self.employee else None,
            'email':         self.employee.email if self.employee else None,
            'first_name':    (
                self.employee.employee_name.split()[0]
                if self.employee and self.employee.employee_name else ''
            ),
            'last_name':     (
                ' '.join(self.employee.employee_name.split()[1:])
                if self.employee and self.employee.employee_name else ''
            ),
            'full_name':     self.employee.employee_name if self.employee else None,
            'phone':         self.employee.phone if self.employee else None,
            # [MODEL-001] real roles from User_Role_Mapping
            'roles':         role_names,
            'role':          role_names[0] if role_names else 'user',
            # True when the user holds at least one owner-level role — used by
            # the frontend to show/hide the Billing menu (PRD §2.2, Design Doc §9)
            'is_owner':      self.is_owner,
            'is_active':     self.is_active,
            'is_verified':   True,
            'created_at':    self.created_at.isoformat() if self.created_at else None,
            'updated_at':    self.updated_at.isoformat() if self.updated_at else None,
        }


class UserRoleMapping(db.Model):
    """Composite PK join table between users and roles."""
    __tablename__ = 'User_Role_Mapping'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    user_id = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.User_Master.user_id'), primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Role_Master.role_id'), primary_key=True)

    def __repr__(self):
        return f'<UserRoleMapping User:{self.user_id} Role:{self.role_id}>'


class CustomerAuth(db.Model):
    """External customer portal login accounts."""
    __tablename__ = 'Customer_Auth'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    customer_user_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    client_id        = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=False)
    # [SUBSCRIPTION-010] was db.SmallInteger
    tenant_id        = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False)
    email            = db.Column(db.String(255), unique=True, nullable=False)
    password_hash    = db.Column(db.Text, nullable=False)
    is_active        = db.Column(db.Boolean, default=True)
    created_at       = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    # Relationships
    client          = db.relationship('ClientMaster', back_populates='customer_auths')
    password_resets = db.relationship('CustomerPasswordReset', back_populates='customer_user', lazy='dynamic')

    def __repr__(self):
        return f'<CustomerAuth {self.email}>'

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def generate_jwt_token(self, secret_key: str) -> str:
        from services.auth_service import generate_customer_token
        return generate_customer_token(
            customer_user_id=self.customer_user_id,
            client_id=self.client_id,
            tenant_id=self.tenant_id,
            secret_key=secret_key,
        )

    def to_dict(self):
        return {
            'customer_user_id': self.customer_user_id,
            'client_id':        self.client_id,
            'tenant_id':        self.tenant_id,
            'email':            self.email,
            'is_active':        self.is_active,
            'created_at':       self.created_at.isoformat() if self.created_at else None,
        }


class CustomerPasswordReset(db.Model):
    """Time-limited password-reset tokens for the customer portal."""
    __tablename__ = 'Customer_Password_Reset'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id               = db.Column(db.Integer, primary_key=True, autoincrement=True)
    customer_user_id = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Customer_Auth.customer_user_id'))
    token            = db.Column(db.Text, nullable=False)
    expires_at       = db.Column(db.DateTime(timezone=False), nullable=False)
    used             = db.Column(db.Boolean, default=False)
    created_at       = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    customer_user = db.relationship('CustomerAuth', back_populates='password_resets')

    def __repr__(self):
        return f'<CustomerPasswordReset {self.id} for User:{self.customer_user_id}>'

    def is_valid(self) -> bool:
        return not self.used and datetime.utcnow() < self.expires_at

    def to_dict(self):
        return {
            'id':               self.id,
            'customer_user_id': self.customer_user_id,
            'expires_at':       self.expires_at.isoformat() if self.expires_at else None,
            'used':             self.used,
            'created_at':       self.created_at.isoformat() if self.created_at else None,
        }


class OpportunityDetails(db.Model):
    """Sales opportunity/lead records with soft-delete support."""
    __tablename__ = 'Opportunity_Details'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    opportunity_id                  = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    client_id                       = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))
    # [SUBSCRIPTION-010] was db.BigInteger
    tenant_id                       = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'))
    opportunity_owner_employee_id   = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'))
    assigned_to_employee_id         = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'))
    stage_id                        = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Stage_Master.stage_id'), nullable=False)
    currency_id                     = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'))
    service_id                      = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Services_Master.service_id'))
    opportunity_title               = db.Column(db.String(255), nullable=False)
    opportunity_description         = db.Column(db.String)
    opportunity_date                = db.Column(db.Date)
    opportunity_value               = db.Column(db.SmallInteger)
    mpan_mpr                        = db.Column(db.String)
    business_name                   = db.Column(db.String(255))
    contact_person                  = db.Column(db.String(255))
    tel_number                      = db.Column(db.String(50))
    email                           = db.Column(db.String(255))
    start_date                      = db.Column(db.Date)
    end_date                        = db.Column(db.Date)
    Misc_Col1                       = db.Column(db.String(255))
    deleted_at                      = db.Column(db.DateTime(timezone=False))
    created_at                      = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    client             = db.relationship('ClientMaster', back_populates='opportunities')
    opportunity_owner  = db.relationship('EmployeeMaster', foreign_keys=[opportunity_owner_employee_id], back_populates='owned_opportunities')
    assigned_employee  = db.relationship('EmployeeMaster', foreign_keys=[assigned_to_employee_id], back_populates='assigned_opportunities')
    stage              = db.relationship('StageMaster', back_populates='opportunities')
    currency           = db.relationship('CurrencyMaster', backref='opportunities')
    service            = db.relationship('ServicesMaster', backref='opportunities')
    projects           = db.relationship('ProjectDetails', back_populates='opportunity', lazy='dynamic')
    case_documents     = db.relationship('CaseDocuments', back_populates='opportunity', lazy='dynamic')
    customer_documents = db.relationship('CustomerDocuments', back_populates='opportunity', lazy='dynamic')

    def __repr__(self):
        return f'<OpportunityDetails {self.opportunity_id}: {self.opportunity_title}>'

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def to_dict(self):
        return {
            'opportunity_id':               self.opportunity_id,
            'client_id':                    self.client_id,
            'client_name':                  self.client.client_company_name if self.client else None,
            'tenant_id':                    self.tenant_id,
            'opportunity_title':            self.opportunity_title,
            'opportunity_description':      self.opportunity_description,
            'opportunity_date':             self.opportunity_date.isoformat() if self.opportunity_date else None,
            'opportunity_owner_employee_id': self.opportunity_owner_employee_id,
            'opportunity_owner_name':       self.opportunity_owner.employee_name if self.opportunity_owner else None,
            'assigned_to_employee_id':      self.assigned_to_employee_id,
            'assigned_employee_name':       self.assigned_employee.employee_name if self.assigned_employee else None,
            'stage_id':                     self.stage_id,
            'stage_name':                   self.stage.stage_name if self.stage else None,
            'opportunity_value':            self.opportunity_value,
            'currency_id':                  self.currency_id,
            'currency_code':                self.currency.currency_code if self.currency else None,
            'service_id':                   self.service_id,
            'service_title':                self.service.service_title if self.service else None,
            'mpan_mpr':                     self.mpan_mpr,
            'business_name':                self.business_name,
            'contact_person':               self.contact_person,
            'tel_number':                   self.tel_number,
            'email':                        self.email,
            'start_date':                   self.start_date.isoformat() if self.start_date else None,
            'end_date':                     self.end_date.isoformat() if self.end_date else None,
            'Misc_Col1':                    self.Misc_Col1,
            'deleted_at':                   self.deleted_at.isoformat() if self.deleted_at else None,
            'created_at':                   self.created_at.isoformat() if self.created_at else None,
        }


class ProjectDetails(db.Model):
    """Projects raised from a won opportunity."""
    __tablename__ = 'Project_Details'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    project_id          = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    client_id           = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=False)
    opportunity_id      = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Opportunity_Details.opportunity_id'), nullable=False)
    employee_id         = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'), nullable=False)
    project_title       = db.Column(db.String(255), nullable=False)
    project_description = db.Column(db.String)
    start_date          = db.Column(db.Date, nullable=False)
    end_date            = db.Column(db.Date)
    address             = db.Column(db.String)
    Misc_Col1           = db.Column(db.String(255))
    Misc_Col2           = db.Column(db.Integer)
    created_at          = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    updated_at          = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    # Relationships
    client           = db.relationship('ClientMaster', back_populates='projects')
    opportunity      = db.relationship('OpportunityDetails', back_populates='projects')
    employee         = db.relationship('EmployeeMaster', back_populates='managed_projects')
    energy_contracts = db.relationship('EnergyContractMaster', back_populates='project', lazy='dynamic')
    invoices         = db.relationship('InvoiceMaster', back_populates='project', lazy='dynamic')

    def __repr__(self):
        return f'<ProjectDetails {self.project_id}: {self.project_title}>'

    def to_dict(self):
        return {
            'project_id':          self.project_id,
            'client_id':           self.client_id,
            'opportunity_id':      self.opportunity_id,
            'opportunity_title':   self.opportunity.opportunity_title if self.opportunity else None,
            'employee_id':         self.employee_id,
            'employee_name':       self.employee.employee_name if self.employee else None,
            'project_title':       self.project_title,
            'project_description': self.project_description,
            'start_date':          self.start_date.isoformat() if self.start_date else None,
            'end_date':            self.end_date.isoformat() if self.end_date else None,
            'address':             self.address,
            'Misc_Col1':           self.Misc_Col1,
            'Misc_Col2':           self.Misc_Col2,
            'created_at':          self.created_at.isoformat() if self.created_at else None,
            'updated_at':          self.updated_at.isoformat() if self.updated_at else None,
        }


class CaseDocuments(db.Model):
    """Files uploaded against a specific opportunity."""
    __tablename__ = 'Case_Documents'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id             = db.Column(db.Integer, primary_key=True, autoincrement=True)
    opportunity_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Opportunity_Details.opportunity_id'), nullable=False)
    client_id      = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=False)
    # [SUBSCRIPTION-010] was db.SmallInteger
    tenant_id      = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False)
    uploaded_by    = db.Column(db.String(255), nullable=False)
    document_type  = db.Column(db.String(100))
    file_name      = db.Column(db.String(255), nullable=False)
    blob_url       = db.Column(db.Text, nullable=False)
    created_at     = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    opportunity = db.relationship('OpportunityDetails', back_populates='case_documents')
    client      = db.relationship('ClientMaster', back_populates='case_documents')

    def __repr__(self):
        return f'<CaseDocuments {self.id}: {self.file_name}>'

    def to_dict(self):
        return {
            'id':             self.id,
            'opportunity_id': self.opportunity_id,
            'client_id':      self.client_id,
            'tenant_id':      self.tenant_id,
            'uploaded_by':    self.uploaded_by,
            'document_type':  self.document_type,
            'file_name':      self.file_name,
            'blob_url':       self.blob_url,
            'created_at':     self.created_at.isoformat() if self.created_at else None,
        }


class CustomerDocuments(db.Model):
    """Files uploaded via the customer portal."""
    __tablename__ = 'Customer_Documents'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id             = db.Column(db.Integer, primary_key=True, autoincrement=True)
    client_id      = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=False)
    opportunity_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Opportunity_Details.opportunity_id'))
    file_url       = db.Column(db.Text, nullable=False)
    file_name      = db.Column(db.Text, nullable=False)
    uploaded_at    = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    client      = db.relationship('ClientMaster', back_populates='customer_documents')
    opportunity = db.relationship('OpportunityDetails', back_populates='customer_documents')

    def __repr__(self):
        return f'<CustomerDocuments {self.id}: {self.file_name}>'

    def to_dict(self):
        return {
            'id':             self.id,
            'client_id':      self.client_id,
            'opportunity_id': self.opportunity_id,
            'file_url':       self.file_url,
            'file_name':      self.file_name,
            'uploaded_at':    self.uploaded_at.isoformat() if self.uploaded_at else None,
        }


class EnergyContractMaster(db.Model):
    """Energy supply contracts negotiated for a project."""
    __tablename__ = 'Energy_Contract_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    energy_contract_master_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    project_id        = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Project_Details.project_id'))
    employee_id       = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'), nullable=False)
    supplier_id       = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Supplier_Master.supplier_id'), nullable=False)
    service_id        = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Services_Master.service_id'), nullable=False)
    currency_id       = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'))
    contract_start_date = db.Column(db.Date, nullable=False)
    contract_end_date   = db.Column(db.Date, nullable=False)
    terms_of_sale     = db.Column(db.String, nullable=False)
    unit_rate         = db.Column(db.Float(precision=24), nullable=False)
    document_details  = db.Column(db.String)
    mpan_number       = db.Column(db.String)
    created_at        = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at        = db.Column(db.DateTime(timezone=True), onupdate=datetime.utcnow)

    # Relationships
    project  = db.relationship('ProjectDetails', back_populates='energy_contracts')
    employee = db.relationship('EmployeeMaster', back_populates='energy_contracts')
    supplier = db.relationship('SupplierMaster', backref='energy_contracts')
    service  = db.relationship('ServicesMaster', backref='energy_contracts')
    currency = db.relationship('CurrencyMaster', backref='energy_contracts')

    def __repr__(self):
        return f'<EnergyContractMaster {self.energy_contract_master_id}>'

    def to_dict(self):
        return {
            'energy_contract_master_id': self.energy_contract_master_id,
            'project_id':     self.project_id,
            'employee_id':    self.employee_id,
            'employee_name':  self.employee.employee_name if self.employee else None,
            'supplier_id':    self.supplier_id,
            'supplier_name':  self.supplier.supplier_company_name if self.supplier else None,
            'service_id':     self.service_id,
            'service_title':  self.service.service_title if self.service else None,
            'currency_id':    self.currency_id,
            'currency_code':  self.currency.currency_code if self.currency else None,
            'contract_start_date': self.contract_start_date.isoformat() if self.contract_start_date else None,
            'contract_end_date':   self.contract_end_date.isoformat() if self.contract_end_date else None,
            'terms_of_sale':  self.terms_of_sale,
            'unit_rate':      self.unit_rate,
            'document_details': self.document_details,
            'mpan_number':    self.mpan_number,
            'created_at':     self.created_at.isoformat() if self.created_at else None,
            'updated_at':     self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================================
# SECTION 4: SUBSCRIPTION BILLING (NEW)
# ============================================================================

class SubscriptionInvoice(db.Model):
    """
    Subscription-specific invoices generated from Stripe.
    Separate from the client-facing InvoiceMaster table.
    """
    __tablename__ = 'Subscription_Invoice'
    __table_args__ = (
        db.Index('idx_invoice_tenant', 'tenant_id', 'status'),
        db.Index('idx_subscription_invoice_stripe', 'stripe_invoice_id'),
        {'schema': 'StreemLyne_MT'},
    )

    id = db.Column(
        PG_UUID(as_uuid=False).with_variant(db.String(36), "sqlite"),
        nullable=False,
        unique=True,
        default=lambda: str(uuid.uuid4()),
    )
    invoice_id = db.Column(
        db.SmallInteger().with_variant(db.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    tenant_id = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False)
    subscription_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Subscription.tenant_subscription_mapping_id'))
    stripe_invoice_id = db.Column(db.String(255), unique=True)
    stripe_subscription_id = db.Column(db.String(255))
    invoice_number = db.Column(db.String(50), nullable=False, unique=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    amount_paid = db.Column(db.Integer)
    tax_amount = db.Column(db.Numeric(10, 2), default=0)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    currency_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'), nullable=False)
    stripe_currency = db.Column('currency', db.String(20))
    status = db.Column(db.String(50), default='pending')
    invoice_date = db.Column(db.DateTime(timezone=True))
    period_start = db.Column(db.Date)
    period_end = db.Column(db.Date)
    invoice_pdf_url = db.Column(db.Text)
    due_date = db.Column(db.Date)
    paid_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='subscription_invoices')
    subscription = db.relationship('TenantSubscription', backref='invoices')
    currency = db.relationship('CurrencyMaster', backref='subscription_invoices')

    def __repr__(self):
        return f'<SubscriptionInvoice {self.invoice_id}: {self.invoice_number}>'

    def to_dict(self):
        line_items = [{
            'label': self.subscription.subscription.subscription_name
            if self.subscription and self.subscription.subscription
            else 'Subscription charge',
            'type': 'subscription',
            'amount': float(self.amount) if self.amount else 0,
        }]
        if self.tax_amount:
            line_items.append({
                'label': 'Tax',
                'type': 'tax',
                'amount': float(self.tax_amount),
            })

        return {
            'id': self.id,
            'invoice_id': self.invoice_id,
            'tenant_id': self.tenant_id,
            'subscription_id': self.subscription_id,
            'stripe_invoice_id': self.stripe_invoice_id,
            'stripe_subscription_id': self.stripe_subscription_id,
            'invoice_number': self.invoice_number,
            'amount': float(self.amount) if self.amount else 0,
            'amount_paid': self.amount_paid,
            'tax_amount': float(self.tax_amount) if self.tax_amount else 0,
            'total_amount': float(self.total_amount) if self.total_amount else 0,
            'currency_id': self.currency_id,
            'currency': self.stripe_currency,
            'currency_code': self.currency.currency_code if self.currency else None,
            'status': self.status,
            'invoice_date': self.invoice_date.isoformat() if self.invoice_date else None,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
            'invoice_pdf_url': self.invoice_pdf_url,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'line_items': line_items,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class PaymentAttempt(db.Model):
    __tablename__ = 'Payment_Attempt'
    __table_args__ = (
        db.Index('idx_payment_attempt_tenant', 'tenant_id', 'created_at'),
        {'schema': 'StreemLyne_MT'},
    )

    payment_attempt_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    tenant_id = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False)
    subscription_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Subscription.tenant_subscription_mapping_id'), nullable=False)
    stripe_payment_intent_id = db.Column(db.String)
    invoice_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Subscription_Invoice.invoice_id'))
    attempt_number = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Numeric, nullable=False)
    currency_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'), nullable=False)
    status = db.Column(db.String, nullable=False)
    failure_reason = db.Column(db.Text)
    failure_code = db.Column(db.String)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='payment_attempts')
    subscription = db.relationship('TenantSubscription', backref='payment_attempts')
    invoice = db.relationship('SubscriptionInvoice', backref='payment_attempts')
    currency = db.relationship('CurrencyMaster', backref='payment_attempts')


class DunningConfig(db.Model):
    __tablename__ = 'Dunning_Config'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    config_id = db.Column(
        db.SmallInteger().with_variant(db.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    plan_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Subscription_Plans.subscription_id'))
    retry_schedule = db.Column(db.JSON, nullable=False, default=lambda: [3, 7])
    max_retries = db.Column(db.Integer, default=3)
    grace_period_days = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), onupdate=datetime.utcnow)

    plan = db.relationship('SubscriptionPlan', backref='dunning_configs')


class NotificationPreference(db.Model):
    __tablename__ = 'Notification_Preference'
    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'notification_type', name='uq_notification_pref_tenant_type'),
        {'schema': 'StreemLyne_MT'},
    )

    preference_id = db.Column(
        db.SmallInteger().with_variant(db.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    tenant_id = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False)
    notification_type = db.Column(db.String, nullable=False)
    email_enabled = db.Column(db.Boolean, default=True)
    in_app_enabled = db.Column(db.Boolean, default=True)
    sms_enabled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='notification_preferences')


class NotificationLog(db.Model):
    __tablename__ = 'Notification_Log'
    __table_args__ = (
        db.Index('idx_notification_log_tenant', 'tenant_id', 'created_at'),
        {'schema': 'StreemLyne_MT'},
    )

    notification_id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    tenant_id = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False)
    notification_type = db.Column(db.String, nullable=False)
    channel = db.Column(db.String, nullable=False)
    recipient = db.Column(db.String)
    subject = db.Column(db.Text)
    body = db.Column(db.Text)
    status = db.Column(db.String, default='pending')
    sent_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='notification_logs')


class SubscriptionPause(db.Model):
    __tablename__ = 'Subscription_Pause'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    pause_id = db.Column(
        db.SmallInteger().with_variant(db.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    tenant_subscription_mapping_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Tenant_Subscription.tenant_subscription_mapping_id'),
        nullable=False,
    )
    paused_at = db.Column(db.DateTime(timezone=True), nullable=False)
    resume_at = db.Column(db.DateTime(timezone=True))
    pause_reason = db.Column(db.String)
    is_active = db.Column(db.Boolean, default=True)

    subscription = db.relationship('TenantSubscription', backref='pauses')


class PendingPlanChange(db.Model):
    __tablename__ = 'Pending_Plan_Change'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    change_id = db.Column(
        db.SmallInteger().with_variant(db.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    tenant_id = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, unique=True)
    current_plan_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Subscription_Plans.subscription_id'))
    new_plan_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Subscription_Plans.subscription_id'), nullable=False)
    scheduled_for = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='pending_plan_change')
    current_plan = db.relationship('SubscriptionPlan', foreign_keys=[current_plan_id], backref='pending_changes_from')
    new_plan = db.relationship('SubscriptionPlan', foreign_keys=[new_plan_id], backref='pending_changes_to')


class ProcessedWebhookEvent(db.Model):
    """
    [I1-FIX] Idempotency guard for Stripe webhooks.

    Stripe retries webhooks on HTTP 5xx or timeout. Without deduplication,
    a single payment event can trigger duplicate invoice rows, emails, and
    notifications. This table records event.id of every processed event so
    identical retries are short-circuited immediately.

    Design Doc §6: "Persist event.id to DB on first process. Short-circuit
    entire handler body if event.id already exists."
    """
    __tablename__ = 'Processed_Webhook_Event'
    __table_args__ = (
        db.Index('idx_processed_webhook_stripe_id', 'stripe_event_id'),
        {'schema': 'StreemLyne_MT'},
    )

    id = db.Column(
        PG_UUID(as_uuid=False).with_variant(db.String(36), "sqlite"),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    stripe_event_id = db.Column(db.String(255), unique=True, nullable=False)
    event_type = db.Column(db.String(100))
    processed_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<ProcessedWebhookEvent {self.stripe_event_id}: {self.event_type}>'

    def to_dict(self):
        return {
            'id': self.id,
            'stripe_event_id': self.stripe_event_id,
            'event_type': self.event_type,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
        }


# ============================================================================
# SECTION 4: PROPOSALS & INVOICES
# ============================================================================

class ProposalMaster(db.Model):
    """Header record for a client proposal (quote)."""
    __tablename__ = 'Proposal_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    quote_id = db.Column(
        db.String(10),
        unique=True,
        nullable=False,
        server_default=text(
            "'QUO-' || lpad(nextval('\"StreemLyne_MT\".quote_id_seq')::text, 3, '0')"
        ),
    )
    proposal_id      = db.Column(db.Integer, primary_key=True)
    client_id        = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))
    project_id       = db.Column(db.SmallInteger)
    currency_id      = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'))
    sub_total        = db.Column(db.Numeric(12, 2))
    total_amount     = db.Column(db.Numeric(12, 2), nullable=False)
    discount_percent = db.Column(db.Float(precision=24))
    discount_amount  = db.Column(db.Numeric(12, 2))
    tax_id           = db.Column(db.SmallInteger)
    customer_name    = db.Column(db.String(255))
    notes            = db.Column(db.Text)
    company_details  = db.Column(db.JSON)
    payment_details  = db.Column(db.JSON)
    tax_breakdown    = db.Column(db.JSON)
    created_at       = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    # Relationships
    client           = db.relationship('ClientMaster', back_populates='proposals')
    currency         = db.relationship('CurrencyMaster', backref='proposals')
    proposal_details = db.relationship('ProposalDetails', back_populates='proposal', lazy='dynamic', cascade='all, delete-orphan')
    invoices         = db.relationship('InvoiceMaster', back_populates='proposal', lazy='dynamic')

    def to_dict(self):
        return {
            'proposal_id':      self.proposal_id,
            'client_id':        self.client_id,
            'client_name':      self.client.client_company_name if self.client else None,
            'project_id':       self.project_id,
            'currency_id':      self.currency_id,
            'sub_total':        self.sub_total,
            'total_amount':     self.total_amount,
            'discount_percent': self.discount_percent,
            'discount_amount':  self.discount_amount,
            'tax_id':           self.tax_id,
            'customer_name':    self.customer_name,
            'notes':            self.notes,
            'company_details':  self.company_details,
            'payment_details':  self.payment_details,
            'tax_breakdown':    self.tax_breakdown,
            'created_at':       self.created_at.isoformat() if self.created_at else None,
            'updated_at':       self.updated_at.isoformat() if self.updated_at else None,
        }


class ProposalDetails(db.Model):
    """Individual line items on a proposal."""
    __tablename__ = 'Proposal_Details'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    proposal_details_id = db.Column(db.Integer, primary_key=True)
    proposal_id  = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Proposal_Master.proposal_id'), nullable=False)
    quantity     = db.Column(db.Numeric(10, 2), nullable=False)
    amount       = db.Column(db.Numeric(12, 2))
    service_id   = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Services_Master.service_id'), nullable=False)
    uom_id       = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.UOM_Master.uom_id'), nullable=False)
    service_name = db.Column(db.String(255))
    created_at   = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at   = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    # Relationships
    proposal = db.relationship('ProposalMaster', back_populates='proposal_details')
    service  = db.relationship('ServicesMaster', backref='proposal_details')
    uom      = db.relationship('UOMMaster', backref='proposal_details')

    def __repr__(self):
        return f'<ProposalDetails {self.proposal_details_id} for Proposal {self.proposal_id}>'

    def calculate_line_total(self) -> float:
        if self.service and self.service.service_rate is not None:
            return self.quantity * self.service.service_rate
        return 0.0

    def to_dict(self):
        return {
            'proposal_details_id': self.proposal_details_id,
            'proposal_id':         self.proposal_id,
            'service_id':          self.service_id,
            'service_title':       self.service.service_title if self.service else None,
            'service_name':        self.service_name,
            'amount':              self.amount,
            'uom_id':              self.uom_id,
            'quantity':            self.quantity,
            'line_total':          self.calculate_line_total(),
            'created_at':          self.created_at.isoformat() if self.created_at else None,
            'updated_at':          self.updated_at.isoformat() if self.updated_at else None,
        }


class InvoiceMaster(db.Model):
    """Invoice header, optionally linked to a proposal."""
    __tablename__ = 'Invoice_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    invoice_id       = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    client_id        = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))
    project_id       = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Project_Details.project_id'))
    proposal_id      = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Proposal_Master.proposal_id'))
    currency_id      = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'))
    invoice_number   = db.Column(db.String, nullable=False)
    billing_remarks  = db.Column(db.String)
    sub_total        = db.Column(db.Float(precision=24))
    vat              = db.Column(db.Numeric(precision=12, scale=2))
    other_taxes      = db.Column(db.Numeric(precision=12, scale=2))
    total_amount     = db.Column(db.Float(precision=24), nullable=False)
    discount_percent = db.Column(db.Float(precision=24))
    discount_amount  = db.Column(db.Float(precision=24))
    payment_status   = db.Column(db.String(50), nullable=True, default='Not Paid')
    tax_id           = db.Column(db.SmallInteger, nullable=False)
    created_at       = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    # Relationships
    client          = db.relationship('ClientMaster', back_populates='invoices')
    project         = db.relationship('ProjectDetails', back_populates='invoices')
    proposal        = db.relationship('ProposalMaster', back_populates='invoices')
    currency        = db.relationship('CurrencyMaster', backref='invoices')
    invoice_details = db.relationship('InvoiceDetails', back_populates='invoice', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<InvoiceMaster {self.invoice_id}: {self.invoice_number}>'

    def calculate_totals(self):
        details = self.invoice_details.all()
        self.sub_total = sum(
            (d.quantity * d.service.service_rate)
            for d in details
            if d.service and d.service.service_rate is not None
        )
        if self.discount_percent:
            self.discount_amount = self.sub_total * (self.discount_percent / 100)
        elif not self.discount_amount:
            self.discount_amount = 0.0
        self.total_amount = self.sub_total - (self.discount_amount or 0.0)
        return self.total_amount

    def to_dict(self):
        return {
            'invoice_id':       self.invoice_id,
            'client_id':        self.client_id,
            'client_name':      self.client.client_company_name if self.client else None,
            'project_id':       self.project_id,
            'project_title':    self.project.project_title if self.project else None,
            'proposal_id':      self.proposal_id,
            'currency_id':      self.currency_id,
            'currency_code':    self.currency.currency_code if self.currency else None,
            'invoice_number':   self.invoice_number,
            'billing_remarks':  self.billing_remarks,
            'sub_total':        float(self.sub_total) if self.sub_total is not None else None,
            'vat':              self.vat,
            'other_taxes':      self.other_taxes,
            'total_amount':     self.total_amount,
            'discount_percent': self.discount_percent,
            'discount_amount':  self.discount_amount,
            'payment_status':   self.payment_status,
            'tax_id':           self.tax_id,
            'created_at':       self.created_at.isoformat() if self.created_at else None,
            'updated_at':       self.updated_at.isoformat() if self.updated_at else None,
        }


class InvoiceDetails(db.Model):
    """Individual line items on an invoice."""
    __tablename__ = 'Invoice_Details'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    invoice_details_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    invoice_id   = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Invoice_Master.invoice_id'), nullable=False)
    service_id   = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Services_Master.service_id'), nullable=True)
    uom_id       = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.UOM_Master.uom_id'), nullable=True)
    quantity     = db.Column(db.Float(precision=24), nullable=True, default=1.0)
    service_name = db.Column(db.String(500), nullable=True)
    unit_price   = db.Column(db.Float(precision=24), nullable=True)
    created_at   = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at   = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    # Relationships
    invoice = db.relationship('InvoiceMaster', back_populates='invoice_details')
    service = db.relationship('ServicesMaster', backref='invoice_details')
    uom     = db.relationship('UOMMaster', backref='invoice_details')

    def __repr__(self):
        return f'<InvoiceDetails {self.invoice_details_id} for Invoice {self.invoice_id}>'

    def calculate_line_total(self) -> float:
        if self.service and self.service.service_rate is not None:
            return self.quantity * self.service.service_rate
        return 0.0

    def to_dict(self):
        return {
            'invoice_details_id': self.invoice_details_id,
            'invoice_id':         self.invoice_id,
            'service_id':         self.service_id,
            'service_title':      self.service.service_title if self.service else None,
            'service_code':       self.service.service_code if self.service else None,
            'service_rate':       self.service.service_rate if self.service else None,
            'uom_id':             self.uom_id,
            'uom_description':    self.uom.uom_description if self.uom else None,
            'quantity':           self.quantity,
            'line_total':         self.calculate_line_total(),
            'created_at':         self.created_at.isoformat() if self.created_at else None,
            'updated_at':         self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================================
# SECTION 5: DOCUMENTS, ACTIVITIES, CHAT & AUDIT
# ============================================================================

class Activity(db.Model):
    """
    Scheduled/completed activities linked to an opportunity.
    status: 'Scheduled' | 'Completed' | 'Cancelled'
    activity_type: 'meeting' | 'call' | 'email' | 'task'
    """
    __tablename__ = 'activities'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id             = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    # [SUBSCRIPTION-010] was db.SmallInteger
    tenant_id      = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    opportunity_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Opportunity_Details.opportunity_id'), nullable=False)
    activity_type  = db.Column(db.String(50), nullable=False)
    title          = db.Column(db.String(200), nullable=False)
    description    = db.Column(db.Text)
    scheduled_date = db.Column(db.DateTime)
    completed_date = db.Column(db.DateTime)
    status         = db.Column(db.String(20), default='Scheduled')
    assigned_to    = db.Column(db.String(200))
    created_by     = db.Column(db.String(200))
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at     = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant      = db.relationship('TenantMaster', backref='activities')
    opportunity = db.relationship('OpportunityDetails', backref='activities')

    def __repr__(self):
        return f'<Activity {self.id}: {self.title}>'

    def to_dict(self):
        return {
            'id':             self.id,
            'tenant_id':      self.tenant_id,
            'opportunity_id': self.opportunity_id,
            'activity_type':  self.activity_type,
            'title':          self.title,
            'description':    self.description,
            'scheduled_date': self.scheduled_date.isoformat() if self.scheduled_date else None,
            'completed_date': self.completed_date.isoformat() if self.completed_date else None,
            'status':         self.status,
            'assigned_to':    self.assigned_to,
            'created_by':     self.created_by,
            'created_at':     self.created_at.isoformat() if self.created_at else None,
            'updated_at':     self.updated_at.isoformat() if self.updated_at else None,
        }


class OpportunityNote(db.Model):
    """Free-text notes attached to an opportunity."""
    __tablename__ = 'opportunity_notes'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id             = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    # [SUBSCRIPTION-010] was db.SmallInteger
    tenant_id      = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    opportunity_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Opportunity_Details.opportunity_id'), nullable=False)
    content        = db.Column(db.Text, nullable=False)
    note_type      = db.Column(db.String(50), default='general')
    author         = db.Column(db.String(200))
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    tenant      = db.relationship('TenantMaster', backref='opportunity_notes')
    opportunity = db.relationship('OpportunityDetails', backref='notes')

    def __repr__(self):
        return f'<OpportunityNote {self.id}>'

    def to_dict(self):
        return {
            'id':             self.id,
            'tenant_id':      self.tenant_id,
            'opportunity_id': self.opportunity_id,
            'content':        self.content,
            'note_type':      self.note_type,
            'author':         self.author,
            'created_at':     self.created_at.isoformat() if self.created_at else None,
        }


class DocumentTemplate(db.Model):
    """Tenant-owned document templates (DOCX/PDF) used for mail-merge."""
    __tablename__ = 'document_templates'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id            = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    # [SUBSCRIPTION-010] was db.SmallInteger
    tenant_id     = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    name          = db.Column(db.String(120), nullable=False)
    template_type = db.Column(db.String(50), nullable=False)
    file_path     = db.Column(db.String(500), nullable=False)
    merge_fields  = db.Column(db.JSON)
    uploaded_by   = db.Column(db.String(200))
    uploaded_at   = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='document_templates')

    def __repr__(self):
        return f'<DocumentTemplate {self.id}: {self.name}>'

    def to_dict(self):
        return {
            'id':            self.id,
            'tenant_id':     self.tenant_id,
            'name':          self.name,
            'template_type': self.template_type,
            'file_path':     self.file_path,
            'merge_fields':  self.merge_fields,
            'uploaded_by':   self.uploaded_by,
            'uploaded_at':   self.uploaded_at.isoformat() if self.uploaded_at else None,
        }


class FormSubmission(db.Model):
    """Raw inbound form submissions from public-facing lead-capture forms."""
    __tablename__ = 'form_submissions'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id           = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    # [SUBSCRIPTION-010] was db.SmallInteger
    tenant_id    = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=True, index=True)
    client_id    = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))
    form_data    = db.Column(db.Text, nullable=False)
    source       = db.Column(db.String(100))
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed    = db.Column(db.Boolean, default=False)
    processed_at = db.Column(db.DateTime)

    tenant = db.relationship('TenantMaster', backref='form_submissions')
    client = db.relationship('ClientMaster', backref='form_submissions')

    def __repr__(self):
        return f'<FormSubmission {self.id}>'

    def to_dict(self):
        return {
            'id':           self.id,
            'tenant_id':    self.tenant_id,
            'client_id':    self.client_id,
            'form_data':    self.form_data,
            'source':       self.source,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'processed':    self.processed,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
        }


class CustomerFormData(db.Model):
    """Structured form submissions from the customer portal."""
    __tablename__ = 'customer_form_data'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id           = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    # [SUBSCRIPTION-010] was db.SmallInteger
    tenant_id    = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=True, index=True)
    client_id    = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=False)
    form_data    = db.Column(db.Text, nullable=False)
    token_used   = db.Column(db.String(64), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='customer_form_data')
    client = db.relationship('ClientMaster', backref='form_data')

    def __repr__(self):
        return f'<CustomerFormData {self.id} for Client {self.client_id}>'

    def to_dict(self):
        return {
            'id':           self.id,
            'tenant_id':    self.tenant_id,
            'client_id':    self.client_id,
            'form_data':    self.form_data,
            'token_used':   self.token_used,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
        }


class DataImport(db.Model):
    """
    Tracks bulk CSV/XLSX import jobs.
    status: 'processing' | 'completed' | 'failed'
    """
    __tablename__ = 'data_imports'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id                 = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    # [SUBSCRIPTION-010] was db.SmallInteger
    tenant_id          = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=True, index=True)
    filename           = db.Column(db.String(255), nullable=False)
    import_type        = db.Column(db.String(50), nullable=False)
    status             = db.Column(db.String(20), default='processing')
    records_processed  = db.Column(db.Integer, default=0)
    records_failed     = db.Column(db.Integer, default=0)
    error_log          = db.Column(db.Text)
    imported_by        = db.Column(db.String(200))
    created_at         = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at       = db.Column(db.DateTime)

    tenant = db.relationship('TenantMaster', backref='data_imports')

    def __repr__(self):
        return f'<DataImport {self.id}: {self.filename} ({self.status})>'

    def to_dict(self):
        return {
            'id':                self.id,
            'tenant_id':         self.tenant_id,
            'filename':          self.filename,
            'import_type':       self.import_type,
            'status':            self.status,
            'records_processed': self.records_processed,
            'records_failed':    self.records_failed,
            'error_log':         self.error_log,
            'imported_by':       self.imported_by,
            'created_at':        self.created_at.isoformat() if self.created_at else None,
            'completed_at':      self.completed_at.isoformat() if self.completed_at else None,
        }


class AuditLog(db.Model):
    """
    Immutable audit trail for create/update/delete operations.
    action: 'create' | 'update' | 'delete'
    """
    __tablename__ = 'audit_logs'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id                 = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    # [SUBSCRIPTION-010] was db.SmallInteger
    tenant_id          = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=True, index=True)
    entity_type        = db.Column(db.String(120), nullable=False)
    entity_id          = db.Column(db.SmallInteger, nullable=False)
    action             = db.Column(db.String(20), nullable=False)
    changed_by         = db.Column(db.String(200))
    changed_at         = db.Column(db.DateTime, default=datetime.utcnow)
    change_summary     = db.Column(db.JSON)
    previous_snapshot  = db.Column(db.JSON)
    new_snapshot       = db.Column(db.JSON)

    tenant = db.relationship('TenantMaster', backref='audit_logs')

    def __repr__(self):
        return f'<AuditLog {self.entity_type}:{self.entity_id} {self.action}>'

    def to_dict(self):
        return {
            'id':                self.id,
            'tenant_id':         self.tenant_id,
            'entity_type':       self.entity_type,
            'entity_id':         self.entity_id,
            'action':            self.action,
            'changed_by':        self.changed_by,
            'changed_at':        self.changed_at.isoformat() if self.changed_at else None,
            'change_summary':    self.change_summary,
            'previous_snapshot': self.previous_snapshot,
            'new_snapshot':      self.new_snapshot,
        }


class VersionedSnapshot(db.Model):
    """Point-in-time snapshots for entities that require version history."""
    __tablename__ = 'versioned_snapshots'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id             = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    # [SUBSCRIPTION-010] was db.SmallInteger
    tenant_id      = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=True, index=True)
    entity_type    = db.Column(db.String(120), nullable=False)
    entity_id      = db.Column(db.SmallInteger, nullable=False)
    version_number = db.Column(db.Integer, nullable=False)
    reason         = db.Column(db.String(255))
    snapshot       = db.Column(db.JSON, nullable=False)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    created_by     = db.Column(db.String(200))

    tenant = db.relationship('TenantMaster', backref='versioned_snapshots')

    def __repr__(self):
        return f'<VersionedSnapshot {self.entity_type}:{self.entity_id} v{self.version_number}>'

    def to_dict(self):
        return {
            'id':             self.id,
            'tenant_id':      self.tenant_id,
            'entity_type':    self.entity_type,
            'entity_id':      self.entity_id,
            'version_number': self.version_number,
            'reason':         self.reason,
            'snapshot':       self.snapshot,
            'created_at':     self.created_at.isoformat() if self.created_at else None,
            'created_by':     self.created_by,
        }


class ChatConversation(db.Model):
    """A named AI-chat session belonging to a user."""
    __tablename__ = 'chat_conversations'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id         = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    # [SUBSCRIPTION-010] was db.SmallInteger
    tenant_id  = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    user_id    = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.User_Master.user_id'), nullable=False, index=True)
    title      = db.Column(db.String(255), default='New Conversation')
    session_id = db.Column(db.String(100), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant   = db.relationship('TenantMaster', backref='chat_conversations')
    user     = db.relationship('UserMaster', backref='chat_conversations')
    messages = db.relationship('ChatMessage', back_populates='conversation', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<ChatConversation {self.id}: {self.title}>'

    def to_dict(self):
        return {
            'id':            self.id,
            'tenant_id':     self.tenant_id,
            'user_id':       self.user_id,
            'title':         self.title,
            'session_id':    self.session_id,
            'created_at':    self.created_at.isoformat() if self.created_at else None,
            'updated_at':    self.updated_at.isoformat() if self.updated_at else None,
            'message_count': len(list(self.messages)) if self.messages else 0,  # type: ignore[arg-type]
        }


class ChatMessage(db.Model):
    """
    Individual message within a ChatConversation.
    role: 'user' | 'assistant'
    """
    __tablename__ = 'chat_messages'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id              = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    # [SUBSCRIPTION-010] was db.SmallInteger
    tenant_id       = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    user_id         = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.User_Master.user_id'), nullable=False, index=True)
    conversation_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.chat_conversations.id'), nullable=False, index=True)
    role            = db.Column(db.String(20), nullable=False)
    content         = db.Column(db.Text, nullable=False)
    function_calls  = db.Column(db.JSON)
    tool_results    = db.Column(db.JSON)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    tenant       = db.relationship('TenantMaster', backref='chat_messages')
    user         = db.relationship('UserMaster', backref='chat_messages')
    conversation = db.relationship('ChatConversation', back_populates='messages')

    def __repr__(self):
        return f'<ChatMessage {self.id}: {self.role}>'

    def to_dict(self):
        return {
            'id':              self.id,
            'conversation_id': self.conversation_id,
            'tenant_id':       self.tenant_id,
            'user_id':         self.user_id,
            'role':            self.role,
            'content':         self.content,
            'function_calls':  self.function_calls,
            'tool_results':    self.tool_results,
            'created_at':      self.created_at.isoformat() if self.created_at else None,
        }


class ChatHistory(db.Model):
    """Denormalised blob storage of an entire conversation's message list."""
    __tablename__ = 'chat_history'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id         = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    # [SUBSCRIPTION-010] was db.SmallInteger
    tenant_id  = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    user_id    = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.User_Master.user_id'), nullable=False, index=True)
    session_id = db.Column(db.String(100), nullable=False, index=True)
    title      = db.Column(db.String(255))
    messages   = db.Column(db.JSON, nullable=False)
    context    = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='chat_history')
    user   = db.relationship('UserMaster', backref='chat_history')

    def __repr__(self):
        return f'<ChatHistory {self.id} session:{self.session_id}>'

    def to_dict(self):
        return {
            'id':         self.id,
            'session_id': self.session_id,
            'tenant_id':  self.tenant_id,
            'user_id':    self.user_id,
            'title':      self.title,
            'messages':   self.messages,
            'context':    self.context,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================================
# SECTION 6: ASSIGNMENTS & SCHEDULING
# ============================================================================

class Assignment(db.Model):
    """
    Application-level table for the Schedule feature.
    type: meeting | call | task | delivery | note
    status: Scheduled | In Progress | Completed | Cancelled
    priority: Low | Medium | High | Urgent
    """
    __tablename__ = 'assignments'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    assignment_id   = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # [SUBSCRIPTION-010] was db.Integer
    tenant_id       = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False)
    type            = db.Column(db.String(50), nullable=False, default='task')
    title           = db.Column(db.String(255), nullable=False)
    date            = db.Column(db.Date, nullable=False)
    staff_name      = db.Column(db.String(150), nullable=True)
    project_id      = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Project_Details.project_id'), nullable=True)
    client_id       = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=True)
    estimated_hours = db.Column(db.Float, nullable=True)
    notes           = db.Column(db.Text, nullable=True)
    priority        = db.Column(db.String(50), nullable=True, default='Medium')
    status          = db.Column(db.String(50), nullable=True, default='Scheduled')
    created_at      = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at      = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)

    # Relationships
    project = db.relationship('ProjectDetails', backref='assignments', lazy='select', foreign_keys=[project_id])
    client  = db.relationship('ClientMaster', backref='assignments', lazy='select', foreign_keys=[client_id])

    def __repr__(self):
        return f'<Assignment {self.assignment_id} [{self.type}] {self.date}>'

    def to_dict(self):
        return {
            'assignment_id':  self.assignment_id,
            'tenant_id':      self.tenant_id,
            'type':           self.type,
            'title':          self.title,
            'date':           self.date.isoformat() if self.date else None,
            'staff_name':     self.staff_name,
            'project_id':     self.project_id,
            'project_title':  self.project.project_title if self.project else None,
            'client_id':      self.client_id,
            'client_name':    self.client.client_company_name if self.client else None,
            'estimated_hours': self.estimated_hours,
            'notes':          self.notes,
            'priority':       self.priority,
            'status':         self.status,
            'created_at':     self.created_at.isoformat() if self.created_at else None,
            'updated_at':     self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================================
# MODULE AVAILABILITY FLAGS & HELPER FUNCTIONS
# ============================================================================

EDUCATION_MODULE_AVAILABLE = False
INTERIOR_MODULE_AVAILABLE  = False
DRAWING_MODULE_AVAILABLE   = False
LEGACY_MODELS_AVAILABLE    = True


def is_module_available(module_name: str) -> bool:
    return {
        'education':      EDUCATION_MODULE_AVAILABLE,
        'interior_design': INTERIOR_MODULE_AVAILABLE,
        'legacy':          LEGACY_MODELS_AVAILABLE,
    }.get(module_name, False)


def get_available_modules() -> list:
    modules = []
    if LEGACY_MODELS_AVAILABLE:
        modules.append('legacy')
    return modules


def get_new_schema_models() -> list:
    return [
        # Tenancy & Subscription
        'TenantMaster', 'SubscriptionPlan', 'ModuleMaster',
        'SubscriptionModuleMapping', 'TenantModuleMapping', 'TenantSubscription',
        # Subscription Billing (NEW)
        'SubscriptionInvoice', 'PaymentAttempt', 'DunningConfig',
        'NotificationPreference', 'NotificationLog', 'SubscriptionPause',
        'PendingPlanChange', 'ProcessedWebhookEvent',
        # Masters
        'CountryMaster', 'CurrencyMaster', 'DesignationMaster',
        'ServicesMaster', 'UOMMaster', 'StageMaster', 'SupplierMaster',
        'RoleMaster', 'PermissionCatalog', 'RolePermissionMapping',
        'TaxMaster', 'ContactMethodMaster',
        # Core
        'ClientMaster', 'ClientInteractions', 'EmployeeMaster', 'UserMaster',
        'UserRoleMapping', 'CustomerAuth', 'CustomerPasswordReset',
        'OpportunityDetails', 'ProjectDetails', 'CaseDocuments',
        'CustomerDocuments', 'EnergyContractMaster',
        # Proposals & Invoices
        'ProposalMaster', 'ProposalDetails', 'InvoiceMaster', 'InvoiceDetails',
        # Documents / Chat / Audit
        'Activity', 'OpportunityNote', 'DocumentTemplate', 'FormSubmission',
        'CustomerFormData', 'DataImport', 'AuditLog', 'VersionedSnapshot',
        'ChatConversation', 'ChatMessage', 'ChatHistory',
        # Assignments
        'Assignment',
    ]


def get_legacy_schema_models() -> list:
    return [
        'Tenant', 'User', 'LoginAttempt', 'Session',
        'Customer', 'Opportunity', 'Job',
        'Team', 'TeamMember', 'Salesperson', 'Assignment',
        'Product', 'ProductCategory', 'Proposal', 'ProposalItem',
        'Invoice', 'InvoiceLineItem', 'Payment',
        'OpportunityDocument',
    ]


# ============================================================================
# PUBLIC API
# ============================================================================

__all__ = [
    # Tenancy & Subscription
    'TenantMaster', 'SubscriptionPlan', 'SubscriptionPlans', 'ModuleMaster',
    'SubscriptionModuleMapping', 'TenantModuleMapping', 'TenantSubscription',
    # Subscription Billing (NEW)
    'SubscriptionInvoice', 'PaymentAttempt', 'DunningConfig',
    'NotificationPreference', 'NotificationLog', 'SubscriptionPause',
    'PendingPlanChange', 'ProcessedWebhookEvent',
    # Masters
    'CountryMaster', 'CurrencyMaster', 'DesignationMaster', 'ServicesMaster',
    'UOMMaster', 'StageMaster', 'SupplierMaster', 'RoleMaster',
    'PermissionCatalog', 'RolePermissionMapping', 'TaxMaster', 'ContactMethodMaster',
    # Core
    'ClientMaster', 'ClientInteractions', 'EmployeeMaster', 'UserMaster',
    'UserRoleMapping', 'CustomerAuth', 'CustomerPasswordReset',
    'OpportunityDetails', 'ProjectDetails', 'CaseDocuments',
    'CustomerDocuments', 'EnergyContractMaster',
    # Proposals & Invoices
    'ProposalMaster', 'ProposalDetails', 'InvoiceMaster', 'InvoiceDetails',
    # Documents, Chat & Audit
    'Activity', 'OpportunityNote', 'DocumentTemplate', 'FormSubmission',
    'CustomerFormData', 'DataImport', 'AuditLog', 'VersionedSnapshot',
    'ChatConversation', 'ChatMessage', 'ChatHistory',
    # Assignments
    'Assignment',
    # Module flags
    'EDUCATION_MODULE_AVAILABLE', 'INTERIOR_MODULE_AVAILABLE',
    'DRAWING_MODULE_AVAILABLE', 'LEGACY_MODELS_AVAILABLE',
    # Helpers
    'is_module_available', 'get_available_modules',
    'get_new_schema_models', 'get_legacy_schema_models',
]
