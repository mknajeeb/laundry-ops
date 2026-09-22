"""Maria Rodriguez Performance V2 regression — employee-day unit + mutations."""

from __future__ import annotations

from datetime import date

from backend.rinse_performance_employee_day import (
    apply_session_publication_patch,
    compose_employee_day_from_sessions,
)
from backend.rinse_performance_folder_publisher import partition_employees_by_exclusion


DAY = date(2026, 9, 19)


def _sess(
    *,
    sid: str,
    code: str,
    status: str,
    bags: int,
    lbs: float,
    hours: float,
    end: str,
):
    return {
        "session_id": sid,
        "session_code": code,
        "segment_id": int(sid),
        "publication_status": status,
        "publication": {"status": status, "excluded": status == "EXCLUDED"},
        "orders_completed": bags,
        "total_pre_lbs": lbs,
        "performance_hours": hours,
        "role_status": "closed",
        "include_in_authoritative_aggregate": True,
        "start_time": "2026-09-19T08:00:00",
        "end_time": end,
        "performance_end": end,
        "employee": "Maria Rodriguez (Veewash)",
    }


def _maria_two_sessions():
    return [
        _sess(
            sid="2001",
            code="WF-01",
            status="APPROVED",
            bags=8,
            lbs=160,
            hours=3.0,
            end="2026-09-19T12:00:00",
        ),
        _sess(
            sid="2002",
            code="WF-02",
            status="APPROVED",
            bags=4,
            lbs=80,
            hours=2.0,
            end="2026-09-19T15:00:00",
        ),
    ]


def test_maria_review_two_sessions_one_employee_day():
    sessions = _maria_two_sessions()
    emp = compose_employee_day_from_sessions(
        employee_name="Maria Rodriguez (Veewash)",
        employee_user_id=59,
        sessions=sessions,
        selected_date_et=DAY,
    )
    assert len(emp["sessions"]) == 2
    assert emp["orders_completed"] == 12
    assert emp["total_pre_lbs"] == 240.0
    assert emp["performance_hours"] == 5.0
    assert abs(float(emp["lbs_per_hour"]) - 48.0) < 0.01
    assert abs(float(emp["bags_per_hour"]) - 2.4) < 0.01
    # Not average of session rates (53.33 and 40).
    assert abs(float(emp["lbs_per_hour"]) - 46.665) > 1.0


def test_maria_disapprove_one_becomes_partial_rates_unchanged():
    """Disapprove flips badge; live rates still include non-excluded sessions."""
    sessions = _maria_two_sessions()
    patched = apply_session_publication_patch(
        sessions, session_id="2002", status="UNAPPROVED"
    )
    emp = compose_employee_day_from_sessions(
        employee_name="Maria Rodriguez (Veewash)",
        employee_user_id=59,
        sessions=patched,
        selected_date_et=DAY,
    )
    assert emp["day_publication_status"] == "PARTIALLY_APPROVED"
    assert emp["dashboard_rankable"] is False
    assert emp["orders_completed"] == 12
    assert emp["total_pre_lbs"] == 240.0
    assert abs(float(emp["lbs_per_hour"]) - 48.0) < 0.01


def test_maria_exclude_one_recalculates_and_stays_visible():
    sessions = _maria_two_sessions()
    patched = apply_session_publication_patch(
        sessions, session_id="2002", status="EXCLUDED"
    )
    emp = compose_employee_day_from_sessions(
        employee_name="Maria Rodriguez (Veewash)",
        employee_user_id=59,
        sessions=patched,
        selected_date_et=DAY,
    )
    assert emp["day_publication_status"] == "APPROVED"
    assert emp["excluded_session_count"] == 1
    assert emp["included_session_count"] == 1
    assert emp["orders_completed"] == 8
    assert emp["total_pre_lbs"] == 160.0
    assert emp["performance_hours"] == 3.0
    assert abs(float(emp["lbs_per_hour"]) - (160.0 / 3.0)) < 0.05
    assert any(s["session_code"] == "WF-02" for s in emp["sessions"])
    assert any(
        (s.get("publication_status") or "") == "EXCLUDED" for s in emp["sessions"]
    )


