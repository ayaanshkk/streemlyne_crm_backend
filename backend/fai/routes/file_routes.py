import os
import uuid
import requests
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from datetime import datetime
from .auth_helpers import token_required

file_bp = Blueprint("file_routes", __name__)


# ═════════════════════════════════════════════════════════════════════════════
# VERCEL BLOB CONFIG
# ═════════════════════════════════════════════════════════════════════════════

VERCEL_BLOB_API = "https://blob.vercel-storage.com"

ALLOWED_EXTENSIONS = {
    "pdf", "png", "jpg", "jpeg", "gif", "webp",
    "xlsx", "xls", "csv", "doc", "docx", "txt", "zip"
}


def get_blob_token():
    token = os.getenv("BLOB_READ_WRITE_TOKEN")
    if not token:
        raise ValueError("BLOB_READ_WRITE_TOKEN is not set in environment variables.")
    return token


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ─────────────────────────────────────────────
# HELPER: Upload a file object to Vercel Blob
# Returns (url, pathname)
# ─────────────────────────────────────────────
def upload_to_blob(file, filename, folder):
    """
    Upload a file to Vercel Blob.
    Vercel Blob uses a flat namespace — folder is prepended to filename as pathname.
    Returns (url, pathname).
    """
    token    = get_blob_token()
    pathname = f"{folder}/{filename}"

    file.seek(0)
    file_bytes = file.read()

    # Determine content type
    ext = filename.rsplit(".", 1)[-1].lower()
    content_type_map = {
        "pdf":  "application/pdf",
        "png":  "image/png",
        "jpg":  "image/jpeg",
        "jpeg": "image/jpeg",
        "gif":  "image/gif",
        "webp": "image/webp",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls":  "application/vnd.ms-excel",
        "csv":  "text/csv",
        "doc":  "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt":  "text/plain",
        "zip":  "application/zip",
    }
    content_type = content_type_map.get(ext, "application/octet-stream")

    response = requests.put(
        f"{VERCEL_BLOB_API}/{pathname}",
        data=file_bytes,
        headers={
            "Authorization":   f"Bearer {token}",
            "Content-Type":    content_type,
            "x-api-version":   "7",
            # Allow overwrite by default — set to '1' to prevent
            "x-add-random-suffix": "1",
        }
    )

    if response.status_code not in (200, 201):
        raise Exception(f"Vercel Blob upload failed: {response.status_code} {response.text}")

    blob = response.json()
    return blob["url"], blob["pathname"]


# ─────────────────────────────────────────────
# HELPER: Delete a file from Vercel Blob by URL
# ─────────────────────────────────────────────
def delete_from_blob(url):
    """
    Delete a blob by its URL.
    Vercel Blob delete endpoint accepts a list of URLs.
    """
    token = get_blob_token()

    response = requests.delete(
        f"{VERCEL_BLOB_API}/delete",
        json={"urls": [url]},
        headers={
            "Authorization": f"Bearer {token}",
            "x-api-version":  "7",
        }
    )

    if response.status_code not in (200, 204):
        current_app.logger.error(f"Blob delete failed: {response.status_code} {response.text}")
        return False

    return True


