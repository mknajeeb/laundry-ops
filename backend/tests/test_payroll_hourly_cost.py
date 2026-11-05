"""Employer hourly-cost reporting. Does not change stored payroll amounts."""

from backend.payroll_hourly_cost import (
    aggregate_finalized_w2_periods,
    analyze_employee_hourly_cost,
    apply_historical_rates,
    economics_from_time_records,
    employer_burden_percent,
    employer_taxes_without_ot_premium,
    finalized_rows_for_period,
    hourly_cost_from_report_rows,
    payable_hours_from_net_seconds,
    price_time_records,
    weighted_burden_from_periods,
)
from backend.payroll_operations import parse_record_worker_category
from backend.payroll_report import build_report_row
from backend.payroll_report_analytics import employee_summaries_by_category

TAX_SETTINGS = {
    "employer_social_security_rate": 0.062,
    "employer_medicare_rate": 0.0145,
    "futa_rate": 0.006,
    "ny_suta_rate": 0.04,
    "ny_reemployment_service_fund_rate": 0.00075,
    "workers_comp_rate": 0.05,
    "labor_cost_target_per_hour": 19.0,
}


def _period(
    *,
    gross,
    total,
    start,
    end,
    recorded=True,
):
    return {
        "pay_period_start": start,
        "pay_period_end": end,
        "gross_pay": gross,
        "total_payroll_cost": total,
        "employer_cost_recorded": recorded,
    }


def test_varun_processed_burden_uses_stored_gross_and_total_cost():
    """Oct 19–25 illustration: $107.40 extra on $919.96 gross is 11.67%."""
    pct = employer_burden_percent(919.96, 1027.36)
    assert pct == 11.67
    assert round(1027.36 - 919.96, 2) == 107.40


def test_varun_oct_19_25_processed_snapshot():
    """Stored W-2 payroll for the week of Oct 19–25. Taxes are not recomputed."""
    components = {
        "futa": 0.0,
        "suta": 37.03,
        "er_ss": 57.03,
        "other": 0.0,
        "er_medicare": 13.34,
        "ny_reemploy": 0.0,
    }
    settings = {
        **TAX_SETTINGS,
        "ny_suta_rate": 0.04025,
        "ny_reemployment_service_fund_rate": 0.0,
        "workers_comp_rate": 0.0,
    }
    analysis = analyze_employee_hourly_cost(
        worker_category="w2",
        payable_hours=49.41,
        regular_hours=40,
        ot_hours=9.41,
        base_earnings=839.97,
        ot_premium=79.99,
        other_earnings=0,
        gross_pay=919.96,
        total_payroll_cost=1027.36,
        employer_taxes=107.40,
        employer_tax_components=components,
        employer_cost_recorded=True,
        regular_rates=[17],
        scenario="processed",
        tax_settings=settings,
        labor_cost_target=19,
    )
    assert analysis["burden_percent"] == 11.67
    assert analysis["burden_label"] == "Actual"
    assert analysis["base_wage"] == 17.00
    assert analysis["base_cost_per_hour"] == 18.98
    assert analysis["effective_cost_per_hour"] == 20.79
    assert analysis["ot_impact_per_hour"] == 1.81
    assert analysis["total_employer_cost"] == 1027.36
    assert analysis["finalized"] is True
    assert "MCTMT" not in " ".join(analysis["notes"])


def test_w2_zero_overtime_has_no_impact_and_reconciles():
    gross = 680.00
    taxes = 79.36
    total = round(gross + taxes, 2)
    analysis = analyze_employee_hourly_cost(
        worker_category="w2",
        payable_hours=40,
        regular_hours=40,
        ot_hours=0,
        base_earnings=gross,
        ot_premium=0,
        gross_pay=gross,
        total_payroll_cost=total,
        employer_taxes=taxes,
        employer_tax_components={"er_ss": 42.16, "er_medicare": 9.86, "futa": 4.08, "suta": 22.51, "ny_reemploy": 0.51, "other": 0.24},
        employer_cost_recorded=True,
        regular_rates=[17],
        scenario="processed",
        tax_settings=TAX_SETTINGS,
    )
    assert analysis["burden_status"] == "actual"
    assert analysis["burden_label"] == "Actual"
    assert analysis["ot_impact_per_hour"] == 0
    assert analysis["base_cost_per_hour"] == analysis["effective_cost_per_hour"]
    assert analysis["effective_cost_per_hour"] == round(total / 40, 2)
    assert analysis["total_employer_cost"] == total
    assert analysis["base_wage"] == 17


def test_w2_some_overtime_uses_stored_total_once():
    # 42 payable hours, 2 of them overtime, rate $17.
    hours = 42
    premium = round(2 * 8.5, 2)
    base = round(hours * 17, 2)
    gross = round(base + premium, 2)
    taxes = 80.00
    total = round(gross + taxes, 2)
    analysis = analyze_employee_hourly_cost(
        worker_category="w2",
        payable_hours=hours,
        regular_hours=40,
        ot_hours=2,
        base_earnings=base,
        ot_premium=premium,
        gross_pay=gross,
        total_payroll_cost=total,
        employer_taxes=taxes,
        employer_cost_recorded=True,
        regular_rates=[17],
        scenario="processed",
        tax_settings=TAX_SETTINGS,
    )
    assert analysis["gross_pay"] == gross
    assert abs(analysis["base_earnings"] + analysis["ot_premium"] + analysis["other_earnings"] - gross) < 0.02
    assert analysis["total_employer_cost"] == total
    assert analysis["effective_cost_per_hour"] == round(total / hours, 2)
    assert analysis["ot_impact_per_hour"] > 0
    assert analysis["burden_label"] == "Actual"
    # Workers' comp rate in settings must not be added on top of the stored total.
    assert analysis["total_employer_cost"] == total


def test_w2_substantial_overtime_estimated_matches_illustration():
    """Unprocessed Oct 26–Nov 1 illustration at a 11.67% historical burden."""
    economics = economics_from_time_records(
        [
            {
                "id": 1,
                "approved_hours": 51.53,
                "clock_in_at": "2026-10-26 08:00:00",
                "hourly_rate": 17,
                "worker_category": "w2",
            }
        ],
        ot_threshold=40,
        ot_multiplier=1.5,
    )
    hours = economics["payable_hours"]
    base = economics["base_earnings"]
    premium = economics["ot_premium"]
    gross = economics["gross_pay"]
    assert gross == 974.02
    analysis = analyze_employee_hourly_cost(
        worker_category="w2",
        payable_hours=hours,
        regular_hours=40,
        ot_hours=11.53,
        base_earnings=base,
        ot_premium=premium,
        gross_pay=gross,
        regular_rates=[17],
        scenario="estimated",
        burden_percent=11.67,
        burden_sources=[
            {
                "pay_period_start": "2026-10-19",
                "pay_period_end": "2026-10-25",
                "gross_pay": 919.96,
                "total_payroll_cost": 1027.36,
                "burden_percent": 11.67,
            }
        ],
        tax_settings=TAX_SETTINGS,
    )
    assert analysis["burden_label"] == "Estimated"
    assert analysis["burden_percent"] == 11.67
    assert analysis["base_wage"] == 17
    assert analysis["base_cost_per_hour"] == 18.98
    assert analysis["effective_cost_per_hour"] == 21.11
    assert analysis["ot_impact_per_hour"] == 2.13
    assert analysis["ot_impact_percent"] == 11.22
    assert analysis["target_status"] == "above"
    assert analysis["target_delta_per_hour"] == 2.11
    assert analysis["finalized"] is False
    assert analysis["burden_sources"][0]["pay_period_end"] == "2026-10-25"


