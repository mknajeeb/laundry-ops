"""Shared AcroForm fill for IRS and other official PDFs (pypdf)."""

from __future__ import annotations

import json
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Optional


def _acroform_text_field_default_appearance_size_pt() -> float:
    raw = (os.environ.get("HR_PDF_FIELD_FONT_PT") or "9").strip()
    try:
        v = float(raw)
        return max(5.0, min(v, 14.0))
    except ValueError:
        return 8.0


def _acroform_text_field_use_bold() -> bool:
    raw = (os.environ.get("HR_PDF_FIELD_FONT_BOLD") or "0").strip().lower()
    return raw not in ("0", "false", "no")


def _acroform_tx_base_font_name() -> str:
    """
    Base-14 font for /DA on AcroForm text fields.
    HR_PDF_FIELD_FONT: times (default), helvetica, courier — matches common government PDF body text.
    """
    raw = (os.environ.get("HR_PDF_FIELD_FONT") or "times").strip().lower()
    bold = _acroform_text_field_use_bold()
    if raw in ("helvetica", "helv", "arial", "sans"):
        return "/Helvetica-Bold" if bold else "/Helvetica"
    if raw in ("courier", "mono", "cour"):
        return "/Courier-Bold" if bold else "/Courier"
    return "/Times-Bold" if bold else "/Times-Roman"


def apply_acroform_compact_text_font(writer: Any) -> None:
    """
    Best-effort: set /DA on each /Tx widget so regenerated values match the template’s body style.
    HR_PDF_FIELD_FONT_PT (default 9), HR_PDF_FIELD_FONT (default times), HR_PDF_FIELD_FONT_BOLD (default 0).
    Only /Tx fields — checkboxes (/Btn) unchanged.
    """
    try:
        from pypdf.generic import NameObject, TextStringObject
    except ImportError:
        return
    pt = _acroform_text_field_default_appearance_size_pt()
    sz = int(pt) if abs(pt - round(pt)) < 1e-6 else pt
    font = _acroform_tx_base_font_name()
    da = TextStringObject(f"{font} {sz} Tf 0 g")
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
            try:
                annot[NameObject("/DA")] = da
            except Exception:
                continue


def expand_acroform_field_name_aliases(field_values: dict[str, str]) -> dict[str, str]:
    """
    pypdf matches either the fully qualified field name or the widget /T (short) name.
    Duplicate values under short keys (e.g. f1_08[0]) so updates still apply if paths differ.
    """
    out = dict(field_values)
    for k, v in field_values.items():
        if "." not in k:
            continue
        leaf = k.rsplit(".", 1)[-1]
        if leaf and leaf not in out:
            out[leaf] = v
    return out


def fill_acroform_pdf_bytes(
    template_path: str,
    field_values: dict[str, str],
    *,
    max_pages: int = 0,
) -> bytes:
    """Fill PDF AcroForm fields. max_pages=0 keeps all pages."""
    try:
        from pypdf import PdfReader, PdfWriter
    except ModuleNotFoundError as e:
        import sys

        raise RuntimeError(
            "Missing dependency 'pypdf'. Install with the same Python you use to run the app "
            f"(e.g. `{sys.executable} -m pip install pypdf`)."
        ) from e

    raw = Path(template_path).read_bytes()
    reader = PdfReader(BytesIO(raw))
    writer = PdfWriter()
    n = len(reader.pages)
    mp = int((os.environ.get("HR_PDF_MAX_PAGES") or str(max_pages)).strip() or "0")
    if mp > 0 and n > mp:
        writer.append(reader, pages=list(range(min(mp, n))))
    else:
        # Preserves AcroForm/page widget linkage better than append() for many IRS PDFs.
        writer.clone_document_from_reader(reader)
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
    raw_flat = (os.environ.get("HR_PDF_FLATTEN") or "0").strip().lower()
    flatten = raw_flat not in ("0", "false", "no")
    apply_acroform_compact_text_font(writer)
    vals = expand_acroform_field_name_aliases(field_values)
    for page in writer.pages:
        writer.update_page_form_field_values(page, vals, auto_regenerate=True, flatten=flatten)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def work_json_from_hr_row(hr: dict | None) -> dict:
    """Parse hr_extended_profiles.work_json — same rules as API _normalize_hr_row, plus raw fallbacks."""
    if not hr:
        return {}
    try:
        from backend.hr_compliance import _normalize_hr_row

        row = _normalize_hr_row(dict(hr))
        if row:
            wj = row.get("work_json")
            if isinstance(wj, dict):
                return wj
    except Exception:
        pass
    wj = hr.get("work_json")
    if wj is None:
        return {}
    if isinstance(wj, dict):
        return wj
    if isinstance(wj, (bytes, bytearray)):
        try:
            wj = wj.decode("utf-8")
        except Exception:
            return {}
    if isinstance(wj, str):
        s = wj.strip()
        if not s:
            return {}
        try:
            o = json.loads(s)
            return o if isinstance(o, dict) else {}
        except Exception:
            return {}
    return {}


