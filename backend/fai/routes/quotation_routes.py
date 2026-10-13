"""
Quotation Routes for FAI CRM — DEV VERSION (streemLyne_mt_dev2)
──────────────────────────────────────────────────────────────────────────
REWRITTEN to target dev's actual tables: "Quotation_Master" (header) and
"Quotation_Details" (line items) — confirmed via information_schema on
streemLyne_mt_dev2. These are DIFFERENT tables from what production uses
("Quotations"/"Quotation_Items", flat/denormalized) — dev was apparently
built against the original relational schema Sir described, not a copy
of what ended up live in prod. Do not assume this file is portable to
prod as-is; prod needs its own version targeting "Quotations".

⚠️ 2026-09-26 UPDATE — doc_type discriminator added:
proposal_routes.py stores Proposals in this SAME Quotation_Master /
Quotation_Details pair of tables (see that file's header comment). With
no way to tell a Proposal row from a Quotation row, every read/update/
delete in either file was silently operating on both — editing a
Proposal's status changed "the row with that ID," which happened to
also be shown on the Quotations list, and vice versa.

Fixed by adding a `doc_type` column (migration: ALTER TABLE ...
ADD COLUMN doc_type VARCHAR(20) NOT NULL DEFAULT 'quotation' CHECK
(doc_type IN ('quotation','proposal'))). This file now filters every
query by DOC_TYPE = 'quotation' and stamps that value on every INSERT.
proposal_routes.py does the same with its own DOC_TYPE = 'proposal'.

⚠️ OPEN ASSUMPTIONS — please confirm with Ateeb/sir:

  1. CUSTOMER INFO: Quotation_Master has no customer_name/address/phone/
     email columns, and no contact_id — only client_id. Customer display
     fields here are joined from Client_Master (client_company_name,
     address, client_phone, client_email). If quotations should show a
     specific CONTACT at that client (not just the company), a
     contact_id FK needs to be added to Quotation_Master — right now
     there's nowhere to store that.

  2. TAX: Quotation_Master.tax_id is an FK to Tax_Master (tax_id, tax_rate),
     not a stored percentage. The old frontend contract sends
     igst_percentage as a raw number (e.g. 18). _resolve_tax_id() below
     looks up Tax_Master by matching tax_rate to that number, falling
     back to the first active tax row if no exact match. This is a
     stopgap — once the frontend is touched for this rewrite, it should
     send tax_id directly instead of a percentage.

  3. STATUS: Quotation_Master had no status column at all — only
     sent_at/approved_at/submitted_for_approval_at timestamps, which
     can't represent Rejected/Expired. Added a real `status` column via
     migration_add_quotation_status.sql (run that before deploying this
     file). sent_at/approved_at are kept in sync automatically when
     status transitions to Sent/Approved, so those columns stay accurate
     for anything else that reads them directly.

  4. TOTALS: no stored total/discount_amount/tax_amount columns on
     Quotation_Master — computed on the fly from Quotation_Details line
     items + global_discount_percent + Tax_Master.tax_rate. This means
     totals always reflect current items rather than a possibly-stale
     snapshot, but it does mean every read does the arithmetic in Python
     (fine at current scale; revisit if list volume grows).

  5. EXTRA FIELDS: customer_designation, customer_company, customer_gst,
     payment_terms, mode_of_enquiry, bank_name, branch_name,
     account_number, ifsc_code, gst_number, pan_card, terms_conditions
     still have no dedicated columns on Quotation_Master (same gap as
     prod). Packed into the `notes` column as JSON, same pattern as
     before — the user's actual typed note text lives under
     "user_notes" inside that JSON.

  6. created_by_employee_id / approved_by_employee_id are NOT NULL /
     nullable FKs to Employee_Master — resolved from the logged-in user
     via Employee_Master.user_id, same lookup pattern used elsewhere in
     this codebase (e.g. the notification block in update_quotation).

  7. valid_for_days (frontend field) maps to valid_until (a real
     timestamp column here) — computed as created_at + N days on
     create, and reported back as the day difference from created_at
     on read. project_id and currency_id exist on Quotation_Master but
     nothing currently populates them from the payload — left NULL
     until there's a project/currency picker on the frontend.
"""

import json
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, timedelta
from sqlalchemy import text
from .auth_helpers import token_required
from .notification_routes import create_notification
from ..db import SessionLocal

quotation_bp = Blueprint('quotation', __name__)

TENANT_ID = 3  # Quotation_Master.tenant_id is INTEGER on dev (was varchar on prod's Quotations)

VALID_STATUSES = ('Draft', 'Sent', 'Approved', 'Rejected', 'Expired')

# Discriminator value for this file's rows — see header comment. Every
# query below must filter/stamp this so Quotations and Proposals (which
# share Quotation_Master/Quotation_Details) never collide.
DOC_TYPE = 'quotation'


# ═════════════════════════════════════════════════════════════════════════════
# notes-JSON packing — unchanged pattern for the fields that still have
# nowhere else to live
# ═════════════════════════════════════════════════════════════════════════════
def _pack_notes(d: dict) -> str:
    payload = {
        # Sent directly by the quotation form (populated from the company+
        # contact picker, but editable afterward) — stored verbatim rather
        # than re-derived from Client_Master, since the user may have typed
        # over what the picker filled in.
        "customer_name":        d.get("customer_name", ""),
        "customer_address":     d.get("customer_address", ""),
        "customer_mobile":      d.get("customer_mobile", ""),
        "customer_email":       d.get("customer_email", ""),
        "customer_designation": d.get("customer_designation", ""),
        "customer_company":     d.get("customer_company", ""),
        "customer_gst":         d.get("customer_gst", ""),
        "payment_terms":        d.get("payment_terms", ""),
        "mode_of_enquiry":      d.get("mode_of_enquiry", "Email"),
        "bank_name":            d.get("bank_name", "Oriental Bank of Commerce"),
        "branch_name":          d.get("branch_name", "Kondwa Branch, Pune"),
        "account_number":       d.get("account_number", "11281132000200"),
        "ifsc_code":            d.get("ifsc_code", "ORBC0101128"),
        "gst_number":           d.get("gst_number", "27AAFFF1562M1Z8"),
        "pan_card":             d.get("pan_card", "AAFFF1562M"),
        "terms_conditions":     d.get("terms_conditions", []),
        "user_notes":           d.get("notes", ""),
    }
    return json.dumps(payload)


