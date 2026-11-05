"""Labor Cost Analysis aggregation. Reporting only; payroll amounts are not rewritten."""

from datetime import date

from backend.labor_cost_analysis import (
    allocate_slices,
    biweekly_bounds,
    build_labor_cost_report,
    compare_summaries,
    comparison_windows,
    make_slice,
    resolve_preset,
)
from backend.payroll_hourly_cost import economics_from_time_records, hourly_cost_from_report_rows
from backend.labor_cost_analysis import slice_from_payroll_rows

VARUN_SETTINGS = {
    "employer_social_security_rate": 0.062,
    "employer_medicare_rate": 0.0145,
    "futa_rate": 0.006,
    "ny_suta_rate": 0.04025,
    "ny_reemployment_service_fund_rate": 0.0,
    "workers_comp_rate": 0.0,
    "labor_cost_target_per_hour": 19.0,
}


def _week(user_id, name, start, end, hours, gross, cost, *, category="w2", ot_hours=0, premium=0, ot_wages=0, straight_cost=None, estimated=False, base_wage=None):
    return make_slice(
        user_id=user_id,
        employee_name=name,
        worker_category=category,
        period_start=start,
        period_end=end,
        payable_hours=hours,
        ot_hours=ot_hours,
        gross_pay=gross,
        ot_premium=premium,
        ot_wages=ot_wages,
        total_employer_cost=cost,
        straight_time_employer_cost=cost if straight_cost is None else straight_cost,
        base_wage=base_wage,
        finalized=not estimated,
        estimated=estimated,
        burden_status="estimated" if estimated else "actual",
        burden_label="Estimated" if estimated else "Actual",
        cost_basis="estimated_time_records" if estimated else "processed_payroll",
    )


def test_weighted_average_is_not_the_mean_of_weekly_rates():
    slices = [
        _week(1, "A", "2026-10-05", "2026-10-11", 500, 9000, 9000),
        _week(1, "A", "2026-10-12", "2026-10-18", 700, 13300, 13300),
    ]
    report = build_labor_cost_report(
        slices,
        start=date(2026, 10, 5),
        end=date(2026, 10, 18),
        frequency="weekly",
        week_starts_on=0,
        target=19,
    )
    assert report["summary"]["employer_effective_rate"] == 18.58
    assert report["chart"]["buckets"][0]["employer_effective_rate"] == 18.00
    assert report["chart"]["buckets"][1]["employer_effective_rate"] == 19.00
    assert report["summary"]["employer_effective_rate"] != 18.50


def test_team_rate_is_not_the_average_of_employee_rates():
    slices = [
        _week(1, "A", "2026-10-05", "2026-10-11", 10, 200, 200, base_wage=20),
        _week(2, "B", "2026-10-05", "2026-10-11", 90, 900, 900, base_wage=10),
    ]
    report = build_labor_cost_report(
        slices,
        start=date(2026, 10, 5),
        end=date(2026, 10, 11),
        frequency="weekly",
        week_starts_on=0,
        target=19,
    )
    assert report["summary"]["employer_effective_rate"] == 11.00
    assert report["summary"]["employee_effective_rate"] == 11.00


def test_w2_burden_is_not_diluted_by_contractors():
    slices = [
        _week(1, "W2", "2026-10-05", "2026-10-11", 50, 1000, 1100),
        _week(2, "Contractor", "2026-10-05", "2026-10-11", 50, 1000, 1000, category="contractor_1099"),
    ]
    report = build_labor_cost_report(
        slices,
        start=date(2026, 10, 5),
        end=date(2026, 10, 11),
        week_starts_on=0,
        target=19,
    )
    assert report["summary"]["employer_effective_rate"] == 21.00
    assert report["summary"]["employer_burden_percent"] == 10.00
    contractor = report["by_classification"]["contractor_1099"]
    assert contractor["employee_effective_rate"] == contractor["employer_effective_rate"] == 20.00
    assert contractor["employee_rate_label"] == "Worker Gross Rate"
    assert contractor["employer_burden_percent"] is None
    assert contractor["employer_burden_label"] == "N/A"
    assert report["by_classification"]["w2"]["employer_burden_percent"] == 10.00


