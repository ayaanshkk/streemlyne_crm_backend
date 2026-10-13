"""
Contact Routes for StreemLyne CRM
──────────────────────────────────────────────────────────────────────────
UPDATED: Contacts are no longer Client_Master rows (client_type =
'Individual'). They now live in their own streemLyne_mt_dev2.Contacts table
and link to Companies (Client_Master, client_type = 'Commercial') through
streemLyne_mt_dev2.Client_Contact_Mapping — a many-to-many table with one row
per (company, contact, role) combination. role is one of
Primary / Purchase / Finance / Participant.

Contacts table columns: contact_id (PK), full_name (required), phone
(required), email, designation, department, address, city, state,
pin_code, created_at, updated_at, is_active, tenant_id.

full_name and phone are mandatory. A contact is treated as a duplicate
of an existing one if BOTH full_name and phone match (case-insensitive,
whitespace-trimmed) an existing active contact for the tenant — email
is not part of the duplicate key, since two different contacts can
legitimately share a family/company email.

REMOVED in this pass (no longer have a home on the new Contacts table —
flag if any of these are still needed and we'll design where they live):
    - payments (was a JSON column on the old Individual Client_Master row)
    - attached_documents on the contact itself (attached documents now
      go through client_files_routes.py, which is schema-agnostic and
      keyed by client_id — a Contact's own contact_id can be used there
      once/if that route is taught to accept contact_id instead of
      client_id)
    - lifecycle "stage" (Lead/etc.) — not present on the new Contacts
      schema
    - company_name_freetext — replaced entirely by real links via
      Client_Contact_Mapping; there's no more "unlinked company text"
      concept

Delete behavior: a contact can be linked to companies via
Client_Contact_Mapping. Deleting a contact removes those mapping rows
and soft-deletes the contact (is_active = false) rather than blocking
the delete — flag if you'd rather block deletion while links exist.

Tables touched:
    streemLyne_mt_dev2.Contact_Master
    streemLyne_mt_dev2.Client_Contact_Mapping
    streemLyne_mt_dev2.Client_Master   (client_type = 'Commercial', read-only — resolving linked company names)
    streemLyne_mt_dev2.Training_Master / Client_Files (read-only, for the
    training-history route further down this file)
"""

import re
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text

from .auth_helpers import token_required
from .import_export_helpers import parse_uploaded_rows, build_csv_response, ImportFileError, apply_header_aliases
from ..db import SessionLocal

contact_bp = Blueprint('contacts', __name__)

SCHEMA = "streemLyne_mt_dev2"

CONTACT_HEADER_ALIASES = {
    "full_name": ["full_name", "name", "contact_name", "contact_person", "client_contact_name"],
    "phone": ["phone", "phone_number", "phone_no", "contact_number", "contact_no",
              "mobile", "mobile_number", "mobile_no", "telephone"],
    "email": ["email", "email_address", "e_mail", "mail"],
    "designation": ["designation", "job_title", "title", "position"],
    "department": ["department", "dept"],
    "address": ["address", "street_address", "street", "location"],
    "city": ["city"],
    "state": ["state", "province"],
    "pin_code": ["pin_code", "pincode", "postal_code", "zip", "zip_code"],
}


def T(table_name):
    return f'"{SCHEMA}"."{table_name}"'


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def validate_optional_email(value, field_name, errors):
    value = (value or "").strip()
    if value and not EMAIL_RE.match(value):
        errors[field_name] = "Invalid email format"
    return value


def get_contact_or_404(session, contact_id, tenant_id, columns="*"):
    return session.execute(
        text(f"""
            SELECT {columns} FROM {T("Contact_Master")}
            WHERE contact_id = :cid AND tenant_id = :tid AND is_active = true
        """),
        {"cid": contact_id, "tid": tenant_id}
    ).fetchone()


