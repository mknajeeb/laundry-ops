"""Shared Activity Groups: collaborative checklist + independent timers."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest import mock

import pytest

from backend.planned_weekly_schedule_responsibilities import (
    EXECUTION_INDIVIDUAL,
    EXECUTION_SHARED,
    normalize_execution_mode,
)
from backend.cleaning_task_shared_execution import is_shared_execution


def test_normalize_execution_mode_defaults_and_guards():
    assert normalize_execution_mode(None, member_count=3) == EXECUTION_INDIVIDUAL
    assert normalize_execution_mode("shared", member_count=1) == EXECUTION_INDIVIDUAL
    assert normalize_execution_mode("shared", member_count=2) == EXECUTION_SHARED
    assert normalize_execution_mode("SHARED", member_count=4) == EXECUTION_SHARED
    assert normalize_execution_mode("bogus", member_count=2) == EXECUTION_INDIVIDUAL


def test_is_shared_execution_requires_group_and_members():
    assert not is_shared_execution(
        {"execution_mode": "shared", "assignment_group_id": "abc", "user_ids": [1]}
    )
    assert not is_shared_execution(
        {"execution_mode": "individual", "assignment_group_id": "abc", "user_ids": [1, 2]}
    )
    assert is_shared_execution(
        {"execution_mode": "shared", "assignment_group_id": "abc", "user_ids": [1, 2]}
    )


class _Mem:
    def __init__(self):
        self.sessions = []
        self.items = []
        self.activities = []
        self.events = []
        self.lastrowid = 0
        self.rowcount = 0
        self._last = None

    def execute(self, sql, params=None):
        sql_n = " ".join(str(sql).split()).lower()
        params = list(params or [])
        self.rowcount = 0
        if sql_n.startswith("create table") or sql_n.startswith("alter table"):
            self._last = None
            return
        if "from information_schema" in sql_n or "show tables" in sql_n or "show columns" in sql_n:
            self._last = [{"c": 1, "Field": "shared_session_id"}]
            return
        if "insert into cleaning_task_shared_sessions" in sql_n:
            self.lastrowid += 1
            row = {
                "id": self.lastrowid,
                "organization_id": params[0],
                "assignment_group_id": params[1],
                "business_date": params[2],
                "role": params[3],
                "status": params[4],
                "checklist_completed_at": None,
            }
            self.sessions.append(row)
            self._last = None
            return
        if "insert into cleaning_task_shared_session_items" in sql_n:
            self.lastrowid += 1
            self.items.append(
                {
                    "id": self.lastrowid,
                    "organization_id": params[0],
                    "shared_session_id": params[1],
                    "task_code": params[2],
                    "display_order": params[3],
                    "required": params[4],
                    "status": params[5],
                    "completed_at": None,
                    "completed_by_user_id": None,
                    "completion_input_json": None,
                    "child_activity_id": None,
                }
            )
            self._last = None
            return
        if "from cleaning_task_shared_sessions" in sql_n and "assignment_group_id" in sql_n:
            gid, day = params[1], params[2]
            hits = [
                s
                for s in self.sessions
                if s["assignment_group_id"] == gid and s["business_date"] == day
            ]
            self._last = hits[:1]
            return
        if "from cleaning_task_shared_sessions" in sql_n and "and id=%s" in sql_n:
            sid = params[1]
            self._last = [s for s in self.sessions if s["id"] == sid][:1]
            return
        if "from cleaning_task_shared_session_items" in sql_n and "and task_code" in sql_n:
            sid, code = params[1], params[2]
            self._last = [
                i for i in self.items if i["shared_session_id"] == sid and i["task_code"] == code
            ][:1]
            return
        if "from cleaning_task_shared_session_items" in sql_n:
            sid = params[1]
            self._last = [i for i in self.items if i["shared_session_id"] == sid]
            return
        if "update cleaning_task_shared_session_items" in sql_n and "status=%s" in sql_n:
            # optimistic checkoff
            item_id, expect = params[4], params[5]
            for it in self.items:
                if it["id"] == item_id and it["status"] == expect:
                    it["status"] = params[0]
                    it["completed_at"] = params[1]
                    it["completed_by_user_id"] = params[2]
                    it["completion_input_json"] = params[3]
                    self.rowcount = 1
                    break
            self._last = None
            return
        if "update cleaning_task_shared_sessions" in sql_n:
            sid = params[2]
            for s in self.sessions:
                if s["id"] == sid and s["status"] == params[4]:
                    s["status"] = params[0]
                    s["checklist_completed_at"] = params[1]
                    self.rowcount = 1
            self._last = None
            return
        if "insert into cleaning_task_activity_events" in sql_n or "insert into cleaning_task_activities" in sql_n:
            self.lastrowid += 1
            self._last = None
            return
        if "update cleaning_task_shared_session_items set child_activity_id" in sql_n:
            self._last = None
            return
        self._last = []

    def fetchone(self):
        rows = self._last or []
        return rows[0] if rows else None

    def fetchall(self):
        return list(self._last or [])


def test_shared_checkoff_is_visible_and_blocks_duplicate():
    from backend.cleaning_task_shared_execution import (
        checkoff_shared_item,
        ensure_shared_session,
        list_shared_session_items,
    )
    from backend.cleaning_task_activity import CleaningTaskError

    mem = _Mem()
    cur = mem
    conn = SimpleNamespace()
    session = ensure_shared_session(
        cur,
        organization_id=3,
        assignment_group_id="g1",
        business_date=date(2026, 10, 27),
        role="agroup_routine",
        group_items=[
            {"task_code": "floor", "display_order": 0, "required": True},
            {"task_code": "lint", "display_order": 1, "required": True},
        ],
    )
    assert session["id"]
    assert len(list_shared_session_items(cur, 3, session["id"])) == 2

    parent = {
        "id": 50,
        "user_id": 23,
        "status": "in_progress",
        "shared_session_id": session["id"],
        "assignment_group_id": "g1",
        "responsibility_id": 1,
        "business_date": date(2026, 10, 27),
        "role": "agroup_routine",
        "timing_mode": "anytime",
        "planned_start_time": None,
        "shift_session_id": None,
    }

    with mock.patch(
        "backend.cleaning_task_shared_execution.get_activity", return_value=dict(parent)
    ), mock.patch(
        "backend.cleaning_task_shared_execution._task_meta_for_role",
        return_value={
            "completion_type": "simple",
            "input_schema": [],
            "verification_required": False,
            "verification_method": "none",
            "name": "Floor",
        },
    ), mock.patch(
        "backend.cleaning_task_shared_execution.validate_completion_input", return_value={}
    ), mock.patch(
        "backend.cleaning_task_shared_execution._record_event"
    ), mock.patch(
        "backend.cleaning_task_shared_execution.serialize_activity",
        return_value={**parent, "id": 50},
    ), mock.patch(
        "backend.cleaning_task_shared_execution._role_catalog", return_value={}
    ), mock.patch(
        "backend.cleaning_task_shared_execution.enrich_shared_group_activity",
        side_effect=lambda c, o, a: a,
    ), mock.patch(
        "backend.cleaning_task_shared_execution.maybe_complete_shared_checklist", return_value=False
    ):
        out = checkoff_shared_item(
            conn,
            cur,
            organization_id=3,
            user_id=23,
            activity_id=50,
            task_code="floor",
            completion_input={},
        )
        assert out["id"] == 50
        items = list_shared_session_items(cur, 3, session["id"])
        floor = next(i for i in items if i["task_code"] == "floor")
        assert floor["status"] == "completed"
        assert floor["completed_by_user_id"] == 23

        with pytest.raises(CleaningTaskError) as exc:
            checkoff_shared_item(
                conn,
                cur,
                organization_id=3,
                user_id=36,
                activity_id=50,  # ownership check uses parent.user_id
                task_code="floor",
                completion_input={},
            )
        # Wrong owner first — use B's activity
        parent_b = {**parent, "id": 51, "user_id": 36}
        with mock.patch(
            "backend.cleaning_task_shared_execution.get_activity", return_value=dict(parent_b)
        ):
            with pytest.raises(CleaningTaskError) as dup:
                checkoff_shared_item(
                    conn,
                    cur,
                    organization_id=3,
                    user_id=36,
                    activity_id=51,
                    task_code="floor",
                    completion_input={},
                )
            assert dup.value.status == 409


def test_rinse_strip_keeps_completed_by_without_durations():
    from backend.cleaning_task_activity import apply_rinse_task_dashboard_scope

    payload = {
        "metrics": {"total_assigned": 1, "time_spent_seconds": 120, "completion_rate": 50},
        "shared_assignments": [
            {
                "execution_mode": "shared",
                "shared_checklist_items": [
                    {
                        "task_code": "floor",
                        "status": "completed",
                        "completed_by_user_id": 23,
                        "completed_by_name": "Francis",
                        "duration_seconds": 99,
                    }
                ],
                "contributions": [
                    {"user_id": 23, "duration_seconds": 40, "group_duration_seconds": 40},
                    {"user_id": 36, "duration_seconds": 35, "group_duration_seconds": 35},
                ],
            }
        ],
        "durations": [{"seconds": 40}],
        "queue": {},
    }
    out = apply_rinse_task_dashboard_scope(payload)
    assert "time_spent_seconds" not in out["metrics"]
    assert out["hide_labor_metrics"] is True
    item = out["shared_assignments"][0]["shared_checklist_items"][0]
    assert item["completed_by_name"] == "Francis"
    assert "duration_seconds" not in item
    for c in out["shared_assignments"][0]["contributions"]:
        assert "duration_seconds" not in c
        assert "group_duration_seconds" not in c
