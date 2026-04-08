"""
HR extended profiles + official PDF prefill (Form I-9 AcroForm fields).
Uses pypdf for AcroForm fill. Optional structured data in `hr_extended_profiles.work_json` under key `i9`
(citizenship, immigration, Section 2 documents, preparer, `pdf_fields` overrides). Keep template PDFs on disk
(see resolve_i9_template_path).
"""

from __future__ import annotations

import json
import os
import re
import zipfile
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.hr_forms.registry import get_form_def
from backend.hr_pdf_acroform import apply_acroform_compact_text_font
from backend.ta_helpers import json_safe, mask_tax_id_for_api_response, table_exists, table_has_column

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


# Only these keys treat an empty patch value as "do not overwrite" (profile saves often
# POST filing_status: "" when the user did not open the W-4 Select). Dollar lines use ""
# to mean clear — they must not use this set.
_W4_COMPLIANCE_EMPTY_PATCH_KEEPS_BASE = frozenset({"filing_status"})


def _deep_merge_w4_compliance(base: Optional[dict], patch: Optional[dict]) -> dict:
    """
    Merge W-4 compliance. Empty ``filing_status`` in the patch does not wipe a saved value.

    Other fields (amounts, booleans) apply as sent so clears and checkbox changes stick.
    """
    out = dict(base or {})
    if not patch:
        return out
    for k, v in patch.items():
        prev = out.get(k)
        is_empty = v is None or v == "" or (isinstance(v, str) and not str(v).strip())
        if is_empty and k in _W4_COMPLIANCE_EMPTY_PATCH_KEEPS_BASE:
            if isinstance(prev, str) and prev.strip():
                continue
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge_json(out[k], v)
        else:
            out[k] = v
    return out


def _deep_merge_w4_block(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in patch.items():
        if k == "compliance":
            if v is None:
                continue
            if isinstance(v, dict):
                bc = out.get("compliance")
                bc = bc if isinstance(bc, dict) else {}
                out["compliance"] = _deep_merge_w4_compliance(bc, v)
            else:
                out[k] = v
        elif k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge_json(out[k], v)
        else:
            out[k] = v
    return out


def _deep_merge_work_json(base: Optional[dict], patch: Optional[dict]) -> dict:
    """Deep-merge work_json; w4.compliance uses empty-string-safe merge."""
    out = dict(base or {})
    if not patch:
        return out
    for k, v in patch.items():
        if k == "w4":
            if v is None:
                continue
            if isinstance(v, dict):
                existing = out.get("w4")
                existing = existing if isinstance(existing, dict) else {}
                out["w4"] = _deep_merge_w4_block(existing, v)
            else:
                out[k] = v
            continue
        elif k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge_json(out[k], v)
        else:
            out[k] = v
    return out


_WORK_JSON_SPILLOVER_HINT_KEYS = frozenset(
    {
        "middle_initial",
        "job_title",
        "language_preference",
        "supervisor_name",
        "rehire_start_date",
        "mailing_address_line1",
        "address_line1",
        "address_line2",
        "city",
        "state",
        "zip",
    }
)


def _emergency_dict_looks_like_work_json(d: dict) -> bool:
    """True when payroll/compliance blobs were saved under emergency_contacts_json by mistake."""
    if not isinstance(d, dict):
        return False
    if isinstance(d.get("i9"), dict) or isinstance(d.get("w4"), dict):
        return True
    ny = d.get("ny_it2104")
    if isinstance(ny, dict) and ny:
        return True
    hints = sum(1 for k in _WORK_JSON_SPILLOVER_HINT_KEYS if d.get(k) not in (None, ""))
    return hints >= 3


def _decode_hr_row_json_columns(out: dict) -> None:
    """In-place: decode bytes / JSON strings for hr_extended_profiles JSON columns."""
    for k in (
        "emergency_contacts_json",
        "work_json",
        "compliance_ack_json",
        "contractor_json",
        "tax_snapshots_json",
        "i9_receipt_json",
    ):
        v = out.get(k)
        if v is None:
            continue
        if isinstance(v, (bytes, bytearray)):
            try:
                v = v.decode("utf-8", errors="replace")
                out[k] = v
            except Exception:
                continue
        if out.get(k) and isinstance(out[k], str):
            try:
                out[k] = json.loads(out[k])
            except Exception:
                pass


def _repair_emergency_contacts_work_json_spill(out: dict) -> bool:
    """
    Merge mistaken work_json payload stored in emergency_contacts_json into work_json
    and reset emergency list (real contacts may live in notes — see frontend migration).
    """
    ec = out.get("emergency_contacts_json")
    if not isinstance(ec, dict):
        return False
    if not _emergency_dict_looks_like_work_json(ec):
        return False
    base = out.get("work_json")
    base = base if isinstance(base, dict) else {}
    out["work_json"] = _deep_merge_work_json(base, ec)
    out["emergency_contacts_json"] = []
    return True


def _sanitize_for_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj


def _json_dumps_db(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    return json.dumps(_sanitize_for_json(obj), ensure_ascii=False, default=str)


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


def _s(v: Any) -> str:
    """Coerce DB/JSON values to trimmed string (JSON may contain numbers)."""
    if v is None:
        return ""
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="replace").strip()
    return str(v).strip()


def _ssn_digits_only(raw: Any) -> str:
    """AcroForm SSN fields are often max 9 chars — use digits only, no dashes."""
    return re.sub(r"\D", "", _s(raw))[:9]


def _parse_dob(d: Any) -> Optional[date]:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if isinstance(d, str):
        t = d.strip()[:10]
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(t, fmt).date()
            except ValueError:
                continue
        return None
    if hasattr(d, "year") and hasattr(d, "month") and hasattr(d, "day"):
        try:
            return date(int(d.year), int(d.month), int(d.day))
        except (TypeError, ValueError):
            return None
    return None


def _fmt_mmddyyyy(d: Optional[date]) -> str:
    if not d:
        return ""
    if isinstance(d, datetime):
        d = d.date()
    return f"{d.month:02d}{d.day:02d}{d.year}"


def _today_eastern_date() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def _split_state_zip_if_combined(state: Any, zip_code: Any) -> tuple[str, str]:
    """If ZIP is empty but state looks like 'NY 11360', split into state + ZIP."""
    st = _s(state)
    z = _s(zip_code)
    if z or len(st) < 4:
        return st, z
    m = re.match(r"^([A-Za-z]{2})\s+(\d{5}(?:-\d{4})?)$", st)
    if m:
        return m.group(1).upper(), m.group(2)
    return st, z


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


# Internal keys for work_json.i9.section2 → exact PDF /T names (USCIS I-9 edition in repo).
I9_SECTION2_INTERNAL_TO_PDF: dict[str, str] = {
    "list_a": "List A",
    "list_a_document_2": "List A.  Document 2",
    "list_a_document_2_expiration": "List A.  Document 2. Expiration Date (if any)",
    "list_a_document_3": "List A. Document 3",
    "list_a_document_title_3": "List A.   Document Title 3",
    "list_a_document_title_3_if_any": "List A.   Document Title 3.  If any",
    "list_a_document_3_number": "List A.  Document 3 Number",
    "list_a_document_3_number_if_any": "List A.  Document 3 Number.  If any",
    "list_a_document_3_issuing_authority": "List A. Document 3.  Enter Issuing Authority",
    "list_a_document_number_1": "Document Number 0 (if any)",
    "issuing_authority_1": "Issuing Authority 1",
    "issuing_authority_2": "Issuing Authority_2",
    "document_title_2_if_any": "Document Title 2 If any",
    "document_number_if_any_2": "Document Number If any_2",
    "document_number_if_any_3": "Document Number if any_3",
    "expiration_date_if_any": "Expiration Date if any",
    "list_b_title": "List B Document 1 Title",
    "list_b_number": "List B Document Number 1",
    "list_b_expiration": "List B Expiration Date 1",
    "list_b_issuing_authority": "List B Issuing Authority 1",
    "list_c_title": "List C Document Title 1",
    "list_c_number": "List C Document Number 1",
    "list_c_expiration": "List C Expiration Date 1",
    "list_c_issuing_authority": "List C Issuing Authority 1",
    "additional_information": "Additional Information",
}

I9_SUPPLEMENT_B_ROW0_TO_PDF: dict[str, str] = {
    "date_of_rehire": "Date of Rehire 0",
    "new_last_name": "Last Name 0",
    "new_first_name": "First Name 0",
    "new_middle_initial": "Middle Initial 0",
    "document_title": "Document Title 0",
    "document_number": "Document Number 0",
    "expiration_date": "Expiration Date 0",
    "additional_information": "Addtl Info 0",
}


def _load_work_and_i9(hr_row: Optional[dict]) -> tuple[dict, dict]:
    w: dict = {}
    if hr_row and hr_row.get("work_json"):
        try:
            wj = hr_row["work_json"]
            if isinstance(wj, str):
                wj = json.loads(wj)
            if isinstance(wj, dict):
                w = wj
        except Exception:
            w = {}
    i9 = w.get("i9")
    if isinstance(i9, str):
        try:
            i9 = json.loads(i9)
        except Exception:
            i9 = {}
    if not isinstance(i9, dict):
        i9 = {}
    return w, i9


def _split_display_name(display: str) -> tuple[str, str]:
    parts = _s(display).split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], " ".join(parts[1:])


