"""Unit tests for WF Folder Performance V1 canonical layer."""

from __future__ import annotations

from datetime import date, datetime

from backend.management_wf_folder_attribution import apply_override_to_bag
from backend.management_wf_folder_performance import (
    COMPARE_7D,
    COMPARE_SAME_WEEKDAY_LAST_WEEK,
    COMPARE_TODAY,
    compute_order_completion_timing,
    resolve_comparison_window,
    weighted_aggregate_rates,
)


DAY = date(2026, 8, 18)


class TestWeightedAggregateRates:
    def test_does_not_average_individual_rates(self):
        # Two sessions: 10 bags / 2h = 5/hr and 10 bags / 1h = 10/hr
        # Naive average of rates = 7.5; weighted = 20/3 ≈ 6.6667
        rates = weighted_aggregate_rates(
            total_orders=20,
            total_pre_lbs=400.0,
            total_session_hours=3.0,
        )
        assert rates["bags_per_hour"] == 6.6667
        assert rates["lbs_per_hour"] == 133.3333
        assert rates["credited_weight_basis"] == "EVIDENCE_PRE"
        assert rates["aggregate_method"] == "weighted_totals"

    def test_zero_hours_yields_none(self):
        rates = weighted_aggregate_rates(
            total_orders=5, total_pre_lbs=100.0, total_session_hours=0
        )
        assert rates["bags_per_hour"] is None
        assert rates["lbs_per_hour"] is None


class TestOrderCompletionTiming:
    def test_first_uses_session_start_subsequent_use_prior_completion(self):
        session_start = datetime(2026, 8, 18, 6, 5, 0)
        orders = [
            {
                "bag_id": "B1",
                "completion_time": "2026-08-18 06:20:00",
                "credited_weight_lbs": 20,
            },
            {
                "bag_id": "B2",
                "completion_time": "2026-08-18 06:35:00",
                "credited_weight_lbs": 22,
            },
            {
                "bag_id": "B3",
                "completion_time": "2026-08-18 07:05:00",
                "credited_weight_lbs": 18,
            },
        ]
        timed = compute_order_completion_timing(orders, session_start=session_start)
        assert timed[0]["timing_basis"] == "session_start"
        assert timed[0]["time_taken_seconds"] == 15 * 60
        assert timed[1]["timing_basis"] == "prior_completion"
        assert timed[1]["time_taken_seconds"] == 15 * 60
        assert timed[2]["timing_basis"] == "prior_completion"
        assert timed[2]["time_taken_seconds"] == 30 * 60
        # No end-of-session idle appended to final bag
        assert timed[2]["bag_id"] == "B3"

    def test_sorts_by_completion_time(self):
        session_start = datetime(2026, 8, 18, 7, 0, 0)
        orders = [
            {"bag_id": "B2", "completion_time": "2026-08-18 07:30:00"},
            {"bag_id": "B1", "completion_time": "2026-08-18 07:10:00"},
        ]
        timed = compute_order_completion_timing(orders, session_start=session_start)
        assert [t["bag_id"] for t in timed] == ["B1", "B2"]
        assert timed[0]["order_sequence"] == 1
        assert timed[1]["order_sequence"] == 2


class TestComparisonWindow:
    def test_today(self):
        w = resolve_comparison_window(anchor_date_et=DAY, compare=COMPARE_TODAY)
        assert w["dates"] == [DAY]
        assert w["mode"] == "dates"

    def test_same_weekday_last_week(self):
        w = resolve_comparison_window(
            anchor_date_et=DAY, compare=COMPARE_SAME_WEEKDAY_LAST_WEEK
        )
        assert w["dates"] == [date(2026, 8, 11)]

    def test_7d(self):
        w = resolve_comparison_window(anchor_date_et=DAY, compare=COMPARE_7D)
        assert len(w["dates"]) == 7
        assert w["date_start_et"] == date(2026, 8, 12)
        assert w["date_end_et"] == DAY


class TestAttributionOverrideApply:
    def test_override_stamps_effective_without_losing_original(self):
        bag = {
            "bag_id": "ABC123",
            "credited_employee": "Scanner A",
            "employee": "Scanner A",
            "credited_weight_lbs": 25.0,
        }
        out = apply_override_to_bag(
            bag,
            {
                "original_employee_name": "Scanner A",
                "original_scanner_name": "Scanner A",
                "effective_employee_name": "Jennifer",
                "effective_session_id": "WF-100",
                "effective_segment_id": 42,
            },
        )
        assert out["original_scanner"] == "Scanner A"
        assert out["effective_employee"] == "Jennifer"
        assert out["credited_employee"] == "Jennifer"
        assert out["reassignment_indicator"] is True
        assert out["override_session_id"] == "WF-100"

    def test_no_override_keeps_original(self):
        bag = {"bag_id": "X", "credited_employee": "Maya", "employee": "Maya"}
        out = apply_override_to_bag(bag, None)
        assert out["effective_employee"] == "Maya"
        assert out["reassignment_indicator"] is False


class TestUnmappedExclusionFromRates:
    def test_mapped_rates_ignore_unmapped_orders(self):
        # Simulate: 2 mapped orders / 2h session; 3 unmapped must not inflate.
        mapped = weighted_aggregate_rates(
            total_orders=2, total_pre_lbs=50.0, total_session_hours=2.0
        )
        with_unmapped_wrong = weighted_aggregate_rates(
            total_orders=5, total_pre_lbs=125.0, total_session_hours=2.0
        )
        assert mapped["bags_per_hour"] == 1.0
        assert mapped["lbs_per_hour"] == 25.0
        assert with_unmapped_wrong["bags_per_hour"] != mapped["bags_per_hour"]
