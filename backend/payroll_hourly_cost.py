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
    ot_earnings: Any = None,
    gross_pay: Any = 0,
    total_payroll_cost: Any = None,
    employer_taxes: Any = None,
    employer_tax_components: Optional[dict] = None,
    employer_cost_recorded: bool = False,
    regular_rates: Optional[list] = None,
    scenario: str = "processed",
    burden_percent: Optional[float] = None,
    burden_sources: Optional[list] = None,
    configured_burden: bool = False,
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
    # ot_earnings is the full overtime-hour wage. Employer cost uses ot_premium only.
    del ot_earnings
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
    # An explicit classification percent is not the W-2 historical burden.
    apply_configured = bool(configured_burden) and burden_percent is not None and not is_w2
    use_contractor = ((not is_w2) or scenario == "contractor") and not apply_configured

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
            method = "configured_burden" if configured_burden else "historical_burden"
            if premium <= 0.005:
                no_ot_cost = total_cost
                method = "identical_no_overtime"
            if configured_burden:
                burden_status = "configured"
                burden_label = "Configured"
                notes.append(
                    "Employer burden uses the percent configured for this classification. "
                    "Not a finalized payroll expense."
                )
            else:
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

    if method == "configured_burden":
        formula = (
            "Estimated total employer cost = gross earnings × (1 + the burden configured for this classification). "
            "W-2 historical burden is not copied onto another classification. "
            "Base cost prices every payable hour at the regular rate, then applies that classification's burden. "
            "Effective cost/hr = estimated total employer cost ÷ payable hours."
        )
    elif method == "historical_burden":
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
    basis = {str(row.get("employer_cost_basis") or "") for row in rows}
    basis.discard("")
    if "configured" in basis and basis <= {"configured", "gross_only"}:
        analysis["burden_status"] = "configured"
        analysis["burden_label"] = "Configured"
        analysis["method"] = "configured_burden"
        analysis["cost_basis"] = "configured_open_period"
        analysis["notes"] = list(analysis.get("notes") or []) + [
            "Employer burden uses the percent configured for this classification. Not a finalized payroll expense."
        ]
    elif analysis.get("worker_category") == "w2" and not finalized and analysis.get("burden_status") == "actual":
        analysis["burden_status"] = "estimated"
        analysis["burden_label"] = "Estimated"
        analysis["cost_basis"] = "payroll_line_unfinalized"
        analysis["notes"] = list(analysis.get("notes") or []) + [
            "Estimated from prior finalized payroll. Not a finalized payroll expense."
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
    ot_wages = Decimal("0")
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
            ot_wages += overtime * rate * multiplier_d
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
        "ot_earnings": float(_q2_dec(ot_wages)),
        "other_earnings": 0.0,
        "gross_pay": _money(base_r + premium_r),
        "regular_rates": rates,
    }


def _category_key(value: Any) -> str:
    text = str(value or "").strip()
    if text in ("w2", "contractor_1099", "temp"):
        return text
    return "w2"


def classification_overtime_rule(
    category: str,
    category_policies: Optional[dict] = None,
    *,
    ot_threshold: Any = None,
    ot_multiplier: Any = None,
) -> dict[str, Any]:
    """Overtime and burden assumptions for one classification.

    Missing overtime settings stay enabled at the shared weekly threshold.
    A category change therefore does not restart or erase overtime. An
    explicit percent applies only to that classification; a blank percent
    does not copy the W-2 burden onto 1099 or temp.
    """
    raw = dict((category_policies or {}).get(category) or {})
    enabled = raw.get("enabled")
    if enabled is None:
        enabled = raw.get("overtime_enabled")
    if enabled is None:
        enabled = True
    threshold = _rate_num(raw.get("threshold_hours"))
    if threshold is None:
        threshold = _rate_num(raw.get("ot_threshold"))
    if threshold is None:
        threshold = _rate_num(ot_threshold) or DEFAULT_OT_THRESHOLD
    multiplier = _rate_num(raw.get("multiplier"))
    if multiplier is None:
        multiplier = _rate_num(raw.get("ot_multiplier"))
    if multiplier is None:
        multiplier = _rate_num(ot_multiplier) or DEFAULT_OT_MULTIPLIER
    burden = raw.get("employer_burden_percent")
    if burden in (None, ""):
        burden_percent = None
    else:
        burden_percent = round(float(burden), 2)
    return {
        "enabled": bool(enabled),
        "threshold_hours": float(threshold),
        "multiplier": float(multiplier),
        "employer_burden_percent": burden_percent,
    }


