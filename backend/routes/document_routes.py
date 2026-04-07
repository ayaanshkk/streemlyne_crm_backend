"""
Document Routes
Handles: Case_Documents, Customer_Documents

Schema alignment (StreemLyne_MT):
  Case_Documents:
    id (PK), opportunity_id (FK→Opportunity_Details, NOT NULL),
    client_id (FK→Client_Master, NOT NULL), tenant_id (NOT NULL),
    uploaded_by (varchar, NOT NULL), document_type (varchar, nullable),
    file_name (varchar, NOT NULL), blob_url (text, NOT NULL), created_at

  Customer_Documents:
    id (PK), client_id (NOT NULL), opportunity_id (nullable),
    file_url (text, NOT NULL), file_name (text, NOT NULL), uploaded_at

Tenant scoping:
  Case_Documents    — has tenant_id directly; all queries filter on g.tenant_id ✅ (unchanged)
  Customer_Documents — no tenant_id column; scope via:
    client_id → Client_Master.tenant_id
"""

from flask import Blueprint, request, jsonify, g, send_file, current_app, abort
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
from database import db
from models import CaseDocuments, CustomerDocuments, ClientMaster
from middleware import auth_required, permission_required
import os
import uuid

document_bp = Blueprint('document', __name__, url_prefix='/documents')

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'docx', 'xlsx', 'csv', 'txt'}


def _allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _upload_folder() -> str:
    folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    os.makedirs(folder, exist_ok=True)
    return folder


def _save_file(file) -> tuple[str, str]:
    """
    Save an uploaded FileStorage object to the upload folder.
    Returns (safe_original_name, unique_stored_name).
    """
    safe_name = secure_filename(file.filename)
    unique_name = f"{uuid.uuid4()}_{safe_name}"
    file_path = os.path.join(_upload_folder(), unique_name)
    file.save(file_path)
    return safe_name, unique_name


def _try_remove(path: str) -> None:
    """Silently attempt to remove a file."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


# ─────────────────────────────────────────
# Case Documents  (staff-facing)
# Already correctly scoped via Case_Documents.tenant_id — no changes needed.
# ─────────────────────────────────────────

@document_bp.route('/case', methods=['GET'])
@auth_required
def list_case_documents():
    """
    List case documents scoped to the current tenant.
    GET /api/documents/case
    Query params:
      opportunity_id  – filter by opportunity
      client_id       – filter by client
      document_type   – filter by type string
    """
    query = CaseDocuments.query.filter_by(tenant_id=g.tenant_id)

    opportunity_id = request.args.get('opportunity_id', type=int)
    client_id      = request.args.get('client_id',      type=int)
    doc_type       = request.args.get('document_type')

    if opportunity_id:
        query = query.filter_by(opportunity_id=opportunity_id)
    if client_id:
        query = query.filter_by(client_id=client_id)
    if doc_type:
        query = query.filter_by(document_type=doc_type)

    docs = query.order_by(CaseDocuments.created_at.desc()).all()
    return jsonify([_case_doc_dict(d) for d in docs]), 200


@document_bp.route('/case', methods=['POST'])
@auth_required
# @permission_required('document.upload')
def upload_case_document():
    """
    Upload a case document (staff only).
    POST /api/documents/case   (multipart/form-data)
    Fields:
      file             (required)
      opportunity_id   (required, FK → Opportunity_Details)
      client_id        (required, FK → Client_Master)
      document_type    (optional)
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400
    if not _allowed_file(file.filename):
        return jsonify({
            'error': f'File type not allowed. Permitted: {", ".join(sorted(ALLOWED_EXTENSIONS))}'
        }), 400

    opportunity_id = request.form.get('opportunity_id', type=int)
    client_id      = request.form.get('client_id',      type=int)
    document_type  = request.form.get('document_type')

    if not opportunity_id or not client_id:
        return jsonify({'error': 'opportunity_id and client_id are required'}), 400

    try:
        safe_name, unique_name = _save_file(file)
        # blob_url: in production swap for Azure Blob / S3 signed URL
        blob_url = f"/api/documents/case/download/{unique_name}"

        doc = CaseDocuments(
            opportunity_id=opportunity_id,
            client_id=client_id,
            tenant_id=g.tenant_id,
            # uploaded_by is NOT NULL in schema — use employee name if available
            uploaded_by=getattr(g, 'employee_name', None) or str(g.user_id),
            document_type=document_type,
            file_name=safe_name,
            blob_url=blob_url
        )
        db.session.add(doc)
        db.session.commit()

    except IntegrityError:
        db.session.rollback()
        _try_remove(os.path.join(_upload_folder(), unique_name))
        return jsonify({
            'error': 'Invalid opportunity_id or client_id — check FK references'
        }), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

    return jsonify(_case_doc_dict(doc)), 201


