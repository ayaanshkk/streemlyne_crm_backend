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

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
fileConfig(config.config_file_name)
logger = logging.getLogger('alembic.env')


# ============================================================================
# CRITICAL: Import all models here so Alembic can detect them
# ============================================================================

# Import all models from models package
# This ensures autogenerate can detect schema changes
from models import (
    # Tenancy models (Dev A)
    TenantMaster,
    TenantModuleMapping,
    TenantSubscription,
    
    # Master data models (Dev A)
    CountryMaster,
    CurrencyMaster,
    DesignationMaster,
    ServicesMaster,
    UOMMaster,
    StageMaster,
    SupplierMaster,
    
    # System configuration models (Dev A)
    ModuleMaster,
    SubscriptionPlans,
    SubscriptionModuleMapping,
    PermissionCatalog,
    RoleMaster,
    RolePermissionMapping,
    
    # Core models (Dev A + Dev B)
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

# Import any module-specific models
# from models.modules.education import *
# from models.modules.interior_design import *

# ============================================================================
# Flask-Migrate helper functions (keep existing)
# ============================================================================

def get_engine():
    """Get database engine from Flask-Migrate extension"""
    try:
        # this works with Flask-SQLAlchemy<3 and Alchemical
        return current_app.extensions['migrate'].db.get_engine()
    except (TypeError, AttributeError):
        # this works with Flask-SQLAlchemy>=3
        return current_app.extensions['migrate'].db.engine


def get_engine_url():
    """Get database URL from engine"""
    try:
        return get_engine().url.render_as_string(hide_password=False).replace(
            '%', '%%')
    except AttributeError:
        return str(get_engine().url).replace('%', '%%')


# Set database URL for Alembic
config.set_main_option('sqlalchemy.url', get_engine_url())

# Get database object from Flask-Migrate
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

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well. By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    
    USAGE:
    ------
    Used when generating SQL scripts without database connection:
    alembic upgrade --sql 1234:5678 > migration.sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, 
        target_metadata=get_metadata(), 
        literal_binds=True,
        # Supabase/PostgreSQL specific options
        render_as_batch=False,  # PostgreSQL supports transactional DDL
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """
    Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    
    USAGE:
    ------
    Normal migration execution:
    alembic upgrade head
    flask db upgrade
    """

    # this callback is used to prevent an auto-migration from being generated
    # when there are no changes to the schema
    # reference: http://alembic.zzzcomputing.com/en/latest/cookbook.html
    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, 'autogenerate', False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info('No changes in schema detected.')

    # NEW: filter objects (skip Supabase-internal tables / schemas)
    def include_object(object, name, type_, reflected, compare_to):
        """Only include objects in the public schema, ignore Supabase internal schemas"""
        if type_ == "table":
            # Skip tables from internal Supabase schemas
            schema = getattr(object, 'schema', None)
            if schema and schema != 'public':
                return False
            # Skip specific tables we don't manage
            skip_tables = {
                # Infrastructure - never touch/remove these
                'alembic_version',
                'tenant_domains',
                'tenant_supabase_config',
                # Old/unused tables - not sure if we have to remove, keep for now
                'quotes',
                'quote_line_items',
                # Dev B tables - not modelled yet, don't drop them, remove them from this list after you implement their models
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

            # Supabase/PostgreSQL specific options
            include_schemas=False,         # ← only include public schema
            include_object=include_object, # ← filter tables

            **conf_args
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()