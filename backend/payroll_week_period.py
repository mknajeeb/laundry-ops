"""Inclusive Monday–Sunday payroll weeks.

Stored ``pay_period_end`` is the last calendar day of the week. Time-record
queries keep an exclusive upper bound internally: the start of the next day.

A week that was saved as Monday through the following Monday (eight calendar
dates) is the same week with the exclusive boundary written into the end
column. Display and new queries use the inclusive Sunday. Saved batch rows
are not rewritten here.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta


def parse_period_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip().replace("Z", "")
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _aligned_week_start(day: date, week_starts_on: int) -> bool:
    anchor = int(week_starts_on) % 7
    # date.weekday() is Monday=0 … Sunday=6, same as payroll week_starts_on.
    return day.weekday() == anchor


def canonical_inclusive_period(
    start,
    end,
    week_starts_on: int = 0,
) -> tuple[date, date]:
    """Return the inclusive calendar span for a payroll week.

    Historical weeks whose end is already six days after the start are unchanged.
    A Monday-aligned span of seven days (end = next Monday) becomes Sunday.
    """
    start_d = parse_period_date(start)
    end_d = parse_period_date(end)
    if start_d is None or end_d is None or end_d < start_d:
        if start_d is None or end_d is None:
            raise ValueError("payroll period dates are required")
        return start_d, end_d
    if _aligned_week_start(start_d, week_starts_on) and (end_d - start_d).days == 7:
        return start_d, start_d + timedelta(days=6)
    return start_d, end_d


def inclusive_period_label(start, end, week_starts_on: int = 0) -> str:
    start_d, end_d = canonical_inclusive_period(start, end, week_starts_on)
    return f"{start_d.isoformat()} – {end_d.isoformat()}"


def display_pay_period(start, end, week_starts_on: int = 0) -> str:
    if not start and not end:
        return ""
    if not start or not end:
        return str(start or end or "")[:10]
    return inclusive_period_label(start, end, week_starts_on)


def period_end_query_values(start, end, week_starts_on: int = 0) -> list[str]:
    """Ends that mean this same week, including a stored off-by-one Monday."""
    start_d, end_d = canonical_inclusive_period(start, end, week_starts_on)
    values = [end_d.isoformat()]
    if (end_d - start_d).days == 6 and _aligned_week_start(start_d, week_starts_on):
        values.append((end_d + timedelta(days=1)).isoformat())
    return values


def period_lookup_pairs(start, end, week_starts_on: int = 0) -> list[tuple[str, str]]:
    """Start/end pairs that identify one week, including a stored next-Monday end."""
    start_d, _end_d = canonical_inclusive_period(start, end, week_starts_on)
    start_iso = start_d.isoformat()
    return [
        (start_iso, end_value)
        for end_value in period_end_query_values(start, end, week_starts_on)
    ]


def collapse_period_pairs(pairs) -> list[tuple[str, str]]:
    """One inclusive Monday–Sunday key per week. Stored rows are not rewritten."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for ps, pe in pairs or []:
        try:
            start_d, end_d = canonical_inclusive_period(ps, pe)
        except ValueError:
            continue
        key = (start_d.isoformat(), end_d.isoformat())
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out
