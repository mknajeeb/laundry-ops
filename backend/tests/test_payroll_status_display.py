"""Tests for user-facing payroll display status."""

from backend.payroll_status_display import (
    build_payroll_display,
    compute_display_status,
    enrich_batch_payroll_display,
)


def test_display_status_draft():
    assert compute_display_status({"status": "draft"}) == "draft"


def test_display_status_ready_for_payroll_after_approve():
    assert compute_display_status({"status": "sent_to_accountant"}) == "ready_for_payroll"
    assert compute_display_status({"status": "approved_for_payment"}) == "ready_for_payroll"


def test_display_status_ready_to_pay_when_finalized():
    batch = {"status": "approved_for_payment", "payout_details_finalized_at": "2026-01-01"}
    assert compute_display_status(batch) == "ready_to_pay"


def test_display_status_paid():
    assert compute_display_status({"status": "paid"}) == "paid"
    assert compute_display_status({"status": "closed"}) == "paid"


def test_primary_action_on_draft():
    batch = enrich_batch_payroll_display({"status": "draft", "total_payout_amount": 100})
    assert batch["payroll_display"]["primary_action"]["action"] == "approve_hours"
    assert batch["payroll_display"]["display_status_label"] == "Draft"


def test_build_payroll_display_summary():
    batch = {
        "status": "approved_for_payment",
        "summary": {
            "gross_total": 1500,
            "taxes_withheld_total": 200,
            "net_pay_total": 1300,
            "paid_amount": 0,
            "unpaid_amount": 1300,
        },
        "worker_count": 3,
    }
    display = build_payroll_display(batch)
    summary = display["payroll_summary"]
    assert summary["employee_count"] == 3
    assert summary["gross_payroll"] == 1500
    assert summary["tax_withheld"] == 200
    assert summary["net_payroll"] == 1300


def test_money_summary_does_not_equate_net_to_gross_when_lines_have_withholding():
    """Stale/missing summary must not hide employee withholding on the headline."""
    from backend.payroll_status_display import _money_summary

    batch = {
        "worker_category": "w2",
        "summary": {
            "gross_total": 3277.86,
            "taxes_withheld_total": None,
            "net_pay_total": None,
            "paid_amount": 0,
            "unpaid_amount": 0,
        },
        "lines": [
            {"tax_withheld": 146.78, "net_paid": 554.64, "gross_amount": 701.42},
            {"tax_withheld": 209.72, "net_paid": 704.12, "gross_amount": 913.84},
            {"tax_withheld": 178.96, "net_paid": 631.09, "gross_amount": 810.05},
            {"tax_withheld": 35.74, "net_paid": 264.31, "gross_amount": 300.05},
            {"tax_withheld": 78.33, "net_paid": 474.17, "gross_amount": 552.50},
        ],
        "worker_count": 5,
    }
    summary = _money_summary(batch)
    assert summary["gross_payroll"] == 3277.86
    assert summary["tax_withheld"] == 649.53
    assert summary["net_payroll"] == 2628.33
    assert abs(summary["gross_payroll"] - summary["tax_withheld"] - summary["net_payroll"]) < 0.02


def test_money_summary_net_equals_gross_when_no_line_withholding():
    from backend.payroll_status_display import _money_summary

    batch = {
        "summary": {
            "gross_total": 2730.29,
            "taxes_withheld_total": None,
            "net_pay_total": None,
        },
        "lines": [
            {"gross_amount": 741.2, "tax_withheld": None, "net_paid": None},
        ],
    }
    summary = _money_summary(batch)
    assert summary["tax_withheld"] is None
    assert summary["net_payroll"] == 2730.29
