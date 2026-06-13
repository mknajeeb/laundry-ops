"""Tests for live Shift Monitor baseline filtering."""

import pytest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_shift_monitor_baseline import (
    REASON_EXCLUDED_PRE_BASELINE,
    REASON_IN_AT_VENDOR_SCRAPE,
    filter_events_after_baseline,
    parse_baseline_start_naive_et,
)
from backend.tests.rinse_snapshot_test_helpers import patch_unified_loaders_from_pending
from backend.tests.test_rinse_simple_shift_performance import (
    T1,
    T2,
    T3,
    T4,
    _FRESH_RFV_SYNC,
    _ev,
    _make_dashboard_snapshot,
    _sv,
)


pytestmark = pytest.mark.enable_live_baseline


class TestBaselineHelpers:
    def test_parse_baseline_start_et(self):
        dt = parse_baseline_start_naive_et("2026-06-10 00:00:00")
        assert dt == datetime(2026, 6, 10, 0, 0, 0)

    def test_filter_events_after_baseline(self):
        baseline = datetime(2026, 6, 10, 8, 0, 0)
        events = [
            {"purpose": "weight-entry", "scanned_at_parsed": datetime(2026, 6, 9, 12, 0, 0)},
            {"purpose": "start-cleaning", "scanned_at_parsed": datetime(2026, 6, 10, 9, 0, 0)},
        ]
        kept = filter_events_after_baseline(events, baseline)
        assert len(kept) == 1
        assert kept[0]["purpose"] == "start-cleaning"


