"""
Make FAI quotations work on the new tables (Quotation_Master_new /
Quotation_Details_new) in "streemLyne_mt_dev2".

1. Set-up data the new quotation design needs (FAI, tenant 3):
   - UOM_Master: the units FAI's courses use ("per participant", "per day",
     "per month") plus "each".
   - Product_Variant: one "Standard" variant per FAI course in Product_Master,
     linked from PriceList_Master.variant_id, so price-list rows can be quoted.
   - One catalogue entry "Custom / imported line" (no price-list row, so it
     can't be picked for new quotes) for free-text lines of old quotations.
2. Copies FAI's old-format quotations (Quotation_Master / Quotation_Details,
   including those brought over from the old StreemLyne database) into the
   new tables, keeping their original numbers. Lines that match a course use
   its variant; free-text lines use "Custom / imported line" with their
   wording kept.

Usage: python fai_quotations_to_new.py --target <DB URL> [--dry-run]
One transaction; re-runnable (copied quotes are logged in migration.fai_id_map).
"""

import argparse
import sys
from decimal import Decimal

import psycopg2
import psycopg2.extras

S = '"streemLyne_mt_dev2"'
TENANT = 3
UNITS = [('PARTICIPANT', 'per participant'), ('DAY', 'per day'), ('MONTH', 'per month'), ('EACH', 'each')]
STATUS_ID = {'Draft': 5, 'Pending': 6, 'Sent': 7, 'Approved': 8, 'Rejected': 9, 'Expired': 7}
CUSTOM_CODE = 'CUSTOM-LINE'


def q(cur, sql, params=()):
    cur.execute(sql, params)
    return cur


def setup(cur, counts):
    for code, desc in UNITS:
        if not q(cur, f'SELECT 1 FROM {S}."UOM_Master" WHERE upper(trim(uom_code)) = %s', (code,)).fetchone():
            q(cur, f'INSERT INTO {S}."UOM_Master"(uom_code, uom_description, created_at) VALUES (%s, %s, now())',
              (code, desc))
            counts['units added'] = counts.get('units added', 0) + 1

    if not q(cur, f'SELECT 1 FROM {S}."Product_Master" WHERE tenant_id = %s AND item_code = %s',
             (TENANT, CUSTOM_CODE)).fetchone():
        q(cur, f"""INSERT INTO {S}."Product_Master"(tenant_id, sku, item_name, description, category, active,
                       created_at, updated_at, item_code, unit, base_price)
                   VALUES (%s, %s, 'Custom / imported line',
                           'Free-text line from an older quotation (not for new quotes)',
                           'Imported', true, now(), now(), %s, 'each', 0)""",
          (TENANT, CUSTOM_CODE, CUSTOM_CODE))
        counts['catalogue entry for free-text lines'] = 1

    # one Standard variant per FAI product that has none
    for (pid, code) in q(cur, f"""SELECT p.product_id, coalesce(p.item_code, p.sku, p.product_id::text)
                                  FROM {S}."Product_Master" p
                                  WHERE p.tenant_id = %s AND NOT EXISTS
                                        (SELECT 1 FROM {S}."Product_Variant" v WHERE v.product_id = p.product_id)""",
                         (TENANT,)).fetchall():
        q(cur, f"""INSERT INTO {S}."Product_Variant"(product_id, sku_variant, variant_label, active,
                       created_at, updated_at, tenant_id, is_sub_item)
                   VALUES (%s, %s, 'Standard', true, now(), now(), %s, false)""", (pid, code, TENANT))
        counts['course variants added'] = counts.get('course variants added', 0) + 1

    n = q(cur, f"""UPDATE {S}."PriceList_Master" pl
                   SET variant_id = (SELECT min(v.variant_id) FROM {S}."Product_Variant" v
                                     WHERE v.product_id = pl.product_id)
                   WHERE pl.tenant_id = %s AND pl.variant_id IS NULL AND pl.product_id IS NOT NULL""",
          (TENANT,)).rowcount
    if n:
        counts['price-list rows linked to a variant'] = n


def variant_for(cur, item_name, pricelist_id, cache):
    key = ((item_name or '').strip().upper(), pricelist_id)
    if key in cache:
        return cache[key]
    row = None
    if pricelist_id:
        row = q(cur, f"""SELECT pl.variant_id, p.unit FROM {S}."PriceList_Master" pl
                         JOIN {S}."Product_Master" p ON p.product_id = pl.product_id
                         WHERE pl.pricelist_id = %s AND pl.variant_id IS NOT NULL""", (pricelist_id,)).fetchone()
    if not row and key[0]:
        row = q(cur, f"""SELECT v.variant_id, p.unit FROM {S}."Product_Master" p
                         JOIN {S}."Product_Variant" v ON v.product_id = p.product_id
                         WHERE p.tenant_id = %s AND p.item_code <> %s
                           AND (upper(trim(p.item_name)) = %s OR upper(trim(p.item_code)) = %s)
                         ORDER BY v.variant_id LIMIT 1""", (TENANT, CUSTOM_CODE, key[0], key[0])).fetchone()
    custom = False
    if not row:
        row = q(cur, f"""SELECT v.variant_id, p.unit FROM {S}."Product_Master" p
                         JOIN {S}."Product_Variant" v ON v.product_id = p.product_id
                         WHERE p.tenant_id = %s AND p.item_code = %s ORDER BY v.variant_id LIMIT 1""",
                 (TENANT, CUSTOM_CODE)).fetchone()
        custom = True
    uom = q(cur, f"""SELECT uom_id FROM {S}."UOM_Master"
                     WHERE upper(trim(uom_description)) = upper(trim(%s)) OR upper(trim(uom_code)) = upper(trim(%s))
                     ORDER BY uom_id LIMIT 1""", (row[1] or 'each', row[1] or 'each')).fetchone()
    if not uom:
        uom = q(cur, f"SELECT uom_id FROM {S}.\"UOM_Master\" WHERE uom_code = 'EACH'").fetchone()
    cache[key] = (row[0], uom[0], custom)
    return cache[key]


