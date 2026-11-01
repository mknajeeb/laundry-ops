"""Monday–Sunday schedule weeks on top of Sunday-stored rows.

``planned_weekly_schedule_entries.week_start`` stays the Sunday date, and
``day_of_week`` stays 0=Sunday … 6=Saturday. A shift's calendar date is still
``week_start + day_of_week``. Nothing here rewrites an existing row onto a
different date.

The Weekly Schedule shows Monday through the following Sunday. Monday–Saturday
of that week are the stored Sunday week that begins the day before. The Sunday
at the end of the week is stored on that Sunday's own week, day 0.

Opening the schedule on a Sunday shows the week that starts the next day.
That Sunday already belongs to the week that ended on that date.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Mapping, Sequence

# Storage indexes, shown Monday through Sunday.
DISPLAY_DAY_ORDER = (1, 2, 3, 4, 5, 6, 0)


def parse_schedule_date(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def schedule_monday_containing(raw: date | str | None) -> date | None:
    """Monday of the Monday–Sunday week that contains this calendar date.

    Sunday belongs to the week that started the previous Monday.
    """
    parsed = parse_schedule_date(raw)
    if parsed is None:
        return None
    return parsed - timedelta(days=parsed.weekday())


def current_schedule_monday(today: date) -> date:
    """Week the schedule opens on for an America/New_York business date.

    Sunday opens the following Monday. Every other day opens the Monday–Sunday
    week that contains that date.
    """
    if today.weekday() == 6:
        return today + timedelta(days=1)
    monday = schedule_monday_containing(today)
    assert monday is not None
    return monday


def display_week_storage(monday: date) -> tuple[date, date]:
    """Storage Sundays for a display week: (Monday–Saturday week, ending Sunday)."""
    return monday - timedelta(days=1), monday + timedelta(days=6)


def storage_week_for_dow(monday: date, day_of_week: int) -> date:
    mon_sat, sunday = display_week_storage(monday)
    return sunday if int(day_of_week) == 0 else mon_sat


def display_monday_for_storage(storage_sunday: date, day_of_week: int) -> date:
    calendar = storage_sunday + timedelta(days=int(day_of_week))
    monday = schedule_monday_containing(calendar)
    assert monday is not None
    return monday


def resolve_schedule_write(raw_week: Any, day_of_week: int) -> tuple[date, date] | None:
    """Map a schedule request onto ``(display Monday, storage Sunday)``.

    A Monday ``week_start`` is the week on screen. A Sunday ``week_start`` is the
    legacy storage key, so every day of that request stays on that Sunday.
    """
    parsed = parse_schedule_date(raw_week)
    if parsed is None:
        return None
    dow = int(day_of_week)
    if parsed.weekday() == 6:
        calendar = parsed + timedelta(days=dow)
        monday = schedule_monday_containing(calendar)
        assert monday is not None
        return monday, parsed
    monday = parsed if parsed.weekday() == 0 else schedule_monday_containing(parsed)
    assert monday is not None
    return monday, storage_week_for_dow(monday, dow)


def row_in_display_week(row: Mapping[str, Any], monday: date) -> bool:
    storage = parse_schedule_date(row.get("week_start"))
    if storage is None:
        return False
    try:
        dow = int(row.get("day_of_week"))
    except (TypeError, ValueError):
        return False
    return storage == storage_week_for_dow(monday, dow) and (
        (dow == 0) == (storage == monday + timedelta(days=6))
    )


def rows_for_display_week(rows: Sequence[Mapping[str, Any]], monday: date) -> list[Mapping[str, Any]]:
    return [row for row in rows if row_in_display_week(row, monday)]
