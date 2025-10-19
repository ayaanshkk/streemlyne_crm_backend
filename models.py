# models.py - Updated schema to align with the data model spec
# Notes:
# - Switch to UUIDs for Customer.id and Job.id (string-based UUIDs)
# - Normalise deposits/payments via a Payment model
# - Add CountingSheet/CountingItem, RemedialAction/RemedialItem
# - Add DocumentTemplate, AuditLog, VersionedSnapshot
# - Strengthen enums for controlled vocabularies
# - Fix FK type mismatches (e.g., Job.customer_id -> String(36) FK to customers.id)
# - UPDATED: Added universal B2B fields to Customer model
# - FIXED: Removed nullable=False from company_name, industry, company_size to allow NULL values

import uuid
import secrets
from datetime import datetime, timedelta

from database import db  # Import SQLAlchemy instance
from werkzeug.security import generate_password_hash, check_password_hash
import jwt

# ----------------------------------
# Helpers / Enums
# ----------------------------------

JOB_STAGE_ENUM = db.Enum(
    'Lead', 'Quote', 'Consultation', 'Survey', 'Measure', 'Design', 'Quoted', 'Accepted',
    'OnHold', 'Production', 'Delivery', 'Installation', 'Complete', 'Remedial', 'Cancelled',
    name='job_stage_enum'
)

JOB_TYPE_ENUM = db.Enum(
    'Kitchen', 'Bedroom', 'Wardrobe', 'Remedial', 'Other',
    name='job_type_enum'
)

CONTACT_MADE_ENUM = db.Enum('Yes', 'No', 'Unknown', name='contact_made_enum')
PREFERRED_CONTACT_ENUM = db.Enum('Phone', 'Email', 'WhatsApp', name='preferred_contact_enum')

CHECKLIST_TEMPLATE_ENUM = db.Enum(
    'BedroomChecklist', 'KitchenChecklist', 'PaymentTerms', 'CustomerSatisfaction',
    'RemedialAction', 'PromotionalOffer', name='checklist_template_enum'
)

DOCUMENT_TEMPLATE_TYPE_ENUM = db.Enum(
    'Invoice', 'Receipt', 'Quotation', 'Warranty', 'Terms', 'Other', name='document_template_type_enum'
)

PAYMENT_METHOD_ENUM = db.Enum('BACS', 'Cash', 'Card', 'Other', name='payment_method_enum')

AUDIT_ACTION_ENUM = db.Enum('create', 'update', 'delete', name='audit_action_enum')

ASSIGNMENT_TYPE_ENUM = db.Enum('job', 'off', 'delivery', 'note', name='assignment_type_enum')

# ----------------------------------
# Auth & Security
# ----------------------------------

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # Profile
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20))

    # Role & permissions
    role = db.Column(db.String(20), default='user')  # admin, manager, user
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

    def __repr__(self):
        return f'<User {self.email}>'

    # Password utils
    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    # Tokens
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
    email = db.Column(db.String(120), nullable=False, index=True)
    ip_address = db.Column(db.String(45), nullable=False)
    success = db.Column(db.Boolean, default=False)
    attempted_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<LoginAttempt {self.email} - {"Success" if self.success else "Failed"}>'