class TestBaselinePayload:
    @patch("backend.rinse_presence_sync_status.get_ready_for_vendor_sync_status")
    @patch("backend.rinse_dashboard_staging.get_dashboard_active_staging_snapshot")
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_registry_only_excluded_from_live_dashboard(
        self,
        mock_settings,
        mock_maps,
        mock_meta,
        mock_events,
        mock_scope_b,
        mock_pending,
        mock_dashboard,
        mock_rfv_sync,
    ):
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload

        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0}
        mock_maps.return_value = {}
        mock_scope_b.return_value = []
        mock_meta.return_value = {}
        mock_events.return_value = {"STG1": _sv(_ev("weight-entry", T1))}
        mock_rfv_sync.return_value = _FRESH_RFV_SYNC
        mock_dashboard.return_value = _make_dashboard_snapshot([
            {"bag_id": "STG1", "service_type": "WF", "effective_rush": "RUSH"},
        ])
        mock_pending.return_value = {
            "rows": [
                {
                    "bag_id": "STG1",
                    "record_scope": "wf_lifecycle",
                    "service_type": "WF",
                    "effective_rush": "RUSH",
                    "current_lifecycle_status": "PENDING_WEIGHING",
                    "in_active_staging": True,
                },
                {
                    "bag_id": "REG1",
                    "record_scope": "wf_lifecycle",
                    "service_type": "WF",
                    "effective_rush": "RUSH",
                    "registry_supplement": True,
                    "current_lifecycle_status": "PENDING_WEIGHING",
                },
            ],
            "incoming": {"rows": [], "groups": {"combined": {}}},
            "wf_lifecycle": {"groups": {"combined": {"total": 2}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 0}}},
            "checkout_summary": {"rush": {}},
        }
        with patch_unified_loaders_from_pending(mock_pending.return_value):
            payload = build_simple_shift_performance_payload(
                MagicMock(), 1, period_start=date(2026, 6, 10), period_end=date(2026, 6, 10), include_debug=True
            )
        bag_ids = {r["bag_id"] for r in payload["records"]}
        assert "STG1" in bag_ids
        assert "REG1" not in bag_ids
        assert payload["live_baseline"]["live_dashboard_record_count"] == len(payload["records"])

    @patch("backend.rinse_presence_sync_status.get_ready_for_vendor_sync_status")
    @patch("backend.rinse_dashboard_staging.get_dashboard_active_staging_snapshot")
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_wf_weighed_uses_post_baseline_weight_only(
        self,
        mock_settings,
        mock_maps,
        mock_meta,
        mock_events,
        mock_scope_b,
        mock_pending,
        mock_dashboard,
        mock_rfv_sync,
    ):
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload

        baseline = datetime(2026, 6, 10, 8, 0, 0)
        pre = datetime(2026, 6, 9, 10, 0, 0)
        post = datetime(2026, 6, 10, 9, 0, 0)
        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0}
        mock_maps.return_value = {}
        mock_scope_b.return_value = []
        mock_meta.return_value = {}
        mock_events.return_value = {
            "WF1": _sv(
                {"purpose": "weight-entry", "scanned_at_parsed": pre, "user_name": "A", "scan_index": 1},
            ),
            "WF2": _sv(
                {"purpose": "weight-entry", "scanned_at_parsed": post, "user_name": "B", "scan_index": 1},
            ),
        }
        mock_rfv_sync.return_value = _FRESH_RFV_SYNC
        mock_dashboard.return_value = _make_dashboard_snapshot([
            {"bag_id": "WF1", "service_type": "WF", "effective_rush": "RUSH"},
            {"bag_id": "WF2", "service_type": "WF", "effective_rush": "RUSH"},
        ])
        mock_pending.return_value = {
            "rows": [
                {"bag_id": "WF1", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "RUSH", "current_lifecycle_status": "WEIGHED_NOT_STARTED", "in_active_staging": True},
                {"bag_id": "WF2", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "RUSH", "current_lifecycle_status": "WEIGHED_NOT_STARTED", "in_active_staging": True},
            ],
            "incoming": {"rows": [], "groups": {"combined": {}}},
            "wf_lifecycle": {"groups": {"combined": {"total": 2}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 0}}},
            "checkout_summary": {"rush": {}},
        }
        ctx = {
            "active": True,
            "shift_monitor_baseline_start_at_et": baseline.strftime("%Y-%m-%d %H:%M:%S"),
            "baseline_source": "manual_reset",
            "baseline_note": "test",
            "timezone": "America/New_York",
            "baseline_start_naive_et": baseline,
            "at_vendor_scrape_ready": True,
            "rfv_scrape_ready": True,
            "needs_refresh": False,
        }
        with patch_unified_loaders_from_pending(mock_pending.return_value):
            with patch(
                "backend.rinse_shift_monitor_baseline.build_baseline_context",
                return_value=ctx,
            ):
                payload = build_simple_shift_performance_payload(
                    MagicMock(), 1, period_start=date(2026, 6, 10), period_end=date(2026, 6, 10), include_debug=True
                )
        wf1 = next(r for r in payload["records"] if r["bag_id"] == "WF1")
        wf2 = next(r for r in payload["records"] if r["bag_id"] == "WF2")
        assert wf1.get("wip_bucket") == "wf_not_weighed"
        assert wf2.get("wip_bucket") == "wf_weighed_not_started"
        assert wf2.get("baseline_inclusion_reason")

    @patch("backend.rinse_presence_sync_status.get_ready_for_vendor_sync_status")
    @patch("backend.rinse_dashboard_staging.get_dashboard_active_staging_snapshot")
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_baseline_inclusion_reason_on_drilldown_row(
        self,
        mock_settings,
        mock_maps,
        mock_meta,
        mock_events,
        mock_scope_b,
        mock_pending,
        mock_dashboard,
        mock_rfv_sync,
    ):
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload

        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0}
        mock_maps.return_value = {}
        mock_scope_b.return_value = []
        mock_meta.return_value = {}
        mock_events.return_value = {"STG1": _sv(_ev("weight-entry", T1))}
        mock_rfv_sync.return_value = _FRESH_RFV_SYNC
        mock_dashboard.return_value = _make_dashboard_snapshot([
            {"bag_id": "STG1", "service_type": "WF", "effective_rush": "RUSH"},
        ])
        mock_pending.return_value = {
            "rows": [
                {"bag_id": "STG1", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "RUSH", "current_lifecycle_status": "PENDING_WEIGHING", "in_active_staging": True},
            ],
            "incoming": {"rows": [], "groups": {"combined": {}}},
            "wf_lifecycle": {"groups": {"combined": {"total": 1}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 0}}},
            "checkout_summary": {"rush": {}},
        }
        with patch_unified_loaders_from_pending(mock_pending.return_value):
            payload = build_simple_shift_performance_payload(
                MagicMock(), 1, period_start=date(2026, 6, 10), period_end=date(2026, 6, 10), include_debug=True
            )
        row = next(r for r in payload["records"] if r["bag_id"] == "STG1")
        assert row.get("baseline_inclusion_reason")
        assert row.get("source_seen_in") is not None
        assert "live_baseline" in payload
        assert payload["live_baseline"]["banner_title"]


