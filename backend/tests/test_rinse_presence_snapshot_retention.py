"""Tests for presence snapshot retention."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_presence_snapshot_retention import (
    KEEP_LATEST_SUCCESSFUL_SNAPSHOTS,
    prune_presence_run_snapshots,
    resolve_protected_presence_run_ids,
)


def _runs(n: int, portal_status: str = "at_vendor") -> list[dict]:
    return [
        {
            "id": 100 + i,
            "organization_id": 3,
            "portal_status": portal_status,
            "status": "success",
            "finished_at": datetime(2026, 6, 10 + i, 12, 0),
            "errors_json": None,
            "scrape_meta_json": {"rinse_vendor": "veewash"},
        }
        for i in range(n)
    ]


class TestPresenceSnapshotRetention:
    def test_keeps_latest_three_plus_baseline(self):
        cursor = MagicMock()
        runs = _runs(5)
        with patch(
            "backend.rinse_presence_snapshot_retention._list_successful_presence_runs",
            return_value=runs,
        ), patch(
            "backend.rinse_presence_snapshot_retention.select_daily_at_vendor_baseline_scrape",
            return_value=(runs[2], "before_midnight"),
        ):
            keep = resolve_protected_presence_run_ids(
                cursor, 3, portal_status="at_vendor", selected_date_et=date(2026, 6, 13)
            )
        assert {100, 101, 102}.issubset(keep)

    def test_prune_reports_deleted_rows(self):
        cursor = MagicMock()
        runs = _runs(5)
        cursor.fetchone.return_value = {"c": 0}
        cursor.rowcount = 2
        with patch(
            "backend.rinse_presence_snapshot_retention.table_exists",
            return_value=True,
        ), patch(
            "backend.rinse_presence_snapshot_retention._list_successful_presence_runs",
            return_value=runs,
        ), patch(
            "backend.rinse_presence_snapshot_retention.resolve_protected_presence_run_ids",
            return_value={100, 101, 102},
        ):
            out = prune_presence_run_snapshots(
                cursor,
                3,
                portal_status="at_vendor",
                rinse_vendor="veewash",
                keep_latest=KEEP_LATEST_SUCCESSFUL_SNAPSHOTS,
            )
        assert out["runs_before"] == 5
        assert out["kept_run_ids"] == [100, 101, 102]
