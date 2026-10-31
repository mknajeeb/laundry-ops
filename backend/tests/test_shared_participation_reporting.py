"""Participation, checklist, overall completion, and verification stay separate.

Display and totals only. Stored activity rows are not rewritten.
"""

from __future__ import annotations

from backend.cleaning_task_activity import (
    COMPLETION_COMPLETED,
    COMPLETION_IN_PROGRESS,
    DISPLAY_COMPLETED,
    DISPLAY_IN_PROGRESS,
    DISPLAY_PENDING_APPROVAL,
    VERIFICATION_NOT_REQUIRED,
    VERIFICATION_VERIFIED,
    VERIFICATION_WAITING,
    apply_assignment_reporting,
    apply_rinse_task_dashboard_scope,
    apply_shared_checklist_to_assignment_status,
    assignment_is_completed,
    assignment_is_verified,
)
from backend.task_activity_groups import (
    default_require_checklist_before_completion,
    participation_finish_allowed_with_open_checklist,
)

PENDING = [
    {"required": True, "status": "pending", "task_code": "floor"},
    {"required": True, "status": "pending", "task_code": "washer"},
]
DONE = [
    {"required": True, "status": "completed", "task_code": "floor"},
    {"required": True, "status": "completed", "task_code": "washer"},
]


def _activity(status: str, **extra):
    row = {"status": status, "completion_source": "pin", "id": extra.pop("id", 1)}
    row.update(extra)
    return row


def _people(maria: str, rocio: str, *, maria_activity=None, rocio_activity=None):
    maria_row = {"employee_name": "Maria Perez", "employee_id": 11, "status": maria}
    rocio_row = {"employee_name": "Rocio", "employee_id": 12, "status": rocio}
    if maria_activity is not None:
        maria_row["activity"] = maria_activity
    if rocio_activity is not None:
        rocio_row["activity"] = rocio_activity
    return [maria_row, rocio_row]


def _shared(contribs, items, **overrides):
    row = {
        "shared": True,
        "execution_mode": "shared",
        "role": "agroup_floor_washer",
        "role_label": "Floor & Washer",
        "completion_status": COMPLETION_COMPLETED,
        "verification_status": VERIFICATION_WAITING,
        "status": DISPLAY_PENDING_APPROVAL,
        "shared_checklist_items": items,
        "contributions": contribs,
        "has_manual_completion": False,
    }
    row.update(overrides)
    return apply_assignment_reporting(row)


def test_two_employees_assigned_neither_started():
    row = _shared(
        _people("pending", "pending"),
        PENDING,
        completion_status="not_started",
        status="pending",
    )
    assert [c["participation_status"] for c in row["contributions"]] == [
        "not_started",
        "not_started",
    ]
    assert row["overall_status"] == "not_started"
    assert row["verification_status"] == VERIFICATION_NOT_REQUIRED
    assert row["checklist_done"] == 0 and row["checklist_required"] == 2
    assert assignment_is_completed(row) is False
    assert assignment_is_verified(row) is False


def test_one_employee_started_second_not_started():
    row = _shared(
        _people(
            "in_progress",
            "pending",
            maria_activity=_activity("in_progress", started_at="2026-10-30 09:00:00"),
        ),
        [
            {"required": True, "status": "completed", "completed_by_name": "Maria Perez"},
            {"required": True, "status": "pending"},
        ],
        completion_status=COMPLETION_IN_PROGRESS,
        status=DISPLAY_IN_PROGRESS,
    )
    assert [c["participation_status"] for c in row["contributions"]] == [
        "in_progress",
        "not_started",
    ]
    assert row["overall_status"] == COMPLETION_IN_PROGRESS
    assert row["verification_status"] == VERIFICATION_NOT_REQUIRED
    assert assignment_is_completed(row) is False


def test_one_employee_finished_second_not_started():
    stored = _activity("completed", started_at="2026-10-30 09:00:00", ended_at="2026-10-30 09:35:00")
    row = _shared(
        _people("completed", "pending", maria_activity=stored),
        PENDING,
    )
    assert [c["participation_status"] for c in row["contributions"]] == [
        "finished",
        "not_started",
    ]
    assert row["overall_status"] == COMPLETION_IN_PROGRESS
    assert row["employees_finished"] == 1 and row["employees_assigned"] == 2
    assert row["checklist_done"] == 0 and row["checklist_required"] == 2
    assert row["verification_status"] == VERIFICATION_NOT_REQUIRED
    assert assignment_is_completed(row) is False
    assert stored["status"] == "completed"


