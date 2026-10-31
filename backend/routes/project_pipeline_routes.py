"""
Project Pipeline Routes

GET    /api/project-pipeline                  — all Closed Won clients with their project stage
PATCH  /api/project-pipeline/<id>/stage       — move a client to another project stage
GET    /api/project-pipeline/stages           — this tenant's project stages (custom if saved, else defaults)
GET    /api/project-pipeline/stages/defaults  — default stages, for a "Reset to Defaults" button
PUT    /api/project-pipeline/stages           — save this tenant's custom project stages + order

Default project stages = Pipeline_Stage_Master rows with Stage_Type = 2
(Pre-Planning -> Planning -> Execution -> Post-Delivery).

Custom stages live in Tenant_Pipeline_Stage_Mapping with Pipeline_Type = 2 and are
ordered by Preceding_Stage_ID, exactly like the Sales pipeline. Several custom stages
may point at the same master stage (Pipeline_Stage_ID); Pipeline_Stage_ID may also be
NULL for a fully custom stage.

ProjectDetails.Misc_Col1 stores the stage NAME.
"""

from datetime import datetime, timezone

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import case
from sqlalchemy.exc import SQLAlchemyError

from database import db
from middleware import auth_required
from models import ClientMaster, ProjectDetails, StageMaster, TenantPipelineStage

project_pipeline_bp = Blueprint("project_pipeline", __name__, url_prefix="/project-pipeline")

PROJECT_PIPELINE_TYPE = 2


def _won_filter():
    """A client is 'won' when the Sales board has a lead in its Won stage, which sets
    Client_Master.is_converted = 1. (The old stage == 'Closed Won' text is no longer written.)"""
    col = getattr(ClientMaster, "is_converted", None)
    if col is not None:
        return col == 1
    return ClientMaster.stage.in_(["Won", "Closed Won"])


def _is_won(client) -> bool:
    return getattr(client, "is_converted", None) in (1, True) or client.stage in ("Won", "Closed Won")


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_tenant_id():
    try:
        return int(g.tenant_id)
    except (AttributeError, TypeError, ValueError):
        return None


def _is_project_mapping(mapping) -> bool:
    """Explicit Project mappings, plus legacy rows with a null type whose master stage is type 2."""
    if mapping.pipeline_type is not None:
        try:
            return int(mapping.pipeline_type) == PROJECT_PIPELINE_TYPE
        except (TypeError, ValueError):
            return False
    if mapping.pipeline_stage_id is None:
        return False
    master = db.session.get(StageMaster, mapping.pipeline_stage_id)
    return bool(master and master.stage_type == PROJECT_PIPELINE_TYPE)


def _ordered_mappings(mappings):
    """Order by walking Preceding_Stage_ID; fall back to mapping id for legacy data."""
    if not mappings:
        return []
    starts = [m for m in mappings if m.preceding_stage_id is None]
    if len(starts) == 1:
        ordered, visited, current = [], set(), starts[0]
        while current and current.tenant_pipeline_stage_mapping_id not in visited:
            cid = current.tenant_pipeline_stage_mapping_id
            ordered.append(current)
            visited.add(cid)
            current = next((m for m in mappings if m.preceding_stage_id == cid), None)
        if len(ordered) == len(mappings):
            return ordered
    return sorted(mappings, key=lambda m: m.tenant_pipeline_stage_mapping_id)


def _order_masters(masters):
    if not masters:
        return []
    starts = [m for m in masters if m.preceding_stage_id is None]
    if len(starts) == 1:
        ordered, seen, current = [], set(), starts[0]
        while current and current.stage_id not in seen:
            ordered.append(current)
            seen.add(current.stage_id)
            current = next((m for m in masters if m.preceding_stage_id == current.stage_id), None)
        if len(ordered) == len(masters):
            return ordered
    return sorted(masters, key=lambda m: m.stage_id)


def _project_masters():
    return _order_masters(StageMaster.query.filter_by(stage_type=PROJECT_PIPELINE_TYPE).all())


