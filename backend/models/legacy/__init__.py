# C:\streemlyne_crm_backend\backend\models\legacy\__init__.py
"""
Legacy System A models — UUID-based, being deprecated.
Do NOT import from here for new features.
Remove each export as its corresponding route is migrated to System B.
Target: empty this file before production launch.

NOTE: This folder contains models using the OLD database schema (UUIDs, default schema).
The NEW schema models are in the parent models directory (SmallInteger IDs, StreemLyne_MT schema).
"""

from .core_legacy import (
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
    generate_job_reference,
    STAGE_ENUM,
    CONTACT_MADE_ENUM,
    PREFERRED_CONTACT_ENUM,
    DOCUMENT_TEMPLATE_TYPE_ENUM,
    PAYMENT_METHOD_ENUM,
    AUDIT_ACTION_ENUM,
    ASSIGNMENT_TYPE_ENUM,
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

# NOTE: Activity, OpportunityNote, DocumentTemplate, etc. are defined
# in core_documents_legacy.py but NOT imported here to avoid table name
# conflicts with the new core_documents.py models.
#
# If you need these legacy models, import directly:
# from models.legacy.core_documents_legacy import Activity as LegacyActivity

__all__ = [
    # System A Core
    'Tenant', 'User', 'LoginAttempt', 'Session',
    'Customer', 'Opportunity', 'Job',
    'Team', 'TeamMember', 'Salesperson', 'Assignment',
    'generate_job_reference',
    # Enums
    'STAGE_ENUM', 'CONTACT_MADE_ENUM', 'PREFERRED_CONTACT_ENUM',
    'DOCUMENT_TEMPLATE_TYPE_ENUM', 'PAYMENT_METHOD_ENUM',
    'AUDIT_ACTION_ENUM', 'ASSIGNMENT_TYPE_ENUM',
    # Financials
    'ProductCategory', 'Product',
    'Proposal', 'ProposalItem',
    'Invoice', 'InvoiceLineItem',
    'Payment',
    # Documents
    'OpportunityDocument',
]