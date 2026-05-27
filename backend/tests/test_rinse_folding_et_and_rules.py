"""ET date boundaries, folding rules, and approvals flag."""

from datetime import date, datetime

import pytest

from backend.rinse_bag_folding import (
    EXCEPTION_FOLDING_DURATION_TOO_SHORT,
    EXCEPTION_MULTIPLE_FOLDING_SCANS,
    STATUS_CALCULATED,
    STATUS_EXCEPTION,
    evaluate_folding_performance_for_bag,
)
from backend.rinse_folding_et import (
    naive_et_day_end_exclusive,
    naive_et_day_start,
    period_datetime_bounds_et,
    rinse_wall_calendar_date,
    sql_period_filter_sql_and_args,
)
from backend.rinse_folding_exception_rules import (
    MULTIPLE_FOLDING_BEHAVIOR_EXCEPTION,
    MULTIPLE_FOLDING_BEHAVIOR_WARNING_EARLIEST,
    normalize_rules_api_dict,
    parse_exception_rules_payload,
)
from backend.rinse_folding_scoring import scoring_fields_from_compute
from backend.rinse_folding_settings_flags import folding_approvals_enabled


def _ev(rack, user, at, ev_id=1, scan_index=1):
    return {
        "id": ev_id,
        "rack": rack,
        "user_name": user,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


class TestEasternDateBounds:
    def test_may_26_range_excludes_may_25_1130pm_et(self):
        start, end = period_datetime_bounds_et(date(2026, 5, 26), date(2026, 5, 26))
        may_25_late = datetime(2026, 5, 25, 23, 30, 0)
        assert may_25_late < start

    def test_may_26_range_includes_may_26_et_rows(self):
        start, end = period_datetime_bounds_et(date(2026, 5, 26), date(2026, 5, 26))
        may_26_mid = datetime(2026, 5, 26, 12, 0, 0)
        assert start <= may_26_mid <= end

    def test_folding_work_date_sql_uses_end_at_wall_range(self):
        sql, args = sql_period_filter_sql_and_args(
            "folding_work_date", date(2026, 5, 26), date(2026, 5, 26)
        )
        assert "folding_end_at" in sql
        assert args[0] == naive_et_day_start(date(2026, 5, 26))
        assert args[1] == naive_et_day_end_exclusive(date(2026, 5, 26))

    def test_utc_stored_naive_maps_to_et_calendar_date(self):
        # Rinse scan timestamps are naive ET wall time
        assert rinse_wall_calendar_date(datetime(2026, 5, 26, 4, 0, 0)) == date(2026, 5, 26)


class TestMultipleFoldingBehavior:
    def test_default_warning_uses_earliest_and_included_in_scoring(self):
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
        assert r.status == STATUS_CALCULATED, (r.status, r.exception_code)
        assert r.exception_code == EXCEPTION_MULTIPLE_FOLDING_SCANS
        scoring = scoring_fields_from_compute(
            status=r.status, exception_code=r.exception_code, existing=None
        )
        assert scoring["included_in_scoring"] == 1

    def test_exception_behavior_when_configured(self):
        rules = parse_exception_rules_payload(
            {"multiple_folding_scans_behavior": MULTIPLE_FOLDING_BEHAVIOR_EXCEPTION}
        )
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
            rules=rules,
        )
        assert r.status == STATUS_EXCEPTION
        assert r.exception_code == EXCEPTION_MULTIPLE_FOLDING_SCANS

    def test_too_short_duration_stays_exception(self):
        t0 = datetime(2026, 5, 16, 10, 0)
        t1 = datetime(2026, 5, 16, 10, 5)
        r = evaluate_folding_performance_for_bag(
            [
                _ev("FOLDING", "Folder", t0, 1, 1),
                _ev("CLEAN", "Staff", t1, 2, 2),
            ],
            registry_row={"date_clean": date(2026, 5, 16)},
        )
        assert r.status == STATUS_EXCEPTION
        assert r.exception_code == EXCEPTION_FOLDING_DURATION_TOO_SHORT

    def test_parse_default_behavior_is_warning(self):
        rules = parse_exception_rules_payload({})
        assert rules.multiple_folding_scans_behavior == MULTIPLE_FOLDING_BEHAVIOR_WARNING_EARLIEST

    def test_normalize_prefers_behavior_over_legacy_bool(self):
        out = normalize_rules_api_dict(
            {
                "rule_multiple_folding_scans": True,
                "multiple_folding_scans_behavior": MULTIPLE_FOLDING_BEHAVIOR_WARNING_EARLIEST,
            }
        )
        assert out["multiple_folding_scans_behavior"] == MULTIPLE_FOLDING_BEHAVIOR_WARNING_EARLIEST
        assert out["rule_multiple_folding_scans"] is False

    def test_normalize_legacy_bool_only_maps_to_exception(self):
        out = normalize_rules_api_dict({"rule_multiple_folding_scans": True})
        assert out["multiple_folding_scans_behavior"] == MULTIPLE_FOLDING_BEHAVIOR_EXCEPTION


class TestApprovalsFlag:
    def test_approvals_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("RINSE_FOLDING_APPROVALS_ENABLED", raising=False)
        assert folding_approvals_enabled() is False

    def test_approvals_enabled_when_env_true(self, monkeypatch):
        monkeypatch.setenv("RINSE_FOLDING_APPROVALS_ENABLED", "true")
        assert folding_approvals_enabled() is True