def test_historical_rate_not_today_rate():
    records = [
        {
            "id": 1,
            "approved_hours": 40,
            "clock_in_at": "2026-09-01 08:00:00",
            "work_date": "2026-09-01",
            "hourly_rate": 20,
            "worker_category": "w2",
        }
    ]
    rated, changed = apply_historical_rates(records, {"2026-09-01": 17})
    assert changed is True
    economics = economics_from_time_records(rated, ot_threshold=40, ot_multiplier=1.5)
    assert economics["base_earnings"] == 680.00
    assert economics["gross_pay"] == 680.00
    assert economics["regular_rates"] == [17]


def test_multiple_rates_in_one_period_are_weighted():
    records = [
        {
            "id": 1,
            "approved_hours": 30,
            "clock_in_at": "2026-10-26 08:00:00",
            "work_date": "2026-10-26",
            "hourly_rate": 16,
            "worker_category": "w2",
        },
        {
            "id": 2,
            "approved_hours": 20,
            "clock_in_at": "2026-10-28 08:00:00",
            "work_date": "2026-10-28",
            "hourly_rate": 18,
            "worker_category": "w2",
        },
    ]
    economics = economics_from_time_records(records, ot_threshold=40, ot_multiplier=1.5)
    assert economics["payable_hours"] == 50
    assert economics["ot_hours"] == 10
    assert economics["base_earnings"] == 840.00
    assert economics["ot_premium"] == 90.00
    analysis = analyze_employee_hourly_cost(
        **economics,
        scenario="estimated",
        burden_percent=10,
        tax_settings=TAX_SETTINGS,
    )
    assert analysis["base_wage"] == 16.80
    assert analysis["base_wage_blended"] is True
    assert analysis["burden_label"] == "Estimated"


def test_contractor_does_not_receive_w2_burden():
    analysis = analyze_employee_hourly_cost(
        worker_category="contractor_1099",
        payable_hours=20,
        regular_hours=20,
        ot_hours=0,
        base_earnings=500,
        ot_premium=0,
        gross_pay=500,
        total_payroll_cost=500,
        employer_taxes=0,
        employer_cost_recorded=True,
        regular_rates=[25],
        scenario="contractor",
        burden_percent=11.67,
        tax_settings=TAX_SETTINGS,
    )
    assert analysis["burden_status"] == "not_applicable"
    assert analysis["burden_label"] == "N/A"
    assert analysis["effective_cost_per_hour"] == 25.00
    assert analysis["base_cost_per_hour"] == 25.00
    assert analysis["total_employer_cost"] == 500
    assert analysis["cost_basis"] == "contractor_cost"


def test_contractor_keeps_recorded_extra_cost():
    analysis = analyze_employee_hourly_cost(
        worker_category="contractor_1099",
        payable_hours=10,
        base_earnings=200,
        ot_premium=0,
        gross_pay=200,
        total_payroll_cost=230,
        employer_taxes=30,
        employer_cost_recorded=True,
        regular_rates=[20],
        scenario="contractor",
    )
    assert analysis["effective_cost_per_hour"] == 23.00
    assert analysis["employer_expenses"] == 30
    assert analysis["burden_label"] == "Actual"


def test_no_processed_history_leaves_burden_unavailable():
    weighted = weighted_burden_from_periods([])
    assert weighted["burden_percent"] is None
    analysis = analyze_employee_hourly_cost(
        worker_category="w2",
        payable_hours=40,
        base_earnings=680,
        ot_premium=0,
        gross_pay=680,
        regular_rates=[17],
        scenario="estimated",
        burden_percent=weighted["burden_percent"],
        burden_sources=weighted["sources"],
    )
    assert analysis["burden_status"] == "unavailable"
    assert analysis["effective_cost_per_hour"] is None
    assert analysis["base_cost_per_hour"] is None
    assert analysis["burden_percent"] is None


def test_fewer_than_four_periods_are_gross_weighted():
    periods = [
        _period(gross=100, total=110, start="2026-10-05", end="2026-10-11"),
        _period(gross=300, total=360, start="2026-09-28", end="2026-10-04"),
        _period(gross=200, total=220, start="2026-09-21", end="2026-09-27"),
    ]
    weighted = weighted_burden_from_periods(periods, limit=4)
    assert weighted["period_count"] == 3
    # (10 + 60 + 20) / 600 = 15%, not the simple average of 10, 20, and 10.
    assert weighted["burden_percent"] == 15.00
    assert weighted["burden_label"] == "Estimated"


def test_four_or_more_periods_use_only_the_newest_four():
    periods = [
        _period(gross=100, total=110, start="2026-10-19", end="2026-10-25"),
        _period(gross=100, total=110, start="2026-10-12", end="2026-10-18"),
        _period(gross=100, total=110, start="2026-10-05", end="2026-10-11"),
        _period(gross=100, total=110, start="2026-09-28", end="2026-10-04"),
        _period(gross=500, total=900, start="2026-09-21", end="2026-09-27"),
    ]
    weighted = weighted_burden_from_periods(periods, limit=4)
    assert weighted["period_count"] == 4
    assert weighted["burden_percent"] == 10.00
    assert all(src["pay_period_end"] != "2026-09-27" for src in weighted["sources"])


def test_unrecorded_history_is_not_used():
    periods = [
        _period(gross=400, total=400, start="2026-10-19", end="2026-10-25", recorded=False),
    ]
    weighted = weighted_burden_from_periods(periods)
    assert weighted["burden_percent"] is None


def test_capped_and_fixed_employer_taxes_do_not_scale_fully_with_overtime():
    gross = 1000.00
    premium = 200.00
    straight = 800.00
    components = {
        "er_medicare": 14.50,
        "er_ss": 62.00,
        "futa": 3.00,
        "other": 10.00,
    }
    taxes = round(sum(components.values()), 2)
    result = employer_taxes_without_ot_premium(
        gross_pay=gross,
        straight_time_gross=straight,
        employer_taxes=taxes,
        components=components,
        tax_settings=TAX_SETTINGS,
    )
    # Medicare and SS scale. FUTA already hit the wage base ($3 of $6). MCTMT stays $10.
    assert result["employer_taxes"] == 74.20
    assert result["component_notes"]["futa"] == "wage_base_cap"
    assert result["component_notes"]["other"] == "held_constant"
    proportional = round(taxes * straight / gross, 2)
    assert result["employer_taxes"] != proportional

    analysis = analyze_employee_hourly_cost(
        worker_category="w2",
        payable_hours=50,
        regular_hours=40,
        ot_hours=10,
        base_earnings=straight,
        ot_premium=premium,
        gross_pay=gross,
        total_payroll_cost=round(gross + taxes, 2),
        employer_taxes=taxes,
        employer_tax_components=components,
        employer_cost_recorded=True,
        regular_rates=[16],
        scenario="processed",
        tax_settings=TAX_SETTINGS,
    )
    assert analysis["method"] == "stored_components"
    assert analysis["total_employer_cost"] == round(gross + taxes, 2)
    assert analysis["effective_cost_per_hour"] == round((gross + taxes) / 50, 2)
    assert analysis["straight_time_employer_cost"] == round(straight + 74.20, 2)


