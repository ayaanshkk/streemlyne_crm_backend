"""
Notification Service
Handles email and in-app notifications for subscription events.

Part of the Subscription Module Implementation Plan - Phase 2 (MEDIUM PRIORITY)
"""

from __future__ import annotations

import os
import json
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional, List, Dict
from urllib import error as urllib_error
from urllib import request as urllib_request

from flask import current_app

from database import db
from models import (
    NotificationPreference,
    NotificationLog,
    TenantMaster,
    TenantSubscription,
)


class NotificationService:
    """Service for notification business logic."""

    NOTIFICATION_TYPES = [
        "trial_expiring",
        "payment_failed",
        "payment_succeeded",
        "subscription_expired",
        "subscription_renewed",
        "renewal_reminder",
        "cancellation_confirmation",
        "upgrade_reminder",
        "dunning_reminder",
    ]

    def __init__(self):
        pass

    def get_preferences(self, tenant_id: str) -> List[Dict]:
        """
        Get notification preferences for a tenant.

        Returns list of preference dicts, including defaults for types not explicitly set.
        """
        prefs = (
            NotificationPreference.query
            .filter_by(tenant_id=tenant_id)
            .all()
        )

        prefs_map = {p.notification_type: p.to_dict() for p in prefs}

        result = []
        for notif_type in self.NOTIFICATION_TYPES:
            if notif_type in prefs_map:
                result.append(prefs_map[notif_type])
            else:
                result.append({
                    "notification_type": notif_type,
                    "email_enabled": True,
                    "in_app_enabled": True,
                    "sms_enabled": False,
                    "is_default": True,
                })

        return result

    def update_preferences(
        self,
        tenant_id: str,
        preferences: List[Dict],
    ) -> bool:
        """
        Update notification preferences for a tenant.

        Args:
            tenant_id: The tenant's unique identifier
            preferences: List of preference dicts with notification_type and enabled flags

        Returns:
            True if successful
        """
        for pref_data in preferences:
            notification_type = pref_data.get("notification_type")
            if not notification_type:
                continue

            pref = NotificationPreference.query.filter_by(
                tenant_id=tenant_id,
                notification_type=notification_type,
            ).first()

            if pref:
                pref.email_enabled = bool(pref_data.get("email_enabled", pref.email_enabled))
                pref.in_app_enabled = bool(pref_data.get("in_app_enabled", pref.in_app_enabled))
                pref.sms_enabled = bool(pref_data.get("sms_enabled", pref.sms_enabled))
            else:
                pref = NotificationPreference(
                    tenant_id=tenant_id,
                    notification_type=notification_type,
                    email_enabled=bool(pref_data.get("email_enabled", True)),
                    in_app_enabled=bool(pref_data.get("in_app_enabled", True)),
                    sms_enabled=bool(pref_data.get("sms_enabled", False)),
                )
                db.session.add(pref)

        db.session.commit()
        return True

    def _should_send(
        self,
        tenant_id: str,
        notification_type: str,
        channel: str,
    ) -> bool:
        """
        Check if a notification should be sent based on preferences.

        Args:
            tenant_id: The tenant's unique identifier
            notification_type: Type of notification
            channel: 'email', 'in_app', or 'sms'

        Returns:
            True if notification should be sent
        """
        pref = NotificationPreference.query.filter_by(
            tenant_id=tenant_id,
            notification_type=notification_type,
        ).first()

        if not pref:
            return True

        channel_field = f"{channel}_enabled"
        return getattr(pref, channel_field, True)

    def _log_notification(
        self,
        tenant_id: str,
        notification_type: str,
        channel: str,
        recipient: Optional[str] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        status: str = "sent",
    ) -> NotificationLog:
        """
        Log a notification to the audit trail.

        Args:
            tenant_id: The tenant's unique identifier
            notification_type: Type of notification
            channel: 'email', 'in_app', or 'sms'
            recipient: Email address or phone number
            subject: Email subject
            body: Notification body
            status: 'sent', 'failed', 'pending'

        Returns:
            The created NotificationLog
        """
        log = NotificationLog(
            tenant_id=tenant_id,
            notification_type=notification_type,
            channel=channel,
            recipient=recipient,
            subject=subject,
            body=body,
            status=status,
            sent_at=datetime.utcnow() if status == "sent" else None,
        )
        db.session.add(log)
        db.session.commit()
        return log

    def send_email(
        self,
        tenant_id: str,
        notification_type: str,
        subject: str,
        body: str,
        recipient: Optional[str] = None,
    ) -> bool:
        """
        Send an email notification.

        Args:
            tenant_id: The tenant's unique identifier
            notification_type: Type of notification
            subject: Email subject
            body: Email body
            recipient: Optional recipient email (uses tenant default if not provided)

        Returns:
            True if sent successfully
        """
        if not self._should_send(tenant_id, notification_type, "email"):
            current_app.logger.info(
                f"[NOTIFICATION] Email {notification_type} suppressed for tenant {tenant_id}"
            )
            return False

        if not recipient:
            tenant = db.session.get(TenantMaster, tenant_id)
            if tenant:
                employee = tenant.employees.first()
                if employee:
                    recipient = employee.email

        if not recipient:
            current_app.logger.warning(
                f"[NOTIFICATION] No email recipient for tenant {tenant_id}"
            )
            return False

        try:
            delivered = self._deliver_email(recipient, subject, body)
            self._log_notification(
                tenant_id=tenant_id,
                notification_type=notification_type,
                channel="email",
                recipient=recipient,
                subject=subject,
                body=body,
                status="sent" if delivered else "pending",
            )
            return delivered
        except Exception as e:
            current_app.logger.error(
                f"[NOTIFICATION] Failed to send email to {recipient}: {e}"
            )
            self._log_notification(
                tenant_id=tenant_id,
                notification_type=notification_type,
                channel="email",
                recipient=recipient,
                subject=subject,
                body=body,
                status="failed",
            )
            return False

    def _deliver_email(self, recipient: str, subject: str, body: str) -> bool:
        """
        Deliver email using SendGrid, SES, SMTP, or log-only fallback.
        """
        sendgrid_key = current_app.config.get("SENDGRID_API_KEY") or os.environ.get("SENDGRID_API_KEY")
        default_sender = (
            current_app.config.get("BILLING_FROM_EMAIL")
            or os.environ.get("BILLING_FROM_EMAIL")
            or current_app.config.get("SALES_CONTACT_EMAIL")
            or "billing@streemlyne.com"
        )
        unsubscribe_url = (
            current_app.config.get("EMAIL_UNSUBSCRIBE_URL")
            or os.environ.get("EMAIL_UNSUBSCRIBE_URL")
        )

        if sendgrid_key:
            payload = {
                "personalizations": [{"to": [{"email": recipient}]}],
                "from": {"email": default_sender},
                "subject": subject,
                "content": [{"type": "text/plain", "value": body}],
            }
            req = urllib_request.Request(
                "https://api.sendgrid.com/v3/mail/send",
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": f"Bearer {sendgrid_key}",
                    "Content-Type": "application/json",
                    **(
                        {"List-Unsubscribe": f"<{unsubscribe_url}>"}
                        if unsubscribe_url
                        else {}
                    ),
                },
            )
            try:
                with urllib_request.urlopen(req, timeout=10) as resp:
                    return 200 <= resp.status < 300
            except urllib_error.URLError as exc:
                current_app.logger.error("[NOTIFICATION] SendGrid delivery failed: %s", exc)
                raise

        smtp_host = current_app.config.get("SMTP_HOST") or os.environ.get("SMTP_HOST")
        smtp_port = int(current_app.config.get("SMTP_PORT") or os.environ.get("SMTP_PORT") or 587)
        smtp_user = current_app.config.get("SMTP_USERNAME") or os.environ.get("SMTP_USERNAME")
        smtp_pass = current_app.config.get("SMTP_PASSWORD") or os.environ.get("SMTP_PASSWORD")
        smtp_tls = str(
            current_app.config.get("SMTP_USE_TLS") or os.environ.get("SMTP_USE_TLS") or "true"
        ).lower() in {"1", "true", "yes"}

        if smtp_host and smtp_user and smtp_pass:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = default_sender
            msg["To"] = recipient
            if unsubscribe_url:
                msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
            msg.set_content(body)

            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                if smtp_tls:
                    server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            return True

        current_app.logger.info(
            "[NOTIFICATION] No email provider configured; retaining log-only delivery for %s",
            recipient,
        )
        return False

    def send_in_app(
        self,
        tenant_id: str,
        notification_type: str,
        message: str,
    ) -> bool:
        """
        Send an in-app notification.

        Args:
            tenant_id: The tenant's unique identifier
            notification_type: Type of notification
            message: Notification message

        Returns:
            True if sent successfully
        """
        if not self._should_send(tenant_id, notification_type, "in_app"):
            current_app.logger.info(
                f"[NOTIFICATION] In-app {notification_type} suppressed for tenant {tenant_id}"
            )
            return False

        try:
            self._log_notification(
                tenant_id=tenant_id,
                notification_type=notification_type,
                channel="in_app",
                body=message,
                status="sent",
            )
            return True
        except Exception as e:
            current_app.logger.error(
                f"[NOTIFICATION] Failed to send in-app notification: {e}"
            )
            return False

    def send_trial_expiring(self, tenant_id: str, days_remaining: int) -> None:
        """
        Send trial expiring notification.

        Args:
            tenant_id: The tenant's unique identifier
            days_remaining: Days until trial expires
        """
        if days_remaining <= 0:
            return

        subject = f"Your trial expires in {days_remaining} day{'s' if days_remaining != 1 else ''}"
        body = f"""
Hello,

Your StreemLyne CRM trial will expire in {days_remaining} day{'s' if days_remaining != 1 else ''}.

Upgrade now to continue using all features without interruption.

Best regards,
The StreemLyne Team
        """.strip()

        self.send_email(tenant_id, "trial_expiring", subject, body)
        self.send_in_app(tenant_id, "trial_expiring", subject)

    def send_payment_failed(
        self,
        tenant_id: str,
        attempt_number: int,
        failure_reason: Optional[str] = None,
    ) -> None:
        """
        Send payment failed notification.

        Args:
            tenant_id: The tenant's unique identifier
            attempt_number: Which attempt failed
            failure_reason: Optional reason for failure
        """
        if attempt_number == 1:
            subject = "Payment failed - Please update your payment method"
        else:
            subject = f"Payment failed (attempt {attempt_number}) - Please update your payment method"

        reason_text = f"\nReason: {failure_reason}" if failure_reason else ""
        body = f"""
Hello,

Your subscription payment failed (attempt {attempt_number}).{reason_text}

Please update your payment method to avoid service interruption.

Best regards,
The StreemLyne Team
        """.strip()

        self.send_email(tenant_id, "payment_failed", subject, body)
        self.send_in_app(tenant_id, "payment_failed", subject)

    def send_payment_succeeded(self, tenant_id: str, amount: float, currency: str = "USD") -> None:
        """
        Send payment succeeded notification.

        Args:
            tenant_id: The tenant's unique identifier
            amount: Payment amount
            currency: Currency code
        """
        subject = "Payment received - Thank you!"
        body = f"""
Hello,

We have received your payment of {currency} {amount:.2f}.

Thank you for your continued support!

Best regards,
The StreemLyne Team
        """.strip()

        self.send_email(tenant_id, "payment_succeeded", subject, body)

    def send_subscription_expired(self, tenant_id: str) -> None:
        """
        Send subscription expired notification.

        Args:
            tenant_id: The tenant's unique identifier
        """
        subject = "Your subscription has expired"
        body = """
Hello,

Your StreemLyne CRM subscription has expired and access to premium features has been limited.

Upgrade now to restore full access to your account and data.

Best regards,
The StreemLyne Team
        """.strip()

        self.send_email(tenant_id, "subscription_expired", subject, body)
        self.send_in_app(tenant_id, "subscription_expired", subject)

    def send_subscription_renewed(
        self,
        tenant_id: str,
        next_period_end: Optional[str] = None,
    ) -> None:
        """
        Send subscription renewed notification.

        Args:
            tenant_id: The tenant's unique identifier
            next_period_end: End date of next billing period
        """
        period_text = f"\n\nYour next billing date is {next_period_end}." if next_period_end else ""

        subject = "Subscription renewed - You're all set!"
        body = f"""
Hello,

Your StreemLyne CRM subscription has been renewed successfully.{period_text}

Thank you for your continued support!

Best regards,
The StreemLyne Team
        """.strip()

        self.send_email(tenant_id, "subscription_renewed", subject, body)

    def send_renewal_reminder(
        self,
        tenant_id: str,
        days_until_renewal: int,
        renewal_date: Optional[str] = None,
    ) -> None:
        renewal_text = f"\n\nYour next renewal date is {renewal_date}." if renewal_date else ""
        subject = f"Subscription renews in {days_until_renewal} day{'s' if days_until_renewal != 1 else ''}"
        body = f"""
Hello,

Your StreemLyne CRM subscription is due to renew in {days_until_renewal} day{'s' if days_until_renewal != 1 else ''}.{renewal_text}

Please review your billing details if anything needs to change before renewal.

Best regards,
The StreemLyne Team
        """.strip()

        self.send_email(tenant_id, "renewal_reminder", subject, body)
        self.send_in_app(tenant_id, "renewal_reminder", subject)

    def send_cancellation_confirmation(
        self,
        tenant_id: str,
        access_until: Optional[str] = None,
    ) -> None:
        """
        Send cancellation confirmation notification.

        Args:
            tenant_id: The tenant's unique identifier
            access_until: Date when access ends
        """
        access_text = f"\n\nYou will have access until {access_until}." if access_until else ""

        subject = "Subscription cancellation confirmed"
        body = f"""
Hello,

Your StreemLyne CRM subscription has been cancelled.{access_text}

We hope to see you again soon!

Best regards,
The StreemLyne Team
        """.strip()

        self.send_email(tenant_id, "cancellation_confirmation", subject, body)

    def send_dunning_reminder(
        self,
        tenant_id: str,
        days_until_retry: int,
    ) -> None:
        """
        Send dunning reminder notification.

        Args:
            tenant_id: The tenant's unique identifier
            days_until_retry: Days until next payment retry
        """
        subject = f"Payment retry scheduled in {days_until_retry} day{'s' if days_until_retry != 1 else ''}"
        body = f"""
Hello,

A payment retry has been scheduled for your StreemLyne CRM subscription in {days_until_retry} day{'s' if days_until_retry != 1 else ''}.

Please ensure your payment method has sufficient funds to avoid service interruption.

Best regards,
The StreemLyne Team
        """.strip()

        self.send_email(tenant_id, "dunning_reminder", subject, body)
        self.send_in_app(tenant_id, "dunning_reminder", subject)

    def get_notification_history(
        self,
        tenant_id: str,
        limit: int = 50,
    ) -> List[Dict]:
        """
        Get notification history for a tenant.

        Args:
            tenant_id: The tenant's unique identifier
            limit: Maximum number of notifications to return

        Returns:
            List of notification log dicts
        """
        logs = (
            NotificationLog.query
            .filter_by(tenant_id=tenant_id)
            .order_by(NotificationLog.created_at.desc())
            .limit(limit)
            .all()
        )
        return [log.to_dict() for log in logs]