def get_default_project_stages():
    """Pre-Planning, Planning, Execution, Post-Delivery — straight from Pipeline_Stage_Master."""
    return [
        {
            "id": m.stage_id,
            "mapping_id": None,
            "pipeline_stage_id": m.stage_id,
            "stage_name": m.stage_name,
            "description": m.stage_description,
            "preceding_stage_id": m.preceding_stage_id,
            "is_custom": False,
        }
        for m in _project_masters()
    ]


def get_project_stages(tenant_id):
    """Tenant's custom project stages in board order, else the defaults (nothing written)."""
    master_by_id = {m.stage_id: m for m in _project_masters()}
    rows = TenantPipelineStage.query.filter_by(tenant_id=tenant_id).all()
    mappings = _ordered_mappings([m for m in rows if _is_project_mapping(m)])

    if not mappings:
        return get_default_project_stages()

    stages = []
    for mp in mappings:
        master = master_by_id.get(mp.pipeline_stage_id) if mp.pipeline_stage_id is not None else None
        stages.append({
            "id": mp.tenant_pipeline_stage_mapping_id,
            "mapping_id": mp.tenant_pipeline_stage_mapping_id,
            "pipeline_stage_id": mp.pipeline_stage_id,
            "stage_name": mp.stage_name or (master.stage_name if master else "Unnamed stage"),
            "description": mp.description or (master.stage_description if master else None),
            "preceding_stage_id": mp.preceding_stage_id,
            "is_custom": mp.pipeline_stage_id is None,
        })
    return stages


def _tenant_client_ids(tenant_id):
    return [cid for (cid,) in db.session.query(ClientMaster.client_id)
            .filter_by(tenant_id=str(tenant_id)).all()]


def _get_project_for_client(client_id: int) -> ProjectDetails | None:
    return (
        ProjectDetails.query
        .filter_by(client_id=client_id)
        .order_by(ProjectDetails.created_at.desc())
        .first()
    )


# ── Board data ───────────────────────────────────────────────────────────────

@project_pipeline_bp.route("", methods=["GET"])
@auth_required
def get_project_pipeline():
    tenant_id = get_tenant_id()
    if tenant_id is None:
        return jsonify({"error": "Tenant context missing"}), 401

    stage_names = [s["stage_name"] for s in get_project_stages(tenant_id)]

    clients = (
        ClientMaster.query
        .filter(ClientMaster.tenant_id == str(tenant_id), _won_filter())
        .order_by(ClientMaster.created_at.desc())
        .all()
    )

    items = []
    for c in clients:
        project = _get_project_for_client(c.client_id)
        project_stage = project.Misc_Col1 if project and project.Misc_Col1 else stage_names[0]
        if project_stage not in stage_names:   # new project, or a legacy value like "Kickoff"
            project_stage = stage_names[0]

        items.append({
            "id":               str(c.client_id),
            "type":             "project",
            "client_id":        c.client_id,
            "project_id":       project.project_id if project else None,
            "project_stage":    project_stage,
            "name":             c.client_contact_name or c.client_company_name or "Unknown",
            "company_name":     c.client_company_name,
            "email":            c.client_email,
            "phone":            c.client_phone,
            "address":          c.address or (project.address if project else None),
            "post_code":        c.post_code,
            "project_title":    project.project_title if project else None,
            "start_date":       project.start_date.isoformat() if project and project.start_date else None,
            "end_date":         project.end_date.isoformat() if project and project.end_date else None,
            "created_at":       c.created_at.isoformat() if c.created_at else None,
            "stage_updated_at": project.updated_at.isoformat() if project and project.updated_at else (
                                    c.created_at.isoformat() if c.created_at else None
                                ),
        })

    return jsonify(items), 200


