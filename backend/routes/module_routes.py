from flask import Blueprint, jsonify, g
from middleware.auth_middleware import auth_required
from models import ModuleMaster, TenantModuleMapping
from database import db

module_bp = Blueprint("modules", __name__, url_prefix="/modules")

# Frontend nav metadata — icon names match lucide-react
MODULE_META = {
    "DASHBOARD":        {"icon": "LayoutDashboard", "path": "/dashboard"},
    "CUSTOMERS":        {"icon": "Users",            "path": "/dashboard/customers"},
    "SALES_PIPELINE":   {"icon": "TrendingUp",       "path": "/dashboard/pipeline"},
    "PROJECT_PIPELINE": {"icon": "Kanban",           "path": "/dashboard/project-pipeline"},
    "SCHEDULE":         {"icon": "Calendar",         "path": "/dashboard/schedule"},
    "FINANCIAL_DOCS":   {"icon": "FileText",         "path": "/dashboard/financial"},
    "STREEMAI":         {"icon": "Bot", "path": "/dashboard/ai"},
}

# Minimum plan needed to unlock each module (for upgrade prompt)
MODULE_UNLOCK_PLAN = {
    "SALES_PIPELINE":   "Starter",
    "PROJECT_PIPELINE": "Pro",
    "SCHEDULE":         "Starter",
    "FINANCIAL_DOCS":   "Starter",
}

@module_bp.get("/access")
@auth_required
def get_module_access():
    tenant_id = g.tenant_id

    # Get all active modules
    all_modules = (
        db.session.query(ModuleMaster)
        .filter_by(is_active=True)
        .order_by(ModuleMaster.module_id)
        .all()
    )

    # Get granted module IDs for this tenant
    granted_ids = {
        row.module_id
        for row in db.session.query(TenantModuleMapping.module_id)
        .filter_by(tenant_id=tenant_id)
        .all()
    }

    result = []
    for mod in all_modules:
        meta = MODULE_META.get(mod.module_code, {})
        has_access = mod.module_id in granted_ids
        result.append({
            "code":         mod.module_code,
            "name":         mod.module_name,
            "icon":         meta.get("icon", "Circle"),
            "path":         meta.get("path", "/dashboard"),
            "has_access":   has_access,
            "is_core":      mod.is_core,
            "unlock_plan":  None if has_access else MODULE_UNLOCK_PLAN.get(mod.module_code),
        })

    return jsonify(result), 200