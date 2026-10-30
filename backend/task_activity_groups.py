"""Task Activity Groups — multiple tasks under one named timed activity.

Distinct from:
- ``assignment_group_id`` (several employees sharing one task assignment)
- verification checklists (next-day / peer verify wrappers)
- category display grouping in the PIN UI

A group is assigned on the weekly schedule via a synthetic role code
``agroup_<slug>`` (untimed catalog row). Execution uses one parent activity
timer plus per-item completion rows (no duration attributed per item).
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Optional, Sequence

from backend.ta_helpers import invalidate_schema_cache, table_exists, table_has_column
from backend.task_catalog import (
    ensure_task_catalog_tables,
    get_task_definition,
    list_categories,
    list_task_definitions,
)
from backend.weekly_schedule_roles import (
    CUSTOM_ROLE_PREFIX,
    ROLE_NAME_MAX,
    ensure_weekly_schedule_roles_table,
)

GROUPS_TABLE = "task_activity_groups"
GROUP_ITEMS_TABLE = "task_activity_group_items"
ACTIVITY_GROUP_PREFIX = "agroup_"
KIND_ACTIVITY_GROUP = "activity_group"


class ActivityGroupError(Exception):
    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def is_activity_group_code(code: Any) -> bool:
    return str(code or "").strip().startswith(ACTIVITY_GROUP_PREFIX)


def activity_group_slug_from_code(code: Any) -> str:
    text = str(code or "").strip()
    if text.startswith(ACTIVITY_GROUP_PREFIX):
        return text[len(ACTIVITY_GROUP_PREFIX) :]
    return text


def ensure_task_activity_group_tables(cursor) -> None:
    ensure_task_catalog_tables(cursor)
    if not table_exists(cursor, GROUPS_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {GROUPS_TABLE} (
              id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              code VARCHAR(40) NOT NULL,
              name VARCHAR(80) NOT NULL,
              category_code VARCHAR(40) NOT NULL,
              display_order INT NOT NULL DEFAULT 0,
              active TINYINT(1) NOT NULL DEFAULT 1,
              verification_inherits TINYINT(1) NOT NULL DEFAULT 1,
              verification_required TINYINT(1) NULL,
              verification_method VARCHAR(32) NULL,
              verification_timing VARCHAR(32) NULL,
              verifier_config_json TEXT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_tag_org_code (organization_id, code),
              INDEX idx_tag_org_order (organization_id, display_order)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    if not table_exists(cursor, GROUP_ITEMS_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {GROUP_ITEMS_TABLE} (
              id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              group_id INT NOT NULL,
              task_code VARCHAR(64) NOT NULL,
              display_order INT NOT NULL DEFAULT 0,
              required TINYINT(1) NOT NULL DEFAULT 1,
              UNIQUE KEY uq_tagi (group_id, task_code),
              INDEX idx_tagi_org (organization_id, group_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    try:
        from backend.task_verification_policy import ensure_verification_policy_schema

        ensure_verification_policy_schema(cursor)
    except Exception:
        pass
    invalidate_schema_cache()


def _slug_code(raw: str, *, max_len: int = 28) -> str:
    text = re.sub(r"[^a-z0-9_]+", "_", str(raw or "").strip().lower())
    text = re.sub(r"_+", "_", text).strip("_")
    return (text[:max_len] or "group").strip("_") or "group"


def _schedule_role_code(group_code: str) -> str:
    slug = activity_group_slug_from_code(group_code)
    return f"{ACTIVITY_GROUP_PREFIX}{slug}"[:40]


def _serialize_group(
    row: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]] | None = None,
    *,
    task_index: Mapping[str, Mapping[str, Any]] | None = None,
    effective_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    code = str(row.get("code") or "")
    role_code = _schedule_role_code(code)
    inherits = bool(row.get("verification_inherits", True))
    members = []
    for it in items or []:
        tc = str(it.get("task_code") or "")
        meta = (task_index or {}).get(tc) or {}
        members.append(
            {
                "task_code": tc,
                "task_name": meta.get("name") or tc,
                "display_order": int(it.get("display_order") or 0),
                "required": bool(it.get("required", True)),
                "completion_type": meta.get("completion_type"),
                "timer_enabled": meta.get("timer_enabled"),
                "verification_required": meta.get("verification_required"),
                "verification_method": meta.get("verification_method"),
                "verification_inherits": bool(meta.get("verification_inherits", False)),
                "input_schema": meta.get("input_schema") or [],
            }
        )
    members.sort(key=lambda m: (m["display_order"], m["task_name"].lower()))
    policy = effective_policy or {}
    return {
        "id": int(row["id"]),
        "organization_id": int(row["organization_id"]),
        "code": code,
        "role_code": role_code,
        "name": str(row.get("name") or ""),
        "category_code": str(row.get("category_code") or ""),
        "display_order": int(row.get("display_order") or 0),
        "active": bool(row.get("active", True)),
        "kind": KIND_ACTIVITY_GROUP,
        "verification_inherits": inherits,
        "verification_required": bool(
            policy.get("verification_required", row.get("verification_required", True))
        ),
        "verification_method": str(
            policy.get("verification_method")
            or row.get("verification_method")
            or "supervisor"
        ),
        "verification_timing": str(
            policy.get("verification_timing")
            or row.get("verification_timing")
            or "same_shift"
        ),
        "verifier_config": policy.get("verifier_config")
        if isinstance(policy.get("verifier_config"), dict)
        else {},
        "verification_source": policy.get("source") or ("global" if inherits else "activity_group"),
        "verification_policy_label": (
            "Inherited from global default" if inherits else "Group override"
        ),
        "items": members,
        "item_count": len(members),
    }


def _load_items(cursor, organization_id: int, group_ids: Sequence[int]) -> dict[int, list[dict]]:
    if not group_ids:
        return {}
    placeholders = ",".join(["%s"] * len(group_ids))
    cursor.execute(
        f"""
        SELECT id, organization_id, group_id, task_code, display_order, required
        FROM {GROUP_ITEMS_TABLE}
        WHERE organization_id=%s AND group_id IN ({placeholders})
        ORDER BY display_order ASC, id ASC
        """,
        (int(organization_id), *[int(g) for g in group_ids]),
    )
    out: dict[int, list[dict]] = {}
    for row in cursor.fetchall() or []:
        out.setdefault(int(row["group_id"]), []).append(row)
    return out


def list_activity_groups(
    cursor,
    organization_id: int,
    *,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    ensure_task_activity_group_tables(cursor)
    oid = int(organization_id)
    sql = f"SELECT * FROM {GROUPS_TABLE} WHERE organization_id=%s"
    params: list[Any] = [oid]
    if not include_inactive:
        sql += " AND active=1"
    sql += " ORDER BY display_order ASC, name ASC"
    cursor.execute(sql, tuple(params))
    rows = list(cursor.fetchall() or [])
    items = _load_items(cursor, oid, [int(r["id"]) for r in rows])
    task_index = {t["code"]: t for t in list_task_definitions(cursor, oid, include_inactive=True)}
    from backend.task_verification_policy import resolve_verification_policy

    out = []
    for r in rows:
        policy = resolve_verification_policy(cursor, oid, activity_group=r)
        out.append(
            _serialize_group(
                r, items.get(int(r["id"]), []), task_index=task_index, effective_policy=policy
            )
        )
    return out


def get_activity_group(
    cursor,
    organization_id: int,
    *,
    group_id: int | None = None,
    code: str | None = None,
    role_code: str | None = None,
    include_inactive: bool = True,
) -> dict[str, Any] | None:
    ensure_task_activity_group_tables(cursor)
    oid = int(organization_id)
    if group_id is not None:
        cursor.execute(
            f"SELECT * FROM {GROUPS_TABLE} WHERE organization_id=%s AND id=%s LIMIT 1",
            (oid, int(group_id)),
        )
    else:
        raw = str(role_code or code or "").strip()
        if is_activity_group_code(raw):
            raw = activity_group_slug_from_code(raw)
            # stored code may be full agroup_ or slug-only; try both
            cursor.execute(
                f"""
                SELECT * FROM {GROUPS_TABLE}
                WHERE organization_id=%s AND (code=%s OR code=%s)
                LIMIT 1
                """,
                (oid, raw, f"{ACTIVITY_GROUP_PREFIX}{raw}"),
            )
        else:
            cursor.execute(
                f"SELECT * FROM {GROUPS_TABLE} WHERE organization_id=%s AND code=%s LIMIT 1",
                (oid, raw),
            )
    row = cursor.fetchone()
    if not row:
        return None
    if not include_inactive and not bool(row.get("active", True)):
        return None
    items = _load_items(cursor, oid, [int(row["id"])])
    task_index = {t["code"]: t for t in list_task_definitions(cursor, oid, include_inactive=True)}
    from backend.task_verification_policy import resolve_verification_policy

    policy = resolve_verification_policy(cursor, oid, activity_group=row)
    return _serialize_group(
        row, items.get(int(row["id"]), []), task_index=task_index, effective_policy=policy
    )


def _sync_schedule_role(cursor, organization_id: int, group: Mapping[str, Any]) -> None:
    """Keep a synthetic role so Weekly Schedule can assign the group.

    Syncs the group's *effective* verification policy (never silently forces none).
    Parent group timers still complete without pending verification; item children
    carry per-task verification snapshots at submit time.
    """
    ensure_weekly_schedule_roles_table(cursor)
    role_code = _schedule_role_code(str(group["code"]))
    name = str(group.get("name") or role_code)[:ROLE_NAME_MAX]
    from backend.task_catalog import upsert_task_definition
    from backend.task_verification_policy import resolve_verification_policy

    policy = resolve_verification_policy(cursor, int(organization_id), activity_group=group)
    group_inherits = bool(group.get("verification_inherits", True))
    upsert_task_definition(
        cursor,
        int(organization_id),
        role_code,
        {
            "name": name,
            "category_code": str(group.get("category_code") or "intra_day"),
            "completion_type": "simple",
            "timer_enabled": True,
            "verification_required": bool(policy.get("verification_required", True)),
            "verification_method": str(policy.get("verification_method") or "supervisor"),
            "verification_timing": str(policy.get("verification_timing") or "same_shift"),
            "verifier_config": policy.get("verifier_config") or {},
            # Mirror whether the group inherits global or has an explicit override.
            "verification_inherits": group_inherits,
            "active": bool(group.get("active", True)),
            "display_order": int(group.get("display_order") or 0),
        },
    )


def upsert_activity_group(
    cursor,
    organization_id: int,
    payload: Mapping[str, Any],
    *,
    group_id: int | None = None,
) -> dict[str, Any]:
    ensure_task_activity_group_tables(cursor)
    oid = int(organization_id)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ActivityGroupError("Activity group name is required.")
    category_code = str(payload.get("category_code") or "").strip()
    cats = {c["code"] for c in list_categories(cursor, oid, include_inactive=True)}
    if category_code not in cats:
        raise ActivityGroupError("Choose a valid task category.")
    display_order = int(payload.get("display_order") or 0)
    active = bool(payload.get("active", True))

    # Default: inherit global (never silent "none"). Explicit override required for none.
    inherits = bool(payload.get("verification_inherits", True))
    if "verification_inherits" not in payload and (
        "verification_method" in payload or "verification_required" in payload
    ):
        # Saving verification fields without inherits flag ⇒ explicit override.
        inherits = False
    verify_required = None
    verify_method = None
    verify_timing = None
    verifier_config_json = None
    if not inherits:
        from backend.task_verification_policy import _normalize_policy_fields

        method = str(payload.get("verification_method") or "supervisor")
        if payload.get("verification_required") is False or method == "none":
            method = "none"
        normalized = _normalize_policy_fields(
            verification_required=payload.get("verification_required", method != "none"),
            verification_method=method,
            verification_timing=payload.get("verification_timing"),
            verifier_config=payload.get("verifier_config")
            if "verifier_config" in payload
            else payload.get("verifier_config_json"),
        )
        verify_required = 1 if normalized["verification_required"] else 0
        verify_method = normalized["verification_method"]
        verify_timing = normalized["verification_timing"]
        verifier_config_json = json.dumps(normalized["verifier_config"])

    raw_items = payload.get("items")
    if raw_items is None and payload.get("task_codes") is not None:
        raw_items = [
            {"task_code": c, "display_order": i * 10, "required": True}
            for i, c in enumerate(payload.get("task_codes") or [])
        ]
    if not isinstance(raw_items, list) or not raw_items:
        raise ActivityGroupError("Add at least one task to the activity group.")

    task_index = {t["code"]: t for t in list_task_definitions(cursor, oid, include_inactive=True)}
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, item in enumerate(raw_items):
        if isinstance(item, str):
            tc = item.strip()
            required = True
            order = i * 10
        else:
            tc = str(item.get("task_code") or item.get("code") or "").strip()
            required = bool(item.get("required", True))
            order = int(item.get("display_order") if item.get("display_order") is not None else i * 10)
        if not tc:
            continue
        if is_activity_group_code(tc):
            raise ActivityGroupError("An activity group cannot contain another activity group.")
        if tc.startswith(CUSTOM_ROLE_PREFIX) or tc in task_index or True:
            # Allow known tasks only (active preferred).
            if tc not in task_index:
                raise ActivityGroupError(f"Unknown task code: {tc}")
            if is_activity_group_code(tc):
                raise ActivityGroupError("Invalid task membership.")
        if tc in seen:
            raise ActivityGroupError(f"Duplicate task in group: {tc}")
        seen.add(tc)
        normalized.append({"task_code": tc, "display_order": order, "required": required})
    if not normalized:
        raise ActivityGroupError("Add at least one task to the activity group.")

    if group_id is not None:
        cursor.execute(
            f"SELECT * FROM {GROUPS_TABLE} WHERE organization_id=%s AND id=%s LIMIT 1",
            (oid, int(group_id)),
        )
        existing = cursor.fetchone()
        if not existing:
            raise ActivityGroupError("Activity group not found.", status=404)
        code = str(existing["code"])
        cursor.execute(
            f"""
            UPDATE {GROUPS_TABLE}
            SET name=%s, category_code=%s, display_order=%s, active=%s,
                verification_inherits=%s, verification_required=%s,
                verification_method=%s, verification_timing=%s, verifier_config_json=%s
            WHERE organization_id=%s AND id=%s
            """,
            (
                name[:80],
                category_code,
                display_order,
                1 if active else 0,
                1 if inherits else 0,
                verify_required,
                verify_method,
                verify_timing,
                verifier_config_json,
                oid,
                int(group_id),
            ),
        )
        gid = int(group_id)
    else:
        requested = str(payload.get("code") or "").strip()
        slug = _slug_code(activity_group_slug_from_code(requested) or name)
        code = slug  # store short code; role_code adds prefix
        # ensure unique
        base = code
        n = 0
        while True:
            cursor.execute(
                f"SELECT id FROM {GROUPS_TABLE} WHERE organization_id=%s AND code=%s LIMIT 1",
                (oid, code),
            )
            if not cursor.fetchone():
                break
            n += 1
            code = f"{base}_{n}"[:40]
        cursor.execute(
            f"""
            INSERT INTO {GROUPS_TABLE}
              (organization_id, code, name, category_code, display_order, active,
               verification_inherits, verification_required, verification_method,
               verification_timing, verifier_config_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                oid,
                code,
                name[:80],
                category_code,
                display_order,
                1 if active else 0,
                1 if inherits else 0,
                verify_required,
                verify_method,
                verify_timing,
                verifier_config_json,
            ),
        )
        gid = int(cursor.lastrowid)

    cursor.execute(
        f"DELETE FROM {GROUP_ITEMS_TABLE} WHERE organization_id=%s AND group_id=%s",
        (oid, gid),
    )
    for item in normalized:
        cursor.execute(
            f"""
            INSERT INTO {GROUP_ITEMS_TABLE}
              (organization_id, group_id, task_code, display_order, required)
            VALUES (%s,%s,%s,%s,%s)
            """,
            (
                oid,
                gid,
                item["task_code"],
                int(item["display_order"]),
                1 if item["required"] else 0,
            ),
        )

    group = get_activity_group(cursor, oid, group_id=gid)
    assert group is not None
    _sync_schedule_role(cursor, oid, group)
    return group
