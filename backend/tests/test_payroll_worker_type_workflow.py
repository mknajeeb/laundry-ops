"""Worker-type payroll workflow primary actions."""

from backend.payroll_status_display import (
    batch_ready_for_payout_details,
    can_finalize_payout_details,
    compute_primary_action,
    enrich_batch_payroll_display,
)


def test_w2_primary_send_to_accountant_after_approve():
    batch = enrich_batch_payroll_display(
        {
            "status": "hours_reviewed",
            "worker_category": "w2",
            "total_payout_amount": 500,
        }
    )
    action = batch["payroll_display"]["primary_action"]
    assert action["action"] == "send_to_accountant"
    assert action["label"] == "Send to Accountant"


def test_w2_primary_awaiting_accountant_when_sent():
    batch = enrich_batch_payroll_display(
        {
            "status": "sent_to_accountant",
            "worker_category": "w2",
            "total_payout_amount": 500,
        }
    )
    action = batch["payroll_display"]["primary_action"]
    assert action["action"] == "await_accountant"
    assert action.get("disabled") is True


def test_w2_primary_enter_details_after_accountant():
    batch = enrich_batch_payroll_display(
        {
            "status": "approved_for_payment",
            "worker_category": "w2",
            "total_payout_amount": 500,
        }
    )
    action = batch["payroll_display"]["primary_action"]
    assert action["action"] == "enter_details"


def test_temp_primary_enter_details_after_approve():
    batch = enrich_batch_payroll_display(
        {
            "status": "hours_reviewed",
            "worker_category": "temp",
            "total_payout_amount": 300,
        }
    )
    action = batch["payroll_display"]["primary_action"]
    assert action["action"] == "enter_details"


def test_contractor_primary_enter_details_after_approve():
    batch = enrich_batch_payroll_display(
        {
            "status": "hours_reviewed",
            "worker_category": "contractor_1099",
            "total_payout_amount": 400,
        }
    )
    action = batch["payroll_display"]["primary_action"]
    assert action["action"] == "enter_details"
    assert action["label"] == "Enter Payment Record"


def test_batch_ready_w2_requires_accountant():
    assert not batch_ready_for_payout_details(
        {"status": "hours_reviewed", "worker_category": "w2"}
    )
    assert batch_ready_for_payout_details(
        {"status": "approved_for_payment", "worker_category": "w2"}
    )


def test_batch_ready_temp_after_hours_reviewed():
    assert batch_ready_for_payout_details(
        {"status": "hours_reviewed", "worker_category": "temp"}
    )


def test_finalize_w2_requires_accountant():
    assert not can_finalize_payout_details(
        {"status": "hours_reviewed", "worker_category": "w2"}
    )
    assert can_finalize_payout_details(
        {"status": "approved_for_payment", "worker_category": "w2"}
    )
    assert can_finalize_payout_details(
        {"status": "hours_reviewed", "worker_category": "temp"}
    )
