import uuid
from datetime import datetime
from models.core import db

# ============================================================
# PROJECTS (Multiple per Customer)
# ============================================================

class Project(db.Model):
    """
    Multiple projects per customer (Kitchen, Bedroom, Wardrobe, etc.)
    Each customer can have multiple concurrent or historical projects
    """
    __tablename__ = 'interior_projects'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'), nullable=False)
    
    # Project Details
    project_name = db.Column(db.String(255))
    project_type = db.Column(db.String(100))  # Kitchen, Bedroom, Wardrobe, Remedial, Other
    stage = db.Column(db.String(50))  # Lead→Survey→Design→Quote→Accepted→Production→Installation→Complete
    
    # Key Dates
    date_of_measure = db.Column(db.Date)
    date_of_installation = db.Column(db.Date)
    completion_date = db.Column(db.Date)
    
    # Team Assignments
    salesperson = db.Column(db.String(200))
    assigned_team = db.Column(db.String(200))
    primary_fitter = db.Column(db.String(200))
    
    # Project Data (measurements, notes, etc.)
    project_data = db.Column(db.JSON)
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    customer = db.relationship('Customer', backref='interior_projects')
    tenant = db.relationship('Tenant')
    
    def __repr__(self):
        return f'<Project {self.project_name} - {self.project_type}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'customer_id': self.customer_id,
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
    """Kitchen installation checklist"""
    __tablename__ = 'interior_kitchen_checklists'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    project_id = db.Column(db.String(36), db.ForeignKey('interior_projects.id'))
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'))
    
    # Appliances (JSON array)
    appliances = db.Column(db.JSON)
    
    # Worktop Details
    worktop_features = db.Column(db.Text)
    worktop_size = db.Column(db.String(100))
    under_lighting = db.Column(db.Boolean)
    
    # Sink & Tap
    sink_details = db.Column(db.Text)
    sink_customer_owned = db.Column(db.Boolean)
    tap_details = db.Column(db.Text)
    tap_customer_owned = db.Column(db.Boolean)
    
    # Accessories (JSON array)
    accessories = db.Column(db.JSON)
    
    # Floor Protection
    floor_protection = db.Column(db.String(100))
    
    # Approval Status
    approval_status = db.Column(db.String(50))
    approved_by = db.Column(db.String(200))
    approved_date = db.Column(db.DateTime)
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    project = db.relationship('Project', backref='kitchen_checklists')
    customer = db.relationship('Customer', backref='kitchen_checklists')
    tenant = db.relationship('Tenant')
    
    def __repr__(self):
        return f'<KitchenChecklist {self.id} for Project {self.project_id}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'project_id': self.project_id,
            'customer_id': self.customer_id,
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
    """Bedroom/Wardrobe installation checklist"""
    __tablename__ = 'interior_bedroom_checklists'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    project_id = db.Column(db.String(36), db.ForeignKey('interior_projects.id'))
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'))
    
    # Wardrobes & Furniture
    bedside_cabinets = db.Column(db.Boolean)
    dresser_desk = db.Column(db.Boolean)
    
    # Mirrors
    internal_mirror = db.Column(db.Boolean)
    mirror_type = db.Column(db.String(100))
    mirror_quantity = db.Column(db.Integer)
    
    # Soffit Lighting
    soffit_lights = db.Column(db.Boolean)
    soffit_light_color = db.Column(db.String(50))
    soffit_light_quantity = db.Column(db.Integer)
    
    # Gable Lighting
    gable_lights = db.Column(db.Boolean)
    gable_light_color = db.Column(db.String(50))
    gable_light_quantity = db.Column(db.Integer)
    
    # Accessories (JSON array)
    accessories = db.Column(db.JSON)
    
    # Floor Protection
    floor_protection = db.Column(db.String(100))
    
    # Approval Status
    approval_status = db.Column(db.String(50))
    approved_by = db.Column(db.String(200))
    approved_date = db.Column(db.DateTime)
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    project = db.relationship('Project', backref='bedroom_checklists')
    customer = db.relationship('Customer', backref='bedroom_checklists')
    tenant = db.relationship('Tenant')
    
    def __repr__(self):
        return f'<BedroomChecklist {self.id} for Project {self.project_id}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'project_id': self.project_id,
            'customer_id': self.customer_id,
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
    """Material ordering with supplier tracking"""
    __tablename__ = 'interior_material_orders'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    project_id = db.Column(db.String(36), db.ForeignKey('interior_projects.id'))
    
    # Material Details
    material_description = db.Column(db.Text, nullable=False)
    quantity_requested = db.Column(db.Numeric(10, 2))
    quantity_ordered = db.Column(db.Numeric(10, 2))
    unit = db.Column(db.String(50))
    
    # Supplier Information
    supplier_name = db.Column(db.String(255))
    supplier_reference = db.Column(db.String(100))
    
    # Status & Tracking
    status = db.Column(db.String(50))
    order_date = db.Column(db.Date)
    expected_delivery_date = db.Column(db.Date)
    actual_delivery_date = db.Column(db.Date)
    
    # Financial
    estimated_cost = db.Column(db.Numeric(10, 2))
    actual_cost = db.Column(db.Numeric(10, 2))
    
    # Additional Info
    notes = db.Column(db.Text)
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    project = db.relationship('Project', backref='material_orders')
    tenant = db.relationship('Tenant')
    
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
    """Appliance product catalog with tier-based pricing"""
    __tablename__ = 'interior_appliance_catalog'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    
    # Appliance Details
    category = db.Column(db.String(100))
    brand = db.Column(db.String(100))
    model = db.Column(db.String(100))
    sku = db.Column(db.String(100), unique=True)
    
    # Specifications
    dimensions = db.Column(db.JSON)
    energy_rating = db.Column(db.String(10))
    warranty_years = db.Column(db.Integer)
    
    # Tier-Based Pricing
    base_price = db.Column(db.Numeric(10, 2))
    low_tier_price = db.Column(db.Numeric(10, 2))
    mid_tier_price = db.Column(db.Numeric(10, 2))
    high_tier_price = db.Column(db.Numeric(10, 2))
    
    # Availability
    in_stock = db.Column(db.Boolean, default=True)
    stock_quantity = db.Column(db.Integer)
    
    # Additional Info
    description = db.Column(db.Text)
    image_url = db.Column(db.String(500))
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    tenant = db.relationship('Tenant')
    
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
    """CAD drawings and layout management"""
    __tablename__ = 'interior_drawings'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    project_id = db.Column(db.String(36), db.ForeignKey('interior_projects.id'))
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'))
    
    # File Details
    file_name = db.Column(db.String(255))
    storage_path = db.Column(db.String(500))
    file_url = db.Column(db.String(500))
    mime_type = db.Column(db.String(100))
    file_size = db.Column(db.Integer)
    
    # Document Info
    category = db.Column(db.String(50))
    drawing_type = db.Column(db.String(100))
    version = db.Column(db.Integer, default=1)
    
    # Status
    status = db.Column(db.String(50))
    
    # Audit
    uploaded_by = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    project = db.relationship('Project', backref='drawings')
    customer = db.relationship('Customer', backref='drawings')
    tenant = db.relationship('Tenant')
    
    def __repr__(self):
        return f'<DrawingDocument {self.file_name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'project_id': self.project_id,
            'customer_id': self.customer_id,
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
# DRAWING ANALYSER MODULE - Technical Drawings with OCR
# ============================================================

