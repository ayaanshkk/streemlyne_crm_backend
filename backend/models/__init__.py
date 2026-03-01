"""
models/__init__.py  —  StreemLyne CRM Model Registry

SCHEMA STRUCTURE:
    StreemLyne_MT  — All tables (DDL-defined + app-level via migration)
    legacy/        — Old UUID-based tables kept for backward compatibility only

IMPORT ORDER (respects SQLAlchemy mapper dependency resolution):
    1. tenancy          — TenantMaster must exist before any FK that references it
    2. masters          — Lookup/reference tables (no FK to business models)
    3. core             — Core business models (Client, Employee, Opportunity, etc.)
    4. core_proposals   — Proposal + Invoice (depend on Client, Project, Services)
    5. core_documents   — Activities, Chat, Audit (depend on most of the above)

NOTE: The education and interior_design modules have been archived.
      Backup copies are in: models/_backup_modules/
      Do NOT re-import them here without restoring the module files first.
"""

# ── 1. Tenancy ────────────────────────────────────────────────────────────────
from .tenancy import (
    TenantMaster,
    SubscriptionPlan,
    ModuleMaster,
    SubscriptionModuleMapping,
    TenantModuleMapping,
    TenantSubscription,
)

# Backward-compatibility alias matching the SQL table name Subscription_Plans
SubscriptionPlans = SubscriptionPlan


# ── 2. Masters / Lookup Tables ───────────────────────────────────────────────
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


# ── 3. Core Business Models ──────────────────────────────────────────────────
from .core import (
    ClientMaster,
    ClientInteractions,
    EmployeeMaster,
    UserMaster,
    UserRoleMapping,
    CustomerAuth,
    CustomerPasswordReset,
    OpportunityDetails,
    ProjectDetails,
    CaseDocuments,
    CustomerDocuments,
    EnergyContractMaster,
)


# ── 4. Proposals & Invoices ──────────────────────────────────────────────────
from .core_proposals import (
    ProposalMaster,
    ProposalDetails,
    InvoiceMaster,
    InvoiceDetails,
)


# ── 5. Documents, Chat & Audit ───────────────────────────────────────────────
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


# ── Module availability flags ─────────────────────────────────────────────────
# Education and interior_design modules are archived — always False.
# Update these when modules are restored.
EDUCATION_MODULE_AVAILABLE = False
INTERIOR_MODULE_AVAILABLE = False
# Alias kept so any existing code referencing DRAWING_MODULE_AVAILABLE doesn't
# crash with ImportError (maps to the same archived module flag).
DRAWING_MODULE_AVAILABLE = False

# Legacy models live in models/legacy/ — import directly in routes that need them.
LEGACY_MODELS_AVAILABLE = True


# ── Public API ────────────────────────────────────────────────────────────────
__all__ = [
    # Tenancy (StreemLyne_MT DDL)
    'TenantMaster',
    'SubscriptionPlan',
    'SubscriptionPlans',
    'ModuleMaster',
    'SubscriptionModuleMapping',
    'TenantModuleMapping',
    'TenantSubscription',

    # Masters (StreemLyne_MT DDL)
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

    # Core (StreemLyne_MT DDL)
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

    # Proposals & Invoices (StreemLyne_MT DDL)
    'ProposalMaster',
    'ProposalDetails',
    'InvoiceMaster',
    'InvoiceDetails',

    # Documents, Chat & Audit (app-level — require Alembic migration)
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
    'DRAWING_MODULE_AVAILABLE',
    'LEGACY_MODELS_AVAILABLE',
]


# ── Helper Functions ──────────────────────────────────────────────────────────

def is_module_available(module_name: str) -> bool:
    """
    Check whether an optional module is currently active.

    Args:
        module_name: 'education' | 'interior_design' | 'legacy'

    Returns:
        bool — False for education and interior_design (both archived)
    """
    return {
        'education': EDUCATION_MODULE_AVAILABLE,
        'interior_design': INTERIOR_MODULE_AVAILABLE,
        'legacy': LEGACY_MODELS_AVAILABLE,
    }.get(module_name, False)


def get_available_modules() -> list:
    """
    Return names of all optional modules that are currently active.

    Returns:
        list[str]
    """
    modules = []
    if LEGACY_MODELS_AVAILABLE:
        modules.append('legacy')
    return modules


def get_new_schema_models() -> list:
    """
    Return class names of all models in the StreemLyne_MT schema.
    Includes both DDL-defined tables and app-level tables created via migration.

    Returns:
        list[str]
    """
    return [
        # Tenancy
        'TenantMaster', 'SubscriptionPlan', 'ModuleMaster',
        'SubscriptionModuleMapping', 'TenantModuleMapping', 'TenantSubscription',
        # Masters
        'CountryMaster', 'CurrencyMaster', 'DesignationMaster',
        'ServicesMaster', 'UOMMaster', 'StageMaster', 'SupplierMaster',
        'RoleMaster', 'PermissionCatalog', 'RolePermissionMapping',
        # Core
        'ClientMaster', 'ClientInteractions', 'EmployeeMaster', 'UserMaster',
        'UserRoleMapping', 'CustomerAuth', 'CustomerPasswordReset',
        'OpportunityDetails', 'ProjectDetails', 'CaseDocuments',
        'CustomerDocuments', 'EnergyContractMaster',
        # Proposals & Invoices
        'ProposalMaster', 'ProposalDetails', 'InvoiceMaster', 'InvoiceDetails',
        # Documents / Chat / Audit (app-level — require Alembic migration)
        'Activity', 'OpportunityNote', 'DocumentTemplate', 'FormSubmission',
        'CustomerFormData', 'DataImport', 'AuditLog', 'VersionedSnapshot',
        'ChatConversation', 'ChatMessage', 'ChatHistory',
    ]


def get_legacy_schema_models() -> list:
    """
    Return class names of models in the legacy/default schema (UUIDs).
    These live in models/legacy/ and exist only for backward compatibility.
    Remove entries as routes are migrated to new schema models.

    Returns:
        list[str]
    """
    return [
        'Tenant', 'User', 'LoginAttempt', 'Session',
        'Customer', 'Opportunity', 'Job',
        'Team', 'TeamMember', 'Salesperson', 'Assignment',
        'Product', 'ProductCategory', 'Proposal', 'ProposalItem',
        'Invoice', 'InvoiceLineItem', 'Payment',
        'OpportunityDocument',
    ]