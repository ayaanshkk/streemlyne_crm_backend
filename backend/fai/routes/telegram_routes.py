"""
telegram_routes.py

Every reminder created via Telegram becomes a single row in Client_Interactions,
following the exact same convention as contact_interactions_routes.py's
create_contact_interaction() for interaction_type="Task":
  - contact_method = 6 (confirmed Task's id in the real method_map)
  - notes prefixed "[Task] ..." so GET routes correctly categorize it
    (they parse the interaction_type back out of this bracket prefix)
  - entity_type = "company" or "contact" depending on which is set

General reminders (no company/contact mentioned) fall back to the FAI
company record (entity_type="company", contact_id=NULL).

Setup (one-time):
    https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://your-domain.com/telegram/webhook
"""

import os
from flask import Blueprint, request, jsonify
import requests
from sqlalchemy import text

from .reminder_parser import parse_reminder_text
from ..db import SessionLocal

telegram_bp = Blueprint("telegram", __name__)

# Optional: without it the StreemLyne backend still starts; Telegram features stay off.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

SCHEMA = "streemLyne_mt_dev2"
TABLE = f'"{SCHEMA}"."Client_Interactions"'

# Confirmed from the Client_Master table view: companies sit under tenant_id 3
TENANT_ID = 3

TASK_CONTACT_METHOD_ID = 6  # confirmed from contact_interactions_routes.py's method_map

# "Forklift Academy of India" company record, created for general reminders
FAI_FALLBACK_CLIENT_ID = 51


def send_telegram_message(chat_id, text_body):
    requests.post(f"{TELEGRAM_API}/sendMessage", json={"chat_id": chat_id, "text": text_body}, timeout=10)


@telegram_bp.route("/telegram/webhook", methods=["POST"], strict_slashes=False)
def telegram_webhook():
    update = request.get_json(force=True)

    message = update.get("message")
    if not message or "text" not in message:
        return jsonify({"ok": True})

    chat_id = str(message["chat"]["id"])
    incoming_text = message["text"]

    parsed = parse_reminder_text(incoming_text)

    if parsed is None:
        send_telegram_message(chat_id, "Sorry, I couldn't figure out the date/time — can you rephrase?")
        return jsonify({"ok": True})

    client_id = None
    mentioned_company = parsed.get("mentioned_company")

    if mentioned_company:
        lookup_session = SessionLocal()
        try:
            match = lookup_session.execute(
                text(f"""
                    SELECT client_id FROM "{SCHEMA}"."Client_Master"
                    WHERE tenant_id = :tid
                      AND client_company_name ILIKE :name
                    LIMIT 1
                """),
                {"tid": TENANT_ID, "name": f"%{mentioned_company}%"}
            ).fetchone()
            if match:
                client_id = match.client_id
        finally:
            lookup_session.close()

    if client_id is None:
        client_id = FAI_FALLBACK_CLIENT_ID

    contact_id = parsed.get("contact_id")
    entity_type = "contact" if contact_id else "company"

    remind_at = parsed["remind_at"]        # e.g. "2026-10-09T10:00:00+05:30"
    due_date = remind_at.split("T")[0]
    due_time = remind_at.split("T")[1][:8]

    # Matches contact_interactions_routes.py's formatted_notes convention exactly,
    # so this row is correctly recognized as a Task by every GET route that parses it.
    formatted_notes = "[Task] Created via Telegram reminder bot"

    session = SessionLocal()
    try:
        result = session.execute(
            text(f"""
                INSERT INTO {TABLE}
                    (client_id, contact_id, entity_type, contact_method,
                     contact_date, contact_time, subject, due_date, notes,
                     telegram_chat_id, lead_minutes, alert_status)
                VALUES
                    (:client_id, :contact_id, :entity_type, :contact_method,
                     CURRENT_DATE, :contact_time, :subject, :due_date, :notes,
                     :telegram_chat_id, :lead_minutes, 'Pending')
                RETURNING interaction_id
            """),
            {
                "client_id": client_id,
                "contact_id": contact_id,
                "entity_type": entity_type,
                "contact_method": TASK_CONTACT_METHOD_ID,
                "contact_time": due_time,
                "subject": parsed["reminder_text"],
                "due_date": due_date,
                "notes": formatted_notes,
                "telegram_chat_id": chat_id,
                "lead_minutes": parsed["lead_minutes"],
            }
        )
        interaction_id = result.fetchone().interaction_id
        session.commit()
    except Exception:
        session.rollback()
        send_telegram_message(chat_id, "Sorry, something went wrong saving that reminder — please try again.")
        return jsonify({"ok": True})
    finally:
        session.close()

    send_telegram_message(
        chat_id,
        f"Got it — I'll remind you about \"{parsed['reminder_text']}\" on {remind_at}.",
    )
    return jsonify({"ok": True})