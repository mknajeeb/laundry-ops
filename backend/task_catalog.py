"""Configurable task categories and task-definition settings.

Categories are stable-coded records (start_of_day, intra_day, end_of_day, inventory).
Task definitions reuse ``weekly_schedule_roles`` rows with ``uses_time_slots=0``.
Existing cleaning task codes migrate to Intra-Day without rewriting history.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Optional, Sequence

from backend.ta_helpers import invalidate_schema_cache, table_exists, table_has_column
from backend.weekly_schedule_roles import (
    BUILTIN_ROLE_CODES,
    CLEANING_TASK_CODES,
    CUSTOM_ROLE_PREFIX,
    KIND_TASK,
    ROLE_NAME_MAX,
    ensure_weekly_schedule_roles_table,
    list_role_catalog,
)

CATEGORIES_TABLE = "task_categories"
CHECKLISTS_TABLE = "task_checklists"
CHECKLIST_ITEMS_TABLE = "task_checklist_items"
CHECKLIST_GROUPS_TABLE = "task_checklist_groups"
CHECKLIST_VERIFICATIONS_TABLE = "task_checklist_verifications"
DEFAULT_CHECKLIST_GROUP_NAME = "General"

COMPLETION_SIMPLE = "simple"
COMPLETION_INPUT = "input_required"
COMPLETION_TYPES = frozenset({COMPLETION_SIMPLE, COMPLETION_INPUT})

VERIFY_NONE = "none"
VERIFY_EMPLOYEE = "employee"
VERIFY_SUPERVISOR = "supervisor"
VERIFY_ROLE = "role"
VERIFY_METHODS = frozenset({VERIFY_NONE, VERIFY_EMPLOYEE, VERIFY_SUPERVISOR, VERIFY_ROLE})

VERIFY_TIMING_SAME_SHIFT = "same_shift"
VERIFY_TIMING_LATER_SHIFT = "later_shift"
VERIFY_TIMING_NEXT_DAY = "next_day"
VERIFY_TIMINGS = frozenset(
    {VERIFY_TIMING_SAME_SHIFT, VERIFY_TIMING_LATER_SHIFT, VERIFY_TIMING_NEXT_DAY}
)

INPUT_NUMBER = "number"
INPUT_TEXT = "text"
INPUT_YES_NO = "yes_no"
INPUT_CHECKBOX = "checkbox"
INPUT_CHECKLIST = "checklist"
INPUT_TYPES = frozenset(
    {INPUT_NUMBER, INPUT_TEXT, INPUT_YES_NO, INPUT_CHECKBOX, INPUT_CHECKLIST}
)

BUILTIN_CATEGORIES: tuple[dict[str, Any], ...] = (
    {"code": "start_of_day", "name": "Start of Day", "display_order": 10},
    {"code": "intra_day", "name": "Intra-Day", "display_order": 20},
    {"code": "end_of_day", "name": "End of Day", "display_order": 30},
    {"code": "inventory", "name": "Inventory", "display_order": 40},
)

# Existing cleaning task codes → Intra-Day (history keeps the same role code).
DEFAULT_TASK_CATEGORY_BY_CODE = {code: "intra_day" for code in CLEANING_TASK_CODES}

_TASK_CONFIG_COLUMNS: tuple[tuple[str, str], ...] = (
    ("task_category_code", "VARCHAR(40) NULL"),
    ("completion_type", "VARCHAR(32) NOT NULL DEFAULT 'simple'"),
    ("timer_enabled", "TINYINT(1) NOT NULL DEFAULT 1"),
    ("verification_required", "TINYINT(1) NOT NULL DEFAULT 1"),
    ("verification_method", "VARCHAR(32) NOT NULL DEFAULT 'supervisor'"),
    ("verification_timing", "VARCHAR(32) NOT NULL DEFAULT 'same_shift'"),
    ("verifier_config_json", "TEXT NULL"),
    ("input_schema_json", "TEXT NULL"),
    ("checklist_id", "INT NULL"),
)


class TaskCatalogError(Exception):
    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def ensure_task_catalog_tables(cursor) -> None:
    ensure_weekly_schedule_roles_table(cursor)
    if not table_exists(cursor, CATEGORIES_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {CATEGORIES_TABLE} (
              id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              code VARCHAR(40) NOT NULL,
              name VARCHAR(80) NOT NULL,
              display_order INT NOT NULL DEFAULT 0,
              active TINYINT(1) NOT NULL DEFAULT 1,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_task_cat_org_code (organization_id, code),
              INDEX idx_task_cat_org_order (organization_id, display_order)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    if not table_exists(cursor, CHECKLISTS_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {CHECKLISTS_TABLE} (
              id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              code VARCHAR(40) NOT NULL,
              name VARCHAR(80) NOT NULL,
              category_id INT NULL,
              verification_required TINYINT(1) NOT NULL DEFAULT 1,
              verification_method VARCHAR(32) NOT NULL DEFAULT 'employee',
              verification_timing VARCHAR(32) NOT NULL DEFAULT 'next_day',
              verifier_config_json TEXT NULL,
              active TINYINT(1) NOT NULL DEFAULT 1,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_task_cl_org_code (organization_id, code),
              INDEX idx_task_cl_org (organization_id, active)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    if not table_exists(cursor, CHECKLIST_ITEMS_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {CHECKLIST_ITEMS_TABLE} (
              id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              checklist_id INT NOT NULL,
              group_id INT NULL,
              task_code VARCHAR(64) NOT NULL,
              display_order INT NOT NULL DEFAULT 0,
              required TINYINT(1) NOT NULL DEFAULT 1,
              UNIQUE KEY uq_task_cli (checklist_id, task_code),
              INDEX idx_task_cli_org (organization_id, checklist_id),
              INDEX idx_task_cli_group (checklist_id, group_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    if not table_exists(cursor, CHECKLIST_GROUPS_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {CHECKLIST_GROUPS_TABLE} (
              id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              checklist_id INT NOT NULL,
              name VARCHAR(80) NOT NULL,
              display_order INT NOT NULL DEFAULT 0,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              INDEX idx_tclg_checklist (organization_id, checklist_id, display_order)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    if table_exists(cursor, CHECKLIST_ITEMS_TABLE) and not table_has_column(
        cursor, CHECKLIST_ITEMS_TABLE, "group_id"
    ):
        cursor.execute(
            f"ALTER TABLE {CHECKLIST_ITEMS_TABLE} ADD COLUMN group_id INT NULL"
        )
        try:
            cursor.execute(
                f"ALTER TABLE {CHECKLIST_ITEMS_TABLE} ADD INDEX idx_task_cli_group (checklist_id, group_id)"
            )
        except Exception:
            pass
    if not table_exists(cursor, CHECKLIST_VERIFICATIONS_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {CHECKLIST_VERIFICATIONS_TABLE} (
              id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              checklist_id INT NOT NULL,
              business_date DATE NOT NULL,
              status VARCHAR(32) NOT NULL,
              verified_by_user_id INT NULL,
              verified_at DATETIME NULL,
              rejection_reason VARCHAR(500) NULL,
              payload_json TEXT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_task_clv (organization_id, checklist_id, business_date),
              INDEX idx_task_clv_status (organization_id, status, business_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    for col, ddl in _TASK_CONFIG_COLUMNS:
        if not table_has_column(cursor, "weekly_schedule_roles", col):
            cursor.execute(f"ALTER TABLE weekly_schedule_roles ADD COLUMN {col} {ddl}")
    invalidate_schema_cache()


def _slug_code(raw: str, *, max_len: int = 40) -> str:
    text = re.sub(r"[^a-z0-9_]+", "_", str(raw or "").strip().lower())
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:max_len] or "category"


def seed_builtin_categories(cursor, organization_id: int) -> list[dict[str, Any]]:
    ensure_task_catalog_tables(cursor)
    oid = int(organization_id)
    for item in BUILTIN_CATEGORIES:
        cursor.execute(
            f"""
            INSERT INTO {CATEGORIES_TABLE} (organization_id, code, name, display_order, active)
            VALUES (%s, %s, %s, %s, 1)
            ON DUPLICATE KEY UPDATE
              name = IF(name IS NULL OR name = '', VALUES(name), name),
              display_order = IF(display_order = 0, VALUES(display_order), display_order)
            """,
            (oid, item["code"], item["name"], int(item["display_order"])),
        )
    # Point built-in cleaning task codes at Intra-Day when unset.
    if table_has_column(cursor, "weekly_schedule_roles", "task_category_code"):
        for code in CLEANING_TASK_CODES:
            cursor.execute(
                """
                UPDATE weekly_schedule_roles
                SET task_category_code = COALESCE(NULLIF(task_category_code, ''), 'intra_day'),
                    completion_type = COALESCE(NULLIF(completion_type, ''), 'simple'),
                    timer_enabled = COALESCE(timer_enabled, 1),
                    verification_required = COALESCE(verification_required, 1),
                    verification_method = COALESCE(NULLIF(verification_method, ''), 'supervisor'),
                    verification_timing = COALESCE(NULLIF(verification_timing, ''), 'same_shift')
                WHERE organization_id = %s AND code = %s
                """,
                (oid, code),
            )
            # Ensure org has an editable overlay row for built-ins so config sticks.
            cursor.execute(
                """
                SELECT id FROM weekly_schedule_roles
                WHERE organization_id = %s AND code = %s
                LIMIT 1
                """,
                (oid, code),
            )
            if not cursor.fetchone():
                from backend.weekly_schedule_roles import BUILTIN_ROLE_DEFAULTS

                base = next((r for r in BUILTIN_ROLE_DEFAULTS if r["code"] == code), None)
                if base:
                    cursor.execute(
                        """
                        INSERT INTO weekly_schedule_roles (
                          organization_id, code, name, role_group, display_order, active,
                          uses_time_slots, remarks_enabled, task_category_code,
                          completion_type, timer_enabled, verification_required,
                          verification_method, verification_timing
                        ) VALUES (%s,%s,%s,%s,%s,1,0,1,'intra_day','simple',1,1,'supervisor','same_shift')
                        """,
                        (
                            oid,
                            code,
                            base["name"],
                            base.get("role_group") or "CLEANING",
                            int(base.get("display_order") or 0),
                        ),
                    )
    return _fetch_categories(cursor, oid, include_inactive=True)


def _fetch_categories(cursor, organization_id: int, *, include_inactive: bool = True) -> list[dict[str, Any]]:
    sql = f"""
        SELECT id, organization_id, code, name, display_order, active
        FROM {CATEGORIES_TABLE}
        WHERE organization_id = %s
    """
    if not include_inactive:
        sql += " AND active = 1"
    sql += " ORDER BY display_order ASC, name ASC"
    cursor.execute(sql, (int(organization_id),))
    out = []
    for r in cursor.fetchall() or []:
        if not isinstance(r, dict):
            continue
        out.append(
            {
                "id": int(r["id"]),
                "organization_id": int(r["organization_id"]),
                "code": str(r["code"]),
                "name": str(r["name"]),
                "display_order": int(r.get("display_order") or 0),
                "active": bool(r.get("active")),
            }
        )
    return out


def list_categories(cursor, organization_id: int, *, include_inactive: bool = True) -> list[dict[str, Any]]:
    ensure_task_catalog_tables(cursor)
    rows = _fetch_categories(cursor, int(organization_id), include_inactive=True)
    if not rows:
        seed_builtin_categories(cursor, organization_id)
        rows = _fetch_categories(cursor, int(organization_id), include_inactive=True)
    # If DB seed is unavailable (e.g. unit FakeCursor), fall back to built-in definitions.
    if not rows:
        rows = [
            {
                "id": i + 1,
                "organization_id": int(organization_id),
                "code": item["code"],
                "name": item["name"],
                "display_order": int(item["display_order"]),
                "active": True,
            }
            for i, item in enumerate(BUILTIN_CATEGORIES)
        ]
    if include_inactive:
        return rows
    return [r for r in rows if r.get("active")]


def _parse_json(raw: Any, default: Any) -> Any:
    if raw in (None, ""):
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def task_definition_from_role(role: Mapping[str, Any], *, categories_by_code: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Normalize a weekly_schedule_roles / catalog row into a task definition."""
    code = str(role.get("code") or "")
    cat_code = str(role.get("task_category_code") or DEFAULT_TASK_CATEGORY_BY_CODE.get(code) or "intra_day")
    cat = (categories_by_code or {}).get(cat_code) or {}
    completion = str(role.get("completion_type") or COMPLETION_SIMPLE)
    if completion not in COMPLETION_TYPES:
        completion = COMPLETION_SIMPLE
    method = str(role.get("verification_method") or VERIFY_SUPERVISOR)
    if method not in VERIFY_METHODS:
        method = VERIFY_SUPERVISOR
    timing = str(role.get("verification_timing") or VERIFY_TIMING_SAME_SHIFT)
    if timing not in VERIFY_TIMINGS:
        timing = VERIFY_TIMING_SAME_SHIFT
    verify_required = bool(role.get("verification_required", True))
    if method == VERIFY_NONE:
        verify_required = False
    return {
        "code": code,
        "name": str(role.get("name") or code),
        "kind": KIND_TASK,
        "active": bool(role.get("active", True)),
        "category_code": cat_code,
        "category_name": str(cat.get("name") or cat_code.replace("_", " ").title()),
        "category_id": int(cat["id"]) if cat.get("id") is not None else None,
        "completion_type": completion,
        "timer_enabled": bool(role.get("timer_enabled", True)),
        "verification_required": verify_required,
        "verification_method": method if verify_required else VERIFY_NONE,
        "verification_timing": timing,
        "verifier_config": _parse_json(role.get("verifier_config_json"), {}),
        "input_schema": _parse_json(role.get("input_schema_json"), []),
        "checklist_id": int(role["checklist_id"]) if role.get("checklist_id") is not None else None,
        "display_order": int(role.get("display_order") or 0),
        "builtin": bool(role.get("builtin")),
    }


