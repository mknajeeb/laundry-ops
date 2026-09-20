"""Payroll Time Records — break visibility, editing, conflicts, approval safety."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.payroll_time_record_breaks import (
    BreakConflictError,
    OpenBreakApprovalError,
    apply_break_conflict_resolution,
    assert_no_open_break_for_approval,
    attach_breaks_to_time_records,
    completed_break_seconds,
    create_session_break,
    delete_session_break,
    find_break_resume_sync_candidate,
    raise_segment_break_conflict,
    recompute_session_work_seconds,
    segment_break_conflicts,
    update_session_break,
    close_open_session_break,
)
from backend.payroll_operations import (
    approve_time_record,
    update_time_record_segment,
)


YESENIA_CLOCK_IN = datetime(2026, 9, 7, 5, 45, 0)
YESENIA_CLOCK_OUT = datetime(2026, 9, 7, 14, 45, 0)
YESENIA_BREAK_START = datetime(2026, 9, 7, 9, 16, 58)
YESENIA_BREAK_END = datetime(2026, 9, 7, 13, 14, 30)
YESENIA_BREAK_SEC = int((YESENIA_BREAK_END - YESENIA_BREAK_START).total_seconds())  # 14252
YESENIA_ELAPSED = int((YESENIA_CLOCK_OUT - YESENIA_CLOCK_IN).total_seconds())  # 32400
YESENIA_NET = YESENIA_ELAPSED - YESENIA_BREAK_SEC  # 18148 → 5.04h


def test_yesenia_equivalent_payable_before_and_after_break_delete():
    """Synthetic Yesenia shape: 05:45–14:45 + ~4h erroneous break → 5.04; delete → 9.00.

    Does not touch production session 1321.
    """
    assert YESENIA_BREAK_SEC == 14252
    assert YESENIA_ELAPSED == 9 * 3600
    assert round(YESENIA_NET / 3600.0, 2) == 5.04
    assert completed_break_seconds(
        [
            {
                "id": 73,
                "break_start_at": YESENIA_BREAK_START,
                "break_end_at": YESENIA_BREAK_END,
            }
        ]
    ) == 14252
    assert completed_break_seconds([]) == 0
    assert round(YESENIA_ELAPSED / 3600.0, 2) == 9.0


def test_recompute_yesenia_shape_then_delete_restores_elapsed():
    conn = MagicMock()
    session = {
        "id": 9001321,
        "clock_in_at": YESENIA_CLOCK_IN,
        "clock_out_at": YESENIA_CLOCK_OUT,
        "status": "completed",
        "net_work_seconds": YESENIA_NET,
        "total_break_seconds": YESENIA_BREAK_SEC,
        "payroll_hours_approved": 0,
    }
    breaks = [
        {
            "id": 73,
            "shift_session_id": 9001321,
            "break_start_at": YESENIA_BREAK_START,
            "break_end_at": YESENIA_BREAK_END,
        }
    ]
    sel = MagicMock()
    sel.fetchone.return_value = dict(session)
    upd = MagicMock()
    conn.cursor.side_effect = lambda *a, **k: sel if k.get("dictionary") else upd

    with patch(
        "backend.payroll_time_record_breaks.load_session_breaks", return_value=breaks
    ), patch(
        "backend.payroll_operations.ensure_payroll_hours_approved_column"
    ), patch(
        "backend.ta_helpers.table_has_column", return_value=False
    ):
        out = recompute_session_work_seconds(conn, 9001321)

    assert out["total_break_seconds"] == 14252
    assert out["net_work_seconds"] == 18148
    assert out["approved_hours"] == 5.04

    with patch(
        "backend.payroll_time_record_breaks.load_session_breaks", return_value=[]
    ), patch(
        "backend.payroll_operations.ensure_payroll_hours_approved_column"
    ), patch(
        "backend.ta_helpers.table_has_column", return_value=False
    ):
        sel.fetchone.return_value = {
            **session,
            "net_work_seconds": 18148,
            "total_break_seconds": 14252,
        }
        after = recompute_session_work_seconds(conn, 9001321)

    assert after["total_break_seconds"] == 0
    assert after["net_work_seconds"] == 32400
    assert after["approved_hours"] == 9.0


def test_completed_break_edit_validates_and_recomputes():
    conn = MagicMock()
    session = {
        "id": 50,
        "user_id": 7,
        "clock_in_at": datetime(2026, 9, 7, 5, 45),
        "clock_out_at": datetime(2026, 9, 7, 14, 45),
        "status": "completed",
        "net_work_seconds": 30000,
        "total_break_seconds": 2400,
        "payroll_hours_approved": 0,
    }
    breaks = [
        {
            "id": 8,
            "break_start_at": datetime(2026, 9, 7, 12, 0),
            "break_end_at": datetime(2026, 9, 7, 12, 40),
        }
    ]
    with patch(
        "backend.payroll_time_record_breaks._load_session_clocks", return_value=session
    ), patch(
        "backend.payroll_time_record_breaks.load_session_breaks", return_value=breaks
    ), patch(
        "backend.payroll_time_record_breaks.recompute_session_work_seconds",
        return_value={
            "id": 50,
            "total_break_seconds": 1800,
            "net_work_seconds": 30600,
            "approved_hours": 8.5,
            "hours_changed": True,
            "approval_cleared": False,
            "has_open_break": False,
        },
    ) as recom, patch(
        "backend.payroll_time_record_breaks._session_response_after_break_change",
        return_value={"id": 50, "approved_hours": 8.5},
    ):
        out = update_session_break(
            conn,
            3,
            50,
            8,
            break_start_at="2026-09-07 12:00:00",
            break_end_at="2026-09-07 12:30:00",
            end_provided=True,
        )
    assert out["break"]["duration_seconds"] == 1800
    recom.assert_called_once_with(conn, 50)


def test_add_break_rejects_overlap_and_creates_when_valid():
    conn = MagicMock()
    session = {
        "id": 50,
        "user_id": 7,
        "clock_in_at": datetime(2026, 9, 7, 5, 45),
        "clock_out_at": datetime(2026, 9, 7, 14, 45),
        "status": "completed",
        "net_work_seconds": 32400,
        "total_break_seconds": 0,
        "payroll_hours_approved": 0,
    }
    existing = [
        {
            "id": 1,
            "break_start_at": datetime(2026, 9, 7, 10, 0),
            "break_end_at": datetime(2026, 9, 7, 10, 30),
        }
    ]
    with patch(
        "backend.payroll_time_record_breaks._load_session_clocks", return_value=session
    ), patch(
        "backend.payroll_time_record_breaks.load_session_breaks", return_value=existing
    ):
        with pytest.raises(ValueError, match="overlaps"):
            create_session_break(
                conn,
                3,
                50,
                break_start_at="2026-09-07 10:15:00",
                break_end_at="2026-09-07 10:45:00",
            )

    insert = MagicMock()
    insert.lastrowid = 99
    conn.cursor.return_value = insert
    with patch(
        "backend.payroll_time_record_breaks._load_session_clocks", return_value=session
    ), patch(
        "backend.payroll_time_record_breaks.load_session_breaks", return_value=existing
    ), patch(
        "backend.payroll_time_record_breaks.recompute_session_work_seconds",
        return_value={
            "id": 50,
            "total_break_seconds": 3600,
            "net_work_seconds": 28800,
            "approved_hours": 8.0,
            "hours_changed": True,
            "approval_cleared": False,
            "has_open_break": False,
        },
    ), patch(
        "backend.payroll_time_record_breaks._session_response_after_break_change",
        return_value={"id": 50},
    ):
        out = create_session_break(
            conn,
            3,
            50,
            break_start_at="2026-09-07 11:00:00",
            break_end_at="2026-09-07 11:30:00",
        )
    assert out["break"]["id"] == 99


def test_overlapping_segment_blocked_without_resolution():
    segments = [
        {
            "id": 2,
            "started_at": datetime(2026, 9, 7, 9, 17),
            "ended_at": datetime(2026, 9, 7, 14, 45),
            "change_source": "payroll_manual",
        }
    ]
    breaks = [
        {
            "id": 73,
            "break_start_at": YESENIA_BREAK_START,
            "break_end_at": YESENIA_BREAK_END,
        }
    ]
    conflicts = segment_break_conflicts(segments, breaks)
    assert conflicts
    assert conflicts[0]["break_id"] == 73
    with pytest.raises(BreakConflictError) as ei:
        raise_segment_break_conflict(
            conflicts=conflicts,
            sync_candidate=None,
            proposed_start=segments[0]["started_at"],
            proposed_end=segments[0]["ended_at"],
        )
    assert ei.value.payload["error"] == "segment_break_conflict"
    assert any(r["key"] == "delete_break" for r in ei.value.payload["resolutions"])


def test_explicit_overlap_resolution_delete_break():
    conn = MagicMock()
    with patch(
        "backend.payroll_time_record_breaks.load_session_breaks",
        return_value=[
            {
                "id": 73,
                "break_start_at": YESENIA_BREAK_START,
                "break_end_at": YESENIA_BREAK_END,
            }
        ],
    ):
        apply_break_conflict_resolution(
            conn,
            50,
            resolution="delete_break",
            break_id=73,
            segment_started_at=datetime(2026, 9, 7, 9, 17),
        )
    sql, params = conn.cursor.return_value.execute.call_args[0]
    assert "DELETE FROM shift_breaks" in sql
    assert params == (73, 50)


def test_break_resume_synchronization_offer_and_apply():
    segment = {
        "id": 5,
        "change_source": "break_resume",
        "started_at": datetime(2026, 9, 7, 13, 14, 30),
    }
    breaks = [
        {
            "id": 73,
            "break_start_at": YESENIA_BREAK_START,
            "break_end_at": YESENIA_BREAK_END,
        }
    ]
    cand = find_break_resume_sync_candidate(
        segment, breaks, previous_start=datetime(2026, 9, 7, 13, 14, 30)
    )
    assert cand and int(cand["id"]) == 73

    conn = MagicMock()
    with patch(
        "backend.payroll_time_record_breaks.load_session_breaks", return_value=breaks
    ):
        apply_break_conflict_resolution(
            conn,
            50,
            resolution="sync_break_end",
            break_id=73,
            segment_started_at=datetime(2026, 9, 7, 13, 0, 0),
        )
    sql, params = conn.cursor.return_value.execute.call_args[0]
    assert "break_end_at=%s" in sql
    assert params[0] == datetime(2026, 9, 7, 13, 0, 0)


def test_open_break_blocks_approval():
    conn = MagicMock()
    with patch(
        "backend.payroll_time_record_breaks.load_session_breaks",
        return_value=[
            {
                "id": 9,
                "break_start_at": datetime(2026, 9, 7, 12, 0),
                "break_end_at": None,
            }
        ],
    ):
        with pytest.raises(OpenBreakApprovalError) as ei:
            assert_no_open_break_for_approval(conn, 50)
    assert ei.value.payload["error"] == "open_break_blocks_approval"

    with patch("backend.payroll_operations._session_in_org", return_value=True), patch(
        "backend.payroll_time_record_breaks.assert_no_open_break_for_approval",
        side_effect=OpenBreakApprovalError("open", {"error": "open_break_blocks_approval"}),
    ):
        with pytest.raises(OpenBreakApprovalError):
            approve_time_record(conn, 3, 50)


def test_close_and_remove_open_break():
    conn = MagicMock()
    session = {
        "id": 50,
        "user_id": 7,
        "clock_in_at": datetime(2026, 9, 7, 5, 45),
        "clock_out_at": datetime(2026, 9, 7, 14, 45),
        "status": "completed",
        "net_work_seconds": 32400,
        "total_break_seconds": 0,
        "payroll_hours_approved": 0,
    }
    open_break = [
        {
            "id": 9,
            "break_start_at": datetime(2026, 9, 7, 12, 0),
            "break_end_at": None,
        }
    ]
    with patch(
        "backend.payroll_time_record_breaks._load_session_clocks", return_value=session
    ), patch(
        "backend.payroll_time_record_breaks.load_session_breaks", return_value=open_break
    ), patch(
        "backend.payroll_time_record_breaks.recompute_session_work_seconds",
        return_value={
            "id": 50,
            "total_break_seconds": 1800,
            "net_work_seconds": 30600,
            "approved_hours": 8.5,
            "hours_changed": True,
            "approval_cleared": False,
            "has_open_break": False,
        },
    ), patch(
        "backend.payroll_time_record_breaks._session_response_after_break_change",
        return_value={"id": 50, "has_open_break": False},
    ):
        closed = close_open_session_break(
            conn, 3, 50, 9, break_end_at="2026-09-07 12:30:00"
        )
    assert closed["break"]["status"] == "completed"

    with patch(
        "backend.payroll_time_record_breaks._load_session_clocks", return_value=session
    ), patch(
        "backend.payroll_time_record_breaks.load_session_breaks", return_value=open_break
    ), patch(
        "backend.payroll_time_record_breaks.recompute_session_work_seconds",
        return_value={
            "id": 50,
            "total_break_seconds": 0,
            "net_work_seconds": 32400,
            "approved_hours": 9.0,
            "hours_changed": True,
            "approval_cleared": False,
            "has_open_break": False,
        },
    ), patch(
        "backend.payroll_time_record_breaks._session_response_after_break_change",
        return_value={"id": 50},
    ):
        deleted = delete_session_break(conn, 3, 50, 9)
    assert deleted["deleted_break_id"] == 9


def test_approved_session_hour_change_clears_only_that_approval():
    conn = MagicMock()
    sel = MagicMock()
    sel.fetchone.return_value = {
        "id": 50,
        "clock_in_at": YESENIA_CLOCK_IN,
        "clock_out_at": YESENIA_CLOCK_OUT,
        "status": "completed",
        "net_work_seconds": YESENIA_NET,
        "total_break_seconds": YESENIA_BREAK_SEC,
        "payroll_hours_approved": 1,
    }
    upd = MagicMock()
    conn.cursor.side_effect = lambda *a, **k: sel if k.get("dictionary") else upd

    with patch(
        "backend.payroll_time_record_breaks.load_session_breaks", return_value=[]
    ), patch(
        "backend.payroll_operations.ensure_payroll_hours_approved_column"
    ), patch(
        "backend.ta_helpers.table_has_column", return_value=False
    ):
        out = recompute_session_work_seconds(conn, 50)

    assert out["approval_cleared"] is True
    assert out["net_work_seconds"] == 32400
    sql, params = upd.execute.call_args[0]
    assert "payroll_hours_approved=0" in sql
    assert params[-1] == 50
    assert "WHERE id=%s" in sql


def test_no_break_historical_session_unchanged_on_attach():
    items = [
        {
            "id": 10,
            "clock_in_at": datetime(2026, 9, 1, 8, 0),
            "clock_out_at": datetime(2026, 9, 1, 16, 0),
            "break_seconds": 0,
            "role_segments": [],
        }
    ]
    conn = MagicMock()
    with patch("backend.payroll_time_record_breaks.table_exists", return_value=True):
        cur = MagicMock()
        cur.fetchall.return_value = []
        conn.cursor.return_value = cur
        attach_breaks_to_time_records(conn, items)
    assert items[0]["breaks"] == []
    assert items[0]["has_open_break"] is False
    assert items[0]["payable_composition"] is None
    assert items[0]["elapsed_seconds"] == 8 * 3600


def test_break_mutation_does_not_touch_frozen_payout_lines():
    """Break edits update shift_sessions only — frozen payout lines stay frozen."""
    conn = MagicMock()
    session = {
        "id": 50,
        "user_id": 7,
        "clock_in_at": YESENIA_CLOCK_IN,
        "clock_out_at": YESENIA_CLOCK_OUT,
        "status": "completed",
        "net_work_seconds": YESENIA_NET,
        "total_break_seconds": YESENIA_BREAK_SEC,
        "payroll_hours_approved": 0,
    }
    breaks = [
        {
            "id": 73,
            "break_start_at": YESENIA_BREAK_START,
            "break_end_at": YESENIA_BREAK_END,
        }
    ]
    with patch(
        "backend.payroll_time_record_breaks._load_session_clocks", return_value=session
    ), patch(
        "backend.payroll_time_record_breaks.load_session_breaks", return_value=breaks
    ), patch(
        "backend.payroll_time_record_breaks.recompute_session_work_seconds",
        return_value={
            "id": 50,
            "total_break_seconds": 0,
            "net_work_seconds": 32400,
            "approved_hours": 9.0,
            "hours_changed": True,
            "approval_cleared": False,
            "has_open_break": False,
        },
    ), patch(
        "backend.payroll_time_record_breaks._session_response_after_break_change",
        return_value={"id": 50},
    ):
        delete_session_break(conn, 3, 50, 73)

    for args in conn.cursor.return_value.execute.call_args_list:
        sql = args[0][0]
        assert "payout_batch" not in sql.lower()


def test_segment_edit_with_resolution_then_recompute():
    segments = [
        {
            "id": 1,
            "shift_session_id": 100,
            "user_id": 7,
            "category_id": 1,
            "role_id": 2,
            "category_role_id": 10,
            "category_code": "RINSE_WF",
            "role_code": "FOLDER",
            "category_name_snapshot": "Rinse WF",
            "role_name_snapshot": "Folder",
            "started_at": datetime(2026, 9, 7, 13, 14, 30),
            "ended_at": datetime(2026, 9, 7, 14, 45),
            "change_source": "break_resume",
        }
    ]
    session = {
        "id": 100,
        "user_id": 7,
        "clock_in_at": YESENIA_CLOCK_IN,
        "clock_out_at": YESENIA_CLOCK_OUT,
        "status": "completed",
        "net_work_seconds": YESENIA_NET,
        "total_break_seconds": YESENIA_BREAK_SEC,
    }
    breaks = [
        {
            "id": 73,
            "break_start_at": YESENIA_BREAK_START,
            "break_end_at": YESENIA_BREAK_END,
        }
    ]
    upd = MagicMock()
    upd.rowcount = 1
    conn = MagicMock()
    conn.cursor.side_effect = [MagicMock(), upd, MagicMock()]

    with patch(
        "backend.payroll_operations._load_session_for_segment_edit", return_value=session
    ), patch(
        "backend.payroll_operations._load_role_segments_for_session", return_value=segments
    ), patch(
        "backend.payroll_time_record_breaks.load_session_breaks", return_value=breaks
    ), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ):
        with pytest.raises(BreakConflictError):
            update_time_record_segment(
                conn,
                3,
                100,
                1,
                started_at="2026-09-07 09:17:00",
                ended_at="2026-09-07 14:45:00",
                ended_at_provided=True,
            )

    conn2 = MagicMock()
    upd2 = MagicMock()
    upd2.rowcount = 1
    conn2.cursor.side_effect = [MagicMock(), upd2, MagicMock()]
    with patch(
        "backend.payroll_operations._load_session_for_segment_edit", return_value=session
    ), patch(
        "backend.payroll_operations._load_role_segments_for_session", return_value=segments
    ), patch(
        "backend.payroll_time_record_breaks.load_session_breaks",
        side_effect=[breaks, []],
    ), patch(
        "backend.payroll_time_record_breaks.apply_break_conflict_resolution"
    ) as apply_res, patch(
        "backend.payroll_operations._sync_session_current_assignment_from_segments"
    ), patch(
        "backend.payroll_operations._sync_session_clock_out_from_last_segment"
    ), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ), patch(
        "backend.payroll_time_record_breaks.recompute_session_work_seconds",
        return_value={
            "id": 100,
            "total_break_seconds": 0,
            "net_work_seconds": 32400,
            "approved_hours": 9.0,
            "hours_changed": True,
            "approval_cleared": False,
            "has_open_break": False,
        },
    ):
        rec = update_time_record_segment(
            conn2,
            3,
            100,
            1,
            started_at="2026-09-07 09:17:00",
            ended_at="2026-09-07 14:45:00",
            ended_at_provided=True,
            break_conflict_resolution="delete_break",
            resolve_break_id=73,
        )
    apply_res.assert_called()
    assert rec["break_conflict_resolved"] is True
    assert rec["session"]["approved_hours"] == 9.0


def test_reopen_paid_for_correction_still_passes():
    """Existing paid-batch correction workflow regression remains green."""
    from backend.tests.test_reopen_paid_for_correction import (
        test_reopen_fully_paid_reverses_every_paid_line_and_keeps_deductions,
    )

    test_reopen_fully_paid_reverses_every_paid_line_and_keeps_deductions()
