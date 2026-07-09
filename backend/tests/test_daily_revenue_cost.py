"""Tests for daily revenue & cost calculations."""

from decimal import Decimal

from backend.daily_revenue_cost import (
    calc_payroll_tax,
    commercial_line_revenue,
    commercial_line_revenue_from_pricing,
    cumulative_wf_revenue,
)
from backend.daily_revenue_cost_constants import BILLING_FLAT, BILLING_HYBRID

DEFAULT_TIERS = [
    {"tier_number": 1, "max_lbs": 5000, "rate_per_lb": 1.00},
    {"tier_number": 2, "max_lbs": None, "rate_per_lb": 0.95},
]


def test_cumulative_wf_revenue_tier1_only():
    assert cumulative_wf_revenue(3000, DEFAULT_TIERS) == Decimal("3000.00")


def test_cumulative_wf_revenue_crosses_tiers():
    assert cumulative_wf_revenue(6000, DEFAULT_TIERS) == Decimal("5950.00")


def test_cumulative_wf_revenue_zero():
    assert cumulative_wf_revenue(0, DEFAULT_TIERS) == Decimal("0")


def test_commercial_line_revenue_per_lb():
    assert commercial_line_revenue(100, 1.25, 50, 25) == 200.0


def test_commercial_line_revenue_flat():
    pricing = {"billing_model": BILLING_FLAT, "flat_amount": 500, "logistics_charge": 25, "additional_charge": 0}
    assert commercial_line_revenue_from_pricing(0, pricing) == 525.0


def test_commercial_line_revenue_hybrid():
    pricing = {
        "billing_model": BILLING_HYBRID,
        "rate_per_pound": 1.0,
        "flat_amount": 200,
        "logistics_charge": 0,
        "additional_charge": 0,
    }
    assert commercial_line_revenue_from_pricing(100, pricing) == 200.0
    assert commercial_line_revenue_from_pricing(300, pricing) == 300.0


def test_calc_payroll_tax_percent():
    settings = {"payroll_tax_pct": 10, "payroll_tax_daily_fixed": None}
    assert calc_payroll_tax(1000, settings) == 100.0


def test_calc_payroll_tax_fixed():
    settings = {"payroll_tax_pct": 10, "payroll_tax_daily_fixed": 75}
    assert calc_payroll_tax(1000, settings) == 75.0


def test_wf_day_revenue_incremental():
    before = cumulative_wf_revenue(4800, DEFAULT_TIERS)
    after = cumulative_wf_revenue(5200, DEFAULT_TIERS)
    day_rev = after - before
    assert day_rev == Decimal("390.00")
