"""
backend/routes/company_training_routes.py

Company training batch routes — Services_Master, extended per Sir's
direction to fully replace Training_Details for company batches.

REQUIRED DB MIGRATION: run migration_services_master_training_columns.sql
before deploying this file. It adds client_id, event_number,
trainer_name, client_address, city, state, pin_code, remarks,
participants (jsonb), participant_count, stage, updated_at to
Services_Master, and relaxes service_code/service_title to nullable (a
training batch row doesn't carry those — they're catalog-service concepts).

ALSO REQUIRED (PO gate): add the PO columns:

    ALTER TABLE "<DB_SCHEMA>"."Services_Master"
      ADD COLUMN IF NOT EXISTS po_file_url text,
      ADD COLUMN IF NOT EXISTS po_file_name text,
      ADD COLUMN IF NOT EXISTS po_received_at timestamptz;

Services_Master rows created by this module represent a single
scheduled training BATCH for one company (client_id), not a reusable
catalog service. Any existing catalog-service rows (service_code /
service_title set, client_id NULL) are left alone by every query here —
all of these routes filter/insert on client_id, so they only ever
touch batch rows.

Stages
------
Stage names are never written in this file. The valid training stages, their
order, and which stages need a PO all come from Stage_Master (see
config_helpers.load_training_stage_context). A PO is required from the
PO-received stage onward, i.e. that stage and every stage after it.

Configuration (app.config or environment, no defaults in code)
--------------------------------------------------------------
    DB_SCHEMA                     Postgres schema holding the CRM tables
    STAGE_TYPE_TRAINING           Stage_Master.stage_type for training stages
    STAGE_ID_AWAITING_SCHEDULING  stage_id of the derived awaiting stage
    STAGE_ID_TRAINING_DEFAULT     stage_id used when a batch has no stage
    STAGE_ID_PO_RECEIVED          stage_id where a PO becomes mandatory
    MAX_BULK_BATCHES              most batches allowed in one bulk request
    CALENDAR_CONTACT_METHOD       Client_Interactions.contact_method for the
                                  training-calendar entries
    CALENDAR_ENTRY_TYPE           "type" stored in the calendar entry
    CALENDAR_ENTRY_STATUS         "status" stored in the calendar entry
    CALENDAR_ENTRY_SOURCE         "source" stored in the calendar entry
    PO_UPLOAD_KIND                kind passed to upload_file() for PO copies
    PARTICIPANT_ID_PREFIX         prefix of generated participant IDs (<PREFIX>-<year>-00001)
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


def serialize_training(row, default_stage):
    raw_participants = row.participants
    if isinstance(raw_participants, str):
        try:
            raw_participants = json.loads(raw_participants)
        except Exception:
            raw_participants = []

    po_received_at = getattr(row, "po_received_at", None)

    return {
        "training_id":    row.service_id,
        "service_id":     row.service_id,
        "client_id":      row.client_id,
        "company_id":     row.client_id,
        "service_code":   getattr(row, "service_code", None),
        "service_title":  getattr(row, "service_title", None),
        "duration":       getattr(row, "duration", None),
        "training_from":  row.date_from.isoformat() if row.date_from else "",
        "training_to":    row.date_to.isoformat() if row.date_to else "",
        "training_fees":  row.service_rate,
        "trainer_name":   row.trainer_name,
        "client_address": row.client_address,
        "city":           row.city,
        "state":          row.state,
        "pin_code":       row.pin_code,
        "remarks":        getattr(row, "remarks", None),
        "participant_count": getattr(row, "participant_count", None),
        "event_number":   row.event_number,
        "stage":          getattr(row, "stage", None) or default_stage,
        "participants":   raw_participants or [],
        "po_file_url":    getattr(row, "po_file_url", None),
        "po_file_name":   getattr(row, "po_file_name", None),
        "po_received_at": po_received_at.isoformat() if po_received_at else None,
    }


def _pack_calendar_meta(meta: dict) -> str:
    return f"__meta__{json.dumps(meta)}__end_meta__"


def _calendar_settings():
    return {
        "contact_method": cfg("CALENDAR_CONTACT_METHOD", int),
        "entry_type": cfg("CALENDAR_ENTRY_TYPE"),
        "entry_status": cfg("CALENDAR_ENTRY_STATUS"),
        "entry_source": cfg("CALENDAR_ENTRY_SOURCE"),
    }


def _allocate_service_ids(session, how_many):
    """
    Reserve `how_many` consecutive service_ids.

    The table is locked until the end of the transaction so two requests
    creating batches at the same moment cannot receive the same id.
    """
    session.execute(
        text(f'LOCK TABLE {T("Services_Master")} IN SHARE ROW EXCLUSIVE MODE')
    )
    row = session.execute(
        text(f'SELECT COALESCE(MAX(service_id), 0) + 1 AS next_id FROM {T("Services_Master")}')
    ).fetchone()
    first = int(row.next_id)
    return list(range(first, first + how_many))


def _validate_new_batch_stage(stage, stages, errors):
    """A new batch can't start in the awaiting stage or in a PO-gated stage."""
    if stage not in stages.names or stage == stages.awaiting:
        errors["stage"] = "Invalid stage for a new batch"
    elif stage in stages.po_required:
        # A brand-new batch has no PO yet, so it can't start here.
        errors["stage"] = (
            "A new batch can't start in this stage. "
            f"Create it as {stages.default}, then upload the PO."
        )


