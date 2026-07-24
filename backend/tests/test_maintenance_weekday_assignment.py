"""Phase 5B — weekday assignment resolution and checklist access."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from backend.maintenance_task_list_constants import STATUS_COMPLETED
from backend.maintenance_task_list_module import (
    MaintenanceTaskListError,
    employee_assigned_for_date,
    get_or_create_task_list,
    get_weekday_assignee_id,
    is_list_read_only,
    list_weekday_assignments,
    save_task_item,
    save_weekday_assignments,
    submit_task_list,
    weekday_assignment_configured,
)
from backend.tests.test_maintenance_task_list import FakeCursor


def test_no_weekday_assignments_denies_all():
    cur = FakeCursor()
    cur.weekday_assignments = []
    with patch("backend.maintenance_task_list_module.table_exists", return_value=True):
        assert weekday_assignment_configured(cur, 3) is False
        assert get_weekday_assignee_id(cur, 3, date(2026, 7, 24)) is None
        assert employee_assigned_for_date(cur, 3, 10, date(2026, 7, 24)) is False


def test_weekday_assignment_resolution_and_empty_day():
    cur = FakeCursor()
    # Friday Jul 24 2026 is weekday() == 4
    with patch("backend.maintenance_task_list_module.table_exists", return_value=True), patch(
        "backend.maintenance_task_list_module._column_exists", return_value=True
    ), patch(
        "backend.maintenance_task_list_module._employee_display_name", return_value="Assigned"
    ):
        save_weekday_assignments(
            cur,
            3,
            [
                {"weekday": 4, "employee_id": 42},
                {"weekday": 5, "employee_id": None},
            ],
            actor_user_id=1,
        )
        assert weekday_assignment_configured(cur, 3) is True
        assert get_weekday_assignee_id(cur, 3, date(2026, 7, 24)) == 42
        assert employee_assigned_for_date(cur, 3, 42, date(2026, 7, 24)) is True
        assert employee_assigned_for_date(cur, 3, 99, date(2026, 7, 24)) is False
        # Saturday empty
        assert get_weekday_assignee_id(cur, 3, date(2026, 7, 25)) is None
        assert employee_assigned_for_date(cur, 3, 42, date(2026, 7, 25)) is False


def test_weekday_removed_clears_access():
    cur = FakeCursor()
    with patch("backend.maintenance_task_list_module.table_exists", return_value=True), patch(
        "backend.maintenance_task_list_module._column_exists", return_value=True
    ), patch(
        "backend.maintenance_task_list_module._employee_display_name", return_value="Assigned"
    ):
        save_weekday_assignments(
            cur, 3, [{"weekday": 4, "employee_id": 42}], actor_user_id=1
        )
        assert employee_assigned_for_date(cur, 3, 42, date(2026, 7, 24)) is True
        save_weekday_assignments(
            cur, 3, [{"weekday": 4, "employee_id": None}], actor_user_id=1
        )
        assert get_weekday_assignee_id(cur, 3, date(2026, 7, 24)) is None
        assert employee_assigned_for_date(cur, 3, 42, date(2026, 7, 24)) is False


def test_list_weekday_assignments_sunday_first():
    cur = FakeCursor()
    with patch("backend.maintenance_task_list_module.table_exists", return_value=True), patch(
        "backend.maintenance_task_list_module._column_exists", return_value=True
    ), patch(
        "backend.maintenance_task_list_module._employee_display_name", return_value="Emp"
    ):
        save_weekday_assignments(cur, 3, [{"weekday": 0, "employee_id": 7}], actor_user_id=1)
        rows = list_weekday_assignments(cur, 3)
    assert rows[0]["label"] == "Sunday"
    assert rows[1]["label"] == "Monday"
    assert rows[1]["employee_id"] == 7


def test_copy_monday_to_all_days_via_save():
    cur = FakeCursor()
    with patch("backend.maintenance_task_list_module.table_exists", return_value=True), patch(
        "backend.maintenance_task_list_module._column_exists", return_value=True
    ), patch(
        "backend.maintenance_task_list_module._employee_display_name", return_value="Emp"
    ):
        # Monday = 0
        rows = save_weekday_assignments(
            cur,
            3,
            [{"weekday": w, "employee_id": 7} for w in range(7)],
            actor_user_id=1,
        )
    assert all(r["employee_id"] == 7 for r in rows)
    assert len(rows) == 7


def test_unassigned_employee_cannot_create_list():
    cur = FakeCursor()
    save_weekday_assignments(cur, 3, [{"weekday": 4, "employee_id": 42}], actor_user_id=1)
    with patch("backend.maintenance_task_list_module.table_exists", return_value=True), patch(
        "backend.maintenance_task_list_module._column_exists", return_value=True
    ), patch(
        "backend.maintenance_task_list_module._employee_display_name", return_value="Test"
    ):
        with pytest.raises(MaintenanceTaskListError) as exc:
            get_or_create_task_list(cur, 3, 99, date(2026, 7, 24), actor_user_id=99)
        assert exc.value.status == 403


def test_no_assignments_cannot_create_list():
    cur = FakeCursor()
    with patch("backend.maintenance_task_list_module.table_exists", return_value=True), patch(
        "backend.maintenance_task_list_module._column_exists", return_value=True
    ), patch(
        "backend.maintenance_task_list_module._employee_display_name", return_value="Test"
    ):
        with pytest.raises(MaintenanceTaskListError) as exc:
            get_or_create_task_list(cur, 3, 10, date(2026, 7, 24), actor_user_id=10)
        assert exc.value.status == 403


def test_assigned_employee_creates_full_snapshot():
    cur = FakeCursor()
    save_weekday_assignments(cur, 3, [{"weekday": 4, "employee_id": 42}], actor_user_id=1)
    with patch("backend.maintenance_task_list_module.table_exists", return_value=True), patch(
        "backend.maintenance_task_list_module._column_exists", return_value=True
    ), patch(
        "backend.maintenance_task_list_module._employee_display_name", return_value="Jennifer"
    ), patch(
        "backend.maintenance_task_list_module._notify_checklist_submitted"
    ):
        payload = get_or_create_task_list(cur, 3, 42, date(2026, 7, 24), actor_user_id=42)
    assert payload["employee_id"] == 42
    assert payload["total_count"] > 0
    item = payload["items"][0]
    assert item.get("category_snapshot") == "Closing"
    assert item.get("task_name_snapshot")
    assert "task_description_snapshot" in item
    assert "is_required_snapshot" in item
    assert "display_order_snapshot" in item


def test_submitted_refresh_and_reopen_stay_immutable():
    cur = FakeCursor()
    save_weekday_assignments(cur, 3, [{"weekday": 4, "employee_id": 42}], actor_user_id=1)
    with patch("backend.maintenance_task_list_module.table_exists", return_value=True), patch(
        "backend.maintenance_task_list_module._column_exists", return_value=True
    ), patch(
        "backend.maintenance_task_list_module._employee_display_name", return_value="Jennifer"
    ), patch(
        "backend.maintenance_task_list_module._notify_checklist_submitted"
    ):
        payload = get_or_create_task_list(cur, 3, 42, date(2026, 7, 24), actor_user_id=42)
        for item in payload["items"]:
            save_task_item(cur, 3, payload["id"], item["id"], completed=True, actor_user_id=42)
        submitted = submit_task_list(cur, 3, payload["id"], 42)
        assert submitted["status"] == STATUS_COMPLETED
        assert is_list_read_only(submitted["status"]) is True

        refreshed = get_or_create_task_list(cur, 3, 42, date(2026, 7, 24), actor_user_id=42)
        assert refreshed["id"] == submitted["id"]
        assert refreshed["status"] == STATUS_COMPLETED
        assert refreshed["read_only"] is True

        with pytest.raises(MaintenanceTaskListError):
            save_task_item(
                cur, 3, refreshed["id"], refreshed["items"][0]["id"], completed=False, actor_user_id=42
            )
