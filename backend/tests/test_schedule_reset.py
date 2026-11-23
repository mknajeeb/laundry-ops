"""VeeWash schedule reset: automatic copy stops at 23 Nov 2026. Tasks stay put."""

from __future__ import annotations

import inspect
from datetime import date, time
from unittest.mock import MagicMock, patch

from backend.operations_planner_v2 import _pattern_covers, _pattern_is_open, cell_shifts
from backend.planned_weekly_schedule import (
    build_week_payload,
    carry_forward_week_schedule,
    clear_week_schedule,
    ensure_week_schedule_carried_forward,
)
from backend.schedule_reset import pattern_end_before_reset, week_reaches_reset
from backend.tests.test_planned_weekly_schedule import _FakeCursor, _mock_workers

BOUNDARY = date(2026, 11, 23)
VEEWASH = 3
WASHPRO = 1


def _bound(cursor, organization_id=VEEWASH):
    cursor.org_state[organization_id] = {
        "organization_id": organization_id,
        "schedule_reset_on": BOUNDARY,
    }


def _shift(organization_id, week_start, day_of_week, user_id=10):
    return {
        "id": 1,
        "organization_id": organization_id,
        "week_start": week_start,
        "user_id": user_id,
        "day_of_week": day_of_week,
        "role": "sort",
        "start_time": time(5, 0),
        "end_time": time(13, 0),
        "break_minutes": 30,
    }


def _task(organization_id, week_start, day_of_week, task_id=290):
    return {
        "id": task_id,
        "organization_id": organization_id,
        "week_start": week_start,
        "user_id": 10,
        "day_of_week": day_of_week,
        "role": "agroup_washer_and_floor_cleaning",
        "remarks": "keep",
        "assignment_group_id": "group-1",
        "timing_mode": "specific_time",
        "start_time": time(9, 0),
        "execution_mode": "shared",
    }


def _open(cursor, organization_id, week_start):
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()
    ), patch(
        "backend.planned_weekly_schedule.schedulable_worker_user_ids", return_value={10}
    ):
        return ensure_week_schedule_carried_forward(
            MagicMock(), cursor, organization_id, week_start=week_start
        )


def test_week_reaching_november_23_is_inside_the_boundary():
    assert week_reaches_reset(date(2026, 11, 15), BOUNDARY) is False
    assert week_reaches_reset(date(2026, 11, 22), BOUNDARY) is True
    assert week_reaches_reset(date(2026, 11, 23), BOUNDARY) is True
    assert week_reaches_reset(date(2026, 11, 29), BOUNDARY) is True


def test_opening_an_empty_future_week_does_not_recreate_shifts_or_tasks():
    cursor = _FakeCursor()
    _bound(cursor)
    cursor.rows = [_shift(VEEWASH, date(2026, 11, 22), 0)]
    cursor.responsibilities = [_task(VEEWASH, date(2026, 11, 22), 1)]
    before = [dict(row) for row in cursor.responsibilities]

    assert _open(cursor, VEEWASH, date(2026, 11, 29)) is None
    assert [row for row in cursor.rows if row["week_start"] == date(2026, 11, 29)] == []
    assert cursor.responsibilities == before


def test_a_week_with_tasks_and_no_shifts_stays_empty_of_shifts():
    cursor = _FakeCursor()
    _bound(cursor)
    cursor.rows = [_shift(VEEWASH, date(2026, 11, 22), 0)]
    task = _task(VEEWASH, date(2026, 12, 6), 0, task_id=11)
    cursor.responsibilities = [task]

    assert _open(cursor, VEEWASH, date(2026, 12, 6)) is None
    assert [row for row in cursor.rows if row["week_start"] == date(2026, 12, 6)] == []
    assert cursor.responsibilities == [task]


def test_historical_week_before_the_boundary_still_carries_forward():
    cursor = _FakeCursor()
    _bound(cursor)
    cursor.rows = [_shift(VEEWASH, date(2026, 11, 8), 1)]

    carried = _open(cursor, VEEWASH, date(2026, 11, 15))
    assert carried is not None
    assert carried["entries_copied"] == 1
    assert [row["week_start"] for row in cursor.rows if row["week_start"] == date(2026, 11, 15)] == [date(2026, 11, 15)]


def test_washpro_future_week_still_carries_forward():
    cursor = _FakeCursor()
    _bound(cursor, VEEWASH)
    cursor.rows = [_shift(WASHPRO, date(2026, 11, 22), 1)]

    carried = _open(cursor, WASHPRO, date(2026, 11, 29))
    assert carried is not None
    assert carried["entries_copied"] == 1


