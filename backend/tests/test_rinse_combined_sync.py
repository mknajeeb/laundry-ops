"""Tests for combined At Vendor + Ready for Vendor scheduled sync."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_presence_scrape import PresenceScrapeResult, ready_for_vendor_scrape_enabled
from backend.rinse_scheduled_scrape import _combine_scheduled_status
from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_AT_VENDOR, PORTAL_STATUS_READY, apply_presence_scrape


class TestCombineScheduledStatus:
    def test_both_success(self):
        assert _combine_scheduled_status("success", "success") == "success"

    def test_at_vendor_success_rfv_failed_partial(self):
        assert _combine_scheduled_status("success", "failed") == "partial_success"

    def test_at_vendor_needs_attention_rfv_failed_partial(self):
        assert _combine_scheduled_status("needs_attention", "failed") == "partial_success"

    def test_at_vendor_failed_rfv_success_partial(self):
        assert _combine_scheduled_status("failed", "success") == "partial_success"
        assert _combine_scheduled_status("skipped", "success") == "partial_success"

    def test_at_vendor_failed_overall_failed(self):
        assert _combine_scheduled_status("failed", "failed") == "failed"

    def test_rfv_disabled_uses_at_vendor_only(self):
        assert _combine_scheduled_status("success", "disabled") == "success"
        assert _combine_scheduled_status("failed", "disabled") == "failed"
        assert _combine_scheduled_status("success", None) == "success"


class TestReadyForVendorFlag:
    @patch("backend.rinse_presence_scrape.is_feature_enabled", return_value=True)
    def test_enabled(self, _mock):
        assert ready_for_vendor_scrape_enabled(MagicMock(), 3) is True

    @patch("backend.rinse_presence_scrape.is_feature_enabled", return_value=False)
    def test_disabled(self, _mock):
        assert ready_for_vendor_scrape_enabled(MagicMock(), 3) is False

    def test_veewash_org_default_enables_rfv(self):
        from backend.tenant_feature_flags import get_tenant_feature_flags

        cursor = MagicMock()
        cursor.fetchone.return_value = {"slug": "veewash"}
        with patch("backend.tenant_feature_flags.table_exists", return_value=True), patch(
            "backend.tenant_feature_flags._get_setting", return_value=None
        ):
            flags = get_tenant_feature_flags(cursor, 3)
        assert flags["enable_ready_for_vendor_scrape"] is True


class TestZeroRowsPresenceScrape:
    @patch("backend.rinse_cleaner_ticket_presence.ensure_presence_tables")
    def test_validated_zero_rows_marks_old_rows_inactive(self, _ensure):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"active_rows": 0}
        cursor.fetchall.return_value = [{"bag_id": "OLD1"}]
        stats = apply_presence_scrape(
            cursor,
            3,
            portal_status=PORTAL_STATUS_READY,
            rows=[],
            source_batch_id="test-batch",
            source_url="http://example",
            dry_run=False,
            mark_missing=True,
            run_type="manual",
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            status="success",
            scrape_meta={
                "stopped_reason": "no_table_rows",
                "empty_result_validated": True,
            },
        )
        assert stats["rows_found"] == 0
        assert stats["rows_missing"] == 1
        assert stats["active_rows"] == 0
        update_calls = [c for c in cursor.execute.call_args_list if "SET active=0" in str(c[0][0])]
        assert update_calls

    @patch("backend.rinse_presence_scrape.run_bag_export_csv")
    @patch("backend.rinse_presence_scrape.export_enabled", return_value=True)
    @patch("backend.rinse_presence_scrape.ready_for_vendor_scrape_enabled", return_value=True)
    @patch("backend.rinse_cleaner_ticket_presence.ensure_presence_tables")
    def test_unvalidated_zero_rows_preserves_active_population(
        self, _ensure, _rfv, _export, mock_scrape
    ):
        from pathlib import Path
        import tempfile

        from backend.rinse_presence_scrape import run_presence_scrape_for_org

        mock_scrape.return_value = (0, "", "")
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = [{"bag_id": "OLD1"}]

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "presence-ready_for_vendor.csv"
            csv_path.write_text("Bag ID\n", encoding="utf-8")
            meta_path = Path(str(csv_path) + ".meta.json")
            meta_path.write_text(
                '{"stopped_reason":"no_table_rows","reached_max_pages":false,"pages_scraped":1}',
                encoding="utf-8",
            )

            def _side_effect(output_path, extra_env=None, **kwargs):
                out = Path(output_path)
                out.write_text("Bag ID\n", encoding="utf-8")
                meta = Path(str(out) + ".meta.json")
                meta.write_text(meta_path.read_text(encoding="utf-8"), encoding="utf-8")
                return (0, "", "")

            mock_scrape.side_effect = _side_effect
            with patch(
                "backend.rinse_presence_scrape.rinse_scrape_env_for_organization",
                return_value=("veewash", {"RINSE_TICKETS_URL": "http://example?status=ready_for_vendor"}),
            ):
                result = run_presence_scrape_for_org(
                    conn,
                    3,
                    portal_status=PORTAL_STATUS_READY,
                    mark_missing=True,
                    dry_run=False,
                )

        assert result.status == "failed"
        assert "not validated" in (result.error_message or "").lower()
        assert result.stats.get("empty_result_validated") is False
        deactivate_calls = [
            c for c in cursor.execute.call_args_list if "SET active=0" in str(c[0][0])
        ]
        assert not deactivate_calls

    @patch("backend.rinse_bag_export_runner.run_vendor_home_summary_scrape")
    @patch("backend.rinse_presence_scrape.parse_presence_rows_from_portal_csv")
    @patch("backend.rinse_presence_scrape.run_bag_export_csv")
    @patch("backend.rinse_presence_scrape.export_enabled", return_value=True)
    @patch("backend.rinse_cleaner_ticket_presence.ensure_presence_tables")
    def test_at_vendor_supplement_persists_vendor_home_summary(
        self, _ensure, _export, mock_scrape, mock_parse, mock_supplement
    ):
        from pathlib import Path
        import tempfile

        from backend.rinse_presence_scrape import run_presence_scrape_for_org

        mock_scrape.return_value = (0, "", "")
        mock_parse.return_value = [{"bag_id": "BAG1"}]
        mock_supplement.return_value = (
            {
                "source": "vendor_home_page",
                "scraped_at": "2026-06-14T05:00:00Z",
                "orders_at_veewash": 20,
                "orders_at_veewash_yet_to_process": 10,
                "due_today": 3,
                "due_today_yet_to_process": 2,
            },
            None,
        )
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = []

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "presence-at_vendor.csv"
            csv_path.write_text("Bag ID\nBAG1\n", encoding="utf-8")
            meta_path = Path(str(csv_path) + ".meta.json")
            meta_path.write_text(
                '{"stopped_reason":"no_next_page_ui","pages_scraped":1,"row_count":1,"session_authenticated":true}',
                encoding="utf-8",
            )

            def _side_effect(output_path, extra_env=None, **kwargs):
                out = Path(output_path)
                out.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")
                meta = Path(str(out) + ".meta.json")
                meta.write_text(meta_path.read_text(encoding="utf-8"), encoding="utf-8")
                return (0, "", "")

            mock_scrape.side_effect = _side_effect
            with patch(
                "backend.rinse_presence_scrape.rinse_scrape_env_for_organization",
                return_value=("veewash", {"RINSE_TICKETS_URL": "http://example?status=at_vendor"}),
            ):
                result = run_presence_scrape_for_org(
                    conn,
                    3,
                    portal_status=PORTAL_STATUS_AT_VENDOR,
                    mark_missing=True,
                    dry_run=False,
                    run_type="scheduled",
                )

        assert result.status == "success"
        mock_supplement.assert_called_once()
        insert_calls = [
            c
            for c in cursor.execute.call_args_list
            if "INSERT INTO rinse_cleaner_ticket_presence_runs" in str(c[0][0])
        ]
        assert insert_calls
        params = insert_calls[-1][0][1]
        scrape_meta_json = params[-1]
        assert '"vendor_home_summary"' in scrape_meta_json
        assert '"orders_at_veewash": 20' in scrape_meta_json
        assert '"vendor_home_supplement"' in scrape_meta_json


class TestScheduledScrapeRunsBoth:
    @patch("backend.rinse_presence_scrape.run_presence_scrape_for_org")
    @patch("backend.rinse_scheduled_scrape._run_bash_script", return_value=0)
    @patch("backend.rinse_scheduled_scrape.count_csv_data_rows", return_value=5)
    @patch("backend.rinse_scheduled_scrape.acquire_scrape_lock", return_value=(True, ""))
    @patch("backend.rinse_scheduled_scrape.release_scrape_lock")
    @patch("backend.rinse_scheduled_scrape.finish_scrape_run")
    @patch("backend.rinse_scheduled_scrape.insert_scrape_run", return_value=99)
    @patch("backend.rinse_scheduled_scrape.resolve_rinse_vendor", return_value="veewash")
    @patch("backend.rinse_scheduled_scrape.tenant_script_dir")
    @patch("backend.rinse_scheduled_scrape.build_run_paths")
    @patch("backend.rinse_scheduled_scrape._org_slug_name", return_value=("veewash", "VeeWash"))
    def test_scheduled_combined_runs_rfv_first(
        self,
        _slug,
        mock_paths,
        mock_tenant_dir,
        _vendor,
        _ins,
        _fin,
        _rel,
        _lock,
        _count,
        _bash,
        mock_rfv,
    ):
        from pathlib import Path
        import tempfile

        from backend.rinse_scheduled_scrape import ScrapePaths, run_rinse_combined_sync_for_org

        mock_tenant_dir.return_value.is_dir.return_value = True
        run_dir = Path(tempfile.mkdtemp())
        p = ScrapePaths(
            run_dir=run_dir,
            portal_csv=run_dir / "portal.csv",
            scan_tickets_csv=run_dir / "t.csv",
            scan_events_csv=run_dir / "e.csv",
            log_path=run_dir / "log",
        )
        mock_paths.return_value = p
        p.portal_csv.write_text("h\n1\n")
        p.scan_events_csv.write_text("h\n1\n")

        call_order: list[str] = []

        def _presence_side_effect(*_args, **kwargs):
            portal = kwargs.get("portal_status") or "ready_for_vendor"
            call_order.append("rfv" if portal == "ready_for_vendor" else "av_presence")
            return PresenceScrapeResult(
                organization_id=3,
                portal_status=portal,
                status="success",
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
                stats={"rows_found": 0, "active_rows": 0, "run_id": 101 if portal == "ready_for_vendor" else 102},
            )

        mock_rfv.side_effect = _presence_side_effect

        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = {"c": 5}
        conn.cursor.return_value = cursor

        with patch("backend.rinse_portal_csv.portal_csv_to_orders_df") as pdf, patch(
            "backend.rinse_scan_events_upload.parse_scan_events_csv", return_value=(MagicMock(), [])
        ), patch("backend.rinse_combined_upload.commit_rinse_combined_upload", return_value={"batch_id": 1, "rows_inserted": 5, "portal_absence_allowed": True}), patch(
            "backend.upload_batch_confirm.confirm_upload_batch_core", return_value={"ok": True}
        ), patch("backend.rinse_scheduled_scrape._subprocess_env_for_vendor", return_value={"RINSE_MAX_PAGES": "500"}), patch(
            "backend.rinse_scheduled_scrape._count_accepted_rows", return_value=5
        ), patch("backend.rinse_scheduled_scrape._count_attention_rows", return_value=0):
            import pandas as pd

            pdf.return_value = pd.DataFrame([{"ticket_id": "ABC"}])
            result = run_rinse_combined_sync_for_org(conn, 3, run_type="scheduled")

        assert call_order == ["rfv", "av_presence"]
        assert mock_rfv.call_count == 2
        assert mock_rfv.call_args.kwargs.get("mark_missing") is True
        assert result.ready_for_vendor_status == "success"
        assert result.status == "success"
        assert result.detail.get("ready_for_vendor_sync", {}).get("rows_found") == 0
        sync_cycle = result.detail.get("sync_cycle") or {}
        assert sync_cycle.get("cycle_status") == "success"
        assert sync_cycle.get("sync_cycle_id") == 99
        assert sync_cycle.get("rfv_run_id") == 101
        assert sync_cycle.get("at_vendor_run_id") == 102
        assert sync_cycle.get("delay_seconds") == 0

    @patch("backend.rinse_presence_scrape.run_presence_scrape_for_org")
    @patch("backend.rinse_scheduled_scrape._run_bash_script", return_value=0)
    @patch("backend.rinse_scheduled_scrape.count_csv_data_rows", return_value=5)
    @patch("backend.rinse_scheduled_scrape.acquire_scrape_lock", return_value=(True, ""))
    @patch("backend.rinse_scheduled_scrape.release_scrape_lock")
    @patch("backend.rinse_scheduled_scrape.finish_scrape_run")
    @patch("backend.rinse_scheduled_scrape.insert_scrape_run", return_value=99)
    @patch("backend.rinse_scheduled_scrape.resolve_rinse_vendor", return_value="veewash")
    @patch("backend.rinse_scheduled_scrape.tenant_script_dir")
    @patch("backend.rinse_scheduled_scrape.build_run_paths")
    @patch("backend.rinse_scheduled_scrape._org_slug_name", return_value=("veewash", "VeeWash"))
    def test_partial_success_when_rfv_fails(
        self,
        _slug,
        mock_paths,
        mock_tenant_dir,
        _vendor,
        _ins,
        _fin,
        _rel,
        _lock,
        _count,
        _bash,
        mock_rfv,
    ):
        from pathlib import Path
        import tempfile

        from backend.rinse_scheduled_scrape import ScrapePaths, run_rinse_combined_sync_for_org

        mock_tenant_dir.return_value.is_dir.return_value = True
        import tempfile

        run_dir = Path(tempfile.mkdtemp())
        p = ScrapePaths(
            run_dir=run_dir,
            portal_csv=run_dir / "portal.csv",
            scan_tickets_csv=run_dir / "t.csv",
            scan_events_csv=run_dir / "e.csv",
            log_path=run_dir / "log",
        )
        mock_paths.return_value = p
        p.portal_csv.write_text("h\n1\n")
        p.scan_events_csv.write_text("h\n1\n")

        mock_rfv.return_value = PresenceScrapeResult(
            organization_id=3,
            portal_status="ready_for_vendor",
            status="failed",
            error_message="scrape timeout",
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
        )

        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = {"c": 5}
        conn.cursor.return_value = cursor

        with patch("backend.rinse_portal_csv.portal_csv_to_orders_df") as pdf, patch(
            "backend.rinse_scan_events_upload.parse_scan_events_csv", return_value=(MagicMock(), [])
        ), patch("backend.rinse_combined_upload.commit_rinse_combined_upload", return_value={"batch_id": 1, "rows_inserted": 5, "portal_absence_allowed": True}), patch(
            "backend.upload_batch_confirm.confirm_upload_batch_core", return_value={"ok": True}
        ), patch("backend.rinse_scheduled_scrape._subprocess_env_for_vendor", return_value={"RINSE_MAX_PAGES": "500"}), patch(
            "backend.rinse_scheduled_scrape._count_accepted_rows", return_value=5
        ), patch("backend.rinse_scheduled_scrape._count_attention_rows", return_value=0):
            import pandas as pd

            pdf.return_value = pd.DataFrame([{"ticket_id": "ABC"}])
            result = run_rinse_combined_sync_for_org(conn, 3, run_type="scheduled")

        assert result.at_vendor_status == "skipped"
        assert result.ready_for_vendor_status == "failed"
        assert result.status == "failed"
        assert result.detail.get("ready_for_vendor_sync", {}).get("status") == "failed"
        sync_cycle = result.detail.get("sync_cycle") or {}
        assert sync_cycle.get("cycle_status") == "RFV_FAILED"
        assert sync_cycle.get("at_vendor_ran") is False
        _bash.assert_not_called()


class TestCombinedSyncOrchestration:
    @patch("backend.rinse_scheduled_scrape.run_scheduled_scrape_for_org")
    @patch("backend.rinse_presence_scrape.run_presence_scrape_for_org")
    @patch("backend.rinse_scheduled_scrape.release_scrape_lock")
    @patch("backend.rinse_scheduled_scrape.finish_scrape_run")
    @patch("backend.rinse_scheduled_scrape.insert_scrape_run", return_value=77)
    @patch("backend.rinse_scheduled_scrape.acquire_scrape_lock", return_value=(True, ""))
    @patch("backend.rinse_scheduled_scrape.build_run_paths")
    @patch("backend.rinse_scheduled_scrape.resolve_rinse_vendor", return_value="veewash")
    @patch("backend.rinse_scheduled_scrape._org_slug_name", return_value=("veewash", "VeeWash"))
    def test_manual_and_scheduled_share_rfv_first_orchestrator(
        self,
        _slug,
        _vendor,
        mock_paths,
        _lock,
        _ins,
        _fin,
        _rel,
        mock_rfv,
        mock_av_import,
    ):
        from pathlib import Path
        import tempfile

        from backend.rinse_scheduled_scrape import ScrapePaths, ScheduledScrapeResult, run_rinse_combined_sync_for_org

        run_dir = Path(tempfile.mkdtemp())
        mock_paths.return_value = ScrapePaths(
            run_dir=run_dir,
            portal_csv=run_dir / "portal.csv",
            scan_tickets_csv=run_dir / "t.csv",
            scan_events_csv=run_dir / "e.csv",
            log_path=run_dir / "log",
        )

        call_order: list[str] = []

        def _presence(*_a, **k):
            portal = k.get("portal_status") or "ready_for_vendor"
            call_order.append("rfv" if portal == "ready_for_vendor" else "av_presence")
            return PresenceScrapeResult(
                organization_id=3,
                portal_status=portal,
                status="success",
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
                stats={"rows_found": 0, "active_rows": 0},
            )

        def _av_import(*_a, **k):
            call_order.append("av_import")
            assert k.get("rfv_detail") is not None
            assert k.get("rfv_status") == "success"
            assert k.get("combined_cycle") is not None
            assert k.get("av_presence_detail") is not None
            return ScheduledScrapeResult(
                organization_id=3,
                status="success",
                at_vendor_status="success",
            )

        mock_rfv.side_effect = _presence
        mock_av_import.side_effect = _av_import
        conn = MagicMock()
        conn.cursor.return_value = MagicMock()

        result = run_rinse_combined_sync_for_org(conn, 3, run_type="manual")
        assert call_order == ["rfv", "av_presence", "av_import"]
        assert result.ready_for_vendor_status == "success"
        assert result.status == "success"
        assert (result.detail.get("sync_cycle") or {}).get("cycle_status") == "success"

    @patch("backend.rinse_scheduled_scrape.run_scheduled_scrape_for_org")
    @patch("backend.rinse_presence_scrape.run_presence_scrape_for_org")
    @patch("backend.rinse_scheduled_scrape.release_scrape_lock")
    @patch("backend.rinse_scheduled_scrape.finish_scrape_run")
    @patch("backend.rinse_scheduled_scrape.insert_scrape_run", return_value=88)
    @patch("backend.rinse_scheduled_scrape.acquire_scrape_lock", return_value=(True, ""))
    @patch("backend.rinse_scheduled_scrape.build_run_paths")
    @patch("backend.rinse_scheduled_scrape.resolve_rinse_vendor", return_value="veewash")
    @patch("backend.rinse_scheduled_scrape._org_slug_name", return_value=("veewash", "VeeWash"))
    def test_av_presence_failure_does_not_hide_rfv_success(
        self,
        _slug,
        _vendor,
        mock_paths,
        _lock,
        _ins,
        _fin,
        _rel,
        mock_rfv,
        mock_av_import,
    ):
        from pathlib import Path
        import tempfile

        from backend.rinse_scheduled_scrape import ScrapePaths, run_rinse_combined_sync_for_org

        run_dir = Path(tempfile.mkdtemp())
        mock_paths.return_value = ScrapePaths(
            run_dir=run_dir,
            portal_csv=run_dir / "portal.csv",
            scan_tickets_csv=run_dir / "t.csv",
            scan_events_csv=run_dir / "e.csv",
            log_path=run_dir / "log",
        )

        def _presence(*_a, **k):
            portal = k.get("portal_status") or "ready_for_vendor"
            if portal == "ready_for_vendor":
                return PresenceScrapeResult(
                    organization_id=3,
                    portal_status=portal,
                    status="success",
                    started_at=datetime.utcnow(),
                    finished_at=datetime.utcnow(),
                    stats={"rows_found": 0, "active_rows": 0},
                )
            return PresenceScrapeResult(
                organization_id=3,
                portal_status=portal,
                status="failed",
                error_message="At Vendor presence scrape failed",
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
            )

        mock_rfv.side_effect = _presence
        conn = MagicMock()
        conn.cursor.return_value = MagicMock()

        result = run_rinse_combined_sync_for_org(conn, 3, run_type="scheduled")
        assert result.ready_for_vendor_status == "success"
        assert result.at_vendor_status == "failed"
        assert result.status == "failed"
        assert (result.detail.get("sync_cycle") or {}).get("cycle_status") == "AT_VENDOR_FAILED"
        mock_av_import.assert_not_called()

    @patch("backend.rinse_scheduled_scrape.insert_skipped_scrape_run")
    @patch("backend.rinse_scheduled_scrape.acquire_scrape_lock", return_value=(False, "Previous scrape still active"))
    @patch("backend.rinse_scheduled_scrape.resolve_rinse_vendor", return_value="veewash")
    @patch("backend.rinse_scheduled_scrape._org_slug_name", return_value=("veewash", "VeeWash"))
    def test_overlapping_cycle_prevention_returns_already_running(
        self, _slug, _vendor, _lock, _skip
    ):
        from backend.rinse_scheduled_scrape import CYCLE_ALREADY_RUNNING, run_rinse_combined_sync_for_org

        conn = MagicMock()
        conn.cursor.return_value = MagicMock()
        result = run_rinse_combined_sync_for_org(conn, 3, run_type="manual")
        assert result.status == "skipped"
        assert result.error_message == CYCLE_ALREADY_RUNNING
        assert (result.detail.get("sync_cycle") or {}).get("cycle_status") == "skipped"

    @patch("backend.rinse_scheduled_scrape.run_rinse_combined_sync_for_org")
    def test_run_all_scheduled_scrapes_uses_combined_orchestrator(self, mock_combined):
        from backend.rinse_scheduled_scrape import ScheduledScrapeResult, run_all_scheduled_scrapes

        mock_combined.return_value = ScheduledScrapeResult(organization_id=3, status="success")
        conn = MagicMock()
        with patch("backend.rinse_scheduled_scrape.scheduled_scrape_enabled", return_value=True), patch(
            "backend.rinse_scheduled_scrape.parse_scheduled_org_ids", return_value=[3]
        ):
            results = run_all_scheduled_scrapes(conn, run_type="scheduled")
        mock_combined.assert_called_once_with(conn, 3, run_type="scheduled", dry_run=False)
        assert len(results) == 1


class TestManualSyncEndpointUsesCombinedWorkflow:
    @patch("backend.rinse_manual_sync_dispatch.dispatch_manual_rinse_sync")
    @patch("backend.db.get_db")
    def test_manual_endpoint_dispatches_aca_or_remote_sync(self, mock_db, mock_dispatch):
        from datetime import date

        from flask import Flask

        from backend.rinse_manual_sync_dispatch import ManualSyncDispatchResult
        from backend.rinse_shift_analysis_routes import register_rinse_shift_analysis_routes

        mock_dispatch.return_value = ManualSyncDispatchResult(
            organization_id=3,
            mode="aca_job",
            overall_status="queued",
            http_status=202,
            message="Scheduler job started.",
            aca_execution_name="exec-1",
            detail={
                "ready_for_vendor_sync": {"status": "queued"},
                "at_vendor_sync": {"status": "queued"},
            },
        )
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_db.return_value = conn

        app = Flask(__name__)
        register_rinse_shift_analysis_routes(
            app,
            require_user=lambda _c: ({"organization_id": 3}, None, None),
            require_admin=lambda _c: (None, None, None),
            require_admin_or_ops=lambda _c: (None, None, None),
            user_org_id=lambda _me: 3,
            parse_date_value=lambda _v: date.today(),
        )
        client = app.test_client()
        resp = client.post("/api/rinse/sync/both", json={})

        assert resp.status_code == 202
        mock_dispatch.assert_called_once()
        body = resp.get_json()
        assert body["overall_status"] == "queued"
        assert body["aca_execution_name"] == "exec-1"


class TestStalePresenceGuardBlocksScanInflation:
    def test_stale_presence_keeps_active_population_blocks_scan_only(self):
        from unittest.mock import MagicMock, patch

        from backend.rinse_at_vendor_module import _load_baseline_gated_at_vendor_population
        from backend.rinse_shift_monitor_baseline import BASELINE_SELECTION_BEFORE_MIDNIGHT

        cursor = MagicMock()
        seed_rows = {
            "B0": {
                "bag_id": "B0",
                "service_type": "WF",
                "portal_yet_to_process": True,
                "active_presence": True,
            }
        }
        baseline_run = {
            "id": 18,
            "source_batch_id": "stale-batch",
            "finished_at": datetime(2026, 6, 12, 23, 20, 28),
            "rows_found": 27,
        }
        baseline_ctx = {
            "baseline_source": "latest_clean_veewash_scrape",
            "baseline_start_naive_et": datetime(2026, 6, 12, 23, 20, 28),
            "baseline_time_et": "2026-06-12 23:20:28",
            "baseline_source_batch_id": "stale-batch",
            "baseline_presence_run_id": 18,
            "latest_at_vendor_presence_source_batch_id": "stale-batch",
        }
        with patch(
            "backend.rinse_shift_monitor_baseline.select_daily_at_vendor_baseline_scrape",
            return_value=(baseline_run, BASELINE_SELECTION_BEFORE_MIDNIGHT),
        ), patch(
            "backend.rinse_cleaner_ticket_presence.load_presence_run_snapshot_by_bag",
            return_value=seed_rows,
        ), patch(
            "backend.rinse_cleaner_ticket_presence.count_presence_run_snapshot_rows",
            return_value=1,
        ), patch(
            "backend.rinse_cleaner_ticket_presence.backfill_presence_run_snapshot_from_live_batch",
            return_value=0,
        ), patch(
            "backend.rinse_at_vendor_module._load_active_at_vendor_presence_by_bag",
            return_value=seed_rows,
        ), patch(
            "backend.rinse_at_vendor_module._load_sent_to_vendor_bag_id_sets_for_et_day",
            return_value=(set(), {"SCANONLY1", "SCANONLY2"}),
        ), patch(
            "backend.rinse_at_vendor_module._load_same_day_scrape_arrival_bag_ids",
            return_value=({"SCANONLY3"}, {"SCANONLY3": {"bag_id": "SCANONLY3"}}),
        ), patch(
            "backend.rinse_at_vendor_module._filter_cross_org_contaminated_bags",
            side_effect=lambda _c, _o, ids: (set(ids), []),
        ), patch(
            "backend.rinse_at_vendor_module._load_registry_service_types",
            return_value={},
        ), patch(
            "backend.rinse_at_vendor_module._load_delivery_meta",
            return_value={},
        ), patch(
            "backend.rinse_at_vendor_module._count_contaminated_active_presence_rows",
            return_value=0,
        ), patch(
            "backend.rinse_presence_sync_status.evaluate_at_vendor_presence_freshness",
            return_value=(False, "At Vendor presence stale (>120 min)", {"id": 18}),
        ):
            population, meta = _load_baseline_gated_at_vendor_population(
                cursor,
                3,
                selected_date_et=date(2026, 6, 13),
                baseline_ctx=baseline_ctx,
            )

        assert len(population) == 1
        assert meta["at_vendor_presence_stale"] is True
        assert meta["scan_only_arrivals_blocked_count"] == 3
        assert meta["daily_metrics_reliable"] is False
        assert meta["same_day_arrivals_from_sent_to_vendor_count"] == 0


class TestAtVendorOnlyDoesNotRunRfv:
    @patch("backend.rinse_presence_scrape.run_presence_scrape_for_org")
    @patch("backend.rinse_scheduled_scrape._run_bash_script", return_value=0)
    @patch("backend.rinse_scheduled_scrape.count_csv_data_rows", return_value=5)
    @patch("backend.rinse_scheduled_scrape.acquire_scrape_lock", return_value=(True, ""))
    @patch("backend.rinse_scheduled_scrape.release_scrape_lock")
    @patch("backend.rinse_scheduled_scrape.finish_scrape_run")
    @patch("backend.rinse_scheduled_scrape.insert_scrape_run", return_value=99)
    @patch("backend.rinse_scheduled_scrape.resolve_rinse_vendor", return_value="veewash")
    @patch("backend.rinse_scheduled_scrape.tenant_script_dir")
    @patch("backend.rinse_scheduled_scrape.build_run_paths")
    @patch("backend.rinse_scheduled_scrape._org_slug_name", return_value=("veewash", "VeeWash"))
    def test_at_vendor_only_path_does_not_call_rfv(
        self,
        _slug,
        mock_paths,
        mock_tenant_dir,
        _vendor,
        _ins,
        _fin,
        _rel,
        _lock,
        _count,
        _bash,
        mock_rfv,
    ):
        from pathlib import Path
        import tempfile

        from backend.rinse_scheduled_scrape import ScrapePaths, run_scheduled_scrape_for_org

        mock_tenant_dir.return_value.is_dir.return_value = True
        run_dir = Path(tempfile.mkdtemp())
        p = ScrapePaths(
            run_dir=run_dir,
            portal_csv=run_dir / "portal.csv",
            scan_tickets_csv=run_dir / "t.csv",
            scan_events_csv=run_dir / "e.csv",
            log_path=run_dir / "log",
        )
        mock_paths.return_value = p
        p.portal_csv.write_text("h\n1\n")
        p.scan_events_csv.write_text("h\n1\n")

        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = {"c": 5}
        conn.cursor.return_value = cursor

        with patch("backend.rinse_portal_csv.portal_csv_to_orders_df") as pdf, patch(
            "backend.rinse_scan_events_upload.parse_scan_events_csv", return_value=(MagicMock(), [])
        ), patch("backend.rinse_combined_upload.commit_rinse_combined_upload", return_value={"batch_id": 1, "rows_inserted": 5, "portal_absence_allowed": True}), patch(
            "backend.upload_batch_confirm.confirm_upload_batch_core", return_value={"ok": True}
        ), patch("backend.rinse_scheduled_scrape._subprocess_env_for_vendor", return_value={"RINSE_MAX_PAGES": "500"}), patch(
            "backend.rinse_scheduled_scrape._count_accepted_rows", return_value=5
        ), patch("backend.rinse_scheduled_scrape._count_attention_rows", return_value=0):
            import pandas as pd

            pdf.return_value = pd.DataFrame([{"ticket_id": "ABC"}])
            run_scheduled_scrape_for_org(conn, 3, run_type="manual")

            run_scheduled_scrape_for_org(conn, 3, run_type="manual")

        mock_rfv.assert_not_called()


class TestScheduledSyncStatusFields:
    @patch("backend.rinse_presence_sync_status.get_ready_for_vendor_sync_status")
    @patch("backend.rinse_presence_sync_status.build_at_vendor_sync_status")
    @patch("backend.rinse_scrape_status.table_exists", return_value=True)
    def test_get_scheduled_scrape_status_exposes_separate_syncs(
        self, _tables, mock_av, mock_rfv
    ):
        from backend.rinse_scrape_status import get_scheduled_scrape_status

        mock_rfv.return_value = {
            "latest_attempt_at": "2026-06-08T12:00:00",
            "last_success_at": "2026-06-08T12:00:00",
            "status": "success",
            "rows_found": 0,
            "active_rows": 0,
        }
        mock_av.return_value = {
            "latest_attempt_at": "2026-06-08T12:30:00",
            "last_success_at": "2026-06-08T12:30:00",
            "status": "success",
            "rows_found": 120,
        }
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, None, None]
        out = get_scheduled_scrape_status(cursor, 3)
        assert out["ready_for_vendor_sync"]["latest_attempt_at"] == "2026-06-08T12:00:00"
        assert out["at_vendor_sync"]["latest_attempt_at"] == "2026-06-08T12:30:00"


class TestPresenceScrapeSubprocessErrors:
    def test_format_scrape_subprocess_error_includes_exit_code_and_stderr(self):
        from backend.rinse_presence_scrape import _format_scrape_subprocess_error

        msg = _format_scrape_subprocess_error(
            1,
            "browserType.launch: Executable doesn't exist",
            phase_timeout=900,
        )
        assert "exit 1" in msg
        assert "Executable doesn't exist" in msg

    def test_format_scrape_subprocess_error_timeout(self):
        from backend.rinse_presence_scrape import _format_scrape_subprocess_error

        msg = _format_scrape_subprocess_error(-1, "still running", phase_timeout=900)
        assert "timed out after 900s" in msg
        assert "still running" in msg

    @patch("backend.rinse_presence_scrape.run_bag_export_csv")
    @patch("backend.rinse_presence_scrape.export_enabled", return_value=True)
    @patch("backend.rinse_presence_scrape.ready_for_vendor_scrape_enabled", return_value=True)
    @patch("backend.rinse_cleaner_ticket_presence.ensure_presence_tables")
    def test_presence_scrape_surfaces_subprocess_stderr(
        self, _ensure, _rfv, _export, mock_scrape
    ):
        from backend.rinse_presence_scrape import run_presence_scrape_for_org

        mock_scrape.return_value = (1, "", "Error: page.goto: Target crashed")
        conn = MagicMock()
        conn.cursor.return_value = MagicMock()
        with patch(
            "backend.rinse_presence_scrape.rinse_scrape_env_for_organization",
            return_value=("veewash", {"RINSE_TICKETS_URL": "http://example?status=ready_for_vendor"}),
        ):
            result = run_presence_scrape_for_org(
                conn,
                3,
                portal_status="ready_for_vendor",
                dry_run=True,
            )
        assert result.status == "failed"
        assert "exit 1" in (result.error_message or "")
        assert "Target crashed" in (result.error_message or "")

    def test_preflight_blocks_remote_only_host(self):
        import os
        from unittest.mock import patch

        from backend.rinse_presence_scrape import _preflight_presence_scrape

        with patch.dict(os.environ, {"RINSE_SCRAPE_REMOTE_ONLY": "1"}, clear=False):
            err = _preflight_presence_scrape("veewash", {"RINSE_STORAGE_STATE": "/data/auth.json"})
        assert err is not None
        assert "scheduler" in err.lower()

    def test_merge_presence_scrape_env_prefers_mounted_auth(self, tmp_path):
        import os
        from unittest.mock import patch

        from backend.rinse_presence_scrape import _merge_presence_scrape_env

        data_root = tmp_path / "rinse-scrape"
        tenant_dir = data_root / "tenants" / "veewash"
        tenant_dir.mkdir(parents=True)
        auth = tenant_dir / "rinse-auth.json"
        auth.write_text('{"cookies":[]}', encoding="utf-8")
        with patch.dict(os.environ, {"RINSE_SCRAPE_DATA_ROOT": str(data_root)}, clear=False):
            merged = _merge_presence_scrape_env(
                "veewash",
                {"RINSE_STORAGE_STATE": "/stale/wwwroot/rinse-auth.json"},
            )
        assert merged["RINSE_STORAGE_STATE"] == str(auth)


class TestRecordFailedPresenceRun:
    @patch("backend.rinse_cleaner_ticket_presence.ensure_presence_tables")
    def test_record_presence_scrape_run_inserts_failed(self, _ensure):
        from datetime import datetime

        from backend.rinse_cleaner_ticket_presence import record_presence_scrape_run

        cursor = MagicMock()
        record_presence_scrape_run(
            cursor,
            3,
            portal_status="ready_for_vendor",
            source_batch_id="manual-abc",
            source_url="http://example",
            run_type="manual",
            status="failed",
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            errors=["Scrape subprocess failed"],
        )
        insert_calls = [
            c for c in cursor.execute.call_args_list if "INSERT INTO rinse_cleaner_ticket_presence_runs" in str(c[0][0])
        ]
        assert insert_calls
        assert "failed" in insert_calls[0][0][1]


class TestPresenceWritesOnlyPresenceTable:
    def test_apply_presence_scrape_does_not_touch_staging(self):
        import inspect

        from backend.rinse_cleaner_ticket_presence import apply_presence_scrape

        src = inspect.getsource(apply_presence_scrape)
        assert "orders_staging" not in src
        assert "upload_batch" not in src
        assert "rinse_cleaner_ticket_presence" in src


class TestShiftMonitorSeparateSyncStatuses:
    def test_build_sync_status_names_sync(self):
        from backend.rinse_simple_shift_performance import _build_sync_status

        out = _build_sync_status("2026-06-07T12:11:00", sync_name="At Vendor Sync")
        assert "At Vendor Sync" in out["message"]
        assert out["sync_name"] == "At Vendor Sync"

    def test_build_sync_status_accepts_aware_evaluation_time(self):
        from datetime import datetime, timezone, timedelta

        from backend.rinse_simple_shift_performance import _build_sync_status

        now = datetime.now(timezone.utc)
        last = (now - timedelta(minutes=30)).replace(tzinfo=None).isoformat()
        out = _build_sync_status(last, sync_name="At Vendor Sync", evaluation_time=now)
        assert out["age_minutes"] == 30

    def test_at_vendor_sync_status_accepts_aware_db_timestamps(self):
        from datetime import datetime, timezone, timedelta

        from backend.rinse_presence_sync_status import build_sync_status_from_run

        finished = datetime.now(timezone.utc) - timedelta(minutes=45)
        run = {"finished_at": finished, "status": "success", "created_at": finished}
        out = build_sync_status_from_run(
            run,
            sync_name="At Vendor Sync",
            evaluation_time=datetime.now(timezone.utc),
        )
        assert out["age_minutes"] == 45

    @patch("backend.rinse_presence_sync_status.ready_for_vendor_scrape_enabled", return_value=False)
    @patch("backend.rinse_presence_sync_status.build_at_vendor_sync_status")
    @patch("backend.rinse_presence_sync_status.get_ready_for_vendor_sync_status")
    def test_rfv_disabled_status(self, mock_rfv, mock_av, _flag):
        from backend.rinse_simple_shift_performance import _attach_section_sync_statuses

        mock_av.return_value = {"message": "At Vendor Sync: Jun 7, 12:11 PM", "enabled": True}
        mock_rfv.return_value = {
            "enabled": False,
            "status": "disabled",
            "message": "Ready for Vendor Sync: disabled",
        }
        out = _attach_section_sync_statuses(
            MagicMock(),
            3,
            ready_for_vendor={"total": 0},
            active_work={"total": 0},
        )
        assert out["ready_for_vendor_enabled"] is False
        assert out["ready_for_vendor"]["status"] == "disabled"
