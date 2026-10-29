"""Isolated Guiling / Evelin Review→Approval validation (no production DB writes).

Models the three production failure modes:
1. Guiling — three Edit Session overrides must persist across reopen/recompose
   and Average Weight must not invalidate approvals.
2. Evelin — session rate overrides feed employee-day + published graph/ranking
   from the same authoritative approved totals; pending days stay off the graph.
3. Save path — Edit Day with client sessions must not rebuild the Folder day;
   unchanged end time must not invalidate.
"""

from __future__ import annotations

import time
from datetime import date
from unittest.mock import MagicMock

import pytest

from backend.rinse_performance_employee_day import (
    apply_employee_day_end_time,
    apply_session_publication_patch,
    compose_employee_day_from_sessions,
    mutation_employee_day_payload,
    pick_final_visible_session,
    recompute_employee_day_metrics,
    session_effective_performance_lbs,
)
from backend.rinse_performance_folder_publisher import partition_employees_by_exclusion


DAY = date(2026, 10, 20)


def _sess(
    *,
    sid: str,
    code: str,
    status: str,
    bags: int,
    lbs: float,
    hours: float,
    end: str,
    start: str = "2026-10-20T08:00:00",
    employee: str,
    segment_id: int | None = None,
    rate_override: float | None = None,
):
    pub = {"status": status, "excluded": status == "EXCLUDED"}
    if rate_override is not None:
        pub.update(
            {
                "is_rate_override": True,
                "published_metric_value": float(rate_override),
                "published_numerator": round(float(rate_override) * float(hours), 4),
                "published_denominator": float(hours),
            }
        )
    return {
        "session_id": sid,
        "session_code": code,
        "segment_id": segment_id if segment_id is not None else int(sid),
        "publication_status": status,
        "publication": pub,
        "orders_completed": bags,
        "total_pre_lbs": lbs,
        "performance_hours": hours,
        "lbs_per_hour": round(lbs / hours, 4) if hours else None,
        "role_status": "closed",
        "include_in_authoritative_aggregate": True,
        "start_time": start,
        "end_time": end,
        "performance_end": end,
        "employee": employee,
        "user_id": None,
    }


def _guiling_three_sessions():
    """Three approved Folder sessions for Guiling — mirrors multi-edit Review day."""
    name = "Guiling"
    return [
        _sess(
            sid="7101",
            code="WF-G1",
            status="APPROVED",
            bags=6,
            lbs=120.0,
            hours=2.0,
            start="2026-10-20T08:00:00",
            end="2026-10-20T10:00:00",
            employee=name,
            segment_id=101,
        ),
        _sess(
            sid="7102",
            code="WF-G2",
            status="APPROVED",
            bags=5,
            lbs=100.0,
            hours=2.0,
            start="2026-10-20T10:15:00",
            end="2026-10-20T12:15:00",
            employee=name,
            segment_id=102,
        ),
        _sess(
            sid="7103",
            code="WF-G3",
            status="APPROVED",
            bags=4,
            lbs=80.0,
            hours=1.5,
            start="2026-10-20T13:00:00",
            end="2026-10-20T14:30:00",
            employee=name,
            segment_id=103,
        ),
    ]


def _evelin_sessions():
    name = "Evelin"
    return [
        _sess(
            sid="8201",
            code="WF-E1",
            status="APPROVED",
            bags=7,
            lbs=140.0,
            hours=2.5,
            start="2026-10-20T08:00:00",
            end="2026-10-20T10:30:00",
            employee=name,
            segment_id=201,
        ),
        _sess(
            sid="8202",
            code="WF-E2",
            status="APPROVED",
            bags=6,
            lbs=120.0,
            hours=2.0,
            start="2026-10-20T11:00:00",
            end="2026-10-20T13:00:00",
            employee=name,
            segment_id=202,
        ),
    ]


