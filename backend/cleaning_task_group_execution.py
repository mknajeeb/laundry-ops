"""Grouped Task Activity execution (one shared timer + per-item checkoffs).

Parent ``cleaning_task_activities`` row holds the group timer/duration.
``cleaning_task_activity_items`` stores per-task completion + inputs.
On Complete Group, verification child activities are inserted for items that
require peer/supervisor/next-day verification (duration_seconds NULL so hours
are not double-counted).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Mapping, Optional

from backend.business_time import business_today
from backend.cleaning_task_activity import (
    ACTIVE_STATUSES,
    COMPLETED_STATUSES,
    EVENTS,
    STATUS_APPROVED,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING_APPROVAL,
    STATUS_REJECTED,
    TABLE,
    CleaningTaskError,
    _day_responsibilities,
    _finalize_completion,
    _record_event,
    _role_catalog,
    _role_label,
    _task_meta_for_role,
    ensure_cleaning_task_activity_tables,
    get_activity,
    get_open_activity,
    serialize_activity,
)
from backend.payroll_identity import eastern_now_naive
from backend.task_activity_groups import (
    ACTIVITY_GROUP_PREFIX,
    get_activity_group,
    is_activity_group_code,
)
from backend.task_catalog import (
    COMPLETION_SIMPLE,
    VERIFY_NONE,
    VERIFY_SUPERVISOR,
    TaskCatalogError,
    validate_completion_input,
)
from backend.ta_helpers import invalidate_schema_cache, table_exists, table_has_column

ITEMS_TABLE = "cleaning_task_activity_items"
KIND_STANDALONE = "standalone"
KIND_GROUP = "group"
KIND_GROUP_ITEM = "group_item"

ITEM_PENDING = "pending"
ITEM_COMPLETED = "completed"


def ensure_group_activity_schema(cursor) -> None:
    ensure_cleaning_task_activity_tables(cursor)
    for col, ddl in (
        ("parent_activity_id", "BIGINT NULL"),
        ("activity_kind", "VARCHAR(20) NULL"),
        ("shared_session_id", "BIGINT NULL"),
    ):
        if not table_has_column(cursor, TABLE, col):
            cursor.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} {ddl}")
    if not table_exists(cursor, ITEMS_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {ITEMS_TABLE} (
              id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              activity_id BIGINT NOT NULL,
              task_code VARCHAR(64) NOT NULL,
              display_order INT NOT NULL DEFAULT 0,
              required TINYINT(1) NOT NULL DEFAULT 1,
              status VARCHAR(32) NOT NULL,
              completed_at DATETIME NULL,
              completion_input_json TEXT NULL,
              child_activity_id BIGINT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_ctai (activity_id, task_code),
              INDEX idx_ctai_org_activity (organization_id, activity_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    from backend.cleaning_task_shared_execution import ensure_shared_activity_schema

    ensure_shared_activity_schema(cursor)
    invalidate_schema_cache()


def list_activity_items(cursor, organization_id: int, activity_id: int) -> list[dict[str, Any]]:
    ensure_group_activity_schema(cursor)
    cursor.execute(
        f"""
        SELECT * FROM {ITEMS_TABLE}
        WHERE organization_id=%s AND activity_id=%s
        ORDER BY display_order ASC, id ASC
        """,
        (int(organization_id), int(activity_id)),
    )
    return [r for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def serialize_group_item(
    row: Mapping[str, Any],
    *,
    catalog: Mapping[str, Mapping[str, Any]] | None = None,
    meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    input_raw = row.get("completion_input_json")
    try:
        completion_input = json.loads(input_raw) if input_raw else None
    except (TypeError, ValueError, json.JSONDecodeError):
        completion_input = None
    code = str(row.get("task_code") or "")
    info = meta or {}
    return {
        "id": int(row.get("id") or 0),
        "task_code": code,
        "task_name": info.get("name") or _role_label(code, catalog),
        "display_order": int(row.get("display_order") or 0),
        "required": bool(row.get("required", True)),
        "status": str(row.get("status") or ITEM_PENDING),
        "completed_at": str(row.get("completed_at") or "")[:19] or None,
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


def enrich_open_group_activity(cursor, organization_id: int, activity: dict[str, Any]) -> dict[str, Any]:
    """Attach group membership + item progress for PIN recovery."""
    ensure_group_activity_schema(cursor)
    oid = int(organization_id)
    kind = str(activity.get("activity_kind") or "")
    role = str(activity.get("role") or "")
    if kind != KIND_GROUP and not is_activity_group_code(role):
        return activity
    # Shared execution: collaborative checklist keyed by shared_session_id.
    session_id = activity.get("shared_session_id")
    if session_id is None and activity.get("id"):
        row = get_activity(cursor, oid, int(activity["id"]))
        session_id = row.get("shared_session_id") if row else None
    if session_id is not None:
        from backend.cleaning_task_shared_execution import enrich_shared_group_activity

        activity = dict(activity)
        activity["shared_session_id"] = int(session_id)
        return enrich_shared_group_activity(cursor, oid, activity)
    catalog = _role_catalog(cursor, oid)
    group = get_activity_group(cursor, oid, role_code=role)
    items = list_activity_items(cursor, oid, int(activity["id"]))
    serialized = []
    for it in items:
        meta = _task_meta_for_role(cursor, oid, str(it.get("task_code") or ""))
        serialized.append(serialize_group_item(it, catalog=catalog, meta=meta))
    required = [x for x in serialized if x["required"]]
    done_req = [x for x in required if x["status"] == ITEM_COMPLETED]
    activity = dict(activity)
    activity["activity_kind"] = KIND_GROUP
    activity["is_activity_group"] = True
    activity["execution_mode"] = "individual"
    activity["group"] = {
        "code": (group or {}).get("code"),
        "name": (group or {}).get("name") or activity.get("role_label"),
        "category_code": (group or {}).get("category_code") or activity.get("category_code"),
        "execution_mode": "individual",
        "items": serialized,
        "required_count": len(required),
        "completed_required_count": len(done_req),
        "can_complete_group": len(required) > 0 and len(done_req) == len(required),
        "checklist_complete": len(required) > 0 and len(done_req) == len(required),
    }
    return activity


def start_group_activity(
    conn,
    cursor,
    *,
    organization_id: int,
    user_id: int,
    responsibility_id: int,
    shift_session_id: int | None,
    business_date: date | None = None,
) -> dict[str, Any]:
    from backend.shift_job_tracking import close_open_job_segment, get_open_job_segment
    from backend.ta_routes import get_open_break

    ensure_group_activity_schema(cursor)
    oid = int(organization_id)
    uid = int(user_id)
    today = business_today()
    day = business_date or today
    catalog = _role_catalog(cursor, oid)
    historical = day != today
    # Historical supervisor backfill must never pause production-role segments.
    if historical:
        shift_session_id = None

    if not historical and get_open_activity(cursor, oid, uid):
        raise CleaningTaskError("Finish your current task first.", status=400)
    if shift_session_id and get_open_break(conn, int(shift_session_id)):
        raise CleaningTaskError("Finish your break before starting a task.", status=400)

    assignments = _day_responsibilities(cursor, oid, business_date=day, user_id=uid)
    target = next((a for a in assignments if int(a["id"]) == int(responsibility_id)), None)
    if not target:
        raise CleaningTaskError(
            "That activity is not assigned to you today."
            if not historical
            else "That activity is not assigned on the selected date.",
            status=404,
        )
    role = str(target.get("role") or "")
    if not is_activity_group_code(role):
        raise CleaningTaskError("That assignment is not an activity group.", status=400)
    group = get_activity_group(cursor, oid, role_code=role)
    if not group or not group.get("active"):
        raise CleaningTaskError("Activity group is inactive or missing.", status=404)
    if not group.get("items"):
        raise CleaningTaskError("Activity group has no tasks configured.", status=400)

    from backend.cleaning_task_shared_execution import (
        ensure_shared_session,
        is_shared_execution,
    )

    shared = is_shared_execution(target)

    # Already completed?
    cursor.execute(
        f"""
        SELECT id, status FROM {TABLE}
        WHERE organization_id=%s AND user_id=%s AND responsibility_id=%s
          AND (parent_activity_id IS NULL)
          AND (activity_kind=%s OR role=%s)
        ORDER BY id DESC LIMIT 1
        """,
        (oid, uid, int(responsibility_id), KIND_GROUP, role),
    )
    latest = cursor.fetchone()
    if latest and str(latest.get("status")) in {
        STATUS_IN_PROGRESS,
        STATUS_PENDING_APPROVAL,
        STATUS_APPROVED,
        STATUS_COMPLETED,
    }:
        raise CleaningTaskError("This activity group is already in progress or completed.", status=400)

    at = eastern_now_naive()
    paused_cat = paused_role = None
    if shift_session_id:
        open_seg = get_open_job_segment(conn, int(shift_session_id))
        if open_seg:
            paused_cat = open_seg.get("category_id")
            paused_role = open_seg.get("role_id")
            close_open_job_segment(conn, int(shift_session_id), at, close_source="cleaning_task_group_start")

    shared_session_id = None
    if shared:
        session = ensure_shared_session(
            cursor,
            organization_id=oid,
            assignment_group_id=str(target.get("assignment_group_id")),
            business_date=day,
            role=role,
            group_items=group.get("items") or [],
        )
        shared_session_id = int(session["id"])

    from backend.task_verification_policy import resolve_verification_policy, snapshot_columns

    # Snapshot group-level effective policy on the parent (audit). Verification of
    # work products still lives on child item rows at complete-group time.
    group_policy = resolve_verification_policy(cursor, oid, activity_group=group)
    group_snap = snapshot_columns(group_policy)
    cursor.execute(
        f"""
        INSERT INTO {TABLE} (
          organization_id, responsibility_id, assignment_group_id, user_id,
          shift_session_id, business_date, role, timing_mode, planned_start_time,
          status, started_at, paused_category_id, paused_role_id,
          category_code, completion_type, timer_enabled, verification_required,
          verification_method, verification_timing, checklist_id,
          parent_activity_id, activity_kind, shared_session_id
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            oid,
            int(target["id"]),
            target.get("assignment_group_id"),
            uid,
            int(shift_session_id) if shift_session_id else None,
            day,
            role,
            target.get("timing_mode") or "anytime",
            target.get("start_time"),
            STATUS_IN_PROGRESS,
            at,
            paused_cat,
            paused_role,
            group.get("category_code"),
            COMPLETION_SIMPLE,
            1,
            group_snap["verification_required"],
            group_snap["verification_method"],
            group_snap["verification_timing"],
            None,
            None,
            KIND_GROUP,
            shared_session_id,
        ),
    )
    activity_id = int(cursor.lastrowid)
    if not shared:
        for item in group["items"]:
            cursor.execute(
                f"""
                INSERT INTO {ITEMS_TABLE}
                  (organization_id, activity_id, task_code, display_order, required, status)
                VALUES (%s,%s,%s,%s,%s,%s)
                """,
                (
                    oid,
                    activity_id,
                    item["task_code"],
                    int(item.get("display_order") or 0),
                    1 if item.get("required", True) else 0,
                    ITEM_PENDING,
                ),
            )
    _record_event(
        cursor,
        organization_id=oid,
        activity_id=activity_id,
        event_type="group_started",
        actor_user_id=uid,
        payload={
            "role": role,
            "item_count": len(group["items"]),
            "execution_mode": "shared" if shared else "individual",
            "shared_session_id": shared_session_id,
        },
    )
    row = get_activity(cursor, oid, activity_id)
    ser = serialize_activity(row, catalog=catalog)
    if shared_session_id is not None:
        ser["shared_session_id"] = shared_session_id
    return enrich_open_group_activity(cursor, oid, ser)


