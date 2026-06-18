"""Scheduled ACA sync runs targeted pending refresh when env enabled."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd


def _run_scheduled_with_mocks(*, refresh_side_effect=None, refresh_return=None):
    import tempfile

    from backend.rinse_scheduled_scrape import ScrapePaths, run_scheduled_scrape_for_org

    run_dir = Path(tempfile.mkdtemp())
    paths = ScrapePaths(
        run_dir=run_dir,
        portal_csv=run_dir / "portal.csv",
        scan_tickets_csv=run_dir / "t.csv",
        scan_events_csv=run_dir / "e.csv",
        log_path=run_dir / "log",
    )
    paths.portal_csv.write_text("h\n1\n")
    paths.scan_events_csv.write_text("h\n1\n")

    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = {"c": 1}
    conn.cursor.return_value = cursor

    tenant = MagicMock()
    tenant.is_dir.return_value = True
    tenant.__truediv__ = lambda _self, name: tenant / name if False else Path(run_dir / name)

    refresh_payload = refresh_return or {
        "dry_run": False,
        "bag_ids_requested": ["BAG1"],
        "bags_processed": 1,
        "events_inserted": 2,
        "lookup_failed": 0,
        "bags": [],
    }

    patches = [
        patch("backend.rinse_scheduled_scrape.tenant_script_dir", return_value=tenant),
        patch("backend.rinse_scheduled_scrape.acquire_scrape_lock", return_value=(True, "")),
        patch("backend.rinse_scheduled_scrape.insert_scrape_run", return_value=1),
        patch("backend.rinse_scheduled_scrape.build_run_paths", return_value=paths),
        patch("backend.rinse_scheduled_scrape._run_bash_script", return_value=0),
        patch("backend.rinse_scheduled_scrape._subprocess_env_for_vendor", return_value={}),
        patch("backend.rinse_scheduled_scrape._count_accepted_rows", return_value=1),
        patch("backend.rinse_scheduled_scrape._count_attention_rows", return_value=0),
        patch("backend.rinse_portal_csv.portal_csv_to_orders_df", return_value=pd.DataFrame([{"ticket_id": "ABC"}])),
        patch("backend.rinse_scan_events_upload.parse_scan_events_csv", return_value=(MagicMock(), [])),
        patch(
            "backend.rinse_combined_upload.commit_rinse_combined_upload",
            return_value={"batch_id": 99, "rows_inserted": 1, "portal_absence_allowed": True},
        ),
        patch("backend.upload_batch_confirm.confirm_upload_batch_core", return_value={"ok": True}),
        patch("backend.rinse_off_portal_scan_refresh.off_portal_refresh_enabled", return_value=True),
        patch("backend.rinse_off_portal_scan_refresh.off_portal_refresh_dry_run", return_value=False),
        patch("backend.rinse_off_portal_scan_refresh.off_portal_refresh_rush_only", return_value=False),
        patch("backend.rinse_shift_monitor_baseline.build_baseline_context", return_value={}),
        patch("backend.rinse_shift_monitor_baseline.get_shift_monitor_baseline", return_value={}),
    ]

    refresh_kw = {}
    if refresh_side_effect is not None:
        refresh_kw["side_effect"] = refresh_side_effect
    else:
        refresh_kw["return_value"] = refresh_payload

    with patch(
        "backend.rinse_off_portal_scan_refresh.refresh_pending_workload_scans_via_direct_lookup",
        **refresh_kw,
    ) as mock_refresh:
        for p in patches:
            p.start()
        try:
            result = run_scheduled_scrape_for_org(conn, 3, run_type="scheduled")
        finally:
            for p in reversed(patches):
                p.stop()

    return result, mock_refresh


def test_scheduled_run_invokes_targeted_refresh_when_enabled():
    result, mock_refresh = _run_scheduled_with_mocks()
    mock_refresh.assert_called_once()
    assert mock_refresh.call_args.kwargs.get("dry_run") is False
    detail = (result.detail or {}).get("targeted_pending_scan_refresh") or {}
    assert detail.get("targeted_refresh_ran") is True
    assert detail.get("targeted_bags_considered") == 1
    assert detail.get("missing_scans_imported") == 2


def test_scheduled_refresh_failure_does_not_fail_main_sync():
    result, _mock_refresh = _run_scheduled_with_mocks(
        refresh_side_effect=RuntimeError("portal timeout"),
    )
    assert result.status in ("success", "needs_attention")
    detail = (result.detail or {}).get("targeted_pending_scan_refresh") or {}
    assert detail.get("targeted_refresh_ran") is False
    assert "portal timeout" in str(detail.get("error") or "")
