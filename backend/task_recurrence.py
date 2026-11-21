"""Recurring requirements on the existing task definition and weekly schedule.

Task definition (weekly_schedule_roles) says what the activity is.
Recurrence on that definition says how often it is required.
task_schedule_occurrences is the stable weekly slot. Employee placement stays
on planned_weekly_schedule_responsibilities. Completed and skipped slots are
not rewritten when the definition changes later.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.planned_weekly_schedule import normalize_week_start
from backend.ta_helpers import invalidate_table_schema, once_per_cursor, table_exists

OCCURRENCES = "task_schedule_occurrences"
MACHINE_CLEANINGS = "task_machine_cleanings"

PROTECTED_STATUSES = frozenset({"completed", "verified", "skipped", "cancelled"})
OPEN_STATUSES = frozenset({"due", "scheduled"})


def normalize_recurrence(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, Mapping) else {}
    mode = str(data.get("mode") or "manual").strip().lower()
    if mode not in ("manual", "recurring"):
        mode = "manual"
    try:
        frequency = int(data.get("weekly_frequency") or 1)
    except (TypeError, ValueError):
        frequency = 1
    frequency = min(14, max(1, frequency))
    weekdays: list[int] = []
    for item in data.get("weekdays") or []:
        try:
            dow = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= dow <= 6 and dow not in weekdays:
            weekdays.append(dow)
    window = data.get("time_window") if isinstance(data.get("time_window"), Mapping) else None
    if window:
        start = str(window.get("start") or "").strip()[:5]
        end = str(window.get("end") or "").strip()[:5]
        window = {"start": start, "end": end} if start or end else None
    assignees: list[int] = []
    for item in data.get("assignee_user_ids") or []:
        try:
            uid = int(item)
        except (TypeError, ValueError):
            continue
        if uid > 0 and uid not in assignees:
            assignees.append(uid)
    exceptions: list[dict[str, str]] = []
    for item in data.get("temporary_exceptions") or []:
        if not isinstance(item, Mapping):
            continue
        day = str(item.get("date") or "")[:10]
        reason = " ".join(str(item.get("reason") or "").split())[:255]
        if day and reason:
            exceptions.append({"date": day, "reason": reason})
    role = " ".join(str(data.get("assignee_role") or "").split())[:40] or None
    return {
        "mode": mode,
        "weekly_frequency": frequency,
        "weekdays": weekdays,
        "time_window": window,
        "effective_start": _ymd(data.get("effective_start")),
        "effective_end": _ymd(data.get("effective_end")),
        "assignee_user_ids": assignees,
        "assignee_role": role,
        "paused": bool(data.get("paused")),
        "active": bool(data.get("active", True)),
        "temporary_exceptions": exceptions,
    }


def _ymd(raw: Any) -> str | None:
    text = str(raw or "").strip()[:10]
    if len(text) != 10:
        return None
    try:
        date.fromisoformat(text)
    except ValueError:
        return None
    return text


def schedule_dow(day: date) -> int:
    """Sunday = 0, matching the weekly schedule."""
    return (day.weekday() + 1) % 7


def plan_slots(recurrence: Mapping[str, Any], week_start: date) -> list[dict[str, Any]]:
    """Dates come only from selected weekdays. Extra frequency stays unscheduled."""
    rule = normalize_recurrence(recurrence)
    if rule["mode"] != "recurring" or not rule["active"] or rule["paused"]:
        return []
    week_end = week_start + timedelta(days=6)
    if rule["effective_start"] and date.fromisoformat(rule["effective_start"]) > week_end:
        return []
    if rule["effective_end"] and date.fromisoformat(rule["effective_end"]) < week_start:
        return []
    exception_days = {item["date"] for item in rule["temporary_exceptions"]}
    slots: list[dict[str, Any]] = []
    for dow in rule["weekdays"]:
        day = week_start + timedelta(days=dow)
        if rule["effective_start"] and day < date.fromisoformat(rule["effective_start"]):
            continue
        if rule["effective_end"] and day > date.fromisoformat(rule["effective_end"]):
            continue
        if day.isoformat() in exception_days:
            continue
        slots.append({"day_of_week": dow, "slot_index": len(slots) + 1, "scheduled": True})
    target = rule["weekly_frequency"]
    while len(slots) < target:
        slots.append({"day_of_week": None, "slot_index": len(slots) + 1, "scheduled": False})
    return slots[: max(target, len(rule["weekdays"]))] if rule["weekdays"] else slots


def occurrence_key(task_code: str, week_start: date, slot: Mapping[str, Any]) -> str:
    day = "open" if slot.get("day_of_week") is None else str(int(slot["day_of_week"]))
    return f"{task_code}:{week_start.isoformat()}:{day}:{int(slot.get('slot_index') or 1)}"


def apply_generation(
    existing: Sequence[Mapping[str, Any]],
    planned: Sequence[Mapping[str, Any]],
    *,
    task_code: str,
    week_start: date,
) -> list[dict[str, Any]]:
    """Return only new slots. Existing keys, including completed and skipped, stay."""
    known = {str(row.get("recurrence_key") or "") for row in existing}
    created: list[dict[str, Any]] = []
    for slot in planned:
        key = occurrence_key(task_code, week_start, slot)
        if key in known:
            continue
        created.append(
            {
                "task_code": task_code,
                "week_start": week_start.isoformat(),
                "day_of_week": slot.get("day_of_week"),
                "slot_index": int(slot["slot_index"]),
                "recurrence_key": key,
                "status": "scheduled" if slot.get("scheduled") else "due",
            }
        )
        known.add(key)
    return created


def reschedule_slot(row: Mapping[str, Any], day_of_week: int, reason: str) -> dict[str, Any]:
    if str(row.get("status") or "") in {"completed", "verified"}:
        raise ValueError("A completed occurrence cannot be replaced by a new requirement")
    updated = dict(row)
    updated["day_of_week"] = int(day_of_week)
    updated["status"] = "scheduled"
    updated["schedule_reason"] = " ".join(str(reason or "").split())[:255]
    updated["recurrence_key"] = row.get("recurrence_key")
    return updated


def skip_slot(row: Mapping[str, Any], reason: str) -> dict[str, Any]:
    text = " ".join(str(reason or "").split())
    if not text:
        raise ValueError("A skip reason is required")
    if str(row.get("status") or "") in {"completed", "verified"}:
        raise ValueError("A completed occurrence cannot be skipped")
    updated = dict(row)
    updated["status"] = "skipped"
    updated["skip_reason"] = text[:255]
    return updated


def unique_machine_codes(selected: Sequence[Any]) -> list[str]:
    """One task occurrence records each machine once, in selection order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in selected or []:
        if isinstance(item, Mapping):
            code = str(item.get("code") or item.get("id") or "").strip()
        else:
            code = str(item or "").strip()
        if not code or code.lower() in seen:
            continue
        seen.add(code.lower())
        out.append(code)
    return out


