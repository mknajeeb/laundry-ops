"""Daily shift roster — end-of-day labor recording (org + date scoped)."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any, Mapping, Sequence

from backend.ta_helpers import table_exists

VALID_ROLES = frozenset({"folder", "operator"})
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


def ensure_daily_shift_roster_table(cursor) -> None:
    if table_exists(cursor, "daily_shift_roster_entries"):
        _ensure_end_time_nullable(cursor)
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_shift_roster_entries (
          id INT AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          roster_date DATE NOT NULL,
          employee_name VARCHAR(255) NOT NULL,
          role VARCHAR(16) NOT NULL DEFAULT 'folder',
          start_time TIME NOT NULL,
          end_time TIME NULL,
          break_minutes INT NOT NULL DEFAULT 0,
          rate DECIMAL(10,2) NOT NULL DEFAULT 0.00,
          notes TEXT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP,
          INDEX idx_dsr_org_date (organization_id, roster_date),
          INDEX idx_dsr_org_date_role (organization_id, roster_date, role)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _ensure_end_time_nullable(cursor) -> None:
    try:
        cursor.execute("SHOW COLUMNS FROM daily_shift_roster_entries LIKE 'end_time'")
        row = cursor.fetchone()
        if not row:
            return
        null_flag = row.get("Null") if isinstance(row, dict) else (row[2] if len(row) > 2 else "NO")
        if str(null_flag or "").upper() == "NO":
            cursor.execute("ALTER TABLE daily_shift_roster_entries MODIFY end_time TIME NULL")
    except Exception:
        return


def roster_entry_match_key(employee_name: Any, start_time: Any) -> tuple[str, str]:
    name = normalize_employee_name(employee_name).casefold()
    parsed = parse_time_value(start_time)
    start_key = parsed.strftime("%H:%M") if parsed else str(start_time or "").strip()
    return name, start_key


def _is_shift_open(data: Mapping[str, Any]) -> bool:
    if bool(data.get("shift_open")):
        return True
    end_raw = data.get("end_time")
    if end_raw is None:
        return True
    if isinstance(end_raw, str) and not str(end_raw).strip():
        return True
    return False


def parse_time_value(raw: Any) -> time | None:
    if raw is None:
        return None
    if isinstance(raw, time):
        return raw
    if isinstance(raw, datetime):
        return raw.time()
    if isinstance(raw, timedelta):
        total = int(raw.total_seconds())
        hours, rem = divmod(total, 3600)
        minutes, seconds = divmod(rem, 60)
        return time(hours % 24, minutes, seconds)
    text = str(raw).strip()
    if not text:
        return None
    m = _TIME_RE.match(text)
    if not m:
        return None
    h, mi, sec = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    if h > 23 or mi > 59 or sec > 59:
        return None
    return time(h, mi, sec)


def normalize_role(raw: Any) -> str | None:
    role = str(raw or "").strip().lower()
    if role in VALID_ROLES:
        return role
    if role == "folders":
        return "folder"
    if role == "operators":
        return "operator"
    return None


def normalize_employee_name(raw: Any) -> str:
    return str(raw or "").strip()


def calc_hours(
    start_time: time,
    end_time: time,
    break_minutes: int = 0,
) -> float:
    """Hours worked = (end - start - break minutes), rounded to 4 decimals."""
    start_dt = datetime.combine(date.min, start_time)
    end_dt = datetime.combine(date.min, end_time)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    worked_sec = max(0, int((end_dt - start_dt).total_seconds()) - max(0, int(break_minutes)) * 60)
    return round(worked_sec / 3600.0, 4)


def calc_cost(hours: float, rate: float) -> float:
    return round(float(hours) * float(rate), 2)


def _time_to_str(value: Any) -> str | None:
    parsed = parse_time_value(value)
    if parsed is None:
        return None
    return parsed.strftime("%H:%M")


def _serialize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return serialize_roster_entry_data(row)


def serialize_roster_entry_data(data: Mapping[str, Any]) -> dict[str, Any]:
    start = parse_time_value(data.get("start_time"))
    shift_open = _is_shift_open(data)
    end = None if shift_open else parse_time_value(data.get("end_time"))
    break_min = max(0, int(data.get("break_minutes") or 0))
    rate = round(float(data.get("rate") or 0), 2)
    hours: float | None = None
    cost: float | None = None
    if start and end and not shift_open:
        hours = calc_hours(start, end, break_min)
        cost = calc_cost(hours, rate)
    role = normalize_role(data.get("role")) or "folder"
    out: dict[str, Any] = {
        "employee_name": normalize_employee_name(data.get("employee_name")),
        "role": role,
        "start_time": _time_to_str(start),
        "end_time": _time_to_str(end) if end else None,
        "break_minutes": break_min,
        "rate": rate,
        "notes": str(data.get("notes") or "").strip() or None,
        "shift_open": shift_open,
        "hours": hours,
        "cost": cost,
    }
    if data.get("id"):
        out["id"] = int(data.get("id") or 0)
    if data.get("organization_id"):
        out["organization_id"] = int(data.get("organization_id") or 0)
    if data.get("roster_date"):
        out["roster_date"] = str(data.get("roster_date") or "")
    return out


def _validate_entry_payload(data: Mapping[str, Any], *, partial: bool = False) -> tuple[dict[str, Any] | None, str | None]:
    out: dict[str, Any] = {}
    if not partial or "employee_name" in data:
        name = normalize_employee_name(data.get("employee_name"))
        if not name:
            return None, "employee_name is required"
        out["employee_name"] = name
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
    if not partial or "end_time" in data or "shift_open" in data:
        open_shift = _is_shift_open(data)
        if open_shift:
            out["shift_open"] = True
            out["end_time"] = None
        else:
            end = parse_time_value(data.get("end_time"))
            if end is None:
                return None, "end_time is required (HH:MM) unless shift is open"
            out["end_time"] = end
            out["shift_open"] = False
    if (
        "start_time" in out
        and "end_time" in out
        and out.get("end_time") is not None
        and not out.get("shift_open")
    ):
        if calc_hours(out["start_time"], out["end_time"], int(data.get("break_minutes") or 0)) <= 0:
            return None, "hours must be greater than zero"
    if "break_minutes" in data or not partial:
        try:
            break_min = max(0, int(data.get("break_minutes") or 0))
        except (TypeError, ValueError):
            return None, "break_minutes must be a non-negative integer"
        out["break_minutes"] = break_min
    if "rate" in data or not partial:
        try:
            out["rate"] = round(max(0.0, float(data.get("rate") or 0)), 2)
        except (TypeError, ValueError):
            return None, "rate must be a number"
    if "notes" in data:
        notes = str(data.get("notes") or "").strip()
        out["notes"] = notes or None
    return out, None


def list_roster_entries(
    cursor,
    organization_id: int,
    *,
    roster_date: date,
) -> list[dict[str, Any]]:
    ensure_daily_shift_roster_table(cursor)
    cursor.execute(
        """
        SELECT id, organization_id, roster_date, employee_name, role,
               start_time, end_time, break_minutes, rate, notes
        FROM daily_shift_roster_entries
        WHERE organization_id = %s AND roster_date = %s
        ORDER BY role ASC, employee_name ASC, start_time ASC, id ASC
        """,
        (int(organization_id), roster_date),
    )
    rows = cursor.fetchall() or []
    return [_serialize_row(r) for r in rows if isinstance(r, dict)]


def get_roster_entry(
    cursor,
    organization_id: int,
    entry_id: int,
) -> dict[str, Any] | None:
    ensure_daily_shift_roster_table(cursor)
    cursor.execute(
        """
        SELECT id, organization_id, roster_date, employee_name, role,
               start_time, end_time, break_minutes, rate, notes
        FROM daily_shift_roster_entries
        WHERE organization_id = %s AND id = %s
        LIMIT 1
        """,
        (int(organization_id), int(entry_id)),
    )
    row = cursor.fetchone()
    if not row or not isinstance(row, dict):
        return None
    return _serialize_row(row)


def create_roster_entry(
    cursor,
    organization_id: int,
    *,
    roster_date: date,
    data: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    ensure_daily_shift_roster_table(cursor)
    payload, err = _validate_entry_payload(data)
    if err:
        return None, err
    cursor.execute(
        """
        INSERT INTO daily_shift_roster_entries (
            organization_id, roster_date, employee_name, role,
            start_time, end_time, break_minutes, rate, notes
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            roster_date,
            payload["employee_name"],
            payload["role"],
            payload["start_time"],
            payload["end_time"],
            payload["break_minutes"],
            payload["rate"],
            payload.get("notes"),
        ),
    )
    entry_id = int(cursor.lastrowid or 0)
    return get_roster_entry(cursor, organization_id, entry_id), None