def _s(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _maybe_json_dict(v: Any) -> dict:
    """Accept dict or JSON string (some DB/clients stringify nested objects)."""
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v.strip():
        try:
            o = json.loads(v)
            return o if isinstance(o, dict) else {}
        except Exception:
            return {}
    return {}


def _coerce_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    t = _s(v).lower()
    if t in ("true", "1", "yes", "y", "on"):
        return True
    if t in ("false", "0", "no", "n", "off", ""):
        return False
    return bool(v)


def _split_display_name(display: str) -> tuple[str, str]:
    parts = _s(display).split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], " ".join(parts[1:])


def _nested_i9_block(work: dict) -> dict:
    i9 = work.get("i9")
    if isinstance(i9, str):
        try:
            i9 = json.loads(i9)
        except Exception:
            i9 = {}
    return i9 if isinstance(i9, dict) else {}


def _resolve_w4_w9_names(payroll_row: dict, hr_row: dict | None, work: dict) -> tuple[str, str]:
    """Same precedence as I-9 legal names: i9.legal_* > preferred_name > payroll > Washpro display."""
    i9 = _nested_i9_block(work)
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
    if fn and ln and fn.lower() != ln.lower():
        return fn, ln

    disp = _s(payroll_row.get("washpro_display_name"))
    if disp:
        return _split_display_name(disp)

    if fn or ln:
        return fn or ln, ln or fn

    return "", ""


def _w4_w9_ssn_digits(payroll_row: dict, work: dict) -> str:
    i9 = _nested_i9_block(work)
    raw = _s(i9.get("ssn") or payroll_row.get("itin_ssn"))
    return re.sub(r"\D", "", raw)[:9]


def _parse_payroll_address_blob(text: str) -> dict[str, str]:
    """Split payroll_profiles.address free text into street / city / state / zip (no hr_compliance import — avoids cycles)."""
    t = _s(text)
    if not t:
        return {}
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    out: dict[str, str] = {}
    if len(lines) == 1:
        one = lines[0]
        m = re.match(
            r"^(.+),\s*(.+?)\s+([A-Za-z]{2})\s+(\d{5}(?:-\d{4})?)\s*$",
            one,
        )
        if m:
            out["address_line1"] = m.group(1).strip()
            out["city"] = m.group(2).strip()
            out["state"] = m.group(3).upper()
            out["zip"] = m.group(4)
            return out
    if lines:
        out["address_line1"] = lines[0]
    if len(lines) >= 2:
        last = lines[-1]
        m = re.match(r"^([^,]+),\s*([A-Za-z]{2})\s*(\d{5}(?:-\d{4})?)$", last)
        if m:
            out["city"] = m.group(1).strip()
            out["state"] = m.group(2).upper()
            out["zip"] = m.group(3)
        else:
            out["address_line2"] = last
    return out


