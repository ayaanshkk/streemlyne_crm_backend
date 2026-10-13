"""

Pipeline Routes for StreemLyne CRM.

Provides Kanban board data for Sales and Training pipelines.

Training pipeline:

- Uses Services_Master as the source of training/course records.

- Services_Master is tenant-scoped.

- Training-specific fields are read from Services_Master.

- Client_Master is used only to resolve the company name.

- "Awaiting Scheduling" cards are derived (no batch row): a company whose

  latest sales stage is Converted and which has no batch created after its

  converted_at time.

Stage names

-----------

Stage names are never written in this file. They are looked up from

Stage_Master by stage_id on every request, so renaming a stage in the

database is picked up automatically. Stages are identified by the IDs below.

Configuration

-------------

Nothing environment-specific is hardcoded here. Every value below is read at

request time from Flask's app.config, falling back to an environment variable

of the same name. A missing value raises a RuntimeError (fail fast) instead of

silently using a default.

    DB_SCHEMA                    Postgres schema holding the CRM tables

    STAGE_TYPE_SALES             Stage_Master.stage_type value for sales stages

    COMMERCIAL_CATEGORY_ID        Client_Category_Master_ID for commercial clients

    ACTIVE_STATUS_ID              status_id meaning "active"

    STAGE_ID_LEAD                Stage_Master.stage_id of the Lead stage

    STAGE_ID_CONVERTED           Stage_Master.stage_id of the Converted stage

    STAGE_ID_AWAITING_SCHEDULING Stage_Master.stage_id of the awaiting stage

    STAGE_ID_TRAINING_DEFAULT    stage_id used when a Services_Master row has

                                 no stage

    STAGE_LABEL_ENQUIRY          Display label shown instead of the Lead stage

                                 name (not stored in Stage_Master)

    MISC_KEY_SALES_STAGE          Key inside Opportunity_Details.Misc_Col1 JSON

                                 holding the sales stage

    MISC_KEY_CONVERTED_AT         Key inside Misc_Col1 JSON holding the

                                 converted-at timestamp

"""

import json

import os

import re

import io

from flask import Blueprint, request, jsonify, current_app

from sqlalchemy import text

import pandas as pd

from .auth_helpers import token_required

from ..db import SessionLocal

from .config_helpers import load_training_stage_context

pipeline_bp = Blueprint("pipeline", __name__)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")

def _cfg(key, cast=str):

    """Read a required setting from app.config or the environment."""

    value = current_app.config.get(key, os.environ.get(key))

    if value is None or str(value).strip() == "":

        raise RuntimeError(

            f"Missing required configuration '{key}'. "

            f"Set it in app.config or as an environment variable."

        )

    return cast(value)

def _schema():

    """Return the configured schema, validated since it is interpolated into SQL."""

    schema = _cfg("DB_SCHEMA")

    if not _IDENTIFIER_RE.match(schema):

        raise RuntimeError(f"Invalid DB_SCHEMA value: {schema!r}")

    return schema

def T(table_name):

    """Prefix a table with the configured schema."""

    return f'"{_schema()}"."{table_name}"'

def _iso(value):

    return value.isoformat() if hasattr(value, "isoformat") else value

def _load_stage_names(session, stage_ids):

    """

    Look up stage names from Stage_Master for the given stage_ids.

    Returns {stage_id: stage_name}. Raises if any id has no row, so a wrong

    stage id in config fails loudly instead of producing empty stage names.

    """

    ids = sorted(set(stage_ids))

    rows = session.execute(

        text(

            f"""

            SELECT stage_id, stage_name

            FROM {T("Stage_Master")}

            WHERE stage_id = ANY(:ids)

            """

        ),

        {"ids": ids},

    ).fetchall()

    names = {r.stage_id: r.stage_name for r in rows}

    missing = [i for i in ids if i not in names]

    if missing:

        raise RuntimeError(

            f"Stage_Master has no row for stage_id(s) {missing}. "

            f"Check the STAGE_ID_* configuration."

        )

    return names

