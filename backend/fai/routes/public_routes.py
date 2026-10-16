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
    Looks up a participant by qr_token OR participant_unique_id (fallback for
    manual entry if the QR doesn't scan). Returns ONLY what is safe to show on
    an unauthenticated page: name and training history (company, dates, MHE
    type, test scores). One entry per training record. No papers, certificates,
    phone/email/internal ids or other participants are ever exposed.
    """
    session = SessionLocal()
    try:
        # 1. Find the batch + participant entry holding this token
        row = None
        for key in ("qr_token", "participant_unique_id"):
            row = session.execute(
                text(f"""
                    SELECT service_id, client_id, participants
                    FROM {T("Services_Master_archive")}
                    WHERE participants @> CAST(:match AS jsonb)
                    LIMIT 1
                """),
                {"match": json.dumps([{key: token}])},
            ).fetchone()
            if row is not None:
                break

        if row is None:
            return jsonify({"error": "Not found"}), 404

        matched = next(
            (
                p for p in _as_list(row.participants)
                if p.get("qr_token") == token or p.get("participant_unique_id") == token
            ),
            None,
        )
        if matched is None:
            return jsonify({"error": "Not found"}), 404

        # Participants picked from Contacts carry a contact_id; ones added by
        # name only don't. Both must verify.
        contact_id = matched.get("contact_id")
        participant_name = matched.get("name") or "Unknown"

        # 2. Display name (from Contacts when linked)
        if contact_id is not None:
            contact_row = session.execute(
                text(f"SELECT full_name FROM {T('Contacts')} WHERE contact_id = :cid"),
                {"cid": contact_id},
            ).fetchone()
            if contact_row and contact_row.full_name:
                participant_name = contact_row.full_name

        # 3. Training history: every batch containing this contact, or just
        #    this batch when the participant has no contact link.
        history_sql = f"""
            SELECT sm.service_id, sm.event_number, sm.service_title,
                   sm.date_from, sm.date_to, sm.trainer_name, sm.participants,
                   cm.client_company_name AS company_name
            FROM {T("Services_Master_archive")} sm
            LEFT JOIN {T("Client_Master")} cm ON cm.client_id = sm.client_id
        """
        if contact_id is not None:
            history_rows = session.execute(
                text(history_sql + """
                    WHERE sm.participants @> CAST(:match AS jsonb)
                    ORDER BY sm.date_from DESC NULLS LAST
                """),
                {"match": json.dumps([{"contact_id": contact_id}])},
            ).fetchall()
        else:
            history_rows = session.execute(
                text(history_sql + " WHERE sm.service_id = :sid"),
                {"sid": row.service_id},
            ).fetchall()

        def same_person(p):
            if contact_id is not None:
                return p.get("contact_id") == contact_id
            return p.get("id") == matched.get("id")

        # 4. One training per training record (a participant can have several
        #    records, e.g. two Forklift trainings, inside the same batch).
        trainings = []
        for h in history_rows:
            entry = next((p for p in _as_list(h.participants) if same_person(p)), None)
            if not entry:
                continue

            base = {
                "event_number": h.event_number,
                "company_name": h.company_name,
                "program": h.service_title,
                "training_from": h.date_from.isoformat() if h.date_from else None,
                "training_to": h.date_to.isoformat() if h.date_to else None,
                "trainer_name": h.trainer_name,
            }

            records = entry.get("trainingRecords") or []
            if not records:
                trainings.append({
                    **base,
                    "mhe_type": None,
                    "pretest_score": None,
                    "posttest_score": None,
                    "pass": bool(entry.get("pass")),
                })
                continue

            for r in records:
                trainings.append({
                    **base,
                    "mhe_type": r.get("mheType") or None,
                    "pretest_score": _score(r, "pre"),
                    "posttest_score": _score(r, "post"),
                    "pass": _record_passed(r, entry.get("pass")),
                })

        return jsonify({
            "participant_name": participant_name,
            "participant_unique_id": matched.get("participant_unique_id"),
            "trainings": trainings,
        })

    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"error": "Could not verify"}), 500
    finally:
        session.close()