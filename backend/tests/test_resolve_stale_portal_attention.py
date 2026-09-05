"""Tests for stale portal attention row resolution / isolation before batch confirm."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, call, patch

from backend.manual_checkout_eligibility import (
    REASON_ISOLATED_OLDER_THAN_BATCH_DATE,
    REASON_OLDER_THAN_BATCH_DATE,
    isolate_nonblocking_older_than_batch_date_attention_rows,
    resolve_stale_portal_attention_rows_before_confirm,
)
from backend.rinse_bag_completion import REASON_ALREADY_COMPLETED, ROW_REJECTED


def _column_side_effect(_c, table, col):
    return col in ("upload_batch_id", "id")


class TestResolveStalePortalAttentionRows(unittest.TestCase):
    def test_downgrades_completed_bag_blocking_attention(self):
        cursor = MagicMock()
        # Phase 1 select (ticketed OLDER) → Phase 2 isolate select (none left)
        cursor.fetchall.side_effect = [
            [{"row_pk": 99, "ticket_id": "92OFXZWFZN"}],
            [],
        ]
        with patch(
            "backend.rinse_bag_registry.is_bag_already_completed",
            return_value=True,
        ), patch(
            "backend.ta_helpers.table_exists",
            return_value=True,
        ), patch(
            "backend.ta_helpers.table_has_column",
            side_effect=_column_side_effect,
        ):
            out = resolve_stale_portal_attention_rows_before_confirm(cursor, 3, 1441)
        self.assertEqual(out["resolved_count"], 1)
        self.assertEqual(out["resolved_bag_ids"], ["92OFXZWFZN"])
        self.assertEqual(out["isolated_count"], 0)
        update_sql = cursor.execute.call_args_list[1][0][0]
        self.assertIn("UPDATE upload_batch_rows", update_sql)
        self.assertEqual(
            cursor.execute.call_args_list[1][0][1],
            (ROW_REJECTED, REASON_ALREADY_COMPLETED, 99),
        )

    def test_isolates_older_than_when_current_oi_open(self):
        """Stale portal date + open current OI: isolate; do not claim ALREADY_COMPLETED."""
        cursor = MagicMock()
        cursor.fetchall.side_effect = [
            [{"row_pk": 7, "ticket_id": "2HCJP6S8FL"}],
            [{"row_pk": 7, "ticket_id": "2HCJP6S8FL", "reason": REASON_OLDER_THAN_BATCH_DATE}],
        ]
        with patch(
            "backend.rinse_bag_registry.is_bag_already_completed",
            return_value=False,
        ) as completed_fn, patch(
            "backend.ta_helpers.table_exists",
            return_value=True,
        ), patch(
            "backend.ta_helpers.table_has_column",
            side_effect=_column_side_effect,
        ):
            out = resolve_stale_portal_attention_rows_before_confirm(cursor, 3, 5900)
        self.assertEqual(out["resolved_count"], 0)
        self.assertEqual(out["isolated_count"], 1)
        self.assertEqual(out["isolated_ticket_ids"], ["2HCJP6S8FL"])
        completed_fn.assert_called()
        # Isolation update uses ISOLATED reason — never mutates OI tables
        oi_writes = [
            c
            for c in cursor.execute.call_args_list
            if "rinse_order_instances" in str(c[0][0]).lower()
            or "rinse_wf_current_workload" in str(c[0][0]).lower()
        ]
        self.assertEqual(oi_writes, [])
        last_params = cursor.execute.call_args_list[-1][0][1]
        self.assertEqual(
            last_params,
            (
                ROW_REJECTED,
                REASON_ISOLATED_OLDER_THAN_BATCH_DATE,
                7,
                REASON_OLDER_THAN_BATCH_DATE,
            ),
        )

    def test_isolates_null_ticket_older_than_without_fabricated_identity(self):
        cursor = MagicMock()
        cursor.fetchall.side_effect = [
            [],  # phase 1: no ticketed rows
            [{"row_pk": 55, "ticket_id": None, "reason": REASON_OLDER_THAN_BATCH_DATE}],
        ]
        with patch(
            "backend.rinse_bag_registry.is_bag_already_completed",
        ) as completed_fn, patch(
            "backend.ta_helpers.table_exists",
            return_value=True,
        ), patch(
            "backend.ta_helpers.table_has_column",
            side_effect=_column_side_effect,
        ):
            out = resolve_stale_portal_attention_rows_before_confirm(cursor, 3, 5901)
        self.assertEqual(out["resolved_count"], 0)
        self.assertEqual(out["isolated_count"], 1)
        self.assertEqual(out["isolated_null_ticket_rows"], 1)
        self.assertEqual(out["isolated_ticket_ids"], [])
        completed_fn.assert_not_called()
        last_params = cursor.execute.call_args_list[-1][0][1]
        self.assertEqual(last_params[1], REASON_ISOLATED_OLDER_THAN_BATCH_DATE)

    def test_isolate_helper_only_targets_older_than_reason(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        with patch("backend.ta_helpers.table_exists", return_value=True), patch(
            "backend.ta_helpers.table_has_column",
            side_effect=_column_side_effect,
        ):
            out = isolate_nonblocking_older_than_batch_date_attention_rows(cursor, 3, 1)
        self.assertEqual(out["isolated_count"], 0)
        sel = cursor.execute.call_args_list[0][0]
        self.assertIn("NEEDS_ATTENTION", sel[0])
        self.assertEqual(sel[1], (1, REASON_OLDER_THAN_BATCH_DATE))


class TestConfirmGateIsolationSemantics(unittest.TestCase):
    def test_valid_rows_plus_one_older_than_isolates_and_clears_attention(self):
        """238 ACCEPTED + 1 OLDER_THAN → isolate → attention count 0 → confirm allowed."""
        cursor = MagicMock()
        # resolve phase1 empty completed; phase2 isolates the one OLDER row
        cursor.fetchall.side_effect = [
            [],
            [{"row_pk": 901, "ticket_id": "2HCJP6S8FL", "reason": REASON_OLDER_THAN_BATCH_DATE}],
        ]
        # After isolation, attention recount used by confirm path
        attention_after = {"attention_count": 0}

        def _fetchone():
            return attention_after

        cursor.fetchone.side_effect = _fetchone

        with patch(
            "backend.rinse_bag_registry.is_bag_already_completed",
            return_value=False,
        ), patch(
            "backend.ta_helpers.table_exists",
            return_value=True,
        ), patch(
            "backend.ta_helpers.table_has_column",
            side_effect=_column_side_effect,
        ):
            out = resolve_stale_portal_attention_rows_before_confirm(cursor, 3, 5902)

        self.assertEqual(out["isolated_count"], 1)
        self.assertEqual(out["isolated_ticket_ids"], ["2HCJP6S8FL"])

        # Simulate confirm gate recount
        cursor.execute(
            """
            SELECT COUNT(*) AS attention_count
            FROM upload_batch_rows
            WHERE upload_batch_id = %s
            AND row_status = 'NEEDS_ATTENTION'
            """,
            (5902,),
        )
        attention_count = int((cursor.fetchone() or {}).get("attention_count", 0) or 0)
        self.assertEqual(attention_count, 0)

    def test_unsafe_needs_attention_reason_still_blocks(self):
        """Non-OLDER NEEDS_ATTENTION must remain NEEDS_ATTENTION (blocking)."""
        cursor = MagicMock()
        cursor.fetchall.side_effect = [
            [],  # no OLDER ticketed for phase 1
            [],  # no OLDER for isolate
        ]
        with patch(
            "backend.ta_helpers.table_exists",
            return_value=True,
        ), patch(
            "backend.ta_helpers.table_has_column",
            side_effect=_column_side_effect,
        ):
            out = resolve_stale_portal_attention_rows_before_confirm(cursor, 3, 5903)
        self.assertEqual(out["isolated_count"], 0)
        # Isolation SELECT is scoped to OLDER_THAN only — other reasons never UPDATEd
        update_calls = [
            c for c in cursor.execute.call_args_list if "UPDATE upload_batch_rows" in c[0][0]
        ]
        self.assertEqual(update_calls, [])

        # Confirm gate still sees blocking attention for a different reason
        cursor2 = MagicMock()
        cursor2.fetchone.return_value = {"attention_count": 1}
        cursor2.execute(
            """
            SELECT COUNT(*) AS attention_count
            FROM upload_batch_rows
            WHERE upload_batch_id = %s
            AND row_status = 'NEEDS_ATTENTION'
            """,
            (5903,),
        )
        attention_count = int((cursor2.fetchone() or {}).get("attention_count", 0) or 0)
        self.assertEqual(attention_count, 1)
        self.assertGreater(attention_count, 0)  # still blocks auto-confirm

    def test_already_completed_reject_path_unchanged(self):
        cursor = MagicMock()
        cursor.fetchall.side_effect = [
            [{"row_pk": 11, "ticket_id": "DONEBAG1"}],
            [],
        ]
        with patch(
            "backend.rinse_bag_registry.is_bag_already_completed",
            return_value=True,
        ), patch(
            "backend.ta_helpers.table_exists",
            return_value=True,
        ), patch(
            "backend.ta_helpers.table_has_column",
            side_effect=_column_side_effect,
        ):
            out = resolve_stale_portal_attention_rows_before_confirm(cursor, 3, 5904)
        self.assertEqual(out["resolved_count"], 1)
        self.assertEqual(out["isolated_count"], 0)
        self.assertEqual(
            cursor.execute.call_args_list[1][0][1],
            (ROW_REJECTED, REASON_ALREADY_COMPLETED, 11),
        )


if __name__ == "__main__":
    unittest.main()
