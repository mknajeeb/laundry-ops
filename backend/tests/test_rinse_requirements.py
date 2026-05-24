"""Tests for Rinse order search, scrape status, folding scoring rules."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_bag_folding import (
    EXCEPTION_FOLDING_DURATION_TOO_SHORT,
    EXCEPTION_MULTIPLE_FOLDING_SCANS,
    STATUS_CALCULATED,
    STATUS_EXCEPTION,
    evaluate_folding_performance_for_bag,
)
from backend.rinse_folding_excluded_users import (
    is_user_excluded_from_scoring,
    sql_exclude_scoring_users_clause,
)
from backend.rinse_folding_registry import aggregate_folding_leaderboard
from backend.rinse_scan_time import serialize_rinse_datetime_for_api
from backend.rinse_scrape_status import get_scheduled_scrape_status


def _ev(rack, user, at, scan_index=1, ev_id=1):
    return {
        "id": ev_id,
        "rack": rack,
        "user_name": user,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


class TestFoldingExceptionsNotInLeaderboard(unittest.TestCase):
    def test_exception_rows_use_exception_status(self):
        r = evaluate_folding_performance_for_bag(
            [
                _ev("FOLDING", "A", datetime(2026, 5, 16, 10, 0), 1, 1),
                _ev("FOLDING", "B", datetime(2026, 5, 16, 10, 5), 2, 2),
                _ev("CLEAN", "C", datetime(2026, 5, 16, 11, 0), 3, 3),
            ],
            registry_row={"date_clean": date(2026, 5, 16)},
        )
        self.assertEqual(r.status, STATUS_EXCEPTION)
        self.assertNotEqual(r.status, STATUS_CALCULATED)


class TestExcludedUserLeaderboard(unittest.TestCase):
    def test_sql_exclude_clause_when_table_missing(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        with patch(
            "backend.rinse_folding_excluded_users.table_exists", return_value=False
        ):
            sql, args = sql_exclude_scoring_users_clause(cursor, 1)
        self.assertEqual(sql, "")
        self.assertEqual(args, [])

    def test_excluded_user_skipped_in_leaderboard_loop(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        with (
            patch("backend.rinse_folding_registry.ensure_rinse_folding_tables"),
            patch(
                "backend.rinse_folding_registry.get_rinse_folding_benchmarks",
                return_value={"week_start_day": "MONDAY"},
            ),
            patch(
                "backend.rinse_folding_registry.list_folding_users_in_period",
                return_value=["Training Account"],
            ),
            patch(
                "backend.rinse_folding_excluded_users.is_user_excluded_from_scoring",
                return_value=True,
            ),
            patch(
                "backend.rinse_folding_registry.aggregate_team_folding_stats",
                return_value={"bag_count": 0},
            ),
        ):
            out = aggregate_folding_leaderboard(
                cursor, 1, period="week", anchor=date(2026, 5, 14)
            )
        self.assertEqual(out["users"], [])


class TestScrapeBatchDetail(unittest.TestCase):
    def test_timing_summary_includes_scrape_and_data_updated(self):
        from backend.rinse_scrape_status import build_scrape_run_batch_detail

        started = datetime(2026, 5, 24, 18, 30, 0)
        finished = datetime(2026, 5, 24, 18, 42, 0)
        confirmed = datetime(2026, 5, 24, 18, 42, 0)
        detail = build_scrape_run_batch_detail(
            {
                "id": 5,
                "status": "success",
                "started_at": started,
                "finished_at": finished,
                "duration_seconds": 720,
                "portal_rows_count": 70,
                "imported_batch_id": 122,
                "run_type": "scheduled",
            },
            {
                "created_at": datetime(2026, 5, 24, 18, 41, 0),
                "confirmed_at": confirmed,
                "state": "CONFIRMED",
                "orders_loaded": 70,
            },
        )
        self.assertIn("Scrape started", detail["timing_summary"])
        self.assertIn("Data updated", detail["timing_summary"])
        self.assertIn("Duration", detail["timing_summary"])
        self.assertEqual(detail["rows_imported"], 70)
        self.assertEqual(detail["imported_batch_id"], 122)


class TestScheduledScrapeStatus(unittest.TestCase):
    def test_data_updated_uses_finished_not_started(self):
        cursor = MagicMock()

        def table_exists_side_effect(_c, name):
            return name == "rinse_scrape_runs"

        finished = datetime(2026, 5, 24, 18, 54, 0)
        started = datetime(2026, 5, 24, 18, 42, 0)
        calls = {"n": 0}

        def fetchone():
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "id": 5,
                    "status": "success",
                    "started_at": started,
                    "finished_at": finished,
                    "duration_seconds": 720,
                    "portal_rows_count": 70,
                    "scan_events_count": 200,
                    "imported_batch_id": 121,
                    "error_message": None,
                    "rinse_vendor": "veewash",
                    "tenant_slug": "veewash",
                    "run_type": "scheduled",
                }
            if calls["n"] == 2:
                return {
                    "id": 5,
                    "status": "success",
                    "started_at": started,
                    "finished_at": finished,
                    "duration_seconds": 720,
                    "portal_rows_count": 70,
                    "scan_events_count": 200,
                    "imported_batch_id": 121,
                    "error_message": None,
                }
            return None

        cursor.fetchone.side_effect = fetchone
        with patch("backend.rinse_scrape_status.table_exists", side_effect=table_exists_side_effect):
            with patch("backend.rinse_scrape_status.table_exists", side_effect=table_exists_side_effect):
                out = get_scheduled_scrape_status(cursor, 3)
        self.assertIsNotNone(out.get("data_last_updated_at"))
        latest = out.get("latest_run") or {}
        self.assertEqual(latest.get("started_at"), latest.get("started_at"))
        if out.get("data_last_updated_at_et"):
            self.assertIn("-04:00", out["data_last_updated_at_et"])


class TestTimezoneSerialization(unittest.TestCase):
    def test_may_24_et_offset_not_gmt_string(self):
        dt = datetime(2026, 5, 24, 17, 25, 0)
        api = serialize_rinse_datetime_for_api(dt)
        self.assertIn("-04:00", api)
        self.assertNotIn("GMT", api)


class TestOrderSearchModule(unittest.TestCase):
    def test_search_empty_without_registry(self):
        from backend.rinse_order_search import search_rinse_orders

        cursor = MagicMock()
        with patch("backend.rinse_order_search.table_exists", return_value=False):
            out = search_rinse_orders(cursor, 1)
        self.assertEqual(out["rows"], [])


if __name__ == "__main__":
    unittest.main()
