"""Unit tests for Task Activity Groups (config + one shared timer)."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from backend.task_activity_groups import (
    ACTIVITY_GROUP_PREFIX,
    ActivityGroupError,
    is_activity_group_code,
    upsert_activity_group,
)
from backend.cleaning_task_group_execution import (
    KIND_GROUP,
    checkoff_group_item,
    complete_group_activity,
    ensure_group_activity_schema,
    start_group_activity,
)
from backend.cleaning_task_activity import CleaningTaskError, get_open_activity


class FakeCursor:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {
            "task_categories": [
                {"id": 1, "organization_id": 3, "code": "intra_day", "name": "Intra-Day", "display_order": 20, "active": 1},
            ],
            "weekly_schedule_roles": [
                {
                    "id": 10,
                    "organization_id": 3,
                    "code": "floor_cleaning",
                    "name": "Floor Brooming",
                    "uses_time_slots": 0,
                    "active": 1,
                    "task_category_code": "intra_day",
                    "completion_type": "simple",
                    "timer_enabled": 1,
                    "verification_required": 1,
                    "verification_method": "employee",
                    "verification_timing": "same_shift",
                    "display_order": 10,
                    "remarks_enabled": 1,
                },
                {
                    "id": 11,
                    "organization_id": 3,
                    "code": "lint_cleaning",
                    "name": "Dryer Lint Cleaning",
                    "uses_time_slots": 0,
                    "active": 1,
                    "task_category_code": "intra_day",
                    "completion_type": "simple",
                    "timer_enabled": 1,
                    "verification_required": 0,
                    "verification_method": "none",
                    "verification_timing": "same_shift",
                    "display_order": 20,
                    "remarks_enabled": 1,
                },
            ],
            "task_activity_groups": [],
            "task_activity_group_items": [],
            "cleaning_task_activities": [],
            "cleaning_task_activity_items": [],
            "cleaning_task_activity_events": [],
            "planned_weekly_schedule_responsibilities": [],
        }
        self._last = None
        self.lastrowid = 100
        self.rowcount = 0
        self._pending_insert_table = None

    def execute(self, sql, params=None):
        sql_n = " ".join(str(sql).split()).lower()
        params = list(params or [])
        if sql_n.startswith("create table") or sql_n.startswith("alter table"):
            self._last = None
            return
        if "from information_schema" in sql_n or "show tables" in sql_n:
            self._last = [{"c": 1}]
            return
        if "from task_categories" in sql_n and "select" in sql_n:
            self._last = list(self.tables["task_categories"])
            return
        if "from weekly_schedule_roles" in sql_n and "select" in sql_n:
            if "where organization_id" in sql_n and "and code" in sql_n:
                code = params[1] if len(params) > 1 else None
                self._last = [r for r in self.tables["weekly_schedule_roles"] if r["code"] == code][:1]
            else:
                self._last = list(self.tables["weekly_schedule_roles"])
            return
        if "insert into weekly_schedule_roles" in sql_n:
            self.lastrowid += 1
            row = {
                "id": self.lastrowid,
                "organization_id": params[0],
                "code": params[1],
                "name": params[2],
                "uses_time_slots": 0,
                "active": params[-1] if params else 1,
                "task_category_code": "intra_day",
                "completion_type": "simple",
                "timer_enabled": 1,
                "verification_required": 0,
                "verification_method": "none",
                "verification_timing": "same_shift",
                "display_order": 0,
                "remarks_enabled": 1,
            }
            # crude map for upsert values order varies — keep minimal
            if len(params) >= 2:
                row["code"] = params[1]
                row["name"] = params[2] if len(params) > 2 else params[1]
            self.tables["weekly_schedule_roles"] = [
                r for r in self.tables["weekly_schedule_roles"] if r["code"] != row["code"]
            ] + [row]
            self._last = None
            return
        if "update weekly_schedule_roles" in sql_n:
            self._last = None
            return
        if "insert into task_activity_groups" in sql_n:
            self.lastrowid += 1
            row = {
                "id": self.lastrowid,
                "organization_id": params[0],
                "code": params[1],
                "name": params[2],
                "category_code": params[3],
                "display_order": params[4],
                "active": params[5],
            }
            self.tables["task_activity_groups"].append(row)
            self._last = None
            return
        if "from task_activity_groups" in sql_n and "select" in sql_n:
            rows = list(self.tables["task_activity_groups"])
            if "and id=%s" in sql_n.replace(" ", ""):
                rows = [r for r in rows if r["id"] == params[1]]
            elif "and (code=%s or code=%s)" in sql_n.replace("  ", " "):
                rows = [r for r in rows if r["code"] in (params[1], params[2])]
            elif "and code=%s" in sql_n:
                rows = [r for r in rows if r["code"] == params[1]]
            self._last = rows
            return
        if "delete from task_activity_group_items" in sql_n:
            gid = params[1]
            self.tables["task_activity_group_items"] = [
                r for r in self.tables["task_activity_group_items"] if r["group_id"] != gid
            ]
            self._last = None
            return
        if "insert into task_activity_group_items" in sql_n:
            self.lastrowid += 1
            self.tables["task_activity_group_items"].append(
                {
                    "id": self.lastrowid,
                    "organization_id": params[0],
                    "group_id": params[1],
                    "task_code": params[2],
                    "display_order": params[3],
                    "required": params[4],
                }
            )
            self._last = None
            return
        if "from task_activity_group_items" in sql_n:
            oid, *gids = params
            self._last = [
                r
                for r in self.tables["task_activity_group_items"]
                if r["organization_id"] == oid and r["group_id"] in gids
            ]
            return
        self._last = []

    def fetchone(self):
        if not self._last:
            return None
        row = self._last[0]
        self._last = self._last[1:]
        return row

    def fetchall(self):
        rows = list(self._last or [])
        self._last = []
        return rows


def test_is_activity_group_code():
    assert is_activity_group_code("agroup_routine")
    assert not is_activity_group_code("floor_cleaning")
    assert not is_activity_group_code("custom_x")


def test_upsert_activity_group_creates_members(monkeypatch):
    cur = FakeCursor()

    monkeypatch.setattr(
        "backend.task_activity_groups.ensure_task_activity_group_tables", lambda c: None
    )
    monkeypatch.setattr(
        "backend.task_activity_groups.list_categories",
        lambda c, oid, include_inactive=True: cur.tables["task_categories"],
    )
    monkeypatch.setattr(
        "backend.task_activity_groups.list_task_definitions",
        lambda c, oid, include_inactive=True: [
            {
                "code": r["code"],
                "name": r["name"],
                "completion_type": r.get("completion_type"),
                "timer_enabled": bool(r.get("timer_enabled")),
                "verification_required": bool(r.get("verification_required")),
                "verification_method": r.get("verification_method"),
                "input_schema": [],
            }
            for r in cur.tables["weekly_schedule_roles"]
            if not str(r["code"]).startswith(ACTIVITY_GROUP_PREFIX)
        ],
    )
    monkeypatch.setattr(
        "backend.task_activity_groups._sync_schedule_role",
        lambda c, oid, group: None,
    )

    group = upsert_activity_group(
        cur,
        3,
        {
            "name": "Routine Cleaning",
            "category_code": "intra_day",
            "items": [
                {"task_code": "floor_cleaning", "required": True},
                {"task_code": "lint_cleaning", "required": True},
            ],
        },
    )
    assert group["name"] == "Routine Cleaning"
    assert group["role_code"].startswith(ACTIVITY_GROUP_PREFIX)
    assert len(group["items"]) == 2

    with pytest.raises(ActivityGroupError):
        upsert_activity_group(
            cur,
            3,
            {"name": "Bad", "category_code": "intra_day", "items": [{"task_code": "agroup_other"}]},
        )
