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
EMPLOYER_TAX_KEYS = ("er_ss", "er_medicare", "futa", "suta", "other")
PAYMENT_METHODS = ("direct_deposit", "check", "cash", "other")

ADMIN_OFFICER_ROLES = frozenset(
    {"ADMIN", "PAYROLL_ADMIN", "OPS", "OPERATIONS", "SUPERVISOR", "FINANCE"}
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
        },
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
    for k in EMPLOYEE_DEDUCTION_KEYS:
        base["employee_deductions"][k] = float(_money(base["employee_deductions"].get(k)))
    for k in EMPLOYER_TAX_KEYS:
        base["employer_taxes"][k] = float(_money(base["employer_taxes"].get(k)))
    for k in ("amount_paid", "amount_withheld", "outstanding_balance", "prior_unpaid_taxes"):
        base["settlement"][k] = float(_money(base["settlement"].get(k)))
    return base


def sum_employee_deductions(details: dict) -> float:
    ded = details.get("employee_deductions") or {}
    return float(sum(_money(ded.get(k)) for k in EMPLOYEE_DEDUCTION_KEYS))


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
    if outstanding == 0 and amount_paid > 0:
        outstanding = round(net - amount_paid - amount_withheld + prior_unpaid, 2)
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
    }


def enrich_line_with_payout_details(line: dict) -> dict:
    row = dict(line)
    details = parse_line_payout_details(row)
    totals = compute_line_totals(row, details)
    row["payout_details"] = json_safe(details)
    row["payout_totals"] = json_safe(totals)
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


def payout_workflow_state(batch: dict) -> dict[str, Any]:
    st = str(batch.get("status") or "")
    confirmed = batch.get("accountant_payment_confirmed_at")
    finalized = batch.get("payout_details_finalized_at")
    return json_safe(
        {
            "batch_status": st,
            "awaiting_accountant_confirmation": (
                st in ACCOUNTANT_QUEUE_STATUSES and not confirmed
            ),
            "accountant_payment_confirmed": bool(confirmed),
            "accountant_payment_confirmed_at": batch.get("accountant_payment_confirmed_at"),
            "accountant_payment_confirmed_by": batch.get("accountant_payment_confirmed_by"),
            "payout_details_finalized": bool(finalized),
            "payout_details_finalized_at": batch.get("payout_details_finalized_at"),
            "payout_details_finalized_by": batch.get("payout_details_finalized_by"),
            "paystub_available": bool(finalized),
            "can_edit_details": bool(confirmed) and not finalized,
        }
    )


def enrich_batch_payout_details(conn, organization_id: int, batch: dict) -> dict:
    from backend.payroll_workflow import enrich_payout_batch

    batch = enrich_payout_batch(conn, organization_id, batch)
    lines = [
        enrich_line_with_payout_details(ln) for ln in batch.get("lines") or []
    ]
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
    if not batch.get("accountant_payment_confirmed_at"):
        raise ValueError("Accountant must confirm payment before editing payout details")
    if batch.get("payout_details_finalized_at"):
        raise ValueError("Payout details are finalized — edits are locked")
    lines_patch = body.get("lines") or []
    if not lines_patch:
        raise ValueError("lines array required")
    c = conn.cursor()
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


def finalize_payout_details(
    conn, organization_id: int, batch_id: int, *, actor_id: int
) -> dict:
    ensure_payout_details_columns(conn.cursor())
    batch = get_payout_batch(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if not batch.get("accountant_payment_confirmed_at"):
        raise ValueError("Accountant payment confirmation required before finalize")
    if batch.get("payout_details_finalized_at"):
        raise ValueError("Payout details already finalized")
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
    totals = line.get("payout_totals") or compute_line_totals(line, details)
    ded = details.get("employee_deductions") or {}
    er = details.get("employer_taxes") or {}
    payment = details.get("payment") or {}
    settlement = details.get("settlement") or {}
    method_labels = {
        "direct_deposit": "Direct Deposit",
        "check": "Check",
        "cash": "Cash",
        "other": "Other",
    }
    method = method_labels.get(str(payment.get("method") or ""), payment.get("method") or "—")

    def row(label: str, amt: float) -> str:
        return f"<tr><td>{label}</td><td style='text-align:right'>${amt:,.2f}</td></tr>"

    ded_rows = "".join(
        row(k.upper().replace("OTHER", "Other "), float(ded.get(k) or 0))
        for k in EMPLOYEE_DEDUCTION_KEYS
        if float(ded.get(k) or 0) > 0
    )
    if not ded_rows:
        ded_rows = row("Total deductions", totals["total_employee_deductions"])

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Paystub — {line.get('worker_name_snapshot')}</title>
<style>
  body {{ font-family: system-ui, sans-serif; color: #0f172a; margin: 24px; }}
  h1 {{ color: #0097b2; font-size: 1.4rem; }}
  .meta {{ color: #475569; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
  th, td {{ padding: 6px 8px; border-bottom: 1px solid #e2e8f0; }}
  th {{ text-align: left; color: #007a91; }}
  .total {{ font-weight: 700; }}
  .brand {{ border-top: 3px solid #0097b2; padding-top: 12px; }}
</style></head><body>
<div class="brand">
<h1>VeeWash Paystub</h1>
<p class="meta"><strong>{line.get('worker_name_snapshot')}</strong><br>
Pay period: {batch.get('pay_period_start')} – {batch.get('pay_period_end')}<br>
Hours: {float(line.get('approved_hours') or 0):.2f} &nbsp; Rate: ${float(line.get('rate') or 0):,.2f}/hr</p>
<h2>Earnings</h2>
<table>
{row('Gross pay', totals['gross_pay'])}
</table>
<h2>Employee deductions</h2>
<table>{ded_rows}
<tr class="total"><td>Total deductions</td><td style="text-align:right">${totals['total_employee_deductions']:,.2f}</td></tr>
<tr class="total"><td>Net pay</td><td style="text-align:right">${totals['net_pay']:,.2f}</td></tr>
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
{row('Amount paid', totals['amount_paid'])}
{row('Amount withheld', totals['amount_withheld'])}
{row('Prior unpaid taxes', totals['prior_unpaid_taxes'])}
{row('Outstanding balance', totals['outstanding_balance'])}
</table>
<p class="meta" style="margin-top:24px">Finalized {batch.get('payout_details_finalized_at')}</p>
</div>
</body></html>"""
    return html
