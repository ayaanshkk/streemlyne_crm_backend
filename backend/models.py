"""
StreemLyne CRM - Unified Models Module

All SQLAlchemy models for the StreemLyne CRM system.
Cleaned to match actual tables in StreemLyne_MT schema.

SCHEMA: StreemLyne_MT (multi-tenant schema)

SECTIONS:
    1. Tenancy & Subscriptions
    2. Master/Reference Data
    3. Core Business Models
    4. Proposals & Invoices
    5. Chat & Documents
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
    __tablename__ = 'Tenant_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}
 
    tenant_id           = db.Column(db.String, primary_key=True)
    tenant_company_name = db.Column(db.String(255))
    tenant_contact_name = db.Column(db.String(255))
    onboarding_Date     = db.Column(db.Date)
    is_active           = db.Column(db.Boolean)
    created_at          = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    updated_at          = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)
    stripe_customer_id  = db.Column(db.String(255), unique=True)
 
    # ── Branding ──────────────────────────────────────────────────────────────
    logo_url            = db.Column(db.Text,         nullable=True)
    tagline             = db.Column(db.String(500),  nullable=True)
 
    # ── Business details ──────────────────────────────────────────────────────
    company_email       = db.Column(db.String(255),  nullable=True)
    company_phone       = db.Column(db.String(50),   nullable=True)
    company_address     = db.Column(db.Text,         nullable=True)
    company_postcode    = db.Column(db.String(20),   nullable=True)
    company_website     = db.Column(db.String(500),  nullable=True)
    registration_no     = db.Column(db.String(100),  nullable=True)
    vat_reg_no          = db.Column(db.String(100),  nullable=True)
 
    # ── Payment details ───────────────────────────────────────────────────────
    bank_name           = db.Column(db.String(255),  nullable=True)
    account_name        = db.Column(db.String(255),  nullable=True)
    sort_code           = db.Column(db.String(20),   nullable=True)
    account_number      = db.Column(db.String(50),   nullable=True)
    payment_reference   = db.Column(db.Text,         nullable=True)
 
    # ── Document defaults ─────────────────────────────────────────────────────
    default_vat_rate    = db.Column(db.Numeric(5, 2),nullable=True, default=20.0)
    default_currency    = db.Column(db.String(10),   nullable=True, default='GBP')
    quote_validity_days = db.Column(db.Integer,      nullable=True, default=30)
    default_notes       = db.Column(db.Text,         nullable=True)
 
    clients         = db.relationship('ClientMaster', back_populates='tenant', lazy='dynamic')
    employees       = db.relationship('EmployeeMaster', back_populates='tenant', lazy='dynamic')
    services        = db.relationship('ServicesMaster', back_populates='tenant', lazy='dynamic')
    subscriptions   = db.relationship('TenantSubscription', back_populates='tenant', lazy='dynamic')
    module_mappings = db.relationship('TenantModuleMapping', back_populates='tenant', lazy='dynamic')
    account_type = db.Column(db.String(20), nullable=True, default='individual')
 
    def __repr__(self):
        return f'<TenantMaster {self.tenant_id}: {self.tenant_company_name}>'
 
    def to_dict(self):
        return {
            'tenant_id':           self.tenant_id,
            'tenant_company_name': self.tenant_company_name,
            'tenant_contact_name': self.tenant_contact_name,
            'onboarding_Date':     self.onboarding_Date.isoformat() if self.onboarding_Date else None,
            'is_active':           self.is_active,
            'stripe_customer_id':  self.stripe_customer_id,
            'created_at':          self.created_at.isoformat() if self.created_at else None,
            'updated_at':          self.updated_at.isoformat() if self.updated_at else None,
            'logo_url':            self.logo_url,
            'tagline':             self.tagline,
            'company_email':       self.company_email,
            'company_phone':       self.company_phone,
            'company_address':     self.company_address,
            'company_postcode':    self.company_postcode,
            'company_website':     self.company_website,
            'registration_no':     self.registration_no,
            'vat_reg_no':          self.vat_reg_no,
            'bank_name':           self.bank_name,
            'account_name':        self.account_name,
            'sort_code':           self.sort_code,
            'account_number':      self.account_number,
            'payment_reference':   self.payment_reference,
            'default_vat_rate':    float(self.default_vat_rate) if self.default_vat_rate is not None else 20.0,
            'default_currency':    self.default_currency or 'GBP',
            'quote_validity_days': self.quote_validity_days or 30,
            'default_notes':       self.default_notes,
        }


class SubscriptionPlan(db.Model):
    __tablename__ = 'Subscription_Plans'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    subscription_id   = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    subscription_code = db.Column(db.String(50), unique=True, nullable=False)
    subscription_name = db.Column(db.String(100), unique=True, nullable=False)
    description       = db.Column(db.String)
    is_base_plan      = db.Column(db.Boolean, nullable=False)
    is_active         = db.Column(db.Boolean, nullable=False)
    billing_cycle     = db.Column(db.SmallInteger, nullable=False)
    price             = db.Column(db.Numeric(10, 2), nullable=False)
    currency_id       = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'), nullable=False)
    created_at        = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    updated_at        = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)
    stripe_price_id   = db.Column(db.String(255))
    max_users         = db.Column(db.Integer)
    max_customers    = db.Column(db.Integer)
    max_ai_messages  = db.Column(db.Integer)
    currency             = db.relationship('CurrencyMaster', backref='subscription_plans')
    module_mappings      = db.relationship('SubscriptionModuleMapping', back_populates='subscription', lazy='dynamic')
    tenant_subscriptions = db.relationship('TenantSubscription', back_populates='subscription', lazy='dynamic')
    stripe_price_id_test = db.Column(db.String(255), nullable=True)
    stripe_price_id_live = db.Column(db.String(255), nullable=True)

    @property
    def active_stripe_price_id(self) -> str | None:
        stripe_key = os.environ.get('STRIPE_SECRET_KEY', '')
        if stripe_key.startswith('sk_live_'):
            return self.stripe_price_id_live or self.stripe_price_id
        return self.stripe_price_id_test or self.stripe_price_id

    def __repr__(self):
        return f'<SubscriptionPlan {self.subscription_code}>'

    def get_billing_cycle_name(self):
        return {1: 'Monthly', 3: 'Quarterly', 12: 'Annual'}.get(self.billing_cycle, 'Unknown')

    def to_dict(self):
        return {
            'subscription_id':    self.subscription_id,
            'subscription_code':  self.subscription_code,
            'subscription_name':  self.subscription_name,
            'description':        self.description,
            'is_base_plan':       self.is_base_plan,
            'is_active':          self.is_active,
            'billing_cycle':      self.billing_cycle,
            'billing_cycle_name': self.get_billing_cycle_name(),
            'price':              float(self.price) if self.price is not None else None,
            'currency_id':        self.currency_id,
            'currency_code':      self.currency.currency_code if self.currency else None,
            'stripe_price_id':    self.stripe_price_id,
            'max_users':          self.max_users,
            'max_customers':      self.max_customers,
            'max_ai_messages':    self.max_ai_messages,
            'created_at':         self.created_at.isoformat() if self.created_at else None,
            'updated_at':         self.updated_at.isoformat() if self.updated_at else None,
        }


SubscriptionPlans = SubscriptionPlan


class ModuleMaster(db.Model):
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

    subscription_mappings = db.relationship('SubscriptionModuleMapping', back_populates='module', lazy='dynamic')
    tenant_mappings       = db.relationship('TenantModuleMapping', back_populates='module', lazy='dynamic')

    def __repr__(self):
        return f'<ModuleMaster {self.module_code}>'

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
    __tablename__ = 'Subscription_Module_Mapping'
    __table_args__ = (
        db.UniqueConstraint('subscription_id', 'module_id', name='uq_subscription_module'),
        {'schema': 'StreemLyne_MT'},
    )

    subscription_module_mapping_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    subscription_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Subscription_Plans.subscription_id'), nullable=False)
    module_id       = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Module_Master.module_id'), nullable=False)
    created_at      = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    subscription = db.relationship('SubscriptionPlan', back_populates='module_mappings')
    module       = db.relationship('ModuleMaster', back_populates='subscription_mappings')

    def to_dict(self):
        return {
            'subscription_module_mapping_id': self.subscription_module_mapping_id,
            'subscription_id': self.subscription_id,
            'module_id':       self.module_id,
            'module_name':     self.module.module_name if self.module else None,
            'created_at':      self.created_at.isoformat() if self.created_at else None,
        }


class TenantModuleMapping(db.Model):
    __tablename__ = 'Tenant_Module_Mapping'
    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'module_id', name='uq_tenant_module'),
        {'schema': 'StreemLyne_MT'},
    )

    tenant_module_mapping_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id  = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'))
    module_id  = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Module_Master.module_id'))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    tenant = db.relationship('TenantMaster', back_populates='module_mappings')
    module = db.relationship('ModuleMaster', back_populates='tenant_mappings')

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
    __tablename__ = 'Tenant_Subscription'
    __table_args__ = (
        db.Index('ix_tenant_subscription_tenant_id', 'tenant_id'),
        db.Index('idx_tenant_subscription_status', 'tenant_id', 'status'),
        db.Index('idx_tenant_subscription_trial_end', 'tenant_id', 'trial_end_date'),
        {'schema': 'StreemLyne_MT'},
    )

    tenant_subscription_mapping_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id               = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'))
    subscription_id         = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Subscription_Plans.subscription_id'))
    subscription_start_date = db.Column(db.Date)
    subscription_end_date   = db.Column(db.Date)
    is_active               = db.Column(db.Boolean)
    auto_renew              = db.Column(db.Boolean)
    created_at              = db.Column(db.DateTime(timezone=False), nullable=False, default=datetime.utcnow)
    updated_at              = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)
    status = db.Column(
        SAEnum('trialing', 'active', 'expired', 'canceled',
               name='subscription_status_enum', schema='StreemLyne_MT', create_type=False),
        nullable=False, default='trialing',
    )
    trial_end_date         = db.Column(db.DateTime(timezone=True))
    stripe_subscription_id = db.Column(db.String(255), unique=True)
    cancel_at_period_end   = db.Column(db.Boolean, default=False)
    current_period_start   = db.Column(db.DateTime(timezone=False))
    current_period_end     = db.Column(db.DateTime(timezone=False))

    tenant       = db.relationship('TenantMaster', back_populates='subscriptions')
    subscription = db.relationship('SubscriptionPlan', back_populates='tenant_subscriptions')

    def __repr__(self):
        return f'<TenantSubscription {self.tenant_id} [{self.status}]>'

    def is_currently_active(self):
        if self.status not in ('trialing', 'active'):
            return False
        if not self.is_active:
            return False
        now = datetime.now(timezone.utc)
        today = now.date()

        def _as_utc(dt):
            if dt is None: return None
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

        if self.status == 'trialing' and self.trial_end_date:
            if now > _as_utc(self.trial_end_date):
                return False
        if self.current_period_end and now > _as_utc(self.current_period_end):
            return False
        if self.subscription_end_date and today > self.subscription_end_date:
            return False
        return True

    def days_remaining_in_trial(self):
        if self.status != 'trialing' or not self.trial_end_date:
            return None
        now = datetime.now(timezone.utc)
        return max(0, (self.trial_end_date - now).days)

    def to_dict(self):
        return {
            'tenant_subscription_mapping_id': self.tenant_subscription_mapping_id,
            'tenant_id':               self.tenant_id,
            'subscription_id':         self.subscription_id,
            'subscription_name':       self.subscription.subscription_name if self.subscription else None,
            'subscription_start_date': self.subscription_start_date.isoformat() if self.subscription_start_date else None,
            'subscription_end_date':   self.subscription_end_date.isoformat() if self.subscription_end_date else None,
            'is_active':               self.is_active,
            'auto_renew':              self.auto_renew,
            'status':                  self.status,
            'trial_end_date':          self.trial_end_date.isoformat() if self.trial_end_date else None,
            'days_remaining_in_trial': self.days_remaining_in_trial(),
            'stripe_subscription_id':  self.stripe_subscription_id,
            'cancel_at_period_end':    self.cancel_at_period_end,
            'current_period_start':    self.current_period_start.isoformat() if self.current_period_start else None,
            'current_period_end':      self.current_period_end.isoformat() if self.current_period_end else None,
            'created_at':              self.created_at.isoformat() if self.created_at else None,
            'updated_at':              self.updated_at.isoformat() if self.updated_at else None,
        }


class SubscriptionInvoice(db.Model):
    __tablename__ = 'Subscription_Invoice'
    __table_args__ = (
        db.Index('idx_invoice_tenant', 'tenant_id', 'status'),
        db.Index('idx_subscription_invoice_stripe', 'stripe_invoice_id'),
        {'schema': 'StreemLyne_MT'},
    )

    invoice_id             = db.Column(db.SmallInteger().with_variant(db.Integer, "sqlite"), primary_key=True, autoincrement=True)
    tenant_id              = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False)
    subscription_id        = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Subscription.tenant_subscription_mapping_id'))
    stripe_invoice_id      = db.Column(db.String(255), unique=True)
    invoice_number         = db.Column(db.String(50), nullable=False, unique=True)
    amount                 = db.Column(db.Numeric(10, 2), nullable=False)
    tax_amount             = db.Column(db.Numeric(10, 2), default=0)
    total_amount           = db.Column(db.Numeric(10, 2), nullable=False)
    currency_id            = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'), nullable=False)
    status                 = db.Column(db.String(50), default='pending')
    period_start           = db.Column(db.Date)
    period_end             = db.Column(db.Date)
    invoice_pdf_url        = db.Column(db.Text)
    due_date               = db.Column(db.Date)
    paid_at                = db.Column(db.DateTime(timezone=True))
    created_at             = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at             = db.Column(db.DateTime(timezone=True), onupdate=datetime.utcnow)

    tenant       = db.relationship('TenantMaster', backref='subscription_invoices')
    subscription = db.relationship('TenantSubscription', backref='invoices')
    currency     = db.relationship('CurrencyMaster', backref='subscription_invoices')

    def __repr__(self):
        return f'<SubscriptionInvoice {self.invoice_number}>'

    def to_dict(self):
        return {
            'invoice_id': self.invoice_id, 'tenant_id': self.tenant_id,
            'subscription_id': self.subscription_id, 'stripe_invoice_id': self.stripe_invoice_id,
            'invoice_number': self.invoice_number, 'amount': float(self.amount) if self.amount else 0,
            'tax_amount': float(self.tax_amount) if self.tax_amount else 0,
            'total_amount': float(self.total_amount) if self.total_amount else 0,
            'currency_id': self.currency_id, 'currency_code': self.currency.currency_code if self.currency else None,
            'status': self.status,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
            'invoice_pdf_url': self.invoice_pdf_url, 'due_date': self.due_date.isoformat() if self.due_date else None,
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class PaymentAttempt(db.Model):
    __tablename__ = 'Payment_Attempt'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    payment_attempt_id       = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True, autoincrement=True)
    tenant_id                = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False)
    subscription_id          = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Subscription.tenant_subscription_mapping_id'), nullable=False)
    stripe_payment_intent_id = db.Column(db.String)
    invoice_id               = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Subscription_Invoice.invoice_id'))
    attempt_number           = db.Column(db.Integer, nullable=False)
    amount                   = db.Column(db.Numeric, nullable=False)
    currency_id              = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'), nullable=False)
    status                   = db.Column(db.String, nullable=False)
    failure_reason           = db.Column(db.Text)
    failure_code             = db.Column(db.String)
    created_at               = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    tenant       = db.relationship('TenantMaster', backref='payment_attempts')
    subscription = db.relationship('TenantSubscription', backref='payment_attempts')
    invoice      = db.relationship('SubscriptionInvoice', backref='payment_attempts')
    currency     = db.relationship('CurrencyMaster', backref='payment_attempts')


class SubscriptionPause(db.Model):
    __tablename__ = 'Subscription_Pause'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    pause_id                        = db.Column(db.SmallInteger().with_variant(db.Integer, "sqlite"), primary_key=True, autoincrement=True)
    tenant_subscription_mapping_id  = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Subscription.tenant_subscription_mapping_id'), nullable=False)
    paused_at    = db.Column(db.DateTime(timezone=True), nullable=False)
    resume_at    = db.Column(db.DateTime(timezone=True))
    pause_reason = db.Column(db.String)
    is_active    = db.Column(db.Boolean, default=True)

    subscription = db.relationship('TenantSubscription', backref='pauses')


class ProcessedWebhookEvent(db.Model):
    __tablename__ = 'Processed_Webhook_Event'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id              = db.Column(PG_UUID(as_uuid=False).with_variant(db.String(36), "sqlite"), primary_key=True, default=lambda: str(uuid.uuid4()))
    stripe_event_id = db.Column(db.String(255), unique=True, nullable=False)
    event_type      = db.Column(db.String(100))
    processed_at    = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<ProcessedWebhookEvent {self.stripe_event_id}>'

    def to_dict(self):
        return {
            'id': self.id, 'stripe_event_id': self.stripe_event_id,
            'event_type': self.event_type,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
        }


# ============================================================================
# SECTION 2: MASTER/REFERENCE DATA
# ============================================================================

class CountryMaster(db.Model):
    __tablename__ = 'Country_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    country_id       = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    country_name     = db.Column(db.String(100), nullable=False, unique=True, index=True)
    country_isd_code = db.Column(db.String(10), nullable=False)
    created_at       = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {'country_id': self.country_id, 'country_name': self.country_name,
                'country_isd_code': self.country_isd_code,
                'created_at': self.created_at.isoformat() if self.created_at else None}


class CurrencyMaster(db.Model):
    __tablename__ = 'Currency_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    currency_id   = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    currency_name = db.Column(db.String(100))
    currency_code = db.Column(db.String(10))
    created_at    = db.Column(db.DateTime(timezone=False))

    def to_dict(self):
        return {'currency_id': self.currency_id, 'currency_name': self.currency_name,
                'currency_code': self.currency_code,
                'created_at': self.created_at.isoformat() if self.created_at else None}


class DesignationMaster(db.Model):
    __tablename__ = 'Designation_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    designation_id          = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    designation_description = db.Column(db.String(100), nullable=False, unique=True)
    created_at              = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {'designation_id': self.designation_id,
                'designation_description': self.designation_description,
                'created_at': self.created_at.isoformat() if self.created_at else None}


class ServicesMaster(db.Model):
    __tablename__ = 'Services_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    service_id          = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
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

    tenant   = db.relationship('TenantMaster', back_populates='services')
    currency = db.relationship('CurrencyMaster', backref='services')

    def __repr__(self):
        return f'<ServicesMaster {self.service_code}>'

    def to_dict(self):
        return {
            'service_id': self.service_id, 'tenant_id': self.tenant_id,
            'service_code': self.service_code, 'service_title': self.service_title,
            'service_description': self.service_description, 'service_rate': self.service_rate,
            'currency_id': self.currency_id,
            'currency_code': self.currency.currency_code if self.currency else None,
            'date_from': self.date_from.isoformat() if self.date_from else None,
            'date_to': self.date_to.isoformat() if self.date_to else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class UOMMaster(db.Model):
    __tablename__ = 'UOM_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    uom_id          = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    uom_description = db.Column(db.String(50), nullable=False, unique=True)
    created_at      = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {'uom_id': self.uom_id, 'uom_description': self.uom_description,
                'created_at': self.created_at.isoformat() if self.created_at else None}


class StageMaster(db.Model):
    __tablename__ = 'Stage_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    stage_id           = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    stage_name         = db.Column(db.String(100), nullable=False, unique=True)
    stage_description  = db.Column(db.String)
    preceding_stage_id = db.Column(db.SmallInteger)
    stage_type         = db.Column(db.SmallInteger, nullable=False)

    opportunities = db.relationship('OpportunityDetails', back_populates='stage')

    def to_dict(self):
        return {'stage_id': self.stage_id, 'stage_name': self.stage_name,
                'stage_description': self.stage_description,
                'preceding_stage_id': self.preceding_stage_id, 'stage_type': self.stage_type}


class SupplierMaster(db.Model):
    __tablename__ = 'Supplier_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    supplier_id           = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    supplier_company_name = db.Column(db.String(255), nullable=False)
    supplier_contact_name = db.Column(db.String(255))
    supplier_provisions   = db.Column(db.SmallInteger)
    created_at            = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {'supplier_id': self.supplier_id,
                'supplier_company_name': self.supplier_company_name,
                'supplier_contact_name': self.supplier_contact_name,
                'supplier_provisions': self.supplier_provisions,
                'created_at': self.created_at.isoformat() if self.created_at else None}

class PriceListMaster(db.Model):
    __tablename__  = 'PriceList_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    pricelist_id      = db.Column(db.Integer, primary_key=True, autoincrement=True)
    tenant_id         = db.Column(db.String,  nullable=False, index=True)
    category          = db.Column(db.String,  nullable=False)
    item_name         = db.Column(db.String,  nullable=False)
    description       = db.Column(db.Text)
    base_price        = db.Column(db.Numeric(10, 2))
    unit              = db.Column(db.String,  default='each')
    item_code         = db.Column(db.String(50))
    dimension_based   = db.Column(db.Boolean, default=False)
    dimension_formula = db.Column(db.String)
    door_type         = db.Column(db.String(100))
    width             = db.Column(db.Integer)
    height            = db.Column(db.Integer)
    depth             = db.Column(db.Integer)
    brand             = db.Column(db.String(50))
    colour            = db.Column(db.String(255))
    alias_codes       = db.Column(db.Text)
    # Gafbros fields
    list_type         = db.Column(db.String,  default='Standard')   # 'Standard' | 'Bespoke'
    variant_id        = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Product_Variant.variant_id'), nullable=True)
    min_qty           = db.Column(db.Integer, default=1)
    effective_from    = db.Column(db.Date,    nullable=True)
    effective_to      = db.Column(db.Date,    nullable=True)
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at        = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    variant = db.relationship('ProductVariant', backref='pricelist_entries')

    def to_dict(self):
        return {
            'pricelist_id':      self.pricelist_id,
            'tenant_id':         self.tenant_id,
            'category':          self.category,
            'item_name':         self.item_name,
            'description':       self.description,
            'base_price':        float(self.base_price) if self.base_price is not None else None,
            'unit':              self.unit or 'each',
            'item_code':         self.item_code,
            'dimension_based':   self.dimension_based or False,
            'dimension_formula': self.dimension_formula,
            'door_type':         self.door_type,
            'width':             self.width,
            'height':            self.height,
            'depth':             self.depth,
            'brand':             self.brand,
            'colour':            self.colour,
            'alias_codes':       self.alias_codes,
            'list_type':         self.list_type or 'Standard',
            'variant_id':        self.variant_id,
            'variant_label':     self.variant.variant_label if self.variant else None,
            'min_qty':           self.min_qty or 1,
            'effective_from':    self.effective_from.isoformat() if self.effective_from else None,
            'effective_to':      self.effective_to.isoformat() if self.effective_to else None,
            'created_at':        self.created_at.isoformat() if self.created_at else None,
            'updated_at':        self.updated_at.isoformat() if self.updated_at else None,
        }


class ProductMaster(db.Model):
    __tablename__  = 'Product_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    product_id  = db.Column(db.Integer, primary_key=True, autoincrement=True)
    tenant_id   = db.Column(db.String,  nullable=False, index=True)
    sku         = db.Column(db.String,  nullable=True)
    name        = db.Column(db.String,  nullable=False)
    description = db.Column(db.Text,    nullable=True)
    category    = db.Column(db.String,  nullable=True)
    active      = db.Column(db.Boolean, default=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    variants = db.relationship('ProductVariant', back_populates='product',
                               lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<ProductMaster {self.product_id}: {self.name}>'

    def to_dict(self):
        return {
            'product_id':  self.product_id,
            'tenant_id':   self.tenant_id,
            'sku':         self.sku,
            'name':        self.name,
            'description': self.description,
            'category':    self.category,
            'active':      self.active,
            'created_at':  self.created_at.isoformat() if self.created_at else None,
            'updated_at':  self.updated_at.isoformat() if self.updated_at else None,
        }


class ProductVariant(db.Model):
    __tablename__  = 'Product_Variant'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    variant_id     = db.Column(db.Integer, primary_key=True, autoincrement=True)
    product_id     = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Product_Master.product_id',
                               ondelete='CASCADE'), nullable=False, index=True)
    sku_variant    = db.Column(db.String,  nullable=True)
    variant_label  = db.Column(db.String,  nullable=False)
    dimensions     = db.Column(db.JSON,    nullable=True)   # {length, width, height, thickness}
    material_type  = db.Column(db.String,  nullable=True)
    material_grade = db.Column(db.String,  nullable=True)
    gsm_thickness  = db.Column(db.Numeric(8, 2), nullable=True)
    print_colors   = db.Column(db.String,  nullable=True)   # '1 Color' | 'Multi Color'
    multi_side     = db.Column(db.Boolean, default=False)
    print_size     = db.Column(db.String,  nullable=True)
    treatments     = db.Column(db.JSON,    nullable=True)   # ['Embossment', 'Foil Stamping', ...]
    active         = db.Column(db.Boolean, default=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at     = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product              = db.relationship('ProductMaster', back_populates='variants')
    supplier_price_lists = db.relationship('SupplierPriceList', back_populates='variant',
                                           lazy='dynamic')

    def __repr__(self):
        return f'<ProductVariant {self.variant_id}: {self.variant_label}>'

    def to_dict(self):
        return {
            'variant_id':     self.variant_id,
            'product_id':     self.product_id,
            'product_name':   self.product.name if self.product else None,
            'sku_variant':    self.sku_variant,
            'variant_label':  self.variant_label,
            'dimensions':     self.dimensions,
            'material_type':  self.material_type,
            'material_grade': self.material_grade,
            'gsm_thickness':  float(self.gsm_thickness) if self.gsm_thickness else None,
            'print_colors':   self.print_colors,
            'multi_side':     self.multi_side,
            'print_size':     self.print_size,
            'treatments':     self.treatments,
            'active':         self.active,
            'created_at':     self.created_at.isoformat() if self.created_at else None,
            'updated_at':     self.updated_at.isoformat() if self.updated_at else None,
        }


class SupplierPriceList(db.Model):
    __tablename__  = 'Supplier_Price_List'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    spl_id          = db.Column(db.Integer, primary_key=True, autoincrement=True)
    supplier_id     = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Supplier_Master.supplier_id',
                                ondelete='RESTRICT'), nullable=False, index=True)
    variant_id      = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Product_Variant.variant_id',
                                ondelete='RESTRICT'), nullable=False, index=True)
    unit_cost       = db.Column(db.Numeric(10, 2), nullable=False)
    currency        = db.Column(db.String,  default='GBP')
    min_qty         = db.Column(db.Integer, default=1)
    lead_time_weeks = db.Column(db.Integer, nullable=True)
    effective_from  = db.Column(db.Date,    nullable=False)
    effective_to    = db.Column(db.Date,    nullable=True)
    notes           = db.Column(db.Text,    nullable=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    supplier = db.relationship('SupplierMaster', backref='price_lists')
    variant  = db.relationship('ProductVariant',  back_populates='supplier_price_lists')

    def __repr__(self):
        return


class RoleMaster(db.Model):
    __tablename__ = 'Role_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    role_id          = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    role_name        = db.Column(db.String(100), nullable=False, unique=True)
    role_description = db.Column(db.String)
    is_system        = db.Column(db.Boolean, nullable=False)
    created_at       = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    role_permission_mappings = db.relationship('RolePermissionMapping', back_populates='role',
                                               lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<RoleMaster {self.role_name}>'

    def to_dict(self):
        return {'role_id': self.role_id, 'role_name': self.role_name,
                'role_description': self.role_description, 'is_system': self.is_system,
                'created_at': self.created_at.isoformat() if self.created_at else None}


class PermissionCatalog(db.Model):
    __tablename__ = 'Permission_Catalog'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    permission_id   = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    permission_code = db.Column(db.String(100), nullable=False, unique=True)
    description     = db.Column(db.String)
    created_at      = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    permission_role_mappings = db.relationship('RolePermissionMapping', back_populates='permission', lazy='dynamic')

    def to_dict(self):
        return {'permission_id': self.permission_id, 'permission_code': self.permission_code,
                'description': self.description,
                'created_at': self.created_at.isoformat() if self.created_at else None}


class RolePermissionMapping(db.Model):
    __tablename__ = 'Role_Permission_Mapping'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    role_permission_mapping_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    role_id       = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Role_Master.role_id'), nullable=False)
    permission_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Permission_Catalog.permission_id'), nullable=False)
    created_at    = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    edited_at     = db.Column(db.Date)

    role       = db.relationship('RoleMaster', back_populates='role_permission_mappings')
    permission = db.relationship('PermissionCatalog', back_populates='permission_role_mappings')

    def to_dict(self):
        return {'role_permission_mapping_id': self.role_permission_mapping_id,
                'role_id': self.role_id, 'role_name': self.role.role_name if self.role else None,
                'permission_id': self.permission_id,
                'permission_code': self.permission.permission_code if self.permission else None,
                'created_at': self.created_at.isoformat() if self.created_at else None}


class TaxMaster(db.Model):
    __tablename__ = 'Tax_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    tax_id          = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tax_name        = db.Column(db.String(100), nullable=False)
    tax_rate        = db.Column(db.Numeric(5, 2), nullable=False)
    tax_description = db.Column(db.String(255))
    is_active       = db.Column(db.Boolean, nullable=False, default=True)
    created_at      = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {'tax_id': self.tax_id, 'tax_name': self.tax_name,
                'tax_rate': float(self.tax_rate) if self.tax_rate else 0,
                'tax_description': self.tax_description, 'is_active': self.is_active,
                'created_at': self.created_at.isoformat() if self.created_at else None}


class ContactMethodMaster(db.Model):
    __tablename__ = 'Contact_Method_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    contact_method_id  = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    method_name        = db.Column(db.String(50), nullable=False, unique=True)
    method_description = db.Column(db.String(255))
    is_active          = db.Column(db.Boolean, nullable=False, default=True)
    created_at         = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {'contact_method_id': self.contact_method_id, 'method_name': self.method_name,
                'method_description': self.method_description, 'is_active': self.is_active,
                'created_at': self.created_at.isoformat() if self.created_at else None}


# ============================================================================
# SECTION 3: CORE BUSINESS MODELS
# ============================================================================

class ClientMaster(db.Model):
    __tablename__ = 'Client_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    client_id           = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id           = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    country_id          = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Country_Master.country_id'))
    default_currency_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'))
    client_company_name = db.Column(db.String(255), nullable=False)
    client_contact_name = db.Column(db.String(255))
    address             = db.Column(db.String)
    post_code           = db.Column(db.String(20))
    client_phone        = db.Column(db.String(50))
    client_email        = db.Column(db.String(255))
    client_website      = db.Column(db.String(255))
    created_at          = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    stage               = db.Column(db.String(50), nullable=True)
    stage_updated_at    = db.Column(db.DateTime(timezone=True), nullable=True)
    is_deleted          = db.Column(db.Boolean, default=False, nullable=True)
    assigned_employee_id    = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'), nullable=True)
    created_by_employee_id  = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'), nullable=True)
    tenant             = db.relationship('TenantMaster', back_populates='clients')
    country            = db.relationship('CountryMaster', backref='clients')
    default_currency   = db.relationship('CurrencyMaster', backref='default_currency_clients')
    opportunities      = db.relationship('OpportunityDetails', back_populates='client', lazy='dynamic')
    interactions       = db.relationship('ClientInteractions', back_populates='client', lazy='dynamic')
    projects           = db.relationship('ProjectDetails', back_populates='client', lazy='dynamic')
    proposals          = db.relationship('ProposalMaster', back_populates='client', lazy='dynamic')
    invoices           = db.relationship('InvoiceMaster', back_populates='client', lazy='dynamic')
    customer_auths     = db.relationship('CustomerAuth', back_populates='client', lazy='dynamic')
    case_documents     = db.relationship('CaseDocuments', back_populates='client', lazy='dynamic')
    customer_documents = db.relationship('CustomerDocuments', back_populates='client', lazy='dynamic')

    def __repr__(self):
        return f'<ClientMaster {self.client_id}: {self.client_company_name}>'

    def to_dict(self):
        return {
            'client_id': self.client_id, 'tenant_id': self.tenant_id,
            'client_company_name': self.client_company_name,
            'client_contact_name': self.client_contact_name,
            'address': self.address,
            'country_id': self.country_id,
            'country_name': self.country.country_name if self.country else None,
            'post_code': self.post_code, 'client_phone': self.client_phone,
            'client_email': self.client_email, 'client_website': self.client_website,
            'default_currency_id': self.default_currency_id,
            'default_currency_code': self.default_currency.currency_code if self.default_currency else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'stage': self.stage,
            'stage_updated_at': self.stage_updated_at.isoformat() if self.stage_updated_at else None,
            # Legacy aliases
            'id': self.client_id, 'name': self.client_company_name,
            'company_name': self.client_company_name,
            'contact_name': self.client_contact_name,
            'client_name': self.client_contact_name or self.client_company_name,
            'display_name': self.client_contact_name or self.client_company_name,
            'full_name': self.client_contact_name or self.client_company_name,
            'email': self.client_email, 'phone': self.client_phone,
            'postcode': self.post_code,
            'assigned_employee_id':   self.assigned_employee_id,
            'created_by_employee_id': self.created_by_employee_id,
        }


class ClientInteractions(db.Model):
    __tablename__ = 'Client_Interactions'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    interaction_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    client_id      = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=False)
    contact_date   = db.Column(db.Date, nullable=False)
    contact_method = db.Column(db.SmallInteger, nullable=False)
    notes          = db.Column(db.String)
    next_steps     = db.Column(db.String)
    reminder_date  = db.Column(db.Date)
    created_at     = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    client = db.relationship('ClientMaster', back_populates='interactions')

    def __repr__(self):
        return f'<ClientInteractions {self.interaction_id}>'

    def to_dict(self):
        return {
            'interaction_id': self.interaction_id, 'client_id': self.client_id,
            'contact_date': self.contact_date.isoformat() if self.contact_date else None,
            'contact_method': self.contact_method,
            'notes': self.notes, 'next_steps': self.next_steps,
            'reminder_date': self.reminder_date.isoformat() if self.reminder_date else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class EmployeeMaster(db.Model):
    __tablename__ = 'Employee_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    employee_id             = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
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

    tenant                 = db.relationship('TenantMaster', back_populates='employees')
    designation            = db.relationship('DesignationMaster', backref='employees')
    owned_opportunities    = db.relationship('OpportunityDetails', foreign_keys='OpportunityDetails.opportunity_owner_employee_id', back_populates='opportunity_owner')
    assigned_opportunities = db.relationship('OpportunityDetails', foreign_keys='OpportunityDetails.assigned_to_employee_id', back_populates='assigned_employee')
    managed_projects       = db.relationship('ProjectDetails', back_populates='employee')
    energy_contracts       = db.relationship('EnergyContractMaster', back_populates='employee')
    user                   = db.relationship('UserMaster', back_populates='employee', uselist=False)

    def __repr__(self):
        return f'<EmployeeMaster {self.employee_id}: {self.employee_name}>'

    def get_roles(self) -> list:
        if not self.role_ids:
            return []
        try:
            return [int(r.strip()) for r in self.role_ids.split(',') if r.strip()]
        except (ValueError, AttributeError):
            return []

    def to_dict(self):
        return {
            'employee_id': self.employee_id, 'tenant_id': self.tenant_id,
            'employee_name': self.employee_name,
            'employee_designation_id': self.employee_designation_id,
            'designation_name': self.designation.designation_description if self.designation else None,
            'phone': self.phone, 'email': self.email,
            'date_of_birth': self.date_of_birth.isoformat() if self.date_of_birth else None,
            'date_of_joining': self.date_of_joining.isoformat() if self.date_of_joining else None,
            'role_ids': self.role_ids,
            'commission_percentage': self.commission_percentage,
            'created_on': self.created_on.isoformat() if self.created_on else None,
            'updated_on': self.updated_on.isoformat() if self.updated_on else None,
        }


class UserMaster(db.Model):
    __tablename__ = 'User_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}
 
    user_id                = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    employee_id            = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'))
    user_name              = db.Column(db.String(100), unique=True)
    password               = db.Column(db.String(255))
    created_at             = db.Column(db.DateTime(timezone=True),  nullable=False, default=datetime.utcnow)
    updated_at             = db.Column(db.Date, onupdate=datetime.utcnow)
    tenant_id              = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'))
    is_active              = db.Column(db.Boolean, default=False)       # False until invite accepted
    is_invite_pending      = db.Column(db.Boolean, default=False)
    invite_token           = db.Column(db.String(100), unique=True)     # cleared after acceptance
    invite_expires_at      = db.Column(db.DateTime(timezone=False))     # UTC expiry
    created_by_employee_id = db.Column(db.SmallInteger)                 # who sent the invite
 
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
        return generate_staff_token(
            user_id=self.user_id,
            employee_id=self.employee_id,
            secret_key=secret_key,
        )
 
    @property
    def is_owner(self) -> bool:
        from typing import cast
        return any(r.role_name == 'Tenant Owner' for r in cast(list, self.roles or []) if hasattr(r, 'role_name'))
 
    def to_dict(self):
        from typing import cast
        role_names = [r.role_name for r in cast(list, self.roles or [])]
        return {
            'user_id':      self.user_id,
            'employee_id':  self.employee_id,
            'user_name':    self.user_name,
            'employee_name': self.employee.employee_name if self.employee else None,
            'email':        self.employee.email          if self.employee else None,
            'first_name':   (self.employee.employee_name.split()[0]
                             if self.employee and self.employee.employee_name else ''),
            'last_name':    (' '.join(self.employee.employee_name.split()[1:])
                             if self.employee and self.employee.employee_name else ''),
            'full_name':    self.employee.employee_name if self.employee else None,
            'phone':        self.employee.phone          if self.employee else None,
            'roles':        role_names,
            'role':         role_names[0] if role_names else 'user',
            'is_owner':     self.is_owner,
            'is_active':    self.is_active,
            'is_verified':  True,
            'is_invite_pending': self.is_invite_pending,
            'created_at':   self.created_at.isoformat() if self.created_at else None,
            'updated_at':   self.updated_at.isoformat() if self.updated_at else None,
        }

class AIUsageLog(db.Model):
    __tablename__ = 'AI_Usage_Log'
    __table_args__ = {'schema': 'StreemLyne_MT'}
 
    id         = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    tenant_id  = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id',
                           ondelete='CASCADE'), nullable=False, index=True)
    user_id    = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.User_Master.user_id',
                           ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
 
    tenant = db.relationship('TenantMaster', backref='ai_usage_logs')
    user   = db.relationship('UserMaster',   backref='ai_usage_logs')
 
    def to_dict(self):
        return {
            'id':         self.id,
            'tenant_id':  self.tenant_id,
            'user_id':    self.user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class UserRoleMapping(db.Model):
    __tablename__ = 'User_Role_Mapping'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    user_id = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.User_Master.user_id'), primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Role_Master.role_id'), primary_key=True)


class CustomerAuth(db.Model):
    __tablename__ = 'Customer_Auth'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    customer_user_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    client_id        = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=False)
    tenant_id        = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False)
    email            = db.Column(db.String(255), unique=True, nullable=False)
    password_hash    = db.Column(db.Text, nullable=False)
    is_active        = db.Column(db.Boolean, default=True)
    created_at       = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    client          = db.relationship('ClientMaster', back_populates='customer_auths')
    password_resets = db.relationship('CustomerPasswordReset', back_populates='customer_user', lazy='dynamic')

    def set_password(self, p: str): self.password_hash = generate_password_hash(p)
    def check_password(self, p: str): return check_password_hash(self.password_hash, p)

    def generate_jwt_token(self, secret_key: str) -> str:
        from services.auth_service import generate_customer_token
        return generate_customer_token(customer_user_id=self.customer_user_id,
                                       client_id=self.client_id, tenant_id=self.tenant_id,
                                       secret_key=secret_key)

    def to_dict(self):
        return {'customer_user_id': self.customer_user_id, 'client_id': self.client_id,
                'tenant_id': self.tenant_id, 'email': self.email, 'is_active': self.is_active,
                'created_at': self.created_at.isoformat() if self.created_at else None}


class CustomerPasswordReset(db.Model):
    __tablename__ = 'Customer_Password_Reset'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id               = db.Column(db.Integer, primary_key=True, autoincrement=True)
    customer_user_id = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Customer_Auth.customer_user_id'))
    token            = db.Column(db.Text, nullable=False)
    expires_at       = db.Column(db.DateTime(timezone=False), nullable=False)
    used             = db.Column(db.Boolean, default=False)
    created_at       = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    customer_user = db.relationship('CustomerAuth', back_populates='password_resets')

    def is_valid(self): return not self.used and datetime.utcnow() < self.expires_at

    def to_dict(self):
        return {'id': self.id, 'customer_user_id': self.customer_user_id,
                'expires_at': self.expires_at.isoformat() if self.expires_at else None,
                'used': self.used, 'created_at': self.created_at.isoformat() if self.created_at else None}

class OpportunityDetails(db.Model):
    __tablename__ = 'Opportunity_Details'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    opportunity_id                = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    client_id                     = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))
    tenant_id                     = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'))
    opportunity_owner_employee_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'))
    assigned_to_employee_id       = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'))
    stage_id                      = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Stage_Master.stage_id'), nullable=False)
    currency_id                   = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'))
    service_id                    = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Services_Master.service_id'))
    opportunity_title             = db.Column(db.String(255), nullable=False)
    opportunity_description       = db.Column(db.String)
    opportunity_date              = db.Column(db.Date)
    opportunity_value             = db.Column(db.SmallInteger)
    mpan_mpr                      = db.Column(db.String)
    business_name                 = db.Column(db.String(255))
    contact_person                = db.Column(db.String(255))
    tel_number                    = db.Column(db.String(50))
    email                         = db.Column(db.String(255))
    start_date                    = db.Column(db.Date)
    end_date                      = db.Column(db.Date)
    Misc_Col1                     = db.Column(db.String(255))
    deleted_at                    = db.Column(db.DateTime(timezone=False))
    created_at                    = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    client            = db.relationship('ClientMaster', back_populates='opportunities')
    opportunity_owner = db.relationship('EmployeeMaster', foreign_keys=[opportunity_owner_employee_id], back_populates='owned_opportunities')
    assigned_employee = db.relationship('EmployeeMaster', foreign_keys=[assigned_to_employee_id], back_populates='assigned_opportunities')
    stage             = db.relationship('StageMaster', back_populates='opportunities')
    currency          = db.relationship('CurrencyMaster', backref='opportunities')
    service           = db.relationship('ServicesMaster', backref='opportunities')
    projects          = db.relationship('ProjectDetails', back_populates='opportunity', lazy='dynamic')
    case_documents    = db.relationship('CaseDocuments', back_populates='opportunity', lazy='dynamic')
    customer_documents = db.relationship('CustomerDocuments', back_populates='opportunity', lazy='dynamic')

    def __repr__(self):
        return f'<OpportunityDetails {self.opportunity_id}: {self.opportunity_title}>'

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def to_dict(self):
        return {
            'opportunity_id': self.opportunity_id, 'client_id': self.client_id,
            'client_name': self.client.client_company_name if self.client else None,
            'tenant_id': self.tenant_id, 'opportunity_title': self.opportunity_title,
            'opportunity_description': self.opportunity_description,
            'opportunity_date': self.opportunity_date.isoformat() if self.opportunity_date else None,
            'opportunity_owner_employee_id': self.opportunity_owner_employee_id,
            'opportunity_owner_name': self.opportunity_owner.employee_name if self.opportunity_owner else None,
            'assigned_to_employee_id': self.assigned_to_employee_id,
            'assigned_employee_name': self.assigned_employee.employee_name if self.assigned_employee else None,
            'stage_id': self.stage_id, 'stage_name': self.stage.stage_name if self.stage else None,
            'opportunity_value': self.opportunity_value,
            'currency_id': self.currency_id,
            'currency_code': self.currency.currency_code if self.currency else None,
            'service_id': self.service_id,
            'service_title': self.service.service_title if self.service else None,
            'mpan_mpr': self.mpan_mpr, 'business_name': self.business_name,
            'contact_person': self.contact_person, 'tel_number': self.tel_number,
            'email': self.email,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'Misc_Col1': self.Misc_Col1,
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ProjectDetails(db.Model):
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

    client           = db.relationship('ClientMaster', back_populates='projects')
    opportunity      = db.relationship('OpportunityDetails', back_populates='projects')
    employee         = db.relationship('EmployeeMaster', back_populates='managed_projects')
    energy_contracts = db.relationship('EnergyContractMaster', back_populates='project', lazy='dynamic')
    invoices         = db.relationship('InvoiceMaster', back_populates='project', lazy='dynamic')

    def __repr__(self):
        return f'<ProjectDetails {self.project_id}: {self.project_title}>'

    def to_dict(self):
        return {
            'project_id': self.project_id, 'client_id': self.client_id,
            'opportunity_id': self.opportunity_id,
            'opportunity_title': self.opportunity.opportunity_title if self.opportunity else None,
            'employee_id': self.employee_id,
            'employee_name': self.employee.employee_name if self.employee else None,
            'project_title': self.project_title, 'project_description': self.project_description,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'address': self.address, 'Misc_Col1': self.Misc_Col1, 'Misc_Col2': self.Misc_Col2,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class CaseDocuments(db.Model):
    __tablename__ = 'Case_Documents'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id             = db.Column(db.Integer, primary_key=True, autoincrement=True)
    opportunity_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Opportunity_Details.opportunity_id'), nullable=False)
    client_id      = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=False)
    tenant_id      = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False)
    uploaded_by    = db.Column(db.String(255), nullable=False)
    document_type  = db.Column(db.String(100))
    file_name      = db.Column(db.String(255), nullable=False)
    blob_url       = db.Column(db.Text, nullable=False)
    created_at     = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    opportunity = db.relationship('OpportunityDetails', back_populates='case_documents')
    client      = db.relationship('ClientMaster', back_populates='case_documents')

    def to_dict(self):
        return {'id': self.id, 'opportunity_id': self.opportunity_id, 'client_id': self.client_id,
                'tenant_id': self.tenant_id, 'uploaded_by': self.uploaded_by,
                'document_type': self.document_type, 'file_name': self.file_name,
                'blob_url': self.blob_url,
                'created_at': self.created_at.isoformat() if self.created_at else None}


class CustomerDocuments(db.Model):
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

    def to_dict(self):
        return {'id': self.id, 'client_id': self.client_id, 'opportunity_id': self.opportunity_id,
                'file_url': self.file_url, 'file_name': self.file_name,
                'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None}


class EnergyContractMaster(db.Model):
    __tablename__ = 'Energy_Contract_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    energy_contract_master_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    project_id          = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Project_Details.project_id'))
    employee_id         = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'), nullable=False)
    supplier_id         = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Supplier_Master.supplier_id'), nullable=False)
    service_id          = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Services_Master.service_id'), nullable=False)
    currency_id         = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'))
    contract_start_date = db.Column(db.Date, nullable=False)
    contract_end_date   = db.Column(db.Date, nullable=False)
    terms_of_sale       = db.Column(db.String, nullable=False)
    unit_rate           = db.Column(db.Float(precision=24), nullable=False)
    document_details    = db.Column(db.String)
    mpan_number         = db.Column(db.String)
    created_at          = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at          = db.Column(db.DateTime(timezone=True), onupdate=datetime.utcnow)

    project  = db.relationship('ProjectDetails', back_populates='energy_contracts')
    employee = db.relationship('EmployeeMaster', back_populates='energy_contracts')
    supplier = db.relationship('SupplierMaster', backref='energy_contracts')
    service  = db.relationship('ServicesMaster', backref='energy_contracts')
    currency = db.relationship('CurrencyMaster', backref='energy_contracts')

    def to_dict(self):
        return {
            'energy_contract_master_id': self.energy_contract_master_id,
            'project_id': self.project_id, 'employee_id': self.employee_id,
            'employee_name': self.employee.employee_name if self.employee else None,
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier.supplier_company_name if self.supplier else None,
            'service_id': self.service_id,
            'service_title': self.service.service_title if self.service else None,
            'currency_id': self.currency_id,
            'currency_code': self.currency.currency_code if self.currency else None,
            'contract_start_date': self.contract_start_date.isoformat() if self.contract_start_date else None,
            'contract_end_date': self.contract_end_date.isoformat() if self.contract_end_date else None,
            'terms_of_sale': self.terms_of_sale, 'unit_rate': self.unit_rate,
            'document_details': self.document_details, 'mpan_number': self.mpan_number,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class TasksMaster(db.Model):
    """Tasks / scheduling — maps to Tasks_Master table."""
    __tablename__ = 'Tasks_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    task_id                  = db.Column(db.String(50), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id                = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False)
    type                     = db.Column(db.String, default='job')
    title                    = db.Column(db.String, nullable=False)
    date                     = db.Column(db.Date)
    start_date               = db.Column(db.Date, nullable=False)
    end_date                 = db.Column(db.Date)
    start_time               = db.Column(db.Time)
    end_time                 = db.Column(db.Time)
    estimated_hours          = db.Column(db.Numeric(5, 2))
    assigned_to_employee_id  = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'))
    team_member              = db.Column(db.String)
    client_id                = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))
    customer_name            = db.Column(db.String)
    project_id               = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Project_Details.project_id'))
    opportunity_id           = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Opportunity_Details.opportunity_id'))
    job_type                 = db.Column(db.String)
    notes                    = db.Column(db.Text)
    priority                 = db.Column(db.String, default='Medium')
    status                   = db.Column(db.String, default='Scheduled')
    created_by_employee_id   = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'), nullable=False)
    created_at               = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by_employee_id   = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'))
    updated_at               = db.Column(db.DateTime)
    work_stage               = db.Column(db.String(50))

    def to_dict(self):
        return {
            'task_id': self.task_id, 'tenant_id': self.tenant_id,
            'type': self.type, 'title': self.title,
            'date': self.date.isoformat() if self.date else None,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'team_member': self.team_member, 'client_id': self.client_id,
            'customer_name': self.customer_name, 'project_id': self.project_id,
            'estimated_hours': float(self.estimated_hours) if self.estimated_hours else None,
            'notes': self.notes, 'priority': self.priority, 'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================================
# SECTION 4: PROPOSALS & INVOICES
# ============================================================================

class ProposalMaster(db.Model):
    __tablename__ = 'Proposal_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    quote_id = db.Column(db.String(10), unique=True, nullable=False,
                         server_default=text("'QUO-' || lpad(nextval('\"StreemLyne_MT\".quote_id_seq')::text, 3, '0')"))
    proposal_id      = db.Column(db.Integer, primary_key=True)
    tenant_id        = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), index=True)  # ← ADD THIS
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

    client           = db.relationship('ClientMaster', back_populates='proposals')
    currency         = db.relationship('CurrencyMaster', backref='proposals')
    proposal_details = db.relationship('ProposalDetails', back_populates='proposal', lazy='dynamic', cascade='all, delete-orphan')
    invoices         = db.relationship('InvoiceMaster', back_populates='proposal', lazy='dynamic')

    def to_dict(self):
        return {
            'quote_id': self.quote_id, 'proposal_id': self.proposal_id,
            'client_id': self.client_id,
            'client_name': self.client.client_company_name if self.client else None,
            'project_id': self.project_id, 'currency_id': self.currency_id,
            'sub_total': float(self.sub_total) if self.sub_total else None,
            'total_amount': float(self.total_amount) if self.total_amount else None,
            'discount_percent': self.discount_percent,
            'discount_amount': float(self.discount_amount) if self.discount_amount else None,
            'tax_id': self.tax_id, 'customer_name': self.customer_name, 'notes': self.notes,
            'company_details': self.company_details, 'payment_details': self.payment_details,
            'tax_breakdown': self.tax_breakdown,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ProposalDetails(db.Model):
    __tablename__ = 'Proposal_Details'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    proposal_details_id = db.Column(db.Integer, primary_key=True)
    proposal_id         = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Proposal_Master.proposal_id'), nullable=False)
    quantity            = db.Column(db.Numeric(10, 2), nullable=False)
    amount              = db.Column(db.Numeric(12, 2))
    service_id          = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Services_Master.service_id'), nullable=False)
    uom_id              = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.UOM_Master.uom_id'), nullable=False)
    service_name        = db.Column(db.String(255))
    created_at          = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at          = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    proposal = db.relationship('ProposalMaster', back_populates='proposal_details')
    service  = db.relationship('ServicesMaster', backref='proposal_details')
    uom      = db.relationship('UOMMaster', backref='proposal_details')

    def to_dict(self):
        return {
            'proposal_details_id': self.proposal_details_id, 'proposal_id': self.proposal_id,
            'service_id': self.service_id,
            'service_title': self.service.service_title if self.service else None,
            'service_name': self.service_name,
            'amount': float(self.amount) if self.amount else None,
            'uom_id': self.uom_id, 'quantity': float(self.quantity),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

class Quotation(db.Model):
    __tablename__ = 'Quotations'
    __table_args__ = {'schema': 'StreemLyne_MT'}
 
    quotation_id             = db.Column(db.Integer, primary_key=True, autoincrement=True)
    tenant_id                = db.Column(db.String, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    client_id                = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=False)
    project_id               = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Project_Details.project_id'), nullable=True)
    employee_id              = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'), nullable=True)
    reference_number         = db.Column(db.String, nullable=False, unique=True)
    total                    = db.Column(db.Numeric(10, 2), default=0)
    status                   = db.Column(db.String, default='Draft')
    notes                    = db.Column(db.Text, nullable=True)
    valid_until              = db.Column(db.DateTime(timezone=False), nullable=True)
    created_at               = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    updated_at               = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)
 
    # Customer snapshot
    customer_name            = db.Column(db.String(255), nullable=True)
    customer_address         = db.Column(db.Text, nullable=True)
    customer_phone           = db.Column(db.String(50), nullable=True)
    customer_email           = db.Column(db.String(255), nullable=True)
 
    # Pricing
    vat_percentage           = db.Column(db.Numeric(5, 2), default=20.00)
    global_discount_percent  = db.Column(db.Numeric(5, 2), default=0)
 
    # Interior design fields
    door_type                = db.Column(db.String(50), default='Carcass Only')
    room_type                = db.Column(db.String(50), default='Kitchen')
    carcass_colour           = db.Column(db.String(100), nullable=True)
    door_colour              = db.Column(db.String(100), nullable=True)
    door_style               = db.Column(db.String(100), nullable=True)
    panelwork_colour         = db.Column(db.String(255), nullable=True)
    room_name                = db.Column(db.String(255), nullable=True)
    section_discounts        = db.Column(db.JSON, default=dict)
    filler_type              = db.Column(db.String(50), default='Basic Slab')
 
    # Relationships
    client   = db.relationship('ClientMaster', backref='quotations')
    tenant   = db.relationship('TenantMaster', backref='quotations')
    items    = db.relationship('QuotationItem', back_populates='quotation',
                               lazy='dynamic', cascade='all, delete-orphan')
 
    def __repr__(self):
        return f'<Quotation {self.reference_number}>'
 
    def to_dict(self):
        return {
            'quotation_id':           self.quotation_id,
            'reference_number':       self.reference_number,
            'tenant_id':              self.tenant_id,
            'client_id':              self.client_id,
            'project_id':             self.project_id,
            'employee_id':            self.employee_id,
            'status':                 self.status or 'Draft',
            'total':                  float(self.total) if self.total is not None else 0.0,
            'vat_percentage':         float(self.vat_percentage) if self.vat_percentage is not None else 20.0,
            'global_discount_percent':float(self.global_discount_percent) if self.global_discount_percent is not None else 0.0,
            'notes':                  self.notes,
            'valid_until':            self.valid_until.isoformat() if self.valid_until else None,
            'created_at':             self.created_at.isoformat() if self.created_at else None,
            'updated_at':             self.updated_at.isoformat() if self.updated_at else None,
            'customer_name':          self.customer_name,
            'customer_address':       self.customer_address,
            'customer_phone':         self.customer_phone,
            'customer_email':         self.customer_email,
            'room_name':              self.room_name,
            'room_type':              self.room_type,
            'door_type':              self.door_type,
            'door_style':             self.door_style,
            'door_colour':            self.door_colour,
            'carcass_colour':         self.carcass_colour,
            'panelwork_colour':       self.panelwork_colour,
            'filler_type':            self.filler_type,
            'section_discounts':      self.section_discounts or {},
        }
 
 
class QuotationItem(db.Model):
    __tablename__ = 'Quotation_Items'
    __table_args__ = {'schema': 'StreemLyne_MT'}
 
    item_id          = db.Column(db.Integer, primary_key=True, autoincrement=True)
    quotation_id     = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Quotations.quotation_id', ondelete='CASCADE'), nullable=False, index=True)
    item_name        = db.Column(db.String, nullable=False)
    description      = db.Column(db.Text, nullable=True)
    color            = db.Column(db.String, nullable=True)
    quantity         = db.Column(db.Integer, default=1)
    amount           = db.Column(db.Numeric(10, 2), default=0)
    width            = db.Column(db.SmallInteger, nullable=True)
    height           = db.Column(db.SmallInteger, nullable=True)
    depth            = db.Column(db.SmallInteger, nullable=True)
    needs_manual_pricing = db.Column(db.Boolean, default=False)
    pricelist_id     = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.PriceList_Master.pricelist_id'), nullable=True)
    created_at       = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    discount_type    = db.Column(db.String(20), default='none')
    discount_value   = db.Column(db.Numeric(10, 2), default=0)
    discounted_amount= db.Column(db.Numeric(10, 2), nullable=True)
    discount_percent = db.Column(db.Numeric(5, 2), default=0)
    parent_item_id   = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Quotation_Items.item_id', ondelete='CASCADE'), nullable=True)
    section          = db.Column(db.String(50), nullable=True)
    source           = db.Column(db.String(20), default='manual')
    checklist_key    = db.Column(db.String(50), nullable=True)
 
    # Relationships
    quotation   = db.relationship('Quotation', back_populates='items')
    pricelist   = db.relationship('PriceListMaster', backref='quotation_items')
    sub_items   = db.relationship('QuotationItem', backref=db.backref('parent', remote_side=[item_id]),
                                   lazy='dynamic', cascade='all, delete-orphan',
                                   foreign_keys=[parent_item_id])
 
    def __repr__(self):
        return f'<QuotationItem {self.item_id}: {self.item_name}>'
 
    def to_dict(self):
        return {
            'item_id':           self.item_id,
            'quotation_id':      self.quotation_id,
            'item_name':         self.item_name,
            'description':       self.description,
            'color':             self.color,
            'quantity':          self.quantity or 1,
            'amount':            float(self.amount) if self.amount is not None else 0.0,
            'width':             self.width,
            'height':            self.height,
            'depth':             self.depth,
            'pricelist_id':      self.pricelist_id,
            'discount_type':     self.discount_type,
            'discount_value':    float(self.discount_value) if self.discount_value is not None else 0.0,
            'discount_percent':  float(self.discount_percent) if self.discount_percent is not None else 0.0,
            'discounted_amount': float(self.discounted_amount) if self.discounted_amount is not None else None,
            'parent_item_id':    self.parent_item_id,
            'section':           self.section,
            'source':            self.source,
            'created_at':        self.created_at.isoformat() if self.created_at else None,
        }

class InvoiceMaster(db.Model):
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

    client          = db.relationship('ClientMaster', back_populates='invoices')
    project         = db.relationship('ProjectDetails', back_populates='invoices')
    proposal        = db.relationship('ProposalMaster', back_populates='invoices')
    currency        = db.relationship('CurrencyMaster', backref='invoices')
    invoice_details = db.relationship('InvoiceDetails', back_populates='invoice', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<InvoiceMaster {self.invoice_id}: {self.invoice_number}>'

    def to_dict(self):
        return {
            'invoice_id': self.invoice_id, 'client_id': self.client_id,
            'client_name': self.client.client_company_name if self.client else None,
            'project_id': self.project_id,
            'project_title': self.project.project_title if self.project else None,
            'proposal_id': self.proposal_id, 'currency_id': self.currency_id,
            'currency_code': self.currency.currency_code if self.currency else None,
            'invoice_number': self.invoice_number, 'billing_remarks': self.billing_remarks,
            'sub_total': float(self.sub_total) if self.sub_total is not None else None,
            'vat': float(self.vat) if self.vat else 0,
            'other_taxes': float(self.other_taxes) if self.other_taxes else 0,
            'total_amount': self.total_amount, 'discount_percent': self.discount_percent,
            'discount_amount': self.discount_amount, 'payment_status': self.payment_status,
            'tax_id': self.tax_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class InvoiceDetails(db.Model):
    __tablename__ = 'Invoice_Details'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    invoice_details_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    invoice_id         = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Invoice_Master.invoice_id'), nullable=False)
    service_id         = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Services_Master.service_id'), nullable=True)
    uom_id             = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.UOM_Master.uom_id'), nullable=True)
    quantity           = db.Column(db.Float(precision=24), nullable=True, default=1.0)
    service_name       = db.Column(db.String(500), nullable=True)
    unit_price         = db.Column(db.Float(precision=24), nullable=True)
    created_at         = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at         = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    invoice = db.relationship('InvoiceMaster', back_populates='invoice_details')
    service = db.relationship('ServicesMaster', backref='invoice_details')
    uom     = db.relationship('UOMMaster', backref='invoice_details')

    def to_dict(self):
        return {
            'invoice_details_id': self.invoice_details_id, 'invoice_id': self.invoice_id,
            'service_id': self.service_id,
            'service_title': self.service.service_title if self.service else None,
            'uom_id': self.uom_id,
            'uom_description': self.uom.uom_description if self.uom else None,
            'quantity': self.quantity, 'unit_price': self.unit_price,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================================
# SECTION 5: CHAT
# ============================================================================

class ChatHistory(db.Model):
    """AI chat session storage — maps to Chat_History table."""
    __tablename__ = 'Chat_History'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id         = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
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
            'id': self.id, 'session_id': self.session_id, 'tenant_id': self.tenant_id,
            'user_id': self.user_id, 'title': self.title, 'messages': self.messages,
            'context': self.context,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================================
# BACKWARD COMPATIBILITY — models still imported by other route files
# ============================================================================

# Assignment is now backed by Tasks_Master
Assignment = TasksMaster

# These models were removed (no backing table) but may still be imported.
# Provide stubs so existing imports don't crash at startup.
# Routes that use these should be updated to use TasksMaster or removed.
class _RemovedModel:
    """Placeholder for removed models with no backing table."""
    pass

ChatConversation = _RemovedModel
ChatMessage      = _RemovedModel
CustomerFormData = _RemovedModel
FormSubmission   = _RemovedModel
DataImport       = _RemovedModel
AuditLog         = _RemovedModel
VersionedSnapshot = _RemovedModel
Activity         = _RemovedModel
OpportunityNote  = _RemovedModel
DocumentTemplate = _RemovedModel
DunningConfig    = _RemovedModel
NotificationPreference = _RemovedModel
NotificationLog  = _RemovedModel
PendingPlanChange = _RemovedModel


# ============================================================================
# MODULE FLAGS & HELPERS
# ============================================================================

EDUCATION_MODULE_AVAILABLE = False
INTERIOR_MODULE_AVAILABLE  = False
DRAWING_MODULE_AVAILABLE   = False
LEGACY_MODELS_AVAILABLE    = True


def is_module_available(module_name: str) -> bool:
    return {'education': EDUCATION_MODULE_AVAILABLE,
            'interior_design': INTERIOR_MODULE_AVAILABLE,
            'legacy': LEGACY_MODELS_AVAILABLE}.get(module_name, False)


def get_available_modules() -> list:
    return ['legacy'] if LEGACY_MODELS_AVAILABLE else []


def get_new_schema_models() -> list:
    return [
        'TenantMaster', 'SubscriptionPlan', 'ModuleMaster',
        'SubscriptionModuleMapping', 'TenantModuleMapping', 'TenantSubscription',
        'SubscriptionInvoice', 'PaymentAttempt', 'SubscriptionPause', 'ProcessedWebhookEvent',
        'CountryMaster', 'CurrencyMaster', 'DesignationMaster', 'ServicesMaster',
        'UOMMaster', 'StageMaster', 'SupplierMaster', 'RoleMaster',
        'PermissionCatalog', 'RolePermissionMapping', 'TaxMaster', 'ContactMethodMaster',
        'ClientMaster', 'ClientInteractions', 'EmployeeMaster', 'UserMaster',
        'UserRoleMapping', 'CustomerAuth', 'CustomerPasswordReset',
        'OpportunityDetails', 'ProjectDetails',
        'CaseDocuments', 'CustomerDocuments', 'EnergyContractMaster',
        'TasksMaster', 'ProposalMaster', 'ProposalDetails', 'InvoiceMaster',
        'InvoiceDetails', 'ChatHistory', 'PriceListMaster', 'ProductMaster', 'ProductVariant', 'SupplierPriceList', 'Quotation', 'QuotationItem'
    ]


def get_legacy_schema_models() -> list:
    return []


__all__ = [
    'TenantMaster', 'SubscriptionPlan', 'SubscriptionPlans', 'ModuleMaster',
    'SubscriptionModuleMapping', 'TenantModuleMapping', 'TenantSubscription',
    'SubscriptionInvoice', 'PaymentAttempt', 'SubscriptionPause', 'ProcessedWebhookEvent',
    'CountryMaster', 'CurrencyMaster', 'DesignationMaster', 'ServicesMaster',
    'UOMMaster', 'StageMaster', 'SupplierMaster', 'RoleMaster',
    'PermissionCatalog', 'RolePermissionMapping', 'TaxMaster', 'ContactMethodMaster',
    'ClientMaster', 'ClientInteractions', 'EmployeeMaster', 'UserMaster',
    'UserRoleMapping', 'CustomerAuth', 'CustomerPasswordReset',
    'OpportunityDetails', 'ProjectDetails',
    'CaseDocuments', 'CustomerDocuments', 'EnergyContractMaster',
    'TasksMaster', 'Assignment',
    'ProposalMaster', 'ProposalDetails', 'InvoiceMaster', 'InvoiceDetails',
    'ChatHistory', 'ChatConversation', 'ChatMessage', 'CustomerFormData', 'FormSubmission',
    'DataImport', 'AuditLog', 'VersionedSnapshot', 'Activity',
    'OpportunityNote', 'DocumentTemplate', 'DunningConfig',
    'NotificationPreference', 'NotificationLog', 'PendingPlanChange',
    'EDUCATION_MODULE_AVAILABLE', 'INTERIOR_MODULE_AVAILABLE',
    'DRAWING_MODULE_AVAILABLE', 'LEGACY_MODELS_AVAILABLE',
    'is_module_available', 'get_available_modules',
    'get_new_schema_models', 'get_legacy_schema_models', 'PriceListMaster', 'ProductMaster', 'ProductVariant', 'SupplierPriceList', 'Quotation', 'QuotationItem'
]