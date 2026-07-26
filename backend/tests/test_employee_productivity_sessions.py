"""Unit tests for additive payroll-session productivity context."""

from __future__ import annotations

from datetime import date, datetime

from backend.rinse_employee_productivity_sessions import (
    ASSIGNMENT_AUTO,
    ASSIGNMENT_NEEDS_REVIEW,
    ASSIGNMENT_UNASSIGNED,
    assign_bag_to_session,
    build_payroll_session,
    build_stable_session_id,
    compute_bag_elapsed_timing,
    compute_session_idle,
    build_session_summary,
    enrich_employee_with_sessions,
    resolve_customer_name,
)


def _seg(**kwargs):
    base = {
        "id": 704,
        "shift_session_id": 10,
        "user_id": 3,
        "category_code": "RINSE_WF",
        "role_code": "FOLDER",
        "category_name_snapshot": "Rinse WF",
        "role_name_snapshot": "Folder",
        "started_at": datetime(2026, 7, 24, 8, 0, 0),
        "ended_at": datetime(2026, 7, 24, 12, 0, 0),
    }
    base.update(kwargs)
    return base


def test_stable_session_id_uses_segment_id_not_index():
    assert build_stable_session_id(_seg(id=704)) == "WF-704"
    assert build_stable_session_id(_seg(id=12, category_code="RINSE_HD")) == "HD-12"


def test_resolve_customer_name_never_dash():
    from backend.rinse_employee_productivity_sessions import customer_name_or_unknown

    assert resolve_customer_name(None) is None
    assert resolve_customer_name("—") is None
    assert resolve_customer_name("Jane Doe") == "Jane Doe"
    assert customer_name_or_unknown(None) == "Unknown Customer"
    assert customer_name_or_unknown("—") == "Unknown Customer"


def test_session_display_codes_are_human_readable():
    from backend.rinse_employee_productivity_sessions import assign_session_display_codes

    s1 = build_payroll_session(
        _seg(id=704, started_at=datetime(2026, 7, 24, 8, 0), ended_at=datetime(2026, 7, 24, 10, 30)),
        selected_date_et=date(2026, 7, 24),
    )
    s2 = build_payroll_session(
        _seg(id=705, started_at=datetime(2026, 7, 24, 10, 45), ended_at=datetime(2026, 7, 24, 14, 15)),
        selected_date_et=date(2026, 7, 24),
    )
    coded = assign_session_display_codes([s1, s2])
    assert coded[0]["session_id"] == "WF-704"
    assert coded[0]["session_code"] == "WF-01"
    assert coded[1]["session_code"] == "WF-02"
    assert "8:00 AM" in coded[0]["option_label"]
    assert "10:30 AM" in coded[0]["option_label"]
    # Visible code must never equal internal id.
    assert coded[0]["session_code"] != coded[0]["session_id"]


def test_missing_session_code_does_not_expose_session_id():
    from backend.rinse_employee_productivity_sessions import (
        assign_session_display_codes,
        public_session_display_fields,
    )

    sess = build_payroll_session(
        _seg(id=704),
        selected_date_et=date(2026, 7, 24),
    )
    # Simulate a bad payload that only has the internal id as a label.
    sess["session_code"] = sess["session_id"]
    fixed = assign_session_display_codes([sess])[0]
    assert fixed["session_code"] == "WF-01"
    assert fixed["session_code"] != fixed["session_id"]
    visible = public_session_display_fields({"session_id": "WF-704", "category_code": "RINSE_WF"})
    assert visible["session_code"] == "WF-01"
    assert visible["session_code"] != "WF-704"
    assert "session_id" not in visible


def test_auto_assign_single_matching_session():
    sess = build_payroll_session(
        _seg(),
        selected_date_et=date(2026, 7, 24),
        now_et=datetime(2026, 7, 24, 15, 0, 0),
    )
    bag = {"bag_id": "A1", "completion_time": "2026-07-24 09:30:00"}
    out = assign_bag_to_session(bag, [sess])
    assert out["session_assignment"] == ASSIGNMENT_AUTO
    assert out["session_id"] == "WF-704"


def test_needs_review_on_overlap():
    s1 = build_payroll_session(
        _seg(id=1, started_at=datetime(2026, 7, 24, 8, 0), ended_at=datetime(2026, 7, 24, 12, 0)),
        selected_date_et=date(2026, 7, 24),
    )
    s2 = build_payroll_session(
        _seg(id=2, started_at=datetime(2026, 7, 24, 9, 0), ended_at=datetime(2026, 7, 24, 13, 0)),
        selected_date_et=date(2026, 7, 24),
    )
    bag = {"bag_id": "B1", "completion_time": "2026-07-24 10:00:00"}
    out = assign_bag_to_session(bag, [s1, s2])
    assert out["session_assignment"] == ASSIGNMENT_NEEDS_REVIEW
    assert out["session_id"] is None


def test_unassigned_when_outside_sessions():
    sess = build_payroll_session(
        _seg(),
        selected_date_et=date(2026, 7, 24),
    )
    bag = {"bag_id": "C1", "completion_time": "2026-07-24 15:00:00"}
    out = assign_bag_to_session(bag, [sess])
    assert out["session_assignment"] == ASSIGNMENT_UNASSIGNED


def test_idle_is_session_end_minus_last_bag():
    sess = build_payroll_session(
        _seg(ended_at=datetime(2026, 7, 24, 12, 0)),
        selected_date_et=date(2026, 7, 24),
    )
    bags = [{"bag_id": "X", "completion_time": "2026-07-24 11:40:00"}]
    out = compute_session_idle(sess, bags, selected_date_et=date(2026, 7, 24))
    assert out["idle_minutes"] == 20.0


