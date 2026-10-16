import traceback
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from sqlalchemy import text
from .auth_helpers import token_required
from ..db import SessionLocal

job_bp = Blueprint('jobs', __name__)

# Separator used to split description from notes inside project_description
NOTES_SEPARATOR = "||NOTES||"


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def parse_date(date_str):
    """Parse ISO or date-only string to a date object."""
    if not date_str:
        return None
    try:
        if 'T' in date_str:
            date_str = date_str.split('T')[0]
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        current_app.logger.warning(f"Invalid date format: {date_str}")
        return None


def split_description_notes(raw: str):
    """Split project_description into (description, notes)."""
    if not raw:
        return '', ''
    if NOTES_SEPARATOR in raw:
        parts = raw.split(NOTES_SEPARATOR, 1)
        return parts[0].strip(), parts[1].strip()
    return raw.strip(), ''


def join_description_notes(description: str, notes: str) -> str:
    """Combine description and notes back into project_description."""
    if notes:
        return f"{description}{NOTES_SEPARATOR}{notes}"
    return description or ''


def generate_job_reference(session, project_id: int) -> str:
    """
    Generate a job reference like SL-PRJ001.
    Uses the new project_id (auto-incremented by DB) as the base.
    Ensures uniqueness against existing project_title prefixes.
    """
    ref = f"SL-PRJ{project_id:03d}"

    # Verify no collision (edge case after deletions)
    existing = session.execute(
        text("""
            SELECT project_id FROM "streemLyne_mt_dev2"."Project_Details"
            WHERE project_title LIKE :ref
            LIMIT 1
        """),
        {"ref": f"{ref}%"}
    ).fetchone()

    if existing and existing.project_id != project_id:
        ref = f"SL-PRJ{project_id:04d}"

    return ref


