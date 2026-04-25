"""
Pytest Configuration
Sets up test fixtures and database for testing
"""

import pytest
import sys
import os
from sqlalchemy import event
from sqlalchemy.pool import StaticPool

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


TEST_TABLES = [
    CurrencyMaster.__table__,
    DesignationMaster.__table__,
    TenantMaster.__table__,
    ModuleMaster.__table__,
    SubscriptionPlan.__table__,
    SubscriptionModuleMapping.__table__,
    TenantModuleMapping.__table__,
    TenantSubscription.__table__,
    SubscriptionInvoice.__table__,
    PaymentAttempt.__table__,
    DunningConfig.__table__,
    NotificationPreference.__table__,
    NotificationLog.__table__,
    SubscriptionPause.__table__,
    PendingPlanChange.__table__,
    EmployeeMaster.__table__,
    RoleMaster.__table__,
    UserMaster.__table__,
    UserRoleMapping.__table__,
]


@pytest.fixture(scope='session')
def app():
    """
    Create Flask app for testing with IN-MEMORY SQLite database.
    Forces SQLite BEFORE the engine is used.
    """
    flask_app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite://',
        'SECRET_KEY': 'test-secret-key',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'SQLALCHEMY_ECHO': False,
        'SQLALCHEMY_ENGINE_OPTIONS': {
            'connect_args': {'check_same_thread': False},
            'poolclass': StaticPool,
        },
    })

    with flask_app.app_context():
        # Dispose any existing connections to Supabase and recreate with SQLite
        _db.engine.dispose()
        
        @event.listens_for(_db.engine, 'connect')
        def _attach_test_schema(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute('ATTACH DATABASE ":memory:" AS "StreemLyne_MT"')
            except Exception:
                pass
            cursor.execute('PRAGMA foreign_keys = ON')
            cursor.close()

        _db.metadata.create_all(bind=_db.engine, tables=TEST_TABLES)

        yield flask_app

        _db.session.remove()
        # Use raw SQL with CASCADE to avoid FK dependency issues on drop
        with _db.engine.connect() as conn:
            conn.execute(_db.text('PRAGMA foreign_keys = OFF'))
        _db.metadata.drop_all(bind=_db.engine, tables=TEST_TABLES)


@pytest.fixture(scope='function')
def session(app):
    with app.app_context():
        yield _db.session
        # Clean up after each test by rolling back and clearing all tables
        _db.session.rollback()
        _db.session.remove()
        # Truncate all tables to ensure clean state
        for table in reversed(TEST_TABLES):
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
        tenant_id='test-company-001',
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
