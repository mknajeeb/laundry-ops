"""Planned weekly schedule — manager grid (org + week scoped, payroll user_id keyed)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any, Mapping, Sequence

from backend.daily_shift_roster import calc_cost, calc_hours, parse_time_value
from backend.ta_helpers import table_exists

VALID_ROLES = frozenset({"sort", "wash", "fold", "weigher"})
LEGACY_ROLE_MAP = {"folder": "fold", "operator": "wash", "folders": "fold", "operators": "wash"}
ROLE_SORT_ORDER = ("sort", "wash", "weigher", "fold")
DAY_LABELS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


def normalize_weekly_role(raw: Any) -> str | None:
    role = str(raw or "").strip().lower()
    if role in VALID_ROLES:
        return role
    return LEGACY_ROLE_MAP.get(role)


def parse_weekly_roles(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        out: list[str] = []
        for item in raw:
            role = normalize_weekly_role(item)
            if role and role not in out:
                out.append(role)
        return _sort_roles(out)
    text = str(raw).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            import json

            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parse_weekly_roles(parsed)
        except (TypeError, ValueError):
            pass
    out = []
    for part in text.replace("|", ",").split(","):
        role = normalize_weekly_role(part.strip())
        if role and role not in out:
            out.append(role)
    return _sort_roles(out)


def _sort_roles(roles: list[str]) -> list[str]:
    order = {r: i for i, r in enumerate(ROLE_SORT_ORDER)}
    return sorted(roles, key=lambda r: order.get(r, 99))


def roles_to_storage(roles: Sequence[str]) -> str:
    cleaned = parse_weekly_roles(list(roles))
    if not cleaned:
        return "fold"
    return ",".join(cleaned)


def primary_weekly_role(raw: Any) -> str:
    roles = parse_weekly_roles(raw)
    return roles[0] if roles else "fold"


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


def _ensure_role_column_width(cursor) -> None:
    try:
        cursor.execute("SHOW COLUMNS FROM planned_weekly_schedule_entries LIKE 'role'")
        row = cursor.fetchone()
        if not row:
            return
        col_type = row.get("Type") if isinstance(row, dict) else (row[1] if len(row) > 1 else "")
        if col_type and "varchar(64)" not in str(col_type).lower():
            cursor.execute(
                "ALTER TABLE planned_weekly_schedule_entries "
                "MODIFY role VARCHAR(64) NOT NULL DEFAULT 'fold'"
            )
    except Exception:
        return


def _ensure_employer_affiliation_column(cursor) -> None:
    try:
        cursor.execute(
            "SHOW COLUMNS FROM planned_weekly_schedule_entries LIKE 'employer_affiliation'"
        )
        if cursor.fetchone():
            return
        cursor.execute(
            "ALTER TABLE planned_weekly_schedule_entries "
            "ADD COLUMN employer_affiliation VARCHAR(32) NULL DEFAULT NULL "
            "AFTER break_minutes"
        )
    except Exception:
        return


def ensure_planned_weekly_schedule_table(cursor) -> None:
    if table_exists(cursor, "planned_weekly_schedule_entries"):
        _ensure_role_column_width(cursor)
        _ensure_employer_affiliation_column(cursor)
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS planned_weekly_schedule_entries (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          week_start DATE NOT NULL,
          user_id INT NOT NULL,
          day_of_week TINYINT NOT NULL,
          role VARCHAR(64) NOT NULL DEFAULT 'fold',
          start_time TIME NOT NULL,
          end_time TIME NOT NULL,
          break_minutes INT NOT NULL DEFAULT 0,
          employer_affiliation VARCHAR(32) NULL DEFAULT NULL,
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


def _entry_employer_affiliation(
    row: Mapping[str, Any],
    *,
    organization_slug: str | None = None,
) -> str | None:
    from backend.payroll_employer_affiliation import normalize_shift_employer_affiliation

    return normalize_shift_employer_affiliation(
        row.get("employer_affiliation"),
        organization_slug=organization_slug,
    )


def serialize_entry(
    row: Mapping[str, Any],
    *,
    schedule_end_time_enabled: bool = True,
    organization_slug: str | None = None,
) -> dict[str, Any]:
    roles = parse_weekly_roles(row.get("role"))
    role = roles_to_storage(roles)
    hours = 0.0 if not schedule_end_time_enabled else _shift_hours_for_entry(row)
    employer_affiliation = _entry_employer_affiliation(row, organization_slug=organization_slug)
    out: dict[str, Any] = {
        "id": int(row.get("id") or 0),
        "organization_id": int(row.get("organization_id") or 0),
        "week_start": str(row.get("week_start") or ""),
        "user_id": int(row.get("user_id") or 0),
        "day_of_week": int(row.get("day_of_week") or 0),
        "day_label": DAY_LABELS[int(row.get("day_of_week") or 0) % 7],
        "role": role,
        "roles": roles,
        "start_time": _time_to_str(row.get("start_time")),
        "end_time": _time_to_str(row.get("end_time")),
        "break_minutes": max(0, int(row.get("break_minutes") or 0)),
        "hours": hours,
    }
    if employer_affiliation:
        out["employer_affiliation"] = employer_affiliation
    return out


def enrich_entries_with_employer_affiliation(
    entries: Sequence[Mapping[str, Any]],
    workers_by_user_id: Mapping[int, Mapping[str, Any]],
    *,
    organization_slug: str | None = None,
) -> list[dict[str, Any]]:
    from backend.payroll_employer_affiliation import default_shift_employer_affiliation

    out: list[dict[str, Any]] = []
    for entry in entries or []:
        row = dict(entry)
        if not row.get("employer_affiliation"):
            uid = int(row.get("user_id") or 0)
            row["employer_affiliation"] = default_shift_employer_affiliation(
                workers_by_user_id.get(uid),
                organization_slug=organization_slug,
            )
        out.append(row)
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
            "sort_count": 0,
            "wash_count": 0,
            "weigher_count": 0,
            "fold_count": 0,
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
        roles = parse_weekly_roles(entry.get("role"))
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
        counted_roles = roles or ["fold"]
        for role in counted_roles:
            if role == "sort":
                day["sort_count"] = int(day["sort_count"]) + 1
            elif role == "wash":
                day["wash_count"] = int(day["wash_count"]) + 1
            elif role == "weigher":
                day["weigher_count"] = int(day["weigher_count"]) + 1
            elif role == "fold":
                day["fold_count"] = int(day["fold_count"]) + 1
            if role == "wash":
                day["operator_count"] = int(day["operator_count"]) + 1
            if role == "fold":
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
    from backend.payroll_schedule import list_schedule_workers_for_grid

    return list_schedule_workers_for_grid(conn, int(organization_id))


def _workers_index(workers: Sequence[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for worker in workers or []:
        uid = int(worker.get("user_id") or 0)
        if uid:
            out[uid] = dict(worker)
    return out


def _schedule_end_time_enabled(cursor, organization_id: int) -> bool:
    from backend.weekly_schedule_display_settings import get_weekly_schedule_display_settings

    settings = get_weekly_schedule_display_settings(cursor, int(organization_id))
    return bool(settings.get("schedule_end_time_enabled", True))


def list_week_entries(
    cursor,
    organization_id: int,
    *,
    week_start: date,
    conn=None,
) -> list[dict[str, Any]]:
    ensure_planned_weekly_schedule_table(cursor)
    end_time_enabled = _schedule_end_time_enabled(cursor, organization_id)
    org_slug = None
    if conn is not None:
        from backend.payroll_employer_affiliation import _organization_slug

        org_slug = _organization_slug(conn, organization_id)
    cursor.execute(
        """
        SELECT id, organization_id, week_start, user_id, day_of_week,
               role, start_time, end_time, break_minutes, employer_affiliation
        FROM planned_weekly_schedule_entries
        WHERE organization_id = %s AND week_start = %s
        ORDER BY user_id ASC, day_of_week ASC, start_time ASC, id ASC
        """,
        (int(organization_id), week_start),
    )
    rows = cursor.fetchall() or []
    return [
        serialize_entry(
            r,
            schedule_end_time_enabled=end_time_enabled,
            organization_slug=org_slug,
        )
        for r in rows
        if isinstance(r, dict)
    ]


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
    *,
    conn=None,
) -> dict[str, Any] | None:
    ensure_planned_weekly_schedule_table(cursor)
    cursor.execute(
        """
        SELECT id, organization_id, week_start, user_id, day_of_week,
               role, start_time, end_time, break_minutes, employer_affiliation
        FROM planned_weekly_schedule_entries
        WHERE organization_id = %s AND id = %s
        LIMIT 1
        """,
        (int(organization_id), int(entry_id)),
    )
    row = cursor.fetchone()
    if not row or not isinstance(row, dict):
        return None
    end_time_enabled = _schedule_end_time_enabled(cursor, organization_id)
    org_slug = None
    if conn is not None:
        from backend.payroll_employer_affiliation import _organization_slug

        org_slug = _organization_slug(conn, organization_id)
    return serialize_entry(
        row,
        schedule_end_time_enabled=end_time_enabled,
        organization_slug=org_slug,
    )


def _validate_entry_payload(
    data: Mapping[str, Any],
    *,
    partial: bool = False,
    schedule_end_time_enabled: bool = True,
    organization_slug: str | None = None,
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
    if not partial or "role" in data or "roles" in data:
        roles_raw = data.get("roles") if "roles" in data else data.get("role")
        roles = parse_weekly_roles(roles_raw)
        if not roles:
            return None, "role must be sort, wash, weigher, and/or fold"
        out["role"] = roles_to_storage(roles)
    if not partial or "start_time" in data:
        start = parse_time_value(data.get("start_time"))
        if start is None:
            return None, "start_time is required (HH:MM)"
        out["start_time"] = start
    if schedule_end_time_enabled:
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
    else:
        start = out.get("start_time") or parse_time_value(data.get("start_time"))
        if start is None and not partial:
            return None, "start_time is required (HH:MM)"
        if start is not None:
            out["start_time"] = start
            out["end_time"] = start
        out["break_minutes"] = 0
    if schedule_end_time_enabled and ("break_minutes" in data or not partial):
        try:
            out["break_minutes"] = max(0, int(data.get("break_minutes") or 0))
        except (TypeError, ValueError):
            return None, "break_minutes must be a non-negative integer"
    if "employer_affiliation" in data:
        from backend.payroll_employer_affiliation import normalize_shift_employer_affiliation

        raw_aff = data.get("employer_affiliation")
        if raw_aff is not None and str(raw_aff).strip():
            aff = normalize_shift_employer_affiliation(
                raw_aff,
                organization_slug=organization_slug,
            )
            if not aff:
                return None, "employer_affiliation must be washpro, washmate, veewash, or rinse_exclusive"
            out["employer_affiliation"] = aff
    return out, None


def _assert_worker_in_org(conn, organization_id: int, user_id: int) -> str | None:
    from backend.payroll_schedule import worker_exists_in_schedule_grid

    if not worker_exists_in_schedule_grid(conn, organization_id, int(user_id)):
        return "worker not found in payroll profiles"
    return None


def _assert_worker_schedulable(conn, organization_id: int, user_id: int) -> str | None:
    from backend.payroll_employer_affiliation import (
        EMPLOYER_AFFILIATION_NONE,
        _organization_slug,
        employer_affiliation_from_flags,
    )

    org_slug = _organization_slug(conn, organization_id)
    worker = _workers_index(_load_workers(conn, organization_id)).get(int(user_id))
    if employer_affiliation_from_flags(worker, organization_slug=org_slug) == EMPLOYER_AFFILIATION_NONE:
        return "worker is not assigned to a schedule entity (affiliation none)"
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
    end_time_enabled = _schedule_end_time_enabled(cursor, organization_id)
    from backend.payroll_employer_affiliation import _organization_slug

    org_slug = _organization_slug(conn, organization_id)
    payload, err = _validate_entry_payload(
        data,
        schedule_end_time_enabled=end_time_enabled,
        organization_slug=org_slug,
    )
    if err:
        return None, err
    worker_err = _assert_worker_in_org(conn, organization_id, payload["user_id"])
    if worker_err:
        return None, worker_err
    schedulable_err = _assert_worker_schedulable(conn, organization_id, payload["user_id"])
    if schedulable_err:
        return None, schedulable_err
    if "employer_affiliation" not in payload:
        from backend.payroll_employer_affiliation import default_shift_employer_affiliation

        worker = _workers_index(_load_workers(conn, organization_id)).get(int(payload["user_id"]))
        payload["employer_affiliation"] = default_shift_employer_affiliation(
            worker,
            organization_slug=org_slug,
        )
    cursor.execute(
        """
        INSERT INTO planned_weekly_schedule_entries (
            organization_id, week_start, user_id, day_of_week,
            role, start_time, end_time, break_minutes, employer_affiliation
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
            payload["employer_affiliation"],
        ),
    )
    entry_id = int(cursor.lastrowid or 0)
    return get_entry(cursor, organization_id, entry_id, conn=conn), None


