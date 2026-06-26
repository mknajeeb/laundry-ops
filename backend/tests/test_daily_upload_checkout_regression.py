"""
Regression gate for Washpro daily upload → confirm → rush checkout.

Run in CI on every main push. If you change upload confirm, operational owner,
scan merge, or rush checkout classification, update this file and
backend/daily_upload_checkout_contract.py together.
"""

from __future__ import annotations

import inspect
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from backend.checkout_batch_summary import build_checkout_batch_summary
from backend.daily_upload_checkout_contract import (
    assert_confirm_pipeline_wired,
    assert_finalize_scan_merge_wired,
    assert_portal_owner_gate_wired,
)
from backend.manual_checkout_eligibility import (
    classify_at_vendor_checkout_row,
    classify_upload_row_for_checkout,
    reclassify_checkout_batch_upload_rows,
    resolve_stale_portal_attention_rows_before_confirm,
)
from backend.rinse_bag_completion import REASON_ALREADY_COMPLETED, REASON_OK


class TestDailyUploadImportContract(unittest.TestCase):
    def test_resolve_stale_helper_is_importable(self):
        self.assertTrue(callable(resolve_stale_portal_attention_rows_before_confirm))

    def test_confirm_core_wires_resolve_then_reclassify(self):
        from backend.upload_batch_confirm import confirm_upload_batch_core

        assert_confirm_pipeline_wired(inspect.getsource(confirm_upload_batch_core))

    def test_staging_insert_uses_portal_credential_owner_gate(self):
        from backend.checkout_batch_staging import insert_staging_from_upload_row

        assert_portal_owner_gate_wired(
            inspect.getsource(insert_staging_from_upload_row),
            label="insert_staging_from_upload_row",
        )

    def test_registry_portal_upsert_uses_credential_owner_gate(self):
        from backend.rinse_bag_upload import upsert_registry_from_portal_row

        assert_portal_owner_gate_wired(
            inspect.getsource(upsert_registry_from_portal_row),
            label="upsert_registry_from_portal_row",
        )

    def test_finalize_replaces_scans_with_credential_owner(self):
        from backend.rinse_upload_finalize import finalize_rinse_after_batch_confirm

        assert_finalize_scan_merge_wired(inspect.getsource(finalize_rinse_after_batch_confirm))

    def test_scheduled_scrape_merges_persistent_scans_on_draft(self):
        from backend.rinse_combined_upload import commit_rinse_combined_upload

        src = inspect.getsource(commit_rinse_combined_upload)
        self.assertIn("is_auto_scrape", src)
        self.assertIn("merge_scan_events_from_upload", src)
        self.assertIn("replace_existing=True", src)
        self.assertIn("credential_sourced=True", src)