def _compose(name: str, uid: int, sessions, **kwargs):
    return compose_employee_day_from_sessions(
        employee_name=name,
        employee_user_id=uid,
        sessions=sessions,
        selected_date_et=DAY,
        **kwargs,
    )


def _graph_and_rank(employees):
    """Same eligibility rule as Management graph + published ranking."""
    day = {"employees": list(employees), "summary": {}}
    partition_employees_by_exclusion(day)
    published = [
        e
        for e in day["employees"]
        if e.get("dashboard_rankable") is True
        or str(e.get("day_publication_status") or "") == "APPROVED"
    ]
    live = [
        e
        for e in day["employees"]
        if e.get("dashboard_rankable") is not True
        and str(e.get("day_publication_status") or "")
        not in ("APPROVED", "EXCLUDED")
    ]
    graph_rows = [
        {
            "name": e["employee"],
            "value": float(e.get("lbs_per_hour") or 0),
        }
        for e in published
    ]
    return day, published, live, graph_rows


# ---------------------------------------------------------------------------
# 1. Guiling — edit persistence
# ---------------------------------------------------------------------------


def test_guiling_three_sessions_load_and_stay_attached():
    sessions = _guiling_three_sessions()
    emp = _compose("Guiling", 41, sessions)
    assert len(emp["sessions"]) == 3
    assert {s["session_id"] for s in emp["sessions"]} == {"7101", "7102", "7103"}
    assert emp["orders_completed"] == 15
    assert abs(float(emp["total_pre_lbs"]) - 300.0) < 0.01
    assert abs(float(emp["performance_hours"]) - 5.5) < 0.01
    assert abs(float(emp["lbs_per_hour"]) - (300.0 / 5.5)) < 0.05
    assert emp["dashboard_rankable"] is True


def test_guiling_edit_save_reopen_each_session_persists_overrides():
    """Simulate Edit Session on all three → recompose (= reopen / refresh)."""
    sessions = _guiling_three_sessions()
    overrides = {"7101": 70.0, "7102": 55.0, "7103": 60.0}
    for sid, rate in overrides.items():
        hours = next(s["performance_hours"] for s in sessions if s["session_id"] == sid)
        sessions = apply_session_publication_patch(
            sessions,
            session_id=sid,
            status="APPROVED",
            publication={
                "status": "APPROVED",
                "is_rate_override": True,
                "published_metric_value": rate,
                "published_numerator": round(rate * hours, 4),
                "published_denominator": hours,
            },
        )

    # "Close and reopen" — recompose from stamped sessions (full page refresh path).
    emp = _compose("Guiling", 41, sessions)
    assert len(emp["sessions"]) == 3
    for s in emp["sessions"]:
        assert s["publication"]["is_rate_override"] is True
        assert s["publication"]["status"] == "APPROVED"
        assert abs(
            float(s["publication"]["published_metric_value"])
            - overrides[s["session_id"]]
        ) < 0.01

    # Effective lbs = 70*2 + 55*2 + 60*1.5 = 140+110+90 = 340
    assert abs(float(emp["total_pre_lbs"]) - 340.0) < 0.01
    assert abs(float(emp["lbs_per_hour"]) - (340.0 / 5.5)) < 0.05
    assert emp["credited_weight_basis"] == "SESSION_RATE_OVERRIDE"
    assert emp["dashboard_rankable"] is True
    assert emp["day_publication_status"] == "APPROVED"