def _unpack_notes(notes_str) -> dict:
    if not notes_str:
        return {}
    try:
        return json.loads(notes_str)
    except Exception:
        return {"user_notes": notes_str}


# ═════════════════════════════════════════════════════════════════════════════
# Lookup helpers
# ═════════════════════════════════════════════════════════════════════════════
def _get_employee_id(session, user_id):
    """Resolve the Employee_Master employee_id for the logged-in user."""
    result = session.execute(
        text("""
            SELECT employee_id
            FROM "streemLyne_mt_dev2"."User_Master"
            WHERE user_id = :user_id
              AND tenant_id = :tenant_id
              AND is_active = TRUE
            LIMIT 1
        """),
        {
            "user_id": user_id,
            "tenant_id": TENANT_ID,
        }
    ).fetchone()

    return result.employee_id if result else None


def _get_client_info(session, client_id) -> dict:
    """FALLBACK ONLY — company-level info from Client_Master, used only
    when a quotation's notes JSON doesn't already carry customer_name/
    address/mobile/email (e.g. rows saved before this fix, or if a
    quotation was ever created without going through the form's company+
    contact picker). The authoritative source is the notes JSON, since
    the quotation form lets the user edit these fields after the picker
    fills them in, and what they typed needs to be preserved verbatim —
    not silently overwritten by a fresh Client_Master join on every read."""
    if not client_id:
        return {}
    row = session.execute(
        text("""
            SELECT client_company_name, address, client_phone, client_email
            FROM "streemLyne_mt_dev2"."Client_Master"
            WHERE client_id = :cid
        """),
        {"cid": client_id}
    ).fetchone()
    if not row:
        return {}
    return {
        "customer_name":    row.client_company_name or "",
        "customer_address": row.address or "",
        "customer_mobile":  row.client_phone or "",
        "customer_email":   row.client_email or "",
    }


def _resolve_tax_id(session, igst_percentage, existing_tax_id=None):
    """Quotation_Master.tax_id is an FK to Tax_Master; the old frontend
    contract sends a raw percentage instead. Look up a matching active
    tax row by rate; if the payload already carries a tax_id, prefer
    that. Falls back to the first active tax row if no exact match —
    flag if that fallback is ever hit in practice (see assumption #2)."""
    if existing_tax_id:
        return existing_tax_id
    if igst_percentage is None:
        igst_percentage = 18
    row = session.execute(
        text("""
            SELECT tax_id FROM "streemLyne_mt_dev2"."Tax_Master"
            WHERE tax_rate = :rate AND is_active = true
            LIMIT 1
        """),
        {"rate": igst_percentage}
    ).fetchone()
    if row:
        return row.tax_id
    fallback = session.execute(
        text('SELECT tax_id FROM "streemLyne_mt_dev2"."Tax_Master" WHERE is_active = true ORDER BY tax_id LIMIT 1')
    ).fetchone()
    return fallback.tax_id if fallback else None


def _get_tax_rate(session, tax_id):
    if not tax_id:
        return 0
    row = session.execute(
        text('SELECT tax_rate FROM "streemLyne_mt_dev2"."Tax_Master" WHERE tax_id = :tid'),
        {"tid": tax_id}
    ).fetchone()
    return float(row.tax_rate) if row else 0


# ═════════════════════════════════════════════════════════════════════════════
# Quotation_Details (line items) — shared 1:1 with proposal_routes.py via
# quotation_id, no doc_type needed here since it's scoped by the parent's id
# ═════════════════════════════════════════════════════════════════════════════
def _get_quotation_items(session, quotation_id) -> list:
    rows = session.execute(
        text("""
            SELECT item_id, quotation_id, item_name, description, section,
                   quantity, amount, discount_type, discount_percent,
                   discounted_amount, section_discount_percent,
                   variant_id, pricelist_id, spl_id,
                   unit_cost_snapshot, unit_price_snapshot
            FROM "streemLyne_mt_dev2"."Quotation_Details"
            WHERE quotation_id = :qid
            ORDER BY item_id
        """),
        {"qid": quotation_id}
    ).fetchall()

    items = []
    for r in rows:
        unit_rate = float(r.unit_price_snapshot or 0)
        items.append({
            "item_id":                  r.item_id,
            "variant_id":               r.variant_id,
            "quantity":                 int(r.quantity or 0),
            "amount":                   float(r.amount or 0),
            "pricelist_id":             r.pricelist_id,
            "spl_id":                   r.spl_id,
            "discount_type":            r.discount_type or "none",
            "discount_percent":         float(r.discount_percent or 0),
            "section_discount_percent": float(r.section_discount_percent or 0),
            "discounted_amount":        float(r.discounted_amount) if r.discounted_amount is not None else 0,
            "unit_rate":                unit_rate,
            "unit_cost":                float(r.unit_cost_snapshot) if r.unit_cost_snapshot is not None else None,
            "service_title":            r.item_name or r.description or "-",
            "service_rate":             unit_rate,
            "section":                  r.section,
        })
    return items


def _replace_quotation_items(session, quotation_id, tenant_id, items: list):
    session.execute(
        text('DELETE FROM "streemLyne_mt_dev2"."Quotation_Details" WHERE quotation_id = :qid'),
        {"qid": quotation_id}
    )
    for item in (items or []):
        item_name = (item.get("service_title") or item.get("description") or "Item").strip() or "Item"
        quantity = int(item.get("quantity") or 1)
        unit_rate = float(item.get("service_rate") or item.get("unit_rate") or 0)
        # The frontend's item payload doesn't send "amount" at all — it only
        # sends quantity + service_rate and computes amount client-side for
        # display. Mirror that same rule here (qty=0 → flat rate, else
        # qty × rate) rather than trusting a possibly-absent "amount" key,
        # which was silently defaulting to 0 and zeroing out every total.
        if "amount" in item and item.get("amount") not in (None, ""):
            amount = float(item["amount"])
        else:
            amount = unit_rate if quantity == 0 else quantity * unit_rate

        session.execute(
            text("""
                INSERT INTO "streemLyne_mt_dev2"."Quotation_Details" (
                    quotation_id, tenant_id, item_name, description, section,
                    quantity, amount, discount_type, discount_percent,
                    discounted_amount, section_discount_percent,
                    variant_id, pricelist_id, spl_id, unit_price_snapshot
                ) VALUES (
                    :quotation_id, :tenant_id, :item_name, :description, :section,
                    :quantity, :amount, :discount_type, :discount_percent,
                    :discounted_amount, :section_discount_percent,
                    :variant_id, :pricelist_id, :spl_id, :unit_price_snapshot
                )
            """),
            {
                "quotation_id":             quotation_id,
                "tenant_id":                tenant_id,
                "item_name":                item_name,
                "description":              item.get("description", ""),
                "section":                  item.get("section"),
                "quantity":                 quantity,
                "amount":                   amount,
                "discount_type":            item.get("discount_type", "none"),
                "discount_percent":         float(item.get("discount_percent") or 0),
                "discounted_amount":        item.get("discounted_amount"),
                "section_discount_percent": float(item.get("section_discount_percent") or 0),
                "variant_id":               item.get("variant_id"),
                "pricelist_id":             item.get("pricelist_id"),
                "spl_id":                   item.get("spl_id"),
                "unit_price_snapshot":      unit_rate,
            }
        )