def allocate_weekly_overtime(
    records: list[dict],
    *,
    ot_threshold: Any = DEFAULT_OT_THRESHOLD,
    ot_multiplier: Any = DEFAULT_OT_MULTIPLIER,
    category_policies: Optional[dict] = None,
) -> list[dict]:
    """One cumulative weekly walk. Category does not reset the hour counter."""
    ordered = sorted(
        records or [],
        key=lambda row: (str(row.get("clock_in_at") or ""), str(row.get("id") or "")),
    )
    cumulative = Decimal("0")
    lines = []
    for row in ordered:
        category = _category_key(row.get("worker_category"))
        rule = classification_overtime_rule(
            category,
            category_policies,
            ot_threshold=ot_threshold,
            ot_multiplier=ot_multiplier,
        )
        hrs = Decimal(str(max(0.0, _money(row.get("approved_hours")))))
        rate = Decimal(str(_rate_num(row.get("hourly_rate")) or 0))
        threshold_d = Decimal(str(rule["threshold_hours"]))
        multiplier_d = Decimal(str(rule["multiplier"]))
        room = max(Decimal("0"), threshold_d - cumulative)
        if rate > 0 and rule["enabled"]:
            regular = min(hrs, room)
            overtime = max(Decimal("0"), hrs - regular)
            base = hrs * rate
            premium = overtime * max(Decimal("0"), rate * multiplier_d - rate)
        elif rate > 0:
            regular = hrs
            overtime = Decimal("0")
            base = hrs * rate
            premium = Decimal("0")
        else:
            regular = hrs
            overtime = Decimal("0")
            base = Decimal("0")
            premium = Decimal("0")
        cumulative += hrs
        lines.append(
            {
                "id": row.get("id"),
                "worker_category": category,
                "hours_dec": hrs,
                "regular_dec": regular,
                "overtime_dec": overtime,
                "base_dec": base,
                "premium_dec": premium,
                "rate": float(rate),
                "rule": rule,
            }
        )
    return lines


def _rollup_lines(lines: list[dict], category: str) -> dict[str, Any]:
    base = Decimal("0")
    premium = Decimal("0")
    ot_wages = Decimal("0")
    reg_h = Decimal("0")
    ot_h = Decimal("0")
    hours = Decimal("0")
    rates: list[float] = []
    for line in lines:
        base += line["base_dec"]
        premium += line["premium_dec"]
        rate = Decimal(str(line["rate"]))
        if line["rule"]["enabled"] and rate > 0:
            ot_wages += line["overtime_dec"] * rate * Decimal(str(line["rule"]["multiplier"]))
        reg_h += line["regular_dec"]
        ot_h += line["overtime_dec"]
        hours += line["hours_dec"]
        if line["rate"] > 0:
            rates.append(line["rate"])
    base_r = float(_q2_dec(base))
    premium_r = float(_q2_dec(premium))
    return {
        "worker_category": category,
        "payable_hours": float(_q2_dec(hours)),
        "regular_hours": float(_q2_dec(reg_h)),
        "ot_hours": float(_q2_dec(ot_h)),
        "base_earnings": base_r,
        "ot_premium": premium_r,
        "ot_earnings": float(_q2_dec(ot_wages)),
        "other_earnings": 0.0,
        "gross_pay": _money(base_r + premium_r),
        "regular_rates": rates,
    }


def _distribute_money(amounts: list[Decimal], total: Optional[float]) -> list[Optional[float]]:
    if total is None:
        return [None for _ in amounts]
    if not amounts:
        return []
    target = Decimal(str(_money(total)))
    whole = sum(amounts, Decimal("0"))
    assigned: list[Optional[float]] = []
    running = Decimal("0")
    for index, amount in enumerate(amounts):
        if index == len(amounts) - 1:
            share = target - running
        elif whole <= 0:
            share = Decimal("0")
        else:
            share = _q2_dec(amount / whole * target)
            running += share
        assigned.append(float(share))
    return assigned


def _record_cost_rows(lines: list[dict], analysis: dict) -> list[dict]:
    grosses = []
    premiums = []
    hours = []
    regulars = []
    overtime = []
    for line in lines:
        grosses.append(line["base_dec"] + line["premium_dec"])
        premiums.append(line["premium_dec"])
        hours.append(line["hours_dec"])
        regulars.append(line["regular_dec"])
        overtime.append(line["overtime_dec"])
    gross_out = _distribute_money(grosses, analysis.get("gross_pay"))
    premium_out = _distribute_money(premiums, analysis.get("ot_premium"))
    hour_out = _distribute_money(hours, analysis.get("payable_hours"))
    regular_out = _distribute_money(regulars, analysis.get("regular_hours"))
    ot_out = _distribute_money(overtime, analysis.get("ot_hours"))
    cost_out = _distribute_money(grosses, analysis.get("total_employer_cost"))
    rows = []
    for index, line in enumerate(lines):
        gross = gross_out[index]
        cost = cost_out[index]
        rows.append(
            {
                "id": line["id"],
                "worker_category": line["worker_category"],
                "payable_hours": hour_out[index],
                "regular_hours": regular_out[index],
                "ot_hours": ot_out[index],
                "gross_pay": gross,
                "ot_premium": premium_out[index],
                "total_employer_cost": cost,
                "employer_expenses": None if cost is None or gross is None else _money(cost - gross),
            }
        )
    return rows


def _combined_burden_status(analyses: list[dict], categories: list[str]) -> tuple[str, str]:
    """Caption status for a mix of classifications. Configured rates stay configured."""
    statuses = [
        str(item.get("burden_status") or "")
        for item in analyses
        if item.get("burden_status") not in (None, "", "not_applicable")
    ]
    if statuses and all(status == "configured" for status in statuses):
        return "configured", "Configured"
    if statuses and all(status == "actual" for status in statuses):
        return "actual", "Actual"
    if statuses and all(status == "estimated" for status in statuses):
        label = "Estimated" if len(categories) <= 1 else "Mixed"
        return "estimated", label
    if len(categories) > 1 or len(set(statuses)) > 1:
        return "mixed", "Mixed"
    if statuses:
        return statuses[0], analyses[0].get("burden_label") or statuses[0].title()
    return "estimated", "Estimated"


