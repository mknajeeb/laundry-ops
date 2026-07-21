"""Tests for staffing-vendor receipts that replace paystubs for temp / 1099.

These cover the pure gating/document-state logic (no DB) plus vendor snapshot
helpers. W-2 behavior must be unaffected.
"""

from unittest import mock

import backend.payroll_payout_details as ppd
from backend.payroll_payout_details import (
    batch_uses_vendor_receipt,
    can_generate_paystub_for_line,
    can_generate_vendor_receipt_for_line,
    generate_vendor_receipt_html,
    line_document_state,
    payout_workflow_state,
)
from backend.payroll_vendors import (
    resolve_line_vendor,
    vendor_snapshot_for_finalize,
)


def _batch(category, *, finalized=False, status="approved_for_payment"):
    return {
        "id": 1,
        "worker_category": category,
        "status": status,
        "payout_details_finalized_at": "2026-07-01T00:00:00" if finalized else None,
        "accountant_payment_confirmed_at": None,
        "lines": [],
    }


def test_batch_uses_vendor_receipt_by_category():
    assert batch_uses_vendor_receipt(_batch("temp")) is True
    assert batch_uses_vendor_receipt(_batch("contractor_1099")) is True
    assert batch_uses_vendor_receipt(_batch("w2")) is False


def test_temp_line_never_gets_paystub():
    batch = _batch("temp", finalized=True)
    details = {"payment": {"method": "direct_deposit"}}
    assert can_generate_paystub_for_line(batch, details) is False
    assert can_generate_vendor_receipt_for_line(batch, details) is True


def test_w2_line_still_gets_paystub_not_vendor_receipt():
    batch = _batch("w2", finalized=True)
    details = {"payment": {"method": "direct_deposit"}}
    assert can_generate_paystub_for_line(batch, details) is True
    assert can_generate_vendor_receipt_for_line(batch, details) is False


def test_vendor_receipt_preview_requires_ready_batch():
    ready = _batch("temp", status="approved_for_payment")
    not_ready = _batch("temp", status="draft")
    details = {"payment": {}}
    assert can_generate_vendor_receipt_for_line(ready, details, preview=True) is True
    assert can_generate_vendor_receipt_for_line(not_ready, details, preview=True) is False


def test_line_document_state_temp_is_vendor_receipt():
    batch = _batch("temp", finalized=True)
    line = {"id": 5, "payout_details_json": {"payment": {"method": "check"}}}
    doc = line_document_state(batch, line)
    assert doc["effective_type"] == "vendor_receipt"
    assert doc["paystub_available"] is False
    assert doc["vendor_receipt_available"] is True


def test_line_document_state_carries_vendor_snapshot():
    batch = _batch("temp", finalized=True)
    line = {
        "id": 5,
        "payout_details_json": {
            "payment": {"method": "check"},
            "vendor": {"id": 1, "name": "Washmate Inc", "address": "X", "logo_url": "/l.png"},
        },
    }
    doc = line_document_state(batch, line)
    assert doc["vendor"]["name"] == "Washmate Inc"


def test_workflow_state_flags_for_temp():
    batch = _batch("temp", finalized=True, status="approved_for_payment")
    wf = payout_workflow_state(batch)
    assert wf["uses_vendor_receipt"] is True
    assert wf["vendor_receipt_available"] is True
    assert wf["paystub_available"] is False


def test_workflow_state_w2_unaffected():
    batch = _batch("w2", finalized=True, status="approved_for_payment")
    wf = payout_workflow_state(batch)
    assert wf["uses_vendor_receipt"] is False
    assert wf["paystub_available"] is True
    assert wf["vendor_receipt_available"] is False


def test_resolve_line_vendor_none_for_w2():
    batch = _batch("w2")
    line = {"id": 1, "user_id": 9, "worker_category": "w2"}
    # No DB access should occur for W-2 — returns None immediately.
    assert resolve_line_vendor(None, 3, line, batch) is None


def test_resolve_line_vendor_uses_snapshot_without_db():
    batch = _batch("temp")
    line = {
        "id": 1,
        "user_id": 9,
        "payout_details": {
            "vendor": {"id": 2, "name": "Acme Staffing", "address": None, "logo_url": None}
        },
    }
    resolved = resolve_line_vendor(None, 3, line, batch)
    assert resolved["name"] == "Acme Staffing"
    assert resolved["snapshot"] is True


def test_vendor_snapshot_for_finalize_shape():
    vendor = {"id": 1, "name": "Washmate Inc", "address": "A", "logo_url": "/l.png", "active": True}
    snap = vendor_snapshot_for_finalize(vendor)
    assert snap == {"id": 1, "name": "Washmate Inc", "address": "A", "logo_url": "/l.png"}
    assert vendor_snapshot_for_finalize(None) is None


def test_vendor_receipt_shows_issued_from_and_service_recipient():
    """Receipt shows the vendor (from snapshot) plus the client org it was for."""
    batch = {
        "id": 22,
        "organization_id": 3,
        "worker_category": "temp",
        "payout_details_finalized_at": "2026-07-01T00:00:00",
        "pay_period_start": "2026-05-11",
        "pay_period_end": "2026-05-17",
        "official_pay_date": "2026-05-16",
        "lines": [
            {
                "id": 211,
                "user_id": 5,
                "worker_name_snapshot": "Jane Doe",
                "approved_hours": 10,
                "rate": 20,
                "adjustments": 0,
                "payout_details": {
                    "payment": {"method": "check", "date": "2026-05-16"},
                    "vendor": {
                        "id": 1,
                        "name": "Washmate Inc",
                        "address": "921 2nd Avenue, Franklin Square, NY 11010",
                        "logo_url": None,
                    },
                },
                "payout_totals": {"gross_pay": 200.0, "amount_paid": 200.0},
            }
        ],
    }
    # Finalized snapshot must be the branding source; org name is the service recipient.
    vendor_snapshot = {
        "id": 1,
        "name": "Washmate Inc",
        "address": "921 2nd Avenue, Franklin Square, NY 11010",
        "logo_url": None,
        "snapshot": True,
    }
    with mock.patch.object(ppd, "get_payout_batch_details", return_value=batch), mock.patch.object(
        ppd, "_vendor_worker_contact", return_value={"phone": "", "email": ""}
    ), mock.patch.object(
        ppd, "fetch_vendor_receipt_ytd_prior", return_value=0.0
    ), mock.patch.object(
        ppd, "_org_display_name", return_value="VeeWash"
    ), mock.patch(
        "backend.payroll_vendors.resolve_line_vendor", return_value=vendor_snapshot
    ):
        html = generate_vendor_receipt_html(object(), 3, 22, 211)

    assert "Issued from" in html
    assert "Washmate Inc" in html
    assert "Work performed for" in html
    assert "VeeWash" in html
    # Service recipient appears directly below the vendor block.
    assert html.index("Issued from") < html.index("Work performed for")
    assert html.index("Washmate Inc") < html.index("Work performed for")
