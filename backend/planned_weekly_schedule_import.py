"""Bulk import helpers for planned weekly schedule (name match + shift parsing)."""

from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher
from typing import Any, Mapping, Sequence

from backend.planned_weekly_schedule import normalize_week_start, normalize_weekly_role, parse_weekly_roles, roles_to_storage

DAY_INDEX = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
_SHIFT_RE = re.compile(
    r"^(?P<day>sun|mon|tue|wed|thu|fri|sat)\s+"
    r"(?P<start_h>\d{1,2})(?::(?P<start_m>\d{2}))?(?P<start_ampm>am|pm)"
    r"-"
    r"(?P<end_h>\d{1,2})(?::(?P<end_m>\d{2}))?(?P<end_ampm>am|pm)$",
    re.IGNORECASE,
)


def norm_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _name_tokens(value: str) -> list[str]:
    return [t for t in norm_name(value).split(" ") if t]


def _to_24h(hour: int, minute: int, ampm: str) -> str:
    h = int(hour) % 12
    if ampm.lower() == "pm":
        h += 12
    return f"{h:02d}:{int(minute or 0):02d}"


def parse_shift_label(label: str) -> tuple[int, str, str] | None:
    """Parse 'Tue 6am-3pm' → (day_of_week, start HH:MM, end HH:MM)."""
    text = re.sub(r"\s+", " ", (label or "").strip())
    m = _SHIFT_RE.match(text)
    if not m:
        return None
    dow = DAY_INDEX[m.group("day").lower()]
    start = _to_24h(int(m.group("start_h")), int(m.group("start_m") or 0), m.group("start_ampm"))
    end = _to_24h(int(m.group("end_h")), int(m.group("end_m") or 0), m.group("end_ampm"))
    return dow, start, end


def sheet_role_to_planned_roles(sheet_role: str | None) -> list[str]:
    """Map spreadsheet role labels to planned schedule roles (sort / wash / fold)."""
    text = str(sheet_role or "").strip().lower()
    if not text:
        return ["fold"]
    roles: list[str] = []
    if "sort" in text:
        roles.append("sort")
    if "wash" in text:
        roles.append("wash")
    if "fold" in text:
        roles.append("fold")
    if roles:
        return roles
    mapped = normalize_weekly_role(text)
    return [mapped] if mapped else ["fold"]


def sheet_role_to_planned_role(sheet_role: str | None) -> str:
    return roles_to_storage(sheet_role_to_planned_roles(sheet_role))


def _score_name(query: str, candidate: str) -> float:
    q_norm = norm_name(query)
    c_norm = norm_name(candidate)
    if not q_norm or not c_norm:
        return 0.0
    if q_norm == c_norm:
        return 1.0
    q_tokens = _name_tokens(query)
    c_tokens = _name_tokens(candidate)
    if q_tokens and all(t in c_tokens for t in q_tokens):
        return 0.95
    if c_tokens and all(t in q_tokens for t in c_tokens):
        return 0.92
    q_last = q_tokens[-1] if q_tokens else ""
    c_last = c_tokens[-1] if c_tokens else ""
    if q_last and q_last == c_last:
        ratio = SequenceMatcher(None, q_norm, c_norm).ratio()
        return max(ratio, 0.88)
    return SequenceMatcher(None, q_norm, c_norm).ratio()


def match_worker_name(
    query: str,
    workers: Sequence[Mapping[str, Any]],
    *,
    min_score: float = 0.84,
) -> tuple[int | None, str | None, float]:
    """Return (user_id, matched_display_name, score) or (None, None, best_score)."""
    best_uid: int | None = None
    best_name: str | None = None
    best_score = 0.0
    for worker in workers or []:
        uid = int(worker.get("user_id") or 0)
        if uid <= 0:
            continue
        display = (
            worker.get("display_name")
            or worker.get("worker_name")
            or f"{worker.get('first_name') or ''} {worker.get('last_name') or ''}".strip()
        )
        score = _score_name(query, display)
        if score > best_score:
            best_score = score
            best_uid = uid
            best_name = display
    if best_uid and best_score >= min_score:
        return best_uid, best_name, best_score
    return None, None, best_score


