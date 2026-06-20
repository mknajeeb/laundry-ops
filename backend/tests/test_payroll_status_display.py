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