def _resolve_i9_employee_names(
    payroll_row: dict,
    hr_row: Optional[dict],
    w: dict,
    i9: dict,
) -> tuple[str, str]:
    """Legal given / family name for I-9: explicit i9 > preferred > payroll if distinct > display name."""
    lf = _s(i9.get("legal_first_name"))
    ll = _s(i9.get("legal_last_name"))
    if lf and ll:
        return lf, ll

    pref = _s(hr_row.get("preferred_name")) if hr_row else ""
    if pref:
        g, fam = _split_display_name(pref)
        if fam and g.lower() != fam.lower():
            return g, fam

    fn = _s(payroll_row.get("first_name"))
    ln = _s(payroll_row.get("last_name"))
    if fn and ln and fn != ln:
        return fn, ln

    disp = _s(payroll_row.get("washpro_display_name"))
    if disp:
        return _split_display_name(disp)

    if fn or ln:
        return fn or ln, ln or fn

    return "", ""


# Suffixes for Preparer blocks (PDF omits First Name widget for row index 1).
I9_PREPARER_ROWS: list[dict[str, Optional[str]]] = [
    {"last": "0", "first": "0", "mi": "0", "addr": "0", "city": "0", "st": "0", "zip": "0", "sig": "0"},
    {"last": "1", "first": None, "mi": "1", "addr": "1", "city": "1", "st": "1", "zip": "1", "sig": "1"},
    {"last": "2", "first": "2", "mi": "2", "addr": "2", "city": "2", "st": "2", "zip": "2", "sig": "2"},
    {"last": "3", "first": "3", "mi": "3", "addr": "3", "city": "3", "st": "3", "zip": "3", "sig": "3"},
]


