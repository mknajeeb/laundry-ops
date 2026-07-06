"""Tests for employee completed bags today attribution and productivity."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

from backend.rinse_at_vendor_module import MOD_AT_VENDOR_COMPLETED
from backend.rinse_employee_completed_bags import (
    UNKNOWN_EMPLOYEE,
    FOLD_BLOCK_END_CLOCK_OUT,
    FOLD_BLOCK_END_LAST_COMPLETION,
    FOLD_BLOCK_START_CLOCK_IN,
    FOLD_BLOCK_START_PRIOR_SCAN,
    PRODUCTIVITY_END_CLOCK_OUT,
    PRODUCTIVITY_END_LAST_COMPLETION,
    PRODUCTIVITY_START_CLOCK_IN,
    PRODUCTIVITY_START_INFERRED_FOLD,
    PRODUCTIVITY_START_OPERATOR_PROCESSING,
    _compute_folding_blocks,
    _compute_productive_window,
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
CLOCK_OUT = datetime(2026, 6, 10, 9, 0)
PROC_SCAN = datetime(2026, 6, 10, 6, 15)


def _ev(
    purpose: str,
    ts: datetime,
    *,
    user_name: str = "Alice Worker",
    ev_id: int = 1,
    weight_lbs: float | None = None,
) -> dict:
    ev = {
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "id": ev_id,
        "scan_index": ev_id,
        "user_name": user_name,
    }
    if weight_lbs is not None:
        ev["weight_lbs"] = weight_lbs
    return ev


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

    def test_wf_attribution_survives_same_day_resend_after_completion(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 6, 2, 35), user_name="Intake"),
            _ev("weight-entry", datetime(2026, 7, 6, 2, 37), user_name="Intake"),
            _ev("complete-cleaning", datetime(2026, 7, 6, 7, 53), user_name="Yesenia Worker"),
            _ev("weight-entry", datetime(2026, 7, 6, 7, 57), user_name="Yesenia Worker"),
            _ev("processed-by-vendor", datetime(2026, 7, 6, 7, 57), user_name="Yesenia Worker"),
            _ev("sent-to-vendor", datetime(2026, 7, 6, 7, 59), user_name="Yesenia Worker"),
            _ev("weight-entry", datetime(2026, 7, 6, 7, 59), user_name="Yesenia Worker"),
        ]
        selected = date(2026, 7, 6)
        employee, comp_ts, signal = resolve_completion_attribution(
            service_type="WF",
            events=events,
            anchor_ts=datetime(2026, 7, 6, 7, 59),
            as_of_end=naive_et_day_end_inclusive(selected),
            selected_date_et=selected,
        )
        assert employee == "Yesenia Worker"
        assert comp_ts == datetime(2026, 7, 6, 7, 59)
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


class TestComputeProductiveWindow:
    def test_operator_uses_last_upstream_scan_before_first_completion(self):
        start, end, start_source, end_source, total_sec = _compute_productive_window(
            roster_role="operator",
            clock_in=CLOCK_IN,
            first_comp=T3,
            last_comp=T4,
            actual_clock_out=None,
            upstream_scans=[datetime(2026, 6, 10, 5, 30), datetime(2026, 6, 10, 6, 45)],
        )
        assert start == datetime(2026, 6, 10, 6, 45)
        assert end == T4
        assert start_source == PRODUCTIVITY_START_OPERATOR_PROCESSING
        assert end_source == "last_completion"
        assert total_sec == int((T4 - datetime(2026, 6, 10, 6, 45)).total_seconds())

    def test_folder_uses_clock_out_when_set(self):
        start, end, start_source, end_source, total_sec = _compute_productive_window(
            roster_role="folder",
            clock_in=CLOCK_IN,
            first_comp=T3,
            last_comp=T3,
            actual_clock_out=CLOCK_OUT,
            upstream_scans=[],
        )
        assert start == CLOCK_IN
        assert end == CLOCK_OUT
        assert start_source == "clock_in"
        assert end_source == PRODUCTIVITY_END_CLOCK_OUT
        assert total_sec == int((CLOCK_OUT - CLOCK_IN).total_seconds())


class TestBuildEmployeeCompletedBagsToday:
    def _build(
        self,
        rows,
        events_by_bag,
        *,
        clock_in=CLOCK_IN,
        clock_out=None,
        user_maps=None,
        roster_roles=None,
        upstream_scans=None,
    ):
        user_maps = user_maps or {
            "alice worker": {"user_id": 42, "display_name": "Alice Worker"},
            "weight clerk": {"user_id": 43, "display_name": "Weight Clerk"},
            "hd finisher": {"user_id": 44, "display_name": "HD Finisher"},
            "folder person": {"user_id": 50, "display_name": "Folder Person"},
        }
        sessions = {
            42: [{"clock_in_at": CLOCK_IN, "clock_out_at": clock_out}],
            43: [{"clock_in_at": CLOCK_IN, "clock_out_at": clock_out}],
            44: [{"clock_in_at": CLOCK_IN, "clock_out_at": clock_out}],
            50: [{"clock_in_at": CLOCK_IN, "clock_out_at": clock_out}],
        }
        roster_roles = roster_roles or {}

        def _shift_window(_c, _o, *, user_id, **kwargs):
            sess = sessions.get(user_id) or []
            if not sess:
                return None, None, "Clock-in missing"
            cin = sess[0].get("clock_in_at")
            cout = sess[0].get("clock_out_at")
            return cin, cout, None

        with patch(
            "backend.rinse_simple_shift_performance._load_rinse_user_maps",
            return_value=user_maps,
        ), patch(
            "backend.rinse_processing_productivity._load_shift_sessions_bulk",
            return_value=sessions,
        ), patch(
            "backend.rinse_simple_shift_performance._employee_shift_window",
            side_effect=_shift_window,
        ), patch(
            "backend.daily_shift_roster.list_roster_entries",
            return_value=[],
        ), patch(
            "backend.daily_shift_roster.build_roster_role_lookup",
            return_value=roster_roles,
        ), patch(
            "backend.rinse_employee_completed_bags._load_upstream_processing_scan_times_bulk",
            return_value=upstream_scans or {},
        ), patch(
            "backend.rinse_employee_completed_bags._load_employee_day_scan_events_bulk",
            return_value={},
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
                _ev("weight-entry", T3, user_name="Weight Clerk", weight_lbs=12.5),
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
                _ev("weight-entry", T3, user_name="Unknown Person", weight_lbs=12.5),
            ],
        }
        out = self._build([row], events, clock_in=None, user_maps={})
        emp = out["employees"][0]
        assert emp["employee"] == "Unknown Person"
        assert emp["productivity_note"] == "Missing clock-in data"
        assert emp["bags_per_hour"] is None
        assert emp["lbs_per_hour"] is None

    def test_weight_integrity_failure_excluded_from_lbs_total(self):
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
        assert emp["weight_integrity_failure_count"] == 1
        assert out["weight_integrity_ok"] is False

    def test_completed_lbs_from_attribution_weight_scan_when_portal_weight_missing(self):
        row = _completed_row("BAG1", post_clean_weight=None)
        row.pop("post_clean_weight", None)
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1),
                _ev("add-photos", T2),
                _ev("weight-entry", T3, user_name="Weight Clerk", weight_lbs=14.2),
            ],
        }
        out = self._build([row], events)
        emp = next(e for e in out["employees"] if e["employee"] == "Weight Clerk")
        assert emp["completed_bags"] == 1
        assert emp["total_completed_lbs"] == 14.2
        assert emp["weight_integrity_failure_count"] == 0
        assert out["weight_integrity_ok"] is True
        assert emp["bags"][0]["completed_lbs"] == 14.2

    def test_bags_sorted_chronologically_in_drilldown(self):
        row1 = _completed_row("BAG1")
        row2 = _completed_row("BAG2")
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1),
                _ev("add-photos", T2),
                _ev("weight-entry", T3, user_name="Weight Clerk", weight_lbs=12.5),
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

    def test_operator_productive_hours_use_folding_blocks(self):
        row = _completed_row("BAG1")
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1),
                _ev("add-photos", T2, user_name="Processor"),
                _ev("weight-entry", T3, user_name="Weight Clerk", ev_id=6, weight_lbs=12.5),
            ],
            "BAG2": [
                _ev("drying", T2, user_name="Weight Clerk", ev_id=5),
            ],
        }
        out = self._build(
            [row],
            events,
            roster_roles={"weight clerk": "operator"},
        )
        emp = next(e for e in out["employees"] if e["employee"] == "Weight Clerk")
        blocks = emp["folding_blocks"]
        assert len(blocks) == 1
        assert blocks[0]["start_time"] == T2.isoformat()
        assert blocks[0]["start_source"] == FOLD_BLOCK_START_PRIOR_SCAN
        assert blocks[0]["end_time"] == T3.isoformat()
        expected_hours = round((T3 - T2).total_seconds() / 3600.0, 4)
        assert emp["productive_hours"] == expected_hours
        assert emp["productivity_start_source"] == PRODUCTIVITY_START_INFERRED_FOLD

    def test_folder_productive_hours_end_at_last_completion(self):
        row = _completed_row("BAG1")
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1),
                _ev("add-photos", T2, user_name="Weight Clerk"),
                _ev("weight-entry", T3, user_name="Weight Clerk", weight_lbs=12.5),
            ],
        }
        out = self._build(
            [row],
            events,
            clock_out=CLOCK_OUT,
            roster_roles={"weight clerk": "folder"},
        )
        emp = next(e for e in out["employees"] if e["employee"] == "Weight Clerk")
        expected_hours = round((T3 - CLOCK_IN).total_seconds() / 3600.0, 4)
        assert emp["productive_end_time"] == T3.isoformat()
        assert emp["productivity_end_source"] == PRODUCTIVITY_END_LAST_COMPLETION
        assert emp["productive_hours"] == expected_hours


class TestFoldingBlocks:
    """Shift-level folding work windows for Operator/Folder — completion credit unchanged."""

    def _build(self, rows, events_by_bag, *, roster_roles=None, clock_in=CLOCK_IN, clock_out=None, user_maps=None):
        helper = TestBuildEmployeeCompletedBagsToday()
        return helper._build(
            rows,
            events_by_bag,
            roster_roles=roster_roles or {},
            clock_in=clock_in,
            clock_out=clock_out,
            user_maps=user_maps,
        )

    def test_folder_no_prior_scans_starts_at_punch_in(self):
        row = _completed_row("BAG1")
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1),
                _ev("add-photos", T2, user_name="Processor"),
                _ev("weight-entry", T3, user_name="Folder Person", ev_id=4, weight_lbs=12.5),
            ],
        }
        out = self._build(
            [row],
            events,
            roster_roles={"folder person": "folder"},
            clock_out=CLOCK_OUT,
            user_maps={"folder person": {"user_id": 50, "display_name": "Folder Person"}},
        )
        emp = next(e for e in out["employees"] if e["employee"] == "Folder Person")
        assert len(emp["folding_blocks"]) == 1
        assert emp["folding_blocks"][0]["start_time"] == CLOCK_IN.isoformat()
        assert emp["folding_blocks"][0]["start_source"] == FOLD_BLOCK_START_CLOCK_IN

    def test_operator_prior_operational_scan_starts_block(self):
        row = _completed_row("BAG1")
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1, user_name="Processor"),
                _ev("add-photos", datetime(2026, 6, 10, 6, 30), user_name="Processor"),
                _ev("weight-entry", T3, user_name="Weight Clerk", ev_id=5, weight_lbs=12.5),
            ],
            "BAG2": [
                _ev("drying", T2, user_name="Weight Clerk"),
            ],
        }
        out = self._build([row], events, roster_roles={"weight clerk": "operator"})
        emp = out["employees"][0]
        assert emp["folding_blocks"][0]["start_time"] == T2.isoformat()
        assert emp["folding_blocks"][0]["start_source"] == FOLD_BLOCK_START_PRIOR_SCAN

    def test_two_folding_blocks_after_non_folding_gap(self):
        row1 = _completed_row("BAG1")
        row2 = _completed_row("BAG2")
        row2["completion_time"] = T4.isoformat()
        gap = datetime(2026, 6, 10, 7, 30)
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1),
                _ev("add-photos", T2, user_name="Processor"),
                _ev("weight-entry", T3, user_name="Weight Clerk", ev_id=4, weight_lbs=12.5),
            ],
            "BAG2": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1),
                _ev("add-photos", datetime(2026, 6, 10, 7, 45), user_name="Processor"),
                _ev("weight-entry", T4, user_name="Weight Clerk", ev_id=7),
            ],
            "BAG3": [
                _ev("drying", gap, user_name="Weight Clerk", ev_id=5),
            ],
        }
        out = self._build([row1, row2], events, roster_roles={"weight clerk": "operator"})
        emp = out["employees"][0]
        assert len(emp["folding_blocks"]) == 2
        assert emp["folding_blocks"][0]["end_time"] == T3.isoformat()
        assert emp["folding_blocks"][1]["start_time"] == gap.isoformat()

    def test_final_block_ends_at_punch_out_without_later_scans(self):
        row = _completed_row("BAG1")
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1),
                _ev("add-photos", T2, user_name="Processor"),
                _ev("weight-entry", T3, user_name="Folder Person", ev_id=4, weight_lbs=12.5),
            ],
        }
        out = self._build(
            [row],
            events,
            roster_roles={"folder person": "folder"},
            clock_out=CLOCK_OUT,
            user_maps={"folder person": {"user_id": 50, "display_name": "Folder Person"}},
        )
        emp = next(e for e in out["employees"] if e["employee"] == "Folder Person")
        assert emp["folding_blocks"][0]["end_time"] == T3.isoformat()
        assert emp["folding_blocks"][0]["end_source"] == FOLD_BLOCK_END_LAST_COMPLETION
        expected_hours = round((T3 - CLOCK_IN).total_seconds() / 3600.0, 4)
        assert emp["productive_hours"] == expected_hours

    def test_block_ends_at_last_completion_before_non_folding_scan(self):
        row = _completed_row("BAG1")
        after = datetime(2026, 6, 10, 7, 30)
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1),
                _ev("add-photos", T2, user_name="Processor"),
                _ev("weight-entry", T3, user_name="Weight Clerk", ev_id=4, weight_lbs=12.5),
            ],
            "BAG2": [
                _ev("sent-to-vendor", T0),
                _ev("drying", after, user_name="Weight Clerk", ev_id=5),
            ],
        }
        out = self._build(
            [row],
            events,
            roster_roles={"weight clerk": "operator"},
            clock_out=CLOCK_OUT,
        )
        emp = out["employees"][0]
        assert emp["folding_blocks"][0]["end_time"] == T3.isoformat()
        assert emp["folding_blocks"][0]["end_source"] == "last_completion"

    def test_fold_completion_credit_unchanged(self):
        row = _completed_row("BAG1")
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1),
                _ev("add-photos", T2, user_name="Processor"),
                _ev("weight-entry", T2, user_name="Weight Clerk", ev_id=5),
                _ev("weight-entry", T3, user_name="Weight Clerk", ev_id=6, weight_lbs=12.5),
            ],
        }
        out = self._build([row], events, roster_roles={"weight clerk": "operator"})
        bag = out["employees"][0]["bags"][0]
        assert bag["completed_by_employee"] == "Weight Clerk"
        assert bag["completion_time"] == T3.isoformat()
        assert out["reconciliation"]["employee_attributed_bag_count"] == 1

    def test_no_cross_employee_non_folding_scans(self):
        row = _completed_row("BAG1")
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("drying", T2, user_name="Other Worker"),
                _ev("weight-entry", T1),
                _ev("add-photos", datetime(2026, 6, 10, 6, 30), user_name="Processor"),
                _ev("weight-entry", T3, user_name="Weight Clerk", ev_id=5, weight_lbs=12.5),
            ],
        }
        out = self._build([row], events, roster_roles={"weight clerk": "operator"})
        emp = out["employees"][0]
        assert emp["folding_blocks"][0]["start_time"] == CLOCK_IN.isoformat()

    def test_no_cross_day_non_folding_scans(self):
        prior_day = datetime(2026, 6, 9, 18, 0)
        row = _completed_row("BAG1")
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("drying", prior_day, user_name="Weight Clerk"),
                _ev("weight-entry", T1),
                _ev("add-photos", T2, user_name="Processor"),
                _ev("weight-entry", T3, user_name="Weight Clerk", ev_id=5, weight_lbs=12.5),
            ],
        }
        out = self._build([row], events, roster_roles={"weight clerk": "operator"})
        emp = out["employees"][0]
        assert emp["folding_blocks"][0]["start_time"] == CLOCK_IN.isoformat()

    def test_shift_boundary_blocks_scan_before_clock_in(self):
        early = datetime(2026, 6, 10, 4, 0)
        row = _completed_row("BAG1")
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("drying", early, user_name="Weight Clerk"),
                _ev("weight-entry", T1),
                _ev("add-photos", T2, user_name="Processor"),
                _ev("weight-entry", T3, user_name="Weight Clerk", ev_id=5, weight_lbs=12.5),
            ],
        }
        out = self._build([row], events, roster_roles={"weight clerk": "operator"})
        emp = out["employees"][0]
        assert emp["folding_blocks"][0]["start_time"] == CLOCK_IN.isoformat()

    def test_repeat_trip_ignores_pre_anchor_non_folding_scans(self):
        resend = datetime(2026, 6, 10, 6, 30)
        post_resend = datetime(2026, 6, 10, 6, 45)
        post_anchor_proc = datetime(2026, 6, 10, 6, 35)
        row = _completed_row("BAG1")
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0, ev_id=1),
                _ev("drying", T1, user_name="Weight Clerk", ev_id=2),
                _ev("sent-to-vendor", resend, ev_id=3),
                _ev("weight-entry", post_anchor_proc, user_name="Processor", ev_id=5),
                _ev("add-photos", post_resend, user_name="Processor", ev_id=6),
                _ev("weight-entry", T3, user_name="Weight Clerk", ev_id=7, weight_lbs=12.5),
            ],
            "BAG2": [
                _ev("drying", post_resend, user_name="Weight Clerk", ev_id=4),
            ],
        }
        out = self._build([row], events, roster_roles={"weight clerk": "operator"})
        emp = next(e for e in out["employees"] if e["employee"] == "Weight Clerk")
        assert emp["folding_blocks"][0]["start_time"] == post_resend.isoformat()

    def test_folding_blocks_sum_productive_hours(self):
        blocks = _compute_folding_blocks(
            roster_role="operator",
            clock_in=CLOCK_IN,
            clock_out=CLOCK_OUT,
            non_folding_scans=[(T2, "BAG1"), (datetime(2026, 6, 10, 7, 30), "BAG2")],
            fold_completions=[(T3, "BAG1"), (T4, "BAG2")],
        )
        assert len(blocks) == 2
        total = sum(b["duration_seconds"] for b in blocks)
        _, _, _, _, productive_sec = _compute_productive_window(
            roster_role="operator",
            clock_in=CLOCK_IN,
            first_comp=T3,
            last_comp=T4,
            actual_clock_out=CLOCK_OUT,
            upstream_scans=[],
            folding_blocks=blocks,
        )
        assert productive_sec == total

    def test_folder_evelin_like_day_uses_continuous_folding_span_not_micro_blocks(self):
        """Regression: WF pipeline steps must not collapse productive hours to ~1 min/bag."""
        folder = "Evelin Folder"
        selected = date(2026, 6, 25)
        clock_in = datetime(2026, 6, 25, 9, 28, 6)
        clock_out = datetime(2026, 6, 25, 17, 1, 1)
        fold_start = datetime(2026, 6, 25, 10, 10, 0)
        completion_times = [
            datetime(2026, 6, 25, 10, 12),
            datetime(2026, 6, 25, 10, 59),
            datetime(2026, 6, 25, 11, 27),
            datetime(2026, 6, 25, 12, 12),
            datetime(2026, 6, 25, 13, 11),
            datetime(2026, 6, 25, 13, 31),
            datetime(2026, 6, 25, 14, 8),
            datetime(2026, 6, 25, 14, 41),
            datetime(2026, 6, 25, 15, 12),
            datetime(2026, 6, 25, 15, 24),
            datetime(2026, 6, 25, 15, 56),
            datetime(2026, 6, 25, 16, 21),
            datetime(2026, 6, 25, 16, 46),
        ]
        rows = []
        events: dict[str, list] = {}
        sent = datetime(2026, 6, 24, 8, 0)
        events["FOLD_START"] = [
            _ev("add-photos", fold_start, user_name=folder, ev_id=900),
        ]
        for idx, comp_ts in enumerate(completion_times, start=1):
            bid = f"BAG{idx:02d}"
            row = _completed_row(bid, service_type="WF")
            row["completion_time"] = comp_ts.isoformat()
            rows.append(row)
            add_photos = comp_ts.replace(minute=max(0, comp_ts.minute - 2))
            cleaning = add_photos.replace(minute=max(0, add_photos.minute - 8))
            events[bid] = [
                _ev("sent-to-vendor", sent, ev_id=idx * 10),
                _ev("cleaning", cleaning, user_name=folder, ev_id=idx * 10 + 1),
                _ev("complete-cleaning", cleaning, user_name=folder, ev_id=idx * 10 + 2),
                _ev("add-photos", add_photos, user_name=folder, ev_id=idx * 10 + 3),
                _ev("weight-entry", comp_ts, user_name=folder, ev_id=idx * 10 + 4),
            ]

        helper = TestBuildEmployeeCompletedBagsToday()
        out = helper._build(
            rows,
            events,
            clock_in=clock_in,
            clock_out=clock_out,
            roster_roles={"evelin folder": "folder"},
            user_maps={
                "evelin folder": {"user_id": 51, "display_name": folder},
            },
        )
        # Patch selected date for Jun 25 ET window
        with patch(
            "backend.rinse_simple_shift_performance._load_rinse_user_maps",
            return_value={"evelin folder": {"user_id": 51, "display_name": folder}},
        ), patch(
            "backend.rinse_processing_productivity._load_shift_sessions_bulk",
            return_value={51: [{"clock_in_at": clock_in, "clock_out_at": clock_out}]},
        ), patch(
            "backend.rinse_simple_shift_performance._employee_shift_window",
            return_value=(clock_in, clock_out, None),
        ), patch(
            "backend.daily_shift_roster.list_roster_entries",
            return_value=[],
        ), patch(
            "backend.daily_shift_roster.build_roster_role_lookup",
            return_value={"evelin folder": "folder"},
        ), patch(
            "backend.rinse_employee_completed_bags._load_upstream_processing_scan_times_bulk",
            return_value={},
        ), patch(
            "backend.rinse_employee_completed_bags._load_employee_day_scan_events_bulk",
            return_value={},
        ):
            out = build_employee_completed_bags_today(
                object(),
                3,
                completed_rows=rows,
                events_by_bag=events,
                selected_date_et=selected,
                registry_meta_by_bag={},
            )

        emp = next(e for e in out["employees"] if e["employee"] == folder)
        micro_block_sum_hours = round(13 * 90 / 3600.0, 4)  # old ~1–2 min/block pattern
        assert emp["productive_hours"] > 1.0
        assert emp["productive_hours"] > micro_block_sum_hours * 2
        assert 6.0 <= emp["productive_hours"] <= 7.5
        assert emp["productive_start_time"] == fold_start.isoformat()
        assert emp["productive_end_time"] == completion_times[-1].isoformat()
        assert emp["bags_per_hour"] is not None
        assert 1.5 <= emp["bags_per_hour"] <= 3.0
        assert emp["lbs_per_hour"] is not None
        assert len(emp["folding_blocks"]) == 1
        assert emp["folding_blocks"][0]["completion_count"] == 13

    def test_two_folding_windows_with_inactive_gap_sums_blocks_not_full_span(self):
        """Regression: lunch-length gap must not inflate hours via continuous-span fallback."""
        folder = "Split Shift Folder"
        selected = date(2026, 6, 25)
        clock_in = datetime(2026, 6, 25, 9, 0, 0)
        morning = [
            (datetime(2026, 6, 25, 10, 0), datetime(2026, 6, 25, 10, 30)),
            (datetime(2026, 6, 25, 10, 35), datetime(2026, 6, 25, 11, 0)),
        ]
        afternoon = [
            (datetime(2026, 6, 25, 14, 0), datetime(2026, 6, 25, 14, 30)),
            (datetime(2026, 6, 25, 14, 35), datetime(2026, 6, 25, 15, 0)),
        ]
        rows = []
        events: dict[str, list] = {}
        sent = datetime(2026, 6, 24, 8, 0)
        events["MORNING_START"] = [
            _ev("add-photos", datetime(2026, 6, 25, 9, 55), user_name=folder, ev_id=900),
        ]
        events["AFTERNOON_START"] = [
            _ev("add-photos", datetime(2026, 6, 25, 13, 55), user_name=folder, ev_id=901),
        ]
        for idx, (add_photos, comp_ts) in enumerate(morning + afternoon, start=1):
            bid = f"WIN{idx}"
            row = _completed_row(bid, service_type="WF")
            row["completion_time"] = comp_ts.isoformat()
            rows.append(row)
            cleaning = add_photos.replace(minute=max(0, add_photos.minute - 5))
            events[bid] = [
                _ev("sent-to-vendor", sent, ev_id=idx * 10),
                _ev("cleaning", cleaning, user_name=folder, ev_id=idx * 10 + 1),
                _ev("add-photos", add_photos, user_name=folder, ev_id=idx * 10 + 2),
                _ev("weight-entry", comp_ts, user_name=folder, ev_id=idx * 10 + 3),
            ]

        with patch(
            "backend.rinse_simple_shift_performance._load_rinse_user_maps",
            return_value={"split shift folder": {"user_id": 52, "display_name": folder}},
        ), patch(
            "backend.rinse_processing_productivity._load_shift_sessions_bulk",
            return_value={52: [{"clock_in_at": clock_in, "clock_out_at": datetime(2026, 6, 25, 16, 0)}]},
        ), patch(
            "backend.rinse_simple_shift_performance._employee_shift_window",
            return_value=(clock_in, datetime(2026, 6, 25, 16, 0), None),
        ), patch(
            "backend.daily_shift_roster.list_roster_entries",
            return_value=[],
        ), patch(
            "backend.daily_shift_roster.build_roster_role_lookup",
            return_value={"split shift folder": "folder"},
        ), patch(
            "backend.rinse_employee_completed_bags._load_upstream_processing_scan_times_bulk",
            return_value={},
        ), patch(
            "backend.rinse_employee_completed_bags._load_employee_day_scan_events_bulk",
            return_value={},
        ):
            out = build_employee_completed_bags_today(
                object(),
                3,
                completed_rows=rows,
                events_by_bag=events,
                selected_date_et=selected,
                registry_meta_by_bag={},
            )

        emp = next(e for e in out["employees"] if e["employee"] == folder)
        full_span_hours = (datetime(2026, 6, 25, 15, 0) - datetime(2026, 6, 25, 10, 0)).total_seconds() / 3600.0
        assert len(emp["folding_blocks"]) == 2
        block_sum_hours = sum(b["duration_seconds"] for b in emp["folding_blocks"]) / 3600.0
        assert 1.5 <= emp["productive_hours"] <= 2.5
        assert emp["productive_hours"] == round(block_sum_hours, 4)
        assert emp["productive_hours"] < full_span_hours - 1.0
        assert emp["bags_per_hour"] is not None
        assert 1.5 <= emp["bags_per_hour"] <= 3.0

    def test_same_bag_scan_does_not_set_folding_start(self):
        """Prior scan on the bag being completed must not anchor folding start."""
        clock_in = datetime(2026, 6, 25, 9, 43, 46)
        first_comp = datetime(2026, 6, 25, 10, 25, 0)
        same_bag = "D6TP8N672R"
        blocks = _compute_folding_blocks(
            roster_role="folder",
            clock_in=clock_in,
            clock_out=datetime(2026, 6, 25, 16, 54, 34),
            non_folding_scans=[(datetime(2026, 6, 25, 10, 17, 0), same_bag)],
            fold_completions=[(first_comp, same_bag)],
            wf_pipeline_scans=[(datetime(2026, 6, 25, 10, 15, 0), same_bag)],
        )
        assert len(blocks) == 1
        assert blocks[0]["start_time"] == clock_in.isoformat()
        assert blocks[0]["start_source"] == FOLD_BLOCK_START_CLOCK_IN
