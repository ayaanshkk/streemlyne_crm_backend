"""
Test Tenant Repository
Tests for TenantRepository
"""

import pytest
from flask import g
from repositories import TenantRepository
from models import TenantMaster


@pytest.fixture
def tenant_repo():
    """Create tenant repository instance"""
    return TenantRepository()


def test_get_by_company_name(session, tenant_repo, tenant):
    """Test getting tenant by company name"""
    result = tenant_repo.get_by_company_name('Test Company')
    
    assert result is not None
    assert result.tenant_id == tenant.tenant_id
    assert result.tenant_company_name == 'Test Company'


def test_get_active_tenants(session, tenant_repo):
    """Test getting all active tenants"""
    # Create multiple tenants
    tenant1 = TenantMaster(
        tenant_company_name='Active Company 1',
        is_active=True
    )
    tenant2 = TenantMaster(
        tenant_company_name='Active Company 2',
        is_active=True
    )
    tenant3 = TenantMaster(
        tenant_company_name='Inactive Company',
        is_active=False
    )
    session.add_all([tenant1, tenant2, tenant3])
    session.commit()
    
    active_tenants = tenant_repo.get_active_tenants()
    
    assert len(active_tenants) >= 2
    assert all(t.is_active for t in active_tenants)


def test_deactivate_tenant(session, tenant_repo, tenant):
    """Test deactivating a tenant"""
    success = tenant_repo.deactivate_tenant(tenant.tenant_id)
    
    assert success is True
    
    # Verify tenant is deactivated
    updated_tenant = session.query(TenantMaster).get(tenant.tenant_id)
    assert updated_tenant.is_active is False


def test_reactivate_tenant(session, tenant_repo, tenant):
    """Test reactivating a tenant"""
    # First deactivate
    tenant_repo.deactivate_tenant(tenant.tenant_id)
    
    # Then reactivate
    success = tenant_repo.reactivate_tenant(tenant.tenant_id)
    
    assert success is True
    
    # Verify tenant is active
    updated_tenant = session.query(TenantMaster).get(tenant.tenant_id)
    assert updated_tenant.is_active is True