def _apply_i9_preparers(i9: dict, today_mm: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    rows = i9.get("preparers")
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        legacy = i9.get("preparer")
        rows = [legacy] if isinstance(legacy, dict) else []

    for idx, p in enumerate(rows[:4]):
        if not isinstance(p, dict):
            continue
        meta = I9_PREPARER_ROWS[idx] if idx < len(I9_PREPARER_ROWS) else None
        if not meta:
            break
        ln = _s(p.get("last_name"))
        fn = _s(p.get("first_name"))
        mi = _s(p.get("middle_initial"))[:1]
        addr = _s(p.get("address"))
        city = _s(p.get("city"))
        st = _s(p.get("state"))
        z = _s(p.get("zip"))
        any_val = any([ln, fn, mi, addr, city, st, z])
        if not any_val:
            continue
        sl = meta["last"]
        out[f"Preparer or Translator Last Name (Family Name) {sl}"] = ln
        sf = meta["first"]
        if sf and fn:
            out[f"Preparer or Translator First Name (Given Name) {sf}"] = fn
        out[f"PT Middle Initial {meta['mi']}"] = mi
        sa = meta["addr"]
        out[f"Preparer or Translator Address (Street Number and Name) {sa}"] = addr
        out[f"Preparer or Translator City or Town {meta['city']}"] = city
        out[f"Preparer State {meta['st']}"] = st
        out[f"Zip Code {meta['zip']}"] = z
        out[f"Sig Date mmddyyyy {meta['sig']}"] = today_mm
    return out


def _i9_map_internal(d: Any, mapping: dict[str, str]) -> dict[str, str]:
    if not isinstance(d, dict):
        return {}
    out: dict[str, str] = {}
    for ik, pdf_name in mapping.items():
        if ik not in d:
            continue
        v = d.get(ik)
        if v is None or v == "":
            continue
        out[pdf_name] = _s(v)
    return out


def _i9_citizenship_checkboxes(choice: Any) -> dict[str, str]:
    if choice is None or choice == "":
        return {}
    c = str(choice).strip()
    if c not in ("1", "2", "3", "4"):
        return {}
    out: dict[str, str] = {}
    for i in range(1, 5):
        out[f"CB_{i}"] = "/On" if c == str(i) else "/Off"
    return out


def _i9_finalize_field_values(vals: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in vals.items():
        if v is None:
            continue
        if v in ("/On", "/Off"):
            out[k] = v
        else:
            s = str(v).strip()
            if s == "":
                continue
            out[k] = s
    return out


def build_i9_field_values(
    payroll_row: dict,
    hr_row: Optional[dict],
    employer_name: str,
    employer_address: str,
) -> dict[str, str]:
    """Map payroll + HR + work_json.i9 to I-9 AcroForm field names."""
    w, i9 = _load_work_and_i9(hr_row)

    given, ln = _resolve_i9_employee_names(payroll_row, hr_row, w, i9)
    middle = _s(w.get("middle_initial") or w.get("middle_name"))
    if len(middle) > 1:
        middle = middle[:1]

    addr1 = _s(w.get("mailing_address_line1") or w.get("address_line1"))
    city = _s(w.get("city"))
    st = _s(w.get("state"))
    z = _s(w.get("zip") or w.get("zip_code"))

    if not addr1 and payroll_row.get("address"):
        parsed = _parse_loose_address(_s(payroll_row.get("address")))
        addr1 = parsed.get("address_line1", "") or addr1
        city = city or parsed.get("city", "")
        st = st or parsed.get("state", "")
        z = z or parsed.get("zip", "")

    st, z = _split_state_zip_if_combined(st, z)

    dob = _parse_dob(hr_row.get("date_of_birth")) if hr_row else None
    hire = _parse_dob(payroll_row.get("hire_date"))

    email = _s(i9.get("employee_email")) or _s(payroll_row.get("email"))
    ssn = _ssn_digits_only(i9.get("ssn") or payroll_row.get("itin_ssn"))
    tel = _s(
        i9.get("telephone")
        or w.get("telephone")
        or payroll_row.get("mobile")
        or (hr_row.get("alternate_phone") if hr_row else "")
    )

    apt = _s(i9.get("apt_number") or w.get("apt_number") or w.get("address_line2"))
    other_last = _s(i9.get("other_last_names") or w.get("other_last_names") or w.get("other_last_name"))

    today = _today_eastern_date()
    attestation_date = _parse_dob(i9.get("employee_attestation_date")) or today
    today_mm = _fmt_mmddyyyy(today)
    att_mm = _fmt_mmddyyyy(attestation_date)

    vals: dict[str, Any] = {
        "Last Name (Family Name)": ln,
        "First Name Given Name": given,
        "Employee Middle Initial (if any)": (middle[:1] if middle else ""),
        "Employee Other Last Names Used (if any)": other_last,
        "Address Street Number and Name": addr1,
        "Apt Number (if any)": apt,
        "City or Town": city,
        "State": st,
        "ZIP Code": z,
        "Date of Birth mmddyyyy": _fmt_mmddyyyy(dob),
        "US Social Security Number": ssn,
        "Employees E-mail Address": email,
        "Telephone Number": tel,
        "Today's Date mmddyyy": att_mm,
        "Employers Business or Org Name": _s(employer_name),
        "Employers Business or Org Address": _s(employer_address),
        "First Name Given Name from Section 1": given,
        "Last Name Family Name from Section 1": ln,
        "Middle initial if any from Section 1": middle,
        "First Name Given Name from Section 1-2": given,
        "Last Name Family Name from Section 1-2": ln,
        "Middle initial if any from Section 1-2": middle,
        "FirstDayEmployed mmddyyyy": _fmt_mmddyyyy(hire),
        "S2 Todays Date mmddyyyy": today_mm,
    }

    vals.update(_i9_citizenship_checkboxes(i9.get("citizenship")))

    lpr = _s(i9.get("uscis_a_number") or i9.get("lawful_permanent_resident_uscis"))
    if lpr:
        vals["3 A lawful permanent resident Enter USCIS or ANumber"] = lpr
        vals["USCIS ANumber"] = lpr
    i94 = _s(i9.get("form_i94_admission") or i9.get("form_i94"))
    if i94:
        vals["Form I94 Admission Number"] = i94
    fp = _s(i9.get("foreign_passport") or i9.get("foreign_passport_country"))
    if fp:
        vals["Foreign Passport Number and Country of IssuanceRow1"] = fp
    wexp = _parse_dob(i9.get("work_authorization_expiration"))
    if wexp:
        vals["Exp Date mmddyyyy"] = _fmt_mmddyyyy(wexp)

    er = _s(i9.get("employer_authorized_representative") or i9.get("employer_rep_name_title"))
    if er:
        vals["Last Name First Name and Title of Employer or Authorized Representative"] = er
        vals["Name of Emp or Auth Rep 0"] = er

    s2_src = i9.get("section2")
    s2: dict = dict(s2_src) if isinstance(s2_src, dict) else {}
    dr = _s(i9.get("document_route"))
    if dr == "list_a" and _s(i9.get("list_a_title")):
        s2["list_a"] = _s(i9["list_a_title"])
    elif dr == "list_bc":
        if _s(i9.get("list_b_title")):
            s2["list_b_title"] = _s(i9["list_b_title"])
        if _s(i9.get("list_c_title")):
            s2["list_c_title"] = _s(i9["list_c_title"])
    vals.update(_i9_map_internal(s2, I9_SECTION2_INTERNAL_TO_PDF))

    vals.update(_apply_i9_preparers(i9, today_mm))

    sb = i9.get("supplement_b")
    if isinstance(sb, dict):
        vals.update(_i9_map_internal(sb, I9_SUPPLEMENT_B_ROW0_TO_PDF))
        if any(_s(sb.get(k)) for k in I9_SUPPLEMENT_B_ROW0_TO_PDF.keys()):
            vals["Todays Date 0"] = today_mm

    # Supplement B / alt-procedure widgets use /Yes (not /On) in this USCIS PDF edition.
    if i9.get("section2_alternative_procedure"):
        vals["CB_Alt"] = "/Yes"
    if i9.get("supplement_b_alternative_procedure"):
        vals["CB_Alt_0"] = "/Yes"

    ov = i9.get("pdf_fields") or i9.get("field_overrides")
    if isinstance(ov, dict):
        for pk, pv in ov.items():
            if pk is None:
                continue
            pk = str(pk).strip()
            if not pk or pk.startswith("Signature of"):
                continue
            if pv in ("/On", "/Off", "/Yes", "/No"):
                vals[pk] = "/On" if pv in ("/On", "/Yes", True, "true", "1", 1) else "/Off"
            elif pv is not None:
                vals[pk] = pv

    return _i9_finalize_field_values(vals)


def build_i9_field_values_es(
    payroll_row: dict,
    hr_row: Optional[dict],
    employer_name: str,
    employer_address: str,
) -> dict[str, str]:
    """Spanish I-9 (uscis_i9_es.pdf) uses different AcroForm /T names than English."""
    w, i9 = _load_work_and_i9(hr_row)

    given, ln = _resolve_i9_employee_names(payroll_row, hr_row, w, i9)
    middle = _s(w.get("middle_initial") or w.get("middle_name"))
    if len(middle) > 1:
        middle = middle[:1]

    addr1 = _s(w.get("mailing_address_line1") or w.get("address_line1"))
    city = _s(w.get("city"))
    st = _s(w.get("state"))
    z = _s(w.get("zip") or w.get("zip_code"))

    if not addr1 and payroll_row.get("address"):
        parsed = _parse_loose_address(_s(payroll_row.get("address")))
        addr1 = parsed.get("address_line1", "") or addr1
        city = city or parsed.get("city", "")
        st = st or parsed.get("state", "")
        z = z or parsed.get("zip", "")

    st, z = _split_state_zip_if_combined(st, z)

    dob = _parse_dob(hr_row.get("date_of_birth")) if hr_row else None
    hire = _parse_dob(payroll_row.get("hire_date"))

    email = _s(i9.get("employee_email")) or _s(payroll_row.get("email"))
    ssn = _ssn_digits_only(i9.get("ssn") or payroll_row.get("itin_ssn"))
    tel = _s(
        i9.get("telephone")
        or w.get("telephone")
        or payroll_row.get("mobile")
        or (hr_row.get("alternate_phone") if hr_row else "")
    )

    apt = _s(i9.get("apt_number") or w.get("apt_number") or w.get("address_line2"))
    other_last = _s(i9.get("other_last_names") or w.get("other_last_names") or w.get("other_last_name"))

    today = _today_eastern_date()
    attestation_date = _parse_dob(i9.get("employee_attestation_date")) or today
    today_mm = _fmt_mmddyyyy(today)
    att_mm = _fmt_mmddyyyy(attestation_date)

    vals: dict[str, Any] = {
        "Last Name Family Name": ln,
        "First Name Given Name": given,
        "Middle Initial if any": (middle[:1] if middle else ""),
        "Other Last Names Used if any": other_last,
        "Address Street Number and Name": addr1,
        "Apt Number if any": apt,
        "City or Town": city,
        "State": st,
        "ZIP Code": z,
        "Date of Birth mmddyyyy": _fmt_mmddyyyy(dob),
        "US Social Security Number": ssn,
        "Employees Email Address": email,
        "EmployeeTelephoneNumber": tel,
        "Todays Date mmddyyyy": att_mm,
        "Employers Business or Organization Name": _s(employer_name),
        "Employers Business or Organization Address": _s(employer_address),
        "Last Name Family Name from Section 1": ln,
        "First Name Given Name from Section 1": given,
        "Middle initial if any from Section 1": (middle[:1] if middle else ""),
        "Last Name Family Name from Section 2": ln,
        "First Name Given Name from Section 2": given,
        "Middle initial if any from Section 2": (middle[:1] if middle else ""),
        "First Day Employed mmddyyyy": _fmt_mmddyyyy(hire),
        "Todays Date mmddyyyy_1": today_mm,
    }

    vals.update(_i9_citizenship_checkboxes(i9.get("citizenship")))

    lpr = _s(i9.get("uscis_a_number") or i9.get("lawful_permanent_resident_uscis"))
    if lpr:
        vals["A lawful permanent resident Enter USCIS or ANumber"] = lpr
    i94 = _s(i9.get("form_i94_admission") or i9.get("form_i94"))
    if i94:
        vals["Formulario I-94 Número de Admisión"] = i94
    fp = _s(i9.get("foreign_passport") or i9.get("foreign_passport_country"))
    if fp:
        vals["Foreign Passport Number and Country of Issuance"] = fp
    wexp = _parse_dob(i9.get("work_authorization_expiration"))
    if wexp:
        vals["Exp Date mmddyyyy"] = _fmt_mmddyyyy(wexp)

    er = _s(i9.get("employer_authorized_representative") or i9.get("employer_rep_name_title"))
    if er:
        vals["Last Name First Name and Title of Employer or Authorized Representative"] = er
        vals["Name of Employer or Authorized Representative_1"] = er

    # Section 2 + supplements: Spanish editions of USCIS I-9 often reuse the same /T names as English.
    s2_src = i9.get("section2")
    s2: dict = dict(s2_src) if isinstance(s2_src, dict) else {}
    dr = _s(i9.get("document_route"))
    if dr == "list_a" and _s(i9.get("list_a_title")):
        s2.setdefault("list_a", _s(i9["list_a_title"]))
    elif dr == "list_bc":
        if _s(i9.get("list_b_title")):
            s2.setdefault("list_b_title", _s(i9["list_b_title"]))
        if _s(i9.get("list_c_title")):
            s2.setdefault("list_c_title", _s(i9["list_c_title"]))
    vals.update(_i9_map_internal(s2, I9_SECTION2_INTERNAL_TO_PDF))

    vals.update(_apply_i9_preparers(i9, today_mm))

    sb = i9.get("supplement_b")
    if isinstance(sb, dict):
        vals.update(_i9_map_internal(sb, I9_SUPPLEMENT_B_ROW0_TO_PDF))
        if any(_s(sb.get(k)) for k in I9_SUPPLEMENT_B_ROW0_TO_PDF.keys()):
            vals["Todays Date 0"] = today_mm

    if i9.get("section2_alternative_procedure"):
        vals["CB_Alt"] = "/Yes"
    if i9.get("supplement_b_alternative_procedure"):
        vals["CB_Alt_0"] = "/Yes"

    ov = i9.get("pdf_fields") or i9.get("field_overrides")
    if isinstance(ov, dict):
        for pk, pv in ov.items():
            if pk is None:
                continue
            pk = str(pk).strip()
            if not pk or pk.startswith("Signature of"):
                continue
            if pv in ("/On", "/Off", "/Yes", "/No"):
                vals[pk] = "/On" if pv in ("/On", "/Yes", True, "true", "1", 1) else "/Off"
            elif pv is not None:
                vals[pk] = pv

    return _i9_finalize_field_values(vals)


# Bit 13 (4096): multiline text — helps long List A/B/C titles wrap in viewers.
_I9_MULTILINE_FLAG = 1 << 12

# Section 2 (and related) fields where document titles tend to overflow a single line.
_I9_MULTILINE_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "List A",
        "List A.  Document 2",
        "List A. Document 3",
        "List A.   Document Title 3",
        "List A.   Document Title 3.  If any",
        "List A. Document 3.  Enter Issuing Authority",
        "List B Document 1 Title",
        "List B Issuing Authority 1",
        "List C Document Title 1",
        "List C Issuing Authority 1",
        "Issuing Authority 1",
        "Issuing Authority_2",
        "Document Title 2 If any",
        "Additional Information",
        "Last Name First Name and Title of Employer or Authorized Representative",
        "Document Number 0 (if any)",
        # Spanish edition
        "Document Title 1",
        "Document Title 2 if any",
        "Document Title 3 if any",
        "List B Document Title 1",
        "List C Document Title 1",
    }
)


