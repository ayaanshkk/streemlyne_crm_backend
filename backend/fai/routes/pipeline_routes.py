"""



Pipeline Routes for StreemLyne CRM.



Provides Kanban board data for Sales and Training pipelines.



Training pipeline:



- Uses Services_Master as the source of training/course records.



*\-* Services_Master is tenant-scoped.



*\-* Training-specific fields are read from Services_Master.



*\-* Client_Master is used only to resolve the company name.



*\-* "Awaiting Scheduling" cards are derived (no batch row): a company whose



  lead is at Sales stage 6 (Won) and which has no batch created after its



  won_at time.



Stage names



*\-*----------



Training stages are loaded from Tenant_Pipeline_Stage_Mapping for the



current tenant, with Pipeline_Stage_Master (stage_type = 2) as fallback.



Configuration



*\-*------------



Nothing environment-specific is hardcoded here. Every value below is read at



request time from Flask's app.config, falling back to an environment variable



of the same name. A missing value raises a RuntimeError (fail fast) instead of



silently using a default.



    DB_SCHEMA                    Postgres schema holding the CRM tables



    STAGE_TYPE_SALES             Stage_Master.stage_type value for sales stages



    COMMERCIAL_CATEGORY_ID        "Client_Category_Master_ID" for commercial clients



    ACTIVE_STATUS_ID              status_id meaning "active"



    STAGE_ID_LEAD                Stage_Master.stage_id of the Lead stage



    Sales stage 6                 Won stage id used to derive training items



    STAGE_ID_AWAITING_SCHEDULING Pipeline_Stage_Master.stage_id of the



                                 awaiting-scheduling stage



    STAGE_ID_TRAINING_DEFAULT    Pipeline_Stage_Master.stage_id used when a



                                 Services_Master row has no stage



    STAGE_ID_PO_RECEIVED         Pipeline_Stage_Master.stage_id where PO is



                                 first required



    STAGE_LABEL_ENQUIRY          Display label shown instead of the Lead stage



                                 name (not stored in Stage_Master)



    MISC_KEY_SALES_STAGE          Key inside Opportunity_Details.Misc_Col1 JSON



                                 holding the sales stage



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



            FROM {T("Pipeline_Stage_Master")}



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



def _insert_lead_record(session, tenant_id, data, default_stage_id):



    """



    Create/find Client_Master and insert the lead into Lead_Master.



    The operation is performed in the caller's transaction. Therefore a lead



    or imported row cannot leave an orphan Client_Master if the Lead_Master



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

    # Postal codes are identifiers, not numbers: preserve leading zeroes and

    # keep the value compatible with Client_Master.post_code (varchar/text).

    if post_code is not None:

        post_code = str(post_code).strip() or None



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



                post_code = COALESCE(CAST(:post_code AS varchar), post_code)



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



    valid_stage = session.execute(

        text(f"""

            SELECT stage_id

            FROM {T("Pipeline_Stage_Master")}

            WHERE stage_id = :stage_id

              AND stage_type = :stage_type

            LIMIT 1

        """),

        {

            "stage_id": stage_id,

            "stage_type": _cfg("STAGE_TYPE_SALES", int),

        },

    ).fetchone()

    if not valid_stage:

        raise ValueError(f"Invalid Sales stage_id: {stage_id}")



    # Lead Title is derived from the company name; it is not a separate form field.

    lead_title = company_name

    lead_description = _first(

        data, "lead_description", "opportunity_description",

        "description", "Description", "notes", "Notes"

    ) or f"Lead for {company_name}"

    lead_date = _first(data, "lead_date", "opportunity_date", "date") or None



    expected_value = _first(data, "expected_value", "opportunity_value", "value")

    if expected_value is not None:

        try:

            expected_value = int(float(expected_value))

        except (TypeError, ValueError):

            raise ValueError("expected_value must be an integer")



    currency_id = _first(data, "currency_id")

    assigned_employee_id = _first(data, "assigned_employee_id")

    qualification_status = _first(

        data, "qualification status", "qualification_status", "qualification_status_id"

    )

    priority = _first(data, "priority")

    expected_decision_date = _first(

        data, "expected_decision_date", "expected_decision_date ", "decision_date"

    )

    last_contacted_date = _first(data, "last_contacted_date")

    next_followup_date = _first(data, "next_followup_date")

    lead_source = _first(data, "lead_source", "source", "Lead Source")



    # The provided schema does not define an identity/sequence default for lead_id.

    # Lock the table while generating the next ID so concurrent inserts do not

    # receive the same MAX(lead_id) + 1 value.

    session.execute(text(f'LOCK TABLE {T("Lead_Master")} IN EXCLUSIVE MODE'))

    next_id_row = session.execute(

        text(f'SELECT COALESCE(MAX(lead_id), 0) + 1 AS next_lead_id FROM {T("Lead_Master")}')

    ).fetchone()

    lead_id = int(next_id_row.next_lead_id)





    # created_by references User_Master.user_id, NOT Employee_Master.employee_id.

    created_by = None



    current_user = getattr(request, "current_user", None)



    if isinstance(current_user, dict):

        user_id_candidates = [

            current_user.get(key)

            for key in ("user_id", "id", "userId")

        ]

    else:

        user_id_candidates = [

            getattr(current_user, key, None)

            for key in ("user_id", "id", "userId")

        ]



    user_id_candidates.append(getattr(request, "user_id", None))



    for candidate in user_id_candidates:

        if candidate is None or not str(candidate).strip():

            continue



        try:

            user_id = int(candidate)

        except (TypeError, ValueError):

            continue



        user_row = session.execute(

            text(f"""

                SELECT um.user_id

                FROM {T("User_Master")} um

                JOIN {T("Employee_Master")} em

                  ON em.employee_id = um.employee_id

                WHERE um.user_id = :user_id

                  AND em.tenant_id = :tenant_id

                LIMIT 1

            """),

            {

                "user_id": user_id,

                "tenant_id": tenant_id,

            },

        ).fetchone()



        if user_row:

            created_by = int(user_row.user_id)

            break





    lead_row = session.execute(

        text(f"""

            INSERT INTO {T("Lead_Master")} (

                lead_id,

                tenant_id,

                "client_ID",

                assigned_employee_id,

                stage_id,

                lead_title,

                lead_description,

                lead_date,

                expected_value,

                currency_id,

                lead_source,

                "qualification status",

                priority,

                "expected_decision_date ",

                last_contacted_date,

                next_followup_date,

                created_by,

                created_date

            )

            VALUES (

                :lead_id,

                :tenant_id,

                :client_id,

                :assigned_employee_id,

                :stage_id,

                :lead_title,

                :lead_description,

                COALESCE(CAST(:lead_date AS date), CURRENT_DATE),

                :expected_value,

                :currency_id,

                :lead_source,

                :qualification_status,

                :priority,

                CAST(:expected_decision_date AS date),

                CAST(:last_contacted_date AS date),

                CAST(:next_followup_date AS date),

                :created_by,

                CURRENT_DATE

            )

            RETURNING lead_id

        """),

        {

            "lead_id": lead_id,

            "tenant_id": tenant_id,

            "client_id": client_id,

            "assigned_employee_id": assigned_employee_id,

            "stage_id": stage_id,

            "lead_title": str(lead_title)[:500],

            "lead_description": str(lead_description)[:5000],

            "lead_date": lead_date,

            "expected_value": expected_value,

            "currency_id": currency_id,

            "lead_source": str(lead_source)[:200] if lead_source is not None else None,

            "qualification_status": qualification_status,

            "priority": priority,

            "expected_decision_date": expected_decision_date,

            "last_contacted_date": last_contacted_date,

            "next_followup_date": next_followup_date,

            "created_by": created_by,

        },

    ).fetchone()



    return int(lead_row.lead_id), client_id





