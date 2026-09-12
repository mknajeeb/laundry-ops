"""Authoritative Performance role registry for Rinse Hub + Management publish.

Phase 1 live role: FOLDER only. SORT / WF_OPERATOR / HD_OPERATOR are reserved
(enabled=false, rinse_visible=false) until Management publishers exist.
"""

from __future__ import annotations

from typing import Any

ROLE_FOLDER = "FOLDER"
ROLE_SORT = "SORT"
ROLE_WF_OPERATOR = "WF_OPERATOR"
ROLE_HD_OPERATOR = "HD_OPERATOR"

# Existing Folder lbs/hr org setting — do not invent a second key.
FOLDER_BENCHMARK_SETTING_KEY = "rinse_folding_lbs_per_hour_target"
FOLDER_DEFAULT_BENCHMARK = 40.0

PERFORMANCE_ROLES: tuple[dict[str, Any], ...] = (
    {
        "role_key": ROLE_FOLDER,
        "display_name": "Folder",
        "metric_key": "lbs_per_hour",
        "metric_label": "Lbs per hour",
        "unit": "lb/hr",
        "benchmark_setting_key": FOLDER_BENCHMARK_SETTING_KEY,
        "default_benchmark": FOLDER_DEFAULT_BENCHMARK,
        "enabled": True,
        "rinse_visible": True,
        "category_code": "RINSE_WF",
        "attendance_role_code": "FOLDER",
        "has_publisher": True,
    },
    {
        "role_key": ROLE_SORT,
        "display_name": "Sorter",
        "metric_key": None,
        "metric_label": None,
        "unit": None,
        "benchmark_setting_key": None,
        "default_benchmark": None,
        "enabled": False,
        "rinse_visible": False,
        "category_code": "RINSE_WF",
        "attendance_role_code": "SORT",
        "has_publisher": False,
    },
    {
        "role_key": ROLE_WF_OPERATOR,
        "display_name": "WF Operator",
        "metric_key": None,
        "metric_label": None,
        "unit": None,
        "benchmark_setting_key": None,
        "default_benchmark": None,
        "enabled": False,
        "rinse_visible": False,
        "category_code": "RINSE_WF",
        "attendance_role_code": "OPERATOR",
        "has_publisher": False,
    },
    {
        "role_key": ROLE_HD_OPERATOR,
        "display_name": "HD Operator",
        "metric_key": None,
        "metric_label": None,
        "unit": None,
        "benchmark_setting_key": None,
        "default_benchmark": None,
        "enabled": False,
        "rinse_visible": False,
        "category_code": "RINSE_HD",
        "attendance_role_code": "OPERATOR",
        "has_publisher": False,
    },
)

_BY_KEY = {str(r["role_key"]): r for r in PERFORMANCE_ROLES}


def get_role(role_key: str | None) -> dict[str, Any] | None:
    key = str(role_key or "").strip().upper()
    row = _BY_KEY.get(key)
    return dict(row) if row else None


def role_is_publishable(role_key: str | None) -> bool:
    role = get_role(role_key)
    if not role:
        return False
    return bool(role.get("enabled") and role.get("has_publisher"))


def rinse_visible_roles() -> list[dict[str, Any]]:
    """Roles Rinse UI should show (live publisher only)."""
    return [
        dict(r)
        for r in PERFORMANCE_ROLES
        if r.get("enabled") and r.get("rinse_visible") and r.get("has_publisher")
    ]


def all_roles_public() -> list[dict[str, Any]]:
    return [dict(r) for r in PERFORMANCE_ROLES]
