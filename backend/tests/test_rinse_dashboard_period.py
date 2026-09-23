"""Unit tests for Rinse Performance period + compare resolution."""

from __future__ import annotations

from datetime import date

import pytest

from backend.rinse_dashboard_period import (
    COMPARE_PREVIOUS_PERIOD,
    COMPARE_PREVIOUS_WEEK,
    MAX_PRIMARY_RANGE_DAYS,
    PERIOD_CUSTOM,
    PERIOD_LAST_7_DAYS,
    PERIOD_LAST_30_DAYS,
    PERIOD_THIS_WEEK,
    PeriodResolutionError,
    compute_delta,
    resolve_compare,
    resolve_period,
    resolve_period_and_compare,
)


def test_last_7_previous_period_equal_length():
    anchor = date(2026, 9, 21)  # Mon
    cur = resolve_period(period=PERIOD_LAST_7_DAYS, anchor=anchor)
    assert cur["start"] == date(2026, 9, 15)
    assert cur["end"] == date(2026, 9, 21)
    base = resolve_compare(current=cur, compare=COMPARE_PREVIOUS_PERIOD)
    assert base["start"] == date(2026, 9, 8)
    assert base["end"] == date(2026, 9, 14)
    assert base["day_count"] == 7


def test_last_30_previous_period_equal_length():
    anchor = date(2026, 9, 21)
    cur = resolve_period(period=PERIOD_LAST_30_DAYS, anchor=anchor)
    assert cur["day_count"] == 30
    base = resolve_compare(current=cur, compare=COMPARE_PREVIOUS_PERIOD)
    assert base["day_count"] == 30
    assert base["end"] == cur["start"].fromordinal(cur["start"].toordinal() - 1)


def test_custom_previous_period_equal_length():
    cur = resolve_period(
        period=PERIOD_CUSTOM,
        start=date(2026, 9, 5),
        end=date(2026, 9, 18),
        anchor=date(2026, 9, 21),
    )
    assert cur["day_count"] == 14
    base = resolve_compare(current=cur, compare=COMPARE_PREVIOUS_PERIOD)
    assert base["start"] == date(2026, 8, 22)
    assert base["end"] == date(2026, 9, 4)
    assert base["day_count"] == 14


def test_previous_week_always_calendar_mon_sun_independent_of_range(monkeypatch):
    """Any period + Previous Week → preceding calendar Mon–Sun (of business today)."""
    from backend import rinse_dashboard_period as rdp

    monkeypatch.setattr(rdp, "business_today", lambda: date(2026, 9, 22))  # Tue
    # Current = Last 7 Days (not a calendar week)
    cur = resolve_period(period=PERIOD_LAST_7_DAYS, anchor=date(2026, 9, 22))
    base = resolve_compare(current=cur, compare=COMPARE_PREVIOUS_WEEK)
    # This week Mon=Sep 21 → previous week Mon Sep 14 – Sun Sep 20
    assert base["start"] == date(2026, 9, 14)
    assert base["end"] == date(2026, 9, 20)
    assert base["day_count"] == 7

    # Same Previous Week even for custom long range
    cur2 = resolve_period(
        period=PERIOD_CUSTOM,
        start=date(2026, 9, 1),
        end=date(2026, 9, 20),
        anchor=date(2026, 9, 22),
    )
    base2 = resolve_compare(current=cur2, compare=COMPARE_PREVIOUS_WEEK)
    assert base2["start"] == base["start"]
    assert base2["end"] == base["end"]


def test_custom_range_cap():
    with pytest.raises(PeriodResolutionError, match="range_exceeds_max"):
        resolve_period(
            period=PERIOD_CUSTOM,
            start=date(2026, 8, 1),
            end=date(2026, 9, 10),  # > 31 days
            anchor=date(2026, 9, 21),
        )


def test_ensure_union_cap_with_compare():
    # 31-day primary + previous_period of 31 = 62 days OK
    windows = resolve_period_and_compare(
        period=PERIOD_LAST_30_DAYS,
        compare=COMPARE_PREVIOUS_PERIOD,
        anchor=date(2026, 9, 21),
    )
    assert (windows["ensure_end"] - windows["ensure_start"]).days + 1 <= 62


def test_compute_delta_zero_previous():
    d = compute_delta(10, 0)
    assert d["percent"] is None
    assert d["display"] == "—"
    d2 = compute_delta(10, None)
    assert d2["display"] == "—"


def test_this_week_bounds():
    cur = resolve_period(period=PERIOD_THIS_WEEK, anchor=date(2026, 9, 24))  # Thu
    assert cur["start"] == date(2026, 9, 21)
    assert cur["end"] == date(2026, 9, 27)