@document_bp.route('/case/<int:doc_id>', methods=['GET'])
@auth_required
def get_case_document(doc_id: int):
    """
    Retrieve metadata for a single case document.
    GET /api/documents/case/<doc_id>
    """
    doc = CaseDocuments.query.filter_by(id=doc_id, tenant_id=g.tenant_id).first()
    if not doc:
        abort(404, description='Document not found')
    return jsonify(_case_doc_dict(doc)), 200


@document_bp.route('/case/<int:doc_id>', methods=['DELETE'])
@auth_required
# @permission_required('document.delete')
def delete_case_document(doc_id: int):
    """
    Delete a case document and its stored file.
    DELETE /api/documents/case/<doc_id>
    """
    doc = CaseDocuments.query.filter_by(id=doc_id, tenant_id=g.tenant_id).first()
    if not doc:
        abort(404, description='Document not found')

    _try_remove(os.path.join(_upload_folder(), os.path.basename(doc.blob_url)))

    db.session.delete(doc)
    db.session.commit()
    return jsonify({'message': 'Document deleted'}), 200


@document_bp.route('/case/download/<path:filename>')
@auth_required
def download_case_document(filename: str):
    """
    Serve a stored case document file.
    GET /api/documents/case/download/<filename>
    """
    file_path = os.path.join(_upload_folder(), secure_filename(filename))
    if not os.path.exists(file_path):
        abort(404, description='File not found')
    return send_file(file_path, as_attachment=True)


# ─────────────────────────────────────────
# Customer Documents  (client portal-facing)
# ─────────────────────────────────────────

@document_bp.route('/customer', methods=['GET'])
@auth_required
def list_customer_documents():
    """
    List documents uploaded by customers, scoped to the current tenant.
    GET /api/documents/customer
    Query params:
      client_id      – filter by client
      opportunity_id – filter by opportunity

    Tenant isolation: CustomerDocuments has no tenant_id column.
    Scope via: client_id → Client_Master.tenant_id
    """
    # Subquery: client_ids that belong to the current tenant
    tenant_client_ids = (
        db.session.query(ClientMaster.client_id)
        .filter(ClientMaster.tenant_id == g.tenant_id)
        .subquery()
    )

    query = CustomerDocuments.query.filter(
        CustomerDocuments.client_id.in_(tenant_client_ids)
    )

    client_id      = request.args.get('client_id',      type=int)
    opportunity_id = request.args.get('opportunity_id', type=int)

    if client_id:
        query = query.filter(CustomerDocuments.client_id == client_id)
    if opportunity_id:
        query = query.filter(CustomerDocuments.opportunity_id == opportunity_id)

    docs = query.order_by(CustomerDocuments.uploaded_at.desc()).all()
    return jsonify([_customer_doc_dict(d) for d in docs]), 200


