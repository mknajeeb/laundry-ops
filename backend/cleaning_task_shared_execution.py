"""Shared Activity Group execution: one collaborative checklist, per-employee timers.

Distinct from Individual Execution (per-employee item rows on each activity).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.business_time import business_today
from backend.cleaning_task_activity import (
    STATUS_APPROVED,
    STATUS_COMPLETED,
    STATUS_PENDING_APPROVAL,
    TABLE,
    CleaningTaskError,
    _employee_names,
    _finalize_completion,
    _record_event,
    _role_catalog,
    _role_label,
    _task_meta_for_role,
    ensure_cleaning_task_activity_tables,
    get_activity,
    serialize_activity,
)
from backend.payroll_identity import eastern_now_naive
from backend.planned_weekly_schedule_responsibilities import (
    EXECUTION_INDIVIDUAL,
    EXECUTION_SHARED,
)
from backend.task_activity_groups import get_activity_group
from backend.task_catalog import (
    COMPLETION_SIMPLE,
    VERIFY_NONE,
    VERIFY_SUPERVISOR,
    TaskCatalogError,
    validate_completion_input,
)
from backend.ta_helpers import invalidate_schema_cache, table_exists, table_has_column

SESSIONS_TABLE = "cleaning_task_shared_sessions"
SESSION_ITEMS_TABLE = "cleaning_task_shared_session_items"

SESSION_OPEN = "open"
SESSION_CHECKLIST_COMPLETE = "checklist_complete"
ITEM_PENDING = "pending"
ITEM_COMPLETED = "completed"
KIND_GROUP = "group"
KIND_GROUP_ITEM = "group_item"


def ensure_shared_activity_schema(cursor) -> None:
    ensure_cleaning_task_activity_tables(cursor)
    if not table_exists(cursor, SESSIONS_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {SESSIONS_TABLE} (
              id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              assignment_group_id VARCHAR(36) NOT NULL,
              business_date DATE NOT NULL,
              role VARCHAR(64) NOT NULL,
              status VARCHAR(32) NOT NULL,
              checklist_completed_at DATETIME NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_ctss (organization_id, assignment_group_id, business_date),
              INDEX idx_ctss_org_day (organization_id, business_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    if not table_exists(cursor, SESSION_ITEMS_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {SESSION_ITEMS_TABLE} (
              id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              shared_session_id BIGINT NOT NULL,
              task_code VARCHAR(64) NOT NULL,
              display_order INT NOT NULL DEFAULT 0,
              required TINYINT(1) NOT NULL DEFAULT 1,
              status VARCHAR(32) NOT NULL,
              completed_at DATETIME NULL,
              completed_by_user_id INT NULL,
              completion_input_json TEXT NULL,
              child_activity_id BIGINT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_ctssi (shared_session_id, task_code),
              INDEX idx_ctssi_org_session (organization_id, shared_session_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    if table_exists(cursor, TABLE) and not table_has_column(cursor, TABLE, "shared_session_id"):
        cursor.execute(f"ALTER TABLE {TABLE} ADD COLUMN shared_session_id BIGINT NULL")
        try:
            cursor.execute(
                f"ALTER TABLE {TABLE} ADD INDEX idx_cta_shared_session (organization_id, shared_session_id)"
            )
        except Exception:
            pass
    invalidate_schema_cache()


def is_shared_execution(target: Mapping[str, Any] | None) -> bool:
    if not target:
        return False
    mode = str(target.get("execution_mode") or EXECUTION_INDIVIDUAL).strip().lower()
    group_id = str(target.get("assignment_group_id") or "").strip()
    members = target.get("user_ids") or []
    return mode == EXECUTION_SHARED and bool(group_id) and len(members) >= 2


def get_shared_session(cursor, organization_id: int, session_id: int) -> dict[str, Any] | None:
    ensure_shared_activity_schema(cursor)
    cursor.execute(
        f"SELECT * FROM {SESSIONS_TABLE} WHERE organization_id=%s AND id=%s LIMIT 1",
        (int(organization_id), int(session_id)),
    )
    row = cursor.fetchone()
    return row if isinstance(row, dict) else None


def list_shared_session_items(cursor, organization_id: int, session_id: int) -> list[dict[str, Any]]:
    ensure_shared_activity_schema(cursor)
    cursor.execute(
        f"""
        SELECT * FROM {SESSION_ITEMS_TABLE}
        WHERE organization_id=%s AND shared_session_id=%s
        ORDER BY display_order ASC, id ASC
        """,
        (int(organization_id), int(session_id)),
    )
    return [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def ensure_shared_session(
    cursor,
    *,
    organization_id: int,
    assignment_group_id: str,
    business_date,
    role: str,
    group_items: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Get or create the day's shared checklist for an assignment group."""
    ensure_shared_activity_schema(cursor)
    oid = int(organization_id)
    gid = str(assignment_group_id).strip()
    day = business_date or business_today()
    cursor.execute(
        f"""
        SELECT * FROM {SESSIONS_TABLE}
        WHERE organization_id=%s AND assignment_group_id=%s AND business_date=%s
        LIMIT 1
        """,
        (oid, gid, day),
    )
    existing = cursor.fetchone()
    if isinstance(existing, dict):
        return existing
    cursor.execute(
        f"""
        INSERT INTO {SESSIONS_TABLE}
          (organization_id, assignment_group_id, business_date, role, status)
        VALUES (%s,%s,%s,%s,%s)
        """,
        (oid, gid, day, str(role), SESSION_OPEN),
    )
    session_id = int(cursor.lastrowid)
    for item in group_items or []:
        cursor.execute(
            f"""
            INSERT INTO {SESSION_ITEMS_TABLE}
              (organization_id, shared_session_id, task_code, display_order, required, status)
            VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (
                oid,
                session_id,
                str(item.get("task_code") or ""),
                int(item.get("display_order") or 0),
                1 if item.get("required", True) else 0,
                ITEM_PENDING,
            ),
        )
    return get_shared_session(cursor, oid, session_id) or {
        "id": session_id,
        "organization_id": oid,
        "assignment_group_id": gid,
        "business_date": day,
        "role": role,
        "status": SESSION_OPEN,
    }


def serialize_shared_item(
    row: Mapping[str, Any],
    *,
    catalog: Mapping[str, Mapping[str, Any]] | None = None,
    meta: Mapping[str, Any] | None = None,
    names: Mapping[int, str] | None = None,
) -> dict[str, Any]:
    input_raw = row.get("completion_input_json")
    try:
        completion_input = json.loads(input_raw) if input_raw else None
    except (TypeError, ValueError, json.JSONDecodeError):
        completion_input = None
    code = str(row.get("task_code") or "")
    info = meta or {}
    completed_by = int(row["completed_by_user_id"]) if row.get("completed_by_user_id") is not None else None
    return {
        "id": int(row.get("id") or 0),
        "task_code": code,
        "task_name": info.get("name") or _role_label(code, catalog),
        "display_order": int(row.get("display_order") or 0),
        "required": bool(row.get("required", True)),
        "status": str(row.get("status") or ITEM_PENDING),
        "completed_at": str(row.get("completed_at") or "")[:19] or None,
        "completed_by_user_id": completed_by,
        "completed_by_name": (names or {}).get(completed_by) if completed_by is not None else None,
        "completion_input": completion_input,
        "child_activity_id": int(row["child_activity_id"])
        if row.get("child_activity_id") is not None
        else None,
        "completion_type": info.get("completion_type") or COMPLETION_SIMPLE,
        "input_schema": info.get("input_schema") or [],
        "verification_required": bool(info.get("verification_required", False)),
        "verification_method": info.get("verification_method"),
        "timer_enabled": bool(info.get("timer_enabled", True)),
    }


def enrich_shared_group_activity(
    cursor,
    organization_id: int,
    activity: dict[str, Any],
) -> dict[str, Any]:
    ensure_shared_activity_schema(cursor)
    oid = int(organization_id)
    session_id = activity.get("shared_session_id")
    if session_id is None and activity.get("id"):
        row = get_activity(cursor, oid, int(activity["id"]))
        session_id = row.get("shared_session_id") if row else None
    if session_id is None:
        return activity
    session = get_shared_session(cursor, oid, int(session_id))
    if not session:
        return activity
    catalog = _role_catalog(cursor, oid)
    items = list_shared_session_items(cursor, oid, int(session_id))
    name_ids = {
        int(it["completed_by_user_id"])
        for it in items
        if it.get("completed_by_user_id") is not None
    }
    names = _employee_names(cursor, oid, sorted(name_ids)) if name_ids else {}
    serialized = []
    for it in items:
        meta = _task_meta_for_role(cursor, oid, str(it.get("task_code") or ""))
        serialized.append(serialize_shared_item(it, catalog=catalog, meta=meta, names=names))
    required = [x for x in serialized if x["required"]]
    done_req = [x for x in required if x["status"] == ITEM_COMPLETED]
    checklist_complete = str(session.get("status") or "") == SESSION_CHECKLIST_COMPLETE or (
        len(required) > 0 and len(done_req) == len(required)
    )
    group_cfg = get_activity_group(cursor, oid, role_code=str(activity.get("role") or ""))
    out = dict(activity)
    out["activity_kind"] = KIND_GROUP
    out["is_activity_group"] = True
    out["execution_mode"] = EXECUTION_SHARED
    out["shared_session_id"] = int(session_id)
    out["shared_checklist_complete"] = checklist_complete
    out["shared_session_status"] = str(session.get("status") or SESSION_OPEN)
    out["participation_complete"] = str(out.get("status") or "") != "in_progress"
    out["group"] = {
        "code": (group_cfg or {}).get("code"),
        "name": (group_cfg or {}).get("name") or out.get("role_label"),
        "category_code": (group_cfg or {}).get("category_code") or out.get("category_code"),
        "execution_mode": EXECUTION_SHARED,
        "items": serialized,
        "required_count": len(required),
        "completed_required_count": len(done_req),
        # Shared: employee may finish participation anytime; checklist completeness is separate.
        "can_complete_group": True,
        "can_finish_participation": True,
        "checklist_complete": checklist_complete,
    }
    from backend.cleaning_task_activity import partners_for_activity

    out["partners"] = partners_for_activity(cursor, oid, out)
    return out


def _spawn_shared_item_verification(
    cursor,
    *,
    organization_id: int,
    parent_activity: Mapping[str, Any],
    item: Mapping[str, Any],
    catalog: Mapping[str, Mapping[str, Any]],
) -> int | None:
    """Create one verification child for a shared item (idempotent via child_activity_id)."""
    if item.get("child_activity_id") is not None:
        return int(item["child_activity_id"])
    code = str(item.get("task_code") or "")
    meta = _task_meta_for_role(cursor, int(organization_id), code)
    verify_required = bool(meta.get("verification_required", True))
    verify_method = str(meta.get("verification_method") or VERIFY_SUPERVISOR)
    if not verify_required:
        verify_method = VERIFY_NONE
    if verify_method == VERIFY_NONE:
        return None
    completed_by = int(item["completed_by_user_id"]) if item.get("completed_by_user_id") is not None else int(
        parent_activity.get("user_id") or 0
    )
    at = item.get("completed_at") or eastern_now_naive()
    cursor.execute(
        f"""
        INSERT INTO {TABLE} (
          organization_id, responsibility_id, assignment_group_id, user_id,
          shift_session_id, business_date, role, timing_mode, planned_start_time,
          status, started_at, ended_at, duration_seconds,
          category_code, completion_type, timer_enabled, verification_required,
          verification_method, verification_timing, checklist_id, completion_input_json,
          parent_activity_id, activity_kind, shared_session_id
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            int(parent_activity["responsibility_id"]),
            parent_activity.get("assignment_group_id"),
            completed_by,
            parent_activity.get("shift_session_id"),
            parent_activity.get("business_date"),
            code,
            parent_activity.get("timing_mode") or "anytime",
            parent_activity.get("planned_start_time"),
            STATUS_PENDING_APPROVAL,
            at,
            at,
            None,
            meta.get("category_code"),
            meta.get("completion_type") or COMPLETION_SIMPLE,
            0,
            1,
            verify_method,
            meta.get("verification_timing") or "same_shift",
            meta.get("checklist_id"),
            item.get("completion_input_json"),
            int(parent_activity["id"]),
            KIND_GROUP_ITEM,
            parent_activity.get("shared_session_id"),
        ),
    )
    child_id = int(cursor.lastrowid)
    cursor.execute(
        f"UPDATE {SESSION_ITEMS_TABLE} SET child_activity_id=%s WHERE id=%s",
        (child_id, int(item["id"])),
    )
    _record_event(
        cursor,
        organization_id=int(organization_id),
        activity_id=child_id,
        event_type="group_item_submitted",
        actor_user_id=completed_by,
        payload={
            "parent_activity_id": int(parent_activity["id"]),
            "task_code": code,
            "status": STATUS_PENDING_APPROVAL,
            "shared_session_id": parent_activity.get("shared_session_id"),
        },
    )
    return child_id


