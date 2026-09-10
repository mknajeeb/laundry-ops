"""Day-level Edit must not collapse multi-role shift_job_segments history."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

from backend.payroll_operations import (
    _resync_role_segments_to_session_clock,
    update_time_record,
)


def _multi_segments():
    return [
        {
            "id": 101,
            "started_at": datetime(2026, 9, 10, 5, 35),
            "ended_at": datetime(2026, 9, 10, 7, 4),
            "category_id": 1,
            "role_id": 1,
            "category_role_id": 10,
        },
        {
            "id": 102,
            "started_at": datetime(2026, 9, 10, 7, 4),
            "ended_at": datetime(2026, 9, 10, 7, 56),
            "category_id": 1,
            "role_id": 2,
            "category_role_id": 11,
        },
        {
            "id": 103,
            "started_at": datetime(2026, 9, 10, 7, 56),
            "ended_at": datetime(2026, 9, 10, 8, 30),
            "category_id": 2,
            "role_id": 2,
            "category_role_id": 20,
        },
        {
            "id": 104,
            "started_at": datetime(2026, 9, 10, 8, 30),
            "ended_at": None,
            "category_id": 1,
            "role_id": 3,
            "category_role_id": 12,
        },
    ]


@pytest.fixture
def conn():
    return MagicMock()


def test_multi_segment_clock_in_preserves_all_segment_ids(conn):
    segs = _multi_segments()
    select_cur = MagicMock()
    select_cur.fetchall.return_value = segs
    upd = MagicMock()
    conn.cursor.side_effect = [select_cur, upd]

    with patch("backend.payroll_operations.table_exists", return_value=True), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ), patch(
        "backend.payroll_operations._apply_time_record_role_tag"
    ) as tag, patch(
        "backend.payroll_operations._sync_session_current_assignment_from_segments"
    ):
        ok = _resync_role_segments_to_session_clock(
            conn,
            3,
            session_id=100,
            user_id=7,
            started_at=datetime(2026, 9, 10, 5, 30),
            ended_at=None,
        )

    assert ok is True
    tag.assert_not_called()
    assert upd.execute.call_count == 1
    sql, params = upd.execute.call_args[0]
    assert params == (datetime(2026, 9, 10, 5, 30), 101, 100)
    assert "DELETE FROM shift_job_segments" not in sql
    # Middle / later IDs never appear in UPDATE params
    updated_ids = {params[1]}
    assert updated_ids == {101}
    assert {102, 103, 104}.isdisjoint(updated_ids)


def test_multi_segment_clock_out_preserves_middle_segments(conn):
    segs = _multi_segments()
    # Close the open last segment for a completed day shape
    segs[-1] = {
        **segs[-1],
        "ended_at": datetime(2026, 9, 10, 12, 0),
    }
    select_cur = MagicMock()
    select_cur.fetchall.return_value = segs
    upd = MagicMock()
    conn.cursor.side_effect = [select_cur, upd]

    with patch("backend.payroll_operations.table_exists", return_value=True), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ), patch(
        "backend.payroll_operations._apply_time_record_role_tag"
    ) as tag, patch(
        "backend.payroll_operations._sync_session_current_assignment_from_segments"
    ):
        ok = _resync_role_segments_to_session_clock(
            conn,
            3,
            session_id=100,
            user_id=7,
            started_at=datetime(2026, 9, 10, 5, 35),
            ended_at=datetime(2026, 9, 10, 11, 45),
        )

    assert ok is True
    tag.assert_not_called()
    assert upd.execute.call_count == 1
    sql, params = upd.execute.call_args[0]
    assert "ended_at=%s" in sql
    assert params[0] == datetime(2026, 9, 10, 11, 45)
    assert params[-2:] == (104, 100)
    # Only last segment touched
    assert params[-2] == 104


def test_multi_segment_clock_in_and_out_only_touch_edges(conn):
    segs = _multi_segments()
    segs[-1] = {**segs[-1], "ended_at": datetime(2026, 9, 10, 12, 0)}
    select_cur = MagicMock()
    select_cur.fetchall.return_value = segs
    upd = MagicMock()
    conn.cursor.side_effect = [select_cur, upd]

    with patch("backend.payroll_operations.table_exists", return_value=True), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ), patch("backend.payroll_operations._apply_time_record_role_tag") as tag, patch(
        "backend.payroll_operations._sync_session_current_assignment_from_segments"
    ):
        ok = _resync_role_segments_to_session_clock(
            conn,
            3,
            session_id=100,
            user_id=7,
            started_at=datetime(2026, 9, 10, 5, 20),
            ended_at=datetime(2026, 9, 10, 12, 15),
        )

    assert ok is True
    tag.assert_not_called()
    assert upd.execute.call_count == 2
    first_params = upd.execute.call_args_list[0][0][1]
    last_params = upd.execute.call_args_list[1][0][1]
    assert first_params == (datetime(2026, 9, 10, 5, 20), 101, 100)
    assert last_params[0] == datetime(2026, 9, 10, 12, 15)
    assert last_params[-2:] == (104, 100)
    touched = {first_params[1], last_params[-2]}
    assert touched == {101, 104}
    assert 102 not in touched and 103 not in touched


def test_remarks_only_day_edit_does_not_collapse_via_retag(conn):
    select_cur = MagicMock()
    select_cur.fetchone.return_value = {
        "user_id": 7,
        "clock_in_at": datetime(2026, 9, 10, 5, 35),
        "clock_out_at": None,
    }
    update_cur = MagicMock()
    update_cur.rowcount = 1
    conn.cursor.side_effect = [MagicMock(), select_cur, update_cur]

    with patch("backend.payroll_operations._session_in_org", return_value=True), patch(
        "backend.payroll_operations.table_has_column", return_value=True
    ), patch("backend.payroll_operations._sum_break_seconds", return_value=0), patch(
        "backend.payroll_operations._resync_role_segments_to_session_clock", return_value=True
    ) as sync, patch(
        "backend.payroll_operations._apply_time_record_role_tag"
    ) as tag, patch(
        "backend.payroll_operations._count_role_segments", return_value=4
    ):
        rec = update_time_record(
            conn,
            3,
            100,
            clock_in_at="2026-09-10 05:35:00",
            clock_out_at="",
            remarks="note only",
        )

    assert rec["id"] == 100
    tag.assert_not_called()
    sync.assert_called_once()


def test_day_level_role_retag_blocked_for_multi_segment(conn):
    select_cur = MagicMock()
    select_cur.fetchone.return_value = {
        "user_id": 7,
        "clock_in_at": datetime(2026, 9, 10, 5, 35),
        "clock_out_at": None,
    }
    update_cur = MagicMock()
    update_cur.rowcount = 1
    conn.cursor.side_effect = [MagicMock(), select_cur, update_cur]

    with patch("backend.payroll_operations._session_in_org", return_value=True), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ), patch("backend.payroll_operations._sum_break_seconds", return_value=0), patch(
        "backend.payroll_operations._count_role_segments", return_value=4
    ), patch(
        "backend.payroll_operations._apply_time_record_role_tag"
    ) as tag, patch(
        "backend.payroll_operations._resync_role_segments_to_session_clock"
    ) as sync:
        with pytest.raises(ValueError, match="multiple role segments"):
            update_time_record(
                conn,
                3,
                100,
                clock_in_at="2026-09-10 05:35:00",
                clock_out_at="",
                category_id=1,
                role_id=9,
            )

    tag.assert_not_called()
    sync.assert_not_called()


def test_single_segment_day_role_retag_still_works(conn):
    select_cur = MagicMock()
    select_cur.fetchone.return_value = {
        "user_id": 7,
        "clock_in_at": datetime(2026, 9, 10, 8, 0),
        "clock_out_at": datetime(2026, 9, 10, 16, 0),
    }
    update_cur = MagicMock()
    update_cur.rowcount = 1
    conn.cursor.side_effect = [MagicMock(), select_cur, update_cur]

    with patch("backend.payroll_operations._session_in_org", return_value=True), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ), patch("backend.payroll_operations._sum_break_seconds", return_value=0), patch(
        "backend.payroll_operations._count_role_segments", return_value=1
    ), patch(
        "backend.payroll_operations._apply_time_record_role_tag"
    ) as tag, patch(
        "backend.payroll_operations._resync_role_segments_to_session_clock"
    ) as sync:
        rec = update_time_record(
            conn,
            3,
            100,
            clock_in_at="2026-09-10 08:00:00",
            clock_out_at="2026-09-10 16:00:00",
            category_id=1,
            role_id=2,
        )

    assert rec["id"] == 100
    tag.assert_called_once()
    sync.assert_not_called()
    assert tag.call_args.kwargs["category_id"] == 1
    assert tag.call_args.kwargs["role_id"] == 2


def test_single_segment_clock_resync_preserves_segment_id(conn):
    select_cur = MagicMock()
    select_cur.fetchall.return_value = [
        {
            "id": 55,
            "started_at": datetime(2026, 9, 10, 8, 0),
            "ended_at": datetime(2026, 9, 10, 16, 0),
            "category_id": 1,
            "role_id": 2,
            "category_role_id": 10,
        }
    ]
    upd = MagicMock()
    conn.cursor.side_effect = [select_cur, upd]

    with patch("backend.payroll_operations.table_exists", return_value=True), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ), patch("backend.payroll_operations._apply_time_record_role_tag") as tag, patch(
        "backend.payroll_operations._sync_session_current_assignment_from_segments"
    ):
        ok = _resync_role_segments_to_session_clock(
            conn,
            3,
            session_id=100,
            user_id=7,
            started_at=datetime(2026, 9, 10, 7, 45),
            ended_at=datetime(2026, 9, 10, 16, 15),
        )

    assert ok is True
    tag.assert_not_called()
    assert upd.execute.call_count == 2
    assert upd.execute.call_args_list[0][0][1][1] == 55
    assert upd.execute.call_args_list[1][0][1][-2] == 55
    assert all(
        "DELETE FROM shift_job_segments" not in c[0][0] for c in upd.execute.call_args_list
    )


def test_update_multi_segment_clock_in_recomputes_session_hours(conn):
    select_cur = MagicMock()
    select_cur.fetchone.return_value = {
        "user_id": 7,
        "clock_in_at": datetime(2026, 9, 10, 5, 35),
        "clock_out_at": datetime(2026, 9, 10, 12, 0),
    }
    update_cur = MagicMock()
    update_cur.rowcount = 1
    conn.cursor.side_effect = [MagicMock(), select_cur, update_cur]

    with patch("backend.payroll_operations._session_in_org", return_value=True), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ), patch("backend.payroll_operations._sum_break_seconds", return_value=0), patch(
        "backend.payroll_operations._resync_role_segments_to_session_clock", return_value=True
    ) as sync, patch(
        "backend.payroll_operations._apply_time_record_role_tag"
    ) as tag:
        rec = update_time_record(
            conn,
            3,
            100,
            clock_in_at="2026-09-10 05:30:00",
            clock_out_at="2026-09-10 12:00:00",
        )

    assert rec["status"] == "pending_approval"
    assert rec["clock_in_at"] == datetime(2026, 9, 10, 5, 30)
    assert rec["clock_out_at"] == datetime(2026, 9, 10, 12, 0)
    tag.assert_not_called()
    sync.assert_called_once()
    sql, params = update_cur.execute.call_args[0]
    assert "net_work_seconds=%s" in sql
    # 5:30 → 12:00 = 6.5 hours = 23400 seconds
    assert 23400 in params


def test_resync_rejects_clock_in_past_first_segment_end(conn):
    select_cur = MagicMock()
    select_cur.fetchall.return_value = _multi_segments()
    conn.cursor.side_effect = [select_cur]

    with patch("backend.payroll_operations.table_exists", return_value=True), patch(
        "backend.payroll_operations._apply_time_record_role_tag"
    ) as tag:
        with pytest.raises(ValueError, match="first role segment"):
            _resync_role_segments_to_session_clock(
                conn,
                3,
                session_id=100,
                user_id=7,
                started_at=datetime(2026, 9, 10, 7, 10),
                ended_at=None,
            )
    tag.assert_not_called()