def machine_codes_from_completion(completion_input: Any, *, machine_kind: str | None = None) -> list[str]:
    values = {}
    if isinstance(completion_input, Mapping):
        values = completion_input.get("values") if isinstance(completion_input.get("values"), Mapping) else completion_input
    found: list[str] = []
    for key, raw in (values or {}).items():
        if isinstance(raw, list):
            found.extend(unique_machine_codes(raw))
        elif "machine" in str(key) and isinstance(raw, str) and raw.strip():
            found.extend(unique_machine_codes([part.strip() for part in raw.split(",")]))
    return unique_machine_codes(found)


def exclusion_covers(exclusion: Mapping[str, Any], week_start: date) -> bool:
    start = _ymd(exclusion.get("effective_start"))
    end = _ymd(exclusion.get("effective_end"))
    if not start or date.fromisoformat(start) > week_start:
        return False
    if end and date.fromisoformat(end) < week_start:
        return False
    return True


def weekly_task_progress(
    *,
    frequency: int,
    occurrences: Sequence[Mapping[str, Any]],
    today: date,
) -> dict[str, int]:
    completed = 0
    verified = 0
    pending = 0
    skipped = 0
    overdue = 0
    for row in occurrences:
        status = str(row.get("status") or "")
        if status == "verified":
            verified += 1
            completed += 1
        elif status in ("completed", "pending_verification"):
            completed += 1
            if status == "pending_verification":
                pending += 1
        elif status == "skipped":
            skipped += 1
        else:
            dow = row.get("day_of_week")
            week = _ymd(row.get("week_start"))
            if dow is not None and week:
                day = date.fromisoformat(week) + timedelta(days=int(dow))
                if day < today and status in OPEN_STATUSES:
                    overdue += 1
    required = max(0, int(frequency or 0))
    return {
        "required": required,
        "completed": completed,
        "verified": verified,
        "pending_verification": pending,
        "skipped": skipped,
        "overdue": overdue,
        "remaining": max(0, required - completed - skipped),
    }


