"""Default and name-based withholding profile overrides for W-2 estimates."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

# NYC resident, single, no dependents, one job — unless profile or override says otherwise.
_DEFAULTS: dict[str, Any] = {
    "nyc_resident": True,
    "filing_status": "single_or_mfs",
    "work_state": "NY",
    "work_city": "New York",
    "home_city": "New York",
    "w4_qualifying_children_under_17_count": 0,
    "w4_other_dependents_count": 0,
    "step2_multiple_jobs": "no",
    "two_jobs_only": False,
    "withholding_exemptions": 0,
}

_NAME_OVERRIDES: dict[str, dict[str, Any]] = {
    "tarannum mithila": {
        "filing_status": "married_joint",
    },
    "alec coaxum": {
        "w4_qualifying_children_under_17_count": 2,
        "dependents_amount": Decimal("4000"),
        "withholding_exemptions": 2,
    },
    "paola almiron": {
        "step2_multiple_jobs": "yes",
        "two_jobs_only": True,
    },
}


def normalize_worker_name(name: str) -> str:
    return " ".join(str(name or "").strip().lower().split())


def apply_withholding_profile_defaults(
    profile: dict[str, Any],
    worker_name: Optional[str] = None,
) -> dict[str, Any]:
    """Merge HR profile with workforce defaults and known employee overrides."""
    out = dict(profile)
    for key, val in _DEFAULTS.items():
        if out.get(key) is None or out.get(key) == "":
            out[key] = val

    override = _NAME_OVERRIDES.get(normalize_worker_name(worker_name or ""))
    if override:
        out.update(override)

    if not out.get("filing_status"):
        out["filing_status"] = _DEFAULTS["filing_status"]

    if out.get("nyc_resident") is None:
        out["nyc_resident"] = True

    # Map child count to annual Step 3 credit when not explicitly set.
    if not out.get("dependents_amount"):
        child_n = int(out.get("w4_qualifying_children_under_17_count") or 0)
        other_n = int(out.get("w4_other_dependents_count") or 0)
        if child_n or other_n:
            out["dependents_amount"] = Decimal(str(child_n * 2000 + other_n * 500))

    if out.get("withholding_exemptions") is None:
        child_n = int(out.get("w4_qualifying_children_under_17_count") or 0)
        out["withholding_exemptions"] = child_n

    return out


def step2_checkbox_checked(profile: dict[str, Any]) -> bool:
    if profile.get("two_jobs_only"):
        return True
    mult = str(profile.get("step2_multiple_jobs") or "").strip().lower()
    return mult in ("yes", "true", "1")


def is_married_filing(profile: dict[str, Any]) -> bool:
    filing = str(profile.get("filing_status") or "").strip().lower()
    return filing in ("mfj_or_qss", "married_joint", "married", "mfj")
