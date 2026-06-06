"""Performance /performance debug payload and reconciliation audit."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_shift_analysis import (
    LIFECYCLE_GROUP_FOLDED,
    LIFECYCLE_GROUP_SENT_TO_RINSE,
    _attach_wf_bucket_reconciliation,
    _empty_lifecycle_group_dict,
    _empty_hd_lifecycle_group_dict,
    _accumulate_lifecycle_group,
    _accumulate_hd_lifecycle_group,
    _sum_lifecycle_groups,
)
from backend.rinse_shift_analysis_debug import (
    _lifecycle_reconciliation,
    build_shift_analysis_debug_payload,
)


class TestWfLifecycleReconciliation(unittest.TestCase):
    def test_wf_buckets_balance_when_mutually_exclusive(self):
        g = _empty_lifecycle_group_dict()
        _accumulate_lifecycle_group(
            g,
            lifecycle_status="FOLDED_COMPLETED",
            lifecycle_group=LIFECYCLE_GROUP_FOLDED,
            is_completed=True,
            needs_review=False,
            has_exceptions=False,
        )
        _accumulate_lifecycle_group(
            g,
            lifecycle_status="SENT_TO_RINSE",
            lifecycle_group=LIFECYCLE_GROUP_SENT_TO_RINSE,
            is_completed=True,
            needs_review=False,
            has_exceptions=False,
        )
        attached = _attach_wf_bucket_reconciliation({"combined": g})["combined"]
        rec = _lifecycle_reconciliation(attached, service="wf")
        self.assertEqual(rec["total"], 2)
        self.assertEqual(rec["completed"], 2)
        self.assertEqual(rec["pending"], 0)
        self.assertTrue(rec["balances"])
        self.assertEqual(rec["unreconciled"], 0)

    def test_completed_equals_folded_plus_sent(self):
        g = _empty_lifecycle_group_dict()
        _accumulate_lifecycle_group(
            g,
            lifecycle_status="FOLDED_COMPLETED",
            lifecycle_group=LIFECYCLE_GROUP_FOLDED,
            is_completed=True,
            needs_review=False,
            has_exceptions=False,
        )
        rec = _lifecycle_reconciliation(g, service="wf")
        self.assertEqual(rec["completed"], rec["completed_from_folded_plus_sent"])


class TestHdLifecycleReconciliation(unittest.TestCase):
    def test_hd_at_vendor_counts_as_pending_not_double_bucket(self):
        """HD at_vendor increments both at_vendor and pending — document overlap."""
        g = _empty_hd_lifecycle_group_dict()
        _accumulate_hd_lifecycle_group(g, hd_status="at_vendor", needs_review=False, has_exceptions=False)
        rec = _lifecycle_reconciliation(g, service="hd")
        self.assertEqual(rec["total"], 1)
        self.assertFalse(rec["balances"])


class TestDebugPayloadShape(unittest.TestCase):
    def test_debug_payload_has_required_sections(self):
        cursor = MagicMock()
        with patch(
            "backend.rinse_shift_analysis_debug.build_shift_analysis_summary",
            return_value={
                "pending": {"incoming": {"summary": {}}, "wf_lifecycle": {"groups": {"combined": {}}}, "hd_lifecycle": {"groups": {"combined": {}}}, "rows": []},
                "overall_production": {"clocked_labor_hours": 0},
                "employees": [],
                "staff_performance": {"tasks": [], "records": []},
                "operational": {"records": []},
            },
        ), patch(
            "backend.rinse_shift_analysis_debug.aggregate_folding_leaderboard",
            return_value={"team": {}, "period_bag_summary": {}},
        ), patch(
            "backend.rinse_shift_analysis_debug.list_folding_performance_rows",
            return_value={"rows": []},
        ), patch(
            "backend.rinse_shift_analysis_debug._latest_scrape_block",
            return_value={"batch_id": 1},
        ), patch(
            "backend.rinse_shift_analysis_debug._registry_block",
            return_value={"total": 0},
        ), patch(
            "backend.rinse_shift_analysis_debug._staging_block",
            return_value={"active_total": 0},
        ), patch(
            "backend.rinse_shift_analysis_debug._clock_hours_diagnostic",
            return_value={"total_hours": 0, "reason_if_missing": "No clock records found"},
        ):
            payload = build_shift_analysis_debug_payload(
                cursor, 3, period_start=date(2026, 6, 4), period_end=date(2026, 6, 4)
            )
        for key in (
            "selected_date_scope",
            "latest_scrape",
            "registry",
            "staging",
            "presence",
            "lifecycle",
            "folding_scoring",
            "staff_performance",
            "clock_hours",
        ):
            self.assertIn(key, payload)