def check_duplicate_contact(session, tenant_id, full_name, phone, exclude_contact_id=None):
    query = f"""
        SELECT contact_id FROM {T("Contact_Master")}
        WHERE tenant_id = :tid AND is_active = true
          AND LOWER(TRIM(full_name)) = LOWER(TRIM(:name))
          AND TRIM(phone) = TRIM(:phone)
    """
    params = {"tid": tenant_id, "name": full_name, "phone": phone}
    if exclude_contact_id is not None:
        query += " AND contact_id != :exclude_id"
        params["exclude_id"] = exclude_contact_id
    return session.execute(text(query), params).fetchone() is not None


# ─────────────────────────────────────────────
# Linked Companies — resolved live from Client_Contact_Mapping joined
# against Client_Master, grouped by company with all of this contact's
# roles at that company (a contact can hold more than one role at the
# same company, e.g. Primary AND Finance).
# ─────────────────────────────────────────────
def _resolve_linked_companies(session, tenant_id, contact_id):
    rows = session.execute(
        text(f"""
            SELECT ccm.client_id, ccm.role, cm.client_company_name
            FROM {T("Client_Contact_Mapping")} ccm
            JOIN {T("Client_Master")} cm ON cm.client_id = ccm.client_id
            WHERE ccm.contact_id = :cid AND cm.tenant_id = :tid
              AND cm."Client_Category_Master_ID" = :cat_id AND cm.status_id = :active_id
        """),
        {"cid": contact_id, "tid": tenant_id,
         "cat_id": COMMERCIAL_CATEGORY_ID, "active_id": ACTIVE_STATUS_ID}
    ).fetchall()

    grouped = {}
    for r in rows:
        bucket = grouped.setdefault(r.client_id, {
            "company_id": r.client_id,
            "company_name": r.client_company_name or '',
            "roles": [],
        })
        bucket["roles"].append(r.role)
    return list(grouped.values())


