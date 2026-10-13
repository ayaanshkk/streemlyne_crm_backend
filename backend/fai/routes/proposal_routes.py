"""
Proposal Routes for FAI CRM
──────────────────────────────────────────────────────────────────────────
MIGRATED to streemLyne_mt_dev2 (2026-09) — was previously on the old
"StreemLyne_MT" schema, writing to "Quotations"/"Quotation_Items" and
stashing extra metadata inside a hacked "Client_Interactions" row
(contact_method = 150). That schema no longer has the client rows the
rest of the app uses (Companies/Contacts live in streemLyne_mt_dev2 —
see company_routes.py), so any client_id from the current UI tripped
fk_quotation_client on insert.

Per sir: keep old schema where it still works, but where it's actively
broken, move it to the new schema. This route was broken, so it now
targets the SAME tables quotation_routes.py already targets —
"Quotation_Master" (header) and "Quotation_Details" (line items) on
streemLyne_mt_dev2 — via SessionLocal, instead of a second,
divergent copy of quotation storage.

"Proposal" and "Quotation" are the same underlying record here. Rather
than re-deriving the dev2 column mapping a second time, this file
reuses quotation_routes.py's helpers (_pack_notes/_unpack_notes,
_get_client_info, _resolve_tax_id, _get_tax_rate, _get_quotation_items,
_replace_quotation_items, _compute_totals, _serialize_quotation,
_get_employee_id, VALID_STATUSES, TENANT_ID) so there is exactly one
place that knows how a quotation/proposal row is read and written.
Only the URL prefix (/proposals instead of /quotations), the response
field aliases some older frontend code expects (proposal_id,
customer_id), the stats/search endpoints, and the PDF template are
specific to this file.

⚠️ 2026-09-26 UPDATE — doc_type discriminator added:
Because Proposals and Quotations share Quotation_Master/Quotation_Details
with no way to tell them apart, editing a proposal's status was also
changing "the quotation with that ID" (the same row) and vice versa —
they were literally the same database row, read/written by two
different route files with no filter distinguishing them.

Fixed by adding a `doc_type` column (migration: ALTER TABLE ...
ADD COLUMN doc_type VARCHAR(20) NOT NULL DEFAULT 'quotation' CHECK
(doc_type IN ('quotation','proposal'))). This file now filters every
query by DOC_TYPE = 'proposal' and stamps that value on every INSERT.
quotation_routes.py does the same with its own DOC_TYPE = 'quotation'.
Existing rows created via this Proposals screen before the migration
need a one-time manual backfill (UPDATE ... SET doc_type = 'proposal'
WHERE quotation_id IN (...)) since there's no way to retroactively
tell them apart automatically.

⚠️ OPEN ITEM: the old Client_Interactions-based metadata store
(_store_proposal_meta / _get_proposal_meta) is gone — metadata now
lives in Quotation_Master.notes as JSON, same as quotation_routes.py.
Any pre-migration proposals that only exist as rows in the old
"StreemLyne_MT"."Quotations" table are NOT visible through this file
any more (they were never valid against the current Client_Master
anyway, per the FK error this migration fixes). Flag if those old rows
need a one-time backfill into streemLyne_mt_dev2 before deploying this.
"""

import json
import traceback
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, timedelta
from sqlalchemy import text
from .auth_helpers import token_required
from ..db import SessionLocal
from .notification_routes import create_notification
from .quotation_routes import (
    TENANT_ID,
    VALID_STATUSES,
    _pack_notes,
    _unpack_notes,
    _get_employee_id,
    _get_client_info,
    _resolve_tax_id,
    _get_tax_rate,
    _get_quotation_items,
    _replace_quotation_items,
    _compute_totals,
    _serialize_quotation,
)

proposal_bp = Blueprint('proposals', __name__)

# Discriminator value for this file's rows — see header comment. Every
# query below must filter/stamp this so Proposals and Quotations (which
# share Quotation_Master/Quotation_Details) never collide.
DOC_TYPE = 'proposal'


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def get_current_user_info():
    if hasattr(request, 'current_user'):
        return {
            'id':          getattr(request.current_user, 'id', None),
            'employee_id': getattr(request.current_user, 'employee_id', None),
            'name':        getattr(request.current_user, 'employee_name',
                           getattr(request.current_user, 'full_name', 'System'))
        }
    return {'id': None, 'employee_id': None, 'name': 'System'}


