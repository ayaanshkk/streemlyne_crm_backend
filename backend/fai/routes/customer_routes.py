"""
Client Routes for StreemLyne CRM
Updated to include display_id field for UI display
FIXED: Removed admin-only restriction from DELETE endpoint
FIXED: Removed the broken /certificates/upload and /certificates routes
       that were silently conflicting with the real file-storage system.
       File uploads now live entirely in client_files_routes.py
       (POST/GET /clients/<id>/files, DELETE /clients/files/<id>).

--------------------------------------------------------------------------
CHANGELOG (Training Calendar sync)
--------------------------------------------------------------------------
create_training_session() now ALSO writes a linked Training Calendar
entry into Client_Interactions (contact_method = 1 — the same convention
calendar_routes.py already reads), in the SAME transaction as the
Training_Details insert. This is what makes every batch saved from the
"Training Details" tab automatically show up on the Training Calendar
page, without needing a separate manual "Add Training Date" click.

The calendar entry's notes carry a __meta__ blob with:
    - training_id  -> links this calendar entry back to the batch
    - training_to  -> the batch's end date, for display
    - source        -> "training_session" (vs "manual" for events created
                        via the calendar page's own Add Training button)

calendar_routes.py surfaces these three fields back out on GET
/calendar/events and GET /calendar/event/<id> so the frontend can tell
synced events apart from manually-created ones and deep-link back to
the batch.

Only created when training_from is present — a draft batch with no
dates yet has nothing to put on a calendar.

--------------------------------------------------------------------------
(all older changelogs below are unchanged from before)
--------------------------------------------------------------------------
- Added get_client_or_404() helper: every route that touches a client_id
  now verifies the client exists AND belongs to the caller's tenant,
  instead of trsting the raw client_id (previously several routes let
  any authenticated user read/edit/delete/stage-change/train ANY client
  from ANY tenant, and the training endpoints didn't check the client
  existed at all).
- create_customer() / update_customer():
    * Added email format validation (both used to accept garbage).
    * create_customer() now checks tenant_id is actually set on the
      user before writing, and returns a clean 400 instead of a raw
      500/DB error if not.
- update_customer_stage():
    * Now validates `stage` and `pipeline_type` against explicit
      whitelists instead of silently no-op'ing on typos/garbage input.
    * Client existence + tenant check added (previously any tenant
      could move any other tenant's client through the pipeline).
    * Opportunity titles now use the client's actual company name
      instead of the raw client_id ("Training - 42" -> "Acme Co -
      Training Scheduled"), matching the naming convention already
      used in create_customer().
- get_customer / update_customer / delete_customer / get_client_test_results:
    * All now scoped to request.current_user.tenant_id via
      get_client_or_404().
- Hoisted `import json` to the top of the file instead of re-importing
  it locally inside four different functions.

--------------------------------------------------------------------------
CHANGELOG (2nd Training module rework — MULTIPLE sessions per client)
--------------------------------------------------------------------------
A client can now have MANY training sessions (e.g. one company gets
trained in January and again in June — those are two separate rows,
not one row overwritten). This replaces the previous "one
Training_Details row per client, upserted on save" model.

- save_training_details() / get_training_details() (the old upsert +
  single-row-or-{} pair) have been REPLACED by:
    * POST   /clients/<client_id>/training
                 -> create_training_session()   (always INSERTs a new
                    row now — no more ON CONFLICT upsert)
    * GET    /clients/<client_id>/training
                 -> list_training_sessions()     (returns an ARRAY of
                    every session for this client, newest first)
    * GET    /clients/<client_id>/training/<training_id>
                 -> get_training_session()        (single session, used
                    by the participant detail view)
    * PATCH  /clients/<client_id>/training/<training_id>/participants
                 -> modify_training_participants() (add / remove /
                    update ONE participant on an already-saved session,
                    without re-submitting the whole session)
- Added serialize_training() helper (mirrors serialize_client()).

REQUIRED DB MIGRATION — see migration.sql shipped alongside this file.
CONFIRMED (via information_schema.columns): Training_Details has NO
dedicated id column today — client_id, made UNIQUE by the previous
rework, was standing in as the de-facto key. migration.sql (1) drops
that UNIQUE constraint and (2) ADDS a new training_id BIGSERIAL PRIMARY
KEY column, which is what every route below (RETURNING training_id /
WHERE training_id = ...) depends on. Run that migration before
deploying this file, or every training route will fail against the
current schema.

--------------------------------------------------------------------------
CHANGELOG (Commercial contact fields rework — Name + Email per department)
--------------------------------------------------------------------------
Client_Master previously stored a single free-text column per department
contact (purchase_department_contact / finance_department_contact), plus
a bare primary_contact_department dropdown value with no dedicated name/
email columns of its own. Per updated form requirements, every department
contact now has its own Name + Email pair:

    primary_contact_name / primary_contact_email
    purchase_contact_name / purchase_contact_email
    finance_contact_name / finance_contact_email

REQUIRED DB MIGRATION (already applied by user):
    ALTER TABLE "streemLyne_mt_dev2"."Client_Master"
      ADD COLUMN primary_contact_name  TEXT,
      ADD COLUMN primary_contact_email TEXT,
      ADD COLUMN purchase_contact_name  TEXT,
      ADD COLUMN purchase_contact_email TEXT,
      ADD COLUMN finance_contact_name  TEXT,
      ADD COLUMN finance_contact_email TEXT;

FIXED (pre-existing bug): create_customer()'s INSERT statement referenced
:primary_contact_department / :purchase_department_contact /
:finance_department_contact as bind placeholders, but the params dict
being passed in never defined a primary_contact_department key at all and
instead defined differently-named keys (primary_contact_name,
purchase_contact_name, etc.) that matched nothing in the query. That
mismatch meant every POST /clients would have failed with a SQLAlchemy
"a bind parameter ... is required" error. The INSERT below now uses the
new columns consistently with the params dict.

The old purchase_department_contact / finance_department_contact columns
are left in the table (untouched) so existing historical rows still read
back correctly, but new/edited clients no longer write to them — they're
fully replaced by the *_contact_name / *_contact_email pairs.

FIXED (schema drift): serialize_client() used to read
row.purchase_department_contact / row.finance_department_contact via
direct attribute access. On environments where those legacy columns
were never (re)added / already dropped, SQLAlchemy raises
"Could not locate column in row for column '...'" the moment any route
serializes a client — this is different from a plain missing-attribute
case, direct access on a Row object fails hard if the column isn't
part of the result set at all. Switched both to getattr(row, ..., None)
the same defensive pattern already used for every other newer contact
field in this dict, so a client with/without those legacy columns in
its schema serializes fine either way.

--------------------------------------------------------------------------
CHANGELOG (City / State stored as their own columns)
--------------------------------------------------------------------------
Previously, City and State typed into the create/edit client form were
never persisted on their own — they were only ever folded into the
single free-text `address` column (as
"<street>, <city>, <state>, <pincode>"), alongside `post_code` which WAS
already a dedicated column. That's lossy: once City/State are baked into
one string, they can't be reliably pulled back out (a street address
that itself contains a comma, e.g. "Camp, MG Road", makes any
comma-split parsing ambiguous), and any UI that wants the *exact* City/
State the user typed (e.g. prefilling a training batch's location from
the client's own address) had no reliable source to read from.

REQUIRED DB MIGRATION:
    ALTER TABLE "streemLyne_mt_dev2"."Client_Master"
      ADD COLUMN city  TEXT,
      ADD COLUMN state TEXT;

- create_customer() now writes `city` and `state` (plus the pre-existing
  `training_location` and `post_code` columns) from the payload, in
  addition to still building and storing the combined `address` string
  for anything that displays a single full address line.
- update_customer() 's field_map now includes `city` / `state` so they
  can be edited directly.
- serialize_client() now returns `city` and `state` alongside the
  existing `training_location` / `post_code`, so the frontend can read
  back the exact values the user typed, instead of re-deriving them by
  parsing the combined `address` string.
--------------------------------------------------------------------------
"""
import json
import re
import uuid
from datetime import datetime
from .db_routes import TRAINING_PIPELINE_STAGES

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text

from .auth_helpers import token_required
from ..db import SessionLocal

customer_bp = Blueprint('customers', __name__)


# ─────────────────────────────────────────────
# SCHEMA CONFIGURATION
# ─────────────────────────────────────────────
SCHEMA = "streemLyne_mt_dev2"  # Multi-tenant schema name


