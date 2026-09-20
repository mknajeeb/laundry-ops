"""Paid-batch correction ledger.

Reopening a paid batch unlocks the payroll calculation. It does not make the
money already paid disappear.

    remaining_due = max(corrected_net - cumulative_actual_paid, 0)
    overpayment   = max(cumulative_actual_paid - corrected_net, 0)

The ledger lives on the line settlement JSON (payment_history +
cumulative_amount_paid). It is written only when someone explicitly reopens a
paid/closed batch. Historical batches without that flag keep the previous
binary paid/unpaid totals. No backfill.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional


def money(val: Any) -> float:
    try:
        raw = val if val is not None and str(val).strip() != "" else 0
        n = Decimal(str(raw))
    except Exception:
        n = Decimal("0")
    return float(n.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def as_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        value = value.isoformat()
    text = str(value).strip()
    if not text or text.lower() == "none":
        return None
    return text[:10]


def correction_balances(corrected_net: Any, cumulative_paid: Any) -> dict[str, float]:
    net = money(corrected_net)
    paid = money(cumulative_paid)
    remaining = money(max(net - paid, 0))
    over = money(max(paid - net, 0))
    return {
        "corrected_net": net,
        "cumulative_amount_paid": paid,
        "remaining_due": remaining,
        "overpayment": over,
        "outstanding_balance": remaining,
        "amount_paid": paid,
    }


def _history_key(entry: dict) -> tuple:
    return (
        money(entry.get("amount")),
        as_date(entry.get("payment_date")) or "",
        str(entry.get("reference") or "").strip(),
        str(entry.get("kind") or ""),
    )


def sum_history(history: Any) -> float:
    total = Decimal("0")
    for entry in history or []:
        if not isinstance(entry, dict):
            continue
        total += Decimal(str(money(entry.get("amount"))))
    return money(total)


def append_payment(history: Any, entry: dict) -> list[dict]:
    out = [dict(item) for item in (history or []) if isinstance(item, dict)]
    key = _history_key(entry)
    if any(_history_key(item) == key for item in out):
        return out
    out.append(dict(entry))
    return out


def stamp_settlement(settlement: dict, corrected_net: Any) -> dict:
    """Keep the cash ledger and recompute due/overpayment from the current net."""
    settlement = dict(settlement or {})
    history = [dict(item) for item in (settlement.get("payment_history") or []) if isinstance(item, dict)]
    cumulative = settlement.get("cumulative_amount_paid")
    if cumulative is None:
        cumulative = sum_history(history) if history else settlement.get("amount_paid")
    settlement["payment_history"] = history
    settlement["correction_accounting"] = True
    settlement["preserve_amount_paid"] = True
    settlement.update(correction_balances(corrected_net, cumulative))
    return settlement


def open_correction_ledger(
    settlement: dict,
    *,
    amount_paid: Any,
    payment_date: Any = None,
    reference: Any = None,
    method: Any = None,
) -> dict:
    """Record money already paid. A second reopen must not copy it again."""
    settlement = dict(settlement or {})
    history = [dict(item) for item in (settlement.get("payment_history") or []) if isinstance(item, dict)]
    if settlement.get("correction_accounting") and history:
        summed = sum_history(history)
        cumulative = settlement.get("cumulative_amount_paid")
        if cumulative is None:
            cumulative = summed
        gap = money(money(cumulative) - summed)
        if gap > 0:
            history = append_payment(
                history,
                {
                    "amount": gap,
                    "payment_date": as_date(payment_date),
                    "reference": str(reference or "").strip(),
                    "method": str(method or "").strip(),
                    "kind": "correction",
                },
            )
        settlement["payment_history"] = history
        settlement["cumulative_amount_paid"] = sum_history(history)
    else:
        amount = money(amount_paid)
        history = []
        if amount > 0:
            history = append_payment(
                [],
                {
                    "amount": amount,
                    "payment_date": as_date(payment_date),
                    "reference": str(reference or "").strip(),
                    "method": str(method or "").strip(),
                    "kind": "original",
                },
            )
        settlement["payment_history"] = history
        settlement["cumulative_amount_paid"] = sum_history(history)
    if settlement.get("corrected_net") is None:
        outstanding = money(settlement.get("outstanding_balance") or 0)
        settlement["corrected_net"] = money(settlement["cumulative_amount_paid"] + outstanding)
    return stamp_settlement(settlement, settlement.get("corrected_net"))


def record_additional_payment(
    settlement: dict,
    *,
    payment_date: Any = None,
    reference: Any = None,
    amount: Any = None,
) -> dict:
    """Append a follow-up payment for the remaining due. Never replace history."""
    settlement = dict(settlement or {})
    history = [dict(item) for item in (settlement.get("payment_history") or []) if isinstance(item, dict)]
    cumulative = settlement.get("cumulative_amount_paid")
    if cumulative is None:
        cumulative = sum_history(history) if history else settlement.get("amount_paid")
    net = settlement.get("corrected_net")
    if net is None:
        net = cumulative
    due = correction_balances(net, cumulative)["remaining_due"]
    pay = due if amount is None else money(amount)
    if pay > 0 and due > 0:
        pay = money(min(pay, due))
        history = append_payment(
            history,
            {
                "amount": pay,
                "payment_date": as_date(payment_date),
                "reference": str(reference or "").strip(),
                "kind": "correction",
            },
        )
        cumulative = sum_history(history)
    settlement["payment_history"] = history
    settlement["cumulative_amount_paid"] = money(cumulative)
    settlement["correction_accounting"] = True
    return stamp_settlement(settlement, net)


def ledger_from_settlement(settlement: Optional[dict]) -> Optional[dict]:
    settlement = settlement or {}
    if not settlement.get("correction_accounting"):
        return None
    history = [dict(item) for item in (settlement.get("payment_history") or []) if isinstance(item, dict)]
    cumulative = settlement.get("cumulative_amount_paid")
    if cumulative is None:
        cumulative = sum_history(history)
    return {
        "correction_accounting": True,
        "payment_history": history,
        "cumulative_amount_paid": money(cumulative),
    }


def dashboard_slice(details: Optional[dict]) -> Optional[dict[str, float]]:
    """Settlement amounts for dashboard totals. None means keep binary status math."""
    settlement = (details or {}).get("settlement") or {}
    if not settlement.get("correction_accounting"):
        return None
    paid = settlement.get("cumulative_amount_paid")
    if paid is None:
        history = settlement.get("payment_history") or []
        paid = sum_history(history) if history else settlement.get("amount_paid")
    net = settlement.get("corrected_net")
    if net is None:
        net = paid
    bal = correction_balances(net, paid)
    return {
        "obligation": bal["corrected_net"],
        "paid": bal["cumulative_amount_paid"],
        "unpaid": bal["remaining_due"],
        "overpayment": bal["overpayment"],
    }


def batch_can_sync_from_time_records(batch: Optional[dict]) -> bool:
    """Refresh Hours stays limited to drafts, hours-reviewed, and explicit corrections."""
    status = str((batch or {}).get("status") or "")
    if status in ("draft", "hours_reviewed"):
        return True
    return status == "approved_for_payment" and bool((batch or {}).get("correction_reopened_at"))


def batch_reserves_coverage(batch: Optional[dict]) -> bool:
    """A batch in correction still owns its employee so the missed day cannot be paid twice.

    Paid/closed and finalized batches keep the existing effective-batch rule.
    A normal approved_for_payment batch does not start reserving coverage.
    """
    row = batch or {}
    status = str(row.get("status") or "").strip().lower()
    if status in ("paid", "closed"):
        return True
    if row.get("payout_details_finalized_at"):
        return True
    return status == "approved_for_payment" and bool(row.get("correction_reopened_at"))