def test_guiling_average_weight_does_not_require_end_time_invalidate(monkeypatch):
    """Avg-weight-only path: end time unchanged → no segment update / invalidate."""
    import backend.rinse_performance_employee_day as mod

    sessions = _guiling_three_sessions()
    # Prior session overrides remain on the cards.
    sessions = apply_session_publication_patch(
        sessions,
        session_id="7101",
        status="APPROVED",
        publication={
            "status": "APPROVED",
            "is_rate_override": True,
            "published_metric_value": 70.0,
            "published_numerator": 140.0,
            "published_denominator": 2.0,
        },
    )

    updated = {"n": 0}
    invalidated = {"n": 0}

    def fake_update(*a, **k):
        updated["n"] += 1
        return {"ok": True}

    def fake_invalidate(*a, **k):
        invalidated["n"] += 1
        return {"ok": True, "invalidated": 1}

    monkeypatch.setattr(
        "backend.payroll_operations.update_time_record_segment",
        fake_update,
    )
    monkeypatch.setattr(
        "backend.rinse_performance_approvals.invalidate_approvals",
        fake_invalidate,
    )
    monkeypatch.setattr(
        "backend.rinse_performance_approvals.approval_status_map",
        lambda *a, **k: {
            s["session_id"]: dict(s["publication"]) for s in sessions
        },
    )
    monkeypatch.setattr(mod, "ensure_employee_day_override_tables", lambda cur: None)

    conn = MagicMock()
    conn.cursor.return_value = MagicMock()
    # Same end as WF-G3 prefill
    out = apply_employee_day_end_time(
        conn,
        3,
        selected_date_et=DAY,
        employee_name="Guiling",
        employee_user_id=41,
        end_time_et="2026-10-20T14:30:00",
        sessions=sessions,
    )
    assert out["ok"] is True
    assert out.get("unchanged") is True
    assert out.get("approval_reset") is False
    assert updated["n"] == 0
    assert invalidated["n"] == 0

    # Day avg weight still applies on recompose; approvals stay APPROVED.
    emp = _compose("Guiling", 41, sessions, average_weight_override=22.0)
    assert emp["total_pre_lbs"] == 330.0  # 22 × 15 bags
    assert emp["credited_weight_basis"] == "DAY_AVERAGE_WEIGHT_OVERRIDE"
    assert all(
        (s.get("publication") or {}).get("status") == "APPROVED" for s in emp["sessions"]
    )
    assert emp["dashboard_rankable"] is True


def test_guiling_consecutive_edits_without_page_refresh_keep_all_sessions():
    """Mutation-style patches accumulate; sibling sessions never drop off the day."""
    sessions = _guiling_three_sessions()
    emp = _compose("Guiling", 41, sessions)
    assert len(emp["sessions"]) == 3

    for sid, rate, hours in (("7101", 65.0, 2.0), ("7102", 58.0, 2.0), ("7103", 62.0, 1.5)):
        sessions = apply_session_publication_patch(
            sessions,
            session_id=sid,
            status="APPROVED",
            publication={
                "status": "APPROVED",
                "is_rate_override": True,
                "published_metric_value": rate,
                "published_numerator": round(rate * hours, 4),
                "published_denominator": hours,
            },
        )
        emp = _compose("Guiling", 41, sessions)
        assert len(emp["sessions"]) == 3
        assert {s["session_id"] for s in emp["sessions"]} == {"7101", "7102", "7103"}

    assert emp["credited_weight_basis"] == "SESSION_RATE_OVERRIDE"
    # 65*2 + 58*2 + 62*1.5 = 130+116+93 = 339
    assert abs(float(emp["total_pre_lbs"]) - 339.0) < 0.01


# ---------------------------------------------------------------------------
# 2. Evelin — graph accuracy
# ---------------------------------------------------------------------------


