"""
backend/routes/company_training_routes.py

Company training routes on the normalised dev2 tables:

    Training_Master_New        one row per training PROGRAM for a company
                               (client + service + optional quotation + city)
    Training_Details_New       one row per BATCH of that program
                               (event no., dates, trainer, stage, remarks)
    Training_Participant_Data  one row per participant of a batch

In the API, "training_id" (and "service_id", kept for the frontend) is the
BATCH id, i.e. Training_Details_New.Training_Details_ID. Every batch belongs to
a Training_Master_New row; creating a batch creates/links that parent.

Participants are plain names (Sir: they are NOT added through Contacts); there is
no Contact_ID. The form accepts Product_Master item_name (or product_id / sku) for the course;
city (name) and trainer_name are resolved against City_Master and Employee_Master; ids may be sent instead.

Course names are read from Product_Master.item_name and course codes from Product_Master.sku.
Training_Master_New.Service_ID stores the matching Product_Master.product_id.

REQUIRED DB MIGRATION: run migration_training_new_tables.sql first (adds PO columns
and fees/address/state/pin on Training_Details_New, and QR/pass/training-records
columns on Training_Participant_Data). No existing column is
altered; the NOT NULL columns on Training_Participant_Data are filled by the code:
Pre_Test/Post_Test/Sweet_Points = 0, Is_Champion = FALSE, and MHE_ID = the
placeholder MHE_Master row given by config MHE_ID_UNASSIGNED until a real MHE type
is chosen.

Stages
------
Stage names are never written here. They come from Pipeline_Stage_Master via
config_helpers.load_training_stage_context. This file expects that context to
expose, besides the existing .names/.default/.awaiting/.po_received/.po_required:

    _stage_id_of(stages, name)  -> stage_id   (raises KeyError on an unknown name)
    _stage_name_of(stages, id)  -> stage name (None if unknown)

Configuration (app.config or environment, no defaults in code)
--------------------------------------------------------------
    DB_SCHEMA, MAX_BULK_BATCHES, CALENDAR_CONTACT_METHOD, CALENDAR_ENTRY_TYPE,
    CALENDAR_ENTRY_STATUS, CALENDAR_ENTRY_SOURCE, PO_UPLOAD_KIND,
    PARTICIPANT_ID_PREFIX, MHE_ID_UNASSIGNED (MHE_Master id of the placeholder row)
"""

import json
import uuid
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text

from .auth_helpers import token_required
from .company_routes import get_company_or_404
from .config_helpers import cfg, T, load_training_stage_context
from ..db import SessionLocal
from ..services.storage_service import upload_file, StorageError

company_training_bp = Blueprint("company_training", __name__)


# ---------------------------------------------------------------------------
# Shared SQL
# ---------------------------------------------------------------------------
# Verified column names:
#   Product_Master:   product_id, tenant_id, sku, item_name
#   City_Master:      city_id, city_name
#   Employee_Master:  employee_id, tenant_id, employee_name, is_active
#   City_Master:      city_id, city_name
#   Employee_Master:  employee_id, employee_name
def _batch_select():
    return f"""
        SELECT
            d."Training_Details_ID"  AS training_id,
            d."Training_ID"          AS master_id,
            d."Event_Number"         AS event_number,
            d."Batch_Start_Date"     AS date_from,
            d."Batch_End_Date"       AS date_to,
            d."No_Of_Participants"   AS participant_count,
            d."Trainer_ID"           AS trainer_id,
            d."Stage_ID"             AS stage_id,
            d."Remarks"              AS remarks,
            d."Training_Fees"        AS training_fees,
            d."Client_Address"       AS client_address,
            d."State"                AS state,
            d."Pin_Code"             AS pin_code,
            d.po_file_url, d.po_file_name, d.po_received_at,
            m."Client_ID"            AS client_id,
            m."Service_ID"           AS service_id_ref,
            m."Quotation_ID"         AS quotation_id,
            m."Training_Location_City_ID" AS city_id,
            pm.sku                    AS service_code,
            pm.item_name              AS service_title,
            NULL::text               AS duration,
            cy.city_name,
            e.employee_name          AS trainer_name
        FROM {T("Training_Details_New")} d
        JOIN {T("Training_Master_New")} m ON m."Training_ID" = d."Training_ID"
        LEFT JOIN {T("Product_Master")} pm ON pm.product_id = m."Service_ID" AND pm.tenant_id = m."Tenant_ID"
        LEFT JOIN {T("City_Master")} cy ON cy.city_id = m."Training_Location_City_ID"
        LEFT JOIN {T("Employee_Master")} e ON e.employee_id = d."Trainer_ID"
    """


def _participant_select():
    return f"""
        SELECT
            "Training_Participant_Data_ID" AS id,
            "Training_Details_ID"           AS training_id,
            "Participant_Name"              AS name,
            "MHE_ID"                        AS mhe_id,
            "Pre_Test"                      AS pre_test,
            "Post_Test"                     AS post_test,
            "Practical"                     AS practical,
            "Practical_out_of_Marks"        AS practical_out_of_marks,
            "Evaluation_Date"               AS evaluation_date,
            "Sweet_Points"                  AS sweet_points,
            "Is_Champion"                   AS is_champion,
            "Certificate_Number"            AS certificate_number,
            "Is_Pass"                       AS is_pass,
            "QR_Token"                      AS qr_token,
            "Participant_Unique_ID"         AS participant_unique_id,
            "Training_Records"              AS training_records
        FROM {T("Training_Participant_Data")}
    """


def _fetch_batch(session, tenant_id, training_id, company_id=None):
    sql = _batch_select() + ' WHERE d."Training_Details_ID" = :sid AND m."Tenant_ID" = :tid'
    params = {"sid": training_id, "tid": tenant_id}
    if company_id is not None:
        sql += ' AND m."Client_ID" = :cid'
        params["cid"] = company_id
    return session.execute(text(sql), params).fetchone()


def _fetch_participants(session, training_ids):
    """{training_id: [participant dict, ...]} for the given batches."""
    if not training_ids:
        return {}
    rows = session.execute(
        text(_participant_select() + ' WHERE "Training_Details_ID" = ANY(:ids) ORDER BY "Training_Participant_Data_ID"'),
        {"ids": list(training_ids)},
    ).fetchall()
    _unassigned_mhe_id(session)  # warm the cache used by serialize_participant
    out = {}
    for r in rows:
        out.setdefault(r.training_id, []).append(serialize_participant(r))
    return out