def normalize_import_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Expand employee rows with shift strings into flat entry payloads."""
    out: list[dict[str, Any]] = []
    for row in rows or []:
        name = str(row.get("name") or row.get("employee") or "").strip()
        if not name:
            continue
        sheet_role = str(row.get("sheet_role") or row.get("role") or "").strip()
        roles = parse_weekly_roles(
            row.get("planned_role") or row.get("roles") or sheet_role_to_planned_roles(sheet_role)
        )
        role = roles_to_storage(roles)
        shifts = row.get("shifts") or []
        for shift in shifts:
            if isinstance(shift, str):
                parsed = parse_shift_label(shift)
                if not parsed:
                    out.append({"name": name, "error": f"unparseable shift: {shift!r}"})
                    continue
                dow, start, end = parsed
            elif isinstance(shift, Mapping):
                dow_raw = shift.get("day_of_week")
                if dow_raw is None:
                    day_label = str(shift.get("day") or "").strip().lower()[:3]
                    dow_raw = DAY_INDEX.get(day_label)
                if dow_raw is None:
                    out.append({"name": name, "error": f"missing day in shift: {shift!r}"})
                    continue
                start = str(shift.get("start_time") or shift.get("start") or "").strip()
                end = str(shift.get("end_time") or shift.get("end") or "").strip()
                if not start or not end:
                    label = shift.get("label")
                    if label:
                        parsed = parse_shift_label(str(label))
                        if parsed:
                            dow_raw, start, end = parsed
                dow = int(dow_raw)
            else:
                out.append({"name": name, "error": f"invalid shift type: {shift!r}"})
                continue
            out.append(
                {
                    "name": name,
                    "sheet_role": sheet_role,
                    "role": role,
                    "roles": roles,
                    "day_of_week": dow,
                    "start_time": start,
                    "end_time": end,
                    "break_minutes": int(shift.get("break_minutes") or 0) if isinstance(shift, Mapping) else 0,
                }
            )
    return out


def _bulk_insert_entries(
    cursor,
    organization_id: int,
    *,
    week_start: date,
    payloads: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    from backend.daily_shift_roster import parse_time_value
    from backend.planned_weekly_schedule import ensure_planned_weekly_schedule_table, list_week_entries

    if not payloads:
        return []
    ensure_planned_weekly_schedule_table(cursor)
    oid = int(organization_id)
    params = []
    for payload in payloads:
        start = parse_time_value(payload.get("start_time"))
        end = parse_time_value(payload.get("end_time"))
        role = roles_to_storage(parse_weekly_roles(payload.get("role") or payload.get("roles")))
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
            )
        )
    cursor.executemany(
        """
        INSERT INTO planned_weekly_schedule_entries (
            organization_id, week_start, user_id, day_of_week,
            role, start_time, end_time, break_minutes
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        params,
    )
    return list_week_entries(cursor, oid, week_start=week_start)


