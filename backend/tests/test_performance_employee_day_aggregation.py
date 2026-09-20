"""Employee-day Performance: excluded=0, weighted day rate, avg-weight override."""

from __future__ import annotations

from backend.rinse_performance_approvals import derive_employee_day_publication_status
from backend.rinse_performance_employee_day import (
    pick_final_included_session,
    recompute_employee_day_metrics,
)


def _sess(
    *,
    sid: str,
    code: str,
    status: str,
    bags: int,
    lbs: float,
    hours: float,
    end: str = "2026-09-10T12:00:00",
    start: str = "2026-09-10T06:00:00",
    segment_id: int = 1,
):
    return {
        "session_id": sid,
        "session_code": code,
        "segment_id": segment_id,
        "publication_status": status,
        "publication": {"status": status, "excluded": status == "EXCLUDED"},
        "orders_completed": bags,
        "total_pre_lbs": lbs,
        "performance_hours": hours,
        "role_status": "closed",
        "include_in_authoritative_aggregate": True,
        "start_time": start,
        "end_time": end,
        "performance_end": end,
        "employee": "Angelica (Veewash)",
    }


def test_angelica_excluded_sibling_zero_contribution_and_approved():
    """WF-01 Approved + WF-02 Excluded → included-only day, status Approved."""
    emp = {
        "employee": "Angelica (Veewash)",
        "user_id": 99,
        "sessions": [
            _sess(
                sid="1001",
                code="WF-01",
                status="APPROVED",
                bags=15,
                lbs=286,
                hours=6.1,
                end="2026-09-10T12:06:00",
                segment_id=10,
            ),
            _sess(
                sid="1002",
                code="WF-02",
                status="EXCLUDED",
                bags=1,
                lbs=27,
                hours=4.2,
                end="2026-09-10T16:30:00",
                segment_id=20,
            ),
        ],
    }
    day_pub = derive_employee_day_publication_status(emp["sessions"])
    assert day_pub["status"] == "APPROVED"
    assert day_pub["excluded_count"] == 1
    assert day_pub["included_session_count"] == 1

    recompute_employee_day_metrics(emp)
    assert emp["included_session_count"] == 1
    assert emp["excluded_session_count"] == 1
    assert emp["orders_completed"] == 15
    assert emp["total_pre_lbs"] == 286.0
    assert emp["performance_hours"] == 6.1
    assert abs(float(emp["lbs_per_hour"]) - (286.0 / 6.1)) < 0.05
    # Must NOT be the leaked aggregate 16 / 313 / 10.3 / ~30.4
    assert emp["orders_completed"] != 16
    assert emp["total_pre_lbs"] != 313.0


def test_angelica_day_average_weight_applied_once():
    emp = {
        "employee": "Angelica (Veewash)",
        "sessions": [
            _sess(
                sid="1001",
                code="WF-01",
                status="APPROVED",
                bags=15,
                lbs=286,
                hours=6.1,
                segment_id=10,
            ),
            _sess(
                sid="1002",
                code="WF-02",
                status="EXCLUDED",
                bags=1,
                lbs=27,
                hours=4.2,
                end="2026-09-10T16:30:00",
                segment_id=20,
            ),
        ],
    }
    recompute_employee_day_metrics(emp, average_weight_override=20.0)
    assert emp["orders_completed"] == 15  # excluded bag omitted
    assert emp["total_pre_lbs"] == 300.0  # 20 × 15
    assert emp["calculated_total_pre_lbs"] == 286.0
    assert emp["day_average_weight_is_override"] is True
    assert abs(float(emp["lbs_per_hour"]) - (300.0 / 6.1)) < 0.05


def test_multiple_included_sessions_weighted_not_averaged():
    emp = {
        "employee": "Worker",
        "sessions": [
            _sess(sid="1", code="WF-01", status="APPROVED", bags=10, lbs=200, hours=4.0),
            _sess(
                sid="2",
                code="WF-02",
                status="APPROVED",
                bags=4,
                lbs=80,
                hours=2.0,
                end="2026-09-10T14:00:00",
                segment_id=2,
            ),
        ],
    }
    recompute_employee_day_metrics(emp)
    assert emp["orders_completed"] == 14
    assert emp["total_pre_lbs"] == 280.0
    assert emp["performance_hours"] == 6.0
    assert abs(float(emp["lbs_per_hour"]) - (280.0 / 6.0)) < 0.01
    # Not (50 + 40) / 2 = 45
    assert abs(float(emp["lbs_per_hour"]) - 45.0) > 1.0


def test_include_restores_contribution_once():
    sessions = [
        _sess(sid="1", code="WF-01", status="APPROVED", bags=10, lbs=100, hours=2.0),
        _sess(
            sid="2",
            code="WF-02",
            status="EXCLUDED",
            bags=5,
            lbs=50,
            hours=1.0,
            end="2026-09-10T14:00:00",
            segment_id=2,
        ),
    ]
    emp = {"employee": "W", "sessions": sessions}
    recompute_employee_day_metrics(emp)
    assert emp["orders_completed"] == 10
    sessions[1]["publication_status"] = "UNAPPROVED"
    sessions[1]["publication"] = {"status": "UNAPPROVED", "excluded": False}
    recompute_employee_day_metrics(emp)
    assert emp["orders_completed"] == 15
    assert emp["total_pre_lbs"] == 150.0
    assert emp["performance_hours"] == 3.0


def test_fully_excluded_day_status():
    st = derive_employee_day_publication_status(
        [
            _sess(sid="1", code="A", status="EXCLUDED", bags=1, lbs=1, hours=1),
            _sess(sid="2", code="B", status="EXCLUDED", bags=1, lbs=1, hours=1),
        ]
    )
    assert st["status"] == "EXCLUDED"


def test_partial_among_included_only():
    st = derive_employee_day_publication_status(
        [
            _sess(sid="1", code="A", status="APPROVED", bags=1, lbs=1, hours=1),
            _sess(sid="2", code="B", status="UNAPPROVED", bags=1, lbs=1, hours=1),
            _sess(sid="3", code="C", status="EXCLUDED", bags=9, lbs=9, hours=9),
        ]
    )
    assert st["status"] == "PARTIALLY_APPROVED"
    assert st["excluded_count"] == 1


def test_pick_final_included_ignores_later_excluded():
    sessions = [
        _sess(
            sid="1",
            code="WF-01",
            status="APPROVED",
            bags=1,
            lbs=1,
            hours=1,
            end="2026-09-10T12:00:00",
            segment_id=10,
        ),
        _sess(
            sid="2",
            code="WF-02",
            status="EXCLUDED",
            bags=1,
            lbs=1,
            hours=1,
            end="2026-09-10T18:00:00",
            segment_id=20,
        ),
    ]
    final = pick_final_included_session(sessions)
    assert final is not None
    assert final["session_id"] == "1"
    assert final["segment_id"] == 10
