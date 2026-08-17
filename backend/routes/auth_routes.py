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

CHANGES
─────────────────────────────────────────────────────────────────────────────
[AUTH-001] tenant_id is stored/forwarded as a STRING (varchar slug).
[AUTH-002] /auth/login now accepts username OR email as the login identifier.
[AUTH-003] /auth/register stores username for individual accounts.
[AUTH-004] /auth/check-username endpoint added for real-time availability.
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


def _validate_username(username: str) -> tuple[bool, str]:
    """Returns (is_valid, message). Only lowercase letters, numbers, underscores allowed."""
    if not username:
        return False, "Username is required"
    if len(username) < 3:
        return False, "Username must be at least 3 characters"
    if len(username) > 30:
        return False, "Username must be 30 characters or fewer"
    if not re.match(r'^[a-z0-9_]+$', username):
        return False, "Username may only contain lowercase letters, numbers, and underscores"
    return True, "OK"


def _user_limit_error_response(exc):
    usage = getattr(exc, "usage", {}) or {}
    return jsonify({
        "error": "user_limit_reached",
        "message": str(exc),
        "limit": usage.get("effective_user_limit"),
        "current_count": usage.get("current_user_count"),
        "plan_code": usage.get("plan_code"),
        "upgrade_url": "/dashboard/subscription",
    }), 403


# ─────────────────────────────────────────
# Internal Staff Auth  (User_Master)
# ─────────────────────────────────────────

@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Authenticate internal staff.
    Accepts username OR email as the login identifier.

    POST /api/auth/login
    Body: { "user_name": "jdoe", "password": "Secret123" }
      OR  { "username": "jdoe", "password": "Secret123" }
      OR  { "email": "jdoe@example.com", "password": "Secret123" }
    """
    data = request.get_json() or {}

    # Accept all three identifier fields — normalise to user_name
    identifier = (
        data.get('user_name') or
        data.get('username') or
        data.get('email') or
        ''
    ).strip()
    password = data.get('password', '')

    if not identifier or not password:
        return jsonify({'error': 'Login identifier (username or email) and password are required'}), 400

    print(f"[DEBUG] login attempt: identifier={identifier!r}")

    from repositories import UserRepository
    repo = UserRepository()

    # Try by username first, then by email if it looks like an email
    user = repo.authenticate(identifier, password)

    # If authenticate only handles user_name, fall back to email lookup
    if not user and '@' in identifier:
        # Look up the user by email via Employee_Master, then authenticate
        employee = EmployeeMaster.query.filter_by(email=identifier.lower()).first()
        if employee:
            user_by_email = UserMaster.query.filter_by(employee_id=employee.employee_id).first()
            if user_by_email and user_by_email.check_password(password):
                user = user_by_email

    print(f"[DEBUG] user found: {user}")

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


@auth_bp.route('/check-username', methods=['POST'])
def check_username():
    """
    Check whether a username is available.

    POST /api/auth/check-username
    Body: { "username": "johndoe" }
    Returns: { "available": true/false, "message": "..." }
    """
    data = request.get_json() or {}
    username = (data.get('username') or '').lower().strip()

    if not username:
        return jsonify({'available': False, 'message': 'Username is required'}), 400

    is_valid, msg = _validate_username(username)
    if not is_valid:
        return jsonify({'available': False, 'message': msg}), 200

    # Check User_Master.user_name for collision
    existing = UserMaster.query.filter_by(user_name=username).first()
    if existing:
        return jsonify({'available': False, 'message': 'Username is already taken'}), 200

    return jsonify({'available': True, 'message': 'Username is available'}), 200


@auth_bp.route('/register', methods=['POST'])
def register():
    """
    Register a new internal user / tenant.

    POST /api/auth/register
    Body (individual): {
        "first_name": "John", "last_name": "Doe",
        "email": "john@example.com", "password": "Secret123",
        "username": "johndoe",
        "account_type": "individual"
    }
    Body (company): {
        "first_name": "Jane", "last_name": "Smith",
        "email": "jane@acme.com", "password": "Secret123",
        "username": "acme_ltd",        ← auto-suggested on frontend, editable
        "company_name": "Acme Ltd",
        "company_size": "1-10",
        "industry": "technology",
        "phone": "+44 7700 000000",    ← optional
        "account_type": "company"
    }
    """
    data = request.get_json() or {}

    account_type = data.get('account_type', 'individual')

    # Build employee_name from first/last
    if not data.get('employee_name') and (data.get('first_name') or data.get('last_name')):
        data['employee_name'] = f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()

    # ── Resolve username ──────────────────────────────────────────────────────
    # Both account types now require a username (company gets it auto-suggested
    # on the frontend but must still supply it here).
    username = (data.get('username') or '').lower().strip()

    if not username:
        # Last-resort fallback: derive from email local part
        username = (data.get('email', '')).split('@')[0].lower()
        username = re.sub(r'[^a-z0-9_]', '_', username)[:28]

    is_valid, msg = _validate_username(username)
    if not is_valid:
        return jsonify({'error': msg}), 400

    # Ensure uniqueness — append number if taken
    original = username
    counter  = 2
    while UserMaster.query.filter_by(user_name=username).first():
        username = f"{original[:25]}_{counter}"
        counter += 1
        if counter > 99:
            return jsonify({'error': 'Could not generate a unique username. Please choose one manually.'}), 409

    data['user_name'] = username

    # ── Common required fields ────────────────────────────────────────────────
    required = ['employee_name', 'email', 'user_name', 'password']
    missing  = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400

    is_valid, msg = _validate_password(data['password'])
    if not is_valid:
        return jsonify({'error': msg}), 400

    try:
        # ── Tenant setup ──────────────────────────────────────────────────────
        if not data.get('tenant_id'):
            from services.tenant_service import TenantService
            company_name = (data.get('company_name') or '').strip() or data['employee_name']
            tenant = TenantService().create_tenant(company_name=company_name)
            g.tenant_id = tenant.tenant_id
        else:
            g.tenant_id = str(data['tenant_id'])
            tenant = None

        from services.subscription_service import SubscriptionService
        SubscriptionService().ensure_user_limit_available(g.tenant_id)

        # ── Store extra company metadata on Tenant_Master if available ────────
        if account_type == 'company' and tenant:
            if data.get('company_size'):
                tenant.company_size  = data['company_size']
            if data.get('industry'):
                tenant.industry      = data['industry']
            db.session.flush()

        # ── Create employee + user account ────────────────────────────────────
        from services import EmployeeService
        svc      = EmployeeService()
        employee = svc.create_employee(
            employee_name  = data['employee_name'],
            email          = data['email'],
            phone          = data.get('phone'),
            designation_id = data.get('designation_id'),
        )
        user = svc.create_user_account(
            employee_id = employee.employee_id,
            user_name   = data['user_name'],
            password    = data['password'],
        )

        token = user.generate_jwt_token(current_app.config['SECRET_KEY'])
        return jsonify({
            'success':  True,
            'message':  'Registration successful',
            'token':    token,
            'username': data['user_name'],   # let frontend show it to the user
            'user':     user.to_dict(),
            'tenant':   {'tenant_id': g.tenant_id},
        }), 201

    except ValueError as e:
        db.session.rollback()
        from services.subscription_service import UserLimitExceeded
        if isinstance(e, UserLimitExceeded):
            return _user_limit_error_response(e)
        return jsonify({'error': str(e)}), 400
    except IntegrityError as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()  # ← add this
        print(f"[DEBUG] IntegrityError detail: {str(e.orig)}")  # ← add this
        return jsonify({'error': 'Email or username already exists', 'detail': str(e.orig)}), 409
    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
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