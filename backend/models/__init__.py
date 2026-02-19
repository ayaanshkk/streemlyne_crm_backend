"""
Models Package
Exports all database models for the StreemLyne CRM
"""

# ============================================================
# NEW SCHEMA - Tenancy Models
# ============================================================
from .tenancy import (
    TenantMaster,
    TenantModuleMapping,
    TenantSubscription
)

# ============================================================
# NEW SCHEMA - Master Data Models
# ============================================================
from .masters import (
    CountryMaster,
    CurrencyMaster,
    DesignationMaster,
    ServicesMaster,
    UOMMaster,
    StageMaster,
    SupplierMaster
)

# ============================================================
# NEW SCHEMA - System Configuration Models
# ============================================================
from .system import (
    ModuleMaster,
    SubscriptionPlans,
    SubscriptionModuleMapping,
    PermissionCatalog,
    RoleMaster,
    RolePermissionMapping
)

# ============================================================
# CORE MODELS - OLD + NEW
# ============================================================
from .core import (
    # OLD MODELS (keep for backward compatibility)
    Tenant,
    User,
    LoginAttempt,
    Session,
    Customer,
    Opportunity,
    Job,
    Team,
    TeamMember,
    Salesperson,
    Assignment,
    
    # NEW MODELS (aligned with new schema)
    EmployeeMaster,
    UserMaster,
    
    # Enums
    STAGE_ENUM,
    CONTACT_MADE_ENUM,
    PREFERRED_CONTACT_ENUM,
    DOCUMENT_TEMPLATE_TYPE_ENUM,
    PAYMENT_METHOD_ENUM,
    AUDIT_ACTION_ENUM,
    ASSIGNMENT_TYPE_ENUM,
    
    # Utilities
    generate_job_reference
)

# ============================================================
# PROPOSALS & FINANCIAL (keep existing)
# ============================================================
from .core_proposals import (
    Product,
    ProductCategory,
    Proposal,
    ProposalItem,
    Invoice,
    InvoiceLineItem,
    Payment
)

# ============================================================
# DOCUMENTS & ACTIVITIES (keep existing)
# ============================================================
from .core_documents import (
    OpportunityDocument,
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
    ChatHistory
)

# ============================================================
# MODULE MODELS - Optional (Industry-Specific)
# ============================================================
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
# EXPORT ALL
# ============================================================
__all__ = [
    # Tenancy
    'TenantMaster',
    'TenantModuleMapping',
    'TenantSubscription',
    
    # Master Data
    'CountryMaster',
    'CurrencyMaster',
    'DesignationMaster',
    'ServicesMaster',
    'UOMMaster',
    'StageMaster',
    'SupplierMaster',
    
    # System Configuration
    'ModuleMaster',
    'SubscriptionPlans',
    'SubscriptionModuleMapping',
    'PermissionCatalog',
    'RoleMaster',
    'RolePermissionMapping',
    
    # Core - OLD (backward compatibility)
    'Tenant',
    'User',
    'LoginAttempt',
    'Session',
    'Customer',
    'Opportunity',
    'Job',
    'Team',
    'TeamMember',
    'Salesperson',
    'Assignment',
    
    # Core - NEW
    'EmployeeMaster',
    'UserMaster',
    
    # Enums
    'STAGE_ENUM',
    'CONTACT_MADE_ENUM',
    'PREFERRED_CONTACT_ENUM',
    'DOCUMENT_TEMPLATE_TYPE_ENUM',
    'PAYMENT_METHOD_ENUM',
    'AUDIT_ACTION_ENUM',
    'ASSIGNMENT_TYPE_ENUM',
    
    # Financial
    'Product',
    'ProductCategory',
    'Proposal',
    'ProposalItem',
    'Invoice',
    'InvoiceLineItem',
    'Payment',
    
    # Documents
    'OpportunityDocument',
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
    
    # Utilities
    'generate_job_reference',
    
    # Module flags
    'EDUCATION_MODULE_AVAILABLE',
    'INTERIOR_MODULE_AVAILABLE',
]

# Add module models to exports if available
if EDUCATION_MODULE_AVAILABLE:
    __all__.extend(['TestResult', 'Certificate', 'TrainingBatch', 'PTIForm'])

if INTERIOR_MODULE_AVAILABLE:
    __all__.extend([
        'Project', 'KitchenChecklist', 'BedroomChecklist',
        'MaterialOrder', 'CuttingList', 'ApplianceCatalog',
        'DrawingDocument', 'Drawing'
    ])


def is_module_available(module_name: str) -> bool:
    """Check if a module is available"""
    if module_name == 'education':
        return EDUCATION_MODULE_AVAILABLE
    elif module_name == 'interior_design':
        return INTERIOR_MODULE_AVAILABLE
    return False


def get_available_modules() -> list:
    """Get list of available module names"""
    modules = []
    if EDUCATION_MODULE_AVAILABLE:
        modules.append('education')
    if INTERIOR_MODULE_AVAILABLE:
        modules.append('interior_design')
    return modules