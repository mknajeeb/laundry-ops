"""Planned weekly schedule — manager grid (org + week scoped, payroll user_id keyed)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any, Mapping, Sequence

from backend.daily_shift_roster import calc_cost, calc_hours, normalize_role, parse_time_value
from backend.ta_helpers import table_exists

VALID_ROLES = frozenset({"folder", "operator"})
DAY_LABELS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


def normalize_week_start(raw: date | str | None) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            parsed = date.fromisoformat(text[:10])
        except ValueError:
            return None
    elif isinstance(raw, date):
        parsed = raw
    else:
        return None
    days_since_sunday = (parsed.weekday() + 1) % 7
    return parsed - timedelta(days=days_since_sunday)


def normalize_day_of_week(raw: Any) -> int | None:
    try:
        dow = int(raw)
    except (TypeError, ValueError):
        return None
    if 0 <= dow <= 6:
        return dow
    return None


def ensure_planned_weekly_schedule_exclusions_table(cursor) -> None:
    if table_exists(cursor, "planned_weekly_schedule_exclusions"):
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS planned_weekly_schedule_exclusions (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          week_start DATE NOT NULL,
          user_id INT NOT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          UNIQUE KEY uq_pwse_org_week_user (organization_id, week_start, user_id),
          INDEX idx_pwse_org_week (organization_id, week_start)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def ensure_planned_weekly_schedule_table(cursor) -> None:
    if table_exists(cursor, "planned_weekly_schedule_entries"):
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS planned_weekly_schedule_entries (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          week_start DATE NOT NULL,
          user_id INT NOT NULL,
          day_of_week TINYINT NOT NULL,
          role VARCHAR(16) NOT NULL DEFAULT 'folder',
          start_time TIME NOT NULL,
          end_time TIME NOT NULL,
          break_minutes INT NOT NULL DEFAULT 0,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP,
          INDEX idx_pwse_org_week (organization_id, week_start),
          INDEX idx_pwse_org_week_user_day (organization_id, week_start, user_id, day_of_week)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _time_to_str(value: Any) -> str | None:
    parsed = parse_time_value(value)
    if parsed is None:
        return None
    return parsed.strftime("%H:%M")


def _shift_hours_for_entry(entry: Mapping[str, Any]) -> float:
    start = parse_time_value(entry.get("start_time"))
    end = parse_time_value(entry.get("end_time"))
    if not start or not end:
        return 0.0
    break_min = max(0, int(entry.get("break_minutes") or 0))
    return calc_hours(start, end, break_min)


def serialize_entry(row: Mapping[str, Any]) -> dict[str, Any]:
    role = normalize_role(row.get("role")) or "folder"
    hours = _shift_hours_for_entry(row)
    out: dict[str, Any] = {
        "id": int(row.get("id") or 0),
        "organization_id": int(row.get("organization_id") or 0),
        "week_start": str(row.get("week_start") or ""),
        "user_id": int(row.get("user_id") or 0),
        "day_of_week": int(row.get("day_of_week") or 0),
        "day_label": DAY_LABELS[int(row.get("day_of_week") or 0) % 7],
        "role": role,
        "start_time": _time_to_str(row.get("start_time")),
        "end_time": _time_to_str(row.get("end_time")),
        "break_minutes": max(0, int(row.get("break_minutes") or 0)),
        "hours": hours,
    }
    return out


def _worker_rate(worker: Mapping[str, Any] | None) -> float:
    if not worker:
        return 0.0
    try:
        return max(0.0, float(worker.get("default_hourly_rate") or 0))
    except (TypeError, ValueError):
        return 0.0


def compute_schedule_totals(
    entries: Sequence[Mapping[str, Any]],
    workers_by_user_id: Mapping[int, Mapping[str, Any]],
    *,
    excluded_user_ids: Sequence[int] | None = None,
) -> dict[str, Any]:
    excluded = {int(uid) for uid in (excluded_user_ids or [])}
    employee_totals: dict[int, dict[str, Any]] = {}
    day_totals: dict[int, dict[str, Any]] = {
        dow: {
            "day_of_week": dow,
            "day_label": DAY_LABELS[dow],
            "employee_count": 0,
            "total_hours": 0.0,
            "operator_count": 0,
            "folder_count": 0,
        }
        for dow in range(7)
    }
    employee_days: dict[int, set[int]] = defaultdict(set)

    for entry in entries or []:
        uid = int(entry.get("user_id") or 0)
        if uid in excluded:
            continue
        dow = int(entry.get("day_of_week") or 0)
        hours = float(entry.get("hours") or _shift_hours_for_entry(entry))
        role = normalize_role(entry.get("role")) or "folder"
        worker = workers_by_user_id.get(uid)
        rate = _worker_rate(worker)

        if uid not in employee_totals:
            employee_totals[uid] = {
                "user_id": uid,
                "total_hours": 0.0,
                "scheduled_days": 0,
                "estimated_cost": 0.0,
            }
        employee_totals[uid]["total_hours"] = round(employee_totals[uid]["total_hours"] + hours, 2)
        employee_totals[uid]["estimated_cost"] = round(
            employee_totals[uid]["estimated_cost"] + calc_cost(hours, rate),
            2,
        )
        employee_days[uid].add(dow)

        day = day_totals.get(dow) or day_totals[dow]
        day["total_hours"] = round(float(day["total_hours"]) + hours, 2)
        if role == "operator":
            day["operator_count"] = int(day["operator_count"]) + 1
        else:
            day["folder_count"] = int(day["folder_count"]) + 1

    for uid, days in employee_days.items():
        if uid in employee_totals:
            employee_totals[uid]["scheduled_days"] = len(days)

    day_people: dict[int, set[int]] = defaultdict(set)
    for entry in entries or []:
        uid = int(entry.get("user_id") or 0)
        if uid in excluded:
            continue
        dow = int(entry.get("day_of_week") or 0)
        day_people[dow].add(uid)
    for dow, people in day_people.items():
        day_totals[dow]["employee_count"] = len(people)

    return {
        "employee_totals": employee_totals,
        "day_totals": [day_totals[dow] for dow in range(7)],
    }


def _load_workers(conn, organization_id: int) -> list[dict[str, Any]]:
    from backend.payroll_schedule import list_workers

    workers = list_workers(conn, int(organization_id), active_only=False)
    return [w for w in workers if w.get("active")]


def _workers_index(workers: Sequence[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for worker in workers or []:
        uid = int(worker.get("user_id") or 0)
        if uid:
            out[uid] = dict(worker)
    return out


def list_week_entries(
    cursor,
    organization_id: int,
    *,
    week_start: date,
) -> list[dict[str, Any]]:
    ensure_planned_weekly_schedule_table(cursor)
    cursor.execute(
        """
        SELECT id, organization_id, week_start, user_id, day_of_week,
               role, start_time, end_time, break_minutes
        FROM planned_weekly_schedule_entries
        WHERE organization_id = %s AND week_start = %s
        ORDER BY user_id ASC, day_of_week ASC, start_time ASC, id ASC
        """,
        (int(organization_id), week_start),
    )
    rows = cursor.fetchall() or []
    return [serialize_entry(r) for r in rows if isinstance(r, dict)]


def list_excluded_user_ids(
    cursor,
    organization_id: int,
    *,
    week_start: date,
) -> list[int]:
    ensure_planned_weekly_schedule_exclusions_table(cursor)
    cursor.execute(
        """
        SELECT user_id
        FROM planned_weekly_schedule_exclusions
        WHERE organization_id = %s AND week_start = %s
        ORDER BY user_id ASC
        """,
        (int(organization_id), week_start),
    )
    rows = cursor.fetchall() or []
    out: list[int] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(int(row.get("user_id") or 0))
        else:
            try:
                out.append(int(row))
            except (TypeError, ValueError):
                continue
    return [uid for uid in out if uid > 0]


def set_employee_exclusion(
    conn,
    cursor,
    organization_id: int,
    *,
    week_start: date,
    user_id: int,
    excluded: bool,
) -> tuple[bool, str | None]:
    ensure_planned_weekly_schedule_exclusions_table(cursor)
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False, "user_id is required"
    if uid <= 0:
        return False, "user_id is required"
    worker_err = _assert_worker_in_org(conn, organization_id, uid)
    if worker_err:
        return False, worker_err
    oid = int(organization_id)
    if excluded:
        cursor.execute(
            """
            INSERT IGNORE INTO planned_weekly_schedule_exclusions
                (organization_id, week_start, user_id)
            VALUES (%s, %s, %s)
            """,
            (oid, week_start, uid),
        )
    else:
        cursor.execute(
            """
            DELETE FROM planned_weekly_schedule_exclusions
            WHERE organization_id = %s AND week_start = %s AND user_id = %s
            """,
            (oid, week_start, uid),
        )
    return excluded, None


def get_entry(
    cursor,
    organization_id: int,
    entry_id: int,
) -> dict[str, Any] | None:
    ensure_planned_weekly_schedule_table(cursor)
    cursor.execute(
        """
        SELECT id, organization_id, week_start, user_id, day_of_week,
               role, start_time, end_time, break_minutes
        FROM planned_weekly_schedule_entries
        WHERE organization_id = %s AND id = %s
        LIMIT 1
        """,
        (int(organization_id), int(entry_id)),
    )
    row = cursor.fetchone()
    if not row or not isinstance(row, dict):
        return None
    return serialize_entry(row)


def _validate_entry_payload(
    data: Mapping[str, Any],
    *,
    partial: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    out: dict[str, Any] = {}
    if not partial or "user_id" in data:
        try:
            uid = int(data.get("user_id"))
        except (TypeError, ValueError):
            return None, "user_id is required"
        if uid <= 0:
            return None, "user_id is required"
        out["user_id"] = uid
    if not partial or "day_of_week" in data:
        dow = normalize_day_of_week(data.get("day_of_week"))
        if dow is None:
            return None, "day_of_week must be 0-6 (Sun-Sat)"
        out["day_of_week"] = dow
    if not partial or "role" in data:
        role = normalize_role(data.get("role"))
        if role is None:
            return None, "role must be folder or operator"
        out["role"] = role
    if not partial or "start_time" in data:
        start = parse_time_value(data.get("start_time"))
        if start is None:
            return None, "start_time is required (HH:MM)"
        out["start_time"] = start
    if not partial or "end_time" in data:
        end = parse_time_value(data.get("end_time"))
        if end is None:
            return None, "end_time is required (HH:MM)"
        out["end_time"] = end
    if (
        "start_time" in out
        and "end_time" in out
        and calc_hours(out["start_time"], out["end_time"], int(data.get("break_minutes") or 0)) <= 0
    ):
        return None, "hours must be greater than zero"
    if "break_minutes" in data or not partial:
        try:
            out["break_minutes"] = max(0, int(data.get("break_minutes") or 0))
        except (TypeError, ValueError):
            return None, "break_minutes must be a non-negative integer"
    return out, None


def _assert_worker_in_org(conn, organization_id: int, user_id: int) -> str | None:
    workers = _workers_index(_load_workers(conn, organization_id))
    if int(user_id) not in workers:
        return "worker not found in payroll profiles"
    return None


def create_entry(
    conn,
    cursor,
    organization_id: int,
    *,
    week_start: date,
    data: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    ensure_planned_weekly_schedule_table(cursor)
    payload, err = _validate_entry_payload(data)
    if err:
        return None, err
    worker_err = _assert_worker_in_org(conn, organization_id, payload["user_id"])
    if worker_err:
        return None, worker_err
    cursor.execute(
        """
        INSERT INTO planned_weekly_schedule_entries (
            organization_id, week_start, user_id, day_of_week,
            role, start_time, end_time, break_minutes
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            week_start,
            payload["user_id"],
            payload["day_of_week"],
            payload["role"],
            payload["start_time"],
            payload["end_time"],
            payload.get("break_minutes", 0),
        ),
    )
    entry_id = int(cursor.lastrowid or 0)
    return get_entry(cursor, organization_id, entry_id), None


