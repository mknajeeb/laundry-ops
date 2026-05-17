"""Registry recompute, aggregates, and upload hook."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_bag_completion import COMPLETION_COMPLETED, COMPLETION_INCOMPLETE
from backend.rinse_bag_folding import STATUS_CALCULATED, STATUS_EXCEPTION
from backend.rinse_folding_registry import (
    _rank_leaderboard_users,
    aggregate_folding_leaderboard,
    apply_folding_performance_for_bag,
    compute_folding_issue_metrics,
    folding_period_bounds,
    previous_period_bounds,
    recompute_folding_after_upload,
    recompute_folding_performance_for_bags,
    summarize_recompute_results,
)
from backend.rinse_folding_settings import (
    DEFAULT_BAGS_PER_HOUR,
    DEFAULT_ISSUE_FREE_PERCENT,
    DEFAULT_LBS_PER_HOUR,
    DEFAULT_MINUTES_PER_BAG,
    DEFAULT_WEEK_START_DAY,
    get_rinse_folding_benchmarks,
    put_rinse_folding_benchmarks,
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
        self.assertEqual(b["minutes_per_bag_target"], DEFAULT_MINUTES_PER_BAG)
        self.assertEqual(b["issue_free_percent_target"], DEFAULT_ISSUE_FREE_PERCENT)
        self.assertEqual(b["week_start_day"], DEFAULT_WEEK_START_DAY)

    def test_put_round_trip(self):
        store: dict[tuple[int, str], str] = {}

        def _get(cursor, org, key):
            return store.get((org, key))

        def _set(cursor, org, key, value):
            store[(org, key)] = value

        with (
            patch("backend.rinse_folding_settings.table_exists", return_value=True),
            patch("backend.rinse_folding_settings._get_setting", side_effect=_get),
            patch("backend.rinse_folding_settings._set_setting", side_effect=_set),
        ):
            out = put_rinse_folding_benchmarks(
                cursor=MagicMock(),
                organization_id=1,
                bags_per_hour=3.0,
                lbs_per_hour=45.0,
                minutes_per_bag=20.0,
                issue_free_percent=97.0,
                week_start_day="MONDAY",
            )
        self.assertEqual(out["bags_per_hour_target"], 3.0)
        self.assertEqual(out["minutes_per_bag_target"], 20.0)
        self.assertEqual(out["issue_free_percent_target"], 97.0)


class TestUploadHook(unittest.TestCase):
    def test_combined_upload_calls_folding_recompute(self):
        import inspect

        from backend.rinse_combined_upload import commit_rinse_combined_upload

        source = inspect.getsource(commit_rinse_combined_upload)
        self.assertIn("recompute_folding_after_upload", source)

    def test_recompute_after_upload_never_raises(self):
        cursor = MagicMock()
        with patch(
            "backend.rinse_folding_registry.recompute_folding_performance_for_bags",
            side_effect=RuntimeError("db down"),
        ):
            out = recompute_folding_after_upload(cursor, 1, ["BAG1"])
        self.assertFalse(out["ok"])
        self.assertIn("db down", out["error"])


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
                return_value={
                    "bags_per_hour_target": 2.5,
                    "lbs_per_hour_target": 40.0,
                    "issue_free_percent_target": 98.0,
                    "week_start_day": "MONDAY",
                },
            ),
            patch(
                "backend.rinse_folding_registry.compute_folding_issue_metrics",
                return_value={
                    "issue_count": 0,
                    "issue_free_percent": 100.0,
                    "issue_metric_available": True,
                    "issue_metric_source": "folding_performance",
                },
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

    def test_leaderboard_week_defaults_and_comparison(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        with (
            patch("backend.rinse_folding_registry.ensure_rinse_folding_tables"),
            patch(
                "backend.rinse_folding_registry.get_rinse_folding_benchmarks",
                return_value={
                    "bags_per_hour_target": 2.5,
                    "lbs_per_hour_target": 40.0,
                    "issue_free_percent_target": 98.0,
                    "week_start_day": "MONDAY",
                },
            ),
            patch("backend.rinse_folding_registry.list_folding_users_in_period", return_value=[]),
            patch(
                "backend.rinse_folding_registry.aggregate_team_folding_stats",
                return_value={"bag_count": 0, "issue_free_percent": None},
            ),
        ):
            out = aggregate_folding_leaderboard(
                cursor, 1, period="week", anchor=date(2026, 5, 14)
            )
        self.assertEqual(out["period"], "week")
        self.assertEqual(out["period_start"], "2026-05-11")
        self.assertEqual(out["period_end"], "2026-05-17")
        self.assertFalse(out["previous_team"]["available"])
        self.assertFalse(out["operational_issues"]["available"])


class TestPeriodBounds(unittest.TestCase):
    def test_week_starts_monday(self):
        start, end = folding_period_bounds("week", date(2026, 5, 14))
        self.assertEqual(start, date(2026, 5, 11))
        self.assertEqual(end, date(2026, 5, 17))

    def test_previous_month(self):
        start, end = folding_period_bounds("month", date(2026, 5, 14))
        prev_start, prev_end = previous_period_bounds("month", start, end)
        self.assertEqual(prev_start, date(2026, 4, 1))
        self.assertEqual(prev_end, date(2026, 4, 30))


class TestIssueMetrics(unittest.TestCase):
    def test_issue_free_percent(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {"status": STATUS_CALCULATED, "cnt": 8},
            {"status": STATUS_EXCEPTION, "cnt": 2},
        ]
        with patch("backend.rinse_folding_registry.ensure_rinse_folding_tables"):
            out = compute_folding_issue_metrics(
                cursor, 1, date(2026, 5, 1), date(2026, 5, 31)
            )
        self.assertEqual(out["issue_count"], 2)
        self.assertEqual(out["issue_free_percent"], 80.0)


if __name__ == "__main__":
    unittest.main()
