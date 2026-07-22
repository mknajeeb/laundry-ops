"""Payroll report analytics: period comparison, KPIs, nested groups, PDF chart SVG.

Presentation only — reuses report row totals; does not mutate payroll amounts.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from typing import Any, Optional

from backend.payroll_operations import CATEGORY_LABELS

COMPARISON_RANGE_OPTIONS = (3, 4, 5, 6, 8, 12)  # union; mode-specific below
DEFAULT_COMPARISON_RANGE = 4
MONTH_TREND_OPTIONS = (3, 4, 6, 12)
PERIOD_TREND_OPTIONS = (3, 4, 5, 8)

COMPARE_WITH_MONTH = (
    ("previous_month", "Previous month"),
    ("same_month_last_year", "Same month last year"),
)
COMPARE_WITH_PERIOD = (
    ("previous_period", "Previous payroll period"),
    ("same_period_4_weeks_earlier", "Same period 4 weeks earlier"),
)

# Executive Summary KPIs only (management scan).
KPI_DEFS = (
    ("total_payroll_cost", "Total Payroll Cost", "money"),
    ("gross_pay", "Gross Payroll", "money"),
    ("total_hours", "Total Hours", "hours"),
    ("worker_count", "Head Count", "count"),
    ("avg_hours_per_worker", "Average Hours / Worker", "hours"),
    ("avg_cost_per_hour", "Average Employer Cost / Hour", "money"),
)

# Periods appear in pickers / comparison only when every batch for that
# period is terminal (paid/closed) or details-finalized — category mix
# does not matter (W-2-only or Temp-only weeks are valid).
TERMINAL_BATCH_STATUSES = frozenset({"paid", "closed"})

# Period-comparison delta keys (broader than executive KPIs).
COMPARISON_DELTA_KEYS = (
    "total_payroll_cost",
    "gross_pay",
    "total_hours",
    "regular_hours",
    "ot_hours",
    "worker_count",
    "base_earnings",
    "ot_premium",
    "regular_earnings",
    "ot_earnings",
    "employee_tax_deductions",
    "net_pay",
    "employer_taxes",
    "amount_paid",
    "outstanding_balance",
    "avg_cost_per_hour",
    "avg_pay_rate",
)

# Increases are not styled as "good" for these cost-like metrics.
NEUTRAL_TREND_KEYS = frozenset(
    {
        "ot_hours",
        "ot_premium",
        "ot_earnings",
        "employer_taxes",
        "total_payroll_cost",
        "gross_pay",
        "avg_cost_per_hour",
        "avg_hours_per_worker",
        "avg_pay_rate",
        "employee_tax_deductions",
        "outstanding_balance",
    }
)


def _money(val: Any) -> float:
    try:
        if val is None or val == "":
            return 0.0
        return round(float(val), 2)
    except (TypeError, ValueError):
        return 0.0


def normalize_comparison_range(value: Any) -> int:
    """Legacy alias — prefers period trend options, falls back to month options."""
    return normalize_trend_range(value, mode="period")


def normalize_trend_range(value: Any, *, mode: str = "period") -> int:
    options = MONTH_TREND_OPTIONS if mode == "month" else PERIOD_TREND_OPTIONS
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_COMPARISON_RANGE
    if n in options:
        return n
    # Snap to nearest allowed option.
    return min(options, key=lambda o: abs(o - n))


def normalize_compare_with(value: Any, *, mode: str) -> str:
    if mode == "month":
        allowed = {k for k, _ in COMPARE_WITH_MONTH}
        default = "previous_month"
    else:
        allowed = {k for k, _ in COMPARE_WITH_PERIOD}
        default = "previous_period"
    v = str(value or "").strip().lower()
    return v if v in allowed else default


def period_key_from_row(row: dict) -> tuple[str, str]:
    ps = str(row.get("pay_period_start") or "")[:10]
    pe = str(row.get("pay_period_end") or "")[:10]
    return ps, pe


def period_label(ps: str, pe: str) -> str:
    if ps and pe:
        return f"{ps} – {pe}"
    return ps or pe or "Unknown period"


def aggregate_period_metrics(rows: list[dict]) -> dict[str, Any]:
    """Roll up filtered report rows into one period metrics blob."""
    from backend.payroll_report import _sum_totals

    # Ensure management earnings fields exist (derive from hours × rates when missing).
    normalized = []
    for row in rows or []:
        r = dict(row)
        if r.get("regular_earnings") is None or r.get("ot_earnings") is None:
            reg_h = _money(r.get("regular_hours"))
            ot_h = _money(r.get("ot_hours"))
            rate = _money(r.get("regular_rate"))
            ot_rate = _money(r.get("ot_rate"))
            if ot_rate <= 0 and rate > 0 and ot_h > 0:
                ot_rate = round(rate * 1.5, 2)
            if r.get("regular_earnings") is None:
                r["regular_earnings"] = round(reg_h * rate, 2) if rate > 0 else 0.0
            if r.get("ot_earnings") is None:
                r["ot_earnings"] = round(ot_h * ot_rate, 2) if ot_h > 0 and ot_rate > 0 else 0.0
        normalized.append(r)

    totals = _sum_totals(normalized)
    user_ids = {r.get("user_id") for r in normalized if r.get("user_id") is not None}
    names = {
        " ".join(str(r.get("employee_name") or "").split())
        for r in normalized
        if str(r.get("employee_name") or "").strip()
    }
    pay_dates = sorted(
        {
            str(r.get("pay_date") or r.get("official_pay_date") or "")[:10]
            for r in normalized
            if str(r.get("pay_date") or r.get("official_pay_date") or "").strip()
        }
    )
    reg = _money(totals.get("regular_hours"))
    ot = _money(totals.get("ot_hours"))
    total_hours = round(reg + ot, 2)
    gross = _money(totals.get("gross_pay"))
    cost = _money(totals.get("total_payroll_cost"))
    avg_cost = round(cost / total_hours, 2) if total_hours > 0.005 else None
    avg_pay = round(gross / total_hours, 2) if total_hours > 0.005 else None
    ot_pct_hours = round((ot / total_hours) * 100.0, 2) if total_hours > 0.005 else 0.0
    ot_earnings = _money(totals.get("ot_earnings"))
    ot_premium = _money(totals.get("ot_premium"))
    ot_pct_gross = (
        round((ot_earnings / gross) * 100.0, 2) if gross > 0.005 else 0.0
    )
    ot_premium_pct_of_gross = (
        round((ot_premium / gross) * 100.0, 2) if gross > 0.005 else 0.0
    )
    worker_count = len(user_ids) if user_ids else len(names)
    avg_hours_per_worker = (
        round(total_hours / worker_count, 2) if worker_count > 0 and total_hours > 0.005 else None
    )
    return {
        **totals,
        "total_hours": total_hours,
        "worker_count": worker_count,
        "pay_dates": pay_dates,
        "pay_date_count": len(pay_dates),
        "avg_cost_per_hour": avg_cost,
        "avg_pay_rate": avg_pay,
        "avg_hours_per_worker": avg_hours_per_worker,
        "ot_pct_of_hours": ot_pct_hours,
        "ot_earnings_pct_of_gross": ot_pct_gross,
        "ot_premium_pct_of_gross": ot_premium_pct_of_gross,
        "line_count": len(normalized),
    }


def _delta(current: float, previous: Optional[float]) -> dict[str, Any]:
    if previous is None:
        return {
            "previous": None,
            "diff": None,
            "pct": None,
            "direction": "flat",
        }
    prev = float(previous)
    cur = float(current)
    diff = round(cur - prev, 2)
    if abs(prev) < 1e-9:
        pct = None
    else:
        pct = round((diff / abs(prev)) * 100.0, 2)
    if abs(diff) < 0.005:
        direction = "flat"
    elif diff > 0:
        direction = "up"
    else:
        direction = "down"
    return {
        "previous": round(prev, 2),
        "diff": diff,
        "pct": pct,
        "direction": direction,
    }


def build_kpi_cards(
    current: dict[str, Any], previous: Optional[dict[str, Any]]
) -> list[dict[str, Any]]:
    cards = []
    for key, label, kind in KPI_DEFS:
        if kind == "count":
            cur_val = int(current.get(key) or 0)
        elif current.get(key) is None and key in (
            "avg_cost_per_hour",
            "avg_pay_rate",
            "avg_hours_per_worker",
        ):
            cur_val = None
        else:
            cur_val = _money(current.get(key))
        prev_val = None
        if previous is not None:
            if kind == "count":
                prev_val = int(previous.get(key) or 0)
            elif previous.get(key) is None and key in (
                "avg_cost_per_hour",
                "avg_pay_rate",
                "avg_hours_per_worker",
            ):
                prev_val = None
            else:
                prev_val = _money(previous.get(key))
        delta = _delta(
            float(cur_val or 0),
            float(prev_val) if prev_val is not None else None,
        )
        if cur_val is None:
            delta = {
                "previous": prev_val,
                "diff": None,
                "pct": None,
                "direction": "flat",
            }
        cards.append(
            {
                "key": key,
                "label": label,
                "kind": kind,
                "value": cur_val if cur_val is not None else 0,
                "current": cur_val if cur_val is not None else 0,
                "neutral_trend": key in NEUTRAL_TREND_KEYS,
                **delta,
            }
        )
    return cards


def build_ot_summary(
    current: dict[str, Any], previous: Optional[dict[str, Any]]
) -> dict[str, Any]:
    """Compact OT insight: hours, share of hours, full OT earnings, vs prior."""
    ot = _money(current.get("ot_hours"))
    pct = _money(current.get("ot_pct_of_hours"))
    ot_earnings = _money(current.get("ot_earnings"))
    premium = _money(current.get("ot_premium"))
    gross = _money(current.get("gross_pay"))
    if current.get("ot_earnings_pct_of_gross") is not None:
        earnings_pct = _money(current.get("ot_earnings_pct_of_gross"))
    else:
        earnings_pct = round((ot_earnings / gross) * 100.0, 2) if gross > 0.005 else 0.0
    if current.get("ot_premium_pct_of_gross") is not None:
        premium_pct = _money(current.get("ot_premium_pct_of_gross"))
    else:
        premium_pct = round((premium / gross) * 100.0, 2) if gross > 0.005 else 0.0
    prev_ot = _money(previous.get("ot_hours")) if previous else None
    prev_earnings = _money(previous.get("ot_earnings")) if previous else None
    prev_premium = _money(previous.get("ot_premium")) if previous else None
    hours_delta = _delta(ot, prev_ot)
    earnings_delta = _delta(ot_earnings, prev_earnings)
    premium_delta = _delta(premium, prev_premium)
    return {
        "key": "ot_hours",
        "label": "OT Hours",
        "kind": "hours",
        "value": ot,
        "current": ot,
        "ot_hours": ot,
        "ot_pct_of_hours": pct,
        "ot_earnings": ot_earnings,
        "ot_earnings_pct_of_gross": earnings_pct,
        "ot_premium": premium,
        "ot_premium_pct_of_gross": premium_pct,
        "previous_ot_hours": prev_ot,
        "previous_ot_earnings": prev_earnings,
        "previous_ot_premium": prev_premium,
        "ot_hours_diff": hours_delta["diff"],
        "ot_hours_pct": hours_delta["pct"],
        "ot_earnings_diff": earnings_delta["diff"],
        "ot_earnings_pct": earnings_delta["pct"],
        "ot_premium_diff": premium_delta["diff"],
        "ot_premium_pct": premium_delta["pct"],
        "neutral_trend": True,
        **hours_delta,
    }


def month_label(year: int, month: int) -> str:
    return f"{calendar.month_name[int(month)]} {int(year)}"


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = int(year) * 12 + (int(month) - 1) + int(delta)
    return idx // 12, (idx % 12) + 1


def select_trend_months(
    focus_year: int, focus_month: int, trend_range: int
) -> list[tuple[int, int]]:
    n = normalize_trend_range(trend_range, mode="month")
    out: list[tuple[int, int]] = []
    for i in range(n - 1, -1, -1):
        out.append(shift_month(focus_year, focus_month, -i))
    return out


def format_focus_period_label(ps: str, pe: str) -> str:
    """Human focus label: Jul 6–12, 2026."""
    try:
        from datetime import date as _date

        s = _date.fromisoformat(str(ps)[:10])
        e = _date.fromisoformat(str(pe)[:10])
    except ValueError:
        return period_label(ps, pe)
    if s.year == e.year and s.month == e.month:
        return f"{s.strftime('%b')} {s.day}–{e.day}, {s.year}"
    if s.year == e.year:
        return f"{s.strftime('%b')} {s.day}–{e.strftime('%b')} {e.day}, {s.year}"
    return f"{s.strftime('%b')} {s.day}, {s.year}–{e.strftime('%b')} {e.day}, {e.year}"


def build_executive_narrative(
    current: dict[str, Any], previous: Optional[dict[str, Any]], categories: list[dict]
) -> dict[str, Any]:
    """One-sentence story + drivers for executives."""
    if not previous:
        return {
            "headline": "No prior period available for comparison.",
            "drivers": [],
            "text": "No prior period available for comparison.",
        }
    cost_d = _delta(
        _money(current.get("total_payroll_cost")),
        _money(previous.get("total_payroll_cost")),
    )
    hours_d = _delta(_money(current.get("total_hours")), _money(previous.get("total_hours")))
    ot_d = _delta(_money(current.get("ot_hours")), _money(previous.get("ot_hours")))
    hc_d = _delta(
        float(current.get("worker_count") or 0),
        float(previous.get("worker_count") or 0),
    )
    avg_h_d = _delta(
        _money(current.get("avg_hours_per_worker") or 0),
        _money(previous.get("avg_hours_per_worker") or 0)
        if previous.get("avg_hours_per_worker") is not None
        else None,
    )

    direction_word = "unchanged"
    if cost_d["direction"] == "up":
        direction_word = "increased"
    elif cost_d["direction"] == "down":
        direction_word = "decreased"

    if cost_d["diff"] is None:
        headline = "Payroll cost comparison unavailable."
    elif cost_d["direction"] == "flat":
        headline = f"Payroll cost was flat at ${_money(current.get('total_payroll_cost')):,.2f}."
    else:
        pct_txt = f"{cost_d['pct']:+.1f}%" if cost_d["pct"] is not None else ""
        diff_txt = f"{cost_d['diff']:+,.2f}"
        headline = f"Payroll cost {direction_word} {pct_txt} (${diff_txt})".replace("  ", " ")

    drivers = []
    if hours_d["pct"] is not None and abs(hours_d["pct"]) >= 0.05:
        drivers.append(f"Hours {hours_d['pct']:+.1f}%")
    if ot_d["pct"] is not None and abs(ot_d["pct"]) >= 0.05:
        drivers.append(f"OT {ot_d['pct']:+.1f}%")
    if hc_d["diff"] is not None:
        if abs(hc_d["diff"]) < 0.5:
            drivers.append("Headcount unchanged")
        else:
            drivers.append(f"Headcount {hc_d['diff']:+.0f}")
    if avg_h_d["pct"] is not None and abs(avg_h_d["pct"]) >= 0.05:
        drivers.append(f"Hours/worker {avg_h_d['pct']:+.1f}%")

    # Which employment type moved cost the most (by absolute $ change vs prior mix not available
    # at category prior — use share of focus cost as secondary signal).
    total_cost = _money(current.get("total_payroll_cost"))
    if total_cost > 0.005 and categories:
        top = max(categories, key=lambda c: _money(c.get("total_payroll_cost")))
        share = round(100.0 * _money(top.get("total_payroll_cost")) / total_cost, 1)
        drivers.append(f"{top.get('label') or top.get('worker_category')} {share}% of cost")

    text = headline
    if drivers:
        text = f"{headline} primarily due to " + "; ".join(drivers[:4]) + "."
    return {"headline": headline, "drivers": drivers[:4], "text": text}


def attach_category_cost_shares(categories: list[dict]) -> list[dict]:
    total = sum(_money(c.get("total_payroll_cost")) for c in categories)
    out = []
    for c in categories:
        row = dict(c)
        if total > 0.005:
            row["pct_of_total_cost"] = round(
                100.0 * _money(c.get("total_payroll_cost")) / total, 1
            )
        else:
            row["pct_of_total_cost"] = None
        out.append(row)
    return out


def build_month_comparison_entries(
    month_metrics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach deltas between consecutive monthly buckets."""
    out = []
    prev = None
    for m in month_metrics:
        entry = dict(m)
        deltas = {}
        pcts = {}
        if prev is not None:
            for key in COMPARISON_DELTA_KEYS:
                if key in ("avg_cost_per_hour", "avg_pay_rate", "avg_hours_per_worker"):
                    if m.get(key) is None or prev.get(key) is None:
                        continue
                d = _delta(_money(m.get(key) or 0), _money(prev.get(key) or 0))
                deltas[key] = d["diff"]
                pcts[key] = d["pct"]
        entry["delta_from_previous"] = deltas
        entry["pct_from_previous"] = pcts
        out.append(entry)
        prev = m
    return out


