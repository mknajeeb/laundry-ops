"""Payout details, accountant payment confirmation, paystub generation."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from backend.payroll_operations import _money, get_payout_batch
from backend.ta_helpers import invalidate_schema_cache, json_safe, table_has_column

EMPLOYEE_DEDUCTION_KEYS = (
    "fit",
    "ss",
    "medicare",
    "state",
    "local",
    "other1",
    "other2",
)
PAYSTUB_DEDUCTION_LINES = (
    ("fit", "Federal Income Tax"),
    ("ss", "Social Security"),
    ("medicare", "Medicare"),
    ("state", "NY State Tax"),
    ("local", "NYC Local Tax"),
)
PAYSTUB_EMPLOYER_TAX_LINES = (
    ("er_ss", "Employer Social Security"),
    ("er_medicare", "Employer Medicare"),
    ("futa", "FUTA"),
    ("suta", "NY SUI"),
    ("other", "MCTMT"),
)
EMPLOYER_TAX_KEYS = ("er_ss", "er_medicare", "futa", "suta", "other")
PAYMENT_METHODS = ("direct_deposit", "check", "cash", "zelle", "other")
DOCUMENT_MODES = ("payment_receipt", "official_paystub")
DEFAULT_DOCUMENT_MODE = "official_paystub"

PAYMENT_METHOD_LABELS = {
    "direct_deposit": "Direct Deposit",
    "check": "Check",
    "cash": "Cash",
    "zelle": "Zelle",
    "other": "Other",
}

ADMIN_OFFICER_ROLES = frozenset(
    {
        "ADMIN",
        "PAYROLL_ADMIN",
        "SUPER_ADMIN",
        "PLATFORM_ADMIN",
        "OPS",
        "OPERATIONS",
        "SUPERVISOR",
        "FINANCE",
    }
)
VIEW_FINALIZED_ROLES = frozenset(
    {"ADMIN", "PAYROLL_ADMIN", "OPS", "OPERATIONS", "SUPERVISOR", "FINANCE", "ACCOUNTANT"}
)

ACCOUNTANT_QUEUE_STATUSES = frozenset({"approved_for_payment", "paid", "closed"})

PAYOUT_DETAILS_EDIT_STATUSES = frozenset(
    {
        "hours_reviewed",
        "sent_to_accountant",
        "accountant_reviewed",
        "approved_for_payment",
        "paid",
        "closed",
    }
)


def ensure_payout_details_columns(cursor) -> None:
    from backend.payroll_operations import ensure_payout_batches_tables

    ensure_payout_batches_tables(cursor)
    batch_cols = [
        ("accountant_payment_confirmed_at", "DATETIME NULL"),
        ("accountant_payment_confirmed_by", "INT NULL"),
        ("payout_details_finalized_at", "DATETIME NULL"),
        ("payout_details_finalized_by", "INT NULL"),
        ("payout_details_audit_json", "JSON NULL"),
        ("document_mode", "VARCHAR(32) NULL"),
        ("batch_note", "TEXT NULL"),
    ]
    for col, typedef in batch_cols:
        if not table_has_column(cursor, "payout_batches", col):
            try:
                cursor.execute(
                    f"ALTER TABLE payout_batches ADD COLUMN {col} {typedef}"
                )
            except Exception as exc:
                if getattr(exc, "args", (None,))[0] != 1060:
                    raise
            invalidate_schema_cache()
    if not table_has_column(cursor, "payout_batch_lines", "payout_details_json"):
        try:
            cursor.execute(
                "ALTER TABLE payout_batch_lines ADD COLUMN payout_details_json JSON NULL"
            )
        except Exception as exc:
            if getattr(exc, "args", (None,))[0] != 1060:
                raise
        invalidate_schema_cache()


def user_role_codes(conn, user_id: int) -> set[str]:
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT r.code FROM user_roles ur
        JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id = %s
        """,
        (int(user_id),),
    )
    return {str(row["code"]).upper() for row in c.fetchall() or []}


ACCOUNTANT_QUEUE_VIEW_ROLES = frozenset(
    {"ACCOUNTANT", "ADMIN", "PAYROLL_ADMIN", "SUPER_ADMIN", "PLATFORM_ADMIN"}
)

ACCOUNTANT_BATCH_ADMIN_ROLES = frozenset(
    {
        "ADMIN",
        "PAYROLL_ADMIN",
        "SUPER_ADMIN",
        "PLATFORM_ADMIN",
        "OPS",
        "OPERATIONS",
        "SUPERVISOR",
        "FINANCE",
    }
)


def can_view_accountant_queue(conn, user_id: int) -> bool:
    from backend.ta_routes import user_has_perm

    codes = user_role_codes(conn, user_id)
    if codes & (ACCOUNTANT_QUEUE_VIEW_ROLES - {"ACCOUNTANT"}):
        return True
    if "ACCOUNTANT" in codes:
        return user_has_perm(conn, user_id, "users.view")
    return False


def can_confirm_accountant_payment(conn, user_id: int) -> bool:
    from backend.ta_routes import user_has_perm

    codes = user_role_codes(conn, user_id)
    if "ACCOUNTANT" in codes:
        return user_has_perm(conn, user_id, "users.view")
    return False


def is_accountant_batch_list_view(conn, user_id: int) -> bool:
    """External accountants see only batches sent to them or already processed."""
    codes = user_role_codes(conn, user_id)
    if "ACCOUNTANT" not in codes:
        return False
    return not codes & ACCOUNTANT_BATCH_ADMIN_ROLES


def can_process_accountant_batch(conn, user_id: int) -> bool:
    from backend.ta_routes import user_has_perm

    codes = user_role_codes(conn, user_id)
    if "ACCOUNTANT" not in codes:
        return False
    return user_has_perm(conn, user_id, "users.view")


def can_edit_payout_details(conn, user_id: int) -> bool:
    from backend.ta_routes import user_has_perm

    codes = user_role_codes(conn, user_id)
    if codes & ADMIN_OFFICER_ROLES:
        return True
    return (
        user_has_perm(conn, user_id, "ta.settings")
        or user_has_perm(conn, user_id, "users.edit")
    )


def can_view_paystub(conn, user_id: int, batch: dict, *, preview: bool = False) -> bool:
    from backend.ta_routes import user_has_perm

    if batch.get("payout_details_finalized_at"):
        codes = user_role_codes(conn, user_id)
        if codes & VIEW_FINALIZED_ROLES:
            return True
        return user_has_perm(conn, user_id, "users.view")
    if not preview:
        return False
    if not batch_ready_for_payout_details(batch):
        return False
    codes = user_role_codes(conn, user_id)
    if codes & VIEW_FINALIZED_ROLES:
        return True
    return (
        user_has_perm(conn, user_id, "ta.settings")
        or user_has_perm(conn, user_id, "users.edit")
        or user_has_perm(conn, user_id, "users.view")
    )


def can_view_finalized_paystub(conn, user_id: int, batch: dict) -> bool:
    return can_view_paystub(conn, user_id, batch, preview=False)


def _empty_details() -> dict[str, Any]:
    return {
        "employee_deductions": {k: 0.0 for k in EMPLOYEE_DEDUCTION_KEYS},
        "employer_taxes": {k: 0.0 for k in EMPLOYER_TAX_KEYS},
        "payment": {
            "date": None,
            "method": "direct_deposit",
            "check_number": "",
            "reference": "",
            "notes": "",
            "cash_amount": None,
            "paid_by": "",
            "receipt_number": "",
            "employee_signature": "",
        },
        "settlement": {
            "amount_paid": 0.0,
            "amount_withheld": 0.0,
            "outstanding_balance": 0.0,
            "prior_unpaid_taxes": 0.0,
            "prior_period_adjustment": 0.0,
            "catch_up_withholding": 0.0,
            "paid_full_gross_without_withholding": False,
            "tax_balance_owed": 0.0,
        },
        "tax_summary": {
            "estimated": False,
            "current_period_taxes": 0.0,
            "prior_tax_balance": 0.0,
            "total_tax_liability": 0.0,
            "actual_tax_withheld": 0.0,
            "tax_balance_owed": 0.0,
            "remaining_balance": 0.0,
            "tax_catch_up_adjustment": 0.0,
        },
        "use_payment_receipt": False,
        "employee_note": "",
    }


