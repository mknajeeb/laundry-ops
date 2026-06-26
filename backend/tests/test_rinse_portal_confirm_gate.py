"""Tests for portal scrape auto-confirm gate."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import pytest

from backend.rinse_portal_confirm_gate import (
    GATE_FAILURE_REASON,
    assess_portal_csv_row,
    build_portal_confirm_gate_report,
    evaluate_portal_confirm_gate,
)

PORTAL_HEADER = [
    "Date",
    "Estd. Delivery",
    "Customer",
    "# WF LBS",
    "# HD",
    "# WF ITEMS",
    "Weight",
    "Notes",
    "Special Instructions",
    "USE OXIC",
    "Use Hypo",
    "USE FAB",
    "Low DRY",
    "NO SCEN",
    "Extra Scen",
    "Service Type",
    "Sub-Service",
    "Bag ID",
]

CATALOG_SI = (
    "Vendor Notes Vendor Price Collateral Dry Clean Hang Dry Launder & Press "
    "Leather Cleaning Press Only Repair Shine Special Services Specialty Items "
    "Wash and Fold Apron Baby Clothing Bag"
)


def _row(
    *,
    si: str = "",
    oxic: str = "",
    hypo: str = "",
    fab: str = "",
    bag: str = "ABC1234567 (Wash & Fold) (Full)",
) -> dict[str, str]:
    return {
        "Date": "Mon 06/15/2026",
        "Estd. Delivery": "Mon 06/15/2026",
        "Customer": "Test Customer",
        "# WF LBS": "18.8",
        "# HD": "NA",
        "# WF ITEMS": "",
        "Weight": "18.8 LBS",
        "Notes": "",
        "Special Instructions": si,
        "USE OXIC": oxic,
        "Use Hypo": hypo,
        "USE FAB": fab,
        "Low DRY": "",
        "NO SCEN": "",
        "Extra Scen": "",
        "Service Type": "Wash & Fold",
        "Sub-Service": "Full",
        "Bag ID": bag,
    }


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PORTAL_HEADER)
        writer.writeheader()
        writer.writerows(rows)


class TestPortalConfirmGateDecisions:
    def test_empty_si_and_no_flags_no_confirm(self):
        report = build_portal_confirm_gate_report([_row()])
        gate = evaluate_portal_confirm_gate(_csv_with_rows([_row()]))
        assert report["total_rows"] == 1
        assert report["rows_with_flags"] == 0
        assert report["rows_with_clean_si"] == 0
        assert gate["confirm_decision"] == "inspect_only"
        assert gate["should_create_batch"] is False
        assert gate["reason"] == GATE_FAILURE_REASON

    def test_catalog_polluted_si_with_template_flags_no_confirm(self):
        rows = [_row(si=CATALOG_SI, oxic="X", hypo="X", fab="X")]
        report = build_portal_confirm_gate_report(rows)
        gate = evaluate_portal_confirm_gate(_csv_with_rows(rows))
        assert report["rows_with_flags"] == 1
        assert report["rows_with_catalog_pollution"] == 1
        assert report["rows_with_template_like_flags"] == 1
        assert report["rows_with_credible_flags"] == 0
        assert gate["confirm_decision"] == "inspect_only"
        assert gate["should_create_batch"] is False

    def test_clean_si_with_supply_token_confirms(self):
        rows = [_row(si="USE OXICLEAN")]
        gate = evaluate_portal_confirm_gate(_csv_with_rows(rows))
        assert gate["rows_with_clean_si"] == 1
        assert gate["confirm_decision"] == "confirm"
        assert gate["reason"] == "clean_si_supply_tokens"
        assert gate["should_create_batch"] is True
        assert gate["should_auto_confirm"] is True

    def test_credible_detail_pane_flags_confirms(self):
        rows = [_row(oxic="X", fab="X")]
        assessed = assess_portal_csv_row(rows[0])
        assert assessed["credible_flags"] is True
        gate = evaluate_portal_confirm_gate(_csv_with_rows(rows))
        assert gate["rows_with_credible_flags"] == 1
        assert gate["confirm_decision"] == "confirm"
        assert gate["reason"] == "credible_detail_pane_flags"
        assert gate["should_create_batch"] is True

    def test_manual_force_override_confirms_with_warning(self):
        rows = [_row(si=CATALOG_SI, oxic="X", hypo="X", fab="X")]
        gate = evaluate_portal_confirm_gate(_csv_with_rows(rows), force_confirm=True)
        assert gate["confirm_decision"] == "confirm"
        assert gate["reason"] == "manual_force_override"
        assert gate["force_override"] is True
        assert gate["should_create_batch"] is True
        assert "force override" in str(gate.get("warning") or "").lower()


def _csv_with_rows(rows: list[dict[str, str]]) -> Path:
    tmp = Path(tempfile.mkdtemp()) / "portal.csv"
    _write_csv(tmp, rows)
    return tmp


class TestScheduledScrapePortalGateIntegration:
    @pytest.fixture
    def scrape_paths(self, tmp_path):
        from backend.rinse_scheduled_scrape import ScrapePaths

        return ScrapePaths(
            run_dir=tmp_path,
            portal_csv=tmp_path / "portal.csv",
            scan_tickets_csv=tmp_path / "t.csv",
            scan_events_csv=tmp_path / "e.csv",
            log_path=tmp_path / "log",
        )

    def _run_with_portal_rows(self, paths, rows, *, force_portal_confirm=None):
        from unittest.mock import MagicMock, patch

        import pandas as pd

        from backend.rinse_scheduled_scrape import run_scheduled_scrape_for_org

        _write_csv(paths.portal_csv, rows)
        paths.scan_events_csv.write_text("h\n1\n")

        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = {"c": 1}
        conn.cursor.return_value = cursor

        tenant = MagicMock()
        tenant.is_dir.return_value = True
        tenant.__truediv__ = lambda _self, name: Path(paths.run_dir / name)

        patches = [
            patch("backend.rinse_scheduled_scrape.tenant_script_dir", return_value=tenant),
            patch("backend.rinse_scheduled_scrape.acquire_scrape_lock", return_value=(True, "")),
            patch("backend.rinse_scheduled_scrape.insert_scrape_run", return_value=1),
            patch("backend.rinse_scheduled_scrape.build_run_paths", return_value=paths),
            patch("backend.rinse_scheduled_scrape._run_bash_script", return_value=0),
            patch("backend.rinse_scheduled_scrape._subprocess_env_for_vendor", return_value={}),
            patch(
                "backend.rinse_portal_csv.portal_csv_to_orders_df",
                return_value=pd.DataFrame([{"ticket_id": "ABC1234567"}]),
            ),
            patch("backend.rinse_scan_events_upload.parse_scan_events_csv", return_value=(MagicMock(), [])),
            patch(
                "backend.rinse_combined_upload.commit_rinse_combined_upload",
                return_value={"batch_id": 99, "rows_inserted": 1, "portal_absence_allowed": True},
            ),
            patch("backend.rinse_scheduled_scrape._count_accepted_rows", return_value=1),
            patch("backend.rinse_scheduled_scrape._count_attention_rows", return_value=0),
            patch("backend.upload_batch_confirm.confirm_upload_batch_core", return_value={"ok": True}),
            patch("backend.rinse_off_portal_scan_refresh.off_portal_refresh_enabled", return_value=False),
        ]
        for p in patches:
            p.start()
        try:
            return run_scheduled_scrape_for_org(
                conn,
                3,
                run_type="scheduled",
                force_portal_confirm=force_portal_confirm,
            )
        finally:
            for p in reversed(patches):
                p.stop()

    def test_scheduled_gate_blocks_empty_si_scrape(self, scrape_paths):
        from unittest.mock import patch

        scan_import_payload = {
            "status": "scan_events_imported",
            "scan_rows": 5,
            "batch_id": 501,
            "persistent_scan_merge": {"events_inserted": 12, "bags_merged": 4},
        }
        with patch(
            "backend.rinse_scheduled_scrape._import_scan_events_when_portal_gate_blocked",
            return_value=scan_import_payload,
        ) as mock_scan_import, patch(
            "backend.rinse_scheduled_scrape._run_targeted_pending_scan_refresh",
            return_value={"targeted_refresh_ran": False},
        ):
            result = self._run_with_portal_rows(scrape_paths, [_row()])
        mock_scan_import.assert_called_once()
        assert result.status == "inspect_only"
        assert result.batch_id == 501
        assert result.scan_events_count == 5
        gate = (result.detail or {}).get("portal_confirm_gate") or {}
        assert gate.get("confirm_decision") == "inspect_only"
        assert result.detail.get("sync_warning") == GATE_FAILURE_REASON
        assert (result.detail.get("scan_events_only_import") or {}).get("status") == "scan_events_imported"

    def test_scheduled_gate_allows_clean_si_scrape(self, scrape_paths):
        result = self._run_with_portal_rows(scrape_paths, [_row(si="USE OXICLEAN")])
        assert result.status == "success"
        assert result.batch_id == 99

    def test_scheduled_force_override_bypasses_gate(self, scrape_paths):
        result = self._run_with_portal_rows(
            scrape_paths,
            [_row(si=CATALOG_SI, oxic="X", hypo="X", fab="X")],
            force_portal_confirm=True,
        )
        assert result.status == "success"
        assert result.batch_id == 99
        assert "force override" in str((result.detail or {}).get("sync_warning") or "").lower()
