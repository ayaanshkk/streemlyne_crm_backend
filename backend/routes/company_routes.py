"""Company Routes for StreemLyne CRM
──────────────────────────────────────────────────────────────────────────
UPDATED: A "Company" is still a Client_Master row with
client_type = 'Commercial'. Primary / Decision Maker / Finance / Technical /
Other contacts NO LONGER live on that row at all — the primary_contact_id /
purchase_contact_id / finance_contact_id columns (and their legacy
*_name/*_email/*_phone text columns) have been dropped from Client_Master.

Company↔Contact relationships now live entirely in
streemLyne_mt_dev2.Client_Contact_Mapping (client_id, contact_id, role), a
many-to-many table with one row per (company, contact, role)
combination — role is one of Primary / Decision Maker / Finance /
Technical / Other (see VALID_CONTACT_ROLES).
There is no limit on how many contacts a company can have in any given
role. Contacts themselves live in streemLyne_mt_dev2.Contacts (see
contact_routes.py), not in Client_Master.

Create Company (the API/UI route) no longer requires or accepts a
primary contact — a company can be created with no contacts at all,
then contacts are linked afterwards (with a role) from the company
detail page's Contacts card "+" icon, via POST /companies/<id>/contacts.
The CSV import route (POST /companies/import) is the one exception:
optional primary_contact_* columns will create/reuse a Contact and link
it with role 'Primary' automatically — see that route's docstring.

Tables touched:
    streemLyne_mt_dev2.Client_Master          (client_type = 'Commercial')
    streemLyne_mt_dev2.Client_Contact_Mapping
    streemLyne_mt_dev2.Contacts               (read-only here — created/edited via contact_routes.py)
"""

import json
import uuid 
import re
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text

from routes.cc_compat import token_required
from routes.cc_compat import SessionLocal
from routes.import_export_helpers import parse_uploaded_rows, build_csv_response, build_xlsx_response, ImportFileError

company_bp = Blueprint('companies', __name__)

from routes.cc_compat import SCHEMA

# Stage_Master.stage_type for the sales pipeline (was imported from the old
# customer_routes.py, which also carried the FAI-only training pipeline).
STAGE_TYPE_SALES = 1

SALES_STAGES    = {"Enquiry", "Proposal", "Converted", "Lost"}

# Industry-neutral roles a contact can hold at a company. Stored as plain text
# on Client_Contact_Mapping.role, so no migration is needed. Rows written by
# the old FAI build may still hold 'Purchase' / 'Participant' — they keep
# displaying fine; only NEW links are validated against this set.
VALID_CONTACT_ROLES = {"Primary", "Decision Maker", "Finance", "Technical", "Other"}


def T(table_name):
    return f'"{SCHEMA}"."{table_name}"'


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def validate_optional_email(value, field_name, errors):
    value = (value or "").strip()
    if value and not EMAIL_RE.match(value):
        errors[field_name] = "Invalid email format"
    return value


def get_latest_sales_opportunity(session, company_id):
    """Sales-only opportunity lookup for a company, so
    this deliberately only looks at stage_type=1 (sales) rows."""
    return session.execute(
        text(f"""
            SELECT od.opportunity_id, od.stage_id, od."Misc_Col1" AS misc_col1,
                   od.created_at, sm.stage_name
            FROM "{SCHEMA}"."Opportunity_Details" od
            JOIN "{SCHEMA}"."Pipeline_Stage_Master" sm ON sm.stage_id = od.stage_id
            WHERE od.client_id = :cid AND sm.stage_type = :stype
            ORDER BY od.created_at DESC
            LIMIT 1
        """),
        {"cid": company_id, "stype": STAGE_TYPE_SALES}
    ).fetchone()


def derive_sales_stage(opportunity):
    """Single source of truth for a company's sales stage. Used by
    serialize_company() and the export so the Clients list and the
    export always agree on who is Converted."""
    sales_stage = "Enquiry"
    if opportunity:
        misc = {}
        if opportunity.misc_col1:
            try:
                misc = json.loads(opportunity.misc_col1)
            except Exception:
                pass
        raw_stage = opportunity.stage_name
        sales_stage = misc.get("sales_stage") or ("Enquiry" if raw_stage == "Lead" else raw_stage)
    return sales_stage


def resolve_company_contacts_map(session, tenant_id, company_ids):
    """Batch-resolves {company_id: [{contact_id, full_name, email, phone,
    roles: [...]}, ...]} for a set of companies in a single query, using
    Client_Contact_Mapping joined against Contacts. A contact holding
    more than one role at the same company (e.g. Primary AND Finance)
    appears once with both roles listed."""
    ids = [cid for cid in company_ids if cid]
    if not ids:
        return {}

    rows = session.execute(
    text(f"""
        SELECT ccm.client_id, ccm.role, c.contact_id, c.full_name, c.email, c.phone
        FROM {T("Client_Contact_Mapping")} ccm
        JOIN {T("Contact_Master")} c ON c.contact_id = ccm.contact_id
        WHERE ccm.client_id = ANY(:ids) AND c.tenant_id = :tid AND c.is_active = true
    """),
    {"ids": ids, "tid": tenant_id}
).fetchall()

    per_company = {}
    for r in rows:
        company_bucket = per_company.setdefault(r.client_id, {})
        contact_bucket = company_bucket.setdefault(r.contact_id, {
            "contact_id": r.contact_id,
            "full_name":  r.full_name or '',
            "email":      r.email or '',
            "phone":      r.phone or '',
            "roles":      [],
        })
        contact_bucket["roles"].append(r.role)

    return {cid: list(contacts.values()) for cid, contacts in per_company.items()}


