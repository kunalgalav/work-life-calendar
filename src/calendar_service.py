from __future__ import annotations

"""
Google Calendar Service — manages work and personal calendars.

Dual-calendar setup:
- Personal calendar (PERSONAL_CALENDAR_ID): read-write — all new events go here
- Work calendar (WORK_CALENDAR_ID): read-only — shown in briefings and conflict checks

Both calendars have been shared with the same Google Service Account
(calendar-bot@family-calendar-bot-488016.iam.gserviceaccount.com).
The work calendar is shared as read-only ("See all event details").
The personal calendar is shared as read-write ("Make changes to events").
"""

import logging
from datetime import datetime, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import (
    get_google_credentials,
    PERSONAL_CALENDAR_ID,
    WORK_CALENDAR_ID,
    CALENDAR_TIMEZONE,
)

logger = logging.getLogger(__name__)

# Google Calendar API scopes — we need full read/write access
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Module-level service instance (reused across Cloud Function invocations)
_service = None


def _get_service():
    """
    Build and cache the Google Calendar API service.

    Uses the same Service Account as the family-calendar-bot.
    """
    global _service
    if _service is not None:
        return _service

    creds_data = get_google_credentials()
    credentials = service_account.Credentials.from_service_account_info(
        creds_data, scopes=SCOPES
    )
    _service = build("calendar", "v3", credentials=credentials)
    logger.info("Google Calendar service initialised")
    return _service


def _build_event_body(event_data: dict) -> dict:
    """
    Convert our internal event dict into a Google Calendar API event body.

    Args:
        event_data: Dict with title, date, start_time, end_time, location, description

    Returns:
        Google Calendar API event resource
    """
    start_dt = f"{event_data['date']}T{event_data['start_time']}:00"
    end_dt = f"{event_data['date']}T{event_data['end_time']}:00"

    body = {
        "summary": event_data.get("title", "Untitled Event"),
        "start": {
            "dateTime": start_dt,
            "timeZone": CALENDAR_TIMEZONE,
        },
        "end": {
            "dateTime": end_dt,
            "timeZone": CALENDAR_TIMEZONE,
        },
        "reminders": {
            "useDefault": True,
        },
    }

    if event_data.get("location"):
        body["location"] = event_data["location"]

    if event_data.get("description"):
        body["description"] = event_data["description"]

    return body


def create_event(event_data: dict) -> dict:
    """
    Create a new event on the PERSONAL calendar only.

    Work calendar is read-only — we never write to it.

    Args:
        event_data: Dict with title, date, start_time, end_time, location, description

    Returns:
        The created event resource from Google Calendar API
    """
    service = _get_service()
    body = _build_event_body(event_data)

    try:
        event = (
            service.events()
            .insert(
                calendarId=PERSONAL_CALENDAR_ID,
                body=body,
            )
            .execute()
        )
        logger.info(f"Created event on personal calendar: {event['summary']} ({event['id']})")
        return event

    except HttpError as e:
        logger.error(f"Failed to create event: {e}")
        raise


def _query_single_calendar(calendar_id: str, start_date: str, end_date: str) -> list[dict]:
    """
    Query events from a single calendar within a date range.

    Args:
        calendar_id: The Google Calendar ID to query
        start_date: Start of range in YYYY-MM-DD format
        end_date: End of range in YYYY-MM-DD format

    Returns:
        List of event dicts
    """
    service = _get_service()

    time_min = f"{start_date}T00:00:00Z"
    time_max = f"{end_date}T23:59:59Z"

    try:
        result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                timeZone=CALENDAR_TIMEZONE,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = result.get("items", [])
        logger.info(f"Found {len(events)} events on {calendar_id} between {start_date} and {end_date}")
        return events

    except HttpError as e:
        logger.error(f"Failed to query events from {calendar_id}: {e}")
        # Don't raise — if one calendar fails, we still want the other
        return []


