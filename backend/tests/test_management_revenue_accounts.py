"""Management Revenue Accounts — unit tests."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.management_revenue_accounts import (
    PRICING_TIERED_LB,
    _period_bounds_extended,
    _wf_tiers_from_pricing,
    build_account_revenue_day,
)


def test_period_bounds_yesterday_and_previous_month():
    ref = date(2026, 8, 19)
    y_start, y_end = _period_bounds_extended("yesterday", ref, None, None)
    assert y_start == date(2026, 8, 18)
    pm_start, pm_end = _period_bounds_extended("previous_month", ref, None, None)
    assert pm_start == date(2026, 7, 1)
    assert pm_end == date(2026, 7, 31)


def test_wf_tiers_from_pricing_not_hardcoded():
    tiers = _wf_tiers_from_pricing({
        "pricing_method": PRICING_TIERED_LB,
        "tiers": [{"tier_number": 1, "max_lbs": 5000, "rate_per_lb": 1.0}],
    })
    assert tiers[0]["max_lbs"] == 5000


@patch("backend.management_revenue_accounts.list_accounts")
@patch("backend.management_revenue_accounts.ensure_mgmt_revenue_account_tables")
def test_build_account_revenue_day_shape(mock_ensure, mock_list):
    mock_list.return_value = [
        {
            "id": 1,
            "account_code": "rinse_wf",
            "revenue_group": "rinse_wf",
            "revenue_mode": "calculated",
            "pricing": {
                "pricing_method": PRICING_TIERED_LB,
                "tiers": [{"tier_number": 1, "max_lbs": 5000, "rate_per_lb": 1.0}],
            },
        },
        {
            "id": 2,
            "account_code": "self_service",
            "revenue_group": "non_rinse",
            "revenue_mode": "absolute",
        },
        {
            "id": 3,
            "name": "Auburn",
            "parent_id": 99,
            "revenue_group": "dhs",
            "revenue_mode": "calculated",
            "dr_commercial_account_id": 10,
            "pricing": {"pricing_method": "flat_lb", "rate_per_unit": 0.95},
        },
    ]
    cursor = MagicMock()
    lines = {
        "revenue.self_service.cash": {"amount": 10},
        "revenue.self_service.card": {"amount": 5},
        "revenue.drop_off.cash": {"amount": 3},
        "revenue.drop_off.card": {"amount": 2},
        "revenue.commercial.10.pounds": {"amount": 100},
    }
    with patch("backend.management_revenue_accounts.wf_revenue_for_day", return_value=(50.0, {})):
        block = build_account_revenue_day(cursor, 1, date(2026, 8, 19), lines)
    assert block["rinse"]["wf"]["enabled"] is True
    assert block["non_rinse_revenue"]["self_service"]["total"] == 15.0
    assert len(block["dhs"]["accounts"]) == 1
    assert block["dhs"]["accounts"][0]["name"] == "Auburn"


def test_account_row_includes_date_basis_flags():
    from backend.management_revenue_accounts import _account_row_to_dict
    row = {
        "id": 1,
        "parent_id": None,
        "account_code": "dhs_x",
        "name": "Clarkson",
        "revenue_group": "dhs",
        "service_type": None,
        "revenue_mode": "calculated",
        "active": 1,
        "allow_override": 1,
        "use_pickup_date": 0,
        "use_processing_date": 1,
        "use_delivery_date": 0,
        "start_date": None,
        "end_date": None,
        "dr_commercial_account_id": 3,
        "notes": None,
        "sort_order": 0,
    }
    d = _account_row_to_dict(row)
    assert d["use_processing_date"] is True
    assert d["use_pickup_date"] is False
    assert d["allow_override"] is True