def T(table_name):
    """Prefix table with schema: StreemLyne_MT.TableName"""
    return f'"{SCHEMA}"."{table_name}"'


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def validate_optional_email(value, field_name, errors):
    """Validates an optional email field; only rejects if non-empty and malformed."""
    value = (value or "").strip()
    if value and not EMAIL_RE.match(value):
        errors[field_name] = "Invalid email format"
    return value



# ─────────────────────────────────────────────
# CONSTANTS: stage_type values in Stage_Master
# ─────────────────────────────────────────────
STAGE_TYPE_SALES    = 1
STAGE_TYPE_TRAINING = 2

SALES_STAGES    = {"Enquiry", "Proposal", "Converted", "Lost"}
AWAITING_SCHEDULING = "Awaiting Scheduling"
STAGE_TRAINING_SCHEDULED = "Training Scheduled"
STAGE_PO_RECEIVED = "PO Received"

TRAINING_PIPELINE_STAGES = [
    "Training Scheduled",
    "PO Received",
    "Training Conducted",
    "Training Completed",
    "PTI Created",
    "Certificates Created",
    "Certificates Dispatched",
]


# Ordered so we can tell "forward" from "backward" — auto-advance never
# regresses a client that's already past a given stage.
TRAINING_STAGE_ORDER = [
    "Training Scheduled", "Training Conducted", "Training Completed",
    "PTI Created", "Certificates Created", "Certificates Dispatched",
]


def auto_advance_training_stage(session, client_id, tenant_id, target_stage):
    """Moves a client's training_stage forward to target_stage, triggered by
    a real event (file upload, dropdown pick) instead of a manual Kanban
    drag. No-ops if the client has no training opportunity yet (sales
    hasn't been converted), or is already at/past target_stage. Caller is
    responsible for committing the session afterward."""
    client_row = get_client_or_404(session, client_id, tenant_id, columns="client_id, client_company_name")
    if not client_row:
        return False

    opp = get_latest_opportunity(session, client_id)
    if not opp or opp.stage_type != STAGE_TYPE_TRAINING:
        return False  # sales hasn't converted to training yet — nothing to advance

    existing_misc = {}
    if opp.misc_col1:
        try:
            existing_misc = json.loads(opp.misc_col1)
        except Exception:
            pass

    current_stage = existing_misc.get('training_stage') or opp.stage_name
    try:
        current_idx = TRAINING_STAGE_ORDER.index(current_stage)
    except ValueError:
        current_idx = -1
    try:
        target_idx = TRAINING_STAGE_ORDER.index(target_stage)
    except ValueError:
        return False

    if target_idx <= current_idx:
        return False  # already at/past this stage — don't regress

    stage_row = session.execute(
        text("""
            SELECT stage_id FROM "streemLyne_mt_dev2"."Pipeline_Stage_Master"
            WHERE stage_type = :stype AND stage_name = :sname
            LIMIT 1
        """),
        {"stype": STAGE_TYPE_TRAINING, "sname": target_stage}
    ).fetchone()
    if not stage_row:
        current_app.logger.warning(f"⚠️ Training stage '{target_stage}' not found in Stage_Master")
        return False

    existing_misc['training_stage'] = target_stage
    existing_misc['pipeline_type'] = 'training'
    existing_misc['notes'] = (existing_misc.get('notes', '') or '') + (
        f"\n[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')}] "
        f"Stage auto-advanced: {current_stage} → {target_stage}"
    )

    session.execute(
        text("""
            UPDATE "streemLyne_mt_dev2"."Opportunity_Details"
            SET stage_id = :stage_id,
                opportunity_title = :title,
                "Misc_Col1" = :misc
            WHERE opportunity_id = :oid
        """),
        {
            "stage_id": stage_row.stage_id,
            "title": f"{client_row.client_company_name} - {target_stage}",
            "misc": json.dumps(existing_misc),
            "oid": opp.opportunity_id,
        }
    )
    return True


# ─────────────────────────────────────────────
# HELPER: Admin check (reused from auth pattern)
# ─────────────────────────────────────────────
def is_admin(session, user_id):
    try:
        row = session.execute(
            text("""
                SELECT em.role_ids
                FROM "streemLyne_mt_dev2"."User_Master" um
                JOIN "streemLyne_mt_dev2"."Employee_Master" em ON em.employee_id = um.employee_id
                WHERE um.user_id = :uid
            """),
            {"uid": user_id}
        ).fetchone()

        if not row or not row.role_ids:
            return False

        role_ids = [r.strip() for r in str(row.role_ids).split(',') if r.strip().isdigit()]
        if not role_ids:
            return False

        placeholders = ', '.join([f':r{i}' for i in range(len(role_ids))])
        params = {f'r{i}': int(rid) for i, rid in enumerate(role_ids)}

        admin_row = session.execute(
            text(f"""
                SELECT role_id FROM "streemLyne_mt_dev2"."Role_Master"
                WHERE role_id IN ({placeholders})
                AND LOWER(role_name) = 'admin'
            """),
            params
        ).fetchone()

        return admin_row is not None
    except Exception as e:
        current_app.logger.error(f"Error checking admin status: {e}")
        return False


# ─────────────────────────────────────────────
# HELPER: Fetch a client scoped to the caller's tenant, or None.
# Centralizes the "does this client exist AND belong to me" check that
# used to be duplicated (or missing entirely) across routes.
# ─────────────────────────────────────────────
def get_client_or_404(session, client_id, tenant_id, columns="*"):
    return session.execute(
        text(f'SELECT {columns} FROM {T("Client_Master")} WHERE client_id = :cid AND tenant_id = :tid'),
        {"cid": client_id, "tid": tenant_id}
    ).fetchone()


# ─────────────────────────────────────────────
# HELPER: Pack a dict into the __meta__...__end_meta__ convention that
# calendar_routes.py already parses back out of Client_Interactions.notes
# for contact_method=1 (Training Calendar) rows. Reusing this exact
# convention means the calendar route needs zero changes to its parsing
# logic — it just gets extra keys inside `meta` (training_id, training_to,
# source) that it wasn't reading before.
# ─────────────────────────────────────────────
def _pack_calendar_meta(meta: dict) -> str:
    return f"__meta__{json.dumps(meta)}__end_meta__"