def combine_category_analyses(
    analyses: list[dict],
    *,
    labor_cost_target: Optional[float] = None,
) -> dict[str, Any]:
    """Selected-record totals. Burden is extra employer cost ÷ all selected gross."""
    if len(analyses) == 1:
        return dict(analyses[0])
    hours = gross = premium = base = reg = ot = 0.0
    total_known = True
    straight_known = True
    total = straight = extra = 0.0
    wage_num = 0.0
    notes: list[str] = []
    categories = []
    for item in analyses:
        h = _money(item.get("payable_hours"))
        hours = _money(hours + h)
        gross = _money(gross + _money(item.get("gross_pay")))
        premium = _money(premium + _money(item.get("ot_premium")))
        base = _money(base + _money(item.get("base_earnings")))
        reg = _money(reg + _money(item.get("regular_hours")))
        ot = _money(ot + _money(item.get("ot_hours")))
        wage = item.get("base_wage")
        if wage is not None and h > 0:
            wage_num += float(wage) * h
        cat = str(item.get("worker_category") or "")
        if cat and cat not in categories:
            categories.append(cat)
        if item.get("total_employer_cost") is None:
            total_known = False
        else:
            total = _money(total + _money(item.get("total_employer_cost")))
            extra = _money(extra + _money(item.get("employer_expenses")))
        if item.get("straight_time_employer_cost") is None:
            straight_known = False
        else:
            straight = _money(straight + _money(item.get("straight_time_employer_cost")))
        notes.extend(item.get("notes") or [])
    target = DEFAULT_LABOR_COST_TARGET if labor_cost_target is None else float(labor_cost_target)
    all_not_applicable = all(item.get("burden_status") == "not_applicable" for item in analyses)
    burden_pct = (
        round(extra / gross * 100.0, 2)
        if total_known and gross > 0.005 and not all_not_applicable
        else None
    )
    if not total_known:
        burden_status = "unavailable"
        burden_label = "Unavailable"
        burden_pct = None
        total_cost = None
        straight_cost = None
        extra_cost = None
    elif all_not_applicable:
        burden_status = "not_applicable"
        burden_label = "N/A"
        total_cost = total
        straight_cost = straight if straight_known else None
        extra_cost = extra
    else:
        burden_status, burden_label = _combined_burden_status(analyses, categories)
        total_cost = total
        straight_cost = straight if straight_known else None
        extra_cost = extra
    effective = round(total_cost / hours, 2) if total_cost is not None and hours > 0.005 else None
    base_hr = round(straight_cost / hours, 2) if straight_cost is not None and hours > 0.005 else None
    impact = round(effective - base_hr, 2) if effective is not None and base_hr is not None else None
    impact_pct = None
    if impact is not None and base_hr and abs(base_hr) > 0.005:
        impact_pct = round(impact / base_hr * 100.0, 2)
    elif impact == 0:
        impact_pct = 0.0
    distinct_wages = {round(float(item.get("base_wage") or 0), 2) for item in analyses if item.get("base_wage") is not None}
    wage = round(wage_num / hours, 2) if hours > 0.005 and wage_num else None
    notes.append(
        "Employer burden is weighted across the selected records. "
        "Each classification uses its own cost assumption."
    )
    return {
        "worker_category": "mixed",
        "worker_categories": categories,
        "cost_basis": "estimated_time_records",
        "burden_status": burden_status,
        "burden_label": burden_label,
        "burden_percent": burden_pct,
        "burden_sources": [],
        "base_wage": wage,
        "base_wage_blended": len(distinct_wages) > 1,
        "payable_hours": hours,
        "regular_hours": reg,
        "ot_hours": ot,
        "base_earnings": base,
        "ot_premium": premium,
        "other_earnings": 0.0,
        "gross_pay": gross,
        "employer_expenses": extra_cost,
        "total_employer_cost": total_cost,
        "straight_time_gross": _money(gross - premium),
        "straight_time_employer_cost": straight_cost,
        "base_cost_per_hour": base_hr,
        "effective_cost_per_hour": effective,
        "ot_impact_per_hour": impact,
        "ot_impact_percent": impact_pct,
        "method": "classification_burden",
        "formula": (
            "Each time record keeps the burden configured for its classification. "
            "Weekly overtime is allocated once across the employee's cumulative hours. "
            "Weighted burden = employer cost above gross ÷ gross of the selected records."
        ),
        "included_expenses": [],
        "employer_cost_recorded": False,
        "finalized": False,
        "notes": notes,
        "limitations": [
            "Employee withholding is excluded from total employer cost.",
            "A classification with no configured burden does not inherit W-2 employer taxes.",
        ],
        "category_analyses": analyses,
        **_target_comparison(effective, target),
    }


