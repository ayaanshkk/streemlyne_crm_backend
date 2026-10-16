"""

Calendar Routes for StreemLyne CRM - Training Calendar

New FAI DB only:

*\\-* Schema: streemLyne_mt_dev2

*\\-* Uses SessionLocal only

*\\-* No primary/secondary DB logic

"""

import json

from datetime import date

from flask import Blueprint, request, jsonify, current_app

from sqlalchemy import text

from .auth_helpers import token_required

from ..db import SessionLocal

calendar_bp = Blueprint("calendar", __name__)

SCHEMA = "streemLyne_mt_dev2"

TRAINING_CONTACT_METHOD = 1

def get_current_tenant_id(session, user_id):

    row = session.execute(

        text(f"""

            SELECT em.tenant_id

            FROM "{SCHEMA}"."User_Master" um

            JOIN "{SCHEMA}"."Employee_Master" em

              ON em.employee_id = um.employee_id

            WHERE um.user_id = :user_id

              AND um.is_active = true

        """),

        {"user_id": user_id},

    ).fetchone()

    return row.tenant_id if row else None

def parse_event_row(row):

    """Convert a calendar DB row into the frontend event format."""

    meta = {}

    notes_text = getattr(row, "notes", None) or ""

    if "__meta__" in notes_text and "__end_meta__" in notes_text:

        try:

            meta_str = notes_text.split("__meta__", 1)[1].split(

                "__end_meta__", 1

            )[0]

            meta = json.loads(meta_str)

            notes_text = notes_text.split("__end_meta__", 1)[1]

        except (ValueError, TypeError, json.JSONDecodeError):

            pass

    display_date = getattr(row, "display_date", None)

    row_source = getattr(row, "source", None)

    source = row_source or meta.get("source", "manual")

    # Services_Master rows carry the authoritative training range.

    # Legacy Client_Interactions training rows represent one historical

    # calendar occurrence and must NOT inherit their metadata training_to.

    row_training_to = getattr(row, "training_to", None)

    if row_training_to is not None:

        training_to = row_training_to

    elif source == "training_session":

        training_to = None

    else:

        training_to = meta.get("training_to")

    if hasattr(training_to, "isoformat"):

        training_to = training_to.isoformat()

    training_id = getattr(row, "training_id", None) or meta.get("training_id")

    name = getattr(row, "name", None) or "Unknown Client"

    assigned_to = (

        getattr(row, "assigned_to", None)

        or meta.get("team_member", "")

        or ""

    )

    display_date_iso = display_date.isoformat() if display_date else None

    if source == "training_session" and row_training_to is None:

        # Historical Client_Interactions training occurrence.

        historical_type = (

            "Training Conducted"

            if display_date and display_date < date.today()

            else "Training Scheduled"

        )

    else:

        historical_type = meta.get("type", "Training")

    return {

        "id": str(row.id),

        "customer_id": getattr(row, "customer_id", None),

        "type": "training",

        "title": meta.get("title", f"{name} - Training"),

        "name": name,

        "display_date": display_date_iso,

        "display_type": historical_type,

        "status": historical_type if historical_type.startswith("Training ") else meta.get("status", "Scheduled"),

        "contact": getattr(row, "contact", None) or "",

        "phone": getattr(row, "phone", None) or "",

        "email": getattr(row, "email", None) or "",

        "address": getattr(row, "address", None) or "",

        "notes": notes_text.strip(),

        "reminder_date": (

            getattr(row, "reminder_date", None).isoformat()

            if getattr(row, "reminder_date", None)

            else None

        ),

        "assigned_to": assigned_to,

        "created_at": (

            getattr(row, "created_at", None).isoformat()

            if getattr(row, "created_at", None)

            else None

        ),

        "training_id": training_id,

        "training_to": training_to,

        "source": source,

        "database": "dev2",

    }

@calendar_bp.route("/calendar/events", methods=["GET", "OPTIONS"])

@token_required

