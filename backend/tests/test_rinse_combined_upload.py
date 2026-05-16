"""Tests for combined dual-CSV Rinse upload."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.rinse_bag_completion import REASON_ALREADY_COMPLETED, classify_portal_upload_row
from backend.rinse_combined_upload import (
    REQUIRE_DUAL_CSV_CODE,
    collect_bag_ids_from_upload,
    commit_rinse_combined_upload,
    dual_csv_required_error,
)
from backend.rinse_scan_events_upload import parse_scan_events_csv
from backend.upload_batch_requirements import upload_batch_require_both_csv


class TestDualCsvRequiredError(unittest.TestCase):
    def test_error_payload(self):
        body, code = dual_csv_required_error()
        self.assertEqual(code, 400)
        self.assertEqual(body["code"], REQUIRE_DUAL_CSV_CODE)
        self.assertIn("both", body["message"].lower())


class TestCollectBagIds(unittest.TestCase):
    def test_union_portal_and_events(self):
        orders = pd.DataFrame({"ticket_id": ["ab12cd34", ""]})
        events = pd.DataFrame({"Bag ID": ["AB12CD34", "ZZ99XX88"]})
        ids = collect_bag_ids_from_upload(orders, events)
        self.assertEqual(ids, ["AB12CD34", "ZZ99XX88"])


class TestCommitRinseCombinedUploadOrder(unittest.TestCase):
    """Scan-events merge + recompute must run before portal row insert."""

    def test_merge_and_recompute_before_row_insert(self):
        call_order: list[str] = []

        def _merge(*_a, **_k):
            call_order.append("merge")
            return {"bag_ids": ["BAG1"], "bags_merged": 1, "events_inserted": 1}

        def _recompute(*_a, **_k):
            call_order.append("recompute")
            return {"bags": 1}

        def _insert(*_a, **_k):
            call_order.append("insert")
            return {"rows_inserted": 1, "rejected_rows": 0, "needs_attention_rows": 0}

        def _audit(*_a, **_k):
            call_order.append("audit")
            return {"rows_inserted": 2, "bags_with_events": 1, "replaced_prior_rows": 0}

        schema = MagicMock(
            row_pk="id",
            upload_batches_pk="id",
            has_ub_org=True,
            has_state=True,
            has_closed_at=True,
            has_updated_at=True,
            has_rows_inserted=True,
            time_col="created_at",
            cap={},
        )

        orders_df = pd.DataFrame(
            {
                "Date_Clean": [date.today()],
                "Name_Clean": ["Test"],
                "Weight_Num": [10.0],
                "ServiceType": ["WF"],
                "RushType": ["NON-RUSH"],
                "ticket_id": ["BAG1"],
            }
        )
        events_df = pd.DataFrame(
            {
                "Bag ID": ["BAG1"],
                "Scan Index": ["1"],
                "Rack": ["Clean A"],
                "Time Scanned": [""],
                "User": ["staff"],
                "Purpose": [""],
                "Last Location": [""],
                "Last Scan": [""],
            }
        )

        conn = MagicMock()
        cursor = MagicMock()

        with (
            patch("backend.rinse_combined_upload.get_upload_batch_schema", return_value=schema),
            patch("backend.rinse_combined_upload.prepare_orders_df", side_effect=lambda df: df),
            patch(
                "backend.rinse_combined_upload.create_draft_upload_batch_shell",
                side_effect=lambda *_a, **_k: (call_order.append("shell") or 99),
            ),
            patch(
                "backend.rinse_bag_registry.merge_scan_events_from_upload",
                side_effect=_merge,
            ),
            patch(
                "backend.rinse_bag_registry.recompute_completion_for_bags",
                side_effect=_recompute,
            ),
            patch(
                "backend.rinse_combined_upload.build_upload_duplicate_indexes",
                return_value=(set(), {}, 3),
            ),
            patch(
                "backend.rinse_combined_upload.insert_upload_batch_rows_from_orders_df",
                side_effect=_insert,
            ),
            patch(
                "backend.rinse_scan_events_upload.commit_scan_events_for_batch",
                side_effect=_audit,
            ),
            patch("backend.rinse_combined_upload.finalize_upload_batch_row_counts"),
            patch(
                "backend.app.summarize_batch_rows",
                return_value={},
            ),
            patch(
                "backend.upload_batch_requirements.batch_upload_files_status",
                return_value={
                    "require_both_csv": True,
                    "has_order_rows": True,
                    "has_scan_events": True,
                    "confirm_ready": True,
                    "missing": [],
                },
            ),
        ):
            payload = commit_rinse_combined_upload(
                conn,
                cursor,
                tenant_oid=1,
                batch_date=date.today(),
                portal_filename="portal.csv",
                orders_df=orders_df,
                events_filename="events.csv",
                events_df=events_df,
            )

        self.assertEqual(payload["batch_id"], 99)
        self.assertEqual(
            call_order,
            ["shell", "merge", "recompute", "insert", "audit"],
        )
        conn.commit.assert_called_once()


class TestCompletedBagRejectedAfterRecompute(unittest.TestCase):
    def test_classify_rejects_completed_bag(self):
        status, reason = classify_portal_upload_row(
            ticket_id="DONE1234",
            is_completed=True,
            has_active_staging=False,
            row_date_before_batch=False,
        )
        self.assertEqual(status, "REJECTED_DUPLICATE")
        self.assertEqual(reason, REASON_ALREADY_COMPLETED)


class TestInvalidScanEventsNoDraft(unittest.TestCase):
    def test_parse_missing_columns_raises(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("Bag ID,Scan Index\n")
            f.write("ABCD,1\n")
            path = f.name
        try:
            with self.assertRaises(ValueError):
                parse_scan_events_csv(path)
        finally:
            import os

            os.unlink(path)


class TestUploadBatchRequireBothCsvFlag(unittest.TestCase):
    def test_default_true_when_flag_missing(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.fetchone.return_value = None
        with patch(
            "backend.ops_ui_flags.get_ops_ui_flags",
            return_value={},
        ):
            self.assertTrue(upload_batch_require_both_csv(cursor, 1))

    def test_false_when_flag_off(self):
        cursor = MagicMock()

        def _get_setting(_cursor, _org, key):
            from backend.ops_ui_flags import KEY_UPLOAD_BOTH_CSV

            if key == KEY_UPLOAD_BOTH_CSV:
                return "0"
            return None

        with patch("backend.ops_ui_flags._get_setting", side_effect=_get_setting):
            self.assertFalse(upload_batch_require_both_csv(cursor, 1))


class TestPortalOnlyBlockedWhenFlagOn(unittest.TestCase):
    def test_dual_csv_required_response(self):
        body, code = dual_csv_required_error()
        self.assertEqual(body["code"], REQUIRE_DUAL_CSV_CODE)
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()
