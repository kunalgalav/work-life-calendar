"""
Image Generator -- creates visual calendar cards and per-day calendar views.

Uses Pillow to render images in-memory (BytesIO) as PNG bytes for Telegram.

Three image types:
1. Daily briefing card (800px wide, list-style, dynamic height)
2. Single-day calendar view (800px wide, Google Calendar-like grid with
   Personal/Work columns side-by-side). Crisp and clear on mobile.
3. Weekly calendar views — simply 5 individual day images (Mon-Fri).
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
# Layout constants for the daily briefing card (in pixels)
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
        # Per-day calendar view fonts (larger, since each day has its own image)
        "day_header": ImageFont.truetype(bold_path, 26),
        "col_label": ImageFont.truetype(bold_path, 16),
        "grid_hour": ImageFont.truetype(regular_path, 13),
        "event_title": ImageFont.truetype(bold_path, 13),
        "event_time": ImageFont.truetype(regular_path, 12),
        "legend": ImageFont.truetype(regular_path, 13),
        "empty_day": ImageFont.truetype(regular_path, 15),
    }
    logger.info("Fonts loaded successfully")
    return _fonts


# ===========================================================================
# 1. DAILY BRIEFING CARD (list-style, same as before)
# ===========================================================================

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
# Drawing helpers (briefing card)
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
# 2. SINGLE-DAY CALENDAR VIEW (one crisp image per day)
# ===========================================================================
#
# Each day gets its own 800px-wide image with:
#   - Blue header showing the day name and date
#   - Two side-by-side columns: Personal (orange) | Work (teal)
#   - Time grid from 07:00 to 22:00
#   - Event blocks proportional to their duration
#
# This replaces the old cramped weekly grid that was blurry on Telegram.
# ===========================================================================

# Layout constants for the per-day view
DAY_VIEW_WIDTH = 800
DAY_VIEW_OUTER_PAD = 16
DAY_VIEW_HEADER_H = 64
DAY_VIEW_COL_HEADER_H = 36
DAY_VIEW_TIME_GUTTER = 60     # Width for the time labels on the left
DAY_VIEW_HOUR_HEIGHT = 56     # Pixels per hour — taller than old weekly view
DAY_VIEW_START_HOUR = 7
DAY_VIEW_END_HOUR = 22
DAY_VIEW_COL_GAP = 8          # Gap between Personal and Work columns
DAY_VIEW_EVENT_PAD = 5
DAY_VIEW_EVENT_RADIUS = 6
DAY_VIEW_MIN_EVENT_H = 26

# Derived
DAY_VIEW_GRID_HOURS = DAY_VIEW_END_HOUR - DAY_VIEW_START_HOUR
DAY_VIEW_GRID_HEIGHT = DAY_VIEW_GRID_HOURS * DAY_VIEW_HOUR_HEIGHT
DAY_VIEW_TOTAL_HEIGHT = (
    DAY_VIEW_OUTER_PAD
    + DAY_VIEW_HEADER_H
    + DAY_VIEW_COL_HEADER_H
    + DAY_VIEW_GRID_HEIGHT
    + DAY_VIEW_OUTER_PAD
)

# Colors specific to the day view
DAY_VIEW_COLORS = {
    "grid_line": "#ECECEC",
    "grid_line_dark": "#DCDCDC",
    "today_bg": "#EEF4FF",       # Light blue tint for today
    "work_block": "#2B8A8A",
    "personal_block": "#E8734A",
    "event_text": "#FFFFFF",
}


def generate_single_day_calendar_image(schedule: dict) -> bytes:
    """
    Generate a Google Calendar-like grid image for ONE day.

    Two side-by-side columns — Personal (left, orange) and Work (right, teal) —
    with a 07:00-22:00 time grid and proportionally positioned event blocks.

    Args:
        schedule: Dict with 'date', 'work', 'personal' (same shape as
                  calendar_service.get_daily_schedule()).

    Returns:
        PNG image as bytes, ready for Telegram sendPhoto.
    """
    fonts = _load_fonts()

    img = Image.new("RGB", (DAY_VIEW_WIDTH, DAY_VIEW_TOTAL_HEIGHT), COLORS["bg_outer"])
    draw = ImageDraw.Draw(img)

    # Card background
    cx0 = DAY_VIEW_OUTER_PAD
    cy0 = DAY_VIEW_OUTER_PAD
    cx1 = DAY_VIEW_WIDTH - DAY_VIEW_OUTER_PAD
    cy1 = DAY_VIEW_TOTAL_HEIGHT - DAY_VIEW_OUTER_PAD
    draw.rounded_rectangle([cx0, cy0, cx1, cy1], radius=12, fill=COLORS["bg_card"])

    # Calculate column geometry
    grid_x_start = cx0 + DAY_VIEW_TIME_GUTTER
    usable_width = (cx1 - grid_x_start) - DAY_VIEW_COL_GAP
    col_w = usable_width // 2
    grid_y_start = cy0 + DAY_VIEW_HEADER_H + DAY_VIEW_COL_HEADER_H

    # Check if this is today
    today_str = datetime.now().strftime("%Y-%m-%d")
    is_today = (schedule.get("date", "") == today_str)

    # Optional light blue background tint for today
    if is_today:
        draw.rectangle(
            [grid_x_start, grid_y_start, cx1, cy1],
            fill=DAY_VIEW_COLORS["today_bg"],
        )

    # 1. Draw the header
    _dayview_draw_header(draw, schedule["date"], is_today, fonts, cx0, cy0, cx1)

    # 2. Draw column sub-headers (Personal | Work)
    _dayview_draw_col_headers(draw, fonts, grid_x_start, cy0 + DAY_VIEW_HEADER_H,
                              col_w, DAY_VIEW_COL_GAP)

    # 3. Draw the time grid (hour labels + lines)
    _dayview_draw_grid(draw, fonts, cx0, grid_x_start, grid_y_start, cx1)

    # 4. Draw events — Personal in left column, Work in right column
    personal_x = grid_x_start
    work_x = grid_x_start + col_w + DAY_VIEW_COL_GAP

    for event in schedule.get("personal", []):
        _dayview_draw_event_block(
            draw, event, fonts,
            x=personal_x, width=col_w,
            grid_y_start=grid_y_start,
            color=DAY_VIEW_COLORS["personal_block"],
        )

    for event in schedule.get("work", []):
        _dayview_draw_event_block(
            draw, event, fonts,
            x=work_x, width=col_w,
            grid_y_start=grid_y_start,
            color=DAY_VIEW_COLORS["work_block"],
        )

    # 5. If no events at all, draw a friendly message in the grid area
    if not schedule.get("personal") and not schedule.get("work"):
        msg = "Nothing scheduled"
        bbox = draw.textbbox((0, 0), msg, font=fonts["empty_day"])
        msg_w = bbox[2] - bbox[0]
        msg_x = grid_x_start + (cx1 - grid_x_start - msg_w) // 2
        msg_y = grid_y_start + DAY_VIEW_GRID_HEIGHT // 2 - 10
        draw.text((msg_x, msg_y), msg, fill=COLORS["empty_text"], font=fonts["empty_day"])

    # Export
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)

    size_kb = len(buffer.getvalue()) / 1024
    logger.info(
        f"Generated day-view image for {schedule.get('date')}: "
        f"{DAY_VIEW_WIDTH}x{DAY_VIEW_TOTAL_HEIGHT}px, {size_kb:.0f}KB"
    )
    return buffer.getvalue()


def generate_weekly_calendar_images(weekly_schedule: list[dict]) -> list[bytes]:
    """
    Generate one calendar image per day for the work week (Mon-Fri).

    This replaces the old single-image weekly view that was blurry when
    Telegram compressed it. Now each day gets a crisp 800px image.

    Args:
        weekly_schedule: List of 5 daily schedule dicts (Mon-Fri) from
                         calendar_service.get_weekly_schedule().

    Returns:
        List of 5 PNG images as bytes (one per day).
    """
    images = []
    for day_schedule in weekly_schedule:
        img_bytes = generate_single_day_calendar_image(day_schedule)
        images.append(img_bytes)
    return images


# ---------------------------------------------------------------------------
# Day-view drawing helpers
# ---------------------------------------------------------------------------

def _dayview_draw_header(draw: ImageDraw, date_str: str, is_today: bool,
                         fonts: dict, cx0: int, cy0: int, cx1: int):
    """Draw the blue header bar with day name and full date."""
    h_y0 = cy0
    h_y1 = cy0 + DAY_VIEW_HEADER_H

    # Blue band — rounded top, flat bottom
    draw.rounded_rectangle(
        [cx0, h_y0, cx1, h_y1 + 12],
        radius=12,
        fill=COLORS["header_bg"],
    )
    draw.rectangle(
        [cx0, h_y1, cx1, h_y1 + 12],
        fill=COLORS["header_bg"],
    )

    # Format: "Monday, 23 February 2026"
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        formatted = dt.strftime("%A, %d %B %Y")
    except (ValueError, TypeError):
        formatted = date_str or "Today"

    # Add "(Today)" badge if applicable
    if is_today:
        formatted += "  (Today)"

    bbox = draw.textbbox((0, 0), formatted, font=fonts["day_header"])
    text_h = bbox[3] - bbox[1]
    text_y = h_y0 + (DAY_VIEW_HEADER_H - text_h) // 2

    draw.text(
        (cx0 + 24, text_y),
        formatted,
        fill=COLORS["header_text"],
        font=fonts["day_header"],
    )

    # Legend dots in the header (right side)
    legend_y = h_y0 + (DAY_VIEW_HEADER_H) // 2 - 6

    # Personal dot + label
    px = cx1 - 200
    draw.ellipse([px, legend_y + 1, px + 12, legend_y + 13], fill=COLORS["personal_accent"])
    draw.text((px + 16, legend_y), "Personal", fill=COLORS["header_text"], font=fonts["legend"])

    # Work dot + label
    wx = cx1 - 95
    draw.ellipse([wx, legend_y + 1, wx + 12, legend_y + 13], fill=DAY_VIEW_COLORS["work_block"])
    draw.text((wx + 16, legend_y), "Work", fill=COLORS["header_text"], font=fonts["legend"])


def _dayview_draw_col_headers(draw: ImageDraw, fonts: dict,
                               grid_x_start: int, y: int,
                               col_w: int, gap: int):
    """Draw the 'Personal' and 'Work' column labels above the grid."""
    # Personal label — centred in left column
    p_label = "Personal"
    bbox = draw.textbbox((0, 0), p_label, font=fonts["col_label"])
    p_w = bbox[2] - bbox[0]
    draw.text(
        (grid_x_start + (col_w - p_w) // 2, y + 10),
        p_label,
        fill=COLORS["personal_accent"],
        font=fonts["col_label"],
    )

    # Work label — centred in right column
    w_label = "Work"
    bbox = draw.textbbox((0, 0), w_label, font=fonts["col_label"])
    w_w = bbox[2] - bbox[0]
    work_x = grid_x_start + col_w + gap
    draw.text(
        (work_x + (col_w - w_w) // 2, y + 10),
        w_label,
        fill=DAY_VIEW_COLORS["work_block"],
        font=fonts["col_label"],
    )

    # Divider line under column labels
    div_y = y + DAY_VIEW_COL_HEADER_H - 1
    draw.line(
        [(grid_x_start, div_y), (grid_x_start + col_w * 2 + gap, div_y)],
        fill=DAY_VIEW_COLORS["grid_line_dark"],
        width=1,
    )


def _dayview_draw_grid(draw: ImageDraw, fonts: dict, cx0: int,
                       grid_x_start: int, grid_y_start: int, cx1: int):
    """Draw hour labels in the gutter and horizontal grid lines."""
    for h in range(DAY_VIEW_GRID_HOURS + 1):
        y = grid_y_start + h * DAY_VIEW_HOUR_HEIGHT
        hour = DAY_VIEW_START_HOUR + h

        # Hour label
        if hour <= DAY_VIEW_END_HOUR:
            label = f"{hour:02d}:00"
            draw.text(
                (cx0 + 8, y - 7),
                label,
                fill=COLORS["text_time"],
                font=fonts["grid_hour"],
            )

        # Horizontal line
        line_color = DAY_VIEW_COLORS["grid_line_dark"] if h == 0 else DAY_VIEW_COLORS["grid_line"]
        draw.line(
            [(grid_x_start, y), (cx1 - DAY_VIEW_OUTER_PAD, y)],
            fill=line_color,
            width=1,
        )

    # Vertical separator between Personal and Work columns
    usable_width = (cx1 - grid_x_start) - DAY_VIEW_COL_GAP
    col_w = usable_width // 2
    sep_x = grid_x_start + col_w + DAY_VIEW_COL_GAP // 2
    draw.line(
        [(sep_x, grid_y_start), (sep_x, grid_y_start + DAY_VIEW_GRID_HEIGHT)],
        fill=DAY_VIEW_COLORS["grid_line_dark"],
        width=1,
    )


def _dayview_draw_event_block(draw: ImageDraw, event: dict, fonts: dict,
                               x: int, width: int, grid_y_start: int,
                               color: str):
    """
    Draw a single event as a colored block on the grid.

    Vertical position and height are proportional to the event's
    start/end times, like Google Calendar.
    """
    start_str = event.get("start", "")
    end_str = event.get("end", "")

    if not start_str or "T" not in start_str:
        # All-day event — draw a thin bar at the top of the grid
        y0 = grid_y_start + 2
        y1 = y0 + DAY_VIEW_MIN_EVENT_H
        draw.rounded_rectangle(
            [x + 2, y0, x + width - 2, y1],
            radius=DAY_VIEW_EVENT_RADIUS,
            fill=color,
        )
        title = event.get("title", "All day")
        if len(title) > 30:
            title = title[:29] + "..."
        draw.text(
            (x + DAY_VIEW_EVENT_PAD + 3, y0 + 4),
            title,
            fill=DAY_VIEW_COLORS["event_text"],
            font=fonts["event_title"],
        )
        return

    # Parse start/end hours and minutes
    try:
        start_hour = int(start_str[11:13])
        start_min = int(start_str[14:16])
        if end_str and "T" in end_str:
            end_hour = int(end_str[11:13])
            end_min = int(end_str[14:16])
        else:
            # Default to 1-hour event
            end_hour = start_hour + 1
            end_min = start_min
    except (ValueError, IndexError):
        return

    # Clamp to the visible grid range
    start_f = max(start_hour + start_min / 60.0, DAY_VIEW_START_HOUR)
    end_f = min(end_hour + end_min / 60.0, DAY_VIEW_END_HOUR)

    if end_f <= start_f:
        return  # Entirely outside the visible grid

    # Calculate pixel positions
    y_start = grid_y_start + int((start_f - DAY_VIEW_START_HOUR) * DAY_VIEW_HOUR_HEIGHT)
    y_end = grid_y_start + int((end_f - DAY_VIEW_START_HOUR) * DAY_VIEW_HOUR_HEIGHT)

    if (y_end - y_start) < DAY_VIEW_MIN_EVENT_H:
        y_end = y_start + DAY_VIEW_MIN_EVENT_H

    # Draw the block
    draw.rounded_rectangle(
        [x + 2, y_start + 1, x + width - 2, y_end - 1],
        radius=DAY_VIEW_EVENT_RADIUS,
        fill=color,
    )

    # Event title (white on colored background)
    title = event.get("title", "Untitled")
    max_chars = max(width // 8, 8)
    if len(title) > max_chars:
        title = title[:max_chars - 1] + "..."

    draw.text(
        (x + DAY_VIEW_EVENT_PAD + 3, y_start + DAY_VIEW_EVENT_PAD),
        title,
        fill=DAY_VIEW_COLORS["event_text"],
        font=fonts["event_title"],
    )

    # If block is tall enough, show the time range below the title
    block_h = y_end - y_start
    if block_h >= 44:
        time_label = f"{start_hour:02d}:{start_min:02d} - {end_hour:02d}:{end_min:02d}"
        draw.text(
            (x + DAY_VIEW_EVENT_PAD + 3, y_start + DAY_VIEW_EVENT_PAD + 18),
            time_label,
            fill=DAY_VIEW_COLORS["event_text"],
            font=fonts["event_time"],
        )

    # If block is tall enough, show location too
    location = event.get("location")
    if location and block_h >= 62:
        loc_text = location
        if len(loc_text) > max_chars:
            loc_text = loc_text[:max_chars - 1] + "..."
        draw.text(
            (x + DAY_VIEW_EVENT_PAD + 3, y_start + DAY_VIEW_EVENT_PAD + 34),
            loc_text,
            fill=DAY_VIEW_COLORS["event_text"],
            font=fonts["event_time"],
        )