def serialize_participant(r):
    records = r.training_records
    if isinstance(records, str):
        try:
            records = json.loads(records)
        except Exception:
            records = []
    return {
        "id": str(r.id),   # the frontend types participant ids as strings
        "name": r.name,
        "mhe_id": None if r.mhe_id == _UNASSIGNED_MHE.get("id") else r.mhe_id,
        "pre_test": r.pre_test,
        "post_test": r.post_test,
        "practical": r.practical,
        "practical_out_of_marks": r.practical_out_of_marks,
        "evaluation_date": r.evaluation_date.isoformat() if r.evaluation_date else None,
        "sweet_points": r.sweet_points,
        "is_champion": r.is_champion,
        "certificate_number": r.certificate_number,
        "pass": bool(r.is_pass),
        "qr_token": r.qr_token,
        "participant_unique_id": r.participant_unique_id,
        "mainTraining": False,
        # Per-MHE records (type, graded pre/post answers...) kept as JSON in
        # Training_Participant_Data."Training_Records" so the participant popup
        # keeps working; the flat Pre_Test/Post_Test columns mirror the first record.
        "trainingRecords": records or [],
    }


def serialize_training(row, participants, stages):
    po_received_at = getattr(row, "po_received_at", None)
    return {
        "training_id":    row.training_id,
        "service_id":     row.training_id,          # legacy alias the frontend already reads
        "master_id":      row.master_id,
        "client_id":      row.client_id,
        "company_id":     row.client_id,
        "quotation_id":   row.quotation_id,
        "catalog_service_id": row.service_id_ref,   # Product_Master.product_id of the course
        "product_id":       row.service_id_ref,
        "service_code":   row.service_code,
        "service_title":  row.service_title,
        "duration":       row.duration,
        "training_from":  row.date_from.isoformat() if row.date_from else "",
        "training_to":    row.date_to.isoformat() if row.date_to else "",
        "trainer_id":     row.trainer_id,
        "trainer_name":   row.trainer_name,
        "city_id":        row.city_id,
        "city":           row.city_name,
        "state":          row.state,
        "pin_code":       row.pin_code,
        "client_address": row.client_address,
        "training_fees":  float(row.training_fees) if row.training_fees is not None else None,
        "remarks":        row.remarks,
        "participant_count": row.participant_count,
        "event_number":   row.event_number,
        "stage":          _stage_name_of(stages, row.stage_id) or stages.default,
        "participants":   participants or [],
        "po_file_url":    row.po_file_url,
        "po_file_name":   row.po_file_name,
        "po_received_at": po_received_at.isoformat() if po_received_at else None,
    }


def _serialize_one(session, tenant_id, training_id, stages, company_id=None):
    row = _fetch_batch(session, tenant_id, training_id, company_id)
    if not row:
        return None
    return serialize_training(row, _fetch_participants(session, [training_id]).get(training_id, []), stages)


def _pack_calendar_meta(meta: dict) -> str:
    return f"__meta__{json.dumps(meta)}__end_meta__"


def _calendar_settings():
    return {
        "contact_method": cfg("CALENDAR_CONTACT_METHOD", int),
        "entry_type": cfg("CALENDAR_ENTRY_TYPE"),
        "entry_status": cfg("CALENDAR_ENTRY_STATUS"),
        "entry_source": cfg("CALENDAR_ENTRY_SOURCE"),
    }


def _add_calendar_entry(session, calendar, company, company_id, detail_id, start, end, trainer_label):
    meta = {
        "title": f"{company.client_company_name} - {calendar['entry_type']}",
        "type": calendar["entry_type"],
        "status": calendar["entry_status"],
        "training_id": detail_id,
        "training_to": end.isoformat() if end else None,
        "team_member": trainer_label or "",
        "source": calendar["entry_source"],
    }
    session.execute(
        text(f"""
            INSERT INTO {T("Client_Interactions")}
                (client_id, contact_method, contact_date, notes)
            VALUES (:client_id, :contact_method, :contact_date, :notes)
        """),
        {
            "client_id": company_id,
            "contact_method": calendar["contact_method"],
            "contact_date": start,
            "notes": _pack_calendar_meta(meta),
        },
    )


def _trainer_label(session, trainer_id, tenant_id):
    row = session.execute(
        text(f"""
            SELECT employee_name
            FROM {T("Employee_Master")}
            WHERE employee_id = :i
              AND tenant_id = :tid
            LIMIT 1
        """),
        {"i": trainer_id, "tid": tenant_id},
    ).fetchone()
    return row.employee_name if row else ""


def _stage_id_of(stages, name):
    """stage name -> stage_id. Works whether or not the stage context has id_of()."""
    fn = getattr(stages, "id_of", None)
    if callable(fn):
        return fn(name)
    wanted = str(name or "").strip().lower()
    for s in stages.ordered:
        if str(s["stage_name"]).strip().lower() == wanted:
            return s["stage_id"]
    raise KeyError(name)
def _stage_name_of(stages, stage_id):
    """stage_id -> stage name (None if unknown). Works without name_of()."""
    fn = getattr(stages, "name_of", None)
    if callable(fn):
        return fn(stage_id)
    for s in stages.ordered:
        if s["stage_id"] == stage_id:
            return s["stage_name"]
    return None
def _validate_new_batch_stage(stage, stages, errors):
    """A new batch can't start in the awaiting stage or in a PO-gated stage."""
    if stage not in stages.names or stage == stages.awaiting:
        errors["stage"] = "Invalid stage for a new batch"
    elif stage in stages.po_required and stage != stages.default:
        errors["stage"] = (
            "A new batch can't start in this stage. "
            f"Create it as {stages.default}, then upload the PO."
        )


def _parse_date_required(value, field, errors):
    if value in (None, ""):
        errors[field] = f"'{field}' is required"
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        errors[field] = f"'{field}' must be a valid date in YYYY-MM-DD format"
        return None


def _parse_int_required(value, field, errors):
    try:
        return int(value)
    except (ValueError, TypeError):
        errors[field] = f"'{field}' is required and must be a number"
        return None


def _parse_count(value, field, errors):
    if value in (None, ""):
        return None
    try:
        n = int(value)
        if n < 0:
            errors[field] = "Participant count cannot be negative"
        return n
    except (ValueError, TypeError):
        errors[field] = "Participant count must be a number"
        return None


