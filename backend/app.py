# app.py - Updated with new models structure and Flask-Migrate

from flask import Flask, request
from flask_cors import CORS
from flask_migrate import Migrate
import os
import re
from database import db, init_db

# Load environment variables from .env file
from dotenv import load_dotenv 
load_dotenv()


def create_app():
    app = Flask(__name__)
    
    # --- Configuration ---
    app.config['SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'default-fallback-secret-key')
    
    # ✅ CORS Configuration - UPDATED
    CORS(app,
         resources={r"/api/*": {"origins": "*"}},
         supports_credentials=True,
         allow_headers=["Content-Type", "Authorization", "X-Requested-With", "X-Tenant-ID"],
         methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
         expose_headers=["Content-Type", "Authorization"],
    )
    
    # Handle OPTIONS requests explicitly
    @app.before_request
    def handle_preflight():
        if request.method == "OPTIONS":
            response = app.make_default_options_response()
            headers = response.headers
            headers['Access-Control-Allow-Origin'] = '*'
            headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
            headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, X-Tenant-ID'  # ✅ ADD X-Tenant-ID
            headers['Access-Control-Max-Age'] = '3600'
            return response
    
    # Database Configuration - Supabase PostgreSQL
    database_uri = os.getenv('DATABASE_URL')
    
    if not database_uri:
        raise ValueError("DATABASE_URL environment variable not set. Please check your .env file.")
    
    app.config['SQLALCHEMY_DATABASE_URI'] = database_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
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
    migrate = Migrate(app, db)
    
    # ============================================================
    # 🎯 NEW: Import all models to ensure they're registered with SQLAlchemy
    # ============================================================
    # This is crucial! Flask-Migrate needs all models imported before it can track them
    
    print("📦 Loading models...")
    
    # Import all core models
    from models import (
        # Core Models
        Tenant, User, LoginAttempt, Session,
        Customer, Opportunity, Job,
        Team, TeamMember, Salesperson,
        Assignment,
        
        # Financial Models
        Product, ProductCategory,
        Proposal, ProposalItem,
        Invoice, InvoiceLineItem,
        Payment,
        
        # Document Models
        OpportunityDocument, Activity, OpportunityNote,
        DocumentTemplate, FormSubmission, CustomerFormData,
        DataImport, AuditLog, VersionedSnapshot,
        
        # Chat Models
        ChatConversation, ChatMessage, ChatHistory,
        
        # Utilities
        generate_job_reference,
        
        # Module availability flags
        EDUCATION_MODULE_AVAILABLE,
        INTERIOR_MODULE_AVAILABLE,
    )
    
    # Import education module models if available
    if EDUCATION_MODULE_AVAILABLE:
        print("   ✅ Education module loaded")
        from models import TestResult, Certificate, TrainingBatch, PTIForm
    else:
        print("   ⚠️  Education module not available")
    
    # Import interior design module models if available
    if INTERIOR_MODULE_AVAILABLE:
        print("   ✅ Interior Design module loaded")
        from models import (
            Project, KitchenChecklist, BedroomChecklist,
            MaterialOrder, CuttingList, ApplianceCatalog, DrawingDocument
        )
    else:
        print("   ⚠️  Interior Design module not available")
    
    print("✅ All models loaded successfully")
    
    # ============================================================
    # Register Blueprints
    # ============================================================
    
    print("📋 Registering blueprints...")
    
    from routes.job_routes import job_bp
    from routes.core_routes import core_bp
    from routes.db_routes import db_bp
    from routes.auth_routes import auth_bp
    from routes.form_routes import form_bp
    from routes.customer_routes import customer_bp
    from routes.assignment_routes import assignment_bp
    from routes.chat_routes import chat_bp
    from routes.tenant_routes import tenant_bp
    from routes.drawing_analyser import drawing_bp

    app.register_blueprint(customer_bp)
    app.register_blueprint(job_bp)
    app.register_blueprint(core_bp)
    app.register_blueprint(db_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(form_bp)
    app.register_blueprint(assignment_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(tenant_bp)
    app.register_blueprint(drawing_bp)  # NEW - Drawing Analyser Blueprint

    print("✅ Drawing Analyser routes registered")
    print("✅ All blueprints registered")
    
    # ============================================================
    # Print Configuration Summary
    # ============================================================
    
    print("\n" + "="*60)
    print("🚀 StreemLyne CRM Backend Starting...")
    print("="*60)
    print("✅ CORS enabled for: localhost (all ports) and Vercel (*.vercel.app)")
    print("✅ Database: Supabase PostgreSQL")
    print("✅ Multi-tenant: Enabled")
    print("✅ Industry Templates: Enabled")
    if EDUCATION_MODULE_AVAILABLE:
        print("✅ Education Module: Available")
    if INTERIOR_MODULE_AVAILABLE:
        print("✅ Interior Design Module: Available")
    print("="*60 + "\n")
    
    return app


# ============================================================
# Create Flask App Instance
# ============================================================

app = create_app()


# ============================================================
# Main Entry Point
# ============================================================

if __name__ == '__main__':
    with app.app_context():
        # IMPORTANT: Flask-Migrate Commands
        # ----------------------------------
        # First time setup:
        #   1. flask db init          (creates migrations folder)
        #   2. flask db migrate -m "Initial migration"  (detects all models)
        #   3. flask db upgrade       (applies migration to database)
        #
        # After model changes:
        #   1. flask db migrate -m "Add custom_data columns"
        #   2. flask db upgrade
        #
        # DO NOT USE db.create_all() when using Flask-Migrate!
        # ----------------------------------
        
        print("\n🌐 Backend running on: http://localhost:5000")
        print("📝 API documentation: http://localhost:5000/api/docs (if available)")
        print("💡 Press CTRL+C to stop\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)