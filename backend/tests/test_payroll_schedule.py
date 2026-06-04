"""Tests for payroll scheduling Phase 1."""

from datetime import time
from decimal import Decimal

from backend.payroll_schedule import (
    compute_scheduled_hours,
    DEFAULT_ROLES,
    DEFAULT_SHIFTS,
    DEFAULT_STREAMS,
)


def test_compute_scheduled_hours_standard():
    hrs = compute_scheduled_hours(time(7, 0), time(15, 0), break_minutes=30)
    assert float(hrs) == 7.5


def test_compute_scheduled_hours_overnight():
    hrs = compute_scheduled_hours(time(23, 0), time(7, 0), break_minutes=0)
    assert float(hrs) == 8.0


def test_default_shifts_not_hardcoded_in_logic():
    names = [s[0] for s in DEFAULT_SHIFTS]
    assert "Morning" in names
    assert "Afternoon" in names


def test_default_streams():
    names = [s[0] for s in DEFAULT_STREAMS]
    assert "Rinse" in names
    assert "Drop Off" in names
    assert "Both" in names


def test_default_roles_operator_folder_active():
    active = [r[0] for r in DEFAULT_ROLES if r[1] <= 20]
    assert "Operator" in active
    assert "Folder" in active


def test_worker_profile_gaps_detects_missing_data():
    from backend.payroll_schedule import worker_profile_gaps

    gaps = worker_profile_gaps(
        {"active": True, "worker_category": "w2", "default_hourly_rate": None},
        availability=[],
        role_skills=[],
    )
    assert "Missing hourly rate" in gaps
    assert "No role skill assigned" in gaps
    assert "No availability set" in gaps


def test_worker_profile_gaps_inactive():
    from backend.payroll_schedule import worker_profile_gaps

    gaps = worker_profile_gaps({"active": False, "worker_category": "w2", "default_hourly_rate": 20})
    assert "Worker inactive" in gaps


def test_profile_completeness_score():
    from backend.payroll_schedule import profile_completeness

    worker = {
        "active": True,
        "worker_category": "w2",
        "default_hourly_rate": 20,
        "role_skills": [{"role_id": 1, "work_stream_id": 2, "active": True}],
        "can_work_rinse": True,
        "availability": [{"day_of_week": 0, "unavailable_flag": 0}],
        "preferred_shift_id": 1,
        "geofence_ids": [1],
        "performance_preview": {"available": True},
    }
    out = profile_completeness(worker)
    assert out["score"] == 100
    assert out["missing"] == []


def test_scheduling_readiness_ready():
    from backend.payroll_schedule import scheduling_readiness_badge

    worker = {
        "active": True,
        "worker_category": "w2",
        "default_hourly_rate": 20,
        "role_skills": [{"role_id": 1, "work_stream_id": 2, "active": True}],
        "can_work_rinse": True,
        "availability": [{"day_of_week": 0, "unavailable_flag": 0}],
        "preferred_shift_id": 1,
        "geofence_ids": [1],
        "profile_gaps": [],
    }
    badge = scheduling_readiness_badge(worker)
    assert badge["ready"] is True
    assert badge["label"] == "Ready for Scheduling"


def test_apply_profile_to_entry_uses_profile_rate():
    from decimal import Decimal
    from unittest.mock import MagicMock

    from backend.payroll_schedule import apply_profile_to_entry

    entry = {"scheduled_hours": 8, "shift_id": 1, "role_id": 2, "work_stream_id": 3}
    prof = {"user_id": 1, "default_hourly_rate": Decimal("18.00"), "worker_category": "w2"}
    conn = MagicMock()
    c = conn.cursor.return_value
    c.fetchone.return_value = None
    merged = apply_profile_to_entry(conn, 1, entry, prof)
    assert float(merged["hourly_rate_snapshot"]) == 18.0
    assert merged["worker_category_snapshot"] == "w2"
    assert float(merged["estimated_cost"]) == 144.0
