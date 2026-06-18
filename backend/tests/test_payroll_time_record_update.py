"""Payroll time record update — active shift without clock out."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.payroll_operations import update_time_record


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
