"""Employee productivity dashboard maintenance settings (presentation layer only)."""

from __future__ import annotations

import os
from typing import Any

from backend.ta_helpers import table_exists

KEY_INCLUDE_HD_IN_EMPLOYEE_PRODUCTIVITY = "include_hd_in_employee_productivity"
ENV_INCLUDE_HD_IN_EMPLOYEE_PRODUCTIVITY = "INCLUDE_HD_IN_EMPLOYEE_PRODUCTIVITY"


def _truthy(raw: Any, default: bool = False) -> bool:
    if raw is None:
        return default
    s = str(raw).strip().lower()
    if s in {"0", "false", "off", "no", "disabled"}:
        return False
    if s in {"1", "true", "on", "yes", "enabled"}:
        return True
    return default


def _get_setting(cursor, organization_id: int, key: str) -> str | None:
    if not table_exists(cursor, "system_settings"):
        return None
    cursor.execute(
        "SELECT svalue FROM system_settings WHERE organization_id=%s AND skey=%s LIMIT 1",
        (int(organization_id), key),
    )
    row = cursor.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        v = row.get("svalue")
    else:
        v = row[0] if row else None
    return None if v is None else str(v)


def include_hd_in_employee_productivity(cursor, organization_id: int) -> bool:
    """When False (default), dashboard metrics use WF bags only."""
    env_raw = os.getenv(ENV_INCLUDE_HD_IN_EMPLOYEE_PRODUCTIVITY)
    if env_raw is not None and str(env_raw).strip() != "":
        return _truthy(env_raw, default=False)
    stored = _get_setting(cursor, organization_id, KEY_INCLUDE_HD_IN_EMPLOYEE_PRODUCTIVITY)
    if stored is None:
        return False
    return _truthy(stored, default=False)


def productivity_scope_label(include_hd: bool) -> str:
    return "WF + HD" if include_hd else "WF Only"
