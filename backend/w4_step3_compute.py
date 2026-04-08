"""Apply tax-year W-4 Step 3 auto-calculation and audit fields before persisting work_json."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from backend.tax_form_year_settings import fetch_w4_year_settings


def _bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if v in (None, "", 0):
        return False
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "on")


def _intish(v: Any) -> int:
    if v is None or v == "":
        return 0
    try:
        return max(0, int(float(str(v).strip())))
    except (ValueError, TypeError):
        return 0


def _money_dec(v: Any) -> Decimal:
    if v is None or v == "":
        return Decimal("0")
    s = str(v).strip().replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0")


def _fmt_money(d: Decimal) -> str:
    if d == d.to_integral():
        return str(int(d))
    return format(d.normalize(), "f").rstrip("0").rstrip(".")


def apply_w4_compliance_step3(
    conn,
    organization_id: int,
    compliance: dict[str, Any],
    acting_user_id: int,
) -> dict[str, Any]:
    """
    Mutates a copy of w4.compliance: fills step3a/b/total from counts + tax-year settings when auto,
    or preserves admin manual override; records audit fields.
    """
    c = dict(compliance)
    try:
        tax_year = int(c.get("w4_tax_year") or datetime.now().year)
    except (ValueError, TypeError):
        tax_year = datetime.now().year

    settings = fetch_w4_year_settings(conn, organization_id, tax_year)
    rate_c = Decimal(str(settings.get("w4_step3_child_credit_amount") or 2000))
    rate_o = Decimal(str(settings.get("w4_step3_other_dependent_credit_amount") or 500))
    allow_other = _bool(settings.get("w4_allow_other_credits", 1))
    allow_manual = _bool(settings.get("w4_enable_manual_override", 1))

    exempt = _bool(c.get("exempt"))
    is_nra = _bool(c.get("is_nonresident_alien") or c.get("nonresident_alien"))
    nra_allow = _bool(c.get("nra_allow_step3_4"))

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    sid = settings.get("id")

    def clear_step3() -> None:
        c["step3a_amount"] = ""
        c["step3b_amount"] = ""
        c["dependents_amount"] = ""
        c["w4_qualifying_children_under_17_count"] = ""
        c["w4_other_dependents_count"] = ""
        c["w4_step3_other_credits_amount"] = ""
        c["w4_calc_method"] = ""
        c["w4_calc_child_credit_rate_used"] = ""
        c["w4_calc_other_dependent_rate_used"] = ""
        c["w4_calc_timestamp"] = ""
        c["w4_calc_by_user_id"] = ""
        c["w4_settings_version_id"] = ""

    if exempt:
        clear_step3()
        c["w4_calc_method"] = "exempt_cleared"
        c["w4_calc_timestamp"] = now_iso
        c["w4_calc_by_user_id"] = int(acting_user_id)
        return c

    if is_nra and not nra_allow:
        clear_step3()
        c["w4_calc_method"] = "nra_cleared"
        c["w4_calc_timestamp"] = now_iso
        c["w4_calc_by_user_id"] = int(acting_user_id)
        return c

    auto = c.get("w4_step3_use_auto_calculation", True)
    if isinstance(auto, str):
        auto = str(auto).strip().lower() in ("1", "true", "yes", "")

    child_n = _intish(
        c.get("w4_qualifying_children_under_17_count") or c.get("w4_helper_children_under_17")
    )
    other_n = _intish(c.get("w4_other_dependents_count") or c.get("w4_helper_other_dependents"))
    other_cred = _money_dec(c.get("w4_step3_other_credits_amount"))
    if not allow_other:
        other_cred = Decimal("0")

    manual_ov = _bool(c.get("w4_step3_manual_override"))

    c["w4_settings_version_id"] = str(sid) if sid is not None else ""

    if manual_ov and allow_manual:
        c["w4_calc_method"] = "manual_override"
        c["w4_calc_child_credit_rate_used"] = str(rate_c)
        c["w4_calc_other_dependent_rate_used"] = str(rate_o)
        c["w4_calc_timestamp"] = now_iso
        c["w4_calc_by_user_id"] = int(acting_user_id)
        return c

    if not auto:
        c["w4_calc_method"] = "manual_amounts"
        c["w4_calc_child_credit_rate_used"] = str(rate_c)
        c["w4_calc_other_dependent_rate_used"] = str(rate_o)
        c["w4_calc_timestamp"] = now_iso
        c["w4_calc_by_user_id"] = int(acting_user_id)
        return c

    s3a = (Decimal(child_n) * rate_c).quantize(Decimal("0.01"))
    s3b = (Decimal(other_n) * rate_o).quantize(Decimal("0.01"))
    total = (s3a + s3b + other_cred).quantize(Decimal("0.01"))

    c["step3a_amount"] = _fmt_money(s3a) if child_n else ""
    c["step3b_amount"] = _fmt_money(s3b) if other_n else ""
    c["dependents_amount"] = _fmt_money(total) if total > 0 else ""

    c["w4_calc_method"] = "auto"
    c["w4_calc_child_credit_rate_used"] = str(rate_c)
    c["w4_calc_other_dependent_rate_used"] = str(rate_o)
    c["w4_calc_timestamp"] = now_iso
    c["w4_calc_by_user_id"] = int(acting_user_id)
    return c


def patch_work_json_w4_compliance(
    conn,
    organization_id: int,
    work_json: Any,
    acting_user_id: int,
) -> Any:
    if not isinstance(work_json, dict):
        return work_json
    w4 = work_json.get("w4")
    if not isinstance(w4, dict):
        return work_json
    comp = w4.get("compliance")
    if not isinstance(comp, dict):
        return work_json
    w4 = dict(w4)
    w4["compliance"] = apply_w4_compliance_step3(conn, organization_id, comp, acting_user_id)
    out = dict(work_json)
    out["w4"] = w4
    return out