# ─────────────────────────────────────────────
# HELPER: Serialize a Client_Master row to dict
# Optionally enriches with latest Opportunity
# ─────────────────────────────────────────────
def serialize_client(row, opportunity=None):
    """Convert a Client_Master row (and optional opportunity row) to response dict."""

    client = {
        "id":                   row.client_id,       # legacy alias
        "client_id":            row.client_id,
        "display_id":           getattr(row, 'display_id', None),  # ✅ Display ID for UI
        "name":                 row.client_company_name,   # legacy alias
        "client_company_name":  row.client_company_name,
        "client_contact_name":  row.client_contact_name,
        "address":              row.address or '',
        # City / State / PIN are now stored as their own columns (see
        # migration above) instead of only living inside the combined
        # `address` string — exposed here so the frontend can read back
        # the exact values the user typed, e.g. to prefill a training
        # batch's location from the client's own address without having
        # to re-parse `address`.
        "city":                 getattr(row, 'city', None) or '',
        "state":                getattr(row, 'state', None) or '',
        "country_id":           row.country_id,
        "post_code":            row.post_code or '',
        "phone":                row.client_phone or '',    # legacy alias
        "client_phone":         row.client_phone or '',
        "email":                row.client_email or '',   # legacy alias
        "client_email":         row.client_email or '',
        "client_website":       row.client_website or '',
        "default_currency_id":  row.default_currency_id,
        "tenant_id":            row.tenant_id,
        "primary_contact_department": row.primary_contact_department or '',
        # Name + Email pairs per department (replaces the old single
        # free-text purchase_department_contact / finance_department_contact
        # fields for anything created/edited going forward).
        "primary_contact_name":  getattr(row, 'primary_contact_name', None) or '',
        "primary_contact_email": getattr(row, 'primary_contact_email', None) or '',
        "purchase_contact_name":  getattr(row, 'purchase_contact_name', None) or '',
        "purchase_contact_email": getattr(row, 'purchase_contact_email', None) or '',
        "finance_contact_name":  getattr(row, 'finance_contact_name', None) or '',
        "finance_contact_email": getattr(row, 'finance_contact_email', None) or '',
        # Legacy single-text columns — kept only so old rows created before
        # this rework still display something; no longer written to.
        # NOTE: use getattr() here (not row.xxx) because on schemas where
        # these legacy columns don't exist, direct attribute access on a
        # SQLAlchemy Row raises "Could not locate column in row for
        # column '...'" rather than AttributeError, which `or ''` can't
        # rescue you from.
        "purchase_department_contact": getattr(row, 'purchase_department_contact', None) or '',
        "finance_department_contact": getattr(row, 'finance_department_contact', None) or '',
        # `training_location` holds the raw street-level address text the
        # user typed into the "Address" field on the create/edit form,
        # BEFORE city/state/pincode were appended to build the combined
        # `address` string above. This is the exact source used to
        # prefill a training batch's location "as it was written" in the
        # client form.
        "training_location": row.training_location or '',
        "mhe_training_details": row.mhe_training_details or '',
        "attached_documents": row.attached_documents or '',
        "created_at":           row.created_at.isoformat() if row.created_at else None,
    }

    # Enrich with opportunity / pipeline data if available
    if opportunity:
        misc = {}
        if opportunity.misc_col1:
            try:
                misc = json.loads(opportunity.misc_col1)
            except Exception:
                pass

        client.update({
            "opportunity_id":          opportunity.opportunity_id,
            "stage_id":                opportunity.stage_id,
            "stage_name": "Enquiry" if opportunity.stage_name == "Lead" else opportunity.stage_name,
            "stage_type":              opportunity.stage_type,
            "pipeline_type":           "training" if opportunity.stage_type == STAGE_TYPE_TRAINING else "sales",
            "sales_stage": ("Enquiry" if opportunity.stage_name == "Lead" else opportunity.stage_name) if opportunity.stage_type == STAGE_TYPE_SALES else misc.get('sales_stage'),
            "training_stage":          opportunity.stage_name if opportunity.stage_type == STAGE_TYPE_TRAINING else misc.get('training_stage'),
            "opportunity_title":       opportunity.opportunity_title,
            "opportunity_value":       opportunity.opportunity_value,
            "opportunity_owner_employee_id": opportunity.opportunity_owner_employee_id,
            "salesperson":             misc.get('salesperson', ''),
            "status":                  misc.get('status', 'Active'),
            "marketing_opt_in":        misc.get('marketing_opt_in', False),
            "contact_made":            misc.get('contact_made', 'No'),
            "preferred_contact_method": misc.get('preferred_contact_method', 'Phone'),
            "notes":                   misc.get('notes', ''),
            "created_by":              misc.get('created_by_user_id'),  # For role-based filtering
        })
    else:
        # Defaults when no opportunity exists yet
        client.update({
            "opportunity_id":     None,
            "stage_id":           None,
            "stage_name":         None,
            "pipeline_type":      "sales",
            "sales_stage":        None,
            "training_stage":     None,
            "salesperson":        '',
            "status":             'Active',
            "marketing_opt_in":   False,
            "contact_made":       'No',
            "preferred_contact_method": 'Phone',
            "notes":              '',
            "created_by":         None,  # For role-based filtering
        })

    return client


# ─────────────────────────────────────────────
# HELPER: Serialize a Training_Details row to dict
# ─────────────────────────────────────────────
def serialize_training(row):
    raw_participants = row.participants
    if isinstance(raw_participants, str):
        try:
            raw_participants = json.loads(raw_participants)
        except Exception:
            raw_participants = []

    return {
        "training_id":     row.training_id,
        "client_id":       row.client_id,
        "training_from":   row.training_from.isoformat() if row.training_from else "",
        "training_to":     row.training_to.isoformat() if row.training_to else "",
        "training_fees":   row.training_fees,
        "trainer_name":    row.trainer_name,
        "client_address":  row.client_address,
        "city":            row.city,
        "state":           row.state,
        "pin_code":        row.pin_code,
        "remarks":         row.remarks,
        "event_number":    row.event_number,
        "stage":           getattr(row, 'stage', None) or 'Training Scheduled',
        "participants":    raw_participants or [],
    }


# ─────────────────────────────────────────────────────────────
# ROUTE: POST /clients/<client_id>/training
# Creates a NEW training session for this client. A client can have
# many training sessions over time, so this always INSERTs a fresh
# row — it no longer upserts/overwrites a single existing row.
#
# NEW: also creates a linked Training Calendar entry (see the
# "Training Calendar sync" changelog at the top of this file).
# ─────────────────────────────────────────────────────────────
@customer_bp.route("/clients/<int:client_id>/training", methods=["POST"])
@token_required
def create_training_session(client_id):
    session = SessionLocal()

    try:
        # NOTE: now also pulling client_company_name — needed to build the
        # calendar event's title below (it wasn't fetched here before).
        client = get_client_or_404(
            session, client_id, request.current_user.tenant_id,
            columns="client_id, client_company_name"
        )
        if not client:
            return jsonify({"error": "Client not found"}), 404

        data = request.get_json(silent=True) or {}
        errors = {}

        def parse_date(value, field):
            if value in (None, ""):
                return None, True
            try:
                return datetime.strptime(value, "%Y-%m-%d").date(), True
            except (ValueError, TypeError):
                errors[field] = f"'{field}' must be a valid date in YYYY-MM-DD format"
                return None, False

        training_from, _ = parse_date(data.get("training_from"), "training_from")
        training_to, _ = parse_date(data.get("training_to"), "training_to")

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

        event_number = (data.get("event_number") or "").strip()
        if not event_number:
            errors["event_number"] = "Event Number is required"

        if errors:
            return jsonify({"error": "Validation failed", "details": errors}), 400

        # Server-assigns a stable id to any participant that doesn't
        # already have one. The frontend already assigns ids client-side,
        # but this is defensive: every later add/remove/update call
        # addresses a participant by id, so no participant should ever
        # end up id-less.
        participants_in = data.get("participants") or []
        for p in participants_in:
            if not p.get("id"):
                p["id"] = f"participant_{uuid.uuid4().hex[:12]}"
            p.setdefault("mainTraining", False)
            p.setdefault("trainingRecords", [])

        params = {
            "client_id": client_id,
            "training_from": training_from,
            "event_number": event_number,
            "training_to": training_to,
            "training_fees": training_fees,
            "trainer_name": (data.get("trainer_name") or "").strip() or None,
            "client_address": (data.get("client_address") or "").strip() or None,
            "city": (data.get("city") or "").strip() or None,
            "state": (data.get("state") or "").strip() or None,
            "pin_code": pin_code,
            "remarks": (data.get("remarks") or "").strip() or None,
            "participants": json.dumps(participants_in),
        }

        result = session.execute(
            text("""
                INSERT INTO "streemLyne_mt_dev2"."Training_Details"
                    (client_id, event_number, training_from, training_to, training_fees,
                     trainer_name, client_address, city, state, pin_code, remarks,
                     participants)
                VALUES
                    (:client_id, :event_number, :training_from, :training_to, :training_fees,
                     :trainer_name, :client_address, :city, :state, :pin_code, :remarks,
                     :participants)
                RETURNING training_id
            """),
            params,
        )
        new_training_id = result.fetchone().training_id



        

        # ─────────────────────────────────────────────────────────────
        # NEW: auto-create a Training Calendar entry linked to this batch.
        #
        # Reuses the EXACT same Client_Interactions / contact_method=1 /
        # __meta__ convention the calendar page's manual "Add Training
        # Date" button already uses (see calendar_routes.py's
        # create_calendar_event) — so GET /calendar/events picks this up
        # automatically with no changes to the read query itself.
        #
        # training_id / training_to / source ride along in the meta so
        # the frontend can tell this event apart from a manually-created
        # one and deep-link back to this specific batch.
        #
        # Only created if training_from was actually provided — a
        # draft batch with no dates yet has nothing to put on a calendar.
        # This is a create-time-only sync: if a batch's dates change
        # later there's currently no route that edits them (only
        # participants get PATCHed), so no update path is needed yet.
        # ─────────────────────────────────────────────────────────────
        if training_from:
            calendar_meta = {
                "title": f"{client.client_company_name} - Training",
                "type": "Training",
                "status": "Scheduled",
                "training_id": new_training_id,
                "training_to": training_to.isoformat() if training_to else None,
                "team_member": (data.get("trainer_name") or "").strip(),
                "source": "training_session",
            }
            session.execute(
                text("""
                    INSERT INTO "streemLyne_mt_dev2"."Client_Interactions"
                        (client_id, contact_method, contact_date, notes)
                    VALUES
                        (:client_id, 1, :contact_date, :notes)
                """),
                {
                    "client_id": client_id,
                    "contact_date": training_from,
                    "notes": _pack_calendar_meta(calendar_meta),
                }
            )

        # Single commit covers BOTH inserts (Training_Details +
        # Client_Interactions) — if either fails, both roll back together
        # so a batch can never exist without its calendar entry or
        # vice versa.
        session.commit()


        return jsonify({
            "success": True,
            "message": "Training session saved successfully",
            "training_id": new_training_id,
        }), 201

    except Exception as e:
        session.rollback()
        current_app.logger.exception(e)
        return jsonify({"error": "Failed to save training session", "details": str(e)}), 500

    finally:
        session.close()
        
