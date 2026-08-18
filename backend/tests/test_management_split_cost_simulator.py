"""Canonical Supply Cost Simulator — independent mix engine tests."""

from __future__ import annotations

from backend.management_split_cost_simulator import (
    compare_scenarios,
    expected_cost_per_load,
    mix_pcts_from_counts,
    normalize_detergent_pcts,
    period_savings,
    resolve_period_dates,
    simulate_supply_cost,
)
from datetime import date


COSTS = {"tide": 0.5294, "ultra_clean": 0.366, "downy": 0.3412, "oxiclean": 0.2226}


def test_loads_identity_0_50_100():
    for pct, expect in ((0, 100), (50, 150), (100, 200)):
        out = simulate_supply_cost(
            total_orders=100,
            split_pct=pct,
            avg_lb_per_bag=20.35,
            tide_pct=70,
            ultra_clean_pct=30,
            downy_pct=36,
            oxiclean_pct=51,
            unit_costs=COSTS,
        )
        assert out["total_loads"] == expect
        assert out["split_orders"] + out["non_split_orders"] == 100


def test_cost_scales_with_loads():
    z = simulate_supply_cost(
        total_orders=100,
        split_pct=0,
        avg_lb_per_bag=20,
        tide_pct=100,
        ultra_clean_pct=0,
        downy_pct=0,
        oxiclean_pct=0,
        unit_costs=COSTS,
    )
    f = simulate_supply_cost(
        total_orders=100,
        split_pct=100,
        avg_lb_per_bag=20,
        tide_pct=100,
        ultra_clean_pct=0,
        downy_pct=0,
        oxiclean_pct=0,
        unit_costs=COSTS,
    )
    assert z["total_loads"] == 100 and f["total_loads"] == 200
    assert abs(f["estimated_supply_cost"] - 2 * z["estimated_supply_cost"]) < 0.05


def test_independent_addon_cost():
    base = expected_cost_per_load(
        tide_pct=100,
        ultra_clean_pct=0,
        downy_pct=0,
        oxiclean_pct=0,
        unit_costs=COSTS,
    )
    with_downy = expected_cost_per_load(
        tide_pct=100,
        ultra_clean_pct=0,
        downy_pct=100,
        oxiclean_pct=0,
        unit_costs=COSTS,
    )
    assert abs(with_downy - (base + COSTS["downy"])) < 1e-6


def test_normalize_detergent():
    t, u = normalize_detergent_pcts(72, 28)
    assert abs(t + u - 100) < 1e-6
    t2, u2 = normalize_detergent_pcts(36, 14)
    assert abs(t2 - 72) < 0.01 and abs(u2 - 28) < 0.01


def test_mix_pcts_independent_addons():
    mix = mix_pcts_from_counts(total=100, tide_n=72, ultra_n=28, downy_n=36, oxi_n=51)
    assert mix["tide_pct"] + mix["ultra_clean_pct"] == 100.0
    assert mix["downy_pct"] == 36.0
    assert mix["oxiclean_pct"] == 51.0
    # addons need not sum to 100
    assert mix["downy_pct"] + mix["oxiclean_pct"] != 100.0


def test_period_savings_and_compare():
    a = simulate_supply_cost(
        total_orders=110,
        split_pct=58.9,
        avg_lb_per_bag=20.35,
        tide_pct=66,
        ultra_clean_pct=34,
        downy_pct=30,
        oxiclean_pct=45,
        unit_costs=COSTS,
    )
    b = simulate_supply_cost(
        total_orders=110,
        split_pct=45,
        avg_lb_per_bag=20.35,
        tide_pct=66,
        ultra_clean_pct=34,
        downy_pct=30,
        oxiclean_pct=45,
        unit_costs=COSTS,
    )
    cmp_ = compare_scenarios(a, b, shifts_per_week=7)
    assert cmp_["loads_saved"] > 0
    assert cmp_["period_savings"]["per_week"] == round(cmp_["dollar_savings"] * 7, 2)
    p = period_savings(23.54, shifts_per_week=7)
    assert p["per_month"] == round(p["per_week"] * 52 / 12, 2)


def test_resolve_period_dates():
    today = date(2026, 8, 18)
    s, e, lab = resolve_period_dates("yesterday", today=today)
    assert s == e == date(2026, 8, 17)
    s, e, lab = resolve_period_dates("last_7", today=today)
    assert s == date(2026, 8, 12) and e == today
