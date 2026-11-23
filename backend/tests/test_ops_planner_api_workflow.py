"""Authenticated planner workflow on the local MySQL at 127.0.0.1:3307.

This does not open a connection to Azure and it does not use organization 3.
"""

from __future__ import annotations

from datetime import date

import pytest

pytest.importorskip("mysql.connector")

from backend.scripts.ops_planner_isolated_db import build_app, connect, prepare

WEEK = "2027-01-04"
NEXT = "2027-01-11"
ORG = 1


def _available():
    try:
        conn = connect(database=None)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _available(), reason="isolated MySQL on port 3307 is not running")


def _clock(value) -> str:
    return str(value or "")[:5]


def _roles(entry):
    return entry.get("role_assignments") or entry.get("assignments") or []


def _week(client, monday=WEEK):
    response = client.get(f"/operations-planner/v2/week?week_start={monday}")
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _apply(client, body):
    response = client.post("/operations-planner/v2/apply", json=body)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _shift(user_id, day, start, end, roles, breaks=None):
    return {
        "op": "create",
        "user_id": user_id,
        "day_of_week": day,
        "shift": {
            "user_id": user_id,
            "day_of_week": day,
            "start_time": start,
            "end_time": end,
            "role": ",".join(item["role"] for item in roles),
            "role_assignments": roles,
            "break_slots": breaks or [],
            "break_minutes": 0,
        },
    }