def _parse_json_blob(val: Any) -> dict[str, Any]:
    if val is None:
        return {}
    if isinstance(val, dict):
        return dict(val)
    try:
        return json.loads(val) if val else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def parse_line_payout_details(line: dict) -> dict[str, Any]:
    raw = _parse_json_blob(line.get("payout_details_json"))
    base = _empty_details()
    for section in ("employee_deductions", "employer_taxes", "payment", "settlement", "tax_summary"):
        if section in raw and isinstance(raw[section], dict):
            base[section].update(raw[section])
    if "use_payment_receipt" in raw:
        base["use_payment_receipt"] = bool(raw.get("use_payment_receipt"))
    if "employee_note" in raw:
        base["employee_note"] = str(raw.get("employee_note") or "").strip()
    for k in EMPLOYEE_DEDUCTION_KEYS:
        base["employee_deductions"][k] = float(_money(base["employee_deductions"].get(k)))
    for k in EMPLOYER_TAX_KEYS:
        base["employer_taxes"][k] = float(_money(base["employer_taxes"].get(k)))
    for k in (
        "amount_paid",
        "amount_withheld",
        "outstanding_balance",
        "prior_unpaid_taxes",
        "prior_period_adjustment",
        "catch_up_withholding",
        "tax_balance_owed",
    ):
        base["settlement"][k] = float(_money(base["settlement"].get(k)))
    if "paid_full_gross_without_withholding" in base["settlement"]:
        base["settlement"]["paid_full_gross_without_withholding"] = bool(
            base["settlement"].get("paid_full_gross_without_withholding")
        )
    if base["payment"].get("cash_amount") is not None:
        base["payment"]["cash_amount"] = float(_money(base["payment"].get("cash_amount")))
    for k in (
        "current_period_taxes",
        "prior_tax_balance",
        "total_tax_liability",
        "actual_tax_withheld",
        "tax_balance_owed",
        "remaining_balance",
        "tax_catch_up_adjustment",
    ):
        base["tax_summary"][k] = float(_money(base["tax_summary"].get(k)))
    if "estimated" in base["tax_summary"]:
        base["tax_summary"]["estimated"] = bool(base["tax_summary"].get("estimated"))
    gross = float(_money(line.get("gross_amount") or line.get("total_amount") or 0))
    base = reconcile_tax_summary(base)
    if gross > 0:
        base = apply_settlement_math(base, gross)
    return base


def sum_employee_deductions(details: dict) -> float:
    ded = details.get("employee_deductions") or {}
    return float(sum(_money(ded.get(k)) for k in EMPLOYEE_DEDUCTION_KEYS))


def sum_employer_taxes(details: dict) -> float:
    er = details.get("employer_taxes") or {}
    return float(sum(_money(er.get(k)) for k in EMPLOYER_TAX_KEYS))


def reconcile_tax_summary(details: dict) -> dict:
    """Compute tax liability vs withheld amounts (catch-up is manager-entered only)."""
    ded = details.get("employee_deductions") or {}
    settlement = dict(details.get("settlement") or {})
    tax_summary = dict(details.get("tax_summary") or {})

    current_period = float(sum(_money(ded.get(k)) for k in EMPLOYEE_DEDUCTION_KEYS))
    prior_balance = float(_money(settlement.get("prior_unpaid_taxes")))
    prior_adj = float(_money(settlement.get("prior_period_adjustment")))
    catch_up = float(_money(settlement.get("catch_up_withholding")))
    paid_full_gross = bool(settlement.get("paid_full_gross_without_withholding"))
    if paid_full_gross:
        catch_up = 0.0
        settlement["catch_up_withholding"] = 0.0

    actual_withheld = float(_money(settlement.get("amount_withheld")))
    total_liability = round(current_period + prior_balance + prior_adj, 2)

    if paid_full_gross:
        period_balance = round(current_period, 2)
    else:
        withheld_for_current = round(min(current_period, max(0.0, actual_withheld - catch_up)), 2)
        period_balance = round(current_period - withheld_for_current, 2)

    remaining = round(prior_balance + period_balance + prior_adj - catch_up, 2)
    settlement["tax_balance_owed"] = period_balance

    tax_summary.update(
        {
            "current_period_taxes": current_period,
            "prior_tax_balance": prior_balance,
            "total_tax_liability": total_liability,
            "actual_tax_withheld": actual_withheld,
            "tax_balance_owed": period_balance,
            "remaining_balance": remaining,
            "tax_catch_up_adjustment": catch_up,
        }
    )
    details["settlement"] = settlement
    details["tax_summary"] = tax_summary
    return details


def apply_settlement_math(details: dict, gross: float) -> dict:
    """Derive withheld and net pay from current taxes + optional catch-up withholding."""
    details = reconcile_tax_summary(dict(details))
    settlement = details.get("settlement") or {}
    tax_summary = details.get("tax_summary") or {}
    gross_f = float(_money(gross))
    current_period = float(tax_summary.get("current_period_taxes") or 0)
    paid_full_gross = bool(settlement.get("paid_full_gross_without_withholding"))
    catch_up = float(_money(settlement.get("catch_up_withholding")))

    if paid_full_gross:
        catch_up = 0.0
        settlement["catch_up_withholding"] = 0.0
        withheld = 0.0
        paid = round(gross_f, 2)
    else:
        withheld = round(current_period + catch_up, 2)
        paid = round(max(0.0, gross_f - withheld), 2)

    settlement["amount_withheld"] = withheld
    settlement["amount_paid"] = paid
    settlement["outstanding_balance"] = 0.0
    details["settlement"] = settlement
    return reconcile_tax_summary(details)


def compute_tax_withheld_breakdown(details: dict) -> dict[str, float]:
    """Employee tax liability components plus actual withheld and balance fields."""
    details = reconcile_tax_summary(dict(details))
    ded = details.get("employee_deductions") or {}
    settlement = details.get("settlement") or {}
    tax_summary = details.get("tax_summary") or {}
    other = float(_money(ded.get("other1"))) + float(_money(ded.get("other2")))
    prior_adj = float(_money(settlement.get("prior_period_adjustment")))
    components = {
        "federal_income_tax": float(_money(ded.get("fit"))),
        "social_security": float(_money(ded.get("ss"))),
        "medicare": float(_money(ded.get("medicare"))),
        "state_tax": float(_money(ded.get("state"))),
        "local_tax": float(_money(ded.get("local"))),
        "other_deduction": other,
        "prior_period_adjustment": prior_adj,
        "total_employee_taxes": float(tax_summary.get("current_period_taxes") or 0),
        "prior_tax_balance": float(tax_summary.get("prior_tax_balance") or 0),
        "total_tax_liability": float(tax_summary.get("total_tax_liability") or 0),
        "actual_tax_withheld": float(tax_summary.get("actual_tax_withheld") or 0),
        "tax_balance_owed": float(tax_summary.get("tax_balance_owed") or 0),
        "remaining_balance": float(tax_summary.get("remaining_balance") or 0),
        "tax_catch_up_adjustment": float(tax_summary.get("tax_catch_up_adjustment") or 0),
        "catch_up_withholding": float(_money(settlement.get("catch_up_withholding"))),
    }
    components["total_tax_withheld"] = components["actual_tax_withheld"]
    return components


def enrich_line_settlement_fields(line: dict, batch: dict) -> dict:
    """Attach net_paid, tax_withheld, and breakdown for API consumers."""
    row = dict(line)
    details = parse_line_payout_details(row)
    finalized = bool(batch.get("payout_details_finalized_at"))
    row["payout_details_finalized"] = finalized
    if finalized:
        settlement = details.get("settlement") or {}
        payment = details.get("payment") or {}
        gross = float(_money(row.get("gross_amount") or row.get("total_amount") or 0))
        breakdown = compute_tax_withheld_breakdown(details)
        paid_full_gross = bool(settlement.get("paid_full_gross_without_withholding"))
        row["net_paid"] = float(_money(settlement.get("amount_paid")))
        if paid_full_gross:
            row["tax_withheld"] = 0.0
            if row["net_paid"] <= 0 and gross > 0:
                row["net_paid"] = gross
        else:
            row["tax_withheld"] = breakdown["actual_tax_withheld"]
        row["tax_liability"] = breakdown["total_employee_taxes"]
        row["prior_tax_balance"] = breakdown["prior_tax_balance"]
        row["catch_up_withholding"] = float(_money(settlement.get("catch_up_withholding")))
        row["tax_withheld_breakdown"] = json_safe(breakdown)
        row["tax_summary"] = json_safe(details.get("tax_summary") or {})
        row["payment_date"] = payment.get("date")
        row["payment_method_settlement"] = payment_method_key(details)
        row["payment_method_label"] = _payment_method_label(payment.get("method"))
    else:
        row["net_paid"] = None
        row["tax_withheld"] = None
        row["tax_withheld_breakdown"] = None
    return row


def sum_employer_taxes(details: dict) -> float:
    er = details.get("employer_taxes") or {}
    return float(sum(_money(er.get(k)) for k in EMPLOYER_TAX_KEYS))