def update_entry(
    conn,
    cursor,
    organization_id: int,
    entry_id: int,
    data: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    ensure_planned_weekly_schedule_table(cursor)
    existing = get_entry(cursor, organization_id, entry_id, conn=conn)
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
    if "employer_affiliation" not in merged and existing.get("employer_affiliation"):
        merged["employer_affiliation"] = existing.get("employer_affiliation")
    end_time_enabled = _schedule_end_time_enabled(cursor, organization_id)
    from backend.payroll_employer_affiliation import _organization_slug

    org_slug = _organization_slug(conn, organization_id)
    payload, err = _validate_entry_payload(
        merged,
        schedule_end_time_enabled=end_time_enabled,
        organization_slug=org_slug,
    )
    if err:
        return None, err
    worker_err = _assert_worker_in_org(conn, organization_id, payload["user_id"])
    if worker_err:
        return None, worker_err
    cursor.execute(
        """
        UPDATE planned_weekly_schedule_entries
        SET user_id=%s, day_of_week=%s, role=%s, start_time=%s, end_time=%s, break_minutes=%s,
            employer_affiliation=%s
        WHERE organization_id=%s AND id=%s
        """,
        (
            payload["user_id"],
            payload["day_of_week"],
            payload["role"],
            payload["start_time"],
            payload["end_time"],
            payload.get("break_minutes", 0),
            payload.get("employer_affiliation") or existing.get("employer_affiliation"),
            int(organization_id),
            int(entry_id),
        ),
    )
    return get_entry(cursor, organization_id, entry_id, conn=conn), None


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
    existing = get_entry(cursor, organization_id, entry_id, conn=conn)
    if not existing:
        return None, "schedule entry not found"
    target_user = int(user_id) if user_id is not None else int(existing["user_id"])
    target_day = normalize_day_of_week(day_of_week) if day_of_week is not None else int(existing["day_of_week"])
    if target_day is None:
        return None, "day_of_week must be 0-6 (Sun-Sat)"
    duplicate_data: dict[str, Any] = {
        "user_id": target_user,
        "day_of_week": target_day,
        "roles": existing.get("roles") or parse_weekly_roles(existing["role"]),
        "start_time": existing["start_time"],
        "end_time": existing["end_time"],
        "break_minutes": existing["break_minutes"],
    }
    if existing.get("employer_affiliation"):
        duplicate_data["employer_affiliation"] = existing["employer_affiliation"]
    return create_entry(
        conn,
        cursor,
        organization_id,
        week_start=date.fromisoformat(str(existing["week_start"])),
        data=duplicate_data,
    )


def _bulk_insert_week_entries(
    cursor,
    organization_id: int,
    *,
    week_start: date,
    payloads: Sequence[Mapping[str, Any]],
) -> None:
    if not payloads:
        return
    ensure_planned_weekly_schedule_table(cursor)
    oid = int(organization_id)
    params = []
    for payload in payloads:
        start = parse_time_value(payload.get("start_time"))
        end = parse_time_value(payload.get("end_time"))
        role = roles_to_storage(parse_weekly_roles(payload.get("role") or payload.get("roles")))
        from backend.payroll_employer_affiliation import normalize_shift_employer_affiliation

        employer_affiliation = normalize_shift_employer_affiliation(payload.get("employer_affiliation"))
        params.append(
            (
                oid,
                week_start,
                int(payload["user_id"]),
                int(payload["day_of_week"]),
                role,
                start,
                end,
                max(0, int(payload.get("break_minutes") or 0)),
                employer_affiliation,
            )
        )
    cursor.executemany(
        """
        INSERT INTO planned_weekly_schedule_entries (
            organization_id, week_start, user_id, day_of_week,
            role, start_time, end_time, break_minutes, employer_affiliation
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        params,
    )


def week_has_schedule_content(
    cursor,
    organization_id: int,
    *,
    week_start: date,
) -> bool:
    if list_week_entries(cursor, organization_id, week_start=week_start):
        return True
    return bool(list_excluded_user_ids(cursor, organization_id, week_start=week_start))


def find_latest_schedule_week_before(
    cursor,
    organization_id: int,
    *,
    before_week_start: date,
) -> date | None:
    ensure_planned_weekly_schedule_table(cursor)
    cursor.execute(
        """
        SELECT week_start
        FROM planned_weekly_schedule_entries
        WHERE organization_id = %s AND week_start < %s
        GROUP BY week_start
        ORDER BY week_start DESC
        LIMIT 1
        """,
        (int(organization_id), before_week_start),
    )
    row = cursor.fetchone()
    if not row:
        return None
    raw = row.get("week_start") if isinstance(row, dict) else row[0]
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def carry_forward_week_schedule(
    conn,
    cursor,
    organization_id: int,
    *,
    target_week_start: date,
    source_week_start: date,
) -> dict[str, Any]:
    """Copy entries and exclusions from source week into target week."""
    oid = int(organization_id)
    valid_user_ids = {
        int(w.get("user_id") or 0)
        for w in _load_workers(conn, oid)
        if int(w.get("user_id") or 0) > 0
    }

    source_entries = list_week_entries(cursor, oid, week_start=source_week_start)
    source_exclusions = list_excluded_user_ids(cursor, oid, week_start=source_week_start)

    payloads: list[dict[str, Any]] = []
    skipped_entries = 0
    for entry in source_entries:
        uid = int(entry.get("user_id") or 0)
        if uid not in valid_user_ids:
            skipped_entries += 1
            continue
        payloads.append(
            {
                "user_id": uid,
                "day_of_week": entry["day_of_week"],
                "role": entry.get("role"),
                "start_time": entry["start_time"],
                "end_time": entry["end_time"],
                "break_minutes": entry.get("break_minutes", 0),
                "employer_affiliation": entry.get("employer_affiliation"),
            }
        )

    entries_copied = 0
    if payloads:
        _bulk_insert_week_entries(cursor, oid, week_start=target_week_start, payloads=payloads)
        entries_copied = len(payloads)

    exclusions_copied = 0
    for uid in source_exclusions:
        if uid not in valid_user_ids:
            continue
        set_employee_exclusion(
            conn,
            cursor,
            oid,
            week_start=target_week_start,
            user_id=uid,
            excluded=True,
        )
        exclusions_copied += 1

    return {
        "source_week_start": str(source_week_start),
        "target_week_start": str(target_week_start),
        "entries_copied": entries_copied,
        "exclusions_copied": exclusions_copied,
        "entries_skipped": skipped_entries,
    }


def ensure_week_schedule_carried_forward(
    conn,
    cursor,
    organization_id: int,
    *,
    week_start: date,
) -> dict[str, Any] | None:
    """If target week has no schedule yet, seed it from the latest prior week."""
    if week_has_schedule_content(cursor, organization_id, week_start=week_start):
        return None
    source = find_latest_schedule_week_before(
        cursor,
        organization_id,
        before_week_start=week_start,
    )
    if not source:
        return None
    return carry_forward_week_schedule(
        conn,
        cursor,
        organization_id,
        target_week_start=week_start,
        source_week_start=source,
    )


def bulk_set_week_entry_employer_affiliation(
    conn,
    cursor,
    organization_id: int,
    *,
    week_start: date,
    employer_affiliation: str,
) -> tuple[int, str | None, list[dict[str, Any]]]:
    from backend.payroll_employer_affiliation import (
        _organization_slug,
        bulk_shift_entity_allowed,
        normalize_shift_employer_affiliation,
    )

    ensure_planned_weekly_schedule_table(cursor)
    org_slug = _organization_slug(conn, organization_id)
    aff = normalize_shift_employer_affiliation(employer_affiliation, organization_slug=org_slug)
    if not aff:
        return 0, "employer_affiliation must be washpro, washmate, veewash, or rinse_exclusive", []

    workers_by_uid = _workers_index(_load_workers(conn, organization_id))
    rows = list_week_entries(cursor, organization_id, week_start=week_start, conn=conn)
    skipped: list[dict[str, Any]] = []
    updated = 0
    for row in rows:
        entry_id = int(row.get("id") or 0)
        uid = int(row.get("user_id") or 0)
        worker = workers_by_uid.get(uid)
        allowed, reason = bulk_shift_entity_allowed(worker, aff, organization_slug=org_slug)
        if not allowed:
            skipped.append(
                {
                    "entry_id": entry_id,
                    "user_id": uid,
                    "reason": reason or "entity mismatch",
                }
            )
            continue
        cursor.execute(
            """
            UPDATE planned_weekly_schedule_entries
            SET employer_affiliation=%s
            WHERE organization_id=%s AND id=%s
            """,
            (aff, int(organization_id), entry_id),
        )
        updated += int(getattr(cursor, "rowcount", 0) or 0)
    return updated, None, skipped


def build_week_payload(
    conn,
    cursor,
    organization_id: int,
    *,
    week_start: date,
    user_roles: Sequence[str] | None = None,
) -> dict[str, Any]:
    from backend.business_entity import entity_scope_payload
    from backend.payroll_employer_affiliation import _organization_slug, employer_affiliation_from_flags
    from backend.weekly_schedule_display_settings import effective_weekly_schedule_view, apply_rinse_viewer_scope

    org_slug = _organization_slug(conn, organization_id)
    workers = _load_workers(conn, organization_id)
    workers_by_uid = _workers_index(workers)
    entries = enrich_entries_with_employer_affiliation(
        list_week_entries(cursor, organization_id, week_start=week_start, conn=conn),
        workers_by_uid,
        organization_slug=org_slug,
    )
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
                "can_work_rinse": bool(worker.get("can_work_rinse", True)),
                "can_work_drop_off": bool(worker.get("can_work_drop_off", True)),
                "can_work_both": bool(worker.get("can_work_both", True)),
                "employer_affiliation": employer_affiliation_from_flags(worker, organization_slug=org_slug),
                "business_entity": employer_affiliation_from_flags(worker, organization_slug=org_slug),
                "total_hours": stats["total_hours"],
                "scheduled_days": stats["scheduled_days"],
                "estimated_cost": stats["estimated_cost"],
                "excluded": is_excluded,
            }
        )
    employee_rows.sort(key=lambda row: (row.get("display_name") or "").casefold())

    view = effective_weekly_schedule_view(cursor, organization_id, user_roles)

    payload = {
        "week_start": str(week_start),
        "day_labels": list(DAY_LABELS),
        "employees": employee_rows,
        "entries": entries,
        "totals": totals,
        "excluded_user_ids": excluded_user_ids,
        "display": view,
        "entity_scope": entity_scope_payload(organization_id, org_slug, user_roles),
    }
    if view.get("lock_employer_tab"):
        return apply_rinse_viewer_scope(payload)
    return payload
