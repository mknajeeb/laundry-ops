"""Map Payroll Management time records into daily shift roster prefill/import."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Mapping, Sequence

from backend.daily_shift_roster import (
    employee_names_match,
    normalize_employee_name,
    parse_time_value,
    roster_entry_match_key,
    roster_times_modified,
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
    conn,
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


def find_matching_payroll_record(
    entry: Mapping[str, Any],
    payroll_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Match a roster row to a payroll time record by name + clock-in time."""
    entry_name = normalize_employee_name(entry.get("employee_name"))
    if not entry_name:
        return None
    entry_start = parse_time_value(entry.get("start_time"))
    exact: list[dict[str, Any]] = []
    by_name: list[dict[str, Any]] = []
    for rec in payroll_records or []:
        if not isinstance(rec, dict):
            continue
        mapped = map_payroll_record_to_roster_data(rec)
        worker = mapped.get("employee_name")
        if not worker or not employee_names_match(entry_name, worker):
            continue
        rec_start = parse_time_value(mapped.get("start_time"))
        if entry_start and rec_start and entry_start == rec_start:
            exact.append(rec)
        else:
            by_name.append(rec)
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return exact[0]
    if len(by_name) == 1:
        return by_name[0]
    return None


def refresh_roster_from_payroll(
    cursor,
    organization_id: int,
    *,
    roster_date: date,
    conn,
) -> tuple[int, str | None]:
    """Update open roster rows from payroll clock-out data."""
    from backend.daily_shift_roster import list_roster_entries, update_roster_entry

    org = int(organization_id)
    if conn is None:
        return 0, "database connection required"

    entries = list_roster_entries(cursor, org, roster_date=roster_date)
    payroll_records = list_payroll_time_records_for_date(conn, org, roster_date=roster_date)
    updated = 0
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        if entry.get("excluded"):
            continue
        if not entry.get("shift_open") and entry.get("end_time"):
            continue
        if roster_times_modified(entry):
            continue

        rec = find_matching_payroll_record(entry, payroll_records)
        if not rec:
            continue
        mapped = map_payroll_record_to_roster_data(rec)
        if mapped.get("shift_open") or not mapped.get("end_time"):
            continue

        patch: dict[str, Any] = {
            "end_time": mapped["end_time"],
            "shift_open": False,
            "break_minutes": mapped.get("break_minutes", entry.get("break_minutes") or 0),
        }
        _, err = update_roster_entry(cursor, org, int(entry["id"]), patch)
        if err:
            return updated, err

        end_time = parse_time_value(mapped.get("end_time"))
        if end_time is not None:
            cursor.execute(
                """
                UPDATE daily_shift_roster_entries
                SET original_end_time=%s
                WHERE organization_id=%s AND id=%s
                """,
                (end_time, org, int(entry["id"])),
            )
        updated += 1
    return updated, None