def test_pending_payroll_is_not_treated_as_finalized_history():
    draft = {
        "worker_category": "w2",
        "pay_period_start": "2026-10-26",
        "pay_period_end": "2026-11-01",
        "gross_pay": 900,
        "total_payroll_cost": 1000,
        "employer_cost_recorded": True,
        "batch_status": "draft",
        "details_finalized_at": "",
    }
    paid = {
        **draft,
        "pay_period_start": "2026-10-19",
        "pay_period_end": "2026-10-25",
        "batch_status": "paid",
        "details_finalized_at": "2026-10-27T12:00:00",
    }
    assert finalized_rows_for_period([draft, paid], "2026-10-26", "2026-11-01") == []
    assert len(finalized_rows_for_period([draft, paid], "2026-10-19", "2026-10-25")) == 1
    history = aggregate_finalized_w2_periods([draft, paid], exclude_period=("2026-10-26", "2026-11-01"))
    assert len(history) == 1
    assert history[0]["pay_period_end"] == "2026-10-25"


def test_unpaid_breaks_are_excluded_from_payable_hours():
    clock_seconds = 8 * 3600
    break_seconds = 30 * 60
    net = clock_seconds - break_seconds
    assert payable_hours_from_net_seconds(net) == 7.5
    economics = economics_from_time_records(
        [
            {
                "id": 1,
                "approved_hours": payable_hours_from_net_seconds(net),
                "clock_in_at": "2026-10-26 08:00:00",
                "hourly_rate": 17,
                "worker_category": "w2",
                "break_seconds": break_seconds,
            }
        ]
    )
    assert economics["payable_hours"] == 7.5
    assert economics["gross_pay"] == round(7.5 * 17, 2)


def test_zero_payable_hours_do_not_divide():
    analysis = analyze_employee_hourly_cost(
        worker_category="w2",
        payable_hours=0,
        base_earnings=0,
        ot_premium=0,
        gross_pay=0,
        total_payroll_cost=0,
        employer_taxes=0,
        employer_cost_recorded=True,
        scenario="processed",
    )
    assert analysis["effective_cost_per_hour"] is None
    assert analysis["base_cost_per_hour"] is None
    assert analysis["ot_impact_per_hour"] is None
    assert analysis["burden_percent"] is None


def test_target_comparison_at_and_below_nineteen():
    below = analyze_employee_hourly_cost(
        worker_category="w2",
        payable_hours=40,
        base_earnings=640,
        ot_premium=0,
        gross_pay=640,
        total_payroll_cost=720,
        employer_taxes=80,
        employer_cost_recorded=True,
        regular_rates=[16],
        scenario="processed",
        labor_cost_target=19,
    )
    assert below["effective_cost_per_hour"] == 18.00
    assert below["target_status"] == "at_or_below"
    assert below["target_delta_per_hour"] == -1.00

    exact = analyze_employee_hourly_cost(
        worker_category="w2",
        payable_hours=40,
        base_earnings=680,
        ot_premium=0,
        gross_pay=680,
        total_payroll_cost=760,
        employer_taxes=80,
        employer_cost_recorded=True,
        regular_rates=[17],
        scenario="processed",
        labor_cost_target=19,
    )
    assert exact["effective_cost_per_hour"] == 19.00
    assert exact["target_status"] == "at_or_below"
    assert exact["target_delta_per_hour"] == 0


def test_dashboard_and_direct_analysis_match_without_rewriting_payroll():
    line = {
        "id": 9,
        "user_id": 42,
        "worker_name_snapshot": "Varun",
        "approved_hours": 40,
        "ot_hours": 9.41,
        "rate": 17,
        "ot_rate": 25.5,
        "gross_amount": 919.96,
        "total_amount": 919.96,
        "payment_status": "paid",
        "net_pay": 800,
        "payout_details": {
            "employer_taxes": {
                "er_ss": 57.04,
                "er_medicare": 13.34,
                "futa": 0,
                "suta": 33.12,
                "ny_reemploy": 0.69,
                "other": 3.21,
            },
            "settlement": {"amount_paid": 800, "amount_withheld": 119.96},
        },
    }
    batch = {
        "id": 3,
        "batch_name": "W2-2026-10-19",
        "worker_category": "w2",
        "pay_period_start": "2026-10-19",
        "pay_period_end": "2026-10-25",
        "status": "paid",
        "official_pay_date": "2026-10-30",
        "payout_details_finalized_at": "2026-10-30T15:00:00",
    }
    gross_before = line["gross_amount"]
    row = build_report_row(batch, line)
    assert row["gross_pay"] == 919.96
    assert row["total_payroll_cost"] == round(919.96 + row["employer_taxes"], 2)
    assert abs(row["total_payroll_cost"] - 1027.36) < 0.05
    stored_total = row["total_payroll_cost"]
    stored_gross = row["gross_pay"]

    from_dashboard = employee_summaries_by_category(
        [row], tax_settings=TAX_SETTINGS, labor_cost_target=19
    )["w2"][0]
    direct = hourly_cost_from_report_rows([row], tax_settings=TAX_SETTINGS, labor_cost_target=19)
    assert from_dashboard["gross_pay"] == stored_gross
    assert from_dashboard["total_payroll_cost"] == stored_total
    assert from_dashboard["hourly_cost"]["effective_cost_per_hour"] == direct["effective_cost_per_hour"]
    assert from_dashboard["hourly_cost"]["base_cost_per_hour"] == direct["base_cost_per_hour"]
    assert from_dashboard["hourly_cost"]["burden_percent"] == direct["burden_percent"]
    assert from_dashboard["hourly_cost"]["burden_label"] == "Actual"
    assert from_dashboard["hourly_cost"]["total_employer_cost"] == stored_total
    assert line["gross_amount"] == gross_before
    assert row["gross_pay"] == stored_gross
    assert row["total_payroll_cost"] == stored_total


def test_unfinalized_payroll_line_is_labeled_estimated_but_not_recomputed():
    line = {
        "id": 10,
        "user_id": 7,
        "worker_name_snapshot": "Ana",
        "approved_hours": 40,
        "ot_hours": 0,
        "rate": 18,
        "ot_rate": 27,
        "gross_amount": 720,
        "total_amount": 720,
        "payment_status": "pending",
        "net_pay": 720,
        "payout_details": {"employer_taxes": {"er_ss": 44.64, "er_medicare": 10.44}},
    }
    batch = {
        "id": 4,
        "worker_category": "w2",
        "pay_period_start": "2026-10-26",
        "pay_period_end": "2026-11-01",
        "status": "draft",
        "payout_details_finalized_at": None,
    }
    row = build_report_row(batch, line)
    total = row["total_payroll_cost"]
    analysis = hourly_cost_from_report_rows([row], tax_settings=TAX_SETTINGS)
    assert analysis["finalized"] is False
    assert analysis["burden_label"] == "Estimated"
    assert analysis["total_employer_cost"] == total
    assert analysis["cost_basis"] == "payroll_line_unfinalized"


def test_time_record_estimate_matches_dashboard_formula_for_same_inputs():
    economics = economics_from_time_records(
        [
            {
                "id": 1,
                "approved_hours": 51.53,
                "clock_in_at": "2026-10-26 08:00:00",
                "hourly_rate": 17,
                "worker_category": "w2",
            }
        ],
        ot_threshold=40,
        ot_multiplier=1.5,
    )
    from_time = analyze_employee_hourly_cost(
        **economics,
        scenario="estimated",
        burden_percent=11.67,
        tax_settings=TAX_SETTINGS,
    )
    again = analyze_employee_hourly_cost(
        worker_category="w2",
        payable_hours=economics["payable_hours"],
        regular_hours=economics["regular_hours"],
        ot_hours=economics["ot_hours"],
        base_earnings=economics["base_earnings"],
        ot_premium=economics["ot_premium"],
        other_earnings=0,
        gross_pay=economics["gross_pay"],
        regular_rates=economics["regular_rates"],
        scenario="estimated",
        burden_percent=11.67,
        tax_settings=TAX_SETTINGS,
    )
    assert from_time["effective_cost_per_hour"] == again["effective_cost_per_hour"]
    assert from_time["base_cost_per_hour"] == again["base_cost_per_hour"]
    assert from_time["ot_impact_per_hour"] == again["ot_impact_per_hour"]


