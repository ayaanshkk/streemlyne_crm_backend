from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from database import db
from middleware import auth_required
from models import ClientMaster, StageMaster, TenantPipelineStage

pipeline_bp = Blueprint("pipeline", __name__, url_prefix="/pipeline")

SALES_PIPELINE_TYPE = 1


def get_tenant_id():
    try:
        return int(g.tenant_id)
    except (AttributeError, TypeError, ValueError):
        return None


def _is_sales_mapping(mapping):
    """Support explicit Sales mappings and legacy rows with a null type."""
    if mapping.pipeline_type is not None:
        try:
            return int(mapping.pipeline_type) == SALES_PIPELINE_TYPE
        except (TypeError, ValueError):
            return False

    if mapping.pipeline_stage_id is None:
        return False

    master = db.session.get(StageMaster, mapping.pipeline_stage_id)
    return bool(master and master.stage_type == SALES_PIPELINE_TYPE)


def _ordered_mappings(mappings):
    """Order mappings using Preceding_Stage_ID; fall back for legacy data."""
    if not mappings:
        return []

    by_id = {m.tenant_pipeline_stage_mapping_id: m for m in mappings}
    starts = [m for m in mappings if m.preceding_stage_id is None]

    # The configured chain should have exactly one first stage.
    if len(starts) == 1:
        ordered = []
        visited = set()
        current = starts[0]
        while current and current.tenant_pipeline_stage_mapping_id not in visited:
            current_id = current.tenant_pipeline_stage_mapping_id
            ordered.append(current)
            visited.add(current_id)
            current = next(
                (m for m in mappings if m.preceding_stage_id == current_id),
                None,
            )
        if len(ordered) == len(mappings):
            return ordered

    # Existing/legacy mappings may not have a complete predecessor chain.
    return sorted(mappings, key=lambda m: m.tenant_pipeline_stage_mapping_id)


def get_sales_stages(tenant_id):
    tenant_mappings = TenantPipelineStage.query.filter_by(tenant_id=tenant_id).all()
    mappings = _ordered_mappings(
        [mapping for mapping in tenant_mappings if _is_sales_mapping(mapping)]
    )

    if mappings:
        stages = []
        for mapping in mappings:
            master = (
                db.session.get(StageMaster, mapping.pipeline_stage_id)
                if mapping.pipeline_stage_id is not None
                else None
            )
            stages.append({
                "id": mapping.tenant_pipeline_stage_mapping_id,
                "mapping_id": mapping.tenant_pipeline_stage_mapping_id,
                "pipeline_stage_id": mapping.pipeline_stage_id,
                "stage_name": mapping.stage_name or (master.stage_name if master else "Unnamed stage"),
                "description": mapping.description or (master.stage_description if master else None),
                "preceding_stage_id": mapping.preceding_stage_id,
                "is_custom": mapping.pipeline_stage_id is None,
            })
        return stages

    # No tenant-specific Sales configuration: use master defaults without writing to DB.
    masters = (
        StageMaster.query
        .filter_by(stage_type=SALES_PIPELINE_TYPE)
        .order_by(StageMaster.preceding_stage_id.asc().nullsfirst(), StageMaster.stage_id.asc())
        .all()
    )
    return [
        {
            "id": stage.stage_id,
            "mapping_id": None,
            "pipeline_stage_id": stage.stage_id,
            "stage_name": stage.stage_name,
            "description": stage.stage_description,
            "preceding_stage_id": stage.preceding_stage_id,
            "is_custom": False,
        }
        for stage in masters
    ]


@pipeline_bp.route("/stages", methods=["GET"])
@auth_required
def get_pipeline_stages():
    tenant_id = get_tenant_id()
    if tenant_id is None:
        return jsonify({"error": "Tenant context missing"}), 401

    return jsonify({
        "pipeline_type": "sales",
        "stages": get_sales_stages(tenant_id),
    }), 200


