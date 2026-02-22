"""
Main webhook handler — the entry point for the Cloud Function.

This is triggered every time someone sends a message to the Telegram chat.
It orchestrates the full flow:
1. Receive Telegram webhook update
2. Parse the message with Claude (text or image)
3. Check for conflicts across BOTH work and personal calendars
4. Send a confirmation message back to Telegram
5. If the user confirms, create/modify/cancel the event (personal calendar only)

SINGLE-USER DESIGN:
This bot is for Kunal only. No partner logic — just work (read-only)
and personal (read-write) calendars.

For local development, run with:
    functions-framework --target=telegram_webhook --debug
"""

import json
import logging
from datetime import datetime

import functions_framework

from claude_service import parse_text, parse_image
from calendar_service import (
    create_event,
    query_events,
    find_event_by_title,
    modify_event,
    cancel_event,
    check_conflicts,
)
from telegram_service import (
    send_message,
    download_photo,
    format_conflict_warning,
)
from config import TELEGRAM_CHAT_ID

# Import daily_briefing so Cloud Functions can find it in main.py
from daily_briefing import daily_briefing  # noqa: F401

logger = logging.getLogger(__name__)

# Simple in-memory store for pending events awaiting confirmation.
# Persists across warm invocations but resets on cold starts.
_pending_events = {}


@functions_framework.http
def telegram_webhook(request):
    """
    Google Cloud Function entry point.

    Receives POST requests from Telegram's webhook with message updates.
    """
    if request.method != "POST":
        return "OK", 200

    try:
        update = request.get_json(silent=True)
        if not update:
            logger.warning("Received empty update")
            return "OK", 200

        message = update.get("message")
        if not message:
            return "OK", 200

        chat_id = str(message.get("chat", {}).get("id", ""))

        # Security: only respond to messages from our chat
        if chat_id != TELEGRAM_CHAT_ID:
            logger.warning(f"Message from unknown chat: {chat_id}")
            return "OK", 200

        if message.get("photo"):
            _handle_photo(message, chat_id)
        elif message.get("text"):
            _handle_text(message, chat_id)
        else:
            logger.info("Received unsupported message type, ignoring")

        return "OK", 200

    except Exception as e:
        # Always return 200 to Telegram — otherwise it retries endlessly
        logger.error(f"Error processing update: {e}", exc_info=True)
        return "OK", 200


def _handle_text(message: dict, chat_id: str):
    """Handle an incoming text message."""
    text = message.get("text", "").strip()
    if not text:
        return

    if text.startswith("/") and not text.startswith("/start"):
        return

    logger.info(f"Processing text message: {text[:100]}")

    parsed = parse_text(text)
    intent = parsed.get("intent", "unknown")

    logger.info(f"Claude parsed intent: {intent}, confidence: {parsed.get('confidence')}")

    if intent == "confirm":
        _handle_confirmation(chat_id)

    elif intent == "create":
        _handle_create_intent(parsed, chat_id)

    elif intent == "modify":
        _handle_modify_intent(parsed, chat_id)

    elif intent == "cancel":
        _handle_cancel_intent(parsed, chat_id)

    elif intent == "query":
        _handle_query_intent(parsed, chat_id)

    elif intent == "unknown":
        reply = parsed.get("reply_text", "Sorry, I didn't understand that. Could you rephrase?")
        send_message(reply, chat_id)

    else:
        send_message(parsed.get("reply_text", "I'm not sure what to do with that."), chat_id)


def _handle_photo(message: dict, chat_id: str):
    """Handle an incoming photo message."""
    photos = message.get("photo", [])
    if not photos:
        return

    largest_photo = photos[-1]
    file_id = largest_photo.get("file_id")
    caption = message.get("caption")

    logger.info(f"Processing photo (file_id: {file_id[:20]}...)")

    try:
        image_bytes = download_photo(file_id)
        parsed = parse_image(image_bytes, caption)
        intent = parsed.get("intent", "unknown")

        if intent == "create" and parsed.get("event"):
            _handle_create_intent(parsed, chat_id)
        elif intent == "unknown":
            reply = parsed.get("reply_text", "I couldn't read that image clearly. Could you type the event details instead?")
            send_message(reply, chat_id)
        else:
            send_message(parsed.get("reply_text", "I extracted some info but I'm not sure what to do with it."), chat_id)

    except Exception as e:
        logger.error(f"Error processing photo: {e}", exc_info=True)
        send_message("Sorry, I had trouble processing that image. Could you try again or type the details?", chat_id)


def _handle_create_intent(parsed: dict, chat_id: str):
    """Handle a 'create' intent — check conflicts across both calendars and ask for confirmation."""
    event = parsed.get("event")
    if not event:
        send_message("I couldn't extract event details. Could you be more specific?", chat_id)
        return

    confidence = parsed.get("confidence", "low")
    clarification = parsed.get("clarification_needed")

    if confidence == "low" and clarification:
        send_message(clarification, chat_id)
        return

    # Check for conflicts across BOTH work and personal calendars
    conflicts = check_conflicts(
        event.get("date", ""),
        event.get("start_time", ""),
        event.get("end_time", ""),
    )

    if conflicts:
        warning = format_conflict_warning(conflicts)
        reply = parsed.get("reply_text", "")
        send_message(f"{reply}\n\n{warning}", chat_id)
    else:
        reply = parsed.get("reply_text", "Shall I add this to your personal calendar?")
        send_message(reply, chat_id)

    _pending_events[chat_id] = {
        "action": "create",
        "event": event,
        "timestamp": datetime.now().isoformat(),
    }