def _amna_week(second_category):
    return [
        {
            "id": 1,
            "approved_hours": 30,
            "clock_in_at": "2026-11-02 08:00:00",
            "hourly_rate": 20,
            "worker_category": "temp",
        },
        {
            "id": 2,
            "approved_hours": 20,
            "clock_in_at": "2026-11-03 08:00:00",
            "hourly_rate": 20,
            "worker_category": second_category,
        },
    ]


_SHARED_OT = {
    "w2": {"enabled": True, "threshold_hours": 40, "multiplier": 1.5, "employer_burden_percent": 10},
    "temp": {"enabled": True, "threshold_hours": 40, "multiplier": 1.5, "employer_burden_percent": None},
    "contractor_1099": {"enabled": True, "threshold_hours": 40, "multiplier": 1.5, "employer_burden_percent": None},
}


def test_single_category_price_matches_existing_w2_estimate():
    records = [
        {
            "id": 1,
            "approved_hours": 51.53,
            "clock_in_at": "2026-10-26 08:00:00",
            "hourly_rate": 17,
            "worker_category": "w2",
        }
    ]
    economics = economics_from_time_records(records, ot_threshold=40, ot_multiplier=1.5)
    expected = analyze_employee_hourly_cost(
        **economics,
        scenario="estimated",
        burden_percent=11.67,
        tax_settings=TAX_SETTINGS,
        labor_cost_target=19,
    )
    priced = price_time_records(
        records,
        historical_w2_percent=11.67,
        tax_settings=TAX_SETTINGS,
        labor_cost_target=19,
    )
    assert priced["ot_hours"] == expected["ot_hours"]
    assert priced["gross_pay"] == expected["gross_pay"]
    assert priced["total_employer_cost"] == expected["total_employer_cost"]
    assert priced["base_cost_per_hour"] == expected["base_cost_per_hour"]
    assert priced["effective_cost_per_hour"] == expected["effective_cost_per_hour"]
    assert priced["ot_impact_per_hour"] == expected["ot_impact_per_hour"]
    assert sum(row["total_employer_cost"] for row in priced["record_costs"]) == priced["total_employer_cost"]


def test_category_change_changes_burden_and_keeps_overtime():
    as_temp = price_time_records(_amna_week("temp"), category_policies=_SHARED_OT, labor_cost_target=19)
    as_w2 = price_time_records(_amna_week("w2"), category_policies=_SHARED_OT, labor_cost_target=19)
    back = price_time_records(_amna_week("temp"), category_policies=_SHARED_OT, labor_cost_target=19)

    assert as_temp["ot_hours"] == 10
    assert as_w2["ot_hours"] == 10
    assert back["ot_hours"] == as_temp["ot_hours"]
    assert as_temp["total_employer_cost"] == 1100
    assert as_w2["total_employer_cost"] == 1150
    assert back["total_employer_cost"] == as_temp["total_employer_cost"]
    assert as_w2["burden_percent"] == 4.55
    assert as_w2["effective_cost_per_hour"] == 23.00
    assert as_w2["base_cost_per_hour"] == 20.80
    assert as_w2["ot_impact_per_hour"] == 2.20
    assert as_w2["target_delta_per_hour"] == 4.00
    assert as_w2["labor_cost_target"] == 19
    by_id = {row["id"]: row for row in as_w2["record_costs"]}
    assert by_id[1]["worker_category"] == "temp"
    assert by_id[1]["total_employer_cost"] == 600
    assert by_id[1]["ot_hours"] == 0
    assert by_id[2]["total_employer_cost"] == 550
    assert by_id[2]["ot_hours"] == 10
    assert sum(row["total_employer_cost"] for row in as_w2["record_costs"]) == as_w2["total_employer_cost"]


def test_temp_and_1099_do_not_inherit_w2_burden_unless_configured():
    mixed = price_time_records(
        _amna_week("contractor_1099"),
        category_policies=_SHARED_OT,
        historical_w2_percent=11.67,
        labor_cost_target=19,
    )
    assert mixed["ot_hours"] == 10
    assert mixed["total_employer_cost"] == 1100
    assert mixed["burden_status"] == "not_applicable"
    configured = dict(_SHARED_OT)
    configured["temp"] = {**_SHARED_OT["temp"], "employer_burden_percent": 5}
    priced = price_time_records(_amna_week("w2"), category_policies=configured, historical_w2_percent=11.67)
    by_id = {row["id"]: row for row in priced["record_costs"]}
    assert by_id[1]["total_employer_cost"] == 630
    assert by_id[2]["total_employer_cost"] == 550
    assert priced["total_employer_cost"] == 1180


def test_disabling_overtime_on_one_classification_does_not_reset_the_week():
    policies = {
        "w2": {"enabled": True, "threshold_hours": 40, "multiplier": 1.5, "employer_burden_percent": None},
        "temp": {"enabled": False, "threshold_hours": 40, "multiplier": 1.5, "employer_burden_percent": None},
    }
    records = [
        {"id": 1, "approved_hours": 45, "clock_in_at": "2026-11-02 08:00:00", "hourly_rate": 20, "worker_category": "w2"},
        {"id": 2, "approved_hours": 5, "clock_in_at": "2026-11-03 08:00:00", "hourly_rate": 20, "worker_category": "temp"},
    ]
    priced = price_time_records(records, category_policies=policies)
    assert priced["ot_hours"] == 5
    by_id = {row["id"]: row for row in priced["record_costs"]}
    assert by_id[1]["ot_hours"] == 5
    assert by_id[2]["ot_hours"] == 0


def test_record_worker_category_parser_rejects_unknown_values():
    assert parse_record_worker_category(None) is None
    assert parse_record_worker_category("") == ""
    assert parse_record_worker_category("w2") == "w2"
    try:
        parse_record_worker_category("salary")
    except ValueError as exc:
        assert "worker_category" in str(exc)
    else:
        raise AssertionError("unknown classification was accepted")


def _payout_row(
    *,
    user_id,
    category,
    gross,
    taxes,
    recorded,
    status,
    finalized_at=None,
    start="2026-10-26",
    end="2026-11-01",
):
    return {
        "user_id": user_id,
        "worker_category": category,
        "gross_pay": gross,
        "employer_taxes": taxes,
        "total_payroll_cost": round(gross + taxes, 2),
        "employer_cost_recorded": recorded,
        "batch_status": status,
        "details_finalized_at": finalized_at,
        "pay_period_start": start,
        "pay_period_end": end,
        "regular_hours": 40,
        "ot_hours": 0,
    }


