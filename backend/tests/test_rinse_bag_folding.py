"""Unit tests for folding performance evaluation."""

from __future__ import annotations

import unittest
from datetime import date, datetime

from backend.rinse_bag_folding import (
    EXCEPTION_CLEAN_BEFORE_FOLDING,
    EXCEPTION_INVALID_TIMESTAMPS,
    EXCEPTION_MISSING_ASSIGNED_USER,
    EXCEPTION_MISSING_CLEAN,
    EXCEPTION_MISSING_FOLDING,
    EXCEPTION_MISSING_SCAN_EVENTS,
    SOURCE_CLEAN_SCAN_FALLBACK,
    SOURCE_FOLDING_SCAN,
    STATUS_CALCULATED,
    STATUS_EXCEPTION,
    WARNING_MULTIPLE_CLEAN_SCANS,
    WARNING_MULTIPLE_FOLDING_SCANS,
    evaluate_folding_performance_for_bag,
)


def _ev(
    rack: str,
    user: str,
    at: datetime,
    scan_index: int = 1,
    ev_id: int = 1,
) -> dict:
    return {
        "id": ev_id,
        "rack": rack,
        "user_name": user,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


class TestEvaluateFoldingPerformance(unittest.TestCase):
    def test_folding_to_clean_calculated_folding_user(self):
        t0 = datetime(2026, 5, 16, 23, 10)
        t1 = datetime(2026, 5, 17, 14, 57)
        r = evaluate_folding_performance_for_bag(
            [
                _ev("003-NY-WF", "Mahmoudou Nduwayo", datetime(2026, 5, 16, 23, 4), 1, 1),
                _ev("FOLDING", "Sarah Kamran", t0, 2, 2),
                _ev("CLEAN", "Veewash Training Account", t1, 3, 3),
            ],
            registry_row={"date_clean": date(2026, 5, 16), "completion_status": "COMPLETED"},
        )
        self.assertEqual(r.status, STATUS_CALCULATED)
        self.assertEqual(r.assigned_user_name, "Sarah Kamran")
        self.assertEqual(r.assigned_user_name_source, SOURCE_FOLDING_SCAN)
        self.assertEqual(r.duration_seconds, int((t1 - t0).total_seconds()))
        self.assertEqual(r.work_date, date(2026, 5, 17))

    def test_clean_fallback_when_folding_user_blank(self):
        t0 = datetime(2026, 5, 16, 10, 0)
        t1 = datetime(2026, 5, 16, 11, 0)
        r = evaluate_folding_performance_for_bag(
            [
                _ev("Folding 1", "", t0, 1, 1),
                _ev("VeeWash Clean", "Mahmoudou Nduwayo", t1, 2, 2),
            ],
            registry_row={"date_clean": date(2026, 5, 16)},
        )
        self.assertEqual(r.status, STATUS_CALCULATED)
        self.assertEqual(r.assigned_user_name, "Mahmoudou Nduwayo")
        self.assertEqual(r.assigned_user_name_source, SOURCE_CLEAN_SCAN_FALLBACK)

    def test_training_account_on_folding_still_calculated(self):
        r = evaluate_folding_performance_for_bag(
            [
                _ev("FOLDING", "Training Account", datetime(2026, 5, 16, 10, 0), 1, 1),
                _ev("CLEAN", "Staff", datetime(2026, 5, 16, 11, 0), 2, 2),
            ],
            registry_row={"date_clean": date(2026, 5, 16)},
        )
        self.assertEqual(r.status, STATUS_CALCULATED)
        self.assertEqual(r.assigned_user_name, "Training Account")

    def test_missing_assigned_user(self):
        r = evaluate_folding_performance_for_bag(
            [
                _ev("FOLDING", "", datetime(2026, 5, 16, 10, 0), 1, 1),
                _ev("CLEAN", "  ", datetime(2026, 5, 16, 11, 0), 2, 2),
            ],
            registry_row={"date_clean": date(2026, 5, 16)},
        )
        self.assertEqual(r.status, STATUS_EXCEPTION)
        self.assertEqual(r.exception_code, EXCEPTION_MISSING_ASSIGNED_USER)

    def test_missing_scan_events_empty_timeline(self):
        r = evaluate_folding_performance_for_bag(
            [],
            registry_row={"date_clean": date(2026, 5, 16)},
        )
        self.assertEqual(r.status, STATUS_EXCEPTION)
        self.assertEqual(r.exception_code, EXCEPTION_MISSING_SCAN_EVENTS)

    def test_missing_folding(self):
        r = evaluate_folding_performance_for_bag(
            [_ev("CLEAN", "User", datetime(2026, 5, 16, 11, 0), 1, 1)],
            registry_row={"date_clean": date(2026, 5, 16)},
        )
        self.assertEqual(r.status, STATUS_EXCEPTION)
        self.assertEqual(r.exception_code, EXCEPTION_MISSING_FOLDING)

    def test_missing_clean_after_folding(self):
        r = evaluate_folding_performance_for_bag(
            [_ev("Washpro Folding Rack", "User", datetime(2026, 5, 16, 10, 0), 1, 1)],
            registry_row={"date_clean": date(2026, 5, 16)},
        )
        self.assertEqual(r.status, STATUS_EXCEPTION)
        self.assertEqual(r.exception_code, EXCEPTION_MISSING_CLEAN)

    def test_clean_before_folding(self):
        r = evaluate_folding_performance_for_bag(
            [
                _ev("CLEAN", "A", datetime(2026, 5, 16, 10, 0), 1, 1),
                _ev("FOLDING", "B", datetime(2026, 5, 16, 11, 0), 2, 2),
            ],
            registry_row={"date_clean": date(2026, 5, 16)},
        )
        self.assertEqual(r.status, STATUS_EXCEPTION)
        self.assertEqual(r.exception_code, EXCEPTION_CLEAN_BEFORE_FOLDING)

    def test_multiple_scans_soft_warning_still_calculated(self):
        t0 = datetime(2026, 5, 16, 10, 0)
        t1 = datetime(2026, 5, 16, 10, 30)
        t2 = datetime(2026, 5, 16, 11, 0)
        r = evaluate_folding_performance_for_bag(
            [
                _ev("FOLDING", "Folder A", t0, 1, 1),
                _ev("VeeWash Folding", "Folder B", datetime(2026, 5, 16, 10, 15), 2, 2),
                _ev("CLEAN", "X", t1, 3, 3),
                _ev("Rack Clean", "Y", t2, 4, 4),
            ],
            registry_row={"date_clean": date(2026, 5, 16)},
        )
        self.assertEqual(r.status, STATUS_CALCULATED)
        self.assertEqual(r.exception_code, WARNING_MULTIPLE_FOLDING_SCANS)
        self.assertEqual(r.duration_seconds, int((t1 - t0).total_seconds()))

    def test_multiple_clean_warning(self):
        t0 = datetime(2026, 5, 16, 10, 0)
        t1 = datetime(2026, 5, 16, 10, 30)
        t2 = datetime(2026, 5, 16, 11, 0)
        r = evaluate_folding_performance_for_bag(
            [
                _ev("FOLDING", "Folder", t0, 1, 1),
                _ev("CLEAN", "A", t1, 2, 2),
                _ev("Clean 1", "B", t2, 3, 3),
            ],
            registry_row={"date_clean": date(2026, 5, 16)},
        )
        self.assertEqual(r.status, STATUS_CALCULATED)
        self.assertEqual(r.exception_code, WARNING_MULTIPLE_CLEAN_SCANS)

    def test_work_date_uses_clean_end_not_portal_date(self):
        t0 = datetime(2026, 5, 17, 16, 16)
        t1 = datetime(2026, 5, 17, 16, 18)
        r = evaluate_folding_performance_for_bag(
            [
                _ev("FOLDING", "Sarah Kamran", t0, 1, 1),
                _ev("VeeWash Clean", "Train", t1, 2, 2),
            ],
            registry_row={"date_clean": date(2026, 5, 19)},
        )
        self.assertEqual(r.work_date, date(2026, 5, 17))
        self.assertNotEqual(r.work_date, date(2026, 5, 19))

    def test_invalid_timestamps(self):
        r = evaluate_folding_performance_for_bag(
            [
                {
                    "id": 1,
                    "rack": "FOLDING",
                    "user_name": "U",
                    "scanned_at_parsed": None,
                    "scan_index": 1,
                },
                _ev("CLEAN", "U", datetime(2026, 5, 16, 11, 0), 2, 2),
            ],
            registry_row={"date_clean": date(2026, 5, 16)},
        )
        self.assertEqual(r.status, STATUS_EXCEPTION)
        self.assertEqual(r.exception_code, EXCEPTION_INVALID_TIMESTAMPS)


class TestWorkDateFromScanTimestamps(unittest.TestCase):
    def test_portal_date_clean_ignored_calculated_uses_clean_end(self):
        folding_at = datetime(2026, 5, 17, 16, 16)
        clean_at = datetime(2026, 5, 17, 16, 18)
        r = evaluate_folding_performance_for_bag(
            [
                _ev("FOLDING", "Sarah Kamran", folding_at, 1, 1),
                _ev("VeeWash Clean", "Training", clean_at, 2, 2),
            ],
            registry_row={"date_clean": date(2026, 5, 19), "completion_status": "COMPLETED"},
        )
        self.assertEqual(r.status, STATUS_CALCULATED)
        self.assertEqual(r.work_date, date(2026, 5, 17))

    def test_missing_clean_uses_folding_start_date(self):
        folding_at = datetime(2026, 5, 17, 16, 16)
        r = evaluate_folding_performance_for_bag(
            [_ev("FOLDING", "Sarah Kamran", folding_at, 1, 1)],
            registry_row={"date_clean": date(2026, 5, 19)},
        )
        self.assertEqual(r.exception_code, EXCEPTION_MISSING_CLEAN)
        self.assertEqual(r.work_date, date(2026, 5, 17))

    def test_missing_folding_uses_clean_scan_not_date_clean(self):
        clean_at = datetime(2026, 5, 17, 16, 18)
        r = evaluate_folding_performance_for_bag(
            [_ev("VeeWash Clean", "User", clean_at, 1, 1)],
            registry_row={"date_clean": date(2026, 5, 19)},
        )
        self.assertEqual(r.exception_code, EXCEPTION_MISSING_FOLDING)
        self.assertEqual(r.work_date, date(2026, 5, 17))

    def test_clean_before_folding_uses_scan_timeline(self):
        clean_at = datetime(2026, 5, 16, 10, 0)
        folding_at = datetime(2026, 5, 16, 11, 0)
        r = evaluate_folding_performance_for_bag(
            [
                _ev("CLEAN", "A", clean_at, 1, 1),
                _ev("FOLDING", "B", folding_at, 2, 2),
            ],
            registry_row={"date_clean": date(2026, 5, 19)},
        )
        self.assertEqual(r.exception_code, EXCEPTION_CLEAN_BEFORE_FOLDING)
        self.assertEqual(r.work_date, date(2026, 5, 16))


class TestWorkDateWeekReporting(unittest.TestCase):
    """Dashboard/TV periods filter on rinse_folding_performance.work_date."""

    def _row_in_period(self, work_date: date, start: date, end: date) -> bool:
        return start <= work_date <= end

    def test_may_17_folding_in_week_may_11_17_not_may_18_24(self):
        work = date(2026, 5, 17)
        week_a_start, week_a_end = date(2026, 5, 11), date(2026, 5, 17)
        week_b_start, week_b_end = date(2026, 5, 18), date(2026, 5, 24)
        portal_date = date(2026, 5, 19)
        self.assertNotEqual(work, portal_date)
        self.assertTrue(self._row_in_period(work, week_a_start, week_a_end))
        self.assertFalse(self._row_in_period(work, week_b_start, week_b_end))

    def test_list_period_filter_matches_work_date(self):
        folding_at = datetime(2026, 5, 17, 16, 16)
        clean_at = datetime(2026, 5, 17, 16, 18)
        r = evaluate_folding_performance_for_bag(
            [
                _ev("FOLDING", "Sarah Kamran", folding_at, 1, 1),
                _ev("VeeWash Clean", "Train", clean_at, 2, 2),
            ],
            registry_row={"date_clean": date(2026, 5, 19)},
        )
        # Week Mon May 11 – Sun May 17 containing the folding scan day
        start, end = date(2026, 5, 11), date(2026, 5, 17)
        self.assertTrue(start <= r.work_date <= end)
        next_start, next_end = date(2026, 5, 18), date(2026, 5, 24)
        self.assertFalse(next_start <= r.work_date <= next_end)


if __name__ == "__main__":
    unittest.main()
