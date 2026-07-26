"""Closing a shift must freeze Employee Productivity — never clear or rebuild it.

Invariant:
  OPEN → EP reads live persisted Step-1 snapshot
  CLOSED → EP reads the same persisted snapshot (immutable)
  Only Shift Status may change.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_step1_productivity_fast import build_step1_snapshot_productivity_section
from backend.rinse_veewash_shift_day import (
    STATUS_CLOSED,
    STATUS_READY_TO_CLOSE,
    _bag_rows_from_workload,
    close_shift_day,
)

D1 = date(2026, 7, 25)
ORG = 3


def _summary(*, review=0, pending=0, completed=3, active=None):
    active = completed + pending + review if active is None else active
    return {
        "active_workload": active,
        "total_workload": active,
        "completed": completed,
        "pending": pending,
        "new_today": active,
        "exceptions": {"review_required": review},
        "review_by_reason": {},
        "segments": {
            "all": {
                "active_workload": active,
                "completed": completed,
                "pending": pending,
                "new_today": active,
                "exceptions": {"review_required": review},
                "bag_ids": {
                    "new_today": [f"B{i}" for i in range(active)],
                    "completed": [f"B{i}" for i in range(completed)],
                    "pending": [f"P{i}" for i in range(pending)],
                    "review_required": [f"R{i}" for i in range(review)],
                },
            },
            "wf": {
                "new_today": active,
                "completed": completed,
                "pending": pending,
                "exceptions": {"review_required": review},
                "bag_ids": {
                    "completed": [f"B{i}" for i in range(completed)],
                    "pending": [],
                    "review_required": [f"R{i}" for i in range(review)],
                },
            },
            "hd": {
                "new_today": 0,
                "completed": 0,
                "pending": 0,
                "exceptions": {"review_required": 0},
                "bag_ids": {"review_required": []},
            },
        },
    }


def _ep_fingerprint(payload: dict) -> dict:
    """Comparable EP surface: KPIs + employee rows (ignore status / mutability)."""
    emp = payload.get("employee_completed_bags_today") or payload
    employees = emp.get("employees") or []
    recon = emp.get("reconciliation") or {}
    return {
        "employees": [
            {
                "employee": e.get("employee"),
                "completed_bags": e.get("completed_bags"),
                "credited_bags_count": e.get("credited_bags_count"),
                "total_credited_lbs": e.get("total_credited_lbs"),
                "total_completed_lbs": e.get("total_completed_lbs"),
                "total_output_lbs": e.get("total_output_lbs"),
                "bags_per_hour": e.get("bags_per_hour"),
                "lbs_per_hour": e.get("lbs_per_hour"),
                "productive_hours": e.get("productive_hours"),
                "role_hours": e.get("role_hours"),
                "labor_cost": e.get("labor_cost"),
                "cost_per_bag": e.get("cost_per_bag"),
                "cost_per_pound": e.get("cost_per_pound"),
            }
            for e in employees
        ],
        "reconciliation": {
            "credited_total": recon.get("credited_total"),
            "workload_completed_today": recon.get("workload_completed_today"),
            "employee_attributed_bag_count": recon.get("employee_attributed_bag_count"),
        },
        "completed_today_kpi": payload.get("completed_today_kpi"),
        "workload_completed_kpi": payload.get("workload_completed_kpi"),
    }


def test_close_does_not_call_persist_day_snapshot():
    cursor = MagicMock()
    summary = _summary(review=0, pending=0, completed=3)
    day = {"status": STATUS_READY_TO_CLOSE, "headline": summary}
    closed = {**day, "status": STATUS_CLOSED}
    bags = [
        {"bag_id": f"DONE{i:06d}"[:10], "service_type": "WF", "effective_status": "completed"}
        for i in range(3)
    ]
    with (
        patch("backend.rinse_veewash_shift_day.persist_day_snapshot") as persist,
        patch("backend.rinse_veewash_shift_day._write_audit"),
        patch(
            "backend.rinse_veewash_shift_day.get_day_record",
            side_effect=[day, closed],
        ),
        patch("backend.rinse_veewash_shift_day.summary_from_day_record", return_value=summary),
        patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=bags),
        patch("backend.rinse_veewash_shift_day._count_hd_partially_recorded", return_value=0),
        patch("backend.rinse_employee_completed_bags.clear_step1_productivity_cache"),
    ):
        out = close_shift_day(
            cursor,
            ORG,
            D1,
            actor_user_id=1,
            actor_display_name="Admin",
        )
    assert out["ok"] is True
    persist.assert_not_called()
    sql = cursor.execute.call_args[0][0]
    assert "UPDATE rinse_shift_monitor_days" in sql
    assert "headline_json" not in sql


def test_close_preserves_employee_productivity_fingerprint():
    """Capture EP → close → reload EP; metrics identical, only status changes."""
    cursor = MagicMock()
    summary = _summary(review=0, pending=0, completed=3)
    day_open = {"status": STATUS_READY_TO_CLOSE, "headline": summary}
    day_closed = {"status": STATUS_CLOSED, "headline": summary}

    before_ep = {
        "employees": [
            {
                "employee": "Maria",
                "completed_bags": 2,
                "credited_bags_count": 2,
                "total_credited_lbs": 40.0,
                "total_completed_lbs": 40.0,
                "total_output_lbs": 38.0,
                "bags_per_hour": 2.0,
                "lbs_per_hour": 40.0,
                "productive_hours": 1.0,
                "role_hours": 1.0,
                "labor_cost": 20.0,
                "cost_per_bag": 10.0,
                "cost_per_pound": 0.5,
            },
            {
                "employee": "Ada",
                "completed_bags": 1,
                "credited_bags_count": 1,
                "total_credited_lbs": 12.0,
                "total_completed_lbs": 12.0,
                "total_output_lbs": 12.0,
                "bags_per_hour": 1.0,
                "lbs_per_hour": 12.0,
                "productive_hours": 1.0,
                "role_hours": 1.0,
                "labor_cost": 15.0,
                "cost_per_bag": 15.0,
                "cost_per_pound": 1.25,
            },
        ],
        "reconciliation": {
            "ok": True,
            "credited_total": 3,
            "workload_completed_today": 3,
            "employee_attributed_bag_count": 3,
        },
    }
    after_ep = deepcopy(before_ep)

    dashboard_before = {
        "employee_completed_bags_today": before_ep,
        "completed_today_kpi": 3,
        "workload_completed_kpi": 3,
        "shift_day_status": STATUS_READY_TO_CLOSE,
    }
    dashboard_after = {
        "employee_completed_bags_today": after_ep,
        "completed_today_kpi": 3,
        "workload_completed_kpi": 3,
        "shift_day_status": STATUS_CLOSED,
    }

    bags = [
        {"bag_id": f"DONE{i:06d}"[:10], "service_type": "WF", "effective_status": "completed"}
        for i in range(3)
    ]
    with (
        patch("backend.rinse_veewash_shift_day.persist_day_snapshot") as persist,
        patch("backend.rinse_veewash_shift_day._write_audit"),
        patch(
            "backend.rinse_veewash_shift_day.get_day_record",
            side_effect=[day_open, day_closed],
        ),
        patch("backend.rinse_veewash_shift_day.summary_from_day_record", return_value=summary),
        patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=bags),
        patch("backend.rinse_veewash_shift_day._count_hd_partially_recorded", return_value=0),
        patch("backend.rinse_employee_completed_bags.clear_step1_productivity_cache"),
        patch(
            "backend.rinse_employee_completed_bags.build_employee_productivity_dashboard_payload",
            side_effect=[dashboard_before, dashboard_after],
        ) as ep_build,
    ):
        from backend.rinse_employee_completed_bags import (
            build_employee_productivity_dashboard_payload,
        )

        before = build_employee_productivity_dashboard_payload(
            cursor, ORG, selected_date_et=D1
        )
        close_out = close_shift_day(
            cursor,
            ORG,
            D1,
            actor_user_id=1,
            actor_display_name="Admin",
        )
        after = build_employee_productivity_dashboard_payload(
            cursor, ORG, selected_date_et=D1
        )

    assert close_out["ok"] is True
    persist.assert_not_called()
    assert ep_build.call_count == 2
    assert _ep_fingerprint(before) == _ep_fingerprint(after)
    assert before["shift_day_status"] != after["shift_day_status"]
    assert after["shift_day_status"] == STATUS_CLOSED


def test_snapshot_shell_repersist_keeps_completed_bags():
    """Regression for the wipe: shell only listed review_required membership keys."""
    rows = [
        {
            "bag_id": "DONE1",
            "outcome": "completed",
            "entry_class": "new_today",
            "completed_by": "Maria",
            "pre_weight_lbs": 10.0,
        },
        {
            "bag_id": "DONE2",
            "outcome": "completed",
            "entry_class": "ADDED_LATER_IN_DAY",
            "completed_by": "Ada",
            "pre_weight_lbs": 12.0,
        },
        {
            "bag_id": "REV1",
            "outcome": "review_required",
            "entry_class": "new_today",
        },
    ]
    wl = {
        "from_snapshot": True,
        "rows": rows,
        # Bug shape: only review ids in list keys (what _workload_shell_from_bags emitted).
        "review_required": ["REV1"],
    }
    out = _bag_rows_from_workload(wl, _summary(review=1, completed=2, pending=0, active=3))
    ids = {r["bag_id"] for r in out}
    assert ids == {"DONE1", "DONE2", "REV1"}
    assert {r["bag_id"] for r in out if r["effective_status"] == "completed"} == {
        "DONE1",
        "DONE2",
    }


def test_build_step1_productivity_empty_when_no_credit_eligible_bags():
    """Documents the empty-EP failure mode after completed rows were deleted."""
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    with (
        patch(
            "backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"
        ),
        patch("backend.ta_helpers.table_exists", return_value=True),
        patch(
            "backend.rinse_step1_productivity_fast._day_bags_have_productivity_projection",
            return_value=True,
        ),
        patch(
            "backend.rinse_step1_productivity_fast._attach_roster_hours",
        ),
    ):
        section = build_step1_snapshot_productivity_section(
            cursor, ORG, selected_date_et=D1
        )
    assert section["employees"] == []
    assert (section.get("reconciliation") or {}).get("credited_total") == 0
