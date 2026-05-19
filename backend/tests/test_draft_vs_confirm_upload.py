"""Draft upload must not finalize registry/folding; confirm must."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.rinse_combined_upload import commit_rinse_combined_upload
from backend.rinse_upload_finalize import finalize_rinse_after_batch_confirm


class TestDraftUploadNoFinalize(unittest.TestCase):
    def test_combined_draft_does_not_merge_or_recompute(self):
        conn = MagicMock()
        cursor = MagicMock()
        orders_df = pd.DataFrame(
            [
                {
                    "Date_Clean": datetime(2026, 5, 17),
                    "Name_Clean": "Customer",
                    "Weight_Num": 10.0,
                    "ServiceType": "WF",
                    "RushType": "NON-RUSH",
                    "ticket_id": "BAGDRAFT1",
                }
            ]
        )
        events_df = pd.DataFrame(
            [
                {
                    "Bag ID": "BAGDRAFT1",
                    "Scan Index": "1",
                    "Rack": "FOLDING",
                    "Time Scanned": "Sunday, May 17, 2026 3:04 PM",
                    "User": "Folder",
                    "Purpose": "",
                    "Last Location": "",
                    "Last Scan": "",
                }
            ]
        )

        with (
            patch("backend.rinse_combined_upload.get_upload_batch_schema") as mock_schema,
            patch("backend.rinse_combined_upload.prepare_orders_df", side_effect=lambda df: df),
            patch(
                "backend.rinse_combined_upload.snapshot_pre_upload_completed_bag_ids",
                return_value=set(),
            ),
            patch(
                "backend.rinse_combined_upload.create_draft_upload_batch_shell",
                return_value=99,
            ),
            patch("backend.rinse_combined_upload.build_upload_duplicate_indexes") as mock_idx,
            patch("backend.rinse_combined_upload.insert_upload_batch_rows_from_orders_df") as mock_ins,
            patch(
                "backend.rinse_scan_events_upload.commit_scan_events_for_batch"
            ) as mock_scan,
            patch("backend.ta_helpers.table_exists", return_value=True),
            patch("backend.rinse_combined_upload.finalize_upload_batch_row_counts"),
            patch(
                "backend.upload_batch_requirements.batch_upload_files_status",
                return_value={},
            ),
            patch("backend.rinse_bag_registry.merge_scan_events_from_upload") as mock_merge,
            patch("backend.rinse_bag_registry.recompute_completion_for_bags") as mock_comp,
            patch(
                "backend.rinse_folding_registry.recompute_folding_after_upload"
            ) as mock_fold,
        ):
            mock_schema.return_value = MagicMock(
                row_pk="id",
                upload_batches_pk="id",
                has_ub_org=True,
                has_state=True,
                has_rows_inserted=False,
                has_updated_at=False,
                cap={"has_ticket_id": True},
            )
            mock_idx.return_value = (set(), {}, 30)
            mock_ins.return_value = {
                "rows_inserted": 1,
                "rejected_rows": 0,
                "needs_attention_rows": 0,
            }
            mock_scan.return_value = {"rows_committed": 1}

            mock_app = MagicMock()
            mock_app.summarize_batch_rows = MagicMock(return_value={})
            with patch.dict(sys.modules, {"backend.app": mock_app}):
                out = commit_rinse_combined_upload(
                conn,
                cursor,
                1,
                datetime(2026, 5, 17).date(),
                "portal.csv",
                orders_df,
                "events.csv",
                events_df,
                )

        mock_merge.assert_not_called()
        mock_comp.assert_not_called()
        mock_fold.assert_not_called()
        self.assertTrue(out.get("finalize_on_confirm"))
        self.assertIn("scan_events_batch", out)
        self.assertNotIn("persistent_merge", out)


class TestConfirmFinalizes(unittest.TestCase):
    def test_finalize_calls_merge_completion_folding(self):
        cursor = MagicMock()
        events_df = pd.DataFrame(
            [
                {
                    "Bag ID": "BAG1",
                    "Scan Index": "1",
                    "Rack": "CLEAN",
                    "Time Scanned": "Sunday, May 17, 2026 3:17 PM",
                    "User": "U",
                    "Purpose": "",
                    "Last Location": "",
                    "Last Scan": "",
                }
            ]
        )
        with (
            patch(
                "backend.rinse_portal_absence_completion.complete_bags_missing_from_latest_portal",
                return_value={
                    "full_snapshot": True,
                    "skipped": False,
                    "count": 0,
                    "bag_ids": [],
                },
            ),
            patch(
                "backend.rinse_upload_finalize.load_upload_batch_scan_events_as_dataframe",
                return_value=events_df,
            ),
            patch(
                "backend.rinse_upload_finalize.merge_scan_events_from_upload"
            ) as mock_merge,
            patch(
                "backend.rinse_upload_finalize.apply_registry_from_accepted_portal_rows",
                return_value=1,
            ) as mock_registry,
            patch(
                "backend.rinse_upload_finalize.recompute_completion_for_bags"
            ) as mock_comp,
            patch(
                "backend.rinse_folding_registry.recompute_folding_after_upload"
            ) as mock_fold,
        ):
            mock_merge.return_value = {"bag_ids": ["BAG1"], "events_inserted": 1}
            mock_comp.return_value = {"bags": [{"bag_id": "BAG1", "completion_status": "COMPLETED"}]}
            mock_fold.return_value = {
                "ok": True,
                "summary": {"processed": 1, "calculated": 1, "exceptions": 0},
            }

            out = finalize_rinse_after_batch_confirm(
                cursor,
                2,
                50,
                accepted_portal_rows=[{"ticket_id": "BAG1", "name_clean": "C"}],
            )

        mock_merge.assert_called_once()
        mock_registry.assert_called_once()
        mock_comp.assert_called_once()
        mock_fold.assert_called_once()
        self.assertEqual(out["bag_ids"], ["BAG1"])
        self.assertIn("folding_recompute_processed", out)


class TestDraftPreviewNoPersist(unittest.TestCase):
    def test_preview_uses_evaluator_not_registry_write(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {
                "id": 1,
                "bag_id": "BAG1",
                "rack": "CLEAN",
                "user_name": "U",
                "scanned_at_parsed": datetime(2026, 5, 17, 15, 0),
                "scan_index": 1,
            }
        ]
        with patch("backend.ta_helpers.table_exists", return_value=True):
            from backend.rinse_upload_finalize import preview_completion_for_batch

            prev = preview_completion_for_batch(cursor, 1, 10)
        self.assertIn("BAG1", prev)
        self.assertIn("completion_status", prev["BAG1"])


if __name__ == "__main__":
    unittest.main()