def _i9_pdf_set_multiline_on_fields(writer: Any) -> None:
    """Set Multiline flag on known long title fields (best-effort for viewer wrapping)."""
    try:
        from pypdf.generic import NameObject, NumberObject
    except ImportError:
        return
    for page in getattr(writer, "pages", []) or []:
        annots = page.get("/Annots")
        if not annots:
            continue
        for ref in annots:
            try:
                annot = ref.get_object()
            except Exception:
                continue
            if annot.get("/Subtype") != "/Widget":
                continue
            if annot.get("/FT") != "/Tx":
                continue
            t = annot.get("/T")
            name = str(t) if t is not None else ""
            if name not in _I9_MULTILINE_FIELD_NAMES:
                continue
            try:
                ff = int(annot.get("/Ff", 0) or 0)
            except Exception:
                ff = 0
            if ff & _I9_MULTILINE_FLAG:
                continue
            annot[NameObject("/Ff")] = NumberObject(ff | _I9_MULTILINE_FLAG)


def fill_i9_pdf_bytes(template_path: str, field_values: dict[str, str]) -> bytes:
    try:
        from pypdf import PdfReader, PdfWriter
    except ModuleNotFoundError as e:
        import sys

        raise RuntimeError(
            "Missing dependency 'pypdf'. Install with the same Python you use to run the app "
            f"(e.g. `{sys.executable} -m pip install pypdf` or activate your venv, then "
            "`pip install -r requirements.txt` from the repo root)."
        ) from e

    try:
        # Read template fully into memory so each request is independent (avoids rare file-handle /
        # platform issues on repeat downloads).
        raw = Path(template_path).read_bytes()
        reader = PdfReader(BytesIO(raw))
        writer = PdfWriter()
        max_pages = int((os.environ.get("HR_I9_MAX_PAGES") or "3").strip() or "3")
        n = len(reader.pages)
        if max_pages > 0 and n > max_pages:
            writer.append(reader, pages=list(range(min(max_pages, n))))
        else:
            writer.clone_document_from_reader(reader)
        _i9_pdf_set_multiline_on_fields(writer)
        try:
            from pypdf.generic import BooleanObject, NameObject

            root = getattr(writer, "root_object", None)
            if root is not None:
                acro = root.get("/AcroForm")
                if acro is not None:
                    acro_obj = acro.get_object() if hasattr(acro, "get_object") else acro
                    acro_obj[NameObject("/NeedAppearances")] = BooleanObject(True)
        except Exception:
            pass
        apply_acroform_compact_text_font(writer)
        flatten = (os.environ.get("HR_PDF_FLATTEN") or "").strip().lower() in ("1", "true", "yes")
        for page in writer.pages:
            writer.update_page_form_field_values(page, field_values, auto_regenerate=True, flatten=flatten)
        buf = BytesIO()
        writer.write(buf)
        return buf.getvalue()
    except Exception as e:
        raise RuntimeError(f"I-9 PDF fill failed ({template_path}): {e}") from e


def format_employer_address_from_org_row(org: dict) -> str:
    """Single block for PDF employer address: structured columns or legacy free-text `address`."""
    st = _s(org.get("employer_street"))
    apt = _s(org.get("employer_apt"))
    line1 = st
    if apt:
        line1 = f"{line1}, {apt}" if line1 else apt
    city = _s(org.get("employer_city"))
    state = _s(org.get("employer_state"))
    z = _s(org.get("employer_zip"))
    line2_parts = []
    if city:
        line2_parts.append(city)
    stz = f"{state} {z}".strip() if state or z else ""
    if stz:
        line2_parts.append(stz)
    line2 = ", ".join(line2_parts) if line2_parts else ""
    if line1 or line2:
        return "\n".join([x for x in (line1, line2) if x]).strip()
    return _s(org.get("address"))


