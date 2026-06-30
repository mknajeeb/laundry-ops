"""Weekly schedule presentation settings (system_settings JSON, org-scoped)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Mapping, Sequence

from backend.payroll_employer_affiliation import (
    EMPLOYER_AFFILIATION_BOTH,
    EMPLOYER_AFFILIATION_RINSE,
)
from backend.planned_weekly_schedule import VALID_ROLES, parse_weekly_roles
from backend.ta_helpers import table_exists

KEY_WEEKLY_SCHEDULE_DISPLAY = "weekly_schedule_display_settings"

BOOL_DEFAULTS: dict[str, bool] = {
    "show_estimated_cost_default": False,
    "show_role_labels_default": True,
    "show_employee_rates_default": False,
    "schedule_end_time_enabled": True,
    "share_cost_with_external": False,
    "share_role_labels_with_external": True,
    "share_break_minutes_with_external": True,
    "share_rates_with_external": False,
}

DEFAULT_HIDDEN_ROLES_FOR_RINSE_VIEWERS = ("non_rinse_folder", "attendant")

PRIVILEGED_ROLES = frozenset({"ADMIN", "OPS", "SUPER_ADMIN", "PLATFORM_ADMIN"})
RINSE_SCHEDULE_VIEWER_ROLES = frozenset({"RINSE"})
RINSE_EXCLUSIVE_EMPLOYER_AFFILIATIONS = frozenset(
    {EMPLOYER_AFFILIATION_RINSE, EMPLOYER_AFFILIATION_BOTH}
)


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


def normalize_hidden_roles_for_rinse_viewers(raw: Any) -> list[str]:
    if raw is None:
        return list(DEFAULT_HIDDEN_ROLES_FOR_RINSE_VIEWERS)
    items: list[Any]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            items = parsed if isinstance(parsed, list) else [raw]
        except (TypeError, json.JSONDecodeError):
            items = [part.strip() for part in text.replace("|", ",").split(",")]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        return list(DEFAULT_HIDDEN_ROLES_FOR_RINSE_VIEWERS)
    out: list[str] = []
    for item in items:
        role = str(item or "").strip().lower()
        if role in VALID_ROLES and role not in out:
            out.append(role)
    return out


def entry_has_hidden_schedule_role(entry: Mapping[str, Any], hidden_roles: Sequence[str]) -> bool:
    hidden = {str(role).strip().lower() for role in (hidden_roles or []) if str(role).strip()}
    if not hidden:
        return False
    roles = parse_weekly_roles(entry.get("roles") or entry.get("role"))
    return any(role in hidden for role in roles)


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


def _serialize_settings(settings: Mapping[str, Any]) -> str:
    payload = {key: bool(settings[key]) for key in BOOL_DEFAULTS}
    payload["hidden_roles_for_rinse_viewers"] = list(
        normalize_hidden_roles_for_rinse_viewers(settings.get("hidden_roles_for_rinse_viewers"))
    )
    return json.dumps(payload)


def get_weekly_schedule_display_settings(cursor, organization_id: int) -> dict[str, Any]:
    raw = _get_setting(cursor, int(organization_id), KEY_WEEKLY_SCHEDULE_DISPLAY)
    out: dict[str, Any] = dict(BOOL_DEFAULTS)
    out["hidden_roles_for_rinse_viewers"] = list(DEFAULT_HIDDEN_ROLES_FOR_RINSE_VIEWERS)
    if not raw:
        return out
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return out
    if not isinstance(parsed, dict):
        return out
    for key in BOOL_DEFAULTS:
        if key in parsed:
            out[key] = _truthy(parsed[key], default=BOOL_DEFAULTS[key])
    if "hidden_roles_for_rinse_viewers" in parsed:
        out["hidden_roles_for_rinse_viewers"] = normalize_hidden_roles_for_rinse_viewers(
            parsed["hidden_roles_for_rinse_viewers"]
        )
    return out


def save_weekly_schedule_display_settings(
    cursor,
    organization_id: int,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    current = get_weekly_schedule_display_settings(cursor, organization_id)
    for key in BOOL_DEFAULTS:
        if key in data:
            current[key] = _truthy(data[key], default=current[key])
    if "hidden_roles_for_rinse_viewers" in data:
        current["hidden_roles_for_rinse_viewers"] = normalize_hidden_roles_for_rinse_viewers(
            data["hidden_roles_for_rinse_viewers"]
        )
    _set_setting(
        cursor,
        int(organization_id),
        KEY_WEEKLY_SCHEDULE_DISPLAY,
        _serialize_settings(current),
    )
    return current


def _is_privileged(user_roles: Sequence[str] | None) -> bool:
    rs = {str(r).upper() for r in (user_roles or [])}
    return bool(rs & PRIVILEGED_ROLES)


def is_rinse_schedule_viewer(user_roles: Sequence[str] | None) -> bool:
    """Rinse partner login: read-only Rinse Exclusive tab, current week onward."""
    if _is_privileged(user_roles):
        return False
    rs = {str(r).upper() for r in (user_roles or [])}
    return bool(rs & RINSE_SCHEDULE_VIEWER_ROLES)


def current_schedule_week_start() -> date:
    from backend.planned_weekly_schedule import normalize_week_start
    from backend.rinse_scheduled_scrape import _today_et

    return normalize_week_start(_today_et())  # type: ignore[return-value]


def validate_schedule_week_access(
    week_start: date,
    user_roles: Sequence[str] | None,
) -> str | None:
    if not is_rinse_schedule_viewer(user_roles):
        return None
    min_week = current_schedule_week_start()
    if week_start < min_week:
        return f"Schedule is only available from the week of {min_week.isoformat()} onward"
    return None


def apply_rinse_viewer_scope(
    payload: Mapping[str, Any],
    *,
    hidden_roles: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Limit weekly schedule payload to Rinse Exclusive shifts for RINSE role viewers."""
    from backend.planned_weekly_schedule import compute_schedule_totals
    from backend.payroll_employer_affiliation import EMPLOYER_AFFILIATION_RINSE

    hidden = normalize_hidden_roles_for_rinse_viewers(hidden_roles)
    out = dict(payload)
    entries = [
        entry
        for entry in (out.get("entries") or [])
        if entry.get("employer_affiliation") == EMPLOYER_AFFILIATION_RINSE
        and not entry_has_hidden_schedule_role(entry, hidden)
    ]
    allowed_user_ids = {int(entry.get("user_id") or 0) for entry in entries if entry.get("user_id") is not None}
    employees = [
        row
        for row in (out.get("employees") or [])
        if int(row.get("user_id") or 0) in allowed_user_ids
    ]
    excluded_user_ids = [
        int(uid)
        for uid in (out.get("excluded_user_ids") or [])
        if int(uid) in allowed_user_ids
    ]
    workers_by_uid = {
        int(row["user_id"]): {
            "user_id": row["user_id"],
            "default_hourly_rate": row.get("default_hourly_rate"),
        }
        for row in employees
        if row.get("user_id") is not None
    }
    out["employees"] = employees
    out["entries"] = entries
    out["excluded_user_ids"] = excluded_user_ids
    out["totals"] = compute_schedule_totals(
        entries,
        workers_by_uid,
        excluded_user_ids=excluded_user_ids,
    )
    return out


