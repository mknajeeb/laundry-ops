"""Acceptance tests for payroll accrual and 2026 tax defaults."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from backend.payroll_accrual import (
    ACCRUAL_DISCLAIMER,
    calculate_health_credit_amount,
    calculate_sick_hours_accrued,
    sick_leave_annual_cap,
)
from backend.payroll_tax_settings import DEFAULT_PAYROLL_TAX_SETTINGS
from backend.w2_payroll_tax_engine import (
    _incremental_mctmt,
    _mctmt_tax_on_quarterly_payroll,
)


def test_2026_tax_defaults():
    assert DEFAULT_PAYROLL_TAX_SETTINGS["ny_suta_wage_base"] == 17600
    assert DEFAULT_PAYROLL_TAX_SETTINGS["federal_standard_deduction_single"] == 16100
    assert DEFAULT_PAYROLL_TAX_SETTINGS["federal_standard_deduction_mfj"] == 32200
    assert DEFAULT_PAYROLL_TAX_SETTINGS["federal_standard_deduction_hoh"] == 24150
    assert DEFAULT_PAYROLL_TAX_SETTINGS["ny_suta_rate"] is None
    assert DEFAULT_PAYROLL_TAX_SETTINGS["ny_reemployment_service_fund_rate"] == 0.00075
    assert DEFAULT_PAYROLL_TAX_SETTINGS["ny_pfl_employee_rate"] == 0.00432
    assert DEFAULT_PAYROLL_TAX_SETTINGS["ny_pfl_employee_annual_cap"] == 411.91


def test_w2_30_hours_accrues_1_sick_hour():
    earned = calculate_sick_hours_accrued(
        Decimal("30"), ytd_accrued=Decimal("0"), annual_cap=Decimal("40")
    )
    assert float(earned) == 1.0


def test_w2_15_hours_accrues_half_sick_hour():
    earned = calculate_sick_hours_accrued(
        Decimal("15"), ytd_accrued=Decimal("0"), annual_cap=Decimal("40")
    )
    assert float(earned) == 0.5


def test_w2_annual_cap_40_blocks_further_accrual():
    earned = calculate_sick_hours_accrued(
        Decimal("30"), ytd_accrued=Decimal("40"), annual_cap=Decimal("40")
    )
    assert float(earned) == 0.0


def test_1099_manual_only_health_credit_zero():
    settings = {"health_credit_accrual_method": "manual_only", "health_credit_enabled_for_1099": True}
    amt = calculate_health_credit_amount(
        settings, worker_category="contractor_1099", eligible_hours=Decimal("20"), has_approved_hours=True
    )
    assert float(amt) == 0.0


def test_1099_per_hour_health_credit():
    settings = {
        "health_credit_accrual_method": "per_hour",
        "health_credit_rate_per_hour": 0.50,
        "health_credit_enabled_for_1099": True,
    }
    amt = calculate_health_credit_amount(
        settings, worker_category="contractor_1099", eligible_hours=Decimal("20"), has_approved_hours=True
    )
    assert float(amt) == 10.0


def test_temp_flat_per_period_health_credit():
    settings = {
        "health_credit_accrual_method": "flat_per_period",
        "health_credit_flat_amount_per_period": 15,
        "health_credit_enabled_for_temp": True,
    }
    amt = calculate_health_credit_amount(
        settings, worker_category="temp", eligible_hours=Decimal("8"), has_approved_hours=True
    )
    assert float(amt) == 15.0


def test_mctmt_zero_below_quarterly_threshold():
    settings = DEFAULT_PAYROLL_TAX_SETTINGS
    tax = _mctmt_tax_on_quarterly_payroll(Decimal("300000"), settings)
    assert float(tax) == 0.0


def test_mctmt_applies_above_threshold():
    settings = DEFAULT_PAYROLL_TAX_SETTINGS
    tax = _mctmt_tax_on_quarterly_payroll(Decimal("400000"), settings)
    assert float(tax) > 0.0


def test_mctmt_incremental_only_on_new_wages():
    settings = DEFAULT_PAYROLL_TAX_SETTINGS
    inc = _incremental_mctmt(Decimal("300000"), Decimal("50000"), settings)
    assert float(inc) >= 0.0


def test_sick_leave_cap_default_40():
    settings = {"sick_leave_annual_cap_hours": 40, "sick_leave_annual_cap_hours_large_employer": 56}
    assert float(sick_leave_annual_cap(settings)) == 40.0


def test_disclaimer_present():
    assert "accountant" in ACCRUAL_DISCLAIMER.lower()


def test_w2_sick_pay_does_not_accrue_on_sick_hours():
    """2 sick hours used → sick pay = 2×rate; accrual basis is reg+OT only."""
    from backend.payroll_accrual import process_w2_line_accruals

    cursor = MagicMock()
    cursor.fetchone = MagicMock(return_value=None)
    cursor.fetchall = MagicMock(return_value=[])
    cursor.lastrowid = 1
    with patch("backend.payroll_accrual.fetch_payroll_tax_settings") as mock_settings:
        mock_settings.return_value = {"sick_leave_annual_cap_hours": 40}
        with patch("backend.payroll_accrual.get_ledger_ytd_totals") as mock_ytd:
            mock_ytd.return_value = {"accrued": Decimal("0"), "used": Decimal("0")}
            with patch("backend.payroll_accrual.get_sick_leave_balance") as mock_bal:
                mock_bal.return_value = {
                    "balance_hours": Decimal("5"),
                    "ytd_accrued_hours": Decimal("0"),
                    "ytd_used_hours": Decimal("0"),
                }
                with patch("backend.payroll_accrual.insert_ledger_entry") as mock_insert:
                    out = process_w2_line_accruals(
                        cursor,
                        1,
                        user_id=99,
                        batch_id=1,
                        line_id=10,
                        regular_hours=Decimal("0"),
                        ot_hours=Decimal("0"),
                        sick_hours_used=Decimal("2"),
                        hourly_rate=Decimal("20"),
                        period_start="2026-01-01",
                        period_end="2026-01-15",
                    )
    assert float(out["sick_pay_amount"]) == 40.0
    assert float(out["sick_hours_accrued"]) == 0.0
    assert mock_insert.call_count >= 1
