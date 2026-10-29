"""Dashboard metrics: shared tasks count once; approval is per contribution."""

from __future__ import annotations

from datetime import date, datetime
from unittest import mock

from backend.cleaning_task_activity import (
    STATUS_APPROVED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING_APPROVAL,
    dashboard_summary,
)


class _Cur:
    def __init__(self):
        self.tables = set()

    def execute(self, *a, **k):
        return None

    def fetchone(self):
        return None

    def fetchall(self):
        return []


def test_shared_assignment_counts_once_and_shift_end_lists_pending():
    cursor = _Cur()
    day = date(2026, 10, 27)
    assignments = [
        {
            "id": 1,
            "user_id": 10,
            "user_ids": [10, 11],
            "assignment_group_id": "g1",
            "week_start": "2026-10-25",
            "day_of_week": 2,
            "role": "floor_cleaning",
            "timing_mode": "anytime",
            "start_time": None,
            "timing_label": "",
        },
        {
            "id": 2,
            "user_id": 11,
            "user_ids": [10, 11],
            "assignment_group_id": "g1",
            "week_start": "2026-10-25",
            "day_of_week": 2,
            "role": "floor_cleaning",
            "timing_mode": "anytime",
            "start_time": None,
            "timing_label": "",
        },
        {
            "id": 3,
            "user_id": 10,
            "user_ids": [10],
            "assignment_group_id": "solo3",
            "week_start": "2026-10-25",
            "day_of_week": 2,
            "role": "lint_cleaning",
            "timing_mode": "anytime",
            "start_time": None,
            "timing_label": "",
        },
    ]
    activities = [
        {
            "id": 100,
            "organization_id": 3,
            "responsibility_id": 1,
            "assignment_group_id": "g1",
            "user_id": 10,
            "status": STATUS_PENDING_APPROVAL,
            "role": "floor_cleaning",
            "timing_mode": "anytime",
            "planned_start_time": None,
            "started_at": datetime(2026, 10, 27, 9, 0),
            "ended_at": datetime(2026, 10, 27, 9, 10),
            "duration_seconds": 600,
            "business_date": day,
            "approved_by_user_id": None,
        },
        {
            "id": 101,
            "organization_id": 3,
            "responsibility_id": 2,
            "assignment_group_id": "g1",
            "user_id": 11,
            "status": STATUS_IN_PROGRESS,
            "role": "floor_cleaning",
            "timing_mode": "anytime",
            "planned_start_time": None,
            "started_at": datetime(2026, 10, 27, 9, 5),
            "ended_at": None,
            "duration_seconds": None,
            "business_date": day,
            "approved_by_user_id": None,
        },
    ]
    with mock.patch(
        "backend.cleaning_task_activity.business_today", return_value=day
    ), mock.patch(
        "backend.cleaning_task_activity.business_now", return_value=datetime(2026, 10, 27, 12, 0)
    ), mock.patch(
        "backend.cleaning_task_activity._day_responsibilities", return_value=assignments
    ), mock.patch(
        "backend.cleaning_task_activity._activities_for_day", return_value=activities
    ), mock.patch(
        "backend.cleaning_task_activity._role_catalog",
        return_value={
            "floor_cleaning": {"name": "Floor Cleaning"},
            "lint_cleaning": {"name": "Lint Cleaning"},
        },
    ), mock.patch(
        "backend.cleaning_task_activity._employee_names",
        return_value={10: "Francis", 11: "Maria Perez"},
    ), mock.patch(
        "backend.cleaning_task_activity._day_shifts_for_user", return_value=[]
    ), mock.patch(
        "backend.cleaning_task_activity.ensure_cleaning_task_activity_tables"
    ), mock.patch(
        "backend.cleaning_task_activity.ensure_responsibilities_table"
    ):
        out = dashboard_summary(cursor, 3, business_date=day)

    assert out["metrics"]["total_assigned"] == 2  # shared floor + solo lint
    assert out["metrics"]["contributions_assigned"] == 3
    # Both people started the shared task; the solo task has not. Started is one assignment.
    assert out["metrics"]["started"] == 1
    assert out["metrics"]["completed"] == 0
    assert out["metrics"]["completion_rate"] == 0
    assert out["metrics"]["started"] <= out["metrics"]["total_assigned"]
    assert out["metrics"]["pending_approval"] == 1
    assert out["metrics"]["in_progress"] == 1
    assert out["approval_policy"] == "per_employee_contribution"
    assert len(out["shared_assignments"]) == 2
    shared = next(r for r in out["shared_assignments"] if r["shared"])
    assert len(shared["contributions"]) == 2
    assert len(out["shift_end"]["pending_approval"]) == 1
    assert len(out["shift_end"]["blocking_close"]) >= 2
    assert out["metrics"]["approved"] == 0
    # Approved contribution would still leave shared incomplete until both verified
    activities_approved = [
        {**activities[0], "status": STATUS_APPROVED, "approved_by_user_id": 7},
        activities[1],
    ]
    with mock.patch(
        "backend.cleaning_task_activity.business_today", return_value=day
    ), mock.patch(
        "backend.cleaning_task_activity.business_now", return_value=datetime(2026, 10, 27, 12, 0)
    ), mock.patch(
        "backend.cleaning_task_activity._day_responsibilities", return_value=assignments
    ), mock.patch(
        "backend.cleaning_task_activity._activities_for_day", return_value=activities_approved
    ), mock.patch(
        "backend.cleaning_task_activity._role_catalog",
        return_value={
            "floor_cleaning": {"name": "Floor Cleaning"},
            "lint_cleaning": {"name": "Lint Cleaning"},
        },
    ), mock.patch(
        "backend.cleaning_task_activity._employee_names",
        return_value={10: "Francis", 11: "Maria Perez", 7: "Supervisor"},
    ), mock.patch(
        "backend.cleaning_task_activity._day_shifts_for_user", return_value=[]
    ), mock.patch(
        "backend.cleaning_task_activity.ensure_cleaning_task_activity_tables"
    ), mock.patch(
        "backend.cleaning_task_activity.ensure_responsibilities_table"
    ):
        out2 = dashboard_summary(cursor, 3, business_date=day)
    assert out2["metrics"]["total_assigned"] == 2
    assert out2["metrics"]["approved"] == 1
    assert out2["metrics"]["started"] == 1
    assert out2["metrics"]["completed"] == 0


