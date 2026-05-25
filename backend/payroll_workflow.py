"""Payroll batch workflow: rates, due amounts, payment status, W-4 tax prep (engine pending)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from backend.contractor_management import (
    _contractor_json_from_hr,
    _latest_hourly_rate,
    _latest_payment_method_label,
    build_contractor_prefill,
    compute_payment_summary_amounts,
)
from backend.hr_compliance import ensure_hr_extended_profiles_table
from backend.payroll_identity import fetch_payroll_profile_row, payroll_profiles_active
from backend.payroll_operations import (
    BATCH_STATUSES,
    CATEGORY_LABELS,
    WORKER_CATEGORIES,
    _money,
    get_payout_batch,
    list_time_records,
    worker_category_for_user,
)
from backend.ta_helpers import invalidate_schema_cache, json_safe, table_exists, table_has_column

PAYMENT_STATUSES = ("pending", "approved_unpaid", "paid")
TAX_CALC_STATUSES = ("not_applicable", "pending", "calculated")

BATCH_ACTIONS = (
    "hours_reviewed",
    "send_to_accountant",
    "mark_paid",
    "mark_line_paid",
    "mark_line_unpaid",
    "refresh_rates",
)


def ensure_payout_batch_line_extensions(cursor) -> None:
    from backend.payroll_operations import ensure_payout_batches_tables

    ensure_payout_batches_tables(cursor)
    extras = [
        ("payment_status", "VARCHAR(32) NOT NULL DEFAULT 'pending'"),
        ("tax_calc_status", "VARCHAR(32) NULL"),
    ]
    for col, typedef in extras:
        if not table_has_column(cursor, "payout_batch_lines", col):
            try:
                cursor.execute(
                    f"ALTER TABLE payout_batch_lines ADD COLUMN {col} {typedef}"
                )
            except Exception as exc:
                if getattr(exc, "args", (None,))[0] != 1060:
                    raise
            invalidate_schema_cache()


def _employee_profile_pay_rate(conn, user_id: int) -> Optional[float]:
    chk = conn.cursor()
    if not table_exists(chk, "employee_profiles") or not table_has_column(chk, "users", "employee_id"):
        return None
    c = conn.cursor(dictionary=True)
    c.execute("SELECT employee_id FROM users WHERE id=%s LIMIT 1", (int(user_id),))
    row = c.fetchone()
    emp_id = row.get("employee_id") if row else None
    if not emp_id:
        return None
    c.execute(
        "SELECT pay_rate FROM employee_profiles WHERE employee_id=%s LIMIT 1",
        (int(emp_id),),
    )
    ep = c.fetchone()
    if not ep or ep.get("pay_rate") is None:
        return None
    val = float(ep["pay_rate"])
    return val if val > 0 else None


def resolve_worker_hourly_rate(
    conn, user_id: int, organization_id: int
) -> dict[str, Any]:
    """Resolve hourly rate from worker profile records (never hardcoded)."""
    cat = worker_category_for_user(conn, user_id)
    rate: Optional[float] = None
    source = "missing"
    cj, _ = _contractor_json_from_hr(conn, user_id)
    cj_rate = cj.get("rate_per_hour") or cj.get("hourly_rate")
    if cj_rate is not None:
        try:
            val = float(cj_rate)
            if val > 0:
                rate = val
                source = "contractor_profile"
        except (TypeError, ValueError):
            pass
    if rate is None:
        ur = _latest_hourly_rate(conn, user_id)
        if ur and ur > 0:
            rate = ur
            source = "user_rates"
    if rate is None and cat == "w2":
        ep = _employee_profile_pay_rate(conn, user_id)
        if ep and ep > 0:
            rate = ep
            source = "employee_profile"
    if rate is None:
        try:
            pre = build_contractor_prefill(conn, user_id, organization_id)
            val = float(pre.get("rate_per_hour") or 0)
            if val > 0:
                rate = val
                source = "payroll_prefill"
        except Exception:
            pass
    payment_method = ""
    try:
        pre = build_contractor_prefill(conn, user_id, organization_id)
        payment_method = str(pre.get("payment_method") or "").strip()
    except Exception:
        payment_method = _latest_payment_method_label(conn, user_id) or ""
    return {
        "user_id": int(user_id),
        "worker_category": cat,
        "worker_category_label": CATEGORY_LABELS.get(cat, cat),
        "hourly_rate": rate,
        "rate_source": source,
        "rate_missing": rate is None or rate <= 0,
        "payment_method": payment_method,
    }


def fetch_w4_compliance_summary(conn, user_id: int) -> dict[str, Any]:
    """Read W-4 choices stored on the employee HR profile (not batch-level)."""
    cur = conn.cursor()
    ensure_hr_extended_profiles_table(cur)
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT work_json FROM hr_extended_profiles WHERE user_id=%s LIMIT 1",
        (int(user_id),),
    )
    row = c.fetchone() or {}
    wj = row.get("work_json")
    if isinstance(wj, str):
        try:
            wj = json.loads(wj)
        except Exception:
            wj = {}
    if not isinstance(wj, dict):
        wj = {}
    w4 = wj.get("w4") if isinstance(wj.get("w4"), dict) else {}
    compliance = w4.get("compliance") if isinstance(w4.get("compliance"), dict) else {}
    filing_status = (
        compliance.get("filing_status")
        or compliance.get("step1c_filing_status")
        or compliance.get("filingStatus")
        or ""
    )
    exempt = bool(compliance.get("exempt") or compliance.get("exempt_from_withholding"))
    has_w4 = bool(filing_status or compliance.get("step3_total") is not None or exempt)
    return {
        "w4_on_file": has_w4,
        "filing_status": str(filing_status or "").strip() or None,
        "exempt_from_withholding": exempt,
        "extra_withholding": compliance.get("extra_withholding")
        or compliance.get("step4c_extra_withholding"),
        "tax_calc_status": "pending",
        "tax_calc_note": (
            "W-4 on file — federal/NY/NYC withholding engine pending; net pay not calculated yet."
            if has_w4
            else "W-4 not on file — add withholding choices on the employee Compliance tab."
        ),
    }


def prepare_w2_line_tax_fields(conn, user_id: int, gross: float) -> dict[str, Any]:
    """Store gross wages and W-4 snapshot; do not fabricate withholding amounts."""
    w4 = fetch_w4_compliance_summary(conn, user_id)
    return {
        "gross_wages": gross,
        "federal_withholding": None,
        "state_withholding": None,
        "city_withholding": None,
        "social_security_withholding": None,
        "medicare_withholding": None,
        "other_deductions": None,
        "net_pay": None,
        "tax_calc_status": "pending" if w4.get("w4_on_file") else "not_applicable",
        "w4_summary": w4,
    }


def _line_payment_status_label(st: str) -> str:
    if st == "paid":
        return "Paid"
    if st == "approved_unpaid":
        return "Approved — unpaid"
    return "Pending payment"


def _batch_payment_status(lines: list[dict]) -> str:
    if not lines:
        return "pending"
    paid = sum(1 for ln in lines if str(ln.get("payment_status") or "") == "paid")
    if paid == len(lines):
        return "paid"
    if paid > 0:
        return "partially_paid"
    if any(str(ln.get("payment_status") or "") == "approved_unpaid" for ln in lines):
        return "approved_unpaid"
    return "pending"


def _sum_withholding(lines: list[dict], field: str) -> float:
    total = Decimal("0")
    for ln in lines:
        val = ln.get(field)
        if val is not None:
            total += _money(val)
    return float(total)


def enrich_payout_batch(conn, organization_id: int, batch: dict) -> dict:
    """Attach workflow summary, warnings, and enriched line metadata."""
    if not batch:
        return batch
    ensure_payout_batch_line_extensions(conn.cursor())
    cat = str(batch.get("worker_category") or "")
    lines = batch.get("lines") or []
    missing_rates: list[dict] = []
    missing_w4: list[dict] = []
    enriched_lines = []
    gross_total = Decimal("0")
    paid_total = Decimal("0")
    unpaid_total = Decimal("0")
    for ln in lines:
        row = dict(ln)
        uid = row.get("user_id")
        if uid:
            rate_info = resolve_worker_hourly_rate(conn, int(uid), organization_id)
            row["worker_category_label"] = rate_info["worker_category_label"]
            row["payment_method"] = row.get("payment_method") or rate_info.get("payment_method")
            if float(row.get("rate") or 0) <= 0 and not rate_info["rate_missing"]:
                row["suggested_rate"] = rate_info["hourly_rate"]
            if float(row.get("rate") or 0) <= 0:
                missing_rates.append(
                    {
                        "user_id": uid,
                        "worker_name": row.get("worker_name_snapshot"),
                        "suggested_rate": rate_info.get("hourly_rate"),
                        "rate_source": rate_info.get("rate_source"),
                    }
                )
            if cat == "w2":
                w4 = fetch_w4_compliance_summary(conn, int(uid))
                row["w4_summary"] = w4
                if not w4.get("w4_on_file"):
                    missing_w4.append(
                        {"user_id": uid, "worker_name": row.get("worker_name_snapshot")}
                    )
        ps = str(row.get("payment_status") or "pending")
        row["payment_status_label"] = _line_payment_status_label(ps)
        amt = _money(row.get("total_amount") or 0)
        gross_total += _money(row.get("gross_amount") or row.get("total_amount") or 0)
        if ps == "paid":
            paid_total += amt
        else:
            unpaid_total += amt
        if cat == "w2":
            row["employee_taxes_total"] = _sum_withholding(
                [row],
                "federal_withholding",
            ) + _sum_withholding([row], "state_withholding") + _sum_withholding(
                [row], "city_withholding"
            ) + _sum_withholding([row], "social_security_withholding") + _sum_withholding(
                [row], "medicare_withholding"
            )
            if row.get("tax_calc_status") == "pending" or row.get("net_pay") is None:
                row["net_pay_display"] = None
                row["net_pay_note"] = (
                    row.get("w4_summary") or {}
                ).get("tax_calc_note") or "Tax calculation pending"
        enriched_lines.append(json_safe(row))
    batch = dict(batch)
    batch["lines"] = enriched_lines
    batch["payment_status"] = _batch_payment_status(enriched_lines)
    batch["summary"] = json_safe(
        {
            "worker_category": cat,
            "worker_category_label": CATEGORY_LABELS.get(cat, cat),
            "gross_total": float(gross_total),
            "taxes_withheld_total": _sum_withholding(enriched_lines, "federal_withholding")
            + _sum_withholding(enriched_lines, "state_withholding")
            + _sum_withholding(enriched_lines, "city_withholding")
            + _sum_withholding(enriched_lines, "social_security_withholding")
            + _sum_withholding(enriched_lines, "medicare_withholding"),
            "net_pay_total": None if cat == "w2" else float(gross_total),
            "net_pay_note": (
                "W-2 net pay requires withholding engine (pending)."
                if cat == "w2"
                else None
            ),
            "payout_total": float(_money(batch.get("total_payout_amount") or 0)),
            "paid_amount": float(paid_total),
            "unpaid_amount": float(unpaid_total),
            "missing_rate_count": len(missing_rates),
            "missing_w4_count": len(missing_w4),
        }
    )
    warnings: list[str] = []
    if missing_rates:
        warnings.append(
            f"{len(missing_rates)} worker(s) have no hourly rate — set rate in Attendance Setup, "
            "employee profile, or contractor profile before approving the batch."
        )
    if cat == "w2" and missing_w4:
        warnings.append(
            f"{len(missing_w4)} W-2 employee(s) missing W-4 on file — complete Compliance tab before payroll."
        )
    if cat == "w2":
        warnings.append(
            "W-2 federal / NY / NYC withholding is not calculated yet — gross pay only until tax engine ships."
        )
    batch["warnings"] = warnings
    batch["missing_rates"] = missing_rates
    batch["missing_w4"] = missing_w4
    batch["available_actions"] = _available_batch_actions(batch)
    return json_safe(batch)


def _available_batch_actions(batch: dict) -> list[str]:
    st = str(batch.get("status") or "draft")
    actions: list[str] = []
    if st == "draft":
        actions.append("hours_reviewed")
    elif st == "hours_reviewed":
        actions.append("send_to_accountant")
    elif st in ("sent_to_accountant", "accountant_reviewed", "approved_for_payment"):
        actions.append("mark_paid")
        actions.append("mark_line_paid")
        actions.append("mark_line_unpaid")
    return actions


def validate_batch_for_workflow(batch: dict, action: str) -> None:
    missing = batch.get("missing_rates") or []
    if action in ("hours_reviewed", "send_to_accountant") and missing:
        names = ", ".join(m.get("worker_name") or "?" for m in missing[:5])
        extra = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
        raise ValueError(f"Cannot proceed — missing hourly rate for: {names}{extra}")
    if action == "send_to_accountant" and str(batch.get("worker_category")) == "w2":
        missing_w4 = batch.get("missing_w4") or []
        if missing_w4:
            names = ", ".join(m.get("worker_name") or "?" for m in missing_w4[:5])
            raise ValueError(f"Cannot send W-2 batch — missing W-4 for: {names}")
    lines = batch.get("lines") or []
    if action in ("hours_reviewed", "send_to_accountant") and not lines:
        raise ValueError("Batch has no worker lines.")


def refresh_batch_line_rates(conn, organization_id: int, batch_id: int) -> dict:
    """Re-apply hourly rates from worker profiles onto batch lines."""
    batch = get_payout_batch(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    if str(batch.get("status") or "") not in ("draft", "hours_reviewed"):
        raise ValueError("Only draft batches can refresh rates")
    from backend.payroll_operations import update_payout_batch_line

    for ln in batch.get("lines") or []:
        uid = ln.get("user_id")
        if not uid:
            continue
        rate = resolve_rate_for_batch_line(conn, organization_id, int(uid))
        if rate <= 0:
            continue
        if float(ln.get("rate") or 0) <= 0 or float(ln.get("rate") or 0) != rate:
            update_payout_batch_line(
                conn,
                organization_id,
                batch_id,
                int(ln["id"]),
                {
                    "approved_hours": ln.get("approved_hours"),
                    "rate": rate,
                    "adjustments": ln.get("adjustments") or 0,
                    "line_status": ln.get("line_status") or "approved",
                },
            )
    out = get_payout_batch(conn, organization_id, batch_id) or {}
    return enrich_payout_batch(conn, organization_id, out)


def apply_batch_workflow_action(
    conn,
    organization_id: int,
    batch_id: int,
    action: str,
    *,
    actor_id: Optional[int] = None,
    line_id: Optional[int] = None,
    payment_date: Optional[str] = None,
    payment_reference: Optional[str] = None,
) -> dict:
    if action not in BATCH_ACTIONS:
        raise ValueError(f"Unknown action: {action}")
    batch = get_payout_batch(conn, organization_id, batch_id)
    if not batch:
        raise ValueError("Batch not found")
    batch = enrich_payout_batch(conn, organization_id, batch)
    ensure_payout_batch_line_extensions(conn.cursor())
    c = conn.cursor()
    pd = payment_date or str(date.today())
    if action == "hours_reviewed":
        validate_batch_for_workflow(batch, action)
        c.execute(
            """
            UPDATE payout_batches SET status='hours_reviewed', approved_by=COALESCE(approved_by, %s),
            updated_at=CURRENT_TIMESTAMP WHERE id=%s AND organization_id=%s
            """,
            (actor_id, int(batch_id), int(organization_id)),
        )
        c.execute(
            """
            UPDATE payout_batch_lines SET payment_status='approved_unpaid', line_status='approved'
            WHERE batch_id=%s AND organization_id=%s AND payment_status='pending'
            """,
            (int(batch_id), int(organization_id)),
        )
    elif action == "send_to_accountant":
        validate_batch_for_workflow(batch, action)
        c.execute(
            """
            UPDATE payout_batches SET status='sent_to_accountant',
            sent_to_accountant_at=COALESCE(sent_to_accountant_at, NOW()),
            approved_by=COALESCE(approved_by, %s), updated_at=CURRENT_TIMESTAMP
            WHERE id=%s AND organization_id=%s
            """,
            (actor_id, int(batch_id), int(organization_id)),
        )
        c.execute(
            """
            UPDATE payout_batch_lines SET payment_status='approved_unpaid', line_status='approved'
            WHERE batch_id=%s AND organization_id=%s AND payment_status IN ('pending', 'approved_unpaid')
            """,
            (int(batch_id), int(organization_id)),
        )
    elif action == "mark_paid":
        c.execute(
            """
            UPDATE payout_batches SET status='paid', paid_at=COALESCE(paid_at, NOW()),
            updated_at=CURRENT_TIMESTAMP WHERE id=%s AND organization_id=%s
            """,
            (int(batch_id), int(organization_id)),
        )
        c.execute(
            """
            UPDATE payout_batch_lines SET payment_status='paid', payment_date=COALESCE(payment_date, %s),
            line_status='approved'
            WHERE batch_id=%s AND organization_id=%s AND payment_status != 'paid'
            """,
            (pd, int(batch_id), int(organization_id)),
        )
    elif action == "mark_line_paid":
        if not line_id:
            raise ValueError("line_id required")
        c.execute(
            """
            UPDATE payout_batch_lines SET payment_status='paid', payment_date=%s,
            payment_reference=COALESCE(%s, payment_reference), line_status='approved'
            WHERE id=%s AND batch_id=%s AND organization_id=%s
            """,
            (pd, payment_reference, int(line_id), int(batch_id), int(organization_id)),
        )
    elif action == "mark_line_unpaid":
        if not line_id:
            raise ValueError("line_id required")
        c.execute(
            """
            UPDATE payout_batch_lines SET payment_status='approved_unpaid', payment_date=NULL
            WHERE id=%s AND batch_id=%s AND organization_id=%s
            """,
            (int(line_id), int(batch_id), int(organization_id)),
        )
    elif action == "refresh_rates":
        conn.commit()
        return refresh_batch_line_rates(conn, organization_id, batch_id)
    conn.commit()
    out = get_payout_batch(conn, organization_id, batch_id) or {}
    return enrich_payout_batch(conn, organization_id, out)


def payroll_due_summary(
    conn,
    organization_id: int,
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> dict:
    """Approved unpaid hours/value by worker category before batch creation."""
    if not payroll_profiles_active(conn):
        return {"categories": {}, "grand_total": 0, "grand_hours": 0, "workers": []}
    records = list_time_records(
        conn,
        organization_id,
        from_date=from_date,
        to_date=to_date,
        status_filter="approved",
        limit=5000,
    )
    by_cat: dict[str, dict] = {
        cat: {"hours": 0.0, "gross": 0.0, "workers": 0, "missing_rates": 0}
        for cat in WORKER_CATEGORIES
    }
    worker_map: dict[tuple[str, int], dict] = {}
    for rec in records:
        uid = int(rec["user_id"])
        cat = worker_category_for_user(conn, uid)
        hours = float(rec.get("approved_hours") or 0)
        rate_info = resolve_worker_hourly_rate(conn, uid, organization_id)
        rate = float(rate_info.get("hourly_rate") or 0)
        gross = round(hours * rate, 2)
        by_cat[cat]["hours"] += hours
        by_cat[cat]["gross"] += gross
        if rate_info.get("rate_missing"):
            by_cat[cat]["missing_rates"] += 1
        key = (cat, uid)
        if key not in worker_map:
            worker_map[key] = {
                "user_id": uid,
                "worker_name": rec.get("worker_name"),
                "worker_category": cat,
                "worker_category_label": CATEGORY_LABELS.get(cat, cat),
                "approved_hours": 0.0,
                "hourly_rate": rate if rate > 0 else None,
                "rate_missing": rate_info.get("rate_missing"),
                "rate_source": rate_info.get("rate_source"),
                "gross_due": 0.0,
                "payment_method": rate_info.get("payment_method"),
            }
        worker_map[key]["approved_hours"] += hours
        worker_map[key]["gross_due"] += gross
    for cat in by_cat:
        by_cat[cat]["workers"] = sum(
            1 for (c, _uid) in worker_map if c == cat
        )
        by_cat[cat]["hours"] = round(by_cat[cat]["hours"], 2)
        by_cat[cat]["gross"] = round(by_cat[cat]["gross"], 2)
    workers = sorted(worker_map.values(), key=lambda w: (w["worker_category"], w["worker_name"] or ""))
    grand_total = round(sum(by_cat[c]["gross"] for c in WORKER_CATEGORIES), 2)
    grand_hours = round(sum(by_cat[c]["hours"] for c in WORKER_CATEGORIES), 2)
    return json_safe(
        {
            "from_date": from_date,
            "to_date": to_date,
            "categories": {
                cat: {**by_cat[cat], "label": CATEGORY_LABELS.get(cat, cat)} for cat in WORKER_CATEGORIES
            },
            "grand_total": grand_total,
            "grand_hours": grand_hours,
            "workers": workers,
        }
    )


def worker_payment_overview(
    conn, organization_id: int, *, year: Optional[int] = None
) -> list[dict]:
    """Per-worker payout summary for payment history screen."""
    from backend.payroll_operations import accountant_ytd_summary

    year = int(year or date.today().year)
    ytd = accountant_ytd_summary(conn, organization_id, year=year)
    ensure_payout_batch_line_extensions(conn.cursor())
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT pbl.user_id, pb.worker_category,
               SUM(CASE WHEN pbl.payment_status != 'paid' THEN pbl.total_amount ELSE 0 END) AS open_unpaid,
               MAX(CASE WHEN pbl.payment_status = 'paid' THEN pbl.payment_date END) AS last_paid
        FROM payout_batch_lines pbl
        JOIN payout_batches pb ON pb.id = pbl.batch_id
        WHERE pb.organization_id = %s AND pbl.user_id IS NOT NULL
          AND pb.status NOT IN ('closed')
        GROUP BY pbl.user_id, pb.worker_category
        """,
        (int(organization_id),),
    )
    open_by_user = {
        (int(r["user_id"]), str(r["worker_category"])): r for r in c.fetchall() or []
    }
    out = []
    for row in ytd:
        uid = int(row["user_id"])
        cat = str(row["worker_category"])
        rate_info = resolve_worker_hourly_rate(conn, uid, organization_id)
        open_row = open_by_user.get((uid, cat)) or {}
        out.append(
            json_safe(
                {
                    **row,
                    "hourly_rate": rate_info.get("hourly_rate"),
                    "rate_missing": rate_info.get("rate_missing"),
                    "rate_source": rate_info.get("rate_source"),
                    "payment_method": rate_info.get("payment_method"),
                    "open_unpaid_amount": float(open_row.get("open_unpaid") or 0),
                    "last_payment_date": row.get("last_payment_date")
                    or (
                        str(open_row["last_paid"])[:10]
                        if open_row.get("last_paid")
                        else None
                    ),
                }
            )
        )
    return out


def resolve_rate_for_batch_line(
    conn, organization_id: int, user_id: int
) -> float:
    info = resolve_worker_hourly_rate(conn, user_id, organization_id)
    return float(info.get("hourly_rate") or 0)


def apply_w2_fields_on_line_insert(
    conn, user_id: int, worker_category: str, gross: float
) -> dict[str, Any]:
    if worker_category != "w2":
        return {"tax_calc_status": "not_applicable"}
    tax = prepare_w2_line_tax_fields(conn, user_id, gross)
    return {
        "gross_wages": tax["gross_wages"],
        "tax_calc_status": tax["tax_calc_status"],
    }