def list_task_definitions(cursor, organization_id: int, *, include_inactive: bool = True) -> list[dict[str, Any]]:
    ensure_task_catalog_tables(cursor)
    cats = {c["code"]: c for c in list_categories(cursor, organization_id)}
    catalog = list_role_catalog(cursor, int(organization_id))
    # Overlay DB config columns for org rows.
    cursor.execute(
        """
        SELECT code, task_category_code, completion_type, timer_enabled, verification_required,
               verification_method, verification_timing, verifier_config_json, input_schema_json,
               checklist_id, active, name, display_order, uses_time_slots
        FROM weekly_schedule_roles
        WHERE organization_id = %s
        """,
        (int(organization_id),),
    )
    overlays = {str(r["code"]): r for r in (cursor.fetchall() or []) if isinstance(r, dict)}
    seen: set[str] = set()
    out = []

    def _append_merged(role: Mapping[str, Any]) -> None:
        code = str(role.get("code") or "")
        if not code or code in seen:
            return
        timed = bool(role.get("uses_time_slots", True))
        merged = dict(role)
        if code in overlays:
            merged.update(
                {
                    k: v
                    for k, v in overlays[code].items()
                    if v is not None or k in ("timer_enabled", "verification_required", "active", "checklist_id")
                }
            )
            if "uses_time_slots" in overlays[code]:
                timed = bool(overlays[code]["uses_time_slots"])
                merged["uses_time_slots"] = timed
        if timed and code not in CLEANING_TASK_CODES:
            return
        # Activity-group synthetic roles are configured separately.
        if code.startswith("agroup_"):
            return
        if code in DEFAULT_TASK_CATEGORY_BY_CODE and not merged.get("task_category_code"):
            merged["task_category_code"] = DEFAULT_TASK_CATEGORY_BY_CODE[code]
        if not include_inactive and not merged.get("active", True):
            return
        seen.add(code)
        out.append(task_definition_from_role(merged, categories_by_code=cats))

    for role in catalog:
        _append_merged(role)
    # Safety net: untimed rows that list_role_catalog might still omit.
    for code, row in overlays.items():
        if bool(row.get("uses_time_slots", True)) and code not in CLEANING_TASK_CODES:
            continue
        _append_merged({**row, "code": code, "uses_time_slots": 0})
    out.sort(key=lambda t: (t.get("category_code") or "", t.get("display_order") or 0, t.get("name") or ""))
    return out


