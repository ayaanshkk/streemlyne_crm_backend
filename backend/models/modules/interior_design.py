# C:\streemlyne_crm_backend\backend\models\modules\interior_design.py
"""
Interior Design Module Models for StreemLyne CRM
Handles projects, checklists, material orders, appliances, and drawings

SCHEMA: StreemLyne_MT
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database import db


# ============================================================
# PROJECTS
# ============================================================

class Project(db.Model):
    """
    Multiple projects per client (Kitchen, Bedroom, Wardrobe, etc.)

    SCHEMA: StreemLyne_MT.interior_projects
    """
    __tablename__ = 'interior_projects'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=False)

    project_name = db.Column(db.String(255))
    project_type = db.Column(db.String(100))
    stage = db.Column(db.String(50))
    date_of_measure = db.Column(db.Date)
    date_of_installation = db.Column(db.Date)
    completion_date = db.Column(db.Date)
    salesperson = db.Column(db.String(200))
    assigned_team = db.Column(db.String(200))
    primary_fitter = db.Column(db.String(200))
    project_data = db.Column(db.JSON)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='interior_projects')
    client = db.relationship('ClientMaster', backref='interior_projects')

    def __repr__(self):
        return f'<Project {self.project_name} - {self.project_type}>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'client_id': self.client_id,
            'client_name': self.client.client_company_name if self.client else None,
            'project_name': self.project_name,
            'project_type': self.project_type,
            'stage': self.stage,
            'date_of_measure': self.date_of_measure.isoformat() if self.date_of_measure else None,
            'date_of_installation': self.date_of_installation.isoformat() if self.date_of_installation else None,
            'completion_date': self.completion_date.isoformat() if self.completion_date else None,
            'salesperson': self.salesperson,
            'assigned_team': self.assigned_team,
            'primary_fitter': self.primary_fitter,
            'project_data': self.project_data,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================
# KITCHEN CHECKLISTS
# ============================================================

class KitchenChecklist(db.Model):
    """SCHEMA: StreemLyne_MT.interior_kitchen_checklists"""
    __tablename__ = 'interior_kitchen_checklists'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    project_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.interior_projects.id'))
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))

    appliances = db.Column(db.JSON)
    worktop_features = db.Column(db.Text)
    worktop_size = db.Column(db.String(100))
    under_lighting = db.Column(db.Boolean)
    sink_details = db.Column(db.Text)
    sink_customer_owned = db.Column(db.Boolean)
    tap_details = db.Column(db.Text)
    tap_customer_owned = db.Column(db.Boolean)
    accessories = db.Column(db.JSON)
    floor_protection = db.Column(db.String(100))
    approval_status = db.Column(db.String(50))
    approved_by = db.Column(db.String(200))
    approved_date = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='kitchen_checklists')
    project = db.relationship('Project', backref='kitchen_checklists')
    client = db.relationship('ClientMaster', backref='kitchen_checklists')

    def __repr__(self):
        return f'<KitchenChecklist {self.id} for Project {self.project_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'project_id': self.project_id,
            'client_id': self.client_id,
            'client_name': self.client.client_company_name if self.client else None,
            'appliances': self.appliances or [],
            'worktop_features': self.worktop_features,
            'worktop_size': self.worktop_size,
            'under_lighting': self.under_lighting,
            'sink_details': self.sink_details,
            'sink_customer_owned': self.sink_customer_owned,
            'tap_details': self.tap_details,
            'tap_customer_owned': self.tap_customer_owned,
            'accessories': self.accessories or [],
            'floor_protection': self.floor_protection,
            'approval_status': self.approval_status,
            'approved_by': self.approved_by,
            'approved_date': self.approved_date.isoformat() if self.approved_date else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================
# BEDROOM CHECKLISTS
# ============================================================

class BedroomChecklist(db.Model):
    """SCHEMA: StreemLyne_MT.interior_bedroom_checklists"""
    __tablename__ = 'interior_bedroom_checklists'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    project_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.interior_projects.id'))
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))

    bedside_cabinets = db.Column(db.Boolean)
    dresser_desk = db.Column(db.Boolean)
    internal_mirror = db.Column(db.Boolean)
    mirror_type = db.Column(db.String(100))
    mirror_quantity = db.Column(db.Integer)
    soffit_lights = db.Column(db.Boolean)
    soffit_light_color = db.Column(db.String(50))
    soffit_light_quantity = db.Column(db.Integer)
    gable_lights = db.Column(db.Boolean)
    gable_light_color = db.Column(db.String(50))
    gable_light_quantity = db.Column(db.Integer)
    accessories = db.Column(db.JSON)
    floor_protection = db.Column(db.String(100))
    approval_status = db.Column(db.String(50))
    approved_by = db.Column(db.String(200))
    approved_date = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='bedroom_checklists')
    project = db.relationship('Project', backref='bedroom_checklists')
    client = db.relationship('ClientMaster', backref='bedroom_checklists')

    def __repr__(self):
        return f'<BedroomChecklist {self.id} for Project {self.project_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'project_id': self.project_id,
            'client_id': self.client_id,
            'client_name': self.client.client_company_name if self.client else None,
            'bedside_cabinets': self.bedside_cabinets,
            'dresser_desk': self.dresser_desk,
            'internal_mirror': self.internal_mirror,
            'mirror_type': self.mirror_type,
            'mirror_quantity': self.mirror_quantity,
            'soffit_lights': self.soffit_lights,
            'soffit_light_color': self.soffit_light_color,
            'soffit_light_quantity': self.soffit_light_quantity,
            'gable_lights': self.gable_lights,
            'gable_light_color': self.gable_light_color,
            'gable_light_quantity': self.gable_light_quantity,
            'accessories': self.accessories or [],
            'floor_protection': self.floor_protection,
            'approval_status': self.approval_status,
            'approved_by': self.approved_by,
            'approved_date': self.approved_date.isoformat() if self.approved_date else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================
# MATERIAL ORDERING
# ============================================================

class MaterialOrder(db.Model):
    """SCHEMA: StreemLyne_MT.interior_material_orders"""
    __tablename__ = 'interior_material_orders'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    project_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.interior_projects.id'))

    material_description = db.Column(db.Text, nullable=False)
    quantity_requested = db.Column(db.Numeric(10, 2))
    quantity_ordered = db.Column(db.Numeric(10, 2))
    unit = db.Column(db.String(50))
    supplier_name = db.Column(db.String(255))
    supplier_reference = db.Column(db.String(100))
    status = db.Column(db.String(50))
    order_date = db.Column(db.Date)
    expected_delivery_date = db.Column(db.Date)
    actual_delivery_date = db.Column(db.Date)
    estimated_cost = db.Column(db.Numeric(10, 2))
    actual_cost = db.Column(db.Numeric(10, 2))
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='material_orders')
    project = db.relationship('Project', backref='material_orders')

    def __repr__(self):
        return f'<MaterialOrder {self.id} - {self.material_description[:30]}>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'project_id': self.project_id,
            'material_description': self.material_description,
            'quantity_requested': float(self.quantity_requested) if self.quantity_requested else None,
            'quantity_ordered': float(self.quantity_ordered) if self.quantity_ordered else None,
            'unit': self.unit,
            'supplier_name': self.supplier_name,
            'supplier_reference': self.supplier_reference,
            'status': self.status,
            'order_date': self.order_date.isoformat() if self.order_date else None,
            'expected_delivery_date': self.expected_delivery_date.isoformat() if self.expected_delivery_date else None,
            'actual_delivery_date': self.actual_delivery_date.isoformat() if self.actual_delivery_date else None,
            'estimated_cost': float(self.estimated_cost) if self.estimated_cost else None,
            'actual_cost': float(self.actual_cost) if self.actual_cost else None,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================
# APPLIANCE CATALOG
# ============================================================

class ApplianceCatalog(db.Model):
    """SCHEMA: StreemLyne_MT.interior_appliance_catalog"""
    __tablename__ = 'interior_appliance_catalog'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)

    category = db.Column(db.String(100))
    brand = db.Column(db.String(100))
    model = db.Column(db.String(100))
    sku = db.Column(db.String(100), unique=True)
    dimensions = db.Column(db.JSON)
    energy_rating = db.Column(db.String(10))
    warranty_years = db.Column(db.Integer)
    base_price = db.Column(db.Numeric(10, 2))
    low_tier_price = db.Column(db.Numeric(10, 2))
    mid_tier_price = db.Column(db.Numeric(10, 2))
    high_tier_price = db.Column(db.Numeric(10, 2))
    in_stock = db.Column(db.Boolean, default=True)
    stock_quantity = db.Column(db.Integer)
    description = db.Column(db.Text)
    image_url = db.Column(db.String(500))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='appliance_catalog')

    def __repr__(self):
        return f'<ApplianceCatalog {self.brand} {self.model}>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'category': self.category,
            'brand': self.brand,
            'model': self.model,
            'sku': self.sku,
            'dimensions': self.dimensions,
            'energy_rating': self.energy_rating,
            'warranty_years': self.warranty_years,
            'base_price': float(self.base_price) if self.base_price else None,
            'low_tier_price': float(self.low_tier_price) if self.low_tier_price else None,
            'mid_tier_price': float(self.mid_tier_price) if self.mid_tier_price else None,
            'high_tier_price': float(self.high_tier_price) if self.high_tier_price else None,
            'in_stock': self.in_stock,
            'stock_quantity': self.stock_quantity,
            'description': self.description,
            'image_url': self.image_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================
# DRAWINGS & LAYOUTS
# ============================================================

class DrawingDocument(db.Model):
    """SCHEMA: StreemLyne_MT.interior_drawings"""
    __tablename__ = 'interior_drawings'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    project_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.interior_projects.id'))
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))

    file_name = db.Column(db.String(255))
    storage_path = db.Column(db.String(500))
    file_url = db.Column(db.String(500))
    mime_type = db.Column(db.String(100))
    file_size = db.Column(db.Integer)
    category = db.Column(db.String(50))
    drawing_type = db.Column(db.String(100))
    version = db.Column(db.Integer, default=1)
    status = db.Column(db.String(50))
    uploaded_by = db.Column(db.String(200))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='drawing_documents')
    project = db.relationship('Project', backref='drawing_documents')
    client = db.relationship('ClientMaster', backref='drawing_documents')

    def __repr__(self):
        return f'<DrawingDocument {self.file_name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'project_id': self.project_id,
            'client_id': self.client_id,
            'client_name': self.client.client_company_name if self.client else None,
            'file_name': self.file_name,
            'storage_path': self.storage_path,
            'file_url': self.file_url,
            'mime_type': self.mime_type,
            'file_size': self.file_size,
            'category': self.category,
            'drawing_type': self.drawing_type,
            'version': self.version,
            'status': self.status,
            'uploaded_by': self.uploaded_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================
# DRAWING ANALYSER
# ============================================================

class Drawing(db.Model):
    """
    Technical drawings for cutting list generation (Drawing Analyser)

    SCHEMA: StreemLyne_MT.interior_drawing_analyser
    """
    __tablename__ = 'interior_drawing_analyser'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False)
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=True)
    project_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.interior_projects.id'), nullable=True)

    project_name = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(50), default='pending')
    ocr_method = db.Column(db.String(50))
    raw_ocr_output = db.Column(db.Text)
    optimization_result = db.Column(db.JSON)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='drawing_analyser_drawings')
    client = db.relationship('ClientMaster', backref='drawing_analyser_drawings')
    project = db.relationship('Project', backref='drawing_analyser_drawings')
    # NOTE: 'drawing' backref on CuttingList is provided by this relationship automatically
    cutting_list_items = db.relationship(
        'CuttingList',
        back_populates='drawing',
        cascade='all, delete-orphan',
        lazy='dynamic'
    )

    def to_dict(self, include_cutting_list=False):
        result = {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'client_id': self.client_id,
            'client_name': self.client.client_company_name if self.client else None,
            'project_id': self.project_id,
            'project_name': self.project_name,
            'original_filename': self.original_filename,
            'status': self.status,
            'ocr_method': self.ocr_method,
            'optimization_result': self.optimization_result,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_cutting_list:
            items = self.cutting_list_items.all()
            result['cutting_list'] = [item.to_dict() for item in items]
            result['total_pieces'] = sum(item.quantity for item in items)
            result['total_area_m2'] = self._calculate_total_area()

        return result

    def _calculate_total_area(self):
        items = self.cutting_list_items.all()
        total_mm2 = sum(
            (item.component_width or 0) * (item.height or 0) * (item.quantity or 0)
            for item in items
        )
        return round(total_mm2 / 1_000_000, 2)


# ============================================================
# CUTTING LISTS
# ============================================================

class CuttingList(db.Model):
    """
    Cutting list items generated from technical drawings

    SCHEMA: StreemLyne_MT.interior_cutting_lists
    """
    __tablename__ = 'interior_cutting_lists'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    drawing_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.interior_drawing_analyser.id', ondelete='CASCADE'),
        nullable=False
    )

    component_type = db.Column(db.String(100))
    part_name = db.Column(db.String(255))
    overall_unit_width = db.Column(db.Integer)
    component_width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    depth = db.Column(db.Integer, nullable=True)
    quantity = db.Column(db.Integer, default=1)
    material_thickness = db.Column(db.Integer)
    edge_banding_notes = db.Column(db.Text)
    is_completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # FIX: Use back_populates to match Drawing.cutting_list_items — do NOT define a
    # separate backref here. The original code had both sides defining backrefs for
    # each other, which caused a SQLAlchemy mapper conflict on startup.
    drawing = db.relationship('Drawing', back_populates='cutting_list_items')

    def __repr__(self):
        return f'<CuttingList {self.part_name} {self.component_width}x{self.height}>'

    def to_dict(self):
        return {
            'id': self.id,
            'drawing_id': self.drawing_id,
            'component_type': self.component_type,
            'part_name': self.part_name,
            'overall_unit_width': self.overall_unit_width,
            'component_width': self.component_width,
            'height': self.height,
            'depth': self.depth,
            'quantity': self.quantity,
            'material_thickness': self.material_thickness,
            'edge_banding_notes': self.edge_banding_notes,
            'is_completed': self.is_completed,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'area_mm2': (self.component_width or 0) * (self.height or 0),
            'area_m2': round(((self.component_width or 0) * (self.height or 0)) / 1_000_000, 4)
        }