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

from backend.ta_helpers import (
    invalidate_table_schema,
    once_per_cursor,
    remember_column,
    table_exists,
    table_has_column,
)
from backend.task_catalog import (
    clear_task_read_cache,
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


@once_per_cursor("task_activity_groups")
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
              require_checklist_before_completion TINYINT(1) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_tag_org_code (organization_id, code),
              INDEX idx_tag_org_order (organization_id, display_order)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        invalidate_table_schema(GROUPS_TABLE)
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
        invalidate_table_schema(GROUP_ITEMS_TABLE)
    try:
        from backend.task_verification_policy import ensure_verification_policy_schema

        ensure_verification_policy_schema(cursor)
    except Exception:
        pass
    if table_exists(cursor, GROUPS_TABLE) and not table_has_column(
        cursor, GROUPS_TABLE, "instructions"
    ):
        cursor.execute(f"ALTER TABLE {GROUPS_TABLE} ADD COLUMN instructions TEXT NULL")
        remember_column(GROUPS_TABLE, "instructions")
    for column in ("instructions_es", "name_es"):
        if table_exists(cursor, GROUPS_TABLE) and not table_has_column(cursor, GROUPS_TABLE, column):
            cursor.execute(f"ALTER TABLE {GROUPS_TABLE} ADD COLUMN {column} TEXT NULL")
            remember_column(GROUPS_TABLE, column)
    for column in ("instructions_es", "section_label_es", "task_name_es"):
        if table_exists(cursor, GROUP_ITEMS_TABLE) and not table_has_column(
            cursor, GROUP_ITEMS_TABLE, column
        ):
            cursor.execute(f"ALTER TABLE {GROUP_ITEMS_TABLE} ADD COLUMN {column} TEXT NULL")
            remember_column(GROUP_ITEMS_TABLE, column)
    if table_exists(cursor, GROUPS_TABLE) and not table_has_column(
        cursor, GROUPS_TABLE, "require_checklist_before_completion"
    ):
        # NULL preserves existing groups. New groups set the flag explicitly.
        cursor.execute(
            f"ALTER TABLE {GROUPS_TABLE} ADD COLUMN require_checklist_before_completion TINYINT(1) NULL"
        )
        remember_column(GROUPS_TABLE, "require_checklist_before_completion")
    try:
        from backend.task_activity_item_responsibility import ensure_item_responsibility_schema

        ensure_item_responsibility_schema(cursor)
    except Exception:
        pass


def _slug_code(raw: str, *, max_len: int = 28) -> str:
    text = re.sub(r"[^a-z0-9_]+", "_", str(raw or "").strip().lower())
    text = re.sub(r"_+", "_", text).strip("_")
    return (text[:max_len] or "group").strip("_") or "group"


def _schedule_role_code(group_code: str) -> str:
    slug = activity_group_slug_from_code(group_code)
    return f"{ACTIVITY_GROUP_PREFIX}{slug}"[:40]


def _serialize_require_checklist_flag(value: Any) -> bool | None:
    """None means the stored column is unset. It is not rewritten."""
    if value in (None, ""):
        return None
    if value in (1, True, "1"):
        return True
    if value in (0, False, "0"):
        return False
    return None


def group_has_required_checklist_items(items: Sequence[Mapping[str, Any]] | None) -> bool:
    for item in items or []:
        if isinstance(item, Mapping) and bool(item.get("required", True)):
            return True
    return False


def default_require_checklist_before_completion(items: Sequence[Mapping[str, Any]]) -> int:
    """New groups with a required checklist item start with the finish gate on."""
    return 1 if group_has_required_checklist_items(items) else 0


def participation_finish_allowed_with_open_checklist(
    value: Any,
    *,
    shared: bool = False,
    has_required_items: bool | None = None,
) -> bool:
    """Whether this employee may finish while required checklist items are still open.

    Explicit OFF allows it. Explicit ON blocks it.
    An unset value is ON when the group has required checklist items, and allows
    normal completion when it does not. The stored NULL is left as NULL.
    ``shared`` applies only when the caller does not say whether required items exist.
    """
    flag = _serialize_require_checklist_flag(value)
    if flag is False:
        return True
    if flag is True:
        return False
    if has_required_items is True:
        return False
    if has_required_items is False:
        return True
    return bool(shared)


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
        from backend.task_activity_item_responsibility import responsibility_payload

        responsibility = responsibility_payload(
            it.get("responsibility_mode"),
            it.get("responsibility_user_ids_json") or it.get("responsibility_user_ids"),
        )
        members.append(
            {
                "id": int(it["id"]) if it.get("id") is not None else None,
                "task_code": tc,
                "task_name": meta.get("name") or tc,
                "display_order": int(it.get("display_order") or 0),
                "required": bool(it.get("required", True)),
                "section_label": (str(it.get("section_label") or "").strip() or None),
                "section_order": int(it.get("section_order") or 0),
                "active": it.get("active", True) not in (0, False, "0"),
                "instructions": (str(it.get("instructions") or "").strip() or None)
                or meta.get("description")
                or meta.get("instructions")
                or None,
                "instructions_es": (str(it.get("instructions_es") or "").strip() or None),
                "section_label_es": (str(it.get("section_label_es") or "").strip() or None),
                "task_name_es": (str(it.get("task_name_es") or "").strip() or None),
                "completion_type": meta.get("completion_type"),
                "timer_enabled": meta.get("timer_enabled"),
                "verification_required": meta.get("verification_required"),
                "verification_method": meta.get("verification_method"),
                "verification_inherits": bool(meta.get("verification_inherits", False)),
                "input_schema": meta.get("input_schema") or [],
                **responsibility,
            }
        )
    members.sort(
        key=lambda m: (int(m.get("section_order") or 0), m["display_order"], m["task_name"].lower())
    )
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
        "instructions": (str(row.get("instructions") or "").strip() or None),
        "instructions_es": (str(row.get("instructions_es") or "").strip() or None),
        "name_es": (str(row.get("name_es") or "").strip() or None),
        "require_checklist_before_completion": _serialize_require_checklist_flag(
            row.get("require_checklist_before_completion")
        ),
        "items": members,
        "item_count": len(members),
    }


