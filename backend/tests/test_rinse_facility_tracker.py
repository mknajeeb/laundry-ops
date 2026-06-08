"""Tests for Facility Tracker management monitoring (Entered / Carryover / Total)."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_bag_activity_rules import evaluate_bag_completion_v2
from backend.rinse_facility_tracker import (
    apply_facility_management_drilldown_tags,
    build_facility_management_tracker,
    classify_facility_bag_status,
    load_carryover_bag_ids,
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


class TestFirstFacilityEntryDates:
    def test_uses_grouped_sql_with_rack_filter(self):
        from backend.rinse_facility_tracker import load_first_facility_entry_dates

        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {"bag_id": "OLD1", "first_scan": datetime(2026, 6, 1, 10, 0, 0)},
        ]
        with patch("backend.rinse_facility_tracker.table_exists", return_value=True):
            out = load_first_facility_entry_dates(
                cursor,
                3,
                entry_racks=["VeeWash Dirty"],
                through_date=date(2026, 6, 8),
            )
        assert out.get("OLD1") == date(2026, 6, 1)
        sql = cursor.execute.call_args[0][0]
        assert "MIN(scanned_at_parsed)" in sql
        assert "GROUP BY bag_id" in sql
        assert "scanned_at_parsed >=" in sql


class TestFacilityStatus:
    def test_pending_vs_left_sent(self):
        pending_rec = {"bag_id": "P1", "completed": False}
        assert classify_facility_bag_status(pending_rec, {}, [], evaluate_bag_completion_v2([])) == "pending"

        sent_rec = {"bag_id": "S1", "completed": True}
        pending = {"current_lifecycle_status": "SENT_TO_RINSE"}
        assert classify_facility_bag_status(sent_rec, pending, [], evaluate_bag_completion_v2([])) == "left_sent"

    def test_completed_still_at_facility(self):
        events = [
            {
                "purpose": "move-bag",
                "rack": "VeeWash Clean",
                "scanned_at_parsed": datetime(2026, 6, 7, 12, 0),
            }
        ]
        rec = {"bag_id": "C1", "completed": True}
        assert classify_facility_bag_status(rec, {}, events, evaluate_bag_completion_v2(events)) == "still_at_facility"


class TestCarryoverLogic:
    def test_carryover_excludes_entered_today(self):
        first = {"OLD": date(2026, 6, 6), "NEW": date(2026, 6, 7)}
        records = {
            "OLD": {"bag_id": "OLD", "completed": False},
            "NEW": {"bag_id": "NEW", "completed": False},
        }
        carry = load_carryover_bag_ids(
            first,
            target_date=date(2026, 6, 7),
            records_by_bag=records,
            pending_by_bag={"OLD": {"in_active_staging": True}, "NEW": {"in_active_staging": True}},
            events_by_bag={"OLD": [], "NEW": []},
            completions_by_bag={"OLD": evaluate_bag_completion_v2([]), "NEW": evaluate_bag_completion_v2([])},
        )
        assert carry == {"OLD"}


class TestManagementTracker:
    @patch("backend.rinse_facility_tracker.load_carryover_bag_ids")
    @patch("backend.rinse_facility_tracker.load_facility_entry_bag_ids")
    @patch("backend.rinse_facility_tracker.load_first_facility_entry_dates")
    def test_total_equals_entered_plus_carryover(self, mock_first, mock_entered, mock_carryover):
        mock_entered.return_value = {"T1"}
        mock_first.return_value = {"T1": date(2026, 6, 7), "O1": date(2026, 6, 6)}
        mock_carryover.return_value = {"O1"}
        cursor = MagicMock()
        tracker = build_facility_management_tracker(
            cursor,
            1,
            target_date=date(2026, 6, 7),
            entry_racks=["VeeWash Dirty"],
            meta_by_bag={
                "T1": {"bag_id": "T1", "service_type": "WF", "rush_type": "RUSH"},
                "O1": {"bag_id": "O1", "service_type": "WF", "rush_type": "NON-RUSH"},
            },
            records_by_bag={
                "T1": {"bag_id": "T1", "completed": False},
                "O1": {"bag_id": "O1", "completed": True},
            },
            pending_by_bag={},
            events_by_bag={"T1": [], "O1": []},
            completions_by_bag={
                "T1": evaluate_bag_completion_v2([]),
                "O1": evaluate_bag_completion_v2([
                    {"purpose": "move-bag", "rack": "Clean", "scanned_at_parsed": datetime(2026, 6, 7, 10)}
                ]),
            },
        )
        assert tracker["entered_today"]["total"] == 1
        assert tracker["carryover"]["total"] == 1
        assert tracker["total_workload"]["total"] == 2
        assert tracker["reconciliation"]["total_equals_entered_plus_carryover"] is True
        assert tracker["entered_today"]["status"]["pending"] == 1
        assert tracker["carryover"]["status"]["completed"] == 1

    def test_drilldown_tags_match_section(self):
        tracker = {
            "entered_today": {"bag_ids": ["A1"], "drilldown_prefix": "ft_entered"},
            "carryover": {"bag_ids": [], "drilldown_prefix": "ft_carryover"},
            "total_workload": {"bag_ids": ["A1"], "drilldown_prefix": "ft_total"},
        }
        records = [{"bag_id": "A1", "completed": False, "rush_bucket": "rush_wf", "drilldown_tags": []}]
        apply_facility_management_drilldown_tags(
            records,
            tracker,
            pending_by_bag={},
            events_by_bag={"A1": []},
            completions_by_bag={"A1": evaluate_bag_completion_v2([])},
            first_entry_dates={"A1": date(2026, 6, 7)},
        )
        tags = set(records[0]["drilldown_tags"])
        assert "ft_entered" in tags
        assert "ft_entered_pending" in tags
        assert "ft_total" in tags
        assert records[0]["facility_entered_date"] == "2026-06-07"


class TestPayloadFacilityTracker:
    @patch("backend.rinse_facility_tracker.load_facility_entry_bag_ids")
    @patch("backend.rinse_facility_tracker.load_first_facility_entry_dates")
    @patch("backend.rinse_presence_sync_status.get_ready_for_vendor_sync_status")
    @patch("backend.rinse_dashboard_staging.get_dashboard_active_staging_snapshot")
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_management_sections_in_payload(
        self,
        mock_settings,
        mock_maps,
        mock_meta,
        mock_events,
        mock_scope_b,
        mock_pending,
        mock_dashboard,
        mock_rfv_sync,
        mock_first_entry,
        mock_facility_ids,
    ):
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload

        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0, "facility_entry_racks": ["VeeWash Dirty"]}
        mock_maps.return_value = {}
        mock_scope_b.return_value = []
        mock_meta.return_value = {
            "TODAY": {"bag_id": "TODAY", "service_type": "WF", "rush_type": "RUSH"},
            "OLD": {"bag_id": "OLD", "service_type": "WF", "rush_type": "NON-RUSH"},
        }
        mock_events.return_value = {"TODAY": [], "OLD": []}
        mock_first_entry.return_value = {"TODAY": date(2026, 6, 7), "OLD": date(2026, 6, 6)}
        mock_facility_ids.return_value = {"TODAY"}
        mock_rfv_sync.return_value = {"stale": False, "enabled": True, "latest_status": "success"}
        mock_dashboard.return_value = {
            "total_orders": 1,
            "wf_non_rush": 1,
            "unique_bag_ids": ["OLD"],
            "nonrush_wf_ids": ["OLD"],
            "rush_wf_ids": [],
            "rush_hd_ids": [],
            "nonrush_hd_ids": [],
            "unknown_ids": [],
            "rows": [],
            "staging_row_count": 1,
            "duplicate_staging_rows": 0,
        }
        mock_pending.return_value = {
            "rows": [
                {"bag_id": "OLD", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "NON-RUSH", "current_lifecycle_status": "IN_WASHING", "in_active_staging": True},
            ],
            "incoming": {"rows": [], "groups": {"combined": {}}},
            "wf_lifecycle": {"groups": {"combined": {"total": 1, "by_lifecycle_status": {}, "by_lifecycle_group": {}}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 0}}},
            "checkout_summary": {"rush": {}},
        }
        payload = build_simple_shift_performance_payload(
            MagicMock(), 1, period_start=date(2026, 6, 7), period_end=date(2026, 6, 7)
        )
        ft = payload["facility_tracker_today"]
        assert ft["entered_today"]["total"] == 1
        assert ft["reconciliation"]["total_equals_entered_plus_carryover"] is True
        today_rec = next(r for r in payload["records"] if r["bag_id"] == "TODAY")
        assert "ft_entered" in (today_rec.get("drilldown_tags") or [])
