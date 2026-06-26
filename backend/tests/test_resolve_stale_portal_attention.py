"""Tests for stale portal attention row resolution before batch confirm."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.manual_checkout_eligibility import resolve_stale_portal_attention_rows_before_confirm
from backend.rinse_bag_completion import REASON_ALREADY_COMPLETED


class TestResolveStalePortalAttentionRows(unittest.TestCase):
    def test_downgrades_completed_bag_blocking_attention(self):
        cursor = MagicMock()
        cursor.fetchall.side_effect = [
            [{"row_pk": 99, "ticket_id": "92OFXZWFZN"}],
        ]
        with patch(
            "backend.rinse_bag_registry.is_bag_already_completed",
            return_value=True,
        ), patch(
            "backend.ta_helpers.table_exists",
            return_value=True,
        ), patch(
            "backend.ta_helpers.table_has_column",
            side_effect=lambda _c, table, col: col in ("upload_batch_id", "id"),
        ):
            out = resolve_stale_portal_attention_rows_before_confirm(cursor, 3, 1441)
        self.assertEqual(out["resolved_count"], 1)
        self.assertEqual(out["resolved_bag_ids"], ["92OFXZWFZN"])
        update_sql = cursor.execute.call_args_list[-1][0][0]
        self.assertIn("UPDATE upload_batch_rows", update_sql)
        self.assertEqual(
            cursor.execute.call_args_list[-1][0][1],
            ("REJECTED_DUPLICATE", REASON_ALREADY_COMPLETED, 99),
        )

    def test_leaves_incomplete_attention_rows(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [{"row_pk": 1, "ticket_id": "PENDING1"}]
        with patch(
            "backend.rinse_bag_registry.is_bag_already_completed",
            return_value=False,
        ), patch(
            "backend.ta_helpers.table_exists",
            return_value=True,
        ), patch(
            "backend.ta_helpers.table_has_column",
            side_effect=lambda _c, table, col: col in ("upload_batch_id", "id"),
        ):
            out = resolve_stale_portal_attention_rows_before_confirm(cursor, 3, 1441)
        self.assertEqual(out["resolved_count"], 0)
        self.assertEqual(out["resolved_bag_ids"], [])
