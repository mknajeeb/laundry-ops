"""Cross-period Payroll Report: query, Excel, and PDF/HTML exports.

OT amounts use premium-only presentation (see payroll_overtime.earnings_breakdown_from_line).
Does not mutate stored gross or historical payroll amounts.

Phase 1: batch official_pay_date is the sole reporting Pay Date (no period-end fallback).
"""

from __future__ import annotations

import calendar
import io
import json
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from backend.payroll_operations import BATCH_STATUSES, CATEGORY_LABELS, WORKER_CATEGORIES
from backend.payroll_overtime import earnings_breakdown_from_line
from backend.payroll_status_display import (
    DISPLAY_STATUS_LABELS,
    compute_display_status,
)
from backend.ta_helpers import json_safe, table_has_column


# Default custom-range rule (Pay Date basis). Never the legacy combined OR.
DATE_MATCH_RULE = (
    "Includes rows where the official Pay Date falls within the selected range."
)
DATE_MATCH_RULE_PERIOD_OVERLAP = (
    "Includes rows where the pay period overlaps the selected range."
)
DATE_MATCH_RULE_MONTHLY = (
    "Includes rows whose official Pay Date falls in the selected month and year. "
    "Rows without an official Pay Date are excluded."
)
DATE_MATCH_RULE_PAYROLL_PERIOD = "Includes rows for the selected payroll period(s)."
DATE_MATCH_RULE_ALL_HISTORY = (
    "Includes all payroll history. Rows without an official Pay Date show Pay Date Missing."
)

REPORT_TYPES = (
    "payroll_period",
    "monthly_paid",
    "custom_range",
    "all_history",
)

DATE_BASES = ("pay_date", "period_overlap")

# Record-level columns (Excel / JSON). PDF uses a readable subset.
REPORT_COLUMNS = (
    ("employee_name", "Employee"),
    ("employee_category", "Category"),
    ("batch_name", "Payroll batch"),
    ("batch_id", "Batch ID"),
    ("pay_period_start", "Payroll-period start"),
    ("pay_period_end", "Payroll-period end"),
    ("pay_date", "Pay Date"),
    ("finalized_date", "Finalized date"),
    ("regular_hours", "Regular hours"),
    ("ot_hours", "OT hours"),
    ("base_earnings", "Regular/Base earnings"),
    ("ot_premium", "OT premium"),
    ("other_earnings", "Other earnings"),
    ("gross_pay", "Gross pay"),
    ("employee_tax_deductions", "Employee taxes"),
    ("other_deductions", "Deductions"),
    ("net_pay", "Net pay"),
    ("employer_taxes", "Employer taxes"),
    ("total_payroll_cost", "Total payroll cost"),
    ("payroll_status", "Payroll status"),
    ("payment_status", "Payment status"),
)

PDF_COLUMNS = (
    ("employee_name", "Employee"),
    ("employee_category", "Category"),
    ("pay_date_display", "Pay Date"),
    ("regular_hours", "Reg hrs"),
    ("ot_hours", "OT hrs"),
    ("base_earnings", "Base"),
    ("ot_premium", "OT prem"),
    ("gross_pay", "Gross"),
    ("employee_tax_deductions", "EE taxes"),
    ("net_pay", "Net"),
    ("employer_taxes", "ER taxes"),
    ("total_payroll_cost", "Total cost"),
    ("payment_status", "Payment"),
)

HOUR_TOTAL_KEYS = ("regular_hours", "ot_hours")
MONEY_TOTAL_KEYS = (
    "base_earnings",
    "ot_premium",
    "other_earnings",
    "gross_pay",
    "employee_tax_deductions",
    "other_deductions",
    "net_pay",
    "employer_taxes",
    "total_payroll_cost",
)

DATE_CELL_KEYS = (
    "pay_date",
    "pay_period_start",
    "pay_period_end",
    "finalized_date",
    "official_pay_date",
)


def date_match_rule_text(
    report_type: str,
    *,
    date_basis: str = "pay_date",
) -> str:
    rt = str(report_type or "").strip().lower()
    if rt == "monthly_paid":
        return DATE_MATCH_RULE_MONTHLY
    if rt == "payroll_period":
        return DATE_MATCH_RULE_PAYROLL_PERIOD
    if rt == "all_history":
        return DATE_MATCH_RULE_ALL_HISTORY
    if rt == "custom_range":
        basis = str(date_basis or "pay_date").strip().lower()
        if basis == "period_overlap":
            return DATE_MATCH_RULE_PERIOD_OVERLAP
        return DATE_MATCH_RULE
    return DATE_MATCH_RULE


def _parse_ymd(val: Any) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()[:10]
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _money(val: Any) -> float:
    try:
        return float(Decimal(str(val if val is not None else 0)))
    except Exception:
        return 0.0


