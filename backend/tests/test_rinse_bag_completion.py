"""Unit tests for Rinse bag Clean-rack completion."""

from __future__ import annotations

import unittest
from datetime import datetime

from backend.rinse_bag_completion import (
    COMPLETION_COMPLETED,
    COMPLETION_INCOMPLETE,
    REASON_CLEAN_RACK_SCANNED,
    REASON_NO_CLEAN_SCAN,
    TRIGGER_CLEAN_RACK,
    classify_portal_upload_row,
    completion_result_references_persisted_events,
    evaluate_bag_completion,
    normalize_bag_id,
    order_events_for_completion,
    rack_contains_clean,
    user_is_internal,
    _event_id_num,
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
        self.assertTrue(rack_contains_clean("Washpro Clean"))
        self.assertTrue(rack_contains_clean("Clean"))
        self.assertFalse(rack_contains_clean("VeeWash Dirty"))

    def test_internal_user(self):
        self.assertTrue(user_is_internal("Washpro Staff"))
        self.assertFalse(user_is_internal("Jake Strauss"))


class TestEvaluateBagCompletion(unittest.TestCase):
    def test_no_events_incomplete(self):
        r = evaluate_bag_completion([])
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)
        self.assertEqual(r.completion_reason, REASON_NO_CLEAN_SCAN)

    def test_no_clean_scan(self):
        r = evaluate_bag_completion(
            [_ev("003-NY-WF", "Jane Customer", datetime(2026, 5, 16, 10, 0))]
        )
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)
        self.assertEqual(r.completion_reason, REASON_NO_CLEAN_SCAN)

    def test_first_clean_rack_completes_immediately(self):
        clean_at = datetime(2026, 5, 16, 11, 0)
        r = evaluate_bag_completion(
            [
                _ev("003-NY-WF", "Customer", datetime(2026, 5, 16, 10, 0), 1, 1),
                _ev("Washpro Clean", "Washpro Staff", clean_at, 2, 2),
                _ev("Out Rack", "Jane Driver", datetime(2026, 5, 16, 12, 0), 3, 3),
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)
        self.assertEqual(r.completion_reason, REASON_CLEAN_RACK_SCANNED)
        self.assertEqual(r.trigger_kind, TRIGGER_CLEAN_RACK)
        self.assertEqual(r.trigger_scan_at, clean_at)
        self.assertEqual(r.trigger_scan_event_id, 2)
        self.assertEqual(r.first_clean_scan_event_id, 2)

    def test_clean_only_completes(self):
        clean_at = datetime(2026, 5, 16, 10, 0)
        r = evaluate_bag_completion(
            [_ev("VeeWash Clean", "Veewash Training Account", clean_at, 1, 1)]
        )
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)
        self.assertEqual(r.completion_reason, REASON_CLEAN_RACK_SCANNED)

    def test_clean_last_row_completes(self):
        clean_at = datetime(2026, 5, 17, 16, 18)
        r = evaluate_bag_completion(
            [
                _ev("003-NY-WF", "Driver", datetime(2026, 5, 16, 14, 0), 1, 1),
                _ev("FOLDING", "Folder", datetime(2026, 5, 16, 14, 30), 2, 2),
                _ev("VeeWash Clean", "Veewash Training Account", clean_at, 3, 3),
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)
        self.assertEqual(r.trigger_scan_at, clean_at)

    def test_none_rack_after_clean_does_not_block_completion(self):
        """Completion is on first Clean scan; later (None) scans are irrelevant."""
        ts = datetime(2026, 5, 17, 16, 18)
        r = evaluate_bag_completion(
            [
                _ev("VeeWash Clean", "Train", ts, 1, 10),
                {"id": 11, "rack": "(None)", "user_name": None, "scanned_at_parsed": ts, "scan_index": 2},
            ]
        )
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)
        self.assertEqual(r.completion_reason, REASON_CLEAN_RACK_SCANNED)

    def test_csv_newest_first_row_order_ignored(self):
        clean_at = datetime(2026, 5, 16, 11, 0)
        events = [
            _ev("Out Rack", "Customer Driver", datetime(2026, 5, 16, 12, 0), 1, 5),
            _ev("CLEAN", "Training Account", clean_at, 2, 4),
            _ev("003-NY-WF", "Mahmoudou Nduwayo", datetime(2026, 5, 16, 10, 0), 3, 1),
        ]
        r = evaluate_bag_completion(events)
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)
        self.assertEqual(r.trigger_scan_at, clean_at)

    def test_timeline_sort_uses_id_after_scan_index(self):
        ts = datetime(2026, 5, 17, 16, 18)
        events = [
            _ev("003-NY-WF", "Jake Strauss", ts, 5, 20),
            _ev("VeeWash Clean", "Train", ts, 5, 10),
        ]
        ordered = order_events_for_completion(events)
        self.assertEqual(_event_id_num(ordered[0]), 10)
        r = evaluate_bag_completion(events)
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)
        self.assertEqual(r.first_clean_scan_event_id, 10)

    def test_persisted_events_guard_requires_clean_scan(self):
        ts = datetime(2026, 5, 17, 16, 18)
        from backend.rinse_bag_completion import CompletionResult

        bogus = CompletionResult(
            completion_status=COMPLETION_COMPLETED,
            completion_reason=REASON_CLEAN_RACK_SCANNED,
            first_clean_scan_at=ts,
            first_clean_scan_event_id=999,
            trigger_scan_at=ts,
            trigger_scan_event_id=999,
            trigger_kind=TRIGGER_CLEAN_RACK,
        )
        self.assertFalse(
            completion_result_references_persisted_events(
                bogus, [_ev("VeeWash Clean", "Train", ts, 1, 10)]
            )
        )


class TestClassifyPortalUploadRow(unittest.TestCase):
    def test_pre_upload_completed_rejected(self):
        st, reason = classify_portal_upload_row(
            ticket_id="BAG12345",
            was_completed_before_upload=True,
            has_active_staging=False,
            row_date_before_batch=False,
        )
        self.assertEqual(st, "REJECTED_DUPLICATE")
        self.assertEqual(reason, "ALREADY_COMPLETED")

    def test_not_pre_completed_accepted(self):
        st, reason = classify_portal_upload_row(
            ticket_id="BAG12345",
            was_completed_before_upload=False,
            has_active_staging=False,
            row_date_before_batch=False,
        )
        self.assertEqual(st, "ACCEPTED")
        self.assertEqual(reason, "OK")


if __name__ == "__main__":
    unittest.main()