class TestCleanVeeWashBaselineAnchor:
    def test_org3_defaults_to_clean_veewash_baseline(self):
        from unittest.mock import MagicMock, patch

        from backend.rinse_shift_monitor_baseline import (
            BASELINE_SOURCE_CLEAN_VEEWASH,
            VEEWASH_CLEAN_BASELINE_START_ET,
            get_shift_monitor_baseline,
        )

        cursor = MagicMock()
        with patch("backend.rinse_shift_monitor_baseline._get_setting", return_value=None):
            baseline = get_shift_monitor_baseline(cursor, 3)
        assert baseline["baseline_source"] == BASELINE_SOURCE_CLEAN_VEEWASH
        assert baseline["shift_monitor_baseline_start_at_et"] == VEEWASH_CLEAN_BASELINE_START_ET
        assert baseline.get("baseline_presence_run_id") is None
        assert baseline.get("baseline_source_batch_id") is None

    def test_contaminated_manual_verify_batch_rejected(self):
        from backend.rinse_shift_monitor_baseline import is_contaminated_presence_batch

        assert is_contaminated_presence_batch(
            "manual_verify-72159513726141a5b11969a2949880af"
        ) is True
        assert is_contaminated_presence_batch(
            "veewash_cleanup_rescrape-ac99501873604898a55d66a5a4710d84"
        ) is False
        assert is_contaminated_presence_batch(
            "manual_verify-5b3022f1d86843499033e35eb11169de"
        ) is False

    def test_latest_clean_presence_scrape_skips_contaminated(self):
        from unittest.mock import MagicMock, patch

        from backend.rinse_shift_monitor_baseline import latest_clean_at_vendor_presence_scrape

        cursor = MagicMock()
        contaminated = {
            "id": 99,
            "source_batch_id": "manual_verify-72159513726141a5b11969a2949880af",
            "status": "success",
            "finished_at": datetime(2026, 6, 12, 10, 0, 0),
        }
        older_clean = {
            "id": 6,
            "source_batch_id": "veewash_cleanup_rescrape-ac99501873604898a55d66a5a4710d84",
            "status": "success",
            "finished_at": datetime(2026, 6, 11, 20, 38, 25),
        }
        newer_clean = {
            "id": 8,
            "source_batch_id": "manual-abc123",
            "status": "success",
            "finished_at": datetime(2026, 6, 12, 9, 0, 0),
        }
        with patch(
            "backend.rinse_shift_monitor_baseline.table_exists",
            return_value=True,
        ), patch.object(
            cursor, "fetchall", return_value=[contaminated, newer_clean, older_clean]
        ):
            row = latest_clean_at_vendor_presence_scrape(cursor, 3)
        assert row is not None
        assert row["id"] == 8
        assert row["source_batch_id"] == "manual-abc123"

    def test_build_baseline_context_exposes_clean_anchor_fields(self):
        from unittest.mock import MagicMock, patch

        from backend.rinse_shift_monitor_baseline import (
            BASELINE_SOURCE_CLEAN_VEEWASH,
            build_baseline_context,
            veewash_clean_baseline_defaults,
        )

        cursor = MagicMock()
        baseline = {
            **veewash_clean_baseline_defaults(),
            "active": True,
            "baseline_org": 3,
            "baseline_time_et": "2026-06-11 20:38:25",
            "timezone": "America/New_York",
        }
        clean_run = {
            "id": 8,
            "source_batch_id": "manual-abc123",
            "status": "success",
            "finished_at": datetime(2026, 6, 12, 9, 0, 0),
        }
        with patch(
            "backend.rinse_shift_monitor_baseline.latest_clean_at_vendor_presence_scrape",
            return_value=clean_run,
        ), patch(
            "backend.rinse_shift_monitor_baseline.latest_clean_rfv_presence_scrape",
            return_value=None,
        ), patch(
            "backend.rinse_shift_monitor_baseline.latest_at_vendor_scrape_after_baseline",
            return_value=None,
        ), patch(
            "backend.rinse_vendor_config.resolve_rinse_vendor",
            return_value="veewash",
        ):
            ctx = build_baseline_context(cursor, 3, baseline)
        assert ctx["baseline_source"] == BASELINE_SOURCE_CLEAN_VEEWASH
        assert ctx["baseline_time_et"] == "2026-06-11 16:38:25"
        assert ctx["baseline_org"] == 3
        assert ctx["baseline_vendor"] == "veewash"
        assert ctx["baseline_presence_run_id"] == 8
        assert ctx["baseline_source_batch_id"] == "manual-abc123"
        assert ctx["latest_at_vendor_presence_source_batch_id"] == "manual-abc123"
        assert ctx["latest_clean_at_vendor_presence_scrape_et"] is not None
        assert ctx["latest_at_vendor_presence_scrape_run_id"] == 8
        assert ctx["at_vendor_scrape_ready"] is True
