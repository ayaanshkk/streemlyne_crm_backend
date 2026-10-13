import os
import jwt
from functools import wraps

from flask import request, jsonify, current_app
from sqlalchemy import text

from ..db import SessionLocal

# Tenants allowed to use the FAI module, e.g. FAI_TENANT_IDS=3
FAI_TENANT_IDS = {t.strip() for t in os.getenv('FAI_TENANT_IDS', '').split(',') if t.strip()}

SCHEMA = "streemLyne_mt_dev2"


def T(table_name):
    return f'"{SCHEMA}"."{table_name}"'


class CurrentUser:
    """Simple object attached to request.current_user by token_required."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self):
        return f"<CurrentUser user_id={self.id} employee_id={self.employee_id} role={self.role}>"


def _get_role_names(session, role_ids_str: str) -> list:
    if not role_ids_str:
        return []

    ids = [r.strip() for r in str(role_ids_str).split(',') if r.strip().isdigit()]
    if not ids:
        return []

    placeholders = ', '.join([f':r{i}' for i in range(len(ids))])
    params = {f'r{i}': int(rid) for i, rid in enumerate(ids)}

    rows = session.execute(
        text(f'SELECT role_name FROM {T("Role_Master")} WHERE role_id IN ({placeholders})'),
        params
    ).fetchall()

    return [row.role_name for row in rows]


def token_required(f):
    """
    JWT authentication decorator.
    On success, attaches a CurrentUser instance to request.current_user.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            try:
                token = auth_header.split(' ')[1]
            except IndexError:
                return jsonify({'error': 'Invalid token format'}), 401

        if not token:
            return jsonify({'error': 'Authentication token is missing'}), 401

        secret_key = current_app.config.get('SECRET_KEY') or os.getenv('SECRET_KEY', 'dev-secret-key')

        try:
            payload = jwt.decode(token, secret_key, algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError as e:
            return jsonify({'error': f'Invalid token: {str(e)}'}), 401

        user_id = payload.get('user_id')

        if not user_id:
            return jsonify({'error': 'Token missing user_id'}), 401

        # ------------------------------------
        # VERIFY USER IN NEW DATABASE
        # tenant_id comes from User_Master.tenant_id, matching auth_routes.py's
        # login query - keeps both files consistent on which tenant_id column
        # is the source of truth.
        # ------------------------------------
        session = SessionLocal()
        try:
            row = session.execute(
                text(f"""
                    SELECT
                        um.user_id,
                        um.username,
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
                    WHERE um.user_id = :uid
                    LIMIT 1
                """),
                {"uid": user_id}
            ).mappings().first()

            # User does not exist
            if not row:
                return jsonify({'error': 'User not found or inactive'}), 401

            if row['is_active'] is False:
                return jsonify({'error': 'User account is inactive'}), 401

            if row['employee_is_active'] is False:
                return jsonify({'error': 'Employee account is inactive'}), 401

            # Inside StreemLyne, every tenant's staff token is valid here, so
            # only tenants that have the FAI module may use these routes.
            if str(row['tenant_id']) not in FAI_TENANT_IDS:
                return jsonify({'error': 'This module is not enabled for your company'}), 403

            role_names = _get_role_names(session, row['role_ids'])
            primary_role = role_names[0] if role_names else payload.get('role', 'Staff')
            admin = any(role.lower() == 'admin' for role in role_names)

            # --------------------------------------------------
            # ATTACH CURRENT USER
            # --------------------------------------------------

            request.current_user = CurrentUser(
                id=row['user_id'],
                user_id=row['user_id'],
                employee_id=row['employee_id'],
                employee_name=row['employee_name'],
                full_name=row['employee_name'],   # legacy alias used in some routes
                email=row['email'],
                phone=row['phone'],
                tenant_id=row['tenant_id'],
                role=primary_role,
                roles=role_names,
                is_admin=admin,
                username=row['username'],
            )

        except Exception as e:
            current_app.logger.error(f"token_required DB error: {e}")
            return jsonify({'error': 'Authentication error'}), 401
        finally:
            session.close()

        return f(*args, **kwargs)

    return decorated