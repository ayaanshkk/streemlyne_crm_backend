"""
models/legacy/__init__.py  —  Legacy Model Registry

These models use the OLD database schema (UUID PKs, default PG schema).
DO NOT use them for new features.

Migration status guide:
    ✅ Migrated      — stop importing; use the new-schema model instead
    🔄 In progress   — route migration underway
    ❌ Not started   — still actively used by existing routes

Remove each export below as its corresponding route is migrated.
Target: retire this entire package before production launch.

Conflict note:
    Activity, OpportunityNote, DocumentTemplate, FormSubmission,
    CustomerFormData, DataImport, AuditLog, VersionedSnapshot,
    ChatConversation, ChatMessage, and ChatHistory are defined in
    core_documents.py (new schema) and are NOT re-exported here.
    If a legacy route still needs them, import directly from their
    new-schema module — they share the same table names.
"""

from .core_legacy import (
    # Enums
    STAGE_ENUM,
    CONTACT_MADE_ENUM,
    PREFERRED_CONTACT_ENUM,
    DOCUMENT_TEMPLATE_TYPE_ENUM,
    PAYMENT_METHOD_ENUM,
    AUDIT_ACTION_ENUM,
    ASSIGNMENT_TYPE_ENUM,
    # Core models
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
    # Helpers
    generate_job_reference,
)

from .core_proposals_legacy import (
    ProductCategory,
    Product,
    Proposal,
    ProposalItem,
    Invoice,
    InvoiceLineItem,
    Payment,
)

from .core_documents_legacy import (
    OpportunityDocument,
)


__all__ = [
    # Enums
    'STAGE_ENUM',
    'CONTACT_MADE_ENUM',
    'PREFERRED_CONTACT_ENUM',
    'DOCUMENT_TEMPLATE_TYPE_ENUM',
    'PAYMENT_METHOD_ENUM',
    'AUDIT_ACTION_ENUM',
    'ASSIGNMENT_TYPE_ENUM',

    # Core legacy models
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

    # Helpers
    'generate_job_reference',

    # Financial legacy models
    'ProductCategory',
    'Product',
    'Proposal',
    'ProposalItem',
    'Invoice',
    'InvoiceLineItem',
    'Payment',

    # Document legacy models
    'OpportunityDocument',
]