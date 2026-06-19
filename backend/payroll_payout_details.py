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
    ("fit", "Federal Income Tax (FIT)"),
    ("ss", "Social Security"),
    ("medicare", "Medicare"),
    ("state", "State Tax"),
    ("local", "Local Tax"),
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


def can_view_finalized_paystub(conn, user_id: int, batch: dict) -> bool:
    from backend.ta_routes import user_has_perm

    if not batch.get("payout_details_finalized_at"):
        return False
    codes = user_role_codes(conn, user_id)
    if codes & VIEW_FINALIZED_ROLES:
        return True
    return user_has_perm(conn, user_id, "users.view")


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
        },
        "settlement": {
            "amount_paid": 0.0,
            "amount_withheld": 0.0,
            "outstanding_balance": 0.0,
            "prior_unpaid_taxes": 0.0,
            "prior_period_adjustment": 0.0,
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
    for section in ("employee_deductions", "employer_taxes", "payment", "settlement"):
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
    ):
        base["settlement"][k] = float(_money(base["settlement"].get(k)))
    return base


def sum_employee_deductions(details: dict) -> float:
    ded = details.get("employee_deductions") or {}
    return float(sum(_money(ded.get(k)) for k in EMPLOYEE_DEDUCTION_KEYS))


def compute_tax_withheld_breakdown(details: dict) -> dict[str, float]:
    """Employee tax withheld from payout_details_json (FIT through prior-period adjustment)."""
    ded = details.get("employee_deductions") or {}
    settlement = details.get("settlement") or {}
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
    }
    components["total_tax_withheld"] = round(sum(components.values()), 2)
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
        breakdown = compute_tax_withheld_breakdown(details)
        row["net_paid"] = float(_money(settlement.get("amount_paid")))
        row["tax_withheld"] = breakdown["total_tax_withheld"]
        row["tax_withheld_breakdown"] = json_safe(breakdown)
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
    gross = float(_money(line.get("gross_amount") or line.get("total_amount") or 0))
    emp_ded = sum_employee_deductions(details)
    er_tax = sum_employer_taxes(details)
    net = round(gross - emp_ded, 2)
    employer_cost = round(gross + er_tax, 2)
    settlement = details.get("settlement") or {}
    amount_paid = float(_money(settlement.get("amount_paid")))
    amount_withheld = float(_money(settlement.get("amount_withheld")))
    outstanding = float(_money(settlement.get("outstanding_balance")))
    prior_unpaid = float(_money(settlement.get("prior_unpaid_taxes")))
    prior_adj = float(_money(settlement.get("prior_period_adjustment")))
    if outstanding == 0 and amount_paid > 0:
        outstanding = round(net - amount_paid - amount_withheld + prior_unpaid + prior_adj, 2)
    return {
        "gross_pay": gross,
        "total_employee_deductions": emp_ded,
        "net_pay": net,
        "total_employer_taxes": er_tax,
        "employer_cost": employer_cost,
        "amount_paid": amount_paid,
        "amount_withheld": amount_withheld,
        "outstanding_balance": outstanding,
        "prior_unpaid_taxes": prior_unpaid,
        "prior_period_adjustment": prior_adj,
    }


def batch_document_mode(batch: dict) -> str:
    mode = str(batch.get("document_mode") or DEFAULT_DOCUMENT_MODE).strip().lower()
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


def can_generate_paystub_for_line(batch: dict, details: dict) -> bool:
    if not batch.get("payout_details_finalized_at"):
        return False
    return not line_uses_payment_receipt(batch, details)


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
    return str(batch.get("status") or "") in ACCOUNTANT_QUEUE_STATUSES


def payout_workflow_state(batch: dict) -> dict[str, Any]:
    st = str(batch.get("status") or "")
    confirmed = batch.get("accountant_payment_confirmed_at")
    finalized = batch.get("payout_details_finalized_at")
    doc_mode = batch_document_mode(batch)
    ready = batch_ready_for_payout_details(batch)
    lines = batch.get("lines") or []
    receipt_required_pending = False
    if ready and not finalized:
        for ln in lines:
            details = ln.get("payout_details") or parse_line_payout_details(ln)
            if receipt_required_for_line(details):
                settlement = details.get("settlement") or {}
                payment = details.get("payment") or {}
                if not settlement.get("amount_paid") or not payment.get("date"):
                    receipt_required_pending = True
                    break
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
            "payment_receipt_available": bool(finalized) and doc_mode == "payment_receipt",
            "receipt_required_pending": receipt_required_pending,
            "can_edit_details": ready and not finalized,
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
        out.append(json_safe(item))
    return out


def get_payout_batch_details(conn, organization_id: int, batch_id: int) -> Optional[dict]:
    batch = get_payout_batch(conn, organization_id, batch_id)
    if not batch:
        return None
    return enrich_batch_payout_details(conn, organization_id, batch)