@customer_bp.route('/training/next-event-number', methods=['GET'])
@token_required
def get_next_event_number():
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        row = session.execute(
            text("""
                SELECT MAX(NULLIF(regexp_replace(event_number, '[^0-9]', '', 'g'), '')::int) AS max_event_no
                FROM "streemLyne_mt_dev2"."Services_Master_archive" sm
                JOIN "streemLyne_mt_dev2"."Client_Master" cm ON cm.client_id = sm.client_id
                WHERE cm.tenant_id = :tid
            """),
            {"tid": tenant_id}
        ).fetchone()

        next_number = (row.max_event_no or 0) + 1
        return jsonify({"next_event_number": str(next_number)}), 200

    except Exception as e:
        current_app.logger.exception(f"Error in GET /training/next-event-number: {e}")
        return jsonify({'error': 'Failed to compute next event number', 'details': str(e)}), 500
    finally:
        session.close()

# ─────────────────────────────────────────────────────────────
# ROUTE: GET /clients/<client_id>/training
# Lists EVERY training session saved for this client, newest first.
# Powers the "Training Sessions" table on the client details page.
# ─────────────────────────────────────────────────────────────
@customer_bp.route("/clients/<int:client_id>/training", methods=["GET"])
@token_required
def list_training_sessions(client_id):
    session = SessionLocal()

    try:
        client = get_client_or_404(session, client_id, request.current_user.tenant_id, columns="client_id")
        if not client:
            return jsonify({"error": "Client not found"}), 404

        rows = session.execute(
            text("""
                SELECT *
                FROM "streemLyne_mt_dev2"."Training_Details"
                WHERE client_id = :client_id
                ORDER BY training_id DESC
            """),
            {"client_id": client_id},
        ).fetchall()

        return jsonify([serialize_training(r) for r in rows]), 200

    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"error": str(e)}), 500

    finally:
        session.close()


# ─────────────────────────────────────────────────────────────
# ROUTE: GET /clients/<client_id>/training/<training_id>
# Fetches ONE training session — used by the participant detail popup
# to look up that participant's name / MHE training records within
# this specific session.
# ─────────────────────────────────────────────────────────────
@customer_bp.route("/clients/<int:client_id>/training/<int:training_id>", methods=["GET"])
@token_required
def get_training_session(client_id, training_id):
    session = SessionLocal()

    try:
        client = get_client_or_404(session, client_id, request.current_user.tenant_id, columns="client_id")
        if not client:
            return jsonify({"error": "Client not found"}), 404

        row = session.execute(
            text("""
                SELECT *
                FROM "streemLyne_mt_dev2"."Training_Details"
                WHERE training_id = :tid AND client_id = :cid
            """),
            {"tid": training_id, "cid": client_id},
        ).fetchone()

        if not row:
            return jsonify({"error": "Training session not found"}), 404

        return jsonify(serialize_training(row)), 200

    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"error": str(e)}), 500

    finally:
        session.close()


