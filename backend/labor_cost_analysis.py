"""Labor Cost Analysis report.

Reporting only. Totals come from stored payroll lines and the existing
hourly-cost helpers. This module does not change wages, overtime rules,
employer taxes, approvals, payments, or historical payroll records.

Averages are weighted: sum of dollars ÷ sum of payable hours. They are never
an average of employee rates or of displayed period rates.

Payroll weeks follow payroll_period_settings.week_starts_on, not the Weekly
Schedule display setting. Biweekly periods pair those payroll weeks from the
payroll week that contains 2024-01-01. Monthly periods are calendar months.
A payroll week that crosses a month or a custom range is allocated by daily
payable hours. If those hours are not available, the week is left out and
named in the coverage notes.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.payroll_hourly_cost import (
    DEFAULT_LABOR_COST_TARGET,
    aggregate_finalized_w2_periods,
    analyze_employee_hourly_cost,
    apply_historical_rates,
    economics_from_time_records,
    hourly_cost_from_report_rows,
    labor_cost_target_from_settings,
    weighted_burden_from_periods,
)

BUSINESS_TZ = ZoneInfo("America/New_York")
BIWEEKLY_ANCHOR = date(2024, 1, 1)
HISTORY_LOOKBACK_DAYS = 400
ROW_LIMIT = 20000
TIME_RECORD_LIMIT = 20000

WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)

FREQUENCIES = ("weekly", "biweekly", "monthly")
PRESETS = (
    "current_week",
    "last_week",
    "last_4_weeks",
    "last_8_weeks",
    "last_12_weeks",
    "this_month",
    "last_month",
    "last_3_months",
    "custom",
)
COMPARE_MODES = ("none", "previous_period", "previous_equivalent", "custom")
CLASSIFICATIONS = ("all", "w2", "contractor_1099")
STATUSES = ("finalized", "open", "all")

PAYROLL_WEEK_RULE = (
    "Weekly reporting uses the payroll week (payroll_period_settings.week_starts_on), "
    "not the Weekly Schedule display setting."
)
BIWEEKLY_RULE = (
    "Biweekly reporting pairs two consecutive payroll weeks. Pair zero is the payroll "
    "week that contains 2024-01-01 and the following payroll week. Every later pair "
    "starts an even number of weeks after that anchor week."
)

_SCALED_FIELDS = (
    "payable_hours",
    "regular_hours",
    "ot_hours",
    "gross_pay",
    "straight_time_gross",
    "base_earnings",
    "other_earnings",
    "ot_premium",
    "ot_wages",
    "employer_expenses",
    "total_employer_cost",
    "straight_time_employer_cost",
)

_CATEGORY_LABELS = {
    "w2": "W-2",
    "contractor_1099": "1099",
    "temp": "Temp",
}


def _q2(val: Any) -> float:
    try:
        return float(Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0.0


def _opt(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    return _q2(val)


def _sum(values) -> float:
    total = Decimal("0")
    for value in values:
        if value is None or value == "":
            continue
        total += Decimal(str(value))
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _div(numerator: Any, denominator: Any) -> Optional[float]:
    if numerator is None or denominator is None:
        return None
    den = Decimal(str(denominator))
    if abs(den) < Decimal("0.0000001"):
        return None
    return float(
        (Decimal(str(numerator)) / den).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


def _pct(numerator: Any, denominator: Any) -> Optional[float]:
    if numerator is None or denominator is None:
        return None
    den = Decimal(str(denominator))
    if abs(den) < Decimal("0.0000001"):
        return None
    return float(
        (Decimal(str(numerator)) / den * Decimal(100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    )


def _parse_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _iso(value: date) -> str:
    return value.isoformat()


def _month_end(day: date) -> date:
    if day.month == 12:
        return date(day.year, 12, 31)
    return date(day.year, day.month + 1, 1) - timedelta(days=1)


def _add_months(day: date, months: int) -> date:
    index = day.month - 1 + months
    year = day.year + index // 12
    month = index % 12 + 1
    last = _month_end(date(year, month, 1)).day
    return date(year, month, min(day.day, last))


def business_today(as_of: Optional[date] = None) -> date:
    if as_of is not None:
        return as_of
    return datetime.now(BUSINESS_TZ).date()


def align_week_start(day: date, week_starts_on: int) -> date:
    anchor = int(week_starts_on) % 7
    delta = (day.weekday() - anchor) % 7
    return day - timedelta(days=delta)


def biweekly_bounds(week_start: date, week_starts_on: int) -> tuple[date, date]:
    """Stable pair containing this payroll week, anchored at 2024-01-01."""
    aligned = align_week_start(week_start, week_starts_on)
    anchor_week = align_week_start(BIWEEKLY_ANCHOR, week_starts_on)
    weeks = (aligned - anchor_week).days // 7
    pair_index = weeks // 2
    start = anchor_week + timedelta(days=pair_index * 14)
    return start, start + timedelta(days=13)


def format_range_label(start: date, end: date) -> str:
    if start.year == end.year:
        return f"{start.strftime('%b')} {start.day} – {end.strftime('%b')} {end.day}, {end.year}"
    return (
        f"{start.strftime('%b')} {start.day}, {start.year} – "
        f"{end.strftime('%b')} {end.day}, {end.year}"
    )


def resolve_preset(preset: str, *, as_of: date, week_starts_on: int) -> dict[str, Any]:
    name = str(preset or "current_week").strip().lower()
    if name not in PRESETS:
        raise ValueError("Invalid preset")
    today = business_today(as_of)
    week_start = align_week_start(today, week_starts_on)
    week_end = week_start + timedelta(days=6)
    if name == "current_week":
        start, end, label = week_start, week_end, "Current payroll week"
    elif name == "last_week":
        start, end = week_start - timedelta(days=7), week_end - timedelta(days=7)
        label = "Last payroll week"
    elif name == "last_4_weeks":
        start, end, label = week_start - timedelta(days=21), week_end, "Last 4 payroll weeks"
    elif name == "last_8_weeks":
        start, end, label = week_start - timedelta(days=49), week_end, "Last 8 payroll weeks"
    elif name == "last_12_weeks":
        start, end, label = week_start - timedelta(days=77), week_end, "Last 12 payroll weeks"
    elif name == "this_month":
        start, end = today.replace(day=1), _month_end(today)
        label = "This month"
    elif name == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
        label = "Last month"
    elif name == "last_3_months":
        start = _add_months(today.replace(day=1), -2)
        end = _month_end(today)
        label = "Last 3 months"
    else:
        raise ValueError("Custom range needs a start and end date")
    return {"preset": name, "start": start, "end": end, "label": label}


def _days_inclusive(start: date, end: date) -> int:
    return (end - start).days + 1


def _overlaps(a0: date, a1: date, b0: date, b1: date) -> bool:
    return a0 <= b1 and b0 <= a1


def _month_segments(start: date, end: date) -> list[tuple[date, date]]:
    segments = []
    cursor = start
    while cursor <= end:
        seg_end = min(_month_end(cursor), end)
        segments.append((cursor, seg_end))
        cursor = seg_end + timedelta(days=1)
    return segments


def _iter_dates(start: date, end: date):
    cursor = start
    while cursor <= end:
        yield cursor
        cursor += timedelta(days=1)


def classification_label(category: str) -> str:
    return _CATEGORY_LABELS.get(str(category or ""), str(category or "Unknown"))


def employee_rate_label(category: str) -> str:
    if str(category or "") == "w2":
        return "Employee Effective Rate"
    if str(category or "") in ("contractor_1099", "temp"):
        return "Worker Gross Rate"
    return "Employee Effective Rate"


def make_slice(
    *,
    user_id: int,
    employee_name: str,
    worker_category: str,
    period_start,
    period_end,
    payable_hours: Any,
    regular_hours: Any = None,
    ot_hours: Any = 0,
    gross_pay: Any = 0,
    straight_time_gross: Any = None,
    base_earnings: Any = None,
    other_earnings: Any = 0,
    ot_premium: Any = 0,
    ot_wages: Any = 0,
    employer_expenses: Any = None,
    total_employer_cost: Any = None,
    straight_time_employer_cost: Any = None,
    base_wage: Any = None,
    base_wage_blended: bool = False,
    burden_percent: Any = None,
    burden_status: str = "actual",
    burden_label: str = "Actual",
    finalized: bool = True,
    estimated: bool = False,
    cost_basis: str = "processed_payroll",
    notes: Optional[list] = None,
) -> dict[str, Any]:
    start = _parse_date(period_start)
    end = _parse_date(period_end)
    if start is None or end is None:
        raise ValueError("A labor-cost slice needs a payroll period")
    hours = _q2(payable_hours)
    ot_h = _q2(ot_hours)
    reg_h = _q2(regular_hours) if regular_hours is not None else _q2(hours - ot_h)
    gross = _q2(gross_pay)
    premium = _q2(ot_premium)
    straight = _q2(straight_time_gross) if straight_time_gross is not None else _q2(gross - premium)
    total = _opt(total_employer_cost)
    straight_cost = _opt(straight_time_employer_cost)
    extra = _opt(employer_expenses)
    if extra is None and total is not None:
        extra = _q2(total - gross)
    return {
        "user_id": int(user_id),
        "employee_name": str(employee_name or "").strip() or "Employee",
        "worker_category": str(worker_category or "unknown"),
        "period_start": _iso(start),
        "period_end": _iso(end),
        "alloc_start": _iso(start),
        "alloc_end": _iso(end),
        "payable_hours": hours,
        "regular_hours": reg_h,
        "ot_hours": ot_h,
        "gross_pay": gross,
        "straight_time_gross": straight,
        "base_earnings": _q2(base_earnings) if base_earnings is not None else straight,
        "other_earnings": _q2(other_earnings),
        "ot_premium": premium,
        "ot_wages": _q2(ot_wages),
        "employer_expenses": extra,
        "total_employer_cost": total,
        "straight_time_employer_cost": straight_cost,
        "base_wage": _opt(base_wage),
        "base_wage_blended": bool(base_wage_blended),
        "burden_percent": None if burden_percent is None else _q2(burden_percent),
        "burden_status": burden_status or "unavailable",
        "burden_label": burden_label or "Unavailable",
        "finalized": bool(finalized),
        "estimated": bool(estimated),
        "cost_basis": cost_basis or "",
        "allocation": "full",
        "allocation_note": "",
        "notes": list(notes or []),
    }


def slice_from_analysis(
    analysis: dict,
    *,
    user_id: int,
    employee_name: str,
    period_start,
    period_end,
    ot_wages: Any = 0,
    estimated: bool = False,
) -> dict[str, Any]:
    """One employee-period slice from the existing hourly-cost analysis."""
    return make_slice(
        user_id=user_id,
        employee_name=employee_name,
        worker_category=analysis.get("worker_category") or "unknown",
        period_start=period_start,
        period_end=period_end,
        payable_hours=analysis.get("payable_hours"),
        regular_hours=analysis.get("regular_hours"),
        ot_hours=analysis.get("ot_hours"),
        gross_pay=analysis.get("gross_pay"),
        straight_time_gross=analysis.get("straight_time_gross"),
        base_earnings=analysis.get("base_earnings"),
        other_earnings=analysis.get("other_earnings"),
        ot_premium=analysis.get("ot_premium"),
        ot_wages=ot_wages,
        employer_expenses=analysis.get("employer_expenses"),
        total_employer_cost=analysis.get("total_employer_cost"),
        straight_time_employer_cost=analysis.get("straight_time_employer_cost"),
        base_wage=analysis.get("base_wage"),
        base_wage_blended=bool(analysis.get("base_wage_blended")),
        burden_percent=analysis.get("burden_percent"),
        burden_status=analysis.get("burden_status") or "unavailable",
        burden_label=analysis.get("burden_label") or "Unavailable",
        finalized=bool(analysis.get("finalized")) and not estimated,
        estimated=estimated or analysis.get("burden_status") == "estimated",
        cost_basis=analysis.get("cost_basis") or "",
        notes=list(analysis.get("notes") or []),
    )


def slice_from_payroll_rows(
    rows: list[dict],
    *,
    tax_settings: Optional[dict] = None,
    labor_cost_target: Optional[float] = None,
) -> Optional[dict]:
    """Finalized or stored payroll lines for one employee and one pay period."""
    if not rows:
        return None
    analysis = hourly_cost_from_report_rows(
        rows,
        tax_settings=tax_settings,
        labor_cost_target=labor_cost_target,
    )
    ot_wages = _sum(row.get("ot_earnings") for row in rows)
    first = rows[0]
    estimated = (not analysis.get("finalized")) or analysis.get("burden_status") == "estimated"
    if analysis.get("burden_status") == "not_applicable" and analysis.get("finalized"):
        estimated = False
    return slice_from_analysis(
        analysis,
        user_id=int(first.get("user_id") or 0),
        employee_name=first.get("employee_name") or "",
        period_start=first.get("pay_period_start"),
        period_end=first.get("pay_period_end"),
        ot_wages=ot_wages,
        estimated=estimated and analysis.get("burden_status") != "not_applicable",
    )


def _quality(row: dict) -> str:
    if row.get("total_employer_cost") is None:
        return "unavailable"
    if row.get("estimated"):
        return "estimated"
    return "actual"


def _keep_for_status(row: dict, status: str) -> bool:
    quality = _quality(row)
    if status == "finalized":
        return quality == "actual"
    if status == "open":
        return quality in ("estimated", "unavailable") and bool(row.get("estimated"))
    return True


def _scale_amount(value: Any, factor: Decimal) -> Optional[float]:
    if value is None:
        return None
    return float(
        (Decimal(str(value)) * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


def _copy_slice(row: dict, **overrides) -> dict:
    copied = dict(row)
    copied["notes"] = list(row.get("notes") or [])
    copied.update(overrides)
    return copied


def _prorate_slice(
    row: dict,
    factor: Decimal,
    *,
    alloc_start: date,
    alloc_end: date,
    note: str,
) -> dict:
    overrides = {
        "alloc_start": _iso(alloc_start),
        "alloc_end": _iso(alloc_end),
        "allocation": "prorated",
        "allocation_note": note,
    }
    for field in _SCALED_FIELDS:
        overrides[field] = _scale_amount(row.get(field), factor)
    return _copy_slice(row, **overrides)


def _daily_total(user_id: int, start: date, end: date, daily: dict, daily_complete: bool):
    total = Decimal("0")
    seen = False
    for day in _iter_dates(start, end):
        key = (int(user_id), day.isoformat())
        if key in daily:
            seen = True
            total += Decimal(str(daily.get(key) or 0))
        elif daily_complete:
            seen = True
    if not seen:
        return None
    return total


def _allocation_factor(row: dict, part_start: date, part_end: date, daily: dict, daily_complete: bool):
    week_start = _parse_date(row["period_start"])
    week_end = _parse_date(row["period_end"])
    week_hours = _daily_total(row["user_id"], week_start, week_end, daily, daily_complete)
    part_hours = _daily_total(row["user_id"], part_start, part_end, daily, daily_complete)
    if week_hours is None or part_hours is None or week_hours <= 0:
        return None, None
    if part_hours <= 0:
        return Decimal("0"), week_hours
    return part_hours / week_hours, week_hours


def allocate_slices(
    slices: list[dict],
    *,
    range_start: date,
    range_end: date,
    frequency: str,
    daily_hours: Optional[dict] = None,
    daily_complete: bool = False,
) -> tuple[list[dict], dict[str, Any]]:
    """Clip payroll weeks to the range. Split calendar months when needed."""
    daily = daily_hours or {}
    kept: list[dict] = []
    excluded = []
    prorated = []
    for row in slices or []:
        week_start = _parse_date(row.get("period_start"))
        week_end = _parse_date(row.get("period_end"))
        if week_start is None or week_end is None:
            continue
        if not _overlaps(week_start, week_end, range_start, range_end):
            continue
        overlap_start = max(week_start, range_start)
        overlap_end = min(week_end, range_end)
        full_week = overlap_start == week_start and overlap_end == week_end
        if frequency == "monthly":
            pieces = _allocate_monthly(
                row,
                overlap_start,
                overlap_end,
                full_week=full_week,
                daily=daily,
                daily_complete=daily_complete,
            )
        else:
            pieces = _allocate_week_piece(
                row,
                overlap_start,
                overlap_end,
                full_week=full_week,
                daily=daily,
                daily_complete=daily_complete,
                reason="range",
            )
        if pieces is None:
            excluded.append(
                {
                    "user_id": row.get("user_id"),
                    "employee_name": row.get("employee_name"),
                    "period_start": row.get("period_start"),
                    "period_end": row.get("period_end"),
                    "reason": _exclusion_reason(frequency, full_week),
                }
            )
            continue
        for piece in pieces:
            if _q2(piece.get("payable_hours")) <= 0 and _q2(piece.get("gross_pay")) <= 0:
                continue
            kept.append(piece)
            if piece.get("allocation") == "prorated":
                prorated.append(
                    {
                        "user_id": piece.get("user_id"),
                        "employee_name": piece.get("employee_name"),
                        "period_start": piece.get("period_start"),
                        "period_end": piece.get("period_end"),
                        "alloc_start": piece.get("alloc_start"),
                        "alloc_end": piece.get("alloc_end"),
                        "note": piece.get("allocation_note") or "",
                    }
                )
    coverage = {
        "excluded_partial_periods": excluded,
        "prorated_periods": prorated,
        "daily_allocation": "available" if daily_complete else "unavailable",
    }
    return kept, coverage


def _exclusion_reason(frequency: str, full_week: bool) -> str:
    if frequency == "monthly" and full_week:
        return (
            "This payroll week crosses a calendar month and daily payable hours "
            "were not available, so it was left out of the monthly totals."
        )
    return (
        "This payroll week crosses the selected dates and daily payable hours "
        "were not available, so its amounts were left out instead of being assigned to one side."
    )


def _allocate_week_piece(
    row: dict,
    part_start: date,
    part_end: date,
    *,
    full_week: bool,
    daily: dict,
    daily_complete: bool,
    reason: str,
) -> Optional[list[dict]]:
    if full_week:
        return [_copy_slice(row, alloc_start=_iso(part_start), alloc_end=_iso(part_end), allocation="full")]
    factor, week_hours = _allocation_factor(row, part_start, part_end, daily, daily_complete)
    if factor is None:
        return None
    if factor <= 0:
        return []
    note = (
        f"Allocated by daily payable hours ({_q2(factor * week_hours)} of "
        f"{_q2(week_hours)} hours in this payroll week fall in {format_range_label(part_start, part_end)})."
    )
    return [
        _prorate_slice(
            row,
            factor,
            alloc_start=part_start,
            alloc_end=part_end,
            note=note,
        )
    ]


def _allocate_monthly(
    row: dict,
    overlap_start: date,
    overlap_end: date,
    *,
    full_week: bool,
    daily: dict,
    daily_complete: bool,
) -> Optional[list[dict]]:
    week_start = _parse_date(row["period_start"])
    week_end = _parse_date(row["period_end"])
    segments = _month_segments(overlap_start, overlap_end)
    crosses_month = week_start.month != week_end.month or week_start.year != week_end.year
    if len(segments) == 1 and full_week and not crosses_month:
        return [
            _copy_slice(
                row,
                alloc_start=_iso(overlap_start),
                alloc_end=_iso(overlap_end),
                allocation="full",
            )
        ]
    pieces = []
    for seg_start, seg_end in segments:
        covers_week = seg_start <= week_start and seg_end >= week_end
        if covers_week:
            pieces.append(
                _copy_slice(row, alloc_start=_iso(week_start), alloc_end=_iso(week_end), allocation="full")
            )
            continue
        factor, week_hours = _allocation_factor(row, seg_start, seg_end, daily, daily_complete)
        if factor is None:
            return None
        if factor <= 0:
            continue
        note = (
            f"Allocated to {seg_start.strftime('%B %Y')} by daily payable hours "
            f"({_q2(factor * week_hours)} of {_q2(week_hours)} hours in this payroll week)."
        )
        pieces.append(
            _prorate_slice(row, factor, alloc_start=seg_start, alloc_end=seg_end, note=note)
        )
    return pieces


def _data_label(slices: list[dict]) -> str:
    if not slices:
        return "No payroll in this range"
    qualities = {_quality(row) for row in slices}
    if "actual" in qualities and "estimated" in qualities:
        return "Mixed: Actual + Estimated"
    if "estimated" in qualities:
        return "Estimated"
    if "actual" in qualities:
        return "Actual"
    return "Unavailable"


def _target_status(rate: Optional[float], target: float) -> dict[str, Any]:
    if rate is None:
        return {
            "labor_cost_target": _q2(target),
            "target_delta_per_hour": None,
            "target_status": "unavailable",
        }
    delta = _q2(Decimal(str(rate)) - Decimal(str(target)))
    return {
        "labor_cost_target": _q2(target),
        "target_delta_per_hour": delta,
        "target_status": "above" if delta > 0.005 else "at_or_below",
    }


def summarize_slices(slices: list[dict], *, target: float, category: str = "all") -> dict[str, Any]:
    """Weighted totals. Rates are sums of dollars divided by sums of hours."""
    rows = list(slices or [])
    users = {row["user_id"] for row in rows}
    w2_users = {row["user_id"] for row in rows if row.get("worker_category") == "w2"}
    c1099_users = {row["user_id"] for row in rows if row.get("worker_category") == "contractor_1099"}
    temp_users = {row["user_id"] for row in rows if row.get("worker_category") == "temp"}
    payable = _sum(row.get("payable_hours") for row in rows)
    regular = _sum(row.get("regular_hours") for row in rows)
    ot_hours = _sum(row.get("ot_hours") for row in rows)
    gross = _sum(row.get("gross_pay") for row in rows)
    straight_gross = _sum(row.get("straight_time_gross") for row in rows)
    premium = _sum(row.get("ot_premium") for row in rows)
    ot_wages = _sum(row.get("ot_wages") for row in rows)

    cost_rows = [row for row in rows if row.get("total_employer_cost") is not None]
    cost_hours = _sum(row.get("payable_hours") for row in cost_rows)
    total_cost = _sum(row.get("total_employer_cost") for row in cost_rows) if cost_rows else None
    straight_rows = [
        row
        for row in cost_rows
        if row.get("straight_time_employer_cost") is not None
    ]
    straight_cost = (
        _sum(row.get("straight_time_employer_cost") for row in straight_rows) if straight_rows else None
    )
    straight_hours = _sum(row.get("payable_hours") for row in straight_rows)
    employer_extra = _sum(row.get("employer_expenses") for row in cost_rows) if cost_rows else None
    employer_ot_premium = None
    if straight_rows and total_cost is not None and straight_cost is not None:
        both_total = _sum(row.get("total_employer_cost") for row in straight_rows)
        employer_ot_premium = _q2(Decimal(str(both_total)) - Decimal(str(straight_cost)))

    employee_rate = _div(gross, payable)
    employee_without = _div(straight_gross, payable)
    employee_impact = None
    if employee_rate is not None and employee_without is not None and payable > 0:
        employee_impact = _div(premium, payable)
    employee_impact_pct = _pct(premium, straight_gross) if straight_gross else None

    employer_rate = _div(total_cost, cost_hours) if total_cost is not None else None
    employer_without = _div(straight_cost, straight_hours) if straight_cost is not None else None
    employer_impact = (
        _div(employer_ot_premium, straight_hours) if employer_ot_premium is not None else None
    )
    employer_impact_pct = None
    if employer_ot_premium is not None and straight_cost not in (None, 0):
        employer_impact_pct = _pct(employer_ot_premium, straight_cost)

    w2_cost_rows = [row for row in cost_rows if row.get("worker_category") == "w2"]
    w2_gross = _sum(row.get("gross_pay") for row in w2_cost_rows)
    w2_extra = _sum(row.get("employer_expenses") for row in w2_cost_rows)
    if category in ("contractor_1099", "temp"):
        if (employer_extra or 0) <= 0.005:
            burden = None
            burden_label = "N/A"
        else:
            burden = _pct(employer_extra, gross)
            burden_label = "Estimated" if any(row.get("estimated") for row in cost_rows) else "Actual"
    elif category == "all":
        burden = _pct(w2_extra, w2_gross) if w2_cost_rows else None
        burden_label = "W-2 only" if burden is not None else ("N/A" if rows else "")
    else:
        burden = _pct(w2_extra, w2_gross) if w2_cost_rows else None
        burden_label = "Actual" if burden is not None else ("N/A" if rows else "")
        if any(row.get("estimated") for row in w2_cost_rows) and burden is not None:
            if any(not row.get("estimated") for row in w2_cost_rows):
                burden_label = "Mixed: Actual + Estimated"
            else:
                burden_label = "Estimated"

    if category == "all" and burden is not None:
        if any(row.get("estimated") for row in w2_cost_rows) and any(
            not row.get("estimated") for row in w2_cost_rows
        ):
            burden_label = "Mixed: Actual + Estimated"
        elif w2_cost_rows and all(row.get("estimated") for row in w2_cost_rows):
            burden_label = "Estimated"
        elif w2_cost_rows:
            burden_label = "Actual"

    target_bits = _target_status(employer_rate, target)
    rate_label = employee_rate_label(category if category != "all" else "w2")
    if category in ("contractor_1099", "temp"):
        rate_label = "Worker Gross Rate"
    elif category == "all" and rows and not w2_users and (c1099_users or temp_users):
        rate_label = "Worker Gross Rate"

    wages = [row.get("base_wage") for row in rows if row.get("base_wage") is not None]
    blended = bool(wages) and (max(wages) - min(wages) > 0.009 or any(row.get("base_wage_blended") for row in rows))
    if wages and not blended:
        base_wage = _q2(wages[0])
    elif rows and payable > 0:
        base_wage = _div(_sum(row.get("base_earnings") for row in rows), payable)
        blended = len({_q2(item) for item in wages}) > 1 if wages else False
    else:
        base_wage = None

    return {
        "worker_count": len(users),
        "w2_worker_count": len(w2_users),
        "contractor_1099_worker_count": len(c1099_users),
        "temp_worker_count": len(temp_users),
        "payable_hours": payable,
        "regular_hours": regular,
        "ot_hours": ot_hours,
        "ot_percent": _pct(ot_hours, payable),
        "gross_pay": gross,
        "employer_expenses": employer_extra,
        "total_employer_cost": total_cost,
        "ot_premium": premium,
        "ot_wages": ot_wages,
        "employer_ot_premium": employer_ot_premium,
        "employee_effective_rate": employee_rate,
        "employee_rate_without_ot": employee_without,
        "employee_ot_impact_per_hour": employee_impact,
        "employee_ot_impact_percent": employee_impact_pct,
        "employer_effective_rate": employer_rate,
        "employer_rate_without_ot": employer_without,
        "employer_ot_impact_per_hour": employer_impact,
        "employer_ot_impact_percent": employer_impact_pct,
        "employer_burden_percent": burden,
        "employer_burden_label": burden_label,
        "employer_burden_scope": "w2_only",
        "employer_rate_hours": cost_hours,
        "employee_rate_label": rate_label,
        "base_wage": base_wage,
        "base_wage_blended": blended,
        "data_label": _data_label(rows),
        "target_scope": "team" if category == "all" else "classification",
        **target_bits,
    }


def _calendar(start: date, end: date, frequency: str, week_starts_on: int) -> list[tuple[date, date, str]]:
    windows = []
    if frequency == "weekly":
        cursor = align_week_start(start, week_starts_on)
        while cursor <= end:
            week_end = cursor + timedelta(days=6)
            if week_end >= start:
                windows.append((cursor, week_end, _iso(cursor)))
            cursor += timedelta(days=7)
    elif frequency == "biweekly":
        cursor = align_week_start(start, week_starts_on)
        pair_start, pair_end = biweekly_bounds(cursor, week_starts_on)
        while pair_start <= end:
            if pair_end >= start:
                windows.append((pair_start, pair_end, _iso(pair_start)))
            pair_start += timedelta(days=14)
            pair_end += timedelta(days=14)
    else:
        cursor = start.replace(day=1)
        while cursor <= end:
            month_end = _month_end(cursor)
            windows.append((cursor, month_end, f"{cursor.year:04d}-{cursor.month:02d}"))
            cursor = _add_months(cursor, 1).replace(day=1)
    return windows


def _slice_bucket_key(row: dict, frequency: str, week_starts_on: int) -> str:
    if frequency == "monthly":
        alloc = _parse_date(row.get("alloc_start")) or _parse_date(row.get("period_start"))
        return f"{alloc.year:04d}-{alloc.month:02d}"
    week = _parse_date(row.get("period_start"))
    if frequency == "biweekly":
        start, _end = biweekly_bounds(week, week_starts_on)
        return _iso(start)
    return _iso(align_week_start(week, week_starts_on))


def bucket_slices(
    slices: list[dict],
    *,
    range_start: date,
    range_end: date,
    frequency: str,
    week_starts_on: int,
    target: float,
) -> list[dict]:
    grouped: dict[str, list] = defaultdict(list)
    for row in slices or []:
        grouped[_slice_bucket_key(row, frequency, week_starts_on)].append(row)
    buckets = []
    for window_start, window_end, key in _calendar(range_start, range_end, frequency, week_starts_on):
        pieces = grouped.get(key, [])
        summary = summarize_slices(pieces, target=target)
        partial = any(piece.get("allocation") == "prorated" for piece in pieces) or (
            window_start < range_start or window_end > range_end
        )
        label = format_range_label(max(window_start, range_start), min(window_end, range_end))
        if frequency == "monthly":
            label = window_start.strftime("%b %Y")
        if partial and pieces:
            label = f"{label} (partial)"
        buckets.append(
            {
                "key": key,
                "label": label,
                "start": _iso(max(window_start, range_start)),
                "end": _iso(min(window_end, range_end)),
                "partial": bool(partial and pieces),
                **summary,
            }
        )
    return buckets


def _latest_period_windows(
    frequency: str,
    start: date,
    end: date,
    week_starts_on: int,
) -> tuple[tuple[date, date], tuple[date, date]]:
    if frequency == "weekly":
        week_start = align_week_start(end, week_starts_on)
        week_end = week_start + timedelta(days=6)
        previous = (week_start - timedelta(days=7), week_end - timedelta(days=7))
        current = (max(week_start, start), min(week_end, end))
        return current, previous
    if frequency == "biweekly":
        week_start = align_week_start(end, week_starts_on)
        pair_start, pair_end = biweekly_bounds(week_start, week_starts_on)
        current = (max(pair_start, start), min(pair_end, end))
        previous = (pair_start - timedelta(days=14), pair_end - timedelta(days=14))
        return current, previous
    month_start = end.replace(day=1)
    month_end = _month_end(end)
    current = (max(month_start, start), min(month_end, end))
    previous_end = month_start - timedelta(days=1)
    previous = (previous_end.replace(day=1), previous_end)
    return current, previous


def comparison_windows(
    mode: str,
    *,
    frequency: str,
    start: date,
    end: date,
    week_starts_on: int,
    compare_start: Optional[date] = None,
    compare_end: Optional[date] = None,
) -> Optional[dict[str, Any]]:
    name = str(mode or "none").strip().lower()
    if name in ("", "none"):
        return None
    if name not in COMPARE_MODES:
        raise ValueError("Invalid comparison")
    if name == "previous_equivalent":
        days = _days_inclusive(start, end)
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=days - 1)
        current = (start, end)
        previous = (prev_start, prev_end)
        scope = (
            f"Previous Equivalent Range compares {format_range_label(start, end)} with the "
            f"immediately preceding range of equal length ({format_range_label(prev_start, prev_end)})."
        )
    elif name == "previous_period":
        current, previous = _latest_period_windows(frequency, start, end, week_starts_on)
        scope = (
            f"Previous Period compares the latest {frequency} bucket in the selected range "
            f"({format_range_label(*current)}) with the immediately preceding bucket "
            f"({format_range_label(*previous)}). The KPI cards cover the full selected range."
        )
    else:
        if compare_start is None or compare_end is None:
            raise ValueError("Custom comparison needs a start and end date")
        if compare_end < compare_start:
            raise ValueError("Comparison end is before comparison start")
        current = (start, end)
        previous = (compare_start, compare_end)
        scope = (
            f"Custom comparison of {format_range_label(start, end)} with "
            f"{format_range_label(compare_start, compare_end)}."
        )
    current_days = _days_inclusive(*current)
    previous_days = _days_inclusive(*previous)
    mismatch = current_days != previous_days
    if mismatch:
        scope += (
            " These ranges have different lengths, so per-hour and per-week figures "
            "are included alongside the totals."
        )
    return {
        "mode": name,
        "current": current,
        "previous": previous,
        "current_days": current_days,
        "previous_days": previous_days,
        "duration_mismatch": mismatch,
        "scope_note": scope,
    }


def _change_row(
    *,
    key: str,
    label: str,
    kind: str,
    current: Any,
    previous: Any,
    current_days: int,
    previous_days: int,
    mismatch: bool,
    current_hours: Any = None,
    previous_hours: Any = None,
) -> dict[str, Any]:
    if current is None or previous is None:
        difference = None
        percent = None
    else:
        difference = _q2(Decimal(str(current)) - Decimal(str(previous)))
        if kind == "percentage_points":
            percent = None
        elif abs(float(previous)) < 0.005:
            percent = None
        else:
            percent = _pct(difference, abs(float(previous)))
    row = {
        "key": key,
        "label": label,
        "unit": kind,
        "change_kind": "percentage_points" if kind == "percentage_points" else "percent",
        "previous": previous,
        "current": current,
        "difference": difference,
        "percent_change": percent,
    }
    if mismatch and kind in ("hours", "money") and current is not None and previous is not None:
        row["current_per_week"] = _div(current, Decimal(current_days) / Decimal(7))
        row["previous_per_week"] = _div(previous, Decimal(previous_days) / Decimal(7))
        if kind == "money":
            row["current_per_hour"] = _div(current, current_hours)
            row["previous_per_hour"] = _div(previous, previous_hours)
    return row


_COMPARISON_METRICS = (
    ("payable_hours", "Total Payable Hours", "hours"),
    ("regular_hours", "Regular Hours", "hours"),
    ("ot_hours", "OT Hours", "hours"),
    ("ot_percent", "OT %", "percentage_points"),
    ("gross_pay", "Total Gross Wages", "money"),
    ("total_employer_cost", "Total Employer Payroll Cost", "money"),
    ("ot_premium", "OT Premium ($)", "money"),
    ("ot_wages", "Total OT Wages ($)", "money"),
    ("employer_ot_premium", "Employer OT Premium ($)", "money"),
    ("employee_effective_rate", "Average Employee Effective Rate", "rate"),
    ("employer_effective_rate", "Average Employer Effective Rate", "rate"),
    ("employer_ot_impact_per_hour", "Employer OT Impact/hr", "rate"),
    ("employer_burden_percent", "Employer Burden %", "percentage_points"),
    ("target_delta_per_hour", "Difference From $19 Target", "rate"),
)


def compare_summaries(
    current: dict,
    previous: dict,
    *,
    current_days: int,
    previous_days: int,
    duration_mismatch: bool,
) -> list[dict]:
    rows = []
    for key, label, kind in _COMPARISON_METRICS:
        shown = label
        if key == "target_delta_per_hour":
            target = current.get("labor_cost_target") or previous.get("labor_cost_target") or DEFAULT_LABOR_COST_TARGET
            shown = f"Difference From ${_q2(target):.2f} Target"
        rows.append(
            _change_row(
                key=key,
                label=shown,
                kind=kind,
                current=current.get(key),
                previous=previous.get(key),
                current_days=current_days,
                previous_days=previous_days,
                mismatch=duration_mismatch,
                current_hours=current.get("payable_hours"),
                previous_hours=previous.get("payable_hours"),
            )
        )
    return rows


def _period_delta(current: dict, previous: Optional[dict]) -> Optional[dict]:
    if previous is None:
        return None

    def diff(key):
        if current.get(key) is None or previous.get(key) is None:
            return None
        return _q2(Decimal(str(current[key])) - Decimal(str(previous[key])))

    return {
        "employer_effective_rate": diff("employer_effective_rate"),
        "ot_hours": diff("ot_hours"),
        "ot_percent": diff("ot_percent"),
        "ot_percent_kind": "percentage_points",
        "ot_premium": diff("ot_premium"),
        "employer_burden_percent": diff("employer_burden_percent"),
        "employer_burden_kind": "percentage_points",
        "total_employer_cost": diff("total_employer_cost"),
    }


def _employee_periods(
    slices: list[dict],
    *,
    frequency: str,
    week_starts_on: int,
    range_start: date,
    range_end: date,
    target: float,
) -> list[dict]:
    buckets = bucket_slices(
        slices,
        range_start=range_start,
        range_end=range_end,
        frequency=frequency,
        week_starts_on=week_starts_on,
        target=target,
    )
    periods = []
    previous = None
    for bucket in buckets:
        if (bucket.get("payable_hours") or 0) <= 0 and (bucket.get("gross_pay") or 0) <= 0:
            continue
        period = {
            "label": bucket["label"],
            "start": bucket["start"],
            "end": bucket["end"],
            "payable_hours": bucket["payable_hours"],
            "ot_hours": bucket["ot_hours"],
            "ot_percent": bucket["ot_percent"],
            "ot_premium": bucket["ot_premium"],
            "employer_burden_percent": bucket["employer_burden_percent"],
            "employer_burden_label": bucket["employer_burden_label"],
            "employer_effective_rate": bucket["employer_effective_rate"],
            "employee_effective_rate": bucket["employee_effective_rate"],
            "total_employer_cost": bucket["total_employer_cost"],
            "target_delta_per_hour": bucket["target_delta_per_hour"],
            "target_status": bucket["target_status"],
            "delta_vs_previous": _period_delta(bucket, previous),
        }
        periods.append(period)
        previous = bucket
    return periods


def _employee_rows(
    slices: list[dict],
    *,
    frequency: str,
    week_starts_on: int,
    range_start: date,
    range_end: date,
    target: float,
    comparison_slices: Optional[dict] = None,
    comparison_meta: Optional[dict] = None,
) -> list[dict]:
    grouped: dict[tuple, list] = defaultdict(list)
    for row in slices:
        grouped[(row["user_id"], row.get("worker_category") or "")].append(row)
    compared: dict[tuple, list] = defaultdict(list)
    for row in comparison_slices or []:
        compared[(row["user_id"], row.get("worker_category") or "")].append(row)
    employees = []
    for key, current_slices in grouped.items():
        if not current_slices:
            continue
        summary = summarize_slices(current_slices, target=target, category=key[1] or "all")
        summary["target_scope"] = "employee"
        user_id, category = key
        name = ""
        for row in current_slices or compared.get(key, []):
            if row.get("employee_name"):
                name = row["employee_name"]
                break
        comparison = None
        if comparison_meta:
            previous_summary = summarize_slices(
                compared.get(key, []),
                target=target,
                category=category or "all",
            )
            comparison = compare_summaries(
                summary,
                previous_summary,
                current_days=comparison_meta["current_days"],
                previous_days=comparison_meta["previous_days"],
                duration_mismatch=comparison_meta["duration_mismatch"],
            )
        employees.append(
            {
                "user_id": user_id,
                "employee_name": name or "Employee",
                "worker_category": category,
                "classification_label": classification_label(category),
                "employee_rate_label": employee_rate_label(category),
                **summary,
                "periods": _employee_periods(
                    current_slices,
                    frequency=frequency,
                    week_starts_on=week_starts_on,
                    range_start=range_start,
                    range_end=range_end,
                    target=target,
                ),
                "comparison": comparison,
            }
        )
    employees.sort(
        key=lambda item: (
            -(item.get("employer_ot_premium") or 0),
            item.get("employee_name") or "",
        )
    )
    return employees


def _coverage_notes(slices: list[dict], coverage: dict, summary: dict) -> list[str]:
    notes = []
    label = summary.get("data_label")
    if label == "Mixed: Actual + Estimated":
        notes.append(
            "Mixed: Actual + Estimated. Estimated employer costs are not finalized expenses."
        )
    elif label == "Estimated":
        notes.append("These employer costs are estimated. They are not finalized payroll expenses.")
    if coverage.get("excluded_partial_periods"):
        notes.append(
            "Some payroll weeks were left out because daily hours were not available to allocate them. "
            "Those amounts are not in the totals."
        )
    if coverage.get("prorated_periods"):
        notes.append("Some payroll weeks were allocated by the daily payable hours inside the selected dates.")
    hours = summary.get("payable_hours") or 0
    cost_hours = summary.get("employer_rate_hours") or 0
    if hours and abs(hours - cost_hours) > 0.05:
        notes.append(
            f"Employer rates use the {cost_hours:.2f} payable hours that have a known employer payroll cost "
            f"out of {hours:.2f} payable hours."
        )
    if summary.get("w2_worker_count") and (
        summary.get("contractor_1099_worker_count") or summary.get("temp_worker_count")
    ):
        notes.append(
            "Employer burden % is the W-2 payroll-tax burden only. The team employer rate includes 1099 and temp workers."
        )
    unique = []
    for row in slices:
        for note in row.get("notes") or []:
            if note not in unique:
                unique.append(note)
    notes.extend(unique[:6])
    return notes


def build_labor_cost_report(
    slices: list[dict],
    *,
    start: date,
    end: date,
    frequency: str = "weekly",
    week_starts_on: int = 0,
    status: str = "finalized",
    classification: str = "all",
    user_ids: Optional[set] = None,
    compare: str = "none",
    compare_start: Optional[date] = None,
    compare_end: Optional[date] = None,
    daily_hours: Optional[dict] = None,
    daily_complete: bool = False,
    target: float = DEFAULT_LABOR_COST_TARGET,
    include_employee_detail: bool = True,
    range_label: str = "",
    extra_notes: Optional[list] = None,
) -> dict[str, Any]:
    if frequency not in FREQUENCIES:
        raise ValueError("Frequency must be weekly, biweekly, or monthly")
    if status not in STATUSES:
        raise ValueError("Payroll status must be finalized, open, or all")
    if classification not in CLASSIFICATIONS:
        raise ValueError("Classification must be all, w2, or contractor_1099")
    if end < start:
        raise ValueError("End date is before start date")
    if _days_inclusive(start, end) > 800:
        raise ValueError("Date range is too long")

    selected = []
    for row in slices or []:
        if classification != "all" and row.get("worker_category") != classification:
            continue
        if not _keep_for_status(row, status):
            continue
        selected.append(row)

    directory = []
    seen_users = set()
    for row in selected:
        period_start = _parse_date(row.get("period_start"))
        period_end = _parse_date(row.get("period_end"))
        if period_start is None or not _overlaps(period_start, period_end, start, end):
            continue
        if row["user_id"] in seen_users:
            continue
        seen_users.add(row["user_id"])
        directory.append(
            {
                "user_id": row["user_id"],
                "employee_name": row.get("employee_name") or "Employee",
                "worker_category": row.get("worker_category"),
                "classification_label": classification_label(row.get("worker_category")),
            }
        )
    directory.sort(key=lambda item: item["employee_name"])

    if user_ids:
        wanted = {int(item) for item in user_ids}
        selected = [row for row in selected if int(row["user_id"]) in wanted]

    current_slices, coverage = allocate_slices(
        selected,
        range_start=start,
        range_end=end,
        frequency=frequency,
        daily_hours=daily_hours,
        daily_complete=daily_complete,
    )
    summary = summarize_slices(current_slices, target=target, category="all")
    by_classification = {
        "all": summary,
        "w2": summarize_slices(
            [row for row in current_slices if row.get("worker_category") == "w2"],
            target=target,
            category="w2",
        ),
        "contractor_1099": summarize_slices(
            [row for row in current_slices if row.get("worker_category") == "contractor_1099"],
            target=target,
            category="contractor_1099",
        ),
    }
    temp_slices = [row for row in current_slices if row.get("worker_category") == "temp"]
    if temp_slices:
        by_classification["temp"] = summarize_slices(temp_slices, target=target, category="temp")

    chart = bucket_slices(
        current_slices,
        range_start=start,
        range_end=end,
        frequency=frequency,
        week_starts_on=week_starts_on,
        target=target,
    )

    comparison_payload: dict[str, Any] = {"mode": "none"}
    comparison_slices: list[dict] = []
    comparison_meta = None
    windows = comparison_windows(
        compare,
        frequency=frequency,
        start=start,
        end=end,
        week_starts_on=week_starts_on,
        compare_start=compare_start,
        compare_end=compare_end,
    )
    if windows:
        comparison_meta = windows
        cur_start, cur_end = windows["current"]
        prev_start, prev_end = windows["previous"]
        current_for_compare, _cur_cov = allocate_slices(
            selected,
            range_start=cur_start,
            range_end=cur_end,
            frequency=frequency,
            daily_hours=daily_hours,
            daily_complete=daily_complete,
        )
        comparison_slices, _prev_cov = allocate_slices(
            selected,
            range_start=prev_start,
            range_end=prev_end,
            frequency=frequency,
            daily_hours=daily_hours,
            daily_complete=daily_complete,
        )
        current_summary = summarize_slices(current_for_compare, target=target)
        previous_summary = summarize_slices(comparison_slices, target=target)
        comparison_buckets = bucket_slices(
            comparison_slices,
            range_start=prev_start,
            range_end=prev_end,
            frequency=frequency,
            week_starts_on=week_starts_on,
            target=target,
        )
        aligned = bool(chart) and len(chart) == len(comparison_buckets)
        comparison_payload = {
            "mode": windows["mode"],
            "current_label": format_range_label(cur_start, cur_end),
            "previous_label": format_range_label(prev_start, prev_end),
            "current_start": _iso(cur_start),
            "current_end": _iso(cur_end),
            "previous_start": _iso(prev_start),
            "previous_end": _iso(prev_end),
            "current_days": windows["current_days"],
            "previous_days": windows["previous_days"],
            "duration_mismatch": windows["duration_mismatch"],
            "scope_note": windows["scope_note"],
            "rows": compare_summaries(
                current_summary,
                previous_summary,
                current_days=windows["current_days"],
                previous_days=windows["previous_days"],
                duration_mismatch=windows["duration_mismatch"],
            ),
            "chart_aligned": aligned,
            "comparison_buckets": comparison_buckets if aligned else [],
        }

    employees = _employee_rows(
        current_slices,
        frequency=frequency,
        week_starts_on=week_starts_on,
        range_start=start,
        range_end=end,
        target=target,
        comparison_slices=comparison_slices if windows else None,
        comparison_meta=comparison_meta,
    )
    if windows:
        comparison_payload["employees"] = [
            {
                "user_id": employee["user_id"],
                "employee_name": employee["employee_name"],
                "classification_label": employee["classification_label"],
                "rows": employee.get("comparison") or [],
            }
            for employee in employees
            if employee.get("comparison")
        ]

    notes = _coverage_notes(current_slices, coverage, summary)
    for note in extra_notes or []:
        if note and note not in notes:
            notes.append(note)
    if (
        summary.get("w2_worker_count", 0)
        + summary.get("contractor_1099_worker_count", 0)
        + summary.get("temp_worker_count", 0)
        > summary.get("worker_count", 0)
    ):
        notes.append(
            "A worker who appears in more than one classification is counted once in Total Workers and once in each classification."
        )

    if not include_employee_detail:
        employees = []
        directory = []
        comparison_payload["employees"] = []
        coverage["excluded_partial_periods"] = [
            {**item, "employee_name": "Employee", "user_id": None}
            for item in coverage.get("excluded_partial_periods") or []
        ]
        coverage["prorated_periods"] = [
            {**item, "employee_name": "Employee", "user_id": None}
            for item in coverage.get("prorated_periods") or []
        ]

    return {
        "title": "Labor Cost Analysis",
        "summary": summary,
        "by_classification": by_classification,
        "chart": {
            "default_metric": "employer_effective_rate",
            "buckets": chart,
            "comparison_aligned": bool(comparison_payload.get("chart_aligned")),
            "comparison_buckets": comparison_payload.get("comparison_buckets") or [],
        },
        "comparison": comparison_payload,
        "employees": employees,
        "directory": directory,
        "employee_detail": bool(include_employee_detail),
        "coverage": {**coverage, "notes": notes},
        "definitions": {
            "employee_effective_rate": "Gross earnings ÷ total payable hours. Includes overtime earnings and excludes employer payroll taxes. This is not take-home pay.",
            "employer_effective_rate": "Employer Payroll Cost ÷ total payable hours. Employer Payroll Cost is gross earnings plus recorded employer payroll taxes.",
            "ot_percent": "Overtime hours ÷ payable hours after unpaid breaks.",
            "ot_premium": "Additional gross wages above straight-time pay because hours were paid at overtime rates.",
            "ot_wages": "All gross earnings attributable to overtime hours, including the straight-time portion and the overtime premium.",
            "employer_ot_premium": "Overtime wage premium plus the incremental employer payroll taxes caused by that premium, using the stored tax components and wage-base caps.",
            "no_ot_premium": "Payable hours stay in both scenarios. The no-premium rate prices those hours at straight time.",
            "weighted_average": "Team and multi-period rates add the underlying dollars and hours first. They are not an average of the displayed rates.",
            "target": "The target compares the weighted average Employer Payroll Cost per hour for the workers in this selection.",
            "employer_payroll_cost": "Gross earnings plus recorded employer taxes (Social Security, Medicare, FUTA, SUTA, re-employment, and MCTMT when stored). Employee withholding is excluded. Workers' compensation is included only when it was already stored on the payroll line.",
        },
        "rules": {
            "payroll_week": PAYROLL_WEEK_RULE,
            "biweekly": BIWEEKLY_RULE,
            "biweekly_anchor": _iso(BIWEEKLY_ANCHOR),
            "monthly": "Monthly reporting uses calendar months. Cross-month payroll weeks are allocated by daily payable hours.",
            "week_starts_on": int(week_starts_on) % 7,
            "week_starts_on_label": WEEKDAY_NAMES[int(week_starts_on) % 7],
        },
        "filters": {
            "frequency": frequency,
            "start": _iso(start),
            "end": _iso(end),
            "range_label": range_label or format_range_label(start, end),
            "compare": compare or "none",
            "classification": classification,
            "status": status,
            "user_ids": sorted(int(item) for item in user_ids) if user_ids else [],
            "week_starts_on": int(week_starts_on) % 7,
            "week_starts_on_label": WEEKDAY_NAMES[int(week_starts_on) % 7],
            "labor_cost_target": _q2(target),
        },
    }


def _read_week_starts_on(conn, organization_id: int, as_of: date) -> int:
    try:
        from backend.payroll_identity import payroll_week_bounds

        week_start, _week_end = payroll_week_bounds(conn, as_of, int(organization_id))
        return int(week_start.weekday())
    except Exception:
        return 0


def _load_overlapping_rows(conn, organization_id: int, date_from: date, date_to: date) -> tuple[list[dict], bool]:
    from backend.payroll_operations import ensure_payout_batches_tables
    from backend.payroll_report import build_report_row
    from backend.ta_helpers import table_has_column

    ensure_payout_batches_tables(conn.cursor())
    cursor = conn.cursor(dictionary=True)
    has_details = table_has_column(cursor, "payout_batch_lines", "payout_details_json")
    has_official = table_has_column(cursor, "payout_batches", "official_pay_date")
    select_cols = """
        pb.id AS batch_id,
        pb.batch_name,
        pb.worker_category,
        pb.pay_period_start,
        pb.pay_period_end,
        pb.status AS batch_status,
        pb.payout_details_finalized_at,
        pbl.id AS line_id,
        pbl.user_id,
        pbl.worker_name_snapshot,
        pbl.approved_hours,
        pbl.ot_hours,
        pbl.rate,
        pbl.ot_rate,
        pbl.gross_amount,
        pbl.total_amount,
        pbl.gross_wages,
        pbl.sick_pay_amount,
        pbl.bonus_tip_amount,
        pbl.reimbursement_amount,
        pbl.adjustments,
        pbl.payment_status,
        pbl.net_pay
    """
    if has_official:
        select_cols += ", pb.official_pay_date"
    if has_details:
        select_cols += ", pbl.payout_details_json"
    query = f"""
        SELECT {select_cols}
        FROM payout_batch_lines pbl
        INNER JOIN payout_batches pb ON pb.id = pbl.batch_id
        WHERE pb.organization_id = %s AND pbl.organization_id = %s
          AND pb.pay_period_end >= %s AND pb.pay_period_start <= %s
        ORDER BY pb.pay_period_start, pbl.worker_name_snapshot
        LIMIT %s
    """
    cursor.execute(
        query,
        (int(organization_id), int(organization_id), _iso(date_from), _iso(date_to), ROW_LIMIT),
    )
    raw_rows = cursor.fetchall() or []
    truncated = len(raw_rows) >= ROW_LIMIT
    rows = []
    seen = set()
    for raw in raw_rows:
        line_id = raw.get("line_id")
        if line_id is not None and line_id in seen:
            continue
        batch = {
            "id": raw.get("batch_id"),
            "batch_name": raw.get("batch_name"),
            "worker_category": raw.get("worker_category"),
            "pay_period_start": raw.get("pay_period_start"),
            "pay_period_end": raw.get("pay_period_end"),
            "status": raw.get("batch_status"),
            "payout_details_finalized_at": raw.get("payout_details_finalized_at"),
            "official_pay_date": raw.get("official_pay_date") if has_official else None,
        }
        line = {
            "id": line_id,
            "user_id": raw.get("user_id"),
            "worker_name_snapshot": raw.get("worker_name_snapshot"),
            "approved_hours": raw.get("approved_hours"),
            "ot_hours": raw.get("ot_hours"),
            "rate": raw.get("rate"),
            "ot_rate": raw.get("ot_rate"),
            "gross_amount": raw.get("gross_amount"),
            "total_amount": raw.get("total_amount"),
            "gross_wages": raw.get("gross_wages"),
            "sick_pay_amount": raw.get("sick_pay_amount"),
            "bonus_tip_amount": raw.get("bonus_tip_amount"),
            "reimbursement_amount": raw.get("reimbursement_amount"),
            "adjustments": raw.get("adjustments"),
            "payment_status": raw.get("payment_status"),
            "net_pay": raw.get("net_pay"),
            "payout_details_json": raw.get("payout_details_json"),
        }
        rows.append(build_report_row(batch, line))
        if line_id is not None:
            seen.add(line_id)
    return rows, truncated


def _load_rate_intervals(conn, user_ids: set[int]) -> dict[int, list]:
    if not user_ids:
        return {}
    try:
        from backend.ta_helpers import table_exists

        check = conn.cursor()
        if not table_exists(check, "user_rates"):
            return {}
        cursor = conn.cursor(dictionary=True)
        placeholders = ", ".join(["%s"] * len(user_ids))
        cursor.execute(
            f"""
            SELECT user_id, hourly_rate, effective_date, end_date, id
            FROM user_rates
            WHERE user_id IN ({placeholders})
            """,
            tuple(int(item) for item in user_ids),
        )
        grouped: dict[int, list] = defaultdict(list)
        for row in cursor.fetchall() or []:
            grouped[int(row["user_id"])].append(row)
        return grouped
    except Exception:
        return {}


def _rate_on(intervals: list, work_date: str) -> Optional[float]:
    from backend.payroll_hourly_cost import _rate_num

    best = None
    for row in intervals or []:
        effective = str(row.get("effective_date") or "")[:10]
        end = row.get("end_date")
        end_text = str(end)[:10] if end else ""
        if effective and effective > work_date:
            continue
        if end_text and end_text < work_date:
            continue
        rank = (effective, int(row.get("id") or 0))
        if best is None or rank > best[0]:
            best = (rank, _rate_num(row.get("hourly_rate")))
    return None if best is None else best[1]


def _estimate_open_slice(
    records: list[dict],
    history_rows: list[dict],
    *,
    tax_settings: dict,
    target: float,
    week_start: date,
    week_end: date,
    policy: dict,
) -> Optional[dict]:
    if not records:
        return None
    user_id = int(records[0].get("user_id") or 0)
    category = str(records[0].get("worker_category") or "w2")
    name = ""
    for record in records:
        if record.get("worker_name"):
            name = record["worker_name"]
    rate_by_date = {}
    for record in records:
        work_date = str(record.get("work_date") or "")[:10]
        if work_date and record.get("_historical_rate") is not None:
            rate_by_date[work_date] = record.get("_historical_rate")
    prepared, changed = apply_historical_rates(records, rate_by_date)
    economics = economics_from_time_records(
        prepared,
        ot_threshold=(policy or {}).get("threshold_hours") or 40,
        ot_multiplier=(policy or {}).get("multiplier") or 1.5,
    )
    if economics.get("payable_hours", 0) <= 0:
        return None
    rate_note = None
    if changed:
        rate_note = "Hourly wage uses the user rate in effect on each work date."
    ot_setting_note = economics.pop("ot_setting_note", None)
    if ot_setting_note:
        rate_note = f"{rate_note} {ot_setting_note}".strip() if rate_note else ot_setting_note
    if category == "w2":
        periods = aggregate_finalized_w2_periods(
            history_rows,
            exclude_period=(_iso(week_start), _iso(week_end)),
        )
        burden = weighted_burden_from_periods(periods)
        analysis = analyze_employee_hourly_cost(
            worker_category=category,
            payable_hours=economics["payable_hours"],
            regular_hours=economics["regular_hours"],
            ot_hours=economics["ot_hours"],
            base_earnings=economics["base_earnings"],
            ot_premium=economics["ot_premium"],
            other_earnings=economics["other_earnings"],
            gross_pay=economics["gross_pay"],
            regular_rates=economics.get("regular_rates"),
            scenario="estimated",
            burden_percent=burden.get("burden_percent"),
            burden_sources=burden.get("sources"),
            tax_settings=tax_settings,
            labor_cost_target=target,
            rate_note=rate_note,
        )
    else:
        analysis = analyze_employee_hourly_cost(
            worker_category=category,
            payable_hours=economics["payable_hours"],
            regular_hours=economics["regular_hours"],
            ot_hours=economics["ot_hours"],
            base_earnings=economics["base_earnings"],
            ot_premium=economics["ot_premium"],
            other_earnings=0,
            gross_pay=economics["gross_pay"],
            total_payroll_cost=economics["gross_pay"],
            regular_rates=economics.get("regular_rates"),
            scenario="contractor",
            tax_settings=tax_settings,
            labor_cost_target=target,
            rate_note=rate_note,
        )
    return slice_from_analysis(
        analysis,
        user_id=user_id,
        employee_name=name,
        period_start=week_start,
        period_end=week_end,
        ot_wages=economics.get("ot_earnings") or 0,
        estimated=True,
    )


def _group_time_records(records: list[dict], week_starts_on: int) -> dict[tuple, list]:
    grouped: dict[tuple, list] = defaultdict(list)
    for record in records or []:
        work_day = _parse_date(record.get("work_date") or record.get("clock_in_at"))
        if work_day is None or not record.get("user_id"):
            continue
        week_start = align_week_start(work_day, week_starts_on)
        week_end = week_start + timedelta(days=6)
        category = str(record.get("worker_category") or "w2")
        grouped[(int(record["user_id"]), _iso(week_start), _iso(week_end), category)].append(record)
    return grouped


def _daily_from_records(records: list[dict]) -> dict[tuple, float]:
    daily: dict[tuple, Decimal] = defaultdict(lambda: Decimal("0"))
    for record in records or []:
        work_day = _parse_date(record.get("work_date") or record.get("clock_in_at"))
        if work_day is None or not record.get("user_id"):
            continue
        daily[(int(record["user_id"]), _iso(work_day))] += Decimal(str(record.get("approved_hours") or 0))
    return {key: float(value) for key, value in daily.items()}


def load_labor_cost_analysis(
    conn,
    organization_id: int,
    *,
    preset: str = "current_week",
    start: Optional[str] = None,
    end: Optional[str] = None,
    frequency: str = "weekly",
    compare: str = "none",
    compare_start: Optional[str] = None,
    compare_end: Optional[str] = None,
    classification: str = "all",
    user_ids: Optional[list] = None,
    status: str = "finalized",
    include_employee_detail: bool = True,
    as_of: Optional[date] = None,
) -> dict[str, Any]:
    """Read payroll and time records, then build the report. Does not write."""
    from backend.payroll_report_analytics import batch_is_complete
    from backend.payroll_tax_settings import fetch_payroll_tax_settings

    today = business_today(as_of)
    week_starts_on = _read_week_starts_on(conn, organization_id, today)
    freq = str(frequency or "weekly").strip().lower()
    if freq not in FREQUENCIES:
        raise ValueError("Frequency must be weekly, biweekly, or monthly")
    status_name = str(status or "finalized").strip().lower()
    if status_name == "estimated":
        status_name = "open"
    if status_name not in STATUSES:
        raise ValueError("Payroll status must be finalized, open, or all")
    preset_name = str(preset or "custom").strip().lower()
    if preset_name == "custom" or (start and end and preset_name not in PRESETS):
        range_start = _parse_date(start)
        range_end = _parse_date(end)
        if range_start is None or range_end is None:
            raise ValueError("Custom range needs a start and end date")
        range_label = "Custom range"
        preset_name = "custom"
    else:
        resolved = resolve_preset(preset_name, as_of=today, week_starts_on=week_starts_on)
        range_start = resolved["start"]
        range_end = resolved["end"]
        range_label = resolved["label"]
    if range_end < range_start:
        raise ValueError("End date is before start date")

    compare_name = str(compare or "none").strip().lower()
    custom_start = _parse_date(compare_start)
    custom_end = _parse_date(compare_end)
    windows = comparison_windows(
        compare_name,
        frequency=freq,
        start=range_start,
        end=range_end,
        week_starts_on=week_starts_on,
        compare_start=custom_start,
        compare_end=custom_end,
    )
    fetch_start = range_start
    fetch_end = range_end
    if windows:
        fetch_start = min(fetch_start, windows["previous"][0], windows["current"][0])
        fetch_end = max(fetch_end, windows["previous"][1], windows["current"][1])
    history_start = fetch_start - timedelta(days=HISTORY_LOOKBACK_DAYS)
    history_end = fetch_end + timedelta(days=7)

    tax_settings = {}
    try:
        tax_settings = fetch_payroll_tax_settings(conn, int(organization_id)) or {}
    except Exception:
        tax_settings = {}
    target = labor_cost_target_from_settings(tax_settings)

    rows, truncated = _load_overlapping_rows(conn, int(organization_id), history_start, history_end)
    rows_by_user: dict[int, list] = defaultdict(list)
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        if row.get("user_id") is None:
            continue
        rows_by_user[int(row["user_id"])].append(row)
        key = (
            int(row["user_id"]),
            str(row.get("pay_period_start") or "")[:10],
            str(row.get("pay_period_end") or "")[:10],
            str(row.get("worker_category") or ""),
        )
        groups[key].append(row)

    slices = []
    finalized_spans = []
    open_line_count = 0
    for key, group in groups.items():
        complete = [
            row
            for row in group
            if batch_is_complete(
                {
                    "batch_status": row.get("batch_status"),
                    "status": row.get("batch_status"),
                    "payout_details_finalized_at": row.get("details_finalized_at"),
                }
            )
        ]
        period_start = _parse_date(key[1])
        period_end = _parse_date(key[2])
        if period_start is None or period_end is None:
            continue
        in_window = _overlaps(period_start, period_end, fetch_start - timedelta(days=6), fetch_end + timedelta(days=6))
        if not in_window:
            continue
        if complete:
            piece = slice_from_payroll_rows(
                complete,
                tax_settings=tax_settings,
                labor_cost_target=target,
            )
            if piece and piece.get("payable_hours", 0) > 0:
                piece["estimated"] = False
                piece["finalized"] = True
                if piece.get("burden_status") == "estimated":
                    piece["burden_status"] = "actual"
                    piece["burden_label"] = "Actual"
                slices.append(piece)
                finalized_spans.append((piece["user_id"], period_start, period_end))
        elif group:
            open_line_count += 1

    needs_time = status_name in ("open", "all") or freq == "monthly" or not _range_is_whole_weeks(
        range_start, range_end, week_starts_on
    )
    if windows and (
        not _range_is_whole_weeks(windows["previous"][0], windows["previous"][1], week_starts_on)
        or not _range_is_whole_weeks(windows["current"][0], windows["current"][1], week_starts_on)
    ):
        needs_time = True

    daily = {}
    daily_complete = False
    extra_notes = []
    if truncated:
        extra_notes.append(
            "The payroll read reached its row limit. Older periods in this range may be missing."
        )
    if status_name == "finalized" and open_line_count:
        extra_notes.append(
            f"{open_line_count} employee payroll weeks in this range are still open and were omitted. "
            "Switch Payroll Status to Open / Estimated or All to include them, labeled Estimated."
        )

    if needs_time:
        time_from = fetch_start - timedelta(days=6)
        time_to = fetch_end + timedelta(days=6)
        records, time_note = _load_time_records(conn, int(organization_id), time_from, time_to)
        if time_note:
            extra_notes.append(time_note)
            daily_complete = False
        else:
            daily_complete = True
            daily = _daily_from_records(records)
        if status_name in ("open", "all") and records:
            intervals = _load_rate_intervals(conn, {int(r["user_id"]) for r in records if r.get("user_id")})
            policies = _overtime_policies(conn, int(organization_id))
            for key, week_records in _group_time_records(records, week_starts_on).items():
                user_id, week_start_text, week_end_text, category = key
                week_start = _parse_date(week_start_text)
                week_end = _parse_date(week_end_text)
                if week_start is None or not _overlaps(week_start, week_end, fetch_start, fetch_end):
                    continue
                if any(
                    uid == user_id and _overlaps(span_start, span_end, week_start, week_end)
                    for uid, span_start, span_end in finalized_spans
                ):
                    continue
                stamped = []
                for record in week_records:
                    copy = dict(record)
                    work_date = str(record.get("work_date") or "")[:10]
                    historical = _rate_on(intervals.get(user_id) or [], work_date)
                    if historical is not None:
                        copy["_historical_rate"] = historical
                    stamped.append(copy)
                piece = _estimate_open_slice(
                    stamped,
                    rows_by_user.get(user_id) or [],
                    tax_settings=tax_settings,
                    target=target,
                    week_start=week_start,
                    week_end=week_end,
                    policy=policies.get(category) or policies.get("w2") or {},
                )
                if piece:
                    slices.append(piece)

    wanted = None
    if user_ids:
        wanted = {int(item) for item in user_ids if str(item).strip()}
    report = build_labor_cost_report(
        slices,
        start=range_start,
        end=range_end,
        frequency=freq,
        week_starts_on=week_starts_on,
        status=status_name,
        classification=str(classification or "all"),
        user_ids=wanted,
        compare=compare_name,
        compare_start=custom_start,
        compare_end=custom_end,
        daily_hours=daily,
        daily_complete=daily_complete,
        target=target,
        include_employee_detail=include_employee_detail,
        range_label=range_label,
        extra_notes=extra_notes,
    )
    report["filters"]["preset"] = preset_name
    return report


def _range_is_whole_weeks(start: date, end: date, week_starts_on: int) -> bool:
    if start != align_week_start(start, week_starts_on):
        return False
    if (end - align_week_start(end, week_starts_on)).days != 6:
        return False
    return (end - start).days % 7 == 6


def _load_time_records(conn, organization_id: int, start: date, end: date) -> tuple[list[dict], str]:
    try:
        from backend.payroll_operations import list_time_records

        records = list_time_records(
            conn,
            int(organization_id),
            from_date=_iso(start),
            to_date=_iso(end),
            limit=TIME_RECORD_LIMIT,
        )
        if len(records) >= TIME_RECORD_LIMIT:
            return records, (
                "Daily time records hit the read limit, so partial weeks and cross-month weeks "
                "were not allocated."
            )
        return list(records or []), ""
    except Exception:
        return [], (
            "Daily time records were unavailable, so partial weeks and cross-month weeks "
            "were left out instead of being assigned to one side."
        )


def _overtime_policies(conn, organization_id: int) -> dict[str, dict]:
    policies = {}
    try:
        from backend.payroll_overtime import resolve_batch_overtime_policy

        for category in ("w2", "contractor_1099", "temp"):
            policies[category] = resolve_batch_overtime_policy(conn, int(organization_id), category)
    except Exception:
        policies = {
            "w2": {"threshold_hours": 40, "multiplier": 1.5},
            "contractor_1099": {"threshold_hours": 40, "multiplier": 1.5},
            "temp": {"threshold_hours": 40, "multiplier": 1.5},
        }
    return policies
