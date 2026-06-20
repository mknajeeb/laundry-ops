"""Tests for catch-up withholding vs prior balance settlement math."""

from backend.payroll_payout_details import apply_settlement_math, reconcile_tax_summary


def _details(current_tax: float, prior: float = 0, catch_up: float = 0, paid_full: bool = False):
    base = {
        "employee_deductions": {
            "fit": current_tax,
            "ss": 0,
            "medicare": 0,
            "state": 0,
            "local": 0,
            "other1": 0,
            "other2": 0,
        },
        "settlement": {
            "prior_unpaid_taxes": prior,
            "catch_up_withholding": catch_up,
            "paid_full_gross_without_withholding": paid_full,
        },
    }
    return reconcile_tax_summary(base)


def test_paid_full_gross_shows_liability_not_withheld():
    details = apply_settlement_math(_details(50.0, paid_full=True), 200.0)
    settlement = details["settlement"]
    assert settlement["amount_withheld"] == 0.0
    assert settlement["amount_paid"] == 200.0
    assert settlement["catch_up_withholding"] == 0.0
    assert settlement["tax_balance_owed"] == 50.0


def test_catch_up_default_zero_prior_visible_only():
    details = apply_settlement_math(_details(30.0, prior=100.0, catch_up=0.0), 150.0)
    settlement = details["settlement"]
    assert settlement["prior_unpaid_taxes"] == 100.0
    assert settlement["amount_withheld"] == 30.0
    assert settlement["amount_paid"] == 120.0
    assert settlement["tax_balance_owed"] == 0.0
    assert details["tax_summary"]["remaining_balance"] == 100.0


def test_partial_withheld_from_payment():
    details = apply_settlement_math(_details(16.90, prior=9.11), 221.0)
    details["settlement"]["withheld_from_payment"] = 7.89
    details = apply_settlement_math(details, 221.0)
    settlement = details["settlement"]
    assert settlement["amount_withheld"] == 7.89
    assert settlement["amount_paid"] == 213.11
    assert settlement["tax_balance_owed"] == 9.01
    assert details["tax_summary"]["remaining_balance"] == 18.12


def test_catch_up_excess_collection_floors_remaining_at_zero():
    """Catch-up + current withholding can exceed prior; remaining balance must not go negative."""
    details = apply_settlement_math(_details(16.90, prior=9.11, catch_up=17.0), 221.0)
    tax_summary = details["tax_summary"]
    assert tax_summary["total_tax_liability"] == 26.01
    assert tax_summary["current_period_taxes"] == 16.90
    assert tax_summary["remaining_balance"] == 0.0


def test_prior_period_adjustment_offsets_prior_balance():
    """Prior-period adj credits carryover prior — must not stack on top of prior_unpaid_taxes."""
    details = apply_settlement_math(_details(16.90, prior=9.11), 221.0)
    details["settlement"]["prior_period_adjustment"] = 9.11
    details = apply_settlement_math(details, 221.0)
    tax_summary = details["tax_summary"]
    assert tax_summary["total_tax_liability"] == 16.90
    assert tax_summary["remaining_balance"] == 0.0


def test_prior_period_adjustment_partial_offset():
    details = apply_settlement_math(_details(16.90, prior=9.11), 221.0)
    details["settlement"]["prior_period_adjustment"] = 4.0
    details = apply_settlement_math(details, 221.0)
    tax_summary = details["tax_summary"]
    settlement = details["settlement"]
    assert tax_summary["total_tax_liability"] == 22.01
    assert settlement["amount_withheld"] == 4.0
    assert settlement["amount_paid"] == 217.0
    assert tax_summary["remaining_balance"] == 18.01


def test_prior_period_adjustment_partial_collection_reduces_net():
    """Partial prior-period adj. is collected from pay; current period not auto-withheld."""
    details = apply_settlement_math(_details(18.21, prior=18.21), 238.0)
    details["settlement"]["prior_period_adjustment"] = 17.0
    details = apply_settlement_math(details, 238.0)
    settlement = details["settlement"]
    tax_summary = details["tax_summary"]
    assert settlement["amount_withheld"] == 17.0
    assert settlement["amount_paid"] == 221.0
    assert settlement["tax_balance_owed"] == 18.21
    assert tax_summary["remaining_balance"] == 2.42


def test_catch_up_withholding_reduces_net_pay():
    details = apply_settlement_math(_details(25.0, prior=80.0, catch_up=40.0), 200.0)
    settlement = details["settlement"]
    assert settlement["amount_withheld"] == 65.0
    assert settlement["amount_paid"] == 135.0
    assert settlement["catch_up_withholding"] == 40.0
    assert details["tax_summary"]["remaining_balance"] == 40.0
