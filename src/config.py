"""
Configuration module.

Loads environment variables for all services.
In production (Google Cloud Functions), these come from Secret Manager.
In development, they come from a .env file.

This bot manages TWO calendars:
- Work calendar (read-only): shows work events in briefings and conflict checks
- Personal calendar (read-write): all new events are created here
"""

import os
import json
import base64
from dotenv import load_dotenv

# Load .env file for local development (no-op in Cloud Functions)
load_dotenv()


# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# --- Anthropic ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# --- Google Calendar ---
CALENDAR_TIMEZONE = os.environ.get("CALENDAR_TIMEZONE", "Europe/London")

# Personal calendar — read-write, where new events are created
PERSONAL_CALENDAR_ID = os.environ.get("PERSONAL_CALENDAR_ID", "kunalgalav@gmail.com")

# Work calendar — read-only, used for conflict checks and briefings
WORK_CALENDAR_ID = os.environ.get("WORK_CALENDAR_ID", "kunal.galav@pleo.io")

# --- User ---
USER_NAME = os.environ.get("USER_NAME", "Kunal")
USER_EMAIL = os.environ.get("USER_EMAIL", "kunalgalav@gmail.com")

# --- Daily Briefing ---
DAILY_BRIEFING_HOUR = int(os.environ.get("DAILY_BRIEFING_HOUR", "7"))
DAILY_BRIEFING_ENABLED = os.environ.get("DAILY_BRIEFING_ENABLED", "true").lower() == "true"


def get_google_credentials():
    """
    Load Google Service Account credentials.

    In production: GOOGLE_SERVICE_ACCOUNT_JSON env var contains base64-encoded JSON.
    In development: reads from a local credentials.json file.
    """
    encoded = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if encoded:
        # Production: decode base64 env var
        json_str = base64.b64decode(encoded).decode("utf-8")
        return json.loads(json_str)

    # Development: read local file
    creds_path = os.path.join(os.path.dirname(__file__), "..", "credentials.json")
    if os.path.exists(creds_path):
        with open(creds_path) as f:
            return json.load(f)

    raise RuntimeError(
        "Google credentials not found. Set GOOGLE_SERVICE_ACCOUNT_JSON env var "
        "or place credentials.json in the project root."
    )