def machine_week_targets(
    machines: Sequence[Mapping[str, Any]],
    cleanings: Sequence[Mapping[str, Any]],
    exclusions: Sequence[Mapping[str, Any]],
    *,
    frequency: int,
    week_start: date,
) -> dict[str, Any]:
    """Each eligible machine has its own frequency. One shared occurrence counts once per machine."""
    excluded_ids = set()
    for row in exclusions:
        if exclusion_covers(row, week_start):
            excluded_ids.add(str(row.get("machine_code") or ""))
    eligible = [
        row
        for row in machines
        if row.get("cleaning_eligible", True)
        and str(row.get("operational_status") or "operational") != "retired"
        and str(row.get("machine_code") or "") not in excluded_ids
    ]
    seen: set[tuple[str, str]] = set()
    completed_by: dict[str, int] = {}
    verified_by: dict[str, int] = {}
    employees: dict[str, list[int]] = {}
    for row in cleanings:
        code = str(row.get("machine_code") or "")
        occurrence = str(row.get("occurrence_key") or row.get("activity_id") or "")
        pair = (code, occurrence)
        if not code or pair in seen:
            continue
        seen.add(pair)
        completed_by[code] = completed_by.get(code, 0) + 1
        if row.get("verified"):
            verified_by[code] = verified_by.get(code, 0) + 1
        uid = row.get("user_id")
        if uid:
            employees.setdefault(code, [])
            if int(uid) not in employees[code]:
                employees[code].append(int(uid))
    per_machine = []
    required_total = 0
    completed_total = 0
    verified_total = 0
    freq = max(1, int(frequency or 1))
    for machine in eligible:
        code = str(machine.get("machine_code") or "")
        done = min(freq, completed_by.get(code, 0))
        verified = min(done, verified_by.get(code, 0))
        required_total += freq
        completed_total += done
        verified_total += verified
        per_machine.append(
            {
                "machine_code": code,
                "required": freq,
                "completed": done,
                "verified": verified,
                "remaining": max(0, freq - done),
                "employees": employees.get(code, []),
            }
        )
    return {
        "eligible_machines": len(eligible),
        "required": required_total,
        "completed": completed_total,
        "verified": verified_total,
        "remaining": max(0, required_total - completed_total),
        "machines": per_machine,
    }


