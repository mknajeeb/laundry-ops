"""Tests for payroll catch-up tax estimates."""

from backend.payroll_catchup_tax import (
    employee_total_tax_rate,
    estimate_catchup_line_details,
    estimate_employee_deductions,
    estimate_employer_taxes,
)


def test_employee_rate_exceptions():
    assert employee_total_tax_rate("Alec Coaxum") == 0.09
    assert employee_total_tax_rate("Paola Almiron") == 0.14
    assert employee_total_tax_rate("Jane Doe") == 0.12


def test_estimate_employee_deductions_splits_components():
    emp = estimate_employee_deductions(500, "Jane Doe")
    total = sum(emp.values())
    assert total == round(500 * 0.12, 2)
    assert emp["ss"] == round(500 * 0.062, 2)
    assert emp["medicare"] == round(500 * 0.0145, 2)


def test_estimate_catchup_full_gross_paid():
    patch = estimate_catchup_line_details(500, "Jane Doe", paid_full_gross_without_withholding=True)
    assert patch["settlement"]["amount_paid"] == 500
    assert patch["settlement"]["amount_withheld"] == 0
    assert patch["settlement"]["paid_full_gross_without_withholding"] is True
    assert patch["tax_summary"]["tax_balance_owed"] == patch["tax_summary"]["current_period_taxes"]


def test_estimate_employer_taxes():
    er = estimate_employer_taxes(1000)
    assert er["er_ss"] == 62.0
    assert er["er_medicare"] == 14.5
