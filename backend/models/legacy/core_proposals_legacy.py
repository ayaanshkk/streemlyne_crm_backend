# C:\streemlyne_crm_backend\backend\models\core_proposals.py
import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db


# ============================================================
# PRODUCT CATALOG
# ============================================================

class ProductCategory(db.Model):
    """Product/Service categories"""
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
    """Product/Service catalog"""
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

    # Additional Info
    specifications = db.Column(db.Text)  # JSON string
    notes = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    category = db.relationship('ProductCategory', back_populates='products')
    proposal_items = db.relationship('ProposalItem', back_populates='product', lazy=True)
    tenant = db.relationship('Tenant')

    def __repr__(self):
        return f'<Product {self.sku}: {self.name}>'


# ============================================================
# PROPOSALS
# ============================================================

class Proposal(db.Model):
    """Proposals/Quotations"""
    __tablename__ = 'proposals'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=True, index=True)
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'), nullable=False)
    
    # Basic Info
    reference_number = db.Column(db.String(50), unique=True)
    title = db.Column(db.String(255))
    total = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(20), default='Draft')  # Draft, Sent, Accepted, Rejected
    valid_until = db.Column(db.Date)
    notes = db.Column(db.Text)
    
    # 🎯 NEW: Industry-Specific Data
    custom_data = db.Column(db.JSON, default=dict)
    # Examples:
    # Education: {"ifo_number": "IFO-123", "mode_of_enquiry": "Email", "igst_percentage": 18.0}
    # Interior: {"room_breakdown": {...}, "appliance_list": [...]}
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    customer = db.relationship('Customer', back_populates='proposals')
    items = db.relationship('ProposalItem', back_populates='proposal', lazy=True, cascade='all, delete-orphan')
    opportunity = db.relationship('Opportunity', back_populates='proposal', uselist=False)

    def __repr__(self):
        return f'<Proposal {self.reference_number}>'


class ProposalItem(db.Model):
    """Line items in proposals"""
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

    # Relationships
    proposal = db.relationship('Proposal', back_populates='items')
    product = db.relationship('Product', back_populates='proposal_items')
    tenant = db.relationship('Tenant')

    def calculate_line_total(self):
        """Calculate line total from quantity and unit price"""
        self.line_total = (self.unit_price or 0) * (self.quantity or 0)
        return self.line_total

    def __repr__(self):
        return f'<ProposalItem {self.description}>'


# ============================================================
# INVOICES
# ============================================================

class Invoice(db.Model):
    """Invoices"""
    __tablename__ = 'invoices'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    opportunity_id = db.Column(db.String(36), db.ForeignKey('opportunities.id'), nullable=False)
    
    # Basic Info
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    status = db.Column(db.String(20), default='Draft')  # Draft, Sent, Paid, Overdue, Cancelled
    due_date = db.Column(db.Date)
    paid_date = db.Column(db.Date)
    
    # 🎯 NEW: Industry-Specific Data
    custom_data = db.Column(db.JSON, default=dict)
    # Examples:
    # Education: {"gst_number": "GST123", "bank_details": {...}}
    # Interior: {"deposit_schedule": [...]}
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    opportunity = db.relationship('Opportunity', back_populates='invoices')
    line_items = db.relationship('InvoiceLineItem', back_populates='invoice', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', back_populates='invoice', lazy=True)
    tenant = db.relationship('Tenant')

    @property
    def amount_due(self):
        """Calculate total amount due"""
        total = sum([(li.quantity or 0) * (li.unit_price or 0) for li in self.line_items])
        return total

    @property
    def amount_paid(self):
        """Calculate total amount paid"""
        return sum([p.amount or 0 for p in self.payments if p.cleared])

    @property
    def balance(self):
        """Calculate remaining balance"""
        return (self.amount_due or 0) - (self.amount_paid or 0)

    def __repr__(self):
        return f'<Invoice {self.invoice_number}>'


class InvoiceLineItem(db.Model):
    """Line items in invoices"""
    __tablename__ = 'invoice_line_items'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=True, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    
    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    tax_rate = db.Column(db.Numeric(5, 2), default=0)  # e.g., 20.00 for 20% VAT

    # Relationships
    invoice = db.relationship('Invoice', back_populates='line_items')

    def __repr__(self):
        return f'<InvoiceLineItem {self.description}>'


# ============================================================
# PAYMENTS
# ============================================================

class Payment(db.Model):
    """Payment records"""
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=True, index=True)
    opportunity_id = db.Column(db.String(36), db.ForeignKey('opportunities.id'), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'))

    # Payment Details
    date = db.Column(db.Date, default=datetime.utcnow)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    method = db.Column(db.String(50), default='Bank Transfer')  # Bank Transfer, Cash, Card, Check, Other
    reference = db.Column(db.String(120))
    notes = db.Column(db.Text)

    # Status
    cleared = db.Column(db.Boolean, default=True)
    
    # Timestamp
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    opportunity = db.relationship('Opportunity', back_populates='payments')
    invoice = db.relationship('Invoice', back_populates='payments')
    tenant = db.relationship('Tenant')

    def __repr__(self):
        return f'<Payment {self.amount} on {self.date}>'