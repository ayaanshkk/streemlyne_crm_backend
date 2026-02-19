"""
System Configuration Models for StreemLyne CRM
Handles modules, subscriptions, permissions, and roles

DEVELOPER: Dev A
CREATED: Day 3

THEORY - WHAT ARE THESE MODELS FOR?
------------------------------------

Imagine you're running a SaaS company. You have:

1. FEATURES (Modules)
   - Client Management
   - Invoicing
   - Advanced Analytics
   - API Access

2. PRICING TIERS (Subscription Plans)
   - Free: Basic features only
   - Professional: More features
   - Enterprise: All features

3. USER ROLES (Roles)
   - Admin: Can do everything
   - Manager: Can approve invoices
   - Sales Rep: Can create opportunities
   - Viewer: Can only view data

4. SPECIFIC PERMISSIONS (Permissions)
   - client.create
   - client.edit
   - invoice.approve
   - user.delete

THIS FILE MODELS ALL OF THE ABOVE.

REAL-WORLD EXAMPLE:
-------------------

Tenant "Acme Solar" signs up:
1. They choose "Professional Plan" subscription
2. Professional Plan includes modules: [1,2,3,4,5]
3. System automatically creates TenantModuleMapping for each
4. Their admin user gets "Admin Role"
5. Admin Role has all permissions
6. Sales reps get "Sales Role" with limited permissions

When sales rep logs in:
- System checks: What role does this user have? → "Sales Role"
- What permissions does Sales Role have? → [client.view, client.create, opportunity.create]
- User tries to delete a client → Permission denied!
"""

from database import db
from datetime import datetime


class ModuleMaster(db.Model):
    """
    System modules/features
    Controls which features are available in the system
    
    CONCEPT:
    --------
    A "module" is a feature or set of features that can be toggled on/off.
    
    Think of it like add-ons in a car:
    - Base model comes with basic features (is_core=True)
    - Upgrade packages add more features (is_core=False)
    
    EXAMPLE MODULES:
    ----------------
    module_id: 1
    module_code: "CLIENT_MGMT"
    module_name: "Client Management"
    description: "Manage clients and contacts"
    is_core: True  # Everyone gets this
    is_active: True
    
    module_id: 2
    module_code: "OPPORTUNITIES"
    module_name: "Sales Opportunities"
    description: "Track sales pipeline"
    is_core: False  # Optional upgrade
    is_active: True
    
    module_id: 3
    module_code: "ADVANCED_ANALYTICS"
    module_name: "Advanced Analytics Dashboard"
    description: "AI-powered insights"
    is_core: False
    is_active: True
    
    module_id: 10
    module_code: "LEGACY_FEATURE"
    module_name: "Old Feature"
    is_core: False
    is_active: False  # Deprecated, no longer offered
    
    BUSINESS RULES:
    ---------------
    - is_core modules are included in ALL plans (can't be removed)
    - is_active=False modules are deprecated (no new tenants get them)
    - module_code is unique identifier (used in code)
    - module_code should be UPPERCASE with underscores
    
    USAGE IN CODE:
    --------------
    # Check if module is available to tenant
    if tenant.has_module_access(MODULE_ADVANCED_ANALYTICS):
        # Show analytics dashboard
    else:
        # Show upgrade prompt
    
    # Get all active modules
    modules = ModuleMaster.query.filter_by(is_active=True).all()
    
    # Constants in code (define in config.py)
    MODULE_CLIENT_MGMT = 1
    MODULE_OPPORTUNITIES = 2
    MODULE_ADVANCED_ANALYTICS = 3
    """
    __tablename__ = 'module_master'
    
    module_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    module_code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    module_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    is_core = db.Column(db.Boolean, default=False)  # Core modules always enabled
    is_active = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Module {self.module_code}: {self.module_name}>'
    
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