def _clean_participants(raw):
    out = []
    for p in (raw or []):
        name = (p.get("name") or "").strip()
        if name:
            out.append({"name": name, "mhe_id": p.get("mhe_id")})
    return out


def _marks_from_records(records):
    """(pre, post) marks from the first training record that has each score."""
    def first(key):
        for r in records or []:
            v = (r or {}).get(key)
            if isinstance(v, (int, float)):
                return int(round(v))
        return None
    return first("preTestObtained"), first("postTestObtained")


def _as_int(value):
    """Participant ids reach the API as strings ("12"); the column is bigint."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _resolve_service_id(session, data, errors, tenant_id, field="service_id"):
    """Resolve the selected course from Product_Master, never Services_Master."""
    direct = data.get("product_id") or data.get("catalog_service_id") or data.get("service_id")

    if str(direct or "").isdigit():
        row = session.execute(
            text(f"""
                SELECT product_id AS i
                FROM {T("Product_Master")}
                WHERE product_id = :pid AND tenant_id = :tid
                LIMIT 1
            """),
            {"pid": int(direct), "tid": tenant_id},
        ).fetchone()
        if row:
            return int(row.i)
        errors[field] = "Selected course was not found in Product_Master for this tenant"
        return None

    item_name = (data.get("item_name") or data.get("service_title") or "").strip()
    sku = (data.get("sku") or data.get("item_code") or data.get("service_code") or "").strip()
    if not item_name and not sku:
        errors[field] = "Course item_name is required"
        return None

    row = session.execute(
        text(f"""
            SELECT product_id AS i
            FROM {T("Product_Master")}
            WHERE tenant_id = :tid
              AND ((:item_name <> '' AND LOWER(item_name) = LOWER(:item_name))
                   OR (:sku <> '' AND UPPER(sku) = UPPER(:sku)))
            ORDER BY CASE WHEN :item_name <> '' AND LOWER(item_name) = LOWER(:item_name) THEN 0 ELSE 1 END
            LIMIT 1
        """),
        {"item_name": item_name, "sku": sku, "tid": tenant_id},
    ).fetchone()
    if not row:
        errors[field] = f"Course '{item_name or sku}' was not found in Product_Master for this tenant"
        return None
    return int(row.i)


def _resolve_city_id(session, data, errors, field="city_id"):
    """City -> City_Master.city_id. Accepts city_id, or the city name the form sends."""
    direct = data.get("city_id")
    if str(direct or "").isdigit():
        return int(direct)
    name = (data.get("city") or "").strip()
    if not name:
        errors[field] = "City is required"
        return None
    row = session.execute(
        text(f'SELECT city_id AS i FROM {T("City_Master")} WHERE LOWER(city_name) = LOWER(:n) LIMIT 1'),
        {"n": name},
    ).fetchone()
    if not row:
        errors[field] = f"City '{name}' was not found in City_Master"
        return None
    return int(row.i)


def _resolve_trainer_id(session, raw_id, raw_name, errors, tenant_id, field="trainer_id"):
    """Resolve an active trainer inside the current tenant only."""
    if str(raw_id or "").isdigit():
        row = session.execute(
            text(f"""
                SELECT employee_id AS i
                FROM {T("Employee_Master")}
                WHERE employee_id = :i
                  AND tenant_id = :tid
                  AND is_active IS TRUE
                LIMIT 1
            """),
            {"i": int(raw_id), "tid": tenant_id},
        ).fetchone()
        if row:
            return int(row.i)
        errors[field] = "Selected trainer was not found or is inactive for this tenant"
        return None

    name = (raw_name or "").strip()
    if not name:
        errors[field] = "Trainer is required"
        return None

    row = session.execute(
        text(f"""
            SELECT employee_id AS i
            FROM {T("Employee_Master")}
            WHERE LOWER(employee_name) = LOWER(:n)
              AND tenant_id = :tid
              AND is_active IS TRUE
            ORDER BY employee_id
            LIMIT 1
        """),
        {"n": name, "tid": tenant_id},
    ).fetchone()
    if not row:
        errors[field] = f"Active trainer '{name}' was not found for this tenant"
        return None
    return int(row.i)


def _parse_fees(value, errors, field="training_fees"):
    if value in (None, ""):
        return None
    try:
        fees = float(value)
        if fees < 0:
            errors[field] = "Training fees cannot be negative"
        return fees
    except (ValueError, TypeError):
        errors[field] = "Training fees must be a number"
        return None


def _parse_location(data, errors):
    """Fields with no column in the original tables; stored in the new columns on Training_Details_New."""
    pin = (data.get("pin_code") or "").strip() or None
    if pin and not pin.isdigit():
        errors["pin_code"] = "PIN code must contain digits only"
    return {
        "client_address": (data.get("client_address") or "").strip() or None,
        "state": (data.get("state") or "").strip() or None,
        "pin_code": pin,
    }


def _next_event_base(session, tenant_id) -> int:
    """Global event-number sequence, scoped to the tenant."""
    row = session.execute(
        text(f"""
            SELECT MAX(NULLIF(regexp_replace(d."Event_Number", '[^0-9]', '', 'g'), '')::int) AS max_event_no
            FROM {T("Training_Details_New")} d
            JOIN {T("Training_Master_New")} m ON m."Training_ID" = d."Training_ID"
            WHERE m."Tenant_ID" = :tid
        """),
        {"tid": tenant_id},
    ).fetchone()
    return (row.max_event_no or 0) + 1


def _insert_master(session, tenant_id, company_id, service_id, quotation_id, city_id, stage_id, start, end):
    return session.execute(
        text(f"""
            INSERT INTO {T("Training_Master_New")}
                ("Quotation_ID", "Tenant_ID", "Client_ID", "Service_ID",
                 "Training_Start_Date", "Training_End_Date",
                 "Training_Location_City_ID", "Stage_ID", "Created_At")
            VALUES (:q, :t, :c, :s, :sd, :ed, :city, :stage, NOW())
            RETURNING "Training_ID"
        """),
        {"q": quotation_id, "t": tenant_id, "c": company_id, "s": service_id,
         "sd": start, "ed": end, "city": city_id, "stage": stage_id},
    ).fetchone()[0]


def _insert_batch(session, master_id, b, stage_id):
    count = b["participant_count"]
    if count is None:
        count = len(b["participants"])
    detail_id = session.execute(
        text(f"""
            INSERT INTO {T("Training_Details_New")}
                ("Training_ID", "Event_Number", "Batch_Start_Date", "Batch_End_Date",
                 "No_Of_Participants", "Trainer_ID", "Stage_ID", "Remarks", created_at,
                 "Training_Fees", "Client_Address", "State", "Pin_Code")
            VALUES (:m, :ev, :sd, :ed, :cnt, :tr, :stage, :rem, NOW(),
                    :fees, :addr, :state, :pin)
            RETURNING "Training_Details_ID"
        """),
        {"m": master_id, "ev": b["event_number"], "sd": b["training_from"], "ed": b["training_to"],
         "cnt": count, "tr": b["trainer_id"], "stage": stage_id, "rem": b.get("remarks"),
         "fees": b.get("training_fees"), "addr": b.get("client_address"),
         "state": b.get("state"), "pin": b.get("pin_code")},
    ).fetchone()[0]
    for p in b["participants"]:
        _insert_participant(session, detail_id, p["name"], p.get("mhe_id"))
    return detail_id


_UNASSIGNED_MHE = {}
def _unassigned_mhe_id(session):
    """MHE_Master id of the 'Unassigned' placeholder. Uses MHE_ID_UNASSIGNED when
    configured, otherwise finds the row named 'Unassigned' (cached)."""
    if "id" in _UNASSIGNED_MHE:
        return _UNASSIGNED_MHE["id"]
    try:
        value = cfg("MHE_ID_UNASSIGNED", int)
    except Exception:
        row = session.execute(
            text(f'''SELECT "MHE_ID" FROM {T("MHE_Master")}
                     WHERE LOWER(TRIM("MHE_Name")) = 'unassigned'
                     ORDER BY "MHE_ID" LIMIT 1''')
        ).fetchone()
        if not row:
            raise RuntimeError(
                "MHE_ID_UNASSIGNED is not configured and MHE_Master has no 'Unassigned' row"
            )
        value = int(row[0])
    _UNASSIGNED_MHE["id"] = value
    return value
def _insert_participant(session, detail_id, name, mhe_id=None):
    """
    The existing NOT NULL columns can't be changed, so they are filled here:
    tests/points start at 0, champion FALSE, and MHE_ID falls back to the
    placeholder MHE_Master row until a real MHE type is chosen.
    """
    if mhe_id in (None, ""):
        mhe_id = _unassigned_mhe_id(session)
    return session.execute(
        text(f"""
            INSERT INTO {T("Training_Participant_Data")}
                ("Training_Details_ID", "Participant_Name", "MHE_ID",
                 "Pre_Test", "Post_Test", "Sweet_Points", "Is_Champion")
            VALUES (:d, :n, :mhe, 0, 0, 0, FALSE)
            RETURNING "Training_Participant_Data_ID"
        """),
        {"d": detail_id, "n": name, "mhe": int(mhe_id)},
    ).fetchone()[0]


def _resync_master(session, master_id):
    """Keep the program's start/end equal to its earliest/latest batch."""
    session.execute(
        text(f"""
            UPDATE {T("Training_Master_New")} m
            SET "Training_Start_Date" = x.s, "Training_End_Date" = x.e
            FROM (SELECT MIN("Batch_Start_Date") AS s, MAX("Batch_End_Date") AS e
                  FROM {T("Training_Details_New")} WHERE "Training_ID" = :m) x
            WHERE m."Training_ID" = :m
        """),
        {"m": master_id},
    )


