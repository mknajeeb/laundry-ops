"""Monthly chart verification must match the day dashboard assignment rules."""

from __future__ import annotations

from datetime import date, datetime
from unittest import mock

from backend.cleaning_task_activity import (
    STATUS_APPROVED,
    STATUS_COMPLETED,
    STATUS_PENDING_APPROVAL,
    dashboard_summary,
)
from backend.cleaning_task_dashboard_analytics import monthly_task_performance


class _Cur:
    def execute(self, *a, **k):
        return None

    def fetchone(self):
        return None

    def fetchall(self):
        return []


def _solo(rid, uid, role, group):
    return {
        "id": rid,
        "user_id": uid,
        "user_ids": [uid],
        "members": [{"id": rid, "user_id": uid}],
        "assignment_group_id": group,
        "week_start": "2026-10-25",
        "day_of_week": 4,
        "role": role,
        "execution_mode": "individual",
        "timing_mode": "anytime",
        "start_time": None,
        "timing_label": "",
    }


def _activity(aid, rid, uid, role, status, *, kind="standalone", parent=None, required=1, method="supervisor"):
    return {
        "id": aid,
        "responsibility_id": rid,
        "user_id": uid,
        "status": status,
        "role": role,
        "verification_required": required,
        "verification_method": method,
        "duration_seconds": 600 if parent is None else None,
        "parent_activity_id": parent,
        "activity_kind": kind,
        "business_date": date(2026, 10, 29),
    }


def _meta(cursor, organization_id, role_code):
    code = "closing" if role_code == "lint_cleaning" else "intra_day"
    return {"code": role_code, "category_code": code, "name": role_code}


def _run(assignments, activities, names, *, category=None):
    day = date(2026, 10, 29)
    cursor = _Cur()

    def responsibilities(cursor, organization_id, business_date=None, **kwargs):
        if business_date == day:
            return assignments
        return []

    def activities_for_day(cursor, organization_id, business_date, **kwargs):
        if business_date == day:
            return activities
        return []

    categories = [
        {"code": "intra_day", "name": "Intra-Day"},
        {"code": "closing", "name": "Closing"},
    ]
    patches = [
        mock.patch("backend.cleaning_task_activity.business_today", return_value=day),
        mock.patch("backend.cleaning_task_activity.business_now", return_value=datetime(2026, 10, 29, 18, 0)),
        mock.patch("backend.business_time.business_now", return_value=datetime(2026, 10, 29, 18, 0)),
        mock.patch("backend.cleaning_task_dashboard_analytics.business_today", return_value=day),
        mock.patch("backend.cleaning_task_activity._day_responsibilities", side_effect=responsibilities),
        mock.patch("backend.cleaning_task_dashboard_analytics._day_responsibilities", side_effect=responsibilities),
        mock.patch("backend.cleaning_task_activity._activities_for_day", side_effect=activities_for_day),
        mock.patch("backend.cleaning_task_dashboard_analytics._activities_for_day", side_effect=activities_for_day),
        mock.patch(
            "backend.cleaning_task_activity._role_catalog",
            return_value={
                "agroup_floor_washer": {"name": "Floor & Washer"},
                "lint_cleaning": {"name": "Dryer Lint"},
                "washer_residue": {"name": "Check Washer Residue"},
                "floor_brooming": {"name": "Floor Brooming"},
            },
        ),
        mock.patch(
            "backend.cleaning_task_dashboard_analytics._role_catalog",
            return_value={
                "agroup_floor_washer": {"name": "Floor & Washer"},
                "lint_cleaning": {"name": "Dryer Lint"},
                "washer_residue": {"name": "Check Washer Residue"},
                "floor_brooming": {"name": "Floor Brooming"},
            },
        ),
        mock.patch("backend.cleaning_task_activity._employee_names", return_value=names),
        mock.patch("backend.cleaning_task_dashboard_analytics._employee_names", return_value=names),
        mock.patch("backend.cleaning_task_activity._day_shifts_for_user", return_value=[]),
        mock.patch("backend.cleaning_task_activity._task_meta_for_role", side_effect=_meta),
        mock.patch("backend.cleaning_task_dashboard_analytics._task_meta_for_role", side_effect=_meta),
        mock.patch("backend.cleaning_task_activity.list_categories", return_value=categories),
        mock.patch("backend.cleaning_task_dashboard_analytics.list_categories", return_value=categories),
        mock.patch("backend.cleaning_task_activity.ensure_cleaning_task_activity_tables"),
        mock.patch("backend.cleaning_task_dashboard_analytics.ensure_cleaning_task_activity_tables"),
        mock.patch("backend.cleaning_task_activity.ensure_responsibilities_table"),
    ]
    for patch in patches:
        patch.start()
    try:
        summary = dashboard_summary(cursor, 3, business_date=day)
        monthly = monthly_task_performance(cursor, 3, year=2026, month=10, category_code=category)
    finally:
        for patch in reversed(patches):
            patch.stop()
    return summary, monthly


def _day(monthly, day=29):
    return next(row for row in monthly["days"] if row["day"] == day)


def _category_verified(summary, code):
    return next(
        row["verified"] for row in summary["category_breakdown"] if row["category_code"] == code
    )