@pipeline_bp.route("/pipeline/sales", methods=["GET", "OPTIONS"])

@token_required

def get_sales_pipeline():

    """Return Sales Pipeline cards exclusively from Lead_Master."""

    if request.method == "OPTIONS":

        return jsonify({}), 200



    session = SessionLocal()

    try:

        tenant_id = request.current_user.tenant_id

        stage_id_lead = _cfg("STAGE_ID_LEAD", int)

        stage_label_enquiry = _cfg("STAGE_LABEL_ENQUIRY")



        rows = session.execute(

            text(f"""

                WITH SalesLeads AS (

                    SELECT

                        lm.lead_id,

                        lm.tenant_id,

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

                        lm.created_by,

                        lm.created_date,

                        sm.stage_name

                    FROM {T("Lead_Master")} lm

                    JOIN {T("Pipeline_Stage_Master")} sm

                      ON sm.stage_id = lm.stage_id

                    WHERE lm.tenant_id = :tenant_id

                      AND sm.stage_type = :stage_type

                    ORDER BY lm.created_date DESC NULLS LAST, lm.lead_id DESC

                )

                SELECT

                    ll.*,

                    cm.client_company_name,

                    cm.address,

                    cm.post_code,

                    cm.client_phone,

                    cm.client_email,

                    cm.client_website,

                    cm.company_number,

                    cm.created_at AS client_created_at

                FROM SalesLeads ll

                LEFT JOIN {T("Client_Master")} cm

                  ON cm.client_id = ll.client_id

                 AND cm.tenant_id = ll.tenant_id

                ORDER BY cm.client_company_name ASC NULLS LAST,

                         ll.created_date DESC NULLS LAST, ll.lead_id DESC

            """),

            {

                "tenant_id": tenant_id,

                "stage_type": _cfg("STAGE_TYPE_SALES", int),

            },

        ).fetchall()



        pipeline_items = []

        for row in rows:

            stage = (

                stage_label_enquiry

                if row.stage_id == stage_id_lead

                else row.stage_name

            )

            pipeline_items.append({

                "id": f"lead-{row.lead_id}",

                "type": "sales",

                "lead_id": row.lead_id,

                "company_id": row.client_id,

                "client_id": row.client_id,

                "company_name": row.client_company_name,

                "address": row.address,

                "post_code": row.post_code,

                "phone": row.client_phone,

                "email": row.client_email,

                "website": row.client_website,

                "company_number": row.company_number,

                "created_at": _iso(row.created_date),

                "client_created_at": _iso(row.client_created_at),

                "lead_title": row.lead_title,

                "lead_description": row.lead_description,

                "lead_date": _iso(row.lead_date),

                "expected_value": row.expected_value,

                "currency_id": row.currency_id,

                "lead_source": row.lead_source,

                "assigned_employee_id": row.assigned_employee_id,

                "qualification_status": row.qualification_status,

                "priority": row.priority,

                "expected_decision_date": _iso(row.expected_decision_date),

                "last_contacted_date": _iso(row.last_contacted_date),

                "next_followup_date": _iso(row.next_followup_date),

                "stage_id": row.stage_id,

                "stage_name": row.stage_name,

                "stage": stage,

                "pipeline_type": "sales",

            })



        return jsonify(pipeline_items), 200

    except Exception as e:

        current_app.logger.exception(f"Error fetching Sales Pipeline from Lead_Master: {e}")

        return jsonify({

            "error": "Failed to fetch sales pipeline",

            "details": str(e),

        }), 500

    finally:

        session.close()





