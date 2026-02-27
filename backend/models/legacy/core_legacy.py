# C:\streemlyne_crm_backend\backend\models\legacy\core_legacy.py
import json
import uuid
import secrets
from datetime import datetime, timedelta
import random
import string
import sys
import os

# Add parent directory to path so we can import database
# Get the directory containing this file (models/)
current_dir = os.path.dirname(os.path.abspath(__file__))
# Get the parent directory (backend/)
parent_dir = os.path.dirname(current_dir)
# Add to path if not already there
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from database import db
from werkzeug.security import generate_password_hash, check_password_hash
import jwt


# ============================================================
# ENUMS - Universal definitions
# ============================================================

STAGE_ENUM = db.Enum(
    'Prospect', 'Qualified', 'Contact Made', 'Meeting Scheduled', 'Proposal Sent',
    'Negotiation', 'Closed Won', 'Closed Lost', 'On Hold',
    name='stage_enum'
)

CONTACT_MADE_ENUM = db.Enum('Yes', 'No', 'Unknown', name='contact_made_enum')
PREFERRED_CONTACT_ENUM = db.Enum('Phone', 'Email', 'WhatsApp', name='preferred_contact_enum')
DOCUMENT_TEMPLATE_TYPE_ENUM = db.Enum(
    'Invoice', 'Receipt', 'Proposal', 'Contract', 'Agreement', 'Terms', 'Other',
    name='document_template_type_enum'
)
PAYMENT_METHOD_ENUM = db.Enum('Bank Transfer', 'Cash', 'Card', 'Check', 'Other', name='payment_method_enum')
AUDIT_ACTION_ENUM = db.Enum('create', 'update', 'delete', name='audit_action_enum')
ASSIGNMENT_TYPE_ENUM = db.Enum('meeting', 'call', 'task', 'delivery', 'note', name='assignment_type_enum')


# ============================================================
# TENANT & INDUSTRY CONFIGURATION
# ============================================================

class Tenant(db.Model):
    """
    Multi-tenant isolation with industry template support
    Each tenant can have different industry configuration and enabled modules
    """
    __tablename__ = 'tenants'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Tenant Type & Identity
    tenant_type = db.Column(db.String(20), nullable=False, default='company')  # 'individual' or 'company'
    company_name = db.Column(db.String(255), unique=True, nullable=True)
    subdomain = db.Column(db.String(100), unique=True, nullable=True)
    custom_domain = db.Column(db.String(255), unique=True)
    
    # 🎯 NEW: Industry Template System
    industry_template = db.Column(db.String(50), default='generic')
    # Values: 'generic', 'education', 'interior_design', 'healthcare', etc.
    
    # 🎯 NEW: Enabled Modules (Feature Flags)
    enabled_modules = db.Column(db.JSON, default=dict)
    # Example: {"education": True, "test_grading": True, "kitchen_checklist": False}
    
    # 🎯 NEW: Custom Terminology
    terminology = db.Column(db.JSON, default=dict)
    # Example: {"customer": "Student", "opportunity": "Enrollment", "job": "Training Session"}
    
    # 🎯 NEW: Pipeline Stage Configuration
    pipeline_stages = db.Column(db.JSON, default=dict)
    # Example: {"sales": ["Enquiry", "Proposal", "Converted"], "training": [...]}
    
    # 🎯 NEW: Custom Fields Configuration
    custom_fields_config = db.Column(db.JSON, default=dict)
    # Example: {"customer": [{"name": "mhe_type", "type": "select", "options": [...]}]}
    
    # Owner (for individual tenants)
    owner_user_id = db.Column(db.Integer, nullable=True)
    
    # Contact & Branding
    contact_email = db.Column(db.String(255))
    contact_phone = db.Column(db.String(50))
    logo_url = db.Column(db.String(500))
    primary_color = db.Column(db.String(7))
    
    # Subscription & Limits
    subscription_tier = db.Column(db.String(50), default='basic')  # basic, professional, enterprise
    max_users = db.Column(db.Integer, default=999999)
    is_active = db.Column(db.Boolean, default=True)
    is_trial = db.Column(db.Boolean, default=False)
    trial_ends_at = db.Column(db.DateTime)
    
    # Settings & Features (keep for backward compatibility)
    features = db.Column(db.JSON, default=dict)
    settings = db.Column(db.JSON, default=dict)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    users = db.relationship('User', back_populates='tenant', foreign_keys='User.tenant_id', lazy=True)
    customers = db.relationship('Customer', back_populates='tenant', lazy=True)
    
    def __repr__(self):
        if self.tenant_type == 'company':
            return f'<Tenant Company: {self.company_name}>'
        return f'<Tenant Individual: {self.id}>'
    
    def has_feature(self, feature_name: str) -> bool:
        """Check if feature is enabled (backward compatibility)"""
        if self.features and feature_name in self.features:
            return self.features.get(feature_name, False)
        return False
    
    def is_module_enabled(self, module_name: str) -> bool:
        """Check if module is enabled"""
        if not self.enabled_modules:
            return False
        return self.enabled_modules.get(module_name, False)
    
    def get_terminology(self, key: str, default: str = None) -> str:
        """Get custom terminology for this tenant"""
        if not self.terminology:
            return default or key
        return self.terminology.get(key, default or key)
    
    def get_pipeline_stages(self, pipeline_type: str = 'sales') -> list:
        """Get pipeline stages for this tenant"""
        if not self.pipeline_stages:
            # Return universal default
            return ['Prospect', 'Qualified', 'Contact Made', 'Meeting Scheduled', 
                    'Proposal Sent', 'Negotiation', 'Closed Won', 'Closed Lost', 'On Hold']
        return self.pipeline_stages.get(pipeline_type, [])
    
    @staticmethod
    def create_slug(company_name: str) -> str:
        """Create URL-friendly slug from company name"""
        import re
        slug = company_name.lower()
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        slug = slug.strip('-')
        return slug
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'tenant_type': self.tenant_type,
            'company_name': self.company_name,
            'subdomain': self.subdomain,
            'industry_template': self.industry_template,
            'enabled_modules': self.enabled_modules or {},
            'terminology': self.terminology or {},
            'pipeline_stages': self.pipeline_stages or {},
            'subscription_tier': self.subscription_tier,
            'is_active': self.is_active,
            'max_users': self.max_users,
            'features': self.features or {}
        }


