"""
Pipeline Routes
GET /api/pipeline  — returns all clients formatted for pipeline/kanban view,
                     grouped by their stage field on ClientMaster.
PATCH /api/pipeline/<client_id>/stage — drag-and-drop stage update.
"""

from datetime import datetime, timezone
from flask import Blueprint, g, jsonify, request
from database import db
from middleware import auth_required
from models import ClientMaster

pipeline_bp = Blueprint("pipeline", __name__, url_prefix="/pipeline")


@pipeline_bp.route("", methods=["GET"])
@auth_required
def get_pipeline():
    """
    GET /api/pipeline
    Returns all clients for the tenant formatted as pipeline items,
    keyed by stage. Clients with no stage default to 'Lead'.
    """
    clients = (
        ClientMaster.query
        .filter_by(tenant_id=str(g.tenant_id))
        .order_by(ClientMaster.created_at.desc())
        .all()
    )

    items = [
        {
            "id":               str(c.client_id),
            "type":             "client",
            "stage":            c.stage or "Lead",
            "client_id":        c.client_id,
            "name":             c.client_contact_name or c.client_company_name or "Unknown",
            "company_name":     c.client_company_name,
            "email":            c.client_email,
            "phone":            c.client_phone,
            "address":          c.address,
            "post_code":        c.post_code,
            "created_at":       c.created_at.isoformat() if c.created_at else None,
            # ✅ Send stage_updated_at so frontend can show accurate "days in stage"
            "stage_updated_at": c.stage_updated_at.isoformat() if c.stage_updated_at else (
                                    c.created_at.isoformat() if c.created_at else None
                                ),
        }
        for c in clients
    ]

    return jsonify(items), 200


@pipeline_bp.route("/<int:client_id>/stage", methods=["PATCH"])
@auth_required
def update_stage(client_id: int):
    """
    PATCH /api/pipeline/<client_id>/stage
    Body: { "stage": "Qualified" }
    Updates the stage on ClientMaster for drag-and-drop kanban moves.
    """
    client = ClientMaster.query.filter_by(
        client_id=client_id,
        tenant_id=str(g.tenant_id),
    ).first()

    if not client:
        return jsonify({"error": "Client not found"}), 404

    data = request.get_json() or {}
    new_stage = data.get("stage")

    if not new_stage:
        return jsonify({"error": "stage is required"}), 400

    # ✅ Only reset stage_updated_at if the stage actually changed
    if client.stage != new_stage:
        client.stage = new_stage
        client.stage_updated_at = datetime.now(timezone.utc)

    db.session.commit()

    return jsonify({
        "message":          "Stage updated",
        "client_id":        client.client_id,
        "stage":            client.stage,
        "stage_updated_at": client.stage_updated_at.isoformat() if client.stage_updated_at else None,
    }), 200