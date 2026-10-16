"""
Copy FAI's records (tenant 3) from the old StreemLyne database
(schema "StreemLyne_MT") into the shared database (schema
"streemLyne_mt_dev2"), next to the FAI records already there.

Usage:
    python migrate_fai_from_streemlyne_mt.py --source <old DB URL> --target <new DB URL> [--dry-run]

- The source is only read.
- Everything is written in one transaction on the target: all or nothing.
- Each copied record's old and new ID is stored in migration.fai_id_map
  (a separate schema, not used by the app), so the copy can be re-run
  (already-copied records are skipped) or undone later.
- Logins whose username already exists in the target (e.g. daniya.fai)
  are linked to the existing account instead of being duplicated.
- Old fields with no column in the new Client_Master are kept in
  Client_Master.metadata -> 'legacy_streemlyne_mt'.

Where things go:
    Employee_Master / User_Master / User_Role_Mapping -> same tables
    Client_Master            -> Client_Master (+ contacts in Contact_Master
                                and Client_Contact_Mapping)
    Client_Interactions      -> Client_Interactions
    Client_Files             -> Client_Files (storage links unchanged)
    Opportunity_Details      -> Lead_Master
    Training_Details         -> Services_Master_archive (old batch format,
                                converted with the rest when training moves
                                to Training_Master_New)
    Quotations / _Items      -> Quotation_Master / Quotation_Details (the new
                                Quotation_Details_new needs product variants,
                                which don't exist yet)
    Notification_Master      -> Notification_Master
    PriceList_Master         -> not copied (the target already holds FAI's
                                course prices in the new product-based format)
"""

import argparse
import json
import sys
from datetime import date, datetime
from decimal import Decimal

import psycopg2
import psycopg2.extras

OLD = '"StreemLyne_MT"'
NEW = '"streemLyne_mt_dev2"'
FAI_OLD_TENANT = '3'      # varchar in the old database
FAI_NEW_TENANT = 3

# Old Stage_Master names (sales and training) -> Pipeline_Stage_Master ids
LEAD_STAGE_BY_OLD_NAME = {
    'Not Called': 1, 'Lead': 1, 'Enquiry': 1,
    'Sales Qualified Lead': 2,
    'Proposal': 4,
    'Converted': 6, 'Customer': 6,
    'Training Scheduled': 6, 'Training Completed': 6,   # training only starts once won
    'Lost': 7,
}
QUOTE_STATUS = {'Draft', 'Sent', 'Approved', 'Rejected', 'Expired'}


def jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (str, int, float, bool, list, dict)) or v is None:
        return v
    return str(v)


