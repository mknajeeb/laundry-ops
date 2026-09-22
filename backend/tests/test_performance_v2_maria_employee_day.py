"""Maria / Tarannum Performance V2 — approved-subset employee-day metrics."""

from __future__ import annotations

from datetime import date

from backend.rinse_performance_employee_day import (
    apply_session_publication_patch,
    compose_employee_day_from_sessions,
)
from backend.rinse_performance_folder_publisher import partition_employees_by_exclusion


DAY = date(2026, 9, 19)
TARANNUM_DAY = date(2026, 9, 21)


def _sess(
    *,
    sid: str,
    code: str,
    status: str,
    bags: int,
    lbs: float,
    hours: float,
    end: str,
    employee: str = "Maria Rodriguez (Veewash)",
):
    return {
        "session_id": sid,
        "session_code": code,
        "segment_id": int(sid) if str(sid).isdigit() else abs(hash(sid)) % 100000,
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
        "employee": employee,
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
    assert emp["metrics_basis"] == "approved_non_excluded"


def test_maria_disapprove_drops_from_performance_keeps_visible():
    """Disapprove removes bags/hrs from Performance; session stays visible."""
    sessions = _maria_two_sessions()
    patched = apply_session_publication_patch(
        sessions, session_id="2001", status="UNAPPROVED"
    )
    emp = _compose(patched)
    assert emp["day_publication_status"] == "PARTIALLY_APPROVED"
    assert emp["dashboard_rankable"] is False
    assert len(emp["sessions"]) == 2
    # Performance = WF-02 only
    assert emp["orders_completed"] == 4
    assert emp["total_pre_lbs"] == 80.0
    assert emp["performance_hours"] == 2.0
    assert abs(float(emp["lbs_per_hour"]) - 40.0) < 0.05
    assert emp["approved_session_count"] == 1
    assert emp["pending_session_count"] == 1
    # All-visible operational totals still include pending
    assert emp["all_visible_orders_completed"] == 12
    assert emp["all_visible_total_pre_lbs"] == 240.0
    assert abs(float(emp["all_visible_performance_hours"]) - 5.0) < 0.01


def test_maria_acceptance_sequence_approved_subset():
    sessions = _maria_two_sessions()
    emp = _compose(sessions)
    assert emp["dashboard_rankable"] is True
    assert emp["orders_completed"] == 12

    # Disapprove WF-01 → Performance from WF-02 only; not Published
    sessions = apply_session_publication_patch(
        sessions, session_id="2001", status="UNAPPROVED"
    )
    emp = _compose(sessions)
    assert emp["day_publication_status"] == "PARTIALLY_APPROVED"
    assert emp["dashboard_rankable"] is False
    assert emp["orders_completed"] == 4
    assert abs(float(emp["lbs_per_hour"]) - 40.0) < 0.05

    day = {"employees": [emp], "summary": {}}
    partition_employees_by_exclusion(day)
    assert day["summary"]["employee_day_count"] == 1
    assert day["summary_approved"]["employee_day_count"] == 0

    # Exclude WF-01 → still visible EXCLUDED; Performance still WF-02
    sessions = apply_session_publication_patch(
        sessions, session_id="2001", status="EXCLUDED"
    )
    emp = _compose(sessions)
    assert emp["excluded_session_count"] == 1
    assert emp["orders_completed"] == 4
    assert emp["all_visible_orders_completed"] == 4  # excluded not visible-active
    assert emp["day_publication_status"] == "APPROVED"
    assert emp["dashboard_rankable"] is True

    # Include as UNAPPROVED → pending again; Performance still WF-02 only
    sessions = apply_session_publication_patch(
        sessions, session_id="2001", status="UNAPPROVED"
    )
    emp = _compose(sessions)
    assert emp["orders_completed"] == 4
    assert emp["all_visible_orders_completed"] == 12
    assert emp["dashboard_rankable"] is False

    # Re-approve WF-01 → full day
    sessions = apply_session_publication_patch(
        sessions, session_id="2001", status="APPROVED"
    )
    emp = _compose(sessions)
    assert emp["orders_completed"] == 12
    assert abs(float(emp["lbs_per_hour"]) - 48.0) < 0.01
    assert emp["dashboard_rankable"] is True

    # Edit Day avg weight applies once to approved bags
    emp = _compose(sessions, average_weight_override=54.0)
    assert emp["orders_completed"] == 12
    assert emp["total_pre_lbs"] == 648.0


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
    assert any(s["session_code"] == "WF-01" for s in emp["sessions"])


def test_tarannum_approved_subset_sequence():
    """Exact live case: 1 approved + 2 pending → ~64.9; then approve cascade."""
    sessions = [
        _sess(
            sid="1",
            code="WF-01",
            status="UNAPPROVED",
            bags=8,
            lbs=205.0,
            hours=4.7,
            end="2026-09-21T12:00:00",
            employee="Tarannum",
        ),
        _sess(
            sid="2",
            code="WF-02",
            status="UNAPPROVED",
            bags=3,
            lbs=48.0,
            hours=0.9,
            end="2026-09-21T13:00:00",
            employee="Tarannum",
        ),
        _sess(
            sid="3",
            code="WF-03",
            status="APPROVED",
            bags=4,
            lbs=100.0,
            hours=1.5,
            end="2026-09-21T15:00:00",
            employee="Tarannum",
        ),
    ]

    def compose(sess):
        return compose_employee_day_from_sessions(
            employee_name="Tarannum",
            employee_user_id=7,
            sessions=sess,
            selected_date_et=TARANNUM_DAY,
        )

    # Start: WF-03 only
    emp = compose(sessions)
    assert len(emp["sessions"]) == 3
    assert emp["day_publication_status"] == "PARTIALLY_APPROVED"
    assert emp["dashboard_rankable"] is False
    assert emp["orders_completed"] == 4
    assert emp["total_pre_lbs"] == 100.0
    assert emp["performance_hours"] == 1.5
    assert abs(float(emp["lbs_per_hour"]) - (100.0 / 1.5)) < 0.05  # ~66.67; live may round 64.9
    assert emp["all_visible_orders_completed"] == 15
    assert abs(float(emp["all_visible_total_pre_lbs"]) - 353.0) < 0.01
    assert abs(float(emp["all_visible_performance_hours"]) - 7.1) < 0.01

    day = {"employees": [emp], "summary": {}}
    partition_employees_by_exclusion(day)
    assert day["summary_approved"]["employee_day_count"] == 0  # not Published

    # Approve WF-01 → WF-01 + WF-03
    sessions = apply_session_publication_patch(
        sessions, session_id="1", status="APPROVED"
    )
    emp = compose(sessions)
    assert emp["orders_completed"] == 12  # 8+4
    assert abs(float(emp["total_pre_lbs"]) - 305.0) < 0.01  # 205+100
    assert abs(float(emp["performance_hours"]) - 6.2) < 0.01  # 4.7+1.5
    assert abs(float(emp["lbs_per_hour"]) - (305.0 / 6.2)) < 0.05
    assert emp["pending_session_count"] == 1
    assert emp["dashboard_rankable"] is False

    # Approve WF-02 → full day ~49.7
    sessions = apply_session_publication_patch(
        sessions, session_id="2", status="APPROVED"
    )
    emp = compose(sessions)
    assert emp["orders_completed"] == 15
    assert abs(float(emp["total_pre_lbs"]) - 353.0) < 0.01
    assert abs(float(emp["performance_hours"]) - 7.1) < 0.01
    assert abs(float(emp["lbs_per_hour"]) - (353.0 / 7.1)) < 0.05  # ~49.7
    assert emp["day_publication_status"] == "APPROVED"
    assert emp["dashboard_rankable"] is True

    day = {"employees": [emp], "summary": {}}
    partition_employees_by_exclusion(day)
    assert day["summary_approved"]["employee_day_count"] == 1
    assert abs(float(day["summary_approved"]["lbs_per_hour"]) - (353.0 / 7.1)) < 0.05

    # Disapprove WF-01 → back to WF-02+WF-03
    sessions = apply_session_publication_patch(
        sessions, session_id="1", status="UNAPPROVED"
    )
    emp = compose(sessions)
    assert emp["orders_completed"] == 7  # 3+4
    assert abs(float(emp["total_pre_lbs"]) - 148.0) < 0.01
    assert abs(float(emp["performance_hours"]) - 2.4) < 0.01
    assert abs(float(emp["lbs_per_hour"]) - (148.0 / 2.4)) < 0.05
    assert emp["dashboard_rankable"] is False
    assert len(emp["sessions"]) == 3  # still visible

    # Exclude WF-01 → zero contribution; Performance still WF-02+WF-03
    sessions = apply_session_publication_patch(
        sessions, session_id="1", status="EXCLUDED"
    )
    emp = compose(sessions)
    assert emp["excluded_session_count"] == 1
    assert emp["orders_completed"] == 7
    assert any(
        s.get("session_code") == "WF-01"
        and (s.get("publication_status") or "") == "EXCLUDED"
        for s in emp["sessions"]
    )

    # Include then leave pending → still WF-02+WF-03 for Performance
    sessions = apply_session_publication_patch(
        sessions, session_id="1", status="UNAPPROVED"
    )
    emp = compose(sessions)
    assert emp["orders_completed"] == 7
    assert emp["all_visible_orders_completed"] == 15
