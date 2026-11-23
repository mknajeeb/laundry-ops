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


class NotificationAssignmentError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def ensure_assignment_tables(cursor) -> None:
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {ROUTING_TABLE} (
          organization_id INT NOT NULL PRIMARY KEY,
          management_routing_active TINYINT(1) NOT NULL DEFAULT 0,
          updated_by_user_id INT NULL,
          updated_at DATETIME NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SETTINGS_TABLE} (
          organization_id INT NOT NULL,
          event_key VARCHAR(64) NOT NULL,
          enabled TINYINT(1) NOT NULL DEFAULT 1,
          updated_by_user_id INT NULL,
          updated_at DATETIME NOT NULL,
          PRIMARY KEY (organization_id, event_key)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {RECIPIENT_TABLE} (
          organization_id INT NOT NULL,
          event_key VARCHAR(64) NOT NULL,
          user_id INT NOT NULL,
          assigned_by_user_id INT NULL,
          assigned_at DATETIME NOT NULL,
          PRIMARY KEY (organization_id, event_key, user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          event_key VARCHAR(64) NOT NULL,
          action VARCHAR(32) NOT NULL,
          actor_user_id INT NULL,
          detail_json TEXT NULL,
          created_at DATETIME NOT NULL,
          KEY idx_notif_assign_audit_org (organization_id, id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


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
        cursor.execute(
            f"""
            SELECT r.event_key, r.user_id, u.username, u.display_name, u.active
            FROM {RECIPIENT_TABLE} r
            JOIN users u ON u.id = r.user_id AND u.organization_id = r.organization_id
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
    return {
        "management_routing_active": routing_is_active(cursor, organization_id),
        "modules": list(modules.values()),
        "automatic": list(AUTOMATIC_NOTIFICATIONS),
        "unsupported_modules": ["Scheduling", "Performance", "Quality"],
    }


def search_active_users(cursor, organization_id: int, query: str) -> list[dict[str, Any]]:
    like = f"%{(query or '').strip()}%"
    cursor.execute(
        """
        SELECT id, username, display_name
        FROM users
        WHERE organization_id=%s AND COALESCE(active, 1)=1
          AND (username LIKE %s OR display_name LIKE %s OR %s='')
        ORDER BY display_name, username, id
        LIMIT 20
        """,
        (int(organization_id), like, like, (query or "").strip()),
    )
    return [
        {
            "id": int(row["id"]),
            "username": row.get("username") or "",
            "display_name": row.get("display_name") or "",
        }
        for row in cursor.fetchall() or []
    ]
