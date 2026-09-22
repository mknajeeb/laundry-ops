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


def _compose(sessions, **kwargs):
    return compose_employee_day_from_sessions(
        employee_name="Maria Rodriguez (Veewash)",
        employee_user_id=59,
        sessions=sessions,
        selected_date_et=DAY,
        **kwargs,
    )


def test_maria_review_two_sessions_one_employee_day():
    sessions = _maria_two_sessions()
    emp = _compose(sessions)
    assert len(emp["sessions"]) == 2
    assert emp["orders_completed"] == 12
    assert emp["total_pre_lbs"] == 240.0
    assert emp["performance_hours"] == 5.0
    assert abs(float(emp["lbs_per_hour"]) - 48.0) < 0.01
    assert abs(float(emp["bags_per_hour"]) - 2.4) < 0.01
    # Not average of session rates (53.33 and 40).
    assert abs(float(emp["lbs_per_hour"]) - 46.665) > 1.0


def test_maria_acceptance_sequence_a_through_e():
    """Sequential A–E: approve → disapprove WF-01 → exclude → include → edit avg 54."""
    # A. Both approved — one observation, combined totals, weighted lb/hr.
    sessions = _maria_two_sessions()
    emp = _compose(sessions)
    assert emp["session_count"] == 2 or len(emp["sessions"]) == 2
    assert emp["orders_completed"] == 12
    assert emp["total_pre_lbs"] == 240.0
    assert emp["performance_hours"] == 5.0
    assert abs(float(emp["lbs_per_hour"]) - 48.0) < 0.01
    assert emp["day_publication_status"] == "APPROVED"
    assert emp["dashboard_rankable"] is True

    day = {"employees": [emp], "summary": {}}
    partition_employees_by_exclusion(day)
    assert day["summary"]["employee_day_count"] == 1
    assert day["summary_approved"]["employee_day_count"] == 1
    assert abs(float(day["summary_approved"]["lbs_per_hour"]) - 48.0) < 0.01

    # B. Disapprove WF-01 — still visible; live rates unchanged; not rankable.
    sessions = apply_session_publication_patch(
        sessions, session_id="2001", status="UNAPPROVED"
    )
    emp = _compose(sessions)
    assert any(s["session_code"] == "WF-01" for s in emp["sessions"])
    assert any(s["session_code"] == "WF-02" for s in emp["sessions"])
    assert emp["day_publication_status"] == "PARTIALLY_APPROVED"
    assert emp["dashboard_rankable"] is False
    assert emp["orders_completed"] == 12
    assert emp["total_pre_lbs"] == 240.0
    assert abs(float(emp["lbs_per_hour"]) - 48.0) < 0.01

    day = {"employees": [emp], "summary": {}}
    partition_employees_by_exclusion(day)
    assert day["summary"]["employee_day_count"] == 1  # live includes partial
    assert day["summary_approved"]["employee_day_count"] == 0  # not published
    assert day["employees"][0]["dashboard_rankable"] is False

    # C. Exclude WF-01 — remains visible EXCLUDED; calc from WF-02 only.
    sessions = apply_session_publication_patch(
        sessions, session_id="2001", status="EXCLUDED"
    )
    emp = _compose(sessions)
    assert any(s["session_code"] == "WF-01" for s in emp["sessions"])
    assert any(
        (s.get("publication_status") or "") == "EXCLUDED"
        and s.get("session_code") == "WF-01"
        for s in emp["sessions"]
    )
    assert emp["excluded_session_count"] == 1
    assert emp["included_session_count"] == 1
    assert emp["orders_completed"] == 4
    assert emp["total_pre_lbs"] == 80.0
    assert emp["performance_hours"] == 2.0
    assert abs(float(emp["lbs_per_hour"]) - 40.0) < 0.05
    # Day status from remaining included session(s)
    assert emp["day_publication_status"] == "APPROVED"
    assert emp["dashboard_rankable"] is True

    # D. Include WF-01 — combined restores immediately.
    sessions = apply_session_publication_patch(
        sessions, session_id="2001", status="UNAPPROVED"
    )
    emp = _compose(sessions)
    assert emp["orders_completed"] == 12
    assert emp["total_pre_lbs"] == 240.0
    assert emp["performance_hours"] == 5.0
    assert abs(float(emp["lbs_per_hour"]) - 48.0) < 0.01
    assert emp["dashboard_rankable"] is False  # not fully approved again

    # E. Edit Day average weight 54 — once on employee-day, no session multiply.
    emp = _compose(sessions, average_weight_override=54.0)
    assert emp["orders_completed"] == 12
    assert emp["total_pre_lbs"] == 648.0  # 54 × 12 once
    assert emp["calculated_total_pre_lbs"] == 240.0
    assert emp["day_average_weight_is_override"] is True
    assert abs(float(emp["lbs_per_hour"]) - (648.0 / 5.0)) < 0.05
    # Session bag counts unchanged (no per-session lbs rewrite storm).
    assert sum(int(s["orders_completed"]) for s in emp["sessions"]) == 12