def _current_employee_id(session, tenant_id):
    """Resolve the authenticated Employee_Master.employee_id for the tenant."""
    user = getattr(request, "current_user", None)
    if isinstance(user, dict):
        user_id_candidates = [user.get(k) for k in ("user_id", "id", "userId")]
        employee_id_candidates = [user.get("employee_id")]
    else:
        user_id_candidates = [getattr(user, k, None) for k in ("user_id", "id", "userId")]
        employee_id_candidates = [getattr(user, "employee_id", None)]

    user_id_candidates += [getattr(request, "user_id", None)]
    employee_id_candidates += [getattr(request, "employee_id", None)]

    for value in employee_id_candidates:
        if value is None or not str(value).strip():
            continue
        try:
            employee_id = int(value)
        except (TypeError, ValueError):
            continue
        row = session.execute(
            text(f"""
                SELECT employee_id
                FROM {T("Employee_Master")}
                WHERE employee_id = :employee_id
                  AND tenant_id = :tenant_id
                LIMIT 1
            """),
            {"employee_id": employee_id, "tenant_id": tenant_id},
        ).fetchone()
        if row:
            return int(row.employee_id)

    for value in user_id_candidates:
        if value is None or not str(value).strip():
            continue
        try:
            user_id = int(value)
        except (TypeError, ValueError):
            continue
        row = session.execute(
            text(f"""
                SELECT em.employee_id
                FROM {T("User_Master")} um
                JOIN {T("Employee_Master")} em
                  ON em.employee_id = um.employee_id
                WHERE um.user_id = :user_id
                  AND em.tenant_id = :tenant_id
                LIMIT 1
            """),
            {"user_id": user_id, "tenant_id": tenant_id},
        ).fetchone()
        if row:
            return int(row.employee_id)

    raise RuntimeError(
        "Authenticated user is not linked to a valid Employee_Master record for this tenant."
    )


def _current_user_id():
    """Resolve the authenticated user's employee ID."""
    user = getattr(request, "current_user", None)

    if isinstance(user, dict):
        for key in ("employee_id", "user_id", "id", "userId"):
            value = user.get(key)
            if value is not None:
                return int(value)

    for attr in ("employee_id", "user_id", "id"):
        value = getattr(user, attr, None)
        if value is not None:
            return int(value)

    raise RuntimeError(
        "Authenticated employee ID is required to create records."
    )


def _clean_value(value):

    """Convert spreadsheet NaN/empty values to None."""

    if value is None:

        return None

    try:

        if pd.isna(value):

            return None

    except Exception:

        pass

    if isinstance(value, str):

        value = value.strip()

        return value or None

    return value

def _first(data, *keys):

    for key in keys:

        value = _clean_value(data.get(key))

        if value is not None:

            return value

    return None

def _build_lead_misc(data, company_name, website, vendor_registration_number,

                     gst_number, address, city, state, post_code, notes,

                     stage_id):

    """

    Store lead/import fields in Opportunity_Details.Misc_Col1.

    Misc_Col1 is JSON text in the supplied schema, so this keeps the complete

    lead payload available without inventing columns that do not exist in

    Opportunity_Details.

    """

    raw_misc = _first(data, "Misc_Col1", "misc_col1")

    if isinstance(raw_misc, str):

        try:

            misc = json.loads(raw_misc)

            if not isinstance(misc, dict):

                misc = {}

        except Exception:

            misc = {}

    elif isinstance(raw_misc, dict):

        misc = dict(raw_misc)

    else:

        misc = {}

    misc.update({

        "sales_stage_id": stage_id,

        "company_name": company_name,

        "company_website": website,

        "vendor_registration_number": vendor_registration_number,

        "gst_number": gst_number,

        "address": address,

        "city": city,

        "state": state,

        "post_code": post_code,

        "notes": notes,

    })

    # Preserve any additional import columns as well.

    for key, value in data.items():

        if key in {

            "client_id", "company_name", "business_name", "client_company_name",

            "company_website", "vendor_registration_number", "gst_number",

            "address", "city", "state", "post_code", "postcode", "notes",

            "Misc_Col1", "misc_col1"

        }:

            continue

        value = _clean_value(value)

        if value is not None:

            misc[key] = value

    return json.dumps(misc, default=str)

