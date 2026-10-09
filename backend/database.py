# Create a new file: database.py
# This will hold the database instance to avoid circular imports

import os

from flask_sqlalchemy import SQLAlchemy

# Postgres schema holding all StreemLyne + FAI tables (shared multi-tenant database)
DB_SCHEMA = os.getenv('DB_SCHEMA', 'streemLyne_mt_dev2')

db = SQLAlchemy()

def init_db(app):
    """Initialize the database with the Flask app"""
    db.init_app(app)
    return db