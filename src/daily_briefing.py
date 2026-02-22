"""
Daily Briefing Cloud Function.

Triggered by Google Cloud Scheduler every morning at 7:00 AM UK time.
Fetches today's schedule from both work and personal calendars,
generates a visual calendar card image, and sends it to the Telegram chat.

Falls back to a text-based briefing if image generation fails.

For local testing:
    functions-framework --target=daily_briefing --debug
    curl -X POST http://localhost:8080
"""

import logging
from datetime import datetime

import pytz
import functions_framework

from config import CALENDAR_TIMEZONE, DAILY_BRIEFING_ENABLED
from calendar_service import get_daily_schedule, get_weekly_schedule
from image_generator import generate_daily_briefing_image, generate_weekly_calendar_image
from telegram_service import send_photo, send_message, format_daily_briefing

logger = logging.getLogger(__name__)


@functions_framework.http
def daily_briefing(request):
    """
    Cloud Function entry point for the daily briefing.

    Called by Google Cloud Scheduler via HTTP POST.
    Fetches today's schedule from both calendars, generates a calendar
    card image, and sends it to the Telegram chat.
    """
    if not DAILY_BRIEFING_ENABLED:
        logger.info("Daily briefing is disabled, skipping")
        return "Briefing disabled", 200

    try:
        tz = pytz.timezone(CALENDAR_TIMEZONE)
        today = datetime.now(tz).strftime("%Y-%m-%d")

        logger.info(f"Generating daily briefing for {today}")

        schedule = get_daily_schedule(today)

        # Try to generate and send a visual calendar card
        try:
            image_bytes = generate_daily_briefing_image(schedule)
            send_photo(
                image_bytes,
                caption="Good morning! Here's today's schedule:",
            )
            logger.info("Daily briefing image sent successfully")

        except Exception as img_error:
            # Fall back to text-based briefing
            logger.warning(
                f"Image generation failed, falling back to text: {img_error}",
                exc_info=True,
            )
            message = format_daily_briefing(schedule)
            send_message(message)
            logger.info("Daily briefing sent as text (fallback)")

        # Also send the weekly calendar view
        try:
            weekly = get_weekly_schedule(today)
            weekly_image = generate_weekly_calendar_image(weekly)
            send_photo(weekly_image, caption="This week at a glance:")
            logger.info("Weekly calendar image sent successfully")
        except Exception as week_error:
            logger.warning(
                f"Weekly calendar image failed: {week_error}",
                exc_info=True,
            )

        return "OK", 200

    except Exception as e:
        logger.error(f"Failed to send daily briefing: {e}", exc_info=True)
        return f"Error: {str(e)}", 500
