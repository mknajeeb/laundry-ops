"""Tests for simplified Scope A / Scope B shift performance rules."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from backend.rinse_bag_activity_rules import (
    ROLE_DRYING,
    ROLE_FOLDING,
    ROLE_SORTING,
    ROLE_WASHING,
    ROLE_WEIGHING,
    ROLE_WORKITEMS,
    evaluate_bag_completion_v2,
    evaluate_weight_difference,
    extract_bag_activity_credits,
    find_strong_completion_evidence_v2,
    sorting_bounds_v2,
)
from backend.rinse_bag_stage_bounds import (
    first_weight_after_anchor,
    gaming_events_from_records,
    lifecycle_anchor,
    events_on_or_after,
    sorting_bounds_after_weight,
)


def _ev(purpose, at, *, user="Alex", rack="Rack", ev_id=1, scan_index=1):
    return {
        "id": ev_id,
        "rack": rack,
        "user_name": user,
        "purpose": purpose,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


def _sv(*events):
    return [_ev("sent-to-vendor", datetime(2026, 6, 4, 7, 0), ev_id=1, scan_index=1)] + list(events)


T0 = datetime(2026, 6, 4, 8, 0)
T1 = datetime(2026, 6, 4, 8, 10)
T2 = datetime(2026, 6, 4, 8, 20)
T3 = datetime(2026, 6, 4, 8, 30)
T4 = datetime(2026, 6, 4, 9, 0)
T5 = datetime(2026, 6, 4, 9, 30)
T6 = datetime(2026, 6, 4, 10, 0)


class TestCompletionRules:
    def test_completion_by_clean_rack(self):
        events = _sv(
            _ev("weight-entry", T1, user="Alice", ev_id=2, scan_index=2),
            _ev("move-bag", T6, user="Bob", rack="VeeWash Clean", ev_id=3, scan_index=3),
        )
        out = evaluate_bag_completion_v2(events)
        assert out.completed is True
        assert out.via_clean_rack is True
        assert out.exception_code is None
        assert out.needs_review is False

    def test_completion_by_processed_by_vendor_without_clean(self):
        events = _sv(
            _ev("weight-entry", T1, user="Alice", ev_id=2, scan_index=2),
            _ev("processed-by-vendor", T5, user="Vendor", ev_id=3, scan_index=3),
        )
        out = evaluate_bag_completion_v2(events)
        assert out.completed is True
        assert out.via_clean_rack is False
        assert out.exception_code == "COMPLETED_WITHOUT_FINAL_CLEAN_SCAN"
        assert out.completion_user == "Vendor"

    def test_completion_by_second_weight_without_clean(self):
        events = _sv(
            _ev("weight-entry", T1, user="Alice", ev_id=2, scan_index=2, rack="Scale"),
            _ev("weight-entry", T5, user="Alice", ev_id=3, scan_index=3, rack="Scale"),
        )
        out = evaluate_bag_completion_v2(events)
        assert out.completed is True
        assert out.exception_code == "COMPLETED_WITHOUT_FINAL_CLEAN_SCAN"
        evidence = find_strong_completion_evidence_v2(events)
        assert evidence is not None
        assert evidence[2] == "second-weight-entry"

    def test_completion_by_received_from_vendor_without_clean(self):
        events = _sv(
            _ev("weight-entry", T1, ev_id=2, scan_index=2),
            _ev("received-from-vendor", T5, user="Recv", ev_id=3, scan_index=3),
        )
        out = evaluate_bag_completion_v2(events)
        assert out.completed is True
        assert out.completion_kind == "received-from-vendor"


class TestSortingRules:
    def test_sorting_identified_by_add_photos(self):
        events = _sv(
            _ev("start-cleaning", T0, user="Prep", ev_id=2, scan_index=2),
            _ev("weight-entry", T1, user="Alice", ev_id=3, scan_index=3),
            _ev("move-bag", T2, user="Noise", ev_id=4, scan_index=4),
            _ev("add-photos", T3, user="Bob", ev_id=5, scan_index=5),
        )
        tl = gaming_events_from_records(events)
        anchor_ts, _ = lifecycle_anchor(tl)
        anchored = events_on_or_after(tl, anchor_ts)
        weight_ev, weight_ts = first_weight_after_anchor(anchored)
        add_ev, start_ev, _end = sorting_bounds_v2(anchored, weight_ts, weight_ev, full_timeline=tl)
        assert add_ev is not None
        assert add_ev.get("purpose") == "add-photos"
        assert start_ev is not None
        assert start_ev.get("purpose") == "start-cleaning"

    def test_sorting_start_fallback_to_weight_when_cleaning_missing(self):
        events = _sv(
            _ev("weight-entry", T1, user="Alice", ev_id=2, scan_index=2),
            _ev("add-photos", T3, user="Bob", ev_id=3, scan_index=3),
        )
        tl = gaming_events_from_records(events)
        anchored = events_on_or_after(tl, lifecycle_anchor(tl)[0])
        weight_ev, weight_ts = first_weight_after_anchor(anchored)
        _, start_ev, _ = sorting_bounds_v2(anchored, weight_ts, weight_ev, full_timeline=tl)
        assert start_ev.get("purpose") == "weight-entry"

    def test_sorting_bounds_after_weight_matches_v2(self):
        events = _sv(
            _ev("cleaning", T0, user="Alice", ev_id=2, scan_index=2),
            _ev("weight-entry", T1, user="Alice", ev_id=3, scan_index=3),
            _ev("add-photos", T3, user="Bob", ev_id=4, scan_index=4),
        )
        tl = gaming_events_from_records(events)
        anchored = events_on_or_after(tl, lifecycle_anchor(tl)[0])
        _, weight_ts = first_weight_after_anchor(anchored)
        start, end = sorting_bounds_after_weight(anchored, weight_ts, full_timeline=tl)
        assert start.get("purpose") == "cleaning"
        assert end.get("purpose") == "add-photos"


class TestActivityCredits:
    def test_weighing_user_is_weight_entry_user(self):
        events = _sv(
            _ev("cleaning", T0, user="Other", ev_id=2, scan_index=2),
            _ev("weight-entry", T1, user="Alice", ev_id=3, scan_index=3),
        )
        credits = extract_bag_activity_credits("B1", events)
        w = next(c for c in credits if c.role == ROLE_WEIGHING)
        assert w.employee == "Alice"
        assert w.needs_review is False
        assert "WEIGHING_START_CLEANING_MISSING" not in w.flags

    def test_washing_user_start_cleaning_without_drying(self):
        events = _sv(
            _ev("weight-entry", T1, user="Alice", ev_id=2, scan_index=2),
            _ev("start-cleaning", T3, user="Carl", ev_id=3, scan_index=3),
        )
        credits = extract_bag_activity_credits("B1", events)
        wash = next(c for c in credits if c.role == ROLE_WASHING)
        assert wash.employee == "Carl"
        assert "DRYING_PURPOSE_MISSING" in wash.flags

    def test_drying_user(self):
        events = _sv(
            _ev("start-cleaning", T2, ev_id=2, scan_index=2),
            _ev("drying", T4, user="Dana", ev_id=3, scan_index=3),
        )
        credits = extract_bag_activity_credits("B1", events)
        dry = next(c for c in credits if c.role == ROLE_DRYING)
        assert dry.employee == "Dana"

    def test_folding_user_clean_or_completion_signal(self):
        events_clean = _sv(
            _ev("move-bag", T6, user="Fin", rack="Clean 1", ev_id=2, scan_index=2),
        )
        fold = next(c for c in extract_bag_activity_credits("B1", events_clean) if c.role == ROLE_FOLDING)
        assert fold.employee == "Fin"

        events_proc = _sv(
            _ev("weight-entry", T1, ev_id=2, scan_index=2),
            _ev("processed-by-vendor", T5, user="Vendor", ev_id=3, scan_index=3),
        )
        fold2 = next(c for c in extract_bag_activity_credits("B2", events_proc) if c.role == ROLE_FOLDING)
        assert fold2.employee == "Vendor"
        assert fold2.needs_review is True

    def test_sorting_user_is_add_photos_user(self):
        events = _sv(
            _ev("weight-entry", T1, user="Alice", ev_id=2, scan_index=2),
            _ev("add-photos", T3, user="Bob", ev_id=3, scan_index=3),
        )
        sort = next(c for c in extract_bag_activity_credits("B1", events) if c.role == ROLE_SORTING)
        assert sort.employee == "Bob"

    def test_workitems_only_after_weight(self):
        events = _sv(
            _ev("create-workitem", T0, user="Early", ev_id=2, scan_index=2),
            _ev("weight-entry", T1, user="Alice", ev_id=3, scan_index=3),
            _ev("create-workitem", T2, user="Late", ev_id=4, scan_index=4),
        )
        credits = extract_bag_activity_credits("B1", events)
        wi = [c for c in credits if c.role == ROLE_WORKITEMS]
        assert len(wi) == 1
        assert wi[0].employee == "Late"


class TestWeightDifference:
    def test_weight_difference_threshold(self):
        w1 = _ev("weight-entry", T1, ev_id=2, scan_index=2, rack="Scale")
        w1["weight_lbs"] = 20.0
        w2 = _ev("weight-entry", T5, ev_id=3, scan_index=3, rack="Scale")
        w2["weight_lbs"] = 12.0
        events = _sv(w1, w2)
        out = evaluate_weight_difference(events, threshold_lbs=5.0)
        assert out.flagged is True
        assert out.difference_lbs == 8.0
        assert out.comparable is True
        assert out.first_weight_user == "Alex"

    def test_weight_difference_unavailable_with_single_weight(self):
        w1 = _ev("weight-entry", T1, ev_id=2, scan_index=2, rack="Scale")
        w1["weight_lbs"] = 20.0
        out = evaluate_weight_difference(_sv(w1), threshold_lbs=5.0)
        assert out.flagged is False
        assert out.comparable is False
        assert out.unavailable_reason == "No comparable first/second weights"


class TestSimplePayloadScopes:
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_scope_b_includes_checked_out_bag_with_activity(
        self,
        mock_settings,
        mock_maps,
        mock_meta,
        mock_events,
        mock_scope_b,
        mock_pending,
    ):
        from datetime import date
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload

        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0}
        mock_maps.return_value = {}
        mock_scope_b.return_value = ["CHECKED1"]
        mock_pending.return_value = {"rows": [], "incoming": {"groups": {"combined": {}}}, "wf_lifecycle": {"groups": {"combined": {"total": 0, "by_lifecycle_status": {}, "by_lifecycle_group": {}}}}, "hd_lifecycle": {"groups": {"combined": {"total": 0}}}, "checkout_rush": {}}
        mock_meta.return_value = {
            "CHECKED1": {
                "bag_id": "CHECKED1",
                "service_type": "WF",
                "rush_type": "RUSH",
                "logistics_status": "SENT_TO_RINSE",
            }
        }
        mock_events.return_value = {
            "CHECKED1": _sv(
                _ev("weight-entry", T1, user="Alice", ev_id=2, scan_index=2),
                _ev("start-cleaning", T3, user="Carl", ev_id=3, scan_index=3),
            )
        }
        cursor = MagicMock()
        payload = build_simple_shift_performance_payload(
            cursor, 1, period_start=date(2026, 6, 4), period_end=date(2026, 6, 4)
        )
        assert payload["scope_b_performance_day"]["total_bags_worked"] == 1
        assert payload["scope_b_performance_day"]["rush_wf"] == 1
        rec = payload["records"][0]
        assert rec["bag_id"] == "CHECKED1"
        assert rec["in_scope_a_active"] is False
        roles = {a["role"] for a in rec["activities"]}
        assert ROLE_WEIGHING in roles
        assert ROLE_WASHING in roles

    @patch("backend.rinse_simple_shift_performance._employee_shift_window")
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_role_wise_denominator_clock_in_to_last_activity(
        self,
        mock_settings,
        mock_maps,
        mock_meta,
        mock_events,
        mock_scope_b,
        mock_pending,
        mock_shift_window,
    ):
        from datetime import date
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload

        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0}
        mock_maps.return_value = {"alice": {"user_id": 10, "rinse_user_name": "Alice"}}
        mock_shift_window.return_value = (datetime(2026, 6, 4, 8, 0), datetime(2026, 6, 4, 17, 0), None)
        mock_scope_b.return_value = ["B1"]
        mock_pending.return_value = {
            "rows": [],
            "incoming": {"groups": {"combined": {}}},
            "wf_lifecycle": {"groups": {"combined": {"total": 0, "by_lifecycle_status": {}, "by_lifecycle_group": {}}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 0}}},
            "checkout_rush": {},
        }
        mock_meta.return_value = {"B1": {"bag_id": "B1", "service_type": "WF", "rush_type": "NON-RUSH"}}
        mock_events.return_value = {
            "B1": _sv(
                _ev("weight-entry", datetime(2026, 6, 4, 9, 15), user="Alice", ev_id=2, scan_index=2),
            )
        }
        cursor = MagicMock()
        payload = build_simple_shift_performance_payload(
            cursor, 1, period_start=date(2026, 6, 4), period_end=date(2026, 6, 4)
        )
        row = next(r for r in payload["employee_activity_summary"] if r["role"] == ROLE_WEIGHING)
        assert row["performance_hours"] == 1.25
        assert row["diagnostic"] is None

    @patch("backend.rinse_simple_shift_performance._employee_shift_window")
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_missing_clock_in_diagnostic(
        self,
        mock_settings,
        mock_maps,
        mock_meta,
        mock_events,
        mock_scope_b,
        mock_pending,
        mock_shift_window,
    ):
        from datetime import date
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload

        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0}
        mock_maps.return_value = {"alice": {"user_id": 10}}
        mock_shift_window.return_value = (None, None, "Clock-in missing")
        mock_scope_b.return_value = ["B1"]
        mock_pending.return_value = {
            "rows": [],
            "incoming": {"groups": {"combined": {}}},
            "wf_lifecycle": {"groups": {"combined": {"total": 0, "by_lifecycle_status": {}, "by_lifecycle_group": {}}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 0}}},
            "checkout_rush": {},
        }
        mock_meta.return_value = {"B1": {"bag_id": "B1", "service_type": "WF", "rush_type": "NON-RUSH"}}
        mock_events.return_value = {
            "B1": _sv(_ev("weight-entry", T1, user="Alice", ev_id=2, scan_index=2)),
        }
        cursor = MagicMock()
        payload = build_simple_shift_performance_payload(
            cursor, 1, period_start=date(2026, 6, 4), period_end=date(2026, 6, 4)
        )
        row = next(r for r in payload["employee_activity_summary"] if r["employee"] == "Alice")
        assert row["diagnostic"] == "Clock-in missing"
        assert row["performance_hours"] is None
        assert row["bags_per_hour"] is None


class TestDrilldownCountIntegrity:
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_ready_for_vendor_splits_match_drilldown(
        self,
        mock_settings,
        mock_maps,
        mock_meta,
        mock_events,
        mock_scope_b,
        mock_pending,
    ):
        from datetime import date
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload, _count_tag

        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0}
        mock_maps.return_value = {}
        mock_scope_b.return_value = []
        mock_meta.return_value = {}
        mock_events.return_value = {}
        mock_pending.return_value = {
            "rows": [
                {"bag_id": "R1", "record_scope": "incoming", "service_type": "WF", "effective_rush": "RUSH"},
                {"bag_id": "R2", "record_scope": "incoming", "service_type": "HD", "effective_rush": "RUSH"},
                {"bag_id": "N1", "record_scope": "incoming", "service_type": "WF", "effective_rush": "NON-RUSH"},
            ],
            "incoming": {
                "rows": [
                    {"bag_id": "R1", "record_scope": "incoming", "service_type": "WF", "effective_rush": "RUSH"},
                    {"bag_id": "R2", "record_scope": "incoming", "service_type": "HD", "effective_rush": "RUSH"},
                    {"bag_id": "N1", "record_scope": "incoming", "service_type": "WF", "effective_rush": "NON-RUSH"},
                ],
                "groups": {"combined": {}},
            },
            "wf_lifecycle": {"groups": {"combined": {"total": 0, "by_lifecycle_status": {}, "by_lifecycle_group": {}}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 0}}},
            "checkout_rush": {},
        }
        cursor = MagicMock()
        payload = build_simple_shift_performance_payload(
            cursor, 1, period_start=date(2026, 6, 4), period_end=date(2026, 6, 4)
        )
        rfv = payload["ready_for_vendor"]
        records = payload["records"]
        assert rfv["total"] == _count_tag(records, "ready_for_vendor") == 3
        assert rfv["rush_wf"] == _count_tag(records, "rfv_rush_wf") == 1
        assert rfv["rush_hd"] == _count_tag(records, "rfv_rush_hd") == 1
        assert rfv["nonrush_wf"] == _count_tag(records, "rfv_nonrush_wf") == 1

    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_active_work_excludes_incoming_and_matches_drilldown(
        self,
        mock_settings,
        mock_maps,
        mock_meta,
        mock_events,
        mock_scope_b,
        mock_pending,
    ):
        from datetime import date
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload, _count_tag

        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0}
        mock_maps.return_value = {}
        mock_scope_b.return_value = []
        mock_meta.return_value = {}
        mock_events.return_value = {}
        mock_pending.return_value = {
            "rows": [
                {"bag_id": "IN1", "record_scope": "incoming", "service_type": "WF", "effective_rush": "RUSH"},
                {"bag_id": "A1", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "RUSH", "current_lifecycle_status": "PENDING_WEIGHING"},
                {"bag_id": "A2", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "RUSH", "checkout_status": "CHECKOUT_PENDING"},
            ],
            "incoming": {"rows": [{"bag_id": "IN1", "record_scope": "incoming"}], "groups": {"combined": {}}},
            "wf_lifecycle": {"groups": {"combined": {"total": 2, "by_lifecycle_status": {}, "by_lifecycle_group": {}}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 0}}},
            "checkout_rush": {"checkout_pending": 1},
        }
        cursor = MagicMock()
        payload = build_simple_shift_performance_payload(
            cursor, 1, period_start=date(2026, 6, 4), period_end=date(2026, 6, 4)
        )
        active = payload["current_active_work"]
        checkout = payload["rush_checkout"]
        records = payload["records"]
        assert active["total"] == _count_tag(records, "active_work") == 2
        assert active["rush_wf"] == _count_tag(records, "active_rush_wf") == 2
        assert active["counts_add_up"] is True
        assert checkout["checkout_pending"] == _count_tag(records, "checkout_pending") == 1
        assert "checkout_pending" not in active
        incoming_rec = next(r for r in records if r["bag_id"] == "IN1")
        assert incoming_rec["in_scope_a_active"] is False
        assert "active_work" not in incoming_rec["drilldown_tags"]

    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_external_employee_excluded_from_productivity(
        self,
        mock_settings,
        mock_maps,
        mock_meta,
        mock_events,
        mock_scope_b,
        mock_pending,
    ):
        from datetime import date
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload

        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0}
        mock_maps.return_value = {"alex (veewash)": {"user_id": 1}}
        mock_scope_b.return_value = ["B1"]
        mock_meta.return_value = {"B1": {"bag_id": "B1", "service_type": "WF", "rush_type": "RUSH"}}
        mock_events.return_value = {
            "B1": [
                _ev("sent-to-vendor", datetime(2026, 6, 4, 7, 0), user="Vendor", ev_id=1, scan_index=1),
                _ev("weight-entry", T1, user="Alex (VeeWash)", ev_id=2, scan_index=2),
                _ev("move-bag", T5, user="Michael Osei", ev_id=3, scan_index=3, rack="VeeWash Clean"),
            ]
        }
        mock_pending.return_value = {
            "rows": [],
            "incoming": {"rows": [], "groups": {"combined": {}}},
            "wf_lifecycle": {"groups": {"combined": {"total": 0, "by_lifecycle_status": {}, "by_lifecycle_group": {}}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 0}}},
            "checkout_rush": {},
        }
        cursor = MagicMock()
        with patch("backend.rinse_simple_shift_performance._employee_shift_window", return_value=(T0, T6, None)):
            payload = build_simple_shift_performance_payload(
                cursor, 1, period_start=date(2026, 6, 4), period_end=date(2026, 6, 4)
            )
        included = payload["employee_diagnostics"]["included_employees"]
        excluded = payload["employee_diagnostics"]["excluded_external"]
        assert any("veewash" in e.lower() for e in included)
        assert "Michael Osei" in excluded

    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_shift_status_has_rush_non_rush_splits(
        self,
        mock_settings,
        mock_maps,
        mock_meta,
        mock_events,
        mock_scope_b,
        mock_pending,
    ):
        from datetime import date
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload

        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0}
        mock_maps.return_value = {}
        mock_scope_b.return_value = []
        mock_meta.return_value = {}
        mock_events.return_value = {
            "N1": [
                _ev("sent-to-vendor", datetime(2026, 6, 4, 7, 0), user="Vendor", ev_id=1, scan_index=1),
                _ev("weight-entry", T1, user="Alice", ev_id=2, scan_index=2),
            ]
        }
        mock_pending.return_value = {
            "rows": [
                {"bag_id": "R1", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "RUSH", "current_lifecycle_status": "PENDING_WEIGHING"},
                {"bag_id": "N1", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "NON-RUSH", "current_lifecycle_status": "WEIGHED_NOT_STARTED"},
            ],
            "incoming": {"rows": [], "groups": {"combined": {}}},
            "wf_lifecycle": {"groups": {"combined": {"total": 2, "by_lifecycle_status": {}, "by_lifecycle_group": {}}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 0}}},
            "checkout_rush": {},
        }
        cursor = MagicMock()
        payload = build_simple_shift_performance_payload(
            cursor, 1, period_start=date(2026, 6, 4), period_end=date(2026, 6, 4)
        )
        weighed = payload["shift_status"]["weighed"]
        assert weighed["all"] == 1
        assert weighed["rush"] == 0
        assert weighed["non_rush"] == 1
