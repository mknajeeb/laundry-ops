"""Maintenance Task List — definitions, daily lists, submissions, and audit events."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional

from backend.business_time import business_now, business_today
from backend.maintenance_task_list_constants import (
    DEFAULT_TASK_DEFINITIONS,
    EVENT_DEFINITION_CREATED,
    EVENT_DEFINITION_REORDERED,
    EVENT_DEFINITION_UPDATED,
    EVENT_LIST_CREATED,
    EVENT_LIST_REOPENED,
    EVENT_LIST_SUBMITTED,
    EVENT_MANAGER_CORRECTION,
    EVENT_NOTES_CHANGED,
    EVENT_PROGRESS_SAVED,
    EVENT_TASK_CHECKED,
    EVENT_TASK_UNCHECKED,
    FREQUENCIES,
    FREQUENCY_AS_NEEDED,
    FREQUENCY_DAILY,
    FREQUENCY_WEEKLY,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_NOT_STARTED,
    STATUS_SUBMITTED,
    TERMINAL_STATUSES,
)
from backend.ta_helpers import table_exists


class MaintenanceTaskListError(ValueError):
    """Domain error with optional HTTP status hint."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _as_bool(val: Any, default: bool = False) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


def _json_dump(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    return json.dumps(obj, default=str)


def _json_load(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def _parse_date(value: Any) -> date:
    if value is None or value == "":
        return business_today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    return date.fromisoformat(text)


def _naive_now() -> datetime:
    return business_now().replace(tzinfo=None)


def ensure_maintenance_task_list_tables(cursor) -> None:
    """Idempotent DDL for environments that have not run the SQL migration yet."""
    if table_exists(cursor, "maintenance_task_definitions"):
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS maintenance_task_definitions (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          task_key VARCHAR(80) NOT NULL,
          name VARCHAR(255) NOT NULL,
          description TEXT NULL,
          frequency VARCHAR(20) NOT NULL DEFAULT 'daily',
          days_of_week_json JSON NULL,
          is_required TINYINT(1) NOT NULL DEFAULT 1,
          require_note_if_incomplete TINYINT(1) NOT NULL DEFAULT 1,
          display_order INT NOT NULL DEFAULT 0,
          is_active TINYINT(1) NOT NULL DEFAULT 1,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
          created_by_user_id INT NULL,
          updated_by_user_id INT NULL,
          UNIQUE KEY uq_mtl_def_org_key (organization_id, task_key),
          INDEX idx_mtl_def_org_active_order (organization_id, is_active, display_order)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS maintenance_task_lists (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          employee_id INT NOT NULL,
          task_date DATE NOT NULL,
          status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
          notes TEXT NULL,
          submitted_at DATETIME NULL,
          submitted_by_user_id INT NULL,
          reopened_at DATETIME NULL,
          reopened_by_user_id INT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_mtl_org_emp_date (organization_id, employee_id, task_date),
          INDEX idx_mtl_org_date_status (organization_id, task_date, status),
          INDEX idx_mtl_org_employee (organization_id, employee_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS maintenance_task_list_items (
          id INT AUTO_INCREMENT PRIMARY KEY,
          maintenance_task_list_id INT NOT NULL,
          maintenance_task_definition_id INT NULL,
          task_name_snapshot VARCHAR(255) NOT NULL,
          task_description_snapshot TEXT NULL,
          is_required_snapshot TINYINT(1) NOT NULL DEFAULT 1,
          require_note_if_incomplete_snapshot TINYINT(1) NOT NULL DEFAULT 1,
          completed TINYINT(1) NOT NULL DEFAULT 0,
          completed_at DATETIME NULL,
          completed_by_user_id INT NULL,
          note TEXT NULL,
          display_order_snapshot INT NOT NULL DEFAULT 0,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
          INDEX idx_mtl_items_list (maintenance_task_list_id),
          INDEX idx_mtl_items_def (maintenance_task_definition_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS maintenance_task_list_events (
          id BIGINT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          maintenance_task_list_id INT NULL,
          actor_user_id INT NULL,
          action VARCHAR(60) NOT NULL,
          entity_type VARCHAR(40) NULL,
          entity_id INT NULL,
          old_value JSON NULL,
          new_value JSON NULL,
          remarks TEXT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          INDEX idx_mtl_events_list (maintenance_task_list_id, created_at),
          INDEX idx_mtl_events_org (organization_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def record_event(
    cursor,
    *,
    organization_id: int,
    list_id: Optional[int],
    actor_user_id: Optional[int],
    action: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    old: Any = None,
    new: Any = None,
    remarks: Optional[str] = None,
    write_audit_fn=None,
) -> None:
    if table_exists(cursor, "maintenance_task_list_events"):
        cursor.execute(
            """
            INSERT INTO maintenance_task_list_events
              (organization_id, maintenance_task_list_id, actor_user_id, action,
               entity_type, entity_id, old_value, new_value, remarks, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                int(organization_id),
                int(list_id) if list_id else None,
                int(actor_user_id) if actor_user_id is not None else None,
                action,
                entity_type,
                int(entity_id) if entity_id is not None else None,
                _json_dump(old),
                _json_dump(new),
                remarks,
                _naive_now(),
            ),
        )
    if write_audit_fn and actor_user_id is not None:
        try:
            write_audit_fn(
                actor_user_id,
                entity_type or "maintenance_task_list",
                entity_id if entity_id is not None else (list_id or 0),
                action,
                old=old,
                new=new,
                remarks=remarks,
                organization_id=organization_id,
            )
        except Exception:
            pass


def definition_applies_on_date(defn: dict, task_date: date) -> bool:
    if not _as_bool(defn.get("is_active"), True):
        return False
    freq = str(defn.get("frequency") or FREQUENCY_DAILY).strip().lower()
    if freq in (FREQUENCY_DAILY, FREQUENCY_AS_NEEDED):
        return True
    if freq == FREQUENCY_WEEKLY:
        days = _json_load(defn.get("days_of_week_json")) or []
        if not isinstance(days, list) or not days:
            return True
        weekday = int(task_date.weekday())  # Mon=0 .. Sun=6
        normalized = {int(d) for d in days if str(d).strip() != ""}
        return weekday in normalized
    return True


def ensure_default_task_definitions(
    cursor,
    organization_id: int,
    actor_user_id: Optional[int] = None,
) -> int:
    """Seed built-in daily tasks when the org has no definitions yet. Returns inserted count."""
    ensure_maintenance_task_list_tables(cursor)
    cursor.execute(
        "SELECT COUNT(*) AS c FROM maintenance_task_definitions WHERE organization_id = %s",
        (int(organization_id),),
    )
    row = cursor.fetchone() or {}
    if int(row.get("c") or 0) > 0:
        return 0
    now = _naive_now()
    inserted = 0
    for spec in DEFAULT_TASK_DEFINITIONS:
        cursor.execute(
            """
            INSERT INTO maintenance_task_definitions
              (organization_id, task_key, name, description, frequency, days_of_week_json,
               is_required, require_note_if_incomplete, display_order, is_active,
               created_at, created_by_user_id, updated_by_user_id)
            VALUES (%s, %s, %s, %s, %s, NULL, %s, %s, %s, 1, %s, %s, %s)
            """,
            (
                int(organization_id),
                spec["task_key"],
                spec["name"],
                spec.get("description"),
                spec["frequency"],
                1 if spec.get("is_required", True) else 0,
                1 if spec.get("require_note_if_incomplete", True) else 0,
                int(spec["display_order"]),
                now,
                actor_user_id,
                actor_user_id,
            ),
        )
        inserted += 1
    return inserted


def list_task_definitions(
    cursor,
    organization_id: int,
    *,
    active_only: bool = False,
    include_inactive: bool = True,
) -> list[dict]:
    ensure_default_task_definitions(cursor, organization_id)
    where = "organization_id = %s"
    params: list[Any] = [int(organization_id)]
    if active_only or not include_inactive:
        where += " AND is_active = 1"
    cursor.execute(
        f"""
        SELECT *
        FROM maintenance_task_definitions
        WHERE {where}
        ORDER BY display_order ASC, id ASC
        """,
        tuple(params),
    )
    rows = cursor.fetchall() or []
    out = []
    for r in rows:
        item = dict(r)
        item["days_of_week"] = _json_load(item.pop("days_of_week_json", None)) or []
        item["is_required"] = _as_bool(item.get("is_required"), True)
        item["require_note_if_incomplete"] = _as_bool(item.get("require_note_if_incomplete"), True)
        item["is_active"] = _as_bool(item.get("is_active"), True)
        out.append(item)
    return out


def create_or_update_definition(
    cursor,
    organization_id: int,
    payload: dict,
    actor_user_id: Optional[int],
    *,
    write_audit_fn=None,
) -> dict:
    ensure_default_task_definitions(cursor, organization_id, actor_user_id)
    def_id = payload.get("id")
    name = (payload.get("name") or "").strip()
    if not name:
        raise MaintenanceTaskListError("Task name is required")
    frequency = str(payload.get("frequency") or FREQUENCY_DAILY).strip().lower()
    if frequency not in FREQUENCIES:
        raise MaintenanceTaskListError("Invalid frequency")
    days = payload.get("days_of_week")
    if days is None:
        days = payload.get("days_of_week_json")
    if frequency == FREQUENCY_WEEKLY and not days:
        raise MaintenanceTaskListError("Weekly tasks require at least one day of week")
    task_key = (payload.get("task_key") or "").strip().lower().replace(" ", "_")
    if not task_key:
        task_key = "".join(ch if ch.isalnum() else "_" for ch in name.lower()).strip("_")[:80]
    now = _naive_now()
    days_json = _json_dump(days) if days is not None else None
    is_required = 1 if _as_bool(payload.get("is_required"), True) else 0
    require_note = 1 if _as_bool(payload.get("require_note_if_incomplete"), True) else 0
    is_active = 1 if _as_bool(payload.get("is_active"), True) else 0
    display_order = int(payload.get("display_order") or 0)
    description = (payload.get("description") or "").strip() or None

    if def_id:
        cursor.execute(
            """
            SELECT * FROM maintenance_task_definitions
            WHERE id = %s AND organization_id = %s
            LIMIT 1
            """,
            (int(def_id), int(organization_id)),
        )
        existing = cursor.fetchone()
        if not existing:
            raise MaintenanceTaskListError("Task definition not found", 404)
        cursor.execute(
            """
            UPDATE maintenance_task_definitions
            SET name = %s,
                description = %s,
                frequency = %s,
                days_of_week_json = %s,
                is_required = %s,
                require_note_if_incomplete = %s,
                display_order = %s,
                is_active = %s,
                updated_at = %s,
                updated_by_user_id = %s
            WHERE id = %s AND organization_id = %s
            """,
            (
                name,
                description,
                frequency,
                days_json,
                is_required,
                require_note,
                display_order,
                is_active,
                now,
                actor_user_id,
                int(def_id),
                int(organization_id),
            ),
        )
        record_event(
            cursor,
            organization_id=organization_id,
            list_id=None,
            actor_user_id=actor_user_id,
            action=EVENT_DEFINITION_UPDATED,
            entity_type="maintenance_task_definition",
            entity_id=int(def_id),
            old={"name": existing.get("name"), "is_active": existing.get("is_active")},
            new={"name": name, "is_active": is_active, "frequency": frequency},
            write_audit_fn=write_audit_fn,
        )
        return get_definition(cursor, organization_id, int(def_id))

    cursor.execute(
        """
        INSERT INTO maintenance_task_definitions
          (organization_id, task_key, name, description, frequency, days_of_week_json,
           is_required, require_note_if_incomplete, display_order, is_active,
           created_at, created_by_user_id, updated_by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            int(organization_id),
            task_key,
            name,
            description,
            frequency,
            days_json,
            is_required,
            require_note,
            display_order,
            is_active,
            now,
            actor_user_id,
            actor_user_id,
        ),
    )
    new_id = int(cursor.lastrowid)
    record_event(
        cursor,
        organization_id=organization_id,
        list_id=None,
        actor_user_id=actor_user_id,
        action=EVENT_DEFINITION_CREATED,
        entity_type="maintenance_task_definition",
        entity_id=new_id,
        new={"task_key": task_key, "name": name},
        write_audit_fn=write_audit_fn,
    )
    return get_definition(cursor, organization_id, new_id)


def get_definition(cursor, organization_id: int, definition_id: int) -> dict:
    cursor.execute(
        """
        SELECT * FROM maintenance_task_definitions
        WHERE id = %s AND organization_id = %s
        LIMIT 1
        """,
        (int(definition_id), int(organization_id)),
    )
    row = cursor.fetchone()
    if not row:
        raise MaintenanceTaskListError("Task definition not found", 404)
    item = dict(row)
    item["days_of_week"] = _json_load(item.pop("days_of_week_json", None)) or []
    item["is_required"] = _as_bool(item.get("is_required"), True)
    item["require_note_if_incomplete"] = _as_bool(item.get("require_note_if_incomplete"), True)
    item["is_active"] = _as_bool(item.get("is_active"), True)
    return item


def set_definition_active(
    cursor,
    organization_id: int,
    definition_id: int,
    is_active: bool,
    actor_user_id: Optional[int],
    *,
    write_audit_fn=None,
) -> dict:
    existing = get_definition(cursor, organization_id, definition_id)
    payload = {
        "id": definition_id,
        "name": existing["name"],
        "description": existing.get("description"),
        "frequency": existing.get("frequency"),
        "days_of_week": existing.get("days_of_week"),
        "is_required": existing.get("is_required"),
        "require_note_if_incomplete": existing.get("require_note_if_incomplete"),
        "display_order": existing.get("display_order"),
        "is_active": is_active,
    }
    return create_or_update_definition(
        cursor,
        organization_id,
        payload,
        actor_user_id,
        write_audit_fn=write_audit_fn,
    )


def reorder_definitions(
    cursor,
    organization_id: int,
    ordered_ids: list[int],
    actor_user_id: Optional[int],
    *,
    write_audit_fn=None,
) -> list[dict]:
    if not ordered_ids:
        raise MaintenanceTaskListError("ordered_ids is required")
    now = _naive_now()
    for idx, def_id in enumerate(ordered_ids):
        cursor.execute(
            """
            UPDATE maintenance_task_definitions
            SET display_order = %s, updated_at = %s, updated_by_user_id = %s
            WHERE id = %s AND organization_id = %s
            """,
            (int(idx) * 10, now, actor_user_id, int(def_id), int(organization_id)),
        )
    record_event(
        cursor,
        organization_id=organization_id,
        list_id=None,
        actor_user_id=actor_user_id,
        action=EVENT_DEFINITION_REORDERED,
        entity_type="maintenance_task_definition",
        new={"ordered_ids": [int(x) for x in ordered_ids]},
        write_audit_fn=write_audit_fn,
    )
    return list_task_definitions(cursor, organization_id, include_inactive=True)


def _fetch_list_row(cursor, organization_id: int, list_id: int) -> Optional[dict]:
    cursor.execute(
        """
        SELECT * FROM maintenance_task_lists
        WHERE id = %s AND organization_id = %s
        LIMIT 1
        """,
        (int(list_id), int(organization_id)),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def _fetch_list_by_employee_date(
    cursor,
    organization_id: int,
    employee_id: int,
    task_date: date,
) -> Optional[dict]:
    cursor.execute(
        """
        SELECT * FROM maintenance_task_lists
        WHERE organization_id = %s AND employee_id = %s AND task_date = %s
        LIMIT 1
        """,
        (int(organization_id), int(employee_id), task_date),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def _list_items(cursor, list_id: int) -> list[dict]:
    cursor.execute(
        """
        SELECT *
        FROM maintenance_task_list_items
        WHERE maintenance_task_list_id = %s
        ORDER BY display_order_snapshot ASC, id ASC
        """,
        (int(list_id),),
    )
    rows = cursor.fetchall() or []
    out = []
    for r in rows:
        item = dict(r)
        item["completed"] = _as_bool(item.get("completed"), False)
        item["is_required_snapshot"] = _as_bool(item.get("is_required_snapshot"), True)
        item["require_note_if_incomplete_snapshot"] = _as_bool(
            item.get("require_note_if_incomplete_snapshot"), True
        )
        out.append(item)
    return out


def _employee_display_name(cursor, employee_id: int) -> str:
    try:
        cursor.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(pp.preferred_name), ''), NULLIF(TRIM(pp.first_name), ''),
                            NULLIF(TRIM(u.display_name), ''), u.username) AS name
            FROM users u
            LEFT JOIN payroll_profiles pp ON pp.user_id = u.id
            WHERE u.id = %s
            LIMIT 1
            """,
            (int(employee_id),),
        )
        row = cursor.fetchone() or {}
        return (row.get("name") or f"Employee {employee_id}").strip()
    except Exception:
        return f"Employee {employee_id}"


def derive_list_status(stored_status: Optional[str], items: list[dict]) -> str:
    """
    V1 display/storage status:
    - completed: checklist submitted (all tasks were checked at submit)
    - not_started: no tasks checked yet
    - in_progress: at least one checked, not yet submitted
    """
    if str(stored_status or "") in TERMINAL_STATUSES:
        return STATUS_COMPLETED
    completed_count = sum(1 for i in items if i.get("completed"))
    if completed_count <= 0:
        return STATUS_NOT_STARTED
    return STATUS_IN_PROGRESS


def is_list_read_only(stored_status: Optional[str]) -> bool:
    return str(stored_status or "") in TERMINAL_STATUSES


def serialize_list(
    cursor,
    list_row: dict,
    *,
    include_events: bool = False,
) -> dict:
    items = _list_items(cursor, int(list_row["id"]))
    completed_count = sum(1 for i in items if i.get("completed"))
    total = len(items)
    incomplete = [i for i in items if not i.get("completed")]
    stored = list_row.get("status") or STATUS_IN_PROGRESS
    payload = {
        "id": int(list_row["id"]),
        "organization_id": int(list_row["organization_id"]),
        "employee_id": int(list_row["employee_id"]),
        "employee_name": _employee_display_name(cursor, int(list_row["employee_id"])),
        "task_date": list_row["task_date"].isoformat()
        if isinstance(list_row["task_date"], date)
        else str(list_row["task_date"]),
        "status": derive_list_status(stored, items),
        "stored_status": stored,
        "all_complete": total > 0 and len(incomplete) == 0,
        "read_only": is_list_read_only(stored),
        "notes": list_row.get("notes") or "",
        "submitted_at": list_row.get("submitted_at"),
        "submitted_by_user_id": list_row.get("submitted_by_user_id"),
        "reopened_at": list_row.get("reopened_at"),
        "reopened_by_user_id": list_row.get("reopened_by_user_id"),
        "created_at": list_row.get("created_at"),
        "updated_at": list_row.get("updated_at"),
        "completed_count": completed_count,
        "total_count": total,
        "incomplete_count": len(incomplete),
        "missing_task_names": [i.get("task_name_snapshot") for i in incomplete],
        "items": items,
    }
    if include_events and table_exists(cursor, "maintenance_task_list_events"):
        cursor.execute(
            """
            SELECT *
            FROM maintenance_task_list_events
            WHERE maintenance_task_list_id = %s
            ORDER BY created_at ASC, id ASC
            """,
            (int(list_row["id"]),),
        )
        events = []
        for e in cursor.fetchall() or []:
            ev = dict(e)
            ev["old_value"] = _json_load(ev.get("old_value"))
            ev["new_value"] = _json_load(ev.get("new_value"))
            events.append(ev)
        payload["events"] = events
    return payload


def get_or_create_task_list(
    cursor,
    organization_id: int,
    employee_id: int,
    task_date: Optional[Any] = None,
    *,
    actor_user_id: Optional[int] = None,
    write_audit_fn=None,
) -> dict:
    """Idempotent: returns existing list for org/employee/date or creates from active definitions."""
    ensure_default_task_definitions(cursor, organization_id, actor_user_id)
    d = _parse_date(task_date)
    existing = _fetch_list_by_employee_date(cursor, organization_id, employee_id, d)
    if existing:
        return serialize_list(cursor, existing)

    defs = [
        defn
        for defn in list_task_definitions(cursor, organization_id, active_only=True)
        if definition_applies_on_date(defn, d)
    ]
    now = _naive_now()
    cursor.execute(
        """
        INSERT INTO maintenance_task_lists
          (organization_id, employee_id, task_date, status, notes, created_at, updated_at)
        VALUES (%s, %s, %s, %s, NULL, %s, %s)
        """,
        (int(organization_id), int(employee_id), d, STATUS_IN_PROGRESS, now, now),
    )
    list_id = int(cursor.lastrowid)
    for defn in defs:
        cursor.execute(
            """
            INSERT INTO maintenance_task_list_items
              (maintenance_task_list_id, maintenance_task_definition_id,
               task_name_snapshot, task_description_snapshot, is_required_snapshot,
               require_note_if_incomplete_snapshot, completed, display_order_snapshot, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, 0, %s, %s)
            """,
            (
                list_id,
                int(defn["id"]),
                defn["name"],
                defn.get("description"),
                1 if defn.get("is_required") else 0,
                1 if defn.get("require_note_if_incomplete") else 0,
                int(defn.get("display_order") or 0),
                now,
            ),
        )
    record_event(
        cursor,
        organization_id=organization_id,
        list_id=list_id,
        actor_user_id=actor_user_id or employee_id,
        action=EVENT_LIST_CREATED,
        entity_type="maintenance_task_list",
        entity_id=list_id,
        new={"task_date": d.isoformat(), "item_count": len(defs)},
        write_audit_fn=write_audit_fn,
    )
    row = _fetch_list_row(cursor, organization_id, list_id)
    return serialize_list(cursor, row)


def get_task_list(
    cursor,
    organization_id: int,
    list_id: int,
    *,
    include_events: bool = False,
) -> dict:
    row = _fetch_list_row(cursor, organization_id, list_id)
    if not row:
        raise MaintenanceTaskListError("Task list not found", 404)
    return serialize_list(cursor, row, include_events=include_events)


def _assert_editable(list_row: dict, *, allow_manager_override: bool = False) -> None:
    # V1: completed/submitted lists are always read-only (no reopen/correction).
    if is_list_read_only(list_row.get("status")):
        raise MaintenanceTaskListError(
            "This maintenance task list is completed and cannot be edited.",
            409,
        )


def save_task_item(
    cursor,
    organization_id: int,
    list_id: int,
    item_id: int,
    *,
    completed: Optional[bool] = None,
    note: Optional[str] = None,
    actor_user_id: int,
    allow_manager_override: bool = False,
    write_audit_fn=None,
) -> dict:
    list_row = _fetch_list_row(cursor, organization_id, list_id)
    if not list_row:
        raise MaintenanceTaskListError("Task list not found", 404)
    _assert_editable(list_row, allow_manager_override=allow_manager_override)

    cursor.execute(
        """
        SELECT * FROM maintenance_task_list_items
        WHERE id = %s AND maintenance_task_list_id = %s
        LIMIT 1
        """,
        (int(item_id), int(list_id)),
    )
    item = cursor.fetchone()
    if not item:
        raise MaintenanceTaskListError("Task item not found", 404)

    now = _naive_now()
    was_completed = _as_bool(item.get("completed"), False)
    new_completed = was_completed if completed is None else _as_bool(completed, False)
    completed_at = item.get("completed_at")
    completed_by = item.get("completed_by_user_id")
    if new_completed and not was_completed:
        completed_at = now
        completed_by = actor_user_id
    elif not new_completed:
        completed_at = None
        completed_by = None

    new_note = item.get("note") if note is None else (str(note).strip() or None)
    cursor.execute(
        """
        UPDATE maintenance_task_list_items
        SET completed = %s,
            completed_at = %s,
            completed_by_user_id = %s,
            note = %s,
            updated_at = %s
        WHERE id = %s
        """,
        (
            1 if new_completed else 0,
            completed_at,
            completed_by,
            new_note,
            now,
            int(item_id),
        ),
    )
    cursor.execute(
        "UPDATE maintenance_task_lists SET updated_at = %s WHERE id = %s",
        (now, int(list_id)),
    )

    action = EVENT_PROGRESS_SAVED
    if completed is not None and new_completed != was_completed:
        action = EVENT_TASK_CHECKED if new_completed else EVENT_TASK_UNCHECKED

    record_event(
        cursor,
        organization_id=organization_id,
        list_id=list_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type="maintenance_task_list_item",
        entity_id=int(item_id),
        old={"completed": was_completed, "note": item.get("note")},
        new={"completed": new_completed, "note": new_note, "completed_at": completed_at},
        write_audit_fn=write_audit_fn,
    )
    return serialize_list(cursor, _fetch_list_row(cursor, organization_id, list_id))


def save_list_notes(
    cursor,
    organization_id: int,
    list_id: int,
    notes: str,
    actor_user_id: int,
    *,
    allow_manager_override: bool = False,
    write_audit_fn=None,
) -> dict:
    list_row = _fetch_list_row(cursor, organization_id, list_id)
    if not list_row:
        raise MaintenanceTaskListError("Task list not found", 404)
    _assert_editable(list_row, allow_manager_override=allow_manager_override)
    now = _naive_now()
    cleaned = (notes or "").strip()
    cursor.execute(
        """
        UPDATE maintenance_task_lists
        SET notes = %s, updated_at = %s
        WHERE id = %s AND organization_id = %s
        """,
        (cleaned or None, now, int(list_id), int(organization_id)),
    )
    record_event(
        cursor,
        organization_id=organization_id,
        list_id=list_id,
        actor_user_id=actor_user_id,
        action=EVENT_NOTES_CHANGED,
        entity_type="maintenance_task_list",
        entity_id=int(list_id),
        old={"notes": list_row.get("notes")},
        new={"notes": cleaned},
        write_audit_fn=write_audit_fn,
    )
    return serialize_list(cursor, _fetch_list_row(cursor, organization_id, list_id))


def save_progress(
    cursor,
    organization_id: int,
    list_id: int,
    payload: dict,
    actor_user_id: int,
    *,
    allow_manager_override: bool = False,
    write_audit_fn=None,
) -> dict:
    """Batch save items + optional list notes (auto-save / Save Progress)."""
    list_row = _fetch_list_row(cursor, organization_id, list_id)
    if not list_row:
        raise MaintenanceTaskListError("Task list not found", 404)
    _assert_editable(list_row, allow_manager_override=allow_manager_override)

    for item_patch in payload.get("items") or []:
        item_id = item_patch.get("id")
        if item_id is None:
            continue
        save_task_item(
            cursor,
            organization_id,
            list_id,
            int(item_id),
            completed=item_patch.get("completed"),
            note=item_patch.get("note"),
            actor_user_id=actor_user_id,
            allow_manager_override=allow_manager_override,
            write_audit_fn=write_audit_fn,
        )
    if "notes" in payload:
        save_list_notes(
            cursor,
            organization_id,
            list_id,
            payload.get("notes") or "",
            actor_user_id,
            allow_manager_override=allow_manager_override,
            write_audit_fn=write_audit_fn,
        )
    record_event(
        cursor,
        organization_id=organization_id,
        list_id=list_id,
        actor_user_id=actor_user_id,
        action=EVENT_PROGRESS_SAVED,
        entity_type="maintenance_task_list",
        entity_id=int(list_id),
        write_audit_fn=write_audit_fn,
    )
    return serialize_list(cursor, _fetch_list_row(cursor, organization_id, list_id))


def submit_task_list(
    cursor,
    organization_id: int,
    list_id: int,
    actor_user_id: int,
    *,
    notes: Optional[str] = None,
    write_audit_fn=None,
) -> dict:
    """Mark checklist Completed. V1 requires every assigned item to be checked."""
    list_row = _fetch_list_row(cursor, organization_id, list_id)
    if not list_row:
        raise MaintenanceTaskListError("Task list not found", 404)
    if is_list_read_only(list_row.get("status")):
        raise MaintenanceTaskListError("This maintenance task list is already completed", 409)

    items = _list_items(cursor, list_id)
    if not items:
        raise MaintenanceTaskListError("There are no tasks to submit", 400)
    incomplete = [i for i in items if not i.get("completed")]
    if incomplete:
        raise MaintenanceTaskListError(
            "All checklist items must be checked before submitting.",
            400,
        )

    now = _naive_now()
    cursor.execute(
        """
        UPDATE maintenance_task_lists
        SET status = %s,
            submitted_at = %s,
            submitted_by_user_id = %s,
            updated_at = %s
        WHERE id = %s AND organization_id = %s
        """,
        (STATUS_COMPLETED, now, actor_user_id, now, int(list_id), int(organization_id)),
    )
    record_event(
        cursor,
        organization_id=organization_id,
        list_id=list_id,
        actor_user_id=actor_user_id,
        action=EVENT_LIST_SUBMITTED,
        entity_type="maintenance_task_list",
        entity_id=int(list_id),
        new={
            "status": STATUS_COMPLETED,
            "submitted_at": now.isoformat(),
            "completed_count": len(items),
        },
        write_audit_fn=write_audit_fn,
    )
    return serialize_list(
        cursor,
        _fetch_list_row(cursor, organization_id, list_id),
        include_events=True,
    )


def reopen_task_list(
    cursor,
    organization_id: int,
    list_id: int,
    actor_user_id: int,
    *,
    remarks: Optional[str] = None,
    write_audit_fn=None,
) -> dict:
    """V1: reopen is not supported."""
    raise MaintenanceTaskListError(
        "Reopening a completed checklist is not available in this version.",
        400,
    )


def summarize_missing(items: list[dict]) -> str:
    incomplete = [i for i in items if not i.get("completed")]
    if not incomplete:
        return "—"
    if len(incomplete) == len(items):
        return "All tasks"
    if len(incomplete) == 1:
        return incomplete[0].get("task_name_snapshot") or "1 task"
    if len(incomplete) <= 2:
        return ", ".join(i.get("task_name_snapshot") or "?" for i in incomplete)
    return f"{len(incomplete)} tasks"


def list_submission_summaries(
    cursor,
    organization_id: int,
    *,
    task_date: Optional[Any] = None,
    employee_id: Optional[int] = None,
    status: Optional[str] = None,
    completed_filter: Optional[str] = None,
    definition_id: Optional[int] = None,
    include_not_started_employees: bool = True,
) -> list[dict]:
    """Manager report rows. Optionally pads with not-started employees who have attendance PINs."""
    ensure_default_task_definitions(cursor, organization_id)
    d = _parse_date(task_date)
    where = ["mtl.organization_id = %s", "mtl.task_date = %s"]
    params: list[Any] = [int(organization_id), d]
    if employee_id is not None:
        where.append("mtl.employee_id = %s")
        params.append(int(employee_id))
    # Derived statuses (not_started / in_progress) are filtered after serialize.
    status_filter = (status or "").strip().lower() or None
    if status_filter in (STATUS_COMPLETED, STATUS_SUBMITTED):
        where.append("mtl.status IN (%s, %s)")
        params.extend([STATUS_COMPLETED, STATUS_SUBMITTED])

    cursor.execute(
        f"""
        SELECT mtl.*
        FROM maintenance_task_lists mtl
        WHERE {' AND '.join(where)}
        ORDER BY mtl.employee_id ASC
        """,
        tuple(params),
    )
    rows = cursor.fetchall() or []
    summaries = []
    seen_employees = set()
    for row in rows:
        payload = serialize_list(cursor, dict(row))
        seen_employees.add(int(payload["employee_id"]))
        if status_filter and payload["status"] != (
            STATUS_COMPLETED if status_filter == STATUS_SUBMITTED else status_filter
        ):
            continue
        if definition_id is not None:
            if not any(
                int(i.get("maintenance_task_definition_id") or 0) == int(definition_id)
                for i in payload["items"]
            ):
                continue
        if completed_filter == "complete" and payload["incomplete_count"] > 0:
            continue
        if completed_filter == "incomplete" and payload["incomplete_count"] == 0:
            continue
        summaries.append(
            {
                "id": payload["id"],
                "task_date": payload["task_date"],
                "employee_id": payload["employee_id"],
                "employee_name": payload["employee_name"],
                "status": payload["status"],
                "completed_count": payload["completed_count"],
                "total_count": payload["total_count"],
                "completed_label": f"{payload['completed_count']}/{payload['total_count']}",
                "missing": summarize_missing(payload["items"]),
                "submitted_at": payload["submitted_at"],
                "updated_at": payload["updated_at"],
                "notes": payload["notes"],
            }
        )

    if include_not_started_employees and (not status_filter or status_filter == STATUS_NOT_STARTED):
        try:
            cursor.execute(
                """
                SELECT u.id AS employee_id,
                       COALESCE(NULLIF(TRIM(pp.preferred_name), ''), NULLIF(TRIM(pp.first_name), ''),
                                NULLIF(TRIM(u.display_name), ''), u.username) AS employee_name
                FROM users u
                INNER JOIN payroll_profiles pp ON pp.user_id = u.id
                WHERE u.organization_id = %s
                  AND u.active = 1
                  AND pp.attendance_pin_hash IS NOT NULL
                ORDER BY employee_name ASC
                """,
                (int(organization_id),),
            )
            for emp in cursor.fetchall() or []:
                eid = int(emp["employee_id"])
                if eid in seen_employees:
                    continue
                if employee_id is not None and eid != int(employee_id):
                    continue
                if status_filter and status_filter != STATUS_NOT_STARTED:
                    continue
                if completed_filter == "complete":
                    continue
                active_defs = [
                    defn
                    for defn in list_task_definitions(cursor, organization_id, active_only=True)
                    if definition_applies_on_date(defn, d)
                ]
                total = len(active_defs)
                summaries.append(
                    {
                        "id": None,
                        "task_date": d.isoformat(),
                        "employee_id": eid,
                        "employee_name": emp.get("employee_name") or f"Employee {eid}",
                        "status": STATUS_NOT_STARTED,
                        "completed_count": 0,
                        "total_count": total,
                        "completed_label": f"0/{total}",
                        "missing": "All tasks" if total else "—",
                        "submitted_at": None,
                        "updated_at": None,
                        "notes": "",
                    }
                )
        except Exception:
            pass

    status_rank = {
        STATUS_COMPLETED: 0,
        STATUS_SUBMITTED: 0,
        STATUS_IN_PROGRESS: 1,
        STATUS_NOT_STARTED: 2,
    }
    summaries.sort(
        key=lambda r: (
            status_rank.get(r["status"], 9),
            (r.get("employee_name") or "").lower(),
        )
    )
    return summaries


def business_today_iso() -> str:
    return business_today().isoformat()


def format_task_date_display(task_date: Optional[Any] = None) -> str:
    d = _parse_date(task_date)
    # Portable day-of-month without leading zero (avoid %-d / %#d platform quirks).
    return f"{d.strftime('%A, %B')} {d.day}, {d.year}"
