"""Tests for GET /dashboard active staging snapshot."""

from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_dashboard_staging import (
    build_dashboard_vs_monitor_reconciliation,
    get_dashboard_active_staging_snapshot,
)


class TestDashboardActiveStaging:
    def test_active_staging_matches_dashboard_aggregates(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "total_orders": 4,
            "batch_date": date(2026, 6, 7),
            "wf_total": 3,
            "hd_total": 1,
            "wf_rush": 2,
            "wf_non_rush": 1,
            "hd_rush": 0,
            "hd_non_rush": 1,
        }
        cursor.fetchall.return_value = [
            {"bag_id": "R1", "service_type": "WF", "effective_rush": "RUSH", "name_clean": "A"},
            {"bag_id": "R2", "service_type": "WF", "effective_rush": "RUSH", "name_clean": "B"},
            {"bag_id": "N1", "service_type": "WF", "effective_rush": "NON-RUSH", "name_clean": "C"},
            {"bag_id": "H1", "service_type": "HD", "effective_rush": "NON-RUSH", "name_clean": "D"},
        ]
        with patch("backend.rinse_dashboard_staging.table_exists", return_value=True), patch(
            "backend.rinse_dashboard_staging.table_has_column", return_value=True
        ):
            out = get_dashboard_active_staging_snapshot(cursor, 1)

        assert out["total_orders"] == 4
        assert out["wf_rush"] == 2
        assert out["hd_non_rush"] == 1
        assert out["unique_bag_count"] == 4
        assert out["rush_wf_ids"] == ["R1", "R2"]
        assert out["nonrush_wf_ids"] == ["N1"]
        assert out["nonrush_hd_ids"] == ["H1"]

    def test_duplicate_staging_rows_deduped_for_bag_ids(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "total_orders": 2,
            "batch_date": None,
            "wf_total": 2,
            "hd_total": 0,
            "wf_rush": 2,
            "wf_non_rush": 0,
            "hd_rush": 0,
            "hd_non_rush": 0,
        }
        cursor.fetchall.return_value = [
            {"bag_id": "DUP", "service_type": "WF", "effective_rush": "RUSH", "name_clean": "A"},
            {"bag_id": "DUP", "service_type": "WF", "effective_rush": "RUSH", "name_clean": "A"},
        ]
        with patch("backend.rinse_dashboard_staging.table_exists", return_value=True), patch(
            "backend.rinse_dashboard_staging.table_has_column", return_value=True
        ):
            out = get_dashboard_active_staging_snapshot(cursor, 1)

        assert out["total_orders"] == 2
        assert out["unique_bag_count"] == 1
        assert out["duplicate_staging_rows"] == 1

    def test_dashboard_vs_monitor_reconciliation(self):
        dashboard = {
            "total_orders": 3,
            "unique_bag_ids": ["A", "B", "C"],
            "rush_wf_ids": ["A"],
            "rush_hd_ids": [],
            "nonrush_wf_ids": ["B"],
            "nonrush_hd_ids": ["C"],
            "unknown_ids": [],
            "source": "GET /dashboard orders_staging",
        }
        monitor = {"total": 3}
        rec = build_dashboard_vs_monitor_reconciliation(dashboard, monitor, monitor_bag_ids=["A", "B"])
        assert rec["match"] is True
        assert rec["bag_ids_in_dashboard_not_monitor"] == ["C"]
        assert rec["bag_ids_in_monitor_not_dashboard"] == []
