import json
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from sqlalchemy import text
from .auth_helpers import token_required
from ..db import SessionLocal

db_bp = Blueprint('database', __name__)

# ─────────────────────────────────────────────
# Pipeline stage constants (matched to Stage_Master stage_type)
# ─────────────────────────────────────────────
STAGE_TYPE_SALES    = 1
STAGE_TYPE_TRAINING = 2

SALES_PIPELINE_STAGES    = ["Enquiry", "Proposal", "Converted"]
TRAINING_PIPELINE_STAGES = [
    "Training Scheduled",
    "PO Received",
    "Training Conducted",
    "Training Completed",
    "PTI Created",
    "Certificates Created",
    "Certificates Dispatched",
]

CONTACT_METHOD_INTERACTION = 1
CONTACT_METHOD_AUDIT       = 50
CONTACT_METHOD_ACTION_ITEM = 99
CONTACT_METHOD_DATA_IMPORT = 100


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def get_current_user_email(data=None):
    if hasattr(request, 'current_user') and hasattr(request.current_user, 'email'):
        return request.current_user.email
    return data.get('created_by', 'System') if isinstance(data, dict) else 'System'


def is_admin(session, user_id):
    try:
        row = session.execute(
            text("""
                SELECT em.role_ids
                FROM "streemLyne_mt_dev2"."User_Master" um
                JOIN "streemLyne_mt_dev2"."Employee_Master" em ON em.employee_id = um.employee_id
                WHERE um.user_id = :uid
            """),
            {"uid": user_id}
        ).fetchone()
        if not row or not row.role_ids:
            return False
        role_ids = [r.strip() for r in str(row.role_ids).split(',') if r.strip().isdigit()]
        if not role_ids:
            return False
        placeholders = ', '.join([f':r{i}' for i in range(len(role_ids))])
        params = {f'r{i}': int(rid) for i, rid in enumerate(role_ids)}
        admin_row = session.execute(
            text(f"""
                SELECT role_id FROM "streemLyne_mt_dev2"."Role_Master"
                WHERE role_id IN ({placeholders})
                AND LOWER(role_name) = 'admin'
            """),
            params
        ).fetchone()
        return admin_row is not None
    except Exception as e:
        current_app.logger.error(f"is_admin check error: {e}")
        return False


def parse_date(value, field_name='date'):
    if not value:
        return None, None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date(), None
    except Exception:
        return None, (jsonify({'error': f'Invalid {field_name} format. Use YYYY-MM-DD'}), 400)


def pack_meta(extra: dict, base_notes: str = '') -> str:
    """Pack extra fields as a JSON prefix in a notes string."""
    if not extra:
        return base_notes
    return f"__meta__{json.dumps(extra)}__end_meta__{base_notes}"


def unpack_meta(notes: str) -> tuple:
    """Extract (meta_dict, base_notes) from a packed notes string."""
    if not notes or '__meta__' not in notes:
        return {}, notes or ''
    try:
        meta_str  = notes.split('__meta__')[1].split('__end_meta__')[0]
        base      = notes.split('__end_meta__')[1] if '__end_meta__' in notes else ''
        return json.loads(meta_str), base
    except Exception:
        return {}, notes


def get_latest_opportunity(session, client_id):
    return session.execute(
        text("""
            SELECT od.opportunity_id, od.client_id, od.stage_id,
                   od.opportunity_title, od.opportunity_description,
                   od.opportunity_owner_employee_id, od.opportunity_value,
                   od.currency_id, od."Misc_Col1" AS misc_col1,
                   od.created_at,
                   sm.stage_name, sm.stage_type
            FROM "streemLyne_mt_dev2"."Opportunity_Details" od
            LEFT JOIN "streemLyne_mt_dev2"."Pipeline_Stage_Master" sm ON sm.stage_id = od.stage_id
            WHERE od.client_id = :cid
            ORDER BY od.created_at DESC
            LIMIT 1
        """),
        {"cid": client_id}
    ).fetchone()


class _ClientRow:
    """Client_Master row in dev2: fields that are not columns there (contact
    name, city, department contacts, ...) are read from its metadata JSON,
    either at the top level or under 'legacy_streemlyne_mt' (migrated rows)."""

    def __init__(self, row):
        self._row = row
        meta = getattr(row, 'metadata', None) or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except ValueError:
                meta = {}
        legacy = meta.get('legacy_streemlyne_mt') if isinstance(meta.get('legacy_streemlyne_mt'), dict) else {}
        self._extra = {**legacy, **{k: v for k, v in meta.items() if k != 'legacy_streemlyne_mt'}}
        if 'contact_name' in self._extra and not self._extra.get('client_contact_name'):
            self._extra['client_contact_name'] = self._extra['contact_name']

    def __getattr__(self, name):
        try:
            return getattr(self._row, name)
        except AttributeError:
            return self._extra.get(name)


def serialize_client(row, opp=None):
    row = _ClientRow(row)
    client = {
        "id":                   row.client_id,
        "client_id":            row.client_id,
        "name":                 row.client_company_name,
        "client_company_name":  row.client_company_name,
        "client_contact_name":  row.client_contact_name,
        "address":              row.address or '',
        "country_id":           row.country_id,
        "post_code":            row.post_code or '',
        "phone":                row.client_phone or '',
        "client_phone":         row.client_phone or '',
        "email":                row.client_email or '',
        "client_email":         row.client_email or '',
        "client_website":       row.client_website or '',
        "default_currency_id":  row.default_currency_id,
        "tenant_id":            row.tenant_id,
        "created_at":           row.created_at.isoformat() if row.created_at else None,
    }
    if opp:
        misc = {}
        if opp.misc_col1:
            try:
                misc = json.loads(opp.misc_col1)
            except Exception:
                pass
        client.update({
            "opportunity_id":    opp.opportunity_id,
            "stage_id":          opp.stage_id,
            "stage_name":        opp.stage_name,
            "stage_type":        opp.stage_type,
            "pipeline_type":     "training" if opp.stage_type == STAGE_TYPE_TRAINING else "sales",
            "sales_stage":       opp.stage_name if opp.stage_type == STAGE_TYPE_SALES else misc.get('sales_stage'),
            "training_stage":    opp.stage_name if opp.stage_type == STAGE_TYPE_TRAINING else misc.get('training_stage'),
            "salesperson":       misc.get('salesperson', ''),
            "status":            misc.get('status', 'Active'),
            "marketing_opt_in":  misc.get('marketing_opt_in', False),
            "contact_made":      misc.get('contact_made', 'Unknown'),
            "preferred_contact_method": misc.get('preferred_contact_method', 'Phone'),
            "notes":             misc.get('notes', ''),
            "project_types":     misc.get('project_types', []),
        })
    else:
        client.update({
            "opportunity_id": None, "stage_id": None, "stage_name": None,
            "pipeline_type": "sales", "sales_stage": None, "training_stage": None,
            "salesperson": '', "status": 'Active', "marketing_opt_in": False,
            "contact_made": 'Unknown', "preferred_contact_method": 'Phone',
            "notes": '', "project_types": [],
        })
    return client