def test_open_period_estimate_keeps_finalized_and_recorded_zero():
    from backend.payroll_hourly_cost import apply_open_period_burden_estimates

    finalized = _payout_row(
        user_id=61,
        category="w2",
        gross=303.45,
        taxes=37.25,
        recorded=True,
        status="paid",
        finalized_at="2026-10-28 12:00:00",
        start="2026-10-19",
        end="2026-10-25",
    )
    recorded_zero = _payout_row(
        user_id=61,
        category="w2",
        gross=400,
        taxes=0,
        recorded=True,
        status="paid",
        finalized_at="2026-09-16 12:00:00",
        start="2026-09-14",
        end="2026-09-20",
    )
    open_w2 = _payout_row(
        user_id=61,
        category="w2",
        gross=3625,
        taxes=0,
        recorded=False,
        status="approved_for_payment",
    )
    open_temp = _payout_row(
        user_id=61,
        category="temp",
        gross=636.91,
        taxes=0,
        recorded=False,
        status="hours_reviewed",
    )
    rows = apply_open_period_burden_estimates(
        [finalized, recorded_zero, open_w2, open_temp],
        historical_w2_percent_by_user={61: 11.59},
    )
    assert rows[0]["employer_taxes"] == 37.25
    assert rows[0]["total_payroll_cost"] == 340.70
    assert rows[0]["employer_cost_basis"] == "actual"
    assert rows[1]["employer_taxes"] == 0
    assert rows[1]["total_payroll_cost"] == 400
    assert rows[1]["employer_cost_basis"] == "actual"
    assert rows[2]["employer_taxes"] == 420.14
    assert rows[2]["total_payroll_cost"] == 4045.14
    assert rows[2]["employer_cost_basis"] == "estimated"
    assert rows[2]["gross_pay"] == 3625
    assert rows[3]["employer_taxes"] == 0
    assert rows[3]["total_payroll_cost"] == 636.91
    assert rows[3]["employer_cost_basis"] == "gross_only"


def test_configured_rate_overrides_history_and_labels_configured():
    from backend.payroll_hourly_cost import (
        apply_open_period_burden_estimates,
        combine_category_analyses,
        employer_cost_basis_for_rows,
    )

    open_w2 = _payout_row(
        user_id=7, category="w2", gross=1000, taxes=0, recorded=False, status="hours_reviewed"
    )
    open_temp = _payout_row(
        user_id=7, category="temp", gross=200, taxes=0, recorded=False, status="hours_reviewed"
    )
    rows = apply_open_period_burden_estimates(
        [open_w2, open_temp],
        historical_w2_percent_by_user={7: 11.59},
        category_burden_percent={"w2": 10, "temp": 5, "contractor_1099": None},
    )
    assert rows[0]["employer_taxes"] == 100
    assert rows[0]["employer_cost_basis"] == "configured"
    assert rows[1]["employer_taxes"] == 10
    assert rows[1]["employer_cost_basis"] == "configured"
    assert employer_cost_basis_for_rows(rows) == "configured"
    combined = combine_category_analyses(
        [
            {"burden_status": "configured", "burden_label": "Configured", "payable_hours": 10,
             "gross_pay": 1000, "employer_expenses": 100, "total_employer_cost": 1100,
             "worker_category": "w2"},
            {"burden_status": "not_applicable", "burden_label": "N/A", "payable_hours": 10,
             "gross_pay": 200, "employer_expenses": 0, "total_employer_cost": 200,
             "worker_category": "temp"},
        ]
    )
    assert combined["burden_status"] == "configured"


def test_report_reconciliation_keeps_finalized_total_and_estimates_open_w2():
    from backend.payroll_hourly_cost import apply_open_period_burden_estimates
    from backend.payroll_report import _sum_totals

    finalized = _payout_row(
        user_id=1, category="w2", gross=1000, taxes=116, recorded=True, status="paid",
        finalized_at="2026-10-28 12:00:00", start="2026-10-19", end="2026-10-25",
    )
    open_w2 = _payout_row(
        user_id=1, category="w2", gross=500, taxes=0, recorded=False, status="approved_for_payment"
    )
    open_temp = _payout_row(
        user_id=2, category="temp", gross=100, taxes=0, recorded=False, status="hours_reviewed"
    )
    rows = apply_open_period_burden_estimates(
        [finalized, open_w2, open_temp],
        historical_w2_percent=10,
    )
    totals = _sum_totals(rows)
    assert finalized["total_payroll_cost"] == 1116
    assert totals["gross_pay"] == 1600
    assert totals["employer_taxes"] == 166
    assert totals["total_payroll_cost"] == 1766
    assert rows[2]["total_payroll_cost"] == 100


def test_batch_sync_walks_overtime_across_categories_and_rates():
    from backend.payroll_hourly_cost import group_batch_sync_lines

    mixed = [
        {"id": 1, "user_id": 7, "worker_name": "A", "approved_hours": 30,
         "clock_in_at": "2026-11-02 08:00:00", "hourly_rate": 20, "worker_category": "w2"},
        {"id": 2, "user_id": 7, "worker_name": "A", "approved_hours": 20,
         "clock_in_at": "2026-11-03 08:00:00", "hourly_rate": 20, "worker_category": "temp"},
    ]
    w2_lines = group_batch_sync_lines(mixed, batch_category="w2")
    temp_lines = group_batch_sync_lines(mixed, batch_category="temp")
    assert w2_lines[0]["regular_hours"] == 30
    assert w2_lines[0]["ot_hours"] == 0
    assert temp_lines[0]["regular_hours"] == 10
    assert temp_lines[0]["ot_hours"] == 10

    two_rates = [
        {"id": 1, "user_id": 28, "worker_name": "J", "approved_hours": 25,
         "clock_in_at": "2026-10-19 08:00:00", "hourly_rate": 17, "worker_category": "temp"},
        {"id": 2, "user_id": 28, "worker_name": "J", "approved_hours": 20,
         "clock_in_at": "2026-10-22 08:00:00", "hourly_rate": 21, "worker_category": "temp"},
    ]
    lines = group_batch_sync_lines(two_rates, batch_category="temp")
    by_rate = {line["rate"]: line for line in lines}
    assert by_rate[17]["regular_hours"] == 25
    assert by_rate[17]["ot_hours"] == 0
    assert by_rate[21]["regular_hours"] == 15
    assert by_rate[21]["ot_hours"] == 5


def test_mixed_period_keeps_stored_cost_and_estimates_the_open_category():
    from backend.payroll_hourly_cost import combine_stored_and_open_categories

    priced = {
        "category_analyses": [
            {
                "worker_category": "w2",
                "payable_hours": 30,
                "regular_hours": 30,
                "ot_hours": 0,
                "gross_pay": 600,
                "ot_premium": 0,
                "base_earnings": 600,
                "employer_expenses": 60,
                "total_employer_cost": 660,
                "straight_time_employer_cost": 660,
                "burden_status": "estimated",
                "base_wage": 20,
            },
            {
                "worker_category": "temp",
                "payable_hours": 20,
                "regular_hours": 10,
                "ot_hours": 10,
                "gross_pay": 500,
                "ot_premium": 100,
                "base_earnings": 400,
                "employer_expenses": 0,
                "total_employer_cost": 500,
                "straight_time_employer_cost": 400,
                "burden_status": "not_applicable",
                "base_wage": 20,
            },
        ],
        "record_costs": [
            {"id": 1, "worker_category": "w2", "total_employer_cost": 660},
            {"id": 2, "worker_category": "temp", "total_employer_cost": 500},
        ],
    }
    stored = {
        "w2": {
            "worker_category": "w2",
            "payable_hours": 30,
            "regular_hours": 30,
            "ot_hours": 0,
            "gross_pay": 600,
            "ot_premium": 0,
            "base_earnings": 600,
            "employer_expenses": 70,
            "total_employer_cost": 670,
            "straight_time_employer_cost": 670,
            "burden_status": "actual",
            "burden_label": "Actual",
            "base_wage": 20,
        }
    }
    combined = combine_stored_and_open_categories(priced, stored, labor_cost_target=19)
    assert combined["total_employer_cost"] == 1170
    assert combined["ot_hours"] == 10
    assert combined["record_costs"] == [
        {"id": 2, "worker_category": "temp", "total_employer_cost": 500}
    ]
    assert combined["burden_status"] == "actual"


