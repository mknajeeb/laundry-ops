"""Tests for presence snapshot retention (retain-all authoritative evidence)."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_presence_snapshot_retention import (
    RETENTION_POLICY,
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
    def test_protects_all_successful_runs(self):
        cursor = MagicMock()
        runs = _runs(5)
        with patch(
            "backend.rinse_presence_snapshot_retention._list_successful_presence_runs",
            return_value=runs,
        ):
            keep = resolve_protected_presence_run_ids(
                cursor, 3, portal_status="at_vendor", selected_date_et=date(2026, 6, 13)
            )
        assert keep == {100, 101, 102, 103, 104}

    def test_prune_is_retain_all_noop(self):
        cursor = MagicMock()
        runs = _runs(5)
        with patch(
            "backend.rinse_presence_snapshot_retention.table_exists",
            return_value=True,
        ), patch(
            "backend.rinse_presence_snapshot_retention._list_successful_presence_runs",
            return_value=runs,
        ):
            out = prune_presence_run_snapshots(
                cursor,
                3,
                portal_status="at_vendor",
                rinse_vendor="veewash",
            )
        assert out["policy"] == RETENTION_POLICY
        assert out["runs_before"] == 5
        assert out["kept_run_ids"] == [100, 101, 102, 103, 104]
        assert out["pruned_run_ids"] == []
        assert out["deleted_run_rows"] == 0
        assert out["deleted_runs"] == 0
        cursor.execute.assert_not_called()
