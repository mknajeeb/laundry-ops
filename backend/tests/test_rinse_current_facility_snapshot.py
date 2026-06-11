"""Tests for Current Facility Snapshot / Vendor Home reconciliation."""

from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import MagicMock, patch

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


class TestCurrentFacilitySnapshotLogic:
    def test_wf_weighed_not_started_reason(self):
        from backend.rinse_current_facility_snapshot import wf_in_progress_bucket_and_reason

        tag, reason = wf_in_progress_bucket_and_reason(
            has_weigh=True,
            has_start_cleaning=False,
            has_drying=False,
            pending_folding=False,
        )
        assert tag == "wf_weighed_not_started"
        assert "start-cleaning is missing" in reason

    def test_hd_not_started_reason(self):
        from backend.rinse_current_facility_snapshot import hd_in_progress_bucket_and_reason

        tag, reason = hd_in_progress_bucket_and_reason(hd_production={"hd_started": False})
        assert tag == "hd_not_started"
        assert "no workitem" in reason.lower()

    def test_at_facility_identity(self):
        from backend.rinse_current_facility_snapshot import build_vendor_home_reconciliation

        recon = build_vendor_home_reconciliation(
            at_facility=59,
            in_progress=42,
            completed_still=17,
            rinse_home_at_veewash=59,
            rinse_home_yet_to_process=42,
        )
        assert recon["identity_ok"] is True
        assert recon["ok"] is True
        assert recon["difference_at_facility"] == 0
        assert recon["difference_in_progress"] == 0

    def test_due_today_identity(self):
        from backend.rinse_current_facility_snapshot import build_due_today_reconciliation

        recon = build_due_today_reconciliation(
            due_today_total=49,
            yet_to_process=34,
            completed_processed=15,
            rinse_due_today_total=49,
            rinse_due_today_yet_to_process=34,
        )
        assert recon["identity_ok"] is True
        assert recon["ok"] is True
        assert recon["difference_due_today"] == 0
        assert recon["difference_due_today_pending"] == 0

    def test_sent_left_excluded_from_at_facility_total(self):
        from backend.rinse_current_facility_snapshot import classify_current_facility_bag, CFS_SENT_LEFT

        assert classify_current_facility_bag(
            in_active_staging=True,
            sent_left=True,
            operationally_complete=False,
        ) == CFS_SENT_LEFT

    def test_load_out_counts_as_sent_left_even_when_staging_active(self):
        from backend.rinse_bag_activity_rules import evaluate_bag_completion_v2
        from backend.rinse_current_facility_snapshot import (
            bag_is_operationally_complete,
            bag_is_sent_left_from_facility,
            scan_events_indicate_sent_left,
        )

        events = [
            _ev("weight-entry", T1),
            _ev("start-cleaning", T2),
            _ev("load-out", T3),
        ]
        completion = evaluate_bag_completion_v2(events)
        pending = {"in_active_staging": True, "current_lifecycle_status": "FOLDED_COMPLETED"}
        assert scan_events_indicate_sent_left(events) is True
        assert bag_is_sent_left_from_facility(
            pending,
            completion,
            {},
            events,
            completion_events=events,
        ) is True

    def test_full_event_history_completes_when_post_baseline_weight_missing(self):
        from backend.rinse_bag_activity_rules import evaluate_bag_completion_v2
        from backend.rinse_current_facility_snapshot import bag_is_operationally_complete
        from backend.rinse_shift_monitor_baseline import filter_events_after_baseline

        baseline = datetime(2026, 6, 10, 0, 0, 0)
        full = _sv(
            _ev("weight-entry", datetime(2026, 6, 9, 9, 46)),
            _ev("weight-entry", datetime(2026, 6, 9, 10, 0)),
            _ev("start-cleaning", datetime(2026, 6, 10, 10, 15)),
            _ev("complete-cleaning", datetime(2026, 6, 10, 15, 25), rack="Folding-5-VW"),
        )
        filtered = filter_events_after_baseline(full, baseline)
        completion_filtered = evaluate_bag_completion_v2(filtered)
        completion_full = evaluate_bag_completion_v2(full)
        assert completion_filtered.completed is False
        assert completion_full.completed is True
        assert bag_is_operationally_complete(
            service_type="WF",
            completion=completion_filtered,
            events=filtered,
            pending_row={"current_lifecycle_status": "FOLDED_COMPLETED", "in_active_staging": True},
            meta={},
            completion_events=full,
        ) is True

    def test_folded_completed_lifecycle_fallback_when_no_scan_completion(self):
        from backend.rinse_bag_activity_rules import BagCompletionResult
        from backend.rinse_current_facility_snapshot import bag_is_operationally_complete

        completion = BagCompletionResult(
            completed=False,
            via_clean_rack=False,
            completion_at=None,
            completion_user=None,
            completion_kind=None,
            exception_code=None,
            needs_review=False,
        )
        assert bag_is_operationally_complete(
            service_type="WF",
            completion=completion,
            events=[],
            pending_row={"current_lifecycle_status": "FOLDED_COMPLETED", "in_active_staging": True},
            meta={},
            completion_events=[],
            record={"current_stage": "FOLDED_COMPLETED"},
        ) is True


