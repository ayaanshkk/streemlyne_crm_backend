"""
Tenant Service
Business logic for tenant management
"""

from repositories import TenantRepository
from models import TenantMaster
from typing import List, Optional, Dict
from datetime import datetime, date


class TenantService:
    """Service for tenant business logic"""
    
    def __init__(self):
        self.repo = TenantRepository()
    
    def create_tenant(self, company_name: str, contact_name: str = None,
                     onboarding_date: date = None) -> TenantMaster:
        """
        Create a new tenant
        
        Args:
            company_name: Company name (must be unique)
            contact_name: Primary contact name
            onboarding_date: Date of onboarding
        
        Returns:
            Created TenantMaster instance
        
        Raises:
            ValueError: If company name already exists
        """
        # Check if company name already exists
        existing = self.repo.get_by_company_name(company_name)
        if existing:
            raise ValueError(f"Tenant with company name '{company_name}' already exists")
        
        # Create tenant
        tenant = TenantMaster(
            tenant_company_name=company_name,
            tenant_contact_name=contact_name,
            onboarding_Date=onboarding_date or date.today(),
            is_active=True
        )
        self.repo.session.add(tenant)
        self.repo.session.commit()
        
        return tenant
    
    def get_tenant(self, tenant_id: int) -> Optional[TenantMaster]:
        """Get tenant by ID"""
        return self.repo.session.query(TenantMaster).get(tenant_id)
    
    def get_all_active_tenants(self) -> List[TenantMaster]:
        """Get all active tenants"""
        return self.repo.get_active_tenants()
    
    def update_tenant(self, tenant_id: int, **updates) -> Optional[TenantMaster]:
        """
        Update tenant information
        
        Args:
            tenant_id: Tenant ID
            **updates: Fields to update
        
        Returns:
            Updated TenantMaster instance or None
        """
        tenant = self.get_tenant(tenant_id)
        if not tenant:
            return None
        
        for key, value in updates.items():
            if hasattr(tenant, key):
                setattr(tenant, key, value)
        
        tenant.updated_at = datetime.utcnow()
        self.repo.session.commit()
        return tenant
    
    def deactivate_tenant(self, tenant_id: int) -> bool:
        """Deactivate a tenant"""
        return self.repo.deactivate_tenant(tenant_id)
    
    def reactivate_tenant(self, tenant_id: int) -> bool:
        """Reactivate a tenant"""
        return self.repo.reactivate_tenant(tenant_id)
    
    def get_tenant_modules(self, tenant_id: int) -> List[int]:
        """Get list of module IDs enabled for tenant"""
        return self.repo.get_tenant_modules(tenant_id)
    
    def enable_module(self, tenant_id: int, module_id: int) -> bool:
        """
        Enable a module for a tenant
        
        Args:
            tenant_id: Tenant ID
            module_id: Module ID
        
        Returns:
            True if successful, False if already enabled
        """
        return self.repo.add_module_to_tenant(tenant_id, module_id)
    
    def disable_module(self, tenant_id: int, module_id: int) -> bool:
        """
        Disable a module for a tenant
        
        Args:
            tenant_id: Tenant ID
            module_id: Module ID
        
        Returns:
            True if successful, False if not found
        """
        return self.repo.remove_module_from_tenant(tenant_id, module_id)
    
    def has_module_access(self, tenant_id: int, module_id: int) -> bool:
        """Check if tenant has access to a module"""
        return self.repo.has_module_access(tenant_id, module_id)
    
    def get_tenant_statistics(self, tenant_id: int) -> Dict:
        """
        Get statistics for a tenant
        
        Args:
            tenant_id: Tenant ID
        
        Returns:
            Dictionary with statistics
        """
        from repositories import EmployeeRepository
        from models import TenantMaster
        
        tenant = self.get_tenant(tenant_id)
        if not tenant:
            return {}
        
        # Get employee count
        from flask import g
        g.tenant_id = tenant_id  # Set tenant context
        
        employee_repo = EmployeeRepository()
        employee_count = employee_repo.count(force_tenant=True)
        
        return {
            'tenant_id': tenant_id,
            'company_name': tenant.tenant_company_name,
            'is_active': tenant.is_active,
            'onboarding_date': tenant.onboarding_Date.isoformat() if tenant.onboarding_Date else None,
            'employee_count': employee_count,
            'enabled_modules': len(self.get_tenant_modules(tenant_id)),
            'created_at': tenant.created_at.isoformat() if tenant.created_at else None
        }