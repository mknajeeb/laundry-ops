"""Unit tests for Rinse bag post-CLEAN progressive-timeline completion."""

from __future__ import annotations

import unittest
from datetime import datetime

from backend.rinse_bag_completion import (
    COMPLETION_COMPLETED,
    COMPLETION_INCOMPLETE,
    REASON_CLEAN_WITHOUT_QUALIFYING_LATER,
    REASON_NO_CLEAN_SCAN,
    REASON_POST_CLEAN_RACK_AND_USER,
    TRIGGER_BOTH,
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
        self.assertFalse(rack_contains_clean("VeeWash Dirty"))

    def test_internal_user(self):
        self.assertTrue(user_is_internal("Washpro Staff"))
        self.assertTrue(user_is_internal("Jennifer (VeeWash)"))
        self.assertFalse(user_is_internal("Jake Strauss"))


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

    def test_clean_only_no_later_scan(self):
        r = evaluate_bag_completion(
            [_ev("Washpro Clean", "Washpro", datetime(2026, 5, 16, 10, 0))]
        )
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)
        self.assertEqual(r.completion_reason, REASON_CLEAN_WITHOUT_QUALIFYING_LATER)

    def test_clean_then_out_rack_customer_completed(self):
        trigger_at = datetime(2026, 5, 16, 12, 0)
        r = evaluate_bag_completion(
            [
                _ev("003-NY-WF", "Customer", datetime(2026, 5, 16, 10, 0), 1, 1),
                _ev("CLEAN", "Training Account", datetime(2026, 5, 16, 11, 0), 2, 2),
                _ev("Out Rack", "Jane Driver", trigger_at, 3, 3),
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)
        self.assertEqual(r.completion_reason, REASON_POST_CLEAN_RACK_AND_USER)
        self.assertEqual(r.trigger_kind, TRIGGER_BOTH)
        self.assertEqual(r.trigger_scan_at, trigger_at)
        self.assertEqual(r.trigger_scan_event_id, 3)

    def test_live_bag_d6clwlcpda_incomplete(self):
        """CLEAN then VeeWash Dirty by Jennifer (VeeWash) — internal user fails AND."""
        events = [
            _ev("workitems-added", "Jake Strauss", datetime(2026, 5, 14, 21, 53), 1, 1),
            _ev("101-NY-WF", "Jake Strauss", datetime(2026, 5, 14, 22, 37), 2, 2),
            _ev("001-NY-WF", "Christopher Browne", datetime(2026, 5, 14, 23, 48), 3, 3),
            _ev("CLEAN", "Jennifer (VeeWash)", datetime(2026, 5, 15, 11, 26), 4, 4),
            _ev("VeeWash Dirty", "Jennifer (VeeWash)", datetime(2026, 5, 15, 11, 27), 5, 5),
        ]
        r = evaluate_bag_completion(events)
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)
        self.assertEqual(r.completion_reason, REASON_CLEAN_WITHOUT_QUALIFYING_LATER)

    def test_clean_then_veewash_dirty_internal_incomplete(self):
        r = evaluate_bag_completion(
            [
                _ev("CLEAN", "Jennifer (VeeWash)", datetime(2026, 5, 15, 11, 26), 1, 1),
                _ev("VeeWash Dirty", "Jennifer (VeeWash)", datetime(2026, 5, 15, 11, 27), 2, 2),
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)

    def test_clean_then_folding_washpro_staff_incomplete(self):
        r = evaluate_bag_completion(
            [
                _ev("Washpro Clean", "Washpro", datetime(2026, 5, 16, 10, 0), 1, 1),
                _ev("Folding", "Washpro Staff", datetime(2026, 5, 16, 10, 20), 2, 2),
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)

    def test_clean_then_training_account_on_wf_rack_incomplete(self):
        r = evaluate_bag_completion(
            [
                _ev("CLEAN", "Staff", datetime(2026, 5, 16, 10, 0), 1, 1),
                _ev("001-NY-WF", "Training Account", datetime(2026, 5, 16, 10, 15), 2, 2),
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)

    def test_workflow_before_clean_only_incomplete(self):
        """Prior non-Clean scans do not complete the bag without a qualifying later scan."""
        r = evaluate_bag_completion(
            [
                _ev("003-NY-WF", "Mahmoudou Nduwayo", datetime(2026, 5, 16, 23, 4), 1, 1),
                _ev("FOLDING", "Sarah Kamran", datetime(2026, 5, 16, 23, 10), 2, 2),
                _ev("CLEAN", "Veewash Training Account", datetime(2026, 5, 17, 14, 57), 3, 3),
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)

    def test_csv_newest_first_row_order_ignored(self):
        trigger_at = datetime(2026, 5, 16, 12, 0)
        events = [
            _ev("Out Rack", "Customer Driver", trigger_at, 1, 5),
            _ev("CLEAN", "Training Account", datetime(2026, 5, 16, 11, 0), 2, 4),
            _ev("003-NY-WF", "Mahmoudou Nduwayo", datetime(2026, 5, 16, 10, 0), 3, 1),
        ]
        r = evaluate_bag_completion(events)
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)
        self.assertEqual(r.trigger_scan_at, trigger_at)

    def test_scan_index_tiebreaker_when_timestamps_equal(self):
        ts_clean = datetime(2026, 5, 16, 11, 0)
        ts_later = datetime(2026, 5, 16, 12, 0)
        r = evaluate_bag_completion(
            [
                _ev("CLEAN", "Training Account", ts_clean, 1, 2),
                _ev("Out Rack", "Customer", ts_later, 1, 3),
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)

    def test_first_qualifying_later_scan_wins(self):
        first_trigger = datetime(2026, 5, 16, 12, 0)
        r = evaluate_bag_completion(
            [
                _ev("CLEAN", "Staff", datetime(2026, 5, 16, 11, 0), 1, 1),
                _ev("Delivered", "Customer A", first_trigger, 2, 2),
                _ev("Pickup", "Customer B", datetime(2026, 5, 16, 13, 0), 3, 3),
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)
        self.assertEqual(r.trigger_scan_at, first_trigger)
        self.assertEqual(r.trigger_scan_event_id, 2)


if __name__ == "__main__":
    unittest.main()