def resolve_last_activity_map(session, company_ids):
    """Batch-resolves {company_id: latest_contact_date_iso_string} from
    Client_Interactions — used to populate the companies list's 'Last
    Activity Date' column."""
    ids = [cid for cid in company_ids if cid]
    if not ids:
        return {}
    rows = session.execute(
        text(f"""
            SELECT client_id, MAX(contact_date) AS last_activity
            FROM "{SCHEMA}"."Client_Interactions"
            WHERE client_id = ANY(:ids)
            GROUP BY client_id
        """),
        {"ids": ids}
    ).fetchall()
    return {
        row.client_id: row.last_activity.isoformat() if row.last_activity else None
        for row in rows
    }
COMMERCIAL_CATEGORY_ID = 1   # Client_Category_Master.Category_Name = 'Commercial'
ACTIVE_STATUS_ID  = 1        # Status_Master.status = 'Active'
DORMANT_STATUS_ID = 2
BLACKLISTED_STATUS_ID = 3
DELETED_STATUS_ID = 4 

def get_company_or_404(session, company_id, tenant_id, columns="*"):
    return session.execute(
        text(f"""
            SELECT {columns} FROM {T("Client_Master")}
            WHERE client_id = :cid AND tenant_id = :tid
              AND "Client_Category_Master_ID" = :cat_id
              AND status_id = :active_id
        """),
        {"cid": company_id, "tid": tenant_id,
         "cat_id": COMMERCIAL_CATEGORY_ID, "active_id": ACTIVE_STATUS_ID}
    ).fetchone()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /companies/<company_id>/contacts — list linked contacts,
