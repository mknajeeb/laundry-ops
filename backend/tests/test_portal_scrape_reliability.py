"""Portal scrape reliability: degraded/partial absence protection + helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from backend.rinse_portal_scrape_meta import (
    normalize_portal_scrape_meta,
    portal_scrape_meta_allows_absence_completion,
    validate_presence_empty_result,
)
from backend.rinse_scrape_subprocess_outcome import (
    FAILURE_PAGE_NAVIGATION_HANG,
    FAILURE_PLAYWRIGHT_HANG,
    classify_subprocess_failure,
)


class TestDegradedAbsenceGuard(unittest.TestCase):
    def test_natural_full_snapshot_allowed(self):
        self.assertTrue(
            portal_scrape_meta_allows_absence_completion(
                {
                    "stopped_reason": "no_next_page_ui",
                    "reached_max_pages": False,
                    "degraded": False,
                    "skipped_ticket_count": 0,
                    "source_inspected_complete": True,
                }
            )
        )

    def test_skipped_tickets_block_absence(self):
        self.assertFalse(
            portal_scrape_meta_allows_absence_completion(
                {
                    "stopped_reason": "completed_with_skipped_tickets",
                    "reached_max_pages": False,
                    "degraded": True,
                    "skipped_ticket_count": 1,
                    "skipped_tickets": [{"ticket_index": 3, "reason": "expand_timeout"}],
                    "source_inspected_complete": False,
                }
            )
        )

    def test_page_navigation_failed_blocks_absence(self):
        self.assertFalse(
            portal_scrape_meta_allows_absence_completion(
                {
                    "stopped_reason": "page_navigation_failed",
                    "reached_max_pages": False,
                    "page_navigation_failed": True,
                    "pages_scraped": 2,
                    "source_inspected_complete": False,
                }
            )
        )

    def test_source_inspected_complete_false_blocks(self):
        self.assertFalse(
            portal_scrape_meta_allows_absence_completion(
                {
                    "stopped_reason": "no_next_page_ui",
                    "source_inspected_complete": False,
                }
            )
        )

    def test_normalize_preserves_skipped(self):
        meta = normalize_portal_scrape_meta(
            {
                "stopped_reason": "completed_with_skipped_tickets",
                "reached_max_pages": False,
                "pages_scraped": 4,
                "skipped_ticket_count": 2,
                "skipped_tickets": [{"ticket_index": 1}, {"ticket_index": 2}],
                "degraded": True,
                "source_inspected_complete": False,
            }
        )
        assert meta is not None
        self.assertTrue(meta["degraded"])
        self.assertEqual(meta["skipped_ticket_count"], 2)
        self.assertFalse(meta["source_inspected_complete"])
        self.assertFalse(portal_scrape_meta_allows_absence_completion(meta))

    def test_degraded_empty_not_validated(self):
        ok, checks = validate_presence_empty_result(
            {
                "stopped_reason": "no_table_rows",
                "reached_max_pages": False,
                "page_loaded": True,
                "session_authenticated": True,
                "expected_status_in_url": True,
                "empty_table_detected": True,
                "degraded": True,
            },
            exit_code=0,
            parsed_row_count=0,
        )
        self.assertFalse(ok)
        self.assertFalse(checks["not_degraded"])


class TestOutcomeClassification(unittest.TestCase):
    def test_stuck_expand_diag(self):
        out = classify_subprocess_failure(
            returncode=-2,
            stalled=True,
            last_log_lines=[
                "[portal-diag] op=expandRowAndReadBag ticket=7 tr=8/25",
                "expandRowAndReadBag_timeout_25000ms",
            ],
        )
        self.assertEqual(out["failure_class"], FAILURE_PLAYWRIGHT_HANG)
        self.assertEqual(out["last_playwright_operation"], "expandRowAndReadBag")

    def test_page_goto_diag(self):
        out = classify_subprocess_failure(
            returncode=-2,
            stalled=True,
            last_log_lines=[
                "[portal-diag] op=page.goto page=3 url=https://www.rinse.com/cleanertickets/?page=3",
            ],
        )
        self.assertEqual(out["failure_class"], FAILURE_PAGE_NAVIGATION_HANG)

    def test_chromium_crash_signal(self):
        out = classify_subprocess_failure(
            returncode=-11,
            last_log_lines=["Segmentation fault"],
        )
        self.assertEqual(out["failure_class"], "chromium_crash")
        self.assertEqual(out["signal"], 11)


class TestBrowserRetryPolicySurface(unittest.TestCase):
    """Document expected retry outcomes via classifier (Node retry is integration)."""

    def test_first_failure_classifiable(self):
        out = classify_subprocess_failure(
            returncode=1,
            last_log_lines=[
                "[portal-diag] op=scrape_attempt_failed attempt=1 transient=1",
                "Target closed",
            ],
        )
        self.assertIsNotNone(out.get("failure_class") or out.get("portal_diag"))


if __name__ == "__main__":
    unittest.main()
