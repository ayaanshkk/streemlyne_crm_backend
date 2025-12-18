import json
import uuid
import secrets
from datetime import datetime, timedelta, date
import random
import string
from database import db  # Import SQLAlchemy instance
from werkzeug.security import generate_password_hash, check_password_hash
import jwt

# ----------------------------------
# Helpers / Enums
# ----------------------------------

# Universal sales pipeline stages
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


# ----------------------------------
# Auth & Security
# ----------------------------------

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)  # ADD THIS
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # Profile
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20))

    # Role & permissions
    role = db.Column(db.String(20), default='user')  # admin, manager, sales, user
    department = db.Column(db.String(50))

    # Account status
    is_active = db.Column(db.Boolean, default=True)
    is_verified = db.Column(db.Boolean, default=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    # Password reset
    reset_token = db.Column(db.String(100))
    reset_token_expires = db.Column(db.DateTime)

    # Email verification
    verification_token = db.Column(db.String(100))

    tenant = db.relationship('Tenant', back_populates='users')

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
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
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
        }


class LoginAttempt(db.Model):
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


# ----------------------------------
# Core CRM Entities
# ----------------------------------

class Customer(db.Model):
    __tablename__ = 'customers'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)  # ADD THIS
    tenant = db.relationship('Tenant', back_populates='customers')  # ADD THIS

    # Basic contact information
    name = db.Column(db.String(200), nullable=False)
    company_name = db.Column(db.String(255), nullable=True)
    address = db.Column(db.Text)
    postcode = db.Column(db.String(20))
    phone = db.Column(db.String(50))
    email = db.Column(db.String(200))
    
    # Business information
    industry = db.Column(db.String(255), nullable=True)
    company_size = db.Column(db.String(50), nullable=True)  # e.g., "1-10", "11-50", etc.
    
    # Contact preferences
    contact_made = db.Column(CONTACT_MADE_ENUM, default='Unknown')
    preferred_contact_method = db.Column(PREFERRED_CONTACT_ENUM, nullable=True)
    marketing_opt_in = db.Column(db.Boolean, default=False)
    
    # Sales information
    stage = db.Column(db.String(50), default='Prospect')
    salesperson = db.Column(db.String(200))
    
    # Additional information
    notes = db.Column(db.Text)
    
    # Audit fields
    created_by = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.String(200))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Status
    status = db.Column(db.String(50), default='active')

    # Relationships
    opportunities = db.relationship('Opportunity', back_populates='customer', lazy=True, cascade='all, delete-orphan')
    proposals = db.relationship('Proposal', back_populates='customer', lazy=True, cascade='all, delete-orphan')
    form_data = db.relationship('CustomerFormData', back_populates='customer', lazy=True, cascade='all, delete-orphan')
    form_submissions = db.relationship('FormSubmission', back_populates='customer', lazy=True)
    
    # ADDED: Explicitly define backref for Assignment with passive_deletes
    assignments = db.relationship('Assignment', backref='customer_rel', lazy=True, passive_deletes='all')

    def update_stage_from_opportunity(self):
        """Update customer stage based on their primary opportunity's stage"""
        primary_opp = self.get_primary_opportunity()
        if primary_opp:
            self.stage = primary_opp.stage
            db.session.commit()

    def get_primary_opportunity(self):
        """Get the customer's primary (most recent or active) opportunity"""
        from sqlalchemy import and_
        return Opportunity.query.filter(
            and_(Opportunity.customer_id == self.id, Opportunity.stage != 'Closed Lost')
        ).order_by(Opportunity.created_at.desc()).first()

    def save(self):
        """Save customer"""
        db.session.add(self)
        db.session.commit()

    def __repr__(self):
        return f'<Customer {self.name}>'


class Team(db.Model):
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
    __tablename__ = 'salespeople'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('Tenant')