@once_per_cursor("task_recurrence")
def ensure_recurrence_tables(cursor) -> None:
    if not table_exists(cursor, OCCURRENCES):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {OCCURRENCES} (
              id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              task_code VARCHAR(40) NOT NULL,
              week_start DATE NOT NULL,
              day_of_week TINYINT NULL,
              slot_index INT NOT NULL,
              recurrence_key VARCHAR(80) NOT NULL,
              status VARCHAR(32) NOT NULL DEFAULT 'due',
              assignment_group_id VARCHAR(36) NULL,
              skip_reason VARCHAR(255) NULL,
              schedule_reason VARCHAR(255) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_task_occ (organization_id, recurrence_key),
              INDEX idx_task_occ_week (organization_id, week_start, task_code)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        invalidate_table_schema(OCCURRENCES)
    if not table_exists(cursor, MACHINE_CLEANINGS):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {MACHINE_CLEANINGS} (
              id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              task_code VARCHAR(40) NOT NULL,
              machine_code VARCHAR(40) NOT NULL,
              occurrence_key VARCHAR(80) NOT NULL,
              activity_id BIGINT NULL,
              user_id INT NULL,
              completed_at DATETIME NULL,
              verified TINYINT(1) NOT NULL DEFAULT 0,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              UNIQUE KEY uq_machine_cleaning (organization_id, task_code, machine_code, occurrence_key)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        invalidate_table_schema(MACHINE_CLEANINGS)


def _week_date(raw: Any) -> date | None:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def list_occurrences(cursor, organization_id: int, week_start: date, task_code: str | None = None) -> list[dict[str, Any]]:
    ensure_recurrence_tables(cursor)
    sql = f"SELECT * FROM {OCCURRENCES} WHERE organization_id=%s AND week_start=%s"
    params: list[Any] = [int(organization_id), week_start]
    if task_code:
        sql += " AND task_code=%s"
        params.append(task_code)
    sql += " ORDER BY task_code, slot_index"
    cursor.execute(sql, tuple(params))
    return [dict(row) for row in (cursor.fetchall() or []) if isinstance(row, dict)]


def generate_week(cursor, organization_id: int, week_start: date, tasks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Insert missing slots for this week. Re-running does not add duplicates."""
    ensure_recurrence_tables(cursor)
    week = normalize_week_start(week_start) or week_start
    created: list[dict[str, Any]] = []
    for task in tasks:
        code = str(task.get("code") or "")
        rule = normalize_recurrence(task.get("recurrence"))
        if not code or rule["mode"] != "recurring":
            continue
        planned = plan_slots(rule, week)
        existing = list_occurrences(cursor, organization_id, week, code)
        fresh = apply_generation(existing, planned, task_code=code, week_start=week)
        for row in fresh:
            cursor.execute(
                f"""
                INSERT IGNORE INTO {OCCURRENCES} (
                  organization_id, task_code, week_start, day_of_week, slot_index,
                  recurrence_key, status
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    int(organization_id),
                    code,
                    week,
                    row["day_of_week"],
                    row["slot_index"],
                    row["recurrence_key"],
                    row["status"],
                ),
            )
            if int(getattr(cursor, "rowcount", 0) or 0):
                created.append(row)
                _assign_defined_employees(cursor, organization_id, week, code, rule, row)
    return created


def _assign_defined_employees(cursor, organization_id, week, code, rule, row) -> None:
    """Place the definition's employees on a dated slot through the existing responsibility table."""
    if row.get("day_of_week") is None or not rule.get("assignee_user_ids"):
        return
    from backend.planned_weekly_schedule_responsibilities import insert_responsibility_rows

    window = rule.get("time_window") or {}
    start = window.get("start") or None
    rows = []
    for uid in rule["assignee_user_ids"]:
        rows.append((uid, int(row["day_of_week"]), code, None, row["recurrence_key"][:36], "specific_time" if start else "anytime", start))
    insert_responsibility_rows(cursor, int(organization_id), week_start=week, rows=rows)


def record_machine_cleanings(
    cursor,
    *,
    organization_id: int,
    task_code: str,
    activity_id: int,
    user_id: int,
    completed_at: datetime,
    completion_input: Any,
    verified: bool = False,
) -> list[str]:
    """Store one row per machine on this activity. Repeating a machine does not add another cleaning."""
    codes = machine_codes_from_completion(completion_input)
    if not codes:
        return []
    ensure_recurrence_tables(cursor)
    occurrence_key = f"activity:{int(activity_id)}"
    for code in codes:
        cursor.execute(
            f"""
            INSERT IGNORE INTO {MACHINE_CLEANINGS} (
              organization_id, task_code, machine_code, occurrence_key, activity_id,
              user_id, completed_at, verified
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                int(organization_id),
                task_code,
                code,
                occurrence_key,
                int(activity_id),
                int(user_id) if user_id else None,
                completed_at,
                1 if verified else 0,
            ),
        )
    return codes
