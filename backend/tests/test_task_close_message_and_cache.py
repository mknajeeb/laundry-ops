"""Closing-day copy stays on End of Day work, and catalog edits drop the read cache."""

from datetime import date, datetime
from unittest import mock

from backend.cleaning_task_activity import list_supervisor_queue
from backend.task_catalog import clear_task_read_cache


def test_clear_task_read_cache_drops_definition_and_meta():
    class Cursor:
        pass

    cursor = Cursor()
    cursor._vw_task_def_list = {3: [{"name": "Old dryer"}]}
    cursor._vw_task_def_cache = {(3, "agroup_dryer"): {"name": "Old dryer"}}
    cursor._vw_task_meta = {(3, "agroup_dryer"): {"name": "Old dryer"}}
    cursor._vw_activity_group = {(3, "dryer"): {"name": "Old dryer"}}
    clear_task_read_cache(cursor)
    assert not hasattr(cursor, "_vw_task_def_list")
    assert not hasattr(cursor, "_vw_task_def_cache")
    assert not hasattr(cursor, "_vw_task_meta")
    assert not hasattr(cursor, "_vw_activity_group")


def test_blocking_close_lists_end_of_day_only():
    day = date(2026, 11, 4)
    assignments = [
        {
            "id": 8,
            "user_id": 2,
            "role": "agroup_floor_washer",
            "assignment_group_id": "floor",
            "week_start": "2026-11-01",
            "day_of_week": 3,
            "timing_mode": "anytime",
            "user_ids": [2],
        },
        {
            "id": 9,
            "user_id": 4,
            "role": "agroup_end_of_day",
            "assignment_group_id": "close",
            "week_start": "2026-11-01",
            "day_of_week": 3,
            "timing_mode": "anytime",
            "user_ids": [4],
        },
    ]

    def meta(_cursor, _org, role):
        code = "end_of_day" if "end_of_day" in str(role) else "intra_day"
        return {"category_code": code, "name": role}

    with mock.patch(
        "backend.cleaning_task_activity.business_today", return_value=day
    ), mock.patch(
        "backend.cleaning_task_activity.business_now", return_value=datetime(2026, 11, 4, 13, 0)
    ), mock.patch(
        "backend.cleaning_task_activity._role_catalog", return_value={}
    ), mock.patch(
        "backend.cleaning_task_activity._day_responsibilities", return_value=assignments
    ), mock.patch(
        "backend.cleaning_task_activity._activities_for_day", return_value=[]
    ), mock.patch(
        "backend.cleaning_task_activity._employee_names", return_value={2: "Alex", 4: "Francis"}
    ), mock.patch(
        "backend.cleaning_task_activity._day_shifts_for_user", return_value=[]
    ), mock.patch(
        "backend.cleaning_task_activity._task_meta_for_role", side_effect=meta
    ), mock.patch(
        "backend.cleaning_task_activity._activity_group_item_templates", return_value=[]
    ), mock.patch(
        "backend.cleaning_task_activity._with_shared_checklists", return_value=assignments
    ):
        out = list_supervisor_queue(object(), 3, business_date=day)

    close_roles = {row["role"] for row in out["shift_end"]["end_of_day_close"]}
    blocking_roles = {row["role"] for row in out["shift_end"]["blocking_close"]}
    assert close_roles == {"agroup_end_of_day"}
    assert "agroup_floor_washer" in blocking_roles
    assert "agroup_end_of_day" in blocking_roles
    assert any(row["role"] == "agroup_floor_washer" for row in out["not_started"])