def _insert_opportunity_record(session, tenant_id, data, default_stage_id):

    """

    Create/find Client_Master and then create its Opportunity_Details row.

    The operation is performed in the caller's transaction. Therefore a lead

    or imported row cannot leave an orphan Client_Master if the opportunity

    insert fails.

    """

    data = {str(k).strip(): _clean_value(v) for k, v in (data or {}).items()}

    company_name = _first(

        data, "company_name", "business_name", "client_company_name",

        "Company Name", "Company"

    )

    if not company_name:

        raise ValueError("company_name is required")

    website = _first(

        data, "company_website", "client_website", "website", "Website"

    )

    vendor_registration_number = _first(

        data, "vendor_registration_number", "company_number",

        "registration_number", "Registration Number"

    )

    gst_number = _first(data, "gst_number", "gst", "GST Number")

    address = _first(data, "address", "Address")

    city = _first(data, "city", "City")

    state = _first(data, "state", "State")

    post_code = _first(
        data, "post_code", "postcode", "pin_code", "postal_code", "Post Code"
    )

    if post_code is not None:
        post_code = str(post_code)

    notes = _first(data, "notes", "Notes")

    phone = _first(

        data, "client_phone", "client_mobile", "mobile_no",

        "tel_number", "phone", "Phone", "Mobile"

    )

    email = _first(data, "client_email", "email", "Email")

    supplied_client_id = _first(data, "client_id")

    client_id = int(supplied_client_id) if supplied_client_id is not None else None

    if client_id is not None:

        client_row = session.execute(

            text(

                f"""

                SELECT client_id

                FROM {T("Client_Master")}

                WHERE client_id = :client_id

                  AND tenant_id = :tenant_id

                LIMIT 1

                """

            ),

            {"client_id": client_id, "tenant_id": tenant_id},

        ).fetchone()

        if not client_row:

            raise ValueError(

                f"Client_Master client_id {client_id} does not belong to this tenant"

            )

    else:

        # Reuse an existing company for this tenant when possible.

        client_row = session.execute(

            text(

                f"""

                SELECT client_id

                FROM {T("Client_Master")}

                WHERE tenant_id = :tenant_id

                  AND LOWER(TRIM(client_company_name)) = LOWER(TRIM(:company_name))

                ORDER BY client_id

                LIMIT 1

                """

            ),

            {"tenant_id": tenant_id, "company_name": company_name},

        ).fetchone()

        if client_row:

            client_id = client_row.client_id

        else:

            active_id = _cfg("ACTIVE_STATUS_ID", int)

            cat_id = _cfg("COMMERCIAL_CATEGORY_ID", int)

            created_by_user_id = _current_employee_id(session, tenant_id)

            client_row = session.execute(

                text(

                    f"""

                    INSERT INTO {T("Client_Master")} (

                        tenant_id,

                        client_company_name,

                        client_phone,

                        client_email,

                        client_website,

                        company_number,

                        address,

                        post_code,

                        status_id,

                        "Client_Category_Master_ID",

                        created_by_user_id,

                        created_at

                    )

                    VALUES (

                        :tenant_id,

                        :company_name,

                        :phone,

                        :email,

                        :website,

                        :company_number,

                        :address,

                        :post_code,

                        :status_id,

                        :cat_id,

                        :created_by_user_id,

                        NOW()

                    )

                    RETURNING client_id

                    """

                ),

                {

                    "tenant_id": tenant_id,

                    "company_name": company_name,

                    "phone": phone,

                    "email": email,

                    "website": website,

                    "company_number": vendor_registration_number,

                    "address": address,

                    "post_code": post_code,

                    "status_id": active_id,

                    "cat_id": cat_id,

                    "created_by_user_id": created_by_user_id,

                },

            ).fetchone()

            client_id = client_row.client_id

    # Keep Client_Master's basic contact/company data current when the client

    # already exists, without touching company_routes.py.

    session.execute(

        text(

            f"""

            UPDATE {T("Client_Master")}

            SET

                client_phone = COALESCE(:phone, client_phone),

                client_email = COALESCE(:email, client_email),

                client_website = COALESCE(:website, client_website),

                company_number = COALESCE(:company_number, company_number),

                address = COALESCE(:address, address),

                post_code = COALESCE(:post_code, post_code)

            WHERE client_id = :client_id

              AND tenant_id = :tenant_id

            """

        ),

        {

            "client_id": client_id,

            "tenant_id": tenant_id,

            "phone": phone,

            "email": email,

            "website": website,

            "company_number": vendor_registration_number,

            "address": address,

            "post_code": post_code,

        },

    )

    stage_id = _first(data, "stage_id")

    stage_id = int(stage_id) if stage_id is not None else int(default_stage_id)

    opportunity_title = _first(

        data, "opportunity_title", "Opportunity Title", "title"

    ) or f"Lead - {company_name}"

    opportunity_description = _first(

        data, "opportunity_description", "description", "Description"

    )

    opportunity_owner_employee_id = _current_user_id()

    opportunity_value = _first(data, "opportunity_value")

    currency_id = _first(data, "currency_id")

    mobile_no = _first(data, "mobile_no", "mobile", "Mobile")

    misc_col1 = _build_lead_misc(

        data=data,

        company_name=company_name,

        website=website,

        vendor_registration_number=vendor_registration_number,

        gst_number=gst_number,

        address=address,

        city=city,

        state=state,

        post_code=post_code,

        notes=notes,

        stage_id=stage_id,

    )

    # Only columns confirmed in the supplied Opportunity_Details schema are

    # used here. opportunity_date is always populated with today's date.

    opp_res = session.execute(

        text(

            f"""

            INSERT INTO {T("Opportunity_Details")} (

                client_id,

                opportunity_title,

                opportunity_description,

                opportunity_date,

                opportunity_owner_employee_id,

                stage_id,

                opportunity_value,

                currency_id,

                tenant_id,

                mobile_no,

                notes,

                "Misc_Col1",

                created_at

            )

            VALUES (

                :client_id,

                :opportunity_title,

                :opportunity_description,

                CURRENT_DATE,

                :opportunity_owner_employee_id,

                :stage_id,

                :opportunity_value,

                :currency_id,

                :tenant_id,

                :mobile_no,

                :notes,

                :misc_col1,

                NOW()

            )

            RETURNING opportunity_id

            """

        ),

        {

            "client_id": client_id,

            "opportunity_title": opportunity_title,

            "opportunity_description": opportunity_description,

            "opportunity_owner_employee_id": opportunity_owner_employee_id,

            "stage_id": stage_id,

            "opportunity_value": opportunity_value,

            "currency_id": currency_id,

            "tenant_id": tenant_id,

            "mobile_no": mobile_no,

            "notes": notes,

            "misc_col1": misc_col1,

        },

    )

    opportunity_id = opp_res.fetchone().opportunity_id

    return opportunity_id, client_id