def merged_mailing_for_forms(work: dict, payroll_row: dict) -> dict:
    """Prefer structured work_json; fill gaps from payroll address blob so W-4/W-9/IT-2104 prefill matches payroll tab."""
    base = dict(work) if isinstance(work, dict) else {}
    parsed = _parse_payroll_address_blob(_s(payroll_row.get("address")))
    a1 = _s(base.get("address_line1") or base.get("mailing_address_line1"))
    if not a1 and parsed.get("address_line1"):
        base["address_line1"] = parsed["address_line1"]
        base.setdefault("mailing_address_line1", parsed["address_line1"])
    if not _s(base.get("city")) and parsed.get("city"):
        base["city"] = parsed["city"]
    if not _s(base.get("state")) and parsed.get("state"):
        base["state"] = parsed["state"]
    z = _s(base.get("zip") or base.get("zip_code"))
    if not z and parsed.get("zip"):
        base["zip"] = parsed["zip"]
    return base


def _w4_step1_prefix_from_pdf(field_keys: list[str], locale: str) -> Optional[str]:
    """Find AcroForm path for W-4 Step 1 name fields (IRS editions vary: Step1a vs Step1)."""
    suffix = ".f1_01[0]"
    if locale == "es":
        subforms = ("Paso1a", "Paso1", "Step1a", "Step1")
    else:
        subforms = ("Step1a", "Step1", "Paso1a", "Paso1")
    for sub in subforms:
        needle = f".Page1[0].{sub}[0]{suffix}"
        for k in field_keys:
            if k.endswith(needle):
                return k[: -len(suffix)]
    return None


def _w4_ssn_key_from_pdf(field_keys: list[str]) -> Optional[str]:
    for k in field_keys:
        if k.endswith("Page1[0].f1_05[0]"):
            return k
    return None


def _w4_pdf_key(field_keys: list[str], leaf: str) -> Optional[str]:
    """Resolve full AcroForm name; `leaf` is e.g. 'c1_1[0]' or 'f1_08[0]'."""
    for k in field_keys:
        if k.endswith(f".{leaf}") or k.endswith(leaf):
            return k
    return None


_W4_P1 = "topmostSubform[0].Page1[0]"
_W4_P3 = "topmostSubform[0].Page3[0]"


def _w4_builtin_full_key(locale: str, leaf: str) -> Optional[str]:
    """
    Full field names for IRS W-4 2026 AcroForm (bundled ``irs_w4_en.pdf`` / ``irs_w4_es.pdf``).

    Used when ``PdfReader.get_fields()`` returns nothing (some pypdf/OS paths) so Step1 can
    still be filled from hardcoded paths while checkboxes / Step3–4 were accidentally skipped.
    """
    es = locale == "es"
    p1_leaf = f"{_W4_P1}.{leaf}"
    if leaf in ("c1_1[0]", "c1_1[1]", "c1_1[2]", "c1_2[0]", "c1_3[0]"):
        return p1_leaf
    if leaf == "f1_06[0]":
        sub = "Paso3_ReadOrder[0]" if es else "Step3_ReadOrder[0]"
        return f"{_W4_P1}.{sub}.f1_06[0]"
    if leaf == "f1_07[0]":
        if es:
            return f"{_W4_P1}.f1_07[0]"
        return f"{_W4_P1}.Step3_ReadOrder[0].f1_07[0]"
    if leaf in (
        "f1_08[0]",
        "f1_09[0]",
        "f1_10[0]",
        "f1_11[0]",
        "f1_12[0]",
        "f1_13[0]",
        "f1_14[0]",
    ):
        return p1_leaf
    if leaf.startswith("f3_") and leaf.endswith("[0]"):
        return f"{_W4_P3}.{leaf}"
    return None


def _w4_ssn_formatted(digits9: str) -> str:
    d = re.sub(r"\D", "", digits9)
    if len(d) != 9:
        return ""
    return f"{d[:3]}-{d[3:5]}-{d[5:9]}"


def _w4_sum_money_amounts(*parts: Any) -> str:
    t = 0.0
    for p in parts:
        m = _w4_money_amount(p)
        if not m:
            continue
        try:
            t += float(m.replace(",", ""))
        except ValueError:
            return ""
    if abs(t - round(t)) < 1e-9:
        return str(int(round(t)))
    return f"{t:.2f}".rstrip("0").rstrip(".")


