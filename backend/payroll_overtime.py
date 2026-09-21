"""Overtime split and wage helpers shared by time records ↔ payout batches."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional  # noqa: F401 — Optional used by week OT helpers

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


def compute_overtime_premium(
    ot_hours: Any,
    regular_rate: Any,
    ot_rate: Any = None,
    *,
    multiplier: Any = None,
) -> Decimal:
    """Additional OT amount above the regular rate (not full OT earnings).

    OT Premium = OT Hours × (OT Rate − Regular Rate)
    For time-and-a-half: OT Hours × Regular Rate × 0.5
    """
    ot_h = max(Decimal("0"), _d(ot_hours))
    if ot_h <= 0:
        return Decimal("0.00")
    rate = _d(regular_rate)
    if rate <= 0:
        return Decimal("0.00")
    ot_r = resolve_overtime_rate(
        rate, multiplier=multiplier, explicit_ot_rate=ot_rate
    )
    premium_rate = max(Decimal("0"), ot_r - rate)
    return _q2(ot_h * premium_rate)


def compute_earnings_breakdown(
    *,
    regular_hours: Any = 0,
    ot_hours: Any = 0,
    regular_rate: Any = 0,
    ot_rate: Any = None,
    multiplier: Any = None,
    gross_pay: Any = None,
    sick_pay: Any = 0,
    bonus_tip_amount: Any = 0,
    reimbursement_amount: Any = 0,
    adjustments: Any = 0,
) -> dict[str, Any]:
    """Display breakdown: base earnings include OT hours at the regular rate.

    Reconciliation (always):
      Regular/Base Earnings + OT Premium + Other Earnings = Gross Pay

    Does not change stored gross — only how components are labeled for display.
    OT Premium is never negative (clamped when OT rate ≤ regular rate).
    Salaried / non-hourly (rate ≤ 0): base and premium are 0; gross stays in other.
    """
    reg_h = max(Decimal("0"), _d(regular_hours))
    ot_h = max(Decimal("0"), _d(ot_hours))
    rate = max(Decimal("0"), _d(regular_rate))
    # Missing / blank OT rate → time-and-a-half when hourly OT hours exist.
    # Explicit non-positive ot_rate is treated as missing (falls back to multiplier).
    explicit = ot_rate
    if explicit is not None and _d(explicit) <= 0:
        explicit = None
    ot_r = (
        resolve_overtime_rate(rate, multiplier=multiplier, explicit_ot_rate=explicit)
        if ot_h > 0 and rate > 0
        else Decimal("0.00")
    )
    # Premium never negative; when OT rate ≤ regular, all OT wages sit in base.
    ot_premium = compute_overtime_premium(
        ot_h, rate, ot_r if ot_r > 0 else None, multiplier=multiplier
    )
    if rate <= 0:
        # Salaried / non-hourly: no hourly base or OT premium breakout.
        base_earnings = Decimal("0.00")
        ot_premium = Decimal("0.00")
    elif ot_r > 0 and ot_r < rate:
        # OT rate below regular — do not inflate base above actual OT wages.
        base_earnings = _q2(reg_h * rate + ot_h * ot_r)
        ot_premium = Decimal("0.00")
    else:
        base_earnings = _q2((reg_h + ot_h) * rate)

    other_from_fields = _q2(
        _d(sick_pay) + _d(bonus_tip_amount) + _d(reimbursement_amount) + _d(adjustments)
    )
    wage_with_ot = _q2(reg_h * rate + ot_h * ot_r) if rate > 0 else Decimal("0.00")
    computed_gross = _q2(wage_with_ot + other_from_fields)
    if gross_pay is not None and str(gross_pay).strip() != "":
        gross = _q2(_d(gross_pay))
    else:
        gross = computed_gross
    # Residual other so base + premium + other always equals displayed gross.
    other_earnings = _q2(gross - base_earnings - ot_premium)
    if other_earnings < 0 and abs(other_earnings) <= Decimal("0.02"):
        # Absorb tiny rounding into base rather than show negative other.
        base_earnings = _q2(base_earnings + other_earnings)
        other_earnings = Decimal("0.00")
    # Final clamp: OT premium display must never be negative.
    if ot_premium < 0:
        ot_premium = Decimal("0.00")
        other_earnings = _q2(gross - base_earnings - ot_premium)
    # Full OT earnings (ot_hours × ot_rate) retained for vendor/invoice math only.
    # Dashboards and payroll reports use base_earnings + ot_premium.
    if rate <= 0:
        regular_earnings = Decimal("0.00")
        ot_earnings = Decimal("0.00")
    else:
        regular_earnings = _q2(reg_h * rate)
        ot_earnings = _q2(ot_h * ot_r) if ot_h > 0 and ot_r > 0 else Decimal("0.00")
    return {
        "regular_hours": float(_q2(reg_h)),
        "ot_hours": float(_q2(ot_h)),
        "regular_rate": float(_q2(rate)),
        "ot_rate": float(_q2(ot_r)),
        "base_earnings": float(base_earnings),
        "ot_premium": float(max(Decimal("0.00"), ot_premium)),
        "regular_earnings": float(regular_earnings),
        "ot_earnings": float(ot_earnings),
        "other_earnings": float(other_earnings),
        "gross_pay": float(gross),
    }


def earnings_breakdown_from_line(line: dict[str, Any], *, multiplier: Any = None) -> dict[str, Any]:
    """Build display earnings breakdown from a payout_batch_lines row."""
    gross = line.get("gross_amount")
    if gross is None or str(gross).strip() == "":
        gross = line.get("total_amount")
    if gross is None or str(gross).strip() == "":
        gross = line.get("gross_wages")
    return compute_earnings_breakdown(
        regular_hours=line.get("approved_hours") or 0,
        ot_hours=line.get("ot_hours") or 0,
        regular_rate=line.get("rate") or 0,
        ot_rate=line.get("ot_rate"),
        multiplier=multiplier,
        gross_pay=gross,
        sick_pay=line.get("sick_pay_amount") or 0,
        bonus_tip_amount=line.get("bonus_tip_amount") or 0,
        reimbursement_amount=line.get("reimbursement_amount") or 0,
        adjustments=line.get("adjustments") or 0,
    )


def compute_contractor_invoice_earnings(
    line: dict[str, Any],
    *,
    multiplier: Any = None,
) -> dict[str, Any]:
    """Contractor receipt earnings: full OT earnings (not premium-only).

    Regular earnings = regular hours × regular rate
    Overtime earnings = OT hours × OT rate (full rate, not premium)
    Other earnings = residual so components always sum to stored gross/total.

    Does not change stored amounts — presentation only.
    """
    reg_h = max(Decimal("0"), _d(line.get("approved_hours") or 0))
    ot_h = max(Decimal("0"), _d(line.get("ot_hours") or 0))
    rate = max(Decimal("0"), _d(line.get("rate") or 0))
    explicit = line.get("ot_rate")
    if explicit is not None and _d(explicit) <= 0:
        explicit = None
    ot_r = (
        resolve_overtime_rate(rate, multiplier=multiplier, explicit_ot_rate=explicit)
        if ot_h > 0 and rate > 0
        else Decimal("0.00")
    )
    regular_earnings = _q2(reg_h * rate) if rate > 0 else Decimal("0.00")
    overtime_earnings = _q2(ot_h * ot_r) if ot_h > 0 and ot_r > 0 else Decimal("0.00")
    other_from_fields = _q2(
        _d(line.get("sick_pay_amount") or 0)
        + _d(line.get("bonus_tip_amount") or 0)
        + _d(line.get("reimbursement_amount") or 0)
        + _d(line.get("adjustments") or 0)
        + _d(line.get("health_credit_amount") or 0)
    )
    gross_raw = line.get("gross_amount")
    if gross_raw is None or str(gross_raw).strip() == "":
        gross_raw = line.get("total_amount")
    if gross_raw is None or str(gross_raw).strip() == "":
        gross = _q2(regular_earnings + overtime_earnings + other_from_fields)
    else:
        gross = _q2(_d(gross_raw))
    other_earnings = _q2(gross - regular_earnings - overtime_earnings)
    if other_earnings < 0 and abs(other_earnings) <= Decimal("0.02"):
        # Prefer adjusting overtime residual into regular for tiny rounding.
        if overtime_earnings > 0:
            overtime_earnings = _q2(overtime_earnings + other_earnings)
        else:
            regular_earnings = _q2(regular_earnings + other_earnings)
        other_earnings = Decimal("0.00")
    return {
        "regular_hours": float(_q2(reg_h)),
        "ot_hours": float(_q2(ot_h)),
        "regular_rate": float(_q2(rate)),
        "ot_rate": float(_q2(ot_r)),
        "regular_earnings": float(regular_earnings),
        "overtime_earnings": float(overtime_earnings),
        "other_earnings": float(other_earnings),
        "gross_pay": float(gross),
    }


def batch_allows_contractor_overtime_autosplit(batch: Optional[dict[str, Any]]) -> bool:
    """Auto-split only for new/unfinalized unpaid contractor batches (never rewrite paid history)."""
    if not batch:
        return False
    if batch.get("payout_details_finalized_at"):
        return False
    status = str(batch.get("status") or "").strip().lower()
    if status in ("paid", "partially_paid", "closed"):
        return False
    return str(batch.get("worker_category") or "").strip() in ("temp", "contractor_1099", "tryout")


def resolve_batch_overtime_policy(
    conn,
    organization_id: int,
    worker_category: str,
) -> dict[str, Any]:
    """Resolve OT threshold/multiplier for a batch category (matches Time Records).

    Time Records applies the same OT rules for W-2, 1099, and temp whenever a rate
    exists. Batch gross must do the same — do not honor calendar overtime_enabled=False
    for contractors/temps (that flag is forecast-only and defaults off for non-W2).
    """
    threshold = DEFAULT_OT_THRESHOLD
    multiplier = DEFAULT_OT_MULTIPLIER
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
        "worker_category": str(worker_category or ""),
    }


def _session_sort_key(rec: dict) -> tuple:
    raw = rec.get("clock_in_at") or rec.get("sort_key") or rec.get("work_date") or ""
    if hasattr(raw, "isoformat"):
        raw = raw.isoformat()
    try:
        sid = int(rec.get("id") or 0)
    except (TypeError, ValueError):
        sid = 0
    return (str(raw), sid)


def weekly_ot_policy_category(records: list[dict]) -> str:
    """Profile category used for the weekly OT threshold.

    Overrides change which batch owns the hours. They must not change the
    threshold, and the threshold must not be recomputed inside each batch.
    """
    for rec in sorted(records or [], key=_session_sort_key):
        profile = rec.get("profile_worker_category")
        if profile:
            return str(profile)
    return "w2"


def allocate_session_overtime(
    sessions: list[dict],
    *,
    threshold: Any = DEFAULT_OT_THRESHOLD,
    enabled: bool = True,
) -> dict[int, tuple[Decimal, Decimal]]:
    """Walk eligible sessions in clock order and mark hours past the weekly threshold.

    Returns session id -> (regular_hours, ot_hours). Hours stay on the session
    that worked them. Callers filter by classification after this split.

    When ``enabled`` is False (employee-week disable_ot), all hours stay regular.
    Do not invent a second OT calculator — callers feed week overrides here.
    """
    ordered = sorted(sessions or [], key=_session_sort_key)
    running = Decimal("0")
    thr = _d(threshold)
    if thr <= 0:
        thr = DEFAULT_OT_THRESHOLD
    out: dict[int, tuple[Decimal, Decimal]] = {}
    for rec in ordered:
        sid = int(rec["id"])
        raw_hours = rec.get("hours")
        if raw_hours is None:
            raw_hours = rec.get("approved_hours")
        hours = max(Decimal("0"), _d(raw_hours))
        if not enabled:
            out[sid] = (_q2(hours), Decimal("0.00"))
            continue
        start = running
        end = running + hours
        if end <= thr:
            regular, ot = hours, Decimal("0")
        elif start >= thr:
            regular, ot = Decimal("0"), hours
        else:
            regular = thr - start
            ot = hours - regular
        running = end
        out[sid] = (_q2(regular), _q2(ot))
    return out


def allocate_session_overtime_by_week(
    sessions: list[dict],
    *,
    threshold: Any = DEFAULT_OT_THRESHOLD,
    week_ot_enabled: Optional[dict[str, bool]] = None,
    default_enabled: bool = True,
) -> dict[int, tuple[Decimal, Decimal]]:
    """Allocate OT per payroll week using the existing chronological calculator.

    ``week_ot_enabled`` maps payroll_week_start ISO date -> enabled flag.
    Sessions without a week key use ``default_enabled``.
    """
    by_week: dict[str, list[dict]] = {}
    for rec in sessions or []:
        ws = rec.get("payroll_week_start") or ""
        if hasattr(ws, "isoformat"):
            ws = ws.isoformat()
        ws = str(ws)[:10] if ws else "_default"
        by_week.setdefault(ws, []).append(rec)
    out: dict[int, tuple[Decimal, Decimal]] = {}
    flags = week_ot_enabled or {}
    for ws, recs in by_week.items():
        enabled = flags.get(ws, default_enabled) if ws != "_default" else default_enabled
        out.update(
            allocate_session_overtime(recs, threshold=threshold, enabled=bool(enabled))
        )
    return out


def _session_resolved_rate(rec: dict) -> Decimal:
    if rec.get("resolved_hourly_rate") is not None and str(rec.get("resolved_hourly_rate")).strip() != "":
        return _q2(rec.get("resolved_hourly_rate"))
    if rec.get("hourly_rate") is not None:
        return _q2(rec.get("hourly_rate"))
    return Decimal("0.00")


def aggregate_classified_batch_lines(
    records: list[dict],
    *,
    batch_category: str,
    threshold_hours: Any = DEFAULT_OT_THRESHOLD,
    ot_enabled: bool = True,
    week_ot_enabled: Optional[dict[str, bool]] = None,
) -> list[dict]:
    """Payout-line payload(s) per user for sessions in ``batch_category``.

    Overtime is allocated across every session in ``records`` first (optionally
    per payroll week when ``week_ot_enabled`` is provided), including other
    classifications, then only this category's regular/OT hours are kept.

    Sessions with different resolved rates become separate lines so each session
    rate is frozen — never blended.
    """
    by_user: dict[int, list[dict]] = {}
    for rec in records or []:
        by_user.setdefault(int(rec["user_id"]), []).append(rec)
    lines = []
    for uid, recs in by_user.items():
        if week_ot_enabled is not None:
            alloc = allocate_session_overtime_by_week(
                recs,
                threshold=threshold_hours,
                week_ot_enabled=week_ot_enabled,
                default_enabled=ot_enabled,
            )
        else:
            alloc = allocate_session_overtime(
                recs, threshold=threshold_hours, enabled=ot_enabled
            )
        matched = [
            r for r in sorted(recs, key=_session_sort_key) if r.get("worker_category") == batch_category
        ]
        if not matched:
            continue
        by_rate: dict[str, list[dict]] = {}
        for rec in matched:
            rate = _session_resolved_rate(rec)
            by_rate.setdefault(f"{rate:.2f}", []).append(rec)
        for rate_key, rate_recs in by_rate.items():
            regular = Decimal("0")
            ot = Decimal("0")
            provenance = []
            session_ids = []
            rate = _q2(rate_key)
            ot_week_modes = set()
            for rec in rate_recs:
                sid = int(rec["id"])
                reg_h, ot_h = alloc.get(sid, (Decimal("0.00"), Decimal("0.00")))
                regular += reg_h
                ot += ot_h
                session_ids.append(sid)
                mode = rec.get("ot_week_mode") or "default"
                ot_week_modes.add(str(mode))
                provenance.append(
                    {
                        "shift_session_id": sid,
                        "worker_category": rec.get("worker_category"),
                        "classification_source": rec.get("classification_source") or "profile",
                        "resolved_rate": float(rate),
                        "rate_source": rec.get("rate_source") or "profile",
                        "profile_rate": (
                            float(_q2(rec["profile_hourly_rate"]))
                            if rec.get("profile_hourly_rate") is not None
                            else None
                        ),
                        "payroll_rate_override": (
                            float(_q2(rec["payroll_rate_override"]))
                            if rec.get("payroll_rate_override") is not None
                            else None
                        ),
                        "ot_week_mode": mode,
                        "payroll_week_start": rec.get("payroll_week_start"),
                    }
                )
            # Prefer disable_ot snapshot when any contributing session had it.
            ot_snap = "disable_ot" if "disable_ot" in ot_week_modes else "default"
            lines.append(
                {
                    "user_id": uid,
                    "worker_name": rate_recs[0].get("worker_name") or "",
                    "approved_hours": float(_q2(regular)),
                    "ot_hours": float(_q2(ot)),
                    "rate": float(rate),
                    "session_ids": session_ids,
                    "classification_provenance": provenance,
                    "ot_week_override_snapshot": ot_snap,
                }
            )
    return lines