@pipeline_bp.route("/pipeline/sales", methods=["GET", "OPTIONS"])

@token_required

def get_sales_pipeline():

    """

    Return one current Sales Pipeline card per client.

    The latest Opportunity_Details row for each client determines the current

    stage/bucket. Existing historical opportunity rows are not modified.

    """

    if request.method == "OPTIONS":

        return jsonify({}), 200

    session = SessionLocal()

    try:

        stage_id_lead = _cfg("STAGE_ID_LEAD", int)

        stage_label_enquiry = _cfg("STAGE_LABEL_ENQUIRY")

        misc_key_sales_stage = _cfg("MISC_KEY_SALES_STAGE")

        tenant_id = request.current_user.tenant_id

        query = text(

            f"""

            WITH LatestSalesOpportunity AS (

                SELECT DISTINCT ON (od.client_id)

                    od.client_id,

                    od.opportunity_id,

                    od.opportunity_title,

                    od.opportunity_description,

                    od.opportunity_date,

                    od.opportunity_value,

                    od.currency_id,

                    od.mobile_no,

                    od.notes,

                    od.created_at AS opportunity_created_at,

                    od.stage_id,

                    od."Misc_Col1" AS misc_col1,

                    sm.stage_name

                FROM {T("Opportunity_Details")} od

                JOIN {T("Client_Master")} cm_scope

                    ON cm_scope.client_id = od.client_id

                JOIN {T("Stage_Master")} sm

                    ON sm.stage_id = od.stage_id

                WHERE sm.stage_type = :stage_type

                  AND cm_scope.tenant_id = :tenant_id

                  AND cm_scope."Client_Category_Master_ID" = :cat_id

                  AND cm_scope.status_id = :active_id

                ORDER BY od.client_id, od.created_at DESC, od.opportunity_id DESC

            )

            SELECT

                cm.client_id,

                cm.client_company_name,

                cm.address,

                cm.post_code,

                cm.client_phone,

                cm.client_email,

                cm.client_website,

                cm.company_number,

                cm.created_at AS client_created_at,

                lso.opportunity_id,

                lso.opportunity_title,

                lso.opportunity_description,

                lso.opportunity_date,

                lso.opportunity_value,

                lso.currency_id,

                lso.mobile_no,

                lso.notes,

                lso.opportunity_created_at,

                lso.stage_id,

                lso.stage_name,

                lso.misc_col1

            FROM {T("Client_Master")} cm

            JOIN LatestSalesOpportunity lso

                ON lso.client_id = cm.client_id

            WHERE cm.tenant_id = :tenant_id

              AND cm."Client_Category_Master_ID" = :cat_id

              AND cm.status_id = :active_id

            ORDER BY cm.client_company_name ASC

            """

        )

        results = session.execute(

            query,

            {

                "tenant_id": tenant_id,

                "stage_type": _cfg("STAGE_TYPE_SALES", int),

                "cat_id": _cfg("COMMERCIAL_CATEGORY_ID", int),

                "active_id": _cfg("ACTIVE_STATUS_ID", int),

            },

        ).fetchall()

        pipeline_items = []

        for row in results:

            misc = {}

            if row.misc_col1:

                try:

                    misc = json.loads(row.misc_col1)

                    if not isinstance(misc, dict):

                        misc = {}

                except Exception:

                    misc = {}

            stage = misc.get(misc_key_sales_stage) or (

                stage_label_enquiry

                if row.stage_id == stage_id_lead

                else row.stage_name

            )

            # The frontend identifies/moves a company by client_id, so expose

            # both company_id and client_id.

            pipeline_items.append(

                {

                    "id": f"company-{row.client_id}",

                    "type": "sales",

                    "company_id": row.client_id,

                    "client_id": row.client_id,

                    "opportunity_id": row.opportunity_id,

                    "company_name": row.client_company_name,

                    "address": row.address,

                    "post_code": row.post_code,

                    "phone": row.client_phone,

                    "email": row.client_email,

                    "website": row.client_website,

                    "company_number": row.company_number,

                    "created_at": _iso(row.opportunity_created_at),

                    "client_created_at": _iso(row.client_created_at),

                    "opportunity_title": row.opportunity_title,

                    "opportunity_description": row.opportunity_description,

                    "opportunity_date": _iso(row.opportunity_date),

                    "opportunity_value": row.opportunity_value,

                    "currency_id": row.currency_id,

                    "mobile_no": row.mobile_no,

                    "notes": row.notes,

                    "stage_id": row.stage_id,

                    "stage_name": row.stage_name,

                    "stage": stage,

                    "misc": misc,

                    "pipeline_type": "sales",

                }

            )

        return jsonify(pipeline_items), 200

    except Exception as e:

        current_app.logger.exception(

            f"Error fetching sales pipeline: {e}"

        )

        return jsonify(

            {

                "error": "Failed to fetch sales pipeline",

                "details": str(e),

            }

        ), 500

    finally:

        session.close()

