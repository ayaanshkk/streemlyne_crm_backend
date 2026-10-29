"""
Company Enquiry Routes for StreemLyne CRM
──────────────────────────────────────────────────────────────────────────
Enquiries are stored as a JSON array directly on the Company's own
Client_Master row (column: enquiries) — same pattern already used for
linked_companies on Contact rows. No new table, per constraint: only
ALTER TABLE on existing tables is allowed, no CREATE TABLE.

Register this blueprint alongside company_bp in your Flask app (same
file or a separate one — routes are independent either way):
    from .company_enquiry_routes import company_enquiry_bp
    app.register_blueprint(company_enquiry_bp)

Requires migration_client_master_enquiries.sql to have been run first
(adds the `enquiries` column to Client_Master).
"""

import json
import uuid
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text

from routes.cc_compat import token_required
from routes.cc_compat import SessionLocal

company_enquiry_bp = Blueprint('company_enquiries', __name__)

from routes.cc_compat import SCHEMA


def T(table_name):
    return f'"{SCHEMA}"."{table_name}"'



VALID_STATUSES = {"Draft", "Open", "In Progress", "Closed"}
VALID_PRIORITIES = {"Low", "Medium", "High"}


COMMERCIAL_CATEGORY_ID = 1   # Client_Category_Master.Category_Name = 'Commercial'
ACTIVE_STATUS_ID = 1         # Status_Master.status = 'Active'


def get_company_or_404(session, company_id, tenant_id):
    return session.execute(
        text(f"""
            SELECT client_id, enquiries FROM {T("Client_Master")}
            WHERE client_id = :cid AND tenant_id = :tid
              AND "Client_Category_Master_ID" = :cat_id AND status_id = :active_id
        """),
        {"cid": company_id, "tid": tenant_id, "cat_id": COMMERCIAL_CATEGORY_ID, "active_id": ACTIVE_STATUS_ID}
    ).fetchone()


def parse_enquiries(val):
    if not val:
        return []
    try:
        return json.loads(val)
    except (TypeError, ValueError):
        return []


def save_enquiries(session, company_id, tenant_id, enquiries):
    session.execute(
        text(f"""
            UPDATE {T("Client_Master")}
            SET enquiries = :enquiries
            WHERE client_id = :cid AND tenant_id = :tid
        """),
        {"enquiries": json.dumps(enquiries), "cid": company_id, "tid": tenant_id}
    )


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /companies/<company_id>/enquiries
# ═════════════════════════════════════════════════════════════════════════════
@company_enquiry_bp.route('/companies/<int:company_id>/enquiries', methods=['GET'])
@token_required
def list_enquiries(company_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        company = get_company_or_404(session, company_id, tenant_id)
        if not company:
            return jsonify({'error': 'Company not found'}), 404

        enquiries = parse_enquiries(company.enquiries)
        enquiries.sort(key=lambda e: e.get('created_at') or '', reverse=True)
        return jsonify(enquiries), 200
    except Exception as e:
        current_app.logger.exception(f"Error in GET /companies/{company_id}/enquiries: {e}")
        return jsonify({'error': 'Failed to fetch enquiries', 'details': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: POST /companies/<company_id>/enquiries
# body: { subject, source, description, status, enquiry_date, assigned_to,
#         follow_up_date, priority }
# ═════════════════════════════════════════════════════════════════════════════
@company_enquiry_bp.route('/companies/<int:company_id>/enquiries', methods=['POST'])
@token_required
def create_enquiry(company_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        company = get_company_or_404(session, company_id, tenant_id)
        if not company:
            return jsonify({'error': 'Company not found'}), 404

        data = request.get_json(silent=True) or {}

        subject = (data.get('subject') or '').strip()
        if not subject:
            return jsonify({'error': 'Subject is required'}), 400

        status = data.get('status') or 'Open'
        if status not in VALID_STATUSES:
            return jsonify({'error': f"status must be one of: {', '.join(sorted(VALID_STATUSES))}"}), 400

        priority = data.get('priority')
        if priority and priority not in VALID_PRIORITIES:
            return jsonify({'error': f"priority must be one of: {', '.join(sorted(VALID_PRIORITIES))}"}), 400

        enquiry = {
            "id": f"enq_{uuid.uuid4().hex[:12]}",
            "subject": subject,
            "source": data.get('source', ''),
            "description": data.get('description', ''),
            "status": status,
            "enquiry_date": data.get('enquiry_date') or datetime.utcnow().date().isoformat(),
            "assigned_to": data.get('assigned_to', ''),
            "follow_up_date": data.get('follow_up_date'),
            "priority": priority or '',
            "created_at": datetime.utcnow().isoformat(),
        }

        enquiries = parse_enquiries(company.enquiries)
        enquiries.append(enquiry)
        save_enquiries(session, company_id, tenant_id, enquiries)
        session.commit()

        return jsonify(enquiry), 201
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error in POST /companies/{company_id}/enquiries: {e}")
        return jsonify({'error': 'Failed to create enquiry', 'details': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: PATCH /companies/<company_id>/enquiries/<enquiry_id>
# ═════════════════════════════════════════════════════════════════════════════
@company_enquiry_bp.route('/companies/<int:company_id>/enquiries/<string:enquiry_id>', methods=['PATCH'])
@token_required
def update_enquiry(company_id, enquiry_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        company = get_company_or_404(session, company_id, tenant_id)
        if not company:
            return jsonify({'error': 'Company not found'}), 404

        data = request.get_json(silent=True) or {}

        if 'status' in data and data['status'] not in VALID_STATUSES:
            return jsonify({'error': f"status must be one of: {', '.join(sorted(VALID_STATUSES))}"}), 400
        if data.get('priority') and data['priority'] not in VALID_PRIORITIES:
            return jsonify({'error': f"priority must be one of: {', '.join(sorted(VALID_PRIORITIES))}"}), 400

        enquiries = parse_enquiries(company.enquiries)
        match = next((e for e in enquiries if e.get('id') == enquiry_id), None)
        if not match:
            return jsonify({'error': 'Enquiry not found'}), 404

        for key in ('subject', 'source', 'description', 'status', 'enquiry_date',
                    'assigned_to', 'follow_up_date', 'priority'):
            if key in data:
                match[key] = data[key]

        save_enquiries(session, company_id, tenant_id, enquiries)
        session.commit()

        return jsonify(match), 200
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error in PATCH /companies/{company_id}/enquiries/{enquiry_id}: {e}")
        return jsonify({'error': 'Failed to update enquiry', 'details': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: DELETE /companies/<company_id>/enquiries/<enquiry_id>
# ═════════════════════════════════════════════════════════════════════════════
@company_enquiry_bp.route('/companies/<int:company_id>/enquiries/<string:enquiry_id>', methods=['DELETE'])
@token_required
def delete_enquiry(company_id, enquiry_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        company = get_company_or_404(session, company_id, tenant_id)
        if not company:
            return jsonify({'error': 'Company not found'}), 404

        enquiries = parse_enquiries(company.enquiries)
        remaining = [e for e in enquiries if e.get('id') != enquiry_id]
        if len(remaining) == len(enquiries):
            return jsonify({'error': 'Enquiry not found'}), 404

        save_enquiries(session, company_id, tenant_id, remaining)
        session.commit()

        return jsonify({'message': 'Enquiry deleted'}), 200
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error in DELETE /companies/{company_id}/enquiries/{enquiry_id}: {e}")
        return jsonify({'error': 'Failed to delete enquiry', 'details': str(e)}), 500
    finally:
        session.close()