def _summary(assignments, activities, names):
    cursor = _Cur()
    day = date(2026, 10, 28)
    with mock.patch(
        "backend.cleaning_task_activity.business_today", return_value=day
    ), mock.patch(
        "backend.cleaning_task_activity.business_now", return_value=datetime(2026, 10, 28, 12, 0)
    ), mock.patch(
        "backend.cleaning_task_activity._day_responsibilities", return_value=assignments
    ), mock.patch(
        "backend.cleaning_task_activity._activities_for_day", return_value=activities
    ), mock.patch(
        "backend.cleaning_task_activity._role_catalog",
        return_value={
            "agroup_floor_washer": {"name": "Floor & Washer"},
            "lint_cleaning": {"name": "Lint Cleaning"},
        },
    ), mock.patch(
        "backend.cleaning_task_activity._employee_names",
        return_value=names,
    ), mock.patch(
        "backend.cleaning_task_activity._day_shifts_for_user", return_value=[]
    ), mock.patch(
        "backend.cleaning_task_activity.ensure_cleaning_task_activity_tables"
    ), mock.patch(
        "backend.cleaning_task_activity.ensure_responsibilities_table"
    ), mock.patch(
        "backend.cleaning_task_activity._task_meta_for_role",
        return_value={"category_code": "intra_day"},
    ):
        return dashboard_summary(cursor, 3, business_date=day)


