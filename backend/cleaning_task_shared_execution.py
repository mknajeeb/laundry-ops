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
    STATUS_IN_PROGRESS,
    STATUS_PENDING_APPROVAL,
    TABLE,
    CleaningTaskError,
    _employee_names,
    _finalize_completion,
    _gate_lost_found_completion,
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
from backend.ta_helpers import invalidate_table_schema, remember_column, table_exists, table_has_column

SESSIONS_TABLE = "cleaning_task_shared_sessions"
SESSION_ITEMS_TABLE = "cleaning_task_shared_session_items"
CHECKS_TABLE = "cleaning_task_shared_item_checks"

SESSION_OPEN = "open"
SESSION_CHECKLIST_COMPLETE = "checklist_complete"
ITEM_PENDING = "pending"
ITEM_COMPLETED = "completed"
ITEM_EXCUSED = "excused"
ACK_ANY = "any"
ACK_EACH = "each"
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
        invalidate_table_schema("cleaning_task_shared_sessions")
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
        invalidate_table_schema(SESSION_ITEMS_TABLE)
    if not table_exists(cursor, CHECKS_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {CHECKS_TABLE} (
              id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              session_item_id BIGINT NOT NULL,
              user_id INT NOT NULL,
              status VARCHAR(32) NOT NULL,
              completed_at DATETIME NULL,
              completion_input_json TEXT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_ctsic (session_item_id, user_id),
              INDEX idx_ctsic_org_item (organization_id, session_item_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        invalidate_table_schema(CHECKS_TABLE)
    if table_exists(cursor, TABLE) and not table_has_column(cursor, TABLE, "shared_session_id"):
        cursor.execute(f"ALTER TABLE {TABLE} ADD COLUMN shared_session_id BIGINT NULL")
        remember_column(TABLE, "shared_session_id")
        try:
            cursor.execute(
                f"ALTER TABLE {TABLE} ADD INDEX idx_cta_shared_session (organization_id, shared_session_id)"
            )
        except Exception:
            pass
    if table_exists(cursor, SESSIONS_TABLE) and not table_has_column(
        cursor, SESSIONS_TABLE, "participation_adjustments_json"
    ):
        cursor.execute(f"ALTER TABLE {SESSIONS_TABLE} ADD COLUMN participation_adjustments_json TEXT NULL")
        remember_column(SESSIONS_TABLE, "participation_adjustments_json")
    if table_exists(cursor, SESSION_ITEMS_TABLE) and not table_has_column(
        cursor, SESSION_ITEMS_TABLE, "acknowledgment_mode"
    ):
        cursor.execute(f"ALTER TABLE {SESSION_ITEMS_TABLE} ADD COLUMN acknowledgment_mode VARCHAR(16) NULL")
        remember_column(SESSION_ITEMS_TABLE, "acknowledgment_mode")


def normalize_acknowledgment_mode(value: Any) -> str:
    return ACK_EACH if str(value or "").strip().lower() in {"each", "all", "every"} else ACK_ANY


def required_acknowledger_ids(
    *,
    acknowledgment_mode: Any,
    responsibility_mode: Any,
    responsibility_user_ids: Sequence[int] | None,
    assigned_user_ids: Sequence[int] | None,
) -> list[int]:
    """Employees who must personally acknowledge. Empty means one assigned employee can."""
    if normalize_acknowledgment_mode(acknowledgment_mode) != ACK_EACH:
        return []
    assigned = _assigned_user_ids(assigned_user_ids)
    named = _assigned_user_ids(responsibility_user_ids or [])
    if str(responsibility_mode or "").strip().lower() == "named" and named:
        chosen = [uid for uid in named if uid in assigned] or named
        return chosen
    return assigned


def item_acknowledgments_satisfied(statuses: Sequence[str]) -> bool:
    """Excused checks are not completions. An item with only excuses stays open."""
    live = [str(status or "") for status in statuses or [] if str(status or "") != ITEM_EXCUSED]
    return bool(live) and all(status == ITEM_COMPLETED for status in live)


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


def _assigned_user_ids(user_ids: Sequence[int] | None) -> list[int]:
    out: list[int] = []
    for raw in user_ids or []:
        try:
            uid = int(raw)
        except (TypeError, ValueError):
            continue
        if uid > 0 and uid not in out:
            out.append(uid)
    return out


def load_employee_checks(
    cursor,
    organization_id: int,
    item_ids: Sequence[int],
) -> dict[int, list[dict[str, Any]]]:
    """Per-employee check-offs for shared checklist items. Empty for older sessions."""
    ids = [int(item_id) for item_id in item_ids or [] if int(item_id or 0) > 0]
    if not ids:
        return {}
    ensure_shared_activity_schema(cursor)
    grouped: dict[int, list[dict[str, Any]]] = {item_id: [] for item_id in ids}
    for item_id in ids:
        cursor.execute(
            f"""
            SELECT * FROM {CHECKS_TABLE}
            WHERE organization_id=%s AND session_item_id=%s
            ORDER BY user_id ASC, id ASC
            """,
            (int(organization_id), int(item_id)),
        )
        grouped[int(item_id)] = [row for row in (cursor.fetchall() or []) if isinstance(row, dict)]
    return grouped


def serialize_employee_checks(
    checks: Sequence[Mapping[str, Any]],
    names: Mapping[int, str] | None = None,
) -> list[dict[str, Any]]:
    out = []
    for row in checks or []:
        uid = int(row.get("user_id") or 0)
        if not uid:
            continue
        out.append(
            {
                "user_id": uid,
                "employee_name": (names or {}).get(uid) or f"User #{uid}",
                "status": str(row.get("status") or ITEM_PENDING),
                "completed_at": str(row.get("completed_at") or "")[:19] or None,
            }
        )
    return out


def open_required_codes_for_user(
    items: Sequence[Mapping[str, Any]],
    checks_by_item: Mapping[int, Sequence[Mapping[str, Any]]],
    user_id: int,
) -> list[str]:
    """Required items this employee still has to check off.

    When a session has per-employee checks, a partner's open item does not count.
    Older sessions have no check rows, so the shared item status still applies.
    Completed item rows are not rewritten.
    """
    uid = int(user_id)
    uses_personal = any(checks_by_item.get(int(item.get("id") or 0)) for item in items or [])
    missing: list[str] = []
    for item in items or []:
        if not bool(item.get("required", True)):
            continue
        code = str(item.get("task_code") or "")
        rows = list(checks_by_item.get(int(item.get("id") or 0)) or [])
        if uses_personal:
            if not rows:
                continue
            mine = next((row for row in rows if int(row.get("user_id") or 0) == uid), None)
            if mine is None:
                missing.append(code)
            elif str(mine.get("status") or "") == ITEM_EXCUSED:
                continue
            elif str(mine.get("status") or "") != ITEM_COMPLETED:
                missing.append(code)
            continue
        if str(item.get("status") or "") != ITEM_COMPLETED:
            missing.append(code)
    return missing


def _insert_check(cursor, organization_id: int, session_item_id: int, user_id: int) -> None:
    cursor.execute(
        f"""
        INSERT INTO {CHECKS_TABLE}
          (organization_id, session_item_id, user_id, status)
        VALUES (%s,%s,%s,%s)
        """,
        (int(organization_id), int(session_item_id), int(user_id), ITEM_PENDING),
    )


def _seed_checks(cursor, organization_id: int, items: Sequence[Mapping[str, Any]], user_ids: Sequence[int]) -> None:
    """Seed personal checks only for items configured as every selected employee.

    Older sessions are not passed here. A missing acknowledgment mode stays one-check.
    """
    assigned = _assigned_user_ids(user_ids)
    if len(assigned) < 2:
        return
    from backend.task_activity_item_responsibility import parse_snapshot

    for item in items or []:
        item_id = int(item.get("id") or 0)
        if not item_id or str(item.get("status") or ITEM_PENDING) == ITEM_COMPLETED:
            continue
        snap = parse_snapshot(item.get("responsibility_snapshot_json"))
        required = required_acknowledger_ids(
            acknowledgment_mode=item.get("acknowledgment_mode"),
            responsibility_mode=None if not snap else snap.get("responsibility_mode"),
            responsibility_user_ids=None if not snap else snap.get("responsibility_user_ids"),
            assigned_user_ids=assigned,
        )
        for uid in required:
            _insert_check(cursor, organization_id, item_id, uid)


def _extend_personal_checks(
    cursor,
    organization_id: int,
    session_id: int,
    user_ids: Sequence[int],
) -> None:
    """Add a missing employee to a session that already tracks personal check-offs.

    A session with no check rows stays collaborative. Completed items are left alone.
    """
    assigned = _assigned_user_ids(user_ids)
    if len(assigned) < 2:
        return
    items = list_shared_session_items(cursor, organization_id, int(session_id))
    existing = load_employee_checks(cursor, organization_id, [int(item.get("id") or 0) for item in items])
    if not any(existing.values()):
        return
    for item in items:
        if str(item.get("status") or "") == ITEM_COMPLETED:
            continue
        item_id = int(item.get("id") or 0)
        rows = existing.get(item_id) or []
        if not rows:
            continue
        have = {int(row.get("user_id") or 0) for row in rows}
        for uid in assigned:
            if uid not in have:
                _insert_check(cursor, organization_id, item_id, uid)


def ensure_shared_session(
    cursor,
    *,
    organization_id: int,
    assignment_group_id: str,
    business_date,
    role: str,
    group_items: Sequence[Mapping[str, Any]],
    assigned_user_ids: Sequence[int] | None = None,
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
        _extend_personal_checks(cursor, oid, int(existing["id"]), assigned_user_ids or [])
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
    from backend.ta_helpers import table_has_column
    from backend.task_activity_item_responsibility import (
        load_overrides_for_items,
        resolve_responsibility,
        snapshot_json,
    )

    item_ids = [int(item.get("id") or 0) for item in (group_items or []) if item.get("id")]
    overrides = {}
    try:
        overrides = load_overrides_for_items(cursor, oid, item_ids, day)
    except Exception:
        overrides = {}
    has_snapshot = table_has_column(cursor, SESSION_ITEMS_TABLE, "responsibility_snapshot_json")
    has_definition = table_has_column(cursor, SESSION_ITEMS_TABLE, "definition_snapshot_json")
    from backend.task_activity_item_responsibility import definition_snapshot_json, item_is_active

    for item in group_items or []:
        if not item_is_active(item):
            continue
        resolved = resolve_responsibility(item, overrides.get(int(item.get("id") or 0)))
        snap = snapshot_json(resolved["responsibility_mode"], resolved["responsibility_user_ids"])
        definition = definition_snapshot_json(item) if has_definition else None
        if has_snapshot and has_definition:
            cursor.execute(
                f"""
                INSERT INTO {SESSION_ITEMS_TABLE}
                  (organization_id, shared_session_id, task_code, display_order, required, status,
                   responsibility_snapshot_json, definition_snapshot_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    oid,
                    session_id,
                    str(item.get("task_code") or ""),
                    int(item.get("display_order") or 0),
                    1 if item.get("required", True) else 0,
                    ITEM_PENDING,
                    snap,
                    definition,
                ),
            )
        elif has_snapshot:
            cursor.execute(
                f"""
                INSERT INTO {SESSION_ITEMS_TABLE}
                  (organization_id, shared_session_id, task_code, display_order, required, status,
                   responsibility_snapshot_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    oid,
                    session_id,
                    str(item.get("task_code") or ""),
                    int(item.get("display_order") or 0),
                    1 if item.get("required", True) else 0,
                    ITEM_PENDING,
                    snap,
                ),
            )
        else:
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
    created_items = list_shared_session_items(cursor, oid, session_id)
    modes = {
        str(item.get("task_code") or ""): normalize_acknowledgment_mode(item.get("acknowledgment_mode"))
        for item in (group_items or [])
    }
    store_mode = table_has_column(cursor, SESSION_ITEMS_TABLE, "acknowledgment_mode")
    for created in created_items:
        mode = modes.get(str(created.get("task_code") or ""), ACK_ANY)
        created["acknowledgment_mode"] = mode
        if store_mode:
            cursor.execute(
                f"UPDATE {SESSION_ITEMS_TABLE} SET acknowledgment_mode=%s WHERE id=%s AND organization_id=%s",
                (mode, int(created["id"]), oid),
            )
    _seed_checks(cursor, oid, created_items, assigned_user_ids or [])
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
    info = dict(meta or {})
    from backend.task_activity_item_responsibility import parse_definition_snapshot

    frozen = parse_definition_snapshot(row.get("definition_snapshot_json"))
    if frozen:
        info = {
            **info,
            "name": frozen.get("task_name") or info.get("name"),
            "instructions": frozen.get("instructions"),
            "completion_type": frozen.get("completion_type") or info.get("completion_type"),
            "input_schema": frozen.get("input_schema") or [],
        }
        for field in ("instructions_es", "section_label_es", "task_name_es"):
            info[field] = frozen.get(field) if field in frozen else None
        # An open item shows the current saved wording. A completed item keeps the
        # snapshot from when the session started, and that snapshot is not rewritten.
        if str(row.get("status") or ITEM_PENDING) == ITEM_PENDING and meta is not None:
            live_name = str(meta.get("name") or meta.get("task_name") or "").strip()
            if live_name:
                info["name"] = live_name
            info["instructions"] = str(meta.get("instructions") or meta.get("description") or "").strip() or None
            info["instructions_es"] = str(meta.get("instructions_es") or "").strip() or None
    completed_by = int(row["completed_by_user_id"]) if row.get("completed_by_user_id") is not None else None
    from backend.task_activity_item_responsibility import parse_snapshot, responsibility_payload

    snap = parse_snapshot(row.get("responsibility_snapshot_json"))
    if snap is None:
        responsibility = responsibility_payload("team", [])
    else:
        responsibility = responsibility_payload(
            snap.get("responsibility_mode"),
            snap.get("responsibility_user_ids"),
            names,
        )
    return {
        "id": int(row.get("id") or 0),
        "task_code": code,
        "task_name": info.get("name") or _role_label(code, catalog),
        "display_order": int(row.get("display_order") or 0),
        "required": bool(row.get("required", True)),
        "acknowledgment_mode": normalize_acknowledgment_mode(row.get("acknowledgment_mode"))
        if row.get("acknowledgment_mode")
        else None,
        "status": str(row.get("status") or ITEM_PENDING),
        "completed_at": str(row.get("completed_at") or "")[:19] or None,
        "completed_by_user_id": completed_by,
        "completed_by_name": (names or {}).get(completed_by) if completed_by is not None else None,
        "instructions": info.get("description") or info.get("instructions") or None,
        "instructions_es": info.get("instructions_es"),
        "task_name_es": info.get("task_name_es"),
        "section_label": (frozen or {}).get("section_label"),
        "section_label_es": (frozen or {}).get("section_label_es") if frozen and "section_label_es" in frozen else info.get("section_label_es"),
        "section_order": int((frozen or {}).get("section_order") or 0),
        **responsibility,
        "completion_input": completion_input,
        "child_activity_id": int(row["child_activity_id"])
        if row.get("child_activity_id") is not None
        else None,
        "completion_type": info.get("completion_type") or COMPLETION_SIMPLE,
        "input_schema": info.get("input_schema") or [],
        "verification_required": bool(info.get("verification_required", False)),
        "verification_method": info.get("verification_method"),
        "timer_enabled": bool(info.get("timer_enabled", True)),
        "employee_checks": serialize_employee_checks(row.get("employee_checks") or [], names),
    }


def _employee_remark_input(remark: str | None, user_id: int, at) -> dict | None:
    text = str(remark or "").strip()
    if not text:
        return None
    stamp = at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(at, "strftime") else str(at)[:19]
    return {
        "employee_remark": {
            "text": text[:1000],
            "author_user_id": int(user_id),
            "at": stamp,
        }
    }


def _shared_finish_allowed(group_cfg, required_items, checklist_complete: bool) -> bool:
    """Required items block finish unless the group explicitly turns that rule off."""
    from backend.task_activity_groups import participation_finish_allowed_with_open_checklist

    allowed_open = participation_finish_allowed_with_open_checklist(
        None if not group_cfg else group_cfg.get("require_checklist_before_completion"),
        shared=True,
        has_required_items=len(required_items or []) > 0,
    )
    return bool(allowed_open or checklist_complete)


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
    checks_by_item = load_employee_checks(cursor, oid, [int(it.get("id") or 0) for it in items])
    for it in items:
        it["employee_checks"] = checks_by_item.get(int(it.get("id") or 0)) or []
    from backend.task_activity_item_responsibility import parse_user_ids

    name_ids = {
        int(it["completed_by_user_id"])
        for it in items
        if it.get("completed_by_user_id") is not None
    }
    for rows in checks_by_item.values():
        name_ids.update(int(row.get("user_id") or 0) for row in rows if row.get("user_id"))
    for it in items:
        snap = it.get("responsibility_snapshot_json")
        parsed = None
        if snap:
            try:
                import json as _json

                parsed = _json.loads(snap) if isinstance(snap, str) else snap
            except (TypeError, ValueError):
                parsed = None
        if isinstance(parsed, dict):
            name_ids.update(parse_user_ids(parsed.get("user_ids")))
    names = _employee_names(cursor, oid, sorted(name_ids)) if name_ids else {}
    serialized = []
    for it in items:
        meta = _task_meta_for_role(cursor, oid, str(it.get("task_code") or ""))
        serialized.append(serialize_shared_item(it, catalog=catalog, meta=meta, names=names))
    viewer_id = int(activity.get("user_id") or 0)
    viewer_items = []
    for source, item in zip(items, serialized):
        personal = list(source.get("employee_checks") or [])
        mine = next((row for row in personal if int(row.get("user_id") or 0) == viewer_id), None)
        if not personal or mine is None:
            viewer_items.append(item)
            continue
        viewed = dict(item)
        viewed["status"] = str(mine.get("status") or ITEM_PENDING)
        viewed["completed_at"] = str(mine.get("completed_at") or "")[:19] or None
        if viewed["status"] == ITEM_COMPLETED:
            viewed["completed_by_user_id"] = viewer_id
            viewed["completed_by_name"] = names.get(viewer_id) or f"User #{viewer_id}"
        else:
            viewed["completed_by_user_id"] = None
            viewed["completed_by_name"] = None
        viewer_items.append(viewed)
    required = [x for x in viewer_items if x["required"]]
    done_req = [x for x in required if x["status"] == ITEM_COMPLETED]
    my_checklist_complete = len(required) > 0 and len(done_req) == len(required)
    group_items_done = [
        it
        for it in items
        if bool(it.get("required", True)) and str(it.get("status") or "") == ITEM_COMPLETED
    ]
    group_required = [it for it in items if bool(it.get("required", True))]
    checklist_complete = str(session.get("status") or "") == SESSION_CHECKLIST_COMPLETE or (
        len(group_required) > 0 and len(group_items_done) == len(group_required)
    )
    group_cfg = get_activity_group(cursor, oid, role_code=str(activity.get("role") or ""))
    can_finish = _shared_finish_allowed(
        group_cfg,
        required,
        my_checklist_complete if any(checks_by_item.values()) else checklist_complete,
    )
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
        "items": viewer_items,
        "required_count": len(required),
        "completed_required_count": len(done_req),
        "can_complete_group": can_finish,
        "can_finish_participation": can_finish,
        "checklist_complete": my_checklist_complete if any(checks_by_item.values()) else checklist_complete,
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
    from backend.task_verification_policy import resolve_checklist_item_policy, snapshot_columns

    parent_group = get_activity_group(cursor, int(organization_id), role_code=str(parent_activity.get("role") or ""))
    definition = next(
        (
            row
            for row in ((parent_group or {}).get("items") or [])
            if str(row.get("task_code") or "") == code
        ),
        None,
    )
    policy = resolve_checklist_item_policy(
        cursor,
        int(organization_id),
        activity_group=parent_group,
        item=definition,
    )
    snap = snapshot_columns(policy)
    verify_required = bool(snap["verification_required"])
    verify_method = str(snap["verification_method"])
    if not verify_required or verify_method == VERIFY_NONE:
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
            snap.get("verification_timing") or "same_shift",
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
    _gate_lost_found_completion(
        cursor,
        organization_id=int(organization_id),
        user_id=int(parent_activity.get("user_id") or 0),
        business_date=parent_activity.get("business_date"),
        activity_id=int(parent_activity.get("id") or 0) or None,
        role_codes=[it.get("task_code") for it in items],
    )
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
    from backend.task_activity_item_responsibility import parse_snapshot

    responsibility = parse_snapshot(item.get("responsibility_snapshot_json"))
    if responsibility and str(responsibility.get("responsibility_mode") or "") == "named":
        allowed = {int(value) for value in (responsibility.get("responsibility_user_ids") or [])}
        if allowed and uid not in allowed:
            raise CleaningTaskError("That checklist item is assigned to someone else.", status=403)

    meta = _task_meta_for_role(cursor, oid, code)
    from backend.task_activity_item_responsibility import parse_definition_snapshot

    frozen = parse_definition_snapshot(item.get("definition_snapshot_json"))
    if frozen:
        meta = {
            **meta,
            "completion_type": frozen.get("completion_type") or meta.get("completion_type"),
            "input_schema": frozen.get("input_schema") if frozen.get("input_schema") is not None else meta.get("input_schema"),
        }
    try:
        validated = validate_completion_input(meta, completion_input)
    except TaskCatalogError as exc:
        raise CleaningTaskError(exc.message, status=exc.status) from exc
    from backend.task_completion_photos import persist_completion_photos

    try:
        validated = persist_completion_photos(cursor, oid, validated)
    except TaskCatalogError as exc:
        raise CleaningTaskError(exc.message, status=exc.status) from exc

    at = eastern_now_naive()
    personal = load_employee_checks(cursor, oid, [int(item["id"])]).get(int(item["id"])) or []
    payload_json = json.dumps(validated, default=str)
    if personal:
        mine = next((row for row in personal if int(row.get("user_id") or 0) == uid), None)
        if mine is None:
            raise CleaningTaskError("That task is not on your checklist.", status=404)
        if str(mine.get("status") or "") == ITEM_EXCUSED:
            raise CleaningTaskError("That employee is excused from this item.", status=409)
        if str(mine.get("status") or "") == ITEM_COMPLETED:
            raise CleaningTaskError("That task is already checked off.", status=409)
        cursor.execute(
            f"""
            UPDATE {CHECKS_TABLE}
            SET status=%s, completed_at=%s, completion_input_json=%s
            WHERE id=%s AND user_id=%s AND status=%s
            """,
            (ITEM_COMPLETED, at, payload_json, int(mine["id"]), uid, ITEM_PENDING),
        )
        if int(getattr(cursor, "rowcount", 0) or 0) == 0:
            raise CleaningTaskError("That task was already checked off.", status=409)
        refreshed = load_employee_checks(cursor, oid, [int(item["id"])]).get(int(item["id"])) or []
        if item_acknowledgments_satisfied([str(row.get("status") or "") for row in refreshed]):
            cursor.execute(
                f"""
                UPDATE {SESSION_ITEMS_TABLE}
                SET status=%s, completed_at=%s, completed_by_user_id=%s, completion_input_json=%s
                WHERE id=%s AND status=%s
                """,
                (ITEM_COMPLETED, at, uid, payload_json, int(item["id"]), ITEM_PENDING),
            )
    else:
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
                payload_json,
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
    remark: str | None = None,
) -> dict[str, Any]:
    """End this employee's timer without stopping peers.

    When the activity group requires the checklist before completion, required items
    must be checked off first. Otherwise this employee's participation can finish
    while the shared checklist is still open. The dashboard still reports that
    assignment as In Progress until the checklist is complete.
    """
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

    from backend.task_activity_groups import (
        get_activity_group,
        group_has_required_checklist_items,
        participation_finish_allowed_with_open_checklist,
    )

    group = get_activity_group(cursor, oid, role_code=str(row.get("role") or ""))
    session_items = list_shared_session_items(cursor, oid, int(session_id))
    checks_by_item = load_employee_checks(cursor, oid, [int(it.get("id") or 0) for it in session_items])
    has_required = group_has_required_checklist_items(
        (group or {}).get("items")
    ) or group_has_required_checklist_items(session_items)
    if not participation_finish_allowed_with_open_checklist(
        None if not group else group.get("require_checklist_before_completion"),
        shared=True,
        has_required_items=has_required,
    ):
        missing = open_required_codes_for_user(session_items, checks_by_item, uid)
        if missing:
            raise CleaningTaskError(
                f"Check off all required tasks before finishing ({len(missing)} remaining).",
                status=400,
                payload={"missing_task_codes": missing},
            )

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
        completion_input=_employee_remark_input(remark, uid, at),
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


def _adjustment_rows(session: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    raw = None if not session else session.get("participation_adjustments_json")
    if not raw:
        return []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [row for row in parsed if isinstance(row, dict)] if isinstance(parsed, list) else []


def participation_timer_is_active(activity: Mapping[str, Any] | None) -> bool:
    """True only while this employee's own timer is still open."""
    if not activity:
        return False
    if activity.get("voided_at"):
        return False
    status = str(activity.get("status") or "")
    if status == STATUS_IN_PROGRESS:
        return True
    closed = {
        STATUS_COMPLETED,
        STATUS_APPROVED,
        STATUS_PENDING_APPROVAL,
        "rejected",
        "cancelled",
        "voided",
    }
    return bool(activity.get("started_at")) and not activity.get("ended_at") and status not in closed


def open_participation_activity(cursor, organization_id: int, session_id: int, user_id: int):
    """Latest parent timer for one employee on a shared session. Does not create a row."""
    has_void = table_has_column(cursor, TABLE, "voided_at")
    void_sql = " AND voided_at IS NULL" if has_void else ""
    void_col = ", voided_at" if has_void else ""
    cursor.execute(
        f"""
        SELECT id, status, started_at, ended_at, duration_seconds{void_col}
        FROM {TABLE}
        WHERE organization_id=%s AND shared_session_id=%s AND user_id=%s
          AND parent_activity_id IS NULL
          {void_sql}
        ORDER BY id DESC LIMIT 1
        """,
        (int(organization_id), int(session_id), int(user_id)),
    )
    row = cursor.fetchone()
    return row if isinstance(row, dict) else None


def excused_ids_by_group(cursor, organization_id: int, business_date) -> dict[str, set[int]]:
    """Excused employees keyed by assignment group. Missing sessions mean nobody is excused."""
    if not table_exists(cursor, SESSIONS_TABLE):
        return {}
    cursor.execute(
        f"""
        SELECT assignment_group_id, participation_adjustments_json
        FROM {SESSIONS_TABLE}
        WHERE organization_id=%s AND business_date=%s
        """,
        (int(organization_id), business_date),
    )
    found: dict[str, set[int]] = {}
    for row in cursor.fetchall() or []:
        group_id = str(row.get("assignment_group_id") or "").strip()
        if not group_id:
            continue
        ids: set[int] = set()
        for adjustment in _adjustment_rows(row):
            if str(adjustment.get("action") or "") not in {"excuse", "reassign"}:
                continue
            try:
                uid = int(adjustment.get("user_id") or 0)
            except (TypeError, ValueError):
                continue
            if uid > 0:
                ids.add(uid)
        found[group_id] = ids
    return found


def user_is_excused(cursor, organization_id: int, assignment_group_id: str | None, business_date, user_id: int) -> bool:
    group_id = str(assignment_group_id or "").strip()
    if not group_id:
        return False
    return int(user_id) in excused_ids_by_group(cursor, int(organization_id), business_date).get(group_id, set())


def excused_user_ids_for_session(cursor, organization_id: int, session_id: int) -> list[int]:
    session = get_shared_session(cursor, int(organization_id), int(session_id))
    found: list[int] = []
    for row in _adjustment_rows(session):
        if str(row.get("action") or "") not in {"excuse", "reassign"}:
            continue
        try:
            uid = int(row.get("user_id") or 0)
        except (TypeError, ValueError):
            continue
        if uid > 0 and uid not in found:
            found.append(uid)
    return found


def excuse_or_reassign_participant(
    cursor,
    *,
    organization_id: int,
    actor_user_id: int,
    shared_session_id: int | None,
    employee_user_id: int,
    reason: str,
    action: str = "excuse",
    replacement_user_id: int | None = None,
    assignment_group_id: str | None = None,
    role: str | None = None,
    business_date=None,
    assigned_user_ids: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Remove an absent employee from the requirement. Does not create time or check-offs."""
    ensure_shared_activity_schema(cursor)
    reason_clean = str(reason or "").strip()
    if len(reason_clean) < 3:
        raise CleaningTaskError("A reason is required.", status=400)
    chosen = str(action or "excuse").strip().lower()
    if chosen not in {"excuse", "reassign"}:
        raise CleaningTaskError("Action must be excuse or reassign.", status=400)
    oid = int(organization_id)
    employee = int(employee_user_id)
    actor = int(actor_user_id)
    replacement = int(replacement_user_id or 0)
    assigned = _assigned_user_ids(assigned_user_ids)
    if chosen == "reassign":
        if replacement <= 0 or replacement == employee:
            raise CleaningTaskError("Choose a different employee already assigned to this activity.", status=400)
        if assigned and replacement not in assigned:
            raise CleaningTaskError(
                "Assign that employee on the Weekly Schedule before reassigning this activity.",
                status=400,
            )
    session_id = int(shared_session_id or 0)
    if session_id <= 0:
        if not assignment_group_id or not role:
            raise CleaningTaskError("This activity has no shared session to update.", status=400)
        group = get_activity_group(cursor, oid, role_code=str(role))
        session = ensure_shared_session(
            cursor,
            organization_id=oid,
            assignment_group_id=str(assignment_group_id),
            business_date=business_date,
            role=str(role),
            group_items=(group or {}).get("items") or [],
            assigned_user_ids=assigned,
        )
        session_id = int(session["id"])
    else:
        session = get_shared_session(cursor, oid, session_id)
        if not session:
            raise CleaningTaskError("Shared session not found.", status=404)
    open_row = open_participation_activity(cursor, oid, session_id, employee)
    if participation_timer_is_active(open_row):
        started = open_row.get("started_at") if open_row else None
        started_text = started.strftime("%Y-%m-%d %H:%M:%S") if hasattr(started, "strftime") else (str(started)[:19] if started else None)
        raise CleaningTaskError(
            "End this employee's active participation session before excusing them.",
            status=409,
            payload={
                "code": "active_timer",
                "activity_id": int(open_row["id"]) if open_row and open_row.get("id") is not None else None,
                "started_at": started_text,
            },
        )
    prior = [int(row.get("user_id") or 0) for row in _adjustment_rows(session)]
    at = eastern_now_naive()
    entry = {
        "action": chosen,
        "user_id": employee,
        "replacement_user_id": replacement or None,
        "reason": reason_clean,
        "actor_user_id": actor,
        "at": at.strftime("%Y-%m-%d %H:%M:%S"),
        "original_assigned_user_ids": assigned or prior,
    }
    rows = _adjustment_rows(session)
    rows.append(entry)
    cursor.execute(
        f"UPDATE {SESSIONS_TABLE} SET participation_adjustments_json=%s WHERE id=%s AND organization_id=%s",
        (json.dumps(rows), session_id, oid),
    )
    items = list_shared_session_items(cursor, oid, session_id)
    for item in items:
        if str(item.get("status") or "") == ITEM_COMPLETED:
            continue
        cursor.execute(
            f"""
            UPDATE {CHECKS_TABLE}
            SET status=%s
            WHERE organization_id=%s AND session_item_id=%s AND user_id=%s AND status=%s
            """,
            (ITEM_EXCUSED, oid, int(item["id"]), employee, ITEM_PENDING),
        )
        if chosen == "reassign" and replacement > 0 and normalize_acknowledgment_mode(item.get("acknowledgment_mode")) == ACK_EACH:
            existing = load_employee_checks(cursor, oid, [int(item["id"])]).get(int(item["id"])) or []
            have = {int(row.get("user_id") or 0) for row in existing}
            if replacement not in have:
                _insert_check(cursor, oid, int(item["id"]), replacement)
        refreshed = load_employee_checks(cursor, oid, [int(item["id"])]).get(int(item["id"])) or []
        if item_acknowledgments_satisfied([str(row.get("status") or "") for row in refreshed]):
            done = next(row for row in refreshed if str(row.get("status") or "") == ITEM_COMPLETED)
            cursor.execute(
                f"""
                UPDATE {SESSION_ITEMS_TABLE}
                SET status=%s, completed_at=%s, completed_by_user_id=%s
                WHERE id=%s AND status=%s
                """,
                (
                    ITEM_COMPLETED,
                    done.get("completed_at"),
                    int(done.get("user_id") or 0),
                    int(item["id"]),
                    ITEM_PENDING,
                ),
            )
    cursor.execute(
        f"""
        SELECT id FROM {TABLE}
        WHERE organization_id=%s AND shared_session_id=%s AND user_id=%s
        ORDER BY id DESC LIMIT 1
        """,
        (oid, session_id, employee),
    )
    host = cursor.fetchone()
    if not host:
        cursor.execute(
            f"""
            SELECT id FROM {TABLE}
            WHERE organization_id=%s AND shared_session_id=%s
            ORDER BY id ASC LIMIT 1
            """,
            (oid, session_id),
        )
        host = cursor.fetchone()
    if host and host.get("id"):
        _record_event(
            cursor,
            organization_id=oid,
            activity_id=int(host["id"]),
            event_type="participation_excused" if chosen == "excuse" else "participation_reassigned",
            actor_user_id=actor,
            payload=entry,
        )
    return {
        "ok": True,
        "shared_session_id": session_id,
        "excused_user_ids": excused_user_ids_for_session(cursor, oid, session_id),
        "adjustment": entry,
    }
