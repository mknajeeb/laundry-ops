"""Copy Shift copies scheduled rows only, inside the selected week."""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from backend.planned_weekly_schedule import create_entry, get_entry, update_entry
from backend.planned_weekly_schedule_copy import (
    apply_copy_shift,
    format_copy_message,
    plan_checklist_transfer,
    preview_copy_shift,
)
from backend.planned_weekly_schedule_responsibilities import (
    _update_member_row,
    assign_tasks_for_days,
    list_week_responsibilities,
)
from backend.tests.test_planned_weekly_schedule import WEEK, _FakeCursor, _mock_workers, _patched


def _workers():
    return _mock_workers() + [
        {"user_id": 30, "id": 3, "display_name": "Cara", "default_hourly_rate": 18, "active": True},
    ]


def _env():
    return (
        patch("backend.planned_weekly_schedule.table_exists", return_value=True),
        patch("backend.planned_weekly_schedule._load_workers", return_value=_workers()),
        patch("backend.payroll_schedule.worker_exists_in_schedule_grid", return_value=True),
    )


class _RecordingCursor(_FakeCursor):
    def __init__(self):
        super().__init__()
        self.sqls = []
        self.attendance = [{"id": 1, "clock_in": "08:00"}]
        self.payroll = [{"id": 9, "gross": 100}]

    def execute(self, sql, params=None):
        self.sqls.append(" ".join(str(sql).split()).lower())
        return super().execute(sql, params)


def _run(fn):
    cursor = _RecordingCursor()
    conn = MagicMock()
    patches = _env()
    for item in patches:
        item.start()
    try:
        return fn(conn, cursor), cursor
    finally:
        for item in patches:
            item.stop()


def _source(cursor, **extra):
    data = {
        "user_id": 10,
        "day_of_week": 1,
        "start_time": "08:00",
        "end_time": "16:00",
        "break_minutes": 45,
        "unscheduled_break_minutes": 15,
        "break_slots": [{"start_time": "12:00", "end_time": "12:30"}],
        "employer_affiliation": "rinse_exclusive",
        "assignments": [
            {"role": "wash", "full_shift": False, "start_time": "08:00", "end_time": "12:00", "remarks": "Early wash"},
            {"role": "fold", "full_shift": False, "start_time": "12:00", "end_time": "16:00", "remarks": "Fold after"},
        ],
    }
    data.update(extra)
    for code, name in (("wash", "Wash"), ("fold", "Fold")):
        cursor.roles.append(
            {
                "organization_id": 1,
                "code": code,
                "name": name,
                "role_group": "RINSE_WF",
                "display_order": 10,
                "active": 1,
                "uses_time_slots": 1,
                "remarks_enabled": 1,
            }
        )
    p1, p2 = _patched()
    with p1, p2, patch("backend.payroll_schedule.worker_exists_in_schedule_grid", return_value=True):
        entry, err = create_entry(MagicMock(), cursor, 1, week_start=WEEK, data=data)
    assert err is None, err
    return entry


def _tasks(cursor, **data):
    body = {
        "days_of_week": [1],
        "role": "lint_cleaning",
        "user_ids": [10],
        "timing_mode": "specific_time",
        "start_time": "10:00",
        "remarks": "Front machines",
    }
    body.update(data)
    p1, p2 = _patched()
    with p1, p2, patch("backend.planned_weekly_schedule._load_workers", return_value=_workers()):
        created, err = assign_tasks_for_days(MagicMock(), cursor, 1, week_start=WEEK, data=body)
    assert err is None, err
    return created


def test_copy_message_counts_created_replaced_and_skipped():
    assert format_copy_message(created=12, replaced=0, skipped=2) == "12 shifts copied, 2 skipped."
    assert format_copy_message(created=1, replaced=0, skipped=0) == "1 shift copied."
    assert format_copy_message(created=1, replaced=1, skipped=1) == "2 shifts copied (1 replaced), 1 skipped."


