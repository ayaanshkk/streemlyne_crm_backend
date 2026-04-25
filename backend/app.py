from flask import Flask
from flask_cors import CORS
from flask_migrate import Migrate
import os

from dotenv import load_dotenv

from config import Config
from database import db, init_db


load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def create_app(test_config=None):
    app = Flask(__name__)

    # Load config first so Stripe and related settings are available globally.
    app.config.from_object(Config)
    app.config["SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "default-fallback-secret-key")

    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": [
                    "http://localhost:3000",
                    "http://127.0.0.1:3000",
                    "http://localhost:3001",
                    "http://127.0.0.1:3001",
                ]
            }
        },
        allow_headers=["Content-Type", "Authorization", "X-Requested-With", "X-Tenant-ID"],
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        expose_headers=["Content-Type", "Authorization"],
        supports_credentials=True,
    )

    if test_config:
        app.config.update(test_config)
    else:
        database_uri = os.getenv("DATABASE_URL")
        if not database_uri:
            raise ValueError("DATABASE_URL environment variable not set.")
        app.config["SQLALCHEMY_DATABASE_URI"] = database_uri
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config["UPLOAD_FOLDER"] = os.path.join(basedir, "uploads")
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

    for folder in ["uploads", "generated_pdfs", "generated_excel"]:
        os.makedirs(os.path.join(basedir, folder), exist_ok=True)

    init_db(app)
    Migrate(app, db)

    def _start_subscription_scheduler(app_obj):
        """
        Background job: sweep time-based subscription transitions.

        This preserves the existing hourly expiry behavior while keeping the
        bootstrap code syntactically valid.
        """
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from datetime import datetime, timezone

            def expire_stale_trials():
                with app_obj.app_context():
                    from models import TenantSubscription

                    now = datetime.now(timezone.utc)
                    stale = (
                        db.session.query(TenantSubscription)
                        .filter(
                            TenantSubscription.status == "trialing",
                            TenantSubscription.trial_end_date < now,
                        )
                        .all()
                    )
                    ended_cancellations = (
                        db.session.query(TenantSubscription)
                        .filter(
                            TenantSubscription.cancel_at_period_end == True,
                            TenantSubscription.current_period_end.isnot(None),
                        )
                        .all()
                    )
                    ended_manual_periods = (
                        db.session.query(TenantSubscription)
                        .filter(
                            TenantSubscription.cancel_at_period_end == True,
                            TenantSubscription.current_period_end.is_(None),
                            TenantSubscription.subscription_end_date.isnot(None),
                        )
                        .all()
                    )

                    for sub in stale:
                        sub.status = "expired"
                        sub.is_active = False

                    ended = 0
                    for sub in ended_cancellations:
                        period_end = sub.current_period_end
                        if period_end.tzinfo is None:
                            period_end = period_end.replace(tzinfo=timezone.utc)
                        else:
                            period_end = period_end.astimezone(timezone.utc)

                        if now > period_end:
                            sub.status = "canceled"
                            sub.is_active = False
                            sub.auto_renew = False
                            sub.cancel_at_period_end = False
                            ended += 1

                    today = now.date()
                    for sub in ended_manual_periods:
                        if today > sub.subscription_end_date:
                            sub.status = "canceled"
                            sub.is_active = False
                            sub.auto_renew = False
                            sub.cancel_at_period_end = False
                            ended += 1

                    if stale or ended:
                        db.session.commit()
                        app_obj.logger.info(
                            "[SCHEDULER] Expired %s stale trial(s) and finalized %s cancellation(s)",
                            len(stale),
                            ended,
                        )

            def apply_scheduled_downgrades():
                with app_obj.app_context():
                    from services.subscription_management_service import SubscriptionManagementService

                    applied = SubscriptionManagementService().apply_scheduled_changes()
                    if applied:
                        app_obj.logger.info(
                            "[SCHEDULER] Applied %s scheduled downgrade(s)",
                            len(applied),
                        )

            def send_renewal_reminders():
                with app_obj.app_context():
                    from services.dunning_service import DunningService

                    notified = DunningService().send_renewal_reminders()
                    if notified:
                        app_obj.logger.info(
                            "[SCHEDULER] Sent %s renewal/trial reminder(s)",
                            len(notified),
                        )

            def check_expirations():
                with app_obj.app_context():
                    from services.dunning_service import DunningService

                    expired = DunningService().check_and_process_expirations()
                    if expired:
                        app_obj.logger.info(
                            "[SCHEDULER] Processed %s dunning expiration(s)",
                            len(expired),
                        )

            def process_retries():
                with app_obj.app_context():
                    from services.dunning_service import DunningService

                    results = DunningService().process_scheduled_retries()
                    succeeded = sum(1 for r in results if r.get("success"))
                    failed = len(results) - succeeded
                    if results:
                        app_obj.logger.info(
                            "[SCHEDULER] Processed %s scheduled retry/retries (%s succeeded, %s failed)",
                            len(results),
                            succeeded,
                            failed,
                        )

            scheduler = BackgroundScheduler(daemon=True)
            scheduler.add_job(
                expire_stale_trials,
                "interval",
                hours=1,
                id="expire_trials",
                replace_existing=True,
            )
            scheduler.add_job(
                apply_scheduled_downgrades,
                "cron",
                minute=0,
                id="apply_scheduled_downgrades",
                replace_existing=True,
            )
            scheduler.add_job(
                send_renewal_reminders,
                "cron",
                hour=9,
                minute=0,
                id="send_renewal_reminders",
                replace_existing=True,
            )
            scheduler.add_job(
                check_expirations,
                "cron",
                hour=10,
                minute=0,
                id="check_expirations",
                replace_existing=True,
            )
            scheduler.add_job(
                process_retries,
                "cron",
                hour=11,
                minute=0,
                id="process_retries",
                replace_existing=True,
            )
            scheduler.start()
            app_obj.logger.info("[SCHEDULER] Subscription maintenance jobs started")
        except ImportError:
            app_obj.logger.warning(
                "[SCHEDULER] apscheduler not installed - trial expiry sweep disabled. "
                "Run: pip install apscheduler"
            )

    _start_subscription_scheduler(app)
    print("[boot] Loading models...")

    from models import (
        ChatConversation,
        ChatHistory,
        ChatMessage,
        ClientInteractions,
        ClientMaster,
        ContactMethodMaster,
        CountryMaster,
        CurrencyMaster,
        CustomerAuth,
        CustomerDocuments,
        CustomerPasswordReset,
        DesignationMaster,
        DunningConfig,
        EmployeeMaster,
        EnergyContractMaster,
        InvoiceDetails,
        InvoiceMaster,
        ModuleMaster,
        NotificationLog,
        NotificationPreference,
        OpportunityDetails,
        PendingPlanChange,
        PermissionCatalog,
        ProjectDetails,
        ProposalDetails,
        ProposalMaster,
        RoleMaster,
        RolePermissionMapping,
        ServicesMaster,
        StageMaster,
        SubscriptionInvoice,
        SubscriptionModuleMapping,
        SubscriptionPause,
        SubscriptionPlan,
        SupplierMaster,
        TaxMaster,
        TenantModuleMapping,
        TenantSubscription,
        TenantMaster,
        UOMMaster,
        UserMaster,
        UserRoleMapping,
        CaseDocuments,
        PaymentAttempt,
        Assignment,
    )

    print("[ok] All models loaded")

    print("[boot] Registering blueprints...")
    from routes.ai_routes import ai_bp
    from routes.assignment_routes import assignment_bp
    from routes.auth_routes import auth_bp
    from routes.chat_routes import chat_bp
    from routes.client_routes import client_bp
    from routes.contract_routes import contract_bp
    from routes.core_routes import core_bp
    from routes.document_routes import document_bp
    from routes.employee_routes import employee_bp
    from routes.form_routes import form_bp
    from routes.invoice_routes import invoice_bp
    from routes.master_routes import master_bp
    from routes.opportunity_routes import opportunity_bp
    from routes.project_routes import project_bp
    from routes.proposal_routes import proposal_bp
    from routes.role_routes import role_bp
    from routes.subscription_routes import subscription_bp
    from routes.tenant_routes import tenant_bp

    blueprints = [
        auth_bp,
        tenant_bp,
        subscription_bp,
        client_bp,
        employee_bp,
        role_bp,
        opportunity_bp,
        project_bp,
        contract_bp,
        proposal_bp,
        invoice_bp,
        document_bp,
        master_bp,
        form_bp,
        chat_bp,
        core_bp,
        assignment_bp,
        ai_bp,
    ]

    for bp in blueprints:
        app.register_blueprint(bp, url_prefix=f"/api{bp.url_prefix}")

    print("[ok] All blueprints registered")

    print("\n[routes] Sample Registered Auth Routes:")
    for rule in app.url_map.iter_rules():
        if "auth" in str(rule) and "login" in str(rule):
            methods = ", ".join(sorted((rule.methods or set()) - {"HEAD", "OPTIONS"}))
            print(f"  -> [{methods}] {rule}")
    print()

    print("\n" + "=" * 60)
    print("StreemLyne CRM Backend Starting...")
    print("=" * 60)
    print(f"{'[test] Database: SQLite (Test Mode)' if test_config else '[ok] Database: Supabase PostgreSQL'}")
    print("[ok] Schema:   StreemLyne_MT")
    print("[ok] CORS:     Enabled (localhost:3000, 3001)")
    print("[ok] Auth:     JWT - staff (UserMaster) + portal (CustomerAuth)")
    print("[ok] RBAC:     Role_Master / Permission_Catalog")
    print("=" * 60 + "\n")

    return app


app = create_app()


if __name__ == "__main__":
    with app.app_context():
        print("Running on http://localhost:5000")
    app.run(debug=True, host="0.0.0.0", port=5000, use_reloader=False)