def _extract_stage_from_payload(data: dict, pipeline_type: str = 'sales'):
    if not isinstance(data, dict):
        return None
    valid = SALES_PIPELINE_STAGES if pipeline_type == 'sales' else TRAINING_PIPELINE_STAGES
    for key in ('stage', 'sales_stage', 'training_stage', 'target_stage', 'new_stage'):
        val = data.get(key)
        if isinstance(val, str) and val.strip() in valid:
            return val.strip()
        if isinstance(val, dict):
            for inner_key in ('value', 'label', 'stage'):
                inner = val.get(inner_key)
                if isinstance(inner, str) and inner.strip() in valid:
                    return inner.strip()
    return None


# ═════════════════════════════════════════════════════════════════════════════
# USERS
# Maps to User_Master + Employee_Master
# ═════════════════════════════════════════════════════════════════════════════

@db_bp.route('/users', methods=['GET', 'POST'])
@token_required
def handle_users():
    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json

            # Insert Employee_Master first, then User_Master
            emp_result = session.execute(
                text("""
                    INSERT INTO "streemLyne_mt_dev2"."Employee_Master"
                        (tenant_id, employee_name, phone, email, role_ids, created_on)
                    VALUES
                        (:tenant_id, :name, :phone, :email, :role_ids, :created_on)
                    RETURNING employee_id
                """),
                {
                    "tenant_id":  request.current_user.tenant_id,
                    "name":       f"{data.get('first_name', '')} {data.get('last_name', '')}".strip(),
                    "phone":      data.get('phone', ''),
                    "email":      data.get('email', ''),
                    "role_ids":   str(data.get('role_id', '')),
                    "created_on": datetime.utcnow()
                }
            )
            new_emp_id = emp_result.fetchone().employee_id

            # Hash password if provided (simple — replace with bcrypt in production)
            password = data.get('password', '')

            user_result = session.execute(
                text("""
                    INSERT INTO "streemLyne_mt_dev2"."User_Master"
                        (employee_id, user_name, password, created_at)
                    VALUES
                        (:emp_id, :username, :password, :created_at)
                    RETURNING user_id
                """),
                {
                    "emp_id":     new_emp_id,
                    "username":   data.get('email', ''),
                    "password":   password,
                    "created_at": datetime.utcnow()
                }
            )
            new_user_id = user_result.fetchone().user_id
            session.commit()

            current_app.logger.info(f"✅ User created: user_id={new_user_id}, employee_id={new_emp_id}")
            return jsonify({'id': new_user_id, 'employee_id': new_emp_id,
                            'message': 'User created successfully'}), 201

        # GET — join User_Master + Employee_Master
        rows = session.execute(
            text("""
                SELECT um.user_id, um.username AS user_name, um.created_at AS user_created_at,
                       em.employee_id, em.employee_name, em.email, em.phone,
                       em.role_ids, em.tenant_id, em.date_of_joining,
                       em.commission_percentage
                FROM "streemLyne_mt_dev2"."User_Master" um
                JOIN "streemLyne_mt_dev2"."Employee_Master" em ON em.employee_id = um.employee_id
                ORDER BY em.employee_name ASC
            """)
        ).fetchall()

        result = []
        for row in rows:
            role_names = _get_role_names(session, row.role_ids)
            result.append({
                "id":           row.user_id,
                "user_id":      row.user_id,
                "employee_id":  row.employee_id,
                "user_name":    row.user_name,
                "email":        row.email,
                "full_name":    row.employee_name,
                "phone":        row.phone or '',
                "role_ids":     row.role_ids,
                "roles":        role_names,
                "role":         role_names[0] if role_names else 'Staff',
                "tenant_id":    row.tenant_id,
                "created_at":   row.user_created_at.isoformat() if row.user_created_at else None,
            })

        return jsonify(result), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling users: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


def _get_role_names(session, role_ids_str):
    if not role_ids_str:
        return []
    ids = [r.strip() for r in str(role_ids_str).split(',') if r.strip().isdigit()]
    if not ids:
        return []
    placeholders = ', '.join([f':r{i}' for i in range(len(ids))])
    params = {f'r{i}': int(rid) for i, rid in enumerate(ids)}
    rows = session.execute(
        text(f'SELECT role_name FROM "streemLyne_mt_dev2"."Role_Master" WHERE role_id IN ({placeholders})'),
        params
    ).fetchall()
    return [r.role_name for r in rows]