def _open_report_row(**overrides):
    row = {
        "line_id": 10,
        "batch_id": 3,
        "user_id": 7,
        "employee_name": "Alex",
        "worker_category": "temp",
        "pay_period_start": "2026-11-02",
        "pay_period_end": "2026-11-08",
        "payroll_period": "2026-11-02 – 2026-11-08",
        "gross_pay": 400,
        "regular_hours": 20,
        "ot_hours": 0,
        "employer_taxes": 0,
        "employer_cost_recorded": False,
        "total_payroll_cost": 400,
        "batch_status": "hours_reviewed",
        "details_finalized_at": "",
        "payroll_status_key": "hours_reviewed",
    }
    row.update(overrides)
    return row


def _week_record(session_id, hours, category, day, rate=20, *, week_start=None, ot_mode="default"):
    row = {
        "id": session_id,
        "user_id": 7,
        "worker_name": "Alex",
        "approved_hours": hours,
        "clock_in_at": f"{day} 08:00:00",
        "hourly_rate": rate,
        "worker_category": category,
    }
    if week_start:
        row["payroll_week_start"] = week_start
        row["ot_week_mode"] = ot_mode
    return row


def test_open_report_follows_classification_before_sync_and_matches_after():
    """A saved classification moves report hours before sync, without writing the batch."""
    from backend.payroll_hourly_cost import (
        apply_open_period_burden_estimates,
        group_batch_sync_lines,
        project_open_classifications,
    )

    stale_lines = [
        _open_report_row(
            line_id=1, batch_id=1, worker_category="w2", gross_pay=600, regular_hours=30, total_payroll_cost=600
        ),
        _open_report_row(line_id=2, batch_id=2, worker_category="temp"),
    ]
    as_temp_tail = [
        _week_record(1, 30, "w2", "2026-11-02"),
        _week_record(2, 20, "temp", "2026-11-03"),
    ]
    before_sync = project_open_classifications(stale_lines, as_temp_tail)
    by_cat = {}
    for row in before_sync:
        by_cat.setdefault(row["worker_category"], row)
    assert by_cat["w2"]["regular_hours"] == 30
    assert by_cat["w2"]["ot_hours"] == 0
    assert by_cat["temp"]["regular_hours"] == 10
    assert by_cat["temp"]["ot_hours"] == 10
    assert by_cat["temp"]["reporting_projection"] is True
    assert by_cat["temp"]["employer_cost_recorded"] is False
    assert by_cat["temp"]["line_id"] is None
    assert sum(row["regular_hours"] + row["ot_hours"] for row in before_sync) == 50

    priced = apply_open_period_burden_estimates(
        before_sync,
        category_burden_percent={"w2": 10, "temp": None, "contractor_1099": None},
    )
    priced_by_cat = {row["worker_category"]: row for row in priced}
    assert priced_by_cat["w2"]["employer_taxes"] == 60
    assert priced_by_cat["w2"]["total_payroll_cost"] == 660
    assert priced_by_cat["w2"]["employer_cost_basis"] == "configured"
    assert priced_by_cat["temp"]["employer_taxes"] == 0
    assert priced_by_cat["temp"]["total_payroll_cost"] == 500
    assert sum(row["regular_hours"] + row["ot_hours"] for row in priced) == 50

    reversed_records = [
        _week_record(1, 30, "temp", "2026-11-02"),
        _week_record(2, 20, "w2", "2026-11-03"),
    ]
    reversed_rows = project_open_classifications(stale_lines, reversed_records)
    reversed_by_cat = {row["worker_category"]: row for row in reversed_rows}
    assert reversed_by_cat["temp"]["regular_hours"] == 30
    assert reversed_by_cat["temp"]["ot_hours"] == 0
    assert reversed_by_cat["w2"]["regular_hours"] == 10
    assert reversed_by_cat["w2"]["ot_hours"] == 10
    assert sum(row["regular_hours"] + row["ot_hours"] for row in reversed_rows) == 50
    assert sum(row["ot_hours"] for row in reversed_rows) == 10

    for category in ("w2", "temp"):
        synced = group_batch_sync_lines(reversed_records, batch_category=category)
        shown = reversed_by_cat[category]
        assert synced[0]["regular_hours"] == shown["regular_hours"]
        assert synced[0]["ot_hours"] == shown["ot_hours"]

    filtered = project_open_classifications(
        stale_lines, reversed_records, category_filter="w2"
    )
    assert [row["worker_category"] for row in filtered] == ["w2"]
    assert filtered[0]["regular_hours"] + filtered[0]["ot_hours"] == 20


def test_open_report_follows_the_batch_week_overtime_switch():
    """Enabled weeks keep one overtime walk. A disabled week stays regular."""
    from backend.payroll_hourly_cost import group_batch_sync_lines, project_open_classifications

    open_lines = [
        _open_report_row(
            line_id=1, batch_id=1, worker_category="w2", gross_pay=600, regular_hours=30, total_payroll_cost=600
        ),
        _open_report_row(line_id=2, batch_id=2, worker_category="temp"),
    ]

    def shown_matches_sync(records, lines=None):
        shown = project_open_classifications(lines or open_lines, records)
        by_cat = {}
        for row in shown:
            by_cat.setdefault(row["worker_category"], []).append(row)
        for category, report_rows in by_cat.items():
            synced = group_batch_sync_lines(records, batch_category=category)
            assert len(synced) == len(report_rows)
            for sync_line, report_row in zip(
                sorted(synced, key=lambda line: (line["rate"], line["regular_hours"])),
                sorted(report_rows, key=lambda row: (row["regular_rate"], row["regular_hours"])),
            ):
                assert report_row["regular_hours"] == sync_line["regular_hours"]
                assert report_row["ot_hours"] == sync_line["ot_hours"]
                assert report_row["reporting_projection"] is True
                assert report_row["employer_cost_recorded"] is False
                assert report_row["line_id"] is None
        return shown

    enabled = [
        _week_record(1, 30, "w2", "2026-11-02", week_start="2026-11-02"),
        _week_record(2, 20, "temp", "2026-11-03", week_start="2026-11-02"),
    ]
    enabled_rows = shown_matches_sync(enabled)
    assert sum(row["ot_hours"] for row in enabled_rows) == 10
    assert sum(row["regular_hours"] + row["ot_hours"] for row in enabled_rows) == 50

    disabled = [
        _week_record(1, 30, "w2", "2026-11-02", week_start="2026-11-02", ot_mode="disable_ot"),
        _week_record(2, 20, "temp", "2026-11-03", week_start="2026-11-02", ot_mode="disable_ot"),
    ]
    disabled_rows = shown_matches_sync(disabled)
    assert sum(row["ot_hours"] for row in disabled_rows) == 0
    assert sum(row["regular_hours"] for row in disabled_rows) == 50

    two_rates = [
        _week_record(1, 25, "temp", "2026-11-02", rate=17, week_start="2026-11-02", ot_mode="disable_ot"),
        _week_record(2, 20, "w2", "2026-11-04", rate=21, week_start="2026-11-02", ot_mode="disable_ot"),
    ]
    rate_rows = shown_matches_sync(two_rates)
    assert sum(row["ot_hours"] for row in rate_rows) == 0
    assert {row["regular_rate"] for row in rate_rows} == {17.0, 21.0}

    wide = [
        _open_report_row(
            line_id=1,
            worker_category="w2",
            pay_period_start="2026-11-02",
            pay_period_end="2026-11-15",
            gross_pay=900,
            regular_hours=45,
            total_payroll_cost=900,
        ),
        _open_report_row(
            line_id=2,
            worker_category="temp",
            pay_period_start="2026-11-02",
            pay_period_end="2026-11-15",
        ),
    ]
    split_weeks = [
        _week_record(1, 45, "w2", "2026-11-02", week_start="2026-11-02", ot_mode="disable_ot"),
        _week_record(2, 45, "temp", "2026-11-09", week_start="2026-11-09"),
    ]
    split_rows = shown_matches_sync(split_weeks, wide)
    by_cat = {row["worker_category"]: row for row in split_rows}
    assert by_cat["w2"]["regular_hours"] == 45
    assert by_cat["w2"]["ot_hours"] == 0
    assert by_cat["temp"]["regular_hours"] == 40
    assert by_cat["temp"]["ot_hours"] == 5

    stored = _open_report_row(
        line_id=9,
        worker_category="w2",
        gross_pay=600,
        regular_hours=30,
        ot_hours=0,
        employer_taxes=0,
        employer_cost_recorded=True,
        total_payroll_cost=600,
        batch_status="paid",
        details_finalized_at="2026-11-09 12:00:00",
        source_shift_session_ids=[1],
    )
    kept = project_open_classifications([stored, open_lines[1]], disabled)
    assert kept[0]["gross_pay"] == 600
    assert kept[0]["employer_taxes"] == 0
    assert kept[0]["employer_cost_recorded"] is True
    assert kept[0].get("reporting_projection") is not True


