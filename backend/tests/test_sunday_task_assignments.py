"""Sunday (day_of_week 0) assignments stay visible and can be saved at a planned time.

November 1, 2026 is a Sunday and the US daylight-saving fallback. A stored day of 0
must not be treated as missing.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest import mock
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from backend.cleaning_task_activity import (
    _day_responsibilities,
    _dow_for_date,
    dashboard_summary,
    list_employee_day_tasks,
    normalize_week_start,
)
from backend.planned_weekly_schedule import create_entry
from backend.planned_weekly_schedule_responsibilities import _day_shifts, create_responsibility
from backend.planned_weekly_schedule_task_timing import evaluate_task_timing
from backend.rinse_folding_et import ET
from backend.tests.test_planned_weekly_schedule import _FakeCursor, _patched

SUNDAY = date(2026, 11, 1)
NAMES = {38: "Amna", 57: "Rocio", 56: "Gabriela", 36: "Yesenia"}
CATALOG = {
    "lint_cleaning": {"name": "Dryer Lint Cleaning", "uses_time_slots": False, "active": True},
    "agroup_floor_washer": {"name": "Floor & Washer", "uses_time_slots": False, "active": True},
}


class _Cur:
    def execute(self, *args, **kwargs):
        return None

    def fetchone(self):
        return None

    def fetchall(self):
        return []


def _member(rid, user_id, group_id, role, *, execution_mode, timing_mode, start_time, user_ids):
    return {
        "id": rid,
        "organization_id": 3,
        "week_start": "2026-11-01",
        "user_id": user_id,
        "user_ids": user_ids,
        "members": [{"id": rid, "user_id": uid} for uid in user_ids],
        "day_of_week": 0,
        "role": role,
        "remarks": None,
        "assignment_group_id": group_id,
        "timing_mode": timing_mode,
        "start_time": start_time,
        "execution_mode": execution_mode,
        "timing_label": "",
    }


def _november_first_rows():
    lint_ids = [38, 57]
    floor_ids = [56, 36]
    return [
        _member(188, 38, "lint-group", "lint_cleaning", execution_mode="individual", timing_mode="specific_time", start_time="09:00", user_ids=lint_ids),
        _member(187, 57, "lint-group", "lint_cleaning", execution_mode="individual", timing_mode="specific_time", start_time="09:00", user_ids=lint_ids),
        _member(185, 56, "floor-group", "agroup_floor_washer", execution_mode="shared", timing_mode="anytime", start_time=None, user_ids=floor_ids),
        _member(186, 36, "floor-group", "agroup_floor_washer", execution_mode="shared", timing_mode="anytime", start_time=None, user_ids=floor_ids),
        _member(199, 38, "monday-only", "lint_cleaning", execution_mode="individual", timing_mode="anytime", start_time=None, user_ids=[38]),
    ]


def test_november_first_2026_is_sunday_through_the_daylight_saving_fallback():
    assert SUNDAY.weekday() == 6
    assert _dow_for_date(SUNDAY) == 0
    assert normalize_week_start(SUNDAY) == SUNDAY
    first = datetime(2026, 11, 1, 1, 30, tzinfo=ET, fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=ET, fold=1)
    assert first.date() == second.date() == SUNDAY
    assert first.utcoffset() != second.utcoffset()
    assert datetime(2026, 11, 1, 5, 30, tzinfo=ZoneInfo("UTC")).astimezone(ET).date() == SUNDAY
    assert datetime(2026, 11, 1, 6, 30, tzinfo=ZoneInfo("UTC")).astimezone(ET).date() == SUNDAY


def test_sunday_responsibilities_are_not_dropped_as_missing():
    rows = _november_first_rows()
    rows[-1]["day_of_week"] = 1
    with mock.patch(
        "backend.cleaning_task_activity.ensure_responsibilities_table"
    ), mock.patch(
        "backend.cleaning_task_activity.list_week_responsibilities", return_value=rows
    ), mock.patch(
        "backend.cleaning_task_activity._role_catalog", return_value=CATALOG
    ):
        found = _day_responsibilities(_Cur(), 3, business_date=SUNDAY)
    assert [item["id"] for item in found] == [188, 187, 185, 186]


def _patches(rows):
    return (
        mock.patch("backend.cleaning_task_activity.business_today", return_value=SUNDAY),
        mock.patch("backend.cleaning_task_activity.business_now", return_value=datetime(2026, 11, 1, 8, 0)),
        mock.patch("backend.cleaning_task_activity.list_week_responsibilities", return_value=rows),
        mock.patch("backend.cleaning_task_activity._role_catalog", return_value=CATALOG),
        mock.patch("backend.cleaning_task_activity._activities_for_day", return_value=[]),
        mock.patch("backend.cleaning_task_activity._employee_names", return_value=NAMES),
        mock.patch("backend.cleaning_task_activity._day_shifts_for_user", return_value=[]),
        mock.patch("backend.cleaning_task_activity.ensure_cleaning_task_activity_tables"),
        mock.patch("backend.cleaning_task_activity.ensure_responsibilities_table"),
        mock.patch("backend.cleaning_task_activity.get_open_activity", return_value=None),
        mock.patch(
            "backend.cleaning_task_activity.list_categories",
            return_value=[{"code": "intra_day", "name": "Intra-Day"}],
        ),
        mock.patch("backend.cleaning_task_activity.seed_builtin_categories", return_value=[]),
        mock.patch("backend.cleaning_task_activity.get_task_definition", return_value=None),
    )


def test_dashboard_and_pin_show_sunday_assignments_before_anyone_starts():
    rows = _november_first_rows()
    rows[-1]["day_of_week"] = 1
    started = []
    for item in _patches(rows):
        started.append(item.start())
    try:
        out = dashboard_summary(_Cur(), 3, business_date=SUNDAY)
        metrics = out["metrics"]
        assert metrics["employees_assigned"] == 4
        assert metrics["employees_started"] == 0
        assert metrics["completed_activities"] == 0
        assert metrics["total_assigned"] == 2
        assert metrics["verified_activities"] == 0
        assert metrics["pending_verification"] == 0
        assert len(out["shared_assignments"]) == 2
        assert {row["status_label"] for row in out["shared_assignments"]} == {"Not Started"}
        assert all(row.get("checklist_complete") is None for row in out["shared_assignments"])
        assert all(not row.get("activity") for row in out["shared_assignments"])
        lint = next(row for row in out["shared_assignments"] if row["role"] == "lint_cleaning")
        floor = next(row for row in out["shared_assignments"] if row["role"] == "agroup_floor_washer")
        assert lint["timing_label"] == "9:00 AM"
        assert floor["timing_label"] == ""
        assert floor["execution_mode"] == "shared"
        assert len(lint["contributions"]) == 2
        assert len(floor["contributions"]) == 2
        assert {c["participation_status"] for c in lint["contributions"] + floor["contributions"]} == {"not_started"}

        pin = list_employee_day_tasks(_Cur(), 3, 38, business_date=SUNDAY)
        assert [task["role"] for task in pin["tasks"]] == ["lint_cleaning"]
        assert pin["tasks"][0]["status"] == "pending"
        assert pin["tasks"][0]["planned_start_time"] == "09:00"
        assert pin["tasks"][0]["timing_label"] == "9:00 AM"
        assert pin["tasks"][0]["activity"] is None
        assert pin["in_progress"] == [] and pin["completed"] == []
        partners = {person for person in pin["tasks"][0]["assigned_employees"]}
        assert partners == {"Amna", "Rocio"}
    finally:
        for item in reversed(started):
            item.stop()


def test_sunday_shifts_cover_a_planned_9am_start():
    cursor = _Cur()
    cursor.fetchall = lambda: [
        {"user_id": 38, "day_of_week": 0, "start_time": "05:00", "end_time": "13:00", "break_minutes": 30, "break_slots": None},
        {"user_id": 57, "day_of_week": 0, "start_time": "05:00", "end_time": "14:00", "break_minutes": 30, "break_slots": None},
        {"user_id": 38, "day_of_week": 1, "start_time": "05:00", "end_time": "13:00", "break_minutes": 0, "break_slots": None},
    ]
    shifts = _day_shifts(cursor, 3, SUNDAY, 0, [38, 57])
    assert len(shifts[38]) == 1 and shifts[38][0]["start_time"].startswith("05:00")
    assert len(shifts[57]) == 1
    errors, warnings = evaluate_task_timing(
        timing_mode="specific_time",
        start_time="09:00",
        members=[
            {"name": "Amna", "shifts": shifts[38]},
            {"name": "Rocio", "shifts": shifts[57]},
        ],
    )
    assert errors == [] and warnings == []
    anytime_errors, _ = evaluate_task_timing(
        timing_mode="anytime",
        start_time=None,
        members=[{"name": "Amna", "shifts": []}],
    )
    assert anytime_errors == []


def test_shared_sunday_assignment_saves_at_9am_and_anytime_still_saves():
    cursor = _FakeCursor()
    conn = MagicMock()
    p1, p2 = _patched()
    with p1, p2, patch("backend.planned_weekly_schedule._schedule_end_time_enabled", return_value=True):
        for user_id in (10, 20):
            entry, err = create_entry(
                conn,
                cursor,
                1,
                week_start=SUNDAY,
                data={
                    "user_id": user_id,
                    "day_of_week": 0,
                    "start_time": "05:00",
                    "end_time": "14:00",
                    "roles": ["fold"],
                },
            )
            assert err is None, err
            assert entry["day_of_week"] == 0
        saved, err = create_responsibility(
            conn,
            cursor,
            1,
            week_start=SUNDAY,
            data={
                "user_ids": [10, 20],
                "day_of_week": 0,
                "role": "floor_cleaning",
                "timing_mode": "specific_time",
                "start_time": "09:00",
                "execution_mode": "shared",
            },
        )
        assert err is None, err
        assert saved["timing_mode"] == "specific_time"
        assert saved["start_time"] == "09:00"
        assert saved["user_ids"] == [10, 20]
        assert saved["execution_mode"] == "shared"
        assert saved["day_of_week"] == 0

        anytime, err = create_responsibility(
            conn,
            cursor,
            1,
            week_start=SUNDAY,
            data={
                "user_ids": [10, 20],
                "day_of_week": 0,
                "role": "lint_cleaning",
                "timing_mode": "anytime",
                "execution_mode": "shared",
            },
        )
        assert err is None, err
        assert anytime["timing_mode"] == "anytime"
        assert anytime["start_time"] is None

        blocked, err = create_responsibility(
            conn,
            cursor,
            1,
            week_start=SUNDAY,
            data={
                "user_ids": [10, 20],
                "day_of_week": 0,
                "role": "washer_cleaning",
                "timing_mode": "specific_time",
                "start_time": "02:00",
                "execution_mode": "shared",
            },
        )
        assert blocked is None
        assert "not scheduled at 2:00 AM" in err
