from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from sqlalchemy import text
from .auth_helpers import token_required
from ..db import SessionLocal

assignment_bp = Blueprint('assignments', __name__)

# ─────────────────────────────────────────────
# VALID ASSIGNMENT FIELDS
# ─────────────────────────────────────────────
VALID_ASSIGNMENT_FIELDS = [
    'type', 'title', 'date', 'start_date', 'end_date', 'client_id',
    'client_name', 'employee_id', 'team_member', 'project_id',
    'start_time', 'end_time', 'estimated_hours',
    'notes', 'next_steps', 'priority', 'status', 'reminder_date',
    'contact_method'
]


def filter_assignment_data(data):
    """Filter request data to only include valid assignment fields."""
    return {key: data[key] for key in VALID_ASSIGNMENT_FIELDS if key in data}


# ─────────────────────────────────────────────
# HELPER: Get employee name from Employee_Master
# ─────────────────────────────────────────────
def get_employee_name(session, employee_id):
    if not employee_id:
        return None
    row = session.execute(
        text('SELECT employee_name FROM "streemLyne_mt_dev2"."Employee_Master" WHERE employee_id = :eid'),
        {"eid": employee_id}
    ).fetchone()
    return row.employee_name if row else None


# ─────────────────────────────────────────────
# HELPER: Get client name from Client_Master
# ─────────────────────────────────────────────
def get_client_name(session, client_id):
    if not client_id:
        return None
    row = session.execute(
        text('SELECT client_company_name FROM "streemLyne_mt_dev2"."Client_Master" WHERE client_id = :cid'),
        {"cid": client_id}
    ).fetchone()
    return row.client_company_name if row else None


# ─────────────────────────────────────────────
# HELPER: Get project info from Project_Details
# ─────────────────────────────────────────────
def get_project_info(session, project_id):
    if not project_id:
        return None
    row = session.execute(
        text("""
            SELECT project_id, project_title, project_description,
                   start_date, end_date, client_id
            FROM "streemLyne_mt_dev2"."Project_Details"
            WHERE project_id = :pid
        """),
        {"pid": project_id}
    ).fetchone()
    if not row:
        return None
    return {
        "project_id": row.project_id,
        "project_title": row.project_title,
        "project_description": row.project_description,
        "start_date": row.start_date.isoformat() if row.start_date else None,
        "end_date": row.end_date.isoformat() if row.end_date else None,
        "client_id": row.client_id
    }


# ─────────────────────────────────────────────
# HELPER: Check if current user is Admin
# Reads role_ids (comma-separated) from Employee_Master,
# then checks Role_Master for role_name = 'Admin'
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

        role_id_list = [r.strip() for r in str(row.role_ids).split(',') if r.strip()]
        if not role_id_list:
            return False

        placeholders = ', '.join([f':r{i}' for i in range(len(role_id_list))])
        params = {f'r{i}': int(rid) for i, rid in enumerate(role_id_list) if rid.isdigit()}

        if not params:
            return False

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
# HELPER: Serialize an interaction row to dict
# ─────────────────────────────────────────────
def interaction_to_dict(row, session):
    """Convert a Client_Interactions row to a response dict."""
    result = {
        "id": row.interaction_id,
        "interaction_id": row.interaction_id,
        "client_id": row.client_id,
        "contact_date": row.contact_date.isoformat() if row.contact_date else None,
        "contact_method": row.contact_method,
        "notes": row.notes,
        "next_steps": row.next_steps,
        "reminder_date": row.reminder_date.isoformat() if row.reminder_date else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }

    # Enrich with client name
    result["client_name"] = get_client_name(session, row.client_id)

    # Map schema fields back to legacy frontend field names for compatibility
    result["date"] = result["contact_date"]
    result["start_date"] = result["contact_date"]
    result["end_date"] = result["reminder_date"]

    return result


