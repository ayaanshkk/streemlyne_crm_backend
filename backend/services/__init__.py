"""
Services Package
Business logic layer for StreemLyne CRM

This package contains all service classes that implement business logic.
Services use repositories for data access and should NOT directly use models.

ARCHITECTURE:
Routes → Services → Repositories → Models → Database

Developer A (Foundation):
- TenantService: Tenant management and module assignment
- SubscriptionService: Subscription lifecycle and validation
- PermissionService: RBAC - roles, permissions, authorization
- EmployeeService: Employee management and user account creation

Developer B (Business Domains):
- ClientService: Client/customer management
- OpportunityService: Sales pipeline and opportunities
- ProjectService: Project tracking and management
- ProposalService: Proposal creation and approval
- InvoiceService: Invoice generation and billing

Existing (Keep as-is):
- Domain-specific services for interior design, education modules
"""

# ============================================================
# DEVELOPER A - FOUNDATION SERVICES (✅ IMPLEMENTED)
# ============================================================

from .tenant_service import TenantService
from .subscription_service import SubscriptionService
from .permission_service import PermissionService
from .employee_service import EmployeeService


# ============================================================
# DEVELOPER B - BUSINESS DOMAIN SERVICES (⏳ TO BE IMPLEMENTED)
# ============================================================
# DEVELOPER B - BUSINESS DOMAIN SERVICES (✅ IMPLEMENTED)
# ============================================================

from .invoice_service import InvoiceService
from .payment_service import PaymentService
from .dunning_service import DunningService
from .notification_service import NotificationService
from .subscription_management_service import SubscriptionManagementService

# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    # Developer A - Foundation Services
    'TenantService',
    'SubscriptionService',
    'PermissionService',
    'EmployeeService',

    # Developer B - Business Domain Services
    'InvoiceService',
    'PaymentService',
    'DunningService',
    'NotificationService',
    'SubscriptionManagementService',
]

# ============================================================
# HELPER FUNCTION FOR SERVICE AVAILABILITY
# ============================================================

def get_available_services():
    """
    Get list of available service names
    Useful for debugging and feature flags

    Returns:
    dict: Dictionary with service categories and their availability
    """
    return {
        'foundation': [
            'TenantService',
            'SubscriptionService',
            'PermissionService',
            'EmployeeService'
        ],
        'business_domain': [
            'InvoiceService',
            'PaymentService',
            'DunningService',
            'NotificationService',
            'SubscriptionManagementService',
        ],
        'domain_specific': [
            'CuttingListBuilder',
            'ManufacturingRules',
            'OCRDimensionExtractor',
            'ImagePreprocessor',
            'SectionAnalyzer',
            'SectionDetector'
        ]
    }
