"""Tests for Shift Monitor five-module layout and dual filters."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_shift_monitor_modules import (
    MOD_EX_WASHER,
    MOD_FACILITY_PENDING,
    MOD_FACILITY_TOTAL,
    MOD_MON_WEIGHT,
    MOD_PROD_HD_NOT_STARTED,
    MOD_PROD_NOT_WEIGHED,
    MOD_PROD_PENDING,
    apply_module_tags,
    build_shift_monitor_modules,
    filter_cards_for_scope,
    filter_module_records,
)


def _rec(
    bid: str,
    *,
    svc: str = "WF",
    rush: str = "RUSH",
    tags: list[str] | None = None,
    weight_flagged: bool = False,
) -> dict:
    rush_bucket = "rush_wf" if rush == "RUSH" and svc == "WF" else "nonrush_hd"
    return {
        "bag_id": bid,
        "customer": f"Cust {bid}",
        "service_type": svc,
        "rush_label": "Rush" if rush == "RUSH" else "Non-Rush",
        "rush_bucket": rush_bucket,
        "completed": False,
        "drilldown_tags": list(tags or []),
        "weight_difference": {"flagged": weight_flagged},
    }


class TestModuleFilters:
    def test_rush_wf_combined_filter(self):
        records = [
            {**_rec("RWF", svc="WF", rush="RUSH", tags=["cfs_total", "cfs_in_progress"]), "service_bucket": "WF", "rush_bucket": "RUSH", "module_tags": [MOD_FACILITY_TOTAL, MOD_FACILITY_PENDING]},
            {**_rec("NWF", svc="WF", rush="NON_RUSH", tags=["cfs_total"]), "service_bucket": "WF", "rush_bucket": "NON_RUSH", "module_tags": [MOD_FACILITY_TOTAL]},
            {**_rec("RHD", svc="HD", rush="RUSH", tags=["cfs_total"]), "service_bucket": "HD", "rush_bucket": "RUSH", "module_tags": [MOD_FACILITY_TOTAL]},
        ]
        out = filter_module_records(records, module_tag=MOD_FACILITY_TOTAL, rush_filter="rush", service_filter="wf")
        assert [r["bag_id"] for r in out] == ["RWF"]

    def test_non_rush_hd_combined_filter(self):
        records = [
            {**_rec("NHD", svc="HD", rush="NON_RUSH", tags=["cfs_total", "cfs_in_progress"]), "service_bucket": "HD", "rush_bucket": "NON_RUSH", "module_tags": [MOD_FACILITY_TOTAL, MOD_FACILITY_PENDING, MOD_PROD_HD_NOT_STARTED]},
            {**_rec("RHD", svc="HD", rush="RUSH", tags=["cfs_total"]), "service_bucket": "HD", "rush_bucket": "RUSH", "module_tags": [MOD_FACILITY_TOTAL]},
        ]
        out = filter_module_records(records, module_tag=MOD_FACILITY_PENDING, rush_filter="non_rush", service_filter="hd")
        assert [r["bag_id"] for r in out] == ["NHD"]

    def test_hd_excluded_from_weighing_stages(self):
        records = [
            {**_rec("HD1", svc="HD", tags=["cfs_in_progress", "hd_not_started"]), "service_bucket": "HD", "rush_bucket": "NON_RUSH", "module_tags": [MOD_PROD_HD_NOT_STARTED]},
            {**_rec("WF1", svc="WF", tags=["cfs_in_progress"]), "service_bucket": "WF", "rush_bucket": "RUSH", "module_tags": [MOD_PROD_NOT_WEIGHED]},
        ]
        hd = filter_module_records(records, module_tag=MOD_PROD_NOT_WEIGHED, service_filter="hd")
        assert len(filter_module_records(records, module_tag=MOD_PROD_NOT_WEIGHED, service_filter="wf")) == 1
        assert hd == []

    def test_drilldown_row_count_equals_visible_count(self):
        records = [
            {**_rec("A", svc="WF", rush="RUSH", tags=["cfs_total", "cfs_in_progress"]), "service_bucket": "WF", "rush_bucket": "RUSH", "module_tags": [MOD_FACILITY_TOTAL, MOD_FACILITY_PENDING, MOD_PROD_PENDING]},
            {**_rec("B", svc="WF", rush="RUSH", tags=["cfs_total", "cfs_in_progress"]), "service_bucket": "WF", "rush_bucket": "RUSH", "module_tags": [MOD_FACILITY_TOTAL, MOD_FACILITY_PENDING, MOD_PROD_PENDING]},
        ]
        visible = len(filter_module_records(records, module_tag=MOD_FACILITY_PENDING, rush_filter="rush", service_filter="wf"))
        assert visible == 2


class TestApplyModuleTags:
    def test_wf_not_weighed_tag(self):
        rec = _rec("WF1", svc="WF", tags=["cfs_in_progress"])
        apply_module_tags([rec], events_by_bag={"WF1": []})
        assert MOD_PROD_NOT_WEIGHED in rec["module_tags"]
        assert rec["service_bucket"] == "WF"

    def test_hd_not_in_weighing(self):
        rec = _rec("HD1", svc="HD", tags=["cfs_in_progress", "hd_not_started"])
        apply_module_tags([rec], events_by_bag={"HD1": []})
        assert MOD_PROD_NOT_WEIGHED not in rec["module_tags"]
        assert MOD_PROD_HD_NOT_STARTED in rec["module_tags"]

    def test_weight_discrepancy_tag(self):
        rec = _rec("WF1", svc="WF", tags=["cfs_in_progress"], weight_flagged=True)
        apply_module_tags([rec], events_by_bag={"WF1": [{"purpose": "weight-entry"}]})
        assert MOD_MON_WEIGHT in rec["module_tags"]

    def test_exception_washer_missing(self):
        rec = _rec("WF1", svc="WF", tags=["cfs_in_progress"])
        events = [{"purpose": "weight-entry", "scanned_at_parsed": datetime(2026, 6, 10, 9)}]
        apply_module_tags([rec], events_by_bag={"WF1": events})
        assert MOD_EX_WASHER in rec["module_tags"]


class TestPortalSnapshot:
    def test_summary_only_mode(self):
        modules = build_shift_monitor_modules(
            [],
            events_by_bag={},
            period_start=date(2026, 6, 10),
            period_end=date(2026, 6, 10),
            period_start_dt=datetime(2026, 6, 10),
            period_end_exclusive=datetime(2026, 6, 11),
            portal_list_available=False,
            portal_counts=None,
            last_rush_wash=None,
            last_nonrush_wash=None,
            last_wash_overall=None,
            today_et=date(2026, 6, 10),
        )
        portal = modules["portal_snapshot"]
        assert portal["mode"] == "summary_only"
        assert portal["filters_enabled"] is False
        assert portal["summary"]["at_veewash"] == 48
        assert portal["summary"]["pending_processing"] == 26
        assert portal["summary"]["processed"] == 22
        assert portal["summary"]["due_today"] == 30
        assert portal["summary"]["due_today_pending"] == 25
        assert portal["summary"]["due_today_processed"] == 5
        assert len(portal["cards"]) == 6
        assert all(not c.get("clickable") for c in portal["cards"])

    def test_service_filter_hides_wf_cards(self):
        cards = [
            {"id": "a", "label": "Not Weighed", "wf_only": True},
            {"id": "b", "label": "HD Not Started", "hd_only": True},
        ]
        out = filter_cards_for_scope(cards, service_filter="hd")
        assert len(out) == 1


class TestPayloadIntegration:
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_payload_includes_shift_monitor_modules(
        self,
        mock_settings,
        mock_users,
        mock_meta,
        mock_events,
        mock_scope_b,
        mock_pending,
    ):
        from backend.tests.rinse_snapshot_test_helpers import patch_unified_loaders_from_pending
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload

        today = date(2026, 6, 10)
        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0, "facility_entry_racks": ["VeeWash Dirty"]}
        mock_users.return_value = ({}, {})
        mock_meta.return_value = {}
        mock_events.return_value = {}
        mock_scope_b.return_value = set()
        mock_pending.return_value = {
            "rows": [],
            "incoming": {"rows": []},
            "wf_lifecycle": {"groups": {"combined": {"total": 0}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 0}}},
            "checkout_summary": {"rush": {}},
        }
        with patch("backend.rinse_scheduled_scrape._today_et", return_value=today):
            with patch_unified_loaders_from_pending(mock_pending.return_value, today=today):
                payload = build_simple_shift_performance_payload(
                    MagicMock(), 1, period_start=today, period_end=today, include_debug=True
                )
        mods = payload.get("shift_monitor_modules") or {}
        assert "portal_snapshot" in mods
        assert "facility_status" in mods
        assert "production_stage" in mods