def _solo(rid, uid, role, group):
    return {
        "id": rid,
        "user_id": uid,
        "user_ids": [uid],
        "members": [{"id": rid, "user_id": uid}],
        "assignment_group_id": group,
        "week_start": "2026-10-25",
        "day_of_week": 3,
        "role": role,
        "execution_mode": "individual",
        "timing_mode": "anytime",
        "start_time": None,
        "timing_label": "",
    }


def test_october_28_completed_rows_are_not_counted_twice():
    """Production shape: 4 assignments, two approved and two completed-without-verification.

    Those two completed rows used to land in the approved bucket and again in a
    separate completed total, so Started and Completed became 6 and the rate 150%.
    """
    from backend.cleaning_task_activity import STATUS_COMPLETED

    names = {35: "Mithila", 36: "Yesenia", 59: "Maria Rodriguez", 61: "Lily Chen"}
    assignments = [
        _solo(112, 59, "agroup_floor_washer", "g-maria"),
        _solo(113, 36, "agroup_floor_washer", "g-yesenia"),
        _solo(106, 61, "lint_cleaning", "g-lily"),
        _solo(114, 35, "lint_cleaning", "g-mithila"),
    ]
    activities = [
        {
            "id": 53,
            "responsibility_id": 114,
            "user_id": 35,
            "status": STATUS_APPROVED,
            "role": "lint_cleaning",
            "verification_required": 1,
            "verification_method": "supervisor",
            "duration_seconds": 1401,
            "parent_activity_id": None,
            "activity_kind": "standalone",
            "business_date": date(2026, 10, 28),
        },
        {
            "id": 54,
            "responsibility_id": 106,
            "user_id": 61,
            "status": STATUS_APPROVED,
            "role": "lint_cleaning",
            "verification_required": 1,
            "verification_method": "supervisor",
            "duration_seconds": 1198,
            "parent_activity_id": None,
            "activity_kind": "standalone",
            "business_date": date(2026, 10, 28),
        },
        {
            "id": 61,
            "responsibility_id": 113,
            "user_id": 36,
            "status": STATUS_COMPLETED,
            "role": "agroup_floor_washer",
            "verification_required": 0,
            "verification_method": "none",
            "completion_source": "corrected",
            "duration_seconds": 1200,
            "parent_activity_id": None,
            "activity_kind": "group",
            "business_date": date(2026, 10, 28),
        },
        {
            "id": 62,
            "responsibility_id": 112,
            "user_id": 59,
            "status": STATUS_COMPLETED,
            "role": "agroup_floor_washer",
            "verification_required": 0,
            "verification_method": "none",
            "completion_source": "manual",
            "duration_seconds": 1200,
            "parent_activity_id": None,
            "activity_kind": "group",
            "business_date": date(2026, 10, 28),
        },
        {
            "id": 99,
            "responsibility_id": 112,
            "user_id": 59,
            "status": STATUS_COMPLETED,
            "role": "agroup_floor_washer",
            "verification_required": 0,
            "verification_method": "none",
            "completion_source": "corrected",
            "duration_seconds": 100,
            "parent_activity_id": None,
            "activity_kind": "group",
            "business_date": date(2026, 10, 28),
        },
    ]
    out = _summary(assignments, activities, names)
    metrics = out["metrics"]
    assert metrics["total_assigned"] == 4
    assert metrics["started"] == 4
    assert metrics["completed"] == 4
    assert metrics["verified"] == 4
    assert metrics["completion_rate"] == 100
    assert metrics["started"] <= metrics["total_assigned"]
    assert metrics["completed"] <= metrics["total_assigned"]
    assert len(out["durations"]) == 5


