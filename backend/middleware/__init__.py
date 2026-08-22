# middleware/__init__.py

from .auth_middleware import (
    auth_required,
    get_current_user,
    get_current_employee,
    require_owner,
    require_tenant_owner,
    role_required,
    ADMIN,
    MANAGER,
    SALESPERSON,
    VIEWER,
    CAN_MANAGE_SETTINGS,
    CAN_VIEW_ALL_RECORDS,
    CAN_CREATE_RECORDS,
    CAN_DELETE_RECORDS,
    CAN_VIEW_REPORTS,
    CAN_INVITE_TEAM,
    CAN_MANAGE_ROLES,
)
from .permission_middleware import permission_required
from .tenant_context import get_current_tenant_id, inject_tenant_context, tenant_required

__all__ = [
    "auth_required",
    "get_current_user",
    "get_current_employee",
    "permission_required",
    "require_owner",
    "require_tenant_owner",
    "tenant_required",
    "get_current_tenant_id",
    "inject_tenant_context",
    "role_required",
    "ADMIN",
    "MANAGER",
    "SALESPERSON",
    "VIEWER",
    "CAN_MANAGE_SETTINGS",
    "CAN_VIEW_ALL_RECORDS",
    "CAN_CREATE_RECORDS",
    "CAN_DELETE_RECORDS",
    "CAN_VIEW_REPORTS",
    "CAN_INVITE_TEAM",
    "CAN_MANAGE_ROLES"
]