def test_projection_keeps_finalized_snapshots_and_does_not_double_count():
    from backend.payroll_hourly_cost import project_open_classifications

    stored = _open_report_row(
        line_id=9,
        worker_category="w2",
        gross_pay=600,
        regular_hours=30,
        ot_hours=0,
        employer_taxes=0,
        employer_cost_recorded=True,
        total_payroll_cost=600,
        batch_status="paid",
        details_finalized_at="2026-11-09 12:00:00",
        source_shift_session_ids=[1],
    )
    open_temp = _open_report_row(line_id=10, worker_category="temp", source_shift_session_ids=[2])
    moved = [
        _week_record(1, 30, "temp", "2026-11-02"),
        _week_record(2, 20, "w2", "2026-11-03"),
    ]
    shown = project_open_classifications([stored, open_temp], moved)
    assert shown[0]["worker_category"] == "w2"
    assert shown[0]["gross_pay"] == 600
    assert shown[0]["employer_taxes"] == 0
    assert shown[0]["employer_cost_recorded"] is True
    assert shown[0].get("reporting_projection") is not True
    projected = [row for row in shown if row.get("reporting_projection")]
    assert len(projected) == 1
    assert projected[0]["worker_category"] == "w2"
    assert projected[0]["regular_hours"] == 10
    assert projected[0]["ot_hours"] == 10
    assert sum(row["regular_hours"] + row["ot_hours"] for row in shown) == 50
    assert sum(row["ot_hours"] for row in shown) == 10


def test_category_reversal_keeps_shared_overtime():
    week = [
        {"id": 1, "approved_hours": 30, "clock_in_at": "2026-11-02 08:00:00", "hourly_rate": 20, "worker_category": "w2"},
        {"id": 2, "approved_hours": 20, "clock_in_at": "2026-11-03 08:00:00", "hourly_rate": 20, "worker_category": "temp"},
    ]
    policies = {
        "w2": {"enabled": True, "threshold_hours": 40, "multiplier": 1.5, "employer_burden_percent": 10},
        "temp": {"enabled": True, "threshold_hours": 40, "multiplier": 1.5, "employer_burden_percent": None},
        "contractor_1099": {"enabled": True, "threshold_hours": 40, "multiplier": 1.5, "employer_burden_percent": None},
    }
    first = price_time_records(week, category_policies=policies)
    reversed_week = [dict(week[0], worker_category="temp"), dict(week[1], worker_category="w2")]
    second = price_time_records(reversed_week, category_policies=policies)
    assert first["ot_hours"] == 10
    assert second["ot_hours"] == 10
    assert first["total_employer_cost"] == 1160
    assert second["total_employer_cost"] == 1150
    again = price_time_records(week, category_policies=policies)
    assert again["total_employer_cost"] == first["total_employer_cost"]


def _jasanpreet_oct_26_records(*, ot_mode):
    """Two Temp rates in one payroll week. Hours are the Oct 26–Nov 1 sessions."""
    sessions = [
        (2006, "2026-10-26", 8.77, 21),
        (2007, "2026-10-27", 12.14, 17),
        (2057, "2026-10-28", 9.99, 21),
        (2077, "2026-10-29", 8.42, 17),
        (2081, "2026-10-30", 11.71, 17),
        (2111, "2026-10-31", 6.38, 21),
    ]
    return [
        {
            "id": session_id,
            "user_id": 28,
            "worker_name": "Jasanpreet",
            "approved_hours": hours,
            "clock_in_at": f"{day} 08:00:00",
            "work_date": day,
            "hourly_rate": rate,
            "resolved_hourly_rate": rate,
            "worker_category": "temp",
            "payroll_week_start": "2026-10-26",
            "ot_week_mode": ot_mode,
        }
        for session_id, day, hours, rate in sessions
    ]


def test_jasanpreet_disabled_week_matches_across_summaries_and_an_enabled_week_keeps_overtime():
    from backend.payroll_hourly_cost import group_batch_sync_lines, project_open_classifications

    disabled = _jasanpreet_oct_26_records(ot_mode="disable_ot")
    economics = economics_from_time_records(disabled, ot_threshold=40, ot_multiplier=1.5)
    assert economics["payable_hours"] == 57.41
    assert economics["ot_hours"] == 0
    assert economics["ot_premium"] == 0
    assert economics["gross_pay"] == 1076.53
    summary = analyze_employee_hourly_cost(
        worker_category="temp",
        payable_hours=economics["payable_hours"],
        regular_hours=economics["regular_hours"],
        ot_hours=economics["ot_hours"],
        base_earnings=economics["base_earnings"],
        ot_premium=economics["ot_premium"],
        gross_pay=economics["gross_pay"],
        total_payroll_cost=economics["gross_pay"],
        employer_taxes=0,
        regular_rates=economics["regular_rates"],
        scenario="contractor",
    )
    assert summary["effective_cost_per_hour"] == 18.75
    assert summary["base_cost_per_hour"] == 18.75
    assert summary["ot_impact_per_hour"] == 0
    priced = price_time_records(disabled, ot_threshold=40, ot_multiplier=1.5)
    assert priced["ot_hours"] == 0
    assert priced["ot_premium"] == 0
    assert priced["payable_hours"] == 57.41
    assert priced["effective_cost_per_hour"] == 18.75
    report = project_open_classifications(
        [
            _open_report_row(
                user_id=28,
                worker_category="temp",
                pay_period_start="2026-10-26",
                pay_period_end="2026-11-01",
                gross_pay=1076.53,
                regular_hours=57.41,
                total_payroll_cost=1076.53,
            )
        ],
        disabled,
    )
    assert sum(row["ot_hours"] for row in report) == 0
    assert round(sum(row["regular_hours"] + row["ot_hours"] for row in report), 2) == 57.41
    synced = group_batch_sync_lines(disabled, batch_category="temp")
    assert sum(line["ot_hours"] for line in synced) == 0
    by_rate = {line["rate"]: line["regular_hours"] for line in synced}
    assert by_rate[21.0] == 25.14
    assert by_rate[17.0] == 32.27

    enabled = _jasanpreet_oct_26_records(ot_mode="default")
    enabled_econ = economics_from_time_records(enabled, ot_threshold=40, ot_multiplier=1.5)
    enabled_priced = price_time_records(enabled, ot_threshold=40, ot_multiplier=1.5)
    enabled_sync = group_batch_sync_lines(enabled, batch_category="temp")
    assert enabled_econ["ot_hours"] == 17.41
    assert enabled_econ["ot_premium"] == 160.75
    assert enabled_priced["ot_hours"] == 17.41
    assert enabled_priced["ot_premium"] == 160.75
    assert round(sum(line["ot_hours"] for line in enabled_sync), 2) == 17.41
    assert {line["rate"] for line in enabled_sync} == {17.0, 21.0}


