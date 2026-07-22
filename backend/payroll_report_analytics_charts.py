"""SVG chart renderers for payroll analytics PDF (html2canvas-friendly)."""

from __future__ import annotations

from typing import Any


def _money(val: Any) -> float:
    try:
        if val is None or val == "":
            return 0.0
        return round(float(val), 2)
    except (TypeError, ValueError):
        return 0.0


def _svg_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _empty_chart_svg(width: int, height: int, msg: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="100%" height="100%" fill="#f8fafc"/>'
        f'<text x="{width / 2}" y="{height / 2}" font-size="11" text-anchor="middle" '
        f'fill="#94a3b8">{_svg_escape(msg)}</text></svg>'
    )


def _period_label_short(e: dict) -> str:
    return str(e.get("pay_period_end") or e.get("payroll_period") or "")[-5:]


def render_cost_trajectory_svg(
    period_comparison: list[dict], *, width: int = 520, height: int = 190
) -> str:
    if not period_comparison:
        return _empty_chart_svg(width, height, "No period data")
    n = len(period_comparison)
    left, right, top, bottom = 44, width - 12, 28, height - 28
    plot_w, plot_h = right - left, bottom - top
    cost = [_money(e.get("total_payroll_cost")) for e in period_comparison]
    gross = [_money(e.get("gross_pay")) for e in period_comparison]
    mx = max(cost + gross) or 1.0

    def x_at(i: int) -> float:
        return left + plot_w / 2 if n == 1 else left + (plot_w * i / (n - 1))

    def y_at(v: float) -> float:
        return top + plot_h * (1 - (v / mx))

    parts = [
        f'<text x="{left}" y="14" font-size="11" font-weight="700" fill="#007a91">Payroll cost trend</text>',
        '<rect x="220" y="4" width="10" height="10" fill="#007a91"/>'
        '<text x="234" y="13" font-size="9" fill="#334155">Total cost</text>',
        '<rect x="310" y="4" width="10" height="10" fill="#0097b2"/>'
        '<text x="324" y="13" font-size="9" fill="#334155">Gross</text>',
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#e2e8f0"/>',
    ]
    for vals, color in ((cost, "#007a91"), (gross, "#0097b2")):
        pts = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(vals))
        parts.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{pts}" />'
        )
        for i, v in enumerate(vals):
            parts.append(
                f'<circle cx="{x_at(i):.1f}" cy="{y_at(v):.1f}" r="2.5" fill="{color}" />'
            )
    for i, e in enumerate(period_comparison):
        parts.append(
            f'<text x="{x_at(i):.1f}" y="{height - 6}" font-size="8" text-anchor="middle" '
            f'fill="#64748b">{_svg_escape(_period_label_short(e))}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#fff"/>'
        f'{"".join(parts)}</svg>'
    )


def render_hours_stacked_svg(
    period_comparison: list[dict], *, width: int = 520, height: int = 190
) -> str:
    if not period_comparison:
        return _empty_chart_svg(width, height, "No period data")
    n = len(period_comparison)
    left, right, top, bottom = 44, width - 12, 28, height - 28
    plot_w, plot_h = right - left, bottom - top
    totals = [
        _money(e.get("regular_hours")) + _money(e.get("ot_hours"))
        for e in period_comparison
    ]
    mx = max(totals) or 1.0
    gap = 8
    bar_w = max(8.0, (plot_w / max(n, 1)) - gap)
    parts = [
        f'<text x="{left}" y="14" font-size="11" font-weight="700" fill="#007a91">Hours trend</text>',
        '<rect x="160" y="4" width="10" height="10" fill="#0097b2"/>'
        '<text x="174" y="13" font-size="9" fill="#334155">Regular</text>',
        '<rect x="240" y="4" width="10" height="10" fill="#c4a052"/>'
        '<text x="254" y="13" font-size="9" fill="#334155">OT</text>',
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
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{height - 6}" font-size="8" text-anchor="middle" '
            f'fill="#64748b">{_svg_escape(_period_label_short(e))}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#fff"/>'
        f'{"".join(parts)}</svg>'
    )


