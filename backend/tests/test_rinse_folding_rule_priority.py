"""Exception rule priority, toggles, and record-level scoring overrides."""

from datetime import date, datetime

import pytest

from backend.rinse_bag_folding import (
    EXCEPTION_CLEAN_BEFORE_FOLDING,
    EXCEPTION_FOLDING_DURATION_TOO_LONG,
    EXCEPTION_FOLDING_DURATION_TOO_SHORT,
    EXCEPTION_MISSING_CLEAN,
    EXCEPTION_MULTIPLE_FOLDING_SCANS,
    STATUS_CALCULATED,
    STATUS_EXCEPTION,
    evaluate_folding_performance_for_bag,
)
from backend.rinse_folding_exception_rules import (
    MULTIPLE_FOLDING_BEHAVIOR_EXCEPTION,
    MULTIPLE_FOLDING_WARNING_EARLIEST,
    parse_exception_rules_payload,
)
from backend.rinse_folding_scoring import (
    SCORING_INCLUDED_OVERRIDE,
    SCORING_OVERRIDE_INCLUDE,
    scoring_fields_from_compute,
)


def _ev(rack, user, at, ev_id=1, scan_index=1):
    return {
        "id": ev_id,
        "rack": rack,
        "user_name": user,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


def _multi_fold_events(*, short=False):
    t0 = datetime(2026, 5, 16, 10, 0)
    t_mid = datetime(2026, 5, 16, 10, 5)
    t1 = datetime(2026, 5, 16, 10, 8) if short else datetime(2026, 5, 16, 10, 30)
    t2 = datetime(2026, 5, 16, 11, 0)
    return [
        _ev("FOLDING", "A", t0, 1, 1),
        _ev("VeeWash Folding", "B", t_mid, 2, 2),
        _ev("CLEAN", "X", t1, 3, 3),
        _ev("Rack Clean", "Y", t2, 4, 4),
    ]


class TestRulePriority:
    def test_missing_clean_wins_over_multiple_folding(self):
        rules = parse_exception_rules_payload(
            {
                "rule_missing_clean": True,
                "multiple_folding_scans_behavior": MULTIPLE_FOLDING_BEHAVIOR_EXCEPTION,
            }
        )
        r = evaluate_folding_performance_for_bag(
            [
                _ev("FOLDING", "A", datetime(2026, 5, 16, 10, 0), 1, 1),
                _ev("VeeWash Folding", "B", datetime(2026, 5, 16, 10, 5), 2, 2),
            ],
            registry_row={"date_clean": date(2026, 5, 16)},
            rules=rules,
        )
        assert r.status == STATUS_EXCEPTION
        assert r.exception_code == EXCEPTION_MISSING_CLEAN

    def test_too_short_wins_over_multiple_folding_warning(self):
        rules = parse_exception_rules_payload({})
        r = evaluate_folding_performance_for_bag(
            _multi_fold_events(short=True),
            registry_row={"date_clean": date(2026, 5, 16)},
            rules=rules,
        )
        assert r.status == STATUS_EXCEPTION
        assert r.exception_code == EXCEPTION_FOLDING_DURATION_TOO_SHORT
        assert EXCEPTION_MULTIPLE_FOLDING_SCANS in r.warning_codes
        assert r.duration_seconds == 8 * 60

    def test_too_long_wins_over_multiple_folding(self):
        rules = parse_exception_rules_payload(
            {"max_duration_minutes": 15, "rule_max_duration_enabled": True}
        )
        t0 = datetime(2026, 5, 16, 10, 0)
        t_mid = datetime(2026, 5, 16, 10, 5)
        t1 = datetime(2026, 5, 16, 11, 0)
        t2 = datetime(2026, 5, 16, 11, 30)
        r = evaluate_folding_performance_for_bag(
            [
                _ev("FOLDING", "A", t0, 1, 1),
                _ev("VeeWash Folding", "B", t_mid, 2, 2),
                _ev("CLEAN", "X", t1, 3, 3),
                _ev("Rack Clean", "Y", t2, 4, 4),
            ],
            registry_row={"date_clean": date(2026, 5, 16)},
            rules=rules,
        )
        assert r.exception_code == EXCEPTION_FOLDING_DURATION_TOO_LONG

    def test_multiple_folding_warning_in_scoring_when_no_blocker(self):
        rules = parse_exception_rules_payload(
            {"multiple_folding_scans_behavior": MULTIPLE_FOLDING_WARNING_EARLIEST}
        )
        r = evaluate_folding_performance_for_bag(
            _multi_fold_events(),
            registry_row={"date_clean": date(2026, 5, 16)},
            rules=rules,
        )
        assert r.status == STATUS_CALCULATED
        assert r.exception_code == EXCEPTION_MULTIPLE_FOLDING_SCANS
        scoring = scoring_fields_from_compute(
            status=r.status, exception_code=r.exception_code, existing=None
        )
        assert scoring["included_in_scoring"] == 1

    def test_min_duration_disabled_skips_too_short(self):
        rules = parse_exception_rules_payload(
            {
                "rule_min_duration_enabled": False,
                "min_duration_minutes": 10,
            }
        )
        t0 = datetime(2026, 5, 16, 10, 0)
        t1 = datetime(2026, 5, 16, 10, 5)
        r = evaluate_folding_performance_for_bag(
            [
                _ev("FOLDING", "A", t0, 1, 1),
                _ev("CLEAN", "X", t1, 2, 2),
            ],
            registry_row={"date_clean": date(2026, 5, 16)},
            rules=rules,
        )
        assert r.status == STATUS_CALCULATED
        assert r.exception_code is None

    def test_max_duration_disabled_skips_too_long(self):
        rules = parse_exception_rules_payload(
            {
                "rule_max_duration_enabled": False,
                "max_duration_minutes": 10,
            }
        )
        t0 = datetime(2026, 5, 16, 10, 0)
        t1 = datetime(2026, 5, 16, 12, 0)
        r = evaluate_folding_performance_for_bag(
            [
                _ev("FOLDING", "A", t0, 1, 1),
                _ev("CLEAN", "X", t1, 2, 2),
            ],
            registry_row={"date_clean": date(2026, 5, 16)},
            rules=rules,
        )
        assert r.status == STATUS_CALCULATED
        assert r.exception_code is None

    def test_clean_before_folding_wins_over_multiple_folding(self):
        rules = parse_exception_rules_payload({})
        r = evaluate_folding_performance_for_bag(
            [
                _ev("CLEAN", "Early", datetime(2026, 5, 16, 9, 55), 1, 1),
                _ev("FOLDING", "A", datetime(2026, 5, 16, 10, 0), 2, 2),
                _ev("VeeWash Folding", "B", datetime(2026, 5, 16, 10, 5), 3, 3),
                _ev("CLEAN", "X", datetime(2026, 5, 16, 10, 30), 4, 4),
            ],
            registry_row={"date_clean": date(2026, 5, 16)},
            rules=rules,
        )
        assert r.exception_code == EXCEPTION_CLEAN_BEFORE_FOLDING


class TestScoringOverride:
    def test_include_override_beats_exception_rule(self):
        scoring = scoring_fields_from_compute(
            status=STATUS_EXCEPTION,
            exception_code=EXCEPTION_FOLDING_DURATION_TOO_SHORT,
            existing={"scoring_override": SCORING_OVERRIDE_INCLUDE},
        )
        assert scoring["included_in_scoring"] == 1
        assert scoring["scoring_status"] == SCORING_INCLUDED_OVERRIDE

    def test_exclude_override_beats_calculated_rule(self):
        scoring = scoring_fields_from_compute(
            status=STATUS_CALCULATED,
            exception_code=None,
            existing={"scoring_override": "EXCLUDE"},
        )
        assert scoring["included_in_scoring"] == 0

    def test_override_survives_recompute_preserve(self):
        scoring = scoring_fields_from_compute(
            status=STATUS_EXCEPTION,
            exception_code=EXCEPTION_FOLDING_DURATION_TOO_SHORT,
            existing={
                "scoring_override": SCORING_OVERRIDE_INCLUDE,
                "scoring_status": SCORING_INCLUDED_OVERRIDE,
                "included_in_scoring": 1,
            },
            preserve_review=True,
        )
        assert scoring["included_in_scoring"] == 1
