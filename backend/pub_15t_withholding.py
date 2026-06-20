"""IRS Publication 15-T (2026) percentage method — estimated federal withholding."""

from __future__ import annotations

from decimal import Decimal

from backend.withholding_bracket_math import annual_bracket_tax, q2

# STANDARD schedules — Step 2 checkbox NOT checked (Pub 15-T 2026)
_SINGLE_STANDARD = [
    (Decimal("0"), Decimal("7500"), Decimal("0"), Decimal("0.10"), Decimal("0")),
    (Decimal("7500"), Decimal("19900"), Decimal("0"), Decimal("0.10"), Decimal("7500")),
    (Decimal("19900"), Decimal("57900"), Decimal("1240"), Decimal("0.12"), Decimal("19900")),
    (Decimal("57900"), Decimal("113200"), Decimal("5800"), Decimal("0.22"), Decimal("57900")),
    (Decimal("113200"), Decimal("209275"), Decimal("17966"), Decimal("0.24"), Decimal("113200")),
    (Decimal("209275"), Decimal("263725"), Decimal("41024"), Decimal("0.32"), Decimal("209275")),
    (Decimal("263725"), Decimal("648100"), Decimal("58448"), Decimal("0.35"), Decimal("263725")),
    (Decimal("648100"), Decimal("999999999"), Decimal("192979.25"), Decimal("0.37"), Decimal("648100")),
]

_MFJ_STANDARD = [
    (Decimal("0"), Decimal("19300"), Decimal("0"), Decimal("0.10"), Decimal("0")),
    (Decimal("19300"), Decimal("39900"), Decimal("0"), Decimal("0.10"), Decimal("19300")),
    (Decimal("39900"), Decimal("115800"), Decimal("2060"), Decimal("0.12"), Decimal("39900")),
    (Decimal("115800"), Decimal("226400"), Decimal("11600"), Decimal("0.22"), Decimal("115800")),
    (Decimal("226400"), Decimal("418550"), Decimal("34332"), Decimal("0.24"), Decimal("226400")),
    (Decimal("418550"), Decimal("527550"), Decimal("82048"), Decimal("0.32"), Decimal("418550")),
    (Decimal("527550"), Decimal("788000"), Decimal("116896"), Decimal("0.35"), Decimal("527550")),
    (Decimal("788000"), Decimal("999999999"), Decimal("206583.50"), Decimal("0.37"), Decimal("788000")),
]

_SINGLE_STEP2 = [
    (Decimal("0"), Decimal("8050"), Decimal("0"), Decimal("0.10"), Decimal("0")),
    (Decimal("8050"), Decimal("14250"), Decimal("0"), Decimal("0.10"), Decimal("8050")),
    (Decimal("14250"), Decimal("33250"), Decimal("620"), Decimal("0.12"), Decimal("14250")),
    (Decimal("33250"), Decimal("60900"), Decimal("2900"), Decimal("0.22"), Decimal("33250")),
    (Decimal("60900"), Decimal("108938"), Decimal("8983"), Decimal("0.24"), Decimal("60900")),
    (Decimal("108938"), Decimal("136163"), Decimal("20512"), Decimal("0.32"), Decimal("108938")),
    (Decimal("136163"), Decimal("328350"), Decimal("29224"), Decimal("0.35"), Decimal("136163")),
    (Decimal("328350"), Decimal("999999999"), Decimal("96489.63"), Decimal("0.37"), Decimal("328350")),
]

_MFJ_STEP2 = [
    (Decimal("0"), Decimal("16100"), Decimal("0"), Decimal("0.10"), Decimal("0")),
    (Decimal("16100"), Decimal("28500"), Decimal("0"), Decimal("0.10"), Decimal("16100")),
    (Decimal("28500"), Decimal("66500"), Decimal("1240"), Decimal("0.12"), Decimal("28500")),
    (Decimal("66500"), Decimal("121800"), Decimal("5800"), Decimal("0.22"), Decimal("66500")),
    (Decimal("121800"), Decimal("217875"), Decimal("17966"), Decimal("0.24"), Decimal("121800")),
    (Decimal("217875"), Decimal("272325"), Decimal("41024"), Decimal("0.32"), Decimal("217875")),
    (Decimal("272325"), Decimal("400450"), Decimal("58448"), Decimal("0.35"), Decimal("272325")),
    (Decimal("400450"), Decimal("999999999"), Decimal("103291.75"), Decimal("0.37"), Decimal("400450")),
]


def federal_withholding_pub_15t(
    period_wages: Decimal,
    *,
    periods_per_year: int = 26,
    filing_status: str = "single_or_mfs",
    dependents_amount_annual: Decimal = Decimal("0"),
    other_income_annual: Decimal = Decimal("0"),
    deductions_annual: Decimal = Decimal("0"),
    extra_withholding_per_period: Decimal = Decimal("0"),
    step2_checkbox: bool = False,
) -> float:
    """
    Worksheet 1A (Form W-4 2020+) percentage method estimate.
    dependents_amount_annual = W-4 Step 3 total (child/other credits).
    """
    wages = Decimal(str(period_wages or 0))
    if wages <= 0:
        return 0.0

    periods = max(1, int(periods_per_year))
    annual_wages = wages * periods
    adjusted_annual = annual_wages + other_income_annual - deductions_annual - dependents_amount_annual
    if adjusted_annual < 0:
        adjusted_annual = Decimal("0")

    filing = str(filing_status or "").strip().lower()
    is_mfj = filing in ("mfj_or_qss", "married_joint", "married", "mfj")

    if step2_checkbox:
        schedule = _MFJ_STEP2 if is_mfj else _SINGLE_STEP2
    else:
        schedule = _MFJ_STANDARD if is_mfj else _SINGLE_STANDARD

    annual_tax = annual_bracket_tax(adjusted_annual, schedule)
    period_tax = annual_tax / periods + extra_withholding_per_period
    return q2(max(Decimal("0"), period_tax))


def federal_minimum_withholding_pub_15t(
    period_wages: Decimal,
    *,
    periods_per_year: int = 26,
    filing_status: str = "single_or_mfs",
    dependents_amount_annual: Decimal = Decimal("0"),
    other_income_annual: Decimal = Decimal("0"),
    deductions_annual: Decimal = Decimal("0"),
    extra_withholding_per_period: Decimal = Decimal("0"),
    step2_checkbox: bool = False,
    low_wage_annual_threshold: Decimal = Decimal("15000"),  # unused — kept for call-site compat
) -> float:
    """Official Pub 15-T withholding (no artificial annual wage gate)."""
    return federal_withholding_pub_15t(
        period_wages,
        periods_per_year=periods_per_year,
        filing_status=filing_status,
        dependents_amount_annual=dependents_amount_annual,
        other_income_annual=other_income_annual,
        deductions_annual=deductions_annual,
        extra_withholding_per_period=extra_withholding_per_period,
        step2_checkbox=step2_checkbox,
    )
