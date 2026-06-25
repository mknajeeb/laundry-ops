"""Tests for employee completed bags today attribution and productivity."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

from backend.rinse_at_vendor_module import MOD_AT_VENDOR_COMPLETED
from backend.rinse_employee_completed_bags import (
    UNKNOWN_EMPLOYEE,
    FOLD_BLOCK_END_CLOCK_OUT,
    FOLD_BLOCK_START_CLOCK_IN,
    FOLD_BLOCK_START_PRIOR_SCAN,
    PRODUCTIVITY_END_CLOCK_OUT,
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
            "backend.rinse_employee_completed_bags._build_roster_role_lookup",
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

    def test_operator_productive_hours_use_folding_blocks(self):
        row = _completed_row("BAG1")
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1),
                _ev("add-photos", T2, user_name="Processor"),
                _ev("weight-entry", T2, user_name="Weight Clerk", ev_id=5),
                _ev("weight-entry", T3, user_name="Weight Clerk", ev_id=6),
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

    def test_folder_productive_hours_use_clock_out_when_set(self):
        row = _completed_row("BAG1")
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1),
                _ev("add-photos", T2),
                _ev("weight-entry", T3, user_name="Weight Clerk"),
            ],
        }
        out = self._build(
            [row],
            events,
            clock_out=CLOCK_OUT,
            roster_roles={"weight clerk": "folder"},
        )
        emp = next(e for e in out["employees"] if e["employee"] == "Weight Clerk")
        expected_hours = round((CLOCK_OUT - CLOCK_IN).total_seconds() / 3600.0, 4)
        assert emp["productive_end_time"] == CLOCK_OUT.isoformat()
        assert emp["productivity_end_source"] == PRODUCTIVITY_END_CLOCK_OUT
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
                _ev("weight-entry", T3, user_name="Folder Person", ev_id=4),
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
                _ev("drying", T2, user_name="Weight Clerk"),
                _ev("weight-entry", T1, user_name="Processor"),
                _ev("add-photos", datetime(2026, 6, 10, 6, 30), user_name="Processor"),
                _ev("weight-entry", T3, user_name="Weight Clerk", ev_id=5),
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
                _ev("weight-entry", T3, user_name="Weight Clerk", ev_id=4),
            ],
            "BAG2": [
                _ev("sent-to-vendor", T0),
                _ev("drying", gap, user_name="Weight Clerk", ev_id=5),
                _ev("weight-entry", T1),
                _ev("add-photos", datetime(2026, 6, 10, 7, 45), user_name="Processor"),
                _ev("weight-entry", T4, user_name="Weight Clerk", ev_id=7),
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
                _ev("weight-entry", T3, user_name="Folder Person", ev_id=4),
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
        assert emp["folding_blocks"][0]["end_time"] == CLOCK_OUT.isoformat()
        assert emp["folding_blocks"][0]["end_source"] == FOLD_BLOCK_END_CLOCK_OUT
        expected_hours = round((CLOCK_OUT - CLOCK_IN).total_seconds() / 3600.0, 4)
        assert emp["productive_hours"] == expected_hours

    def test_block_ends_at_last_completion_before_non_folding_scan(self):
        row = _completed_row("BAG1")
        after = datetime(2026, 6, 10, 7, 30)
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0),
                _ev("weight-entry", T1),
                _ev("add-photos", T2, user_name="Processor"),
                _ev("weight-entry", T3, user_name="Weight Clerk", ev_id=4),
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
                _ev("weight-entry", T3, user_name="Weight Clerk", ev_id=6),
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
                _ev("weight-entry", T3, user_name="Weight Clerk", ev_id=5),
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
                _ev("weight-entry", T3, user_name="Weight Clerk", ev_id=5),
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
                _ev("weight-entry", T3, user_name="Weight Clerk", ev_id=5),
            ],
        }
        out = self._build([row], events, roster_roles={"weight clerk": "operator"})
        emp = out["employees"][0]
        assert emp["folding_blocks"][0]["start_time"] == CLOCK_IN.isoformat()

    def test_repeat_trip_ignores_pre_anchor_non_folding_scans(self):
        resend = datetime(2026, 6, 10, 6, 30)
        post_resend = datetime(2026, 6, 10, 6, 45)
        row = _completed_row("BAG1")
        events = {
            "BAG1": [
                _ev("sent-to-vendor", T0, ev_id=1),
                _ev("drying", T1, user_name="Weight Clerk", ev_id=2),
                _ev("sent-to-vendor", resend, ev_id=3),
                _ev("drying", post_resend, user_name="Weight Clerk", ev_id=4),
                _ev("weight-entry", T1, user_name="Processor", ev_id=5),
                _ev("add-photos", T2, user_name="Processor", ev_id=6),
                _ev("weight-entry", T3, user_name="Weight Clerk", ev_id=7),
            ],
        }
        out = self._build([row], events, roster_roles={"weight clerk": "operator"})
        emp = out["employees"][0]
        assert emp["folding_blocks"][0]["start_time"] == post_resend.isoformat()

    def test_folding_blocks_sum_productive_hours(self):
        blocks = _compute_folding_blocks(
            roster_role="operator",
            clock_in=CLOCK_IN,
            clock_out=CLOCK_OUT,
            non_folding_scans=[T2, datetime(2026, 6, 10, 7, 30)],
            fold_completions=[T3, T4],
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