# ============================================================================
# POST /companies/<company_id>/training — create ONE program with ONE batch
#
# Body: product_id/item_name (Product_Master course), city_id, trainer_id, training_from,
#       training_to, event_number, quotation_id?, participant_count?, remarks?,
#       stage?, participants: [{name}]
# ============================================================================
@company_training_bp.route("/companies/<int:company_id>/training", methods=["POST"])
@token_required
def create_company_training_session(company_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        company = get_company_or_404(
            session, company_id, tenant_id, columns="client_id, client_company_name"
        )
        if not company:
            return jsonify({"error": "Company not found"}), 404

        stages = load_training_stage_context(session)
        calendar = _calendar_settings()

        data = request.get_json(silent=True) or {}
        errors = {}

        service_id = _resolve_service_id(session, data, errors, tenant_id)
        city_id = _resolve_city_id(session, data, errors)
        trainer_id = _resolve_trainer_id(session, data.get("trainer_id"), data.get("trainer_name"), errors, tenant_id)
        fees = _parse_fees(data.get("training_fees"), errors)
        location = _parse_location(data, errors)
        quotation_id = data.get("quotation_id")
        quotation_id = int(quotation_id) if str(quotation_id or "").isdigit() else None

        training_from = _parse_date_required(data.get("training_from"), "training_from", errors)
        training_to = _parse_date_required(data.get("training_to"), "training_to", errors)
        if training_from and training_to and training_to < training_from:
            errors["training_to"] = "Training end date cannot be before the start date"

        participant_count = _parse_count(data.get("participant_count"), "participant_count", errors)

        event_number = (data.get("event_number") or "").strip()
        if not event_number:
            errors["event_number"] = "Event Number is required"

        stage = (data.get("stage") or stages.default).strip()
        # The PO is uploaded AFTER the batch exists, so a batch can never start in
        # Awaiting or a PO-gated stage: start it in the default stage instead.
        if stage == stages.awaiting or stage in stages.po_required:
            stage = stages.default
        _validate_new_batch_stage(stage, stages, errors)

        if errors:
            return jsonify({"error": "Validation failed: " + "; ".join(str(v) for v in errors.values()), "details": errors}), 400

        stage_id = _stage_id_of(stages, stage)
        batch = {
            "training_from": training_from,
            "training_to": training_to,
            "trainer_id": trainer_id,
            "event_number": event_number,
            "participant_count": participant_count,
            "participants": _clean_participants(data.get("participants")),
            "remarks": (data.get("remarks") or "").strip() or None,
            "training_fees": fees,
            **location,
        }

        master_id = _insert_master(session, tenant_id, company_id, service_id, quotation_id,
                                   city_id, stage_id, training_from, training_to)
        detail_id = _insert_batch(session, master_id, batch, stage_id)

        _add_calendar_entry(session, calendar, company, company_id, detail_id,
                            training_from, training_to, _trainer_label(session, trainer_id, tenant_id))
        session.commit()

        return jsonify({
            "success": True,
            "message": "Training session saved successfully",
            "training_id": detail_id,
            "service_id": detail_id,
            "master_id": master_id,
        }), 201

    except Exception as e:
        session.rollback()
        current_app.logger.exception(e)
        return jsonify({"error": "Failed to save training session", "details": str(e)}), 500
    finally:
        session.close()


# ============================================================================
# POST /companies/<company_id>/training/bulk — ONE program, several batches
#
# Body:
# {
#   "shared":  { service_id, city_id, quotation_id?, stage? },
#   "batches": [ { training_from, training_to, trainer_id,
#                  event_number?,  # blank => next in the global sequence
#                  participant_count?, remarks?,
#                  participants: [ {name} ] }, ... ]
# }
# Everything is saved in ONE transaction: if any batch is invalid, nothing is.
# ============================================================================
@company_training_bp.route("/companies/<int:company_id>/training/bulk", methods=["POST"])
@token_required
def create_company_training_batches_bulk(company_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        company = get_company_or_404(
            session, company_id, tenant_id, columns="client_id, client_company_name"
        )
        if not company:
            return jsonify({"error": "Company not found"}), 404

        stages = load_training_stage_context(session)
        calendar = _calendar_settings()
        max_bulk_batches = cfg("MAX_BULK_BATCHES", int)

        data = request.get_json(silent=True) or {}
        shared = data.get("shared") or {}
        batches_in = data.get("batches") or []
        errors = {}

        if not isinstance(batches_in, list) or len(batches_in) == 0:
            return jsonify({"error": "At least one batch is required"}), 400
        if len(batches_in) > max_bulk_batches:
            return jsonify({"error": f"You can create at most {max_bulk_batches} batches at once"}), 400

        service_id = _resolve_service_id(session, shared, errors, tenant_id)
        city_id = _resolve_city_id(session, shared, errors)
        fees = _parse_fees(shared.get("training_fees"), errors)
        location = _parse_location(shared, errors)
        quotation_id = shared.get("quotation_id")
        quotation_id = int(quotation_id) if str(quotation_id or "").isdigit() else None

        stage = (shared.get("stage") or stages.default).strip()
        if stage == stages.awaiting or stage in stages.po_required:
            stage = stages.default
        _validate_new_batch_stage(stage, stages, errors)

        prepared = []
        for i, b in enumerate(batches_in):
            prefix = f"batches[{i}]"
            b = b or {}
            t_from = _parse_date_required(b.get("training_from"), f"{prefix}.training_from", errors)
            t_to = _parse_date_required(b.get("training_to"), f"{prefix}.training_to", errors)
            if t_from and t_to and t_to < t_from:
                errors[f"{prefix}.training_to"] = "Training end date cannot be before the start date"
            trainer_id = _resolve_trainer_id(
                session, b.get("trainer_id"), b.get("trainer_name"), errors, tenant_id, f"{prefix}.trainer_id"
            )
            count = _parse_count(b.get("participant_count"), f"{prefix}.participant_count", errors)

            prepared.append({
                "training_from": t_from,
                "training_to": t_to,
                "trainer_id": trainer_id,
                "event_number": str(b.get("event_number") or "").strip(),
                "participant_count": count,
                "participants": _clean_participants(b.get("participants")),
                "remarks": (shared.get("remarks") or b.get("remarks") or "").strip() or None,
                "training_fees": fees,
                **location,
            })

        explicit_numbers = [p["event_number"] for p in prepared if p["event_number"]]
        if len(set(explicit_numbers)) != len(explicit_numbers):
            errors["event_number"] = "Each batch needs a different Event Number"

        if errors:
            return jsonify({"error": "Validation failed: " + "; ".join(str(v) for v in errors.values()), "details": errors}), 400

        used = set(explicit_numbers)
        next_no = _next_event_base(session, tenant_id)
        for p in prepared:
            if not p["event_number"]:
                while str(next_no) in used:
                    next_no += 1
                p["event_number"] = str(next_no)
                used.add(str(next_no))
                next_no += 1

        stage_id = _stage_id_of(stages, stage)
        master_id = _insert_master(
            session, tenant_id, company_id, service_id, quotation_id, city_id, stage_id,
            min(p["training_from"] for p in prepared),
            max(p["training_to"] for p in prepared),
        )

        created = []
        for p in prepared:
            detail_id = _insert_batch(session, master_id, p, stage_id)
            _add_calendar_entry(session, calendar, company, company_id, detail_id,
                                p["training_from"], p["training_to"],
                                _trainer_label(session, p["trainer_id"], tenant_id))
            created.append({"training_id": detail_id, "event_number": p["event_number"]})

        session.commit()

        return jsonify({
            "success": True,
            "message": f"{len(created)} training batches saved successfully",
            "count": len(created),
            "master_id": master_id,
            "batches": created,
        }), 201

    except Exception as e:
        session.rollback()
        current_app.logger.exception(e)
        return jsonify({"error": "Failed to save training batches", "details": str(e)}), 500
    finally:
        session.close()


def generate_next_participant_unique_id(db_session, tenant_id, year=None):
    """
    Sequential, human-readable ID like <PREFIX>-2026-00123.

    Prefix from config (PARTICIPANT_ID_PREFIX). Only the trailing digit run is
    used for the sequence, so the year never inflates the counter. Tenant-scoped.
    Not row-locked: truly simultaneous passes carry a small race-condition risk.
    """
    prefix = cfg("PARTICIPANT_ID_PREFIX")
    year = year or datetime.utcnow().year

    row = db_session.execute(
        text(f"""
            SELECT COALESCE(MAX(
                NULLIF(
                    substring(p."Participant_Unique_ID" from '^[^-]+-[0-9]{{4}}-([0-9]{{1,6}})$'),
                    ''
                )::bigint
            ), 0) AS max_id
            FROM {T("Training_Participant_Data")} p
            JOIN {T("Training_Details_New")} d ON d."Training_Details_ID" = p."Training_Details_ID"
            JOIN {T("Training_Master_New")} m ON m."Training_ID" = d."Training_ID"
            WHERE m."Tenant_ID" = :tid
              AND p."Participant_Unique_ID" IS NOT NULL
        """),
        {"tid": tenant_id},
    ).fetchone()
    return f"{prefix}-{year}-{(row.max_id or 0) + 1:05d}"


# ============================================================================
# GET /companies/<company_id>/training — list every batch for this company
# ============================================================================
@company_training_bp.route("/companies/<int:company_id>/training", methods=["GET"])
@token_required
def list_company_training_sessions(company_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        company = get_company_or_404(session, company_id, tenant_id, columns="client_id")
        if not company:
            return jsonify({"error": "Company not found"}), 404

        stages = load_training_stage_context(session)
        rows = session.execute(
            text(_batch_select() + """
                WHERE m."Client_ID" = :cid AND m."Tenant_ID" = :tid
                ORDER BY d."Training_Details_ID" DESC
            """),
            {"cid": company_id, "tid": tenant_id},
        ).fetchall()
        people = _fetch_participants(session, [r.training_id for r in rows])

        return jsonify([serialize_training(r, people.get(r.training_id, []), stages) for r in rows]), 200

    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ============================================================================
# GET /companies/<company_id>/training/<training_id> — a single batch
# ============================================================================
@company_training_bp.route("/companies/<int:company_id>/training/<int:training_id>", methods=["GET"])
@token_required
def get_company_training_session(company_id, training_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        company = get_company_or_404(session, company_id, tenant_id, columns="client_id")
        if not company:
            return jsonify({"error": "Company not found"}), 404

        stages = load_training_stage_context(session)
        result = _serialize_one(session, tenant_id, training_id, stages, company_id)
        if not result:
            return jsonify({"error": "Training session not found"}), 404
        return jsonify(result), 200

    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ============================================================================
# PATCH /companies/<company_id>/training/<training_id> — edit batch fields
#
# Batch fields  (Training_Details_New): training_from, training_to, trainer_id,
#                                       event_number, remarks, participant_count
# Program fields (Training_Master_New): service_id, city_id, quotation_id
# ============================================================================
@company_training_bp.route("/companies/<int:company_id>/training/<int:training_id>", methods=["PATCH"])
@token_required
def update_company_training_session(company_id, training_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        company = get_company_or_404(session, company_id, tenant_id, columns="client_id")
        if not company:
            return jsonify({"error": "Company not found"}), 404

        stages = load_training_stage_context(session)

        existing = _fetch_batch(session, tenant_id, training_id, company_id)
        if not existing:
            return jsonify({"error": "Training session not found"}), 404

        data = request.get_json(silent=True) or {}
        errors = {}

        d_sets, d_params = [], {"sid": training_id}
        m_sets, m_params = [], {"mid": existing.master_id}

        new_from, new_to = existing.date_from, existing.date_to
        if "training_from" in data:
            new_from = _parse_date_required(data.get("training_from"), "training_from", errors)
            d_sets.append('"Batch_Start_Date" = :date_from')
            d_params["date_from"] = new_from
        if "training_to" in data:
            new_to = _parse_date_required(data.get("training_to"), "training_to", errors)
            d_sets.append('"Batch_End_Date" = :date_to')
            d_params["date_to"] = new_to
        if new_from and new_to and new_to < new_from:
            errors["training_to"] = "Training end date cannot be before the start date"

        if "event_number" in data:
            ev = (data.get("event_number") or "").strip()
            if not ev:
                errors["event_number"] = "Event Number is required"
            d_sets.append('"Event_Number" = :event_number')
            d_params["event_number"] = ev

        if "trainer_id" in data or "trainer_name" in data:
            tid_ = _resolve_trainer_id(session, data.get("trainer_id"), data.get("trainer_name"), errors, tenant_id)
            d_sets.append('"Trainer_ID" = :trainer_id')
            d_params["trainer_id"] = tid_

        if "training_fees" in data:
            d_sets.append('"Training_Fees" = :fees')
            d_params["fees"] = _parse_fees(data.get("training_fees"), errors)

        if any(k in data for k in ("client_address", "state", "pin_code")):
            loc = _parse_location(data, errors)
            for key, column in (("client_address", "Client_Address"), ("state", "State"), ("pin_code", "Pin_Code")):
                if key in data:
                    d_sets.append(f'"{column}" = :{key}')
                    d_params[key] = loc[key]

        if "remarks" in data:
            d_sets.append('"Remarks" = :remarks')
            d_params["remarks"] = (data.get("remarks") or "").strip() or None

        if "participant_count" in data:
            cnt = _parse_count(data.get("participant_count"), "participant_count", errors)
            if cnt is None:
                errors.setdefault("participant_count", "Participant count is required")
            d_sets.append('"No_Of_Participants" = :cnt')
            d_params["cnt"] = cnt

        if any(k in data for k in ("service_id", "catalog_service_id", "product_id", "item_name", "service_title", "sku", "item_code", "service_code")):
            m_sets.append('"Service_ID" = :service_id')
            m_params["service_id"] = _resolve_service_id(session, data, errors, tenant_id)
        if "city_id" in data or "city" in data:
            m_sets.append('"Training_Location_City_ID" = :city_id')
            m_params["city_id"] = _resolve_city_id(session, data, errors)
        if "quotation_id" in data:
            q = data.get("quotation_id")
            m_sets.append('"Quotation_ID" = :quotation_id')
            m_params["quotation_id"] = int(q) if str(q or "").isdigit() else None

        if errors:
            return jsonify({"error": "Validation failed: " + "; ".join(str(v) for v in errors.values()), "details": errors}), 400
        if not d_sets and not m_sets:
            return jsonify({"error": "No updatable fields provided"}), 400

        if d_sets:
            session.execute(
                text(f'UPDATE {T("Training_Details_New")} SET {", ".join(d_sets)} WHERE "Training_Details_ID" = :sid'),
                d_params,
            )
        if m_sets:
            session.execute(
                text(f'UPDATE {T("Training_Master_New")} SET {", ".join(m_sets)} WHERE "Training_ID" = :mid'),
                m_params,
            )
        if "training_from" in data or "training_to" in data:
            _resync_master(session, existing.master_id)

        session.commit()
        return jsonify(_serialize_one(session, tenant_id, training_id, stages, company_id)), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(e)
        return jsonify({"error": "Failed to update training session", "details": str(e)}), 500
    finally:
        session.close()


# ============================================================================
# PATCH /companies/<company_id>/training/<training_id>/participants
#   action = add     {name}
#   action = remove  {participant_id}
#   action = update  {participant_id, participant: {...fields...}}
# ============================================================================
_PARTICIPANT_FIELDS = {
    "name": "Participant_Name",
    "mhe_id": "MHE_ID",
    "pre_test": "Pre_Test",
    "post_test": "Post_Test",
    "practical": "Practical",
    "practical_out_of_marks": "Practical_out_of_Marks",
    "evaluation_date": "Evaluation_Date",
    "sweet_points": "Sweet_Points",
    "is_champion": "Is_Champion",
    "certificate_number": "Certificate_Number",
    "pass": "Is_Pass",
}


@company_training_bp.route(
    "/companies/<int:company_id>/training/<int:training_id>/participants",
    methods=["PATCH"],
)
@token_required
def modify_company_training_participants(company_id, training_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        company = get_company_or_404(session, company_id, tenant_id, columns="client_id")
        if not company:
            return jsonify({"error": "Company not found"}), 404

        batch = _fetch_batch(session, tenant_id, training_id, company_id)
        if not batch:
            return jsonify({"error": "Training session not found"}), 404

        data = request.get_json(silent=True) or {}
        action = data.get("action")

        def owned(pid):
            return session.execute(
                text(f"""
                    SELECT 1 FROM {T("Training_Participant_Data")}
                    WHERE "Training_Participant_Data_ID" = :p AND "Training_Details_ID" = :d
                """),
                {"p": pid, "d": training_id},
            ).fetchone()

        if action == "add":
            name = (data.get("name") or "").strip()
            if not name:
                return jsonify({"error": "Participant name is required"}), 400
            _insert_participant(session, training_id, name, data.get("mhe_id"))

        elif action == "remove":
            pid = _as_int(data.get("participant_id"))
            if not pid:
                return jsonify({"error": "participant_id is required"}), 400
            session.execute(
                text(f"""
                    DELETE FROM {T("Training_Participant_Data")}
                    WHERE "Training_Participant_Data_ID" = :p AND "Training_Details_ID" = :d
                """),
                {"p": pid, "d": training_id},
            )

        elif action == "update":
            pid = _as_int(data.get("participant_id"))
            updates = data.get("participant") or {}
            if not pid:
                return jsonify({"error": "participant_id is required"}), 400
            if not owned(pid):
                return jsonify({"error": "Participant not found in this session"}), 404

            sets, params = [], {"p": pid}
            for key, column in _PARTICIPANT_FIELDS.items():
                if key in updates:
                    value = updates[key]
                    # NOT NULL columns can't be cleared: fall back to their starting value.
                    if value in (None, ""):
                        if key == "mhe_id":
                            value = _unassigned_mhe_id(session)
                        elif key in ("pre_test", "post_test", "sweet_points"):
                            value = 0
                        elif key == "is_champion":
                            value = False
                    sets.append(f'"{column}" = :{key}')
                    params[key] = value

            # Per-MHE training records live as JSON; the flat Pre_Test/Post_Test
            # columns mirror the first record that has a score.
            if "trainingRecords" in updates:
                records = updates.get("trainingRecords") or []
                sets.append('"Training_Records" = CAST(:training_records AS jsonb)')
                params["training_records"] = json.dumps(records)
                pre_mark, post_mark = _marks_from_records(records)
                if pre_mark is not None:
                    sets.append('"Pre_Test" = :pre_mark')
                    params["pre_mark"] = pre_mark
                if post_mark is not None:
                    sets.append('"Post_Test" = :post_mark')
                    params["post_mark"] = post_mark
            if sets:
                session.execute(
                    text(f"""
                        UPDATE {T("Training_Participant_Data")}
                        SET {", ".join(sets)}
                        WHERE "Training_Participant_Data_ID" = :p
                    """),
                    params,
                )

            # Generate QR details once the participant has passed.
            cur = session.execute(
                text(f"""
                    SELECT "Is_Pass" AS is_pass, "QR_Token" AS qr_token
                    FROM {T("Training_Participant_Data")}
                    WHERE "Training_Participant_Data_ID" = :p
                """),
                {"p": pid},
            ).fetchone()

            if cur.is_pass and not cur.qr_token:
                # Participants are no longer linked to Contacts, so there is no
                # shared identity across batches: each participant row gets its
                # own QR token and unique ID.
                existing_token = existing_id = None

                session.execute(
                    text(f"""
                        UPDATE {T("Training_Participant_Data")}
                        SET "QR_Token" = :tok, "Participant_Unique_ID" = :puid
                        WHERE "Training_Participant_Data_ID" = :p
                    """),
                    {
                        "tok": existing_token or str(uuid.uuid4()),
                        "puid": existing_id or generate_next_participant_unique_id(session, tenant_id),
                        "p": pid,
                    },
                )
        else:
            return jsonify({"error": "action must be 'add', 'remove', or 'update'"}), 400

        # keep the batch's participant count in step with its rows
        session.execute(
            text(f"""
                UPDATE {T("Training_Details_New")}
                SET "No_Of_Participants" = (
                    SELECT COUNT(*)
                    FROM {T("Training_Participant_Data")}
                    WHERE "Training_Details_ID" = :d
                )
                WHERE "Training_Details_ID" = :d
            """),
            {"d": training_id},
        )
        session.commit()

        participants = _fetch_participants(session, [training_id]).get(training_id, [])
        return jsonify({"success": True, "participants": participants}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(e)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ============================================================================
# PATCH /companies/<company_id>/training/<training_id>/stage
# ============================================================================
@company_training_bp.route(
    "/companies/<int:company_id>/training/<int:training_id>/stage",
    methods=["PATCH"],
)
@token_required
def update_company_training_stage(company_id, training_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        company = get_company_or_404(session, company_id, tenant_id, columns="client_id")
        if not company:
            return jsonify({"error": "Company not found"}), 404

        stages = load_training_stage_context(session)

        data = request.get_json(silent=True) or {}
        new_stage = data.get("stage")
        if new_stage not in stages.names or new_stage == stages.awaiting:
            return jsonify({"error": f"Invalid stage. Must be one of: {stages.names}"}), 400

        batch = _fetch_batch(session, tenant_id, training_id, company_id)
        if not batch:
            return jsonify({"error": "Training session not found"}), 404

        # PO gate: the PO-received stage and every later stage need a PO copy.
        if new_stage in stages.po_required and not batch.po_file_url:
            return jsonify({"error": "Upload the PO copy before moving to this stage"}), 400

        session.execute(
            text(f"""
                UPDATE {T("Training_Details_New")}
                SET "Stage_ID" = :stage
                WHERE "Training_Details_ID" = :sid
            """),
            {"stage": _stage_id_of(stages, new_stage), "sid": training_id},
        )
        session.commit()
        return jsonify({"training_id": training_id, "company_id": company_id, "stage": new_stage}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(e)
        return jsonify({"error": "Failed to update training stage", "details": str(e)}), 500
    finally:
        session.close()


# ============================================================================
# GET /companies/training/stage-config
# ============================================================================
@company_training_bp.route("/companies/training/stage-config", methods=["GET"])
@token_required
def get_company_training_stage_config():
    session = SessionLocal()
    try:
        stages = load_training_stage_context(session)
        names = list(stages.names)
        return jsonify({
            "stages": names,
            "awaiting": stages.awaiting,
            "default": stages.default,
            "po_received": stages.po_received,
            "po_required": [s for s in names if s in stages.po_required],
        }), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"error": "Failed to load stage configuration", "details": str(e)}), 500
    finally:
        session.close()


# ============================================================================
# GET /companies/training/cities and /companies/training/states
# Dropdown sources for the batch form (City_Master / State_Master).
# ============================================================================
@company_training_bp.route("/companies/training/cities", methods=["GET"])
@token_required
def list_training_cities():
    session = SessionLocal()
    try:
        rows = session.execute(
            text(f'SELECT city_id, city_name FROM {T("City_Master")} '
                 f'WHERE city_name IS NOT NULL AND TRIM(city_name) <> \'\' '
                 f'ORDER BY LOWER(city_name)')
        ).fetchall()
        return jsonify([{"city_id": r.city_id, "city_name": r.city_name} for r in rows]), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"error": "Failed to load cities", "details": str(e)}), 500
    finally:
        session.close()
@company_training_bp.route("/companies/training/trainers", methods=["GET"])
@token_required
def list_training_trainers():
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        rows = session.execute(
            text(f'''SELECT employee_id, employee_name FROM {T("Employee_Master")}
                     WHERE tenant_id = :tid AND is_active IS TRUE
                       AND employee_name IS NOT NULL
                     ORDER BY LOWER(employee_name)'''),
            {"tid": tenant_id},
        ).fetchall()
        return jsonify([{"employee_id": r.employee_id, "employee_name": r.employee_name} for r in rows]), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"error": "Failed to load trainers", "details": str(e)}), 500
    finally:
        session.close()
@company_training_bp.route("/companies/training/mhe", methods=["GET"])
@token_required
def list_training_mhe():
    session = SessionLocal()
    try:
        unassigned = _unassigned_mhe_id(session)
        rows = session.execute(
            text(f'''SELECT "MHE_ID", "MHE_Name" FROM {T("MHE_Master")}
                     WHERE "MHE_ID" <> :unassigned ORDER BY "MHE_ID"'''),
            {"unassigned": unassigned},
        ).fetchall()
        return jsonify([{"mhe_id": r[0], "mhe_name": r[1]} for r in rows]), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"error": "Failed to load MHE types", "details": str(e)}), 500
    finally:
        session.close()
@company_training_bp.route("/companies/training/states", methods=["GET"])
@token_required
def list_training_states():
    session = SessionLocal()
    try:
        rows = session.execute(
            text(f'SELECT state_id, state_name FROM {T("State_Master")} '
                 f'WHERE state_name IS NOT NULL AND TRIM(state_name) <> \'\' '
                 f'ORDER BY LOWER(state_name)')
        ).fetchall()
        return jsonify([{"state_id": r.state_id, "state_name": r.state_name} for r in rows]), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"error": "Failed to load states", "details": str(e)}), 500
    finally:
        session.close()
