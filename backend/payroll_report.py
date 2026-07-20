"""Cross-period Payroll Report: query, Excel, and PDF/HTML exports.

OT amounts use premium-only presentation (see payroll_overtime.earnings_breakdown_from_line).
Does not mutate stored gross or historical payroll amounts.
"""

from __future__ import annotations

import io
import json
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


DATE_MATCH_RULE = (
    "Includes rows where the pay period overlaps the selected range, "
    "or the pay date falls within the selected range."
)

REPORT_COLUMNS = (
    ("employee_name", "Employee name"),
    ("employee_category", "Employee category"),
    ("payroll_period", "Payroll period"),
    ("pay_date", "Pay date"),
    ("regular_hours", "Regular hours"),
    ("ot_hours", "OT hours"),
    ("base_earnings", "Regular/Base earnings"),
    ("ot_premium", "OT premium"),
    ("other_earnings", "Other earnings"),
    ("gross_pay", "Gross pay"),
    ("employee_tax_deductions", "Employee tax deductions"),
    ("other_deductions", "Other deductions"),
    ("net_pay", "Net pay"),
    ("employer_taxes", "Employer taxes"),
    ("payment_status", "Payment status"),
    ("payroll_status", "Payroll status"),
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
)


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


def _line_pay_date(line: dict, batch: dict) -> Optional[str]:
    details = line.get("payout_details") or _parse_details(line.get("payout_details_json"))
    payment = details.get("payment") or {}
    pay_date = str(payment.get("date") or "").strip()[:10]
    if pay_date:
        return pay_date
    fallback = batch.get("pay_period_end") or batch.get("pay_period_start")
    d = _parse_ymd(fallback)
    return d.isoformat() if d else None


def _periods_overlap(ps: Optional[date], pe: Optional[date], start: date, end: date) -> bool:
    if not ps and not pe:
        return False
    period_start = ps or pe
    period_end = pe or ps
    assert period_start is not None and period_end is not None
    return period_start <= end and period_end >= start


def _row_matches_date_range(row: dict, start: date, end: date) -> bool:
    """Consistent date rule: pay-period overlap OR pay date within range."""
    ps = _parse_ymd(row.get("pay_period_start"))
    pe = _parse_ymd(row.get("pay_period_end"))
    if _periods_overlap(ps, pe, start, end):
        return True
    pd = _parse_ymd(row.get("pay_date"))
    if pd and start <= pd <= end:
        return True
    return False


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