def user_for_employee(cur, employee_id):
    if employee_id:
        r = q(cur, f'SELECT min(user_id) FROM {S}."User_Master" WHERE employee_id = %s', (employee_id,)).fetchone()
        if r and r[0]:
            return r[0]
    return None


def convert(cur, dcur, counts):
    q(cur, """CREATE SCHEMA IF NOT EXISTS migration""")
    q(cur, """CREATE TABLE IF NOT EXISTS migration.fai_id_map (
                entity text NOT NULL, old_id text NOT NULL, new_id text NOT NULL,
                migrated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (entity, old_id))""")
    fallback_user = q(cur, f'SELECT min(user_id) FROM {S}."User_Master" WHERE tenant_id = %s', (TENANT,)).fetchone()[0]
    cache = {}
    quotes = q(dcur, f'SELECT * FROM {S}."Quotation_Master" WHERE tenant_id = %s ORDER BY quotation_id',
               (TENANT,)).fetchall()
    for m in quotes:
        if q(cur, "SELECT 1 FROM migration.fai_id_map WHERE entity = 'legacy_quotation' AND old_id = %s",
             (str(m['quotation_id']),)).fetchone():
            continue
        lines = q(dcur, f'SELECT * FROM {S}."Quotation_Details" WHERE quotation_id = %s ORDER BY item_id',
                  (m['quotation_id'],)).fetchall()
        meta = (m.get('metadata') or {}).get('legacy_streemlyne_mt', {}) if isinstance(m.get('metadata'), dict) else {}
        new_lines = []
        for d in lines:
            variant_id, uom_id, custom = variant_for(cur, d['item_name'], d['pricelist_id'], cache)
            qty = Decimal(d['quantity'] or 1)
            rate = Decimal(d['unit_price_snapshot'] if d['unit_price_snapshot'] is not None else (d['amount'] or 0))
            gross = rate * qty
            total = Decimal(d['discounted_amount']) if d['discounted_amount'] is not None else gross
            new_lines.append((variant_id, float(qty), uom_id, float(rate), float(max(gross - total, 0)),
                              (d['item_name'] or 'Item')[:500], d['description'], float(total)))
            if custom:
                counts['free-text lines kept as "Custom / imported line"'] = \
                    counts.get('free-text lines kept as "Custom / imported line"', 0) + 1
        sub_total = m['sub_total'] if m['sub_total'] is not None else sum(Decimal(str(l[7])) for l in new_lines)
        tax = meta.get('vat_amount') or 0
        new_id = q(cur, f"""INSERT INTO {S}."Quotation_Master_new"(
                        "Tenant_ID", "Client_ID", "Project_ID", "Quotation_Number", "Created_by_user_ID",
                        "Quotation_Date", "Valid_Until", "Status_ID", "Approved_By_User_ID", "Approval_Date",
                        "Sub_Total", "Tax_Amount", "Discount_percent", "Updated_At", notes, terms)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING "Quotation_ID" """,
                     (TENANT, m['client_id'], None, m['reference_number'],
                      user_for_employee(cur, m['created_by_employee_id']) or fallback_user,
                      (m['created_at'] or m['updated_at']).date() if (m['created_at'] or m['updated_at']) else None,
                      m['valid_until'].date() if m['valid_until'] else None,
                      STATUS_ID.get(m['status'] or 'Draft', 5),
                      user_for_employee(cur, m['approved_by_employee_id']),
                      m['approved_at'].date() if m['approved_at'] else None,
                      sub_total, tax, m['global_discount_percent'], m['updated_at'], m['notes'],
                      meta.get('additional_terms'))).fetchone()[0]
        for l in new_lines:
            q(cur, f"""INSERT INTO {S}."Quotation_Details_new"(
                        "Quotation_ID", "Product_Variant_ID", "Quantity", "UOM_ID", "Rate", "Discount_Amount",
                        "Tax_Amount", "Item_Name", "Description", "Total_Amount")
                       VALUES (%s, %s, %s, %s, %s, %s, 0, %s, %s, %s)""", (new_id, *l))
        q(cur, "INSERT INTO migration.fai_id_map(entity, old_id, new_id) VALUES ('legacy_quotation', %s, %s)",
          (str(m['quotation_id']), str(new_id)))
        counts['quotations copied to the new table'] = counts.get('quotations copied to the new table', 0) + 1
        counts['quotation lines copied'] = counts.get('quotation lines copied', 0) + len(new_lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', required=True)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    conn = psycopg2.connect(a.target)
    counts = {}
    try:
        with conn.cursor() as cur:
            setup(cur, counts)
        with conn.cursor() as cur, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as dcur:
            convert(cur, dcur, counts)
        for k, v in counts.items():
            print(f'  {k}: {v}')
        if a.dry_run:
            conn.rollback()
            print('DRY RUN - rolled back, nothing saved')
        else:
            conn.commit()
            print('COMMITTED')
    except Exception:
        conn.rollback()
        print('FAILED - rolled back, nothing saved', file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