def test_ot_wages_are_not_the_premium_and_target_delta():
    row = _week(
        1,
        "A",
        "2026-10-05",
        "2026-10-11",
        50,
        935,
        1000,
        ot_hours=10,
        premium=85,
        ot_wages=255,
        straight_cost=910,
        base_wage=17,
    )
    report = build_labor_cost_report(
        [row],
        start=date(2026, 10, 5),
        end=date(2026, 10, 11),
        week_starts_on=0,
        target=19,
    )
    summary = report["summary"]
    assert summary["ot_premium"] == 85.00
    assert summary["ot_wages"] == 255.00
    assert summary["ot_wages"] != summary["ot_premium"]
    assert summary["employer_ot_premium"] == 90.00
    assert summary["target_status"] == "above"
    assert summary["target_delta_per_hour"] == 1.00
    assert summary["target_scope"] == "team"
    assert report["employees"][0]["target_scope"] == "employee"


def test_varun_slice_matches_stored_hourly_cost():
    components = {
        "futa": 0.0,
        "suta": 37.03,
        "er_ss": 57.03,
        "other": 0.0,
        "er_medicare": 13.34,
        "ny_reemploy": 0.0,
    }
    row = {
        "user_id": 26,
        "employee_name": "Varun",
        "worker_category": "w2",
        "pay_period_start": "2026-10-19",
        "pay_period_end": "2026-10-25",
        "gross_pay": 919.96,
        "total_payroll_cost": 1027.36,
        "ot_premium": 79.99,
        "ot_earnings": 239.96,
        "base_earnings": 839.97,
        "other_earnings": 0,
        "regular_hours": 40,
        "ot_hours": 9.41,
        "regular_rate": 17,
        "employer_taxes": 107.40,
        "employer_tax_components": components,
        "employer_cost_recorded": True,
        "batch_status": "paid",
        "details_finalized_at": "2026-10-26T12:00:00",
    }
    analysis = hourly_cost_from_report_rows([row], tax_settings=VARUN_SETTINGS, labor_cost_target=19)
    piece = slice_from_payroll_rows([row], tax_settings=VARUN_SETTINGS, labor_cost_target=19)
    report = build_labor_cost_report(
        [piece],
        start=date(2026, 10, 19),
        end=date(2026, 10, 25),
        week_starts_on=0,
        target=19,
    )
    summary = report["summary"]
    assert summary["employer_effective_rate"] == analysis["effective_cost_per_hour"] == 20.79
    assert summary["employer_rate_without_ot"] == analysis["base_cost_per_hour"] == 18.98
    assert summary["ot_premium"] == 79.99
    assert summary["ot_wages"] == 239.96
    assert summary["employer_ot_premium"] == round(
        analysis["total_employer_cost"] - analysis["straight_time_employer_cost"], 2
    )
    assert summary["employer_ot_premium"] != summary["ot_premium"]
    assert summary["employer_burden_percent"] == 11.67
    assert summary["data_label"] == "Actual"
    assert summary["target_status"] == "above"
    assert report["employees"][0]["base_wage"] == 17.00


def test_ot_percent_change_is_percentage_points_and_zero_baseline_is_na():
    rows = compare_summaries(
        {"ot_percent": 8.5, "payable_hours": 10, "labor_cost_target": 19},
        {"ot_percent": 6.0, "payable_hours": 0, "labor_cost_target": 19},
        current_days=7,
        previous_days=7,
        duration_mismatch=False,
    )
    ot = next(row for row in rows if row["key"] == "ot_percent")
    hours = next(row for row in rows if row["key"] == "payable_hours")
    assert ot["difference"] == 2.5
    assert ot["change_kind"] == "percentage_points"
    assert ot["percent_change"] is None
    assert hours["difference"] == 10.00
    assert hours["percent_change"] is None


