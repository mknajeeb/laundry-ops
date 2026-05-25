"""Tests for W-2 payroll tax estimation engine."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from backend.w2_payroll_tax_engine import (
    ESTIMATE_DISCLAIMER,
    _annual_tax_from_brackets,
    calculate_w2_line_taxes,
)


def test_annual_tax_from_brackets_zero():
    assert _annual_tax_from_brackets(Decimal("0"), []) == Decimal("0")


def test_calculate_incomplete_profile():
    conn = MagicMock()
    with patch("backend.w2_payroll_tax_engine.fetch_employee_tax_profile") as mock_prof:
        mock_prof.return_value = {"w4_complete": False, "missing_fields": ["filing_status"]}
        out = calculate_w2_line_taxes(conn, 1, 99, gross_pay=800.0)
    assert out["tax_calc_status"] == "profile_incomplete"
    assert "filing_status" in out["tax_calc_notes"]


def test_calculate_estimated_has_disclaimer():
    conn = MagicMock()
    profile = {
        "w4_complete": True,
        "missing_fields": [],
        "pay_periods_per_year": 26,
        "filing_status": "single_or_mfs",
        "dependents_amount": Decimal("0"),
        "other_income": Decimal("0"),
        "deductions": Decimal("0"),
        "extra_withholding": Decimal("0"),
        "exempt_federal": False,
        "exempt_fica": False,
        "exempt_state": False,
        "exempt_city": False,
        "pre_tax_deductions": Decimal("0"),
        "post_tax_deductions": Decimal("0"),
        "work_state": "NY",
        "work_city": "Queens",
        "nyc_resident": True,
    }
    with patch("backend.w2_payroll_tax_engine.fetch_employee_tax_profile", return_value=profile):
        with patch("backend.w2_payroll_tax_engine.fetch_payroll_tax_settings") as mock_set:
            mock_set.return_value = {
                "tax_year": 2026,
                "employee_social_security_rate": 0.062,
                "employer_social_security_rate": 0.062,
                "social_security_wage_base": 184500,
                "employee_medicare_rate": 0.0145,
                "employer_medicare_rate": 0.0145,
                "additional_medicare_rate": 0.009,
                "additional_medicare_threshold": 200000,
                "futa_rate": 0.006,
                "futa_wage_base": 7000,
                "ny_suta_rate": 0.025,
                "ny_suta_wage_base": 12500,
                "ny_reemployment_service_fund_rate": 0.00075,
                "nyc_mctmt_enabled": False,
                "workers_comp_rate": 0,
                "federal_standard_deduction_single": 15750,
                "federal_standard_deduction_mfj": 31500,
                "federal_standard_deduction_hoh": 23625,
                "ny_withholding_estimate_rate": 0.045,
                "nyc_resident_estimate_rate": 0.035,
                "nyc_nonresident_estimate_rate": 0.01,
            }
            with patch("backend.w2_payroll_tax_engine.get_w2_ytd_gross", return_value=Decimal("0")):
                out = calculate_w2_line_taxes(conn, 1, 99, gross_pay=1000.0)
    assert out["tax_calc_status"] == "estimated"
    assert out["net_pay"] is not None
    assert out["net_pay"] < 1000.0
    assert ESTIMATE_DISCLAIMER in out["tax_calc_notes"]
    assert out["total_employer_taxes"] is not None
