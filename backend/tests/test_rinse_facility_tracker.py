"""Tests for Facility Tracker Today vs Current Active Work Now scopes."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_facility_tracker import (
    build_facility_tracker_section,
    build_scope_overlap_debug,
    classify_bag_ids_into_section,
    load_facility_entry_bag_ids,
    rack_is_facility_entry,
)


class TestFacilityEntryRack:
    def test_default_rack_match(self):
        assert rack_is_facility_entry("VeeWash Dirty", ["VeeWash Dirty"])
        assert rack_is_facility_entry("veewash dirty", ["VeeWash Dirty"])
        assert not rack_is_facility_entry("VeeWash Clean", ["VeeWash Dirty"])

    def test_load_facility_entry_bag_ids_from_scan_events(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {"bag_id": "A1", "rack": "VeeWash Dirty"},
            {"bag_id": "B1", "rack": "VeeWash Clean"},
            {"bag_id": "A1", "rack": "VeeWash Dirty"},
        ]
        with patch("backend.rinse_facility_tracker.table_exists", return_value=True):
            ids = load_facility_entry_bag_ids(
                cursor,
                1,
                period_start=date(2026, 6, 7),
                period_end=date(2026, 6, 7),
                entry_racks=["VeeWash Dirty"],
            )
        assert ids == {"A1"}


class TestScopeClassification:
    def test_classify_bags_into_buckets(self):
        meta = {
            "R1": {"bag_id": "R1", "service_type": "WF", "rush_type": "RUSH"},
            "H1": {"bag_id": "H1", "service_type": "HD", "effective_rush": "NON-RUSH"},
        }
        section = classify_bag_ids_into_section(
            ["R1", "H1"],
            meta,
            date(2026, 6, 7),
            source="test",
            drilldown_filter="facility_tracker",
            scope_label="facility_tracker_today",
        )
        assert section["total"] == 2
        assert section["rush_wf"] == 1
        assert section["nonrush_hd"] == 1
        assert section["counts_add_up"] is True

    def test_facility_tracker_keeps_completed_bags_in_scope(self):
        section = build_facility_tracker_section(
            ["DONE1"],
            {"DONE1": {"bag_id": "DONE1", "service_type": "WF", "rush_type": "RUSH"}},
            date(2026, 6, 7),
            entry_racks=["VeeWash Dirty"],
            period_start=date(2026, 6, 7),
            period_end=date(2026, 6, 7),
        )
        assert section["total"] == 1
        assert section["entry_racks"] == ["VeeWash Dirty"]


class TestScopeOverlap:
    def test_overlap_examples(self):
        overlap = build_scope_overlap_debug(
            facility_bag_ids=["TODAY1", "BOTH1", "DONE1"],
            active_bag_ids=["BOTH1", "OLD1"],
        )
        assert overlap["entered_today_and_still_active"] == ["BOTH1"]
        assert overlap["entered_today_and_completed"] == ["DONE1", "TODAY1"]
        assert overlap["carryover_active_from_prior_day"] == ["OLD1"]


class TestFacilityTrackerStatus:
    def test_completed_bag_stays_in_facility_tracker_not_active(self):
        from backend.rinse_facility_tracker import enrich_facility_tracker_status

        section = {"total": 1, "bag_ids": ["DONE1"]}
        records = {
            "DONE1": {"bag_id": "DONE1", "completed": True, "current_status": "FOLDED_COMPLETED"},
        }
        out = enrich_facility_tracker_status(
            section,
            bag_ids=["DONE1"],
            records_by_bag=records,
            active_bag_ids=[],
            staging_bag_ids=[],
        )
        assert out["completed"] == 1
        assert out["still_active"] == 0
        assert "DONE1" in out["completed_ids"]


class TestPayloadFacilityTracker:
    @patch("backend.rinse_facility_tracker.load_facility_entry_bag_ids")
    @patch("backend.rinse_presence_sync_status.get_ready_for_vendor_sync_status")
    @patch("backend.rinse_dashboard_staging.get_dashboard_active_staging_snapshot")
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_facility_and_active_scopes_differ(
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
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload

        mock_settings.return_value = {
            "weight_difference_threshold_lbs": 5.0,
            "facility_entry_racks": ["VeeWash Dirty"],
        }
        mock_maps.return_value = {}
        mock_scope_b.return_value = []
        mock_meta.return_value = {
            "TODAY": {"bag_id": "TODAY", "service_type": "WF", "rush_type": "RUSH"},
            "OLD": {"bag_id": "OLD", "service_type": "WF", "rush_type": "NON-RUSH"},
        }
        mock_events.return_value = {
            "TODAY": [
                {
                    "purpose": "sent-to-vendor",
                    "rack": "VeeWash Dirty",
                    "scanned_at_parsed": datetime(2026, 6, 7, 8, 0),
                },
                {
                    "purpose": "move-bag",
                    "rack": "VeeWash Clean",
                    "scanned_at_parsed": datetime(2026, 6, 7, 12, 0),
                },
            ],
            "OLD": [],
        }
        mock_facility_ids.return_value = {"TODAY"}
        mock_rfv_sync.return_value = {
            "stale": False,
            "enabled": True,
            "latest_status": "success",
            "last_refreshed_at": "2026-06-07T12:00:00",
            "last_success_at": "2026-06-07T12:00:00",
        }
        mock_dashboard.return_value = {
            "total_orders": 1,
            "wf_rush": 0,
            "wf_non_rush": 1,
            "hd_rush": 0,
            "hd_non_rush": 0,
            "unique_bag_ids": ["OLD"],
            "rush_wf_ids": [],
            "rush_hd_ids": [],
            "nonrush_wf_ids": ["OLD"],
            "nonrush_hd_ids": [],
            "unknown_ids": [],
            "rows": [],
            "staging_row_count": 1,
            "duplicate_staging_rows": 0,
        }
        mock_pending.return_value = {
            "rows": [
                {"bag_id": "OLD", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "NON-RUSH", "in_active_staging": True},
            ],
            "incoming": {"rows": [], "groups": {"combined": {}}},
            "wf_lifecycle": {"groups": {"combined": {"total": 1, "by_lifecycle_status": {}, "by_lifecycle_group": {}}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 0}}},
            "checkout_summary": {"rush": {}},
        }
        payload = build_simple_shift_performance_payload(
            MagicMock(), 1, period_start=date(2026, 6, 7), period_end=date(2026, 6, 7)
        )
        assert payload["facility_tracker_today"]["total"] == 1
        assert payload["current_active_work_now"]["total"] == 1
        overlap = payload["scope_overlap"]
        assert "TODAY" in overlap["entered_today_and_completed"]
        assert "OLD" in overlap["carryover_active_from_prior_day"]
        audit = payload["debug_audit"]
        assert audit["facility_tracker_today"]["bag_ids"] == ["TODAY"]
        assert audit["current_active_work_now"]["bag_ids"] == ["OLD"]