def test_copy_one_employee_one_day_keeps_breaks_roles_and_tasks():
    def run(conn, cursor):
        source = _source(cursor)
        _tasks(cursor)
        other_week = WEEK + timedelta(days=7)
        with patch("backend.payroll_schedule.worker_exists_in_schedule_grid", return_value=True):
            other, err = create_entry(
                conn,
                cursor,
                1,
                week_start=other_week,
                data={"user_id": 20, "day_of_week": 1, "role": "fold", "start_time": "09:00", "end_time": "12:00"},
            )
        assert err is None
        before = get_entry(cursor, 1, source["id"], conn=conn)
        result, err = apply_copy_shift(
            conn,
            cursor,
            1,
            source["id"],
            user_ids=[20],
            days_of_week=[3],
            conflict_mode="skip",
        )
        assert err is None, err
        assert result["message"] == "1 shift copied."
        copied = get_entry(cursor, 1, result["entry_ids"][0], conn=conn)
        assert copied["id"] != source["id"]
        assert copied["user_id"] == 20 and copied["day_of_week"] == 3
        assert copied["start_time"] == before["start_time"]
        assert copied["end_time"] == before["end_time"]
        assert copied["break_slots"] == before["break_slots"]
        assert copied["break_minutes"] == before["break_minutes"]
        assert copied["unscheduled_break_minutes"] == before["unscheduled_break_minutes"]
        assert copied["employer_affiliation"] == "rinse_exclusive"
        assert [(a["role"], a["start_time"], a["end_time"], a["remarks"]) for a in copied["assignments"]] == [
            (a["role"], a["start_time"], a["end_time"], a["remarks"]) for a in before["assignments"]
        ]
        rows = list_week_responsibilities(cursor, 1, week_start=WEEK)
        source_task = next(row for row in rows if row["user_id"] == 10)
        copied_task = next(row for row in rows if row["user_id"] == 20)
        assert copied_task["role"] == "lint_cleaning"
        assert copied_task["remarks"] == "Front machines"
        assert copied_task["timing_mode"] == "specific_time"
        assert copied_task["start_time"] == "10:00"
        assert copied_task["assignment_group_id"] != source_task["assignment_group_id"]
        assert get_entry(cursor, 1, source["id"], conn=conn)["start_time"] == before["start_time"]
        assert get_entry(cursor, 1, other["id"], conn=conn)["week_start"][:10] == other_week.isoformat()
        assert len([row for row in cursor.rows if row["week_start"] == other_week]) == 1
        changed, err = update_entry(
            conn,
            cursor,
            1,
            copied["id"],
            {"employer_affiliation": "washpro"},
        )
        assert err is None, err
        assert changed["employer_affiliation"] == "washpro"
        assert get_entry(cursor, 1, source["id"], conn=conn)["employer_affiliation"] == "rinse_exclusive"
        assert get_entry(cursor, 1, source["id"], conn=conn)["start_time"] == "08:00"
        _update_member_row(
            cursor,
            1,
            copied_task["id"],
            user_id=20,
            day_of_week=3,
            role="lint_cleaning",
            remarks="Changed copy",
            assignment_group_id=copied_task["assignment_group_id"],
            timing_mode="specific_time",
            start_time="10:00",
        )
        again = list_week_responsibilities(cursor, 1, week_start=WEEK)
        assert next(row for row in again if row["id"] == source_task["id"])["remarks"] == "Front machines"
        assert next(row for row in again if row["id"] == copied_task["id"])["remarks"] == "Changed copy"

    _run(run)