def chart_titles_for_mode(mode: str) -> dict[str, str]:
    if mode == "month":
        return {
            "cost": "Monthly Payroll Cost Trend",
            "hours": "Monthly Hours Trend",
            "mix": "Monthly Employment Mix",
            "cost_per_hour": "Monthly Average Employer Cost/Hour",
        }
    return {
        "cost": "Payroll Cost by Period",
        "hours": "Hours by Period",
        "mix": "Employment Mix by Period",
        "cost_per_hour": "Average Employer Cost/Hour by Period",
    }


def find_period_4_weeks_earlier(
    all_periods_asc: list[tuple[str, str]], anchor: tuple[str, str]
) -> Optional[tuple[str, str]]:
    """Nearest complete period whose end is ~28 days before the anchor end."""
    try:
        from datetime import date as _date, timedelta

        anchor_end = _date.fromisoformat(str(anchor[1])[:10])
        target = anchor_end - timedelta(days=28)
    except ValueError:
        return None
    best = None
    best_dist = None
    for ps, pe in all_periods_asc:
        if (ps, pe) == anchor:
            continue
        try:
            end = _date.fromisoformat(str(pe)[:10])
        except ValueError:
            continue
        if end >= anchor_end:
            continue
        dist = abs((end - target).days)
        if best_dist is None or dist < best_dist:
            best = (ps, pe)
            best_dist = dist
    return best


