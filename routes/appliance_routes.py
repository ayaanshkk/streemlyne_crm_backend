# routes/appliance_routes.py
from flask import Blueprint, request, jsonify, current_app
from database import db
from models import Product, Brand, ApplianceCategory, DataImport, ProductQuoteItem
from datetime import datetime
import json
import pandas as pd
from werkzeug.utils import secure_filename
import os

appliance_bp = Blueprint('appliances', __name__)

def serialize_product(product):
    """Serialize product object to dictionary"""
    return {
        'id': product.id,
        'model_code': product.model_code,
        'name': product.name,
        'description': product.description,
        'series': product.series,
        'brand': {
            'id': product.brand.id,
            'name': product.brand.name
        } if product.brand else None,
        'category': {
            'id': product.category.id,
            'name': product.category.name
        } if product.category else None,
        'pricing': {
            'base_price': float(product.base_price) if product.base_price else None,
            'low_tier_price': float(product.low_tier_price) if product.low_tier_price else None,
            'mid_tier_price': float(product.mid_tier_price) if product.mid_tier_price else None,
            'high_tier_price': float(product.high_tier_price) if product.high_tier_price else None,
        },
        'dimensions': product.get_dimensions_dict(),
        'weight': float(product.weight) if product.weight else None,
        'color_options': product.get_color_options_list(),
        'pack_name': product.pack_name,
        'notes': product.notes,
        'energy_rating': product.energy_rating,
        'warranty_years': product.warranty_years,
        'active': product.active,
        'in_stock': product.in_stock,
        'lead_time_weeks': product.lead_time_weeks,
        'created_at': product.created_at.isoformat() if product.created_at else None,
        'updated_at': product.updated_at.isoformat() if product.updated_at else None,
    }

