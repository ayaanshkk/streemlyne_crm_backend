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

from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool, create_engine
from alembic import context
import sys
import os
import logging

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ✅ Import Flask app and db
from app import app, db

# ✅ Import all models
from models import *

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger('alembic.env')

# ✅ Set target metadata from db (not models.db)
target_metadata = db.metadata


def run_migrations_offline():
    """
    Run migrations in 'offline' mode.
    Used when generating SQL scripts without database connection:
    alembic upgrade --sql 1234:5678 > migration.sql
    """
    with app.app_context():
        url = str(db.engine.url)
        context.configure(
            url=url,
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
            version_table_schema='StreemLyne_MT',
            render_as_batch=False,
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
        """Only include objects in StreemLyne_MT schema"""
        if type_ == "table":
            schema = getattr(object, 'schema', None)
            # Only include tables in StreemLyne_MT schema
            if schema != 'StreemLyne_MT':
                return False
                
            # Skip Alembic's own table
            if name == 'alembic_version':
                return False
        return True

    # ✅ Use Flask app's engine directly
    with app.app_context():
        connectable = db.engine

        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                process_revision_directives=process_revision_directives,
                version_table_schema='StreemLyne_MT',
                include_schemas=False,
                include_object=include_object,
            )

            with context.begin_transaction():
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()