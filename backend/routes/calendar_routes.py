"""
Calendar / Assignment Routes
Handles scheduling of tasks, meetings, calls, deliveries, and notes
against the Tasks_Master table for the current tenant.

Endpoints:
  GET    /api/assignments              — list (filter by month, project_id, client_id)
  POST   /api/assignments              — create
  GET    /api/assignments/<id>         — get single
  PUT    /api/assignments/<id>         — update
  DELETE /api/assignments/<id>         — delete

Backed by:  "StreemLyne_MT"."Tasks_Master"

Field mapping (frontend → Tasks_Master column):
  frontend.staff_name  → team_member
  frontend.job_id      → project_id
  frontend.customer_id → client_id
  frontend.id          → task_id  (UUID string)

Month filtering uses start_date (indexed) rather than the date column.
"""

from flask import Blueprint, request, jsonify, g
from sqlalchemy import text
from datetime import datetime, date

from database import db
from middleware import auth_required

calendar_bp = Blueprint('calendar', __name__, url_prefix='')

VALID_TYPES = {'meeting', 'call', 'task', 'delivery', 'note'}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/assignments
# ─────────────────────────────────────────────────────────────────────────────

@calendar_bp.route('/assignments', methods=['GET'])
@auth_required
def list_assignments():
    """
    List assignments for the current tenant.

    Query parameters:
      month       — YYYY-MM        filter to a calendar month
      date        — YYYY-MM-DD     filter to an exact date
      project_id  — int            filter by project / job
      client_id   — int            filter by client
    """
    try:
        where_conditions = ["t.tenant_id = :tenant_id"]
        params = {'tenant_id': str(g.tenant_id)}

        # ── Month filter ──────────────────────────────────────────────────
        month_param = request.args.get('month')
        if month_param:
            try:
                year, month = month_param.split('-')
                where_conditions.append(
                    "EXTRACT(year  FROM t.start_date) = :year "
                    "AND EXTRACT(month FROM t.start_date) = :month"
                )
                params['year']  = int(year)
                params['month'] = int(month)
            except (ValueError, AttributeError):
                return jsonify({'error': 'month must be in YYYY-MM format'}), 400

        # ── Exact date filter ─────────────────────────────────────────────
        date_param = request.args.get('date')
        if date_param:
            try:
                datetime.strptime(date_param, '%Y-%m-%d')
                where_conditions.append("t.start_date = :exact_date")
                params['exact_date'] = date_param
            except ValueError:
                return jsonify({'error': 'date must be in YYYY-MM-DD format'}), 400

        # ── FK filters ────────────────────────────────────────────────────
        project_id = request.args.get('project_id', type=int)
        if project_id:
            where_conditions.append("t.project_id = :project_id")
            params['project_id'] = project_id

        client_id = (
            request.args.get('client_id',   type=int) or
            request.args.get('customer_id', type=int)
        )
        if client_id:
            where_conditions.append("t.client_id = :client_id")
            params['client_id'] = client_id

        where_clause = " AND ".join(where_conditions)

        query = text(f"""
            SELECT
                t.task_id,
                t.type,
                t.title,
                t.start_date      AS date,
                t.start_date,
                t.end_date,
                t.start_time,
                t.end_time,
                t.team_member     AS staff_name,
                t.project_id,
                t.client_id,
                t.customer_name,
                t.estimated_hours,
                t.notes,
                t.priority,
                t.status,
                t.created_at,
                t.updated_at
            FROM "StreemLyne_MT"."Tasks_Master" t
            WHERE {where_clause}
            ORDER BY t.start_date ASC, t.start_time ASC NULLS LAST
        """)

        result = db.session.execute(query, params)
        rows = result.fetchall()

        return jsonify([_row_to_dict(r) for r in rows]), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/assignments
# ─────────────────────────────────────────────────────────────────────────────

