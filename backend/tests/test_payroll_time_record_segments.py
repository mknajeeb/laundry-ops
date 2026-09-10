"""Payroll time-record role segment edit/delete — surgical updates only."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

from backend.payroll_operations import (
    _segments_overlap,
    _validate_role_segment_windows,
    delete_time_record_segment,
    update_time_record_segment,
)


def _seg(
    seg_id,
    *,
    started,
    ended=None,
    category_id=1,
    role_id=2,
    category_name="Rinse WF",
    role_name="Operator",
    category_role_id=10,
):
    return {
        "id": seg_id,
        "shift_session_id": 100,
        "user_id": 7,
        "category_id": category_id,
        "role_id": role_id,
        "category_role_id": category_role_id,
        "category_code": "RINSE_WF",
        "role_code": "OPERATOR",
        "category_name_snapshot": category_name,
        "role_name_snapshot": role_name,
        "started_at": started,
        "ended_at": ended,
        "change_source": "switch",
    }


@pytest.fixture
def conn():
    return MagicMock()


def test_segments_overlap_rejects_interior_overlap():
    a0 = datetime(2026, 9, 10, 5, 35)
    a1 = datetime(2026, 9, 10, 7, 4)
    b0 = datetime(2026, 9, 10, 6, 50)
    b1 = datetime(2026, 9, 10, 7, 56)
    assert _segments_overlap(a0, a1, b0, b1)


def test_segments_touching_endpoints_not_overlap():
    a0 = datetime(2026, 9, 10, 5, 35)
    a1 = datetime(2026, 9, 10, 7, 4)
    b0 = datetime(2026, 9, 10, 7, 4)
    b1 = datetime(2026, 9, 10, 7, 56)
    assert not _segments_overlap(a0, a1, b0, b1)


def test_validate_gap_warning_not_error():
    segs = [
        _seg(1, started=datetime(2026, 9, 10, 5, 35), ended=datetime(2026, 9, 10, 7, 0)),
        _seg(2, started=datetime(2026, 9, 10, 7, 15), ended=datetime(2026, 9, 10, 8, 0)),
    ]
    warnings = _validate_role_segment_windows(
        segs,
        session_clock_in=datetime(2026, 9, 10, 5, 35),
        session_clock_out=datetime(2026, 9, 10, 8, 0),
    )
    assert any("Gap of 15 minute" in w for w in warnings)


def test_validate_overlap_raises():
    segs = [
        _seg(1, started=datetime(2026, 9, 10, 5, 35), ended=datetime(2026, 9, 10, 7, 10)),
        _seg(2, started=datetime(2026, 9, 10, 7, 0), ended=datetime(2026, 9, 10, 8, 0)),
    ]
    with pytest.raises(ValueError, match="overlap"):
        _validate_role_segment_windows(
            segs,
            session_clock_in=datetime(2026, 9, 10, 5, 35),
            session_clock_out=datetime(2026, 9, 10, 8, 0),
        )


def test_validate_end_before_start_raises():
    segs = [
        _seg(1, started=datetime(2026, 9, 10, 8, 0), ended=datetime(2026, 9, 10, 7, 0)),
    ]
    with pytest.raises(ValueError, match="after start"):
        _validate_role_segment_windows(
            segs,
            session_clock_in=datetime(2026, 9, 10, 5, 35),
            session_clock_out=None,
        )


def _session_row(*, clock_out=None, status="active", net=None):
    return {
        "id": 100,
        "user_id": 7,
        "clock_in_at": datetime(2026, 9, 10, 5, 35),
        "clock_out_at": clock_out,
        "status": status,
        "net_work_seconds": net,
        "total_break_seconds": 0,
    }


def test_edit_middle_segment_times_only(conn):
    segments = [
        _seg(1, started=datetime(2026, 9, 10, 5, 35), ended=datetime(2026, 9, 10, 7, 4), role_id=1, role_name="Sort"),
        _seg(2, started=datetime(2026, 9, 10, 7, 4), ended=datetime(2026, 9, 10, 7, 56), role_id=2),
        _seg(3, started=datetime(2026, 9, 10, 7, 56), ended=datetime(2026, 9, 10, 8, 30), category_id=2, role_id=2, category_name="Rinse HD"),
        _seg(4, started=datetime(2026, 9, 10, 8, 30), ended=None, role_id=3, role_name="Folder"),
    ]
    upd = MagicMock()
    upd.rowcount = 1
    conn.cursor.side_effect = [MagicMock(), upd, MagicMock()]

    with patch(
        "backend.payroll_operations._load_session_for_segment_edit",
        return_value=_session_row(),
    ), patch(
        "backend.payroll_operations._load_role_segments_for_session",
        return_value=segments,
    ), patch(
        "backend.payroll_operations._sync_session_current_assignment_from_segments"
    ) as sync, patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ):
        rec = update_time_record_segment(
            conn,
            3,
            100,
            2,
            started_at="2026-09-10 07:10:00",
            ended_at="2026-09-10 07:50:00",
            ended_at_provided=True,
        )

    assert rec["id"] == 2
    assert str(rec["started_at"]).startswith("2026-09-10T07:10:00")
    assert str(rec["ended_at"]).startswith("2026-09-10T07:50:00")
    assert str(rec["session"]["clock_in_at"]).startswith("2026-09-10T05:35:00")
    assert any("Gap" in w for w in rec["warnings"])
    sync.assert_called_once()
    sql, params = upd.execute.call_args[0]
    assert "UPDATE shift_job_segments" in sql
    assert params[0] == datetime(2026, 9, 10, 7, 10)
    assert params[1] == datetime(2026, 9, 10, 7, 50)
    assert params[-2:] == (2, 100)


def test_edit_middle_segment_overlap_rejected(conn):
    segments = [
        _seg(1, started=datetime(2026, 9, 10, 5, 35), ended=datetime(2026, 9, 10, 7, 4)),
        _seg(2, started=datetime(2026, 9, 10, 7, 4), ended=datetime(2026, 9, 10, 7, 56)),
        _seg(3, started=datetime(2026, 9, 10, 7, 56), ended=datetime(2026, 9, 10, 8, 30)),
    ]
    with patch(
        "backend.payroll_operations._load_session_for_segment_edit",
        return_value=_session_row(clock_out=datetime(2026, 9, 10, 8, 30), status="completed", net=10500),
    ), patch(
        "backend.payroll_operations._load_role_segments_for_session",
        return_value=segments,
    ):
        with pytest.raises(ValueError, match="overlap"):
            update_time_record_segment(
                conn,
                3,
                100,
                2,
                started_at="2026-09-10 07:00:00",
                ended_at="2026-09-10 08:00:00",
                ended_at_provided=True,
            )


def test_edit_first_segment_does_not_change_check_in(conn):
    segments = [
        _seg(1, started=datetime(2026, 9, 10, 5, 35), ended=datetime(2026, 9, 10, 7, 4), role_id=1),
        _seg(2, started=datetime(2026, 9, 10, 7, 4), ended=None, role_id=3, role_name="Folder"),
    ]
    upd = MagicMock()
    upd.rowcount = 1
    conn.cursor.side_effect = [MagicMock(), upd, MagicMock()]

    with patch(
        "backend.payroll_operations._load_session_for_segment_edit",
        return_value=_session_row(),
    ), patch(
        "backend.payroll_operations._load_role_segments_for_session",
        return_value=segments,
    ), patch(
        "backend.payroll_operations._sync_session_current_assignment_from_segments"
    ), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ):
        rec = update_time_record_segment(
            conn,
            3,
            100,
            1,
            started_at="2026-09-10 05:50:00",
            ended_at="2026-09-10 07:04:00",
            ended_at_provided=True,
        )

    assert str(rec["session"]["clock_in_at"]).startswith("2026-09-10T05:35:00")
    assert str(rec["started_at"]).startswith("2026-09-10T05:50:00")
    assert any("check-in" in w.lower() for w in rec["warnings"])


def test_edit_open_segment_role_and_start(conn):
    segments = [
        _seg(1, started=datetime(2026, 9, 10, 5, 35), ended=datetime(2026, 9, 10, 8, 30), role_id=1),
        _seg(4, started=datetime(2026, 9, 10, 8, 30), ended=None, role_id=3, role_name="Folder"),
    ]
    assignment = {
        "id": 99,
        "category_id": 1,
        "role_id": 5,
        "category_code": "RINSE_WF",
        "role_code": "SORT",
        "category_name": "Rinse WF",
        "role_name": "Sort",
    }
    assign_cur = MagicMock()
    upd = MagicMock()
    upd.rowcount = 1
    conn.cursor.side_effect = [assign_cur, MagicMock(), upd, MagicMock()]

    with patch(
        "backend.payroll_operations._load_session_for_segment_edit",
        return_value=_session_row(),
    ), patch(
        "backend.payroll_operations._load_role_segments_for_session",
        return_value=segments,
    ), patch(
        "backend.shift_job_tracking.ensure_shift_job_tracking_schema"
    ), patch(
        "backend.shift_job_tracking.resolve_active_assignment",
        return_value=assignment,
    ), patch(
        "backend.payroll_operations._sync_session_current_assignment_from_segments"
    ) as sync, patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ):
        rec = update_time_record_segment(
            conn,
            3,
            100,
            4,
            category_id=1,
            role_id=5,
            started_at="2026-09-10 08:45:00",
            ended_at="",
            ended_at_provided=True,
        )

    assert rec["ended_at"] is None
    assert rec["role_id"] == 5
    assert rec["display_label"] == "Rinse WF — Sort"
    assert str(rec["session"]["clock_in_at"]).startswith("2026-09-10T05:35:00")
    assert rec["session"]["status"] == "open"
    sync.assert_called_once()
    proposed = sync.call_args[0][2]
    open_seg = next(s for s in proposed if s.get("ended_at") is None)
    assert int(open_seg["role_id"]) == 5
    assert open_seg["started_at"] == datetime(2026, 9, 10, 8, 45)


def test_delete_middle_segment_keeps_parent_attendance(conn):
    segments = [
        _seg(1, started=datetime(2026, 9, 10, 5, 35), ended=datetime(2026, 9, 10, 7, 4)),
        _seg(2, started=datetime(2026, 9, 10, 7, 4), ended=datetime(2026, 9, 10, 7, 56)),
        _seg(3, started=datetime(2026, 9, 10, 7, 56), ended=datetime(2026, 9, 10, 8, 30)),
        _seg(4, started=datetime(2026, 9, 10, 8, 30), ended=None, role_id=3),
    ]
    delete_cur = MagicMock()
    delete_cur.rowcount = 1
    conn.cursor.side_effect = [delete_cur, MagicMock()]

    with patch(
        "backend.payroll_operations._load_session_for_segment_edit",
        return_value=_session_row(),
    ), patch(
        "backend.payroll_operations._load_role_segments_for_session",
        return_value=segments,
    ), patch(
        "backend.payroll_operations._sync_session_current_assignment_from_segments"
    ) as sync, patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ):
        result = delete_time_record_segment(conn, 3, 100, 2)

    assert result["ok"] is True
    assert result["deleted_segment_id"] == 2
    assert result["shift_session_id"] == 100
    assert result["remaining_segment_count"] == 3
    assert result["session"]["id"] == 100
    assert any("Gap" in w for w in result["warnings"])
    delete_cur.execute.assert_called_once_with(
        "DELETE FROM shift_job_segments WHERE id=%s AND shift_session_id=%s",
        (2, 100),
    )
    # Must never DELETE the parent shift_sessions row
    assert delete_cur.execute.call_args != call(
        "DELETE FROM shift_sessions WHERE id=%s AND organization_id=%s",
        (100, 3),
    )
    remaining = sync.call_args[0][2]
    assert [int(s["id"]) for s in remaining] == [1, 3, 4]


def test_delete_segment_preserves_session_hours_in_response(conn):
    """Payroll hours remain session-driven; response still exposes session net hours."""
    segments = [
        _seg(1, started=datetime(2026, 9, 10, 5, 35), ended=datetime(2026, 9, 10, 12, 0)),
        _seg(2, started=datetime(2026, 9, 10, 12, 0), ended=datetime(2026, 9, 10, 14, 0)),
    ]
    delete_cur = MagicMock()
    delete_cur.rowcount = 1
    conn.cursor.side_effect = [delete_cur, MagicMock()]
    session = _session_row(
        clock_out=datetime(2026, 9, 10, 14, 0),
        status="completed",
        net=8 * 3600,
    )

    with patch(
        "backend.payroll_operations._load_session_for_segment_edit",
        return_value=session,
    ), patch(
        "backend.payroll_operations._load_role_segments_for_session",
        return_value=segments,
    ), patch(
        "backend.payroll_operations._sync_session_current_assignment_from_segments"
    ), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ):
        result = delete_time_record_segment(conn, 3, 100, 2)

    assert result["session"]["approved_hours"] == 8.0
    assert result["session"]["net_work_seconds"] == 28800
    assert str(result["session"]["clock_in_at"]).startswith("2026-09-10T05:35:00")
    assert str(result["session"]["clock_out_at"]).startswith("2026-09-10T14:00:00")


def _jennifer_style_segments():
    """Production-shaped timeline (Jennifer 2026-09-10) with sub-minute boundaries."""
    return [
        _seg(
            975,
            started=datetime(2026, 9, 10, 5, 35, 27),
            ended=datetime(2026, 9, 10, 7, 4, 23),
            role_id=1,
            role_name="Sort",
        ),
        _seg(
            977,
            started=datetime(2026, 9, 10, 7, 4, 23),
            ended=datetime(2026, 9, 10, 7, 56, 45),
            role_id=3,
            role_name="Operator",
        ),
        _seg(
            982,
            started=datetime(2026, 9, 10, 7, 56, 45),
            ended=datetime(2026, 9, 10, 8, 30, 51),
            category_id=2,
            role_id=3,
            category_name="Rinse HD",
            role_name="Operator",
            category_role_id=20,
        ),
        _seg(
            985,
            started=datetime(2026, 9, 10, 9, 7, 0),
            ended=datetime(2026, 9, 10, 12, 43, 0),
            role_id=2,
            role_name="Folder",
        ),
        _seg(
            994,
            started=datetime(2026, 9, 10, 12, 54, 23),
            ended=None,
            role_id=2,
            role_name="Folder",
        ),
    ]


@pytest.mark.parametrize(
    "new_end,expect_ok",
    [
        ("2026-09-10 09:06:00", True),
        ("2026-09-10 09:07:00", True),
        ("2026-09-10 09:08:00", False),
    ],
)
def test_extend_hd_segment_gap_and_touch_vs_overlap(conn, new_end, expect_ok):
    """7:56–8:30 → end at 9:06/9:07 pass; 9:08 overlaps next 9:07–12:43."""
    segments = _jennifer_style_segments()
    # Frontend minute truncation would send start 07:56:00; backend must restore :45.
    upd = MagicMock()
    upd.rowcount = 1
    conn.cursor.side_effect = [MagicMock(), upd, MagicMock()]

    with patch(
        "backend.payroll_operations._load_session_for_segment_edit",
        return_value=_session_row(),
    ), patch(
        "backend.payroll_operations._load_role_segments_for_session",
        return_value=segments,
    ), patch(
        "backend.payroll_operations._sync_session_current_assignment_from_segments"
    ), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ):
        if expect_ok:
            rec = update_time_record_segment(
                conn,
                3,
                100,
                982,
                started_at="2026-09-10 07:56:00",
                ended_at=new_end,
                ended_at_provided=True,
            )
            assert str(rec["started_at"]).startswith("2026-09-10T07:56:45")
            assert any("Gap" in w for w in rec["warnings"]) or new_end.endswith("09:07:00")
        else:
            with pytest.raises(ValueError, match="overlap"):
                update_time_record_segment(
                    conn,
                    3,
                    100,
                    982,
                    started_at="2026-09-10 07:56:00",
                    ended_at=new_end,
                    ended_at_provided=True,
                )


def test_minute_truncation_without_coalesce_would_overlap_prior():
    """Document the exact false-overlap pair before seconds coalesce."""
    prior_end = datetime(2026, 9, 10, 7, 56, 45)
    truncated_start = datetime(2026, 9, 10, 7, 56, 0)
    proposed_end = datetime(2026, 9, 10, 9, 6, 0)
    assert _segments_overlap(
        datetime(2026, 9, 10, 7, 4, 23),
        prior_end,
        truncated_start,
        proposed_end,
    )
    from backend.payroll_operations import _coalesce_same_minute_seconds

    restored = _coalesce_same_minute_seconds(truncated_start, datetime(2026, 9, 10, 7, 56, 45))
    assert restored == datetime(2026, 9, 10, 7, 56, 45)
    assert not _segments_overlap(
        datetime(2026, 9, 10, 7, 4, 23),
        prior_end,
        restored,
        proposed_end,
    )


def test_edited_segment_excludes_itself_from_overlap(conn):
    segments = _jennifer_style_segments()
    upd = MagicMock()
    upd.rowcount = 1
    conn.cursor.side_effect = [MagicMock(), upd, MagicMock()]

    with patch(
        "backend.payroll_operations._load_session_for_segment_edit",
        return_value=_session_row(),
    ), patch(
        "backend.payroll_operations._load_role_segments_for_session",
        return_value=segments,
    ), patch(
        "backend.payroll_operations._sync_session_current_assignment_from_segments"
    ), patch(
        "backend.payroll_operations.table_has_column", return_value=False
    ):
        # Extending past own old end (8:30:51) must not self-conflict.
        rec = update_time_record_segment(
            conn,
            3,
            100,
            982,
            started_at="2026-09-10 07:56:45",
            ended_at="2026-09-10 09:06:00",
            ended_at_provided=True,
        )
    assert rec["id"] == 982


def test_touching_edges_allowed_same_instant():
    a0, a1 = datetime(2026, 9, 10, 7, 56, 45), datetime(2026, 9, 10, 9, 7, 0)
    b0, b1 = datetime(2026, 9, 10, 9, 7, 0), datetime(2026, 9, 10, 12, 43, 0)
    assert not _segments_overlap(a0, a1, b0, b1)
    warnings = _validate_role_segment_windows(
        [
            {"id": 1, "started_at": a0, "ended_at": a1},
            {"id": 2, "started_at": b0, "ended_at": b1},
        ],
        session_clock_in=datetime(2026, 9, 10, 7, 56, 45),
        session_clock_out=None,
    )
    assert not any("overlap" in w.lower() for w in warnings)
    assert not any("Gap of" in w and "between role segments" in w for w in warnings)


def test_gap_warning_non_blocking_for_one_minute_gap():
    warnings = _validate_role_segment_windows(
        [
            {
                "id": 1,
                "started_at": datetime(2026, 9, 10, 7, 56, 45),
                "ended_at": datetime(2026, 9, 10, 9, 6, 0),
            },
            {
                "id": 2,
                "started_at": datetime(2026, 9, 10, 9, 7, 0),
                "ended_at": datetime(2026, 9, 10, 12, 43, 0),
            },
        ],
        session_clock_in=datetime(2026, 9, 10, 5, 35, 27),
        session_clock_out=None,
    )
    assert any("Gap of 1 minute" in w for w in warnings)


def test_open_last_segment_does_not_false_overlap_earlier_edit():
    segs = [
        {
            "id": 1,
            "started_at": datetime(2026, 9, 10, 7, 56, 45),
            "ended_at": datetime(2026, 9, 10, 9, 6, 0),
        },
        {
            "id": 2,
            "started_at": datetime(2026, 9, 10, 9, 7, 0),
            "ended_at": datetime(2026, 9, 10, 12, 43, 0),
        },
        {
            "id": 3,
            "started_at": datetime(2026, 9, 10, 12, 54, 23),
            "ended_at": None,
        },
    ]
    warnings = _validate_role_segment_windows(
        segs,
        session_clock_in=datetime(2026, 9, 10, 5, 35, 27),
        session_clock_out=None,
    )
    assert all("overlap" not in w.lower() for w in warnings)