def build_report_row(batch: dict, line: dict) -> dict[str, Any]:
    details = line.get("payout_details") or _parse_details(line.get("payout_details_json"))
    breakdown = earnings_breakdown_from_line(line)
    cat = str(batch.get("worker_category") or "")
    display_status = compute_display_status(batch)
    pay_date = _line_pay_date(line, batch)
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
        "regular_hours": breakdown["regular_hours"],
        "ot_hours": breakdown["ot_hours"],
        "regular_rate": breakdown["regular_rate"],
        "ot_rate": breakdown["ot_rate"],
        "base_earnings": breakdown["base_earnings"],
        "ot_premium": breakdown["ot_premium"],
        "other_earnings": breakdown["other_earnings"],
        "gross_pay": breakdown["gross_pay"],
        "employee_tax_deductions": emp_tax,
        "other_deductions": other_ded,
        "net_pay": round(_money(net), 2),
        "employer_taxes": _employer_tax_total(details),
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
) -> dict[str, Any]:
    """Return filtered payroll report rows + totals across categories/periods."""
    from backend.payroll_operations import ensure_payout_batches_tables

    ensure_payout_batches_tables(conn.cursor())
    c = conn.cursor(dictionary=True)
    has_details = table_has_column(c, "payout_batch_lines", "payout_details_json")

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
    if has_details:
        select_cols += ", pbl.payout_details_json"

    q = f"""
        SELECT {select_cols}
        FROM payout_batch_lines pbl
        INNER JOIN payout_batches pb ON pb.id = pbl.batch_id
        WHERE pb.organization_id = %s AND pbl.organization_id = %s
    """
    params: list[Any] = [int(organization_id), int(organization_id)]

    period_pairs: list[tuple[str, str]] = []
    starts = [str(s).strip()[:10] for s in (period_starts or []) if str(s).strip()]
    ends = [str(e).strip()[:10] for e in (period_ends or []) if str(e).strip()]
    if starts and ends and len(starts) == len(ends):
        period_pairs = list(zip(starts, ends))
    elif starts and ends and len(starts) == 1 and len(ends) == 1:
        period_pairs = [(starts[0], ends[0])]

    if period_pairs and not all_history:
        placeholders = " OR ".join(
            ["(pb.pay_period_start = %s AND pb.pay_period_end = %s)"] * len(period_pairs)
        )
        q += f" AND ({placeholders})"
        for ps, pe in period_pairs:
            params.extend([ps, pe])

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

    q += " ORDER BY pb.pay_period_start DESC, pb.worker_category, pbl.worker_name_snapshot LIMIT %s"
    params.append(int(limit))

    c.execute(q, params)
    raw_rows = c.fetchall() or []

    df = _parse_ymd(date_from)
    dt = _parse_ymd(date_to)
    use_date_range = bool(df and dt and not all_history and not period_pairs)

    rows: list[dict] = []
    seen_line_ids: set[Any] = set()
    for raw in raw_rows:
        line_id = raw.get("line_id")
        # Date-range OR-match must never emit the same payout line twice.
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
        if use_date_range and not _row_matches_date_range(row, df, dt):
            continue
        if payroll_status and payroll_status != "all":
            if row["payroll_status_key"] != payroll_status:
                continue
        if line_id is not None:
            seen_line_ids.add(line_id)
        rows.append(row)

    totals = _sum_totals(rows)
    filters = {
        "period_starts": starts,
        "period_ends": ends,
        "date_from": date_from or "",
        "date_to": date_to or "",
        "all_history": bool(all_history),
        "user_id": int(user_id) if user_id else None,
        "worker_category": worker_category or "all",
        "payroll_status": payroll_status or "all",
        "payment_status": payment_status or "all",
        "date_match_rule": DATE_MATCH_RULE,
    }
    return json_safe(
        {
            "rows": rows,
            "totals": totals,
            "count": len(rows),
            "filters": filters,
            "date_match_rule": DATE_MATCH_RULE,
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


def _filter_summary_text(filters: dict) -> str:
    parts = []
    if filters.get("all_history"):
        parts.append("All payroll history")
    elif filters.get("period_starts") and filters.get("period_ends"):
        pairs = list(zip(filters["period_starts"], filters["period_ends"]))
        if len(pairs) == 1:
            parts.append(f"Period {pairs[0][0]} – {pairs[0][1]}")
        else:
            parts.append(f"{len(pairs)} payroll periods")
    elif filters.get("date_from") and filters.get("date_to"):
        parts.append(f"Custom date range {filters['date_from']} – {filters['date_to']}")
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
    ws.title = "Payroll Report"
    filters = report.get("filters") or {}
    ws.append(["Payroll Report"])
    ws.append([_filter_summary_text(filters)])
    ws.append([report.get("date_match_rule") or DATE_MATCH_RULE])
    ws.append([])
    headers = [lab for _, lab in REPORT_COLUMNS]
    ws.append(headers)
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    money_keys = set(MONEY_TOTAL_KEYS)
    hour_keys = set(HOUR_TOTAL_KEYS)
    header_row = 5
    data_start = header_row + 1

    for row in report.get("rows") or []:
        excel_vals = []
        for key, _ in REPORT_COLUMNS:
            val = row.get(key)
            if key == "pay_date":
                d = _parse_ymd(val)
                excel_vals.append(d if d else None)
            elif key in money_keys or key in hour_keys:
                excel_vals.append(round(_money(val), 2))
            else:
                excel_vals.append(val if val is not None else "")
        ws.append(excel_vals)
        r = ws.max_row
        for col_idx, (key, _) in enumerate(REPORT_COLUMNS, start=1):
            cell = ws.cell(row=r, column=col_idx)
            if key == "pay_date" and cell.value is not None:
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
            "Money and hour columns are numeric; pay date is a date cell."
        ),
    )
    # Freeze header for filtering in Excel
    ws.freeze_panes = f"A{data_start}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_payroll_report_html(report: dict) -> str:
    """HTML suitable for browser print / PDF download.

    Pagination: thead repeats on each printed page; data/total rows avoid mid-row splits.
    Totals match the same report.totals used by the on-screen filtered grid.
    """
    filters = report.get("filters") or {}
    rows = report.get("rows") or []
    totals = report.get("totals") or {}

    def fmt_money(v: Any) -> str:
        return f"${_money(v):,.2f}"

    def fmt_hours(v: Any) -> str:
        return f"{_money(v):,.2f}"

    body_rows = []
    for row in rows:
        cells = []
        for key, _ in REPORT_COLUMNS:
            val = row.get(key)
            if key in MONEY_TOTAL_KEYS:
                cells.append(f"<td class='num'>{fmt_money(val)}</td>")
            elif key in HOUR_TOTAL_KEYS:
                cells.append(f"<td class='num'>{fmt_hours(val)}</td>")
            else:
                cells.append(f"<td>{val or ''}</td>")
        body_rows.append("<tr class='data-row'>" + "".join(cells) + "</tr>")

    total_cells = []
    for key, _ in REPORT_COLUMNS:
        if key == "employee_name":
            total_cells.append("<td><strong>Totals</strong></td>")
        elif key in totals:
            if key in HOUR_TOTAL_KEYS:
                total_cells.append(f"<td class='num'><strong>{fmt_hours(totals[key])}</strong></td>")
            else:
                total_cells.append(f"<td class='num'><strong>{fmt_money(totals[key])}</strong></td>")
        else:
            total_cells.append("<td></td>")

    th = "".join(f"<th>{lab}</th>" for _, lab in REPORT_COLUMNS)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Payroll Report</title>
