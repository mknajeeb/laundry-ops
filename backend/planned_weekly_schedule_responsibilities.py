"""Daily responsibilities on the planned weekly schedule (tasks, not shift roles).

A responsibility is one employee's membership in a task assignment for a week and day.
Several employees can share one assignment (``assignment_group_id``). Timing is stored
on that assignment and, for relative options, stays linked to each employee's current
shift and scheduled break. Tasks never contribute scheduled hours, estimated cost, or
attendance windows, and they can sit alongside the employee's timed shift that day.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Mapping, Sequence

from backend.planned_weekly_schedule import (
    DAY_LABELS,
    normalize_day_of_week,
    normalize_weekly_role,
)
from backend.planned_weekly_schedule_task_timing import (
    TIMING_ANYTIME,
    evaluate_task_timing,
    normalize_timing,
    timing_display,
)
from backend.ta_helpers import invalidate_schema_cache, table_exists

TABLE = "planned_weekly_schedule_responsibilities"
_COLUMNS = (
    "id, organization_id, week_start, user_id, day_of_week, role, remarks, "
    "assignment_group_id, timing_mode, start_time"
)

_GROUP_COLUMNS = (
    ("assignment_group_id", "VARCHAR(36) NULL DEFAULT NULL"),
    ("timing_mode", "VARCHAR(20) NOT NULL DEFAULT 'anytime'"),
    ("start_time", "TIME NULL DEFAULT NULL"),
)


def _column_present(cursor, column: str) -> bool:
    cursor.execute(f"SHOW COLUMNS FROM {TABLE} LIKE %s", (column,))
    row = cursor.fetchone()
    if not row:
        return False
    field = row.get("Field") if isinstance(row, dict) else row[0]
    return str(field or "").lower() == column.lower()


def _ensure_task_group_columns(cursor) -> None:
    for column, ddl in _GROUP_COLUMNS:
        try:
            if _column_present(cursor, column):
                continue
            cursor.execute(f"ALTER TABLE {TABLE} ADD COLUMN {column} {ddl}")
        except Exception:
            return


def ensure_responsibilities_table(cursor) -> None:
    if table_exists(cursor, TABLE):
        _ensure_task_group_columns(cursor)
        return
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          week_start DATE NOT NULL,
          user_id INT NOT NULL,
          day_of_week TINYINT NOT NULL,
          role VARCHAR(40) NOT NULL,
          remarks VARCHAR(255) NULL DEFAULT NULL,
          assignment_group_id VARCHAR(36) NULL DEFAULT NULL,
          timing_mode VARCHAR(20) NOT NULL DEFAULT 'anytime',
          start_time TIME NULL DEFAULT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_pwsr_assignment (organization_id, week_start, user_id, day_of_week, role),
          INDEX idx_pwsr_org_week (organization_id, week_start),
          INDEX idx_pwsr_group (organization_id, week_start, assignment_group_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    invalidate_schema_cache()


def serialize_responsibility(row: Mapping[str, Any]) -> dict[str, Any]:
    dow = int(row.get("day_of_week") or 0)
    mode = str(row.get("timing_mode") or TIMING_ANYTIME)
    start = None
    if mode == "specific_time" and row.get("start_time"):
        from backend.planned_weekly_schedule import _time_to_str

        start = _time_to_str(row.get("start_time"))
    group_id = str(row.get("assignment_group_id") or "").strip() or None
    user_id = int(row.get("user_id") or 0)
    return {
        "id": int(row.get("id") or 0),
        "organization_id": int(row.get("organization_id") or 0),
        "week_start": str(row.get("week_start") or ""),
        "user_id": user_id,
        "user_ids": [user_id] if user_id else [],
        "day_of_week": dow,
        "day_label": DAY_LABELS[dow % 7],
        "role": str(row.get("role") or ""),
        "remarks": (str(row.get("remarks")).strip() or None) if row.get("remarks") else None,
        "assignment_group_id": group_id,
        "timing_mode": mode,
        "start_time": start,
        "timing_label": timing_display(mode, start),
        "members": [{"id": int(row.get("id") or 0), "user_id": user_id}] if user_id else [],
    }


def assignment_key(item: Mapping[str, Any]) -> str:
    group_id = str(item.get("assignment_group_id") or "").strip()
    if group_id:
        return f"g:{item.get('week_start')}:{item.get('day_of_week')}:{group_id}"
    return f"solo:{item.get('id')}"


def annotate_assignment_members(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Each member row lists every employee on the same assignment."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    out = [dict(item) for item in items or []]
    for item in out:
        grouped.setdefault(assignment_key(item), []).append(item)
    for members in grouped.values():
        user_ids = [int(member["user_id"]) for member in members]
        member_rows = [{"id": int(member["id"]), "user_id": int(member["user_id"])} for member in members]
        for member in members:
            member["user_ids"] = user_ids
            member["members"] = member_rows
    return out


def _fetch_week_rows(cursor, organization_id: int, week_start: date) -> list[dict[str, Any]]:
    ensure_responsibilities_table(cursor)
    cursor.execute(
        f"""
        SELECT {_COLUMNS}
        FROM {TABLE}
        WHERE organization_id = %s AND week_start = %s
        ORDER BY day_of_week ASC, role ASC, user_id ASC, id ASC
        """,
        (int(organization_id), week_start),
    )
    return [serialize_responsibility(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def list_week_responsibilities(cursor, organization_id: int, *, week_start: date) -> list[dict[str, Any]]:
    return annotate_assignment_members(_fetch_week_rows(cursor, organization_id, week_start))


def get_responsibility(cursor, organization_id: int, responsibility_id: int) -> dict[str, Any] | None:
    ensure_responsibilities_table(cursor)
    cursor.execute(
        f"""
        SELECT {_COLUMNS}
        FROM {TABLE}
        WHERE organization_id = %s AND id = %s
        LIMIT 1
        """,
        (int(organization_id), int(responsibility_id)),
    )
    row = cursor.fetchone()
    if not isinstance(row, dict):
        return None
    item = serialize_responsibility(row)
    week_start = date.fromisoformat(str(item["week_start"])[:10])
    members = [
        member
        for member in annotate_assignment_members(_fetch_week_rows(cursor, organization_id, week_start))
        if assignment_key(member) == assignment_key(item)
    ]
    match = next((member for member in members if int(member["id"]) == int(item["id"])), None)
    return match or item


def _duplicate_exists(
    cursor,
    organization_id: int,
    *,
    week_start: date,
    user_id: int,
    day_of_week: int,
    role: str,
    exclude_ids: set[int] | None = None,
) -> bool:
    cursor.execute(
        f"""
        SELECT id FROM {TABLE}
        WHERE organization_id = %s AND week_start = %s AND user_id = %s
          AND day_of_week = %s AND role = %s
        LIMIT 1
        """,
        (int(organization_id), week_start, int(user_id), int(day_of_week), role),
    )
    row = cursor.fetchone()
    if not row:
        return False
    found = int(row.get("id") if isinstance(row, dict) else row[0])
    return found not in (exclude_ids or set())


def _parse_user_ids(data: Mapping[str, Any], *, fallback: Sequence[int] | None = None) -> tuple[list[int] | None, str | None]:
    if "user_ids" in data and data.get("user_ids") is not None:
        raw = data.get("user_ids")
        if not isinstance(raw, (list, tuple)) or not raw:
            return None, "choose at least one employee"
        ids: list[int] = []
        for item in raw:
            try:
                uid = int(item)
            except (TypeError, ValueError):
                return None, "user_ids must be employee ids"
            if uid > 0 and uid not in ids:
                ids.append(uid)
        if not ids:
            return None, "choose at least one employee"
        return ids, None
    if data.get("user_id") not in (None, ""):
        try:
            uid = int(data.get("user_id"))
        except (TypeError, ValueError):
            return None, "user_id is required"
        if uid <= 0:
            return None, "user_id is required"
        return [uid], None
    if fallback:
        return [int(uid) for uid in fallback], None
    return None, "user_id is required"


def _worker_names(conn, organization_id: int, user_ids: Sequence[int]) -> dict[int, str]:
    from backend.planned_weekly_schedule import _load_workers

    try:
        workers = _load_workers(conn, organization_id) if conn is not None else []
    except Exception:
        workers = []
    named = {
        int(worker.get("user_id") or 0): str(worker.get("display_name") or worker.get("worker_name") or "").strip()
        for worker in workers or []
    }
    return {int(uid): named.get(int(uid)) or f"User #{int(uid)}" for uid in user_ids}


def _day_shifts(cursor, organization_id: int, week_start: date, day_of_week: int, user_ids: Sequence[int]) -> dict[int, list[dict[str, Any]]]:
    from backend.planned_weekly_schedule import _time_to_str, parse_break_slots_storage

    wanted = {int(uid) for uid in user_ids}
    cursor.execute(
        """
        SELECT user_id, day_of_week, start_time, end_time, break_minutes, break_slots
        FROM planned_weekly_schedule_entries
        WHERE organization_id = %s AND week_start = %s
        """,
        (int(organization_id), week_start),
    )
    grouped: dict[int, list[dict[str, Any]]] = {uid: [] for uid in wanted}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict) or int(row.get("day_of_week") or -1) != int(day_of_week):
            continue
        uid = int(row.get("user_id") or 0)
        if uid not in wanted:
            continue
        slots = parse_break_slots_storage(row.get("break_slots"))
        try:
            break_minutes = int(row.get("break_minutes") or 0)
        except (TypeError, ValueError):
            break_minutes = 0
        timed = sum(
            max(0, _hhmm_minutes(slot.get("end_time")) - _hhmm_minutes(slot.get("start_time")))
            for slot in slots
            if _hhmm_minutes(slot.get("start_time")) is not None and _hhmm_minutes(slot.get("end_time")) is not None
        )
        grouped[uid].append(
            {
                "start_time": _time_to_str(row.get("start_time")) or "",
                "end_time": _time_to_str(row.get("end_time")) or "",
                "break_slots": slots,
                "unscheduled_break_minutes": max(0, break_minutes - timed),
            }
        )
    return grouped


def _hhmm_minutes(value: Any) -> int | None:
    text = str(value or "")[:5]
    if len(text) < 4 or ":" not in text:
        return None
    try:
        hour, minute = int(text[:2]), int(text[3:5])
    except (TypeError, ValueError):
        return None
    return hour * 60 + minute


def _timing_for_members(
    conn,
    cursor,
    organization_id: int,
    *,
    week_start: date,
    day_of_week: int,
    user_ids: Sequence[int],
    timing: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    names = _worker_names(conn, organization_id, user_ids)
    shifts = _day_shifts(cursor, organization_id, week_start, day_of_week, user_ids)
    return evaluate_task_timing(
        timing_mode=str(timing.get("timing_mode") or TIMING_ANYTIME),
        start_time=timing.get("start_time"),
        members=[{"name": names[int(uid)], "shifts": shifts.get(int(uid)) or []} for uid in user_ids],
    )


def _validate_assignment(
    conn,
    cursor,
    organization_id: int,
    data: Mapping[str, Any],
    *,
    existing: Mapping[str, Any] | None = None,
    existing_user_ids: Sequence[int] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    from backend.planned_weekly_schedule import (
        _assert_worker_in_org,
        _assert_worker_schedulable,
        _load_role_catalog_index,
    )
    from backend.weekly_schedule_roles import accept_remarks, normalize_remarks, role_assignment_error

    merged = {**(existing or {}), **dict(data or {})}
    user_ids, err = _parse_user_ids(data, fallback=existing_user_ids or ([int(existing["user_id"])] if existing else None))
    if err or not user_ids:
        return None, err or "user_id is required"
    dow = normalize_day_of_week(merged.get("day_of_week"))
    if dow is None:
        return None, "day_of_week must be 0-6 (Sun-Sat)"
    role = normalize_weekly_role(merged.get("role"))
    if not role:
        return None, "role is required"
    catalog = _load_role_catalog_index(cursor, organization_id)
    unchanged_role = bool(existing) and existing.get("role") == role
    role_err = role_assignment_error(role, catalog, timed=False, already_assigned=unchanged_role)
    if role_err:
        return None, role_err
    kept = {int(uid) for uid in (existing_user_ids or [])}
    names = _worker_names(conn, organization_id, user_ids)
    for uid in user_ids:
        worker_err = _assert_worker_in_org(conn, organization_id, uid)
        if worker_err:
            return None, worker_err
        if uid not in kept:
            schedulable_err = _assert_worker_schedulable(conn, organization_id, uid)
            if schedulable_err:
                return None, f"{names[uid]}: {schedulable_err}"
    prior_remarks = {str(existing["remarks"])} if existing and existing.get("remarks") else None
    remarks = accept_remarks(
        role,
        normalize_remarks(merged.get("remarks")),
        catalog,
        existing=prior_remarks if unchanged_role else None,
    )
    timing, timing_err = normalize_timing(
        data.get("timing_mode", existing.get("timing_mode") if existing else TIMING_ANYTIME),
        data.get("start_time", existing.get("start_time") if existing else None),
        default_mode=str(existing.get("timing_mode") or TIMING_ANYTIME) if existing else TIMING_ANYTIME,
    )
    if timing_err or timing is None:
        return None, timing_err
    return {
        "user_ids": user_ids,
        "day_of_week": dow,
        "role": role,
        "remarks": remarks,
        **timing,
    }, None


def _insert_member(
    cursor,
    organization_id: int,
    *,
    week_start: date,
    user_id: int,
    day_of_week: int,
    role: str,
    remarks: str | None,
    assignment_group_id: str,
    timing_mode: str,
    start_time: str | None,
) -> int:
    cursor.execute(
        f"""
        INSERT INTO {TABLE} (
          organization_id, week_start, user_id, day_of_week, role, remarks,
          assignment_group_id, timing_mode, start_time
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            week_start,
            int(user_id),
            int(day_of_week),
            role,
            remarks,
            assignment_group_id,
            timing_mode,
            start_time,
        ),
    )
    return int(cursor.lastrowid or 0)