def get_task_definition(cursor, organization_id: int, code: str) -> dict[str, Any] | None:
    code_clean = str(code or "").strip()
    if not code_clean:
        return None
    # Prefer the normal task list (excludes synthetic activity-group roles).
    for item in list_task_definitions(cursor, organization_id, include_inactive=True):
        if item["code"] == code_clean:
            return item
    # Activity-group schedule roles (agroup_*) are omitted from list_task_definitions
    # but still need a definition after upsert / for schedule labels.
    if code_clean.startswith("agroup_"):
        ensure_task_catalog_tables(cursor)
        cats = {c["code"]: c for c in list_categories(cursor, organization_id)}
        cursor.execute(
            """
            SELECT code, task_category_code, completion_type, timer_enabled, verification_required,
                   verification_method, verification_timing, verifier_config_json, input_schema_json,
                   checklist_id, active, name, display_order, uses_time_slots
            FROM weekly_schedule_roles
            WHERE organization_id = %s AND code = %s
            LIMIT 1
            """,
            (int(organization_id), code_clean),
        )
        row = cursor.fetchone()
        if isinstance(row, dict):
            return task_definition_from_role(row, categories_by_code=cats)
    return None


def upsert_category(cursor, organization_id: int, data: Mapping[str, Any], *, category_id: int | None = None) -> dict[str, Any]:
    ensure_task_catalog_tables(cursor)
    oid = int(organization_id)
    name = " ".join(str(data.get("name") or "").split())
    if not name or len(name) > 80:
        raise TaskCatalogError("Category name is required (max 80 characters).")
    active = 1 if data.get("active", True) else 0
    display_order = int(data.get("display_order") or 0)
    if category_id is not None:
        cursor.execute(
            f"""
            UPDATE {CATEGORIES_TABLE}
            SET name = %s, display_order = %s, active = %s
            WHERE organization_id = %s AND id = %s
            """,
            (name, display_order, active, oid, int(category_id)),
        )
        if cursor.rowcount == 0:
            raise TaskCatalogError("Category not found.", status=404)
        cursor.execute(
            f"SELECT * FROM {CATEGORIES_TABLE} WHERE organization_id = %s AND id = %s",
            (oid, int(category_id)),
        )
    else:
        code = _slug_code(str(data.get("code") or name))
        if not code:
            raise TaskCatalogError("Category code is required.")
        cursor.execute(
            f"""
            INSERT INTO {CATEGORIES_TABLE} (organization_id, code, name, display_order, active)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE name=VALUES(name), display_order=VALUES(display_order), active=VALUES(active)
            """,
            (oid, code, name, display_order, active),
        )
        cursor.execute(
            f"SELECT * FROM {CATEGORIES_TABLE} WHERE organization_id = %s AND code = %s",
            (oid, code),
        )
    row = cursor.fetchone()
    return {
        "id": int(row["id"]),
        "organization_id": oid,
        "code": str(row["code"]),
        "name": str(row["name"]),
        "display_order": int(row.get("display_order") or 0),
        "active": bool(row.get("active")),
    }


