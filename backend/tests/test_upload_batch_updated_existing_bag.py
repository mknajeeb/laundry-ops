"""Regression: active staging + incomplete registry => UPDATED_EXISTING_BAG."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_bag_completion import REASON_OK, REASON_UPDATED_EXISTING_BAG
from backend.rinse_bag_upload import find_active_staging_for_portal_upload


class TestFindActiveStagingForPortalUpload(unittest.TestCase):
    BAG = "DPFNODROJ5"

    def test_identity_fallback_when_ticket_id_not_on_staging(self):
        cursor = MagicMock()
        with (
            patch(
                "backend.rinse_bag_upload.find_active_staging_by_ticket_id",
                return_value=None,
            ),
            patch(
                "backend.rinse_bag_upload.table_exists",
                side_effect=lambda _c, t: t != "rinse_bag_registry",
            ),
            patch("backend.rinse_bag_upload.table_has_column", return_value=True),
            patch(
                "backend.rinse_bag_upload.find_active_staging_by_identity",
                return_value={"id": 4450},
            ),
        ):
            hit = find_active_staging_for_portal_upload(
                cursor,
                3,
                self.BAG,
                "1=1",
                has_staging_org=True,
                portal_row={
                    "name_clean": "Awais Hussain 0",
                    "weight_num": None,
                    "service_type": "WF",
                    "date_clean": date(2026, 5, 26),
                },
            )
        self.assertEqual(hit["id"], 4450)

    def test_classify_updated_when_staging_hit(self):
        from backend.rinse_bag_completion import classify_portal_upload_row

        st, reason = classify_portal_upload_row(
            ticket_id=self.BAG,
            was_completed_before_upload=False,
            has_active_staging=True,
            row_date_before_batch=False,
        )
        self.assertEqual(st, "ACCEPTED")
        self.assertEqual(reason, REASON_UPDATED_EXISTING_BAG)
        self.assertNotEqual(reason, REASON_OK)


if __name__ == "__main__":
    unittest.main()
