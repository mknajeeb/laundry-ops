"""Organization payroll tax rate settings (additive system_settings JSON)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from backend.ta_helpers import table_exists, table_has_column

SETTINGS_KEY = "payroll_tax_settings_json"

# 2026-oriented defaults — admin must set NY SUTA rate from assigned DOL notice.
DEFAULT_PAYROLL_TAX_SETTINGS: dict[str, Any] = {
    "tax_year": 2026,
    "effective_date": "2026-01-01",
    "notes": "Estimated rates for internal payroll reporting — verify with accountant.",
    "employee_social_security_rate": 0.062,
    "employer_social_security_rate": 0.062,
    "social_security_wage_base": 184500,
    "employee_medicare_rate": 0.0145,
    "employer_medicare_rate": 0.0145,
    "additional_medicare_rate": 0.009,
    "additional_medicare_threshold": 200000,
    "futa_rate": 0.006,
    "futa_wage_base": 7000,
    "ny_suta_rate": None,
    "ny_suta_wage_base": 17600,
    "ny_suta_rate_note": (
        "Use employer's assigned NY DOL UI rate. New employer 2026 total rate is 0.041 including RSF."
    ),
    "ny_reemployment_service_fund_rate": 0.00075,
    "nyc_mctmt_enabled": False,
    "nyc_mctmt_zone": 1,
    "nyc_mctmt_quarterly_payroll_threshold": 312500,
    "nyc_mctmt_tier1_cap": 375000,
    "nyc_mctmt_tier1_rate": 0.00055,
    "nyc_mctmt_tier2_cap": 437500,
    "nyc_mctmt_tier2_rate": 0.00115,
    "nyc_mctmt_tier3_cap": 2500000,
    "nyc_mctmt_tier3_rate": 0.006,
    "nyc_mctmt_tier4_rate": 0.00895,
    "workers_comp_rate": 0.0,
    "federal_standard_deduction_single": 16100,
    "federal_standard_deduction_mfj": 32200,
    "federal_standard_deduction_hoh": 24150,
    "ny_withholding_estimate_rate": 0.045,
    "nyc_resident_estimate_rate": 0.035,
    "nyc_nonresident_estimate_rate": 0.010,
    "ny_pfl_employee_rate": 0.00432,
    "ny_pfl_employee_annual_cap": 411.91,
    "ny_dbl_employee_rate": 0.005,
    "ny_dbl_employee_weekly_cap": 0.60,
    "ny_dbl_employee_enabled": False,
    # Sick leave / PTO (W-2)
    "sick_leave_annual_cap_hours": 40,
    "sick_leave_annual_cap_hours_large_employer": 56,
    "sick_leave_large_employer_threshold": 100,
    "sick_leave_carryover_enabled": True,
    "sick_leave_accrual_hours_per_30_worked": 1,
    # Health credit (1099 / temp)
    "health_credit_enabled_for_1099": True,
    "health_credit_enabled_for_temp": True,
    "health_credit_accrual_method": "manual_only",
    "health_credit_rate_per_hour": 0,
    "health_credit_flat_amount_per_period": 0,
    "health_credit_cap_per_period": None,
    "health_credit_cap_per_year": None,
}

# Keys accepted on save beyond the static default map (allows future fields).
_MERGE_KEYS = frozenset(DEFAULT_PAYROLL_TAX_SETTINGS.keys()) | frozenset(
    {
        "nyc_mctmt_tier4_rate",
        "w2_employee_count",
    }
)


def _get_setting(conn, organization_id: int, key: str, default=None):
    cur = conn.cursor()
    if not table_exists(cur, "system_settings"):
        return default
    if not table_has_column(cur, "system_settings", "organization_id"):
        return default
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT svalue FROM system_settings WHERE organization_id=%s AND skey=%s LIMIT 1",
        (int(organization_id), key),
    )
    row = c.fetchone()
    return row["svalue"] if row and row.get("svalue") is not None else default


def _set_setting(conn, organization_id: int, key: str, value: str) -> None:
    cur = conn.cursor()
    if not table_exists(cur, "system_settings"):
        return
    if not table_has_column(cur, "system_settings", "organization_id"):
        return
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO system_settings (organization_id, skey, svalue)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE svalue=VALUES(svalue)
        """,
        (int(organization_id), key, value),
    )


def fetch_payroll_tax_settings(conn, organization_id: int) -> dict[str, Any]:
    raw = _get_setting(conn, organization_id, SETTINGS_KEY, None)
    out = dict(DEFAULT_PAYROLL_TAX_SETTINGS)
    if raw:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, dict):
                out.update(parsed)
        except Exception:
            pass
    out["tax_year"] = int(out.get("tax_year") or date.today().year)
    return out


def save_payroll_tax_settings(conn, organization_id: int, body: dict[str, Any]) -> dict[str, Any]:
    current = fetch_payroll_tax_settings(conn, organization_id)
    for key in _MERGE_KEYS:
        if key in body and body[key] is not None:
            current[key] = body[key]
    if "ny_suta_rate" in body and body["ny_suta_rate"] in ("", None):
        current["ny_suta_rate"] = None
    if body.get("notes") is not None:
        current["notes"] = str(body["notes"])[:2000]
    if body.get("ny_suta_rate_note") is not None:
        current["ny_suta_rate_note"] = str(body["ny_suta_rate_note"])[:500]
    _set_setting(conn, organization_id, SETTINGS_KEY, json.dumps(current))
    return fetch_payroll_tax_settings(conn, organization_id)