def compute_line_totals(line: dict, details: Optional[dict] = None) -> dict[str, float]:
    details = details or parse_line_payout_details(line)
    details = reconcile_tax_summary(dict(details))
    gross = float(_money(line.get("gross_amount") or line.get("total_amount") or 0))
    emp_ded = sum_employee_deductions(details)
    er_tax = sum_employer_taxes(details)
    catch_up = float(_money((details.get("settlement") or {}).get("catch_up_withholding")))
    net = round(gross - emp_ded - catch_up, 2)
    employer_cost = round(gross + er_tax, 2)
    details = apply_settlement_math(details, gross)
    settlement = details.get("settlement") or {}
    tax_summary = details.get("tax_summary") or {}
    amount_paid = float(_money(settlement.get("amount_paid")))
    amount_withheld = float(_money(settlement.get("amount_withheld")))
    outstanding = float(_money(settlement.get("outstanding_balance")))
    prior_unpaid = float(_money(settlement.get("prior_unpaid_taxes")))
    prior_adj = float(_money(settlement.get("prior_period_adjustment")))
    catch_up = float(_money(settlement.get("catch_up_withholding")))
    paid_full_gross = bool(settlement.get("paid_full_gross_without_withholding"))
    net_paid_to_employee = amount_paid if amount_paid > 0 else (gross if paid_full_gross else net)
    return {
        "gross_pay": gross,
        "total_employee_deductions": emp_ded,
        "net_pay": net,
        "net_paid_to_employee": round(net_paid_to_employee, 2),
        "total_employer_taxes": er_tax,
        "employer_cost": employer_cost,
        "amount_paid": amount_paid,
        "amount_withheld": amount_withheld,
        "outstanding_balance": outstanding,
        "prior_unpaid_taxes": prior_unpaid,
        "prior_period_adjustment": prior_adj,
        "current_period_taxes": float(tax_summary.get("current_period_taxes") or emp_ded),
        "prior_tax_balance": float(tax_summary.get("prior_tax_balance") or prior_unpaid),
        "total_tax_liability": float(tax_summary.get("total_tax_liability") or 0),
        "tax_balance_owed": float(tax_summary.get("tax_balance_owed") or 0),
        "remaining_tax_balance": float(tax_summary.get("remaining_balance") or 0),
        "catch_up_withholding": catch_up,
        "tax_catch_up_adjustment": float(tax_summary.get("tax_catch_up_adjustment") or 0),
        "paid_full_gross_without_withholding": paid_full_gross,
    }


def batch_document_mode(batch: dict) -> str:
    raw = batch.get("document_mode")
    if raw is None or str(raw).strip() == "":
        if str(batch.get("worker_category") or "") == "contractor_1099":
            return "payment_receipt"
        return DEFAULT_DOCUMENT_MODE
    mode = str(raw).strip().lower()
    if mode not in DOCUMENT_MODES:
        return DEFAULT_DOCUMENT_MODE
    return mode


def payment_method_key(details: dict) -> str:
    payment = details.get("payment") or {}
    return str(payment.get("method") or "direct_deposit").strip().lower()


def is_cash_payment(details: dict) -> bool:
    return payment_method_key(details) == "cash"


def line_uses_payment_receipt(batch: dict, details: dict) -> bool:
    if batch_document_mode(batch) == "payment_receipt":
        return True
    return bool(details.get("use_payment_receipt"))


def receipt_required_for_line(details: dict) -> bool:
    return is_cash_payment(details)


def _default_payment_date(batch: dict) -> str:
    return str(batch.get("pay_period_end") or batch.get("pay_period_start") or "").strip()


def apply_payment_defaults(batch: dict, details: dict) -> dict:
    """Fill missing payment date from pay period end when method is set or cash receipt required."""
    out = dict(details)
    payment = dict(out.get("payment") or {})
    needs_date = receipt_required_for_line(out) or str(payment.get("method") or "").strip()
    if needs_date and not str(payment.get("date") or "").strip():
        default = _default_payment_date(batch)
        if default:
            payment["date"] = default
    out["payment"] = payment
    return out


def finalize_blockers(batch: dict, lines: list[dict]) -> list[str]:
    from backend.payroll_status_display import can_finalize_payout_details

    if batch.get("payout_details_finalized_at"):
        return ["Payout details already finalized"]
    if not can_finalize_payout_details(batch):
        cat = str(batch.get("worker_category") or "w2")
        if cat == "w2" and str(batch.get("status") or "") not in (
            "approved_for_payment",
            "paid",
            "closed",
        ):
            return ["W-2 batches must be approved for payment before finalize"]
        return ["Batch is not ready to finalize payout details"]
    mode = batch_document_mode(batch)
    blockers: list[str] = []
    for ln in lines:
        details = ln.get("payout_details") or parse_line_payout_details(ln)
        details = apply_payment_defaults(batch, details)
        payment = details.get("payment") or {}
        settlement = details.get("settlement") or {}
        name = ln.get("worker_name_snapshot") or ln.get("id")
        if mode == "payment_receipt":
            if not payment.get("date"):
                blockers.append(f"Payment date required for {name}")
            if not payment.get("method"):
                blockers.append(f"Payment method required for {name}")
            if float(_money(settlement.get("amount_paid"))) <= 0:
                blockers.append(f"Amount paid required for {name}")
        if receipt_required_for_line(details):
            if not payment.get("date"):
                blockers.append(f"Payment date required for cash payment — {name}")
            if float(_money(settlement.get("amount_paid"))) <= 0:
                blockers.append(f"Amount paid required for cash payment — {name}")
    return blockers


def can_generate_paystub_for_line(batch: dict, details: dict, *, preview: bool = False) -> bool:
    if line_uses_payment_receipt(batch, details):
        return False
    if preview:
        return batch_ready_for_payout_details(batch)
    return bool(batch.get("payout_details_finalized_at"))


def can_generate_receipt_for_line(batch: dict, details: dict) -> bool:
    if not batch.get("payout_details_finalized_at"):
        return False
    if batch_document_mode(batch) == "payment_receipt":
        return True
    if line_uses_payment_receipt(batch, details):
        return True
    if receipt_required_for_line(details):
        return True
    if payment_method_key(details) == "check":
        return True
    return False


def line_document_state(batch: dict, line: dict, details: Optional[dict] = None) -> dict[str, Any]:
    details = details or parse_line_payout_details(line)
    effective = (
        "payment_receipt"
        if line_uses_payment_receipt(batch, details)
        else "official_paystub"
    )
    return json_safe(
        {
            "effective_type": effective,
            "receipt_available": can_generate_receipt_for_line(batch, details),
            "receipt_required": receipt_required_for_line(details),
            "paystub_available": can_generate_paystub_for_line(batch, details),
            "paystub_preview_available": can_generate_paystub_for_line(
                batch, details, preview=True
            ),
            "use_payment_receipt": bool(details.get("use_payment_receipt")),
        }
    )


def _user_display_meta(conn, user_id: Optional[int]) -> dict[str, str]:
    if not user_id:
        return {"display_name": "", "employee_id": ""}
    chk = conn.cursor()
    select_cols = ["display_name", "username"]
    if table_has_column(chk, "users", "employee_id"):
        select_cols.insert(0, "employee_id")
    c = conn.cursor(dictionary=True)
    c.execute(
        f"SELECT {', '.join(select_cols)} FROM users WHERE id=%s LIMIT 1",
        (int(user_id),),
    )
    row = c.fetchone() or {}
    name = str(row.get("display_name") or row.get("username") or "").strip()
    emp_id = str(row.get("employee_id") or "").strip()
    return {"display_name": name, "employee_id": emp_id}


def _payment_method_label(method: str) -> str:
    key = str(method or "").strip().lower()
    return PAYMENT_METHOD_LABELS.get(key, method or "—")


def enrich_line_with_payout_details(line: dict, batch: Optional[dict] = None) -> dict:
    row = dict(line)
    details = parse_line_payout_details(row)
    totals = compute_line_totals(row, details)
    row["payout_details"] = json_safe(details)
    row["payout_totals"] = json_safe(totals)
    if batch:
        row = enrich_line_settlement_fields(row, batch)
        row["document"] = line_document_state(batch, row, details)
    return json_safe(row)


def _audit_append(batch: dict, event: str, actor_id: int, detail: str = "") -> list:
    audit = _parse_json_blob(batch.get("payout_details_audit_json"))
    events = audit.get("events") if isinstance(audit.get("events"), list) else []
    events.append(
        {
            "event": event,
            "actor_id": int(actor_id),
            "at": datetime.utcnow().isoformat(timespec="seconds"),
            "detail": detail,
        }
    )
    return events


def batch_ready_for_payout_details(batch: dict) -> bool:
    from backend.payroll_status_display import batch_ready_for_payout_details as _ready

    return _ready(batch)


def payout_workflow_state(batch: dict) -> dict[str, Any]:
    st = str(batch.get("status") or "")
    confirmed = batch.get("accountant_payment_confirmed_at")
    finalized = batch.get("payout_details_finalized_at")
    doc_mode = batch_document_mode(batch)
    ready = batch_ready_for_payout_details(batch)
    lines = batch.get("lines") or []
    receipt_required_pending = False
    finalize_blockers_list: list[str] = []
    if ready and not finalized:
        finalize_blockers_list = finalize_blockers(batch, lines)
        for ln in lines:
            details = ln.get("payout_details") or parse_line_payout_details(ln)
            if receipt_required_for_line(details):
                settlement = details.get("settlement") or {}
                payment = details.get("payment") or {}
                if not settlement.get("amount_paid") or not payment.get("date"):
                    receipt_required_pending = True
                    break
    from backend.payroll_status_display import can_finalize_payout_details

    can_finalize = (
        ready
        and not finalized
        and can_finalize_payout_details(batch)
        and not finalize_blockers_list
    )
    return json_safe(
        {
            "batch_status": st,
            "awaiting_accountant_confirmation": ready and not confirmed,
            "accountant_payment_confirmed": bool(confirmed),
            "accountant_payment_confirmed_at": batch.get("accountant_payment_confirmed_at"),
            "accountant_payment_confirmed_by": batch.get("accountant_payment_confirmed_by"),
            "payout_details_finalized": bool(finalized),
            "payout_details_finalized_at": batch.get("payout_details_finalized_at"),
            "payout_details_finalized_by": batch.get("payout_details_finalized_by"),
            "document_mode": doc_mode,
            "can_set_document_mode": ready and not finalized,
            "paystub_available": bool(finalized) and doc_mode == "official_paystub",
            "paystub_preview_available": ready and doc_mode == "official_paystub",
            "payment_receipt_available": bool(finalized) and doc_mode == "payment_receipt",
            "receipt_required_pending": receipt_required_pending,
            "can_edit_details": ready and not finalized,
            "can_finalize": can_finalize,
            "finalize_blockers": finalize_blockers_list,
        }
    )


