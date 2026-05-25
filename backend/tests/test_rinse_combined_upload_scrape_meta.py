"""Ensure dual-CSV manual upload can import rinse_portal_scrape_meta (production deploy guard)."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.rinse_combined_upload import commit_rinse_combined_upload


class TestManualDualCsvScrapeMetaImport(unittest.TestCase):
    def test_commit_rinse_combined_upload_imports_scrape_meta_module(self):
        """Regression: module must exist on API host (not only in dev tree)."""
        import backend.rinse_portal_scrape_meta as mod

        self.assertTrue(hasattr(mod, "persist_portal_scrape_meta_on_batch"))

        schema = MagicMock(row_pk="batch_id")
        orders_df = pd.DataFrame(
            {
                "ticket_id": ["BAGTEST01"],
                "date_clean": ["2026-05-25"],
                "name_clean": ["TEST"],
                "weight_num": [10],
                "service_type": ["HD"],
                "rush_type": ["NON-RUSH"],
            }
        )
        events_df = pd.DataFrame(
            {
                "Bag ID": ["BAGTEST01"],
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
            patch("backend.rinse_combined_upload.snapshot_pre_upload_completed_bag_ids", return_value=set()),
            patch("backend.rinse_combined_upload.create_draft_upload_batch_shell", return_value=1),
            patch("backend.rinse_combined_upload.build_upload_duplicate_indexes", return_value=(set(), {}, 3)),
            patch(
                "backend.rinse_combined_upload.insert_upload_batch_rows_from_orders_df",
                return_value={"rows_inserted": 1, "rejected_rows": 0, "needs_attention_rows": 0},
            ),
            patch(
                "backend.rinse_scan_events_upload.commit_scan_events_for_batch",
                return_value={"rows_inserted": 1},
            ),
            patch("backend.rinse_combined_upload.finalize_upload_batch_row_counts"),
            patch(
                "backend.rinse_portal_scrape_meta.persist_portal_scrape_meta_on_batch",
                return_value={
                    "full_snapshot": True,
                    "portal_scrape_meta": None,
                    "portal_absence_allowed": True,
                },
            ) as mock_persist,
            patch.dict(
                sys.modules,
                {"backend.app": MagicMock(summarize_batch_rows=MagicMock(return_value={}))},
            ),
            patch(
                "backend.upload_batch_requirements.batch_upload_files_status",
                return_value={"confirm_ready": True, "has_scan_events": True},
            ),
        ):
            out = commit_rinse_combined_upload(
                conn,
                cursor,
                tenant_oid=1,
                batch_date=date.today(),
                portal_filename="portal.csv",
                orders_df=orders_df,
                events_filename="events.csv",
                events_df=events_df,
            )

        mock_persist.assert_called_once()
        call_meta = mock_persist.call_args[0][3]
        self.assertIsNone(call_meta)
        self.assertEqual(out.get("status"), "draft_uploaded")
        self.assertEqual(out.get("source"), "upload_rinse_dual_csv")


if __name__ == "__main__":
    unittest.main()
