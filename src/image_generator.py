"""
Image Generator -- creates visual calendar cards and weekly calendar views.

Uses Pillow to render images in-memory (BytesIO) as PNG bytes for Telegram.

Two image types:
1. Daily briefing card (800px wide, list-style, dynamic height)
2. Weekly calendar view (1400px wide, Google Calendar-like grid with time blocks)
"""

from __future__ import annotations

import io
import os
import logging
from datetime import datetime, timedelta

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
        # Daily briefing card fonts
        "header": ImageFont.truetype(bold_path, 30),
        "section": ImageFont.truetype(bold_path, 18),
        "time": ImageFont.truetype(regular_path, 16),
        "title": ImageFont.truetype(regular_path, 16),
        "location": ImageFont.truetype(regular_path, 13),
        "empty": ImageFont.truetype(regular_path, 16),
        # Weekly calendar view fonts
        "week_header": ImageFont.truetype(bold_path, 22),
        "day_name": ImageFont.truetype(bold_path, 14),
        "day_date": ImageFont.truetype(regular_path, 12),
        "sub_label": ImageFont.truetype(bold_path, 9),
        "grid_hour": ImageFont.truetype(regular_path, 11),
        "event_title_sm": ImageFont.truetype(bold_path, 10),
        "event_time_sm": ImageFont.truetype(regular_path, 9),
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


# ===========================================================================
# Weekly Calendar View (Google Calendar-like grid)
# ===========================================================================

# Layout constants for the weekly view
WEEK_WIDTH = 1400
WEEK_OUTER_PAD = 16
WEEK_HEADER_HEIGHT = 56
WEEK_DAY_HEADER_HEIGHT = 48
WEEK_TIME_GUTTER = 56          # Width of the time labels column on the left
WEEK_HOUR_HEIGHT = 50          # Pixels per hour row
WEEK_START_HOUR = 7            # Grid starts at 07:00
WEEK_END_HOUR = 22             # Grid ends at 22:00 (15 hours visible)
WEEK_COL_GAP = 4               # Gap between day columns
WEEK_SUB_GAP = 3               # Gap between personal and work sub-columns
WEEK_EVENT_PAD = 3             # Padding inside event blocks
WEEK_EVENT_RADIUS = 4          # Rounded corner radius for event blocks
WEEK_MIN_EVENT_H = 22          # Minimum event block height (for very short events)

# Derived
WEEK_GRID_HOURS = WEEK_END_HOUR - WEEK_START_HOUR
WEEK_GRID_HEIGHT = WEEK_GRID_HOURS * WEEK_HOUR_HEIGHT
WEEK_TOTAL_HEIGHT = (
    WEEK_OUTER_PAD + WEEK_HEADER_HEIGHT + WEEK_DAY_HEADER_HEIGHT
    + WEEK_GRID_HEIGHT + WEEK_OUTER_PAD
)

# Colors specific to the weekly view
WEEK_COLORS = {
    "grid_line": "#ECECEC",
    "grid_line_dark": "#DCDCDC",
    "today_bg": "#EEF4FF",       # Light blue highlight for today's column
    "work_block": "#2B8A8A",     # Teal event block
    "work_block_light": "#D6F0F0",
    "personal_block": "#E8734A", # Orange event block
    "personal_block_light": "#FDEADF",
    "event_text": "#FFFFFF",
}


