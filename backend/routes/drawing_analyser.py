"""
Drawing Analyser Routes
Module: cutting_list_generator (interior design add-on)

This module does NOT map to the core StreemLyne_MT schema tables.
Drawing and CuttingList are module-specific models stored separately.

Schema alignment changes:
  - db import corrected:   `from database import db`  (was models.core)
  - Tenant lookup aligned: uses Tenant_Master via TenantMaster model
    and checks Tenant_Module_Mapping for module access rather than a
    JSON `enabled_modules` column (which doesn't exist in the new schema).
  - All URL prefixes now use /api/drawing-analyser consistently.
  - Replaced bare `except:` with typed exception handling.
  - Added Blueprint url_prefix so routes don't need the prefix hard-coded.
"""

import os
import uuid
import logging
from datetime import datetime
from functools import wraps

from flask import Blueprint, request, jsonify, send_file, abort
from werkzeug.utils import secure_filename

from database import db
from middleware import auth_required

# Module-specific models — not part of the core schema
from models.modules.interior_design import Drawing, CuttingList

logger = logging.getLogger(__name__)

drawing_bp = Blueprint('drawing_analyser', __name__, url_prefix='/api/drawing-analyser')

UPLOAD_FOLDER = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'uploads', 'drawings'
)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

def _allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _parse_dimension(value):
    """Extract a numeric dimension from a string like '900', '900mm', or 'N/A'."""
    if not value or str(value).strip() == 'N/A':
        return None
    numeric_str = ''.join(c for c in str(value) if c.isdigit() or c == '.')
    if not numeric_str:
        return None
    try:
        return float(numeric_str) if '.' in numeric_str else int(numeric_str)
    except ValueError:
        return None


def _parse_quantity(value) -> int:
    """Extract an integer quantity; defaults to 1 on failure."""
    try:
        return int(''.join(c for c in str(value) if c.isdigit())) or 1
    except (ValueError, TypeError):
        return 1


# ─────────────────────────────────────────
# Module access middleware
# ─────────────────────────────────────────