def test_fully_verified_groups_match_dashboard_and_do_not_count_items():
    """October 29 shape: two groups with two approved items each, plus two approved standalone tasks.

    Task Review lists six individual rows. The dashboard and the monthly chart must both
    count four verified assignments.
    """
    names = {38: "Amna", 53: "Florentina", 19: "Jennifer Farfan", 30: "Evelin"}
    assignments = [
        _solo(201, 38, "agroup_floor_washer", "amna-floor"),
        _solo(202, 53, "agroup_floor_washer", "florentina-floor"),
        _solo(203, 19, "lint_cleaning", "jennifer-lint"),
        _solo(204, 30, "lint_cleaning", "evelin-lint"),
    ]
    activities = [
        _activity(301, 201, 38, "agroup_floor_washer", STATUS_COMPLETED, kind="group", required=0, method="none"),
        _activity(311, 201, 38, "washer_residue", STATUS_APPROVED, kind="group_item", parent=301),
        _activity(312, 201, 38, "floor_brooming", STATUS_APPROVED, kind="group_item", parent=301),
        _activity(302, 202, 53, "agroup_floor_washer", STATUS_COMPLETED, kind="group", required=0, method="none"),
        _activity(321, 202, 53, "washer_residue", STATUS_APPROVED, kind="group_item", parent=302),
        _activity(322, 202, 53, "floor_brooming", STATUS_APPROVED, kind="group_item", parent=302),
        _activity(303, 203, 19, "lint_cleaning", STATUS_APPROVED),
        _activity(304, 204, 30, "lint_cleaning", STATUS_APPROVED),
    ]
    summary, monthly = _run(assignments, activities, names)
    day = _day(monthly)
    assert summary["metrics"]["total_assigned"] == 4
    assert summary["metrics"]["verified"] == 4
    assert summary["metrics"]["pending_verification"] == 0
    assert day["assigned"] == 4
    assert day["verified"] == summary["metrics"]["verified"]
    assert day["completed"] == summary["metrics"]["completed"]
    assert day["pending_verification"] == summary["metrics"]["pending_verification"]
    assert monthly["totals"]["verified"] == 4
    assert sum(row["verified"] for row in monthly["days"]) == 4


def test_partial_group_is_not_verified_on_the_monthly_chart():
    names = {38: "Amna"}
    assignments = [_solo(201, 38, "agroup_floor_washer", "amna-floor")]
    activities = [
        _activity(301, 201, 38, "agroup_floor_washer", STATUS_COMPLETED, kind="group", required=0, method="none"),
        _activity(311, 201, 38, "washer_residue", STATUS_APPROVED, kind="group_item", parent=301),
        _activity(312, 201, 38, "floor_brooming", STATUS_PENDING_APPROVAL, kind="group_item", parent=301),
    ]
    summary, monthly = _run(assignments, activities, names)
    day = _day(monthly)
    assert summary["metrics"]["total_assigned"] == 1
    assert summary["metrics"]["completed"] == 1
    assert summary["metrics"]["verified"] == 0
    assert summary["metrics"]["pending_verification"] == 1
    assert day["verified"] == 0
    assert day["pending_verification"] == 1
    assert day["completed"] == 1
    assert day["assigned"] == 1


def test_shared_pair_counts_as_one_verified_assignment():
    names = {10: "Francis", 11: "Yesenia"}
    assignments = [
        {
            **_solo(1, 10, "agroup_floor_washer", "pair"),
            "user_ids": [10, 11],
            "execution_mode": "shared",
        },
        {
            **_solo(2, 11, "agroup_floor_washer", "pair"),
            "user_ids": [10, 11],
            "execution_mode": "shared",
        },
    ]
    activities = [
        _activity(1, 1, 10, "agroup_floor_washer", STATUS_COMPLETED, kind="group", required=0, method="none"),
        _activity(2, 2, 11, "agroup_floor_washer", STATUS_COMPLETED, kind="group", required=0, method="none"),
    ]
    summary, monthly = _run(assignments, activities, names)
    day = _day(monthly)
    assert summary["metrics"]["total_assigned"] == 1
    assert summary["metrics"]["verified"] == 1
    assert day["assigned"] == 1
    assert day["verified"] == 1
    assert day["completed"] == 1


def test_monthly_category_verified_matches_dashboard_category():
    names = {38: "Amna", 53: "Florentina", 19: "Jennifer Farfan", 30: "Evelin"}
    assignments = [
        _solo(201, 38, "agroup_floor_washer", "amna-floor"),
        _solo(202, 53, "agroup_floor_washer", "florentina-floor"),
        _solo(203, 19, "lint_cleaning", "jennifer-lint"),
        _solo(204, 30, "lint_cleaning", "evelin-lint"),
    ]
    activities = [
        _activity(301, 201, 38, "agroup_floor_washer", STATUS_COMPLETED, kind="group", required=0, method="none"),
        _activity(311, 201, 38, "washer_residue", STATUS_APPROVED, kind="group_item", parent=301),
        _activity(312, 201, 38, "floor_brooming", STATUS_APPROVED, kind="group_item", parent=301),
        _activity(302, 202, 53, "agroup_floor_washer", STATUS_COMPLETED, kind="group", required=0, method="none"),
        _activity(321, 202, 53, "washer_residue", STATUS_APPROVED, kind="group_item", parent=302),
        _activity(322, 202, 53, "floor_brooming", STATUS_APPROVED, kind="group_item", parent=302),
        _activity(303, 203, 19, "lint_cleaning", STATUS_APPROVED),
        _activity(304, 204, 30, "lint_cleaning", STATUS_APPROVED),
    ]
    summary, _all = _run(assignments, activities, names)
    _, intra = _run(assignments, activities, names, category="intra_day")
    _, closing = _run(assignments, activities, names, category="closing")
    assert _day(intra)["verified"] == _category_verified(summary, "intra_day") == 2
    assert _day(closing)["verified"] == _category_verified(summary, "closing") == 2
    assert _day(intra)["assigned"] == 2
    assert _day(closing)["assigned"] == 2
