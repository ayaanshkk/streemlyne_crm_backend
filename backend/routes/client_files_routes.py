"""
backend/routes/client_files_routes.py

Unified file management for a company: certificates, attached documents,
and quotation files — all stored in Supabase Storage, all tracked in one
Client_Files table.

Endpoints:
  POST   /clients/<client_id>/files/upload   multipart: file, type
  GET    /clients/<client_id>/files          optional ?type=certificate
  DELETE /clients/files/<file_id>
"""
from flask import Blueprint, request, jsonify, current_app
from services.storage_service import (
    upload_file,
    delete_file,
    StorageError,
)
from sqlalchemy import text
from datetime import datetime

from routes.cc_compat import token_required
from routes.cc_compat import SessionLocal

client_files_bp = Blueprint('client_files', __name__)

from routes.cc_compat import SCHEMA
# Industry-neutral file categories. (The FAI-only trainee_* / batch_* types
# were removed; existing rows with those types are left untouched in the DB.)
VALID_TYPES = {"certificate", "document", "quotation", "contract", "invoice", "other"}


def serialize_file(row):
    return {
        "id": row.id,
        "client_id": row.client_id,
        "file_name": row.file_name,
        "file_url": row.file_url,
        "file_type": row.file_type,
        "mime_type": row.mime_type,
        "file_size": row.file_size,
        "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
    }


def get_tenant_client(session, client_id, tenant_id):
    return session.execute(
        text(f'SELECT client_id FROM "{SCHEMA}"."Client_Master" WHERE client_id = :cid AND tenant_id = :tid'),
        {"cid": client_id, "tid": tenant_id}
    ).fetchone()


@client_files_bp.route('/clients/<int:client_id>/files/upload', methods=['POST', 'OPTIONS'])
@token_required
def upload_client_file(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        client = get_tenant_client(session, client_id, request.current_user.tenant_id)
        if not client:
            return jsonify({"error": "Client not found"}), 404

        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        file_type = request.form.get("type", "document")
        if file_type not in VALID_TYPES:
            return jsonify({"error": f"Invalid type. Must be one of {sorted(VALID_TYPES)}"}), 400

        uploaded = upload_file(file, client_id, file_type)

        result = session.execute(
            text(f"""
                INSERT INTO "{SCHEMA}"."Client_Files"
                    (client_id, file_name, storage_path, file_url, file_type,
                     mime_type, file_size, uploaded_by, uploaded_at)
                VALUES
                    (:client_id, :file_name, :storage_path, :file_url, :file_type,
                     :mime_type, :file_size, :uploaded_by, :uploaded_at)
                RETURNING id, client_id, file_name, file_url, file_type,
                          mime_type, file_size, uploaded_at
            """),
            {
                "client_id": client_id,
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
            f"✅ Uploaded {file_type} for client {client_id}: {uploaded['file_name']}"
        )
        return jsonify(serialize_file(row)), 201

    except StorageError as e:
        session.rollback()
        current_app.logger.error(f"❌ Storage error: {e}")
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error uploading file: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


@client_files_bp.route('/clients/<int:client_id>/files', methods=['GET', 'OPTIONS'])
@token_required
def list_client_files(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        client = get_tenant_client(session, client_id, request.current_user.tenant_id)
        if not client:
            return jsonify({"error": "Client not found"}), 404

        file_type = request.args.get('type')

        query = f'SELECT * FROM "{SCHEMA}"."Client_Files" WHERE client_id = :cid'
        params = {"cid": client_id}

        if file_type:
            if file_type not in VALID_TYPES:
                return jsonify({"error": "Invalid type filter"}), 400
            query += ' AND file_type = :ftype'
            params["ftype"] = file_type

        query += ' ORDER BY uploaded_at DESC'

        rows = session.execute(text(query), params).fetchall()
        return jsonify([serialize_file(r) for r in rows]), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Error listing files for client {client_id}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


@client_files_bp.route('/clients/files/<int:file_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_client_file(file_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        row = session.execute(
            text(f"""
                SELECT cf.*
                FROM "{SCHEMA}"."Client_Files" cf
                JOIN "{SCHEMA}"."Client_Master" cm ON cm.client_id = cf.client_id
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
            text(f'DELETE FROM "{SCHEMA}"."Client_Files" WHERE id = :fid'),
            {"fid": file_id}
        )
        session.commit()

        current_app.logger.info(f"✅ Deleted file {file_id} ({row.file_name})")
        return jsonify({"success": True, "message": "File deleted"}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error deleting file {file_id}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()