def test_shared_pair_counts_once_and_keeps_both_timers():
    from backend.cleaning_task_activity import STATUS_COMPLETED

    assignments = [
        {
            "id": 1,
            "user_id": 10,
            "user_ids": [10, 11],
            "members": [{"id": 1, "user_id": 10}, {"id": 2, "user_id": 11}],
            "assignment_group_id": "shared-floor",
            "week_start": "2026-10-25",
            "day_of_week": 3,
            "role": "agroup_floor_washer",
            "execution_mode": "shared",
            "timing_mode": "anytime",
            "start_time": None,
            "timing_label": "",
        },
        {
            "id": 2,
            "user_id": 11,
            "user_ids": [10, 11],
            "members": [{"id": 1, "user_id": 10}, {"id": 2, "user_id": 11}],
            "assignment_group_id": "shared-floor",
            "week_start": "2026-10-25",
            "day_of_week": 3,
            "role": "agroup_floor_washer",
            "execution_mode": "shared",
            "timing_mode": "anytime",
            "start_time": None,
            "timing_label": "",
        },
    ]
    activities = [
        {
            "id": 1,
            "responsibility_id": 1,
            "user_id": 10,
            "status": STATUS_COMPLETED,
            "role": "agroup_floor_washer",
            "verification_required": 0,
            "verification_method": "none",
            "duration_seconds": 600,
            "parent_activity_id": None,
            "activity_kind": "group",
            "business_date": date(2026, 10, 28),
        },
        {
            "id": 2,
            "responsibility_id": 2,
            "user_id": 11,
            "status": STATUS_COMPLETED,
            "role": "agroup_floor_washer",
            "verification_required": 0,
            "verification_method": "none",
            "duration_seconds": 540,
            "parent_activity_id": None,
            "activity_kind": "group",
            "business_date": date(2026, 10, 28),
        },
    ]
    out = _summary(assignments, activities, {10: "Francis", 11: "Yesenia"})
    assert out["metrics"]["total_assigned"] == 1
    assert out["metrics"]["started"] == 1
    assert out["metrics"]["completed"] == 1
    assert out["metrics"]["verified"] == 1
    assert out["metrics"]["completion_rate"] == 100
    assert out["metrics"]["contributions_assigned"] == 2
    assert len(out["durations"]) == 2
    assert {row["employee_name"] for row in out["durations"]} == {"Francis", "Yesenia"}


