"""Persistence checks for staffing intervals and task drafts.

These run only against the local isolated MySQL on 127.0.0.1:3307.
They do not connect to Azure and they do not write a production schedule.
"""

from __future__ import annotations

from datetime import date

import mysql.connector
import pytest

from backend.operations_planner_v2_store import (
    StaffingRequirementError,
    add_assignments,
    load_assignment_rows,
    load_staffing_requirements,
    replace_staffing_requirements,
)

HOST = "127.0.0.1"
PORT = 3307
ORG = 303030
WEEK = date(2027, 1, 4)


def _connect():
    if HOST != "127.0.0.1":
        raise RuntimeError("isolated staffing test refused a non-local host")
    return mysql.connector.connect(
        host=HOST,
        port=PORT,
        user="root",
        database="ops_planner_test",
        autocommit=False,
        connection_timeout=5,
    )


def _available():
    try:
        conn = _connect()
    except Exception:
        return False
    conn.close()
    return True


pytestmark = pytest.mark.skipif(not _available(), reason="isolated MySQL on 127.0.0.1:3307 is not running")


def _prepare(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ops_planner_staffing_requirements (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          role_key VARCHAR(64) NOT NULL,
          day_of_week TINYINT NULL,
          start_time TIME NOT NULL,
          end_time TIME NOT NULL,
          required_headcount INT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS planned_weekly_schedule_responsibilities (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          week_start DATE NOT NULL,
          user_id INT NOT NULL,
          day_of_week TINYINT NOT NULL,
          role VARCHAR(40) NOT NULL,
          remarks VARCHAR(255) NULL,
          assignment_group_id VARCHAR(36) NULL,
          timing_mode VARCHAR(20) NOT NULL DEFAULT 'anytime',
          start_time TIME NULL,
          execution_mode VARCHAR(20) NOT NULL DEFAULT 'individual'
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cleaning_task_activities (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          responsibility_id INT NOT NULL,
          status VARCHAR(32) NOT NULL,
          parent_activity_id INT NULL,
          activity_kind VARCHAR(32) NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ops_planner_isolated_schedule_guard (
          id INT PRIMARY KEY,
          organization_id INT NOT NULL,
          marker VARCHAR(64) NOT NULL
        )
        """
    )
    cursor.execute("DELETE FROM ops_planner_staffing_requirements WHERE organization_id=%s", (ORG,))
    cursor.execute("DELETE FROM cleaning_task_activities WHERE organization_id=%s", (ORG,))
    cursor.execute("DELETE FROM planned_weekly_schedule_responsibilities WHERE organization_id=%s", (ORG,))
    cursor.execute("DELETE FROM ops_planner_isolated_schedule_guard WHERE organization_id=%s", (ORG,))
    cursor.execute(
        """
        INSERT INTO planned_weekly_schedule_responsibilities
          (organization_id, week_start, user_id, day_of_week, role, remarks, assignment_group_id)
        VALUES (%s, %s, 19, 1, 'floor_reset', 'keep me', 'shared-locked')
        """,
        (ORG, WEEK),
    )
    responsibility_id = int(cursor.lastrowid)
    cursor.execute(
        """
        INSERT INTO cleaning_task_activities (organization_id, responsibility_id, status, activity_kind)
        VALUES (%s, %s, 'completed', 'shared')
        """,
        (ORG, responsibility_id),
    )
    cursor.execute(
        "INSERT INTO ops_planner_isolated_schedule_guard (id, organization_id, marker) VALUES (1, %s, 'untouched')",
        (ORG,),
    )
    return responsibility_id


def _guard(cursor):
    cursor.execute(
        "SELECT marker FROM ops_planner_isolated_schedule_guard WHERE organization_id=%s",
        (ORG,),
    )
    row = cursor.fetchone()
    return row["marker"] if isinstance(row, dict) else row[0]


def _completed(cursor, responsibility_id):
    cursor.execute(
        """
        SELECT role, remarks, assignment_group_id
        FROM planned_weekly_schedule_responsibilities
        WHERE id=%s AND organization_id=%s
        """,
        (responsibility_id, ORG),
    )
    row = cursor.fetchone()
    cursor.execute(
        "SELECT status FROM cleaning_task_activities WHERE organization_id=%s AND responsibility_id=%s",
        (ORG, responsibility_id),
    )
    activity = cursor.fetchone()
    status = activity["status"] if isinstance(activity, dict) else activity[0]
    if isinstance(row, dict):
        return (row["role"], row["remarks"], row["assignment_group_id"], status)
    return (row[0], row[1], row[2], status)


def test_staffing_and_task_drafts_persist_without_touching_schedule_or_history():
    conn = _connect()
    cursor = conn.cursor(dictionary=True)
    responsibility_id = _prepare(cursor)
    conn.commit()
    before = _completed(cursor, responsibility_id)
    assert before == ("floor_reset", "keep me", "shared-locked", "completed")
    assert _guard(cursor) == "untouched"
    try:
        with pytest.raises(StaffingRequirementError):
            replace_staffing_requirements(
                cursor,
                ORG,
                [{"role": "wash", "day_of_week": 1, "start_time": "05:00", "end_time": "13:00", "required_headcount": ""}],
            )
        saved = replace_staffing_requirements(
            cursor,
            ORG,
            [
                {"role": "wash", "day_of_week": 1, "start_time": "05:00", "end_time": "13:00", "required_headcount": 3},
                {"role": "fold", "day_of_week": None, "start_time": "09:00", "end_time": "12:00", "required_headcount": 0},
            ],
        )
        conn.commit()
        assert [(row["role"], row["required_headcount"]) for row in saved] == [("fold", 0), ("wash", 3)]
        result = add_assignments(
            cursor,
            ORG,
            WEEK,
            [
                {"user_id": 67, "day_of_week": 1, "role": "trash", "shared": True},
                {"user_id": 23, "day_of_week": 1, "role": "floor_reset", "assignment_group_id": "shared-locked"},
            ],
        )
        conn.commit()
        assert result["inserted"] == 1
        assert result["removed"] == 0
        assert result["refused_groups"] == 1
        assert responsibility_id in result["preserved_history"]
        reloaded = load_staffing_requirements(cursor, ORG)
        assert reloaded[0]["required_headcount"] == 0
        assert reloaded[1]["day_of_week"] == 1
        assert reloaded[1]["start_time"] == "05:00"
        assert _completed(cursor, responsibility_id) == before
        rows = load_assignment_rows(cursor, ORG, WEEK)
        added = [row for row in rows if row["id"] != responsibility_id]
        assert len(added) == 1
        assert added[0]["role"] == "trash"
        assert added[0]["user_id"] == 67
        assert added[0]["assignment_group_id"] not in (None, "", "shared-locked")
        assert _guard(cursor) == "untouched"
        fresh = _connect()
        fresh_cursor = fresh.cursor(dictionary=True)
        try:
            again = load_staffing_requirements(fresh_cursor, ORG)
            assert [row["required_headcount"] for row in again] == [0, 3]
            assert _completed(fresh_cursor, responsibility_id) == before
            assert _guard(fresh_cursor) == "untouched"
        finally:
            fresh_cursor.close()
            fresh.close()
    finally:
        cursor.execute("DELETE FROM cleaning_task_activities WHERE organization_id=%s", (ORG,))
        cursor.execute("DELETE FROM planned_weekly_schedule_responsibilities WHERE organization_id=%s", (ORG,))
        cursor.execute("DELETE FROM ops_planner_staffing_requirements WHERE organization_id=%s", (ORG,))
        cursor.execute("DELETE FROM ops_planner_isolated_schedule_guard WHERE organization_id=%s", (ORG,))
        conn.commit()
        cursor.close()
        conn.close()
