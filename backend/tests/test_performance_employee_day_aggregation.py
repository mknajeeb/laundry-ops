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


def test_include_as_unapproved_does_not_restore_performance():
    """Include returns visibility; Performance waits until APPROVED."""
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
    # Still only WF-01 contributes to Performance
    assert emp["orders_completed"] == 10
    assert emp["total_pre_lbs"] == 100.0
    assert emp["all_visible_orders_completed"] == 15
    sessions[1]["publication_status"] = "APPROVED"
    sessions[1]["publication"] = {"status": "APPROVED"}
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


def test_angelica_average_weight_set_change_remove_restores_calculated():
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
    recompute_employee_day_metrics(emp)
    assert emp["total_pre_lbs"] == 286.0
    base_rate = float(emp["lbs_per_hour"])

    recompute_employee_day_metrics(emp, average_weight_override=20.0)
    assert emp["total_pre_lbs"] == 300.0
    assert emp["calculated_total_pre_lbs"] == 286.0
    assert abs(float(emp["lbs_per_hour"]) - (300.0 / 6.1)) < 0.05

    recompute_employee_day_metrics(emp, average_weight_override=18.0)
    assert emp["total_pre_lbs"] == 270.0  # 18 × 15 once

    recompute_employee_day_metrics(emp, average_weight_override=None)
    assert emp["total_pre_lbs"] == 286.0
    assert emp["day_average_weight_is_override"] is False
    assert abs(float(emp["lbs_per_hour"]) - base_rate) < 0.001


def test_pick_final_uses_chronology_not_session_id_or_array_order():
    """Higher session_id earlier in day must not win over later included end."""
    sessions = [
        _sess(
            sid="9999",
            code="WF-A",
            status="APPROVED",
            bags=1,
            lbs=10,
            hours=2.0,
            start="2026-09-10T08:00:00",
            end="2026-09-10T10:00:00",
            segment_id=1,
        ),
        _sess(
            sid="100",
            code="WF-B",
            status="APPROVED",
            bags=1,
            lbs=10,
            hours=3.5,
            start="2026-09-10T10:30:00",
            end="2026-09-10T14:00:00",
            segment_id=2,
        ),
        _sess(
            sid="5000",
            code="WF-C",
            status="EXCLUDED",
            bags=1,
            lbs=10,
            hours=2.0,
            start="2026-09-10T14:00:00",
            end="2026-09-10T16:00:00",
            segment_id=3,
        ),
    ]
    # Array order reversed intentionally
    sessions = list(reversed(sessions))
    final = pick_final_included_session(sessions)
    assert final["session_id"] == "100"
    assert final["segment_id"] == 2
    assert final["session_code"] == "WF-B"


def test_edit_day_end_time_targets_final_included_only(monkeypatch):
    from datetime import date
    from unittest.mock import MagicMock
    import backend.rinse_performance_employee_day as mod

    day = {
        "selected_date_et": "2026-09-10",
        "employees": [
            {
                "employee": "Worker",
                "user_id": 7,
                "sessions": [
                    _sess(
                        sid="11",
                        code="WF-A",
                        status="APPROVED",
                        bags=1,
                        lbs=10,
                        hours=2.0,
                        start="2026-09-10T08:00:00",
                        end="2026-09-10T10:00:00",
                        segment_id=101,
                    ),
                    _sess(
                        sid="22",
                        code="WF-B",
                        status="APPROVED",
                        bags=1,
                        lbs=10,
                        hours=3.5,
                        start="2026-09-10T10:30:00",
                        end="2026-09-10T14:00:00",
                        segment_id=202,
                    ),
                    _sess(
                        sid="33",
                        code="WF-C",
                        status="EXCLUDED",
                        bags=1,
                        lbs=10,
                        hours=2.0,
                        start="2026-09-10T14:00:00",
                        end="2026-09-10T16:00:00",
                        segment_id=303,
                    ),
                ],
            }
        ],
    }

    calls = {}

    def fake_update(conn, org, session_id, segment_id, **kwargs):
        calls["session_id"] = session_id
        calls["segment_id"] = segment_id
        calls["ended_at"] = kwargs.get("ended_at")
        return {"ok": True}

    def fake_build(*a, **k):
        return day

    monkeypatch.setattr(mod, "build_day_folder_performance", fake_build, raising=False)
    monkeypatch.setattr(
        "backend.management_wf_folder_performance.build_day_folder_performance",
        fake_build,
    )
    monkeypatch.setattr(
        "backend.rinse_performance_folder_publisher.attach_publication_status_to_day",
        lambda *a, **k: day,
    )
    monkeypatch.setattr(
        "backend.payroll_operations.update_time_record_segment",
        fake_update,
    )
    monkeypatch.setattr(
        "backend.rinse_performance_approvals.invalidate_approvals",
        lambda *a, **k: {"ok": True, "invalidated": 1},
    )
    monkeypatch.setattr(mod, "ensure_employee_day_override_tables", lambda cur: None)
    monkeypatch.setattr(mod, "apply_publication_and_day_metrics", lambda *a, **k: day)

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur

    out = mod.apply_employee_day_end_time(
        conn,
        3,
        selected_date_et=date(2026, 9, 10),
        employee_name="Worker",
        employee_user_id=7,
        end_time_et="2026-09-10T14:30:00",
        actor_user_id=1,
        actor_name="mgr",
        day=day,
    )
    assert out["ok"] is True
    assert calls["session_id"] == 22
    assert calls["segment_id"] == 202
    assert "14:30" in str(calls["ended_at"])


