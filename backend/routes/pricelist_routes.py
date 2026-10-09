"""
Pricelist Routes
Handles: PriceList_Master — tenant-scoped service/item price catalogue.
Used by the AI chatbot to pre-fill quote line items.

Endpoints:
  GET    /api/pricelist          — list all items for tenant
  POST   /api/pricelist          — create item
  PUT    /api/pricelist/<id>     — update item
  DELETE /api/pricelist/<id>     — delete item
  POST   /api/pricelist/seed     — seed dummy data (only if tenant has 0 items)
"""

from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy.exc import IntegrityError
from database import db
from middleware import auth_required
from datetime import datetime
from decimal import Decimal

pricelist_bp = Blueprint('pricelist', __name__, url_prefix='/pricelist')


# ── Model (inline — avoids adding to models.py for now) ──────────────────────

from sqlalchemy import Column, Integer, String, Numeric, Text, DateTime
from database import db

class PriceListMaster(db.Model):
    __tablename__  = 'PriceList_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    pricelist_id      = db.Column(db.Integer, primary_key=True, autoincrement=True)
    tenant_id         = db.Column(db.String,  nullable=False, index=True)
    category          = db.Column(db.String,  nullable=False)
    item_name         = db.Column(db.String,  nullable=False)
    description       = db.Column(db.Text)
    base_price        = db.Column(db.Numeric(10, 2))
    unit              = db.Column(db.String,  default='each')
    item_code         = db.Column(db.String(50))
    dimension_based   = db.Column(db.Boolean, default=False)
    dimension_formula = db.Column(db.String)
    door_type         = db.Column(db.String(100))
    width             = db.Column(db.Integer)
    height            = db.Column(db.Integer)
    depth             = db.Column(db.Integer)
    brand             = db.Column(db.String(50))
    colour            = db.Column(db.String(255))
    alias_codes       = db.Column(db.Text)
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at        = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'pricelist_id':      self.pricelist_id,
            'tenant_id':         self.tenant_id,
            'category':          self.category,
            'item_name':         self.item_name,
            'description':       self.description,
            'base_price':        float(self.base_price) if self.base_price is not None else None,
            'unit':              self.unit or 'each',
            'item_code':         self.item_code,
            'dimension_based':   self.dimension_based or False,
            'dimension_formula': self.dimension_formula,
            'door_type':         self.door_type,
            'width':             self.width,
            'height':            self.height,
            'depth':             self.depth,
            'brand':             self.brand,
            'colour':            self.colour,
            'alias_codes':       self.alias_codes,
            'created_at':        self.created_at.isoformat() if self.created_at else None,
            'updated_at':        self.updated_at.isoformat() if self.updated_at else None,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

DUMMY_ITEMS = [
    # Consulting
    {"category": "Consulting",    "item_name": "Initial Consultation",       "description": "One-hour discovery call or meeting",         "base_price": 150.00,  "unit": "session"},
    {"category": "Consulting",    "item_name": "Strategy Session",           "description": "Half-day strategic planning workshop",        "base_price": 500.00,  "unit": "session"},
    {"category": "Consulting",    "item_name": "Business Analysis Report",   "description": "Detailed written analysis and recommendations","base_price": 800.00,  "unit": "report"},
    # Design
    {"category": "Design",        "item_name": "Logo Design",                "description": "Brand logo with 3 concepts and revisions",    "base_price": 350.00,  "unit": "project"},
    {"category": "Design",        "item_name": "Website Mockup",             "description": "UI/UX mockup for up to 5 pages",              "base_price": 600.00,  "unit": "project"},
    {"category": "Design",        "item_name": "Social Media Pack",          "description": "10 branded social media templates",           "base_price": 250.00,  "unit": "pack"},
    # Development
    {"category": "Development",   "item_name": "Website Development",        "description": "Custom website build (up to 10 pages)",       "base_price": 2500.00, "unit": "project"},
    {"category": "Development",   "item_name": "Landing Page",               "description": "Single conversion-focused landing page",      "base_price": 600.00,  "unit": "page"},
    {"category": "Development",   "item_name": "API Integration",            "description": "Third-party API connection and testing",      "base_price": 400.00,  "unit": "integration"},
    {"category": "Development",   "item_name": "Monthly Maintenance",        "description": "Ongoing site updates and support",            "base_price": 150.00,  "unit": "month"},
    # Marketing
    {"category": "Marketing",     "item_name": "SEO Audit",                  "description": "Full technical and content SEO review",       "base_price": 300.00,  "unit": "report"},
    {"category": "Marketing",     "item_name": "Social Media Management",    "description": "Monthly content creation and scheduling",     "base_price": 400.00,  "unit": "month"},
    {"category": "Marketing",     "item_name": "Email Campaign",             "description": "Design and send one email campaign",          "base_price": 200.00,  "unit": "campaign"},
    # Training
    {"category": "Training",      "item_name": "Staff Training Session",     "description": "On-site or remote training (half day)",       "base_price": 450.00,  "unit": "session"},
    {"category": "Training",      "item_name": "Online Course Creation",     "description": "Scripted and recorded e-learning module",     "base_price": 1200.00, "unit": "module"},
    {"category": "Training",      "item_name": "Workshop Facilitation",      "description": "Full-day group workshop with materials",      "base_price": 900.00,  "unit": "day"},
    # Support
    {"category": "Support",       "item_name": "Hourly Support",             "description": "Ad-hoc technical or consultancy support",     "base_price": 85.00,   "unit": "hour"},
    {"category": "Support",       "item_name": "Support Retainer",           "description": "10 hours/month priority support package",     "base_price": 750.00,  "unit": "month"},
    # Installation
    {"category": "Installation",  "item_name": "On-site Installation",       "description": "Equipment or system installation visit",      "base_price": 300.00,  "unit": "visit"},
    {"category": "Installation",  "item_name": "Cabling & Setup",            "description": "Network or hardware cabling and setup",       "base_price": 180.00,  "unit": "day"},
]


