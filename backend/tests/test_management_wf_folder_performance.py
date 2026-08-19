"""Unit tests for WF Folder Performance V1 canonical layer."""

from __future__ import annotations

from datetime import date, datetime

from backend.management_wf_folder_attribution import apply_override_to_bag
from backend.management_wf_folder_performance import (
    COMPARE_7D,
    COMPARE_SAME_WEEKDAY_LAST_WEEK,
    COMPARE_TODAY,
    _assign_bag_into_folder_sessions,
    _employee_picker_label,
    _public_session_card,
    compute_order_completion_timing,
    resolve_comparison_window,
    resolve_folder_performance_window,
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


class TestMoveDestinationLabels:
    def test_picker_label_includes_display_when_different_from_rinse(self):
        assert (
            _employee_picker_label(
                "Mrs Chen (VeeWash)",
                {"display_name": "Guiying Lin", "rinse_user_name": "Mrs Chen (VeeWash)"},
            )
            == "Guiying Lin · Mrs Chen (VeeWash)"
        )

    def test_picker_label_plain_when_names_match(self):
        assert (
            _employee_picker_label(
                "Francis (Veewash)",
                {"display_name": "Francis (Veewash)"},
            )
            == "Francis (Veewash)"
        )


class TestOverrideOntoSignedInNonFolderSession:
    def test_manual_destination_session_accepts_override(self):
        sessions = [
            {
                "session_id": "WF-430",
                "session_code": "WF-01",
                "manual_destination_only": True,
                "role_code": "OPERATOR",
            }
        ]
        bag = {
            "bag_id": "XYZ",
            "override_session_id": "WF-430",
            "credited_employee": "Mrs Chen (VeeWash)",
            "completion_time": "2026-08-19 14:00:00",
        }
        out = _assign_bag_into_folder_sessions(bag, sessions)
        assert out["session_id"] == "WF-430"
        assert out.get("unmapped_reason") is None

    def test_auto_assign_ignores_manual_destination_only_sessions(self):
        sessions = [
            {
                "session_id": "WF-430",
                "session_code": "WF-01",
                "manual_destination_only": True,
                "_start_dt": datetime(2026, 8, 19, 13, 54, 0),
                "_end_dt": datetime(2026, 8, 19, 18, 0, 0),
                "start_time": "2026-08-19 13:54:00",
                "end_time": "2026-08-19 18:00:00",
            }
        ]
        bag = {
            "bag_id": "XYZ",
            "credited_employee": "Mrs Chen (VeeWash)",
            "completion_time": "2026-08-19 14:00:00",
            "credit_timestamp": "2026-08-19 14:00:00",
        }
        out = _assign_bag_into_folder_sessions(bag, sessions)
        assert out["session_id"] is None
        assert out["unmapped_reason"] == "OUTSIDE_FOLDER_SESSION"


class TestOpenSessionPerformanceEnd:
    def test_open_session_uses_last_completion_not_now(self):
        session_start = datetime(2026, 8, 19, 8, 31, 0)
        latest = datetime(2026, 8, 19, 12, 34, 0)
        now = datetime(2026, 8, 19, 14, 0, 0)
        sess = {
            "session_id": "WF-1",
            "role_status": "open",
            "start_time": session_start.isoformat(),
            "end_time": now.isoformat(),
            "_start_dt": session_start,
            "_end_dt": now,
            "end_display": "Open",
        }
        orders = [
            {
                "bag_id": "B1",
                "completion_time": latest.isoformat(),
                "credited_weight_lbs": 20.0,
                "credited_weight_source": "EVIDENCE_PRE",
            }
        ]
        perf = resolve_folder_performance_window(sess, orders)
        assert perf["performance_basis"] == "last_completion"
        assert perf["performance_end"] == latest
        assert perf["role_session_hours"] == 5.4833  # role window to now (display only)
        assert perf["performance_hours"] == 4.05  # to last completion

        card = _public_session_card(sess, orders)
        assert card["bags_per_hour"] == round(1 / 4.05, 4)
        assert card["performance_through_label"] == "Performance through last completion: 12:34 PM"
        assert card["duration_label"] == "4h 3m"
        assert "Open" in card["time_range_label"]

    def test_open_session_zero_bags_shows_dash_rates(self):
        session_start = datetime(2026, 8, 19, 8, 31, 0)
        now = datetime(2026, 8, 19, 14, 0, 0)
        sess = {
            "session_id": "WF-2",
            "role_status": "open",
            "_start_dt": session_start,
            "_end_dt": now,
        }
        card = _public_session_card(sess, [])
        assert card["bags_per_hour"] is None
        assert card["lbs_per_hour"] is None
        assert card["performance_hours"] is None

    def test_closed_session_uses_actual_session_end(self):
        session_start = datetime(2026, 8, 18, 8, 31, 0)
        session_end = datetime(2026, 8, 18, 16, 0, 0)
        latest = datetime(2026, 8, 18, 15, 30, 0)
        sess = {
            "session_id": "WF-3",
            "role_status": "closed",
            "_start_dt": session_start,
            "_end_dt": session_end,
        }
        orders = [
            {
                "bag_id": "B1",
                "completion_time": latest.isoformat(),
                "credited_weight_lbs": 30.0,
                "credited_weight_source": "EVIDENCE_PRE",
            }
        ]
        perf = resolve_folder_performance_window(sess, orders)
        assert perf["performance_basis"] == "session_end"
        assert perf["performance_end"] == session_end
        assert perf["performance_hours"] == 7.4833

        card = _public_session_card(sess, orders)
        assert card["performance_through_label"] is None
        assert "4:00 PM" in card["time_range_label"]
        assert card["duration_label"] == "7h 29m"