def test_edit_day_end_time_rejects_overlap(monkeypatch):
    from datetime import date
    from unittest.mock import MagicMock
    import backend.rinse_performance_employee_day as mod

    day = {
        "selected_date_et": "2026-09-10",
        "employees": [
            {
                "employee": "Worker",
                "user_id": 7,
                "sessions": [
                    _sess(
                        sid="22",
                        code="WF-B",
                        status="APPROVED",
                        bags=1,
                        lbs=10,
                        hours=3.5,
                        start="2026-09-10T10:30:00",
                        end="2026-09-10T14:00:00",
                        segment_id=202,
                    ),
                ],
            }
        ],
    }

    def boom(*a, **k):
        raise ValueError(
            "Role segments overlap. Adjust start/end times so segments do not overlap."
        )

    monkeypatch.setattr(
        "backend.rinse_performance_folder_publisher.attach_publication_status_to_day",
        lambda *a, **k: day,
    )
    monkeypatch.setattr(mod, "apply_publication_and_day_metrics", lambda *a, **k: day)
    monkeypatch.setattr(mod, "ensure_employee_day_override_tables", lambda cur: None)
    monkeypatch.setattr(
        "backend.payroll_operations.update_time_record_segment",
        boom,
    )

    conn = MagicMock()
    conn.cursor.return_value = MagicMock()
    out = mod.apply_employee_day_end_time(
        conn,
        3,
        selected_date_et=date(2026, 9, 10),
        employee_name="Worker",
        employee_user_id=7,
        end_time_et="2026-09-10T09:00:00",
        day=day,
    )
    assert out["ok"] is False
    assert out["status"] == "segment_update_failed"
    assert "overlap" in str(out.get("error") or "").lower()


def test_employee_day_override_key_prefers_user_id():
    from backend.rinse_performance_employee_day import employee_day_override_key

    a = employee_day_override_key(employee_user_id=10, employee_name="Same Name")
    b = employee_day_override_key(employee_user_id=11, employee_name="Same Name")
    assert a == "u:10"
    assert b == "u:11"
    assert a != b


def test_disapprove_drops_performance_metrics_keeps_session_visible():
    """UNAPPROVE removes contribution from Performance; session remains in the day."""
    sessions = [
        _sess(
            sid="1",
            code="WF-01",
            status="APPROVED",
            bags=15,
            lbs=286,
            hours=6.1,
        ),
        _sess(
            sid="2",
            code="WF-02",
            status="EXCLUDED",
            bags=1,
            lbs=27,
            hours=4.2,
            end="2026-09-10T16:00:00",
        ),
    ]
    emp = {"employee": "A", "user_id": 1, "sessions": sessions}
    recompute_employee_day_metrics(emp)
    assert emp["orders_completed"] == 15
    assert abs(float(emp["lbs_per_hour"]) - (286.0 / 6.1)) < 0.01
    assert derive_employee_day_publication_status(sessions)["status"] == "APPROVED"

    sessions[0]["publication_status"] = "UNAPPROVED"
    sessions[0]["publication"] = {"status": "UNAPPROVED"}
    recompute_employee_day_metrics(emp)
    assert emp["orders_completed"] == 0
    assert emp["total_pre_lbs"] == 0
    assert emp["performance_hours"] is None or emp["performance_hours"] == 0
    assert emp["lbs_per_hour"] is None
    assert len(emp.get("sessions") or sessions) >= 1
    assert derive_employee_day_publication_status(sessions)["status"] == "NEEDS_APPROVAL"

    sessions[0]["publication_status"] = "APPROVED"
    sessions[0]["publication"] = {"status": "APPROVED"}
    recompute_employee_day_metrics(emp)
    assert emp["orders_completed"] == 15
    assert abs(float(emp["lbs_per_hour"]) - (286.0 / 6.1)) < 0.01
    assert derive_employee_day_publication_status(sessions)["status"] == "APPROVED"


def test_avg_weight_does_not_mutate_session_bag_lbs():
    """Override may recompute day lbs from bags; approved-session bag lbs stay intact."""
    s1 = _sess(sid="1", code="A", status="APPROVED", bags=15, lbs=286, hours=6.1)
    s2 = _sess(
        sid="2",
        code="B",
        status="EXCLUDED",
        bags=1,
        lbs=27,
        hours=4.2,
        end="2026-09-10T16:00:00",
    )
    emp = {"employee": "A", "sessions": [s1, s2]}
    recompute_employee_day_metrics(emp, average_weight_override=20.0)
    assert s1["total_pre_lbs"] == 286
    assert s2["total_pre_lbs"] == 27
    # Only APPROVED session contributes: 15 bags * 20 override
    assert emp["total_pre_lbs"] == 300.0
    assert emp["orders_completed"] == 15