# ============================================================================
# GET /companies/training/next-event-number
# ============================================================================
@company_training_bp.route("/companies/training/next-event-number", methods=["GET"])
@token_required
def get_company_next_event_number():
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        return jsonify({"next_event_number": str(_next_event_base(session, tenant_id))}), 200
    except Exception as e:
        current_app.logger.exception(f"Error in GET /companies/training/next-event-number: {e}")
        return jsonify({"error": "Failed to compute next event number", "details": str(e)}), 500
    finally:
        session.close()


# ============================================================================
# POST /companies/<company_id>/training/<training_id>/po
# multipart: file  (mandatory PO copy)
#
# Attaches the PO copy to the batch. If the batch is still before the
# PO-received stage, it is moved to that stage in the same request.
# ============================================================================
@company_training_bp.route(
    "/companies/<int:company_id>/training/<int:training_id>/po",
    methods=["POST", "OPTIONS"],
)
@token_required
def upload_company_training_po(company_id, training_id):
    if request.method == "OPTIONS":
        return jsonify({}), 200

    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        company = get_company_or_404(session, company_id, tenant_id, columns="client_id")
        if not company:
            return jsonify({"error": "Company not found"}), 404

        stages = load_training_stage_context(session)

        batch = _fetch_batch(session, tenant_id, training_id, company_id)
        if not batch:
            return jsonify({"error": "Training session not found"}), 404

        if "file" not in request.files:
            return jsonify({"error": "PO copy is required"}), 400
        file = request.files["file"]
        if not file or file.filename == "":
            return jsonify({"error": "PO copy is required"}), 400

        uploaded = upload_file(file, company_id, cfg("PO_UPLOAD_KIND"))

        current_stage = _stage_name_of(stages, batch.stage_id) or stages.default
        new_stage = current_stage if current_stage in stages.po_required else stages.po_received

        session.execute(
            text(f"""
                UPDATE {T("Training_Details_New")}
                SET po_file_url = :url,
                    po_file_name = :name,
                    po_received_at = NOW(),
                    "Stage_ID" = :stage
                WHERE "Training_Details_ID" = :sid
            """),
            {
                "url": uploaded["file_url"],
                "name": uploaded["file_name"],
                "stage": _stage_id_of(stages, new_stage),
                "sid": training_id,
            },
        )
        session.commit()

        return jsonify(_serialize_one(session, tenant_id, training_id, stages, company_id)), 200

    except StorageError as e:
        session.rollback()
        current_app.logger.error(f"Storage error uploading PO: {e}")
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        session.rollback()
        current_app.logger.exception(e)
        return jsonify({"error": "Failed to upload PO", "details": str(e)}), 500
    finally:
        session.close()