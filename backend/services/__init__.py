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

# Uncomment these imports as Developer B creates the services:

# from .client_service import ClientService
# from .opportunity_service import OpportunityService
# from .project_service import ProjectService
# from .proposal_service import ProposalService
# from .invoice_service import InvoiceService


# ============================================================
# EXISTING SERVICES (✅ KEEP AS-IS)
# ============================================================

# Domain-specific services for module functionality
from .cutting_list_builder import CuttingListBuilder
from .manufacturing_rules import ManufacturingRules
from .ocr_dimension_extractor import OCRDimensionExtractor
from .preprocessing import ImagePreprocessor
from .section_analyzer import SectionAnalyzer
from .section_detector import SectionDetector


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    # Developer A - Foundation Services
    'TenantService',
    'SubscriptionService',
    'PermissionService',
    'EmployeeService',
    
    # Developer B - Business Domain Services (add as implemented)
    # 'ClientService',
    # 'OpportunityService',
    # 'ProjectService',
    # 'ProposalService',
    # 'InvoiceService',
    
    # Existing Domain Services
    'CuttingListBuilder',
    'ManufacturingRules',
    'OCRDimensionExtractor',
    'ImagePreprocessor',
    'SectionAnalyzer',
    'SectionDetector',
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
            # Add as Developer B implements them
            # 'ClientService',
            # 'OpportunityService',
            # 'ProjectService',
            # 'ProposalService',
            # 'InvoiceService',
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
