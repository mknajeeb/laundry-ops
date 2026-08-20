"""At Vendor single-pass scheduled sync (one Playwright walk)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.rinse_scheduled_scrape import (
    ScrapePaths,
    _materialize_portal_csv_from_scan_tickets,
    _resolve_combined_cycle_status,
    av_single_pass_enabled,
)
from backend.tests.test_rinse_portal_confirm_gate import PORTAL_HEADER, _row, _write_csv


class TestAvSinglePassFlag:
    def test_default_on(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RINSE_AV_SINGLE_PASS", None)
            assert av_single_pass_enabled() is True

    def test_explicit_off(self):
        with patch.dict(os.environ, {"RINSE_AV_SINGLE_PASS": "0"}):
            assert av_single_pass_enabled() is False

    def test_explicit_on(self):
        with patch.dict(os.environ, {"RINSE_AV_SINGLE_PASS": "1"}):
            assert av_single_pass_enabled() is True


class TestResolveCombinedStatusSinglePass:
    def test_pending_single_pass_defers_to_import(self):
        assert (
            _resolve_combined_cycle_status(
                rfv_status="disabled",
                av_presence_status="pending_single_pass",
                import_status="success",
            )
            == "success"
        )

    def test_rfv_never_blocks_when_disabled(self):
        assert (
            _resolve_combined_cycle_status(
                rfv_status="disabled",
                av_presence_status="success",
                import_status="success",
            )
            == "success"
        )


class TestMaterializePortalFromTickets:
    def test_copies_tickets_and_writes_meta(self, tmp_path: Path):
        tickets = tmp_path / "scan-events-tickets.csv"
        portal = tmp_path / "portal.csv"
        _write_csv(tickets, [_row()])
        paths = ScrapePaths(
            run_dir=tmp_path,
            portal_csv=portal,
            scan_tickets_csv=tickets,
            scan_events_csv=tmp_path / "e.csv",
            log_path=tmp_path / "log",
        )
        log = MagicMock()
        _materialize_portal_csv_from_scan_tickets(paths, log)
        assert portal.is_file()
        assert portal.read_text() == tickets.read_text()
        assert Path(str(portal) + ".meta.json").is_file()


class TestSinglePassSkipsPortalBash:
    def test_run_scheduled_uses_scan_only_when_single_pass(self, tmp_path: Path):
        from contextlib import ExitStack

        from backend.rinse_scheduled_scrape import run_scheduled_scrape_for_org
        from backend.rinse_presence_scrape import PresenceScrapeResult

        paths = ScrapePaths(
            run_dir=tmp_path,
            portal_csv=tmp_path / "portal.csv",
            scan_tickets_csv=tmp_path / "t.csv",
            scan_events_csv=tmp_path / "e.csv",
            log_path=tmp_path / "log",
        )
        _write_csv(paths.scan_tickets_csv, [_row()])
        paths.scan_events_csv.write_text(
            "Bag ID,Scan Index,Rack,Time Scanned,User,Purpose,Last Location,Last Scan\n"
            "ABC1234567,1,,06/26/2026 10:00 AM,,weight-entry,,\n",
            encoding="utf-8",
        )

        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {"slug": "veewash", "name": "VeeWash"},
            {"c": 1},
            {"c": 0},
            {"c": 1},
            {"c": 0},
        ]
        conn.cursor.return_value = cursor

        tenant = MagicMock()
        tenant.is_dir.return_value = True
        tenant.__truediv__ = lambda _self, name: Path(tmp_path / str(name))

        presence = PresenceScrapeResult(
            organization_id=3,
            portal_status="at_vendor",
            status="success",
            started_at=__import__("datetime").datetime.utcnow(),
            finished_at=__import__("datetime").datetime.utcnow(),
        )
        presence.stats = {
            "run_id": 99,
            "rows_found": 1,
            "rows_inserted": 0,
            "rows_updated": 1,
            "rows_unchanged": 0,
            "active_rows": 1,
        }

        bash_calls: list[str] = []

        def fake_bash(script, env, log, **kwargs):
            bash_calls.append(Path(script).name)
            return 0

        draft = {
            "status": "draft_uploaded",
            "batch_id": 1,
            "rows_inserted": 1,
            "portal_absence_allowed": True,
            "persistent_scan_merge": {
                "events_inserted": 1,
                "events_already_present": 0,
                "import_incomplete": False,
            },
        }
        confirm = {
            "status": "batch_confirmed",
            "batch_id": 1,
        }

        patches = [
            patch.dict(os.environ, {"RINSE_AV_SINGLE_PASS": "1"}),
            patch("backend.rinse_scheduled_scrape.tenant_script_dir", return_value=tenant),
            patch("backend.rinse_scheduled_scrape.acquire_scrape_lock", return_value=(True, "")),
            patch("backend.rinse_scheduled_scrape.insert_scrape_run", return_value=42),
            patch("backend.rinse_scheduled_scrape.build_run_paths", return_value=paths),
            patch("backend.rinse_scheduled_scrape._run_bash_script", side_effect=fake_bash),
            patch("backend.rinse_scheduled_scrape._subprocess_env_for_vendor", return_value={}),
            patch("backend.rinse_scheduled_scrape.resolve_rinse_vendor", return_value="veewash"),
            patch(
                "backend.rinse_scheduled_scrape._org_slug_name",
                return_value=("veewash", "VeeWash"),
            ),
            patch(
                "backend.rinse_presence_scrape.apply_at_vendor_presence_from_portal_csv",
                return_value=presence,
            ),
            patch(
                "backend.rinse_combined_upload.commit_rinse_combined_upload",
                return_value=draft,
            ),
            patch(
                "backend.upload_batch_confirm.confirm_upload_batch_core",
                return_value=confirm,
            ),
            patch(
                "backend.rinse_scheduled_scrape._refresh_open_step1_day_after_scrape",
                return_value={"ok": True, "step1_refresh_status": "SUCCESS"},
            ),
            patch(
                "backend.rinse_scheduled_scrape._run_in_lock_rinse_finalize",
                return_value={"persistent_merge": {"events_inserted": 0}},
            ),
            patch("backend.rinse_scheduled_scrape.finish_scrape_run"),
            patch("backend.rinse_scheduled_scrape.release_scrape_lock"),
            patch("backend.rinse_scheduled_scrape._newest_source_scan_et", return_value=None),
            patch("backend.rinse_scheduled_scrape._newest_db_scan_et", return_value=None),
            patch(
                "backend.rinse_scan_events_upload.parse_scan_events_csv",
                return_value=(
                    pd.DataFrame(
                        [
                            {
                                "Bag ID": "ABC1234567",
                                "Time Scanned": "06/26/2026 10:00 AM",
                                "Purpose": "weight-entry",
                            }
                        ]
                    ),
                    [],
                ),
            ),
            patch(
                "backend.rinse_portal_csv.portal_csv_to_orders_df",
                return_value=pd.DataFrame([{"bag_id": "ABC1234567"}]),
            ),
            patch(
                "backend.manual_checkout_eligibility.resolve_stale_portal_attention_rows_before_confirm"
            ),
        ]
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result = run_scheduled_scrape_for_org(conn, 3, run_type="scheduled")

        assert "run-production-scrape.sh" not in bash_calls
        assert "run-scan-events.sh" in bash_calls
        assert paths.portal_csv.is_file()
        assert result.detail.get("av_single_pass") is True
        assert result.detail.get("at_vendor_presence_sync", {}).get("run_id") == 99