@calendar_bp.route('/assignments', methods=['POST'])
@auth_required
def create_assignment():
    """
    Create a new assignment.

    Required: type, title, date (YYYY-MM-DD)
    Optional: staff_name, job_id/project_id, customer_id/client_id,
              estimated_hours, notes, priority, status
    """
    try:
        data = request.get_json() or {}

        # ── Validation ────────────────────────────────────────────────────
        title = (data.get('title') or '').strip()
        if not title:
            return jsonify({'error': 'title is required'}), 400

        raw_date = data.get('date') or data.get('start_date')
        parsed_date = _parse_date(raw_date)
        if not parsed_date:
            return jsonify({'error': 'date must be in YYYY-MM-DD format'}), 400

        assignment_type = data.get('type', 'task')
        if assignment_type not in VALID_TYPES:
            assignment_type = 'task'

        # ── Resolve FK aliases ────────────────────────────────────────────
        project_id = data.get('project_id') or data.get('job_id')
        client_id  = data.get('client_id')  or data.get('customer_id')

        # ── employee_id for created_by (required NOT NULL column) ─────────
        employee_id = getattr(g.current_user, 'employee_id', None)

        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Tasks_Master" (
                tenant_id, type, title,
                date, start_date, end_date,
                team_member, project_id, client_id,
                estimated_hours, notes, priority, status,
                created_by_employee_id, created_at
            ) VALUES (
                :tenant_id, :type, :title,
                :start_date, :start_date, :end_date,
                :team_member, :project_id, :client_id,
                :estimated_hours, :notes, :priority, :status,
                :created_by, NOW()
            )
            RETURNING
                task_id, type, title,
                start_date AS date, start_date, end_date,
                team_member AS staff_name,
                project_id, client_id, customer_name,
                estimated_hours, notes, priority, status,
                created_at, updated_at
        """)

        result = db.session.execute(insert_query, {
            'tenant_id':       str(g.tenant_id),
            'type':            assignment_type,
            'title':           title,
            'start_date':      parsed_date.isoformat(),
            'end_date':        parsed_date.isoformat(),
            'team_member':     data.get('staff_name'),
            'project_id':      int(project_id) if project_id else None,
            'client_id':       int(client_id)  if client_id  else None,
            'estimated_hours': data.get('estimated_hours'),
            'notes':           data.get('notes'),
            'priority':        data.get('priority', 'Medium'),
            'status':          data.get('status', 'Scheduled'),
            'created_by':      employee_id,
        })
        db.session.commit()

        row = result.fetchone()
        return jsonify(_row_to_dict(row)), 201

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/assignments/<id>
# ─────────────────────────────────────────────────────────────────────────────

@calendar_bp.route('/assignments/<task_id>', methods=['GET'])
@auth_required
def get_assignment(task_id):
    """GET /api/assignments/<task_id>"""
    try:
        row = _fetch_task(task_id, g.tenant_id)
        if not row:
            return jsonify({'error': 'Assignment not found'}), 404
        return jsonify(_row_to_dict(row)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# PUT /api/assignments/<id>
# ─────────────────────────────────────────────────────────────────────────────

@calendar_bp.route('/assignments/<task_id>', methods=['PUT'])
@auth_required
def update_assignment(task_id):
    """
    Update an assignment.
    PUT /api/assignments/<task_id>
    Body: any subset of the create fields.
    """
    try:
        if not _fetch_task(task_id, g.tenant_id):
            return jsonify({'error': 'Assignment not found'}), 404

        data = request.get_json() or {}
        employee_id = getattr(g.current_user, 'employee_id', None)

        set_parts = ["updated_by_employee_id = :updated_by", "updated_at = NOW()"]
        params = {
            'task_id':    task_id,
            'tenant_id':  str(g.tenant_id),
            'updated_by': employee_id,
        }

        if 'type' in data and data['type'] in VALID_TYPES:
            set_parts.append("type = :type")
            params['type'] = data['type']

        if 'title' in data and (data['title'] or '').strip():
            set_parts.append("title = :title")
            params['title'] = data['title'].strip()

        raw_date = data.get('date') or data.get('start_date')
        if raw_date:
            parsed = _parse_date(raw_date)
            if not parsed:
                return jsonify({'error': 'date must be in YYYY-MM-DD format'}), 400
            set_parts.append("start_date = :start_date")
            set_parts.append("date = :start_date")
            params['start_date'] = parsed.isoformat()

        if 'staff_name' in data:
            set_parts.append("team_member = :team_member")
            params['team_member'] = data['staff_name']

        if 'project_id' in data or 'job_id' in data:
            raw = data.get('project_id') or data.get('job_id')
            set_parts.append("project_id = :project_id")
            params['project_id'] = int(raw) if raw else None

        if 'client_id' in data or 'customer_id' in data:
            raw = data.get('client_id') or data.get('customer_id')
            set_parts.append("client_id = :client_id")
            params['client_id'] = int(raw) if raw else None

        for field in ('estimated_hours', 'notes', 'priority', 'status'):
            if field in data:
                set_parts.append(f"{field} = :{field}")
                params[field] = data[field]

        update_query = text(f"""
            UPDATE "StreemLyne_MT"."Tasks_Master"
            SET {', '.join(set_parts)}
            WHERE task_id = :task_id AND tenant_id = :tenant_id
            RETURNING
                task_id, type, title,
                start_date AS date, start_date, end_date,
                team_member AS staff_name,
                project_id, client_id, customer_name,
                estimated_hours, notes, priority, status,
                created_at, updated_at
        """)

        result = db.session.execute(update_query, params)
        db.session.commit()

        row = result.fetchone()
        return jsonify(_row_to_dict(row)), 200

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /api/assignments/<id>
# ─────────────────────────────────────────────────────────────────────────────

@calendar_bp.route('/assignments/<task_id>', methods=['DELETE'])
@auth_required
def delete_assignment(task_id):
    """DELETE /api/assignments/<task_id>"""
    try:
        result = db.session.execute(
            text("""
                DELETE FROM "StreemLyne_MT"."Tasks_Master"
                WHERE task_id = :task_id AND tenant_id = :tenant_id
            """),
            {'task_id': task_id, 'tenant_id': str(g.tenant_id)},
        )
        db.session.commit()

        if result.rowcount == 0:
            return jsonify({'error': 'Assignment not found'}), 404

        return jsonify({'message': 'Assignment deleted'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_task(task_id: str, tenant_id):
    """Return the Tasks_Master row or None — always scoped to tenant."""
    result = db.session.execute(
        text("""
            SELECT
                task_id, type, title,
                start_date AS date, start_date, end_date,
                team_member AS staff_name,
                project_id, client_id, customer_name,
                estimated_hours, notes, priority, status,
                created_at, updated_at
            FROM "StreemLyne_MT"."Tasks_Master"
            WHERE task_id = :task_id AND tenant_id = :tenant_id
        """),
        {'task_id': task_id, 'tenant_id': str(tenant_id)},
    )
    return result.fetchone()


def _parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    raw = str(value).split('T')[0]
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _row_to_dict(row) -> dict:
    """
    Serialise a Tasks_Master row to a dict.
    Exposes both schema names and frontend aliases.
    """
    if row is None:
        return {}

    r = dict(row._mapping)
    date_val = r.get('date') or r.get('start_date')

    return {
        'id':             r.get('task_id'),
        'assignment_id':  r.get('task_id'),
        'type':           r.get('type'),
        'title':          r.get('title'),
        'date':           date_val.isoformat() if isinstance(date_val, date) else date_val,
        'staff_name':     r.get('staff_name'),
        'project_id':     r.get('project_id'),
        'job_id':         r.get('project_id'),
        'client_id':      r.get('client_id'),
        'customer_id':    r.get('client_id'),
        'customer_name':  r.get('customer_name'),
        'estimated_hours': r.get('estimated_hours'),
        'notes':           r.get('notes'),
        'priority':        r.get('priority'),
        'status':          r.get('status'),
        'created_at': r.get('created_at').isoformat() if r.get('created_at') else None,
        'updated_at': r.get('updated_at').isoformat() if r.get('updated_at') else None,
    }