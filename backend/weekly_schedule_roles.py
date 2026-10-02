"""Operational weekly-schedule roles (org-scoped settings over built-in role codes).

These are job assignments on the planned schedule (Sort, Lint Cleaning, Self Service, …).
They are intentionally separate from account permission roles (``roles`` / ``user_roles``):
nothing here grants or checks access.

Built-in roles need no seeding — a row is written only when an org edits one.
Custom roles always use a ``custom_`` code so stored entries stay parseable without a DB hit.
Roles are never deleted; deactivating hides them from new assignments while existing
schedule rows keep their code and continue to display.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from backend.planned_weekly_schedule import (
    CUSTOM_ROLE_PREFIX,
    HOUR_TRACKED_ROLES,
    is_schedule_role_code,
)
from backend.ta_helpers import invalidate_schema_cache, table_exists

ROLE_NAME_MAX = 64
REMARKS_MAX = 255

ROLE_GROUPS: tuple[tuple[str, str], ...] = (
    # First four mirror ta_task_categories codes used by attendance.
    ("RINSE_WF", "Rinse WF"),
    ("RINSE_HD", "Rinse HD"),
    ("DROP_OFF", "Drop Off"),
    ("DHS", "DHS"),
    ("SELF_SERVICE", "Self Service"),
    ("CLEANING", "Cleaning"),
)
ROLE_GROUP_CODES = frozenset(code for code, _ in ROLE_GROUPS)

BUILTIN_ROLE_DEFAULTS: tuple[dict[str, Any], ...] = (
    {"code": "wash", "name": "Wash", "role_group": "RINSE_WF", "display_order": 10},
    {"code": "sort", "name": "Sort", "role_group": "RINSE_WF", "display_order": 20},
    {"code": "weigher", "name": "Weigher", "role_group": "RINSE_WF", "display_order": 30},
    {"code": "dry", "name": "Dry", "role_group": "RINSE_WF", "display_order": 35},
    {"code": "fold", "name": "Fold", "role_group": "RINSE_WF", "display_order": 40},
    {"code": "post_weigh", "name": "Post-Weigh", "role_group": "RINSE_WF", "display_order": 45},
    {"code": "pt_washer", "name": "PT Washer", "role_group": "RINSE_WF", "display_order": 50},
    {"code": "pt_sorter", "name": "PT Sorter", "role_group": "RINSE_WF", "display_order": 60},
    {"code": "pt_folder", "name": "PT Folder", "role_group": "RINSE_WF", "display_order": 70},
    {"code": "hd_operator", "name": "HD Operator", "role_group": "RINSE_HD", "display_order": 80},
    {"code": "hd_folder", "name": "HD Folder", "role_group": "RINSE_HD", "display_order": 90},
    {"code": "non_rinse_folder", "name": "Non-Rinse Folder", "role_group": "DROP_OFF", "display_order": 100},
    {"code": "attendant", "name": "Attendant", "role_group": "SELF_SERVICE", "display_order": 110},
    {
        "code": "lint_cleaning",
        "name": "Lint Cleaning",
        "role_group": "CLEANING",
        "display_order": 120,
        "uses_time_slots": False,
        "remarks_enabled": True,
    },
    {
        "code": "floor_cleaning",
        "name": "Floor Cleaning",
        "role_group": "CLEANING",
        "display_order": 130,
        "uses_time_slots": False,
        "remarks_enabled": True,
    },
    {
        "code": "washer_cleaning",
        "name": "Washer Cleaning",
        "role_group": "CLEANING",
        "display_order": 140,
        "uses_time_slots": False,
        "remarks_enabled": True,
    },
    {
        "code": "drop_off_customer",
        "name": "Drop Off Customer",
        "role_group": "DROP_OFF",
        "display_order": 150,
        "uses_time_slots": False,
        "remarks_enabled": True,
    },
    {
        "code": "self_service",
        "name": "Self Service",
        "role_group": "SELF_SERVICE",
        "display_order": 160,
        "uses_time_slots": False,
        "remarks_enabled": True,
    },
)
BUILTIN_ROLE_CODES = frozenset(r["code"] for r in BUILTIN_ROLE_DEFAULTS)
CLEANING_TASK_CODES = frozenset({"lint_cleaning", "floor_cleaning", "washer_cleaning"})
DEFAULT_ROLE_GROUP = "RINSE_WF"
KIND_ROLE = "role"
KIND_TASK = "task"

_CUSTOM_SLUG_MAX = 24


def ensure_weekly_schedule_roles_table(cursor) -> None:
    if table_exists(cursor, "weekly_schedule_roles"):
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS weekly_schedule_roles (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          code VARCHAR(40) NOT NULL,
          name VARCHAR(64) NOT NULL,
          role_group VARCHAR(32) NULL DEFAULT NULL,
          display_order INT NOT NULL DEFAULT 0,
          active TINYINT(1) NOT NULL DEFAULT 1,
          uses_time_slots TINYINT(1) NOT NULL DEFAULT 1,
          remarks_enabled TINYINT(1) NOT NULL DEFAULT 0,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_wsr_org_code (organization_id, code),
          INDEX idx_wsr_org_order (organization_id, display_order)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    invalidate_schema_cache()


def _builtin_default(code: str) -> dict[str, Any] | None:
    for item in BUILTIN_ROLE_DEFAULTS:
        if item["code"] == code:
            return item
    return None


def _role_record(base: Mapping[str, Any], *, builtin: bool) -> dict[str, Any]:
    code = str(base["code"])
    timed = bool(base.get("uses_time_slots", True))
    return {
        "code": code,
        "name": str(base.get("name") or code),
        "kind": KIND_ROLE if timed else KIND_TASK,
        "role_group": base.get("role_group") or None,
        "display_order": int(base.get("display_order") or 0),
        "active": bool(base.get("active", True)),
        "uses_time_slots": timed,
        # Tasks always carry instructions.
        "remarks_enabled": bool(base.get("remarks_enabled", False)) or not timed,
        "builtin": builtin,
        "hour_tracked": code in HOUR_TRACKED_ROLES,
    }


def is_task_role(role: str, catalog: Mapping[str, Mapping[str, Any]]) -> bool:
    info = catalog.get(role)
    return bool(info) and not info.get("uses_time_slots", True)


def role_groups_payload() -> list[dict[str, str]]:
    return [{"code": code, "label": label} for code, label in ROLE_GROUPS]


def list_role_catalog(cursor, organization_id: int) -> list[dict[str, Any]]:
    """Built-in defaults overlaid with org overrides, plus org custom roles, in display order."""
    by_code: dict[str, dict[str, Any]] = {
        item["code"]: _role_record(item, builtin=True) for item in BUILTIN_ROLE_DEFAULTS
    }
    ensure_weekly_schedule_roles_table(cursor)
    cursor.execute(
        """
        SELECT code, name, role_group, display_order, active, uses_time_slots, remarks_enabled
        FROM weekly_schedule_roles
        WHERE organization_id = %s
        """,
        (int(organization_id),),
    )
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip().lower()
        if not code or not is_schedule_role_code(code):
            continue
        builtin = code in BUILTIN_ROLE_CODES
        if not builtin and not code.startswith(CUSTOM_ROLE_PREFIX):
            continue
        by_code[code] = _role_record({**row, "code": code}, builtin=builtin)
    return sorted(by_code.values(), key=lambda r: (r["display_order"], r["name"].casefold()))


def default_role_catalog() -> list[dict[str, Any]]:
    return [_role_record(item, builtin=True) for item in BUILTIN_ROLE_DEFAULTS]


def catalog_index(catalog: Sequence[Mapping[str, Any]] | None) -> dict[str, dict[str, Any]]:
    rows = catalog if catalog is not None else default_role_catalog()
    return {str(r["code"]): dict(r) for r in rows}


def role_assignment_error(
    role: str,
    catalog: Mapping[str, Mapping[str, Any]],
    *,
    timed: bool,
    already_assigned: bool = False,
) -> str | None:
    """Why ``role`` cannot be used for a new timed shift / daily responsibility (None = OK).

    ``already_assigned`` keeps existing rows editable after the role is deactivated or its
    time-slot setting changes, so settings never invalidate historical schedules.
    """
    info = catalog.get(role)
    if not info:
        return f"unknown schedule role: {role}"
    if already_assigned:
        return None
    if not info.get("active", True):
        return f"{info.get('name') or role} is inactive"
    if timed and not info.get("uses_time_slots", True):
        return f"{info.get('name') or role} is a task (assigned by day, without times)"
    if not timed and info.get("uses_time_slots", True):
        return f"{info.get('name') or role} is a role and requires start and end times"
    return None


def normalize_remarks(raw: Any) -> str | None:
    if raw is None:
        return None
    text = " ".join(str(raw).split())
    if not text:
        return None
    return text[:REMARKS_MAX]


def accept_remarks(
    role: str,
    remarks: str | None,
    catalog: Mapping[str, Mapping[str, Any]],
    *,
    existing: set[str] | None = None,
) -> str | None:
    """Keep remarks for tasks and remarks-enabled roles, or when unchanged from the stored value."""
    if not remarks:
        return None
    info = catalog.get(role) or {}
    if info.get("remarks_enabled") or not info.get("uses_time_slots", True):
        return remarks
    if existing and remarks in existing:
        return remarks
    return None


def _parse_bool(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _validate_role_fields(
    data: Mapping[str, Any],
    current: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    out = dict(current)
    if "name" in data:
        name = " ".join(str(data.get("name") or "").split())
        if not name:
            return None, "name is required"
        if len(name) > ROLE_NAME_MAX:
            return None, f"name must be at most {ROLE_NAME_MAX} characters"
        clash = next(
            (
                r
                for r in catalog
                if r["code"] != current.get("code") and str(r["name"]).casefold() == name.casefold()
            ),
            None,
        )
        if clash:
            return None, f"a role or task named {name} already exists"
        out["name"] = name
    if "kind" in data:
        kind = str(data.get("kind") or "").strip().lower()
        if kind not in {KIND_ROLE, KIND_TASK}:
            return None, "kind must be role or task"
        out["uses_time_slots"] = kind == KIND_ROLE
        if kind == KIND_TASK:
            out["remarks_enabled"] = True
    if "role_group" in data:
        raw_group = str(data.get("role_group") or "").strip().upper()
        if raw_group and raw_group not in ROLE_GROUP_CODES:
            return None, "role_group must be one of " + ", ".join(sorted(ROLE_GROUP_CODES))
        out["role_group"] = raw_group or None
    if "display_order" in data:
        try:
            out["display_order"] = int(data.get("display_order"))
        except (TypeError, ValueError):
            return None, "display_order must be an integer"
    for key in ("active", "uses_time_slots", "remarks_enabled"):
        if key in data and not (key != "active" and "kind" in data):
            out[key] = _parse_bool(data.get(key), bool(out.get(key)))
    if not out.get("uses_time_slots", True):
        out["remarks_enabled"] = True
    return out, None


def _upsert_role(cursor, organization_id: int, role: Mapping[str, Any]) -> None:
    ensure_weekly_schedule_roles_table(cursor)
    cursor.execute(
        """
        INSERT INTO weekly_schedule_roles (
            organization_id, code, name, role_group, display_order,
            active, uses_time_slots, remarks_enabled
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            name=VALUES(name),
            role_group=VALUES(role_group),
            display_order=VALUES(display_order),
            active=VALUES(active),
            uses_time_slots=VALUES(uses_time_slots),
            remarks_enabled=VALUES(remarks_enabled)
        """,
        (
            int(organization_id),
            role["code"],
            role["name"],
            role.get("role_group"),
            int(role.get("display_order") or 0),
            1 if role.get("active", True) else 0,
            1 if role.get("uses_time_slots", True) else 0,
            1 if role.get("remarks_enabled") else 0,
        ),
    )


def _custom_code_for_name(name: str, taken: set[str]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:_CUSTOM_SLUG_MAX] or "role"
    code = f"{CUSTOM_ROLE_PREFIX}{slug}"
    n = 2
    while code in taken:
        suffix = f"_{n}"
        code = f"{CUSTOM_ROLE_PREFIX}{slug[: _CUSTOM_SLUG_MAX - len(suffix)]}{suffix}"
        n += 1
    return code


def create_role(
    cursor,
    organization_id: int,
    data: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    catalog = list_role_catalog(cursor, organization_id)
    if not str(data.get("name") or "").strip():
        return None, "name is required"
    next_order = max((int(r["display_order"]) for r in catalog), default=0) + 10
    base = {
        "code": "",
        "name": "",
        "role_group": DEFAULT_ROLE_GROUP,
        "display_order": next_order,
        "active": True,
        "uses_time_slots": True,
        "remarks_enabled": False,
    }
    role, err = _validate_role_fields(data, base, catalog)
    if err or role is None:
        return None, err
    role["code"] = _custom_code_for_name(role["name"], {r["code"] for r in catalog})
    _upsert_role(cursor, organization_id, role)
    return _role_record(role, builtin=False), None


def update_role(
    cursor,
    organization_id: int,
    code: str,
    data: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    catalog = list_role_catalog(cursor, organization_id)
    key = str(code or "").strip().lower()
    current = next((r for r in catalog if r["code"] == key), None)
    if not current:
        return None, "schedule role not found"
    role, err = _validate_role_fields(data, current, catalog)
    if err or role is None:
        return None, err
    _upsert_role(cursor, organization_id, role)
    return _role_record(role, builtin=bool(_builtin_default(key))), None
