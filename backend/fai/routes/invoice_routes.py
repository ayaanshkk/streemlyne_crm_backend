"""
Invoice Routes for FAI CRM
Rewritten against the ACTUAL streemLyne_mt_dev2 schema:

    Invoice_Master        - header row (no customer text columns, no description blob)
    Invoice_Details        - one row per line item, FK'd to a product catalog
    Invoice_Tax_Details    - one row per tax line, FK'd to a tax lookup table

Key differences from the old (StreemLyne_MT) design this replaces:
  - No customer_name / customer_address / customer_phone / customer_email
    columns on Invoice_Master. Customer identity now comes from client_id,
    joined out to Client_Master.client_company_name. Delivery_address /
    Delivery_phone / Delivery_email ARE real columns and are used for the
    ship-to / contact-on-invoice fields.
  - No `description` JSON blob column. Line items live in their own table
    (Invoice_Details) and taxes in their own table (Invoice_Tax_Details).
  - Invoice_Details.Product_Variant_ID is NOT NULL: every line item must
    reference a real product/service catalog row. This file does NOT
    fabricate catalog IDs - if the frontend doesn't send product_variant_id
    for an item, that item's insert will fail with a clear error rather
    than silently writing a wrong/placeholder value.
  - Invoice_Tax_Details.tax_id is a lookup FK (not a raw percentage).
    DEFAULT_IGST_TAX_ID below is a PLACEHOLDER - confirm the real tax_id
    for "IGST 18%" (or whatever your Tax_Master-equivalent table calls it)
    and update the constant.
  - Fields that no longer have ANY home in this schema (dropped for now,
    pending a decision on where they should live):
        bank_name, branch_name, account_number, ifsc_code,
        gst_number, pan_card, payment_terms, mode_of_enquiry,
        valid_for_days, terms_conditions, customer_designation,
        customer_gst
    These are removed from create/update/serialize. The PDF generator
    (download_invoice_pdf) has been updated to skip sections it can no
    longer populate rather than guess at the missing data - it will need
    a follow-up design pass once you decide where (if anywhere) those
    fields live going forward.
"""

from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from sqlalchemy import text
from .auth_helpers import token_required
from .notification_routes import create_notification
from ..db import DevSessionLocal

invoice_bp = Blueprint('invoice', __name__)

TENANT_ID = 3
SCHEMA = 'streemLyne_mt_dev2'

# ── PLACEHOLDER - CONFIRM WITH SUPERVISOR ──────────────────────────────────
# Invoice_Tax_Details.tax_id is a foreign key into a tax lookup table.
# This is a guess (1) standing in for "IGST 18%" until confirmed for real.
DEFAULT_IGST_TAX_ID = 1


def T(table_name):
    return f'"{SCHEMA}"."{table_name}"'


# ═════════════════════════════════════════════════════════════════════════════
# Serialization helpers
# ═════════════════════════════════════════════════════════════════════════════
def _serialize_invoice(row, client_name, items, taxes) -> dict:
    """Serialize an Invoice_Master row + its joined name + child rows."""
    sub_total = float(row.sub_total_withouttax or 0)
    discount_amount = float(row.discount_amount or 0)
    discount_pct = float(row.global_discount_percent or 0)
    total_amount = float(row.total_amount or 0)
    igst_amount = sum(float(t["tax_amount"] or 0) for t in taxes)

    return {
        "id":                   row.invoice_id,
        "invoice_id":           row.invoice_id,
        "invoice_number":       row.invoice_number,
        "date":                 row.invoice_date.isoformat() if row.invoice_date else None,
        "due_date":             row.due_date.isoformat() if row.due_date else None,
        "client_id":            row.client_id,
        "project_id":           row.project_id,
        "quotation_id":         row.quotation_id,
        "customer_name":        client_name or "",
        "customer_company":     client_name or "",
        "customer_address":     row.Delivery_address or "",
        "customer_mobile":      row.Delivery_phone or "",
        "customer_email":       row.Delivery_email or "",
        "sub_total":            sub_total,
        "discount_percentage":  discount_pct,
        "discount_amount":      discount_amount,
        "igst_amount":          igst_amount,
        "grand_total":          total_amount,
        "total_amount":         total_amount,
        "notes":                row.billing_remarks or "",
        "status":               row.status or "Draft",
        "created_at":           row.created_at.isoformat() if row.created_at else None,
        "items":                items,
        "taxes":                taxes,
    }


