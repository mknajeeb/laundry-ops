"""Shared checklist gates assignment Completed (display/totals; no historical rewrite)."""

from __future__ import annotations

from backend.cleaning_task_activity import (
    COMPLETION_COMPLETED,
    COMPLETION_IN_PROGRESS,
    DISPLAY_COMPLETED,
    DISPLAY_IN_PROGRESS,
    DISPLAY_PENDING_APPROVAL,
    VERIFICATION_WAITING,
    apply_shared_checklist_to_assignment_status,
    assignment_is_completed,
    shared_required_checklist_progress,
)


def test_required_checklist_progress():
    items = [
        {"required": True, "status": "pending"},
        {"required": True, "status": "completed"},
    ]
    complete, status, done, req = shared_required_checklist_progress(items)
    assert complete is False
    assert status == COMPLETION_IN_PROGRESS
    assert done == 1 and req == 2


def test_finished_timers_stay_in_progress_until_checklist_done():
    complete, checklist_status, completion, rollup = apply_shared_checklist_to_assignment_status(
        [
            {"required": True, "status": "pending"},
            {"required": True, "status": "pending"},
        ],
        completion_status=COMPLETION_COMPLETED,
        rollup=DISPLAY_COMPLETED,
        member_statuses=[DISPLAY_COMPLETED, DISPLAY_COMPLETED],
    )
    assert complete is False
    assert checklist_status == COMPLETION_IN_PROGRESS
    assert completion == COMPLETION_IN_PROGRESS
    assert rollup == DISPLAY_IN_PROGRESS


def test_checklist_complete_keeps_completed():
    complete, checklist_status, completion, rollup = apply_shared_checklist_to_assignment_status(
        [
            {"required": True, "status": "completed"},
            {"required": True, "status": "completed"},
        ],
        completion_status=COMPLETION_COMPLETED,
        rollup=DISPLAY_COMPLETED,
        member_statuses=[DISPLAY_COMPLETED, DISPLAY_COMPLETED],
    )
    assert complete is True
    assert checklist_status == COMPLETION_COMPLETED
    assert completion == COMPLETION_COMPLETED
    assert rollup == DISPLAY_COMPLETED


def test_assignment_is_completed_respects_checklist_flag():
    row = {
        "completion_status": COMPLETION_COMPLETED,
        "checklist_complete": False,
        "execution_mode": "shared",
        "contributions": [{"status": "completed"}, {"status": "completed"}],
    }
    assert assignment_is_completed(row) is False
    row["checklist_complete"] = True
    assert assignment_is_completed(row) is True


def test_assignment_is_completed_reads_shared_items():
    row = {
        "completion_status": COMPLETION_COMPLETED,
        "execution_mode": "shared",
        "shared_checklist_items": [
            {"required": True, "status": "pending"},
            {"required": True, "status": "completed"},
        ],
        "contributions": [{"status": "completed"}, {"status": "completed"}],
    }
    assert assignment_is_completed(row) is False


def test_pending_verification_rollup_constant_available():
    # Smoke: constants used when checklist done + verification waiting.
    assert DISPLAY_PENDING_APPROVAL
    assert VERIFICATION_WAITING
