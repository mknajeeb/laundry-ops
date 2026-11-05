"""Supervisor participation corrections stay separate from checklist check-offs."""

from datetime import datetime
import inspect

import pytest

from backend.cleaning_task_activity import CleaningTaskError
from backend.cleaning_task_dashboard_analytics import chart_status
from backend.cleaning_task_record_management import (
    correct_employee_participation,
    plan_participation_sessions,
)
from backend.cleaning_task_shared_execution import serialize_shared_item


def test_sessions_sum_work_time_and_keep_a_break_gap():
    plan = plan_participation_sessions(
        "finished",
        [
            {
                "started_at": datetime(2026, 11, 4, 9, 0),
                "ended_at": datetime(2026, 11, 4, 9, 18),
            },
            {
                "started_at": datetime(2026, 11, 4, 10, 0),
                "ended_at": datetime(2026, 11, 4, 10, 12),
            },
        ],
    )
    assert plan["duration_seconds"] == 18 * 60 + 12 * 60
    assert plan["sessions"][0]["ended_at"] == "2026-11-04 09:18:00"
    assert plan["ended_at"] == datetime(2026, 11, 4, 10, 12)


def test_overlapping_sessions_are_rejected():
    with pytest.raises(CleaningTaskError):
        plan_participation_sessions(
            "finished",
            [
                {"started_at": datetime(2026, 11, 4, 9, 0), "ended_at": datetime(2026, 11, 4, 10, 0)},
                {"started_at": datetime(2026, 11, 4, 9, 30), "ended_at": datetime(2026, 11, 4, 11, 0)},
            ],
        )


def test_not_started_has_no_sessions_and_a_short_reason_never_writes():
    assert plan_participation_sessions("not_started", [])["sessions"] == []

    class Cursor:
        def execute(self, *args, **kwargs):
            raise AssertionError("checklist and activity tables must not be touched")

    with pytest.raises(CleaningTaskError):
        correct_employee_participation(
            None,
            Cursor(),
            organization_id=1,
            supervisor_user_id=9,
            responsibility_id=4,
            employee_user_id=2,
            business_date="2026-11-04",
            participation_status="finished",
            sessions=[],
            reason="no",
        )


def test_participation_correction_does_not_call_checklist_checkoff():
    source = inspect.getsource(correct_employee_participation)
    assert "checkoff" not in source
    assert "shared_item_completions" not in source


def test_completed_without_approval_is_not_verified():
    assert chart_status(
        {
            "status": "completed",
            "overall_status": "completed",
            "completion_status": "completed",
            "verification_status": "not_required",
            "contributions": [{"status": "completed", "participation_status": "finished"}],
        }
    ) == "completed"


def test_open_item_shows_current_instructions_and_a_completed_item_keeps_the_snapshot():
    frozen = {
        "task_name": "Washer",
        "instructions": "Old wording",
        "instructions_es": "Texto viejo",
    }
    pending = serialize_shared_item(
        {"id": 1, "task_code": "washer", "status": "pending", "required": True, "definition_snapshot_json": frozen},
        meta={"name": "Washer", "instructions": "Sweep first.\nThen mop.", "instructions_es": "Barre primero."},
    )
    completed = serialize_shared_item(
        {"id": 2, "task_code": "washer", "status": "completed", "required": True, "definition_snapshot_json": frozen},
        meta={"name": "Washer", "instructions": "Sweep first.\nThen mop.", "instructions_es": "Barre primero."},
    )
    assert pending["instructions"] == "Sweep first.\nThen mop."
    assert completed["instructions"] == "Old wording"
    assert "\n" in pending["instructions"]