def serialize_project(row) -> dict:
    """Serialize a Project_Details row (with optional joined fields) to dict."""
    description, notes = split_description_notes(row.project_description)

    # Extract job_number from project_title — stored as "SL-PRJ001 | Title text"
    title_parts = (row.project_title or '').split(' | ', 1)
    job_number  = title_parts[0].strip() if title_parts else f"SL-PRJ{row.project_id:03d}"
    description_title = title_parts[1].strip() if len(title_parts) > 1 else description

    return {
        # Legacy aliases (keep frontend working)
        'id':          row.project_id,
        'job_number':  job_number,
        'customer_id': row.client_id,
        'description': description_title or description,
        'status':      row._mapping.get("Misc_Col1") or 'Pending',
        'notes':       notes,
        # New field names
        'project_id':          row.project_id,
        'client_id':           row.client_id,
        'project_title':       row.project_title,
        'project_description': row.project_description,
        'employee_id':         row.employee_id,
        'opportunity_id':      row.opportunity_id,
        # Dates
        'start_date': row.start_date.isoformat() if row.start_date else None,
        'end_date':   row.end_date.isoformat()   if row.end_date   else None,
        'created_at': row.created_at.isoformat() if row.created_at else None,
        'updated_at': row.updated_at.isoformat() if row.updated_at else None,
        # Joined
        'client_name':   getattr(row, 'client_company_name', None),
        'customer_name': getattr(row, 'client_company_name', None),  # legacy alias
    }


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /jobs
# ═════════════════════════════════════════════════════════════════════════════
@job_bp.route('/jobs', methods=['GET', 'OPTIONS'])
@token_required
def get_jobs():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        # Accept both client_id (new) and customer_id (legacy)
        client_id = request.args.get('client_id') or request.args.get('customer_id')
        status    = request.args.get('status')

        query  = """
            SELECT pd.*, cm.client_company_name
            FROM "streemLyne_mt_dev2"."Project_Details" pd
            LEFT JOIN "streemLyne_mt_dev2"."Client_Master" cm ON cm.client_id = pd.client_id
            WHERE 1=1
        """
        params = {}

        if client_id:
            query += " AND pd.client_id = :client_id"
            params["client_id"] = client_id

        if status:
            query += ' AND pd."Misc_Col1" = :status'
            params["status"] = status

        query += " ORDER BY pd.created_at DESC"

        rows = session.execute(text(query), params).fetchall()

        current_app.logger.info(f"✅ Returning {len(rows)} projects")
        return jsonify([serialize_project(row) for row in rows]), 200

    except Exception as e:
        current_app.logger.error(f"Error fetching jobs: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /jobs/<project_id>
# ═════════════════════════════════════════════════════════════════════════════
@job_bp.route('/jobs/<int:project_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_job(project_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        row = session.execute(
            text("""
                SELECT pd.*, cm.client_company_name
                FROM "streemLyne_mt_dev2"."Project_Details" pd
                LEFT JOIN "streemLyne_mt_dev2"."Client_Master" cm ON cm.client_id = pd.client_id
                WHERE pd.project_id = :pid
            """),
            {"pid": project_id}
        ).fetchone()

        if not row:
            return jsonify({'error': 'Job not found'}), 404

        return jsonify(serialize_project(row)), 200

    except Exception as e:
        current_app.logger.error(f"Error fetching job {project_id}: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: POST /jobs
# ═════════════════════════════════════════════════════════════════════════════
@job_bp.route('/jobs', methods=['POST'])
@token_required
def create_job():
    session = SessionLocal()
    try:
        data = request.get_json()
        current_app.logger.info(f"📥 Create job data: {data}")

        # Accept client_id or legacy customer_id
        client_id = data.get('client_id') or data.get('customer_id')
        if not client_id:
            return jsonify({'error': 'client_id is required'}), 400

        # Validate client exists
        client_row = session.execute(
            text('SELECT client_id, client_company_name FROM "streemLyne_mt_dev2"."Client_Master" WHERE client_id = :cid'),
            {"cid": client_id}
        ).fetchone()
        if not client_row:
            return jsonify({'error': 'Client not found'}), 404

        # Resolve employee_id from current user
        employee_id = getattr(request.current_user, 'employee_id', None)

        # Resolve opportunity_id if provided
        opportunity_id = data.get('opportunity_id')
        if not opportunity_id:
            # Auto-link to latest opportunity for this client
            opp_row = session.execute(
                text("""
                    SELECT opportunity_id FROM "streemLyne_mt_dev2"."Opportunity_Details"
                    WHERE client_id = :cid
                    ORDER BY created_at DESC LIMIT 1
                """),
                {"cid": client_id}
            ).fetchone()
            if opp_row:
                opportunity_id = opp_row.opportunity_id

        description = data.get('description', '')
        notes       = data.get('notes', '')
        status      = data.get('status', 'Pending')
        start_date  = parse_date(data.get('start_date'))
        end_date    = parse_date(data.get('end_date'))

        # tenant_id is NOT NULL on dev with no default — resolve from the current user
        tenant_id = getattr(request.current_user, 'tenant_id', None)
        if not tenant_id:
            return jsonify({'error': 'Unable to resolve tenant_id for current user'}), 400

        # Insert — we need project_id back to build the job reference
        result = session.execute(
            text("""
                INSERT INTO "streemLyne_mt_dev2"."Project_Details"
                    (client_id, opportunity_id, project_title, project_description,
                     start_date, end_date, employee_id, created_at, updated_at,
                     "Misc_Col1", tenant_id)
                VALUES
                    (:client_id, :opportunity_id, :project_title, :project_description,
                     :start_date, :end_date, :employee_id, :created_at, :updated_at,
                     :status, :tenant_id)
                RETURNING project_id
            """),
            {
                "client_id":           client_id,
                "opportunity_id":      opportunity_id,
                "project_title":       "__PENDING__",   # updated below with real reference
                "project_description": join_description_notes(description, notes),
                "start_date":          start_date,
                "end_date":            end_date,
                "employee_id":         employee_id,
                "created_at":          datetime.utcnow(),
                "updated_at":          datetime.utcnow(),
                "status":              status,
                "tenant_id":           tenant_id,
            }
        )
        new_project_id = result.fetchone().project_id

        # Build final job reference and title now that we have the ID
        job_number    = data.get('job_number') or generate_job_reference(session, new_project_id)
        project_title = f"{job_number} | {description[:80]}" if description else job_number

        session.execute(
            text('UPDATE "streemLyne_mt_dev2"."Project_Details" SET project_title = :title WHERE project_id = :pid'),
            {"title": project_title, "pid": new_project_id}
        )
        session.commit()

        # Fetch full row for response
        row = session.execute(
            text("""
                SELECT pd.*, cm.client_company_name
                FROM "streemLyne_mt_dev2"."Project_Details" pd
                LEFT JOIN "streemLyne_mt_dev2"."Client_Master" cm ON cm.client_id = pd.client_id
                WHERE pd.project_id = :pid
            """),
            {"pid": new_project_id}
        ).fetchone()

        current_app.logger.info(f"✅ Project created: {new_project_id} ({job_number})")
        return jsonify(serialize_project(row)), 201

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error creating job: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: PUT /jobs/<project_id>
# ═════════════════════════════════════════════════════════════════════════════
@job_bp.route('/jobs/<int:project_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_job(project_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        row = session.execute(
            text('SELECT * FROM "streemLyne_mt_dev2"."Project_Details" WHERE project_id = :pid'),
            {"pid": project_id}
        ).fetchone()

        if not row:
            return jsonify({'error': 'Job not found'}), 404

        data    = request.get_json()
        updates = {}

        # Description / notes — both live in project_description
        current_desc, current_notes = split_description_notes(row.project_description)
        new_desc  = data.get('description', current_desc)
        new_notes = data.get('notes', current_notes)

        if 'description' in data or 'notes' in data:
            updates['project_description'] = join_description_notes(new_desc, new_notes)

        # Rebuild project_title if description changed
        if 'description' in data:
            title_parts = (row.project_title or '').split(' | ', 1)
            job_number  = title_parts[0].strip() if title_parts else f"SL-PRJ{project_id:03d}"
            updates['project_title'] = f"{job_number} | {new_desc[:80]}" if new_desc else job_number

        if 'status' in data:
            updates['"Misc_Col1"'] = data['status']

        if 'start_date' in data:
            updates['start_date'] = parse_date(data['start_date'])

        if 'end_date' in data:
            updates['end_date'] = parse_date(data['end_date'])

        updates['updated_at'] = datetime.utcnow()

        if updates:
            set_clauses = ', '.join([f'{k} = :{k.strip(chr(34))}' for k in updates])
            clean_params = {k.strip('"'): v for k, v in updates.items()}
            clean_params['pid'] = project_id

            session.execute(
                text(f'UPDATE "streemLyne_mt_dev2"."Project_Details" SET {set_clauses} WHERE project_id = :pid'),
                clean_params
            )
            session.commit()

        updated_row = session.execute(
            text("""
                SELECT pd.*, cm.client_company_name
                FROM "streemLyne_mt_dev2"."Project_Details" pd
                LEFT JOIN "streemLyne_mt_dev2"."Client_Master" cm ON cm.client_id = pd.client_id
                WHERE pd.project_id = :pid
            """),
            {"pid": project_id}
        ).fetchone()

        current_app.logger.info(f"✅ Project {project_id} updated")
        return jsonify(serialize_project(updated_row)), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error updating job {project_id}: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: DELETE /jobs/<project_id>
# Deletes linked Client_Interactions (assignments) first, then the project
# ═════════════════════════════════════════════════════════════════════════════
@job_bp.route('/jobs/<int:project_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_job(project_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        row = session.execute(
            text('SELECT project_id FROM "streemLyne_mt_dev2"."Project_Details" WHERE project_id = :pid'),
            {"pid": project_id}
        ).fetchone()

        if not row:
            return jsonify({'error': 'Job not found'}), 404

        current_app.logger.info(f"🗑️ Deleting project {project_id} and linked interactions")

        # Delete linked assignment interactions where meta project_id matches
        # We use a LIKE match on the notes JSON meta (same pattern as assignment_routes.py)
        session.execute(
            text("""
                DELETE FROM "streemLyne_mt_dev2"."Client_Interactions"
                WHERE notes LIKE :pattern
            """),
            {"pattern": f'%"project_id": {project_id}%'}
        )

        # Delete the project
        session.execute(
            text('DELETE FROM "streemLyne_mt_dev2"."Project_Details" WHERE project_id = :pid'),
            {"pid": project_id}
        )
        session.commit()

        current_app.logger.info(f"✅ Project {project_id} deleted")
        return jsonify({'message': 'Job deleted successfully'}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error deleting job {project_id}: {e}")
        traceback.print_exc()
        return jsonify({'error': f"Failed to delete job: {str(e)}"}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /jobs/stats
# ═════════════════════════════════════════════════════════════════════════════
@job_bp.route('/jobs/stats', methods=['GET', 'OPTIONS'])
@token_required
def get_job_stats():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        total = session.execute(
            text('SELECT COUNT(*) FROM "streemLyne_mt_dev2"."Project_Details"')
        ).scalar()

        status_rows = session.execute(
            text("""
                SELECT "Misc_Col1" AS status, COUNT(*) AS cnt
                FROM "streemLyne_mt_dev2"."Project_Details"
                GROUP BY "Misc_Col1"
            """)
        ).fetchall()

        by_status = {
            (row.status or 'Unknown'): row.cnt
            for row in status_rows
        }

        return jsonify({
            'total_jobs': total,
            'by_status':  by_status
        }), 200

    except Exception as e:
        current_app.logger.error(f"Error fetching job stats: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: PATCH /jobs/<project_id>/status
# ═════════════════════════════════════════════════════════════════════════════
@job_bp.route('/jobs/<int:project_id>/status', methods=['PATCH', 'OPTIONS'])
@token_required
def update_job_status(project_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        row = session.execute(
            text('SELECT * FROM "streemLyne_mt_dev2"."Project_Details" WHERE project_id = :pid'),
            {"pid": project_id}
        ).fetchone()

        if not row:
            return jsonify({'error': 'Job not found'}), 404

        data = request.get_json()
        if not data.get('status'):
            return jsonify({'error': 'Status is required'}), 400

        old_status = row._mapping.get("Misc_Col1") or 'Pending'
        new_status = data['status']

        updates = {
            "status":     new_status,
            "updated_at": datetime.utcnow(),
            "pid":        project_id
        }

        # Optionally append status change note to project_description
        if data.get('add_note'):
            current_desc, current_notes = split_description_notes(row.project_description)
            note_entry = (
                f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')}] "
                f"Status changed from '{old_status}' to '{new_status}'"
            )
            new_notes = f"{current_notes}\n{note_entry}".strip() if current_notes else note_entry
            updates["project_description"] = join_description_notes(current_desc, new_notes)

        set_clauses = []
        params      = {"pid": project_id}
        for k, v in updates.items():
            if k == 'pid':
                continue
            if k == 'status':
                set_clauses.append('"Misc_Col1" = :status')
            else:
                set_clauses.append(f'"{k}" = :{k}')
            params[k] = v

        session.execute(
            text(f'UPDATE "streemLyne_mt_dev2"."Project_Details" SET {", ".join(set_clauses)} WHERE project_id = :pid'),
            params
        )
        session.commit()

        updated_row = session.execute(
            text("""
                SELECT pd.*, cm.client_company_name
                FROM "streemLyne_mt_dev2"."Project_Details" pd
                LEFT JOIN "streemLyne_mt_dev2"."Client_Master" cm ON cm.client_id = pd.client_id
                WHERE pd.project_id = :pid
            """),
            {"pid": project_id}
        ).fetchone()

        current_app.logger.info(f"✅ Project {project_id} status: {old_status} → {new_status}")
        return jsonify(serialize_project(updated_row)), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error updating status for job {project_id}: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()