def query_events(start_date: str, end_date: str, calendar: str = "both") -> list[dict]:
    """
    Query events within a date range from one or both calendars.

    Args:
        start_date: Start of range in YYYY-MM-DD format
        end_date: End of range in YYYY-MM-DD format
        calendar: "work", "personal", or "both" (default)

    Returns:
        List of event dicts, sorted by start time. Each event has an extra
        '_calendar' field ("work" or "personal") for display purposes.
    """
    events = []

    if calendar in ("both", "work"):
        work_events = _query_single_calendar(WORK_CALENDAR_ID, start_date, end_date)
        for e in work_events:
            e["_calendar"] = "work"
        events.extend(work_events)

    if calendar in ("both", "personal"):
        personal_events = _query_single_calendar(PERSONAL_CALENDAR_ID, start_date, end_date)
        for e in personal_events:
            e["_calendar"] = "personal"
        events.extend(personal_events)

    # Sort all events by start time
    def sort_key(e):
        dt = e.get("start", {}).get("dateTime", "")
        return dt if dt else "9999"

    events.sort(key=sort_key)
    return events


def find_event_by_title(title: str, date: str = None) -> dict | None:
    """
    Find an event by fuzzy-matching its title.

    Only searches the PERSONAL calendar — work events are read-only
    and can't be modified or cancelled through this bot.

    Args:
        title: The event title to search for (fuzzy match)
        date: Optional date to narrow the search (YYYY-MM-DD)

    Returns:
        The matching event dict, or None if not found
    """
    if date:
        start_date = date
        end_date = date
    else:
        today = datetime.now()
        start_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        end_date = (today + timedelta(days=30)).strftime("%Y-%m-%d")

    events = query_events(start_date, end_date, calendar="personal")

    title_lower = title.lower()
    for event in events:
        summary = event.get("summary", "").lower()
        if title_lower in summary or summary in title_lower:
            logger.info(f"Found matching event: {event['summary']} ({event['id']})")
            return event

    logger.info(f"No event found matching '{title}' on personal calendar")
    return None


def modify_event(event_id: str, updates: dict) -> dict:
    """
    Modify an existing event on the PERSONAL calendar.

    Args:
        event_id: The Google Calendar event ID
        updates: Dict with fields to update (title, date, start_time, end_time, location)

    Returns:
        The updated event resource
    """
    service = _get_service()

    try:
        # Fetch the existing event from personal calendar
        event = (
            service.events()
            .get(calendarId=PERSONAL_CALENDAR_ID, eventId=event_id)
            .execute()
        )

        if updates.get("title"):
            event["summary"] = updates["title"]

        if updates.get("date") and updates.get("start_time"):
            event["start"] = {
                "dateTime": f"{updates['date']}T{updates['start_time']}:00",
                "timeZone": CALENDAR_TIMEZONE,
            }
        elif updates.get("start_time"):
            existing_date = event["start"]["dateTime"][:10]
            event["start"] = {
                "dateTime": f"{existing_date}T{updates['start_time']}:00",
                "timeZone": CALENDAR_TIMEZONE,
            }

        if updates.get("date") and updates.get("end_time"):
            event["end"] = {
                "dateTime": f"{updates['date']}T{updates['end_time']}:00",
                "timeZone": CALENDAR_TIMEZONE,
            }
        elif updates.get("end_time"):
            existing_date = event["end"]["dateTime"][:10]
            event["end"] = {
                "dateTime": f"{existing_date}T{updates['end_time']}:00",
                "timeZone": CALENDAR_TIMEZONE,
            }

        if updates.get("location"):
            event["location"] = updates["location"]

        if updates.get("description"):
            event["description"] = updates["description"]

        updated = (
            service.events()
            .update(
                calendarId=PERSONAL_CALENDAR_ID,
                eventId=event_id,
                body=event,
            )
            .execute()
        )
        logger.info(f"Modified event: {updated['summary']} ({updated['id']})")
        return updated

    except HttpError as e:
        logger.error(f"Failed to modify event {event_id}: {e}")
        raise


def cancel_event(event_id: str) -> bool:
    """
    Cancel (delete) an event from the PERSONAL calendar.

    Args:
        event_id: The Google Calendar event ID

    Returns:
        True if successfully deleted
    """
    service = _get_service()

    try:
        service.events().delete(
            calendarId=PERSONAL_CALENDAR_ID,
            eventId=event_id,
        ).execute()
        logger.info(f"Cancelled event: {event_id}")
        return True

    except HttpError as e:
        logger.error(f"Failed to cancel event {event_id}: {e}")
        raise


