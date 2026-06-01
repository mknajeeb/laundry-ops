"""Operations dashboard summary and folding exception bulk actions."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_folding_review import (
    BULK_ACTION_APPROVE_SCORING,
    BULK_ACTION_EXCLUDE_SCORING,
    BULK_ACTION_MARK_REVIEWED,
    bulk_folding_exceptions_action,
)
from backend.rinse_operations_dashboard import get_operations_dashboard_summary


class TestOperationsDashboardSummary(unittest.TestCase):
    def test_counts_rush_and_completion_from_registry_rows(self):
        cursor = MagicMock()
        registry_rows = [
            {
                "bag_id": "A1",
                "service_type": "WF",
                "effective_rush": "RUSH",
                "is_completed": 1,
            },
            {
                "bag_id": "A2",
                "service_type": "WF",
                "effective_rush": "RUSH",
                "is_completed": 0,
            },
            {
                "bag_id": "A3",
                "service_type": "HD",
                "effective_rush": "NON-RUSH",
                "is_completed": 1,
            },
        ]

        def fake_execute(sql, args=None):
            s = " ".join(sql.split())
            if "FROM rinse_bag_registry r" in s and "is_completed" in s:
                cursor.fetchall.return_value = registry_rows
            elif "FROM orders_staging s" in s and "NOT EXISTS" in s:
                cursor.fetchall.return_value = []
            elif "COUNT(*) AS cnt" in s and "orders_staging" in s:
                cursor.fetchone.return_value = {"cnt": 5}
            elif "rinse_folding_performance" in s:
                cursor.fetchone.return_value = {"cnt": 2}

        cursor.execute.side_effect = fake_execute

        with patch("backend.rinse_operations_dashboard.table_exists", return_value=True), patch(
            "backend.rinse_operations_dashboard.table_has_column", return_value=True
        ), patch("backend.rinse_bag_registry.ensure_rinse_bag_registry_table"):
            out = get_operations_dashboard_summary(
                cursor, 3, target_date=date(2026, 5, 26)
            )

        self.assertEqual(out["total_orders"], 3)
        self.assertEqual(out["rush_total"], 2)
        self.assertEqual(out["non_rush_total"], 1)
        self.assertEqual(out["completed_total"], 2)
        self.assertEqual(out["remaining_total"], 1)
        self.assertEqual(out["rush_completed"], 1)
        self.assertEqual(out["rush_remaining"], 1)
        self.assertEqual(out["non_rush_completed"], 1)
        self.assertEqual(out["non_rush_remaining"], 0)
        self.assertEqual(out["wf_total"], 2)
        self.assertEqual(out["wf_completed"], 1)
        self.assertEqual(out["wf_remaining"], 1)

    def test_registry_only_still_works_without_upload_batch_rows(self):
        """Summary must not require upload_batch_rows (purged raw rows)."""
        cursor = MagicMock()

        def fake_execute(sql, args=None):
            s = " ".join(sql.split())
            if "FROM rinse_bag_registry r" in s:
                cursor.fetchall.return_value = [
                    {
                        "bag_id": "ONLYREG",
                        "service_type": "WF",
                        "effective_rush": "NON-RUSH",
                        "is_completed": 0,
                    }
                ]
            elif "NOT EXISTS" in s and "orders_staging" in s:
                cursor.fetchall.return_value = []
            elif "orders_staging" in s and "COUNT" in s:
                cursor.fetchone.return_value = {"cnt": 0}
            elif "rinse_folding_performance" in s:
                cursor.fetchone.return_value = {"cnt": 0}

        cursor.execute.side_effect = fake_execute

        with patch("backend.rinse_operations_dashboard.table_exists", return_value=True), patch(
            "backend.rinse_operations_dashboard.table_has_column", return_value=True
        ), patch("backend.rinse_bag_registry.ensure_rinse_bag_registry_table"):
            out = get_operations_dashboard_summary(
                cursor, 3, target_date=date(2026, 5, 26)
            )

        self.assertEqual(out["total_orders"], 1)
        self.assertEqual(out["remaining_total"], 1)
        self.assertEqual(out["source"], "registry+staging")


class TestBulkFoldingExceptions(unittest.TestCase):
    def _row(self, **extra):
        base = {
            "id": 10,
            "bag_id": "BAG1",
            "status": "EXCEPTION",
            "exception_code": "FOLDING_DURATION_TOO_SHORT",
            "scoring_status": "EXCEPTION",
            "included_in_scoring": 0,
            "reviewed_at": None,
        }
        base.update(extra)
        return base

    @patch("backend.rinse_folding_review.get_folding_performance_row")
    @patch("backend.rinse_folding_review.ensure_rinse_folding_tables")
    def test_bulk_approve_updates_multiple(self, _ensure, mock_get):
        cursor = MagicMock()
        mock_get.side_effect = lambda c, o, b: self._row(bag_id=b)

        out = bulk_folding_exceptions_action(
            cursor,
            3,
            ["BAG1", "BAG2"],
            action=BULK_ACTION_APPROVE_SCORING,
            actor_user_id=1,
            note="bulk ok",
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["updated"], 2)
        self.assertEqual(out["requested"], 2)
        self.assertGreaterEqual(cursor.execute.call_count, 4)

    @patch("backend.rinse_folding_review.get_folding_performance_row")
    @patch("backend.rinse_folding_review.ensure_rinse_folding_tables")
    def test_bulk_mark_reviewed_preserves_scoring(self, _ensure, mock_get):
        cursor = MagicMock()
        row = self._row(scoring_status="EXCEPTION", included_in_scoring=0)
        mock_get.return_value = row

        bulk_folding_exceptions_action(
            cursor,
            3,
            ["BAG1"],
            action=BULK_ACTION_MARK_REVIEWED,
            actor_user_id=1,
            note="seen",
        )
        update_sql = " ".join(
            str(c[0][0]) for c in cursor.execute.call_args_list if c[0]
        )
        self.assertIn("reviewed_at", update_sql)
        self.assertNotIn("scoring_status =", update_sql.replace("scoring_status", "", 1))

    @patch("backend.rinse_folding_review.get_folding_performance_row")
    @patch("backend.rinse_folding_review.ensure_rinse_folding_tables")
    def test_bulk_partial_failure_returns_results(self, _ensure, mock_get):
        cursor = MagicMock()

        def get_row(c, o, b):
            if b == "MISSING":
                return None
            return self._row(bag_id=b)

        mock_get.side_effect = get_row

        out = bulk_folding_exceptions_action(
            cursor,
            3,
            ["BAG1", "MISSING"],
            action=BULK_ACTION_EXCLUDE_SCORING,
            actor_user_id=1,
            note="bulk ex",
        )
        self.assertEqual(out["updated"], 1)
        self.assertEqual(out["skipped"], 1)
        self.assertEqual(len(out["results"]), 2)
        self.assertTrue(any(not r.get("ok") for r in out["results"]))

    @patch("backend.rinse_folding_review._log_review_action")
    @patch("backend.rinse_folding_review.get_folding_performance_row")
    @patch("backend.rinse_folding_review.ensure_rinse_folding_tables")
    def test_bulk_writes_audit(self, _ensure, mock_get, mock_audit):
        cursor = MagicMock()
        mock_get.return_value = self._row()
        bulk_folding_exceptions_action(
            cursor,
            3,
            ["BAG1"],
            action=BULK_ACTION_APPROVE_SCORING,
            actor_user_id=9,
            note="audit test",
        )
        mock_audit.assert_called()
        self.assertTrue(mock_audit.call_args[1].get("action_type"))


if __name__ == "__main__":
    unittest.main()