class TestCurrentFacilitySnapshotPayload:
    @patch("backend.rinse_presence_sync_status.get_ready_for_vendor_sync_status")
    @patch("backend.rinse_dashboard_staging.get_dashboard_active_staging_snapshot")
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_snapshot_reconciles_in_progress_plus_completed(
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
        from datetime import date
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload, _count_tag

        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0}
        mock_maps.return_value = {}
        mock_scope_b.return_value = []
        mock_meta.return_value = {}
        mock_events.return_value = {
            "IP1": _sv(_ev("weight-entry", T1)),
            "IP2": _sv(_ev("weight-entry", T1)),
            "DONE1": _sv(
                _ev("weight-entry", T1),
                _ev("start-cleaning", T2),
                _ev("drying", T3),
                _ev("move-bag", T4, rack="VeeWash Clean"),
            ),
            "SENT1": _sv(_ev("weight-entry", T1)),
        }
        mock_rfv_sync.return_value = _FRESH_RFV_SYNC
        dashboard = _make_dashboard_snapshot([
            {"bag_id": "IP1", "service_type": "WF", "effective_rush": "RUSH"},
            {"bag_id": "IP2", "service_type": "HD", "effective_rush": "NON-RUSH"},
            {"bag_id": "DONE1", "service_type": "WF", "effective_rush": "RUSH"},
            {"bag_id": "SENT1", "service_type": "WF", "effective_rush": "RUSH"},
        ])
        mock_dashboard.return_value = dashboard
        mock_pending.return_value = {
            "rows": [
                {"bag_id": "IP1", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "RUSH", "current_lifecycle_status": "PENDING_WEIGHING", "in_active_staging": True},
                {"bag_id": "IP2", "record_scope": "hd_lifecycle", "service_type": "HD", "effective_rush": "NON-RUSH", "current_lifecycle_status": "HD_NOT_STARTED", "at_vendor_presence": True, "in_active_staging": True},
                {"bag_id": "DONE1", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "RUSH", "current_lifecycle_status": "FOLDED_COMPLETED", "in_active_staging": True},
                {"bag_id": "SENT1", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "RUSH", "current_lifecycle_status": "SENT_TO_RINSE", "in_active_staging": True},
            ],
            "incoming": {"rows": [], "groups": {"combined": {}}},
            "wf_lifecycle": {"groups": {"combined": {"total": 3}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 1}}},
            "checkout_summary": {"rush": {}},
        }
        with patch_unified_loaders_from_pending(mock_pending.return_value):
            payload = build_simple_shift_performance_payload(
                MagicMock(), 1, period_start=date(2026, 6, 9), period_end=date(2026, 6, 9), include_debug=True
            )
        cfs = payload["current_facility_snapshot"]
        records = payload["records"]
        assert cfs["at_facility_total"] == cfs["in_progress"] + cfs["completed_still_at_facility"]
        assert cfs["at_facility_total"] == 3
        assert cfs["in_progress"] == 2
        assert cfs["completed_still_at_facility"] == 1
        assert _count_tag(records, "cfs_sent_left") == 1
        assert _count_tag(records, "cfs_total") == 3
        assert "SENT1" not in (payload["debug_audit"]["current_facility_snapshot"]["cfs_total_ids"])
        for card in cfs["cards"] + cfs["breakdown_cards"]:
            if card.get("drilldown_tag"):
                assert card["count"] == card["records_count"]
                assert card["clickable"] is True
        assert payload["wip"]["scope"] == "cfs_in_progress"
        assert payload["wip"]["summary"]["total"] == 2

    @patch("backend.rinse_presence_sync_status.get_ready_for_vendor_sync_status")
    @patch("backend.rinse_dashboard_staging.get_dashboard_active_staging_snapshot")
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_wip_bucket_reason_on_records(
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
        from datetime import date
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload

        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0}
        mock_maps.return_value = {}
        mock_scope_b.return_value = []
        mock_meta.return_value = {}
        mock_events.return_value = {
            "WF_WEIGHED": _sv(_ev("weight-entry", T1)),
            "HD_NEW": _sv(),
        }
        mock_rfv_sync.return_value = _FRESH_RFV_SYNC
        mock_dashboard.return_value = _make_dashboard_snapshot([
            {"bag_id": "WF_WEIGHED", "service_type": "WF", "effective_rush": "NON-RUSH"},
            {"bag_id": "HD_NEW", "service_type": "HD", "effective_rush": "RUSH"},
        ])
        mock_pending.return_value = {
            "rows": [
                {"bag_id": "WF_WEIGHED", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "NON-RUSH", "current_lifecycle_status": "WEIGHED_NOT_STARTED", "in_active_staging": True},
                {"bag_id": "HD_NEW", "record_scope": "hd_lifecycle", "service_type": "HD", "effective_rush": "RUSH", "current_lifecycle_status": "HD_NOT_STARTED", "at_vendor_presence": True, "in_active_staging": True},
            ],
            "incoming": {"rows": [], "groups": {"combined": {}}},
            "wf_lifecycle": {"groups": {"combined": {"total": 1}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 1}}},
            "checkout_summary": {"rush": {}},
        }
        with patch_unified_loaders_from_pending(mock_pending.return_value):
            payload = build_simple_shift_performance_payload(
                MagicMock(), 1, period_start=date(2026, 6, 9), period_end=date(2026, 6, 9), include_debug=True
            )
        wf = next(r for r in payload["records"] if r["bag_id"] == "WF_WEIGHED")
        hd = next(r for r in payload["records"] if r["bag_id"] == "HD_NEW")
        assert wf["wip_bucket"] == "wf_weighed_not_started"
        assert "start-cleaning is missing" in wf["wip_bucket_reason"]
        assert hd["wip_bucket"] == "hd_not_started"
        assert "workitem" in hd["wip_bucket_reason"].lower()
        audit = payload["debug_audit"]
        assert "vendor_home_debug" in audit
        assert "WF_WEIGHED" in audit["current_facility_snapshot"]["wf_weighed_not_started_ids"]
        assert "HD_NEW" in audit["current_facility_snapshot"]["hd_not_started_ids"]

    @patch("backend.rinse_presence_sync_status.get_ready_for_vendor_sync_status")
    @patch("backend.rinse_dashboard_staging.get_dashboard_active_staging_snapshot")
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_due_today_snapshot_cards_and_identity(
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
        from datetime import date
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload, _count_tag

        today = date(2026, 6, 10)
        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0}
        mock_maps.return_value = {}
        mock_scope_b.return_value = []
        mock_meta.return_value = {}
        mock_events.return_value = {
            "DT1": _sv(_ev("weight-entry", T1)),
            "DT2": _sv(
                _ev("weight-entry", T1),
                _ev("start-cleaning", T2),
                _ev("drying", T3),
                _ev("move-bag", T4, rack="VeeWash Clean"),
            ),
        }
        mock_rfv_sync.return_value = _FRESH_RFV_SYNC
        mock_dashboard.return_value = _make_dashboard_snapshot([
            {"bag_id": "DT1", "service_type": "WF", "effective_rush": "RUSH"},
            {"bag_id": "DT2", "service_type": "WF", "effective_rush": "NON-RUSH"},
        ])
        mock_pending.return_value = {
            "rows": [
                {"bag_id": "DT1", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "RUSH", "date_clean": today, "current_lifecycle_status": "PENDING_WEIGHING", "in_active_staging": True},
                {"bag_id": "DT2", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "NON-RUSH", "date_clean": today, "current_lifecycle_status": "FOLDED_COMPLETED", "in_active_staging": True},
            ],
            "incoming": {"rows": [], "groups": {"combined": {}}},
            "wf_lifecycle": {"groups": {"combined": {"total": 2}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 0}}},
            "checkout_summary": {"rush": {}},
        }
        with patch("backend.rinse_scheduled_scrape._today_et", return_value=today):
            with patch_unified_loaders_from_pending(mock_pending.return_value, today=today):
                payload = build_simple_shift_performance_payload(
                    MagicMock(), 1, period_start=today, period_end=today, include_debug=True
                )
        dts = payload["due_today_snapshot"]
        assert dts["due_today_total"] == dts["due_today_yet_to_process"] + dts["due_today_completed_processed"]
        assert dts["due_today_total"] == 2
        assert dts["due_today_yet_to_process"] == 1
        assert dts["due_today_completed_processed"] == 1
        for card in dts["cards"] + dts["breakdown_cards"] + (dts.get("wip") or {}).get("cards", []):
            if card.get("drilldown_tag"):
                assert card["count"] == card["records_count"]
        assert payload["wip"]["scope"] == "cfs_in_progress"
        assert _count_tag(payload["records"], "dts_total") == 2

    @patch("backend.rinse_presence_sync_status.get_ready_for_vendor_sync_status")
    @patch("backend.rinse_dashboard_staging.get_dashboard_active_staging_snapshot")
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_wip_uses_cfs_in_progress_not_pipeline_work(
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
        from datetime import date
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload

        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0}
        mock_maps.return_value = {}
        mock_scope_b.return_value = ["PIPE1"]
        mock_meta.return_value = {}
        mock_events.return_value = {"STG1": _sv(), "PIPE1": _sv(_ev("weight-entry", T1))}
        mock_rfv_sync.return_value = _FRESH_RFV_SYNC
        mock_dashboard.return_value = _make_dashboard_snapshot([
            {"bag_id": "STG1", "service_type": "WF", "effective_rush": "RUSH"},
        ])
        mock_pending.return_value = {
            "rows": [
                {"bag_id": "STG1", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "RUSH", "current_lifecycle_status": "PENDING_WEIGHING", "in_active_staging": True},
                {"bag_id": "PIPE1", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "RUSH", "current_lifecycle_status": "IN_WASHING", "in_active_staging": False},
            ],
            "incoming": {"rows": [], "groups": {"combined": {}}},
            "wf_lifecycle": {"groups": {"combined": {"total": 2}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 0}}},
            "checkout_summary": {"rush": {}},
        }
        with patch_unified_loaders_from_pending(mock_pending.return_value):
            payload = build_simple_shift_performance_payload(
                MagicMock(), 1, period_start=date(2026, 6, 9), period_end=date(2026, 6, 9), include_debug=True
            )
        assert payload["wip"]["summary"]["total"] == 1
        assert payload["current_facility_snapshot"]["in_progress"] == 1
        bag_ids = {r["bag_id"] for r in payload["records"]}
        assert "PIPE1" not in bag_ids
        assert "STG1" in bag_ids


