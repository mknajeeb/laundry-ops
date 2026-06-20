"""User-facing payroll status — one workflow label for managers, accountants, and employees."""

from __future__ import annotations

from typing import Any, Optional

from backend.ta_helpers import json_safe

DISPLAY_STATUSES = ("draft", "ready_for_payroll", "ready_to_pay", "paid")

DISPLAY_STATUS_LABELS = {
    "draft": "Draft",
    "ready_for_payroll": "Ready For Payroll",
    "ready_to_pay": "Ready To Pay",
    "paid": "Paid",
}

PRIMARY_ACTIONS = {
    "draft": {"action": "approve_hours", "label": "Approve Hours"},
    "ready_for_payroll": {"action": "enter_details", "label": "Enter Payroll Details"},
    "ready_to_pay": {"action": "mark_paid", "label": "Mark Paid"},
    "paid": {"action": "view_documents", "label": "View Documents"},
}

DISPLAY_STATUS_COLORS = {
    "draft": "default",
    "ready_for_payroll": "info",
    "ready_to_pay": "warning",
    "paid": "success",
}

PAID_INTERNAL_STATUSES = frozenset({"paid", "closed"})
READY_FOR_PAYROLL_INTERNAL = frozenset(
    {
        "hours_reviewed",
        "sent_to_accountant",
        "accountant_reviewed",
        "approved_for_payment",
    }
)


def compute_display_status(batch: dict) -> str:
    st = str(batch.get("status") or "draft")
    if st in PAID_INTERNAL_STATUSES:
        return "paid"
    finalized = bool(batch.get("payout_details_finalized_at"))
    if finalized:
        return "ready_to_pay"
    if st == "draft":
        return "draft"
    if st in READY_FOR_PAYROLL_INTERNAL:
        return "ready_for_payroll"
    return "draft"


def _skips_accountant_review(batch: dict) -> bool:
    cat = str(batch.get("worker_category") or "w2")
    return cat in ("temp", "contractor_1099")


def compute_primary_action(batch: dict) -> dict[str, str]:
    """Worker-type-aware primary CTA — simple labels only in UI."""
    ds = compute_display_status(batch)
    st = str(batch.get("status") or "draft")
    skips_accountant = _skips_accountant_review(batch)

    if ds == "draft":
        return {"action": "approve_hours", "label": "Approve Hours"}
    if ds == "ready_for_payroll":
        if not skips_accountant:
            if st == "hours_reviewed":
                return {"action": "send_to_accountant", "label": "Send to Accountant"}
            if st in ("sent_to_accountant", "accountant_reviewed"):
                return {
                    "action": "await_accountant",
                    "label": "Awaiting Accountant",
                    "disabled": True,
                }
            return {"action": "enter_details", "label": "Enter Payroll Details"}
        cat = str(batch.get("worker_category") or "")
        if cat == "contractor_1099":
            return {"action": "enter_details", "label": "Enter Payment Record"}
        if cat == "temp":
            return {"action": "enter_details", "label": "Enter Deductions & Payment"}
        return {"action": "enter_details", "label": "Enter Payroll Details"}
    if ds == "ready_to_pay":
        return {"action": "mark_paid", "label": "Mark Paid"}
    if ds == "paid":
        return {"action": "view_documents", "label": "View Documents"}
    return dict(PRIMARY_ACTIONS["draft"])


def batch_ready_for_payout_details(batch: dict) -> bool:
    """Whether payment/deduction details can be entered (varies by worker type)."""
    st = str(batch.get("status") or "")
    if _skips_accountant_review(batch):
        return st in (
            "hours_reviewed",
            "approved_for_payment",
            "paid",
            "closed",
        )
    return st in ("approved_for_payment", "paid", "closed")


def can_finalize_payout_details(batch: dict) -> bool:
    """W-2 requires accountant processing before paystubs are finalized."""
    if not batch_ready_for_payout_details(batch):
        return False
    if str(batch.get("worker_category") or "") == "w2":
        return str(batch.get("status") or "") in (
            "approved_for_payment",
            "paid",
            "closed",
        )
    return True


def _money_summary(batch: dict) -> dict[str, Any]:
    summary = batch.get("summary") or {}
    gross = summary.get("gross_total") or batch.get("total_payout_amount") or 0
    paid = summary.get("paid_amount") or 0
    unpaid = summary.get("unpaid_amount") or 0
    taxes = summary.get("taxes_withheld_total")
    net = summary.get("net_pay_total")
    if net is None and taxes is not None:
        try:
            net = float(gross) - float(taxes)
        except (TypeError, ValueError):
            net = None
    if net is None and not taxes:
        net = gross
    worker_count = batch.get("worker_count")
    if worker_count is None:
        worker_count = len(batch.get("lines") or [])
    return {
        "employee_count": int(worker_count or 0),
        "gross_payroll": float(gross or 0),
        "tax_withheld": float(taxes) if taxes is not None else None,
        "net_payroll": float(net) if net is not None else None,
        "paid_amount": float(paid or 0),
        "outstanding_amount": float(unpaid or 0),
    }


def build_payroll_display(batch: dict) -> dict[str, Any]:
    display_status = compute_display_status(batch)
    primary = compute_primary_action(batch)
    return json_safe(
        {
            "display_status": display_status,
            "display_status_label": DISPLAY_STATUS_LABELS.get(display_status, "Draft"),
            "display_status_color": DISPLAY_STATUS_COLORS.get(display_status, "default"),
            "primary_action": primary,
            "payroll_summary": _money_summary(batch),
            "pay_period_start": batch.get("pay_period_start"),
            "pay_period_end": batch.get("pay_period_end"),
            "worker_category": batch.get("worker_category"),
            "skips_accountant_review": _skips_accountant_review(batch),
        }
    )


def enrich_batch_payroll_display(batch: dict) -> dict:
    batch["payroll_display"] = build_payroll_display(batch)
    return batch


def enrich_list_item_payroll_display(batch: dict) -> dict:
    """Light enrichment for batch list rows (no line-level summary)."""
    display_status = compute_display_status(batch)
    primary = compute_primary_action(batch)
    gross = float(batch.get("total_payout_amount") or 0)
    worker_count = batch.get("worker_count")
    batch["payroll_display"] = json_safe(
        {
            "display_status": display_status,
            "display_status_label": DISPLAY_STATUS_LABELS.get(display_status, "Draft"),
            "display_status_color": DISPLAY_STATUS_COLORS.get(display_status, "default"),
            "primary_action": primary,
            "payroll_summary": {
                "employee_count": int(worker_count or 0),
                "gross_payroll": gross,
                "tax_withheld": None,
                "net_payroll": None,
                "paid_amount": None,
                "outstanding_amount": None,
            },
            "pay_period_start": batch.get("pay_period_start"),
            "pay_period_end": batch.get("pay_period_end"),
            "worker_category": batch.get("worker_category"),
            "skips_accountant_review": _skips_accountant_review(batch),
        }
    )
    return batch
