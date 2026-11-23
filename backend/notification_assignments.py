"""Explicit management-notification recipients.

Role and module access do not add anyone to these lists. An empty list sends
to nobody. Routing stays on the previous rules until an organization row sets
management_routing_active.
"""

from __future__ import annotations

import json
from typing import Any

from backend.notification_catalog import (
    AUTOMATIC_NOTIFICATIONS,
    LEGACY_ROUTING,
    MANAGEMENT_CATEGORIES,
    is_management_event,
    management_event,
)

ROUTING_TABLE = "notification_routing_activation"
SETTINGS_TABLE = "notification_category_settings"
RECIPIENT_TABLE = "notification_category_recipients"
AUDIT_TABLE = "notification_assignment_audit"
ASSIGNMENT_TABLES = (ROUTING_TABLE, SETTINGS_TABLE, RECIPIENT_TABLE, AUDIT_TABLE)
MIGRATION_FILE = "backend/sql/notification_assignments_v1.sql"


class NotificationAssignmentError(Exception):
    def __init__(self, code: str, **details):
        super().__init__(code)
        self.code = code
        self.details = details


def assignment_tables_ready(cursor) -> bool:
    """True only when the controlled migration has already created the tables."""
    from backend.ta_helpers import table_exists

    return all(table_exists(cursor, name) for name in ASSIGNMENT_TABLES)


def routing_is_active(cursor, organization_id: int) -> bool:
    from backend.ta_helpers import table_exists

    if not table_exists(cursor, ROUTING_TABLE):
        return False
    cursor.execute(
        f"SELECT management_routing_active FROM {ROUTING_TABLE} WHERE organization_id=%s",
        (int(organization_id),),
    )
    row = cursor.fetchone()
    return bool(row and row.get("management_routing_active"))


def category_is_enabled(cursor, organization_id: int, event_key: str) -> bool:
    from backend.ta_helpers import table_exists

    if not table_exists(cursor, SETTINGS_TABLE):
        return True
    cursor.execute(
        f"SELECT enabled FROM {SETTINGS_TABLE} WHERE organization_id=%s AND event_key=%s",
        (int(organization_id), event_key),
    )
    row = cursor.fetchone()
    if not row:
        return True
    return bool(row.get("enabled"))


def resolve_assigned_recipients(cursor, organization_id: int, event_key: str) -> set[int]:
    """Active users in this organization who are explicitly assigned. Never roles."""
    from backend.ta_helpers import table_exists

    if not category_is_enabled(cursor, organization_id, event_key):
        return set()
    if not table_exists(cursor, RECIPIENT_TABLE):
        return set()
    cursor.execute(
        f"""
        SELECT r.user_id
        FROM {RECIPIENT_TABLE} r
        JOIN users u ON u.id = r.user_id AND u.organization_id = r.organization_id
        WHERE r.organization_id=%s AND r.event_key=%s AND COALESCE(u.active, 1)=1
        """,
        (int(organization_id), event_key),
    )
    return {int(row["user_id"]) for row in cursor.fetchall() or [] if row.get("user_id") is not None}


def management_dispatch_recipients(cursor, organization_id: int, event_key: str):
    """Explicit recipients once routing is active. LEGACY_ROUTING until then."""
    if not is_management_event(event_key):
        return LEGACY_ROUTING
    if not routing_is_active(cursor, organization_id):
        return LEGACY_ROUTING
    return resolve_assigned_recipients(cursor, organization_id, event_key)


def _distinct_user_ids(user_ids) -> list[int]:
    chosen: list[int] = []
    seen: set[int] = set()
    for raw in user_ids or []:
        try:
            uid = int(raw)
        except (TypeError, ValueError):
            raise NotificationAssignmentError("invalid_user") from None
        if uid <= 0 or uid in seen:
            continue
        seen.add(uid)
        chosen.append(uid)
    return chosen


