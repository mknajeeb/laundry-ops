"""Tests for employee completed bags today attribution and productivity."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

from backend.rinse_at_vendor_module import MOD_AT_VENDOR_COMPLETED
from backend.rinse_employee_completed_bags import (
    UNKNOWN_EMPLOYEE,
    build_employee_completed_bags_today,
    resolve_completion_attribution,
)
from backend.rinse_folding_et import naive_et_day_end_inclusive

SELECTED = date(2026, 6, 10)
T0 = datetime(2026, 6, 10, 4, 0)
T1 = datetime(2026, 6, 10, 5, 0)
T2 = datetime(2026, 6, 10, 6, 0)
T3 = datetime(2026, 6, 10, 7, 0)
T4 = datetime(2026, 6, 10, 8, 0)
CLOCK_IN = datetime(2026, 6, 10, 4, 30)


def _ev(
    purpose: str,
    ts: datetime,
    *,
    user_name: str = "Alice Worker",
    ev_id: int = 1,
) -> dict:
    return {
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "id": ev_id,
        "scan_index": ev_id,
        "user_name": user_name,
    }


def _completed_row(
    bag_id: str,
    *,
    service_type: str = "WF",
    post_clean_weight: float | None = 12.5,
    customer_name: str = "Test Customer",
) -> dict:
    return {
        "bag_id": bag_id,
        "customer_name": customer_name,
        "service_type": service_type,
        "service_bucket": service_type,
        "at_vendor_status": "Completed",
        "module_tags": [MOD_AT_VENDOR_COMPLETED],
        "completion_time": T3.isoformat(),
        "completion_time_et": "2026-06-10 07:00:00",
        "completion_signal": "post_processing_weight",
        "post_clean_weight": post_clean_weight,
        "pre_clean_weight": 14.0,
        "clean_weight_delta": -1.5,
        "rush_bucket": "NON_RUSH",
        "estimated_delivery_date": "2026-06-12",
    }


class TestResolveCompletionAttribution:
    def test_wf_attributes_post_clean_weight_user(self):
        events = [
            _ev("sent-to-vendor", T0, user_name="System"),
            _ev("weight-entry", T1, user_name="Early"),
            _ev("add-photos", T2, user_name="Processor"),
            _ev("weight-entry", T3, user_name="Weight Clerk"),
        ]
        employee, comp_ts, signal = resolve_completion_attribution(
            service_type="WF",
            events=events,
            anchor_ts=T0,
            as_of_end=naive_et_day_end_inclusive(SELECTED),
        )
        assert employee == "Weight Clerk"
        assert comp_ts == T3
        assert signal == "post_processing_weight"

    def test_hd_complete_cleaning_user(self):
        events = [
            _ev("sent-to-vendor", T0),
            _ev("complete-cleaning", T2, user_name="HD Finisher"),
        ]
        employee, comp_ts, signal = resolve_completion_attribution(
            service_type="HD",
            events=events,
            anchor_ts=T0,
            as_of_end=naive_et_day_end_inclusive(SELECTED),
        )
        assert employee == "HD Finisher"
        assert comp_ts == T2
        assert signal == "complete-cleaning"

    def test_hd_second_add_photos_user(self):
        events = [
            _ev("sent-to-vendor", T0),
            _ev("add-photos", T1, user_name="First"),
            _ev("add-photos", T3, user_name="Second Photo"),
        ]
        employee, comp_ts, signal = resolve_completion_attribution(
            service_type="HD",
            events=events,
            anchor_ts=T0,
            as_of_end=naive_et_day_end_inclusive(SELECTED),
        )
        assert employee == "Second Photo"
        assert comp_ts == T3
        assert signal == "second add-photos"

    def test_missing_user_groups_unknown(self):
        events = [
            _ev("sent-to-vendor", T0, user_name=""),
            _ev("complete-cleaning", T2, user_name=""),
        ]
        employee, _, _ = resolve_completion_attribution(
            service_type="HD",
            events=events,
            anchor_ts=T0,
            as_of_end=naive_et_day_end_inclusive(SELECTED),
        )
        assert employee == UNKNOWN_EMPLOYEE


class TestBuildEmployeeCompletedBagsToday:
    def _build(self, rows, events_by_bag, *, clock_in=CLOCK_IN, user_maps=None):
        user_maps = user_maps or {
            "alice worker": {"user_id": 42, "display_name": "Alice Worker"},
            "weight clerk": {"user_id": 43, "display_name": "Weight Clerk"},
            "hd finisher": {"user_id": 44, "display_name": "HD Finisher"},
        }
        sessions = {
            42: [{"clock_in": CLOCK_IN, "clock_out": None}],
            43: [{"clock_in": CLOCK_IN, "clock_out": None}],
            44: [{"clock_in": CLOCK_IN, "clock_out": None}],
        }

        with patch(
            "backend.rinse_simple_shift_performance._load_rinse_user_maps",
            return_value=user_maps,
        ), patch(
            "backend.rinse_processing_productivity._load_shift_sessions_bulk",
            return_value=sessions,
        ), patch(
            "backend.rinse_simple_shift_performance._employee_shift_window",
            side_effect=lambda _c, _o, *, user_id, **_: (
                (clock_in, None, None) if user_id in sessions else (None, None, "Clock-in missing")
            ),
        ):
            return build_employee_completed_bags_today(
                object(),
                3,
                completed_rows=rows,
                events_by_bag=events_by_bag,
                selected_date_et=SELECTED,
                registry_meta_by_bag={},
            )

    def test_reconciliation_and_productivity(self):
        wf_row = _completed_row("BAGWF1", service_type="WF")
        hd_row = _completed_row("BAGHD1", service_type="HD", post_clean_weight=None)
        hd_row["post_clean_weight"] = None
        events = {
            "Bkp": [],
            "BAGWF1": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1),
                _ev("add-photos", T2),
                _ev("weight-entry", T3, user_name="Weight Clerk"),
            ],
            "BAGHD1": [
                _ev("sent-to-vendor", T0),
                _ev("complete-cleaning", T4, user_name="HD Finisher"),
            ],
        }
        out = self._build([wf_row, hd_row], events)
        recon = out["reconciliation"]
        assert recon["ok"] is True
        assert recon["workload_completed_today"] == 2
        assert recon["employee_attributed_bag_count"] == 2
        assert recon["wf_count"] == 1
        assert recon["hd_count"] == 1

        by_name = {e["employee"]: e for e in out["employees"]}
        wf_emp = by_name["Weight Clerk"]
        assert wf_emp["completed_bags"] == 1
        assert wf_emp["total_completed_lbs"] == 12.5
        assert wf_emp["bags_per_hour"] is not None
        assert wf_emp["worked_hours"] is not None
        assert wf_emp["last_completion_time"] == T3.isoformat()

        hd_emp = by_name["HD Finisher"]
        assert hd_emp["completed_bags"] == 1
        assert hd_emp["last_completion_time"] == T4.isoformat()

    def test_missing_clock_in_skips_hourly_rates(self):
        row = _completed_row("BAG1")
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1),
                _ev("add-photos", T2),
                _ev("weight-entry", T3, user_name="Unknown Person"),
            ],
        }
        out = self._build([row], events, clock_in=None, user_maps={})
        emp = out["employees"][0]
        assert emp["employee"] == "Unknown Person"
        assert emp["productivity_note"] == "Missing clock-in data"
        assert emp["bags_per_hour"] is None
        assert emp["lbs_per_hour"] is None

    def test_missing_weight_counted_not_in_lbs_total(self):
        row = _completed_row("BAG1", post_clean_weight=None)
        row.pop("post_clean_weight", None)
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1),
                _ev("add-photos", T2),
                _ev("weight-entry", T3, user_name="Weight Clerk"),
            ],
        }
        out = self._build([row], events)
        emp = next(e for e in out["employees"] if e["employee"] == "Weight Clerk")
        assert emp["completed_bags"] == 1
        assert emp["total_completed_lbs"] == 0
        assert emp["missing_weight_count"] == 1

    def test_bags_sorted_chronologically_in_drilldown(self):
        row1 = _completed_row("BAG1")
        row2 = _completed_row("BAG2")
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1),
                _ev("add-photos", T2),
                _ev("weight-entry", T3, user_name="Weight Clerk"),
            ],
            "BAG2": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1),
                _ev("add-photos", T2),
                _ev("weight-entry", T4, user_name="Weight Clerk"),
            ],
        }
        out = self._build([row1, row2], events)
        emp = next(e for e in out["employees"] if e["employee"] == "Weight Clerk")
        bag_ids = [b["bag_id"] for b in emp["bags"]]
        assert bag_ids == ["BAG1", "BAG2"]
