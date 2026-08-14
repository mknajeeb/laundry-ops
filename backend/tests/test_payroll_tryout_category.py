"""Try Out is a first-class payroll category, classified before Temp."""

from backend.payroll_payout_details import batch_uses_vendor_receipt
from backend.payroll_status_display import (
    batch_ready_for_payout_details,
    can_finalize_payout_details,
    compute_primary_action,
)
from backend.payroll_worker_categories import (
    classify_employment_category,
    is_vendor_receipt_category,
)


def test_classify_tryout_before_temp_substring():
    assert classify_employment_category("EC_TRYOUT", "Try Out") == "tryout"
    assert classify_employment_category("TRYOUT", "Tryout") == "tryout"
    assert classify_employment_category("EC_TEMP", "Temporary / seasonal") == "temp"


def test_tryout_is_not_w2_or_1099():
    assert classify_employment_category("EC_TRYOUT", "Try Out") not in (
        "w2",
        "contractor_1099",
        "temp",
    )


def test_tryout_uses_vendor_receipt_like_temp():
    assert is_vendor_receipt_category("tryout") is True
    assert is_vendor_receipt_category("w2") is False
    assert batch_uses_vendor_receipt({"worker_category": "tryout"}) is True
    assert batch_uses_vendor_receipt({"worker_category": "w2"}) is False


def test_tryout_skips_accountant_like_temp():
    batch = {
        "status": "hours_reviewed",
        "worker_category": "tryout",
        "total_payout_amount": 68,
    }
    assert batch_ready_for_payout_details(batch) is True
    assert can_finalize_payout_details(batch) is True
    action = compute_primary_action(batch)
    assert action["action"] == "enter_details"
