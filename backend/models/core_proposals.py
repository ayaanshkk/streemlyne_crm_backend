# C:\streemlyne_crm_backend\backend\models\core_proposals.py
"""
Proposal and Invoice Models for StreemLyne CRM
Handles proposals, invoices, and their line items

SCHEMA: StreemLyne_MT
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db


# ============================================================
# PROPOSAL MASTER
# ============================================================

class ProposalMaster(db.Model):
    """SCHEMA: StreemLyne_MT.Proposal_Master"""
    __tablename__ = 'Proposal_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    proposal_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))
    project_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Project_Details.project_id'))
    currency_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'))
    sub_total = db.Column(db.Float(precision=24))
    total_amount = db.Column(db.Float(precision=24), nullable=False)
    discount_percent = db.Column(db.Float(precision=24))
    discount_amount = db.Column(db.Float(precision=24))
    tax_id = db.Column(db.SmallInteger, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    client = db.relationship('ClientMaster', back_populates='proposals')
    project = db.relationship('ProjectDetails', backref='proposals')
    currency = db.relationship('CurrencyMaster', backref='proposals')
    proposal_details = db.relationship(
        'ProposalDetails',
        back_populates='proposal',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    invoices = db.relationship('InvoiceMaster', back_populates='proposal', lazy='dynamic')

    def __repr__(self):
        return f'<ProposalMaster {self.proposal_id}>'

    def to_dict(self):
        return {
            'proposal_id': self.proposal_id,
            'client_id': self.client_id,
            'client_name': self.client.client_company_name if self.client else None,
            'project_id': self.project_id,
            'project_title': self.project.project_title if self.project else None,
            'currency_id': self.currency_id,
            'currency_code': self.currency.currency_code if self.currency else None,
            'sub_total': self.sub_total,
            'total_amount': self.total_amount,
            'discount_percent': self.discount_percent,
            'discount_amount': self.discount_amount,
            'tax_id': self.tax_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def calculate_totals(self):
        details = self.proposal_details.all()
        self.sub_total = sum(d.quantity * d.service.service_rate for d in details if d.service)
        if self.discount_percent:
            self.discount_amount = self.sub_total * (self.discount_percent / 100)
        elif not self.discount_amount:
            self.discount_amount = 0
        self.total_amount = self.sub_total - (self.discount_amount or 0)
        return self.total_amount


# ============================================================
# PROPOSAL DETAILS (Line Items)
# ============================================================

class ProposalDetails(db.Model):
    """SCHEMA: StreemLyne_MT.Proposal_Details"""
    __tablename__ = 'Proposal_Details'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    proposal_details_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    proposal_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Proposal_Master.proposal_id'), nullable=False)
    service_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Services_Master.service_id'), nullable=False)
    uom_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.UOM_Master.uom_id'), nullable=False)
    quantity = db.Column(db.Float(precision=24), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    proposal = db.relationship('ProposalMaster', back_populates='proposal_details')
    service = db.relationship('ServicesMaster', backref='proposal_details')
    uom = db.relationship('UOMMaster', backref='proposal_details')

    def __repr__(self):
        return f'<ProposalDetails {self.proposal_details_id} for Proposal {self.proposal_id}>'

    def to_dict(self):
        return {
            'proposal_details_id': self.proposal_details_id,
            'proposal_id': self.proposal_id,
            'service_id': self.service_id,
            'service_title': self.service.service_title if self.service else None,
            'service_code': self.service.service_code if self.service else None,
            'service_rate': self.service.service_rate if self.service else None,
            'uom_id': self.uom_id,
            'uom_description': self.uom.uom_description if self.uom else None,
            'quantity': self.quantity,
            'line_total': self.calculate_line_total(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def calculate_line_total(self):
        if self.service and self.service.service_rate:
            return self.quantity * self.service.service_rate
        return 0


# ============================================================
# INVOICE MASTER
# ============================================================

class InvoiceMaster(db.Model):
    """SCHEMA: StreemLyne_MT.Invoice_Master"""
    __tablename__ = 'Invoice_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    invoice_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))
    project_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Project_Details.project_id'))
    proposal_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Proposal_Master.proposal_id'))
    currency_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'))
    invoice_number = db.Column(db.String(50), nullable=False)
    billing_remarks = db.Column(db.String(500))
    sub_total = db.Column(db.Float(precision=24))
    total_amount = db.Column(db.Float(precision=24), nullable=False)
    discount_percent = db.Column(db.Float(precision=24))
    discount_amount = db.Column(db.Float(precision=24))
    tax_id = db.Column(db.SmallInteger, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    client = db.relationship('ClientMaster', back_populates='invoices')
    project = db.relationship('ProjectDetails', back_populates='invoices')
    proposal = db.relationship('ProposalMaster', back_populates='invoices')
    currency = db.relationship('CurrencyMaster', backref='invoices')
    invoice_details = db.relationship(
        'InvoiceDetails',
        back_populates='invoice',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f'<InvoiceMaster {self.invoice_id}: {self.invoice_number}>'

    def to_dict(self):
        return {
            'invoice_id': self.invoice_id,
            'client_id': self.client_id,
            'client_name': self.client.client_company_name if self.client else None,
            'project_id': self.project_id,
            'project_title': self.project.project_title if self.project else None,
            'proposal_id': self.proposal_id,
            'currency_id': self.currency_id,
            'currency_code': self.currency.currency_code if self.currency else None,
            'invoice_number': self.invoice_number,
            'billing_remarks': self.billing_remarks,
            'sub_total': self.sub_total,
            'total_amount': self.total_amount,
            'discount_percent': self.discount_percent,
            'discount_amount': self.discount_amount,
            'tax_id': self.tax_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def calculate_totals(self):
        details = self.invoice_details.all()
        self.sub_total = sum(d.quantity * d.service.service_rate for d in details if d.service)
        if self.discount_percent:
            self.discount_amount = self.sub_total * (self.discount_percent / 100)
        elif not self.discount_amount:
            self.discount_amount = 0
        self.total_amount = self.sub_total - (self.discount_amount or 0)
        return self.total_amount


# ============================================================
# INVOICE DETAILS (Line Items)
# ============================================================

class InvoiceDetails(db.Model):
    """SCHEMA: StreemLyne_MT.Invoice_Details"""
    __tablename__ = 'Invoice_Details'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    invoice_details_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    invoice_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Invoice_Master.invoice_id'), nullable=False)
    service_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Services_Master.service_id'), nullable=False)
    uom_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.UOM_Master.uom_id'), nullable=False)
    quantity = db.Column(db.Float(precision=24), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    invoice = db.relationship('InvoiceMaster', back_populates='invoice_details')
    service = db.relationship('ServicesMaster', backref='invoice_details')
    uom = db.relationship('UOMMaster', backref='invoice_details')

    def __repr__(self):
        return f'<InvoiceDetails {self.invoice_details_id} for Invoice {self.invoice_id}>'

    def to_dict(self):
        return {
            'invoice_details_id': self.invoice_details_id,
            'invoice_id': self.invoice_id,
            'service_id': self.service_id,
            'service_title': self.service.service_title if self.service else None,
            'service_code': self.service.service_code if self.service else None,
            'service_rate': self.service.service_rate if self.service else None,
            'uom_id': self.uom_id,
            'uom_description': self.uom.uom_description if self.uom else None,
            'quantity': self.quantity,
            'line_total': self.calculate_line_total(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def calculate_line_total(self):
        if self.service and self.service.service_rate:
            return self.quantity * self.service.service_rate
        return 0