def enrich_batch_payout_details(conn, organization_id: int, batch: dict) -> dict:
    from backend.payroll_workflow import enrich_payout_batch

    batch = enrich_payout_batch(conn, organization_id, batch)
    lines = []
    for ln in batch.get("lines") or []:
        row = dict(ln)
        uid = row.get("user_id")
        if uid:
            meta = _user_display_meta(conn, int(uid))
            row["employee_id"] = meta["employee_id"]
        lines.append(enrich_line_with_payout_details(row, batch))
    batch["lines"] = lines
    batch["payout_workflow"] = payout_workflow_state(batch)
    from backend.payroll_status_display import enrich_batch_payroll_display

    batch = enrich_batch_payroll_display(batch)
    audit = _parse_json_blob(batch.get("payout_details_audit_json"))
    batch["payout_details_audit"] = audit.get("events") or []
    return json_safe(batch)


def list_accountant_payment_queue(
    conn, organization_id: int, *, worker_category: Optional[str] = None
) -> list[dict]:
    ensure_payout_details_columns(conn.cursor())
    c = conn.cursor(dictionary=True)
    q = """
        SELECT * FROM payout_batches
        WHERE organization_id = %s
          AND status IN ('approved_for_payment', 'paid', 'closed')
          AND accountant_payment_confirmed_at IS NULL
    """
    params: list[Any] = [int(organization_id)]
    if worker_category:
        q += " AND worker_category = %s"
        params.append(str(worker_category))
    q += " ORDER BY pay_period_start DESC, id DESC"
    c.execute(q, tuple(params))
    rows = c.fetchall() or []
    out = []
    for row in rows:
        item = dict(row)
        item["payout_workflow"] = payout_workflow_state(item)
        from backend.payroll_status_display import enrich_list_item_payroll_display

        enrich_list_item_payroll_display(item)
        out.append(json_safe(item))
    return out


def get_payout_batch_details(conn, organization_id: int, batch_id: int) -> Optional[dict]:
    batch = get_payout_batch(conn, organization_id, batch_id)
    if not batch:
        return None
    return enrich_batch_payout_details(conn, organization_id, batch)


def infer_pay_frequency_from_batch(batch: dict) -> str:
    """Infer weekly vs biweekly from pay period length."""
    start = batch.get("pay_period_start")
    end = batch.get("pay_period_end")
    try:
        from datetime import datetime

        d0 = datetime.strptime(str(start)[:10], "%Y-%m-%d")
        d1 = datetime.strptime(str(end)[:10], "%Y-%m-%d")
        days = (d1 - d0).days + 1
        if days <= 8:
            return "weekly"
        if days <= 16:
            return "biweekly"
    except (TypeError, ValueError):
        pass
    return "weekly"


def build_estimated_payout_details_patch(
    conn,
    organization_id: int,
    user_id: int,
    gross: float,
    *,
    worker_name: str = "",
    pay_period_start: Optional[str] = None,
    pay_frequency: Optional[str] = None,
) -> dict[str, Any]:
    """Estimated employee/employer taxes for payout_details_json (accountant may override)."""
    from backend.w2_payroll_tax_engine import calculate_w2_line_taxes

    calc = calculate_w2_line_taxes(
        conn,
        organization_id,
        int(user_id),
        gross_pay=float(gross or 0),
        pay_period_start=pay_period_start,
        minimum_withholding=True,
        worker_name_snapshot=worker_name or None,
        pay_frequency=pay_frequency,
    )
    if calc.get("tax_calc_status") == "profile_incomplete":
        raise ValueError(calc.get("tax_calc_notes") or "Tax profile incomplete")

    medicare = float(calc.get("medicare_employee") or 0) + float(
        calc.get("additional_medicare_employee") or 0
    )
    employee_deductions = {
        "fit": float(calc.get("federal_withholding_estimate") or 0),
        "ss": float(calc.get("social_security_employee") or 0),
        "medicare": round(medicare, 2),
        "state": float(calc.get("ny_state_withholding_estimate") or 0),
        "local": float(calc.get("nyc_withholding_estimate") or 0),
        "other1": float(calc.get("ny_pfl_deduction") or 0),
        "other2": float(calc.get("ny_dbl_deduction") or 0),
    }
    employer_taxes = {
        "er_ss": float(calc.get("employer_social_security") or 0),
        "er_medicare": float(calc.get("employer_medicare") or 0),
        "futa": float(calc.get("futa_estimate") or 0),
        "suta": float(calc.get("ny_suta_estimate") or 0),
        "other": float(calc.get("employer_other_tax_estimate") or 0),
    }
    patch = {
        "employee_deductions": employee_deductions,
        "employer_taxes": employer_taxes,
        "tax_summary": {
            "estimated": True,
            "minimum_withholding": True,
            "calc_notes": str(calc.get("tax_calc_notes") or ""),
        },
    }
    return reconcile_tax_summary(parse_line_payout_details({"payout_details_json": patch}))


