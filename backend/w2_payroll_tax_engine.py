"""
Estimated W-2 payroll tax calculator for internal reporting only.

NOT official payroll filing software. All outputs labeled as estimates.
Federal: IRS Pub 15-T percentage method (2026 tables).
NY/NYC: NYS-50-T-NYS / NYS-50-T-NYC Method II (2026 tables).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from backend.employee_withholding_profile import (
    apply_withholding_profile_defaults,
    is_married_filing,
    step2_checkbox_checked,
)
from backend.ny_nyc_withholding_2026 import nyc_withholding_nys50, ny_state_withholding_nys50
from backend.pub_15t_withholding import federal_minimum_withholding_pub_15t, federal_withholding_pub_15t
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


def _worker_display_name(conn, user_id: int) -> str:
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT display_name, username FROM users WHERE id=%s LIMIT 1",
        (int(user_id),),
    )
    row = c.fetchone() or {}
    return str(row.get("display_name") or row.get("username") or "").strip()


def fetch_employee_tax_profile(
    conn, user_id: int, organization_id: int, *, worker_name: Optional[str] = None
) -> dict[str, Any]:
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
    nyc_raw = comp.get("nyc_resident")
    if nyc_raw is None or str(nyc_raw).strip() == "":
        nyc_resident: Optional[bool] = None
    elif isinstance(nyc_raw, bool):
        nyc_resident = nyc_raw
    else:
        nyc_resident = str(nyc_raw).strip().lower() in ("true", "1", "yes")

    missing: list[str] = []
    if not str(filing_status).strip():
        missing.append("filing_status (W-4 Step 1c)")

    name = worker_name or _worker_display_name(conn, user_id)
    profile = {
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
        "nyc_resident": nyc_resident,
        "hourly_rate": rate_info.get("hourly_rate"),
        "rate_missing": rate_info.get("rate_missing"),
        "w4_complete": len(missing) == 0,
        "missing_fields": missing,
        "ssn_on_file": bool(comp.get("ssn_last4") or comp.get("tax_id_last4")),
        "step2_multiple_jobs": comp.get("step2_multiple_jobs") or comp.get("step2MultipleJobs"),
        "two_jobs_only": bool(comp.get("two_jobs_only") or comp.get("twoJobsOnly")),
        "w4_qualifying_children_under_17_count": comp.get("w4_qualifying_children_under_17_count"),
        "w4_other_dependents_count": comp.get("w4_other_dependents_count"),
        "withholding_exemptions": comp.get("withholding_exemptions"),
        "worker_name": name,
    }
    profile = apply_withholding_profile_defaults(profile, name)
    missing = list(missing)
    if not str(profile.get("filing_status") or "").strip():
        if "filing_status (W-4 Step 1c)" not in missing:
            missing.append("filing_status (W-4 Step 1c)")
    else:
        missing = [m for m in missing if "filing_status" not in m]
    if not rate_info.get("hourly_rate") or float(rate_info["hourly_rate"]) <= 0:
        missing.append("pay_rate (Attendance Setup or employee profile)")
    if not profile.get("work_state"):
        missing.append("work_state (payroll tax profile)")
    if profile.get("work_state") == "NY" and not profile.get("work_city"):
        missing.append("work_city (NYC/NY local withholding)")
    profile["missing_fields"] = missing
    profile["w4_complete"] = len(missing) == 0
    return profile


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


def get_org_quarterly_w2_gross(
    conn, organization_id: int, *, year: int, quarter: int
) -> Decimal:
    q = max(1, min(4, int(quarter)))
    start_month = (q - 1) * 3 + 1
    end_month = start_month + 2
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT COALESCE(SUM(COALESCE(pbl.gross_wages, pbl.gross_amount, 0)), 0) AS qtd
        FROM payout_batch_lines pbl
        JOIN payout_batches pb ON pb.id = pbl.batch_id
        WHERE pb.organization_id=%s AND pb.worker_category='w2'
          AND YEAR(COALESCE(pbl.payment_date, pb.pay_period_end))=%s
          AND MONTH(COALESCE(pbl.payment_date, pb.pay_period_end)) BETWEEN %s AND %s
        """,
        (int(organization_id), int(year), start_month, end_month),
    )
    row = c.fetchone() or {}
    return _d(row.get("qtd"))


