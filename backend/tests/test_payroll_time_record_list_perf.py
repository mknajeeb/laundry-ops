"""Time records list query uses sargable date bounds."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from backend.payroll_operations import (
    _date_end_exclusive_dt,
    _date_start_dt,
    list_time_records,
)


def test_date_bounds_are_inclusive_start_exclusive_end():
    assert _date_start_dt("2026-07-27") == datetime(2026, 7, 27, 0, 0, 0)
    assert _date_end_exclusive_dt("2026-08-02") == datetime(2026, 8, 3, 0, 0, 0)


def test_list_time_records_uses_clock_in_range_not_date_fn():
    conn = MagicMock()
    chk = MagicMock()
    select_cur = MagicMock()
    select_cur.fetchall.return_value = []
    conn.cursor.side_effect = [chk, select_cur]

    with patch("backend.payroll_operations.payroll_profiles_active", return_value=True), patch(
        "backend.payroll_operations.ensure_payroll_hours_approved_column"
    ), patch("backend.payroll_operations.table_has_column", return_value=False), patch(
        "backend.payroll_operations._attach_role_segments_to_time_records"
    ):
        items = list_time_records(
            conn,
            3,
            from_date="2026-07-27",
            to_date="2026-08-02",
            limit=100,
        )

    assert items == []
    sql, params = select_cur.execute.call_args[0]
    assert "DATE(s.clock_in_at)" not in sql
    assert "s.clock_in_at >= %s" in sql
    assert "s.clock_in_at < %s" in sql
    assert params[0] == 3
    assert params[1] == datetime(2026, 7, 27, 0, 0, 0)
    assert params[2] == datetime(2026, 8, 3, 0, 0, 0)
    assert params[3] == 100