def fetch_hr_org_settings(conn, organization_id: int) -> dict:
    """Employer line for forms: prefer `organizations` structured fields (see organizations_employer_form_fields_v1.sql)."""
    c = conn.cursor(dictionary=True)
    out = {"employer_name": "", "employer_address": "", "employer_ein": ""}
    if table_exists(c, "system_settings") and table_has_column(c, "system_settings", "organization_id"):
        try:
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
        except Exception:
            pass

    if not table_exists(c, "organizations"):
        return out

    cols = ["display_name"]
    for col in (
        "employer_legal_name",
        "employer_street",
        "employer_apt",
        "employer_city",
        "employer_state",
        "employer_zip",
        "employer_ein",
        "address",
    ):
        if table_has_column(c, "organizations", col) and col not in cols:
            cols.append(col)

    c.execute(
        f"SELECT {', '.join(cols)} FROM organizations WHERE id=%s LIMIT 1",
        (int(organization_id),),
    )
    org = c.fetchone() or {}
    eln = _s(org.get("employer_legal_name"))
    if eln:
        out["employer_name"] = eln
    elif not out["employer_name"]:
        out["employer_name"] = _s(org.get("display_name"))
    structured = format_employer_address_from_org_row(org)
    if structured:
        out["employer_address"] = structured
    eein = _s(org.get("employer_ein"))
    if eein:
        out["employer_ein"] = eein
    return out


def ensure_document_compliance_tables(cursor) -> None:
    """Runtime-safe table bootstrap for document policy + employee document records."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS org_document_compliance_policy (
          organization_id INT NOT NULL PRIMARY KEY,
          reminder_days_before INT NOT NULL DEFAULT 14,
          push_enabled TINYINT(1) NOT NULL DEFAULT 1,
          prompt_enabled TINYINT(1) NOT NULL DEFAULT 1,
          disable_profile_on_expiry TINYINT(1) NOT NULL DEFAULT 0,
          enforce_on_clock_in TINYINT(1) NOT NULL DEFAULT 0,
          updated_by_user_id INT NULL,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          CONSTRAINT fk_odcp_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
          CONSTRAINT fk_odcp_user FOREIGN KEY (updated_by_user_id) REFERENCES users(id) ON DELETE SET NULL
        ) ENGINE=InnoDB
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_document_records (
          id BIGINT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          user_id INT NOT NULL,
          document_code VARCHAR(80) NOT NULL,
          document_name VARCHAR(255) NOT NULL,
          form_locale VARCHAR(16) NULL,
          source_kind ENUM('uploaded','generated','external') NOT NULL DEFAULT 'uploaded',
          status ENUM('pending','received','verified','expired','rejected') NOT NULL DEFAULT 'received',
          issued_on DATE NULL,
          expires_on DATE NULL,
          reminder_days_before INT NULL,
          disable_profile_on_expiry TINYINT(1) NOT NULL DEFAULT 0,
          file_uri VARCHAR(1024) NULL,
          notes TEXT NULL,
          metadata_json JSON NULL,
          verified_by_user_id INT NULL,
          verified_at DATETIME NULL,
          created_by_user_id INT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          CONSTRAINT fk_edr_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
          CONSTRAINT fk_edr_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
          CONSTRAINT fk_edr_verifier FOREIGN KEY (verified_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
          CONSTRAINT fk_edr_author FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
          INDEX idx_edr_org_user (organization_id, user_id),
          INDEX idx_edr_org_code_exp (organization_id, document_code, expires_on),
          INDEX idx_edr_org_exp (organization_id, expires_on)
        ) ENGINE=InnoDB
        """
    )


def get_document_compliance_policy(conn, organization_id: int) -> dict:
    c = conn.cursor(dictionary=True)
    ensure_document_compliance_tables(c)
    c.execute(
        """
        SELECT organization_id, reminder_days_before, push_enabled, prompt_enabled,
               disable_profile_on_expiry, enforce_on_clock_in, updated_by_user_id, updated_at
        FROM org_document_compliance_policy
        WHERE organization_id=%s
        LIMIT 1
        """,
        (int(organization_id),),
    )
    row = c.fetchone()
    if not row:
        return {
            "organization_id": int(organization_id),
            "reminder_days_before": 14,
            "push_enabled": 1,
            "prompt_enabled": 1,
            "disable_profile_on_expiry": 0,
            "enforce_on_clock_in": 0,
        }
    return json_safe(row)


def upsert_document_compliance_policy(conn, organization_id: int, actor_user_id: int, body: dict) -> dict:
    c = conn.cursor()
    ensure_document_compliance_tables(c)
    rem = int(body.get("reminder_days_before") or 14)
    rem = max(0, min(rem, 365))
    push = 1 if bool(body.get("push_enabled", True)) else 0
    prompt = 1 if bool(body.get("prompt_enabled", True)) else 0
    dis = 1 if bool(body.get("disable_profile_on_expiry", False)) else 0
    enf = 1 if bool(body.get("enforce_on_clock_in", False)) else 0
    c.execute(
        """
        INSERT INTO org_document_compliance_policy
          (organization_id, reminder_days_before, push_enabled, prompt_enabled,
           disable_profile_on_expiry, enforce_on_clock_in, updated_by_user_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          reminder_days_before=VALUES(reminder_days_before),
          push_enabled=VALUES(push_enabled),
          prompt_enabled=VALUES(prompt_enabled),
          disable_profile_on_expiry=VALUES(disable_profile_on_expiry),
          enforce_on_clock_in=VALUES(enforce_on_clock_in),
          updated_by_user_id=VALUES(updated_by_user_id)
        """,
        (int(organization_id), rem, push, prompt, dis, enf, int(actor_user_id)),
    )
    conn.commit()
    return get_document_compliance_policy(conn, organization_id)


def list_employee_document_records(conn, organization_id: int, user_id: int) -> list[dict]:
    c = conn.cursor(dictionary=True)
    ensure_document_compliance_tables(c)
    c.execute(
        """
        SELECT *
        FROM employee_document_records
        WHERE organization_id=%s AND user_id=%s
        ORDER BY COALESCE(expires_on, DATE('2999-12-31')) ASC, id DESC
        """,
        (int(organization_id), int(user_id)),
    )
    rows = c.fetchall() or []
    return [json_safe(r) for r in rows]


def list_organization_document_records(conn, organization_id: int) -> list[dict]:
    """All document records for a tenant with employee join (for Documents & Evidence center)."""
    c = conn.cursor(dictionary=True)
    ensure_document_compliance_tables(c)
    c.execute(
        """
        SELECT d.*,
               pp.first_name AS emp_first_name,
               pp.last_name AS emp_last_name,
               pp.employee_id AS emp_employee_id,
               pp.email AS emp_email,
               u.username AS washpro_username
        FROM employee_document_records d
        INNER JOIN payroll_profiles pp ON pp.user_id = d.user_id
        INNER JOIN users u ON u.id = d.user_id
        WHERE d.organization_id = %s
        ORDER BY d.updated_at DESC
        LIMIT 4000
        """,
        (int(organization_id),),
    )
    out: list[dict] = []
    for r in c.fetchall() or []:
        row = dict(r)
        meta = row.get("metadata_json")
        if isinstance(meta, str):
            try:
                row["metadata_json"] = json.loads(meta)
            except Exception:
                row["metadata_json"] = {}
        elif meta is None:
            row["metadata_json"] = {}
        nm = f"{(row.get('emp_first_name') or '')} {(row.get('emp_last_name') or '')}".strip()
        row["employee_display_name"] = nm or None
        fd = get_form_def(str(row.get("document_code") or "").strip())
        row["evidence_required"] = bool((fd or {}).get("evidence_required"))
        out.append(json_safe(row))
    return out