def generate_weekly_calendar_image(weekly_schedule: list[dict]) -> bytes:
    """
    Generate a Google Calendar-like week view image.

    Args:
        weekly_schedule: List of 5 daily schedule dicts (Mon-Fri) from
                         calendar_service.get_weekly_schedule(). Each dict has:
                         {"date": "YYYY-MM-DD", "work": [...], "personal": [...]}

    Returns:
        PNG image as bytes, ready for Telegram sendPhoto
    """
    fonts = _load_fonts()

    img = Image.new("RGB", (WEEK_WIDTH, WEEK_TOTAL_HEIGHT), COLORS["bg_outer"])
    draw = ImageDraw.Draw(img)

    # Card background
    card_x0 = WEEK_OUTER_PAD
    card_y0 = WEEK_OUTER_PAD
    card_x1 = WEEK_WIDTH - WEEK_OUTER_PAD
    card_y1 = WEEK_TOTAL_HEIGHT - WEEK_OUTER_PAD
    draw.rounded_rectangle(
        [card_x0, card_y0, card_x1, card_y1],
        radius=12,
        fill=COLORS["bg_card"],
    )

    # Calculate column geometry
    usable_width = (card_x1 - card_x0) - WEEK_TIME_GUTTER
    day_col_width = (usable_width - WEEK_COL_GAP * 4) // 5
    grid_x_start = card_x0 + WEEK_TIME_GUTTER
    grid_y_start = card_y0 + WEEK_HEADER_HEIGHT + WEEK_DAY_HEADER_HEIGHT

    # 1. Draw header
    _week_draw_header(draw, weekly_schedule, fonts, card_x0, card_y0, card_x1)

    # 2. Draw day column headers
    today_str = datetime.now().strftime("%Y-%m-%d")
    for i, day in enumerate(weekly_schedule):
        col_x = grid_x_start + i * (day_col_width + WEEK_COL_GAP)
        is_today = (day["date"] == today_str)

        # Highlight today's column
        if is_today:
            draw.rectangle(
                [col_x, grid_y_start, col_x + day_col_width, card_y1],
                fill=WEEK_COLORS["today_bg"],
            )

        _week_draw_day_header(draw, day["date"], is_today, fonts,
                              col_x, card_y0 + WEEK_HEADER_HEIGHT,
                              day_col_width)

    # 3. Draw time gutter and grid lines
    _week_draw_grid(draw, fonts, card_x0, grid_x_start, grid_y_start,
                    card_x1, day_col_width, len(weekly_schedule))

    # 4. Draw events for each day
    for i, day in enumerate(weekly_schedule):
        col_x = grid_x_start + i * (day_col_width + WEEK_COL_GAP)
        sub_w = (day_col_width - WEEK_SUB_GAP) // 2

        # Personal events in left sub-column
        for event in day.get("personal", []):
            _week_draw_event_block(
                draw, event, fonts,
                x=col_x,
                width=sub_w,
                grid_y_start=grid_y_start,
                color=WEEK_COLORS["personal_block"],
                light_color=WEEK_COLORS["personal_block_light"],
            )

        # Work events in right sub-column
        for event in day.get("work", []):
            _week_draw_event_block(
                draw, event, fonts,
                x=col_x + sub_w + WEEK_SUB_GAP,
                width=sub_w,
                grid_y_start=grid_y_start,
                color=WEEK_COLORS["work_block"],
                light_color=WEEK_COLORS["work_block_light"],
            )

    # 5. Draw legend at bottom-right of header
    _week_draw_legend(draw, fonts, card_x1, card_y0)

    # Export
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)

    size_kb = len(buffer.getvalue()) / 1024
    logger.info(f"Generated weekly calendar: {WEEK_WIDTH}x{WEEK_TOTAL_HEIGHT}px, {size_kb:.0f}KB")
    return buffer.getvalue()


def _week_draw_header(draw: ImageDraw, schedule: list[dict], fonts: dict,
                      card_x0: int, card_y0: int, card_x1: int):
    """Draw the blue week title header."""
    header_y0 = card_y0
    header_y1 = card_y0 + WEEK_HEADER_HEIGHT

    # Blue header band (rounded top, flat bottom)
    draw.rounded_rectangle(
        [card_x0, header_y0, card_x1, header_y1 + 12],
        radius=12,
        fill=COLORS["header_bg"],
    )
    draw.rectangle(
        [card_x0, header_y1, card_x1, header_y1 + 12],
        fill=COLORS["header_bg"],
    )

    # "Week of 24 - 28 February 2026"
    if schedule:
        try:
            mon = datetime.strptime(schedule[0]["date"], "%Y-%m-%d")
            fri = datetime.strptime(schedule[-1]["date"], "%Y-%m-%d")
            if mon.month == fri.month:
                title = f"Week of {mon.day} - {fri.day} {fri.strftime('%B %Y')}"
            else:
                title = f"Week of {mon.strftime('%d %b')} - {fri.strftime('%d %b %Y')}"
        except (ValueError, IndexError):
            title = "This Week"
    else:
        title = "This Week"

    bbox = draw.textbbox((0, 0), title, font=fonts["week_header"])
    text_h = bbox[3] - bbox[1]
    text_y = header_y0 + (WEEK_HEADER_HEIGHT - text_h) // 2

    draw.text(
        (card_x0 + 24, text_y),
        title,
        fill=COLORS["header_text"],
        font=fonts["week_header"],
    )