# ============================================================
# USER & AUTHENTICATION
# ============================================================

class User(db.Model):
    """User accounts with multi-tenant isolation"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # Profile
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20))

    # Role & Permissions
    role = db.Column(db.String(20), default='member')  # admin, manager, member, viewer
    department = db.Column(db.String(50))

    # Account Status
    is_active = db.Column(db.Boolean, default=True)
    is_verified = db.Column(db.Boolean, default=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    # Password Reset
    reset_token = db.Column(db.String(100))
    reset_token_expires = db.Column(db.DateTime)

    # Email Verification
    verification_token = db.Column(db.String(100))

    # Relationships
    tenant = db.relationship('Tenant', back_populates='users', foreign_keys=[tenant_id])

    # Unique constraint on email + tenant_id
    __table_args__ = (
        db.UniqueConstraint('email', 'tenant_id', name='uq_user_email_tenant'),
    )

    def __repr__(self):
        return f'<User {self.email}>'

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def generate_reset_token(self) -> str:
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
        return self.reset_token

    def generate_verification_token(self) -> str:
        self.verification_token = secrets.token_urlsafe(32)
        return self.verification_token

    def generate_jwt_token(self, secret_key: str) -> str:
        payload = {
            'user_id': self.id,
            'email': self.email,
            'role': self.role,
            'tenant_id': self.tenant_id,
            'exp': datetime.utcnow() + timedelta(days=7),
            'iat': datetime.utcnow(),
        }
        return jwt.encode(payload, secret_key, algorithm='HS256')

    @staticmethod
    def verify_jwt_token(token: str, secret_key: str):
        try:
            payload = jwt.decode(token, secret_key, algorithms=['HS256'])
            user = User.query.get(payload['user_id'])
            return user if user and user.is_active else None
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return None

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'full_name': self.get_full_name(),
            'phone': self.phone,
            'role': self.role,
            'department': self.department,
            'is_active': self.is_active,
            'is_verified': self.is_verified,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'tenant_type': self.tenant.tenant_type if self.tenant else None,
            'company_name': self.tenant.company_name if self.tenant and self.tenant.tenant_type == 'company' else None,
        }


class LoginAttempt(db.Model):
    """Track login attempts for security"""
    __tablename__ = 'login_attempts'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=True, index=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    ip_address = db.Column(db.String(45), nullable=False)
    success = db.Column(db.Boolean, default=False)
    attempted_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<LoginAttempt {self.email} - {"Success" if self.success else "Failed"}>'


class Session(db.Model):
    """User session management"""
    __tablename__ = 'user_sessions'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    session_token = db.Column(db.String(255), unique=True, nullable=False)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='sessions')

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at


# ============================================================
# CUSTOMER (Universal B2B/B2C)
# ============================================================

class Customer(db.Model):
    """
    Universal customer model with industry-agnostic fields
    Industry-specific data stored in custom_data JSON field
    """
    __tablename__ = 'customers'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)

    # Basic Contact Information
    name = db.Column(db.String(200), nullable=False)
    company_name = db.Column(db.String(255), nullable=True)
    address = db.Column(db.Text)
    postcode = db.Column(db.String(20))
    phone = db.Column(db.String(50))
    email = db.Column(db.String(200))
    
    # Business Information (B2B)
    industry = db.Column(db.String(255), nullable=True)
    company_size = db.Column(db.String(50), nullable=True)  # "1-10", "11-50", "51-200", etc.
    
    # Contact Preferences
    contact_made = db.Column(CONTACT_MADE_ENUM, default='Unknown')
    preferred_contact_method = db.Column(PREFERRED_CONTACT_ENUM, nullable=True)
    marketing_opt_in = db.Column(db.Boolean, default=False)
    
    # Sales Pipeline
    stage = db.Column(db.String(50), default='Prospect')  # Universal stage
    salesperson = db.Column(db.String(200))
    
    # 🎯 NEW: Industry-Specific Data (JSONB)
    custom_data = db.Column(db.JSON, default=dict)
    # Examples:
    # Education: {"customer_type": "Individual", "mhe_type": "Forklift", "batch_size": 10, "training_stage": "Scheduled"}
    # Interior: {"project_types": ["Kitchen", "Bedroom"], "date_of_measure": "2024-01-15", "room_count": 3}
    # Generic: {} (empty)
    
    # Additional Information
    notes = db.Column(db.Text)
    status = db.Column(db.String(50), default='active')
    
    # Audit Fields
    created_by = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.String(200))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tenant = db.relationship('Tenant', back_populates='customers')
    opportunities = db.relationship('Opportunity', back_populates='customer', lazy=True, cascade='all, delete-orphan')
    proposals = db.relationship('Proposal', back_populates='customer', lazy=True, cascade='all, delete-orphan')
    form_data = db.relationship('CustomerFormData', viewonly=True, lazy=True)
    form_submissions = db.relationship('FormSubmission', viewonly=True, lazy=True)
    assignments = db.relationship('Assignment', backref='customer_rel', lazy=True, passive_deletes='all')

    def update_stage_from_opportunity(self):
        """Update customer stage based on primary opportunity"""
        primary_opp = self.get_primary_opportunity()
        if primary_opp:
            self.stage = primary_opp.stage
            db.session.commit()

    def get_primary_opportunity(self):
        """Get customer's most recent active opportunity"""
        from sqlalchemy import and_
        return Opportunity.query.filter(
            and_(Opportunity.customer_id == self.id, Opportunity.stage != 'Closed Lost')
        ).order_by(Opportunity.created_at.desc()).first()

    def save(self):
        """Save customer to database"""
        db.session.add(self)
        db.session.commit()

    def __repr__(self):
        return f'<Customer {self.name}>'