def _parse_details(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _batch_official_pay_date(batch: dict) -> Optional[str]:
    """Reporting Pay Date from batch official_pay_date only — no period-end fallback."""
    d = _parse_ymd(batch.get("official_pay_date"))
    return d.isoformat() if d else None


def _periods_overlap(ps: Optional[date], pe: Optional[date], start: date, end: date) -> bool:
    if not ps and not pe:
        return False
    period_start = ps or pe
    period_end = pe or ps
    assert period_start is not None and period_end is not None
    return period_start <= end and period_end >= start


def _row_matches_pay_date(row: dict, start: date, end: date) -> bool:
    pd = _parse_ymd(row.get("pay_date") or row.get("official_pay_date"))
    if not pd:
        return False
    return start <= pd <= end


def _row_matches_period_overlap(row: dict, start: date, end: date) -> bool:
    ps = _parse_ymd(row.get("pay_period_start"))
    pe = _parse_ymd(row.get("pay_period_end"))
    return _periods_overlap(ps, pe, start, end)


def _row_matches_date_range(
    row: dict, start: date, end: date, *, date_basis: str = "pay_date"
) -> bool:
    """Custom range match by explicit basis only (never combined OR)."""
    basis = str(date_basis or "pay_date").strip().lower()
    if basis == "period_overlap":
        return _row_matches_period_overlap(row, start, end)
    return _row_matches_pay_date(row, start, end)


def _employee_tax_total(details: dict) -> float:
    ded = details.get("employee_deductions") or {}
    return round(sum(_money(v) for v in ded.values()), 2)


def _employer_tax_total(details: dict) -> float:
    er = details.get("employer_taxes") or {}
    return round(sum(_money(v) for v in er.values()), 2)


def _other_deductions_total(details: dict) -> float:
    """Non-tax employee deductions if present (catch-up / misc)."""
    settlement = details.get("settlement") or {}
    catch_up = _money(settlement.get("catch_up_withholding"))
    misc = details.get("other_deductions") or details.get("voluntary_deductions") or {}
    misc_total = sum(_money(v) for v in misc.values()) if isinstance(misc, dict) else _money(misc)
    return round(catch_up + misc_total, 2)


def _payment_status_label(st: str) -> str:
    key = str(st or "pending").strip().lower()
    labels = {
        "paid": "Paid",
        "approved_unpaid": "Approved — unpaid",
        "pending": "Pending",
    }
    return labels.get(key, key.replace("_", " ").title() or "Pending")


def _finalized_date_str(batch: dict) -> str:
    raw = batch.get("payout_details_finalized_at")
    if not raw:
        return ""
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    s = str(raw).strip()
    if not s:
        return ""
    d = _parse_ymd(s[:10])
    return d.isoformat() if d else s[:19]


def build_report_row(batch: dict, line: dict) -> dict[str, Any]:
    details = line.get("payout_details") or _parse_details(line.get("payout_details_json"))
    breakdown = earnings_breakdown_from_line(line)
    cat = str(batch.get("worker_category") or "")
    display_status = compute_display_status(batch)
    pay_date = _batch_official_pay_date(batch)
    pay_date_missing = pay_date is None
    emp_tax = _employee_tax_total(details)
    other_ded = _other_deductions_total(details)
    settlement = details.get("settlement") or {}
    net = settlement.get("amount_paid")
    if net is None or str(net).strip() == "":
        net = line.get("net_pay")
    if net is None or str(net).strip() == "":
        net = breakdown["gross_pay"] - emp_tax - other_ded

    ps = batch.get("pay_period_start")
    pe = batch.get("pay_period_end")
    period_label = ""
    if ps and pe:
        period_label = f"{str(ps)[:10]} – {str(pe)[:10]}"
    elif ps or pe:
        period_label = str(ps or pe)[:10]

    employer_taxes = _employer_tax_total(details)
    gross_pay = breakdown["gross_pay"]
    total_payroll_cost = round(_money(gross_pay) + employer_taxes, 2)

    payment_st = str(line.get("payment_status") or "pending")
    return {
        "line_id": line.get("id"),
        "batch_id": batch.get("id"),
        "user_id": line.get("user_id"),
        "employee_name": line.get("worker_name_snapshot") or "",
        "employee_category": CATEGORY_LABELS.get(cat, cat),
        "worker_category": cat,
        "payroll_period": period_label,
        "pay_period_start": str(ps)[:10] if ps else "",
        "pay_period_end": str(pe)[:10] if pe else "",
        "pay_date": pay_date or "",
        "official_pay_date": pay_date or "",
        "pay_date_missing": pay_date_missing,
        "pay_date_display": pay_date if pay_date else "Pay Date Missing",
        "finalized_date": _finalized_date_str(batch),
        "regular_hours": breakdown["regular_hours"],
        "ot_hours": breakdown["ot_hours"],
        "regular_rate": breakdown["regular_rate"],
        "ot_rate": breakdown["ot_rate"],
        "base_earnings": breakdown["base_earnings"],
        "ot_premium": breakdown["ot_premium"],
        "other_earnings": breakdown["other_earnings"],
        "gross_pay": gross_pay,
        "employee_tax_deductions": emp_tax,
        "other_deductions": other_ded,
        "net_pay": round(_money(net), 2),
        "employer_taxes": employer_taxes,
        "total_payroll_cost": total_payroll_cost,
        "payment_status": _payment_status_label(payment_st),
        "payment_status_key": payment_st,
        "payroll_status": DISPLAY_STATUS_LABELS.get(display_status, display_status),
        "payroll_status_key": display_status,
        "batch_status": batch.get("status"),
        "batch_name": batch.get("batch_name") or "",
    }


def _sum_totals(rows: list[dict]) -> dict[str, float]:
    totals = {k: 0.0 for k in (*HOUR_TOTAL_KEYS, *MONEY_TOTAL_KEYS)}
    for row in rows:
        for k in totals:
            totals[k] = round(totals[k] + _money(row.get(k)), 2)
    return totals


def _build_summary(rows: list[dict], totals: dict[str, float]) -> dict[str, Any]:
    batch_ids = {r.get("batch_id") for r in rows if r.get("batch_id") is not None}
    user_ids = {r.get("user_id") for r in rows if r.get("user_id") is not None}
    return {
        "batch_count": len(batch_ids),
        "unique_employees": len(user_ids),
        **totals,
    }


def _infer_report_type(
    *,
    report_type: Optional[str],
    all_history: bool,
    month: Optional[int],
    year: Optional[int],
    period_pairs: list[tuple[str, str]],
    date_from: Optional[str],
    date_to: Optional[str],
) -> str:
    if report_type:
        rt = str(report_type).strip().lower()
        if rt in REPORT_TYPES:
            return rt
        raise ValueError(f"Invalid report_type: {report_type}")
    if all_history:
        return "all_history"
    if month is not None and year is not None:
        return "monthly_paid"
    if period_pairs:
        return "payroll_period"
    if date_from and date_to:
        return "custom_range"
    return "all_history"


def _normalize_date_basis(date_basis: Optional[str]) -> str:
    basis = str(date_basis or "pay_date").strip().lower()
    if basis not in DATE_BASES:
        raise ValueError("date_basis must be 'pay_date' or 'period_overlap'")
    return basis


def query_payroll_report(
    conn,
    organization_id: int,
    *,
    period_starts: Optional[list[str]] = None,
    period_ends: Optional[list[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    all_history: bool = False,
    user_id: Optional[int] = None,
    worker_category: Optional[str] = None,
    payroll_status: Optional[str] = None,
    payment_status: Optional[str] = None,
    limit: int = 5000,
    report_type: Optional[str] = None,
    date_basis: str = "pay_date",
    month: Optional[int] = None,
    year: Optional[int] = None,
) -> dict[str, Any]:
    """Return filtered payroll report rows + totals across categories/periods."""
    from backend.payroll_operations import ensure_payout_batches_tables

    ensure_payout_batches_tables(conn.cursor())
    c = conn.cursor(dictionary=True)
    has_details = table_has_column(c, "payout_batch_lines", "payout_details_json")
    has_official_pay_date = table_has_column(c, "payout_batches", "official_pay_date")

    select_cols = """
        pb.id AS batch_id,
        pb.batch_name,
        pb.worker_category,
        pb.pay_period_start,
        pb.pay_period_end,
        pb.status AS batch_status,
        pb.payout_details_finalized_at,
        pbl.id AS line_id,
        pbl.user_id,
        pbl.worker_name_snapshot,
        pbl.approved_hours,
        pbl.ot_hours,
        pbl.rate,
        pbl.ot_rate,
        pbl.gross_amount,
        pbl.total_amount,
        pbl.gross_wages,
        pbl.sick_pay_amount,
        pbl.bonus_tip_amount,
        pbl.reimbursement_amount,
        pbl.adjustments,
        pbl.payment_status,
        pbl.net_pay
    """
    if has_official_pay_date:
        select_cols += ", pb.official_pay_date"
    if has_details:
        select_cols += ", pbl.payout_details_json"

    period_pairs: list[tuple[str, str]] = []
    starts = [str(s).strip()[:10] for s in (period_starts or []) if str(s).strip()]
    ends = [str(e).strip()[:10] for e in (period_ends or []) if str(e).strip()]
    if starts and ends and len(starts) == len(ends):
        period_pairs = list(zip(starts, ends))
    elif starts and ends and len(starts) == 1 and len(ends) == 1:
        period_pairs = [(starts[0], ends[0])]

    month_i = int(month) if month is not None and str(month).strip() != "" else None
    year_i = int(year) if year is not None and str(year).strip() != "" else None

    resolved_type = _infer_report_type(
        report_type=report_type,
        all_history=all_history,
        month=month_i,
        year=year_i,
        period_pairs=period_pairs,
        date_from=date_from,
        date_to=date_to,
    )
    basis = _normalize_date_basis(date_basis)
    match_rule = date_match_rule_text(resolved_type, date_basis=basis)

    if resolved_type == "monthly_paid":
        if month_i is None or year_i is None:
            raise ValueError("monthly_paid requires month and year")
        if month_i < 1 or month_i > 12:
            raise ValueError("month must be 1–12")
        if not has_official_pay_date:
            # Column missing: nothing can match official pay date filters.
            empty_totals = _sum_totals([])
            return json_safe(
                {
                    "rows": [],
                    "totals": empty_totals,
                    "summary": _build_summary([], empty_totals),
                    "count": 0,
                    "report_type": resolved_type,
                    "date_basis": basis,
                    "excluded_missing_pay_date_count": 0,
                    "filters": {
                        "report_type": resolved_type,
                        "date_basis": basis,
                        "period_starts": starts,
                        "period_ends": ends,
                        "date_from": date_from or "",
                        "date_to": date_to or "",
                        "month": month_i,
                        "year": year_i,
                        "all_history": False,
                        "user_id": int(user_id) if user_id else None,
                        "worker_category": worker_category or "all",
                        "payroll_status": payroll_status or "all",
                        "payment_status": payment_status or "all",
                        "date_match_rule": match_rule,
                    },
                    "date_match_rule": match_rule,
                    "columns": [{"key": k, "label": lab} for k, lab in REPORT_COLUMNS],
                    "categories": [
                        {"value": "all", "label": "All categories"},
                        *[{"value": c, "label": CATEGORY_LABELS[c]} for c in WORKER_CATEGORIES],
                    ],
                    "payroll_statuses": [
                        {"value": "all", "label": "All payroll statuses"},
                        *[
                            {"value": k, "label": v}
                            for k, v in DISPLAY_STATUS_LABELS.items()
                        ],
                    ],
                    "payment_statuses": [
                        {"value": "all", "label": "All payment statuses"},
                        {"value": "pending", "label": "Pending"},
                        {"value": "approved_unpaid", "label": "Approved — unpaid"},
                        {"value": "paid", "label": "Paid"},
                    ],
                    "batch_statuses": list(BATCH_STATUSES),
                }
            )

    q = f"""
        SELECT {select_cols}
        FROM payout_batch_lines pbl
        INNER JOIN payout_batches pb ON pb.id = pbl.batch_id
        WHERE pb.organization_id = %s AND pbl.organization_id = %s
    """
    params: list[Any] = [int(organization_id), int(organization_id)]

    if resolved_type == "payroll_period" and period_pairs:
        placeholders = " OR ".join(
            ["(pb.pay_period_start = %s AND pb.pay_period_end = %s)"] * len(period_pairs)
        )
        q += f" AND ({placeholders})"
        for ps, pe in period_pairs:
            params.extend([ps, pe])
    elif resolved_type == "monthly_paid":
        q += (
            " AND pb.official_pay_date IS NOT NULL"
            " AND MONTH(pb.official_pay_date) = %s"
            " AND YEAR(pb.official_pay_date) = %s"
        )
        params.extend([month_i, year_i])

    if worker_category and worker_category != "all":
        if worker_category not in WORKER_CATEGORIES:
            raise ValueError("Invalid worker_category")
        q += " AND pb.worker_category = %s"
        params.append(worker_category)

    if user_id:
        q += " AND pbl.user_id = %s"
        params.append(int(user_id))

    if payment_status and payment_status != "all":
        q += " AND pbl.payment_status = %s"
        params.append(str(payment_status))

    if resolved_type == "monthly_paid" and has_official_pay_date:
        q += " ORDER BY pb.official_pay_date, pb.pay_period_start, pb.worker_category, pbl.worker_name_snapshot LIMIT %s"
    else:
        q += " ORDER BY pb.pay_period_start DESC, pb.worker_category, pbl.worker_name_snapshot LIMIT %s"
    params.append(int(limit))

    c.execute(q, params)
    raw_rows = c.fetchall() or []

    excluded_missing_pay_date_count = 0
    if resolved_type == "monthly_paid" and has_official_pay_date:
        # Informational: lines matching other filters but missing official_pay_date.
        miss_q = """
            SELECT COUNT(*) AS cnt
            FROM payout_batch_lines pbl
            INNER JOIN payout_batches pb ON pb.id = pbl.batch_id
            WHERE pb.organization_id = %s AND pbl.organization_id = %s
              AND pb.official_pay_date IS NULL
        """
        miss_params: list[Any] = [int(organization_id), int(organization_id)]
        if worker_category and worker_category != "all":
            miss_q += " AND pb.worker_category = %s"
            miss_params.append(worker_category)
        if user_id:
            miss_q += " AND pbl.user_id = %s"
            miss_params.append(int(user_id))
        if payment_status and payment_status != "all":
            miss_q += " AND pbl.payment_status = %s"
            miss_params.append(str(payment_status))
        c.execute(miss_q, miss_params)
        miss_row = c.fetchone() or {}
        excluded_missing_pay_date_count = int(miss_row.get("cnt") or 0)

    df = _parse_ymd(date_from)
    dt = _parse_ymd(date_to)
    use_custom_range = resolved_type == "custom_range" and bool(df and dt)
    if resolved_type == "custom_range" and not (df and dt):
        raise ValueError("custom_range requires date_from and date_to")

    rows: list[dict] = []
    seen_line_ids: set[Any] = set()
    for raw in raw_rows:
        line_id = raw.get("line_id")
        if line_id is not None and line_id in seen_line_ids:
            continue
        batch = {
            "id": raw.get("batch_id"),
            "batch_name": raw.get("batch_name"),
            "worker_category": raw.get("worker_category"),
            "pay_period_start": raw.get("pay_period_start"),
            "pay_period_end": raw.get("pay_period_end"),
            "status": raw.get("batch_status"),
            "payout_details_finalized_at": raw.get("payout_details_finalized_at"),
            "official_pay_date": raw.get("official_pay_date") if has_official_pay_date else None,
        }
        line = {
            "id": line_id,
            "user_id": raw.get("user_id"),
            "worker_name_snapshot": raw.get("worker_name_snapshot"),
            "approved_hours": raw.get("approved_hours"),
            "ot_hours": raw.get("ot_hours"),
            "rate": raw.get("rate"),
            "ot_rate": raw.get("ot_rate"),
            "gross_amount": raw.get("gross_amount"),
            "total_amount": raw.get("total_amount"),
            "gross_wages": raw.get("gross_wages"),
            "sick_pay_amount": raw.get("sick_pay_amount"),
            "bonus_tip_amount": raw.get("bonus_tip_amount"),
            "reimbursement_amount": raw.get("reimbursement_amount"),
            "adjustments": raw.get("adjustments"),
            "payment_status": raw.get("payment_status"),
            "net_pay": raw.get("net_pay"),
            "payout_details_json": raw.get("payout_details_json"),
        }
        row = build_report_row(batch, line)
        if use_custom_range and not _row_matches_date_range(row, df, dt, date_basis=basis):
            continue
        if payroll_status and payroll_status != "all":
            if row["payroll_status_key"] != payroll_status:
                continue
        if line_id is not None:
            seen_line_ids.add(line_id)
        rows.append(row)

    totals = _sum_totals(rows)
    summary = _build_summary(rows, totals)
    filters = {
        "report_type": resolved_type,
        "date_basis": basis if resolved_type == "custom_range" else "",
        "period_starts": starts,
        "period_ends": ends,
        "date_from": date_from or "",
        "date_to": date_to or "",
        "month": month_i,
        "year": year_i,
        "all_history": resolved_type == "all_history",
        "user_id": int(user_id) if user_id else None,
        "worker_category": worker_category or "all",
        "payroll_status": payroll_status or "all",
        "payment_status": payment_status or "all",
        "date_match_rule": match_rule,
    }
    out: dict[str, Any] = {
        "rows": rows,
        "totals": totals,
        "summary": summary,
        "count": len(rows),
        "report_type": resolved_type,
        "date_basis": basis if resolved_type == "custom_range" else None,
        "report_heading": report_heading(filters),
        "filters": filters,
        "date_match_rule": match_rule,
        "columns": [{"key": k, "label": lab} for k, lab in REPORT_COLUMNS],
        "categories": [
            {"value": "all", "label": "All categories"},
            *[{"value": c, "label": CATEGORY_LABELS[c]} for c in WORKER_CATEGORIES],
        ],
        "payroll_statuses": [
            {"value": "all", "label": "All payroll statuses"},
            *[
                {"value": k, "label": v}
                for k, v in DISPLAY_STATUS_LABELS.items()
            ],
        ],
        "payment_statuses": [
            {"value": "all", "label": "All payment statuses"},
            {"value": "pending", "label": "Pending"},
            {"value": "approved_unpaid", "label": "Approved — unpaid"},
            {"value": "paid", "label": "Paid"},
        ],
        "batch_statuses": list(BATCH_STATUSES),
    }
    if resolved_type == "monthly_paid":
        out["excluded_missing_pay_date_count"] = excluded_missing_pay_date_count
    return json_safe(out)


def list_report_employees(conn, organization_id: int) -> list[dict]:
    """Distinct employees that appear on payout lines (for report filter)."""
    from backend.payroll_operations import ensure_payout_batches_tables

    ensure_payout_batches_tables(conn.cursor())
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT DISTINCT pbl.user_id, pbl.worker_name_snapshot AS name
        FROM payout_batch_lines pbl
        INNER JOIN payout_batches pb ON pb.id = pbl.batch_id
        WHERE pb.organization_id = %s AND pbl.user_id IS NOT NULL
        ORDER BY pbl.worker_name_snapshot
        """,
        (int(organization_id),),
    )
    out = []
    seen = set()
    for row in c.fetchall() or []:
        uid = row.get("user_id")
        if uid in seen:
            continue
        seen.add(uid)
        out.append({"user_id": uid, "name": row.get("name") or f"User {uid}"})
    return out


def list_report_periods(conn, organization_id: int) -> list[dict]:
    """Distinct pay periods across all worker categories."""
    from backend.payroll_operations import ensure_payout_batches_tables

    ensure_payout_batches_tables(conn.cursor())
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT DISTINCT pay_period_start, pay_period_end
        FROM payout_batches
        WHERE organization_id = %s
        ORDER BY pay_period_start DESC
        """,
        (int(organization_id),),
    )
    return [
        {
            "pay_period_start": str(r["pay_period_start"])[:10],
            "pay_period_end": str(r["pay_period_end"])[:10],
            "label": f"{str(r['pay_period_start'])[:10]} – {str(r['pay_period_end'])[:10]}",
        }
        for r in (c.fetchall() or [])
        if r.get("pay_period_start") and r.get("pay_period_end")
    ]


def report_heading(filters: dict) -> str:
    """Dynamic title for screen, PDF, and Excel metadata."""
    rt = str(filters.get("report_type") or "").strip().lower()
    if rt == "all_history" or filters.get("all_history"):
        return "Payroll Reports — All History"
    if rt == "monthly_paid" and filters.get("month") and filters.get("year"):
        m = int(filters["month"])
        y = int(filters["year"])
        return f"Monthly Payroll Paid: {calendar.month_name[m]} {y}"
    if filters.get("period_starts") and filters.get("period_ends"):
        pairs = list(zip(filters["period_starts"], filters["period_ends"]))
        if len(pairs) == 1:
            return f"Payroll Period: {pairs[0][0]} – {pairs[0][1]}"
        return f"Payroll Period Report ({len(pairs)} periods)"
    if filters.get("date_from") and filters.get("date_to"):
        basis = str(filters.get("date_basis") or "pay_date")
        basis_label = "Pay Date" if basis == "pay_date" else "Payroll Period Overlap"
        return (
            f"Payroll Report: {filters['date_from']} – {filters['date_to']} "
            f"({basis_label} Basis)"
        )
    return "Payroll Reports"


def _filter_summary_text(filters: dict) -> str:
    parts = [report_heading(filters)]
    cat = filters.get("worker_category") or "all"
    if cat != "all":
        parts.append(CATEGORY_LABELS.get(cat, cat))
    if filters.get("payroll_status") and filters["payroll_status"] != "all":
        parts.append(
            DISPLAY_STATUS_LABELS.get(filters["payroll_status"], filters["payroll_status"])
        )
    if filters.get("payment_status") and filters["payment_status"] != "all":
        parts.append(_payment_status_label(filters["payment_status"]))
    return " · ".join(parts) if parts else "All records"


def build_payroll_report_xlsx(report: dict) -> bytes:
    """Excel workbook with real numeric/date cells (not formatted text)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, numbers

    wb = Workbook()
    ws = wb.active
    ws.title = "Payroll Reports"
    filters = report.get("filters") or {}
    heading = report.get("report_heading") or report_heading(filters)
    ws.append([heading])
    ws.append([_filter_summary_text(filters)])
    ws.append([report.get("date_match_rule") or DATE_MATCH_RULE])
    summary = report.get("summary") or {}
    if summary:
        ws.append(
            [
                f"Batches: {summary.get('batch_count', 0)}",
                f"Unique employees: {summary.get('unique_employees', 0)}",
                f"Total payroll cost: {round(_money(summary.get('total_payroll_cost')), 2)}",
            ]
        )
    else:
        ws.append([])
    headers = [lab for _, lab in REPORT_COLUMNS]
    ws.append(headers)
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    money_keys = set(MONEY_TOTAL_KEYS)
    hour_keys = set(HOUR_TOTAL_KEYS)
    date_keys = set(DATE_CELL_KEYS)
    header_row = ws.max_row
    data_start = header_row + 1

    for row in report.get("rows") or []:
        excel_vals = []
        for key, _ in REPORT_COLUMNS:
            val = row.get(key)
            if key in date_keys:
                d = _parse_ymd(val)
                excel_vals.append(d if d else None)
            elif key in money_keys or key in hour_keys:
                excel_vals.append(round(_money(val), 2))
            elif key == "batch_id":
                excel_vals.append(int(val) if val is not None and str(val).strip() != "" else None)
            else:
                excel_vals.append(val if val is not None else "")
        ws.append(excel_vals)
        r = ws.max_row
        for col_idx, (key, _) in enumerate(REPORT_COLUMNS, start=1):
            cell = ws.cell(row=r, column=col_idx)
            if key in date_keys and cell.value is not None:
                cell.number_format = "YYYY-MM-DD"
            elif key in money_keys:
                cell.number_format = numbers.FORMAT_NUMBER_COMMA_SEPARATED1
            elif key in hour_keys:
                cell.number_format = "0.00"

    totals = report.get("totals") or {}
    total_row = []
    for key, _lab in REPORT_COLUMNS:
        if key == "employee_name":
            total_row.append("Totals")
        elif key in totals:
            total_row.append(round(_money(totals[key]), 2))
        else:
            total_row.append("")
    ws.append(total_row)
    totals_excel_row = ws.max_row
    for cell in ws[totals_excel_row]:
        cell.font = Font(bold=True)
    for col_idx, (key, _) in enumerate(REPORT_COLUMNS, start=1):
        cell = ws.cell(row=totals_excel_row, column=col_idx)
        if key in money_keys:
            cell.number_format = numbers.FORMAT_NUMBER_COMMA_SEPARATED1
        elif key in hour_keys:
            cell.number_format = "0.00"

    note = totals_excel_row + 2
    ws.cell(
        row=note,
        column=1,
        value=(
            "OT Premium is only the additional amount above the regular hourly rate. "
            "Regular/Base Earnings include overtime hours at the regular rate. "
            "Regular/Base + OT Premium + Other Earnings = Gross Pay. "
            "Total Payroll Cost = Gross Pay + Employer Taxes (stored only). "
            "Pay Date is the batch official_pay_date (no period-end fallback). "
            "Money and hour columns are numeric; date columns are date cells."
        ),
    )
    ws.freeze_panes = f"A{data_start}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _group_key_period(row: dict) -> str:
    return row.get("payroll_period") or (
        f"{row.get('pay_period_start') or ''} – {row.get('pay_period_end') or ''}".strip(" –")
        or "Unknown period"
    )


def _group_key_pay_date(row: dict) -> str:
    return row.get("pay_date") or row.get("official_pay_date") or "Pay Date Missing"


def _group_rows_for_pdf(report: dict) -> list[tuple[str, list[dict]]]:
    """Return ordered (group_heading, rows) based on report_type / date_basis."""
    rows = list(report.get("rows") or [])
    filters = report.get("filters") or {}
    rt = str(
        report.get("report_type") or filters.get("report_type") or ""
    ).strip().lower()
    basis = str(
        report.get("date_basis") or filters.get("date_basis") or "pay_date"
    ).strip().lower()

    if rt == "monthly_paid":
        # Group by pay date, then by period within each pay date.
        by_pay: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            by_pay[_group_key_pay_date(r)].append(r)
        groups: list[tuple[str, list[dict]]] = []
        for pd in sorted(by_pay.keys()):
            by_period: dict[str, list[dict]] = defaultdict(list)
            for r in by_pay[pd]:
                by_period[_group_key_period(r)].append(r)
            for period in sorted(by_period.keys()):
                heading = f"Pay Date: {pd} · Payroll Period: {period}"
                groups.append((heading, by_period[period]))
        return groups

    if rt == "custom_range" and basis == "pay_date":
        by_pay = defaultdict(list)
        for r in rows:
            by_pay[_group_key_pay_date(r)].append(r)
        return [(f"Pay Date: {k}", by_pay[k]) for k in sorted(by_pay.keys())]

    # payroll_period, all_history, custom_range period_overlap → group by period
    by_period = defaultdict(list)
    for r in rows:
        by_period[_group_key_period(r)].append(r)
    return [(f"Payroll Period: {k}", by_period[k]) for k in sorted(by_period.keys())]


def build_payroll_report_html(report: dict) -> str:
    """HTML suitable for browser print / PDF download.

    Grouped by report type / date basis. thead repeats; rows avoid mid-row splits.
    Landscape layout. Grand total at end.
    """
    filters = report.get("filters") or {}
    totals = report.get("totals") or {}
    summary = report.get("summary") or _build_summary(report.get("rows") or [], totals)
    rt = str(report.get("report_type") or filters.get("report_type") or "").strip().lower()

    def fmt_money(v: Any) -> str:
        return f"${_money(v):,.2f}"

    def fmt_hours(v: Any) -> str:
        return f"{_money(v):,.2f}"

    def summary_block(title: str, data: dict) -> str:
        return f"""
<div class="group-summary">
  <strong>{title}</strong>
  <span>Batches: {data.get('batch_count', 0)}</span>
  <span>Employees: {data.get('unique_employees', 0)}</span>
  <span>Gross: {fmt_money(data.get('gross_pay'))}</span>
  <span>ER taxes: {fmt_money(data.get('employer_taxes'))}</span>
  <span>Total payroll cost: {fmt_money(data.get('total_payroll_cost'))}</span>
  <span>Net: {fmt_money(data.get('net_pay'))}</span>
</div>"""

    def rows_table(group_rows: list[dict], subtotal: dict) -> str:
        body = []
        for row in group_rows:
            cells = []
            for key, _ in PDF_COLUMNS:
                val = row.get(key)
                if key in MONEY_TOTAL_KEYS:
                    cells.append(f"<td class='num'>{fmt_money(val)}</td>")
                elif key in HOUR_TOTAL_KEYS:
                    cells.append(f"<td class='num'>{fmt_hours(val)}</td>")
                else:
                    cells.append(f"<td>{val or ''}</td>")
            body.append("<tr class='data-row'>" + "".join(cells) + "</tr>")

        sub_cells = []
        for key, _ in PDF_COLUMNS:
            if key == "employee_name":
                sub_cells.append("<td><strong>Subtotal</strong></td>")
            elif key in subtotal and key in (*HOUR_TOTAL_KEYS, *MONEY_TOTAL_KEYS):
                if key in HOUR_TOTAL_KEYS:
                    sub_cells.append(
                        f"<td class='num'><strong>{fmt_hours(subtotal[key])}</strong></td>"
                    )
                else:
                    sub_cells.append(
                        f"<td class='num'><strong>{fmt_money(subtotal[key])}</strong></td>"
                    )
            else:
                sub_cells.append("<td></td>")
        body.append("<tr class='subtotal'>" + "".join(sub_cells) + "</tr>")

        th = "".join(f"<th>{lab}</th>" for _, lab in PDF_COLUMNS)
        return f"""
<table>
<thead><tr>{th}</tr></thead>
<tbody>
{"".join(body)}
</tbody>
</table>"""

    heading = report.get("report_heading") or report_heading(filters)
    monthly_intro = ""
    if rt == "monthly_paid" and filters.get("month") and filters.get("year"):
        monthly_intro = summary_block("Monthly summary", summary)

    groups = _group_rows_for_pdf(report)
    group_html = []
    for g_heading, g_rows in groups:
        g_totals = _sum_totals(g_rows)
        g_summary = _build_summary(g_rows, g_totals)
        group_html.append(
            f"""
<section class="group">
  <h2>{g_heading}</h2>
  {summary_block("Group summary", g_summary)}
  {rows_table(g_rows, g_totals)}
</section>"""
        )

    grand_cells = []
    for key, _ in PDF_COLUMNS:
        if key == "employee_name":
            grand_cells.append("<td><strong>Grand Total</strong></td>")
        elif key in totals and key in (*HOUR_TOTAL_KEYS, *MONEY_TOTAL_KEYS):
            if key in HOUR_TOTAL_KEYS:
                grand_cells.append(
                    f"<td class='num'><strong>{fmt_hours(totals[key])}</strong></td>"
                )
            else:
                grand_cells.append(
                    f"<td class='num'><strong>{fmt_money(totals[key])}</strong></td>"
                )
        else:
            grand_cells.append("<td></td>")
    grand_th = "".join(f"<th>{lab}</th>" for _, lab in PDF_COLUMNS)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{heading}</title>
<style>
  @page {{ size: letter landscape; margin: 0.45in; }}
  body {{ font-family: system-ui, sans-serif; color: #0f172a; margin: 16px; font-size: 10px; }}
  h1 {{ color: #0097b2; font-size: 1.25rem; margin-bottom: 4px; }}
  h2 {{ color: #007a91; font-size: 1.05rem; margin: 14px 0 6px; page-break-after: avoid; }}
  .meta {{ color: #475569; margin-bottom: 6px; }}
  .note {{ color: #64748b; font-size: 9px; margin: 6px 0 12px; max-width: 960px; }}
  .group {{ page-break-inside: avoid; break-inside: avoid; margin-bottom: 12px; }}
  .group-summary {{ display: flex; flex-wrap: wrap; gap: 10px 16px; margin: 4px 0 8px;
    color: #334155; background: #f8fafc; padding: 6px 8px; border-radius: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 8px; }}
  thead {{ display: table-header-group; }}
  th, td {{ padding: 5px 6px; border-bottom: 1px solid #e2e8f0; text-align: left; vertical-align: top; }}
  th {{ background: #f8fafc; color: #007a91; white-space: nowrap; }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  tr.data-row, tr.subtotal, tr.total {{ page-break-inside: avoid; break-inside: avoid; }}
  tr.subtotal {{ background: #f1f5f9; }}
  tr.total {{ background: #e2e8f0; font-weight: 700; }}
  .grand {{ margin-top: 16px; }}
</style></head><body>
<h1>{heading}</h1>
<p class="meta">{_filter_summary_text(filters)}</p>
<p class="meta">{report.get("date_match_rule") or DATE_MATCH_RULE}</p>
{summary_block("Report summary", summary)}
{monthly_intro}
<p class="note">OT Premium is only the additional amount above the regular hourly rate.
Regular/Base Earnings include overtime hours at the regular rate.
<strong>Regular/Base + OT Premium + Other Earnings = Gross Pay.</strong>
<strong>Total Payroll Cost = Gross + Employer Taxes (stored only).</strong>
Pay Date is the batch official_pay_date (no period-end fallback).
Totals match the filtered on-screen report.</p>
{"".join(group_html)}
<section class="grand">
  <h2>Grand Total</h2>
  <table>
  <thead><tr>{grand_th}</tr></thead>
  <tbody>
  <tr class="total">{"".join(grand_cells)}</tr>
  </tbody>
  </table>
</section>
</body></html>"""