# ─────────────────────────────────────────────
# HELPER: List files in a Vercel Blob prefix
# ─────────────────────────────────────────────
def list_blobs(prefix):
    """
    List all blobs under a given prefix (folder path).
    Handles pagination automatically.
    """
    token  = get_blob_token()
    files  = []
    cursor = None

    while True:
        params = {"prefix": prefix, "limit": 1000}
        if cursor:
            params["cursor"] = cursor

        response = requests.get(
            f"{VERCEL_BLOB_API}",
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "x-api-version":  "7",
            }
        )

        if response.status_code != 200:
            raise Exception(f"Vercel Blob list failed: {response.status_code} {response.text}")

        data   = response.json()
        blobs  = data.get("blobs", [])
        files += blobs

        if not data.get("hasMore"):
            break
        cursor = data.get("cursor")

    return files


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: POST /files/upload
# ═════════════════════════════════════════════════════════════════════════════
@file_bp.route("/files/upload", methods=["POST", "OPTIONS"])
@token_required
def upload_file():
    if request.method == "OPTIONS":
        return jsonify({}), 200

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]

    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed"}), 400

    filename        = secure_filename(file.filename)
    unique_filename = f"{uuid.uuid4()}_{filename}"

    # Resolve folder — use client_id (new schema) or fall back to legacy customer_id
    client_id = request.form.get("client_id") or request.form.get("customer_id")
    folder    = request.form.get("folder", "streemLyne/general")

    if client_id:
        folder = f"streemLyne/clients/{client_id}"

    try:
        url, pathname = upload_to_blob(file, unique_filename, folder)
    except Exception as e:
        current_app.logger.error(f"❌ Blob upload error: {e}")
        return jsonify({"error": str(e)}), 500

    uploaded_by = getattr(getattr(request, "current_user", None), "employee_name", "System")

    current_app.logger.info(f"✅ File uploaded: {pathname} by {uploaded_by}")

    return jsonify({
        "success":     True,
        "file_url":    url,
        "pathname":    pathname,        # Vercel Blob identifier (use for delete)
        "public_id":   pathname,        # legacy alias — same value, kept for frontend compat
        "filename":    filename,
        "uploaded_by": uploaded_by
    }), 201


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: POST /files/delete
# ═════════════════════════════════════════════════════════════════════════════
@file_bp.route("/files/delete", methods=["POST", "OPTIONS"])
@token_required
def delete_file():
    if request.method == "OPTIONS":
        return jsonify({}), 200

    data       = request.get_json() or {}
    # Accept file_url or public_id (legacy) — Vercel Blob deletes by URL
    file_url   = data.get("file_url") or data.get("public_id")

    if not file_url:
        return jsonify({"error": "file_url or public_id required"}), 400

    # If a pathname was passed instead of a full URL, reconstruct the URL
    # Vercel Blob URLs follow: https://<store-id>.public.blob.vercel-storage.com/<pathname>
    # The delete endpoint accepts the full URL, so we pass as-is and let the API handle it
    try:
        success = delete_from_blob(file_url)
    except Exception as e:
        current_app.logger.error(f"❌ Blob delete error: {e}")
        return jsonify({"error": str(e)}), 500

    if success:
        current_app.logger.info(f"✅ File deleted: {file_url}")
        return jsonify({"success": True}), 200

    return jsonify({"error": "Delete failed"}), 500


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /files/list
# ═════════════════════════════════════════════════════════════════════════════
@file_bp.route("/files/list", methods=["GET", "OPTIONS"])
@token_required
def list_files():
    if request.method == "OPTIONS":
        return jsonify({}), 200

    # Accept client_id (new schema) or legacy customer_id
    client_id = request.args.get("client_id") or request.args.get("customer_id")
    folder    = request.args.get("folder", "streemLyne")

    if client_id:
        folder = f"streemLyne/clients/{client_id}"

    try:
        blobs = list_blobs(folder)
    except Exception as e:
        current_app.logger.error(f"❌ Blob list error: {e}")
        return jsonify({"error": str(e)}), 500

    files = []
    for blob in blobs:
        files.append({
            "public_id":   blob.get("pathname"),   # legacy alias
            "pathname":    blob.get("pathname"),
            "url":         blob.get("url"),
            "size":        blob.get("size"),
            "content_type": blob.get("contentType"),
            "created_at":  blob.get("uploadedAt"),
        })

    current_app.logger.info(f"✅ Listed {len(files)} files in {folder}")
    return jsonify({"files": files, "count": len(files)}), 200


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /files/health
# ═════════════════════════════════════════════════════════════════════════════
@file_bp.route("/files/health", methods=["GET"])
def file_system_health_check():
    try:
        get_blob_token()   # will raise if token missing
        # Lightweight check — list with limit 1 to confirm API reachability
        token    = get_blob_token()
        response = requests.get(
            f"{VERCEL_BLOB_API}",
            params={"limit": 1},
            headers={"Authorization": f"Bearer {token}", "x-api-version": "7"}
        )
        if response.status_code == 200:
            return jsonify({"status": "ok", "storage": "vercel-blob"}), 200
        return jsonify({"status": "error", "message": response.text}), 500
    except Exception as ex:
        return jsonify({"status": "error", "message": str(ex)}), 500
