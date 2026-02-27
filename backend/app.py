# app.py - Refactored for new StreemLyne_MT schema

from flask import Flask, request
from flask_cors import CORS
from flask_migrate import Migrate
import os
from database import db, init_db
from dotenv import load_dotenv

load_dotenv()


def create_app(test_config=None):
    app = Flask(__name__)

    app.config['SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'default-fallback-secret-key')

    CORS(
        app,
        resources={r"/api/*": {"origins": "*"}},
        supports_credentials=True,
        allow_headers=["Content-Type", "Authorization", "X-Requested-With", "X-Tenant-ID"],
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        expose_headers=["Content-Type", "Authorization"],
    )

    @app.before_request
    def handle_preflight():
        if request.method == "OPTIONS":
            response = app.make_default_options_response()
            h = response.headers
            h['Access-Control-Allow-Origin'] = '*'
            h['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
            h['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, X-Tenant-ID'
            h['Access-Control-Max-Age'] = '3600'
            return response

    if test_config:
        app.config.update(test_config)
    else:
        database_uri = os.getenv('DATABASE_URL')
        if not database_uri:
            raise ValueError("DATABASE_URL environment variable not set.")
        app.config['SQLALCHEMY_DATABASE_URI'] = database_uri
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads')
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

    for folder in ['uploads', 'generated_pdfs', 'generated_excel']:
        os.makedirs(os.path.join(basedir, folder), exist_ok=True)

    init_db(app)
    Migrate(app, db)

    print("📦 Loading models...")

    from models import (
        # Tenant & Auth
        TenantMaster,
        EmployeeMaster,
        DesignationMaster,
        UserMaster,
        CustomerAuth,
        CustomerPasswordReset,

        # Subscription & Modules
        SubscriptionPlan,
        TenantSubscription,
        ModuleMaster,
        TenantModuleMapping,
        SubscriptionModuleMapping,

        # RBAC
        RoleMaster,
        RolePermissionMapping,
        PermissionCatalog,
        UserRoleMapping,

        # CRM
        ClientMaster,
        ClientInteractions,
        OpportunityDetails,
        StageMaster,
        ProjectDetails,
        EnergyContractMaster,

        # Commercial
        ServicesMaster,
        SupplierMaster,
        ProposalMaster,
        ProposalDetails,
        InvoiceMaster,
        InvoiceDetails,
        UOMMaster,

        # Documents & Forms
        CaseDocuments,
        CustomerDocuments,
        CustomerFormData,

        # Master data
        CountryMaster,
        CurrencyMaster,

        # Chat (application-level, no schema table)
        ChatHistory,
        ChatConversation,
        ChatMessage,
    )

    from models import DRAWING_MODULE_AVAILABLE
    if DRAWING_MODULE_AVAILABLE:
        print("   ✅ Drawing Analyser module loaded")
        from models import Drawing, CuttingList
    else:
        print("   ⚠️  Drawing Analyser module not available")

    print("✅ All models loaded")

    print("📋 Registering blueprints...")

    from routes.auth_routes         import auth_bp
    from routes.tenant_routes       import tenant_bp
    from routes.subscription_routes import subscription_bp
    from routes.client_routes       import client_bp
    from routes.employee_routes     import employee_bp
    from routes.role_routes         import role_bp
    from routes.opportunity_routes  import opportunity_bp
    from routes.project_routes      import project_bp
    from routes.contract_routes     import contract_bp
    from routes.proposal_routes     import proposal_bp
    from routes.invoice_routes      import invoice_bp
    from routes.document_routes     import document_bp
    from routes.master_routes       import master_bp
    from routes.form_routes         import form_bp
    from routes.chat_routes         import chat_bp
    from routes.core_routes         import core_bp

    blueprints = [
        auth_bp, tenant_bp, subscription_bp,
        client_bp, employee_bp, role_bp,
        opportunity_bp, project_bp, contract_bp,
        proposal_bp, invoice_bp, document_bp,
        master_bp, form_bp, chat_bp, core_bp,
    ]

    if DRAWING_MODULE_AVAILABLE:
        from routes.drawing_analyser import drawing_bp
        blueprints.append(drawing_bp)

    for bp in blueprints:
        app.register_blueprint(bp)

    print("✅ All blueprints registered")

    print("\n" + "=" * 60)
    print("🚀 StreemLyne CRM Backend Starting...")
    print("=" * 60)
    print(f"{'🧪 Database: SQLite (Test Mode)' if test_config else '✅ Database: Supabase PostgreSQL'}")
    print("✅ Schema:   StreemLyne_MT")
    print("✅ CORS:     Enabled (all origins on /api/*)")
    print("✅ Auth:     JWT — staff (UserMaster) + portal (CustomerAuth)")
    print("✅ RBAC:     Role_Master / Permission_Catalog")
    if DRAWING_MODULE_AVAILABLE:
        print("✅ Module:   Drawing Analyser")
    print("=" * 60 + "\n")

    return app


app = create_app()

if __name__ == '__main__':
    with app.app_context():
        print("🌐 Running on http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)