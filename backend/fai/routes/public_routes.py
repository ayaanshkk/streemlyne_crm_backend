"""
backend/routes/public_routes.py

Public, UNAUTHENTICATED routes. This blueprint must NOT be wrapped in the
auth decorator that protects the rest of the app (no @token_required), and
app.py must skip the tenant check for /public/*. The qr_token itself is the
only "credential" — it's an unguessable UUID, so possession of the token is
what grants access.

Register in app.py like any other blueprint:
    from .routes.public_routes import public_bp
    app.register_blueprint(public_bp)

No schema names are written in this file; every table goes through T().
"""

import json

from flask import Blueprint, jsonify, current_app
from sqlalchemy import text

from .config_helpers import T
from ..db import SessionLocal

public_bp = Blueprint("public_bp", __name__, url_prefix="/public")


def _as_list(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return []
    return value if isinstance(value, list) else []


def _score(record, prefix):
    """Graded score of one test (pre or post) as 'obtained/total', or None."""
    obtained = record.get(f"{prefix}TestObtained")
    total = record.get(f"{prefix}TestTotal")
    if obtained is None or total is None:
        return None
    return f"{obtained}/{total}"


def _record_passed(record, fallback):
    """
    A training record counts as passed when its post-test is passed; if there
    is no post-test result yet, the pre-test result decides. When the record
    has no result at all, fall back to the participant-level pass flag.
    """
    post = record.get("postPassed")
    if post is not None:
        return bool(post)
    pre = record.get("prePassed")
    if pre is not None:
        return bool(pre)
    return bool(fallback)


@public_bp.route("/participant/<string:token>", methods=["GET"])
def get_public_participant(token):
    """
    Looks up a participant by QR_Token OR Participant_Unique_ID (fallback for
    manual entry if the QR doesn't scan) in Training_Participant_Data, the
    table the training form writes. Returns ONLY what is safe to show on an
    unauthenticated page: name, unique id and the training (company, dates,
    program, trainer, MHE type, test scores). Participants are no longer linked
    to Contacts, so the history is this participant's own training record(s).
    No papers, certificates, phone/email/internal ids or other participants
    are exposed.
    """
    session = SessionLocal()
    try:
        h = session.execute(
            text(f"""
                SELECT p."Participant_Name"        AS name,
                       p."Participant_Unique_ID"   AS participant_unique_id,
                       p."Is_Pass"                 AS is_pass,
                       p."Pre_Test"                AS pre_test,
                       p."Post_Test"               AS post_test,
                       p."Training_Records"        AS records,
                       mhe."MHE_Name"              AS mhe_name,
                       d."Event_Number"            AS event_number,
                       d."Batch_Start_Date"        AS date_from,
                       d."Batch_End_Date"          AS date_to,
                       pm.item_name                AS program,
                       cm.client_company_name      AS company_name,
                       e.employee_name             AS trainer_name
                FROM {T("Training_Participant_Data")} p
                JOIN {T("Training_Details_New")} d
                  ON d."Training_Details_ID" = p."Training_Details_ID"
                JOIN {T("Training_Master_New")} m
                  ON m."Training_ID" = d."Training_ID"
                LEFT JOIN {T("Client_Master")} cm
                  ON cm.client_id = m."Client_ID" AND cm.tenant_id = m."Tenant_ID"
                LEFT JOIN {T("Product_Master")} pm
                  ON pm.product_id = m."Service_ID" AND pm.tenant_id = m."Tenant_ID"
                LEFT JOIN {T("Employee_Master")} e
                  ON e.employee_id = d."Trainer_ID"
                LEFT JOIN {T("MHE_Master")} mhe
                  ON mhe."MHE_ID" = p."MHE_ID"
                WHERE CAST(p."QR_Token" AS text) = :token
                   OR p."Participant_Unique_ID" = :token
                LIMIT 1
            """),
            {"token": token},
        ).fetchone()

        if h is None:
            return jsonify({"error": "Not found"}), 404

        base = {
            "event_number": h.event_number,
            "company_name": h.company_name,
            "program": h.program,
            "training_from": h.date_from.isoformat() if h.date_from else None,
            "training_to": h.date_to.isoformat() if h.date_to else None,
            "trainer_name": h.trainer_name,
        }

        trainings = []
        records = _as_list(h.records)
        if records:
            # A participant can have several records (e.g. two Forklift trainings).
            for r in records:
                trainings.append({
                    **base,
                    "mhe_type": r.get("mheType") or h.mhe_name or None,
                    "pretest_score": _score(r, "pre"),
                    "posttest_score": _score(r, "post"),
                    "pass": _record_passed(r, h.is_pass),
                })
        else:
            # No graded paper yet: show the marks saved on the participant row.
            total = 20 if "bopt" in str(h.mhe_name or "").lower() else 24
            trainings.append({
                **base,
                "mhe_type": h.mhe_name or None,
                "pretest_score": f"{h.pre_test}/{total}" if h.pre_test else None,
                "posttest_score": f"{h.post_test}/{total}" if h.post_test else None,
                "pass": bool(h.is_pass),
            })

        return jsonify({
            "participant_name": h.name or "Unknown",
            "participant_unique_id": h.participant_unique_id,
            "trainings": trainings,
        })

    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"error": "Could not verify"}), 500
    finally:
        session.close()