class Session(db.Model):
    __tablename__ = 'user_sessions'

    id = db.Column(db.Integer, primary_key=True)
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
    
    # Basic contact information
    name = db.Column(db.String(200), nullable=False)
    company_name = db.Column(db.String(255), nullable=True)  # FIXED - Now allows NULL
    address = db.Column(db.Text)
    postcode = db.Column(db.String(20))
    phone = db.Column(db.String(50))
    email = db.Column(db.String(200))
    
    # Business information (for universal B2B)
    industry = db.Column(db.String(255), nullable=True)  # FIXED - Now allows NULL
    company_size = db.Column(db.String(50), nullable=True)  # FIXED - Now allows NULL
    
    # Contact preferences
    contact_made = db.Column(CONTACT_MADE_ENUM, default='Unknown')
    preferred_contact_method = db.Column(PREFERRED_CONTACT_ENUM)
    marketing_opt_in = db.Column(db.Boolean, default=False)
    
    # Sales information
    stage = db.Column(db.String(50), default='Prospect')  # VARCHAR for universal stages
    salesperson = db.Column(db.String(200))
    
    # Legacy/interior-specific fields (keep for backward compatibility)
    date_of_measure = db.Column(db.Date)
    project_types = db.Column(db.JSON)
    
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
    jobs = db.relationship('Job', back_populates='customer', lazy=True, cascade='all, delete-orphan')
    quotations = db.relationship('Quotation', back_populates='customer', lazy=True, cascade='all, delete-orphan')
    form_data = db.relationship('CustomerFormData', back_populates='customer', lazy=True, cascade='all, delete-orphan')
    form_submissions = db.relationship('FormSubmission', back_populates='customer', lazy=True)

    def extract_postcode_from_address(self):
        """Extract UK postcode from address string"""
        if not self.address:
            return None
        import re
        pattern = r'\b[A-Z]{1,2}[0-9][A-Z0-9]? ?[0-9][A-Z]{2}\b'
        match = re.search(pattern, self.address.upper())
        return match.group(0) if match else None

    def update_stage_from_job(self):
        """Update customer stage based on their primary job's stage"""
        primary_job = self.get_primary_job()
        if primary_job:
            self.stage = primary_job.stage
            db.session.commit()

    def get_primary_job(self):
        """Get the customer's primary (most recent or active) job"""
        from sqlalchemy import and_
        return Job.query.filter(
            and_(Job.customer_id == self.id, Job.stage != 'Cancelled')
        ).order_by(Job.created_at.desc()).first()

    def save(self):
        """Save customer and auto-extract postcode if needed"""
        if not self.postcode and self.address:
            self.postcode = self.extract_postcode_from_address()
        db.session.add(self)
        db.session.commit()

    def __repr__(self):
        return f'<Customer {self.name}>'


class Team(db.Model):
    __tablename__ = 'teams'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    specialty = db.Column(db.String(100))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    members = db.relationship('Fitter', back_populates='team', lazy=True)


class Fitter(db.Model):
    __tablename__ = 'fitters'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'))
    skills = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    team = db.relationship('Team', back_populates='members')