def test_maria_disapprove_one_becomes_partial_rates_unchanged():
    """Disapprove flips badge; live rates still include non-excluded sessions."""
    sessions = _maria_two_sessions()
    patched = apply_session_publication_patch(
        sessions, session_id="2001", status="UNAPPROVED"
    )
    emp = _compose(patched)
    assert emp["day_publication_status"] == "PARTIALLY_APPROVED"
    assert emp["dashboard_rankable"] is False
    assert emp["orders_completed"] == 12
    assert emp["total_pre_lbs"] == 240.0
    assert abs(float(emp["lbs_per_hour"]) - 48.0) < 0.01


def test_maria_exclude_one_recalculates_and_stays_visible():
    sessions = _maria_two_sessions()
    patched = apply_session_publication_patch(
        sessions, session_id="2001", status="EXCLUDED"
    )
    emp = _compose(patched)
    assert emp["day_publication_status"] == "APPROVED"
    assert emp["excluded_session_count"] == 1
    assert emp["included_session_count"] == 1
    assert emp["orders_completed"] == 4
    assert emp["total_pre_lbs"] == 80.0
    assert emp["performance_hours"] == 2.0
    assert abs(float(emp["lbs_per_hour"]) - 40.0) < 0.05
    assert any(s["session_code"] == "WF-01" for s in emp["sessions"])
    assert any(
        (s.get("publication_status") or "") == "EXCLUDED" for s in emp["sessions"]
    )


def test_maria_include_restores_totals():
    sessions = _maria_two_sessions()
    patched = apply_session_publication_patch(
        sessions, session_id="2001", status="EXCLUDED"
    )
    emp = _compose(patched)
    assert emp["orders_completed"] == 4
    restored = apply_session_publication_patch(
        emp["sessions"], session_id="2001", status="UNAPPROVED"
    )
    emp2 = _compose(restored)
    assert emp2["orders_completed"] == 12
    assert emp2["total_pre_lbs"] == 240.0
    assert emp2["performance_hours"] == 5.0


def test_maria_edit_day_average_weight_applied_once():
    sessions = _maria_two_sessions()
    emp = _compose(sessions, average_weight_override=54.0)
    assert emp["orders_completed"] == 12
    assert emp["total_pre_lbs"] == 648.0  # 54 × 12 once
    assert emp["calculated_total_pre_lbs"] == 240.0
    assert emp["day_average_weight_is_override"] is True
    assert abs(float(emp["lbs_per_hour"]) - (648.0 / 5.0)) < 0.05


def test_maria_leaderboard_and_team_use_same_employee_day():
    sessions = _maria_two_sessions()
    maria = _compose(sessions, average_weight_override=54.0)
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
    assert summary["total_pre_lbs"] == 848.0  # 648 + 200
    assert abs(float(summary["total_hours"]) - 9.0) < 0.01
    assert abs(float(summary["lbs_per_hour"]) - (848.0 / 9.0)) < 0.05
    assert day["summary_approved"]["employee_day_count"] == 2
    names = [e["employee"] for e in day["employees"]]
    assert names.count("Maria Rodriguez (Veewash)") == 1


def test_partial_maria_not_in_approved_leaderboard_summary():
    sessions = apply_session_publication_patch(
        _maria_two_sessions(), session_id="2001", status="UNAPPROVED"
    )
    maria = _compose(sessions)
    other = compose_employee_day_from_sessions(
        employee_name="Other",
        employee_user_id=1,
        sessions=[
            _sess(
                sid="9",
                code="WF-01",
                status="APPROVED",
                bags=10,
                lbs=200,
                hours=4.0,
                end="2026-09-19T12:00:00",
            )
        ],
        selected_date_et=DAY,
    )
    other["employee"] = "Other"
    day = {"employees": [maria, other], "summary": {}}
    partition_employees_by_exclusion(day)
    # Live team includes both employee-days.
    assert day["summary"]["employee_day_count"] == 2
    # Published/approved ranking excludes Maria's partial day.
    assert day["summary_approved"]["employee_day_count"] == 1
    assert day["summary_approved"]["orders_completed"] == 10
    rankable = [e for e in day["employees"] if e.get("dashboard_rankable")]
    assert len(rankable) == 1
    assert rankable[0]["employee"] == "Other"


def test_excluded_employee_day_stays_in_employees_list():
    emp = _compose(
        apply_session_publication_patch(
            _maria_two_sessions(),
            session_ids=["2001", "2002"],
            status="EXCLUDED",
        )
    )
    assert emp["day_publication_status"] == "EXCLUDED"
    day = {"employees": [emp], "summary": {}}
    partition_employees_by_exclusion(day)
    assert len(day["employees"]) == 1
    assert day["employees"][0]["excluded_from_metrics"] is True
    assert day["summary"]["employee_count"] == 0
    assert day["excluded_employee_count"] == 1
    # Reload-shaped payload still carries the excluded row (not frontend-only).
    assert day["excluded_employees"][0]["employee"] == "Maria Rodriguez (Veewash)"