def price_time_records(
    records: list[dict],
    *,
    ot_threshold: Any = DEFAULT_OT_THRESHOLD,
    ot_multiplier: Any = DEFAULT_OT_MULTIPLIER,
    category_policies: Optional[dict] = None,
    historical_w2_percent: Optional[float] = None,
    burden_sources: Optional[list] = None,
    tax_settings: Optional[dict] = None,
    labor_cost_target: Optional[float] = None,
    rate_note: Optional[str] = None,
) -> dict[str, Any]:
    """Price one employee's records. Burden follows each record's classification."""
    lines = allocate_weekly_overtime(
        records,
        ot_threshold=ot_threshold,
        ot_multiplier=ot_multiplier,
        category_policies=category_policies,
    )
    grouped: dict[str, list[dict]] = {}
    order: list[str] = []
    for line in lines:
        cat = line["worker_category"]
        if cat not in grouped:
            order.append(cat)
            grouped[cat] = []
        grouped[cat].append(line)
    analyses = []
    record_costs: list[dict] = []
    target = labor_cost_target
    for cat in order:
        group = grouped[cat]
        economics = _rollup_lines(group, cat)
        rule = group[0]["rule"]
        configured = rule.get("employer_burden_percent")
        if cat == "w2" and configured is None:
            analysis = analyze_employee_hourly_cost(
                **economics,
                scenario="estimated",
                burden_percent=historical_w2_percent,
                burden_sources=burden_sources or [],
                tax_settings=tax_settings,
                labor_cost_target=target,
                rate_note=rate_note,
                employer_cost_recorded=False,
            )
        elif configured is not None:
            analysis = analyze_employee_hourly_cost(
                **economics,
                scenario="estimated",
                burden_percent=configured,
                configured_burden=True,
                tax_settings=tax_settings,
                labor_cost_target=target,
                rate_note=rate_note,
                employer_cost_recorded=False,
            )
        else:
            analysis = analyze_employee_hourly_cost(
                **economics,
                scenario="contractor",
                tax_settings=tax_settings,
                labor_cost_target=target,
                rate_note=rate_note,
                total_payroll_cost=economics["gross_pay"],
                employer_taxes=0.0,
                employer_cost_recorded=False,
            )
        analysis["ot_earnings"] = economics.get("ot_earnings") or 0
        analyses.append(analysis)
        record_costs.extend(_record_cost_rows(group, analysis))
    if not analyses:
        empty = analyze_employee_hourly_cost(
            worker_category="w2",
            payable_hours=0,
            regular_hours=0,
            ot_hours=0,
            base_earnings=0,
            ot_premium=0,
            gross_pay=0,
            scenario="estimated",
            burden_percent=historical_w2_percent,
            labor_cost_target=target,
        )
        empty["record_costs"] = []
        empty["category_analyses"] = []
        return empty
    combined = combine_category_analyses(analyses, labor_cost_target=target)
    if len(analyses) == 1:
        combined = dict(analyses[0])
        combined["category_analyses"] = analyses
    combined["record_costs"] = record_costs
    return combined


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
        estimate_open_burden=False,
        limit=500,
    )
    return list(report.get("rows") or [])


def group_batch_sync_lines(
    records: list[dict],
    *,
    batch_category: str,
    category_policies: Optional[dict] = None,
    ot_threshold: Any = DEFAULT_OT_THRESHOLD,
    ot_multiplier: Any = DEFAULT_OT_MULTIPLIER,
) -> list[dict]:
    """Split one batch's lines with the same week allocator batch sync uses.

    An enabled week accumulates hours across classifications and rates. A
    ``disable_ot`` week stays regular. Only slices whose classification matches
    this batch become payout lines.
    """
    from backend.payroll_overtime import (
        aggregate_classified_batch_lines,
        week_ot_enabled_flags,
        weekly_ot_policy_category,
    )

    category = _category_key(batch_category)
    by_user: dict[Any, list[dict]] = {}
    user_order: list[Any] = []
    for rec in records or []:
        uid = rec.get("user_id")
        if uid not in by_user:
            user_order.append(uid)
            by_user[uid] = []
        by_user[uid].append(rec)
    out = []
    for uid in user_order:
        user_records = by_user[uid]
        policy_category = weekly_ot_policy_category(user_records)
        rule = classification_overtime_rule(
            policy_category,
            category_policies,
            ot_threshold=ot_threshold,
            ot_multiplier=ot_multiplier,
        )
        flags = week_ot_enabled_flags(user_records, default_enabled=True)
        lines = aggregate_classified_batch_lines(
            user_records,
            batch_category=category,
            threshold_hours=rule["threshold_hours"],
            ot_enabled=True,
            week_ot_enabled=flags if flags else None,
        )
        for line in lines:
            out.append(
                {
                    "user_id": line["user_id"],
                    "worker_name": line["worker_name"],
                    "rate": line["rate"],
                    "regular_hours": line["approved_hours"],
                    "ot_hours": line["ot_hours"],
                    "session_ids": line["session_ids"],
                    "multiplier": rule["multiplier"],
                }
            )
    return out


