"""
reminder_scheduler.py

Polls Client_Interactions directly using the same SQLAlchemy SessionLocal()/
text() pattern as company_routes.py — not raw psycopg2. Only rows created via
the Telegram bot have telegram_chat_id set, so this never touches Notes/Calls/
Emails/Meetings or manually-created Tasks made through the normal CRM UI.

In your main app.py:
    from reminder_scheduler import start_scheduler
    start_scheduler()

Requires: pip install apscheduler
"""

import os
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from sqlalchemy import text

from .db import SessionLocal  # relative import — this file and db.py are both inside the `backend` package


SCHEMA = "streemLyne_mt_dev2"


def T(table_name):
    return f'"{SCHEMA}"."{table_name}"'


# Optional: without it the StreemLyne backend still starts; Telegram features stay off.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_telegram_message(chat_id, text_body):
    requests.post(f"{TELEGRAM_API}/sendMessage", json={"chat_id": chat_id, "text": text_body}, timeout=10)


def check_due_reminders():
    """Runs every 5 minutes. Finds Telegram-created interactions whose alert
    window has arrived, sends the message, and marks them Sent."""
    session = SessionLocal()
    try:
        due_rows = session.execute(
            text(f"""
                SELECT interaction_id, telegram_chat_id, subject, due_date, contact_time
                FROM {T('Client_Interactions')}
                WHERE telegram_chat_id IS NOT NULL
                  AND alert_status = 'Pending'
                  AND now() >= (due_date + contact_time) - (lead_minutes || ' minutes')::interval
            """)
        ).fetchall()

        for row in due_rows:
            send_telegram_message(
                row.telegram_chat_id,
                f"Reminder: \"{row.subject}\" is due at {row.contact_time} on {row.due_date}.",
            )
            session.execute(
                text(f"""
                    UPDATE {T('Client_Interactions')}
                    SET alert_status = 'Sent'
                    WHERE interaction_id = :iid
                """),
                {"iid": row.interaction_id}
            )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_due_reminders, "interval", minutes=5)
    scheduler.start()
    return scheduler