def test_biweekly_anchor_is_stable():
    assert biweekly_bounds(date(2024, 1, 8), 0) == (date(2024, 1, 1), date(2024, 1, 14))
    assert biweekly_bounds(date(2024, 1, 15), 0) == (date(2024, 1, 15), date(2024, 1, 28))
    assert biweekly_bounds(date(2023, 12, 25), 0) == (date(2023, 12, 18), date(2023, 12, 31))
    slices = [
        _week(1, "A", "2024-01-01", "2024-01-07", 10, 200, 200),
        _week(1, "A", "2024-01-08", "2024-01-14", 30, 900, 900),
        _week(1, "A", "2024-01-15", "2024-01-21", 10, 100, 100),
    ]
    report = build_labor_cost_report(
        slices,
        start=date(2024, 1, 1),
        end=date(2024, 1, 21),
        frequency="biweekly",
        week_starts_on=0,
        target=19,
    )
    assert report["rules"]["biweekly_anchor"] == "2024-01-01"
    assert report["chart"]["buckets"][0]["employer_effective_rate"] == 27.50
    assert report["chart"]["buckets"][1]["employer_effective_rate"] == 10.00
    assert report["summary"]["employer_effective_rate"] == 24.00


def test_monthly_proration_uses_daily_hours_and_exclusion_when_missing():
    row = _week(1, "A", "2026-10-26", "2026-11-01", 56, 1120, 1120)
    daily = {}
    for day in range(26, 32):
        daily[(1, f"2026-10-{day:02d}")] = 8
    daily[(1, "2026-11-01")] = 8
    november = build_labor_cost_report(
        [row],
        start=date(2026, 11, 1),
        end=date(2026, 11, 30),
        frequency="monthly",
        week_starts_on=0,
        daily_hours=daily,
        daily_complete=True,
        target=19,
    )
    assert november["summary"]["payable_hours"] == 8.00
    assert november["summary"]["total_employer_cost"] == 160.00
    october = build_labor_cost_report(
        [row],
        start=date(2026, 10, 1),
        end=date(2026, 10, 31),
        frequency="monthly",
        week_starts_on=0,
        daily_hours=daily,
        daily_complete=True,
        target=19,
    )
    assert october["summary"]["payable_hours"] == 48.00
    assert october["summary"]["total_employer_cost"] == 960.00
    missing = build_labor_cost_report(
        [row],
        start=date(2026, 10, 1),
        end=date(2026, 11, 30),
        frequency="monthly",
        week_starts_on=0,
        daily_complete=False,
        target=19,
    )
    assert missing["summary"]["payable_hours"] == 0
    assert missing["coverage"]["excluded_partial_periods"]
    assert "calendar month" in missing["coverage"]["excluded_partial_periods"][0]["reason"]


def test_full_week_inside_one_month_does_not_need_daily_hours():
    row = _week(1, "A", "2026-10-19", "2026-10-25", 40, 800, 880)
    kept, coverage = allocate_slices(
        [row],
        range_start=date(2026, 10, 1),
        range_end=date(2026, 10, 31),
        frequency="monthly",
        daily_complete=False,
    )
    assert len(kept) == 1
    assert kept[0]["payable_hours"] == 40
    assert kept[0]["allocation"] == "full"
    assert coverage["excluded_partial_periods"] == []