class _WeekCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, _sql, _params):
        self.conn.queries += 1

    def fetchone(self):
        return {"week_starts_on": 0}


class _WeekConn:
    def __init__(self):
        self.queries = 0

    def cursor(self, dictionary=True):
        return _WeekCursor(self)


def test_schema_scope_uses_the_connection_database_without_querying():
    from backend.ta_helpers import _schema_scope

    class Conn:
        _database = "laundryapp"

        @property
        def database(self):
            raise AssertionError("SELECT DATABASE() should not run")

    class Cursor:
        connection = None

    cursor = Cursor()
    cursor.connection = Conn()
    assert _schema_scope(cursor) == "laundryapp"
    assert _schema_scope(cursor) == "laundryapp"


def test_payroll_week_bounds_reads_the_anchor_once_per_connection():
    from datetime import date

    from backend.payroll_identity import payroll_week_bounds

    conn = _WeekConn()
    first_start, first_end = payroll_week_bounds(conn, date(2026, 10, 28), 3)
    second_start, second_end = payroll_week_bounds(conn, date(2026, 11, 1), 3)
    assert conn.queries == 1
    assert (first_start, first_end) == (date(2026, 10, 26), date(2026, 11, 1))
    assert (second_start, second_end) == (first_start, first_end)


def test_week_ot_schema_skips_create_when_both_tables_exist(monkeypatch):
    from backend.payroll_week_ot import ensure_payroll_week_ot_schema

    class Cursor:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("CREATE should not run")

    monkeypatch.setattr("backend.ta_helpers.table_exists", lambda _cursor, _name: True)
    ensure_payroll_week_ot_schema(Cursor())


def test_shared_hourly_cost_keeps_mixed_overtime_and_a_disabled_week():
    from backend.payroll_hourly_cost import build_hourly_cost_for_time_records

    policies = {
        category: {
            "enabled": True,
            "threshold_hours": 40,
            "multiplier": 1.5,
            "employer_burden_percent": None,
        }
        for category in ("w2", "temp", "contractor_1099")
    }
    lily = [
        {
            "id": 1,
            "approved_hours": 19.02,
            "work_date": "2026-10-26",
            "payroll_week_start": "2026-10-26",
            "ot_week_mode": "default",
            "hourly_rate": 17,
            "worker_category": "w2",
        },
        {
            "id": 2,
            "approved_hours": 20.98,
            "work_date": "2026-10-28",
            "payroll_week_start": "2026-10-26",
            "ot_week_mode": "default",
            "hourly_rate": 17,
            "worker_category": "temp",
        },
        {
            "id": 3,
            "approved_hours": 10.99,
            "work_date": "2026-10-30",
            "payroll_week_start": "2026-10-26",
            "ot_week_mode": "default",
            "hourly_rate": 25.5,
            "worker_category": "temp",
        },
    ]
    shared = {
        "settings": {},
        "policies": policies,
        "history": {61: [], 28: []},
        "rates": {61: [], 28: []},
        "modes": {(28, "2026-10-26"): "disable_ot"},
    }
    mixed = build_hourly_cost_for_time_records(
        object(),
        3,
        61,
        period_start="2026-10-26",
        period_end="2026-11-01",
        records=lily,
        shared=shared,
    )
    direct = price_time_records(
        lily,
        ot_threshold=40,
        ot_multiplier=1.5,
        category_policies=policies,
    )
    assert mixed["ot_hours"] == direct["ot_hours"] == 10.99
    assert mixed["ot_premium"] == direct["ot_premium"]
    assert mixed["gross_pay"] == direct["gross_pay"]
    disabled_records = _jasanpreet_oct_26_records(ot_mode="default")
    disabled = build_hourly_cost_for_time_records(
        object(),
        3,
        28,
        period_start="2026-10-26",
        period_end="2026-11-01",
        records=disabled_records,
        shared=shared,
    )
    straight = price_time_records(
        _jasanpreet_oct_26_records(ot_mode="disable_ot"),
        ot_threshold=40,
        ot_multiplier=1.5,
        category_policies=policies,
    )
    assert disabled["ot_hours"] == straight["ot_hours"] == 0
    assert disabled["ot_premium"] == straight["ot_premium"] == 0
    assert disabled["payable_hours"] == 57.41
    assert disabled["gross_pay"] == 1076.53


def test_batched_hourly_cost_reads_payroll_history_once(monkeypatch):
    from backend.payroll_hourly_cost import build_hourly_costs_for_time_records

    calls = {"history": 0}

    def fake_report(*_args, **_kwargs):
        calls["history"] += 1
        return {"rows": []}

    monkeypatch.setattr("backend.payroll_report.query_payroll_report", fake_report)
    monkeypatch.setattr(
        "backend.payroll_tax_settings.fetch_payroll_tax_settings",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "backend.payroll_hourly_cost.load_category_cost_assumptions",
        lambda *_args, **_kwargs: {
            "temp": {
                "enabled": True,
                "threshold_hours": 40,
                "multiplier": 1.5,
                "employer_burden_percent": None,
            }
        },
    )
    monkeypatch.setattr(
        "backend.payroll_hourly_cost._rates_by_user",
        lambda *_args, **_kwargs: {28: [], 61: []},
    )
    monkeypatch.setattr(
        "backend.payroll_week_ot.load_employee_week_ot_modes",
        lambda *_args, **_kwargs: {(28, "2026-10-26"): "disable_ot"},
    )
    analyses = build_hourly_costs_for_time_records(
        object(),
        3,
        [
            {
                "user_id": 61,
                "records": [
                    {
                        "approved_hours": 50.99,
                        "work_date": "2026-10-26",
                        "payroll_week_start": "2026-10-26",
                        "clock_in_at": "2026-10-26 08:00:00",
                        "hourly_rate": 17,
                        "worker_category": "temp",
                    }
                ],
            },
            {
                "user_id": 28,
                "records": _jasanpreet_oct_26_records(ot_mode="default"),
            },
        ],
        period_start="2026-10-26",
        period_end="2026-11-01",
    )
    assert calls["history"] == 1
    assert analyses[0]["ot_hours"] == 10.99
    assert analyses[1]["ot_hours"] == 0
    assert analyses[1]["gross_pay"] == 1076.53
