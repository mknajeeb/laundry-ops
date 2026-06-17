"""Tests for employee productivity presentation-layer scoping (WF vs WF+HD)."""

from __future__ import annotations

from datetime import datetime

from backend.rinse_employee_productivity_presentation import apply_employee_productivity_scope

CLOCK_IN = "2026-06-10T04:30:00"
WF_COMP = "2026-06-10T07:00:00"
HD_COMP = "2026-06-10T08:00:00"


def _bag(bag_id: str, service_type: str, completion_time: str, lbs: float = 10.0) -> dict:
    return {
        "bag_id": bag_id,
        "service_type": service_type,
        "service_bucket": service_type,
        "completion_time": completion_time,
        "completion_timestamp": completion_time,
        "completed_lbs": lbs,
        "weight_missing": False,
        "customer_name": "Customer",
        "completion_signal": "post_processing_weight" if service_type == "WF" else "complete-cleaning",
    }


def _employee(name: str, bags: list[dict]) -> dict:
    return {
        "employee": name,
        "clock_in_time": CLOCK_IN,
        "clock_in_time_et": "2026-06-10 04:30:00",
        "completed_bags": len(bags),
        "total_completed_lbs": sum(float(b["completed_lbs"]) for b in bags),
        "bags": bags,
        "bags_per_hour": 2.0,
        "lbs_per_hour": 20.0,
        "productive_hours": 1.5,
        "worked_hours": 1.5,
        "last_completion_time": max(b["completion_time"] for b in bags),
        "last_completion_time_et": "2026-06-10 08:00:00",
    }


def _section() -> dict:
    wf = _bag("WF1", "WF", WF_COMP, 12.0)
    hd = _bag("HD1", "HD", HD_COMP, 8.0)
    return {
        "selected_date_et": "2026-06-10",
        "employees": [
            _employee("Alice", [wf]),
            _employee("Bob", [hd]),
        ],
        "reconciliation": {
            "workload_completed_today": 2,
            "employee_attributed_bag_count": 2,
            "wf_count": 1,
            "hd_count": 1,
            "no_duplicate_bags": True,
            "duplicate_bag_ids": [],
            "missing_from_employee_dashboard": [],
            "extra_in_employee_dashboard": [],
        },
        "reconciliation_banner": {
            "workload_completed_today": 2,
            "employee_completed_bags_credited": 2,
        },
        "attribution_audit": [
            {"bag_id": "WF1", "service_type": "WF"},
            {"bag_id": "HD1", "service_type": "HD"},
        ],
    }


class TestApplyEmployeeProductivityScope:
    def test_wf_only_filters_hd_bags_and_recalculates(self):
        section = _section()
        section["employees"] = [
            _employee("Alice", [_bag("WF1", "WF", WF_COMP, 12.0), _bag("HD1", "HD", HD_COMP, 8.0)]),
            _employee("Bob", [_bag("HD1", "HD", HD_COMP, 8.0)]),
        ]
        scoped = apply_employee_productivity_scope(section, include_hd=False)
        alice = scoped["employees"][0]
        assert alice["employee"] == "Alice"
        assert alice["completed_bags"] == 1
        assert alice["total_completed_lbs"] == 12.0
        assert len(alice["bags"]) == 1
        assert alice["bags"][0]["bag_id"] == "WF1"
        assert alice["last_completion_time"].startswith("2026-06-10T07:00:00")

        bob = next(e for e in scoped["employees"] if e["employee"] == "Bob")
        assert bob["completed_bags"] == 0
        assert bob["bags"] == []

        assert scoped["executive_summary"]["total_bags_completed"] == 1
        assert scoped["executive_summary"]["total_pounds_completed"] == 12.0
        assert scoped["executive_summary"]["total_employees_active"] == 1
        assert scoped["productivity_scope_label"] == "WF Only"
        assert scoped["reconciliation"]["employee_completed_bags_credited"] == 1
        assert scoped["reconciliation"]["workload_completed_today"] == 1
        assert len(scoped["attribution_audit"]) == 1

    def test_wf_plus_hd_preserves_totals(self):
        scoped = apply_employee_productivity_scope(_section(), include_hd=True)
        assert scoped["executive_summary"]["total_bags_completed"] == 2
        assert scoped["executive_summary"]["total_employees_active"] == 2
        assert scoped["productivity_scope_label"] == "WF + HD"
        assert scoped["reconciliation"]["employee_completed_bags_credited"] == 2
        assert scoped["reconciliation"]["workload_completed_today"] == 2

    def test_productive_hours_recomputed_from_scoped_last_completion(self):
        scoped = apply_employee_productivity_scope(_section(), include_hd=False)
        alice = scoped["employees"][0]
        clock_in = datetime.fromisoformat(CLOCK_IN)
        last = datetime.fromisoformat(WF_COMP)
        expected_hours = round((last - clock_in).total_seconds() / 3600.0, 4)
        assert alice["productive_hours"] == expected_hours
        assert alice["bags_per_hour"] == round(1 / expected_hours, 4)