def test_maria_include_restores_totals():
    sessions = _maria_two_sessions()
    patched = apply_session_publication_patch(
        sessions, session_id="2002", status="EXCLUDED"
    )
    emp = compose_employee_day_from_sessions(
        employee_name="Maria Rodriguez (Veewash)",
        employee_user_id=59,
        sessions=patched,
        selected_date_et=DAY,
    )
    assert emp["orders_completed"] == 8
    restored = apply_session_publication_patch(
        emp["sessions"], session_id="2002", status="UNAPPROVED"
    )
    emp2 = compose_employee_day_from_sessions(
        employee_name="Maria Rodriguez (Veewash)",
        employee_user_id=59,
        sessions=restored,
        selected_date_et=DAY,
    )
    assert emp2["orders_completed"] == 12
    assert emp2["total_pre_lbs"] == 240.0
    assert emp2["performance_hours"] == 5.0


def test_maria_edit_day_average_weight_applied_once():
    sessions = _maria_two_sessions()
    emp = compose_employee_day_from_sessions(
        employee_name="Maria Rodriguez (Veewash)",
        employee_user_id=59,
        sessions=sessions,
        average_weight_override=22.0,
        selected_date_et=DAY,
    )
    assert emp["orders_completed"] == 12
    assert emp["total_pre_lbs"] == 264.0  # 22 × 12 once
    assert emp["calculated_total_pre_lbs"] == 240.0
    assert emp["day_average_weight_is_override"] is True
    assert abs(float(emp["lbs_per_hour"]) - (264.0 / 5.0)) < 0.05


def test_maria_leaderboard_and_team_use_same_employee_day():
    sessions = _maria_two_sessions()
    maria = compose_employee_day_from_sessions(
        employee_name="Maria Rodriguez (Veewash)",
        employee_user_id=59,
        sessions=sessions,
        average_weight_override=22.0,
        selected_date_et=DAY,
    )
    other_sess = _sess(
        sid="9",
        code="WF-01",
        status="APPROVED",
        bags=10,
        lbs=200,
        hours=4.0,
        end="2026-09-19T12:00:00",
    )
    other_sess["employee"] = "Other"
    other = compose_employee_day_from_sessions(
        employee_name="Other",
        employee_user_id=1,
        sessions=[other_sess],
        selected_date_et=DAY,
    )
    day = {"employees": [maria, other], "summary": {}}
    partition_employees_by_exclusion(day)
    summary = day["summary"]
    assert summary["orders_completed"] == 22
    assert summary["total_pre_lbs"] == 464.0  # 264 + 200
    assert abs(float(summary["total_hours"]) - 9.0) < 0.01
    assert abs(float(summary["lbs_per_hour"]) - (464.0 / 9.0)) < 0.05
    names = [e["employee"] for e in day["employees"]]
    assert names.count("Maria Rodriguez (Veewash)") == 1


def test_excluded_employee_day_stays_in_employees_list():
    emp = compose_employee_day_from_sessions(
        employee_name="Maria Rodriguez (Veewash)",
        employee_user_id=59,
        sessions=apply_session_publication_patch(
            _maria_two_sessions(),
            session_ids=["2001", "2002"],
            status="EXCLUDED",
        ),
        selected_date_et=DAY,
    )
    assert emp["day_publication_status"] == "EXCLUDED"
    day = {"employees": [emp], "summary": {}}
    partition_employees_by_exclusion(day)
    assert len(day["employees"]) == 1
    assert day["employees"][0]["excluded_from_metrics"] is True
    assert day["summary"]["employee_count"] == 0
    assert day["excluded_employee_count"] == 1