def test_manager_workflow_against_the_isolated_api():
    import backend.db as backend_db
    import backend.operations_planner_v2_routes as routes

    original_db = backend_db.get_db
    original_routes = routes.get_db
    prepare()
    conn = connect()
    cursor = conn.cursor()
    for statement in (
        "DELETE FROM planned_weekly_schedule_entries WHERE organization_id=%s",
        "DELETE FROM planned_weekly_schedule_responsibilities WHERE organization_id=%s",
        "DELETE FROM cleaning_task_activities WHERE organization_id=%s",
        "DELETE FROM ops_planner_patterns WHERE organization_id=%s",
        "DELETE FROM ops_planner_weeks WHERE organization_id=%s",
    ):
        try:
            cursor.execute(statement, (ORG,))
        except Exception:
            conn.rollback()
    conn.commit()
    cursor.close()
    conn.close()

    app = build_app()
    try:
        client = app.test_client()
        health = client.get("/health")
        assert health.status_code == 200
        assert health.get_json()["database"] == "ops_planner_test"
        assert health.get_json()["port"] == 3307

        before = _week(client)
        assert before["entries"] == []
        token = before["planner"]["schedule_token"]

        created = _apply(client, {
            "action": "apply_shift_set",
            "scope": "this_week",
            "week_start": WEEK,
            "expected_schedule_token": token,
            "operations": [
                _shift(7, 1, "05:00", "13:30", [
                    {"role": "weigher", "start_time": "05:00", "end_time": "06:00"},
                    {"role": "sort", "start_time": "06:00", "end_time": "10:00"},
                ]),
            ],
        })
        assert created["created_ids"]

        loaded = _week(client)
        amina = next(row for row in loaded["entries"] if int(row["user_id"]) == 7)
        assert _clock(amina["start_time"]) == "05:00"
        assert _clock(amina["end_time"]) == "13:30"
        roles = _roles(amina)
        assert {item["role"] for item in roles} == {"weigher", "sort"}

        edited = _apply(client, {
            "action": "apply_shift_set",
            "scope": "this_week",
            "week_start": WEEK,
            "expected_schedule_token": loaded["planner"]["schedule_token"],
            "operations": [{
                "op": "update",
                "id": amina["id"],
                "user_id": 7,
                "day_of_week": 1,
                "shift": {
                    "user_id": 7,
                    "day_of_week": 1,
                    "start_time": "05:00",
                    "end_time": "13:30",
                    "role": "sort,weigher",
                    "role_assignments": [
                        {"role": "weigher", "start_time": "05:00", "end_time": "06:00"},
                        {"role": "sort", "start_time": "06:00", "end_time": "11:00"},
                    ],
                },
            }],
        })
        assert amina["id"] in edited["updated_ids"]
        reloaded = _week(client)
        amina = next(row for row in reloaded["entries"] if int(row["id"]) == int(amina["id"]))
        assert _clock(amina["end_time"]) == "13:30"
        sort = next(item for item in _roles(amina) if item["role"] == "sort")
        assert _clock(sort["end_time"]) == "11:00"

        with_break = _apply(client, {
            "action": "apply_shift_set",
            "scope": "this_week",
            "week_start": WEEK,
            "expected_schedule_token": reloaded["planner"]["schedule_token"],
            "operations": [{
                "op": "update",
                "id": amina["id"],
                "user_id": 7,
                "day_of_week": 1,
                "shift": {
                    "user_id": 7,
                    "day_of_week": 1,
                    "start_time": "05:00",
                    "end_time": "13:30",
                    "role": "sort,weigher",
                    "role_assignments": [
                        {"role": "weigher", "start_time": "05:00", "end_time": "06:00"},
                        {"role": "sort", "start_time": "06:00", "end_time": "11:00"},
                    ],
                    "break_slots": [{"start_time": "10:00", "end_time": "10:30"}],
                    "break_minutes": 30,
                },
            }],
        })
        assert amina["id"] in with_break["updated_ids"]
        broken = _week(client)
        amina = next(row for row in broken["entries"] if int(row["id"]) == int(amina["id"]))
        assert _clock(amina["end_time"]) == "13:30"
        assert any(_clock(slot.get("start_time")) == "10:00" for slot in (amina.get("break_slots") or []))

        cleared = _apply(client, {
            "action": "apply_shift_set",
            "scope": "this_week",
            "week_start": WEEK,
            "expected_schedule_token": broken["planner"]["schedule_token"],
            "operations": [{
                "op": "update",
                "id": amina["id"],
                "user_id": 7,
                "day_of_week": 1,
                "shift": {
                    "user_id": 7,
                    "day_of_week": 1,
                    "start_time": "05:00",
                    "end_time": "13:30",
                    "role": "sort,weigher",
                    "role_assignments": [
                        {"role": "weigher", "start_time": "05:00", "end_time": "06:00"},
                        {"role": "sort", "start_time": "06:00", "end_time": "11:00"},
                    ],
                    "break_slots": [],
                    "break_minutes": 0,
                },
            }],
        })
        assert amina["id"] in cleared["updated_ids"]

        copied = _week(client)
        _apply(client, {
            "action": "apply_shift_set",
            "scope": "this_week",
            "week_start": WEEK,
            "expected_schedule_token": copied["planner"]["schedule_token"],
            "operations": [
                _shift(7, 2, "05:00", "13:30", [
                    {"role": "weigher", "start_time": "05:00", "end_time": "06:00"},
                    {"role": "sort", "start_time": "06:00", "end_time": "11:00"},
                ]),
            ],
        })
        both = _week(client)
        assert sorted(int(row["day_of_week"]) for row in both["entries"] if int(row["user_id"]) == 7) == [1, 2]

        future = _week(client, NEXT)
        assert future["entries"] == []

        from backend.planned_weekly_schedule import ensure_week_schedule_carried_forward
        from backend.schedule_reset import ensure_reset_column
        from backend.weekly_schedule_template import ensure_org_state_table

        guard = connect()
        guard_cursor = guard.cursor()
        ensure_org_state_table(guard_cursor)
        ensure_reset_column(guard_cursor)
        guard_cursor.execute(
            """
            INSERT INTO weekly_schedule_org_state (organization_id, template_enabled, schedule_reset_on)
            VALUES (%s, 0, %s)
            ON DUPLICATE KEY UPDATE schedule_reset_on=VALUES(schedule_reset_on), template_enabled=0
            """,
            (ORG, NEXT),
        )
        guard.commit()
        opened = ensure_week_schedule_carried_forward(guard, guard.cursor(dictionary=True), ORG, week_start=date.fromisoformat(NEXT))
        assert opened is None
        guard_cursor.execute(
            """
            SELECT COUNT(*) FROM planned_weekly_schedule_entries
            WHERE organization_id=%s AND week_start >= %s
            """,
            (ORG, NEXT),
        )
        assert int(guard_cursor.fetchone()[0]) == 0
        guard.rollback()
        guard.close()

        preview = client.post("/operations-planner/v2/preview", json={
            "action": "apply_cell_scopes",
            "scope": "this_and_future",
            "week_start": WEEK,
            "anchor": WEEK,
            "cells": [{
                "user_id": 8,
                "day_of_week": 3,
                "shifts": [{
                    "user_id": 8,
                    "day_of_week": 3,
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "role": "fold",
                    "role_assignments": [{"role": "fold", "start_time": "09:00", "end_time": "17:00"}],
                }],
            }],
        })
        assert preview.status_code == 200, preview.get_json()
        dates = preview.get_json()["preview"]["dates"]
        assert WEEK in dates
        assert NEXT in dates
        assert len(dates) > 1

        current = _week(client)
        _apply(client, {
            "action": "apply_shift_set",
            "scope": "this_week",
            "week_start": WEEK,
            "expected_schedule_token": current["planner"]["schedule_token"],
            "operations": [_shift(9, 4, "10:00", "14:00", [{"role": "fold", "start_time": "10:00", "end_time": "14:00"}])],
        })
        disposable = _week(client)
        extra = next(row for row in disposable["entries"] if int(row["user_id"]) == 9)
        _apply(client, {
            "action": "apply_shift_set",
            "scope": "this_week",
            "week_start": WEEK,
            "expected_schedule_token": disposable["planner"]["schedule_token"],
            "operations": [{"op": "delete", "id": extra["id"], "user_id": 9, "day_of_week": 4}],
        })
        after_delete = _week(client)
        assert all(int(row["id"]) != int(extra["id"]) for row in after_delete["entries"])

        approved = client.post("/operations-planner/v2/weeks/approve", json={"weeks": [WEEK]})
        assert approved.status_code == 200, approved.get_json()
        published = client.post("/operations-planner/v2/weeks/publish", json={"weeks": [WEEK]})
        assert published.status_code == 200, published.get_json()
        live = _week(client)
        assert live["planner"]["status"] == "published"

        task_count_before = len(live.get("daily_responsibilities") or [])
        individual = client.post("/operations-planner/v2/task-assignments", json={
            "week_start": WEEK,
            "tasks": [{
                "user_id": 9,
                "day_of_week": 4,
                "role": "floor_cleaning",
                "timing_mode": "anytime",
                "execution_mode": "individual",
            }],
        })
        assert individual.status_code == 200, individual.get_json()
        shared = client.post("/operations-planner/v2/task-assignments", json={
            "week_start": WEEK,
            "tasks": [{
                "user_id": 7,
                "day_of_week": 5,
                "role": "washer_cleaning",
                "timing_mode": "anytime",
                "execution_mode": "shared",
                "shared": True,
            }],
        })
        assert shared.status_code == 200, shared.get_json()
        group = None
        tasked = _week(client)
        priya = [row for row in tasked["daily_responsibilities"] if int(row["user_id"]) == 9 and row["role"] == "floor_cleaning"]
        assert priya and not priya[0].get("assignment_group_id")
        assert not any(int(row["user_id"]) == 9 and int(row["day_of_week"]) == 4 for row in tasked["entries"])
        washer = [row for row in tasked["daily_responsibilities"] if row["role"] == "washer_cleaning"]
        assert len(washer) == 1
        group = washer[0].get("assignment_group_id")
        assert group
        lookalike = client.post("/operations-planner/v2/task-assignments", json={
            "week_start": WEEK,
            "tasks": [{
                "user_id": 8,
                "day_of_week": 5,
                "role": "washer_cleaning",
                "timing_mode": "anytime",
                "execution_mode": "individual",
            }],
        })
        assert lookalike.status_code == 200, lookalike.get_json()
        joined = client.post("/operations-planner/v2/task-assignments", json={
            "week_start": WEEK,
            "tasks": [{
                "user_id": 9,
                "day_of_week": 5,
                "role": "washer_cleaning",
                "timing_mode": "anytime",
                "execution_mode": "shared",
                "shared": True,
                "assignment_group_id": group,
            }],
        })
        assert joined.status_code == 200, joined.get_json()
        final_tasks = _week(client)["daily_responsibilities"]
        luis = next(row for row in final_tasks if int(row["user_id"]) == 8 and row["role"] == "washer_cleaning")
        priya_shared = next(row for row in final_tasks if int(row["user_id"]) == 9 and row["role"] == "washer_cleaning")
        assert not luis.get("assignment_group_id")
        assert priya_shared.get("assignment_group_id") == group

        hold = connect()
        hold_cursor = hold.cursor()
        hold_cursor.execute(
            """
            INSERT INTO planned_weekly_schedule_responsibilities
              (organization_id, week_start, user_id, day_of_week, role, timing_mode, execution_mode)
            VALUES (%s, %s, 8, 1, 'floor_cleaning', 'anytime', 'individual')
            """,
            (ORG, "2027-01-03"),
        )
        locked_id = int(hold_cursor.lastrowid)
        hold_cursor.execute(
            """
            INSERT INTO cleaning_task_activities (organization_id, responsibility_id, status, activity_kind)
            VALUES (%s, %s, 'completed', 'task')
            """,
            (ORG, locked_id),
        )
        hold.commit()
        hold.close()
        refused = client.post("/operations-planner/v2/task-assignments", json={
            "week_start": WEEK,
            "updates": [{"id": locked_id, "user_id": 7, "day_of_week": 2, "role": "floor_cleaning"}],
            "removals": [locked_id],
        })
        assert refused.status_code >= 400
        still = connect()
        still_cursor = still.cursor(dictionary=True)
        still_cursor.execute(
            "SELECT user_id, day_of_week, role FROM planned_weekly_schedule_responsibilities WHERE id=%s",
            (locked_id,),
        )
        kept = still_cursor.fetchone()
        assert int(kept["user_id"]) == 8
        assert int(kept["day_of_week"]) == 1
        still.close()
        assert len(_week(client)["daily_responsibilities"]) >= task_count_before
    finally:
        backend_db.get_db = original_db
        routes.get_db = original_routes
