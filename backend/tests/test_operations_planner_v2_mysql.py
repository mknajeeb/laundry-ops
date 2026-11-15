"""Planner behavior against the isolated MySQL on 127.0.0.1:3307."""

from __future__ import annotations

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