# ═════════════════════════════════════════════════════════════════════════════
# Totals — computed from line items + discount + tax, since Quotation_Master
# stores none of these as final numbers (assumption #4)
# ═════════════════════════════════════════════════════════════════════════════
def _compute_totals(items: list, global_discount_percent: float, tax_rate: float) -> dict:
    sub_total = sum(i["amount"] for i in items)
    discount_amount = sub_total * (global_discount_percent or 0) / 100
    taxable_amount = sub_total - discount_amount
    tax_amount = taxable_amount * (tax_rate or 0) / 100
    total = taxable_amount + tax_amount
    return {
        "sub_total":       sub_total,
        "discount_amount": discount_amount,
        "tax_amount":      tax_amount,
        "total":           total,
    }


def _serialize_quotation(row, meta: dict, items: list, client_info: dict, tax_rate: float) -> dict:
    totals = _compute_totals(items, float(row.global_discount_percent or 0), tax_rate)
    valid_for_days = None
    if row.valid_until and row.created_at:
        valid_for_days = (row.valid_until - row.created_at).days

    return {
        "id":                   row.quotation_id,
        "quotation_id":         row.quotation_id,
        "quotation_number":     row.reference_number,
        "date":                 row.created_at.isoformat() if row.created_at else None,
        "client_id":            row.client_id,
        "project_id":           row.project_id,
        # notes JSON is authoritative (what the user actually typed/saved);
        # Client_Master join is only a fallback for rows that predate it
        # or never had these fields captured.
        "customer_name":        meta.get("customer_name") or client_info.get("customer_name", ""),
        "customer_designation": meta.get("customer_designation", ""),
        "customer_company":     meta.get("customer_company", ""),
        "customer_address":     meta.get("customer_address") or client_info.get("customer_address", ""),
        "customer_mobile":      meta.get("customer_mobile") or client_info.get("customer_mobile", ""),
        "customer_email":       meta.get("customer_email") or client_info.get("customer_email", ""),
        "customer_gst":         meta.get("customer_gst", ""),
        "payment_terms":        meta.get("payment_terms", ""),
        "mode_of_enquiry":      meta.get("mode_of_enquiry", "Email"),
        "sub_total":            totals["sub_total"],
        "discount_percentage":  float(row.global_discount_percent or 0),
        "discount_amount":      totals["discount_amount"],
        "igst_percentage":      tax_rate,
        "igst_amount":          totals["tax_amount"],
        "grand_total":          totals["total"],
        "total_amount":         totals["total"],
        "bank_name":            meta.get("bank_name", "Oriental Bank of Commerce"),
        "branch_name":          meta.get("branch_name", "Kondwa Branch, Pune"),
        "account_number":       meta.get("account_number", "11281132000200"),
        "ifsc_code":            meta.get("ifsc_code", "ORBC0101128"),
        "gst_number":           meta.get("gst_number", "27AAFFF1562M1Z8"),
        "pan_card":             meta.get("pan_card", "AAFFF1562M"),
        "valid_for_days":       valid_for_days if valid_for_days is not None else 30,
        "valid_until":          row.valid_until.isoformat() if row.valid_until else None,
        "terms_conditions":     meta.get("terms_conditions", []),
        "notes":                meta.get("user_notes", ""),
        "status":               row.status,
        "sent_at":              row.sent_at.isoformat() if row.sent_at else None,
        "approved_at":          row.approved_at.isoformat() if row.approved_at else None,
        "created_at":           row.created_at.isoformat() if row.created_at else None,
        "items":                items,
    }