@project_pipeline_bp.route("/<int:client_id>/stage", methods=["PATCH"])
@auth_required
def update_project_stage(client_id: int):
    """Body: { "project_stage": "Planning" } — any stage name from this tenant's list."""
    tenant_id = get_tenant_id()
    if tenant_id is None:
        return jsonify({"error": "Tenant context missing"}), 401

    client = ClientMaster.query.filter_by(client_id=client_id, tenant_id=str(tenant_id)).first()
    if not client:
        return jsonify({"error": "Client not found"}), 404
    if not _is_won(client):
        return jsonify({"error": "Only won clients can have a project stage"}), 400

    new_stage = (request.get_json(silent=True) or {}).get("project_stage")
    if not new_stage:
        return jsonify({"error": "project_stage is required"}), 400

    stage_names = [s["stage_name"] for s in get_project_stages(tenant_id)]
    if new_stage not in stage_names:
        return jsonify({"error": f"Invalid stage. Must be one of: {stage_names}"}), 400

    project = _get_project_for_client(client_id)
    if not project:
        # ProjectDetails needs valid opportunity_id / employee_id FKs, so we can't
        # create one here. The frontend's optimistic move shows, but isn't saved yet.
        return jsonify({
            "message":       "Project stage updated (no project record — create one to persist)",
            "client_id":     client_id,
            "project_stage": new_stage,
            "persisted":     False,
        }), 200

    project.Misc_Col1  = new_stage
    project.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({
        "message":       "Project stage updated",
        "client_id":     client_id,
        "project_id":    project.project_id,
        "project_stage": new_stage,
        "persisted":     True,
    }), 200


# ── Stage management ─────────────────────────────────────────────────────────

@project_pipeline_bp.route("/stages", methods=["GET"])
@auth_required
def get_stages():
    tenant_id = get_tenant_id()
    if tenant_id is None:
        return jsonify({"error": "Tenant context missing"}), 401
    return jsonify({"pipeline_type": "project", "stages": get_project_stages(tenant_id)}), 200


@project_pipeline_bp.route("/stages/defaults", methods=["GET"])
@auth_required
def get_default_stages():
    if get_tenant_id() is None:
        return jsonify({"error": "Tenant context missing"}), 401
    return jsonify({"pipeline_type": "project", "stages": get_default_project_stages()}), 200


