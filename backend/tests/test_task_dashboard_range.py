"""Date ranges and management history stay complete and pageable."""

from datetime import date, datetime
from unittest import mock

import pytest

from backend.cleaning_task_dashboard_analytics import (
    TaskDashboardRangeError,
    history_verification_label,
    monthly_task_performance,
    participation_rollup,
    resolve_task_dashboard_range,
)


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
