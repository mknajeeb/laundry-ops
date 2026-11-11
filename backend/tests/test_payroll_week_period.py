"""Payroll weeks are seven inclusive America/New_York calendar dates."""

from datetime import date, datetime, timedelta

from backend.payroll_operations import _date_end_exclusive_dt, _date_start_dt
from backend.payroll_report_analytics import format_focus_period_label, period_key_from_row
from backend.payroll_week_period import (
    canonical_inclusive_period,
    collapse_period_pairs,
    inclusive_period_label,
    period_end_query_values,
    period_lookup_pairs,
)


def _dates(start: date):
    return [start + timedelta(days=i) for i in range(7)]


def test_november_weeks_are_seven_days_and_do_not_overlap():
    first = canonical_inclusive_period("2026-11-02", "2026-11-09")
    second = canonical_inclusive_period("2026-11-09", "2026-11-15")
    previous = canonical_inclusive_period("2026-10-26", "2026-11-01")
    assert first == (date(2026, 11, 2), date(2026, 11, 8))
    assert second == (date(2026, 11, 9), date(2026, 11, 15))
    assert previous == (date(2026, 10, 26), date(2026, 11, 1))
    assert len(_dates(first[0])) == 7
    assert set(_dates(first[0])).isdisjoint(set(_dates(second[0])))
    assert inclusive_period_label("2026-11-02", "2026-11-09") == "2026-11-02 – 2026-11-08"


def test_historical_sunday_end_is_unchanged():
    assert canonical_inclusive_period("2026-10-26", "2026-11-01") == (
        date(2026, 10, 26),
        date(2026, 11, 1),
    )
    assert period_end_query_values("2026-10-26", "2026-11-01") == [
        "2026-11-01",
        "2026-11-02",
    ]


def test_daylight_saving_weeks_stay_seven_calendar_dates():
    # US DST starts 2026-03-08 and ends 2026-11-01. Bounds are calendar dates.
    spring = canonical_inclusive_period("2026-03-02", "2026-03-09")
    fall = canonical_inclusive_period("2026-10-26", "2026-11-02")
    assert spring == (date(2026, 3, 2), date(2026, 3, 8))
    assert fall == (date(2026, 10, 26), date(2026, 11, 1))
    assert (spring[1] - spring[0]).days == 6
    assert (fall[1] - fall[0]).days == 6


def test_overnight_clock_in_date_picks_the_week():
    """Naive clock-in values are Eastern wall time. The clock-in date owns the week."""
    sunday_night = datetime(2026, 11, 8, 23, 10)
    monday_morning = datetime(2026, 11, 9, 4, 53)
    week_of = lambda day: day - timedelta(days=day.weekday())
    assert week_of(sunday_night.date()) == date(2026, 11, 2)
    assert week_of(monday_morning.date()) == date(2026, 11, 9)
    start, end = canonical_inclusive_period("2026-11-02", "2026-11-09")
    assert start <= sunday_night.date() <= end
    assert not (start <= monday_morning.date() <= end)
    window_start = _date_start_dt(start.isoformat())
    window_end = _date_end_exclusive_dt(end.isoformat())
    assert window_end == datetime(2026, 11, 9, 0, 0, 0)
    assert window_start <= sunday_night < window_end
    assert not (window_start <= monday_morning < window_end)


def test_stored_next_monday_matches_the_sunday_week_only():
    assert period_lookup_pairs("2026-11-02", "2026-11-09") == [
        ("2026-11-02", "2026-11-08"),
        ("2026-11-02", "2026-11-09"),
    ]
    assert collapse_period_pairs(
        [("2026-11-02", "2026-11-08"), ("2026-11-02", "2026-11-09"), ("2026-11-09", "2026-11-15")]
    ) == [
        ("2026-11-02", "2026-11-08"),
        ("2026-11-09", "2026-11-15"),
    ]
    assert format_focus_period_label("2026-11-02", "2026-11-09") == "Nov 2–8, 2026"
    assert period_key_from_row(
        {"pay_period_start": "2026-11-02", "pay_period_end": "2026-11-09"}
    ) == ("2026-11-02", "2026-11-08")
    assert period_key_from_row(
        {"pay_period_start": "2026-09-14", "pay_period_end": "2026-09-20"}
    ) == ("2026-09-14", "2026-09-20")
