"""Date ranges and management history stay complete and pageable."""

from datetime import date, datetime
from unittest import mock

import pytest

from backend.cleaning_task_activity import _activities_for_day, _prime_activities_for_range
from backend.cleaning_task_dashboard_analytics import (
    TaskDashboardRangeError,
    build_activity_frequency,
    build_employee_report,
    history_verification_label,
    monthly_task_performance,
    participation_rollup,
    resolve_task_dashboard_range,
)


def test_one_range_query_serves_every_day():
    class Cur:
        def __init__(self):
            self.calls = 0

        def execute(self, *args, **kwargs):
            self.calls += 1

        def fetchall(self):
            return [
                {
                    "id": 9,
                    "user_id": 2,
                    "business_date": date(2026, 11, 4),
                    "status": "pending",
                    "role": "lint",
                }
            ]

        def fetchone(self):
            return None

    cur = Cur()
    _prime_activities_for_range(cur, 1, date(2026, 11, 1), date(2026, 11, 7))
    assert cur.calls == 1
    assert _activities_for_day(cur, 1, date(2026, 11, 4))[0]["id"] == 9
    assert _activities_for_day(cur, 1, date(2026, 11, 2)) == []
    assert cur.calls == 1


def test_range_is_not_shortened():
    start, end = resolve_task_dashboard_range(date(2026, 8, 1), date(2026, 10, 29))
    assert start == date(2026, 8, 1)
    assert end == date(2026, 10, 29)
    assert (end - start).days + 1 == 90


def test_reversed_endpoints_are_ordered_without_dropping_days():
    start, end = resolve_task_dashboard_range(date(2026, 10, 29), date(2026, 8, 1))
    assert (start, end) == (date(2026, 8, 1), date(2026, 10, 29))


def test_overlong_range_is_rejected():
    with pytest.raises(TaskDashboardRangeError, match="367 days"):
        resolve_task_dashboard_range(date(2025, 1, 1), date(2026, 1, 2))


def test_participation_counts_people_once_and_skips_checklist_rows():
    roll = participation_rollup(
        [
            {
                "shared": True,
                "contributions": [
                    {
                        "participation_status": "finished",
                        "activity": {"duration_seconds": 3600, "timestamp_kind": "work_interval"},
                    },
                    {
                        "participation_status": "not_started",
                        "activity": {},
                    },
                    {
                        "participation_status": "finished",
                        "activity": {"duration_seconds": 30, "activity_kind": "group_item"},
                    },
                ],
            }
        ]
    )
    assert roll == {
        "employees_assigned": 3,
        "employees_started": 2,
        "employees_finished": 2,
        "total_time_seconds": 3600,
    }


def test_employee_report_counts_a_shared_activity_once():
    report = build_employee_report(
        [
            {
                "assignment_key": "g:2026-11-04:wash",
                "role": "agroup_wash",
                "role_label": "Washer Cleaning",
                "business_date": "2026-11-04",
                "status": "in_progress",
                "overall_status": "in_progress",
                "verification_status": "not_required",
                "verification_label": "Not Required",
                "checklist_done": 0,
                "checklist_required": 2,
                "assigned_employees": ["Evelin", "Florentina"],
                "shared_checklist_items": [
                    {"completed_by_user_id": 1, "status": "completed"},
                ],
                "contributions": [
                    {
                        "employee_id": 1,
                        "employee_name": "Evelin",
                        "status": "in_progress",
                        "participation_status": "in_progress",
                        "activity": {"started_at": "2026-11-04 10:00:00", "duration_seconds": 600},
                    },
                    {
                        "employee_id": 2,
                        "employee_name": "Florentina",
                        "participation_status": "not_started",
                        "activity": {},
                    },
                ],
            }
        ]
    )
    assert report["unique_activities"] == 1
    assert len(report["employees"]) == 2
    evelin = next(person for person in report["employees"] if person["employee_name"] == "Evelin")
    florentina = next(person for person in report["employees"] if person["employee_name"] == "Florentina")
    assert evelin["assigned"] == 1
    assert evelin["in_progress"] == 1
    assert evelin["verified"] == 0
    assert florentina["not_started"] == 1
    assert florentina["completed"] == 0
    assert florentina["verified"] == 0
    assert evelin["activities"][0]["checklist_completed_by_employee"] == 1
    assert florentina["activities"][0]["checklist_completed_by_employee"] == 0
    frequency = build_activity_frequency(
        [
            {
                "role": "agroup_dry",
                "role_label": "Dryer Lint Cleaning",
                "business_date": "2026-11-04",
                "status": "approved",
                "verification_status": "verified",
                "overall_status": "verified",
                "assigned_employees": ["Maria Perez", "Lily Chen"],
                "contributions": [],
            },
            {
                "role": "agroup_dry",
                "role_label": "Dryer Lint Cleaning",
                "business_date": "2026-11-03",
                "status": "approved",
                "verification_status": "verified",
                "overall_status": "verified",
                "assigned_employees": ["Jennifer", "Aselisa"],
                "contributions": [],
            },
        ]
    )
    assert frequency[0]["activity"] == "Dryer Lint Cleaning"
    assert frequency[0]["assigned"] == 2
    assert [row["business_date"] for row in frequency[0]["dates"]] == ["2026-11-04", "2026-11-03"]