@pipeline_bp.route("/stages", methods=["PUT"])
@auth_required
def save_pipeline_stages():
    """Create/update this tenant's Sales stage mappings and save their order."""
    tenant_id = get_tenant_id()
    if tenant_id is None:
        return jsonify({"error": "Tenant context missing"}), 401

    payload = request.get_json(silent=True) or {}
    submitted = payload.get("stages")
    if not isinstance(submitted, list) or not submitted:
        return jsonify({"error": "stages must be a non-empty list"}), 400

    cleaned = []
    seen_names = set()
    for index, row in enumerate(submitted):
        if not isinstance(row, dict):
            return jsonify({"error": f"Stage at position {index + 1} must be an object"}), 400

        stage_name = str(row.get("stage_name") or row.get("name") or "").strip()
        if not stage_name:
            return jsonify({"error": f"Stage at position {index + 1} needs a name"}), 400
        if len(stage_name) > 100:
            return jsonify({"error": f"Stage name '{stage_name[:30]}' exceeds 100 characters"}), 400

        normalized_name = stage_name.casefold()
        if normalized_name in seen_names:
            return jsonify({"error": "Stage names must be unique"}), 400
        seen_names.add(normalized_name)

        pipeline_stage_id = row.get("pipeline_stage_id")
        if pipeline_stage_id in ("", 0):
            pipeline_stage_id = None
        if pipeline_stage_id is not None:
            try:
                pipeline_stage_id = int(pipeline_stage_id)
            except (TypeError, ValueError):
                return jsonify({"error": f"Invalid pipeline_stage_id for stage '{stage_name}'"}), 400

            master = db.session.get(StageMaster, pipeline_stage_id)
            if not master or master.stage_type != SALES_PIPELINE_TYPE:
                return jsonify({"error": f"'{stage_name}' does not reference a valid Sales master stage"}), 400

        mapping_id = row.get("mapping_id")
        # The frontend may use `id` as a fallback for mapping_id. For master
        # defaults that id is a master stage ID, so pipeline_stage_id takes priority.
        if mapping_id in ("", 0):
            mapping_id = None
        if mapping_id is not None:
            try:
                mapping_id = int(mapping_id)
            except (TypeError, ValueError):
                mapping_id = None

        description = row.get("description")
        if description is not None:
            description = str(description).strip() or None

        cleaned.append({
            "stage_name": stage_name,
            "pipeline_stage_id": pipeline_stage_id,
            "mapping_id": mapping_id,
            "description": description,
        })

    tenant_rows = TenantPipelineStage.query.filter_by(tenant_id=tenant_id).all()
    existing_sales = [row for row in tenant_rows if _is_sales_mapping(row)]
    by_mapping_id = {row.tenant_pipeline_stage_mapping_id: row for row in existing_sales}
    by_master_id = {}
    for row in existing_sales:
        if row.pipeline_stage_id is not None:
            by_master_id.setdefault(row.pipeline_stage_id, row)

    # Resolve which existing mappings are retained before mutating anything.
    resolved = []
    retained_ids = set()
    for item in cleaned:
        mapping = None
        master_id = item["pipeline_stage_id"]
        if master_id is not None:
            candidate = by_master_id.get(master_id)
            if candidate and candidate.tenant_pipeline_stage_mapping_id not in retained_ids:
                mapping = candidate

        if mapping is None and item["mapping_id"] is not None:
            candidate = by_mapping_id.get(item["mapping_id"])
            if candidate and candidate.tenant_pipeline_stage_mapping_id not in retained_ids:
                # Do not let a master-stage ID accidentally select an unrelated mapping.
                if master_id is None or candidate.pipeline_stage_id in (None, master_id):
                    mapping = candidate

        if mapping is not None:
            retained_ids.add(mapping.tenant_pipeline_stage_mapping_id)
        resolved.append((item, mapping))

    removed = [row for row in existing_sales if row.tenant_pipeline_stage_mapping_id not in retained_ids]
    removed_ids = [row.tenant_pipeline_stage_mapping_id for row in removed]
    if removed_ids:
        referenced = (
            ClientMaster.query
            .filter(ClientMaster.tenant_id == tenant_id, ClientMaster.stage_id.in_(removed_ids))
            .first()
        )
        if referenced:
            return jsonify({
                "error": "One or more stages cannot be removed because existing leads reference them. Move those leads to another stage first.",
                "client_id": referenced.client_id,
            }), 409

    try:
        saved_mappings = []
        for item, mapping in resolved:
            if mapping is None:
                mapping = TenantPipelineStage(
                    tenant_id=tenant_id,
                    pipeline_stage_id=item["pipeline_stage_id"],
                    stage_name=item["stage_name"],
                    description=item["description"],
                    pipeline_type=SALES_PIPELINE_TYPE,
                    preceding_stage_id=None,
                    # The existing PostgreSQL column is NOT NULL and has no
                    # database default, so populate it in application code.
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
                db.session.add(mapping)
            else:
                mapping.stage_name = item["stage_name"]
                mapping.pipeline_stage_id = item["pipeline_stage_id"]
                mapping.description = item["description"]
                mapping.pipeline_type = SALES_PIPELINE_TYPE
            saved_mappings.append(mapping)

        # Flush once to assign IDs to newly-created mappings, then persist ordering.
        db.session.flush()
        for index, mapping in enumerate(saved_mappings):
            mapping.preceding_stage_id = (
                saved_mappings[index - 1].tenant_pipeline_stage_mapping_id
                if index > 0 else None
            )

        # Break predecessor links among mappings being removed so self-referencing
        # foreign keys cannot block deletion of a removed chain.
        for mapping in removed:
            mapping.preceding_stage_id = None
        if removed:
            db.session.flush()
        for mapping in removed:
            db.session.delete(mapping)

        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"error": "Unable to save pipeline stages. No changes were committed."}), 500

    return jsonify({
        "message": "Pipeline stages saved",
        "pipeline_type": "sales",
        "stages": get_sales_stages(tenant_id),
    }), 200


