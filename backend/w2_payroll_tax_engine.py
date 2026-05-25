"""
Estimated W-2 payroll tax calculator for internal reporting only.

NOT official payroll filing software. All outputs labeled as estimates.
Federal: simplified annualized percentage method from W-4 inputs.
NY/NYC: simplified effective-rate estimates — verify with accountant.
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from backend.payroll_tax_messages import ESTIMATE_DISCLAIMER
from backend.payroll_tax_settings import fetch_payroll_tax_settings
from backend.payroll_identity import fetch_payroll_profile_row

PAY_PERIODS = {
    "weekly": 52,
    "biweekly": 26,
    "semimonthly": 24,
    "monthly": 12,
    "annual": 1,
}

# 2026-style annual brackets (single_or_mfs) — simplified estimate tiers
_FED_BRACKETS_SINGLE = [
    (11925, Decimal("0.10")),
    (48475, Decimal("0.12")),
    (103350, Decimal("0.22")),
    (197300, Decimal("0.24")),
    (250525, Decimal("0.32")),
    (626350, Decimal("0.35")),
    (Decimal("Infinity"), Decimal("0.37")),
]

_FED_BRACKETS_MFJ = [
    (23850, Decimal("0.10")),
    (96950, Decimal("0.12")),
    (206700, Decimal("0.22")),
    (394600, Decimal("0.24")),
    (501050, Decimal("0.32")),
    (751600, Decimal("0.35")),
    (Decimal("Infinity"), Decimal("0.37")),
]


def _d(val: Any) -> Decimal:
    try:
        return Decimal(str(val or 0))
    except Exception:
        return Decimal("0")


def _q2(val: Decimal) -> float:
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _money_json(val: Decimal) -> Optional[float]:
    if val is None:
        return None
    return _q2(val)


def _annual_tax_from_brackets(taxable: Decimal, brackets: list) -> Decimal:
    if taxable <= 0:
        return Decimal("0")
    tax = Decimal("0")
    prev = Decimal("0")
    for upper, rate in brackets:
        upper_d = Decimal(str(upper)) if upper != Decimal("Infinity") else taxable + 1
        band = min(taxable, upper_d) - prev
        if band <= 0:
            break
        tax += band * rate
        prev = upper_d
        if taxable <= upper_d:
            break
    return tax


def _read_compliance(work_json: Any) -> dict:
    if isinstance(work_json, str):
        try:
            work_json = json.loads(work_json)
        except Exception:
            work_json = {}
    if not isinstance(work_json, dict):
        work_json = {}
    w4 = work_json.get("w4") if isinstance(work_json.get("w4"), dict) else {}
    comp = w4.get("compliance") if isinstance(w4.get("compliance"), dict) else {}
    pt = work_json.get("payroll_tax") if isinstance(work_json.get("payroll_tax"), dict) else {}
    return {**comp, **pt, "_work_json": work_json}


def fetch_employee_tax_profile(conn, user_id: int, organization_id: int) -> dict[str, Any]:
    """Merge W-4, payroll_tax, pay rate, and address into one profile for validation/calc."""
    from backend.hr_compliance import ensure_hr_extended_profiles_table
    from backend.payroll_workflow import resolve_worker_hourly_rate

    cur = conn.cursor()
    ensure_hr_extended_profiles_table(cur)
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT work_json FROM hr_extended_profiles WHERE user_id=%s LIMIT 1",
        (int(user_id),),
    )
    row = c.fetchone() or {}
    wj = row.get("work_json")
    comp = _read_compliance(wj)

    filing_status = (
        comp.get("filing_status")
        or comp.get("step1c_filing_status")
        or comp.get("filingStatus")
        or ""
    )
    pay_frequency = (
        str(comp.get("pay_frequency") or comp.get("payout_frequency") or "biweekly").strip().lower()
    )
    if pay_frequency not in PAY_PERIODS:
        pay_frequency = "biweekly"

    rate_info = resolve_worker_hourly_rate(conn, user_id, organization_id)
    u = fetch_payroll_profile_row(conn, int(user_id))
    work_state = str(comp.get("work_state") or comp.get("state") or "").strip().upper()
    work_city = str(comp.get("work_city") or comp.get("primary_work_location") or "").strip()
    home_city = str(comp.get("home_city") or comp.get("residence_city") or work_city).strip()
    if u:
        if not work_state:
            work_state = str(u.get("state") or u.get("mailing_state") or "NY").strip().upper()
        if not work_city:
            work_city = str(u.get("city") or u.get("mailing_city") or "").strip()
        if not home_city:
            home_city = work_city or str(u.get("city") or "").strip()
    if not work_state:
        work_state = "NY"
    nyc_resident = comp.get("nyc_resident")
    if nyc_resident is None:
        nyc_resident = "new york" in home_city.lower() or home_city.lower() in ("nyc", "queens", "brooklyn", "bronx", "staten island")

    missing: list[str] = []
    if not str(filing_status).strip():
        missing.append("filing_status (W-4 Step 1c)")
    if not rate_info.get("hourly_rate") or float(rate_info["hourly_rate"]) <= 0:
        missing.append("pay_rate (Attendance Setup or employee profile)")
    if not work_state:
        missing.append("work_state (payroll tax profile)")
    if work_state == "NY" and not work_city:
        missing.append("work_city (NYC/NY local withholding)")
    if comp.get("dependents_amount") is None and comp.get("step3a_amount") is None:
        # allow zero but field should be present — soft requirement
        pass

    return {
        "user_id": int(user_id),
        "filing_status": str(filing_status).strip(),
        "pay_frequency": pay_frequency,
        "pay_periods_per_year": PAY_PERIODS[pay_frequency],
        "dependents_amount": _d(
            comp.get("dependents_amount")
            or comp.get("step3_total_amount")
            or comp.get("line_3_total")
            or 0
        ),
        "other_income": _d(comp.get("other_income") or comp.get("step4a_other_income") or 0),
        "deductions": _d(comp.get("deductions") or comp.get("step4b_deductions") or 0),
        "extra_withholding": _d(
            comp.get("extra_withholding") or comp.get("step4c_extra_withholding") or 0
        ),
        "exempt_federal": bool(comp.get("exempt") or comp.get("exempt_from_withholding")),
        "exempt_fica": bool(comp.get("exempt_fica")),
        "exempt_state": bool(comp.get("exempt_state")),
        "exempt_city": bool(comp.get("exempt_city")),
        "pre_tax_deductions": _d(comp.get("pre_tax_deductions") or 0),
        "post_tax_deductions": _d(comp.get("post_tax_deductions") or 0),
        "work_state": work_state,
        "work_city": work_city,
        "home_city": home_city,
        "nyc_resident": bool(nyc_resident),
        "hourly_rate": rate_info.get("hourly_rate"),
        "rate_missing": rate_info.get("rate_missing"),
        "w4_complete": len(missing) == 0,
        "missing_fields": missing,
        "ssn_on_file": bool(comp.get("ssn_last4") or comp.get("tax_id_last4")),
    }


def get_w2_ytd_gross(conn, organization_id: int, user_id: int, year: int) -> Decimal:
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT COALESCE(SUM(COALESCE(pbl.gross_wages, pbl.gross_amount, 0)), 0) AS ytd
        FROM payout_batch_lines pbl
        JOIN payout_batches pb ON pb.id = pbl.batch_id
        WHERE pb.organization_id=%s AND pbl.user_id=%s AND pb.worker_category='w2'
          AND YEAR(COALESCE(pbl.payment_date, pb.pay_period_end))=%s
        """,
        (int(organization_id), int(user_id), int(year)),
    )
    row = c.fetchone() or {}
    return _d(row.get("ytd"))


