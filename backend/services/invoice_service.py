"""
Invoice Service
Handles subscription invoice generation and PDF creation.

Part of the Subscription Module Implementation Plan - Phase 1 (HIGH PRIORITY)
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Optional, List, Dict

from database import db
from models import (
    SubscriptionInvoice,
    TenantSubscription,
    SubscriptionPlan,
    CurrencyMaster,
    TenantMaster,
)


class InvoiceService:
    """Service for subscription invoice business logic."""

    INVOICE_NUMBER_PREFIX = "SUB-INV"

    def __init__(self):
        pass

    def create_invoice(
        self,
        tenant_id: str,
        subscription: TenantSubscription,
        stripe_invoice_id: Optional[str] = None,
        amount: Optional[float] = None,
        tax_amount: Optional[float] = None,
        currency_id: Optional[int] = None,
        status: str = "pending",
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
        due_date: Optional[date] = None,
    ) -> SubscriptionInvoice:
        """
        Create a new subscription invoice.

        Args:
            tenant_id: The tenant's unique identifier
            subscription: The TenantSubscription record
            stripe_invoice_id: Stripe invoice ID if applicable
            amount: Subtotal amount (defaults to plan price)
            tax_amount: Tax amount (defaults to 0)
            currency_id: Currency ID (defaults to plan's currency)
            status: Invoice status (pending, paid, failed, void)
            period_start: Billing period start date
            period_end: Billing period end date
            due_date: Payment due date

        Returns:
            The created SubscriptionInvoice record
        """
        plan = subscription.subscription
        if plan is None:
            raise ValueError("Subscription has no associated plan")

        invoice_number = self._generate_invoice_number(tenant_id)
        subtotal = amount if amount is not None else float(plan.price or 0)
        tax_total = tax_amount if tax_amount is not None else 0
        total = subtotal + tax_total

        invoice = SubscriptionInvoice(
            tenant_id=tenant_id,
            subscription_id=subscription.tenant_subscription_mapping_id,
            stripe_invoice_id=stripe_invoice_id,
            stripe_subscription_id=subscription.stripe_subscription_id,
            invoice_number=invoice_number,
            amount=subtotal,
            amount_paid=int(round(total * 100)) if status == "paid" else None,
            tax_amount=tax_total,
            total_amount=total,
            currency_id=currency_id or plan.currency_id,
            stripe_currency=plan.currency.currency_code.lower() if plan.currency else None,
            status=status,
            invoice_date=datetime.now(timezone.utc),
            period_start=period_start,
            period_end=period_end,
            due_date=due_date,
        )

        db.session.add(invoice)
        db.session.flush()

        return invoice

    def create_or_update_from_stripe_invoice(
        self,
        tenant_id: str,
        subscription: TenantSubscription,
        stripe_invoice: Dict,
        *,
        status: Optional[str] = None,
    ) -> SubscriptionInvoice:
        """
        Mirror a Stripe invoice into SubscriptionInvoice.

        Existing records are updated in place using stripe_invoice_id as the
        stable key so webhook retries remain idempotent.
        """
        stripe_invoice_id = stripe_invoice.get("id")
        existing = (
            self.get_invoice_by_stripe_id(stripe_invoice_id)
            if stripe_invoice_id
            else None
        )

        period_start = period_end = None
        lines = stripe_invoice.get("lines", {}).get("data", [])
        if lines:
            period = lines[0].get("period", {})
            if period.get("start"):
                period_start = datetime.fromtimestamp(period["start"], tz=timezone.utc).date()
            if period.get("end"):
                period_end = datetime.fromtimestamp(period["end"], tz=timezone.utc).date()

        amount = float(stripe_invoice.get("subtotal", 0)) / 100
        tax_amount = float(stripe_invoice.get("tax", 0) or 0) / 100
        total_amount = float(stripe_invoice.get("amount_paid") or stripe_invoice.get("amount_due") or stripe_invoice.get("total") or 0) / 100
        amount_paid = stripe_invoice.get("amount_paid")
        invoice_currency = stripe_invoice.get("currency")
        invoice_date = None
        if stripe_invoice.get("created"):
            invoice_date = datetime.fromtimestamp(stripe_invoice["created"], tz=timezone.utc)
        due_date = None
        if stripe_invoice.get("due_date"):
            due_date = datetime.fromtimestamp(stripe_invoice["due_date"], tz=timezone.utc).date()

        invoice_status = status or stripe_invoice.get("status") or "pending"
        if invoice_status == "open":
            invoice_status = "pending"

        if existing:
            existing.subscription_id = subscription.tenant_subscription_mapping_id
            existing.stripe_subscription_id = stripe_invoice.get("subscription") or subscription.stripe_subscription_id
            existing.amount = amount
            existing.amount_paid = amount_paid
            existing.tax_amount = tax_amount
            existing.total_amount = total_amount
            existing.currency_id = existing.currency_id or subscription.subscription.currency_id
            existing.stripe_currency = invoice_currency
            existing.status = invoice_status
            existing.invoice_date = invoice_date
            existing.period_start = period_start
            existing.period_end = period_end
            existing.due_date = due_date
            existing.updated_at = datetime.utcnow()
            return existing

        invoice = self.create_invoice(
            tenant_id=tenant_id,
            subscription=subscription,
            stripe_invoice_id=stripe_invoice_id,
            amount=amount,
            tax_amount=tax_amount,
            currency_id=subscription.subscription.currency_id if subscription.subscription else 1,
            status=invoice_status,
            period_start=period_start,
            period_end=period_end,
            due_date=due_date,
        )

        invoice_number = stripe_invoice.get("number")
        if invoice_number:
            invoice.invoice_number = invoice_number
        invoice.stripe_subscription_id = stripe_invoice.get("subscription") or subscription.stripe_subscription_id
        invoice.amount_paid = amount_paid
        invoice.stripe_currency = invoice_currency
        invoice.invoice_date = invoice_date

        return invoice

    def _generate_invoice_number(self, tenant_id: str) -> str:
        """
        Generate a unique invoice number for the tenant.
        Format: SUB-INV-{tenant_slug}-{YYYYMM}-{sequence}
        """
        year_month = datetime.now(timezone.utc).strftime("%Y%m")

        existing = (
            db.session.query(SubscriptionInvoice.invoice_number)
            .filter(
                SubscriptionInvoice.tenant_id == tenant_id,
                SubscriptionInvoice.invoice_number.like(f"{self.INVOICE_NUMBER_PREFIX}-{tenant_id}-{year_month}%"),
            )
            .order_by(SubscriptionInvoice.invoice_id.desc())
            .first()
        )

        if existing:
            last_number = existing[0]
            try:
                seq_part = int(last_number.split("-")[-1])
                next_seq = seq_part + 1
            except (ValueError, IndexError):
                next_seq = 1
        else:
            next_seq = 1

        return f"{self.INVOICE_NUMBER_PREFIX}-{tenant_id}-{year_month}-{next_seq:04d}"

    def get_invoice(self, invoice_id: int) -> Optional[SubscriptionInvoice]:
        """Get an invoice by ID."""
        return db.session.get(SubscriptionInvoice, invoice_id)

    def get_invoice_by_stripe_id(self, stripe_invoice_id: str) -> Optional[SubscriptionInvoice]:
        """Get an invoice by Stripe invoice ID."""
        return (
            db.session.query(SubscriptionInvoice)
            .filter_by(stripe_invoice_id=stripe_invoice_id)
            .first()
        )

    def list_invoices(
        self,
        tenant_id: str,
        page: int = 1,
        per_page: int = 20,
        status: Optional[str] = None,
    ) -> Dict:
        """
        List invoices for a tenant with pagination.

        Args:
            tenant_id: The tenant's unique identifier
            page: Page number (1-indexed)
            per_page: Items per page
            status: Filter by status (optional)

        Returns:
            Dict with 'items' (list), 'total', 'page', 'per_page', 'pages'
        """
        query = (
            db.session.query(SubscriptionInvoice)
            .filter_by(tenant_id=tenant_id)
            .order_by(SubscriptionInvoice.created_at.desc())
        )

        if status:
            query = query.filter_by(status=status)

        total = query.count()
        invoices = query.offset((page - 1) * per_page).limit(per_page).all()

        return {
            "items": [inv.to_dict() for inv in invoices],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page if per_page > 0 else 0,
        }

    def mark_paid(
        self,
        invoice_id: int,
        paid_at: Optional[datetime] = None,
    ) -> Optional[SubscriptionInvoice]:
        """
        Mark an invoice as paid.

        Args:
            invoice_id: The invoice ID
            paid_at: Payment timestamp (defaults to now)

        Returns:
            The updated invoice or None if not found
        """
        invoice = db.session.get(SubscriptionInvoice, invoice_id)
        if not invoice:
            return None

        invoice.status = "paid"
        invoice.paid_at = paid_at or datetime.now(timezone.utc)
        invoice.updated_at = datetime.utcnow()

        db.session.commit()
        return invoice

    def mark_failed(self, invoice_id: int) -> Optional[SubscriptionInvoice]:
        """Mark an invoice as failed."""
        invoice = db.session.get(SubscriptionInvoice, invoice_id)
        if not invoice:
            return None

        invoice.status = "failed"
        invoice.updated_at = datetime.utcnow()

        db.session.commit()
        return invoice

    def void_invoice(self, invoice_id: int) -> Optional[SubscriptionInvoice]:
        """Void an invoice."""
        invoice = db.session.get(SubscriptionInvoice, invoice_id)
        if not invoice:
            return None

        if invoice.status == "paid":
            raise ValueError("Cannot void a paid invoice")

        invoice.status = "void"
        invoice.updated_at = datetime.utcnow()

        db.session.commit()
        return invoice

    def update_invoice_pdf_url(self, invoice_id: int, pdf_url: str) -> Optional[SubscriptionInvoice]:
        """Update the PDF URL for an invoice."""
        invoice = db.session.get(SubscriptionInvoice, invoice_id)
        if not invoice:
            return None

        invoice.invoice_pdf_url = pdf_url
        invoice.updated_at = datetime.utcnow()

        db.session.commit()
        return invoice

    def generate_invoice_pdf(
        self,
        invoice_id: int,
        output_dir: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generate PDF for an invoice.
        Returns the path to the generated PDF file.

        Args:
            invoice_id: The invoice ID
            output_dir: Directory to save PDF (defaults to generated_pdfs)

        Returns:
            Path to the PDF file or None if invoice not found
        """
        from flask import current_app

        invoice = db.session.get(SubscriptionInvoice, invoice_id)
        if not invoice:
            return None

        if output_dir is None:
            output_dir = current_app.config.get(
                "UPLOAD_FOLDER",
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "generated_pdfs"),
            )

        os.makedirs(output_dir, exist_ok=True)

        filename = f"invoice_{invoice.invoice_number.replace('-', '_')}.pdf"
        filepath = os.path.join(output_dir, filename)

        self._generate_pdf_content(invoice, filepath)

        pdf_url = f"/generated_pdfs/{filename}"
        self.update_invoice_pdf_url(invoice_id, pdf_url)

        return filepath

    def _generate_pdf_content(self, invoice: SubscriptionInvoice, filepath: str) -> None:
        """
        Generate the actual PDF content.
        This is a simplified implementation - in production, use a proper PDF library
        like ReportLab or WeasyPrint.
        """
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

        doc = SimpleDocTemplate(
            filepath,
            pagesize=A4,
            rightMargin=20 * mm,
            leftMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "Title",
            parent=styles["Heading1"],
            fontSize=24,
            spaceAfter=30,
        )

        elements = []

        elements.append(Paragraph("INVOICE", title_style))
        elements.append(Spacer(1, 10 * mm))

        tenant = db.session.get(TenantMaster, invoice.tenant_id)
        tenant_name = tenant.tenant_company_name if tenant else invoice.tenant_id

        info_data = [
            ["Invoice Number:", invoice.invoice_number],
            ["Date:", datetime.now(timezone.utc).strftime("%Y-%m-%d")],
            ["Tenant:", tenant_name],
            ["Status:", invoice.status.capitalize()],
        ]

        if invoice.period_start:
            info_data.append(["Period:", f"{invoice.period_start} to {invoice.period_end or 'N/A'}"])

        info_table = Table(info_data, colWidths=[50 * mm, 100 * mm])
        info_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("ALIGN", (0, 0), (0, -1), "RIGHT"),
                    ("ALIGN", (1, 0), (1, -1), "LEFT"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        elements.append(info_table)
        elements.append(Spacer(1, 20 * mm))

        currency = db.session.get(CurrencyMaster, invoice.currency_id)
        currency_code = currency.currency_code if currency else "USD"

        amount_data = [
            ["Description", "Amount"],
            ["Subscription Invoice", f"{currency_code} {invoice.amount:.2f}"],
        ]

        if invoice.tax_amount and invoice.tax_amount > 0:
            amount_data.append(["Tax", f"{currency_code} {invoice.tax_amount:.2f}"])

        amount_data.append(
            ["Total", f"{currency_code} {invoice.total_amount:.2f}"]
        )

        amount_table = Table(amount_data, colWidths=[120 * mm, 30 * mm])
        amount_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ]
            )
        )
        elements.append(amount_table)

        doc.build(elements)

    def send_invoice_email(self, invoice_id: int) -> bool:
        """
        Send invoice via email.
        """
        invoice = db.session.get(SubscriptionInvoice, invoice_id)
        if not invoice:
            return False

        if not invoice.invoice_pdf_url:
            self.generate_invoice_pdf(invoice_id)

        from services.notification_service import NotificationService

        subject = f"Invoice {invoice.invoice_number}"
        body = (
            f"Your subscription invoice {invoice.invoice_number} is ready.\n\n"
            f"Status: {invoice.status}\n"
            f"Total: {invoice.total_amount}\n"
        )
        return NotificationService().send_email(
            tenant_id=invoice.tenant_id,
            notification_type="payment_succeeded",
            subject=subject,
            body=body,
        )

    def get_invoice_stats(self, tenant_id: str) -> Dict:
        """
        Get invoice statistics for a tenant.

        Returns:
            Dict with counts by status and total amounts
        """
        from sqlalchemy import func

        results = (
            db.session.query(
                SubscriptionInvoice.status,
                func.count(SubscriptionInvoice.invoice_id).label("count"),
                func.sum(SubscriptionInvoice.total_amount).label("total"),
            )
            .filter(SubscriptionInvoice.tenant_id == tenant_id)
            .group_by(SubscriptionInvoice.status)
            .all()
        )

        stats = {
            "by_status": {},
            "total_invoices": 0,
            "total_amount": 0.0,
            "paid_amount": 0.0,
            "pending_amount": 0.0,
        }

        for status, count, total in results:
            stats["by_status"][status] = {"count": count, "total": float(total) if total else 0}
            stats["total_invoices"] += count
            stats["total_amount"] += float(total) if total else 0

            if status == "paid":
                stats["paid_amount"] = float(total) if total else 0
            elif status == "pending":
                stats["pending_amount"] = float(total) if total else 0

        return stats