class Opportunity(db.Model):
    __tablename__ = 'opportunities'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'), nullable=False)

    # Basic opportunity info
    opportunity_reference = db.Column(db.String(100), unique=True)
    opportunity_name = db.Column(db.String(200))
    stage = db.Column(db.String(50), nullable=False, default='Prospect')
    priority = db.Column(db.String(20), default='Medium')

    # Financial information
    estimated_value = db.Column(db.Numeric(10, 2))
    probability = db.Column(db.Integer)  # 0-100%
    
    # Dates
    expected_close_date = db.Column(db.DateTime)
    actual_close_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Additional info
    notes = db.Column(db.Text)

    # Team assignments
    salesperson_name = db.Column(db.String(100))
    salesperson_id = db.Column(db.Integer, db.ForeignKey('salespeople.id'))

    # Links
    proposal_id = db.Column(db.Integer, db.ForeignKey('proposals.id'))

    # Boolean flags
    has_proposal = db.Column(db.Boolean, default=False)
    has_contract = db.Column(db.Boolean, default=False)
    has_invoice = db.Column(db.Boolean, default=False)

    # Relationships
    customer = db.relationship('Customer', back_populates='opportunities')
    proposal = db.relationship('Proposal', foreign_keys=[proposal_id], back_populates='opportunity', uselist=False)
    salesperson = db.relationship('Salesperson', foreign_keys=[salesperson_id])

    documents = db.relationship('OpportunityDocument', back_populates='opportunity', lazy=True, cascade='all, delete-orphan')
    activities = db.relationship('Activity', back_populates='opportunity', lazy=True, cascade='all, delete-orphan')
    notes_list = db.relationship('OpportunityNote', back_populates='opportunity', lazy=True, cascade='all, delete-orphan')
    invoices = db.relationship('Invoice', back_populates='opportunity', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', back_populates='opportunity', lazy=True, cascade='all, delete-orphan')
    
    # ADDED: Explicitly define backref for Assignment with passive_deletes
    assignments = db.relationship('Assignment', backref='opportunity_rel', lazy=True, passive_deletes='all')

    tenant = db.relationship('Tenant')

    def __repr__(self):
        return f'<Opportunity {self.opportunity_reference or self.id}: {self.opportunity_name}>'


# ----------------------------------
# Documents / Activities
# ----------------------------------

class OpportunityDocument(db.Model):
    __tablename__ = 'opportunity_documents'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    opportunity_id = db.Column(db.String(36), db.ForeignKey('opportunities.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)
    mime_type = db.Column(db.String(100))
    category = db.Column(db.String(50))
    uploaded_by = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    opportunity = db.relationship('Opportunity', back_populates='documents')

    tenant = db.relationship('Tenant')


class Activity(db.Model):
    __tablename__ = 'activities'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    opportunity_id = db.Column(db.String(36), db.ForeignKey('opportunities.id'), nullable=False)
    
    activity_type = db.Column(db.String(50), nullable=False)  # meeting, call, email, task
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    
    scheduled_date = db.Column(db.DateTime)
    completed_date = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='Scheduled')  # Scheduled, Completed, Cancelled
    
    assigned_to = db.Column(db.String(200))
    created_by = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    opportunity = db.relationship('Opportunity', back_populates='activities')


class OpportunityNote(db.Model):
    __tablename__ = 'opportunity_notes'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    opportunity_id = db.Column(db.String(36), db.ForeignKey('opportunities.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    note_type = db.Column(db.String(50), default='general')
    author = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    opportunity = db.relationship('Opportunity', back_populates='notes_list')

    tenant = db.relationship('Tenant')


# ----------------------------------
# Products / Services Catalogue
# ----------------------------------

class ProductCategory(db.Model):
    __tablename__ = 'product_categories'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    products = db.relationship('Product', back_populates='category', lazy=True)

    tenant = db.relationship('Tenant')  

    def __repr__(self):
        return f'<ProductCategory {self.name}>'


class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('product_categories.id'), nullable=False)

    sku = db.Column(db.String(100), nullable=False, unique=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    # Pricing
    base_price = db.Column(db.Numeric(10, 2))
    discount_price = db.Column(db.Numeric(10, 2))
    
    # Inventory
    active = db.Column(db.Boolean, default=True)
    in_stock = db.Column(db.Boolean, default=True)
    stock_quantity = db.Column(db.Integer)

    # Additional info
    specifications = db.Column(db.Text)  # JSON string
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = db.relationship('ProductCategory', back_populates='products')
    proposal_items = db.relationship('ProposalItem', back_populates='product', lazy=True)

    tenant = db.relationship('Tenant')

    def __repr__(self):
        return f'<Product {self.sku}: {self.name}>'


# ----------------------------------
# Proposals
# ----------------------------------

class Proposal(db.Model):
    __tablename__ = 'proposals'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=True, index=True)
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'), nullable=False)
    reference_number = db.Column(db.String(50), unique=True)
    title = db.Column(db.String(255))
    total = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(20), default='Draft')  # Draft, Sent, Accepted, Rejected
    valid_until = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = db.relationship('Customer', back_populates='proposals')
    items = db.relationship('ProposalItem', back_populates='proposal', lazy=True, cascade='all, delete-orphan')
    opportunity = db.relationship('Opportunity', back_populates='proposal', uselist=False)


class ProposalItem(db.Model):
    __tablename__ = 'proposal_items'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=True, index=True)
    proposal_id = db.Column(db.Integer, db.ForeignKey('proposals.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'))

    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    line_total = db.Column(db.Numeric(10, 2))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    proposal = db.relationship('Proposal', back_populates='items')
    product = db.relationship('Product', back_populates='proposal_items')

    tenant = db.relationship('Tenant')

    def calculate_line_total(self):
        self.line_total = (self.unit_price or 0) * (self.quantity or 0)
        return self.line_total


# ----------------------------------
# Invoicing & Payments
# ----------------------------------

class Invoice(db.Model):
    __tablename__ = 'invoices'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    opportunity_id = db.Column(db.String(36), db.ForeignKey('opportunities.id'), nullable=False)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    status = db.Column(db.String(20), default='Draft')  # Draft, Sent, Paid, Overdue, Cancelled
    due_date = db.Column(db.Date)
    paid_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    opportunity = db.relationship('Opportunity', back_populates='invoices')
    line_items = db.relationship('InvoiceLineItem', back_populates='invoice', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', back_populates='invoice', lazy=True)

    tenant = db.relationship('Tenant')

    @property
    def amount_due(self):
        total = sum([(li.quantity or 0) * (li.unit_price or 0) for li in self.line_items])
        return total

    @property
    def amount_paid(self):
        return sum([p.amount or 0 for p in self.payments if p.cleared])

    @property
    def balance(self):
        return (self.amount_due or 0) - (self.amount_paid or 0)


class InvoiceLineItem(db.Model):
    __tablename__ = 'invoice_line_items'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=True, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    tax_rate = db.Column(db.Numeric(5, 2), default=0)  # e.g. 20.00 for 20%

    invoice = db.relationship('Invoice', back_populates='line_items')


class Payment(db.Model):
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=True, index=True)
    opportunity_id = db.Column(db.String(36), db.ForeignKey('opportunities.id'), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'))

    date = db.Column(db.Date, default=datetime.utcnow)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    method = db.Column(PAYMENT_METHOD_ENUM, default='Bank Transfer')
    reference = db.Column(db.String(120))
    notes = db.Column(db.Text)

    cleared = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    opportunity = db.relationship('Opportunity', back_populates='payments')
    invoice = db.relationship('Invoice', back_populates='payments')

    tenant = db.relationship('Tenant')


# ----------------------------------
# Templates Library
# ----------------------------------

class DocumentTemplate(db.Model):
    __tablename__ = 'document_templates'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    template_type = db.Column(DOCUMENT_TEMPLATE_TYPE_ENUM, nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    merge_fields = db.Column(db.JSON)
    uploaded_by = db.Column(db.String(200))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('Tenant')


# ----------------------------------
# Audit & Versioning
# ----------------------------------

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=True, index=True)
    entity_type = db.Column(db.String(120), nullable=False)
    entity_id = db.Column(db.String(120), nullable=False)
    action = db.Column(AUDIT_ACTION_ENUM, nullable=False)
    changed_by = db.Column(db.String(200))
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)
    change_summary = db.Column(db.JSON)
    previous_snapshot = db.Column(db.JSON)
    new_snapshot = db.Column(db.JSON)


class VersionedSnapshot(db.Model):
    __tablename__ = 'versioned_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=True, index=True)
    entity_type = db.Column(db.String(120), nullable=False)
    entity_id = db.Column(db.String(120), nullable=False)
    version_number = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(255))
    snapshot = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.String(200))