def import_planned_weekly_schedule(
    conn,
    cursor,
    organization_id: int,
    *,
    week_start: date | str,
    rows: Sequence[Mapping[str, Any]],
    workers: Sequence[Mapping[str, Any]] | None = None,
    replace_existing: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    from backend.planned_weekly_schedule import _load_workers, ensure_planned_weekly_schedule_table

    oid = int(organization_id)
    week = normalize_week_start(week_start)
    if not isinstance(week, date):
        raise ValueError("week_start must be YYYY-MM-DD")

    worker_list = list(workers) if workers is not None else _load_workers(conn, oid)
    valid_user_ids = {int(w.get("user_id") or 0) for w in worker_list if int(w.get("user_id") or 0) > 0}
    flat = normalize_import_rows(rows)

    deleted = 0
    if replace_existing and not dry_run:
        ensure_planned_weekly_schedule_table(cursor)
        cursor.execute(
            """
            DELETE FROM planned_weekly_schedule_entries
            WHERE organization_id = %s AND week_start = %s
            """,
            (oid, week),
        )
        deleted = int(cursor.rowcount or 0)

    created: list[dict[str, Any]] = []
    name_failures: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    match_map: dict[str, dict[str, Any]] = {}
    pending_payloads: list[dict[str, Any]] = []

    for item in flat:
        if item.get("error"):
            parse_errors.append(item)
            continue
        name = item["name"]
        if name not in match_map:
            uid, matched, score = match_worker_name(name, worker_list)
            match_map[name] = {"user_id": uid, "matched_name": matched, "score": round(score, 3)}
            if not uid:
                name_failures.append({"name": name, "best_score": round(score, 3)})
        uid = match_map[name]["user_id"]
        if not uid:
            continue
        if uid not in valid_user_ids:
            parse_errors.append({"name": name, "error": "worker not found in payroll profiles", "user_id": uid})
            continue
        payload = {
            "user_id": uid,
            "day_of_week": item["day_of_week"],
            "role": item["role"],
            "start_time": item["start_time"],
            "end_time": item["end_time"],
            "break_minutes": item.get("break_minutes") or 0,
            "source_name": name,
        }
        if dry_run:
            created.append({"dry_run": True, **payload})
            continue
        pending_payloads.append(payload)

    if pending_payloads and not dry_run:
        created = _bulk_insert_entries(cursor, oid, week_start=week, payloads=pending_payloads)

    return {
        "organization_id": oid,
        "week_start": str(week),
        "dry_run": dry_run,
        "replace_existing": replace_existing,
        "deleted_existing": deleted,
        "created_count": len(created),
        "created": created,
        "name_mappings": match_map,
        "name_failures": name_failures,
        "parse_errors": parse_errors,
    }


# VeeWash org 3 — week of 2026-06-14 (Sun–Sat), from manager spreadsheet.
VEEWASH_WEEK_2026_06_14: list[dict[str, Any]] = [
    {
        "name": "Francis Arita",
        "sheet_role": "Wash, Sort & Fold",
        "shifts": ["Tue 6am-3pm", "Wed 6am-3pm", "Fri 6am-3pm", "Sat 6am-3pm"],
    },
    {
        "name": "Jennifer Farfan",
        "sheet_role": "Wash, Sort & Fold",
        "shifts": ["Sun 8am-4pm", "Mon 8am-4pm", "Tue 6am-3pm", "Wed 6am-3pm", "Thu 8am-4pm"],
    },
    {
        "name": "Maria Perez",
        "sheet_role": "Wash, Sort & Fold",
        "shifts": [
            "Mon 7am-3pm",
            "Tue 9am-4pm",
            "Wed 7am-3pm",
            "Thu 9am-4pm",
            "Fri 9am-4pm",
            "Sat 7am-3pm",
        ],
    },
    {
        "name": "Varun Kumar Mongia",
        "sheet_role": "Wash & Fold",
        "shifts": ["Mon 9am-4pm", "Fri 9am-4pm", "Sat 9am-4pm"],
    },
    {
        "name": "Jaspreet Singh",
        "sheet_role": "Wash & Fold",
        "shifts": ["Thu 9am-4pm", "Fri 9am-4pm", "Sat 9am-4pm"],
    },
    {
        "name": "Paola Almiron",
        "sheet_role": "Sort & Fold",
        "shifts": ["Sun 7am-3pm", "Sat 9am-4pm"],
    },
    {
        "name": "Alec Coaxum",
        "sheet_role": "Fold",
        "shifts": ["Sun 9am-4pm", "Mon 9am-4pm", "Tue 7am-3pm", "Wed 9am-4pm"],
    },
    {
        "name": "Evelin Delgado Hernandez",
        "sheet_role": "Fold",
        "shifts": ["Tue 9am-4pm", "Thu 9am-4pm", "Fri 9am-4pm"],
    },
    {
        "name": "Jahangir Raza",
        "sheet_role": "Fold",
        "shifts": ["Sun 9am-4pm", "Mon 2pm-10pm", "Tue 9am-4pm", "Thu 2pm-10pm"],
    },
    {
        "name": "Angelica Angelica",
        "sheet_role": "Fold",
        "shifts": ["Mon 9am-4pm", "Sat 9am-4pm"],
    },
    {
        "name": "Tarannum Mithala",
        "sheet_role": "Fold",
        "shifts": ["Thu 9am-4pm"],
    },
    {
        "name": "Guiying Lin",
        "sheet_role": "Fold",
        "shifts": ["Sun 4pm-10pm", "Mon 4pm-10pm", "Tue 4pm-10pm", "Fri 4pm-10pm", "Sat 4pm-10pm"],
    },
]
