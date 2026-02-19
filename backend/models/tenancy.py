"""
Tenancy Models for StreemLyne CRM
Multi-tenant architecture support models

DEVELOPER: Dev A
CREATED: Day 1

THEORY:
-------
Multi-tenancy means multiple organizations (tenants) use the same application,
but their data is completely isolated from each other.

This file contains three models:
1. TenantMaster - The main tenant/organization record
2. TenantModuleMapping - Which features each tenant has access to
3. TenantSubscription - Billing and subscription tracking

Every tenant-specific model in the system will have a tenant_id foreign key
pointing to TenantMaster.

BUSINESS CONTEXT:
-----------------
Example: Our CRM is used by:
- Tenant 1: "Acme Solar Solutions" (solar panel company)
- Tenant 2: "Beta Energy Ltd" (energy consultancy)

Acme Solar's data is COMPLETELY SEPARATE from Beta Energy's data.
Even though both are in the same database, Acme can never see Beta's clients,
projects, invoices, etc.

This is enforced at TWO levels:
1. Application level: Every query filters by tenant_id
2. Database level: Row-Level Security (RLS) policies (we'll set up later)
"""

from database import db
from datetime import datetime


class TenantMaster(db.Model):
    """
    Core tenant/organization model
    Each tenant represents a separate customer organization using our system
    
    RELATIONSHIPS:
    --------------
    A tenant HAS MANY:
    - Employees (EmployeeMaster)
    - Clients (ClientMaster)
    - Services (ServicesMaster)
    - Module mappings (TenantModuleMapping)
    - Subscriptions (TenantSubscription)
    
    EXAMPLE DATA:
    -------------
    tenant_id: 1
    tenant_company_name: "Acme Solar Solutions LLC"
    tenant_contact_name: "John Smith"
    onboarding_date: 2025-01-15
    is_active: True
    
    BUSINESS RULES:
    ---------------
    - Company name must be unique (enforced at app level, not DB level)
    - Cannot delete tenant if has active employees or clients
    - Deactivating tenant (is_active=False) should hide from login
    """
    __tablename__ = 'tenant_master'
    
    # Primary Key
    tenant_id = db.Column(db.Integer, primary_key=True, autoincrement=True)  #changed db.SmallInt to db.Int bcz tests werent passing for SQLite
    
    # Basic Information
    tenant_company_name = db.Column(db.String(255), nullable=False, index=True)
    tenant_contact_name = db.Column(db.String(255))  # Primary contact person
    onboarding_date = db.Column(db.Date)  # When they joined
    
    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    # is_active controls whether tenant can login
    # False = suspended/cancelled subscription
    
    # Timestamps
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)
    
    # Relationships
    # These define connections to other tables
    # lazy='dynamic' means relationships aren't loaded until accessed (performance)
    # cascade='all, delete-orphan' means if tenant is deleted, these are too
    employees = db.relationship('EmployeeMaster', backref='tenant_master', lazy='dynamic', 
                            cascade='all, delete-orphan')
    # clients = db.relationship('ClientMaster', backref='client_tenant', lazy='dynamic',
    #                         cascade='all, delete-orphan')
    services = db.relationship('ServicesMaster', backref='service_tenant', lazy='dynamic',
                            cascade='all, delete-orphan')
    module_mappings = db.relationship('TenantModuleMapping', backref='mapping_tenant', 
                                    lazy='dynamic', cascade='all, delete-orphan')
    subscriptions = db.relationship('TenantSubscription', backref='subscription_tenant', 
                                lazy='dynamic', cascade='all, delete-orphan')    
    def __repr__(self):
        """String representation for debugging"""
        return f'<TenantMaster {self.tenant_id}: {self.tenant_company_name}>'
    
    def to_dict(self, include_relationships=False):
        """
        Convert model to dictionary (for JSON responses)
        
        Parameters:
        -----------
        include_relationships : bool
            If True, includes counts of related records
        
        Returns:
        --------
        dict : Dictionary representation of tenant
        
        Usage:
        ------
        tenant = TenantMaster.query.get(1)
        return jsonify(tenant.to_dict())
        
        With relationships:
        tenant_data = tenant.to_dict(include_relationships=True)
        # Returns: {..., 'employee_count': 15, 'client_count': 47, ...}
        """
        data = {
            'tenant_id': self.tenant_id,
            'tenant_company_name': self.tenant_company_name,
            'tenant_contact_name': self.tenant_contact_name,
            'onboarding_date': self.onboarding_date.isoformat() if self.onboarding_date else None,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        
        if include_relationships:
            data.update({
                'employee_count': self.employees.count(),
                'client_count': self.clients.count(),
                'active_modules': [m.module_id for m in self.module_mappings.all()],
                'subscription_status': 'active' if self.get_active_subscription() else 'inactive'
            })
        
        return data
    
    def get_active_subscription(self):
        """
        Get the currently active subscription for this tenant
        
        Returns:
        --------
        TenantSubscription or None
        
        Business Logic:
        ---------------
        A tenant should only have ONE active subscription at a time.
        If multiple found, this returns the first one (shouldn't happen).
        If none found, tenant is on free/trial tier or suspended.
        
        Usage:
        ------
        subscription = tenant.get_active_subscription()
        if subscription:
            plan_name = subscription.subscription_plan.subscription_name
        else:
            # Show upgrade prompt
        """
        return self.subscriptions.filter_by(is_active=True).first()
    
    def has_module_access(self, module_id):
        """
        Check if tenant has access to a specific module
        
        Parameters:
        -----------
        module_id : int
            The module ID to check
        
        Returns:
        --------
        bool : True if tenant has access, False otherwise
        
        Business Logic:
        ---------------
        Module access is determined by:
        1. Tenant's subscription plan (includes certain modules)
        2. Additional modules purchased separately
        
        This is checked via TenantModuleMapping table.
        
        Usage:
        ------
        if tenant.has_module_access(5):  # 5 = "Advanced Invoicing"
            # Show invoicing feature in UI
        else:
            # Show "Upgrade to unlock" message
        
        Example in Route:
        -----------------
        @app.route('/api/invoices')
        def list_invoices():
            tenant = get_current_tenant()
            if not tenant.has_module_access(MODULE_INVOICING):
                return jsonify({'error': 'Module not available'}), 403
            # ... rest of logic
        """
        return self.module_mappings.filter_by(module_id=module_id).count() > 0
    
    def activate(self):
        """
        Activate tenant account
        
        Business Logic:
        ---------------
        Called when:
        - Payment received
        - Subscription renewed
        - Support manually reactivates account
        """
        self.is_active = True
        db.session.commit()
    
    def deactivate(self):
        """
        Deactivate tenant account
        
        Business Logic:
        ---------------
        Called when:
        - Subscription expired and not renewed
        - Payment failed
        - Account suspended by admin
        
        NOTE: Does NOT delete data, just prevents login
        """
        self.is_active = False
        db.session.commit()


class TenantModuleMapping(db.Model):
    """
    Maps modules to tenants
    Controls which features/modules each tenant has access to
    
    BUSINESS CONTEXT:
    -----------------
    Modules are features/functionalities like:
    - Client Management (module_id=1) - Core, everyone has
    - Opportunities (module_id=2) - Basic plan and up
    - Advanced Analytics (module_id=10) - Premium only
    - API Access (module_id=11) - Enterprise only
    
    When a tenant subscribes to "Basic Plan", we automatically create
    TenantModuleMapping records for all modules in the Basic plan.
    
    EXAMPLE SCENARIO:
    -----------------
    Tenant "Acme Solar" subscribes to "Professional Plan" which includes:
    - Client Management
    - Opportunities
    - Projects
    - Proposals
    - Invoices
    
    We create 5 TenantModuleMapping records:
    (tenant_id=1, module_id=1)  # Client Management
    (tenant_id=1, module_id=2)  # Opportunities
    (tenant_id=1, module_id=3)  # Projects
    (tenant_id=1, module_id=4)  # Proposals
    (tenant_id=1, module_id=5)  # Invoices
    
    Later, they purchase "Advanced Analytics" add-on:
    We create: (tenant_id=1, module_id=10)
    
    If they downgrade to "Basic Plan", we DELETE the mappings for
    modules not in Basic plan.
    """
    __tablename__ = 'tenant_module_mapping'
    
    tenant_module_mapping_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    
    # Foreign Keys
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('tenant_master.tenant_id'), 
                         nullable=False, index=True)
    module_id = db.Column(db.SmallInteger, db.ForeignKey('module_master.module_id'), 
                         nullable=False, index=True)
    
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    
    # Relationships
    module = db.relationship('ModuleMaster', backref='tenant_mappings')
    
    # Unique constraint - can't have same tenant + module combo twice
    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'module_id', name='uq_tenant_module'),
    )
    
    def __repr__(self):
        return f'<TenantModuleMapping T:{self.tenant_id} M:{self.module_id}>'
    
    def to_dict(self):
        return {
            'tenant_module_mapping_id': self.tenant_module_mapping_id,
            'tenant_id': self.tenant_id,
            'module_id': self.module_id,
            'module_code': self.module.module_code if self.module else None,
            'module_name': self.module.module_name if self.module else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class TenantSubscription(db.Model):
    """
    Tracks tenant subscription plans and billing
    
    BUSINESS CONTEXT:
    -----------------
    This is the billing/subscription record. Each tenant can have multiple
    subscription records over time (historical), but only ONE is active.
    
    SUBSCRIPTION LIFECYCLE:
    -----------------------
    1. Tenant signs up → Create TenantSubscription (is_active=True)
    2. Subscription period ends → Set is_active=False
    3. If auto_renew=True → Create NEW TenantSubscription for next period
    4. If auto_renew=False → Wait for manual renewal
    
    EXAMPLE DATA:
    -------------
    Tenant "Acme Solar" timeline:
    
    Record 1:
    - subscription_id: 2 (Professional Plan - $99/month)
    - start: 2025-01-01
    - end: 2025-02-01
    - is_active: False  # Expired
    - auto_renew: True
    
    Record 2: (auto-created because auto_renew=True)
    - subscription_id: 2 (Professional Plan)
    - start: 2025-02-01
    - end: 2025-03-01
    - is_active: True  # Current
    - auto_renew: True
    
    UPGRADE/DOWNGRADE:
    ------------------
    If tenant upgrades mid-month:
    1. Set current subscription is_active=False
    2. Create new subscription with new plan
    3. Pro-rate billing (handled externally)
    """
    __tablename__ = 'tenant_subscription'
    
    tenant_subscription_mapping_id = db.Column(db.SmallInteger, primary_key=True, 
                                              autoincrement=True)
    
    # Foreign Keys
    tenant_id = db.Column(db.BigInteger, db.ForeignKey('tenant_master.tenant_id'), 
                         nullable=False, index=True)
    subscription_id = db.Column(db.BigInteger, db.ForeignKey('subscription_plans.subscription_id'), 
                               nullable=False)
    
    # Subscription Period
    subscription_start_date = db.Column(db.Date)
    subscription_end_date = db.Column(db.Date, index=True)  # Indexed for expiry checks
    
    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    auto_renew = db.Column(db.Boolean, default=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)
    
    # Relationships
    subscription_plan = db.relationship('SubscriptionPlans', backref='tenant_subscriptions')
    
    def __repr__(self):
        return f'<TenantSubscription T:{self.tenant_id} S:{self.subscription_id}>'
    
    def to_dict(self):
        return {
            'tenant_subscription_mapping_id': self.tenant_subscription_mapping_id,
            'tenant_id': self.tenant_id,
            'subscription_id': self.subscription_id,
            'subscription_code': self.subscription_plan.subscription_code if self.subscription_plan else None,
            'subscription_name': self.subscription_plan.subscription_name if self.subscription_plan else None,
            'subscription_start_date': self.subscription_start_date.isoformat() if self.subscription_start_date else None,
            'subscription_end_date': self.subscription_end_date.isoformat() if self.subscription_end_date else None,
            'is_active': self.is_active,
            'auto_renew': self.auto_renew,
            'days_remaining': self.days_remaining(),
            'is_expired': self.is_expired(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def is_expired(self):
        """
        Check if subscription is expired
        
        Returns:
        --------
        bool : True if expired, False otherwise
        
        Business Logic:
        ---------------
        Subscription is expired if:
        - subscription_end_date is in the past
        - OR no end date but is_active=False
        
        Usage:
        ------
        if subscription.is_expired():
            # Show renewal prompt
            # Block access to paid features
        """
        if not self.subscription_end_date:
            # No end date means perpetual (shouldn't happen)
            return not self.is_active
        return datetime.now().date() > self.subscription_end_date
    
    def days_remaining(self):
        """
        Calculate days remaining in subscription
        
        Returns:
        --------
        int : Number of days left, or None if no end date
        
        Usage:
        ------
        days = subscription.days_remaining()
        if days and days <= 7:
            # Show "Renew now" banner
        """
        if not self.subscription_end_date:
            return None
        delta = self.subscription_end_date - datetime.now().date()
        return max(0, delta.days)
    
    def renew(self, new_end_date=None):
        """
        Renew subscription (extend end date)
        
        Parameters:
        -----------
        new_end_date : date, optional
            If provided, sets this as new end date
            If None, extends by billing cycle from current end
        
        Business Logic:
        ---------------
        Called when:
        - Payment successful for renewal
        - Admin manually extends subscription
        
        Usage:
        ------
        # Auto-renew for another month
        subscription.renew()
        
        # Or specify exact date
        from datetime import date, timedelta
        new_end = date.today() + timedelta(days=365)
        subscription.renew(new_end)
        """
        if new_end_date:
            self.subscription_end_date = new_end_date
        elif self.subscription_plan:
            # Extend by billing cycle
            from datetime import timedelta
            days_to_add = self.subscription_plan.billing_cycle * 30  # Rough approximation
            self.subscription_end_date = self.subscription_end_date + timedelta(days=days_to_add)
        
        self.is_active = True
        db.session.commit()