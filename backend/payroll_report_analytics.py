"""Payroll report analytics: period comparison, KPIs, nested groups, PDF chart SVG.

Presentation only — reuses report row totals; does not mutate payroll amounts.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from backend.payroll_operations import CATEGORY_LABELS

COMPARISON_RANGE_OPTIONS = (4, 8, 12)
DEFAULT_COMPARISON_RANGE = 4

KPI_DEFS = (
    ("total_hours", "Total Hours", "hours"),
    ("regular_hours", "Regular Hours", "hours"),
    ("ot_hours", "OT Hours", "hours"),
    ("gross_pay", "Gross Payroll", "money"),
    ("ot_premium", "OT Premium", "money"),
    ("employee_tax_deductions", "Employee Taxes", "money"),
    ("net_pay", "Net Pay", "money"),
    ("employer_taxes", "Employer Taxes", "money"),
    ("total_payroll_cost", "Total Payroll Cost", "money"),
    ("amount_paid", "Amount Paid", "money"),
    ("outstanding_balance", "Outstanding Balance", "money"),
    ("worker_count", "Employee/Worker Count", "count"),
)

# Increases are not styled as "good" for these cost-like metrics.
NEUTRAL_TREND_KEYS = frozenset(
    {
        "ot_hours",
        "ot_premium",
        "employer_taxes",
        "total_payroll_cost",
        "gross_pay",
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
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_COMPARISON_RANGE
    if n in COMPARISON_RANGE_OPTIONS:
        return n
    if n <= 4:
        return 4
    if n <= 8:
        return 8
    return 12


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

    totals = _sum_totals(rows)
    user_ids = {r.get("user_id") for r in rows if r.get("user_id") is not None}
    names = {
        " ".join(str(r.get("employee_name") or "").split())
        for r in rows
        if str(r.get("employee_name") or "").strip()
    }
    pay_dates = sorted(
        {
            str(r.get("pay_date") or r.get("official_pay_date") or "")[:10]
            for r in rows
            if str(r.get("pay_date") or r.get("official_pay_date") or "").strip()
        }
    )
    reg = _money(totals.get("regular_hours"))
    ot = _money(totals.get("ot_hours"))
    total_hours = round(reg + ot, 2)
    gross = _money(totals.get("gross_pay"))
    cost = _money(totals.get("total_payroll_cost"))
    avg_cost = round(cost / total_hours, 2) if total_hours > 0.005 else None
    ot_pct_hours = round((ot / total_hours) * 100.0, 2) if total_hours > 0.005 else 0.0
    ot_pct_gross = (
        round((_money(totals.get("ot_premium")) / gross) * 100.0, 2) if gross > 0.005 else 0.0
    )
    return {
        **totals,
        "total_hours": total_hours,
        "worker_count": len(user_ids) if user_ids else len(names),
        "pay_dates": pay_dates,
        "pay_date_count": len(pay_dates),
        "avg_cost_per_hour": avg_cost,
        "ot_pct_of_hours": ot_pct_hours,
        "ot_premium_pct_of_gross": ot_pct_gross,
        "line_count": len(rows),
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
        cur_val = _money(current.get(key)) if kind != "count" else int(current.get(key) or 0)
        prev_val = None
        if previous is not None:
            prev_val = (
                _money(previous.get(key))
                if kind != "count"
                else int(previous.get(key) or 0)
            )
        delta = _delta(float(cur_val), float(prev_val) if prev_val is not None else None)
        cards.append(
            {
                "key": key,
                "label": label,
                "kind": kind,
                "value": cur_val,
                "neutral_trend": key in NEUTRAL_TREND_KEYS,
                **delta,
            }
        )
    return cards


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
        out.append(
            {
                "worker_category": cat,
                "label": CATEGORY_LABELS.get(cat, cat),
                **metrics,
            }
        )
    return out


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
            for key, _label, kind in KPI_DEFS:
                if kind == "count":
                    cur = float(metrics.get(key) or 0)
                    prev = float(prev_metrics.get(key) or 0)
                else:
                    cur = _money(metrics.get(key))
                    prev = _money(prev_metrics.get(key))
                d = _delta(cur, prev)
                entry["delta_from_previous"][key] = d["diff"]
                entry["pct_from_previous"][key] = d["pct"]
            # Also include table money/hour extras
            for key in (
                "base_earnings",
                "total_payroll_cost",
                "avg_cost_per_hour",
            ):
                d = _delta(_money(metrics.get(key)), _money(prev_metrics.get(key)))
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


def list_org_periods_asc(conn, organization_id: int) -> list[tuple[str, str]]:
    c = conn.cursor(dictionary=True)
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


def build_report_analytics(
    conn,
    organization_id: int,
    *,
    detail_rows: list[dict],
    report_type: str,
    filters: dict,
    comparison_range: int = DEFAULT_COMPARISON_RANGE,
) -> dict[str, Any]:
    """Build analytics payload from detail rows + preceding payroll periods."""
    n = normalize_comparison_range(comparison_range)
    groups = group_rows_by_period_then_pay_date(detail_rows)
    detail_metrics = aggregate_period_metrics(detail_rows)

    anchor_periods = [
        (g["pay_period_start"], g["pay_period_end"])
        for g in groups
        if g.get("pay_period_start") and g.get("pay_period_end")
    ]
    # For monthly_paid / custom / all_history, anchors are periods present in detail.
    # For payroll_period, anchors are the selected periods.
    if report_type == "payroll_period":
        starts = filters.get("period_starts") or []
        ends = filters.get("period_ends") or []
        if starts and ends and len(starts) == len(ends):
            anchor_periods = list(zip(
                [str(s)[:10] for s in starts],
                [str(e)[:10] for e in ends],
            ))

    all_periods = list_org_periods_asc(conn, organization_id)
    selected = select_comparison_periods(
        all_periods, anchor_periods=anchor_periods, comparison_range=n
    )

    period_rows_map: dict[tuple[str, str], list[dict]] = defaultdict(list)
    # Seed with detail rows (exact filtered membership for periods in selection)
    detail_period_set = set(anchor_periods)
    for row in detail_rows:
        key = period_key_from_row(row)
        if key[0] and key[1]:
            period_rows_map[key].append(row)

    missing = [p for p in selected if p not in period_rows_map or not period_rows_map[p]]
    # Periods in comparison window but outside detail filter window need a fetch.
    # Always fetch non-detail periods; for periods inside detail, keep detail rows
    # so dashboard matches the filtered report.
    fetch_periods = [p for p in selected if p not in detail_period_set]
    if fetch_periods:
        extra = fetch_rows_for_periods(
            conn,
            organization_id,
            fetch_periods,
            user_id=filters.get("user_id"),
            worker_category=filters.get("worker_category"),
            payroll_status=filters.get("payroll_status"),
            payment_status=filters.get("payment_status"),
        )
        for row in extra:
            key = period_key_from_row(row)
            period_rows_map[key].append(row)

    # Ensure empty shells for selected periods with no rows
    for p in selected:
        period_rows_map.setdefault(p, [])

    period_comparison = build_period_comparison_entries(period_rows_map, selected)

    # Focus period for KPI deltas: latest period in comparison that is in the
    # selected report when possible; else latest comparison period.
    focus = None
    if anchor_periods:
        focus = max(anchor_periods, key=lambda t: (t[1] or "", t[0] or ""))
    elif selected:
        focus = selected[-1]

    focus_metrics = detail_metrics
    prev_metrics = None
    if focus and period_comparison:
        # Prefer full selected-report totals as KPI "current" so dashboard
        # reconciles with detail; previous = period immediately before focus.
        idx = next(
            (
                i
                for i, e in enumerate(period_comparison)
                if e.get("pay_period_start") == focus[0]
                and e.get("pay_period_end") == focus[1]
            ),
            None,
        )
        if idx is not None and idx > 0:
            prev_metrics = period_comparison[idx - 1]
        # For single-period reports, current KPIs use that period's metrics
        # (equal to detail). For monthly multi-period, current = detail totals.
        if report_type == "payroll_period" and len(anchor_periods) == 1 and idx is not None:
            focus_metrics = period_comparison[idx]

    kpis = build_kpi_cards(focus_metrics, prev_metrics)

    # Category breakdown from detail rows (respects filters)
    categories = category_breakdown(detail_rows)

    overtime_analysis = [
        {
            "payroll_period": e["payroll_period"],
            "pay_period_start": e["pay_period_start"],
            "pay_period_end": e["pay_period_end"],
            "ot_hours": e.get("ot_hours", 0),
            "ot_premium": e.get("ot_premium", 0),
            "ot_pct_of_hours": e.get("ot_pct_of_hours", 0),
            "ot_premium_pct_of_gross": e.get("ot_premium_pct_of_gross", 0),
            "total_hours": e.get("total_hours", 0),
            "gross_pay": e.get("gross_pay", 0),
        }
        for e in period_comparison
    ]

    pay_date_count = len(
        {
            str(r.get("pay_date") or r.get("official_pay_date") or "")[:10]
            for r in detail_rows
            if str(r.get("pay_date") or r.get("official_pay_date") or "").strip()
        }
    )

    summary = {
        **detail_metrics,
        "payroll_period_count": len(groups),
        "official_pay_date_count": pay_date_count,
        "unique_employees": detail_metrics.get("worker_count", 0),
        "comparison_range": n,
        "focus_period": period_label(focus[0], focus[1]) if focus else None,
        "previous_period": (
            prev_metrics.get("payroll_period") if prev_metrics else None
        ),
    }

    return {
        "summary": summary,
        "kpis": kpis,
        "period_comparison": period_comparison,
        "category_breakdown": categories,
        "overtime_analysis": overtime_analysis,
        "groups": groups,
        "comparison_range": n,
        "comparison_range_options": list(COMPARISON_RANGE_OPTIONS),
    }


# --- PDF SVG charts (no JS dependency; html2canvas-friendly) ---


def _svg_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _scale(vals: list[float], height: float, pad: float = 8.0) -> tuple[float, list[float]]:
    mx = max(vals) if vals else 0.0
    if mx <= 0:
        mx = 1.0
    usable = height - pad * 2
    return mx, [pad + usable * (1 - (v / mx)) for v in vals]


def render_cost_trajectory_svg(period_comparison: list[dict], *, width: int = 520, height: int = 200) -> str:
    if not period_comparison:
        return _empty_chart_svg(width, height, "No period data")
    labels = [e.get("pay_period_end") or e.get("payroll_period") or "" for e in period_comparison]
    series = {
        "Total Payroll Cost": [ _money(e.get("total_payroll_cost")) for e in period_comparison ],
        "Gross Payroll": [ _money(e.get("gross_pay")) for e in period_comparison ],
        "Net Pay": [ _money(e.get("net_pay")) for e in period_comparison ],
    }
    colors = {
        "Total Payroll Cost": "#007a91",
        "Gross Payroll": "#0097b2",
        "Net Pay": "#c4a052",
    }
    all_vals = [v for vals in series.values() for v in vals]
    mx, _ = _scale(all_vals, height - 40)
    n = len(period_comparison)
    left, right, top, bottom = 44, width - 12, 18, height - 36
    plot_w = right - left
    plot_h = bottom - top

    def x_at(i: int) -> float:
        if n == 1:
            return left + plot_w / 2
        return left + (plot_w * i / (n - 1))

    def y_at(v: float) -> float:
        return top + plot_h * (1 - (v / mx if mx else 0))

    paths = []
    for name, vals in series.items():
        pts = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(vals))
        paths.append(
            f'<polyline fill="none" stroke="{colors[name]}" stroke-width="2" points="{pts}" />'
        )
        for i, v in enumerate(vals):
            paths.append(
                f'<circle cx="{x_at(i):.1f}" cy="{y_at(v):.1f}" r="2.5" fill="{colors[name]}" />'
            )

    legend = []
    lx = left
    for name, color in colors.items():
        legend.append(
            f'<rect x="{lx}" y="2" width="10" height="10" fill="{color}" />'
            f'<text x="{lx + 14}" y="11" font-size="9" fill="#334155">{_svg_escape(name)}</text>'
        )
        lx += 130

    xlabels = []
    for i, lab in enumerate(labels):
        short = str(lab)[-5:] if lab else ""
        xlabels.append(
            f'<text x="{x_at(i):.1f}" y="{height - 8}" font-size="8" text-anchor="middle" fill="#64748b">{_svg_escape(short)}</text>'
        )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#ffffff"/>
  <text x="{left}" y="12" font-size="11" font-weight="700" fill="#007a91">Total payroll cost trajectory</text>
  {"".join(legend)}
  <line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#e2e8f0"/>
  <line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#e2e8f0"/>
  {"".join(paths)}
  {"".join(xlabels)}
</svg>'''


def render_hours_stacked_svg(period_comparison: list[dict], *, width: int = 520, height: int = 200) -> str:
    if not period_comparison:
        return _empty_chart_svg(width, height, "No period data")
    n = len(period_comparison)
    left, right, top, bottom = 44, width - 12, 28, height - 36
    plot_w = right - left
    plot_h = bottom - top
    totals = [
        _money(e.get("regular_hours")) + _money(e.get("ot_hours"))
        for e in period_comparison
    ]
    mx = max(totals) if totals else 1.0
    if mx <= 0:
        mx = 1.0
    gap = 8
    bar_w = max(8.0, (plot_w / max(n, 1)) - gap)
    parts = [
        f'<text x="{left}" y="14" font-size="11" font-weight="700" fill="#007a91">Hours trajectory</text>',
        '<rect x="44" y="2" width="10" height="10" fill="#0097b2"/><text x="58" y="11" font-size="9" fill="#334155">Regular</text>',
        '<rect x="120" y="2" width="10" height="10" fill="#c4a052"/><text x="134" y="11" font-size="9" fill="#334155">OT</text>',
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#e2e8f0"/>',
    ]
    for i, e in enumerate(period_comparison):
        reg = _money(e.get("regular_hours"))
        ot = _money(e.get("ot_hours"))
        x = left + i * (plot_w / max(n, 1)) + gap / 2
        h_reg = plot_h * (reg / mx)
        h_ot = plot_h * (ot / mx)
        y_ot = bottom - h_ot
        y_reg = y_ot - h_reg
        parts.append(
            f'<rect x="{x:.1f}" y="{y_reg:.1f}" width="{bar_w:.1f}" height="{h_reg:.1f}" fill="#0097b2"/>'
        )
        parts.append(
            f'<rect x="{x:.1f}" y="{y_ot:.1f}" width="{bar_w:.1f}" height="{h_ot:.1f}" fill="#c4a052"/>'
        )
        total = reg + ot
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{y_reg - 3:.1f}" font-size="8" text-anchor="middle" fill="#475569">{total:.0f}</text>'
        )
        lab = str(e.get("pay_period_end") or "")[-5:]
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{height - 8}" font-size="8" text-anchor="middle" fill="#64748b">{_svg_escape(lab)}</text>'
        )
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#fff"/>{"".join(parts)}</svg>'


def render_cost_composition_svg(period_comparison: list[dict], *, width: int = 520, height: int = 200) -> str:
    if not period_comparison:
        return _empty_chart_svg(width, height, "No period data")
    n = len(period_comparison)
    left, right, top, bottom = 44, width - 12, 28, height - 36
    plot_w = right - left
    plot_h = bottom - top
    stacks = [
        (_money(e.get("gross_pay")), _money(e.get("employer_taxes")))
        for e in period_comparison
    ]
    mx = max((g + er for g, er in stacks), default=1.0) or 1.0
    gap = 8
    bar_w = max(8.0, (plot_w / max(n, 1)) - gap)
    parts = [
        f'<text x="{left}" y="14" font-size="11" font-weight="700" fill="#007a91">Payroll-cost composition</text>',
        '<rect x="44" y="2" width="10" height="10" fill="#0097b2"/><text x="58" y="11" font-size="9" fill="#334155">Gross</text>',
        '<rect x="120" y="2" width="10" height="10" fill="#64748b"/><text x="134" y="11" font-size="9" fill="#334155">ER taxes</text>',
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#e2e8f0"/>',
    ]
    for i, (gross, er) in enumerate(stacks):
        x = left + i * (plot_w / max(n, 1)) + gap / 2
        h_g = plot_h * (gross / mx)
        h_e = plot_h * (er / mx)
        y_e = bottom - h_e
        y_g = y_e - h_g
        parts.append(
            f'<rect x="{x:.1f}" y="{y_g:.1f}" width="{bar_w:.1f}" height="{h_g:.1f}" fill="#0097b2"/>'
        )
        parts.append(
            f'<rect x="{x:.1f}" y="{y_e:.1f}" width="{bar_w:.1f}" height="{h_e:.1f}" fill="#64748b"/>'
        )
        lab = str(period_comparison[i].get("pay_period_end") or "")[-5:]
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{height - 8}" font-size="8" text-anchor="middle" fill="#64748b">{_svg_escape(lab)}</text>'
        )
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#fff"/>{"".join(parts)}</svg>'


def render_overtime_analysis_svg(overtime_analysis: list[dict], *, width: int = 520, height: int = 200) -> str:
    if not overtime_analysis:
        return _empty_chart_svg(width, height, "No OT data")
    # Dual: OT hours as bars, OT premium as line (scaled independently visually via labels)
    n = len(overtime_analysis)
    left, right, top, bottom = 44, width - 12, 28, height - 36
    plot_w = right - left
    plot_h = bottom - top
    hours = [_money(e.get("ot_hours")) for e in overtime_analysis]
    prem = [_money(e.get("ot_premium")) for e in overtime_analysis]
    mx_h = max(hours) if hours else 1.0
    mx_p = max(prem) if prem else 1.0
    if mx_h <= 0:
        mx_h = 1.0
    if mx_p <= 0:
        mx_p = 1.0
    gap = 8
    bar_w = max(8.0, (plot_w / max(n, 1)) - gap)
    parts = [
        f'<text x="{left}" y="14" font-size="11" font-weight="700" fill="#007a91">Overtime analysis</text>',
        '<rect x="44" y="2" width="10" height="10" fill="#c4a052"/><text x="58" y="11" font-size="9" fill="#334155">OT hrs</text>',
        '<line x1="120" y1="7" x2="140" y2="7" stroke="#007a91" stroke-width="2"/>'
        '<text x="144" y="11" font-size="9" fill="#334155">OT premium</text>',
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#e2e8f0"/>',
    ]
    pts = []
    for i, e in enumerate(overtime_analysis):
        x = left + i * (plot_w / max(n, 1)) + gap / 2
        h = plot_h * (hours[i] / mx_h)
        y = bottom - h
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="#c4a052" opacity="0.85"/>'
        )
        cx = x + bar_w / 2
        cy = top + plot_h * (1 - (prem[i] / mx_p))
        pts.append(f"{cx:.1f},{cy:.1f}")
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.5" fill="#007a91"/>')
        pct = e.get("ot_pct_of_hours") or 0
        parts.append(
            f'<text x="{cx:.1f}" y="{y - 3:.1f}" font-size="7" text-anchor="middle" fill="#64748b">{pct:.0f}%</text>'
        )
        lab = str(e.get("pay_period_end") or "")[-5:]
        parts.append(
            f'<text x="{cx:.1f}" y="{height - 8}" font-size="8" text-anchor="middle" fill="#64748b">{_svg_escape(lab)}</text>'
        )
    parts.append(
        f'<polyline fill="none" stroke="#007a91" stroke-width="2" points="{" ".join(pts)}" />'
    )
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#fff"/>{"".join(parts)}</svg>'


def render_category_comparison_svg(category_breakdown: list[dict], *, width: int = 520, height: int = 200) -> str:
    if not category_breakdown:
        return _empty_chart_svg(width, height, "No category data")
    n = len(category_breakdown)
    left, right, top, bottom = 80, width - 12, 28, height - 36
    plot_w = right - left
    plot_h = bottom - top
    costs = [_money(c.get("total_payroll_cost")) for c in category_breakdown]
    hours = [_money(c.get("total_hours")) for c in category_breakdown]
    mx_c = max(costs) if costs else 1.0
    mx_h = max(hours) if hours else 1.0
    if mx_c <= 0:
        mx_c = 1.0
    if mx_h <= 0:
        mx_h = 1.0
    gap = 16
    pair_w = max(20.0, (plot_w / max(n, 1)) - gap)
    bar_w = pair_w / 2 - 2
    parts = [
        f'<text x="12" y="14" font-size="11" font-weight="700" fill="#007a91">Category comparison</text>',
        '<rect x="200" y="2" width="10" height="10" fill="#0097b2"/><text x="214" y="11" font-size="9" fill="#334155">Cost</text>',
        '<rect x="260" y="2" width="10" height="10" fill="#94a3b8"/><text x="274" y="11" font-size="9" fill="#334155">Hours</text>',
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#e2e8f0"/>',
    ]
    for i, c in enumerate(category_breakdown):
        x0 = left + i * (plot_w / max(n, 1)) + gap / 2
        h_c = plot_h * (costs[i] / mx_c)
        h_h = plot_h * (hours[i] / mx_h)
        parts.append(
            f'<rect x="{x0:.1f}" y="{bottom - h_c:.1f}" width="{bar_w:.1f}" height="{h_c:.1f}" fill="#0097b2"/>'
        )
        parts.append(
            f'<rect x="{x0 + bar_w + 4:.1f}" y="{bottom - h_h:.1f}" width="{bar_w:.1f}" height="{h_h:.1f}" fill="#94a3b8"/>'
        )
        lab = str(c.get("label") or c.get("worker_category") or "")[:12]
        parts.append(
            f'<text x="{x0 + pair_w / 2:.1f}" y="{height - 8}" font-size="9" text-anchor="middle" fill="#64748b">{_svg_escape(lab)}</text>'
        )
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#fff"/>{"".join(parts)}</svg>'


def _empty_chart_svg(width: int, height: int, msg: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#f8fafc"/>
  <text x="{width/2}" y="{height/2}" font-size="11" text-anchor="middle" fill="#94a3b8">{_svg_escape(msg)}</text>
</svg>'''


def build_analytics_chart_svgs(analytics: dict) -> dict[str, str]:
    pc = analytics.get("period_comparison") or []
    return {
        "cost_trajectory": render_cost_trajectory_svg(pc),
        "hours_trajectory": render_hours_stacked_svg(pc),
        "cost_composition": render_cost_composition_svg(pc),
        "overtime_analysis": render_overtime_analysis_svg(
            analytics.get("overtime_analysis") or pc
        ),
        "category_comparison": render_category_comparison_svg(
            analytics.get("category_breakdown") or []
        ),
    }