<style>
  @page {{ size: letter landscape; margin: 0.45in; }}
  body {{ font-family: system-ui, sans-serif; color: #0f172a; margin: 16px; font-size: 10px; }}
  h1 {{ color: #0097b2; font-size: 1.25rem; margin-bottom: 4px; }}
  .meta {{ color: #475569; margin-bottom: 6px; }}
  .note {{ color: #64748b; font-size: 9px; margin: 6px 0 12px; max-width: 960px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead {{ display: table-header-group; }}
  tfoot {{ display: table-footer-group; }}
  th, td {{ padding: 5px 6px; border-bottom: 1px solid #e2e8f0; text-align: left; vertical-align: top; }}
  th {{ background: #f8fafc; color: #007a91; white-space: nowrap; }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  tr.data-row, tr.total {{ page-break-inside: avoid; break-inside: avoid; }}
  tr.total {{ background: #f1f5f9; font-weight: 700; }}
</style></head><body>
<h1>Payroll Report</h1>
<p class="meta">{_filter_summary_text(filters)}</p>
<p class="meta">{report.get("date_match_rule") or DATE_MATCH_RULE}</p>
<p class="note">OT Premium is only the additional amount above the regular hourly rate.
Regular/Base Earnings include overtime hours at the regular rate.
<strong>Regular/Base + OT Premium + Other Earnings = Gross Pay.</strong>
Totals below match the filtered on-screen report.</p>
<table>
<thead><tr>{th}</tr></thead>
<tbody>
{"".join(body_rows)}
</tbody>
<tfoot>
<tr class="total">{"".join(total_cells)}</tr>
</tfoot>
</table>
</body></html>"""
