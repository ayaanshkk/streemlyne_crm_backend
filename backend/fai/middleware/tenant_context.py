import os
from urllib.parse import urlparse

from flask import g, jsonify, request

from fai.services.tenant_service import resolve_tenant_context


def _extract_subdomain(hostname: str) -> str:
    if not hostname:
        return ""
    base_domain = (os.getenv("TENANT_BASE_DOMAIN") or "").strip().lower()
    if not base_domain:
        return ""
    if not hostname.lower().endswith(base_domain):
        return ""

    suffix = "." + base_domain
    prefix = hostname[: -len(suffix)]
    if not prefix or "." in prefix:
        return ""
    return prefix.strip().lower()


def _default_supabase_context():
    database_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL") or ""
    parsed = urlparse(os.getenv("SUPABASE_URL", ""))
    project_id = parsed.hostname.split(".")[0] if parsed.hostname else ""

    return {
        "tenant_id": None,
        "tenant_name": "default",
        "tenant_slug": "default",
        "supabase_project_id": project_id,
        "supabase_url": os.getenv("SUPABASE_URL"),
        "supabase_anon_key": os.getenv("SUPABASE_ANON_KEY"),
        "supabase_service_role_key": os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
        "tenant_jwt_secret": os.getenv("JWT_SECRET_KEY"),
        "database_url": database_url,
    }


def load_tenant_context():
    if request.method == "OPTIONS":
        return None

    tenant_id_header = request.headers.get("X-Tenant-Id")
    tenant_name_header = request.headers.get("X-Tenant-Name")
    tenant_slug_header = request.headers.get("X-Tenant-Slug")
    host_slug = _extract_subdomain((request.host or "").split(":")[0])

    tenant_id = None
    if tenant_id_header:
        try:
            tenant_id = int(tenant_id_header)
        except ValueError:
            return jsonify({"error": "X-Tenant-Id must be an integer"}), 400

    context = resolve_tenant_context(
        tenant_id=tenant_id,
        tenant_name=tenant_name_header,
        tenant_slug=tenant_slug_header or host_slug,
    )

    if tenant_id_header or tenant_name_header or tenant_slug_header or host_slug:
        if not context:
            return jsonify({"error": "Tenant context not found or inactive"}), 404
        default_ctx = _default_supabase_context()
        default_ctx.update(context)
        g.tenant = default_ctx
        return None

    g.tenant = _default_supabase_context()
    return None
