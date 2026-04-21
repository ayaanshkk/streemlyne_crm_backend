"""
Auth Routes
Handles authentication for two user types:
  - Internal users  → User_Master + Employee_Master  (staff / admin login)
  - Customer portal → Customer_Auth + Customer_Password_Reset

Schema alignment (StreemLyne_MT):
  - User_Master       : user_id, employee_id, user_name, password, created_at, updated_at (DATE)
  - Employee_Master   : employee_id, tenant_id (varchar), employee_name, email, phone, …
  - Customer_Auth     : customer_user_id, client_id, tenant_id (varchar), email, password_hash, is_active, created_at
  - Customer_Password_Reset : id, customer_user_id, token, expires_at, used, created_at

CHANGES vs previous version
─────────────────────────────────────────────────────────────────────────────
[AUTH-001] tenant_id is now stored and forwarded as a STRING (varchar slug).
           The old code called int(data['tenant_id']) which would crash for
           slugs like "acme-ltd-a3f8c2" and was inconsistent with the DB PK.
─────────────────────────────────────────────────────────────────────────────
"""

from flask import Blueprint, request, jsonify, g, current_app
from sqlalchemy.exc import IntegrityError
from database import db
from models import UserMaster, EmployeeMaster, CustomerAuth, CustomerPasswordReset
from middleware import auth_required, get_current_user
from datetime import datetime, timedelta, date
import secrets
import re

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

def _validate_password(password: str) -> tuple[bool, str]:
    """Returns (is_valid, message)."""
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r'\d', password):
        return False, "Password must contain at least one number"
    return True, "OK"


# ─────────────────────────────────────────
# Internal Staff Auth  (User_Master)
# ─────────────────────────────────────────

