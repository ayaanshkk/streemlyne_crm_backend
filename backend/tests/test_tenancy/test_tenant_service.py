"""
Test Tenant Service
Tests for TenantService business logic
"""

import pytest
from services import TenantService
from models import TenantMaster
from datetime import date


@pytest.fixture
def tenant_service():
    """Create tenant service instance"""
    return TenantService()


def test_create_tenant(session, tenant_service):
    """Test creating a tenant through service"""
    tenant = tenant_service.create_tenant(
        company_name='Service Test Company',
        contact_name='John Service',
        onboarding_date=date.today()
    )
    
    assert tenant.tenant_id is not None
    assert tenant.tenant_company_name == 'Service Test Company'
    assert tenant.is_active is True


def test_create_duplicate_tenant(session, tenant_service, tenant):
    """Test that creating duplicate tenant raises error"""
    with pytest.raises(ValueError) as excinfo:
        tenant_service.create_tenant(
            company_name='Test Company',  # Already exists
            contact_name='Duplicate'
        )
    
    assert 'already exists' in str(excinfo.value).lower()


def test_get_tenant(session, tenant_service, tenant):
    """Test getting a tenant"""
    result = tenant_service.get_tenant(tenant.tenant_id)
    
    assert result is not None
    assert result.tenant_id == tenant.tenant_id


def test_update_tenant(session, tenant_service, tenant):
    """Test updating tenant information"""
    updated = tenant_service.update_tenant(
        tenant.tenant_id,
        tenant_contact_name='Updated Contact'
    )
    
    assert updated is not None
    assert updated.tenant_contact_name == 'Updated Contact'


def test_get_tenant_statistics(session, tenant_service, tenant, employee):
    """Test getting tenant statistics"""
    stats = tenant_service.get_tenant_statistics(tenant.tenant_id)
    
    assert 'tenant_id' in stats
    assert 'company_name' in stats
    assert 'employee_count' in stats
    assert stats['employee_count'] >= 1  # At least the test employee