def save_management_assignment(
    cursor,
    *,
    organization_id: int,
    event_key: str,
    user_ids,
    enabled: bool,
    actor_user_id: int | None,
) -> list[int]:
    """Replace one category's recipients. Does not change roles or module access."""
    if management_event(event_key) is None:
        raise NotificationAssignmentError("unknown_category")
    wanted = _distinct_user_ids(user_ids)
    if wanted:
        placeholders = ",".join(["%s"] * len(wanted))
        cursor.execute(
            f"SELECT id, active FROM users WHERE organization_id=%s AND id IN ({placeholders})",
            (int(organization_id), *wanted),
        )
        found = {}
        for row in cursor.fetchall() or []:
            active = row.get("active")
            found[int(row["id"])] = 1 if active is None else int(active)
        if any(uid not in found for uid in wanted):
            raise NotificationAssignmentError("outside_organization")
        if any(not found[uid] for uid in wanted):
            raise NotificationAssignmentError("inactive_user")
    cursor.execute(
        f"SELECT user_id FROM {RECIPIENT_TABLE} WHERE organization_id=%s AND event_key=%s",
        (int(organization_id), event_key),
    )
    previous = {int(row["user_id"]) for row in cursor.fetchall() or []}
    cursor.execute(
        f"DELETE FROM {RECIPIENT_TABLE} WHERE organization_id=%s AND event_key=%s",
        (int(organization_id), event_key),
    )
    for uid in wanted:
        cursor.execute(
            f"""
            INSERT INTO {RECIPIENT_TABLE}
              (organization_id, event_key, user_id, assigned_by_user_id, assigned_at)
            VALUES (%s,%s,%s,%s, NOW())
            """,
            (int(organization_id), event_key, uid, actor_user_id),
        )
    cursor.execute(
        f"""
        INSERT INTO {SETTINGS_TABLE}
          (organization_id, event_key, enabled, updated_by_user_id, updated_at)
        VALUES (%s,%s,%s,%s, NOW())
        ON DUPLICATE KEY UPDATE
          enabled=VALUES(enabled),
          updated_by_user_id=VALUES(updated_by_user_id),
          updated_at=NOW()
        """,
        (int(organization_id), event_key, 1 if enabled else 0, actor_user_id),
    )
    detail = {
        "enabled": bool(enabled),
        "user_ids": wanted,
        "added": sorted(set(wanted) - previous),
        "removed": sorted(previous - set(wanted)),
    }
    cursor.execute(
        f"""
        INSERT INTO {AUDIT_TABLE}
          (organization_id, event_key, action, actor_user_id, detail_json, created_at)
        VALUES (%s,%s,%s,%s,%s, NOW())
        """,
        (
            int(organization_id),
            event_key,
            "assignment_saved",
            actor_user_id,
            json.dumps(detail),
        ),
    )
    return wanted


def management_catalog(cursor, organization_id: int) -> dict[str, Any]:
    from backend.ta_helpers import table_exists

    recipients: dict[str, list[dict[str, Any]]] = {}
    if table_exists(cursor, RECIPIENT_TABLE):
        payroll_name = ""
        payroll_join = ""
        if table_exists(cursor, "payroll_profiles"):
            payroll_name = ", pp.first_name, pp.last_name"
            payroll_join = "LEFT JOIN payroll_profiles pp ON pp.user_id = u.id"
        cursor.execute(
            f"""
            SELECT r.event_key, r.user_id, u.username, u.display_name, u.active
                   {payroll_name}
            FROM {RECIPIENT_TABLE} r
            JOIN users u ON u.id = r.user_id AND u.organization_id = r.organization_id
            {payroll_join}
            WHERE r.organization_id=%s
            ORDER BY u.display_name, u.username, u.id
            """,
            (int(organization_id),),
        )
        for row in cursor.fetchall() or []:
            recipients.setdefault(str(row["event_key"]), []).append(
                {
                    "id": int(row["user_id"]),
                    "username": row.get("username") or "",
                    "display_name": row.get("display_name") or "",
                    "employee_name": employee_name(row.get("first_name"), row.get("last_name")),
                    "active": bool(row.get("active", 1)),
                }
            )
    enabled: dict[str, bool] = {}
    if table_exists(cursor, SETTINGS_TABLE):
        cursor.execute(
            f"SELECT event_key, enabled FROM {SETTINGS_TABLE} WHERE organization_id=%s",
            (int(organization_id),),
        )
        for row in cursor.fetchall() or []:
            enabled[str(row["event_key"])] = bool(row.get("enabled"))
    modules: dict[str, dict[str, Any]] = {}
    for spec in MANAGEMENT_CATEGORIES:
        module = modules.setdefault(
            spec["module_key"],
            {"module_key": spec["module_key"], "label": spec["module_label"], "categories": []},
        )
        people = recipients.get(spec["event_key"], [])
        module["categories"].append(
            {
                "event_key": spec["event_key"],
                "label": spec["label"],
                "description": spec["description"],
                "kind": "management",
                "targeting": "assignment",
                "enabled": enabled.get(spec["event_key"], True),
                "recipients": people,
            }
        )
    modules_out = list(modules.values())
    empty_categories = []
    for module in modules_out:
        for category in module["categories"]:
            active_people = [person for person in category["recipients"] if person.get("active", True)]
            if not active_people:
                empty_categories.append(
                    {
                        "event_key": category["event_key"],
                        "label": f"{module['label']} — {category['label']}",
                    }
                )
    return {
        "management_routing_active": routing_is_active(cursor, organization_id),
        "category_count": len(MANAGEMENT_CATEGORIES),
        "empty_categories": empty_categories,
        "modules": modules_out,
        "automatic": list(AUTOMATIC_NOTIFICATIONS),
        "unsupported_modules": ["Scheduling", "Performance", "Quality"],
    }


