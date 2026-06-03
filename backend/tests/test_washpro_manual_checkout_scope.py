"""Washpro manual checkout override — tenant scope and setting gate."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.manual_checkout_eligibility import (
    REASON_ALREADY_FORCE_CHECKOUT,
    REASON_ALREADY_SENT_TO_RINSE,
    REASON_RACK_SCAN_AFTER_CLEAN,
    bag_has_rack_scan_after_clean,
    classify_upload_row_for_checkout,
    classify_washpro_manual_checkout_row,
    staging_checkout_sent_reason,
)
from backend.manual_checkout_settings import (
    KEY_MANUAL_CHECKOUT_ACCEPT_COMPLETED,
    get_manual_checkout_accept_completed_without_later_rack,
    washpro_manual_checkout_override_active,
)
from backend.rinse_bag_completion import REASON_ALREADY_COMPLETED, REASON_OK


def _ev(rack, ts=None, scan_index=0):
    return {
        "rack": rack,
        "scanned_at_parsed": ts or datetime(2026, 6, 1, 10, 0),
        "scan_index": scan_index,
        "id": scan_index,
    }


class TestManualCheckoutSettings(unittest.TestCase):
    def test_washpro_default_enabled_when_unset(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, {"slug": "washpro"}]
        with patch("backend.manual_checkout_settings.table_exists", return_value=True):
            self.assertTrue(get_manual_checkout_accept_completed_without_later_rack(cursor, 1))

    def test_veewash_default_disabled_when_unset(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, {"slug": "veewash"}]
        with patch("backend.manual_checkout_settings.table_exists", return_value=True):
            self.assertFalse(get_manual_checkout_accept_completed_without_later_rack(cursor, 3))

    def test_explicit_setting_overrides_default(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"svalue": "0"}
        with patch("backend.manual_checkout_settings.table_exists", return_value=True):
            self.assertFalse(get_manual_checkout_accept_completed_without_later_rack(cursor, 1))

    def test_override_inactive_for_auto_scrape(self):
        cursor = MagicMock()
        with patch(
            "backend.manual_checkout_settings.get_manual_checkout_accept_completed_without_later_rack",
            return_value=True,
        ):
            self.assertFalse(
                washpro_manual_checkout_override_active(cursor, 1, is_auto_scrape=True)
            )


class TestWashproManualCheckoutClassification(unittest.TestCase):
    BAG = "BAG12345"

    def test_clean_no_later_rack_accepted(self):
        st, reason = classify_washpro_manual_checkout_row(
            ticket_id=self.BAG,
            has_active_staging=False,
            row_date_before_batch=False,
            has_rack_scan_after_clean=False,
        )
        self.assertEqual(st, "ACCEPTED")
        self.assertEqual(reason, REASON_OK)

    def test_clean_then_wf_rejected(self):
        events = [_ev("VeeWash Clean"), _ev("026-NY-WF")]
        self.assertTrue(bag_has_rack_scan_after_clean(events))
        st, reason = classify_washpro_manual_checkout_row(
            ticket_id=self.BAG,
            has_active_staging=False,
            row_date_before_batch=False,
            has_rack_scan_after_clean=True,
        )
        self.assertEqual(st, "REJECTED_DUPLICATE")
        self.assertEqual(reason, REASON_RACK_SCAN_AFTER_CLEAN)

    def test_sent_staging_excluded(self):
        st, reason = classify_washpro_manual_checkout_row(
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
            "backend.manual_checkout_eligibility.washpro_manual_checkout_override_active",
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

    def test_auto_scrape_unchanged(self):
        cursor = MagicMock()
        with patch(
            "backend.manual_checkout_eligibility.washpro_manual_checkout_override_active",
            return_value=False,
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
        self.assertEqual(reason, REASON_ALREADY_COMPLETED)


class TestSettingKey(unittest.TestCase):
    def test_key_name(self):
        self.assertEqual(
            KEY_MANUAL_CHECKOUT_ACCEPT_COMPLETED,
            "manual_checkout_accept_completed_without_later_rack",
        )


if __name__ == "__main__":
    unittest.main()
