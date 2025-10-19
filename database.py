# Create a new file: database.py
# This will hold the database instance to avoid circular imports

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def init_db(app):
    """Initialize the database with the Flask app"""
    db.init_app(app)
    return db