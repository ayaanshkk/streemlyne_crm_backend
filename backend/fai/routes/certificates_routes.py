import os
import uuid
import requests
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from .auth_helpers import token_required
from urllib.parse import unquote


certificates_bp = Blueprint('certificates', __name__)

VERCEL_BLOB_API = "https://blob.vercel-storage.com"


def get_blob_token():
    token = os.environ.get("BLOB_READ_WRITE_TOKEN")
    if not token:
        raise ValueError("BLOB_READ_WRITE_TOKEN environment variable not set")
    return token


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: POST /clients/<client_id>/certificates/upload
# ═════════════════════════════════════════════════════════════════════════════
@certificates_bp.route('/clients/<int:client_id>/certificates/upload', methods=['POST', 'OPTIONS'])
@token_required
def upload_certificate(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'No file selected'}), 400

        # Validate file type
        allowed_types = {
            'application/pdf':  'pdf',
            'image/jpeg':       'image',
            'image/jpg':        'image',
            'image/png':        'image',
        }
        file_type = allowed_types.get(file.content_type)
        if not file_type:
            return jsonify({'error': 'Invalid file type. Only PDF and images allowed.'}), 400

        # Validate file size (10MB max)
        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)
        if file_size > 10 * 1024 * 1024:
            return jsonify({'error': 'File size must be less than 10MB'}), 400

        # Build unique blob path
        ext          = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'bin'
        safe_name    = file.filename.rsplit('.', 1)[0].replace(' ', '_')
        unique_name  = f"certificates/client_{client_id}/{safe_name}_{uuid.uuid4().hex[:8]}.{ext}"
        original_name = file.filename
        upload_date  = datetime.utcnow().date().isoformat()

        # Upload to Vercel Blob
        token      = get_blob_token()
        file_bytes = file.read()

        blob_response = requests.put(
            f"{VERCEL_BLOB_API}/{unique_name}",
            headers={
                "Authorization":  f"Bearer {token}",
                "Content-Type":   file.content_type,
                "x-content-type": file.content_type,
            },
            data=file_bytes,
        )

        if not blob_response.ok:
            current_app.logger.error(f"Blob upload failed: {blob_response.text}")
            return jsonify({'error': 'Failed to upload to storage'}), 500

        blob_data = blob_response.json()
        file_url  = blob_data.get('url') or blob_data.get('downloadUrl')

        if not file_url:
            return jsonify({'error': 'No URL returned from storage'}), 500

        current_app.logger.info(f"✅ Certificate uploaded for client {client_id}: {unique_name}")

        return jsonify({
            'success':     True,
            'id':          unique_name,
            'file_name':   original_name,
            'file_url':    file_url,
            'file_type':   file_type,
            'upload_date': upload_date,
        }), 201

    except ValueError as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        current_app.logger.error(f"❌ Certificate upload error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /clients/<client_id>/certificates
# ═════════════════════════════════════════════════════════════════════════════
@certificates_bp.route('/clients/<int:client_id>/certificates', methods=['GET', 'OPTIONS'])
@token_required
def get_certificates(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        token  = get_blob_token()
        prefix = f"certificates/client_{client_id}/"

        list_response = requests.get(
            f"{VERCEL_BLOB_API}",
            headers={"Authorization": f"Bearer {token}"},
            params={"prefix": prefix, "limit": 100},
        )

        if not list_response.ok:
            current_app.logger.error(f"Blob list failed: {list_response.text}")
            return jsonify([]), 200

        blobs = list_response.json().get('blobs', [])

        result = []
        for blob in blobs:
            raw_name    = blob.get('pathname', '').split('/')[-1]
            ct          = blob.get('contentType', '')
            file_type   = 'pdf' if 'pdf' in ct else 'image'
            uploaded_at = blob.get('uploadedAt', '')

            result.append({
                "id":          blob.get('pathname'),
                "file_name":   raw_name,
                "file_url":    blob.get('url'),
                "file_type":   file_type,
                "upload_date": uploaded_at[:10] if uploaded_at else '',
                "uploaded_by": None,
            })

        return jsonify(result), 200

    except ValueError as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        current_app.logger.error(f"❌ Error listing certificates: {e}")
        return jsonify({'error': str(e)}), 500


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: DELETE /clients/<client_id>/certificates/<path:cert_id>
# ═════════════════════════════════════════════════════════════════════════════
@certificates_bp.route('/clients/<int:client_id>/certificates/<path:filename>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_certificate(client_id, filename):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        token    = get_blob_token()
        filename = unquote(filename)
        cert_id  = f"certificates/client_{client_id}/{filename}"

        current_app.logger.info(f"🔍 Trying to delete cert_id: {cert_id}")

        # List all blobs for this client to find the matching one
        list_response = requests.get(
            f"{VERCEL_BLOB_API}",
            headers={"Authorization": f"Bearer {token}"},
            params={"prefix": f"certificates/client_{client_id}/", "limit": 100},
        )

        current_app.logger.info(f"List response status: {list_response.status_code}")

        file_url = None
        if list_response.ok:
            blobs = list_response.json().get('blobs', [])
            current_app.logger.info(f"Found {len(blobs)} blobs: {[b.get('pathname') for b in blobs]}")
            for blob in blobs:
                if blob.get('pathname') == cert_id:
                    file_url = blob.get('url')
                    break

        if not file_url:
            current_app.logger.error(f"❌ No blob found matching pathname: {cert_id}")
            return jsonify({'error': 'Certificate not found in storage'}), 404

        # Delete from Vercel Blob
        del_response = requests.post(
            f"{VERCEL_BLOB_API}/delete",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            json={"urls": [file_url]},
        )

        if not del_response.ok:
            current_app.logger.error(f"Blob delete failed: {del_response.text}")
            return jsonify({'error': 'Failed to delete from storage'}), 500

        current_app.logger.info(f"✅ Certificate deleted: {cert_id}")
        return jsonify({'success': True, 'message': 'Certificate deleted'}), 200

    except ValueError as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        current_app.logger.error(f"❌ Error deleting certificate: {e}")
        return jsonify({'error': str(e)}), 500