def maybe_complete_shared_checklist(
    cursor,
    *,
    organization_id: int,
    session_id: int,
    parent_activity: Mapping[str, Any],
) -> bool:
    """Mark checklist complete and spawn verification children once."""
    items = list_shared_session_items(cursor, int(organization_id), int(session_id))
    required = [it for it in items if bool(it.get("required", True))]
    if not required or any(str(it.get("status")) != ITEM_COMPLETED for it in required):
        return False
    session = get_shared_session(cursor, int(organization_id), int(session_id))
    already = str((session or {}).get("status") or "") == SESSION_CHECKLIST_COMPLETE
    at = eastern_now_naive()
    if not already:
        cursor.execute(
            f"""
            UPDATE {SESSIONS_TABLE}
            SET status=%s, checklist_completed_at=%s
            WHERE id=%s AND organization_id=%s AND status=%s
            """,
            (SESSION_CHECKLIST_COMPLETE, at, int(session_id), int(organization_id), SESSION_OPEN),
        )
    catalog = _role_catalog(cursor, int(organization_id))
    for it in items:
        if str(it.get("status")) != ITEM_COMPLETED:
            continue
        _spawn_shared_item_verification(
            cursor,
            organization_id=int(organization_id),
            parent_activity=parent_activity,
            item=it,
            catalog=catalog,
        )
    return True