def _w4_money_amount(s: Any) -> str:
    """Strip currency symbols/spaces; keep a reasonable decimal string for PDF dollar lines."""
    raw = _s(s)
    if not raw:
        return ""
    t = re.sub(r"[\$,]", "", raw).strip()
    if not t:
        return ""
    try:
        v = float(t)
        if abs(v - round(v)) < 1e-9:
            return str(int(round(v)))
        return f"{v:.2f}".rstrip("0").rstrip(".")
    except ValueError:
        return t


def _w4_hire_date_mmddyyyy(payroll_row: dict) -> str:
    raw = payroll_row.get("hire_date")
    if raw is None:
        return ""
    if hasattr(raw, "year") and hasattr(raw, "month"):
        return f"{int(raw.month):02d}/{int(raw.day):02d}/{int(raw.year)}"
    s = _s(str(raw))
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        return f"{mo}/{d}/{y}"
    m2 = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m2:
        mo, d, y = int(m2.group(1)), int(m2.group(2)), m2.group(3)
        return f"{mo:02d}/{d:02d}/{y}"
    return s[:20]


def _w4_ein_formatted(s: Any) -> str:
    d = re.sub(r"\D", "", _s(s))
    if len(d) == 9:
        return f"{d[:2]}-{d[2:]}"
    return _s(s)[:20]


def _w4_effective_compliance(work: dict) -> dict:
    """
    Resolve W-4 withholding choices from work_json regardless of minor shape drift.
    Tries: w4.compliance, flat keys on w4, top-level w4Compliance / w4_compliance, alternate casing.
    """
    if not isinstance(work, dict):
        return {}
    w4 = _maybe_json_dict(work.get("w4") or work.get("W4"))
    c = _maybe_json_dict(w4.get("compliance"))
    if c:
        return c
    # Compliance fields stored directly under w4 (mis-merge / legacy)
    if any(
        k in w4
        for k in (
            "filing_status",
            "exempt",
            "two_jobs_only",
            "step2_multiple_jobs",
            "is_nonresident_alien",
            "nra_allow_step3_4",
            "dependents_amount",
            "step3a_amount",
            "step3b_amount",
            "step3_other_credits_amount",
            "other_income",
            "deductions",
            "extra_withholding",
        )
    ):
        return dict(w4)
    top = _maybe_json_dict(work.get("w4_compliance") or work.get("w4Compliance"))
    if top:
        return top
    return {}


def _w4_normalized_filing_status(raw: Any, *, is_nra: bool) -> str:
    """
    Canonical W-4 Step 1(c) keys for IRS PDF (three mutually exclusive boxes):
    single_or_mfs | mfj_or_qss | hoh
    """
    if is_nra:
        return "single_or_mfs"
    s = _s(str(raw)).lower().replace(" ", "_").replace("-", "_")
    if not s:
        return ""
    direct = {"single_or_mfs", "mfj_or_qss", "hoh"}
    if s in direct:
        return s
    legacy = {
        "single": "single_or_mfs",
        "married_separate": "single_or_mfs",
        "s": "single_or_mfs",
        "married_joint": "mfj_or_qss",
        "married_filing_jointly": "mfj_or_qss",
        "head": "hoh",
        "head_of_household": "hoh",
        "nonresident": "single_or_mfs",
        "nonresident_alien": "single_or_mfs",
        "nra": "single_or_mfs",
    }
    if s in legacy:
        return legacy[s]
    if "married" in s and ("joint" in s or "jointly" in s):
        return "mfj_or_qss"
    if "head" in s:
        return "hoh"
    if "nonresident" in s or "nra" == s:
        return "single_or_mfs"
    if "married" in s and ("separate" in s or "separately" in s):
        return "single_or_mfs"
    if s in ("single", "mfj", "mfs"):
        return "single_or_mfs" if s != "mfj" else "mfj_or_qss"
    return ""


