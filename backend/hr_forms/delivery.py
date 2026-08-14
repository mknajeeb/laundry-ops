"""
Build HR form inventory for a user and infer W-2 vs 1099 lanes from employment categories.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from backend.hr_forms.registry import get_form_def, list_forms, resolve_form_asset_path


def infer_user_form_lanes(conn, user_id: int) -> list[str]:
    """employee_w2 / contractor_1099 / temp_worker / tryout from current assignments.

    Avoid treating "Washmate 1099"–style rows as both W-2 and 1099. With no assignment
    rows, default to W-2 only (safest single packet); set a category for contractors.
    Try Out is never classified as W-2 or 1099.
    """
    from backend.payroll_worker_categories import classify_employment_category
    from backend.portal_system_users import is_portal_system_user

    if is_portal_system_user(conn, int(user_id)):
        return []
    c = conn.cursor(dictionary=True)
    try:
        c.execute(
            """
            SELECT ec.name, ec.code
            FROM user_employment_categories uec
            JOIN employment_categories ec ON ec.id = uec.employment_category_id
            WHERE uec.user_id=%s
              AND (uec.effective_from IS NULL OR uec.effective_from <= CURDATE())
              AND (uec.effective_to IS NULL OR uec.effective_to >= CURDATE())
            """,
            (int(user_id),),
        )
        rows = c.fetchall() or []
    except Exception:
        rows = []
    if not rows:
        return ["employee_w2"]
    kinds = [
        classify_employment_category(r.get("code"), r.get("name")) for r in rows
    ]
    if "system" in kinds:
        return []
    out: list[str] = []
    if "w2" in kinds:
        out.append("employee_w2")
    if "contractor_1099" in kinds:
        out.append("contractor_1099")
    if "temp" in kinds:
        out.append("temp_worker")
    if "tryout" in kinds:
        out.append("tryout")
    if not out:
        return ["employee_w2"]
    return out


def form_matches_tax_year(form_def: dict[str, Any]) -> bool:
    """If HR_FORMS_TAX_YEAR is set, hide forms whose catalog tax_year differs (year-specific PDFs)."""
    env = (os.environ.get("HR_FORMS_TAX_YEAR") or "").strip()
    if not env:
        return True
    fy = form_def.get("tax_year")
    if fy is None or fy == "":
        return True
    return str(fy) == env


def prefill_supported(form_id: str, locale: str, form_def: dict[str, Any]) -> bool:
    """True when server can merge profile data into this template."""
    if form_def.get("fill_strategy") != "acroform":
        return False
    if form_id == "uscis_i9" and locale in ("en", "es"):
        return True
    if form_id in ("irs_w4", "irs_w9") and locale in ("en", "es"):
        return True
    if form_id == "ny_it2104" and locale == "en":
        return True
    return False


def build_hr_forms_inventory(conn, user_id: int) -> dict[str, Any]:
    lanes = infer_user_form_lanes(conn, user_id)
    forms_out: list[dict[str, Any]] = []
    for d in list_forms():
        if not form_matches_tax_year(d):
            continue
        if d.get("lane") not in lanes:
            continue
        fid = str(d.get("id") or "")
        locale_info: list[dict[str, Any]] = []
        for loc in d.get("locales") or []:
            p = resolve_form_asset_path(fid, loc)
            available = p is not None or d.get("fill_strategy") in ("docx_template", "reference_pdf")
            locale_info.append(
                {
                    "locale": loc,
                    "available": available,
                    "prefill_supported": prefill_supported(fid, loc, d),
                }
            )
        if not any(x["available"] for x in locale_info):
            continue
        forms_out.append(
            {
                "id": fid,
                "title": d.get("title") or fid,
                "lane": d.get("lane"),
                "kind": d.get("kind"),
                "fill_strategy": d.get("fill_strategy"),
                "tax_year": d.get("tax_year"),
                "locales": locale_info,
            }
        )
    env_ty = (os.environ.get("HR_FORMS_TAX_YEAR") or "").strip()
    return {
        "lanes_detected": lanes,
        "forms": forms_out,
        "tax_year_filter": env_ty or None,
    }
