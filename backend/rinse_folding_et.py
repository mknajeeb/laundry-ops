"""America/New_York calendar boundaries for folding filters and work_date."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from backend.rinse_scan_time import RINSE_SCAN_SOURCE_TIMEZONE

ET = ZoneInfo(RINSE_SCAN_SOURCE_TIMEZONE)


def eastern_now() -> datetime:
    return datetime.now(tz=ET)


def eastern_today() -> date:
    return eastern_now().date()


def eastern_week_bounds(anchor: date | None = None, *, week_start_day: str = "MONDAY") -> tuple[date, date]:
    """Inclusive Mon–Sun (or configured week start) in Eastern calendar."""
    d = anchor or eastern_today()
    if str(week_start_day or "MONDAY").upper().startswith("SUN"):
        start = d - timedelta(days=(d.weekday() + 1) % 7)
    else:
        start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def eastern_month_bounds(anchor: date | None = None) -> tuple[date, date]:
    d = anchor or eastern_today()
    start = date(d.year, d.month, 1)
    if d.month == 12:
        end = date(d.year, 12, 31)
    else:
        end = date(d.year, d.month + 1, 1) - timedelta(days=1)
    return start, end


def naive_et_day_start(d: date) -> datetime:
    """Inclusive start of Eastern calendar day (naive ET wall time)."""
    return datetime(d.year, d.month, d.day, 0, 0, 0)


def naive_et_day_end_inclusive(d: date) -> datetime:
    """Inclusive end of Eastern calendar day (naive ET wall time)."""
    return datetime(d.year, d.month, d.day, 23, 59, 59)


def naive_et_day_end_exclusive(d: date) -> datetime:
    """Start of next Eastern calendar day (for `<` upper bound)."""
    return naive_et_day_start(d + timedelta(days=1))


def rinse_wall_calendar_date(ts: datetime | None) -> date | None:
    """Calendar date for naive Rinse scan/folding DATETIME (already ET wall)."""
    if ts is None or ts == datetime.min:
        return None
    if not isinstance(ts, datetime):
        return None
    return ts.date()


def period_datetime_bounds_et(
    period_start: date, period_end: date
) -> tuple[datetime, datetime]:
    """Inclusive naive ET range [start, end] for the date span."""
    return naive_et_day_start(period_start), naive_et_day_end_inclusive(period_end)


def sql_period_filter_sql_and_args(
    date_field: str,
    period_start: date,
    period_end: date,
    *,
    perf_alias: str = "p",
    registry_alias: str = "r",
) -> tuple[str, list]:
    """
  ET-safe period filter. folding_work_date uses folding_end_at wall time;
  completed_at uses Eastern calendar date of registry completion timestamp.
  """
    p, r = perf_alias, registry_alias
    start_dt, end_dt = period_datetime_bounds_et(period_start, period_end)
    end_excl = naive_et_day_end_exclusive(period_end)
    field = str(date_field or "folding_work_date").strip().lower()

    if field == "date_clean":
        return (
            f" AND {r}.date_clean >= %s AND {r}.date_clean <= %s",
            [period_start, period_end],
        )

    if field == "completed_at":
        return (
            f" AND {r}.completed_at IS NOT NULL"
            f" AND {r}.completed_at >= %s AND {r}.completed_at < %s",
            [start_dt, end_excl],
        )

    # folding_work_date: anchor on clean/fold end (ET wall), fallback work_date
    return (
        f" AND ("
        f"({p}.folding_end_at IS NOT NULL AND {p}.folding_end_at >= %s AND {p}.folding_end_at < %s)"
        f" OR ({p}.folding_end_at IS NULL AND {p}.work_date >= %s AND {p}.work_date <= %s)"
        f")",
        [start_dt, end_excl, period_start, period_end],
    )