def _task_has_execution_history(cursor, organization_id: int, task_code: str) -> bool:
    """True when a check-off already exists. The master row is deactivated, not deleted."""
    from backend.ta_helpers import table_exists

    code = str(task_code or "")
    if not code:
        return False
    for table in ("cleaning_task_shared_session_items", "cleaning_task_activity_items"):
        if not table_exists(cursor, table):
            continue
        cursor.execute(
            f"SELECT id FROM {table} WHERE organization_id=%s AND task_code=%s LIMIT 1",
            (int(organization_id), code),
        )
        if cursor.fetchone():
            return True
    return False


def _load_items(cursor, organization_id: int, group_ids: Sequence[int]) -> dict[int, list[dict]]:
    if not group_ids:
        return {}
    placeholders = ",".join(["%s"] * len(group_ids))
    cursor.execute(
        f"""
        SELECT *
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
    cache_key = (oid, group_id, str(code or ""), str(role_code or ""), bool(include_inactive))
    store = getattr(cursor, "_vw_activity_group", None)
    if isinstance(store, dict) and cache_key in store:
        return store[cache_key]
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
    result = _serialize_group(
        row, items.get(int(row["id"]), []), task_index=task_index, effective_policy=policy
    )
    if not isinstance(store, dict):
        store = {}
        try:
            setattr(cursor, "_vw_activity_group", store)
        except Exception:
            store = None
    if isinstance(store, dict):
        store[cache_key] = result
    return result


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
    clear_task_read_cache(cursor)
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
        from backend.task_activity_item_responsibility import normalize_responsibility

        if isinstance(item, str):
            tc = item.strip()
            required = True
            order = i * 10
            mode, user_ids = normalize_responsibility("team", [])
            section_label = None
            section_order = 0
            instructions = None
            instructions_es = None
            section_label_es = None
            task_name_es = None
            active = True
        else:
            tc = str(item.get("task_code") or item.get("code") or "").strip()
            required = bool(item.get("required", True))
            order = int(item.get("display_order") if item.get("display_order") is not None else i * 10)
            mode, user_ids = normalize_responsibility(
                item.get("responsibility_mode"),
                item.get("responsibility_user_ids") or item.get("user_ids"),
            )
            section_label = (str(item.get("section_label") or "").strip() or None)
            section_order = int(item.get("section_order") or 0)
            instructions = (str(item.get("instructions") or "").strip()[:2000] or None)
            instructions_es = (
                (str(item.get("instructions_es") or "").strip()[:2000] or None)
                if "instructions_es" in item
                else None
            )
            section_label_es = (
                (str(item.get("section_label_es") or "").strip()[:200] or None)
                if "section_label_es" in item
                else None
            )
            task_name_es = (
                (str(item.get("task_name_es") or "").strip()[:200] or None)
                if "task_name_es" in item
                else None
            )
            active = item.get("active", True) not in (0, False, "0")
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
        normalized.append(
            {
                "task_code": tc,
                "display_order": order,
                "required": required,
                "responsibility_mode": mode,
                "responsibility_user_ids": user_ids,
                "section_label": section_label,
                "section_order": section_order,
                "instructions": instructions,
                "instructions_es": instructions_es if isinstance(item, Mapping) and "instructions_es" in item else None,
                "section_label_es": section_label_es if isinstance(item, Mapping) and "section_label_es" in item else None,
                "task_name_es": task_name_es if isinstance(item, Mapping) and "task_name_es" in item else None,
                "set_instructions_es": isinstance(item, Mapping) and "instructions_es" in item,
                "set_section_label_es": isinstance(item, Mapping) and "section_label_es" in item,
                "set_task_name_es": isinstance(item, Mapping) and "task_name_es" in item,
                "active": active,
            }
        )
    if not normalized:
        raise ActivityGroupError("Add at least one task to the activity group.")

    existing = None
    if group_id is not None:
        cursor.execute(
            f"SELECT * FROM {GROUPS_TABLE} WHERE organization_id=%s AND id=%s LIMIT 1",
            (oid, int(group_id)),
        )
        existing = cursor.fetchone()
        if not existing:
            raise ActivityGroupError("Activity group not found.", status=404)
    if "require_checklist_before_completion" in payload:
        require_flag = 1 if payload.get("require_checklist_before_completion") in (1, True, "1") else 0
    elif existing is not None:
        require_flag = _serialize_require_checklist_flag(
            existing.get("require_checklist_before_completion")
        )
        if require_flag is True:
            require_flag = 1
        elif require_flag is False:
            require_flag = 0
    else:
        require_flag = default_require_checklist_before_completion(normalized)

    if group_id is not None:
        code = str(existing["code"])
        cursor.execute(
            f"""
            UPDATE {GROUPS_TABLE}
            SET name=%s, category_code=%s, display_order=%s, active=%s,
                verification_inherits=%s, verification_required=%s,
                verification_method=%s, verification_timing=%s, verifier_config_json=%s,
                require_checklist_before_completion=%s
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
                require_flag,
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
               verification_timing, verifier_config_json, require_checklist_before_completion)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
                require_flag,
            ),
        )
        gid = int(cursor.lastrowid)

    if "instructions" in payload and table_has_column(cursor, GROUPS_TABLE, "instructions"):
        text = str(payload.get("instructions") or "").strip()[:2000] or None
        cursor.execute(
            f"UPDATE {GROUPS_TABLE} SET instructions=%s WHERE organization_id=%s AND id=%s",
            (text, oid, gid),
        )
    for column in ("instructions_es", "name_es"):
        if column in payload and table_has_column(cursor, GROUPS_TABLE, column):
            text = str(payload.get(column) or "").strip()[:2000] or None
            cursor.execute(
                f"UPDATE {GROUPS_TABLE} SET {column}=%s WHERE organization_id=%s AND id=%s",
                (text, oid, gid),
            )

    import json as _json

    from backend.ta_helpers import table_has_column as _has_col

    existing_rows = _load_items(cursor, oid, [gid]).get(gid, [])
    by_code = {str(row.get("task_code") or ""): row for row in existing_rows}
    keep_codes = {item["task_code"] for item in normalized}
    has_responsibility = _has_col(cursor, GROUP_ITEMS_TABLE, "responsibility_mode")
    has_item_instructions = _has_col(cursor, GROUP_ITEMS_TABLE, "instructions")
    has_item_active = _has_col(cursor, GROUP_ITEMS_TABLE, "active")
    for item in normalized:
        user_json = _json.dumps(item.get("responsibility_user_ids") or [])
        current = by_code.get(item["task_code"])
        if current and current.get("id") is not None:
            if has_responsibility:
                extra_sql = ""
                extra_params: list[Any] = []
                if has_item_instructions:
                    extra_sql += ", instructions=%s"
                    extra_params.append(item.get("instructions"))
                for column, flag in (
                    ("instructions_es", "set_instructions_es"),
                    ("section_label_es", "set_section_label_es"),
                    ("task_name_es", "set_task_name_es"),
                ):
                    if item.get(flag) and _has_col(cursor, GROUP_ITEMS_TABLE, column):
                        extra_sql += f", {column}=%s"
                        extra_params.append(item.get(column))
                if has_item_active:
                    extra_sql += ", active=%s"
                    extra_params.append(1 if item.get("active", True) else 0)
                cursor.execute(
                    f"""
                    UPDATE {GROUP_ITEMS_TABLE}
                    SET display_order=%s, required=%s, responsibility_mode=%s,
                        responsibility_user_ids_json=%s, section_label=%s, section_order=%s
                        {extra_sql}
                    WHERE id=%s AND organization_id=%s
                    """,
                    (
                        int(item["display_order"]),
                        1 if item["required"] else 0,
                        item.get("responsibility_mode") or "team",
                        user_json,
                        item.get("section_label"),
                        int(item.get("section_order") or 0),
                        *extra_params,
                        int(current["id"]),
                        oid,
                    ),
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE {GROUP_ITEMS_TABLE}
                    SET display_order=%s, required=%s
                    WHERE id=%s AND organization_id=%s
                    """,
                    (
                        int(item["display_order"]),
                        1 if item["required"] else 0,
                        int(current["id"]),
                        oid,
                    ),
                )
            continue
        if has_responsibility:
            columns = (
                "organization_id, group_id, task_code, display_order, required, "
                "responsibility_mode, responsibility_user_ids_json, section_label, section_order"
            )
            values: list[Any] = [
                oid,
                gid,
                item["task_code"],
                int(item["display_order"]),
                1 if item["required"] else 0,
                item.get("responsibility_mode") or "team",
                user_json,
                item.get("section_label"),
                int(item.get("section_order") or 0),
            ]
            if has_item_instructions:
                columns += ", instructions"
                values.append(item.get("instructions"))
            for column, flag in (
                ("instructions_es", "set_instructions_es"),
                ("section_label_es", "set_section_label_es"),
                ("task_name_es", "set_task_name_es"),
            ):
                if item.get(flag) and _has_col(cursor, GROUP_ITEMS_TABLE, column):
                    columns += f", {column}"
                    values.append(item.get(column))
            if has_item_active:
                columns += ", active"
                values.append(1 if item.get("active", True) else 0)
            placeholders = ",".join(["%s"] * len(values))
            cursor.execute(
                f"INSERT INTO {GROUP_ITEMS_TABLE} ({columns}) VALUES ({placeholders})",
                tuple(values),
            )
        else:
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
    for code, row in by_code.items():
        if code in keep_codes or row.get("id") is None:
            continue
        if has_item_active and _task_has_execution_history(cursor, oid, code):
            cursor.execute(
                f"UPDATE {GROUP_ITEMS_TABLE} SET active=0 WHERE id=%s AND organization_id=%s",
                (int(row["id"]), oid),
            )
            continue
        cursor.execute(
            f"DELETE FROM {GROUP_ITEMS_TABLE} WHERE id=%s AND organization_id=%s",
            (int(row["id"]), oid),
        )

    group = get_activity_group(cursor, oid, group_id=gid)
    assert group is not None
    _sync_schedule_role(cursor, oid, group)
    return group
