"""Planner behavior against the isolated MySQL on 127.0.0.1:3307."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from datetime import date

import pytest

pytest.importorskip("mysql.connector")

from backend.operations_planner_v2 import commit_or_rollback, paystub_code_hash, verify_personal_paystub_code
from backend.operations_planner_v2_store import _sync_cell_tasks, load_state, save_state
from backend.scripts.ops_planner_isolated_db import connect, prepare


def _available():
    try:
        conn = connect(database=None)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _available(), reason="isolated MySQL on port 3307 is not running")


@pytest.fixture(scope="module", autouse=True)
def _schema():
    prepare()


def test_two_connections_cannot_hold_the_planner_lock():
    first = connect()
    second = connect()
    try:
        one = first.cursor(dictionary=True)
        two = second.cursor(dictionary=True)
        one.execute("SELECT GET_LOCK('ops_planner_1', 2) AS locked")
        assert int(one.fetchone()["locked"]) == 1
        two.execute("SELECT GET_LOCK('ops_planner_1', 1) AS locked")
        assert int(two.fetchone()["locked"]) == 0
        one.execute("SELECT RELEASE_LOCK('ops_planner_1')")
        two.execute("SELECT GET_LOCK('ops_planner_1', 2) AS locked")
        assert int(two.fetchone()["locked"]) == 1
        two.execute("SELECT RELEASE_LOCK('ops_planner_1')")
    finally:
        first.close()
        second.close()


def test_a_failed_bulk_write_leaves_no_pattern_rows():
    conn = connect()
    cursor = conn.cursor(dictionary=True)

    def work():
        cursor.execute(
            """
            INSERT INTO ops_planner_patterns
              (id, organization_id, user_id, day_of_week, effective_from, shift_json)
            VALUES (9001, 1, 7, 1, '2026-11-09', '{}')
            """
        )
        cursor.execute(
            """
            INSERT INTO ops_planner_patterns
              (id, organization_id, user_id, day_of_week, effective_from, shift_json)
            VALUES (9002, 1, 8, 1, '2026-11-09', '{}')
            """
        )
        raise RuntimeError("second employee failed")

    try:
        outcome = commit_or_rollback(work, conn.commit, conn.rollback)
        assert outcome["rolled_back"] is True
        cursor.execute("SELECT COUNT(*) AS n FROM ops_planner_patterns WHERE id IN (9001, 9002)")
        assert int(cursor.fetchone()["n"]) == 0
    finally:
        conn.rollback()
        cursor.close()
        conn.close()


def test_completed_task_rows_survive_a_schedule_sync():
    conn = connect()
    cursor = conn.cursor(dictionary=True)
    storage = date(2026, 11, 8)
    try:
        from backend.planned_weekly_schedule_responsibilities import create_responsibility

        created, err = create_responsibility(
            conn,
            cursor,
            1,
            week_start=storage,
            data={
                "user_ids": [7],
                "day_of_week": 1,
                "role": "floor_cleaning",
                "remarks": "",
                "timing_mode": "anytime",
                "execution_mode": "individual",
            },
        )
        assert err is None and created
        responsibility_id = int(created["id"])
        cursor.execute(
            """
            INSERT INTO cleaning_task_activities
              (organization_id, responsibility_id, status, activity_kind)
            VALUES (1, %s, 'completed', 'task')
            """,
            (responsibility_id,),
        )
        _sync_cell_tasks(conn, cursor, 1, storage_week=storage, user_id=7, day_of_week=1, tasks=[])
        cursor.execute(
            "SELECT id FROM planned_weekly_schedule_responsibilities WHERE id=%s",
            (responsibility_id,),
        )
        assert cursor.fetchone()["id"] == responsibility_id
    finally:
        conn.rollback()
        cursor.close()
        conn.close()


def test_published_snapshot_round_trips_from_mysql():
    conn = connect()
    cursor = conn.cursor(dictionary=True)
    state = {
        "patterns": [],
        "exceptions": [],
        "weeks": {
            "2026-11-09": {
                "status": "published",
                "revision": 2,
                "published_revision": 2,
                "published_snapshot": {"entries": [{"user_id": 7, "role": "fold"}], "daily_responsibilities": []},
            }
        },
        "audit": [{"action": "publish"}],
        "next_pattern_id": 1,
        "next_exception_id": 1,
    }
    try:
        save_state(cursor, 1, state, state["audit"][0], 1)
        conn.commit()
        loaded = load_state(cursor, 1)
        assert loaded["weeks"]["2026-11-09"]["status"] == "published"
        assert loaded["weeks"]["2026-11-09"]["published_snapshot"]["entries"][0]["user_id"] == 7
    finally:
        cursor.execute("DELETE FROM ops_planner_weeks WHERE organization_id=1 AND week_monday='2026-11-09'")
        cursor.execute("DELETE FROM ops_planner_audit WHERE organization_id=1")
        conn.commit()
        cursor.close()
        conn.close()


def test_a_personal_paystub_code_does_not_accept_another_employee_or_a_reused_code():
    digest = paystub_code_hash("481920")
    ok, reason = verify_personal_paystub_code(
        supplied="481920",
        stored_hash=digest,
        employee_id=7,
        stored_employee_id=7,
        used=False,
        expired=False,
    )
    assert ok is True and reason == "ok"
    rejected, why = verify_personal_paystub_code(
        supplied="481920",
        stored_hash=digest,
        employee_id=8,
        stored_employee_id=7,
        used=False,
        expired=False,
    )
    assert rejected is False and why == "verification_failed"
    reused, reuse_why = verify_personal_paystub_code(
        supplied="481920",
        stored_hash=digest,
        employee_id=7,
        stored_employee_id=7,
        used=True,
        expired=False,
    )
    assert reused is False and reuse_why == "verification_failed"


def _clock(value):
    if hasattr(value, "total_seconds"):
        minutes = int(value.total_seconds() // 60) % (24 * 60)
        return f"{minutes // 60:02d}:{minutes % 60:02d}"
    return str(value)[:5]


def _shift(user_id, day, start, end, role="wash"):
    return {
        "user_id": user_id,
        "day_of_week": day,
        "start_time": start,
        "end_time": end,
        "role": role,
        "role_assignments": [{"role": role, "start_time": start, "end_time": end}],
        "break_slots": [],
        "break_minutes": 0,
    }


def _post(base, body):
    data = json.dumps(body).encode()
    request = urllib.request.Request(
        base + "/operations-planner/v2/apply",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def _get(base, monday):
    with urllib.request.urlopen(f"{base}/operations-planner/v2/week?week_start={monday}") as response:
        return json.loads(response.read().decode())


def _count(cursor, table):
    cursor.execute(
        "SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = %s",
        (table,),
    )
    if int(cursor.fetchone()["n"]) == 0:
        return None
    cursor.execute(f"SELECT COUNT(*) AS n FROM {table}")
    return int(cursor.fetchone()["n"])


def test_rollback_after_the_lock_sees_the_commit_that_landed_while_waiting():
    """GET_LOCK opens the snapshot before the wait ends. ROLLBACK starts a fresh read."""
    from backend.weekly_schedule_week import storage_week_for_dow

    holder = connect()
    waiter = connect()
    writer = connect()
    monday = date(2027, 10, 4)
    storage = storage_week_for_dow(monday, 1)
    try:
        writer.cursor().execute(
            """
            INSERT INTO planned_weekly_schedule_entries
              (organization_id, week_start, user_id, day_of_week, role, start_time, end_time, break_minutes)
            VALUES (1, %s, 8, 1, 'wash', '05:00', '09:00', 0)
            """,
            (storage,),
        )
        writer.commit()
        held = holder.cursor()
        held.execute("SELECT GET_LOCK('ops_planner_1', 2)")
        assert int(held.fetchone()[0]) == 1
        seen = {}
        ready = threading.Event()

        def wait_for_lock():
            cursor = waiter.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT end_time
                FROM planned_weekly_schedule_entries
                WHERE organization_id=1 AND week_start=%s AND user_id=8 AND day_of_week=1
                """,
                (storage,),
            )
            seen["before"] = _clock(cursor.fetchone()["end_time"])
            ready.set()
            cursor.execute("SELECT GET_LOCK('ops_planner_1', 5) AS locked")
            seen["locked"] = int(cursor.fetchone()["locked"])
            cursor.execute(
                """
                SELECT end_time
                FROM planned_weekly_schedule_entries
                WHERE organization_id=1 AND week_start=%s AND user_id=8 AND day_of_week=1
                """,
                (storage,),
            )
            seen["stale"] = _clock(cursor.fetchone()["end_time"])
            waiter.rollback()
            cursor.execute(
                """
                SELECT end_time
                FROM planned_weekly_schedule_entries
                WHERE organization_id=1 AND week_start=%s AND user_id=8 AND day_of_week=1
                """,
                (storage,),
            )
            seen["fresh"] = _clock(cursor.fetchone()["end_time"])
            cursor.execute("SELECT RELEASE_LOCK('ops_planner_1')")
            cursor.fetchone()

        thread = threading.Thread(target=wait_for_lock)
        thread.start()
        assert ready.wait(3)
        time.sleep(0.2)
        writer.cursor().execute(
            """
            UPDATE planned_weekly_schedule_entries
               SET end_time='11:00'
             WHERE organization_id=1 AND week_start=%s AND user_id=8 AND day_of_week=1
            """,
            (storage,),
        )
        writer.commit()
        held.execute("SELECT RELEASE_LOCK('ops_planner_1')")
        held.fetchone()
        thread.join(6)
        assert seen["before"] == "09:00"
        assert seen["locked"] == 1
        assert seen["stale"] == "09:00"
        assert seen["fresh"] == "11:00"
    finally:
        writer.cursor().execute(
            "DELETE FROM planned_weekly_schedule_entries WHERE organization_id=1 AND week_start=%s AND user_id=8 AND day_of_week=1",
            (storage,),
        )
        writer.commit()
        for conn in (holder, waiter, writer):
            try:
                conn.close()
            except Exception:
                pass


