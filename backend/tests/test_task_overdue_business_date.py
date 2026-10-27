"""Overdue classification must respect America/New_York business dates."""

from __future__ import annotations

from datetime import date, datetime
from unittest import mock

from backend.cleaning_task_activity import _is_overdue


def test_future_business_date_never_overdue_even_if_clock_past_deadline():
    with mock.patch("backend.cleaning_task_activity.business_today", return_value=date(2026, 10, 27)):
        assert (
            _is_overdue(
                timing_mode="specific_time",
                planned_start_time="10:00",
                now=datetime(2026, 10, 27, 15, 0),
                business_date=date(2026, 10, 28),
            )
            is False
        )


def test_anytime_not_overdue_on_current_day():
    with mock.patch("backend.cleaning_task_activity.business_today", return_value=date(2026, 10, 27)):
        assert (
            _is_overdue(
                timing_mode="anytime",
                planned_start_time=None,
                now=datetime(2026, 10, 27, 23, 50),
                business_date=date(2026, 10, 27),
            )
            is False
        )


def test_anytime_overdue_on_past_day():
    with mock.patch("backend.cleaning_task_activity.business_today", return_value=date(2026, 10, 27)):
        assert (
            _is_overdue(
                timing_mode="anytime",
                planned_start_time=None,
                now=datetime(2026, 10, 27, 9, 0),
                business_date=date(2026, 10, 26),
            )
            is True
        )


def test_specific_time_overdue_only_after_grace_on_current_day():
    with mock.patch("backend.cleaning_task_activity.business_today", return_value=date(2026, 10, 27)):
        assert (
            _is_overdue(
                timing_mode="specific_time",
                planned_start_time="10:00",
                now=datetime(2026, 10, 27, 10, 10),
                business_date=date(2026, 10, 27),
            )
            is False
        )
        assert (
            _is_overdue(
                timing_mode="specific_time",
                planned_start_time="10:00",
                now=datetime(2026, 10, 27, 10, 20),
                business_date=date(2026, 10, 27),
            )
            is True
        )


def test_past_timed_task_is_overdue():
    with mock.patch("backend.cleaning_task_activity.business_today", return_value=date(2026, 10, 27)):
        assert (
            _is_overdue(
                timing_mode="specific_time",
                planned_start_time="10:00",
                now=datetime(2026, 10, 27, 8, 0),
                business_date=date(2026, 10, 26),
            )
            is True
        )