def _handle_modify_intent(parsed: dict, chat_id: str):
    """Handle a 'modify' intent — find the event on personal calendar and ask for confirmation."""
    event = parsed.get("event", {})
    original_title = parsed.get("original_event_title") or event.get("title", "")

    if not original_title:
        send_message("Which event would you like to modify?", chat_id)
        return

    # Only search personal calendar — work events are read-only
    existing = find_event_by_title(original_title, event.get("date"))

    if not existing:
        send_message(
            f"I couldn't find a personal event matching '{original_title}'. "
            "Note: I can only modify events on your personal calendar, not work events.",
            chat_id,
        )
        return

    updates = {}
    if event.get("title") and event["title"] != original_title:
        updates["title"] = event["title"]
    if event.get("date"):
        updates["date"] = event["date"]
    if event.get("start_time"):
        updates["start_time"] = event["start_time"]
    if event.get("end_time"):
        updates["end_time"] = event["end_time"]
    if event.get("location"):
        updates["location"] = event["location"]

    reply = parsed.get("reply_text", "Shall I make this change?")
    send_message(reply, chat_id)

    _pending_events[chat_id] = {
        "action": "modify",
        "event_id": existing["id"],
        "updates": updates,
        "timestamp": datetime.now().isoformat(),
    }


def _handle_cancel_intent(parsed: dict, chat_id: str):
    """Handle a 'cancel' intent — find the event on personal calendar and ask for confirmation."""
    event = parsed.get("event", {})
    original_title = parsed.get("original_event_title") or event.get("title", "")

    if not original_title:
        send_message("Which event would you like to cancel?", chat_id)
        return

    existing = find_event_by_title(original_title, event.get("date"))

    if not existing:
        send_message(
            f"I couldn't find a personal event matching '{original_title}'. "
            "Note: I can only cancel events on your personal calendar, not work events.",
            chat_id,
        )
        return

    reply = parsed.get("reply_text", "Shall I cancel this event?")
    send_message(reply, chat_id)

    _pending_events[chat_id] = {
        "action": "cancel",
        "event_id": existing["id"],
        "event_title": existing.get("summary", ""),
        "timestamp": datetime.now().isoformat(),
    }


def _handle_query_intent(parsed: dict, chat_id: str):
    """Handle a 'query' intent — fetch and display events from both calendars."""
    event = parsed.get("event", {})

    start_date = event.get("date", datetime.now().strftime("%Y-%m-%d"))
    end_date = event.get("end_time", start_date)

    # If end_time looks like a time (HH:MM) rather than a date, default to same day
    if len(end_date) <= 5:
        end_date = start_date

    try:
        events = query_events(start_date, end_date, calendar="both")

        if not events:
            send_message(f"Nothing scheduled between {start_date} and {end_date}.", chat_id)
            return

        # Group events by calendar type for display
        work_events = [e for e in events if e.get("_calendar") == "work"]
        personal_events = [e for e in events if e.get("_calendar") == "personal"]

        lines = [f"<b>Schedule ({start_date} to {end_date}):</b>\n"]

        if work_events:
            lines.append("<b>Work:</b>")
            for ev in work_events:
                lines.append(_format_event_line(ev))
            lines.append("")

        if personal_events:
            lines.append("<b>Personal:</b>")
            for ev in personal_events:
                lines.append(_format_event_line(ev))
            lines.append("")

        send_message("\n".join(lines), chat_id)

    except Exception as e:
        logger.error(f"Error querying events: {e}", exc_info=True)
        send_message("Sorry, I had trouble checking the calendar. Please try again.", chat_id)


def _format_event_line(ev: dict) -> str:
    """Format a single event into a display line."""
    start = ev.get("start", {}).get("dateTime", "")
    time_str = start.split("T")[1][:5] if "T" in start else "All day"
    summary = ev.get("summary", "Untitled")
    location = ev.get("location")

    if location:
        return f"  {time_str} — {summary} ({location})"
    return f"  {time_str} — {summary}"


def _handle_confirmation(chat_id: str):
    """Handle a 'confirm' intent — execute the pending action on the personal calendar."""
    pending = _pending_events.get(chat_id)

    if not pending:
        send_message(
            "I'm not sure what you're confirming. Could you tell me what you'd like to do?",
            chat_id,
        )
        return

    # Check if the pending event is stale (more than 10 minutes old)
    try:
        pending_time = datetime.fromisoformat(pending["timestamp"])
        age_minutes = (datetime.now() - pending_time).total_seconds() / 60
        if age_minutes > 10:
            send_message(
                "That request has expired. Could you tell me again what you'd like to do?",
                chat_id,
            )
            del _pending_events[chat_id]
            return
    except (ValueError, KeyError):
        pass

    action = pending.get("action")

    try:
        if action == "create":
            event = create_event(pending["event"])
            send_message(
                f"Done! <b>{event['summary']}</b> has been added to your personal calendar.",
                chat_id,
            )

        elif action == "modify":
            event = modify_event(pending["event_id"], pending["updates"])
            send_message(
                f"Done! <b>{event['summary']}</b> has been updated.",
                chat_id,
            )

        elif action == "cancel":
            cancel_event(pending["event_id"])
            title = pending.get("event_title", "The event")
            send_message(
                f"Done! <b>{title}</b> has been cancelled.",
                chat_id,
            )

    except Exception as e:
        logger.error(f"Error executing {action}: {e}", exc_info=True)
        send_message(
            "Sorry, something went wrong while updating the calendar. "
            "Could you try again?",
            chat_id,
        )

    finally:
        _pending_events.pop(chat_id, None)
