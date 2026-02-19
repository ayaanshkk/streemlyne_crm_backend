"""
Pytest Configuration
Sets up test fixtures and database for testing
"""

import pytest
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# CRITICAL: Set test environment BEFORE importing app
os.environ['TESTING'] = 'true'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'

from app import app as flask_app
from database import db as _db
from models import *
from flask import g


@pytest.fixture(scope='session')
def app():
    """
    Create Flask app for testing with IN-MEMORY SQLite database.
    Forces SQLite BEFORE the engine is used.
    """
    flask_app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SECRET_KEY': 'test-secret-key',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'SQLALCHEMY_ECHO': False,
    })

    with flask_app.app_context():
        # Dispose any existing connections to Supabase and recreate with SQLite
        _db.engine.dispose()
        _db.create_all()

        yield flask_app

        _db.session.remove()
        # Use raw SQL with CASCADE to avoid FK dependency issues on drop
        with _db.engine.connect() as conn:
            conn.execute(_db.text('PRAGMA foreign_keys = OFF'))
        _db.drop_all()


@pytest.fixture(scope='function')
def session(app):
    with app.app_context():
        yield _db.session
        # Clean up after each test by rolling back and clearing all tables
        _db.session.rollback()
        _db.session.remove()
        # Truncate all tables to ensure clean state
        for table in reversed(_db.metadata.sorted_tables):
            _db.session.execute(table.delete())
        _db.session.commit()

@pytest.fixture
def client(app):
    """Create test client"""
    return app.test_client()


@pytest.fixture
def tenant(session):
    """Create a test tenant"""
    tenant = TenantMaster(
        tenant_company_name='Test Company',
        tenant_contact_name='Test User',
        is_active=True
    )
    session.add(tenant)
    session.commit()

    return tenant


@pytest.fixture
def employee(session, tenant):
    """Create a test employee"""
    employee = EmployeeMaster(
        tenant_id=tenant.tenant_id,
        employee_name='Test Employee',
        email='test@example.com',
        phone='555-0123',
        role_ids='1'
    )
    session.add(employee)
    session.commit()
    return employee


@pytest.fixture
def user(session, employee):
    """Create a test user"""
    user = UserMaster(
        employee_id=employee.employee_id,
        user_name='testuser'
    )
    user.set_password('testpass123')
    session.add(user)
    session.commit()
    return user