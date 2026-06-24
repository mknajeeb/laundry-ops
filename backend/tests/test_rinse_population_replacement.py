"""Tests for latest-scrape population replacement and canonical scan upsert."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.rinse_cleaner_ticket_presence import (
    PORTAL_STATUS_AT_VENDOR,
    PORTAL_STATUS_READY,
    apply_presence_scrape,
)
from backend.rinse_bag_registry import merge_scan_events_from_upload, upsert_scan_event_row


class TestPresencePopulationReplacement:
    @patch("backend.rinse_cleaner_ticket_presence._fetch_presence_row", return_value=None)
    @patch("backend.rinse_cleaner_ticket_presence.ensure_presence_tables")
    def test_dry_run_does_not_replace_population(self, _ensure, _fetch):
        cursor = MagicMock()
        cursor.fetchall.return_value = [{"bag_id": "OLD1"}]

        stats = apply_presence_scrape(
            cursor,
            3,
            portal_status=PORTAL_STATUS_READY,
            rows=[{"bag_id": "NEW1", "raw_row_json": {}}],
            dry_run=True,
            mark_missing=True,
        )

        assert stats["dry_run"] is True
        assert stats["rows_missing"] == 1
        assert not any(
            "INSERT INTO rinse_cleaner_ticket_presence" in str(c)
            for c in cursor.execute.call_args_list
        )

    def test_mark_missing_replacement_covered_by_presence_tests(self):
        """See test_mark_missing_deactivates_absent_rows in test_rinse_cleaner_ticket_presence."""
        from backend.tests import test_rinse_cleaner_ticket_presence as mod

        assert hasattr(mod.TestPresenceApplyDryRun, "test_mark_missing_deactivates_absent_rows")


class TestCanonicalScanUpsert:
    def test_reimport_metadata_merge_uses_null_safe_coalesce(self):
        import inspect

        from backend.rinse_bag_registry import upsert_scan_event_row

        src = inspect.getsource(upsert_scan_event_row)
        assert "COALESCE(NULLIF" in src
        assert "metadata_updated" in src or "return \"metadata_updated\"" in src

    def test_merge_counts_inserted_vs_already_present(self):
        cursor = MagicMock()

        def _upsert(_cursor, **kwargs):
            if kwargs.get("dedupe_key") == "dup":
                return "metadata_updated"
            return "inserted"

        df = pd.DataFrame(
            [
                {
                    "Bag ID": "BAG1",
                    "Scan Index": "1",
                    "Rack": "CLEAN",
                    "Time Scanned": "Friday 8:00 PM",
                    "User": "U",
                    "Purpose": "add-photos",
                    "Last Location": "",
                    "Last Scan": "",
                },
                {
                    "Bag ID": "BAG1",
                    "Scan Index": "2",
                    "Rack": "FOLDING",
                    "Time Scanned": "Friday 9:00 PM",
                    "User": "U",
                    "Purpose": "",
                    "Last Location": "",
                    "Last Scan": "",
                },
            ]
        )
        with patch("backend.rinse_bag_registry.ensure_rinse_bag_tables"), patch(
            "backend.rinse_bag_registry.ensure_rinse_bag_scan_events_dedupe_schema"
        ), patch("backend.rinse_bag_registry.upsert_scan_event_row", side_effect=_upsert), patch(
            "backend.rinse_bag_registry.compute_scan_event_dedupe_key",
            side_effect=lambda **k: "dup" if k.get("purpose") == "add-photos" else "new",
        ), patch(
            "backend.rinse_bag_registry.parse_rinse_scanned_at",
            return_value=datetime(2026, 6, 13, 20, 0),
        ):
            out = merge_scan_events_from_upload(cursor, 3, 100, df, "a.csv")

        assert out["events_inserted"] == 1
        assert out["events_already_present"] == 1
