"""
Tenant Repository
Handles tenant-related database operations
"""

from models import TenantMaster, TenantModuleMapping, TenantSubscription
from .base_repository import BaseRepository
from typing import List, Optional
from datetime import datetime


class TenantRepository(BaseRepository):
    """Repository for Tenant operations"""
    
    def __init__(self):
        super().__init__(TenantMaster)
    
    def get_by_company_name(self, company_name: str) -> Optional[TenantMaster]:
        """
        Find tenant by company name
        
        Args:
            company_name: Company name to search for
        
        Returns:
            TenantMaster instance or None
        """
        return self.session.query(TenantMaster).filter(
            TenantMaster.tenant_company_name == company_name
        ).first()
    
    def get_active_tenants(self) -> List[TenantMaster]:
        """
        Get all active tenants
        
        Returns:
            List of active TenantMaster instances
        """
        return self.session.query(TenantMaster).filter(
            TenantMaster.is_active == True
        ).all()
    
    def deactivate_tenant(self, tenant_id: int) -> bool:
        """
        Deactivate a tenant (soft delete)
        
        Args:
            tenant_id: Tenant ID to deactivate
        
        Returns:
            True if successful, False otherwise
        """
        tenant = self.session.query(TenantMaster).get(tenant_id)
        if tenant:
            tenant.is_active = False
            tenant.updated_at = datetime.utcnow()
            self.session.commit()
            return True
        return False
    
    def reactivate_tenant(self, tenant_id: int) -> bool:
        """
        Reactivate a tenant
        
        Args:
            tenant_id: Tenant ID to reactivate
        
        Returns:
            True if successful, False otherwise
        """
        tenant = self.session.query(TenantMaster).get(tenant_id)
        if tenant:
            tenant.is_active = True
            tenant.updated_at = datetime.utcnow()
            self.session.commit()
            return True
        return False
    
    # ============================================================
    # TENANT MODULE MAPPING
    # ============================================================
    
    def get_tenant_modules(self, tenant_id: int) -> List[int]:
        """
        Get list of module IDs enabled for a tenant
        
        Args:
            tenant_id: Tenant ID
        
        Returns:
            List of module IDs
        """
        mappings = self.session.query(TenantModuleMapping).filter(
            TenantModuleMapping.tenant_id == tenant_id
        ).all()
        return [m.module_id for m in mappings]
    
    def add_module_to_tenant(self, tenant_id: int, module_id: int) -> bool:
        """
        Enable a module for a tenant
        
        Args:
            tenant_id: Tenant ID
            module_id: Module ID to enable
        
        Returns:
            True if successful, False if already exists
        """
        # Check if already exists
        existing = self.session.query(TenantModuleMapping).filter(
            TenantModuleMapping.tenant_id == tenant_id,
            TenantModuleMapping.module_id == module_id
        ).first()
        
        if existing:
            return False
        
        mapping = TenantModuleMapping(
            tenant_id=tenant_id,
            module_id=module_id
        )
        self.session.add(mapping)
        self.session.commit()
        return True
    
    def remove_module_from_tenant(self, tenant_id: int, module_id: int) -> bool:
        """
        Disable a module for a tenant
        
        Args:
            tenant_id: Tenant ID
            module_id: Module ID to disable
        
        Returns:
            True if successful, False if not found
        """
        mapping = self.session.query(TenantModuleMapping).filter(
            TenantModuleMapping.tenant_id == tenant_id,
            TenantModuleMapping.module_id == module_id
        ).first()
        
        if mapping:
            self.session.delete(mapping)
            self.session.commit()
            return True
        return False
    
    def has_module_access(self, tenant_id: int, module_id: int) -> bool:
        """
        Check if tenant has access to a module
        
        Args:
            tenant_id: Tenant ID
            module_id: Module ID
        
        Returns:
            True if tenant has access, False otherwise
        """
        mapping = self.session.query(TenantModuleMapping).filter(
            TenantModuleMapping.tenant_id == tenant_id,
            TenantModuleMapping.module_id == module_id
        ).first()
        return mapping is not None
    
    # ============================================================
    # TENANT SUBSCRIPTION
    # ============================================================
    
    def get_active_subscription(self, tenant_id: int) -> Optional[TenantSubscription]:
        """
        Get tenant's active subscription
        
        Args:
            tenant_id: Tenant ID
        
        Returns:
            TenantSubscription instance or None
        """
        return self.session.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == tenant_id,
            TenantSubscription.is_active == True,
            TenantSubscription.subscription_end_date >= datetime.utcnow().date()
        ).first()
    
    def create_subscription(self, tenant_id: int, subscription_id: int,
                          start_date, end_date, auto_renew: bool = False) -> TenantSubscription:
        """
        Create a subscription for a tenant
        
        Args:
            tenant_id: Tenant ID
            subscription_id: Subscription plan ID
            start_date: Subscription start date
            end_date: Subscription end date
            auto_renew: Auto-renew flag
        
        Returns:
            Created TenantSubscription instance
        """
        subscription = TenantSubscription(
            tenant_id=tenant_id,
            subscription_id=subscription_id,
            subscription_start_date=start_date,
            subscription_end_date=end_date,
            is_active=True,
            auto_renew=auto_renew
        )
        self.session.add(subscription)
        self.session.commit()
        return subscription
    
    def cancel_subscription(self, tenant_id: int) -> bool:
        """
        Cancel tenant's active subscription
        
        Args:
            tenant_id: Tenant ID
        
        Returns:
            True if successful, False if no active subscription
        """
        subscription = self.get_active_subscription(tenant_id)
        if subscription:
            subscription.is_active = False
            subscription.updated_at = datetime.utcnow()
            self.session.commit()
            return True
        return False