def test_verification_label_stays_separate_from_completion():
    assert history_verification_label({"status": "approved", "verification_required": True}) == "Verified"
    assert (
        history_verification_label({"status": "pending_approval", "verification_required": True})
        == "Pending verification"
    )
    assert history_verification_label({"status": "completed", "verification_required": False}) == "Not required"


class _Cur:
    def execute(self, *args, **kwargs):
        return None

    def fetchone(self):
        return None

    def fetchall(self):
        return []


def test_history_pages_across_the_selected_range():
    start = date(2026, 10, 30)
    end = date(2026, 11, 1)
    activities = {
        date(2026, 10, 31): [
            {
                "id": 2,
                "user_id": 56,
                "status": "pending_approval",
                "role": "lint_cleaning",
                "verification_required": 1,
                "business_date": date(2026, 10, 31),
                "duration_seconds": 900,
            }
        ],
        date(2026, 11, 1): [
            {
                "id": 3,
                "user_id": 56,
                "status": "approved",
                "role": "lint_cleaning",
                "verification_required": 1,
                "business_date": date(2026, 11, 1),
                "duration_seconds": 600,
                "approved_by_user_id": 1,
            }
        ],
    }

    def activities_for_day(cursor, organization_id, business_date, **kwargs):
        return activities.get(business_date, [])

    patches = [
        mock.patch("backend.cleaning_task_dashboard_analytics.business_today", return_value=end),
        mock.patch("backend.cleaning_task_dashboard_analytics.ensure_cleaning_task_activity_tables"),
        mock.patch("backend.cleaning_task_dashboard_analytics._role_catalog", return_value={"lint_cleaning": {"name": "Dryer Lint"}}),
        mock.patch("backend.cleaning_task_dashboard_analytics._day_responsibilities", return_value=[]),
        mock.patch("backend.cleaning_task_dashboard_analytics._activities_for_day", side_effect=activities_for_day),
        mock.patch("backend.cleaning_task_dashboard_analytics._employee_names", return_value={56: "Gabriela"}),
        mock.patch(
            "backend.cleaning_task_dashboard_analytics._task_meta_for_role",
            return_value={"category_code": "intra_day", "name": "Dryer Lint"},
        ),
        mock.patch(
            "backend.cleaning_task_dashboard_analytics.list_categories",
            return_value=[{"code": "intra_day", "name": "Intra-Day"}],
        ),
        mock.patch(
            "backend.cleaning_task_dashboard_analytics._group_shared_assignments",
            return_value=[],
        ),
        mock.patch("backend.business_time.business_now", return_value=datetime(2026, 11, 1, 18, 0)),
    ]
    for patch in patches:
        patch.start()
    try:
        report = monthly_task_performance(
            _Cur(),
            3,
            start_date=start,
            end_date=end,
            include_assignments=True,
            history_offset=0,
            history_limit=1,
        )
    finally:
        for patch in reversed(patches):
            patch.stop()

    assert report["span_days"] == 3
    assert report["truncated"] is False
    assert report["range_start"] == "2026-10-30"
    assert report["range_end"] == "2026-11-01"
    assert report["history_total"] == 2
    assert len(report["history"]) == 1
    assert report["history"][0]["business_date"] == "2026-11-01"
    assert report["history"][0]["verification_label"] == "Verified"
    assert report["history"][0]["employee_name"] == "Gabriela"