@document_bp.route('/customer', methods=['POST'])
@auth_required
# @permission_required('document.upload')
def upload_customer_document():
    """
    Upload a customer document (requires staff JWT).
    POST /api/documents/customer   (multipart/form-data)
    Fields:
      file            (required)
      client_id       (required, FK → Client_Master — must belong to current tenant)
      opportunity_id  (optional, FK → Opportunity_Details)

    Previously unauthenticated — @auth_required and tenant ownership check added.
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400
    if not _allowed_file(file.filename):
        return jsonify({
            'error': f'File type not allowed. Permitted: {", ".join(sorted(ALLOWED_EXTENSIONS))}'
        }), 400

    client_id = request.form.get('client_id', type=int)
    if not client_id:
        return jsonify({'error': 'client_id is required'}), 400

    # Validate client_id belongs to current tenant
    client = ClientMaster.query.filter_by(
        client_id=client_id, tenant_id=g.tenant_id
    ).first()
    if not client:
        return jsonify({'error': 'Invalid client_id — not found for this tenant'}), 400

    opportunity_id = request.form.get('opportunity_id', type=int)

    try:
        safe_name, unique_name = _save_file(file)
        file_url = f"/api/documents/customer/download/{unique_name}"

        doc = CustomerDocuments(
            client_id=client_id,
            opportunity_id=opportunity_id,   # nullable in schema — fine to be None
            file_url=file_url,
            file_name=safe_name
        )
        db.session.add(doc)
        db.session.commit()

    except IntegrityError:
        db.session.rollback()
        _try_remove(os.path.join(_upload_folder(), unique_name))
        return jsonify({'error': 'Invalid client_id or opportunity_id'}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

    return jsonify(_customer_doc_dict(doc)), 201


@document_bp.route('/customer/<int:doc_id>', methods=['DELETE'])
@auth_required
# @permission_required('document.delete')
def delete_customer_document(doc_id: int):
    """
    Delete a customer-uploaded document and its stored file.
    DELETE /api/documents/customer/<doc_id>

    Tenant isolation: join through Client_Master to verify ownership before deleting.
    Replaces unscoped query.get() which allowed cross-tenant deletion.
    """
    # Subquery: client_ids that belong to the current tenant
    tenant_client_ids = (
        db.session.query(ClientMaster.client_id)
        .filter(ClientMaster.tenant_id == g.tenant_id)
        .subquery()
    )
    doc = CustomerDocuments.query.filter(
        CustomerDocuments.id == doc_id,
        CustomerDocuments.client_id.in_(tenant_client_ids)
    ).first()
    if not doc:
        abort(404, description='Document not found')

    _try_remove(os.path.join(_upload_folder(), os.path.basename(doc.file_url)))

    db.session.delete(doc)
    db.session.commit()
    return jsonify({'message': 'Document deleted'}), 200


@document_bp.route('/customer/download/<path:filename>')
def download_customer_document(filename: str):
    """
    Serve a customer-uploaded document file (no auth — link is unguessable by design).
    GET /api/documents/customer/download/<filename>
    """
    file_path = os.path.join(_upload_folder(), secure_filename(filename))
    if not os.path.exists(file_path):
        abort(404, description='File not found')
    return send_file(file_path, as_attachment=True)


# ─────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────

def _case_doc_dict(d: CaseDocuments) -> dict:
    return {
        'id':              d.id,
        'opportunity_id':  d.opportunity_id,
        'client_id':       d.client_id,
        'tenant_id':       d.tenant_id,
        'uploaded_by':     d.uploaded_by,
        'document_type':   d.document_type,
        'file_name':       d.file_name,
        'blob_url':        d.blob_url,
        'created_at':      d.created_at.isoformat() if d.created_at else None,
    }


def _customer_doc_dict(d: CustomerDocuments) -> dict:
    return {
        'id':             d.id,
        'client_id':      d.client_id,
        'opportunity_id': d.opportunity_id,
        'file_name':      d.file_name,
        'file_url':       d.file_url,
        'uploaded_at':    d.uploaded_at.isoformat() if d.uploaded_at else None,
    }