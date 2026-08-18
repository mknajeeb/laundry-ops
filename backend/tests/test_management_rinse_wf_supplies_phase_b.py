"""Phase B — Management Rinse WF Supplies: membership, rush scope, provisional split."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from backend.management_rinse_wf_supplies import (
    _product_usage_cards,
    build_management_wf_supply_summary,
    load_orders_for_management_wf_supplies,
    management_wf_supply_membership,
    normalize_rush_scope,
    reconcile_scope_populations,
)
from backend.management_today import extract_supplies
from backend.supply_product_master import calculate_cost_metrics, resolve_price_as_of


DAY = date(2026, 8, 17)


def test_normalize_rush_scope():
    assert normalize_rush_scope("ALL") == "all"
    assert normalize_rush_scope("rush") == "rush"
    assert normalize_rush_scope("non-rush") == "non_rush"
    assert normalize_rush_scope("wf_non_rush") == "non_rush"


def test_membership_filters_wf_and_rush():
    bags = [
        {"bag_id": "0AAAAAAA01", "service_type": "WF", "rush_status": "RUSH"},
        {"bag_id": "0AAAAAAA02", "service_type": "WF", "rush_status": "NON_RUSH"},
        {"bag_id": "0HHHHHHHH1", "service_type": "HD", "rush_status": "RUSH"},
    ]
    with patch(
        "backend.management_rinse_wf_supplies.load_day_bags",
        return_value=bags,
    ):
        all_rows = management_wf_supply_membership(MagicMock(), 3, DAY, rush_scope="all")
        rush_rows = management_wf_supply_membership(MagicMock(), 3, DAY, rush_scope="rush")
        non_rows = management_wf_supply_membership(
            MagicMock(), 3, DAY, rush_scope="non_rush"
        )
    assert {r["bag_id"] for r in all_rows} == {"0AAAAAAA01", "0AAAAAAA02"}
    assert {r["bag_id"] for r in rush_rows} == {"0AAAAAAA01"}
    assert {r["bag_id"] for r in non_rows} == {"0AAAAAAA02"}


def test_scope_reconcile_unique_bags():
    bags = [
        {"bag_id": "0RRRRRRRR1", "service_type": "WF", "rush_status": "RUSH"},
        {"bag_id": "0NNNNNNNN1", "service_type": "WF", "rush_status": "NON_RUSH"},
        {"bag_id": "0NNNNNNNN2", "service_type": "WF", "rush_status": "NON_RUSH"},
    ]
    with patch(
        "backend.management_rinse_wf_supplies.load_day_bags",
        return_value=bags,
    ):
        out = reconcile_scope_populations(MagicMock(), 3, DAY)
    assert out["all"] == 3
    assert out["rush"] == 1
    assert out["non_rush"] == 2
    assert out["match"] is True


def test_unresolved_split_excluded_from_confirmed_totals():
    membership = [
        {"bag_id": "CONF1", "service_type": "WF", "rush_status": "RUSH"},
        {"bag_id": "PEND1", "service_type": "WF", "rush_status": "RUSH"},
        {"bag_id": "SPLIT1", "service_type": "WF", "rush_status": "NON_RUSH"},
    ]
    meta = {
        "CONF1": {
            "ticket_id": "CONF1",
            "name_clean": "A",
            "special_instructions_raw": None,
            "_source": "test",
        },
        "PEND1": {
            "ticket_id": "PEND1",
            "name_clean": "B",
            "special_instructions_raw": None,
            "_source": "test",
        },
        "SPLIT1": {
            "ticket_id": "SPLIT1",
            "name_clean": "C",
            "special_instructions_raw": "Use Fabric Softener",
            "_source": "test",
        },
    }

    evaluations = {
        "SPLIT1": {
            "processing_units": 2,
            "canonical_split": True,
            "split_finalized": True,
            "state": "CONFIRMED_SPLIT",
            "washer_load_count": 2,
            "washer_racks": ["W1", "W2"],
            "split_marker_present": True,
        },
        "PEND1": {
            "processing_units": 1,
            "canonical_split": None,
            "split_finalized": False,
            "state": "REVIEW_REQUIRED",
            "washer_load_count": 1,
            "washer_racks": ["W1"],
            "split_marker_present": True,
            "review_reason": "split_marked_but_second_washer_not_found",
        },
        "CONF1": {
            "processing_units": 1,
            "canonical_split": False,
            "split_finalized": True,
            "state": "CONFIRMED_NOT_SPLIT",
            "washer_load_count": 1,
            "washer_racks": ["W1"],
            "split_marker_present": False,
        },
    }

    with (
        patch(
            "backend.management_rinse_wf_supplies.management_wf_supply_membership",
            return_value=membership,
        ),
        patch(
            "backend.management_rinse_wf_supplies._load_approved_order_metadata",
            return_value=meta,
        ),
        patch(
            "backend.management_rinse_wf_supplies.evaluate_day_wf_splits",
            return_value=evaluations,
        ),
        patch(
            "backend.management_rinse_wf_supplies.get_supply_usage_mapping_rules",
            return_value=[],
        ),
    ):
        orders, ids = load_orders_for_management_wf_supplies(
            MagicMock(), 3, DAY, rush_scope="all"
        )

    assert set(ids) == {"CONF1", "PEND1", "SPLIT1"}
    by_id = {o["order_id"]: o for o in orders}
    assert by_id["CONF1"]["confirmed_for_supply"] is True
    assert by_id["CONF1"]["confirmed_processing_units"] == 1
    assert by_id["PEND1"]["confirmed_for_supply"] is False
    assert by_id["PEND1"]["confirmed_processing_units"] == 0
    assert by_id["SPLIT1"]["confirmed_processing_units"] == 2

    cards = _product_usage_cards(
        orders,
        [
            {
                "id": 1,
                "legacy_report_key": "Tide",
                "brand": "Tide",
                "product_name": "Tide Original",
                "average_dose": 2.0,
                "dose_unit": "oz",
                "cost_per_dose": 0.25,
            },
            {
                "id": 2,
                "legacy_report_key": "Downy",
                "brand": "Downy",
                "average_dose": 1.0,
                "dose_unit": "oz",
                "cost_per_dose": 0.10,
            },
        ],
    )
    tide = next(c for c in cards if c["legacy_report_key"] == "Tide")
    # CONF1 (1) + SPLIT1 (2) — PEND1 excluded
    assert tide["orders_using"] == 2
    assert tide["confirmed_loads"] == 3
    assert tide["label"] == "Tide Original"
    assert tide["quantity_used"] == 6.0
    assert tide["estimated_cost"] == 0.75


def test_extract_supplies_phase_b_status_and_products():
    report = {
        "available": True,
        "cost_available": True,
        "cost": 1.5,
        "rush_filtering_supported": True,
        "scope": "rush",
        "scope_label": "RUSH",
        "supply_finalizable": False,
        "supply_status": "PROVISIONAL",
        "supply_banner": "PROVISIONAL · 2 split reviews pending",
        "supply_banner_detail": (
            "Costs may increase after pending split reviews are resolved. "
            "Confirmed totals exclude unresolved split increments."
        ),
        "pending_split_reviews": 2,
        "population": {"orders": 10, "confirmed_orders": 8},
        "dashboard": {
            "period_grain": "day",
            "total_supply_cost": 1.5,
            "total_doses": 6,
            "unique_orders": 10,
            "confirmed_loads": 9,
            "kpis": {"cost_per_order": 0.1875, "cost_per_load": 0.1667},
        },
        "products": [
            {
                "legacy_report_key": "Tide",
                "label": "Tide",
                "orders_using": 5,
                "confirmed_loads": 6,
                "confirmed_doses": 6,
                "quantity_used": 12.0,
                "estimated_cost": 1.5,
                "cost_per_dose": 0.25,
            }
        ],
        "usage_by_supply": {
            "Tide": {
                "orders": 5,
                "doses": 6,
                "ounces": 12.0,
                "estimated_cost": 1.5,
            }
        },
    }
    out = extract_supplies(report)
    assert out["supply_status"] == "PROVISIONAL"
    assert out["pending_split_reviews"] == 2
    assert out["rush_filtering_supported"] is True
    assert out["cost_available"] is True
    assert out["dashboard"]["total_doses"] == 6
    assert out["supply_banner_detail"]
    assert out["Tide"]["confirmed_loads"] == 6
    assert out["Tide"]["estimated_cost"] == 1.5
    assert out["products"][0]["orders_using"] == 5


def test_historical_price_as_of_selected_date():
    rows = [
        {
            "purchase_price_per_package": 10.0,
            "effective_from": date(2026, 1, 1),
            "effective_to": date(2026, 8, 16),
        },
        {
            "purchase_price_per_package": 20.0,
            "effective_from": date(2026, 8, 17),
            "effective_to": None,
        },
    ]
    past = resolve_price_as_of(rows, date(2026, 8, 10))
    today = resolve_price_as_of(rows, date(2026, 8, 17))
    assert float(past["purchase_price_per_package"]) == 10.0
    assert float(today["purchase_price_per_package"]) == 20.0
    metrics = calculate_cost_metrics(
        package_qty=100,
        average_dose=2,
        purchase_price_per_package=past["purchase_price_per_package"],
    )
    assert metrics["cost_per_dose"] == 0.2


def test_summary_wires_product_master(monkeypatch):
    fake_orders = [
        {
            "order_id": "X1",
            "supplies_used": ["Tide"],
            "confirmed_for_supply": True,
            "confirmed_processing_units": 1,
            "confirmed_doses_by_supply": {"Tide": 1},
            "split_state": "CONFIRMED_NOT_SPLIT",
            "split_finalized": True,
        },
        {
            "order_id": "X2",
            "supplies_used": ["Tide"],
            "confirmed_for_supply": False,
            "confirmed_processing_units": 0,
            "confirmed_doses_by_supply": {},
            "split_state": "PENDING",
            "split_finalized": False,
        },
    ]
    products = [
        {
            "id": 9,
            "legacy_report_key": "Tide",
            "brand": "Tide",
            "product_name": "Tide Liquid",
            "average_dose": 2.0,
            "dose_unit": "fl oz",
            "cost_per_dose": 0.5,
            "is_active": True,
        }
    ]
    membership = [
        {"bag_id": "X1", "service_type": "WF", "pre_weight_lbs": 10.0, "post_weight_lbs": 9.0},
        {"bag_id": "X2", "service_type": "WF", "pre_weight_lbs": 8.0},
    ]
    monkeypatch.setattr(
        "backend.management_rinse_wf_supplies.management_wf_supply_membership",
        lambda *a, **k: membership,
    )
    monkeypatch.setattr(
        "backend.management_rinse_wf_supplies.load_orders_for_management_wf_supplies",
        lambda *a, **k: (fake_orders, ["X1", "X2"]),
    )
    monkeypatch.setattr(
        "backend.management_rinse_wf_supplies._active_products_as_of",
        lambda *a, **k: products,
    )
    monkeypatch.setattr(
        "backend.management_rinse_wf_supplies.get_supply_usage_mapping_rules",
        lambda *a, **k: [],
    )
    summary = build_management_wf_supply_summary(MagicMock(), 3, DAY, rush_scope="all")
    assert summary["population"]["orders"] == 2
    assert summary["population"]["confirmed_orders"] == 1
    assert summary["population"]["unresolved_split_orders"] == 1
    assert summary["supply_status"] == "PROVISIONAL"
    assert summary["pending_split_reviews"] == 1
    assert "split review" in (summary["supply_banner"] or "").lower()
    assert "Final cost may increase" in (summary["supply_banner_detail"] or "")
    tide = summary["products"][0]
    assert tide["confirmed_loads"] == 1
    assert tide["quantity_used"] == 2.0
    assert tide["estimated_cost"] == 0.5
    assert tide["label"] == "Tide Liquid"
    assert summary["cost_available"] is True
    dash = summary["dashboard"]
    assert dash["period_grain"] == "day"
    assert dash["unique_orders"] == 2
    assert dash["workload_orders"] == 2
    assert dash["confirmed_supply_orders"] == 1
    assert dash["confirmed_loads"] == 1
    assert dash["total_doses"] == 1
    assert dash["total_supply_cost"] == 0.5
    assert dash["kpis"]["cost_per_order"] == 0.5
    assert dash["kpis"]["cost_per_load"] == 0.5
    assert dash["pounds_available"] is True
    assert dash["pounds"] == 9.0
    assert dash["kpis"]["cost_per_lb"] == round(0.5 / 9.0, 4)
    assert dash["pounds_scope"] == "confirmed_supply_orders"
