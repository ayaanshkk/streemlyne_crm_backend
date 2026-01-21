# backend/routes/drawing_analyser.py

from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename
from functools import wraps
import os
import uuid
from datetime import datetime
import logging

# Fix imports - db is in models.core
from models.core import db
from models import Tenant
from models.modules.interior_design import Drawing, CuttingList
from services.ocr_dimension_extractor import OCRDimensionExtractor

drawing_bp = Blueprint('drawing_analyser', __name__)
logger = logging.getLogger(__name__)

# Initialize OCR service
ocr_extractor = OCRDimensionExtractor()

# File upload configuration
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads', 'drawings')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def require_module(module_name):
    """Middleware to check if tenant has access to this module"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            tenant_id = request.headers.get('X-Tenant-ID')
            
            if not tenant_id:
                return jsonify({'error': 'X-Tenant-ID header required'}), 400
            
            tenant = Tenant.query.filter_by(id=tenant_id).first()
            
            if not tenant:
                return jsonify({'error': 'Tenant not found'}), 404
            
            enabled_modules = tenant.enabled_modules or {}
            if not enabled_modules.get(module_name):
                return jsonify({
                    'error': f'Module {module_name} not enabled for this tenant',
                    'available_modules': list(enabled_modules.keys())
                }), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# Helper functions (defined before routes use them)
def _parse_dimension(value):
    """Extract numeric dimension from string like '900' or '900mm' or 'N/A'"""
    if not value or value == 'N/A':
        return None
    
    numeric_str = ''.join(c for c in str(value) if c.isdigit() or c == '.')
    
    try:
        return float(numeric_str) if '.' in numeric_str else int(numeric_str)
    except:
        return None

def _parse_quantity(value):
    """Extract quantity from string"""
    try:
        return int(''.join(c for c in str(value) if c.isdigit()))
    except:
        return 1


@drawing_bp.route('/api/drawing-analyser/upload', methods=['POST'])
@require_module('cutting_list_generator')
def upload_drawing():
    """Upload a technical drawing and extract cutting list"""
    tenant_id = request.headers.get('X-Tenant-ID')
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Allowed: PNG, JPG, PDF'}), 400
    
    try:
        # Generate unique filename
        file_ext = file.filename.rsplit('.', 1)[1].lower()
        unique_filename = f"{uuid.uuid4()}.{file_ext}"
        file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
        
        # Save file
        file.save(file_path)
        logger.info(f"📁 File saved: {file_path}")
        
        # Read file bytes for OCR
        with open(file_path, 'rb') as f:
            image_bytes = f.read()
        
        # Extract dimensions using OCR
        logger.info("🤖 Starting OCR extraction...")
        ocr_result = ocr_extractor.extract_dimensions(image_bytes)
        
        logger.info(f"✅ OCR completed using method: {ocr_result.get('method')}")
        
        # Create Drawing record
        drawing = Drawing(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            customer_id=request.form.get('customer_id'),
            job_id=request.form.get('job_id'),
            project_id=request.form.get('project_id'),
            project_name=request.form.get('project_name', 'Untitled Project'),
            original_filename=file.filename,
            file_path=file_path,
            status='completed' if ocr_result.get('success') else 'failed',
            ocr_method=ocr_result.get('method'),
            raw_ocr_output=ocr_result.get('raw_output'),
            created_at=datetime.utcnow()
        )
        
        db.session.add(drawing)
        db.session.flush()
        
        # Create CuttingList records from table data
        cutting_list_items = []
        
        if ocr_result.get('success') and ocr_result.get('table_data'):
            table_data = ocr_result['table_data']
            
            # Skip header row
            for row in table_data[1:]:
                if len(row) < 7:
                    continue
                
                cutting_item = CuttingList(
                    id=str(uuid.uuid4()),
                    drawing_id=drawing.id,
                    component_type=row[0],
                    part_name=row[1],
                    overall_unit_width=_parse_dimension(row[2]),
                    component_width=_parse_dimension(row[3]),
                    height=_parse_dimension(row[4]),
                    depth=_parse_dimension(row[5]) if len(row) > 5 else None,
                    quantity=_parse_quantity(row[6]) if len(row) > 6 else 1,
                    material_thickness=_parse_dimension(row[7]) if len(row) > 7 else 18,
                    edge_banding_notes=row[8] if len(row) > 8 else None,
                    created_at=datetime.utcnow()
                )
                
                db.session.add(cutting_item)
                cutting_list_items.append(cutting_item)
        
        db.session.commit()
        
        logger.info(f"✅ Drawing saved: {drawing.id} with {len(cutting_list_items)} cutting items")
        
        return jsonify({
            'success': True,
            'drawing_id': drawing.id,
            'status': drawing.status,
            'ocr_method': drawing.ocr_method,
            'table_markdown': ocr_result.get('table_markdown'),
            'cutting_list': [item.to_dict() for item in cutting_list_items],
            'preview_url': f'/api/drawing-analyser/{drawing.id}/preview',
            'total_pieces': sum(item.quantity for item in cutting_list_items),
            'total_area_m2': drawing._calculate_total_area() if cutting_list_items else 0
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Upload failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@drawing_bp.route('/api/drawing-analyser/<drawing_id>', methods=['GET'])
@require_module('cutting_list_generator')
def get_drawing(drawing_id):
    """Get drawing details and cutting list"""
    tenant_id = request.headers.get('X-Tenant-ID')
    
    drawing = Drawing.query.filter_by(
        id=drawing_id,
        tenant_id=tenant_id
    ).first()
    
    if not drawing:
        return jsonify({'error': 'Drawing not found'}), 404
    
    return jsonify(drawing.to_dict(include_cutting_list=True))


@drawing_bp.route('/api/drawing-analyser', methods=['GET'])
@require_module('cutting_list_generator')
def list_drawings():
    """List all drawings for tenant"""
    tenant_id = request.headers.get('X-Tenant-ID')
    
    customer_id = request.args.get('customer_id')
    job_id = request.args.get('job_id')
    project_id = request.args.get('project_id')
    status = request.args.get('status')
    limit = int(request.args.get('limit', 50))
    offset = int(request.args.get('offset', 0))
    
    query = Drawing.query.filter_by(tenant_id=tenant_id)
    
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    if job_id:
        query = query.filter_by(job_id=job_id)
    if project_id:
        query = query.filter_by(project_id=project_id)
    if status:
        query = query.filter_by(status=status)
    
    total = query.count()
    drawings = query.order_by(Drawing.created_at.desc()).limit(limit).offset(offset).all()
    
    return jsonify({
        'total': total,
        'limit': limit,
        'offset': offset,
        'drawings': [d.to_dict() for d in drawings]
    })


@drawing_bp.route('/api/drawing-analyser/<drawing_id>/preview', methods=['GET'])
@require_module('cutting_list_generator')
def preview_drawing(drawing_id):
    """Get drawing image file"""
    tenant_id = request.headers.get('X-Tenant-ID')
    
    drawing = Drawing.query.filter_by(
        id=drawing_id,
        tenant_id=tenant_id
    ).first()
    
    if not drawing:
        return jsonify({'error': 'Drawing not found'}), 404
    
    if not os.path.exists(drawing.file_path):
        return jsonify({'error': 'File not found'}), 404
    
    return send_file(drawing.file_path)


@drawing_bp.route('/api/drawing-analyser/<drawing_id>', methods=['DELETE'])
@require_module('cutting_list_generator')
def delete_drawing(drawing_id):
    """Delete drawing and associated cutting list"""
    tenant_id = request.headers.get('X-Tenant-ID')
    
    drawing = Drawing.query.filter_by(
        id=drawing_id,
        tenant_id=tenant_id
    ).first()
    
    if not drawing:
        return jsonify({'error': 'Drawing not found'}), 404
    
    # Delete file
    if os.path.exists(drawing.file_path):
        try:
            os.remove(drawing.file_path)
        except Exception as e:
            logger.warning(f"Failed to delete file {drawing.file_path}: {e}")
    
    # Delete from database (cascade will delete cutting list items)
    db.session.delete(drawing)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Drawing deleted'})