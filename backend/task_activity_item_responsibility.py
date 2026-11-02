"""Checklist-item responsibility on an existing Activity.

Master defaults live on ``task_activity_group_items``.
A date override is one row in ``task_activity_item_date_overrides``.
Completed check-offs keep ``responsibility_snapshot_json`` and are not rewritten.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.ta_helpers import invalidate_schema_cache, table_exists, table_has_column

MODE_TEAM = "team"
MODE_NAMED = "named"
MODES = frozenset({MODE_TEAM, MODE_NAMED})

OVERRIDES_TABLE = "task_activity_item_date_overrides"
GROUP_ITEMS_TABLE = "task_activity_group_items"
SESSIONS_TABLE = "cleaning_task_shared_sessions"
SESSION_ITEMS_TABLE = "cleaning_task_shared_session_items"


class ItemResponsibilityConflict(Exception):
    """Roster change still leaves a removed employee on an incomplete item."""

    def __init__(self, items: Sequence[Mapping[str, Any]]):
        self.items = [dict(item) for item in items]
        labels = ", ".join(str(item.get("task_name") or item.get("task_code") or "item") for item in self.items)
        super().__init__(
            "Resolve checklist responsibility before removing this employee. "
            f"Affected items: {labels}."
        )


class ItemResponsibilityError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def ensure_item_responsibility_schema(cursor) -> None:
    if table_exists(cursor, GROUP_ITEMS_TABLE):
        if not table_has_column(cursor, GROUP_ITEMS_TABLE, "responsibility_mode"):
            cursor.execute(
                f"ALTER TABLE {GROUP_ITEMS_TABLE} "
                "ADD COLUMN responsibility_mode VARCHAR(16) NOT NULL DEFAULT 'team'"
            )
        if not table_has_column(cursor, GROUP_ITEMS_TABLE, "responsibility_user_ids_json"):
            cursor.execute(
                f"ALTER TABLE {GROUP_ITEMS_TABLE} ADD COLUMN responsibility_user_ids_json TEXT NULL"
            )
        if not table_has_column(cursor, GROUP_ITEMS_TABLE, "section_label"):
            cursor.execute(
                f"ALTER TABLE {GROUP_ITEMS_TABLE} ADD COLUMN section_label VARCHAR(80) NULL"
            )
        if not table_has_column(cursor, GROUP_ITEMS_TABLE, "section_order"):
            cursor.execute(
                f"ALTER TABLE {GROUP_ITEMS_TABLE} ADD COLUMN section_order INT NOT NULL DEFAULT 0"
            )
        if not table_has_column(cursor, GROUP_ITEMS_TABLE, "instructions"):
            cursor.execute(
                f"ALTER TABLE {GROUP_ITEMS_TABLE} ADD COLUMN instructions TEXT NULL"
            )
        if not table_has_column(cursor, GROUP_ITEMS_TABLE, "active"):
            cursor.execute(
                f"ALTER TABLE {GROUP_ITEMS_TABLE} ADD COLUMN active TINYINT(1) NOT NULL DEFAULT 1"
            )
    if not table_exists(cursor, OVERRIDES_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {OVERRIDES_TABLE} (
              id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              group_item_id INT NOT NULL,
              business_date DATE NOT NULL,
              responsibility_mode VARCHAR(16) NOT NULL,
              user_ids_json TEXT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_taido_item_date (group_item_id, business_date),
              INDEX idx_taido_org_date (organization_id, business_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    for table in (SESSION_ITEMS_TABLE, "cleaning_task_activity_items"):
        if not table_exists(cursor, table):
            continue
        if not table_has_column(cursor, table, "responsibility_snapshot_json"):
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN responsibility_snapshot_json TEXT NULL")
        if not table_has_column(cursor, table, "definition_snapshot_json"):
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN definition_snapshot_json TEXT NULL")
    invalidate_schema_cache()


def parse_user_ids(raw: Any) -> list[int]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            raw = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            raw = [part for part in text.split(",") if part.strip()]
    if isinstance(raw, int):
        return [raw] if raw > 0 else []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    out: list[int] = []
    for value in raw:
        try:
            uid = int(value)
        except (TypeError, ValueError):
            continue
        if uid > 0 and uid not in out:
            out.append(uid)
    return out


def normalize_responsibility(mode: Any, user_ids: Any) -> tuple[str, list[int]]:
    """Anyone on Team is the default. Named requires at least one employee."""
    chosen = str(mode or MODE_TEAM).strip().lower()
    ids = parse_user_ids(user_ids)
    if chosen not in MODES:
        chosen = MODE_NAMED if ids else MODE_TEAM
    if chosen == MODE_NAMED and not ids:
        chosen = MODE_TEAM
    if chosen == MODE_TEAM:
        ids = []
    return chosen, ids


def responsibility_payload(mode: Any, user_ids: Any, names: Mapping[int, str] | None = None) -> dict[str, Any]:
    chosen, ids = normalize_responsibility(mode, user_ids)
    label_names = []
    for uid in ids:
        label_names.append((names or {}).get(int(uid)) or f"User #{uid}")
    return {
        "responsibility_mode": chosen,
        "responsibility_user_ids": ids,
        "responsibility_names": label_names,
        "responsibility_label": "Anyone on Team" if chosen == MODE_TEAM else ", ".join(label_names),
    }


def snapshot_json(mode: Any, user_ids: Any) -> str:
    chosen, ids = normalize_responsibility(mode, user_ids)
    return json.dumps({"responsibility_mode": chosen, "user_ids": ids})


def definition_snapshot(item: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze the checklist line as it was when a session started.

    Later edits to the master Activity do not rewrite this copy.
    """
    schema = item.get("input_schema") or []
    frozen = {
        "task_name": str(item.get("task_name") or item.get("name") or item.get("task_code") or ""),
        "instructions": (str(item.get("instructions") or "").strip() or None),
        "section_label": (str(item.get("section_label") or "").strip() or None),
        "section_order": int(item.get("section_order") or 0),
        "display_order": int(item.get("display_order") or 0),
        "completion_type": item.get("completion_type") or "simple",
        "input_schema": schema if isinstance(schema, list) else [],
    }
    for field in ("instructions_es", "section_label_es", "task_name_es"):
        text = str(item.get(field) or "").strip()
        if text:
            frozen[field] = text
    return frozen


