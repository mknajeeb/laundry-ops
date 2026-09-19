"""Unit tests for WF Folder Performance V1 canonical layer."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

from backend.management_wf_folder_attribution import apply_override_to_bag
from backend.management_wf_folder_performance import (
    COMPARE_7D,
    COMPARE_SAME_WEEKDAY_LAST_WEEK,
    COMPARE_TODAY,
    _assign_bag_into_folder_sessions,
    _build_folder_sessions_for_user,
    _employee_picker_label,
    _limit_last_n_sessions,
    _public_session_card,
    clip_folder_segments_to_epoch,
    compute_order_completion_timing,
    merge_day_payloads,
    resolve_comparison_window,
    resolve_folder_performance_window,
    weighted_aggregate_rates,
)
from backend.rinse_folding_folder_role_productivity import _hours


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
        assert rates["session_hours"] == 3.0
        assert rates["total_hours"] == 3.0
        assert rates["credited_weight_basis"] == "EVIDENCE_PRE"
        assert rates["aggregate_method"] == "weighted_totals"

    def test_zero_hours_yields_none(self):
        rates = weighted_aggregate_rates(
            total_orders=5, total_pre_lbs=100.0, total_session_hours=0
        )
        assert rates["bags_per_hour"] is None
        assert rates["lbs_per_hour"] is None
        assert rates["total_hours"] == 0.0


class TestSummaryKpiStripRegression:
    """Top KPI strip: Total Hours, Avg Bags/hr, Avg lb/hr from credited sessions."""

    @staticmethod
    def _emp(
        name,
        *,
        orders,
        lbs,
        hours,
        sessions=None,
        selected_date_et="2026-08-18",
    ):
        sess = sessions or [
            {
                "session_id": f"{name}-1",
                "selected_date_et": selected_date_et,
                "orders_completed": orders,
                "total_pre_lbs": lbs,
                "performance_hours": hours,
                "session_hours": hours,
            }
        ]
        return {
            "employee": name,
            "orders_completed": orders,
            "total_pre_lbs": lbs,
            "performance_hours": hours,
            "session_hours": hours,
            "session_count": len(sess),
            "sessions": sess,
        }

    def test_total_hours_sums_included_session_durations(self):
        day = {
            "employees": [
                self._emp("A", orders=10, lbs=200.0, hours=2.0),
                self._emp("B", orders=15, lbs=300.0, hours=3.5),
            ],
            "unmapped_orders": [],
        }
        summary = merge_day_payloads([day])["summary"]
        assert summary["total_hours"] == 5.5
        assert summary["session_hours"] == 5.5
        # Not earliest→latest wall clock (would be irrelevant here); Σ session hours.
        assert summary["total_hours"] == 2.0 + 3.5

    def test_avg_bags_hr_is_orders_over_total_hours(self):
        day = {
            "employees": [
                self._emp("A", orders=10, lbs=200.0, hours=2.0),
                self._emp("B", orders=20, lbs=400.0, hours=3.0),
            ],
            "unmapped_orders": [],
        }
        summary = merge_day_payloads([day])["summary"]
        assert summary["orders_completed"] == 30
        assert summary["total_hours"] == 5.0
        assert summary["bags_per_hour"] == 6.0  # 30 / 5

    def test_avg_lb_hr_is_pounds_over_total_hours(self):
        day = {
            "employees": [
                self._emp("A", orders=10, lbs=200.0, hours=2.0),
                self._emp("B", orders=20, lbs=400.0, hours=3.0),
            ],
            "unmapped_orders": [],
        }
        summary = merge_day_payloads([day])["summary"]
        assert summary["total_pre_lbs"] == 600.0
        assert summary["total_hours"] == 5.0
        assert summary["lbs_per_hour"] == 120.0  # 600 / 5

    def test_multiple_sessions_one_employee_summed_once(self):
        # Two Folder sessions for Maya: hours/orders must sum once into her card
        # and once into the strip — never double-count the employee.
        day = {
            "employees": [
                self._emp(
                    "Maya",
                    orders=18,
                    lbs=360.0,
                    hours=4.5,
                    sessions=[
                        {
                            "session_id": "M-AM",
                            "selected_date_et": "2026-08-18",
                            "orders_completed": 8,
                            "total_pre_lbs": 160.0,
                            "performance_hours": 2.0,
                            "session_hours": 2.0,
                        },
                        {
                            "session_id": "M-PM",
                            "selected_date_et": "2026-08-18",
                            "orders_completed": 10,
                            "total_pre_lbs": 200.0,
                            "performance_hours": 2.5,
                            "session_hours": 2.5,
                        },
                    ],
                )
            ],
            "unmapped_orders": [],
        }
        merged = merge_day_payloads([day])
        assert len(merged["employees"]) == 1
        emp = merged["employees"][0]
        assert emp["orders_completed"] == 18
        assert emp["session_hours"] == 4.5
        assert emp["performance_hours"] == 4.5
        summary = merged["summary"]
        assert summary["employee_count"] == 1
        assert summary["total_hours"] == 4.5
        assert summary["bags_per_hour"] == 4.0  # 18 / 4.5
        assert summary["lbs_per_hour"] == 80.0  # 360 / 4.5

    def test_open_session_denominator_runs_to_now(self):
        session_start = datetime(2026, 8, 19, 8, 31, 0)
        latest = datetime(2026, 8, 19, 12, 34, 0)
        now = datetime(2026, 8, 19, 14, 0, 0)
        sess = {
            "session_id": "WF-OPEN",
            "role_status": "open",
            "start_time": session_start.isoformat(),
            "end_time": now.isoformat(),
            "_start_dt": session_start,
            "_end_dt": now,
            "end_display": "Open",
            "selected_date_et": "2026-08-19",
        }
        orders = [
            {
                "bag_id": "B1",
                "completion_time": latest.isoformat(),
                "credited_weight_lbs": 40.0,
                "credited_weight_source": "EVIDENCE_PRE",
            },
            {
                "bag_id": "B2",
                "completion_time": latest.isoformat(),
                "credited_weight_lbs": 40.0,
                "credited_weight_source": "EVIDENCE_PRE",
            },
        ]
        card = _public_session_card(sess, orders)
        assert card["performance_basis"] == "open_session_now"
        assert card["performance_hours"] == 5.4833
        assert card["role_session_hours"] == 5.4833

        day = {
            "employees": [
                {
                    "employee": "OpenFolder",
                    "orders_completed": card["orders_completed"],
                    "total_pre_lbs": card["total_pre_lbs"],
                    "performance_hours": card["performance_hours"],
                    "session_hours": card["session_hours"],
                    "session_count": 1,
                    "sessions": [card],
                }
            ],
            "unmapped_orders": [],
        }
        summary = merge_day_payloads([day])["summary"]
        assert summary["total_hours"] == 5.4833
        assert summary["bags_per_hour"] == round(2 / 5.4833, 4)
        assert summary["lbs_per_hour"] == round(80.0 / 5.4833, 4)
        assert summary["total_hours"] == card["role_session_hours"]

    def test_unmapped_orders_excluded_from_productivity_numerator(self):
        # Mapped only in employee attribution → strip numerator matches mapped.
        day = {
            "employees": [self._emp("Mapped", orders=2, lbs=50.0, hours=2.0)],
            "unmapped_orders": [
                {"bag_id": "U1", "pre_lbs": 25.0},
                {"bag_id": "U2", "pre_lbs": 25.0},
                {"bag_id": "U3", "pre_lbs": 25.0},
            ],
        }
        summary = merge_day_payloads([day])["summary"]
        assert summary["orders_completed"] == 2
        assert summary["total_pre_lbs"] == 50.0
        assert summary["unmapped_count"] == 3
        assert summary["bags_per_hour"] == 1.0
        assert summary["lbs_per_hour"] == 25.0
        # Including unmapped would wrongly inflate rates.
        wrong = weighted_aggregate_rates(
            total_orders=5, total_pre_lbs=125.0, total_session_hours=2.0
        )
        assert wrong["bags_per_hour"] != summary["bags_per_hour"]
        assert wrong["lbs_per_hour"] != summary["lbs_per_hour"]

    def test_range_filters_recompute_hours_and_rates_consistently(self):
        day1 = {
            "employees": [
                self._emp(
                    "A",
                    orders=10,
                    lbs=200.0,
                    hours=2.0,
                    selected_date_et="2026-08-17",
                    sessions=[
                        {
                            "session_id": "A-17",
                            "selected_date_et": "2026-08-17",
                            "orders_completed": 10,
                            "total_pre_lbs": 200.0,
                            "performance_hours": 2.0,
                            "session_hours": 2.0,
                        }
                    ],
                )
            ],
            "unmapped_orders": [],
        }
        day2 = {
            "employees": [
                self._emp(
                    "A",
                    orders=20,
                    lbs=400.0,
                    hours=4.0,
                    selected_date_et="2026-08-18",
                    sessions=[
                        {
                            "session_id": "A-18",
                            "selected_date_et": "2026-08-18",
                            "orders_completed": 20,
                            "total_pre_lbs": 400.0,
                            "performance_hours": 4.0,
                            "session_hours": 4.0,
                        }
                    ],
                ),
                self._emp(
                    "B",
                    orders=6,
                    lbs=120.0,
                    hours=1.5,
                    selected_date_et="2026-08-18",
                    sessions=[
                        {
                            "session_id": "B-18",
                            "selected_date_et": "2026-08-18",
                            "orders_completed": 6,
                            "total_pre_lbs": 120.0,
                            "performance_hours": 1.5,
                            "session_hours": 1.5,
                        }
                    ],
                ),
            ],
            "unmapped_orders": [],
        }

        one_day = merge_day_payloads([day2])["summary"]
        assert one_day["total_hours"] == 5.5
        assert one_day["orders_completed"] == 26
        assert one_day["bags_per_hour"] == round(26 / 5.5, 4)
        assert one_day["lbs_per_hour"] == round(520.0 / 5.5, 4)

        two_day = merge_day_payloads([day1, day2])["summary"]
        assert two_day["employee_count"] == 2
        assert two_day["total_hours"] == 7.5  # 2 + 4 + 1.5
        assert two_day["orders_completed"] == 36
        assert two_day["total_pre_lbs"] == 720.0
        assert two_day["bags_per_hour"] == round(36 / 7.5, 4)
        assert two_day["lbs_per_hour"] == round(720.0 / 7.5, 4)

        # Last-N sessions keeps only newest N and recomputes all three KPIs.
        merged = merge_day_payloads([day1, day2])
        limited = _limit_last_n_sessions(merged, 2)
        lim = limited["summary"]
        assert lim["session_count"] == 2
        # Newest two by date/start: A-18 and B-18 (both 2026-08-18)
        assert lim["orders_completed"] == 26
        assert lim["total_hours"] == 5.5
        assert lim["bags_per_hour"] == round(26 / 5.5, 4)
        assert lim["lbs_per_hour"] == round(520.0 / 5.5, 4)
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
    def test_open_session_denominator_ends_at_now(self):
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
        assert perf["performance_basis"] == "open_session_now"
        assert perf["performance_end"] == now
        assert perf["role_session_hours"] == 5.4833
        assert perf["performance_hours"] == 5.4833

        card = _public_session_card(sess, orders)
        assert card["bags_per_hour"] == round(1 / 5.4833, 4)
        assert card["performance_through_label"] is None
        assert card["duration_label"] == "5h 29m"
        assert card["time_range_label"] == "8:31 AM – Open · 5h 29m"

    def test_open_session_zero_bags_still_has_folder_hours(self):
        session_start = datetime(2026, 8, 19, 8, 31, 0)
        now = datetime(2026, 8, 19, 14, 0, 0)
        sess = {
            "session_id": "WF-2",
            "role_status": "open",
            "_start_dt": session_start,
            "_end_dt": now,
        }
        card = _public_session_card(sess, [])
        assert card["performance_basis"] == "open_session_now"
        assert card["performance_hours"] == 5.4833
        assert card["bags_per_hour"] == 0.0
        assert card["lbs_per_hour"] == 0.0

    def test_open_idle_hour_after_last_completion_is_included(self):
        session_start = datetime(2026, 9, 19, 8, 0, 0)
        latest = datetime(2026, 9, 19, 12, 0, 0)
        now = datetime(2026, 9, 19, 13, 0, 0)
        sess = {
            "session_id": "WF-IDLE",
            "role_status": "open",
            "_start_dt": session_start,
            "_end_dt": now,
        }
        orders = [
            {
                "bag_id": "B1",
                "completion_time": latest.isoformat(),
                "credited_weight_lbs": 10.0,
                "credited_weight_source": "EVIDENCE_PRE",
            }
        ]
        perf = resolve_folder_performance_window(sess, orders)
        assert perf["latest_completion"] == latest
        assert perf["performance_end"] == now
        assert perf["performance_hours"] == 5.0

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


def _role_segment(seg_id, role, start, end, *, category="RINSE_WF"):
    return {
        "id": seg_id,
        "user_id": 7,
        "category_code": category,
        "role_code": role,
        "started_at": start,
        "ended_at": end,
    }


class TestFolderSessionBoundaryHours:
    def test_folder_operator_folder_counts_only_folder_intervals(self):
        day = date(2026, 8, 18)
        segs = [
            _role_segment(1, "FOLDER", datetime(2026, 8, 18, 8, 0), datetime(2026, 8, 18, 10, 0)),
            _role_segment(2, "OPERATOR", datetime(2026, 8, 18, 10, 0), datetime(2026, 8, 18, 12, 0)),
            _role_segment(3, "FOLDER", datetime(2026, 8, 18, 12, 0), datetime(2026, 8, 18, 14, 0)),
        ]
        sessions = _build_folder_sessions_for_user(
            segs,
            selected_date_et=day,
            sessions_by_id={},
            now_et=datetime(2026, 8, 18, 16, 0),
        )
        assert len(sessions) == 2
        assert {s["role_code"] for s in sessions} == {"FOLDER"}
        hours = sum(
            _hours((s["_end_dt"] - s["_start_dt"]).total_seconds()) for s in sessions
        )
        assert hours == 4.0

    def test_non_folder_roles_do_not_count(self):
        day = date(2026, 8, 18)
        segs = [
            _role_segment(1, "OPERATOR", datetime(2026, 8, 18, 8, 0), datetime(2026, 8, 18, 10, 0)),
            _role_segment(2, "SORT", datetime(2026, 8, 18, 10, 0), datetime(2026, 8, 18, 12, 0)),
            _role_segment(
                3,
                "FOLDER",
                datetime(2026, 8, 18, 12, 0),
                datetime(2026, 8, 18, 14, 0),
                category="RINSE_HD",
            ),
        ]
        sessions = _build_folder_sessions_for_user(
            segs,
            selected_date_et=day,
            sessions_by_id={},
            now_et=datetime(2026, 8, 18, 16, 0),
        )
        assert sessions == []

    def test_overlapping_folder_segments_do_not_double_count(self):
        day = date(2026, 8, 18)
        segs = [
            _role_segment(1, "FOLDER", datetime(2026, 8, 18, 8, 0), datetime(2026, 8, 18, 12, 0)),
            _role_segment(2, "FOLDER", datetime(2026, 8, 18, 10, 0), datetime(2026, 8, 18, 14, 0)),
        ]
        sessions = _build_folder_sessions_for_user(
            segs,
            selected_date_et=day,
            sessions_by_id={},
            now_et=datetime(2026, 8, 18, 16, 0),
        )
        assert len(sessions) == 2
        hours = sum(
            _hours((s["_end_dt"] - s["_start_dt"]).total_seconds()) for s in sessions
        )
        assert hours == 6.0
        assert sessions[0]["_end_dt"] == datetime(2026, 8, 18, 10, 0)

    def test_epoch_clip_is_the_performance_start(self):
        epoch = datetime(2026, 9, 17, 22, 43, 16)
        end = datetime(2026, 9, 18, 12, 0, 0)
        clipped = clip_folder_segments_to_epoch(
            {
                7: [
                    _role_segment(9, "FOLDER", datetime(2026, 9, 17, 8, 0), end),
                ]
            },
            epoch,
        )
        sessions = _build_folder_sessions_for_user(
            clipped[7],
            selected_date_et=date(2026, 9, 18),
            sessions_by_id={},
            now_et=datetime(2026, 9, 18, 14, 0),
        )
        assert len(sessions) == 1
        assert sessions[0]["_start_dt"] == epoch
        card = _public_session_card(sessions[0], [])
        assert card["performance_basis"] == "session_end"
        assert card["performance_hours"] == _hours((end - epoch).total_seconds())

    def test_open_folder_segment_ends_at_current_et(self):
        day = date(2026, 9, 19)
        start = datetime(2026, 9, 19, 7, 57)
        now = datetime(2026, 9, 19, 13, 20)
        with patch(
            "backend.rinse_folding_folder_role_productivity.eastern_today",
            return_value=day,
        ):
            sessions = _build_folder_sessions_for_user(
                [_role_segment(1, "FOLDER", start, None)],
                selected_date_et=day,
                sessions_by_id={},
                now_et=now,
            )
        assert len(sessions) == 1
        assert sessions[0]["role_status"] == "open"
        assert sessions[0]["_end_dt"] == now
        card = _public_session_card(sessions[0], [])
        assert card["performance_basis"] == "open_session_now"
        assert card["performance_hours"] == _hours((now - start).total_seconds())


class TestManualAttributionPrecedence:
    def test_existing_training_account_credit_is_not_replaced_without_override(self):
        bag = {
            "bag_id": "271V8S89G2",
            "credited_employee": "Veewash (Training Account)",
            "employee": "Veewash (Training Account)",
            "completed_by_employee": "Veewash (Training Account)",
        }
        out = apply_override_to_bag(bag, None)
        assert out["effective_employee"] == "Veewash (Training Account)"
        assert out["credited_employee"] == "Veewash (Training Account)"
        assert out["attribution_overridden"] is False

    def test_271_manual_override_beats_weight_entry_user(self):
        bag = {
            "bag_id": "271V8S89G2",
            "credited_employee": "Francis",
            "employee": "Francis",
            "completed_by_employee": "Francis",
        }
        override = {
            "effective_employee_name": "Veewash (Training Account)",
            "original_scanner_name": "Francis",
            "original_employee_name": "Francis",
            "effective_session_id": "WF-training",
        }
        out = apply_override_to_bag(bag, override)
        assert out["effective_employee"] == "Veewash (Training Account)"
        assert out["credited_employee"] == "Veewash (Training Account)"
        assert out["employee"] == "Veewash (Training Account)"
        assert out["completed_by_employee"] == "Veewash (Training Account)"
        assert out["attribution_overridden"] is True
        assert out["override_session_id"] == "WF-training"

        rewritten = dict(out)
        rewritten["credited_employee"] = "Francis"
        rewritten["employee"] = "Francis"
        rewritten["completed_by_employee"] = "Francis"
        again = apply_override_to_bag(rewritten, override)
        assert again["credited_employee"] == "Veewash (Training Account)"
        assert again["effective_employee"] == "Veewash (Training Account)"


class TestWeightedFolderHours:
    def test_summary_uses_summed_folder_hours_not_mean_of_rates(self):
        day = {
            "employees": [
                {
                    "employee": "A",
                    "orders_completed": 1,
                    "total_pre_lbs": 10.0,
                    "performance_hours": 1.0,
                    "session_hours": 1.0,
                    "session_count": 1,
                    "sessions": [],
                },
                {
                    "employee": "B",
                    "orders_completed": 1,
                    "total_pre_lbs": 10.0,
                    "performance_hours": 2.0,
                    "session_hours": 2.0,
                    "session_count": 1,
                    "sessions": [],
                },
            ],
            "unmapped_orders": [],
        }
        summary = merge_day_payloads([day])["summary"]
        assert summary["total_hours"] == 3.0
        assert summary["lbs_per_hour"] == round(20.0 / 3.0, 4)
        assert summary["bags_per_hour"] == round(2 / 3.0, 4)
        assert summary["lbs_per_hour"] != 7.5

    def test_zero_completion_folder_employee_reconciles_into_total_hours(self):
        day = {
            "employees": [
                {
                    "employee": "Producer",
                    "orders_completed": 6,
                    "total_pre_lbs": 154.8,
                    "performance_hours": 5.0,
                    "session_hours": 5.0,
                    "session_count": 1,
                    "sessions": [],
                },
                {
                    "employee": "Singh (VeeWash)",
                    "orders_completed": 0,
                    "total_pre_lbs": 0.0,
                    "performance_hours": 0.5,
                    "session_hours": 0.5,
                    "session_count": 1,
                    "sessions": [],
                },
            ],
            "unmapped_orders": [],
        }
        merged = merge_day_payloads([day])
        singh = next(e for e in merged["employees"] if e["employee"] == "Singh (VeeWash)")
        assert singh["orders_completed"] == 0
        assert singh["total_pre_lbs"] == 0.0
        assert singh["performance_hours"] == 0.5
        assert singh["lbs_per_hour"] == 0.0
        assert singh["bags_per_hour"] == 0.0
        row_hours = round(
            sum(float(e["performance_hours"]) for e in merged["employees"]),
            4,
        )
        assert merged["summary"]["total_hours"] == row_hours == 5.5
        assert merged["summary"]["employee_count"] == 2

