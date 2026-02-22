from __future__ import annotations

"""
Claude Service — the "brain" of the work-life calendar bot.

Handles two types of input:
1. Text messages  → parsed into structured event JSON (create, modify, cancel, query)
2. Image uploads  → vision API extracts event details from photos of invites/tickets

Key difference from the family bot: this is single-user with two calendars.
- Work events are read-only (shown but never created/modified)
- Personal events are read-write (full CRUD)
- Claude is aware of both calendars for context
"""

import json
import base64
import logging
from datetime import datetime

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, USER_NAME, CALENDAR_TIMEZONE

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# The system prompt tells Claude to act as a personal calendar assistant
# that's aware of both work and personal schedules.
SYSTEM_PROMPT = f"""You are a helpful calendar assistant for {USER_NAME}.
You help manage a personal schedule alongside a read-only work calendar.

Today's date is {{today_date}}.

CALENDAR SETUP:
- Personal calendar: read-write — you can create, modify, and cancel events here
- Work calendar: read-only — you can SEE work events but CANNOT create, modify, or cancel them
- When creating events, they always go on the personal calendar
- When checking for conflicts, you check BOTH calendars

IMPORTANT RULES:
- Use the timezone {CALENDAR_TIMEZONE}
- Use UK date format when speaking (e.g. "Saturday 28th February")
- If you're not confident about a date, time, or detail, set confidence to "low" and explain in clarification_needed
- For event end times, default to 1 hour after start if not specified
- For modifications, include the original_event_title to help find the event
- For queries, set the date range in the event object
- If someone asks to modify or cancel a work event, set intent to "unknown" and explain that work events are read-only

You MUST respond with valid JSON matching this exact schema (no markdown, no backticks, just raw JSON):

{{
  "intent": "create" | "modify" | "cancel" | "query" | "confirm" | "unknown",
  "event": {{
    "title": "string",
    "date": "YYYY-MM-DD",
    "start_time": "HH:MM",
    "end_time": "HH:MM",
    "location": "string or null",
    "description": "string or null"
  }},
  "original_event_title": "string or null",
  "confidence": "high" | "medium" | "low",
  "clarification_needed": "string or null",
  "reply_text": "A short, friendly message to send back in Telegram confirming what you understood"
}}

If the user says "yes", "yeah", "go ahead", "do it", "confirm", etc., return intent "confirm".
If you can't understand the message, return intent "unknown" with a helpful reply_text.

For "query" intents (e.g. "what's on this week?"), set date to the start date and end_time to the end date in YYYY-MM-DD format.
"""


def _get_system_prompt() -> str:
    """Build the system prompt with today's date injected."""
    today = datetime.now().strftime("%A %d %B %Y")
    return SYSTEM_PROMPT.replace("{today_date}", today)


def parse_text(user_message: str) -> dict:
    """
    Parse a natural language message into a structured event dict.

    Args:
        user_message: The text message from Telegram

    Returns:
        Parsed dict with intent, event details, confidence, etc.
    """
    logger.info("Parsing text message with Claude")

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=_get_system_prompt(),
        messages=[
            {"role": "user", "content": user_message}
        ],
    )

    raw_text = response.content[0].text.strip()
    logger.debug(f"Claude raw response: {raw_text}")

    try:
        parsed = json.loads(raw_text)
        return parsed
    except json.JSONDecodeError:
        logger.error(f"Claude returned invalid JSON: {raw_text}")
        return {
            "intent": "unknown",
            "event": None,
            "confidence": "low",
            "clarification_needed": None,
            "reply_text": "Sorry, I had trouble understanding that. Could you rephrase?",
        }


def parse_image(image_bytes: bytes, caption: str | None = None) -> dict:
    """
    Extract event details from an image (photo of invite, ticket, screenshot, etc.).

    Uses Claude's vision capability to read the image and return structured event data.

    Args:
        image_bytes: Raw image bytes (JPEG or PNG)
        caption: Optional caption the user included with the image

    Returns:
        Parsed dict with intent, event details, confidence, etc.
    """
    logger.info("Parsing image with Claude Vision")

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": image_b64,
            },
        },
    ]

    if caption:
        content.append({"type": "text", "text": caption})
    else:
        content.append({
            "type": "text",
            "text": "Please extract any event details (title, date, time, location) from this image.",
        })

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=_get_system_prompt(),
        messages=[
            {"role": "user", "content": content}
        ],
    )

    raw_text = response.content[0].text.strip()
    logger.debug(f"Claude vision raw response: {raw_text}")

    try:
        parsed = json.loads(raw_text)
        if parsed.get("intent") != "unknown":
            parsed["intent"] = "create"
        return parsed
    except json.JSONDecodeError:
        logger.error(f"Claude returned invalid JSON from image: {raw_text}")
        return {
            "intent": "unknown",
            "event": None,
            "confidence": "low",
            "clarification_needed": None,
            "reply_text": "I couldn't read that clearly. Could you type the event details instead?",
        }
