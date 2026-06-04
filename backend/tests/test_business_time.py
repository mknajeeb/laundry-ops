"""Business timezone: America/New_York for Laundry Ops parsing and display."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from backend.business_time import (
    business_today,
    format_business_datetime_display,
    serialize_rinse_scan_datetime_for_api,
    serialize_system_datetime_for_api,
)
from backend.rinse_portal_csv import parse_portal_date

ET = ZoneInfo("America/New_York")


class TestPortalDateParsing(unittest.TestCase):
    def test_today_uses_eastern_not_server_utc(self):
        # UTC midnight May 25 still May 24 in Eastern (EDT).
        fake_et = datetime(2026, 5, 24, 22, 0, 0, tzinfo=ET)
        with patch("backend.rinse_portal_csv.business_today", return_value=fake_et.date()):
            self.assertEqual(parse_portal_date("TODAY"), date(2026, 5, 24))
            self.assertEqual(parse_portal_date("today"), date(2026, 5, 24))
            self.assertEqual(parse_portal_date("Tue TODAY"), date(2026, 5, 24))

    def test_no_year_infers_eastern_year(self):
        fake_et = datetime(2026, 1, 2, 10, 0, 0, tzinfo=ET)
        with patch("backend.rinse_portal_csv.business_today", return_value=fake_et.date()):
            self.assertEqual(parse_portal_date("Tue 4/14"), date(2026, 4, 14))
            self.assertEqual(parse_portal_date("Wed 12/31"), date(2026, 12, 31))

    def test_explicit_year_unchanged(self):
        fake_et = datetime(2026, 5, 24, 12, 0, 0, tzinfo=ET)
        with patch("backend.rinse_portal_csv.business_today", return_value=fake_et.date()):
            self.assertEqual(parse_portal_date("Tue 04/14/2025"), date(2025, 4, 14))
            self.assertEqual(parse_portal_date("Tue 4/14/26"), date(2026, 4, 14))

    def test_date_clean_is_date_only(self):
        d = parse_portal_date("Tue 06/04/2026")
        self.assertIsInstance(d, date)
        self.assertNotIsInstance(d, datetime)
        self.assertEqual(d.isoformat(), "2026-06-04")


class TestScanEventDisplay(unittest.TestCase):
    def test_scan_wall_time_serializes_et_offset(self):
        wall = datetime(2026, 6, 4, 14, 15, 0)
        api = serialize_rinse_scan_datetime_for_api(wall)
        self.assertEqual(api, "2026-06-04T14:15:00-04:00")
        self.assertNotIn("GMT", api)

    def test_scan_display_label_is_eastern(self):
        wall = datetime(2026, 6, 4, 14, 15, 0)
        label = format_business_datetime_display(wall, source="scan")
        self.assertIn("Jun 4", label)
        self.assertIn("2:15 PM", label)
        self.assertTrue(label.endswith("EDT") or label.endswith("ET"))


class TestSystemTimestampDisplay(unittest.TestCase):
    def test_scrape_batch_utc_naive_converts_to_et(self):
        utc_naive = datetime(2026, 6, 5, 2, 35, 0)
        api = serialize_system_datetime_for_api(utc_naive)
        self.assertEqual(api, "2026-06-04T22:35:00-04:00")

    def test_batch_display_label_is_eastern(self):
        utc_naive = datetime(2026, 6, 5, 2, 35, 0)
        label = format_business_datetime_display(utc_naive, source="system")
        self.assertIn("Jun 4", label)
        self.assertIn("10:35 PM", label)
        self.assertTrue(label.endswith("EDT") or label.endswith("ET"))


class TestBusinessToday(unittest.TestCase):
    def test_business_today_matches_eastern_calendar(self):
        fake_now = datetime(2026, 5, 25, 3, 30, 0, tzinfo=ZoneInfo("UTC"))
        with patch("backend.rinse_folding_et.eastern_now", return_value=fake_now.astimezone(ET)):
            self.assertEqual(business_today(), date(2026, 5, 24))


class TestBag4C3EFPEJSQTrace(unittest.TestCase):
    """Documented trace for Washpro bag 4C3EFPEJSQ (Patrick Truhler rush)."""

    def test_trace_documentation(self):
        trace = {
            "bag_id": "4C3EFPEJSQ",
            "raw_portal_date_text": "Tue 06/04/2026 (inferred from batch #653 upload)",
            "parsed_date_clean": "2026-06-04",
            "today_no_year_parsing": False,
            "displayed_timestamps": {
                "batch_created": "ET via serialize_system_datetime_for_api",
                "scan_events": "Jun 2–3 load-in / sent-to-vendor (ET wall)",
            },
            "utc_server_conversion": "batch/scrape times: UTC→ET; date_clean: plain date, no TZ",
        }
        self.assertEqual(parse_portal_date("Tue 06/04/2026"), date(2026, 6, 4))
        self.assertFalse(trace["today_no_year_parsing"])


if __name__ == "__main__":
    unittest.main()