# ── Routes ────────────────────────────────────────────────────────────────────

@pricelist_bp.route('', methods=['GET'])
@auth_required
def list_items():
    """GET /api/pricelist — list all pricelist items for tenant, grouped by category."""
    category = request.args.get('category')
    search   = request.args.get('search', '').strip().lower()

    query = PriceListMaster.query.filter_by(tenant_id=g.tenant_id)

    if category:
        query = query.filter(PriceListMaster.category == category)

    if search:
        query = query.filter(
            db.or_(
                PriceListMaster.item_name.ilike(f'%{search}%'),
                PriceListMaster.description.ilike(f'%{search}%'),
                PriceListMaster.category.ilike(f'%{search}%'),
            )
        )

    items = query.order_by(PriceListMaster.category, PriceListMaster.item_name).all()
    return jsonify([i.to_dict() for i in items]), 200


@pricelist_bp.route('/categories', methods=['GET'])
@auth_required
def list_categories():
    """GET /api/pricelist/categories — list distinct categories for tenant."""
    rows = db.session.query(PriceListMaster.category).filter_by(
        tenant_id=g.tenant_id
    ).distinct().order_by(PriceListMaster.category).all()
    return jsonify([r.category for r in rows]), 200


@pricelist_bp.route('', methods=['POST'])
@auth_required
def create_item():
    """POST /api/pricelist — create a new pricelist item."""
    data = request.get_json() or {}

    if not (data.get('item_name') or '').strip():
        return jsonify({'error': 'item_name is required'}), 400
    if not (data.get('category') or '').strip():
        return jsonify({'error': 'category is required'}), 400

    item = PriceListMaster(
        tenant_id   = g.tenant_id,
        category    = data['category'].strip(),
        item_name   = data['item_name'].strip(),
        description = (data.get('description') or '').strip() or None,
        base_price  = Decimal(str(data['base_price'])) if data.get('base_price') is not None else None,
        unit        = (data.get('unit') or 'each').strip() or 'each',
        item_code   = (data.get('item_code') or '').strip() or None,
    )

    db.session.add(item)
    db.session.commit()
    return jsonify({'message': 'Item created', 'item': item.to_dict()}), 201


@pricelist_bp.route('/<int:item_id>', methods=['PUT'])
@auth_required
def update_item(item_id: int):
    item = PriceListMaster.query.filter_by(
        pricelist_id=item_id, tenant_id=g.tenant_id
    ).first()
    if not item:
        abort(404, description='Item not found')

    data = request.get_json() or {}

    if 'category'          in data: item.category          = data['category'].strip()
    if 'item_name'         in data: item.item_name         = data['item_name'].strip()
    if 'description'       in data: item.description       = (data.get('description') or '').strip() or None
    if 'unit'              in data: item.unit              = (data.get('unit') or 'each').strip() or 'each'
    if 'item_code'         in data: item.item_code         = (data.get('item_code') or '').strip() or None
    if 'dimension_based'   in data: item.dimension_based   = data['dimension_based']
    if 'dimension_formula' in data: item.dimension_formula = data.get('dimension_formula')
    if 'door_type'         in data: item.door_type         = data.get('door_type')
    if 'width'             in data: item.width             = data.get('width')
    if 'height'            in data: item.height            = data.get('height')
    if 'depth'             in data: item.depth             = data.get('depth')
    if 'brand'             in data: item.brand             = data.get('brand')
    if 'colour'            in data: item.colour            = data.get('colour')
    if 'alias_codes'       in data: item.alias_codes       = data.get('alias_codes')
    if 'base_price'        in data:
        item.base_price = Decimal(str(data['base_price'])) if data['base_price'] is not None else None

    item.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'message': 'Item updated', 'item': item.to_dict()}), 200

@pricelist_bp.route('/<int:item_id>', methods=['DELETE'])
@auth_required
def delete_item(item_id: int):
    """DELETE /api/pricelist/<id> — delete a pricelist item."""
    item = PriceListMaster.query.filter_by(
        pricelist_id=item_id, tenant_id=g.tenant_id
    ).first()
    if not item:
        abort(404, description='Item not found')

    db.session.delete(item)
    db.session.commit()
    return jsonify({'message': 'Item deleted'}), 200


@pricelist_bp.route('/seed', methods=['POST'])
@auth_required
def seed_items():
    """
    POST /api/pricelist/seed
    Seeds dummy pricelist items for the tenant.
    Only runs if the tenant has 0 items — safe to call multiple times.
    """
    existing = PriceListMaster.query.filter_by(tenant_id=g.tenant_id).count()
    if existing > 0:
        return jsonify({
            'message': f'Pricelist already has {existing} items — skipping seed.',
            'seeded': 0,
        }), 200

    for item_data in DUMMY_ITEMS:
        item = PriceListMaster(
            tenant_id   = g.tenant_id,
            category    = item_data['category'],
            item_name   = item_data['item_name'],
            description = item_data['description'],
            base_price  = Decimal(str(item_data['base_price'])),
            unit        = item_data['unit'],
        )
        db.session.add(item)

    db.session.commit()
    return jsonify({
        'message': f'Seeded {len(DUMMY_ITEMS)} items successfully.',
        'seeded': len(DUMMY_ITEMS),
    }), 201