@pipeline_bp.route("/pipeline/sales/stages", methods=["GET", "OPTIONS"])

@token_required

def get_sales_stages():

    """Return configured Sales stages from Pipeline_Stage_Master."""

    if request.method == "OPTIONS":

        return jsonify({}), 200



    session = SessionLocal()

    try:

        rows = session.execute(

            text(

                f"""

                SELECT stage_id, stage_name, preceding_stage_id

                FROM {T("Pipeline_Stage_Master")}

                WHERE stage_type = :stage_type

                ORDER BY stage_id

                """

            ),

            {"stage_type": _cfg("STAGE_TYPE_SALES", int)},

        ).fetchall()



        return jsonify([

            {

                "stage_id": row.stage_id,

                "name": row.stage_name,

                "stage_name": row.stage_name,

                "stage_description": None,

                "preceding_stage_id": row.preceding_stage_id,

            }

            for row in rows

        ]), 200

    except Exception as e:

        current_app.logger.exception(f"Error fetching Sales stages: {e}")

        return jsonify({

            "error": "Failed to fetch Sales stages",

            "details": str(e),

        }), 500

    finally:

        session.close()





@pipeline_bp.route("/pipeline/sales/lead", methods=["POST", "OPTIONS"])



@token_required



def create_sales_lead():



    """



    Create a Lead by creating/finding Client_Master and inserting into Lead_Master.



    """



    if request.method == "OPTIONS":



        return jsonify({}), 200



    session = SessionLocal()



    try:



        data = request.get_json(silent=True) or {}



        tenant_id = request.current_user.tenant_id



        stage_id_lead = _cfg("STAGE_ID_LEAD", int)



        lead_id, client_id = _insert_lead_record(



            session=session,



            tenant_id=tenant_id,



            data=data,



            default_stage_id=stage_id_lead,



        )



        session.commit()



        return jsonify(



            {



                "message": "Lead created successfully",



                "lead_id": lead_id,



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



    Each row follows the same Client_Master -> Lead_Master flow as manual Lead creation.



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



            lead_id, client_id = _insert_lead_record(



                session=session,



                tenant_id=tenant_id,



                data=record,



                default_stage_id=stage_id_lead,



            )



            created_records.append(



                {



                    "lead_id": lead_id,



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



                "lead_ids": [item["lead_id"] for item in created_records],



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



def _as_int(value):
    """int(value) or None. Lead_Master."qualification status" can come back as
    an int, a numeric string or a Decimal depending on the column type, and the
    stage rules below compare it with plain integers (0/1/2)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _role_name(role):
    """A role may be a plain string or an object/dict with role_name/name/role
    (the frontend already accepts both)."""
    if isinstance(role, dict):
        return role.get("role_name") or role.get("name") or role.get("role") or ""
    for attr in ("role_name", "name", "role"):
        value = getattr(role, attr, None)
        if value:
            return value
    return role


_QUOTATION_SOURCE = {}
def _qident(name):
    return '"' + str(name).replace('"', '""') + '"'
def _quotation_source(session):
    """Locate the quotation table and its client/tenant columns (cached).
    Order: QUOTATION_TABLE setting, the foreign key on
    Training_Master_New.Quotation_ID, then common table names."""
    if _QUOTATION_SOURCE:
        return _QUOTATION_SOURCE
    schema = _schema()
    table = current_app.config.get("QUOTATION_TABLE", os.environ.get("QUOTATION_TABLE"))
    if not table:
        row = session.execute(
            text("""SELECT c.relname AS tbl
                    FROM pg_constraint k
                    JOIN pg_class c ON c.oid = k.confrelid
                    JOIN pg_attribute s ON s.attrelid = k.conrelid AND s.attnum = k.conkey[1]
                    WHERE k.contype = 'f'
                      AND k.conrelid = CAST(:src AS regclass)
                      AND LOWER(s.attname) = 'quotation_id'
                    LIMIT 1"""),
            {"src": f'"{schema}"."Training_Master_New"'},
        ).fetchone()
        table = row.tbl if row else None
    if not table:
        for guess in ("Quotation_Master", "Quotations", "Quotation"):
            found = session.execute(
                text("SELECT to_regclass(:name) AS oid"),
                {"name": f'"{schema}"."{guess}"'},
            ).fetchone()
            if found and found.oid:
                table = guess
                break
    if not table:
        raise RuntimeError(
            "Quotation table not found. Set QUOTATION_TABLE in app.config or the environment."
        )
    cols = [r.column_name for r in session.execute(
        text("""SELECT column_name FROM information_schema.columns
                WHERE table_schema = :schema AND table_name = :table"""),
        {"schema": schema, "table": table},
    ).fetchall()]
    lowered = {col.lower(): col for col in cols}
    client_col = next((lowered[n] for n in ("client_id", "company_id", "customer_id") if n in lowered), None)
    if not client_col:
        raise RuntimeError(f"Quotation table {table} has no client_id/company_id column")
    _QUOTATION_SOURCE.update({
        "table": table,
        "client_col": client_col,
        "tenant_col": lowered.get("tenant_id"),
    })
    return _QUOTATION_SOURCE
def _client_has_quotation(session, tenant_id, client_id):
    if client_id is None:
        return False
    src = _quotation_source(session)
    sql = f'SELECT 1 FROM {T(src["table"])} WHERE {_qident(src["client_col"])} = :client_id'
    params = {"client_id": client_id}
    if src["tenant_col"]:
        sql += f' AND {_qident(src["tenant_col"])} = :tenant_id'
        params["tenant_id"] = tenant_id
    return session.execute(text(sql + " LIMIT 1"), params).fetchone() is not None
@pipeline_bp.route("/pipeline/sales/<int:lead_id>/stage", methods=["PATCH", "OPTIONS"])
@token_required
def update_sales_pipeline_stage(lead_id):
    """Update a sales lead stage and enforce qualification approval rules."""
    if request.method == "OPTIONS":
        return jsonify({}), 200

    session = SessionLocal()
    try:
        user = request.current_user
        # Auth helpers may expose the authenticated user as either an object or a dict.
        def user_value(*keys, default=None):
            for key in keys:
                value = user.get(key) if isinstance(user, dict) else getattr(user, key, None)
                if value is not None:
                    return value
            return default

        tenant_id = user_value("tenant_id", "tenantId")
        if tenant_id is None:
            return jsonify({"error": "Authenticated user has no tenant context"}), 401

        payload = request.get_json(silent=True) or {}
        action = str(payload.get("action") or "").strip().lower()
        questionnaire_completed = payload.get("questionnaire_completed") is True

        # Keep backend role detection aligned with the frontend's supported user fields.
        admin_values = [user_value("is_admin", "isAdmin", default=False)]
        role_values = [
            user_value("role"),
            user_value("user_role"),
            user_value("role_name"),
            user_value("userRole"),
        ]
        roles = user_value("roles")
        if isinstance(roles, (list, tuple, set)):
            role_values.extend(roles)
        elif roles:
            role_values.append(roles)

        admin_role_names = {
            "admin", "administrator", "super_admin", "super admin",
            "platform admin", "tenant super admin",
        }
        is_admin = any(bool(value) for value in admin_values) or any(
            str(_role_name(role)).strip().lower() in admin_role_names
            for role in role_values if role is not None
        )
        # The authenticated user often carries only role ids (Role_Master:
        # 1 = Tenant Super Admin, 2 = Platform Admin), not role names.
        if not is_admin:
            def _role_ids(value):
                found = []
                if value is None:
                    return found
                items = value if isinstance(value, (list, tuple, set)) else str(value).split(",")
                for item in items:
                    if isinstance(item, dict):
                        item = item.get("role_id", item.get("id"))
                    else:
                        item = getattr(item, "role_id", item)
                    try:
                        found.append(int(str(item).strip()))
                    except (TypeError, ValueError):
                        pass
                return found
            candidate_ids = []
            for value in (user_value("role_id", "roleId"), user_value("role_ids", "roleIds"), roles, *role_values):
                candidate_ids.extend(_role_ids(value))
            is_admin = any(rid in {1, 2} for rid in candidate_ids)
        if action in {"approve", "reject"} and not is_admin:
            current_app.logger.warning(
                "Qualification %s denied: no admin role detected. role_values=%r roles=%r role_id=%r role_ids=%r",
                action, role_values, roles, user_value("role_id", "roleId"), user_value("role_ids", "roleIds"),
            )

        # Resolve the lead within the authenticated tenant first.
        lead = session.execute(
            text(f'''SELECT lead_id, stage_id, "client_ID" AS client_id, "qualification status" AS qualification_status
                     FROM {T("Lead_Master")}
                     WHERE lead_id = :lead_id AND tenant_id = :tenant_id
                     LIMIT 1'''),
            {"lead_id": lead_id, "tenant_id": tenant_id},
        ).fetchone()
        if not lead:
            return jsonify({"error": "Lead was not found for this tenant"}), 404

        stage_type = _cfg("STAGE_TYPE_SALES", int)

        def find_stage_id(stage_name):
            row = session.execute(
                text(f'''SELECT stage_id, stage_name
                         FROM {T("Pipeline_Stage_Master")}
                         WHERE stage_type = :stage_type
                           AND LOWER(TRIM(stage_name)) = LOWER(TRIM(:stage_name))
                         LIMIT 1'''),
                {"stage_type": stage_type, "stage_name": stage_name},
            ).fetchone()
            return row

        # Admin decisions are explicit actions; never trust a client-supplied status.
        if action in {"approve", "reject"}:
            if not is_admin:
                return jsonify({"error": "Only an Admin can approve or reject qualification"}), 403
            qual_row = find_stage_id("Qualification")
            in_qualification = bool(qual_row) and int(lead.stage_id or 0) == int(qual_row.stage_id)
            qs = _as_int(lead.qualification_status)
            # Pending (2), or a legacy lead sitting in Qualification with no status yet.
            if not (qs == 2 or (qs is None and in_qualification)):
                return jsonify({"error": "This lead is not pending qualification approval"}), 409
            target_name = "Opportunity" if action == "approve" else "Lost"
            target_row = find_stage_id(target_name)
            if not target_row:
                # Tolerate small naming differences (e.g. "Opportunities", "Lost Deals").
                target_row = session.execute(
                    text(f'''SELECT stage_id, stage_name
                             FROM {T("Pipeline_Stage_Master")}
                             WHERE stage_type = :stage_type
                               AND LOWER(stage_name) LIKE :pattern
                             ORDER BY stage_id LIMIT 1'''),
                    {"stage_type": stage_type,
                     "pattern": "%opportunit%" if action == "approve" else "%lost%"},
                ).fetchone()
            if not target_row:
                return jsonify({"error": f"Sales stage '{target_name}' is not configured"}), 500
            stage_id = int(target_row.stage_id)
            qualification_status = 1 if action == "approve" else 0
            stage_name = target_row.stage_name

        else:
            requested_stage = payload.get("stage")
            requested_stage_id = payload.get("stage_id")
            if requested_stage_id is not None:
                try:
                    stage_id = int(requested_stage_id)
                except (TypeError, ValueError):
                    return jsonify({"error": "stage_id must be an integer"}), 400
                target_row = session.execute(
                    text(f'''SELECT stage_id, stage_name
                             FROM {T("Pipeline_Stage_Master")}
                             WHERE stage_id = :stage_id AND stage_type = :stage_type
                             LIMIT 1'''),
                    {"stage_id": stage_id, "stage_type": stage_type},
                ).fetchone()
            else:
                stage_text = str(requested_stage or "").strip()
                if not stage_text:
                    return jsonify({"error": "stage or stage_id is required"}), 400
                if stage_text.lower() in {"lead", "enquiry", "inquiry"}:
                    stage_id = _cfg("STAGE_ID_LEAD", int)
                    target_row = session.execute(
                        text(f'''SELECT stage_id, stage_name FROM {T("Pipeline_Stage_Master")}
                                 WHERE stage_id = :stage_id AND stage_type = :stage_type LIMIT 1'''),
                        {"stage_id": stage_id, "stage_type": stage_type},
                    ).fetchone()
                else:
                    target_row = find_stage_id(stage_text)
                    stage_id = int(target_row.stage_id) if target_row else None
            if not target_row:
                return jsonify({"error": "Invalid Sales stage"}), 400
            stage_id = int(target_row.stage_id)
            stage_name = target_row.stage_name
            target_lower = str(stage_name).strip().lower()
            current_status = _as_int(lead.qualification_status)

            # A pending lead cannot be moved around the pipeline to bypass review.
            if current_status == 2:
                return jsonify({
                    "error": "This lead is pending Admin qualification approval",
                    "qualification_status": 2,
                }), 409

            # A quotation is compulsory before Proposal and every later stage
            # (Lost stays reachable at any time).
            if not questionnaire_completed:
                proposal_row = find_stage_id("Proposal")
                lost_gate_row = find_stage_id("Lost")
                is_lost_target = bool(lost_gate_row) and stage_id == int(lost_gate_row.stage_id)
                if proposal_row and stage_id >= int(proposal_row.stage_id) and not is_lost_target:
                    if not _client_has_quotation(session, tenant_id, lead.client_id):
                        return jsonify({
                            "error": f"A quotation is required before moving this company to {stage_name}. "
                                     "Create a quotation for the company first.",
                            "code": "QUOTATION_REQUIRED",
                        }), 409
            if questionnaire_completed:
                # The client may request Qualification or Lost; the server derives
                # the final stage and status from the submitted score.
                answers = payload.get("questionnaire_answers")
                if not isinstance(answers, list) or len(answers) != 5:
                    return jsonify({"error": "Submit exactly five questionnaire answers"}), 400
                if any(isinstance(answer, bool) or not isinstance(answer, int) or answer < 0 or answer > 3 for answer in answers):
                    return jsonify({"error": "Each questionnaire answer must be an integer from 0 to 3"}), 400
                # Score in the API payload is deliberately ignored; calculate it server-side.
                score = sum(answers)
                if score <= 5:
                    lost_row = find_stage_id("Lost")
                    if not lost_row:
                        return jsonify({"error": "Sales stage 'Lost' is not configured"}), 500
                    stage_id = int(lost_row.stage_id)
                    stage_name = lost_row.stage_name
                    qualification_status = 0
                else:
                    qualification_row = find_stage_id("Qualification")
                    if not qualification_row:
                        return jsonify({"error": "Sales stage 'Qualification' is not configured"}), 500
                    stage_id = int(qualification_row.stage_id)
                    stage_name = qualification_row.stage_name
                    qualification_status = 2
            elif target_lower == "qualification":
                return jsonify({
                    "error": "Complete the qualification questionnaire before moving this lead to Qualification"
                }), 400
            elif payload.get("qualification_status") is not None:
                return jsonify({"error": "qualification_status can only be changed by the qualification workflow"}), 400
            else:
                qualification_status = current_status

        won_row = find_stage_id("Won")
        if not won_row:
            return jsonify({"error": "Won stage is not configured for the Sales Pipeline"}), 500
        won_stage_id = int(won_row.stage_id)

        # Persist only the status and stage. Questionnaire answers and score are not stored.
        session.execute(
            text(f'''UPDATE {T("Lead_Master")}
                     SET stage_id = :stage_id,
                         "qualification status" = :qualification_status,
                         won_at = CASE
                             WHEN :stage_id = :won_stage_id
                              AND stage_id IS DISTINCT FROM :won_stage_id
                             THEN CURRENT_TIMESTAMP
                             ELSE won_at
                         END,
                         modified_date = CURRENT_DATE
                     WHERE lead_id = :lead_id AND tenant_id = :tenant_id'''),
            {
                "stage_id": stage_id,
                "qualification_status": qualification_status,
                "won_stage_id": won_stage_id,
                "lead_id": lead_id,
                "tenant_id": tenant_id,
            },
        )
        session.commit()
        response = {
            "message": "Sales stage updated successfully",
            "lead_id": lead_id,
            "stage_id": stage_id,
            "stage_name": stage_name,
            "qualification_status": qualification_status,
        }
        if action in {"approve", "reject"}:
            response["decision"] = action
        if questionnaire_completed:
            response["questionnaire_score"] = score
            response["qualification_tier"] = (
                "Low Priority" if score <= 5 else
                "Qualified" if score <= 10 else
                "Strong Opportunity" if score <= 13 else
                "Strategic Opportunity"
            )
        return jsonify(response), 200
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error updating Sales stage in Lead_Master: {e}")
        return jsonify({"error": "Failed to update sales stage", "details": str(e)}), 500
    finally:
        session.close()


@pipeline_bp.route(
    "/pipeline/sales/company/<int:client_id>/move-to-proposal",
    methods=["POST", "OPTIONS"],
)
@token_required
def move_company_to_proposal(client_id):
    """
    Called when a quotation for this company is Approved.

    Moves the company's Sales leads that are currently at the Opportunity
    stage to the Proposal stage. Leads at any other stage are left alone, so
    a lead that is already at Proposal or later is never moved backwards, and
    a lead pending qualification approval (qualification status 2) is skipped.
    Stage ids are looked up by name from Pipeline_Stage_Master (nothing hardcoded).
    """
    if request.method == "OPTIONS":
        return jsonify({}), 200

    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        stage_type = _cfg("STAGE_TYPE_SALES", int)

        def stage_by_name(name):
            return session.execute(
                text(f'''SELECT stage_id, stage_name
                         FROM {T("Pipeline_Stage_Master")}
                         WHERE stage_type = :stage_type
                           AND LOWER(TRIM(stage_name)) = LOWER(TRIM(:name))
                         LIMIT 1'''),
                {"stage_type": stage_type, "name": name},
            ).fetchone()

        opportunity = stage_by_name("Opportunity")
        proposal = stage_by_name("Proposal")
        if not opportunity or not proposal:
            return jsonify({
                "error": "Sales stages 'Opportunity' and 'Proposal' must both be configured"
            }), 500

        # Make sure the company belongs to this tenant.
        client = session.execute(
            text(f'''SELECT client_id FROM {T("Client_Master")}
                     WHERE client_id = :client_id AND tenant_id = :tenant_id
                     LIMIT 1'''),
            {"client_id": client_id, "tenant_id": tenant_id},
        ).fetchone()
        if not client:
            return jsonify({"error": "Company was not found for this tenant"}), 404

        moved = session.execute(
            text(f'''UPDATE {T("Lead_Master")}
                     SET stage_id = :proposal_id,
                         modified_date = CURRENT_DATE
                     WHERE tenant_id = :tenant_id
                       AND "client_ID" = :client_id
                       AND stage_id = :opportunity_id
                       AND "qualification status" IS DISTINCT FROM 2
                     RETURNING lead_id'''),
            {
                "proposal_id": int(proposal.stage_id),
                "tenant_id": tenant_id,
                "client_id": client_id,
                "opportunity_id": int(opportunity.stage_id),
            },
        ).fetchall()
        session.commit()

        lead_ids = [int(r.lead_id) for r in moved]
        return jsonify({
            "message": (
                f"Moved {len(lead_ids)} lead(s) to {proposal.stage_name}"
                if lead_ids else "No leads at the Opportunity stage to move"
            ),
            "client_id": client_id,
            "moved_lead_ids": lead_ids,
            "stage_id": int(proposal.stage_id),
            "stage_name": proposal.stage_name,
        }), 200
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error moving company {client_id} to Proposal: {e}")
        return jsonify({"error": "Failed to move company to Proposal", "details": str(e)}), 500
    finally:
        session.close()


@pipeline_bp.route("/pipeline/training/stages", methods=["GET", "OPTIONS"])



@token_required



def get_training_stages():



    """



    Training stages for the board, in tenant-specific board order.



    Each item:



      stage_id     Pipeline_Stage_Master id



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



        tenant_id = request.current_user.tenant_id



        stages = load_training_stage_context(session, tenant_id)



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



    Return training batches from Training_Details_New (under Training_Master_New).



    Training_Details_New is the source of truth for training batches; the training form writes it.



    Client_Master is used to resolve the company name.



    service_id is exposed as training_id for frontend compatibility.



    stage is resolved from Training_Details_New.Stage_ID (Pipeline_Stage_Master).



    client_id is exposed as company_id for the existing frontend.



    Awaiting Scheduling cards are appended first; they have



    training_id == None.



    """



    if request.method == "OPTIONS":



        return jsonify({}), 200



    session = SessionLocal()



    try:



        tenant_id = request.current_user.tenant_id



        # Sales stage 6 is Won. Keep the sales lead in Lead_Master and derive
        # an Awaiting Scheduling card for its company until a training batch
        # is created after the lead entered Won.
        stage_id_won = 6



        training_stages = load_training_stage_context(session, tenant_id)

        stage_awaiting = training_stages.awaiting

        stage_default = training_stages.default

        # Training batches live in Training_Details_New (one row per batch) under
        # Training_Master_New (one row per program); participants are in
        # Training_Participant_Data. This is exactly what the training form
        # (company_training_routes.py) writes, so a saved batch appears here.
        stage_name_by_id = {s["stage_id"]: s["stage_name"] for s in training_stages.ordered}

        results = session.execute(
            text(
                f"""
                SELECT
                    d."Training_Details_ID"       AS training_id,
                    d."Training_ID"               AS master_id,
                    d."Event_Number"              AS event_number,
                    d."Batch_Start_Date"          AS date_from,
                    d."Batch_End_Date"            AS date_to,
                    d."No_Of_Participants"        AS participant_count,
                    d."Trainer_ID"                AS trainer_id,
                    d."Stage_ID"                  AS stage_id,
                    d."Remarks"                   AS remarks,
                    d."Training_Fees"             AS training_fees,
                    d."Client_Address"            AS client_address,
                    d."State"                     AS state,
                    d."Pin_Code"                  AS pin_code,
                    d.created_at                  AS created_at,
                    d.po_file_url,
                    d.po_file_name,
                    d.po_received_at,
                    m."Client_ID"                 AS client_id,
                    m."Service_ID"                AS product_id,
                    m."Quotation_ID"              AS quotation_id,
                    m."Training_Location_City_ID" AS city_id,
                    cm.client_company_name,
                    pm.sku                        AS service_code,
                    pm.item_name                  AS service_title,
                    cy.city_name,
                    e.employee_name               AS trainer_name
                FROM {T("Training_Details_New")} d
                JOIN {T("Training_Master_New")} m
                  ON m."Training_ID" = d."Training_ID"
                LEFT JOIN {T("Client_Master")} cm
                  ON cm.client_id = m."Client_ID"
                 AND cm.tenant_id = m."Tenant_ID"
                LEFT JOIN {T("Product_Master")} pm
                  ON pm.product_id = m."Service_ID"
                 AND pm.tenant_id = m."Tenant_ID"
                LEFT JOIN {T("City_Master")} cy
                  ON cy.city_id = m."Training_Location_City_ID"
                LEFT JOIN {T("Employee_Master")} e
                  ON e.employee_id = d."Trainer_ID"
                WHERE m."Tenant_ID" = :tenant_id
                ORDER BY d."Training_Details_ID" DESC
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchall()

        participants_by_batch = {}
        batch_ids = [r.training_id for r in results]
        if batch_ids:
            participant_rows = session.execute(
                text(
                    f"""
                    SELECT "Training_Participant_Data_ID" AS id,
                           "Training_Details_ID"          AS training_id,
                           "Participant_Name"             AS name
                    FROM {T("Training_Participant_Data")}
                    WHERE "Training_Details_ID" = ANY(:ids)
                    ORDER BY "Training_Participant_Data_ID"
                    """
                ),
                {"ids": batch_ids},
            ).fetchall()
            for p in participant_rows:
                participants_by_batch.setdefault(p.training_id, []).append(
                    {"id": str(p.id), "name": p.name}
                )

        pipeline_items = []

        for row in results:

            stage = stage_name_by_id.get(row.stage_id) or stage_default

            # Awaiting Scheduling cards are derived below, never real batches.
            if stage == stage_awaiting:
                continue

            pipeline_items.append(
                {
                    "id": f"training-{row.training_id}",
                    "type": "training",
                    "training": {
                        "training_id": row.training_id,
                        "service_id": row.training_id,
                        "master_id": row.master_id,
                        # Company/client relationship
                        "company_id": row.client_id,
                        "client_id": row.client_id,
                        "company_name": row.client_company_name,
                        "quotation_id": row.quotation_id,
                        # Course information (Product_Master)
                        "product_id": row.product_id,
                        "service_code": row.service_code,
                        "training_name": row.service_title,
                        "service_title": row.service_title,
                        "training_fees": float(row.training_fees) if row.training_fees is not None else None,
                        # Batch information
                        "training_from": _iso(row.date_from),
                        "training_to": _iso(row.date_to),
                        "event_number": row.event_number,
                        "trainer_id": row.trainer_id,
                        "trainer_name": row.trainer_name,
                        "participant_count": row.participant_count,
                        # Location
                        "client_address": row.client_address,
                        "city_id": row.city_id,
                        "city": row.city_name,
                        "state": row.state,
                        "pin_code": row.pin_code,
                        # Other training data
                        "remarks": row.remarks,
                        "participants": participants_by_batch.get(row.training_id, []),
                        # Current pipeline stage
                        "stage": stage,
                        # PO copy (required before PO Received and later stages)
                        "po_file_url": row.po_file_url,
                        "po_file_name": row.po_file_name,
                        "po_received_at": _iso(row.po_received_at),
                        "created_at": _iso(row.created_at),
                    },
                    "stage": stage,
                    "pipeline_type": "training",
                }
            )

        # ── Awaiting Scheduling (derived cards, no batch row) ────────────
        # Every client with a Won lead must appear in Awaiting Scheduling.
        # Do not filter by client category/status or existing training rows.
        awaiting_rows = session.execute(
            text(
                f"""
                WITH won_clients AS (
                    SELECT DISTINCT ON (cm.client_id)
                        cm.client_id,
                        cm.client_company_name,
                        lm.won_at,
                        lm.created_date,
                        lm.lead_id
                    FROM {T("Lead_Master")} lm
                    JOIN {T("Client_Master")} cm
                      ON cm.client_id = lm."client_ID"
                     AND cm.tenant_id = lm.tenant_id
                    WHERE lm.tenant_id = :tenant_id
                      AND lm.stage_id = :stage_id_won
                    ORDER BY cm.client_id,
                             lm.won_at DESC NULLS LAST,
                             lm.created_date DESC NULLS LAST,
                             lm.lead_id DESC
                )
                SELECT client_id, client_company_name
                FROM won_clients
                ORDER BY client_company_name ASC
                """
            ),
            {
                "tenant_id": tenant_id,
                "stage_id_won": stage_id_won,
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



            f"Error fetching training pipeline from Training_Details_New: {e}"



        )



        return jsonify(



            {



                "error": "Failed to fetch training pipeline",



                "details": str(e),



            }



        ), 500



    finally:



        session.close()