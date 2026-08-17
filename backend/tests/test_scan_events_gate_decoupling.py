"""Regression: portal ACA gate blocks portal confirm but scan events still import."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import os

import pandas as pd
import pytest

from backend.rinse_portal_confirm_gate import GATE_FAILURE_REASON
from backend.rinse_scheduled_scrape import _build_gate_block_operational_log
from backend.tests.portal_csv_gate_fixtures import write_gate_passing_portal_csv
from backend.tests.test_rinse_portal_confirm_gate import PORTAL_HEADER, _row, _write_csv


class TestGateBlockOperationalLog:
    def test_operational_fields_when_scan_import_succeeds(self):
        portal_gate = {
            "confirm_decision": "inspect_only",
            "reason": GATE_FAILURE_REASON,
            "should_create_batch": False,
        }
        scan_detail = {
            "status": "scan_events_imported",
            "batch_id": 808,
            "persistent_scan_merge": {"events_inserted": 42, "bags_merged": 11},
        }
        ops = _build_gate_block_operational_log(portal_gate, scan_detail)
        assert ops["portal_confirm_blocked"] is True
        assert ops["portal_confirm_block_reason"] == GATE_FAILURE_REASON
        assert ops["scan_events_import_attempted"] is True
        assert ops["scan_events_imported_count"] == 42
        assert ops["scan_only_batch_id"] == 808


class TestInspectOnlyScanImportIntegration:
    def _run_gate_blocked_with_scan_import(self, tmp_path: Path):
        from backend.rinse_scheduled_scrape import ScrapePaths, run_scheduled_scrape_for_org

        paths = ScrapePaths(
            run_dir=tmp_path,
            portal_csv=tmp_path / "portal.csv",
            scan_tickets_csv=tmp_path / "t.csv",
            scan_events_csv=tmp_path / "e.csv",
            log_path=tmp_path / "log",
        )
        _write_csv(paths.portal_csv, [_row()])

        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = {"c": 1}
        conn.cursor.return_value = cursor

        tenant = MagicMock()
        tenant.is_dir.return_value = True
        tenant.__truediv__ = lambda _self, name: Path(tmp_path / name)

        events_df = pd.DataFrame(
            [{"Bag ID": "ABC1234567", "Time Scanned": "06/26/2026 10:00 AM", "Purpose": "weight-entry"}]
        )
        scan_payload = {
            "status": "scan_events_imported",
            "batch_id": 909,
            "scan_rows": 3,
            "persistent_scan_merge": {"events_inserted": 3, "bags_merged": 1},
            "scan_events_batch": {"rows_inserted": 3},
        }

        import_patcher = patch(
            "backend.rinse_scheduled_scrape._import_scan_events_when_portal_gate_blocked",
            return_value=scan_payload,
        )
        patches = [
            patch.dict(os.environ, {"RINSE_AV_SINGLE_PASS": "0"}),
            patch("backend.rinse_scheduled_scrape.tenant_script_dir", return_value=tenant),
            patch("backend.rinse_scheduled_scrape.acquire_scrape_lock", return_value=(True, "")),
            patch("backend.rinse_scheduled_scrape.insert_scrape_run", return_value=1),
            patch("backend.rinse_scheduled_scrape.build_run_paths", return_value=paths),
            patch("backend.rinse_scheduled_scrape._run_bash_script", return_value=0),
            patch("backend.rinse_scheduled_scrape._subprocess_env_for_vendor", return_value={}),
            import_patcher,
            patch(
                "backend.rinse_scheduled_scrape._run_targeted_pending_scan_refresh",
                return_value={"targeted_refresh_ran": True, "missing_scans_imported": 0},
            ),
            patch(
                "backend.rinse_combined_upload.commit_rinse_combined_upload",
                side_effect=AssertionError("portal batch must not be created"),
            ),
        ]
        started = []
        for p in patches:
            started.append(p.start())
        try:
            result = run_scheduled_scrape_for_org(conn, 3, run_type="scheduled")
        finally:
            for p in reversed(patches):
                p.stop()
        return result, started[7]

    def test_gate_blocked_scan_import_no_portal_batch(self, tmp_path):
        result, mock_import = self._run_gate_blocked_with_scan_import(tmp_path)
        mock_import.assert_called_once()
        assert result.status == "inspect_only"
        assert result.batch_id == 909
        assert result.detail["portal_confirm_blocked"] is True
        assert result.detail["scan_events_import_attempted"] is True
        assert result.detail["scan_events_imported_count"] == 3
        assert result.detail["scan_only_batch_id"] == 909

    def test_shift_monitor_employee_section_when_completions_exist(self):
        from backend.rinse_employee_completed_bags import build_employee_completed_bags_today
        from datetime import date, datetime

        row = {
            "bag_id": "ABC1234567",
            "at_vendor_status": "Completed",
            "module_tags": ["mod_at_vendor_completed"],
            "completion_time": datetime(2026, 6, 26, 10, 5).isoformat(),
            "service_type": "WF",
            "post_clean_weight": 10.0,
        }
        events = {
            "ABC1234567": [
                {"purpose": "sent-to-vendor", "scanned_at_parsed": datetime(2026, 6, 26, 8, 0)},
                {
                    "purpose": "weight-entry",
                    "scanned_at_parsed": datetime(2026, 6, 26, 10, 5),
                    "user_name": "Worker",
                },
            ],
        }
        with patch(
            "backend.rinse_simple_shift_performance._load_rinse_user_maps",
            return_value={"worker": {"user_id": 1, "display_name": "Worker"}},
        ), patch(
            "backend.rinse_processing_productivity._load_shift_sessions_bulk",
            return_value={1: [{"clock_in_at": datetime(2026, 6, 26, 8, 0), "clock_out_at": None}]},
        ), patch(
            "backend.rinse_simple_shift_performance._employee_shift_window",
            return_value=(datetime(2026, 6, 26, 8, 0), None, None),
        ), patch("backend.daily_shift_roster.list_roster_entries", return_value=[]), patch(
            "backend.daily_shift_roster.build_roster_role_lookup", return_value={}
        ), patch(
            "backend.rinse_employee_completed_bags._load_upstream_processing_scan_times_bulk",
            return_value={},
        ), patch(
            "backend.rinse_employee_completed_bags._load_employee_day_scan_events_bulk",
            return_value={},
        ):
            out = build_employee_completed_bags_today(
                MagicMock(),
                3,
                completed_rows=[row],
                events_by_bag=events,
                selected_date_et=date(2026, 6, 26),
            )
        assert out["reconciliation"]["workload_completed_today"] == 1
        assert len(out.get("employees") or []) == 1


class TestTargetedScrapeTimeout:
    def test_run_targeted_portal_scrape_timeout_marks_bags_failed(self, tmp_path):
        import subprocess

        from backend.rinse_off_portal_scan_refresh import run_targeted_portal_scrape

        fake_script = tmp_path / "scrape-targeted-bags.mjs"
        fake_script.write_text("//")
        with patch(
            "backend.rinse_off_portal_scan_refresh.TARGETED_SCRAPE_SCRIPT",
            fake_script,
        ), patch(
            "backend.rinse_off_portal_scan_refresh.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="node", timeout=30),
        ):
            out = run_targeted_portal_scrape(["BAG1", "BAG2"], organization_id=3, timeout_sec=60)
        assert out["bags"] == []
        assert "BAG1" in out["timed_out_bag_ids"]
        assert "BAG2" in out["lookup_failed_bag_ids"]