def test_previous_equivalent_range_and_unequal_custom_comparison():
    windows = comparison_windows(
        "previous_equivalent",
        frequency="weekly",
        start=date(2026, 10, 19),
        end=date(2026, 10, 25),
        week_starts_on=0,
    )
    assert windows["previous"] == (date(2026, 10, 12), date(2026, 10, 18))
    assert windows["duration_mismatch"] is False
    slices = [
        _week(1, "A", "2026-10-12", "2026-10-18", 40, 760, 760),
        _week(1, "A", "2026-10-19", "2026-10-25", 50, 1000, 1000),
    ]
    report = build_labor_cost_report(
        slices,
        start=date(2026, 10, 12),
        end=date(2026, 10, 25),
        frequency="weekly",
        week_starts_on=0,
        compare="previous_period",
        target=19,
    )
    assert report["summary"]["payable_hours"] == 90
    hours = next(row for row in report["comparison"]["rows"] if row["key"] == "payable_hours")
    assert hours["current"] == 50
    assert hours["previous"] == 40
    custom = comparison_windows(
        "custom",
        frequency="weekly",
        start=date(2026, 10, 19),
        end=date(2026, 10, 25),
        week_starts_on=0,
        compare_start=date(2026, 10, 5),
        compare_end=date(2026, 10, 18),
    )
    assert custom["duration_mismatch"] is True
    mismatch_rows = compare_summaries(
        {"payable_hours": 70, "gross_pay": 1400, "labor_cost_target": 19},
        {"payable_hours": 70, "gross_pay": 700, "labor_cost_target": 19},
        current_days=7,
        previous_days=14,
        duration_mismatch=True,
    )
    hours = next(row for row in mismatch_rows if row["key"] == "payable_hours")
    assert hours["current_per_week"] == 70.00
    assert hours["previous_per_week"] == 35.00


def test_mixed_actual_and_estimated_label_and_hidden_names():
    slices = [
        _week(1, "A", "2026-10-05", "2026-10-11", 10, 200, 220),
        _week(1, "A", "2026-10-12", "2026-10-18", 10, 200, 230, estimated=True),
    ]
    report = build_labor_cost_report(
        slices,
        start=date(2026, 10, 5),
        end=date(2026, 10, 18),
        week_starts_on=0,
        status="all",
        target=19,
    )
    assert report["summary"]["data_label"] == "Mixed: Actual + Estimated"
    finalized = build_labor_cost_report(
        slices,
        start=date(2026, 10, 5),
        end=date(2026, 10, 18),
        week_starts_on=0,
        status="finalized",
        target=19,
    )
    assert finalized["summary"]["payable_hours"] == 10
    assert finalized["summary"]["data_label"] == "Actual"
    hidden = build_labor_cost_report(
        slices,
        start=date(2026, 10, 5),
        end=date(2026, 10, 18),
        week_starts_on=0,
        status="all",
        include_employee_detail=False,
        target=19,
    )
    assert hidden["employees"] == []
    assert hidden["directory"] == []
    assert hidden["summary"]["worker_count"] == 1


def test_open_estimate_uses_historical_burden_and_stored_ot_wages_from_hours():
    economics = economics_from_time_records(
        [{"approved_hours": 50, "hourly_rate": 17, "clock_in_at": "2026-10-26T08:00:00", "worker_category": "w2"}],
        ot_threshold=40,
        ot_multiplier=1.5,
    )
    assert economics["ot_premium"] == 85.00
    assert economics["ot_earnings"] == 255.00
    assert economics["gross_pay"] == 935.00


def _clocks(user_id, name, pairs):
    rows = []
    for index, (day, hours, category) in enumerate(pairs, start=1):
        rows.append(
            {
                "id": user_id * 100 + index,
                "user_id": user_id,
                "worker_name": name,
                "approved_hours": hours,
                "clock_in_at": f"{day} 08:00:00",
                "work_date": day,
                "hourly_rate": 17,
                "worker_category": category,
                "payroll_week_start": "2026-10-26",
            }
        )
    return rows


LILY_WEEK = [
    ("2026-10-26", 9.80, "w2"),
    ("2026-10-28", 9.23, "w2"),
    ("2026-10-29", 8.90, "temp"),
    ("2026-10-30", 9.68, "temp"),
    ("2026-10-31", 6.71, "temp"),
    ("2026-11-01", 6.68, "temp"),
]
AMNA_WEEK = [
    ("2026-10-26", 8.16, "w2"),
    ("2026-10-27", 7.74, "w2"),
    ("2026-10-28", 8.72, "temp"),
    ("2026-10-29", 5.97, "temp"),
    ("2026-10-30", 8.24, "temp"),
    ("2026-11-01", 7.29, "temp"),
]


