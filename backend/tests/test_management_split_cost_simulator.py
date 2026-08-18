"""Split Cost Simulator — pure math + identity + mix classification tests."""

from __future__ import annotations

from backend.management_split_cost_simulator import (
    _classify_order_supplies,
    _build_order_mix,
    combo_key_from_supplies,
    compare_baseline_target,
    period_savings,
    short_combo_label,
    simulate_split_cost,
)
from backend.supply_product_constants import (
    LEGACY_KEY_DOWNY,
    LEGACY_KEY_OXICLEAN,
    LEGACY_KEY_TIDE,
    SUPPLY_TYPE_BOOSTER_OXI,
    SUPPLY_TYPE_DETERGENT,
    SUPPLY_TYPE_FABRIC_SOFTENER,
    SUPPLY_TYPE_HYPO_DETERGENT,
)
from backend.supply_usage import supplies_for_usage


COMBOS = [
    {
        "key": "Tide + Downy + OxiClean",
        "label": "Tide + Downy + Oxi",
        "short_label": "Tide + Downy + Oxi",
        "share": 0.5,
        "cost_per_load": 1.0,
        "products": [],
    },
    {
        "key": "Tide",
        "label": "Tide only",
        "short_label": "Tide only",
        "share": 0.5,
        "cost_per_load": 0.5,
        "products": [],
    },
]

PRODUCTS = {
    "Tide": {"supply_type": SUPPLY_TYPE_DETERGENT, "brand": "Tide"},
    "Downy": {"supply_type": SUPPLY_TYPE_FABRIC_SOFTENER, "brand": "Downy"},
    "OxiClean": {"supply_type": SUPPLY_TYPE_BOOSTER_OXI, "brand": "OxiClean"},
    "Kirkland": {"supply_type": SUPPLY_TYPE_HYPO_DETERGENT, "brand": "Kirkland"},
}


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
    cmp_ = compare_baseline_target(baseline, target, shifts_per_week=7)
    assert cmp_["loads_saved"] == 25
    assert cmp_["dollar_savings"] > 0
    assert cmp_["period_savings"]["per_week"] == round(cmp_["dollar_savings"] * 7, 2)
    assert cmp_["period_savings"]["per_month"] == round(
        cmp_["period_savings"]["per_week"] * 52 / 12, 2
    )


def test_period_savings_math():
    p = period_savings(23.54, shifts_per_week=7)
    assert p["per_shift"] == 23.54
    assert p["per_week"] == round(23.54 * 7, 2)
    assert p["per_month"] == round(p["per_week"] * 52 / 12, 2)


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
    mapped = supplies_for_usage("USE FABRIC SOFTENER; USE OXICLEAN")
    supplies = list((mapped or {}).get("supplies_used") or ["Tide"])
    key = combo_key_from_supplies(supplies)
    assert "special_instructions_raw" not in key
    assert LEGACY_KEY_TIDE in key
    assert LEGACY_KEY_DOWNY in key
    assert LEGACY_KEY_OXICLEAN in key


def test_order_mix_classification_and_reconcile():
    # 100 orders: 60 Tide, 40 Kirkland; 30 Downy; 25 Oxi; 10 both; rest no addon
    standard = hypo = downy = oxi = no_addon = both = 0
    for i in range(100):
        if i < 60:
            supplies = ["Tide"]
            standard += 1
        else:
            supplies = ["Kirkland"]
            hypo += 1
        if i < 30:
            supplies = list(supplies) + ["Downy"]
            downy += 1
        if i < 25:
            supplies = list(supplies) + ["OxiClean"]
            oxi += 1
        has_d = "Downy" in supplies
        has_o = "OxiClean" in supplies
        if has_d and has_o:
            both += 1
        if not has_d and not has_o:
            no_addon += 1
        kind, hd, ho = _classify_order_supplies(supplies, PRODUCTS)
        assert kind in ("standard", "hypo")
        assert hd == has_d
        assert ho == has_o

    mix = _build_order_mix(
        total_orders=100,
        standard_n=standard,
        hypo_n=hypo,
        downy_n=downy,
        oxi_n=oxi,
        no_addon_n=no_addon,
        both_addon_n=both,
    )
    assert mix["detergent_standard_order_pct"] + mix["detergent_hypo_order_pct"] == 100.0
    assert mix["downy_order_pct"] == 30.0
    assert mix["oxiclean_order_pct"] == 25.0


def test_short_combo_labels():
    assert short_combo_label("Tide", PRODUCTS) == "Tide only"
    assert "Hypo" in short_combo_label("Kirkland + OxiClean", PRODUCTS)
    assert "Oxi" in short_combo_label("Tide + Downy + OxiClean", PRODUCTS)
