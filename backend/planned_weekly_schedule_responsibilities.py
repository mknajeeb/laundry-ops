"""Daily responsibilities on the planned weekly schedule (roles without time slots).

A responsibility is (week, day, employee, role, remarks) with no start/end time. It never
contributes scheduled hours, estimated cost, or attendance windows, and it can sit alongside
the employee's timed shift that day.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

from backend.planned_weekly_schedule import (
    DAY_LABELS,
    normalize_day_of_week,
    normalize_weekly_role,
)
from backend.ta_helpers import invalidate_schema_cache, table_exists

TABLE = "planned_weekly_schedule_responsibilities"


def ensure_responsibilities_table(cursor) -> None:
    if table_exists(cursor, TABLE):
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
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_pwsr_assignment (organization_id, week_start, user_id, day_of_week, role),
          INDEX idx_pwsr_org_week (organization_id, week_start)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    invalidate_schema_cache()


def serialize_responsibility(row: Mapping[str, Any]) -> dict[str, Any]:
    dow = int(row.get("day_of_week") or 0)
    return {
        "id": int(row.get("id") or 0),
        "organization_id": int(row.get("organization_id") or 0),
        "week_start": str(row.get("week_start") or ""),
        "user_id": int(row.get("user_id") or 0),
        "day_of_week": dow,
        "day_label": DAY_LABELS[dow % 7],
        "role": str(row.get("role") or ""),
        "remarks": (str(row.get("remarks")).strip() or None) if row.get("remarks") else None,
    }


def list_week_responsibilities(cursor, organization_id: int, *, week_start: date) -> list[dict[str, Any]]:
    ensure_responsibilities_table(cursor)
    cursor.execute(
        f"""
        SELECT id, organization_id, week_start, user_id, day_of_week, role, remarks
        FROM {TABLE}
        WHERE organization_id = %s AND week_start = %s
        ORDER BY day_of_week ASC, role ASC, user_id ASC, id ASC
        """,
        (int(organization_id), week_start),
    )
    return [serialize_responsibility(r) for r in (cursor.fetchall() or []) if isinstance(r, dict)]


def get_responsibility(cursor, organization_id: int, responsibility_id: int) -> dict[str, Any] | None:
    ensure_responsibilities_table(cursor)
    cursor.execute(
        f"""
        SELECT id, organization_id, week_start, user_id, day_of_week, role, remarks
        FROM {TABLE}
        WHERE organization_id = %s AND id = %s
        LIMIT 1
        """,
        (int(organization_id), int(responsibility_id)),
    )
    row = cursor.fetchone()
    return serialize_responsibility(row) if isinstance(row, dict) else None


def _duplicate_exists(
    cursor,
    organization_id: int,
    *,
    week_start: date,
    user_id: int,
    day_of_week: int,
    role: str,
    exclude_id: int | None = None,
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
    return exclude_id is None or found != int(exclude_id)


def _validate(
    conn,
    cursor,
    organization_id: int,
    data: Mapping[str, Any],
    *,
    existing: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    from backend.planned_weekly_schedule import (
        _assert_worker_in_org,
        _assert_worker_schedulable,
        _load_role_catalog_index,
    )
    from backend.weekly_schedule_roles import accept_remarks, normalize_remarks, role_assignment_error

    merged = {**(existing or {}), **dict(data or {})}
    try:
        uid = int(merged.get("user_id"))
    except (TypeError, ValueError):
        return None, "user_id is required"
    if uid <= 0:
        return None, "user_id is required"
    dow = normalize_day_of_week(merged.get("day_of_week"))
    if dow is None:
        return None, "day_of_week must be 0-6 (Sun-Sat)"
    role = normalize_weekly_role(merged.get("role"))
    if not role:
        return None, "role is required"
    catalog = _load_role_catalog_index(cursor, organization_id)
    unchanged_role = bool(existing) and existing.get("role") == role  # type: ignore[union-attr]
    err = role_assignment_error(role, catalog, timed=False, already_assigned=unchanged_role)
    if err:
        return None, err
    worker_err = _assert_worker_in_org(conn, organization_id, uid)
    if worker_err:
        return None, worker_err
    if not existing or int(existing.get("user_id") or 0) != uid:
        schedulable_err = _assert_worker_schedulable(conn, organization_id, uid)
        if schedulable_err:
            return None, schedulable_err
    prior_remarks = {str(existing["remarks"])} if existing and existing.get("remarks") else None
    remarks = accept_remarks(
        role,
        normalize_remarks(merged.get("remarks")),
        catalog,
        existing=prior_remarks if unchanged_role else None,
    )
    return {"user_id": uid, "day_of_week": dow, "role": role, "remarks": remarks}, None


def create_responsibility(
    conn,
    cursor,
    organization_id: int,
    *,
    week_start: date,
    data: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    ensure_responsibilities_table(cursor)
    payload, err = _validate(conn, cursor, organization_id, data)
    if err or payload is None:
        return None, err
    if _duplicate_exists(cursor, organization_id, week_start=week_start, **payload_key(payload)):
        return None, "this employee already has that responsibility on this day"
    cursor.execute(
        f"""
        INSERT INTO {TABLE} (organization_id, week_start, user_id, day_of_week, role, remarks)
        VALUES (%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            week_start,
            payload["user_id"],
            payload["day_of_week"],
            payload["role"],
            payload["remarks"],
        ),
    )
    return get_responsibility(cursor, organization_id, int(cursor.lastrowid or 0)), None


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
    payload, err = _validate(conn, cursor, organization_id, data, existing=existing)
    if err or payload is None:
        return None, err
    week_start = date.fromisoformat(str(existing["week_start"])[:10])
    if _duplicate_exists(
        cursor,
        organization_id,
        week_start=week_start,
        exclude_id=responsibility_id,
        **payload_key(payload),
    ):
        return None, "this employee already has that responsibility on this day"
    cursor.execute(
        f"""
        UPDATE {TABLE}
        SET user_id=%s, day_of_week=%s, role=%s, remarks=%s
        WHERE organization_id=%s AND id=%s
        """,
        (
            payload["user_id"],
            payload["day_of_week"],
            payload["role"],
            payload["remarks"],
            int(organization_id),
            int(responsibility_id),
        ),
    )
    return get_responsibility(cursor, organization_id, responsibility_id), None


