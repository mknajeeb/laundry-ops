"""Bulk approve time records — single UPDATE, no per-row list reload."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.payroll_operations import approve_time_record, bulk_approve_time_records


def test_approve_time_record_skips_list_reload():
    conn = MagicMock()
    upd = MagicMock()
    upd.rowcount = 1
    conn.cursor.side_effect = [MagicMock(), upd]

    with patch("backend.payroll_operations._session_in_org", return_value=True), patch(
        "backend.payroll_operations.ensure_payroll_hours_approved_column"
    ), patch("backend.payroll_operations.table_has_column", side_effect=[True, True]), patch(
        "backend.payroll_operations.list_time_records"
    ) as list_fn:
        rec = approve_time_record(conn, 3, 99)

    assert rec == {"id": 99, "status": "approved", "payroll_hours_approved": True}
    list_fn.assert_not_called()
    sql, params = upd.execute.call_args[0]
    assert "payroll_hours_approved=1" in sql
    assert "manual_override=0" in sql
    assert params == (99, 3)


def test_bulk_approve_uses_single_update():
    conn = MagicMock()
    schema_cur = MagicMock()
    find_cur = MagicMock()
    find_cur.fetchall.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]
    upd_cur = MagicMock()
    upd_cur.rowcount = 3
    conn.cursor.side_effect = [schema_cur, find_cur, upd_cur]

    with patch("backend.payroll_operations.ensure_payroll_hours_approved_column"), patch(
        "backend.payroll_operations.table_has_column", side_effect=[True, True]
    ), patch("backend.payroll_operations.list_time_records") as list_fn, patch(
        "backend.payroll_operations.approve_time_record"
    ) as approve_fn:
        result = bulk_approve_time_records(conn, 3, session_ids=[1, 2, 2, 3])

    assert result == {"approved": 3, "skipped": 0, "errors": []}
    list_fn.assert_not_called()
    approve_fn.assert_not_called()
    find_sql, find_params = find_cur.execute.call_args[0]
    assert "id IN (%s,%s,%s)" in find_sql
    assert find_params == (1, 2, 3, 3)
    upd_sql, upd_params = upd_cur.execute.call_args[0]
    assert "UPDATE shift_sessions SET" in upd_sql
    assert "payroll_hours_approved=1" in upd_sql
    assert "id IN (%s,%s,%s)" in upd_sql
    assert upd_params == (1, 2, 3, 3)
    conn.commit.assert_called_once()


def test_bulk_approve_reports_missing_ids():
    conn = MagicMock()
    schema_cur = MagicMock()
    find_cur = MagicMock()
    find_cur.fetchall.return_value = [{"id": 10}]
    upd_cur = MagicMock()
    upd_cur.rowcount = 1
    conn.cursor.side_effect = [schema_cur, find_cur, upd_cur]

    with patch("backend.payroll_operations.ensure_payroll_hours_approved_column"), patch(
        "backend.payroll_operations.table_has_column", side_effect=[False, True]
    ):
        result = bulk_approve_time_records(conn, 3, session_ids=[10, 99])

    assert result["approved"] == 1
    assert result["skipped"] == 1
    assert result["errors"] == [{"id": 99, "error": "Time record not found"}]
    upd_sql, upd_params = upd_cur.execute.call_args[0]
    assert "id IN (%s)" in upd_sql
    assert upd_params == (10, 3)