def _row_keeps_stored_employer_cost(row: dict) -> bool:
    """Finalized payroll and any line that already has an employer-tax snapshot stay stored."""
    from backend.payroll_report_analytics import batch_is_complete

    if row.get("employer_cost_recorded"):
        return True
    return batch_is_complete(
        {
            "batch_status": row.get("batch_status"),
            "status": row.get("batch_status"),
            "payout_details_finalized_at": row.get("details_finalized_at"),
        }
    )


def apply_open_period_burden_estimates(
    rows: list[dict],
    *,
    historical_w2_percent_by_user: Optional[dict] = None,
    historical_w2_percent: Optional[float] = None,
    category_burden_percent: Optional[dict] = None,
) -> list[dict]:
    """Display estimate for open lines. Does not change finalized or already-recorded costs.

    W-2 uses the classification's configured percent when one is set, otherwise
    that employee's historical finalized burden. Temp and 1099 stay at gross
    unless their own percent is configured. Gross, hours, and overtime stay
    on the stored payout line.
    """
    configured = dict(category_burden_percent or {})
    by_user = dict(historical_w2_percent_by_user or {})
    out = []
    for row in rows or []:
        copy = dict(row)
        if _row_keeps_stored_employer_cost(copy):
            copy["employer_cost_basis"] = "actual"
            out.append(copy)
            continue
        cat = _category_key(copy.get("worker_category"))
        percent = configured.get(cat)
        basis = "configured" if percent is not None else None
        if percent is None and cat == "w2":
            uid = copy.get("user_id")
            percent = by_user.get(uid)
            if percent is None and uid is not None:
                try:
                    percent = by_user.get(int(uid))
                except (TypeError, ValueError):
                    percent = None
            if percent is None:
                percent = historical_w2_percent
            basis = "estimated" if percent is not None else "unavailable"
        elif percent is None:
            basis = "gross_only"
        gross = _money(copy.get("gross_pay"))
        if percent is None:
            copy["employer_cost_basis"] = basis
            copy["total_payroll_cost"] = _money(gross + _money(copy.get("employer_taxes")))
            out.append(copy)
            continue
        try:
            percent_num = float(percent)
        except (TypeError, ValueError):
            copy["employer_cost_basis"] = "unavailable" if cat == "w2" else "gross_only"
            out.append(copy)
            continue
        taxes = float(
            _q2_dec(Decimal(str(gross)) * Decimal(str(percent_num)) / Decimal("100"))
        )
        copy["employer_taxes"] = taxes
        copy["total_payroll_cost"] = _money(gross + taxes)
        copy["employer_burden_percent"] = round(float(percent), 2)
        copy["employer_cost_basis"] = basis
        copy["employer_cost_recorded"] = False
        out.append(copy)
    return out


def employer_cost_basis_for_rows(rows: list[dict]) -> str:
    bases = {str(row.get("employer_cost_basis") or "") for row in rows or []}
    bases.discard("")
    applied = bases - {"gross_only", "unavailable"}
    if not bases or applied <= {"actual"}:
        return "actual"
    if "actual" in applied and applied - {"actual"}:
        return "mixed"
    if "estimated" in applied and "configured" in applied:
        return "mixed"
    if "estimated" in applied:
        return "estimated"
    if "configured" in applied:
        return "configured"
    return "actual"


def _session_ids(row: dict) -> set[int]:
    raw = row.get("source_shift_session_ids")
    if isinstance(raw, str):
        try:
            import json

            raw = json.loads(raw)
        except Exception:
            return set()
    if not isinstance(raw, (list, tuple)):
        return set()
    found = set()
    for item in raw:
        try:
            found.add(int(item))
        except (TypeError, ValueError):
            continue
    return found


def _record_day(record: dict) -> str:
    return str(record.get("work_date") or record.get("clock_in_at") or "")[:10]


def _projected_slice_row(template: dict, category: str, breakdown: dict, session_ids: list) -> dict:
    from backend.payroll_operations import CATEGORY_LABELS

    same_category = _category_key(template.get("worker_category")) == category
    gross = _money(breakdown.get("gross_pay"))
    return {
        "line_id": None,
        "batch_id": template.get("batch_id") if same_category else None,
        "user_id": template.get("user_id"),
        "employee_name": template.get("employee_name") or template.get("worker_name") or "",
        "employee_category": CATEGORY_LABELS.get(category, category),
        "worker_category": category,
        "payroll_period": template.get("payroll_period") or "",
        "pay_period_start": template.get("pay_period_start") or "",
        "pay_period_end": template.get("pay_period_end") or "",
        "pay_date": "",
        "official_pay_date": "",
        "pay_date_missing": True,
        "pay_date_display": "Pay Date Missing",
        "finalized_date": "",
        "regular_hours": breakdown.get("regular_hours") or 0,
        "ot_hours": breakdown.get("ot_hours") or 0,
        "regular_rate": breakdown.get("regular_rate") or 0,
        "ot_rate": breakdown.get("ot_rate") or 0,
        "base_earnings": breakdown.get("base_earnings") or 0,
        "ot_premium": breakdown.get("ot_premium") or 0,
        "regular_earnings": breakdown.get("regular_earnings") or 0,
        "ot_earnings": breakdown.get("ot_earnings") or 0,
        "other_earnings": breakdown.get("other_earnings") or 0,
        "gross_pay": gross,
        "earned_gross": gross,
        "employee_tax_deductions": 0.0,
        "other_deductions": 0.0,
        "net_pay": gross,
        "amount_paid": 0.0,
        "outstanding_balance": gross,
        "employer_taxes": 0.0,
        "employer_tax_components": {},
        "employer_cost_recorded": False,
        "total_payroll_cost": gross,
        "details_finalized_at": "",
        "payment_status": template.get("payment_status") or "",
        "payment_status_key": template.get("payment_status_key") or "",
        "payroll_status": template.get("payroll_status") or "",
        "payroll_status_key": template.get("payroll_status_key") or "",
        "batch_status": template.get("batch_status") or "hours_reviewed",
        "batch_name": template.get("batch_name") or "",
        "reporting_projection": True,
        "source_shift_session_ids": list(session_ids),
    }