def checkoff_shared_item(
    conn,
    cursor,
    *,
    organization_id: int,
    user_id: int,
    activity_id: int,
    task_code: str,
    completion_input: Any = None,
) -> dict[str, Any]:
    ensure_shared_activity_schema(cursor)
    oid = int(organization_id)
    uid = int(user_id)
    row = get_activity(cursor, oid, int(activity_id))
    if not row or int(row.get("user_id") or 0) != uid:
        raise CleaningTaskError("Active activity group not found.", status=404)
    # Participants may finish their timer before the shared checklist is done.
    # Allow check-off while the session is still open, even after participation ends.
    status = str(row.get("status") or "")
    session_id = row.get("shared_session_id")
    if session_id is None:
        raise CleaningTaskError("Not a shared activity session.", status=400)
    session = get_shared_session(cursor, oid, int(session_id))
    session_status = str((session or {}).get("status") or SESSION_OPEN)
    if status == "in_progress":
        pass
    elif status in {STATUS_COMPLETED, STATUS_PENDING_APPROVAL, STATUS_APPROVED}:
        if session_status == SESSION_CHECKLIST_COMPLETE:
            raise CleaningTaskError("Shared checklist is already complete.", status=400)
    else:
        raise CleaningTaskError("That activity group is not available for check-off.", status=400)
    # Must be an assigned collaborator on this shared assignment.
    group_id = str(row.get("assignment_group_id") or "").strip()
    if not group_id:
        raise CleaningTaskError("Shared assignment is missing.", status=400)

    code = str(task_code or "").strip()
    cursor.execute(
        f"""
        SELECT * FROM {SESSION_ITEMS_TABLE}
        WHERE organization_id=%s AND shared_session_id=%s AND task_code=%s
        LIMIT 1
        """,
        (oid, int(session_id), code),
    )
    item = cursor.fetchone()
    if not item:
        raise CleaningTaskError("That task is not part of this activity group.", status=404)

    meta = _task_meta_for_role(cursor, oid, code)
    try:
        validated = validate_completion_input(meta, completion_input)
    except TaskCatalogError as exc:
        raise CleaningTaskError(exc.message, status=exc.status) from exc

    at = eastern_now_naive()
    cursor.execute(
        f"""
        UPDATE {SESSION_ITEMS_TABLE}
        SET status=%s, completed_at=%s, completed_by_user_id=%s, completion_input_json=%s
        WHERE id=%s AND status=%s
        """,
        (
            ITEM_COMPLETED,
            at,
            uid,
            json.dumps(validated, default=str),
            int(item["id"]),
            ITEM_PENDING,
        ),
    )
    if int(getattr(cursor, "rowcount", 0) or 0) == 0:
        raise CleaningTaskError("That task was already checked off.", status=409)

    _record_event(
        cursor,
        organization_id=oid,
        activity_id=int(activity_id),
        event_type="group_item_completed",
        actor_user_id=uid,
        payload={"task_code": code, "shared_session_id": int(session_id)},
    )
    maybe_complete_shared_checklist(
        cursor,
        organization_id=oid,
        session_id=int(session_id),
        parent_activity=row,
    )
    ser = serialize_activity(get_activity(cursor, oid, int(activity_id)), catalog=_role_catalog(cursor, oid))
    ser["shared_session_id"] = int(session_id)
    return enrich_shared_group_activity(cursor, oid, ser)


