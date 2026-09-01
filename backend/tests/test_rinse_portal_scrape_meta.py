"""Portal scrape metadata and portal absence safety guard."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.rinse_portal_absence_completion import complete_bags_missing_from_latest_portal
from backend.rinse_portal_scrape_meta import (
    apply_ship_window_discovery_meta,
    fetch_portal_scrape_meta_for_batch,
    load_portal_scrape_meta_file,
    meta_path_for_portal_csv,
    normalize_portal_scrape_meta,
    portal_scrape_meta_allows_absence_completion,
    persist_portal_scrape_meta_on_batch,
    validate_presence_empty_result,
)


class TestPortalScrapeMetaAllowsAbsence(unittest.TestCase):
    def test_ship_window_discovery_never_allows_absence(self):
        """Rolling STV window traversal must not authorize Missing From Portal."""
        self.assertFalse(
            portal_scrape_meta_allows_absence_completion(
                {
                    "stopped_reason": "no_next_page_ui",
                    "reached_max_pages": False,
                    "pages_scraped": 6,
                    "source_inspected_complete": True,
                    "source_mode": "ship_to_vendor_window",
                    "absence_capable": False,
                    "tickets_sources": [
                        {
                            "label": "wash_and_fold",
                            "url": (
                                "https://www.rinse.com/cleanertickets/?"
                                "status=any&service_types=wash_and_fold"
                                "&ship_to_vendor_date_start=2026-08-30"
                                "&ship_to_vendor_date_end=2026-08-31"
                            ),
                        }
                    ],
                }
            )
        )

    def test_completeness_guard_blocks_absence(self):
        self.assertFalse(
            portal_scrape_meta_allows_absence_completion(
                {
                    "stopped_reason": "no_next_page_ui",
                    "source_inspected_complete": True,
                    "completeness_guard": {
                        "trustworthy": False,
                        "allow_mark_missing": False,
                        "reason": "row_count_drop:135<0.60*230",
                    },
                }
            )
        )

    def test_manual_upload_no_meta_allowed(self):
        self.assertTrue(portal_scrape_meta_allows_absence_completion(None))

    def test_natural_stop_no_next_page_allowed(self):
        self.assertTrue(
            portal_scrape_meta_allows_absence_completion(
                {
                    "stopped_reason": "no_next_page_ui",
                    "reached_max_pages": False,
                    "pages_scraped": 3,
                    "source_inspected_complete": True,
                }
            )
        )

    def test_natural_stop_without_explicit_complete_blocked(self):
        """Aug27 incident: no_next_page_ui alone must not authorize absence."""
        self.assertFalse(
            portal_scrape_meta_allows_absence_completion(
                {
                    "stopped_reason": "no_next_page_ui",
                    "reached_max_pages": False,
                    "pages_scraped": 2,
                    "row_count": 45,
                }
            )
        )

    def test_max_pages_reached_not_allowed(self):
        self.assertFalse(
            portal_scrape_meta_allows_absence_completion(
                {
                    "stopped_reason": "max_pages_reached",
                    "reached_max_pages": True,
                    "pages_scraped": 20,
                }
            )
        )

    def test_skipped_tickets_not_allowed(self):
        self.assertFalse(
            portal_scrape_meta_allows_absence_completion(
                {
                    "stopped_reason": "completed_with_skipped_tickets",
                    "degraded": True,
                    "skipped_ticket_count": 1,
                }
            )
        )

    def test_load_meta_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "portal.csv.meta.json"
            p.write_text(
                json.dumps(
                    {
                        "stopped_reason": "duplicate_bag_set",
                        "reached_max_pages": False,
                        "pages_scraped": 5,
                    }
                ),
                encoding="utf-8",
            )
            meta = load_portal_scrape_meta_file(p)
            self.assertIsNotNone(meta)
            self.assertFalse(meta["reached_max_pages"])
            self.assertEqual(meta["stopped_reason"], "duplicate_bag_set")

    def test_meta_path_for_portal_csv(self):
        self.assertEqual(
            meta_path_for_portal_csv("/data/runs/portal.csv").name,
            "portal.csv.meta.json",
        )

    def test_fetch_meta_none_for_legacy_full_snapshot_without_json(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "portal_scrape_meta": None,
            "full_snapshot": 1,
        }
        with patch(
            "backend.rinse_portal_scrape_meta.table_exists",
            return_value=True,
        ), patch(
            "backend.rinse_portal_scrape_meta.table_has_column",
            return_value=True,
        ):
            meta = fetch_portal_scrape_meta_for_batch(cursor, 493, 3)
        self.assertIsNone(meta)
        self.assertTrue(portal_scrape_meta_allows_absence_completion(meta))

    def test_normalize_preserves_ship_window_discovery_fields(self):
        raw = {
            "stopped_reason": "no_next_page_ui",
            "source_mode": "ship_to_vendor_window",
            "absence_capable": False,
            "tickets_sources": [
                {"label": "wash_and_fold", "url": "x?ship_to_vendor_date_start=1"}
            ],
            "source_inspected_complete": True,
        }
        norm = normalize_portal_scrape_meta(raw)
        self.assertEqual(norm["source_mode"], "ship_to_vendor_window")
        self.assertFalse(norm["absence_capable"])
        self.assertFalse(portal_scrape_meta_allows_absence_completion(norm))

    def test_apply_ship_window_discovery_meta_blocks_absence(self):
        sources = [
            {
                "label": "wash_and_fold",
                "url": "https://example/?ship_to_vendor_date_start=2026-08-30",
            }
        ]
        meta = apply_ship_window_discovery_meta(
            {"source_inspected_complete": True, "stopped_reason": "no_next_page_ui"},
            sources,
        )
        self.assertEqual(meta["source_mode"], "ship_to_vendor_window")
        self.assertFalse(meta["absence_capable"])
        self.assertFalse(portal_scrape_meta_allows_absence_completion(meta))


class TestValidatePresenceEmptyResult(unittest.TestCase):
    def test_validated_empty_requires_scrape_flags(self):
        validated, checks = validate_presence_empty_result(
            {
                "stopped_reason": "no_table_rows",
                "reached_max_pages": False,
                "page_loaded": True,
                "session_authenticated": True,
                "expected_status_in_url": True,
                "empty_table_detected": True,
            },
            exit_code=0,
            parsed_row_count=0,
        )
        self.assertTrue(validated)
        self.assertTrue(all(checks.values()))

    def test_legacy_meta_without_flags_not_validated(self):
        validated, _checks = validate_presence_empty_result(
            {"stopped_reason": "no_table_rows", "reached_max_pages": False},
            exit_code=0,
            parsed_row_count=0,
        )
        self.assertFalse(validated)

    def test_nonzero_rows_not_validated(self):
        validated, _checks = validate_presence_empty_result(
            {"stopped_reason": "no_next_page_ui"},
            exit_code=0,
            parsed_row_count=3,
        )
        self.assertFalse(validated)


class TestPortalAbsenceSkippedOnMaxPages(unittest.TestCase):
    def test_absence_skipped_partial_scrape(self):
        cursor = MagicMock()
        accepted = [{"ticket_id": "BAGB"}]
        with (
            patch(
                "backend.rinse_portal_absence_completion.fetch_portal_scrape_meta_for_batch",
                return_value={
                    "stopped_reason": "max_pages_reached",
                    "reached_max_pages": True,
                    "pages_scraped": 20,
                    "max_pages_limit": 20,
                },
            ),
            patch(
                "backend.rinse_portal_absence_completion.verify_and_resolve_portal_departure_bag"
            ) as mock_verify,
        ):
            out = complete_bags_missing_from_latest_portal(
                cursor, 3, 122, accepted
            )
        self.assertTrue(out["skipped"])
        self.assertEqual(out["reason"], "partial_portal_scrape_max_pages")
        self.assertEqual(out["count"], 0)
        mock_verify.assert_not_called()

    def test_persist_sets_full_snapshot_zero_on_max_pages(self):
        cursor = MagicMock()
        with patch(
            "backend.rinse_portal_scrape_meta.table_has_column",
            return_value=True,
        ), patch(
            "backend.rinse_portal_scrape_meta.table_exists",
            return_value=True,
        ):
            out = persist_portal_scrape_meta_on_batch(
                cursor,
                99,
                3,
                {
                    "stopped_reason": "max_pages_reached",
                    "reached_max_pages": True,
                    "pages_scraped": 20,
                    "max_pages_limit": 20,
                },
            )
        self.assertFalse(out["full_snapshot"])
        self.assertFalse(out["portal_absence_allowed"])
        sql = cursor.execute.call_args[0][0]
        self.assertIn("full_snapshot", sql)
        args = cursor.execute.call_args[0][1]
        self.assertEqual(args[0], 0)
