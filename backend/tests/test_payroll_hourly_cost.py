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
    weighted_burden_from_periods,
)
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