def definition_snapshot_json(item: Mapping[str, Any]) -> str:
    return json.dumps(definition_snapshot(item))


def parse_definition_snapshot(raw: Any) -> dict[str, Any] | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, Mapping):
        data = dict(raw)
    else:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    return data if isinstance(data, dict) else None


def item_is_active(item: Mapping[str, Any] | None) -> bool:
    if not item:
        return False
    return item.get("active", True) is not False and item.get("active") != 0


def parse_snapshot(raw: Any) -> dict[str, Any] | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, Mapping):
        data = dict(raw)
    else:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    if not isinstance(data, Mapping):
        return None
    return responsibility_payload(data.get("responsibility_mode"), data.get("user_ids"))


def business_date_for_week(week_start: date, day_of_week: int) -> date:
    """Sunday-start week. day_of_week 0 is Sunday."""
    return week_start + timedelta(days=int(day_of_week))


def task_management_write_allowed(roles: set[str] | Sequence[str]) -> bool:
    """Rinse schedule viewers stay read-only. Hub managers may edit."""
    from backend.weekly_schedule_display_settings import is_rinse_schedule_viewer

    normalized = {str(role).upper() for role in (roles or [])}
    hub = {"ADMIN", "OPS", "MANAGER"}
    if is_rinse_schedule_viewer(normalized) and not (normalized & hub):
        return False
    return bool(normalized & hub)


def assert_named_employees_eligible(user_ids: Sequence[int], eligible: Sequence[int]) -> None:
    allowed = {int(uid) for uid in eligible}
    blocked = [int(uid) for uid in user_ids if int(uid) not in allowed]
    if blocked:
        raise ItemResponsibilityError(
            "Item responsibility can only name employees assigned to this Activity."
        )