def fetch_organization_document_records_by_ids(
    conn, organization_id: int, record_ids: list[int]
) -> list[dict]:
    """Subset of org document rows by primary key (for bulk export)."""
    ids = []
    for x in record_ids or []:
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if n > 0:
            ids.append(n)
    if not ids:
        return []
    ids = ids[:120]
    ph = ",".join(["%s"] * len(ids))
    c = conn.cursor(dictionary=True)
    ensure_document_compliance_tables(c)
    c.execute(
        f"""
        SELECT d.*,
               pp.first_name AS emp_first_name,
               pp.last_name AS emp_last_name,
               pp.employee_id AS emp_employee_id,
               pp.email AS emp_email,
               u.username AS washpro_username
        FROM employee_document_records d
        INNER JOIN payroll_profiles pp ON pp.user_id = d.user_id
        INNER JOIN users u ON u.id = d.user_id
        WHERE d.organization_id = %s AND d.id IN ({ph})
        ORDER BY d.id ASC
        """,
        (int(organization_id),) + tuple(ids),
    )
    out: list[dict] = []
    for r in c.fetchall() or []:
        row = dict(r)
        meta = row.get("metadata_json")
        if isinstance(meta, str):
            try:
                row["metadata_json"] = json.loads(meta)
            except Exception:
                row["metadata_json"] = {}
        elif meta is None:
            row["metadata_json"] = {}
        nm = f"{(row.get('emp_first_name') or '')} {(row.get('emp_last_name') or '')}".strip()
        row["employee_display_name"] = nm or None
        fd = get_form_def(str(row.get("document_code") or "").strip())
        row["evidence_required"] = bool((fd or {}).get("evidence_required"))
        out.append(json_safe(row))
    return out


def _export_http_url_allowed(url: str) -> bool:
    from urllib.parse import urlparse

    p = urlparse((url or "").strip())
    if p.scheme not in ("http", "https"):
        return False
    h = (p.hostname or "").lower()
    if not h or h in ("localhost",) or h.endswith((".local", ".localhost")):
        return False
    if re.match(r"^127\.", h) or h == "[::1]":
        return False
    if re.match(r"^10\.", h) or re.match(r"^192\.168\.", h):
        return False
    if re.match(r"^172\.(1[6-9]|2[0-9]|3[0-1])\.", h):
        return False
    if h.startswith("169.254.") or h == "0.0.0.0":
        return False
    return True


def _safe_zip_segment(s: str, max_len: int = 64) -> str:
    x = re.sub(r"[^a-zA-Z0-9._-]+", "_", (s or "").strip())
    return (x or "x")[:max_len]


def _http_get_bytes(url: str, max_bytes: int) -> tuple[bytes, str]:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "WashproDocumentsExport/1.0"})
    out = bytearray()
    with urllib.request.urlopen(req, timeout=45) as resp:  # noqa: S310
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            out.extend(chunk)
            if len(out) > max_bytes:
                raise ValueError("response too large")
    return bytes(out), ctype


def build_document_records_export_zip(
    records: list[dict],
    *,
    max_files: int = 100,
    max_total_zip: int = 95 * 1024 * 1024,
    max_per_file: int = 25 * 1024 * 1024,
) -> bytes:
    """
    Build a ZIP of remote files referenced by document rows (file_uri + metadata evidence_uri).
    URLs must be http(s), not loopback/private literal hostnames.
    """
    manifest_lines: list[str] = []
    buf = BytesIO()
    total_zip = 0
    n_added = 0
    used_names: set[str] = set()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rec in records:
            rid = rec.get("id")
            uid = rec.get("user_id")
            code = _safe_zip_segment(str(rec.get("document_code") or "doc"))
            base = f"u{uid}_r{rid}_{code}"
            urls: list[tuple[str, str]] = []
            fu = _s(rec.get("file_uri") or "").strip()
            if fu:
                urls.append((fu, "file"))
            meta = _load_metadata_dict(rec.get("metadata_json"))
            eu = _s(meta.get("evidence_uri") or "").strip()
            if eu and eu != fu:
                urls.append((eu, "evidence"))
            for url, kind in urls:
                if n_added >= max_files:
                    manifest_lines.append(f"skip record {rid}: max_files ({max_files})")
                    break
                if not _export_http_url_allowed(url):
                    manifest_lines.append(f"skip record {rid} ({kind}): URL not allowed")
                    continue
                try:
                    data, ctype = _http_get_bytes(url, max_per_file)
                except Exception as e:
                    manifest_lines.append(f"skip record {rid} ({kind}): fetch failed ({e})")
                    continue
                if total_zip + len(data) > max_total_zip:
                    manifest_lines.append("skip: total zip size cap reached")
                    break
                ext = ".bin"
                cl = ctype.lower()
                if "pdf" in cl:
                    ext = ".pdf"
                elif "jpeg" in cl or "jpg" in cl:
                    ext = ".jpg"
                elif "png" in cl:
                    ext = ".png"
                elif "webp" in cl:
                    ext = ".webp"
                inner = f"{base}_{kind}{ext}"
                c = 0
                while inner in used_names:
                    c += 1
                    inner = f"{base}_{kind}_{c}{ext}"
                used_names.add(inner)
                zf.writestr(inner, data)
                total_zip += len(data)
                n_added += 1
            if total_zip >= max_total_zip or n_added >= max_files:
                break
        manifest_lines.insert(0, f"files_in_archive: {n_added}")
        zf.writestr("EXPORT_MANIFEST.txt", "\n".join(manifest_lines).encode("utf-8"))
    return buf.getvalue()


def upsert_generated_hr_form_record(
    conn,
    organization_id: int,
    user_id: int,
    actor_user_id: int,
    *,
    document_code: str,
    document_name: str,
    form_locale: Optional[str],
    download_filename: str,
) -> None:
    """Ensure a generated document row exists / is refreshed after hub PDF download."""
    ensure_document_compliance_tables(conn.cursor())
    code = _s(document_code).upper()[:80]
    if not code:
        return
    name = _s(document_name)[:255] or code
    loc_raw = _s(form_locale)[:16] if form_locale else ""
    loc = loc_raw or None
    fn = _s(download_filename)[:255] or "download.pdf"
    now_iso = datetime.now(timezone.utc).isoformat()
    base_meta = {"hub_generated": True, "last_hub_download_at": now_iso, "download_filename": fn}
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT id, metadata_json FROM employee_document_records
        WHERE organization_id=%s AND user_id=%s AND document_code=%s
          AND (form_locale <=> %s) AND source_kind='generated'
        ORDER BY id DESC LIMIT 1
        """,
        (int(organization_id), int(user_id), code, loc),
    )
    ex = c.fetchone()
    if ex:
        rid = int(ex["id"])
        prev = _load_metadata_dict(ex.get("metadata_json"))
        prev.update(base_meta)
        update_employee_document_record(conn, organization_id, user_id, rid, {
            "document_name": name,
            "status": "received",
            "issued_on": date.today().isoformat(),
            "metadata_json": prev,
        })
    else:
        create_employee_document_record(conn, organization_id, user_id, int(actor_user_id), {
            "document_code": code,
            "document_name": name,
            "form_locale": loc,
            "source_kind": "generated",
            "status": "received",
            "issued_on": date.today().isoformat(),
            "metadata_json": base_meta,
        })


def create_employee_document_record(
    conn,
    organization_id: int,
    user_id: int,
    actor_user_id: int,
    body: dict,
) -> dict:
    c = conn.cursor()
    ensure_document_compliance_tables(c)
    code = _s(body.get("document_code") or body.get("code")).upper()[:80]
    if not code:
        raise ValueError("document_code is required")
    name = _s(body.get("document_name") or body.get("name"))[:255] or code
    src = _s(body.get("source_kind") or "uploaded").lower()
    if src not in ("uploaded", "generated", "external"):
        src = "uploaded"
    status = _s(body.get("status") or "received").lower()
    if status not in ("pending", "received", "verified", "expired", "rejected"):
        status = "received"
    locale = _s(body.get("form_locale"))[:16] or None
    reminder_days = body.get("reminder_days_before")
    reminder_days = None if reminder_days in (None, "") else max(0, min(int(reminder_days), 365))
    disable = 1 if bool(body.get("disable_profile_on_expiry", False)) else 0
    file_uri = _s(body.get("file_uri"))[:1024] or None
    notes = _s(body.get("notes"))[:4000] or None
    issued_on = body.get("issued_on") or None
    expires_on = body.get("expires_on") or None
    metadata = body.get("metadata_json")
    metadata_json = json.dumps(metadata) if metadata is not None else None
    verified_at = body.get("verified_at") or None
    verified_by = body.get("verified_by_user_id")
    verified_by = int(verified_by) if verified_by not in (None, "") else None
    c.execute(
        """
        INSERT INTO employee_document_records (
          organization_id, user_id, document_code, document_name, form_locale, source_kind, status,
          issued_on, expires_on, reminder_days_before, disable_profile_on_expiry,
          file_uri, notes, metadata_json, verified_by_user_id, verified_at, created_by_user_id
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            int(user_id),
            code,
            name,
            locale,
            src,
            status,
            issued_on,
            expires_on,
            reminder_days,
            disable,
            file_uri,
            notes,
            metadata_json,
            verified_by,
            verified_at,
            int(actor_user_id),
        ),
    )
    rid = c.lastrowid
    conn.commit()
    c2 = conn.cursor(dictionary=True)
    c2.execute("SELECT * FROM employee_document_records WHERE id=%s LIMIT 1", (rid,))
    return json_safe(c2.fetchone() or {})


