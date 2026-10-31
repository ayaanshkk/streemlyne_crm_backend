"""Sales pipeline routes for StreemLyne.

Cards on the board are rows of Lead_Master (same as FAI). Stages are tenant
configurable (Tenant pipeline stage mappings) and default to the Sales stages
in Pipeline_Stage_Master, which is what FAI uses.

Workflow rules are attached to a stage's ROLE, not its name or id. A stage's role
comes from the default (master) stage it was created from, so a tenant can rename
or reorder it and keep the rule. Custom stages have no role and no rules.

    qualification -> 5-question form; score <= 5 sends the lead to the "lost" stage,
                     otherwise the lead waits for an admin to approve / reject
    opportunity   -> where an approved qualification goes
    proposal      -> a quotation must exist for the company before a lead reaches
                     this stage or any stage after it (board order, not stage id)
    won           -> won_at is stamped on entry
    lost          -> always reachable, except from a pending qualification

Stage ids stored in Lead_Master.stage_id are the "id" returned by
get_sales_stages(): master stage ids while a tenant has not customised its board,
tenant mapping ids afterwards. The first save of a customised board re-points the
tenant's leads from master ids to mapping ids inside the same transaction.
"""

import os
import re
from datetime import date, datetime, timezone

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from database import db
from middleware import auth_required
from models import ClientMaster, StageMaster, TenantPipelineStage

pipeline_bp = Blueprint("pipeline", __name__, url_prefix="/pipeline")

SALES_PIPELINE_TYPE = 1
MAX_IMPORT_ROWS = 500

QUESTION_COUNT = 5
MAX_ANSWER_SCORE = 3
QUALIFICATION_PASS_SCORE = 5  # a score of 5 or less is disqualified

# Qualification status values stored in Lead_Master."qualification status"
QS_REJECTED = 0
QS_APPROVED = 1
QS_PENDING = 2

ADMIN_ROLE_NAMES = {
    "admin",
    "administrator",
    "super_admin",
    "super admin",
    "platform admin",
    "tenant super admin",
}
ADMIN_ROLE_IDS = {1, 2}  # Role_Master: 1 = Tenant Super Admin, 2 = Platform Admin

_IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")
_QUOTATION_SOURCE = {}


# ── Small helpers ──────────────────────────────────────────────────────────


def get_tenant_id():
    try:
        return int(g.tenant_id)
    except (AttributeError, TypeError, ValueError):
        return None


def _setting(key, default=None):
    value = current_app.config.get(key, os.environ.get(key))
    if value is None or str(value).strip() == "":
        return default
    return value


def _schema():
    """Use the schema the ORM models already live in, else DB_SCHEMA."""
    schema = ClientMaster.__table__.schema or _setting("DB_SCHEMA")
    if schema and not _IDENT_RE.match(str(schema)):
        raise RuntimeError("Invalid database schema name")
    return schema


def T(table):
    schema = _schema()
    return f'"{schema}"."{table}"' if schema else f'"{table}"'


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _iso(value):
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def _norm_key(key):
    return re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")


def _parse_date(value, label):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if len(raw) > 10 and raw[4:5] == "-":
        raw = raw[:10]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"{label} must be a valid date (YYYY-MM-DD or DD-MM-YYYY)")


# ── Current user ───────────────────────────────────────────────────────────


def _auth_user():
    for holder in (g, request):
        for attr in ("current_user", "user"):
            candidate = getattr(holder, attr, None)
            if candidate is not None:
                return candidate
    return None


def _user_value(*keys):
    user = _auth_user()
    for key in keys:
        value = user.get(key) if isinstance(user, dict) else getattr(user, key, None)
        if value is None:
            value = getattr(g, key, None)
        if value is not None:
            return value
    return None


def _role_name(role):
    if isinstance(role, dict):
        role = role.get("role_name") or role.get("name") or role.get("role")
    elif role is not None and not isinstance(role, str):
        role = getattr(role, "role_name", None) or getattr(role, "name", None)
    return str(role or "").strip().lower()


def _role_ids(value):
    if value is None:
        return set()
    items = value if isinstance(value, (list, tuple, set)) else str(value).split(",")
    ids = set()
    for item in items:
        if isinstance(item, dict):
            item = item.get("role_id", item.get("id"))
        elif not isinstance(item, (str, int)) and item is not None:
            item = getattr(item, "role_id", getattr(item, "id", None))
        parsed = _as_int(str(item).strip()) if item is not None else None
        if parsed is not None:
            ids.add(parsed)
    return ids


def _is_admin():
    if bool(_user_value("is_admin", "isAdmin")):
        return True

    roles = _user_value("roles")
    role_values = [_user_value("role", "user_role", "role_name", "userRole")]
    if isinstance(roles, (list, tuple, set)):
        role_values.extend(roles)
    elif roles is not None:
        role_values.append(roles)
    if any(_role_name(role) in ADMIN_ROLE_NAMES for role in role_values):
        return True

    ids = set()
    for key in ("role_id", "roleId", "role_ids", "roleIds", "roles"):
        ids |= _role_ids(_user_value(key))
    return bool(ids & ADMIN_ROLE_IDS)


