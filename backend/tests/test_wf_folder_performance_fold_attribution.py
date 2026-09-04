"""Regression tests A–F: Performance OI-window fold attribution (not CW)."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.management_wf_folder_fold_attribution import (
    EXCEPTION_NEEDS_ATTRIBUTION,
    EXCEPTION_OUTSIDE_FOLDER_SESSION,
    enrich_folder_performance_bags_with_oi_fold_attribution,
    extract_oi_window_folder_fold_evidence,
    is_provable_folder_employee,
)
from backend.management_wf_folder_performance import (
    _assign_bag_into_folder_sessions,
    build_day_folder_performance,
)
from backend.rinse_employee_productivity_sessions import ASSIGNMENT_AUTO


DAY = date(2026, 9, 4)
ANCHOR = datetime(2026, 9, 4, 4, 40, 0)


def _ev(purpose, ts, user, rack=None):
    return {
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "user_name": user,
        "rack": rack,
    }


class TestExtractOiWindowFolderFold:
    def test_a_later_dirty_stv_does_not_erase_fold_employee(self):
        """A — fold/sign-off then later Dirty STV; employee retained in OI window."""
        events = [
            _ev("sent-to-vendor", ANCHOR, "Driver", "Rinse Zipvan"),
            _ev("sent-to-vendor", datetime(2026, 9, 4, 5, 53), "Driver", "VeeWash Dirty"),
            _ev("garments-reviewed", datetime(2026, 9, 4, 8, 48), "Mrs Chen (VeeWash)"),
            _ev("weight-entry", datetime(2026, 9, 4, 9, 5), "Mrs Chen (VeeWash)"),
            _ev("processed-by-vendor", datetime(2026, 9, 4, 9, 5), "Mrs Chen (VeeWash)"),
            # Later Dirty STV must not truncate OI-window fold evidence.
            _ev("sent-to-vendor", datetime(2026, 9, 4, 11, 39), "Driver", "VeeWash Dirty"),
        ]
        ev = extract_oi_window_folder_fold_evidence(
            events,
            cycle_anchor_at=ANCHOR,
            lifecycle_end_exclusive=None,
        )
        assert ev is not None
        assert ev["fold_employee"] == "Mrs Chen (VeeWash)"
        assert ev["fold_complete_at"] == datetime(2026, 9, 4, 9, 5)
        assert ev["garments_reviewed_at"] == datetime(2026, 9, 4, 8, 48)

    def test_b_mapped_scan_user_fold_chain(self):
        """B — v2/fold user present with GR→weight-entry."""
        events = [
            _ev("sent-to-vendor", ANCHOR, "Driver", "Rinse Zipvan"),
            _ev(
                "garments-reviewed",
                datetime(2026, 9, 4, 8, 7),
                "Veewash (Training Account 2)",
            ),
            _ev(
                "weight-entry",
                datetime(2026, 9, 4, 8, 51),
                "Veewash (Training Account 2)",
            ),
            _ev(
                "processed-by-vendor",
                datetime(2026, 9, 4, 8, 51),
                "Veewash (Training Account 2)",
            ),
        ]
        ev = extract_oi_window_folder_fold_evidence(
            events, cycle_anchor_at=ANCHOR, lifecycle_end_exclusive=None
        )
        assert ev["fold_employee"] == "Veewash (Training Account 2)"
        assert ev["fold_complete_at"] == datetime(2026, 9, 4, 8, 51)

    def test_d_lifecycle_completion_without_fold_excluded(self):
        """D — PBV/strong without garments-reviewed → no Folder membership."""
        events = [
            _ev("sent-to-vendor", ANCHOR, "Driver", "Rinse Zipvan"),
            _ev("sent-to-vendor", datetime(2026, 9, 4, 6, 1), "Driver", "VeeWash Dirty"),
            _ev("weight-entry", datetime(2026, 9, 4, 9, 36), "Francis (Veewash)"),
            _ev(
                "processed-by-vendor",
                datetime(2026, 9, 4, 15, 54),
                "Jordan Graham",
            ),
        ]
        assert (
            extract_oi_window_folder_fold_evidence(
                events, cycle_anchor_at=ANCHOR, lifecycle_end_exclusive=None
            )
            is None
        )

    def test_e_normal_fold_gr_then_weight_entry(self):
        """E — normal GR → weight-entry/PBV unchanged."""
        events = [
            _ev("sent-to-vendor", ANCHOR, "Driver", "Rinse Zipvan"),
            _ev("garments-reviewed", datetime(2026, 9, 4, 8, 30), "Yessenia (Veewash)"),
            _ev("weight-entry", datetime(2026, 9, 4, 8, 32), "Yessenia (Veewash)"),
            _ev("processed-by-vendor", datetime(2026, 9, 4, 8, 32), "Yessenia (Veewash)"),
        ]
        ev = extract_oi_window_folder_fold_evidence(
            events, cycle_anchor_at=ANCHOR, lifecycle_end_exclusive=None
        )
        assert ev["fold_employee"] == "Yessenia (Veewash)"
        assert ev["fold_complete_at"] == datetime(2026, 9, 4, 8, 32)
        assert ev["fold_complete_purpose"] == "weight-entry"

    def test_f_reusable_bag_oi_scoped(self):
        """F — lifecycle A fold cannot leak into lifecycle B window."""
        life_a_anchor = datetime(2026, 9, 1, 8, 0)
        life_b_anchor = datetime(2026, 9, 4, 4, 40)
        events = [
            _ev("garments-reviewed", datetime(2026, 9, 1, 10, 0), "Folder A"),
            _ev("weight-entry", datetime(2026, 9, 1, 10, 5), "Folder A"),
            _ev("sent-to-vendor", life_b_anchor, "Driver", "Rinse Zipvan"),
            _ev("garments-reviewed", datetime(2026, 9, 4, 9, 0), "Folder B"),
            _ev("weight-entry", datetime(2026, 9, 4, 9, 10), "Folder B"),
        ]
        a = extract_oi_window_folder_fold_evidence(
            events,
            cycle_anchor_at=life_a_anchor,
            lifecycle_end_exclusive=life_b_anchor,
        )
        b = extract_oi_window_folder_fold_evidence(
            events,
            cycle_anchor_at=life_b_anchor,
            lifecycle_end_exclusive=None,
        )
        assert a["fold_employee"] == "Folder A"
        assert b["fold_employee"] == "Folder B"
        assert a["fold_complete_at"] == datetime(2026, 9, 1, 10, 5)
        assert b["fold_complete_at"] == datetime(2026, 9, 4, 9, 10)


class TestOutsideSessionVsNeedsAttribution:
    def test_c_outside_session_keeps_credited_employee(self):
        """C — valid employee + fold outside session → Outside Folder Session."""
        bag = {
            "bag_id": "F48A3C88MM",
            "credited_employee": "Tarannum (Veewash)",
            "effective_employee": "Tarannum (Veewash)",
            "completion_time": "2026-09-04 08:39:00",
            "credit_timestamp": "2026-09-04 08:39:00",
        }
        # Session ends before fold.
        sessions = [
            {
                "session_id": "WF-01",
                "session_code": "WF-01",
                "_start_dt": datetime(2026, 9, 4, 8, 0, 0),
                "_end_dt": datetime(2026, 9, 4, 8, 8, 27),
                "start_time": "2026-09-04 08:00:00",
                "end_time": "2026-09-04 08:08:27",
            }
        ]
        out = _assign_bag_into_folder_sessions(bag, sessions)
        assert out["session_id"] is None
        assert out["unmapped_reason"] == "OUTSIDE_FOLDER_SESSION"
        assert is_provable_folder_employee(out.get("credited_employee"))

    def test_mapped_user_inside_session_auto_assigns(self):
        bag = {
            "bag_id": "2HCJP6S8FL",
            "credited_employee": "Veewash (Training Account 2)",
            "completion_time": "2026-09-04 08:51:00",
            "credit_timestamp": "2026-09-04 08:51:00",
        }
        sessions = [
            {
                "session_id": "WF-01",
                "session_code": "WF-01",
                "_start_dt": datetime(2026, 9, 4, 8, 0, 42),
                "_end_dt": datetime(2026, 9, 4, 15, 17, 40),
                "start_time": "2026-09-04 08:00:42",
                "end_time": "2026-09-04 15:17:40",
            }
        ]
        out = _assign_bag_into_folder_sessions(bag, sessions)
        assert out["session_assignment"] == ASSIGNMENT_AUTO
        assert out["session_id"] == "WF-01"


class TestEnrichFillsMissingEmployeeAndExcludesNonFold:
    def test_enrich_fills_null_employee_from_oi_fold(self):
        bags = [
            {
                "bag_id": "2R2O1YCZHY",
                "credited_employee": "Unassigned / No Attribution",
                "employee": "Unassigned / No Attribution",
                "completion_time": "2026-09-04 09:05:00",
            }
        ]
        evidence = {
            "qualifying_fold": True,
            "garments_reviewed_at": datetime(2026, 9, 4, 8, 48),
            "garments_reviewed_user": "Mrs Chen (VeeWash)",
            "fold_complete_at": datetime(2026, 9, 4, 9, 5),
            "fold_employee": "Mrs Chen (VeeWash)",
            "fold_complete_purpose": "weight-entry",
            "order_instance_id": 4188,
            "cycle_anchor_at": ANCHOR,
            "lifecycle_end_exclusive": None,
        }
        with patch(
            "backend.management_wf_folder_fold_attribution.resolve_folder_fold_attribution_for_bag",
            return_value=evidence,
        ):
            out = enrich_folder_performance_bags_with_oi_fold_attribution(
                MagicMock(), 3, DAY, bags
            )
        assert len(out) == 1
        assert out[0]["credited_employee"] == "Mrs Chen (VeeWash)"
        assert out[0]["folder_employee_source"] == "oi_window_fold_evidence"
        assert out[0]["fold_complete_at"] == "2026-09-04 09:05:00"

    def test_enrich_excludes_non_fold(self):
        bags = [
            {
                "bag_id": "B25VAXND8V",
                "credited_employee": None,
                "completion_time": "2026-09-04 15:54:00",
            }
        ]
        with patch(
            "backend.management_wf_folder_fold_attribution.resolve_folder_fold_attribution_for_bag",
            return_value=None,
        ):
            out = enrich_folder_performance_bags_with_oi_fold_attribution(
                MagicMock(), 3, DAY, bags
            )
        assert out == []


class TestDayBuildExceptionClasses:
    def test_needs_vs_outside_split(self):
        bags = [
            {
                "bag_id": "NEED1",
                "service_type": "WF",
                "pre_weight_lbs": 10.0,
                "credited_weight_lbs": 10.0,
                "credited_weight_source": "EVIDENCE_PRE",
                "employee": None,
                "credited_employee": None,
                "completion_time": "2026-09-04 10:00:00",
                "folder_fold_qualified": True,
                "fold_complete_at": "2026-09-04 10:00:00",
            },
            {
                "bag_id": "OUT1",
                "service_type": "WF",
                "pre_weight_lbs": 12.0,
                "credited_weight_lbs": 12.0,
                "credited_weight_source": "EVIDENCE_PRE",
                "employee": "Tarannum (Veewash)",
                "credited_employee": "Tarannum (Veewash)",
                "completion_time": "2026-09-04 08:39:00",
                "folder_fold_qualified": True,
                "fold_complete_at": "2026-09-04 08:39:00",
            },
        ]

        def _enrich(_c, _o, _d, incoming):
            return [dict(b) for b in incoming]

        with (
            patch(
                "backend.management_wf_folder_performance.load_completed_productivity_day_bags",
                return_value=bags,
            ),
            patch(
                "backend.management_wf_folder_performance.load_active_attribution_overrides",
                return_value={},
            ),
            patch(
                "backend.management_wf_folder_performance.enrich_folder_performance_bags_with_oi_fold_attribution",
                side_effect=_enrich,
            ),
            patch(
                "backend.rinse_simple_shift_performance._load_rinse_user_maps",
                return_value={
                    "tarannum (veewash)": {
                        "user_id": 35,
                        "rinse_user_name": "Tarannum (Veewash)",
                    }
                },
            ),
            patch(
                "backend.management_wf_folder_performance.load_day_job_segments_by_user",
                return_value={},
            ),
            patch(
                "backend.management_wf_folder_performance.load_shift_sessions_by_id",
                return_value={},
            ),
            patch(
                "backend.management_wf_folder_performance.apply_canonical_pre_to_folder_performance_bags",
                side_effect=lambda _c, _o, _d, b: [dict(x) for x in b],
            ),
        ):
            day = build_day_folder_performance(
                MagicMock(), 3, selected_date_et=DAY, attach_customers=False
            )

        assert day["needs_attribution_count"] == 1
        assert day["outside_folder_session_count"] == 1
        assert day["needs_attribution_orders"][0]["bag_id"] == "NEED1"
        assert (
            day["needs_attribution_orders"][0]["exception_class"]
            == EXCEPTION_NEEDS_ATTRIBUTION
        )
        assert day["outside_folder_session_orders"][0]["bag_id"] == "OUT1"
        assert (
            day["outside_folder_session_orders"][0]["exception_class"]
            == EXCEPTION_OUTSIDE_FOLDER_SESSION
        )
        assert day["outside_folder_session_orders"][0]["credited_employee"] == (
            "Tarannum (Veewash)"
        )
