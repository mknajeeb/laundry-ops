"""Seconds-based clock helpers for bag_des_v2.

Internal simulation times are integer seconds from midnight.
API fields named *_min often still mean "minutes from midnight" at the
edge; convert at parse/serialize boundaries.
"""

from __future__ import annotations

from typing import Any

SECONDS_PER_MINUTE = 60
SECONDS_PER_DAY = 24 * 60 * 60


def min_to_sec(minutes: float | int | None) -> int:
    if minutes is None:
        return 0
    return int(round(float(minutes) * SECONDS_PER_MINUTE))


def sec_to_min_float(seconds: float | int | None) -> float:
    if seconds is None:
        return 0.0
    return float(seconds) / SECONDS_PER_MINUTE


def sec_to_min_int(seconds: float | int | None) -> int:
    if seconds is None:
        return 0
    return int(seconds) // SECONDS_PER_MINUTE


def duration_sec_from_min(minutes: float | int | None) -> int:
    """Convert a minute-based process duration to seconds. Zero allowed."""
    if minutes is None:
        return 0
    return max(0, int(round(float(minutes) * SECONDS_PER_MINUTE)))


def duration_sec(seconds: float | int | None) -> int:
    if seconds is None:
        return 0
    return max(0, int(round(float(seconds))))


def parse_clock_seconds(raw: Any, *, default: str = "7:00 AM") -> int:
    text = str(raw if raw is not None else default).strip().upper().replace(".", "")
    if not text:
        text = default.upper()
    am_pm = "AM" if "AM" in text else "PM" if "PM" in text else ""
    core = text.replace("AM", "").replace("PM", "").strip()
    parts = core.split(":")
    try:
        hh = int(parts[0])
        mm = int(parts[1]) if len(parts) > 1 else 0
        ss = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        return parse_clock_seconds(default)
    if am_pm == "PM" and hh != 12:
        hh += 12
    if am_pm == "AM" and hh == 12:
        hh = 0
    return hh * 3600 + mm * 60 + ss


def label_seconds(seconds: int | None, *, include_seconds: bool | None = None) -> str | None:
    if seconds is None:
        return None
    s = int(seconds) % SECONDS_PER_DAY
    hh = s // 3600
    mm = (s % 3600) // 60
    ss = s % 60
    am_pm = "AM" if hh < 12 else "PM"
    h12 = hh % 12 or 12
    if include_seconds is None:
        include_seconds = ss != 0
    if include_seconds:
        return f"{h12}:{mm:02d}:{ss:02d} {am_pm}"
    return f"{h12}:{mm:02d} {am_pm}"


def api_minutes_to_seconds(value: int | float) -> int:
    """Interpret API continue_from_min / planned minute fields.

    Values <= 24h in minutes are treated as minutes; larger values are
    assumed to already be seconds (internal re-entry).
    """
    v = int(value)
    if v <= 24 * 60:
        return v * SECONDS_PER_MINUTE
    return v


def planning_block_boundaries(start_sec: int, target_sec: int, block_size_min: int) -> list[int]:
    """Return [start, ..., target], allowing a shorter final block."""
    if target_sec < start_sec:
        target_sec = start_sec
    block_sec = max(1, int(block_size_min)) * SECONDS_PER_MINUTE
    bounds = [int(start_sec)]
    t = int(start_sec)
    while t + block_sec < target_sec:
        t += block_sec
        bounds.append(t)
    if bounds[-1] != int(target_sec):
        bounds.append(int(target_sec))
    return bounds
