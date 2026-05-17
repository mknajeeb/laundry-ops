"""Unit tests for Rinse bag progressive-timeline completion rule."""

from __future__ import annotations

import unittest
from datetime import datetime

from backend.rinse_bag_completion import (
    COMPLETION_COMPLETED,
    COMPLETION_INCOMPLETE,
    REASON_CLEAN_WITHOUT_PRIOR_WORKFLOW,
    REASON_NO_CLEAN_SCAN,
    REASON_WORKFLOW_THEN_CLEAN,
    TRIGGER_PRIOR_WORKFLOW_BEFORE_CLEAN,
    evaluate_bag_completion,
    normalize_bag_id,
    rack_contains_clean,
    user_is_internal,
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


class TestNormalizeBagId(unittest.TestCase):
    def test_portal_style(self):
        self.assertEqual(normalize_bag_id("ABCD12 (Wash & Fold)"), "ABCD12")

    def test_uppercase(self):
        self.assertEqual(normalize_bag_id("abcd12"), "ABCD12")


class TestRackAndUser(unittest.TestCase):
    def test_clean_substring(self):
        self.assertTrue(rack_contains_clean("VeeWash Clean1"))

    def test_internal_user(self):
        self.assertTrue(user_is_internal("Washpro Staff"))
        self.assertTrue(user_is_internal("Jennifer (VeeWash)"))
        self.assertFalse(user_is_internal("Mahmoudou Nduwayo"))


class TestEvaluateBagCompletion(unittest.TestCase):
    def test_no_events(self):
        r = evaluate_bag_completion([])
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)
        self.assertEqual(r.completion_reason, REASON_NO_CLEAN_SCAN)

    def test_no_clean_scan(self):
        r = evaluate_bag_completion(
            [_ev("003-NY-WF", "Jane Customer", datetime(2026, 5, 16, 10, 0))]
        )
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)
        self.assertEqual(r.completion_reason, REASON_NO_CLEAN_SCAN)

    def test_clean_only_no_prior_workflow(self):
        r = evaluate_bag_completion(
            [_ev("Washpro Clean", "Washpro", datetime(2026, 5, 16, 10, 0))]
        )
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)
        self.assertEqual(r.completion_reason, REASON_CLEAN_WITHOUT_PRIOR_WORKFLOW)

    def test_workflow_then_clean_completed(self):
        r = evaluate_bag_completion(
            [
                _ev("003-NY-WF", "Mahmoudou Nduwayo", datetime(2026, 5, 16, 23, 4), 1, 1),
                _ev("FOLDING", "Sarah Kamran", datetime(2026, 5, 16, 23, 10), 2, 2),
                _ev(
                    "CLEAN",
                    "Veewash Training Account",
                    datetime(2026, 5, 17, 14, 57),
                    3,
                    3,
                ),
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)
        self.assertEqual(r.completion_reason, REASON_WORKFLOW_THEN_CLEAN)
        self.assertEqual(r.trigger_kind, TRIGGER_PRIOR_WORKFLOW_BEFORE_CLEAN)

    def test_live_bag_5lcz5rj60e(self):
        """5LCZ5RJ60E: WF → FOLDING → CLEAN (training on clean rack)."""
        events = [
            _ev("003-NY-WF", "Mahmoudou Nduwayo", datetime(2026, 5, 16, 23, 4), 10, 10),
            _ev("FOLDING", "Sarah Kamran", datetime(2026, 5, 16, 23, 10), 9, 9),
            _ev("CLEAN", "Veewash Training Account", datetime(2026, 5, 17, 14, 57), 1, 1),
        ]
        r = evaluate_bag_completion(events)
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)

    def test_live_bag_d6clwlcpda(self):
        events = [
            _ev("101-NY-WF", "Jake Strauss", datetime(2026, 5, 15, 22, 37), 1, 1),
            _ev("001-NY-WF", "Christopher Browne", datetime(2026, 5, 15, 23, 48), 2, 2),
            _ev("CLEAN", "Jennifer (VeeWash)", datetime(2026, 5, 16, 11, 26), 3, 3),
        ]
        r = evaluate_bag_completion(events)
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)

    def test_live_bag_30wi6kw06g(self):
        events = [
            _ev("103-NY-WF", "Natasha Peterson", datetime(2026, 5, 15, 22, 40), 1, 1),
            _ev("001-NY-WF", "Christopher Browne", datetime(2026, 5, 15, 23, 47), 2, 2),
            _ev("CLEAN", "Francis (Veewash)", datetime(2026, 5, 16, 13, 39), 3, 3),
        ]
        r = evaluate_bag_completion(events)
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)

    def test_csv_newest_first_row_order_ignored(self):
        """Newest-first CSV row order must not affect completion when timestamps are set."""
        events = [
            _ev("CLEAN", "Veewash Training Account", datetime(2026, 5, 17, 14, 57), 1, 3),
            _ev("FOLDING", "Sarah Kamran", datetime(2026, 5, 16, 23, 10), 2, 2),
            _ev("003-NY-WF", "Mahmoudou Nduwayo", datetime(2026, 5, 16, 23, 4), 3, 1),
        ]
        r = evaluate_bag_completion(events)
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)

    def test_scan_index_tiebreaker_only_when_timestamps_equal(self):
        """Same timestamp: lower scan_index is earlier in progressive order."""
        ts = datetime(2026, 5, 16, 12, 0)
        r = evaluate_bag_completion(
            [
                _ev("CLEAN", "Training Account", ts, 2, 2),
                _ev("003-NY-WF", "Customer", ts, 1, 1),
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)

    def test_scans_after_clean_ignored(self):
        """Post-CLEAN activity does not affect completion (no 'left clean' rule)."""
        r = evaluate_bag_completion(
            [
                _ev("003-NY-WF", "Customer", datetime(2026, 5, 16, 10, 0), 1, 1),
                _ev("CLEAN", "Training Account", datetime(2026, 5, 16, 11, 0), 2, 2),
                _ev("Out Rack", "Customer", datetime(2026, 5, 16, 12, 0), 3, 3),
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)

    def test_only_internal_work_before_clean_incomplete(self):
        r = evaluate_bag_completion(
            [
                _ev("003-NY-WF", "Washpro Staff", datetime(2026, 5, 16, 10, 0), 1, 1),
                _ev("CLEAN", "Veewash Training Account", datetime(2026, 5, 16, 11, 0), 2, 2),
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)
        self.assertEqual(r.completion_reason, REASON_CLEAN_WITHOUT_PRIOR_WORKFLOW)


if __name__ == "__main__":
    unittest.main()
