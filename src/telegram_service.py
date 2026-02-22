"""
Telegram Service — handles sending messages, photos, and downloading images.

This module wraps the Telegram Bot API for:
1. Sending text replies to the chat
2. Sending photos (e.g. calendar card images)
3. Downloading photos from incoming messages
4. Formatting schedule messages for daily briefings

We use the `requests` library directly instead of python-telegram-bot
because Cloud Functions are short-lived — we don't need the full
async bot framework, just simple HTTP calls to the Telegram API.
"""

import io
import logging
from datetime import datetime

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_message(text: str, chat_id: str = None) -> dict:
    """
    Send a text message to a Telegram chat.

    Args:
        text: The message to send (supports HTML formatting)
        chat_id: Target chat ID (defaults to the configured chat)

    Returns:
        Telegram API response dict
    """
    target_chat = chat_id or TELEGRAM_CHAT_ID

    payload = {
        "chat_id": target_chat,
        "text": text,
        "parse_mode": "HTML",
    }

    try:
        resp = requests.post(f"{BASE_URL}/sendMessage", json=payload, timeout=10)
        resp.raise_for_status()
        logger.info(f"Message sent to chat {target_chat}")
        return resp.json()

    except requests.RequestException as e:
        logger.error(f"Failed to send Telegram message: {e}")
        raise


def send_photo(image_bytes: bytes, caption: str = None, chat_id: str = None) -> dict:
    """
    Send a photo to a Telegram chat.

    Args:
        image_bytes: PNG or JPEG image data as bytes
        caption: Optional caption text (supports HTML formatting)
        chat_id: Target chat ID (defaults to the configured chat)

    Returns:
        Telegram API response dict
    """
    target_chat = chat_id or TELEGRAM_CHAT_ID

    data = {"chat_id": target_chat}
    if caption:
        data["caption"] = caption
        data["parse_mode"] = "HTML"

    files = {"photo": ("briefing.png", io.BytesIO(image_bytes), "image/png")}

    try:
        resp = requests.post(
            f"{BASE_URL}/sendPhoto",
            data=data,
            files=files,
            timeout=15,
        )
        resp.raise_for_status()
        logger.info(f"Photo sent to chat {target_chat}")
        return resp.json()

    except requests.RequestException as e:
        logger.error(f"Failed to send Telegram photo: {e}")
        raise


def download_photo(file_id: str) -> bytes:
    """
    Download a photo from Telegram servers.

    Args:
        file_id: The Telegram file_id from the incoming message

    Returns:
        Raw image bytes (JPEG)
    """
    try:
        resp = requests.get(
            f"{BASE_URL}/getFile",
            params={"file_id": file_id},
            timeout=10,
        )
        resp.raise_for_status()
        file_path = resp.json()["result"]["file_path"]

        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
        file_resp = requests.get(file_url, timeout=30)
        file_resp.raise_for_status()

        logger.info(f"Downloaded photo: {file_path} ({len(file_resp.content)} bytes)")
        return file_resp.content

    except requests.RequestException as e:
        logger.error(f"Failed to download photo: {e}")
        raise


def format_daily_briefing(schedule: dict) -> str:
    """
    Format a daily schedule into a nice Telegram message.

    Shows work and personal events in separate sections.

    Args:
        schedule: Dict from calendar_service.get_daily_schedule() with
                  'date', 'work', 'personal'

    Returns:
        Formatted HTML string for Telegram
    """
    date_obj = datetime.strptime(schedule["date"], "%Y-%m-%d")
    date_str = date_obj.strftime("%A %d %B")

    lines = [f"<b>Good morning! Here's your schedule for {date_str}:</b>\n"]

    has_events = False

    # Work events
    if schedule.get("work"):
        has_events = True
        lines.append("<b>Work:</b>")
        for event in schedule["work"]:
            lines.append(_format_event_line(event))
        lines.append("")

    # Personal events
    if schedule.get("personal"):
        has_events = True
        lines.append("<b>Personal:</b>")
        for event in schedule["personal"]:
            lines.append(_format_event_line(event))
        lines.append("")

    if not has_events:
        lines.append("Nothing scheduled today — enjoy the free day!")

    return "\n".join(lines)


def _format_event_line(event: dict) -> str:
    """Format a single event into a readable line."""
    start_str = event.get("start", "")
    if "T" in start_str:
        time_part = start_str.split("T")[1][:5]
    else:
        time_part = "All day"

    title = event.get("title", "Untitled")
    location = event.get("location")

    if location:
        return f"  {time_part} — {title} ({location})"
    return f"  {time_part} — {title}"


def format_conflict_warning(conflicts: list[dict]) -> str:
    """
    Format a list of conflicting events into a warning message.

    Includes which calendar (work/personal) each conflict is from.

    Args:
        conflicts: List of event dicts from check_conflicts()

    Returns:
        Formatted warning string
    """
    if not conflicts:
        return ""

    lines = ["<b>Heads up — there's a conflict:</b>"]
    for event in conflicts:
        summary = event.get("summary", "Untitled")
        cal_type = event.get("_calendar", "").capitalize()
        start = event.get("start", {}).get("dateTime", "")
        end = event.get("end", {}).get("dateTime", "")

        start_time = start.split("T")[1][:5] if "T" in start else "?"
        end_time = end.split("T")[1][:5] if "T" in end else "?"

        # Show which calendar the conflict is on
        cal_label = f" [{cal_type}]" if cal_type else ""
        lines.append(f"  {summary} ({start_time}–{end_time}){cal_label}")

    lines.append("\nShould I still go ahead, or pick a different time?")
    return "\n".join(lines)