def test_group_verification_follows_required_items_not_the_parent():
    """A finished activity group is completed, but not verified, while a required item waits."""
    from backend.cleaning_task_activity import STATUS_COMPLETED, STATUS_REJECTED

    day = date(2026, 10, 29)
    assignments = [
        _solo(201, 38, "agroup_floor_washer", "amna-floor"),
        _solo(202, 53, "agroup_floor_washer", "florentina-floor"),
        _solo(203, 19, "lint_cleaning", "jennifer-lint"),
        _solo(204, 30, "lint_cleaning", "evelin-lint"),
    ]
    activities = [
        {
            "id": 301,
            "responsibility_id": 201,
            "user_id": 38,
            "status": STATUS_COMPLETED,
            "role": "agroup_floor_washer",
            "verification_required": 0,
            "verification_method": "none",
            "duration_seconds": 600,
            "parent_activity_id": None,
            "activity_kind": "group",
            "business_date": day,
        },
        {
            "id": 311,
            "responsibility_id": 201,
            "user_id": 38,
            "status": STATUS_PENDING_APPROVAL,
            "role": "washer_residue",
            "verification_required": 1,
            "verification_method": "supervisor",
            "parent_activity_id": 301,
            "activity_kind": "group_item",
            "business_date": day,
        },
        {
            "id": 312,
            "responsibility_id": 201,
            "user_id": 38,
            "status": STATUS_PENDING_APPROVAL,
            "role": "floor_brooming",
            "verification_required": 1,
            "verification_method": "supervisor",
            "parent_activity_id": 301,
            "activity_kind": "group_item",
            "business_date": day,
        },
        {
            "id": 302,
            "responsibility_id": 202,
            "user_id": 53,
            "status": STATUS_COMPLETED,
            "role": "agroup_floor_washer",
            "verification_required": 0,
            "verification_method": "none",
            "duration_seconds": 600,
            "parent_activity_id": None,
            "activity_kind": "group",
            "business_date": day,
        },
        {
            "id": 321,
            "responsibility_id": 202,
            "user_id": 53,
            "status": STATUS_APPROVED,
            "role": "washer_residue",
            "verification_required": 1,
            "verification_method": "supervisor",
            "parent_activity_id": 302,
            "activity_kind": "group_item",
            "business_date": day,
        },
        {
            "id": 322,
            "responsibility_id": 202,
            "user_id": 53,
            "status": STATUS_PENDING_APPROVAL,
            "role": "floor_brooming",
            "verification_required": 1,
            "verification_method": "supervisor",
            "parent_activity_id": 302,
            "activity_kind": "group_item",
            "business_date": day,
        },
        {
            "id": 303,
            "responsibility_id": 203,
            "user_id": 19,
            "status": STATUS_PENDING_APPROVAL,
            "role": "lint_cleaning",
            "verification_required": 1,
            "verification_method": "supervisor",
            "duration_seconds": 400,
            "parent_activity_id": None,
            "activity_kind": "standalone",
            "business_date": day,
        },
        {
            "id": 304,
            "responsibility_id": 204,
            "user_id": 30,
            "status": STATUS_REJECTED,
            "role": "lint_cleaning",
            "verification_required": 1,
            "verification_method": "supervisor",
            "duration_seconds": 400,
            "parent_activity_id": None,
            "activity_kind": "standalone",
            "business_date": day,
        },
    ]
    out = _summary(
        assignments,
        activities,
        {38: "Amna", 53: "Florentina", 19: "Jennifer Farfan", 30: "Evelin"},
    )
    by_name = {row["assigned_employees"][0]: row for row in out["shared_assignments"]}
    amna = by_name["Amna"]
    florentina = by_name["Florentina"]
    jennifer = by_name["Jennifer Farfan"]
    evelin = by_name["Evelin"]
    assert amna["completion_status"] == "completed"
    assert amna["verification_status"] == "waiting"
    assert florentina["completion_status"] == "completed"
    assert florentina["verification_status"] == "partial"
    assert jennifer["completion_status"] == "completed"
    assert jennifer["verification_status"] == "waiting"
    assert evelin["completion_status"] == "completed"
    assert evelin["verification_status"] == "needs_correction"
    metrics = out["metrics"]
    assert metrics["total_assigned"] == 4
    assert metrics["completed"] == 4
    assert metrics["verified"] == 0
    assert metrics["pending_verification"] == 3
    assert metrics["rejected"] == 1
    waiting = out["shift_end"]["pending_approval"]
    waiting_names = {row["employee_name"] for row in waiting}
    assert waiting_names == {"Amna", "Florentina", "Jennifer Farfan"}
    waiting_ids = {row["activity"]["id"] for row in waiting}
    assert waiting_ids == {311, 312, 322, 303}
    assert 301 not in waiting_ids and 302 not in waiting_ids
    approved_ids = {row["activity"]["id"] for row in out["queue"]["approved"]}
    assert 321 in approved_ids
    assert 302 not in approved_ids
    assert {row["employee_name"] for row in out["shift_end"]["blocking_close"]} >= waiting_names
    assert amna["contributions"][0]["verification_status"] == "waiting"
    assert jennifer["contributions"][0]["verification_status"] == "waiting"


def test_partner_states_distinguish_working_from_not_started():
    from backend.cleaning_task_activity import partner_participation_state

    assert partner_participation_state(None) == "assigned"
    assert partner_participation_state("in_progress") == "working"
    assert partner_participation_state("completed") == "finished"
    assert partner_participation_state("approved") == "finished"