def _merge_line_details(existing: dict, patch: dict) -> dict:
    base = parse_line_payout_details({"payout_details_json": existing})
    for section in ("employee_deductions", "employer_taxes", "payment", "settlement"):
        if section in patch and isinstance(patch[section], dict):
            for key, val in patch[section].items():
                if key in base[section]:
                    if section in ("employee_deductions", "employer_taxes", "settlement"):
                        base[section][key] = float(_money(val))
                    else:
                        base[section][key] = val
    if "use_payment_receipt" in patch:
        base["use_payment_receipt"] = bool(patch.get("use_payment_receipt"))
    if "employee_note" in patch:
        base["employee_note"] = str(patch.get("employee_note") or "").strip()
    return base


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
            SELECT payout_details_json FROM payout_batch_lines
            WHERE id=%s AND batch_id=%s AND organization_id=%s
            """,
            (int(line_id), int(batch_id), int(organization_id)),
        )
        row = c.fetchone()
        if not row:
            raise ValueError(f"Line {line_id} not found in batch")
        merged = _merge_line_details(
            _parse_json_blob(row[0] if not isinstance(row, dict) else row.get("payout_details_json")),
            item.get("payout_details") or item,
        )
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
    mode = batch_document_mode(batch)
    lines = batch.get("lines") or []
    for ln in lines:
        details = ln.get("payout_details") or parse_line_payout_details(ln)
        payment = details.get("payment") or {}
        settlement = details.get("settlement") or {}
        name = ln.get("worker_name_snapshot") or ln.get("id")
        if mode == "payment_receipt":
            if not payment.get("date"):
                raise ValueError(f"Payment date required for {name} in receipt mode")
            if not payment.get("method"):
                raise ValueError(f"Payment method required for {name} in receipt mode")
            if float(_money(settlement.get("amount_paid"))) <= 0:
                raise ValueError(f"Amount paid required for {name} in receipt mode")
        if receipt_required_for_line(details):
            if not payment.get("date"):
                raise ValueError(f"Payment date required for cash payment — {name}")
            if float(_money(settlement.get("amount_paid"))) <= 0:
                raise ValueError(f"Amount paid required for cash payment — {name}")


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


def generate_paystub_html(
    conn, organization_id: int, batch_id: int, line_id: int
) -> str:
    batch = get_payout_batch_details(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if not batch.get("payout_details_finalized_at"):
        raise ValueError("Paystub not available until payout details are finalized")
    line = next(
        (ln for ln in batch.get("lines") or [] if int(ln.get("id")) == int(line_id)),
        None,
    )
    if not line:
        raise ValueError("Line not found")
    details = line.get("payout_details") or parse_line_payout_details(line)
    if not can_generate_paystub_for_line(batch, details):
        raise ValueError("Official paystub not available for this payment — use payment receipt")
    totals = line.get("payout_totals") or compute_line_totals(line, details)
    er = details.get("employer_taxes") or {}
    payment = details.get("payment") or {}
    settlement = details.get("settlement") or {}
    method = _payment_method_label(payment.get("method"))
    gross = float(totals["gross_pay"])
    ded_rows, total_deductions = paystub_deduction_rows(details)
    net_pay = round(gross - total_deductions, 2)

    def money_row(label: str, amt: float) -> str:
        return f"<tr><td>{label}</td><td style='text-align:right'>${amt:,.2f}</td></tr>"

    ded_html = "".join(money_row(label, amt) for label, amt in ded_rows)

    er_label_map = {
        "er_ss": "ER SS",
        "er_medicare": "ER Medicare",
        "futa": "FUTA",
        "suta": "SUTA",
        "other": "Other",
    }
    er_rows = "".join(
        money_row(er_label_map.get(k, k), float(er.get(k) or 0))
        for k in EMPLOYER_TAX_KEYS
        if float(er.get(k) or 0) > 0
    )

    notes_html = _paystub_notes_html(batch, details)
    from backend.veewash_branding import veewash_logo_img_html

    logo_html = veewash_logo_img_html(height_px=52)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Paystub — {line.get('worker_name_snapshot')}</title>
<style>
  body {{ font-family: system-ui, sans-serif; color: #0f172a; margin: 24px; }}
  h1 {{ color: #0097b2; font-size: 1.4rem; }}
  h2 {{ color: #007a91; font-size: 1.05rem; margin-top: 18px; }}
  .meta {{ color: #475569; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
  th, td {{ padding: 6px 8px; border-bottom: 1px solid #e2e8f0; }}
  th {{ text-align: left; color: #007a91; }}
  .total {{ font-weight: 700; }}
  .brand {{ border-top: 3px solid #0097b2; padding-top: 12px; }}
  .brand-head {{ display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }}
  .internal {{ font-size: 0.85rem; color: #64748b; }}
  .notes p {{ white-space: pre-wrap; margin: 4px 0 12px; }}
</style></head><body>
<div class="brand">
<div class="brand-head">{logo_html}<h1 style="margin:0">VeeWash Official Paystub</h1></div>
<p class="meta"><strong>{line.get('worker_name_snapshot')}</strong><br>
Pay period: {batch.get('pay_period_start')} – {batch.get('pay_period_end')}<br>
Hours: {float(line.get('approved_hours') or 0):.2f} &nbsp; Rate: ${float(line.get('rate') or 0):,.2f}/hr</p>
<h2>Earnings</h2>
<table>
{money_row('Gross pay', gross)}
</table>
<h2>Employee Deductions</h2>
<table>{ded_html}
<tr class="total"><td>Total Deductions</td><td style="text-align:right">${total_deductions:,.2f}</td></tr>
<tr class="total"><td>Net pay</td><td style="text-align:right">${net_pay:,.2f}</td></tr>
</table>
<h2>Payment</h2>
<table>
<tr><td>Date</td><td>{payment.get('date') or '—'}</td></tr>
<tr><td>Method</td><td>{method}</td></tr>
<tr><td>Check #</td><td>{payment.get('check_number') or '—'}</td></tr>
<tr><td>Reference</td><td>{payment.get('reference') or '—'}</td></tr>
</table>
<h2>Settlement</h2>
<table>
{money_row('Amount paid', totals['amount_paid'])}
{money_row('Amount withheld', totals['amount_withheld'])}
{money_row('Prior unpaid taxes', totals['prior_unpaid_taxes'])}
{money_row('Outstanding balance', totals['outstanding_balance'])}
</table>
<h2 class="internal">Employer taxes (internal record)</h2>
<table class="internal">{er_rows or money_row('Total employer taxes', totals['total_employer_taxes'])}
<tr class="total"><td>Employer cost</td><td style='text-align:right'>${totals['employer_cost']:,.2f}</td></tr>
</table>
{f'<div class="notes">{notes_html}</div>' if notes_html else ''}
<p class="meta" style="margin-top:24px">Finalized {batch.get('payout_details_finalized_at')}</p>
</div>
</body></html>"""
    return html


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
    user_meta = _user_display_meta(conn, line.get("user_id"))
    employee_id = user_meta.get("employee_id") or "—"
    prepared = _user_display_meta(conn, batch.get("payout_details_finalized_by"))
    confirmed = _user_display_meta(conn, batch.get("accountant_payment_confirmed_by"))
    notes = str(payment.get("notes") or payment.get("reference") or "").strip() or "—"
    from backend.veewash_branding import veewash_logo_img_html

    logo_html = veewash_logo_img_html(height_px=52)

    def row(label: str, val: str) -> str:
        return f"<tr><td>{label}</td><td>{val}</td></tr>"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Payment Receipt — {line.get('worker_name_snapshot')}</title>
