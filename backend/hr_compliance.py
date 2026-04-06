"""
HR extended profiles + official PDF prefill (I-9 Section 1 demographics).
Uses pypdf for AcroForm fill. Keep template PDFs on disk (see resolve_i9_template_path).
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from io import BytesIO
from typing import Any, Optional

from backend.ta_helpers import json_safe, table_exists

def ensure_hr_extended_profiles_table(cursor) -> None:
    """Create hr_extended_profiles if missing (runtime safety if SQL not applied yet)."""
    if table_exists(cursor, "hr_extended_profiles"):
        return
    cursor.execute(
        """
        CREATE TABLE hr_extended_profiles (
          user_id INT NOT NULL PRIMARY KEY,
          organization_id INT NOT NULL,
          preferred_name VARCHAR(128) NULL,
          date_of_birth DATE NULL,
          alternate_phone VARCHAR(32) NULL,
          emergency_contacts_json JSON NULL,
          work_json JSON NULL,
          compliance_ack_json JSON NULL,
          contractor_json JSON NULL,
          tax_snapshots_json JSON NULL,
          i9_receipt_json JSON NULL,
          notes TEXT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP,
          INDEX idx_hr_ep_org (organization_id)
        ) ENGINE=InnoDB
        """
    )


def _deep_merge_json(base: Optional[dict], patch: Optional[dict]) -> dict:
    out = dict(base or {})
    if not patch:
        return out
    for k, v in patch.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge_json(out[k], v)
        else:
            out[k] = v
    return out


def _parse_loose_address(text: str) -> dict:
    """Best-effort split of payroll_profiles.address free text."""
    t = (text or "").strip()
    if not t:
        return {}
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    out = {}
    if lines:
        out["address_line1"] = lines[0]
    if len(lines) >= 2:
        last = lines[-1]
        m = re.match(
            r"^([^,]+),\s*([A-Za-z]{2})\s*(\d{5}(?:-\d{4})?)$",
            last,
        )
        if m:
            out["city"] = m.group(1).strip()
            out["state"] = m.group(2).upper()
            out["zip"] = m.group(3)
        else:
            out["address_line2"] = last
    return out


def _fmt_ssn(raw: Optional[str]) -> str:
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 9:
        return f"{d[:3]}-{d[3:5]}-{d[5:]}"
    return raw or ""


def _fmt_mmddyyyy(d: Optional[date]) -> str:
    if not d:
        return ""
    if isinstance(d, datetime):
        d = d.date()
    return f"{d.month:02d}{d.day:02d}{d.year}"


def resolve_i9_template_path() -> Optional[str]:
    """
    Resolution order:
      HR_I9_TEMPLATE_PATH env
      backend/hr_form_assets/i-9.pdf
      frontend/src/assets/i-9.pdf (repo dev layout)
    """
    env = (os.environ.get("HR_I9_TEMPLATE_PATH") or "").strip()
    if env and os.path.isfile(env):
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "hr_form_assets", "i-9.pdf"),
        os.path.join(here, "..", "frontend", "src", "assets", "i-9.pdf"),
    ]
    for p in candidates:
        ap = os.path.abspath(p)
        if os.path.isfile(ap):
            return ap
    return None


def build_i9_field_values(
    payroll_row: dict,
    hr_row: Optional[dict],
    employer_name: str,
    employer_address: str,
) -> dict[str, str]:
    """Map DB rows to USCIS I-9 fillable field names (Section 1 focus)."""
    w = {}
    if hr_row and hr_row.get("work_json"):
        try:
            wj = hr_row["work_json"]
            if isinstance(wj, str):
                wj = json.loads(wj)
            if isinstance(wj, dict):
                w = wj
        except Exception:
            w = {}

    fn = (payroll_row.get("first_name") or "").strip()
    ln = (payroll_row.get("last_name") or "").strip()
    given = fn
    middle = (w.get("middle_initial") or w.get("middle_name") or "").strip()
    if middle and len(middle) > 1:
        middle = middle[:1]

    addr1 = (w.get("mailing_address_line1") or w.get("address_line1") or "").strip()
    city = (w.get("city") or "").strip()
    st = (w.get("state") or "").strip()
    z = (w.get("zip") or w.get("zip_code") or "").strip()

    if not addr1 and payroll_row.get("address"):
        parsed = _parse_loose_address(payroll_row.get("address") or "")
        addr1 = parsed.get("address_line1", "") or addr1
        city = city or parsed.get("city", "")
        st = st or parsed.get("state", "")
        z = z or parsed.get("zip", "")

    dob = None
    if hr_row and hr_row.get("date_of_birth"):
        d = hr_row["date_of_birth"]
        if isinstance(d, datetime):
            dob = d.date()
        elif isinstance(d, date):
            dob = d
        elif hasattr(d, "year"):
            dob = d

    email = (payroll_row.get("email") or "").strip()
    ssn = _fmt_ssn(payroll_row.get("itin_ssn"))

    vals = {
        "Last Name (Family Name)": ln,
        "First Name Given Name": first,
        "Employee Middle Initial (if any)": (middle[:1] if middle else ""),
        "Address Street Number and Name": addr1,
        "City or Town": city,
        "State": st,
        "ZIP Code": z,
        "Date of Birth mmddyyyy": _fmt_mmddyyyy(dob),
        "US Social Security Number": ssn,
        "Employees E-mail Address": email,
        "Employers Business or Org Name": (employer_name or "").strip(),
        "Employers Business or Org Address": (employer_address or "").strip(),
    }
    # Mirror common alternate field names on some I-9 revisions
    vals["First Name Given Name from Section 1"] = given
    vals["Last Name Family Name from Section 1"] = ln
    vals["middle initial if any from Section 1"] = middle

    return {k: v for k, v in vals.items() if v is not None}


def fill_i9_pdf_bytes(template_path: str, field_values: dict[str, str]) -> bytes:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(template_path)
    writer = PdfWriter()
    writer.append(reader)
    for page in writer.pages:
        writer.update_page_form_field_values(page, field_values)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def fetch_hr_org_settings(conn, organization_id: int) -> dict:
    c = conn.cursor(dictionary=True)
    out = {"employer_name": "", "employer_address": "", "employer_ein": ""}
    for key, tgt in (
        ("hr_employer_legal_name", "employer_name"),
        ("hr_employer_address", "employer_address"),
        ("hr_employer_ein", "employer_ein"),
    ):
        c.execute(
            "SELECT svalue FROM system_settings WHERE organization_id=%s AND skey=%s LIMIT 1",
            (int(organization_id), key),
        )
        row = c.fetchone()
        if row and row.get("svalue"):
            out[tgt] = (row["svalue"] or "").strip()
    c.execute(
        "SELECT display_name FROM organizations WHERE id=%s LIMIT 1",
        (int(organization_id),),
    )
    org = c.fetchone()
    if org and not out["employer_name"]:
        out["employer_name"] = (org.get("display_name") or "").strip()
    return out


def fetch_hr_extended_row(cursor, user_id: int) -> Optional[dict]:
    cursor.execute("SELECT * FROM hr_extended_profiles WHERE user_id=%s LIMIT 1", (int(user_id),))
    return cursor.fetchone()


def _json_load_maybe(v):
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v


def upsert_hr_extended_profile(conn, user_id: int, organization_id: int, body: dict) -> dict:
    cur = conn.cursor()
    ensure_hr_extended_profiles_table(cur)
    c = conn.cursor(dictionary=True)
    c.execute("SELECT * FROM hr_extended_profiles WHERE user_id=%s LIMIT 1", (int(user_id),))
    existing = c.fetchone()
    json_cols = (
        "emergency_contacts_json",
        "work_json",
        "compliance_ack_json",
        "contractor_json",
        "tax_snapshots_json",
        "i9_receipt_json",
    )

    def pick_scalar(key, current):
        if key not in body:
            return current
        return body.get(key)

    row = existing or {}
    preferred_name = pick_scalar("preferred_name", row.get("preferred_name"))
    date_of_birth = pick_scalar("date_of_birth", row.get("date_of_birth"))
    alternate_phone = pick_scalar("alternate_phone", row.get("alternate_phone"))
    notes = pick_scalar("notes", row.get("notes"))

    merged_json: dict[str, Any] = {}
    for jc in json_cols:
        if jc not in body:
            continue
        patch = body.get(jc)
        if patch is None:
            merged_json[jc] = None
            continue
        patch = _json_load_maybe(patch)
        if jc == "emergency_contacts_json" or isinstance(patch, list):
            merged_json[jc] = patch
            continue
        if isinstance(patch, dict):
            base = _json_load_maybe(row.get(jc))
            if not isinstance(base, dict):
                base = {}
            merged_json[jc] = _deep_merge_json(base, patch)
        else:
            merged_json[jc] = patch

    if existing:
        parts = [
            "preferred_name = %s",
            "date_of_birth = %s",
            "alternate_phone = %s",
            "notes = %s",
            "updated_at = NOW()",
        ]
        params: list[Any] = [preferred_name, date_of_birth, alternate_phone, notes]
        for jc in json_cols:
            if jc in merged_json:
                parts.insert(-1, f"{jc} = %s")
                v = merged_json[jc]
                params.insert(-1, json.dumps(v) if v is not None else None)
        params.append(int(user_id))
        cur.execute(
            f"UPDATE hr_extended_profiles SET {', '.join(parts)} WHERE user_id = %s",
            tuple(params),
        )
    else:
        ins: dict[str, Any] = {
            "user_id": int(user_id),
            "organization_id": int(organization_id),
            "preferred_name": preferred_name,
            "date_of_birth": date_of_birth,
            "alternate_phone": alternate_phone,
            "notes": notes,
        }
        for jc in json_cols:
            if jc in merged_json:
                v = merged_json[jc]
                ins[jc] = json.dumps(v) if v is not None else None
        cols = list(ins.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        cur.execute(
            f"INSERT INTO hr_extended_profiles ({', '.join(cols)}) VALUES ({placeholders})",
            tuple(ins[k] for k in cols),
        )
    conn.commit()
    c.execute("SELECT * FROM hr_extended_profiles WHERE user_id=%s LIMIT 1", (int(user_id),))
    out = c.fetchone()
    return json_safe(_normalize_hr_row(out))


def _normalize_hr_row(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    out = dict(row)
    for k in (
        "emergency_contacts_json",
        "work_json",
        "compliance_ack_json",
        "contractor_json",
        "tax_snapshots_json",
        "i9_receipt_json",
    ):
        if out.get(k) and isinstance(out[k], str):
            try:
                out[k] = json.loads(out[k])
            except Exception:
                pass
    return out


def get_merged_hr_profile(conn, user_id: int, payroll_row: dict) -> dict:
    _cur = conn.cursor()
    ensure_hr_extended_profiles_table(_cur)
    c = conn.cursor(dictionary=True)
    c.execute("SELECT * FROM hr_extended_profiles WHERE user_id=%s LIMIT 1", (int(user_id),))
    hr = c.fetchone()
    return {
        "payroll": json_safe(
            {
                k: payroll_row.get(k)
                for k in (
                    "user_id",
                    "first_name",
                    "last_name",
                    "email",
                    "mobile",
                    "address",
                    "itin_ssn",
                    "hire_date",
                    "termination_date",
                    "employee_id",
                    "organization_id",
                )
                if k in payroll_row or k == "user_id"
            }
        ),
        "hr": json_safe(_normalize_hr_row(hr)),
        "org_settings": json_safe(fetch_hr_org_settings(conn, int(payroll_row.get("organization_id") or 1))),
    }
