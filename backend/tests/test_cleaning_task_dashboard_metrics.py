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
    assert out["metrics"]["started"] == 2
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