def _week_draw_day_header(draw: ImageDraw, date_str: str, is_today: bool,
                          fonts: dict, col_x: int, y: int, col_w: int):
    """Draw a single day column header (day name + date + P/W labels)."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day_name = dt.strftime("%a")   # "Mon"
        day_date = dt.strftime("%d")   # "24"
    except (ValueError, TypeError):
        day_name = "?"
        day_date = "?"

    # Day name (bold, centred)
    name_color = COLORS["header_bg"] if is_today else COLORS["text_dark"]
    bbox = draw.textbbox((0, 0), day_name, font=fonts["day_name"])
    name_w = bbox[2] - bbox[0]
    draw.text(
        (col_x + (col_w - name_w) // 2, y + 4),
        day_name,
        fill=name_color,
        font=fonts["day_name"],
    )

    # Date number
    bbox = draw.textbbox((0, 0), day_date, font=fonts["day_date"])
    date_w = bbox[2] - bbox[0]
    draw.text(
        (col_x + (col_w - date_w) // 2, y + 20),
        day_date,
        fill=name_color,
        font=fonts["day_date"],
    )

    # P / W sub-column labels
    sub_w = (col_w - WEEK_SUB_GAP) // 2
    draw.text(
        (col_x + sub_w // 2 - 3, y + 36),
        "P",
        fill=COLORS["personal_accent"],
        font=fonts["sub_label"],
    )
    draw.text(
        (col_x + sub_w + WEEK_SUB_GAP + sub_w // 2 - 3, y + 36),
        "W",
        fill=WEEK_COLORS["work_block"],
        font=fonts["sub_label"],
    )


def _week_draw_grid(draw: ImageDraw, fonts: dict, card_x0: int,
                    grid_x_start: int, grid_y_start: int, card_x1: int,
                    day_col_width: int, num_days: int):
    """Draw the time gutter labels, horizontal hour lines, and vertical day separators."""
    # Horizontal hour lines and time labels
    for h in range(WEEK_GRID_HOURS + 1):
        y = grid_y_start + h * WEEK_HOUR_HEIGHT
        hour = WEEK_START_HOUR + h

        # Hour label in the gutter
        if hour <= WEEK_END_HOUR:
            label = f"{hour:02d}:00"
            draw.text(
                (card_x0 + 8, y - 6),
                label,
                fill=COLORS["text_time"],
                font=fonts["grid_hour"],
            )

        # Horizontal line across all columns
        line_color = WEEK_COLORS["grid_line_dark"] if h == 0 else WEEK_COLORS["grid_line"]
        draw.line(
            [(grid_x_start, y), (card_x1 - WEEK_OUTER_PAD, y)],
            fill=line_color,
            width=1,
        )

    # Vertical separators between day columns
    for i in range(1, num_days):
        x = grid_x_start + i * (day_col_width + WEEK_COL_GAP) - WEEK_COL_GAP // 2
        draw.line(
            [(x, grid_y_start), (x, grid_y_start + WEEK_GRID_HEIGHT)],
            fill=WEEK_COLORS["grid_line"],
            width=1,
        )


def _week_draw_event_block(draw: ImageDraw, event: dict, fonts: dict,
                           x: int, width: int, grid_y_start: int,
                           color: str, light_color: str):
    """
    Draw a single event as a colored block on the grid.

    The block's vertical position and height are proportional to the
    event's start/end times, like Google Calendar.
    """
    start_str = event.get("start", "")
    end_str = event.get("end", "")

    if not start_str or "T" not in start_str:
        return  # Skip all-day events for now

    # Parse hours and minutes
    try:
        start_hour, start_min = int(start_str[11:13]), int(start_str[14:16])
        if end_str and "T" in end_str:
            end_hour, end_min = int(end_str[11:13]), int(end_str[14:16])
        else:
            end_hour, end_min = start_hour + 1, start_min
    except (ValueError, IndexError):
        return

    # Clamp to grid boundaries
    start_hour_f = max(start_hour + start_min / 60, WEEK_START_HOUR)
    end_hour_f = min(end_hour + end_min / 60, WEEK_END_HOUR)

    if end_hour_f <= start_hour_f:
        return  # Event is fully outside the visible grid

    # Calculate Y coordinates
    y_start = grid_y_start + int((start_hour_f - WEEK_START_HOUR) * WEEK_HOUR_HEIGHT)
    y_end = grid_y_start + int((end_hour_f - WEEK_START_HOUR) * WEEK_HOUR_HEIGHT)

    # Enforce minimum height
    if (y_end - y_start) < WEEK_MIN_EVENT_H:
        y_end = y_start + WEEK_MIN_EVENT_H

    # Draw the event block — solid color with slight rounding
    draw.rounded_rectangle(
        [x + 1, y_start + 1, x + width - 1, y_end - 1],
        radius=WEEK_EVENT_RADIUS,
        fill=color,
    )

    # Draw event title inside the block (white text)
    title = event.get("title", "Untitled")
    max_chars = max(width // 7, 5)  # Rough estimate of chars that fit
    if len(title) > max_chars:
        title = title[:max_chars - 1] + "…"

    draw.text(
        (x + WEEK_EVENT_PAD + 2, y_start + WEEK_EVENT_PAD + 1),
        title,
        fill=WEEK_COLORS["event_text"],
        font=fonts["event_title_sm"],
    )

    # If the block is tall enough, show the time below the title
    block_height = y_end - y_start
    if block_height >= 38:
        time_label = f"{start_hour:02d}:{start_min:02d}"
        draw.text(
            (x + WEEK_EVENT_PAD + 2, y_start + WEEK_EVENT_PAD + 14),
            time_label,
            fill=WEEK_COLORS["event_text"],
            font=fonts["event_time_sm"],
        )


def _week_draw_legend(draw: ImageDraw, fonts: dict, card_x1: int, card_y0: int):
    """Draw a small legend in the header area (Personal / Work indicators)."""
    y = card_y0 + 20
    x = card_x1 - 200

    # Personal dot + label
    draw.ellipse(
        [x, y + 2, x + 10, y + 12],
        fill=COLORS["personal_accent"],
    )
    draw.text(
        (x + 14, y),
        "Personal",
        fill=COLORS["header_text"],
        font=fonts["day_date"],
    )

    # Work dot + label
    x += 80
    draw.ellipse(
        [x, y + 2, x + 10, y + 12],
        fill=WEEK_COLORS["work_block"],
    )
    draw.text(
        (x + 14, y),
        "Work",
        fill=COLORS["header_text"],
        font=fonts["day_date"],
    )
