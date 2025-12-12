# app.py - Updated with Flask-Migrate for database migrations

from flask import Flask
from flask_cors import CORS
from flask_migrate import Migrate
import os
from database import db, init_db
# ----------------------------------------------------
# New Import: Load environment variables from .env file
from dotenv import load_dotenv 

load_dotenv()
# ----------------------------------------------------


def create_app():
    app = Flask(__name__)
    
    # --- Configuration ---
    # Secret Key for session management and security
    # Fetches from .env or uses fallback
    app.config['SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'default-fallback-secret-key')
    
    # Configure CORS
    CORS(app, origins="*")
    
    # Database configuration: SWITCHING TO SUPABASE POSTGRESQL
    # -----------------------------------------------------------
    # Database URI is now solely pulled from the DATABASE_URL environment variable 
    # (which is loaded from .env)
    
    database_uri = os.getenv('DATABASE_URL')
    
    # Check if the database URI was successfully loaded
    if not database_uri:
        raise ValueError("DATABASE_URL environment variable not set. Please check your .env file.")
    
    app.config['SQLALCHEMY_DATABASE_URI'] = database_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # IMPORTANT: Install psycopg2-binary to connect to Postgres
    # pip install psycopg2-binary
    # -----------------------------------------------------------
    
    # Upload folder configuration
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['UPLOAD_FOLDER'] = 'uploads'
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

    # Create directories if they don't exist
    os.makedirs(os.path.join(basedir, app.config['UPLOAD_FOLDER']), exist_ok=True)
    os.makedirs(os.path.join(basedir, 'generated_pdfs'), exist_ok=True)
    os.makedirs(os.path.join(basedir, 'generated_excel'), exist_ok=True)
    
    # Initialize database
    init_db(app)
    
    # Initialize Flask-Migrate
    # This will now track migrations against the Supabase database
    migrate = Migrate(app, db)
    
    # Import and register blueprints (after app is created)
    from routes.job_routes import job_bp
    from routes.core_routes import core_bp
    from routes.db_routes import db_bp
    from routes.auth_routes import auth_bp
    from routes.form_routes import form_bp
    from routes.customer_routes import customer_bp
    app.register_blueprint(customer_bp)
    
    app.register_blueprint(job_bp)
    app.register_blueprint(core_bp)
    app.register_blueprint(db_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(form_bp)
    
    return app

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        # IMPORTANT: When setting up Flask-Migrate for the first time, 
        # you MUST run 'flask db init' first to create the migrations folder.
        # Then, use 'flask db migrate' and 'flask db upgrade'.
        # db.create_all() 
        print("Starting Flask application...")
    app.run(debug=True)