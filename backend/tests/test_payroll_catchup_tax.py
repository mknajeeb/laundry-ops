"""Tests for minimum withholding helpers (no flat % shortcuts)."""

from backend.payroll_catchup_tax import estimate_catchup_line_details, estimate_employee_deductions


def test_employee_deductions_ss_medicare_only():
    emp = estimate_employee_deductions(500.0, "Alec Coaxum")
    assert emp["fit"] == 0.0
    assert emp["state"] == 0.0
    assert emp["local"] == 0.0
    assert emp["ss"] == round(500 * 0.062, 2)
    assert emp["medicare"] == round(500 * 0.0145, 2)


def test_estimate_catchup_full_gross_paid():
    patch = estimate_catchup_line_details(500, "Jane Doe", paid_full_gross_without_withholding=True)
    assert patch["settlement"]["amount_paid"] == 500.0
    assert patch["settlement"]["amount_withheld"] == 0.0
    assert patch["settlement"]["paid_full_gross_without_withholding"] is True