def resolve_responsibility(
    item: Mapping[str, Any],
    override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Date override wins. The master item is left unchanged."""
    if override:
        return responsibility_payload(override.get("responsibility_mode"), override.get("user_ids") or override.get("user_ids_json"))
    return responsibility_payload(
        item.get("responsibility_mode"),
        item.get("responsibility_user_ids") or item.get("responsibility_user_ids_json"),
    )


def incomplete_items_naming_users(
    items: Sequence[Mapping[str, Any]],
    *,
    removed_user_ids: Sequence[int],
    session_items: Sequence[Mapping[str, Any]] | None = None,
    overrides_by_item_id: Mapping[int, Mapping[str, Any]] | None = None,
    eligible_user_ids: Sequence[int] | None = None,
) -> list[dict[str, Any]]:
    """Incomplete items still naming someone who is not on this date's roster.

    Completed session rows are ignored so their snapshots stay historical.
    When ``eligible_user_ids`` is omitted, only explicit removals are checked.
    """
    removed = {int(uid) for uid in removed_user_ids}
    eligible = None if eligible_user_ids is None else {int(uid) for uid in eligible_user_ids}
    if not removed and eligible is None:
        return []
    by_code = {}
    for row in session_items or []:
        code = str(row.get("task_code") or "")
        if code:
            by_code[code] = row
    conflicts = []
    for item in items or []:
        code = str(item.get("task_code") or "")
        session = by_code.get(code)
        if session is not None and str(session.get("status") or "") == "completed":
            continue
        override = (overrides_by_item_id or {}).get(int(item.get("id") or 0))
        if override:
            resolved = resolve_responsibility(item, override)
        elif session is not None:
            resolved = parse_snapshot(session.get("responsibility_snapshot_json")) or resolve_responsibility(item, None)
        else:
            resolved = resolve_responsibility(item, None)
        named = set(resolved.get("responsibility_user_ids") or [])
        hit = sorted(named & removed)
        outside = sorted(named - eligible) if eligible is not None else []
        if not hit and not outside:
            continue
        conflicts.append(
            {
                "group_item_id": int(item.get("id") or 0),
                "task_code": code,
                "task_name": item.get("task_name") or item.get("name") or code,
                "responsibility_mode": resolved.get("responsibility_mode"),
                "responsibility_user_ids": list(resolved.get("responsibility_user_ids") or []),
                "removed_user_ids": hit,
                "ineligible_user_ids": outside,
            }
        )
    return conflicts


def _override_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "group_item_id": int(row.get("group_item_id") or 0),
        "business_date": str(row.get("business_date") or "")[:10],
        "responsibility_mode": row.get("responsibility_mode"),
        "user_ids": parse_user_ids(row.get("user_ids_json")),
    }


def load_overrides_for_items(
    cursor,
    organization_id: int,
    group_item_ids: Sequence[int],
    business_date: date,
) -> dict[int, dict[str, Any]]:
    ids = [int(item_id) for item_id in group_item_ids if int(item_id or 0) > 0]
    if not ids or not table_exists(cursor, OVERRIDES_TABLE):
        return {}
    placeholders = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT group_item_id, business_date, responsibility_mode, user_ids_json
        FROM {OVERRIDES_TABLE}
        WHERE organization_id=%s AND business_date=%s AND group_item_id IN ({placeholders})
        """,
        (int(organization_id), business_date, *ids),
    )
    out = {}
    for row in cursor.fetchall() or []:
        if isinstance(row, dict):
            parsed = _override_row(row)
            out[parsed["group_item_id"]] = parsed
    return out


def load_session_items_for_role_date(cursor, organization_id: int, role: str, business_date: date) -> list[dict]:
    if not table_exists(cursor, SESSIONS_TABLE):
        return []
    cursor.execute(
        f"""
        SELECT i.task_code, i.status, i.responsibility_snapshot_json, i.completed_by_user_id, i.completed_at
        FROM {SESSION_ITEMS_TABLE} i
        INNER JOIN {SESSIONS_TABLE} s ON s.id = i.shared_session_id
        WHERE s.organization_id=%s AND s.role=%s AND s.business_date=%s
        """,
        (int(organization_id), str(role), business_date),
    )
    return [dict(row) for row in (cursor.fetchall() or []) if isinstance(row, dict)]


