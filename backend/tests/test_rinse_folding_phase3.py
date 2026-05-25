"""Phase 3: configurable exception rules and review scoring."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from backend.rinse_bag_folding import (
    EXCEPTION_FOLDING_DURATION_TOO_LONG,
    EXCEPTION_FOLDING_DURATION_TOO_SHORT,
    EXCEPTION_MISSING_CLEAN,
    EXCEPTION_MISSING_FOLDING,
    EXCEPTION_MULTIPLE_FOLDING_SCANS,
    STATUS_CALCULATED,
    STATUS_EXCEPTION,
    WARNING_MULTIPLE_CLEAN_SCANS,
    evaluate_folding_performance_for_bag,
)
from backend.rinse_folding_exception_rules import (
    FoldingExceptionRules,
    parse_exception_rules_payload,
)
from backend.rinse_folding_registry import _folding_performance_search_clauses
from backend.rinse_folding_scoring import (
    SCORING_APPROVED,
    row_included_in_scoring,
    scoring_fields_from_compute,
    sql_scoring_included_predicate,
)


def _folding_event(minutes_after_base: int, rack: str, user: str = "Alice") -> dict:
    base = datetime(2026, 5, 25, 10, 0, 0)
    ts = base + timedelta(minutes=minutes_after_base)
    return {
        "id": minutes_after_base,
        "rack": rack,
        "user_name": user,
        "scanned_at_parsed": ts,
        "scan_index": minutes_after_base,
    }


class TestConfigurableExceptionRules(unittest.TestCase):
    def test_min_duration_creates_exception(self):
        rules = parse_exception_rules_payload({"min_duration_minutes": 15})
        events = [_folding_event(0, "FOLDING"), _folding_event(10, "CLEAN")]
        r = evaluate_folding_performance_for_bag(events, rules=rules)
        self.assertEqual(r.status, STATUS_EXCEPTION)
        self.assertEqual(r.exception_code, EXCEPTION_FOLDING_DURATION_TOO_SHORT)

    def test_max_duration_creates_exception(self):
        rules = parse_exception_rules_payload(
            {"min_duration_minutes": 1, "max_duration_minutes": 30}
        )
        events = [_folding_event(0, "FOLDING"), _folding_event(45, "CLEAN")]
        r = evaluate_folding_performance_for_bag(events, rules=rules)
        self.assertEqual(r.status, STATUS_EXCEPTION)
        self.assertEqual(r.exception_code, EXCEPTION_FOLDING_DURATION_TOO_LONG)

    def test_multiple_folding_scan_toggle(self):
        rules_on = parse_exception_rules_payload({"rule_multiple_folding_scans": True})
        events = [
            _folding_event(0, "FOLDING"),
            _folding_event(5, "FOLDING"),
            _folding_event(20, "CLEAN"),
        ]
        r_on = evaluate_folding_performance_for_bag(events, rules=rules_on)
        self.assertEqual(r_on.exception_code, EXCEPTION_MULTIPLE_FOLDING_SCANS)

        rules_off = parse_exception_rules_payload({"rule_multiple_folding_scans": False})
        r_off = evaluate_folding_performance_for_bag(events, rules=rules_off)
        self.assertEqual(r_off.status, STATUS_CALCULATED)

    def test_missing_clean_toggle(self):
        rules_on = parse_exception_rules_payload({"rule_missing_clean": True})
        r_on = evaluate_folding_performance_for_bag([_folding_event(0, "FOLDING")], rules=rules_on)
        self.assertEqual(r_on.status, STATUS_EXCEPTION)
        self.assertEqual(r_on.exception_code, EXCEPTION_MISSING_CLEAN)

        rules_off = parse_exception_rules_payload({"rule_missing_clean": False})
        r_off = evaluate_folding_performance_for_bag([_folding_event(0, "FOLDING")], rules=rules_off)
        self.assertEqual(r_off.status, STATUS_CALCULATED)
        self.assertEqual(r_off.exception_code, EXCEPTION_MISSING_CLEAN)

    def test_missing_folding_toggle(self):
        rules_on = parse_exception_rules_payload({"rule_missing_folding": True})
        r_on = evaluate_folding_performance_for_bag([_folding_event(0, "CLEAN")], rules=rules_on)
        self.assertEqual(r_on.exception_code, EXCEPTION_MISSING_FOLDING)

        rules_off = parse_exception_rules_payload({"rule_missing_folding": False})
        r_off = evaluate_folding_performance_for_bag([_folding_event(0, "CLEAN")], rules=rules_off)
        self.assertEqual(r_off.status, STATUS_CALCULATED)

    def test_multiple_clean_warning_by_default(self):
        rules = parse_exception_rules_payload({"multiple_clean_scans_as_exception": False})
        events = [
            _folding_event(0, "FOLDING"),
            _folding_event(15, "CLEAN"),
            _folding_event(20, "CLEAN"),
        ]
        r = evaluate_folding_performance_for_bag(events, rules=rules)
        self.assertEqual(r.status, STATUS_CALCULATED)
        self.assertEqual(r.exception_code, WARNING_MULTIPLE_CLEAN_SCANS)

    def test_multiple_clean_as_exception_when_toggled(self):
        rules = parse_exception_rules_payload({"multiple_clean_scans_as_exception": True})
        events = [
            _folding_event(0, "FOLDING"),
            _folding_event(15, "CLEAN"),
            _folding_event(20, "CLEAN"),
        ]
        r = evaluate_folding_performance_for_bag(events, rules=rules)
        self.assertEqual(r.status, STATUS_EXCEPTION)
        self.assertEqual(r.exception_code, WARNING_MULTIPLE_CLEAN_SCANS)


class TestScoringInclusion(unittest.TestCase):
    def test_unapproved_exception_excluded(self):
        row = {
            "status": STATUS_EXCEPTION,
            "exception_code": EXCEPTION_MISSING_CLEAN,
            "scoring_status": "EXCEPTION",
            "included_in_scoring": 0,
            "excluded_from_performance": 0,
        }
        self.assertFalse(row_included_in_scoring(row))

    def test_approved_exception_included(self):
        row = {
            "status": STATUS_EXCEPTION,
            "exception_code": EXCEPTION_MISSING_CLEAN,
            "scoring_status": SCORING_APPROVED,
            "included_in_scoring": 1,
            "excluded_from_performance": 0,
        }
        self.assertTrue(row_included_in_scoring(row))

    def test_approval_preserves_exception_code(self):
        existing = {
            "status": STATUS_EXCEPTION,
            "exception_code": EXCEPTION_MISSING_CLEAN,
            "scoring_status": SCORING_APPROVED,
            "included_in_scoring": 1,
        }
        scoring = scoring_fields_from_compute(
            status=STATUS_EXCEPTION,
            exception_code=EXCEPTION_MISSING_CLEAN,
            existing=existing,
        )
        self.assertEqual(scoring["scoring_status"], SCORING_APPROVED)
        self.assertEqual(scoring["included_in_scoring"], 1)

    def test_leaderboard_sql_includes_approved(self):
        sql = sql_scoring_included_predicate("p")
        self.assertIn("APPROVED", sql)
        self.assertIn("included_in_scoring", sql)


class TestExceptionSearchFilters(unittest.TestCase):
    def test_reviewed_filter_in_sql(self):
        sql, args = _folding_performance_search_clauses(reviewed=True)
        self.assertIn("reviewed_at IS NOT NULL", sql)

    def test_user_filter_in_sql(self):
        sql, args = _folding_performance_search_clauses(user_name="Alice")
        self.assertIn("assigned_user_name", sql)
        self.assertEqual(args[-1], "Alice")


class TestReviewAudit(unittest.TestCase):
    def test_mark_reviewed_writes_override(self):
        from backend.rinse_folding_review import mark_exception_reviewed

        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "id": 9,
            "bag_id": "BAG1",
            "reviewed_at": None,
            "status": STATUS_EXCEPTION,
        }
        with patch(
            "backend.rinse_folding_review.get_folding_performance_row",
            return_value=cursor.fetchone.return_value,
        ):
            with patch("backend.rinse_folding_review.ensure_rinse_folding_tables"):
                out = mark_exception_reviewed(cursor, 3, "BAG1", actor_user_id=1, note="ok")
        self.assertIn("reviewed_at", out)
        self.assertTrue(cursor.execute.call_count >= 2)


if __name__ == "__main__":
    unittest.main()
