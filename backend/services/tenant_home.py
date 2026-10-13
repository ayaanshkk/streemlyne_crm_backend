"""
Which part of the frontend each tenant's users land in after login.

Most tenants use the standard StreemLyne dashboard. Tenants whose software
was merged in as its own section (FAI) are listed in TENANT_HOME_PATHS, a
JSON object keyed by tenant_id, e.g. {"3": "/fai"}.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_HOME_PATH = "/dashboard"


def get_tenant_home_path(tenant_id) -> str:
    raw = os.getenv("TENANT_HOME_PATHS", "").strip()
    if not raw or tenant_id is None:
        return DEFAULT_HOME_PATH
    try:
        paths = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("TENANT_HOME_PATHS is not valid JSON; ignoring it")
        return DEFAULT_HOME_PATH
    return paths.get(str(tenant_id)) or DEFAULT_HOME_PATH