def update_roster_entry(
    cursor,
    organization_id: int,
    entry_id: int,
    data: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    ensure_daily_shift_roster_table(cursor)
    existing = get_roster_entry(cursor, organization_id, entry_id)
    if not existing:
        return None, "roster entry not found"
    merged = {
        "employee_name": existing["employee_name"],
        "role": existing["role"],
        "start_time": existing["start_time"],
        "end_time": existing.get("end_time"),
        "shift_open": existing.get("shift_open"),
        "break_minutes": existing["break_minutes"],
        "rate": existing["rate"],
        "notes": existing.get("notes"),
        **dict(data or {}),
    }
    payload, err = _validate_entry_payload(merged)
    if err:
        return None, err
    cursor.execute(
        """
        UPDATE daily_shift_roster_entries
        SET employee_name=%s, role=%s, start_time=%s, end_time=%s,
            break_minutes=%s, rate=%s, notes=%s
        WHERE organization_id=%s AND id=%s
        """,
        (
            payload["employee_name"],
            payload["role"],
            payload["start_time"],
            payload["end_time"],
            payload["break_minutes"],
            payload["rate"],
            payload.get("notes"),
            int(organization_id),
            int(entry_id),
        ),
    )
    return get_roster_entry(cursor, organization_id, entry_id), None


def delete_roster_entry(
    cursor,
    organization_id: int,
    entry_id: int,
) -> tuple[bool, str | None]:
    ensure_daily_shift_roster_table(cursor)
    existing = get_roster_entry(cursor, organization_id, entry_id)
    if not existing:
        return False, "roster entry not found"
    cursor.execute(
        "DELETE FROM daily_shift_roster_entries WHERE organization_id=%s AND id=%s",
        (int(organization_id), int(entry_id)),
    )
    return True, None


def build_roster_payload(
    cursor,
    organization_id: int,
    *,
    roster_date: date,
) -> dict[str, Any]:
    from backend.daily_shift_roster_payroll import build_payroll_prefill_entries

    entries = list_roster_entries(cursor, organization_id, roster_date=roster_date)
    total_hours = round(
        sum(float(e.get("hours") or 0) for e in entries if e.get("hours") is not None),
        4,
    )
    total_cost = round(
        sum(float(e.get("cost") or 0) for e in entries if e.get("cost") is not None),
        2,
    )
    conn = cursor.connection if hasattr(cursor, "connection") else None
    payroll_prefill: list[dict[str, Any]] = []
    payroll_record_count = 0
    if conn is not None:
        payroll_prefill = build_payroll_prefill_entries(
            conn, organization_id, roster_date=roster_date
        )
        payroll_record_count = len(payroll_prefill)

    has_roster = bool(entries)
    if has_roster:
        message = None
    elif payroll_record_count:
        message = "Payroll records found. Review and save today's roster."
    else:
        message = "No labor roster recorded for this date."

    return {
        "roster_date": roster_date.isoformat(),
        "has_roster": has_roster,
        "entries": entries,
        "payroll_prefill": payroll_prefill if not has_roster else [],
        "payroll_record_count": payroll_record_count,
        "summary": {
            "employee_count": len(entries),
            "total_hours": total_hours,
            "total_cost": total_cost,
        },
        "message": message,
    }