# ─────────────────────────────────────────────────────────────
# ROUTE: PATCH /clients/<client_id>/training/<training_id>/participants
# Adds, removes, or updates ONE participant on an already-saved
# training session, without touching the rest of the session's fields.
#
# Body shapes:
#   { "action": "add",    "name": "Jane Doe" }
#   { "action": "remove", "participant_id": "participant_abc123" }
#   { "action": "update", "participant_id": "participant_abc123",
#     "participant": { "name": ..., "mainTraining": ..., "trainingRecords": [...] } }
#
# Used by:
#   - the "Training Sessions" table on the client details page (add /
#     remove a participant by name, inline in the table)
#   - the participant detail popup (update mainTraining flag and
#     trainingRecords as pre/post-test + certificate work happens)
# ─────────────────────────────────────────────────────────────
@customer_bp.route("/clients/<int:client_id>/training/<int:training_id>/participants", methods=["PATCH"])
@token_required
def modify_training_participants(client_id, training_id):
    session = SessionLocal()

    try:
        client = get_client_or_404(session, client_id, request.current_user.tenant_id, columns="client_id")
        if not client:
            return jsonify({"error": "Client not found"}), 404

        row = session.execute(
            text("""
                SELECT training_id, participants
                FROM "streemLyne_mt_dev2"."Training_Details"
                WHERE training_id = :tid AND client_id = :cid
            """),
            {"tid": training_id, "cid": client_id}
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
                    break
            if not found:
                return jsonify({"error": "Participant not found in this session"}), 404

        else:
            return jsonify({"error": "action must be 'add', 'remove', or 'update'"}), 400

        session.execute(
            text("""
                UPDATE "streemLyne_mt_dev2"."Training_Details"
                SET participants = :participants, updated_at = NOW()
                WHERE training_id = :tid
            """),
            {"participants": json.dumps(participants), "tid": training_id}
        )
        session.commit()

        return jsonify({"success": True, "participants": participants}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(e)
        return jsonify({"error": str(e)}), 500

    finally:
        session.close()

# ─────────────────────────────────────────────────────────────
# ROUTE: PATCH /clients/<client_id>/training/<training_id>
# Edits an already-saved training session's own fields (dates, fees,
# trainer, location, event number, remarks) — separate from the
# participants-only PATCH above. Powers the "Edit" button on the
# Training Batches table.
#
# NOTE: does NOT touch the linked Training Calendar entry created at
# creation time (see the "Training Calendar sync" changelog at the top
# of this file) — that sync is create-time-only today. If training_from
# changes here, the calendar entry will be stale until that's built.
# ─────────────────────────────────────────────────────────────
@customer_bp.route("/clients/<int:client_id>/training/<int:training_id>", methods=["PATCH"])
@token_required
def update_training_session(client_id, training_id):
    session = SessionLocal()

    try:
        client = get_client_or_404(session, client_id, request.current_user.tenant_id, columns="client_id")
        if not client:
            return jsonify({"error": "Client not found"}), 404

        existing = session.execute(
            text("""
                SELECT training_id, training_from, training_to
                FROM "streemLyne_mt_dev2"."Training_Details"
                WHERE training_id = :tid AND client_id = :cid
            """),
            {"tid": training_id, "cid": client_id},
        ).fetchone()
        if not existing:
            return jsonify({"error": "Training session not found"}), 404

        data = request.get_json(silent=True) or {}
        errors = {}

        def parse_date(value, field):
            if value in (None, ""):
                return None, True
            try:
                return datetime.strptime(value, "%Y-%m-%d").date(), True
            except (ValueError, TypeError):
                errors[field] = f"'{field}' must be a valid date in YYYY-MM-DD format"
                return None, False

        set_clauses = []
        params = {"tid": training_id, "cid": client_id}

        if "training_from" in data:
            training_from, _ = parse_date(data.get("training_from"), "training_from")
            set_clauses.append("training_from = :training_from")
            params["training_from"] = training_from
        if "training_to" in data:
            training_to, _ = parse_date(data.get("training_to"), "training_to")
            set_clauses.append("training_to = :training_to")
            params["training_to"] = training_to

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
            set_clauses.append("training_fees = :training_fees")
            params["training_fees"] = fees

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

        effective_from = params.get("training_from") if "training_from" in data else existing.training_from
        effective_to   = params.get("training_to")   if "training_to"   in data else existing.training_to

        if effective_from and effective_to and effective_to < effective_from:
            errors["training_to"] = "Training end date cannot be before the start date"

        if errors:
            return jsonify({"error": "Validation failed", "details": errors}), 400

        if not set_clauses:
            return jsonify({"error": "No updatable fields provided"}), 400

        set_clauses.append("updated_at = NOW()")

        session.execute(
            text(f"""
                UPDATE "streemLyne_mt_dev2"."Training_Details"
                SET {', '.join(set_clauses)}
                WHERE training_id = :tid AND client_id = :cid
            """),
            params,
        )
        session.commit()

        row = session.execute(
            text('SELECT * FROM "streemLyne_mt_dev2"."Training_Details" WHERE training_id = :tid'),
            {"tid": training_id},
        ).fetchone()

        return jsonify(serialize_training(row)), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(e)
        return jsonify({"error": "Failed to update training session", "details": str(e)}), 500

    finally:
        session.close()


@customer_bp.route("/clients/<int:client_id>/training/<int:training_id>/stage", methods=["PATCH"])
@token_required
def update_training_stage(client_id, training_id):
    session = SessionLocal()
    try:
        client = get_client_or_404(session, client_id, request.current_user.tenant_id, columns="client_id")
        if not client:
            return jsonify({"error": "Client not found"}), 404

        data = request.get_json(silent=True) or {}
        new_stage = data.get("stage")
        if new_stage not in TRAINING_PIPELINE_STAGES:
            return jsonify({"error": f"Invalid stage. Must be one of: {TRAINING_PIPELINE_STAGES}"}), 400

        row = session.execute(
            text("""
                SELECT stage, training_from, training_to, trainer_name
                FROM "streemLyne_mt_dev2"."Training_Details"
                WHERE training_id = :tid AND client_id = :cid
            """),
            {"tid": training_id, "cid": client_id}
        ).fetchone()
        if not row:
            return jsonify({"error": "Training session not found"}), 404

        err = validate_training_stage_change(
            getattr(row, "stage", None), new_stage,
            {"date_from": row.training_from, "date_to": row.training_to, "trainer_name": row.trainer_name},
        )
        if err:
            return jsonify({"error": err}), 422

        session.execute(
            text("""
                UPDATE "streemLyne_mt_dev2"."Training_Details"
                SET stage = :stage, updated_at = NOW()
                WHERE training_id = :tid AND client_id = :cid
            """),
            {"stage": new_stage, "tid": training_id, "cid": client_id}
        )
        session.commit()
        return jsonify({"training_id": training_id, "client_id": client_id, "stage": new_stage}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(e)
        return jsonify({"error": "Failed to update training stage", "details": str(e)}), 500
    finally:
        session.close()



# ─────────────────────────────────────────────
# HELPER: Fetch latest opportunity for a client
# ─────────────────────────────────────────────
def get_latest_opportunity(session, client_id):
    # For converted clients, get the training opportunity first
    training_opp = session.execute(
        text("""
            SELECT od.opportunity_id, od.client_id, od.stage_id,
                   od.opportunity_title, od.opportunity_description,
                   od.opportunity_owner_employee_id, od.opportunity_value,
                   od.currency_id, od."Misc_Col1" AS misc_col1,
                   od.created_at,
                   sm.stage_name, sm.stage_type
            FROM "streemLyne_mt_dev2"."Opportunity_Details" od
            LEFT JOIN "streemLyne_mt_dev2"."Pipeline_Stage_Master" sm ON sm.stage_id = od.stage_id
            WHERE od.client_id = :cid
            AND sm.stage_type = 2
            ORDER BY od.created_at DESC
            LIMIT 1
        """),
        {"cid": client_id}
    ).fetchone()

    if training_opp:
        return training_opp

    return session.execute(
        text("""
            SELECT od.opportunity_id, od.client_id, od.stage_id,
                   od.opportunity_title, od.opportunity_description,
                   od.opportunity_owner_employee_id, od.opportunity_value,
                   od.currency_id, od."Misc_Col1" AS misc_col1,
                   od.created_at,
                   sm.stage_name, sm.stage_type
            FROM "streemLyne_mt_dev2"."Opportunity_Details" od
            LEFT JOIN "streemLyne_mt_dev2"."Pipeline_Stage_Master" sm ON sm.stage_id = od.stage_id
            WHERE od.client_id = :cid
            AND (sm.stage_type = 1 OR sm.stage_type IS NULL)
            ORDER BY od.created_at DESC
            LIMIT 1
        """),
        {"cid": client_id}
    ).fetchone()

# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /clients
# ═════════════════════════════════════════════════════════════════════════════
@customer_bp.route('/clients', methods=['GET', 'OPTIONS'])
@token_required
def get_customers():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        current_app.logger.info(f"📊 GET /clients called")
        current_app.logger.info(f"User: {request.current_user.id}, Tenant: {request.current_user.tenant_id}, Employee: {request.current_user.employee_id}")

        if not hasattr(request.current_user, 'tenant_id') or request.current_user.tenant_id is None:
            current_app.logger.error("❌ User has no tenant_id")
            return jsonify({'error': 'User tenant not found', 'details': 'User account is not associated with a tenant'}), 400

        current_app.logger.info(f"Querying Client_Master for tenant_id={request.current_user.tenant_id}")

        clients = session.execute(
            text("""
                SELECT cm.*, cm.display_id
                FROM "streemLyne_mt_dev2"."Client_Master" cm
                WHERE cm.tenant_id = :tid
                ORDER BY cm.display_id DESC
            """),
            {"tid": request.current_user.tenant_id}
        ).fetchall()

        current_app.logger.info(f"✅ Query returned {len(clients)} clients")

        result = []
        for idx, client_row in enumerate(clients):
            try:
                current_app.logger.debug(f"Serializing client {idx+1}/{len(clients)}: {client_row.client_id}")
                opp = get_latest_opportunity(session, client_row.client_id)
                serialized = serialize_client(client_row, opp)
                result.append(serialized)
            except Exception as serialize_error:
                current_app.logger.error(f"❌ Error serializing client {client_row.client_id}: {serialize_error}")
                import traceback
                current_app.logger.error(traceback.format_exc())
                continue

        current_app.logger.info(f"✅ Successfully serialized {len(result)} clients, returning to frontend")
        return jsonify(result), 200

    except Exception as e:
        current_app.logger.exception(f"❌ CRITICAL ERROR in GET /clients: {e}")
        import traceback
        current_app.logger.error(f"Full traceback:\n{traceback.format_exc()}")

        return jsonify({
            'error': 'Failed to fetch clients',
            'details': str(e),
            'type': type(e).__name__
        }), 500
    finally:
        session.close()
        current_app.logger.info("Session closed")

#═════════════════════════════════════════════════════════════════════════════
# ROUTE: POST /clients
# Creates a Client_Master record + initial Opportunity_Details record
# ═════════════════════════════════════════════════════════════════════════════
@customer_bp.route('/clients', methods=['POST'])
@token_required
def create_customer():
    session = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}

        # Validate required fields
        if not data.get('name') and not data.get('client_company_name'):
            return jsonify({'error': 'Client name is required'}), 400
        if not data.get('phone') and not data.get('client_phone'):
            return jsonify({'error': 'Phone is required'}), 400

        email = (data.get('client_email') or data.get('email') or '').strip()
        if email and not EMAIL_RE.match(email):
            return jsonify({'error': 'Invalid email format'}), 400

        # Per-department contact emails are optional, but if provided they
        # must be well-formed. Collected into `errors` so all three come
        # back in one response instead of failing one field at a time.
        contact_email_errors = {}
        primary_contact_email  = validate_optional_email(data.get('primary_contact_email'), 'primary_contact_email', contact_email_errors)
        purchase_contact_email = validate_optional_email(data.get('purchase_contact_email'), 'purchase_contact_email', contact_email_errors)
        finance_contact_email  = validate_optional_email(data.get('finance_contact_email'), 'finance_contact_email', contact_email_errors)
        if contact_email_errors:
            return jsonify({'error': 'Validation failed', 'details': contact_email_errors}), 400

        tenant_id = request.current_user.tenant_id
        if not tenant_id:
            return jsonify({'error': 'User account is not associated with a tenant'}), 400

        company_name = data.get('client_company_name') or data.get('name')
        phone        = data.get('client_phone') or data.get('phone')
        address      = data.get('address', '')
        contact_name = data.get('client_contact_name', '')
        country_id   = data.get('country_id')
        currency_id  = data.get('default_currency_id')

        # City / State / PIN Code / raw street address, stored as their own
        # columns (see migration in the module docstring) so the exact
        # values the user typed are always available later, without having
        # to re-parse them back out of the combined `address` string.
        city             = data.get('city', '')
        state            = data.get('state', '')
        post_code        = data.get('post_code', '')
        training_location = data.get('training_location', '')

        # Insert into Client_Master (display_id auto-generated by trigger)
        result = session.execute(
        text("""
            INSERT INTO "streemLyne_mt_dev2"."Client_Master"
            (
            tenant_id,
            client_company_name,
            client_contact_name,
            address,
            city,
            state,
            country_id,
            post_code,
            client_phone,
            client_email,
            client_website,
            default_currency_id,

            primary_contact_department,
            primary_contact_name,
            primary_contact_email,
            purchase_contact_name,
            purchase_contact_email,
            finance_contact_name,
            finance_contact_email,
            training_location,
            mhe_training_details,
            attached_documents,

            created_at
        )
        VALUES
        (
            :tenant_id,
            :company_name,
            :contact_name,
            :address,
            :city,
            :state,
            :country_id,
            :post_code,
            :phone,
            :email,
            :website,
            :currency_id,

            :primary_contact_department,
            :primary_contact_name,
            :primary_contact_email,
            :purchase_contact_name,
            :purchase_contact_email,
            :finance_contact_name,
            :finance_contact_email,
            :training_location,
            :mhe_training_details,
            :attached_documents,

            :created_at
        )
        RETURNING client_id
    """),
    {
        "tenant_id": tenant_id,
        "company_name": company_name,
        "contact_name": contact_name,
        "address": address,
        "city": city,
        "state": state,
        "country_id": country_id,
        "post_code": post_code,
        "phone": phone,
        "email": email,
        "website": data.get("client_website", ""),
        "currency_id": currency_id,

        "primary_contact_department": data.get("primary_contact_department", ""),
        "primary_contact_name": data.get("primary_contact_name", ""),
        "primary_contact_email": primary_contact_email,
        "purchase_contact_name": data.get("purchase_contact_name", ""),
        "purchase_contact_email": purchase_contact_email,
        "finance_contact_name": data.get("finance_contact_name", ""),
        "finance_contact_email": finance_contact_email,
        "training_location": training_location,
        "mhe_training_details": data.get("mhe_training_details", ""),
        "attached_documents": data.get("attached_documents", ""),

        "created_at": datetime.utcnow()
    }
)
        new_client_id = result.fetchone().client_id
        current_app.logger.info(f"✅ Client_Master record created: {new_client_id}")

        # Resolve default sales stage (first stage with stage_type=1)
        stage_row = session.execute(
            text("""
                SELECT stage_id, stage_name FROM "streemLyne_mt_dev2"."Pipeline_Stage_Master""
                WHERE stage_type = :stype
                ORDER BY stage_id ASC
                LIMIT 1
            """),
            {"stype": STAGE_TYPE_SALES}
        ).fetchone()

        default_stage_id   = stage_row.stage_id   if stage_row else None
        default_stage_name = stage_row.stage_name if stage_row else 'Enquiry'

        # Pack extra fields into Misc_Col1 JSON
        misc = {
            "salesperson":              data.get('salesperson', ''),
            "status":                   "Active",
            "marketing_opt_in":         data.get('marketing_opt_in', False),
            "contact_made":             data.get('contact_made', 'No'),
            "preferred_contact_method": data.get('preferred_contact_method', 'Phone'),
            "notes":                    data.get('notes', ''),
            "pipeline_type":            "sales",
            "created_by_user_id":       request.current_user.id,
        }

        # Insert initial Opportunity_Details
        session.execute(
            text("""
                INSERT INTO "streemLyne_mt_dev2"."Opportunity_Details"
                    (client_id, opportunity_title, opportunity_description,
                     opportunity_date, opportunity_owner_employee_id,
                     stage_id, opportunity_value, currency_id,
                     created_at, "Misc_Col1")
                VALUES
                    (:client_id, :title, :desc,
                     :opp_date, :owner_emp_id,
                     :stage_id, :opp_value, :currency_id,
                     :created_at, :misc)
            """),
            {
                "client_id":    new_client_id,
                "title":        f"{company_name} - {default_stage_name}",
                "desc":         data.get('notes', ''),
                "opp_date":     datetime.utcnow().date(),
                "owner_emp_id": request.current_user.employee_id,
                "stage_id":     default_stage_id,
                "opp_value":    data.get('opportunity_value', 0),
                "currency_id":  currency_id,
                "created_at":   datetime.utcnow(),
                "misc":         json.dumps(misc)
            }
        )

        session.commit()

        # Fetch and return the full record with display_id
        new_client = session.execute(
            text('SELECT * FROM "streemLyne_mt_dev2"."Client_Master" WHERE client_id = :cid'),
            {"cid": new_client_id}
        ).fetchone()
        opp = get_latest_opportunity(session, new_client_id)

        current_app.logger.info(f"✅ Client {new_client_id} created")

        return jsonify({
            'success': True,
            'message': 'Client created successfully',
            'customer': serialize_client(new_client, opp)
        }), 201

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error creating client: {e}")
        return jsonify({'error': f'Failed to create client: {str(e)}'}), 500
    finally:
        session.close()






# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /clients/<client_id>
# ═════════════════════════════════════════════════════════════════════════════
@customer_bp.route('/clients/<int:client_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_customer(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        client_row = get_client_or_404(session, client_id, request.current_user.tenant_id)

        if not client_row:
            return jsonify({'error': 'Client not found'}), 404

        opp = get_latest_opportunity(session, client_id)
        client_data = serialize_client(client_row, opp)

        # ✅ Everyone in the client's tenant can view
        return jsonify(client_data), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching client {client_id}: {e}")
        return jsonify({'error': 'Failed to fetch client'}), 500
    finally:
        session.close()

# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: PUT /clients/<client_id>
# ═════════════════════════════════════════════════════════════════════════════
@customer_bp.route('/clients/<int:client_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_customer(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        client_row = get_client_or_404(session, client_id, request.current_user.tenant_id)

        if not client_row:
            return jsonify({'error': 'Client not found'}), 404

        opp = get_latest_opportunity(session, client_id)
        data = request.get_json(silent=True) or {}

        incoming_email = data.get('client_email', data.get('email'))
        if incoming_email and not EMAIL_RE.match(incoming_email.strip()):
            return jsonify({'error': 'Invalid email format'}), 400

        # Per-department contact emails are optional, but validated the
        # same way as create_customer() if the caller sends them.
        contact_email_errors = {}
        for field in ('primary_contact_email', 'purchase_contact_email', 'finance_contact_email'):
            if field in data:
                validate_optional_email(data[field], field, contact_email_errors)
        if contact_email_errors:
            return jsonify({'error': 'Validation failed', 'details': contact_email_errors}), 400

        # ── Update Client_Master fields ───────────────────────────────────────
        client_updates = {}
        field_map = {
            'name':                 'client_company_name',
            'client_company_name':  'client_company_name',
            'client_contact_name':  'client_contact_name',
            'address':              'address',
            'city':                 'city',
            'state':                'state',
            'country_id':           'country_id',
            'post_code':            'post_code',
            'phone':                'client_phone',
            'client_phone':         'client_phone',
            'email':                'client_email',
            'client_email':         'client_email',
            'client_website':       'client_website',
            'primary_contact_department': 'primary_contact_department',
            'primary_contact_name':  'primary_contact_name',
            'primary_contact_email': 'primary_contact_email',
            'purchase_contact_name': 'purchase_contact_name',
            'purchase_contact_email': 'purchase_contact_email',
            'finance_contact_name':  'finance_contact_name',
            'finance_contact_email': 'finance_contact_email',
            'training_location': 'training_location',
            'mhe_training_details': 'mhe_training_details',
            'attached_documents': 'attached_documents',
            'default_currency_id':  'default_currency_id',
        }
        for incoming, col in field_map.items():
            if incoming in data:
                client_updates[col] = data[incoming]

        if client_updates:
            set_clauses = ', '.join([f'"{k}" = :{k}' for k in client_updates])
            client_updates['cid'] = client_id
            session.execute(
                text(f'UPDATE "streemLyne_mt_dev2"."Client_Master" SET {set_clauses} WHERE client_id = :cid'),
                client_updates
            )

        # ── Update Opportunity_Details Misc_Col1 (extra fields) ──────────────
        misc_fields = [
            'salesperson', 'status', 'marketing_opt_in',
            'contact_made', 'preferred_contact_method', 'notes'
        ]
        extra_updates = {f: data[f] for f in misc_fields if f in data}

        if extra_updates and opp:
            existing_misc = {}
            if opp.misc_col1:
                try:
                    existing_misc = json.loads(opp.misc_col1)
                except Exception:
                    pass
            existing_misc.update(extra_updates)

            if 'notes' in extra_updates:
                existing_misc['notes'] = extra_updates['notes']

            session.execute(
                text("""
                    UPDATE "streemLyne_mt_dev2"."Opportunity_Details"
                    SET "Misc_Col1" = :misc
                    WHERE opportunity_id = :oid
                """),
                {"misc": json.dumps(existing_misc), "oid": opp.opportunity_id}
            )

        session.commit()

        # Return updated record
        updated_client = session.execute(
            text('SELECT * FROM "streemLyne_mt_dev2"."Client_Master" WHERE client_id = :cid'),
            {"cid": client_id}
        ).fetchone()
        updated_opp = get_latest_opportunity(session, client_id)

        current_app.logger.info(f"✅ Client {client_id} updated")

        return jsonify({
            'success': True,
            'message': 'Client updated successfully',
            'customer': serialize_client(updated_client, updated_opp)
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error updating client {client_id}: {e}")
        return jsonify({'error': f'Failed to update client: {str(e)}'}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: PATCH /clients/<client_id>/stage
# Updates Opportunity_Details stage — handles Sales → Training auto-transition
# ═════════════════════════════════════════════════════════════════════════════
@customer_bp.route('/clients/<int:client_id>/stage', methods=['PATCH', 'OPTIONS'])
@token_required
def update_customer_stage(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        client_row = get_client_or_404(session, client_id, request.current_user.tenant_id)

        if not client_row:
            return jsonify({'error': 'Client not found'}), 404

        data          = request.get_json(silent=True) or {}
        new_stage     = data.get('stage')
        pipeline_type = data.get('pipeline_type', 'sales')

        if not new_stage:
            return jsonify({'error': 'Stage is required'}), 400

        if pipeline_type not in ('sales', 'training'):
            return jsonify({'error': "pipeline_type must be 'sales' or 'training'"}), 400

        allowed_stages = SALES_STAGES if pipeline_type == 'sales' else TRAINING_STAGES
        if new_stage not in allowed_stages:
            return jsonify({
                'error': f"Invalid stage '{new_stage}' for {pipeline_type} pipeline",
                'allowed': sorted(allowed_stages)
            }), 400

        clear_training = data.get('clear_training', False)

        # Map frontend "Enquiry" to backend "Lead" (unified backend)
        backend_stage = "Lead" if new_stage == "Enquiry" else new_stage

        # Fetch current opportunity
        opp = get_latest_opportunity(session, client_id)
        old_stage    = opp.stage_name if opp else None
        old_pipeline = "training" if (opp and opp.stage_type == STAGE_TYPE_TRAINING) else "sales"

        existing_misc = {}
        if opp and opp.misc_col1:
            try:
                existing_misc = json.loads(opp.misc_col1)
            except Exception:
                pass

        # Determine stage_type for new stage
        target_stage_type = STAGE_TYPE_TRAINING if pipeline_type == 'training' else STAGE_TYPE_SALES

        # Look up the new stage_id from Stage_Master (using backend stage name)
        stage_row = session.execute(
            text("""
                SELECT stage_id, stage_name FROM "streemLyne_mt_dev2"."Pipeline_Stage_Master"
                WHERE LOWER(stage_name) = LOWER(:sname)
                AND stage_type = :stype
                LIMIT 1
            """),
            {"sname": backend_stage, "stype": target_stage_type}
        ).fetchone()

        # Fall back: match by name alone if stage_type miss
        if not stage_row:
            stage_row = session.execute(
                text("""
                    SELECT stage_id, stage_name, stage_type FROM "streemLyne_mt_dev2"."Pipeline_Stage_Master"
                    WHERE LOWER(stage_name) = LOWER(:sname)
                    LIMIT 1
                """),
                {"sname": backend_stage}
            ).fetchone()

        new_stage_id = stage_row.stage_id if stage_row else None

        # ── LOST: update status in Misc_Col1, don't change stage ─────────────
        if new_stage == 'Lost':
            existing_misc['status'] = 'Lost'
            if opp:
                session.execute(
                    text("""
                        UPDATE "streemLyne_mt_dev2"."Opportunity_Details"
                        SET "Misc_Col1" = :misc
                        WHERE opportunity_id = :oid
                    """),
                    {"misc": json.dumps(existing_misc), "oid": opp.opportunity_id}
                )
            session.commit()
            return jsonify({
                'success': True,
                'client_id': client_id,
                'old_stage': old_stage,
                'new_stage': new_stage,
                'status': 'Lost',
                'auto_transitioned': False
            }), 200

        # ── Active stage change ───────────────────────────────────────────────
        existing_misc['status'] = 'Active'

        auto_transitioned = False

        if pipeline_type == 'sales':
            existing_misc['pipeline_type'] = 'sales'
            existing_misc['sales_stage']   = new_stage

            # Auto-create training opportunity on "Converted"
            if new_stage == 'Converted' and not existing_misc.get('training_stage'):
                training_stage_row = session.execute(
                    text("""
                        SELECT stage_id, stage_name FROM "streemLyne_mt_dev2"."Pipeline_Stage_Master"
                        WHERE stage_type = :stype
                        AND stage_name = 'Awaiting Scheduling'
                        LIMIT 1
                    """),
                    {"stype": STAGE_TYPE_TRAINING}
                ).fetchone()

                if training_stage_row:
                    training_misc = {
                        **existing_misc,
                        "pipeline_type":   "training",
                        "training_stage":  training_stage_row.stage_name,
                        "sales_stage":     new_stage,
                    }
                    session.execute(
                        text("""
                            INSERT INTO "streemLyne_mt_dev2"."Opportunity_Details"
                                (client_id, opportunity_title, opportunity_date,
                                 opportunity_owner_employee_id, stage_id,
                                 opportunity_value, currency_id, created_at, "Misc_Col1")
                            VALUES
                                (:client_id, :title, :opp_date,
                                 :owner_emp_id, :stage_id,
                                 :opp_value, :currency_id, :created_at, :misc)
                        """),
                        {
                            "client_id":    client_id,
                            "title":        f"{client_row.client_company_name} - {training_stage_row.stage_name}",
                            "opp_date":     datetime.utcnow().date(),
                            "owner_emp_id": request.current_user.employee_id,
                            "stage_id":     training_stage_row.stage_id,
                            "opp_value":    opp.opportunity_value if opp else 0,
                            "currency_id":  opp.currency_id if opp else None,
                            "created_at":   datetime.utcnow(),
                            "misc":         json.dumps(training_misc)
                        }
                    )
                    auto_transitioned = True
                    current_app.logger.info(f"🔄 Training opportunity auto-created for client {client_id}")
                else:
                    current_app.logger.warning(
                        "⚠️ 'Training Scheduled' stage not found in Stage_Master — "
                        f"skipped auto-creating training opportunity for client {client_id}"
                    )

            # Clear training stage if moving back
            if clear_training and new_stage in ['Enquiry', 'Proposal']:
                existing_misc.pop('training_stage', None)
                current_app.logger.info(f"Training stage cleared for client {client_id}")

        elif pipeline_type == 'training':
            existing_misc['pipeline_type']  = 'training'
            existing_misc['training_stage'] = new_stage

        # Append stage change to notes
        note_entry = (
            f"\n[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')}] "
            f"Stage changed: {old_stage} → {new_stage} ({pipeline_type} pipeline)"
        )
        existing_misc['notes'] = (existing_misc.get('notes', '') or '') + note_entry

        # Update opportunity record
        if opp and new_stage_id:
            session.execute(
                text("""
                    UPDATE "streemLyne_mt_dev2"."Opportunity_Details"
                    SET stage_id = :stage_id,
                        opportunity_title = :title,
                        "Misc_Col1" = :misc
                    WHERE opportunity_id = :oid
                """),
                {
                    "stage_id": new_stage_id,
                    "title":    f"{client_row.client_company_name} - {new_stage}",
                    "misc":     json.dumps(existing_misc),
                    "oid":      opp.opportunity_id
                }
            )
        elif opp:
            # Stage not found in Stage_Master — update misc only
            session.execute(
                text("""
                    UPDATE "streemLyne_mt_dev2"."Opportunity_Details"
                    SET "Misc_Col1" = :misc
                    WHERE opportunity_id = :oid
                """),
                {"misc": json.dumps(existing_misc), "oid": opp.opportunity_id}
            )

        session.commit()
        current_app.logger.info(f"✅ Client {client_id} stage updated: {old_stage} → {new_stage}")

        return jsonify({
            'success':          True,
            'client_id':        client_id,
            'old_stage':        old_stage,
            'new_stage':        new_stage,
            'old_pipeline':     old_pipeline,
            'new_pipeline':     pipeline_type,
            'auto_transitioned': auto_transitioned
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error updating client stage: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: DELETE /clients/<client_id>
# ✅ FIXED: Removed admin-only restriction (everyone can delete)
# Checks for linked Project_Details and Client_Interactions before deleting
# ═════════════════════════════════════════════════════════════════════════════
@customer_bp.route('/clients/<int:client_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_customer(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        client_row = get_client_or_404(session, client_id, request.current_user.tenant_id, columns="client_id")

        if not client_row:
            return jsonify({'error': 'Client not found'}), 404

        # Guard: linked projects (replaces Job check)
        project_count = session.execute(
            text('SELECT COUNT(*) FROM "streemLyne_mt_dev2"."Project_Details" WHERE client_id = :cid'),
            {"cid": client_id}
        ).scalar()

        if project_count > 0:
            return jsonify({
                'error': f'Cannot delete client with {project_count} project(s). Delete projects first.'
            }), 400

        # Delete linked interactions (cascade)
        session.execute(
            text('DELETE FROM "streemLyne_mt_dev2"."Client_Interactions" WHERE client_id = :cid'),
            {"cid": client_id}
        )

        # Delete linked opportunities (cascade)
        session.execute(
            text('DELETE FROM "streemLyne_mt_dev2"."Opportunity_Details" WHERE client_id = :cid'),
            {"cid": client_id}
        )

        # Delete linked training sessions (cascade) — deletes ALL saved
        # training sessions for this client, not just one, since a
        # client can now have many rows in Training_Details.
        session.execute(
            text('DELETE FROM "streemLyne_mt_dev2"."Training_Details" WHERE client_id = :cid'),
            {"cid": client_id}
        )

        # Delete client (Client_Files rows cascade automatically via FK ON DELETE CASCADE)
        session.execute(
            text('DELETE FROM "streemLyne_mt_dev2"."Client_Master" WHERE client_id = :cid'),
            {"cid": client_id}
        )
        session.commit()

        current_app.logger.info(f"✅ Client {client_id} deleted by user {request.current_user.id}")

        return jsonify({'success': True, 'message': 'Client deleted successfully'}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error deleting client {client_id}: {e}")
        return jsonify({'error': 'Failed to delete client'}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /clients/search
# Searches Client_Master by company name, email, phone
# ═════════════════════════════════════════════════════════════════════════════
@customer_bp.route('/clients/search', methods=['GET', 'OPTIONS'])
@token_required
def search_customers():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        query_param = request.args.get('q', '').strip()
        if not query_param:
            return jsonify([]), 200

        like = f'%{query_param}%'

        rows = session.execute(
            text("""
                SELECT * FROM "streemLyne_mt_dev2"."Client_Master"
                WHERE tenant_id = :tid
                AND (
                    client_company_name ILIKE :q
                    OR client_email      ILIKE :q
                    OR client_phone      ILIKE :q
                    OR client_contact_name ILIKE :q
                )
                ORDER BY client_company_name ASC
                LIMIT 20
            """),
            {"tid": request.current_user.tenant_id, "q": like}
        ).fetchall()

        result = []
        for row in rows:
            opp = get_latest_opportunity(session, row.client_id)
            result.append(serialize_client(row, opp))

        current_app.logger.info(f"🔍 Search '{query_param}' → {len(result)} results")
        return jsonify(result), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Error searching clients: {e}")
        return jsonify({'error': 'Failed to search clients'}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /clients/stats
# Aggregates from Opportunity_Details + Stage_Master
# ═════════════════════════════════════════════════════════════════════════════
@customer_bp.route('/clients/stats', methods=['GET', 'OPTIONS'])
@token_required
def get_customer_stats():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        # Total clients for this tenant
        total = session.execute(
            text('SELECT COUNT(*) FROM "streemLyne_mt_dev2"."Client_Master" WHERE tenant_id = :tid'),
            {"tid": request.current_user.tenant_id}
        ).scalar()

        # Stage breakdown joined to stage type
        stage_rows = session.execute(
            text("""
                SELECT sm.stage_name, sm.stage_type, COUNT(od.opportunity_id) AS cnt
                FROM "streemLyne_mt_dev2"."Opportunity_Details" od
                JOIN "streemLyne_mt_dev2"."Client_Master" cm ON cm.client_id = od.client_id
                JOIN "streemLyne_mt_dev2"."Pipeline_Stage_Master" sm  ON sm.stage_id  = od.stage_id
                WHERE cm.tenant_id = :tid
                GROUP BY sm.stage_name, sm.stage_type
            """),
            {"tid": request.current_user.tenant_id}
        ).fetchall()

        sales_stages    = {}
        training_stages = {}
        for row in stage_rows:
            if row.stage_type == STAGE_TYPE_SALES:
                sales_stages[row.stage_name] = row.cnt
            elif row.stage_type == STAGE_TYPE_TRAINING:
                training_stages[row.stage_name] = row.cnt

        # Status breakdown from Misc_Col1
        all_opps = session.execute(
            text("""
                SELECT od."Misc_Col1" AS misc_col1
                FROM "streemLyne_mt_dev2"."Opportunity_Details" od
                JOIN "streemLyne_mt_dev2"."Client_Master" cm ON cm.client_id = od.client_id
                WHERE cm.tenant_id = :tid
            """),
            {"tid": request.current_user.tenant_id}
        ).fetchall()

        status_counts   = {}
        pipeline_counts = {}
        for row in all_opps:
            misc = {}
            if row.misc_col1:
                try:
                    misc = json.loads(row.misc_col1)
                except Exception:
                    pass
            s = misc.get('status', 'Active')
            p = misc.get('pipeline_type', 'sales')
            status_counts[s]   = status_counts.get(s, 0) + 1
            pipeline_counts[p] = pipeline_counts.get(p, 0) + 1

        return jsonify({
            'total':           total,
            'by_pipeline':     pipeline_counts,
            'sales_stages':    sales_stages,
            'training_stages': training_stages,
            'by_status':       status_counts
        }), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching client stats: {e}")
        return jsonify({'error': 'Failed to fetch statistics'}), 500
    finally:
        session.close()

# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /clients/<client_id>/test-results
# Fetch all test results for a specific client
# ═════════════════════════════════════════════════════════════════════════════
@customer_bp.route('/clients/<int:client_id>/test-results', methods=['GET'])
@token_required
def get_client_test_results(client_id):
    session = SessionLocal()
    try:
        # Verify client exists and belongs to caller's tenant
        client_row = get_client_or_404(session, client_id, request.current_user.tenant_id, columns="client_id")

        if not client_row:
            return jsonify({'error': 'Client not found'}), 404

        # Fetch all test results for this client
        rows = session.execute(
            text(f"""
                SELECT *
                FROM "{SCHEMA}"."Client_Interactions"
                WHERE client_id = :cid
                AND contact_method = 200
                ORDER BY created_at DESC
            """),
            {"cid": client_id}
        ).fetchall()

        # Import from test_grading_routes
        from .test_grading_routes import serialize_result, unpack_meta

        results = []
        for row in rows:
            try:
                result = serialize_result(row)
                results.append(result)
            except Exception as e:
                current_app.logger.error(f"Error serializing test result {row.interaction_id}: {e}")
                continue

        current_app.logger.info(f"✅ Found {len(results)} test results for client {client_id}")

        return jsonify(results), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching test results for client {client_id}: {e}")
        return jsonify({'error': 'Failed to fetch test results'}), 500
    finally:
        session.close()

# ─────────────────────────────────────────────────────────────────────────────
# NOTE: The old /clients/<id>/certificates/upload and GET /clients/<id>/certificates
# routes that used to live here have been REMOVED. They only ever stored a
# filename string in Client_Master.attached_documents with no real file behind
# it, and they silently conflicted with the certificates_bp blueprint that was
# also registered on the same URL. All file upload/list/delete now goes through
# client_files_routes.py:
#     POST   /clients/<client_id>/files/upload   (multipart: file, type)
#     GET    /clients/<client_id>/files           (?type=certificate|document|quotation)
#     DELETE /clients/files/<file_id>
# ─────────────────────────────────────────────────────────────────────────────