class Salesperson(db.Model):
    __tablename__ = 'salespeople'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Job(db.Model):
    __tablename__ = 'jobs'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))  # UUID
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'), nullable=False)

    # Basic job info
    job_reference = db.Column(db.String(100), unique=True)
    job_name = db.Column(db.String(200))
    job_type = db.Column(JOB_TYPE_ENUM, nullable=False, default='Kitchen')
    stage = db.Column(JOB_STAGE_ENUM, nullable=False, default='Lead')
    priority = db.Column(db.String(20), default='Medium')

    # Pricing
    quote_price = db.Column(db.Numeric(10, 2))
    agreed_price = db.Column(db.Numeric(10, 2))
    sold_amount = db.Column(db.Numeric(10, 2))
    deposit1 = db.Column(db.Numeric(10, 2))
    deposit2 = db.Column(db.Numeric(10, 2))

    # Dates
    delivery_date = db.Column(db.DateTime)
    measure_date = db.Column(db.DateTime)
    completion_date = db.Column(db.DateTime)
    deposit_due_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Additional info
    installation_address = db.Column(db.Text)
    notes = db.Column(db.Text)

    # Team assignments
    salesperson_name = db.Column(db.String(100))
    assigned_team_name = db.Column(db.String(100))
    primary_fitter_name = db.Column(db.String(100))

    assigned_team_id = db.Column(db.Integer, db.ForeignKey('teams.id'))
    primary_fitter_id = db.Column(db.Integer, db.ForeignKey('fitters.id'))
    salesperson_id = db.Column(db.Integer, db.ForeignKey('salespeople.id'))

    # Links
    quote_id = db.Column(db.Integer, db.ForeignKey('quotations.id'))

    # Boolean flags
    has_counting_sheet = db.Column(db.Boolean, default=False)
    has_schedule = db.Column(db.Boolean, default=False)
    has_invoice = db.Column(db.Boolean, default=False)

    # Relationships
    customer = db.relationship('Customer', back_populates='jobs')
    quotation = db.relationship('Quotation', foreign_keys=[quote_id], back_populates='job', uselist=False)
    assigned_team = db.relationship('Team', foreign_keys=[assigned_team_id])
    primary_fitter = db.relationship('Fitter', foreign_keys=[primary_fitter_id])
    salesperson = db.relationship('Salesperson', foreign_keys=[salesperson_id])

    documents = db.relationship('JobDocument', back_populates='job', lazy=True, cascade='all, delete-orphan')
    checklists = db.relationship('JobChecklist', back_populates='job', lazy=True, cascade='all, delete-orphan')
    schedule_items = db.relationship('ScheduleItem', back_populates='job', lazy=True, cascade='all, delete-orphan')
    rooms = db.relationship('Room', back_populates='job', lazy=True, cascade='all, delete-orphan')
    form_links = db.relationship('JobFormLink', back_populates='job', lazy=True, cascade='all, delete-orphan')
    job_notes = db.relationship('JobNote', back_populates='job', lazy=True, cascade='all, delete-orphan')
    invoices = db.relationship('Invoice', back_populates='job', lazy=True, cascade='all, delete-orphan')
    counting_sheets = db.relationship('CountingSheet', back_populates='job', lazy=True, cascade='all, delete-orphan')
    remedials = db.relationship('RemedialAction', back_populates='job', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', back_populates='job', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Job {self.job_reference or self.id}: {self.job_name or self.job_type}>'


# ----------------------------------
# Documents / Checklists / Rooms
# ----------------------------------

class JobDocument(db.Model):
    __tablename__ = 'job_documents'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(36), db.ForeignKey('jobs.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)
    mime_type = db.Column(db.String(100))
    category = db.Column(db.String(50))
    uploaded_by = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    job = db.relationship('Job', back_populates='documents')


class JobChecklist(db.Model):
    __tablename__ = 'job_checklists'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(36), db.ForeignKey('jobs.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    template_type = db.Column(CHECKLIST_TEMPLATE_ENUM, nullable=True)
    template_version = db.Column(db.Integer, default=1)
    status = db.Column(db.String(20), default='Not Started')
    filled_by = db.Column(db.String(200))
    filled_at = db.Column(db.DateTime)
    fields = db.Column(db.JSON)  # JSON key/value for flexible templates
    signed = db.Column(db.Boolean, default=False)
    signature_path = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = db.relationship('Job', back_populates='checklists')
    items = db.relationship('ChecklistItem', back_populates='checklist', lazy=True, cascade='all, delete-orphan')


class ChecklistItem(db.Model):
    __tablename__ = 'checklist_items'

    id = db.Column(db.Integer, primary_key=True)
    checklist_id = db.Column(db.Integer, db.ForeignKey('job_checklists.id'), nullable=False)
    text = db.Column(db.String(500), nullable=False)
    completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime)
    completed_by = db.Column(db.String(200))
    notes = db.Column(db.Text)
    order_index = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    checklist = db.relationship('JobChecklist', back_populates='items')


class ScheduleItem(db.Model):
    __tablename__ = 'schedule_items'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(36), db.ForeignKey('jobs.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime)
    all_day = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='Scheduled')
    assigned_team_id = db.Column(db.Integer, db.ForeignKey('teams.id'))
    assigned_fitter_id = db.Column(db.Integer, db.ForeignKey('fitters.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = db.relationship('Job', back_populates='schedule_items')
    assigned_team = db.relationship('Team')
    assigned_fitter = db.relationship('Fitter')


class Room(db.Model):
    __tablename__ = 'rooms'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(36), db.ForeignKey('jobs.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    room_type = db.Column(db.String(50), nullable=False)
    measurements = db.Column(db.Text)  # could be JSON
    notes = db.Column(db.Text)
    order_index = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    job = db.relationship('Job', back_populates='rooms')
    appliances = db.relationship('RoomAppliance', back_populates='room', lazy=True, cascade='all, delete-orphan')


class RoomAppliance(db.Model):
    __tablename__ = 'room_appliances'

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    appliance_type = db.Column(db.String(100), nullable=False)
    brand = db.Column(db.String(100))
    model = db.Column(db.String(100))
    specifications = db.Column(db.Text)
    installation_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    room = db.relationship('Room', back_populates='appliances')


class JobFormLink(db.Model):
    __tablename__ = 'job_form_links'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(36), db.ForeignKey('jobs.id'), nullable=False)
    form_submission_id = db.Column(db.Integer, db.ForeignKey('form_submissions.id'), nullable=False)
    linked_at = db.Column(db.DateTime, default=datetime.utcnow)
    linked_by = db.Column(db.String(200))

    job = db.relationship('Job', back_populates='form_links')
    form_submission = db.relationship('FormSubmission', back_populates='job_links')


class JobNote(db.Model):
    __tablename__ = 'job_notes'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(36), db.ForeignKey('jobs.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    note_type = db.Column(db.String(50), default='general')
    author = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    job = db.relationship('Job', back_populates='job_notes')


# ----------------------------------
# Quotation / Products Catalogue
# ----------------------------------

class ApplianceCategory(db.Model):
    __tablename__ = 'appliance_categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    products = db.relationship('Product', back_populates='category', lazy=True)

    def __repr__(self):
        return f'<ApplianceCategory {self.name}>'


class Brand(db.Model):
    __tablename__ = 'brands'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    logo_url = db.Column(db.String(255))
    website = db.Column(db.String(255))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    products = db.relationship('Product', back_populates='brand', lazy=True)

    def __repr__(self):
        return f'<Brand {self.name}>'


class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, db.ForeignKey('brands.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('appliance_categories.id'), nullable=False)

    model_code = db.Column(db.String(100), nullable=False, unique=True)
    series = db.Column(db.String(100))
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    base_price = db.Column(db.Numeric(10, 2))
    low_tier_price = db.Column(db.Numeric(10, 2))
    mid_tier_price = db.Column(db.Numeric(10, 2))
    high_tier_price = db.Column(db.Numeric(10, 2))

    dimensions = db.Column(db.Text)  # JSON string (W/H/D)
    weight = db.Column(db.Numeric(8, 2))
    color_options = db.Column(db.Text)  # JSON array

    pack_name = db.Column(db.String(200))
    notes = db.Column(db.Text)
    energy_rating = db.Column(db.String(10))
    warranty_years = db.Column(db.Integer)

    active = db.Column(db.Boolean, default=True)
    in_stock = db.Column(db.Boolean, default=True)
    lead_time_weeks = db.Column(db.Integer)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    brand = db.relationship('Brand', back_populates='products')
    category = db.relationship('ApplianceCategory', back_populates='products')
    quote_items = db.relationship('ProductQuoteItem', back_populates='product', lazy=True)

    def __repr__(self):
        brand_name = self.brand.name if getattr(self, 'brand', None) else 'Unknown'
        return f'<Product {brand_name} {self.model_code}>'

    def get_price_for_tier(self, tier='mid'):
        tier_map = {
            'low': self.low_tier_price or self.base_price,
            'mid': self.mid_tier_price or self.base_price,
            'high': self.high_tier_price or self.base_price,
        }
        return tier_map.get(tier.lower(), self.base_price)

    def get_dimensions_dict(self):
        if self.dimensions:
            try:
                import json
                return json.loads(self.dimensions)
            except Exception:
                return {}
        return {}

    def get_color_options_list(self):
        if self.color_options:
            try:
                import json
                return json.loads(self.color_options)
            except Exception:
                return []
        return []


class Quotation(db.Model):
    __tablename__ = 'quotations'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'), nullable=False)
    reference_number = db.Column(db.String(50), unique=True)
    total = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(20), default='Draft')
    valid_until = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = db.relationship('Customer', back_populates='quotations')
    items = db.relationship('QuotationItem', back_populates='quotation', lazy=True, cascade='all, delete-orphan')
    product_items = db.relationship('ProductQuoteItem', back_populates='quotation', lazy=True, cascade='all, delete-orphan')
    job = db.relationship('Job', back_populates='quotation', uselist=False)


class QuotationItem(db.Model):
    __tablename__ = 'quotation_items'

    id = db.Column(db.Integer, primary_key=True)
    quotation_id = db.Column(db.Integer, db.ForeignKey('quotations.id'), nullable=False)
    item = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    color = db.Column(db.String(50))
    amount = db.Column(db.Float, nullable=False)

    quotation = db.relationship('Quotation', back_populates='items')

    def __repr__(self):
        return f'<QuotationItem {self.item} (Quotation {self.quotation_id})>'


class ProductQuoteItem(db.Model):
    __tablename__ = 'product_quote_items'

    id = db.Column(db.Integer, primary_key=True)
    quotation_id = db.Column(db.Integer, db.ForeignKey('quotations.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)

    quantity = db.Column(db.Integer, default=1)
    quoted_price = db.Column(db.Numeric(10, 2), nullable=False)
    tier_used = db.Column(db.String(10))
    selected_color = db.Column(db.String(50))
    custom_notes = db.Column(db.Text)

    line_total = db.Column(db.Numeric(10, 2))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    quotation = db.relationship('Quotation', back_populates='product_items')
    product = db.relationship('Product', back_populates='quote_items')

    def __repr__(self):
        code = self.product.model_code if getattr(self, 'product', None) else 'Unknown'
        return f'<ProductQuoteItem {code} x{self.quantity}>'

    def calculate_line_total(self):
        self.line_total = (self.quoted_price or 0) * (self.quantity or 0)
        return self.line_total


# ----------------------------------
# Invoicing & Payments
# ----------------------------------

class Invoice(db.Model):
    __tablename__ = 'invoices'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(36), db.ForeignKey('jobs.id'), nullable=False)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    status = db.Column(db.String(20), default='Draft')
    due_date = db.Column(db.Date)
    paid_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = db.relationship('Job', back_populates='invoices')
    line_items = db.relationship('InvoiceLineItem', back_populates='invoice', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', back_populates='invoice', lazy=True)

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
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    vat_rate = db.Column(db.Numeric(5, 2), default=0)  # e.g. 20.00 for 20%

    invoice = db.relationship('Invoice', back_populates='line_items')


class Payment(db.Model):
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(36), db.ForeignKey('jobs.id'), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'))  # optional link to invoice

    date = db.Column(db.Date, default=datetime.utcnow)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    method = db.Column(PAYMENT_METHOD_ENUM, default='BACS')
    reference = db.Column(db.String(120))
    bank_details_used = db.Column(db.String(255))
    notes = db.Column(db.Text)

    cleared = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    job = db.relationship('Job', back_populates='payments')
    invoice = db.relationship('Invoice', back_populates='payments')


# ----------------------------------
# Counting Sheets
# ----------------------------------

class CountingSheet(db.Model):
    __tablename__ = 'counting_sheets'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(36), db.ForeignKey('jobs.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'))  # optional, per-room counting
    template_type = db.Column(db.Enum('KitchenCountingSheet', 'BedCountingSheet', name='counting_template_enum'), nullable=False)
    status = db.Column(db.Enum('Draft', 'Finalised', name='counting_status_enum'), default='Draft')

    created_by = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.String(200))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = db.relationship('Job', back_populates='counting_sheets')
    room = db.relationship('Room')
    items = db.relationship('CountingItem', back_populates='sheet', lazy=True, cascade='all, delete-orphan')


class CountingItem(db.Model):
    __tablename__ = 'counting_items'

    id = db.Column(db.Integer, primary_key=True)
    sheet_id = db.Column(db.Integer, db.ForeignKey('counting_sheets.id'), nullable=False)

    description = db.Column(db.String(255), nullable=False)   # ITEM
    quantity_requested = db.Column(db.Integer, default=0)     # ORDERED
    quantity_ordered = db.Column(db.Integer, default=0)
    quantity_counted = db.Column(db.Integer, default=0)       # COUNTED
    unit = db.Column(db.String(50))
    supplier = db.Column(db.String(120))
    customer_supplied = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)

    sheet = db.relationship('CountingSheet', back_populates='items')


# ----------------------------------
# Remedial Actions
# ----------------------------------

class RemedialAction(db.Model):
    __tablename__ = 'remedial_actions'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(36), db.ForeignKey('jobs.id'), nullable=False)

    date = db.Column(db.Date, default=datetime.utcnow)
    assigned_to = db.Column(db.String(200))  # could be fitter/team/user
    status = db.Column(db.Enum('Submitted', 'Reviewed', 'Actioned', name='remedial_status_enum'), default='Submitted')
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    job = db.relationship('Job', back_populates='remedials')
    items = db.relationship('RemedialItem', back_populates='remedial', lazy=True, cascade='all, delete-orphan')


class RemedialItem(db.Model):
    __tablename__ = 'remedial_items'

    id = db.Column(db.Integer, primary_key=True)
    remedial_id = db.Column(db.Integer, db.ForeignKey('remedial_actions.id'), nullable=False)

    number = db.Column(db.Integer)  # No
    item = db.Column(db.String(120))
    remedial_action = db.Column(db.String(255))
    colour = db.Column(db.String(50))
    size = db.Column(db.String(50))
    quantity = db.Column(db.Integer, default=1)
    status = db.Column(db.String(50), default='Pending')

    remedial = db.relationship('RemedialAction', back_populates='items')


# ----------------------------------
# Templates Library
# ----------------------------------

class DocumentTemplate(db.Model):
    __tablename__ = 'document_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    template_type = db.Column(DOCUMENT_TEMPLATE_TYPE_ENUM, nullable=False)
    file_path = db.Column(db.String(500), nullable=False)  # points to uploaded file
    merge_fields = db.Column(db.JSON)  # list/structure of exposed merge fields
    uploaded_by = db.Column(db.String(200))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


# ----------------------------------
# Audit & Versioning
# ----------------------------------

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(120), nullable=False)
    entity_id = db.Column(db.String(120), nullable=False)
    action = db.Column(AUDIT_ACTION_ENUM, nullable=False)
    changed_by = db.Column(db.String(200))
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)
    change_summary = db.Column(db.JSON)  # JSON diff summary
    previous_snapshot = db.Column(db.JSON)
    new_snapshot = db.Column(db.JSON)


class VersionedSnapshot(db.Model):
    __tablename__ = 'versioned_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(120), nullable=False)
    entity_id = db.Column(db.String(120), nullable=False)
    version_number = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(255))
    snapshot = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.String(200))