def check_conflicts(date: str, start_time: str, end_time: str) -> list[dict]:
    """
    Check for conflicting events at the proposed time across BOTH calendars.

    This is the key benefit of the dual-calendar setup — when you're about
    to add a personal event, the bot checks your work calendar too.

    Args:
        date: Date in YYYY-MM-DD format
        start_time: Start time in HH:MM format
        end_time: End time in HH:MM format

    Returns:
        List of conflicting events (empty if no conflicts).
        Each event has '_calendar' field ("work" or "personal").
    """
    # Query both calendars for the day
    events = query_events(date, date, calendar="both")

    proposed_start = datetime.strptime(f"{date} {start_time}", "%Y-%m-%d %H:%M")
    proposed_end = datetime.strptime(f"{date} {end_time}", "%Y-%m-%d %H:%M")

    conflicts = []
    for event in events:
        event_start_str = event.get("start", {}).get("dateTime")
        event_end_str = event.get("end", {}).get("dateTime")
        if not event_start_str or not event_end_str:
            continue

        event_start = datetime.fromisoformat(event_start_str)
        event_end = datetime.fromisoformat(event_end_str)

        # Make naive for comparison (same timezone)
        event_start = event_start.replace(tzinfo=None)
        event_end = event_end.replace(tzinfo=None)

        if proposed_start < event_end and proposed_end > event_start:
            conflicts.append(event)

    if conflicts:
        titles = [f"{c.get('summary', 'Untitled')} ({c.get('_calendar', '?')})" for c in conflicts]
        logger.info(f"Found {len(conflicts)} conflicts: {titles}")
    else:
        logger.info(f"No conflicts found for {date} {start_time}-{end_time}")

    return conflicts


def get_daily_schedule(date: str) -> dict:
    """
    Get the full day's schedule, split by work vs personal.

    Used for the daily briefing message.

    Args:
        date: Date in YYYY-MM-DD format

    Returns:
        Dict with 'work' and 'personal' event lists:
        {
            "date": "2026-02-22",
            "work": [{"title": "...", "start": "...", ...}, ...],
            "personal": [{"title": "...", "start": "...", ...}, ...],
        }
    """
    all_events = query_events(date, date, calendar="both")

    result = {
        "date": date,
        "work": [],
        "personal": [],
    }

    for event in all_events:
        simple_event = {
            "id": event.get("id"),
            "title": event.get("summary", "Untitled"),
            "start": event.get("start", {}).get("dateTime", ""),
            "end": event.get("end", {}).get("dateTime", ""),
            "location": event.get("location"),
        }

        if event.get("_calendar") == "work":
            result["work"].append(simple_event)
        else:
            result["personal"].append(simple_event)

    return result


def get_weekly_schedule(start_date: str = None) -> list[dict]:
    """
    Get the Mon-Fri schedule for the current week, split by work vs personal.

    Fetches all events in one API call per calendar, then groups by day.

    Args:
        start_date: Optional YYYY-MM-DD to anchor the week. If None, uses today.
                    The function finds the Monday of that week.

    Returns:
        List of 5 daily schedule dicts (Mon-Fri), each with:
        {"date": "YYYY-MM-DD", "work": [...], "personal": [...]}
    """
    if start_date:
        anchor = datetime.strptime(start_date, "%Y-%m-%d")
    else:
        anchor = datetime.now()

    # Find Monday of this week (weekday() returns 0=Mon, 6=Sun)
    monday = anchor - timedelta(days=anchor.weekday())
    friday = monday + timedelta(days=4)

    monday_str = monday.strftime("%Y-%m-%d")
    friday_str = friday.strftime("%Y-%m-%d")

    # Single API call for the full range across both calendars
    all_events = query_events(monday_str, friday_str, calendar="both")

    # Build 5 empty day buckets
    days = []
    for i in range(5):
        day_date = (monday + timedelta(days=i)).strftime("%Y-%m-%d")
        days.append({"date": day_date, "work": [], "personal": []})

    # Group events into the correct day bucket
    for event in all_events:
        start_str = event.get("start", {}).get("dateTime", "")
        if not start_str:
            continue

        # Extract the date portion from ISO 8601 datetime
        event_date = start_str[:10]

        # Find the matching day bucket
        for day in days:
            if day["date"] == event_date:
                simple_event = {
                    "id": event.get("id"),
                    "title": event.get("summary", "Untitled"),
                    "start": start_str,
                    "end": event.get("end", {}).get("dateTime", ""),
                    "location": event.get("location"),
                }

                if event.get("_calendar") == "work":
                    day["work"].append(simple_event)
                else:
                    day["personal"].append(simple_event)
                break

    return days
