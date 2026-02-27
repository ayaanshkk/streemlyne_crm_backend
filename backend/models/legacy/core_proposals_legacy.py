# C:\streemlyne_crm_backend\backend\models\legacy\core_proposals_legacy.py
"""
Legacy Proposal and Invoice Models — Default Schema (No StreemLyne_MT prefix)

IMPORTANT: These are LEGACY models kept for backward compatibility with
existing routes that have not yet been migrated to the new schema.

DO NOT use these for new development.

New equivalents:
  Proposal      → ProposalMaster   (StreemLyne_MT.Proposal_Master)
  ProposalItem  → ProposalDetails  (StreemLyne_MT.Proposal_Details)
  Invoice       → InvoiceMaster    (StreemLyne_MT.Invoice_Master)
  InvoiceLineItem → InvoiceDetails (StreemLyne_MT.Invoice_Details)
  Product/ProductCategory → ServicesMaster (StreemLyne_MT.Services_Master)
  Payment       → No direct equivalent yet (app-level concern)
"""

import sys
import os
from datetime import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from database import db


# ============================================================
# PRODUCT CATALOG (LEGACY)
# ============================================================

class ProductCategory(db.Model):
    """Legacy product categories. New equivalent: ServicesMaster (tenant-scoped)."""
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
    """Legacy product catalog. New equivalent: ServicesMaster."""
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('product_categories.id'), nullable=False)
    sku = db.Column(db.String(100), nullable=False, unique=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    base_price = db.Column(db.Numeric(10, 2))
    discount_price = db.Column(db.Numeric(10, 2))
    active = db.Column(db.Boolean, default=True)
    in_stock = db.Column(db.Boolean, default=True)
    stock_quantity = db.Column(db.Integer)
    specifications = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = db.relationship('ProductCategory', back_populates='products')
    proposal_items = db.relationship('ProposalItem', back_populates='product', lazy=True)
    tenant = db.relationship('Tenant')

    def __repr__(self):
        return f'<Product {self.sku}: {self.name}>'


# ============================================================
# PROPOSALS (LEGACY)
# ============================================================

class Proposal(db.Model):
    """Legacy proposal model. New equivalent: ProposalMaster."""
    __tablename__ = 'proposals'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=True, index=True)
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'), nullable=False)
    reference_number = db.Column(db.String(50), unique=True)
    title = db.Column(db.String(255))
    total = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(20), default='Draft')
    valid_until = db.Column(db.Date)
    notes = db.Column(db.Text)
    custom_data = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = db.relationship('Customer', back_populates='proposals')
    items = db.relationship('ProposalItem', back_populates='proposal', lazy=True, cascade='all, delete-orphan')
    opportunity = db.relationship('Opportunity', back_populates='proposal', uselist=False)

    def __repr__(self):
        return f'<Proposal {self.reference_number}>'


class ProposalItem(db.Model):
    """Legacy proposal line items. New equivalent: ProposalDetails."""
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

    def __repr__(self):
        return f'<ProposalItem {self.description}>'


# ============================================================
# INVOICES (LEGACY)
# ============================================================

class Invoice(db.Model):
    """Legacy invoice model. New equivalent: InvoiceMaster."""
    __tablename__ = 'invoices'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    opportunity_id = db.Column(db.String(36), db.ForeignKey('opportunities.id'), nullable=False)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    status = db.Column(db.String(20), default='Draft')
    due_date = db.Column(db.Date)
    paid_date = db.Column(db.Date)
    custom_data = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    opportunity = db.relationship('Opportunity', back_populates='invoices')
    line_items = db.relationship('InvoiceLineItem', back_populates='invoice', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', back_populates='invoice', lazy=True)
    tenant = db.relationship('Tenant')

    @property
    def amount_due(self):
        return sum([(li.quantity or 0) * (li.unit_price or 0) for li in self.line_items])

    @property
    def amount_paid(self):
        return sum([p.amount or 0 for p in self.payments if p.cleared])

    @property
    def balance(self):
        return (self.amount_due or 0) - (self.amount_paid or 0)

    def __repr__(self):
        return f'<Invoice {self.invoice_number}>'


class InvoiceLineItem(db.Model):
    """Legacy invoice line items. New equivalent: InvoiceDetails."""
    __tablename__ = 'invoice_line_items'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=True, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    tax_rate = db.Column(db.Numeric(5, 2), default=0)

    invoice = db.relationship('Invoice', back_populates='line_items')

    def __repr__(self):
        return f'<InvoiceLineItem {self.description}>'


# ============================================================
# PAYMENTS (LEGACY)
# ============================================================

class Payment(db.Model):
    """Legacy payment records. No direct new-schema equivalent yet."""
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=True, index=True)
    opportunity_id = db.Column(db.String(36), db.ForeignKey('opportunities.id'), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'))
    date = db.Column(db.Date, default=datetime.utcnow)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    method = db.Column(db.String(50), default='Bank Transfer')
    reference = db.Column(db.String(120))
    notes = db.Column(db.Text)
    cleared = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    opportunity = db.relationship('Opportunity', back_populates='payments')
    invoice = db.relationship('Invoice', back_populates='payments')
    tenant = db.relationship('Tenant')

    def __repr__(self):
        return f'<Payment {self.amount} on {self.date}>'