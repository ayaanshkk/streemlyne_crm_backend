"""
backend/routes/company_interactions_routes.py

Interaction logging (calls, emails, notes, tasks, meetings) for a Company
(streemLyne_mt_dev2.Client_Master, "client_category_master_id " = Commercial),
mirroring contact_interactions_routes.py but scoped to companies instead of
contacts, and running on the dev DB connection (SessionLocal) like
company_routes.py / company_enquiry_routes.py.

Endpoints:
  POST   /companies/<company_id>/interactions
  GET    /companies/<company_id>/interactions
  DELETE /companies/<company_id>/interactions/<interaction_id>
"""

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text
from datetime import datetime
from routes.cc_compat import token_required
from routes.cc_compat import SessionLocal
import json

company_interactions_bp = Blueprint('company_interactions', __name__)

from routes.cc_compat import SCHEMA

COMMERCIAL_CATEGORY_ID = 1   # Client_Category_Master.Category_Name = 'Commercial'
ACTIVE_STATUS_ID = 1         # Status_Master.status = 'Active'

VALID_INTERACTION_TYPES = {
    "Called", "Not Answered", "Callback", "Email Sent", "WhatsApp",
    "Note", "Task", "Meeting",
}

CALL_OUTCOMES = {"Connected", "No Answer", "Left Voicemail", "Busy"}
CALL_DIRECTIONS = {"Inbound", "Outbound"}
TASK_PRIORITIES = {"Low", "Medium", "High"}


def parse_optional_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def parse_optional_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (ValueError, TypeError):
        return None


def get_tenant_company(session, company_id, tenant_id):
    return session.execute(
        text(f'SELECT client_id FROM "{SCHEMA}"."Client_Master" '
             f'WHERE client_id = :cid AND tenant_id = :tid '
             f'AND "Client_Category_Master_ID" = :cat_id AND status_id = :active_id'),
        {"cid": company_id, "tid": tenant_id,
         "cat_id": COMMERCIAL_CATEGORY_ID, "active_id": ACTIVE_STATUS_ID}
    ).fetchone()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: POST /companies/<company_id>/interactions
