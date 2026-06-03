"""At-vendor checkout override — tenant scope, manual + auto scrape."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.manual_checkout_eligibility import (
    REASON_ALREADY_FORCE_CHECKOUT,
    REASON_ALREADY_SENT_TO_RINSE,
    REASON_RACK_SCAN_AFTER_CLEAN,
    bag_has_rack_scan_after_clean,
    classify_at_vendor_checkout_row,
    classify_upload_row_for_checkout,
    staging_checkout_sent_reason,
)
from backend.manual_checkout_settings import (
    KEY_CHECKOUT_INCLUDE_COMPLETED,
    KEY_MANUAL_CHECKOUT_ACCEPT_COMPLETED,
    checkout_at_vendor_override_active,
    get_checkout_include_completed_if_at_vendor,
)
from backend.rinse_bag_completion import REASON_ALREADY_COMPLETED, REASON_OK


def _ev(rack, ts=None, scan_index=0, purpose=None):
    return {
        "rack": rack,
        "scanned_at_parsed": ts or datetime(2026, 6, 1, 10, 0),
        "scan_index": scan_index,
        "id": scan_index,
        "purpose": purpose,
    }


class TestCheckoutSettings(unittest.TestCase):
    def test_washpro_default_enabled_when_unset(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, None, {"slug": "washpro"}]
        with patch("backend.manual_checkout_settings.table_exists", return_value=True):
            self.assertTrue(get_checkout_include_completed_if_at_vendor(cursor, 1))

    def test_veewash_default_enabled_when_unset(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, None, {"slug": "veewash"}]
        with patch("backend.manual_checkout_settings.table_exists", return_value=True):
            self.assertTrue(get_checkout_include_completed_if_at_vendor(cursor, 3))

    def test_other_tenant_default_disabled_when_unset(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, None, {"slug": "otherco"}]
        with patch("backend.manual_checkout_settings.table_exists", return_value=True):
            self.assertFalse(get_checkout_include_completed_if_at_vendor(cursor, 99))

    def test_explicit_setting_overrides_default(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"svalue": "0"}
        with patch("backend.manual_checkout_settings.table_exists", return_value=True):
            self.assertFalse(get_checkout_include_completed_if_at_vendor(cursor, 1))

    def test_legacy_key_used_when_new_key_unset(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, {"svalue": "1"}]
        with patch("backend.manual_checkout_settings.table_exists", return_value=True):
            self.assertTrue(get_checkout_include_completed_if_at_vendor(cursor, 1))

    def test_override_active_for_auto_scrape_when_enabled(self):
        cursor = MagicMock()
        with patch(
            "backend.manual_checkout_settings.get_checkout_include_completed_if_at_vendor",
            return_value=True,
        ):
            self.assertTrue(checkout_at_vendor_override_active(cursor, 1))
            self.assertTrue(
                checkout_at_vendor_override_active(cursor, 3)
            )


class TestAtVendorCheckoutClassification(unittest.TestCase):
    BAG = "BAG12345"

    def test_clean_no_later_rack_accepted(self):
        st, reason = classify_at_vendor_checkout_row(
            ticket_id=self.BAG,
            has_active_staging=False,
            row_date_before_batch=False,
            has_rack_scan_after_clean=False,
            apply_rack_after_clean_rule=True,
        )
        self.assertEqual(st, "ACCEPTED")
        self.assertEqual(reason, REASON_OK)

    def test_clean_then_wf_rejected_when_rack_rule_applied(self):
        events = [
            _ev("Washpro Clean", datetime(2026, 6, 3, 8, 21), 1, "move-bag"),
            _ev("026-NY-WF", datetime(2026, 6, 3, 10, 0), 2, "move-bag"),
        ]
        self.assertTrue(bag_has_rack_scan_after_clean(events))
        st, reason = classify_at_vendor_checkout_row(
            ticket_id=self.BAG,
            has_active_staging=False,
            row_date_before_batch=False,
            has_rack_scan_after_clean=True,
            apply_rack_after_clean_rule=True,
        )
        self.assertEqual(st, "REJECTED_DUPLICATE")
        self.assertEqual(reason, REASON_RACK_SCAN_AFTER_CLEAN)

    def test_non_clean_rack_before_clean_not_rejected(self):
        from backend.manual_checkout_eligibility import find_rack_scan_after_clean_trigger

        events = [
            _ev("Washpro Clean", datetime(2026, 5, 20, 9, 14), 1, "move-bag"),
            _ev("020-NY-WF", datetime(2026, 6, 2, 21, 30), 2, "load-in"),
            _ev("020-NY-WF", datetime(2026, 6, 2, 23, 40), 1, "sent-to-vendor Last Scan"),
        ]
        self.assertFalse(bag_has_rack_scan_after_clean(events))
        self.assertIsNone(find_rack_scan_after_clean_trigger(events))

    def test_a8l82x92v2_prod_timeline_not_rejected(self):
        from backend.manual_checkout_eligibility import find_rack_scan_after_clean_trigger

        events = [
            _ev("Washpro Clean", datetime(2026, 5, 20, 9, 14), 1, "move-bag Last Scan"),
            _ev(None, datetime(2026, 6, 2, 21, 10), 3, "bag-picked-up"),
            _ev(None, datetime(2026, 6, 2, 21, 10), 4, "workitems-added"),
            _ev("020-NY-WF", datetime(2026, 6, 2, 21, 30), 2, "load-in"),
            _ev("020-NY-WF", datetime(2026, 6, 2, 23, 40), 1, "sent-to-vendor Last Scan"),
        ]
        self.assertFalse(bag_has_rack_scan_after_clean(events))
        self.assertIsNone(find_rack_scan_after_clean_trigger(events))

    def test_auto_scrape_ignores_rack_after_clean(self):
        st, reason = classify_at_vendor_checkout_row(
            ticket_id=self.BAG,
            has_active_staging=False,
            row_date_before_batch=False,
            has_rack_scan_after_clean=True,
            apply_rack_after_clean_rule=False,
        )
        self.assertEqual(st, "ACCEPTED")
        self.assertEqual(reason, REASON_OK)

    def test_sent_staging_excluded(self):
        st, reason = classify_at_vendor_checkout_row(
            ticket_id=self.BAG,
            has_active_staging=False,
            row_date_before_batch=False,
            has_rack_scan_after_clean=False,
            staging_sent_reason=REASON_ALREADY_SENT_TO_RINSE,
        )
        self.assertEqual(st, "REJECTED_DUPLICATE")
        self.assertEqual(reason, REASON_ALREADY_SENT_TO_RINSE)

    def test_force_checkout_excluded(self):
        reason = staging_checkout_sent_reason({"logistics_status": "FORCE_CHECKOUT"})
        self.assertEqual(reason, REASON_ALREADY_FORCE_CHECKOUT)

    def test_setting_off_uses_already_completed(self):
        cursor = MagicMock()
        with patch(
            "backend.manual_checkout_eligibility.checkout_at_vendor_override_active",
            return_value=False,
        ):
            st, reason = classify_upload_row_for_checkout(
                cursor,
                3,
                ticket_id=self.BAG,
                has_active_staging=False,
                row_date_before_batch=False,
                was_completed_before_upload=True,
                is_auto_scrape=False,
            )
        self.assertEqual(st, "REJECTED_DUPLICATE")
        self.assertEqual(reason, REASON_ALREADY_COMPLETED)

    def test_manual_completed_in_portal_accepted_when_override_on(self):
        cursor = MagicMock()
        with patch(
            "backend.manual_checkout_eligibility.checkout_at_vendor_override_active",
            return_value=True,
        ), patch(
            "backend.manual_checkout_eligibility._latest_staging_for_ticket",
            return_value=None,
        ), patch(
            "backend.manual_checkout_eligibility.load_bag_scan_timeline",
            return_value=[_ev("Washpro Clean")],
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

    def test_auto_scrape_completed_at_vendor_accepted_when_override_on(self):
        cursor = MagicMock()
        with patch(
            "backend.manual_checkout_eligibility.checkout_at_vendor_override_active",
            return_value=True,
        ), patch(
            "backend.manual_checkout_eligibility._latest_staging_for_ticket",
            return_value=None,
        ):
            st, reason = classify_upload_row_for_checkout(
                cursor,
                3,
                ticket_id=self.BAG,
                has_active_staging=False,
                row_date_before_batch=False,
                was_completed_before_upload=True,
                is_auto_scrape=True,
            )
        self.assertEqual(st, "ACCEPTED")
        self.assertEqual(reason, REASON_OK)

    def test_auto_scrape_ignores_stale_force_checkout_staging(self):
        cursor = MagicMock()
        with patch(
            "backend.manual_checkout_eligibility.checkout_at_vendor_override_active",
            return_value=True,
        ), patch(
            "backend.manual_checkout_eligibility._latest_staging_for_ticket",
            return_value={"logistics_status": "FORCE_CHECKOUT", "status": "FORCED_CHECKOUT"},
        ):
            st, reason = classify_upload_row_for_checkout(
                cursor,
                3,
                ticket_id=self.BAG,
                has_active_staging=False,
                row_date_before_batch=False,
                was_completed_before_upload=True,
                is_auto_scrape=True,
            )
        self.assertEqual(st, "ACCEPTED")
        self.assertEqual(reason, REASON_OK)

    def test_manual_still_excludes_force_checkout_staging(self):
        cursor = MagicMock()
        with patch(
            "backend.manual_checkout_eligibility.checkout_at_vendor_override_active",
            return_value=True,
        ), patch(
            "backend.manual_checkout_eligibility._latest_staging_for_ticket",
            return_value={"logistics_status": "FORCE_CHECKOUT"},
        ), patch(
            "backend.manual_checkout_eligibility.load_bag_scan_timeline",
            return_value=[],
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
        self.assertEqual(reason, REASON_ALREADY_FORCE_CHECKOUT)

    def test_checked_out_excluded_manual(self):
        cursor = MagicMock()
        with patch(
            "backend.manual_checkout_eligibility.checkout_at_vendor_override_active",
            return_value=True,
        ), patch(
            "backend.manual_checkout_eligibility._latest_staging_for_ticket",
            return_value={"logistics_status": "SENT_TO_RINSE"},
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
        self.assertEqual(reason, REASON_ALREADY_SENT_TO_RINSE)


class TestSettingKeys(unittest.TestCase):
    def test_key_names(self):
        self.assertEqual(
            KEY_CHECKOUT_INCLUDE_COMPLETED,
            "checkout_include_completed_if_at_vendor",
        )
        self.assertEqual(
            KEY_MANUAL_CHECKOUT_ACCEPT_COMPLETED,
            "manual_checkout_accept_completed_without_later_rack",
        )


if __name__ == "__main__":
    unittest.main()