def test_lily_and_amna_mixed_weeks_allocate_overtime_once():
    """W-2 and Temp share one 40-hour week. Burden stays on W-2 wages."""
    from backend.labor_cost_analysis import _employee_rows, estimate_open_week_slices

    history = [
        {
            "worker_category": "w2",
            "employer_cost_recorded": True,
            "batch_status": "paid",
            "pay_period_start": "2026-09-28",
            "pay_period_end": "2026-10-04",
            "gross_pay": 10000,
            "total_payroll_cost": 11227,
        }
    ]
    policy = {"enabled": True, "threshold_hours": 40, "multiplier": 1.5}
    week = dict(
        tax_settings={},
        target=19,
        week_start=date(2026, 10, 26),
        week_end=date(2026, 11, 1),
        policy=policy,
    )
    lily = _clocks(61, "Lily Chen", LILY_WEEK)
    amna = _clocks(38, "Amna Yousaf", AMNA_WEEK)
    for person in (lily, amna):
        w2 = [row for row in person if row["worker_category"] == "w2"]
        temp = [row for row in person if row["worker_category"] == "temp"]
        assert economics_from_time_records(w2)["ot_hours"] == 0
        assert economics_from_time_records(temp)["ot_hours"] == 0

    lily_slices = estimate_open_week_slices(lily, history, **week)
    amna_slices = estimate_open_week_slices(amna, history, **week)
    by_cat = lambda slices, cat: next(row for row in slices if row["worker_category"] == cat)

    lily_w2 = by_cat(lily_slices, "w2")
    lily_temp = by_cat(lily_slices, "temp")
    assert lily_w2["ot_hours"] == 0
    assert lily_temp["ot_hours"] > 10
    assert lily_temp["ot_premium"] == lily_w2["ot_premium"] + lily_temp["ot_premium"]
    assert lily_temp["total_employer_cost"] == lily_temp["gross_pay"]
    assert lily_w2["total_employer_cost"] > lily_w2["gross_pay"]
    assert lily_w2["burden_status"] == "estimated"
    assert lily_temp["burden_status"] == "not_applicable"
    assert lily_w2["estimated"] is True

    amna_w2 = by_cat(amna_slices, "w2")
    amna_temp = by_cat(amna_slices, "temp")
    assert amna_w2["payable_hours"] == 15.90
    assert amna_temp["payable_hours"] == 30.22
    assert amna_w2["ot_hours"] == 0
    assert amna_temp["ot_hours"] == 6.12
    assert amna_temp["ot_premium"] == 52.02
    assert amna_temp["gross_pay"] == 565.76
    assert amna_temp["total_employer_cost"] == 565.76
    assert amna_w2["gross_pay"] == 270.30
    assert amna_w2["total_employer_cost"] == round(270.30 * 1.1227, 2)

    employees = _employee_rows(
        lily_slices + amna_slices,
        frequency="weekly",
        week_starts_on=0,
        range_start=date(2026, 10, 26),
        range_end=date(2026, 11, 1),
        target=19,
    )
    by_name = {row["employee_name"]: row for row in employees}
    assert by_name["Amna Yousaf"]["ot_hours"] == 6.12
    assert by_name["Amna Yousaf"]["ot_premium"] == 52.02
    assert by_name["Amna Yousaf"]["payable_hours"] == 46.12
    assert by_name["Amna Yousaf"]["worker_category"] == "all"
    assert [item["ot_hours"] for item in by_name["Amna Yousaf"]["classifications"]] == [0, 6.12]
    assert by_name["Lily Chen"]["ot_hours"] == lily_temp["ot_hours"]
    assert by_name["Lily Chen"]["ot_hours"] > 0
    assert by_name["Lily Chen"]["classifications"][0]["worker_category"] == "w2"
    assert by_name["Lily Chen"]["classifications"][0]["ot_hours"] == 0
    assert by_name["Lily Chen"]["classifications"][1]["ot_hours"] == lily_temp["ot_hours"]