def set_routing_active(
    cursor,
    *,
    organization_id: int,
    active: bool,
    actor_user_id: int | None,
    confirm_incomplete: bool = False,
) -> dict[str, Any]:
    """Turn explicit routing on or off for one organization. Audited and reversible."""
    catalog = management_catalog(cursor, organization_id)
    empty_categories = catalog["empty_categories"]
    if active and empty_categories and not confirm_incomplete:
        raise NotificationAssignmentError(
            "incomplete_configuration",
            empty_categories=empty_categories,
        )
    cursor.execute(
        f"""
        INSERT INTO {ROUTING_TABLE}
          (organization_id, management_routing_active, updated_by_user_id, updated_at)
        VALUES (%s,%s,%s, NOW())
        ON DUPLICATE KEY UPDATE
          management_routing_active=VALUES(management_routing_active),
          updated_by_user_id=VALUES(updated_by_user_id),
          updated_at=NOW()
        """,
        (int(organization_id), 1 if active else 0, actor_user_id),
    )
    cursor.execute(
        f"""
        INSERT INTO {AUDIT_TABLE}
          (organization_id, event_key, action, actor_user_id, detail_json, created_at)
        VALUES (%s,%s,%s,%s,%s, NOW())
        """,
        (
            int(organization_id),
            "*",
            "routing_activated" if active else "routing_deactivated",
            actor_user_id,
            json.dumps(
                {
                    "management_routing_active": bool(active),
                    "confirm_incomplete": bool(confirm_incomplete),
                    "empty_categories": [row["event_key"] for row in empty_categories],
                }
            ),
        ),
    )
    return {
        "management_routing_active": bool(active),
        "empty_categories": empty_categories,
    }


def employee_name(first_name: Any, last_name: Any) -> str:
    return " ".join(part for part in (str(first_name or "").strip(), str(last_name or "").strip()) if part)


def search_active_users(cursor, organization_id: int, query: str) -> list[dict[str, Any]]:
    """Active application users in one organization.

    Payroll names are searchable, but a payroll row never creates an account
    and never becomes a recipient by itself. Roles and module access are ignored.
    """
    from backend.ta_helpers import table_exists

    needle = (query or "").strip()
    like = f"%{needle}%"
    if table_exists(cursor, "payroll_profiles"):
        cursor.execute(
            """
            SELECT u.id, u.username, u.display_name, pp.first_name, pp.last_name
            FROM users u
            LEFT JOIN payroll_profiles pp ON pp.user_id = u.id
            WHERE u.organization_id=%s AND COALESCE(u.active, 1)=1
              AND (
                %s=''
                OR u.username LIKE %s
                OR u.display_name LIKE %s
                OR pp.first_name LIKE %s
                OR pp.last_name LIKE %s
                OR CONCAT(TRIM(COALESCE(pp.first_name, '')), ' ', TRIM(COALESCE(pp.last_name, ''))) LIKE %s
              )
            ORDER BY u.display_name, u.username, u.id
            """,
            (int(organization_id), needle, like, like, like, like, like),
        )
    else:
        cursor.execute(
            """
            SELECT id, username, display_name
            FROM users
            WHERE organization_id=%s AND COALESCE(active, 1)=1
              AND (%s='' OR username LIKE %s OR display_name LIKE %s)
            ORDER BY display_name, username, id
            """,
            (int(organization_id), needle, like, like),
        )
    return [
        {
            "id": int(row["id"]),
            "username": row.get("username") or "",
            "display_name": row.get("display_name") or "",
            "employee_name": employee_name(row.get("first_name"), row.get("last_name")),
        }
        for row in cursor.fetchall() or []
    ]