def checkoff_group_item(
    conn,
    cursor,
    *,
    organization_id: int,
    user_id: int,
    activity_id: int,
    task_code: str,
    completion_input: Any = None,
) -> dict[str, Any]:
    ensure_group_activity_schema(cursor)
    oid = int(organization_id)
    uid = int(user_id)
    row = get_activity(cursor, oid, int(activity_id))
    if not row or int(row.get("user_id") or 0) != uid:
        raise CleaningTaskError("Active activity group not found.", status=404)
    if str(row.get("status")) != STATUS_IN_PROGRESS:
        raise CleaningTaskError("That activity group is not in progress.", status=400)
    if str(row.get("activity_kind") or "") != KIND_GROUP and not is_activity_group_code(row.get("role")):
        raise CleaningTaskError("Not an activity group session.", status=400)

    if row.get("shared_session_id") is not None:
        from backend.cleaning_task_shared_execution import checkoff_shared_item

        return checkoff_shared_item(
            conn,
            cursor,
            organization_id=oid,
            user_id=uid,
            activity_id=int(activity_id),
            task_code=task_code,
            completion_input=completion_input,
        )

    code = str(task_code or "").strip()
    cursor.execute(
        f"""
        SELECT * FROM {ITEMS_TABLE}
        WHERE organization_id=%s AND activity_id=%s AND task_code=%s
        LIMIT 1
        """,
        (oid, int(activity_id), code),
    )
    item = cursor.fetchone()
    if not item:
        raise CleaningTaskError("That task is not part of this activity group.", status=404)
    if str(item.get("status")) == ITEM_COMPLETED:
        raise CleaningTaskError("That task is already checked off.", status=400)

    meta = _task_meta_for_role(cursor, oid, code)
    try:
        validated = validate_completion_input(meta, completion_input)
    except TaskCatalogError as exc:
        raise CleaningTaskError(exc.message, status=exc.status) from exc

    at = eastern_now_naive()
    cursor.execute(
        f"""
        UPDATE {ITEMS_TABLE}
        SET status=%s, completed_at=%s, completion_input_json=%s
        WHERE id=%s AND status=%s
        """,
        (ITEM_COMPLETED, at, json.dumps(validated, default=str), int(item["id"]), ITEM_PENDING),
    )
    if int(getattr(cursor, "rowcount", 0) or 0) == 0:
        raise CleaningTaskError("That task was already checked off.", status=409)
    _record_event(
        cursor,
        organization_id=oid,
        activity_id=int(activity_id),
        event_type="group_item_completed",
        actor_user_id=uid,
        payload={"task_code": code},
    )
    ser = serialize_activity(get_activity(cursor, oid, int(activity_id)), catalog=_role_catalog(cursor, oid))
    return enrich_open_group_activity(cursor, oid, ser)


