"""Unit tests for Task Dashboard enhancements (manual completion + labels + monthly)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from backend.cleaning_task_activity import friendly_status_label, serialize_activity
from backend.cleaning_task_manual_completion import (
    SOURCE_MANUAL,
    completion_source_label,
    parse_manual_payload,
)
from backend.cleaning_task_dashboard_analytics import _month_bounds


def test_friendly_status_labels():
    assert friendly_status_label("pending") == "Not Started"
    assert friendly_status_label("in_progress") == "In Progress"
    assert friendly_status_label("pending_approval") == "Waiting for Verification"
    assert friendly_status_label("approved") == "Verified"
    assert friendly_status_label("completed") == "Completed"
    assert friendly_status_label("rejected") == "Needs Correction"
    assert friendly_status_label("overdue", overdue=True) == "Overdue"


def test_completion_source_labels():
    assert completion_source_label("pin") == "Completed via PIN"
    assert completion_source_label(SOURCE_MANUAL) == "Recorded by Supervisor"
    assert completion_source_label("corrected") == "Corrected by Supervisor"


def test_parse_manual_payload_datetime_and_optional_start():
    parsed = parse_manual_payload(
        {
            "completion_date": "2026-10-28",
            "completion_time": "10:15",
            "reason": "Employee forgot PIN",
            "employee_user_id": 36,
            "responsibility_id": 99,
        }
    )
    assert parsed["completed_at"] == datetime(2026, 10, 28, 10, 15)
    assert parsed["started_at"] is None
    assert parsed["employee_user_id"] == 36

    with_start = parse_manual_payload(
        {
            "completed_at": "2026-10-28 10:15",
            "start_date": "2026-10-28",
            "start_time": "10:00",
            "reason": "ok reason",
        }
    )
    assert with_start["started_at"] == datetime(2026, 10, 28, 10, 0)


def test_parse_manual_requires_reason_fields_for_complete():
    with pytest.raises(Exception):
        parse_manual_payload({"reason": "x"})  # missing completion time


def test_serialize_includes_manual_fields():
    row = {
        "id": 1,
        "organization_id": 3,
        "responsibility_id": 9,
        "user_id": 36,
        "business_date": date(2026, 10, 28),
        "role": "floor",
        "status": "pending_approval",
        "started_at": datetime(2026, 10, 28, 10, 0),
        "ended_at": datetime(2026, 10, 28, 10, 15),
        "duration_seconds": None,
        "completion_source": "manual",
        "recorded_by_user_id": 15,
        "manual_reason": "Forgot PIN",
        "times_manual": 1,
    }
    ser = serialize_activity(row)
    assert ser["is_manual_completion"] is True
    assert ser["completion_source_label"] == "Recorded by Supervisor"
    assert ser["status_label"] == "Waiting for Verification"
    assert ser["duration_seconds"] is None  # do not fabricate


def test_month_bounds():
    start, end = _month_bounds(2026, 10)
    assert start == date(2026, 10, 1)
    assert end == date(2026, 10, 31)


def test_parse_shared_item_completions_preserved():
    parsed = parse_manual_payload(
        {
            "completion_date": "2026-10-28",
            "completion_time": "10:15",
            "reason": "Forgot PIN app",
            "employee_user_id": 16,
            "responsibility_id": 10,
            "shared_item_completions": [
                {"task_code": "floor", "completed_by_user_id": 16},
                {"task_code": "lint", "completed_by_user_id": 36},
            ],
        }
    )
    assert len(parsed["shared_item_completions"]) == 2
    assert parsed["shared_item_completions"][1]["completed_by_user_id"] == 36
