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
    ("fit", "FWT"),
    ("ss", "SS W/H"),
    ("medicare", "MC W/H"),
    ("state", "NY State Tax"),
    ("local", "NYC Resident Tax"),
    ("other2", "NY SDI"),
    ("other1", "NY PFML"),
)
PAYSTUB_EMPLOYER_TAX_LINES = (
    ("er_ss", "ER SS"),
    ("er_medicare", "ER MC"),
    ("futa", "FUTA"),
    ("suta", "NY SUTA"),
    ("ny_reemploy", "NY Re-employ"),
)
EMPLOYER_TAX_KEYS = ("er_ss", "er_medicare", "futa", "suta", "ny_reemploy", "other")
PAYMENT_METHODS = ("direct_deposit", "check", "cash", "zelle", "other")
DOCUMENT_MODES = ("payment_receipt", "official_paystub")
DEFAULT_DOCUMENT_MODE = "official_paystub"

PAYSTUB_LOGO_HEIGHT_PX = 40

ORG_WEBSITE_BY_SLUG = {
    "veewash": "www.veewash.com",
    "washpro": "www.washpro.com",
}

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
        # Phase 1: authoritative Pay Date for Monthly Payroll Paid (no historical backfill).
        ("official_pay_date", "DATE NULL"),
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
    from backend.payroll_vendors import ensure_payroll_vendor_tables

    ensure_payroll_vendor_tables(cursor)


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
            "withheld_from_payment": None,
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
        "show_tax_payment_section": True,
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
    if "show_tax_payment_section" in raw:
        base["show_tax_payment_section"] = bool(raw.get("show_tax_payment_section"))
    if "employee_note" in raw:
        base["employee_note"] = str(raw.get("employee_note") or "").strip()
    if isinstance(raw.get("vendor"), dict) and raw["vendor"].get("name"):
        v = raw["vendor"]
        base["vendor"] = {
            "id": v.get("id"),
            "name": v.get("name"),
            "address": v.get("address"),
            "logo_url": v.get("logo_url"),
        }
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
    if "withheld_from_payment" in base["settlement"]:
        wfp = base["settlement"].get("withheld_from_payment")
        if wfp is None or str(wfp).strip() == "":
            base["settlement"]["withheld_from_payment"] = None
        else:
            base["settlement"]["withheld_from_payment"] = float(_money(wfp))
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


def _effective_prior_tax_balance(prior_balance: float, prior_adj: float) -> float:
    """Prior-period adjustment credits against carryover prior balance (not added on top)."""
    return round(max(0.0, float(prior_balance) - float(prior_adj)), 2)


def _prior_collected_from_pay(settlement: dict) -> float:
    """Prior balance collected from this paycheck (catch-up field or partial prior-period adj.)."""
    catch_up = float(_money(settlement.get("catch_up_withholding")))
    if catch_up > 0:
        return round(catch_up, 2)
    prior_balance = float(_money(settlement.get("prior_unpaid_taxes")))
    prior_adj = float(_money(settlement.get("prior_period_adjustment")))
    if prior_adj <= 0:
        return 0.0
    return round(min(prior_adj, prior_balance), 2)


def _prior_still_owed(
    prior_balance: float,
    effective_prior: float,
    prior_adj: float,
    prior_collected: float,
) -> float:
    """Outstanding prior portion after adj. credit and/or catch-up collection."""
    if prior_adj > 0:
        return round(effective_prior, 2)
    if prior_collected > 0:
        return round(max(0.0, prior_balance - prior_collected), 2)
    return round(effective_prior, 2)


def reconcile_tax_summary(details: dict) -> dict:
    """Compute tax liability vs withheld amounts (catch-up is manager-entered only)."""
    ded = details.get("employee_deductions") or {}
    settlement = dict(details.get("settlement") or {})
    tax_summary = dict(details.get("tax_summary") or {})

    current_period = float(sum(_money(ded.get(k)) for k in EMPLOYEE_DEDUCTION_KEYS))
    prior_balance = float(_money(settlement.get("prior_unpaid_taxes")))
    prior_adj = float(_money(settlement.get("prior_period_adjustment")))
    effective_prior = _effective_prior_tax_balance(prior_balance, prior_adj)
    prior_collected = _prior_collected_from_pay(settlement)
    paid_full_gross = bool(settlement.get("paid_full_gross_without_withholding"))
    if paid_full_gross:
        settlement["catch_up_withholding"] = 0.0

    actual_withheld = float(_money(settlement.get("amount_withheld")))
    total_liability = round(current_period + effective_prior, 2)

    if paid_full_gross:
        period_balance = round(current_period, 2)
        prior_still = _prior_still_owed(
            prior_balance, effective_prior, prior_adj, prior_collected
        )
        remaining = round(prior_still + period_balance, 2)
    else:
        withheld_for_current = round(
            min(current_period, max(0.0, actual_withheld - prior_collected)),
            2,
        )
        period_balance = round(current_period - withheld_for_current, 2)
        prior_still = _prior_still_owed(
            prior_balance, effective_prior, prior_adj, prior_collected
        )
        remaining = round(prior_still + period_balance, 2)
    settlement["tax_balance_owed"] = period_balance

    tax_summary.update(
        {
            "current_period_taxes": current_period,
            "prior_tax_balance": prior_balance,
            "total_tax_liability": total_liability,
            "actual_tax_withheld": actual_withheld,
            "tax_balance_owed": period_balance,
            "remaining_balance": remaining,
            "tax_catch_up_adjustment": prior_collected,
        }
    )
    details["settlement"] = settlement
    details["tax_summary"] = tax_summary
    return details


def fetch_carryover_prior_tax_balance(
    conn,
    organization_id: int,
    user_id: int,
    *,
    exclude_batch_id: Optional[int] = None,
) -> float:
    """Remaining estimated tax balance from the employee's latest finalized payout line."""
    c = conn.cursor(dictionary=True)
    params: list[Any] = [int(organization_id), int(user_id)]
    exclude_sql = ""
    if exclude_batch_id is not None:
        exclude_sql = "AND pb.id <> %s"
        params.append(int(exclude_batch_id))
    c.execute(
        f"""
        SELECT pbl.payout_details_json
        FROM payout_batch_lines pbl
        JOIN payout_batches pb ON pb.id = pbl.batch_id
        WHERE pb.organization_id = %s
          AND pbl.user_id = %s
          AND pb.payout_details_finalized_at IS NOT NULL
          {exclude_sql}
        ORDER BY pb.payout_details_finalized_at DESC, pbl.id DESC
        LIMIT 1
        """,
        tuple(params),
    )
    row = c.fetchone()
    if not row:
        return 0.0
    raw = _parse_json_blob(row.get("payout_details_json"))
    tax_summary = raw.get("tax_summary") or {}
    settlement = raw.get("settlement") or {}
    remaining = float(tax_summary.get("remaining_balance") or 0)
    if remaining > 0:
        return round(remaining, 2)
    return round(float(settlement.get("tax_balance_owed") or 0), 2)


def apply_carryover_prior_tax_balance(
    conn,
    organization_id: int,
    batch_id: int,
    line: dict,
    details: dict,
) -> dict:
    """Default prior_unpaid_taxes from last finalized remaining balance when unset."""
    settlement = dict(details.get("settlement") or {})
    if float(_money(settlement.get("prior_unpaid_taxes"))) > 0:
        return details
    uid = line.get("user_id")
    if not uid:
        return details
    carry = fetch_carryover_prior_tax_balance(
        conn,
        organization_id,
        int(uid),
        exclude_batch_id=int(batch_id),
    )
    if carry <= 0:
        return details
    settlement["prior_unpaid_taxes"] = carry
    out = dict(details)
    out["settlement"] = settlement
    gross = float(_money(line.get("gross_amount") or line.get("total_amount") or 0))
    out = reconcile_tax_summary(out)
    if gross > 0:
        out = apply_settlement_math(out, gross)
    return out