def _quarter_from_date_str(d: Optional[str]) -> tuple[int, int]:
    if not d:
        today = date.today()
        return today.year, (today.month - 1) // 3 + 1
    try:
        parts = str(d)[:10].split("-")
        y, m = int(parts[0]), int(parts[1])
        return y, (m - 1) // 3 + 1
    except (ValueError, IndexError):
        today = date.today()
        return today.year, (today.month - 1) // 3 + 1


def _mctmt_tax_on_quarterly_payroll(qpe: Decimal, settings: dict) -> Decimal:
    threshold = _d(settings.get("nyc_mctmt_quarterly_payroll_threshold") or 312500)
    if qpe <= threshold:
        return Decimal("0")
    t1 = _d(settings.get("nyc_mctmt_tier1_cap") or 375000)
    t2 = _d(settings.get("nyc_mctmt_tier2_cap") or 437500)
    t3 = _d(settings.get("nyc_mctmt_tier3_cap") or 2500000)
    r1 = _d(settings.get("nyc_mctmt_tier1_rate") or 0.00055)
    r2 = _d(settings.get("nyc_mctmt_tier2_rate") or 0.00115)
    r3 = _d(settings.get("nyc_mctmt_tier3_rate") or 0.006)
    r4 = _d(settings.get("nyc_mctmt_tier4_rate") or 0.00895)
    tax = min(qpe, t1) * r1
    if qpe > t1:
        tax += min(qpe - t1, t2 - t1) * r2
    if qpe > t2:
        tax += min(qpe - t2, t3 - t2) * r3
    if qpe > t3:
        tax += (qpe - t3) * r4
    return tax


def _incremental_mctmt(qtd_before: Decimal, increment: Decimal, settings: dict) -> Decimal:
    if increment <= 0:
        return Decimal("0")
    after = _mctmt_tax_on_quarterly_payroll(qtd_before + increment, settings)
    before = _mctmt_tax_on_quarterly_payroll(qtd_before, settings)
    return max(Decimal("0"), after - before)


def get_w2_ytd_deduction(
    conn, organization_id: int, user_id: int, year: int, column: str
) -> Decimal:
    if column not in ("ny_pfl_deduction", "ny_dbl_deduction"):
        return Decimal("0")
    c = conn.cursor(dictionary=True)
    c.execute(
        f"""
        SELECT COALESCE(SUM(COALESCE(pbl.{column}, 0)), 0) AS ytd
        FROM payout_batch_lines pbl
        JOIN payout_batches pb ON pb.id = pbl.batch_id
        WHERE pb.organization_id=%s AND pbl.user_id=%s AND pb.worker_category='w2'
          AND YEAR(COALESCE(pbl.payment_date, pb.pay_period_end))=%s
        """,
        (int(organization_id), int(user_id), int(year)),
    )
    row = c.fetchone() or {}
    return _d(row.get("ytd"))


def resolve_withholding_profile(
    conn,
    organization_id: int,
    user_id: int,
    *,
    profile: Optional[dict] = None,
    worker_name_snapshot: Optional[str] = None,
    pay_frequency: Optional[str] = None,
) -> dict[str, Any]:
    """
  Build the withholding profile used for tax calculation.
  When profile is provided, merges pay_frequency without re-fetching HR data.
  worker_name_snapshot drives name-based W-4 overrides (not DB display name alone).
    """
    if profile is not None:
        resolved = dict(profile)
    else:
        resolved = fetch_employee_tax_profile(
            conn,
            user_id,
            organization_id,
            worker_name=worker_name_snapshot,
        )
    if pay_frequency:
        pf = str(pay_frequency).strip().lower()
        if pf in PAY_PERIODS:
            resolved["pay_frequency"] = pf
            resolved["pay_periods_per_year"] = PAY_PERIODS[pf]
    if worker_name_snapshot and not profile:
        resolved["worker_name"] = str(worker_name_snapshot).strip()
    return resolved


