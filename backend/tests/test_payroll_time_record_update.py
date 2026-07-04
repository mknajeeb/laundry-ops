"""Payroll time record update — active shift without clock out."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.payroll_operations import create_manual_time_record, update_time_record


@pytest.fixture
def conn():
    connection = MagicMock()
    return connection


def test_update_clock_in_only_keeps_active_session(conn):
    connection = conn
    select_cur = MagicMock()
    select_cur.fetchone.return_value = {
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
