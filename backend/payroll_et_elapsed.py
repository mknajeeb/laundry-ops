"""Payable elapsed time for Eastern wall clocks, including DST transitions.

``shift_sessions.clock_in_at`` / ``clock_out_at`` and breaks are naive
America/New_York wall times. Subtracting those naive values drops the extra
hour when clocks fall back and keeps a non-existent hour when clocks spring
forward. Absolute elapsed time is the UTC timestamp difference after the wall
values are localized.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.rinse_folding_et import ET


def coerce_et_wall(value: Any) -> datetime | None:
    """Localize a payroll clock to America/New_York.

    Naive values are Eastern wall time. Aware values are converted to Eastern.
    During the repeated fallback hour the first occurrence (EDT, fold 0) is used,
    because a naive wall time does not record which instance was punched.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ET)
    return dt.astimezone(ET)


def et_wall_elapsed_seconds(start: Any, end: Any) -> int:
    """Seconds of real time from start to end. Zero when either clock is missing."""
    a = coerce_et_wall(start)
    b = coerce_et_wall(end)
    if a is None or b is None:
        return 0
    return int(round(b.timestamp() - a.timestamp()))
