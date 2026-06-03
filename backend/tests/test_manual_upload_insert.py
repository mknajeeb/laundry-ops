"""Manual upload row insert — Washpro checkout override scope."""

from __future__ import annotations

import sys
import types
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.rinse_bag_completion import REASON_OK, REASON_RACK_SCAN_AFTER_CLEAN
from backend.rinse_combined_upload import insert_upload_batch_rows_from_orders_df


def _ensure_app_stubs():
    if "backend.app" in sys.modules and hasattr(sys.modules["backend.app"], "build_identity_key"):
        return
    stub = types.ModuleType("backend.app")
    stub.build_identity_key = lambda *a, **k: "|".join(str(x) for x in a)
    stub.parse_date_value = lambda x: x
    stub.table_has_column = lambda *a, **k: True
    sys.modules["backend.app"] = stub


class TestWashproManualUploadInsert(unittest.TestCase):
    BAG = "BAG12345"

    def setUp(self):
        _ensure_app_stubs()

    def tearDown(self):
        if "backend.app" in sys.modules and isinstance(sys.modules["backend.app"], types.ModuleType):
            mod = sys.modules["backend.app"]
            if not hasattr(mod, "Flask"):
                sys.modules.pop("backend.app", None)

    def _run_insert(self, cursor, *, rack_after_clean: bool, override_active: bool):
        schema = MagicMock(cap={"has_ticket_id": True})
        orders_df = pd.DataFrame(
            {
                "Date_Clean": [date(2026, 6, 2)],
                "Name_Clean": ["Completed Customer"],
                "Weight_Num": [0.0],
                "ServiceType": ["WF"],
                "RushType": ["RUSH"],
                "ticket_id": [self.BAG],
            }
        )

        def _classify(*args, **kwargs):
            from backend.manual_checkout_eligibility import classify_washpro_manual_checkout_row

            if not override_active:
                from backend.rinse_bag_completion import classify_portal_upload_row

                return classify_portal_upload_row(
                    ticket_id=self.BAG,
                    was_completed_before_upload=True,
                    has_active_staging=False,
                    row_date_before_batch=False,
                )
            return classify_washpro_manual_checkout_row(
                ticket_id=self.BAG,
                has_active_staging=False,
                row_date_before_batch=False,
                has_rack_scan_after_clean=rack_after_clean,
            )

        with (
            patch(
                "backend.rinse_bag_upload.find_active_staging_for_portal_upload",
                return_value=None,
            ),
            patch(
                "backend.manual_checkout_eligibility.classify_upload_row_for_checkout",
                side_effect=_classify,
            ),
            patch("backend.ta_helpers.table_has_column", return_value=True),
            patch("backend.ta_helpers.table_exists", return_value=True),
            patch(
                "backend.rinse_combined_upload.build_upload_duplicate_indexes",
                return_value=(set(), {}, 3),
            ),
        ):
            return insert_upload_batch_rows_from_orders_df(
                cursor,
                1,
                551,
                date(2026, 6, 2),
                orders_df,
                schema,
                set(),
                {},
                pre_existing_completed_bag_ids={self.BAG},
                is_auto_scrape=False,
            )

    def test_washpro_override_accepts_completed_without_rack_after(self):
        cursor = MagicMock()
        counts = self._run_insert(cursor, rack_after_clean=False, override_active=True)
        self.assertEqual(counts["rejected_rows"], 0)
        self.assertEqual(counts["rows_inserted"], 1)

    def test_washpro_override_rejects_rack_after_clean(self):
        cursor = MagicMock()
        counts = self._run_insert(cursor, rack_after_clean=True, override_active=True)
        self.assertEqual(counts["rejected_rows"], 1)


if __name__ == "__main__":
    unittest.main()