def test_pages_cover_every_record_once_past_the_screen_limits():
    start = date(2026, 10, 1)
    end = date(2026, 10, 30)
    calls = {"n": 0}

    def responsibilities(cursor, organization_id, business_date=None, **kwargs):
        calls["n"] += 1
        return [{"id": calls["n"], "user_id": 10, "role": "lint_cleaning"}]

    def activities_for_day(cursor, organization_id, business_date, **kwargs):
        day_number = business_date.day
        rows = []
        for seq in (1, 2) if day_number <= 15 else (1,):
            rows.append(
                {
                    "id": day_number * 10 + seq,
                    "user_id": 10 + seq,
                    "status": "approved" if seq == 1 else "pending_approval",
                    "role": "lint_cleaning",
                    "verification_required": 1,
                    "business_date": business_date,
                    "duration_seconds": 100,
                }
            )
        return rows

    def grouped(assignments, by_resp, **kwargs):
        day = kwargs["business_date"]
        return [
            {
                "assignment_key": f"solo:{day.isoformat()}",
                "role": "lint_cleaning",
                "role_label": "Dryer Lint Cleaning",
                "shared": False,
                "business_date": day.isoformat(),
                "status": "completed",
                "completion_status": "completed",
                "verification_status": "verified",
                "contributions": [
                    {
                        "participation_status": "finished",
                        "employee_name": "Francis",
                        "activity": {"duration_seconds": 100, "timestamp_kind": "work_interval"},
                    }
                ],
            }
        ]

    patches = [
        mock.patch("backend.cleaning_task_dashboard_analytics.business_today", return_value=end),
        mock.patch("backend.cleaning_task_dashboard_analytics.ensure_cleaning_task_activity_tables"),
        mock.patch("backend.cleaning_task_dashboard_analytics._role_catalog", return_value={}),
        mock.patch("backend.cleaning_task_dashboard_analytics._day_responsibilities", side_effect=responsibilities),
        mock.patch("backend.cleaning_task_dashboard_analytics._activities_for_day", side_effect=activities_for_day),
        mock.patch("backend.cleaning_task_dashboard_analytics._employee_names", return_value={11: "Francis", 12: "Gabriela"}),
        mock.patch(
            "backend.cleaning_task_dashboard_analytics._task_meta_for_role",
            return_value={"category_code": "intra_day"},
        ),
        mock.patch("backend.cleaning_task_dashboard_analytics.list_categories", return_value=[]),
        mock.patch("backend.cleaning_task_dashboard_analytics._group_shared_assignments", side_effect=grouped),
        mock.patch("backend.business_time.business_now", return_value=datetime(2026, 10, 30, 18, 0)),
    ]
    for patch in patches:
        patch.start()
    try:
        first = monthly_task_performance(
            _Cur(),
            3,
            start_date=start,
            end_date=end,
            include_assignments=True,
            assignment_offset=0,
            assignment_limit=25,
            history_offset=0,
            history_limit=40,
        )
        second_activities = monthly_task_performance(
            _Cur(),
            3,
            start_date=start,
            end_date=end,
            include_assignments=True,
            assignment_offset=25,
            assignment_limit=25,
            history_offset=40,
            history_limit=40,
        )
        printed = monthly_task_performance(
            _Cur(),
            3,
            start_date=start,
            end_date=end,
            include_assignments=True,
            assignment_limit=0,
        )
    finally:
        for patch in reversed(patches):
            patch.stop()

    assert first["span_days"] == 30
    assert first["assignment_total"] == 30
    assert len(first["assignments"]) == 25
    assert len(second_activities["assignments"]) == 5
    keys = [row["assignment_key"] for row in first["assignments"] + second_activities["assignments"]]
    assert len(keys) == len(set(keys)) == 30
    assert first["history_total"] == 45
    assert len(first["history"]) == 40
    assert len(second_activities["history"]) == 5
    history_ids = [row["id"] for row in first["history"] + second_activities["history"]]
    assert len(history_ids) == len(set(history_ids)) == 45
    assert {row["verification_label"] for row in first["history"]} >= {"Verified", "Pending verification"}
    assert len(printed["assignments"]) == 30
    assert printed["totals"]["assigned"] == 30