# ----------------------------------
# Forms / Submissions
# ----------------------------------

class FormSubmission(db.Model):
    __tablename__ = 'form_submissions'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=True, index=True)
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'))
    form_data = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(100))
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed = db.Column(db.Boolean, default=False)
    processed_at = db.Column(db.DateTime)

    customer = db.relationship('Customer', back_populates='form_submissions')


class CustomerFormData(db.Model):
    __tablename__ = 'customer_form_data'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=True, index=True)
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'), nullable=False)
    form_data = db.Column(db.Text, nullable=False)
    token_used = db.Column(db.String(64), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    customer = db.relationship('Customer', back_populates='form_data')

    tenant = db.relationship('Tenant')

    def __repr__(self):
        return f'<CustomerFormData {self.id} for Customer {self.customer_id}>'


class DataImport(db.Model):
    __tablename__ = 'data_imports'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=True, index=True)
    filename = db.Column(db.String(255), nullable=False)
    import_type = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default='processing')
    records_processed = db.Column(db.Integer, default=0)
    records_failed = db.Column(db.Integer, default=0)
    error_log = db.Column(db.Text)
    imported_by = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    def __repr__(self):
        return f'<DataImport {self.filename} ({self.status})>'


# ----------------------------------
# Assignments / Schedule
# ----------------------------------