def _fetch_items(session, invoice_id):
    rows = session.execute(
        text(f"""
            SELECT invoice_details_id, "Product_Variant_ID", quantity, uom_id,
                   "Product_name", unit_price, description, amount, section, is_sub_item
            FROM {T("Invoice_Details")}
            WHERE invoice_id = :iid
            ORDER BY invoice_details_id
        """),
        {"iid": invoice_id}
    ).fetchall()
    return [
        {
            "invoice_details_id": r.invoice_details_id,
            "product_variant_id": r.Product_Variant_ID,
            "product_name":       r.Product_name or "",
            "quantity":           float(r.quantity or 0),
            "uom_id":             r.uom_id,
            "unit_price":         float(r.unit_price or 0),
            "description":        r.description or "",
            "amount":             float(r.amount or 0),
            "section":            r.section or "",
            "is_sub_item":        bool(r.is_sub_item),
        }
        for r in rows
    ]


def _fetch_taxes(session, invoice_id):
    rows = session.execute(
        text(f"""
            SELECT invoice_tax_details_id, tax_id, tax_amount, remarks
            FROM {T("Invoice_Tax_Details")}
            WHERE invoice_id = :iid
            ORDER BY invoice_tax_details_id
        """),
        {"iid": invoice_id}
    ).fetchall()
    return [
        {
            "invoice_tax_details_id": r.invoice_tax_details_id,
            "tax_id":                 r.tax_id,
            "tax_amount":             float(r.tax_amount or 0),
            "remarks":                r.remarks or "",
        }
        for r in rows
    ]


def _fetch_client_name(session, client_id):
    if not client_id:
        return ""
    row = session.execute(
        text(f'SELECT client_company_name FROM {T("Client_Master")} WHERE client_id = :cid'),
        {"cid": client_id}
    ).fetchone()
    return (row.client_company_name if row else "") or ""


def _replace_items(session, invoice_id, items):
    """Delete existing Invoice_Details rows for this invoice and insert fresh ones.
    Every item MUST include product_variant_id (NOT NULL in the DB) - items
    missing it are rejected rather than inserted with a made-up value."""
    session.execute(
        text(f'DELETE FROM {T("Invoice_Details")} WHERE invoice_id = :iid'),
        {"iid": invoice_id}
    )
    now = datetime.utcnow()
    for item in items:
        product_variant_id = item.get("product_variant_id")
        if not product_variant_id:
            raise ValueError(
                f"Item '{item.get('product_name', '?')}' is missing product_variant_id "
                f"(required - Invoice_Details.Product_Variant_ID is NOT NULL)"
            )
        session.execute(
            text(f"""
                INSERT INTO {T("Invoice_Details")} (
                    invoice_id, "Product_Variant_ID", quantity, uom_id,
                    created_at, "Product_name", unit_price, description,
                    amount, section, is_sub_item
                ) VALUES (
                    :invoice_id, :pvid, :quantity, :uom_id,
                    :created_at, :product_name, :unit_price, :description,
                    :amount, :section, :is_sub_item
                )
            """),
            {
                "invoice_id":   invoice_id,
                "pvid":         product_variant_id,
                "quantity":     float(item.get("quantity", 0)),
                "uom_id":       item.get("uom_id"),
                "created_at":   now,
                "product_name": item.get("product_name", ""),
                "unit_price":   float(item.get("unit_price", 0)),
                "description":  item.get("description", ""),
                "amount":       float(item.get("amount", 0)),
                "section":      item.get("section", ""),
                "is_sub_item":  bool(item.get("is_sub_item", False)),
            }
        )