def update_entry(
    conn,
    cursor,
    organization_id: int,
    entry_id: int,
    data: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    ensure_planned_weekly_schedule_table(cursor)
    existing = get_entry(cursor, organization_id, entry_id)
    if not existing:
        return None, "schedule entry not found"
    merged = {
        "user_id": existing["user_id"],
        "day_of_week": existing["day_of_week"],
        "role": existing["role"],
        "start_time": existing["start_time"],
        "end_time": existing["end_time"],
        "break_minutes": existing["break_minutes"],
        **dict(data or {}),
    }
    payload, err = _validate_entry_payload(merged)
    if err:
        return None, err
    worker_err = _assert_worker_in_org(conn, organization_id, payload["user_id"])
    if worker_err:
        return None, worker_err
    cursor.execute(
        """
        UPDATE planned_weekly_schedule_entries
        SET user_id=%s, day_of_week=%s, role=%s, start_time=%s, end_time=%s, break_minutes=%s
        WHERE organization_id=%s AND id=%s
        """,
        (
            payload["user_id"],
            payload["day_of_week"],
            payload["role"],
            payload["start_time"],
            payload["end_time"],
            payload.get("break_minutes", 0),
            int(organization_id),
            int(entry_id),
        ),
    )
    return get_entry(cursor, organization_id, entry_id), None


def delete_entry(
    cursor,
    organization_id: int,
    entry_id: int,
) -> bool:
    ensure_planned_weekly_schedule_table(cursor)
    cursor.execute(
        """
        DELETE FROM planned_weekly_schedule_entries
        WHERE organization_id = %s AND id = %s
        """,
        (int(organization_id), int(entry_id)),
    )
    return bool(cursor.rowcount)


def move_entry(
    conn,
    cursor,
    organization_id: int,
    entry_id: int,
    *,
    user_id: int,
    day_of_week: int,
) -> tuple[dict[str, Any] | None, str | None]:
    dow = normalize_day_of_week(day_of_week)
    if dow is None:
        return None, "day_of_week must be 0-6 (Sun-Sat)"
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None, "user_id is required"
    worker_err = _assert_worker_in_org(conn, organization_id, uid)
    if worker_err:
        return None, worker_err
    return update_entry(
        conn,
        cursor,
        organization_id,
        entry_id,
        {"user_id": uid, "day_of_week": dow},
    )


def duplicate_entry(
    conn,
    cursor,
    organization_id: int,
    entry_id: int,
    *,
    user_id: int | None = None,
    day_of_week: int | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    existing = get_entry(cursor, organization_id, entry_id)
    if not existing:
        return None, "schedule entry not found"
    target_user = int(user_id) if user_id is not None else int(existing["user_id"])
    target_day = normalize_day_of_week(day_of_week) if day_of_week is not None else int(existing["day_of_week"])
    if target_day is None:
        return None, "day_of_week must be 0-6 (Sun-Sat)"
    return create_entry(
        conn,
        cursor,
        organization_id,
        week_start=date.fromisoformat(str(existing["week_start"])),
        data={
            "user_id": target_user,
            "day_of_week": target_day,
            "role": existing["role"],
            "start_time": existing["start_time"],
            "end_time": existing["end_time"],
            "break_minutes": existing["break_minutes"],
        },
    )


def build_week_payload(
    conn,
    cursor,
    organization_id: int,
    *,
    week_start: date,
) -> dict[str, Any]:
    workers = _load_workers(conn, organization_id)
    workers_by_uid = _workers_index(workers)
    entries = list_week_entries(cursor, organization_id, week_start=week_start)
    excluded_user_ids = list_excluded_user_ids(cursor, organization_id, week_start=week_start)
    excluded_set = set(excluded_user_ids)
    totals = compute_schedule_totals(
        entries,
        workers_by_uid,
        excluded_user_ids=excluded_user_ids,
    )

    employee_rows = []
    for worker in workers:
        uid = int(worker.get("user_id") or 0)
        is_excluded = uid in excluded_set
        stats = totals["employee_totals"].get(uid) or {
            "user_id": uid,
            "total_hours": 0.0,
            "scheduled_days": 0,
            "estimated_cost": 0.0,
        }
        employee_rows.append(
            {
                "user_id": uid,
                "worker_profile_id": worker.get("worker_profile_id") or worker.get("id"),
                "display_name": worker.get("display_name") or worker.get("worker_name") or f"User {uid}",
                "default_hourly_rate": _worker_rate(worker),
                "total_hours": stats["total_hours"],
                "scheduled_days": stats["scheduled_days"],
                "estimated_cost": stats["estimated_cost"],
                "excluded": is_excluded,
            }
        )
    employee_rows.sort(key=lambda row: (row.get("display_name") or "").casefold())

    return {
        "week_start": str(week_start),
        "day_labels": list(DAY_LABELS),
        "employees": employee_rows,
        "entries": entries,
        "totals": totals,
        "excluded_user_ids": excluded_user_ids,
    }