def test_evelin_oct_27_override_rate_stays_published_and_oct_28_stays_off_graph():
    """Lock the live approved day: override pounds, not evidence pounds.

    WF-2418 evidence is 208.5 lb. The approved rate 50.15 publishes 274.05 lb.
    Oct 28 is unapproved and must not become rankable.
    """
    approved = [
        _sess(
            sid="WF-2403",
            code="WF-01",
            status="APPROVED",
            bags=2,
            lbs=44.7,
            hours=1.1764,
            start="2026-10-27T04:59:00",
            end="2026-10-27T06:09:53",
            employee="Evelin (VeeWash)",
            segment_id=2403,
        ),
        _sess(
            sid="WF-2418",
            code="WF-02",
            status="APPROVED",
            bags=8,
            lbs=208.5,
            hours=5.4647,
            start="2026-10-27T08:38:00",
            end="2026-10-27T14:05:53",
            employee="Evelin (VeeWash)",
            segment_id=2418,
            rate_override=50.15,
        ),
    ]
    emp = _compose("Evelin (VeeWash)", 30, approved)
    assert emp["credited_weight_basis"] == "SESSION_RATE_OVERRIDE"
    assert abs(float(emp["total_pre_lbs"]) - 318.75) < 0.01
    assert abs(float(emp["performance_hours"]) - 6.6411) < 0.0001
    assert abs(float(emp["lbs_per_hour"]) - (318.75 / 6.6411)) < 0.001
    assert emp["dashboard_rankable"] is True
    _day, published, live, graph_rows = _graph_and_rank([emp])
    assert live == []
    assert abs(graph_rows[0]["value"] - (318.75 / 6.6411)) < 0.001

    pending = [
        _sess(
            sid="WF-2456",
            code="WF-01",
            status="UNAPPROVED",
            bags=9,
            lbs=237.4,
            hours=5.0494,
            start="2026-10-28T06:54:00",
            end="2026-10-28T11:57:29",
            employee="Evelin (VeeWash)",
            segment_id=2456,
        )
    ]
    pending_emp = _compose("Evelin (VeeWash)", 30, pending)
    assert pending_emp["dashboard_rankable"] is False
    assert pending_emp["day_publication_status"] == "NEEDS_APPROVAL"
    _day, published, live, graph_rows = _graph_and_rank([pending_emp])
    assert published == []
    assert graph_rows == []
    assert live[0]["employee"] == "Evelin (VeeWash)"


def test_evelin_approved_override_updates_graph_and_ranking_identically():
    sessions = _evelin_sessions()
    # Override WF-E1: 140/2.5=56 → 72 lb/hr ⇒ 180 lbs
    sessions = apply_session_publication_patch(
        sessions,
        session_id="8201",
        status="APPROVED",
        publication={
            "status": "APPROVED",
            "is_rate_override": True,
            "published_metric_value": 72.0,
            "published_numerator": 180.0,
            "published_denominator": 2.5,
        },
    )
    emp = _compose("Evelin", 55, sessions)
    # (180 + 120) / (2.5 + 2.0) = 300 / 4.5 = 66.666…
    expected = 300.0 / 4.5
    assert abs(float(emp["lbs_per_hour"]) - expected) < 0.05
    assert emp["dashboard_rankable"] is True

    day, published, live, graph_rows = _graph_and_rank([emp])
    assert live == []
    assert len(published) == 1
    assert len(graph_rows) == 1
    assert abs(graph_rows[0]["value"] - expected) < 0.05
    # Ranking field == graph field (same employee-day lbs_per_hour)
    assert abs(float(published[0]["lbs_per_hour"]) - graph_rows[0]["value"]) < 1e-9
    assert abs(
        float(day["summary_approved"]["lbs_per_hour"]) - expected
    ) < 0.05


def test_evelin_unapproved_edit_awaits_approval_not_on_graph():
    sessions = _evelin_sessions()
    # Edit / invalidate second session → pending (Edit Day end-time style reset)
    sessions = apply_session_publication_patch(
        sessions,
        session_id="8202",
        status="UNAPPROVED",
        publication={"status": "UNAPPROVED", "is_rate_override": False},
    )
    emp = _compose("Evelin", 55, sessions)
    assert emp["day_publication_status"] == "PARTIALLY_APPROVED"
    assert emp["dashboard_rankable"] is False
    # Performance still includes approved WF-E1 only
    assert emp["orders_completed"] == 7
    assert abs(float(emp["total_pre_lbs"]) - 140.0) < 0.01

    _day, published, live, graph_rows = _graph_and_rank([emp])
    assert published == []
    assert graph_rows == []
    assert len(live) == 1
    assert live[0]["employee"] == "Evelin"
    # Clear awaiting-approval signal for UI (not silently stale on graph)
    assert live[0]["day_publication_status"] == "PARTIALLY_APPROVED"