def refresh_carryover_prior_tax_balances(
    conn,
    organization_id: int,
    batch_id: int,
    *,
    actor_id: int,
    line_ids: Optional[list[int]] = None,
) -> dict:
    """Replace stale prior_unpaid_taxes with each worker's latest finalized remaining balance."""
    ensure_payout_details_columns(conn.cursor())
    batch = get_payout_batch(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if not batch_ready_for_payout_details(batch):
        raise ValueError("Batch must be approved for payment before refreshing prior balances")
    if batch.get("payout_details_finalized_at"):
        raise ValueError("Payout details are finalized — prior balances are locked")

    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT id, user_id, worker_name_snapshot, gross_amount, total_amount, payout_details_json
        FROM payout_batch_lines
        WHERE batch_id=%s AND organization_id=%s
        """,
        (int(batch_id), int(organization_id)),
    )
    rows = c.fetchall() or []
    want = {int(x) for x in (line_ids or [])} if line_ids else None
    updater = conn.cursor()
    refreshed: list[dict[str, Any]] = []
    updated = 0

    for row in rows:
        lid = int(row["id"])
        if want is not None and lid not in want:
            continue
        uid = row.get("user_id")
        if not uid:
            continue
        carry = fetch_carryover_prior_tax_balance(
            conn,
            int(organization_id),
            int(uid),
            exclude_batch_id=int(batch_id),
        )
        details = parse_line_payout_details(row)
        settlement = dict(details.get("settlement") or {})
        old_prior = round(float(_money(settlement.get("prior_unpaid_taxes"))), 2)
        new_prior = round(float(carry), 2)
        if old_prior == new_prior:
            continue
        settlement["prior_unpaid_taxes"] = new_prior
        details["settlement"] = settlement
        gross = float(_money(row.get("gross_amount") or row.get("total_amount") or 0))
        details = reconcile_tax_summary(details)
        if gross > 0:
            details = apply_settlement_math(details, gross)
        updater.execute(
            """
            UPDATE payout_batch_lines SET payout_details_json=%s, updated_at=CURRENT_TIMESTAMP
            WHERE id=%s AND batch_id=%s AND organization_id=%s
            """,
            (
                json.dumps(details),
                lid,
                int(batch_id),
                int(organization_id),
            ),
        )
        refreshed.append(
            {
                "line_id": lid,
                "worker_name": str(row.get("worker_name_snapshot") or ""),
                "prior_before": old_prior,
                "prior_after": new_prior,
            }
        )
        updated += 1

    if updated:
        events = _audit_append(
            batch,
            "prior_balances_refreshed",
            actor_id,
            f"{updated} line(s)",
        )
        updater.execute(
            """
            UPDATE payout_batches SET payout_details_audit_json=%s, updated_at=CURRENT_TIMESTAMP
            WHERE id=%s AND organization_id=%s
            """,
            (json.dumps({"events": events}), int(batch_id), int(organization_id)),
        )
        conn.commit()

    out = get_payout_batch_details(conn, organization_id, batch_id) or {}
    out["prior_balance_refresh"] = {
        "updated": updated,
        "lines": refreshed,
    }
    return out


def _withheld_for_current_period(
    settlement: dict, current_period: float, *, paid_full_gross: bool
) -> float:
    """Current-period withholding taken from this pay (optional manual override)."""
    if paid_full_gross:
        return 0.0
    raw = settlement.get("withheld_from_payment")
    if raw is not None and str(raw).strip() != "":
        return round(min(float(_money(raw)), round(current_period, 2)), 2)
    prior_adj = float(_money(settlement.get("prior_period_adjustment")))
    if prior_adj > 0:
        return 0.0
    return round(current_period, 2)


def apply_settlement_math(details: dict, gross: float) -> dict:
    """Derive withheld and net pay from current taxes + optional catch-up withholding."""
    details = reconcile_tax_summary(dict(details))
    settlement = details.get("settlement") or {}
    tax_summary = details.get("tax_summary") or {}
    gross_f = float(_money(gross))
    current_period = float(tax_summary.get("current_period_taxes") or 0)
    paid_full_gross = bool(settlement.get("paid_full_gross_without_withholding"))

    if paid_full_gross:
        settlement["catch_up_withholding"] = 0.0
        settlement["withheld_from_payment"] = None
        withheld = 0.0
        paid = round(gross_f, 2)
    else:
        prior_collected = _prior_collected_from_pay(settlement)
        withheld_current = _withheld_for_current_period(
            settlement, current_period, paid_full_gross=False
        )
        withheld = round(withheld_current + prior_collected, 2)
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
        "ny_pfml": float(_money(ded.get("other1"))),
        "ny_sdi": float(_money(ded.get("other2"))),
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


# Categories whose finalized document is a vendor-branded Contractor Invoice &
# Payment Receipt (replaces the paystub entirely). W-2 keeps official paystubs.
VENDOR_RECEIPT_CATEGORIES = ("temp", "contractor_1099")


def batch_uses_vendor_receipt(batch: dict) -> bool:
    return str(batch.get("worker_category") or "") in VENDOR_RECEIPT_CATEGORIES


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
    # Temp/1099 never get a paystub — they get the vendor receipt instead.
    if batch_uses_vendor_receipt(batch):
        return False
    if line_uses_payment_receipt(batch, details):
        return False
    if preview:
        return batch_ready_for_payout_details(batch)
    return bool(batch.get("payout_details_finalized_at"))


def can_generate_vendor_receipt_for_line(
    batch: dict, details: dict, *, preview: bool = False
) -> bool:
    """Vendor receipt is the finalized document for temp/1099 (preview when ready)."""
    if not batch_uses_vendor_receipt(batch):
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
    uses_vendor_receipt = batch_uses_vendor_receipt(batch)
    if uses_vendor_receipt:
        effective = "vendor_receipt"
    elif line_uses_payment_receipt(batch, details):
        effective = "payment_receipt"
    else:
        effective = "official_paystub"
    vendor_snapshot = None
    if uses_vendor_receipt and isinstance(details, dict):
        v = details.get("vendor")
        if isinstance(v, dict) and v.get("name"):
            vendor_snapshot = json_safe(v)
    return json_safe(
        {
            "effective_type": effective,
            "receipt_available": can_generate_receipt_for_line(batch, details),
            "receipt_required": receipt_required_for_line(details),
            "paystub_available": can_generate_paystub_for_line(batch, details),
            "paystub_preview_available": can_generate_paystub_for_line(
                batch, details, preview=True
            ),
            "vendor_receipt_available": can_generate_vendor_receipt_for_line(batch, details),
            "vendor_receipt_preview_available": can_generate_vendor_receipt_for_line(
                batch, details, preview=True
            ),
            "vendor": vendor_snapshot,
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


def _format_organization_address(row: dict) -> list[str]:
    lines: list[str] = []
    street = str(row.get("employer_street") or row.get("address") or "").strip()
    apt = str(row.get("employer_apt") or "").strip()
    if street:
        lines.append(f"{street}, {apt}" if apt else street)
    city = str(row.get("employer_city") or "").strip()
    state = str(row.get("employer_state") or "").strip()
    zip_code = str(row.get("employer_zip") or "").strip()
    locality = ", ".join(p for p in [city, state] if p)
    if zip_code:
        locality = f"{locality} {zip_code}".strip()
    if locality:
        lines.append(locality)
    if not lines and row.get("address"):
        lines.append(str(row.get("address") or "").strip())
    return lines


def _format_us_phone_display(raw: str) -> str:
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    return str(raw or "").strip()


def _organization_website(row: dict) -> str:
    slug = str(row.get("slug") or "").lower()
    if slug in ORG_WEBSITE_BY_SLUG:
        return ORG_WEBSITE_BY_SLUG[slug]
    email = str(row.get("email") or "").strip()
    if "@" in email:
        domain = email.split("@", 1)[1].strip().lower()
        if domain and "." in domain:
            return domain
    return ""


def _organization_print_branding(conn, organization_id: int, *, logo_height_px: int = 52) -> dict[str, str]:
    """Company name, logo, and compact contact lines for payroll print documents."""
    c = conn.cursor(dictionary=True)
    base_cols = ["slug", "display_name"]
    optional_cols = [
        "logo_url",
        "address",
        "phone",
        "email",
        "employer_street",
        "employer_apt",
        "employer_city",
        "employer_state",
        "employer_zip",
    ]
    cols = list(base_cols)
    for col in optional_cols:
        if table_has_column(c, "organizations", col):
            cols.append(col)
    c.execute(
        f"SELECT {', '.join(cols)} FROM organizations WHERE id=%s LIMIT 1",
        (int(organization_id),),
    )
    row = c.fetchone() or {}
    slug = str(row.get("slug") or "").lower()
    company_name = str(row.get("display_name") or "").strip()
    if not company_name:
        company_name = {
            "veewash": "VeeWash",
            "washpro": "WashPro Inc.",
        }.get(slug, "Payroll")

    logo_url_raw = row.get("logo_url")
    from backend.org_logo_embed import organization_logo_img_html

    logo_html = organization_logo_img_html(
        int(organization_id),
        logo_url_raw,
        company_name,
        height_px=logo_height_px,
    )

    address_lines = _format_organization_address(row)
    phone = _format_us_phone_display(str(row.get("phone") or ""))
    website = _organization_website(row)

    return {
        "company_name": company_name,
        "logo_html": logo_html,
        "address_line": address_lines[0] if address_lines else "",
        "address_line2": address_lines[1] if len(address_lines) > 1 else "",
        "phone_display": phone,
        "website": website,
        "contact_line": " • ".join(p for p in [phone, website] if p),
    }


def _payment_method_label(method: str) -> str:
    key = str(method or "").strip().lower()
    return PAYMENT_METHOD_LABELS.get(key, method or "—")


def enrich_line_with_payout_details(
    line: dict,
    batch: Optional[dict] = None,
    *,
    conn: Optional[Any] = None,
    organization_id: Optional[int] = None,
    batch_id: Optional[int] = None,
) -> dict:
    row = dict(line)
    details = parse_line_payout_details(row)
    if (
        conn is not None
        and organization_id is not None
        and batch_id is not None
        and batch
        and not batch.get("payout_details_finalized_at")
    ):
        details = apply_carryover_prior_tax_balance(
            conn, int(organization_id), int(batch_id), row, details
        )
    totals = compute_line_totals(row, details)
    row["payout_details"] = json_safe(details)
    row["payout_totals"] = json_safe(totals)
    if batch:
        row = enrich_line_settlement_fields(row, batch)
        row["document"] = line_document_state(batch, row, details)
        if (
            batch_uses_vendor_receipt(batch)
            and conn is not None
            and organization_id is not None
        ):
            try:
                from backend.payroll_vendors import resolve_line_vendor

                row["vendor"] = resolve_line_vendor(
                    conn, int(organization_id), row, batch
                )
            except Exception:  # pragma: no cover - vendor resolution is best-effort
                row["vendor"] = None
    return json_safe(row)


def _audit_append(
    batch: dict,
    event: str,
    actor_id: int,
    detail: str = "",
    *,
    old_value: Any = None,
    new_value: Any = None,
    reason: str = "",
) -> list:
    audit = _parse_json_blob(batch.get("payout_details_audit_json"))
    events = audit.get("events") if isinstance(audit.get("events"), list) else []
    entry: dict[str, Any] = {
        "event": event,
        "actor_id": int(actor_id),
        "at": datetime.utcnow().isoformat(timespec="seconds"),
        "detail": detail,
    }
    if old_value is not None or new_value is not None:
        entry["old_value"] = old_value
        entry["new_value"] = new_value
    if reason:
        entry["reason"] = str(reason).strip()
    events.append(entry)
    return events


def _parse_official_pay_date(raw: Any) -> Optional[str]:
    """Return YYYY-MM-DD or None. Never invents a date from period end."""
    if raw is None:
        return None
    if hasattr(raw, "isoformat"):
        try:
            return raw.isoformat()[:10]
        except Exception:
            return None
    s = str(raw).strip()[:10]
    if not s:
        return None
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None
    return s


def batch_official_pay_date(batch: dict) -> Optional[str]:
    return _parse_official_pay_date(batch.get("official_pay_date"))


def batch_pay_date_missing(batch: dict) -> bool:
    return batch_official_pay_date(batch) is None


def suggested_pay_date_for_ui(batch: dict) -> Optional[str]:
    """Suggestion only — never treated as a confirmed official Pay Date."""
    pe = batch.get("pay_period_end") or batch.get("pay_period_start")
    return _parse_official_pay_date(pe)


def compute_batch_finalize_cost_summary(batch: dict, lines: Optional[list] = None) -> dict:
    """Gross / net / stored employer taxes / total payroll cost for finalize confirmation.

    Total Payroll Cost = Gross + stored employer-side taxes only (no invented burdens).
    Employee withholding is not added on top of gross.
    """
    rows = lines if lines is not None else (batch.get("lines") or [])
    employee_count = len(rows)
    gross_total = 0.0
    net_total = 0.0
    employer_total = 0.0
    for ln in rows:
        details = ln.get("payout_details") or parse_line_payout_details(ln)
        totals = ln.get("payout_totals") or compute_line_totals(ln, details)
        if isinstance(totals, dict):
            gross_total += float(_money(totals.get("gross_pay")))
            net_total += float(
                _money(totals.get("net_paid_to_employee") or totals.get("net_pay"))
            )
            employer_total += float(_money(totals.get("total_employer_taxes")))
        else:
            gross_total += float(_money(ln.get("gross_amount") or ln.get("total_amount")))
            er = details.get("employer_taxes") or {}
            if isinstance(er, dict):
                employer_total += sum(float(_money(v)) for v in er.values())
    gross_total = round(gross_total, 2)
    net_total = round(net_total, 2)
    employer_total = round(employer_total, 2)
    return {
        "employee_count": employee_count,
        "gross_pay": gross_total,
        "net_pay": net_total,
        "employer_taxes": employer_total,
        "total_payroll_cost": round(gross_total + employer_total, 2),
        "pay_period_start": str(batch.get("pay_period_start") or "")[:10],
        "pay_period_end": str(batch.get("pay_period_end") or "")[:10],
        "official_pay_date": batch_official_pay_date(batch),
        "suggested_pay_date": suggested_pay_date_for_ui(batch),
        "pay_date_missing": batch_pay_date_missing(batch),
        "pay_date_note": (
            "The Pay Date determines which monthly payroll report this batch appears in."
        ),
    }


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
    can_unfinalize = can_unfinalize_payout_details(batch)
    opd = batch_official_pay_date(batch)
    return json_safe(
        {
            "batch_status": st,
            "awaiting_accountant_confirmation": (
                st == "approved_for_payment" and not confirmed and bool(finalized)
            ),
            "accountant_payment_confirmed": bool(confirmed),
            "accountant_payment_confirmed_at": batch.get("accountant_payment_confirmed_at"),
            "accountant_payment_confirmed_by": batch.get("accountant_payment_confirmed_by"),
            "payout_details_finalized": bool(finalized),
            "payout_details_finalized_at": batch.get("payout_details_finalized_at"),
            "payout_details_finalized_by": batch.get("payout_details_finalized_by"),
            "document_mode": doc_mode,
            "can_set_document_mode": ready and not finalized,
            "uses_vendor_receipt": batch_uses_vendor_receipt(batch),
            "paystub_available": (
                bool(finalized)
                and doc_mode == "official_paystub"
                and not batch_uses_vendor_receipt(batch)
            ),
            "paystub_preview_available": (
                ready
                and doc_mode == "official_paystub"
                and not batch_uses_vendor_receipt(batch)
            ),
            "vendor_receipt_available": bool(finalized) and batch_uses_vendor_receipt(batch),
            "vendor_receipt_preview_available": ready and batch_uses_vendor_receipt(batch),
            "payment_receipt_available": bool(finalized) and doc_mode == "payment_receipt",
            "receipt_required_pending": receipt_required_pending,
            "can_edit_details": ready and not finalized,
            "can_finalize": can_finalize,
            "can_unfinalize": can_unfinalize,
            "finalize_blockers": finalize_blockers_list,
            "official_pay_date": opd,
            "pay_date_missing": opd is None,
            "pay_date_status": "set" if opd else "missing",
            "suggested_pay_date": suggested_pay_date_for_ui(batch),
            "can_correct_official_pay_date": bool(finalized),
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
        lines.append(
            enrich_line_with_payout_details(
                row,
                batch,
                conn=conn,
                organization_id=int(organization_id),
                batch_id=int(batch.get("id") or 0),
            )
        )
    batch["lines"] = lines
    batch["payout_workflow"] = payout_workflow_state(batch)
    batch["official_pay_date"] = batch_official_pay_date(batch)
    batch["pay_date_missing"] = batch_pay_date_missing(batch)
    batch["pay_date_status"] = "set" if batch["official_pay_date"] else "missing"
    batch["suggested_pay_date"] = suggested_pay_date_for_ui(batch)
    batch["finalize_cost_summary"] = compute_batch_finalize_cost_summary(batch, lines)
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
        "suta": round(
            float(calc.get("ny_suta_estimate") or 0)
            - float(calc.get("ny_reemployment_estimate") or 0),
            2,
        ),
        "ny_reemploy": float(calc.get("ny_reemployment_estimate") or 0),
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
                    elif section == "settlement" and key == "withheld_from_payment":
                        if val is None or str(val).strip() == "":
                            base[section][key] = None
                        else:
                            base[section][key] = float(_money(val))
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
    if "show_tax_payment_section" in patch:
        base["show_tax_payment_section"] = bool(patch.get("show_tax_payment_section"))
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


def _persist_line_vendor_snapshots(
    conn,
    organization_id: int,
    batch_id: int,
    batch: dict,
    lines: list[dict],
) -> int:
    """Freeze the resolved vendor branding onto each temp/1099 line before finalize."""
    if not batch_uses_vendor_receipt(batch):
        return 0
    from backend.payroll_vendors import (
        resolve_line_vendor,
        vendor_snapshot_for_finalize,
    )

    c = conn.cursor()
    updated = 0
    for ln in lines:
        details = ln.get("payout_details") or parse_line_payout_details(ln)
        if isinstance(details.get("vendor"), dict) and details["vendor"].get("name"):
            continue  # already snapshotted
        vendor = resolve_line_vendor(conn, int(organization_id), ln, batch)
        snapshot = vendor_snapshot_for_finalize(vendor)
        if not snapshot:
            continue
        merged = dict(details)
        merged["vendor"] = snapshot
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
        if "vendor_id" in item and batch_uses_vendor_receipt(batch):
            from backend.payroll_vendors import ensure_payroll_vendor_tables, get_vendor

            ensure_payroll_vendor_tables(c)
            raw_vendor = item.get("vendor_id")
            vendor_val = None
            if raw_vendor not in (None, "", "null"):
                v = get_vendor(conn, int(organization_id), int(raw_vendor))
                if not v:
                    raise ValueError("Vendor not found")
                vendor_val = int(raw_vendor)
            c.execute(
                """
                UPDATE payout_batch_lines SET vendor_id=%s, updated_at=CURRENT_TIMESTAMP
                WHERE id=%s AND batch_id=%s AND organization_id=%s
                """,
                (vendor_val, int(line_id), int(batch_id), int(organization_id)),
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


def _validate_finalize_batch(batch: dict, *, official_pay_date: Optional[str] = None) -> None:
    blockers = finalize_blockers(batch, batch.get("lines") or [])
    if not _parse_official_pay_date(official_pay_date or batch.get("official_pay_date")):
        blockers = [
            "Official Pay Date is required to finalize. "
            "Confirm the date employees are actually paid."
        ] + blockers
    if blockers:
        raise ValueError(blockers[0])


def finalize_payout_details(
    conn,
    organization_id: int,
    batch_id: int,
    *,
    actor_id: int,
    official_pay_date: Optional[str] = None,
    confirm_pay_date: bool = False,
) -> dict:
    ensure_payout_details_columns(conn.cursor())
    batch = get_payout_batch(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if not batch_ready_for_payout_details(batch):
        raise ValueError("Batch must be approved for payment before finalize")
    if batch.get("payout_details_finalized_at"):
        raise ValueError("Payout details already finalized")
    pay_date = _parse_official_pay_date(official_pay_date)
    if not pay_date:
        raise ValueError(
            "Official Pay Date is required to finalize. "
            "Confirm the date employees are actually paid."
        )
    if not confirm_pay_date:
        raise ValueError(
            "Confirm the Official Pay Date explicitly before finalizing. "
            "A suggested date is not applied automatically."
        )
    enriched = get_payout_batch_details(conn, organization_id, batch_id) or {}
    changed = _persist_line_payment_defaults(
        conn,
        organization_id,
        batch_id,
        enriched,
        enriched.get("lines") or [],
    )
    changed += _persist_line_vendor_snapshots(
        conn,
        organization_id,
        batch_id,
        enriched,
        enriched.get("lines") or [],
    )
    if changed:
        conn.commit()
    enriched = get_payout_batch_details(conn, organization_id, batch_id) or {}
    _validate_finalize_batch(enriched, official_pay_date=pay_date)
    events = _audit_append(
        batch,
        "payout_details_finalized",
        actor_id,
        detail=f"official_pay_date={pay_date}",
        old_value=batch_official_pay_date(batch),
        new_value=pay_date,
        reason="finalization",
    )
    events = _audit_append(
        {**batch, "payout_details_audit_json": json.dumps({"events": events})},
        "official_pay_date_set",
        actor_id,
        detail="Set at finalization",
        old_value=None,
        new_value=pay_date,
        reason="finalization",
    )
    c = conn.cursor()
    c.execute(
        """
        UPDATE payout_batches SET
          official_pay_date=%s,
          payout_details_finalized_at=NOW(),
          payout_details_finalized_by=%s,
          payout_details_audit_json=%s,
          updated_at=CURRENT_TIMESTAMP
        WHERE id=%s AND organization_id=%s
        """,
        (
            pay_date,
            int(actor_id),
            json.dumps({"events": events}),
            int(batch_id),
            int(organization_id),
        ),
    )
    conn.commit()
    return get_payout_batch_details(conn, organization_id, batch_id) or {}


def set_official_pay_date(
    conn,
    organization_id: int,
    batch_id: int,
    *,
    actor_id: int,
    official_pay_date: str,
    reason: str,
) -> dict:
    """Assign or correct batch official_pay_date. Affects report membership only."""
    ensure_payout_details_columns(conn.cursor())
    batch = get_payout_batch(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if not batch.get("payout_details_finalized_at"):
        raise ValueError(
            "Official Pay Date for unfinalized batches is set during finalization"
        )
    pay_date = _parse_official_pay_date(official_pay_date)
    if not pay_date:
        raise ValueError("A valid Official Pay Date (YYYY-MM-DD) is required")
    reason_s = str(reason or "").strip()
    if len(reason_s) < 3:
        raise ValueError("A reason is required when setting or correcting Official Pay Date")
    old = batch_official_pay_date(batch)
    if old == pay_date:
        return get_payout_batch_details(conn, organization_id, batch_id) or {}
    event_name = "official_pay_date_corrected" if old else "official_pay_date_set"
    events = _audit_append(
        batch,
        event_name,
        actor_id,
        detail="Report membership only; wages/taxes unchanged",
        old_value=old,
        new_value=pay_date,
        reason=reason_s,
    )
    c = conn.cursor()
    c.execute(
        """
        UPDATE payout_batches SET
          official_pay_date=%s,
          payout_details_audit_json=%s,
          updated_at=CURRENT_TIMESTAMP
        WHERE id=%s AND organization_id=%s
        """,
        (
            pay_date,
            json.dumps({"events": events}),
            int(batch_id),
            int(organization_id),
        ),
    )
    conn.commit()
    return get_payout_batch_details(conn, organization_id, batch_id) or {}

def can_unfinalize_payout_details(batch: dict) -> bool:
    """Allow reopening finalized payout details for corrections (same readiness as edit)."""
    if not batch.get("payout_details_finalized_at"):
        return False
    return batch_ready_for_payout_details(batch)


def unfinalize_payout_details(
    conn, organization_id: int, batch_id: int, *, actor_id: int
) -> dict:
    ensure_payout_details_columns(conn.cursor())
    batch = get_payout_batch(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if not batch.get("payout_details_finalized_at"):
        raise ValueError("Payout details are not finalized")
    if not can_unfinalize_payout_details(batch):
        raise ValueError("Batch is not in a state that allows reopening payout details")
    events = _audit_append(batch, "payout_details_unfinalized", actor_id)
    c = conn.cursor()
    c.execute(
        """
        UPDATE payout_batches SET
          payout_details_finalized_at=NULL,
          payout_details_finalized_by=NULL,
          payout_details_audit_json=%s,
          updated_at=CURRENT_TIMESTAMP
        WHERE id=%s AND organization_id=%s
        """,
        (
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
    rows: list[tuple[str, float]] = []
    for key, label in PAYSTUB_DEDUCTION_LINES:
        rows.append((label, float(_money(ded.get(key)))))
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
  * { box-sizing: border-box; }
  body { font-family: system-ui, -apple-system, sans-serif; color: #0f172a; margin: 0; padding: 20px 24px; font-size: 9.5px; line-height: 1.35; background: #f1f5f9; }
  h1 { color: #0097b2; font-size: 1rem; margin: 0; }
  h2 { color: #007a91; font-size: 0.82rem; margin: 8px 0 4px; font-weight: 700; }
  .meta { color: #475569; margin: 4px 0 8px; font-size: 9px; }
  table.compact { width: 100%; border-collapse: collapse; margin: 4px 0 8px; table-layout: fixed; }
  table.compact th, table.compact td { padding: 6px 12px; border-bottom: 1px solid #e2e8f0; vertical-align: top; }
  table.compact th { text-align: left; color: #007a91; font-size: 9px; font-weight: 600; }
  table.compact td:first-child, table.compact th:first-child { width: 58%; padding-left: 12px; }
  table.compact td:last-child, table.compact th:last-child { width: 42%; text-align: right; padding-right: 12px; }
  table.compact td.amount, table.compact th.amount { text-align: right; white-space: nowrap; }
  table.compact tr.total td { font-weight: 700; border-top: 1px solid #cbd5e1; }
  .paystub-sheet {
    page-break-after: always;
    max-height: 10.2in;
    overflow: hidden;
    padding: 28px 32px;
    margin: 0 auto 18px;
    max-width: 7.5in;
    background: #fff;
    border-radius: 12px;
    border: 1px solid #e2e8f0;
    box-shadow: 0 4px 18px rgba(15, 23, 42, 0.08);
  }
  .paystub-sheet:last-child { page-break-after: auto; margin-bottom: 0; }
  .copy-badge { font-size: 8.5px; font-weight: 700; letter-spacing: 0.05em; color: #64748b; margin-bottom: 6px; }
  .preview-banner { background: #fef3c7; color: #92400e; padding: 6px 10px; border-radius: 6px; margin-bottom: 8px; font-size: 9px; }
  .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 16px; margin: 6px 0 10px; font-size: 9.5px; }
  .info-grid dt { color: #64748b; font-size: 9px; }
  .info-grid dd { margin: 0 0 4px; font-weight: 600; }
  .note-box { font-size: 8.5px; color: #64748b; margin: 6px 0; padding: 8px 10px; background: #f8fafc; border-radius: 6px; }
  .brand-head { display: flex; align-items: center; margin-bottom: 8px; padding: 10px 14px; border-top: 3px solid #0097b2; background: #f0fdfa; border-radius: 8px; }
  .brand-logo-wrap { flex-shrink: 0; padding: 2px 0; margin-right: 14px; }
  .paystub-logo { height: 44px; width: auto; display: block; }
  .brand-text { flex: 1; min-width: 0; }
  .company-name { font-size: 1.02rem; font-weight: 700; color: #0f766e; line-height: 1.2; }
  .brand-contact-line { font-size: 8.5px; color: #64748b; margin: 1px 0 0; line-height: 1.35; }
  .brand-contact-line .sep { color: #94a3b8; margin: 0 5px; }
  .doc-title-row { margin: 8px 0 6px; padding-bottom: 4px; border-bottom: 1px solid #e2e8f0; }
  .doc-title { color: #0097b2; font-size: 0.78rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; }
  table.compact.ytd th.col-current, table.compact.ytd td.col-current { width: 18%; text-align: right; padding-right: 8px; }
  table.compact.ytd th.col-ytd, table.compact.ytd td.col-ytd { width: 18%; text-align: right; padding-right: 4px; }
  table.compact.ytd td:first-child, table.compact.ytd th:first-child { width: 64%; padding-left: 12px; }
  .cash-receipt { margin-top: 8px; padding: 10px 12px; border: 1px dashed #94a3b8; border-radius: 4px; font-size: 9px; }
  .cash-receipt h2 { margin: 0 0 6px; font-size: 0.8rem; }
  .cash-receipt .row { margin: 4px 0; }
  .cash-receipt .ack { margin-top: 8px; font-size: 8.5px; color: #475569; }
  .sig-field { margin-bottom: 14px; }
  .sig-line { margin: 0; border-bottom: 1px solid #334155; }
  .sig-line-large { min-height: 40px; }
  .sig-line-date { min-height: 28px; max-width: 55%; }
  .sig-label { font-size: 8px; color: #64748b; margin-top: 4px; }
  .employee-meta { margin: 4px 0 10px; font-size: 9.5px; color: #334155; }
  .internal { font-size: 8.5px; color: #64748b; margin: 2px 0; }
  .notes p { white-space: pre-wrap; margin: 2px 0 4px; font-size: 9px; }
  .employee-paystub-group { margin-top: 8px; }
  .employee-paystub-group .employee-name {
    font-size: 1.05rem; margin: 14px 0 8px; color: #0f766e;
    border-bottom: 2px solid #0097b2; padding-bottom: 4px;
  }
  .archive-intro { color: #475569; font-size: 9px; margin: 4px 0 10px; }
"""


def _paystub_money_row(label: str, amt: float, bold: bool = False) -> str:
    cls = " class='total'" if bold else ""
    return (
        f"<tr{cls}><td>{label}</td>"
        f"<td class='amount'>${amt:,.2f}</td></tr>"
    )


def _paystub_ytd_money_row(
    label: str, current: float, ytd: float, *, bold: bool = False
) -> str:
    cls = " class='total'" if bold else ""
    ytd_cell = "—" if ytd is None else f"${float(ytd):,.2f}"
    return (
        f"<tr{cls}><td>{label}</td>"
        f"<td class='col-current amount'>${current:,.2f}</td>"
        f"<td class='col-ytd amount'>{ytd_cell}</td></tr>"
    )


def _paystub_ytd_table_head() -> str:
    return (
        "<tr><th>Description</th>"
        "<th class='col-current amount'>Current</th>"
        "<th class='col-ytd amount'>YTD</th></tr>"
    )


def _empty_paystub_ytd() -> dict[str, float]:
    return {
        "gross_pay": 0.0,
        "fit": 0.0,
        "ss": 0.0,
        "medicare": 0.0,
        "state": 0.0,
        "local": 0.0,
        "other1": 0.0,
        "other2": 0.0,
        "total_employee_deductions": 0.0,
        "net_pay": 0.0,
        "amount_paid": 0.0,
    }


def _line_paystub_ytd_components(line: dict, details: dict, totals: dict) -> dict[str, float]:
    ded = details.get("employee_deductions") or {}
    return {
        "gross_pay": float(totals.get("gross_pay") or 0),
        "fit": float(_money(ded.get("fit"))),
        "ss": float(_money(ded.get("ss"))),
        "medicare": float(_money(ded.get("medicare"))),
        "state": float(_money(ded.get("state"))),
        "local": float(_money(ded.get("local"))),
        "other1": float(_money(ded.get("other1"))),
        "other2": float(_money(ded.get("other2"))),
        "total_employee_deductions": float(totals.get("total_employee_deductions") or 0),
        "net_pay": float(totals.get("net_pay") or 0),
        "amount_paid": float(
            totals.get("net_paid_to_employee") or totals.get("amount_paid") or 0
        ),
    }


def _add_paystub_ytd(accum: dict[str, float], components: dict[str, float]) -> dict[str, float]:
    out = dict(accum)
    for key in out:
        out[key] = round(out[key] + float(components.get(key) or 0), 2)
    return out


def _paystub_year_from_batch(batch: dict, line: dict, payment: dict) -> int:
    for raw in (
        batch.get("pay_period_end"),
        batch.get("pay_period_start"),
        payment.get("date"),
        line.get("payment_date"),
    ):
        if raw:
            try:
                return int(str(raw)[:4])
            except (TypeError, ValueError):
                continue
    return datetime.utcnow().year


def fetch_finalized_paystub_ytd(
    conn,
    organization_id: int,
    user_id: int,
    year: int,
    pay_period_end: str,
    *,
    current_batch_id: Optional[int] = None,
    exclude_line_id: Optional[int] = None,
) -> dict[str, float]:
    """Sum YTD from prior finalized pay periods in the same calendar year (pay-period based)."""
    c = conn.cursor(dictionary=True)
    period_end = str(pay_period_end or "")[:10]
    batch_id = int(current_batch_id or 0)
    params: list[Any] = [
        int(organization_id),
        int(user_id),
        int(year),
        period_end,
        period_end,
        batch_id,
    ]
    exclude_sql = ""
    if exclude_line_id is not None:
        exclude_sql = "AND pbl.id <> %s"
        params.append(int(exclude_line_id))
    c.execute(
        f"""
        SELECT pbl.gross_amount, pbl.total_amount, pbl.payout_details_json
        FROM payout_batch_lines pbl
        JOIN payout_batches pb ON pb.id = pbl.batch_id
        WHERE pb.organization_id = %s
          AND pbl.user_id = %s
          AND pb.worker_category = 'w2'
          AND pb.payout_details_finalized_at IS NOT NULL
          AND YEAR(pb.pay_period_end) = %s
          AND (
            pb.pay_period_end < %s
            OR (pb.pay_period_end = %s AND pb.id < %s)
          )
          {exclude_sql}
        ORDER BY pb.pay_period_end, pb.id, pbl.id
        """,
        tuple(params),
    )
    ytd = _empty_paystub_ytd()
    for row in c.fetchall() or []:
        ln = {
            "gross_amount": row.get("gross_amount"),
            "total_amount": row.get("total_amount"),
            "payout_details_json": row.get("payout_details_json"),
        }
        details = parse_line_payout_details(ln)
        totals = compute_line_totals(ln, details)
        ytd = _add_paystub_ytd(ytd, _line_paystub_ytd_components(ln, details, totals))
    return ytd


def compute_paystub_ytd(
    conn,
    organization_id: int,
    batch: dict,
    line: dict,
    details: dict,
    totals: dict,
) -> dict[str, float]:
    payment = details.get("payment") or {}
    year = _paystub_year_from_batch(batch, line, payment)
    uid = line.get("user_id")
    if not uid or not conn:
        return _add_paystub_ytd(
            _empty_paystub_ytd(),
            _line_paystub_ytd_components(line, details, totals),
        )
    ytd = fetch_finalized_paystub_ytd(
        conn,
        int(organization_id),
        int(uid),
        year,
        str(batch.get("pay_period_end") or "")[:10],
        current_batch_id=int(batch.get("id") or 0),
        exclude_line_id=int(line.get("id") or 0) or None,
    )
    return _add_paystub_ytd(
        ytd,
        _line_paystub_ytd_components(line, details, totals),
    )


def _paystub_brand_head_html(branding: dict[str, str], doc_title: str) -> str:
    address_parts = []
    if branding.get("address_line"):
        address_parts.append(str(branding["address_line"]))
    if branding.get("address_line2"):
        address_parts.append(str(branding["address_line2"]))
    address_html = ""
    if address_parts:
        address_html = f"<div class='brand-contact-line'>{' • '.join(address_parts)}</div>"

    contact_bits = []
    if branding.get("phone_display"):
        contact_bits.append(f"<span>{branding['phone_display']}</span>")
    if branding.get("website"):
        contact_bits.append(f"<span>{branding['website']}</span>")
    contact_html = ""
    if contact_bits:
        contact_html = (
            "<div class='brand-contact-line'>"
            + "<span class='sep'>•</span>".join(contact_bits)
            + "</div>"
        )

    return f"""
<div class="brand-head">
<div class="brand-logo-wrap">{branding.get("logo_html") or ""}</div>
<div class="brand-text">
<div class="company-name">{branding.get("company_name") or ""}</div>
{address_html}
{contact_html}
</div>
</div>
<div class="doc-title-row"><span class="doc-title">{doc_title}</span></div>"""


def _employee_earnings_ytd_html(
    hours: float,
    rate: float,
    gross: float,
    ytd: dict[str, float],
    *,
    line: Optional[dict] = None,
) -> str:
    from backend.payroll_overtime import earnings_breakdown_from_line

    breakdown = None
    if line is not None:
        breakdown = earnings_breakdown_from_line(
            {
                **line,
                "gross_amount": gross,
                "approved_hours": line.get("approved_hours", hours),
                "rate": line.get("rate", rate),
            }
        )
    if breakdown and float(breakdown.get("ot_hours") or 0) > 0:
        return f"""
<h2>Earnings</h2>
<table class="compact ytd">
{_paystub_ytd_table_head()}
<tr><td>Regular hours</td><td class="col-current amount">{breakdown['regular_hours']:.2f}</td><td class="col-ytd amount">—</td></tr>
<tr><td>OT hours</td><td class="col-current amount">{breakdown['ot_hours']:.2f}</td><td class="col-ytd amount">—</td></tr>
<tr><td>Hourly rate</td><td class="col-current amount">${rate:,.2f}</td><td class="col-ytd amount">—</td></tr>
{_paystub_ytd_money_row("Regular/Base earnings", breakdown["base_earnings"], None)}
{_paystub_ytd_money_row("OT premium", breakdown["ot_premium"], None)}
{_paystub_ytd_money_row("Other earnings", breakdown["other_earnings"], None) if float(breakdown.get("other_earnings") or 0) else ""}
{_paystub_ytd_money_row("Gross pay", gross, ytd["gross_pay"], bold=True)}
</table>
<p class="note" style="font-size:0.8rem;color:#64748b;margin-top:6px">
OT Premium represents only the additional amount paid above the employee’s regular hourly rate.
Regular/Base earnings include overtime hours at the regular rate.
</p>"""
    return f"""
<h2>Earnings</h2>
<table class="compact ytd">
{_paystub_ytd_table_head()}
<tr><td>Hours worked</td><td class="col-current amount">{hours:.2f}</td><td class="col-ytd amount">—</td></tr>
<tr><td>Hourly rate</td><td class="col-current amount">${rate:,.2f}</td><td class="col-ytd amount">—</td></tr>
{_paystub_ytd_money_row("Gross pay", gross, ytd["gross_pay"], bold=True)}
</table>"""


def _employee_taxes_ytd_html(details: dict, totals: dict, ytd: dict[str, float]) -> str:
    rows = []
    for key, label in PAYSTUB_DEDUCTION_LINES:
        current = float(_money((details.get("employee_deductions") or {}).get(key)))
        rows.append(_paystub_ytd_money_row(label, current, ytd.get(key, 0.0)))
    rows.append(
        _paystub_ytd_money_row(
            "Total employee taxes",
            float(totals.get("total_employee_deductions") or 0),
            ytd["total_employee_deductions"],
            bold=True,
        )
    )
    return f"""
<h2>Employee Taxes</h2>
<table class="compact ytd">
{_paystub_ytd_table_head()}
{"".join(rows)}
</table>"""


def _employee_net_pay_ytd_html(
    net_pay: float, net_paid: float, ytd: dict[str, float], *, gross: float = 0, withheld: float = 0
) -> str:
    """Employee copy: one net line = cash actually paid (gross minus all withholding)."""
    net_paid_f = float(net_paid)
    net_pay_f = float(net_pay)
    ytd_net = float(ytd.get("amount_paid") or 0)
    if abs(net_paid_f - net_pay_f) > 0.01:
        ytd_net = float(ytd.get("amount_paid") or 0)
    else:
        ytd_net = float(ytd.get("net_pay") or ytd.get("amount_paid") or 0)
    return f"""
<h2>Net Pay</h2>
<table class="compact ytd">
{_paystub_ytd_table_head()}
{_paystub_ytd_money_row("Net pay", net_paid_f, ytd_net, bold=True)}
</table>"""


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


def _employee_tax_balance_html(totals: dict) -> str:
    """Compact tax balance block for employee paystub copy."""
    prior = float(totals.get("prior_tax_balance") or 0)
    prior_adj = float(totals.get("prior_period_adjustment") or 0)
    prior_collected = float(totals.get("tax_catch_up_adjustment") or 0)
    period_balance = float(totals.get("tax_balance_owed") or 0)
    current_period = float(totals.get("current_period_taxes") or 0)
    total_liability = float(totals.get("total_tax_liability") or 0)
    remaining = float(totals.get("remaining_tax_balance") or 0)

    if current_period <= 0 and prior <= 0 and prior_collected <= 0 and remaining <= 0:
        return ""

    if prior > 0 or prior_collected > 0:
        prior_adj_row = (
            _paystub_money_row("Prior period adjustment", -prior_adj)
            if prior_adj > 0
            else ""
        )
        rows_html = (
            _paystub_money_row("This period estimated tax", current_period)
            + _paystub_money_row("Prior tax balance", prior)
            + prior_adj_row
            + _paystub_money_row("Total estimated liability", total_liability)
            + _paystub_money_row("Remaining balance", remaining, True)
        )
        return f"""
<h2>Tax Balance</h2>
<table class="compact">
{rows_html}
</table>"""

    if period_balance <= 0 and remaining <= 0:
        return ""
    balance = period_balance if period_balance > 0 else remaining
    rows_html = (
        _paystub_money_row("Estimated tax liability", current_period)
        + _paystub_money_row("Estimated tax balance", balance, True)
    )
    return f"""
<h2>Tax Balance</h2>
<table class="compact">
{rows_html}
</table>"""


def _employee_earnings_html(
    hours: float, rate: float, gross: float, *, line: Optional[dict] = None
) -> str:
    from backend.payroll_overtime import earnings_breakdown_from_line

    breakdown = None
    if line is not None:
        breakdown = earnings_breakdown_from_line(
            {
                **line,
                "gross_amount": gross,
                "approved_hours": line.get("approved_hours", hours),
                "rate": line.get("rate", rate),
            }
        )
    if breakdown and float(breakdown.get("ot_hours") or 0) > 0:
        other_row = (
            _paystub_money_row("Other earnings", float(breakdown["other_earnings"]))
            if float(breakdown.get("other_earnings") or 0)
            else ""
        )
        return f"""
<h2>Earnings</h2>
<table class="compact">
<tr><td>Regular hours</td><td class="amount">{breakdown['regular_hours']:.2f}</td></tr>
<tr><td>OT hours</td><td class="amount">{breakdown['ot_hours']:.2f}</td></tr>
<tr><td>Hourly rate</td><td class="amount">${rate:,.2f}</td></tr>
{_paystub_money_row("Regular/Base earnings", float(breakdown["base_earnings"]))}
{_paystub_money_row("OT premium", float(breakdown["ot_premium"]))}
{other_row}
{_paystub_money_row("Gross pay", gross, True)}
</table>
<p class="note" style="font-size:0.8rem;color:#64748b;margin-top:6px">
OT Premium represents only the additional amount paid above the employee’s regular hourly rate.
</p>"""
    return f"""
<h2>Earnings</h2>
<table class="compact">
<tr><td>Hours worked</td><td class="amount">{hours:.2f}</td></tr>
<tr><td>Hourly rate</td><td class="amount">${rate:,.2f}</td></tr>
{_paystub_money_row("Gross pay", gross, True)}
</table>"""


def _employee_payment_method_html(payment: dict) -> str:
    label = _payment_method_label(payment.get("method"))
    pay_date = payment.get("date")
    date_row = (
        f"<tr><td>Payment date</td><td>{pay_date}</td></tr>" if pay_date else ""
    )
    return f"""
<h2>Payment</h2>
<table class="compact">
<tr><td>Payment method</td><td>{label}</td></tr>
{date_row}
</table>"""


def _cash_receipt_section_html(line: dict, payment: dict, totals: dict) -> str:
    name = str(line.get("worker_name_snapshot") or "")
    amt = payment.get("cash_amount")
    if amt is None or str(amt).strip() == "":
        amt = totals.get("net_paid_to_employee") or totals.get("amount_paid")
    amt_str = f"${float(_money(amt)):,.2f}"
    return f"""
<div class="cash-receipt">
<h2>Cash Payment Acknowledgment</h2>
<div class="row"><strong>Amount received:</strong> {amt_str}</div>
<div class="sig-field">
<div class="sig-line sig-line-large"></div>
<div class="sig-label">Employee name</div>
</div>
<div class="sig-field">
<div class="sig-line sig-line-large"></div>
<div class="sig-label">Employee signature</div>
</div>
<div class="sig-field">
<div class="sig-line sig-line-date"></div>
<div class="sig-label">Date</div>
</div>
<div class="sig-field">
<div class="sig-line sig-line-large"></div>
<div class="sig-label">Manager / witness</div>
</div>
<p class="ack">I acknowledge receipt of the cash payment shown above.</p>
</div>"""


def _render_paystub_html(
    batch: dict,
    line: dict,
    details: dict,
    totals: dict,
    *,
    preview: bool = False,
    copy_mode: str = "employee",
    conn: Optional[Any] = None,
    organization_id: Optional[int] = None,
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

    org_id = organization_id or batch.get("organization_id")
    branding = (
        _organization_print_branding(conn, int(org_id), logo_height_px=PAYSTUB_LOGO_HEIGHT_PX)
        if conn is not None and org_id
        else {
            "company_name": "",
            "logo_html": "",
            "address_line": "",
            "address_line2": "",
            "contact_line": "",
        }
    )
    brand_head_html = _paystub_brand_head_html(branding, title)

    worker = line.get("worker_name_snapshot") or ""
    emp_id = line.get("employee_id") or ""
    hours = float(line.get("approved_hours") or 0)
    rate = float(line.get("rate") or 0)

    cash_receipt_separate = is_employee and method_key == "cash"

    if is_employee:
        ytd = (
            compute_paystub_ytd(conn, int(org_id), batch, line, details, totals)
            if conn is not None and org_id
            else _add_paystub_ytd(
                _empty_paystub_ytd(),
                _line_paystub_ytd_components(line, details, totals),
            )
        )
        employee_meta = f"""
<p class="employee-meta"><strong>{worker}</strong><br>
Pay period: {batch.get('pay_period_start')} – {batch.get('pay_period_end')}</p>"""
        earnings_html = _employee_earnings_ytd_html(hours, rate, gross, ytd, line=line)
        emp_tax_table = _employee_taxes_ytd_html(details, totals, ytd)
        net_pay_html = _employee_net_pay_ytd_html(
            net_pay, net_paid, ytd, gross=gross, withheld=withheld
        )
        tax_balance_html = ""
        if bool(details.get("show_tax_payment_section", True)):
            tax_balance_html = _employee_tax_balance_html(totals)
        payment_html = _employee_payment_method_html(payment)
        cash_receipt_html = (
            _cash_receipt_section_html(line, payment, totals) if cash_receipt_separate else ""
        )

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title} — {worker}</title>
<style>{_paystub_base_css()}</style></head><body>
<div class="paystub-sheet">
<div class="copy-badge">{copy_badge}</div>
{brand_head_html}
{preview_banner}
{employee_meta}
{earnings_html}
{emp_tax_table}
{net_pay_html}
{tax_balance_html}
{payment_html}
{cash_receipt_html}
</div>
</body></html>"""

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
</table>"""

    employee_info_html = f"""
<h2>Employee Information</h2>
<dl class="info-grid">
<dt>Employee name</dt><dd>{worker}</dd>
{f'<dt>Employee ID</dt><dd>{emp_id}</dd>' if emp_id else ''}
<dt>Pay period</dt><dd>{batch.get('pay_period_start')} – {batch.get('pay_period_end')}</dd>
<dt>Hours worked</dt><dd>{hours:.2f}</dd>
<dt>Hourly rate</dt><dd>${rate:,.2f}</dd>
</dl>"""

    earnings_html = _employee_earnings_html(hours, rate, gross, line=line)

    gross_paid_note = ""
    tax_balance = float(totals.get("tax_balance_owed") or 0)
    if paid_full_gross or (net_paid > net_pay and withheld < emp_tax_total * 0.5):
        parts = [
            "Amount paid exceeds net pay because taxes were not withheld from this payment."
        ]
        if tax_balance > 0:
            parts.append(
                f"Estimated tax balance for this period: ${tax_balance:,.2f} "
                "(not collected with this payment)."
            )
        gross_paid_note = f"<p class='note-box'>{' '.join(parts)}</p>"

    net_pay_html = f"""
<h2>Net Pay</h2>
<table class="compact">
{_paystub_money_row('Net pay (after taxes)', net_pay)}
{_paystub_money_row('Amount paid to employee', net_paid, True)}
</table>
{gross_paid_note}"""

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
{_paystub_money_row('Prior period adjustment', -float(totals.get('prior_period_adjustment') or 0)) if float(totals.get('prior_period_adjustment') or 0) > 0 else ''}
{_paystub_money_row('Current period taxes', float(totals.get('current_period_taxes') or 0))}
{_paystub_money_row('Total tax liability', float(totals.get('total_tax_liability') or 0))}
{_paystub_money_row('Actual tax withheld', withheld)}
{_paystub_money_row('Remaining balance', float(totals.get('remaining_tax_balance') or 0), True)}
{_paystub_money_row('Tax balance owed (period)', float(totals.get('tax_balance_owed') or 0))}
</table>
{catch_up_html}"""

    payment_html = f"""
<h2>Payment Information</h2>
<table class="compact">
{_payment_detail_rows(payment, totals, cash_receipt_separate=False)}
</table>"""

    employer_html = ""
    if not is_employee:
        er_rows = "".join(
            _paystub_money_row(label, float(_money(er.get(key))))
            for key, label in PAYSTUB_EMPLOYER_TAX_LINES
        )
        mctmt = float(_money(er.get("other")))
        if mctmt > 0:
            er_rows += _paystub_money_row("MCTMT", mctmt)
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

    notes_html = _paystub_notes_html(batch, details)
    notes_block = f'<div class="notes">{notes_html}</div>' if notes_html else ""

    finalized_footer = ""
    if batch.get("payout_details_finalized_at") and not preview:
        finalized_footer = f"<p class='meta'>Finalized {batch.get('payout_details_finalized_at')}</p>"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title} — {worker}</title>
<style>{_paystub_base_css()}</style></head><body>
<div class="paystub-sheet">
<div class="copy-badge">{copy_badge}</div>
{brand_head_html}
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
        batch,
        line,
        details,
        totals,
        preview=preview,
        copy_mode=copy_mode,
        conn=conn,
        organization_id=int(organization_id),
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
        conn=conn,
        organization_id=int(organization_id),
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
            batch,
            line,
            details,
            totals,
            preview=preview,
            copy_mode=copy_mode,
            conn=conn,
            organization_id=int(organization_id),
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


def _parse_archive_batch_ids(raw: Optional[str]) -> Optional[list[int]]:
    if raw is None or str(raw).strip() == "":
        return None
    ids: list[int] = []
    for part in str(raw).replace(" ", ",").split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids or None


def _archive_batch_filters_sql(
    *,
    worker_category: Optional[str] = None,
    pay_period_start: Optional[str] = None,
    pay_period_end: Optional[str] = None,
    batch_ids: Optional[list[int]] = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if worker_category and worker_category != "all":
        clauses.append("pb.worker_category = %s")
        params.append(str(worker_category))
    if pay_period_start:
        clauses.append("pb.pay_period_end >= %s")
        params.append(str(pay_period_start))
    if pay_period_end:
        clauses.append("pb.pay_period_start <= %s")
        params.append(str(pay_period_end))
    if batch_ids:
        placeholders = ",".join(["%s"] * len(batch_ids))
        clauses.append(f"pb.id IN ({placeholders})")
        params.extend([int(x) for x in batch_ids])
    clauses.append(
        "(pb.document_mode IS NULL OR pb.document_mode = '' OR pb.document_mode = 'official_paystub')"
    )
    sql = " AND ".join(clauses)
    return sql, params


def fetch_finalized_archive_batches(
    conn,
    organization_id: int,
    *,
    worker_category: Optional[str] = None,
    pay_period_start: Optional[str] = None,
    pay_period_end: Optional[str] = None,
    batch_ids: Optional[list[int]] = None,
) -> list[dict]:
    """Finalized payout batches eligible for paystub archive (official paystub mode)."""
    ensure_payout_details_columns(conn.cursor())
    extra_sql, extra_params = _archive_batch_filters_sql(
        worker_category=worker_category,
        pay_period_start=pay_period_start,
        pay_period_end=pay_period_end,
        batch_ids=batch_ids,
    )
    c = conn.cursor(dictionary=True)
    c.execute(
        f"""
        SELECT pb.id, pb.batch_name, pb.pay_period_start, pb.pay_period_end, pb.worker_category
        FROM payout_batches pb
        WHERE pb.organization_id = %s
          AND pb.payout_details_finalized_at IS NOT NULL
          AND {extra_sql}
        ORDER BY pb.pay_period_start ASC, pb.id ASC
        """,
        tuple([int(organization_id)] + extra_params),
    )
    return [json_safe(r) for r in c.fetchall() or []]


def list_paystub_archive_employees(
    conn,
    organization_id: int,
    *,
    worker_category: Optional[str] = None,
    pay_period_start: Optional[str] = None,
    pay_period_end: Optional[str] = None,
    batch_ids: Optional[list[int]] = None,
) -> list[dict]:
    extra_sql, extra_params = _archive_batch_filters_sql(
        worker_category=worker_category,
        pay_period_start=pay_period_start,
        pay_period_end=pay_period_end,
        batch_ids=batch_ids,
    )
    c = conn.cursor(dictionary=True)
    c.execute(
        f"""
        SELECT DISTINCT pbl.user_id, pbl.worker_name_snapshot AS worker_name
        FROM payout_batch_lines pbl
        JOIN payout_batches pb ON pb.id = pbl.batch_id
        WHERE pb.organization_id = %s
          AND pb.payout_details_finalized_at IS NOT NULL
          AND pbl.user_id IS NOT NULL
          AND {extra_sql}
        ORDER BY pbl.worker_name_snapshot ASC, pbl.user_id ASC
        """,
        tuple([int(organization_id)] + extra_params),
    )
    return [
        {
            "user_id": int(r["user_id"]),
            "worker_name": str(r.get("worker_name") or ""),
        }
        for r in c.fetchall() or []
        if r.get("user_id")
    ]


def generate_employee_paystub_archive_html(
    conn,
    organization_id: int,
    viewing_user_id: int,
    *,
    worker_category: Optional[str] = None,
    pay_period_start: Optional[str] = None,
    pay_period_end: Optional[str] = None,
    user_id: Optional[int] = None,
    batch_ids: Optional[list[int]] = None,
    copy_mode: str = "employee",
) -> str:
    """All paystubs grouped by employee, spanning multiple finalized pay periods."""
    batches = fetch_finalized_archive_batches(
        conn,
        organization_id,
        worker_category=worker_category,
        pay_period_start=pay_period_start,
        pay_period_end=pay_period_end,
        batch_ids=batch_ids,
    )
    if not batches:
        raise ValueError("No finalized payout batches match filters")

    entries: list[dict[str, Any]] = []
    for batch_row in batches:
        batch_id = int(batch_row["id"])
        batch = get_payout_batch_details(conn, organization_id, batch_id)
        if not batch:
            continue
        if not can_view_paystub(conn, viewing_user_id, batch, preview=False):
            continue
        for line in batch.get("lines") or []:
            line_uid = line.get("user_id")
            if user_id is not None and int(line_uid or 0) != int(user_id):
                continue
            details = line.get("payout_details") or parse_line_payout_details(line)
            if not can_generate_paystub_for_line(batch, details):
                continue
            totals = line.get("payout_totals") or compute_line_totals(line, details)
            html = _render_paystub_html(
                batch,
                line,
                details,
                totals,
                preview=False,
                copy_mode=copy_mode,
                conn=conn,
                organization_id=int(organization_id),
            )
            sheet = _extract_paystub_sheet(html)
            worker_name = str(line.get("worker_name_snapshot") or "Employee")
            entries.append(
                {
                    "user_id": int(line_uid or 0),
                    "worker_name": worker_name,
                    "pay_period_start": str(batch.get("pay_period_start") or ""),
                    "batch_id": batch_id,
                    "sheet": sheet,
                }
            )

    if not entries:
        raise ValueError("No paystubs available for archive filters")

    entries.sort(
        key=lambda e: (
            e["worker_name"].lower(),
            e["user_id"],
            e["pay_period_start"],
            e["batch_id"],
        )
    )

    from itertools import groupby

    groups: list[tuple[int, list[dict[str, Any]]]] = []
    for uid, group in groupby(entries, key=lambda e: e["user_id"]):
        groups.append((uid, list(group)))

    sections: list[str] = []
    for _uid, group_entries in groups:
        name = group_entries[0]["worker_name"]
        sheets = "".join(e["sheet"] for e in group_entries)
        sections.append(
            f"<div class='employee-paystub-group'>"
            f"<h2 class='employee-name'>{name}</h2>"
            f"{sheets}</div>"
        )

    copy = _paystub_copy_mode(copy_mode)
    title = (
        "Employee Paystub Archive"
        if copy == "employee"
        else "Employer Payroll Record Archive"
    )
    period_bits = [
        str(pay_period_start or "").strip(),
        str(pay_period_end or "").strip(),
    ]
    period_label = ""
    if period_bits[0] and period_bits[1]:
        period_label = f"Pay periods {period_bits[0]} – {period_bits[1]}"
    elif period_bits[0]:
        period_label = f"From {period_bits[0]}"
    elif period_bits[1]:
        period_label = f"Through {period_bits[1]}"
    else:
        starts = [str(b.get("pay_period_start") or "") for b in batches]
        ends = [str(b.get("pay_period_end") or "") for b in batches]
        if starts and ends:
            period_label = f"Pay periods {min(starts)} – {max(ends)}"

    employee_count = len(groups)
    paystub_count = len(entries)
    intro = (
        f"<p class='archive-intro'>{period_label} · "
        f"{employee_count} employee(s) · {paystub_count} paystub(s)</p>"
    )
    if user_id is not None and groups:
        title = f"{groups[0][1][0]['worker_name']} — Paystub Archive"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>{_paystub_base_css()}</style></head><body>
<h1>{title}</h1>
{intro}
{"".join(sections)}
</body></html>"""


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
    from backend.payroll_overtime import earnings_breakdown_from_line

    batch = get_payout_batch_details(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if not preview and not batch.get("payout_details_finalized_at"):
        raise ValueError("Pay register not available until payout details are finalized")
    if not batch_ready_for_payout_details(batch) and preview:
        raise ValueError("Batch must be approved for payment before previewing pay register")

    rows_html = []
    sum_base = sum_ot_prem = sum_other = sum_gross = sum_net = sum_wh = 0.0
    sum_reg_h = sum_ot_h = 0.0
    for line in batch.get("lines") or []:
        details = line.get("payout_details") or parse_line_payout_details(line)
        totals = line.get("payout_totals") or compute_line_totals(line, details)
        breakdown = earnings_breakdown_from_line({**line, "gross_amount": totals["gross_pay"]})
        gross = float(breakdown["gross_pay"])
        net = float(totals.get("net_paid_to_employee") or totals["amount_paid"])
        withheld = float(totals.get("amount_withheld") or 0)
        method = _payment_method_label((details.get("payment") or {}).get("method"))
        sum_base += float(breakdown["base_earnings"])
        sum_ot_prem += float(breakdown["ot_premium"])
        sum_other += float(breakdown["other_earnings"])
        sum_reg_h += float(breakdown["regular_hours"])
        sum_ot_h += float(breakdown["ot_hours"])
        sum_gross += gross
        sum_net += net
        sum_wh += withheld
        rows_html.append(
            f"<tr><td>{line.get('worker_name_snapshot')}</td>"
            f"<td style='text-align:right'>{breakdown['regular_hours']:.2f}</td>"
            f"<td style='text-align:right'>{breakdown['ot_hours']:.2f}</td>"
            f"<td style='text-align:right'>${breakdown['base_earnings']:,.2f}</td>"
            f"<td style='text-align:right'>${breakdown['ot_premium']:,.2f}</td>"
            f"<td style='text-align:right'>${breakdown['other_earnings']:,.2f}</td>"
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
  .note {{ color: #64748b; font-size: 0.85rem; margin-bottom: 12px; }}
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
<p class="note">OT Premium represents only the additional amount paid above the employee’s regular hourly rate.
Regular/Base earnings include overtime hours at the regular rate.</p>
<table>
<thead><tr>
<th>Employee</th>
<th style="text-align:right">Reg hrs</th>
<th style="text-align:right">OT hrs</th>
<th style="text-align:right">Regular/Base</th>
<th style="text-align:right">OT Premium</th>
<th style="text-align:right">Other</th>
<th style="text-align:right">Gross</th>
<th style="text-align:right">Withheld</th>
<th style="text-align:right">Net paid</th>
<th>Method</th>
</tr></thead>
<tbody>
{"".join(rows_html)}
<tr class="total">
<td>Total</td>
<td style="text-align:right">{sum_reg_h:,.2f}</td>
<td style="text-align:right">{sum_ot_h:,.2f}</td>
<td style="text-align:right">${sum_base:,.2f}</td>
<td style="text-align:right">${sum_ot_prem:,.2f}</td>
<td style="text-align:right">${sum_other:,.2f}</td>
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
    branding = _organization_print_branding(conn, organization_id, logo_height_px=52)
    logo_html = branding["logo_html"]
    company_name = branding["company_name"]

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


def _vendor_receipt_year(batch: dict, payment: dict) -> int:
    for raw in (
        batch.get("official_pay_date"),
        payment.get("date"),
        batch.get("pay_period_end"),
    ):
        if raw:
            try:
                return int(str(raw)[:4])
            except (TypeError, ValueError):
                continue
    return datetime.utcnow().year


def fetch_vendor_receipt_ytd_prior(
    conn,
    organization_id: int,
    user_id: int,
    *,
    year: int,
    pay_date: str,
    current_batch_id: Optional[int] = None,
    exclude_line_id: Optional[int] = None,
) -> float:
    """Amount paid to a temp/1099 worker on finalized batches earlier this year.

    "Earlier" = pay date strictly before this line's pay date, or same date on an
    earlier batch id. Only finalized vendor-receipt batches contribute.
    """
    c = conn.cursor(dictionary=True)
    pd = str(pay_date or "")[:10]
    bid = int(current_batch_id or 0)
    params: list[Any] = [int(organization_id), int(user_id), int(year)]
    date_clause = ""
    if pd:
        date_clause = (
            " AND (COALESCE(pb.official_pay_date, pb.pay_period_end) < %s"
            " OR (COALESCE(pb.official_pay_date, pb.pay_period_end) = %s AND pb.id < %s))"
        )
        params += [pd, pd, bid]
    exclude_sql = ""
    if exclude_line_id is not None:
        exclude_sql = " AND pbl.id <> %s"
        params.append(int(exclude_line_id))
    c.execute(
        f"""
        SELECT pbl.gross_amount, pbl.total_amount, pbl.payout_details_json
        FROM payout_batch_lines pbl
        JOIN payout_batches pb ON pb.id = pbl.batch_id
        WHERE pb.organization_id = %s
          AND pbl.user_id = %s
          AND pb.worker_category IN ('temp', 'contractor_1099')
          AND pb.payout_details_finalized_at IS NOT NULL
          AND YEAR(COALESCE(pb.official_pay_date, pb.pay_period_end)) = %s
          {date_clause}{exclude_sql}
        """,
        tuple(params),
    )
    prior = 0.0
    for row in c.fetchall() or []:
        ln = {
            "gross_amount": row.get("gross_amount"),
            "total_amount": row.get("total_amount"),
            "payout_details_json": row.get("payout_details_json"),
        }
        details = parse_line_payout_details(ln)
        totals = compute_line_totals(ln, details)
        prior += float(totals.get("amount_paid") or 0)
    return round(prior, 2)


def _vendor_worker_contact(conn, user_id: Optional[int]) -> dict[str, str]:
    if not user_id:
        return {"phone": "", "email": ""}
    c = conn.cursor(dictionary=True)
    try:
        c.execute(
            "SELECT email, mobile FROM payroll_profiles WHERE user_id=%s LIMIT 1",
            (int(user_id),),
        )
    except Exception:
        return {"phone": "", "email": ""}
    row = c.fetchone() or {}
    return {
        "phone": str(row.get("mobile") or "").strip(),
        "email": str(row.get("email") or "").strip(),
    }


def _vendor_receipt_type_label(worker_category: str) -> str:
    if worker_category == "temp":
        return "Temporary / Short-Term Contractor"
    if worker_category == "contractor_1099":
        return "1099 Contractor"
    return "Contractor"


def _org_service_recipient(conn, organization_id) -> dict[str, str]:
    """Legal/display name + full address of the client the work was performed for.

    Reuses the existing employer/organization settings resolver (legal name,
    structured address). Identifies the service recipient, not the vendor.
    """
    if not organization_id:
        return {"name": "", "address": ""}
    name = ""
    address = ""
    try:
        from backend.hr_compliance import fetch_hr_org_settings

        settings = fetch_hr_org_settings(conn, int(organization_id)) or {}
        name = str(settings.get("employer_name") or "").strip()
        address = str(settings.get("employer_address") or "").strip()
    except Exception:  # pragma: no cover - settings lookup is best-effort
        pass
    if not name:
        name = _org_display_name(conn, organization_id)
    return {"name": name, "address": address}


def _org_display_name(conn, organization_id) -> str:
    """Display name of the organization the work was performed for (the client).

    Identifies the service recipient, not the contractor vendor, so it resolves
    from the batch's organization record.
    """
    if not organization_id:
        return ""
    c = conn.cursor(dictionary=True)
    try:
        c.execute(
            "SELECT display_name, slug FROM organizations WHERE id=%s LIMIT 1",
            (int(organization_id),),
        )
    except Exception:
        return ""
    row = c.fetchone() or {}
    return str(row.get("display_name") or row.get("slug") or "").strip()


def generate_vendor_receipt_html(
    conn,
    organization_id: int,
    batch_id: int,
    line_id: int,
    *,
    preview: bool = False,
) -> str:
    """Contractor Invoice & Payment Receipt for a temp/1099 line (replaces paystub).

    Branding (name/address/logo) comes from the line's resolved vendor. YTD is the
    payout-based total paid this calendar year, including this payment.
    """
    import html as _html

    from backend.payroll_vendors import resolve_line_vendor

    batch = get_payout_batch_details(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if not batch_uses_vendor_receipt(batch):
        raise ValueError("Vendor receipt applies to temp / 1099 batches only")
    if not preview and not batch.get("payout_details_finalized_at"):
        raise ValueError("Vendor receipt not available until payout details are finalized")
    line = next(
        (ln for ln in batch.get("lines") or [] if int(ln.get("id")) == int(line_id)),
        None,
    )
    if not line:
        raise ValueError("Line not found")
    details = line.get("payout_details") or parse_line_payout_details(line)
    totals = line.get("payout_totals") or compute_line_totals(line, details)
    payment = details.get("payment") or {}

    vendor = resolve_line_vendor(conn, int(organization_id), line, batch) or {}
    contact = _vendor_worker_contact(conn, line.get("user_id"))

    gross = float(totals.get("gross_pay") or 0)
    amount_paid = float(totals.get("amount_paid") or gross)
    hours = float(line.get("approved_hours") or 0)
    rate = float(line.get("rate") or 0)
    adjustments = float(_money(line.get("adjustments") or 0))

    year = _vendor_receipt_year(batch, payment)
    pay_date = str(
        payment.get("date") or batch.get("official_pay_date") or batch.get("pay_period_end") or ""
    )[:10]
    prior_ytd = fetch_vendor_receipt_ytd_prior(
        conn,
        int(organization_id),
        int(line.get("user_id") or 0),
        year=year,
        pay_date=pay_date,
        current_batch_id=int(batch.get("id") or 0),
        exclude_line_id=int(line.get("id") or 0) or None,
    )
    ytd_including = round(prior_ytd + amount_paid, 2)

    worker_name = str(line.get("worker_name_snapshot") or "").strip()
    method = _payment_method_label(payment.get("method"))
    reference = str(payment.get("reference") or "").strip()
    type_label = _vendor_receipt_type_label(str(batch.get("worker_category") or ""))
    vendor_name = str(vendor.get("name") or "").strip()
    vendor_address = str(vendor.get("address") or "").strip()
    vendor_logo = str(vendor.get("logo_url") or "").strip()

    def esc(val: Any) -> str:
        return _html.escape(str(val)) if val is not None else ""

    def money(val: float) -> str:
        return f"${val:,.2f}"

    def row(label: str, value: str, *, strong: bool = False, left: bool = True) -> str:
        if value is None or value == "":
            return ""
        align = "left" if left else "right"
        cell = f"<strong>{value}</strong>" if strong else value
        lbl = f"<strong>{label}</strong>" if strong else label
        return f"<tr><td>{lbl}</td><td style='text-align:{align}'>{cell}</td></tr>"

    logo_html = ""
    if vendor_logo:
        logo_html = (
            f"<img src='{esc(vendor_logo)}' alt='{esc(vendor_name)}' "
            "style='max-height:60px;max-width:240px;object-fit:contain' />"
        )
    else:
        logo_html = f"<h1 style='margin:0;color:#0f2f66'>{esc(vendor_name)}</h1>"

    work_period = f"{batch.get('pay_period_start')} — {batch.get('pay_period_end')}"

    part1_rows = "".join(
        [
            row("Contractor / worker name", esc(worker_name), strong=True),
            row("Phone", esc(contact["phone"])) if contact["phone"] else "",
            row("Email", esc(contact["email"])) if contact["email"] else "",
            row("Work period", esc(work_period)),
            row("Total approved hours", f"{hours:.2f}", left=False) if hours else "",
            row("Service rate", money(rate), left=False) if rate else "",
            row("Service amount", money(gross), left=False),
            (row("Adjustments, if any", money(adjustments), left=False) if adjustments else ""),
            row("Total amount due", money(round(gross + adjustments, 2)), strong=True, left=False),
            (row("Total paid this year (before this payment)", money(prior_ytd), left=False)
             if prior_ytd > 0 else ""),
            row(
                "Total paid this year (including this payment)",
                money(ytd_including),
                strong=True,
                left=False,
            ),
        ]
    )

    part2_rows = "".join(
        [
            row("Amount paid", money(amount_paid), strong=True, left=False),
            row("Payment method", esc(method)),
            row("Payment reference", esc(reference)) if reference else "",
            row("Payment date", esc(payment.get("date") or "—"), strong=True),
        ]
    )

    recipient = _org_service_recipient(conn, organization_id)
    org_name = str(recipient.get("name") or "").strip()
    org_address = str(recipient.get("address") or "").strip()

    def party(title: str, name: str, address: str) -> str:
        if not (name or address):
            return ""
        addr = (
            f"<p class='party-addr'>{esc(address)}</p>" if address else ""
        )
        return (
            "<div class='party'>"
            f"<span class='party-label'>{title}</span>"
            f"<p class='party-name'>{esc(name)}</p>{addr}</div>"
        )

    issued_party = party("Issued from", vendor_name, vendor_address)
    recipient_party = party("Work performed for", org_name, org_address)
    parties_html = (
        f"<div class='parties'>{issued_party}{recipient_party}</div>"
        if (issued_party or recipient_party)
        else ""
    )

    # Signature: contractor (from worker + category) and vendor representative
    # (from the finalized vendor snapshot for historical immutability).
    contractor_designation = type_label
    rep_name = str(vendor.get("representative_name") or "").strip()
    rep_title = str(vendor.get("representative_title") or "").strip()

    draft_banner = (
        "<p class='draft'>DRAFT PREVIEW — not finalized</p>" if preview and not batch.get(
            "payout_details_finalized_at"
        ) else ""
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Contractor Invoice &amp; Payment Receipt — {esc(worker_name)}</title>
<style>
  @page {{ size: letter portrait; margin: 0.5in; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: system-ui, -apple-system, sans-serif; color: #0f172a; margin: 0; padding: 28px; font-size: 12px; line-height: 1.35; }}
  @media print {{ body {{ padding: 0; }} }}
  .head {{ border-bottom: 2px solid #0f2f66; padding-bottom: 8px; margin-bottom: 8px; }}
  .head img {{ max-height: 48px; max-width: 220px; object-fit: contain; }}
  .head h1 {{ margin: 0; color: #0f2f66; font-size: 1.3rem; }}
  h2.doc {{ font-size: 1.1rem; margin: 4px 0 0; }}
  h3.section {{ color: #0f2f66; font-size: 0.95rem; margin: 12px 0 3px; border-bottom: 1px solid #cbd5e1; padding-bottom: 3px; page-break-after: avoid; }}
  .hint {{ font-size: 0.72rem; color: #64748b; margin: 0 0 4px; }}
  .parties {{ display: flex; align-items: flex-start; gap: 28px; margin: 10px 0; page-break-inside: avoid; }}
  .party {{ flex: 1; min-width: 0; }}
  .party-label {{ font-weight: 700; }}
  .party-name {{ margin: 2px 0 0; font-weight: 600; }}
  .party-addr {{ margin: 2px 0 0; color: #475569; white-space: pre-line; }}
  table {{ width: 100%; border-collapse: collapse; margin: 4px 0; page-break-inside: avoid; }}
  td {{ padding: 4px 8px; border: 1px solid #e2e8f0; font-size: 0.82rem; }}
  td:first-child {{ background: #f8fafc; width: 55%; }}
  .draft {{ color: #b45309; font-weight: 700; letter-spacing: 0.05em; margin: 4px 0; }}
  .sig {{ display: grid; grid-template-columns: 1fr 1fr; gap: 28px; margin-top: 18px; page-break-inside: avoid; }}
  .sig-col {{ min-width: 0; }}
  .sig-title {{ font-weight: 700; display: block; }}
  .sig-meta {{ margin: 4px 0 0; font-size: 0.82rem; }}
  .sig-line {{ border-top: 1px solid #334155; margin-top: 26px; padding-top: 3px; font-size: 0.78rem; color: #475569; }}
  .footnote {{ font-size: 0.7rem; color: #64748b; margin-top: 12px; }}
</style></head><body>
<div class="head">
  {logo_html}
  <h2 class="doc">Contractor Invoice &amp; Payment Receipt</h2>
</div>
{draft_banner}
{parties_html}
<p class="hint"><strong>Contractor type:</strong> {esc(type_label)}</p>

<h3 class="section">Part 1 — Invoice / Work Summary</h3>
<p class="hint">Work summary for the pay period. Signature is not required for this section.</p>
<table><tbody>{part1_rows}</tbody></table>

<h3 class="section">Part 2 — Payment Receipt</h3>
<p class="hint">Worker/Contractor confirms that the work listed above was completed and that
payment listed below was received. This receipt confirms payment only and does not waive any
legal rights. This form does not guarantee future work.</p>
<table><tbody>{part2_rows}</tbody></table>

<div class="sig">
  <div class="sig-col">
    <span class="sig-title">Contractor / worker signature</span>
    <p class="sig-meta">Name: {esc(worker_name) or "&nbsp;"}</p>
    <p class="sig-meta">Designation: {esc(contractor_designation) or "&nbsp;"}</p>
    <div class="sig-line">Signature</div>
    <div class="sig-line">Date</div>
  </div>
  <div class="sig-col">
    <span class="sig-title">Vendor representative signature</span>
    <p class="sig-meta">Name: {esc(rep_name) if rep_name else "&nbsp;"}</p>
    <p class="sig-meta">Designation: {esc(rep_title) if rep_title else "&nbsp;"}</p>
    <div class="sig-line">Signature</div>
    <div class="sig-line">Date</div>
  </div>
</div>
<p class="hint footnote">Total paid this year is based on finalized payouts for {year}.
{"Finalized " + str(batch.get('payout_details_finalized_at')) if batch.get('payout_details_finalized_at') else ""}</p>
</body></html>"""
    return html


def generate_batch_vendor_receipts_html(
    conn, organization_id: int, batch_id: int, *, preview: bool = False
) -> str:
    """Concatenate every temp/1099 line's vendor receipt into one printable doc."""
    batch = get_payout_batch_details(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if not batch_uses_vendor_receipt(batch):
        raise ValueError("Vendor receipt applies to temp / 1099 batches only")
    parts: list[str] = []
    for ln in batch.get("lines") or []:
        try:
            parts.append(
                generate_vendor_receipt_html(
                    conn, organization_id, batch_id, int(ln.get("id")), preview=preview
                )
            )
        except ValueError:
            continue
    if not parts:
        raise ValueError("No vendor receipts available for this batch")
    bodies = []
    for doc in parts:
        start = doc.find("<body>")
        end = doc.find("</body>")
        if start != -1 and end != -1:
            body = doc[start + len("<body>") : end]
            # Capture targets so Download batch PDF / html2canvas emits one
            # page per receipt instead of shrinking everything onto a blank page.
            bodies.append(
                f'<div class="paystub-sheet pdf-capture-page">{body}</div>'
            )
    combined = (
        "<div style='page-break-after:always'></div>".join(bodies) if bodies else ""
    )
    style_start = parts[0].find("<style>")
    style_end = parts[0].find("</style>")
    style = parts[0][style_start : style_end + len("</style>")] if style_start != -1 else ""
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>Vendor Receipts — {batch.get('batch_name')}</title>{style}"
        f"</head><body>{combined}</body></html>"
    )
