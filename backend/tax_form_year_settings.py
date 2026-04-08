"""Tax-year-driven form parameters (W-4 Step 3 credits, etc.)."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from backend.ta_helpers import table_exists


def ensure_tax_form_year_settings_table(cursor) -> None:
    if table_exists(cursor, "tax_form_year_settings"):
        return
    cursor.execute(
        """
        CREATE TABLE tax_form_year_settings (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          tax_year SMALLINT NOT NULL,
          form_code VARCHAR(16) NOT NULL,
          is_active TINYINT(1) NOT NULL DEFAULT 1,
          w4_step3_child_credit_amount DECIMAL(12,2) NOT NULL DEFAULT 2000.00,
          w4_step3_other_dependent_credit_amount DECIMAL(12,2) NOT NULL DEFAULT 500.00,
          w4_allow_other_credits TINYINT(1) NOT NULL DEFAULT 1,
          w4_enable_manual_override TINYINT(1) NOT NULL DEFAULT 1,
          effective_start_date DATE NULL,
          effective_end_date DATE NULL,
          notes TEXT NULL,
          created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_tenant_year_form (organization_id, tax_year, form_code),
          KEY idx_tfs_org (organization_id)
        ) ENGINE=InnoDB
        """
    )


def default_w4_settings_row(organization_id: int, tax_year: int) -> dict[str, Any]:
    return {
        "id": None,
        "organization_id": int(organization_id),
        "tax_year": int(tax_year),
        "form_code": "W4",
        "is_active": 1,
        "w4_step3_child_credit_amount": 2000.0,
        "w4_step3_other_dependent_credit_amount": 500.0,
        "w4_allow_other_credits": 1,
        "w4_enable_manual_override": 1,
        "effective_start_date": None,
        "effective_end_date": None,
        "notes": None,
    }


def fetch_w4_year_settings(conn, organization_id: int, tax_year: int) -> dict[str, Any]:
    cur = conn.cursor()
    ensure_tax_form_year_settings_table(cur)
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT * FROM tax_form_year_settings
        WHERE organization_id=%s AND tax_year=%s AND form_code='W4' AND is_active=1
        LIMIT 1
        """,
        (int(organization_id), int(tax_year)),
    )
    row = c.fetchone()
    if row:
        return dict(row)
    return default_w4_settings_row(organization_id, tax_year)


def upsert_w4_year_settings(conn, organization_id: int, data: dict[str, Any]) -> dict[str, Any]:
    cur = conn.cursor()
    ensure_tax_form_year_settings_table(cur)
    ty = int(data.get("tax_year") or date.today().year)
    child = float(data.get("w4_step3_child_credit_amount") or 2000)
    other = float(data.get("w4_step3_other_dependent_credit_amount") or 500)
    allow_oc = 1 if data.get("w4_allow_other_credits", True) else 0
    allow_mo = 1 if data.get("w4_enable_manual_override", True) else 0
    notes = (data.get("notes") or "").strip() or None
    active = 1 if data.get("is_active", True) else 0
    cur.execute(
        """
        INSERT INTO tax_form_year_settings (
          organization_id, tax_year, form_code, is_active,
          w4_step3_child_credit_amount, w4_step3_other_dependent_credit_amount,
          w4_allow_other_credits, w4_enable_manual_override, notes
        ) VALUES (%s, %s, 'W4', %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
          is_active=VALUES(is_active),
          w4_step3_child_credit_amount=VALUES(w4_step3_child_credit_amount),
          w4_step3_other_dependent_credit_amount=VALUES(w4_step3_other_dependent_credit_amount),
          w4_allow_other_credits=VALUES(w4_allow_other_credits),
          w4_enable_manual_override=VALUES(w4_enable_manual_override),
          notes=VALUES(notes),
          updated_at=NOW()
        """,
        (int(organization_id), ty, active, child, other, allow_oc, allow_mo, notes),
    )
    return fetch_w4_year_settings(conn, organization_id, ty)


def json_safe_settings(row: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in row.items():
        if k.startswith("_"):
            continue
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif isinstance(v, float):
            out[k] = v
        elif isinstance(v, (int, str)) or v is None:
            out[k] = v
        else:
            out[k] = float(v) if v is not None else None
    return out