@pipeline_bp.route("", methods=["GET"])
@auth_required
def get_pipeline():
    tenant_id = get_tenant_id()
    if tenant_id is None:
        return jsonify({"error": "Tenant context missing"}), 401

    clients = (
        ClientMaster.query
        .filter_by(tenant_id=tenant_id)
        .order_by(ClientMaster.created_at.desc())
        .all()
    )

    items = []
    for client in clients:
        items.append({
            "id": str(client.client_id),
            "type": "client",
            "stage": client.stage or "Lead",
            "client_id": client.client_id,
            "name": client.client_contact_name or client.client_company_name or "Unknown",
            "company_name": client.client_company_name,
            "email": client.client_email,
            "phone": client.client_phone,
            "address": client.address,
            "post_code": client.post_code,
            "created_at": client.created_at.isoformat() if client.created_at else None,
            "stage_updated_at": (
                client.stage_updated_at.isoformat()
                if client.stage_updated_at
                else (client.created_at.isoformat() if client.created_at else None)
            ),
        })

    return jsonify(items), 200


@pipeline_bp.route("/<int:client_id>/stage", methods=["PATCH"])
@auth_required
def update_stage(client_id):
    tenant_id = get_tenant_id()
    if tenant_id is None:
        return jsonify({"error": "Tenant context missing"}), 401

    client = ClientMaster.query.filter_by(
        client_id=client_id,
        tenant_id=tenant_id,
    ).first()
    if not client:
        return jsonify({"error": "Client not found"}), 404

    data = request.get_json(silent=True) or {}
    new_stage = str(data.get("stage", "")).strip()
    if not new_stage:
        return jsonify({"error": "stage is required"}), 400

    allowed_stages = {
        stage["stage_name"].casefold()
        for stage in get_sales_stages(tenant_id)
    }
    if new_stage.casefold() not in allowed_stages:
        return jsonify({"error": "Stage is not configured for this tenant"}), 400

    if client.stage != new_stage:
        client.stage = new_stage
        client.stage_updated_at = datetime.now(timezone.utc)

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"error": "Unable to update the lead stage"}), 500

    return jsonify({
        "message": "Stage updated",
        "client_id": client.client_id,
        "stage": client.stage,
        "stage_updated_at": client.stage_updated_at.isoformat() if client.stage_updated_at else None,
    }), 200