def test_both_finished_checklist_incomplete_stays_in_progress():
    maria = _activity("completed", id=1)
    rocio = _activity("completed", id=2)
    row = _shared(
        _people("completed", "completed", maria_activity=maria, rocio_activity=rocio),
        PENDING,
    )
    assert [c["participation_status"] for c in row["contributions"]] == ["finished", "finished"]
    assert row["overall_status"] == COMPLETION_IN_PROGRESS
    assert row["completion_status"] == COMPLETION_IN_PROGRESS
    assert row["checklist_complete"] is False
    assert row["verification_status"] == VERIFICATION_NOT_REQUIRED
    assert row["verification_eligible"] is False
    assert assignment_is_completed(row) is False
    assert assignment_is_verified(row) is False
    assert maria["status"] == "completed"
    assert rocio["status"] == "completed"
    assert maria is row["contributions"][0]["activity"]


def test_checklist_complete_one_employee_unfinished():
    row = _shared(
        _people("completed", "pending", maria_activity=_activity("completed")),
        DONE,
    )
    assert row["checklist_complete"] is True
    assert [c["participation_status"] for c in row["contributions"]] == [
        "finished",
        "not_started",
    ]
    assert row["overall_status"] == COMPLETION_IN_PROGRESS
    assert row["verification_status"] == VERIFICATION_NOT_REQUIRED
    assert assignment_is_completed(row) is False
    assert assignment_is_verified(row) is False


def test_checklist_complete_both_finished_is_pending_verification():
    row = _shared(
        _people(
            "completed",
            "completed",
            maria_activity=_activity("completed", id=1, verification_required=True),
            rocio_activity=_activity("completed", id=2, verification_required=True),
        ),
        DONE,
    )
    assert row["overall_status"] == "pending_verification"
    assert row["verification_status"] == VERIFICATION_WAITING
    assert row["verification_eligible"] is True
    assert assignment_is_completed(row) is True
    assert assignment_is_verified(row) is False


def test_supervisor_verification():
    row = _shared(
        _people(
            "approved",
            "approved",
            maria_activity=_activity("approved", id=1, verification_required=True),
            rocio_activity=_activity("approved", id=2, verification_required=True),
        ),
        DONE,
        verification_status=VERIFICATION_VERIFIED,
        status="approved",
    )
    assert row["overall_status"] == VERIFICATION_VERIFIED
    assert assignment_is_completed(row) is True
    assert assignment_is_verified(row) is True


def test_group_counts_once_in_assignment_totals():
    row = _shared(
        _people(
            "approved",
            "approved",
            maria_activity=_activity("approved", id=1, verification_required=True),
            rocio_activity=_activity("approved", id=2, verification_required=True),
        ),
        DONE,
        verification_status=VERIFICATION_VERIFIED,
        status="approved",
    )
    rows = [row]
    assert len(row["contributions"]) == 2
    assert sum(1 for item in rows if assignment_is_completed(item)) == 1
    assert sum(1 for item in rows if assignment_is_verified(item)) == 1


def test_rinse_does_not_count_unchecked_assignment():
    maria = _activity(
        "completed",
        id=1,
        started_at="2026-10-30 09:00:00",
        ended_at="2026-10-30 09:35:00",
        duration_seconds=2100,
    )
    rocio = _activity("completed", id=2, duration_seconds=1800)
    row = _shared(
        _people("completed", "completed", maria_activity=maria, rocio_activity=rocio),
        PENDING,
    )
    scoped = apply_rinse_task_dashboard_scope(
        {"shared_assignments": [row], "activity_log": [{"id": 1}], "metrics": {}}
    )
    assert scoped["read_only"] is True
    assert scoped["can_approve"] is False
    assert scoped["activity_log"] == []
    visible = scoped["shared_assignments"]
    assert len(visible) == 1
    assert visible[0]["overall_status"] == COMPLETION_IN_PROGRESS
    assert visible[0]["contributions"][0]["activity"]["started_at"] == "2026-10-30 09:00:00"
    assert "duration_seconds" not in visible[0]["contributions"][0]["activity"]
    assert scoped["metrics"]["total_assigned"] == 1
    assert scoped["metrics"]["completed"] == 0
    assert scoped["metrics"]["pending_verification"] == 0
    assert scoped["metrics"]["verified"] == 0
    assert scoped["metrics"]["contributions_assigned"] == 2