def test_copy_several_employees_and_days_skips_conflicts_until_replace_is_confirmed():
    def run(conn, cursor):
        source = _source(cursor)
        _tasks(cursor)
        with patch("backend.payroll_schedule.worker_exists_in_schedule_grid", return_value=True):
            create_entry(
                conn,
                cursor,
                1,
                week_start=WEEK,
                data={"user_id": 30, "day_of_week": 2, "role": "fold", "start_time": "07:00", "end_time": "11:00"},
            )
        blocked, err = apply_copy_shift(
            conn,
            cursor,
            1,
            source["id"],
            user_ids=[20, 30],
            days_of_week=[2, 4],
            conflict_mode="replace",
            confirm_replace=False,
        )
        assert blocked is None and "Confirm replacement" in err
        preview, err = preview_copy_shift(
            conn, cursor, 1, source["id"], user_ids=[20, 30], days_of_week=[2, 4], conflict_mode="skip"
        )
        assert err is None
        assert preview["counts"] == {"create": 3, "replace": 0, "skip": 1, "needs_resolution": 0}
        skipped = apply_copy_shift(
            conn, cursor, 1, source["id"], user_ids=[20, 30], days_of_week=[2, 4], conflict_mode="skip"
        )
        result, err = skipped
        assert err is None, err
        assert result["message"] == "3 shifts copied, 1 skipped."
        assert result["skipped_targets"][0]["employee_name"] == "Cara"
        assert result["skipped_targets"][0]["day_label"] == "Tue"
        kept = next(row for row in cursor.rows if row["user_id"] == 30 and int(row["day_of_week"]) == 2)
        assert str(kept["start_time"]).startswith("07:00")
        replaced, err = apply_copy_shift(
            conn,
            cursor,
            1,
            source["id"],
            user_ids=[30],
            days_of_week=[2],
            conflict_mode="replace",
            confirm_replace=True,
        )
        assert err is None, err
        assert replaced["replaced"] == 1
        tuesday = [row for row in cursor.rows if row["user_id"] == 30 and int(row["day_of_week"]) == 2]
        assert len(tuesday) == 1
        assert str(tuesday[0]["start_time"]).startswith("08:00")
        return result

    _run(run)


def test_shared_activity_copy_is_independent_and_checklist_names_the_destination():
    def checklist(cursor, organization_id, role, business_date):
        assert role == "agroup_closing"
        named = business_date == date(2026, 6, 15)
        return {
            "error": None,
            "open_session": False,
            "items": [
                {
                    "group_item_id": 7,
                    "task_code": "lock_doors",
                    "task_name": "Lock doors",
                    "responsibility_mode": "named" if named else "team",
                    "responsibility_user_ids": [10] if named else [],
                    "responsibility_label": "Alice" if named else "Anyone on Team",
                    "date_override": named,
                }
            ],
        }

    def run(conn, cursor):
        cursor.roles.append(
            {
                "organization_id": 1,
                "code": "agroup_closing",
                "name": "Closing",
                "role_group": None,
                "display_order": 500,
                "active": 1,
                "uses_time_slots": 0,
                "remarks_enabled": 1,
            }
        )
        source = _source(cursor)
        _tasks(cursor, role="agroup_closing", user_ids=[10, 20], execution_mode="shared", timing_mode="anytime", start_time=None, remarks="Lock up")
        with patch("backend.planned_weekly_schedule_copy._checklist_for_role_date", side_effect=checklist), patch(
            "backend.task_activity_item_responsibility.attach_checklist_responsibilities",
            side_effect=lambda _c, _o, rows: [dict(row) for row in rows],
        ):
            preview, err = preview_copy_shift(conn, cursor, 1, source["id"], user_ids=[30], days_of_week=[4])
            assert err is None, err
            assert any("own assignment" in note for target in preview["targets"] for note in target["notes"])
            result, err = apply_copy_shift(conn, cursor, 1, source["id"], user_ids=[30], days_of_week=[4])
        assert err is None, err
        rows = [row for row in list_week_responsibilities(cursor, 1, week_start=WEEK) if row["role"] == "agroup_closing"]
        original = [row for row in rows if row["day_of_week"] == 1]
        copied = [row for row in rows if row["user_id"] == 30]
        assert {row["user_id"] for row in original} == {10, 20}
        assert len({row["assignment_group_id"] for row in original}) == 1
        assert copied[0]["assignment_group_id"] not in {row["assignment_group_id"] for row in original}
        assert copied[0]["execution_mode"] == "individual"
        assert copied[0]["remarks"] == "Lock up"
        assert result["checklist_overrides"][0]["user_ids"] == [30]
        assert result["checklist_overrides"][0]["business_date"] == "2026-06-18"
        writes = [sql for sql in cursor.sqls if sql.startswith("insert") or sql.startswith("update") or sql.startswith("delete")]
        assert any("task_activity_item_date_overrides" in sql for sql in writes)
        assert not any("cleaning_task_" in sql or "payroll_" in sql or "clock" in sql for sql in writes)
        assert cursor.attendance == [{"id": 1, "clock_in": "08:00"}]
        assert cursor.payroll == [{"id": 9, "gross": 100}]
        return source

    _run(run)


