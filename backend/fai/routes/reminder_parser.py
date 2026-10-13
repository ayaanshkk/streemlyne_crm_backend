"""
reminder_parser.py

Calls Groq to turn a natural-language message into structured reminder fields.
"""

import json
import re
import requests
from datetime import datetime
import pytz

GROQ_API_KEY = "..."  # move to env var, same pattern used by the WhatsApp chatbot's Groq calls
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"  # match whatever model the WhatsApp chatbot already uses

TIMEZONE = pytz.timezone("Asia/Kolkata")


def parse_reminder_text(message_text: str) -> dict | None:
    """
    Returns {"reminder_text": str, "remind_at": iso_str, "lead_minutes": int}
    or None if the message doesn't contain a clear date/time.
    """
    now_str = datetime.now(TIMEZONE).isoformat()

    prompt = f"""You are a reminder-parsing assistant. Extract a reminder from the user's message.
Return ONLY valid JSON, no other text, no markdown fences:
{{
  "reminder_text": "<what to remind about, cleaned up>",
  "remind_at": "<ISO 8601 datetime with timezone, e.g. 2026-10-09T10:00:00+05:30, or null if unclear>",
  "lead_minutes": <integer, default 15 if not specified>,
  "mentioned_company": "<company/client name mentioned in the message, exactly as written, or null if none is mentioned>"
}}
Only set mentioned_company if the user is clearly referring to a specific business/client by name
(e.g. "Zavsons", "the Zavsons quotation") — not for generic reminders with no company context
(e.g. "call the electrician", "submit my expense report").
Today's date and time is: {now_str} (Asia/Kolkata).
User message: "{message_text}\""""

    resp = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        timeout=15,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]

    # strip stray markdown fences just in case
    cleaned = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None

    if not data.get("remind_at"):
        return None

    data.setdefault("lead_minutes", 15)
    return data