def test_idle_never_negative():
    sess = build_payroll_session(
        _seg(ended_at=datetime(2026, 7, 24, 12, 0)),
        selected_date_et=date(2026, 7, 24),
    )
    bags = [{"bag_id": "X", "completion_time": "2026-07-24 12:30:00"}]
    out = compute_session_idle(sess, bags, selected_date_et=date(2026, 7, 24))
    assert out["idle_minutes"] == 0.0


def test_timing_conflict_when_last_bag_after_session_end():
    sess = build_payroll_session(
        _seg(ended_at=datetime(2026, 7, 24, 12, 0)),
        selected_date_et=date(2026, 7, 24),
    )
    bags = [{"bag_id": "X", "completion_time": "2026-07-24 12:30:00"}]
    out = compute_session_idle(sess, bags, selected_date_et=date(2026, 7, 24))
    assert out["idle_minutes"] == 0.0
    assert out["timing_conflict"] is True


def test_timing_conflict_false_when_bag_before_end():
    sess = build_payroll_session(
        _seg(ended_at=datetime(2026, 7, 24, 12, 0)),
        selected_date_et=date(2026, 7, 24),
    )
    bags = [{"bag_id": "X", "completion_time": "2026-07-24 11:40:00"}]
    out = compute_session_idle(sess, bags, selected_date_et=date(2026, 7, 24))
    assert out["idle_minutes"] == 20.0
    assert out["timing_conflict"] is False


def test_bag_elapsed_first_uses_session_start():
    sess = build_payroll_session(
        _seg(),
        selected_date_et=date(2026, 7, 24),
    )
    bags = [
        {
            "bag_id": "1",
            "session_id": "WF-704",
            "session_assignment": ASSIGNMENT_AUTO,
            "completion_time": "2026-07-24 09:00:00",
        },
        {
            "bag_id": "2",
            "session_id": "WF-704",
            "session_assignment": ASSIGNMENT_AUTO,
            "completion_time": "2026-07-24 09:30:00",
        },
    ]
    timed = compute_bag_elapsed_timing(bags, {"WF-704": sess})
    by_id = {b["bag_id"]: b for b in timed}
    assert by_id["1"]["bag_start"].startswith("2026-07-24 08:00")
    assert by_id["1"]["elapsed_time_minutes"] == 60.0
    assert by_id["2"]["bag_start"].startswith("2026-07-24 09:00")
    assert by_id["2"]["elapsed_time_minutes"] == 30.0


def test_enrich_preserves_productivity_fields():
    emp = {
        "employee": "Alex",
        "completed_bags": 2,
        "total_completed_lbs": 40.0,
        "role_bags_per_hour": 1.5,
        "role_lbs_per_hour": 20.0,
        "productive_hours": 4.0,
        "idle_time_hours": 0.5,
        "folder_role_dual_productivity": True,
        "bags": [
            {
                "bag_id": "A1",
                "completion_time": "2026-07-24 09:00:00",
                "customer_name": "—",
                "credited_weight_lbs": 20,
            },
            {
                "bag_id": "A2",
                "completion_time": "2026-07-24 10:00:00",
                "customer_name": "Sam Customer",
                "credited_weight_lbs": 20,
            },
        ],
    }
    segs = [_seg()]
    out = enrich_employee_with_sessions(
        emp,
        segs,
        selected_date_et=date(2026, 7, 24),
        now_et=datetime(2026, 7, 24, 15, 0, 0),
    )
    assert out["completed_bags"] == 2
    assert out["total_completed_lbs"] == 40.0
    assert out["role_bags_per_hour"] == 1.5
    assert out["role_lbs_per_hour"] == 20.0
    assert out["productive_hours"] == 4.0
    assert out["idle_time_hours"] == 0.5
    assert out["total_sessions"] == 1
    assert out["sessions"][0]["session_id"] == "WF-704"
    # Known names preserved; dash is not treated as a real customer name.
    assert out["bags"][0].get("customer_name") != "Jane Doe"
    assert out["bags"][1]["customer_name"] == "Sam Customer"
    assert out["bags"][0]["session_id"] == "WF-704"
    assert out["bags"][0].get("session_code") == "WF-01"
    assert out["sessions"][0]["session_code"] == "WF-01"
    assert out["sessions"][0]["completed_bags"] == 2
    assert out["summary"]["total_idle_minutes"] is not None
    # Productivity fields unchanged (regression guard).
    assert out["completed_bags"] == emp["completed_bags"]
    assert out["total_completed_lbs"] == emp["total_completed_lbs"]
    assert out["role_bags_per_hour"] == emp["role_bags_per_hour"]
    assert out["role_lbs_per_hour"] == emp["role_lbs_per_hour"]
    assert out["productive_hours"] == emp["productive_hours"]
    assert out["idle_time_hours"] == emp["idle_time_hours"]


def test_customer_from_day_bag_snapshot_batch():
    from backend.rinse_employee_productivity_sessions import _customer_from_snapshot

    assert _customer_from_snapshot('{"customer_name": "Acme Laundry"}') == "Acme Laundry"
    assert _customer_from_snapshot({"name_clean": "Portal Name"}) == "Portal Name"
    assert _customer_from_snapshot({"customer_name": "—"}) is None


def test_session_summary_idle_pct():
    sessions = [
        {
            "session_id": "WF-1",
            "start_time": "2026-07-24 08:00:00",
            "end_time": "2026-07-24 12:00:00",
            "duration_minutes": 240,
            "idle_minutes": 20,
        }
    ]
    summary = build_session_summary(sessions)
    assert summary["total_sessions"] == 1
    assert summary["total_session_minutes"] == 240
    assert summary["total_idle_minutes"] == 20
    assert summary["idle_pct"] == 8.3
