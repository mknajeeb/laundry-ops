"""Deprecated flat-rate catch-up helpers — use w2_payroll_tax_engine minimum withholding instead."""

from __future__ import annotations

from typing import Any

_SS_RATE = 0.062
_MEDICARE_RATE = 0.0145
_ER_SS_RATE = 0.062
_ER_MEDICARE_RATE = 0.0145
_FUTA_RATE = 0.006
_SUI_RATE = 0.03
_MCTMT_RATE = 0.0011


def _round2(val: float) -> float:
    return round(float(val), 2)


def estimate_employee_deductions(gross: float, worker_name: str = "") -> dict[str, float]:
    """SS + Medicare only — no flat FIT/state/local shortcuts."""
    gross_f = float(gross or 0)
    if gross_f <= 0:
        return {k: 0.0 for k in ("fit", "ss", "medicare", "state", "local", "other1", "other2")}
    return {
        "fit": 0.0,
        "ss": _round2(gross_f * _SS_RATE),
        "medicare": _round2(gross_f * _MEDICARE_RATE),
        "state": 0.0,
        "local": 0.0,
        "other1": 0.0,
        "other2": 0.0,
    }


def estimate_employer_taxes(gross: float) -> dict[str, float]:
    gross_f = float(gross or 0)
    if gross_f <= 0:
        return {k: 0.0 for k in ("er_ss", "er_medicare", "futa", "suta", "other")}

    er_ss = _round2(gross_f * _ER_SS_RATE)
    er_medicare = _round2(gross_f * _ER_MEDICARE_RATE)
    futa = _round2(gross_f * _FUTA_RATE)
    suta = _round2(gross_f * _SUI_RATE)
    mctmt = _round2(gross_f * _MCTMT_RATE)
    return {
        "er_ss": er_ss,
        "er_medicare": er_medicare,
        "futa": futa,
        "suta": suta,
        "other": mctmt,
    }


def estimate_catchup_line_details(
    gross: float,
    worker_name: str,
    *,
    paid_full_gross_without_withholding: bool = True,
    prior_unpaid_taxes: float = 0.0,
    amount_withheld: float = 0.0,
    amount_paid: float | None = None,
) -> dict[str, Any]:
    """Build payout_details patch (minimum SS/Medicare only — use backfill script for table estimates)."""
    gross_f = float(gross or 0)
    emp = estimate_employee_deductions(gross_f, worker_name)
    er = estimate_employer_taxes(gross_f)
    paid = float(amount_paid if amount_paid is not None else gross_f)
    withheld = float(amount_withheld or 0)
    prior = float(prior_unpaid_taxes or 0)
    current_liability = _round2(sum(emp.values()))
    tax_balance = _round2(current_liability - withheld)

    return {
        "employee_deductions": emp,
        "employer_taxes": er,
        "payment": {
            "method": "cash",
            "date": None,
            "cash_amount": paid if paid_full_gross_without_withholding else None,
        },
        "settlement": {
            "amount_paid": paid,
            "amount_withheld": withheld,
            "outstanding_balance": 0.0,
            "prior_unpaid_taxes": prior,
            "prior_period_adjustment": 0.0,
            "catch_up_withholding": 0.0,
            "paid_full_gross_without_withholding": paid_full_gross_without_withholding,
            "tax_balance_owed": tax_balance,
        },
        "tax_summary": {
            "estimated": True,
            "minimum_withholding": True,
            "current_period_taxes": current_liability,
            "prior_tax_balance": prior,
            "total_tax_liability": _round2(current_liability + prior),
            "actual_tax_withheld": withheld,
            "tax_balance_owed": tax_balance,
            "remaining_balance": _round2(current_liability + prior - withheld),
        },
    }
