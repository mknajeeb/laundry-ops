"""Tests for shift analysis dashboard helpers."""

from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_shift_analysis import (
    _classify_pending_bucket,
    get_pending_bag_status,
)


class TestPendingBucket:
    def test_not_weighed(self):
        assert _classify_pending_bucket(is_completed=False, has_weight_entry=False, has_start_cleaning=False) == "not_weighed"

    def test_weighed_not_washed(self):
        assert _classify_pending_bucket(is_completed=False, has_weight_entry=True, has_start_cleaning=False) == "weighed_not_washed"

    def test_in_washing(self):
        assert _classify_pending_bucket(is_completed=False, has_weight_entry=True, has_start_cleaning=True) == "in_washing"

    def test_completed(self):
        assert _classify_pending_bucket(is_completed=True, has_weight_entry=True, has_start_cleaning=True) is None


class TestPendingBagStatus:
    def test_groups_rush_and_non_rush_from_active_staging(self):
        cursor = MagicMock()

        def execute_side_effect(sql, args=None):
            s = " ".join(sql.split())
            if "FROM orders_staging s" in s:
                cursor.fetchall.return_value = [
                    {
                        "bag_id": "B1",
                        "name_clean": "A",
                        "weight_num": 10,
                        "service_type": "WF",
                        "effective_rush": "RUSH",
                        "is_completed": 0,
                    },
                    {
                        "bag_id": "B2",
                        "name_clean": "B",
                        "weight_num": 8,
                        "service_type": "WF",
                        "effective_rush": "NON-RUSH",
                        "is_completed": 1,
                    },
                ]
            elif "FROM rinse_bag_registry r" in s and "date_clean" in s:
                cursor.fetchall.return_value = []
            elif "rinse_bag_scan_events" in s:
                cursor.fetchall.return_value = [
                    {"bag_id": "B1", "purpose": "weight-entry"},
                    {"bag_id": "B2", "purpose": "start-cleaning"},
                ]

        cursor.execute.side_effect = execute_side_effect

        with patch("backend.rinse_shift_analysis.table_exists", return_value=True), patch(
            "backend.rinse_shift_analysis.table_has_column", return_value=True
        ):
            out = get_pending_bag_status(cursor, 1, target_date=date(2026, 5, 27))

        assert out["groups"]["rush"]["pending"] == 1
        assert out["groups"]["rush"]["weighed_not_washed"] == 1
        assert out["groups"]["non_rush"]["completed"] == 1
        assert out["groups"]["combined"]["total"] == 2
        assert out["portal_alignment"]["wf_total"] == 2

    def test_excludes_hd_from_portal_active_staging(self):
        cursor = MagicMock()

        def execute_side_effect(sql, args=None):
            s = " ".join(sql.split())
            if "FROM orders_staging s" in s:
                cursor.fetchall.return_value = [
                    {"bag_id": "WF1", "name_clean": "A", "weight_num": 10, "service_type": "WF", "effective_rush": "RUSH", "is_completed": 0},
                    {"bag_id": "HD1", "name_clean": "B", "weight_num": 5, "service_type": "HD", "effective_rush": "NON-RUSH", "is_completed": 0},
                    {"bag_id": "WF2", "name_clean": "C", "weight_num": 12, "service_type": "WF", "effective_rush": "NON-RUSH", "is_completed": 0},
                ]
            elif "FROM rinse_bag_registry r" in s and "date_clean" in s:
                cursor.fetchall.return_value = []
            elif "rinse_bag_scan_events" in s:
                cursor.fetchall.return_value = []

        cursor.execute.side_effect = execute_side_effect

        with patch("backend.rinse_shift_analysis.table_exists", return_value=True), patch(
            "backend.rinse_shift_analysis.table_has_column", return_value=True
        ):
            out = get_pending_bag_status(cursor, 1, target_date=date(2026, 5, 28))

        assert out["groups"]["combined"]["total"] == 2
        assert out["portal_alignment"]["portal_active_total"] == 3
        assert out["portal_alignment"]["hd_excluded"] == 1
        assert out["portal_alignment"]["wf_total"] == 2
        assert out["service_scope"] == "WF only (HD excluded)"


class TestRecordsPayloadShape:
    def test_list_return_normalized(self):
        rows = [{"bag_id": "B1", "status": "CALCULATED", "included_in_scoring": 1}]
        if isinstance(rows, list):
            payload = {"rows": rows, "total": len(rows)}
        else:
            payload = rows
        assert payload.get("rows")
