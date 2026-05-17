"""Tests for combined dual-CSV Rinse upload and pre-upload completion snapshot."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.rinse_bag_completion import (
    REASON_ALREADY_COMPLETED,
    REASON_OK,
    REASON_UPDATED_EXISTING_BAG,
    classify_portal_upload_row,
)
from backend.rinse_combined_upload import (
    REQUIRE_DUAL_CSV_CODE,
    commit_rinse_combined_upload,
    dual_csv_required_error,
    snapshot_pre_upload_completed_bag_ids,
)
from backend.rinse_bag_upload import enrich_upload_batch_rows_with_registry
from backend.rinse_scan_events_upload import parse_scan_events_csv
from backend.upload_batch_requirements import upload_batch_require_both_csv


class TestDualCsvRequiredError(unittest.TestCase):
    def test_error_payload(self):
        body, code = dual_csv_required_error()
        self.assertEqual(code, 400)
        self.assertEqual(body["code"], REQUIRE_DUAL_CSV_CODE)


class TestPreUploadCompletionSnapshot(unittest.TestCase):
    """ALREADY_COMPLETED = completed before this upload began, not during it."""

    BAG = "BAG12345"

    def test_existing_incomplete_with_staging_accepted_when_not_pre_completed(self):
        st, reason = classify_portal_upload_row(
            ticket_id=self.BAG,
            was_completed_before_upload=False,
            has_active_staging=True,
            row_date_before_batch=False,
        )
        self.assertEqual(st, "ACCEPTED")
        self.assertEqual(reason, REASON_UPDATED_EXISTING_BAG)

    def test_new_bag_accepted_ok_when_not_pre_completed(self):
        st, reason = classify_portal_upload_row(
            ticket_id=self.BAG,
            was_completed_before_upload=False,
            has_active_staging=False,
            row_date_before_batch=False,
        )
        self.assertEqual(st, "ACCEPTED")
        self.assertEqual(reason, REASON_OK)

    def test_repeat_upload_after_prior_completion_rejected(self):
        st, reason = classify_portal_upload_row(
            ticket_id=self.BAG,
            was_completed_before_upload=True,
            has_active_staging=True,
            row_date_before_batch=False,
        )
        self.assertEqual(st, "REJECTED_DUPLICATE")
        self.assertEqual(reason, REASON_ALREADY_COMPLETED)

    def test_already_completed_before_upload_rejected(self):
        st, reason = classify_portal_upload_row(
            ticket_id=self.BAG,
            was_completed_before_upload=True,
            has_active_staging=False,
            row_date_before_batch=False,
        )
        self.assertEqual(st, "REJECTED_DUPLICATE")
        self.assertEqual(reason, REASON_ALREADY_COMPLETED)

    def test_snapshot_recomputes_before_fetch(self):
        cursor = MagicMock()
        orders = pd.DataFrame({"ticket_id": ["bag12345"]})
        with (
            patch(
                "backend.rinse_bag_registry.recompute_completion_for_bags"
            ) as mock_recompute,
            patch(
                "backend.rinse_bag_registry.fetch_pre_existing_completed_bag_ids",
                return_value=set(),
            ) as mock_fetch,
        ):
            result = snapshot_pre_upload_completed_bag_ids(cursor, 1, orders)
        self.assertEqual(result, set())
        mock_recompute.assert_called_once_with(cursor, 1, ["BAG12345"])
        mock_fetch.assert_called_once_with(cursor, 1, ["BAG12345"])

    def test_stale_or_completed_not_in_snapshot_after_recompute(self):
        """After progressive-timeline recompute marks bag INCOMPLETE, snapshot must be empty."""
        cursor = MagicMock()
        orders = pd.DataFrame({"ticket_id": ["STALE01"]})

        def _fetch(_c, _o, ids):
            self.assertEqual(ids, ["STALE01"])
            return set()

        with (
            patch("backend.rinse_bag_registry.recompute_completion_for_bags"),
            patch(
                "backend.rinse_bag_registry.fetch_pre_existing_completed_bag_ids",
                side_effect=_fetch,
            ),
        ):
            snap = snapshot_pre_upload_completed_bag_ids(cursor, 1, orders)
        self.assertNotIn("STALE01", snap)
        st, reason = classify_portal_upload_row(
            ticket_id="STALE01",
            was_completed_before_upload=False,
            has_active_staging=True,
            row_date_before_batch=False,
        )
        self.assertEqual(st, "ACCEPTED")
        self.assertEqual(reason, REASON_UPDATED_EXISTING_BAG)

    def test_truly_completed_in_snapshot_rejects(self):
        cursor = MagicMock()
        orders = pd.DataFrame({"ticket_id": ["DONE1234"]})
        with (
            patch("backend.rinse_bag_registry.recompute_completion_for_bags"),
            patch(
                "backend.rinse_bag_registry.fetch_pre_existing_completed_bag_ids",
                return_value={"DONE1234"},
            ),
        ):
            snap = snapshot_pre_upload_completed_bag_ids(cursor, 1, orders)
        self.assertIn("DONE1234", snap)
        st, reason = classify_portal_upload_row(
            ticket_id="DONE1234",
            was_completed_before_upload=True,
            has_active_staging=True,
            row_date_before_batch=False,
        )
        self.assertEqual(st, "REJECTED_DUPLICATE")
        self.assertEqual(reason, REASON_ALREADY_COMPLETED)


class TestCommitRinseCombinedUploadOrder(unittest.TestCase):
    """Scan-events merge + recompute run before portal row insert; snapshot taken first."""

    def test_snapshot_before_merge_and_classify_after_recompute(self):
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

        def _pre_existing(*_a, **_k):
            call_order.append("pre_upload_snapshot")
            return set()

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
                "backend.rinse_combined_upload.snapshot_pre_upload_completed_bag_ids",
                side_effect=_pre_existing,
            ),
            patch("backend.rinse_bag_registry.merge_scan_events_from_upload", side_effect=_merge),
            patch("backend.rinse_bag_registry.recompute_completion_for_bags", side_effect=_recompute),
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
            patch("backend.app.summarize_batch_rows", return_value={}),
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
            commit_rinse_combined_upload(
                conn,
                cursor,
                tenant_oid=1,
                batch_date=date.today(),
                portal_filename="portal.csv",
                orders_df=orders_df,
                events_filename="events.csv",
                events_df=events_df,
            )

        self.assertEqual(
            call_order,
            ["shell", "pre_upload_snapshot", "merge", "recompute", "insert", "audit"],
        )


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
        with patch("backend.ops_ui_flags.get_ops_ui_flags", return_value={}):
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


class TestEnrichRegistryReasonAlignment(unittest.TestCase):
    def test_incomplete_registry_hides_already_completed_reason(self):
        cursor = MagicMock()
        rows = [
            {
                "ticket_id": "BAG1",
                "row_status": "ACCEPTED",
                "reason": REASON_ALREADY_COMPLETED,
            }
        ]
        with patch(
            "backend.rinse_bag_upload.fetch_registry_map_for_bag_ids",
            return_value={
                "BAG1": {
                    "completion_status": "INCOMPLETE",
                    "completion_reason": "NO_CLEAN_SCAN",
                }
            },
        ):
            out = enrich_upload_batch_rows_with_registry(cursor, 1, rows)
        self.assertEqual(out[0]["registry_status"], "INCOMPLETE")
        self.assertEqual(out[0]["reason"], REASON_OK)


class TestConfirmTrustsDraftAcceptance(unittest.TestCase):
    def test_confirm_staging_updates_when_not_pre_completed(self):
        from backend.rinse_bag_completion import confirm_staging_action

        self.assertEqual(
            confirm_staging_action(
                ticket_id="BAG1",
                was_completed_before_upload=False,
                has_active_staging=True,
            ),
            "UPDATE_STAGING",
        )


if __name__ == "__main__":
    unittest.main()