def save_date_overrides(
    cursor,
    organization_id: int,
    *,
    business_date: date,
    items_by_code: Mapping[str, Mapping[str, Any]],
    overrides: Sequence[Mapping[str, Any]],
    eligible_user_ids: Sequence[int],
    role: str | None = None,
) -> None:
    """Write one date only. Does not update the master item or other dates."""
    ensure_item_responsibility_schema(cursor)
    by_id = {int(item.get("id") or 0): item for item in items_by_code.values()}
    by_code = {str(item.get("task_code") or ""): item for item in items_by_code.values()}
    for raw in overrides or []:
        item = None
        if raw.get("group_item_id") is not None:
            item = by_id.get(int(raw.get("group_item_id") or 0))
        if item is None:
            item = by_code.get(str(raw.get("task_code") or ""))
        if not item:
            raise ItemResponsibilityError("That checklist item is not on this Activity.")
        requested_mode = str(raw.get("responsibility_mode") or MODE_TEAM).strip().lower()
        requested_ids = parse_user_ids(raw.get("user_ids") if raw.get("user_ids") is not None else raw.get("user_ids_json"))
        if requested_mode == MODE_NAMED and not requested_ids:
            raise ItemResponsibilityError(
                "Choose at least one employee for a named item, or switch it to Anyone on Team."
            )
        mode, ids = normalize_responsibility(requested_mode, requested_ids)
        if mode == MODE_NAMED:
            assert_named_employees_eligible(ids, eligible_user_ids)
        cursor.execute(
            f"""
            INSERT INTO {OVERRIDES_TABLE}
              (organization_id, group_item_id, business_date, responsibility_mode, user_ids_json)
            VALUES (%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              responsibility_mode=VALUES(responsibility_mode),
              user_ids_json=VALUES(user_ids_json)
            """,
            (
                int(organization_id),
                int(item["id"]),
                business_date,
                mode,
                json.dumps(ids),
            ),
        )
        _refresh_pending_snapshot(
            cursor,
            organization_id,
            business_date=business_date,
            task_code=str(item.get("task_code") or ""),
            snapshot=snapshot_json(mode, ids),
            role=role,
        )


def _refresh_pending_snapshot(
    cursor,
    organization_id: int,
    *,
    business_date: date,
    task_code: str,
    snapshot: str,
    role: str | None = None,
) -> None:
    """Pending rows follow the date override. Completed rows stay as recorded."""
    if table_exists(cursor, SESSIONS_TABLE) and table_has_column(
        cursor, SESSION_ITEMS_TABLE, "responsibility_snapshot_json"
    ):
        role_sql = " AND s.role=%s" if role else ""
        params: list[Any] = [snapshot, int(organization_id), business_date, task_code]
        if role:
            params.append(str(role))
        cursor.execute(
            f"""
            UPDATE {SESSION_ITEMS_TABLE} i
            INNER JOIN {SESSIONS_TABLE} s ON s.id = i.shared_session_id
            SET i.responsibility_snapshot_json=%s
            WHERE s.organization_id=%s AND s.business_date=%s AND i.task_code=%s
              AND i.status<>'completed'{role_sql}
            """,
            tuple(params),
        )
    activity_items = "cleaning_task_activity_items"
    if (
        role
        and table_exists(cursor, activity_items)
        and table_has_column(cursor, activity_items, "responsibility_snapshot_json")
        and table_exists(cursor, "cleaning_task_activities")
    ):
        cursor.execute(
            f"""
            UPDATE {activity_items} i
            INNER JOIN cleaning_task_activities a ON a.id = i.activity_id
            SET i.responsibility_snapshot_json=%s
            WHERE a.organization_id=%s AND a.business_date=%s AND a.role=%s AND i.task_code=%s
              AND i.status<>'completed'
            """,
            (snapshot, int(organization_id), business_date, str(role), task_code),
        )


