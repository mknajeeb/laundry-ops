"""Scan timeline merge must not wipe later persisted events with truncated scrapes."""

from __future__ import annotations

from datetime import datetime

from backend.rinse_bag_registry import _should_replace_scan_timeline
from backend.rinse_scan_freshness import (
    bag_scan_chronology_is_stale,
    build_scan_data_freshness,
)


T_EARLY = datetime(2026, 7, 22, 8, 39)
T_LATE = datetime(2026, 7, 22, 14, 59)
T_PORTAL = datetime(2026, 7, 22, 19, 48)


class TestShouldReplaceScanTimeline:
    def test_allows_replace_when_incoming_is_newer(self):
        assert (
            _should_replace_scan_timeline(
                existing_max=T_EARLY,
                existing_n=16,
                incoming_max=T_LATE,
                incoming_n=20,
            )
            is True
        )

    def test_preserves_when_incoming_max_is_older(self):
        assert (
            _should_replace_scan_timeline(
                existing_max=T_LATE,
                existing_n=20,
                incoming_max=T_EARLY,
                incoming_n=16,
            )
            is False
        )

    def test_preserves_when_incoming_is_thinner_at_same_max(self):
        assert (
            _should_replace_scan_timeline(
                existing_max=T_EARLY,
                existing_n=19,
                incoming_max=T_EARLY,
                incoming_n=10,
            )
            is False
        )

    def test_scans_after_drying_are_kept_when_scrape_stops_at_drying(self):
        """Regression: drying Last Scan export must not erase later complete-cleaning."""
        assert (
            _should_replace_scan_timeline(
                existing_max=T_LATE,
                existing_n=23,
                incoming_max=T_EARLY,
                incoming_n=16,
            )
            is False
        )


class TestScanFreshness:
    def test_stale_when_portal_last_seen_hours_after_last_scan(self):
        assert bag_scan_chronology_is_stale(last_scan_at=T_EARLY, portal_last_seen_at=T_PORTAL)

    def test_partial_scrape_disables_pending_trust(self):
        out = build_scan_data_freshness(
            selected_date_et=T_EARLY.date(),
            shift_last_sync_at=T_PORTAL,
            most_recent_persisted_scan_at=T_EARLY,
            partial_portal_scrape=True,
        )
        assert out["status"] == "incomplete_scrape"
        assert out["trust_pending_from_missing_completion"] is False

    def test_stale_chronology_disables_pending_trust(self):
        out = build_scan_data_freshness(
            selected_date_et=T_EARLY.date(),
            shift_last_sync_at=T_PORTAL,
            most_recent_persisted_scan_at=T_EARLY,
            bags_with_stale_chronology=["15M7MCEK4J"],
        )
        assert out["status"] == "scan_chronology_stale"
        assert out["trust_pending_from_missing_completion"] is False


class TestLoadScansNoLimit:
    def test_load_scans_sql_has_no_limit(self):
        import inspect
        import re

        from backend.rinse_veewash_step1_api import load_scans_for_bags

        src = inspect.getsource(load_scans_for_bags)
        # Strip docstring so "no SQL LIMIT" wording does not false-positive.
        body = re.sub(r'""".*?"""', "", src, count=1, flags=re.S)
        assert "LIMIT" not in body.upper()
        assert "ORDER BY scanned_at_parsed ASC" in body


class TestStaleChronologyPromotesFromPending:
    def test_pending_bag_with_stale_scans_moves_to_review(self):
        from datetime import date

        from backend.rinse_veewash_review import expand_review_required
        from backend.rinse_veewash_workload import REASON_SCAN_CHRONOLOGY_STALE

        result = {
            "new_today": ["15M7MCEK4J"],
            "carryover": [],
            "completed_on_date": [],
            "pending_end_of_date": ["15M7MCEK4J"],
            "review_required": [],
            "disappeared_without_completion_exceptions": [],
            "rows": [
                {
                    "bag_id": "15M7MCEK4J",
                    "service_type": "WF",
                    "outcome": "pending",
                    "final_bucket": "pending",
                }
            ],
        }
        out = expand_review_required(
            result,
            selected_date_et=date(2026, 7, 22),
            presence_by_bag={
                "15M7MCEK4J": {
                    "service_type": "WF",
                    "active": 1,
                    "last_seen_at": T_PORTAL,
                    "rush_flag": "Rush",
                }
            },
            entry_by_bag={},
            last_scan_at_by_bag={"15M7MCEK4J": T_EARLY},
        )
        assert "15M7MCEK4J" in out["review_required"]
        assert "15M7MCEK4J" not in out["pending_end_of_date"]
        assert REASON_SCAN_CHRONOLOGY_STALE in (out["review_reasons_by_bag"].get("15M7MCEK4J") or [])