def effective_weekly_schedule_view(
    cursor,
    organization_id: int,
    user_roles: Sequence[str] | None,
) -> dict[str, Any]:
    """Resolve what the current user may see on the weekly schedule."""
    settings = get_weekly_schedule_display_settings(cursor, organization_id)
    privileged = _is_privileged(user_roles)
    rinse_viewer = is_rinse_schedule_viewer(user_roles)
    min_week = current_schedule_week_start().isoformat() if rinse_viewer else None
    hidden_for_rinse = normalize_hidden_roles_for_rinse_viewers(
        settings.get("hidden_roles_for_rinse_viewers")
    )
    if privileged:
        return {
            "is_privileged": True,
            "show_estimated_cost": settings["show_estimated_cost_default"],
            "show_role_labels": settings["show_role_labels_default"],
            "show_employee_rates": settings["show_employee_rates_default"],
            "schedule_end_time_enabled": settings["schedule_end_time_enabled"],
            "show_break_minutes": True,
            "can_edit_schedule": True,
            "can_manage_exclusions": True,
            "can_configure_sharing": True,
            "employer_tab": None,
            "lock_employer_tab": False,
            "hide_employer_tabs": False,
            "min_week_start": None,
            "can_view_past_weeks": True,
            "hidden_schedule_roles": [],
            "org_settings": settings,
        }
    external_view = {
        "is_privileged": False,
        "show_estimated_cost": settings["share_cost_with_external"],
        "show_role_labels": settings["share_role_labels_with_external"],
        "show_employee_rates": settings["share_rates_with_external"],
        "schedule_end_time_enabled": settings["schedule_end_time_enabled"],
        "show_break_minutes": settings["share_break_minutes_with_external"],
        "can_edit_schedule": False,
        "can_manage_exclusions": False,
        "can_configure_sharing": False,
        "employer_tab": EMPLOYER_AFFILIATION_RINSE if rinse_viewer else None,
        "lock_employer_tab": rinse_viewer,
        "hide_employer_tabs": rinse_viewer,
        "min_week_start": min_week,
        "can_view_past_weeks": not rinse_viewer,
        "hidden_schedule_roles": hidden_for_rinse if rinse_viewer else [],
        "org_settings": {
            k: settings[k]
            for k in (
                "share_cost_with_external",
                "share_role_labels_with_external",
                "share_break_minutes_with_external",
                "share_rates_with_external",
                "hidden_roles_for_rinse_viewers",
            )
        },
    }
    return external_view