# Product endpoints
@appliance_bp.route('/products', methods=['GET'])
def get_products():
    """Get all products with filtering and search"""
    try:
        # Query parameters
        search = request.args.get('search', '')
        brand_id = request.args.get('brand_id', type=int)
        category_id = request.args.get('category_id', type=int)
        series = request.args.get('series')
        tier = request.args.get('tier')  # low/mid/high
        active_only = request.args.get('active_only', 'true').lower() == 'true'
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 50, type=int), 100)
        
        # Build query
        query = Product.query
        
        if active_only:
            query = query.filter(Product.active == True)
        
        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                db.or_(
                    Product.name.ilike(search_filter),
                    Product.model_code.ilike(search_filter),
                    Product.series.ilike(search_filter)
                )
            )
        
        if brand_id:
            query = query.filter(Product.brand_id == brand_id)
        
        if category_id:
            query = query.filter(Product.category_id == category_id)
        
        if series:
            query = query.filter(Product.series.ilike(f"%{series}%"))
        
        # Order by brand, then series, then model
        query = query.join(Brand).order_by(Brand.name, Product.series, Product.model_code)
        
        # Paginate
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        products = pagination.items
        
        return jsonify({
            'products': [serialize_product(p) for p in products],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': pagination.total,
                'pages': pagination.pages,
                'has_next': pagination.has_next,
                'has_prev': pagination.has_prev
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@appliance_bp.route('/products/<int:product_id>', methods=['GET'])
def get_product(product_id):
    """Get a specific product by ID"""
    try:
        product = Product.query.get_or_404(product_id)
        return jsonify(serialize_product(product))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@appliance_bp.route('/products', methods=['POST'])
def create_product():
    """Create a new product"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['model_code', 'name', 'brand_id', 'category_id']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        # Check if model code already exists
        if Product.query.filter_by(model_code=data['model_code']).first():
            return jsonify({'error': 'Model code already exists'}), 400
        
        # Create product
        product = Product(
            model_code=data['model_code'],
            name=data['name'],
            description=data.get('description'),
            brand_id=data['brand_id'],
            category_id=data['category_id'],
            series=data.get('series'),
            base_price=data.get('base_price'),
            low_tier_price=data.get('low_tier_price'),
            mid_tier_price=data.get('mid_tier_price'),
            high_tier_price=data.get('high_tier_price'),
            dimensions=json.dumps(data.get('dimensions', {})),
            weight=data.get('weight'),
            color_options=json.dumps(data.get('color_options', [])),
            pack_name=data.get('pack_name'),
            notes=data.get('notes'),
            energy_rating=data.get('energy_rating'),
            warranty_years=data.get('warranty_years'),
            active=data.get('active', True),
            in_stock=data.get('in_stock', True),
            lead_time_weeks=data.get('lead_time_weeks')
        )
        
        db.session.add(product)
        db.session.commit()
        
        return jsonify(serialize_product(product)), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@appliance_bp.route('/products/<int:product_id>', methods=['PUT'])
def update_product(product_id):
    """Update an existing product"""
    try:
        product = Product.query.get_or_404(product_id)
        data = request.get_json()
        
        # Update fields
        updatable_fields = [
            'name', 'description', 'series', 'base_price', 'low_tier_price',
            'mid_tier_price', 'high_tier_price', 'weight', 'pack_name',
            'notes', 'energy_rating', 'warranty_years', 'active', 'in_stock',
            'lead_time_weeks', 'brand_id', 'category_id'
        ]
        
        for field in updatable_fields:
            if field in data:
                setattr(product, field, data[field])
        
        # Handle JSON fields
        if 'dimensions' in data:
            product.dimensions = json.dumps(data['dimensions'])
        if 'color_options' in data:
            product.color_options = json.dumps(data['color_options'])
        
        # Don't allow model_code changes to prevent breaking references
        # if 'model_code' in data:
        #     product.model_code = data['model_code']
        
        product.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify(serialize_product(product))
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@appliance_bp.route('/products/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    """Delete a product (soft delete by setting active=False)"""
    try:
        product = Product.query.get_or_404(product_id)
        product.active = False
        product.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'message': 'Product deactivated successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# Brand endpoints
@appliance_bp.route('/brands', methods=['GET'])
def get_brands():
    """Get all brands"""
    try:
        active_only = request.args.get('active_only', 'true').lower() == 'true'
        
        query = Brand.query
        if active_only:
            query = query.filter(Brand.active == True)
        
        brands = query.order_by(Brand.name).all()
        
        return jsonify([{
            'id': b.id,
            'name': b.name,
            'logo_url': b.logo_url,
            'website': b.website,
            'active': b.active,
            'product_count': len([p for p in b.products if p.active]) if active_only else len(b.products)
        } for b in brands])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@appliance_bp.route('/brands', methods=['POST'])
def create_brand():
    """Create a new brand"""
    try:
        data = request.get_json()
        
        if not data.get('name'):
            return jsonify({'error': 'Brand name is required'}), 400
        
        # Check if brand already exists
        if Brand.query.filter_by(name=data['name']).first():
            return jsonify({'error': 'Brand already exists'}), 400
        
        brand = Brand(
            name=data['name'],
            logo_url=data.get('logo_url'),
            website=data.get('website'),
            active=data.get('active', True)
        )
        
        db.session.add(brand)
        db.session.commit()
        
        return jsonify({
            'id': brand.id,
            'name': brand.name,
            'logo_url': brand.logo_url,
            'website': brand.website,
            'active': brand.active
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# Category endpoints
@appliance_bp.route('/categories', methods=['GET'])
def get_categories():
    """Get all appliance categories"""
    try:
        active_only = request.args.get('active_only', 'true').lower() == 'true'
        
        query = ApplianceCategory.query
        if active_only:
            query = query.filter(ApplianceCategory.active == True)
        
        categories = query.order_by(ApplianceCategory.name).all()
        
        return jsonify([{
            'id': c.id,
            'name': c.name,
            'description': c.description,
            'active': c.active,
            'product_count': len([p for p in c.products if p.active]) if active_only else len(c.products)
        } for c in categories])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@appliance_bp.route('/categories', methods=['POST'])
def create_category():
    """Create a new appliance category"""
    try:
        data = request.get_json()
        
        if not data.get('name'):
            return jsonify({'error': 'Category name is required'}), 400
        
        # Check if category already exists
        if ApplianceCategory.query.filter_by(name=data['name']).first():
            return jsonify({'error': 'Category already exists'}), 400
        
        category = ApplianceCategory(
            name=data['name'],
            description=data.get('description'),
            active=data.get('active', True)
        )
        
        db.session.add(category)
        db.session.commit()
        
        return jsonify({
            'id': category.id,
            'name': category.name,
            'description': category.description,
            'active': category.active
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# Price tier endpoint
@appliance_bp.route('/products/<int:product_id>/price/<tier>', methods=['GET'])
def get_product_price_for_tier(product_id, tier):
    """Get product price for specific tier"""
    try:
        product = Product.query.get_or_404(product_id)
        price = product.get_price_for_tier(tier)
        
        return jsonify({
            'product_id': product_id,
            'tier': tier,
            'price': float(price) if price else None
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Search endpoint with autocomplete
@appliance_bp.route('/products/search', methods=['GET'])
def search_products():
    """Search products with autocomplete support"""
    try:
        query_text = request.args.get('q', '')
        limit = min(request.args.get('limit', 10, type=int), 50)
        
        if len(query_text) < 2:
            return jsonify([])
        
        search_filter = f"%{query_text}%"
        products = Product.query.filter(
            Product.active == True
        ).filter(
            db.or_(
                Product.name.ilike(search_filter),
                Product.model_code.ilike(search_filter),
                Product.series.ilike(search_filter)
            )
        ).join(Brand).order_by(
            Brand.name, Product.series, Product.model_code
        ).limit(limit).all()
        
        return jsonify([{
            'id': p.id,
            'model_code': p.model_code,
            'name': p.name,
            'brand_name': p.brand.name if p.brand else None,
            'series': p.series,
            'base_price': float(p.base_price) if p.base_price else None,
            'category_name': p.category.name if p.category else None
        } for p in products])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Data import endpoints (for bulk import functionality)
@appliance_bp.route('/import/upload', methods=['POST'])
def upload_import_file():
    """Upload file for data import"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        import_type = request.form.get('import_type', 'appliance_matrix')
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.lower().endswith(('.xlsx', '.xls', '.csv')):
            return jsonify({'error': 'Invalid file type. Please upload Excel or CSV file'}), 400
        
        # Save file
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{filename}"
        
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)
        file.save(file_path)
        
        # Create import record
        import_record = DataImport(
            filename=filename,
            import_type=import_type,
            imported_by=request.form.get('imported_by', 'System')
        )
        db.session.add(import_record)
        db.session.commit()
        
        return jsonify({
            'import_id': import_record.id,
            'filename': filename,
            'message': 'File uploaded successfully. Processing will begin shortly.'
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@appliance_bp.route('/import/<int:import_id>/status', methods=['GET'])
def get_import_status(import_id):
    """Get status of data import"""
    try:
        import_record = DataImport.query.get_or_404(import_id)
        
        return jsonify({
            'id': import_record.id,
            'filename': import_record.filename,
            'import_type': import_record.import_type,
            'status': import_record.status,
            'records_processed': import_record.records_processed,
            'records_failed': import_record.records_failed,
            'error_log': import_record.error_log,
            'created_at': import_record.created_at.isoformat(),
            'completed_at': import_record.completed_at.isoformat() if import_record.completed_at else None
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500