"""Hourly employer-cost reporting.

Reads stored payroll totals and time-record hours. Does not change wages,
overtime rules, tax calculations, approvals, or payment amounts.

Total employer cost on a processed line is gross earnings plus the stored
employer-tax snapshot (Social Security, Medicare, FUTA, NY SUTA, NY
re-employment fund, and other/MCTMT). Employee withholding is not included.
Workers' compensation is included only when it was already stored in that
snapshot — the tax engine's separate workers-comp estimate is not added again.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

DEFAULT_LABOR_COST_TARGET = 19.0
HISTORY_PERIODS = 4
DEFAULT_OT_THRESHOLD = 40.0
DEFAULT_OT_MULTIPLIER = 1.5

# Stored payout_details employer_taxes keys. "other" is MCTMT (quarterly,
# company-level). It does not move with one employee's overtime premium.
_PROPORTIONAL_KEYS = frozenset({"er_medicare", "employer_medicare"})
_CAPPED_KEYS = {
    "er_ss": "employer_social_security_rate",
    "employer_social_security": "employer_social_security_rate",
    "futa": "futa_rate",
    "suta": "ny_suta_rate",
    "ny_reemploy": "ny_reemployment_service_fund_rate",
}
_FIXED_KEYS = frozenset({"other", "mctmt"})

_EXPENSE_LABELS = {
    "er_ss": "Employer Social Security",
    "employer_social_security": "Employer Social Security",
    "er_medicare": "Employer Medicare",
    "employer_medicare": "Employer Medicare",
    "futa": "FUTA",
    "suta": "NY SUTA",
    "ny_reemploy": "NY re-employment fund",
    "other": "Other employer tax (MCTMT)",
    "mctmt": "MCTMT",
}


def _q2_dec(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _money(val: Any) -> float:
    try:
        if val is None or val == "":
            return 0.0
        return float(_q2_dec(Decimal(str(val))))
    except Exception:
        return 0.0


def _rate_num(val: Any) -> Optional[float]:
    try:
        if val is None or val == "":
            return None
        num = float(val)
    except (TypeError, ValueError):
        return None
    if num <= 0:
        return None
    return num


def labor_cost_target_from_settings(settings: Optional[dict]) -> float:
    """Management comparison target. Never used as a wage or tax rate."""
    if not isinstance(settings, dict):
        return DEFAULT_LABOR_COST_TARGET
    raw = _rate_num(settings.get("labor_cost_target_per_hour"))
    return raw if raw is not None else DEFAULT_LABOR_COST_TARGET


def employer_burden_percent(gross_pay: Any, total_employer_cost: Any) -> Optional[float]:
    """(Total employer cost − gross) ÷ gross × 100.

    Returns None when gross is zero so the caller does not invent a percentage.
    """
    gross = _money(gross_pay)
    total = _money(total_employer_cost)
    if gross <= 0.005:
        return None
    return round((total - gross) / gross * 100.0, 2)


def payable_hours_from_net_seconds(net_work_seconds: Any) -> float:
    """Payable hours from net work seconds. Unpaid breaks are already excluded."""
    try:
        seconds = int(net_work_seconds or 0)
    except (TypeError, ValueError):
        seconds = 0
    if seconds < 0:
        seconds = 0
    return round(seconds / 3600.0, 2)


def _distinct_rates(rates: Optional[list]) -> list[float]:
    found: list[float] = []
    for raw in rates or []:
        rate = _rate_num(raw)
        if rate is None:
            continue
        rounded = round(rate, 2)
        if all(abs(rounded - prev) > 0.009 for prev in found):
            found.append(rounded)
    return found


def _settings_rate(settings: Optional[dict], key: str) -> Optional[float]:
    if not isinstance(settings, dict):
        return None
    return _rate_num(settings.get(key))


def _scale_capped_component(
    amount: float,
    gross: float,
    straight_gross: float,
    statutory_rate: Optional[float],
) -> tuple[float, str]:
    """Remove the overtime premium from a wage-base tax.

    Wages in the period are treated as straight-time first and the overtime
    premium as the marginal dollars. A tax that already stopped at a wage
    base does not shrink when those marginal dollars are removed.
    """
    if amount <= 0.005 or gross <= 0.005:
        return 0.0, "zero"
    if straight_gross >= gross - 0.005:
        return _money(amount), "unchanged"
    if statutory_rate is None:
        return _money(amount * straight_gross / gross), "rate_unconfigured_proportional"
    full_period_tax = gross * statutory_rate
    if amount + 0.02 >= full_period_tax:
        return _money(straight_gross * statutory_rate), "under_wage_base"
    implied_taxable = amount / statutory_rate
    taxed = min(straight_gross, implied_taxable)
    return _money(taxed * statutory_rate), "wage_base_cap"


def employer_taxes_without_ot_premium(
    *,
    gross_pay: float,
    straight_time_gross: float,
    employer_taxes: float,
    components: Optional[dict],
    tax_settings: Optional[dict],
) -> dict[str, Any]:
    """Employer taxes on a no-overtime-premium gross, using the stored snapshot.

    Proportional taxes (Medicare) scale with the lower gross. Wage-base taxes
    (Social Security, FUTA, SUTA, re-employment) scale only for wages still
    under the cap. MCTMT / other stays at the stored amount.
    """
    gross = _money(gross_pay)
    straight = _money(straight_time_gross)
    actual = _money(employer_taxes)
    if gross <= 0.005:
        return {
            "employer_taxes": 0.0,
            "method": "no_gross",
            "component_notes": {},
        }
    if straight >= gross - 0.005:
        return {
            "employer_taxes": actual,
            "method": "identical_no_overtime",
            "component_notes": {},
        }
    if straight < 0:
        straight = 0.0

    raw = components if isinstance(components, dict) else None
    if not raw:
        scaled = _money(actual * straight / gross) if gross else 0.0
        return {
            "employer_taxes": scaled,
            "method": "proportional_burden",
            "component_notes": {"total": "proportional_burden"},
        }

    scaled_total = 0.0
    notes: dict[str, str] = {}
    consumed = 0.0
    saw_fixed = False
    saw_cap = False
    for key, raw_amount in raw.items():
        amount = _money(raw_amount)
        consumed = _money(consumed + amount)
        name = str(key)
        if name in _FIXED_KEYS:
            scaled = amount
            note = "held_constant"
            saw_fixed = True
        elif name in _PROPORTIONAL_KEYS:
            scaled = _money(amount * straight / gross) if gross else 0.0
            note = "proportional"
        elif name in _CAPPED_KEYS:
            scaled, note = _scale_capped_component(
                amount,
                gross,
                straight,
                _settings_rate(tax_settings, _CAPPED_KEYS[name]),
            )
            if note == "wage_base_cap":
                saw_cap = True
        else:
            scaled = _money(amount * straight / gross) if gross else 0.0
            note = "unclassified_proportional"
        notes[name] = note
        scaled_total = _money(scaled_total + scaled)

    residual = _money(actual - consumed)
    if abs(residual) >= 0.01:
        extra = _money(residual * straight / gross) if gross else 0.0
        scaled_total = _money(scaled_total + extra)
        notes["unclassified_residual"] = "proportional"
    method = "stored_components"
    if saw_cap or saw_fixed:
        method = "stored_components"
    elif all(v in ("proportional", "under_wage_base", "zero") for v in notes.values()):
        method = "stored_components"
    return {
        "employer_taxes": scaled_total,
        "method": method,
        "component_notes": notes,
    }


def weighted_burden_from_periods(
    periods: list[dict],
    *,
    limit: int = HISTORY_PERIODS,
) -> dict[str, Any]:
    """Gross-weighted employer burden from the newest finalized periods.

    Weighting is sum(employer cost − gross) ÷ sum(gross), which is the
    gross-weighted average of the period percentages. Periods with no
    recorded employer-tax snapshot are skipped.
    """
    chosen: list[dict] = []
    for period in periods or []:
        if not period.get("employer_cost_recorded", True):
            continue
        gross = _money(period.get("gross_pay"))
        total = _money(period.get("total_payroll_cost"))
        if gross <= 0.005:
            continue
        pct = employer_burden_percent(gross, total)
        chosen.append(
            {
                "pay_period_start": str(period.get("pay_period_start") or "")[:10],
                "pay_period_end": str(period.get("pay_period_end") or "")[:10],
                "gross_pay": gross,
                "total_payroll_cost": total,
                "employer_expenses": _money(total - gross),
                "burden_percent": pct,
            }
        )
        if len(chosen) >= max(1, int(limit)):
            break
    if not chosen:
        return {
            "burden_percent": None,
            "burden_status": "unavailable",
            "burden_label": "Unavailable",
            "sources": [],
            "period_count": 0,
        }
    gross_sum = sum(item["gross_pay"] for item in chosen)
    extra_sum = sum(item["employer_expenses"] for item in chosen)
    pct = round(extra_sum / gross_sum * 100.0, 2) if gross_sum > 0.005 else None
    return {
        "burden_percent": pct,
        "burden_status": "estimated",
        "burden_label": "Estimated",
        "sources": chosen,
        "period_count": len(chosen),
    }


def _base_wage(payable_hours: float, base_earnings: float, rates: list[float]) -> tuple[Optional[float], bool]:
    distinct = _distinct_rates(rates)
    if payable_hours <= 0.005:
        if len(distinct) == 1:
            return distinct[0], False
        return None, False
    if len(distinct) == 1:
        expected = round(payable_hours * distinct[0], 2)
        if abs(expected - _money(base_earnings)) <= 0.05 or _money(base_earnings) <= 0.005:
            return distinct[0], False
    if _money(base_earnings) > 0.005:
        return round(_money(base_earnings) / payable_hours, 2), len(distinct) != 1
    if len(distinct) == 1:
        return distinct[0], False
    return None, len(distinct) > 1


def _target_comparison(effective: Optional[float], target: float) -> dict[str, Any]:
    if effective is None:
        return {
            "labor_cost_target": target,
            "target_delta_per_hour": None,
            "target_status": "unavailable",
        }
    delta = round(effective - target, 2)
    status = "above" if delta > 0.005 else "at_or_below"
    return {
        "labor_cost_target": target,
        "target_delta_per_hour": delta,
        "target_status": status,
    }


def _expense_labels(components: Optional[dict]) -> list[str]:
    labels = []
    for key, amount in (components or {}).items():
        if abs(_money(amount)) < 0.005:
            continue
        labels.append(_EXPENSE_LABELS.get(str(key), str(key).replace("_", " ")))
    return labels


def analyze_employee_hourly_cost(
    *,
    worker_category: str,
    payable_hours: Any,
    regular_hours: Any = 0,
    ot_hours: Any = 0,
    base_earnings: Any = 0,
    ot_premium: Any = 0,
    other_earnings: Any = 0,
    gross_pay: Any = 0,
    total_payroll_cost: Any = None,
    employer_taxes: Any = None,
    employer_tax_components: Optional[dict] = None,
    employer_cost_recorded: bool = False,
    regular_rates: Optional[list] = None,
    scenario: str = "processed",
    burden_percent: Optional[float] = None,
    burden_sources: Optional[list] = None,
    tax_settings: Optional[dict] = None,
    labor_cost_target: Optional[float] = None,
    rate_note: Optional[str] = None,
) -> dict[str, Any]:
    """Four hourly employer-cost metrics for one employee and one period.

    scenario:
      processed — stored gross and total cost (finalized payroll)
      estimated — historical burden applied to time-record earnings
      contractor — no W-2 burden; stored extras only, otherwise cost equals gross
    """
    cat = str(worker_category or "").strip() or "unknown"
    hours = _money(payable_hours)
    premium = max(0.0, _money(ot_premium))
    gross = _money(gross_pay)
    base = _money(base_earnings)
    other = _money(other_earnings)
    reg_h = _money(regular_hours)
    ot_h = _money(ot_hours)
    target = (
        labor_cost_target
        if labor_cost_target is not None and labor_cost_target > 0
        else labor_cost_target_from_settings(tax_settings)
    )
    straight = _money(gross - premium)
    if straight < 0:
        straight = 0.0
    wage, blended = _base_wage(hours, base, regular_rates or [])
    notes: list[str] = []
    if rate_note:
        notes.append(rate_note)
    if other > 0.005:
        notes.append(
            "Other earnings stay in both comparisons. Only the overtime premium is removed."
        )

    components = dict(employer_tax_components or {})
    recorded_taxes = _money(employer_taxes) if employer_taxes is not None else None
    stored_total = _money(total_payroll_cost) if total_payroll_cost is not None else None

    burden_status = "unavailable"
    burden_label = "Unavailable"
    burden_pct: Optional[float] = None
    sources = list(burden_sources or [])
    method = "unavailable"
    total_cost: Optional[float] = None
    no_ot_cost: Optional[float] = None
    employer_extra: Optional[float] = None
    suspect_difference = False

    is_w2 = cat == "w2"
    use_contractor = (not is_w2) or scenario == "contractor"

    if use_contractor:
        if stored_total is None:
            stored_total = gross
        extra = _money(stored_total - gross)
        employer_extra = extra
        total_cost = stored_total
        if extra > 0.005 and (employer_cost_recorded or recorded_taxes):
            burden_pct = employer_burden_percent(gross, stored_total)
            burden_status = "actual"
            burden_label = "Actual"
            tax_result = employer_taxes_without_ot_premium(
                gross_pay=gross,
                straight_time_gross=straight,
                employer_taxes=extra,
                components=components or None,
                tax_settings=tax_settings,
            )
            no_ot_cost = _money(straight + tax_result["employer_taxes"])
            method = "contractor_recorded_expenses"
        else:
            burden_status = "not_applicable"
            burden_label = "N/A"
            no_ot_cost = straight
            method = "contractor_gross"
            notes.append(
                "1099/temp cost uses stored contractor amounts. W-2 payroll taxes are not applied."
            )
        if premium <= 0.005 and total_cost is not None:
            no_ot_cost = total_cost
            method = "identical_no_overtime"
    elif scenario == "estimated":
        if burden_percent is None:
            burden_status = "unavailable"
            burden_label = "Unavailable"
            method = "unavailable"
            notes.append(
                "No finalized employer-cost history for this employee. No burden percentage was substituted."
            )
        else:
            burden_pct = round(float(burden_percent), 2)
            burden_status = "estimated"
            burden_label = "Estimated"
            factor = 1.0 + (burden_pct / 100.0)
            total_cost = _money(gross * factor)
            employer_extra = _money(total_cost - gross)
            no_ot_cost = _money(straight * factor)
            method = "historical_burden"
            if premium <= 0.005:
                no_ot_cost = total_cost
                method = "identical_no_overtime"
            notes.append(
                "Estimated from this employee's finalized payrolls. Not a finalized payroll expense."
            )
    else:
        # Processed W-2. Stored total cost is the source of truth.
        if stored_total is None:
            notes.append("Processed payroll total cost is missing.")
        else:
            total_cost = stored_total
            extra = _money(stored_total - gross)
            employer_extra = extra
            if recorded_taxes is not None and abs(extra - recorded_taxes) > 0.05:
                suspect_difference = True
                notes.append(
                    "Total cost minus gross does not match stored employer taxes, so no burden percentage is applied."
                )
            elif not employer_cost_recorded and abs(extra) <= 0.005:
                notes.append(
                    "This finalized payroll has no employer-tax snapshot, so employer burden is unavailable."
                )
            elif gross <= 0.005:
                notes.append("Gross earnings are zero, so employer burden is unavailable.")
            else:
                burden_pct = employer_burden_percent(gross, stored_total)
                burden_status = "actual"
                burden_label = "Actual"
                if premium <= 0.005:
                    no_ot_cost = total_cost
                    method = "identical_no_overtime"
                else:
                    tax_result = employer_taxes_without_ot_premium(
                        gross_pay=gross,
                        straight_time_gross=straight,
                        employer_taxes=extra,
                        components=components or None,
                        tax_settings=tax_settings,
                    )
                    no_ot_cost = _money(straight + tax_result["employer_taxes"])
                    method = tax_result["method"]
                    fixed_amount = sum(
                        _money((components or {}).get(key)) for key in _FIXED_KEYS
                    )
                    if method == "stored_components" and fixed_amount > 0.005:
                        notes.append(
                            "MCTMT or other threshold tax is held at the stored amount in the no-premium comparison."
                        )

    base_cost_hr = None
    effective_hr = None
    impact_hr = None
    impact_pct = None
    if hours <= 0.005:
        notes.append("Payable hours are zero, so hourly rates are not calculated.")
    else:
        if total_cost is not None and not suspect_difference:
            effective_hr = round(total_cost / hours, 2)
        elif total_cost is not None and suspect_difference:
            effective_hr = round(total_cost / hours, 2)
        if no_ot_cost is not None and not suspect_difference and burden_status != "unavailable":
            base_cost_hr = round(no_ot_cost / hours, 2)
        if effective_hr is not None and base_cost_hr is not None:
            impact_hr = round(effective_hr - base_cost_hr, 2)
            if premium <= 0.005:
                impact_hr = 0.0
                base_cost_hr = effective_hr
                no_ot_cost = total_cost
            if base_cost_hr and abs(base_cost_hr) > 0.005:
                impact_pct = round(impact_hr / base_cost_hr * 100.0, 2)
            elif impact_hr == 0:
                impact_pct = 0.0

    if method == "historical_burden":
        formula = (
            "Estimated total employer cost = gross earnings × (1 + historical burden). "
            "Base cost prices every payable hour at the regular rate, then applies the same burden. "
            "Effective cost/hr = estimated total employer cost ÷ payable hours."
        )
    elif method == "stored_components":
        formula = (
            "Effective cost/hr = stored total employer cost ÷ payable hours. "
            "Base cost removes only the overtime premium and reapplies stored employer taxes, "
            "keeping wage-base caps and holding MCTMT at the stored amount."
        )
    elif method == "proportional_burden":
        formula = (
            "Effective cost/hr = stored total employer cost ÷ payable hours. "
            "Base cost = straight-time gross × (1 + actual burden) ÷ payable hours. "
            "The payroll line did not include separate employer-tax components."
        )
    elif method in ("contractor_gross", "contractor_recorded_expenses"):
        formula = (
            "Effective cost/hr = stored contractor cost ÷ payable hours. "
            "W-2 employer payroll taxes are not added."
        )
    elif method == "identical_no_overtime":
        formula = (
            "No overtime premium. Effective cost/hr and base cost/hr both use the same employer cost ÷ payable hours."
        )
    else:
        formula = "Employer hourly cost is unavailable because no reliable employer-cost figure is on file."

    included = _expense_labels(components)
    if not included and employer_extra and employer_extra > 0.005 and burden_status == "actual":
        included = ["Stored employer payroll taxes"]

    target_bits = _target_comparison(effective_hr if burden_status != "unavailable" or effective_hr is not None else effective_hr, target)
    # Target compares the effective employer cost whenever we have one, including
    # a processed total that lacked a tax snapshot. Hide it only when there is
    # no hourly employer figure at all.
    if effective_hr is None:
        target_bits = _target_comparison(None, target)

    cost_basis = {
        "processed": "processed_payroll",
        "estimated": "estimated_time_records",
        "contractor": "contractor_cost",
    }.get(scenario, "processed_payroll")
    if use_contractor:
        cost_basis = "contractor_cost"
    if burden_status == "unavailable" and scenario == "estimated":
        cost_basis = "unavailable"

    return {
        "worker_category": cat,
        "cost_basis": cost_basis,
        "burden_status": burden_status,
        "burden_label": burden_label,
        "burden_percent": burden_pct,
        "burden_sources": sources,
        "base_wage": wage,
        "base_wage_blended": blended,
        "payable_hours": hours,
        "regular_hours": reg_h,
        "ot_hours": ot_h,
        "base_earnings": base,
        "ot_premium": premium,
        "other_earnings": other,
        "gross_pay": gross,
        "employer_expenses": employer_extra,
        "total_employer_cost": total_cost,
        "straight_time_gross": straight,
        "straight_time_employer_cost": no_ot_cost,
        "base_cost_per_hour": base_cost_hr,
        "effective_cost_per_hour": effective_hr,
        "ot_impact_per_hour": impact_hr,
        "ot_impact_percent": impact_pct,
        "method": method,
        "formula": formula,
        "included_expenses": included,
        "employer_cost_recorded": bool(employer_cost_recorded),
        "finalized": scenario == "processed" and not use_contractor,
        "notes": notes,
        "limitations": [
            "Employee withholding is excluded from total employer cost.",
            "Workers' compensation is included only when it was already stored on the payroll line.",
        ],
        **target_bits,
    }


def aggregate_report_rows(rows: list[dict]) -> dict[str, Any]:
    """Sum stored payroll lines for one employee. Does not recompute taxes."""
    components: dict[str, float] = {}
    rates: list[float] = []
    gross = total = premium = base = other = reg_h = ot_h = taxes = 0.0
    recorded = False
    category = "unknown"
    for row in rows or []:
        category = str(row.get("worker_category") or category)
        gross = _money(gross + _money(row.get("gross_pay")))
        total = _money(total + _money(row.get("total_payroll_cost")))
        premium = _money(premium + _money(row.get("ot_premium")))
        base = _money(base + _money(row.get("base_earnings")))
        other = _money(other + _money(row.get("other_earnings")))
        reg_h = _money(reg_h + _money(row.get("regular_hours")))
        ot_h = _money(ot_h + _money(row.get("ot_hours")))
        taxes = _money(taxes + _money(row.get("employer_taxes")))
        rate = _rate_num(row.get("regular_rate"))
        if rate is not None:
            rates.append(rate)
        if row.get("employer_cost_recorded"):
            recorded = True
        for key, amount in (row.get("employer_tax_components") or {}).items():
            components[str(key)] = _money(components.get(str(key), 0.0) + _money(amount))
    return {
        "worker_category": category,
        "payable_hours": _money(reg_h + ot_h),
        "regular_hours": reg_h,
        "ot_hours": ot_h,
        "base_earnings": base,
        "ot_premium": premium,
        "other_earnings": other,
        "gross_pay": gross,
        "total_payroll_cost": total,
        "employer_taxes": taxes,
        "employer_tax_components": components,
        "employer_cost_recorded": recorded,
        "regular_rates": rates,
    }


def hourly_cost_from_report_rows(
    rows: list[dict],
    *,
    tax_settings: Optional[dict] = None,
    labor_cost_target: Optional[float] = None,
) -> dict[str, Any]:
    """Dashboard analysis. Uses stored payroll totals and does not recompute them."""
    from backend.payroll_report_analytics import batch_is_complete

    agg = aggregate_report_rows(rows)
    scenario = "processed" if agg["worker_category"] == "w2" else "contractor"
    analysis = analyze_employee_hourly_cost(
        **agg,
        scenario=scenario,
        tax_settings=tax_settings,
        labor_cost_target=labor_cost_target,
    )
    finalized = bool(rows) and all(
        batch_is_complete(
            {
                "batch_status": row.get("batch_status"),
                "status": row.get("batch_status"),
                "payout_details_finalized_at": row.get("details_finalized_at"),
            }
        )
        for row in rows
    )
    analysis["finalized"] = finalized
    if analysis.get("worker_category") == "w2" and not finalized and analysis.get("burden_status") == "actual":
        analysis["burden_status"] = "estimated"
        analysis["burden_label"] = "Estimated"
        analysis["cost_basis"] = "payroll_line_unfinalized"
        analysis["notes"] = list(analysis.get("notes") or []) + [
            "Uses amounts stored on the payroll line. This payroll is not finalized."
        ]
    return analysis


def economics_from_time_records(
    records: list[dict],
    *,
    ot_threshold: Any = DEFAULT_OT_THRESHOLD,
    ot_multiplier: Any = DEFAULT_OT_MULTIPLIER,
) -> dict[str, Any]:
    """Same payable-hour and premium walk as Time Records period summary.

    Payable hours are the record's approved hours (net of unpaid breaks).
    Each record keeps its own regular rate so a mid-period rate change is weighted
    by the hours worked at that rate. Overtime starts after the threshold,
    in clock-in order.
    """
    threshold = _rate_num(ot_threshold) or DEFAULT_OT_THRESHOLD
    multiplier = _rate_num(ot_multiplier) or DEFAULT_OT_MULTIPLIER
    ordered = sorted(
        records or [],
        key=lambda row: (str(row.get("clock_in_at") or ""), str(row.get("id") or "")),
    )
    cumulative = Decimal("0")
    base = Decimal("0")
    premium = Decimal("0")
    reg_h = Decimal("0")
    ot_h = Decimal("0")
    rates: list[float] = []
    category = ""
    threshold_d = Decimal(str(threshold))
    multiplier_d = Decimal(str(multiplier))
    for row in ordered:
        hrs = Decimal(str(max(0.0, _money(row.get("approved_hours")))))
        rate = Decimal(str(_rate_num(row.get("hourly_rate")) or 0))
        if not category:
            category = str(row.get("worker_category") or "")
        room = max(Decimal("0"), threshold_d - cumulative)
        if rate > 0:
            regular = min(hrs, room)
            overtime = max(Decimal("0"), hrs - regular)
            base += hrs * rate
            premium += overtime * max(Decimal("0"), rate * multiplier_d - rate)
            rates.append(float(rate))
        else:
            regular = hrs
            overtime = Decimal("0")
        cumulative += hrs
        reg_h += regular
        ot_h += overtime
    base_r = float(_q2_dec(base))
    premium_r = float(_q2_dec(premium))
    return {
        "worker_category": category or "w2",
        "payable_hours": float(_q2_dec(cumulative)),
        "regular_hours": float(_q2_dec(reg_h)),
        "ot_hours": float(_q2_dec(ot_h)),
        "base_earnings": base_r,
        "ot_premium": premium_r,
        "other_earnings": 0.0,
        "gross_pay": _money(base_r + premium_r),
        "regular_rates": rates,
    }


def apply_historical_rates(
    records: list[dict],
    rate_by_date: dict[str, Optional[float]],
) -> tuple[list[dict], bool]:
    """Use the user-rate in effect on each work date when one exists."""
    changed = False
    out = []
    for row in records or []:
        work_date = str(row.get("work_date") or row.get("clock_in_at") or "")[:10]
        historical = _rate_num((rate_by_date or {}).get(work_date))
        current = _rate_num(row.get("hourly_rate"))
        copy = dict(row)
        if historical is not None:
            copy["hourly_rate"] = historical
            copy["rate_source"] = "user_rates"
            if current is None or abs(historical - current) > 0.009:
                changed = True
        else:
            copy["rate_source"] = "time_record"
        out.append(copy)
    return out, changed


def aggregate_finalized_w2_periods(
    rows: list[dict],
    *,
    exclude_period: Optional[tuple[str, str]] = None,
) -> list[dict]:
    """Newest finalized W-2 periods that have an employer-tax snapshot."""
    from backend.payroll_report_analytics import batch_is_complete

    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows or []:
        if str(row.get("worker_category") or "") != "w2":
            continue
        if not row.get("employer_cost_recorded"):
            continue
        if not batch_is_complete(
            {
                "batch_status": row.get("batch_status"),
                "status": row.get("batch_status"),
                "payout_details_finalized_at": row.get("details_finalized_at"),
            }
        ):
            continue
        start = str(row.get("pay_period_start") or "")[:10]
        end = str(row.get("pay_period_end") or "")[:10]
        if not start or not end:
            continue
        if exclude_period and (start, end) == (
            str(exclude_period[0])[:10],
            str(exclude_period[1])[:10],
        ):
            continue
        bucket = buckets.setdefault(
            (start, end),
            {
                "pay_period_start": start,
                "pay_period_end": end,
                "gross_pay": 0.0,
                "total_payroll_cost": 0.0,
                "employer_cost_recorded": True,
            },
        )
        bucket["gross_pay"] = _money(bucket["gross_pay"] + _money(row.get("gross_pay")))
        bucket["total_payroll_cost"] = _money(
            bucket["total_payroll_cost"] + _money(row.get("total_payroll_cost"))
        )
    ordered = sorted(buckets.values(), key=lambda item: (item["pay_period_end"], item["pay_period_start"]), reverse=True)
    return ordered


def _row_period(row: dict) -> tuple[str, str]:
    return (
        str(row.get("pay_period_start") or "")[:10],
        str(row.get("pay_period_end") or "")[:10],
    )


def finalized_rows_for_period(rows: list[dict], start: str, end: str) -> list[dict]:
    from backend.payroll_report_analytics import batch_is_complete

    want = (str(start)[:10], str(end)[:10])
    kept = []
    for row in rows or []:
        if _row_period(row) != want:
            continue
        if batch_is_complete(
            {
                "batch_status": row.get("batch_status"),
                "status": row.get("batch_status"),
                "payout_details_finalized_at": row.get("details_finalized_at"),
            }
        ):
            kept.append(row)
    return kept


def _lookup_user_rate(conn, user_id: int, work_date: str) -> Optional[float]:
    if not work_date:
        return None
    from backend.ta_helpers import table_exists

    cur = conn.cursor()
    if not table_exists(cur, "user_rates"):
        return None
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT hourly_rate
        FROM user_rates
        WHERE user_id = %s
          AND effective_date <= %s
          AND (end_date IS NULL OR end_date >= %s)
        ORDER BY effective_date DESC, id DESC
        LIMIT 1
        """,
        (int(user_id), work_date, work_date),
    )
    row = c.fetchone()
    if not row:
        return None
    return _rate_num(row.get("hourly_rate"))


