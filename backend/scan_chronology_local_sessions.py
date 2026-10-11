"""Scan Chronology local sessions.

Manager-entered work windows used only for Scan Chronology time and
productivity. Stored in their own table; never read from or written to
payroll / attendance (``shift_sessions`` / ``shift_job_segments``).

Times are naive America/New_York wall clock, the same convention as Rinse
scan fields, so scans and sessions compare directly.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_folding_et import ET

TABLE = "scan_chronology_local_sessions"
ROLES = ("weighing", "sorting", "washing", "drying", "folder")
ROLE_LABELS = {
    "weighing": "Weighing",
    "sorting": "Sorting",
    "washing": "Washing",
    "drying": "Drying",
    "folder": "Folder",
}
UNASSIGNED = "unassigned"

_MYSQL_NO_SUCH_TABLE = 1146
_TABLE_READY = False


def ensure_local_session_table(cursor) -> None:
    global _TABLE_READY
    if _TABLE_READY:
        return
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          session_date_et DATE NOT NULL,
          employee_name VARCHAR(255) NOT NULL,
          employee_key VARCHAR(255) NOT NULL,
          role_code VARCHAR(32) NOT NULL,
          started_at_et DATETIME NOT NULL,
          ended_at_et DATETIME NOT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          created_by_user_id INT NULL,
          updated_by_user_id INT NULL,
          KEY idx_scl_sessions_org_day (organization_id, session_date_et, role_code)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _TABLE_READY = True


def employee_key(name: Any) -> str:
    return str(name or "").strip().casefold()


def parse_et_wall(raw: Any) -> datetime:
    """Accept ``YYYY-MM-DDTHH:MM[:SS]`` as ET wall clock; aware values convert to ET."""
    if isinstance(raw, datetime):
        dt = raw
    else:
        text = str(raw or "").strip()
        if not text:
            raise ValueError("start and end times are required")
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"invalid time: {text}") from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone(ET).replace(tzinfo=None)
    return dt.replace(microsecond=0)


def _validate(employee: Any, role: Any, start: datetime, end: datetime) -> tuple[str, str]:
    name = str(employee or "").strip()
    if not name:
        raise ValueError("employee is required")
    if len(name) > 255:
        raise ValueError("employee name is too long")
    role_code = str(role or "").strip().lower()
    if role_code not in ROLES:
        raise ValueError(f"role must be one of: {', '.join(ROLES)}")
    if end <= start:
        raise ValueError("end time must be after start time")
    if end > datetime.combine(start.date() + timedelta(days=1), datetime.min.time()):
        raise ValueError("a session must start and end on the same ET day")
    return name, role_code


def _overlap_id(
    cursor,
    organization_id: int,
    *,
    key: str,
    role_code: str,
    start: datetime,
    end: datetime,
    exclude_id: int | None,
) -> int | None:
    cursor.execute(
        f"""
        SELECT id FROM {TABLE}
        WHERE organization_id = %s
          AND employee_key = %s
          AND role_code = %s
          AND started_at_et < %s
          AND ended_at_et > %s
          AND id <> %s
        LIMIT 1
        """,
        (int(organization_id), key, role_code, end, start, int(exclude_id or 0)),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return int(row["id"] if isinstance(row, Mapping) else row[0])


def _row_out(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "session_date_et": row.get("session_date_et"),
        "employee": row.get("employee_name"),
        "role": row.get("role_code"),
        "start_et": row.get("started_at_et"),
        "end_et": row.get("ended_at_et"),
    }


def _fetch_one(cursor, organization_id: int, session_id: int) -> dict[str, Any] | None:
    cursor.execute(
        f"""
        SELECT id, session_date_et, employee_name, role_code, started_at_et, ended_at_et
        FROM {TABLE}
        WHERE organization_id = %s AND id = %s
        """,
        (int(organization_id), int(session_id)),
    )
    row = cursor.fetchone()
    return _row_out(row) if row else None


def list_local_sessions(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    role: str | None = None,
) -> list[dict[str, Any]]:
    sql = f"""
        SELECT id, session_date_et, employee_name, role_code, started_at_et, ended_at_et
        FROM {TABLE}
        WHERE organization_id = %s AND session_date_et = %s
    """
    params: list[Any] = [int(organization_id), selected_date_et]
    if role:
        sql += " AND role_code = %s"
        params.append(str(role).strip().lower())
    sql += " ORDER BY started_at_et, employee_name, id"
    try:
        cursor.execute(sql, tuple(params))
    except Exception as exc:
        if getattr(exc, "errno", None) == _MYSQL_NO_SUCH_TABLE:
            return []
        raise
    return [_row_out(r) for r in cursor.fetchall() or []]


def create_local_session(
    cursor,
    organization_id: int,
    *,
    employee: Any,
    role: Any,
    start_et: Any,
    end_et: Any,
    actor_user_id: int | None = None,
) -> dict[str, Any]:
    start = parse_et_wall(start_et)
    end = parse_et_wall(end_et)
    name, role_code = _validate(employee, role, start, end)
    ensure_local_session_table(cursor)
    key = employee_key(name)
    if _overlap_id(
        cursor, organization_id, key=key, role_code=role_code, start=start, end=end, exclude_id=None
    ):
        raise ValueError(f"{name} already has an overlapping {ROLE_LABELS[role_code]} session")
    cursor.execute(
        f"""
        INSERT INTO {TABLE}
          (organization_id, session_date_et, employee_name, employee_key, role_code,
           started_at_et, ended_at_et, created_by_user_id, updated_by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            int(organization_id),
            start.date(),
            name,
            key,
            role_code,
            start,
            end,
            actor_user_id,
            actor_user_id,
        ),
    )
    return _fetch_one(cursor, organization_id, int(cursor.lastrowid)) or {}