def complete_group_activity(
    conn,
    cursor,
    *,
    organization_id: int,
    user_id: int,
    activity_id: int,
) -> dict[str, Any]:
    ensure_group_activity_schema(cursor)
    oid = int(organization_id)
    uid = int(user_id)
    row = get_activity(cursor, oid, int(activity_id))
    if not row or int(row.get("user_id") or 0) != uid:
        raise CleaningTaskError("Active activity group not found.", status=404)
    if str(row.get("status")) != STATUS_IN_PROGRESS:
        raise CleaningTaskError("That activity group is not in progress.", status=400)

    if row.get("shared_session_id") is not None:
        from backend.cleaning_task_shared_execution import finish_shared_participation

        return finish_shared_participation(
            conn,
            cursor,
            organization_id=oid,
            user_id=uid,
            activity_id=int(activity_id),
        )

    items = list_activity_items(cursor, oid, int(activity_id))
    missing = [
        str(it.get("task_code"))
        for it in items
        if bool(it.get("required", True)) and str(it.get("status")) != ITEM_COMPLETED
    ]
    from backend.task_activity_groups import (
        get_activity_group,
        group_has_required_checklist_items,
        participation_finish_allowed_with_open_checklist,
    )

    parent_group = get_activity_group(cursor, oid, role_code=str(row.get("role") or ""))
    has_required = bool(missing) or group_has_required_checklist_items(
        (parent_group or {}).get("items")
    )
    finish_with_open_checklist = participation_finish_allowed_with_open_checklist(
        None if not parent_group else parent_group.get("require_checklist_before_completion"),
        shared=False,
        has_required_items=has_required,
    )
    if missing and not finish_with_open_checklist:
        raise CleaningTaskError(
            f"Check off all required tasks first ({len(missing)} remaining).",
            status=400,
            payload={"missing_task_codes": missing},
        )

    at = eastern_now_naive()
    started = row.get("started_at")
    if isinstance(started, str):
        try:
            started = datetime.fromisoformat(started[:19])
        except ValueError:
            started = at
    duration = max(0, int((at - started).total_seconds())) if isinstance(started, datetime) else 0

    # Spawn verification child activities (no duration) for items that need verify.
    catalog = _role_catalog(cursor, oid)
    from backend.task_verification_policy import resolve_verification_policy, snapshot_columns
    for it in items:
        if str(it.get("status")) != ITEM_COMPLETED:
            continue
        code = str(it.get("task_code") or "")
        meta = _task_meta_for_role(cursor, oid, code)
        policy = resolve_verification_policy(
            cursor,
            oid,
            task_code=code,
            activity_group=parent_group,
            task_definition=meta,
        )
        snap = snapshot_columns(policy)
        verify_required = bool(snap["verification_required"])
        verify_method = str(snap["verification_method"])
        status = (
            STATUS_PENDING_APPROVAL
            if verify_required and verify_method != VERIFY_NONE
            else STATUS_COMPLETED
        )
        completed_at = it.get("completed_at") or at
        cursor.execute(
            f"""
            INSERT INTO {TABLE} (
              organization_id, responsibility_id, assignment_group_id, user_id,
              shift_session_id, business_date, role, timing_mode, planned_start_time,
              status, started_at, ended_at, duration_seconds,
              category_code, completion_type, timer_enabled, verification_required,
              verification_method, verification_timing, checklist_id, completion_input_json,
              parent_activity_id, activity_kind
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                oid,
                int(row["responsibility_id"]),
                row.get("assignment_group_id"),
                uid,
                row.get("shift_session_id"),
                row.get("business_date"),
                code,
                row.get("timing_mode") or "anytime",
                row.get("planned_start_time"),
                status,
                completed_at,
                completed_at,
                None,  # do not attribute group duration to items
                meta.get("category_code"),
                meta.get("completion_type") or COMPLETION_SIMPLE,
                0,
                snap["verification_required"],
                snap["verification_method"],
                snap["verification_timing"],
                meta.get("checklist_id"),
                it.get("completion_input_json"),
                int(activity_id),
                KIND_GROUP_ITEM,
            ),
        )
        child_id = int(cursor.lastrowid)
        cursor.execute(
            f"UPDATE {ITEMS_TABLE} SET child_activity_id=%s WHERE id=%s",
            (child_id, int(it["id"])),
        )
        _record_event(
            cursor,
            organization_id=oid,
            activity_id=child_id,
            event_type="group_item_submitted",
            actor_user_id=uid,
            payload={"parent_activity_id": int(activity_id), "task_code": code, "status": status},
        )

    # Close parent as completed (verification lives on children).
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
    _record_event(
        cursor,
        organization_id=oid,
        activity_id=int(activity_id),
        event_type="group_completed",
        actor_user_id=uid,
        payload={"duration_seconds": duration, "items": len(items)},
    )
    activity = enrich_open_group_activity(cursor, oid, activity)
    activity["activity_kind"] = KIND_GROUP
    activity["is_activity_group"] = True
    return activity