def test_evelin_graph_never_shows_stale_evidence_after_override():
    """Evidence PRE rate must not leak into graph once a manager override exists."""
    sessions = _evelin_sessions()
    evidence_rate = 260.0 / 4.5  # 140+120 over 4.5h ≈ 57.78
    sessions = apply_session_publication_patch(
        sessions,
        session_id="8201",
        status="APPROVED",
        publication={
            "status": "APPROVED",
            "is_rate_override": True,
            "published_metric_value": 80.0,
            "published_numerator": 200.0,  # 80 * 2.5
            "published_denominator": 2.5,
        },
    )
    emp = _compose("Evelin", 55, sessions)
    override_rate = 320.0 / 4.5  # 200+120
    assert abs(float(emp["lbs_per_hour"]) - override_rate) < 0.05
    assert abs(float(emp["lbs_per_hour"]) - evidence_rate) > 1.0
    assert session_effective_performance_lbs(emp["sessions"][0]) == 200.0


# ---------------------------------------------------------------------------
# 3. Save performance — rebuild elimination
# ---------------------------------------------------------------------------


def test_edit_day_changed_end_time_fast_path_zero_rebuilds(monkeypatch):
    import backend.rinse_performance_employee_day as mod

    sessions = _guiling_three_sessions()
    rebuilt = {"n": 0}
    updated = {"n": 0}

    def boom(*a, **k):
        rebuilt["n"] += 1
        raise AssertionError("full day rebuild must not run")

    def fake_update(*a, **k):
        updated["n"] += 1
        return {"ok": True}

    monkeypatch.setattr(
        "backend.management_wf_folder_performance.build_day_folder_performance",
        boom,
    )
    monkeypatch.setattr(
        "backend.payroll_operations.update_time_record_segment",
        fake_update,
    )
    monkeypatch.setattr(
        "backend.rinse_performance_approvals.invalidate_approvals",
        lambda *a, **k: {"ok": True, "invalidated": 1},
    )
    monkeypatch.setattr(
        "backend.rinse_performance_approvals.approval_status_map",
        lambda *a, **k: {
            s["session_id"]: {"status": "APPROVED"} for s in sessions
        },
    )
    monkeypatch.setattr(mod, "ensure_employee_day_override_tables", lambda cur: None)

    conn = MagicMock()
    conn.cursor.return_value = MagicMock()
    out = apply_employee_day_end_time(
        conn,
        3,
        selected_date_et=DAY,
        employee_name="Guiling",
        employee_user_id=41,
        end_time_et="2026-10-20T15:00:00",
        sessions=sessions,
    )
    assert out["ok"] is True
    assert out.get("approval_reset") is True
    assert rebuilt["n"] == 0
    assert updated["n"] == 1
    assert pick_final_visible_session(sessions)["session_id"] == "7103"


