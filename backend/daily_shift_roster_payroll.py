"""Map Payroll Management time records into daily shift roster prefill/import."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Mapping

from backend.daily_shift_roster import (
    normalize_employee_name,
    parse_time_value,
    roster_entry_match_key,
    _time_to_str,
)

ROSTER_DEFAULT_W2_RATE = 19.5
ROSTER_DEFAULT_CONTRACTOR_RATE = 17.0


def _default_rate_for_category(category: str | None) -> float:
    cat = str(category or "").strip().lower()
    if cat in ("contractor_1099", "temp", "1099"):
        return ROSTER_DEFAULT_CONTRACTOR_RATE
    return ROSTER_DEFAULT_W2_RATE


def _clock_datetime_to_time(raw: Any) -> time | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.time()
    if isinstance(raw, time):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[1]
    if " " in text:
        text = text.split(" ", 1)[1]
    return parse_time_value(text[:8] if len(text) > 8 else text)


def list_payroll_time_records_for_date(
    conn,
    organization_id: int,
    *,
    roster_date: date,
) -> list[dict[str, Any]]:
    from backend.payroll_operations import list_time_records

    day = roster_date.isoformat()
    return list_time_records(
        conn,
        int(organization_id),
        from_date=day,
        to_date=day,
        limit=500,
    )


def map_payroll_record_to_roster_data(rec: Mapping[str, Any]) -> dict[str, Any]:
    status = str(rec.get("status") or "").strip().lower()
    clock_out = rec.get("clock_out_at")
    shift_open = status == "open" or not clock_out

    start = _clock_datetime_to_time(rec.get("clock_in_at"))
    end = None if shift_open else _clock_datetime_to_time(clock_out)

    break_sec = int(rec.get("break_seconds") or 0)
    break_min = max(0, break_sec // 60)

    rate = float(rec.get("hourly_rate") or 0)
    if rate <= 0:
        rate = _default_rate_for_category(rec.get("worker_category"))

    notes = str(rec.get("notes") or "").strip() or None

    return {
        "employee_name": normalize_employee_name(rec.get("worker_name")),
        "role": "folder",
        "start_time": _time_to_str(start) or "08:00",
        "end_time": _time_to_str(end) if end else None,
        "break_minutes": break_min,
        "rate": round(rate, 2),
        "notes": notes,
        "shift_open": shift_open,
        "payroll_time_record_id": int(rec.get("id") or 0) or None,
    }


def build_payroll_prefill_entries(
    conn,
    organization_id: int,
    *,
    roster_date: date,
) -> list[dict[str, Any]]:
    from backend.daily_shift_roster import serialize_roster_entry_data

    records = list_payroll_time_records_for_date(conn, organization_id, roster_date=roster_date)
    out: list[dict[str, Any]] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        mapped = map_payroll_record_to_roster_data(rec)
        if not mapped.get("employee_name"):
            continue
        serialized = serialize_roster_entry_data(mapped)
        serialized["prefill_source"] = "payroll"
        serialized["payroll_time_record_id"] = mapped.get("payroll_time_record_id")
        out.append(serialized)
    return out


def import_payroll_records_into_roster(
    cursor,
    organization_id: int,
    *,
    roster_date: date,
    existing_entries: list[dict[str, Any]] | None = None,
) -> tuple[int, list[dict[str, Any]], str | None]:
    from backend.daily_shift_roster import create_roster_entry, list_roster_entries

    org = int(organization_id)
    saved = existing_entries if existing_entries is not None else list_roster_entries(
        cursor, org, roster_date=roster_date
    )
    existing_keys = {
        roster_entry_match_key(e.get("employee_name"), e.get("start_time")) for e in saved
    }

    conn = cursor.connection if hasattr(cursor, "connection") else None
    if conn is None:
        return 0, saved, "database connection required"

    payroll_records = list_payroll_time_records_for_date(conn, org, roster_date=roster_date)
    added = 0
    for rec in payroll_records:
        if not isinstance(rec, dict):
            continue
        data = map_payroll_record_to_roster_data(rec)
        if not data.get("employee_name"):
            continue
        key = roster_entry_match_key(data["employee_name"], data["start_time"])
        if key in existing_keys:
            continue
        entry, err = create_roster_entry(cursor, org, roster_date=roster_date, data=data)
        if err:
            return added, saved, err
        if entry:
            added += 1
            saved.append(entry)
            existing_keys.add(key)
    return added, saved, None
