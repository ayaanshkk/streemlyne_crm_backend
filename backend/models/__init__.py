# ============================================================
# STREEMLYNE CRM MODELS
# ============================================================
# 
# This package contains all SQLAlchemy models for the StreemLyne CRM.
# 
# SCHEMA STRUCTURE:
# - StreemLyne_MT: Main schema for new normalized tables (NEW)
# - Default schema: Legacy tables for backward compatibility (OLD)
#
# MODEL ORGANIZATION:
# - tenancy.py: Tenant, subscriptions, modules (NEW - StreemLyne_MT)
# - core.py: Clients, opportunities, projects, employees, users (NEW - StreemLyne_MT)
# - masters.py: Reference data (countries, currencies, etc.) (NEW - StreemLyne_MT)
# - core_proposals.py: Proposals and invoices (NEW - StreemLyne_MT)
# - core_documents.py: Documents, activities, chat (NEW/legacy mix)
# - modules/: Industry-specific modules (education, interior_design)
# - legacy/: Legacy models for backward compatibility only
#
# ============================================================


# ============================================================
# TENANCY MODELS - Multi-tenant Architecture
# ============================================================

from .tenancy import (
    TenantMaster,
    SubscriptionPlan,
    ModuleMaster,
    SubscriptionModuleMapping,
    TenantModuleMapping,
    TenantSubscription,
)


# ============================================================
# CORE BUSINESS MODELS - Main Entities
# ============================================================

from .core import (
    # Client Management
    ClientMaster,
    ClientInteractions,
    
    # Employee & User Management
    EmployeeMaster,
    UserMaster,
    UserRoleMapping,
    CustomerAuth,
    CustomerPasswordReset,
    
    # Opportunity & Project Management
    OpportunityDetails,
    ProjectDetails,
    
    # Documents
    CaseDocuments,
    CustomerDocuments,
    
    # Energy Contracts
    EnergyContractMaster,
)


# ============================================================
# MASTER DATA MODELS - Reference Tables
# ============================================================

from .masters import (
    CountryMaster,
    CurrencyMaster,
    DesignationMaster,
    ServicesMaster,
    UOMMaster,
    StageMaster,
    SupplierMaster,
    RoleMaster,
    PermissionCatalog,
    RolePermissionMapping,
)


# ============================================================
# PROPOSAL & INVOICE MODELS
# ============================================================

from .core_proposals import (
    ProposalMaster,
    ProposalDetails,
    InvoiceMaster,
    InvoiceDetails,
)


# ============================================================
# DOCUMENT & ACTIVITY MODELS
# ============================================================

from .core_documents import (
    Activity,
    OpportunityNote,
    DocumentTemplate,
    FormSubmission,
    CustomerFormData,
    DataImport,
    AuditLog,
    VersionedSnapshot,
    ChatConversation,
    ChatMessage,
    ChatHistory,
)


# ============================================================
# MODULE MODELS - Optional (Industry-Specific)
# ============================================================

# Education Module
try:
    from .modules.education import (
        TestResult, 
        Certificate, 
        TrainingBatch, 
        PTIForm
    )
    EDUCATION_MODULE_AVAILABLE = True
except ImportError:
    EDUCATION_MODULE_AVAILABLE = False
    TestResult = None
    Certificate = None
    TrainingBatch = None
    PTIForm = None

# Interior Design Module
try:
    from .modules.interior_design import (
        Project, 
        KitchenChecklist, 
        BedroomChecklist,
        MaterialOrder, 
        CuttingList, 
        ApplianceCatalog, 
        DrawingDocument,
        Drawing
    )
    INTERIOR_MODULE_AVAILABLE = True
except ImportError:
    INTERIOR_MODULE_AVAILABLE = False
    Project = None
    KitchenChecklist = None
    BedroomChecklist = None
    MaterialOrder = None
    CuttingList = None
    ApplianceCatalog = None
    DrawingDocument = None
    Drawing = None


# ============================================================
# LEGACY MODELS - Backward Compatibility Only
# ============================================================
# NOTE: Legacy models are available but should NOT be used for new development.
# They use the OLD schema (UUIDs, default schema).
# Import them only when needed for backward compatibility with existing routes.

LEGACY_MODELS_AVAILABLE = True  # Legacy models exist in the legacy/ folder


# ============================================================
# EXPORT ALL MODELS
# ============================================================