def update_employee_document_record(
    conn,
    organization_id: int,
    user_id: int,
    record_id: int,
    body: dict,
) -> Optional[dict]:
    c = conn.cursor(dictionary=True)
    ensure_document_compliance_tables(c)
    c.execute(
        "SELECT * FROM employee_document_records WHERE id=%s AND organization_id=%s AND user_id=%s LIMIT 1",
        (int(record_id), int(organization_id), int(user_id)),
    )
    row = c.fetchone()
    if not row:
        return None
    set_parts = []
    vals: list[Any] = []

    def _set(col: str, val):
        set_parts.append(f"{col}=%s")
        vals.append(val)

    if "document_code" in body:
        _set("document_code", _s(body.get("document_code")).upper()[:80])
    if "document_name" in body:
        _set("document_name", _s(body.get("document_name"))[:255])
    if "form_locale" in body:
        _set("form_locale", _s(body.get("form_locale"))[:16] or None)
    if "source_kind" in body:
        src = _s(body.get("source_kind")).lower()
        if src not in ("uploaded", "generated", "external"):
            src = "uploaded"
        _set("source_kind", src)
    if "status" in body:
        st = _s(body.get("status")).lower()
        if st not in ("pending", "received", "verified", "expired", "rejected"):
            st = "received"
        _set("status", st)
    for dcol in ("issued_on", "expires_on", "verified_at"):
        if dcol in body:
            _set(dcol, body.get(dcol) or None)
    if "verified_by_user_id" in body:
        v = body.get("verified_by_user_id")
        _set("verified_by_user_id", int(v) if v not in (None, "") else None)
    if "reminder_days_before" in body:
        v = body.get("reminder_days_before")
        vv = None if v in (None, "") else max(0, min(int(v), 365))
        _set("reminder_days_before", vv)
    if "disable_profile_on_expiry" in body:
        _set("disable_profile_on_expiry", 1 if bool(body.get("disable_profile_on_expiry")) else 0)
    if "file_uri" in body:
        _set("file_uri", _s(body.get("file_uri"))[:1024] or None)
    if "notes" in body:
        _set("notes", _s(body.get("notes"))[:4000] or None)
    if "metadata_json" in body:
        mj = body.get("metadata_json")
        _set("metadata_json", json.dumps(mj) if mj is not None else None)
    if not set_parts:
        return json_safe(row)
    vals.extend([int(record_id), int(organization_id), int(user_id)])
    c2 = conn.cursor()
    c2.execute(
        f"UPDATE employee_document_records SET {', '.join(set_parts)} WHERE id=%s AND organization_id=%s AND user_id=%s",
        tuple(vals),
    )
    conn.commit()
    c.execute(
        "SELECT * FROM employee_document_records WHERE id=%s AND organization_id=%s AND user_id=%s LIMIT 1",
        (int(record_id), int(organization_id), int(user_id)),
    )
    return json_safe(c.fetchone() or {})


def delete_employee_document_record(conn, organization_id: int, user_id: int, record_id: int) -> bool:
    c = conn.cursor()
    ensure_document_compliance_tables(c)
    c.execute(
        "DELETE FROM employee_document_records WHERE id=%s AND organization_id=%s AND user_id=%s",
        (int(record_id), int(organization_id), int(user_id)),
    )
    conn.commit()
    return c.rowcount > 0


def list_expiring_document_records(conn, organization_id: int, days: int = 14, code: Optional[str] = None) -> list[dict]:
    c = conn.cursor(dictionary=True)
    ensure_document_compliance_tables(c)
    d = max(0, min(int(days), 3650))
    code_s = _s(code).upper()
    if code_s:
        c.execute(
            """
            SELECT d.*, pp.first_name, pp.last_name, pp.employee_id
            FROM employee_document_records d
            LEFT JOIN payroll_profiles pp ON pp.user_id = d.user_id
            WHERE d.organization_id=%s
              AND d.document_code=%s
              AND d.expires_on IS NOT NULL
              AND d.expires_on <= DATE_ADD(CURDATE(), INTERVAL %s DAY)
            ORDER BY d.expires_on ASC, d.id DESC
            LIMIT 500
            """,
            (int(organization_id), code_s, d),
        )
    else:
        c.execute(
            """
            SELECT d.*, pp.first_name, pp.last_name, pp.employee_id
            FROM employee_document_records d
            LEFT JOIN payroll_profiles pp ON pp.user_id = d.user_id
            WHERE d.organization_id=%s
              AND d.expires_on IS NOT NULL
              AND d.expires_on <= DATE_ADD(CURDATE(), INTERVAL %s DAY)
            ORDER BY d.expires_on ASC, d.id DESC
            LIMIT 500
            """,
            (int(organization_id), d),
        )
    rows = c.fetchall() or []
    return [json_safe(r) for r in rows]


_REMINDER_META_KEY = "last_compliance_reminder_on"


def _coerce_date_only(val: Any) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = _s(val)
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return _parse_dob(val)


def _user_wants_push_out(conn, user_id: int) -> bool:
    c = conn.cursor(dictionary=True)
    try:
        c.execute(
            "SELECT push_out FROM user_notification_preferences WHERE user_id=%s LIMIT 1",
            (int(user_id),),
        )
    except Exception:
        return True
    row = c.fetchone()
    if not row:
        return True
    return bool(row.get("push_out"))


def _load_metadata_dict(raw: Any) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return {}
        try:
            v = json.loads(raw)
            return dict(v) if isinstance(v, dict) else {}
        except Exception:
            return {}
    return {}


def clock_in_blocked_by_expired_documents(conn, user_id: int, organization_id: int) -> bool:
    """True when org policy requires clock-in compliance and user has past-due documents."""
    pol = get_document_compliance_policy(conn, int(organization_id))
    if not int(pol.get("enforce_on_clock_in") or 0):
        return False
    c = conn.cursor()
    ensure_document_compliance_tables(c)
    c.execute(
        """
        SELECT 1 FROM employee_document_records
        WHERE organization_id=%s AND user_id=%s
          AND expires_on IS NOT NULL AND expires_on < CURDATE()
          AND status IN ('pending','received','verified')
        LIMIT 1
        """,
        (int(organization_id), int(user_id)),
    )
    return c.fetchone() is not None