def serialize_proposal(row, items, meta, client_info, tax_rate):
    """Same shape as quotation_routes._serialize_quotation, plus the
    legacy field aliases (proposal_id, customer_id, discount_percent)
    older frontend code for this page expects."""
    base = _serialize_quotation(row, meta, items, client_info, tax_rate)
    base['proposal_id'] = row.quotation_id
    base['customer_id'] = row.client_id
    base['discount_percent'] = base['discount_percentage']
    return base


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /proposals  &  POST /proposals
# ═════════════════════════════════════════════════════════════════════════════
@proposal_bp.route('/proposals', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_proposals():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        # ── POST: Create proposal ─────────────────────────────────────────
        if request.method == 'POST':
            d = request.get_json(silent=True) or {}
            user_info = get_current_user_info()

            client_id = d.get('client_id') or d.get('customer_id')
            if not client_id:
                return jsonify({'error': 'client_id is required'}), 400
            if not d.get('items'):
                return jsonify({'error': 'At least one item is required'}), 400

            employee_id = _get_employee_id(session, request.current_user.id)
            if not employee_id:
                return jsonify({'error': 'No Employee_Master record found for the current user'}), 400

            reference_number = (d.get('quotation_number') or d.get('reference_number') or '').strip()
            # Older proposal UI may not send a number up front — fall back to
            # a placeholder and rename once we have the real id, same trick
            # the old implementation used for its NOT NULL/UNIQUE column.
            temp_reference = reference_number or f"TMP-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"

            tax_id = _resolve_tax_id(session, d.get('igst_percentage'), d.get('tax_id'))
            discount_pct = float(d.get('discount_percentage', d.get('discount_percent', 0)) or 0)
            notes_str = _pack_notes(d)
            valid_for_days = int(d.get('valid_for_days') or 30)
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
                    "client_id":              client_id,
                    "project_id":             d.get('project_id'),
                    "reference_number":       temp_reference,
                    "notes":                  notes_str,
                    "valid_until":            valid_until,
                    "created_by_employee_id": employee_id,
                    "discount_pct":           discount_pct,
                    "currency_id":            d.get('currency_id'),
                    "tax_id":                 tax_id,
                    "status":                 d.get('status', 'Draft'),
                    "doc_type":               DOC_TYPE,
                }
            )
            new_proposal_id = result.fetchone()[0]

            _replace_quotation_items(session, new_proposal_id, TENANT_ID, d.get('items', []))

            if not reference_number:
                final_reference = f"QT-{new_proposal_id:04d}"
                session.execute(
                    text('UPDATE "streemLyne_mt_dev2"."Quotation_Master" SET reference_number = :ref WHERE quotation_id = :qid'),
                    {"ref": final_reference, "qid": new_proposal_id}
                )

            session.commit()

            row = session.execute(
                text("""
                    SELECT * FROM "streemLyne_mt_dev2"."Quotation_Master"
                    WHERE quotation_id = :qid AND doc_type = :doc_type
                """),
                {"qid": new_proposal_id, "doc_type": DOC_TYPE}
            ).fetchone()
            meta = _unpack_notes(row.notes)
            items = _get_quotation_items(session, new_proposal_id)
            client_info = _get_client_info(session, row.client_id)
            tax_rate = _get_tax_rate(session, row.tax_id)

            current_app.logger.info(f"Proposal created: {row.reference_number} (id={new_proposal_id})")
            return jsonify(serialize_proposal(row, items, meta, client_info, tax_rate)), 201

        # ── GET: List proposals ─────────────────────────────────────────────
        client_id = request.args.get('client_id') or request.args.get('customer_id')
        status = request.args.get('status')

        query = """
            SELECT *
            FROM "streemLyne_mt_dev2"."Quotation_Master"
            WHERE tenant_id = :tid
              AND doc_type = :doc_type
        """
        params = {"tid": TENANT_ID, "doc_type": DOC_TYPE}

        if client_id:
            query += " AND client_id = :client_id"
            params["client_id"] = client_id
        if status:
            query += " AND status = :status"
            params["status"] = status

        query += " ORDER BY created_at DESC"

        rows = session.execute(text(query), params).fetchall()

        result = []
        for row in rows:
            meta = _unpack_notes(row.notes)
            items = _get_quotation_items(session, row.quotation_id)
            client_info = _get_client_info(session, row.client_id)
            tax_rate = _get_tax_rate(session, row.tax_id)
            result.append(serialize_proposal(row, items, meta, client_info, tax_rate))

        return jsonify(result), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error in /proposals: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET/PUT/DELETE /proposals/<proposal_id>