def require_module(module_code: str):
    """
    Decorator: verifies that the requesting tenant has the given module enabled.

    Checks Tenant_Module_Mapping → Module_Master using module_code.
    Falls back to the X-Tenant-ID request header when g.tenant_id is unavailable
    (e.g. unauthenticated drawing preview endpoints).
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            from flask import g
            from models import TenantMaster, TenantModuleMapping, ModuleMaster

            tenant_id = getattr(g, 'tenant_id', None) or request.headers.get('X-Tenant-ID')
            if not tenant_id:
                return jsonify({'error': 'Tenant identification required'}), 400

            tenant = TenantMaster.query.get(int(tenant_id))
            if not tenant:
                return jsonify({'error': 'Tenant not found'}), 404

            # Verify module exists and is mapped to the tenant
            module = ModuleMaster.query.filter_by(
                module_code=module_code, is_active=True
            ).first()

            if not module:
                return jsonify({'error': f'Module {module_code!r} does not exist'}), 404

            mapping = TenantModuleMapping.query.filter_by(
                tenant_id=int(tenant_id),
                module_id=module.module_id
            ).first()

            if not mapping:
                return jsonify({
                    'error': f'Module {module_code!r} is not enabled for this tenant'
                }), 403

            return f(*args, **kwargs)
        return decorated
    return decorator


# ─────────────────────────────────────────
# Routes
# ─────────────────────────────────────────

@drawing_bp.route('/upload', methods=['POST'])
@auth_required
@require_module('cutting_list_generator')
def upload_drawing():
    """
    Upload a technical drawing and extract a cutting list via OCR.
    POST /api/drawing-analyser/upload  (multipart/form-data)
    Fields:
      file            (required)
      project_name    (optional)
      project_id      (optional)
      customer_id     (optional)
      job_id          (optional)
    """
    from flask import g
    from services.ocr_dimension_extractor import OCRDimensionExtractor

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400
    if not _allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Allowed: PNG, JPG, PDF'}), 400

    tenant_id = str(g.tenant_id)

    try:
        file_ext    = file.filename.rsplit('.', 1)[1].lower()
        unique_name = f"{uuid.uuid4()}.{file_ext}"
        file_path   = os.path.join(UPLOAD_FOLDER, unique_name)
        file.save(file_path)
        logger.info('File saved: %s', file_path)

        with open(file_path, 'rb') as fh:
            image_bytes = fh.read()

        logger.info('Starting OCR extraction …')
        ocr_result = OCRDimensionExtractor().extract_dimensions(image_bytes)
        logger.info('OCR completed using method: %s', ocr_result.get('method'))

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

        cutting_list_items = []

        if ocr_result.get('success') and ocr_result.get('table_data'):
            for row in ocr_result['table_data'][1:]:   # skip header row
                if len(row) < 7:
                    continue

                item = CuttingList(
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
                db.session.add(item)
                cutting_list_items.append(item)

        db.session.commit()
        logger.info('Drawing %s saved with %d cutting items', drawing.id, len(cutting_list_items))

        return jsonify({
            'success':        True,
            'drawing_id':     drawing.id,
            'status':         drawing.status,
            'ocr_method':     drawing.ocr_method,
            'table_markdown': ocr_result.get('table_markdown'),
            'cutting_list':   [item.to_dict() for item in cutting_list_items],
            'preview_url':    f'/api/drawing-analyser/{drawing.id}/preview',
            'total_pieces':   sum(i.quantity for i in cutting_list_items),
            'total_area_m2':  drawing._calculate_total_area() if cutting_list_items else 0,
        }), 201

    except Exception as e:
        db.session.rollback()
        logger.error('Upload failed: %s', e, exc_info=True)
        return jsonify({'error': str(e)}), 500


@drawing_bp.route('', methods=['GET'])
@auth_required
@require_module('cutting_list_generator')
def list_drawings():
    """
    List all drawings for the current tenant.
    GET /api/drawing-analyser
    Query params: customer_id, job_id, project_id, status, limit, offset
    """
    from flask import g
    tenant_id = str(g.tenant_id)

    customer_id = request.args.get('customer_id')
    job_id      = request.args.get('job_id')
    project_id  = request.args.get('project_id')
    status      = request.args.get('status')
    limit       = min(int(request.args.get('limit', 50)), 200)
    offset      = int(request.args.get('offset', 0))

    query = Drawing.query.filter_by(tenant_id=tenant_id)

    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    if job_id:
        query = query.filter_by(job_id=job_id)
    if project_id:
        query = query.filter_by(project_id=project_id)
    if status:
        query = query.filter_by(status=status)

    total    = query.count()
    drawings = query.order_by(Drawing.created_at.desc()).limit(limit).offset(offset).all()

    return jsonify({
        'total':    total,
        'limit':    limit,
        'offset':   offset,
        'drawings': [d.to_dict() for d in drawings],
    }), 200


@drawing_bp.route('/<string:drawing_id>', methods=['GET'])
@auth_required
@require_module('cutting_list_generator')
def get_drawing(drawing_id: str):
    """
    Get drawing details and its cutting list.
    GET /api/drawing-analyser/<drawing_id>
    """
    from flask import g
    drawing = Drawing.query.filter_by(
        id=drawing_id, tenant_id=str(g.tenant_id)
    ).first()
    if not drawing:
        abort(404, description='Drawing not found')
    return jsonify(drawing.to_dict(include_cutting_list=True)), 200


@drawing_bp.route('/<string:drawing_id>/preview', methods=['GET'])
@auth_required
@require_module('cutting_list_generator')
def preview_drawing(drawing_id: str):
    """
    Serve the original drawing image.
    GET /api/drawing-analyser/<drawing_id>/preview
    """
    from flask import g
    drawing = Drawing.query.filter_by(
        id=drawing_id, tenant_id=str(g.tenant_id)
    ).first()
    if not drawing:
        abort(404, description='Drawing not found')
    if not os.path.exists(drawing.file_path):
        abort(404, description='File not found on disk')
    return send_file(drawing.file_path)


@drawing_bp.route('/<string:drawing_id>', methods=['DELETE'])
@auth_required
@require_module('cutting_list_generator')
def delete_drawing(drawing_id: str):
    """
    Delete a drawing, its cutting list items, and the stored file.
    DELETE /api/drawing-analyser/<drawing_id>
    """
    from flask import g
    drawing = Drawing.query.filter_by(
        id=drawing_id, tenant_id=str(g.tenant_id)
    ).first()
    if not drawing:
        abort(404, description='Drawing not found')

    if os.path.exists(drawing.file_path):
        try:
            os.remove(drawing.file_path)
        except OSError as e:
            logger.warning('Could not delete file %s: %s', drawing.file_path, e)

    # CuttingList rows are deleted via DB cascade on drawing FK
    db.session.delete(drawing)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Drawing deleted'}), 200