def _update_member_row(
    cursor,
    organization_id: int,
    responsibility_id: int,
    *,
    user_id: int,
    day_of_week: int,
    role: str,
    remarks: str | None,
    assignment_group_id: str | None,
    timing_mode: str,
    start_time: str | None,
) -> None:
    cursor.execute(
        f"""
        UPDATE {TABLE}
        SET user_id=%s, day_of_week=%s, role=%s, remarks=%s,
            assignment_group_id=%s, timing_mode=%s, start_time=%s
        WHERE organization_id=%s AND id=%s
        """,
        (
            int(user_id),
            int(day_of_week),
            role,
            remarks,
            assignment_group_id,
            timing_mode,
            start_time,
            int(organization_id),
            int(responsibility_id),
        ),
    )


def _with_warnings(item: dict[str, Any] | None, warnings: Sequence[str]) -> dict[str, Any] | None:
    if item is None:
        return None
    item = dict(item)
    item["timing_warnings"] = list(warnings)
    return item


def create_responsibility(
    conn,
    cursor,
    organization_id: int,
    *,
    week_start: date,
    data: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    ensure_responsibilities_table(cursor)
    payload, err = _validate_assignment(conn, cursor, organization_id, data)
    if err or payload is None:
        return None, err
    names = _worker_names(conn, organization_id, payload["user_ids"])
    for uid in payload["user_ids"]:
        if _duplicate_exists(
            cursor,
            organization_id,
            week_start=week_start,
            user_id=uid,
            day_of_week=payload["day_of_week"],
            role=payload["role"],
        ):
            return None, f"{names[uid]} already has that task on this day"
    errors, warnings = _timing_for_members(
        conn,
        cursor,
        organization_id,
        week_start=week_start,
        day_of_week=payload["day_of_week"],
        user_ids=payload["user_ids"],
        timing=payload,
    )
    if errors:
        return None, "; ".join(errors)
    group_id = uuid.uuid4().hex
    first_id = None
    for uid in payload["user_ids"]:
        rid = _insert_member(
            cursor,
            organization_id,
            week_start=week_start,
            user_id=uid,
            day_of_week=payload["day_of_week"],
            role=payload["role"],
            remarks=payload["remarks"],
            assignment_group_id=group_id,
            timing_mode=payload["timing_mode"],
            start_time=payload["start_time"],
        )
        if first_id is None:
            first_id = rid
    return _with_warnings(get_responsibility(cursor, organization_id, int(first_id or 0)), warnings), None


def payload_key(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "user_id": payload["user_id"],
        "day_of_week": payload["day_of_week"],
        "role": payload["role"],
    }


def update_responsibility(
    conn,
    cursor,
    organization_id: int,
    responsibility_id: int,
    data: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    existing = get_responsibility(cursor, organization_id, responsibility_id)
    if not existing:
        return None, "responsibility not found"
    member_rows = list(existing.get("members") or [{"id": existing["id"], "user_id": existing["user_id"]}])
    existing_ids = {int(member["id"]) for member in member_rows}
    existing_users = [int(member["user_id"]) for member in member_rows]
    payload, err = _validate_assignment(
        conn,
        cursor,
        organization_id,
        data,
        existing=existing,
        existing_user_ids=existing_users,
    )
    if err or payload is None:
        return None, err
    week_start = date.fromisoformat(str(existing["week_start"])[:10])
    names = _worker_names(conn, organization_id, payload["user_ids"])
    for uid in payload["user_ids"]:
        if _duplicate_exists(
            cursor,
            organization_id,
            week_start=week_start,
            user_id=uid,
            day_of_week=payload["day_of_week"],
            role=payload["role"],
            exclude_ids=existing_ids,
        ):
            return None, f"{names[uid]} already has that task on this day"
    errors, warnings = _timing_for_members(
        conn,
        cursor,
        organization_id,
        week_start=week_start,
        day_of_week=payload["day_of_week"],
        user_ids=payload["user_ids"],
        timing=payload,
    )
    if errors:
        return None, "; ".join(errors)
    group_id = str(existing.get("assignment_group_id") or "").strip() or uuid.uuid4().hex
    by_user = {int(member["user_id"]): int(member["id"]) for member in member_rows}
    kept_id = None
    for uid in payload["user_ids"]:
        if uid in by_user:
            _update_member_row(
                cursor,
                organization_id,
                by_user[uid],
                user_id=uid,
                day_of_week=payload["day_of_week"],
                role=payload["role"],
                remarks=payload["remarks"],
                assignment_group_id=group_id,
                timing_mode=payload["timing_mode"],
                start_time=payload["start_time"],
            )
            if kept_id is None:
                kept_id = by_user[uid]
        else:
            rid = _insert_member(
                cursor,
                organization_id,
                week_start=week_start,
                user_id=uid,
                day_of_week=payload["day_of_week"],
                role=payload["role"],
                remarks=payload["remarks"],
                assignment_group_id=group_id,
                timing_mode=payload["timing_mode"],
                start_time=payload["start_time"],
            )
            if kept_id is None:
                kept_id = rid
    for uid, rid in by_user.items():
        if uid not in payload["user_ids"]:
            delete_responsibility(cursor, organization_id, rid)
    return _with_warnings(get_responsibility(cursor, organization_id, int(kept_id or responsibility_id)), warnings), None


def sync_day_tasks(
    cursor,
    organization_id: int,
    *,
    week_start: date,
    user_id: int,
    day_of_week: int,
    tasks: Any,
    conn=None,
) -> tuple[dict[str, int] | None, str | None]:
    """Make the employee's tasks for one day exactly ``tasks``.

    Used by the shift dialog. Only this employee's membership changes, so shifts, breaks,
    hours, and the other people on a shared task stay as they are. A role listed twice is rejected.
    """
    from backend.planned_weekly_schedule import _load_role_catalog_index
    from backend.weekly_schedule_roles import accept_remarks, normalize_remarks, role_assignment_error

    if not isinstance(tasks, list):
        return None, "tasks must be a list"
    ensure_responsibilities_table(cursor)
    oid, uid, dow = int(organization_id), int(user_id), int(day_of_week)
    catalog = _load_role_catalog_index(cursor, oid)
    current = {
        item["role"]: item
        for item in list_week_responsibilities(cursor, oid, week_start=week_start)
        if item["user_id"] == uid and item["day_of_week"] == dow
    }
    wanted: dict[str, dict[str, Any]] = {}
    for raw in tasks:
        if not isinstance(raw, Mapping):
            return None, "each task must be an object"
        role = normalize_weekly_role(raw.get("role"))
        if not role:
            return None, f"unknown task: {raw.get('role')}"
        label = (catalog.get(role) or {}).get("name") or role
        if role in wanted:
            return None, f"{label} is listed more than once"
        err = role_assignment_error(role, catalog, timed=False, already_assigned=role in current)
        if err:
            return None, err
        prior = current.get(role, {}).get("remarks")
        remarks = accept_remarks(
            role, normalize_remarks(raw.get("remarks")), catalog, existing={prior} if prior else None
        )
        existing = current.get(role) or {}
        if "timing_mode" in raw or "start_time" in raw:
            timing, timing_err = normalize_timing(raw.get("timing_mode"), raw.get("start_time"))
            if timing_err or timing is None:
                return None, timing_err
        else:
            timing = {
                "timing_mode": existing.get("timing_mode") or TIMING_ANYTIME,
                "start_time": existing.get("start_time"),
            }
        member_ids = [int(uid) for uid in (existing.get("user_ids") or [uid])]
        errors, _warnings = _timing_for_members(
            conn,
            cursor,
            oid,
            week_start=week_start,
            day_of_week=dow,
            user_ids=member_ids,
            timing=timing,
        )
        if errors:
            return None, "; ".join(errors)
        wanted[role] = {"remarks": remarks, **timing, "members": list(existing.get("members") or [])}
    counts = {"added": 0, "updated": 0, "removed": 0}
    for role, item in current.items():
        if role not in wanted:
            delete_responsibility(cursor, oid, item["id"])
            counts["removed"] += 1
    for role, spec in wanted.items():
        if role not in current:
            _insert_member(
                cursor,
                oid,
                week_start=week_start,
                user_id=uid,
                day_of_week=dow,
                role=role,
                remarks=spec["remarks"],
                assignment_group_id=uuid.uuid4().hex,
                timing_mode=spec["timing_mode"],
                start_time=spec["start_time"],
            )
            counts["added"] += 1
            continue
        existing = current[role]
        changed = (existing.get("remarks") or None) != spec["remarks"] or (
            existing.get("timing_mode") or TIMING_ANYTIME
        ) != spec["timing_mode"] or (existing.get("start_time") or None) != spec["start_time"]
        if not changed:
            continue
        member_rows = spec["members"] or [{"id": existing["id"], "user_id": existing["user_id"]}]
        group_id = existing.get("assignment_group_id") or uuid.uuid4().hex
        for member in member_rows:
            _update_member_row(
                cursor,
                oid,
                int(member["id"]),
                user_id=int(member["user_id"]),
                day_of_week=dow,
                role=role,
                remarks=spec["remarks"],
                assignment_group_id=group_id,
                timing_mode=spec["timing_mode"],
                start_time=spec["start_time"],
            )
        counts["updated"] += 1
    return counts, None


def delete_responsibility(cursor, organization_id: int, responsibility_id: int) -> bool:
    ensure_responsibilities_table(cursor)
    cursor.execute(
        f"DELETE FROM {TABLE} WHERE organization_id = %s AND id = %s",
        (int(organization_id), int(responsibility_id)),
    )
    return bool(cursor.rowcount)


def delete_assignment(cursor, organization_id: int, responsibility_id: int) -> bool:
    """Remove every employee on the assignment that ``responsibility_id`` belongs to."""
    existing = get_responsibility(cursor, organization_id, responsibility_id)
    if not existing:
        return False
    ids = [int(member["id"]) for member in (existing.get("members") or [{"id": responsibility_id}])]
    removed = False
    for rid in ids:
        removed = delete_responsibility(cursor, organization_id, rid) or removed
    return removed


def clear_week_responsibilities(cursor, organization_id: int, *, week_start: date) -> int:
    ensure_responsibilities_table(cursor)
    cursor.execute(
        f"DELETE FROM {TABLE} WHERE organization_id = %s AND week_start = %s",
        (int(organization_id), week_start),
    )
    return int(cursor.rowcount or 0)


def clear_future_responsibilities_for_user(
    cursor,
    organization_id: int,
    user_id: int,
    *,
    current_week: date,
    from_day_of_week: int | None,
) -> int:
    """Mirror of the planned-entry purge: future weeks plus remaining days of the current week."""
    ensure_responsibilities_table(cursor)
    oid, uid = int(organization_id), int(user_id)
    cursor.execute(
        f"DELETE FROM {TABLE} WHERE organization_id = %s AND user_id = %s AND week_start > %s",
        (oid, uid, current_week),
    )
    deleted = int(getattr(cursor, "rowcount", 0) or 0)
    if from_day_of_week is not None:
        cursor.execute(
            f"""
            DELETE FROM {TABLE}
            WHERE organization_id = %s AND user_id = %s AND week_start = %s AND day_of_week >= %s
            """,
            (oid, uid, current_week, int(from_day_of_week)),
        )
        deleted += int(getattr(cursor, "rowcount", 0) or 0)
    return deleted


def copy_week_responsibilities(
    cursor,
    organization_id: int,
    *,
    source_week_start: date,
    target_week_start: date,
    valid_user_ids: set[int],
    seed_sunday_from_saturday: bool,
) -> int:
    """Copy responsibilities into the target week (same Sat→Sun seeding rule as planned entries)."""
    source = list_week_responsibilities(cursor, organization_id, week_start=source_week_start)
    rows = responsibility_copy_rows(
        source,
        valid_user_ids=valid_user_ids,
        seed_sunday_from_saturday=seed_sunday_from_saturday
        and not any(item["day_of_week"] == 0 for item in source),
    )
    return insert_responsibility_rows(cursor, organization_id, week_start=target_week_start, rows=rows)


def responsibility_copy_rows(
    source: Sequence[Mapping[str, Any]],
    *,
    valid_user_ids: set[int],
    seed_sunday_from_saturday: bool,
) -> list[tuple[Any, ...]]:
    """Rows are ``(user_id, day, role, remarks, group_id, timing_mode, start_time)``.

    Saturday copied onto an empty Sunday gets new group ids so the two days stay
    separate assignments.
    """
    rows: list[tuple[Any, ...]] = []
    seen: set[tuple[int, int, str]] = set()
    sunday_groups: dict[str, str] = {}

    def _add(uid: int, dow: int, item: Mapping[str, Any], group_id: str | None) -> None:
        key = (uid, dow, str(item.get("role") or ""))
        if key in seen:
            return
        seen.add(key)
        rows.append(
            (
                uid,
                dow,
                item.get("role"),
                item.get("remarks"),
                group_id,
                item.get("timing_mode") or TIMING_ANYTIME,
                item.get("start_time"),
            )
        )

    def _sunday_group(item: Mapping[str, Any]) -> str | None:
        source_group = str(item.get("assignment_group_id") or "").strip()
        if not source_group:
            return None
        if source_group not in sunday_groups:
            sunday_groups[source_group] = uuid.uuid4().hex
        return sunday_groups[source_group]

    for item in source:
        if item["user_id"] in valid_user_ids:
            _add(item["user_id"], item["day_of_week"], item, item.get("assignment_group_id"))
    if seed_sunday_from_saturday:
        for item in source:
            if item["day_of_week"] == 6 and item["user_id"] in valid_user_ids:
                _add(item["user_id"], 0, item, _sunday_group(item))
    return rows


def insert_responsibility_rows(
    cursor,
    organization_id: int,
    *,
    week_start: date,
    rows: Sequence[Sequence[Any]],
) -> int:
    if not rows:
        return 0
    ensure_responsibilities_table(cursor)
    payload = []
    for row in rows:
        uid, dow, role, remarks = row[0], row[1], row[2], row[3]
        group_id = row[4] if len(row) > 4 else None
        timing_mode = row[5] if len(row) > 5 else TIMING_ANYTIME
        start_time = row[6] if len(row) > 6 else None
        payload.append(
            (int(organization_id), week_start, uid, dow, role, remarks, group_id, timing_mode or TIMING_ANYTIME, start_time)
        )
    cursor.executemany(
        f"""
        INSERT IGNORE INTO {TABLE} (
          organization_id, week_start, user_id, day_of_week, role, remarks,
          assignment_group_id, timing_mode, start_time
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        payload,
    )
    return len(rows)


def _clock_label(value: Any) -> str:
    text = str(value or "")[:5]
    try:
        hour, minute = int(text[:2]), int(text[3:5])
    except ValueError:
        return text
    suffix = "AM" if hour < 12 else "PM"
    return f"{hour % 12 or 12}:{minute:02d} {suffix}"


def migrate_timed_tasks_to_responsibilities(
    cursor,
    organization_id: int,
    *,
    task_roles: set[str],
    from_week: date | None = None,
) -> dict[str, Any]:
    """Move ``task_roles`` off timed shifts into day tasks, keeping the old times in the instructions.

    Shifts are never deleted: they keep their times, break, and hours, plus any remaining roles
    (a shift may be left with no production role). Safe to re-run: converted shifts no longer hold
    the task role, and an existing task's instructions are never overwritten.
    """
    from backend.planned_weekly_schedule import (
        entry_role_assignments,
        ensure_planned_weekly_schedule_table,
        role_assignments_storage,
        roles_to_storage,
        serialize_entry,
    )
    from backend.weekly_schedule_roles import normalize_remarks

    ensure_planned_weekly_schedule_table(cursor)
    ensure_responsibilities_table(cursor)
    oid = int(organization_id)
    cursor.execute(
        """
        SELECT id, organization_id, week_start, user_id, day_of_week,
               role, start_time, end_time, break_minutes, employer_affiliation, role_assignments
        FROM planned_weekly_schedule_entries
        WHERE organization_id = %s AND week_start >= %s
        """,
        (oid, from_week or date(1970, 1, 1)),
    )
    moved: list[dict[str, Any]] = []
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        entry = serialize_entry(row)
        assignments = entry_role_assignments(entry)
        tasks = [a for a in assignments if a.get("role") in task_roles]
        if not tasks:
            continue
        keep = [a for a in assignments if a.get("role") not in task_roles]
        week_start = row["week_start"]
        for a in tasks:
            start = a.get("start_time") or entry.get("start_time")
            end = a.get("end_time") or entry.get("end_time")
            note = f"Previously scheduled {_clock_label(start)} – {_clock_label(end)}"
            remarks = normalize_remarks(" · ".join(p for p in (a.get("remarks"), note) if p))
            cursor.execute(
                f"""
                INSERT INTO {TABLE} (organization_id, week_start, user_id, day_of_week, role, remarks)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE remarks = COALESCE(remarks, VALUES(remarks))
                """,
                (oid, week_start, int(row["user_id"]), int(row["day_of_week"]), a["role"], remarks),
            )
            moved.append(
                {
                    "entry_id": int(row["id"]),
                    "week_start": str(week_start),
                    "user_id": int(row["user_id"]),
                    "day_of_week": int(row["day_of_week"]),
                    "role": a["role"],
                    "remarks": remarks,
                    "shift_kept_without_role": not keep,
                }
            )
        cursor.execute(
            """
            UPDATE planned_weekly_schedule_entries
            SET role = %s, role_assignments = %s
            WHERE organization_id = %s AND id = %s
            """,
            (
                roles_to_storage([a["role"] for a in keep]) if keep else "",
                role_assignments_storage(keep) if keep else None,
                oid,
                int(row["id"]),
            ),
        )
    return {"moved": moved}


def filter_responsibilities_for_view(
    items: Sequence[Mapping[str, Any]],
    *,
    allowed_user_ids: set[int] | None = None,
    hidden_roles: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    hidden = {str(r).strip().lower() for r in (hidden_roles or [])}
    out = []
    for item in items or []:
        if allowed_user_ids is not None and int(item.get("user_id") or 0) not in allowed_user_ids:
            continue
        if str(item.get("role") or "") in hidden:
            continue
        out.append(dict(item))
    return out
