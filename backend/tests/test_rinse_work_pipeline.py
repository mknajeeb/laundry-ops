"""Tests for Current Work Pipeline scope, carryover, pending wash, and sent/left logic."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_bag_activity_rules import evaluate_bag_completion_v2
from backend.rinse_work_pipeline import (
    bag_is_pipeline_eligible,
    bag_is_sent_or_left,
    build_current_work_pipeline_debug,
)


def _pending(**kwargs):
    base = {
        "record_scope": "wf_lifecycle",
        "in_active_staging": True,
        "current_lifecycle_status": "IN_WASHING",
    }
    base.update(kwargs)
    return base


class TestSentOrLeft:
    def test_sent_from_lifecycle_not_checkout(self):
        row = _pending(current_lifecycle_status="SENT_TO_RINSE")
        assert bag_is_sent_or_left(row, None, row) is True

    def test_not_sent_from_manual_checkout_only(self):
        row = _pending(
            current_lifecycle_status="FOLDED_COMPLETED",
            checkout_status="NOT_CHECKED_OUT",
        )
        completion = evaluate_bag_completion_v2([])
        assert bag_is_sent_or_left(row, completion, row) is False


class TestPipelineEligibility:
    def test_carryover_active_in_pipeline(self):
        row = _pending(bag_id="OLD1", current_lifecycle_status="IN_WASHING")
        assert bag_is_pipeline_eligible(row, evaluate_bag_completion_v2([]), row, []) is True

    def test_completed_excluded_from_pipeline(self):
        events = [
            {
                "purpose": "move-bag",
                "rack": "VeeWash Clean",
                "scanned_at_parsed": datetime(2026, 6, 7, 12, 0),
            }
        ]
        completion = evaluate_bag_completion_v2(events)
        row = _pending(current_lifecycle_status="FOLDED_COMPLETED")
        assert bag_is_pipeline_eligible(row, completion, row, events) is False

    def test_sent_excluded_from_pipeline(self):
        row = _pending(current_lifecycle_status="SENT_TO_RINSE")
        assert bag_is_pipeline_eligible(row, evaluate_bag_completion_v2([]), row, []) is False


class TestPipelineDebug:
    def test_carryover_not_in_facility_today(self):
        debug = build_current_work_pipeline_debug(
            facility_bag_ids=["TODAY1"],
            pipeline_bag_ids=["TODAY1", "OLD1"],
            staging_bag_ids=["TODAY1", "OLD1"],
            completed_excluded=["DONE1"],
            sent_excluded=["SENT1"],
        )
        assert debug["entered_today_still_active"] == ["TODAY1"]
        assert debug["carryover_active_from_prior_day"] == ["OLD1"]
        assert debug["completed_excluded"] == ["DONE1"]
        assert debug["sent_excluded"] == ["SENT1"]


class TestPipelinePayload:
    @patch("backend.rinse_facility_tracker.load_facility_entry_bag_ids")
    @patch("backend.rinse_presence_sync_status.get_ready_for_vendor_sync_status")
    @patch("backend.rinse_dashboard_staging.get_dashboard_active_staging_snapshot")
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_carryover_in_pipeline_not_facility_tracker(
        self,
        mock_settings,
        mock_maps,
        mock_meta,
        mock_events,
        mock_scope_b,
        mock_pending,
        mock_dashboard,
        mock_rfv_sync,
        mock_facility_ids,
    ):
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload, _count_tag

        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0, "facility_entry_racks": ["VeeWash Dirty"]}
        mock_maps.return_value = {}
        mock_scope_b.return_value = []
        mock_meta.return_value = {
            "TODAY": {"bag_id": "TODAY", "service_type": "WF", "rush_type": "RUSH"},
            "OLD": {"bag_id": "OLD", "service_type": "WF", "rush_type": "NON-RUSH"},
        }
        mock_events.return_value = {"TODAY": [], "OLD": []}
        mock_facility_ids.return_value = {"TODAY"}
        mock_rfv_sync.return_value = {"stale": False, "enabled": True, "latest_status": "success"}
        mock_dashboard.return_value = {
            "total_orders": 2,
            "wf_rush": 1,
            "wf_non_rush": 1,
            "hd_rush": 0,
            "hd_non_rush": 0,
            "unique_bag_ids": ["TODAY", "OLD"],
            "rush_wf_ids": ["TODAY"],
            "nonrush_wf_ids": ["OLD"],
            "rush_hd_ids": [],
            "nonrush_hd_ids": [],
            "unknown_ids": [],
            "rows": [],
            "staging_row_count": 2,
            "duplicate_staging_rows": 0,
        }
        mock_pending.return_value = {
            "rows": [
                {"bag_id": "TODAY", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "RUSH", "current_lifecycle_status": "IN_WASHING", "in_active_staging": True},
                {"bag_id": "OLD", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "NON-RUSH", "current_lifecycle_status": "IN_WASHING", "in_active_staging": True},
            ],
            "incoming": {"rows": [], "groups": {"combined": {}}},
            "wf_lifecycle": {"groups": {"combined": {"total": 2, "by_lifecycle_status": {}, "by_lifecycle_group": {}}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 0}}},
            "checkout_summary": {"rush": {}},
        }
        payload = build_simple_shift_performance_payload(
            MagicMock(), 1, period_start=date(2026, 6, 7), period_end=date(2026, 6, 7), include_debug=True
        )
        assert payload["facility_tracker_today"]["total"] == 1
        assert payload["current_work_pipeline"]["total"] == 2
        overlap = payload["scope_overlap"]["current_work_pipeline"]
        assert "OLD" in overlap["carryover_active_from_prior_day"]
        assert "checkout_pending" not in str(payload["records"])

    @patch("backend.rinse_facility_tracker.load_facility_entry_bag_ids")
    @patch("backend.rinse_presence_sync_status.get_ready_for_vendor_sync_status")
    @patch("backend.rinse_dashboard_staging.get_dashboard_active_staging_snapshot")
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_pending_wash_split_and_last_wash(
        self,
        mock_settings,
        mock_maps,
        mock_meta,
        mock_events,
        mock_scope_b,
        mock_pending,
        mock_dashboard,
        mock_rfv_sync,
        mock_facility_ids,
    ):
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload, _count_tag

        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0, "facility_entry_racks": ["VeeWash Dirty"]}
        mock_maps.return_value = {}
        mock_scope_b.return_value = ["R1", "N1"]
        mock_meta.return_value = {
            "R1": {"bag_id": "R1", "service_type": "WF", "rush_type": "RUSH"},
            "N1": {"bag_id": "N1", "service_type": "WF", "rush_type": "NON-RUSH"},
        }
        mock_events.return_value = {
            "R1": [
                {"purpose": "start-cleaning", "scanned_at_parsed": datetime(2026, 6, 7, 10, 0), "user_name": "Alice"},
            ],
            "N1": [],
        }
        mock_facility_ids.return_value = set()
        mock_rfv_sync.return_value = {"stale": False, "enabled": True, "latest_status": "success"}
        mock_dashboard.return_value = {
            "total_orders": 2,
            "wf_rush": 1,
            "wf_non_rush": 1,
            "hd_rush": 0,
            "hd_non_rush": 0,
            "unique_bag_ids": ["R1", "N1"],
            "rush_wf_ids": ["R1"],
            "nonrush_wf_ids": ["N1"],
            "rush_hd_ids": [],
            "nonrush_hd_ids": [],
            "unknown_ids": [],
            "rows": [],
            "staging_row_count": 2,
            "duplicate_staging_rows": 0,
        }
        mock_pending.return_value = {
            "rows": [
                {"bag_id": "R1", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "RUSH", "current_lifecycle_status": "IN_WASHING", "in_active_staging": True},
                {"bag_id": "N1", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "NON-RUSH", "current_lifecycle_status": "SORTED_READY_FOR_WASH", "in_active_staging": True},
            ],
            "incoming": {"rows": [], "groups": {"combined": {}}},
            "wf_lifecycle": {"groups": {"combined": {"total": 2, "by_lifecycle_status": {}, "by_lifecycle_group": {}}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 0}}},
            "checkout_summary": {"rush": {}},
        }
        payload = build_simple_shift_performance_payload(
            MagicMock(), 1, period_start=date(2026, 6, 7), period_end=date(2026, 6, 7), include_debug=True
        )
        pipeline = payload["current_work_pipeline"]
        assert pipeline["pending_wash_nonrush"] == _count_tag(payload["records"], "wf_pending_wash_nonrush") == 1
        assert pipeline["pending_wash_rush"] == 0
        assert pipeline["last_rush_wash"]["bag_id"] == "R1"
        assert pipeline["last_rush_wash"]["employee"] == "Alice"
        debug = payload["debug_audit"]["current_work_pipeline"]
        assert debug["last_rush_wash"]["bag_id"] == "R1"
