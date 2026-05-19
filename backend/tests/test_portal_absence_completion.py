"""Missing-from-latest-portal completion on batch CONFIRM only."""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from backend.rinse_bag_completion import (
    COMPLETION_COMPLETED,
    COMPLETION_INCOMPLETE,
    REASON_MISSING_FROM_LATEST_PORTAL_UPLOAD,
    TRIGGER_KIND_PORTAL_ABSENCE,
)
from backend.rinse_portal_absence_completion import (
    build_current_upload_bag_ids,
    complete_bags_missing_from_latest_portal,
    upload_batch_is_full_snapshot_portal,
)
from backend.rinse_upload_finalize import finalize_rinse_after_batch_confirm


class TestPortalAbsenceCompletion(unittest.TestCase):
    def test_build_current_upload_bag_ids_normalizes(self):
        rows = [
            {"ticket_id": "  bag1234 "},
            {"ticket_id": ""},
            {"ticket_id": "BAG2"},
            {"ticket_id": "BAG_9999"},
        ]
        self.assertEqual(
            build_current_upload_bag_ids(rows),
            {"BAG1234", "BAG2", "BAG_9999"},
        )

    def test_incomplete_a_absent_on_confirm_full_snapshot(self):
        cursor = MagicMock()
        accepted = [{"ticket_id": "BAGB", "name_clean": "N"}]
        with (
            patch(
                "backend.rinse_portal_absence_completion.fetch_incomplete_bag_candidates_for_org",
                return_value={"BAGA"},
            ),
            patch(
                "backend.rinse_portal_absence_completion.mark_registry_completed_portal_absence",
                return_value=True,
            ) as mock_mark,
        ):
            out = complete_bags_missing_from_latest_portal(
                cursor, 1, 99, accepted, full_snapshot=True
            )

        self.assertTrue(out["full_snapshot"])
        self.assertFalse(out["skipped"])
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["bag_ids"], ["BAGA"])
        mock_mark.assert_called_once()
        self.assertEqual(mock_mark.call_args[0][2], "BAGA")

    def test_finalize_calls_portal_absence_on_confirm(self):
        cursor = MagicMock()
        with (
            patch(
                "backend.rinse_portal_absence_completion.complete_bags_missing_from_latest_portal",
                return_value={
                    "full_snapshot": False,
                    "skipped": True,
                    "count": 0,
                    "bag_ids": [],
                },
            ) as mock_absence,
            patch(
                "backend.rinse_upload_finalize.load_upload_batch_scan_events_as_dataframe",
                return_value=__import__("pandas").DataFrame(),
            ),
            patch(
                "backend.rinse_upload_finalize.merge_scan_events_from_upload",
                return_value={"bag_ids": []},
            ),
            patch(
                "backend.rinse_upload_finalize.recompute_completion_for_bags",
                return_value={"bags": 0},
            ),
            patch(
                "backend.rinse_upload_finalize.apply_registry_from_accepted_portal_rows",
                return_value=0,
            ),
        ):
            finalize_rinse_after_batch_confirm(cursor, 1, 10, accepted_portal_rows=[])
        mock_absence.assert_called_once()

    def test_absence_skipped_when_not_full_snapshot(self):
        cursor = MagicMock()
        with patch(
            "backend.rinse_portal_absence_completion.upload_batch_is_full_snapshot_portal",
            return_value=False,
        ):
            out = complete_bags_missing_from_latest_portal(
                cursor,
                1,
                10,
                [{"ticket_id": "BAG_B"}],
            )
        self.assertFalse(out["full_snapshot"])
        self.assertTrue(out["skipped"])
        self.assertEqual(out["count"], 0)

    def test_bag_in_upload_not_absence_completed(self):
        cursor = MagicMock()
        accepted = [{"ticket_id": "BAGA"}]
        with (
            patch(
                "backend.rinse_portal_absence_completion.fetch_incomplete_bag_candidates_for_org",
                return_value={"BAGA"},
            ),
            patch(
                "backend.rinse_portal_absence_completion.mark_registry_completed_portal_absence"
            ) as mock_mark,
        ):
            out = complete_bags_missing_from_latest_portal(
                cursor, 1, 10, accepted, full_snapshot=True
            )
        self.assertEqual(out["bag_ids"], [])
        mock_mark.assert_not_called()

    def test_completed_bag_missing_from_upload_unchanged(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {"bag_id": "BAG_DONE", "completion_status": COMPLETION_COMPLETED}
        ]
        with (
            patch(
                "backend.rinse_portal_absence_completion.upload_batch_is_full_snapshot_portal",
                return_value=True,
            ),
            patch(
                "backend.rinse_portal_absence_completion.mark_registry_completed_portal_absence"
            ) as mock_mark,
            patch(
                "backend.rinse_portal_absence_completion.fetch_incomplete_bag_candidates_for_org",
                return_value=set(),
            ),
        ):
            out = complete_bags_missing_from_latest_portal(
                cursor,
                1,
                10,
                [{"ticket_id": "BAGNEW"}],
                full_snapshot=True,
            )
        self.assertEqual(out["bag_ids"], [])
        mock_mark.assert_not_called()

    def test_scan_events_only_not_full_snapshot(self):
        cursor = MagicMock()
        with patch(
            "backend.upload_batch_requirements.batch_upload_files_status",
            return_value={
                "has_order_rows": False,
                "has_scan_events": True,
                "require_both_csv": True,
            },
        ):
            self.assertFalse(
                upload_batch_is_full_snapshot_portal(
                    cursor, 1, 10, [{"ticket_id": "X"}]
                )
            )

    def test_finalize_includes_absence_bags_in_folding(self):
        cursor = MagicMock()
        events_df = __import__("pandas").DataFrame()
        absence_out = {
            "full_snapshot": True,
            "skipped": False,
            "count": 1,
            "bag_ids": ["BAGOLD"],
        }
        with (
            patch(
                "backend.rinse_portal_absence_completion.complete_bags_missing_from_latest_portal",
                return_value=absence_out,
            ),
            patch(
                "backend.rinse_upload_finalize.load_upload_batch_scan_events_as_dataframe",
                return_value=events_df,
            ),
            patch(
                "backend.rinse_upload_finalize.merge_scan_events_from_upload",
                return_value={"bag_ids": ["BAGNEW"]},
            ),
            patch(
                "backend.rinse_upload_finalize.recompute_completion_for_bags",
                return_value={
                    "bags": [{"bag_id": "BAGNEW", "completion_status": COMPLETION_COMPLETED}]
                },
            ),
            patch(
                "backend.rinse_upload_finalize.apply_registry_from_accepted_portal_rows",
                return_value=1,
            ),
            patch(
                "backend.rinse_folding_registry.recompute_folding_after_upload"
            ) as mock_fold,
        ):
            mock_fold.return_value = {"ok": True, "processed": 2}
            out = finalize_rinse_after_batch_confirm(
                cursor,
                2,
                50,
                accepted_portal_rows=[{"ticket_id": "BAGNEW"}],
            )
        mock_fold.assert_called_once()
        fold_bags = mock_fold.call_args[0][2]
        self.assertIn("BAGNEW", fold_bags)
        self.assertIn("BAGOLD", fold_bags)
        self.assertEqual(out["missing_prior_bags_completed_count"], 1)
        self.assertEqual(out["missing_prior_bag_ids_completed"], ["BAGOLD"])

    def test_confirm_response_fields_present(self):
        cursor = MagicMock()
        with (
            patch(
                "backend.rinse_portal_absence_completion.complete_bags_missing_from_latest_portal",
                return_value={
                    "full_snapshot": True,
                    "skipped": False,
                    "count": 2,
                    "bag_ids": ["OLD1", "OLD2"],
                },
            ),
            patch(
                "backend.rinse_upload_finalize.load_upload_batch_scan_events_as_dataframe",
                return_value=__import__("pandas").DataFrame(),
            ),
            patch(
                "backend.rinse_upload_finalize.merge_scan_events_from_upload",
                return_value={"bag_ids": []},
            ),
            patch(
                "backend.rinse_upload_finalize.recompute_completion_for_bags",
                return_value={"bags": 0},
            ),
            patch(
                "backend.rinse_upload_finalize.apply_registry_from_accepted_portal_rows",
                return_value=0,
            ),
        ):
            out = finalize_rinse_after_batch_confirm(
                cursor, 1, 10, accepted_portal_rows=[{"ticket_id": "NEW1"}]
            )
        self.assertEqual(out["missing_prior_bags_completed_count"], 2)
        self.assertEqual(out["missing_prior_bag_ids_completed"], ["OLD1", "OLD2"])
        self.assertTrue(out["full_snapshot"])

    def test_multi_tenant_only_same_org_candidates(self):
        cursor = MagicMock()
        with (
            patch(
                "backend.rinse_portal_absence_completion.fetch_incomplete_bag_candidates_for_org",
                return_value={"BAG1"},
            ),
            patch(
                "backend.rinse_portal_absence_completion.mark_registry_completed_portal_absence",
                return_value=True,
            ),
        ):
            out = complete_bags_missing_from_latest_portal(
                cursor,
                1,
                10,
                [{"ticket_id": "BAG2"}],
                full_snapshot=True,
            )
        self.assertEqual(out["bag_ids"], ["BAG1"])


class TestMarkRegistryPortalAbsence(unittest.TestCase):
    def test_mark_sets_reason_and_trigger(self):
        from backend.rinse_bag_registry import mark_registry_completed_portal_absence

        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "bag_id": "BAG1",
            "completion_status": COMPLETION_INCOMPLETE,
        }
        when = datetime(2026, 5, 17, 12, 0, 0)
        ok = mark_registry_completed_portal_absence(
            cursor, 1, "BAG1", upload_batch_id=99, completed_at=when
        )
        self.assertTrue(ok)
        insert_sql = cursor.execute.call_args_list[-1][0][0]
        self.assertIn("INSERT INTO rinse_bag_registry", insert_sql)
        params = cursor.execute.call_args_list[-1][0][1]
        self.assertEqual(params[2], COMPLETION_COMPLETED)
        self.assertEqual(params[3], REASON_MISSING_FROM_LATEST_PORTAL_UPLOAD)
        self.assertEqual(params[5], TRIGGER_KIND_PORTAL_ABSENCE)


if __name__ == "__main__":
    unittest.main()