def test_explicit_copy_into_a_reset_week_copies_shifts_and_not_tasks():
    cursor = _FakeCursor()
    _bound(cursor)
    cursor.rows = [_shift(VEEWASH, date(2026, 11, 22), 1)]
    original = _task(VEEWASH, date(2026, 11, 22), 1)
    cursor.responsibilities = [original]
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()
    ), patch(
        "backend.planned_weekly_schedule.schedulable_worker_user_ids", return_value={10}
    ):
        result = carry_forward_week_schedule(
            MagicMock(),
            cursor,
            VEEWASH,
            target_week_start=date(2026, 11, 29),
            source_week_start=date(2026, 11, 22),
        )
    assert result["entries_copied"] == 1
    assert result["responsibilities_copied"] == 0
    assert cursor.responsibilities == [original]
    assert len([row for row in cursor.rows if row["week_start"] == date(2026, 11, 29)]) == 1


def test_clearing_a_reset_week_does_not_delete_tasks():
    cursor = _FakeCursor()
    _bound(cursor)
    task = _task(VEEWASH, date(2026, 11, 29), 0, task_id=15)
    cursor.responsibilities = [task]
    cursor.rows = [_shift(VEEWASH, date(2026, 11, 29), 1)]
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True):
        cleared = clear_week_schedule(cursor, VEEWASH, week_start=date(2026, 11, 29))
    assert cleared["responsibilities_deleted"] == 0
    assert cursor.responsibilities == [task]


def test_historical_clear_still_removes_tasks():
    cursor = _FakeCursor()
    _bound(cursor)
    cursor.responsibilities = [_task(VEEWASH, date(2026, 11, 15), 1, task_id=4)]
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True):
        cleared = clear_week_schedule(cursor, VEEWASH, week_start=date(2026, 11, 15))
    assert cleared["responsibilities_deleted"] == 1
    assert cursor.responsibilities == []


def test_pattern_end_cannot_regenerate_november_23_either_way():
    """Equal start and end is exclusive in code and inclusive to a later reader. Do not store it."""
    reset_on = BOUNDARY
    end = pattern_end_before_reset(reset_on)
    assert end == date(2026, 11, 22)
    closed = {
        "id": 1,
        "user_id": 38,
        "day_of_week": 1,
        "effective_from": date(2026, 11, 23),
        "effective_until": end,
        "shift": {"start_time": "05:00", "end_time": "13:00"},
    }
    state = {"patterns": [closed], "exceptions": []}
    for monday in (date(2026, 11, 23), date(2026, 11, 30), date(2027, 3, 8)):
        assert cell_shifts(state, 38, 1, monday) == []
        assert _pattern_covers(closed, monday) is False
        assert not (closed["effective_from"] <= monday <= closed["effective_until"])
    assert _pattern_is_open(closed) is False
    ambiguous = {**closed, "effective_until": date(2026, 11, 23)}
    assert _pattern_covers(ambiguous, date(2026, 11, 23)) is False
    assert ambiguous["effective_from"] <= date(2026, 11, 23) <= ambiguous["effective_until"]


def test_earlier_pattern_stopped_before_the_reset_keeps_november_16():
    end = pattern_end_before_reset(BOUNDARY)
    older = {
        "user_id": 38,
        "day_of_week": 1,
        "effective_from": date(2026, 11, 16),
        "effective_until": end,
        "shift": {"start_time": "05:00", "end_time": "13:00"},
    }
    state = {"patterns": [older], "exceptions": []}
    assert len(cell_shifts(state, 38, 1, date(2026, 11, 16))) == 1
    assert cell_shifts(state, 38, 1, date(2026, 11, 23)) == []


def test_enabling_a_sunday_template_does_not_refill_reset_weeks():
    from backend.weekly_schedule_template import enable_template

    cursor = _FakeCursor()
    _bound(cursor)
    replaced: list[date] = []
    with patch(
        "backend.weekly_schedule_template.current_week_start", return_value=date(2026, 11, 15)
    ), patch(
        "backend.weekly_schedule_template._content_weeks_after",
        return_value=[date(2026, 11, 22), date(2026, 11, 29)],
    ), patch(
        "backend.weekly_schedule_template.build_week_copy",
        return_value={"entries": [{"user_id": 10}], "responsibilities": [{"id": 290}]},
    ), patch(
        "backend.weekly_schedule_template.week_copy_has_content", return_value=True
    ), patch(
        "backend.weekly_schedule_template._replace_week",
        side_effect=lambda _cursor, _org, week, _copy: replaced.append(week) or {"week_start": str(week)},
    ), patch("backend.weekly_schedule_template._save_template"):
        result, err = enable_template(
            MagicMock(), cursor, VEEWASH, source_week_start=date(2026, 11, 15), user_id=1
        )
    assert err is None
    assert result is not None
    assert replaced == []
    assert result["weeks"] == []


def test_open_paths_use_the_guard_and_the_planner_read_does_not_copy():
    from backend import team_status_routes
    from backend.operations_planner_v2_routes import register_operations_planner_v2_routes

    team_source = inspect.getsource(team_status_routes)
    assert "ensure_week_schedule_carried_forward" in team_source
    planner_source = inspect.getsource(register_operations_planner_v2_routes)
    assert "ensure_week_schedule_carried_forward" not in planner_source
    assert "ensure_week_schedule_carried_forward" not in inspect.getsource(build_week_payload)