def _replace_taxes(session, invoice_id, taxes, tenant_id):
    """Delete existing Invoice_Tax_Details rows for this invoice and insert fresh
    ones. If the frontend doesn't send explicit tax lines yet, falls back to a
    single IGST line using DEFAULT_IGST_TAX_ID (placeholder - confirm the real
    tax_id with your supervisor)."""
    session.execute(
        text(f'DELETE FROM {T("Invoice_Tax_Details")} WHERE invoice_id = :iid'),
        {"iid": invoice_id}
    )
    now = datetime.utcnow()

    if not taxes:
        igst_amount = 0.0
        taxes = [{
            "tax_id": DEFAULT_IGST_TAX_ID,
            "tax_amount": igst_amount,
            "remarks": "IGST (auto - confirm tax_id)",
        }]

    for tax in taxes:
        session.execute(
            text(f"""
                INSERT INTO {T("Invoice_Tax_Details")} (
                    created_at, invoice_id, tax_id, tax_amount, remarks, tenant_id
                ) VALUES (
                    :created_at, :invoice_id, :tax_id, :tax_amount, :remarks, :tenant_id
                )
            """),
            {
                "created_at": now,
                "invoice_id": invoice_id,
                "tax_id":     tax.get("tax_id", DEFAULT_IGST_TAX_ID),
                "tax_amount": float(tax.get("tax_amount", 0)),
                "remarks":    tax.get("remarks", ""),
                "tenant_id":  tenant_id,
            }
        )


