"""Overdue business-date rules + Rinse task-dashboard labor stripping."""

from __future__ import annotations

from datetime import date, datetime
from unittest import mock

from backend.cleaning_task_activity import (
    _is_overdue,
    apply_rinse_task_dashboard_scope,
)


def test_future_business_date_never_overdue_even_if_clock_past_planned_time():
    # Bug repro: viewing Oct 28 tasks on Oct 27 evening marked 10:00 AM as overdue.
    with mock.patch("backend.cleaning_task_activity.business_today", return_value=date(2026, 10, 27)):
        assert (
            _is_overdue(
                timing_mode="specific_time",
                planned_start_time="10:00",
                now=datetime(2026, 10, 27, 19, 30),
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
                now=datetime(2026, 10, 27, 23, 0),
                business_date=date(2026, 10, 27),
            )
            is False
        )


def test_past_incomplete_is_overdue():
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


def test_today_timed_overdue_after_grace():
    with mock.patch("backend.cleaning_task_activity.business_today", return_value=date(2026, 10, 27)):
        assert (
            _is_overdue(
                timing_mode="specific_time",
                planned_start_time="10:00",
                now=datetime(2026, 10, 27, 10, 20),
                business_date=date(2026, 10, 27),
            )
            is True
        )
        assert (
            _is_overdue(
                timing_mode="specific_time",
                planned_start_time="10:00",
                now=datetime(2026, 10, 27, 10, 10),
                business_date=date(2026, 10, 27),
            )
            is False
        )


def test_rinse_dashboard_strips_duration_fields():
    payload = {
        "metrics": {"total_assigned": 2, "time_spent_seconds": 900, "overdue": 0},
        "durations": [{"activity_id": 1, "duration_seconds": 120}],
        "shared_assignments": [
            {
                "role": "floor_cleaning",
                "status": "pending",
                "contributions": [
                    {
                        "employee_name": "Amna",
                        "status": "pending_approval",
                        "group_duration_seconds": 300,
                        "activity": {"id": 9, "duration_seconds": 300, "status": "pending_approval"},
                    }
                ],
            }
        ],
        "activity_log": [{"id": 9, "duration_seconds": 300, "status": "pending_approval"}],
        "checklists": [
            {
                "checklist_name": "EOD",
                "groups": [
                    {
                        "group_name": "Floor",
                        "items": [{"task_code": "floor", "activities": [{"duration_seconds": 40}]}],
                    }
                ],
            }
        ],
        "queue": {
            "pending_approval": [{"activity": {"duration_seconds": 12}}],
            "shift_end": {
                "blocking_close": [{"activity": {"id": 1, "duration_seconds": 38}}],
                "incomplete": [{"activity": {"id": 2, "duration_seconds": 40}}],
            },
        },
        "shift_end": {"blocking_close": [{"activity": {"duration_seconds": 12}}]},
    }
    out = apply_rinse_task_dashboard_scope(payload)
    assert "time_spent_seconds" not in out["metrics"]
    assert out["durations"] == []
    assert out["hide_labor_metrics"] is True
    contrib = out["shared_assignments"][0]["contributions"][0]
    assert "group_duration_seconds" not in contrib
    assert "duration_seconds" not in (contrib.get("activity") or {})
    assert "duration_seconds" not in out["activity_log"][0]
    nested = out["checklists"][0]["groups"][0]["items"][0]["activities"][0]
    assert "duration_seconds" not in nested
    assert "duration_seconds" not in out["queue"]["pending_approval"][0]["activity"]
    assert "duration_seconds" not in out["queue"]["shift_end"]["blocking_close"][0]["activity"]
    assert "duration_seconds" not in out["queue"]["shift_end"]["incomplete"][0]["activity"]
    assert "duration_seconds" not in out["shift_end"]["blocking_close"][0]["activity"]
