"""Weekly schedule presentation settings (system_settings JSON, org-scoped)."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from backend.ta_helpers import table_exists

KEY_WEEKLY_SCHEDULE_DISPLAY = "weekly_schedule_display_settings"

DEFAULTS: dict[str, bool] = {
    "show_estimated_cost_default": True,
    "show_role_labels_default": True,
    "share_cost_with_external": False,
    "share_role_labels_with_external": True,
    "share_break_minutes_with_external": True,
}

PRIVILEGED_ROLES = frozenset({"ADMIN", "OPS", "SUPER_ADMIN", "PLATFORM_ADMIN"})


def _truthy(raw: Any, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
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


def _set_setting(cursor, organization_id: int, key: str, value: str) -> None:
    cursor.execute(
        """
        INSERT INTO system_settings (organization_id, skey, svalue) VALUES (%s,%s,%s)
        ON DUPLICATE KEY UPDATE svalue=VALUES(svalue)
        """,
        (int(organization_id), key, value),
    )


def get_weekly_schedule_display_settings(cursor, organization_id: int) -> dict[str, bool]:
    raw = _get_setting(cursor, int(organization_id), KEY_WEEKLY_SCHEDULE_DISPLAY)
    out = dict(DEFAULTS)
    if not raw:
        return out
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return out
    if not isinstance(parsed, dict):
        return out
    for key in DEFAULTS:
        if key in parsed:
            out[key] = _truthy(parsed[key], default=DEFAULTS[key])
    return out


def save_weekly_schedule_display_settings(
    cursor,
    organization_id: int,
    data: Mapping[str, Any],
) -> dict[str, bool]:
    current = get_weekly_schedule_display_settings(cursor, organization_id)
    for key in DEFAULTS:
        if key in data:
            current[key] = _truthy(data[key], default=current[key])
    _set_setting(
        cursor,
        int(organization_id),
        KEY_WEEKLY_SCHEDULE_DISPLAY,
        json.dumps(current),
    )
    return current


def _is_privileged(user_roles: Sequence[str] | None) -> bool:
    rs = {str(r).upper() for r in (user_roles or [])}
    return bool(rs & PRIVILEGED_ROLES)


def effective_weekly_schedule_view(
    cursor,
    organization_id: int,
    user_roles: Sequence[str] | None,
) -> dict[str, Any]:
    """Resolve what the current user may see on the weekly schedule."""
    settings = get_weekly_schedule_display_settings(cursor, organization_id)
    privileged = _is_privileged(user_roles)
    if privileged:
        return {
            "is_privileged": True,
            "show_estimated_cost": settings["show_estimated_cost_default"],
            "show_role_labels": settings["show_role_labels_default"],
            "show_break_minutes": True,
            "can_edit_schedule": True,
            "can_manage_exclusions": True,
            "can_configure_sharing": True,
            "org_settings": settings,
        }
    return {
        "is_privileged": False,
        "show_estimated_cost": settings["share_cost_with_external"],
        "show_role_labels": settings["share_role_labels_with_external"],
        "show_break_minutes": settings["share_break_minutes_with_external"],
        "can_edit_schedule": False,
        "can_manage_exclusions": False,
        "can_configure_sharing": False,
        "org_settings": {
            k: settings[k]
            for k in (
                "share_cost_with_external",
                "share_role_labels_with_external",
                "share_break_minutes_with_external",
            )
        },
    }
