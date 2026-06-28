"""Regression: employee productivity must reconcile to Today's Workload bag universe."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

import pytest

from backend.rinse_at_vendor_module import MOD_AT_VENDOR_COMPLETED, MOD_AT_VENDOR_PENDING
from backend.rinse_employee_completed_bags import build_employee_completed_bags_today
from backend.rinse_employee_productivity_presentation import apply_employee_productivity_scope
from backend.rinse_employee_workload_productivity import (
    UNASSIGNED_EMPLOYEE,
    build_workload_productivity_reconciliation,
    credit_workload_bags,
    resolve_workload_bag_credit,
)

SELECTED = date(2026, 6, 27)
T0 = datetime(2026, 6, 27, 8, 0)
T1 = datetime(2026, 6, 27, 9, 0)
T2 = datetime(2026, 6, 27, 10, 0)
EMPLOYEE = "Alice Worker"


def _ev(purpose: str, ts: datetime, *, user_name: str = EMPLOYEE, ev_id: int = 1) -> dict:
    return {
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "id": ev_id,
        "scan_index": ev_id,
        "user_name": user_name,
        "bag_id": "PLACEHOLDER",
    }


def _workload_row(
    bag_id: str,
    *,
    service_type: str = "WF",
    status: str = "Completed",
    weight: float = 12.0,
) -> dict:
    tags = [MOD_AT_VENDOR_COMPLETED] if status == "Completed" else [MOD_AT_VENDOR_PENDING]
    return {
        "bag_id": bag_id,
        "customer_name": "Customer",
        "service_type": service_type,
        "service_bucket": service_type,
        "at_vendor_status": status,
        "module_tags": tags,
        "completion_time": T2.isoformat() if status == "Completed" else None,
        "completion_signal": "post_processing_weight" if status == "Completed" else None,
        "post_clean_weight": weight if status == "Completed" else None,
        "rush_bucket": "NON_RUSH",
    }


def _wf_events(bag_id: str, post_weight: datetime) -> list[dict]:
    return [
        {**_ev("sent-to-vendor", T0, ev_id=1), "bag_id": bag_id},
        {**_ev("weight-entry", T0, ev_id=2), "bag_id": bag_id},
        {**_ev("add-photos", T1, ev_id=3), "bag_id": bag_id},
        {**_ev("complete-cleaning", T1, ev_id=4), "bag_id": bag_id},
        {**_ev("weight-entry", post_weight, ev_id=5), "bag_id": bag_id},
    ]


class _FakeCursor:
    def execute(self, *args, **kwargs):
        return None

    def fetchall(self):
        return []

    def fetchone(self):
        return None


class TestWorkloadProductivityReconciliation:
    def test_credit_unique_workload_bags_once(self):
        rows = [
            _workload_row("WF1"),
            _workload_row("WF2", status="Pending"),
            _workload_row("HD1", service_type="HD", status="Pending"),
        ]
        events = {
            "WF1": _wf_events("WF1", T2),
            "WF2": _wf_events("WF2", T1),
            "HD1": [
                {**_ev("sent-to-vendor", T0, ev_id=1), "bag_id": "HD1"},
                {**_ev("garments-reviewed", T1, ev_id=2), "bag_id": "HD1"},
            ],
        }
        credited, dups = credit_workload_bags(rows, events_by_bag=events, selected_date_et=SELECTED)
        assert dups == []
        assert len(credited) == 3
        assert len({b["bag_id"] for b in credited}) == 3

    def test_reconciliation_total_matches_workload(self):
        rows = [
            _workload_row("WF1"),
            _workload_row("WF2"),
            _workload_row("HD1", service_type="HD"),
        ]
        events = {
            "WF1": _wf_events("WF1", T2),
            "WF2": _wf_events("WF2", T2),
            "HD1": [
                {**_ev("sent-to-vendor", T0, ev_id=1), "bag_id": "HD1"},
                {**_ev("complete-cleaning", T2, ev_id=2), "bag_id": "HD1"},
            ],
        }
        credited, dups = credit_workload_bags(rows, events_by_bag=events, selected_date_et=SELECTED)
        recon = build_workload_productivity_reconciliation(
            workload_rows=rows,
            credited_bags=credited,
            duplicate_bag_ids=dups,
            selected_date_et=SELECTED,
        )
        assert recon["workload_total"] == 3
        assert recon["credited_total"] == 3
        assert recon["ok"] is True
        assert recon["wf_count"] == 2
        assert recon["hd_count"] == 1

    def test_duplicate_scans_do_not_inflate_productivity(self):
        bag_id = "WF1"
        row = _workload_row(bag_id)
        events = _wf_events(bag_id, T2) + [
            {**_ev("weight-entry", T2, ev_id=99), "bag_id": bag_id},
        ]
        credit = resolve_workload_bag_credit(
            row, events=events, selected_date_et=SELECTED, as_of_end=T2
        )
        credited, dups = credit_workload_bags([row], events_by_bag={bag_id: events}, selected_date_et=SELECTED)
        assert len(credited) == 1
        assert credit["credited_employee"] == EMPLOYEE

    def test_unassigned_when_no_ownership_signal(self):
        row = _workload_row("WF9", status="Pending")
        credit = resolve_workload_bag_credit(
            row, events=[], selected_date_et=SELECTED, as_of_end=T2
        )
        assert credit["credited_employee"] == UNASSIGNED_EMPLOYEE
        assert credit["workload_status"] == "pending"

    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps", return_value={EMPLOYEE.casefold(): {"user_id": 42, "display_name": EMPLOYEE}})
    @patch("backend.rinse_processing_productivity._load_shift_sessions_bulk", return_value={})
    @patch("backend.daily_shift_roster.list_roster_entries", return_value=[])
    @patch("backend.rinse_employee_completed_bags._load_upstream_processing_scan_times_bulk", return_value={})
    @patch("backend.rinse_employee_completed_bags._load_employee_day_scan_events_bulk", return_value={})
    def test_build_employee_section_reconciles_to_workload(self, *_mocks):
        rows = [_workload_row("WF1"), _workload_row("WF2", status="Pending")]
        events = {
            "WF1": _wf_events("WF1", T2),
            "WF2": _wf_events("WF2", T1),
        }
        section = build_employee_completed_bags_today(
            _FakeCursor(),
            1,
            completed_rows=[r for r in rows if r["at_vendor_status"] == "Completed"],
            workload_rows=rows,
            events_by_bag=events,
            selected_date_et=SELECTED,
            registry_meta_by_bag={},
        )
        assert section["workload_based_productivity"] is True
        recon = section["reconciliation"]
        assert recon["workload_total"] == 2
        assert recon["credited_total"] == 2
        assert recon["ok"] is True
        assert recon["credited_completed"] == 1
        assert recon["credited_pending"] == 1

    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps", return_value={EMPLOYEE.casefold(): {"user_id": 42, "display_name": EMPLOYEE}})
    @patch("backend.rinse_processing_productivity._load_shift_sessions_bulk", return_value={})
    @patch("backend.daily_shift_roster.list_roster_entries", return_value=[])
    @patch("backend.rinse_employee_completed_bags._load_upstream_processing_scan_times_bulk", return_value={})
    @patch("backend.rinse_employee_completed_bags._load_employee_day_scan_events_bulk", return_value={})
    def test_wf_only_scope_reconciles_to_wf_workload(self, *_mocks):
        rows = [
            _workload_row("WF1"),
            _workload_row("HD1", service_type="HD"),
        ]
        events = {
            "WF1": _wf_events("WF1", T2),
            "HD1": [
                {**_ev("sent-to-vendor", T0, ev_id=1), "bag_id": "HD1"},
                {**_ev("complete-cleaning", T2, ev_id=2), "bag_id": "HD1"},
            ],
        }
        section = build_employee_completed_bags_today(
            _FakeCursor(),
            1,
            completed_rows=rows,
            workload_rows=rows,
            events_by_bag=events,
            selected_date_et=SELECTED,
            registry_meta_by_bag={},
        )
        scoped = apply_employee_productivity_scope(section, include_hd=False)
        assert scoped["reconciliation"]["ok"] is True
        assert scoped["reconciliation"]["workload_total"] == 1
        assert scoped["executive_summary"]["total_bags_credited"] == 1

    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps", return_value={EMPLOYEE.casefold(): {"user_id": 42, "display_name": EMPLOYEE}})
    @patch("backend.rinse_processing_productivity._load_shift_sessions_bulk", return_value={42: [{"clock_in_at": T0, "clock_out_at": T2}]})
    @patch("backend.daily_shift_roster.list_roster_entries", return_value=[])
    @patch("backend.rinse_employee_completed_bags._load_upstream_processing_scan_times_bulk", return_value={})
    @patch("backend.rinse_employee_completed_bags._load_employee_day_scan_events_bulk", return_value={})
    def test_lbs_per_hour_present_on_employee(self, *_mocks):
        rows = [_workload_row("WF1", weight=20.0)]
        events = {"WF1": _wf_events("WF1", T2)}
        section = build_employee_completed_bags_today(
            _FakeCursor(),
            1,
            completed_rows=rows,
            workload_rows=rows,
            events_by_bag=events,
            selected_date_et=SELECTED,
            registry_meta_by_bag={},
        )
        emp = next(e for e in section["employees"] if e["employee"] == EMPLOYEE)
        assert emp["processed_lbs_per_hour"] is not None or emp["lbs_per_hour"] is not None
        assert emp["credited_bags_count"] == 1
