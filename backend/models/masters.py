"""
Master / Reference Data Models for StreemLyne CRM
Lookup tables consumed across the entire application.

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
    """
    ISO country reference data.
    SCHEMA: StreemLyne_MT.Country_Master
    """
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
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================
# CURRENCY MASTER
# ============================================================

class CurrencyMaster(db.Model):
    """
    ISO currency reference data.
    SCHEMA: StreemLyne_MT.Currency_Master
    """
    __tablename__ = 'Currency_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    currency_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    currency_name = db.Column(db.String(100))
    currency_code = db.Column(db.String(10))
    created_at = db.Column(db.DateTime(timezone=False))                  # Nullable, no DB default in schema

    def __repr__(self):
        return f'<CurrencyMaster {self.currency_code}>'

    def format_amount(self, amount):
        return f'{self.currency_code} {amount:,.2f}'

    def to_dict(self):
        return {
            'currency_id': self.currency_id,
            'currency_name': self.currency_name,
            'currency_code': self.currency_code,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================
# DESIGNATION MASTER
# ============================================================

class DesignationMaster(db.Model):
    """
    Employee job-title/designation catalogue.
    SCHEMA: StreemLyne_MT.Designation_Master
    """
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
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================
# SERVICES MASTER
# ============================================================

class ServicesMaster(db.Model):
    """
    Tenant-scoped product / service catalogue.

    supplier_id is stored as a plain integer (no FK constraint in schema).
    date_from / date_to define the effective window; use is_active() to check.

    SCHEMA: StreemLyne_MT.Services_Master
    """
    __tablename__ = 'Services_Master'
    __table_args__ = (
        db.Index('idx_service_tenant_dates', 'tenant_id', 'date_from', 'date_to'),
        db.Index('idx_service_code_tenant', 'service_code', 'tenant_id'),
        {'schema': 'StreemLyne_MT'},
    )

    service_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'),
        nullable=False,
        index=True,
    )
    service_code = db.Column(db.String(50), nullable=False)
    service_title = db.Column(db.String(255), nullable=False)
    service_description = db.Column(db.String)
    service_rate = db.Column(db.Float(precision=24))
    currency_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'))

    # supplier_id: no FK constraint in schema — stored as plain reference
    supplier_id = db.Column(db.SmallInteger)

    date_from = db.Column(db.Date)
    date_to = db.Column(db.Date)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    tenant = db.relationship('TenantMaster', back_populates='services')
    currency = db.relationship('CurrencyMaster', backref='services')

    def __repr__(self):
        return f'<ServicesMaster {self.service_code}: {self.service_title}>'

    def is_active(self, check_date=None):
        """Return True if the service is within its effective date window."""
        if check_date is None:
            check_date = datetime.utcnow().date()
        if self.date_from and check_date < self.date_from:
            return False
        if self.date_to and check_date > self.date_to:
            return False
        return True

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
            'supplier_id': self.supplier_id,
            'date_from': self.date_from.isoformat() if self.date_from else None,
            'date_to': self.date_to.isoformat() if self.date_to else None,
            'is_active': self.is_active(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================
# UOM MASTER
# ============================================================

class UOMMaster(db.Model):
    """
    Unit-of-measure catalogue (kg, kWh, hours, etc.).
    SCHEMA: StreemLyne_MT.UOM_Master
    """
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
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================
# STAGE MASTER
# ============================================================

class StageMaster(db.Model):
    """
    Workflow stage catalogue for opportunity / project pipelines.

    stage_type values:  1 = Opportunity  |  2 = Project  |  3 = General

    SCHEMA: StreemLyne_MT.Stage_Master
    """
    __tablename__ = 'Stage_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    stage_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    stage_name = db.Column(db.String(100), nullable=False, unique=True)
    stage_description = db.Column(db.String)
    preceding_stage_id = db.Column(db.SmallInteger)   # Self-reference; no FK constraint in schema
    stage_type = db.Column(db.SmallInteger, nullable=False)  # 1=Opportunity, 2=Project, 3=General

    # Relationships
    opportunities = db.relationship('OpportunityDetails', back_populates='stage')

    def __repr__(self):
        return f'<StageMaster {self.stage_name}>'

    def get_stage_type_name(self):
        return {1: 'Opportunity', 2: 'Project', 3: 'General'}.get(self.stage_type, 'Unknown')

    def to_dict(self):
        return {
            'stage_id': self.stage_id,
            'stage_name': self.stage_name,
            'stage_description': self.stage_description,
            'preceding_stage_id': self.preceding_stage_id,
            'stage_type': self.stage_type,
            'stage_type_name': self.get_stage_type_name(),
        }


# ============================================================
# SUPPLIER MASTER
# ============================================================

class SupplierMaster(db.Model):
    """
    External supplier / vendor catalogue.

    supplier_provisions values:
        1 = Energy Supplier  |  2 = Equipment Supplier
        3 = Service Provider |  4 = Other

    SCHEMA: StreemLyne_MT.Supplier_Master
    """
    __tablename__ = 'Supplier_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    supplier_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    supplier_company_name = db.Column(db.String(255), nullable=False)
    supplier_contact_name = db.Column(db.String(255))
    supplier_provisions = db.Column(db.SmallInteger)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<SupplierMaster {self.supplier_company_name}>'

    def get_provisions_name(self):
        return {
            1: 'Energy Supplier',
            2: 'Equipment Supplier',
            3: 'Service Provider',
            4: 'Other',
        }.get(self.supplier_provisions, 'Unknown')

    def to_dict(self):
        return {
            'supplier_id': self.supplier_id,
            'supplier_company_name': self.supplier_company_name,
            'supplier_contact_name': self.supplier_contact_name,
            'supplier_provisions': self.supplier_provisions,
            'supplier_provisions_name': self.get_provisions_name(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================
# ROLE MASTER
# ============================================================

class RoleMaster(db.Model):
    """
    RBAC role catalogue.

    is_system=True roles are built-in and cannot be deleted.

    NOTE: Use RolePermissionMapping to query permissions for a role,
    rather than the .permissions convenience relationship, when you
    need the created_at / edited_at audit columns.

    SCHEMA: StreemLyne_MT.Role_Master
    """
    __tablename__ = 'Role_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    role_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    role_name = db.Column(db.String(100), nullable=False, unique=True)
    role_description = db.Column(db.String)                              # character varying in schema
    is_system = db.Column(db.Boolean, nullable=False)                   # NOT NULL, no DB default
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    # Explicit through-model relationships (preferred — gives access to audit cols)
    role_permission_mappings = db.relationship(
        'RolePermissionMapping',
        back_populates='role',
        lazy='dynamic',
        cascade='all, delete-orphan',
    )

    def __repr__(self):
        return f'<RoleMaster {self.role_name}>'

    def get_permission_codes(self) -> list:
        """Return list of permission_code strings assigned to this role."""
        return [
            rpm.permission.permission_code
            for rpm in self.role_permission_mappings
            if rpm.permission
        ]

    def to_dict(self):
        return {
            'role_id': self.role_id,
            'role_name': self.role_name,
            'role_description': self.role_description,
            'is_system': self.is_system,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================
# PERMISSION CATALOG
# ============================================================

class PermissionCatalog(db.Model):
    """
    System-wide permission catalogue.
    Permission codes follow the pattern: RESOURCE_ACTION  (e.g. CLIENT_VIEW).

    SCHEMA: StreemLyne_MT.Permission_Catalog
    """
    __tablename__ = 'Permission_Catalog'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    permission_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    permission_code = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String)                                   # character varying in schema
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    # Back-reference from RolePermissionMapping
    permission_role_mappings = db.relationship(
        'RolePermissionMapping',
        back_populates='permission',
        lazy='dynamic',
    )

    def __repr__(self):
        return f'<PermissionCatalog {self.permission_code}>'

    def to_dict(self):
        return {
            'permission_id': self.permission_id,
            'permission_code': self.permission_code,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================
# ROLE PERMISSION MAPPING
# ============================================================

class RolePermissionMapping(db.Model):
    """
    Joins roles to their granted permissions.
    Includes audit timestamps (created_at, edited_at).

    SCHEMA: StreemLyne_MT.Role_Permission_Mapping
    """
    __tablename__ = 'Role_Permission_Mapping'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    role_permission_mapping_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    role_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Role_Master.role_id'),
        nullable=False,
    )
    permission_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Permission_Catalog.permission_id'),
        nullable=False,
    )
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    edited_at = db.Column(db.Date)

    role = db.relationship('RoleMaster', back_populates='role_permission_mappings')
    permission = db.relationship('PermissionCatalog', back_populates='permission_role_mappings')

    def __repr__(self):
        return f'<RolePermissionMapping Role:{self.role_id} Perm:{self.permission_id}>'

    def to_dict(self):
        return {
            'role_permission_mapping_id': self.role_permission_mapping_id,
            'role_id': self.role_id,
            'role_name': self.role.role_name if self.role else None,
            'permission_id': self.permission_id,
            'permission_code': self.permission.permission_code if self.permission else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'edited_at': self.edited_at.isoformat() if self.edited_at else None,
        }