def get_calendar_events():

    if request.method == "OPTIONS":

        return jsonify({}), 200

    session = SessionLocal()

    try:

        current_user = request.current_user

        tenant_id = get_current_tenant_id(session, current_user.id)

        if tenant_id is None:

            return jsonify({"error": "User or tenant not found"}), 404

        rows = session.execute(

            text(f"""

                SELECT

                    sm.service_id AS id,

                    sm.client_id AS customer_id,

                    sm.date_from AS display_date,

                    sm.date_to::text AS training_to,

                    sm.trainer_name AS assigned_to,

                    NULL::date AS reminder_date,

                    sm.created_at AS created_at,

                    sm.service_id AS training_id,

                    'training_session' AS source,

                    cm.client_company_name AS name,

                    NULL::text AS contact,

                    cm.client_phone AS phone,

                    cm.client_email AS email,

                    cm.address AS address,

                    sm.remarks AS notes

                FROM "{SCHEMA}"."Services_Master_archive" sm

                LEFT JOIN "{SCHEMA}"."Client_Master" cm

                    ON cm.client_id = sm.client_id

                WHERE sm.tenant_id = :tenant_id

                  AND sm.date_from IS NOT NULL

                UNION ALL

                SELECT

                    ci.interaction_id AS id,

                    ci.client_id AS customer_id,

                    ci.contact_date AS display_date,

                    NULL::text AS training_to,

                    NULL::text AS assigned_to,

                    ci.reminder_date AS reminder_date,

                    ci.created_at AS created_at,

                    NULL::integer AS training_id,

                    CASE

                        WHEN ci.notes LIKE '%"source": "training_session"%'

                        THEN 'training_session'

                        ELSE 'manual'

                    END AS source,

                    cm.client_company_name AS name,

                    NULL::text AS contact,

                    cm.client_phone AS phone,

                    cm.client_email AS email,

                    cm.address AS address,

                    ci.notes AS notes

                FROM "{SCHEMA}"."Client_Interactions" ci

                LEFT JOIN "{SCHEMA}"."Client_Master" cm

                    ON cm.client_id = ci.client_id

                WHERE ci.contact_method = :contact_method

                  AND cm.tenant_id = :tenant_id

                                    AND (
                      ci.notes IS NULL
                      OR ci.notes NOT LIKE '%"source": "training_session"%'
                  )

                  ORDER BY display_date DESC

            """),

            {

                "tenant_id": tenant_id,

                "contact_method": TRAINING_CONTACT_METHOD,

            },

        ).fetchall()

        return jsonify([parse_event_row(row) for row in rows]), 200

    except Exception as e:

        current_app.logger.exception("Error fetching calendar events")

        return jsonify({"error": str(e)}), 500

    finally:

        session.close()

@calendar_bp.route("/calendar/employees", methods=["GET", "OPTIONS"])

@token_required

def get_calendar_employees():

    if request.method == "OPTIONS":

        return jsonify({}), 200

    session = SessionLocal()

    try:

        tenant_id = get_current_tenant_id(

            session, request.current_user.id

        )

        if tenant_id is None:

            return jsonify({"error": "User or tenant not found"}), 404

        rows = session.execute(

            text(f"""

                SELECT DISTINCT

                    em.employee_id AS id,

                    em.employee_name AS full_name,

                    em.email

                FROM "{SCHEMA}"."Employee_Master" em

                JOIN "{SCHEMA}"."User_Master" um

                  ON um.employee_id = em.employee_id

                WHERE um.is_active = true

                  AND em.tenant_id = :tenant_id

                ORDER BY em.employee_name ASC

            """),

            {"tenant_id": tenant_id},

        ).fetchall()

        return jsonify([

            {

                "id": row.id,

                "full_name": row.full_name,

                "email": row.email or "",

            }

            for row in rows

        ]), 200

    except Exception as e:

        current_app.logger.exception("Error fetching calendar employees")

        return jsonify({"error": str(e)}), 500

    finally:

        session.close()

@calendar_bp.route("/calendar/event/<int:event_id>", methods=["GET", "OPTIONS"])

@token_required

def get_calendar_event(event_id):

    if request.method == "OPTIONS":

        return jsonify({}), 200

    session = SessionLocal()

    try:

        tenant_id = get_current_tenant_id(

            session, request.current_user.id

        )

        if tenant_id is None:

            return jsonify({"error": "User or tenant not found"}), 404

        row = session.execute(

            text(f"""

                SELECT

                    ci.interaction_id AS id,

                    ci.client_id AS customer_id,

                    ci.contact_date AS display_date,

                    ci.reminder_date,

                    ci.notes,

                    ci.next_steps,

                    ci.created_at,

                    cm.client_company_name AS name,

                    NULL AS contact,

                    cm.client_phone AS phone,

                    cm.client_email AS email,

                    cm.address

                FROM "{SCHEMA}"."Client_Interactions" ci

                JOIN "{SCHEMA}"."Client_Master" cm

                  ON cm.client_id = ci.client_id

                WHERE ci.interaction_id = :event_id

                  AND ci.contact_method = :contact_method

                  AND cm.tenant_id = :tenant_id

            """),

            {

                "event_id": event_id,

                "contact_method": TRAINING_CONTACT_METHOD,

                "tenant_id": tenant_id,

            },

        ).fetchone()

        if not row:

            return jsonify({"error": "Event not found"}), 404

        return jsonify(parse_event_row(row)), 200

    except Exception as e:

        current_app.logger.exception(

            "Error fetching calendar event %s", event_id

        )

        return jsonify({"error": str(e)}), 500

    finally:

        session.close()

@calendar_bp.route("/calendar/events/create", methods=["POST", "OPTIONS"])

@token_required