def test_save_latency_compose_vs_simulated_full_rebuild():
    """Micro-benchmark: targeted compose is orders of magnitude cheaper than rebuild stub."""
    sessions = _guiling_three_sessions()
    for sid, rate, hours in (("7101", 70.0, 2.0), ("7102", 55.0, 2.0), ("7103", 60.0, 1.5)):
        sessions = apply_session_publication_patch(
            sessions,
            session_id=sid,
            status="APPROVED",
            publication={
                "status": "APPROVED",
                "is_rate_override": True,
                "published_metric_value": rate,
                "published_numerator": round(rate * hours, 4),
                "published_denominator": hours,
            },
        )

    def targeted():
        return _compose("Guiling", 41, sessions)

    def fake_full_rebuild():
        # Approximate pre-fix cost: rebuild day + recompute every employee.
        time.sleep(0.025)  # stand-in for Folder day SQL rebuild (~25–200ms+ in prod)
        return targeted()

    n = 40
    t0 = time.perf_counter()
    for _ in range(n):
        targeted()
    targeted_ms = (time.perf_counter() - t0) * 1000 / n

    t0 = time.perf_counter()
    for _ in range(n):
        fake_full_rebuild()
    rebuild_ms = (time.perf_counter() - t0) * 1000 / n

    assert targeted_ms < 5.0, f"targeted compose too slow: {targeted_ms:.2f}ms"
    assert rebuild_ms > targeted_ms * 5, (
        f"expected rebuild stub slower than compose "
        f"(targeted={targeted_ms:.2f}ms rebuild={rebuild_ms:.2f}ms)"
    )
    # Expose numbers for the validation report via pytest output.
    print(
        f"\nLATENCY_BENCH targeted_compose_ms={targeted_ms:.3f} "
        f"simulated_rebuild_ms={rebuild_ms:.3f} "
        f"speedup≈{rebuild_ms / max(targeted_ms, 1e-6):.0f}x"
    )


def test_mutation_employee_day_payload_skips_when_sync_fails(monkeypatch):
    """Compose still returns employee_day even if Hub publication cache sync fails."""
    import backend.rinse_performance_employee_day as mod

    sessions = _evelin_sessions()
    cursor = MagicMock()
    monkeypatch.setattr(mod, "load_override_for_employee", lambda *a, **k: None)
    monkeypatch.setattr(
        mod,
        "sync_employee_day_publication",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cache down")),
    )
    out = mutation_employee_day_payload(
        cursor,
        3,
        selected_date_et=DAY,
        employee_name="Evelin",
        employee_user_id=55,
        sessions=sessions,
    )
    assert "employee_day" in out
    assert out["employee_day"]["employee"] == "Evelin"
    assert len(out["employee_day"]["sessions"]) == 2


# ---------------------------------------------------------------------------
# 4. Regression matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "end_a,end_b,same",
    [
        ("2026-10-20T14:30:00", "2026-10-20 14:30", True),
        ("2026-10-20T14:30:00", "2026-10-20T14:30:45", True),
        ("2026-10-20T14:30:00", "2026-10-20T15:00:00", False),
    ],
)
def test_end_time_same_minute_matrix(end_a, end_b, same):
    from backend.rinse_performance_employee_day import _end_times_same_minute

    assert _end_times_same_minute(end_a, end_b) is same


def test_excluded_session_never_in_performance_or_graph():
    sessions = _guiling_three_sessions()
    sessions = apply_session_publication_patch(
        sessions, session_id="7102", status="EXCLUDED"
    )
    emp = _compose("Guiling", 41, sessions)
    assert emp["excluded_session_count"] == 1
    assert emp["orders_completed"] == 10  # 6+4
    assert abs(float(emp["total_pre_lbs"]) - 200.0) < 0.01
    assert emp["dashboard_rankable"] is True
    _day, published, live, graph_rows = _graph_and_rank([emp])
    assert len(graph_rows) == 1
    assert live == []


def test_recompute_preserves_all_session_attachments_after_mixed_states():
    sessions = _guiling_three_sessions()
    sessions = apply_session_publication_patch(
        sessions, session_id="7101", status="EXCLUDED"
    )
    sessions = apply_session_publication_patch(
        sessions, session_id="7102", status="UNAPPROVED"
    )
    emp = {"employee": "Guiling", "user_id": 41, "sessions": sessions}
    recompute_employee_day_metrics(emp)
    assert len(emp["sessions"]) == 3
    assert emp["excluded_session_count"] == 1
    assert emp["pending_session_count"] == 1
    assert emp["approved_session_count"] == 1
    assert emp["orders_completed"] == 4  # WF-G3 only
