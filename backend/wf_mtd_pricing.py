"""Shared month-to-date WF tier pricing for Finance DRC and Daily Operations.

Single pricing authority: cumulative tier math with calendar-month MTD position.
Do not invent a second daily-reset algorithm.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

MONEY_Q = Decimal("0.01")
LBS_Q = Decimal("0.01")

# Seed target for VeeWash (org 3) — do not apply to Jul 23–31.
VEEWASH_WF_SCHEDULE_EFFECTIVE_FROM = date(2026, 8, 1)
VEEWASH_WF_SCHEDULE_NAME = "VeeWash WF tiers Aug 2026"


def _d(val: Any) -> Decimal:
    if val is None:
        return Decimal("0")
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("0")


def money(val: Any) -> float:
    return float(_d(val).quantize(MONEY_Q, rounding=ROUND_HALF_UP))


def lbs(val: Any) -> float:
    return float(_d(val).quantize(LBS_Q, rounding=ROUND_HALF_UP))


def cumulative_wf_revenue(total_lbs: Any, tiers: list[dict]) -> Decimal:
    """Revenue for a cumulative MTD pound total through the tier schedule."""
    qty = _d(total_lbs)
    if qty <= 0 or not tiers:
        return Decimal("0")
    sorted_tiers = sorted(tiers, key=lambda t: int(t.get("tier_number") or 0))
    processed = Decimal("0")
    revenue = Decimal("0")
    prev_cap = Decimal("0")
    for tier in sorted_tiers:
        if processed >= qty:
            break
        cap_raw = tier.get("max_lbs")
        rate = _d(tier.get("rate_per_lb"))
        if cap_raw is None:
            lbs_here = qty - processed
        else:
            cap = _d(cap_raw)
            tier_span = cap - prev_cap
            lbs_here = min(qty - processed, tier_span)
            prev_cap = cap
        if lbs_here <= 0:
            continue
        revenue += lbs_here * rate
        processed += lbs_here
    return revenue.quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def allocate_wf_day_revenue_from_mtd(
    mtd_before: Any,
    day_pounds: Any,
    tiers: list[dict] | None,
) -> dict[str, Any]:
    """
    Allocate today's WF weight revenue from MTD position before the day.

    Shared by Finance DRC and Daily Operations. Tiers are applied to the
    cumulative month total; today's revenue is the incremental difference.
    """
    before = _d(mtd_before)
    day = _d(day_pounds)
    if day < 0:
        day = Decimal("0")
    after = before + day
    tier_list = list(tiers or [])

    rev_before = cumulative_wf_revenue(before, tier_list)
    rev_after = cumulative_wf_revenue(after, tier_list)
    day_rev = (rev_after - rev_before).quantize(MONEY_Q, rounding=ROUND_HALF_UP)

    applied: list[dict[str, Any]] = []
    remaining = day
    pos_before = before
    sorted_tiers = sorted(tier_list, key=lambda t: int(t.get("tier_number") or 0))
    prev_cap = Decimal("0")
    tier1_lbs = Decimal("0")
    tier2_lbs = Decimal("0")
    tier1_rev = Decimal("0")
    tier2_rev = Decimal("0")

    for tier in sorted_tiers:
        if remaining <= 0:
            break
        cap_raw = tier.get("max_lbs")
        rate = _d(tier.get("rate_per_lb"))
        tier_number = int(tier.get("tier_number") or 0)
        if cap_raw is None:
            lbs_in_tier = remaining
        else:
            cap = _d(cap_raw)
            if pos_before >= cap:
                prev_cap = cap
                continue
            space = cap - max(pos_before, prev_cap)
            lbs_in_tier = min(remaining, space)
            prev_cap = cap
        if lbs_in_tier <= 0:
            continue
        tier_revenue = (lbs_in_tier * rate).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
        applied.append(
            {
                "tier_number": tier_number,
                "rate_per_lb": money(rate),
                "max_lbs": int(cap_raw) if cap_raw is not None else None,
                "pounds_applied": money(lbs_in_tier),
                "tier_revenue": money(tier_revenue),
            }
        )
        if tier_number <= 1:
            tier1_lbs += lbs_in_tier
            tier1_rev += tier_revenue
        else:
            tier2_lbs += lbs_in_tier
            tier2_rev += tier_revenue
        remaining -= lbs_in_tier
        pos_before += lbs_in_tier

    return {
        "mtd_pounds_before": money(before),
        "day_pounds": money(day),
        "mtd_pounds_after": money(after),
        "tier1_pounds_today": money(tier1_lbs),
        "tier2_pounds_today": money(tier2_lbs),
        "tier1_revenue_today": money(tier1_rev),
        "tier2_revenue_today": money(tier2_rev),
        "weight_revenue_today": money(day_rev),
        "applied_tiers": applied,
        "pricing_complete": bool(tier_list),
    }


__all__ = [
    "MONEY_Q",
    "LBS_Q",
    "VEEWASH_WF_SCHEDULE_EFFECTIVE_FROM",
    "VEEWASH_WF_SCHEDULE_NAME",
    "money",
    "lbs",
    "cumulative_wf_revenue",
    "allocate_wf_day_revenue_from_mtd",
]
