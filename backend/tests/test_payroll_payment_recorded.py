"""Paid vs UNPAID payment_recorded — unpaid must not count as money paid."""

from backend.payroll_payout_details import finalize_blockers
from backend.payroll_report import build_report_row
from backend.payroll_worker_categories import (
    is_payment_recorded_paid,
    is_payment_recorded_unpaid,
    line_payment_recorded,
)


def test_explicit_unpaid_wins_over_paid_batch():
    line = {"payment_status": "paid"}
    details = {"settlement": {"payment_recorded": "unpaid", "amount_paid": 68}}
    batch = {"status": "paid"}
    assert line_payment_recorded(line, details, batch) == "unpaid"
    assert is_payment_recorded_unpaid(line, details, batch) is True
    assert is_payment_recorded_paid(line, details, batch) is False


def test_legacy_paid_batch_without_flag_stays_paid():
    line = {"payment_status": "pending"}
    details = {"settlement": {"amount_paid": 68}}
    batch = {"status": "paid"}
    assert line_payment_recorded(line, details, batch) == "paid"
    assert is_payment_recorded_unpaid(line, details, batch) is False


def test_monthly_paid_excludes_unpaid_amount():
    batch = {
        "id": 1,
        "batch_name": "W2-2026-099",
        "worker_category": "w2",
        "pay_period_start": "2026-07-27",
        "pay_period_end": "2026-08-02",
        "status": "paid",
        "official_pay_date": "2026-08-02",
        "payout_details_finalized_at": "2026-08-02",
    }
    line = {
        "id": 10,
        "user_id": 5,
        "worker_name_snapshot": "Test Worker",
        "approved_hours": 8,
        "ot_hours": 0,
        "rate": 17,
        "gross_amount": 68,
        "payment_status": "unpaid",
        "payout_details_json": {
            "settlement": {
                "payment_recorded": "unpaid",
                "amount_paid": 68,
                "amount_withheld": 0,
            }
        },
    }
    row = build_report_row(batch, line, report_type="monthly_paid")
    assert row["payment_status_key"] == "unpaid"
    assert row["amount_paid"] == 0
    assert row["gross_pay"] == 68


def test_monthly_paid_includes_explicit_paid():
    batch = {
        "id": 2,
        "batch_name": "TEMP-2026-099",
        "worker_category": "temp",
        "pay_period_start": "2026-07-27",
        "pay_period_end": "2026-08-02",
        "status": "paid",
        "official_pay_date": "2026-08-02",
        "payout_details_finalized_at": "2026-08-02",
    }
    line = {
        "id": 11,
        "user_id": 6,
        "worker_name_snapshot": "Paid Temp",
        "approved_hours": 8,
        "rate": 17,
        "gross_amount": 68,
        "payment_status": "paid",
        "payout_details_json": {
            "settlement": {
                "payment_recorded": "paid",
                "amount_paid": 68,
                "amount_withheld": 0,
                "paid_full_gross_without_withholding": True,
            }
        },
    }
    row = build_report_row(batch, line, report_type="monthly_paid")
    assert row["payment_status_key"] == "paid"
    assert row["amount_paid"] == 68


def test_unpaid_skips_amount_paid_finalize_blocker():
    batch = {
        "worker_category": "w2",
        "status": "approved_for_payment",
        "payout_details_finalized_at": None,
        "document_mode": "payment_receipt",
    }
    lines = [
        {
            "id": 1,
            "worker_name_snapshot": "Nely",
            "payout_details": {
                "payment": {"method": "cash", "date": "2026-08-02"},
                "settlement": {"payment_recorded": "unpaid", "amount_paid": 0},
            },
        }
    ]
    blockers = finalize_blockers(batch, lines)
    assert not any("Amount paid required" in b for b in blockers)


def test_vendor_required_for_tryout_not_w2():
    tryout_batch = {
        "worker_category": "tryout",
        "status": "hours_reviewed",
        "payout_details_finalized_at": None,
    }
    w2_batch = {
        "worker_category": "w2",
        "status": "approved_for_payment",
        "payout_details_finalized_at": None,
    }
    line = {
        "id": 1,
        "worker_name_snapshot": "Nely",
        "payout_details": {
            "payment": {"method": "cash", "date": "2026-08-02"},
            "settlement": {"payment_recorded": "paid", "amount_paid": 68},
        },
    }
    tryout_blockers = finalize_blockers(tryout_batch, [line])
    assert any("Vendor is required" in b for b in tryout_blockers)
    w2_blockers = finalize_blockers(w2_batch, [line])
    assert not any("Vendor" in b for b in w2_blockers)
