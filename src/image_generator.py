"""
Image Generator -- creates visual calendar cards for the daily briefing.

Uses Pillow to render a clean, modern-looking schedule card as a PNG image.
The image is generated in-memory (BytesIO) and returned as bytes for
sending via Telegram's sendPhoto API.

Design:
- 800px wide, dynamic height based on event count
- Blue header with the date
- Colour-coded sections: teal (work), orange (personal)
- Rounded card on a light grey background
- Inter font for clean typography
"""

from __future__ import annotations

import io
import os
import logging
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
COLORS = {
    "bg_outer": "#F0F2F5",       # Light grey page background
    "bg_card": "#FFFFFF",         # White card
    "header_bg": "#4A90D9",       # Steel blue header
    "header_text": "#FFFFFF",     # White text on header
    "work_accent": "#2B8A8A",     # Teal for work events
    "personal_accent": "#E8734A", # Warm orange for personal events
    "text_dark": "#2D2D2D",       # Event titles
    "text_time": "#666666",       # Event times
    "text_location": "#999999",   # Location text
    "divider": "#E8E8E8",        # Section divider lines
    "empty_text": "#999999",     # "Nothing scheduled" text
}


# ---------------------------------------------------------------------------
# Layout constants (in pixels)
# ---------------------------------------------------------------------------
CARD_WIDTH = 800
OUTER_PADDING = 24
CARD_RADIUS = 16
CONTENT_X_LEFT = 50
CONTENT_X_RIGHT = CARD_WIDTH - OUTER_PADDING - 30

HEADER_HEIGHT = 90
HEADER_RADIUS = 16

SECTION_TOP_PAD = 28
SECTION_HEADER_HEIGHT = 30
SECTION_DIVIDER_PAD = 8
SECTION_DIVIDER_BOTTOM = 14

EVENT_DOT_RADIUS = 5
EVENT_LINE_HEIGHT = 24
EVENT_SPACING = 18
LOCATION_EXTRA_HEIGHT = 20

BOTTOM_PADDING = 30
EMPTY_DAY_HEIGHT = 60

MAX_TITLE_LENGTH = 50


# ---------------------------------------------------------------------------
# Font loading
# ---------------------------------------------------------------------------
FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")

_fonts = None


def _load_fonts() -> dict:
    """Load and cache font objects at various sizes."""
    global _fonts
    if _fonts is not None:
        return _fonts

    bold_path = os.path.join(FONTS_DIR, "Inter-Bold.ttf")
    regular_path = os.path.join(FONTS_DIR, "Inter-Regular.ttf")

    _fonts = {
        "header": ImageFont.truetype(bold_path, 30),
        "section": ImageFont.truetype(bold_path, 18),
        "time": ImageFont.truetype(regular_path, 16),
        "title": ImageFont.truetype(regular_path, 16),
        "location": ImageFont.truetype(regular_path, 13),
        "empty": ImageFont.truetype(regular_path, 16),
    }
    logger.info("Fonts loaded successfully")
    return _fonts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_daily_briefing_image(schedule: dict) -> bytes:
    """
    Generate a calendar card image for the daily briefing.

    Args:
        schedule: Dict from calendar_service.get_daily_schedule() with keys:
                  'date', 'work', 'personal'

    Returns:
        PNG image as bytes, ready for Telegram sendPhoto
    """
    fonts = _load_fonts()

    sections = _build_sections(schedule)
    height = _calculate_height(sections, fonts)

    img = Image.new("RGB", (CARD_WIDTH, height), COLORS["bg_outer"])
    draw = ImageDraw.Draw(img)

    # White card background with rounded corners
    card_x0 = OUTER_PADDING
    card_y0 = OUTER_PADDING
    card_x1 = CARD_WIDTH - OUTER_PADDING
    card_y1 = height - OUTER_PADDING
    draw.rounded_rectangle(
        [card_x0, card_y0, card_x1, card_y1],
        radius=CARD_RADIUS,
        fill=COLORS["bg_card"],
    )

    # Date header
    y = _draw_header(draw, schedule["date"], fonts, card_x0, card_y0, card_x1)

    # Sections
    for section in sections:
        y = _draw_section(draw, section, fonts, y, card_x0, card_x1)

    if not sections:
        y = _draw_empty_message(draw, fonts, y, card_x0, card_x1)

    # Export to PNG bytes
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)

    size_kb = len(buffer.getvalue()) / 1024
    logger.info(f"Generated calendar image: {CARD_WIDTH}x{height}px, {size_kb:.0f}KB")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Section building
# ---------------------------------------------------------------------------

def _build_sections(schedule: dict) -> list[dict]:
    """
    Convert the schedule into renderable sections.
    Work events first (teal), then personal events (orange).
    """
    sections = []

    if schedule.get("work"):
        sections.append({
            "title": "Work",
            "accent": COLORS["work_accent"],
            "events": schedule["work"],
        })

    if schedule.get("personal"):
        sections.append({
            "title": "Personal",
            "accent": COLORS["personal_accent"],
            "events": schedule["personal"],
        })

    return sections


# ---------------------------------------------------------------------------
# Height calculation
# ---------------------------------------------------------------------------