def serialize_contact(row, companies=None):
    return {
        "id":           row.contact_id,
        "contact_id":   row.contact_id,
        "full_name":    row.full_name or '',
        "job_title":    getattr(row, 'designation', '') or '',
        "designation":  getattr(row, 'designation', '') or '',
        "department":   getattr(row, 'department', '') or '',
        "phone":        row.phone or '',
        "email":        row.email or '',
        "address":      getattr(row, 'address', '') or '',
        "city":         '',   # city_id FK, City_Master empty — no text col on dev
        "state":        '',   # state_id FK, same
        "pin_code":     getattr(row, 'pin_code', '') or '',
        "companies":    companies or [],
        "tenant_id":    row.tenant_id,
        "created_at":   row.created_at.isoformat() if getattr(row, 'created_at', None) else None,
        "updated_at":   row.updated_at.isoformat() if getattr(row, 'updated_at', None) else None,
    }


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /contacts
# ═════════════════════════════════════════════════════════════════════════════
@contact_bp.route('/contacts', methods=['GET'])
@token_required
def list_contacts():
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        search = request.args.get('search', '').strip()

        query = f"""
            SELECT * FROM {T("Contact_Master")}
            WHERE tenant_id = :tenant_id AND is_active = true
        """
        params = {"tenant_id": tenant_id}

        if search:
            query += """ AND (full_name ILIKE :search
                               OR email ILIKE :search
                               OR phone ILIKE :search)"""
            params["search"] = f"%{search}%"

        query += " ORDER BY full_name ASC"

        rows = session.execute(text(query), params).fetchall()
        contact_ids = [row.contact_id for row in rows]
        companies_by_contact = {cid: [] for cid in contact_ids}

        if contact_ids:
            mapping_rows = session.execute(
                text(f"""
                    SELECT ccm.contact_id, ccm.client_id, ccm.role, cm.client_company_name
                    FROM {T("Client_Contact_Mapping")} ccm
                    JOIN {T("Client_Master")} cm ON cm.client_id = ccm.client_id
                    WHERE ccm.contact_id = ANY(:ids) AND cm.tenant_id = :tid
                      AND cm."Client_Category_Master_ID" = :cat_id AND cm.status_id = :active_id
                """),
                {"ids": contact_ids, "tid": tenant_id,
                 "cat_id": COMMERCIAL_CATEGORY_ID, "active_id": ACTIVE_STATUS_ID}
            ).fetchall()

            per_contact_company = {}
            for r in mapping_rows:
                key = (r.contact_id, r.client_id)
                bucket = per_contact_company.setdefault(key, {
                    "company_id": r.client_id,
                    "company_name": r.client_company_name or '',
                    "roles": [],
                })
                bucket["roles"].append(r.role)

            for (contact_id, _company_id), bucket in per_contact_company.items():
                companies_by_contact[contact_id].append(bucket)

        result = [serialize_contact(row, companies_by_contact.get(row.contact_id, [])) for row in rows]
        return jsonify(result), 200
    except Exception as e:
        current_app.logger.exception(f"Error in GET /contacts: {e}")
        return jsonify({'error': 'Failed to fetch contacts', 'details': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /contacts/<contact_id>
# ═════════════════════════════════════════════════════════════════════════════
@contact_bp.route('/contacts/<int:contact_id>', methods=['GET'])
@token_required
def get_contact(contact_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        row = get_contact_or_404(session, contact_id, tenant_id)
        if not row:
            return jsonify({'error': 'Contact not found'}), 404

        companies = _resolve_linked_companies(session, tenant_id, contact_id)
        return jsonify(serialize_contact(row, companies)), 200

    except Exception as e:
        current_app.logger.exception(f"Error in GET /contacts/{contact_id}: {e}")
        return jsonify({'error': 'Failed to fetch contact', 'details': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /contacts/<contact_id>/trainings
# Read-only training history for this Contact, matched by NAME against
# participants[] inside every Company's Training_Details.participants
# JSON (there's no real link between a batch participant and a Contact
# row today — participants are free-text names typed on the batch form —
# so this is a best-effort name match, not a guaranteed one).
# ═════════════════════════════════════════════════════════════════════════════
@contact_bp.route('/contacts/<int:contact_id>/trainings', methods=['GET'])
@token_required
def get_contact_trainings(contact_id):
    import json
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        contact = get_contact_or_404(session, contact_id, tenant_id, columns="contact_id, full_name")
        if not contact:
            return jsonify({'error': 'Contact not found'}), 404

        contact_name = (contact.full_name or '').strip().lower()
        if not contact_name:
            return jsonify([]), 200

        rows = session.execute(
            text(f"""
                SELECT tm.training_id, tm.client_id AS company_id,
                       tm.training_date AS training_from, tm.training_end_date AS training_to,
                       tm.participants, cm.client_company_name AS company_name
                FROM {T("Training_Master")} tm
                JOIN {T("Client_Master")} cm ON cm.client_id = tm.client_id
                WHERE cm.tenant_id = :tid
                  AND cm."Client_Category_Master_ID" = :cat_id AND cm.status_id = :active_id
            """),
            {"tid": tenant_id, "cat_id": COMMERCIAL_CATEGORY_ID, "active_id": ACTIVE_STATUS_ID}
        ).fetchall()

        files_cache = {}

        def get_company_files(company_id):
            if company_id not in files_cache:
                files_cache[company_id] = session.execute(
                    text(f"""
                        SELECT * FROM {T("Client_Files")}
                        WHERE client_id = :cid
                          AND file_type IN ('trainee_pretest', 'trainee_posttest', 'trainee_certificate')
                    """),
                    {"cid": company_id}
                ).fetchall()
            return files_cache[company_id]

        def find_file(company_id, file_type, prefix):
            for f in get_company_files(company_id):
                if f.file_type == file_type and (f.file_name or '').startswith(prefix):
                    return {"file_name": f.file_name, "file_url": f.file_url}
            return None

        result = []
        for row in rows:
            participants = row.participants if isinstance(row.participants, list) else []
            # participants is jsonb now — SQLAlchemy auto-deserializes it to a
            # Python list/dict directly, unlike the old text/JSON-string column.
            # Keeping a defensive str fallback in case a row was ever written
            # as a JSON string rather than true jsonb.
            if isinstance(row.participants, str):
                try:
                    participants = json.loads(row.participants)
                except (TypeError, ValueError):
                    participants = []

            matched = next(
                (p for p in participants if (p.get('name') or '').strip().lower() == contact_name),
                None
            )
            if not matched:
                continue

            participant_id = matched.get('id', '')
            certificate = find_file(row.company_id, 'trainee_certificate', f"{participant_id}__certificate__")

            training_records = []
            for tr in matched.get('trainingRecords', []):
                tr_id = tr.get('id', '')
                pre_file = find_file(row.company_id, 'trainee_pretest', f"{participant_id}__{tr_id}__preTest__")
                post_file = find_file(row.company_id, 'trainee_posttest', f"{participant_id}__{tr_id}__postTest__")

                pre_test = None
                if tr.get('preTestObtained') is not None or pre_file:
                    pre_test = {
                        "obtained": tr.get('preTestObtained'),
                        "total": tr.get('preTestTotal'),
                        "percentage": tr.get('prePercentage'),
                        "passed": tr.get('prePassed'),
                        "file": pre_file,
                    }

                post_test = None
                if tr.get('postTestObtained') is not None or post_file:
                    post_test = {
                        "obtained": tr.get('postTestObtained'),
                        "total": tr.get('postTestTotal'),
                        "percentage": tr.get('postPercentage'),
                        "passed": tr.get('postPassed'),
                        "file": post_file,
                    }

                training_records.append({
                    "mhe_type": tr.get('mheType', ''),
                    "pre_test": pre_test,
                    "post_test": post_test,
                })

            result.append({
                "company_id": row.company_id,
                "company_name": row.company_name or '',
                "training_id": row.training_id,
                "training_from": row.training_from.isoformat() if row.training_from else "",
                "training_to": row.training_to.isoformat() if row.training_to else "",
                "training_records": training_records,
                "certificate": certificate,
            })

        result.sort(key=lambda r: r["training_from"] or "", reverse=True)
        return jsonify(result), 200

    except Exception as e:
        current_app.logger.exception(f"Error in GET /contacts/{contact_id}/trainings: {e}")
        return jsonify({'error': 'Failed to fetch contact trainings', 'details': str(e)}), 500
    finally:
        session.close()

COMMERCIAL_CATEGORY_ID = 1   # Client_Category_Master.Category_Name = 'Commercial'
ACTIVE_STATUS_ID = 1         # Status_Master.status = 'Active'


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: POST /contacts
# Mandatory: full_name, phone. Rejects a duplicate — same full_name AND
# same phone (case-insensitive, whitespace-trimmed) as an existing
# active contact for this tenant.
# ═════════════════════════════════════════════════════════════════════════════
@contact_bp.route('/contacts', methods=['POST'])
@token_required
def create_contact():
    session = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}
        full_name = (data.get('full_name') or '').strip()
        phone = (data.get('phone') or '').strip()

        errors = {}
        if not full_name:
            errors['full_name'] = 'Contact name is required'
        if not phone:
            errors['phone'] = 'Phone is required'

        email = validate_optional_email(data.get('email'), 'email', errors)
        if errors:
            return jsonify({'error': 'Validation failed', 'details': errors}), 400

        tenant_id = request.current_user.tenant_id
        if not tenant_id:
            return jsonify({'error': 'User account is not associated with a tenant'}), 400

        if check_duplicate_contact(session, tenant_id, full_name, phone):
            return jsonify({
                'error': 'Validation failed',
                'details': {'full_name': 'A contact with this name and phone number already exists'}
            }), 400

        result = session.execute(
            text(f"""
                INSERT INTO {T("Contact_Master")}
                (
                    tenant_id, full_name, phone, email,
                    designation, department,
                    address, city_id, state_id, pin_code,
                    is_active, created_at, updated_at
                )
                VALUES
                (
                    :tenant_id, :full_name, :phone, :email,
                    :designation, :department,
                    :address, NULL, NULL, :pin_code,
                    true, :created_at, :created_at
                )
                RETURNING contact_id
            """),
            {
                "tenant_id":   tenant_id,
                "full_name":   full_name,
                "phone":       phone,
                "email":       email,
                "designation": data.get('designation') or data.get('job_title', ''),
                "department":  data.get('department', ''),
                "address":     data.get('address', ''),
                "pin_code":    data.get('pin_code', ''),
                "created_at":  datetime.utcnow(),
            }
        )
        new_contact_id = result.fetchone().contact_id
        session.commit()

        row = get_contact_or_404(session, new_contact_id, tenant_id)
        return jsonify(serialize_contact(row)), 201
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error in POST /contacts: {e}")
        return jsonify({'error': 'Failed to create contact', 'details': str(e)}), 500
    finally:
        session.close()

# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: PATCH /contacts/<contact_id>
# ═════════════════════════════════════════════════════════════════════════════
@contact_bp.route('/contacts/<int:contact_id>', methods=['PATCH'])
@token_required
def update_contact(contact_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        existing = get_contact_or_404(session, contact_id, tenant_id, columns="contact_id, full_name, phone")
        if not existing:
            return jsonify({'error': 'Contact not found'}), 404

        data = request.get_json(silent=True) or {}
        errors = {}

        if 'full_name' in data and not (data.get('full_name') or '').strip():
            errors['full_name'] = 'Contact name is required'
        if 'phone' in data and not (data.get('phone') or '').strip():
            errors['phone'] = 'Phone is required'
        if 'email' in data:
            validate_optional_email(data.get('email'), 'email', errors)
        if errors:
            return jsonify({'error': 'Validation failed', 'details': errors}), 400

        effective_name = (data.get('full_name') if 'full_name' in data else existing.full_name) or ''
        effective_phone = (data.get('phone') if 'phone' in data else existing.phone) or ''

        if ('full_name' in data or 'phone' in data) and effective_name.strip() and effective_phone.strip():
            if check_duplicate_contact(session, tenant_id, effective_name, effective_phone, exclude_contact_id=contact_id):
                return jsonify({
                    'error': 'Validation failed',
                    'details': {'full_name': 'A contact with this name and phone number already exists'}
                }), 400

        field_map = {
            'full_name':   'full_name',
            'job_title':   'designation',
            'designation': 'designation',
            'department':  'department',
            'phone':       'phone',
            'email':       'email',
            'address':     'address',
            'pin_code':    'pin_code',
        }

        set_clauses = []
        params = {"cid": contact_id, "tid": tenant_id}
        for incoming_key, column in field_map.items():
            if incoming_key in data:
                set_clauses.append(f"{column} = :{column}")
                params[column] = data[incoming_key]

        if not set_clauses:
            return jsonify({'error': 'No updatable fields provided'}), 400

        set_clauses.append("updated_at = :updated_at")
        params["updated_at"] = datetime.utcnow()

        session.execute(
            text(f"""
                UPDATE {T("Contact_Master")}
                SET {', '.join(set_clauses)}
                WHERE contact_id = :cid AND tenant_id = :tid
            """),
            params
        )
        session.commit()

        row = get_contact_or_404(session, contact_id, tenant_id)
        companies = _resolve_linked_companies(session, tenant_id, contact_id)
        return jsonify(serialize_contact(row, companies)), 200
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error in PATCH /contacts/{contact_id}: {e}")
        return jsonify({'error': 'Failed to update contact', 'details': str(e)}), 500
    finally:
        session.close()



# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: DELETE /contacts/<contact_id>
# ═════════════════════════════════════════════════════════════════════════════
@contact_bp.route('/contacts/<int:contact_id>', methods=['DELETE'])
@token_required
def delete_contact(contact_id):
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        existing = get_contact_or_404(session, contact_id, tenant_id, columns="contact_id")
        if not existing:
            return jsonify({'error': 'Contact not found'}), 404

        session.execute(
            text(f'DELETE FROM {T("Client_Contact_Mapping")} WHERE contact_id = :cid'),
            {"cid": contact_id}
        )
        session.execute(
            text(f"""
                UPDATE {T("Contact_Master")}
                SET is_active = false, updated_at = :updated_at
                WHERE contact_id = :cid AND tenant_id = :tid
            """),
            {"cid": contact_id, "tid": tenant_id, "updated_at": datetime.utcnow()}
        )
        session.commit()
        return jsonify({'message': 'Contact deleted'}), 200
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error in DELETE /contacts/{contact_id}: {e}")
        return jsonify({'error': 'Failed to delete contact', 'details': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# EXPORT / IMPORT
# ═════════════════════════════════════════════════════════════════════════════
CONTACT_EXPORT_FIELDS = [
    "contact_id", "full_name", "designation", "department", "phone", "email", "pin_code",
]


@contact_bp.route('/contacts/export', methods=['GET'])
@token_required
def export_contacts():
    session = SessionLocal()
    try:
        tenant_id = request.current_user.tenant_id
        rows = session.execute(
            text(f"""
                SELECT contact_id, full_name, designation, department, phone, email, pin_code
                FROM {T("Contact_Master")}
                WHERE tenant_id = :tenant_id AND is_active = true
                ORDER BY full_name ASC
            """),
            {"tenant_id": tenant_id}
        ).fetchall()

        dict_rows = [dict(row._mapping) for row in rows]
        return build_csv_response(CONTACT_EXPORT_FIELDS, dict_rows, "contacts_export.csv")
    except Exception as e:
        current_app.logger.exception(f"Error in GET /contacts/export: {e}")
        return jsonify({'error': 'Failed to export contacts', 'details': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: POST /contacts/import
# Duplicate rule: a row is skipped if a contact with the same
# full_name + phone (case-insensitive on name) already exists — matches
# the same name+phone duplicate rule used by create/update above.
# ═════════════════════════════════════════════════════════════════════════════
@contact_bp.route('/contacts/import', methods=['POST'])
@token_required
def import_contacts():
    session = SessionLocal()
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded (expected form field "file")'}), 400

        try:
            rows = parse_uploaded_rows(request.files['file'])
        except ImportFileError as e:
            return jsonify({'error': str(e)}), 400

        rows = apply_header_aliases(rows, CONTACT_HEADER_ALIASES)

        tenant_id = request.current_user.tenant_id
        

        existing_keys = set()
        for r in session.execute(
            text(f"""
                SELECT full_name, phone
                FROM {T("Contact_Master")}
                WHERE tenant_id = :tid AND is_active = true
            """),
            {"tid": tenant_id}
        ).fetchall():
            existing_keys.add((
                (r.full_name or '').strip().lower(),
                (r.phone or '').strip(),
            ))

        created, skipped, errors = 0, 0, []

        for i, row in enumerate(rows, start=2):
            full_name = (row.get('full_name') or '').strip()
            if not full_name:
                errors.append({"row": i, "error": "Missing full_name"})
                continue

            phone = (row.get('phone') or '').strip()
            if not phone:
                errors.append({"row": i, "error": "Missing phone"})
                continue

            email = (row.get('email') or '').strip()
            if email and not EMAIL_RE.match(email):
                errors.append({"row": i, "error": f"Invalid email: {email}"})
                continue

            key = (full_name.lower(), phone)
            if key in existing_keys:
                skipped += 1
                continue

            session.execute(
                text(f"""
                    INSERT INTO {T("Contact_Master")}
                    (
                        tenant_id, full_name, designation, department,
                        phone, email, pin_code,
                        is_active, created_at, updated_at
                    )
                    VALUES
                    (
                        :tenant_id, :full_name, :designation, :department,
                        :phone, :email, :pin_code,
                        true, :created_at, :created_at
                    )
                """),
                {
                    "tenant_id": tenant_id, "full_name": full_name,
                    "designation": row.get('designation', ''),
                    "department": row.get('department', ''),
                    "phone": phone, "email": email,
                    "pin_code": row.get('pin_code', ''),
                    "created_at": datetime.utcnow(),
                }
            )
            existing_keys.add(key)
            created += 1

        session.commit()
        current_app.logger.info(f"Contact import: {created} created, {skipped} skipped, {len(errors)} errors")

        return jsonify({"added": created, "created": created, "skipped": skipped, "errors": errors}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error in POST /contacts/import: {e}")
        return jsonify({'error': 'Failed to import contacts', 'details': str(e)}), 500
    finally:
        session.close()
