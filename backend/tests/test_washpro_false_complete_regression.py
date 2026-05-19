"""Regression: Washpro staff workflow must not false-complete via (None) rack OR-era logic."""

from __future__ import annotations

import unittest
from datetime import datetime

from backend.rinse_bag_completion import (
    COMPLETION_COMPLETED,
    COMPLETION_INCOMPLETE,
    evaluate_bag_completion,
    rack_contains_clean,
    user_is_internal,
)


def _ev(rack, user, at, scan_index=1, ev_id=1):
    return {
        "id": ev_id,
        "rack": rack,
        "user_name": user,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


class TestWashproFalseCompleteRegression(unittest.TestCase):
    def test_current_and_incomplete_washpro_clean_last_staff_workflow(self):
        """EDN6JV5H07 / 085QC2NMYP pattern: Clean rack last, only staff (None) scans before."""
        events = [
            _ev("(None)", "Hanif Ector", datetime(2026, 5, 18, 20, 12), 1, 1),
            _ev("015-NY-WF", "Washpro Driver", datetime(2026, 5, 19, 0, 5), 2, 2),
            _ev("(None)", "Noemi (Washpro Staff)", datetime(2026, 5, 19, 6, 26), 3, 3),
            _ev("(None)", "Coral (Washpro Staff)", datetime(2026, 5, 19, 8, 22), 4, 4),
            _ev("Washpro Clean", "Coral (Washpro Staff)", datetime(2026, 5, 19, 8, 23), 5, 5),
        ]
        r = evaluate_bag_completion(events)
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)

    def test_legacy_or_would_complete_on_none_rack_after_clean(self):
        """Documents why registry rows were wrongly COMPLETED before AND + meaningful-rack fix."""
        events = [
            _ev("Washpro Clean", "Gloria (Washpro Staff)", datetime(2026, 5, 19, 6, 0), 1, 1),
            _ev("(None)", "Gloria (Washpro Staff)", datetime(2026, 5, 19, 6, 45), 2, 2),
        ]
        later = events[1]
        rack = later.get("rack")
        user = later.get("user_name")
        legacy_or_trigger = (not rack_contains_clean(rack)) or (not user_is_internal(user))
        self.assertTrue(legacy_or_trigger)
        r = evaluate_bag_completion(events)
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)

    def test_pre_clean_only_incomplete(self):
        """B09GVBCNFQ pattern: no Clean rack scan yet."""
        events = [
            _ev("(None)", "Jarvis Roberts", datetime(2026, 5, 18, 21, 23), 1, 1),
            _ev("012-NY-WF", "Jarvis Roberts", datetime(2026, 5, 18, 21, 57), 2, 2),
        ]
        r = evaluate_bag_completion(events)
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)


if __name__ == "__main__":
    unittest.main()
