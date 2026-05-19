"""Folding recompute runs after batch CONFIRM with full completed-bag coverage."""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.rinse_bag_completion import COMPLETION_COMPLETED
from backend.rinse_bag_folding import (
    EXCEPTION_MISSING_FOLDING,
    EXCEPTION_MISSING_SCAN_EVENTS,
    STATUS_CALCULATED,
    STATUS_EXCEPTION,
)
from backend.rinse_folding_registry import (
    apply_folding_performance_for_bag,
    collect_completed_bag_ids_for_folding,
    folding_recompute_summary_for_response,
    recompute_folding_after_upload,
)
from backend.rinse_upload_finalize import finalize_rinse_after_batch_confirm


class TestFoldingAfterConfirm(unittest.TestCase):
    def test_finalize_registry_before_completion_then_folding(self):
        cursor = MagicMock()
        call_order: list[str] = []

        def _registry(*_a, **_k):
            call_order.append("registry")
            return 1

        def _completion(*_a, **_k):
            call_order.append("completion")
            return {"bags": [{"bag_id": "BAG1", "completion_status": COMPLETION_COMPLETED}]}

        def _folding(*_a, **_k):
            call_order.append("folding")
            return {"ok": True, "summary": {"processed": 1, "calculated": 1, "exceptions": 0}}

        with (
            patch(
                "backend.rinse_portal_absence_completion.complete_bags_missing_from_latest_portal",
                return_value={"bag_ids": [], "count": 0, "full_snapshot": True},
            ),
            patch(
                "backend.rinse_upload_finalize.load_upload_batch_scan_events_as_dataframe",
                return_value=pd.DataFrame(),
            ),
            patch(
                "backend.rinse_upload_finalize.apply_registry_from_accepted_portal_rows",
                side_effect=_registry,
            ),
            patch(
                "backend.rinse_upload_finalize.recompute_completion_for_bags",
                side_effect=_completion,
            ),
            patch(
                "backend.rinse_folding_registry.recompute_folding_after_upload",
                side_effect=_folding,
            ),
        ):
            finalize_rinse_after_batch_confirm(
                cursor,
                1,
                10,
                accepted_portal_rows=[{"ticket_id": "BAG1"}],
            )

        self.assertEqual(call_order, ["registry", "completion", "folding"])

    def test_finalize_includes_absence_and_portal_bags_in_folding_candidates(self):
        cursor = MagicMock()
        with (
            patch(
                "backend.rinse_portal_absence_completion.complete_bags_missing_from_latest_portal",
                return_value={
                    "bag_ids": ["BAGOLD"],
                    "count": 1,
                    "full_snapshot": True,
                },
            ),
            patch(
                "backend.rinse_upload_finalize.load_upload_batch_scan_events_as_dataframe",
                return_value=pd.DataFrame(),
            ),
            patch(
                "backend.rinse_upload_finalize.merge_scan_events_from_upload",
                return_value={"bag_ids": ["BAGNEW"]},
            ),
            patch(
                "backend.rinse_upload_finalize.apply_registry_from_accepted_portal_rows",
                return_value=1,
            ),
            patch(
                "backend.rinse_upload_finalize.recompute_completion_for_bags",
                return_value={
                    "bags": [
                        {
                            "bag_id": "BAGNEW",
                            "completion_status": COMPLETION_COMPLETED,
                        }
                    ]
                },
            ),
            patch(
                "backend.rinse_folding_registry.recompute_folding_after_upload"
            ) as mock_fold,
        ):
            mock_fold.return_value = {
                "ok": True,
                "summary": {"processed": 2, "calculated": 1, "exceptions": 1},
            }
            finalize_rinse_after_batch_confirm(
                cursor,
                2,
                50,
                accepted_portal_rows=[{"ticket_id": "BAGNEW"}],
            )

        candidates = mock_fold.call_args[0][2]
        self.assertIn("BAGNEW", candidates)
        self.assertIn("BAGOLD", candidates)
        summaries = mock_fold.call_args[1].get("completion_summaries")
        self.assertEqual(len(summaries), 1)

    def test_confirm_response_folding_summary_fields(self):
        summary = folding_recompute_summary_for_response(
            {
                "ok": True,
                "bags": [
                    {"skipped": False, "status": STATUS_CALCULATED},
                    {"skipped": False, "status": STATUS_EXCEPTION},
                ],
                "summary": {
                    "processed": 2,
                    "calculated": 1,
                    "exceptions": 1,
                    "skipped_not_completed": 0,
                    "errors": 0,
                },
            }
        )
        self.assertEqual(summary["folding_recompute_processed"], 2)
        self.assertEqual(summary["folding_recompute_calculated"], 1)
        self.assertEqual(summary["folding_recompute_exceptions"], 1)

    def test_completed_bag_no_scans_writes_exception(self):
        cursor = MagicMock()
        with (
            patch(
                "backend.rinse_folding_registry.get_registry_row",
                return_value={
                    "bag_id": "BAGX",
                    "completion_status": COMPLETION_COMPLETED,
                    "weight_num": 5.0,
                },
            ),
            patch(
                "backend.rinse_folding_registry.fetch_persistent_scan_events_for_bag",
                return_value=[],
            ),
            patch(
                "backend.rinse_folding_registry._upsert_performance_row",
                return_value=42,
            ) as mock_upsert,
        ):
            out = apply_folding_performance_for_bag(
                cursor,
                1,
                "BAGX",
                require_completed_registry=True,
            )
        self.assertFalse(out.get("skipped"))
        self.assertEqual(out["status"], STATUS_EXCEPTION)
        fields = mock_upsert.call_args[0][3]
        self.assertEqual(fields["exception_code"], EXCEPTION_MISSING_SCAN_EVENTS)

    def test_completed_bag_clean_only_writes_missing_folding(self):
        cursor = MagicMock()
        t1 = datetime(2026, 5, 17, 14, 0)
        with (
            patch(
                "backend.rinse_folding_registry.get_registry_row",
                return_value={
                    "bag_id": "BAGY",
                    "completion_status": COMPLETION_COMPLETED,
                },
            ),
            patch(
                "backend.rinse_folding_registry.fetch_persistent_scan_events_for_bag",
                return_value=[
                    {
                        "id": 1,
                        "rack": "CLEAN",
                        "user_name": "User",
                        "scanned_at_parsed": t1,
                        "scan_index": 1,
                    }
                ],
            ),
            patch(
                "backend.rinse_folding_registry._upsert_performance_row",
                return_value=7,
            ) as mock_upsert,
        ):
            out = apply_folding_performance_for_bag(
                cursor, 1, "BAGY", require_completed_registry=True
            )
        self.assertEqual(out["status"], STATUS_EXCEPTION)
        fields = mock_upsert.call_args[0][3]
        self.assertEqual(fields["exception_code"], EXCEPTION_MISSING_FOLDING)

    def test_recompute_after_upload_only_completed_registry(self):
        cursor = MagicMock()

        def _reg(_c, org, bid):
            if bid == "DONE1":
                return {"bag_id": bid, "completion_status": COMPLETION_COMPLETED}
            return {"bag_id": bid, "completion_status": "INCOMPLETE"}

        with (
            patch(
                "backend.rinse_folding_registry.collect_completed_bag_ids_for_folding",
                return_value=["DONE1"],
            ) as mock_collect,
            patch(
                "backend.rinse_folding_registry.recompute_folding_performance_for_bags",
                return_value={
                    "bags_processed": 1,
                    "bags": [{"skipped": False, "status": STATUS_CALCULATED}],
                    "summary": {
                        "processed": 1,
                        "calculated": 1,
                        "exceptions": 0,
                        "skipped_not_completed": 0,
                        "errors": 0,
                    },
                },
            ) as mock_recompute,
        ):
            out = recompute_folding_after_upload(
                cursor, 1, ["DONE1", "PEND1"], completion_summaries=[]
            )
        mock_collect.assert_called_once()
        mock_recompute.assert_called_once()
        self.assertTrue(mock_recompute.call_args[1]["require_completed_registry"])
        self.assertEqual(out["completed_bag_ids"], ["DONE1"])


class TestCollectCompletedBagIds(unittest.TestCase):
    def test_collect_uses_registry_status(self):
        cursor = MagicMock()

        def _is_completed(reg):
            return (
                reg is not None
                and str(reg.get("completion_status") or "").upper()
                == COMPLETION_COMPLETED
            )

        def _reg(_c, _o, bid):
            if bid == "BAGA":
                return {"bag_id": "BAGA", "completion_status": COMPLETION_COMPLETED}
            return {"bag_id": bid, "completion_status": "INCOMPLETE"}

        with (
            patch("backend.rinse_folding_registry.get_registry_row", side_effect=_reg),
            patch(
                "backend.rinse_folding_registry.registry_is_completed",
                side_effect=_is_completed,
            ),
        ):
            ids = collect_completed_bag_ids_for_folding(
                cursor,
                1,
                ["BAGA", "BAGB"],
                completion_summaries=[
                    {"bag_id": "BAGB", "completion_status": COMPLETION_COMPLETED}
                ],
            )
        self.assertEqual(ids, ["BAGA"])


if __name__ == "__main__":
    unittest.main()
