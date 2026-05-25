"""Organization payroll tax rate settings (additive system_settings JSON)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from backend.ta_helpers import table_exists, table_has_column

SETTINGS_KEY = "payroll_tax_settings_json"

# 2026-oriented defaults — admin can override per org. Estimates only.
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
    "ny_suta_rate": 0.025,
    "ny_suta_wage_base": 12500,
    "ny_reemployment_service_fund_rate": 0.00075,
    "nyc_mctmt_rate": 0.0034,
    "nyc_mctmt_enabled": False,
    "workers_comp_rate": 0.0,
    "federal_standard_deduction_single": 15750,
    "federal_standard_deduction_mfj": 31500,
    "federal_standard_deduction_hoh": 23625,
    "ny_withholding_estimate_rate": 0.045,
    "nyc_resident_estimate_rate": 0.035,
    "nyc_nonresident_estimate_rate": 0.010,
}


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
    for key in DEFAULT_PAYROLL_TAX_SETTINGS:
        if key in body and body[key] is not None:
            current[key] = body[key]
    if body.get("notes") is not None:
        current["notes"] = str(body["notes"])[:2000]
    _set_setting(conn, organization_id, SETTINGS_KEY, json.dumps(current))
    return fetch_payroll_tax_settings(conn, organization_id)