def render_employment_mix_svg(
    employment_mix: list[dict], *, width: int = 520, height: int = 190
) -> str:
    """Stacked: W-2 gross, W-2 ER taxes, Temp, 1099."""
    if not employment_mix:
        return _empty_chart_svg(width, height, "No mix data")
    n = len(employment_mix)
    left, right, top, bottom = 44, width - 12, 28, height - 28
    plot_w, plot_h = right - left, bottom - top
    stacks = [
        (
            _money(e.get("w2_gross")),
            _money(e.get("w2_employer_taxes")),
            _money(e.get("temp_cost")),
            _money(e.get("contractor_1099_cost")),
        )
        for e in employment_mix
    ]
    mx = max((sum(s) for s in stacks), default=1.0) or 1.0
    gap = 8
    bar_w = max(8.0, (plot_w / max(n, 1)) - gap)
    colors = ("#007a91", "#64748b", "#c4a052", "#94a3b8")
    labels = ("W-2 gross", "ER taxes", "Temp", "1099")
    parts = [
        f'<text x="{left}" y="14" font-size="11" font-weight="700" fill="#007a91">Employment mix</text>',
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#e2e8f0"/>',
    ]
    lx = 180
    for lab, color in zip(labels, colors):
        parts.append(f'<rect x="{lx}" y="4" width="10" height="10" fill="{color}"/>')
        parts.append(f'<text x="{lx + 14}" y="13" font-size="8" fill="#334155">{lab}</text>')
        lx += 70
    for i, stack in enumerate(stacks):
        x = left + i * (plot_w / max(n, 1)) + gap / 2
        y = bottom
        for val, color in zip(stack, colors):
            h = plot_h * (val / mx)
            y -= h
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="{color}"/>'
            )
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{height - 6}" font-size="8" text-anchor="middle" '
            f'fill="#64748b">{_svg_escape(_period_label_short(employment_mix[i]))}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#fff"/>'
        f'{"".join(parts)}</svg>'
    )


def render_cost_per_hour_svg(
    period_comparison: list[dict], *, width: int = 520, height: int = 190
) -> str:
    if not period_comparison:
        return _empty_chart_svg(width, height, "No period data")
    n = len(period_comparison)
    left, right, top, bottom = 44, width - 12, 28, height - 28
    plot_w, plot_h = right - left, bottom - top
    vals = [
        _money(e.get("avg_cost_per_hour")) if e.get("avg_cost_per_hour") is not None else 0.0
        for e in period_comparison
    ]
    mx = max(vals) or 1.0

    def x_at(i: int) -> float:
        return left + plot_w / 2 if n == 1 else left + (plot_w * i / (n - 1))

    def y_at(v: float) -> float:
        return top + plot_h * (1 - (v / mx))

    pts = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(vals))
    parts = [
        f'<text x="{left}" y="14" font-size="11" font-weight="700" fill="#007a91">Payroll cost per hour</text>',
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#e2e8f0"/>',
        f'<polyline fill="none" stroke="#007a91" stroke-width="2" points="{pts}" />',
    ]
    for i, v in enumerate(vals):
        parts.append(
            f'<circle cx="{x_at(i):.1f}" cy="{y_at(v):.1f}" r="2.5" fill="#007a91" />'
        )
        parts.append(
            f'<text x="{x_at(i):.1f}" y="{height - 6}" font-size="8" text-anchor="middle" '
            f'fill="#64748b">{_svg_escape(_period_label_short(period_comparison[i]))}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#fff"/>'
        f'{"".join(parts)}</svg>'
    )


def build_analytics_chart_svgs(analytics: dict) -> dict[str, str]:
    pc = analytics.get("period_comparison") or []
    mix = analytics.get("employment_mix") or []
    return {
        "cost_trajectory": render_cost_trajectory_svg(pc),
        "hours_trajectory": render_hours_stacked_svg(pc),
        "employment_mix": render_employment_mix_svg(mix),
        "cost_per_hour": render_cost_per_hour_svg(pc),
    }