# ─────────────────────────────────────────────
# PARSE DATE HELPER
# ─────────────────────────────────────────────
def parse_date(value, field_name):
    """Parse a date string, returning (date_obj, error_response)."""
    if not value:
        return None, None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date(), None
    except Exception:
        return None, (jsonify({'error': f'Invalid {field_name} format. Use YYYY-MM-DD'}), 400)


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /assignments  &  POST /assignments
# Maps to Client_Interactions table
# ═════════════════════════════════════════════════════════════════════════════
@assignment_bp.route('/assignments', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_assignments():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    current_user = request.current_user
    session = SessionLocal()

    try:
        # ── POST: Create new interaction/assignment ──────────────────────────
        if request.method == 'POST':
            data = request.json
            current_app.logger.info(f"📥 RAW data received: {data}")
            data = filter_assignment_data(data)
            current_app.logger.info(f"📥 Creating assignment with filtered data: {data}")

            # Resolve contact_date / start_date / date
            contact_date = None
            if data.get('start_date'):
                contact_date, err = parse_date(data['start_date'], 'start_date')
                if err:
                    return err
            elif data.get('date'):
                contact_date, err = parse_date(data['date'], 'date')
                if err:
                    return err
            elif data.get('contact_date'):
                contact_date, err = parse_date(data['contact_date'], 'contact_date')
                if err:
                    return err

            if not contact_date:
                return jsonify({'error': 'start_date or date is required'}), 400

            # reminder_date maps to end_date
            reminder_date = None
            if data.get('end_date'):
                reminder_date, err = parse_date(data['end_date'], 'end_date')
                if err:
                    return err
            elif data.get('reminder_date'):
                reminder_date, err = parse_date(data['reminder_date'], 'reminder_date')
                if err:
                    return err
            else:
                reminder_date = contact_date

            # Resolve client_id — accept either client_id or legacy customer_id
            client_id = data.get('client_id') or data.get('customer_id')

            # Resolve client_name if not provided
            client_name = data.get('client_name') or data.get('customer_name')
            if client_id and not client_name:
                client_name = get_client_name(session, client_id)

            # Resolve employee (assigned user)
            employee_id = data.get('employee_id') or data.get('user_id')
            team_member = data.get('team_member')
            if employee_id and not team_member:
                team_member = get_employee_name(session, employee_id)

            # Build notes: prefix with extra fields not in schema
            extra = {}
            for field in ['type', 'title', 'start_time', 'end_time',
                          'estimated_hours', 'priority', 'status',
                          'project_id', 'employee_id', 'team_member',
                          'client_name']:
                val = data.get(field) or (team_member if field == 'team_member' else None) \
                      or (client_name if field == 'client_name' else None) \
                      or (employee_id if field == 'employee_id' else None)
                if val is not None:
                    extra[field] = val

            # Merge extra info as JSON prefix in notes
            import json
            base_notes = data.get('notes', '')
            notes_with_meta = f"__meta__{json.dumps(extra)}__end_meta__{base_notes}" if extra else base_notes

            # contact_method: default to 1 (e.g. "In Person") if not provided
            contact_method = data.get('contact_method', 1)

            # next_steps field
            next_steps = data.get('next_steps', '')

            session.execute(
                text("""
                    INSERT INTO "streemLyne_mt_dev2"."Client_Interactions"
                        (client_id, contact_date, contact_method, notes,
                         next_steps, reminder_date, created_at)
                    VALUES
                        (:client_id, :contact_date, :contact_method, :notes,
                         :next_steps, :reminder_date, :created_at)
                """),
                {
                    "client_id": client_id,
                    "contact_date": contact_date,
                    "contact_method": contact_method,
                    "notes": notes_with_meta,
                    "next_steps": next_steps,
                    "reminder_date": reminder_date,
                    "created_at": datetime.utcnow()
                }
            )
            session.commit()

            # Fetch the newly created row
            new_row = session.execute(
                text("""
                    SELECT * FROM "streemLyne_mt_dev2"."Client_Interactions"
                    WHERE client_id = :client_id
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"client_id": client_id}
            ).fetchone()

            result = interaction_to_dict(new_row, session) if new_row else {}
            result['created_by_employee_id'] = current_user.id

            current_app.logger.info(f"✅ Assignment (interaction) created: {result.get('interaction_id')}")
            return jsonify({
                'message': 'Assignment created successfully',
                'assignment': result
            }), 201

        # ── GET: Fetch all interactions/assignments ──────────────────────────
        if request.method == 'GET':
            current_app.logger.info(
                f"📋 Fetching all assignments. Requester employee_id: {current_user.id}"
            )

            rows = session.execute(
                text("""
                    SELECT ci.*, cm.client_company_name
                    FROM "streemLyne_mt_dev2"."Client_Interactions" ci
                    LEFT JOIN "streemLyne_mt_dev2"."Client_Master" cm ON cm.client_id = ci.client_id
                    ORDER BY ci.contact_date DESC
                """)
            ).fetchall()

            result = []
            for row in rows:
                try:
                    d = {
                        "id": row.interaction_id,
                        "interaction_id": row.interaction_id,
                        "client_id": row.client_id,
                        "client_name": row.client_company_name,
                        "contact_date": row.contact_date.isoformat() if row.contact_date else None,
                        "contact_method": row.contact_method,
                        "notes": row.notes,
                        "next_steps": row.next_steps,
                        "reminder_date": row.reminder_date.isoformat() if row.reminder_date else None,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                        # Legacy frontend compatibility aliases
                        "date": row.contact_date.isoformat() if row.contact_date else None,
                        "start_date": row.contact_date.isoformat() if row.contact_date else None,
                        "end_date": row.reminder_date.isoformat() if row.reminder_date else None,
                    }
                    result.append(d)
                except Exception as e:
                    current_app.logger.error(f"Error serializing interaction {row.interaction_id}: {e}")
                    continue

            current_app.logger.info(f"✅ Returning {len(result)} assignments")
            return jsonify(result), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error in handle_assignments: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET/PUT/DELETE /assignments/<id>
# ═════════════════════════════════════════════════════════════════════════════
@assignment_bp.route('/assignments/<int:interaction_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@token_required
def handle_single_assignment(interaction_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    current_user = request.current_user
    session = SessionLocal()

    try:
        # Fetch the record
        row = session.execute(
            text("""
                SELECT ci.*, cm.client_company_name
                FROM "streemLyne_mt_dev2"."Client_Interactions" ci
                LEFT JOIN "streemLyne_mt_dev2"."Client_Master" cm ON cm.client_id = ci.client_id
                WHERE ci.interaction_id = :iid
            """),
            {"iid": interaction_id}
        ).fetchone()

        if not row:
            current_app.logger.error(f"❌ Assignment/Interaction {interaction_id} not found")
            return jsonify({'error': 'Assignment not found'}), 404

        # ── GET ──────────────────────────────────────────────────────────────
        if request.method == 'GET':
            result = {
                "id": row.interaction_id,
                "interaction_id": row.interaction_id,
                "client_id": row.client_id,
                "client_name": row.client_company_name,
                "contact_date": row.contact_date.isoformat() if row.contact_date else None,
                "contact_method": row.contact_method,
                "notes": row.notes,
                "next_steps": row.next_steps,
                "reminder_date": row.reminder_date.isoformat() if row.reminder_date else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "date": row.contact_date.isoformat() if row.contact_date else None,
                "start_date": row.contact_date.isoformat() if row.contact_date else None,
                "end_date": row.reminder_date.isoformat() if row.reminder_date else None,
            }
            return jsonify(result), 200

        # ── Authorization for PUT / DELETE ────────────────────────────────────
        if request.method in ['PUT', 'DELETE']:
            user_is_admin = is_admin(session, current_user.id)
            if not user_is_admin:
                # Non-admins can only modify interactions they created (matched via client scope)
                # Since Client_Interactions has no created_by column, allow if client matches
                # or deny entirely — adjust this logic to your business rules
                current_app.logger.warning(
                    f"Non-admin user {current_user.id} attempting to modify interaction {interaction_id}"
                )
                # Permissive default: allow (tighten once created_by is added to schema)
                pass

        # ── PUT: Update ───────────────────────────────────────────────────────
        if request.method == 'PUT':
            data = request.json
            current_app.logger.info(f"📝 RAW update data for interaction {interaction_id}: {data}")
            data = filter_assignment_data(data)

            updates = {}

            # contact_date (maps from start_date / date)
            if data.get('start_date'):
                d, err = parse_date(data['start_date'], 'start_date')
                if err:
                    return err
                updates['contact_date'] = d
            elif data.get('date'):
                d, err = parse_date(data['date'], 'date')
                if err:
                    return err
                updates['contact_date'] = d
            elif data.get('contact_date'):
                d, err = parse_date(data['contact_date'], 'contact_date')
                if err:
                    return err
                updates['contact_date'] = d

            # reminder_date (maps from end_date)
            if data.get('end_date'):
                d, err = parse_date(data['end_date'], 'end_date')
                if err:
                    return err
                updates['reminder_date'] = d
            elif data.get('reminder_date'):
                d, err = parse_date(data['reminder_date'], 'reminder_date')
                if err:
                    return err
                updates['reminder_date'] = d

            if 'contact_method' in data:
                updates['contact_method'] = data['contact_method']

            if 'next_steps' in data:
                updates['next_steps'] = data['next_steps']

            # Rebuild notes with meta if extended fields are present
            import json
            extra_fields = ['type', 'title', 'start_time', 'end_time',
                            'estimated_hours', 'priority', 'status',
                            'project_id', 'employee_id', 'team_member', 'client_name']
            extra = {f: data[f] for f in extra_fields if f in data and data[f] is not None}

            if 'notes' in data or extra:
                base_notes = data.get('notes', row.notes or '')
                # Strip old meta if present
                if base_notes and '__meta__' in base_notes:
                    parts = base_notes.split('__end_meta__')
                    base_notes = parts[1] if len(parts) > 1 else base_notes

                # Re-parse existing meta and merge
                existing_meta = {}
                if row.notes and '__meta__' in row.notes:
                    try:
                        meta_str = row.notes.split('__meta__')[1].split('__end_meta__')[0]
                        existing_meta = json.loads(meta_str)
                    except Exception:
                        pass
                existing_meta.update(extra)

                updates['notes'] = (
                    f"__meta__{json.dumps(existing_meta)}__end_meta__{base_notes}"
                    if existing_meta else base_notes
                )

            if 'client_id' in data:
                updates['client_id'] = data['client_id']

            if not updates:
                return jsonify({'message': 'No valid fields to update'}), 200

            # Build dynamic SET clause
            set_clauses = ', '.join([f'"{k}" = :{k}' for k in updates])
            updates['iid'] = interaction_id

            session.execute(
                text(f'UPDATE "streemLyne_mt_dev2"."Client_Interactions" SET {set_clauses} WHERE interaction_id = :iid'),
                updates
            )
            session.commit()

            # Fetch updated row
            updated = session.execute(
                text("""
                    SELECT ci.*, cm.client_company_name
                    FROM "streemLyne_mt_dev2"."Client_Interactions" ci
                    LEFT JOIN "streemLyne_mt_dev2"."Client_Master" cm ON cm.client_id = ci.client_id
                    WHERE ci.interaction_id = :iid
                """),
                {"iid": interaction_id}
            ).fetchone()

            result = {
                "id": updated.interaction_id,
                "interaction_id": updated.interaction_id,
                "client_id": updated.client_id,
                "client_name": updated.client_company_name,
                "contact_date": updated.contact_date.isoformat() if updated.contact_date else None,
                "contact_method": updated.contact_method,
                "notes": updated.notes,
                "next_steps": updated.next_steps,
                "reminder_date": updated.reminder_date.isoformat() if updated.reminder_date else None,
                "created_at": updated.created_at.isoformat() if updated.created_at else None,
                "date": updated.contact_date.isoformat() if updated.contact_date else None,
                "start_date": updated.contact_date.isoformat() if updated.contact_date else None,
                "end_date": updated.reminder_date.isoformat() if updated.reminder_date else None,
            }
            current_app.logger.info(f"✅ Assignment (interaction) {interaction_id} updated")
            return jsonify({'message': 'Assignment updated successfully', 'assignment': result}), 200

        # ── DELETE ────────────────────────────────────────────────────────────
        if request.method == 'DELETE':
            current_app.logger.info(f"🗑️ Deleting interaction {interaction_id}")
            session.execute(
                text('DELETE FROM "streemLyne_mt_dev2"."Client_Interactions" WHERE interaction_id = :iid'),
                {"iid": interaction_id}
            )
            session.commit()
            current_app.logger.info(f"✅ Interaction {interaction_id} deleted")
            return jsonify({'message': 'Assignment deleted successfully', 'id': interaction_id}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error in handle_single_assignment: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /assignments/by-date-range
# ═════════════════════════════════════════════════════════════════════════════
@assignment_bp.route('/assignments/by-date-range', methods=['GET', 'OPTIONS'])
@token_required
def get_assignments_by_date_range():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    if not start_date or not end_date:
        return jsonify({'error': 'start_date and end_date are required'}), 400

    start, err = parse_date(start_date, 'start_date')
    if err:
        return err
    end, err = parse_date(end_date, 'end_date')
    if err:
        return err

    session = SessionLocal()
    try:
        current_app.logger.info(f"📅 Fetching assignments from {start} to {end}")

        rows = session.execute(
            text("""
                SELECT ci.*, cm.client_company_name
                FROM "streemLyne_mt_dev2"."Client_Interactions" ci
                LEFT JOIN "streemLyne_mt_dev2"."Client_Master" cm ON cm.client_id = ci.client_id
                WHERE ci.contact_date >= :start AND ci.contact_date <= :end
                ORDER BY ci.contact_date ASC
            """),
            {"start": start, "end": end}
        ).fetchall()

        current_app.logger.info(f"✅ Found {len(rows)} assignments in date range")

        result = []
        for row in rows:
            try:
                result.append({
                    "id": row.interaction_id,
                    "interaction_id": row.interaction_id,
                    "client_id": row.client_id,
                    "client_name": row.client_company_name,
                    "contact_date": row.contact_date.isoformat() if row.contact_date else None,
                    "contact_method": row.contact_method,
                    "notes": row.notes,
                    "next_steps": row.next_steps,
                    "reminder_date": row.reminder_date.isoformat() if row.reminder_date else None,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "date": row.contact_date.isoformat() if row.contact_date else None,
                    "start_date": row.contact_date.isoformat() if row.contact_date else None,
                    "end_date": row.reminder_date.isoformat() if row.reminder_date else None,
                })
            except Exception as e:
                current_app.logger.error(f"Error processing interaction {row.interaction_id}: {e}")
                continue

        return jsonify(result), 200

    except Exception as e:
        current_app.logger.error(f"Error in get_assignments_by_date_range: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 400
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /jobs/available
# Maps to Project_Details (non-completed projects)
# ═════════════════════════════════════════════════════════════════════════════
@assignment_bp.route('/jobs/available', methods=['GET', 'OPTIONS'])
@token_required
def get_available_jobs():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        current_app.logger.info("📋 Fetching available projects (jobs)...")

        # Project_Details has no 'status' column — use Misc_Col1 for status
        # or return all projects; adjust filter as needed
        rows = session.execute(
            text("""
                SELECT pd.project_id, pd.project_title, pd.project_description,
                       pd.start_date, pd.end_date, pd.client_id,
                       pd.misc_col1 AS status,
                       cm.client_company_name
                FROM "streemLyne_mt_dev2"."Project_Details" pd
                LEFT JOIN "streemLyne_mt_dev2"."Client_Master" cm ON cm.client_id = pd.client_id
                WHERE pd.misc_col1 NOT IN ('Completed', 'Cancelled')
                   OR pd.misc_col1 IS NULL
                ORDER BY pd.project_id DESC
            """)
        ).fetchall()

        current_app.logger.info(f"✅ Found {len(rows)} available projects")

        result = []
        for row in rows:
            try:
                result.append({
                    'id': row.project_id,
                    'job_number': row.project_id,           # legacy alias
                    'project_id': row.project_id,
                    'title': row.project_title,
                    'description': row.project_description or '',
                    'client_name': row.client_company_name or 'Unknown',
                    'client_id': row.client_id,
                    'status': row.status or 'Active',
                    'start_date': row.start_date.isoformat() if row.start_date else None,
                    'end_date': row.end_date.isoformat() if row.end_date else None,
                })
            except Exception as e:
                current_app.logger.error(f"Error processing project {row.project_id}: {e}")
                continue

        current_app.logger.info(f"✅ Returning {len(result)} projects")
        return jsonify(result), 200

    except Exception as e:
        current_app.logger.error(f"❌ Error in get_available_jobs: {e}")
        import traceback
        traceback.print_exc()
        return jsonify([]), 200
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /clients/active
# Maps to Client_Master
# ═════════════════════════════════════════════════════════════════════════════
@assignment_bp.route('/clients/active', methods=['GET', 'OPTIONS'])
@token_required
def get_active_clients():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        current_app.logger.info("📋 Fetching active clients...")

        rows = session.execute(
            text("""
                SELECT cm.client_id, cm.client_company_name, cm.client_contact_name,
                       cm.address, cm.client_phone, cm.client_email,
                       cm.client_website, co.country_name
                FROM "streemLyne_mt_dev2"."Client_Master" cm
                LEFT JOIN "streemLyne_mt_dev2"."Country_Master" co ON co.country_id = cm.country_id
                ORDER BY cm.client_company_name ASC
            """)
        ).fetchall()

        current_app.logger.info(f"✅ Found {len(rows)} clients")

        result = []
        for row in rows:
            try:
                result.append({
                    'id': row.client_id,                         # legacy alias
                    'client_id': row.client_id,
                    'name': row.client_company_name,             # legacy alias
                    'client_company_name': row.client_company_name,
                    'client_contact_name': row.client_contact_name,
                    'address': row.address or '',
                    'phone': row.client_phone or '',             # legacy alias
                    'client_phone': row.client_phone or '',
                    'email': row.client_email or '',             # legacy alias
                    'client_email': row.client_email or '',
                    'client_website': row.client_website or '',
                    'country': row.country_name or '',
                })
            except Exception as e:
                current_app.logger.error(f"Error processing client {row.client_id}: {e}")
                continue

        current_app.logger.info(f"✅ Returning {len(result)} clients")
        return jsonify(result), 200

    except Exception as e:
        current_app.logger.error(f"❌ Error in get_active_clients: {e}")
        import traceback
        traceback.print_exc()
        return jsonify([]), 200
    finally:
        session.close()