class TestRushCheckoutCompletedOnPortalToday(unittest.TestCase):
    """Jun 26 2026 prod: 8 rush bags excluded — registry completed but still on portal."""

    BAG = "E9ZDC1B7MW"
    BATCH_DATE = date(2026, 6, 26)

    def test_classify_accepts_completed_when_edd_is_batch_date(self):
        st, reason = classify_at_vendor_checkout_row(
            ticket_id=self.BAG,
            has_active_staging=False,
            row_date_before_batch=False,
            was_completed_before_upload=True,
        )
        self.assertEqual(st, "ACCEPTED")
        self.assertEqual(reason, REASON_OK)

    def test_classify_rejects_completed_only_when_edd_before_batch(self):
        st, reason = classify_at_vendor_checkout_row(
            ticket_id=self.BAG,
            has_active_staging=False,
            row_date_before_batch=True,
            was_completed_before_upload=True,
        )
        self.assertEqual(st, "REJECTED_DUPLICATE")
        self.assertEqual(reason, REASON_ALREADY_COMPLETED)

    def test_upload_classify_accepts_completed_today_when_override_on(self):
        cursor = MagicMock()
        with patch(
            "backend.manual_checkout_eligibility.checkout_at_vendor_override_active",
            return_value=True,
        ):
            st, reason = classify_upload_row_for_checkout(
                cursor,
                1,
                ticket_id=self.BAG,
                has_active_staging=False,
                row_date_before_batch=False,
                was_completed_before_upload=True,
                is_auto_scrape=False,
            )
        self.assertEqual(st, "ACCEPTED")
        self.assertEqual(reason, REASON_OK)

    def test_reclassify_promotes_rejected_completed_today_before_staging(self):
        cursor = MagicMock()
        row = {
            "id": 99,
            "ticket_id": self.BAG,
            "date_clean": self.BATCH_DATE,
            "row_status": "REJECTED_DUPLICATE",
            "reason": REASON_ALREADY_COMPLETED,
        }
        cursor.fetchone.side_effect = [
            {"batch_date": self.BATCH_DATE},
            None,
        ]
        cursor.fetchall.return_value = [row]

        with patch(
            "backend.ta_helpers.table_exists",
            return_value=True,
        ), patch(
            "backend.ta_helpers.table_has_column",
            return_value=True,
        ), patch(
            "backend.checkout_batch_source.upload_batch_is_auto_scrape",
            return_value=False,
        ), patch(
            "backend.manual_checkout_eligibility.get_checkout_include_completed_if_at_vendor",
            return_value=True,
        ), patch(
            "backend.manual_checkout_eligibility.effective_checkout_row_status",
            return_value=("ACCEPTED", REASON_OK),
        ):
            out = reclassify_checkout_batch_upload_rows(cursor, 1, 1712, dry_run=False)

        self.assertEqual(out["accepted"], 1)
        update_sql = str(cursor.execute.call_args_list[-1].args[0])
        self.assertIn("UPDATE upload_batch_rows", update_sql)
        self.assertEqual(cursor.execute.call_args_list[-1].args[1][0], "ACCEPTED")

    def test_rush_summary_not_excluded_when_effective_accepted_and_staged(self):
        from backend.tests.test_checkout_batch_summary import _mock_summary_cursor

        batch_rows = [
            {
                "ticket_id": self.BAG,
                "date_clean": self.BATCH_DATE,
                "name_clean": "Pedro Gomez Brooklyn Bouldering 0",
                "service_type": "WF",
                "rush_type": "RUSH",
                "row_status": "REJECTED_DUPLICATE",
                "reason": REASON_ALREADY_COMPLETED,
                "weight_num": None,
            },
        ]
        active_staging = [
            {
                "id": 1,
                "ticket_id": self.BAG,
                "name_clean": "Pedro Gomez Brooklyn Bouldering 0",
                "date_clean": self.BATCH_DATE,
                "service_type": "WF",
                "effective_rush": "RUSH",
                "status": "PENDING",
                "logistics_status": "AT_WASHPRO",
                "weight_num": None,
            },
        ]
        batch_meta = {
            "batch_id": 1712,
            "batch_date": self.BATCH_DATE,
            "confirmed_at": None,
        }

        cursor, mod, orig_te, orig_thc, auto_patch, override_patch = _mock_summary_cursor(
            batch_rows=batch_rows,
            active_staging=active_staging,
            batch_meta=batch_meta,
        )
        eff_patch = patch(
            "backend.manual_checkout_eligibility.effective_checkout_row_status",
            return_value=("ACCEPTED", REASON_OK),
        )
        try:
            eff_patch.start()
            out = build_checkout_batch_summary(cursor, 1, source="manual")
        finally:
            eff_patch.stop()
            override_patch.stop()
            auto_patch.stop()
            mod.table_exists = orig_te
            mod.table_has_column = orig_thc

        self.assertEqual(out["rush"]["total"], 1)
        self.assertEqual(out["rush"]["remaining"], 1)
        self.assertEqual(out["rush"]["excluded_not_staged"], 0)
        self.assertEqual(len(out["missing_rush_rows"]), 0)


class TestOperationalOwnerPortalCredential(unittest.TestCase):
    def test_credential_sourced_beats_cross_org_history(self):
        from backend.rinse_bag_operational_owner import (
            REJECT_REASON_NOT_OWNER,
            SOURCE_REGISTRY,
            CanonicalOwner,
            assert_operational_write_allowed,
        )
        from datetime import datetime

        canonical = CanonicalOwner(
            bag_id="E9ZDC1B7MW",
            owner_organization_id=3,
            owner_rinse_vendor="veewash",
            assigned_at=datetime(2026, 6, 1),
            assignment_source=SOURCE_REGISTRY,
        )
        with patch(
            "backend.rinse_bag_operational_owner.resolve_canonical_owner",
            return_value=canonical,
        ), patch(
            "backend.rinse_bag_operational_owner.operational_owner_gate_enabled",
            return_value=True,
        ), patch(
            "backend.rinse_bag_operational_owner.assign_owner_from_credential",
        ) as assign_cred:
            ok, reason, owner = assert_operational_write_allowed(
                object(), 1, "E9ZDC1B7MW", credential_sourced=True
            )
        self.assertTrue(ok)
        self.assertIsNone(reason)
        assign_cred.assert_called_once()
        self.assertNotEqual(reason, REJECT_REASON_NOT_OWNER)


if __name__ == "__main__":
    unittest.main()