def calculate_w2_line_taxes(
    conn,
    organization_id: int,
    user_id: int,
    *,
    gross_pay: float,
    pay_period_start: Optional[str] = None,
    tax_year: Optional[int] = None,
    minimum_withholding: bool = False,
    profile: Optional[dict] = None,
    worker_name_snapshot: Optional[str] = None,
    pay_frequency: Optional[str] = None,
) -> dict[str, Any]:
    """
    Calculate estimated employee + employer taxes for one W-2 pay period line.
    Returns amounts as floats and metadata for persistence on payout_batch_lines.

    Pass worker_name_snapshot and pay_frequency (batch-inferred weekly for 7-day
    periods) so Pub 15-T annualization matches the payroll batch. Optional profile
    avoids re-fetching when already built upstream.
    """
    profile = resolve_withholding_profile(
        conn,
        organization_id,
        user_id,
        profile=profile,
        worker_name_snapshot=worker_name_snapshot,
        pay_frequency=pay_frequency,
    )
    gross = _d(gross_pay)
    notes: list[str] = [ESTIMATE_DISCLAIMER]

    blocking = [
        m
        for m in (profile.get("missing_fields") or [])
        if "pay_rate" not in m
    ]
    if blocking:
        return {
            "gross_pay": _money_json(gross),
            "tax_calc_status": "profile_incomplete",
            "tax_calc_notes": "; ".join(profile.get("missing_fields") or ["Incomplete W-4/payroll profile"]),
            "missing_fields": profile.get("missing_fields") or [],
            "disclaimer": ESTIMATE_DISCLAIMER,
        }

    settings = fetch_payroll_tax_settings(conn, organization_id)
    year = int(tax_year or settings.get("tax_year") or 2026)
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

    # --- Federal income tax (IRS Pub 15-T percentage method) ---
    federal = Decimal("0")
    if not profile.get("exempt_federal"):
        if minimum_withholding:
            federal = _d(
                federal_minimum_withholding_pub_15t(
                    taxable_gross,
                    periods_per_year=periods,
                    filing_status=str(profile.get("filing_status") or "single_or_mfs"),
                    dependents_amount_annual=_d(profile.get("dependents_amount")),
                    other_income_annual=_d(profile.get("other_income")),
                    deductions_annual=_d(profile.get("deductions")),
                    extra_withholding_per_period=_d(profile.get("extra_withholding")),
                    step2_checkbox=step2_checkbox_checked(profile),
                )
            )
            notes.append(
                "Federal: IRS Pub 15-T percentage method (2026 tables) — estimate."
            )
        else:
            federal = _d(
                federal_withholding_pub_15t(
                    taxable_gross,
                    periods_per_year=periods,
                    filing_status=str(profile.get("filing_status") or "single_or_mfs"),
                    dependents_amount_annual=_d(profile.get("dependents_amount")),
                    other_income_annual=_d(profile.get("other_income")),
                    deductions_annual=_d(profile.get("deductions")),
                    extra_withholding_per_period=_d(profile.get("extra_withholding")),
                    step2_checkbox=step2_checkbox_checked(profile),
                )
            )
            notes.append("Federal: IRS Pub 15-T percentage method (2026 tables) — estimate.")
    else:
        notes.append("Federal: exempt per W-4.")

    # --- NY state (NYS-50-T-NYS Method II) ---
    ny_state = Decimal("0")
    if profile.get("work_state") == "NY" and not profile.get("exempt_state"):
        ny_state = _d(
            ny_state_withholding_nys50(
                taxable_gross,
                pay_frequency=str(profile.get("pay_frequency") or "weekly"),
                married=is_married_filing(profile),
                withholding_exemptions=int(profile.get("withholding_exemptions") or 0),
            )
        )
        notes.append("NY state: NYS-50-T-NYS Method II (2026 tables) — estimate.")

    # --- NYC (NYS-50-T-NYC Method II, NYC residents) ---
    nyc = Decimal("0")
    if (
        profile.get("nyc_resident")
        and profile.get("work_state") == "NY"
        and not profile.get("exempt_city")
    ):
        nyc = _d(
            nyc_withholding_nys50(
                taxable_gross,
                pay_frequency=str(profile.get("pay_frequency") or "weekly"),
                married=is_married_filing(profile),
                withholding_exemptions=int(profile.get("withholding_exemptions") or 0),
            )
        )
        notes.append("NYC: NYS-50-T-NYC Method II (2026 tables) — estimate.")

    post_tax = Decimal("0") if minimum_withholding else _d(profile.get("post_tax_deductions"))
    total_employee = federal + ny_state + nyc + ss_employee + medicare_employee + addl_medicare + post_tax

    # NY Paid Family Leave (employee estimate)
    ny_pfl = Decimal("0")
    if not minimum_withholding and profile.get("work_state") == "NY":
        pfl_rate = _d(settings.get("ny_pfl_employee_rate") or 0)
        pfl_cap = _d(settings.get("ny_pfl_employee_annual_cap") or 411.91)
        ytd_pfl = get_w2_ytd_deduction(conn, organization_id, user_id, year, "ny_pfl_deduction")
        period_pfl = taxable_gross * pfl_rate
        ny_pfl = min(period_pfl, max(Decimal("0"), pfl_cap - ytd_pfl))
        total_employee += ny_pfl
        notes.append("NY PFL: estimated employee deduction — verify with payroll provider.")

    # NY Disability Benefits (optional employee estimate)
    ny_dbl = Decimal("0")
    if not minimum_withholding and profile.get("work_state") == "NY" and settings.get("ny_dbl_employee_enabled"):
        dbl_rate = _d(settings.get("ny_dbl_employee_rate") or 0.005)
        weekly_cap = _d(settings.get("ny_dbl_employee_weekly_cap") or 0.60)
        periods = int(profile["pay_periods_per_year"])
        weeks_in_period = Decimal("52") / Decimal(str(periods))
        period_cap = weekly_cap * weeks_in_period
        ny_dbl = min(taxable_gross * dbl_rate, period_cap)
        total_employee += ny_dbl
        notes.append("NY DBL: estimated employee deduction — verify with payroll provider.")

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
    suta_rate_raw = settings.get("ny_suta_rate")
    ny_suta = Decimal("0")
    if suta_rate_raw is not None and str(suta_rate_raw).strip() != "":
        ny_suta = suta_wages * _d(suta_rate_raw)
    else:
        notes.append(
            "NY SUTA: rate not configured — set employer's assigned NY DOL UI rate in Tax Settings."
        )
    ny_reemployment = suta_wages * _d(settings.get("ny_reemployment_service_fund_rate") or 0)

    mctmt = Decimal("0")
    work_in_nyc = bool(profile.get("nyc_resident"))
    if settings.get("nyc_mctmt_enabled") and work_in_nyc:
        yr, qtr = _quarter_from_date_str(pay_period_start)
        qtd_before = get_org_quarterly_w2_gross(conn, organization_id, year=yr, quarter=qtr)
        mctmt = _incremental_mctmt(qtd_before, taxable_gross, settings)
        if mctmt <= 0:
            notes.append(
                "MCTMT: $0 — quarterly MCTD payroll below threshold or Zone 1 tier estimate."
            )
        else:
            notes.append(
                "MCTMT: Zone 1 tiered estimate on quarterly payroll expense — verify with accountant."
            )

    wc_rate = _d(settings.get("workers_comp_rate") or 0)
    workers_comp = taxable_gross * wc_rate

    total_employer = er_ss + er_medicare + futa + ny_suta + ny_reemployment + mctmt + workers_comp
    total_cost = gross + total_employer

    if minimum_withholding:
        notes.insert(1, "Minimum withholding mode: Pub 15-T FIT + NY/NYC tables + SS/Medicare; no PFL/DBL.")

    return {
        "gross_pay": _money_json(gross),
        "federal_withholding_estimate": _money_json(federal),
        "ny_state_withholding_estimate": _money_json(ny_state),
        "nyc_withholding_estimate": _money_json(nyc),
        "social_security_employee": _money_json(ss_employee),
        "medicare_employee": _money_json(medicare_employee),
        "additional_medicare_employee": _money_json(addl_medicare),
        "ny_pfl_deduction": _money_json(ny_pfl),
        "ny_dbl_deduction": _money_json(ny_dbl),
        "total_employee_taxes": _money_json(
            total_employee - post_tax
        ),
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
