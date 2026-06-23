"""
Test User Model
"""

import pytest
from models import UserMaster


def test_create_user(session, employee):
    """Test creating a user"""
    user = UserMaster(
        employee_id=employee.employee_id,
        user_name='testuser'
    )
    user.set_password('testpass123')
    session.add(user)
    session.commit()
    
    assert user.user_id is not None
    assert user.user_name == 'testuser'


def test_password_hashing(session, user):
    """Test password is hashed, not stored as plain text"""
    # Password should NOT be stored as plain text
    assert user.password != 'testpass123'
    
    # But check_password should work
    assert user.check_password('testpass123') is True
    assert user.check_password('wrongpassword') is False


def test_generate_jwt_token(session, user):
    """Test JWT token generation"""
    token = user.generate_jwt_token('test-secret-key')
    
    assert token is not None
    assert isinstance(token, str)
    assert len(token) > 50  # JWT tokens are long


def test_verify_jwt_token(session, user):
    """Test JWT token verification"""
    token = user.generate_jwt_token('test-secret-key')
    
    # Verify valid token
    verified_user = UserMaster.verify_jwt_token(token, 'test-secret-key')
    assert verified_user is not None
    assert verified_user.user_id == user.user_id
    
    # Verify invalid token
    invalid_user = UserMaster.verify_jwt_token('invalid-token', 'test-secret-key')
    assert invalid_user is None