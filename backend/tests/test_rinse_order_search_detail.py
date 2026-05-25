"""Order search detail and lifecycle filter."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.rinse_order_search import search_rinse_orders
from backend.rinse_order_search_detail import (
    PURGED_ROW_MESSAGE,
    build_folding_detail,
    build_order_lifecycle_detail,
)


class TestFoldingDetailExplanation(unittest.TestCase):
    def test_multiple_clean_scans_warning_included_in_scoring(self):
        perf = {
            "status": "CALCULATED",
            "exception_code": "MULTIPLE_CLEAN_SCANS",
            "excluded_from_performance": 0,
            "folding_start_event_id": 10,
            "folding_end_event_id": 20,
            "duration_seconds": 3600,
            "weight_lbs": 12.5,
            "folding_scan_count": 1,
            "clean_scan_count": 2,
        }
        events = [
            {"id": 10, "rack": "FOLDING", "scan_index": 1, "purpose": "fold"},
            {"id": 15, "rack": "CLEAN", "scan_index": 2, "purpose": "clean"},
            {"id": 20, "rack": "CLEAN", "scan_index": 3, "purpose": "clean"},
        ]
        detail = build_folding_detail(perf, events)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertTrue(detail["included_in_scoring"])
        self.assertTrue(detail["warning_only"])
        self.assertEqual(detail["exception_code"], "MULTIPLE_CLEAN_SCANS")
        self.assertIn("CLEAN rack scan", detail["plain_english_reason"])
        self.assertEqual(len(detail["scans_used_for_calculation"]), 2)
        self.assertEqual(detail["lbs_per_hour"], 12.5)

    def test_exception_not_in_scoring(self):
        perf = {
            "status": "EXCEPTION",
            "exception_code": "MISSING_FOLDING",
            "excluded_from_performance": 0,
        }
        detail = build_folding_detail(perf, [])
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertFalse(detail["included_in_scoring"])


class TestOrderSearchLifecycleFilter(unittest.TestCase):
    def test_lifecycle_filter_completed_adds_where(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {"cnt": 0},
        ]
        cursor.fetchall.return_value = []
        with patch("backend.rinse_order_search.table_exists") as te:
            te.side_effect = lambda _c, name: name == "rinse_bag_registry"
            with patch("backend.rinse_order_search.table_has_column", return_value=False):
                with patch(
                    "backend.rinse_order_search._lifecycle_summary",
                    return_value={"registry_total": 0},
                ):
                    with patch(
                        "backend.rinse_order_search._active_staging_where_sql",
                        return_value="1=1",
                    ):
                        search_rinse_orders(
                            cursor, 3, lifecycle_filter="completed", limit=10
                        )
        count_args = cursor.execute.call_args_list[0][0][1]
        self.assertIn("COMPLETED", count_args)


class TestPurgedMessageConstant(unittest.TestCase):
    def test_purged_message_non_empty(self):
        self.assertIn("purged", PURGED_ROW_MESSAGE.lower())


if __name__ == "__main__":
    unittest.main()