# ----------------------------------
# Forms / Submissions / Imports
# ----------------------------------

class FormSubmission(db.Model):
    __tablename__ = 'form_submissions'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'))
    form_data = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(100))
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed = db.Column(db.Boolean, default=False)
    processed_at = db.Column(db.DateTime)

    customer = db.relationship('Customer', back_populates='form_submissions')
    job_links = db.relationship('JobFormLink', back_populates='form_submission', lazy=True, cascade='all, delete-orphan')


class CustomerFormData(db.Model):
    __tablename__ = 'customer_form_data'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'), nullable=False)
    form_data = db.Column(db.Text, nullable=False)
    token_used = db.Column(db.String(64), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    customer = db.relationship('Customer', back_populates='form_data')

    def __repr__(self):
        return f'<CustomerFormData {self.id} for Customer {self.customer_id}>'


class DataImport(db.Model):
    __tablename__ = 'data_imports'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    import_type = db.Column(db.String(50), nullable=False)  # 'appliance_matrix', 'kbb_pricelist'
    status = db.Column(db.String(20), default='processing')  # processing, completed, failed
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

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Basic assignment info
    type = db.Column(ASSIGNMENT_TYPE_ENUM, nullable=False, default='job')
    title = db.Column(db.String(255), nullable=False)
    date = db.Column(db.Date, nullable=False)
    
    # Staff assignment
    staff_id = db.Column(db.Integer, db.ForeignKey('fitters.id'), nullable=False)
    
    # Job-related fields
    job_id = db.Column(db.String(36), db.ForeignKey('jobs.id'))
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'))
    
    # Time fields
    start_time = db.Column(db.Time)
    end_time = db.Column(db.Time)
    estimated_hours = db.Column(db.Float)  # Calculated from start/end time or manually set
    
    # Additional info
    notes = db.Column(db.Text)
    priority = db.Column(db.String(20), default='Medium')
    status = db.Column(db.String(20), default='Scheduled')  # Scheduled, In Progress, Completed, Cancelled
    
    # Audit fields
    created_by = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.String(200))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    staff = db.relationship('Fitter', backref='assignments')
    job = db.relationship('Job', backref='assignments')
    customer = db.relationship('Customer', backref='assignments')
    
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
        return {
            'id': self.id,
            'type': self.type,
            'title': self.title,
            'date': self.date.isoformat() if self.date else None,
            'staff_id': str(self.staff_id),
            'job_id': self.job_id,
            'customer_id': self.customer_id,
            'start_time': self.start_time.strftime('%H:%M') if self.start_time else None,
            'end_time': self.end_time.strftime('%H:%M') if self.end_time else None,
            'estimated_hours': self.estimated_hours,
            'notes': self.notes,
            'priority': self.priority,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            # Include related data
            'staff_name': self.staff.name if self.staff else None,
            'job_reference': self.job.job_reference if self.job else None,
            'customer_name': self.customer.name if self.customer else None,
        }