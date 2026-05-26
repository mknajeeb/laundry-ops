"""Shared date-range parsing for folding dashboard APIs."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from backend.rinse_folding_et import (
    eastern_month_bounds,
    eastern_today,
    eastern_week_bounds,
)
from backend.rinse_folding_registry import folding_period_bounds, resolve_analysis_period

DateField = Literal["folding_work_date", "date_clean", "completed_at"]


def default_week_range(
    anchor: date | None = None,
    *,
    week_start_day: str = "MONDAY",
) -> tuple[date, date]:
    """Current Eastern calendar week Mon–Sun (or configured week start)."""
    return eastern_week_bounds(anchor or eastern_today(), week_start_day=week_start_day)


def sql_date_column(date_field: str) -> str:
    """Qualified SQL expression for period filtering."""
    f = str(date_field or "folding_work_date").strip().lower()
    if f == "date_clean":
        return "r.date_clean"
    if f == "completed_at":
        return "DATE(r.completed_at)"
    return "p.work_date"


def sql_period_range_clause(date_field: str) -> str:
    """Deprecated: use sql_period_filter_sql_and_args from rinse_folding_et."""
    col = sql_date_column(date_field)
    return f" AND {col} >= %s AND {col} <= %s"


def sql_period_filter_sql_and_args(
    date_field: str,
    period_start: date,
    period_end: date,
    *,
    perf_alias: str = "p",
    registry_alias: str = "r",
) -> tuple[str, list]:
    from backend.rinse_folding_et import sql_period_filter_sql_and_args as _et

    return _et(
        date_field, period_start, period_end, perf_alias=perf_alias, registry_alias=registry_alias
    )


def parse_folding_date_range(
    *,
    date_start: date | None = None,
    date_end: date | None = None,
    period: str | None = None,
    anchor: date | None = None,
    week_start_day: str = "MONDAY",
) -> tuple[date, date, str]:
    """
    Resolve inclusive [start, end] from explicit range or legacy period+anchor.

    Presets: today, week, month, custom (explicit start/end).
    """
    if isinstance(date_start, date) and isinstance(date_end, date):
        if date_start > date_end:
            raise ValueError("date_start must be on or before date_end")
        label = "custom" if date_start != date_end else "today"
        if date_start == date_end:
            label = "today"
        return date_start, date_end, label

    anchor_day = anchor or eastern_today()
    p = str(period or "week").strip().lower()
    if p == "custom":
        raise ValueError("custom period requires date_start and date_end")
    if p in ("today", "day"):
        return anchor_day, anchor_day, "today"
    if p == "month":
        start, end = eastern_month_bounds(anchor_day)
        return start, end, "month"
    start, end = eastern_week_bounds(anchor_day, week_start_day=week_start_day)
    return start, end, "week"


def parse_range_from_request(
    args: Any,
    parse_date_value,
    *,
    week_start_day: str = "MONDAY",
) -> tuple[date, date, str, str]:
    """
    Read Flask-style request args; return (start, end, period_label, date_field).
    """
    date_field = str(
        args.get("date_field") or args.get("dateField") or "folding_work_date"
    ).strip().lower()
    if date_field not in ("folding_work_date", "date_clean", "completed_at"):
        date_field = "folding_work_date"

    start_raw = args.get("date_start") or args.get("start_date") or args.get("period_start")
    end_raw = args.get("date_end") or args.get("end_date") or args.get("period_end")
    custom_start = parse_date_value(start_raw) if start_raw else None
    custom_end = parse_date_value(end_raw) if end_raw else None

    if isinstance(custom_start, date) and isinstance(custom_end, date):
        start, end, label = parse_folding_date_range(
            date_start=custom_start, date_end=custom_end
        )
        return start, end, label, date_field

    period_raw = (args.get("period") or "week").strip().lower()
    anchor_raw = args.get("date") or args.get("anchor_date")
    anchor = parse_date_value(anchor_raw) if anchor_raw else eastern_today()
    if not isinstance(anchor, date):
        raise ValueError("Invalid anchor date")

    if period_raw == "custom":
        raise ValueError("custom period requires date_start and date_end")

    start, end, label = resolve_analysis_period(
        period_raw,
        anchor,
        week_start_day=week_start_day,
        custom_start=None,
        custom_end=None,
    )
    return start, end, label, date_field