# ============================================================
# OPPORTUNITY (Universal Sales)
# ============================================================

class Opportunity(db.Model):
    """
    Universal opportunity/deal tracking
    Industry-specific data stored in custom_data JSON field
    """
    __tablename__ = 'opportunities'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'), nullable=False)

    # Basic Opportunity Info
    opportunity_reference = db.Column(db.String(100), unique=True)
    opportunity_name = db.Column(db.String(200))
    stage = db.Column(db.String(50), nullable=False, default='Prospect')
    priority = db.Column(db.String(20), default='Medium')  # Low, Medium, High, Urgent

    # Financial Information
    estimated_value = db.Column(db.Numeric(10, 2))
    probability = db.Column(db.Integer)  # 0-100% win probability
    
    # Dates
    expected_close_date = db.Column(db.DateTime)
    actual_close_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Team Assignments
    salesperson_name = db.Column(db.String(100))
    salesperson_id = db.Column(db.Integer, db.ForeignKey('salespeople.id'))

    # Links
    proposal_id = db.Column(db.Integer, db.ForeignKey('proposals.id'))

    # Boolean Flags
    has_proposal = db.Column(db.Boolean, default=False)
    has_contract = db.Column(db.Boolean, default=False)
    has_invoice = db.Column(db.Boolean, default=False)

    # 🎯 NEW: Industry-Specific Data
    custom_data = db.Column(db.JSON, default=dict)
    # Examples:
    # Education: {"course_type": "Forklift Advanced", "participants": 15}
    # Interior: {"rooms": ["Kitchen", "Master Bedroom"], "installation_type": "Full"}
    
    # Additional Info
    notes = db.Column(db.Text)

    # Relationships
    tenant = db.relationship('Tenant')
    customer = db.relationship('Customer', back_populates='opportunities')
    proposal = db.relationship('Proposal', foreign_keys=[proposal_id], back_populates='opportunity', uselist=False)
    salesperson = db.relationship('Salesperson', foreign_keys=[salesperson_id])
    documents = db.relationship('OpportunityDocument', back_populates='opportunity', lazy=True, cascade='all, delete-orphan')
    activities = db.relationship('Activity', viewonly=True, lazy=True)
    notes_list = db.relationship('OpportunityNote', viewonly=True, lazy=True)
    invoices = db.relationship('Invoice', back_populates='opportunity', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', back_populates='opportunity', lazy=True, cascade='all, delete-orphan')
    assignments = db.relationship('Assignment', backref='opportunity_rel', lazy=True, passive_deletes='all')

    def __repr__(self):
        return f'<Opportunity {self.opportunity_reference or self.id}: {self.opportunity_name}>'


# ============================================================
# JOB (Universal Work Management)
# ============================================================

def generate_job_reference():
    """Generate unique job reference: JOB-YYYYMMDD-HHMMSS-XXX"""
    now = datetime.utcnow()
    date_part = now.strftime("%Y%m%d")
    time_part = now.strftime("%H%M%S")
    random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=3))
    return f"JOB-{date_part}-{time_part}-{random_suffix}"