def create_calendar_event():

    if request.method == "OPTIONS":

        return jsonify({}), 200

    session = SessionLocal()

    try:

        current_user = request.current_user

        data = request.get_json() or {}

        client_id = data.get("client_id")

        contact_date = data.get("contact_date")

        training_type = data.get(

            "training_type", "Training Scheduled"

        )

        notes_text = data.get("notes", "")

        if not client_id or not contact_date:

            return jsonify({

                "error": "client_id and contact_date are required"

            }), 400

        tenant_id = get_current_tenant_id(session, current_user.id)

        if tenant_id is None:

            return jsonify({"error": "User or tenant not found"}), 404

        client_row = session.execute(

            text(f"""

                SELECT client_id

                FROM "{SCHEMA}"."Client_Master"

                WHERE client_id = :client_id

                  AND tenant_id = :tenant_id

            """),

            {

                "client_id": int(client_id),

                "tenant_id": tenant_id,

            },

        ).fetchone()

        if not client_row:

            return jsonify({

                "error": "Client not found or access denied"

            }), 404

        meta = json.dumps({

            "type": training_type,

            "status": "Scheduled",

            "title": f"Training - {training_type}",

            "source": "manual",

        })

        full_notes = (

            f"__meta__{meta}__end_meta__{notes_text}"

        )

        result = session.execute(

            text(f"""

                INSERT INTO "{SCHEMA}"."Client_Interactions"

                    (client_id, contact_method, contact_date, notes)

                VALUES

                    (:client_id, :contact_method, :contact_date, :notes)

                RETURNING interaction_id

            """),

            {

                "client_id": int(client_id),

                "contact_method": TRAINING_CONTACT_METHOD,

                "contact_date": contact_date,

                "notes": full_notes,

            },

        )

        interaction_id = result.scalar_one()

        session.commit()

        return jsonify({

            "id": str(interaction_id),

            "client_id": int(client_id),

            "contact_date": contact_date,

            "training_type": training_type,

        }), 201

    except Exception as e:

        session.rollback()

        current_app.logger.exception("Error creating calendar event")

        return jsonify({"error": str(e)}), 500

    finally:

        session.close()

@calendar_bp.route(

    "/calendar/events/<int:event_id>",

    methods=["DELETE", "OPTIONS"],

)

@token_required

def delete_calendar_event(event_id):

    if request.method == "OPTIONS":

        return jsonify({}), 200

    session = SessionLocal()

    try:

        tenant_id = get_current_tenant_id(

            session, request.current_user.id

        )

        if tenant_id is None:

            return jsonify({"error": "User or tenant not found"}), 404

        result = session.execute(

            text(f"""

                DELETE FROM "{SCHEMA}"."Client_Interactions" ci

                USING "{SCHEMA}"."Client_Master" cm

                WHERE ci.interaction_id = :event_id

                  AND ci.contact_method = :contact_method

                  AND ci.client_id = cm.client_id

                  AND cm.tenant_id = :tenant_id

            """),

            {

                "event_id": event_id,

                "contact_method": TRAINING_CONTACT_METHOD,

                "tenant_id": tenant_id,

            },

        )

        if result.rowcount == 0:

            session.rollback()

            return jsonify({

                "error": "Event not found or access denied"

            }), 404

        session.commit()

        return jsonify({

            "success": True,

            "deleted": event_id

        }), 200

    except Exception as e:

        session.rollback()

        current_app.logger.exception(

            "Error deleting calendar event %s", event_id

        )

        return jsonify({"error": str(e)}), 500

    finally:

        session.close()

@calendar_bp.route(

    "/calendar/events/<int:event_id>",

    methods=["PUT", "OPTIONS"],

)

@token_required

def update_calendar_event(event_id):

    if request.method == "OPTIONS":

        return jsonify({}), 200

    session = SessionLocal()

    try:

        data = request.get_json() or {}

        new_date = data.get("contact_date")

        if not new_date:

            return jsonify({

                "error": "contact_date is required"

            }), 400

        tenant_id = get_current_tenant_id(

            session, request.current_user.id

        )

        if tenant_id is None:

            return jsonify({"error": "User or tenant not found"}), 404

        result = session.execute(

            text(f"""

                UPDATE "{SCHEMA}"."Client_Interactions" ci

                SET contact_date = :new_date

                FROM "{SCHEMA}"."Client_Master" cm

                WHERE ci.interaction_id = :event_id

                  AND ci.contact_method = :contact_method

                  AND ci.client_id = cm.client_id

                  AND cm.tenant_id = :tenant_id

            """),

            {

                "event_id": event_id,

                "new_date": new_date,

                "contact_method": TRAINING_CONTACT_METHOD,

                "tenant_id": tenant_id,

            },

        )

        if result.rowcount == 0:

            session.rollback()

            return jsonify({

                "error": "Event not found or access denied"

            }), 404

        session.commit()

        return jsonify({

            "success": True,

            "event_id": event_id,

            "new_date": new_date,

        }), 200

    except Exception as e:

        session.rollback()

        current_app.logger.exception(

            "Error updating calendar event %s", event_id

        )

        return jsonify({"error": str(e)}), 500

    finally:

        session.close()