# ============================================================================
# POST /companies/<company_id>/training — create a NEW training batch
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

        service_code = (data.get("service_code") or "").strip()
        service_title = (data.get("service_title") or "").strip()
        duration = (data.get("duration") or "").strip() or None

        if not service_code:
            errors["service_code"] = "Service Code is required"
        if not service_title:
            errors["service_title"] = "Service Title is required"

        def parse_date(value, field):
            if value in (None, ""):
                return None
            try:
                return datetime.strptime(value, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                errors[field] = f"'{field}' must be a valid date in YYYY-MM-DD format"
                return None

        training_from = parse_date(data.get("training_from"), "training_from")
        training_to = parse_date(data.get("training_to"), "training_to")

        if training_from and training_to and training_to < training_from:
            errors["training_to"] = "Training end date cannot be before the start date"

        training_fees = data.get("training_fees")
        if training_fees not in (None, ""):
            try:
                training_fees = float(training_fees)
                if training_fees < 0:
                    errors["training_fees"] = "Training fees cannot be negative"
            except (ValueError, TypeError):
                errors["training_fees"] = "Training fees must be a number"
        else:
            training_fees = None

        pin_code = (data.get("pin_code") or "").strip() or None
        if pin_code and not pin_code.isdigit():
            errors["pin_code"] = "PIN code must contain digits only"

        participant_count = data.get("participant_count")
        if participant_count in (None, ""):
            participant_count = None
        else:
            try:
                participant_count = int(participant_count)
                if participant_count < 0:
                    errors["participant_count"] = "Participant count cannot be negative"
            except (ValueError, TypeError):
                errors["participant_count"] = "Participant count must be a number"

        event_number = (data.get("event_number") or "").strip()
        if not event_number:
            errors["event_number"] = "Event Number is required"

        stage = (data.get("stage") or stages.default).strip()
        _validate_new_batch_stage(stage, stages, errors)

        if errors:
            return jsonify({"error": "Validation failed", "details": errors}), 400

        participants_in = data.get("participants") or []
        for p in participants_in:
            if not p.get("id"):
                p["id"] = f"participant_{uuid.uuid4().hex[:12]}"
            p.setdefault("mainTraining", False)
            p.setdefault("trainingRecords", [])

        (new_service_id_value,) = _allocate_service_ids(session, 1)

        params = {
            "service_id": new_service_id_value,
            "tenant_id": tenant_id,
            "client_id": company_id,
            "stage": stage,
            "service_code": service_code,
            "service_title": service_title,
            "duration": duration,
            "event_number": event_number,
            "date_from": training_from,
            "date_to": training_to,
            "service_rate": training_fees,
            "trainer_name": (data.get("trainer_name") or "").strip() or None,
            "client_address": (data.get("client_address") or "").strip() or None,
            "city": (data.get("city") or "").strip() or None,
            "state": (data.get("state") or "").strip() or None,
            "pin_code": pin_code,
            "remarks": (data.get("remarks") or "").strip() or None,
            "participants": json.dumps(participants_in),
            "participant_count": participant_count,
        }

        result = session.execute(
            text(f"""
                INSERT INTO {T("Services_Master")}
                    (service_id, tenant_id, client_id,
                     service_code, service_title, duration,
                     event_number, date_from, date_to, service_rate,
                     trainer_name, client_address, city, state, pin_code,
                     remarks, participants, participant_count, stage)
                VALUES
                    (:service_id, :tenant_id, :client_id,
                     :service_code, :service_title, :duration,
                     :event_number, :date_from, :date_to, :service_rate,
                     :trainer_name, :client_address, :city, :state, :pin_code,
                     :remarks, :participants, :participant_count, :stage)
                RETURNING service_id
            """),
            params,
        )
        new_service_id = result.fetchone().service_id

        # Same Training Calendar sync as the client-side route.
        if training_from:
            calendar_meta = {
                "title": f"{company.client_company_name} - {calendar['entry_type']}",
                "type": calendar["entry_type"],
                "status": calendar["entry_status"],
                "training_id": new_service_id,
                "training_to": training_to.isoformat() if training_to else None,
                "team_member": (data.get("trainer_name") or "").strip(),
                "source": calendar["entry_source"],
            }
            session.execute(
                text(f"""
                    INSERT INTO {T("Client_Interactions")}
                        (client_id, contact_method, contact_date, notes)
                    VALUES
                        (:client_id, :contact_method, :contact_date, :notes)
                """),
                {
                    "client_id": company_id,
                    "contact_method": calendar["contact_method"],
                    "contact_date": training_from,
                    "notes": _pack_calendar_meta(calendar_meta),
                },
            )

        session.commit()

        return jsonify({
            "success": True,
            "message": "Training session saved successfully",
            "training_id": new_service_id,
            "service_id": new_service_id,
        }), 201

    except Exception as e:
        session.rollback()
        current_app.logger.exception(e)
        return jsonify({"error": "Failed to save training session", "details": str(e)}), 500
    finally:
        session.close()


def _next_event_base(session, tenant_id) -> int:
    """Same global sequence as GET /companies/training/next-event-number."""
    row = session.execute(
        text(f"""
            SELECT MAX(NULLIF(regexp_replace(event_number, '[^0-9]', '', 'g'), '')::int) AS max_event_no
            FROM {T("Services_Master")} sm
            JOIN {T("Client_Master")} cm ON cm.client_id = sm.client_id
            WHERE cm.tenant_id = :tid AND sm.client_id IS NOT NULL
        """),
        {"tid": tenant_id},
    ).fetchone()
    return (row.max_event_no or 0) + 1


# ============================================================================
# POST /companies/<company_id>/training/bulk — create several batches at once
#
# Body:
# {
#   "shared": { service_code, service_title, duration, training_fees,
#               client_address, city, state, pin_code, remarks, stage? },
#   "batches": [
#     { training_from, training_to, trainer_name,
#       event_number?,            # blank => auto, next in the global sequence
#       participant_count?,       # planned size of this batch
#       participants: [ {id?, name, contact_id?} ] },
#     ...
#   ]
# }
# All batches are inserted in ONE transaction: if any batch is invalid,
# nothing is saved.
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

        def parse_date(value, field):
            if value in (None, ""):
                errors[field] = f"'{field}' is required"
                return None
            try:
                return datetime.strptime(value, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                errors[field] = f"'{field}' must be a valid date in YYYY-MM-DD format"
                return None

        # ---- shared fields ----
        service_code = (shared.get("service_code") or "").strip()
        service_title = (shared.get("service_title") or "").strip()
        duration = (shared.get("duration") or "").strip() or None
        if not service_code:
            errors["service_code"] = "Service Code is required"
        if not service_title:
            errors["service_title"] = "Service Title is required"

        training_fees = shared.get("training_fees")
        if training_fees not in (None, ""):
            try:
                training_fees = float(training_fees)
                if training_fees < 0:
                    errors["training_fees"] = "Training fees cannot be negative"
            except (ValueError, TypeError):
                errors["training_fees"] = "Training fees must be a number"
        else:
            training_fees = None

        pin_code = (shared.get("pin_code") or "").strip() or None
        if pin_code and not pin_code.isdigit():
            errors["pin_code"] = "PIN code must contain digits only"

        stage = (shared.get("stage") or stages.default).strip()
        _validate_new_batch_stage(stage, stages, errors)

        # ---- per-batch fields ----
        prepared = []
        for i, b in enumerate(batches_in):
            prefix = f"batches[{i}]"
            b = b or {}

            training_from = parse_date(b.get("training_from"), f"{prefix}.training_from")
            training_to = parse_date(b.get("training_to"), f"{prefix}.training_to")
            if training_from and training_to and training_to < training_from:
                errors[f"{prefix}.training_to"] = "Training end date cannot be before the start date"

            count = b.get("participant_count")
            if count in (None, ""):
                count = None
            else:
                try:
                    count = int(count)
                    if count < 0:
                        errors[f"{prefix}.participant_count"] = "Participant count cannot be negative"
                except (ValueError, TypeError):
                    errors[f"{prefix}.participant_count"] = "Participant count must be a number"

            participants = []
            for p in (b.get("participants") or []):
                name = (p.get("name") or "").strip()
                if not name:
                    continue
                participants.append({
                    "id": p.get("id") or f"participant_{uuid.uuid4().hex[:12]}",
                    "name": name,
                    "contact_id": p.get("contact_id"),
                    "mainTraining": False,
                    "trainingRecords": [],
                })

            prepared.append({
                "training_from": training_from,
                "training_to": training_to,
                "trainer_name": (b.get("trainer_name") or "").strip() or None,
                "event_number": str(b.get("event_number") or "").strip(),
                "participant_count": count,
                "participants": participants,
            })

        # a contact can only be in one batch of the same request
        seen_contacts = {}
        for i, p in enumerate(prepared):
            for part in p["participants"]:
                cid = part.get("contact_id")
                if cid is None:
                    continue
                if str(cid) in seen_contacts and seen_contacts[str(cid)] != i:
                    errors["participants"] = (
                        f"'{part['name']}' is selected in more than one batch"
                    )
                seen_contacts[str(cid)] = i

        explicit_numbers = [p["event_number"] for p in prepared if p["event_number"]]
        if len(set(explicit_numbers)) != len(explicit_numbers):
            errors["event_number"] = "Each batch needs a different Event Number"

        if errors:
            return jsonify({"error": "Validation failed", "details": errors}), 400

        # ---- allocate Event Nos for blanks (global sequence, skipping any
        #      number the user typed explicitly in this request) ----
        used = set(explicit_numbers)
        next_no = _next_event_base(session, tenant_id)
        for p in prepared:
            if not p["event_number"]:
                while str(next_no) in used:
                    next_no += 1
                p["event_number"] = str(next_no)
                used.add(str(next_no))
                next_no += 1

        # ---- insert everything in one transaction ----
        service_ids = _allocate_service_ids(session, len(prepared))

        created = []
        for service_id, p in zip(service_ids, prepared):
            session.execute(
                text(f"""
                    INSERT INTO {T("Services_Master")}
                        (service_id, tenant_id, client_id,
                         service_code, service_title, duration,
                         event_number, date_from, date_to, service_rate,
                         trainer_name, client_address, city, state, pin_code,
                         remarks, participants, participant_count, stage)
                    VALUES
                        (:service_id, :tenant_id, :client_id,
                         :service_code, :service_title, :duration,
                         :event_number, :date_from, :date_to, :service_rate,
                         :trainer_name, :client_address, :city, :state, :pin_code,
                         :remarks, :participants, :participant_count, :stage)
                """),
                {
                    "service_id": service_id,
                    "tenant_id": tenant_id,
                    "client_id": company_id,
                    "service_code": service_code,
                    "service_title": service_title,
                    "duration": duration,
                    "event_number": p["event_number"],
                    "date_from": p["training_from"],
                    "date_to": p["training_to"],
                    "service_rate": training_fees,
                    "trainer_name": p["trainer_name"],
                    "client_address": (shared.get("client_address") or "").strip() or None,
                    "city": (shared.get("city") or "").strip() or None,
                    "state": (shared.get("state") or "").strip() or None,
                    "pin_code": pin_code,
                    "remarks": (shared.get("remarks") or "").strip() or None,
                    "participants": json.dumps(p["participants"]),
                    "participant_count": p["participant_count"],
                    "stage": stage,
                },
            )

            # Training Calendar sync, same as the single-batch route
            if p["training_from"]:
                calendar_meta = {
                    "title": f"{company.client_company_name} - {calendar['entry_type']}",
                    "type": calendar["entry_type"],
                    "status": calendar["entry_status"],
                    "training_id": service_id,
                    "training_to": p["training_to"].isoformat() if p["training_to"] else None,
                    "team_member": p["trainer_name"] or "",
                    "source": calendar["entry_source"],
                }
                session.execute(
                    text(f"""
                        INSERT INTO {T("Client_Interactions")}
                            (client_id, contact_method, contact_date, notes)
                        VALUES
                            (:client_id, :contact_method, :contact_date, :notes)
                    """),
                    {
                        "client_id": company_id,
                        "contact_method": calendar["contact_method"],
                        "contact_date": p["training_from"],
                        "notes": _pack_calendar_meta(calendar_meta),
                    },
                )

            created.append({"training_id": service_id, "event_number": p["event_number"]})

        session.commit()

        return jsonify({
            "success": True,
            "message": f"{len(created)} training batches saved successfully",
            "count": len(created),
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

    The prefix comes from config (PARTICIPANT_ID_PREFIX), the schema from
    T(); nothing is hardcoded. Only the trailing digit run is used for the
    sequence, so the year inside the ID never inflates the counter. Scoped to
    the caller's tenant.

    Note: like the Event No. generator, this is not row-locked, so truly
    simultaneous passes carry the same small race-condition risk.
    """
    prefix = cfg("PARTICIPANT_ID_PREFIX")
    year = year or datetime.utcnow().year

    row = db_session.execute(
        text(f"""
            SELECT COALESCE(MAX(
                NULLIF(
                    substring(elem->>'participant_unique_id' from '^[^-]+-[0-9]{{4}}-([0-9]{{1,6}})$'),
                    ''
                )::bigint
            ), 0) AS max_id
            FROM {T("Services_Master")} sm
            JOIN {T("Client_Master")} cm ON cm.client_id = sm.client_id,
                 jsonb_array_elements(
                     CASE WHEN jsonb_typeof(sm.participants) = 'array'
                          THEN sm.participants ELSE '[]'::jsonb END
                 ) AS elem
            WHERE cm.tenant_id = :tid
              AND elem->>'participant_unique_id' IS NOT NULL
        """),
        {"tid": tenant_id},
    ).fetchone()
    next_value = (row.max_id or 0) + 1
    return f"{prefix}-{year}-{next_value:05d}"


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
            text(f"""
                SELECT *
                FROM {T("Services_Master")}
                WHERE client_id = :client_id
                ORDER BY service_id DESC
            """),
            {"client_id": company_id},
        ).fetchall()

        return jsonify([serialize_training(r, stages.default) for r in rows]), 200

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

        row = session.execute(
            text(f"""
                SELECT *
                FROM {T("Services_Master")}
                WHERE service_id = :sid AND client_id = :cid
            """),
            {"sid": training_id, "cid": company_id},
        ).fetchone()

        if not row:
            return jsonify({"error": "Training session not found"}), 404

        return jsonify(serialize_training(row, stages.default)), 200

    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ============================================================================
# PATCH /companies/<company_id>/training/<training_id> — edit batch fields
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

        existing = session.execute(
            text(f"""
                SELECT service_id, date_from, date_to
                FROM {T("Services_Master")}
                WHERE service_id = :sid AND client_id = :cid
            """),
            {"sid": training_id, "cid": company_id},
        ).fetchone()
        if not existing:
            return jsonify({"error": "Training session not found"}), 404

        data = request.get_json(silent=True) or {}
        errors = {}

        def parse_date(value, field):
            if value in (None, ""):
                return None
            try:
                return datetime.strptime(value, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                errors[field] = f"'{field}' must be a valid date in YYYY-MM-DD format"
                return None

        set_clauses = []
        params = {"sid": training_id, "cid": company_id}

        if "service_code" in data:
            value = (data.get("service_code") or "").strip()
            if not value:
                errors["service_code"] = "Service Code is required"
            else:
                set_clauses.append("service_code = :service_code")
                params["service_code"] = value

        if "service_title" in data:
            value = (data.get("service_title") or "").strip()
            if not value:
                errors["service_title"] = "Service Title is required"
            else:
                set_clauses.append("service_title = :service_title")
                params["service_title"] = value

        if "duration" in data:
            value = (data.get("duration") or "").strip() or None
            set_clauses.append("duration = :duration")
            params["duration"] = value

        if "training_from" in data:
            date_from = parse_date(data.get("training_from"), "training_from")
            set_clauses.append("date_from = :date_from")
            params["date_from"] = date_from
        if "training_to" in data:
            date_to = parse_date(data.get("training_to"), "training_to")
            set_clauses.append("date_to = :date_to")
            params["date_to"] = date_to

        if "training_fees" in data:
            fees = data.get("training_fees")
            if fees not in (None, ""):
                try:
                    fees = float(fees)
                    if fees < 0:
                        errors["training_fees"] = "Training fees cannot be negative"
                except (ValueError, TypeError):
                    errors["training_fees"] = "Training fees must be a number"
            else:
                fees = None
            set_clauses.append("service_rate = :service_rate")
            params["service_rate"] = fees

        if "pin_code" in data:
            pin_code = (data.get("pin_code") or "").strip() or None
            if pin_code and not pin_code.isdigit():
                errors["pin_code"] = "PIN code must contain digits only"
            set_clauses.append("pin_code = :pin_code")
            params["pin_code"] = pin_code

        if "event_number" in data:
            event_number = (data.get("event_number") or "").strip()
            if not event_number:
                errors["event_number"] = "Event Number is required"
            set_clauses.append("event_number = :event_number")
            params["event_number"] = event_number

        for field, column in (
            ("trainer_name", "trainer_name"),
            ("client_address", "client_address"),
            ("city", "city"),
            ("state", "state"),
            ("remarks", "remarks"),
        ):
            if field in data:
                set_clauses.append(f"{column} = :{column}")
                params[column] = (data.get(field) or "").strip() or None

        effective_from = params.get("date_from") if "training_from" in data else existing.date_from
        effective_to = params.get("date_to") if "training_to" in data else existing.date_to
        if effective_from and effective_to and effective_to < effective_from:
            errors["training_to"] = "Training end date cannot be before the start date"

        if errors:
            return jsonify({"error": "Validation failed", "details": errors}), 400

        if not set_clauses:
            return jsonify({"error": "No updatable fields provided"}), 400

        set_clauses.append("updated_at = NOW()")

        session.execute(
            text(f"""
                UPDATE {T("Services_Master")}
                SET {', '.join(set_clauses)}
                WHERE service_id = :sid AND client_id = :cid
            """),
            params,
        )
        session.commit()

        row = session.execute(
            text(f'SELECT * FROM {T("Services_Master")} WHERE service_id = :sid'),
            {"sid": training_id},
        ).fetchone()

        return jsonify(serialize_training(row, stages.default)), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(e)
        return jsonify({"error": "Failed to update training session", "details": str(e)}), 500
    finally:
        session.close()


# ============================================================================
# PATCH /companies/<company_id>/training/<training_id>/participants
# ============================================================================
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

        row = session.execute(
            text(f"""
                SELECT service_id, participants
                FROM {T("Services_Master")}
                WHERE service_id = :sid AND client_id = :cid
            """),
            {"sid": training_id, "cid": company_id},
        ).fetchone()
        if not row:
            return jsonify({"error": "Training session not found"}), 404

        participants = row.participants
        if isinstance(participants, str):
            try:
                participants = json.loads(participants)
            except Exception:
                participants = []
        participants = participants or []

        data = request.get_json(silent=True) or {}
        action = data.get("action")

        if action == "add":
            name = (data.get("name") or "").strip()
            if not name:
                return jsonify({"error": "Participant name is required"}), 400
            participants.append({
                "id": f"participant_{uuid.uuid4().hex[:12]}",
                "name": name,
                "mainTraining": False,
                "trainingRecords": [],
            })

        elif action == "remove":
            participant_id = data.get("participant_id")
            if not participant_id:
                return jsonify({"error": "participant_id is required"}), 400
            participants = [p for p in participants if p.get("id") != participant_id]

                
        elif action == "update":
            participant_id = data.get("participant_id")
            updates = data.get("participant") or {}

            if not participant_id:
                return jsonify({"error": "participant_id is required"}), 400

            found = False

            for p in participants:
                if p.get("id") == participant_id:
                    p.update(updates)
                    found = True

                    # Generate QR details once participant has passed.
                    passed = bool(p.get("pass"))

                    if passed and not p.get("qr_token"):
                        contact_id = p.get("contact_id")
                        existing_token = None
                        existing_id = None

                        if contact_id is not None:
                            # Reuse the contact's existing token/ID (same person,
                            # earlier batch), scoped to this tenant only.
                            existing = session.execute(
                                text(f"""
                                    SELECT
                                        elem->>'qr_token' AS qr_token,
                                        elem->>'participant_unique_id' AS participant_unique_id
                                    FROM {T("Services_Master")} sm
                                    JOIN {T("Client_Master")} cm ON cm.client_id = sm.client_id,
                                         jsonb_array_elements(
                                             CASE WHEN jsonb_typeof(sm.participants) = 'array'
                                                  THEN sm.participants ELSE '[]'::jsonb END
                                         ) AS elem
                                    WHERE cm.tenant_id = :tid
                                      AND elem->>'contact_id' = :cid
                                      AND elem->>'qr_token' IS NOT NULL
                                    LIMIT 1
                                """),
                                {"tid": tenant_id, "cid": str(contact_id)},
                            ).fetchone()

                            if existing:
                                existing_token = existing.qr_token
                                existing_id = existing.participant_unique_id

                        p["qr_token"] = existing_token or str(uuid.uuid4())
                        p["participant_unique_id"] = (
                            existing_id
                            or generate_next_participant_unique_id(session, tenant_id)
                        )

                    break

            if not found:
                return jsonify(
                    {"error": "Participant not found in this session"}
                ), 404

        else:
            return jsonify({"error": "action must be 'add', 'remove', or 'update'"}), 400

        session.execute(
            text(f"""
                UPDATE {T("Services_Master")}
                SET participants = :participants, updated_at = NOW()
                WHERE service_id = :sid
            """),
            {"participants": json.dumps(participants), "sid": training_id},
        )
        session.commit()

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

        # PO gate: the PO-received stage and every later stage need an
        # uploaded PO copy.
        if new_stage in stages.po_required:
            po = session.execute(
                text(f"""
                    SELECT po_file_url FROM {T("Services_Master")}
                    WHERE service_id = :sid AND client_id = :cid
                """),
                {"sid": training_id, "cid": company_id},
            ).fetchone()
            if not po:
                return jsonify({"error": "Training session not found"}), 404
            if not po.po_file_url:
                return jsonify({"error": "Upload the PO copy before moving to this stage"}), 400

        result = session.execute(
            text(f"""
                UPDATE {T("Services_Master")}
                SET stage = :stage, updated_at = NOW()
                WHERE service_id = :sid AND client_id = :cid
            """),
            {"stage": new_stage, "sid": training_id, "cid": company_id},
        )
        if result.rowcount == 0:
            session.rollback()
            return jsonify({"error": "Training session not found"}), 404

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
#
# The training stages, which one is the default, which one is the derived
# "awaiting" stage, which stage a PO is first required at, and every stage that
# needs a PO — all read from Stage_Master via load_training_stage_context, so
# the frontend never has to carry its own copy of the stage names.
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
# GET /companies/training/next-event-number
# ============================================================================
@company_training_bp.route("/companies/training/next-event-number", methods=["GET"])
@token_required
def get_company_next_event_number():
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        row = session.execute(
            text(f"""
                SELECT MAX(NULLIF(regexp_replace(event_number, '[^0-9]', '', 'g'), '')::int) AS max_event_no
                FROM {T("Services_Master")} sm
                JOIN {T("Client_Master")} cm ON cm.client_id = sm.client_id
                WHERE cm.tenant_id = :tid AND sm.client_id IS NOT NULL
            """),
            {"tid": tenant_id},
        ).fetchone()

        next_number = (row.max_event_no or 0) + 1
        return jsonify({"next_event_number": str(next_number)}), 200

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
# Uploading again replaces the PO. Needs the po_* columns on Services_Master.
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

        batch = session.execute(
            text(f"""
                SELECT service_id, stage
                FROM {T("Services_Master")}
                WHERE service_id = :sid AND client_id = :cid
            """),
            {"sid": training_id, "cid": company_id},
        ).fetchone()
        if not batch:
            return jsonify({"error": "Training session not found"}), 404

        if "file" not in request.files:
            return jsonify({"error": "PO copy is required"}), 400
        file = request.files["file"]
        if not file or file.filename == "":
            return jsonify({"error": "PO copy is required"}), 400

        uploaded = upload_file(file, company_id, cfg("PO_UPLOAD_KIND"))

        current_stage = batch.stage or stages.default
        new_stage = current_stage if current_stage in stages.po_required else stages.po_received

        session.execute(
            text(f"""
                UPDATE {T("Services_Master")}
                SET po_file_url = :url,
                    po_file_name = :name,
                    po_received_at = NOW(),
                    stage = :stage,
                    updated_at = NOW()
                WHERE service_id = :sid AND client_id = :cid
            """),
            {
                "url": uploaded["file_url"],
                "name": uploaded["file_name"],
                "stage": new_stage,
                "sid": training_id,
                "cid": company_id,
            },
        )
        session.commit()

        row = session.execute(
            text(f'SELECT * FROM {T("Services_Master")} WHERE service_id = :sid'),
            {"sid": training_id},
        ).fetchone()
        return jsonify(serialize_training(row, stages.default)), 200

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