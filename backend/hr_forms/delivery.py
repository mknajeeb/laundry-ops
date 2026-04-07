"""
Build HR form inventory for a user and infer W-2 vs 1099 lanes from employment categories.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from backend.hr_forms.registry import get_form_def, list_forms, resolve_form_asset_path


def infer_user_form_lanes(conn, user_id: int) -> list[str]:
    """employee_w2 / contractor_1099 based on active employment category labels."""
    c = conn.cursor(dictionary=True)
    try:
        c.execute(
            """
            SELECT ec.name, ec.code
            FROM user_employment_categories uec
            JOIN employment_categories ec ON ec.id = uec.employment_category_id
            WHERE uec.user_id=%s
              AND uec.effective_from <= CURDATE()
              AND (uec.effective_to IS NULL OR uec.effective_to >= CURDATE())
            """,
            (int(user_id),),
        )
        rows = c.fetchall() or []
    except Exception:
        rows = []
    if not rows:
        return ["employee_w2", "contractor_1099"]
    has_1099 = False
    has_w2 = False
    has_temp = False
    for r in rows:
        blob = f"{r.get('name') or ''} {r.get('code') or ''}".lower()
        if re.search(r"1099|contractor|independent|\bic\b", blob):
            has_1099 = True
        if re.search(r"\btemp\b|temporary|seasonal", blob):
            has_temp = True
        if re.search(r"w[\s-]*2|employee|hourly|salary|washmate|ops", blob):
            has_w2 = True
    out: list[str] = []
    if has_w2:
        out.append("employee_w2")
    if has_1099:
        out.append("contractor_1099")
    if has_temp:
        out.append("temp_worker")
    if not out:
        return ["employee_w2", "contractor_1099"]
    return out


def prefill_supported(form_id: str, locale: str, form_def: dict[str, Any]) -> bool:
    """True when server can merge profile data into this template."""
    if form_def.get("fill_strategy") != "acroform":
        return False
    if form_id == "uscis_i9" and locale in ("en", "es"):
        return True
    return False


def build_hr_forms_inventory(conn, user_id: int) -> dict[str, Any]:
    lanes = infer_user_form_lanes(conn, user_id)
    forms_out: list[dict[str, Any]] = []
    for d in list_forms():
        if d.get("lane") not in lanes:
            continue
        fid = str(d.get("id") or "")
        locale_info: list[dict[str, Any]] = []
        for loc in d.get("locales") or []:
            p = resolve_form_asset_path(fid, loc)
            locale_info.append(
                {
                    "locale": loc,
                    "available": p is not None,
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
                "locales": locale_info,
            }
        )
    return {"lanes_detected": lanes, "forms": forms_out}
