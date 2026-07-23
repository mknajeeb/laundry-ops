"""Tests for Maintenance Task List domain logic."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from backend.maintenance_task_list_constants import (
    DEFAULT_TASK_DEFINITIONS,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_NOT_STARTED,
)
from backend.maintenance_task_list_module import (
    MaintenanceTaskListError,
    business_today_iso,
    definition_applies_on_date,
    format_task_date_display,
    get_or_create_task_list,
    reopen_task_list,
    reorder_definitions,
    save_task_item,
    submit_task_list,
    summarize_missing,
)


class FakeCursor:
    """Minimal in-memory cursor for maintenance task list flows."""

    def __init__(self):
        self.definitions = []
        self.lists = []
        self.items = []
        self.events = []
        self._next_def = 1
        self._next_list = 1
        self._next_item = 1
        self._next_event = 1
        self.lastrowid = None
        self._result = None
        self._results = []

    def execute(self, sql, params=None):
        sql_n = " ".join(str(sql).split())
        params = params or ()

        if "FROM information_schema" in sql_n or "information_schema.columns" in sql_n:
            self._result = {"c": 0}
            return

        if sql_n.startswith("CREATE TABLE"):
            self._result = None
            return

        if "FROM maintenance_task_definitions WHERE organization_id" in sql_n and "COUNT(*)" in sql_n:
            org = int(params[0])
            self._result = {"c": sum(1 for d in self.definitions if d["organization_id"] == org)}
            return

        if sql_n.startswith("INSERT INTO maintenance_task_definitions"):
            # Seed: org, key, name, desc, freq, is_required, require_note, order, now, created_by, updated_by
            # Create: org, key, name, desc, freq, days, is_required, require_note, order, is_active, now, created_by, updated_by
            if len(params) == 11:
                row = {
                    "id": self._next_def,
                    "organization_id": int(params[0]),
                    "task_key": params[1],
                    "name": params[2],
                    "description": params[3],
                    "frequency": params[4],
                    "days_of_week_json": None,
                    "is_required": params[5],
                    "require_note_if_incomplete": params[6],
                    "display_order": params[7],
                    "is_active": 1,
                    "created_at": params[8],
                    "created_by_user_id": params[9],
                    "updated_by_user_id": params[10],
                }
            else:
                row = {
                    "id": self._next_def,
                    "organization_id": int(params[0]),
                    "task_key": params[1],
                    "name": params[2],
                    "description": params[3],
                    "frequency": params[4],
                    "days_of_week_json": params[5],
                    "is_required": params[6],
                    "require_note_if_incomplete": params[7],
                    "display_order": params[8],
                    "is_active": params[9],
                    "created_at": params[10],
                    "created_by_user_id": params[11],
                    "updated_by_user_id": params[12],
                }
            self.definitions.append(row)
            self.lastrowid = row["id"]
            self._next_def += 1
            self._result = None
            return

        if "FROM maintenance_task_definitions" in sql_n and "WHERE id =" in sql_n:
            def_id, org = int(params[0]), int(params[1])
            self._result = next(
                (dict(d) for d in self.definitions if d["id"] == def_id and d["organization_id"] == org),
                None,
            )
            return

        if "FROM maintenance_task_definitions" in sql_n and "ORDER BY display_order" in sql_n:
            org = int(params[0])
            rows = [dict(d) for d in self.definitions if d["organization_id"] == org]
            if "is_active = 1" in sql_n:
                rows = [r for r in rows if r.get("is_active")]
            rows.sort(key=lambda r: (r.get("display_order") or 0, r["id"]))
            self._results = rows
            self._result = None
            return

        if sql_n.startswith("UPDATE maintenance_task_definitions") and "display_order" in sql_n and "WHERE id =" in sql_n:
            display_order, _updated, _actor, def_id, org = params
            for d in self.definitions:
                if d["id"] == int(def_id) and d["organization_id"] == int(org):
                    d["display_order"] = int(display_order)
            self._result = None
            return

        if sql_n.startswith("UPDATE maintenance_task_definitions"):
            # generic update by id
            # name, description, frequency, days, is_required, require_note, display_order, is_active, updated_at, actor, id, org
            if len(params) >= 12:
                (
                    name,
                    description,
                    frequency,
                    days,
                    is_required,
                    require_note,
                    display_order,
                    is_active,
                    _updated,
                    _actor,
                    def_id,
                    org,
                ) = params[:12]
                for d in self.definitions:
                    if d["id"] == int(def_id) and d["organization_id"] == int(org):
                        d.update(
                            {
                                "name": name,
                                "description": description,
                                "frequency": frequency,
                                "days_of_week_json": days,
                                "is_required": is_required,
                                "require_note_if_incomplete": require_note,
                                "display_order": display_order,
                                "is_active": is_active,
                            }
                        )
            self._result = None
            return

        if "FROM maintenance_task_lists" in sql_n and "employee_id" in sql_n and "task_date" in sql_n:
            org, emp, task_date = int(params[0]), int(params[1]), params[2]
            self._result = next(
                (
                    dict(r)
                    for r in self.lists
                    if r["organization_id"] == org
                    and r["employee_id"] == emp
                    and r["task_date"] == task_date
                ),
                None,
            )
            return

        if "FROM maintenance_task_lists" in sql_n and "WHERE id =" in sql_n:
            list_id, org = int(params[0]), int(params[1])
            self._result = next(
                (dict(r) for r in self.lists if r["id"] == list_id and r["organization_id"] == org),
                None,
            )
            return

        if sql_n.startswith("INSERT INTO maintenance_task_lists"):
            row = {
                "id": self._next_list,
                "organization_id": int(params[0]),
                "employee_id": int(params[1]),
                "task_date": params[2],
                "status": params[3],
                "notes": None,
                "created_at": params[4],
                "updated_at": params[5],
                "submitted_at": None,
                "submitted_by_user_id": None,
                "reopened_at": None,
                "reopened_by_user_id": None,
            }
            self.lists.append(row)
            self.lastrowid = row["id"]
            self._next_list += 1
            self._result = None
            return

        if sql_n.startswith("INSERT INTO maintenance_task_list_items"):
            row = {
                "id": self._next_item,
                "maintenance_task_list_id": int(params[0]),
                "maintenance_task_definition_id": params[1],
                "task_name_snapshot": params[2],
                "task_description_snapshot": params[3],
                "is_required_snapshot": params[4],
                "require_note_if_incomplete_snapshot": params[5],
                "completed": 0,
                "display_order_snapshot": params[6],
                "created_at": params[7],
                "completed_at": None,
                "completed_by_user_id": None,
                "note": None,
            }
            self.items.append(row)
            self.lastrowid = row["id"]
            self._next_item += 1
            self._result = None
            return

        if "FROM maintenance_task_list_items" in sql_n and "maintenance_task_list_id" in sql_n and "ORDER BY" in sql_n:
            list_id = int(params[0])
            rows = [dict(i) for i in self.items if i["maintenance_task_list_id"] == list_id]
            rows.sort(key=lambda r: (r.get("display_order_snapshot") or 0, r["id"]))
            self._results = rows
            self._result = None
            return

        if "FROM maintenance_task_list_items" in sql_n and "WHERE id =" in sql_n:
            item_id, list_id = int(params[0]), int(params[1])
            self._result = next(
                (
                    dict(i)
                    for i in self.items
                    if i["id"] == item_id and i["maintenance_task_list_id"] == list_id
                ),
                None,
            )
            return

        if sql_n.startswith("UPDATE maintenance_task_list_items"):
            completed, completed_at, completed_by, note, _updated, item_id = params
            for i in self.items:
                if i["id"] == int(item_id):
                    i.update(
                        {
                            "completed": completed,
                            "completed_at": completed_at,
                            "completed_by_user_id": completed_by,
                            "note": note,
                        }
                    )
            self._result = None
            return

        if sql_n.startswith("UPDATE maintenance_task_lists") and "status" in sql_n and "submitted_at" in sql_n and "reopened" not in sql_n.lower():
            # submit
            status, submitted_at, submitted_by, updated_at, list_id, org = params
            for r in self.lists:
                if r["id"] == int(list_id) and r["organization_id"] == int(org):
                    r.update(
                        {
                            "status": status,
                            "submitted_at": submitted_at,
                            "submitted_by_user_id": submitted_by,
                            "updated_at": updated_at,
                        }
                    )
            self._result = None
            return

        if sql_n.startswith("UPDATE maintenance_task_lists") and "reopened_at" in sql_n:
            status, reopened_at, reopened_by, updated_at, list_id, org = params
            for r in self.lists:
                if r["id"] == int(list_id) and r["organization_id"] == int(org):
                    r.update(
                        {
                            "status": status,
                            "reopened_at": reopened_at,
                            "reopened_by_user_id": reopened_by,
                            "submitted_at": None,
                            "submitted_by_user_id": None,
                            "updated_at": updated_at,
                        }
                    )
            self._result = None
            return

        if sql_n.startswith("UPDATE maintenance_task_lists") and "notes" in sql_n:
            notes, updated_at, list_id, org = params
            for r in self.lists:
                if r["id"] == int(list_id) and r["organization_id"] == int(org):
                    r["notes"] = notes
                    r["updated_at"] = updated_at
            self._result = None
            return

        if sql_n.startswith("UPDATE maintenance_task_lists") and "updated_at" in sql_n:
            updated_at, list_id = params
            for r in self.lists:
                if r["id"] == int(list_id):
                    r["updated_at"] = updated_at
            self._result = None
            return

        if sql_n.startswith("INSERT INTO maintenance_task_list_events"):
            self.events.append({"id": self._next_event, "action": params[3], "params": params})
            self._next_event += 1
            self._result = None
            return

        if "FROM maintenance_task_list_events" in sql_n:
            list_id = int(params[0])
            self._results = [e for e in self.events if e.get("params") and e["params"][1] == list_id]
            self._result = None
            return

        if "FROM users u" in sql_n:
            self._result = {"name": "Jennifer"}
            return

        # fallback no-op
        self._result = None
        self._results = []

    def fetchone(self):
        return self._result

    def fetchall(self):
        return list(self._results)


class TestMaintenanceTaskListModule(unittest.TestCase):
    def test_default_definitions_cover_required_tasks(self):
        names = [d["name"] for d in DEFAULT_TASK_DEFINITIONS]
        self.assertIn("Empty dehumidifier buckets", names)
        self.assertIn("Empty A/C water bucket", names)
        self.assertIn("Cash up register", names)
        self.assertEqual(len(DEFAULT_TASK_DEFINITIONS), 8)

    def test_definition_applies_weekly_days(self):
        defn = {"is_active": True, "frequency": "weekly", "days_of_week_json": [0, 2, 4]}
        # 2026-07-23 is Thursday = weekday 3
        self.assertFalse(definition_applies_on_date(defn, date(2026, 7, 23)))
        # Monday
        self.assertTrue(definition_applies_on_date(defn, date(2026, 7, 20)))

    def test_inactive_definition_does_not_apply(self):
        defn = {"is_active": False, "frequency": "daily"}
        self.assertFalse(definition_applies_on_date(defn, date(2026, 7, 23)))

    def test_business_today_uses_eastern(self):
        with patch("backend.maintenance_task_list_module.business_today", return_value=date(2026, 7, 23)):
            self.assertEqual(business_today_iso(), "2026-07-23")
            self.assertEqual(format_task_date_display("2026-07-23"), "Thursday, July 23, 2026")

    @patch("backend.maintenance_task_list_module.table_exists", return_value=True)
    @patch("backend.maintenance_task_list_module._employee_display_name", return_value="Jennifer")
    def test_idempotent_list_creation_and_active_defs(self, _name, _exists):
        cur = FakeCursor()
        with patch("backend.maintenance_task_list_module.business_today", return_value=date(2026, 7, 23)):
            first = get_or_create_task_list(cur, 3, 10, "2026-07-23", actor_user_id=10)
            second = get_or_create_task_list(cur, 3, 10, "2026-07-23", actor_user_id=10)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["status"], STATUS_NOT_STARTED)
        self.assertEqual(len(cur.lists), 1)
        self.assertEqual(first["total_count"], 8)

    @patch("backend.maintenance_task_list_module.table_exists", return_value=True)
    @patch("backend.maintenance_task_list_module._employee_display_name", return_value="Jennifer")
    def test_inactive_excluded_from_new_list_history_preserved(self, _name, _exists):
        cur = FakeCursor()
        with patch("backend.maintenance_task_list_module.business_today", return_value=date(2026, 7, 23)):
            created = get_or_create_task_list(cur, 3, 10, "2026-07-23", actor_user_id=10)
        # Deactivate a definition after list creation
        cur.definitions[0]["is_active"] = 0
        historical_names = {i["task_name_snapshot"] for i in created["items"]}
        self.assertIn(cur.definitions[0]["name"], historical_names)
        # New employee list should not include inactive def
        with patch("backend.maintenance_task_list_module.business_today", return_value=date(2026, 7, 23)):
            other = get_or_create_task_list(cur, 3, 11, "2026-07-23", actor_user_id=11)
        other_names = {i["task_name_snapshot"] for i in other["items"]}
        self.assertNotIn(cur.definitions[0]["name"], other_names)
        # Original list items unchanged
        again = get_or_create_task_list(cur, 3, 10, "2026-07-23", actor_user_id=10)
        self.assertEqual(again["total_count"], 8)

    @patch("backend.maintenance_task_list_module.table_exists", return_value=True)
    @patch("backend.maintenance_task_list_module._employee_display_name", return_value="Jennifer")
    def test_completion_persists_and_submit_requires_all_checked(self, _name, _exists):
        cur = FakeCursor()
        with patch("backend.maintenance_task_list_module.business_today", return_value=date(2026, 7, 23)):
            payload = get_or_create_task_list(cur, 3, 10, "2026-07-23", actor_user_id=10)
        item_id = payload["items"][0]["id"]
        updated = save_task_item(
            cur, 3, payload["id"], item_id, completed=True, actor_user_id=10
        )
        self.assertTrue(updated["items"][0]["completed"])
        self.assertIsNotNone(updated["items"][0]["completed_at"])
        self.assertEqual(updated["status"], STATUS_IN_PROGRESS)

        with self.assertRaises(MaintenanceTaskListError) as ctx:
            submit_task_list(cur, 3, payload["id"], 10)
        self.assertIn("all checklist items", str(ctx.exception).lower())

        for item in updated["items"]:
            if item["id"] == item_id:
                continue
            save_task_item(
                cur, 3, payload["id"], item["id"], completed=True, actor_user_id=10
            )

        submitted = submit_task_list(cur, 3, payload["id"], 10)
        self.assertEqual(submitted["status"], STATUS_COMPLETED)
        self.assertTrue(submitted["read_only"])

        with self.assertRaises(MaintenanceTaskListError):
            save_task_item(cur, 3, payload["id"], item_id, completed=False, actor_user_id=10)

        with self.assertRaises(MaintenanceTaskListError) as reopen_ctx:
            reopen_task_list(cur, 3, payload["id"], 99, remarks="manager fix")
        self.assertIn("not available", str(reopen_ctx.exception).lower())

    @patch("backend.maintenance_task_list_module.table_exists", return_value=True)
    def test_reorder_definitions_preserved(self, _exists):
        cur = FakeCursor()
        # seed via ensure path
        with patch("backend.maintenance_task_list_module.business_today", return_value=date(2026, 7, 23)):
            get_or_create_task_list(cur, 3, 10, "2026-07-23", actor_user_id=10)
        ids = [d["id"] for d in cur.definitions]
        reversed_ids = list(reversed(ids))
        rows = reorder_definitions(cur, 3, reversed_ids, 1)
        self.assertEqual([r["id"] for r in rows], reversed_ids)

    def test_summarize_missing(self):
        items = [
            {"completed": True, "task_name_snapshot": "A"},
            {"completed": False, "task_name_snapshot": "Cash up register"},
        ]
        self.assertEqual(summarize_missing(items), "Cash up register")
        self.assertEqual(
            summarize_missing(
                [
                    {"completed": False, "task_name_snapshot": "A"},
                    {"completed": False, "task_name_snapshot": "B"},
                    {"completed": False, "task_name_snapshot": "C"},
                    {"completed": True, "task_name_snapshot": "D"},
                ]
            ),
            "3 tasks",
        )
        self.assertEqual(
            summarize_missing([{"completed": False, "task_name_snapshot": "A"}] * 4),
            "All tasks",
        )


class TestOrgIsolationGuards(unittest.TestCase):
    def test_list_lookup_requires_matching_org(self):
        cur = FakeCursor()
        with patch("backend.maintenance_task_list_module.table_exists", return_value=True), patch(
            "backend.maintenance_task_list_module._employee_display_name", return_value="Jennifer"
        ), patch("backend.maintenance_task_list_module.business_today", return_value=date(2026, 7, 23)):
            created = get_or_create_task_list(cur, 3, 10, "2026-07-23", actor_user_id=10)
        from backend.maintenance_task_list_module import get_task_list

        with self.assertRaises(MaintenanceTaskListError):
            get_task_list(cur, 99, created["id"])


if __name__ == "__main__":
    unittest.main()