class TestUnifiedSnapshotPopulation:
    def test_merge_row_deduplicates_by_bag_id(self):
        from backend.rinse_current_facility_snapshot import _merge_row

        rows: dict[str, dict] = {}
        _merge_row(rows, {"bag_id": "ABC123", "service_type": "WF", "in_active_staging": True}, source="orders_staging")
        _merge_row(rows, {"bag_id": "ABC123", "name_clean": "Customer A", "registry_supplement": True}, source="registry")
        assert len(rows) == 1
        assert rows["ABC123"]["source_seen_in"] == ["orders_staging", "registry"]
        assert rows["ABC123"]["in_active_staging"] is True
        assert rows["ABC123"]["name_clean"] == "Customer A"

    def test_gap_analysis_lists_non_staging_and_mismatch(self):
        from backend.rinse_current_facility_snapshot import build_vendor_home_gap_analysis

        records = [
            {"bag_id": "STG1", "drilldown_tags": ["cfs_total"], "customer": "A"},
            {"bag_id": "REG1", "drilldown_tags": ["cfs_total"], "customer": "B"},
            {"bag_id": "SENT1", "drilldown_tags": ["cfs_sent_left"], "customer": "C"},
        ]
        unified_at = {
            "STG1": {"bag_id": "STG1", "source_seen_in": ["orders_staging"]},
            "REG1": {"bag_id": "REG1", "source_seen_in": ["registry"], "name_clean": "B"},
            "SENT1": {"bag_id": "SENT1", "source_seen_in": ["registry"], "name_clean": "C"},
        }
        gap = build_vendor_home_gap_analysis(
            records=records,
            unified_at_facility=unified_at,
            unified_due_today={},
            cfs_reconciliation={"dashboard_at_facility": 2, "dashboard_in_progress": 1, "at_facility_total": 2, "in_progress": 1},
            dts_reconciliation={"dashboard_due_today": 0, "due_today_total": 0},
            unified_meta={"at_vendor_presence_count": 0},
        )
        assert gap["difference_at_facility"] != 0
        assert gap["ok"] is False
        assert gap["non_staging_at_facility_count"] == 1
        assert gap["cfs_sent_left_excluded_count"] == 1
        assert any("REG1" in str(x.get("bag_id")) for x in gap["missing_or_excluded_records"])
        assert any("presence" in n.lower() or "scrape" in n.lower() for n in (gap.get("notes") or []))

    @patch("backend.rinse_presence_sync_status.get_ready_for_vendor_sync_status")
    @patch("backend.rinse_dashboard_staging.get_dashboard_active_staging_snapshot")
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    @patch("backend.rinse_current_facility_snapshot.load_unified_at_facility_population")
    @patch("backend.rinse_current_facility_snapshot.load_unified_due_today_population")
    def test_payload_merges_registry_bag_into_cfs_with_source_seen_in(
        self,
        mock_unified_due,
        mock_unified_at,
        mock_settings,
        mock_maps,
        mock_meta,
        mock_events,
        mock_scope_b,
        mock_pending,
        mock_dashboard,
        mock_rfv_sync,
    ):
        from datetime import date
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload

        today = date(2026, 6, 10)
        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0}
        mock_maps.return_value = {}
        mock_scope_b.return_value = []
        mock_meta.return_value = {}
        mock_events.return_value = {"STG1": _sv(_ev("weight-entry", T1)), "REG1": _sv()}
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
        mock_unified_at.return_value = (
            {
                "STG1": {"bag_id": "STG1", "service_type": "WF", "in_active_staging": True, "source_seen_in": ["orders_staging"]},
                "REG1": {"bag_id": "REG1", "service_type": "WF", "registry_supplement": True, "source_seen_in": ["registry"], "date_clean": today},
            },
            {"unified_total": 2, "staging_count": 1, "registry_supplement_count": 1, "at_vendor_presence_count": 0},
        )
        mock_unified_due.return_value = ({}, {"unified_due_today_total": 0})

        with patch("backend.rinse_scheduled_scrape._today_et", return_value=today):
            with patch(
                "backend.rinse_current_facility_snapshot.load_portal_vendor_home_counts",
                return_value=(None, {"at_vendor_active": 0, "rfv_active": 0, "portal_list_available": False}, [], []),
            ), patch(
                "backend.rinse_current_facility_snapshot.load_presence_edd_by_bag",
                return_value={},
            ):
                payload = build_simple_shift_performance_payload(
                    MagicMock(), 1, period_start=today, period_end=today, include_debug=True
                )

        cfs = payload["current_facility_snapshot"]
        reg = next(r for r in payload["records"] if r["bag_id"] == "REG1")
        assert "cfs_total" in (reg.get("drilldown_tags") or [])
        assert reg.get("source_seen_in") == ["registry"]
        assert (cfs.get("reconciliation") or {}).get("ok") is True
        assert (cfs.get("reconciliation") or {}).get("vendor_home_parity_ok") is False
        assert cfs.get("gap_analysis", {}).get("difference_at_facility") != 0
        assert payload["sections_under_review"]["current_facility_snapshot"] is True
        parity = payload.get("vendor_home_parity") or {}
        assert parity.get("needs_review") is True
        assert parity.get("reconciled") is False
        vh_cards = (cfs.get("vendor_home_view") or {}).get("cards") or []
        assert all(not c.get("clickable") for c in vh_cards if c.get("drilldown_tag") is None or c.get("manual_reference_only"))

    @patch("backend.rinse_presence_sync_status.get_ready_for_vendor_sync_status")
    @patch("backend.rinse_dashboard_staging.get_dashboard_active_staging_snapshot")
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    @patch("backend.rinse_current_facility_snapshot.load_unified_due_today_population")
    def test_due_today_includes_rfv_with_tags(
        self,
        mock_unified_due,
        mock_settings,
        mock_maps,
        mock_meta,
        mock_events,
        mock_scope_b,
        mock_pending,
        mock_dashboard,
        mock_rfv_sync,
    ):
        from datetime import date
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload, _count_tag

        today = date(2026, 6, 10)
        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0}
        mock_maps.return_value = {}
        mock_scope_b.return_value = []
        mock_meta.return_value = {}
        mock_events.return_value = {"RFV1": _sv()}
        mock_rfv_sync.return_value = _FRESH_RFV_SYNC
        mock_dashboard.return_value = _make_dashboard_snapshot([])
        mock_pending.return_value = {
            "rows": [],
            "incoming": {"rows": [], "groups": {"combined": {}}},
            "wf_lifecycle": {"groups": {"combined": {"total": 0}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 0}}},
            "checkout_summary": {"rush": {}},
        }
        mock_unified_due.return_value = (
            {
                "RFV1": {
                    "bag_id": "RFV1",
                    "service_type": "WF",
                    "date_clean": today,
                    "ready_for_vendor": True,
                    "source_seen_in": ["ready_for_vendor_presence"],
                },
            },
            {"unified_due_today_total": 1, "rfv_incoming_count": 1},
        )

        with patch("backend.rinse_scheduled_scrape._today_et", return_value=today):
            with patch(
                "backend.rinse_current_facility_snapshot.load_unified_at_facility_population",
                return_value=({}, {"unified_total": 0}),
            ), patch(
                "backend.rinse_current_facility_snapshot.load_portal_vendor_home_counts",
                return_value=(None, {"at_vendor_active": 0, "rfv_active": 0, "portal_list_available": False}, [], []),
            ), patch(
                "backend.rinse_current_facility_snapshot.load_presence_edd_by_bag",
                return_value={},
            ):
                payload = build_simple_shift_performance_payload(
                    MagicMock(), 1, period_start=today, period_end=today, include_debug=True
                )

        assert _count_tag(payload["records"], "dts_total") == 1
        assert _count_tag(payload["records"], "due_today_rfv_or_incoming") == 1
        assert _count_tag(payload["records"], "due_today_missing_from_staging") == 1
        rfv = next(r for r in payload["records"] if r["bag_id"] == "RFV1")
        assert "ready_for_vendor_presence" in (rfv.get("source_seen_in") or [])
        assert (payload["due_today_snapshot"].get("reconciliation") or {}).get("ok") is True
        assert (payload["due_today_snapshot"].get("reconciliation") or {}).get("vendor_home_parity_ok") is False
        parity = payload.get("vendor_home_parity") or {}
        assert parity.get("due_today_yet_to_process") == 25
        assert parity.get("internal_scan", {}).get("due_today_yet_to_process") == 1
        vh_due_cards = (payload["due_today_snapshot"].get("vendor_home_view") or {}).get("due_today_cards") or []
        assert all(not c.get("clickable") for c in vh_due_cards)


