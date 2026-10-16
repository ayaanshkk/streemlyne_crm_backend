"""
FAI (Forklift Academy of India) module inside the StreemLyne backend.

FAI's routes are served under /api/fai/... and use the normal StreemLyne
login token. Access is limited to tenants listed in FAI_TENANT_IDS
(see routes/auth_helpers.py).
"""

import logging
import os

logger = logging.getLogger(__name__)

URL_PREFIX = "/api/fai"


def register_fai(app):
    from .routes import (
        assignment_routes, auth_routes, calendar_routes, client_files_routes,
        company_enquiry_routes, company_interactions_routes, company_routes,
        company_training_routes, contact_files_routes, contact_interactions_routes,
        contact_routes, customer_routes, db_routes, file_routes, invoice_routes,
        job_routes, notification_routes, pipeline_routes, pricelist_routes,
        public_routes, quotation_routes, telegram_routes,
        tenant_routes, test_grading_routes,
    )

    blueprints = [
        auth_routes.auth_bp,
        contact_interactions_routes.contact_interactions_bp,
        contact_files_routes.contact_files_bp,
        customer_routes.customer_bp,
        pipeline_routes.pipeline_bp,
        db_routes.db_bp,
        notification_routes.notification_bp,
        assignment_routes.assignment_bp,
        file_routes.file_bp,
        job_routes.job_bp,
        test_grading_routes.test_grading_bp,
        tenant_routes.tenant_bp,
        calendar_routes.calendar_bp,
        client_files_routes.client_files_bp,
        pricelist_routes.pricelist_bp,
        invoice_routes.invoice_bp,
        company_routes.company_bp,
        contact_routes.contact_bp,
        company_enquiry_routes.company_enquiry_bp,
        company_interactions_routes.company_interactions_bp,
        company_training_routes.company_training_bp,
        quotation_routes.quotation_bp,
        telegram_routes.telegram_bp,
        public_routes.public_bp,
    ]

    for bp in blueprints:
        # Prefixed names keep FAI's blueprints from clashing with StreemLyne's
        # (both have "auth", "calendar", "invoice", ...).
        app.register_blueprint(
            bp,
            url_prefix=URL_PREFIX + (bp.url_prefix or ""),
            name=f"fai_{bp.name}",
        )

    # FAI's Proposals page is a copy of StreemLyne's and has no FAI backend
    # route; serve StreemLyne's (same login, same quotations table) under /fai.
    from routes.proposal_routes import proposal_bp
    app.register_blueprint(proposal_bp, url_prefix=URL_PREFIX + proposal_bp.url_prefix, name="fai_proposal")

    if os.getenv("TELEGRAM_BOT_TOKEN"):
        from .reminder_scheduler import start_scheduler
        start_scheduler()
    else:
        logger.info("FAI module: TELEGRAM_BOT_TOKEN not set, Telegram reminders are off")

    logger.info("FAI module registered under %s (%d blueprints)", URL_PREFIX, len(blueprints))