# grouped by contact with all roles they hold at this company.
# ═════════════════════════════════════════════════════════════════════════════
@company_bp.route('/companies/<int:company_id>/contacts', methods=['GET'])
@token_required
def list_company_contacts(company_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        company = get_company_or_404(session, company_id, tenant_id, columns="client_id")
        if not company:
            return jsonify({'error': 'Company not found'}), 404

        contacts_map = resolve_company_contacts_map(session, tenant_id, [company_id])
        return jsonify(contacts_map.get(company_id, [])), 200

    except Exception as e:
        current_app.logger.exception(f"Error in GET /companies/{company_id}/contacts: {e}")
        return jsonify({'error': 'Failed to fetch company contacts', 'details': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: POST /companies/<company_id>/contacts — link an EXISTING contact
# with a role. body: { "contact_id": 123, "role": "Primary" }
# role is required and must be one of VALID_CONTACT_ROLES.
# The same contact can be linked again with a different role — only the
# exact (company, contact, role) combination is rejected as a duplicate.
# ═════════════════════════════════════════════════════════════════════════════
@company_bp.route('/companies/<int:company_id>/contacts', methods=['POST'])
@token_required
def link_company_contact(company_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        company = get_company_or_404(session, company_id, tenant_id, columns="client_id")
        if not company:
            return jsonify({'error': 'Company not found'}), 404

        data = request.get_json(silent=True) or {}
        contact_id = data.get('contact_id')
        role = (data.get('role') or '').strip()

        if not contact_id:
            return jsonify({'error': 'contact_id is required'}), 400
        if not role:
            return jsonify({'error': 'role is required'}), 400
        if role not in VALID_CONTACT_ROLES and len(role) > 100:
            return jsonify({'error': 'role must be 100 characters or fewer'}), 400

        contact_row = session.execute(
            text(f"""
                SELECT contact_id FROM {T("Contact_Master")}
                WHERE contact_id = :cid AND tenant_id = :tid AND is_active = true
            """),
            {"cid": contact_id, "tid": tenant_id}
        ).fetchone()
        if not contact_row:
            return jsonify({'error': 'Contact not found'}), 404

        existing = session.execute(
            text(f"""
                SELECT 1 FROM {T("Client_Contact_Mapping")}
                WHERE client_id = :company_id AND contact_id = :cid AND role = :role
            """),
            {"company_id": company_id, "cid": contact_id, "role": role}
        ).fetchone()
        if existing:
            return jsonify({'error': f'This contact is already linked to this company as {role}'}), 409

        session.execute(
            text(f"""
                INSERT INTO {T("Client_Contact_Mapping")} (client_id, contact_id, role)
                VALUES (:company_id, :cid, :role)
            """),
            {"company_id": company_id, "cid": contact_id, "role": role}
        )
        session.commit()

        return jsonify({'success': True}), 201

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error in POST /companies/{company_id}/contacts: {e}")
        return jsonify({'error': 'Failed to link contact', 'details': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: PATCH /companies/<company_id>
# Partial update — only keys present in the body are touched.
#   • real columns  → field_map below
#   • metadata jsonb → industry / gst_number / city / state (merged, never replaced)
# Contact roles are NOT edited here; use /companies/<id>/contacts.
# ═════════════════════════════════════════════════════════════════════════════
@company_bp.route('/companies/<int:company_id>', methods=['PATCH'])
@token_required
def update_company(company_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        row = get_company_or_404(session, company_id, tenant_id)
        if not row:
            return jsonify({'error': 'Company not found'}), 404

        data = request.get_json(silent=True) or {}
        errors = {}

        if 'company_name' in data:
            name = (data.get('company_name') or '').strip()
            if not name:
                errors['company_name'] = 'Company name is required'
            elif check_duplicate_company_name(session, tenant_id, name, exclude_company_id=company_id):
                errors['company_name'] = 'A company with this name already exists'
            data['company_name'] = name
        if 'address' in data and not (data.get('address') or '').strip():
            errors['address'] = 'Address is required'
        if errors:
            return jsonify({'error': 'Validation failed', 'details': errors}), 400

        field_map = {
            'company_name': 'client_company_name',
            'company_website': 'client_website',
            'address': 'address',
            'post_code': 'post_code',
            'vendor_registration_number': 'company_number',
            'notes': 'notes',
        }
        sets, params = [], {"cid": company_id, "tid": tenant_id}
        for key, column in field_map.items():
            if key in data:
                sets.append(f'{column} = :{key}')
                params[key] = (data.get(key) or '').strip() if isinstance(data.get(key), str) else data.get(key)

        metadata = dict(row.metadata or {})
        for key in ('industry', 'gst_number', 'city', 'state'):
            if key in data:
                metadata[key] = (data.get(key) or '').strip()
        sets.append('metadata = :metadata')
        params['metadata'] = json.dumps(metadata)

        session.execute(
            text(f"""
                UPDATE {T("Client_Master")}
                SET {", ".join(sets)}
                WHERE client_id = :cid AND tenant_id = :tid
            """),
            params
        )
        session.commit()

        row = get_company_or_404(session, company_id, tenant_id)
        contacts_map = resolve_company_contacts_map(session, tenant_id, [company_id])
        return jsonify(serialize_company(row, contacts_map)), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error in PATCH /companies/{company_id}: {e}")
        return jsonify({'error': 'Failed to update company', 'details': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: DELETE /companies/<company_id>/contacts/<contact_id> — unlink.
# Optional ?role= query param removes just that one role mapping; with
# no role given, every mapping row between this contact and company is
# removed (fully unlinked).
# ═════════════════════════════════════════════════════════════════════════════
@company_bp.route('/companies/<int:company_id>/contacts/<int:contact_id>', methods=['DELETE'])
@token_required
def unlink_company_contact(company_id, contact_id):
    session = SessionLocal()
    try:
        role = request.args.get('role')

        query = f"""
            DELETE FROM {T("Client_Contact_Mapping")}
            WHERE client_id = :company_id AND contact_id = :cid
        """
        params = {"company_id": company_id, "cid": contact_id}
        if role:
            query += " AND role = :role"
            params["role"] = role

        result = session.execute(text(query), params)
        session.commit()

        if result.rowcount == 0:
            return jsonify({'error': 'Link not found'}), 404

        return jsonify({'message': f'Contact unlinked from {role}' if role else 'Contact unlinked'}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error in DELETE /companies/{company_id}/contacts/{contact_id}: {e}")
        return jsonify({'error': 'Failed to unlink contact', 'details': str(e)}), 500
    finally:
        session.close()


def serialize_company(row, contacts_map=None, last_activity_map=None, opportunity=None):
    contacts_map = contacts_map or {}
    metadata = row.metadata or {}   # jsonb column — SQLAlchemy auto-deserializes to dict

    sales_stage = derive_sales_stage(opportunity)

    return {
        "id":                        row.client_id,
        "company_id":                row.client_id,
        "display_id":                row.display_id,
        "company_name":              row.client_company_name or '',
        "company_website":           row.client_website or '',
        "address":                   row.address or '',
        # City_Master / State_Master are not populated, so city & state are kept
        # as plain text inside Client_Master.metadata (no migration needed).
        "city":                      metadata.get("city", ""),
        "state":                     metadata.get("state", ""),
        "country_id":                row.country_id,
        "post_code":                 row.post_code or '',
        "default_currency_id":       row.default_currency_id,
        "vendor_registration_number": row.company_number or '',
        "industry":                  metadata.get("industry", ""),
        "gst_number":                metadata.get("gst_number", ""),
        "attached_documents":        metadata.get("attached_documents", []),
        "payments":                  metadata.get("payments", []),
        "notes":                     row.notes or '',
        # assigned_employee_id has no equivalent column on dev's Client_Master —
        # dropped for now. Flag if this needs to be added, or if
        # assigned_pricelist_id is actually meant to serve double duty (it
        # looks pricing-specific, not personnel, so I haven't assumed that).
        "contacts":                  contacts_map.get(row.client_id, []),
        "tenant_id":   row.tenant_id,
        "created_at":  row.created_at.isoformat() if row.created_at else None,
        "last_activity_date": (last_activity_map or {}).get(row.client_id),
        "sales_stage": sales_stage,
        "sales_allowed_stages": sorted(SALES_STAGES),
    }




# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /companies
# ═════════════════════════════════════════════════════════════════════════════
@company_bp.route('/companies', methods=['GET'])
@token_required
def list_companies():
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        employee_id = request.current_user.employee_id
        if not employee_id:
            return jsonify({'error': 'No employee record linked to this user'}), 400
        search = request.args.get('search', '').strip()
        query = f"""
            SELECT cm.*
            FROM {T("Client_Master")} cm
            WHERE cm.tenant_id = :tenant_id
              AND cm."Client_Category_Master_ID" = :cat_id
              AND cm.status_id = :active_id
        """
        params = {"tenant_id": tenant_id, "cat_id": COMMERCIAL_CATEGORY_ID, "active_id": ACTIVE_STATUS_ID}

        if search:
            query += """ AND (cm.client_company_name ILIKE :search
                               OR cm.client_website ILIKE :search
                               OR cm.company_number ILIKE :search
                               OR cm.address ILIKE :search)"""
            params["search"] = f"%{search}%"

        query += " ORDER BY cm.client_company_name ASC"

        rows = session.execute(text(query), params).fetchall()
        company_ids = [row.client_id for row in rows]
        contacts_map = resolve_company_contacts_map(session, tenant_id, company_ids)
        last_activity_map = resolve_last_activity_map(session, company_ids)

        companies = []
        for row in rows:
            company = serialize_company(
                row,
                contacts_map,
                last_activity_map,
                get_latest_sales_opportunity(session, row.client_id),
            )
            companies.append(company)

        return jsonify(companies), 200
    except Exception as e:
        current_app.logger.exception(f"Error in GET /companies: {e}")
        return jsonify({'error': 'Failed to fetch companies', 'details': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /companies/<company_id>
# ═════════════════════════════════════════════════════════════════════════════
@company_bp.route('/companies/<int:company_id>', methods=['GET'])
@token_required
def get_company(company_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        row = get_company_or_404(session, company_id, tenant_id)
        if not row:
            return jsonify({'error': 'Company not found'}), 404

        contacts_map = resolve_company_contacts_map(session, tenant_id, [company_id])
        last_activity_map = resolve_last_activity_map(session, [company_id])

        return jsonify(serialize_company(row, contacts_map, last_activity_map, get_latest_sales_opportunity(session, company_id))), 200

    except Exception as e:
        current_app.logger.exception(f"Error in GET /companies/{company_id}: {e}")
        return jsonify({'error': 'Failed to fetch company', 'details': str(e)}), 500
    finally:
        session.close()


def find_or_create_contact(session, tenant_id, full_name, phone, email='', designation=''):
    existing = session.execute(
        text(f"""
            SELECT contact_id FROM {T("Contact_Master")}
            WHERE tenant_id = :tid AND is_active = true
              AND LOWER(TRIM(full_name)) = LOWER(TRIM(:name))
              AND TRIM(phone) = TRIM(:phone)
        """),
        {"tid": tenant_id, "name": full_name, "phone": phone}
    ).fetchone()
    if existing:
        return existing.contact_id, False

    result = session.execute(
        text(f"""
            INSERT INTO {T("Contact_Master")}
            (tenant_id, full_name, phone, email, designation, city_id, state_id, is_active, created_at, updated_at)
            VALUES (:tenant_id, :full_name, :phone, :email, :designation, NULL, NULL, true, :now, :now)
            RETURNING contact_id
        """),
        {
            "tenant_id": tenant_id, "full_name": full_name, "phone": phone,
            "email": email, "designation": designation, "now": datetime.utcnow(),
        }
    )
    return result.fetchone().contact_id, True

    

def get_default_country_id(session):
    row = session.execute(
        text(f"""
            SELECT country_id FROM {T("Country_Master")}
            WHERE LOWER(TRIM(country_name)) = 'india'
            LIMIT 1
        """)
    ).fetchone()
    return row.country_id if row else None


def check_duplicate_company_name(session, tenant_id, company_name, exclude_company_id=None):
    query = f"""
        SELECT client_id FROM {T("Client_Master")}
        WHERE tenant_id = :tid
          AND "Client_Category_Master_ID" = :cat_id AND status_id = :active_id
          AND LOWER(TRIM(client_company_name)) = LOWER(TRIM(:name))
    """
    params = {"tid": tenant_id, "cat_id": COMMERCIAL_CATEGORY_ID,
              "active_id": ACTIVE_STATUS_ID, "name": company_name}
    if exclude_company_id is not None:
        query += " AND client_id != :exclude_id"
        params["exclude_id"] = exclude_company_id
    return session.execute(text(query), params).fetchone() is not None



# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: PATCH /companies/<company_id>/stage
# Updates the SALES pipeline stage for a company. This is the single
# place that mutates a company's sales stage.
#
# NOTE: a company created via POST /companies has NO Opportunity_Details
# row at all — this route creates one on first use instead of erroring.
# ═════════════════════════════════════════════════════════════════════════════
@company_bp.route('/companies/<int:company_id>/stage', methods=['PATCH'])
@token_required
def update_company_sales_stage(company_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        row = get_company_or_404(session, company_id, tenant_id, columns="client_id, client_company_name")
        if not row:
            return jsonify({'error': 'Company not found'}), 404

        data = request.get_json(silent=True) or {}
        new_stage = data.get('stage')
        if new_stage not in SALES_STAGES:
            return jsonify({'error': f"Invalid stage. Must be one of: {sorted(SALES_STAGES)}"}), 400

        backend_stage = "Lead" if new_stage == "Enquiry" else new_stage

        opp = get_latest_sales_opportunity(session, company_id)
        existing_misc = {}
        if opp and opp.misc_col1:
            try:
                existing_misc = json.loads(opp.misc_col1)
            except Exception:
                pass

        stage_row = session.execute(
            text(f"""
                SELECT stage_id, stage_name FROM "{SCHEMA}"."Pipeline_Stage_Master"
                WHERE LOWER(stage_name) = LOWER(:sname) AND stage_type = :stype
                LIMIT 1
            """),
            {"sname": backend_stage, "stype": STAGE_TYPE_SALES}
        ).fetchone()
        if not stage_row:
            return jsonify({'error': f"Stage '{new_stage}' not configured in Pipeline_Stage_Master"}), 400

        old_stage = opp.stage_name if opp else None
        existing_misc['status'] = 'Lost' if new_stage == 'Lost' else 'Active'
        previous_stage = existing_misc.get("sales_stage")   # read before overwriting
        existing_misc["sales_stage"] = new_stage

        if new_stage == "Converted" and previous_stage != "Converted":
            existing_misc["converted_at"] = datetime.utcnow().isoformat() + "+00:00"

        existing_misc['notes'] = (existing_misc.get('notes', '') or '') + (
            f"\n[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')}] "
            f"Stage changed: {old_stage} → {new_stage} (sales pipeline)"
        )

        if opp:
            session.execute(
                text(f"""
                    UPDATE "{SCHEMA}"."Opportunity_Details"
                    SET stage_id = :stage_id, opportunity_title = :title, "Misc_Col1" = :misc
                    WHERE opportunity_id = :oid
                """),
                {
                    "stage_id": stage_row.stage_id,
                    "title": f"{row.client_company_name} - {new_stage}",
                    "misc": json.dumps(existing_misc),
                    "oid": opp.opportunity_id,
                }
            )
        else:
            session.execute(
                text(f"""
                    INSERT INTO "{SCHEMA}"."Opportunity_Details"
                        (client_id, opportunity_title, opportunity_date,
                         opportunity_owner_employee_id, stage_id,
                         opportunity_value, currency_id, created_at, "Misc_Col1")
                    VALUES
                        (:client_id, :title, :opp_date, :owner_emp_id, :stage_id,
                         0, NULL, :created_at, :misc)
                """),
                {
                    "client_id": company_id,
                    "title": f"{row.client_company_name} - {new_stage}",
                    "opp_date": datetime.utcnow().date(),
                    "owner_emp_id": request.current_user.employee_id,
                    "stage_id": stage_row.stage_id,
                    "created_at": datetime.utcnow(),
                    "misc": json.dumps(existing_misc),
                }
            )

        session.commit()

        updated_row = get_company_or_404(session, company_id, tenant_id)
        contacts_map = resolve_company_contacts_map(session, tenant_id, [company_id])
        updated_opp = get_latest_sales_opportunity(session, company_id)
        return jsonify(serialize_company(updated_row, contacts_map, opportunity=updated_opp)), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error in PATCH /companies/{company_id}/stage: {e}")
        return jsonify({'error': 'Failed to update stage', 'details': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTES: /companies/<company_id>/payments
# Payments are stored inside Client_Master.metadata (jsonb), same
# pattern as industry/gst_number — no dedicated table. Each payment
# gets a UUID string id since there's no serial column backing it.
# ═════════════════════════════════════════════════════════════════════════════
PAYMENT_STATUSES = {"Paid", "Pending", "Overdue"}


@company_bp.route('/companies/<int:company_id>/payments', methods=['POST'])
@token_required
def add_company_payment(company_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        row = get_company_or_404(session, company_id, tenant_id, columns="client_id, metadata")
        if not row:
            return jsonify({'error': 'Company not found'}), 404

        data = request.get_json(silent=True) or {}
        errors = {}

        try:
            amount = float(data.get('amount'))
        except (TypeError, ValueError):
            errors['amount'] = 'A valid amount is required'
            amount = None

        date = (data.get('date') or '').strip()
        if not date:
            errors['date'] = 'Date is required'

        status = data.get('status', 'Pending')
        if status not in PAYMENT_STATUSES:
            errors['status'] = f"Must be one of: {', '.join(sorted(PAYMENT_STATUSES))}"

        if errors:
            return jsonify({'error': 'Validation failed', 'details': errors}), 400

        metadata = row.metadata or {}
        payments = metadata.get('payments', [])

        new_payment = {
            "id": str(uuid.uuid4()),
            "amount": amount,
            "date": date,
            "status": status,
            "note": (data.get('note') or '').strip(),
        }
        payments.append(new_payment)
        metadata['payments'] = payments

        session.execute(
            text(f'UPDATE {T("Client_Master")} SET metadata = :metadata WHERE client_id = :cid'),
            {"metadata": json.dumps(metadata), "cid": company_id}
        )
        session.commit()

        return jsonify(new_payment), 201
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error in POST /companies/{company_id}/payments: {e}")
        return jsonify({'error': 'Failed to add payment', 'details': str(e)}), 500
    finally:
        session.close()


@company_bp.route('/companies/<int:company_id>/payments/<payment_id>', methods=['PATCH'])
@token_required
def update_company_payment(company_id, payment_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        row = get_company_or_404(session, company_id, tenant_id, columns="client_id, metadata")
        if not row:
            return jsonify({'error': 'Company not found'}), 404

        data = request.get_json(silent=True) or {}
        if 'status' in data and data['status'] not in PAYMENT_STATUSES:
            return jsonify({'error': 'Validation failed', 'details': {'status': f"Must be one of: {', '.join(sorted(PAYMENT_STATUSES))}"}}), 400

        metadata = row.metadata or {}
        payments = metadata.get('payments', [])

        found = False
        for p in payments:
            if p.get('id') == payment_id:
                for field in ('amount', 'date', 'status', 'note'):
                    if field in data:
                        p[field] = data[field]
                found = True
                break

        if not found:
            return jsonify({'error': 'Payment not found'}), 404

        metadata['payments'] = payments
        session.execute(
            text(f'UPDATE {T("Client_Master")} SET metadata = :metadata WHERE client_id = :cid'),
            {"metadata": json.dumps(metadata), "cid": company_id}
        )
        session.commit()

        return jsonify({'success': True}), 200
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error in PATCH /companies/{company_id}/payments/{payment_id}: {e}")
        return jsonify({'error': 'Failed to update payment', 'details': str(e)}), 500
    finally:
        session.close()


@company_bp.route('/companies/<int:company_id>/payments/<payment_id>', methods=['DELETE'])
@token_required
def delete_company_payment(company_id, payment_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        row = get_company_or_404(session, company_id, tenant_id, columns="client_id, metadata")
        if not row:
            return jsonify({'error': 'Company not found'}), 404

        metadata = row.metadata or {}
        payments = metadata.get('payments', [])
        new_payments = [p for p in payments if p.get('id') != payment_id]

        if len(new_payments) == len(payments):
            return jsonify({'error': 'Payment not found'}), 404

        metadata['payments'] = new_payments
        session.execute(
            text(f'UPDATE {T("Client_Master")} SET metadata = :metadata WHERE client_id = :cid'),
            {"metadata": json.dumps(metadata), "cid": company_id}
        )
        session.commit()

        return jsonify({'message': 'Payment deleted'}), 200
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error in DELETE /companies/{company_id}/payments/{payment_id}: {e}")
        return jsonify({'error': 'Failed to delete payment', 'details': str(e)}), 500
    finally:
        session.close()    

    # ═════════════════════════════════════════════════════════════════════════════
# ROUTE: POST /companies
# Mandatory fields: company_name, address only. Optional
# primary_contact_id / purchase_contact_id / finance_contact_id: if
# provided, each must be an existing active Contact for this tenant —
# invalid ids are validated up front (before the INSERT) and returned
# as field errors, same shape as the company_name/address checks below.
# Valid ids are linked into Client_Contact_Mapping with roles
# Primary/Purchase/Finance in the same transaction as company creation,
# so the company either has all its requested contacts linked or none
# of it (and the whole company row) is committed. Also rejects a
# company_name that already exists for this tenant (case-insensitive,
# ignoring surrounding whitespace).
# ═════════════════════════════════════════════════════════════════════════════
@company_bp.route('/companies', methods=['POST'])
@token_required
def create_company():
    current_app.logger.info(f"DEBUG current_user: {request.current_user.__dict__}")
    session = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}
        company_name = (data.get('company_name') or '').strip()
        address = (data.get('address') or '').strip()

        errors = {}
        if not company_name:
            errors['company_name'] = 'Company name is required'
        if not address:
            errors['address'] = 'Address is required'

        tenant_id = request.current_user.tenant_id
        if not tenant_id:
            return jsonify({'error': 'User account is not associated with a tenant'}), 400

        if company_name and check_duplicate_company_name(
            session, tenant_id, company_name
        ):
            errors['company_name'] = 'A company with this name already exists'

        # Optional convenience: link existing contacts while creating the company.
        contact_role_fields = {
            'primary_contact_id': 'Primary',
            'decision_maker_contact_id': 'Decision Maker',
            'finance_contact_id': 'Finance',
        }

        contacts_to_link = []

        for field_key, role in contact_role_fields.items():
            raw_id = data.get(field_key)

            if raw_id in (None, '', 0):
                continue

            try:
                contact_id = int(raw_id)
            except (TypeError, ValueError):
                errors[field_key] = 'Must be a valid contact id'
                continue

            contact_row = session.execute(
                text(f"""
                    SELECT contact_id
                    FROM {T("Contact_Master")}
                    WHERE contact_id = :cid
                      AND tenant_id = :tid
                      AND is_active = true
                """),
                {
                    "cid": contact_id,
                    "tid": tenant_id
                }
            ).fetchone()

            if not contact_row:
                errors[field_key] = 'Contact not found'
                continue

            contacts_to_link.append((contact_id, role))

        if errors:
            return jsonify({
                'error': 'Validation failed',
                'details': errors
            }), 400
        
        employee_id = request.current_user.employee_id
        if not employee_id:
            return jsonify({'error': 'No employee record linked to this user'}), 400

        metadata = {
            "industry": (data.get('industry') or '').strip(),
            "gst_number": (data.get('gst_number') or '').strip(),
            "city": (data.get('city') or '').strip(),
            "state": (data.get('state') or '').strip(),
            "attached_documents": data.get('attached_documents') or [],
        }

        result = session.execute(
            text(f"""
                INSERT INTO {T("Client_Master")}
                (
                    tenant_id,
                    "Client_Category_Master_ID",
                    status_id,
                    client_company_name,
                    client_website,
                    address,
                    city_id,
                    state_id,
                    country_id,
                    post_code,
                    default_currency_id,
                    company_number,
                    notes,
                    metadata,
                    created_by_user_id,
                    created_at
                )
                VALUES
                (
                    :tenant_id,
                    :cat_id,
                    :active_id,
                    :company_name,
                    :company_website,
                    :address,
                    NULL,
                    NULL,
                    :country_id,
                    :post_code,
                    :default_currency_id,
                    :company_number,
                    :notes,
                    :metadata,
                    :created_by_user_id,
                    :created_at
                )
                RETURNING client_id
            """),
            {
                "tenant_id": tenant_id,
                "cat_id": COMMERCIAL_CATEGORY_ID,
                "active_id": ACTIVE_STATUS_ID,
                "company_name": company_name,
                "company_website": data.get('company_website', ''),
                "address": data.get('address', ''),
                "country_id": data.get('country_id') or get_default_country_id(session),
                "post_code": data.get('post_code', ''),
                "default_currency_id": data.get('default_currency_id'),
                "company_number": data.get('vendor_registration_number', ''),
                "notes": data.get('notes', ''),
                "metadata": json.dumps(metadata),
                "created_by_user_id": employee_id,
                "created_at": datetime.utcnow(),
            }
        )

        new_company_id = result.fetchone().client_id

        for contact_id, role in contacts_to_link:
            session.execute(
                text(f"""
                    INSERT INTO {T("Client_Contact_Mapping")}
                    (client_id, contact_id, role)
                    VALUES (:company_id, :contact_id, :role)
                """),
                {
                    "company_id": new_company_id,
                    "contact_id": contact_id,
                    "role": role
                }
            )

        session.commit()

        row = get_company_or_404(
            session,
            new_company_id,
            tenant_id
        )

        contacts_map = resolve_company_contacts_map(
            session,
            tenant_id,
            [new_company_id]
        )

        return jsonify(
            serialize_company(row, contacts_map)
        ), 201

    except Exception as e:
        session.rollback()
        current_app.logger.exception(
            f"Error in POST /companies: {e}"
        )
        return jsonify({
            'error': 'Failed to create company',
            'details': str(e)
        }), 500

    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: DELETE /companies/<company_id>
# Also removes any Client_Contact_Mapping rows for this company, since a
# mapping to a soft-deleted company would otherwise be dead weight.
# ═════════════════════════════════════════════════════════════════════════════
@company_bp.route('/companies/<int:company_id>', methods=['DELETE'])
@token_required
def delete_company(company_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        existing = get_company_or_404(session, company_id, tenant_id, columns="client_id")
        if not existing:
            return jsonify({'error': 'Company not found'}), 404

        project_count = session.execute(
            text(f'SELECT COUNT(*) FROM {T("Project_Details")} WHERE client_id = :cid'),
            {"cid": company_id}
        ).scalar()
        if project_count > 0:
            return jsonify({'error': f'Cannot delete company with {project_count} project(s). Delete projects first.'}), 400

        session.execute(
            text(f'DELETE FROM {T("Client_Contact_Mapping")} WHERE client_id = :cid'),
            {"cid": company_id}
        )
        session.execute(
            text(f"""
                UPDATE {T("Client_Master")}
                SET status_id = :deleted_id,
                    "Status_Note" = :reason
                WHERE client_id = :cid AND tenant_id = :tid
            """),
            {
                "deleted_id": DELETED_STATUS_ID,
                "reason": (request.get_json(silent=True) or {}).get('reason', 'Deleted via Companies module'),
                "cid": company_id, "tid": tenant_id,
            }
        )
        session.commit()
        return jsonify({'message': 'Company deleted'}), 200
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error in DELETE /companies/{company_id}: {e}")
        return jsonify({'error': 'Failed to delete company', 'details': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# EXPORT — no longer includes primary/purchase/finance contact columns
# (those never existed on Client_Master's schema; they're now rows in
# Client_Contact_Mapping). Flag if you'd like a "primary contact name"
# column added back by joining to the Primary-role mapping per company.
# ═════════════════════════════════════════════════════════════════════════════

COMPANY_EXPORT_FIELDS = [
    "client_id", "company_name", "industry", "company_website", "address",
    "city", "state", "post_code", "vendor_registration_number", "gst_number", "notes",
]


@company_bp.route('/companies/export', methods=['GET'])
@token_required
def export_companies():
    """Exports every active company of the tenant. Optional ?stage=Enquiry|Proposal|
    Converted|Lost narrows it to one sales stage. ?format=csv|xlsx (default csv)."""
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        fmt = request.args.get('format', 'csv').lower()
        stage_filter = (request.args.get('stage') or '').strip()
        if stage_filter and stage_filter not in SALES_STAGES:
            return jsonify({'error': f'stage must be one of {sorted(SALES_STAGES)}'}), 400

        rows = session.execute(
            text(f"""
                SELECT cm.client_id,
                       cm.client_company_name AS company_name,
                       cm.client_website AS company_website,
                       cm.address, cm.post_code,
                       cm.company_number AS vendor_registration_number,
                       cm.notes, cm.metadata
                FROM {T("Client_Master")} cm
                WHERE cm.tenant_id = :tenant_id
                  AND cm."Client_Category_Master_ID" = :cat_id
                  AND cm.status_id = :active_id
                ORDER BY cm.client_company_name ASC
            """),
            {"tenant_id": tenant_id, "cat_id": COMMERCIAL_CATEGORY_ID, "active_id": ACTIVE_STATUS_ID}
        ).fetchall()

        dict_rows = []
        for row in rows:
            if stage_filter and derive_sales_stage(get_latest_sales_opportunity(session, row.client_id)) != stage_filter:
                continue
            d = dict(row._mapping)
            meta = d.pop("metadata", None) or {}
            for key in ("industry", "gst_number", "city", "state"):
                d[key] = meta.get(key, "")
            dict_rows.append(d)

        if fmt == 'xlsx':
            return build_xlsx_response(COMPANY_EXPORT_FIELDS, dict_rows, "companies_export.xlsx")
        return build_csv_response(COMPANY_EXPORT_FIELDS, dict_rows, "companies_export.csv")
    except Exception as e:
        current_app.logger.exception(f"Error in GET /companies/export: {e}")
        return jsonify({'error': 'Failed to export companies', 'details': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: POST /companies/import
# Duplicate rule is company_name alone (case-insensitive).
# Optional columns: company_website, vendor_registration_number, industry,
# gst_number, city, state, address, post_code, notes.
#
# Optional CSV columns primary_contact_name / primary_contact_phone /
# primary_contact_email / primary_contact_designation: if a row provides
# a name AND phone, that contact is created in the Contacts module (or
# reused if an active contact with the same full_name + phone already
# exists — same duplicate rule as contact_routes.py) and linked to the
# new company with role 'Primary' via Client_Contact_Mapping. Providing
# only one of name/phone is a row error (both are required together,
# same as a normal Contact create). Both columns are optional overall —
# a company can still be imported with no contact info at all.
# ═════════════════════════════════════════════════════════════════════════════
@company_bp.route('/companies/import', methods=['POST'])
@token_required
def import_companies():
    session = SessionLocal()
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded (expected form field "file")'}), 400

        try:
            rows = parse_uploaded_rows(request.files['file'])
        except ImportFileError as e:
            return jsonify({'error': str(e)}), 400

        tenant_id = request.current_user.tenant_id

        employee_id = request.current_user.employee_id
        if not employee_id:
            return jsonify({'error': 'No employee record linked to this user'}), 400

        existing_names = set()
        for r in session.execute(
            text(f"""
                SELECT client_company_name
                FROM {T("Client_Master")}
                WHERE tenant_id = :tid
                  AND "Client_Category_Master_ID" = :cat_id AND status_id = :active_id
            """),
            {"tid": tenant_id, "cat_id": COMMERCIAL_CATEGORY_ID, "active_id": ACTIVE_STATUS_ID}
        ).fetchall():
            existing_names.add((r.client_company_name or '').strip().lower())

        created, skipped, errors = 0, 0, []
        contacts_created, contacts_linked = 0, 0

        for i, row in enumerate(rows, start=2):
            company_name = (row.get('company_name') or '').strip()
            if not company_name:
                errors.append({"row": i, "error": "Missing company_name"})
                continue

            if company_name.lower() in existing_names:
                skipped += 1
                continue

            primary_name = (row.get('primary_contact_name') or '').strip()
            primary_phone = (row.get('primary_contact_phone') or '').strip()
            primary_email = (row.get('primary_contact_email') or '').strip()
            primary_designation = (row.get('primary_contact_designation') or '').strip()

            if (primary_name or primary_phone) and not (primary_name and primary_phone):
                errors.append({
                    "row": i,
                    "error": "primary_contact_name and primary_contact_phone must both be provided together"
                })
                continue

            if primary_email and not EMAIL_RE.match(primary_email):
                errors.append({"row": i, "error": f"Invalid primary contact email: {primary_email}"})
                continue

            result = session.execute(
                text(f"""
                    INSERT INTO {T("Client_Master")}
                    (
                        tenant_id, "Client_Category_Master_ID", status_id, client_company_name,
                        client_website, company_number,
                        address, city_id, state_id, post_code,
                        notes, metadata, created_by_user_id, created_at
                    )
                    VALUES
                    (
                        :tenant_id, :cat_id, :active_id, :company_name,
                        :company_website, :company_number,
                        :address, NULL, NULL, :post_code,
                        :notes, :metadata, :created_by_user_id, :created_at
                    )
                    RETURNING client_id
                """),
                {
                    "tenant_id": tenant_id,
                    "cat_id": COMMERCIAL_CATEGORY_ID,
                    "active_id": ACTIVE_STATUS_ID,
                    "company_name": company_name,
                    "company_website": (row.get('company_website') or '').strip(),
                    "company_number": (row.get('vendor_registration_number') or '').strip(),
                    "address": row.get('address', ''),
                    "post_code": row.get('post_code', ''),
                    "notes": row.get('notes', ''),
                    "metadata": json.dumps({
                        "industry": (row.get('industry') or '').strip(),
                        "gst_number": (row.get('gst_number') or '').strip(),
                        "city": (row.get('city') or '').strip(),
                        "state": (row.get('state') or '').strip(),
                    }),
                    # same unverified created_by_user_id mapping as create_company
                    "created_by_user_id": employee_id,
                    "created_at": datetime.utcnow(),
                }
            )
            new_company_id = result.fetchone().client_id

            if primary_name and primary_phone:
                contact_id, was_created = find_or_create_contact(
                    session, tenant_id, primary_name, primary_phone,
                    email=primary_email, designation=primary_designation,
                )
                session.execute(
                    text(f"""
                        INSERT INTO {T("Client_Contact_Mapping")} (client_id, contact_id, role)
                        VALUES (:company_id, :contact_id, 'Primary')
                    """),
                    {"company_id": new_company_id, "contact_id": contact_id}
                )
                contacts_linked += 1
                if was_created:
                    contacts_created += 1

            existing_names.add(company_name.lower())
            created += 1

        session.commit()
        current_app.logger.info(
            f"Company import: {created} created, {skipped} skipped, {len(errors)} errors, "
            f"{contacts_created} contacts created, {contacts_linked} contacts linked"
        )

        return jsonify({
            "added": created, "created": created, "skipped": skipped, "errors": errors,
            "contacts_created": contacts_created, "contacts_linked": contacts_linked,
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error in POST /companies/import: {e}")
        return jsonify({'error': 'Failed to import companies', 'details': str(e)}), 500
    finally:
        session.close()