class Job(db.Model):
    """
    Universal job/work unit tracking
    Industry-specific data stored in custom_data JSON field
    """
    __tablename__ = "jobs"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    job_reference = db.Column(db.String(50), unique=True, nullable=False, default=generate_job_reference)
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'), nullable=False)

    # Core Job Info
    title = db.Column(db.String(255), nullable=False, default="New Job")
    job_type = db.Column(db.String(100), default="General")
    description = db.Column(db.Text)
    requirements = db.Column(db.Text)
    tags = db.Column(db.String(255))  # Comma-separated

    # Pipeline / Status
    stage = db.Column(db.String(50), default="Prospect")
    priority = db.Column(db.String(20), default="Medium")

    # Timeline
    start_date = db.Column(db.Date, nullable=True)
    due_date = db.Column(db.Date)
    completion_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Financial
    estimated_value = db.Column(db.Numeric(10, 2))
    agreed_value = db.Column(db.Numeric(10, 2))
    deposit_amount = db.Column(db.Numeric(10, 2))
    deposit_due_date = db.Column(db.Date)

    # Location & Team
    location = db.Column(db.String(255))
    primary_contact = db.Column(db.String(255))
    team_members_json = db.Column(db.Text)  # JSON list of team members

    # Links
    quote_id = db.Column(db.String(36))

    # 🎯 NEW: Industry-Specific Data
    custom_data = db.Column(db.JSON, default=dict)
    # Examples:
    # Education: {"training_date": "2024-03-15", "instructor": "John Doe", "venue": "Main Hall"}
    # Interior: {"rooms": ["Kitchen"], "work_stage": "Production", "fitter": "Team A"}
    
    # Notes
    notes = db.Column(db.Text)

    # Relationships
    tenant = db.relationship('Tenant')
    customer = db.relationship("Customer", backref="jobs")

    def __repr__(self):
        return f"<Job {self.job_reference}: {self.title}>"

    @property
    def team_members(self):
        """Get team members list from JSON"""
        try:
            return json.loads(self.team_members_json) if self.team_members_json else []
        except Exception:
            return []

    @team_members.setter
    def team_members(self, value):
        """Set team members list as JSON"""
        try:
            self.team_members_json = json.dumps(value or [])
        except Exception:
            self.team_members_json = "[]"


# ============================================================
# TEAM MANAGEMENT
# ============================================================

