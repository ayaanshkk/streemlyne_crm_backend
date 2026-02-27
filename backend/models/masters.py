# C:\streemlyne_crm_backend\backend\models\masters.py
"""
Master Data Models for StreemLyne CRM
Reference/lookup tables for system-wide data

SCHEMA: StreemLyne_MT
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db


__all__ = [
    'CountryMaster',
    'CurrencyMaster',
    'DesignationMaster',
    'ServicesMaster',
    'UOMMaster',
    'StageMaster',
    'SupplierMaster',
    'RoleMaster',
    'PermissionCatalog',
    'RolePermissionMapping',
]


# ============================================================
# COUNTRY MASTER
# ============================================================

class CountryMaster(db.Model):
    """SCHEMA: StreemLyne_MT.Country_Master"""
    __tablename__ = 'Country_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    country_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    country_name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    country_isd_code = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<CountryMaster {self.country_name}>'

    def to_dict(self):
        return {
            'country_id': self.country_id,
            'country_name': self.country_name,
            'country_isd_code': self.country_isd_code,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ============================================================
# CURRENCY MASTER
# ============================================================

class CurrencyMaster(db.Model):
    """SCHEMA: StreemLyne_MT.Currency_Master"""
    __tablename__ = 'Currency_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    currency_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    currency_name = db.Column(db.String(100))
    currency_code = db.Column(db.String(10))
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    def __repr__(self):
        return f'<CurrencyMaster {self.currency_code}>'

    def to_dict(self):
        return {
            'currency_id': self.currency_id,
            'currency_name': self.currency_name,
            'currency_code': self.currency_code,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def format_amount(self, amount):
        return f"{self.currency_code} {amount:,.2f}"


# ============================================================
# DESIGNATION MASTER
# ============================================================

class DesignationMaster(db.Model):
    """SCHEMA: StreemLyne_MT.Designation_Master"""
    __tablename__ = 'Designation_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    designation_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    designation_description = db.Column(db.String(100), nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<DesignationMaster {self.designation_description}>'

    def to_dict(self):
        return {
            'designation_id': self.designation_id,
            'designation_description': self.designation_description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ============================================================
# SERVICES MASTER
# ============================================================

class ServicesMaster(db.Model):
    """
    Services/Products catalog (tenant-scoped)
    SCHEMA: StreemLyne_MT.Services_Master
    """
    __tablename__ = 'Services_Master'
    __table_args__ = (
        db.Index('idx_service_tenant_active', 'tenant_id', 'date_from', 'date_to'),
        db.Index('idx_service_code_tenant', 'service_code', 'tenant_id'),
        {'schema': 'StreemLyne_MT'}
    )

    service_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'),
                          nullable=False, index=True)
    service_title = db.Column(db.String(255), nullable=False)
    service_description = db.Column(db.Text)
    service_rate = db.Column(db.Float(precision=24))
    currency_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'))
    supplier_id = db.Column(db.SmallInteger)
    date_from = db.Column(db.Date)
    date_to = db.Column(db.Date)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    service_code = db.Column(db.String(50), nullable=False)

    tenant = db.relationship('TenantMaster', back_populates='services')
    currency = db.relationship('CurrencyMaster', backref='services')

    def __repr__(self):
        return f'<ServicesMaster {self.service_code}: {self.service_title}>'

    def to_dict(self):
        return {
            'service_id': self.service_id,
            'tenant_id': self.tenant_id,
            'service_code': self.service_code,
            'service_title': self.service_title,
            'service_description': self.service_description,
            'service_rate': self.service_rate,
            'currency_id': self.currency_id,
            'currency_code': self.currency.currency_code if self.currency else None,
            'date_from': self.date_from.isoformat() if self.date_from else None,
            'date_to': self.date_to.isoformat() if self.date_to else None,
            'is_active': self.is_active(),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def is_active(self, check_date=None):
        if check_date is None:
            check_date = datetime.now().date()
        if self.date_from and check_date < self.date_from:
            return False
        if self.date_to and check_date > self.date_to:
            return False
        return True


# ============================================================
# UOM MASTER
# ============================================================

class UOMMaster(db.Model):
    """SCHEMA: StreemLyne_MT.UOM_Master"""
    __tablename__ = 'UOM_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    uom_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    uom_description = db.Column(db.String(50), nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<UOMMaster {self.uom_description}>'

    def to_dict(self):
        return {
            'uom_id': self.uom_id,
            'uom_description': self.uom_description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ============================================================
# STAGE MASTER
# ============================================================

class StageMaster(db.Model):
    """
    Workflow stages for opportunities/projects
    SCHEMA: StreemLyne_MT.Stage_Master
    """
    __tablename__ = 'Stage_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    stage_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    stage_name = db.Column(db.String(100), nullable=False, unique=True)
    stage_description = db.Column(db.Text)
    preceding_stage_id = db.Column(db.SmallInteger)
    stage_type = db.Column(db.SmallInteger, nullable=False)  # 1=Opportunity, 2=Project, 3=General

    opportunities = db.relationship('OpportunityDetails', back_populates='stage')

    def __repr__(self):
        return f'<StageMaster {self.stage_name}>'

    def to_dict(self):
        return {
            'stage_id': self.stage_id,
            'stage_name': self.stage_name,
            'stage_description': self.stage_description,
            'preceding_stage_id': self.preceding_stage_id,
            'stage_type': self.stage_type,
            'stage_type_name': self.get_stage_type_name()
        }

    def get_stage_type_name(self):
        return {1: 'Opportunity', 2: 'Project', 3: 'General'}.get(self.stage_type, 'Unknown')


# ============================================================
# SUPPLIER MASTER
# ============================================================

class SupplierMaster(db.Model):
    """SCHEMA: StreemLyne_MT.Supplier_Master"""
    __tablename__ = 'Supplier_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    supplier_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    supplier_company_name = db.Column(db.String(255), nullable=False)
    supplier_contact_name = db.Column(db.String(255))
    supplier_provisions = db.Column(db.SmallInteger)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<SupplierMaster {self.supplier_company_name}>'

    def to_dict(self):
        return {
            'supplier_id': self.supplier_id,
            'supplier_company_name': self.supplier_company_name,
            'supplier_contact_name': self.supplier_contact_name,
            'supplier_provisions': self.supplier_provisions,
            'supplier_provisions_name': self.get_provisions_name(),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def get_provisions_name(self):
        return {
            1: 'Energy Supplier',
            2: 'Equipment Supplier',
            3: 'Service Provider',
            4: 'Other'
        }.get(self.supplier_provisions, 'Unknown')


# ============================================================
# ROLE MASTER
# ============================================================

class RoleMaster(db.Model):
    """SCHEMA: StreemLyne_MT.Role_Master"""
    __tablename__ = 'Role_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    role_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    role_name = db.Column(db.String(100), nullable=False, unique=True)
    role_description = db.Column(db.Text)
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    permissions = db.relationship(
        'PermissionCatalog',
        secondary='StreemLyne_MT.Role_Permission_Mapping',
        backref='roles'
    )

    def __repr__(self):
        return f'<RoleMaster {self.role_name}>'

    def to_dict(self):
        return {
            'role_id': self.role_id,
            'role_name': self.role_name,
            'role_description': self.role_description,
            'is_system': self.is_system,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ============================================================
# PERMISSION CATALOG
# ============================================================

class PermissionCatalog(db.Model):
    """SCHEMA: StreemLyne_MT.Permission_Catalog"""
    __tablename__ = 'Permission_Catalog'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    permission_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    permission_code = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    def __repr__(self):
        return f'<PermissionCatalog {self.permission_code}>'

    def to_dict(self):
        return {
            'permission_id': self.permission_id,
            'permission_code': self.permission_code,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ============================================================
# ROLE PERMISSION MAPPING
# ============================================================

class RolePermissionMapping(db.Model):
    """SCHEMA: StreemLyne_MT.Role_Permission_Mapping"""
    __tablename__ = 'Role_Permission_Mapping'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    role_permission_mapping_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    role_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Role_Master.role_id'), nullable=False)
    permission_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Permission_Catalog.permission_id'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    edited_at = db.Column(db.Date)

    role = db.relationship('RoleMaster', backref='role_permissions')
    permission = db.relationship('PermissionCatalog', backref='role_permissions')

    def __repr__(self):
        return f'<RolePermissionMapping Role:{self.role_id} Perm:{self.permission_id}>'

    def to_dict(self):
        return {
            'role_permission_mapping_id': self.role_permission_mapping_id,
            'role_id': self.role_id,
            'permission_id': self.permission_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'edited_at': self.edited_at.isoformat() if self.edited_at else None
        }