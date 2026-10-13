"""
backend/routes/contact_files_routes.py

File management for a Contact (streemLyne_mt_dev2.Contact_Master), mirroring
client_files_routes.py but scoped to contacts instead of companies/clients,
and running on the dev DB connection (SessionLocal) like contact_routes.py
and company_routes.py.

Endpoints:
  POST   /contacts/<contact_id>/files/upload   multipart: file, type
  GET    /contacts/<contact_id>/files          optional ?type=document
  DELETE /contacts/files/<file_id>
"""
from flask import Blueprint, request, jsonify, current_app
from ..services.storage_service import (
    upload_file,
    delete_file,
    StorageError,
)
from sqlalchemy import text
from datetime import datetime

from .auth_helpers import token_required
from ..db import SessionLocal

contact_files_bp = Blueprint('contact_files', __name__)

SCHEMA = "streemLyne_mt_dev2"

# Kept deliberately smaller than client_files_routes.py's VALID_TYPES —
# batch_* / trainee_* types belong to a training batch (Training_Master),
# not a contact. Widen this if a real use case shows up.
VALID_TYPES = {"document", "certificate", "photo"}


def serialize_file(row):
    return {
        "id": row.id,
        "contact_id": row.contact_id,
        "file_name": row.file_name,
        "file_url": row.file_url,
        "file_type": row.file_type,
        "mime_type": row.mime_type,
        "file_size": row.file_size,
        "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
    }


def get_tenant_contact(session, contact_id, tenant_id):
    return session.execute(
        text(f'SELECT contact_id FROM "{SCHEMA}"."Contact_Master" '
             f'WHERE contact_id = :cid AND tenant_id = :tid AND is_active = true'),
        {"cid": contact_id, "tid": tenant_id}
    ).fetchone()


@contact_files_bp.route('/contacts/<int:contact_id>/files/upload', methods=['POST', 'OPTIONS'])
@token_required
def upload_contact_file(contact_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        contact = get_tenant_contact(session, contact_id, request.current_user.tenant_id)
        if not contact:
            return jsonify({"error": "Contact not found"}), 404

        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        file_type = request.form.get("type", "document")
        if file_type not in VALID_TYPES:
            return jsonify({"error": f"Invalid type. Must be one of {sorted(VALID_TYPES)}"}), 400

        # storage_service.upload_file() is entity-agnostic — it just needs
        # an id to namespace the storage path, same as client_files_routes.py.
        uploaded = upload_file(file, contact_id, file_type)

        result = session.execute(
            text(f"""
                INSERT INTO "{SCHEMA}"."Contact_Files"
                    (contact_id, file_name, storage_path, file_url, file_type,
                     mime_type, file_size, uploaded_by, uploaded_at)
                VALUES
                    (:contact_id, :file_name, :storage_path, :file_url, :file_type,
                     :mime_type, :file_size, :uploaded_by, :uploaded_at)
                RETURNING id, contact_id, file_name, file_url, file_type,
                          mime_type, file_size, uploaded_at
            """),
            {
                "contact_id": contact_id,
                "file_name": uploaded["file_name"],
                "storage_path": uploaded["storage_path"],
                "file_url": uploaded["file_url"],
                "file_type": file_type,
                "mime_type": uploaded["mime_type"],
                "file_size": uploaded["file_size"],
                "uploaded_by": getattr(request.current_user, "id", None),
                "uploaded_at": datetime.utcnow(),
            }
        )
        row = result.fetchone()
        session.commit()

        current_app.logger.info(
            f"✅ Uploaded {file_type} for contact {contact_id}: {uploaded['file_name']}"
        )
        return jsonify(serialize_file(row)), 201

    except StorageError as e:
        session.rollback()
        current_app.logger.error(f"❌ Storage error: {e}")
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error uploading contact file: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


@contact_files_bp.route('/contacts/<int:contact_id>/files', methods=['GET', 'OPTIONS'])
@token_required
def list_contact_files(contact_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        contact = get_tenant_contact(session, contact_id, request.current_user.tenant_id)
        if not contact:
            return jsonify({"error": "Contact not found"}), 404

        file_type = request.args.get('type')

        query = f'SELECT * FROM "{SCHEMA}"."Contact_Files" WHERE contact_id = :cid'
        params = {"cid": contact_id}

        if file_type:
            if file_type not in VALID_TYPES:
                return jsonify({"error": "Invalid type filter"}), 400
            query += ' AND file_type = :ftype'
            params["ftype"] = file_type

        query += ' ORDER BY uploaded_at DESC'

        rows = session.execute(text(query), params).fetchall()
        return jsonify([serialize_file(r) for r in rows]), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Error listing files for contact {contact_id}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


@contact_files_bp.route('/contacts/files/<int:file_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_contact_file(file_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        row = session.execute(
            text(f"""
                SELECT cf.*
                FROM "{SCHEMA}"."Contact_Files" cf
                JOIN "{SCHEMA}"."Contact_Master" cm ON cm.contact_id = cf.contact_id
                WHERE cf.id = :fid AND cm.tenant_id = :tid
            """),
            {"fid": file_id, "tid": request.current_user.tenant_id}
        ).fetchone()

        if not row:
            return jsonify({"error": "File not found"}), 404

        try:
            delete_file(row.storage_path)
        except StorageError as e:
            current_app.logger.warning(
                f"⚠️ Storage delete failed for {row.storage_path}, removing DB record anyway: {e}"
            )

        session.execute(
            text(f'DELETE FROM "{SCHEMA}"."Contact_Files" WHERE id = :fid'),
            {"fid": file_id}
        )
        session.commit()

        current_app.logger.info(f"✅ Deleted contact file {file_id} ({row.file_name})")
        return jsonify({"success": True, "message": "File deleted"}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error deleting contact file {file_id}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()