class TestVendorHomeParitySplit:
    def test_portal_yet_to_process_ignores_scan_completion(self):
        from backend.rinse_current_facility_snapshot import portal_at_vendor_yet_to_process

        complete_row = {
            "bag_id": "BAG1",
            "raw_row_json": {"steps_in_cleaning_process": "Complete — ready for pickup"},
        }
        missing_steps = {"bag_id": "BAG2", "raw_row_json": {}}
        assert portal_at_vendor_yet_to_process(complete_row) is False
        assert portal_at_vendor_yet_to_process(missing_steps) is True

    def test_manual_vendor_home_cards_not_clickable(self):
        from backend.rinse_current_facility_snapshot import build_vendor_home_view_section

        def _count(records, tag):
            return sum(1 for r in records if tag in (r.get("drilldown_tags") or []))

        section = build_vendor_home_view_section(
            portal_counts=None,
            presence_meta={"at_vendor_active": 0, "rfv_active": 0, "portal_list_available": False},
            records=[],
            record_count_fn=_count,
        )
        assert section["manual_reference_only"] is True
        assert section["at_veewash_yet_to_process"] == 26
        for card in section["cards"] + section["due_today_cards"]:
            assert card.get("clickable") is False
            assert card.get("manual_reference_only") is True
            if card["label"] in ("At VeeWash Total", "Vendor Home Yet to Process", "Due Today Total", "Vendor Home Due Today Pending"):
                assert card.get("drilldown_tag") is None

    def test_vendor_home_parity_empty_presence_needs_review(self):
        from backend.rinse_current_facility_snapshot import build_vendor_home_parity, build_vendor_home_view_section

        vh = build_vendor_home_view_section(
            portal_counts=None,
            presence_meta={"at_vendor_active": 0, "rfv_active": 0, "portal_list_available": False},
            records=[],
            record_count_fn=lambda _r, _t: 0,
        )
        parity = build_vendor_home_parity(
            vendor_home_view=vh,
            internal_scan_view={
                "at_facility_total": 57,
                "in_progress": 26,
                "completed_still_at_facility": 31,
                "due_today_total": 40,
                "due_today_yet_to_process": 4,
                "due_today_completed": 36,
            },
            presence_meta={"at_vendor_active": 0, "rfv_active": 0, "portal_list_available": False},
        )
        assert parity["reconciled"] is False
        assert parity["needs_review"] is True
        assert parity["due_today_yet_to_process"] == 25
        assert parity["internal_scan"]["due_today_yet_to_process"] == 4
        assert "presence" in parity["reason"].lower() or "portal" in parity["reason"].lower()
        assert parity["comparison"]["due_today"]["status"] == "Needs Review"

    def test_edd_backfill_priority(self):
        from backend.rinse_current_facility_snapshot import backfill_record_due_dates
        from datetime import date

        today = date(2026, 6, 10)
        records = [
            {"bag_id": "A", "due_date": None},
            {"bag_id": "B", "due_date": None},
            {"bag_id": "C", "due_date": "2026-06-01"},
        ]
        meta = {
            "A": {"date_clean": today},
            "B": {"due_date": today},
            "C": {"date_clean": today},
        }
        presence = {"D": today}
        records.append({"bag_id": "D", "due_date": None})
        stats = backfill_record_due_dates(records, meta, presence_edd_by_bag=presence)
        assert records[0]["due_date"] == today.isoformat()
        assert records[0]["due_date_source"] == "orders_staging"
        assert records[1]["due_date"] == today.isoformat()
        assert records[1]["due_date_source"] == "registry"
        assert records[3]["due_date"] == today.isoformat()
        assert records[3]["due_date_source"] == "presence"
        assert records[2]["due_date"] == "2026-06-01"
        assert stats["missing_before"] >= 3
        assert stats["missing_after"] == 0

    @patch("backend.rinse_presence_sync_status.get_ready_for_vendor_sync_status")
    @patch("backend.rinse_dashboard_staging.get_dashboard_active_staging_snapshot")
    @patch("backend.rinse_simple_shift_performance.get_pending_bag_status")
    @patch("backend.rinse_simple_shift_performance._load_bag_ids_with_et_activity")
    @patch("backend.rinse_simple_shift_performance._load_scan_events_for_bags")
    @patch("backend.rinse_simple_shift_performance._load_bag_metadata")
    @patch("backend.rinse_simple_shift_performance._load_rinse_user_maps")
    @patch("backend.rinse_simple_shift_performance.get_processing_settings")
    def test_scan_and_vendor_home_due_today_pending_differ(
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
        from datetime import date
        from backend.rinse_simple_shift_performance import build_simple_shift_performance_payload, _count_tag
        from backend.rinse_current_facility_snapshot import SCAN_DTS_YET_TO_PROCESS

        today = date(2026, 6, 10)
        mock_settings.return_value = {"weight_difference_threshold_lbs": 5.0}
        mock_maps.return_value = {}
        mock_scope_b.return_value = []
        mock_meta.return_value = {}
        mock_events.return_value = {
            "PEND": _sv(_ev("weight-entry", T1)),
            "DONE": _sv(
                _ev("weight-entry", T1),
                _ev("start-cleaning", T2),
                _ev("drying", T3),
                _ev("move-bag", T4, rack="VeeWash Clean"),
            ),
        }
        mock_rfv_sync.return_value = _FRESH_RFV_SYNC
        mock_dashboard.return_value = _make_dashboard_snapshot([
            {"bag_id": "PEND", "service_type": "WF", "effective_rush": "RUSH"},
            {"bag_id": "DONE", "service_type": "WF", "effective_rush": "NON-RUSH"},
        ])
        mock_pending.return_value = {
            "rows": [
                {"bag_id": "PEND", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "RUSH", "date_clean": today, "current_lifecycle_status": "PENDING_WEIGHING", "in_active_staging": True},
                {"bag_id": "DONE", "record_scope": "wf_lifecycle", "service_type": "WF", "effective_rush": "NON-RUSH", "date_clean": today, "current_lifecycle_status": "FOLDED_COMPLETED", "in_active_staging": True},
            ],
            "incoming": {"rows": [], "groups": {"combined": {}}},
            "wf_lifecycle": {"groups": {"combined": {"total": 2}}},
            "hd_lifecycle": {"groups": {"combined": {"total": 0}}},
            "checkout_summary": {"rush": {}},
        }
        with patch("backend.rinse_scheduled_scrape._today_et", return_value=today):
            with patch_unified_loaders_from_pending(mock_pending.return_value, today=today):
                payload = build_simple_shift_performance_payload(
                    MagicMock(), 1, period_start=today, period_end=today, include_debug=True
                )
        parity = payload["vendor_home_parity"]
        dts = payload["due_today_snapshot"]
        assert _count_tag(payload["records"], SCAN_DTS_YET_TO_PROCESS) == 1
        assert dts["due_today_yet_to_process"] == 1
        assert parity["due_today_yet_to_process"] == 25
        assert parity["internal_scan"]["due_today_yet_to_process"] == 1
        internal_cards = (dts.get("internal_scan_view") or {}).get("cards") or dts.get("cards") or []
        for card in internal_cards:
            if card.get("drilldown_tag"):
                assert card["count"] == card["records_count"]
                assert card["clickable"] is True