def _w4_employer_address_lines(org: dict) -> tuple[str, str, str, str]:
    """Split org employer address into up to three lines for PDF spill (f3_02–f3_04)."""
    name = _s(org.get("employer_name"))
    blob = _s(org.get("employer_address"))
    if not blob:
        return name, "", "", ""
    lines = [ln.strip() for ln in blob.splitlines() if ln.strip()]
    if not lines:
        return name, "", "", ""
    if len(lines) == 1:
        parsed = _parse_payroll_address_blob(lines[0])
        if parsed.get("address_line1"):
            csz = ", ".join(
                [
                    x
                    for x in (
                        parsed.get("city"),
                        f"{parsed.get('state', '')} {parsed.get('zip', '')}".strip(),
                    )
                    if x
                ]
            )
            return name, parsed.get("address_line1", ""), "", csz
        return name, lines[0], "", ""
    return name, lines[0], lines[1], ", ".join(lines[2:]) if len(lines) > 2 else ""


def build_irs_w4_field_values(
    payroll_row: dict,
    hr_row: dict | None,
    work: dict,
    locale: str = "en",
    *,
    template_path: Optional[str] = None,
    org: Optional[dict] = None,
) -> dict[str, str]:
    """Map payroll + work_json + org settings to IRS W-4 AcroForm (Step 1, compliance, employer block).

    Step 1 (name, address, SSN) is always attempted from profile / I-9 legal / payroll.
    Filing status, Step 2(c), exempt, Step 3–4 dollar lines come from ``work["w4"]["compliance"]`` when present.
    Employer-only fields (page 3) use ``org`` (employer_name, employer_address, employer_ein) and payroll hire_date.
    ``work["w4"]["acroform"]`` still supplies explicit PDF key overrides (last wins).
    """
    work = merged_mailing_for_forms(work, payroll_row)
    fn, ln = _resolve_w4_w9_names(payroll_row, hr_row, work)
    mi = _s(work.get("middle_initial"))[:1]
    addr1 = _s(work.get("address_line1") or work.get("mailing_address_line1") or payroll_row.get("address"))
    city = _s(work.get("city"))
    st = _s(work.get("state"))
    z = _s(work.get("zip") or work.get("zip_code"))
    line1 = f"{fn} {mi}".strip() if mi else fn
    csz = ", ".join([x for x in (city, f"{st} {z}".strip()) if x])
    ssn = _w4_w9_ssn_digits(payroll_row, work)

    field_keys: list[str] = []
    if template_path:
        try:
            from pypdf import PdfReader

            field_keys = list((PdfReader(template_path).get_fields() or {}).keys())
        except Exception:
            field_keys = []
        if not field_keys:
            try:
                raw = Path(template_path).read_bytes()
                field_keys = list((PdfReader(BytesIO(raw)).get_fields() or {}).keys())
            except Exception:
                field_keys = []

    base = _w4_step1_prefix_from_pdf(field_keys, locale) if field_keys else None
    if not base:
        step = "Paso1a" if locale == "es" else "Step1a"
        base = f"topmostSubform[0].Page1[0].{step}[0]"

    ssn_key = _w4_ssn_key_from_pdf(field_keys) if field_keys else None
    if not ssn_key:
        ssn_key = "topmostSubform[0].Page1[0].f1_05[0]"

    out: dict[str, str] = {
        f"{base}.f1_01[0]": line1,
        f"{base}.f1_02[0]": ln,
        f"{base}.f1_03[0]": addr1,
        f"{base}.f1_04[0]": csz,
    }
    if len(ssn) == 9:
        out[ssn_key] = _w4_ssn_formatted(ssn)

    w4 = _maybe_json_dict(work.get("w4") or work.get("W4"))
    comp = _w4_effective_compliance(work)

    def pk(leaf: str) -> Optional[str]:
        found = _w4_pdf_key(field_keys, leaf) if field_keys else None
        return found or _w4_builtin_full_key(locale, leaf)

    exempt = _coerce_bool(comp.get("exempt"))
    is_nra = _coerce_bool(
        comp.get("is_nonresident_alien")
        or comp.get("nonresident_alien")
        or comp.get("nonresident")
    )
    if is_nra:
        exempt = False
    nra_allow_34 = _coerce_bool(comp.get("nra_allow_step3_4"))
    fs = _w4_normalized_filing_status(comp.get("filing_status"), is_nra=is_nra)

    c10 = pk("c1_1[0]")
    c11 = pk("c1_1[1]")
    c12 = pk("c1_1[2]")
    if c10 and c11 and c12:
        if fs == "single_or_mfs":
            out[c10], out[c11], out[c12] = "/1", "/Off", "/Off"
        elif fs == "mfj_or_qss":
            out[c10], out[c11], out[c12] = "/Off", "/2", "/Off"
        elif fs == "hoh":
            out[c10], out[c11], out[c12] = "/Off", "/Off", "/3"
        else:
            out[c10], out[c11], out[c12] = "/Off", "/Off", "/Off"

    c13 = pk("c1_3[0]")
    if c13:
        out[c13] = "/1" if exempt else "/Off"

    mult = _s(comp.get("step2_multiple_jobs") or comp.get("step2MultipleJobs")).lower()
    two_ok = _coerce_bool(comp.get("two_jobs_only") or comp.get("twoJobsOnly"))
    if mult == "no":
        step2c_checked = False
    elif exempt:
        step2c_checked = False
    else:
        step2c_checked = two_ok and (mult == "yes" or mult == "")

    c22 = pk("c1_2[0]")
    if c22:
        out[c22] = "/1" if step2c_checked else "/Off"

    k06 = pk("f1_06[0]")
    k07 = pk("f1_07[0]")
    k08 = pk("f1_08[0]")
    k09, k10, k11 = pk("f1_09[0]"), pk("f1_10[0]"), pk("f1_11[0]")

    block_steps_34 = exempt or (is_nra and not nra_allow_34)
    s3a = _w4_money_amount(
        comp.get("step3a_amount") or comp.get("step3aAmount") or comp.get("step_3a")
    )
    s3b = _w4_money_amount(
        comp.get("step3b_amount") or comp.get("step3bAmount") or comp.get("step_3b")
    )
    s3o = _w4_money_amount(
        comp.get("step3_other_credits_amount") or comp.get("step3OtherCreditsAmount")
    )
    manual_total = _w4_money_amount(
        comp.get("dependents_amount")
        or comp.get("dependentsAmount")
        or comp.get("line_3_total")
        or comp.get("step3_total_amount")
    )
    dep_auto = _w4_sum_money_amounts(s3a, s3b, s3o)
    dep_total = manual_total if manual_total else dep_auto

    if not block_steps_34:
        if k06 and s3a:
            out[k06] = s3a
        if k07 and s3b:
            out[k07] = s3b
        if k08 and dep_total:
            out[k08] = dep_total
        if k09:
            v = _w4_money_amount(comp.get("other_income") or comp.get("otherIncome") or comp.get("line_4a"))
            if v:
                out[k09] = v
        if k10:
            v = _w4_money_amount(comp.get("deductions") or comp.get("line_4b"))
            if v:
                out[k10] = v
        if k11:
            v = _w4_money_amount(
                comp.get("extra_withholding") or comp.get("extraWithholding") or comp.get("line_4c")
            )
            if v:
                out[k11] = v
    else:
        for kk in (k06, k07, k08, k09, k10, k11):
            if kk:
                out[kk] = ""

    # Nonresident status is stored in HR/work_json for payroll — do not write NRA text into 4(c);
    # that field is only for extra withholding dollars and appending text overlaps amounts in viewers.

    # Employers only (page 3): name, address lines, first date of employment, EIN (spill into f3_01–f3_06).
    if org and isinstance(org, dict):
        ename, el1, el2, elrest = _w4_employer_address_lines(org)
        hire = _w4_hire_date_mmddyyyy(payroll_row)
        ein = _w4_ein_formatted(org.get("employer_ein"))
        pairs = [
            (pk("f3_01[0]"), ename),
            (pk("f3_02[0]"), el1),
            (pk("f3_03[0]"), el2),
            (pk("f3_04[0]"), elrest),
            (pk("f3_05[0]"), hire),
            (pk("f3_06[0]"), ein),
        ]
        for kk, val in pairs:
            if kk and _s(val):
                out[kk] = _s(val)

    acr = w4.get("acroform")
    if isinstance(acr, dict):
        for k, v in acr.items():
            s = _s(v)
            if s:
                out[str(k)] = s
    return {k: v for k, v in out.items() if v is not None}


