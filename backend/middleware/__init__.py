# middleware/__init__.py
#
# CHANGES vs previous version
# ─────────────────────────────────────────────────────────────────────────────
# [MW-INIT-001] Removed duplicate import of permission_required from
#               auth_middleware.  The correct implementation lives in
#               permission_middleware (delegates to PermissionService).
#               Previously, line 4 re-imported permission_required from
#               auth_middleware AFTER line 3 imported it from
#               permission_middleware, silently overwriting the correct one.
#
# [MW-INIT-002] Removed duplicate import of auth_required (was on both line 2
#               and line 4).
#
# [MW-INIT-003] require_tenant_owner added to __all__ so that wildcard imports
#               and IDE auto-complete expose it correctly.
# ─────────────────────────────────────────────────────────────────────────────

from .auth_middleware import auth_required, get_current_user, get_current_employee, require_owner, require_tenant_owner  # [MW-INIT-001, 002]
from .permission_middleware import permission_required  # [MW-INIT-001] sole source of truth
from .tenant_context import get_current_tenant_id, inject_tenant_context, tenant_required

__all__ = [
    "auth_required",
    "get_current_user",
    "get_current_employee",
    "permission_required",
    "require_owner",
    "require_tenant_owner",    # [MW-INIT-003] was missing
    "tenant_required",
    "get_current_tenant_id",
    "inject_tenant_context",
]