def _calculate_height(sections: list[dict], fonts: dict) -> int:
    """Calculate the total image height based on content."""
    h = OUTER_PADDING + HEADER_HEIGHT

    if not sections:
        h += EMPTY_DAY_HEIGHT
    else:
        for section in sections:
            h += SECTION_TOP_PAD
            h += SECTION_HEADER_HEIGHT
            h += SECTION_DIVIDER_PAD + 1 + SECTION_DIVIDER_BOTTOM

            for event in section["events"]:
                h += EVENT_LINE_HEIGHT
                if event.get("location"):
                    h += LOCATION_EXTRA_HEIGHT
                h += EVENT_SPACING

    h += BOTTOM_PADDING + OUTER_PADDING
    return h


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _draw_header(draw: ImageDraw, date_str: str, fonts: dict,
                 card_x0: int, card_y0: int, card_x1: int) -> int:
    """Draw the blue date header at the top of the card."""
    header_y0 = card_y0
    header_y1 = card_y0 + HEADER_HEIGHT

    draw.rounded_rectangle(
        [card_x0, header_y0, card_x1, header_y1 + HEADER_RADIUS],
        radius=HEADER_RADIUS,
        fill=COLORS["header_bg"],
    )
    draw.rectangle(
        [card_x0, header_y1, card_x1, header_y1 + HEADER_RADIUS],
        fill=COLORS["header_bg"],
    )

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        formatted_date = dt.strftime("%A, %d %B %Y")
    except (ValueError, TypeError):
        formatted_date = date_str or "Today"

    bbox = draw.textbbox((0, 0), formatted_date, font=fonts["header"])
    text_h = bbox[3] - bbox[1]
    text_y = header_y0 + (HEADER_HEIGHT - text_h) // 2

    draw.text(
        (CONTENT_X_LEFT, text_y),
        formatted_date,
        fill=COLORS["header_text"],
        font=fonts["header"],
    )

    return header_y1


def _draw_section(draw: ImageDraw, section: dict, fonts: dict,
                  y: int, card_x0: int, card_x1: int) -> int:
    """Draw a section (header + divider + events)."""
    accent = section["accent"]

    y += SECTION_TOP_PAD
    draw.text(
        (CONTENT_X_LEFT, y),
        section["title"],
        fill=accent,
        font=fonts["section"],
    )
    y += SECTION_HEADER_HEIGHT

    y += SECTION_DIVIDER_PAD
    draw.line(
        [(CONTENT_X_LEFT, y), (card_x1 - 30, y)],
        fill=COLORS["divider"],
        width=1,
    )
    y += 1 + SECTION_DIVIDER_BOTTOM

    for event in section["events"]:
        y = _draw_event(draw, event, accent, fonts, y)

    return y


def _draw_event(draw: ImageDraw, event: dict, accent: str,
                fonts: dict, y: int) -> int:
    """Draw a single event line (dot + time + title, optional location)."""
    # Coloured dot
    dot_x = CONTENT_X_LEFT + 4
    dot_y = y + EVENT_LINE_HEIGHT // 2
    draw.ellipse(
        [dot_x - EVENT_DOT_RADIUS, dot_y - EVENT_DOT_RADIUS,
         dot_x + EVENT_DOT_RADIUS, dot_y + EVENT_DOT_RADIUS],
        fill=accent,
    )

    # Time text
    time_str = _format_event_time(event)
    time_x = CONTENT_X_LEFT + 22
    draw.text(
        (time_x, y),
        time_str,
        fill=COLORS["text_time"],
        font=fonts["time"],
    )

    # Event title
    time_bbox = draw.textbbox((0, 0), time_str, font=fonts["time"])
    time_width = time_bbox[2] - time_bbox[0]
    title_x = time_x + time_width + 12

    title = event.get("title", "Untitled")
    if len(title) > MAX_TITLE_LENGTH:
        title = title[:MAX_TITLE_LENGTH - 1] + "..."

    draw.text(
        (title_x, y),
        title,
        fill=COLORS["text_dark"],
        font=fonts["title"],
    )

    y += EVENT_LINE_HEIGHT

    # Location
    location = event.get("location")
    if location:
        loc_x = time_x
        loc_text = f"\u2022 {location}"
        if len(loc_text) > MAX_TITLE_LENGTH + 5:
            loc_text = loc_text[:MAX_TITLE_LENGTH + 4] + "..."

        draw.text(
            (loc_x, y),
            loc_text,
            fill=COLORS["text_location"],
            font=fonts["location"],
        )
        y += LOCATION_EXTRA_HEIGHT

    y += EVENT_SPACING
    return y


def _draw_empty_message(draw: ImageDraw, fonts: dict, y: int,
                        card_x0: int, card_x1: int) -> int:
    """Draw the 'nothing scheduled' message for empty days."""
    y += SECTION_TOP_PAD
    message = "Nothing scheduled -- enjoy the free day!"

    bbox = draw.textbbox((0, 0), message, font=fonts["empty"])
    text_w = bbox[2] - bbox[0]
    text_x = card_x0 + (card_x1 - card_x0 - text_w) // 2

    draw.text(
        (text_x, y),
        message,
        fill=COLORS["empty_text"],
        font=fonts["empty"],
    )

    y += EMPTY_DAY_HEIGHT
    return y


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _format_event_time(event: dict) -> str:
    """Extract a display time from an event's start field."""
    start = event.get("start", "")

    if not start:
        return "All day"

    if "T" in start:
        time_part = start.split("T")[1][:5]
        return time_part

    return "All day"
