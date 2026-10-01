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
    if seed_sunday_from_saturday and not any(item["day_of_week"] == 0 for item in source):
        for item in source:
            if item["day_of_week"] == 6 and item["user_id"] in valid_user_ids:
                _add(item["user_id"], 0, item["role"], item.get("remarks"))
    if not rows:
        return 0
    cursor.executemany(
        f"""
        INSERT IGNORE INTO {TABLE} (organization_id, week_start, user_id, day_of_week, role, remarks)
        VALUES (%s,%s,%s,%s,%s,%s)
        """,
        [(int(organization_id), target_week_start, uid, dow, role, remarks) for uid, dow, role, remarks in rows],
    )
    return len(rows)


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