# ═════════════════════════════════════════════════════════════════════════════
# GET /invoices
# ═════════════════════════════════════════════════════════════════════════════
@invoice_bp.route('/invoices', methods=['GET', 'OPTIONS'])
@token_required
def list_invoices():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = DevSessionLocal()
    try:
        rows = session.execute(
            text(f"""
                SELECT im.invoice_id, im.invoice_number, im.invoice_date, im.client_id,
                       im.total_amount, im.status, im.created_at,
                       cm.client_company_name
                FROM {T("Invoice_Master")} im
                LEFT JOIN {T("Client_Master")} cm ON cm.client_id = im.client_id
                WHERE im.tenant_id = :tid
                ORDER BY im.created_at DESC
            """),
            {"tid": TENANT_ID}
        ).fetchall()
        return jsonify([
            {
                "id":             r.invoice_id,
                "invoice_id":     r.invoice_id,
                "invoice_number": r.invoice_number,
                "date":           r.invoice_date.isoformat() if r.invoice_date else None,
                "client_id":      r.client_id,
                "customer_name":  r.client_company_name or "—",
                "grand_total":    float(r.total_amount or 0),
                "total_amount":   float(r.total_amount or 0),
                "status":         r.status or "Draft",
                "created_at":     r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]), 200
    except Exception as e:
        current_app.logger.error(f"Invoice list error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# GET /invoices/<id>
# ═════════════════════════════════════════════════════════════════════════════
@invoice_bp.route('/invoices/<int:invoice_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_invoice(invoice_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = DevSessionLocal()
    try:
        row = session.execute(
            text(f'SELECT * FROM {T("Invoice_Master")} WHERE invoice_id = :iid'),
            {"iid": invoice_id}
        ).fetchone()
        if not row:
            return jsonify({"error": "Invoice not found"}), 404

        client_name = _fetch_client_name(session, row.client_id)
        items = _fetch_items(session, invoice_id)
        taxes = _fetch_taxes(session, invoice_id)
        return jsonify(_serialize_invoice(row, client_name, items, taxes)), 200
    except Exception as e:
        current_app.logger.error(f"Invoice get error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# POST /invoices
# ═════════════════════════════════════════════════════════════════════════════
@invoice_bp.route('/invoices', methods=['POST', 'OPTIONS'])
@token_required
def create_invoice():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = DevSessionLocal()
    try:
        d = request.get_json() or {}

        sub_total = float(d.get("sub_total", 0))
        discount_amt = float(d.get("discount_amount", 0))
        discount_pct = float(d.get("discount_percentage", 0))
        total_amount = float(d.get("total_amount", d.get("grand_total", 0)))
        items = d.get("items", [])
        taxes = d.get("taxes")  # optional - falls back to DEFAULT_IGST_TAX_ID if omitted

        result = session.execute(
            text(f"""
                INSERT INTO {T("Invoice_Master")} (
                    tenant_id, client_id, project_id, quotation_id, invoice_number,
                    billing_remarks, sub_total_withouttax, currency_id, total_amount,
                    discount_amount, created_at, invoice_date, due_date, status,
                    "Delivery_address", "Delivery_phone", "Delivery_email",
                    created_by_userid, global_discount_percent
                ) VALUES (
                    :tenant_id, :client_id, :project_id, :quotation_id, :invoice_number,
                    :billing_remarks, :sub_total, :currency_id, :total_amount,
                    :discount_amt, :created_at, :invoice_date, :due_date, :status,
                    :delivery_address, :delivery_phone, :delivery_email,
                    :created_by_userid, :discount_pct
                )
                RETURNING invoice_id
            """),
            {
                "tenant_id":         TENANT_ID,
                "client_id":         d.get("client_id"),
                "project_id":        d.get("project_id"),
                "quotation_id":      d.get("quotation_id"),
                "invoice_number":    d.get("invoice_number"),
                "billing_remarks":   d.get("notes", ""),
                "sub_total":         sub_total,
                "currency_id":       d.get("currency_id"),
                "total_amount":      total_amount,
                "discount_amt":      discount_amt,
                "created_at":        datetime.utcnow(),
                "invoice_date":      d.get("date"),
                "due_date":          d.get("due_date"),
                "status":            d.get("status", "Draft"),
                "delivery_address":  d.get("customer_address", ""),
                "delivery_phone":    d.get("customer_mobile", ""),
                "delivery_email":    d.get("customer_email", ""),
                "created_by_userid": request.current_user.id,
                "discount_pct":      discount_pct,
            }
        )
        invoice_id = result.fetchone()[0]

        _replace_items(session, invoice_id, items)
        _replace_taxes(session, invoice_id, taxes, TENANT_ID)

        session.commit()
        return jsonify({"invoice_id": invoice_id, "id": invoice_id}), 201

    except ValueError as e:
        # Raised by _replace_items when an item is missing product_variant_id
        session.rollback()
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Invoice create error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# PUT /invoices/<id>
# ═════════════════════════════════════════════════════════════════════════════
@invoice_bp.route('/invoices/<int:invoice_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_invoice(invoice_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = DevSessionLocal()
    try:
        d = request.get_json() or {}

        # Status-only update (from list page dropdown)
        if list(d.keys()) == ['status']:
            old_row = session.execute(
                text(f'SELECT status, client_id, invoice_number FROM {T("Invoice_Master")} WHERE invoice_id=:iid'),
                {"iid": invoice_id}
            ).fetchone()
            new_status = d["status"]

            session.execute(
                text(f'UPDATE {T("Invoice_Master")} SET status=:s, updated_at=NOW() WHERE invoice_id=:iid'),
                {"s": new_status, "iid": invoice_id}
            )
            session.commit()

            if new_status in ('Sent', 'Approved', 'Rejected', 'Paid'):
                client_name = _fetch_client_name(session, old_row.client_id) if old_row else "Client"
                emp_row = session.execute(
                    text(f'SELECT employee_id FROM {T("Employee_Master")} WHERE user_id = :uid LIMIT 1'),
                    {"uid": request.current_user.id}
                ).fetchone()
                emp_id = emp_row.employee_id if emp_row else None
                inum = (old_row.invoice_number if old_row else None) or f"INV-{invoice_id:04d}"
                cust = client_name or "Client"
                msg_map = {
                    'Sent':     f"📤 Invoice {inum} for {cust} has been marked as Sent",
                    'Approved': f"✅ Invoice {inum} for {cust} has been Approved",
                    'Rejected': f"❌ Invoice {inum} for {cust} has been Rejected",
                    'Paid':     f"💰 Invoice {inum} for {cust} has been marked as Paid",
                }
                create_notification(
                    session,
                    message=msg_map[new_status],
                    notification_type="invoice",
                    client_id=old_row.client_id if old_row else None,
                    created_by_employee_id=emp_id,
                    priority="high" if new_status in ('Approved', 'Paid') else "medium",
                )
                session.commit()

            return jsonify({"invoice_id": invoice_id}), 200

        sub_total = float(d.get("sub_total", 0))
        discount_amt = float(d.get("discount_amount", 0))
        discount_pct = float(d.get("discount_percentage", 0))
        total_amount = float(d.get("total_amount", d.get("grand_total", 0)))
        items = d.get("items", [])
        taxes = d.get("taxes")

        session.execute(
            text(f"""
                UPDATE {T("Invoice_Master")} SET
                    client_id=:client_id, project_id=:project_id, quotation_id=:quotation_id,
                    invoice_number=:invoice_number, billing_remarks=:billing_remarks,
                    sub_total_withouttax=:sub_total, total_amount=:total_amount,
                    discount_amount=:discount_amt, global_discount_percent=:discount_pct,
                    invoice_date=:invoice_date, due_date=:due_date, status=:status,
                    "Delivery_address"=:delivery_address, "Delivery_phone"=:delivery_phone,
                    "Delivery_email"=:delivery_email, updated_at=NOW()
                WHERE invoice_id=:invoice_id
            """),
            {
                "invoice_id":       invoice_id,
                "client_id":        d.get("client_id"),
                "project_id":       d.get("project_id"),
                "quotation_id":     d.get("quotation_id"),
                "invoice_number":   d.get("invoice_number"),
                "billing_remarks":  d.get("notes", ""),
                "sub_total":        sub_total,
                "total_amount":     total_amount,
                "discount_amt":     discount_amt,
                "discount_pct":     discount_pct,
                "invoice_date":     d.get("date"),
                "due_date":         d.get("due_date"),
                "status":           d.get("status", "Draft"),
                "delivery_address": d.get("customer_address", ""),
                "delivery_phone":   d.get("customer_mobile", ""),
                "delivery_email":   d.get("customer_email", ""),
            }
        )

        _replace_items(session, invoice_id, items)
        _replace_taxes(session, invoice_id, taxes, TENANT_ID)

        session.commit()
        return jsonify({"invoice_id": invoice_id}), 200

    except ValueError as e:
        session.rollback()
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Invoice update error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# DELETE /invoices/<id>
# ═════════════════════════════════════════════════════════════════════════════
@invoice_bp.route('/invoices/<int:invoice_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_invoice(invoice_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = DevSessionLocal()
    try:
        # Children first - no ON DELETE CASCADE assumed
        session.execute(
            text(f'DELETE FROM {T("Invoice_Tax_Details")} WHERE invoice_id = :iid'),
            {"iid": invoice_id}
        )
        session.execute(
            text(f'DELETE FROM {T("Invoice_Details")} WHERE invoice_id = :iid'),
            {"iid": invoice_id}
        )
        session.execute(
            text(f'DELETE FROM {T("Invoice_Master")} WHERE invoice_id=:iid'),
            {"iid": invoice_id}
        )
        session.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Invoice delete error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# GET /invoices/<id>/pdf
# ═════════════════════════════════════════════════════════════════════════════
@invoice_bp.route('/invoices/<int:invoice_id>/pdf', methods=['GET'])
def download_invoice_pdf(invoice_id):
    """Generate and return invoice as PDF — Warm Parchment edition.

    NOTE: bank details / GST / PAN / terms & conditions / payment terms /
    mode of enquiry / valid-for-days sections have been REMOVED from this
    PDF because those fields no longer exist anywhere in the new schema.
    This needs a follow-up design pass once you decide where (if anywhere)
    that data should live going forward.
    """
    session = DevSessionLocal()
    try:
        from io import BytesIO
        from flask import send_file
        from .pdf_helpers import (
            PDF, BROWN_DARK, BROWN_MID, BROWN_TEXT, BROWN_BORDER,
            BROWN_ACCENT, PARCHMENT_1, PARCHMENT_2, CREAM,
            draw_section_label,
        )

        row = session.execute(
            text(f'SELECT * FROM {T("Invoice_Master")} WHERE invoice_id = :iid'),
            {"iid": invoice_id}
        ).fetchone()
        if not row:
            return jsonify({"error": "Invoice not found"}), 404

        client_name = _fetch_client_name(session, row.client_id)
        items_raw = _fetch_items(session, invoice_id)
        taxes = _fetch_taxes(session, invoice_id)
        invoice = _serialize_invoice(row, client_name, items_raw, taxes)

        def number_to_words(num):
            ones  = ['','One','Two','Three','Four','Five','Six','Seven','Eight','Nine']
            tens  = ['','','Twenty','Thirty','Forty','Fifty','Sixty','Seventy','Eighty','Ninety']
            teens = ['Ten','Eleven','Twelve','Thirteen','Fourteen','Fifteen','Sixteen','Seventeen','Eighteen','Nineteen']
            if num == 0: return 'Zero'
            def b1000(n):
                if n==0: return ''
                if n<10: return ones[n]
                if n<20: return teens[n-10]
                if n<100: return tens[n//10]+(' '+ones[n%10] if n%10 else '')
                return ones[n//100]+' Hundred'+(' '+b1000(n%100) if n%100 else '')
            c=num//10000000; l=(num%10000000)//100000; t=(num%100000)//1000; r=num%1000
            res=''
            if c: res+=b1000(c)+' Crore '
            if l: res+=b1000(l)+' Lakh '
            if t: res+=b1000(t)+' Thousand '
            if r: res+=b1000(r)
            return res.strip()+' Only'

        def fmt(amount): return f"Rs. {(amount or 0):,.2f}"

        def sanitize(text_):
            if not text_: return ''
            for c,r in {'\u20b9':'Rs.','\u2014':'--','\u2013':'-','\u2019':"'",'\u201c':'"','\u201d':'"','\u2026':'...','\u2022':'-','\u00a0':' '}.items():
                text_ = text_.replace(c, r)
            return text_.encode('latin-1', errors='replace').decode('latin-1')

        def fmt_date(ds):
            if not ds: return '-'
            try: return datetime.fromisoformat(ds.replace('Z','')).strftime('%d %B %Y')
            except: return ds

        sub_total = float(invoice.get('sub_total') or 0)
        discount_pct = float(invoice.get('discount_percentage') or 0)
        discount_amt = float(invoice.get('discount_amount') or 0)
        igst_amt = float(invoice.get('igst_amount') or 0)
        grand_total = float(invoice.get('grand_total') or 0)

        lh = 5.5
        pdf = PDF('P', 'mm', 'A4')
        pdf.doc_title = ''
        pdf.contact_line = 'Property No. 630, Survey Number 37/1 to 4/1/1, Pisoli, Pune-411060  *  9833133772  *  8983340496  *  8983340497  *  info@forklift.academy'
        pdf.alias_nb_pages()
        pdf.set_margins(12, 12, 12)
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=18)
        page_w = pdf.w; margin = pdf.l_margin; body_w = page_w - margin * 2

        # Meta strip
        meta_h = 7
        pdf.set_fill_color(254, 249, 244); pdf.set_draw_color(*BROWN_BORDER)
        pdf.rect(margin, pdf.get_y(), body_w, meta_h, 'FD')
        y_meta = pdf.get_y()
        pdf.set_xy(margin+3, y_meta+1)
        pdf.set_font('Arial','B',9); pdf.set_text_color(*BROWN_DARK)
        pdf.cell(60, 5, invoice.get('invoice_number') or f"INV-{invoice_id:04d}", 0, 0, 'L')
        pdf.set_font('Arial','',8); pdf.set_text_color(*BROWN_MID)
        pdf.cell(40, 5, fmt_date(invoice.get('date')), 0, 0, 'L')
        badge_label = 'TAX INVOICE'
        pdf.set_font('Arial','B',7)
        bw = pdf.get_string_width(badge_label)+8; bx = margin+body_w-bw-2
        pdf.set_draw_color(*BROWN_DARK); pdf.set_fill_color(255,255,255)
        pdf.rect(bx, y_meta+1, bw, 5, 'D'); pdf.set_xy(bx, y_meta+1)
        pdf.set_text_color(*BROWN_DARK); pdf.cell(bw, 5, badge_label, 0, 0, 'C')
        pdf.set_text_color(*BROWN_TEXT); pdf.set_draw_color(*BROWN_TEXT); pdf.ln(meta_h+4)

        # Invoice Information
        draw_section_label(pdf, 'INVOICE INFORMATION')
        half = body_w/2-4; y_info = pdf.get_y()
        pdf.set_xy(margin, y_info)
        pdf.set_font('Arial','',7); pdf.set_text_color(*BROWN_MID); pdf.cell(half, 4, 'TO', 0, 1, 'L')
        pdf.set_x(margin); pdf.set_font('Arial','B',9); pdf.set_text_color(*BROWN_TEXT)
        pdf.cell(half, 5, invoice.get('customer_name') or '-', 0, 1, 'L')
        if invoice.get('customer_address'):
            pdf.set_x(margin); pdf.set_font('Arial','',7.5); pdf.set_text_color(*BROWN_MID)
            pdf.multi_cell(half, 4, sanitize(invoice.get('customer_address')), 0, 'L')
        pdf.set_x(margin); pdf.set_font('Arial','',7.5); pdf.set_text_color(*BROWN_ACCENT)
        if invoice.get('customer_mobile'): pdf.cell(half, 4, f"Mobile: {invoice.get('customer_mobile')}", 0, 1, 'L')
        if invoice.get('customer_email'):  pdf.cell(half, 4, f"Email: {invoice.get('customer_email')}", 0, 1, 'L')
        y_after_left = pdf.get_y()

        rx = margin+half+8; pdf.set_xy(rx, y_info)
        right_w = body_w-half-8; lw_r = right_w*0.48
        for label, value in [
            ('Invoice #', invoice.get('invoice_number') or f"INV-{invoice_id:04d}"),
            ('Date',      fmt_date(invoice.get('date'))),
            ('Due date',  fmt_date(invoice.get('due_date'))),
        ]:
            y_row = pdf.get_y(); pdf.set_xy(rx, y_row)
            pdf.set_font('Arial','',7.5); pdf.set_text_color(*BROWN_MID); pdf.cell(lw_r, lh, label, 0, 0, 'L')
            pdf.set_font('Arial','B',7.5); pdf.set_text_color(*BROWN_TEXT); pdf.cell(right_w-lw_r, lh, str(value), 0, 0, 'R')
            pdf.ln(lh); pdf.set_draw_color(*BROWN_BORDER); pdf.line(rx, pdf.get_y(), rx+right_w, pdf.get_y())
        pdf.set_draw_color(*BROWN_TEXT); pdf.set_text_color(*BROWN_TEXT)
        pdf.set_y(max(y_after_left, pdf.get_y())+5)

        # Items table
        draw_section_label(pdf, 'ITEMS')
        col_w = [10, 88, 16, 28, 28]
        headers = ['Sr.','Description','N.O.P','Unit Rate','Amount']
        aligns  = ['C','L','C','R','R']
        hdr_h = 7
        pdf.set_fill_color(*BROWN_DARK); pdf.set_text_color(*CREAM); pdf.set_font('Arial','B',7)
        for h,w,a in zip(headers, col_w, aligns): pdf.cell(w, hdr_h, h, 0, 0, a, 1)
        pdf.ln(hdr_h); pdf.set_text_color(*BROWN_TEXT)

        items = invoice.get('items') or []
        for idx, item in enumerate(items):
            rate = float(item.get('unit_price') or 0)
            qty  = float(item.get('quantity') or 0)
            amount = float(item.get('amount') or (rate * qty))
            desc = sanitize(item.get('product_name') or item.get('description') or '-')
            pdf.set_font('Arial','',7.5)
            n_lines = max(1, len(desc)//60+(1 if len(desc)%60 else 0))
            row_h = max(7, n_lines*4.5)
            fill_color = PARCHMENT_1 if idx%2==0 else PARCHMENT_2
            pdf.set_fill_color(*fill_color)
            rx0=margin; ry0=pdf.get_y()
            pdf.set_text_color(*BROWN_MID); pdf.cell(col_w[0], row_h, str(idx+1), 0, 0, 'C', 1)
            xd,yd=pdf.get_x(),pdf.get_y()
            pdf.set_fill_color(*fill_color); pdf.set_font('Arial','',7.5); pdf.set_text_color(*BROWN_TEXT)
            pdf.multi_cell(col_w[1], 4.5, desc, 0, 'L', 1)
            actual_h=pdf.get_y()-yd; row_h=max(row_h, actual_h)
            if actual_h<row_h:
                pdf.set_fill_color(*fill_color); pdf.set_xy(xd, yd+actual_h); pdf.cell(col_w[1], row_h-actual_h, '', 0, 0, 'L', 1)
            pdf.set_xy(xd+col_w[1], yd); pdf.set_fill_color(*fill_color)
            pdf.set_font('Arial','',8); pdf.set_text_color(*BROWN_TEXT)
            pdf.cell(col_w[2], row_h, str(int(qty)), 0, 0, 'C', 1)
            pdf.cell(col_w[3], row_h, fmt(rate), 0, 0, 'R', 1)
            pdf.set_font('Arial','B',8); pdf.cell(col_w[4], row_h, fmt(amount), 0, 0, 'R', 1)
            pdf.set_draw_color(*BROWN_BORDER); pdf.line(rx0, yd+row_h, rx0+body_w, yd+row_h)
            pdf.set_draw_color(*BROWN_TEXT); pdf.set_text_color(*BROWN_TEXT); pdf.set_font('Arial','',8); pdf.ln(row_h)

        if not items:
            pdf.set_font('Arial','',8); pdf.set_text_color(*BROWN_MID)
            pdf.cell(body_w, 8, 'No items found', 0, 1, 'C'); pdf.set_text_color(*BROWN_TEXT)

        pdf.ln(5)

        # Financial Summary (bank details section removed - no columns for it anymore)
        draw_section_label(pdf, 'FINANCIAL SUMMARY')
        rx2 = margin; rw = body_w; lw_t = rw*0.7
        totals_rows = [('Sub total', f'{fmt(sub_total)}')]
        if discount_pct > 0 or discount_amt > 0:
            totals_rows.append((f'Discount ({discount_pct:.0f}%)' if discount_pct else 'Discount', f'- {fmt(discount_amt)}'))
        for tax in taxes:
            label = tax.get("remarks") or f"Tax (id {tax.get('tax_id')})"
            totals_rows.append((label, f'+ {fmt(tax.get("tax_amount"))}'))
        for label, value in totals_rows:
            y_row=pdf.get_y(); pdf.set_xy(rx2, y_row)
            pdf.set_font('Arial','',7.5); pdf.set_text_color(*BROWN_MID); pdf.cell(lw_t, lh, label, 0, 0, 'L')
            pdf.set_font('Arial','B',7.5); pdf.set_text_color(*BROWN_TEXT); pdf.cell(rw-lw_t, lh, value, 0, 0, 'R')
            pdf.ln(lh); pdf.set_draw_color(*BROWN_BORDER); pdf.line(rx2, pdf.get_y(), rx2+rw, pdf.get_y())
        pdf.ln(2)
        gt_h=9; gt_y=pdf.get_y()
        pdf.set_fill_color(*BROWN_DARK); pdf.rect(rx2, gt_y, rw, gt_h, 'F')
        pdf.set_xy(rx2, gt_y); pdf.set_font('Arial','B',9); pdf.set_text_color(*CREAM)
        pdf.cell(lw_t, gt_h, 'Grand Total', 0, 0, 'L')
        pdf.cell(rw-lw_t, gt_h, f'{fmt(grand_total)}', 0, 0, 'R')
        pdf.ln(gt_h+2); pdf.set_text_color(*BROWN_TEXT)
        pdf.set_x(rx2); pdf.set_font('Arial','I',7.5); pdf.set_text_color(*BROWN_MID)
        pdf.cell(rw, 5, f'Amount in words: {number_to_words(round(grand_total))}', 0, 1, 'R')
        pdf.set_text_color(*BROWN_TEXT)

        pdf.ln(5)
        pdf.set_draw_color(*BROWN_BORDER); pdf.line(margin, pdf.get_y(), margin+body_w, pdf.get_y()); pdf.ln(3)
        pdf.set_font('Arial','',7.5); pdf.set_text_color(*BROWN_MID)
        pdf.cell(0, 4, 'For more information about our training programmes, visit www.forklift.academy', 0, 1, 'C')
        pdf.set_text_color(*BROWN_TEXT)

        out = pdf.output(dest='S')
        if isinstance(out, str): out = out.encode('latin-1')
        buf = BytesIO(bytes(out))
        inum = invoice.get('invoice_number') or str(invoice_id)
        cust = (invoice.get('customer_name') or 'Customer').replace(' ','_')
        return send_file(buf, mimetype='application/pdf', as_attachment=False, download_name=f"Invoice_{inum}_{cust}.pdf")

    except Exception as e:
        current_app.logger.exception(f"Invoice PDF failed: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()
