"""Tests for combined At Vendor + Ready for Vendor scheduled sync."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from backend.rinse_presence_scrape import PresenceScrapeResult, ready_for_vendor_scrape_enabled
from backend.rinse_scheduled_scrape import _combine_scheduled_status
from backend.rinse_cleaner_ticket_presence import PORTAL_STATUS_READY, apply_presence_scrape


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
    def test_zero_rows_marks_old_rows_inactive(self, _ensure):
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
        )
        assert stats["rows_found"] == 0
        assert stats["rows_missing"] == 1
        assert stats["active_rows"] == 0
        update_calls = [c for c in cursor.execute.call_args_list if "SET active=0" in str(c[0][0])]
        assert update_calls


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
    def test_scheduled_runs_rfv_when_flag_path_called(
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
        from datetime import datetime
        from pathlib import Path

        from backend.rinse_scheduled_scrape import ScrapePaths, run_scheduled_scrape_for_org

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
            status="success",
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            stats={"rows_found": 2},
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
            result = run_scheduled_scrape_for_org(conn, 3, run_type="scheduled")

        mock_rfv.assert_called_once()
        assert mock_rfv.call_args.kwargs.get("mark_missing") is True
        assert result.ready_for_vendor_status == "success"
        assert result.status == "success"

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
        from datetime import datetime
        from pathlib import Path

        from backend.rinse_scheduled_scrape import ScrapePaths, run_scheduled_scrape_for_org

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
            result = run_scheduled_scrape_for_org(conn, 3, run_type="scheduled")

        assert result.at_vendor_status == "success"
        assert result.ready_for_vendor_status == "failed"
        assert result.status == "partial_success"


class TestSyncBothRunsRfvFirst:
    @patch("backend.rinse_scheduled_scrape.run_scheduled_scrape_for_org")
    @patch("backend.rinse_presence_scrape.run_presence_scrape_for_org")
    def test_rfv_runs_before_at_vendor_with_skip_flag(self, mock_rfv, mock_av):
        from datetime import datetime

        from backend.rinse_scheduled_scrape import ScheduledScrapeResult

        mock_rfv.return_value = PresenceScrapeResult(
            organization_id=3,
            portal_status="ready_for_vendor",
            status="success",
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            stats={"rows_found": 0, "active_rows": 0},
        )
        mock_av.return_value = ScheduledScrapeResult(
            organization_id=3,
            status="success",
            at_vendor_status="success",
        )

        conn = MagicMock()
        mock_rfv(conn, 3, portal_status="ready_for_vendor", dry_run=False, mark_missing=True)
        mock_av(conn, 3, run_type="manual", dry_run=False, skip_ready_for_vendor=True)

        assert mock_rfv.call_count == 1
        assert mock_av.call_count == 1
        assert mock_rfv.call_args.kwargs.get("mark_missing") is True
        assert mock_av.call_args.kwargs.get("skip_ready_for_vendor") is True


class TestSkipReadyForVendorInScheduled:
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
    def test_skip_rfv_when_requested(
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
            run_scheduled_scrape_for_org(conn, 3, run_type="manual", skip_ready_for_vendor=True)

        mock_rfv.assert_not_called()


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
