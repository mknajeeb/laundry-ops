"""Daily task pairings, shared moves, and active-assignment guards."""

from datetime import date
from unittest.mock import MagicMock, patch

from backend.planned_weekly_schedule_responsibilities import (
    assign_tasks_for_days,
    list_week_responsibilities,
    move_task_assignment,
    reorder_day_tasks,
    update_responsibility,
)
from backend.tests.test_planned_weekly_schedule import WEEK, _FakeCursor, _create, _patched


def _shifts(cursor):
    for user_id, day in ((10, 1), (20, 1), (10, 2), (20, 2)):
        _create(
            cursor,
            {
                "user_id": user_id,
                "day_of_week": day,
                "start_time": "09:00",
                "end_time": "17:00",
                "roles": ["fold"],
            },
        )


def test_shared_group_is_one_assignment_per_day_and_pairings_differ():
    cursor = _FakeCursor()
    conn = MagicMock()
    _shifts(cursor)
    p1, p2 = _patched()
    with p1, p2:
        monday, err = assign_tasks_for_days(
            conn,
            cursor,
            1,
            week_start=WEEK,
            data={
                "days_of_week": [1],
                "role": "lint_cleaning",
                "user_ids": [10, 20],
                "execution_mode": "shared",
                "timing_mode": "anytime",
            },
        )
        assert err is None
        assert len(monday["assignment_group_ids"]) == 1
        tuesday, err = assign_tasks_for_days(
            conn,
            cursor,
            1,
            week_start=WEEK,
            data={
                "days_of_week": [2],
                "role": "lint_cleaning",
                "user_ids": [10],
                "execution_mode": "individual",
                "timing_mode": "anytime",
            },
        )
        assert err is None
        rows = list_week_responsibilities(cursor, 1, week_start=WEEK)
    monday_rows = [row for row in rows if row["day_of_week"] == 1]
    tuesday_rows = [row for row in rows if row["day_of_week"] == 2]
    assert {row["user_id"] for row in monday_rows} == {10, 20}
    assert {row["execution_mode"] for row in monday_rows} == {"shared"}
    assert len({row["assignment_group_id"] for row in monday_rows}) == 1
    assert {row["user_id"] for row in tuesday_rows} == {10}
    assert monday_rows[0]["assignment_group_id"] != tuesday_rows[0]["assignment_group_id"]
    assert monday["assignment_group_ids"][0] != tuesday["assignment_group_ids"][0]


def test_moving_a_shared_assignment_keeps_both_employees():
    cursor = _FakeCursor()
    conn = MagicMock()
    _shifts(cursor)
    p1, p2 = _patched()
    with p1, p2:
        created, err = assign_tasks_for_days(
            conn,
            cursor,
            1,
            week_start=WEEK,
            data={"days_of_week": [1], "role": "lint_cleaning", "user_ids": [10, 20], "execution_mode": "shared"},
        )
        assert err is None
        moved, err = move_task_assignment(conn, cursor, 1, created["items"][0]["id"], {"day_of_week": 2, "user_id": 10})
        assert err is None, err
        rows = [row for row in list_week_responsibilities(cursor, 1, week_start=WEEK) if row["role"] == "lint_cleaning"]
    assert {row["day_of_week"] for row in rows} == {2}
    assert {row["user_id"] for row in rows} == {10, 20}
    assert len({row["assignment_group_id"] for row in rows}) == 1
    assert moved["user_ids"] == [10, 20] or set(moved["user_ids"]) == {10, 20}


def test_duplicate_task_on_the_same_day_is_rejected():
    cursor = _FakeCursor()
    conn = MagicMock()
    _shifts(cursor)
    p1, p2 = _patched()
    with p1, p2:
        _, err = assign_tasks_for_days(
            conn, cursor, 1, week_start=WEEK, data={"days_of_week": [1], "role": "lint_cleaning", "user_ids": [10]}
        )
        assert err is None
        _, dup = assign_tasks_for_days(
            conn, cursor, 1, week_start=WEEK, data={"days_of_week": [1], "role": "lint_cleaning", "user_ids": [10]}
        )
    assert dup and "already has" in dup


def test_started_assignment_requires_an_audited_correction():
    cursor = _FakeCursor()
    conn = MagicMock()
    _shifts(cursor)
    p1, p2 = _patched()
    with p1, p2:
        created, err = assign_tasks_for_days(
            conn, cursor, 1, week_start=WEEK, data={"days_of_week": [1], "role": "lint_cleaning", "user_ids": [10]}
        )
        assert err is None
        responsibility_id = created["items"][0]["id"]
        with patch(
            "backend.planned_weekly_schedule_responsibilities._activity_lock_ids",
            return_value={responsibility_id},
        ):
            blocked, block_err = move_task_assignment(
                conn, cursor, 1, responsibility_id, {"day_of_week": 2, "user_id": 10}
            )
            assert blocked is None and "already started" in block_err
            recorded = []
            with patch(
                "backend.planned_weekly_schedule_responsibilities._record_assignment_correction",
                side_effect=lambda *args, **kwargs: recorded.append(kwargs),
            ):
                moved, move_err = move_task_assignment(
                    conn,
                    cursor,
                    1,
                    responsibility_id,
                    {"day_of_week": 2, "user_id": 10, "confirm_active_change": True, "correction_reason": "Coverage change"},
                    actor_user_id=15,
                )
        rows = list_week_responsibilities(cursor, 1, week_start=WEEK)
    assert move_err is None and moved["day_of_week"] == 2
    assert recorded and recorded[0]["reason"] == "Coverage change"
    assert rows[0]["day_of_week"] == 2


def test_reorder_persists_card_order_for_one_employee():
    cursor = MagicMock()
    rows = [
        {"id": 3, "user_id": 10, "day_of_week": 1},
        {"id": 4, "user_id": 10, "day_of_week": 1},
    ]
    with patch("backend.planned_weekly_schedule_responsibilities.list_week_responsibilities", return_value=rows), patch(
        "backend.planned_weekly_schedule_responsibilities.ensure_responsibilities_table"
    ):
        ordered, err = reorder_day_tasks(
            cursor, 1, week_start=date(2026, 6, 14), day_of_week=1, user_id=10, ordered_ids=[4, 3]
        )
    assert err is None and ordered == [4, 3]
    updates = [call.args[1][0] for call in cursor.execute.call_args_list if "display_order" in str(call.args[0])]
    assert updates == [0, 1]


def test_remarks_edit_does_not_require_a_correction():
    cursor = _FakeCursor()
    conn = MagicMock()
    _shifts(cursor)
    p1, p2 = _patched()
    with p1, p2:
        created, err = assign_tasks_for_days(
            conn, cursor, 1, week_start=WEEK, data={"days_of_week": [1], "role": "lint_cleaning", "user_ids": [10]}
        )
        assert err is None
        with patch(
            "backend.planned_weekly_schedule_responsibilities._activity_lock_ids",
            return_value={created["items"][0]["id"]},
        ):
            updated, edit_err = update_responsibility(
                conn, cursor, 1, created["items"][0]["id"], {"remarks": "Use the side door"}
            )
    assert edit_err is None and updated["remarks"] == "Use the side door"
