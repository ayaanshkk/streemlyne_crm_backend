from flask import Blueprint, jsonify, request, current_app
from sqlalchemy import text
from datetime import datetime
from .auth_helpers import token_required
from ..db import SessionLocal

notification_bp = Blueprint('notification', __name__, url_prefix='/notifications')

SCHEMA = "streemLyne_mt_dev2"
FAI_TENANT_ID = "3"


def T(table_name):
    return f'"{SCHEMA}"."{table_name}"'


def create_notification(session, message: str, notification_type: str = "proposal",
                        proposal_id: int = None, client_id: int = None,
                        created_by_employee_id: int = None, priority: str = "medium"):
    """
    Insert into Notification_Master. Call this from other routes.
    created_by_employee_id is stored so we can exclude the sender from seeing it.
    """
    session.execute(
        text(f"""
            INSERT INTO {T("Notification_Master")}
                (tenant_id, employee_id, client_id, proposal_id,
                 notification_type, priority, message,
                 created_by_employee_id, created_at)
            VALUES
                (:tenant_id, NULL, :client_id, :proposal_id,
                 :notification_type, :priority, :message,
                 :created_by_employee_id, :created_at)
        """),
        {
            "tenant_id":                FAI_TENANT_ID,
            "client_id":               client_id,
            "proposal_id":             proposal_id,
            "notification_type":       notification_type,
            "priority":                priority,
            "message":                 message,
            "created_by_employee_id":  created_by_employee_id,
            "created_at":              datetime.utcnow(),
        }
    )


def _get_employee_id(session, user_id: int):
    row = session.execute(
        text(f"""
            SELECT employee_id
            FROM "{SCHEMA}"."User_Master"
            WHERE user_id = :user_id
            LIMIT 1
        """),
        {"user_id": user_id}
    ).fetchone()

    return row.employee_id if row else None

def _serialize(r) -> dict:
    return {
        "id":          str(r.notification_id),
        "message":     r.message,
        "read":        r.read or False,
        "dismissed":   r.dismissed or False,
        "created_at":  r.created_at.isoformat() if r.created_at else None,
        "customer_id": str(r.client_id) if r.client_id else None,
        "proposal_id": str(r.proposal_id) if r.proposal_id else None,
        "priority":    r.priority,
        "type":        r.notification_type,
    }


# ── GET /notifications ─────────────────────────────────────────────
# Excludes dismissed — used by sidebar
@notification_bp.route('', methods=['GET', 'OPTIONS'])
@token_required
def get_notifications():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = SessionLocal()
    try:
        emp_id = _get_employee_id(session, request.current_user.id)
        rows = session.execute(
            text(f"""
                SELECT * FROM {T("Notification_Master")}
                WHERE tenant_id = :tid
                AND dismissed = FALSE
                AND (created_by_employee_id IS NULL OR created_by_employee_id != :emp_id)
                ORDER BY created_at DESC
                LIMIT 50
            """),
            {"tid": FAI_TENANT_ID, "emp_id": emp_id or -1}
        ).fetchall()
        return jsonify([_serialize(r) for r in rows]), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        current_app.logger.error(f"❌ Notifications error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

# ── GET /notifications/all ─────────────────────────────────────────
# Includes dismissed — used by full notifications page
@notification_bp.route('/all', methods=['GET', 'OPTIONS'])
@token_required
def get_all_notifications():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = SessionLocal()
    try:
        emp_id = _get_employee_id(session, request.current_user.id)
        rows = session.execute(
            text(f"""
                SELECT * FROM {T("Notification_Master")}
                WHERE tenant_id = :tid
                AND (created_by_employee_id IS NULL OR created_by_employee_id != :emp_id)
                ORDER BY created_at DESC
                LIMIT 200
            """),
            {"tid": FAI_TENANT_ID, "emp_id": emp_id or -1}
        ).fetchall()
        return jsonify([_serialize(r) for r in rows]), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ── PATCH /notifications/<id>/read ─────────────────────────────────
@notification_bp.route('/<int:notif_id>/read', methods=['PATCH', 'OPTIONS'])
@token_required
def mark_read(notif_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = SessionLocal()
    try:
        session.execute(
            text(f"""
                UPDATE {T("Notification_Master")}
                SET read = TRUE, read_at = :now
                WHERE notification_id = :id AND tenant_id = :tid
            """),
            {"id": notif_id, "tid": FAI_TENANT_ID, "now": datetime.utcnow()}
        )
        session.commit()
        return jsonify({'success': True}), 200
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ── PATCH /notifications/mark-all-read ─────────────────────────────
@notification_bp.route('/mark-all-read', methods=['PATCH', 'OPTIONS'])
@token_required
def mark_all_read():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = SessionLocal()
    try:
        emp_id = _get_employee_id(session, request.current_user.id)
        session.execute(
            text(f"""
                UPDATE {T("Notification_Master")}
                SET read = TRUE, read_at = :now
                WHERE tenant_id = :tid
                AND (created_by_employee_id IS NULL OR created_by_employee_id != :emp_id)
            """),
            {"tid": FAI_TENANT_ID, "emp_id": emp_id or -1, "now": datetime.utcnow()}
        )
        session.commit()
        return jsonify({'success': True}), 200
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ── POST /notifications/<id>/dismiss ───────────────────────────────
@notification_bp.route('/<int:notif_id>/dismiss', methods=['POST', 'OPTIONS'])
@token_required
def dismiss_notification(notif_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = SessionLocal()
    try:
        session.execute(
            text(f"""
                UPDATE {T("Notification_Master")}
                SET dismissed = TRUE
                WHERE notification_id = :id AND tenant_id = :tid
            """),
            {"id": notif_id, "tid": FAI_TENANT_ID}
        )
        session.commit()
        return jsonify({'success': True}), 200
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ── DELETE /notifications/<id> ─────────────────────────────────────
@notification_bp.route('/<int:notif_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_notification(notif_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = SessionLocal()
    try:
        session.execute(
            text(f"""
                DELETE FROM {T("Notification_Master")}
                WHERE notification_id = :id AND tenant_id = :tid
            """),
            {"id": notif_id, "tid": FAI_TENANT_ID}
        )
        session.commit()
        return jsonify({'success': True}), 200
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ── DELETE /notifications/clear-all ────────────────────────────────
@notification_bp.route('/clear-all', methods=['DELETE', 'OPTIONS'])
@token_required
def clear_all():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = SessionLocal()
    try:
        emp_id = _get_employee_id(session, request.current_user.id)
        session.execute(
            text(f"""
                DELETE FROM {T("Notification_Master")}
                WHERE tenant_id = :tid
                AND (created_by_employee_id IS NULL OR created_by_employee_id != :emp_id)
            """),
            {"tid": FAI_TENANT_ID, "emp_id": emp_id or -1}
        )
        session.commit()
        return jsonify({'success': True}), 200
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()