def apply_roster_responsibility(
    cursor,
    organization_id: int,
    *,
    role: str,
    business_date: date,
    removed_user_ids: Sequence[int],
    eligible_user_ids: Sequence[int],
    overrides: Sequence[Mapping[str, Any]] | None,
    group_items: Sequence[Mapping[str, Any]],
) -> None:
    """Save date overrides, then block if a removed employee is still responsible for open work."""
    indexed = {str(item.get("task_code") or ""): item for item in group_items}
    if overrides:
        save_date_overrides(
            cursor,
            organization_id,
            business_date=business_date,
            items_by_code=indexed,
            overrides=overrides,
            eligible_user_ids=eligible_user_ids,
            role=role,
        )
    override_rows = load_overrides_for_items(
        cursor,
        organization_id,
        [int(item.get("id") or 0) for item in group_items],
        business_date,
    )
    session_items = load_session_items_for_role_date(cursor, organization_id, role, business_date)
    conflicts = incomplete_items_naming_users(
        group_items,
        removed_user_ids=removed_user_ids,
        session_items=session_items,
        overrides_by_item_id=override_rows,
        eligible_user_ids=eligible_user_ids,
    )
    if conflicts:
        raise ItemResponsibilityConflict(conflicts)


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def attach_checklist_responsibilities(
    cursor,
    organization_id: int,
    responsibilities: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Resolved checklist responsibility for each assignment date.

    A saved date override replaces the master names. The master row is not changed.
    """
    from backend.task_activity_groups import get_activity_group

    rows = [dict(item) for item in responsibilities or []]
    groups: dict[str, dict[str, Any]] = {}
    for item in rows:
        role = str(item.get("role") or "")
        if not role.startswith("agroup_") or role in groups:
            continue
        try:
            group = get_activity_group(cursor, int(organization_id), role_code=role)
        except Exception:
            group = None
        groups[role] = group or {}
    for item in rows:
        group = groups.get(str(item.get("role") or ""))
        members = [
            member
            for member in ((group or {}).get("items") or [])
            if item_is_active(member)
        ]
        if not members:
            continue
        week = _as_date(item.get("week_start"))
        if week is None:
            continue
        business_date = business_date_for_week(week, int(item.get("day_of_week") or 0))
        overrides = load_overrides_for_items(
            cursor,
            int(organization_id),
            [int(member.get("id") or 0) for member in members],
            business_date,
        )
        resolved = []
        for member in members:
            override = overrides.get(int(member.get("id") or 0))
            payload = resolve_responsibility(member, override)
            resolved.append(
                {
                    "group_item_id": int(member.get("id") or 0),
                    "task_code": member.get("task_code"),
                    "task_name": member.get("task_name") or member.get("task_code"),
                    "responsibility_mode": payload.get("responsibility_mode"),
                    "responsibility_user_ids": list(payload.get("responsibility_user_ids") or []),
                    "responsibility_label": payload.get("responsibility_label"),
                    "date_override": bool(override),
                }
            )
        item["checklist_items"] = resolved
    return rows


def split_items_for_employee(items: Sequence[Mapping[str, Any]], user_id: int) -> dict[str, list]:
    """Each item is either mine or the team's. Anyone on Team is mine."""
    mine: list[Mapping[str, Any]] = []
    other: list[Mapping[str, Any]] = []
    uid = int(user_id or 0)
    for item in items or []:
        mode = str(item.get("responsibility_mode") or MODE_TEAM)
        ids = parse_user_ids(item.get("responsibility_user_ids"))
        if mode != MODE_NAMED or not ids or uid in ids:
            mine.append(item)
        else:
            other.append(item)
    required = [item for item in items or [] if item.get("required", True)]
    done = [
        item
        for item in required
        if str(item.get("status") or "") in {"completed", "approved", "verified"}
    ]
    return {
        "my_items": mine,
        "other_items": other,
        "required_total": len(required),
        "required_done": len(done),
    }