def project_open_classifications(
    rows: list[dict],
    records: list[dict],
    *,
    category_policies: Optional[dict] = None,
    category_filter: Optional[str] = None,
    ot_threshold: Any = DEFAULT_OT_THRESHOLD,
    ot_multiplier: Any = DEFAULT_OT_MULTIPLIER,
) -> list[dict]:
    """Show the saved time-record classification on an open period.

    Authoritative rows stay exactly as stored. Their sessions remain in the
    weekly overtime walk and are not emitted again. Open rows for a user and
    period are replaced by that walk, so a classification change moves hours
    once and does not wait for batch synchronization. Nothing is written.

    Overtime uses the same week allocator as batch sync. A ``disable_ot`` week
    stays all regular. An enabled week keeps one running total across
    classifications and rates.
    """
    from backend.payroll_overtime import (
        allocate_session_overtime_by_week,
        compute_earnings_breakdown,
        week_ot_enabled_flags,
        weekly_ot_policy_category,
    )

    wanted = _category_key(category_filter) if category_filter and category_filter != "all" else None
    grouped: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for row in rows or []:
        try:
            uid = int(row.get("user_id") or 0)
        except (TypeError, ValueError):
            uid = 0
        key = (uid, str(row.get("pay_period_start") or "")[:10], str(row.get("pay_period_end") or "")[:10])
        if key not in grouped:
            order.append(key)
            grouped[key] = []
        grouped[key].append(row)

    by_user_records: dict[int, list[dict]] = {}
    for record in records or []:
        if not isinstance(record, dict) or record.get("id") is None:
            continue
        try:
            uid = int(record.get("user_id") or 0)
        except (TypeError, ValueError):
            continue
        by_user_records.setdefault(uid, []).append(record)

    out: list[dict] = []
    for key in order:
        group = grouped[key]
        uid, start, end = key
        authoritative = [row for row in group if _row_keeps_stored_employer_cost(row)]
        open_rows = [row for row in group if not _row_keeps_stored_employer_cost(row)]
        if not open_rows or uid <= 0 or not start or not end:
            out.extend(group)
            continue
        if authoritative and any(not _session_ids(row) for row in authoritative):
            out.extend(group)
            continue
        locked_ids: set[int] = set()
        for row in authoritative:
            locked_ids |= _session_ids(row)
        period_records = [
            record
            for record in by_user_records.get(uid, [])
            if start <= _record_day(record) <= end
        ]
        if not period_records:
            out.extend(group)
            continue
        policy_category = weekly_ot_policy_category(period_records)
        rule = classification_overtime_rule(
            policy_category,
            category_policies,
            ot_threshold=ot_threshold,
            ot_multiplier=ot_multiplier,
        )
        flags = week_ot_enabled_flags(period_records, default_enabled=True)
        allocated = allocate_session_overtime_by_week(
            period_records,
            threshold=rule["threshold_hours"],
            week_ot_enabled=flags if flags else None,
            default_enabled=True,
        )
        by_id = {record.get("id"): record for record in period_records}
        buckets: dict[tuple, dict] = {}
        bucket_order: list[tuple] = []
        ordered_records = sorted(
            period_records,
            key=lambda row: (str(row.get("clock_in_at") or ""), str(row.get("id") or "")),
        )
        for record in ordered_records:
            try:
                session_id = int(record.get("id"))
            except (TypeError, ValueError):
                continue
            if session_id in locked_ids:
                continue
            category = _category_key(record.get("worker_category"))
            if wanted and category != wanted:
                continue
            regular_hours, overtime_hours = allocated.get(
                session_id, (Decimal("0"), Decimal("0"))
            )
            rate_raw = record.get("resolved_hourly_rate")
            if rate_raw in (None, ""):
                rate_raw = record.get("hourly_rate")
            rate = round(float(rate_raw or 0), 2)
            bucket_key = (category, rate)
            if bucket_key not in buckets:
                bucket_order.append(bucket_key)
                buckets[bucket_key] = {
                    "regular": Decimal("0"),
                    "overtime": Decimal("0"),
                    "session_ids": [],
                    "multiplier": rule["multiplier"],
                }
            bucket = buckets[bucket_key]
            bucket["regular"] += regular_hours
            bucket["overtime"] += overtime_hours
            bucket["session_ids"].append(record.get("id"))
        out.extend(authoritative)
        for category, rate in bucket_order:
            bucket = buckets[(category, rate)]
            regular = float(_q2_dec(bucket["regular"]))
            overtime = float(_q2_dec(bucket["overtime"]))
            if regular <= 0 and overtime <= 0:
                continue
            names = [
                (by_id.get(session_id) or {}).get("worker_name")
                for session_id in bucket["session_ids"]
            ]
            template = next(
                (row for row in open_rows if _category_key(row.get("worker_category")) == category),
                open_rows[0],
            )
            if names and names[0] and not template.get("employee_name"):
                template = dict(template)
                template["employee_name"] = names[0]
            breakdown = compute_earnings_breakdown(
                regular_hours=regular,
                ot_hours=overtime,
                regular_rate=rate,
                multiplier=bucket["multiplier"],
            )
            projected = _projected_slice_row(template, category, breakdown, bucket["session_ids"])
            if names and names[0]:
                projected["employee_name"] = template.get("employee_name") or names[0]
            out.append(projected)
    return out