def update_local_session(
    cursor,
    organization_id: int,
    session_id: int,
    *,
    employee: Any,
    role: Any,
    start_et: Any,
    end_et: Any,
    actor_user_id: int | None = None,
) -> dict[str, Any]:
    ensure_local_session_table(cursor)
    if _fetch_one(cursor, organization_id, session_id) is None:
        raise LookupError("session not found")
    start = parse_et_wall(start_et)
    end = parse_et_wall(end_et)
    name, role_code = _validate(employee, role, start, end)
    key = employee_key(name)
    if _overlap_id(
        cursor,
        organization_id,
        key=key,
        role_code=role_code,
        start=start,
        end=end,
        exclude_id=session_id,
    ):
        raise ValueError(f"{name} already has an overlapping {ROLE_LABELS[role_code]} session")
    cursor.execute(
        f"""
        UPDATE {TABLE}
        SET session_date_et = %s, employee_name = %s, employee_key = %s, role_code = %s,
            started_at_et = %s, ended_at_et = %s, updated_by_user_id = %s
        WHERE organization_id = %s AND id = %s
        """,
        (start.date(), name, key, role_code, start, end, actor_user_id, int(organization_id), int(session_id)),
    )
    return _fetch_one(cursor, organization_id, session_id) or {}


def delete_local_session(cursor, organization_id: int, session_id: int) -> None:
    ensure_local_session_table(cursor)
    cursor.execute(
        f"DELETE FROM {TABLE} WHERE organization_id = %s AND id = %s",
        (int(organization_id), int(session_id)),
    )
    if not cursor.rowcount:
        raise LookupError("session not found")


def scan_time(row: Mapping[str, Any], stage: str) -> datetime | None:
    if stage == "folder":
        candidates = (row.get("end_et"), row.get("start_et"))
    else:
        candidates = (
            row.get("sort_time_et"),
            row.get("time_et"),
            row.get("timestamp_et"),
            row.get("start_et"),
        )
    for value in candidates:
        if isinstance(value, datetime):
            return value.replace(tzinfo=None, microsecond=0) if value.tzinfo else value
    return None


def apply_local_sessions(
    rows: Sequence[dict[str, Any]],
    sessions: Sequence[Mapping[str, Any]],
    *,
    stage: str,
    employee_filter: str | None = None,
) -> dict[str, Any]:
    """Match each scan row to one local session and summarize.

    A scan matches a session with the same employee and role whose window
    contains the scan time (inclusive). When two touching sessions share a
    boundary minute, the later session wins. Rows are annotated in place with
    ``local_session_id`` (None = Unassigned).
    """
    role_code = str(stage or "").strip().lower()
    needle = employee_key(employee_filter) if employee_filter else ""
    scoped = [
        dict(s)
        for s in sessions
        if str(s.get("role") or "").lower() == role_code
        and (not needle or employee_key(s.get("employee")) == needle)
    ]
    scoped.sort(key=lambda s: (s["start_et"], employee_key(s.get("employee")), s["id"]))
    by_employee: dict[str, list[dict[str, Any]]] = {}
    for s in scoped:
        s["scans"] = 0
        by_employee.setdefault(employee_key(s.get("employee")), []).append(s)

    matched = 0
    for row in rows:
        ts = scan_time(row, role_code)
        hit = None
        if ts is not None:
            for s in by_employee.get(employee_key(row.get("employee")), []):
                if s["start_et"] <= ts <= s["end_et"]:
                    hit = s
        row["local_session_id"] = hit["id"] if hit else None
        row["session_status"] = "matched" if hit else UNASSIGNED
        if hit:
            hit["scans"] += 1
            matched += 1

    total_hours = 0.0
    for s in scoped:
        hours = (s["end_et"] - s["start_et"]).total_seconds() / 3600.0
        total_hours += hours
        s["hours"] = round(hours, 2)
        s["scans_per_hour"] = round(s["scans"] / hours, 2) if hours > 0 else None

    n_sessions = len(scoped)
    return {
        "summary": {
            "total_scans": len(rows),
            "matched_scans": matched,
            "unassigned_scans": len(rows) - matched,
            "total_sessions": n_sessions,
            "total_hours": round(total_hours, 2),
            "average_per_session": round(matched / n_sessions, 2) if n_sessions else None,
            "scans_per_hour": round(matched / total_hours, 2) if total_hours > 0 else None,
        },
        "sessions": scoped,
        "roles": [{"id": r, "label": ROLE_LABELS[r]} for r in ROLES],
    }