class Drawing(db.Model):
    """Technical drawings uploaded for cutting list generation (Drawing Analyser)"""
    __tablename__ = 'drawings'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False)
    customer_id = db.Column(db.String(36), db.ForeignKey('customers.id'), nullable=True)
    job_id = db.Column(db.String(36), db.ForeignKey('jobs.id'), nullable=True)
    project_id = db.Column(db.String(36), db.ForeignKey('interior_projects.id'), nullable=True)
    
    project_name = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    
    status = db.Column(db.String(50), default='pending')  # pending, processing, completed, failed
    ocr_method = db.Column(db.String(50))  # qwen2.5-vl, openai_vision, default
    raw_ocr_output = db.Column(db.Text)
    optimization_result = db.Column(db.JSON)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    tenant = db.relationship('Tenant', backref='drawing_analyser_drawings')
    customer = db.relationship('Customer', backref='drawing_analyser_drawings')
    job = db.relationship('Job', backref='drawing_analyser_drawings')
    cutting_list_items = db.relationship('CuttingList', backref='drawing', cascade='all, delete-orphan', lazy='dynamic')
    
    def to_dict(self, include_cutting_list=False):
        result = {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'customer_id': self.customer_id,
            'job_id': self.job_id,
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
            result['cutting_list'] = [item.to_dict() for item in self.cutting_list_items]
            result['total_pieces'] = sum(item.quantity for item in self.cutting_list_items)
            result['total_area_m2'] = self._calculate_total_area()
        
        return result
    
    def _calculate_total_area(self):
        """Calculate total area in square meters"""
        total_mm2 = sum(
            (item.component_width or 0) * (item.height or 0) * (item.quantity or 0)
            for item in self.cutting_list_items
        )
        return round(total_mm2 / 1_000_000, 2)


# ============================================================
# CUTTING LISTS - Auto-generated from Drawing Analyser
# ============================================================

class CuttingList(db.Model):
    """Cutting list items generated from technical drawings"""
    __tablename__ = 'cutting_lists'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    drawing_id = db.Column(db.String(36), db.ForeignKey('drawings.id', ondelete='CASCADE'), nullable=False)
    
    component_type = db.Column(db.String(100))  # GABLE, BASE, SHELF, BACKS, BRACES
    part_name = db.Column(db.String(255))
    
    overall_unit_width = db.Column(db.Integer)  # Original cabinet width (e.g., 900)
    component_width = db.Column(db.Integer)  # Calculated width (e.g., 864)
    height = db.Column(db.Integer)
    depth = db.Column(db.Integer, nullable=True)
    quantity = db.Column(db.Integer, default=1)
    material_thickness = db.Column(db.Integer)
    
    edge_banding_notes = db.Column(db.Text)
    
    # Track completion status
    is_completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
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
    
    def __repr__(self):
        return f'<CuttingList {self.part_name} {self.component_width}x{self.height}>'