def _column_is_present(conn, table_name: str, column_name: str) -> bool:
    """True only for a real schema row. A mock cursor does not count as present."""
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT 1 AS present FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s
            LIMIT 1
            """,
            (table_name, column_name),
        )
        row = cursor.fetchone()
    except Exception:
        return False
    return isinstance(row, (dict, tuple, list))


def _load_projection_records(conn, organization_id: int, rows: list[dict]) -> list[dict]:
    open_rows = [row for row in rows if not _row_keeps_stored_employer_cost(row)]
    if not open_rows:
        return []
    if not (
        _column_is_present(conn, "shift_sessions", "payroll_classification_override")
        or _column_is_present(conn, "shift_sessions", "payroll_worker_category")
    ):
        return []
    starts = [str(row.get("pay_period_start") or "")[:10] for row in open_rows]
    ends = [str(row.get("pay_period_end") or "")[:10] for row in open_rows]
    starts = [day for day in starts if day]
    ends = [day for day in ends if day]
    if not starts or not ends:
        return []
    from backend.payroll_operations import list_time_records

    fetched = list_time_records(
        conn,
        int(organization_id),
        from_date=min(starts),
        to_date=max(ends),
        status_filter="approved",
        limit=5000,
    )
    if not isinstance(fetched, list):
        return []
    return [row for row in fetched if isinstance(row, dict) and row.get("id") is not None]


def _with_source_sessions(conn, rows: list[dict]) -> list[dict]:
    if not _column_is_present(conn, "payout_batch_lines", "source_shift_session_ids"):
        return rows
    line_ids = []
    for row in rows:
        if not _row_keeps_stored_employer_cost(row):
            continue
        try:
            line_ids.append(int(row.get("line_id")))
        except (TypeError, ValueError):
            continue
    if not line_ids:
        return rows
    try:
        cursor = conn.cursor(dictionary=True)
        placeholders = ", ".join(["%s"] * len(line_ids))
        cursor.execute(
            f"SELECT id, source_shift_session_ids FROM payout_batch_lines WHERE id IN ({placeholders})",
            tuple(line_ids),
        )
        found = cursor.fetchall()
    except Exception:
        return rows
    if not isinstance(found, list):
        return rows
    by_id = {}
    for item in found:
        if isinstance(item, dict) and item.get("id") is not None:
            by_id[int(item["id"])] = item.get("source_shift_session_ids")
    copied = []
    for row in rows:
        clone = dict(row)
        try:
            clone["source_shift_session_ids"] = by_id.get(int(row.get("line_id")))
        except (TypeError, ValueError):
            pass
        copied.append(clone)
    return copied


def annotate_open_period_rows(
    conn,
    organization_id: int,
    rows: list[dict],
    *,
    category_filter: Optional[str] = None,
) -> list[dict]:
    """Apply the live classification, then the open-period burden. Does not write payroll."""
    if not rows:
        return []
    projected = rows
    try:
        if any(not _row_keeps_stored_employer_cost(row) for row in rows):
            records = _load_projection_records(conn, organization_id, rows)
            if records:
                policies = {}
                try:
                    policies = load_category_cost_assumptions(conn, int(organization_id))
                except Exception:
                    policies = {}
                projected = project_open_classifications(
                    _with_source_sessions(conn, rows),
                    records,
                    category_policies=policies,
                    category_filter=category_filter,
                )
    except Exception:
        projected = rows
    try:
        policies = load_category_cost_assumptions(conn, int(organization_id))
    except Exception:
        policies = {}
    configured = {}
    for cat in ("w2", "contractor_1099", "temp"):
        raw = (policies.get(cat) or {}).get("employer_burden_percent")
        if raw in (None, ""):
            configured[cat] = None
            continue
        try:
            configured[cat] = round(float(raw), 2)
        except (TypeError, ValueError):
            configured[cat] = None
    needs_history = []
    for row in projected:
        if _row_keeps_stored_employer_cost(row):
            continue
        if _category_key(row.get("worker_category")) != "w2":
            continue
        if configured.get("w2") is not None:
            continue
        uid = row.get("user_id")
        if uid is not None:
            needs_history.append(int(uid))
    by_user: dict[int, Optional[float]] = {}
    for uid in dict.fromkeys(needs_history):
        try:
            history = _load_employee_rows(conn, int(organization_id), uid)
            periods = aggregate_finalized_w2_periods(history)
            by_user[uid] = weighted_burden_from_periods(periods, limit=HISTORY_PERIODS).get(
                "burden_percent"
            )
        except Exception:
            by_user[uid] = None
    return apply_open_period_burden_estimates(
        projected,
        historical_w2_percent_by_user=by_user,
        category_burden_percent=configured,
    )


def combine_stored_and_open_categories(
    priced: dict,
    stored_by_category: dict,
    *,
    labor_cost_target: Optional[float] = None,
) -> dict[str, Any]:
    """Finalized classifications keep stored cost. Open classifications keep the live estimate."""
    pieces = []
    seen = set()
    for analysis in priced.get("category_analyses") or []:
        cat = _category_key(analysis.get("worker_category"))
        seen.add(cat)
        stored = stored_by_category.get(cat)
        pieces.append(stored if stored is not None else analysis)
    for cat, stored in stored_by_category.items():
        if cat not in seen:
            pieces.append(stored)
    if not pieces:
        return dict(priced)
    if len(pieces) == 1:
        combined = dict(pieces[0])
        combined["category_analyses"] = pieces
    else:
        combined = combine_category_analyses(pieces, labor_cost_target=labor_cost_target)
    stored_cats = set(stored_by_category)
    combined["record_costs"] = [
        row
        for row in (priced.get("record_costs") or [])
        if _category_key(row.get("worker_category")) not in stored_cats
    ]
    combined["finalized"] = False
    notes = list(combined.get("notes") or [])
    notes.append(
        "Finalized classifications keep stored employer taxes. "
        "Open classifications use the current burden assumption."
    )
    combined["notes"] = notes
    return combined


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
    finalized_cats = {_category_key(row.get("worker_category")) for row in finalized}

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

    record_cats = {_category_key(rec.get("worker_category")) for rec in clean_records}
    if finalized and (not record_cats or record_cats <= finalized_cats):
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
        analysis["record_costs"] = []
        return analysis

    rate_by_date: dict[str, Optional[float]] = {}
    for rec in clean_records:
        work_date = rec["work_date"]
        if work_date and work_date not in rate_by_date:
            try:
                rate_by_date[work_date] = _lookup_user_rate(conn, user_id, work_date)
            except Exception:
                rate_by_date[work_date] = None
    rated, rates_changed = apply_historical_rates(clean_records, rate_by_date)
    rate_note = None
    if rates_changed:
        rate_note = (
            "Regular rates use the rate in effect on each work date. "
            "That differs from the current profile rate shown on the period summary."
        )
    policies = load_category_cost_assumptions(conn, organization_id)
    periods = aggregate_finalized_w2_periods(history_rows, exclude_period=(start, end))
    weighted = weighted_burden_from_periods(periods, limit=HISTORY_PERIODS)
    priced = price_time_records(
        rated,
        ot_threshold=ot_threshold if ot_threshold not in (None, "") else DEFAULT_OT_THRESHOLD,
        ot_multiplier=ot_multiplier if ot_multiplier not in (None, "") else DEFAULT_OT_MULTIPLIER,
        category_policies=policies,
        historical_w2_percent=weighted.get("burden_percent"),
        burden_sources=weighted.get("sources") or [],
        tax_settings=settings,
        labor_cost_target=target,
        rate_note=rate_note,
    )
    open_cats = record_cats - finalized_cats
    if not finalized or not open_cats:
        return priced
    stored_by_category = {}
    for cat in finalized_cats:
        cat_rows = [
            row for row in finalized if _category_key(row.get("worker_category")) == cat
        ]
        if not cat_rows:
            continue
        stored = hourly_cost_from_report_rows(
            cat_rows,
            tax_settings=settings,
            labor_cost_target=target,
        )
        stored["worker_category"] = cat
        stored["finalized"] = True
        stored["burden_status"] = "actual"
        stored["burden_label"] = "Actual"
        stored_by_category[cat] = stored
    return combine_stored_and_open_categories(
        priced,
        stored_by_category,
        labor_cost_target=target,
    )


def load_category_cost_assumptions(conn, organization_id: int) -> dict[str, dict]:
    """Calendar overtime rules plus an optional burden percent for each classification."""
    from backend.payroll_overtime import resolve_batch_overtime_policy

    calendar: dict = {}
    try:
        from backend.payroll_funding_forecast import get_calendar_settings

        calendar = (get_calendar_settings(conn, int(organization_id)) or {}).get("categories") or {}
    except Exception:
        calendar = {}
    policies: dict[str, dict] = {}
    for cat in ("w2", "contractor_1099", "temp"):
        try:
            policy = dict(resolve_batch_overtime_policy(conn, int(organization_id), cat) or {})
        except Exception:
            policy = {}
        stored = calendar.get(cat) or {}
        if "employer_burden_percent" in stored:
            policy["employer_burden_percent"] = stored.get("employer_burden_percent")
        policies[cat] = policy
    return policies