class Team(db.Model):
    """Teams for organizing staff"""
    __tablename__ = 'teams'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    specialty = db.Column(db.String(100))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    members = db.relationship('TeamMember', back_populates='team', lazy=True)
    tenant = db.relationship('Tenant')


class TeamMember(db.Model):
    """Individual team members/staff"""
    __tablename__ = 'team_members'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'))
    role = db.Column(db.String(100))
    skills = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    team = db.relationship('Team', back_populates='members')
    tenant = db.relationship('Tenant')


class Salesperson(db.Model):
    """Sales team members"""
    __tablename__ = 'salespeople'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('Tenant')


# ============================================================
# SCHEDULE & ASSIGNMENTS
# ============================================================

class Assignment(db.Model):
    """Calendar assignments and tasks"""
    __tablename__ = 'assignments'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Assignment Type & Details
    type = db.Column(ASSIGNMENT_TYPE_ENUM, nullable=False, default='task')
    title = db.Column(db.String(255), nullable=False)
    date = db.Column(db.Date, nullable=False)
    
    # Date Range
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    
    # Staff Assignment
    staff_id = db.Column(db.Integer, db.ForeignKey('team_members.id'), nullable=True)
    team_member = db.Column(db.String(200), nullable=True)
    
    # Customer/Opportunity Links
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id', ondelete='CASCADE'), nullable=True)
    customer_name = db.Column(db.String(200), nullable=True)
    opportunity_id = db.Column(db.String(36), db.ForeignKey('opportunities.id', ondelete='CASCADE'), nullable=True)
    job_id = db.Column(db.String(36), nullable=True)
    job_type = db.Column(db.String(100), nullable=True)
    
    # Time Tracking
    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)
    estimated_hours = db.Column(db.Float, nullable=True)
    
    # Additional Info
    notes = db.Column(db.Text, nullable=True)
    priority = db.Column(db.String(20), default='Medium')
    status = db.Column(db.String(20), default='Scheduled')
    
    # Audit
    created_by = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.String(200), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    staff = db.relationship('TeamMember', backref='assignments')
    opportunity = db.relationship('Opportunity', backref='opportunity_assignments', viewonly=True)
    customer = db.relationship('Customer', backref='customer_assignments', viewonly=True)
    tenant = db.relationship('Tenant')
    
    def __repr__(self):
        return f'<Assignment {self.id}: {self.title} on {self.date}>'
    
    def calculate_hours(self):
        """Calculate hours from start_time and end_time"""
        if self.start_time and self.end_time:
            start_datetime = datetime.combine(datetime.today(), self.start_time)
            end_datetime = datetime.combine(datetime.today(), self.end_time)
            duration = end_datetime - start_datetime
            return duration.total_seconds() / 3600
        return self.estimated_hours or 0
    
    def to_dict(self):
        """Convert to dictionary"""
        staff_name = None
        try:
            if self.staff and hasattr(self.staff, 'name'):
                staff_name = self.staff.name
            elif self.team_member:
                staff_name = self.team_member
        except Exception:
            staff_name = self.team_member
        
        customer_name = None
        try:
            if self.customer and hasattr(self.customer, 'name'):
                customer_name = self.customer.name
            elif self.customer_name:
                customer_name = self.customer_name
        except Exception:
            customer_name = self.customer_name
        
        opportunity_reference = None
        try:
            if self.opportunity and hasattr(self.opportunity, 'opportunity_reference'):
                opportunity_reference = self.opportunity.opportunity_reference
        except Exception:
            pass
        
        return {
            'id': self.id,
            'type': self.type,
            'title': self.title,
            'date': self.date.isoformat() if self.date else None,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'staff_id': str(self.staff_id) if self.staff_id else None,
            'team_member': staff_name,
            'staff_name': staff_name,
            'customer_id': self.customer_id,
            'customer_name': customer_name,
            'opportunity_id': self.opportunity_id,
            'opportunity_reference': opportunity_reference,
            'job_id': self.job_id,
            'job_type': self.job_type,
            'start_time': self.start_time.strftime('%H:%M') if self.start_time else None,
            'end_time': self.end_time.strftime('%H:%M') if self.end_time else None,
            'estimated_hours': self.estimated_hours,
            'notes': self.notes,
            'priority': self.priority,
            'status': self.status,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_by': self.updated_by,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'tenant_id': self.tenant_id,
        }