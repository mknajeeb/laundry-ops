"""Weekly schedule presentation settings (system_settings JSON, org-scoped)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Mapping, Sequence

from backend.payroll_employer_affiliation import (
    EMPLOYER_AFFILIATION_BOTH,
    EMPLOYER_AFFILIATION_RINSE,
)
from backend.planned_weekly_schedule import is_schedule_role_code, parse_weekly_roles
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
        if is_schedule_role_code(role) and role not in out:
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


_ENTRY_LABOR_KEYS = (
    "hours",
    "gross_hours",
    "break_hours",
    "break_minutes",
    "timed_break_minutes",
    "unscheduled_break_minutes",
    "break_slots",
    "end_time",
    "estimated_cost",
    "ot_hours",
    "overtime_hours",
    "overtime",
)

_EMPLOYEE_LABOR_KEYS = (
    "total_hours",
    "gross_hours",
    "break_hours",
    "timed_break_hours",
    "unscheduled_break_hours",
    "estimated_cost",
    "default_hourly_rate",
    "ot_hours",
    "overtime_hours",
    "overtime",
)

_TOTALS_HOUR_SUFFIXES = ("_hours",)
_TOTALS_DROP_KEYS = (
    "total_hours",
    "gross_hours",
    "break_hours",
    "timed_break_hours",
    "unscheduled_break_hours",
    "unallocated_break_hours",
    "estimated_cost",
    "total_estimated_cost",
    "ot_hours",
    "overtime_hours",
)


def _strip_role_assignment_labor(assignments: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in assignments or []:
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        item.pop("end_time", None)
        item.pop("hours", None)
        item.pop("duration_minutes", None)
        out.append(item)
    return out


def _strip_schedule_entry_labor(entry: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(entry)
    for key in _ENTRY_LABOR_KEYS:
        row.pop(key, None)
    if "assignments" in row:
        row["assignments"] = _strip_role_assignment_labor(row.get("assignments"))
    return row


def _strip_schedule_employee_labor(row: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for key in _EMPLOYEE_LABOR_KEYS:
        out.pop(key, None)
    return out


def _strip_day_or_role_labor(row: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if key in _TOTALS_DROP_KEYS:
            continue
        if any(key.endswith(suf) for suf in _TOTALS_HOUR_SUFFIXES):
            continue
        if key == "roles" and isinstance(value, list):
            cleaned_roles = []
            for role_row in value:
                if not isinstance(role_row, Mapping):
                    continue
                cleaned = {
                    "role": role_row.get("role"),
                    "employees": role_row.get("employees"),
                }
                cleaned_roles.append(cleaned)
            out[key] = cleaned_roles
            continue
        out[key] = value
    return out


def _strip_schedule_totals_labor(totals: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(totals or {})
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key in _TOTALS_DROP_KEYS:
            continue
        if key == "employee_totals" and isinstance(value, Mapping):
            out[key] = {
                uid: {
                    "user_id": (row or {}).get("user_id", uid),
                    "scheduled_days": (row or {}).get("scheduled_days"),
                }
                for uid, row in value.items()
                if isinstance(row, Mapping) or row is None
            }
            continue
        if key == "day_totals" and isinstance(value, (list, tuple)):
            out[key] = [
                _strip_day_or_role_labor(day) if isinstance(day, Mapping) else day for day in value
            ]
            continue
        if key == "day_totals" and isinstance(value, Mapping):
            out[key] = {
                dow: _strip_day_or_role_labor(day) if isinstance(day, Mapping) else day
                for dow, day in value.items()
            }
            continue
        if isinstance(value, Mapping) and any(
            k in value or any(str(k).endswith("_hours") for k in value)
            for k in _TOTALS_DROP_KEYS
        ):
            out[key] = _strip_day_or_role_labor(value)
            continue
        out[key] = value
    out["labor_fields_hidden"] = True
    return out


def apply_rinse_viewer_scope(
    payload: Mapping[str, Any],
    *,
    hidden_roles: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Limit weekly schedule payload to Rinse Exclusive shifts for RINSE role viewers.

    Also strips labor-hour, break-duration, overtime, and wage fields from the API
    response so Rinse cannot recover them from the network payload.
    """
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
    from backend.planned_weekly_schedule_responsibilities import filter_responsibilities_for_view

    totals = compute_schedule_totals(
        entries,
        workers_by_uid,
        excluded_user_ids=excluded_user_ids,
    )
    out["employees"] = [_strip_schedule_employee_labor(row) for row in employees]
    out["entries"] = [_strip_schedule_entry_labor(entry) for entry in entries]
    out["daily_responsibilities"] = filter_responsibilities_for_view(
        out.get("daily_responsibilities") or [],
        allowed_user_ids=allowed_user_ids,
        hidden_roles=hidden,
    )
    out["excluded_user_ids"] = excluded_user_ids
    out["totals"] = _strip_schedule_totals_labor(totals)
    display = dict(out.get("display") or {})
    display["show_estimated_cost"] = False
    display["show_employee_rates"] = False
    display["show_break_minutes"] = False
    display["hide_labor_hours"] = True
    display["can_edit_schedule"] = False
    out["display"] = display
    out["hide_labor_hours"] = True
    out["labor_fields_hidden"] = True
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
            "hide_labor_hours": False,
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
    if rinse_viewer:
        # Rinse partner: operational schedule only — no labor/hours/wage sharing toggles.
        return {
            "is_privileged": False,
            "show_estimated_cost": False,
            "show_role_labels": settings["share_role_labels_with_external"],
            "show_employee_rates": False,
            "schedule_end_time_enabled": settings["schedule_end_time_enabled"],
            "show_break_minutes": False,
            "hide_labor_hours": True,
            "can_edit_schedule": False,
            "can_manage_exclusions": False,
            "can_configure_sharing": False,
            "employer_tab": EMPLOYER_AFFILIATION_RINSE,
            "lock_employer_tab": True,
            "hide_employer_tabs": True,
            "min_week_start": min_week,
            "can_view_past_weeks": False,
            "hidden_schedule_roles": hidden_for_rinse,
            "org_settings": {
                "share_cost_with_external": False,
                "share_role_labels_with_external": settings["share_role_labels_with_external"],
                "share_break_minutes_with_external": False,
                "share_rates_with_external": False,
                "hidden_roles_for_rinse_viewers": settings["hidden_roles_for_rinse_viewers"],
            },
        }
    external_view = {
        "is_privileged": False,
        "show_estimated_cost": settings["share_cost_with_external"],
        "show_role_labels": settings["share_role_labels_with_external"],
        "show_employee_rates": settings["share_rates_with_external"],
        "schedule_end_time_enabled": settings["schedule_end_time_enabled"],
        "show_break_minutes": settings["share_break_minutes_with_external"],
        "hide_labor_hours": False,
        "can_edit_schedule": False,
        "can_manage_exclusions": False,
        "can_configure_sharing": False,
        "employer_tab": None,
        "lock_employer_tab": False,
        "hide_employer_tabs": False,
        "min_week_start": min_week,
        "can_view_past_weeks": True,
        "hidden_schedule_roles": [],
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
