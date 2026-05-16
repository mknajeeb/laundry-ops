"""Unit tests for Rinse bag OR completion rule."""

from __future__ import annotations

import unittest
from datetime import datetime

from backend.rinse_bag_completion import (
    COMPLETION_COMPLETED,
    COMPLETION_INCOMPLETE,
    REASON_NO_CLEAN_SCAN,
    REASON_POST_CLEAN_ONLY_INTERNAL_ON_CLEAN_RACK,
    REASON_POST_CLEAN_RACK_OR_USER,
    TRIGGER_RACK_NOT_CLEAN,
    TRIGGER_USER_NOT_INTERNAL,
    evaluate_bag_completion,
    normalize_bag_id,
    rack_contains_clean,
    user_is_internal,
)


def _ev(
    rack: str,
    user: str,
    at: datetime | None = None,
    scan_index: int = 1,
    ev_id: int = 1,
) -> dict:
    return {
        "id": ev_id,
        "rack": rack,
        "user_name": user,
        "scanned_at_parsed": at or datetime(2026, 5, 16, 10, 0, 0),
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
        self.assertFalse(user_is_internal("Customer Driver"))


class TestEvaluateBagCompletion(unittest.TestCase):
    def test_no_events(self):
        r = evaluate_bag_completion([])
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)
        self.assertEqual(r.completion_reason, REASON_NO_CLEAN_SCAN)

    def test_no_clean_scan(self):
        r = evaluate_bag_completion([_ev("Folding", "Jane", scan_index=1)])
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)
        self.assertEqual(r.completion_reason, REASON_NO_CLEAN_SCAN)

    def test_clean_only_no_later(self):
        r = evaluate_bag_completion([_ev("Washpro Clean", "Washpro", scan_index=1)])
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)
        self.assertEqual(r.completion_reason, REASON_POST_CLEAN_ONLY_INTERNAL_ON_CLEAN_RACK)

    def test_clean_then_out_rack(self):
        r = evaluate_bag_completion(
            [
                _ev("Washpro Clean", "Washpro", datetime(2026, 5, 16, 10, 0), 1, 1),
                _ev("Out Rack", "Washpro", datetime(2026, 5, 16, 10, 30), 2, 2),
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)
        self.assertEqual(r.completion_reason, REASON_POST_CLEAN_RACK_OR_USER)
        self.assertEqual(r.trigger_kind, TRIGGER_RACK_NOT_CLEAN)

    def test_clean_then_external_user_on_clean_rack(self):
        r = evaluate_bag_completion(
            [
                _ev("VeeWash Clean", "VeeWash", datetime(2026, 5, 16, 10, 0), 1, 1),
                _ev("VeeWash Clean", "Customer Driver", datetime(2026, 5, 16, 10, 15), 2, 2),
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)
        self.assertEqual(r.trigger_kind, TRIGGER_USER_NOT_INTERNAL)

    def test_clean_then_internal_on_clean_rack(self):
        r = evaluate_bag_completion(
            [
                _ev("VeeWash Clean", "VeeWash", datetime(2026, 5, 16, 10, 0), 1, 1),
                _ev("VeeWash Clean", "Washpro Staff", datetime(2026, 5, 16, 10, 15), 2, 2),
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)

    def test_clean_then_folding_internal(self):
        r = evaluate_bag_completion(
            [
                _ev("Washpro Clean", "Washpro", datetime(2026, 5, 16, 10, 0), 1, 1),
                _ev("Folding", "Washpro", datetime(2026, 5, 16, 10, 20), 2, 2),
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)
        self.assertEqual(r.trigger_kind, TRIGGER_RACK_NOT_CLEAN)

    def test_first_clean_anchors_later_only(self):
        r = evaluate_bag_completion(
            [
                _ev("Folding", "Jane", datetime(2026, 5, 16, 9, 0), 1, 1),
                _ev("Washpro Clean", "Washpro", datetime(2026, 5, 16, 10, 0), 2, 2),
                _ev("Out", "Jane", datetime(2026, 5, 16, 11, 0), 3, 3),
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)


if __name__ == "__main__":
    unittest.main()