def _load_employee_rows(conn, organization_id: int, user_id: int) -> list[dict]:
    from backend.payroll_report import query_payroll_report

    report = query_payroll_report(
        conn,
        int(organization_id),
        all_history=True,
        user_id=int(user_id),
        include_analytics=False,
        include_employee_detail=True,
        limit=500,
    )
    return list(report.get("rows") or [])


def build_hourly_cost_for_time_records(
    conn,
    organization_id: int,
    user_id: int,
    *,
    period_start: str,
    period_end: str,
    records: Optional[list[dict]] = None,
    ot_threshold: Any = None,
    ot_multiplier: Any = None,
) -> dict[str, Any]:
    """Time Records analysis for one employee and one payroll period.

    Finalized payroll for that period wins. Otherwise the hours and earnings
    walk matches the period summary, with historical user rates when a dated
    rate exists, and a gross-weighted burden from up to four prior finalized
    payrolls. Read-only.
    """
    from backend.payroll_tax_settings import fetch_payroll_tax_settings

    start = str(period_start or "")[:10]
    end = str(period_end or "")[:10]
    settings = None
    try:
        settings = fetch_payroll_tax_settings(conn, int(organization_id))
    except Exception:
        settings = None
    target = labor_cost_target_from_settings(settings)

    history_rows: list[dict] = []
    try:
        history_rows = _load_employee_rows(conn, organization_id, user_id)
    except Exception:
        history_rows = []

    finalized = finalized_rows_for_period(history_rows, start, end)
    if finalized:
        analysis = hourly_cost_from_report_rows(
            finalized,
            tax_settings=settings,
            labor_cost_target=target,
        )
        analysis["finalized"] = True
        analysis["cost_basis"] = (
            "processed_payroll"
            if analysis.get("worker_category") == "w2"
            else "contractor_cost"
        )
        analysis["notes"] = list(analysis.get("notes") or []) + [
            "Uses finalized payroll amounts for this period."
        ]
        return analysis

    clean_records = []
    for raw in records or []:
        if not isinstance(raw, dict):
            continue
        clean_records.append(
            {
                "id": raw.get("id"),
                "approved_hours": raw.get("approved_hours"),
                "clock_in_at": raw.get("clock_in_at"),
                "work_date": str(raw.get("work_date") or raw.get("clock_in_at") or "")[:10],
                "hourly_rate": raw.get("hourly_rate"),
                "worker_category": raw.get("worker_category"),
            }
        )

    rate_by_date: dict[str, Optional[float]] = {}
    for rec in clean_records:
        work_date = rec["work_date"]
        if work_date and work_date not in rate_by_date:
            try:
                rate_by_date[work_date] = _lookup_user_rate(conn, user_id, work_date)
            except Exception:
                rate_by_date[work_date] = None
    rated, rates_changed = apply_historical_rates(clean_records, rate_by_date)
    economics = economics_from_time_records(
        rated,
        ot_threshold=ot_threshold if ot_threshold not in (None, "") else DEFAULT_OT_THRESHOLD,
        ot_multiplier=ot_multiplier if ot_multiplier not in (None, "") else DEFAULT_OT_MULTIPLIER,
    )
    category = economics.get("worker_category") or "w2"
    if category not in ("w2", "temp", "contractor_1099"):
        category = str((clean_records[0].get("worker_category") if clean_records else "") or "w2")
        economics["worker_category"] = category

    rate_note = None
    if rates_changed:
        rate_note = (
            "Regular rates use the rate in effect on each work date. "
            "That differs from the current profile rate shown on the period summary."
        )

    if category != "w2":
        return analyze_employee_hourly_cost(
            **economics,
            scenario="contractor",
            tax_settings=settings,
            labor_cost_target=target,
            rate_note=rate_note,
            total_payroll_cost=economics["gross_pay"],
            employer_taxes=0.0,
            employer_cost_recorded=False,
        )

    periods = aggregate_finalized_w2_periods(
        history_rows, exclude_period=(start, end)
    )
    weighted = weighted_burden_from_periods(periods, limit=HISTORY_PERIODS)
    return analyze_employee_hourly_cost(
        **economics,
        scenario="estimated",
        burden_percent=weighted.get("burden_percent"),
        burden_sources=weighted.get("sources") or [],
        tax_settings=settings,
        labor_cost_target=target,
        rate_note=rate_note,
        employer_cost_recorded=False,
    )