@project_pipeline_bp.route("/stages", methods=["PUT"])
@auth_required
def save_stages():
    """
    Body: { "stages": [ {"stage_name", "pipeline_stage_id"?, "mapping_id"?, "description"?}, ... ] }
    List order = board order. Renamed stages carry their projects with them; a stage that
    still has projects can't be removed.
    """
    tenant_id = get_tenant_id()
    if tenant_id is None:
        return jsonify({"error": "Tenant context missing"}), 401

    submitted = (request.get_json(silent=True) or {}).get("stages")
    if not isinstance(submitted, list) or not submitted:
        return jsonify({"error": "stages must be a non-empty list"}), 400

    master_ids = {m.stage_id for m in _project_masters()}
    existing = [r for r in TenantPipelineStage.query.filter_by(tenant_id=tenant_id).all()
                if _is_project_mapping(r)]
    by_mapping_id = {r.tenant_pipeline_stage_mapping_id: r for r in existing}
    had_mappings = bool(existing)

    cleaned, seen_names = [], set()
    for i, row in enumerate(submitted):
        if not isinstance(row, dict):
            return jsonify({"error": f"Stage at position {i + 1} must be an object"}), 400

        name = str(row.get("stage_name") or row.get("name") or "").strip()
        if not name:
            return jsonify({"error": f"Stage at position {i + 1} needs a name"}), 400
        if len(name) > 100:
            return jsonify({"error": f"Stage name '{name[:30]}' exceeds 100 characters"}), 400
        if name.casefold() in seen_names:
            return jsonify({"error": "Stage names must be unique"}), 400
        seen_names.add(name.casefold())

        sid = row.get("pipeline_stage_id")
        if sid in ("", 0):
            sid = None
        if sid is not None:
            try:
                sid = int(sid)
            except (TypeError, ValueError):
                return jsonify({"error": f"Invalid pipeline_stage_id for stage '{name}'"}), 400
            if sid not in master_ids:
                return jsonify({"error": f"'{name}' does not reference a valid Project master stage"}), 400

        mid = row.get("mapping_id")
        try:
            mid = int(mid) if mid not in (None, "", 0) else None
        except (TypeError, ValueError):
            mid = None
        if mid is not None and mid not in by_mapping_id:
            mid = None

        desc = row.get("description")
        desc = (str(desc).strip() or None) if desc is not None else None
        cleaned.append({"stage_name": name, "pipeline_stage_id": sid, "mapping_id": mid, "description": desc})

    # Work out which old stage each submitted stage replaces (to carry renames, find dropped stages)
    old_stages = get_project_stages(tenant_id)
    old_by_mapping = {s["mapping_id"]: s for s in old_stages if s["mapping_id"]}
    old_by_master = {s["pipeline_stage_id"]: s for s in old_stages if not s["mapping_id"]}

    renames, retained_old_names = {}, set()
    for item in cleaned:
        old = (old_by_mapping.get(item["mapping_id"]) if item["mapping_id"]
               else old_by_master.get(item["pipeline_stage_id"]))
        if old and old["stage_name"] not in retained_old_names:
            retained_old_names.add(old["stage_name"])
            if old["stage_name"] != item["stage_name"]:
                renames[old["stage_name"]] = item["stage_name"]

    dropped_names = [s["stage_name"] for s in old_stages if s["stage_name"] not in retained_old_names]
    client_ids = _tenant_client_ids(tenant_id)

    if dropped_names and client_ids:
        rows = (db.session.query(ProjectDetails.Misc_Col1, db.func.count())
                .filter(ProjectDetails.client_id.in_(client_ids),
                        ProjectDetails.Misc_Col1.in_(dropped_names))
                .group_by(ProjectDetails.Misc_Col1).all())
        if rows:
            detail = ", ".join(f"{n} ({c})" for n, c in rows)
            return jsonify({"error": f"These stages still have projects: {detail}. "
                                     "Move those projects to another stage first."}), 409

    try:
        retained_ids = {i["mapping_id"] for i in cleaned if i["mapping_id"]}
        removed = [r for r in existing if r.tenant_pipeline_stage_mapping_id not in retained_ids]

        saved = []
        for item in cleaned:
            mp = by_mapping_id.get(item["mapping_id"]) if item["mapping_id"] else None
            if mp is None:
                mp = TenantPipelineStage(
                    tenant_id=tenant_id,
                    pipeline_stage_id=item["pipeline_stage_id"],
                    stage_name=item["stage_name"],
                    description=item["description"],
                    pipeline_type=PROJECT_PIPELINE_TYPE,
                    preceding_stage_id=None,
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
                db.session.add(mp)
            else:
                mp.stage_name = item["stage_name"]
                mp.pipeline_stage_id = item["pipeline_stage_id"]
                mp.description = item["description"]
                mp.pipeline_type = PROJECT_PIPELINE_TYPE
            saved.append(mp)

        db.session.flush()
        for idx, mp in enumerate(saved):
            mp.preceding_stage_id = saved[idx - 1].tenant_pipeline_stage_mapping_id if idx else None

        for mp in removed:
            mp.preceding_stage_id = None
        if removed:
            db.session.flush()
        for mp in removed:
            db.session.delete(mp)

        # One CASE update so A->B and B->C renames can't chain
        if renames and client_ids:
            (ProjectDetails.query
                .filter(ProjectDetails.client_id.in_(client_ids),
                        ProjectDetails.Misc_Col1.in_(list(renames)))
                .update({"Misc_Col1": case(renames, value=ProjectDetails.Misc_Col1,
                                           else_=ProjectDetails.Misc_Col1)},
                        synchronize_session=False))

        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Unable to save project pipeline stages")
        return jsonify({"error": "Unable to save project stages. No changes were committed."}), 500

    return jsonify({"message": "Project stages saved", "pipeline_type": "project",
                    "stages": get_project_stages(tenant_id)}), 200