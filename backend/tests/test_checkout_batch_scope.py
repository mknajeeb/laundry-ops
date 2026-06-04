"""Tests for checkout batch scoping and manual batch staging reapply."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from backend.checkout_batch_scope import (
    batch_accepted_ticket_ids,
    reapply_checkout_batch_staging,
)


class TestCheckoutBatchScope(unittest.TestCase):
    def test_batch_accepted_ticket_ids_normalizes(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {"ticket_id": " abc123 "},
            {"ticket_id": "WXYZ"},
            {"ticket_id": ""},
        ]
        with patch(
            "backend.checkout_batch_scope._row_batch_col", return_value="upload_batch_id"
        ), patch("backend.checkout_batch_scope.table_exists", return_value=True):
            ids = batch_accepted_ticket_ids(cursor, 551)
        self.assertEqual(ids, {"ABC123", "WXYZ"})

    def test_reapply_works_for_auto_scrape_batch(self):
        cursor = MagicMock()
        row = {
            "date_clean": date(2026, 6, 2),
            "name_clean": "Auto Bag",
            "weight_num": 5,
            "service_type": "WF",
            "rush_type": "NON-RUSH",
            "ticket_id": "AUTO12345",
        }
        cursor.fetchone.return_value = {"batch_id": 585, "batch_date": date(2026, 6, 2)}
        cursor.fetchall.return_value = [row]
        cursor.lastrowid = 9002

        with patch(
            "backend.checkout_batch_scope._row_batch_col", return_value="upload_batch_id"
        ), patch("backend.checkout_batch_scope.table_exists", return_value=True), patch(
            "backend.checkout_batch_scope.table_has_column", return_value=True
        ), patch(
            "backend.rinse_bag_upload.find_staging_by_ticket_id", return_value=None
        ), patch(
            "backend.rinse_bag_upload.update_staging_from_upload_row"
        ):
            out = reapply_checkout_batch_staging(cursor, 3, 585, dry_run=True)

        self.assertEqual(out["inserted"], 1)
        self.assertEqual(out["updated"], 0)

    def test_reapply_updates_sent_staging(self):
        cursor = MagicMock()
        row = {
            "date_clean": date(2026, 6, 2),
            "name_clean": "Nina Holloway",
            "weight_num": 0,
            "service_type": "WF",
            "rush_type": "RUSH",
            "ticket_id": "05X9GTM0CN",
        }
        cursor.fetchone.return_value = {"batch_id": 551, "batch_date": date(2026, 6, 2)}
        cursor.fetchall.side_effect = [
            [row],
        ]
        cursor.lastrowid = 9001

        cap = {
            "has_ticket_id": True,
            "has_logistics": True,
            "has_processing": True,
            "has_status": True,
        }
        existing = {"id": 42}

        with patch(
            "backend.checkout_batch_scope._row_batch_col", return_value="upload_batch_id"
        ), patch("backend.checkout_batch_scope.table_exists", return_value=True), patch(
            "backend.checkout_batch_scope.table_has_column", return_value=True
        ), patch(
            "backend.manual_checkout_settings.checkout_at_vendor_override_active",
            return_value=True,
        ), patch(
            "backend.checkout_batch_staging.upsert_staging_for_ticket_upload_row",
            return_value=("updated", 42),
        ) as mock_upsert:
            out = reapply_checkout_batch_staging(cursor, 1, 551, dry_run=False)

        self.assertEqual(out["updated"], 1)
        self.assertEqual(out["inserted"], 0)
        mock_upsert.assert_called_once()
        self.assertEqual(mock_upsert.call_args.kwargs.get("reactivate_sent"), True)


if __name__ == "__main__":
    unittest.main()
