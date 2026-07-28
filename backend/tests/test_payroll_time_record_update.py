"""Payroll time record update — active shift without clock out."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

from backend.payroll_operations import (
    _apply_time_record_role_tag,
    create_manual_time_record,
    update_time_record,
)


@pytest.fixture
def conn():
    connection = MagicMock()
    return connection


def test_update_clock_in_only_keeps_active_session(conn):
    connection = conn
    select_cur = MagicMock()
    select_cur.fetchone.return_value = {
        "user_id": 7,
        "clock_in_at": datetime(2026, 6, 18, 8, 0),
        "clock_out_at": None,
    }
    update_cur = MagicMock()
    update_cur.rowcount = 1
    connection.cursor.side_effect = [MagicMock(), select_cur, update_cur]

    with patch("backend.payroll_operations._session_in_org", return_value=True), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ), patch("backend.payroll_operations._sum_break_seconds", return_value=0), patch(
        "backend.payroll_operations.list_time_records",
        return_value=[{"id": 9, "clock_in_at": datetime(2026, 6, 18, 10, 12)}],
    ):
        rec = update_time_record(
            connection,
            3,
            9,
            clock_in_at="2026-06-18 10:12:00",
            clock_out_at="",
        )
    assert rec["id"] == 9
    sql = update_cur.execute.call_args[0][0]
    assert "clock_out_at=NULL" in sql
    assert "status=%s" in sql or "status='active'" in sql.lower() or "active" in str(
        update_cur.execute.call_args[0][1]
    )


def test_create_clock_in_only_starts_active_session(conn):
    active_check = MagicMock()
    active_check.fetchone.return_value = None
    insert_cur = MagicMock()
    insert_cur.lastrowid = 42
    connection = conn
    connection.cursor.side_effect = [active_check, MagicMock(), insert_cur]

    with patch("backend.payroll_operations.get_or_create_payroll_cycle_unified", return_value=1), patch(
        "backend.payroll_operations._geofence_for_user", return_value=5
    ), patch("backend.payroll_operations._employment_category_for_user", return_value=2), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ), patch(
        "backend.payroll_operations.list_time_records",
        return_value=[{"id": 42, "status": "open", "clock_out_at": None}],
    ):
        rec = create_manual_time_record(
            connection,
            3,
            user_id=7,
            clock_in_at="2026-06-25 14:00:00",
            clock_out_at="",
        )
    assert rec["id"] == 42
    sql, params = insert_cur.execute.call_args[0]
    assert "active" in params
    assert None in params


def test_create_clock_in_only_rejects_existing_active_shift(conn):
    active_check = MagicMock()
    active_check.fetchone.return_value = {"id": 99}
    connection = conn
    connection.cursor.return_value = active_check

    with pytest.raises(ValueError, match="already has an open shift"):
        create_manual_time_record(
            connection,
            3,
            user_id=7,
            clock_in_at="2026-06-25 14:00:00",
            clock_out_at="",
        )


def test_create_requires_category_and_role_together(conn):
    with pytest.raises(ValueError, match="required together"):
        create_manual_time_record(
            conn,
            3,
            user_id=7,
            clock_in_at="2026-06-25 14:00:00",
            clock_out_at="2026-06-25 18:00:00",
            category_id=1,
        )


def test_apply_time_record_role_tag_inserts_segment(conn):
    schema_cur = MagicMock()
    write_cur = MagicMock()
    conn.cursor.side_effect = [schema_cur, write_cur]
    assignment = {
        "id": 55,
        "category_id": 1,
        "role_id": 2,
        "category_code": "RINSE_WF",
        "role_code": "OPERATOR",
        "category_name": "Rinse WF",
        "role_name": "Operator",
    }
    started = datetime(2026, 6, 25, 14, 0)
    ended = datetime(2026, 6, 25, 18, 0)

    with patch("backend.shift_job_tracking.ensure_shift_job_tracking_schema"), patch(
        "backend.shift_job_tracking.resolve_active_assignment", return_value=assignment
    ), patch("backend.payroll_operations.table_exists", return_value=True), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ):
        _apply_time_record_role_tag(
            conn,
            3,
            session_id=42,
            user_id=7,
            category_id=1,
            role_id=2,
            started_at=started,
            ended_at=ended,
        )

    assert write_cur.execute.call_args_list[0] == call(
        "DELETE FROM shift_job_segments WHERE shift_session_id=%s",
        (42,),
    )
    insert_sql, insert_params = write_cur.execute.call_args_list[1][0]
    assert "INSERT INTO shift_job_segments" in insert_sql
    assert insert_params[0] == 42
    assert insert_params[2] == 1
    assert insert_params[3] == 2
    assert insert_params[4] == 55
    assert insert_params[-1] == "payroll_manual"


def test_update_tags_role_when_category_and_role_provided(conn):
    select_cur = MagicMock()
    select_cur.fetchone.return_value = {
        "user_id": 7,
        "clock_in_at": datetime(2026, 6, 18, 8, 0),
        "clock_out_at": datetime(2026, 6, 18, 16, 0),
    }
    update_cur = MagicMock()
    update_cur.rowcount = 1
    conn.cursor.side_effect = [MagicMock(), select_cur, update_cur]

    with patch("backend.payroll_operations._session_in_org", return_value=True), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ), patch("backend.payroll_operations._sum_break_seconds", return_value=0), patch(
        "backend.payroll_operations._apply_time_record_role_tag"
    ) as tag, patch(
        "backend.payroll_operations.list_time_records",
        return_value=[{"id": 9, "role_label": "Rinse WF — Operator"}],
    ):
        rec = update_time_record(
            conn,
            3,
            9,
            clock_in_at="2026-06-18 08:00:00",
            clock_out_at="2026-06-18 16:00:00",
            category_id=1,
            role_id=2,
        )

    assert rec["id"] == 9
    tag.assert_called_once()
    kwargs = tag.call_args.kwargs
    assert kwargs["session_id"] == 9
    assert kwargs["user_id"] == 7
    assert kwargs["category_id"] == 1
    assert kwargs["role_id"] == 2
    assert kwargs["ended_at"] == datetime(2026, 6, 18, 16, 0)


def test_update_tags_role_on_open_shift_without_clock_out(conn):
    """Open records (e.g. Evelin still clocked in) can still retag category/role."""
    select_cur = MagicMock()
    select_cur.fetchone.return_value = {
        "user_id": 7,
        "clock_in_at": datetime(2026, 7, 28, 8, 2),
        "clock_out_at": None,
    }
    update_cur = MagicMock()
    update_cur.rowcount = 1
    conn.cursor.side_effect = [MagicMock(), select_cur, update_cur]

    with patch("backend.payroll_operations._session_in_org", return_value=True), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ), patch("backend.payroll_operations._sum_break_seconds", return_value=0), patch(
        "backend.payroll_operations._apply_time_record_role_tag"
    ) as tag, patch(
        "backend.payroll_operations.list_time_records",
        return_value=[{"id": 9, "role_label": "Rinse HD — Operator", "status": "open"}],
    ):
        rec = update_time_record(
            conn,
            3,
            9,
            clock_in_at="2026-07-28 08:02:00",
            clock_out_at="",
            category_id=1,
            role_id=3,
        )

    assert rec["id"] == 9
    tag.assert_called_once()
    kwargs = tag.call_args.kwargs
    assert kwargs["category_id"] == 1
    assert kwargs["role_id"] == 3
    assert kwargs["ended_at"] is None
    assert kwargs["started_at"] == datetime(2026, 7, 28, 8, 2)
