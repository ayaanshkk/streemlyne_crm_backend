from flask import Blueprint, current_app, jsonify, request

from fai.routes.auth_helpers import token_required as admin_required
from fai.services.tenant_service import TenantOnboardingError, create_tenant

tenant_bp = Blueprint("tenant", __name__)


@tenant_bp.route("/tenants", methods=["POST"])
@admin_required
def onboard_tenant():
    payload = request.get_json(silent=True) or {}
    try:
        result = create_tenant(payload)
        return (
            jsonify(
                {
                    "message": "Tenant created successfully. Existing tenants were not modified.",
                    "tenant": result,
                }
            ),
            201,
        )
    except TenantOnboardingError as exc:
        message = str(exc)
        lowered = message.lower()
        conflict_markers = ("already exists", "concurrent writes", "duplicate", "unique")
        status_code = 409 if any(marker in lowered for marker in conflict_markers) else 400
        return jsonify({"error": message}), status_code
    except Exception as exc:
        current_app.logger.exception("Unexpected tenant onboarding error: %s", exc)
        return jsonify({"error": "Internal error while creating tenant."}), 500