<style>
  body {{ font-family: system-ui, sans-serif; color: #0f172a; margin: 24px; }}
  h1 {{ color: #0097b2; font-size: 1.4rem; }}
  .meta {{ color: #475569; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
  td {{ padding: 6px 8px; border-bottom: 1px solid #e2e8f0; }}
  .brand {{ border-top: 3px solid #0097b2; padding-top: 12px; }}
  .brand-head {{ display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }}
  .notice {{ font-size: 0.85rem; color: #64748b; margin-top: 20px; }}
</style></head><body>
<div class="brand">
<div class="brand-head">{logo_html}<h1 style="margin:0">VeeWash Payment Receipt</h1></div>
<p class="meta">Proof of manual/cash payment — not a wage statement or official paystub.</p>
<table>
{row('Employee', str(line.get('worker_name_snapshot') or '—'))}
{row('Employee ID', employee_id)}
{row('Pay period', f"{batch.get('pay_period_start')} – {batch.get('pay_period_end')}")}
{row('Approved hours', f"{float(line.get('approved_hours') or 0):.2f}")}
{row('Rate', f"${float(line.get('rate') or 0):,.2f}/hr")}
{row('Gross earnings', f"${totals['gross_pay']:,.2f}")}
{row('Amount paid', f"${totals['amount_paid']:,.2f}")}
{row('Payment method', method)}
{row('Payment date', str(payment.get('date') or '—'))}
{row('Notes / reference', notes)}
</table>
<table>
{row('Prepared by', prepared.get('display_name') or '—')}
{row('Payment confirmed by', confirmed.get('display_name') or '—')}
</table>
<p class="notice">This receipt documents payment only. For W-2 periods with tax withholding, retain the official paystub as the wage statement.</p>
<p class="meta" style="margin-top:12px">Finalized {batch.get('payout_details_finalized_at')}</p>
</div>
</body></html>"""
    return html
