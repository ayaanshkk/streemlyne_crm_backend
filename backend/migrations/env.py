"""
Alembic Migration Environment Configuration
Works with Flask-Migrate for StreemLyne CRM

IMPORTANT FOR REFACTOR:
-----------------------
This file has been updated to import ALL new models so that
Alembic can detect schema changes for autogenerate.

When you create new model files, you MUST import them in the
"Import all models" section below.
"""

import logging
from logging.config import fileConfig

from flask import current_app

from alembic import context

config = context.config

fileConfig(config.config_file_name)
logger = logging.getLogger('alembic.env')


# ============================================================================
# CRITICAL: Import all models here so Alembic can detect them
# ============================================================================

from models import (
    # Tenancy models
    TenantMaster,
    TenantModuleMapping,
    TenantSubscription,

    # Master data models
    CountryMaster,
    CurrencyMaster,
    DesignationMaster,
    ServicesMaster,
    UOMMaster,
    StageMaster,
    SupplierMaster,

    # System configuration models
    ModuleMaster,
    SubscriptionPlan,
    SubscriptionModuleMapping,
    PermissionCatalog,
    RoleMaster,
    RolePermissionMapping,

    # Core models
    EmployeeMaster,
    UserMaster,


    # Business models (Dev B - uncomment as they're created)
    # ClientMaster,
    # ClientInteractions,
    # OpportunityDetails,
    # ProjectDetails,
    # ProposalMaster,
    # ProposalDetails,
    # InvoiceMaster,
    # InvoiceDetails,
    # EnergyContractMaster,
)


# ============================================================================
# Flask-Migrate helper functions (keep existing)
# ============================================================================

def get_engine():
    """Get database engine from Flask-Migrate extension"""
    try:
        return current_app.extensions['migrate'].db.get_engine()
    except (TypeError, AttributeError):
        return current_app.extensions['migrate'].db.engine


def get_engine_url():
    """Get database URL from engine"""
    try:
        return get_engine().url.render_as_string(hide_password=False).replace(
            '%', '%%')
    except AttributeError:
        return str(get_engine().url).replace('%', '%%')


config.set_main_option('sqlalchemy.url', get_engine_url())

target_db = current_app.extensions['migrate'].db


def get_metadata():
    """
    Get metadata from database object

    This is where Alembic reads your model definitions to detect changes.
    All imported models above are included in this metadata.
    """
    if hasattr(target_db, 'metadatas'):
        return target_db.metadatas[None]
    return target_db.metadata


# ============================================================================
# Migration execution functions
# ============================================================================

def run_migrations_offline():
    """
    Run migrations in 'offline' mode.
    Used when generating SQL scripts without database connection:
    alembic upgrade --sql 1234:5678 > migration.sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=get_metadata(),
        literal_binds=True,
        render_as_batch=False,  # PostgreSQL supports transactional DDL
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """
    Run migrations in 'online' mode.
    Normal migration execution:
    alembic upgrade head
    flask db upgrade
    """

    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, 'autogenerate', False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info('No changes in schema detected.')

    def include_object(object, name, type_, reflected, compare_to):
        """Only include objects in the public schema, ignore Supabase internal schemas"""
        if type_ == "table":
            schema = getattr(object, 'schema', None)
            if schema and schema != 'public':
                return False
            skip_tables = {
                # Infrastructure - never touch/remove these
                'alembic_version',
                'tenant_domains',
                'tenant_supabase_config',
                # Old/unused tables
                'quotes',
                'quote_line_items',
                # Dev B tables - not modelled yet, don't drop them
                'client_master',
                'client_interactions',
                'energy_contract_master',
                'invoice_master',
                'invoice_details',
                'opportunity_details',
                'project_details',
                'proposal_master',
                'proposal_details',
                # OLD tables - never modify these via migration
                'tenants',
                'users',
                'jobs',
                'customers',
                'assignments',
                'teams',
                'team_members',
                'salespeople',
                'invoices',
                'invoice_line_items',
                'proposals',
                'proposal_items',
                'payments',
                'opportunities',
                'opportunity_documents',
                'opportunity_notes',
                'activities',
                'audit_logs',
                'login_attempts',
                'user_sessions',
                'chat_conversations',
                'chat_messages',
                'chat_history',
                'document_templates',
                'form_submissions',
                'customer_form_data',
                'data_imports',
                'versioned_snapshots',
                'products',
                'product_categories',
                'drawings',
                'cutting_lists',
                'education_certificates',
                'education_test_results',
                'education_training_batches',
                'education_pti_forms',
            }
            if name in skip_tables:
                return False
        return True

    conf_args = current_app.extensions['migrate'].configure_args
    if conf_args.get("process_revision_directives") is None:
        conf_args["process_revision_directives"] = process_revision_directives

    connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=get_metadata(),
            include_schemas=False,
            include_object=include_object,
            **conf_args
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()