def test_overlapping_saves_let_only_the_first_commit_win():
    """Two requests in flight with one token: one 200, one 409, and the stored row is the winner."""
    import backend.db as backend_db
    import backend.operations_planner_v2_routes as routes
    from werkzeug.serving import make_server

    from backend.scripts.ops_planner_isolated_db import build_app

    original_get_db = backend_db.get_db
    monday = "2027-10-04"
    app = build_app()
    server = make_server("127.0.0.1", 0, app, threaded=True)
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    conn = connect()
    cursor = conn.cursor(dictionary=True)
    protected = ("payroll_worker_profiles", "planned_weekly_schedule_responsibilities", "cleaning_task_activities")
    before_counts = {name: _count(cursor, name) for name in protected}
    cursor.execute("SELECT id FROM planned_weekly_schedule_entries WHERE organization_id=1")
    before_entries = {int(row["id"]) for row in cursor.fetchall()}
    cursor.execute("SELECT id FROM ops_planner_patterns WHERE organization_id=1")
    before_patterns = {int(row["id"]) for row in cursor.fetchall()}
    cursor.execute("SELECT id FROM ops_planner_exceptions WHERE organization_id=1")
    before_exceptions = {int(row["id"]) for row in cursor.fetchall()}
    try:
        week = _get(base, monday)
        token = week["planner"]["schedule_token"]
        status, created = _post(base, {
            "action": "apply_shift_set",
            "scope": "this_week",
            "week_start": monday,
            "expected_schedule_token": token,
            "operations": [{"op": "create", "user_id": 8, "day_of_week": 1, "shift": _shift(8, 1, "05:00", "09:00")}],
        })
        assert status == 200 and created.get("ok") is True
        week = _get(base, monday)
        token = week["planner"]["schedule_token"]
        entry_id = next(row["id"] for row in week["entries"] if row["user_id"] == 8 and row["day_of_week"] == 1)
        holder = connect()
        held = holder.cursor()
        held.execute("SELECT GET_LOCK('ops_planner_1', 2)")
        assert int(held.fetchone()[0]) == 1
        results = []

        def save(end):
            status, body = _post(base, {
                "action": "apply_shift_set",
                "scope": "this_week",
                "week_start": monday,
                "expected_schedule_token": token,
                "operations": [{"op": "update", "id": entry_id, "user_id": 8, "day_of_week": 1, "shift": _shift(8, 1, "05:00", end)}],
            })
            results.append((end, status, body))

        first = threading.Thread(target=save, args=("14:00",))
        second = threading.Thread(target=save, args=("16:00",))
        first.start()
        second.start()
        time.sleep(1.0)
        held.execute("SELECT RELEASE_LOCK('ops_planner_1')")
        held.fetchone()
        holder.close()
        first.join(8)
        second.join(8)
        codes = sorted(status for _end, status, _body in results)
        assert codes == [200, 409]
        rejected = next(body for _end, status, body in results if status == 409)
        assert rejected["code"] == "schedule_changed"
        winner_end = next(end for end, status, _body in results if status == 200)
        fresh = connect()
        check = fresh.cursor(dictionary=True)
        check.execute("SELECT end_time FROM planned_weekly_schedule_entries WHERE id=%s", (entry_id,))
        stored = _clock(check.fetchone()["end_time"])
        assert stored == winner_end
        week = _get(base, monday)
        assert week["planner"]["schedule_token"] != token
        reloaded = next(row for row in week["entries"] if row["id"] == entry_id)
        assert str(reloaded["end_time"])[:5] == stored

        status, again = _post(base, {
            "action": "apply_shift_set",
            "scope": "this_week",
            "week_start": monday,
            "expected_schedule_token": week["planner"]["schedule_token"],
            "operations": [{"op": "update", "id": entry_id, "user_id": 8, "day_of_week": 1, "shift": _shift(8, 1, "05:00", stored)}],
        })
        assert status == 200 and again.get("ok") is True
        check.execute("SELECT COUNT(*) AS n FROM planned_weekly_schedule_entries WHERE id=%s", (entry_id,))
        assert int(check.fetchone()["n"]) == 1

        sunday = "2027-11-01"
        sunday_week = _get(base, sunday)
        status, repeated = _post(base, {
            "action": "apply_cell_scopes",
            "scope": "this_and_future",
            "week_start": sunday,
            "anchor": sunday,
            "expected_schedule_token": sunday_week["planner"]["schedule_token"],
            "cells": [{"user_id": 9, "day_of_week": 0, "shifts": [_shift(9, 0, "08:00", "12:00", "fold")]}],
        })
        assert status == 200 and repeated.get("ok") is True
        assert len(repeated["preview"]["dates"]) == 16
        fresh.rollback()
        check.execute(
            """
            SELECT COUNT(*) AS n FROM planned_weekly_schedule_entries
            WHERE organization_id=1 AND user_id=9 AND day_of_week=0 AND start_time='08:00' AND end_time='12:00'
            """
        )
        assert int(check.fetchone()["n"]) == 16
        check.execute(
            """
            SELECT COUNT(*) AS n FROM ops_planner_patterns
            WHERE organization_id=1 AND user_id=9 AND day_of_week=0 AND effective_until IS NULL
            """
        )
        assert int(check.fetchone()["n"]) == 1
        check.execute("SELECT week_start FROM planned_weekly_schedule_entries WHERE organization_id=1 AND user_id=9 AND day_of_week=0 ORDER BY week_start LIMIT 1")
        assert str(check.fetchone()["week_start"])[:10] == "2027-11-07"
        sunday_week = _get(base, sunday)
        status, repeated_again = _post(base, {
            "action": "apply_cell_scopes",
            "scope": "this_and_future",
            "week_start": sunday,
            "anchor": sunday,
            "expected_schedule_token": sunday_week["planner"]["schedule_token"],
            "cells": [{"user_id": 9, "day_of_week": 0, "shifts": [_shift(9, 0, "08:00", "12:00", "fold")]}],
        })
        assert status == 200 and repeated_again.get("ok") is True
        fresh.rollback()
        check.execute(
            """
            SELECT COUNT(*) AS n FROM ops_planner_patterns
            WHERE organization_id=1 AND user_id=9 AND day_of_week=0 AND effective_until IS NULL
            """
        )
        assert int(check.fetchone()["n"]) == 1
        check.execute(
            """
            SELECT COUNT(*) AS n FROM planned_weekly_schedule_entries
            WHERE organization_id=1 AND user_id=9 AND day_of_week=0
            """
        )
        assert int(check.fetchone()["n"]) == 16
        assert any(cell["user_id"] == 9 and cell["day_of_week"] == 0 for cell in _get(base, sunday)["planner"]["recurring_cells"])

        status, exception = _post(base, {
            "action": "apply_cell_scopes",
            "scope": "this_week",
            "week_start": sunday,
            "anchor": sunday,
            "expected_schedule_token": _get(base, sunday)["planner"]["schedule_token"],
            "cells": [{"user_id": 9, "day_of_week": 0, "shifts": [_shift(9, 0, "08:00", "13:00", "fold")]}],
        })
        assert status == 200 and exception.get("ok") is True
        fresh.rollback()
        check.execute(
            """
            SELECT end_time
            FROM planned_weekly_schedule_entries
            WHERE organization_id=1 AND user_id=9 AND day_of_week=0 AND week_start='2027-11-07'
            """
        )
        assert _clock(check.fetchone()["end_time"]) == "13:00"
        check.execute(
            """
            SELECT end_time
            FROM planned_weekly_schedule_entries
            WHERE organization_id=1 AND user_id=9 AND day_of_week=0 AND week_start='2027-11-14'
            """
        )
        assert _clock(check.fetchone()["end_time"]) == "12:00"
        check.execute(
            """
            SELECT kind FROM ops_planner_exceptions
            WHERE organization_id=1 AND user_id=9 AND day_of_week=0 AND week_monday='2027-11-01'
            """
        )
        assert check.fetchone()["kind"] == "override"
        check.execute(
            """
            SELECT COUNT(*) AS n FROM ops_planner_patterns
            WHERE organization_id=1 AND user_id=9 AND day_of_week=0 AND effective_until IS NULL
            """
        )
        assert int(check.fetchone()["n"]) == 1

        status, rejected_break = _post(base, {
            "action": "apply_shift_set",
            "scope": "this_week",
            "week_start": monday,
            "expected_schedule_token": _get(base, monday)["planner"]["schedule_token"],
            "operations": [{
                "op": "update",
                "id": entry_id,
                "user_id": 8,
                "day_of_week": 1,
                "shift": {**_shift(8, 1, "05:00", stored), "break_slots": [{"start_time": "12:00", "end_time": "19:00"}], "break_minutes": 420},
            }],
        })
        assert status == 409 and rejected_break.get("ok") is False
        fresh.rollback()
        check.execute("SELECT break_slots FROM planned_weekly_schedule_entries WHERE id=%s", (entry_id,))
        assert check.fetchone()["break_slots"] in (None, "", "null")

        for name, count in before_counts.items():
            if count is not None:
                assert _count(check, name) == count
        fresh.close()
    finally:
        server.shutdown()
        backend_db.get_db = original_get_db
        routes.get_db = original_get_db
        cleanup = connect()
        try:
            wipe = cleanup.cursor()
            wipe.execute("SELECT id FROM planned_weekly_schedule_entries WHERE organization_id=1")
            extra_entries = [int(row[0]) for row in wipe.fetchall() if int(row[0]) not in before_entries]
            if extra_entries:
                marks = ",".join(["%s"] * len(extra_entries))
                wipe.execute(f"DELETE FROM planned_weekly_schedule_entries WHERE id IN ({marks})", extra_entries)
            wipe.execute("SELECT id FROM ops_planner_patterns WHERE organization_id=1")
            extra_patterns = [int(row[0]) for row in wipe.fetchall() if int(row[0]) not in before_patterns]
            if extra_patterns:
                marks = ",".join(["%s"] * len(extra_patterns))
                wipe.execute(f"DELETE FROM ops_planner_patterns WHERE id IN ({marks})", extra_patterns)
            wipe.execute("SELECT id FROM ops_planner_exceptions WHERE organization_id=1")
            extra_exceptions = [int(row[0]) for row in wipe.fetchall() if int(row[0]) not in before_exceptions]
            if extra_exceptions:
                marks = ",".join(["%s"] * len(extra_exceptions))
                wipe.execute(f"DELETE FROM ops_planner_exceptions WHERE id IN ({marks})", extra_exceptions)
            wipe.execute(
                "DELETE FROM ops_planner_links WHERE organization_id=1 AND user_id IN (8, 9) AND week_monday >= '2027-10-04'"
            )
            cleanup.commit()
        finally:
            cleanup.close()
