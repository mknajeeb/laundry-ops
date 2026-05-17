"""Tests for upload_batch_scan_events cleanup on batch delete/reset."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import backend.rinse_scan_events_upload as scan_upload
from backend.rinse_scan_events_upload import (
    delete_upload_batch_scan_events_for_batch,
    delete_upload_batch_scan_events_for_organization,
)


class TestUploadBatchScanEventsCleanup(unittest.TestCase):
    def test_delete_for_batch_with_org(self):
        cursor = MagicMock()
        cursor.rowcount = 3
        with patch("backend.rinse_scan_events_upload.table_exists", return_value=True):
            n = delete_upload_batch_scan_events_for_batch(cursor, 42, organization_id=1)
        self.assertEqual(n, 3)
        sql = cursor.execute.call_args[0][0]
        self.assertIn("upload_batch_scan_events", sql)
        self.assertIn("organization_id", sql)
        self.assertEqual(cursor.execute.call_args[0][1], (42, 1))

    def test_delete_for_organization(self):
        cursor = MagicMock()
        cursor.rowcount = 10
        with patch("backend.rinse_scan_events_upload.table_exists", return_value=True):
            n = delete_upload_batch_scan_events_for_organization(cursor, 5)
        self.assertEqual(n, 10)
        self.assertIn("organization_id", cursor.execute.call_args[0][0])

    def test_skips_when_table_missing(self):
        cursor = MagicMock()
        with patch.object(scan_upload, "table_exists", return_value=False):
            n = delete_upload_batch_scan_events_for_batch(cursor, 1, organization_id=1)
        self.assertEqual(n, 0)
        cursor.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
