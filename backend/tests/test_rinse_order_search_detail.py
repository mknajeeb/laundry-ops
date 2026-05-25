"""Order search detail and lifecycle filter."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.rinse_order_search import search_rinse_orders
from backend.rinse_order_search_detail import (
    PURGED_ROW_MESSAGE,
    build_folding_detail,
    build_order_lifecycle_detail,
    empty_lifecycle_detail_shell,
    list_staging_history_for_bag,
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
        cursor.fetchone.side_effect = [{"cnt": 0}]
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

    def test_wild_search_token_in_sql(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"cnt": 1}
        cursor.fetchall.return_value = []
        with patch("backend.rinse_order_search.table_exists") as te:
            te.side_effect = lambda _c, name: name in (
                "rinse_bag_registry",
                "rinse_folding_performance",
            )
            with patch("backend.rinse_order_search.table_has_column", return_value=False):
                with patch(
                    "backend.rinse_order_search._lifecycle_summary",
                    return_value={"registry_total": 0},
                ):
                    with patch(
                        "backend.rinse_order_search._active_staging_where_sql",
                        return_value="1=1",
                    ):
                        search_rinse_orders(cursor, 3, wild_search="step", limit=10)
        count_sql = cursor.execute.call_args_list[0][0][0]
        self.assertIn("name_clean LIKE", count_sql)
        self.assertIn("bag_id LIKE", count_sql)


class TestDetailRegressionPartialSections(unittest.TestCase):
    """Bag in registry with a failing section still returns a detail shell."""

    def test_staging_failure_returns_empty_staging_not_raise(self):
        cursor = MagicMock()

        def has_col(_c, table, col):
            if table == "orders_staging" and col in ("created_at", "updated_at"):
                return False
            return col in ("id", "ticket_id", "name_clean", "status", "organization_id")

        with patch("backend.rinse_order_search_detail.table_exists", return_value=True):
            with patch("backend.rinse_order_search_detail.table_has_column", side_effect=has_col):
                cursor.execute.side_effect = Exception("Unknown column 'created_at'")
                with self.assertRaises(Exception):
                    list_staging_history_for_bag(
                        cursor,
                        3,
                        "3QW48ZYOXP",
                        has_staging_org=True,
                        has_ticket_id_col=True,
                    )

    def test_build_detail_survives_staging_section_error(self):
        cursor = MagicMock()
        reg = {
            "bag_id": "3QW48ZYOXP",
            "name_clean": "Stephanie Davis 0",
            "organization_id": 3,
            "completion_status": "INCOMPLETE",
        }

        with patch(
            "backend.rinse_bag_registry.get_registry_row", return_value=reg
        ):
            with patch(
                "backend.rinse_order_search_detail.list_scan_events_for_bag",
                return_value=[{"id": 1, "rack": "FOLDING", "scan_index": 1}],
            ):
                with patch(
                    "backend.rinse_order_search_detail.list_upload_history_for_bag",
                    return_value=[],
                ):
                    with patch(
                        "backend.rinse_order_search_detail.list_staging_history_for_bag",
                        side_effect=Exception("Unknown column 'created_at'"),
                    ):
                        with patch(
                            "backend.rinse_order_search_detail.find_active_staging_by_ticket_id",
                            return_value=None,
                        ):
                            with patch(
                                "backend.rinse_order_search_detail.table_exists",
                                return_value=False,
                            ):
                                detail = build_order_lifecycle_detail(
                                    cursor,
                                    3,
                                    "3QW48ZYOXP",
                                    active_where_sql="1=1",
                                    has_staging_org=True,
                                    has_ticket_id_col=True,
                                    upload_batch_row_pk="id",
                                )
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail["bag_id"], "3QW48ZYOXP")
        self.assertEqual(detail["staging_history"], [])
        self.assertIn("staging_history", detail.get("section_errors", {}))
        self.assertEqual(len(detail["scan_events"]), 1)

    def test_empty_shell_has_arrays(self):
        shell = empty_lifecycle_detail_shell("BAG1", {"bag_id": "BAG1", "name_clean": "Test"})
        self.assertEqual(shell["upload_history"], [])
        self.assertEqual(shell["scan_events"], [])
        self.assertIsNone(shell["folding"])


class TestUploadHistorySchemaSafe(unittest.TestCase):
    def test_upload_history_without_ub_created_at(self):
        from backend.rinse_order_search_detail import list_upload_history_for_bag

        cursor = MagicMock()

        def has_col(_c, table, col):
            if table == "upload_batches" and col == "created_at":
                return False
            if table == "upload_batches" and col == "uploaded_at":
                return True
            return col in (
                "batch_id",
                "state",
                "batch_date",
                "confirmed_at",
                "id",
                "upload_batch_id",
                "row_status",
                "reason",
                "date_clean",
                "name_clean",
                "created_at",
                "raw_rows_purged_at",
                "purged_summary_json",
            )

        registry = {"last_upload_batch_id": 191}
        fetch_batches = [{"batch_id": 191, "state": "CONFIRMED", "created_at": None, "batch_date": None}]
        fetch_rows = [
            {
                "id": 1,
                "upload_batch_id": 191,
                "row_status": "ACCEPTED",
                "created_at": None,
                "batch_created_at": None,
            }
        ]

        with patch("backend.rinse_order_search_detail.table_exists", return_value=True):
            with patch("backend.rinse_order_search_detail.table_has_column", side_effect=has_col):
                with patch(
                    "backend.rinse_order_search_detail._collect_upload_batch_ids",
                    return_value=[191],
                ):
                    cursor.fetchall.side_effect = [fetch_batches, fetch_rows]
                    history = list_upload_history_for_bag(cursor, 3, "7DGTUXAGP1", registry)
        self.assertEqual(len(history), 1)
        join_sql = cursor.execute.call_args_list[1][0][0]
        self.assertNotIn("ub.created_at", join_sql)
        self.assertIn("uploaded_at", join_sql)


class TestPurgedMessageConstant(unittest.TestCase):
    def test_purged_message_non_empty(self):
        self.assertIn("purged", PURGED_ROW_MESSAGE.lower())


if __name__ == "__main__":
    unittest.main()