def reorder_categories(cursor, organization_id: int, ordered_codes: Sequence[str]) -> list[dict[str, Any]]:
    ensure_task_catalog_tables(cursor)
    oid = int(organization_id)
    for idx, code in enumerate(ordered_codes):
        cursor.execute(
            f"""
            UPDATE {CATEGORIES_TABLE}
            SET display_order = %s
            WHERE organization_id = %s AND code = %s
            """,
            ((idx + 1) * 10, oid, str(code)),
        )
    return list_categories(cursor, oid)


def upsert_task_definition(cursor, organization_id: int, code: str, data: Mapping[str, Any]) -> dict[str, Any]:
    """Create/update task config on weekly_schedule_roles (task kind only)."""
    ensure_task_catalog_tables(cursor)
    oid = int(organization_id)
    code_clean = str(code or data.get("code") or "").strip().lower()
    if not code_clean:
        raise TaskCatalogError("Task code is required.")
    # Align with weekly schedule catalog: non-builtin codes need custom_ prefix
    # (or agroup_ for Task Activity Groups) so they appear in list_role_catalog.
    from backend.planned_weekly_schedule import ACTIVITY_GROUP_PREFIX

    if (
        code_clean not in BUILTIN_ROLE_CODES
        and not code_clean.startswith(CUSTOM_ROLE_PREFIX)
        and not code_clean.startswith(ACTIVITY_GROUP_PREFIX)
    ):
        slug = re.sub(r"[^a-z0-9]+", "_", code_clean).strip("_") or "task"
        code_clean = f"{CUSTOM_ROLE_PREFIX}{slug}"
    name = " ".join(str(data.get("name") or code_clean).split())[:ROLE_NAME_MAX]
    cats = {c["code"]: c for c in list_categories(cursor, oid)}
    cat_code = str(data.get("category_code") or data.get("task_category_code") or "intra_day")
    if cat_code not in cats:
        raise TaskCatalogError(f"Unknown category '{cat_code}'.")
    completion = str(data.get("completion_type") or COMPLETION_SIMPLE)
    if completion not in COMPLETION_TYPES:
        raise TaskCatalogError("Invalid completion_type.")
    method = str(data.get("verification_method") or VERIFY_SUPERVISOR)
    if method not in VERIFY_METHODS:
        raise TaskCatalogError("Invalid verification_method.")
    timing = str(data.get("verification_timing") or VERIFY_TIMING_SAME_SHIFT)
    if timing not in VERIFY_TIMINGS:
        raise TaskCatalogError("Invalid verification_timing.")
    verify_required = bool(data.get("verification_required", method != VERIFY_NONE))
    if method == VERIFY_NONE:
        verify_required = False
    timer_enabled = 1 if data.get("timer_enabled", True) else 0
    active = 1 if data.get("active", True) else 0
    verifier_config = data.get("verifier_config") if "verifier_config" in data else data.get("verifier_config_json")
    input_schema = data.get("input_schema") if "input_schema" in data else data.get("input_schema_json")
    if isinstance(verifier_config, (dict, list)):
        verifier_config = json.dumps(verifier_config)
    if isinstance(input_schema, (dict, list)):
        input_schema = json.dumps(input_schema)
    checklist_id = data.get("checklist_id")
    display_order = int(data.get("display_order") or 0)

    cursor.execute(
        """
        SELECT id FROM weekly_schedule_roles
        WHERE organization_id = %s AND code = %s
        LIMIT 1
        """,
        (oid, code_clean),
    )
    existing = cursor.fetchone()
    if existing:
        cursor.execute(
            """
            UPDATE weekly_schedule_roles
            SET name = %s, active = %s, display_order = %s, uses_time_slots = 0, remarks_enabled = 1,
                task_category_code = %s, completion_type = %s, timer_enabled = %s,
                verification_required = %s, verification_method = %s, verification_timing = %s,
                verifier_config_json = %s, input_schema_json = %s, checklist_id = %s
            WHERE organization_id = %s AND code = %s
            """,
            (
                name,
                active,
                display_order,
                cat_code,
                completion,
                timer_enabled,
                1 if verify_required else 0,
                method,
                timing,
                verifier_config,
                input_schema,
                int(checklist_id) if checklist_id not in (None, "") else None,
                oid,
                code_clean,
            ),
        )
    else:
        cursor.execute(
            """
            INSERT INTO weekly_schedule_roles (
              organization_id, code, name, role_group, display_order, active,
              uses_time_slots, remarks_enabled, task_category_code, completion_type,
              timer_enabled, verification_required, verification_method, verification_timing,
              verifier_config_json, input_schema_json, checklist_id
            ) VALUES (%s,%s,%s,'CLEANING',%s,%s,0,1,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                oid,
                code_clean,
                name,
                display_order,
                active,
                cat_code,
                completion,
                timer_enabled,
                1 if verify_required else 0,
                method,
                timing,
                verifier_config,
                input_schema,
                int(checklist_id) if checklist_id not in (None, "") else None,
            ),
        )
    defn = get_task_definition(cursor, oid, code_clean)
    if not defn:
        raise TaskCatalogError("Could not load task after save.", status=500)
    return defn


def validate_completion_input(defn: Mapping[str, Any], submitted: Any) -> dict[str, Any]:
    """Validate employee-submitted completion input against task input_schema."""
    if str(defn.get("completion_type") or COMPLETION_SIMPLE) != COMPLETION_INPUT:
        return {"values": {}, "remarks": None}
    schema = defn.get("input_schema") or []
    if not isinstance(schema, list) or not schema:
        raise TaskCatalogError("This task requires input but has no configured fields.")
    payload = submitted if isinstance(submitted, dict) else {}
    values = payload.get("values") if isinstance(payload.get("values"), dict) else payload
    out: dict[str, Any] = {}
    for field in schema:
        if not isinstance(field, dict):
            continue
        key = str(field.get("id") or field.get("key") or "").strip()
        if not key:
            continue
        required = bool(field.get("required", True))
        ftype = str(field.get("type") or INPUT_TEXT)
        raw = values.get(key) if isinstance(values, dict) else None
        if raw in (None, "") and required:
            raise TaskCatalogError(f"Missing required input: {field.get('label') or key}")
        if raw in (None, ""):
            continue
        if ftype == INPUT_NUMBER:
            try:
                out[key] = float(raw) if "." in str(raw) else int(raw)
            except (TypeError, ValueError):
                raise TaskCatalogError(f"Invalid number for {field.get('label') or key}")
        elif ftype == INPUT_YES_NO:
            out[key] = str(raw).strip().lower() in {"1", "true", "yes", "y"}
        elif ftype == INPUT_CHECKBOX:
            out[key] = bool(raw)
        elif ftype == INPUT_CHECKLIST:
            if not isinstance(raw, list):
                raise TaskCatalogError(f"Checklist input required for {field.get('label') or key}")
            out[key] = raw
        else:
            out[key] = str(raw)[:500]
    remarks = payload.get("remarks")
    return {"values": out, "remarks": (str(remarks).strip()[:500] if remarks else None)}
