"""Washpro / production bag patterns under Clean-rack completion."""

from __future__ import annotations

import unittest
from datetime import datetime

from backend.rinse_bag_completion import (
    COMPLETION_COMPLETED,
    COMPLETION_INCOMPLETE,
    REASON_CLEAN_RACK_SCANNED,
    REASON_NO_CLEAN_SCAN,
    evaluate_bag_completion,
)


def _ev(rack, user, at, scan_index=1, ev_id=1):
    return {
        "id": ev_id,
        "rack": rack,
        "user_name": user,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


class TestWashproCleanRackCompletion(unittest.TestCase):
    def test_washpro_clean_last_completes_on_clean_scan(self):
        """EDN6JV5H07 pattern: Washpro Clean is sufficient; no later scan required."""
        events = [
            _ev("(None)", "Hanif Ector", datetime(2026, 5, 18, 20, 12), 1, 1),
            _ev("015-NY-WF", "Washpro Driver", datetime(2026, 5, 19, 0, 5), 2, 2),
            _ev("(None)", "Noemi (Washpro Staff)", datetime(2026, 5, 19, 6, 26), 3, 3),
            _ev("(None)", "Coral (Washpro Staff)", datetime(2026, 5, 19, 8, 22), 4, 4),
            _ev("Washpro Clean", "Coral (Washpro Staff)", datetime(2026, 5, 19, 8, 23), 5, 5),
        ]
        r = evaluate_bag_completion(events)
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)
        self.assertEqual(r.completion_reason, REASON_CLEAN_RACK_SCANNED)
        self.assertEqual(r.first_clean_scan_event_id, 5)

    def test_first_clean_rack_wins_over_later_none_rack(self):
        events = [
            _ev("Washpro Clean", "Gloria (Washpro Staff)", datetime(2026, 5, 19, 6, 0), 1, 1),
            _ev("(None)", "Gloria (Washpro Staff)", datetime(2026, 5, 19, 6, 45), 2, 2),
        ]
        r = evaluate_bag_completion(events)
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)
        self.assertEqual(r.trigger_scan_event_id, 1)

    def test_pre_clean_only_incomplete(self):
        """B09GVBCNFQ pattern: no Clean rack scan yet."""
        events = [
            _ev("(None)", "Jarvis Roberts", datetime(2026, 5, 18, 21, 23), 1, 1),
            _ev("012-NY-WF", "Jarvis Roberts", datetime(2026, 5, 18, 21, 57), 2, 2),
        ]
        r = evaluate_bag_completion(events)
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)
        self.assertEqual(r.completion_reason, REASON_NO_CLEAN_SCAN)


if __name__ == "__main__":
    unittest.main()