def build_irs_w9_field_values(
    payroll_row: dict,
    work: dict,
    locale: str = "en",
    *,
    hr_row: dict | None = None,
) -> dict[str, str]:
    """W-9 — name, address, SSN. EN vs ES use different subform paths (IRS)."""
    work = merged_mailing_for_forms(work, payroll_row)
    fn, ln = _resolve_w4_w9_names(payroll_row, hr_row, work)
    name = f"{fn} {ln}".strip()
    addr = _s(work.get("address_line1") or payroll_row.get("address"))
    city = _s(work.get("city"))
    st = _s(work.get("state"))
    z = _s(work.get("zip") or work.get("zip_code"))
    line_city = ", ".join([x for x in (city, f"{st} {z}".strip()) if x])
    tin = _w4_w9_ssn_digits(payroll_row, work)
    if locale == "es":
        out = {
            "topmostSubform[0].Page1[0].f1_1[0]": name,
            "topmostSubform[0].Page1[0].Line5-6_ReadOrder[0].f1_7[0]": addr,
            "topmostSubform[0].Page1[0].Line5-6_ReadOrder[0].f1_8[0]": line_city,
        }
        if len(tin) == 9:
            out["topmostSubform[0].Page1[0].SSN[0].f1_11[0]"] = tin[:3]
            out["topmostSubform[0].Page1[0].SSN[0].f1_12[0]"] = tin[3:5]
            out["topmostSubform[0].Page1[0].SSN[0].f1_13[0]"] = tin[5:9]
    else:
        out = {
            "topmostSubform[0].Page1[0].f1_01[0]": name,
            "topmostSubform[0].Page1[0].Address_ReadOrder[0].f1_07[0]": addr,
            "topmostSubform[0].Page1[0].Address_ReadOrder[0].f1_08[0]": line_city,
        }
        if len(tin) == 9:
            # Rev. March 2024 EN: SSN is three widgets f1_11 / f1_12 / f1_13 on Page1 (3 + 2 + 4 digits).
            out["topmostSubform[0].Page1[0].f1_11[0]"] = tin[:3]
            out["topmostSubform[0].Page1[0].f1_12[0]"] = tin[3:5]
            out["topmostSubform[0].Page1[0].f1_13[0]"] = tin[5:9]
    return {k: v for k, v in out.items() if v}