@pipeline_bp.route("/pipeline/sales/lead", methods=["POST", "OPTIONS"])

@token_required

def create_sales_lead():

    """

    Create a Lead by creating/finding Client_Master and then inserting

    Opportunity_Details linked by client_id.

    """

    if request.method == "OPTIONS":

        return jsonify({}), 200

    session = SessionLocal()

    try:

        data = request.get_json(silent=True) or {}

        tenant_id = request.current_user.tenant_id

        stage_id_lead = _cfg("STAGE_ID_LEAD", int)

        opportunity_id, client_id = _insert_opportunity_record(

            session=session,

            tenant_id=tenant_id,

            data=data,

            default_stage_id=stage_id_lead,

        )

        session.commit()

        return jsonify(

            {

                "message": "Lead created successfully",

                "opportunity_id": opportunity_id,

                "client_id": client_id,

                "company_id": client_id,

                "company_name": _first(

                    data, "company_name", "business_name", "client_company_name"

                ),

            }

        ), 201

    except Exception as e:

        session.rollback()

        current_app.logger.exception(f"Error creating sales lead: {e}")

        return jsonify(

            {

                "error": "Failed to create sales lead",

                "details": str(e),

            }

        ), 500

    finally:

        session.close()

@pipeline_bp.route("/pipeline/sales/leads/import", methods=["POST", "OPTIONS"])

@token_required

