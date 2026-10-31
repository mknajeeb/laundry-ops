"""Phase 3 record management + Rinse eligibility (unit, no live DB)."""

from __future__ import annotations

from datetime import datetime

import pytest

from backend.cleaning_task_activity import (
    COMPLETION_COMPLETED,
    COMPLETION_IN_PROGRESS,
    apply_rinse_task_dashboard_scope,
    completion_status_from_members,
)
from backend.cleaning_task_record_management import (
    activity_is_rinse_eligible,
    activity_is_voided,
    activity_has_manual_touch,
)


def test_rinse_eligible_pin_only():
    assert activity_is_rinse_eligible(
        {"completion_source": "pin", "times_manual": 0, "voided_at": None}
    )
    assert not activity_is_rinse_eligible({"completion_source": "manual"})
    assert not activity_is_rinse_eligible({"completion_source": "corrected"})
    assert not activity_is_rinse_eligible(
        {"completion_source": "pin", "times_manual": 1}
    )
    assert not activity_is_rinse_eligible(
        {"completion_source": "pin", "voided_at": datetime(2026, 10, 30, 12, 0, 0)}
    )
    assert not activity_is_rinse_eligible(
        {"completion_source": "pin", "superseded_by_activity_id": 99}
    )


def test_void_and_manual_helpers():
    assert activity_is_voided({"voided_at": "2026-10-30 12:00:00"})
    assert not activity_is_voided({"voided_at": None})
    assert activity_has_manual_touch({"completion_source": "manual"})
    assert activity_has_manual_touch({"times_manual": 1, "completion_source": "pin"})
    assert not activity_has_manual_touch({"completion_source": "pin", "times_manual": 0})


def test_rinse_scope_drops_activity_log_and_manual_assignments():
    payload = {
        "metrics": {"total_assigned": 2, "time_spent_seconds": 500},
        "durations": [{"seconds": 12}],
        "activity_log": [{"id": 1, "role": "lint_cleaning"}],
        "shared_assignments": [
            {
                "assignment_key": "g:manual",
                "has_manual_completion": True,
                "completion_status": "completed",
                "verification_status": "not_required",
                "contributions": [
                    {
                        "status": "completed",
                        "activity": {"completion_source": "manual", "id": 1},
                    }
                ],
            },
            {
                "assignment_key": "g:pin",
                "has_manual_completion": False,
                "completion_status": "completed",
                "verification_status": "verified",
                "contributions": [
                    {
                        "status": "approved",
                        "activity": {
                            "id": 2,
                            "completion_source": "pin",
                            "times_manual": 0,
                            "duration_seconds": 40,
                            "manual_reason": "should strip",
                        },
                    }
                ],
            },
        ],
        "queue": {"pending": []},
    }
    out = apply_rinse_task_dashboard_scope(payload)
    assert out["activity_log"] == []
    assert out["durations"] == []
    assert out["read_only"] is True
    assert out["can_manual_complete"] is False
    assert "queue" not in out
    assert len(out["shared_assignments"]) == 1
    assert out["shared_assignments"][0]["assignment_key"] == "g:pin"
    assert out["metrics"]["total_assigned"] == 1
    assert "time_spent_seconds" not in out["metrics"]
    contrib = out["shared_assignments"][0]["contributions"][0]
    act = contrib.get("activity") or {}
    assert "duration_seconds" not in act
    assert "manual_reason" not in act


def test_completion_members_finished():
    assert (
        completion_status_from_members(["completed", "approved"])
        == COMPLETION_COMPLETED
    )
    assert (
        completion_status_from_members(["completed", "in_progress"])
        == COMPLETION_IN_PROGRESS
    )


def test_shared_checklist_rollup_keeps_in_progress_when_items_pending():
    """Floor & Washer style: finished timers + pending shared checklist ⇒ In Progress."""
    from backend.cleaning_task_activity import (
        DISPLAY_COMPLETED,
        DISPLAY_IN_PROGRESS,
        apply_shared_checklist_to_assignment_status,
    )

    complete, _, completion, rollup = apply_shared_checklist_to_assignment_status(
        [{"required": True, "status": "pending"}, {"required": True, "status": "pending"}],
        completion_status=COMPLETION_COMPLETED,
        rollup=DISPLAY_COMPLETED,
        member_statuses=[DISPLAY_COMPLETED, DISPLAY_COMPLETED],
    )
    assert complete is False
    assert completion == COMPLETION_IN_PROGRESS
    assert rollup == DISPLAY_IN_PROGRESS


def test_duration_recalc_and_end_before_start():
    from backend.cleaning_task_record_management import _recalc_duration
    from datetime import datetime

    start = datetime(2026, 10, 30, 9, 0, 0)
    end = datetime(2026, 10, 30, 9, 32, 0)
    assert _recalc_duration(start, end) == 32 * 60
    assert _recalc_duration(end, start) == 0  # clamped; update_activity_record rejects end < start


def test_midnight_boundary_duration():
    from backend.cleaning_task_record_management import _recalc_duration
    from datetime import datetime

    start = datetime(2026, 10, 30, 23, 50, 0)
    end = datetime(2026, 10, 31, 0, 10, 0)
    assert _recalc_duration(start, end) == 20 * 60