def build_ny_it2104_field_values(payroll_row: dict, work: dict, *, hr_row: dict | None = None) -> dict[str, str]:
    """NY IT-2104 common prefill fields (name/address/SSN/sign date)."""
    work = merged_mailing_for_forms(work, payroll_row)
    fn, ln = _resolve_w4_w9_names(payroll_row, hr_row, work)
    mi = _s(work.get("middle_initial"))[:1]
    first_with_mi = f"{fn} {mi}".strip() if mi else fn
    addr = _s(work.get("address_line1") or work.get("mailing_address_line1") or payroll_row.get("address"))
    apt = _s(work.get("address_line2") or work.get("apt_number"))
    city = _s(work.get("city"))
    st = _s(work.get("state"))
    z = _s(work.get("zip") or work.get("zip_code"))
    ssn = _w4_w9_ssn_digits(payroll_row, work)
    from datetime import date

    today = date.today().isoformat()
    out: dict[str, str] = {
        "First name and middle initial": first_with_mi,
        "Last name": ln,
        "Permanent mailing address": addr,
        "Apartment number": apt,
        "City, village or post office": city,
        "State": st,
        "ZIP code": z,
        "Date": today,
    }
    if len(ssn) == 9:
        out["Your SSN"] = ssn
    ny = work.get("ny_it2104")
    if isinstance(ny, dict):
        # direct field overrides/support for richer capture by UI
        for key in (
            "Status",
            "Resident",
            "Resident of Yonkers",
            "line 1",
            "line 2",
            "line 3",
            "line 4",
            "line 5",
            "employee is a new hire",
            "employee claims more than 14 exemption",
        ):
            s = _s(ny.get(key))
            if s:
                out[key] = s
        acr = ny.get("acroform")
        if isinstance(acr, dict):
            for k, v in acr.items():
                s = _s(v)
                if s:
                    out[str(k)] = s
    return {k: v for k, v in out.items() if v}