class Migrator:
    def __init__(self, src, dst, log):
        self.src, self.dst, self.log = src, dst, log
        self.cols = {}
        self.counts = {}
        self.mapped = {}

    # ------------------------------------------------------------ helpers
    def target_cols(self, table):
        if table not in self.cols:
            with self.dst.cursor() as c:
                c.execute("""SELECT column_name FROM information_schema.columns
                             WHERE table_schema = 'streemLyne_mt_dev2' AND table_name = %s""", (table,))
                self.cols[table] = {r[0] for r in c.fetchall()}
        return self.cols[table]

    def old_rows(self, sql, params=()):
        with self.src.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
            c.execute(sql, params)
            return c.fetchall()

    def new_id(self, entity, old_id):
        if old_id is None:
            return None
        key = (entity, str(old_id))
        if key not in self.mapped:
            with self.dst.cursor() as c:
                c.execute("SELECT new_id FROM migration.fai_id_map WHERE entity = %s AND old_id = %s", key)
                r = c.fetchone()
            self.mapped[key] = int(r[0]) if r else None
        return self.mapped[key]

    def remember(self, entity, old_id, new_id):
        with self.dst.cursor() as c:
            c.execute("INSERT INTO migration.fai_id_map(entity, old_id, new_id) VALUES (%s, %s, %s)",
                      (entity, str(old_id), str(new_id)))
        self.mapped[(entity, str(old_id))] = int(new_id)

    def fks(self, table):
        """Single-column foreign keys of a target table: {column: (ref_table, ref_column)}."""
        if ('fk', table) not in self.cols:
            with self.dst.cursor() as c:
                c.execute("""SELECT a.attname, rc.relname, ra.attname
                             FROM pg_constraint k
                             JOIN pg_class tc ON tc.oid = k.conrelid
                             JOIN pg_namespace n ON n.oid = tc.relnamespace
                             JOIN pg_class rc ON rc.oid = k.confrelid
                             JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = k.conkey[1]
                             JOIN pg_attribute ra ON ra.attrelid = k.confrelid AND ra.attnum = k.confkey[1]
                             WHERE k.contype = 'f' AND n.nspname = 'streemLyne_mt_dev2'
                               AND tc.relname = %s AND array_length(k.conkey, 1) = 1""", (table,))
                self.cols[('fk', table)] = {r[0]: (r[1], r[2]) for r in c.fetchall()}
        return self.cols[('fk', table)]

    def exists(self, ref_table, ref_col, value):
        key = ('exists', ref_table, ref_col, str(value))
        if key not in self.mapped:
            with self.dst.cursor() as c:
                c.execute(f'SELECT 1 FROM {NEW}."{ref_table}" WHERE "{ref_col}" = %s LIMIT 1', (value,))
                self.mapped[key] = c.fetchone() is not None
        return self.mapped[key]

    def insert(self, table, row, pk):
        cols = self.target_cols(table)
        data = {k: v for k, v in row.items() if k in cols and k != pk}
        # Lookups the new database doesn't have (e.g. an empty Currency_Master)
        # are left empty; the original values are kept for reference.
        dropped = {}
        for col, (ref_table, ref_col) in self.fks(table).items():
            v = data.get(col)
            if v is not None and not self.exists(ref_table, ref_col, v):
                dropped[col] = v
                data[col] = None
        if dropped:
            self.bump(f'{table}: missing lookup values left empty')
            if 'metadata' in data and isinstance(data['metadata'], dict):
                data['metadata'].setdefault('legacy_streemlyne_mt', {})['unmatched_lookups'] = dropped
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                data[k] = psycopg2.extras.Json(v, dumps=lambda o: json.dumps(o, default=jsonable))
        names = ', '.join(f'"{k}"' for k in data)
        marks = ', '.join(['%s'] * len(data))
        with self.dst.cursor() as c:
            c.execute(f'INSERT INTO {NEW}."{table}" ({names}) VALUES ({marks}) RETURNING "{pk}"',
                      list(data.values()))
            return c.fetchone()[0]

    def bump(self, what, n=1):
        self.counts[what] = self.counts.get(what, 0) + n

    # ------------------------------------------------------------ steps
    def setup(self):
        with self.dst.cursor() as c:
            c.execute("CREATE SCHEMA IF NOT EXISTS migration")
            c.execute("""CREATE TABLE IF NOT EXISTS migration.fai_id_map (
                           entity text NOT NULL, old_id text NOT NULL, new_id text NOT NULL,
                           migrated_at timestamptz NOT NULL DEFAULT now(),
                           PRIMARY KEY (entity, old_id))""")

    def employees_and_users(self):
        users = self.old_rows(f"""SELECT u.*, e.employee_name, e.phone, e.email, e.date_of_birth,
                                         e.date_of_joining, e.id_type, e.id_number, e.role_ids,
                                         e.created_on, e.updated_on, e.commission_percentage,
                                         e.company_name, e.is_active AS employee_is_active
                                  FROM {OLD}."User_Master" u
                                  JOIN {OLD}."Employee_Master" e USING (employee_id)
                                  WHERE u.tenant_id::text = %s ORDER BY u.user_id""", (FAI_OLD_TENANT,))
        for u in users:
            if self.new_id('user', u['user_id']):
                continue
            with self.dst.cursor() as c:
                c.execute(f'SELECT user_id, employee_id FROM {NEW}."User_Master" WHERE username = %s',
                          (u['user_name'],))
                existing = c.fetchone()
            if existing:
                self.remember('user', u['user_id'], existing[0])
                self.remember('employee', u['employee_id'], existing[1])
                self.bump('logins linked to an existing account')
                continue
            emp_id = self.insert('Employee_Master', {
                'tenant_id': FAI_NEW_TENANT, 'employee_name': u['employee_name'], 'phone': u['phone'],
                'email': u['email'], 'date_of_birth': u['date_of_birth'], 'date_of_joining': u['date_of_joining'],
                'id_type': u['id_type'], 'id_number': u['id_number'], 'role_ids': u['role_ids'],
                'created_on': u['created_on'], 'updated_on': u['updated_on'],
                'commission_percentage': u['commission_percentage'], 'company_name': u['company_name'],
                'is_active': u['employee_is_active'] if u['employee_is_active'] is not None else True,
            }, 'employee_id')
            self.remember('employee', u['employee_id'], emp_id)
            user_id = self.insert('User_Master', {
                'employee_id': emp_id, 'tenant_id': FAI_NEW_TENANT, 'username': u['user_name'],
                'password': u['password'], 'created_at': u['created_at'], 'updated_at': u['updated_at'],
                'is_active': u['is_active'] if u['is_active'] is not None else True,
                'is_invite_pending': u['is_invite_pending'], 'invite_token': u['invite_token'],
                'invite_expires_at': u['invite_expires_at'],
            }, 'user_id')
            self.remember('user', u['user_id'], user_id)
            self.bump('staff + logins')
            for r in self.old_rows(f"""SELECT r.role_name FROM {OLD}."User_Role_Mapping" m
                                       JOIN {OLD}."Role_Master" r USING (role_id) WHERE m.user_id = %s""",
                                   (u['user_id'],)):
                with self.dst.cursor() as c:
                    c.execute(f'SELECT role_id FROM {NEW}."Role_Master" WHERE role_name = %s', (r['role_name'],))
                    role = c.fetchone()
                if role:
                    self.insert('User_Role_Mapping', {'user_id': user_id, 'role_id': role[0]}, 'user_role_mapping_id')
                    self.bump('role assignments')

    def user_for_employee(self, old_employee_id):
        rows = self.old_rows(f'SELECT user_id FROM {OLD}."User_Master" WHERE employee_id = %s', (old_employee_id,))
        return self.new_id('user', rows[0]['user_id']) if rows else None

    def customers(self):
        keep = {'client_company_name', 'address', 'country_id', 'post_code', 'client_phone', 'client_email',
                'client_website', 'default_currency_id', 'created_at', 'company_number', 'display_order',
                'stage_updated_at', 'default_margin_pct', 'notes', 'enquiries'}
        for c in self.old_rows(f'SELECT * FROM {OLD}."Client_Master" WHERE tenant_id::text = %s ORDER BY client_id',
                               (FAI_OLD_TENANT,)):
            if self.new_id('client', c['client_id']):
                continue
            legacy = {k: jsonable(v) for k, v in c.items()
                      if k not in keep and v not in (None, '', [], {}) and k not in ('client_id', 'tenant_id')}
            legacy['old_client_id'] = c['client_id']
            row = {k: c[k] for k in keep}
            # company name is required in the new table; individuals often have none
            row['client_company_name'] = (c.get('client_company_name') or c.get('company_name_freetext')
                                          or c.get('client_contact_name') or c.get('primary_contact_name')
                                          or c.get('client_email') or f"Customer {c['client_id']}")
            row.update({
                'tenant_id': FAI_NEW_TENANT,
                'status_id': 4 if c.get('is_deleted') else 1,       # Status_Master: 1 Active, 4 Deleted
                'Client_Category_Master_ID': 1,                     # Commercial
                # required; despite its name this column references Employee_Master.
                # Old records often have no creator: use FAI's first employee.
                'created_by_user_id': self.new_id('employee', c.get('created_by_employee_id')) or self.any_fai_employee(),
                'metadata': {'legacy_streemlyne_mt': legacy,
                             **({'payments': c['payments']} if c.get('payments') else {})},
            })
            new_id = self.insert('Client_Master', row, 'client_id')
            self.remember('client', c['client_id'], new_id)
            self.bump('customers')
            self.contacts_for(c, new_id)

    def contacts_for(self, c, new_client_id):
        ids_by_person = {}   # the same person can be primary and finance contact
        for role, name, email, phone in (
            ('Primary', c.get('primary_contact_name') or c.get('client_contact_name'),
             c.get('primary_contact_email'), c.get('primary_contact_phone')),
            ('Purchase', c.get('purchase_contact_name'), c.get('purchase_contact_email'), c.get('purchase_contact_phone')),
            ('Finance', c.get('finance_contact_name'), c.get('finance_contact_email'), c.get('finance_contact_phone')),
        ):
            if not name or not str(name).strip():
                continue
            person = (str(name).strip().lower(), (email or '').lower())
            if person not in ids_by_person:
                ids_by_person[person] = self.insert('Contact_Master', {
                    'tenant_id': FAI_NEW_TENANT, 'full_name': str(name).strip(), 'phone': phone or '',
                    'email': email, 'department': c.get('primary_contact_department') if role == 'Primary' else None,
                    'is_active': True, 'created_at': c.get('created_at'),
                }, 'contact_id')
                self.bump('contacts')
            self.insert('Client_Contact_Mapping', {'client_id': new_client_id, 'contact_id': ids_by_person[person],
                                                    'role': role}, 'Client_Contact_Mapping_ID')

    def by_client(self, old_table, new_table, pk, entity, fix=None):
        rows = self.old_rows(f"""SELECT x.* FROM {OLD}."{old_table}" x
                                 JOIN {OLD}."Client_Master" c USING (client_id)
                                 WHERE c.tenant_id::text = %s ORDER BY 1""", (FAI_OLD_TENANT,))
        for r in rows:
            old_pk = r[list(r.keys())[0]] if pk not in r else r[pk]
            if self.new_id(entity, old_pk):
                continue
            row = dict(r)
            row['client_id'] = self.new_id('client', r['client_id'])
            if fix:
                row = fix(row)
                if row is None:
                    continue
            new_id = self.insert(new_table, row, pk)
            self.remember(entity, old_pk, new_id)
            self.bump(new_table)

    def interactions_and_files(self):
        def fix_file(r):
            r['uploaded_by'] = self.user_for_employee(r.get('uploaded_by')) if r.get('uploaded_by') else None
            return r
        def fix_interaction(r):
            # code 150 = old FAI quotation entries; not in the new list -> "Other" (5).
            # The entry's content stays unchanged in notes.
            if r.get('contact_method') is not None and not self.exists('Contact_Method_Master', 'contact_method_id', r['contact_method']):
                r['contact_method'] = 5
                self.bump('interactions filed as Other (unknown old code)')
            return r
        self.by_client('Client_Interactions', 'Client_Interactions', 'interaction_id', 'interaction', fix_interaction)
        self.by_client('Client_Files', 'Client_Files', 'id', 'file', fix_file)

    def opportunities_to_leads(self):
        rows = self.old_rows(f"""SELECT o.*, s.stage_name AS old_stage, c.client_company_name
                                 FROM {OLD}."Opportunity_Details" o
                                 JOIN {OLD}."Client_Master" c USING (client_id)
                                 LEFT JOIN {OLD}."Stage_Master" s ON s.stage_id = o.stage_id
                                 WHERE c.tenant_id::text = %s ORDER BY o.opportunity_id""", (FAI_OLD_TENANT,))
        for o in rows:
            if self.new_id('opportunity', o['opportunity_id']):
                continue
            stage = LEAD_STAGE_BY_OLD_NAME.get(o['old_stage'] or '', 1)
            owner = o.get('opportunity_owner_employee_id') or o.get('assigned_to_employee_id')
            lead_id = self.insert('Lead_Master', {
                'tenant_id': FAI_NEW_TENANT,
                'client_ID': self.new_id('client', o['client_id']),
                'assigned_employee_id': self.new_id('employee', owner),
                'stage_id': stage,
                'lead_title': o.get('opportunity_title') or o['client_company_name'] or 'Lead',
                'lead_description': o.get('opportunity_description') or o.get('notes') or '',
                'lead_date': o.get('opportunity_date') or (o['created_at'].date() if o.get('created_at') else date.today()),
                'expected_value': int(o['opportunity_value']) if o.get('opportunity_value') else None,
                'currency_id': o.get('currency_id'),
                'created_date': o['created_at'].date() if o.get('created_at') else None,
                'won_at': o.get('created_at') if stage == 6 else None,
            }, 'lead_id')
            self.remember('opportunity', o['opportunity_id'], lead_id)
            self.bump('leads')

    def training_batches(self):
        for t in self.old_rows(f"""SELECT t.* FROM {OLD}."Training_Details" t
                                   JOIN {OLD}."Client_Master" c USING (client_id)
                                   WHERE c.tenant_id::text = %s ORDER BY t.training_id""", (FAI_OLD_TENANT,)):
            if self.new_id('training', t['training_id']):
                continue
            new_id = self.insert('Services_Master_archive', {
                'tenant_id': FAI_NEW_TENANT, 'client_id': self.new_id('client', t['client_id']),
                'event_number': t.get('event_number'), 'trainer_name': t.get('trainer_name'),
                'client_address': t.get('client_address'), 'city': t.get('city'), 'state': t.get('state'),
                'pin_code': t.get('pin_code'), 'remarks': t.get('remarks'), 'participants': t.get('participants'),
                'stage': t.get('stage'), 'date_from': t.get('training_from'), 'date_to': t.get('training_to'),
                'service_rate': t.get('training_fees'), 'created_at': t.get('created_at'),
                'updated_at': t.get('updated_at'),
            }, 'service_id')
            self.remember('training', t['training_id'], new_id)
            self.bump('training batches')

    def quotations(self):
        for q in self.old_rows(f'SELECT * FROM {OLD}."Quotations" WHERE tenant_id::text = %s ORDER BY quotation_id',
                               (FAI_OLD_TENANT,)):
            if self.new_id('quotation', q['quotation_id']):
                continue
            new_q = self.insert('Quotation_Master', {
                'tenant_id': FAI_NEW_TENANT, 'client_id': self.new_id('client', q['client_id']),
                'reference_number': q.get('reference_number') or q.get('quote_reference') or f"OLD-{q['quotation_id']}",
                'notes': q.get('notes'), 'valid_until': q.get('valid_until'),
                'created_by_employee_id': self.new_id('employee', q.get('employee_id')) or self.any_fai_employee(),
                'created_at': q.get('created_at'), 'updated_at': q.get('updated_at'),
                'global_discount_percent': q.get('global_discount_percent'), 'sent_at': q.get('sent_at'),
                'approved_at': q.get('approved_at'),
                'approved_by_employee_id': self.new_id('employee', q.get('approver_employee_id')),
                'sub_total': q.get('sub_total'), 'currency_id': q.get('currency_id'), 'tax_id': q.get('tax_id'),
                'supplier_cost_total': q.get('supplier_cost_total'), 'margin_percentage': q.get('margin_percentage'),
                'margin_amount': q.get('margin_amount'), 'approval_notes': q.get('approval_notes'),
                'submitted_for_approval_at': q.get('submitted_for_approval_at'),
                'customer_name': q.get('customer_name'), 'customer_address': q.get('customer_address'),
                'customer_phone': q.get('customer_phone'), 'customer_email': q.get('customer_email'),
                'status': q.get('status') if q.get('status') in QUOTE_STATUS else 'Draft',
                'doc_type': 'quotation',
                'metadata': {'legacy_streemlyne_mt': {'old_quotation_id': q['quotation_id'],
                                                      'total': jsonable(q.get('total')),
                                                      'vat_amount': jsonable(q.get('vat_amount')),
                                                      'additional_terms': q.get('additional_terms')}},
            }, 'quotation_id')
            self.remember('quotation', q['quotation_id'], new_q)
            self.bump('quotations')
            for it in self.old_rows(f'SELECT * FROM {OLD}."Quotation_Items" WHERE quotation_id = %s ORDER BY item_id',
                                    (q['quotation_id'],)):
                new_it = self.insert('Quotation_Details', {
                    'quotation_id': new_q, 'tenant_id': FAI_NEW_TENANT, 'item_name': it.get('item_name'),
                    'description': it.get('description'),
                    'quantity': int(it['quantity']) if it.get('quantity') is not None else 1,
                    'amount': it.get('amount'), 'discount_type': it.get('discount_type'),
                    'discounted_amount': it.get('discounted_amount'), 'discount_percent': it.get('discount_percent'),
                    'section': it.get('section'), 'unit_cost_snapshot': it.get('unit_cost_snapshot'),
                    'unit_price_snapshot': it.get('unit_price_snapshot'), 'created_at': it.get('created_at'),
                }, 'item_id')
                self.remember('quotation_item', it['item_id'], new_it)
                self.bump('quotation lines')

    def any_fai_user(self):
        with self.dst.cursor() as c:
            c.execute(f'SELECT min(user_id) FROM {NEW}."User_Master" WHERE tenant_id = %s', (FAI_NEW_TENANT,))
            return c.fetchone()[0]

    def any_fai_employee(self):
        with self.dst.cursor() as c:
            c.execute(f'SELECT min(employee_id) FROM {NEW}."Employee_Master" WHERE tenant_id = %s', (FAI_NEW_TENANT,))
            return c.fetchone()[0]

    def notifications(self):
        for n in self.old_rows(f'SELECT * FROM {OLD}."Notification_Master" WHERE tenant_id::text = %s',
                               (FAI_OLD_TENANT,)):
            if self.new_id('notification', n['notification_id']):
                continue
            row = dict(n)
            row.update({'tenant_id': FAI_NEW_TENANT, 'client_id': self.new_id('client', n.get('client_id')),
                        'employee_id': self.new_id('employee', n.get('employee_id')),
                        'created_by_employee_id': self.new_id('employee', n.get('created_by_employee_id')),
                        'contract_id': None, 'property_id': None, 'proposal_id': None})
            self.remember('notification', n['notification_id'], self.insert('Notification_Master', row, 'notification_id'))
            self.bump('notifications')

    def run(self):
        self.setup()
        self.employees_and_users()
        self.customers()
        self.interactions_and_files()
        self.opportunities_to_leads()
        self.training_batches()
        self.quotations()
        self.notifications()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', required=True)
    ap.add_argument('--target', required=True)
    ap.add_argument('--dry-run', action='store_true', help='run everything, then roll back')
    a = ap.parse_args()

    src = psycopg2.connect(a.source)
    src.set_session(readonly=True)
    dst = psycopg2.connect(a.target)
    m = Migrator(src, dst, print)
    try:
        m.run()
        for k, v in m.counts.items():
            print(f'  {k}: {v}')
        if a.dry_run:
            dst.rollback()
            print('DRY RUN - rolled back, nothing saved')
        else:
            dst.commit()
            print('COMMITTED')
    except Exception:
        dst.rollback()
        print('FAILED - rolled back, nothing saved', file=sys.stderr)
        raise
    finally:
        src.close()
        dst.close()


if __name__ == '__main__':
    main()
