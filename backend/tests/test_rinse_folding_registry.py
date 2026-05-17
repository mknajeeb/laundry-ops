"""Registry recompute, aggregates, and no upload hook."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.rinse_bag_completion import COMPLETION_COMPLETED, COMPLETION_INCOMPLETE
from backend.rinse_bag_folding import STATUS_CALCULATED, STATUS_EXCEPTION
from backend.rinse_folding_registry import (
    _rank_leaderboard_users,
    aggregate_folding_leaderboard,
    apply_folding_performance_for_bag,
    recompute_folding_performance_for_bags,
    summarize_recompute_results,
)
from backend.rinse_folding_settings import (
    DEFAULT_BAGS_PER_HOUR,
    DEFAULT_LBS_PER_HOUR,
    get_rinse_folding_benchmarks,
)


class TestApplyFoldingPerformance(unittest.TestCase):
    BAG = "5LCZ5RJ60E"

    def test_skips_incomplete_registry(self):
        cursor = MagicMock()
        with patch(
            "backend.rinse_folding_registry.get_registry_row",
            return_value={
                "bag_id": self.BAG,
                "completion_status": COMPLETION_INCOMPLETE,
            },
        ):
            out = apply_folding_performance_for_bag(cursor, 1, self.BAG)
        self.assertTrue(out.get("skipped"))
        self.assertEqual(out.get("reason"), "not_completed")

    def test_processes_completed_registry(self):
        cursor = MagicMock()
        t0 = datetime(2026, 5, 16, 10, 0)
        t1 = datetime(2026, 5, 16, 11, 0)
        with (
            patch(
                "backend.rinse_folding_registry.get_registry_row",
                return_value={
                    "bag_id": self.BAG,
                    "completion_status": COMPLETION_COMPLETED,
                    "weight_num": 12.5,
                    "date_clean": date(2026, 5, 16),
                },
            ),
            patch(
                "backend.rinse_folding_registry.fetch_persistent_scan_events_for_bag",
                return_value=[
                    {
                        "id": 1,
                        "rack": "FOLDING",
                        "user_name": "Sarah Kamran",
                        "scanned_at_parsed": t0,
                        "scan_index": 1,
                    },
                    {
                        "id": 2,
                        "rack": "CLEAN",
                        "user_name": "Training Account",
                        "scanned_at_parsed": t1,
                        "scan_index": 2,
                    },
                ],
            ),
            patch(
                "backend.rinse_folding_registry._upsert_performance_row",
                return_value=99,
            ) as mock_upsert,
        ):
            out = apply_folding_performance_for_bag(cursor, 1, self.BAG)
        self.assertFalse(out.get("skipped"))
        self.assertEqual(out["status"], STATUS_CALCULATED)
        mock_upsert.assert_called_once()


class TestBenchmarks(unittest.TestCase):
    def test_defaults(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        with patch("backend.rinse_folding_settings.table_exists", return_value=True):
            b = get_rinse_folding_benchmarks(cursor, 1)
        self.assertEqual(b["bags_per_hour_target"], DEFAULT_BAGS_PER_HOUR)
        self.assertEqual(b["lbs_per_hour_target"], DEFAULT_LBS_PER_HOUR)


class TestNoUploadHook(unittest.TestCase):
    def test_combined_upload_does_not_call_folding_recompute(self):
        import inspect

        from backend.rinse_combined_upload import commit_rinse_combined_upload

        source = inspect.getsource(commit_rinse_combined_upload)
        self.assertNotIn("folding", source.lower())
        self.assertNotIn("recompute_folding", source)


class TestAggregateStats(unittest.TestCase):
    def test_aggregate_excludes_exceptions(self):
        from backend.rinse_folding_registry import aggregate_user_folding_stats

        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {
                "bag_id": "B1",
                "duration_seconds": 3600,
                "weight_lbs": 10.0,
                "work_date": date(2026, 5, 16),
                "folding_start_at": datetime(2026, 5, 16, 8, 0),
                "folding_end_at": datetime(2026, 5, 16, 9, 0),
            },
        ]
        with (
            patch("backend.rinse_folding_registry.ensure_rinse_folding_tables"),
            patch(
                "backend.rinse_folding_registry.get_rinse_folding_benchmarks",
                return_value={"bags_per_hour_target": 2.5, "lbs_per_hour_target": 40.0},
            ),
        ):
            stats = aggregate_user_folding_stats(
                cursor,
                1,
                "Sarah Kamran",
                date(2026, 5, 16),
                date(2026, 5, 16),
            )
        self.assertEqual(stats["bag_count"], 1)
        self.assertEqual(stats["bags_per_hour"], 1.0)


class TestRecomputeSummary(unittest.TestCase):
    def test_summarize_counts(self):
        bags = [
            {"skipped": True, "reason": "not_completed"},
            {"skipped": True, "reason": "no_registry_row"},
            {"skipped": False, "status": STATUS_CALCULATED},
            {
                "skipped": False,
                "status": STATUS_CALCULATED,
                "exception_code": "MULTIPLE_FOLDING_SCANS",
            },
            {"skipped": False, "status": STATUS_EXCEPTION},
        ]
        s = summarize_recompute_results(bags)
        self.assertEqual(s["skipped_not_completed"], 1)
        self.assertEqual(s["errors"], 1)
        self.assertEqual(s["processed"], 3)
        self.assertEqual(s["calculated"], 2)
        self.assertEqual(s["warnings"], 1)
        self.assertEqual(s["exceptions"], 1)


class TestLeaderboardRanking(unittest.TestCase):
    def test_ranks_by_lbs_per_hour(self):
        users = [
            {"user_name": "A", "lbs_per_hour": 30, "bags_per_hour": 2, "total_lbs": 50, "bag_count": 5},
            {"user_name": "B", "lbs_per_hour": 50, "bags_per_hour": 1, "total_lbs": 80, "bag_count": 4},
            {"user_name": "C", "lbs_per_hour": 50, "bags_per_hour": 3, "total_lbs": 60, "bag_count": 6},
        ]
        ranked = _rank_leaderboard_users(users)
        self.assertEqual(ranked[0]["user_name"], "C")
        self.assertEqual(ranked[1]["user_name"], "B")
        self.assertEqual(ranked[0]["rank"], 1)

    def test_leaderboard_empty_prior_winner(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        with (
            patch("backend.rinse_folding_registry.ensure_rinse_folding_tables"),
            patch(
                "backend.rinse_folding_registry.get_rinse_folding_benchmarks",
                return_value={"bags_per_hour_target": 2.5, "lbs_per_hour_target": 40.0},
            ),
            patch("backend.rinse_folding_registry.list_folding_users_in_period", return_value=[]),
        ):
            out = aggregate_folding_leaderboard(
                cursor, 1, period="today", anchor=date(2026, 5, 16)
            )
        self.assertEqual(out["users"], [])
        self.assertFalse(out["prior_period_winner"]["available"])
        self.assertEqual(out["prior_period_winner"]["message"], "Not enough data yet")


if __name__ == "__main__":
    unittest.main()
