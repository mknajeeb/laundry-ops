"""Item responsibility: defaults, date overrides, roster conflicts, snapshots."""

from datetime import date

import pytest

from backend.task_activity_item_responsibility import (
    incomplete_items_naming_users,
    normalize_responsibility,
    resolve_responsibility,
    split_items_for_employee,
    task_management_write_allowed,
)


def test_default_is_anyone_on_team():
    mode, ids = normalize_responsibility(None, None)
    assert mode == "team"
    assert ids == []
    mode, ids = normalize_responsibility("named", [4, 4, 9])
    assert mode == "named"
    assert ids == [4, 9]
    mode, ids = normalize_responsibility("named", [])
    assert mode == "team"


def test_date_override_does_not_change_master():
    master = {"id": 3, "task_code": "lint", "responsibility_mode": "team", "responsibility_user_ids": []}
    original = dict(master)
    resolved = resolve_responsibility(master, {"responsibility_mode": "named", "user_ids": [8]})
    assert master == original
    assert resolved["responsibility_user_ids"] == [8]
    assert resolve_responsibility(master, None)["responsibility_mode"] == "team"


def test_removing_employee_requires_resolution_for_open_items_only():
    items = [
        {"id": 1, "task_code": "open_item", "task_name": "Open", "responsibility_mode": "named", "responsibility_user_ids": [5]},
        {"id": 2, "task_code": "done_item", "task_name": "Done", "responsibility_mode": "named", "responsibility_user_ids": [5]},
    ]
    session = [
        {"task_code": "done_item", "status": "completed", "responsibility_snapshot_json": '{"responsibility_mode":"named","user_ids":[5]}', "completed_by_user_id": 5},
        {"task_code": "open_item", "status": "pending", "responsibility_snapshot_json": '{"responsibility_mode":"named","user_ids":[5]}'},
    ]
    conflicts = incomplete_items_naming_users(items, removed_user_ids=[5], session_items=session)
    assert [row["task_code"] for row in conflicts] == ["open_item"]
    resolved = incomplete_items_naming_users(
        items,
        removed_user_ids=[5],
        session_items=session,
        overrides_by_item_id={1: {"responsibility_mode": "team", "user_ids": []}},
    )
    assert resolved == []


def test_completed_snapshot_is_not_the_conflict_source():
    items = [{"id": 1, "task_code": "done_item", "responsibility_mode": "team", "responsibility_user_ids": []}]
    session = [
        {
            "task_code": "done_item",
            "status": "completed",
            "responsibility_snapshot_json": '{"responsibility_mode":"named","user_ids":[5]}',
            "completed_by_user_id": 9,
            "completed_at": "2026-11-01 18:00:00",
        }
    ]
    assert incomplete_items_naming_users(items, removed_user_ids=[5], session_items=session) == []


def test_split_keeps_each_item_once_and_counts_required():
    items = [
        {"task_code": "team", "required": True, "responsibility_mode": "team", "status": "completed"},
        {"task_code": "mine", "required": True, "responsibility_mode": "named", "responsibility_user_ids": [2], "status": "pending"},
        {"task_code": "other", "required": True, "responsibility_mode": "named", "responsibility_user_ids": [3], "status": "pending"},
    ]
    split = split_items_for_employee(items, 2)
    assert [item["task_code"] for item in split["my_items"]] == ["team", "mine"]
    assert [item["task_code"] for item in split["other_items"]] == ["other"]
    assert split["required_done"] == 1
    assert split["required_total"] == 3


def test_rinse_viewer_cannot_write_task_management():
    assert task_management_write_allowed(["RINSE"]) is False
    assert task_management_write_allowed(["ADMIN"]) is True
    assert task_management_write_allowed(["OPS", "RINSE"]) is True


def test_date_override_refresh_skips_completed_rows(monkeypatch):
    from backend.task_activity_item_responsibility import ItemResponsibilityError, save_date_overrides

    monkeypatch.setattr(
        "backend.task_activity_item_responsibility.ensure_item_responsibility_schema",
        lambda cursor: None,
    )
    monkeypatch.setattr(
        "backend.task_activity_item_responsibility.table_exists",
        lambda cursor, table: True,
    )
    monkeypatch.setattr(
        "backend.task_activity_item_responsibility.table_has_column",
        lambda cursor, table, column: True,
    )
    captured = []

    class Recorder:
        def execute(self, sql, params=None):
            captured.append(" ".join(str(sql).split()))

        def fetchall(self):
            return []

        def fetchone(self):
            return None

    save_date_overrides(
        Recorder(),
        3,
        business_date=date(2026, 11, 1),
        items_by_code={"lint": {"id": 1, "task_code": "lint"}},
        overrides=[{"task_code": "lint", "responsibility_mode": "named", "user_ids": [4]}],
        eligible_user_ids=[4, 8],
    )
    updates = [sql for sql in captured if sql.lower().startswith("update")]
    assert len(updates) == 1
    assert "status<>'completed'" in updates[0]
    assert "responsibility_snapshot_json" in updates[0]

    with pytest.raises(ItemResponsibilityError):
        save_date_overrides(
            Recorder(),
            3,
            business_date=date(2026, 11, 2),
            items_by_code={"lint": {"id": 1, "task_code": "lint"}},
            overrides=[{"task_code": "lint", "responsibility_mode": "named", "user_ids": [9]}],
            eligible_user_ids=[4],
        )
    with pytest.raises(ItemResponsibilityError):
        save_date_overrides(
            Recorder(),
            3,
            business_date=date(2026, 11, 2),
            items_by_code={"lint": {"id": 1, "task_code": "lint"}},
            overrides=[{"task_code": "lint", "responsibility_mode": "named", "user_ids": []}],
            eligible_user_ids=[4],
        )


def test_business_date_is_sunday_start():
    from backend.task_activity_item_responsibility import business_date_for_week

    assert business_date_for_week(date(2026, 11, 1), 0) == date(2026, 11, 1)
    assert business_date_for_week(date(2026, 11, 1), 1) == date(2026, 11, 2)