# ═════════════════════════════════════════════════════════════════════════════
@proposal_bp.route('/proposals/<int:proposal_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@token_required
def handle_single_proposal(proposal_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        row = session.execute(
            text("""
                SELECT *
                FROM "streemLyne_mt_dev2"."Quotation_Master"
                WHERE quotation_id = :qid
                AND tenant_id = :tid
                AND doc_type = :doc_type
            """),
            {"qid": proposal_id, "tid": TENANT_ID, "doc_type": DOC_TYPE}
        ).fetchone()
        if not row:
            return jsonify({'error': 'Proposal not found'}), 404

        # ── GET ─────────────────────────────────────────────────────────────
        if request.method == 'GET':
            meta = _unpack_notes(row.notes)
            items = _get_quotation_items(session, proposal_id)
            client_info = _get_client_info(session, row.client_id)
            tax_rate = _get_tax_rate(session, row.tax_id)
            return jsonify(serialize_proposal(row, items, meta, client_info, tax_rate)), 200

        # ── PUT ─────────────────────────────────────────────────────────────
        elif request.method == 'PUT':
            d = request.get_json(silent=True) or {}
            old_status = row.status
            old_meta = _unpack_notes(row.notes)

            # Status-only update (from list page dropdown)
            if list(d.keys()) == ['status']:
                new_status = d['status']
                if new_status not in VALID_STATUSES:
                    return jsonify({'error': f"Invalid status: {new_status}"}), 400

                set_clauses = ["status = :status", "updated_at = NOW()"]
                update_fields = {
                    "status": new_status,
                    "qid": proposal_id,
                    "tid": TENANT_ID,
                    "doc_type": DOC_TYPE,
                }
                if new_status == 'Sent':
                    set_clauses.append("sent_at = NOW()")
                elif new_status == 'Approved':
                    approver_id = _get_employee_id(session, request.current_user.id)
                    set_clauses.append("approved_at = NOW()")
                    set_clauses.append("approved_by_employee_id = :approver_id")
                    update_fields["approver_id"] = approver_id

                session.execute(
                    text(f'''
                        UPDATE "streemLyne_mt_dev2"."Quotation_Master"
                        SET {", ".join(set_clauses)}
                        WHERE quotation_id = :qid
                        AND tenant_id = :tid
                        AND doc_type = :doc_type
                    '''),
                    update_fields
                )
                session.commit()

                if new_status in ('Sent', 'Approved', 'Rejected', 'Expired') and new_status != old_status:
                    client_info = _get_client_info(session, row.client_id)
                    qnum = row.reference_number or f"QT-{proposal_id:04d}"
                    cust = old_meta.get('customer_name') or client_info.get('customer_name') or 'Client'
                    emp_id = _get_employee_id(session, request.current_user.id)
                    msg_map = {
                        'Sent':     f"📤 Proposal {qnum} for {cust} has been marked as Sent",
                        'Approved': f"✅ Proposal {qnum} for {cust} has been Approved",
                        'Rejected': f"❌ Proposal {qnum} for {cust} has been Rejected",
                        'Expired':  f"⌛ Proposal {qnum} for {cust} has Expired",
                    }
                    create_notification(
                        session,
                        message=msg_map[new_status],
                        notification_type="proposal",
                        client_id=row.client_id,
                        created_by_employee_id=emp_id,
                        priority="high" if new_status == 'Approved' else "medium",
                    )
                    session.commit()

                return jsonify({'proposal_id': proposal_id, 'quotation_id': proposal_id}), 200

            # Full update
            reference_number = (d.get('quotation_number') or d.get('reference_number') or row.reference_number or '').strip()
            if not reference_number:
                return jsonify({'error': 'quotation_number is required'}), 400

            tax_id = _resolve_tax_id(session, d.get('igst_percentage'), d.get('tax_id'))
            discount_pct = float(d.get('discount_percentage', d.get('discount_percent', 0)) or 0)
            merged = dict(old_meta)
            merged.update(d)
            notes_str = _pack_notes(merged)

            valid_for_days = int(d.get('valid_for_days') or 30)
            valid_until = (row.created_at or datetime.utcnow()) + timedelta(days=valid_for_days)

            client_id = d.get('client_id') or d.get('customer_id') or row.client_id

            session.execute(
                text("""
                    UPDATE "streemLyne_mt_dev2"."Quotation_Master" SET
                        client_id = :client_id, project_id = :project_id,
                        reference_number = :reference_number, notes = :notes,
                        valid_until = :valid_until, global_discount_percent = :discount_pct,
                        currency_id = :currency_id, tax_id = :tax_id, updated_at = NOW()
                    WHERE quotation_id = :quotation_id
                      AND tenant_id = :tenant_id
                      AND doc_type = :doc_type
                """),
                {
                    "quotation_id":     proposal_id,
                    "client_id":        client_id,
                    "project_id":       d.get('project_id', row.project_id),
                    "reference_number": reference_number,
                    "notes":            notes_str,
                    "valid_until":      valid_until,
                    "discount_pct":     discount_pct,
                    "currency_id":      d.get('currency_id', row.currency_id),
                    "tax_id":           tax_id,
                    "tenant_id":        TENANT_ID,
                    "doc_type":         DOC_TYPE,
                }
            )

            if 'items' in d:
                _replace_quotation_items(session, proposal_id, TENANT_ID, d.get('items', []))

            if 'status' in d and d['status'] in VALID_STATUSES:
                session.execute(
                    text("""
                        UPDATE "streemLyne_mt_dev2"."Quotation_Master"
                        SET status = :status
                        WHERE quotation_id = :qid
                        AND tenant_id = :tid
                        AND doc_type = :doc_type
                    """),
                    {"status": d['status'], "qid": proposal_id, "tid": TENANT_ID, "doc_type": DOC_TYPE}
                )

            session.commit()

            new_status = d.get('status', old_status)
            if old_status != new_status and new_status in ('Sent', 'Approved', 'Rejected'):
                client_info = _get_client_info(session, client_id)
                qnum = reference_number or f"QT-{proposal_id:04d}"
                cust = merged.get('customer_name') or client_info.get('customer_name') or 'Client'
                msg_map = {
                    'Sent':     f"Proposal {qnum} for {cust} has been marked as Sent",
                    'Approved': f"Proposal {qnum} for {cust} has been Approved",
                    'Rejected': f"Proposal {qnum} for {cust} has been Rejected",
                }
                create_notification(
                    session,
                    message=msg_map[new_status],
                    notification_type="proposal",
                    proposal_id=proposal_id,
                    client_id=client_id,
                    created_by_employee_id=get_current_user_info().get('employee_id'),
                    priority="high" if new_status == 'Approved' else "medium",
                )
                session.commit()

            updated_row = session.execute(
                text("""
                    SELECT *
                    FROM "streemLyne_mt_dev2"."Quotation_Master"
                    WHERE quotation_id = :qid
                    AND tenant_id = :tid
                    AND doc_type = :doc_type
                """),
                {"qid": proposal_id, "tid": TENANT_ID, "doc_type": DOC_TYPE}
            ).fetchone()
            updated_meta = _unpack_notes(updated_row.notes)
            items = _get_quotation_items(session, proposal_id)
            client_info = _get_client_info(session, updated_row.client_id)
            tax_rate = _get_tax_rate(session, updated_row.tax_id)

            current_app.logger.info(f"Proposal updated: {proposal_id}")
            return jsonify(serialize_proposal(updated_row, items, updated_meta, client_info, tax_rate)), 200

        # ── DELETE ──────────────────────────────────────────────────────────
        elif request.method == 'DELETE':
            qnum = row.reference_number or str(proposal_id)

            session.execute(
                text("""
                    DELETE FROM "streemLyne_mt_dev2"."Quotation_Details"
                    WHERE quotation_id = :qid
                    AND tenant_id = :tid
                """),
                {"qid": proposal_id, "tid": TENANT_ID}
            )
            session.execute(
                text("""
                    DELETE FROM "streemLyne_mt_dev2"."Quotation_Master"
                    WHERE quotation_id = :qid
                    AND tenant_id = :tid
                    AND doc_type = :doc_type
                """),
                {"qid": proposal_id, "tid": TENANT_ID, "doc_type": DOC_TYPE}
            )
            session.commit()

            current_app.logger.info(f"Proposal deleted: {qnum}")
            return jsonify({'success': True, 'message': 'Proposal deleted successfully'}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error handling proposal {proposal_id}: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /proposals/stats
# ═════════════════════════════════════════════════════════════════════════════
@proposal_bp.route('/proposals/stats', methods=['GET', 'OPTIONS'])
@token_required
def get_proposal_stats():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        rows = session.execute(
            text("""
                SELECT status, global_discount_percent, tax_id, notes,
                       COALESCE((
                           SELECT SUM(amount) FROM "streemLyne_mt_dev2"."Quotation_Details" qd
                           WHERE qd.quotation_id = qm.quotation_id
                       ), 0) AS sub_total
                FROM "streemLyne_mt_dev2"."Quotation_Master" qm
                WHERE tenant_id = :tid
                  AND doc_type = :doc_type
            """),
            {"tid": TENANT_ID, "doc_type": DOC_TYPE}
        ).fetchall()

        status_counts = {}
        total_value = 0.0
        for row in rows:
            s = (row.status or 'Draft').lower()
            status_counts[s] = status_counts.get(s, 0) + 1
            tax_rate = _get_tax_rate(session, row.tax_id)
            totals = _compute_totals(
                [{"amount": float(row.sub_total or 0)}],
                float(row.global_discount_percent or 0),
                tax_rate,
            )
            total_value += totals["total"]

        return jsonify({
            'total_proposals': len(rows),
            'by_status': {
                'draft':     status_counts.get('draft', 0),
                'sent':      status_counts.get('sent', 0),
                'pending':   status_counts.get('pending', 0),
                'approved':  status_counts.get('approved', 0),
                'rejected':  status_counts.get('rejected', 0),
                'cancelled': status_counts.get('cancelled', 0),
            },
            'total_value': total_value
        }), 200

    except Exception as e:
        current_app.logger.error(f"❌ Error fetching proposal stats: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /proposals/search
# ═════════════════════════════════════════════════════════════════════════════
@proposal_bp.route('/proposals/search', methods=['GET', 'OPTIONS'])
@token_required
def search_proposals():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        search_term = request.args.get('q', '').strip()
        if not search_term:
            return jsonify([]), 200

        like = f'%{search_term}%'

        rows = session.execute(
            text("""
                SELECT * FROM "streemLyne_mt_dev2"."Quotation_Master"
                WHERE tenant_id = :tid
                  AND doc_type = :doc_type
                  AND (reference_number ILIKE :like OR notes ILIKE :like)
                ORDER BY created_at DESC
                LIMIT 20
            """),
            {"tid": TENANT_ID, "like": like, "doc_type": DOC_TYPE}
        ).fetchall()

        result = []
        for row in rows:
            meta = _unpack_notes(row.notes)
            items = _get_quotation_items(session, row.quotation_id)
            client_info = _get_client_info(session, row.client_id)
            tax_rate = _get_tax_rate(session, row.tax_id)
            result.append(serialize_proposal(row, items, meta, client_info, tax_rate))

        return jsonify(result), 200

    except Exception as e:
        current_app.logger.error(f"❌ Error searching proposals: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# GET /proposals/<id>/pdf — same "Warm Parchment" template as before, now
# sourced from streemLyne_mt_dev2 via serialize_proposal().
# ═════════════════════════════════════════════════════════════════════════════
@proposal_bp.route('/proposals/<int:proposal_id>/pdf', methods=['GET'])
def download_proposal_pdf(proposal_id):
    session = SessionLocal()
    try:
        from io import BytesIO
        from flask import send_file
        from .pdf_helpers import (
            PDF, BROWN_DARK, BROWN_MID, BROWN_TEXT, BROWN_BORDER,
            BROWN_ACCENT, PARCHMENT_1, PARCHMENT_2, CREAM,
            draw_section_label,
        )

        row = session.execute(
            text("""
                SELECT *
                FROM "streemLyne_mt_dev2"."Quotation_Master"
                WHERE quotation_id = :qid
                AND tenant_id = :tid
                AND doc_type = :doc_type
            """),
            {"qid": proposal_id, "tid": TENANT_ID, "doc_type": DOC_TYPE}
        ).fetchone()
        if not row:
            return jsonify({'error': 'Proposal not found'}), 404

        meta = _unpack_notes(row.notes)
        items = _get_quotation_items(session, proposal_id)
        client_info = _get_client_info(session, row.client_id)
        tax_rate = _get_tax_rate(session, row.tax_id)
        proposal = serialize_proposal(row, items, meta, client_info, tax_rate)

        def number_to_words(num: int) -> str:
            ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine']
            tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']
            teens = ['Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen',
                     'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
            if num == 0:
                return 'Zero'

            def b1000(n):
                if n == 0:
                    return ''
                if n < 10:
                    return ones[n]
                if n < 20:
                    return teens[n - 10]
                if n < 100:
                    return tens[n // 10] + (' ' + ones[n % 10] if n % 10 else '')
                return ones[n // 100] + ' Hundred' + (' ' + b1000(n % 100) if n % 100 else '')

            c = num // 10000000
            l = (num % 10000000) // 100000
            t = (num % 100000) // 1000
            r = num % 1000
            res = ''
            if c:
                res += b1000(c) + ' Crore '
            if l:
                res += b1000(l) + ' Lakh '
            if t:
                res += b1000(t) + ' Thousand '
            if r:
                res += b1000(r)
            return res.strip() + ' Only'

        def fmt(amount):
            return f"Rs. {(amount or 0):,.2f}"

        def sanitize(text_str: str) -> str:
            if not text_str:
                return ''
            replacements = {
                '\u20b9': 'Rs.', '\u2014': '--', '\u2013': '-', '\u2012': '-',
                '\u2010': '-', '\u2019': "'", '\u2018': "'", '\u201c': '"',
                '\u201d': '"', '\u2026': '...', '\u00b7': '.', '\u2022': '-',
                '\u2605': '*', '\u00a0': ' ', '\u00ae': '(R)', '\u00a9': '(C)',
                '\u2122': '(TM)',
            }
            for char, replacement in replacements.items():
                text_str = text_str.replace(char, replacement)
            return text_str.encode('latin-1', errors='replace').decode('latin-1')

        def fmt_date(date_str):
            if not date_str:
                return '-'
            try:
                d = datetime.fromisoformat(date_str.replace('Z', ''))
                return d.strftime('%d %B %Y')
            except Exception:
                return date_str

        sub_total = float(proposal.get('sub_total') or 0)
        discount_pct = float(proposal.get('discount_percentage') or 0)
        discount_amt = float(proposal.get('discount_amount') or 0)
        igst_pct = float(proposal.get('igst_percentage') or 18)
        igst_amt = float(proposal.get('igst_amount') or 0)
        grand_total = float(proposal.get('grand_total') or proposal.get('total_amount') or 0)

        lh = 5.5
        pdf = PDF('P', 'mm', 'A4')
        pdf.doc_title = ''
        pdf.alias_nb_pages()
        pdf.set_margins(12, 12, 12)
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=14)

        page_w = pdf.w
        margin = pdf.l_margin
        body_w = page_w - margin * 2

        meta_h = 7
        pdf.set_fill_color(254, 249, 244)
        pdf.set_draw_color(*BROWN_BORDER)
        pdf.rect(margin, pdf.get_y(), body_w, meta_h, 'FD')

        y_meta = pdf.get_y()
        pdf.set_xy(margin + 3, y_meta + 1)
        pdf.set_font('Arial', 'B', 9)
        pdf.set_text_color(*BROWN_DARK)
        qt_num = proposal.get('quotation_number') or f"QT-{proposal_id:04d}"
        pdf.cell(60, 5, qt_num, 0, 0, 'L')

        pdf.set_font('Arial', '', 8)
        pdf.set_text_color(*BROWN_MID)
        pdf.cell(40, 5, fmt_date(proposal.get('date') or proposal.get('created_at')), 0, 0, 'L')

        badge_label = 'TRAINING PROPOSAL'
        pdf.set_font('Arial', 'B', 7)
        bw = pdf.get_string_width(badge_label) + 8
        bx = margin + body_w - bw - 2
        by = y_meta + 1
        pdf.set_draw_color(*BROWN_DARK)
        pdf.set_fill_color(255, 255, 255)
        pdf.rect(bx, by, bw, 5, 'D')
        pdf.set_xy(bx, by)
        pdf.set_text_color(*BROWN_DARK)
        pdf.cell(bw, 5, badge_label, 0, 0, 'C')

        pdf.set_text_color(*BROWN_TEXT)
        pdf.set_draw_color(*BROWN_TEXT)
        pdf.ln(meta_h + 4)

        draw_section_label(pdf, 'PROPOSAL INFORMATION')

        half = body_w / 2 - 4
        y_info = pdf.get_y()
        pdf.set_xy(margin, y_info)

        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(*BROWN_MID)
        pdf.cell(half, 4, 'TO', 0, 1, 'L')

        pdf.set_x(margin)
        pdf.set_font('Arial', 'B', 9)
        pdf.set_text_color(*BROWN_TEXT)
        pdf.cell(half, 5, proposal.get('customer_name') or '-', 0, 1, 'L')

        if proposal.get('customer_designation'):
            pdf.set_x(margin)
            pdf.set_font('Arial', '', 8)
            pdf.set_text_color(*BROWN_DARK)
            pdf.cell(half, 4, proposal.get('customer_designation'), 0, 1, 'L')

        if proposal.get('customer_company'):
            pdf.set_x(margin)
            pdf.set_font('Arial', '', 8)
            pdf.set_text_color(*BROWN_ACCENT)
            pdf.cell(half, 4, proposal.get('customer_company'), 0, 1, 'L')

        if proposal.get('customer_address'):
            pdf.set_x(margin)
            pdf.set_font('Arial', '', 7.5)
            pdf.set_text_color(*BROWN_MID)
            pdf.multi_cell(half, 4, sanitize(proposal.get('customer_address')), 0, 'L')

        pdf.set_x(margin)
        pdf.set_font('Arial', '', 7.5)
        pdf.set_text_color(*BROWN_ACCENT)
        if proposal.get('customer_mobile'):
            pdf.cell(half, 4, f"Mobile: {proposal.get('customer_mobile')}", 0, 1, 'L')
        if proposal.get('customer_email'):
            pdf.cell(half, 4, f"Email: {proposal.get('customer_email')}", 0, 1, 'L')

        y_after_left = pdf.get_y()

        rx = margin + half + 8
        pdf.set_xy(rx, y_info)

        right_w = body_w - half - 8
        lw_r = right_w * 0.48

        for label, value in [
            ('Quotation #', qt_num),
            ('Date', fmt_date(proposal.get('date') or proposal.get('created_at'))),
            ('Payment terms', proposal.get('payment_terms') or '-'),
            ('Mode of enquiry', proposal.get('mode_of_enquiry') or 'Email'),
            ('Valid for', f"{proposal.get('valid_for_days') or 30} days"),
        ]:
            y_row = pdf.get_y()
            pdf.set_xy(rx, y_row)
            pdf.set_font('Arial', '', 7.5)
            pdf.set_text_color(*BROWN_MID)
            pdf.cell(lw_r, lh, label, 0, 0, 'L')
            pdf.set_font('Arial', 'B', 7.5)
            pdf.set_text_color(*BROWN_TEXT)
            pdf.cell(right_w - lw_r, lh, str(value), 0, 0, 'R')
            pdf.ln(lh)
            pdf.set_draw_color(*BROWN_BORDER)
            pdf.line(rx, pdf.get_y(), rx + right_w, pdf.get_y())

        pdf.set_draw_color(*BROWN_TEXT)
        pdf.set_text_color(*BROWN_TEXT)
        pdf.set_y(max(y_after_left, pdf.get_y()) + 5)

        draw_section_label(pdf, 'TRAINING ITEMS')

        col_w = [10, 20, 88, 16, 28, 28]
        headers = ['Sr.', 'Code', 'Description', 'N.O.P', 'Unit Rate', 'Amount']
        aligns = ['C', 'C', 'L', 'C', 'R', 'R']

        hdr_h = 7
        pdf.set_fill_color(*BROWN_DARK)
        pdf.set_text_color(*CREAM)
        pdf.set_font('Arial', 'B', 7)
        for h, w, a in zip(headers, col_w, aligns):
            pdf.cell(w, hdr_h, h, 0, 0, a, 1)
        pdf.ln(hdr_h)
        pdf.set_text_color(*BROWN_TEXT)

        for idx, item in enumerate(proposal.get('items') or []):
            rate = float(item.get('service_rate') or item.get('unit_rate') or 0)
            qty = float(item.get('quantity') or 0)
            amount = rate if qty == 0 else qty * rate
            desc = sanitize(item.get('service_title') or '-')
            code = (item.get('service_code') or '-')[:16]

            desc_lower = desc.lower()
            is_auto_item = (
                'training shall be conducted in' in desc_lower or
                'additional participant will be charged' in desc_lower
            )

            pdf.set_font('Arial', '', 7.5)
            n_lines = max(1, len(desc) // 52 + (1 if len(desc) % 52 else 0))
            row_h = max(7, n_lines * 4.5)

            fill_color = PARCHMENT_1 if idx % 2 == 0 else PARCHMENT_2
            pdf.set_fill_color(*fill_color)

            rx0 = margin
            ry0 = pdf.get_y()

            pdf.set_font('Arial', '', 7.5)
            pdf.set_text_color(*BROWN_MID)
            pdf.cell(col_w[0], row_h, str(idx + 1), 0, 0, 'C', 1)

            pdf.set_font('Arial', 'B', 7.5)
            pdf.set_text_color(*BROWN_DARK)
            pdf.cell(col_w[1], row_h, '' if is_auto_item else code, 0, 0, 'C', 1)

            xd, yd = pdf.get_x(), pdf.get_y()
            pdf.set_fill_color(*fill_color)
            pdf.set_font('Arial', '', 7.5)
            pdf.set_text_color(*BROWN_TEXT)
            pdf.multi_cell(col_w[2], 4.5, desc, 0, 'L', 1)
            actual_h = pdf.get_y() - yd
            row_h = max(row_h, actual_h)

            if actual_h < row_h:
                pdf.set_fill_color(*fill_color)
                pdf.set_xy(xd, yd + actual_h)
                pdf.cell(col_w[2], row_h - actual_h, '', 0, 0, 'L', 1)

            pdf.set_xy(xd + col_w[2], yd)
            pdf.set_fill_color(*fill_color)
            pdf.set_font('Arial', '', 8)
            pdf.set_text_color(*BROWN_TEXT)
            pdf.cell(col_w[3], row_h, '' if is_auto_item else str(int(qty)), 0, 0, 'C', 1)

            pdf.set_text_color(*BROWN_TEXT)
            pdf.cell(col_w[4], row_h, '' if is_auto_item else fmt(rate), 0, 0, 'R', 1)

            pdf.set_font('Arial', 'B', 8)
            pdf.cell(col_w[5], row_h, '' if is_auto_item else fmt(amount), 0, 0, 'R', 1)

            pdf.set_draw_color(*BROWN_BORDER)
            pdf.line(rx0, yd + row_h, rx0 + body_w, yd + row_h)
            pdf.set_draw_color(*BROWN_TEXT)

            pdf.set_text_color(*BROWN_TEXT)
            pdf.set_font('Arial', '', 8)
            pdf.ln(row_h)

        if not proposal.get('items'):
            pdf.set_font('Arial', '', 8)
            pdf.set_text_color(*BROWN_MID)
            pdf.cell(body_w, 8, 'No items found', 0, 1, 'C')
            pdf.set_text_color(*BROWN_TEXT)

        pdf.ln(5)

        draw_section_label(pdf, 'FINANCIAL SUMMARY')

        half2 = body_w / 2 - 4
        y_fin = pdf.get_y()
        pdf.set_xy(margin, y_fin)

        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(*BROWN_MID)
        pdf.set_x(margin)

        for label, key in [
            ('Bank', 'bank_name'), ('Branch', 'branch_name'),
            ('Account No.', 'account_number'), ('IFSC Code', 'ifsc_code'),
            ('GST No.', 'gst_number'), ('PAN', 'pan_card'),
        ]:
            val = proposal.get(key)
            if val:
                y_row = pdf.get_y()
                pdf.set_xy(margin, y_row)
                pdf.set_font('Arial', '', 7.5)
                pdf.set_text_color(*BROWN_MID)
                pdf.cell(half2 * 0.45, lh, label, 0, 0, 'L')
                pdf.set_font('Arial', 'B', 7.5)
                pdf.set_text_color(*BROWN_TEXT)
                pdf.cell(half2 * 0.55, lh, str(val), 0, 0, 'R')
                pdf.ln(lh)
                pdf.set_draw_color(*BROWN_BORDER)
                pdf.line(margin, pdf.get_y(), margin + half2, pdf.get_y())

        y_after_bank = pdf.get_y()

        rx2 = margin + half2 + 8
        rw = body_w - half2 - 8
        lw_t = rw * 0.58

        pdf.set_xy(rx2, y_fin)
        pdf.set_font('Arial', '', 7)
        pdf.set_text_color(*BROWN_MID)
        pdf.cell(rw, 4, 'TOTALS', 0, 1, 'L')

        totals_rows = [
            ('Sub total', f'{fmt(sub_total)}'),
            (f'IGST @ {igst_pct:.0f}% (SAC: 999223)', f'+ {fmt(igst_amt)}'),
        ]
        if discount_pct > 0:
            totals_rows.insert(1, (f'Discount ({discount_pct:.0f}%)', f'- {fmt(discount_amt)}'))

        for label, value in totals_rows:
            y_row = pdf.get_y()
            pdf.set_xy(rx2, y_row)
            pdf.set_font('Arial', '', 7.5)
            pdf.set_text_color(*BROWN_MID)
            pdf.cell(lw_t, lh, label, 0, 0, 'L')
            pdf.set_font('Arial', 'B', 7.5)
            pdf.set_text_color(*BROWN_TEXT)
            pdf.cell(rw - lw_t, lh, value, 0, 0, 'R')
            pdf.ln(lh)
            pdf.set_draw_color(*BROWN_BORDER)
            pdf.line(rx2, pdf.get_y(), rx2 + rw, pdf.get_y())

        pdf.ln(2)

        gt_h = 9
        gt_y = pdf.get_y()
        pdf.set_fill_color(*BROWN_DARK)
        pdf.rect(rx2, gt_y, rw, gt_h, 'F')
        pdf.set_xy(rx2, gt_y)
        pdf.set_font('Arial', 'B', 9)
        pdf.set_text_color(*CREAM)
        pdf.cell(lw_t, gt_h, 'Grand Total', 0, 0, 'L')
        pdf.cell(rw - lw_t, gt_h, f'{fmt(grand_total)}', 0, 0, 'R')
        pdf.ln(gt_h + 2)
        pdf.set_text_color(*BROWN_TEXT)

        pdf.set_x(rx2)
        pdf.set_font('Arial', 'I', 7.5)
        pdf.set_text_color(*BROWN_MID)
        pdf.cell(rw, 5, f'Amount in words: {number_to_words(round(grand_total))}', 0, 1, 'R')

        pdf.set_x(rx2)
        pdf.set_font('Arial', '', 7)
        pdf.cell(rw, 4, f"Valid for {proposal.get('valid_for_days') or 30} days from the date above  |  E. & O. E.", 0, 1, 'R')

        pdf.set_text_color(*BROWN_TEXT)
        pdf.set_y(max(y_after_bank, pdf.get_y()) + 5)

        terms = proposal.get('terms_conditions') or []
        if terms:
            if pdf.get_y() + 40 > pdf.h - pdf.b_margin:
                pdf.add_page()

            draw_section_label(pdf, 'TERMS & CONDITIONS')

            import re as _re
            seen_norm = set()
            unique_terms = []
            for t in terms:
                norm = _re.sub(r'^[A-H]\.\s*', '', t.strip()).lower()
                if norm not in seen_norm:
                    seen_norm.add(norm)
                    unique_terms.append(t)

            tc_start_y = pdf.get_y()
            accent_x = margin

            pdf.set_x(margin + 4)
            pdf.set_font('Arial', '', 7.5)
            pdf.set_text_color(*BROWN_ACCENT)

            for idx_t, term in enumerate(unique_terms):
                if pdf.get_y() + 6 > pdf.h - pdf.b_margin - 18:
                    pdf.add_page()
                    pdf.set_font('Arial', '', 7.5)
                    pdf.set_text_color(*BROWN_ACCENT)
                pdf.set_x(margin + 4)
                safe_term = sanitize(term.strip())
                safe_term = _re.sub(r'^[A-H]\.\s*', '', safe_term)
                letter = chr(65 + idx_t)
                pdf.multi_cell(body_w - 4, 4.5, f'{letter}.  {safe_term}', 0, 'L')

            tc_end_y = pdf.get_y()

            pdf.set_fill_color(*BROWN_DARK)
            pdf.rect(accent_x, tc_start_y - 1, 2.5, tc_end_y - tc_start_y + 2, 'F')

            pdf.set_draw_color(*BROWN_BORDER)
            pdf.rect(accent_x, tc_start_y - 1, body_w, tc_end_y - tc_start_y + 2, 'D')
            pdf.set_draw_color(*BROWN_TEXT)

            pdf.ln(4)

            import os
            _routes_dir = os.path.dirname(os.path.abspath(__file__))
            _backend_dir = os.path.dirname(_routes_dir)
            sig_img_path = os.path.normpath(os.path.join(_backend_dir, 'static', 'images', 'sign.png'))

            if pdf.get_y() + 18 > pdf.h - pdf.b_margin:
                pdf.add_page()

            sig_w = 35
            sig_x = margin + body_w - sig_w
            sig_y = pdf.get_y()

            if os.path.exists(sig_img_path):
                try:
                    pdf.image(sig_img_path, x=sig_x, y=sig_y, w=sig_w)
                    pdf.ln(13)
                except Exception as sig_err:
                    current_app.logger.warning(f"Signature image failed to render: {sig_err}")
                    pdf.ln(4)
            else:
                pdf.ln(4)

            line_x = margin + body_w - 56
            pdf.set_draw_color(*BROWN_BORDER)
            pdf.line(line_x, pdf.get_y(), margin + body_w, pdf.get_y())
            pdf.ln(2)

            pdf.set_x(line_x)
            pdf.set_font('Arial', 'B', 8)
            pdf.set_text_color(*BROWN_TEXT)
            pdf.cell(56, 4, 'F C Shaikh', 0, 1, 'R')
            pdf.set_x(line_x)
            pdf.set_font('Arial', '', 7)
            pdf.set_text_color(*BROWN_MID)
            pdf.cell(56, 4, 'Founder - CEO', 0, 1, 'R')
            pdf.set_text_color(*BROWN_TEXT)
            pdf.ln(2)

        if proposal.get('notes'):
            pdf.ln(3)
            draw_section_label(pdf, 'ADDITIONAL NOTES')
            pdf.set_font('Arial', '', 7.5)
            pdf.set_text_color(*BROWN_ACCENT)
            pdf.multi_cell(body_w, 4.5, sanitize(proposal.get('notes')), 0, 'L')
            pdf.set_text_color(*BROWN_TEXT)

        pdf.set_auto_page_break(False)
        footer_y = pdf.h - 12
        pdf.set_draw_color(*BROWN_BORDER)
        pdf.line(margin, footer_y, margin + body_w, footer_y)
        pdf.set_xy(margin, footer_y + 3)
        pdf.set_font('Arial', '', 7.5)
        pdf.set_text_color(*BROWN_MID)
        pdf.cell(0, 4,
                 'For more information about our training programmes, visit www.forklift.academy',
                 0, 1, 'C')

        out = pdf.output(dest='S')
        if isinstance(out, str):
            out = out.encode('latin-1')
        buf = BytesIO(bytes(out))

        qnum = proposal.get('quotation_number') or str(proposal_id)
        cust = (proposal.get('customer_name') or 'Customer').replace(' ', '_')
        fname = f"Proposal_{qnum}_{cust}.pdf"

        return send_file(buf, mimetype='application/pdf',
                          as_attachment=False, download_name=fname)

    except Exception as e:
        current_app.logger.exception(f"Proposal PDF generation failed: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()