# ═════════════════════════════════════════════════════════════════════════════
@company_interactions_bp.route('/companies/<int:company_id>/interactions', methods=['POST', 'OPTIONS'])
@token_required
def create_company_interaction(company_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        data = request.get_json() or {}

        company = get_tenant_company(session, company_id, request.current_user.tenant_id)
        if not company:
            return jsonify({'error': 'Company not found'}), 404

        interaction_type = data.get('interaction_type')
        notes = (data.get('notes') or '').strip()

        if not interaction_type:
            return jsonify({'error': 'Interaction type is required'}), 400
        if interaction_type not in VALID_INTERACTION_TYPES:
            return jsonify({'error': f'Unsupported interaction type: {interaction_type}'}), 400

        errors = {}

        subject = None
        outcome = None
        duration_minutes = None
        direction = None
        due_date = None
        assignee_name = None
        priority = None
        contact_time = None
        contact_date = parse_optional_date(data.get('contact_date')) or datetime.utcnow().date()

        if interaction_type == "Called":
            outcome = data.get('outcome')
            if outcome and outcome not in CALL_OUTCOMES:
                errors['outcome'] = f"Must be one of: {', '.join(sorted(CALL_OUTCOMES))}"
            direction = data.get('direction')
            if direction and direction not in CALL_DIRECTIONS:
                errors['direction'] = f"Must be one of: {', '.join(sorted(CALL_DIRECTIONS))}"
            duration_raw = data.get('duration_minutes')
            if duration_raw not in (None, ''):
                try:
                    duration_minutes = int(duration_raw)
                except (TypeError, ValueError):
                    errors['duration_minutes'] = "Must be a whole number of minutes"
            contact_time = parse_optional_time(data.get('contact_time'))

        elif interaction_type == "Task":
            subject = (data.get('subject') or '').strip()
            if not subject:
                errors['subject'] = "Task title is required"
            due_date = parse_optional_date(data.get('due_date'))
            assignee_name = (data.get('assignee_name') or '').strip() or None
            priority = data.get('priority')
            if priority and priority not in TASK_PRIORITIES:
                errors['priority'] = f"Must be one of: {', '.join(sorted(TASK_PRIORITIES))}"

        elif interaction_type == "Email Sent":
            subject = (data.get('subject') or '').strip()
            if not subject:
                errors['subject'] = "Email subject is required"

        elif interaction_type == "Meeting":
            contact_time = parse_optional_time(data.get('contact_time'))

        if errors:
            return jsonify({'error': 'Validation failed', 'details': errors}), 400

        method_map = {
            "Called": 1, "Not Answered": 1, "Callback": 1,
            "Email Sent": 2, "WhatsApp": 3, "Note": 5, "Task": 6, "Meeting": 7,
        }
        contact_method = method_map.get(interaction_type, 5)
        formatted_notes = f"[{interaction_type}] {notes}" if notes else f"[{interaction_type}]"

        result = session.execute(
            text(f"""
                INSERT INTO "{SCHEMA}"."Client_Interactions"
                    (client_id, entity_type, contact_date, contact_time, contact_method, notes,
                    subject, outcome, duration_minutes, direction,
                    due_date, assignee_name, priority, created_at)
                VALUES
                    (:client_id, :entity_type, :contact_date, :contact_time, :contact_method, :notes,
                    :subject, :outcome, :duration_minutes, :direction,
                    :due_date, :assignee_name, :priority, :created_at)
                    RETURNING interaction_id
                 """),
                {
                "client_id": company_id,
                "entity_type": "company",
                "contact_date": contact_date,
                "contact_time": contact_time,
                "contact_method": contact_method,
                "notes": formatted_notes,
                "subject": subject,
                "outcome": outcome,
                "duration_minutes": duration_minutes,
                "direction": direction,
                "due_date": due_date,
                "assignee_name": assignee_name,
                "priority": priority,
                "created_at": datetime.utcnow()
            }
        )
        new_interaction_id = result.fetchone()[0]
        session.commit()

        current_app.logger.info(
            f"✅ Interaction {new_interaction_id} created for company {company_id}: {interaction_type}"
        )

        return jsonify({
            'success': True,
            'interaction_id': new_interaction_id,
            'interaction_type': interaction_type,
            'message': f'{interaction_type} logged successfully'
        }), 201

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error creating company interaction: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


    # ═════════════════════════════════════════════════════════════════════════════
# ROUTE: PATCH /companies/<company_id>/interactions/<interaction_id>
# Partial update — only fields present in the request body are changed.
# The [interaction_type] prefix stored in `notes` is preserved from the
# existing row; only the text after it is replaced by the new `notes`
# value, so editing a Note/Task/etc. doesn't lose its type tag.
# ═════════════════════════════════════════════════════════════════════════════
@company_interactions_bp.route('/companies/<int:company_id>/interactions/<int:interaction_id>', methods=['PATCH', 'OPTIONS'])
@token_required
def update_company_interaction(company_id, interaction_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        company = get_tenant_company(session, company_id, request.current_user.tenant_id)
        if not company:
            return jsonify({'error': 'Company not found'}), 404


        existing = session.execute(
            text(f"""
                SELECT interaction_id, notes FROM "{SCHEMA}"."Client_Interactions"
                WHERE interaction_id = :iid AND client_id = :cid AND entity_type = 'company'
            """),
            {"iid": interaction_id, "cid": company_id}
            ).fetchone()
        if not existing:
            return jsonify({'error': 'Interaction not found'}), 404

        data = request.get_json() or {}
        errors = {}

        field_map = {
            'contact_time': 'contact_time',
            'subject': 'subject',
            'outcome': 'outcome',
            'duration_minutes': 'duration_minutes',
            'direction': 'direction',
            'due_date': 'due_date',
            'assignee_name': 'assignee_name',
            'priority': 'priority',
        }

        set_clauses = []
        params = {"iid": interaction_id}

        if 'contact_date' in data:
            parsed = parse_optional_date(data.get('contact_date'))
            set_clauses.append("contact_date = :contact_date")
            params["contact_date"] = parsed or datetime.utcnow().date()

        if 'contact_time' in data:
            set_clauses.append("contact_time = :contact_time")
            params["contact_time"] = parse_optional_time(data.get('contact_time'))

        if 'due_date' in data:
            set_clauses.append("due_date = :due_date")
            params["due_date"] = parse_optional_date(data.get('due_date'))

        if 'outcome' in data:
            outcome = data.get('outcome')
            if outcome and outcome not in CALL_OUTCOMES:
                errors['outcome'] = f"Must be one of: {', '.join(sorted(CALL_OUTCOMES))}"
            set_clauses.append("outcome = :outcome")
            params["outcome"] = outcome

        if 'direction' in data:
            direction = data.get('direction')
            if direction and direction not in CALL_DIRECTIONS:
                errors['direction'] = f"Must be one of: {', '.join(sorted(CALL_DIRECTIONS))}"
            set_clauses.append("direction = :direction")
            params["direction"] = direction

        if 'priority' in data:
            priority = data.get('priority')
            if priority and priority not in TASK_PRIORITIES:
                errors['priority'] = f"Must be one of: {', '.join(sorted(TASK_PRIORITIES))}"
            set_clauses.append("priority = :priority")
            params["priority"] = priority

        if 'duration_minutes' in data:
            duration_raw = data.get('duration_minutes')
            duration_minutes = None
            if duration_raw not in (None, ''):
                try:
                    duration_minutes = int(duration_raw)
                except (TypeError, ValueError):
                    errors['duration_minutes'] = "Must be a whole number of minutes"
            set_clauses.append("duration_minutes = :duration_minutes")
            params["duration_minutes"] = duration_minutes

        if 'assignee_name' in data:
            set_clauses.append("assignee_name = :assignee_name")
            params["assignee_name"] = (data.get('assignee_name') or '').strip() or None

        if 'subject' in data:
            set_clauses.append("subject = :subject")
            params["subject"] = (data.get('subject') or '').strip() or None

        if errors:
            return jsonify({'error': 'Validation failed', 'details': errors}), 400

        if 'notes' in data:
            old_notes = existing.notes or ""
            interaction_type = "Other"
            if old_notes.startswith("["):
                end_bracket = old_notes.find("]")
                if end_bracket > 0:
                    interaction_type = old_notes[1:end_bracket]
            new_notes_text = (data.get('notes') or '').strip()
            set_clauses.append("notes = :notes")
            params["notes"] = f"[{interaction_type}] {new_notes_text}" if new_notes_text else f"[{interaction_type}]"

        if not set_clauses:
            return jsonify({'error': 'No updatable fields provided'}), 400

        session.execute(
            text(f"""
                UPDATE "{SCHEMA}"."Client_Interactions"
                SET {', '.join(set_clauses)}
                WHERE interaction_id = :iid
            """),
            params
        )
        session.commit()

        current_app.logger.info(f"✅ Company interaction {interaction_id} updated")
        return jsonify({'success': True, 'message': 'Interaction updated successfully'}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error updating company interaction: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()    


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /companies/<company_id>/interactions
# ═════════════════════════════════════════════════════════════════════════════
@company_interactions_bp.route('/companies/<int:company_id>/interactions', methods=['GET', 'OPTIONS'])
@token_required
def get_company_interactions(company_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        company = get_tenant_company(session, company_id, request.current_user.tenant_id)
        if not company:
            return jsonify({'error': 'Company not found'}), 404

        interactions = session.execute(
    text(f"""
        SELECT
            interaction_id, client_id, contact_date, contact_time,
            contact_method, notes, subject, outcome, duration_minutes,
            direction, due_date, assignee_name, priority,
            next_steps, reminder_date, created_at
        FROM "{SCHEMA}"."Client_Interactions"
        WHERE client_id = :cid
        AND entity_type = 'company'
        AND contact_method != 150
        ORDER BY contact_date DESC, created_at DESC
    """),
    {"cid": company_id}
).fetchall()

        method_labels = {
            1: "Phone", 2: "Email", 3: "WhatsApp", 4: "In-person",
            5: "Other", 6: "Task", 7: "Meeting",
        }

        result = []
        for row in interactions:
            interaction_type = "Other"
            notes_text = row.notes or ""

            if notes_text.startswith("["):
                end_bracket = notes_text.find("]")
                if end_bracket > 0:
                    interaction_type = notes_text[1:end_bracket]
                    notes_text = notes_text[end_bracket + 1:].strip()

            result.append({
                'interaction_id': row.interaction_id,
                'company_id': row.client_id,
                'client_id': row.client_id,
                'contact_date': row.contact_date.isoformat() if row.contact_date else None,
                'contact_time': row.contact_time.strftime('%H:%M') if row.contact_time else None,
                'contact_method': method_labels.get(row.contact_method, 'Other'),
                'contact_method_code': row.contact_method,
                'interaction_type': interaction_type,
                'notes': notes_text,
                'subject': row.subject,
                'outcome': row.outcome,
                'duration_minutes': row.duration_minutes,
                'direction': row.direction,
                'due_date': row.due_date.isoformat() if row.due_date else None,
                'assignee_name': row.assignee_name,
                'priority': row.priority,
                'next_steps': row.next_steps,
                'reminder_date': row.reminder_date.isoformat() if row.reminder_date else None,
                'created_at': row.created_at.isoformat() if row.created_at else None
            })

        return jsonify(result), 200

    except Exception as e:
        current_app.logger.error(f"❌ Error fetching company interactions: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: DELETE /companies/<company_id>/interactions/<interaction_id>
# ═════════════════════════════════════════════════════════════════════════════
@company_interactions_bp.route('/companies/<int:company_id>/interactions/<int:interaction_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_company_interaction(company_id, interaction_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        interaction = session.execute(
    text(f"""
        SELECT interaction_id FROM "{SCHEMA}"."Client_Interactions"
        WHERE interaction_id = :iid AND client_id = :cid AND entity_type = 'company'
    """),
    {"iid": interaction_id, "cid": company_id}
).fetchone()

        if not interaction:
            return jsonify({'error': 'Interaction not found'}), 404

        session.execute(
            text(f'DELETE FROM "{SCHEMA}"."Client_Interactions" WHERE interaction_id = :iid'),
            {"iid": interaction_id}
        )
        session.commit()

        current_app.logger.info(f"✅ Company interaction {interaction_id} deleted")

        return jsonify({'success': True, 'message': 'Interaction deleted successfully'}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error deleting company interaction: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()