def import_sales_leads():

    """

    Bulk import leads from Excel or a JSON array.

    Each row follows the same Client_Master -> Opportunity_Details flow as

    manual Lead creation.

    """

    if request.method == "OPTIONS":

        return jsonify({}), 200

    session = SessionLocal()

    try:

        tenant_id = request.current_user.tenant_id

        stage_id_lead = _cfg("STAGE_ID_LEAD", int)

        records_to_import = []

        if "file" in request.files:

            file = request.files["file"]

            if not file or not file.filename:

                return jsonify({"error": "No import file provided"}), 400

            filename = file.filename.lower()

            if not filename.endswith((".xlsx", ".xls")):

                return jsonify(

                    {"error": "Only .xlsx and .xls files are supported"}

                ), 400

            file_bytes = file.read()

            if not file_bytes:

                return jsonify({"error": "Import file is empty"}), 400

            df = pd.read_excel(io.BytesIO(file_bytes))

            df = df.where(pd.notnull(df), None)

            records_to_import = df.to_dict(orient="records")

        else:

            payload = request.get_json(silent=True) or {}

            if isinstance(payload, list):

                records_to_import = payload

            else:

                records_to_import = payload.get("leads", [])

        if not records_to_import:

            return jsonify({"error": "No lead data provided for import"}), 400

        created_records = []

        for record in records_to_import:

            if not isinstance(record, dict):

                raise ValueError("Each imported lead must be an object/row")

            opportunity_id, client_id = _insert_opportunity_record(

                session=session,

                tenant_id=tenant_id,

                data=record,

                default_stage_id=stage_id_lead,

            )

            created_records.append(

                {

                    "opportunity_id": opportunity_id,

                    "client_id": client_id,

                    "company_id": client_id,

                }

            )

        session.commit()

        return jsonify(

            {

                "message": f"Successfully imported {len(created_records)} lead(s)",

                "imported_count": len(created_records),

                "records": created_records,

                "opportunity_ids": [

                    item["opportunity_id"] for item in created_records

                ],

            }

        ), 201

    except Exception as e:

        session.rollback()

        current_app.logger.exception(f"Error importing sales leads: {e}")

        return jsonify(

            {

                "error": "Failed to import sales leads",

                "details": str(e),

            }

        ), 500

    finally:

        session.close()

@pipeline_bp.route("/pipeline/sales/<int:client_id>/stage", methods=["PATCH", "OPTIONS"])

@token_required

def update_sales_pipeline_stage(client_id):

    """Update the latest Sales Opportunity stage for a client."""

    if request.method == "OPTIONS":

        return jsonify({}), 200

    session = SessionLocal()

    try:

        tenant_id = request.current_user.tenant_id

        payload = request.get_json(silent=True) or {}

        requested_stage = payload.get("stage")

        requested_stage_id = payload.get("stage_id")

        if requested_stage_id is not None:

            try:

                stage_id = int(requested_stage_id)

            except (TypeError, ValueError):

                return jsonify({"error": "stage_id must be an integer"}), 400

        else:

            stage_text = str(requested_stage or "").strip()

            if not stage_text:

                return jsonify({"error": "stage or stage_id is required"}), 400

            # The UI calls the Lead stage "Enquiry".

            if stage_text.lower() in {"lead", "enquiry", "inquiry"}:

                stage_id = _cfg("STAGE_ID_LEAD", int)

            else:

                stage_row = session.execute(

                    text(

                        f"""

                        SELECT stage_id

                        FROM {T("Stage_Master")}

                        WHERE stage_type = :stage_type

                          AND LOWER(stage_name) = LOWER(:stage_name)

                        LIMIT 1

                        """

                    ),

                    {

                        "stage_type": _cfg("STAGE_TYPE_SALES", int),

                        "stage_name": stage_text,

                    },

                ).fetchone()

                if not stage_row:

                    return jsonify({"error": f"Sales stage '{stage_text}' was not found"}), 400

                stage_id = int(stage_row.stage_id)

        # Validate that the target stage belongs to the Sales stage type.

        valid_stage = session.execute(

            text(

                f"""

                SELECT stage_id, stage_name

                FROM {T("Stage_Master")}

                WHERE stage_id = :stage_id

                  AND stage_type = :stage_type

                LIMIT 1

                """

            ),

            {"stage_id": stage_id, "stage_type": _cfg("STAGE_TYPE_SALES", int)},

        ).fetchone()

        if not valid_stage:

            return jsonify({"error": "Invalid Sales stage"}), 400

        latest = session.execute(

            text(

                f"""

                SELECT od.opportunity_id

                FROM {T("Opportunity_Details")} od

                JOIN {T("Client_Master")} cm ON cm.client_id = od.client_id

                JOIN {T("Stage_Master")} sm ON sm.stage_id = od.stage_id

                WHERE od.client_id = :client_id

                  AND cm.tenant_id = :tenant_id

                  AND sm.stage_type = :stage_type

                ORDER BY od.created_at DESC, od.opportunity_id DESC

                LIMIT 1

                """

            ),

            {

                "client_id": client_id,

                "tenant_id": tenant_id,

                "stage_type": _cfg("STAGE_TYPE_SALES", int),

            },

        ).fetchone()

        if not latest:

            return jsonify({"error": "No Sales Opportunity exists for this client"}), 404

        session.execute(

            text(

                f"""

                UPDATE {T("Opportunity_Details")}

                SET stage_id = :stage_id

                WHERE opportunity_id = :opportunity_id

                """

            ),

            {"stage_id": stage_id, "opportunity_id": latest.opportunity_id},

        )

        session.commit()

        return jsonify({

            "message": "Sales stage updated successfully",

            "client_id": client_id,

            "opportunity_id": latest.opportunity_id,

            "stage_id": stage_id,

            "stage_name": valid_stage.stage_name,

        }), 200

    except Exception as e:

        session.rollback()

        current_app.logger.exception(f"Error updating Sales stage: {e}")

        return jsonify({"error": "Failed to update sales stage", "details": str(e)}), 500

    finally:

        session.close()