def sync_day_tasks(
    cursor,
    organization_id: int,
    *,
    week_start: date,
    user_id: int,
    day_of_week: int,
    tasks: Any,
) -> tuple[dict[str, int] | None, str | None]:
    """Make the employee's tasks for one day exactly ``tasks`` ([{role, remarks}]).

    Used by the shift dialog. Only the tasks table changes, so shifts, breaks, and hours are untouched.
    Unchanged tasks keep their row; a role listed twice is rejected instead of duplicated.
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
    wanted: dict[str, str | None] = {}
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
        wanted[role] = accept_remarks(
            role, normalize_remarks(raw.get("remarks")), catalog, existing={prior} if prior else None
        )
    counts = {"added": 0, "updated": 0, "removed": 0}
    for role, item in current.items():
        if role not in wanted:
            delete_responsibility(cursor, oid, item["id"])
            counts["removed"] += 1
    for role, remarks in wanted.items():
        if role not in current:
            cursor.execute(
                f"""
                INSERT INTO {TABLE} (organization_id, week_start, user_id, day_of_week, role, remarks)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE remarks = VALUES(remarks)
                """,
                (oid, week_start, uid, dow, role, remarks),
            )
            counts["added"] += 1
        elif (current[role].get("remarks") or None) != remarks:
            cursor.execute(
                f"UPDATE {TABLE} SET remarks = %s WHERE organization_id = %s AND id = %s",
                (remarks, oid, current[role]["id"]),
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
) -> list[tuple[int, int, str, str | None]]:
    rows: list[tuple[int, int, str, str | None]] = []
    seen: set[tuple[int, int, str]] = set()

    def _add(uid: int, dow: int, role: str, remarks: str | None) -> None:
        key = (uid, dow, role)
        if key in seen:
            return
        seen.add(key)
        rows.append((uid, dow, role, remarks))

    for item in source:
        if item["user_id"] in valid_user_ids:
            _add(item["user_id"], item["day_of_week"], item["role"], item.get("remarks"))
    if seed_sunday_from_saturday:
        for item in source:
            if item["day_of_week"] == 6 and item["user_id"] in valid_user_ids:
                _add(item["user_id"], 0, item["role"], item.get("remarks"))
    return rows


def insert_responsibility_rows(
    cursor,
    organization_id: int,
    *,
    week_start: date,
    rows: Sequence[tuple[int, int, str, str | None]],
) -> int:
    if not rows:
        return 0
    ensure_responsibilities_table(cursor)
    cursor.executemany(
        f"""
        INSERT IGNORE INTO {TABLE} (organization_id, week_start, user_id, day_of_week, role, remarks)
        VALUES (%s,%s,%s,%s,%s,%s)
        """,
        [(int(organization_id), week_start, uid, dow, role, remarks) for uid, dow, role, remarks in rows],
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