def test_rinse_counts_ready_assignment_as_pending_verification_once():
    row = _shared(
        _people(
            "completed",
            "completed",
            maria_activity=_activity("completed", id=1, verification_required=True),
            rocio_activity=_activity("completed", id=2, verification_required=True),
        ),
        DONE,
    )
    scoped = apply_rinse_task_dashboard_scope({"shared_assignments": [row]})
    assert scoped["metrics"]["total_assigned"] == 1
    assert scoped["metrics"]["completed"] == 1
    assert scoped["metrics"]["pending_verification"] == 1
    assert scoped["metrics"]["verified"] == 0
    assert scoped["shared_assignments"][0]["overall_status"] == "pending_verification"


def test_pending_approval_rollup_does_not_survive_an_open_checklist():
    complete, _status, completion, rollup = apply_shared_checklist_to_assignment_status(
        PENDING,
        completion_status=COMPLETION_COMPLETED,
        rollup=DISPLAY_PENDING_APPROVAL,
        member_statuses=[DISPLAY_COMPLETED, DISPLAY_COMPLETED],
    )
    assert complete is False
    assert completion == COMPLETION_IN_PROGRESS
    assert rollup == DISPLAY_IN_PROGRESS


def test_historical_solo_activity_is_not_rewritten():
    activity = {"id": 9, "status": "completed", "completion_source": "pin"}
    row = apply_assignment_reporting(
        {
            "shared": False,
            "execution_mode": "individual",
            "completion_status": COMPLETION_COMPLETED,
            "verification_status": VERIFICATION_VERIFIED,
            "status": "approved",
            "contributions": [{"status": "approved", "activity": activity}],
        }
    )
    assert activity["status"] == "completed"
    assert activity is row["contributions"][0]["activity"]
    assert "overall_status" not in row
    assert row["contributions"][0]["participation_status"] == "finished"
    assert assignment_is_completed(row) is True
    assert assignment_is_verified(row) is True


def test_previously_verified_shared_assignment_stays_verified():
    activity = _activity("approved", id=3, verification_required=True)
    row = _shared(
        _people("approved", "approved", maria_activity=activity, rocio_activity=_activity("approved", id=4, verification_required=True)),
        DONE,
        verification_status=VERIFICATION_VERIFIED,
        status="approved",
    )
    assert activity["status"] == "approved"
    assert row["overall_status"] == VERIFICATION_VERIFIED
    assert assignment_is_verified(row) is True


def test_unset_required_group_blocks_finish_without_rewriting_the_flag():
    """NULL plus required items behaves as ON. The stored value stays NULL."""
    assert default_require_checklist_before_completion([{"required": True}, {"required": False}]) == 1
    assert default_require_checklist_before_completion([{"required": False}]) == 0
    assert (
        participation_finish_allowed_with_open_checklist(
            None, shared=True, has_required_items=True
        )
        is False
    )
    assert (
        participation_finish_allowed_with_open_checklist(
            None, shared=False, has_required_items=True
        )
        is False
    )
    assert (
        participation_finish_allowed_with_open_checklist(
            None, shared=True, has_required_items=False
        )
        is True
    )
    assert (
        participation_finish_allowed_with_open_checklist(
            None, shared=False, has_required_items=False
        )
        is True
    )


def test_explicit_off_allows_finish_while_checklist_is_open():
    assert (
        participation_finish_allowed_with_open_checklist(
            0, shared=True, has_required_items=True
        )
        is True
    )
    assert (
        participation_finish_allowed_with_open_checklist(
            False, shared=False, has_required_items=True
        )
        is True
    )
    assert (
        participation_finish_allowed_with_open_checklist(
            1, shared=True, has_required_items=True
        )
        is False
    )


def test_supervisor_cannot_verify_open_checklist_or_unfinished_group():
    open_checklist = _shared(
        _people(
            "approved",
            "approved",
            maria_activity=_activity("approved", id=1, verification_required=True),
            rocio_activity=_activity("approved", id=2, verification_required=True),
        ),
        PENDING,
        verification_status=VERIFICATION_VERIFIED,
        status="approved",
    )
    assert open_checklist["overall_status"] == COMPLETION_IN_PROGRESS
    assert open_checklist["verification_eligible"] is False
    assert assignment_is_verified(open_checklist) is False

    unfinished = _shared(
        _people(
            "approved",
            "pending",
            maria_activity=_activity("approved", id=1, verification_required=True),
        ),
        DONE,
        verification_status=VERIFICATION_VERIFIED,
        status="approved",
    )
    assert unfinished["contributions"][1]["participation_status"] == "not_started"
    assert unfinished["overall_status"] == COMPLETION_IN_PROGRESS
    assert assignment_is_verified(unfinished) is False
    assert assignment_is_completed(unfinished) is False
