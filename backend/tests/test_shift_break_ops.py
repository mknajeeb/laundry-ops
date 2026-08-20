"""Break start closes open role segment; resume starts new role."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from backend.shift_break_ops import BreakOpError, start_break_on_session


def test_start_break_closes_open_segment_then_inserts_break():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.lastrowid = 99
    cur.fetchone.return_value = {
        "id": 99,
        "shift_session_id": 55,
        "break_start_at": datetime(2026, 8, 20, 10, 0, 0),
        "break_end_at": None,
    }

    with patch("backend.ta_routes.get_open_break", return_value=None), patch(
        "backend.shift_job_tracking.close_open_job_segment"
    ) as close_seg, patch(
        "backend.shift_break_ops.eastern_now_naive",
        return_value=datetime(2026, 8, 20, 10, 0, 0),
    ):
        row = start_break_on_session(conn, 55)

    assert row["id"] == 99
    close_seg.assert_called_once()
    assert close_seg.call_args.kwargs.get("close_source") == "break_start"
    assert close_seg.call_args.args[1] == 55


def test_start_break_denied_when_already_on_break():
    conn = MagicMock()
    with patch("backend.ta_routes.get_open_break", return_value={"id": 1}):
        try:
            start_break_on_session(conn, 55)
            assert False, "expected BreakOpError"
        except BreakOpError as e:
            assert "already" in e.message.lower()


@patch("backend.attendance_pin_break.start_break_on_session")
@patch("backend.attendance_pin_break.get_open_break", return_value=None)
@patch("backend.attendance_pin_break._active_shift")
@patch("backend.attendance_pin_break.shared_device_attendance_enabled", return_value=True)
@patch("backend.attendance_pin_break.payroll_profiles_active", return_value=True)
@patch("backend.attendance_pin_break.fetch_organization_by_slug")
@patch("backend.attendance_pin_break.is_rate_limited", return_value=False)
def test_pin_break_start_requires_clocked_in(
    _rl, mock_org, _pp, _shared, mock_active, _ob, _start
):
    from backend.attendance_pin_break import perform_pin_break_start

    mock_org.return_value = {"id": 3, "slug": "veewash"}
    mock_active.return_value = None
    conn = MagicMock()
    with patch(
        "backend.attendance_pin_break.resolve_user_by_attendance_pin",
        return_value={"id": 10, "first_name": "Maria", "display_name": "Maria"},
    ), patch("backend.attendance_pin_break.record_pin_attempt"):
        body, status = perform_pin_break_start(
            conn, "veewash", "1234", lambda *_: [], "1.1.1.1"
        )
    assert status == 400
    assert "clocked in" in body["error"].lower()
