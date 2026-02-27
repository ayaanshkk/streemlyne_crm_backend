"""
Subscription Service
Business logic for subscription management
"""

from repositories import TenantRepository, PermissionRepository
from models import TenantSubscription, SubscriptionPlan
from typing import Optional, List, Dict
from datetime import date, datetime
from dateutil.relativedelta import relativedelta


class SubscriptionService:
    """Service for subscription business logic"""
    
    def __init__(self):
        self.tenant_repo = TenantRepository()
        self.permission_repo = PermissionRepository()
    
    def get_active_subscription(self, tenant_id: int) -> Optional[TenantSubscription]:
        """Get tenant's active subscription"""
        return self.tenant_repo.get_active_subscription(tenant_id)
    
    def get_subscription_plan(self, subscription_id: int) -> Optional[SubscriptionPlan]:
        """Get subscription plan details"""
        return self.tenant_repo.session.query(SubscriptionPlan).get(subscription_id)
    
    def get_all_plans(self) -> List[SubscriptionPlan]:
        """Get all available subscription plans"""
        return self.permission_repo.get_active_subscription_plans()
    
    def create_subscription(self, tenant_id: int, subscription_code: str,
                          auto_renew: bool = False) -> TenantSubscription:
        """
        Create a new subscription for a tenant
        
        Args:
            tenant_id: Tenant ID
            subscription_code: Subscription plan code
            auto_renew: Enable auto-renewal
        
        Returns:
            Created TenantSubscription instance
        
        Raises:
            ValueError: If subscription code not found or tenant already has active subscription
        """
        # Check if tenant already has active subscription
        existing = self.get_active_subscription(tenant_id)
        if existing:
            raise ValueError("Tenant already has an active subscription")
        
        # Get subscription plan
        plan = self.permission_repo.get_subscription_by_code(subscription_code)
        if not plan:
            raise ValueError(f"Subscription plan '{subscription_code}' not found")
        
        if not plan.is_active:
            raise ValueError(f"Subscription plan '{subscription_code}' is not active")
        
        # Calculate dates
        start_date = date.today()
        
        # Billing cycle: 1=Monthly, 12=Yearly
        if plan.billing_cycle == 1:
            end_date = start_date + relativedelta(months=1)
        elif plan.billing_cycle == 12:
            end_date = start_date + relativedelta(years=1)
        else:
            end_date = start_date + relativedelta(months=plan.billing_cycle)
        
        # Create subscription
        subscription = self.tenant_repo.create_subscription(
            tenant_id=tenant_id,
            subscription_id=plan.subscription_id,
            start_date=start_date,
            end_date=end_date,
            auto_renew=auto_renew
        )
        
        # Enable modules included in subscription
        modules = self.permission_repo.get_subscription_modules(plan.subscription_id)
        for module in modules:
            self.tenant_repo.add_module_to_tenant(tenant_id, module.module_id)
        
        return subscription
    
    def cancel_subscription(self, tenant_id: int) -> bool:
        """
        Cancel tenant's active subscription
        
        Args:
            tenant_id: Tenant ID
        
        Returns:
            True if successful, False if no active subscription
        """
        return self.tenant_repo.cancel_subscription(tenant_id)
    
    def renew_subscription(self, tenant_id: int) -> Optional[TenantSubscription]:
        """
        Renew tenant's subscription
        
        Args:
            tenant_id: Tenant ID
        
        Returns:
            New TenantSubscription instance or None
        
        Raises:
            ValueError: If no active subscription found
        """
        # Get current subscription
        current = self.get_active_subscription(tenant_id)
        if not current:
            raise ValueError("No active subscription found to renew")
        
        # Cancel current subscription
        self.cancel_subscription(tenant_id)
        
        # Get subscription plan
        plan = self.get_subscription_plan(current.subscription_id)
        if not plan:
            return None
        
        # Create new subscription
        return self.create_subscription(
            tenant_id=tenant_id,
            subscription_code=plan.subscription_code,
            auto_renew=current.auto_renew
        )
    
    def check_subscription_status(self, tenant_id: int) -> Dict:
        """
        Check subscription status and details
        
        Args:
            tenant_id: Tenant ID
        
        Returns:
            Dictionary with subscription status
        """
        subscription = self.get_active_subscription(tenant_id)
        
        if not subscription:
            return {
                'has_subscription': False,
                'is_active': False,
                'message': 'No active subscription'
            }
        
        plan = self.get_subscription_plan(subscription.subscription_id)
        days_remaining = (subscription.subscription_end_date - date.today()).days
        
        return {
            'has_subscription': True,
            'is_active': subscription.is_active,
            'plan_name': plan.subscription_name if plan else 'Unknown',
            'plan_code': plan.subscription_code if plan else None,
            'start_date': subscription.subscription_start_date.isoformat(),
            'end_date': subscription.subscription_end_date.isoformat(),
            'days_remaining': days_remaining,
            'auto_renew': subscription.auto_renew,
            'is_expiring_soon': days_remaining <= 7,
            'is_expired': days_remaining < 0
        }
    
    def can_access_module(self, tenant_id: int, module_code: str) -> bool:
        """
        Check if tenant can access a module based on subscription
        
        Args:
            tenant_id: Tenant ID
            module_code: Module code to check
        
        Returns:
            True if tenant can access module, False otherwise
        """
        # Check subscription status
        subscription = self.get_active_subscription(tenant_id)
        if not subscription:
            return False
        
        # Check if subscription is expired
        if subscription.subscription_end_date < date.today():
            return False
        
        # Get module
        module = self.permission_repo.get_module_by_code(module_code)
        if not module:
            return False
        
        # Check if module is enabled for tenant
        return self.tenant_repo.has_module_access(tenant_id, module.module_id)