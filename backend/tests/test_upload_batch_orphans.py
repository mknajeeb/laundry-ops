"""Upload batch orphan prevention and tenant-safe cascade deletes."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.upload_batch_cleanup import (
    count_orphan_upload_batch_children,
    delete_children_for_upload_batch,
    delete_orphan_upload_batch_children,
    delete_upload_batch_cascade,
    delete_upload_batch_children_for_organization,
    delete_upload_batches_for_organization,
)


class TestDeleteChildrenOrder(unittest.TestCase):
    def test_single_batch_deletes_rows_then_scan_events(self):
        cursor = MagicMock()
        calls: list[str] = []

        def _record_rows(*_a, **_k):
            calls.append("rows")

        def _record_scan(*_a, **_k):
            calls.append("scan_events")

        with (
            patch(
                "backend.upload_batch_cleanup.delete_upload_batch_rows_for_batch",
                side_effect=_record_rows,
            ),
            patch(
                "backend.rinse_scan_events_upload.delete_upload_batch_scan_events_for_batch",
                side_effect=_record_scan,
            ),
        ):
            delete_children_for_upload_batch(cursor, 42, organization_id=1)
        self.assertEqual(calls, ["rows", "scan_events"])

    def test_delete_upload_batch_cascade_order(self):
        cursor = MagicMock()
        order: list[str] = []

        def _children(*_a, **_k):
            order.append("children")
            return {"upload_batch_rows": 2, "upload_batch_scan_events": 1}

        with (
            patch(
                "backend.upload_batch_cleanup.delete_children_for_upload_batch",
                side_effect=_children,
            ),
            patch("backend.upload_batch_cleanup.table_exists", return_value=True),
            patch(
                "backend.upload_batch_cleanup.resolve_upload_batches_pk",
                return_value="id",
            ),
            patch(
                "backend.upload_batch_cleanup._table_has_column", return_value=True
            ),
        ):
            delete_upload_batch_cascade(cursor, 99, organization_id=5)
        order.append("batch")
        self.assertEqual(order, ["children", "batch"])
        sql = cursor.execute.call_args[0][0]
        self.assertIn("DELETE FROM upload_batches", sql)
        self.assertIn("organization_id", sql)
        self.assertEqual(cursor.execute.call_args[0][1], (99, 5))


class TestOrganizationScopedDelete(unittest.TestCase):
    def test_org_delete_children_before_batches(self):
        cursor = MagicMock()
        cursor.rowcount = 3
        executed: list[str] = []

        def _capture(sql, *_args):
            executed.append(sql.strip().split()[0:4])

        cursor.execute.side_effect = _capture

        with (
            patch("backend.upload_batch_cleanup.table_exists", return_value=True),
            patch(
                "backend.upload_batch_cleanup._table_has_column", return_value=True
            ),
            patch(
                "backend.upload_batch_cleanup.resolve_upload_batches_pk",
                return_value="id",
            ),
            patch(
                "backend.rinse_scan_events_upload.delete_upload_batch_scan_events_for_organization",
                return_value=2,
            ) as mock_scan,
        ):
            delete_upload_batches_for_organization(cursor, 7)

        mock_scan.assert_called_once_with(cursor, 7)
        delete_sqls = [c[0][0] for c in cursor.execute.call_args_list]
        self.assertGreaterEqual(len(delete_sqls), 1)
        batch_sql = delete_sqls[-1]
        self.assertIn("upload_batches", batch_sql)
        self.assertIn("organization_id", batch_sql)

    def test_org_children_delete_scoped_to_tenant(self):
        cursor = MagicMock()
        with (
            patch("backend.upload_batch_cleanup.table_exists", return_value=True),
            patch(
                "backend.upload_batch_cleanup._table_has_column", return_value=True
            ),
            patch(
                "backend.upload_batch_cleanup.resolve_upload_batches_pk",
                return_value="id",
            ),
            patch(
                "backend.rinse_scan_events_upload.delete_upload_batch_scan_events_for_organization",
                return_value=0,
            ),
        ):
            delete_upload_batch_children_for_organization(cursor, 2)
        rows_sql = cursor.execute.call_args[0][0]
        self.assertIn("upload_batch_rows", rows_sql)
        self.assertIn("organization_id = %s", rows_sql)
        self.assertEqual(cursor.execute.call_args[0][1], (2,))


class TestOrphanDetection(unittest.TestCase):
    def test_count_orphans_uses_left_join(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"c": 5}
        cursor.fetchall.return_value = [{"organization_id": 1, "c": 3}]
        with (
            patch("backend.upload_batch_cleanup.table_exists", return_value=True),
            patch(
                "backend.upload_batch_cleanup.resolve_upload_batches_pk",
                return_value="id",
            ),
        ):
            out = count_orphan_upload_batch_children(cursor)
        self.assertEqual(out["upload_batch_rows"]["total"], 5)
        self.assertEqual(out["upload_batch_scan_events"]["by_organization_id"]["1"], 3)
        sqls = " ".join(c[0][0] for c in cursor.execute.call_args_list)
        self.assertIn("LEFT JOIN upload_batches", sqls)

    def test_delete_orphans_only_child_tables(self):
        cursor = MagicMock()
        cursor.rowcount = 10
        with (
            patch("backend.upload_batch_cleanup.table_exists", return_value=True),
            patch(
                "backend.upload_batch_cleanup.resolve_upload_batches_pk",
                return_value="id",
            ),
        ):
            n = delete_orphan_upload_batch_children(cursor, organization_id=3)
        self.assertEqual(n["upload_batch_rows"], 10)
        for c in cursor.execute.call_args_list:
            sql = c[0][0]
            self.assertNotIn("DELETE FROM upload_batches", sql)


class TestDeleteBatchRemovesChildren(unittest.TestCase):
    """Deleting one batch must remove rows and scan-events for that batch only."""

    def test_cascade_invokes_child_delete_then_parent(self):
        cursor = MagicMock()
        with (
            patch(
                "backend.upload_batch_cleanup.delete_children_for_upload_batch",
                return_value={"upload_batch_rows": 4, "upload_batch_scan_events": 2},
            ) as mock_children,
            patch("backend.upload_batch_cleanup.table_exists", return_value=True),
            patch(
                "backend.upload_batch_cleanup.resolve_upload_batches_pk",
                return_value="id",
            ),
            patch(
                "backend.upload_batch_cleanup._table_has_column", return_value=True
            ),
        ):
            out = delete_upload_batch_cascade(cursor, 100, organization_id=1)
        mock_children.assert_called_once_with(
            cursor, 100, organization_id=1
        )
        self.assertEqual(out["upload_batch_rows"], 4)
        self.assertEqual(out["upload_batch_scan_events"], 2)
        self.assertEqual(out["upload_batches"], int(cursor.rowcount or 0))


if __name__ == "__main__":
    unittest.main()
