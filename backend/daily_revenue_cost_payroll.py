"""Payroll integration adapter for Daily Revenue & Cost."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from backend.daily_revenue_cost_constants import LK_PAYROLL_TOTAL, SOURCE_PAYROLL

MONEY_Q = Decimal("0.01")


def _cursor_connection(cursor_or_conn) -> Any:
    if cursor_or_conn is None:
        return None
    if callable(getattr(cursor_or_conn, "cursor", None)) and not hasattr(cursor_or_conn, "fetchone"):
        return cursor_or_conn
    parent = getattr(cursor_or_conn, "_dict_connection", None)
    if parent is not None:
        return parent
    return (
        getattr(cursor_or_conn, "connection", None)
        or getattr(cursor_or_conn, "_conn", None)
        or cursor_or_conn
    )


def _record_gross(rec: dict) -> Decimal:
    if rec.get("rate_missing"):
        return Decimal("0")
    hours = Decimal(str(rec.get("approved_hours") or 0))
    rate = Decimal(str(rec.get("hourly_rate") or 0))
    return (hours * rate).quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def build_payroll_daily_total(records: list[dict]) -> tuple[float, list[dict]]:
    """Sum approved_hours * hourly_rate for shift sessions on the entry date."""
    total = Decimal("0")
    workers: list[dict] = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        gross = _record_gross(rec)
        total += gross
        workers.append(
            {
                "shift_session_id": rec.get("id"),
                "user_id": rec.get("user_id"),
                "worker_name": rec.get("worker_name"),
                "approved_hours": rec.get("approved_hours"),
                "hourly_rate": rec.get("hourly_rate"),
                "gross": float(gross),
                "status": rec.get("status"),
                "work_date": rec.get("work_date"),
            }
        )
    return float(total.quantize(MONEY_Q, rounding=ROUND_HALF_UP)), workers


def fetch_payroll_total_suggestion(cursor_or_conn, org_id: int, entry_date: date) -> dict | None:
    """Build payroll.total suggestion from payroll time records for entry_date."""
    from backend.daily_shift_roster_payroll import list_payroll_time_records_for_date

    conn = _cursor_connection(cursor_or_conn)
    if conn is None:
        return None
    try:
        records = list_payroll_time_records_for_date(conn, int(org_id), roster_date=entry_date)
    except Exception:
        return None
    if not records:
        return None

    total, workers = build_payroll_daily_total(records)
    if total <= 0:
        return None

    session_ids = sorted(int(r["shift_session_id"]) for r in workers if r.get("shift_session_id"))
    day = entry_date.isoformat()
    source_ref = f"payroll-day:{day}"
    if session_ids:
        source_ref = f"payroll-day:{day}:sessions={','.join(str(i) for i in session_ids[:25])}"

    captured = datetime.utcnow()
    return {
        "line_key": LK_PAYROLL_TOTAL,
        "source_system": SOURCE_PAYROLL,
        "amount": total,
        "source_ref": source_ref,
        "source_captured_at": captured.isoformat(sep=" "),
        "source_payload": {
            "entry_date": day,
            "record_count": len(workers),
            "total_gross": total,
            "calculation": "sum(approved_hours * hourly_rate)",
            "records": workers,
        },
    }


def payroll_line_is_manual_override(line: dict | None) -> bool:
    return bool(line and line.get("is_manual_override"))


def payroll_line_is_imported_frozen(line: dict | None) -> bool:
    if not line:
        return False
    source = str(line.get("source_system") or "manual")
    return source != "manual" and not bool(line.get("is_manual_override"))


def should_apply_payroll_suggestion(existing_line: dict | None) -> bool:
    """True when GET may auto-fill payroll.total from the adapter."""
    if payroll_line_is_manual_override(existing_line):
        return False
    if payroll_line_is_imported_frozen(existing_line):
        return False
    if not existing_line:
        return True
    amount = float(existing_line.get("amount") or 0)
    source = str(existing_line.get("source_system") or "manual")
    if amount == 0 and source == "manual":
        return True
    return False


def suggestion_to_line_row(suggestion: dict) -> dict:
    return {
        "amount": suggestion["amount"],
        "source_system": suggestion["source_system"],
        "source_ref": suggestion.get("source_ref"),
        "source_captured_at": suggestion.get("source_captured_at"),
        "source_payload": suggestion.get("source_payload"),
        "is_manual_override": 0,
    }


def resolve_payroll_line_for_save(
    *,
    payload_amount: float,
    overrides: dict,
    existing_line: dict | None,
    suggestion: dict | None,
) -> dict:
    """Resolve amount + source metadata for payroll.total on save."""
    from backend.daily_revenue_cost_constants import SOURCE_MANUAL

    override_info = overrides.get(LK_PAYROLL_TOTAL) or {}
    is_override = bool(override_info.get("is_manual_override"))
    override_reason = override_info.get("reason")

    if payroll_line_is_manual_override(existing_line) or is_override:
        return {
            "amount": payload_amount,
            "source_system": (existing_line or {}).get("source_system") or SOURCE_PAYROLL,
            "source_ref": (existing_line or {}).get("source_ref"),
            "source_payload": (existing_line or {}).get("source_payload"),
            "source_captured_at": (existing_line or {}).get("source_captured_at"),
            "is_override": True,
            "override_reason": override_reason or (existing_line or {}).get("override_reason"),
        }

    if payroll_line_is_imported_frozen(existing_line):
        return {
            "amount": float(existing_line.get("amount") or 0),
            "source_system": existing_line.get("source_system"),
            "source_ref": existing_line.get("source_ref"),
            "source_payload": existing_line.get("source_payload"),
            "source_captured_at": existing_line.get("source_captured_at"),
            "is_override": False,
            "override_reason": None,
        }

    if suggestion and should_apply_payroll_suggestion(existing_line):
        if payload_amount == suggestion["amount"] or (not existing_line and payload_amount == suggestion["amount"]):
            return {
                "amount": suggestion["amount"],
                "source_system": suggestion["source_system"],
                "source_ref": suggestion.get("source_ref"),
                "source_payload": suggestion.get("source_payload"),
                "source_captured_at": suggestion.get("source_captured_at"),
                "is_override": False,
                "override_reason": None,
            }

    return {
        "amount": payload_amount,
        "source_system": SOURCE_MANUAL,
        "source_ref": None,
        "source_payload": None,
        "source_captured_at": None,
        "is_override": False,
        "override_reason": None,
    }
