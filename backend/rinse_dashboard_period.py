"""Rinse Performance period + comparison window resolution (ET business dates).

Rinse-owned — do not import Management comparison helpers.
Primary range hard-capped at MAX_PRIMARY_RANGE_DAYS; ensure union at MAX_ENSURE_UNION_DAYS.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.business_time import business_today
from backend.rinse_performance_approvals import current_et_week_start, et_week_bounds

MAX_PRIMARY_RANGE_DAYS = 31
MAX_ENSURE_UNION_DAYS = 62

# Safety ceiling for "last N sessions" retrieval — NOT the semantic definition.
# Semantic: employee's actual last N relevant sessions (ORDER BY … DESC LIMIT N).
# Bound only prevents unbounded historical scans.
RECENT_SESSIONS_SAFETY_LOOKBACK_DAYS = 730

PERIOD_TODAY = "today"
PERIOD_YESTERDAY = "yesterday"
PERIOD_THIS_WEEK = "this_week"
PERIOD_LAST_WEEK = "last_week"
PERIOD_LAST_7_DAYS = "last_7_days"
PERIOD_LAST_30_DAYS = "last_30_days"
PERIOD_CUSTOM = "custom"

COMPARE_NONE = "none"
COMPARE_PREVIOUS_PERIOD = "previous_period"
COMPARE_PREVIOUS_WEEK = "previous_week"
COMPARE_PREVIOUS_4_WEEKS = "previous_4_weeks"

PERIOD_PRESETS = frozenset(
    {
        PERIOD_TODAY,
        PERIOD_YESTERDAY,
        PERIOD_THIS_WEEK,
        PERIOD_LAST_WEEK,
        PERIOD_LAST_7_DAYS,
        PERIOD_LAST_30_DAYS,
        PERIOD_CUSTOM,
    }
)
COMPARE_PRESETS = frozenset(
    {
        COMPARE_NONE,
        COMPARE_PREVIOUS_PERIOD,
        COMPARE_PREVIOUS_WEEK,
        COMPARE_PREVIOUS_4_WEEKS,
    }
)


class PeriodResolutionError(ValueError):
    """Invalid period / compare / custom range."""


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _inclusive_days(start: date, end: date) -> int:
    return (end - start).days + 1


def _dates_between(start: date, end: date) -> list[date]:
    out: list[date] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def resolve_period(
    *,
    period: str | None = None,
    start: date | None = None,
    end: date | None = None,
    week_start: date | None = None,
    anchor: date | None = None,
) -> dict[str, Any]:
    """Resolve a primary analysis window in America/New_York business dates.

    Legacy ``week_start`` (without period) maps to that calendar Mon–Sun week.
    """
    today = anchor or business_today()
    key = str(period or "").strip().lower()

    if not key and week_start is not None:
        ws, we = et_week_bounds(week_start)
        return _window(PERIOD_THIS_WEEK if week_start == current_et_week_start() else "week", ws, we)

    if not key:
        key = PERIOD_THIS_WEEK

    if key not in PERIOD_PRESETS:
        raise PeriodResolutionError(f"unsupported_period:{key}")

    if key == PERIOD_TODAY:
        return _window(key, today, today)
    if key == PERIOD_YESTERDAY:
        d = today - timedelta(days=1)
        return _window(key, d, d)
    if key == PERIOD_THIS_WEEK:
        ws, we = et_week_bounds(today)
        return _window(key, ws, we)
    if key == PERIOD_LAST_WEEK:
        this_start = _monday_of(today)
        prev_start = this_start - timedelta(days=7)
        return _window(key, prev_start, prev_start + timedelta(days=6))
    if key == PERIOD_LAST_7_DAYS:
        start_d = today - timedelta(days=6)
        return _window(key, start_d, today)
    if key == PERIOD_LAST_30_DAYS:
        start_d = today - timedelta(days=29)
        return _window(key, start_d, today)
    # custom
    if start is None or end is None:
        raise PeriodResolutionError("custom_requires_start_and_end")
    if end < start:
        raise PeriodResolutionError("end_before_start")
    days = _inclusive_days(start, end)
    if days > MAX_PRIMARY_RANGE_DAYS:
        raise PeriodResolutionError(
            f"range_exceeds_max:{days}>{MAX_PRIMARY_RANGE_DAYS}"
        )
    return _window(PERIOD_CUSTOM, start, end)


def resolve_compare(
    *,
    current: dict[str, Any],
    compare: str | None = None,
) -> dict[str, Any] | None:
    """Resolve comparison baseline.

    previous_period — equal-length range immediately before current.start
    previous_week — always the calendar Mon–Sun immediately preceding *today's*
      current Monday? No: "immediately preceding calendar Mon–Sun week"
      relative to what?

    Spec: "previous_week must always resolve to the immediately preceding
    calendar Mon–Sun week, independent of the selected current range."

    Interpretation: relative to the *anchor/today* (business today), the Mon–Sun
    week before the current calendar week — i.e. last_week. Independent of
    whether current period is Last 7 Days, custom, etc.

    Wait — "immediately preceding calendar Mon–Sun" could also mean the Mon–Sun
    week that ends before the current period starts. But examples say:
    "Any period + Previous Week → previous calendar Mon–Sun"

    Most natural management reading: Previous Week = last completed/current
    calendar week's predecessor from business today = Mon–Sun of last week.
    That matches PERIOD_LAST_WEEK and is independent of selected range.
    """
    key = str(compare or COMPARE_NONE).strip().lower() or COMPARE_NONE
    if key not in COMPARE_PRESETS:
        raise PeriodResolutionError(f"unsupported_compare:{key}")
    if key == COMPARE_NONE:
        return None

    cur_start: date = current["start"]
    cur_end: date = current["end"]
    length = _inclusive_days(cur_start, cur_end)

    if key == COMPARE_PREVIOUS_PERIOD:
        end_b = cur_start - timedelta(days=1)
        start_b = end_b - timedelta(days=length - 1)
        return _window(key, start_b, end_b, label="Previous Period")

    if key == COMPARE_PREVIOUS_WEEK:
        # Always the Mon–Sun week immediately before the calendar week containing
        # business today — independent of the selected current range.
        today = business_today()
        this_monday = _monday_of(today)
        prev_monday = this_monday - timedelta(days=7)
        return _window(key, prev_monday, prev_monday + timedelta(days=6), label="Previous Week")

    # previous_4_weeks
    end_b = cur_start - timedelta(days=1)
    start_b = end_b - timedelta(days=27)
    return _window(key, start_b, end_b, label="Previous 4 Weeks")


def resolve_period_and_compare(
    *,
    period: str | None = None,
    start: date | None = None,
    end: date | None = None,
    week_start: date | None = None,
    compare: str | None = None,
    anchor: date | None = None,
) -> dict[str, Any]:
    current = resolve_period(
        period=period,
        start=start,
        end=end,
        week_start=week_start,
        anchor=anchor,
    )
    baseline = resolve_compare(current=current, compare=compare)
    ensure_start = current["start"]
    ensure_end = current["end"]
    if baseline is not None:
        ensure_start = min(ensure_start, baseline["start"])
        ensure_end = max(ensure_end, baseline["end"])
    union_days = _inclusive_days(ensure_start, ensure_end)
    if union_days > MAX_ENSURE_UNION_DAYS:
        raise PeriodResolutionError(
            f"ensure_union_exceeds_max:{union_days}>{MAX_ENSURE_UNION_DAYS}"
        )
    return {
        "current": current,
        "compare": baseline,
        "ensure_start": ensure_start,
        "ensure_end": ensure_end,
        "ensure_dates": _dates_between(ensure_start, ensure_end),
    }


def compute_delta(current: float | int | None, previous: float | int | None) -> dict[str, Any]:
    """Absolute + percent change; missing/zero previous → null pct and display —."""
    if current is None or previous is None:
        return {
            "current": current,
            "previous": previous,
            "absolute": None,
            "percent": None,
            "display": "—",
        }
    try:
        cur_f = float(current)
        prev_f = float(previous)
    except (TypeError, ValueError):
        return {
            "current": current,
            "previous": previous,
            "absolute": None,
            "percent": None,
            "display": "—",
        }
    abs_d = round(cur_f - prev_f, 4)
    if prev_f == 0:
        return {
            "current": cur_f,
            "previous": prev_f,
            "absolute": abs_d,
            "percent": None,
            "display": "—",
        }
    pct = round((abs_d / abs(prev_f)) * 100.0, 2)
    sign = "+" if abs_d > 0 else ""
    return {
        "current": cur_f,
        "previous": prev_f,
        "absolute": abs_d,
        "percent": pct,
        "display": f"{sign}{abs_d:g} / {sign}{pct:g}%",
    }


def _window(
    key: str,
    start: date,
    end: date,
    *,
    label: str | None = None,
) -> dict[str, Any]:
    labels = {
        PERIOD_TODAY: "Today",
        PERIOD_YESTERDAY: "Yesterday",
        PERIOD_THIS_WEEK: "This Week",
        PERIOD_LAST_WEEK: "Last Week",
        PERIOD_LAST_7_DAYS: "Last 7 Days",
        PERIOD_LAST_30_DAYS: "Last 30 Days",
        PERIOD_CUSTOM: "Custom",
        COMPARE_PREVIOUS_PERIOD: "Previous Period",
        COMPARE_PREVIOUS_WEEK: "Previous Week",
        COMPARE_PREVIOUS_4_WEEKS: "Previous 4 Weeks",
    }
    return {
        "key": key,
        "label": label or labels.get(key, key),
        "start": start,
        "end": end,
        "start_et": start.isoformat(),
        "end_et": end.isoformat(),
        "day_count": _inclusive_days(start, end),
        "dates": _dates_between(start, end),
    }