def estimate_payout_batch_taxes(
    conn,
    organization_id: int,
    batch_id: int,
    *,
    actor_id: int,
    line_ids: Optional[list[int]] = None,
) -> dict:
    """Auto-fill estimated withholding on batch lines (editable until finalize)."""
    ensure_payout_details_columns(conn.cursor())
    batch = get_payout_batch(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if not batch_ready_for_payout_details(batch):
        raise ValueError("Batch must be approved for payment before estimating taxes")
    if batch.get("payout_details_finalized_at"):
        raise ValueError("Payout details are finalized — estimates are locked")

    pay_freq = infer_pay_frequency_from_batch(batch)
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT id, user_id, worker_name_snapshot, gross_amount, total_amount, payout_details_json
        FROM payout_batch_lines WHERE batch_id=%s
        """,
        (int(batch_id),),
    )
    rows = c.fetchall() or []
    want = {int(x) for x in (line_ids or [])} if line_ids else None
    updated = 0
    for row in rows:
        lid = int(row["id"])
        if want is not None and lid not in want:
            continue
        gross = float(_money(row.get("gross_amount") or row.get("total_amount") or 0))
        if gross <= 0:
            continue
        existing = parse_line_payout_details(row)
        estimate = build_estimated_payout_details_patch(
            conn,
            organization_id,
            int(row["user_id"]),
            gross,
            worker_name=str(row.get("worker_name_snapshot") or ""),
            pay_period_start=str(batch.get("pay_period_start") or ""),
            pay_frequency=pay_freq,
        )
        merged = dict(existing)
        merged["employee_deductions"] = estimate["employee_deductions"]
        merged["employer_taxes"] = estimate["employer_taxes"]
        merged["tax_summary"] = {
            **(merged.get("tax_summary") or {}),
            **(estimate.get("tax_summary") or {}),
            "estimated": True,
        }
        merged = apply_settlement_math(merged, gross)
        c2 = conn.cursor()
        c2.execute(
            "UPDATE payout_batch_lines SET payout_details_json=%s WHERE id=%s",
            (json.dumps(merged), lid),
        )
        updated += 1

    events = _audit_append(batch, "tax_estimates_applied", actor_id, f"{updated} lines")
    c3 = conn.cursor()
    c3.execute(
        """
        UPDATE payout_batches SET payout_details_audit_json=%s, updated_at=CURRENT_TIMESTAMP
        WHERE id=%s AND organization_id=%s
        """,
        (json.dumps({"events": events}), int(batch_id), int(organization_id)),
    )
    conn.commit()
    return get_payout_batch_details(conn, organization_id, batch_id) or {}


def _merge_line_details(existing: dict, patch: dict, *, gross: float = 0) -> dict:
    base = parse_line_payout_details(
        {
            "payout_details_json": existing,
            "gross_amount": gross,
            "total_amount": gross,
        }
    )
    for section in ("employee_deductions", "employer_taxes", "payment", "settlement", "tax_summary"):
        if section in patch and isinstance(patch[section], dict):
            for key, val in patch[section].items():
                if key in base[section]:
                    if section == "settlement" and key == "paid_full_gross_without_withholding":
                        base[section][key] = bool(val)
                    elif section == "tax_summary" and key == "estimated":
                        base[section][key] = bool(val)
                    elif section in ("employee_deductions", "employer_taxes", "settlement", "tax_summary"):
                        base[section][key] = float(_money(val))
                    else:
                        base[section][key] = val
    if "paid_full_gross_without_withholding" in (patch.get("settlement") or {}):
        base["settlement"]["paid_full_gross_without_withholding"] = bool(
            patch["settlement"]["paid_full_gross_without_withholding"]
        )
    if "estimated" in (patch.get("tax_summary") or {}):
        base["tax_summary"]["estimated"] = bool(patch["tax_summary"]["estimated"])
    if "use_payment_receipt" in patch:
        base["use_payment_receipt"] = bool(patch.get("use_payment_receipt"))
    if "employee_note" in patch:
        base["employee_note"] = str(patch.get("employee_note") or "").strip()
    gross_f = float(_money(gross))
    base = reconcile_tax_summary(base)
    if gross_f > 0:
        base = apply_settlement_math(base, gross_f)
    return base


def _persist_line_payment_defaults(
    conn,
    organization_id: int,
    batch_id: int,
    batch: dict,
    lines: list[dict],
) -> int:
    """Write default payment dates onto lines before finalize validation."""
    c = conn.cursor()
    updated = 0
    for ln in lines:
        details = ln.get("payout_details") or parse_line_payout_details(ln)
        merged = apply_payment_defaults(batch, details)
        if merged == details:
            continue
        gross = float(_money(ln.get("gross_amount") or ln.get("total_amount") or 0))
        merged = reconcile_tax_summary(merged)
        if gross > 0:
            merged = apply_settlement_math(merged, gross)
        c.execute(
            """
            UPDATE payout_batch_lines SET payout_details_json=%s, updated_at=CURRENT_TIMESTAMP
            WHERE id=%s AND batch_id=%s AND organization_id=%s
            """,
            (
                json.dumps(merged),
                int(ln["id"]),
                int(batch_id),
                int(organization_id),
            ),
        )
        updated += 1
    return updated


def update_payout_batch_details(
    conn,
    organization_id: int,
    batch_id: int,
    body: dict,
    *,
    actor_id: int,
) -> dict:
    ensure_payout_details_columns(conn.cursor())
    batch = get_payout_batch(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if not batch_ready_for_payout_details(batch):
        raise ValueError("Batch must be approved for payment before editing payout details")
    if batch.get("payout_details_finalized_at"):
        raise ValueError("Payout details are finalized — edits are locked")
    lines_patch = body.get("lines") or []
    batch_note = body.get("batch_note")
    if not lines_patch and batch_note is None:
        raise ValueError("lines array or batch_note required")
    c = conn.cursor()
    if batch_note is not None:
        c.execute(
            """
            UPDATE payout_batches SET batch_note=%s, updated_at=CURRENT_TIMESTAMP
            WHERE id=%s AND organization_id=%s
            """,
            (str(batch_note or "").strip() or None, int(batch_id), int(organization_id)),
        )
    if not lines_patch:
        events = _audit_append(batch, "details_updated", actor_id, "batch note")
        c.execute(
            """
            UPDATE payout_batches SET payout_details_audit_json=%s, updated_at=CURRENT_TIMESTAMP
            WHERE id=%s AND organization_id=%s
            """,
            (json.dumps({"events": events}), int(batch_id), int(organization_id)),
        )
        conn.commit()
        return get_payout_batch_details(conn, organization_id, batch_id) or {}
    for item in lines_patch:
        line_id = item.get("line_id") or item.get("id")
        if not line_id:
            continue
        c.execute(
            """
            SELECT payout_details_json, gross_amount, total_amount FROM payout_batch_lines
            WHERE id=%s AND batch_id=%s AND organization_id=%s
            """,
            (int(line_id), int(batch_id), int(organization_id)),
        )
        row = c.fetchone()
        if not row:
            raise ValueError(f"Line {line_id} not found in batch")
        row_dict = row if isinstance(row, dict) else {"payout_details_json": row[0], "gross_amount": row[1], "total_amount": row[2]}
        line_gross = float(_money(row_dict.get("gross_amount") or row_dict.get("total_amount") or 0))
        merged = _merge_line_details(
            _parse_json_blob(row_dict.get("payout_details_json")),
            item.get("payout_details") or item,
            gross=line_gross,
        )
        merged = apply_payment_defaults(batch, merged)
        c.execute(
            """
            UPDATE payout_batch_lines SET payout_details_json=%s, updated_at=CURRENT_TIMESTAMP
            WHERE id=%s AND batch_id=%s AND organization_id=%s
            """,
            (
                json.dumps(merged),
                int(line_id),
                int(batch_id),
                int(organization_id),
            ),
        )
    events = _audit_append(batch, "details_updated", actor_id, f"{len(lines_patch)} line(s)")
    c.execute(
        """
        UPDATE payout_batches SET payout_details_audit_json=%s, updated_at=CURRENT_TIMESTAMP
        WHERE id=%s AND organization_id=%s
        """,
        (json.dumps({"events": events}), int(batch_id), int(organization_id)),
    )
    conn.commit()
    return get_payout_batch_details(conn, organization_id, batch_id) or {}


def confirm_accountant_payment(
    conn, organization_id: int, batch_id: int, *, actor_id: int
) -> dict:
    ensure_payout_details_columns(conn.cursor())
    batch = get_payout_batch(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    st = str(batch.get("status") or "")
    if st not in ACCOUNTANT_QUEUE_STATUSES:
        raise ValueError(
            "Batch must be approved for payment before accountant confirmation"
        )
    if batch.get("accountant_payment_confirmed_at"):
        raise ValueError("Payment already confirmed by accountant")
    events = _audit_append(batch, "accountant_payment_confirmed", actor_id)
    c = conn.cursor()
    c.execute(
        """
        UPDATE payout_batches SET
          accountant_payment_confirmed_at=NOW(),
          accountant_payment_confirmed_by=%s,
          payout_details_audit_json=%s,
          updated_at=CURRENT_TIMESTAMP
        WHERE id=%s AND organization_id=%s
        """,
        (
            int(actor_id),
            json.dumps({"events": events}),
            int(batch_id),
            int(organization_id),
        ),
    )
    conn.commit()
    return get_payout_batch_details(conn, organization_id, batch_id) or {}


def set_batch_document_mode(
    conn,
    organization_id: int,
    batch_id: int,
    document_mode: str,
    *,
    actor_id: int,
) -> dict:
    ensure_payout_details_columns(conn.cursor())
    mode = str(document_mode or "").strip().lower()
    if mode not in DOCUMENT_MODES:
        raise ValueError("document_mode must be payment_receipt or official_paystub")
    batch = get_payout_batch(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if not batch_ready_for_payout_details(batch):
        raise ValueError("Batch must be approved for payment before setting document mode")
    if batch.get("payout_details_finalized_at"):
        raise ValueError("Document mode cannot be changed after finalize")
    events = _audit_append(batch, "document_mode_set", actor_id, mode)
    c = conn.cursor()
    c.execute(
        """
        UPDATE payout_batches SET
          document_mode=%s,
          payout_details_audit_json=%s,
          updated_at=CURRENT_TIMESTAMP
        WHERE id=%s AND organization_id=%s
        """,
        (
            mode,
            json.dumps({"events": events}),
            int(batch_id),
            int(organization_id),
        ),
    )
    conn.commit()
    return get_payout_batch_details(conn, organization_id, batch_id) or {}


def _validate_finalize_batch(batch: dict) -> None:
    blockers = finalize_blockers(batch, batch.get("lines") or [])
    if blockers:
        raise ValueError(blockers[0])


def finalize_payout_details(
    conn, organization_id: int, batch_id: int, *, actor_id: int
) -> dict:
    ensure_payout_details_columns(conn.cursor())
    batch = get_payout_batch(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if not batch_ready_for_payout_details(batch):
        raise ValueError("Batch must be approved for payment before finalize")
    if batch.get("payout_details_finalized_at"):
        raise ValueError("Payout details already finalized")
    enriched = get_payout_batch_details(conn, organization_id, batch_id) or {}
    if _persist_line_payment_defaults(
        conn,
        organization_id,
        batch_id,
        enriched,
        enriched.get("lines") or [],
    ):
        conn.commit()
    enriched = get_payout_batch_details(conn, organization_id, batch_id) or {}
    _validate_finalize_batch(enriched)
    events = _audit_append(batch, "payout_details_finalized", actor_id)
    c = conn.cursor()
    c.execute(
        """
        UPDATE payout_batches SET
          payout_details_finalized_at=NOW(),
          payout_details_finalized_by=%s,
          payout_details_audit_json=%s,
          updated_at=CURRENT_TIMESTAMP
        WHERE id=%s AND organization_id=%s
        """,
        (
            int(actor_id),
            json.dumps({"events": events}),
            int(batch_id),
            int(organization_id),
        ),
    )
    conn.commit()
    return get_payout_batch_details(conn, organization_id, batch_id) or {}


def _other_deduction_amount(ded: dict) -> float:
    return round(
        float(_money(ded.get("other1"))) + float(_money(ded.get("other2"))),
        2,
    )


def paystub_deduction_rows(details: dict) -> tuple[list[tuple[str, float]], float]:
    """Return labeled deduction rows and total deductions for paystub display."""
    ded = details.get("employee_deductions") or {}
    settlement = details.get("settlement") or {}
    rows: list[tuple[str, float]] = []
    for key, label in PAYSTUB_DEDUCTION_LINES:
        rows.append((label, float(_money(ded.get(key)))))
    rows.append(("Other Deduction", _other_deduction_amount(ded)))
    prior_adj = float(_money(settlement.get("prior_period_adjustment")))
    rows.append(("Prior Period Adjustment", prior_adj))
    total = round(sum(amt for _, amt in rows), 2)
    return rows, total


def _paystub_notes_html(batch: dict, details: dict) -> str:
    batch_note = str(batch.get("batch_note") or "").strip()
    employee_note = str(details.get("employee_note") or "").strip()
    if not batch_note and not employee_note:
        return ""
    parts: list[str] = []
    if batch_note:
        parts.append(f"<h2>Batch Note</h2>\n<p>{batch_note}</p>")
    if employee_note:
        parts.append(f"<h2>Employee Note</h2>\n<p>{employee_note}</p>")
    return "\n".join(parts)


def _paystub_copy_mode(raw: Optional[str]) -> str:
    c = str(raw or "employee").strip().lower()
    if c in ("employer", "employer_copy", "employer_packet"):
        return "employer"
    return "employee"


def _paystub_base_css() -> str:
    return """
  @page { size: letter; margin: 0.4in; }
  * { box-sizing: border-box; }
  body { font-family: system-ui, -apple-system, sans-serif; color: #0f172a; margin: 0; padding: 0; font-size: 9.5px; line-height: 1.25; }
  h1 { color: #0097b2; font-size: 1rem; margin: 0; }
  h2 { color: #007a91; font-size: 0.82rem; margin: 5px 0 2px; font-weight: 700; }
  .meta { color: #475569; margin: 2px 0 4px; font-size: 9px; }
  table.compact { width: 100%; border-collapse: collapse; margin: 2px 0 4px; table-layout: fixed; }
  table.compact th, table.compact td { padding: 3px 6px; border-bottom: 1px solid #e2e8f0; vertical-align: top; }
  table.compact th { text-align: left; color: #007a91; font-size: 9px; font-weight: 600; }
  table.compact td:first-child, table.compact th:first-child { width: 64%; }
  table.compact td:last-child, table.compact th:last-child { width: 36%; text-align: right; }
  table.compact td.amount, table.compact th.amount { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
  table.compact tr.total td { font-weight: 700; border-top: 1px solid #cbd5e1; }
  .paystub-sheet { page-break-after: always; max-height: 10.2in; overflow: hidden; }
  .paystub-sheet:last-child { page-break-after: auto; }
  .brand-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; border-top: 2px solid #0097b2; padding-top: 5px; }
  .copy-badge { font-size: 8.5px; font-weight: 700; letter-spacing: 0.05em; color: #64748b; margin-bottom: 2px; }
  .preview-banner { background: #fef3c7; color: #92400e; padding: 4px 8px; border-radius: 3px; margin-bottom: 4px; font-size: 9px; }
  .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 16px; margin: 4px 0 6px; font-size: 9.5px; }
  .info-grid dt { color: #64748b; font-size: 9px; }
  .info-grid dd { margin: 0 0 2px; font-weight: 600; }
  .note-box { font-size: 8.5px; color: #64748b; margin: 3px 0; padding: 4px 6px; background: #f8fafc; border-radius: 3px; }
  .cash-receipt { margin-top: 8px; padding: 8px; border: 1px dashed #94a3b8; border-radius: 3px; font-size: 9px; }
  .cash-receipt h2 { margin: 0 0 4px; font-size: 0.8rem; }
  .cash-receipt .row { margin: 3px 0; }
  .sig-line { margin: 6px 0 2px; border-bottom: 1px solid #334155; min-height: 16px; }
  .sig-label { font-size: 8px; color: #64748b; }
  .internal { font-size: 8.5px; color: #64748b; margin: 2px 0; }
  .notes p { white-space: pre-wrap; margin: 2px 0 4px; font-size: 9px; }
"""


def _paystub_money_row(label: str, amt: float, bold: bool = False) -> str:
    cls = " class='total'" if bold else ""
    return (
        f"<tr{cls}><td>{label}</td>"
        f"<td class='amount'>${amt:,.2f}</td></tr>"
    )


def _payment_detail_rows(payment: dict, totals: dict, *, cash_receipt_separate: bool = False) -> str:
    method_key = payment_method_key({"payment": payment})
    label = _payment_method_label(payment.get("method"))
    rows = [f"<tr><td>Payment method</td><td>{label}</td></tr>"]
    if method_key == "cash" and not cash_receipt_separate:
        amt = payment.get("cash_amount")
        if amt is None or str(amt).strip() == "":
            amt = totals.get("net_paid_to_employee") or totals.get("amount_paid")
        rows.append(
            f"<tr><td>Amount received</td><td class='amount'>${float(_money(amt)):,.2f}</td></tr>"
        )
    elif method_key == "check":
        chk = str(payment.get("check_number") or "").strip() or "—"
        rows.append(f"<tr><td>Check number</td><td>{chk}</td></tr>")
    elif method_key in ("zelle", "direct_deposit"):
        ref = str(payment.get("reference") or "").strip() or "—"
        rows.append(f"<tr><td>Reference</td><td>{ref}</td></tr>")
    elif method_key == "other":
        ref = str(payment.get("reference") or "").strip()
        if ref:
            rows.append(f"<tr><td>Reference</td><td>{ref}</td></tr>")
    if method_key != "cash" or not cash_receipt_separate:
        pay_date = payment.get("date")
        if pay_date:
            rows.append(f"<tr><td>Pay date</td><td>{pay_date}</td></tr>")
    return "\n".join(rows)


def _cash_receipt_section_html(line: dict, payment: dict, totals: dict) -> str:
    name = str(line.get("worker_name_snapshot") or "")
    amt = payment.get("cash_amount")
    if amt is None or str(amt).strip() == "":
        amt = totals.get("net_paid_to_employee") or totals.get("amount_paid")
    amt_str = f"${float(_money(amt)):,.2f}"
    pay_date = str(payment.get("date") or "").strip() or "—"
    return f"""
<div class="cash-receipt">
<h2>Cash Receipt</h2>
<div class="row"><strong>Amount received:</strong> {amt_str}</div>
<div class="row"><strong>Date paid:</strong> {pay_date}</div>
<div class="row"><strong>Employee name:</strong> {name}</div>
<div class="sig-line"></div><div class="sig-label">Employee signature</div>
<p class="row" style="margin-top:6px;font-size:8.5px">I acknowledge receipt of the cash payment shown above.</p>
</div>"""


def _render_paystub_html(
    batch: dict,
    line: dict,
    details: dict,
    totals: dict,
    *,
    preview: bool = False,
    copy_mode: str = "employee",
) -> str:
    if not can_generate_paystub_for_line(batch, details, preview=preview):
        raise ValueError("Official paystub not available for this payment — use payment receipt")
    copy = _paystub_copy_mode(copy_mode)
    is_employee = copy == "employee"
    er = details.get("employer_taxes") or {}
    payment = details.get("payment") or {}
    settlement = details.get("settlement") or {}
    tax_summary = details.get("tax_summary") or {}
    method_key = payment_method_key(details)
    method_label = _payment_method_label(payment.get("method"))
    gross = float(totals["gross_pay"])
    net_pay = float(totals["net_pay"])
    net_paid = float(totals.get("net_paid_to_employee") or totals["amount_paid"])
    emp_tax_total = float(totals["total_employee_deductions"])
    withheld = float(totals.get("amount_withheld") or 0)
    paid_full_gross = bool(settlement.get("paid_full_gross_without_withholding"))

    preview_banner = (
        "<p class='preview-banner'><strong>PREVIEW</strong> — not finalized. Verify before locking.</p>"
        if preview
        else ""
    )
    copy_badge = "EMPLOYEE COPY" if is_employee else "EMPLOYER COPY — INTERNAL RECORD"
    title = "Employee Paystub" if is_employee else "Employer Payroll Record"
    estimated_note = (
        "<p class='internal'>Estimated withholding — verify with accountant before finalizing.</p>"
        if tax_summary.get("estimated") and not is_employee
        else ""
    )

    gross_paid_note = ""
    if paid_full_gross or (net_paid > net_pay and withheld < emp_tax_total * 0.5):
        gross_paid_note = (
            "<p class='note-box'>Amount paid exceeds net pay because taxes were not withheld from this payment.</p>"
        )

    worker = line.get("worker_name_snapshot") or ""
    emp_id = line.get("employee_id") or ""
    hours = float(line.get("approved_hours") or 0)
    rate = float(line.get("rate") or 0)

    employee_info_html = f"""
<h2>Employee Information</h2>
<dl class="info-grid">
<dt>Employee name</dt><dd>{worker}</dd>
{f'<dt>Employee ID</dt><dd>{emp_id}</dd>' if emp_id else ''}
<dt>Pay period</dt><dd>{batch.get('pay_period_start')} – {batch.get('pay_period_end')}</dd>
<dt>Hours worked</dt><dd>{hours:.2f}</dd>
<dt>Hourly rate</dt><dd>${rate:,.2f}</dd>
</dl>"""

    earnings_html = f"""
<h2>Earnings</h2>
<table class="compact">
<tr><th>Description</th><th class="amount">Amount</th></tr>
{_paystub_money_row('Gross pay', gross, True)}
</table>"""

    emp_ded_rows = []
    for key, label in PAYSTUB_DEDUCTION_LINES:
        val = float(_money((details.get("employee_deductions") or {}).get(key)))
        emp_ded_rows.append(_paystub_money_row(label, val))
    emp_tax_table = f"""
<h2>Employee Taxes</h2>
<table class="compact">
<tr><th>Tax</th><th class="amount">Amount</th></tr>
{"".join(emp_ded_rows)}
{_paystub_money_row('Total employee taxes', emp_tax_total, True)}
</table>"""

    net_pay_html = f"""
<h2>Net Pay</h2>
<table class="compact">
{_paystub_money_row('Net pay (after taxes)', net_pay)}
{_paystub_money_row('Amount paid to employee', net_paid, True)}
</table>
{gross_paid_note}"""

    if is_employee:
        tax_balance_html = ""
    else:
        catch_up = float(totals.get("tax_catch_up_adjustment") or 0)
        catch_up_html = ""
        if catch_up > 0 or float(totals.get("prior_tax_balance") or 0) > 0:
            catch_up_html = f"""
<h2>Tax Catch-Up</h2>
<table class="compact">
{_paystub_money_row('Current period taxes', float(totals.get('current_period_taxes') or 0))}
{_paystub_money_row('Prior tax balance', float(totals.get('prior_tax_balance') or 0))}
{_paystub_money_row('Catch-up withholding', catch_up)}
{_paystub_money_row('Total taxes collected', withheld)}
</table>"""
        tax_balance_html = f"""
<h2>Tax Balances (Audit)</h2>
<table class="compact">
{_paystub_money_row('Prior period tax balance', float(totals.get('prior_tax_balance') or 0))}
{_paystub_money_row('Current period taxes', float(totals.get('current_period_taxes') or 0))}
{_paystub_money_row('Total tax liability', float(totals.get('total_tax_liability') or 0))}
{_paystub_money_row('Actual tax withheld', withheld)}
{_paystub_money_row('Remaining balance', float(totals.get('remaining_tax_balance') or 0), True)}
{_paystub_money_row('Tax balance owed (period)', float(totals.get('tax_balance_owed') or 0))}
</table>
{catch_up_html}"""

    cash_receipt_separate = is_employee and method_key == "cash"
    payment_html = f"""
<h2>Payment Information</h2>
<table class="compact">
{_payment_detail_rows(payment, totals, cash_receipt_separate=cash_receipt_separate)}
</table>"""

    employer_html = ""
    if not is_employee:
        er_rows = "".join(
            _paystub_money_row(label, float(_money(er.get(key))))
            for key, label in PAYSTUB_EMPLOYER_TAX_LINES
        )
        employer_html = f"""
<h2>Employer Taxes</h2>
<table class="compact">
<tr><th>Tax</th><th class="amount">Amount</th></tr>
{er_rows}
{_paystub_money_row('Total employer taxes', float(totals['total_employer_taxes']), True)}
<tr class="total"><td>Employer cost</td><td class="amount">${totals['employer_cost']:,.2f}</td></tr>
</table>
<h2>Settlement</h2>
<table class="compact">
{_paystub_money_row('Amount paid', float(totals.get('amount_paid') or 0))}
{_paystub_money_row('Amount withheld', withheld)}
{_paystub_money_row('Prior unpaid taxes', float(totals.get('prior_unpaid_taxes') or 0))}
{_paystub_money_row('Catch-up withholding', float(settlement.get('catch_up_withholding') or 0))}
</table>"""

    cash_receipt_html = ""
    if cash_receipt_separate:
        cash_receipt_html = _cash_receipt_section_html(line, payment, totals)

    notes_html = _paystub_notes_html(batch, details)
    notes_block = f'<div class="notes">{notes_html}</div>' if notes_html and not is_employee else ""
    if notes_html and is_employee and batch.get("batch_note"):
        notes_block = f'<div class="notes"><h2>Paystub Note</h2><p>{batch.get("batch_note")}</p></div>'

    finalized_footer = ""
    if batch.get("payout_details_finalized_at") and not preview:
        finalized_footer = f"<p class='meta'>Finalized {batch.get('payout_details_finalized_at')}</p>"

    from backend.veewash_branding import veewash_logo_img_html

    logo_html = veewash_logo_img_html(height_px=32)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title} — {worker}</title>
<style>{_paystub_base_css()}</style></head><body>
<div class="paystub-sheet">
<div class="copy-badge">{copy_badge}</div>
<div class="brand-head">{logo_html}<h1>{title}</h1></div>
{preview_banner}
{estimated_note}
{employee_info_html}
{earnings_html}
{emp_tax_table}
{net_pay_html}
{tax_balance_html}
{payment_html}
{employer_html}
{notes_block}
{cash_receipt_html}
{finalized_footer}
</div>
</body></html>"""


def _extract_paystub_sheet(html: str) -> str:
    start = html.find("<div class=\"paystub-sheet\">")
    end = html.rfind("</div>\n</body>")
    if start >= 0 and end > start:
        return html[start:end]
    return html


def _combine_paystub_documents(
    batch: dict,
    sheets: list[str],
    *,
    title: str,
    subtitle: str = "",
) -> str:
    if not sheets:
        raise ValueError("No paystub sheets to combine")
    sub = subtitle or f"Pay period: {batch.get('pay_period_start')} – {batch.get('pay_period_end')}"
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>{_paystub_base_css()}</style></head><body>
<h1>{title}</h1>
<p class="meta">{sub}</p>
{"".join(sheets)}
</body></html>"""


def generate_paystub_html(
    conn,
    organization_id: int,
    batch_id: int,
    line_id: int,
    *,
    preview: bool = False,
    copy_mode: str = "employee",
) -> str:
    batch = get_payout_batch_details(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if not preview and not batch.get("payout_details_finalized_at"):
        raise ValueError("Paystub not available until payout details are finalized")
    line = next(
        (ln for ln in batch.get("lines") or [] if int(ln.get("id")) == int(line_id)),
        None,
    )
    if not line:
        raise ValueError("Line not found")
    details = line.get("payout_details") or parse_line_payout_details(line)
    totals = line.get("payout_totals") or compute_line_totals(line, details)
    return _render_paystub_html(
        batch, line, details, totals, preview=preview, copy_mode=copy_mode
    )


def preview_paystub_html(
    conn,
    organization_id: int,
    batch_id: int,
    line_id: int,
    payout_details_patch: dict,
    *,
    batch_note: Optional[str] = None,
    copy_mode: str = "employee",
) -> str:
    """Render paystub from unsaved draft values (preview before finalize)."""
    batch = get_payout_batch_details(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if not batch_ready_for_payout_details(batch):
        raise ValueError("Batch must be approved for payment before previewing paystubs")
    line = next(
        (ln for ln in batch.get("lines") or [] if int(ln.get("id")) == int(line_id)),
        None,
    )
    if not line:
        raise ValueError("Line not found")
    gross = float(_money(line.get("gross_amount") or line.get("total_amount") or 0))
    existing = _parse_json_blob(line.get("payout_details_json"))
    merged = _merge_line_details(existing, payout_details_patch or {}, gross=gross)
    preview_batch = dict(batch)
    if batch_note is not None:
        preview_batch["batch_note"] = str(batch_note or "").strip() or None
    preview_line = dict(line)
    totals = compute_line_totals(preview_line, merged)
    return _render_paystub_html(
        preview_batch,
        preview_line,
        merged,
        totals,
        preview=True,
        copy_mode=copy_mode,
    )


def generate_batch_paystubs_html(
    conn,
    organization_id: int,
    batch_id: int,
    *,
    preview: bool = False,
    copy_mode: str = "employee",
) -> str:
    batch = get_payout_batch_details(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if not preview and not batch.get("payout_details_finalized_at"):
        raise ValueError("Paystubs not available until payout details are finalized")
    sheets: list[str] = []
    for line in batch.get("lines") or []:
        details = line.get("payout_details") or parse_line_payout_details(line)
        if not can_generate_paystub_for_line(batch, details, preview=preview):
            continue
        totals = line.get("payout_totals") or compute_line_totals(line, details)
        html = _render_paystub_html(
            batch, line, details, totals, preview=preview, copy_mode=copy_mode
        )
        sheets.append(_extract_paystub_sheet(html))
    if not sheets:
        raise ValueError("No paystubs available for this batch")
    copy = _paystub_copy_mode(copy_mode)
    title = (
        f"Batch {batch.get('batch_name')} — Employee Paystubs"
        if copy == "employee"
        else f"Batch {batch.get('batch_name')} — Employer Records"
    )
    return _combine_paystub_documents(batch, sheets, title=title)


def generate_employer_payroll_packet_html(
    conn,
    organization_id: int,
    batch_id: int,
    *,
    preview: bool = False,
) -> str:
    """Employer copies of all paystubs plus pay register summary."""
    batch = get_payout_batch_details(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    paystubs_html = generate_batch_paystubs_html(
        conn, organization_id, batch_id, preview=preview, copy_mode="employer"
    )
    register_html = generate_pay_register_html(
        conn, organization_id, batch_id, preview=preview
    )
    paystub_sheets = _extract_paystub_sheet(paystubs_html)
    # Pay register is a full document — append its body content after paystubs.
    reg_start = register_html.find("<body>")
    reg_end = register_html.rfind("</body>")
    register_body = ""
    if reg_start >= 0 and reg_end > reg_start:
        register_body = register_html[reg_start + 6:reg_end].strip()
    title = f"Employer Payroll Packet — {batch.get('batch_name')}"
    combined_sheets = [paystub_sheets]
    if register_body:
        combined_sheets.append(
            f"<div class='paystub-sheet'><h1>Pay Register</h1>{register_body}</div>"
        )
    return _combine_paystub_documents(
        batch,
        combined_sheets,
        title=title,
        subtitle=f"Employer internal record · Pay period {batch.get('pay_period_start')} – {batch.get('pay_period_end')}",
    )


def generate_pay_register_html(
    conn,
    organization_id: int,
    batch_id: int,
    *,
    preview: bool = False,
) -> str:
    batch = get_payout_batch_details(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if not preview and not batch.get("payout_details_finalized_at"):
        raise ValueError("Pay register not available until payout details are finalized")
    if not batch_ready_for_payout_details(batch) and preview:
        raise ValueError("Batch must be approved for payment before previewing pay register")

    rows_html = []
    sum_gross = sum_net = sum_wh = 0.0
    for line in batch.get("lines") or []:
        details = line.get("payout_details") or parse_line_payout_details(line)
        totals = line.get("payout_totals") or compute_line_totals(line, details)
        gross = float(totals["gross_pay"])
        net = float(totals.get("net_paid_to_employee") or totals["amount_paid"])
        withheld = float(totals.get("amount_withheld") or 0)
        method = _payment_method_label((details.get("payment") or {}).get("method"))
        sum_gross += gross
        sum_net += net
        sum_wh += withheld
        rows_html.append(
            f"<tr><td>{line.get('worker_name_snapshot')}</td>"
            f"<td style='text-align:right'>${gross:,.2f}</td>"
            f"<td style='text-align:right'>${withheld:,.2f}</td>"
            f"<td style='text-align:right'>${net:,.2f}</td>"
            f"<td>{method}</td></tr>"
        )

    preview_banner = (
        "<p class='preview-banner'><strong>PREVIEW</strong> — not finalized.</p>"
        if preview
        else ""
    )
    from backend.veewash_branding import veewash_logo_img_html

    logo_html = veewash_logo_img_html(height_px=48)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Pay Register — {batch.get('batch_name')}</title>
<style>
  body {{ font-family: system-ui, sans-serif; color: #0f172a; margin: 24px; }}
  h1 {{ color: #0097b2; font-size: 1.35rem; }}
  .meta {{ color: #475569; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
  th, td {{ padding: 8px 10px; border-bottom: 1px solid #e2e8f0; }}
  th {{ text-align: left; color: #007a91; background: #f8fafc; }}
  .total {{ font-weight: 700; background: #f1f5f9; }}
  .preview-banner {{ background: #fef3c7; color: #92400e; padding: 8px 12px; border-radius: 6px; margin-bottom: 12px; }}
</style></head><body>
{logo_html}
<h1>Pay Register — {batch.get('batch_name')}</h1>
{preview_banner}
<p class="meta">Pay period: {batch.get('pay_period_start')} – {batch.get('pay_period_end')}</p>
<table>
<thead><tr>
<th>Employee</th><th style="text-align:right">Gross</th><th style="text-align:right">Withheld</th>
<th style="text-align:right">Net paid</th><th>Method</th>
</tr></thead>
<tbody>
{"".join(rows_html)}
<tr class="total">
<td>Total</td>
<td style="text-align:right">${sum_gross:,.2f}</td>
<td style="text-align:right">${sum_wh:,.2f}</td>
<td style="text-align:right">${sum_net:,.2f}</td>
<td></td>
</tr>
</tbody>
</table>
</body></html>"""


def generate_payment_receipt_html(
    conn, organization_id: int, batch_id: int, line_id: int
) -> str:
    batch = get_payout_batch_details(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if not batch.get("payout_details_finalized_at"):
        raise ValueError("Payment receipt not available until payout details are finalized")
    line = next(
        (ln for ln in batch.get("lines") or [] if int(ln.get("id")) == int(line_id)),
        None,
    )
    if not line:
        raise ValueError("Line not found")
    details = line.get("payout_details") or parse_line_payout_details(line)
    if not can_generate_receipt_for_line(batch, details):
        raise ValueError("Payment receipt not available for this line")
    totals = line.get("payout_totals") or compute_line_totals(line, details)
    payment = details.get("payment") or {}
    settlement = details.get("settlement") or {}
    method = _payment_method_label(payment.get("method"))
    is_cash = payment_method_key(details) == "cash"
    user_meta = _user_display_meta(conn, line.get("user_id"))
    employee_id = user_meta.get("employee_id") or "—"
    prepared = _user_display_meta(conn, batch.get("payout_details_finalized_by"))
    confirmed = _user_display_meta(conn, batch.get("accountant_payment_confirmed_by"))
    notes = str(payment.get("notes") or payment.get("reference") or "").strip() or "—"
    from backend.veewash_branding import veewash_logo_img_html

    logo_html = veewash_logo_img_html(height_px=52)
    company_name = "WashPro Inc."

    gross = float(totals["gross_pay"])
    taxes_withheld = float(totals.get("amount_withheld") or 0)
    net_cash = float(
        payment.get("cash_amount") or totals.get("net_paid_to_employee") or totals["amount_paid"]
    )
    if is_cash and net_cash <= 0:
        net_cash = round(gross - taxes_withheld, 2)

    def row(label: str, val: str) -> str:
        return f"<tr><td>{label}</td><td>{val}</td></tr>"

    def money_row(label: str, amt: float) -> str:
        return f"<tr><td>{label}</td><td style='text-align:right'>${amt:,.2f}</td></tr>"

    title = "Cash Payment Receipt" if is_cash else "Payment Receipt"
    cash_fields = ""
    signature_block = ""
    if is_cash:
        cash_fields = f"""
<table>
{money_row('Gross pay', gross)}
{money_row('Taxes withheld', taxes_withheld)}
{money_row('Net cash received', net_cash)}
</table>
<table>
{row('Cash amount', f"${float(_money(payment.get('cash_amount') or net_cash)):,.2f}")}
{row('Date paid', str(payment.get('date') or '—'))}
{row('Paid by', str(payment.get('paid_by') or prepared.get('display_name') or '—'))}
{row('Receipt number', str(payment.get('receipt_number') or '—'))}
</table>"""
        sig_name = str(payment.get("employee_signature") or "").strip()
        signature_block = f"""
<p class="ack">I acknowledge receipt of the above cash payment.</p>
<p class="sig-line">Employee signature: {sig_name or '________________________'}</p>
<p class="sig-line">Date: ________________________</p>"""

    body_table = cash_fields if is_cash else f"""
<table>
{row('Employee', str(line.get('worker_name_snapshot') or '—'))}
{row('Employee ID', employee_id)}
{row('Pay period', f"{batch.get('pay_period_start')} – {batch.get('pay_period_end')}")}
{row('Approved hours', f"{float(line.get('approved_hours') or 0):.2f}")}
{row('Rate', f"${float(line.get('rate') or 0):,.2f}/hr")}
{row('Gross earnings', f"${gross:,.2f}")}
{row('Amount paid', f"${totals['amount_paid']:,.2f}")}
{row('Payment method', method)}
{row('Payment date', str(payment.get('date') or '—'))}
{row('Notes / reference', notes)}
</table>
<table>
{row('Prepared by', prepared.get('display_name') or '—')}
{row('Payment confirmed by', confirmed.get('display_name') or '—')}
</table>"""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title} — {line.get('worker_name_snapshot')}</title>
<style>
  body {{ font-family: system-ui, sans-serif; color: #0f172a; margin: 24px; }}
  h1 {{ color: #0097b2; font-size: 1.4rem; }}
  .meta {{ color: #475569; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
  td {{ padding: 6px 8px; border-bottom: 1px solid #e2e8f0; }}
  .brand {{ border-top: 3px solid #0097b2; padding-top: 12px; }}
  .brand-head {{ display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }}
  .notice {{ font-size: 0.85rem; color: #64748b; margin-top: 20px; }}
  .ack {{ margin-top: 28px; font-weight: 600; }}
  .sig-line {{ margin: 16px 0; }}
</style></head><body>
<div class="brand">
<div class="brand-head">{logo_html}<h1 style="margin:0">{company_name}</h1></div>
<p class="meta"><strong>{title}</strong></p>
<p class="meta">Employee: <strong>{line.get('worker_name_snapshot')}</strong><br>
Pay period: {batch.get('pay_period_start')} – {batch.get('pay_period_end')}</p>
{body_table}
{signature_block}
<p class="notice">{'Retain signed copy for payroll records.' if is_cash else 'Proof of manual payment — not a wage statement or official paystub.'}</p>
<p class="meta" style="margin-top:12px">Finalized {batch.get('payout_details_finalized_at')}</p>
</div>
</body></html>"""
    return html