def _current_user_id():
    return _as_int(_user_value("user_id", "userId", "id"))


def _current_employee_id(tenant_id):
    employee_id = _as_int(_user_value("employee_id", "employeeId"))
    if employee_id is not None:
        return employee_id
    user_id = _current_user_id()
    if user_id is None:
        return None
    row = db.session.execute(
        text(
            f"""
            SELECT um.employee_id
            FROM {T("User_Master")} um
            JOIN {T("Employee_Master")} em ON em.employee_id = um.employee_id
            WHERE um.user_id = :user_id AND em.tenant_id = :tenant_id
            LIMIT 1
            """
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    ).fetchone()
    return row.employee_id if row else None


def _valid_created_by(tenant_id):
    """Lead_Master.created_by references User_Master.user_id."""
    user_id = _current_user_id()
    if user_id is None:
        return None
    row = db.session.execute(
        text(
            f"""
            SELECT um.user_id
            FROM {T("User_Master")} um
            JOIN {T("Employee_Master")} em ON em.employee_id = um.employee_id
            WHERE um.user_id = :user_id AND em.tenant_id = :tenant_id
            LIMIT 1
            """
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    ).fetchone()
    return row.user_id if row else None


# ── Tenant stages ──────────────────────────────────────────────────────────


def _role_for(master_name):
    name = re.sub(r"\s+", " ", str(master_name or "").strip().lower())
    if name == "qualification":
        return "qualification"
    if name in ("opportunity", "opportunities"):
        return "opportunity"
    if name == "proposal":
        return "proposal"
    if re.fullmatch(r"(closed )?won", name):
        return "won"
    if re.fullmatch(r"(closed )?lost", name):
        return "lost"
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

    starts = [m for m in mappings if m.preceding_stage_id is None]

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

    return sorted(mappings, key=lambda m: m.tenant_pipeline_stage_mapping_id)


def _order_masters(masters):
    """Order default stages by walking Preceding_Stage_ID (not by comparing the ids)."""
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
    return sorted(
        masters,
        key=lambda m: (m.preceding_stage_id is not None, m.preceding_stage_id or 0, m.stage_id),
    )


def _sales_masters():
    return _order_masters(StageMaster.query.filter_by(stage_type=SALES_PIPELINE_TYPE).all())


def get_default_sales_stages():
    """The platform's default Sales stages (Pipeline_Stage_Master), in board order."""
    return [
        {
            "id": stage.stage_id,
            "mapping_id": None,
            "pipeline_stage_id": stage.stage_id,
            "stage_name": stage.stage_name,
            "description": stage.stage_description,
            "preceding_stage_id": stage.preceding_stage_id,
            "is_custom": False,
            "role": _role_for(stage.stage_name),
        }
        for stage in _sales_masters()
    ]


def get_sales_stages(tenant_id):
    master_by_id = {m.stage_id: m for m in _sales_masters()}

    tenant_mappings = TenantPipelineStage.query.filter_by(tenant_id=tenant_id).all()
    mappings = _ordered_mappings([m for m in tenant_mappings if _is_sales_mapping(m)])

    if mappings:
        stages = []
        for mapping in mappings:
            master = master_by_id.get(mapping.pipeline_stage_id) if mapping.pipeline_stage_id is not None else None
            stages.append(
                {
                    "id": mapping.tenant_pipeline_stage_mapping_id,
                    "mapping_id": mapping.tenant_pipeline_stage_mapping_id,
                    "pipeline_stage_id": mapping.pipeline_stage_id,
                    "stage_name": mapping.stage_name or (master.stage_name if master else "Unnamed stage"),
                    "description": mapping.description or (master.stage_description if master else None),
                    "preceding_stage_id": mapping.preceding_stage_id,
                    "is_custom": mapping.pipeline_stage_id is None,
                    "role": _role_for(master.stage_name) if master else None,
                }
            )
        return stages

    # No tenant-specific Sales configuration: use master defaults without writing to DB.
    return get_default_sales_stages()


def _stage_maps(stages):
    by_id = {s["id"]: s for s in stages}
    by_role = {}
    for stage in stages:
        if stage["role"] and stage["role"] not in by_role:
            by_role[stage["role"]] = stage
    position = {s["id"]: index for index, s in enumerate(stages)}
    return by_id, by_role, position


@pipeline_bp.route("/stages", methods=["GET"])
@auth_required
def get_pipeline_stages():
    tenant_id = get_tenant_id()
    if tenant_id is None:
        return jsonify({"error": "Tenant context missing"}), 401

    return jsonify({"pipeline_type": "sales", "stages": get_sales_stages(tenant_id)}), 200


@pipeline_bp.route("/stages/defaults", methods=["GET"])
@auth_required
def get_default_pipeline_stages():
    """The default stages, for the "Reset to Defaults" button (never hardcode ids in the UI)."""
    if get_tenant_id() is None:
        return jsonify({"error": "Tenant context missing"}), 401

    return jsonify({"pipeline_type": "sales", "stages": get_default_sales_stages()}), 200


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
    seen_masters = set()
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
        role = None
        if pipeline_stage_id is not None:
            try:
                pipeline_stage_id = int(pipeline_stage_id)
            except (TypeError, ValueError):
                return jsonify({"error": f"Invalid pipeline_stage_id for stage '{stage_name}'"}), 400

            master = db.session.get(StageMaster, pipeline_stage_id)
            if not master or master.stage_type != SALES_PIPELINE_TYPE:
                return jsonify({"error": f"'{stage_name}' does not reference a valid Sales master stage"}), 400
            if pipeline_stage_id in seen_masters:
                return jsonify({"error": "A default stage can only be used once"}), 400
            seen_masters.add(pipeline_stage_id)
            role = _role_for(master.stage_name)

        mapping_id = row.get("mapping_id")
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

        cleaned.append(
            {
                "stage_name": stage_name,
                "pipeline_stage_id": pipeline_stage_id,
                "mapping_id": mapping_id,
                "description": description,
                "role": role,
            }
        )

    # The qualification workflow routes failed leads to the lost stage.
    roles = {item["role"] for item in cleaned if item["role"]}
    if "qualification" in roles and "lost" not in roles:
        return (
            jsonify(
                {
                    "error": "A board with a Qualification stage must also keep its Lost stage, "
                    "because failed qualifications are moved there."
                }
            ),
            400,
        )

    old_stages = get_sales_stages(tenant_id)
    tenant_rows = TenantPipelineStage.query.filter_by(tenant_id=tenant_id).all()
    existing_sales = [row for row in tenant_rows if _is_sales_mapping(row)]
    had_mappings = bool(existing_sales)
    by_mapping_id = {row.tenant_pipeline_stage_mapping_id: row for row in existing_sales}
    by_master_id = {}
    for row in existing_sales:
        if row.pipeline_stage_id is not None:
            by_master_id.setdefault(row.pipeline_stage_id, row)

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
                if master_id is None or candidate.pipeline_stage_id in (None, master_id):
                    mapping = candidate

        if mapping is not None:
            retained_ids.add(mapping.tenant_pipeline_stage_mapping_id)
        resolved.append((item, mapping))

    removed = [row for row in existing_sales if row.tenant_pipeline_stage_mapping_id not in retained_ids]

    # Leads store the "effective" stage id: a mapping id once the board is customised,
    # a master id before that. Work out which old ids survive this save.
    if had_mappings:
        retained_old_ids = set(retained_ids)
    else:
        retained_old_ids = {item["pipeline_stage_id"] for item, _ in resolved if item["pipeline_stage_id"] is not None}
    dropped = [stage for stage in old_stages if stage["id"] not in retained_old_ids]

    if dropped:
        counts = db.session.execute(
            text(
                f"""
                SELECT stage_id, COUNT(*) AS n
                FROM {T("Lead_Master")}
                WHERE tenant_id = :tenant_id AND stage_id = ANY(:ids)
                GROUP BY stage_id
                """
            ),
            {"tenant_id": tenant_id, "ids": [stage["id"] for stage in dropped]},
        ).fetchall()
        if counts:
            names = {stage["id"]: stage["stage_name"] for stage in dropped}
            detail = ", ".join(f"{names.get(row.stage_id, row.stage_id)} ({row.n})" for row in counts)
            return (
                jsonify(
                    {
                        "error": f"These stages still have leads: {detail}. "
                        "Move those leads to another stage first."
                    }
                ),
                409,
            )

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
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
                db.session.add(mapping)
            else:
                mapping.stage_name = item["stage_name"]
                mapping.pipeline_stage_id = item["pipeline_stage_id"]
                mapping.description = item["description"]
                mapping.pipeline_type = SALES_PIPELINE_TYPE
            saved_mappings.append(mapping)

        db.session.flush()
        for index, mapping in enumerate(saved_mappings):
            mapping.preceding_stage_id = (
                saved_mappings[index - 1].tenant_pipeline_stage_mapping_id if index > 0 else None
            )

        for mapping in removed:
            mapping.preceding_stage_id = None
        if removed:
            db.session.flush()
        for mapping in removed:
            db.session.delete(mapping)

        # First customisation: re-point leads from master ids to the new mapping ids.
        # One statement, so a new id that equals another old id cannot chain-remap.
        if not had_mappings:
            old_ids, new_ids = [], []
            for (item, _), mapping in zip(resolved, saved_mappings):
                if item["pipeline_stage_id"] is not None:
                    old_ids.append(item["pipeline_stage_id"])
                    new_ids.append(mapping.tenant_pipeline_stage_mapping_id)
            if old_ids:
                db.session.execute(
                    text(
                        f"""
                        UPDATE {T("Lead_Master")} AS lm
                        SET stage_id = m.new_id
                        FROM unnest(CAST(:old_ids AS integer[]), CAST(:new_ids AS integer[])) AS m(old_id, new_id)
                        WHERE lm.tenant_id = :tenant_id AND lm.stage_id = m.old_id
                        """
                    ),
                    {"old_ids": old_ids, "new_ids": new_ids, "tenant_id": tenant_id},
                )

        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Unable to save pipeline stages")
        return jsonify({"error": "Unable to save pipeline stages. No changes were committed."}), 500

    return jsonify(
        {
            "message": "Pipeline stages saved",
            "pipeline_type": "sales",
            "stages": get_sales_stages(tenant_id),
        }
    ), 200


# ── Board data ─────────────────────────────────────────────────────────────


@pipeline_bp.route("", methods=["GET"])
@auth_required
def get_pipeline():
    tenant_id = get_tenant_id()
    if tenant_id is None:
        return jsonify({"error": "Tenant context missing"}), 401

    stages = get_sales_stages(tenant_id)
    by_id, _, _ = _stage_maps(stages)

    try:
        rows = db.session.execute(
            text(
                f"""
                SELECT
                    lm.lead_id,
                    lm."client_ID" AS client_id,
                    lm.assigned_employee_id,
                    lm.stage_id,
                    lm.lead_title,
                    lm.lead_description,
                    lm.lead_date,
                    lm.expected_value,
                    lm.currency_id,
                    lm.lead_source,
                    lm."qualification status" AS qualification_status,
                    lm.priority,
                    lm."expected_decision_date " AS expected_decision_date,
                    lm.last_contacted_date,
                    lm.next_followup_date,
                    lm.created_date,
                    lm.modified_date,
                    lm.won_at,
                    cm.client_company_name,
                    cm.address,
                    cm.post_code,
                    cm.client_phone,
                    cm.client_email,
                    em.employee_name
                FROM {T("Lead_Master")} lm
                LEFT JOIN {T("Client_Master")} cm
                    ON cm.client_id = lm."client_ID" AND cm.tenant_id = lm.tenant_id
                LEFT JOIN {T("Employee_Master")} em
                    ON em.employee_id = lm.assigned_employee_id AND em.tenant_id = lm.tenant_id
                WHERE lm.tenant_id = :tenant_id
                ORDER BY lm.created_date DESC NULLS LAST, lm.lead_id DESC
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchall()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Unable to load sales pipeline")
        return jsonify({"error": "Unable to load the sales pipeline"}), 500

    items = []
    for row in rows:
        stage = by_id.get(row.stage_id)
        orphaned = stage is None
        if orphaned and stages:
            stage = stages[0]  # never hide a lead whose stage was removed

        items.append(
            {
                "id": f"lead-{row.lead_id}",
                "lead_id": row.lead_id,
                "client_id": row.client_id,
                "company_name": row.client_company_name,
                "lead_title": row.lead_title,
                "description": row.lead_description,
                "stage_id": stage["id"] if stage else None,
                "stage": stage["stage_name"] if stage else None,
                "stage_role": stage["role"] if stage else None,
                "stage_orphaned": orphaned,
                "qualification_status": _as_int(row.qualification_status),
                "expected_value": float(row.expected_value) if row.expected_value is not None else None,
                "priority": row.priority,
                "lead_source": row.lead_source,
                "lead_date": _iso(row.lead_date),
                "expected_decision_date": _iso(row.expected_decision_date),
                "last_contacted_date": _iso(row.last_contacted_date),
                "next_followup_date": _iso(row.next_followup_date),
                "assigned_employee_id": row.assigned_employee_id,
                "salesperson": row.employee_name,
                "email": row.client_email,
                "phone": row.client_phone,
                "address": row.address,
                "post_code": row.post_code,
                "created_at": _iso(row.created_date),
                "stage_updated_at": _iso(row.modified_date or row.created_date),
                "won_at": _iso(row.won_at),
            }
        )

    return jsonify(items), 200


# ── Quotation lookup (gate before Proposal) ────────────────────────────────


def _quotation_source():
    if _QUOTATION_SOURCE:
        return _QUOTATION_SOURCE

    schema = _schema()
    table = _setting("QUOTATION_TABLE")
    if not table:
        for guess in ("Quotation_Master_new", "Quotation_Master", "Quotations", "Quotation"):
            qualified = f'"{schema}"."{guess}"' if schema else f'"{guess}"'
            found = db.session.execute(text("SELECT to_regclass(:name) AS oid"), {"name": qualified}).fetchone()
            if found and found.oid:
                table = guess
                break
    if not table:
        raise RuntimeError("Quotation table not found. Set QUOTATION_TABLE in the app config.")

    cols = db.session.execute(
        text(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = COALESCE(CAST(:schema AS text), current_schema())
              AND table_name = :table
            """
        ),
        {"schema": schema, "table": table},
    ).fetchall()
    names = {row.column_name for row in cols}

    def pick(*candidates):
        for candidate in candidates:
            for name in names:
                if name.lower() == candidate.lower():
                    return name
        return None

    client_col = pick("client_id", "client_ID", "customer_id")
    tenant_col = pick("tenant_id")
    if not client_col:
        raise RuntimeError(f"Could not find a client column on {table}")

    _QUOTATION_SOURCE.update({"table": table, "client_col": client_col, "tenant_col": tenant_col})
    return _QUOTATION_SOURCE


def _client_has_quotation(tenant_id, client_id):
    if client_id is None:
        return False
    source = _quotation_source()
    sql = f'SELECT 1 FROM {T(source["table"])} WHERE "{source["client_col"]}" = :client_id'
    params = {"client_id": client_id}
    if source["tenant_col"]:
        sql += f' AND "{source["tenant_col"]}" = :tenant_id'
        params["tenant_id"] = tenant_id
    sql += " LIMIT 1"
    return db.session.execute(text(sql), params).fetchone() is not None


def _sync_client_converted(tenant_id, client_id, won_stage_id):
    """Keep Client_Master.is_converted in step with the board: 1 while the company has
    at least one lead in the Won stage, 0 otherwise. Does NOT commit."""
    db.session.execute(
        text(
            f"""
            UPDATE {T("Client_Master")}
            SET is_converted = CASE WHEN EXISTS (
                    SELECT 1 FROM {T("Lead_Master")} lm
                    WHERE lm.tenant_id = :tenant_id
                      AND lm."client_ID" = :client_id
                      AND lm.stage_id = :won_stage_id
                ) THEN 1 ELSE 0 END,
                stage_updated_at = NOW()
            WHERE client_id = :client_id AND tenant_id = :tenant_id
            """
        ),
        {"tenant_id": tenant_id, "client_id": client_id, "won_stage_id": won_stage_id},
    )


# ── Stage changes ──────────────────────────────────────────────────────────


def _score_answers(answers):
    if not isinstance(answers, list) or len(answers) != QUESTION_COUNT:
        raise ValueError(f"Answer all {QUESTION_COUNT} qualification questions")
    score = 0
    for answer in answers:
        if isinstance(answer, bool) or not isinstance(answer, int) or not 0 <= answer <= MAX_ANSWER_SCORE:
            raise ValueError(f"Each answer must be a whole number from 0 to {MAX_ANSWER_SCORE}")
        score += answer
    return score


@pipeline_bp.route("/<int:lead_id>/stage", methods=["PATCH"])
@auth_required
def update_stage(lead_id):
    tenant_id = get_tenant_id()
    if tenant_id is None:
        return jsonify({"error": "Tenant context missing"}), 401

    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action") or "").strip().lower()
    questionnaire_completed = payload.get("questionnaire_completed") is True

    stages = get_sales_stages(tenant_id)
    by_id, by_role, position = _stage_maps(stages)
    qualification_stage = by_role.get("qualification")
    lost_stage = by_role.get("lost")
    won_stage = by_role.get("won")
    proposal_stage = by_role.get("proposal")

    try:
        lead = db.session.execute(
            text(
                f"""
                SELECT lead_id, stage_id, "client_ID" AS client_id,
                       "qualification status" AS qualification_status
                FROM {T("Lead_Master")}
                WHERE lead_id = :lead_id AND tenant_id = :tenant_id
                LIMIT 1
                """
            ),
            {"lead_id": lead_id, "tenant_id": tenant_id},
        ).fetchone()
        if not lead:
            return jsonify({"error": "Lead not found"}), 404

        current = by_id.get(lead.stage_id)
        current_role = current["role"] if current else None
        current_status = _as_int(lead.qualification_status)
        awaiting_decision = current_status == QS_PENDING or (
            current_status is None and current_role == "qualification"
        )

        questionnaire_score = None
        target = None
        new_status = current_status

        # 1) Admin decision on a lead waiting in Qualification
        if action in {"approve", "reject"}:
            if not _is_admin():
                return jsonify({"error": "Only an admin can approve or reject a qualification"}), 403
            if not qualification_stage:
                return jsonify({"error": "This pipeline has no Qualification stage"}), 409
            if not awaiting_decision:
                return jsonify({"error": "This lead is not waiting for a qualification decision"}), 409

            if action == "approve":
                target = by_role.get("opportunity")
                if not target:
                    next_index = position[qualification_stage["id"]] + 1
                    target = stages[next_index] if next_index < len(stages) else None
                    if target and target["role"] == "lost":
                        target = None
                new_status = QS_APPROVED
            else:
                target = lost_stage
                new_status = QS_REJECTED
            if not target:
                return jsonify({"error": "The stage this decision moves the lead to is not configured"}), 409

        # 2) Qualification questionnaire submitted
        elif questionnaire_completed:
            if not qualification_stage or not lost_stage:
                return jsonify({"error": "The qualification workflow is not configured for this pipeline"}), 409
            if awaiting_decision:
                return jsonify({"error": "This lead is already waiting for admin approval"}), 409
            try:
                questionnaire_score = _score_answers(payload.get("questionnaire_answers"))
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            if questionnaire_score <= QUALIFICATION_PASS_SCORE:
                target, new_status = lost_stage, QS_REJECTED
            else:
                target, new_status = qualification_stage, QS_PENDING

        # 3) Normal move
        else:
            if payload.get("qualification_status") is not None:
                return jsonify({"error": "qualification_status cannot be set directly"}), 400

            if payload.get("stage_id") is not None:
                requested_id = _as_int(payload.get("stage_id"))
                target = by_id.get(requested_id) if requested_id is not None else None
            else:
                wanted = str(payload.get("stage") or "").strip().casefold()
                if not wanted:
                    return jsonify({"error": "stage_id is required"}), 400
                target = next((s for s in stages if s["stage_name"].casefold() == wanted), None)
            if not target:
                return jsonify({"error": "Stage is not configured for this tenant"}), 400

            if target["id"] == lead.stage_id:
                return jsonify({"message": "Stage unchanged", "lead_id": lead_id, "stage_id": target["id"]}), 200
            if awaiting_decision:
                return (
                    jsonify({"error": "This lead is waiting for qualification approval. An admin must approve or reject it."}),
                    409,
                )
            if target["role"] == "qualification":
                return (
                    jsonify({"error": "Complete the qualification questionnaire to move a lead into Qualification"}),
                    400,
                )
            if {current_role, target["role"]} == {"won", "lost"}:
                return jsonify({"error": "A lead cannot be moved directly between Won and Lost"}), 409

            if (
                proposal_stage
                and target["role"] != "lost"
                and position[target["id"]] >= position[proposal_stage["id"]]
                and not _client_has_quotation(tenant_id, lead.client_id)
            ):
                return (
                    jsonify(
                        {
                            "error": f"A quotation is required before a lead can move to "
                            f"{target['stage_name']}. Create one for this company first.",
                            "code": "QUOTATION_REQUIRED",
                        }
                    ),
                    409,
                )

        result = db.session.execute(
            text(
                f"""
                UPDATE {T("Lead_Master")}
                SET stage_id = :stage_id,
                    "qualification status" = :qualification_status,
                    won_at = CASE
                        WHEN CAST(:won_stage_id AS integer) IS NOT NULL
                             AND :stage_id = CAST(:won_stage_id AS integer)
                             AND stage_id IS DISTINCT FROM CAST(:won_stage_id AS integer)
                        THEN CURRENT_TIMESTAMP
                        ELSE won_at
                    END,
                    modified_date = CURRENT_DATE
                WHERE lead_id = :lead_id AND tenant_id = :tenant_id
                RETURNING lead_id, won_at
                """
            ),
            {
                "stage_id": target["id"],
                "qualification_status": new_status,
                "won_stage_id": won_stage["id"] if won_stage else None,
                "lead_id": lead_id,
                "tenant_id": tenant_id,
            },
        ).fetchone()

        if won_stage and lead.client_id is not None and (target["role"] == "won" or current_role == "won"):
            _sync_client_converted(tenant_id, lead.client_id, won_stage["id"])

        db.session.commit()

    except RuntimeError as exc:
        db.session.rollback()
        current_app.logger.exception("Pipeline configuration error")
        return jsonify({"error": str(exc)}), 500
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Unable to update lead stage")
        return jsonify({"error": "Unable to update the lead stage"}), 500

    return jsonify(
        {
            "message": "Stage updated",
            "lead_id": lead_id,
            "stage_id": target["id"],
            "stage_name": target["stage_name"],
            "qualification_status": new_status,
            "questionnaire_score": questionnaire_score,
            "won_at": _iso(result.won_at) if result else None,
        }
    ), 200


def move_client_leads_to_proposal(tenant_id, client_id):
    """Opportunity -> Proposal for a company's leads. Does NOT commit; the caller does.

    Call this from the quotation create route, before its db.session.commit(), so the
    quotation and the stage move are saved together. Leads still waiting for a
    qualification decision, and leads already past Opportunity, are left alone.
    """
    _, by_role, _ = _stage_maps(get_sales_stages(tenant_id))
    opportunity_stage = by_role.get("opportunity")
    proposal_stage = by_role.get("proposal")
    if not opportunity_stage or not proposal_stage:
        return []

    rows = db.session.execute(
        text(
            f"""
            UPDATE {T("Lead_Master")}
            SET stage_id = :proposal_id, modified_date = CURRENT_DATE
            WHERE tenant_id = :tenant_id
              AND "client_ID" = :client_id
              AND stage_id = :opportunity_id
              AND COALESCE(CAST("qualification status" AS integer), 1) <> :pending
            RETURNING lead_id
            """
        ),
        {
            "proposal_id": proposal_stage["id"],
            "opportunity_id": opportunity_stage["id"],
            "tenant_id": tenant_id,
            "client_id": client_id,
            "pending": QS_PENDING,
        },
    ).fetchall()
    return [row.lead_id for row in rows]


@pipeline_bp.route("/company/<int:client_id>/move-to-proposal", methods=["POST"])
@auth_required
def move_company_leads_to_proposal(client_id):
    """Manual trigger for the same Opportunity -> Proposal move."""
    tenant_id = get_tenant_id()
    if tenant_id is None:
        return jsonify({"error": "Tenant context missing"}), 401

    try:
        lead_ids = move_client_leads_to_proposal(tenant_id, client_id)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Unable to move leads to proposal")
        return jsonify({"error": "Unable to move leads to the Proposal stage"}), 500

    return jsonify({"message": "Leads moved to Proposal", "moved": len(lead_ids), "lead_ids": lead_ids}), 200


# ── Create / import leads ──────────────────────────────────────────────────

_ALIASES = {
    "client_id": ("client_id",),
    "company_name": ("company_name", "company", "business_name", "client_company_name"),
    "website": ("company_website", "client_website", "website"),
    "company_number": ("vendor_registration_number", "company_number", "registration_number"),
    "address": ("address",),
    "post_code": ("post_code", "postcode", "pin_code", "postal_code", "zip"),
    "phone": ("client_phone", "client_mobile", "mobile_no", "tel_number", "phone", "mobile"),
    "email": ("client_email", "email"),
    "lead_title": ("lead_title", "title", "opportunity_title"),
    "description": ("lead_description", "opportunity_description", "description", "description_notes", "notes"),
    "lead_date": ("lead_date", "opportunity_date", "date"),
    "expected_value": ("expected_value", "opportunity_value", "value"),
    "priority": ("priority",),
    "lead_source": ("lead_source", "source"),
    "expected_decision_date": ("expected_decision_date", "decision_date"),
    "last_contacted_date": ("last_contacted_date",),
    "next_followup_date": ("next_followup_date", "next_follow_up_date"),
    "currency_id": ("currency_id",),
    "assigned_employee_id": ("assigned_employee_id",),
}


def _pick(data, field):
    for alias in _ALIASES[field]:
        value = data.get(alias)
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if value == "":
                continue
        return value
    return None


def _text_or_none(value):
    return None if value is None else str(value).strip() or None


def _insert_lead(tenant_id, raw, first_stage):
    data = {_norm_key(k): v for k, v in (raw or {}).items()}

    company_name = _text_or_none(_pick(data, "company_name"))
    client_id = _as_int(_pick(data, "client_id"))
    if not company_name and client_id is None:
        raise ValueError("Company Name is required")

    expected_value = _pick(data, "expected_value")
    if expected_value is not None:
        try:
            expected_value = int(float(str(expected_value).replace(",", "")))
        except ValueError:
            raise ValueError("Expected Value must be a number")

    dates = {
        field: _parse_date(_pick(data, field), label)
        for field, label in (
            ("lead_date", "Lead Date"),
            ("expected_decision_date", "Expected Decision Date"),
            ("last_contacted_date", "Last Contacted Date"),
            ("next_followup_date", "Next Follow-up Date"),
        )
    }

    assigned_employee_id = _as_int(_pick(data, "assigned_employee_id"))
    if assigned_employee_id is not None:
        owned = db.session.execute(
            text(f'SELECT 1 FROM {T("Employee_Master")} WHERE employee_id = :id AND tenant_id = :t'),
            {"id": assigned_employee_id, "t": tenant_id},
        ).fetchone()
        if not owned:
            raise ValueError("assigned_employee_id does not belong to this tenant")

    phone = _text_or_none(_pick(data, "phone"))
    email = _text_or_none(_pick(data, "email"))
    address = _text_or_none(_pick(data, "address"))
    post_code = _text_or_none(_pick(data, "post_code"))

    if client_id is not None:
        found = db.session.execute(
            text(f'SELECT client_id FROM {T("Client_Master")} WHERE client_id = :id AND tenant_id = :t'),
            {"id": client_id, "t": tenant_id},
        ).fetchone()
        if not found:
            raise ValueError("Company not found for this tenant")
    else:
        found = db.session.execute(
            text(
                f"""
                SELECT client_id FROM {T("Client_Master")}
                WHERE tenant_id = :t AND LOWER(TRIM(client_company_name)) = LOWER(TRIM(:name))
                ORDER BY client_id LIMIT 1
                """
            ),
            {"t": tenant_id, "name": company_name},
        ).fetchone()
        client_id = found.client_id if found else None

    # New companies must satisfy the Companies list filter (category + active status),
    # so take both ids from the company module itself when it is importable.
    try:
        from routes.company_routes import COMMERCIAL_CATEGORY_ID as company_category_id
        from routes.company_routes import ACTIVE_STATUS_ID as company_active_id
    except Exception:
        company_category_id = _as_int(_setting("COMMERCIAL_CATEGORY_ID", 1))
        company_active_id = _as_int(_setting("ACTIVE_STATUS_ID", 1))

    if client_id is not None:
        db.session.execute(
            text(
                f"""
                UPDATE {T("Client_Master")}
                SET client_phone = COALESCE(:phone, client_phone),
                    client_email = COALESCE(:email, client_email),
                    address = COALESCE(:address, address),
                    post_code = COALESCE(:post_code, post_code)
                WHERE client_id = :id AND tenant_id = :t
                """
            ),
            {"phone": phone, "email": email, "address": address, "post_code": post_code, "id": client_id, "t": tenant_id},
        )
    else:
        row = db.session.execute(
            text(
                f"""
                INSERT INTO {T("Client_Master")}
                    (tenant_id, client_company_name, client_phone, client_email, address, post_code,
                     client_website, company_number, status_id, "Client_Category_Master_ID",
                     created_by_user_id, created_at)
                VALUES
                    (:t, :name, :phone, :email, :address, :post_code,
                     :website, :company_number, :status_id, :category_id, :created_by, NOW())
                RETURNING client_id
                """
            ),
            {
                "t": tenant_id,
                "name": company_name,
                "phone": phone,
                "email": email,
                "address": address,
                "post_code": post_code,
                "website": _text_or_none(_pick(data, "website")),
                "company_number": _text_or_none(_pick(data, "company_number")),
                "status_id": company_active_id,
                "category_id": company_category_id,
                "created_by": _current_employee_id(tenant_id),
            },
        ).fetchone()
        client_id = row.client_id

    # Lead_Master.lead_id has no sequence: serialise inserts so ids are not reused.
    db.session.execute(text(f'LOCK TABLE {T("Lead_Master")} IN EXCLUSIVE MODE'))
    next_id = db.session.execute(text(f'SELECT COALESCE(MAX(lead_id), 0) + 1 AS next_id FROM {T("Lead_Master")}')).scalar()

    lead_title = _text_or_none(_pick(data, "lead_title")) or company_name
    if lead_title is None:
        lead_title = f"Lead {next_id}"

    db.session.execute(
        text(
            f"""
            INSERT INTO {T("Lead_Master")}
                (lead_id, tenant_id, "client_ID", assigned_employee_id, stage_id, lead_title,
                 lead_description, lead_date, expected_value, currency_id, lead_source,
                 "qualification status", priority, "expected_decision_date ", last_contacted_date,
                 next_followup_date, created_by, created_date, modified_date)
            VALUES
                (:lead_id, :t, :client_id, :assigned, :stage_id, :title,
                 :description, COALESCE(CAST(:lead_date AS date), CURRENT_DATE), :expected_value,
                 :currency_id, :lead_source, NULL, :priority, CAST(:decision AS date),
                 CAST(:last_contacted AS date), CAST(:followup AS date), :created_by,
                 CURRENT_DATE, CURRENT_DATE)
            """
        ),
        {
            "lead_id": next_id,
            "t": tenant_id,
            "client_id": client_id,
            "assigned": assigned_employee_id,
            "stage_id": first_stage["id"],
            "title": lead_title,
            "description": _text_or_none(_pick(data, "description")),
            "lead_date": dates["lead_date"],
            "expected_value": expected_value,
            "currency_id": _as_int(_pick(data, "currency_id")),
            "lead_source": _text_or_none(_pick(data, "lead_source")),
            "priority": _text_or_none(_pick(data, "priority")),
            "decision": dates["expected_decision_date"],
            "last_contacted": dates["last_contacted_date"],
            "followup": dates["next_followup_date"],
            "created_by": _valid_created_by(tenant_id),
        },
    )
    return next_id, client_id


def _row_error(exc):
    if isinstance(exc, ValueError):
        return str(exc)
    current_app.logger.warning("Lead import row rejected by the database: %s", exc)
    original = str(getattr(exc, "orig", exc)).strip().splitlines()
    return original[0][:200] if original else "The database rejected this row"


@pipeline_bp.route("/lead", methods=["POST"])
@auth_required
def create_lead():
    tenant_id = get_tenant_id()
    if tenant_id is None:
        return jsonify({"error": "Tenant context missing"}), 401

    stages = get_sales_stages(tenant_id)
    if not stages:
        return jsonify({"error": "No sales stages are configured for this tenant"}), 409

    try:
        lead_id, client_id = _insert_lead(tenant_id, request.get_json(silent=True) or {}, stages[0])
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400
    except SQLAlchemyError as exc:
        db.session.rollback()
        return jsonify({"error": "Unable to create the lead", "details": _row_error(exc)}), 500

    return jsonify({"message": "Lead created", "lead_id": lead_id, "client_id": client_id}), 201


@pipeline_bp.route("/leads/import", methods=["POST"])
@auth_required
def import_leads():
    """Import leads from rows the browser parsed out of an .xlsx file.

    Body: {"leads": [ {...row...}, ... ]}. Every lead starts in the board's first stage.
    A bad row is reported in `failed` and does not stop the rest.
    """
    tenant_id = get_tenant_id()
    if tenant_id is None:
        return jsonify({"error": "Tenant context missing"}), 401

    body = request.get_json(silent=True)
    records = body if isinstance(body, list) else (body or {}).get("leads")
    if not isinstance(records, list) or not records:
        return jsonify({"error": "leads must be a non-empty list"}), 400
    if len(records) > MAX_IMPORT_ROWS:
        return jsonify({"error": f"Import at most {MAX_IMPORT_ROWS} rows at a time"}), 400

    stages = get_sales_stages(tenant_id)
    if not stages:
        return jsonify({"error": "No sales stages are configured for this tenant"}), 409

    created, failed = [], []
    for row_number, record in enumerate(records, start=2):  # row 1 is the header row
        if not isinstance(record, dict):
            failed.append({"row": row_number, "error": "Row must be an object"})
            continue
        try:
            with db.session.begin_nested():
                lead_id, client_id = _insert_lead(tenant_id, record, stages[0])
            created.append({"row": row_number, "lead_id": lead_id, "client_id": client_id})
        except (ValueError, SQLAlchemyError) as exc:
            failed.append({"row": row_number, "error": _row_error(exc)})

    if not created:
        db.session.rollback()
        first = failed[0] if failed else {"row": "?", "error": "no rows"}
        return (
            jsonify(
                {
                    "error": f"No rows could be imported. Row {first['row']}: {first['error']}",
                    "failed": failed,
                }
            ),
            400,
        )

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Unable to commit lead import")
        return jsonify({"error": "Unable to save the imported leads"}), 500

    return jsonify({"message": "Import complete", "imported_count": len(created), "failed": failed}), 201