class Assignment(db.Model):
    __tablename__ = 'assignments'

    # Primary key
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Required fields
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    type = db.Column(ASSIGNMENT_TYPE_ENUM, nullable=False, default='task')
    title = db.Column(db.String(255), nullable=False)
    date = db.Column(db.Date, nullable=False)
    
    # Date range fields (NEW - already in your database)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    
    # Staff assignment (staff_id is nullable, can use team_member text instead)
    staff_id = db.Column(db.Integer, db.ForeignKey('team_members.id'), nullable=True)
    team_member = db.Column(db.String(200), nullable=True)  # Text-based assignment
    
    # Customer reference
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id', ondelete='CASCADE'), nullable=True)
    customer_name = db.Column(db.String(200), nullable=True)  # Cached for faster display
    
    # Opportunity/Job references
    opportunity_id = db.Column(db.String(36), db.ForeignKey('opportunities.id', ondelete='CASCADE'), nullable=True)
    job_id = db.Column(db.String(36), nullable=True)  # NEW field
    job_type = db.Column(db.String(100), nullable=True)  # NEW field
    
    # Time tracking
    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)
    estimated_hours = db.Column(db.Float, nullable=True)
    
    # Additional info
    notes = db.Column(db.Text, nullable=True)
    priority = db.Column(db.String(20), default='Medium')
    status = db.Column(db.String(20), default='Scheduled')
    
    # Audit fields
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
        """Convert assignment to dictionary - handles all fields safely"""
        # Get staff name safely
        staff_name = None
        try:
            if self.staff and hasattr(self.staff, 'name'):
                staff_name = self.staff.name
            elif self.team_member:
                staff_name = self.team_member
        except Exception:
            staff_name = self.team_member
        
        # Get customer name safely
        customer_name = None
        try:
            if self.customer and hasattr(self.customer, 'name'):
                customer_name = self.customer.name
            elif self.customer_name:
                customer_name = self.customer_name
        except Exception:
            customer_name = self.customer_name
        
        # Get opportunity reference safely
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
            'staff_name': staff_name,  # Alias for compatibility
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
    
