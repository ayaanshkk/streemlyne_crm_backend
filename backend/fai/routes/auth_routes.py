from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, timedelta
from sqlalchemy import text
from werkzeug.security import check_password_hash
from functools import wraps
import jwt

from ..db import SessionLocal


auth_bp = Blueprint("auth", __name__)

SCHEMA = "streemLyne_mt_dev2"


def T(table_name):
    return f'"{SCHEMA}"."{table_name}"'


def get_role_names(session, role_ids_str):
    """Return role names from Employee_Master.role_ids."""

    if not role_ids_str:
        return []

    role_ids = [
        r.strip()
        for r in str(role_ids_str).split(",")
        if r.strip().isdigit()
    ]

    if not role_ids:
        return []

    placeholders = ', '.join([f':r{i}' for i in range(len(role_ids))])
    params = {f'r{i}': int(role_id) for i, role_id in enumerate(role_ids)}

    rows = session.execute(
        text(f'SELECT role_name FROM {T("Role_Master")} WHERE role_id IN ({placeholders})'),
        params
    ).fetchall()

    return [row.role_name for row in rows]


def get_roles_from_mapping(session, user_id):
    """
    Get roles from User_Role_Mapping.

    Returns an empty list if no mapping exists or
    if the mapping table is unavailable.
    """

    try:
        rows = session.execute(
            text(f"""
                SELECT rm.role_id, rm.role_name
                FROM {T("User_Role_Mapping")} urm
                JOIN {T("Role_Master")} rm ON rm.role_id = urm.role_id
                WHERE urm.user_id = :user_id
                """
            ),
            {
                "user_id": user_id
            },
        ).fetchall()

        return [(row.role_id, row.role_name) for row in rows]

    except Exception as e:
        current_app.logger.warning(
            f"User_Role_Mapping lookup failed: {e}"
        )
        return []


@auth_bp.route("/health", methods=["GET"])
def health_check():
    return jsonify({'status': 'ok', 'message': 'Backend is running'}), 200


@auth_bp.route("/auth/login", methods=["POST"])
def login():
    session = SessionLocal()
    try:
        data = request.get_json() or {}
        username = data.get('user_name') or data.get('username')
        password = data.get('password')

        if not username or not password:
            return jsonify({'error': 'Username and password required'}), 400

        username = username.strip()

        # =========================================================
        # FETCH USER FROM NEW DATABASE
        # tenant_id comes from User_Master.tenant_id (not Employee_Master) -
        # User_Master has its own tenant_id column and is the source of
        # truth for which tenant a login belongs to.
        # =========================================================
        row = session.execute(
            text(
                f"""
                SELECT
                    um.user_id,
                    um.username,
                    um.password,
                    um.employee_id,
                    um.tenant_id,
                    um.is_active,
                    em.employee_name,
                    em.email,
                    em.phone,
                    em.role_ids,
                    em.is_active AS employee_is_active
                FROM {T("User_Master")} um
                LEFT JOIN {T("Employee_Master")} em ON em.employee_id = um.employee_id
                WHERE um.username = :username
                LIMIT 1
            """),
            {"username": username}
        ).mappings().first()

        if not row:
            current_app.logger.warning(f"Login failed - user not found: {username}")
            return jsonify({'error': 'Invalid username or password'}), 401

        if row.get('is_active') is False:
            return jsonify({'error': 'User account is inactive'}), 403

        if not check_password_hash(row['password'], password):
            current_app.logger.warning(f"Login failed - invalid password for: {username}")
            return jsonify({'error': 'Invalid username or password'}), 401

        # =========================================================
        # GET ROLES
        # =========================================================
        mapping_roles = get_roles_from_mapping(session, row['user_id'])

        if mapping_roles:
            role_ids_list = [role[0] for role in mapping_roles]
            role_names = [role[1] for role in mapping_roles]
        else:
            role_names = get_role_names(session, row.get('role_ids'))
            role_ids_list = [
                int(r.strip())
                for r in str(row.get('role_ids') or '').split(',')
                if r.strip().isdigit()
            ]

        primary_role = role_names[0] if role_names else 'Staff'
        primary_role_id = role_ids_list[0] if role_ids_list else None
        is_admin = any('admin' in role.lower() for role in role_names)

        current_app.logger.info(
            f"Login successful: {username} | tenant_id={row['tenant_id']} | roles={role_names}"
        )

        # =========================================================
        # JWT
        # =========================================================
        now = datetime.utcnow()
        payload = {
            "user_id": row["user_id"],
            "username": row["username"],
            "employee_id": row["employee_id"],
            "tenant_id": row["tenant_id"],
            "role": primary_role,
            "role_id": primary_role_id,
            "roles": role_names,
            "role_ids": role_ids_list,
            "is_admin": is_admin,
            "exp": now + timedelta(days=7),
            "iat": now,
        }
        token = jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')

        return jsonify({
            'success': True,
            'message': 'Login successful',
            'token': token,
            'user': {
                'user_id': row['user_id'],
                'user_name': row['username'],
                'employee_id': row['employee_id'],
                'employee_name': row['employee_name'],
                'email': row['email'],
                'phone': row['phone'],
                'tenant_id': row['tenant_id'],
                'role': primary_role,
                'role_id': primary_role_id,
                'roles': role_names,
                'role_ids': role_ids_list,
                'is_admin': is_admin
            }
        }), 200

    except Exception as e:
        current_app.logger.error(f"Login error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            return jsonify({'error': 'No token provided'}), 401
        try:
            payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
            if not payload.get('is_admin', False):
                return jsonify({'error': 'Admin access required'}), 403
            return f(*args, **kwargs)
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
    return decorated_function