@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Authenticate internal staff.

    POST /api/auth/login
    Body: { "user_name": "jdoe", "password": "Secret123" }
    """
    data = request.get_json() or {}

    if not data.get('user_name') or not data.get('password'):
        return jsonify({'error': 'user_name and password are required'}), 400

    from repositories import UserRepository
    user = UserRepository().authenticate(data['user_name'], data['password'])

    if not user:
        return jsonify({'error': 'Invalid credentials'}), 401

    if not user.employee:
        return jsonify({'error': 'User account is not linked to an employee'}), 500

    token = user.generate_jwt_token(current_app.config['SECRET_KEY'])

    return jsonify({
        'message': 'Login successful',
        'token': token,
        'user': user.to_dict()
    }), 200


@auth_bp.route('/register', methods=['POST'])
def register():
    """
    Register a new employee + internal user account.

    POST /api/auth/register
    Body:
    {
        "tenant_id": "acme-ltd-a3f8c2",   (required, string slug)
        "employee_name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "555-0100",               (optional)
        "user_name": "janedoe",
        "password": "Secret123",
        "designation_id": 2                (optional)
    }
    """
    data = request.get_json() or {}

    required = ['tenant_id', 'employee_name', 'email', 'user_name', 'password']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400

    is_valid, msg = _validate_password(data['password'])
    if not is_valid:
        return jsonify({'error': msg}), 400

    try:
        # [AUTH-001] tenant_id is a string slug — do NOT cast to int.
        g.tenant_id = str(data['tenant_id'])

        from services import EmployeeService
        svc = EmployeeService()

        employee = svc.create_employee(
            employee_name=data['employee_name'],
            email=data['email'],
            phone=data.get('phone'),
            designation_id=data.get('designation_id')
        )

        user = svc.create_user_account(
            employee_id=employee.employee_id,
            user_name=data['user_name'],
            password=data['password']
        )

        token = user.generate_jwt_token(current_app.config['SECRET_KEY'])

        return jsonify({
            'message': 'Registration successful',
            'token': token,
            'user': user.to_dict()
        }), 201

    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'A user with that email or username already exists'}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/me', methods=['GET'])
@auth_required
def get_current_user_info():
    """Return profile for the currently authenticated staff user."""
    user = get_current_user()
    return jsonify({'user': user.to_dict()}), 200


@auth_bp.route('/change-password', methods=['POST'])
@auth_required
def change_password():
    """
    Change password for the authenticated staff user.

    POST /api/auth/change-password
    Body: { "current_password": "...", "new_password": "..." }

    Note: User_Master.updated_at is a DATE column in the schema.
    """
    data = request.get_json() or {}
    user = get_current_user()

    if not data.get('current_password') or not data.get('new_password'):
        return jsonify({'error': 'current_password and new_password are required'}), 400

    if not user.check_password(data['current_password']):
        return jsonify({'error': 'Current password is incorrect'}), 400

    is_valid, msg = _validate_password(data['new_password'])
    if not is_valid:
        return jsonify({'error': msg}), 400

    user.set_password(data['new_password'])
    # updated_at is a DATE column in User_Master — store today's date
    user.updated_at = date.today()
    db.session.commit()

    return jsonify({'message': 'Password changed successfully'}), 200


# ─────────────────────────────────────────
# Customer Portal Auth  (Customer_Auth)
# ─────────────────────────────────────────

@auth_bp.route('/customer/login', methods=['POST'])
def customer_login():
    """
    Authenticate a customer portal user.

    POST /api/auth/customer/login
    Body: { "email": "client@example.com", "password": "..." }
    """
    data = request.get_json() or {}

    if not data.get('email') or not data.get('password'):
        return jsonify({'error': 'email and password are required'}), 400

    customer_user: CustomerAuth = CustomerAuth.query.filter_by(
        email=data['email'].lower().strip(),
        is_active=True
    ).first()

    if not customer_user or not customer_user.check_password(data['password']):
        return jsonify({'error': 'Invalid credentials'}), 401

    token = customer_user.generate_jwt_token(current_app.config['SECRET_KEY'])

    return jsonify({
        'message': 'Login successful',
        'token': token,
        'customer_user_id': customer_user.customer_user_id,
        'client_id': customer_user.client_id,
        'tenant_id': customer_user.tenant_id
    }), 200


@auth_bp.route('/customer/register', methods=['POST'])
def customer_register():
    """
    Register a new customer portal account.

    POST /api/auth/customer/register
    Body: { "email": "...", "password": "...", "client_id": 5, "tenant_id": "acme-ltd-a3f8c2" }

    Validates that the referenced Client_Master row exists before creating the account.
    """
    data = request.get_json() or {}

    required = ['email', 'password', 'client_id', 'tenant_id']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400

    is_valid, msg = _validate_password(data['password'])
    if not is_valid:
        return jsonify({'error': msg}), 400

    email = data['email'].lower().strip()

    if CustomerAuth.query.filter_by(email=email).first():
        return jsonify({'error': 'Email is already registered'}), 409

    # Validate FK → Client_Master (also confirms client belongs to the stated tenant)
    from models import ClientMaster
    client = ClientMaster.query.filter_by(
        client_id=data['client_id'],
        tenant_id=str(data['tenant_id'])
    ).first()
    if not client:
        return jsonify({'error': 'Invalid client_id or tenant_id'}), 400

    try:
        customer_user = CustomerAuth(
            client_id=data['client_id'],
            tenant_id=str(data['tenant_id']),
            email=email,
            is_active=True
        )
        customer_user.set_password(data['password'])
        db.session.add(customer_user)
        db.session.commit()

        return jsonify({
            'message': 'Customer account created successfully',
            'customer_user_id': customer_user.customer_user_id
        }), 201

    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Email is already registered'}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/customer/forgot-password', methods=['POST'])
def customer_forgot_password():
    """
    Request a password reset token for a customer portal account.
    Always returns 200 to prevent email enumeration.

    POST /api/auth/customer/forgot-password
    Body: { "email": "client@example.com" }
    """
    data = request.get_json() or {}
    email = (data.get('email') or '').lower().strip()

    if not email:
        return jsonify({'error': 'email is required'}), 400

    customer_user: CustomerAuth = CustomerAuth.query.filter_by(
        email=email,
        is_active=True
    ).first()

    if customer_user:
        # Invalidate any existing unused tokens for this user
        CustomerPasswordReset.query.filter_by(
            customer_user_id=customer_user.customer_user_id,
            used=False
        ).update({'used': True})

        token = secrets.token_urlsafe(32)
        reset = CustomerPasswordReset(
            customer_user_id=customer_user.customer_user_id,
            token=token,
            expires_at=datetime.utcnow() + timedelta(hours=2),
            used=False
        )
        db.session.add(reset)
        db.session.commit()

        # TODO: dispatch reset email containing the token
        current_app.logger.info(f"[AUTH] Password reset requested for {email}")

    return jsonify({'message': 'If that email exists, a reset link has been sent.'}), 200


@auth_bp.route('/customer/reset-password', methods=['POST'])
def customer_reset_password():
    """
    Reset customer password using a valid, unused token.

    POST /api/auth/customer/reset-password
    Body: { "token": "...", "new_password": "..." }
    """
    data = request.get_json() or {}

    if not data.get('token') or not data.get('new_password'):
        return jsonify({'error': 'token and new_password are required'}), 400

    is_valid, msg = _validate_password(data['new_password'])
    if not is_valid:
        return jsonify({'error': msg}), 400

    reset: CustomerPasswordReset = CustomerPasswordReset.query.filter_by(
        token=data['token'],
        used=False
    ).first()

    if not reset or reset.expires_at < datetime.utcnow():
        return jsonify({'error': 'Invalid or expired token'}), 400

    customer_user: CustomerAuth = db.session.get(CustomerAuth, reset.customer_user_id)
    if not customer_user:
        return jsonify({'error': 'Account not found'}), 404

    customer_user.set_password(data['new_password'])
    reset.used = True
    db.session.commit()

    return jsonify({'message': 'Password reset successfully'}), 200