__all__ = [
    # Tenancy Models (NEW - StreemLyne_MT schema)
    'TenantMaster',
    'SubscriptionPlan',
    'ModuleMaster',
    'SubscriptionModuleMapping',
    'TenantModuleMapping',
    'TenantSubscription',
    
    # Core Business Models (NEW - StreemLyne_MT schema)
    'ClientMaster',
    'ClientInteractions',
    'EmployeeMaster',
    'UserMaster',
    'UserRoleMapping',
    'CustomerAuth',
    'CustomerPasswordReset',
    'OpportunityDetails',
    'ProjectDetails',
    'CaseDocuments',
    'CustomerDocuments',
    'EnergyContractMaster',
    
    # Master Data Models (NEW - StreemLyne_MT schema)
    'CountryMaster',
    'CurrencyMaster',
    'DesignationMaster',
    'ServicesMaster',
    'UOMMaster',
    'StageMaster',
    'SupplierMaster',
    'RoleMaster',
    'PermissionCatalog',
    'RolePermissionMapping',
    
    # Proposal & Invoice Models (NEW - StreemLyne_MT schema)
    'ProposalMaster',
    'ProposalDetails',
    'InvoiceMaster',
    'InvoiceDetails',
    
    # Document & Activity Models
    'Activity',
    'OpportunityNote',
    'DocumentTemplate',
    'FormSubmission',
    'CustomerFormData',
    'DataImport',
    'AuditLog',
    'VersionedSnapshot',
    'ChatConversation',
    'ChatMessage',
    'ChatHistory',
    
    # Module availability flags
    'EDUCATION_MODULE_AVAILABLE',
    'INTERIOR_MODULE_AVAILABLE',
    'LEGACY_MODELS_AVAILABLE',
]

# Add education models to exports if available
if EDUCATION_MODULE_AVAILABLE:
    __all__.extend([
        'TestResult', 'Certificate', 'TrainingBatch', 'PTIForm'
    ])

# Add interior design models to exports if available
if INTERIOR_MODULE_AVAILABLE:
    __all__.extend([
        'Project', 'KitchenChecklist', 'BedroomChecklist',
        'MaterialOrder', 'CuttingList', 'ApplianceCatalog', 'DrawingDocument',
        'Drawing'
    ])


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def is_module_available(module_name: str) -> bool:
    """
    Check if a module is available
    
    Args:
        module_name: 'education', 'interior_design', or 'legacy'
    
    Returns:
        bool: True if module is available
    """
    if module_name == 'education':
        return EDUCATION_MODULE_AVAILABLE
    elif module_name == 'interior_design':
        return INTERIOR_MODULE_AVAILABLE
    elif module_name == 'legacy':
        return LEGACY_MODELS_AVAILABLE
    return False


def get_available_modules() -> list:
    """
    Get list of available modules
    
    Returns:
        list: List of available module names
    """
    modules = []
    if EDUCATION_MODULE_AVAILABLE:
        modules.append('education')
    if INTERIOR_MODULE_AVAILABLE:
        modules.append('interior_design')
    if LEGACY_MODELS_AVAILABLE:
        modules.append('legacy')
    return modules


def get_new_schema_models() -> list:
    """
    Get list of models using the new StreemLyne_MT schema
    
    Returns:
        list: List of model class names using new schema
    """
    return [
        # Tenancy
        'TenantMaster', 'SubscriptionPlan', 'ModuleMaster',
        'SubscriptionModuleMapping', 'TenantModuleMapping', 'TenantSubscription',
        
        # Core
        'ClientMaster', 'ClientInteractions', 'EmployeeMaster', 'UserMaster',
        'UserRoleMapping', 'CustomerAuth', 'CustomerPasswordReset',
        'OpportunityDetails', 'ProjectDetails', 'CaseDocuments', 
        'CustomerDocuments', 'EnergyContractMaster',
        
        # Masters
        'CountryMaster', 'CurrencyMaster', 'DesignationMaster',
        'ServicesMaster', 'UOMMaster', 'StageMaster', 'SupplierMaster',
        'RoleMaster', 'PermissionCatalog', 'RolePermissionMapping',
        
        # Proposals
        'ProposalMaster', 'ProposalDetails', 'InvoiceMaster', 'InvoiceDetails',
    ]


def get_legacy_schema_models() -> list:
    """
    Get list of models using the legacy/default schema
    
    Returns:
        list: List of model class names using legacy schema
    """
    return [
        # Legacy Core
        'Tenant', 'User', 'LoginAttempt', 'Session',
        'Customer', 'Opportunity', 'Job',
        'Team', 'TeamMember', 'Salesperson', 'Assignment',
        
        # Legacy Proposals
        'Product', 'ProductCategory', 'Proposal', 'ProposalItem',
        'Invoice', 'InvoiceLineItem', 'Payment',
        
        # Legacy Documents
        'OpportunityDocument', 'Activity', 'OpportunityNote',
        'DocumentTemplate', 'FormSubmission', 'CustomerFormData',
        'DataImport', 'AuditLog', 'VersionedSnapshot',
        'ChatConversation', 'ChatMessage', 'ChatHistory',
    ]
