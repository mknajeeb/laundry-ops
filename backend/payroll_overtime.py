"""Overtime split and wage helpers shared by time records ↔ payout batches."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

DEFAULT_OT_THRESHOLD = Decimal("40")
DEFAULT_OT_MULTIPLIER = Decimal("1.5")


def _d(val: Any) -> Decimal:
    try:
        return Decimal(str(val if val is not None else 0))
    except Exception:
        return Decimal("0")


def _q2(val: Decimal) -> Decimal:
    return _d(val).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def split_hours_for_overtime(
    total_hours: Any,
    *,
    threshold: Any = DEFAULT_OT_THRESHOLD,
    enabled: bool = True,
) -> tuple[Decimal, Decimal]:
    """Split period hours into regular and overtime (weekly threshold model)."""
    total = max(Decimal("0"), _d(total_hours))
    if not enabled or total <= 0:
        return _q2(total), Decimal("0.00")
    thr = _d(threshold)
    if thr <= 0:
        thr = DEFAULT_OT_THRESHOLD
    regular = min(total, thr)
    ot = max(Decimal("0"), total - thr)
    return _q2(regular), _q2(ot)


def resolve_overtime_rate(
    regular_rate: Any,
    *,
    multiplier: Any = None,
    explicit_ot_rate: Any = None,
) -> Decimal:
    """OT hourly rate: explicit rate, else regular × multiplier (default 1.5)."""
    reg = _d(regular_rate)
    if explicit_ot_rate is not None and _d(explicit_ot_rate) > 0:
        return _q2(_d(explicit_ot_rate))
    mult = _d(multiplier) if multiplier is not None and _d(multiplier) > 0 else DEFAULT_OT_MULTIPLIER
    if reg <= 0:
        return Decimal("0.00")
    return _q2(reg * mult)


def compute_wage_with_overtime(
    regular_hours: Any,
    ot_hours: Any,
    regular_rate: Any,
    ot_rate: Any = None,
    *,
    sick_pay: Any = 0,
) -> Decimal:
    """Gross wages: regular×rate + OT×ot_rate + sick pay."""
    reg_h = max(Decimal("0"), _d(regular_hours))
    ot_h = max(Decimal("0"), _d(ot_hours))
    rate = _d(regular_rate)
    ot_r = resolve_overtime_rate(rate, explicit_ot_rate=ot_rate) if ot_h > 0 else Decimal("0")
    return _q2(reg_h * rate + ot_h * ot_r + _d(sick_pay))


def resolve_batch_overtime_policy(
    conn,
    organization_id: int,
    worker_category: str,
) -> dict[str, Any]:
    """Resolve OT threshold/multiplier for a batch category (matches Time Records)."""
    threshold = DEFAULT_OT_THRESHOLD
    multiplier = DEFAULT_OT_MULTIPLIER
    # Time Records enables OT whenever a rate exists; calendar may refine threshold/multiplier.
    enabled = True
    try:
        from backend.payroll_funding_forecast import get_calendar_settings

        bundle = get_calendar_settings(conn, int(organization_id))
        cats = bundle.get("categories") or {}
        cat = str(worker_category or "w2")
        cal = cats.get(cat) or cats.get("default") or {}
        org = bundle.get("org_schedule_settings") or {}
        if cal.get("overtime_threshold_hours") is not None:
            threshold = _d(cal["overtime_threshold_hours"])
        elif org.get("overtime_threshold_hours") is not None:
            threshold = _d(org["overtime_threshold_hours"])
        if cal.get("overtime_multiplier") is not None and _d(cal["overtime_multiplier"]) > 0:
            multiplier = _d(cal["overtime_multiplier"])
        # Calendar can disable OT per category; keep W-2 on unless explicitly False.
        if "overtime_enabled" in cal and cal.get("overtime_enabled") is False and cat != "w2":
            enabled = False
    except Exception:
        pass
    if threshold <= 0:
        threshold = DEFAULT_OT_THRESHOLD
    if multiplier <= 0:
        multiplier = DEFAULT_OT_MULTIPLIER
    return {
        "enabled": enabled,
        "threshold_hours": float(threshold),
        "multiplier": float(multiplier),
    }