def finish_shared_participation(
    conn,
    cursor,
    *,
    organization_id: int,
    user_id: int,
    activity_id: int,
) -> dict[str, Any]:
    """End this employee's timer without requiring the full checklist (and without stopping peers)."""
    ensure_shared_activity_schema(cursor)
    oid = int(organization_id)
    uid = int(user_id)
    row = get_activity(cursor, oid, int(activity_id))
    if not row or int(row.get("user_id") or 0) != uid:
        raise CleaningTaskError("Active activity group not found.", status=404)
    if str(row.get("status")) != "in_progress":
        raise CleaningTaskError("That activity group is not in progress.", status=400)
    session_id = row.get("shared_session_id")
    if session_id is None:
        raise CleaningTaskError("Not a shared activity session.", status=400)

    # Ensure verification children exist if checklist already finished.
    maybe_complete_shared_checklist(
        cursor,
        organization_id=oid,
        session_id=int(session_id),
        parent_activity=row,
    )

    at = eastern_now_naive()
    started = row.get("started_at")
    if isinstance(started, str):
        try:
            started = datetime.fromisoformat(started[:19])
        except ValueError:
            started = at
    duration = max(0, int((at - started).total_seconds())) if isinstance(started, datetime) else 0
    activity = _finalize_completion(
        cursor,
        oid=oid,
        uid=uid,
        activity_id=int(activity_id),
        row=row,
        at=at,
        duration=duration,
        completion_input=None,
        interrupt_role=True,
        force_status=STATUS_COMPLETED,
        force_verify=False,
    )
    session = get_shared_session(cursor, oid, int(session_id))
    checklist_complete = str((session or {}).get("status") or "") == SESSION_CHECKLIST_COMPLETE
    _record_event(
        cursor,
        organization_id=oid,
        activity_id=int(activity_id),
        event_type="group_participation_completed",
        actor_user_id=uid,
        payload={
            "duration_seconds": duration,
            "shared_session_id": int(session_id),
            "shared_checklist_complete": checklist_complete,
        },
    )
    activity = serialize_activity(get_activity(cursor, oid, int(activity_id)), catalog=_role_catalog(cursor, oid))
    activity["shared_session_id"] = int(session_id)
    return enrich_shared_group_activity(cursor, oid, activity)