class SubscriptionPlans(db.Model):
    """
    Subscription/pricing plans
    Defines different tiers of service
    
    CONCEPT:
    --------
    Like Netflix pricing:
    - Basic: $9.99/month
    - Standard: $15.99/month
    - Premium: $19.99/month
    
    Each tier includes different features (modules).
    
    EXAMPLE PLANS:
    --------------
    Plan 1: Free Tier
    subscription_code: "FREE"
    subscription_name: "Free Plan"
    is_base_plan: True
    billing_cycle: 1  # Monthly
    price: 0.00
    currency_id: 1  # USD
    Includes modules: [1, 2]  # Client Management, Basic CRM
    
    Plan 2: Professional
    subscription_code: "PRO"
    subscription_name: "Professional Plan"
    is_base_plan: False
    billing_cycle: 1
    price: 99.00
    currency_id: 1
    Includes modules: [1, 2, 3, 4, 5]  # More features
    
    Plan 3: Enterprise
    subscription_code: "ENTERPRISE"
    subscription_name: "Enterprise Plan"
    is_base_plan: False
    billing_cycle: 12  # Annual
    price: 999.00
    currency_id: 1
    Includes modules: ALL
    
    BUSINESS RULES:
    ---------------
    - Only ONE plan should have is_base_plan=True (default/free tier)
    - billing_cycle in months (1=monthly, 3=quarterly, 12=annual)
    - price is per billing_cycle
    - Currency determines how price is displayed
    - Deactivated plans (is_active=False) aren't shown to new customers
      but existing customers on old plans keep them
    
    UPGRADE/DOWNGRADE LOGIC:
    -------------------------
    User currently on: Professional ($99/mo)
    User upgrades to: Enterprise ($999/yr)
    
    System:
    1. Calculates pro-rated credit for Professional
    2. Creates new TenantSubscription for Enterprise
    3. Sets old subscription is_active=False
    4. Updates TenantModuleMapping (add Enterprise-only modules)
    
    USAGE IN CODE:
    --------------
    # Get all active plans for display
    plans = SubscriptionPlans.query.filter_by(is_active=True).order_by(
        SubscriptionPlans.price
    ).all()
    
    # Get plan details
    plan = SubscriptionPlans.query.get(subscription_id)
    modules = plan.get_included_modules()
    
    # Check if upgrade
    if new_plan.price > current_plan.price:
        # This is an upgrade
        apply_upgrade_logic()
    """
    __tablename__ = 'subscription_plans'
    
    subscription_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    subscription_code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    subscription_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    is_base_plan = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True, index=True)
    billing_cycle = db.Column(db.SmallInteger)  # 1=Monthly, 12=Yearly, etc.
    price = db.Column(db.Numeric(precision=10, scale=2))
    currency_id = db.Column(db.SmallInteger, db.ForeignKey('currency_master.currency_id'))
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)
    
    # Relationships
    currency = db.relationship('CurrencyMaster', backref='subscription_plans')
    module_mappings = db.relationship('SubscriptionModuleMapping', 
                                     backref='subscription', 
                                     lazy='dynamic',
                                     cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<SubscriptionPlan {self.subscription_code}: {self.subscription_name}>'
    
    def to_dict(self, include_modules=False):
        data = {
            'subscription_id': self.subscription_id,
            'subscription_code': self.subscription_code,
            'subscription_name': self.subscription_name,
            'description': self.description,
            'is_base_plan': self.is_base_plan,
            'is_active': self.is_active,
            'billing_cycle': self.billing_cycle,
            'billing_cycle_name': self.get_billing_cycle_name(),
            'price': float(self.price) if self.price else None,
            'currency_id': self.currency_id,
            'currency_code': self.currency.currency_code if self.currency else None,
            'price_display': self.get_price_display(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        
        if include_modules:
            data['modules'] = [m.module.to_dict() for m in self.module_mappings.all()]
            data['module_count'] = self.module_mappings.count()
        
        return data
    
    def get_billing_cycle_name(self):
        """Get human-readable billing cycle"""
        cycles = {
            1: 'Monthly',
            3: 'Quarterly',
            6: 'Semi-Annual',
            12: 'Annual'
        }
        return cycles.get(self.billing_cycle, f'{self.billing_cycle} months')
    
    def get_price_display(self):
        """
        Get formatted price with currency
        
        Returns:
        --------
        str : e.g., "USD 99.00/month" or "GBP 999.00/year"
        
        Usage:
        ------
        plan = SubscriptionPlans.query.get(1)
        print(plan.get_price_display())
        # Output: "USD 99.00/month"
        """
        if not self.price or not self.currency:
            return "Free"
        
        period = "month" if self.billing_cycle == 1 else "year" if self.billing_cycle == 12 else f"{self.billing_cycle} months"
        return f"{self.currency.currency_code} {float(self.price):.2f}/{period}"
    
    def get_included_modules(self):
        """
        Get list of modules included in this plan
        
        Returns:
        --------
        list of ModuleMaster : Modules included in plan
        
        Usage:
        ------
        plan = SubscriptionPlans.query.get(2)  # Professional plan
        modules = plan.get_included_modules()
        for module in modules:
            print(f"- {module.module_name}")
        """
        return [mapping.module for mapping in self.module_mappings.all()]
    
    def includes_module(self, module_id):
        """
        Check if plan includes specific module
        
        Parameters:
        -----------
        module_id : int
            Module ID to check
        
        Returns:
        --------
        bool : True if module is included
        """
        return self.module_mappings.filter_by(module_id=module_id).count() > 0


class SubscriptionModuleMapping(db.Model):
    """
    Maps modules to subscription plans
    Defines which modules are included in each plan
    
    CONCEPT:
    --------
    This is the link between "What you pay for" and "What you get".
    
    EXAMPLE DATA:
    -------------
    Professional Plan (subscription_id=2) includes:
    - Record 1: subscription_id=2, module_id=1  (Client Management)
    - Record 2: subscription_id=2, module_id=2  (Opportunities)
    - Record 3: subscription_id=2, module_id=3  (Projects)
    - Record 4: subscription_id=2, module_id=4  (Proposals)
    - Record 5: subscription_id=2, module_id=5  (Invoices)
    
    Enterprise Plan (subscription_id=3) includes:
    - All above, plus:
    - Record 6: subscription_id=3, module_id=10 (Advanced Analytics)
    - Record 7: subscription_id=3, module_id=11 (API Access)
    
    USAGE WHEN CREATING A PLAN:
    ----------------------------
    # Create new plan
    plan = SubscriptionPlans(
        subscription_code="STARTUP",
        subscription_name="Startup Plan",
        price=49.00,
        billing_cycle=1,
        currency_id=1
    )
    db.session.add(plan)
    db.session.flush()  # Get plan ID
    
    # Add modules to plan
    modules_to_include = [1, 2, 3]  # Module IDs
    for module_id in modules_to_include:
        mapping = SubscriptionModuleMapping(
            subscription_id=plan.subscription_id,
            module_id=module_id
        )
        db.session.add(mapping)
    
    db.session.commit()
    """
    __tablename__ = 'subscription_module_mapping'
    
    subscription_module_mapping_id = db.Column(db.SmallInteger, primary_key=True, 
                                              autoincrement=True)
    subscription_id = db.Column(db.BigInteger, 
                               db.ForeignKey('subscription_plans.subscription_id'),
                               nullable=False, index=True)
    module_id = db.Column(db.BigInteger, 
                         db.ForeignKey('module_master.module_id'),
                         nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    
    # Relationships
    module = db.relationship('ModuleMaster', backref='subscription_mappings')
    
    # Unique constraint - can't have same plan+module twice
    __table_args__ = (
        db.UniqueConstraint('subscription_id', 'module_id', 
                          name='uq_subscription_module'),
    )
    
    def __repr__(self):
        return f'<SubscriptionModuleMapping S:{self.subscription_id} M:{self.module_id}>'
    
    def to_dict(self):
        return {
            'subscription_module_mapping_id': self.subscription_module_mapping_id,
            'subscription_id': self.subscription_id,
            'module_id': self.module_id,
            'module_code': self.module.module_code if self.module else None,
            'module_name': self.module.module_name if self.module else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class PermissionCatalog(db.Model):
    """
    System-wide permission definitions
    Defines all available permissions in the system
    
    CONCEPT - WHAT IS A PERMISSION?
    --------------------------------
    A permission is a specific action a user can perform.
    It's the MOST GRANULAR level of access control.
    
    Format: <resource>.<action>
    
    EXAMPLE PERMISSIONS:
    --------------------
    permission_code: "client.view"
    description: "View client records"
    
    permission_code: "client.create"
    description: "Create new client records"
    
    permission_code: "client.edit"
    description: "Edit existing client records"
    
    permission_code: "client.delete"
    description: "Delete client records"
    
    permission_code: "invoice.approve"
    description: "Approve invoices for payment"
    
    permission_code: "user.manage"
    description: "Manage user accounts"
    
    permission_code: "reports.financial"
    description: "Access financial reports"
    
    WHY SO GRANULAR?
    ----------------
    Imagine you have a user who should:
    - View clients ✓
    - Create clients ✓
    - Edit clients ✓
    - Delete clients ✗  (NOT allowed)
    
    With granular permissions, we can give them exactly these rights.
    
    PERMISSION NAMING CONVENTION:
    -----------------------------
    <resource>.<action>
    
    Resources: client, opportunity, project, proposal, invoice, user, role, etc.
    Actions: view, create, edit, delete, approve, export, import, manage
    
    Special permissions:
    - "*.admin" = Admin over everything
    - "client.*" = All client permissions
    
    USAGE IN CODE:
    --------------
    # Check permission (done in middleware/decorators)
    from services.permission_service import has_permission
    
    @app.route('/api/clients/<id>', methods=['DELETE'])
    @require_permission('client.delete')
    def delete_client(id):
        # Only users with client.delete permission reach here
        pass
    
    # Or manual check:
    if has_permission(user_id, 'invoice.approve'):
        # Show "Approve" button
    else:
        # Hide button
    """
    __tablename__ = 'permission_catalog'
    
    permission_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    permission_code = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Permission {self.permission_code}>'
    
    def to_dict(self):
        return {
            'permission_id': self.permission_id,
            'permission_code': self.permission_code,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class RoleMaster(db.Model):
    """
    User roles for RBAC (Role-Based Access Control)
    
    CONCEPT - WHAT IS A ROLE?
    --------------------------
    A role is a GROUP of permissions.
    Instead of assigning 50 permissions to each user,
    we create roles and assign roles to users.
    
    EXAMPLE ROLES:
    --------------
    Role 1: Admin
    role_name: "Administrator"
    is_system: True  (can't be deleted)
    Permissions: ALL (*.admin)
    
    Role 2: Sales Manager
    role_name: "Sales Manager"
    is_system: False
    Permissions:
    - client.* (all client permissions)
    - opportunity.* (all opportunity permissions)
    - project.view
    - proposal.create, proposal.edit, proposal.view
    - invoice.view
    - reports.sales
    
    Role 3: Sales Representative
    role_name: "Sales Representative"
    is_system: False
    Permissions:
    - client.view, client.create, client.edit
    - opportunity.view, opportunity.create, opportunity.edit
    - project.view
    - proposal.view
    
    Role 4: Accountant
    role_name: "Accountant"
    is_system: False
    Permissions:
    - invoice.* (all invoice permissions)
    - reports.financial
    - client.view (read-only)
    
    Role 5: Viewer
    role_name: "Viewer"
    is_system: False
    Permissions:
    - *.view (view everything, edit nothing)
    
    BUSINESS RULES:
    ---------------
    - is_system=True roles cannot be deleted (Admin, SuperAdmin)
    - is_system=False roles can be customized per tenant
    - Each user can have multiple roles (permissions are combined)
    - If user has ANY role with permission X, they have permission X
    
    USAGE IN CODE:
    --------------
    # Assign role to user (via EmployeeMaster.role_ids)
    employee.role_ids = "1,5"  # Admin and Sales Manager
    
    # Check if user has permission
    def user_has_permission(user_id, permission_code):
        user = UserMaster.query.get(user_id)
        employee = user.employee
        role_ids = employee.get_roles()  # [1, 5]
        
        for role_id in role_ids:
            role = RoleMaster.query.get(role_id)
            if role.has_permission(permission_code):
                return True
        return False
    """
    __tablename__ = 'role_master'
    
    role_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    role_name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    role_description = db.Column(db.Text)
    is_system = db.Column(db.Boolean, default=False)  # System roles can't be deleted
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    
    # Relationships
    permission_mappings = db.relationship('RolePermissionMapping', 
                                         backref='role',
                                         lazy='dynamic',
                                         cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Role {self.role_name}>'
    
    def to_dict(self, include_permissions=False):
        data = {
            'role_id': self.role_id,
            'role_name': self.role_name,
            'role_description': self.role_description,
            'is_system': self.is_system,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        
        if include_permissions:
            data['permissions'] = [
                {
                    'permission_id': p.permission.permission_id,
                    'permission_code': p.permission.permission_code,
                    'description': p.permission.description
                }
                for p in self.permission_mappings.all()
            ]
            data['permission_count'] = self.permission_mappings.count()
        
        return data
    
    def has_permission(self, permission_code):
        """
        Check if role has specific permission
        
        Parameters:
        -----------
        permission_code : str
            Permission to check (e.g., "client.delete")
        
        Returns:
        --------
        bool : True if role has permission
        
        Logic:
        ------
        1. Check if role has exact permission
        2. Check if role has wildcard (e.g., "client.*")
        3. Check if role has admin wildcard ("*.admin")
        
        Usage:
        ------
        role = RoleMaster.query.get(1)
        if role.has_permission('client.delete'):
            # User with this role can delete clients
        """
        # Direct match
        if self.permission_mappings.join(PermissionCatalog).filter(
            PermissionCatalog.permission_code == permission_code
        ).count() > 0:
            return True
        
        # Wildcard match (e.g., client.* matches client.delete)
        resource = permission_code.split('.')[0] if '.' in permission_code else ''
        wildcard = f"{resource}.*"
        if self.permission_mappings.join(PermissionCatalog).filter(
            PermissionCatalog.permission_code == wildcard
        ).count() > 0:
            return True
        
        # Admin wildcard
        if self.permission_mappings.join(PermissionCatalog).filter(
            PermissionCatalog.permission_code == '*.admin'
        ).count() > 0:
            return True
        
        return False
    
    def get_permissions(self):
        """
        Get all permissions for this role
        
        Returns:
        --------
        list of PermissionCatalog : All permissions
        """
        return [mapping.permission for mapping in self.permission_mappings.all()]
    
    def add_permission(self, permission_code):
        """
        Add permission to this role
        
        Parameters:
        -----------
        permission_code : str
            Permission code to add
        
        Usage:
        ------
        role = RoleMaster.query.get(2)  # Sales Manager
        role.add_permission('reports.sales')
        db.session.commit()
        """
        permission = PermissionCatalog.query.filter_by(
            permission_code=permission_code
        ).first()
        
        if not permission:
            raise ValueError(f"Permission {permission_code} not found")
        
        # Check if already exists
        if not self.has_permission(permission_code):
            mapping = RolePermissionMapping(
                role_id=self.role_id,
                permission_id=permission.permission_id
            )
            db.session.add(mapping)
    
    def remove_permission(self, permission_code):
        """
        Remove permission from this role
        
        Parameters:
        -----------
        permission_code : str
            Permission code to remove
        """
        permission = PermissionCatalog.query.filter_by(
            permission_code=permission_code
        ).first()
        
        if permission:
            mapping = self.permission_mappings.filter_by(
                permission_id=permission.permission_id
            ).first()
            if mapping:
                db.session.delete(mapping)


class RolePermissionMapping(db.Model):
    """
    Maps permissions to roles
    Defines which permissions each role has
    
    CONCEPT:
    --------
    This is the glue between roles and permissions.
    
    EXAMPLE DATA:
    -------------
    Sales Manager role (role_id=2) has these permissions:
    
    Record 1: role_id=2, permission_id=1  (client.view)
    Record 2: role_id=2, permission_id=2  (client.create)
    Record 3: role_id=2, permission_id=3  (client.edit)
    Record 4: role_id=2, permission_id=10 (opportunity.view)
    Record 5: role_id=2, permission_id=11 (opportunity.create)
    ...
    
    CREATING A NEW ROLE WITH PERMISSIONS:
    --------------------------------------
    # 1. Create role
    role = RoleMaster(
        role_name="Custom Role",
        role_description="Custom role for specific needs"
    )
    db.session.add(role)
    db.session.flush()
    
    # 2. Add permissions
    permission_codes = [
        'client.view',
        'client.create',
        'opportunity.view'
    ]
    
    for perm_code in permission_codes:
        permission = PermissionCatalog.query.filter_by(
            permission_code=perm_code
        ).first()
        
        if permission:
            mapping = RolePermissionMapping(
                role_id=role.role_id,
                permission_id=permission.permission_id
            )
            db.session.add(mapping)
    
    db.session.commit()
    """
    __tablename__ = 'role_permission_mapping'
    
    role_permission_mapping_id = db.Column(db.SmallInteger, primary_key=True, 
                                          autoincrement=True)
    role_id = db.Column(db.SmallInteger, db.ForeignKey('role_master.role_id'),
                       nullable=False, index=True)
    permission_id = db.Column(db.SmallInteger, 
                             db.ForeignKey('permission_catalog.permission_id'),
                             nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    edited_at = db.Column(db.Date)
    
    # Relationships
    permission = db.relationship('PermissionCatalog', backref='role_mappings')
    
    # Unique constraint
    __table_args__ = (
        db.UniqueConstraint('role_id', 'permission_id', name='uq_role_permission'),
    )
    
    def __repr__(self):
        return f'<RolePermissionMapping R:{self.role_id} P:{self.permission_id}>'
    
    def to_dict(self):
        return {
            'role_permission_mapping_id': self.role_permission_mapping_id,
            'role_id': self.role_id,
            'permission_id': self.permission_id,
            'permission_code': self.permission.permission_code if self.permission else None,
            'permission_description': self.permission.description if self.permission else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'edited_at': self.edited_at.isoformat() if self.edited_at else None
        }