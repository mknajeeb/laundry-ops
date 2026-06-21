"""Pre-deploy checks: unified payroll status, mounted UI labels, workflow lifecycle."""

from __future__ import annotations

import re
from pathlib import Path

from backend.payroll_payout_details import batch_ready_for_payout_details, compute_line_totals
from backend.payroll_status_display import (
    build_payroll_display,
    compute_display_status,
    enrich_batch_payroll_display,
)

ROOT = Path(__file__).resolve().parents[2]

MOUNTED_PAYROLL_UI = [
    "frontend/src/pages/PayrollManagementPage.jsx",
    "frontend/src/components/PayrollDashboard.jsx",
    "frontend/src/components/PayrollBatchSummaryCard.jsx",
    "frontend/src/components/PayoutBatchesPanel.jsx",
    "frontend/src/components/PayoutDetailsPanel.jsx",
    "frontend/src/components/AccountantPayrollPanel.jsx",
    "frontend/src/components/AccountantReportsPanel.jsx",
    "frontend/src/components/AccountantW2DocumentsPanel.jsx",
    "frontend/src/payroll/payrollBatchStatus.js",
    "frontend/src/payroll/payPeriodOptions.js",
    "frontend/src/components/PayPeriodSelect.jsx",
]

FORBIDDEN_UI_LABELS = [
    "sent to accountant",
    "accountant reviewed",
    "approved for payment",
    "ready to send",
    "approved unpaid",
    "approved — unpaid",
    "hours reviewed",
]

LEGACY_PANEL_IMPORTS = [
    "AccountantPaymentQueuePanel",
]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_accountant_reports_mounted_for_admin_payroll():
    mgmt = _read("frontend/src/pages/PayrollManagementPage.jsx")
    assert "AccountantReportsPanel" in mgmt
    assert 'key: "accountant_reports"' in mgmt
    assert 'key: "accountant_documents"' not in mgmt
    section_block = mgmt.split("const sections = useMemo")[1].split("}, [")[0]
    admin_block = section_block.split("if (readOnlyAccountant)")[1].split("return out;")[1]
    batches_idx = admin_block.index('key: "batches"')
    accountant_idx = admin_block.index('key: "accountant_payroll"')
    details_idx = admin_block.index('key: "payout_details"')
    assert batches_idx < accountant_idx < details_idx


def test_legacy_accountant_queue_not_imported():
    mgmt = _read("frontend/src/pages/PayrollManagementPage.jsx")
    for name in LEGACY_PANEL_IMPORTS:
        assert name not in mgmt, f"{name} still imported in PayrollManagementPage"
    assert "AccountantPayrollPanel" in mgmt


def test_mounted_payroll_ui_has_no_legacy_status_labels():
    for rel in MOUNTED_PAYROLL_UI:
        text = _read(rel).lower()
        for bad in FORBIDDEN_UI_LABELS:
            assert bad not in text, f"{bad!r} found in {rel}"


def test_display_status_lifecycle_draft_to_paid():
    assert compute_display_status({"status": "draft"}) == "draft"
    assert compute_display_status({"status": "hours_reviewed"}) == "ready_for_payroll"
    assert compute_display_status({"status": "sent_to_accountant"}) == "ready_for_payroll"
    assert compute_display_status({"status": "approved_for_payment"}) == "ready_for_payroll"
    assert compute_display_status(
        {"status": "approved_for_payment", "payout_details_finalized_at": "2026-06-20"}
    ) == "ready_to_pay"
    assert compute_display_status({"status": "paid"}) == "paid"
    assert compute_display_status({"status": "closed"}) == "paid"


def test_payout_details_unlock_after_hours_approved():
    assert batch_ready_for_payout_details(
        {"status": "hours_reviewed", "worker_category": "temp"}
    )
    assert batch_ready_for_payout_details(
        {"status": "hours_reviewed", "worker_category": "contractor_1099"}
    )
    assert not batch_ready_for_payout_details(
        {"status": "hours_reviewed", "worker_category": "w2"}
    )
    assert not batch_ready_for_payout_details(
        {"status": "sent_to_accountant", "worker_category": "w2"}
    )
    assert batch_ready_for_payout_details(
        {"status": "approved_for_payment", "worker_category": "w2"}
    )
    assert not batch_ready_for_payout_details({"status": "draft", "worker_category": "w2"})


def test_finalize_net_pay_from_deductions():
    line = {"gross_amount": 1500.0, "total_amount": 1500.0}
    details = {
        "employee_deductions": {
            "fit": 200.0,
            "ss": 93.0,
            "medicare": 21.75,
            "state": 50.0,
            "local": 0,
            "other1": 0,
            "other2": 0,
        },
        "employer_taxes": {},
        "payment": {},
        "settlement": {},
    }
    totals = compute_line_totals(line, details)
    assert totals["total_employee_deductions"] == 364.75
    assert totals["net_pay"] == 1135.25


def test_paid_batch_display_and_summary():
    batch = enrich_batch_payroll_display(
        {
            "status": "paid",
            "total_payout_amount": 2000,
            "worker_count": 4,
            "payout_details_finalized_at": "2026-06-20",
            "summary": {
                "gross_total": 2000,
                "taxes_withheld_total": 400,
                "net_pay_total": 1600,
                "paid_amount": 1600,
                "unpaid_amount": 0,
            },
        }
    )
    pd = batch["payroll_display"]
    assert pd["display_status"] == "paid"
    assert pd["display_status_label"] == "Paid"
    assert pd["primary_action"]["action"] == "view_documents"
    assert pd["payroll_summary"]["paid_amount"] == 1600
    assert pd["payroll_summary"]["outstanding_amount"] == 0


def test_read_only_accountant_lands_on_single_tab():
    page = _read("frontend/src/pages/PayrollManagementPage.jsx")
    assert "readOnlyAccountant" in page
    assert 'key: "accountant_payroll"' in page
    assert "AccountantPayrollPanel" in page
    assert re.search(
        r"readOnlyAccountant.*accountant_payroll|accountant_payroll.*readOnlyAccountant",
        page,
        re.DOTALL,
    )
