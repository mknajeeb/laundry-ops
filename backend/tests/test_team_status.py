"""Team Status builder unit tests (no DB)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from backend.team_status import (
    _break_seconds_for_session,
    _build_timeline,
    _role_summary_from_segments,
    _session_worked_seconds,
)


def test_session_worked_excludes_breaks_for_active():
    now = datetime(2026, 8, 20, 12, 0, 0)
    session = {
        "status": "active",
        "clock_in_at": datetime(2026, 8, 20, 6, 0, 0),
        "clock_out_at": None,
        "net_work_seconds": None,
    }
    breaks = [
        {
            "break_start_at": datetime(2026, 8, 20, 9, 0, 0),
            "break_end_at": datetime(2026, 8, 20, 9, 30, 0),
        }
    ]
    worked, on_break, _ = _session_worked_seconds(session, breaks, now=now)
    # 6h gross - 30m break = 5.5h
    assert worked == 5 * 3600 + 30 * 60
    assert on_break is False


def test_open_break_marks_on_break_and_counts_live():
    now = datetime(2026, 8, 20, 11, 0, 0)
    session = {
        "status": "active",
        "clock_in_at": datetime(2026, 8, 20, 6, 0, 0),
        "clock_out_at": None,
    }
    breaks = [
        {
            "break_start_at": datetime(2026, 8, 20, 10, 30, 0),
            "break_end_at": None,
        }
    ]
    worked, on_break, open_start = _session_worked_seconds(session, breaks, now=now)
    assert on_break is True
    assert open_start == datetime(2026, 8, 20, 10, 30, 0)
    assert worked == 4 * 3600 + 30 * 60  # 5h gross - 30m open break


def test_completed_prefers_net_work_seconds():
    now = datetime(2026, 8, 20, 18, 0, 0)
    session = {
        "status": "completed",
        "clock_in_at": datetime(2026, 8, 20, 6, 0, 0),
        "clock_out_at": datetime(2026, 8, 20, 14, 0, 0),
        "net_work_seconds": 7 * 3600 + 30 * 60,
    }
    worked, on_break, _ = _session_worked_seconds(session, [], now=now)
    assert worked == 7 * 3600 + 30 * 60
    assert on_break is False


def test_role_summary_uses_friendly_labels_and_keeps_sort():
    now = datetime(2026, 8, 20, 12, 0, 0)
    segments = [
        {
            "role_code": "OPERATOR",
            "role_name_snapshot": "Operator",
            "duration_seconds": 100,
        },
        {
            "role_code": "SORT",
            "role_name_snapshot": "Sort",
            "duration_seconds": 200,
        },
        {
            "role_code": "FOLDER",
            "role_name_snapshot": "Folder",
            "duration_seconds": 300,
        },
    ]
    summary = _role_summary_from_segments(segments, [], now=now)
    labels = [r["label"] for r in summary if r["kind"] == "role"]
    assert labels == ["Fold", "Sort", "Wash-Dry"]
    assert "Operator" not in labels
    assert "Folder" not in labels


def test_timeline_interleaves_roles_and_breaks():
    now = datetime(2026, 8, 20, 15, 0, 0)
    session = {
        "clock_in_at": datetime(2026, 8, 20, 6, 3, 0),
        "clock_out_at": datetime(2026, 8, 20, 14, 9, 0),
    }
    segments = [
        {
            "started_at": datetime(2026, 8, 20, 6, 3, 0),
            "ended_at": datetime(2026, 8, 20, 8, 21, 0),
            "role_code": "OPERATOR",
            "role_name_snapshot": "Operator",
            "category_code": "RINSE_WF",
            "category_name_snapshot": "Rinse WF",
            "duration_seconds": 100,
        },
        {
            "started_at": datetime(2026, 8, 20, 8, 21, 0),
            "ended_at": datetime(2026, 8, 20, 10, 47, 0),
            "role_code": "SORT",
            "role_name_snapshot": "Sort",
            "category_code": "RINSE_WF",
            "category_name_snapshot": "Rinse WF",
            "duration_seconds": 100,
        },
    ]
    breaks = [
        {
            "break_start_at": datetime(2026, 8, 20, 10, 47, 0),
            "break_end_at": datetime(2026, 8, 20, 11, 17, 0),
        }
    ]
    timeline = _build_timeline(session, segments, breaks, now=now)
    types = [e["type"] for e in timeline]
    assert types[0] == "clock_in"
    assert "role" in types
    assert "break" in types
    assert types[-1] == "clock_out"
    role_labels = [e.get("assignment_label") for e in timeline if e["type"] == "role"]
    assert any("Wash-Dry" in (x or "") for x in role_labels)
    assert any("Sort" in (x or "") for x in role_labels)
    assert not any("Operator" in (x or "") for x in role_labels)
    assert not any("RINSE_WF" in (x or "") for x in role_labels)


def test_break_seconds_helper():
    now = datetime(2026, 8, 20, 12, 0, 0)
    total, on_break, _ = _break_seconds_for_session(
        [
            {
                "break_start_at": datetime(2026, 8, 20, 9, 0, 0),
                "break_end_at": datetime(2026, 8, 20, 9, 20, 0),
            }
        ],
        now=now,
    )
    assert total == 20 * 60
    assert on_break is False


@patch("backend.team_status._load_planned_day_entries", return_value=[])
@patch("backend.team_status._org_ot_threshold_hours")
@patch("backend.team_status.payroll_week_bounds")
@patch("backend.team_status._load_range_sessions", return_value=[])
@patch("backend.team_status.list_session_segments")
@patch("backend.team_status._fetch_breaks")
@patch("backend.team_status._load_day_sessions")
@patch("backend.team_status.business_today")
def test_build_team_status_splits_active_vs_worked(
    mock_today,
    mock_sessions,
    mock_breaks,
    mock_segments,
    mock_range,
    mock_bounds,
    mock_thr,
    mock_planned,
):
    from datetime import date
    from decimal import Decimal

    from backend.team_status import build_team_status

    mock_today.return_value = date(2026, 8, 20)
    mock_bounds.return_value = (date(2026, 8, 17), date(2026, 8, 23))
    mock_thr.return_value = Decimal("40")
    mock_sessions.return_value = [
        {
            "id": 1,
            "user_id": 10,
            "status": "active",
            "clock_in_at": datetime(2026, 8, 20, 6, 0, 0),
            "clock_out_at": None,
            "display_name": "Maria Lopez",
            "name_parts": "Maria Lopez",
            "username": "maria",
            "net_work_seconds": None,
        },
        {
            "id": 2,
            "user_id": 11,
            "status": "completed",
            "clock_in_at": datetime(2026, 8, 20, 6, 2, 0),
            "clock_out_at": datetime(2026, 8, 20, 12, 14, 0),
            "display_name": "Francis",
            "name_parts": "Francis",
            "username": "francis",
            "net_work_seconds": 6 * 3600 + 12 * 60,
        },
    ]
    mock_breaks.return_value = {1: [], 2: []}
    mock_segments.return_value = [
        {
            "started_at": datetime(2026, 8, 20, 6, 0, 0),
            "ended_at": None,
            "role_code": "SORT",
            "role_name_snapshot": "Sort",
            "category_code": "RINSE_WF",
            "category_name_snapshot": "Rinse WF",
            "duration_seconds": 100,
        }
    ]
    conn = MagicMock()
    with patch("backend.team_status.eastern_now_naive", return_value=datetime(2026, 8, 20, 12, 0, 0)):
        payload = build_team_status(conn, 3, date_et=date(2026, 8, 20))
    assert payload["is_today"] is True
    assert payload["summary"]["working_count"] == 1
    assert payload["summary"]["break_count"] == 0
    assert payload["summary"]["worked_count"] == 2
    assert len(payload["working_now"]) == 1
    assert payload["working_now"][0]["display_name"] == "Maria Lopez"
    assert "Sort" in payload["working_now"][0]["assignment_label"]
    assert len(payload["worked"]) == 1
    assert payload["worked"][0]["display_name"] == "Francis"
    assert payload["worked"][0]["status"] == "completed"
    assert "week" in payload["working_now"][0]


def test_ot_flag_near_and_over():
    from decimal import Decimal

    from backend.team_status import _ot_flag

    assert _ot_flag(36 * 3600, Decimal("40")) == "near_40"
    assert _ot_flag(41 * 3600, Decimal("40")) == "ot"
    assert _ot_flag(20 * 3600, Decimal("40")) is None


@patch("backend.team_status.list_session_segments", return_value=[])
@patch("backend.team_status._load_planned_day_entries", return_value=[])
@patch("backend.team_status._org_ot_threshold_hours")
@patch("backend.team_status.payroll_week_bounds")
@patch("backend.team_status._fetch_breaks")
@patch("backend.team_status._load_range_sessions")
@patch("backend.team_status.business_today")
def test_build_team_status_week_sorts_ot_first(
    mock_today, mock_range, mock_breaks, mock_bounds, mock_thr, mock_planned, mock_seg
):
    from datetime import date
    from decimal import Decimal

    from backend.team_status import build_team_status_week

    mock_today.return_value = date(2026, 8, 20)
    mock_bounds.return_value = (date(2026, 8, 17), date(2026, 8, 23))
    mock_thr.return_value = Decimal("40")
    mock_range.return_value = [
        {
            "id": 1,
            "user_id": 1,
            "status": "completed",
            "clock_in_at": datetime(2026, 8, 18, 6, 0, 0),
            "clock_out_at": datetime(2026, 8, 18, 14, 0, 0),
            "display_name": "Near Person",
            "name_parts": "Near Person",
            "username": "near",
            "net_work_seconds": 36 * 3600,
        },
        {
            "id": 2,
            "user_id": 2,
            "status": "completed",
            "clock_in_at": datetime(2026, 8, 18, 6, 0, 0),
            "clock_out_at": datetime(2026, 8, 18, 14, 0, 0),
            "display_name": "OT Person",
            "name_parts": "OT Person",
            "username": "ot",
            "net_work_seconds": 43 * 3600,
        },
        {
            "id": 3,
            "user_id": 3,
            "status": "completed",
            "clock_in_at": datetime(2026, 8, 18, 6, 0, 0),
            "clock_out_at": datetime(2026, 8, 18, 14, 0, 0),
            "display_name": "Normal Person",
            "name_parts": "Normal Person",
            "username": "norm",
            "net_work_seconds": 20 * 3600,
        },
    ]
    mock_breaks.return_value = {1: [], 2: [], 3: []}
    conn = MagicMock()
    with patch("backend.team_status.eastern_now_naive", return_value=datetime(2026, 8, 20, 12, 0, 0)):
        with patch("backend.planned_weekly_schedule.list_week_entries", return_value=[]):
            payload = build_team_status_week(conn, 3, date_et=date(2026, 8, 20))
    assert payload["summary"]["ot_count"] == 1
    assert payload["summary"]["near_count"] == 1
    names = [e["display_name"] for e in payload["employees"]]
    assert names[0] == "OT Person"
    assert names[1] == "Near Person"
    assert names[2] == "Normal Person"


@patch("backend.team_status._load_planned_day_entries")
@patch("backend.team_status.business_today")
def test_build_team_status_upcoming_groups_by_start(mock_today, mock_planned):
    from datetime import date

    from backend.team_status import build_team_status_upcoming

    mock_today.return_value = date(2026, 8, 20)
    mock_planned.return_value = [
        {
            "user_id": 10,
            "roles": ["sort"],
            "start_time": "07:00",
            "end_time": "15:00",
            "hours": 8.0,
        },
        {
            "user_id": 11,
            "roles": ["wash"],
            "start_time": "06:00",
            "end_time": "14:00",
            "hours": 8.0,
        },
        {
            "user_id": 12,
            "roles": ["fold"],
            "start_time": "07:00",
            "end_time": "15:00",
            "hours": 8.0,
        },
    ]
    conn = MagicMock()
    with patch(
        "backend.planned_weekly_schedule._load_workers",
        return_value=[
            {"user_id": 10, "display_name": "Maria"},
            {"user_id": 11, "display_name": "Francis"},
            {"user_id": 12, "display_name": "Jennifer"},
        ],
    ):
        with patch(
            "backend.planned_weekly_schedule._workers_index",
            return_value={
                10: {"user_id": 10, "display_name": "Maria"},
                11: {"user_id": 11, "display_name": "Francis"},
                12: {"user_id": 12, "display_name": "Jennifer"},
            },
        ):
            payload = build_team_status_upcoming(conn, 3, date_et=date(2026, 8, 21))
    assert payload["is_tomorrow"] is True
    assert payload["summary"]["staff_count"] == 3
    assert payload["groups"][0]["start_time"] == "06:00"
    assert payload["groups"][0]["entries"][0]["display_name"] == "Francis"


@patch("backend.team_status._load_planned_day_entries")
@patch("backend.team_status.business_today")
def test_build_team_status_upcoming_uses_saturday_template_for_empty_sunday(
    mock_today, mock_planned
):
    from datetime import date

    from backend.team_status import build_team_status_upcoming

    mock_today.return_value = date(2026, 8, 22)

    def planned_side_effect(conn, org_id, day):
        if day == date(2026, 8, 23):
            return []
        if day == date(2026, 8, 22):
            return [
                {
                    "user_id": 10,
                    "roles": ["fold"],
                    "start_time": "08:00",
                    "end_time": "16:00",
                    "hours": 8.0,
                }
            ]
        return []

    mock_planned.side_effect = planned_side_effect
    conn = MagicMock()
    with patch(
        "backend.planned_weekly_schedule._load_workers",
        return_value=[{"user_id": 10, "display_name": "Maria"}],
    ):
        with patch(
            "backend.planned_weekly_schedule._workers_index",
            return_value={10: {"user_id": 10, "display_name": "Maria"}},
        ):
            payload = build_team_status_upcoming(conn, 3, date_et=date(2026, 8, 23))
    assert payload["is_tomorrow"] is True
    assert payload["summary"]["staff_count"] == 1
    assert payload["entries"][0]["display_name"] == "Maria"


def test_load_planned_day_entries_excludes_affiliation_none():
    from datetime import date, time
    from unittest.mock import MagicMock, patch

    from backend.team_status import _load_planned_day_entries

    conn = MagicMock()
    entries = [
        {
            "user_id": 29,
            "day_of_week": 5,
            "roles": ["fold"],
            "start_time": "09:00",
            "end_time": "16:00",
            "hours": 7.0,
        },
        {
            "user_id": 10,
            "day_of_week": 5,
            "roles": ["sort"],
            "start_time": "07:00",
            "end_time": "15:00",
            "hours": 8.0,
        },
    ]
    with patch(
        "backend.planned_weekly_schedule.list_week_entries", return_value=entries
    ), patch(
        "backend.planned_weekly_schedule.normalize_week_start", return_value=date(2026, 8, 23)
    ), patch(
        "backend.team_status._schedulable_user_ids", return_value={10}
    ):
        out = _load_planned_day_entries(conn, 3, date(2026, 8, 28))
    assert len(out) == 1
    assert out[0]["user_id"] == 10