# ═════════════════════════════════════════════════════════════════════════════
# GET /quotations
# ═════════════════════════════════════════════════════════════════════════════
@quotation_bp.route('/quotations', methods=['GET', 'OPTIONS'])
@token_required
def list_quotations():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = SessionLocal()
    try:
        rows = session.execute(
            text("""
                SELECT qm.quotation_id, qm.reference_number, qm.created_at, qm.client_id,
                       qm.status, qm.global_discount_percent, qm.tax_id, qm.notes,
                       tm.tax_rate,
                       cm.client_company_name AS fallback_customer_name,
                       COALESCE(items.sub_total, 0) AS sub_total
                FROM "streemLyne_mt_dev2"."Quotation_Master" qm
                LEFT JOIN "streemLyne_mt_dev2"."Client_Master" cm ON cm.client_id = qm.client_id
                LEFT JOIN "streemLyne_mt_dev2"."Tax_Master" tm ON tm.tax_id = qm.tax_id
                LEFT JOIN (
                    SELECT quotation_id, SUM(amount) AS sub_total
                    FROM "streemLyne_mt_dev2"."Quotation_Details"
                    GROUP BY quotation_id
                ) items ON items.quotation_id = qm.quotation_id
                WHERE qm.tenant_id = :tid
                  AND qm.doc_type = :doc_type
                ORDER BY qm.created_at DESC
            """),
            {"tid": TENANT_ID, "doc_type": DOC_TYPE}
        ).fetchall()

        result = []
        for r in rows:
            sub_total = float(r.sub_total or 0)
            discount_amount = sub_total * float(r.global_discount_percent or 0) / 100
            taxable = sub_total - discount_amount
            tax_amount = taxable * float(r.tax_rate or 0) / 100
            total = taxable + tax_amount
            meta = _unpack_notes(r.notes)
            customer_name = meta.get("customer_name") or r.fallback_customer_name or "—"
            result.append({
                "id":               r.quotation_id,
                "quotation_id":     r.quotation_id,
                "quotation_number": r.reference_number,
                "date":             r.created_at.isoformat() if r.created_at else None,
                "client_id":        r.client_id,
                "customer_name":    customer_name,
                "grand_total":      total,
                "total_amount":     total,
                "status":           r.status,
                "created_at":       r.created_at.isoformat() if r.created_at else None,
            })
        return jsonify(result), 200
    except Exception as e:
        current_app.logger.error(f"Quotation list error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# GET /quotations/<id>
# ═════════════════════════════════════════════════════════════════════════════
@quotation_bp.route('/quotations/<int:quotation_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_quotation(quotation_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = SessionLocal()
    try:
        row = session.execute(
            text("""
                SELECT * FROM "streemLyne_mt_dev2"."Quotation_Master"
                WHERE quotation_id = :qid AND doc_type = :doc_type
            """),
            {"qid": quotation_id, "doc_type": DOC_TYPE}
        ).fetchone()
        if not row:
            return jsonify({"error": "Quotation not found"}), 404

        meta = _unpack_notes(row.notes)
        items = _get_quotation_items(session, quotation_id)
        client_info = _get_client_info(session, row.client_id)
        tax_rate = _get_tax_rate(session, row.tax_id)

        return jsonify(_serialize_quotation(row, meta, items, client_info, tax_rate)), 200
    except Exception as e:
        current_app.logger.error(f"Quotation get error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# POST /quotations
# ═════════════════════════════════════════════════════════════════════════════
@quotation_bp.route('/quotations', methods=['POST', 'OPTIONS'])
@token_required
def create_quotation():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = SessionLocal()
    try:
        d = request.get_json() or {}

        reference_number = (d.get("quotation_number") or "").strip()
        if not reference_number:
            return jsonify({"error": "quotation_number is required"}), 400

        employee_id = _get_employee_id(session, request.current_user.id)
        if not employee_id:
            return jsonify({"error": "No Employee_Master record found for the current user"}), 400

        tax_id = _resolve_tax_id(session, d.get("igst_percentage"), d.get("tax_id"))
        discount_pct = float(d.get("discount_percentage", 0))
        notes_str = _pack_notes(d)
        valid_for_days = int(d.get("valid_for_days") or 30)
        valid_until = datetime.utcnow() + timedelta(days=valid_for_days)

        result = session.execute(
            text("""
                INSERT INTO "streemLyne_mt_dev2"."Quotation_Master" (
                    tenant_id, client_id, project_id, reference_number,
                    notes, valid_until, created_by_employee_id,
                    global_discount_percent, currency_id, tax_id, status, doc_type
                ) VALUES (
                    :tenant_id, :client_id, :project_id, :reference_number,
                    :notes, :valid_until, :created_by_employee_id,
                    :discount_pct, :currency_id, :tax_id, :status, :doc_type
                )
                RETURNING quotation_id
            """),
            {
                "tenant_id":              TENANT_ID,
                "client_id":              d.get("client_id"),
                "project_id":             d.get("project_id"),
                "reference_number":       reference_number,
                "notes":                  notes_str,
                "valid_until":            valid_until,
                "created_by_employee_id": employee_id,
                "discount_pct":           discount_pct,
                "currency_id":            d.get("currency_id"),
                "tax_id":                 tax_id,
                "status":                 d.get("status", "Draft"),
                "doc_type":               DOC_TYPE,
            }
        )
        quotation_id = result.fetchone()[0]

        _replace_quotation_items(session, quotation_id, TENANT_ID, d.get("items", []))

        session.commit()
        return jsonify({"quotation_id": quotation_id, "id": quotation_id}), 201

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Quotation create error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# PUT /quotations/<id>
# ═════════════════════════════════════════════════════════════════════════════
@quotation_bp.route('/quotations/<int:quotation_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_quotation(quotation_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = SessionLocal()
    try:
        d = request.get_json() or {}

        # Status-only update (from list page dropdown)
        if list(d.keys()) == ['status']:
            new_status = d["status"]
            if new_status not in VALID_STATUSES:
                return jsonify({"error": f"Invalid status: {new_status}"}), 400

            old_row = session.execute(
                text("""
                    SELECT status, client_id, reference_number, notes
                    FROM "streemLyne_mt_dev2"."Quotation_Master"
                    WHERE quotation_id=:qid AND doc_type = :doc_type
                """),
                {"qid": quotation_id, "doc_type": DOC_TYPE}
            ).fetchone()
            if not old_row:
                return jsonify({"error": "Quotation not found"}), 404

            update_fields = {"status": new_status, "qid": quotation_id, "doc_type": DOC_TYPE}
            set_clauses = ["status = :status", "updated_at = NOW()"]

            # Keep sent_at/approved_at in sync with status, since other
            # code may still read those timestamps directly.
            if new_status == 'Sent':
                set_clauses.append("sent_at = NOW()")
            elif new_status == 'Approved':
                approver_id = _get_employee_id(session, request.current_user.id)
                set_clauses.append("approved_at = NOW()")
                set_clauses.append("approved_by_employee_id = :approver_id")
                update_fields["approver_id"] = approver_id

            session.execute(
                text(f"""
                    UPDATE "streemLyne_mt_dev2"."Quotation_Master"
                    SET {", ".join(set_clauses)}
                    WHERE quotation_id=:qid AND doc_type = :doc_type
                """),
                update_fields
            )
            session.commit()

            if new_status in ('Sent', 'Approved', 'Rejected', 'Expired'):
                old_meta = _unpack_notes(old_row.notes)
                client_info = _get_client_info(session, old_row.client_id)
                qnum = old_row.reference_number or f"QUO-{quotation_id:04d}"
                cust = old_meta.get("customer_name") or client_info.get("customer_name") or "Client"
                emp_id = _get_employee_id(session, request.current_user.id)
                msg_map = {
                    'Sent':     f"📤 Quotation {qnum} for {cust} has been marked as Sent",
                    'Approved': f"✅ Quotation {qnum} for {cust} has been Approved",
                    'Rejected': f"❌ Quotation {qnum} for {cust} has been Rejected",
                    'Expired':  f"⌛ Quotation {qnum} for {cust} has Expired",
                }
                create_notification(
                    session,
                    message=msg_map[new_status],
                    notification_type="quotation",
                    client_id=old_row.client_id,
                    created_by_employee_id=emp_id,
                    priority="high" if new_status == 'Approved' else "medium",
                )
                session.commit()

            return jsonify({"quotation_id": quotation_id}), 200

        reference_number = (d.get("quotation_number") or "").strip()
        if not reference_number:
            return jsonify({"error": "quotation_number is required"}), 400

        tax_id = _resolve_tax_id(session, d.get("igst_percentage"), d.get("tax_id"))
        discount_pct = float(d.get("discount_percentage", 0))
        notes_str = _pack_notes(d)

        existing = session.execute(
            text("""
                SELECT created_at FROM "streemLyne_mt_dev2"."Quotation_Master"
                WHERE quotation_id=:qid AND doc_type = :doc_type
            """),
            {"qid": quotation_id, "doc_type": DOC_TYPE}
        ).fetchone()
        if not existing:
            return jsonify({"error": "Quotation not found"}), 404

        valid_for_days = int(d.get("valid_for_days") or 30)
        valid_until = (existing.created_at or datetime.utcnow()) + timedelta(days=valid_for_days)

        session.execute(
            text("""
                UPDATE "streemLyne_mt_dev2"."Quotation_Master" SET
                    client_id=:client_id, project_id=:project_id,
                    reference_number=:reference_number, notes=:notes,
                    valid_until=:valid_until, global_discount_percent=:discount_pct,
                    currency_id=:currency_id, tax_id=:tax_id, updated_at=NOW()
                WHERE quotation_id=:quotation_id AND doc_type = :doc_type
            """),
            {
                "quotation_id":     quotation_id,
                "client_id":        d.get("client_id"),
                "project_id":       d.get("project_id"),
                "reference_number": reference_number,
                "notes":            notes_str,
                "valid_until":      valid_until,
                "discount_pct":     discount_pct,
                "currency_id":      d.get("currency_id"),
                "tax_id":           tax_id,
                "doc_type":         DOC_TYPE,
            }
        )

        _replace_quotation_items(session, quotation_id, TENANT_ID, d.get("items", []))

        session.commit()
        return jsonify({"quotation_id": quotation_id}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Quotation update error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# DELETE /quotations/<id>
# ═════════════════════════════════════════════════════════════════════════════
@quotation_bp.route('/quotations/<int:quotation_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_quotation(quotation_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = SessionLocal()
    try:
        # Confirm this id actually belongs to a Quotation before touching
        # it — without this check a stray call could delete a Proposal
        # that happens to share the same quotation_id-space.
        owned = session.execute(
            text("""
                SELECT 1 FROM "streemLyne_mt_dev2"."Quotation_Master"
                WHERE quotation_id = :qid AND doc_type = :doc_type
            """),
            {"qid": quotation_id, "doc_type": DOC_TYPE}
        ).fetchone()
        if not owned:
            return jsonify({"error": "Quotation not found"}), 404

        session.execute(
            text('DELETE FROM "streemLyne_mt_dev2"."Quotation_Details" WHERE quotation_id=:qid'),
            {"qid": quotation_id}
        )
        session.execute(
            text("""
                DELETE FROM "streemLyne_mt_dev2"."Quotation_Master"
                WHERE quotation_id=:qid AND doc_type = :doc_type
            """),
            {"qid": quotation_id, "doc_type": DOC_TYPE}
        )
        session.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Quotation delete error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# POST /quotations/<id>/convert-to-invoice
# ⚠️ UNCHANGED SCOPE NOTE: Invoice_Master's existence/columns on dev are
# still unverified (see prior conversation). This endpoint is left mostly
# as-is aside from pulling customer info the new way; confirm
# Invoice_Master exists on streemLyne_mt_dev2 before relying on it.
# ═════════════════════════════════════════════════════════════════════════════
@quotation_bp.route('/quotations/<int:quotation_id>/convert-to-invoice', methods=['POST', 'OPTIONS'])
@token_required
def convert_quotation_to_invoice(quotation_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = SessionLocal()
    try:
        row = session.execute(
            text("""
                SELECT * FROM "streemLyne_mt_dev2"."Quotation_Master"
                WHERE quotation_id = :qid AND doc_type = :doc_type
            """),
            {"qid": quotation_id, "doc_type": DOC_TYPE}
        ).fetchone()
        if not row:
            return jsonify({"error": "Quotation not found"}), 404

        meta = _unpack_notes(row.notes)
        items = _get_quotation_items(session, quotation_id)
        client_info = _get_client_info(session, row.client_id)
        tax_rate = _get_tax_rate(session, row.tax_id)
        totals = _compute_totals(items, float(row.global_discount_percent or 0), tax_rate)

        invoice_meta = dict(meta)
        invoice_meta["items"] = items
        description_str = json.dumps(invoice_meta)

        result = session.execute(
            text("""
                INSERT INTO "streemLyne_mt_dev2"."Invoice_Master" (
                    tenant_id, client_id, invoice_number, invoice_date,
                    customer_name, customer_address, customer_phone, customer_email,
                    sub_total, subtotal, discount_percent, discount_amount,
                    vat_rate, vat_amount, total_amount,
                    notes, status, payment_status, description
                ) VALUES (
                    :tenant_id, :client_id, :invoice_number, :invoice_date,
                    :customer_name, :customer_address, :customer_phone, :customer_email,
                    :sub_total, :sub_total, :discount_pct, :discount_amt,
                    :igst_pct, :igst_amt, :total_amount,
                    :notes, 'Draft', 'Not Paid', :description
                )
                RETURNING invoice_id
            """),
            {
                "tenant_id":        TENANT_ID,
                "client_id":        row.client_id,
                "invoice_number":   f"INV-{datetime.now().strftime('%Y%m')}-{quotation_id:04d}",
                "invoice_date":     datetime.now().date().isoformat(),
                "customer_name":    meta.get("customer_name") or client_info.get("customer_name", ""),
                "customer_address": meta.get("customer_address") or client_info.get("customer_address", ""),
                "customer_phone":   meta.get("customer_mobile") or client_info.get("customer_mobile", ""),
                "customer_email":   meta.get("customer_email") or client_info.get("customer_email", ""),
                "sub_total":        totals["sub_total"],
                "discount_pct":     float(row.global_discount_percent or 0),
                "discount_amt":     totals["discount_amount"],
                "igst_pct":         tax_rate,
                "igst_amt":         totals["tax_amount"],
                "total_amount":     totals["total"],
                "notes":            meta.get("user_notes", ""),
                "description":      description_str,
            }
        )
        invoice_id = result.fetchone()[0]
        session.commit()
        return jsonify({"invoice_id": invoice_id, "id": invoice_id}), 201

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Quotation->Invoice conversion error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# PDF drawing helpers — the original download_quotation_pdf body was lost
# (the source we had only carried a placeholder comment, not real code),
# so this is a fresh implementation built to match the existing view page
# (Quotation Information / Training Items / Financial Summary / Terms /
# Notes) using the PDF class + draw_section_label/kv_row from pdf_helpers.py.
# ═════════════════════════════════════════════════════════════════════════════
def _format_pdf_date(iso_str):
    if not iso_str:
        return "-"
    try:
        s = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.strftime("%d %B %Y")
    except Exception:
        return iso_str


def _number_to_words(num: int) -> str:
    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
    teens = ["Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
             "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    if num == 0:
        return "Zero"

    def b(n):
        if n == 0:
            return ""
        if n < 10:
            return ones[n]
        if n < 20:
            return teens[n - 10]
        if n < 100:
            return tens[n // 10] + (" " + ones[n % 10] if n % 10 else "")
        return ones[n // 100] + " Hundred" + (" " + b(n % 100) if n % 100 else "")

    crore = num // 10000000
    lakh = (num % 10000000) // 100000
    thousand = (num % 100000) // 1000
    rest = num % 1000
    res = ""
    if crore:
        res += b(crore) + " Crore "
    if lakh:
        res += b(lakh) + " Lakh "
    if thousand:
        res += b(thousand) + " Thousand "
    if rest:
        res += b(rest)
    return res.strip() + " Only"


def _wrap_lines(pdf, text_str, width):
    """Split text into lines that fit `width` mm at the pdf's current font.
    Uses fpdf2's multi_cell(split_only=True) where available; falls back
    to a rough char-count estimate on older fpdf/fpdf2 versions that
    renamed/removed that kwarg."""
    text_str = text_str or "-"
    try:
        lines = pdf.multi_cell(width, 4, text_str, split_only=True)
        if lines:
            return lines
    except TypeError:
        pass
    # Fallback: estimate ~1.8mm per character at this font size
    chars_per_line = max(int(width / 1.8), 8)
    words = text_str.split(" ")
    lines, current = [], ""
    for w in words:
        trial = (current + " " + w).strip()
        if len(trial) > chars_per_line and current:
            lines.append(current)
            current = w
        else:
            current = trial
    if current:
        lines.append(current)
    return lines or ["-"]


def _draw_quotation_info(pdf, quotation):
    from .pdf_helpers import BROWN_MID, BROWN_TEXT, BROWN_ACCENT, kv_row

    margin = pdf.l_margin
    usable_w = pdf.w - pdf.l_margin - pdf.r_margin
    col_w = (usable_w - 10) / 2
    left_x = margin
    right_x = margin + col_w + 10
    top_y = pdf.get_y()

    # Left column — "To"
    pdf.set_xy(left_x, top_y)
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(*BROWN_MID)
    pdf.cell(col_w, 4, 'TO', 0, 2, 'L')

    pdf.set_x(left_x)
    pdf.set_font('Arial', 'B', 9)
    pdf.set_text_color(*BROWN_TEXT)
    pdf.cell(col_w, 5, quotation.get('customer_name') or '-', 0, 2, 'L')

    if quotation.get('customer_designation'):
        pdf.set_x(left_x)
        pdf.set_font('Arial', '', 8)
        pdf.set_text_color(*BROWN_ACCENT)
        pdf.cell(col_w, 4.5, quotation['customer_designation'], 0, 2, 'L')

    if quotation.get('customer_company'):
        pdf.set_x(left_x)
        pdf.set_font('Arial', '', 8)
        pdf.set_text_color(*BROWN_ACCENT)
        pdf.cell(col_w, 4.5, quotation['customer_company'], 0, 2, 'L')

    if quotation.get('customer_address'):
        pdf.set_x(left_x)
        pdf.set_font('Arial', '', 7.5)
        pdf.set_text_color(*BROWN_MID)
        pdf.multi_cell(col_w, 4, quotation['customer_address'])

    if quotation.get('customer_mobile'):
        pdf.set_x(left_x)
        pdf.set_font('Arial', '', 7.5)
        pdf.set_text_color(*BROWN_ACCENT)
        pdf.cell(col_w, 4.5, f"Mobile: {quotation['customer_mobile']}", 0, 2, 'L')

    if quotation.get('customer_email'):
        pdf.set_x(left_x)
        pdf.set_font('Arial', '', 7.5)
        pdf.set_text_color(*BROWN_ACCENT)
        pdf.cell(col_w, 4.5, f"Email: {quotation['customer_email']}", 0, 2, 'L')

    left_end_y = pdf.get_y()

    # Right column — "Details"
    pdf.set_xy(right_x, top_y)
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(*BROWN_MID)
    pdf.cell(col_w, 4, 'DETAILS', 0, 2, 'L')

    quotation_number = quotation.get('quotation_number') or f"QUO-{quotation.get('id', 0):04d}"
    date_str = _format_pdf_date(quotation.get('date') or quotation.get('created_at'))
    details_rows = [
        ('Quotation #', quotation_number),
        ('Date', date_str),
        ('Payment terms', quotation.get('payment_terms') or '-'),
        ('Valid for', f"{quotation.get('valid_for_days') or 30} days"),
    ]
    for label, value in details_rows:
        pdf.set_x(right_x)
        kv_row(pdf, label, value, lw=col_w * 0.5, full_w=col_w)

    right_end_y = pdf.get_y()
    pdf.set_y(max(left_end_y, right_end_y) + 4)


def _draw_items_table_header(pdf, col_widths, margin):
    from .pdf_helpers import BROWN_DARK, CREAM

    pdf.set_font('Arial', 'B', 8)
    pdf.set_fill_color(*BROWN_DARK)
    pdf.set_text_color(*CREAM)
    x = margin
    headers = [('sr', 'Sr.', 'C'), ('code', 'Code', 'L'), ('desc', 'Description', 'L'),
               ('nop', 'N.O.P', 'C'), ('rate', 'Unit rate', 'R'), ('amount', 'Amount', 'R')]
    for key, label, align in headers:
        pdf.set_xy(x, pdf.get_y())
        pdf.cell(col_widths[key], 7, label, 0, 0, align, fill=True)
        x += col_widths[key]
    pdf.ln(7)


def _draw_items_table(pdf, items):
    from .pdf_helpers import BROWN_TEXT, PARCHMENT_1, PARCHMENT_2

    margin = pdf.l_margin
    usable_w = pdf.w - pdf.l_margin - pdf.r_margin
    col_widths = {
        'sr': 10, 'code': 20, 'nop': 16, 'rate': 27, 'amount': 27,
    }
    col_widths['desc'] = usable_w - sum(col_widths.values())

    _draw_items_table_header(pdf, col_widths, margin)

    if not items:
        pdf.set_font('Arial', '', 8)
        pdf.set_text_color(*BROWN_TEXT)
        pdf.set_fill_color(*PARCHMENT_1)
        pdf.cell(usable_w, 8, 'No items found', 1, 1, 'C', fill=True)
        return

    for idx, item in enumerate(items):
        qty = item.get('quantity') or 0
        rate = item.get('service_rate') or item.get('unit_rate') or 0
        amount = rate if qty == 0 else qty * rate
        desc_text = item.get('service_title') or '-'
        code_text = item.get('service_code') or '-'

        pdf.set_font('Arial', '', 7.5)
        lines = _wrap_lines(pdf, desc_text, col_widths['desc'] - 2)
        row_h = max(8, len(lines) * 4 + 2)

        y0 = pdf.get_y()
        if y0 + row_h > pdf.page_break_trigger:
            pdf.add_page()
            _draw_items_table_header(pdf, col_widths, margin)
            y0 = pdf.get_y()

        fill_color = PARCHMENT_1 if idx % 2 == 0 else PARCHMENT_2
        pdf.set_fill_color(*fill_color)
        pdf.rect(margin, y0, usable_w, row_h, 'F')
        pdf.set_text_color(*BROWN_TEXT)

        vcenter_y = y0 + max((row_h - 4) / 2, 2)
        x = margin

        pdf.set_font('Arial', '', 7.5)
        pdf.set_xy(x, vcenter_y)
        pdf.cell(col_widths['sr'], 4, str(idx + 1), 0, 0, 'C')
        x += col_widths['sr']

        pdf.set_font('Arial', 'B', 7.5)
        pdf.set_xy(x, vcenter_y)
        pdf.cell(col_widths['code'], 4, code_text, 0, 0, 'L')
        x += col_widths['code']

        pdf.set_font('Arial', '', 7.5)
        pdf.set_xy(x, y0 + 2)
        pdf.multi_cell(col_widths['desc'] - 2, 4, desc_text)
        x += col_widths['desc']

        pdf.set_xy(x, vcenter_y)
        pdf.cell(col_widths['nop'], 4, str(qty), 0, 0, 'C')
        x += col_widths['nop']

        pdf.set_xy(x, vcenter_y)
        pdf.cell(col_widths['rate'], 4, f"Rs. {rate:,.2f}", 0, 0, 'R')
        x += col_widths['rate']

        pdf.set_font('Arial', 'B', 7.5)
        pdf.set_xy(x, vcenter_y)
        pdf.cell(col_widths['amount'], 4, f"Rs. {amount:,.2f}", 0, 0, 'R')

        pdf.set_xy(margin, y0 + row_h)


def _draw_financial_summary(pdf, quotation):
    from .pdf_helpers import BROWN_DARK, BROWN_MID, BROWN_TEXT, BROWN_BORDER, BROWN_ACCENT, CREAM, kv_row

    margin = pdf.l_margin
    usable_w = pdf.w - pdf.l_margin - pdf.r_margin
    col_w = (usable_w - 10) / 2
    left_x = margin
    right_x = margin + col_w + 10
    top_y = pdf.get_y()

    # Left — Our Bankers
    pdf.set_xy(left_x, top_y)
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(*BROWN_MID)
    pdf.cell(col_w, 4, 'OUR BANKERS', 0, 2, 'L')
    bank_rows = [
        ('Bank', quotation.get('bank_name')),
        ('Branch', quotation.get('branch_name')),
        ('Account No.', quotation.get('account_number')),
        ('IFSC Code', quotation.get('ifsc_code')),
        ('GST No.', quotation.get('gst_number')),
        ('PAN', quotation.get('pan_card')),
    ]
    for label, value in bank_rows:
        if not value:
            continue
        pdf.set_x(left_x)
        kv_row(pdf, label, value, lw=col_w * 0.45, full_w=col_w)
    left_end_y = pdf.get_y()

    # Right — Totals
    pdf.set_xy(right_x, top_y)
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(*BROWN_MID)
    pdf.cell(col_w, 4, 'TOTALS', 0, 2, 'L')

    sub_total = quotation.get('sub_total') or 0
    discount_pct = quotation.get('discount_percentage') or 0
    discount_amt = quotation.get('discount_amount') or 0
    tax_pct = quotation.get('igst_percentage') or 18
    tax_amt = quotation.get('igst_amount') or 0
    grand_total = quotation.get('grand_total') or quotation.get('total_amount') or 0

    pdf.set_x(right_x)
    kv_row(pdf, 'Sub total', f"Rs. {sub_total:,.2f}", lw=col_w * 0.5, full_w=col_w)
    if discount_pct:
        pdf.set_x(right_x)
        kv_row(pdf, f"Discount ({discount_pct:g}%)", f"- Rs. {discount_amt:,.2f}", lw=col_w * 0.5, full_w=col_w)
    pdf.set_x(right_x)
    kv_row(pdf, f"IGST @ {tax_pct:g}% (SAC: 999223)", f"+ Rs. {tax_amt:,.2f}", lw=col_w * 0.5, full_w=col_w)

    pdf.ln(1)
    pdf.set_x(right_x)
    pdf.set_fill_color(*BROWN_DARK)
    pdf.set_text_color(*CREAM)
    pdf.set_font('Arial', 'B', 9)
    pdf.cell(col_w * 0.55, 9, 'GRAND TOTAL', 0, 0, 'L', fill=True)
    pdf.cell(col_w * 0.45, 9, f"Rs. {grand_total:,.2f}", 0, 1, 'R', fill=True)
    pdf.set_text_color(*BROWN_TEXT)

    words = _number_to_words(round(grand_total))
    pdf.set_x(right_x)
    pdf.set_font('Arial', 'I', 7)
    pdf.set_text_color(*BROWN_MID)
    pdf.multi_cell(col_w, 4, f"Amount in words: {words}", align='R')

    if quotation.get('customer_gst'):
        pdf.set_x(right_x)
        pdf.set_font('Arial', '', 7.5)
        pdf.set_text_color(*BROWN_TEXT)
        pdf.cell(col_w, 4.5, f"Client GST No.: {quotation['customer_gst']}", 0, 1, 'R')

    right_end_y = pdf.get_y()
    pdf.set_y(max(left_end_y, right_end_y) + 3)

    pdf.set_draw_color(*BROWN_BORDER)
    pdf.line(margin, pdf.get_y(), margin + usable_w, pdf.get_y())
    pdf.ln(3)
    pdf.set_font('Arial', 'B', 8)
    pdf.set_text_color(*BROWN_DARK)
    pdf.cell(pdf.get_string_width('N.B.') + 2, 4.5, 'N.B.', 0, 0)
    pdf.set_text_color(*BROWN_TEXT)
    pdf.cell(0, 4.5, ' This is a Quotation, not a Tax Invoice.', 0, 1)
    pdf.set_font('Arial', '', 8)
    pdf.set_text_color(*BROWN_ACCENT)
    pdf.cell(0, 4.5, 'Prices are subject to change after the validity period.', 0, 1)


# ═════════════════════════════════════════════════════════════════════════════
# GET /quotations/<id>/pdf
# ═════════════════════════════════════════════════════════════════════════════
@quotation_bp.route('/quotations/<int:quotation_id>/pdf', methods=['GET'])
def download_quotation_pdf(quotation_id):
    session = SessionLocal()
    try:
        import os
        from io import BytesIO
        from flask import send_file
        from .pdf_helpers import (
            PDF, BROWN_DARK, BROWN_MID, BROWN_TEXT, BROWN_BORDER,
            BROWN_ACCENT, PARCHMENT_1, PARCHMENT_2, CREAM,
            draw_section_label, kv_row,
        )

        row = session.execute(
            text("""
                SELECT * FROM "streemLyne_mt_dev2"."Quotation_Master"
                WHERE quotation_id = :qid AND doc_type = :doc_type
            """),
            {"qid": quotation_id, "doc_type": DOC_TYPE}
        ).fetchone()
        if not row:
            return jsonify({"error": "Quotation not found"}), 404

        meta = _unpack_notes(row.notes)
        items = _get_quotation_items(session, quotation_id)
        client_info = _get_client_info(session, row.client_id)
        tax_rate = _get_tax_rate(session, row.tax_id)
        quotation = _serialize_quotation(row, meta, items, client_info, tax_rate)
        quotation['id'] = quotation_id

        pdf = PDF(orientation='P', unit='mm', format='A4')
        pdf.alias_nb_pages()
        pdf.set_auto_page_break(auto=True, margin=18)
        pdf.add_page()

        quotation_number = quotation.get('quotation_number') or f"QUO-{quotation_id:04d}"
        date_str = _format_pdf_date(quotation.get('date') or quotation.get('created_at'))
        status = quotation.get('status') or 'Draft'

        pdf.set_font('Arial', 'B', 10)
        pdf.set_text_color(*BROWN_DARK)
        pdf.cell(0, 6, f"{quotation_number}    |    {date_str}    |    {status}", 0, 1, 'L')
        pdf.ln(2)

        draw_section_label(pdf, 'QUOTATION INFORMATION')
        _draw_quotation_info(pdf, quotation)

        draw_section_label(pdf, 'TRAINING ITEMS')
        _draw_items_table(pdf, quotation.get('items') or [])
        pdf.ln(4)

        draw_section_label(pdf, 'FINANCIAL SUMMARY')
        _draw_financial_summary(pdf, quotation)

        terms = quotation.get('terms_conditions') or []
        if terms:
            pdf.ln(3)
            draw_section_label(pdf, 'TERMS & CONDITIONS')
            pdf.set_font('Arial', '', 8)
            pdf.set_text_color(*BROWN_ACCENT)
            seen = set()
            for term in terms:
                clean = (term or '').strip()
                if not clean:
                    continue
                norm = clean.lower()
                if norm in seen:
                    continue
                seen.add(norm)
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(0, 4.5, f"- {clean}")

            pdf.ln(6)
            sign_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'images', 'sign.png')
            sig_w = 45
            sig_x = pdf.w - pdf.r_margin - sig_w
            try:
                pdf.image(sign_path, x=sig_x, y=pdf.get_y(), w=sig_w)
                pdf.ln(18)
            except Exception:
                pdf.ln(2)
            pdf.set_font('Arial', 'B', 8)
            pdf.set_text_color(*BROWN_TEXT)
            pdf.cell(0, 4.5, 'F C Shaikh', 0, 1, 'R')
            pdf.set_font('Arial', '', 7)
            pdf.set_text_color(*BROWN_MID)
            pdf.cell(0, 4, 'Founder - CEO', 0, 1, 'R')

        if quotation.get('notes'):
            pdf.ln(4)
            draw_section_label(pdf, 'ADDITIONAL NOTES')
            pdf.set_font('Arial', '', 8)
            pdf.set_text_color(*BROWN_ACCENT)
            pdf.multi_cell(0, 4.5, quotation['notes'])

        pdf.ln(6)
        pdf.set_draw_color(*BROWN_BORDER)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(3)
        pdf.set_font('Arial', 'I', 7.5)
        pdf.set_text_color(*BROWN_MID)
        pdf.cell(0, 5, 'For more information about our training programmes, visit www.forklift.academy', 0, 1, 'C')

        pdf_bytes = bytes(pdf.output())
        filename = f"{quotation_number}.pdf".replace('/', '-').replace(' ', '_')

        return send_file(
            BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename,
        )

    except Exception as e:
        current_app.logger.exception(f"Quotation PDF failed: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()