def calculate_w2_line_taxes(
    conn,
    organization_id: int,
    user_id: int,
    *,
    gross_pay: float,
    pay_period_start: Optional[str] = None,
    tax_year: Optional[int] = None,
) -> dict[str, Any]:
    """
    Calculate estimated employee + employer taxes for one W-2 pay period line.
    Returns amounts as floats and metadata for persistence on payout_batch_lines.
    """
    settings = fetch_payroll_tax_settings(conn, organization_id)
    year = int(tax_year or settings.get("tax_year") or 2026)
    profile = fetch_employee_tax_profile(conn, user_id, organization_id)
    gross = _d(gross_pay)
    notes: list[str] = [ESTIMATE_DISCLAIMER]

    if not profile.get("w4_complete"):
        return {
            "gross_pay": _money_json(gross),
            "tax_calc_status": "profile_incomplete",
            "tax_calc_notes": "; ".join(profile.get("missing_fields") or ["Incomplete W-4/payroll profile"]),
            "missing_fields": profile.get("missing_fields") or [],
            "disclaimer": ESTIMATE_DISCLAIMER,
        }

    periods = int(profile["pay_periods_per_year"])
    ytd_gross = get_w2_ytd_gross(conn, organization_id, user_id, year)
    pre_tax = _d(profile.get("pre_tax_deductions"))
    taxable_gross = max(Decimal("0"), gross - pre_tax)

    # --- FICA employee ---
    ss_base = _d(settings["social_security_wage_base"])
    ss_rate = _d(settings["employee_social_security_rate"])
    medicare_rate = _d(settings["employee_medicare_rate"])
    addl_medicare_rate = _d(settings["additional_medicare_rate"])
    addl_threshold = _d(settings["additional_medicare_threshold"])

    ss_remaining = max(Decimal("0"), ss_base - ytd_gross)
    ss_wages = min(taxable_gross, ss_remaining) if not profile.get("exempt_fica") else Decimal("0")
    ss_employee = ss_wages * ss_rate

    medicare_employee = Decimal("0") if profile.get("exempt_fica") else taxable_gross * medicare_rate
    ytd_after = ytd_gross + taxable_gross
    addl_medicare = Decimal("0")
    if not profile.get("exempt_fica") and ytd_after > addl_threshold:
        over = min(taxable_gross, ytd_after - max(ytd_gross, addl_threshold))
        addl_medicare = over * addl_medicare_rate

    # --- Federal income tax (annualized estimate) ---
    federal = Decimal("0")
    if not profile.get("exempt_federal"):
        annual_wages = taxable_gross * periods
        annual_wages += _d(profile.get("other_income")) * periods / periods  # step4a is annual
        filing = profile.get("filing_status") or "single_or_mfs"
        if filing in ("mfj_or_qss", "married_joint", "married"):
            brackets = _FED_BRACKETS_MFJ
            std = _d(settings["federal_standard_deduction_mfj"])
        elif filing in ("hoh", "head_of_household"):
            brackets = _FED_BRACKETS_SINGLE  # simplified — HOH uses own deduction
            std = _d(settings["federal_standard_deduction_hoh"])
        else:
            brackets = _FED_BRACKETS_SINGLE
            std = _d(settings["federal_standard_deduction_single"])

        annual_taxable = annual_wages - std - _d(profile.get("deductions")) - _d(profile.get("dependents_amount"))
        annual_taxable = max(Decimal("0"), annual_taxable)
        annual_fed = _annual_tax_from_brackets(annual_taxable, brackets)
        federal = annual_fed / periods + _d(profile.get("extra_withholding"))
        notes.append("Federal: simplified 2026 annualized bracket estimate (not full IRS Pub 15-T tables).")
    else:
        notes.append("Federal: exempt per W-4.")

    # --- NY state estimate ---
    ny_state = Decimal("0")
    if profile.get("work_state") == "NY" and not profile.get("exempt_state"):
        ny_rate = _d(settings["ny_withholding_estimate_rate"])
        ny_state = taxable_gross * ny_rate
        notes.append("NY state: simplified effective-rate estimate — not full NY wage tables.")

    # --- NYC estimate ---
    nyc = Decimal("0")
    work_in_nyc = "new york" in str(profile.get("work_city") or "").lower() or str(profile.get("work_city") or "").upper() == "NYC"
    if work_in_nyc and profile.get("work_state") == "NY" and not profile.get("exempt_city"):
        if profile.get("nyc_resident"):
            nyc_rate = _d(settings["nyc_resident_estimate_rate"])
            notes.append("NYC: resident simplified rate estimate.")
        else:
            nyc_rate = _d(settings["nyc_nonresident_estimate_rate"])
            notes.append("NYC: non-resident simplified rate estimate.")
        nyc = taxable_gross * nyc_rate

    total_employee = federal + ny_state + nyc + ss_employee + medicare_employee + addl_medicare + _d(
        profile.get("post_tax_deductions")
    )
    net = max(Decimal("0"), gross - total_employee)

    # --- Employer taxes ---
    er_ss = ss_wages * _d(settings["employer_social_security_rate"])
    er_medicare = taxable_gross * _d(settings["employer_medicare_rate"]) if not profile.get("exempt_fica") else Decimal("0")

    futa_base = _d(settings["futa_wage_base"])
    futa_remaining = max(Decimal("0"), futa_base - ytd_gross)
    futa_wages = min(taxable_gross, futa_remaining)
    futa = futa_wages * _d(settings["futa_rate"])

    suta_base = _d(settings["ny_suta_wage_base"])
    suta_remaining = max(Decimal("0"), suta_base - ytd_gross)
    suta_wages = min(taxable_gross, suta_remaining)
    ny_suta = suta_wages * _d(settings["ny_suta_rate"])
    ny_reemployment = suta_wages * _d(settings.get("ny_reemployment_service_fund_rate") or 0)

    mctmt = Decimal("0")
    if settings.get("nyc_mctmt_enabled") and work_in_nyc:
        mctmt = taxable_gross * _d(settings["nyc_mctmt_rate"])

    wc_rate = _d(settings.get("workers_comp_rate") or 0)
    workers_comp = taxable_gross * wc_rate

    total_employer = er_ss + er_medicare + futa + ny_suta + ny_reemployment + mctmt + workers_comp
    total_cost = gross + total_employer

    return {
        "gross_pay": _money_json(gross),
        "federal_withholding_estimate": _money_json(federal),
        "ny_state_withholding_estimate": _money_json(ny_state),
        "nyc_withholding_estimate": _money_json(nyc),
        "social_security_employee": _money_json(ss_employee),
        "medicare_employee": _money_json(medicare_employee),
        "additional_medicare_employee": _money_json(addl_medicare),
        "total_employee_taxes": _money_json(total_employee - _d(profile.get("post_tax_deductions"))),
        "net_pay": _money_json(net),
        "employer_social_security": _money_json(er_ss),
        "employer_medicare": _money_json(er_medicare),
        "futa_estimate": _money_json(futa),
        "ny_suta_estimate": _money_json(ny_suta + ny_reemployment),
        "employer_other_tax_estimate": _money_json(mctmt),
        "workers_comp_estimate": _money_json(workers_comp),
        "total_employer_taxes": _money_json(total_employer),
        "total_employer_cost": _money_json(total_cost),
        "tax_calc_status": "estimated",
        "tax_calc_notes": " | ".join(notes),
        "missing_fields": [],
        "disclaimer": ESTIMATE_DISCLAIMER,
        "profile": profile,
    }
