# routes/auth_routes.py
from flask import Blueprint, request, jsonify, current_app
from database import db
from models import User, LoginAttempt, Session, Tenant
from datetime import datetime, timedelta
from functools import wraps
import secrets
import re

auth_bp = Blueprint('auth', __name__)

def get_client_ip():
    """Get client IP address"""
    if request.environ.get('HTTP_X_FORWARDED_FOR') is None:
        return request.environ['REMOTE_ADDR']
    else:
        return request.environ['HTTP_X_FORWARDED_FOR']

def validate_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_password(password):
    """Validate password strength"""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r'\d', password):
        return False, "Password must contain at least one number"
    return True, "Password is valid"

def check_rate_limit(email, max_attempts=5, window_minutes=15):
    """Check if user has exceeded login attempts"""
    cutoff_time = datetime.utcnow() - timedelta(minutes=window_minutes)
    
    recent_attempts = LoginAttempt.query.filter(
        LoginAttempt.email == email,
        LoginAttempt.attempted_at > cutoff_time,
        LoginAttempt.success == False
    ).count()
    
    return recent_attempts < max_attempts

def log_login_attempt(email, ip_address, success):
    """Log login attempt"""
    attempt = LoginAttempt(
        email=email,
        ip_address=ip_address,
        success=success
    )
    db.session.add(attempt)
    db.session.commit()

