"""
Test Tenant Model
Tests for TenantMaster model
"""

import pytest
from datetime import date
from models import TenantMaster


def test_create_tenant(session):
    """Test creating a tenant"""
    tenant = TenantMaster(
        tenant_company_name='New Company',
        tenant_contact_name='John Doe',
        onboarding_date=date.today(),
        is_active=True
    )
    session.add(tenant)
    session.commit()
    
    assert tenant.tenant_id is not None
    assert tenant.tenant_company_name == 'New Company'
    assert tenant.is_active is True


def test_tenant_string_representation(session, tenant):
    """Test tenant __repr__ method"""
    repr_str = repr(tenant)
    assert 'TenantMaster' in repr_str
    assert tenant.tenant_company_name in repr_str


def test_tenant_to_dict(session, tenant):
    """Test tenant to_dict method"""
    tenant_dict = tenant.to_dict()
    
    assert 'tenant_id' in tenant_dict
    assert 'tenant_company_name' in tenant_dict
    assert tenant_dict['tenant_company_name'] == tenant.tenant_company_name
    assert tenant_dict['is_active'] == tenant.is_active


def test_deactivate_tenant(session, tenant):
    """Test deactivating a tenant"""
    tenant.is_active = False
    session.commit()
    
    assert tenant.is_active is False


def test_tenant_unique_company_name(session):
    """Test that company names are not required to be unique (multi-tenant system)"""
    tenant1 = TenantMaster(
        tenant_company_name='Duplicate Company',
        is_active=True
    )
    tenant2 = TenantMaster(
        tenant_company_name='Duplicate Company',
        is_active=True
    )
    session.add_all([tenant1, tenant2])
    session.commit()  # Should NOT raise
    
    assert tenant1.tenant_id != tenant2.tenant_id  # Both created, different IDs