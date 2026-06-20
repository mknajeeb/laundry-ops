"""Tests for NY/NYC NYS-50 withholding tables."""

from decimal import Decimal

from backend.ny_nyc_withholding_2026 import nyc_withholding_nys50, ny_state_withholding_nys50


def test_ny_state_weekly_low_wage():
    tax = ny_state_withholding_nys50(Decimal("400"), pay_frequency="weekly", married=False)
    assert tax > 0
    assert tax < 50


def test_nyc_resident_weekly_low_wage():
    tax = nyc_withholding_nys50(Decimal("400"), pay_frequency="weekly", married=False)
    assert tax > 0
    assert tax < 30