def _list_organization_ids(conn) -> list[int]:
    c = conn.cursor()
    try:
        c.execute("SELECT id FROM organizations ORDER BY id")
    except Exception:
        return []
    return [int(r[0]) for r in c.fetchall()]


def run_document_compliance_tick(conn, *, dry_run: bool = False) -> dict:
    """
    Batch job: mark expired rows, optionally deactivate payroll_profiles, send reminder pushes.
    Safe to run repeatedly (per-record reminder dedup by date in metadata_json).
    """
    from backend.onesignal_client import external_user_id, send_push_to_external_user_ids

    today = _today_eastern_date()
    today_s = today.isoformat()
    stats = {
        "dry_run": dry_run,
        "organizations_scanned": 0,
        "marked_expired": 0,
        "profiles_deactivated": 0,
        "pushes_sent": 0,
        "pushes_skipped": 0,
        "errors": [],
    }
    web_base = (os.getenv("WEB_APP_BASE") or os.getenv("VITE_WEB_APP_BASE") or "").strip().rstrip("/")

    org_ids = _list_organization_ids(conn)
    stats["organizations_scanned"] = len(org_ids)
    cur = conn.cursor(dictionary=True)
    cur_up = conn.cursor()

    for org_id in org_ids:
        try:
            ensure_document_compliance_tables(cur_up)
            policy = get_document_compliance_policy(conn, org_id)
            org_disable = int(policy.get("disable_profile_on_expiry") or 0)
            push_on = int(policy.get("push_enabled") or 0)
            rem_days = max(1, min(int(policy.get("reminder_days_before") or 14), 365))

            # Reminders first so overdue rows still receive a push the day they roll into expired.
            cur.execute(
                """
                SELECT id, user_id, organization_id, document_code, document_name, status,
                       expires_on, metadata_json
                FROM employee_document_records
                WHERE organization_id=%s
                  AND expires_on IS NOT NULL
                  AND expires_on <= DATE_ADD(CURDATE(), INTERVAL %s DAY)
                  AND status IN ('pending','received','verified')
                ORDER BY expires_on ASC, id
                LIMIT 2000
                """,
                (int(org_id), rem_days),
            )
            window_rows = cur.fetchall() or []

            for row in window_rows:
                if not push_on:
                    stats["pushes_skipped"] += 1
                    continue
                uid = int(row["user_id"])
                if not _user_wants_push_out(conn, uid):
                    stats["pushes_skipped"] += 1
                    continue

                meta = _load_metadata_dict(row.get("metadata_json"))
                if meta.get(_REMINDER_META_KEY) == today_s:
                    stats["pushes_skipped"] += 1
                    continue

                exp = row.get("expires_on")
                if isinstance(exp, datetime):
                    exp_d = exp.date()
                elif isinstance(exp, date):
                    exp_d = exp
                else:
                    exp_d = _coerce_date_only(exp)
                if not exp_d:
                    stats["pushes_skipped"] += 1
                    continue

                doc_label = _s(row.get("document_name")) or _s(row.get("document_code")) or "Document"
                if exp_d < today:
                    title = "Document expired"
                    body = f"{doc_label} expired on {exp_d.isoformat()}. Please update it in HR / compliance."
                else:
                    title = "Document expiring soon"
                    body = f"{doc_label} expires on {exp_d.isoformat()}. Please renew or upload before the deadline."

                eid = external_user_id(int(org_id), uid)
                push_url = None
                if web_base:
                    push_url = f"{web_base}/employees/{uid}/hr"

                if dry_run:
                    stats["pushes_sent"] += 1
                else:
                    ok, err = send_push_to_external_user_ids(
                        [eid],
                        title,
                        body,
                        data={"type": "document_compliance", "record_id": int(row["id"])},
                        url=push_url,
                    )
                    if ok:
                        stats["pushes_sent"] += 1
                        meta[_REMINDER_META_KEY] = today_s
                        cur_up.execute(
                            """
                            UPDATE employee_document_records
                            SET metadata_json=%s
                            WHERE id=%s AND organization_id=%s AND user_id=%s
                            """,
                            (json.dumps(meta), int(row["id"]), int(org_id), uid),
                        )
                    else:
                        stats["errors"].append(f"org={org_id} user={uid} record={row['id']}: {err}")

            cur.execute(
                """
                SELECT id, user_id, organization_id, document_code, document_name, status,
                       expires_on, disable_profile_on_expiry, metadata_json
                FROM employee_document_records
                WHERE organization_id=%s
                  AND expires_on IS NOT NULL
                  AND expires_on < CURDATE()
                  AND status IN ('pending','received','verified')
                ORDER BY id
                LIMIT 2000
                """,
                (int(org_id),),
            )
            overdue = cur.fetchall() or []

            for row in overdue:
                rid = int(row["id"])
                uid = int(row["user_id"])
                rec_disable = int(row.get("disable_profile_on_expiry") or 0)

                if dry_run:
                    stats["marked_expired"] += 1
                else:
                    cur_up.execute(
                        "UPDATE employee_document_records SET status='expired' WHERE id=%s AND organization_id=%s",
                        (rid, int(org_id)),
                    )
                    if cur_up.rowcount:
                        stats["marked_expired"] += 1

                if org_disable or rec_disable:
                    if table_exists(cur_up, "payroll_profiles"):
                        if not dry_run:
                            cur_up.execute(
                                "UPDATE payroll_profiles SET active=0 WHERE user_id=%s AND active=1",
                                (uid,),
                            )
                            if cur_up.rowcount:
                                stats["profiles_deactivated"] += 1
                        else:
                            stats["profiles_deactivated"] += 1
        except Exception as e:
            stats["errors"].append(f"org={org_id}: {e}")

    if not dry_run:
        conn.commit()
    return stats


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
    if existing:
        er = dict(existing)
        _decode_hr_row_json_columns(er)
        if _repair_emergency_contacts_work_json_spill(er):
            cur.execute(
                """
                UPDATE hr_extended_profiles
                SET work_json=%s, emergency_contacts_json=%s, updated_at=NOW()
                WHERE user_id=%s
                """,
                (
                    _json_dumps_db(er.get("work_json")),
                    _json_dumps_db(er.get("emergency_contacts_json")),
                    int(user_id),
                ),
            )
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
            if jc == "work_json":
                merged_json[jc] = _deep_merge_work_json(base, patch)
            else:
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
                params.insert(-1, _json_dumps_db(v))
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
                ins[jc] = _json_dumps_db(v)
        cols = list(ins.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        cur.execute(
            f"INSERT INTO hr_extended_profiles ({', '.join(cols)}) VALUES ({placeholders})",
            tuple(ins[k] for k in cols),
        )
    c.execute("SELECT * FROM hr_extended_profiles WHERE user_id=%s LIMIT 1", (int(user_id),))
    out = c.fetchone()
    return json_safe(_normalize_hr_row(out))


def _normalize_hr_row(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    out = dict(row)
    _decode_hr_row_json_columns(out)
    _repair_emergency_contacts_work_json_spill(out)
    return out


def get_merged_hr_profile(conn, user_id: int, payroll_row: dict) -> dict:
    _cur = conn.cursor()
    ensure_hr_extended_profiles_table(_cur)
    c = conn.cursor(dictionary=True)
    c.execute("SELECT * FROM hr_extended_profiles WHERE user_id=%s LIMIT 1", (int(user_id),))
    hr = c.fetchone()
    pay_pub = {
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
            "washpro_display_name",
            "username",
        )
        if k in payroll_row or k == "user_id"
    }
    mask_tax_id_for_api_response(pay_pub)
    return {
        "payroll": json_safe(pay_pub),
        "hr": json_safe(_normalize_hr_row(hr)),
        "org_settings": json_safe(fetch_hr_org_settings(conn, int(payroll_row.get("organization_id") or 1))),
    }