def test_open_checklist_requires_a_resolution_and_same_day_keeps_the_source_name():
    def checklist(*_args, **_kwargs):
        return {
            "error": None,
            "open_session": True,
            "items": [
                {
                    "group_item_id": 7,
                    "task_code": "lock_doors",
                    "task_name": "Lock doors",
                    "responsibility_mode": "named",
                    "responsibility_user_ids": [10],
                    "date_override": True,
                }
            ],
        }

    def run(conn, cursor):
        cursor.roles.append(
            {
                "organization_id": 1,
                "code": "agroup_closing",
                "name": "Closing",
                "role_group": None,
                "display_order": 500,
                "active": 1,
                "uses_time_slots": 0,
                "remarks_enabled": 1,
            }
        )
        source = _source(cursor)
        _tasks(cursor, role="agroup_closing", timing_mode="anytime", start_time=None)
        with patch("backend.planned_weekly_schedule_copy._checklist_for_role_date", side_effect=checklist), patch(
            "backend.task_activity_item_responsibility.attach_checklist_responsibilities",
            side_effect=lambda _c, _o, rows: list(rows),
        ):
            preview, err = preview_copy_shift(conn, cursor, 1, source["id"], user_ids=[20], days_of_week=[1])
            assert err is None
            assert preview["counts"]["needs_resolution"] == 1
            refused, err = apply_copy_shift(conn, cursor, 1, source["id"], user_ids=[20], days_of_week=[1])
            assert refused is None and "Resolve flagged" in err
            result, err = apply_copy_shift(
                conn,
                cursor,
                1,
                source["id"],
                user_ids=[20],
                days_of_week=[1],
                resolutions=[{"user_id": 20, "day_of_week": 1, "action": "copy_schedule_only"}],
            )
        assert err is None, err
        assert result["checklist_overrides"][0]["user_ids"] == [10, 20]
        assert not any("cleaning_task_shared_session" in sql for sql in cursor.sqls)

    _run(run)


def test_checklist_plan_does_not_drop_an_ineligible_destination_name():
    planned = plan_checklist_transfer(
        source_user_id=10,
        dest_user_id=30,
        same_date=False,
        source_items=[
            {
                "group_item_id": 7,
                "task_code": "lock_doors",
                "task_name": "Lock doors",
                "responsibility_mode": "named",
                "responsibility_user_ids": [10],
            }
        ],
        dest_items=[
            {
                "group_item_id": 7,
                "task_code": "lock_doors",
                "task_name": "Lock doors",
                "responsibility_mode": "named",
                "responsibility_user_ids": [99],
                "date_override": True,
            }
        ],
        dest_roster=[30],
    )
    assert planned["overrides"] == []
    assert planned["issues"][0]["code"] == "checklist_ineligible"
    clear = plan_checklist_transfer(
        source_user_id=10,
        dest_user_id=30,
        same_date=True,
        source_items=[
            {
                "group_item_id": 7,
                "task_name": "Lock doors",
                "responsibility_mode": "named",
                "responsibility_user_ids": [10, 20],
            }
        ],
        dest_items=[],
        dest_roster=[10, 20, 30],
    )
    assert clear["issues"] == []
    assert clear["overrides"][0]["user_ids"] == [10, 20, 30]


def test_source_day_is_never_replaced():
    def run(conn, cursor):
        source = _source(cursor)
        result, err = apply_copy_shift(
            conn,
            cursor,
            1,
            source["id"],
            user_ids=[10],
            days_of_week=[1],
            conflict_mode="replace",
            confirm_replace=True,
        )
        assert err is None, err
        assert result["created"] == 0 and result["skipped"] == 1
        assert get_entry(cursor, 1, source["id"], conn=conn)["user_id"] == 10

    _run(run)