def token_required(f):
    """Decorator to require authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Check for token in Authorization header
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]  # Bearer TOKEN
            except IndexError:
                return jsonify({'error': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        
        try:
            # Verify the token
            current_user = User.verify_jwt_token(token, current_app.config['SECRET_KEY'])
            if not current_user:
                return jsonify({'error': 'Token is invalid or expired'}), 401
            
            # Add current user to the request context
            request.current_user = current_user
            
        except Exception as e:
            return jsonify({'error': 'Token verification failed'}), 401
        
        return f(*args, **kwargs)
    
    return decorated

def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    @token_required
    def decorated(*args, **kwargs):
        if request.current_user.role != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated

@auth_bp.route('/auth/register', methods=['POST'])
def register():
    """
    Register a new user with either Individual or Company tenant
    
    Request Body:
    {
        "email": "user@example.com",
        "password": "password123",
        "first_name": "John",
        "last_name": "Doe",
        "tenant_type": "individual" OR "company",
        "company_name": "Acme Corp" (only if tenant_type is "company")
    }
    """
    try:
        data = request.get_json(silent=True) or {}
        
        # ✅ CRITICAL: Check for tenant_type, NOT tenant_id
        required_fields = ['email', 'password', 'first_name', 'last_name', 'tenant_type']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        email = data['email'].lower().strip()
        password = data['password']
        first_name = data['first_name'].strip()
        last_name = data['last_name'].strip()
        tenant_type = data['tenant_type'].lower()
        
        print(f"📝 Registration request - Email: {email}, Type: {tenant_type}")
        
        # Validate tenant type
        if tenant_type not in ['individual', 'company']:
            return jsonify({'error': 'tenant_type must be either "individual" or "company"'}), 400
        
        # Validate email format
        if not validate_email(email):
            return jsonify({'error': 'Invalid email format'}), 400
        
        # Validate password strength
        is_valid, message = validate_password(password)
        if not is_valid:
            return jsonify({'error': message}), 400
        
        # Handle Company Registration
        if tenant_type == 'company':
            company_name = data.get('company_name', '').strip()
            
            if not company_name:
                return jsonify({'error': 'company_name is required when tenant_type is "company"'}), 400
            
            print(f"🏢 Company registration for: {company_name}")
            
            # Check if company already exists (case-insensitive)
            existing_tenant = Tenant.query.filter(
                Tenant.tenant_type == 'company',
                db.func.lower(Tenant.company_name) == company_name.lower()
            ).first()
            
            if existing_tenant:
                # Company exists - check if email is already used in this tenant
                existing_user = User.query.filter_by(
                    email=email,
                    tenant_id=existing_tenant.id
                ).first()
                
                if existing_user:
                    return jsonify({'error': 'Email already registered in this company'}), 409
                
                # Add user to existing company
                tenant = existing_tenant
                role = 'member'  # New users joining existing company are members
                
                print(f"✅ User joining existing company: {company_name}")
            else:
                # Create new company tenant
                company_slug = Tenant.create_slug(company_name)
                
                # Ensure slug is unique
                base_slug = company_slug
                counter = 1
                while Tenant.query.filter_by(subdomain=company_slug).first():
                    company_slug = f"{base_slug}-{counter}"
                    counter += 1
                
                tenant = Tenant(
                    tenant_type='company',
                    company_name=company_name,
                    subdomain=company_slug,
                    max_users=999999,  # Unlimited for companies
                    is_active=True
                )
                db.session.add(tenant)
                db.session.flush()  # Get tenant ID
                
                role = 'owner'  # First user in company is owner
                
                print(f"✅ Created new company: {company_name} (slug: {company_slug})")
        
        # Handle Individual Registration
        else:  # tenant_type == 'individual'
            print(f"👤 Individual registration for: {email}")
            
            # Check if this email already has an individual account
            existing_individual = User.query.join(
                Tenant, User.tenant_id == Tenant.id  # Explicit join condition
            ).filter(
                User.email == email,
                Tenant.tenant_type == 'individual'
            ).first()
            
            if existing_individual:
                return jsonify({'error': 'Email already registered as individual account'}), 409
            
            # Create individual tenant (one per user)
            tenant = Tenant(
                tenant_type='individual',
                company_name=None,
                subdomain=None,
                max_users=1,  # Only one user allowed
                is_active=True
            )
            db.session.add(tenant)
            db.session.flush()  # Get tenant ID
            
            role = 'owner'  # Individual users are owners of their tenant
            
            print(f"✅ Created individual tenant: {tenant.id}")
        
        # Create user
        user = User(
            tenant_id=tenant.id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            phone=data.get('phone', '').strip(),
            role=role,
            is_active=True,
            is_verified=False
        )
        user.set_password(password)
        user.generate_verification_token()#

        db.session.add(user)
        db.session.flush() 
        
        # Link individual tenant to owner user
        if tenant_type == 'individual':
            tenant.owner_user_id = user.id
        
        db.session.commit()
        
        # Generate JWT token
        token = user.generate_jwt_token(current_app.config['SECRET_KEY'])
        
        # Log successful registration
        log_login_attempt(email, get_client_ip(), True)
        
        print(f"✅ User registered successfully: {email} (ID: {user.id}, Tenant: {tenant.id})")
        
        return jsonify({
            'message': 'User registered successfully',
            'user': user.to_dict(),
            'tenant': tenant.to_dict(),
            'token': token
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Registration error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/auth/login', methods=['POST'])
def login():
    """Login user"""
    try:
        data = request.get_json(silent=True) or {}

        if not data.get('email') or not data.get('password'):
            return jsonify({'error': 'Email and password are required'}), 400
        
        email = data['email'].lower().strip()
        password = data['password']
        ip_address = get_client_ip()
        
        # Check rate limiting
        if not check_rate_limit(email):
            return jsonify({'error': 'Too many failed login attempts. Try again later.'}), 429
        
        # Find user (email is now unique per tenant, but we don't know tenant yet)
        user = User.query.filter_by(email=email).first()
        
        if not user or not user.check_password(password):
            log_login_attempt(email, ip_address, False)
            return jsonify({'error': 'Invalid email or password'}), 401
        
        if not user.is_active:
            log_login_attempt(email, ip_address, False)
            return jsonify({'error': 'Account is disabled'}), 401
        
        # NEW: Get tenant info and verify it's active
        tenant = Tenant.query.get(user.tenant_id)
        if not tenant:
            log_login_attempt(email, ip_address, False)
            return jsonify({'error': 'Tenant not found'}), 404
        
        if not tenant.is_active:
            log_login_attempt(email, ip_address, False)
            return jsonify({'error': 'Tenant account is inactive'}), 403
        
        # Update last login
        user.last_login = datetime.utcnow()
        
        # Generate JWT token (includes user_id which links to tenant)
        token = user.generate_jwt_token(current_app.config['SECRET_KEY'])
        
        # Create session record
        session = Session(
            user_id=user.id,
            tenant_id=user.tenant_id,  # NEW: Add tenant_id to session
            session_token=token,
            ip_address=ip_address,
            user_agent=request.headers.get('User-Agent', ''),
            expires_at=datetime.utcnow() + timedelta(days=7)
        )
        db.session.add(session)
        
        # Log successful login
        log_login_attempt(email, ip_address, True)
        
        db.session.commit()
        
        return jsonify({
            'message': 'Login successful',
            'token': token,
            'user': user.to_dict(),
            'tenant': tenant.to_dict()  # NEW: Return tenant info to frontend
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/auth/logout', methods=['POST'])
@token_required
def logout():
    """Logout user"""
    try:
        # Get token from header
        token = request.headers.get('Authorization').split(" ")[1]
        
        # Remove session
        session = Session.query.filter_by(session_token=token).first()
        if session:
            db.session.delete(session)
            db.session.commit()
        
        return jsonify({'message': 'Logged out successfully'}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/auth/me', methods=['GET'])
@token_required
def get_current_user():
    """Get current user information"""
    try:
        user = request.current_user
        
        # NEW: Also return tenant info
        tenant = Tenant.query.get(user.tenant_id)
        
        return jsonify({
            'user': user.to_dict(),
            'tenant': tenant.to_dict() if tenant else None  # NEW
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/auth/refresh', methods=['POST'])
@token_required
def refresh_token():
    """Refresh JWT token"""
    try:
        user = request.current_user
        
        # NEW: Verify tenant is still active
        tenant = Tenant.query.get(user.tenant_id)
        if not tenant or not tenant.is_active:
            return jsonify({'error': 'Tenant account is inactive'}), 403
        
        new_token = user.generate_jwt_token(current_app.config['SECRET_KEY'])
        
        # Update session with new token
        old_token = request.headers.get('Authorization').split(" ")[1]
        session = Session.query.filter_by(session_token=old_token).first()
        if session:
            session.session_token = new_token
            session.expires_at = datetime.utcnow() + timedelta(days=7)
            db.session.commit()
        
        return jsonify({
            'token': new_token,
            'user': user.to_dict(),
            'tenant': tenant.to_dict()  # NEW
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/auth/forgot-password', methods=['POST'])
def forgot_password():
    """Request password reset"""
    try:
        data = request.get_json(silent=True) or {}
        
        if not data.get('email'):
            return jsonify({'error': 'Email is required'}), 400
        
        email = data['email'].lower().strip()
        user = User.query.filter_by(email=email).first()
        
        if user:
            reset_token = user.generate_reset_token()
            db.session.commit()
            
            # TODO: Send email with reset token
            # For now, just return success
            print(f"Password reset token for {email}: {reset_token}")
        
        # Always return success to prevent email enumeration
        return jsonify({
            'message': 'If the email exists, a password reset link has been sent.'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/auth/reset-password', methods=['POST'])
def reset_password():
    """Reset password with token"""
    try:
        data = request.get_json(silent=True) or {}
        
        required_fields = ['token', 'password']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        token = data['token']
        password = data['password']
        
        # Validate password strength
        is_valid, message = validate_password(password)
        if not is_valid:
            return jsonify({'error': message}), 400
        
        # Find user by reset token
        user = User.query.filter(
            User.reset_token == token,
            User.reset_token_expires > datetime.utcnow()
        ).first()
        
        if not user:
            return jsonify({'error': 'Invalid or expired reset token'}), 400
        
        # Update password
        user.set_password(password)
        user.reset_token = None
        user.reset_token_expires = None
        
        db.session.commit()
        
        return jsonify({'message': 'Password reset successful'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/auth/change-password', methods=['POST'])
@token_required
def change_password():
    """Change password for authenticated user"""
    try:
        data = request.get_json(silent=True) or {}
        
        required_fields = ['current_password', 'new_password']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        current_password = data['current_password']
        new_password = data['new_password']
        user = request.current_user
        
        # Verify current password
        if not user.check_password(current_password):
            return jsonify({'error': 'Current password is incorrect'}), 400
        
        # Validate new password
        is_valid, message = validate_password(new_password)
        if not is_valid:
            return jsonify({'error': message}), 400
        
        # Update password
        user.set_password(new_password)
        user.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({'message': 'Password changed successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/auth/users', methods=['GET'])
@admin_required
def get_users():
    """Get all users (admin only) - scoped to current user's tenant"""
    try:
        # NEW: Filter users by tenant
        current_user = request.current_user
        users = User.query.filter_by(tenant_id=current_user.tenant_id).order_by(User.created_at.desc()).all()
        
        return jsonify({
            'users': [user.to_dict() for user in users]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/auth/users/<int:user_id>/toggle-status', methods=['POST'])
@admin_required
def toggle_user_status(user_id):
    """Toggle user active status (admin only)"""
    try:
        current_user = request.current_user
        
        # NEW: Security check - can only toggle users in same tenant
        user = User.query.filter_by(id=user_id, tenant_id=current_user.tenant_id).first_or_404()
        
        user.is_active = not user.is_active
        user.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': f'User {"activated" if user.is_active else "deactivated"} successfully',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    
@auth_bp.route('/auth/tenant', methods=['GET'])
@token_required
def get_tenant_info():
    """Get current tenant information"""
    try:
        user = request.current_user
        tenant = Tenant.query.get(user.tenant_id)
        
        if not tenant:
            return jsonify({'error': 'Tenant not found'}), 404
        
        return jsonify({
            'tenant': tenant.to_dict()
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/auth/check-company', methods=['POST'])
def check_company():
    """
    Check if a company name already exists
    Used in frontend to show if user is joining existing company or creating new
    """
    try:
        data = request.get_json(silent=True) or {}
        company_name = data.get('company_name', '').strip()
        
        if not company_name:
            return jsonify({'exists': False}), 200
        
        existing_tenant = Tenant.query.filter(
            Tenant.tenant_type == 'company',
            db.func.lower(Tenant.company_name) == company_name.lower()
        ).first()
        
        if existing_tenant:
            return jsonify({
                'exists': True,
                'company_name': existing_tenant.company_name,
                'company_slug': existing_tenant.subdomain,
                'message': f'You will join the existing company: {existing_tenant.company_name}'
            }), 200
        else:
            return jsonify({
                'exists': False,
                'message': f'A new company will be created: {company_name}'
            }), 200
            
    except Exception as e:
        print(f"❌ Check company error: {e}")
        return jsonify({'error': str(e)}), 500
