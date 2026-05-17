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
        self.assertEqual(r.work_date, date(2026, 5, 16))

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

    def test_work_date_fallback_to_folding_start(self):
        t0 = datetime(2026, 5, 20, 8, 0)
        t1 = datetime(2026, 5, 20, 9, 0)
        r = evaluate_folding_performance_for_bag(
            [
                _ev("FOLDING", "User", t0, 1, 1),
                _ev("CLEAN", "User", t1, 2, 2),
            ],
            registry_row={"date_clean": None},
        )
        self.assertEqual(r.work_date, date(2026, 5, 20))

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


if __name__ == "__main__":
    unittest.main()