@pipeline_bp.route("/pipeline/training/stages", methods=["GET", "OPTIONS"])

@token_required

def get_training_stages():

    """

    Training stages for the board, in board order, read from Stage_Master.

    Each item:

      stage_id     Stage_Master id

      name         stage name shown as the column title

      requires_po  true when a PO copy must be uploaded before a batch can

                   be in this stage

      is_awaiting  true for the derived "awaiting scheduling" column (its

                   cards have no batch yet)

    """

    if request.method == "OPTIONS":

        return jsonify({}), 200

    session = SessionLocal()

    try:

        stages = load_training_stage_context(session)

        return jsonify(

            [

                {

                    "stage_id": s["stage_id"],

                    "name": s["stage_name"],

                    "requires_po": s["stage_name"] in stages.po_required,

                    "is_awaiting": s["stage_name"] == stages.awaiting,

                }

                for s in stages.ordered

            ]

        ), 200

    except Exception as e:

        current_app.logger.exception(

            f"Error fetching training stages: {e}"

        )

        return jsonify(

            {

                "error": "Failed to fetch training stages",

                "details": str(e),

            }

        ), 500

    finally:

        session.close()

@pipeline_bp.route("/pipeline/training", methods=["GET", "OPTIONS"])

@token_required

def get_training_pipeline():

    """

    Return training pipeline records from Services_Master.

    Services_Master is the source of truth for training batches.

    Client_Master is used to resolve the company name.

    service_id is exposed as training_id for frontend compatibility.

    stage comes directly from Services_Master.stage.

    client_id is exposed as company_id for the existing frontend.

    Awaiting Scheduling cards are appended first; they have

    training_id == None.

    """

    if request.method == "OPTIONS":

        return jsonify({}), 200

    session = SessionLocal()

    try:

        tenant_id = request.current_user.tenant_id

        stage_id_converted = _cfg("STAGE_ID_CONVERTED", int)

        stage_id_awaiting = _cfg("STAGE_ID_AWAITING_SCHEDULING", int)

        stage_id_default = _cfg("STAGE_ID_TRAINING_DEFAULT", int)

        misc_key_converted_at = _cfg("MISC_KEY_CONVERTED_AT")

        stage_names = _load_stage_names(

            session, [stage_id_awaiting, stage_id_default]

        )

        stage_awaiting = stage_names[stage_id_awaiting]

        stage_default = stage_names[stage_id_default]

        query = text(

            f"""

            SELECT

                sm.service_id,

                sm.tenant_id,

                sm.service_code,

                sm.service_title,

                sm.service_description,

                sm.service_rate,

                sm.currency_id,

                sm.supplier_id,

                sm.date_from,

                sm.date_to,

                sm.created_at,

                sm.client_id,

                cm.client_company_name,

                sm.event_number,

                sm.trainer_name,

                sm.client_address,

                sm.city,

                sm.state,

                sm.pin_code,

                sm.remarks,

                sm.participants,

                sm.stage,

                sm.updated_at,

                sm.duration,

                sm.po_file_url,

                sm.po_file_name,

                sm.po_received_at

            FROM {T("Services_Master")} sm

            LEFT JOIN {T("Client_Master")} cm

                ON cm.client_id = sm.client_id

               AND cm.tenant_id = sm.tenant_id

            WHERE sm.tenant_id = :tenant_id

            AND COALESCE(sm.stage, '') <> :stage_awaiting

            ORDER BY sm.service_id DESC

            """

        )

        results = session.execute(

            query,

            {

                "tenant_id": tenant_id,

                "stage_awaiting": stage_awaiting,

            },

        ).fetchall()

        pipeline_items = []

        for row in results:

            participants = row.participants

            if participants is None:

                participants = []

            elif isinstance(participants, str):

                try:

                    participants = json.loads(participants)

                except Exception:

                    participants = []

            stage = row.stage or stage_default

            pipeline_items.append(

                {

                    "id": f"training-{row.service_id}",

                    "type": "training",

                    "training": {

                        "training_id": row.service_id,

                        "service_id": row.service_id,

                        # Company/client relationship

                        "company_id": row.client_id,

                        "client_id": row.client_id,

                        "company_name": row.client_company_name,

                        # Service/course information

                        "service_code": row.service_code,

                        "training_name": row.service_title,

                        "service_title": row.service_title,

                        "service_description": row.service_description,

                        "training_fees": row.service_rate,

                        "service_rate": row.service_rate,

                        "currency_id": row.currency_id,

                        "supplier_id": row.supplier_id,

                        # Training information

                        "training_from": _iso(row.date_from),

                        "training_to": _iso(row.date_to),

                        "event_number": row.event_number,

                        "trainer_name": row.trainer_name,

                        "duration": row.duration,

                        # Location

                        "client_address": row.client_address,

                        "city": row.city,

                        "state": row.state,

                        "pin_code": row.pin_code,

                        # Other training data

                        "remarks": row.remarks,

                        "participants": participants,

                        # Current pipeline stage

                        "stage": stage,

                        # PO copy (required before PO Received and later stages)

                        "po_file_url": row.po_file_url,

                        "po_file_name": row.po_file_name,

                        "po_received_at": _iso(row.po_received_at),

                        "created_at": _iso(row.created_at),

                        "updated_at": _iso(row.updated_at),

                    },

                    "stage": stage,

                    "pipeline_type": "training",

                }

            )

        # ── Awaiting Scheduling (derived cards, no batch row) ────────────

        # A company is awaiting when its latest sales stage is Converted and

        # it has no batch created after its last Converted move

        # (Misc_Col1 converted-at value; missing value = converted long ago,

        # i.e. the epoch via to_timestamp(0)).

        awaiting_rows = session.execute(

            text(

                f"""

                SELECT cm.client_id, cm.client_company_name

                FROM {T("Client_Master")} cm

                JOIN LATERAL (

                    SELECT sm.stage_id,

                           (od."Misc_Col1"::jsonb ->> :converted_at_key)::timestamptz AS converted_at

                    FROM {T("Opportunity_Details")} od

                    JOIN {T("Stage_Master")} sm ON sm.stage_id = od.stage_id

                    WHERE od.client_id = cm.client_id

                      AND sm.stage_type = :stage_type

                    ORDER BY od.created_at DESC

                    LIMIT 1

                ) so ON true

                WHERE cm.tenant_id = :tenant_id

                  AND cm."Client_Category_Master_ID" = :cat_id

                  AND cm.status_id = :active_id

                  AND so.stage_id = :stage_id_converted

                  AND NOT EXISTS (

                      SELECT 1 FROM {T("Services_Master")} s

                      WHERE s.client_id = cm.client_id

                        AND s.tenant_id = cm.tenant_id

                        AND s.created_at > COALESCE(so.converted_at, to_timestamp(0))

                  )

                ORDER BY cm.client_company_name ASC

                """

            ),

            {

                "tenant_id": tenant_id,

                "stage_type": _cfg("STAGE_TYPE_SALES", int),

                "cat_id": _cfg("COMMERCIAL_CATEGORY_ID", int),

                "active_id": _cfg("ACTIVE_STATUS_ID", int),

                "stage_id_converted": stage_id_converted,

                "converted_at_key": misc_key_converted_at,

            },

        ).fetchall()

        awaiting_items = [

            {

                "id": f"company-{r.client_id}",

                "type": "training",

                "training": {

                    "training_id": None,

                    "service_id": None,

                    "company_id": r.client_id,

                    "client_id": r.client_id,

                    "company_name": r.client_company_name,

                    "participants": [],

                    "stage": stage_awaiting,

                },

                "stage": stage_awaiting,

                "pipeline_type": "training",

            }

            for r in awaiting_rows

        ]

        pipeline_items = awaiting_items + pipeline_items

        return jsonify(pipeline_items), 200

    except Exception as e:

        current_app.logger.exception(

            f"Error fetching training pipeline from Services_Master: {e}"

        )

        return jsonify(

            {

                "error": "Failed to fetch training pipeline",

                "details": str(e),

            }

        ), 500

    finally:

        session.close()