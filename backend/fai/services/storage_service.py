"""
backend/services/storage_service.py

Reusable cloud file storage service backed by Supabase Storage.
Used by client_files_routes.py for certificates, documents, and quotations.

Why Supabase Storage (not local disk):
Vercel's filesystem is read-only/ephemeral outside /tmp, and /tmp is wiped
between invocations and not shared across serverless instances. Any file
saved with file.save() or open(path, 'wb') will vanish on the next request
or redeploy. Supabase Storage (or S3/R2) gives you a real, permanent,
publicly-fetchable URL that survives redeploys.

Required environment variables (set these in Vercel project settings):
    SUPABASE_URL                 e.g. https://xxxxxxxx.supabase.co
    SUPABASE_SERVICE_ROLE_KEY    service_role key (NOT the anon key — this
                                  needs write access and bypasses RLS)
    SUPABASE_STORAGE_BUCKET      bucket name, e.g. "client-files"
                                  (create this bucket in Supabase dashboard
                                  and mark it "Public" so file_url works
                                  directly without signed URLs)
"""

import os
import uuid
import requests
from werkzeug.utils import secure_filename

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "client-files")
print("SUPABASE_URL:", SUPABASE_URL)
print("SERVICE KEY EXISTS:", bool(SUPABASE_SERVICE_ROLE_KEY))
print("BUCKET:", SUPABASE_BUCKET)

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB


class StorageError(Exception):
    """Raised for any storage configuration or upload/delete failure."""
    pass


def _require_config():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise StorageError(
            "Supabase storage is not configured. Set SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY environment variables."
        )


def upload_file(file_storage, client_id: int, category: str) -> dict:
    """
    Upload a werkzeug FileStorage object to Supabase Storage.

    Args:
        file_storage: request.files['file'] (a werkzeug FileStorage)
        client_id: the client this file belongs to
        category: 'certificate' | 'document' | 'quotation'

    Returns:
        dict with storage_path, file_url, file_name, mime_type, file_size

    Raises:
        StorageError on misconfiguration or upload failure
    """
    _require_config()

    original_name = secure_filename(file_storage.filename or "file")
    ext = original_name.rsplit(".", 1)[1].lower() if "." in original_name else ""

    unique_name = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
    storage_path = f"{category}/client_{client_id}/{unique_name}"

    file_bytes = file_storage.read()
    file_storage.seek(0)
    file_size = len(file_bytes)

    if file_size > MAX_FILE_SIZE_BYTES:
        raise StorageError("File size must be less than 10MB")

    mime_type = file_storage.mimetype or "application/octet-stream"

    upload_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{storage_path}"
    

    resp = requests.post(
        upload_url,
        headers={
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": mime_type,
            "x-upsert": "true",
        },
        data=file_bytes,
        timeout=30,
    )

    if resp.status_code not in (200, 201):
        raise StorageError(f"Upload failed ({resp.status_code}): {resp.text}")

    file_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{storage_path}"

    return {
        "storage_path": storage_path,
        "file_url": file_url,
        "file_name": original_name,
        "mime_type": mime_type,
        "file_size": file_size,
    }


def delete_file(storage_path: str) -> None:
    """Delete a file from Supabase Storage by its storage_path."""
    _require_config()

    delete_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{storage_path}"

    resp = requests.delete(
        delete_url,
        headers={"Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"},
        timeout=30,
    )

    # Supabase returns 200 with a JSON body listing deleted objects
    if resp.status_code not in (200, 204):
        raise StorageError(f"Delete failed ({resp.status_code}): {resp.text}")