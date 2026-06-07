"""Tests for rule-based roster generator."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from backend.payroll_roster_generator import (
    _score_worker_for_slot,
    _stream_matches_filter,
    _worker_eligible,
    generate_roster_draft,
)


def test_stream_filter():
    assert _stream_matches_filter(1, "Rinse", [1, 2]) is True
    assert _stream_matches_filter(3, "Drop Off", [1, 2]) is False
    assert _stream_matches_filter(1, "Rinse", None) is True


def test_worker_eligible_incomplete():
    w = {"active": True, "default_hourly_rate": 20, "profile_gaps": ["No availability set"]}
    ok, _ = _worker_eligible(w, active_only=True, include_incomplete=False)
    assert ok is False
    ok2, _ = _worker_eligible(w, active_only=True, include_incomplete=True)
    assert ok2 is True


def test_score_worker_role_required():
    conn = MagicMock()
    worker = {
        "id": 1,
        "active": True,
        "worker_category": "w2",
        "default_hourly_rate": 18,
        "geofence_ids": [1],
        "can_work_rinse": True,
        "availability": [{"day_of_week": 0, "unavailable_flag": 0, "available_from": "06:00", "available_to": "18:00"}],
        "role_skills": [{"role_id": 2, "work_stream_id": 3, "active": True}],
        "preferred_shift_id": 10,
        "performance_preview": {"available": True, "avg_bags_per_hour": 12},
    }
    shift = {"id": 10, "name": "Morning", "start_time_default": "07:00:00", "end_time_default": "15:00:00"}
    work_date = date(2026, 6, 8)
    with patch("backend.payroll_roster_generator._overtime_threshold", return_value=Decimal("40")):
        score, reasons, disq = _score_worker_for_slot(
            conn,
            1,
            worker,
            work_date=work_date,
            shift=shift,
            work_stream_id=3,
            role_id=2,
            shift_hours=Decimal("8"),
            week_start=work_date,
            week_end=work_date,
            simulated_week_hours={1: Decimal("0")},
            day_entries=[],
            settings={"overtime_threshold_hours": 40, "target_hours_per_week": 32},
            options={"avoid_overtime": True, "prefer_strong_performers": True, "geofence_id": 1},
        )
    assert score > 0
    assert "Available" in reasons
    assert "Role match" in reasons
    assert not disq


def test_generate_roster_empty_range_raises():
    conn = MagicMock()
    try:
        generate_roster_draft(conn, 1, {})
    except ValueError as e:
        assert "start_date" in str(e)
    else:
        raise AssertionError("expected ValueError")