def test_stored_mixed_week_shows_one_overtime_total_and_estimated_burden():
    """Report rows keep the stored split. The employee week shows the combined overtime."""
    from backend.payroll_report_analytics import employee_summaries_by_category

    def row(user_id, name, category, regular, ot, premium, gross, taxes, cost, basis):
        return {
            "user_id": user_id,
            "employee_name": name,
            "worker_category": category,
            "pay_period_start": "2026-10-26",
            "pay_period_end": "2026-11-01",
            "regular_hours": regular,
            "ot_hours": ot,
            "ot_premium": premium,
            "gross_pay": gross,
            "employer_taxes": taxes,
            "total_payroll_cost": cost,
            "employer_cost_basis": basis,
            "employer_cost_recorded": False,
            "batch_status": "hours_reviewed",
        }

    rows = [
        row(61, "Lily Chen", "w2", 19.02, 0, 0, 323.34, 39.67, 363.01, "estimated"),
        row(61, "Lily Chen", "temp", 20.98, 10.99, 93.42, 636.91, 0, 636.91, "gross_only"),
        row(38, "Amna Yousaf", "w2", 15.90, 0, 0, 270.30, 0, 270.30, "estimated"),
        row(38, "Amna Yousaf", "temp", 24.10, 6.12, 52.02, 565.76, 0, 565.76, "gross_only"),
    ]
    summaries = employee_summaries_by_category(rows)
    lily_w2 = summaries["w2"][0] if summaries["w2"][0]["employee_name"] == "Lily Chen" else summaries["w2"][1]
    lily_temp = next(item for item in summaries["temp"] if item["employee_name"] == "Lily Chen")
    amna_temp = next(item for item in summaries["temp"] if item["employee_name"] == "Amna Yousaf")
    assert lily_w2["ot_hours"] == 0
    assert lily_temp["ot_hours"] == 10.99
    assert lily_temp["ot_premium"] == 93.42
    assert lily_w2["week"]["ot_hours"] == 10.99
    assert lily_w2["week"]["ot_premium"] == 93.42
    assert lily_w2["week"]["total_hours"] == 50.99
    assert lily_w2["week"]["total_payroll_cost"] == 999.92
    assert lily_w2["week"]["avg_cost_per_hour"] == 19.61
    assert lily_w2["week"]["cost_basis"] == "estimated"
    assert lily_w2["week"]["ot_hours"] == lily_temp["week"]["ot_hours"]
    assert [item["ot_hours"] for item in lily_w2["week"]["classifications"]] == [0, 10.99]
    assert amna_temp["ot_hours"] == 6.12
    assert amna_temp["ot_premium"] == 52.02
    assert amna_temp["week"]["total_hours"] == 46.12
    assert amna_temp["week"]["ot_hours"] == 6.12
    assert amna_temp["week"]["gross_pay"] == 836.06


def test_presets_follow_payroll_weeks_not_calendar_weeks_only():
    as_of = date(2026, 11, 1)
    current = resolve_preset("current_week", as_of=as_of, week_starts_on=0)
    assert current["start"] == date(2026, 10, 26)
    assert current["end"] == date(2026, 11, 1)
    last_four = resolve_preset("last_4_weeks", as_of=as_of, week_starts_on=0)
    assert last_four["start"] == date(2026, 10, 5)
    assert last_four["end"] == date(2026, 11, 1)
    assert resolve_preset("this_month", as_of=as_of, week_starts_on=0)["start"] == date(2026, 11, 1)
    assert resolve_preset("last_month", as_of=as_of, week_starts_on=0)["end"] == date(2026, 10, 31)
    last_three = resolve_preset("last_3_months", as_of=as_of, week_starts_on=0)
    assert last_three["start"] == date(2026, 9, 1)
    assert last_three["end"] == date(2026, 11, 30)
