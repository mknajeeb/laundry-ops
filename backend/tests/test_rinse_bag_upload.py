"""Tests for Bag-ID–controlled Rinse portal upload / confirm helpers."""

from __future__ import annotations

import unittest

from backend.rinse_bag_completion import (
    REASON_ALREADY_COMPLETED,
    REASON_COMPLETED_NEEDS_CHECKOUT,
    REASON_OK,
    REASON_UPDATED_EXISTING_BAG,
    ROW_REJECTED,
    classify_portal_upload_row,
    confirm_staging_action,
)


class TestClassifyPortalUploadRow(unittest.TestCase):
    def test_completed_during_same_upload_not_rejected(self):
        """Registry may be COMPLETED after scan-events in this upload; row still accepted."""
        st, reason = classify_portal_upload_row(
            ticket_id="ABCD1234",
            was_completed_before_upload=False,
            has_active_staging=True,
            row_date_before_batch=False,
        )
        self.assertEqual(st, "ACCEPTED")
        self.assertEqual(reason, REASON_UPDATED_EXISTING_BAG)

    def test_new_bag_completed_during_same_upload_ok(self):
        st, reason = classify_portal_upload_row(
            ticket_id="NEWBAG99",
            was_completed_before_upload=False,
            has_active_staging=False,
            row_date_before_batch=False,
        )
        self.assertEqual(st, "ACCEPTED")
        self.assertEqual(reason, REASON_OK)

    def test_completed_bag_without_staging_accepted_for_checkout(self):
        st, reason = classify_portal_upload_row(
            ticket_id="ABCD1234",
            was_completed_before_upload=True,
            has_active_staging=False,
            row_date_before_batch=False,
        )
        self.assertEqual(st, "ACCEPTED")
        self.assertEqual(reason, REASON_COMPLETED_NEEDS_CHECKOUT)

    def test_completed_bag_with_active_staging_rejected(self):
        st, reason = classify_portal_upload_row(
            ticket_id="ABCD1234",
            was_completed_before_upload=True,
            has_active_staging=True,
            row_date_before_batch=False,
        )
        self.assertEqual(st, ROW_REJECTED)
        self.assertEqual(reason, REASON_ALREADY_COMPLETED)

    def test_incomplete_with_staging_accepted_updated(self):
        st, reason = classify_portal_upload_row(
            ticket_id="ABCD1234",
            was_completed_before_upload=False,
            has_active_staging=True,
            row_date_before_batch=False,
        )
        self.assertEqual(st, "ACCEPTED")
        self.assertEqual(reason, REASON_UPDATED_EXISTING_BAG)

    def test_new_bag_ok(self):
        st, reason = classify_portal_upload_row(
            ticket_id="NEWBAG01",
            was_completed_before_upload=False,
            has_active_staging=False,
            row_date_before_batch=False,
        )
        self.assertEqual(st, "ACCEPTED")
        self.assertEqual(reason, REASON_OK)


class TestConfirmStagingAction(unittest.TestCase):
    BAG = "ABCD1234"

    def test_completed_with_active_staging_blocks(self):
        self.assertEqual(
            confirm_staging_action(
                ticket_id=self.BAG,
                was_completed_before_upload=True,
                has_active_staging=True,
            ),
            "BLOCK",
        )

    def test_completed_without_staging_inserts(self):
        self.assertEqual(
            confirm_staging_action(
                ticket_id=self.BAG,
                was_completed_before_upload=True,
                has_active_staging=False,
            ),
            "INSERT_STAGING",
        )

    def test_incomplete_updates_existing_staging(self):
        self.assertEqual(
            confirm_staging_action(
                ticket_id=self.BAG,
                was_completed_before_upload=False,
                has_active_staging=True,
            ),
            "UPDATE_STAGING",
        )

    def test_new_bag_inserts(self):
        self.assertEqual(
            confirm_staging_action(
                ticket_id=self.BAG,
                was_completed_before_upload=False,
                has_active_staging=False,
            ),
            "INSERT_STAGING",
        )

    def test_no_ticket_id_uses_identity_path(self):
        self.assertEqual(
            confirm_staging_action(
                ticket_id=None,
                was_completed_before_upload=False,
                has_active_staging=False,
            ),
            "USE_IDENTITY_PATH",
        )


class TestLegacyDuplicateSkippedForTicketId(unittest.TestCase):
    """Document: rows with ticket_id must not use identity-key duplicate in commit_draft (integration)."""

    def test_confirm_action_distinct_from_identity(self):
        self.assertEqual(
            confirm_staging_action(
                ticket_id="ABCD1234",
                was_completed_before_upload=False,
                has_active_staging=False,
            ),
            "INSERT_STAGING",
        )


if __name__ == "__main__":
    unittest.main()