#--------------
# JOB 
#--------------

def generate_job_reference():
    """
    Generate a unique job reference with format: JOB-YYYYMMDD-HHMMSS-XXX
    Where XXX is a random 3-character alphanumeric suffix for uniqueness
    """
    now = datetime.utcnow()
    date_part = now.strftime("%Y%m%d")
    time_part = now.strftime("%H%M%S")
    random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=3))
    return f"JOB-{date_part}-{time_part}-{random_suffix}"

class Job(db.Model):
    __tablename__ = "jobs"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    job_reference = db.Column(db.String(50), unique=True, nullable=False, default=generate_job_reference)

    # Core job info
    title = db.Column(db.String(255), nullable=False, default="New Job")
    job_type = db.Column(db.String(100), default="General")
    description = db.Column(db.Text)           # long description
    requirements = db.Column(db.Text)          # what needs to be done
    tags = db.Column(db.String(255))           # comma-separated tags

    # pipeline / status
    stage = db.Column(db.String(50), default="Prospect")
    priority = db.Column(db.String(20), default="Medium")

    # Linked customer
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'), nullable=False)
    customer = db.relationship("Customer", backref="jobs")

    # Dates
    start_date = db.Column(db.Date, nullable=True)
    due_date = db.Column(db.Date)
    completion_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Financials
    estimated_value = db.Column(db.Numeric(10,2))
    agreed_value = db.Column(db.Numeric(10,2))
    deposit_amount = db.Column(db.Numeric(10,2))
    deposit_due_date = db.Column(db.Date)

    # Location & contacts
    location = db.Column(db.String(255))
    primary_contact = db.Column(db.String(255))  # name of main contact

    # Team / Assignment
   # account_manager = db.Column(db.String(100))
    team_members_json = db.Column(db.Text)   # JSON list of team members; keep text for sqlite compatibility

    # Links
    quote_id = db.Column(db.String(36))

    # Notes
    notes = db.Column(db.Text)

    tenant = db.relationship('Tenant')

    def __repr__(self):
        return f"<Job {self.job_reference}: {self.title}>"

    # convenience property to read/write team members
    @property
    def team_members(self):
        try:
            return json.loads(self.team_members_json) if self.team_members_json else []
        except Exception:
            return []

    @team_members.setter
    def team_members(self, value):
        try:
            self.team_members_json = json.dumps(value or [])
        except Exception:
            self.team_members_json = "[]"

class Tenant(db.Model):
    __tablename__ = 'tenants'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Company identification
    company_name = db.Column(db.String(255), nullable=False, unique=True)
    subdomain = db.Column(db.String(100), unique=True, nullable=False)  # aztec, client2
    custom_domain = db.Column(db.String(255), unique=True)  # optional: aztec.com
    
    # Contact info
    contact_email = db.Column(db.String(255))
    contact_phone = db.Column(db.String(50))
    
    # Subscription & Features
    subscription_tier = db.Column(db.String(50), default='basic')  # basic, professional, enterprise
    features = db.Column(db.JSON)  # Feature flags
    settings = db.Column(db.JSON)  # Tenant-specific settings
    
    # Branding
    logo_url = db.Column(db.String(500))
    primary_color = db.Column(db.String(7))  # hex color
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    is_trial = db.Column(db.Boolean, default=False)
    trial_ends_at = db.Column(db.DateTime)
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    users = db.relationship('User', back_populates='tenant', lazy=True)
    customers = db.relationship('Customer', back_populates='tenant', lazy=True)
    
    def __repr__(self):
        return f'<Tenant {self.company_name} ({self.subdomain})>'
    
    def has_feature(self, feature_name: str) -> bool:
        """Check if tenant has access to a feature"""
        if not self.features:
            return False
        return self.features.get(feature_name, False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'company_name': self.company_name,
            'subdomain': self.subdomain,
            'subscription_tier': self.subscription_tier,
            'is_active': self.is_active,
            'features': self.features or {}
        }