"""Count expensive Folder day rebuilds on Edit Session / Edit Day save paths."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import backend.rinse_performance_employee_day as emp_day
from backend.rinse_performance_employee_day import (
    apply_employee_day_end_time,
    mutation_employee_day_payload,
)


DAY = date(2026, 10, 20)


def _sessions():
    return [
        {
            "session_id": "7101",
            "session_code": "WF-G1",
            "segment_id": 101,
            "publication_status": "APPROVED",
            "publication": {
                "status": "APPROVED",
                "is_rate_override": True,
                "published_metric_value": 70.0,
                "published_numerator": 140.0,
                "published_denominator": 2.0,
            },
            "orders_completed": 6,
            "total_pre_lbs": 120.0,
            "performance_hours": 2.0,
            "role_status": "closed",
            "include_in_authoritative_aggregate": True,
            "start_time": "2026-10-20T08:00:00",
            "end_time": "2026-10-20T10:00:00",
            "performance_end": "2026-10-20T10:00:00",
            "employee": "Guiling",
        },
        {
            "session_id": "7103",
            "session_code": "WF-G3",
            "segment_id": 103,
            "publication_status": "APPROVED",
            "publication": {"status": "APPROVED"},
            "orders_completed": 4,
            "total_pre_lbs": 80.0,
            "performance_hours": 1.5,
            "role_status": "closed",
            "include_in_authoritative_aggregate": True,
            "start_time": "2026-10-20T13:00:00",
            "end_time": "2026-10-20T14:30:00",
            "performance_end": "2026-10-20T14:30:00",
            "employee": "Guiling",
        },
    ]


def test_edit_session_mutation_payload_zero_folder_rebuilds(monkeypatch):
    rebuilt = {"n": 0}

    def boom(*a, **k):
        rebuilt["n"] += 1
        raise AssertionError("Edit Session must not rebuild Folder day")

    monkeypatch.setattr(
        "backend.management_wf_folder_performance.build_day_folder_performance",
        boom,
    )
    monkeypatch.setattr(emp_day, "load_override_for_employee", lambda *a, **k: None)
    monkeypatch.setattr(emp_day, "sync_employee_day_publication", lambda *a, **k: None)

    cursor = MagicMock()
    out = mutation_employee_day_payload(
        cursor,
        3,
        selected_date_et=DAY,
        employee_name="Guiling",
        employee_user_id=41,
        sessions=_sessions(),
    )
    assert rebuilt["n"] == 0
    assert out["employee_day"]["employee"] == "Guiling"
    assert len(out["employee_day"]["sessions"]) == 2
    # Rate override on 7101 feeds day lbs
    assert out["employee_day"]["credited_weight_basis"] == "SESSION_RATE_OVERRIDE"


def test_edit_day_avg_weight_path_zero_rebuilds_when_end_unchanged(monkeypatch):
    """Mirrors post-fix Edit Day: sessions provided, end time same → 0 rebuilds."""
    rebuilt = {"n": 0}
    invalidated = {"n": 0}

    def boom(*a, **k):
        rebuilt["n"] += 1
        raise AssertionError("must not rebuild")

    monkeypatch.setattr(
        "backend.management_wf_folder_performance.build_day_folder_performance",
        boom,
    )
    monkeypatch.setattr(
        "backend.payroll_operations.update_time_record_segment",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("end unchanged")),
    )
    def fake_invalidate(*a, **k):
        invalidated["n"] += 1
        return {"ok": True}

    monkeypatch.setattr(
        "backend.rinse_performance_approvals.invalidate_approvals",
        fake_invalidate,
    )
    monkeypatch.setattr(
        "backend.rinse_performance_approvals.approval_status_map",
        lambda *a, **k: {
            "7101": {"status": "APPROVED"},
            "7103": {"status": "APPROVED"},
        },
    )
    monkeypatch.setattr(emp_day, "ensure_employee_day_override_tables", lambda cur: None)

    conn = MagicMock()
    conn.cursor.return_value = MagicMock()
    out = apply_employee_day_end_time(
        conn,
        3,
        selected_date_et=DAY,
        employee_name="Guiling",
        employee_user_id=41,
        end_time_et="2026-10-20T14:30:00",
        sessions=_sessions(),
    )
    assert out["unchanged"] is True
    assert rebuilt["n"] == 0
    assert invalidated["n"] == 0


def test_legacy_edit_day_without_sessions_still_rebuilds_once(monkeypatch):
    """Before fix / clients without sessions: exactly one Folder day rebuild."""
    rebuilt = {"n": 0}
    day = {
        "selected_date_et": "2026-10-20",
        "employees": [
            {
                "employee": "Guiling",
                "user_id": 41,
                "sessions": _sessions(),
            }
        ],
    }

    def fake_build(*a, **k):
        rebuilt["n"] += 1
        return day

    monkeypatch.setattr(
        "backend.management_wf_folder_performance.build_day_folder_performance",
        fake_build,
    )
    monkeypatch.setattr(
        "backend.rinse_performance_folder_publisher.attach_publication_status_to_day",
        lambda *a, **k: day,
    )
    monkeypatch.setattr(emp_day, "apply_publication_and_day_metrics", lambda *a, **k: day)
    monkeypatch.setattr(
        "backend.payroll_operations.update_time_record_segment",
        lambda *a, **k: {"ok": True},
    )
    monkeypatch.setattr(
        "backend.rinse_performance_approvals.invalidate_approvals",
        lambda *a, **k: {"ok": True, "invalidated": 1},
    )
    monkeypatch.setattr(emp_day, "ensure_employee_day_override_tables", lambda cur: None)

    conn = MagicMock()
    conn.cursor.return_value = MagicMock()
    out = apply_employee_day_end_time(
        conn,
        3,
        selected_date_et=DAY,
        employee_name="Guiling",
        employee_user_id=41,
        end_time_et="2026-10-20T15:00:00",
        # no sessions → legacy rebuild path
    )
    assert out["ok"] is True
    assert rebuilt["n"] == 1
    assert out.get("approval_reset") is True
    assert out.get("session_id") == "7103"


def _wf_evelin_sessions():
    return [
        {
            "session_id": "WF-2403",
            "session_code": "WF-01",
            "segment_id": 2403,
            "shift_session_id": 8801,
            "publication_status": "APPROVED",
            "publication": {"status": "APPROVED", "is_rate_override": False},
            "orders_completed": 2,
            "total_pre_lbs": 44.7,
            "performance_hours": 1.1764,
            "role_status": "closed",
            "include_in_authoritative_aggregate": True,
            "start_time": "2026-10-27T04:59:00",
            "end_time": "2026-10-27 06:09:53",
            "performance_end": "2026-10-27 06:09:53",
            "employee": "Evelin (VeeWash)",
        },
        {
            "session_id": "WF-2418",
            "session_code": "WF-02",
            "segment_id": 2418,
            "shift_session_id": 8802,
            "publication_status": "APPROVED",
            "publication": {
                "status": "APPROVED",
                "is_rate_override": True,
                "published_metric_value": 50.15,
                "published_numerator": 274.0547,
                "published_denominator": 5.4647,
            },
            "orders_completed": 8,
            "total_pre_lbs": 208.5,
            "performance_hours": 5.4647,
            "role_status": "closed",
            "include_in_authoritative_aggregate": True,
            "start_time": "2026-10-27T08:38:00",
            "end_time": "2026-10-27 14:05:53",
            "performance_end": "2026-10-27 14:05:53",
            "employee": "Evelin (VeeWash)",
        },
    ]


def test_wf_prefixed_unchanged_end_keeps_approval_and_session_key(monkeypatch):
    """Average Weight prefill posts the current end. WF-2418 must not 400."""
    updated = {"n": 0}
    invalidated = {"n": 0}

    monkeypatch.setattr(
        "backend.payroll_operations.update_time_record_segment",
        lambda *a, **k: updated.__setitem__("n", updated["n"] + 1),
    )
    monkeypatch.setattr(
        "backend.rinse_performance_approvals.invalidate_approvals",
        lambda *a, **k: invalidated.__setitem__("n", invalidated["n"] + 1),
    )
    monkeypatch.setattr(
        "backend.rinse_performance_approvals.approval_status_map",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(emp_day, "ensure_employee_day_override_tables", lambda cur: None)
    monkeypatch.setattr(
        "backend.management_wf_folder_performance.build_day_folder_performance",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not rebuild")),
    )

    conn = MagicMock()
    out = apply_employee_day_end_time(
        conn,
        3,
        selected_date_et=date(2026, 10, 27),
        employee_name="Evelin (VeeWash)",
        employee_user_id=30,
        end_time_et="2026-10-27T14:05:00",
        sessions=_wf_evelin_sessions(),
    )
    assert out["ok"] is True
    assert out["unchanged"] is True
    assert out["approval_reset"] is False
    assert out["session_id"] == "WF-2418"
    assert out["segment_id"] == 2418
    assert updated["n"] == 0
    assert invalidated["n"] == 0


def test_wf_prefixed_changed_end_resets_the_wf_key_not_the_segment_number(monkeypatch):
    captured = {}

    def upd(conn, org, session_id, segment_id, **k):
        captured["update"] = (session_id, segment_id)
        return {"ok": True}

    def inv(*a, **k):
        captured["invalidate"] = list(k.get("session_ids") or [])
        return {"ok": True, "invalidated": 1}

    monkeypatch.setattr("backend.payroll_operations.update_time_record_segment", upd)
    monkeypatch.setattr("backend.rinse_performance_approvals.invalidate_approvals", inv)
    monkeypatch.setattr(
        "backend.rinse_performance_approvals.approval_status_map",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(emp_day, "ensure_employee_day_override_tables", lambda cur: None)

    sessions = _wf_evelin_sessions()
    for sess in sessions:
        sess.pop("shift_session_id", None)
    cursor = MagicMock()
    cursor.fetchone.return_value = {"shift_session_id": 8802}
    conn = MagicMock()
    conn.cursor.return_value = cursor

    out = apply_employee_day_end_time(
        conn,
        3,
        selected_date_et=date(2026, 10, 27),
        employee_name="Evelin (VeeWash)",
        employee_user_id=30,
        end_time_et="2026-10-27T15:30:00",
        sessions=sessions,
    )
    assert out["ok"] is True
    assert out["approval_reset"] is True
    assert out["session_id"] == "WF-2418"
    assert captured["update"] == (8802, 2418)
    assert captured["invalidate"] == ["WF-2418"]


def test_numeric_session_id_remains_the_payroll_parent(monkeypatch):
    captured = {}

    def upd(conn, org, session_id, segment_id, **k):
        captured["update"] = (session_id, segment_id)
        return {"ok": True}

    monkeypatch.setattr("backend.payroll_operations.update_time_record_segment", upd)
    monkeypatch.setattr(
        "backend.rinse_performance_approvals.invalidate_approvals",
        lambda *a, **k: {"ok": True, "invalidated": 1, "ids": k.get("session_ids")},
    )
    monkeypatch.setattr(
        "backend.rinse_performance_approvals.approval_status_map",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(emp_day, "ensure_employee_day_override_tables", lambda cur: None)
    monkeypatch.setattr(
        "backend.management_wf_folder_performance.build_day_folder_performance",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("sessions supplied")),
    )

    conn = MagicMock()
    out = apply_employee_day_end_time(
        conn,
        3,
        selected_date_et=DAY,
        employee_name="Guiling",
        employee_user_id=41,
        end_time_et="2026-10-20T15:00:00",
        sessions=_sessions(),
    )
    assert out["ok"] is True
    assert out["approval_reset"] is True
    assert out["session_id"] == "7103"
    assert captured["update"] == (7103, 103)