def group_rows_by_period_then_pay_date(rows: list[dict]) -> list[dict[str, Any]]:
    """Nested hierarchy: Payroll Period → Pay Date → employee rows."""
    from backend.payroll_report import _sum_totals, _build_summary

    by_period: dict[tuple[str, str], dict[str, list[dict]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows or []:
        ps, pe = period_key_from_row(row)
        pay = str(row.get("pay_date") or row.get("official_pay_date") or "Pay Date Missing")[
            :10
        ] or "Pay Date Missing"
        by_period[(ps, pe)][pay].append(row)

    groups: list[dict[str, Any]] = []
    for ps, pe in sorted(by_period.keys(), key=lambda t: (t[0] or "", t[1] or "")):
        pay_map = by_period[(ps, pe)]
        period_rows: list[dict] = []
        pay_date_groups: list[dict] = []
        for pay in sorted(pay_map.keys()):
            g_rows = sorted(
                pay_map[pay],
                key=lambda r: (
                    str(r.get("employee_name") or "").lower(),
                    int(r.get("line_id") or 0),
                ),
            )
            g_totals = _sum_totals(g_rows)
            pay_date_groups.append(
                {
                    "pay_date": pay,
                    "heading": f"Pay Date: {pay}",
                    "rows": g_rows,
                    "totals": g_totals,
                    "summary": _build_summary(g_rows, g_totals),
                }
            )
            period_rows.extend(g_rows)
        p_totals = _sum_totals(period_rows)
        p_summary = _build_summary(period_rows, p_totals)
        groups.append(
            {
                "pay_period_start": ps,
                "pay_period_end": pe,
                "payroll_period": period_label(ps, pe),
                "heading": f"Payroll Period: {period_label(ps, pe)}",
                "pay_dates": pay_date_groups,
                "totals": p_totals,
                "summary": {
                    **p_summary,
                    "pay_date_count": len(pay_date_groups),
                    "total_hours": round(
                        _money(p_totals.get("regular_hours"))
                        + _money(p_totals.get("ot_hours")),
                        2,
                    ),
                },
                "row_count": len(period_rows),
            }
        )
    return groups


def category_breakdown(rows: list[dict]) -> list[dict[str, Any]]:
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for row in rows or []:
        cat = str(row.get("worker_category") or "unknown")
        by_cat[cat].append(row)
    out = []
    order = ("w2", "temp", "contractor_1099")
    keys = [k for k in order if k in by_cat] + sorted(
        k for k in by_cat if k not in order
    )
    for cat in keys:
        metrics = aggregate_period_metrics(by_cat[cat])
        # Employer true cost: W-2 = gross + ER taxes; Temp/1099 = gross.
        if cat == "w2":
            employer_cost = round(
                _money(metrics.get("gross_pay")) + _money(metrics.get("employer_taxes")), 2
            )
        else:
            employer_cost = _money(metrics.get("gross_pay"))
        base = _money(metrics.get("base_earnings"))
        prem = _money(metrics.get("ot_premium"))
        reg_earn = _money(metrics.get("regular_earnings"))
        ot_earn = _money(metrics.get("ot_earnings"))
        other = _money(metrics.get("other_earnings"))
        gross = _money(metrics.get("gross_pay"))
        # Premium model still reconciles; management model uses regular+ot full.
        recon_diff = round(gross - base - prem - other, 2)
        mgmt_diff = round(gross - reg_earn - ot_earn - other, 2)
        avg_pay = metrics.get("avg_pay_rate")
        avg_cost = metrics.get("avg_cost_per_hour")
        out.append(
            {
                "worker_category": cat,
                "label": CATEGORY_LABELS.get(cat, cat),
                **metrics,
                "head_count": metrics.get("worker_count", 0),
                "regular_hours": _money(metrics.get("regular_hours")),
                "ot_hours": _money(metrics.get("ot_hours")),
                "regular_earnings": reg_earn,
                "ot_earnings": ot_earn,
                "base_earnings": base,
                "ot_premium": prem,
                "other_earnings": other,
                "gross_pay": gross,
                "avg_pay_rate": avg_pay,
                "avg_cost_per_hour": avg_cost,
                "avg_rate": avg_pay,
                "employer_cost": employer_cost,
                "gross_reconciliation_diff": recon_diff,
                "gross_reconciles": abs(recon_diff) < 0.005,
                "mgmt_reconciliation_diff": mgmt_diff,
                "mgmt_reconciles": abs(mgmt_diff) < 0.005,
                "has_other_earnings": abs(other) >= 0.005,
            }
        )
    return out


def employee_summaries_by_category(
    rows: list[dict], *, include_identities: bool = True
) -> dict[str, list[dict[str, Any]]]:
    """Per-category employee rollups for dashboard drill-down.

    When include_identities is False, returns an empty mapping (no names, rates,
    or line-level employee payroll data).
    """
    if not include_identities:
        return {}

    by_cat: dict[str, dict[Any, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in rows or []:
        cat = str(row.get("worker_category") or "unknown")
        uid = row.get("user_id")
        key = uid if uid is not None else (
            " ".join(str(row.get("employee_name") or "").split()).lower() or id(row)
        )
        by_cat[cat][key].append(row)

    out: dict[str, list[dict[str, Any]]] = {}
    for cat, employees in by_cat.items():
        summaries = []
        for key, emp_rows in employees.items():
            metrics = aggregate_period_metrics(emp_rows)
            name = emp_rows[0].get("employee_name") or "Employee"
            summaries.append(
                {
                    "user_id": emp_rows[0].get("user_id"),
                    "employee_name": name,
                    "worker_category": cat,
                    "line_count": len(emp_rows),
                    "regular_hours": metrics.get("regular_hours"),
                    "ot_hours": metrics.get("ot_hours"),
                    "total_hours": metrics.get("total_hours"),
                    "regular_earnings": metrics.get("regular_earnings"),
                    "ot_earnings": metrics.get("ot_earnings"),
                    "base_earnings": metrics.get("base_earnings"),
                    "ot_premium": metrics.get("ot_premium"),
                    "other_earnings": metrics.get("other_earnings"),
                    "gross_pay": metrics.get("gross_pay"),
                    "employer_taxes": metrics.get("employer_taxes"),
                    "total_payroll_cost": metrics.get("total_payroll_cost"),
                    "avg_pay_rate": metrics.get("avg_pay_rate"),
                    "avg_cost_per_hour": metrics.get("avg_cost_per_hour"),
                }
            )
        summaries.sort(
            key=lambda s: (str(s.get("employee_name") or "").lower(), int(s.get("user_id") or 0))
        )
        out[cat] = summaries
    return out


def employment_mix_by_period(
    period_rows_map: dict[tuple[str, str], list[dict]],
    ordered_periods: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Stacked employment-mix series: W-2 gross, ER taxes, Temp, 1099."""
    out = []
    for ps, pe in ordered_periods:
        rows = period_rows_map.get((ps, pe)) or []
        by_cat: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            by_cat[str(row.get("worker_category") or "unknown")].append(row)
        w2 = aggregate_period_metrics(by_cat.get("w2") or [])
        temp = aggregate_period_metrics(by_cat.get("temp") or [])
        c1099 = aggregate_period_metrics(by_cat.get("contractor_1099") or [])
        out.append(
            {
                "pay_period_start": ps,
                "pay_period_end": pe,
                "payroll_period": period_label(ps, pe),
                "w2_gross": _money(w2.get("gross_pay")),
                "w2_employer_taxes": _money(w2.get("employer_taxes")),
                "w2_cost": round(
                    _money(w2.get("gross_pay")) + _money(w2.get("employer_taxes")), 2
                ),
                "temp_gross": _money(temp.get("gross_pay")),
                "temp_cost": _money(temp.get("gross_pay")),
                "contractor_1099_gross": _money(c1099.get("gross_pay")),
                "contractor_1099_cost": _money(c1099.get("gross_pay")),
            }
        )
    return out


def workforce_breakdown_totals(categories: list[dict]) -> dict[str, Any]:
    """Total row for workforce breakdown table."""
    keys = (
        "worker_count",
        "total_hours",
        "regular_hours",
        "ot_hours",
        "regular_earnings",
        "ot_earnings",
        "base_earnings",
        "ot_premium",
        "other_earnings",
        "gross_pay",
        "employer_taxes",
        "total_payroll_cost",
        "employer_cost",
    )
    tot = {k: 0.0 for k in keys}
    for c in categories:
        for k in keys:
            if k == "worker_count":
                tot[k] += int(c.get("head_count") or c.get("worker_count") or 0)
            else:
                tot[k] = round(tot[k] + _money(c.get(k)), 2)
    hours = tot["total_hours"]
    avg_pay = round(tot["gross_pay"] / hours, 2) if hours > 0.005 else None
    avg_cost = (
        round(tot["total_payroll_cost"] / hours, 2) if hours > 0.005 else None
    )
    recon_diff = round(
        tot["gross_pay"]
        - tot["base_earnings"]
        - tot["ot_premium"]
        - tot["other_earnings"],
        2,
    )
    mgmt_diff = round(
        tot["gross_pay"]
        - tot["regular_earnings"]
        - tot["ot_earnings"]
        - tot["other_earnings"],
        2,
    )
    tot["avg_pay_rate"] = avg_pay
    tot["avg_cost_per_hour"] = avg_cost
    tot["avg_rate"] = avg_pay  # legacy alias
    tot["head_count"] = int(tot["worker_count"])
    tot["gross_reconciliation_diff"] = recon_diff
    tot["gross_reconciles"] = abs(recon_diff) < 0.005
    tot["mgmt_reconciliation_diff"] = mgmt_diff
    tot["mgmt_reconciles"] = abs(mgmt_diff) < 0.005
    tot["has_other_earnings"] = abs(tot["other_earnings"]) >= 0.005
    return tot


def build_period_comparison_entries(
    period_rows_map: dict[tuple[str, str], list[dict]],
    ordered_periods: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    prev_metrics: Optional[dict[str, Any]] = None
    for ps, pe in ordered_periods:
        rows = period_rows_map.get((ps, pe)) or []
        metrics = aggregate_period_metrics(rows)
        entry = {
            "pay_period_start": ps,
            "pay_period_end": pe,
            "payroll_period": period_label(ps, pe),
            "pay_dates_label": ", ".join(metrics.get("pay_dates") or []) or "—",
            **metrics,
            "delta_from_previous": {},
            "pct_from_previous": {},
        }
        if prev_metrics is not None:
            for key in COMPARISON_DELTA_KEYS:
                if key == "worker_count":
                    cur = float(metrics.get(key) or 0)
                    prev = float(prev_metrics.get(key) or 0)
                else:
                    cur = _money(metrics.get(key))
                    prev = _money(prev_metrics.get(key))
                d = _delta(cur, prev)
                entry["delta_from_previous"][key] = d["diff"]
                entry["pct_from_previous"][key] = d["pct"]
        entries.append(entry)
        prev_metrics = metrics
    return entries


def select_comparison_periods(
    all_periods_asc: list[tuple[str, str]],
    *,
    anchor_periods: list[tuple[str, str]],
    comparison_range: int,
) -> list[tuple[str, str]]:
    """Return up to N periods ending at the latest anchor, chronological."""
    if not all_periods_asc:
        return []
    n = normalize_comparison_range(comparison_range)
    anchors = [p for p in anchor_periods if p in set(all_periods_asc)]
    if not anchors:
        # Fall back to latest periods overall
        return all_periods_asc[-n:]
    latest_anchor = max(anchors, key=lambda t: (t[1] or "", t[0] or ""))
    try:
        idx = all_periods_asc.index(latest_anchor)
    except ValueError:
        return all_periods_asc[-n:]
    start = max(0, idx - n + 1)
    return all_periods_asc[start : idx + 1]


def batch_is_complete(batch: dict) -> bool:
    """True when a payout batch is paid/closed or payroll details are finalized."""
    st = str(
        batch.get("status") or batch.get("batch_status") or ""
    ).strip().lower()
    if st in TERMINAL_BATCH_STATUSES:
        return True
    if batch.get("payout_details_finalized_at"):
        return True
    return False


def period_batches_are_complete(batches: list[dict]) -> bool:
    """A period is complete when it has ≥1 batch and every batch is terminal.

    Worker category mix is irrelevant — W-2-only or Temp-only weeks count
    when all generated batches for the period are paid/closed/finalized.
    Partially processed periods (any open/draft batch) are incomplete.
    """
    if not batches:
        return False
    return all(batch_is_complete(b) for b in batches)


def complete_period_keys_from_batches(
    batches: list[dict],
) -> set[tuple[str, str]]:
    """Return (start, end) keys for periods whose batches are all complete."""
    by_period: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for b in batches or []:
        ps = str(b.get("pay_period_start") or "")[:10]
        pe = str(b.get("pay_period_end") or "")[:10]
        if ps and pe:
            by_period[(ps, pe)].append(b)
    return {key for key, rows in by_period.items() if period_batches_are_complete(rows)}


def list_org_periods_asc(
    conn, organization_id: int, *, require_complete: bool = True
) -> list[tuple[str, str]]:
    """Distinct payroll periods ascending.

    When require_complete is True (default), only periods where every
    payout batch is paid, closed, or details-finalized are returned.
    """
    c = conn.cursor(dictionary=True)
    if require_complete:
        c.execute(
            """
            SELECT pay_period_start, pay_period_end
            FROM payout_batches
            WHERE organization_id = %s
              AND pay_period_start IS NOT NULL
              AND pay_period_end IS NOT NULL
            GROUP BY pay_period_start, pay_period_end
            HAVING COUNT(*) > 0
               AND SUM(
                     CASE
                       WHEN LOWER(COALESCE(status, '')) IN ('paid', 'closed')
                         OR payout_details_finalized_at IS NOT NULL
                       THEN 0
                       ELSE 1
                     END
                   ) = 0
            ORDER BY pay_period_start ASC, pay_period_end ASC
            """,
            (int(organization_id),),
        )
    else:
        c.execute(
            """
            SELECT DISTINCT pay_period_start, pay_period_end
            FROM payout_batches
            WHERE organization_id = %s
              AND pay_period_start IS NOT NULL
              AND pay_period_end IS NOT NULL
            ORDER BY pay_period_start ASC, pay_period_end ASC
            """,
            (int(organization_id),),
        )
    out = []
    for r in c.fetchall() or []:
        ps = str(r["pay_period_start"])[:10]
        pe = str(r["pay_period_end"])[:10]
        if ps and pe:
            out.append((ps, pe))
    return out


def fetch_rows_for_periods(
    conn,
    organization_id: int,
    periods: list[tuple[str, str]],
    *,
    user_id: Optional[int] = None,
    worker_category: Optional[str] = None,
    payroll_status: Optional[str] = None,
    payment_status: Optional[str] = None,
) -> list[dict]:
    """Load report rows for explicit payroll periods (no nested analytics)."""
    if not periods:
        return []
    from backend.payroll_report import query_payroll_report

    starts = [p[0] for p in periods]
    ends = [p[1] for p in periods]
    report = query_payroll_report(
        conn,
        organization_id,
        period_starts=starts,
        period_ends=ends,
        report_type="payroll_period",
        user_id=user_id,
        worker_category=worker_category,
        payroll_status=payroll_status,
        payment_status=payment_status,
        include_analytics=False,
        limit=20000,
    )
    return list(report.get("rows") or [])


def _fetch_monthly_paid_rows(
    conn,
    organization_id: int,
    *,
    month: int,
    year: int,
    user_id: Optional[int] = None,
    worker_category: Optional[str] = None,
    payroll_status: Optional[str] = None,
    payment_status: Optional[str] = None,
) -> list[dict]:
    """Load Monthly Payroll Paid rows for a calendar month (no nested analytics)."""
    from backend.payroll_report import query_payroll_report

    report = query_payroll_report(
        conn,
        organization_id,
        report_type="monthly_paid",
        month=int(month),
        year=int(year),
        user_id=user_id,
        worker_category=worker_category,
        payroll_status=payroll_status,
        payment_status=payment_status,
        include_analytics=False,
        limit=20000,
    )
    return list(report.get("rows") or [])


def build_report_analytics(
    conn,
    organization_id: int,
    *,
    detail_rows: list[dict],
    report_type: str,
    filters: dict,
    comparison_range: int = DEFAULT_COMPARISON_RANGE,
    compare_with: Optional[str] = None,
    trend_range: Optional[int] = None,
) -> dict[str, Any]:
    """Build analytics payload — month mode for Monthly Paid, period mode otherwise."""
    groups = group_rows_by_period_then_pay_date(detail_rows)
    detail_metrics = aggregate_period_metrics(detail_rows)
    comparison_mode = "month" if report_type == "monthly_paid" else "period"
    n = normalize_trend_range(
        trend_range if trend_range is not None else comparison_range,
        mode=comparison_mode,
    )
    compare_key = normalize_compare_with(
        compare_with or filters.get("compare_with"), mode=comparison_mode
    )

    common_filters = dict(
        user_id=filters.get("user_id"),
        worker_category=filters.get("worker_category"),
        payroll_status=filters.get("payroll_status"),
        payment_status=filters.get("payment_status"),
    )

    all_periods = list_org_periods_asc(conn, organization_id, require_complete=True)
    complete_set = set(all_periods)

    period_comparison: list[dict] = []
    month_comparison: list[dict] = []
    employment_mix: list[dict] = []
    focus_label = None
    previous_label = None
    focus_is_partial = False
    focus_metrics = detail_metrics
    prev_metrics = None
    analytics_rows = list(detail_rows)

    if comparison_mode == "month":
        try:
            month_i = int(filters.get("month"))
            year_i = int(filters.get("year"))
        except (TypeError, ValueError):
            month_i, year_i = None, None
        if not (month_i and year_i and 1 <= month_i <= 12):
            month_i = year_i = None

        from datetime import date as _date

        today = _date.today()
        focus_is_partial = bool(
            month_i and year_i and (year_i, month_i) >= (today.year, today.month)
        )
        if month_i and year_i:
            focus_label = month_label(year_i, month_i)
            if focus_is_partial:
                focus_label = f"{focus_label} (month to date)"

            # Trend: one bucket per calendar month (Official Pay Date membership).
            trend_months = select_trend_months(year_i, month_i, n)
            month_buckets = []
            for y, m in trend_months:
                if (y, m) == (year_i, month_i):
                    rows_m = list(detail_rows)
                else:
                    rows_m = _fetch_monthly_paid_rows(
                        conn, organization_id, month=m, year=y, **common_filters
                    )
                metrics = aggregate_period_metrics(rows_m)
                partial = (y, m) >= (today.year, today.month)
                month_buckets.append(
                    {
                        **metrics,
                        "month": f"{y:04d}-{m:02d}",
                        "year": y,
                        "month_num": m,
                        "label": month_label(y, m)
                        + (" (month to date)" if partial else ""),
                        "pay_dates_label": ", ".join(metrics.get("pay_dates") or []),
                        "is_partial": partial,
                        "worker_count": metrics.get("worker_count", 0),
                        "head_count": metrics.get("worker_count", 0),
                    }
                )
            month_comparison = build_month_comparison_entries(month_buckets)

            # Employment mix by month (reuse period helper shape with synthetic keys).
            mix_map: dict[tuple[str, str], list[dict]] = {}
            ordered_keys: list[tuple[str, str]] = []
            for y, m in trend_months:
                key = (f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-28")
                ordered_keys.append(key)
                if (y, m) == (year_i, month_i):
                    mix_map[key] = list(detail_rows)
                else:
                    mix_map[key] = _fetch_monthly_paid_rows(
                        conn, organization_id, month=m, year=y, **common_filters
                    )
            employment_mix = employment_mix_by_period(mix_map, ordered_keys)
            for i, e in enumerate(employment_mix):
                y, m = trend_months[i]
                e["month"] = f"{y:04d}-{m:02d}"
                e["label"] = month_label(y, m)
                e["payroll_period"] = month_label(y, m)

            # Compare With target month
            if compare_key == "same_month_last_year":
                cy, cm = year_i - 1, month_i
            else:
                cy, cm = shift_month(year_i, month_i, -1)
            previous_label = month_label(cy, cm)
            prev_rows = _fetch_monthly_paid_rows(
                conn, organization_id, month=cm, year=cy, **common_filters
            )
            if prev_rows:
                prev_metrics = aggregate_period_metrics(prev_rows)
            else:
                previous_label = None
            focus_metrics = aggregate_period_metrics(detail_rows)
            analytics_rows = list(detail_rows)
    else:
        # Period mode
        anchor_periods = [
            (g["pay_period_start"], g["pay_period_end"])
            for g in groups
            if g.get("pay_period_start") and g.get("pay_period_end")
        ]
        if report_type == "payroll_period":
            starts = filters.get("period_starts") or []
            ends = filters.get("period_ends") or []
            if starts and ends and len(starts) == len(ends):
                anchor_periods = list(
                    zip(
                        [str(s)[:10] for s in starts],
                        [str(e)[:10] for e in ends],
                    )
                )
        complete_anchors = [p for p in anchor_periods if p in complete_set]
        selected = select_comparison_periods(
            all_periods, anchor_periods=complete_anchors, comparison_range=n
        )
        analytics_rows = [
            r
            for r in detail_rows
            if (period_key_from_row(r) in complete_set)
            or (not period_key_from_row(r)[0] and not period_key_from_row(r)[1])
        ]
        if not analytics_rows and detail_rows and not complete_anchors:
            analytics_rows = []

        period_rows_map: dict[tuple[str, str], list[dict]] = defaultdict(list)
        detail_period_set = set(complete_anchors)
        for row in analytics_rows:
            key = period_key_from_row(row)
            if key[0] and key[1]:
                period_rows_map[key].append(row)
        fetch_periods = [p for p in selected if p not in detail_period_set]
        if fetch_periods:
            extra = fetch_rows_for_periods(
                conn, organization_id, fetch_periods, **common_filters
            )
            for row in extra:
                key = period_key_from_row(row)
                period_rows_map[key].append(row)
        for p in selected:
            period_rows_map.setdefault(p, [])
        period_comparison = build_period_comparison_entries(period_rows_map, selected)
        employment_mix = employment_mix_by_period(period_rows_map, selected)

        focus = None
        if complete_anchors:
            focus = max(complete_anchors, key=lambda t: (t[1] or "", t[0] or ""))
        elif selected:
            focus = selected[-1]
        if focus:
            focus_label = format_focus_period_label(focus[0], focus[1])
            idx = next(
                (
                    i
                    for i, e in enumerate(period_comparison)
                    if e.get("pay_period_start") == focus[0]
                    and e.get("pay_period_end") == focus[1]
                ),
                None,
            )
            if report_type == "payroll_period" and len(complete_anchors) == 1 and idx is not None:
                focus_metrics = period_comparison[idx]
            else:
                focus_metrics = aggregate_period_metrics(analytics_rows)

            if compare_key == "same_period_4_weeks_earlier":
                prior = find_period_4_weeks_earlier(all_periods, focus)
                if prior:
                    prior_rows = period_rows_map.get(prior) or fetch_rows_for_periods(
                        conn, organization_id, [prior], **common_filters
                    )
                    if prior_rows:
                        prev_metrics = aggregate_period_metrics(prior_rows)
                        previous_label = format_focus_period_label(prior[0], prior[1])
            else:
                if idx is not None and idx > 0:
                    prev_metrics = period_comparison[idx - 1]
                    previous_label = format_focus_period_label(
                        prev_metrics.get("pay_period_start") or "",
                        prev_metrics.get("pay_period_end") or "",
                    )
                elif focus in complete_set:
                    try:
                        fi = all_periods.index(focus)
                    except ValueError:
                        fi = -1
                    if fi > 0:
                        prior = all_periods[fi - 1]
                        prior_rows = fetch_rows_for_periods(
                            conn, organization_id, [prior], **common_filters
                        )
                        if prior_rows:
                            prev_metrics = aggregate_period_metrics(prior_rows)
                            previous_label = format_focus_period_label(prior[0], prior[1])

    categories = attach_category_cost_shares(category_breakdown(analytics_rows))
    workforce_totals = workforce_breakdown_totals(categories)
    kpis = build_kpi_cards(focus_metrics, prev_metrics)
    ot_summary = build_ot_summary(focus_metrics, prev_metrics)
    narrative = build_executive_narrative(focus_metrics, prev_metrics, categories)

    overtime_analysis = month_comparison if comparison_mode == "month" else period_comparison

    pay_date_count = len(
        {
            str(r.get("pay_date") or r.get("official_pay_date") or "")[:10]
            for r in detail_rows
            if str(r.get("pay_date") or r.get("official_pay_date") or "").strip()
        }
    )

    include_identities = bool(filters.get("include_employee_detail", True))
    employee_summaries = employee_summaries_by_category(
        detail_rows, include_identities=include_identities
    )

    compare_options = (
        [{"value": k, "label": lab} for k, lab in COMPARE_WITH_MONTH]
        if comparison_mode == "month"
        else [{"value": k, "label": lab} for k, lab in COMPARE_WITH_PERIOD]
    )
    trend_options = list(
        MONTH_TREND_OPTIONS if comparison_mode == "month" else PERIOD_TREND_OPTIONS
    )

    summary = {
        **detail_metrics,
        "payroll_period_count": len(groups),
        "official_pay_date_count": pay_date_count,
        "unique_employees": detail_metrics.get("worker_count", 0),
        "head_count": detail_metrics.get("worker_count", 0),
        "comparison_range": n,
        "trend_range": n,
        "compare_with": compare_key,
        "comparison_mode": comparison_mode,
        "focus_period": focus_label,
        "previous_period": previous_label,
        "focus_kind": comparison_mode,
        "focus_is_partial": focus_is_partial,
    }

    return {
        "summary": summary,
        "kpis": kpis,
        "ot_summary": ot_summary,
        "executive_narrative": narrative,
        "period_comparison": period_comparison,
        "month_comparison": month_comparison,
        "category_breakdown": categories,
        "workforce_totals": workforce_totals,
        "employment_mix": employment_mix,
        "employee_summaries_by_category": employee_summaries,
        "access": {
            "can_view_employee_detail": include_identities,
            "layout": "executive_v4",
        },
        "overtime_analysis": overtime_analysis,
        "groups": groups if include_identities else [],
        "comparison_mode": comparison_mode,
        "compare_with": compare_key,
        "compare_with_options": compare_options,
        "trend_range": n,
        "trend_range_options": trend_options,
        "comparison_range": n,
        "comparison_range_options": trend_options,
        "chart_titles": chart_titles_for_mode(comparison_mode),
        "layout": "executive_v4",
    }


from backend.payroll_report_analytics_charts import build_analytics_chart_svgs  # noqa: E402
