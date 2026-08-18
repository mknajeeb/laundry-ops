"""Split Cost Simulator V1 — pure math + identity tests (no DB)."""

from __future__ import annotations

from backend.management_split_cost_simulator import (
    combo_key_from_supplies,
    compare_baseline_target,
    simulate_split_cost,
)
from backend.supply_usage import supplies_for_usage


COMBOS = [
    {
        "key": "Tide + Downy + OxiClean",
        "label": "Tide + Downy + OxiClean",
        "share": 0.5,
        "cost_per_load": 1.0,
        "products": [],
    },
    {
        "key": "Tide",
        "label": "Tide",
        "share": 0.5,
        "cost_per_load": 0.5,
        "products": [],
    },
]


def test_loads_identity_0_50_100_percent():
    for pct, expect_loads in ((0, 100), (50, 150), (100, 200)):
        out = simulate_split_cost(
            total_orders=100,
            split_rate=pct / 100.0,
            avg_lb_per_bag=20.5,
            combinations=COMBOS,
        )
        assert out["total_loads"] == expect_loads
        assert out["split_orders"] + out["non_split_orders"] == 100
        assert out["estimated_lbs"] == 2050.0


def test_est_cost_per_lb_and_savings():
    baseline = simulate_split_cost(
        total_orders=100,
        split_rate=0.5,
        avg_lb_per_bag=20.5,
        combinations=COMBOS,
    )
    target = simulate_split_cost(
        total_orders=100,
        split_rate=0.25,
        avg_lb_per_bag=20.5,
        combinations=COMBOS,
    )
    assert baseline["total_loads"] == 150
    assert target["total_loads"] == 125
    assert baseline["est_cost_per_lb"] == round(
        baseline["estimated_supply_cost"] / 2050.0, 4
    )
    cmp_ = compare_baseline_target(baseline, target)
    assert cmp_["loads_saved"] == 25
    assert cmp_["dollar_savings"] > 0
    assert cmp_["headline"]["est_cost_per_lb_from"] == baseline["est_cost_per_lb"]
    assert cmp_["headline"]["est_cost_per_lb_to"] == target["est_cost_per_lb"]


def test_shares_total_orders():
    out = simulate_split_cost(
        total_orders=100,
        split_rate=0.0,
        avg_lb_per_bag=20.0,
        combinations=COMBOS,
    )
    assert sum(c["estimated_orders"] for c in out["combinations"]) == 100
    assert out["total_loads"] == 100


def test_combo_key_uses_supplies_used_not_mapping_dict_keys():
    """Regression: supplies_for_usage returns a dict; mix must use supplies_used."""
    mapped = supplies_for_usage("USE FABRIC SOFTENER; USE OXICLEAN")
    supplies = list((mapped or {}).get("supplies_used") or ["Tide"])
    key = combo_key_from_supplies(supplies)
    assert "special_instructions_raw" not in key
    assert "Tide" in key
    assert "Downy" in key
    assert "OxiClean" in key