@db_bp.route('/users/<int:user_id>', methods=['GET', 'PUT', 'DELETE'])
@token_required
def handle_single_user(user_id):
    session = SessionLocal()
    try:
        row = session.execute(
            text("""
                SELECT um.user_id, um.username AS user_name, um.created_at AS user_created_at,
                       em.employee_id, em.employee_name, em.email, em.phone,
                       em.role_ids, em.tenant_id
                FROM "streemLyne_mt_dev2"."User_Master" um
                JOIN "streemLyne_mt_dev2"."Employee_Master" em ON em.employee_id = um.employee_id
                WHERE um.user_id = :uid
            """),
            {"uid": user_id}
        ).fetchone()

        if not row:
            return jsonify({'error': 'User not found'}), 404

        if request.method == 'GET':
            role_names = _get_role_names(session, row.role_ids)
            return jsonify({
                "id":          row.user_id,
                "user_id":     row.user_id,
                "employee_id": row.employee_id,
                "user_name":   row.user_name,
                "email":       row.email,
                "full_name":   row.employee_name,
                "phone":       row.phone or '',
                "roles":       role_names,
                "role":        role_names[0] if role_names else 'Staff',
                "tenant_id":   row.tenant_id,
                "created_at":  row.user_created_at.isoformat() if row.user_created_at else None,
            }), 200

        elif request.method == 'PUT':
            data = request.json

            # Update Employee_Master
            emp_updates = {}
            name = f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()
            if name:
                emp_updates['employee_name'] = name
            if 'email' in data:
                emp_updates['email'] = data['email']
            if 'phone' in data:
                emp_updates['phone'] = data['phone']
            if 'role_id' in data:
                emp_updates['role_ids'] = str(data['role_id'])
            emp_updates['updated_on'] = datetime.utcnow()

            if emp_updates:
                set_clause = ', '.join([f'"{k}" = :{k}' for k in emp_updates])
                emp_updates['eid'] = row.employee_id
                session.execute(
                    text(f'UPDATE "streemLyne_mt_dev2"."Employee_Master" SET {set_clause} WHERE employee_id = :eid'),
                    emp_updates
                )

            # Update User_Master password if provided
            if data.get('password'):
                session.execute(
                    text('UPDATE "streemLyne_mt_dev2"."User_Master" SET password = :pw WHERE user_id = :uid'),
                    {"pw": data['password'], "uid": user_id}
                )
            # Update username if email changed
            if 'email' in data:
                session.execute(
                    text('UPDATE "streemLyne_mt_dev2"."User_Master" SET user_name = :un WHERE user_id = :uid'),
                    {"un": data['email'], "uid": user_id}
                )

            session.commit()
            return jsonify({'message': 'User updated successfully'}), 200

        elif request.method == 'DELETE':
            emp_id = row.employee_id
            # Delete User_Master first (FK dependency)
            session.execute(
                text('DELETE FROM "streemLyne_mt_dev2"."User_Master" WHERE user_id = :uid'),
                {"uid": user_id}
            )
            session.execute(
                text('DELETE FROM "streemLyne_mt_dev2"."Employee_Master" WHERE employee_id = :eid'),
                {"eid": emp_id}
            )
            session.commit()
            return jsonify({'message': 'User deleted successfully'}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling user {user_id}: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# CUSTOMERS
# Maps to Client_Master + Opportunity_Details
# ═════════════════════════════════════════════════════════════════════════════

@db_bp.route('/clients', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_customers():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json

            company_name = data.get('name') or data.get('client_company_name', '')
            phone        = data.get('phone') or data.get('client_phone', '')
            email        = data.get('client_email') or data.get('email', '')
            address      = data.get('address', '')
            contact_name = data.get('client_contact_name', '')
            country_id   = data.get('country_id')
            currency_id  = data.get('default_currency_id')
            tenant_id    = request.current_user.tenant_id

            result = session.execute(
                text("""
                    INSERT INTO "streemLyne_mt_dev2"."Client_Master"
                        (tenant_id, client_company_name, client_contact_name, address,
                         country_id, post_code, client_phone, client_email,
                         client_website, default_currency_id, created_at)
                    VALUES
                        (:tenant_id, :name, :contact_name, :address,
                         :country_id, :post_code, :phone, :email,
                         :website, :currency_id, :created_at)
                    RETURNING client_id
                """),
                {
                    "tenant_id":    tenant_id,
                    "name":         company_name,
                    "contact_name": contact_name,
                    "address":      address,
                    "country_id":   country_id,
                    "post_code":    data.get('post_code', ''),
                    "phone":        phone,
                    "email":        email,
                    "website":      data.get('client_website', ''),
                    "currency_id":  currency_id,
                    "created_at":   datetime.utcnow()
                }
            )
            new_client_id = result.fetchone().client_id

            # Resolve default sales stage
            stage_row = session.execute(
                text("""
                    SELECT stage_id, stage_name FROM "streemLyne_mt_dev2"."Pipeline_Stage_Master"
                    WHERE stage_type = :stype ORDER BY stage_id ASC LIMIT 1
                """),
                {"stype": STAGE_TYPE_SALES}
            ).fetchone()
            default_stage_id   = stage_row.stage_id   if stage_row else None
            default_stage_name = stage_row.stage_name if stage_row else 'Enquiry'

            misc = {
                "salesperson":              data.get('salesperson', ''),
                "status":                   data.get('status', 'Active'),
                "marketing_opt_in":         data.get('marketing_opt_in', False),
                "contact_made":             data.get('contact_made', 'Unknown'),
                "preferred_contact_method": data.get('preferred_contact_method', 'Phone'),
                "notes":                    data.get('notes', ''),
                "project_types":            data.get('project_types', []),
                "pipeline_type":            data.get('pipeline_type', 'sales'),
                "created_by":               get_current_user_email(data),
            }

            session.execute(
                text("""
                    INSERT INTO "streemLyne_mt_dev2"."Opportunity_Details"
                        (client_id, opportunity_title, opportunity_description,
                         opportunity_date, opportunity_owner_employee_id,
                         stage_id, opportunity_value, currency_id,
                         created_at, misc_col1)
                    VALUES
                        (:client_id, :title, :desc,
                         :opp_date, :owner_emp_id,
                         :stage_id, :opp_value, :currency_id,
                         :created_at, :misc)
                """),
                {
                    "client_id":    new_client_id,
                    "title":        f"{company_name} - {default_stage_name}",
                    "desc":         data.get('notes', ''),
                    "opp_date":     datetime.utcnow().date(),
                    "owner_emp_id": getattr(request.current_user, 'employee_id', None),
                    "stage_id":     default_stage_id,
                    "opp_value":    data.get('opportunity_value', 0),
                    "currency_id":  currency_id,
                    "created_at":   datetime.utcnow(),
                    "misc":         json.dumps(misc)
                }
            )
            session.commit()

            new_client = session.execute(
                text('SELECT * FROM "streemLyne_mt_dev2"."Client_Master" WHERE client_id = :cid'),
                {"cid": new_client_id}
            ).fetchone()
            opp = get_latest_opportunity(session, new_client_id)

            current_app.logger.info(f"✅ Client {new_client_id} created")
            return jsonify({
                'id': new_client_id,
                'message': 'Customer created successfully',
                'customer': serialize_client(new_client, opp)
            }), 201

        # GET
        rows = session.execute(
            text("""
                SELECT * FROM "streemLyne_mt_dev2"."Client_Master"
                WHERE tenant_id = :tid
                ORDER BY created_at DESC
            """),
            {"tid": request.current_user.tenant_id}
        ).fetchall()

        result = []
        for row in rows:
            opp = get_latest_opportunity(session, row.client_id)
            result.append(serialize_client(row, opp))

        return jsonify(result), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling customers: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@db_bp.route('/clients/<int:client_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@token_required
def handle_single_customer(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        client_row = session.execute(
            text('SELECT * FROM "streemLyne_mt_dev2"."Client_Master" WHERE client_id = :cid'),
            {"cid": client_id}
        ).fetchone()

        if not client_row:
            return jsonify({'error': 'Customer not found'}), 404

        opp = get_latest_opportunity(session, client_id)

        if request.method == 'GET':
            return jsonify(serialize_client(client_row, opp)), 200

        elif request.method == 'PUT':
            data = request.json

            # Client_Master updatable fields
            field_map = {
                'name':                'client_company_name',
                'client_company_name': 'client_company_name',
                'client_contact_name': 'client_contact_name',
                'address':             'address',
                'country_id':          'country_id',
                'post_code':           'post_code',
                'phone':               'client_phone',
                'client_phone':        'client_phone',
                'email':               'client_email',
                'client_email':        'client_email',
                'client_website':      'client_website',
                'default_currency_id': 'default_currency_id',
            }
            client_updates = {col: data[inc] for inc, col in field_map.items() if inc in data}

            if client_updates:
                set_clause = ', '.join([f'"{k}" = :{k}' for k in client_updates])
                client_updates['cid'] = client_id
                session.execute(
                    text(f'UPDATE "streemLyne_mt_dev2"."Client_Master" SET {set_clause} WHERE client_id = :cid'),
                    client_updates
                )

            # Misc fields into Opportunity_Details.Misc_Col1
            misc_fields = [
                'salesperson', 'status', 'marketing_opt_in', 'contact_made',
                'preferred_contact_method', 'notes', 'project_types',
                'sales_stage', 'training_stage', 'pipeline_type'
            ]
            extra = {f: data[f] for f in misc_fields if f in data}

            if extra and opp:
                existing_misc = {}
                if opp.misc_col1:
                    try:
                        existing_misc = json.loads(opp.misc_col1)
                    except Exception:
                        pass
                existing_misc.update(extra)
                existing_misc['updated_by'] = get_current_user_email(data)

                session.execute(
                    text("""
                        UPDATE "streemLyne_mt_dev2"."Opportunity_Details"
                        SET misc_col1 = :misc
                        WHERE opportunity_id = :oid
                    """),
                    {"misc": json.dumps(existing_misc), "oid": opp.opportunity_id}
                )

            session.commit()

            updated_client = session.execute(
                text('SELECT * FROM "streemLyne_mt_dev2"."Client_Master" WHERE client_id = :cid'),
                {"cid": client_id}
            ).fetchone()
            updated_opp = get_latest_opportunity(session, client_id)

            current_app.logger.info(f"✅ Client {client_id} updated")
            return jsonify({
                'message': 'Customer updated successfully',
                'customer': serialize_client(updated_client, updated_opp)
            }), 200

        elif request.method == 'DELETE':
            # Clean up linked records first
            session.execute(
                text('DELETE FROM "streemLyne_mt_dev2"."Opportunity_Details" WHERE client_id = :cid'),
                {"cid": client_id}
            )
            session.execute(
                text('DELETE FROM "streemLyne_mt_dev2"."Client_Master" WHERE client_id = :cid'),
                {"cid": client_id}
            )
            session.commit()
            return jsonify({'message': 'Customer deleted successfully'}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling customer {client_id}: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@db_bp.route('/clients/<int:client_id>/stage', methods=['PATCH', 'OPTIONS'])
@token_required
def update_customer_stage(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        client_row = session.execute(
            text('SELECT client_id FROM "streemLyne_mt_dev2"."Client_Master" WHERE client_id = :cid'),
            {"cid": client_id}
        ).fetchone()
        if not client_row:
            return jsonify({'error': 'Customer not found'}), 404

        data          = request.json
        opp           = get_latest_opportunity(session, client_id)
        pipeline_type = data.get('pipeline_type', 'sales')
        new_stage     = _extract_stage_from_payload(data, pipeline_type)
        reason        = data.get('reason', 'Stage updated')

        if not new_stage:
            return jsonify({'error': 'Stage is required'}), 400

        valid = SALES_PIPELINE_STAGES if pipeline_type == 'sales' else TRAINING_PIPELINE_STAGES
        if new_stage not in valid:
            return jsonify({'error': f'Invalid stage for {pipeline_type} pipeline: {new_stage}'}), 400

        existing_misc = {}
        if opp and opp.misc_col1:
            try:
                existing_misc = json.loads(opp.misc_col1)
            except Exception:
                pass

        old_stage = (opp.stage_name if opp else None)

        if old_stage == new_stage:
            return jsonify({
                'message': 'Stage not changed', 'stage_updated': False,
                'client_id': client_id, 'new_stage': new_stage,
                'old_stage': old_stage, 'pipeline_type': pipeline_type
            }), 200

        # Resolve new stage_id
        target_stage_type = STAGE_TYPE_TRAINING if pipeline_type == 'training' else STAGE_TYPE_SALES
        stage_row = session.execute(
            text("""
                SELECT stage_id FROM "streemLyne_mt_dev2"."Pipeline_Stage_Master"
                WHERE LOWER(stage_name) = LOWER(:sname)
                AND stage_type = :stype LIMIT 1
            """),
            {"sname": new_stage, "stype": target_stage_type}
        ).fetchone()
        new_stage_id = stage_row.stage_id if stage_row else None

        # Append note
        note_entry = (
            f"\n[{datetime.utcnow().isoformat()}] "
            f"{pipeline_type.title()} stage changed from {old_stage} to {new_stage}. "
            f"Reason: {reason}"
        )
        existing_misc['notes']        = (existing_misc.get('notes', '') or '') + note_entry
        existing_misc['pipeline_type'] = pipeline_type
        existing_misc['updated_by']    = get_current_user_email(data)

        if pipeline_type == 'sales':
            existing_misc['sales_stage'] = new_stage
            # Auto-create training opportunity on Converted
            if new_stage == 'Converted' and not existing_misc.get('training_stage'):
                training_stage_row = session.execute(
                    text("""
                        SELECT stage_id, stage_name FROM "streemLyne_mt_dev2"."Pipeline_Stage_Master"
                        WHERE stage_type = :stype ORDER BY stage_id ASC LIMIT 1
                    """),
                    {"stype": STAGE_TYPE_TRAINING}
                ).fetchone()
                if training_stage_row:
                    training_misc = {
                        **existing_misc,
                        "pipeline_type":  "training",
                        "training_stage": training_stage_row.stage_name,
                    }
                    session.execute(
                        text("""
                            INSERT INTO "streemLyne_mt_dev2"."Opportunity_Details"
                                (client_id, opportunity_title, opportunity_date,
                                 opportunity_owner_employee_id, stage_id,
                                 opportunity_value, currency_id, created_at, misc_col1)
                            VALUES
                                (:client_id, :title, :opp_date,
                                 :owner_emp_id, :stage_id,
                                 :opp_value, :currency_id, :created_at, :misc)
                        """),
                        {
                            "client_id":    client_id,
                            "title":        f"Training - {client_id}",
                            "opp_date":     datetime.utcnow().date(),
                            "owner_emp_id": getattr(request.current_user, 'employee_id', None),
                            "stage_id":     training_stage_row.stage_id,
                            "opp_value":    opp.opportunity_value if opp else 0,
                            "currency_id":  opp.currency_id if opp else None,
                            "created_at":   datetime.utcnow(),
                            "misc":         json.dumps(training_misc)
                        }
                    )
                    current_app.logger.info(f"🔄 Training opportunity auto-created for client {client_id}")
        else:
            existing_misc['training_stage'] = new_stage

        # Update current opportunity
        if opp and new_stage_id:
            session.execute(
                text("""
                    UPDATE "streemLyne_mt_dev2"."Opportunity_Details"
                    SET stage_id = :stage_id, misc_col1 = :misc
                    WHERE opportunity_id = :oid
                """),
                {"stage_id": new_stage_id, "misc": json.dumps(existing_misc), "oid": opp.opportunity_id}
            )
        elif opp:
            session.execute(
                text('UPDATE "streemLyne_mt_dev2"."Opportunity_Details" SET misc_col1 = :misc WHERE opportunity_id = :oid'),
                {"misc": json.dumps(existing_misc), "oid": opp.opportunity_id}
            )

        session.commit()
        current_app.logger.info(f"✅ Client {client_id} stage: {old_stage} → {new_stage}")

        return jsonify({
            'message': 'Stage updated successfully',
            'client_id': client_id, 'old_stage': old_stage,
            'new_stage': new_stage, 'pipeline_type': pipeline_type,
            'stage_updated': True
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error updating stage: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# PIPELINE
# Reads from Opportunity_Details + Stage_Master
# ═════════════════════════════════════════════════════════════════════════════

@db_bp.route('/pipeline/<string:pipeline_type>', methods=['GET', 'OPTIONS'])
@token_required
def get_pipeline_data(pipeline_type):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    if pipeline_type not in ['sales', 'training']:
        return jsonify({'error': 'Invalid pipeline type. Must be "sales" or "training"'}), 400

    session = SessionLocal()
    try:
        target_stage_type = STAGE_TYPE_TRAINING if pipeline_type == 'training' else STAGE_TYPE_SALES

        rows = session.execute(
            text("""
                SELECT cm.*, od.opportunity_id, od.stage_id, od."Misc_Col1" AS misc_col1,
                       od.opportunity_value, od.currency_id,
                       od.opportunity_owner_employee_id,
                       sm.stage_name, sm.stage_type
                FROM "streemLyne_mt_dev2"."Client_Master" cm
                JOIN "streemLyne_mt_dev2"."Opportunity_Details" od ON od.client_id = cm.client_id
                JOIN "streemLyne_mt_dev2"."Pipeline_Stage_Master" sm ON sm.stage_id = od.stage_id
                WHERE cm.tenant_id = :tid
                AND sm.stage_type = :stype
                ORDER BY cm.client_company_name ASC
            """),
            {"tid": request.current_user.tenant_id, "stype": target_stage_type}
        ).fetchall()

        pipeline_items = []
        for row in rows:
            misc = {}
            if row.misc_col1:
                try:
                    misc = json.loads(row.misc_col1)
                except Exception:
                    pass

            default_stage = 'Enquiry' if pipeline_type == 'sales' else 'Training Scheduled'
            stage = row.stage_name or default_stage

            pipeline_items.append({
                'id':            f'client-{row.client_id}',
                'type':          'customer',
                'stage':         stage,
                'pipeline_type': pipeline_type,
                'customer': {
                    "id":           row.client_id,
                    "client_id":    row.client_id,
                    "name":         row.client_company_name,
                    "phone":        row.client_phone or '',
                    "email":        row.client_email or '',
                    "address":      row.address or '',
                    "salesperson":  misc.get('salesperson', ''),
                    "status":       misc.get('status', 'Active'),
                    "notes":        misc.get('notes', ''),
                    "sales_stage":  stage if pipeline_type == 'sales' else misc.get('sales_stage'),
                    "training_stage": stage if pipeline_type == 'training' else misc.get('training_stage'),
                    "pipeline_type": pipeline_type,
                }
            })

        return jsonify(pipeline_items), 200

    except Exception as e:
        current_app.logger.error(f"Error fetching pipeline: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ASSIGNMENTS
# Maps to Client_Interactions (contact_method = CONTACT_METHOD_INTERACTION)
# ═════════════════════════════════════════════════════════════════════════════

@db_bp.route('/assignments', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_assignments():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json

            contact_date, err = parse_date(data.get('start_date') or data.get('date'), 'start_date')
            if err:
                return err
            if not contact_date:
                return jsonify({'error': 'start_date or date is required'}), 400

            reminder_date, err = parse_date(data.get('end_date'), 'end_date')
            if err:
                return err
            if not reminder_date:
                reminder_date = contact_date

            client_id   = data.get('client_id') or data.get('customer_id')
            client_name = None
            if client_id:
                row = session.execute(
                    text('SELECT client_company_name FROM "streemLyne_mt_dev2"."Client_Master" WHERE client_id = :cid'),
                    {"cid": client_id}
                ).fetchone()
                if row:
                    client_name = row.client_company_name

            start_time = end_time = None
            if data.get('start_time'):
                try:
                    start_time = datetime.strptime(data['start_time'], '%H:%M').time().isoformat()
                except ValueError:
                    pass
            if data.get('end_time'):
                try:
                    end_time = datetime.strptime(data['end_time'], '%H:%M').time().isoformat()
                except ValueError:
                    pass

            meta = {
                "type":            data.get('type', 'job'),
                "title":           data.get('title', ''),
                "team_member":     data.get('team_member', ''),
                "employee_id":     data.get('user_id') or data.get('employee_id'),
                "client_name":     client_name or data.get('customer_name', ''),
                "start_time":      start_time,
                "end_time":        end_time,
                "estimated_hours": data.get('estimated_hours'),
                "priority":        data.get('priority', 'Medium'),
                "status":          data.get('status', 'Scheduled'),
                "project_id":      data.get('job_id') or data.get('project_id'),
                "created_by":      request.current_user.id,
            }

            notes = pack_meta(meta, data.get('notes', ''))
            next_steps = data.get('next_steps', '')

            result = session.execute(
                text("""
                    INSERT INTO "streemLyne_mt_dev2"."Client_Interactions"
                        (client_id, contact_date, contact_method, notes,
                         next_steps, reminder_date, created_at)
                    VALUES
                        (:client_id, :contact_date, :contact_method, :notes,
                         :next_steps, :reminder_date, :created_at)
                    RETURNING interaction_id
                """),
                {
                    "client_id":      client_id,
                    "contact_date":   contact_date,
                    "contact_method": CONTACT_METHOD_INTERACTION,
                    "notes":          notes,
                    "next_steps":     next_steps,
                    "reminder_date":  reminder_date,
                    "created_at":     datetime.utcnow()
                }
            )
            new_id = result.fetchone().interaction_id
            session.commit()

            current_app.logger.info(f"✅ Assignment (interaction) {new_id} created")
            return jsonify({
                'id': new_id,
                'message': 'Assignment created successfully',
                'assignment': _serialize_interaction(new_id, session)
            }), 201

        # GET
        rows = session.execute(
            text("""
                SELECT ci.*, cm.client_company_name
                FROM "streemLyne_mt_dev2"."Client_Interactions" ci
                LEFT JOIN "streemLyne_mt_dev2"."Client_Master" cm ON cm.client_id = ci.client_id
                WHERE ci.contact_method = :cm
                ORDER BY ci.contact_date ASC
            """),
            {"cm": CONTACT_METHOD_INTERACTION}
        ).fetchall()

        return jsonify([_row_to_assignment(row) for row in rows]), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error in /assignments: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@db_bp.route('/assignments/<int:assignment_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@token_required
def handle_single_assignment(assignment_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        row = session.execute(
            text("""
                SELECT ci.*, cm.client_company_name
                FROM "streemLyne_mt_dev2"."Client_Interactions" ci
                LEFT JOIN "streemLyne_mt_dev2"."Client_Master" cm ON cm.client_id = ci.client_id
                WHERE ci.interaction_id = :iid
            """),
            {"iid": assignment_id}
        ).fetchone()

        if not row:
            return jsonify({'error': 'Assignment not found'}), 404

        if request.method == 'GET':
            return jsonify(_row_to_assignment(row)), 200

        elif request.method == 'PUT':
            data = request.json

            contact_date, err = parse_date(data.get('start_date') or data.get('date'), 'start_date')
            if err:
                return err
            reminder_date, err = parse_date(data.get('end_date'), 'end_date')
            if err:
                return err

            existing_meta, base_notes = unpack_meta(row.notes)

            update_meta_keys = [
                'type', 'title', 'team_member', 'priority',
                'status', 'estimated_hours', 'start_time', 'end_time'
            ]
            for k in update_meta_keys:
                if k in data:
                    existing_meta[k] = data[k]

            if 'customer_id' in data or 'client_id' in data:
                new_client_id = data.get('client_id') or data.get('customer_id')
                c = session.execute(
                    text('SELECT client_company_name FROM "streemLyne_mt_dev2"."Client_Master" WHERE client_id = :cid'),
                    {"cid": new_client_id}
                ).fetchone()
                if c:
                    existing_meta['client_name'] = c.client_company_name

            if 'notes' in data:
                base_notes = data['notes']

            updates = {
                "notes":         pack_meta(existing_meta, base_notes),
                "next_steps":    data.get('next_steps', row.next_steps or ''),
                "updated_notes": datetime.utcnow()
            }
            if contact_date:
                updates['contact_date'] = contact_date
            if reminder_date:
                updates['reminder_date'] = reminder_date
            if 'client_id' in data:
                updates['client_id'] = data['client_id']

            set_clauses = []
            params = {"iid": assignment_id}
            for k, v in updates.items():
                if k == 'updated_notes':
                    continue
                col = 'contact_date' if k == 'contact_date' \
                      else 'reminder_date' if k == 'reminder_date' \
                      else k
                set_clauses.append(f'"{col}" = :{k}')
                params[k] = v

            if set_clauses:
                session.execute(
                    text(f'UPDATE "streemLyne_mt_dev2"."Client_Interactions" SET {", ".join(set_clauses)} WHERE interaction_id = :iid'),
                    params
                )
            session.commit()

            updated = session.execute(
                text("""
                    SELECT ci.*, cm.client_company_name FROM "streemLyne_mt_dev2"."Client_Interactions" ci
                    LEFT JOIN "streemLyne_mt_dev2"."Client_Master" cm ON cm.client_id = ci.client_id
                    WHERE ci.interaction_id = :iid
                """),
                {"iid": assignment_id}
            ).fetchone()

            return jsonify({
                'message': 'Assignment updated successfully',
                'assignment': _row_to_assignment(updated)
            }), 200

        elif request.method == 'DELETE':
            session.execute(
                text('DELETE FROM "streemLyne_mt_dev2"."Client_Interactions" WHERE interaction_id = :iid'),
                {"iid": assignment_id}
            )
            session.commit()
            return jsonify({'message': 'Assignment deleted successfully', 'id': assignment_id}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling assignment {assignment_id}: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


def _serialize_interaction(interaction_id, session):
    row = session.execute(
        text("""
            SELECT ci.*, cm.client_company_name FROM "streemLyne_mt_dev2"."Client_Interactions" ci
            LEFT JOIN "streemLyne_mt_dev2"."Client_Master" cm ON cm.client_id = ci.client_id
            WHERE ci.interaction_id = :iid
        """),
        {"iid": interaction_id}
    ).fetchone()
    return _row_to_assignment(row) if row else {}


def _row_to_assignment(row):
    meta, base_notes = unpack_meta(row.notes)
    return {
        "id":              row.interaction_id,
        "interaction_id":  row.interaction_id,
        "client_id":       row.client_id,
        "client_name":     getattr(row, 'client_company_name', meta.get('client_name', '')),
        "date":            row.contact_date.isoformat() if row.contact_date else None,
        "start_date":      row.contact_date.isoformat() if row.contact_date else None,
        "end_date":        row.reminder_date.isoformat() if row.reminder_date else None,
        "notes":           base_notes,
        "next_steps":      row.next_steps or '',
        "created_at":      row.created_at.isoformat() if row.created_at else None,
        # Fields from meta
        "type":            meta.get('type', 'job'),
        "title":           meta.get('title', ''),
        "team_member":     meta.get('team_member', ''),
        "employee_id":     meta.get('employee_id'),
        "start_time":      meta.get('start_time'),
        "end_time":        meta.get('end_time'),
        "estimated_hours": meta.get('estimated_hours'),
        "priority":        meta.get('priority', 'Medium'),
        "status":          meta.get('status', 'Scheduled'),
        "project_id":      meta.get('project_id'),
    }


# ═════════════════════════════════════════════════════════════════════════════
# AUDIT LOGS
# Stored in Client_Interactions with contact_method = CONTACT_METHOD_AUDIT (50)
# ═════════════════════════════════════════════════════════════════════════════

@db_bp.route('/audit-logs', methods=['GET', 'OPTIONS'])
@token_required
def get_audit_logs():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        entity_type = request.args.get('entity_type')
        entity_id   = request.args.get('entity_id')
        action      = request.args.get('action')

        base_query = """
            SELECT ci.interaction_id, ci.client_id, ci.contact_date,
                   ci.notes, ci.created_at
            FROM "streemLyne_mt_dev2"."Client_Interactions" ci
            WHERE ci.contact_method = :cm
        """
        params = {"cm": CONTACT_METHOD_AUDIT}

        rows = session.execute(text(base_query), params).fetchall()

        # Filter in Python using meta (avoids complex JSON SQL)
        logs = []
        for row in rows:
            meta, _ = unpack_meta(row.notes)
            if entity_type and meta.get('entity_type') != entity_type:
                continue
            if entity_id and str(meta.get('entity_id')) != str(entity_id):
                continue
            if action and meta.get('action') != action:
                continue
            logs.append({
                "id":          row.interaction_id,
                "entity_type": meta.get('entity_type'),
                "entity_id":   meta.get('entity_id'),
                "action":      meta.get('action'),
                "changed_by":  meta.get('changed_by'),
                "old_value":   meta.get('old_value'),
                "new_value":   meta.get('new_value'),
                "changed_at":  row.created_at.isoformat() if row.created_at else None,
            })

        # Sort and limit
        logs.sort(key=lambda x: x['changed_at'] or '', reverse=True)
        return jsonify(logs[:100]), 200

    except Exception as e:
        current_app.logger.error(f"Error fetching audit logs: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ACTION ITEMS
# Stored in Client_Interactions with contact_method = CONTACT_METHOD_ACTION_ITEM (99)
# ═════════════════════════════════════════════════════════════════════════════

@db_bp.route('/action-items', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_action_items():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        if request.method == 'POST':
            data    = request.json
            meta    = {
                "stage":     data.get('stage'),
                "priority":  data.get('priority', 'High'),
                "completed": data.get('completed', False),
                "completed_at": None,
                "item_type": "action_item"
            }
            result = session.execute(
                text("""
                    INSERT INTO "streemLyne_mt_dev2"."Client_Interactions"
                        (client_id, contact_date, contact_method, notes, created_at)
                    VALUES
                        (:client_id, :contact_date, :contact_method, :notes, :created_at)
                    RETURNING interaction_id
                """),
                {
                    "client_id":      data.get('customer_id') or data.get('client_id'),
                    "contact_date":   datetime.utcnow().date(),
                    "contact_method": CONTACT_METHOD_ACTION_ITEM,
                    "notes":          pack_meta(meta),
                    "created_at":     datetime.utcnow()
                }
            )
            new_id = result.fetchone().interaction_id
            session.commit()

            return jsonify({
                'id': new_id,
                'message': 'Action item created successfully',
                'action_item': _row_to_action_item(new_id, session)
            }), 201

        # GET with optional filters
        client_id = request.args.get('customer_id') or request.args.get('client_id')
        completed = request.args.get('completed')

        query  = """
            SELECT * FROM "streemLyne_mt_dev2"."Client_Interactions"
            WHERE contact_method = :cm
        """
        params = {"cm": CONTACT_METHOD_ACTION_ITEM}

        if client_id:
            query += " AND client_id = :cid"
            params["cid"] = client_id

        query += " ORDER BY created_at DESC"
        rows = session.execute(text(query), params).fetchall()

        result = []
        for row in rows:
            meta, _ = unpack_meta(row.notes)
            if completed is not None:
                row_completed = meta.get('completed', False)
                if str(completed).lower() == 'true' and not row_completed:
                    continue
                if str(completed).lower() == 'false' and row_completed:
                    continue
            result.append({
                "id":           row.interaction_id,
                "client_id":    row.client_id,
                "stage":        meta.get('stage'),
                "priority":     meta.get('priority', 'High'),
                "completed":    meta.get('completed', False),
                "completed_at": meta.get('completed_at'),
                "created_at":   row.created_at.isoformat() if row.created_at else None,
            })

        return jsonify(result), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling action items: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@db_bp.route('/action-items/<int:item_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@token_required
def handle_single_action_item(item_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        row = session.execute(
            text('SELECT * FROM "streemLyne_mt_dev2"."Client_Interactions" WHERE interaction_id = :iid AND contact_method = :cm'),
            {"iid": item_id, "cm": CONTACT_METHOD_ACTION_ITEM}
        ).fetchone()

        if not row:
            return jsonify({'error': 'Action item not found'}), 404

        meta, base_notes = unpack_meta(row.notes)

        if request.method == 'GET':
            return jsonify({
                "id":           row.interaction_id,
                "client_id":    row.client_id,
                "stage":        meta.get('stage'),
                "priority":     meta.get('priority', 'High'),
                "completed":    meta.get('completed', False),
                "completed_at": meta.get('completed_at'),
                "created_at":   row.created_at.isoformat() if row.created_at else None,
            }), 200

        elif request.method == 'PUT':
            data = request.json

            if 'stage' in data:
                meta['stage'] = data['stage']
            if 'priority' in data:
                meta['priority'] = data['priority']
            if 'completed' in data:
                was_completed = meta.get('completed', False)
                meta['completed'] = data['completed']
                if data['completed'] and not was_completed:
                    meta['completed_at'] = datetime.utcnow().isoformat()
                elif not data['completed']:
                    meta['completed_at'] = None

            session.execute(
                text('UPDATE "streemLyne_mt_dev2"."Client_Interactions" SET notes = :notes WHERE interaction_id = :iid'),
                {"notes": pack_meta(meta, base_notes), "iid": item_id}
            )
            session.commit()
            return jsonify({'message': 'Action item updated successfully'}), 200

        elif request.method == 'DELETE':
            session.execute(
                text('DELETE FROM "streemLyne_mt_dev2"."Client_Interactions" WHERE interaction_id = :iid'),
                {"iid": item_id}
            )
            session.commit()
            return jsonify({'message': 'Action item deleted successfully'}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling action item {item_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


def _row_to_action_item(item_id, session):
    row = session.execute(
        text('SELECT * FROM "streemLyne_mt_dev2"."Client_Interactions" WHERE interaction_id = :iid'),
        {"iid": item_id}
    ).fetchone()
    if not row:
        return {}
    meta, _ = unpack_meta(row.notes)
    return {
        "id":           row.interaction_id,
        "client_id":    row.client_id,
        "stage":        meta.get('stage'),
        "priority":     meta.get('priority', 'High'),
        "completed":    meta.get('completed', False),
        "completed_at": meta.get('completed_at'),
        "created_at":   row.created_at.isoformat() if row.created_at else None,
    }


# ═════════════════════════════════════════════════════════════════════════════
# DATA IMPORTS
# Stored in Client_Interactions with contact_method = CONTACT_METHOD_DATA_IMPORT (100)
# client_id = NULL (imports are not tied to a specific client)
# ═════════════════════════════════════════════════════════════════════════════

@db_bp.route('/data-imports', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_data_imports():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json
            meta = {
                "filename":          data.get('filename'),
                "import_type":       data.get('import_type'),
                "status":            data.get('status', 'processing'),
                "records_processed": data.get('records_processed', 0),
                "records_failed":    data.get('records_failed', 0),
                "error_log":         data.get('error_log'),
                "imported_by":       get_current_user_email(data),
                "completed_at":      None,
            }
            result = session.execute(
                text("""
                    INSERT INTO "streemLyne_mt_dev2"."Client_Interactions"
                        (client_id, contact_date, contact_method, notes, created_at)
                    VALUES
                        (NULL, :contact_date, :contact_method, :notes, :created_at)
                    RETURNING interaction_id
                """),
                {
                    "contact_date":   datetime.utcnow().date(),
                    "contact_method": CONTACT_METHOD_DATA_IMPORT,
                    "notes":          pack_meta(meta),
                    "created_at":     datetime.utcnow()
                }
            )
            new_id = result.fetchone().interaction_id
            session.commit()

            return jsonify({
                'id': new_id,
                'message': 'Data import record created successfully',
                'data_import': _row_to_data_import(new_id, session)
            }), 201

        # GET
        rows = session.execute(
            text("""
                SELECT * FROM "streemLyne_mt_dev2"."Client_Interactions"
                WHERE contact_method = :cm
                ORDER BY created_at DESC
            """),
            {"cm": CONTACT_METHOD_DATA_IMPORT}
        ).fetchall()

        result = []
        for row in rows:
            meta, _ = unpack_meta(row.notes)
            result.append({
                "id":                row.interaction_id,
                "filename":          meta.get('filename'),
                "import_type":       meta.get('import_type'),
                "status":            meta.get('status', 'processing'),
                "records_processed": meta.get('records_processed', 0),
                "records_failed":    meta.get('records_failed', 0),
                "error_log":         meta.get('error_log'),
                "imported_by":       meta.get('imported_by'),
                "completed_at":      meta.get('completed_at'),
                "created_at":        row.created_at.isoformat() if row.created_at else None,
            })

        return jsonify(result), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling data imports: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@db_bp.route('/data-imports/<int:import_id>', methods=['GET', 'PUT', 'OPTIONS'])
@token_required
def handle_single_data_import(import_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        row = session.execute(
            text('SELECT * FROM "streemLyne_mt_dev2"."Client_Interactions" WHERE interaction_id = :iid AND contact_method = :cm'),
            {"iid": import_id, "cm": CONTACT_METHOD_DATA_IMPORT}
        ).fetchone()

        if not row:
            return jsonify({'error': 'Data import not found'}), 404

        meta, base_notes = unpack_meta(row.notes)

        if request.method == 'GET':
            return jsonify({
                "id":                import_id,
                "filename":          meta.get('filename'),
                "import_type":       meta.get('import_type'),
                "status":            meta.get('status', 'processing'),
                "records_processed": meta.get('records_processed', 0),
                "records_failed":    meta.get('records_failed', 0),
                "error_log":         meta.get('error_log'),
                "imported_by":       meta.get('imported_by'),
                "completed_at":      meta.get('completed_at'),
                "created_at":        row.created_at.isoformat() if row.created_at else None,
            }), 200

        elif request.method == 'PUT':
            data = request.json

            for field in ['status', 'records_processed', 'records_failed', 'error_log']:
                if field in data:
                    meta[field] = data[field]

            if data.get('status') in ['completed', 'failed'] and not meta.get('completed_at'):
                meta['completed_at'] = datetime.utcnow().isoformat()

            session.execute(
                text('UPDATE "streemLyne_mt_dev2"."Client_Interactions" SET notes = :notes WHERE interaction_id = :iid'),
                {"notes": pack_meta(meta, base_notes), "iid": import_id}
            )
            session.commit()
            return jsonify({'message': 'Data import updated successfully'}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling data import {import_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


def _row_to_data_import(import_id, session):
    row = session.execute(
        text('SELECT * FROM "streemLyne_mt_dev2"."Client_Interactions" WHERE interaction_id = :iid'),
        {"iid": import_id}
    ).fetchone()
    if not row:
        return {}
    meta, _ = unpack_meta(row.notes)
    return {
        "id":                import_id,
        "filename":          meta.get('filename'),
        "import_type":       meta.get('import_type'),
        "status":            meta.get('status', 'processing'),
        "records_processed": meta.get('records_processed', 0),
        "records_failed":    meta.get('records_failed', 0),
        "error_log":         meta.get('error_log'),
        "imported_by":       meta.get('imported_by'),
        "completed_at":      meta.get('completed_at'),
        "created_at":        row.created_at.isoformat() if row.created_at else None,
    }