"""Planned weekly schedule — manager grid (org + week scoped, payroll user_id keyed)."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any, Mapping, Sequence

from backend.daily_shift_roster import calc_cost, calc_hours, parse_time_value
from backend.ta_helpers import table_exists

VALID_ROLES = frozenset(
    {
        "sort",
        "wash",
        "fold",
        "weigher",
        "dry",
        "post_weigh",
        "pt_sorter",
        "pt_washer",
        "pt_folder",
        "hd_operator",
        "hd_folder",
        "attendant",
        "non_rinse_folder",
        "lint_cleaning",
        "floor_cleaning",
        "washer_cleaning",
        "drop_off_customer",
        "self_service",
    }
)
CUSTOM_ROLE_PREFIX = "custom_"
_CUSTOM_ROLE_RE = re.compile(r"^custom_[a-z0-9_]{1,32}$")
ROLE_STORAGE_MAX = 64
LEGACY_ROLE_MAP = {
    "folder": "fold",
    "operator": "wash",
    "folders": "fold",
    "operators": "wash",
    "hd operator": "hd_operator",
    "hd_operator": "hd_operator",
    "hd-operator": "hd_operator",
    "hd folder": "hd_folder",
    "hd_folder": "hd_folder",
    "hd-folder": "hd_folder",
    "attendants": "attendant",
    "dryer": "dry",
    "drying": "dry",
    "post weigh": "post_weigh",
    "post-weigh": "post_weigh",
    "post weighing": "post_weigh",
    "non-rinse folder": "non_rinse_folder",
    "non rinse folder": "non_rinse_folder",
    "non_rinse_folder": "non_rinse_folder",
    "non-rinse-folder": "non_rinse_folder",
    "pt sorter": "pt_sorter",
    "pt_sorter": "pt_sorter",
    "pt-sorter": "pt_sorter",
    "pt sort": "pt_sorter",
    "pt_sort": "pt_sorter",
    "pt washer": "pt_washer",
    "pt_washer": "pt_washer",
    "pt-washer": "pt_washer",
    "pt wash": "pt_washer",
    "pt_wash": "pt_washer",
    "pt folder": "pt_folder",
    "pt_folder": "pt_folder",
    "pt-folder": "pt_folder",
    "pt fold": "pt_folder",
    "pt_fold": "pt_folder",
    "lint cleaning": "lint_cleaning",
    "lint-cleaning": "lint_cleaning",
    "floor cleaning": "floor_cleaning",
    "floor-cleaning": "floor_cleaning",
    "washer cleaning": "washer_cleaning",
    "washer-cleaning": "washer_cleaning",
    "drop off customer": "drop_off_customer",
    "drop-off customer": "drop_off_customer",
    "self service": "self_service",
    "self-service": "self_service",
}
ROLE_SORT_ORDER = (
    "sort",
    "wash",
    "weigher",
    "dry",
    "fold",
    "post_weigh",
    "pt_sorter",
    "pt_washer",
    "pt_folder",
    "hd_operator",
    "hd_folder",
    "non_rinse_folder",
    "attendant",
    "lint_cleaning",
    "floor_cleaning",
    "washer_cleaning",
    "drop_off_customer",
    "self_service",
)
HOUR_TRACKED_ROLES = frozenset({"wash", "sort", "fold", "pt_washer", "pt_sorter", "pt_folder"})
DAY_LABELS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


def is_schedule_role_code(code: Any) -> bool:
    text = str(code or "").strip().lower()
    return text in VALID_ROLES or bool(_CUSTOM_ROLE_RE.match(text))


def normalize_weekly_role(raw: Any) -> str | None:
    role = str(raw or "").strip().lower()
    if is_schedule_role_code(role):
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


def clear_future_planned_schedule_entries_for_user(
    cursor,
    organization_id: int,
    user_id: int,
    *,
    as_of: date,
) -> int:
    """
    Remove planned shifts on/after ``as_of`` (ET business date) for one worker.

    Past weeks and past days in the current week are left intact.
    """
    ensure_planned_weekly_schedule_table(cursor)
    oid = int(organization_id)
    uid = int(user_id)
    if not isinstance(as_of, date):
        raise ValueError("as_of must be a date")
    current_week = normalize_week_start(as_of)
    if not current_week:
        return 0

    deleted = 0
    cursor.execute(
        """
        DELETE FROM planned_weekly_schedule_entries
        WHERE organization_id = %s AND user_id = %s AND week_start > %s
        """,
        (oid, uid, current_week),
    )
    deleted += int(getattr(cursor, "rowcount", 0) or 0)

    days_from_sunday = (as_of - current_week).days
    if 0 <= days_from_sunday <= 6:
        cursor.execute(
            """
            DELETE FROM planned_weekly_schedule_entries
            WHERE organization_id = %s AND user_id = %s AND week_start = %s
              AND day_of_week >= %s
            """,
            (oid, uid, current_week, days_from_sunday),
        )
        deleted += int(getattr(cursor, "rowcount", 0) or 0)

    from backend.planned_weekly_schedule_responsibilities import (
        clear_future_responsibilities_for_user,
    )

    clear_future_responsibilities_for_user(
        cursor,
        oid,
        uid,
        current_week=current_week,
        from_day_of_week=days_from_sunday if 0 <= days_from_sunday <= 6 else None,
    )

    # Drop future-week exclusions so none workers do not linger as excluded rows.
    ensure_planned_weekly_schedule_exclusions_table(cursor)
    cursor.execute(
        """
        DELETE FROM planned_weekly_schedule_exclusions
        WHERE organization_id = %s AND user_id = %s AND week_start >= %s
        """,
        (oid, uid, current_week),
    )
    return deleted


def schedulable_worker_user_ids(
    conn,
    organization_id: int,
    workers: Sequence[Mapping[str, Any]] | None = None,
) -> set[int]:
    """Active schedule-grid workers whose Mapping affiliation is not ``none``."""
    from backend.payroll_employer_affiliation import (
        EMPLOYER_AFFILIATION_NONE,
        _organization_slug,
        employer_affiliation_from_flags,
    )

    org_slug = _organization_slug(conn, int(organization_id))
    rows = list(workers) if workers is not None else _load_workers(conn, int(organization_id))
    out: set[int] = set()
    for worker in rows:
        uid = int(worker.get("user_id") or 0)
        if uid <= 0:
            continue
        if employer_affiliation_from_flags(worker, organization_slug=org_slug) == EMPLOYER_AFFILIATION_NONE:
            continue
        out.add(uid)
    return out


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


def _ensure_role_assignments_column(cursor) -> None:
    try:
        cursor.execute(
            "SHOW COLUMNS FROM planned_weekly_schedule_entries LIKE 'role_assignments'"
        )
        if cursor.fetchone():
            return
        cursor.execute(
            "ALTER TABLE planned_weekly_schedule_entries "
            "ADD COLUMN role_assignments TEXT NULL DEFAULT NULL"
        )
    except Exception:
        return


def _ensure_break_slots_column(cursor) -> None:
    try:
        cursor.execute(
            "SHOW COLUMNS FROM planned_weekly_schedule_entries LIKE 'break_slots'"
        )
        if cursor.fetchone():
            return
        cursor.execute(
            "ALTER TABLE planned_weekly_schedule_entries "
            "ADD COLUMN break_slots TEXT NULL DEFAULT NULL"
        )
    except Exception:
        return


def ensure_planned_weekly_schedule_table(cursor) -> None:
    if table_exists(cursor, "planned_weekly_schedule_entries"):
        _ensure_role_column_width(cursor)
        _ensure_employer_affiliation_column(cursor)
        _ensure_role_assignments_column(cursor)
        _ensure_break_slots_column(cursor)
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
          role_assignments TEXT NULL DEFAULT NULL,
          break_slots TEXT NULL DEFAULT NULL,
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


MAX_BREAK_SLOTS = 6


def parse_break_slots_storage(raw: Any) -> list[dict[str, str]]:
    """Decode ``break_slots`` JSON: [{start_time, end_time}] planned break windows inside the shift."""
    if raw in (None, ""):
        return []
    data: Any = raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, Mapping):
            continue
        start = _time_to_str(item.get("start_time"))
        end = _time_to_str(item.get("end_time"))
        if start and end and start != end:
            out.append({"start_time": start, "end_time": end})
    return out


def break_slots_storage(slots: Sequence[Mapping[str, Any]] | None) -> str | None:
    items = parse_break_slots_storage(list(slots or []))
    return json.dumps(items, separators=(",", ":")) if items else None


def entry_break_slots(entry: Mapping[str, Any]) -> list[dict[str, str]]:
    raw = entry.get("break_slots")
    return parse_break_slots_storage(list(raw) if isinstance(raw, (list, tuple)) else raw)


def _shift_interval(entry: Mapping[str, Any]) -> tuple[int, int] | None:
    """Shift (start, end) in minutes on its start day's timeline; overnight ends run past 24:00."""
    start = _hm_minutes(entry.get("start_time"))
    end = _hm_minutes(entry.get("end_time"))
    if start is None or end is None:
        return None
    if end <= start:
        end += 24 * 60
    return start, end


def _placed_break_ranges(entry: Mapping[str, Any], shift: tuple[int, int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for slot in entry_break_slots(entry):
        seg_start = _hm_minutes(slot["start_time"])
        seg_end = _hm_minutes(slot["end_time"])
        if seg_start is None or seg_end is None:
            continue
        start, end = _place_on_shift_timeline(seg_start, seg_end, shift[0])
        start, end = max(start, shift[0]), min(end, shift[1])
        if end > start:
            out.append((start, end))
    return out


def _merge_ranges(ranges: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _ranges_minutes(ranges: Sequence[tuple[int, int]]) -> int:
    return sum(max(0, end - start) for start, end in ranges)


def entry_break_breakdown(entry: Mapping[str, Any]) -> dict[str, int]:
    """
    Minutes for one shift. ``break_minutes`` is the total planned deduction; timed slots are the part
    of it with a known time and the rest is duration-only ("not scheduled"). A slot never adds to an
    existing duration-only break: the deduction is the larger of the two.
    """
    shift = _shift_interval(entry)
    if shift is None:
        return {"gross_minutes": 0, "break_minutes": 0, "timed_break_minutes": 0, "unscheduled_break_minutes": 0}
    gross = shift[1] - shift[0]
    timed = _ranges_minutes(_merge_ranges(_placed_break_ranges(entry, shift)))
    total = min(gross, max(max(0, int(entry.get("break_minutes") or 0)), timed))
    timed = min(timed, total)
    return {
        "gross_minutes": gross,
        "break_minutes": total,
        "timed_break_minutes": timed,
        "unscheduled_break_minutes": total - timed,
    }


def _shift_hours_for_entry(entry: Mapping[str, Any]) -> float:
    parts = entry_break_breakdown(entry)
    return round(max(0, parts["gross_minutes"] - parts["break_minutes"]) / 60.0, 4)


def _default_task_roles() -> frozenset[str]:
    from backend.weekly_schedule_roles import default_role_catalog

    return frozenset(r["code"] for r in default_role_catalog() if not r.get("uses_time_slots", True))


def employee_day_timeline(
    entries: Sequence[Mapping[str, Any]],
    *,
    task_roles: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """
    One employee's planned day (all entries share user and day).

    Overlapping shifts merge into one span, so their time is counted once. A timed break from any of
    those shifts takes the person off every role for that time. The duration-only part of a merged
    span is its largest declared break less the timed break already placed there; it is deducted
    from net hours but never given an hourly position. Worked pieces carry the roles active in them,
    and simultaneous roles share a piece evenly. Tasks never count.
    """
    tasks = _default_task_roles() if task_roles is None else task_roles
    direct_hours = 0.0
    direct_roles: dict[str, float] = defaultdict(float)
    shifts: list[tuple[int, int, Mapping[str, Any]]] = []
    assigned: set[str] = set()
    for entry in entries or []:
        roles = list(
            dict.fromkeys(
                str(a["role"]) for a in entry_role_assignments(entry) if a.get("role") and a["role"] not in tasks
            )
        )
        assigned.update(roles)
        raw_hours = entry.get("hours")
        if raw_hours is not None and float(raw_hours or 0) <= 0:
            continue
        shift = _shift_interval(entry)
        if shift is None:
            hours = max(0.0, float(raw_hours or 0))
            if hours <= 0:
                continue
            direct_hours += hours
            for role in roles:
                direct_roles[role] += hours / len(roles)
            continue
        shifts.append((shift[0], shift[1], entry))
    shifts.sort(key=lambda item: (item[0], item[1]))

    clusters: list[dict[str, Any]] = []
    for item in shifts:
        if clusters and item[0] < clusters[-1]["end"]:
            clusters[-1]["end"] = max(clusters[-1]["end"], item[1])
            clusters[-1]["items"].append(item)
        else:
            clusters.append({"start": item[0], "end": item[1], "items": [item]})

    gross = timed = unscheduled = 0
    break_ranges: list[tuple[int, int]] = []
    untimed_breaks: list[dict[str, Any]] = []
    for cluster in clusters:
        span = cluster["end"] - cluster["start"]
        per_entry = [_merge_ranges(_placed_break_ranges(e, (s, en))) for s, en, e in cluster["items"]]
        ranges = _merge_ranges([r for rs in per_entry for r in rs])
        cluster_timed = _ranges_minutes(ranges)
        declared = max(
            max(max(0, int(e.get("break_minutes") or 0)), _ranges_minutes(rs))
            for (_, _, e), rs in zip(cluster["items"], per_entry)
        )
        deduction = min(span, max(cluster_timed, declared))
        gross += span
        timed += cluster_timed
        unscheduled += deduction - cluster_timed
        if deduction > cluster_timed:
            untimed_breaks.append(
                {"start": cluster["start"], "end": cluster["end"], "minutes": deduction - cluster_timed}
            )
        break_ranges.extend(ranges)

    segments: list[tuple[str, int, int]] = []
    for shift_start, shift_end, entry in shifts:
        for assignment in entry_role_assignments(entry):
            role = assignment.get("role")
            if not role or role in tasks:
                continue
            seg_start = _hm_minutes(assignment.get("start_time"))
            seg_end = _hm_minutes(assignment.get("end_time"))
            if assignment.get("full_shift", True) or seg_start is None or seg_end is None:
                segments.append((str(role), shift_start, shift_end))
                continue
            start, end = _place_on_shift_timeline(seg_start, seg_end, shift_start)
            start, end = max(start, shift_start), min(end, shift_end)
            if end > start:
                segments.append((str(role), start, end))

    points = sorted(
        {p for s, e, _ in shifts for p in (s, e)}
        | {p for _, s, e in segments for p in (s, e)}
        | {p for s, e in break_ranges for p in (s, e)}
    )
    pieces: list[dict[str, Any]] = []
    for left, right in zip(points, points[1:]):
        if not any(s <= left and e >= right for s, e, _ in shifts):
            continue
        pieces.append(
            {
                "start": left,
                "end": right,
                "roles": _sort_roles(list({r for r, s, e in segments if s <= left and e >= right})),
                "on_break": any(s <= left and e >= right for s, e in break_ranges),
            }
        )

    for item in untimed_breaks:
        keys: set[str] = set()
        for piece in pieces:
            if piece["on_break"] or piece["start"] < item["start"] or piece["end"] > item["end"]:
                continue
            keys.update(piece["roles"] or [""])
        item["role_keys"] = sorted(keys)
        item["resolved_role"] = next(iter(keys)) if len(keys) == 1 else ("" if not keys else None)

    break_minutes = timed + unscheduled
    return {
        "gross_hours": gross / 60.0 + direct_hours,
        "break_hours": break_minutes / 60.0,
        "timed_break_hours": timed / 60.0,
        "unscheduled_break_hours": unscheduled / 60.0,
        "net_hours": (gross - break_minutes) / 60.0 + direct_hours,
        "pieces": pieces,
        "break_ranges": break_ranges,
        "untimed_breaks": untimed_breaks,
        "direct_hours": direct_hours,
        "direct_role_hours": dict(direct_roles),
        "assigned_roles": _sort_roles(list(assigned)),
    }


def timeline_role_breakdown(timeline: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    """
    Per-role hours for one day timeline (key ``""`` = shift time without a role).

    Worked time off timed breaks is split evenly between simultaneous roles, and a timed break is split
    the same way between the roles it pauses. A duration-only break has no position: when its shift holds
    a single role (or only time without a role) it comes off that role (``untimed_break``); otherwise it
    is not allocated, and each role it could fall in reports it as ``unallocated_break`` with ``net``
    left gross of it until the break is scheduled. Splits always use every role the employee holds, so
    leaving a role out of a report never moves its hours to another role.
    """
    out: dict[str, dict[str, float]] = {}

    def parts(role: str) -> dict[str, float]:
        return out.setdefault(
            role,
            {"gross": 0.0, "worked": 0.0, "timed_break": 0.0, "untimed_break": 0.0, "unallocated_break": 0.0, "net": 0.0},
        )

    for piece in timeline.get("pieces") or []:
        keys = list(piece["roles"]) or [""]
        share = (piece["end"] - piece["start"]) / 60.0 / len(keys)
        for role in keys:
            row = parts(role)
            row["gross"] += share
            if piece["on_break"]:
                row["timed_break"] += share
            else:
                row["worked"] += share
    for item in timeline.get("untimed_breaks") or []:
        hours = item["minutes"] / 60.0
        if item.get("resolved_role") is None:
            for role in item.get("role_keys") or []:
                parts(role)["unallocated_break"] += hours
        else:
            parts(item["resolved_role"])["untimed_break"] += hours
    for row in out.values():
        row["net"] = row["worked"] - row["untimed_break"]
    direct_roles = timeline.get("direct_role_hours") or {}
    direct_no_role = max(0.0, float(timeline.get("direct_hours") or 0.0) - sum(direct_roles.values()))
    for role, hours in [*direct_roles.items(), ("", direct_no_role)]:
        if hours <= 0:
            continue
        row = parts(role)
        row["gross"] += hours
        row["worked"] += hours
        row["net"] += hours
    return out


def timeline_role_hours(timeline: Mapping[str, Any]) -> dict[str, float]:
    """Net role hours from one day timeline (see ``timeline_role_breakdown``)."""
    return {role: row["net"] for role, row in timeline_role_breakdown(timeline).items() if role}


def _entries_by_user_day(entries: Sequence[Mapping[str, Any]]) -> dict[tuple[int, int], list[Mapping[str, Any]]]:
    groups: dict[tuple[int, int], list[Mapping[str, Any]]] = defaultdict(list)
    for entry in entries or []:
        groups[(int(entry.get("user_id") or 0), int(entry.get("day_of_week") or 0))].append(entry)
    return groups


def scheduled_hours_breakdown_by_user_day(
    entries: Sequence[Mapping[str, Any]],
    *,
    task_roles: set[str] | frozenset[str] | None = None,
) -> dict[tuple[int, int], dict[str, float]]:
    """Gross, break (timed + duration-only), and net scheduled hours per (user_id, day_of_week)."""
    out: dict[tuple[int, int], dict[str, float]] = {}
    for key, group in _entries_by_user_day(entries).items():
        timeline = employee_day_timeline(group, task_roles=task_roles)
        out[key] = {
            name: round(float(timeline[name]), 2)
            for name in ("gross_hours", "break_hours", "timed_break_hours", "unscheduled_break_hours", "net_hours")
        }
    return out


def _intervals_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _hm_minutes(value: Any) -> int | None:
    parsed = parse_time_value(value)
    if parsed is None:
        return None
    return parsed.hour * 60 + parsed.minute


def _place_on_shift_timeline(seg_start: int, seg_end: int, shift_start: int) -> tuple[int, int]:
    """Map wall-clock minutes onto a shift timeline whose end may run past midnight (+24h)."""
    start = seg_start + (24 * 60 if seg_start < shift_start else 0)
    end = seg_end
    while end <= start:
        end += 24 * 60
    return start, end


def parse_role_assignments_storage(raw: Any) -> list[dict[str, Any]]:
    """Decode ``role_assignments`` JSON: [{role, start_time?, end_time?, remarks?}]."""
    if raw in (None, ""):
        return []
    data: Any = raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, Mapping):
            continue
        role = normalize_weekly_role(item.get("role"))
        if not role:
            continue
        start = _time_to_str(item.get("start_time"))
        end = _time_to_str(item.get("end_time"))
        timed = bool(start and end)
        remarks = str(item.get("remarks") or "").strip() or None
        out.append(
            {
                "role": role,
                "start_time": start if timed else None,
                "end_time": end if timed else None,
                "remarks": remarks,
            }
        )
    return out


def expand_role_assignments(
    roles: Sequence[str],
    stored: Sequence[Mapping[str, Any]],
    *,
    start_time: str | None,
    end_time: str | None,
) -> list[dict[str, Any]]:
    """Every role on a shift as an assignment; roles without a stored range span the whole shift."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in stored:
        role = item.get("role")
        if role not in roles:
            continue
        timed = bool(item.get("start_time") and item.get("end_time"))
        out.append(
            {
                "role": role,
                "start_time": item["start_time"] if timed else start_time,
                "end_time": item["end_time"] if timed else end_time,
                "remarks": item.get("remarks") or None,
                "full_shift": not timed,
            }
        )
        seen.add(str(role))
    for role in roles:
        if role not in seen:
            out.append(
                {
                    "role": role,
                    "start_time": start_time,
                    "end_time": end_time,
                    "remarks": None,
                    "full_shift": True,
                }
            )
    shift_start = _hm_minutes(start_time)
    order = {role: i for i, role in enumerate(roles)}

    def _key(assignment: Mapping[str, Any]) -> tuple[int, int]:
        offset = 0
        if not assignment["full_shift"] and shift_start is not None:
            seg = _hm_minutes(assignment.get("start_time"))
            if seg is not None:
                offset = (seg - shift_start) % (24 * 60)
        return offset, order.get(assignment["role"], 99)

    return sorted(out, key=_key)


def entry_role_assignments(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    assignments = entry.get("assignments")
    if isinstance(assignments, list) and assignments:
        return [dict(a) for a in assignments if isinstance(a, Mapping) and a.get("role")]
    roles = parse_weekly_roles(entry.get("role") or entry.get("roles"))
    return expand_role_assignments(
        roles,
        parse_role_assignments_storage(entry.get("role_assignments")),
        start_time=_time_to_str(entry.get("start_time")),
        end_time=_time_to_str(entry.get("end_time")),
    )


def role_assignments_storage(assignments: Sequence[Mapping[str, Any]]) -> str | None:
    """Persist only what the ``role`` column cannot express: sub-shift ranges and remarks."""
    items: list[dict[str, Any]] = []
    for assignment in assignments or []:
        timed = bool(assignment.get("start_time") and assignment.get("end_time"))
        full_shift = bool(assignment.get("full_shift", not timed)) or not timed
        remarks = assignment.get("remarks") or None
        if full_shift and not remarks:
            continue
        item: dict[str, Any] = {"role": assignment["role"]}
        if not full_shift:
            item["start_time"] = _time_to_str(assignment.get("start_time"))
            item["end_time"] = _time_to_str(assignment.get("end_time"))
        if remarks:
            item["remarks"] = remarks
        items.append(item)
    return json.dumps(items, separators=(",", ":")) if items else None


def scheduled_hours_by_user_day(
    entries: Sequence[Mapping[str, Any]],
    *,
    task_roles: set[str] | frozenset[str] | None = None,
) -> dict[tuple[int, int], float]:
    """
    Net scheduled hours per (user_id, day_of_week): gross span minus timed and duration-only breaks.
    Overlapping shifts for the same employee/day count their combined span once, so stacking role
    entries inside one shift never double-counts hours or breaks.
    """
    return {
        key: parts["net_hours"]
        for key, parts in scheduled_hours_breakdown_by_user_day(entries, task_roles=task_roles).items()
    }


def allocate_role_hours_by_day(
    entries: Sequence[Mapping[str, Any]],
    *,
    task_roles: set[str] | frozenset[str] | None = None,
) -> list[dict[str, float]]:
    """
    Role hours for wash/sort/fold/PT per day from the shared day timeline: each assignment counts over
    its own range, timed breaks come off the roles they pause, simultaneous roles split the time, and a
    duration-only break comes off the role only when its shift has a single role; on a multi-role shift
    it stays unallocated (see ``timeline_role_breakdown`` and ``day_role_totals``).
    """
    totals = day_role_totals(entries, task_roles=task_roles)
    return [
        {role: round(float(day.get(role, {}).get("hours") or 0.0), 2) for role in HOUR_TRACKED_ROLES}
        for day in totals
    ]


def day_role_totals(
    entries: Sequence[Mapping[str, Any]],
    *,
    task_roles: set[str] | frozenset[str] | None = None,
) -> list[dict[str, dict[str, Any]]]:
    """
    Per day and role: distinct employees assigned the role, their role hours after timed breaks and
    allocated duration-only breaks (unrounded), and ``unallocated_break_hours`` — duration-only breaks on
    that role's multi-role shifts, of which those hours are still gross.
    """
    by_day: list[dict[str, dict[str, Any]]] = [{} for _ in range(7)]
    for (uid, dow), group in _entries_by_user_day(entries).items():
        if dow < 0 or dow > 6:
            continue
        timeline = employee_day_timeline(group, task_roles=task_roles)
        breakdown = timeline_role_breakdown(timeline)
        for role in timeline["assigned_roles"]:
            row = by_day[dow].setdefault(role, {"user_ids": set(), "hours": 0.0, "unallocated_break_hours": 0.0})
            row["user_ids"].add(uid)
            parts = breakdown.get(role) or {}
            row["hours"] += float(parts.get("net") or 0.0)
            row["unallocated_break_hours"] += float(parts.get("unallocated_break") or 0.0)
    return by_day


def day_unallocated_break_hours(
    entries: Sequence[Mapping[str, Any]],
    *,
    task_roles: set[str] | frozenset[str] | None = None,
) -> list[float]:
    """Per day: duration-only breaks on multi-role shifts, not allocated to any role (each counted once)."""
    out = [0.0] * 7
    for (_, dow), group in _entries_by_user_day(entries).items():
        if 0 <= dow <= 6:
            timeline = employee_day_timeline(group, task_roles=task_roles)
            out[dow] += sum(
                item["minutes"] / 60.0 for item in timeline["untimed_breaks"] if item.get("resolved_role") is None
            )
    return out


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
    role = roles_to_storage(roles) if roles or str(row.get("role") or "").strip() else ""
    breaks = (
        entry_break_breakdown(row)
        if schedule_end_time_enabled
        else {"gross_minutes": 0, "break_minutes": 0, "timed_break_minutes": 0, "unscheduled_break_minutes": 0}
    )
    hours = round(max(0, breaks["gross_minutes"] - breaks["break_minutes"]) / 60.0, 4)
    employer_affiliation = _entry_employer_affiliation(row, organization_slug=organization_slug)
    start_time = _time_to_str(row.get("start_time"))
    end_time = _time_to_str(row.get("end_time"))
    stored_assignments = parse_role_assignments_storage(row.get("role_assignments"))
    out: dict[str, Any] = {
        "id": int(row.get("id") or 0),
        "organization_id": int(row.get("organization_id") or 0),
        "week_start": str(row.get("week_start") or ""),
        "user_id": int(row.get("user_id") or 0),
        "day_of_week": int(row.get("day_of_week") or 0),
        "day_label": DAY_LABELS[int(row.get("day_of_week") or 0) % 7],
        "role": role,
        "roles": roles,
        "start_time": start_time,
        "end_time": end_time,
        "break_minutes": max(0, int(row.get("break_minutes") or 0)),
        "break_slots": entry_break_slots(row),
        "timed_break_minutes": breaks["timed_break_minutes"],
        "unscheduled_break_minutes": breaks["unscheduled_break_minutes"],
        "gross_hours": round(breaks["gross_minutes"] / 60.0, 4),
        "break_hours": round(breaks["break_minutes"] / 60.0, 4),
        "hours": hours,
        "assignments": expand_role_assignments(
            roles,
            stored_assignments,
            start_time=start_time,
            end_time=end_time,
        ),
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


_BREAKDOWN_TOTAL_KEYS = ("gross_hours", "break_hours", "timed_break_hours", "unscheduled_break_hours")


def compute_schedule_totals(
    entries: Sequence[Mapping[str, Any]],
    workers_by_user_id: Mapping[int, Mapping[str, Any]],
    *,
    excluded_user_ids: Sequence[int] | None = None,
    task_roles: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """``total_hours`` is net (gross minus breaks); gross and break hours are reported beside it."""
    excluded = {int(uid) for uid in (excluded_user_ids or [])}
    employee_totals: dict[int, dict[str, Any]] = {}
    day_totals: dict[int, dict[str, Any]] = {
        dow: {
            "day_of_week": dow,
            "day_label": DAY_LABELS[dow],
            "employee_count": 0,
            "total_hours": 0.0,
            **{name: 0.0 for name in _BREAKDOWN_TOTAL_KEYS},
            "sort_count": 0,
            "wash_count": 0,
            "weigher_count": 0,
            "fold_count": 0,
            "pt_sorter_count": 0,
            "pt_washer_count": 0,
            "pt_folder_count": 0,
            "hd_operator_count": 0,
            "hd_folder_count": 0,
            "attendant_count": 0,
            "non_rinse_folder_count": 0,
            "operator_count": 0,
            "folder_count": 0,
            "wash_hours": 0.0,
            "sort_hours": 0.0,
            "fold_hours": 0.0,
            "pt_washer_hours": 0.0,
            "pt_sorter_hours": 0.0,
            "pt_folder_hours": 0.0,
            "roles": [],
        }
        for dow in range(7)
    }
    employee_days: dict[int, set[int]] = defaultdict(set)
    included_entries: list[Mapping[str, Any]] = []
    role_people: dict[tuple[int, str], set[int]] = defaultdict(set)

    for entry in entries or []:
        uid = int(entry.get("user_id") or 0)
        if uid in excluded:
            continue
        included_entries.append(entry)
        dow = int(entry.get("day_of_week") or 0)
        roles = parse_weekly_roles(entry.get("role"))

        if uid not in employee_totals:
            employee_totals[uid] = {
                "user_id": uid,
                "total_hours": 0.0,
                **{name: 0.0 for name in _BREAKDOWN_TOTAL_KEYS},
                "scheduled_days": 0,
                "estimated_cost": 0.0,
            }
        employee_days[uid].add(dow)

        for role in roles or ["fold"]:
            role_people[(dow, role)].add(uid)

    for (uid, dow), parts in scheduled_hours_breakdown_by_user_day(included_entries, task_roles=task_roles).items():
        hours = parts["net_hours"]
        rate = _worker_rate(workers_by_user_id.get(uid))
        totals = employee_totals[uid]
        totals["total_hours"] = round(totals["total_hours"] + hours, 2)
        totals["estimated_cost"] = round(totals["estimated_cost"] + calc_cost(hours, rate), 2)
        day = day_totals.get(dow) or day_totals[dow % 7]
        day["total_hours"] = round(float(day["total_hours"]) + hours, 2)
        for target in (totals, day):
            for name in _BREAKDOWN_TOTAL_KEYS:
                target[name] = round(float(target.get(name) or 0.0) + parts[name], 2)

    for (dow, role), people in role_people.items():
        day = day_totals.get(dow)
        if day is not None and f"{role}_count" in day:
            day[f"{role}_count"] = len(people)
    for day in day_totals.values():
        day["operator_count"] = day["wash_count"]
        day["folder_count"] = day["fold_count"]

    unallocated_by_day = day_unallocated_break_hours(included_entries, task_roles=task_roles)
    for dow, role_rows in enumerate(day_role_totals(included_entries, task_roles=task_roles)):
        day = day_totals[dow]
        for role in HOUR_TRACKED_ROLES:
            day[f"{role}_hours"] = round(float(role_rows.get(role, {}).get("hours") or 0.0), 2)
        day["roles"] = [
            {
                "role": role,
                "employees": len(role_rows[role]["user_ids"]),
                "hours": round(role_rows[role]["hours"], 2),
                "unallocated_break_hours": round(role_rows[role]["unallocated_break_hours"], 2),
            }
            for role in _sort_roles(list(role_rows))
        ]
        day["unallocated_break_hours"] = round(unallocated_by_day[dow], 2)

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
               role, start_time, end_time, break_minutes, employer_affiliation,
               role_assignments, break_slots
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
               role, start_time, end_time, break_minutes, employer_affiliation,
               role_assignments, break_slots
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


def _validate_role_assignments(
    data: Mapping[str, Any],
    *,
    shift_start: time | None,
    shift_end: time | None,
    end_time_enabled: bool,
    role_catalog: Mapping[str, Mapping[str, Any]] | None,
    existing_assignments: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """
    Normalize per-role assignments inside one shift.

    Accepts ``assignments`` ([{role, full_shift?, start_time?, end_time?, remarks?}]) or, for older
    clients, ``roles``/``role`` (each role spans the whole shift, prior details kept).
    Sub-shift ranges must sit inside the shift; the shift row stays the source for hours.
    """
    from backend.weekly_schedule_roles import (
        accept_remarks,
        catalog_index,
        normalize_remarks,
        role_assignment_error,
    )

    index = role_catalog if role_catalog is not None else catalog_index(None)
    raw = data.get("assignments")
    if raw is None:
        roles = parse_weekly_roles(data.get("roles") if "roles" in data else data.get("role"))
        kept = [dict(a) for a in existing_assignments if a.get("role") in roles]
        kept_roles = {a["role"] for a in kept}
        raw = kept + [{"role": r, "full_shift": True} for r in roles if r not in kept_roles]
    if isinstance(raw, list) and not raw and "assignments" in data:
        return [], None
    if not isinstance(raw, list) or not raw:
        return None, "at least one role is required"

    # Each saved row may keep its role after the role is deactivated; extra rows may not.
    existing_role_slots = Counter(str(a.get("role")) for a in existing_assignments)
    existing_remarks: dict[str, set[str]] = defaultdict(set)
    for a in existing_assignments:
        if a.get("remarks"):
            existing_remarks[str(a.get("role"))].add(str(a["remarks"]))

    shift_start_min = shift_start.hour * 60 + shift_start.minute if shift_start else None
    shift_end_min = shift_end.hour * 60 + shift_end.minute if shift_end else None
    if shift_start_min is not None and shift_end_min is not None and shift_end_min <= shift_start_min:
        shift_end_min += 24 * 60
    can_split = end_time_enabled and shift_start_min is not None and shift_end_min is not None

    out: list[dict[str, Any]] = []
    full_roles: set[str] = set()
    timed_by_role: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for item in raw:
        if not isinstance(item, Mapping):
            return None, "each assignment must be an object"
        role = normalize_weekly_role(item.get("role"))
        if not role:
            return None, f"unknown schedule role: {item.get('role')}"
        already_assigned = existing_role_slots[role] > 0
        if already_assigned:
            existing_role_slots[role] -= 1
        err = role_assignment_error(role, index, timed=True, already_assigned=already_assigned)
        if err:
            return None, err
        label = (index.get(role) or {}).get("name") or role
        seg_start = parse_time_value(item.get("start_time"))
        seg_end = parse_time_value(item.get("end_time"))
        full = (
            item.get("full_shift") is True
            or (seg_start is None and seg_end is None)
            or not can_split
        )
        placed: tuple[int, int] | None = None
        if not full:
            if seg_start is None or seg_end is None:
                return None, f"{label}: start and end time are required"
            placed = _place_on_shift_timeline(
                seg_start.hour * 60 + seg_start.minute,
                seg_end.hour * 60 + seg_end.minute,
                int(shift_start_min),  # type: ignore[arg-type]
            )
            if placed[1] > int(shift_end_min):  # type: ignore[arg-type]
                return None, f"{label} time range must be within the shift"
            if placed == (shift_start_min, shift_end_min):
                full = True
        remarks = accept_remarks(
            role,
            normalize_remarks(item.get("remarks")),
            index,
            existing=existing_remarks.get(role),
        )
        if role in full_roles or (full and timed_by_role[role]):
            return None, f"{label} is assigned more than once on this shift"
        if full:
            full_roles.add(role)
            out.append({"role": role, "start_time": None, "end_time": None, "remarks": remarks, "full_shift": True})
            continue
        assert placed is not None and seg_start is not None and seg_end is not None
        if any(_intervals_overlap(placed, other) for other in timed_by_role[role]):
            return None, f"{label} time ranges overlap"
        timed_by_role[role].append(placed)
        out.append(
            {
                "role": role,
                "start_time": seg_start.strftime("%H:%M"),
                "end_time": seg_end.strftime("%H:%M"),
                "remarks": remarks,
                "full_shift": False,
            }
        )
    return out, None


def _clock_label(value: time) -> str:
    return f"{value.hour % 12 or 12}:{value.minute:02d} {'AM' if value.hour < 12 else 'PM'}"


def _validate_breaks(
    data: Mapping[str, Any],
    *,
    shift_start: time | None,
    shift_end: time | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Normalize planned breaks: ``break_slots`` ([{start_time, end_time}]) must sit inside the shift
    (overnight shifts included) without overlapping each other. ``unscheduled_break_minutes`` is the
    duration-only remainder; when it is absent, slots use up the existing ``break_minutes`` first
    so giving a duration-only break a time replaces its deduction instead of adding another.
    Stored ``break_minutes`` is always the total deduction (timed + duration-only).
    """
    try:
        declared = max(0, int(data.get("break_minutes") or 0))
    except (TypeError, ValueError):
        return None, "break_minutes must be a non-negative integer"
    raw = data.get("break_slots")
    if raw is None:
        raw = []
    if not isinstance(raw, (list, tuple)):
        return None, "break_slots must be a list"
    if len(raw) > MAX_BREAK_SLOTS:
        return None, f"at most {MAX_BREAK_SLOTS} breaks per shift"
    shift: tuple[int, int] | None = None
    if shift_start is not None and shift_end is not None:
        start_min = shift_start.hour * 60 + shift_start.minute
        end_min = shift_end.hour * 60 + shift_end.minute
        shift = (start_min, end_min + (24 * 60 if end_min <= start_min else 0))

    placed: list[tuple[str, tuple[int, int]]] = []
    slots: list[tuple[int, dict[str, str]]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, Mapping):
            return None, "each break must be an object"
        start = parse_time_value(item.get("start_time"))
        end = parse_time_value(item.get("end_time"))
        if start is None or end is None:
            return None, f"Break {index}: start and end time are required"
        if start == end:
            return None, f"Break {index}: end time must be after the start time"
        if shift is None:
            return None, "timed breaks need the shift start and end times"
        label = f"Break {_clock_label(start)}–{_clock_label(end)}"
        window = _place_on_shift_timeline(start.hour * 60 + start.minute, end.hour * 60 + end.minute, shift[0])
        if window[1] > shift[1]:
            return None, f"{label} must be within the shift"
        for other_label, other in placed:
            if _intervals_overlap(window, other):
                return None, f"{label} overlaps {other_label}"
        placed.append((label, window))
        slots.append((window[0], {"start_time": start.strftime("%H:%M"), "end_time": end.strftime("%H:%M")}))

    timed = sum(end - start for _, (start, end) in placed)
    if "unscheduled_break_minutes" in data:
        try:
            unscheduled = max(0, int(data.get("unscheduled_break_minutes") or 0))
        except (TypeError, ValueError):
            return None, "unscheduled_break_minutes must be a non-negative integer"
        total = timed + unscheduled
    else:
        total = max(declared, timed)
    ordered = [slot for _, slot in sorted(slots, key=lambda item: item[0])]
    return {"break_minutes": total, "break_slots": break_slots_storage(ordered)}, None


def _validate_entry_payload(
    data: Mapping[str, Any],
    *,
    partial: bool = False,
    schedule_end_time_enabled: bool = True,
    organization_slug: str | None = None,
    role_catalog: Mapping[str, Mapping[str, Any]] | None = None,
    existing_assignments: Sequence[Mapping[str, Any]] | None = None,
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
        if not partial or any(k in data for k in ("break_minutes", "break_slots", "unscheduled_break_minutes")):
            breaks, err = _validate_breaks(data, shift_start=out.get("start_time"), shift_end=out.get("end_time"))
            if err or breaks is None:
                return None, err
            out.update(breaks)
        if (
            "start_time" in out
            and "end_time" in out
            and calc_hours(out["start_time"], out["end_time"], int(out.get("break_minutes") or 0)) <= 0
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
        out["break_slots"] = None
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
    if not partial or "role" in data or "roles" in data or "assignments" in data:
        assignments, err = _validate_role_assignments(
            data,
            shift_start=out.get("start_time"),
            shift_end=out.get("end_time"),
            end_time_enabled=schedule_end_time_enabled,
            role_catalog=role_catalog,
            existing_assignments=existing_assignments or [],
        )
        if err or assignments is None:
            return None, err
        role_storage = (
            roles_to_storage(list(dict.fromkeys(a["role"] for a in assignments))) if assignments else ""
        )
        if len(role_storage) > ROLE_STORAGE_MAX:
            return None, "too many roles on one shift"
        out["role"] = role_storage
        out["role_assignments"] = role_assignments_storage(assignments)
    return out, None


def _load_role_catalog_index(cursor, organization_id: int) -> dict[str, dict[str, Any]]:
    from backend.weekly_schedule_roles import catalog_index, list_role_catalog

    return catalog_index(list_role_catalog(cursor, organization_id))


def default_new_shift_employer_affiliation(
    worker: Mapping[str, Any] | None,
    *,
    organization_slug: str | None = None,
) -> str:
    """New shifts default to Rinse Exclusive whenever the org offers it and the worker may hold it."""
    from backend.business_entity import (
        ENTITY_RINSE_EXCLUSIVE,
        entities_for_organization,
        worker_allows_shift_entity,
    )
    from backend.payroll_employer_affiliation import (
        default_shift_employer_affiliation,
        employer_affiliation_from_flags,
    )

    worker_entity = employer_affiliation_from_flags(worker, organization_slug=organization_slug)
    if ENTITY_RINSE_EXCLUSIVE in entities_for_organization(organization_slug) and worker_allows_shift_entity(
        worker_entity, ENTITY_RINSE_EXCLUSIVE, organization_slug=organization_slug
    ):
        return ENTITY_RINSE_EXCLUSIVE
    return default_shift_employer_affiliation(worker, organization_slug=organization_slug)


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
    preserve_assignments: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """``preserve_assignments`` (copy flows) keeps roles/remarks valid even if since deactivated."""
    ensure_planned_weekly_schedule_table(cursor)
    end_time_enabled = _schedule_end_time_enabled(cursor, organization_id)
    from backend.payroll_employer_affiliation import _organization_slug

    org_slug = _organization_slug(conn, organization_id)
    payload, err = _validate_entry_payload(
        data,
        schedule_end_time_enabled=end_time_enabled,
        organization_slug=org_slug,
        role_catalog=_load_role_catalog_index(cursor, organization_id),
        existing_assignments=preserve_assignments or [],
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
        worker = _workers_index(_load_workers(conn, organization_id)).get(int(payload["user_id"]))
        payload["employer_affiliation"] = default_new_shift_employer_affiliation(
            worker,
            organization_slug=org_slug,
        )
    cursor.execute(
        """
        INSERT INTO planned_weekly_schedule_entries (
            organization_id, week_start, user_id, day_of_week,
            role, start_time, end_time, break_minutes, employer_affiliation,
            role_assignments, break_slots
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
            payload.get("role_assignments"),
            payload.get("break_slots"),
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
    existing_assignments = existing.get("assignments") or []
    merged = {
        "user_id": existing["user_id"],
        "day_of_week": existing["day_of_week"],
        "role": existing["role"],
        "start_time": existing["start_time"],
        "end_time": existing["end_time"],
        "break_minutes": existing["break_minutes"],
        "break_slots": existing.get("break_slots") or [],
        **dict(data or {}),
    }
    if not any(key in (data or {}) for key in ("role", "roles", "assignments")):
        merged["assignments"] = existing_assignments
    if "employer_affiliation" not in merged and existing.get("employer_affiliation"):
        merged["employer_affiliation"] = existing.get("employer_affiliation")
    end_time_enabled = _schedule_end_time_enabled(cursor, organization_id)
    from backend.payroll_employer_affiliation import _organization_slug

    org_slug = _organization_slug(conn, organization_id)
    payload, err = _validate_entry_payload(
        merged,
        schedule_end_time_enabled=end_time_enabled,
        organization_slug=org_slug,
        role_catalog=_load_role_catalog_index(cursor, organization_id),
        existing_assignments=existing_assignments,
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
            employer_affiliation=%s, role_assignments=%s, break_slots=%s
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
            payload.get("role_assignments"),
            payload.get("break_slots"),
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
        "assignments": existing.get("assignments") or entry_role_assignments(existing),
        "start_time": existing["start_time"],
        "end_time": existing["end_time"],
        "break_minutes": existing["break_minutes"],
        "break_slots": existing.get("break_slots") or [],
    }
    if existing.get("employer_affiliation"):
        duplicate_data["employer_affiliation"] = existing["employer_affiliation"]
    else:
        # Untagged rows display the worker default; the copy keeps that category.
        from backend.payroll_employer_affiliation import _organization_slug, default_shift_employer_affiliation

        worker = _workers_index(_load_workers(conn, organization_id)).get(int(existing["user_id"]))
        duplicate_data["employer_affiliation"] = default_shift_employer_affiliation(
            worker, organization_slug=_organization_slug(conn, organization_id)
        )
    return create_entry(
        conn,
        cursor,
        organization_id,
        week_start=date.fromisoformat(str(existing["week_start"])),
        data=duplicate_data,
        preserve_assignments=duplicate_data["assignments"],
    )


def _bulk_insert_week_entries(
    cursor,
    organization_id: int,
    *,
    week_start: date,
    payloads: Sequence[Mapping[str, Any]],
    organization_slug: str | None = None,
) -> None:
    from backend.payroll_employer_affiliation import normalize_shift_employer_affiliation

    if not payloads:
        return
    ensure_planned_weekly_schedule_table(cursor)
    oid = int(organization_id)
    params = []
    for payload in payloads:
        start = parse_time_value(payload.get("start_time"))
        end = parse_time_value(payload.get("end_time"))
        if payload.get("role") == "" and not payload.get("roles"):
            role = ""
        else:
            role = roles_to_storage(parse_weekly_roles(payload.get("role") or payload.get("roles")))
        employer_affiliation = normalize_shift_employer_affiliation(
            payload.get("employer_affiliation"),
            organization_slug=organization_slug,
        )
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
                payload.get("role_assignments"),
                break_slots_storage(entry_break_slots(payload)),
            )
        )
    cursor.executemany(
        """
        INSERT INTO planned_weekly_schedule_entries (
            organization_id, week_start, user_id, day_of_week,
            role, start_time, end_time, break_minutes, employer_affiliation,
            role_assignments, break_slots
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        params,
    )


def week_has_schedule_content(
    cursor,
    organization_id: int,
    *,
    week_start: date,
) -> bool:
    from backend.planned_weekly_schedule_responsibilities import list_week_responsibilities

    if list_week_entries(cursor, organization_id, week_start=week_start):
        return True
    if list_week_responsibilities(cursor, organization_id, week_start=week_start):
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


def clear_week_schedule(
    cursor,
    organization_id: int,
    *,
    week_start: date,
) -> dict[str, int]:
    """Delete all schedule entries, daily responsibilities, and exclusions for a week."""
    from backend.planned_weekly_schedule_responsibilities import clear_week_responsibilities

    ensure_planned_weekly_schedule_table(cursor)
    oid = int(organization_id)
    cursor.execute(
        """
        DELETE FROM planned_weekly_schedule_entries
        WHERE organization_id = %s AND week_start = %s
        """,
        (oid, week_start),
    )
    entries_deleted = int(cursor.rowcount or 0)
    cursor.execute(
        """
        DELETE FROM planned_weekly_schedule_exclusions
        WHERE organization_id = %s AND week_start = %s
        """,
        (oid, week_start),
    )
    exclusions_deleted = int(cursor.rowcount or 0)
    responsibilities_deleted = clear_week_responsibilities(cursor, oid, week_start=week_start)
    return {
        "entries_deleted": entries_deleted,
        "exclusions_deleted": exclusions_deleted,
        "responsibilities_deleted": responsibilities_deleted,
    }


def cascade_week_schedule(
    conn,
    cursor,
    organization_id: int,
    *,
    source_week_start: date,
    target_week_start: date,
    replace: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Copy one week's schedule onto another week.

    When ``replace`` is True, the target week's existing entries/exclusions are
    cleared first. When False and the target already has content, returns an error.
    """
    source = normalize_week_start(source_week_start)
    target = normalize_week_start(target_week_start)
    if not isinstance(source, date) or not isinstance(target, date):
        return None, "source_week_start and target_week_start must be YYYY-MM-DD Sundays"
    if source == target:
        return None, "source and target weeks must be different"

    if not week_has_schedule_content(cursor, organization_id, week_start=source):
        return None, "source week has no schedule to cascade"

    cleared = {"entries_deleted": 0, "exclusions_deleted": 0}
    target_has_content = week_has_schedule_content(cursor, organization_id, week_start=target)
    if target_has_content and not replace:
        return None, "target week already has a schedule; set replace=true to overwrite it"
    if target_has_content and replace:
        cleared = clear_week_schedule(cursor, organization_id, week_start=target)

    result = carry_forward_week_schedule(
        conn,
        cursor,
        organization_id,
        target_week_start=target,
        source_week_start=source,
    )
    result["replaced"] = bool(target_has_content and replace)
    result["entries_deleted"] = int(cleared.get("entries_deleted") or 0)
    result["exclusions_deleted"] = int(cleared.get("exclusions_deleted") or 0)
    return result, None


def _entry_copy_payload(entry: Mapping[str, Any], *, day_of_week: int) -> dict[str, Any]:
    return {
        "user_id": int(entry.get("user_id") or 0),
        "day_of_week": day_of_week,
        "role": entry.get("role"),
        "start_time": entry["start_time"],
        "end_time": entry["end_time"],
        "break_minutes": entry.get("break_minutes", 0),
        "break_slots": entry_break_slots(entry),
        "employer_affiliation": entry.get("employer_affiliation"),
        "role_assignments": role_assignments_storage(entry_role_assignments(entry)),
    }


def build_week_copy(
    conn,
    cursor,
    organization_id: int,
    *,
    source_week_start: date,
    seed_sunday_from_saturday: bool = True,
) -> dict[str, Any]:
    """Snapshot a week's shifts, tasks and exclusions for copying onto other weeks."""
    from backend.payroll_employer_affiliation import _organization_slug
    from backend.planned_weekly_schedule_responsibilities import (
        list_week_responsibilities,
        responsibility_copy_rows,
    )

    oid = int(organization_id)
    workers = _load_workers(conn, oid)
    # Affiliation=none workers must never be resurrected by cascade / carry-forward,
    # even when stale planned rows still exist on the source week.
    valid_user_ids = schedulable_worker_user_ids(conn, oid, workers)
    source_entries = list_week_entries(cursor, oid, week_start=source_week_start, conn=conn)

    payloads: list[dict[str, Any]] = []
    skipped_entries = 0
    for entry in source_entries:
        if int(entry.get("user_id") or 0) not in valid_user_ids:
            skipped_entries += 1
            continue
        payloads.append(_entry_copy_payload(entry, day_of_week=int(entry.get("day_of_week") or 0)))

    source_has_sunday = any(int(p["day_of_week"]) == 0 for p in payloads)
    # When cascading near week-end, the source Sunday column is often still empty
    # (that calendar Sunday is already in the past). Seed target Sunday from source
    # Saturday so tomorrow shows up in Team Status after a cascade.
    seed_sunday = seed_sunday_from_saturday and not source_has_sunday
    if seed_sunday:
        for entry in source_entries:
            if int(entry.get("day_of_week") or -1) == 6 and int(entry.get("user_id") or 0) in valid_user_ids:
                payloads.append(_entry_copy_payload(entry, day_of_week=0))

    responsibilities = responsibility_copy_rows(
        list_week_responsibilities(cursor, oid, week_start=source_week_start),
        valid_user_ids=valid_user_ids,
        seed_sunday_from_saturday=seed_sunday,
    )
    exclusions = [
        uid
        for uid in list_excluded_user_ids(cursor, oid, week_start=source_week_start)
        if uid in valid_user_ids
    ]
    return {
        "source_week_start": source_week_start,
        "organization_slug": _organization_slug(conn, oid),
        "entries": payloads,
        "entries_skipped": skipped_entries,
        "responsibilities": responsibilities,
        "exclusions": exclusions,
    }


def week_copy_has_content(copy: Mapping[str, Any]) -> bool:
    return bool(copy.get("entries") or copy.get("responsibilities") or copy.get("exclusions"))


def apply_week_copy(
    cursor,
    organization_id: int,
    *,
    target_week_start: date,
    copy: Mapping[str, Any],
) -> dict[str, Any]:
    """Insert a ``build_week_copy`` snapshot into ``target_week_start`` (caller clears it first)."""
    from backend.planned_weekly_schedule_responsibilities import insert_responsibility_rows

    oid = int(organization_id)
    entries = list(copy.get("entries") or [])
    _bulk_insert_week_entries(
        cursor,
        oid,
        week_start=target_week_start,
        payloads=entries,
        organization_slug=copy.get("organization_slug"),
    )
    responsibilities_copied = insert_responsibility_rows(
        cursor,
        oid,
        week_start=target_week_start,
        rows=copy.get("responsibilities") or [],
    )
    exclusions = list(copy.get("exclusions") or [])
    if exclusions:
        ensure_planned_weekly_schedule_exclusions_table(cursor)
        cursor.executemany(
            """
            INSERT IGNORE INTO planned_weekly_schedule_exclusions
                (organization_id, week_start, user_id)
            VALUES (%s, %s, %s)
            """,
            [(oid, target_week_start, int(uid)) for uid in exclusions],
        )
    return {
        "source_week_start": str(copy.get("source_week_start")),
        "target_week_start": str(target_week_start),
        "entries_copied": len(entries),
        "exclusions_copied": len(exclusions),
        "entries_skipped": int(copy.get("entries_skipped") or 0),
        "responsibilities_copied": responsibilities_copied,
    }


def carry_forward_week_schedule(
    conn,
    cursor,
    organization_id: int,
    *,
    target_week_start: date,
    source_week_start: date,
    seed_sunday_from_saturday: bool = True,
) -> dict[str, Any]:
    """Copy entries, tasks and exclusions from source week into target week."""
    copy = build_week_copy(
        conn,
        cursor,
        organization_id,
        source_week_start=source_week_start,
        seed_sunday_from_saturday=seed_sunday_from_saturday,
    )
    return apply_week_copy(cursor, organization_id, target_week_start=target_week_start, copy=copy)


def ensure_week_schedule_carried_forward(
    conn,
    cursor,
    organization_id: int,
    *,
    week_start: date,
) -> dict[str, Any] | None:
    """If target week has no schedule yet, seed it from the active template or the latest prior week."""
    from backend.weekly_schedule_template import template_source_for_week

    if week_has_schedule_content(cursor, organization_id, week_start=week_start):
        return None
    template_source = template_source_for_week(cursor, organization_id, week_start)
    if template_source:
        return carry_forward_week_schedule(
            conn,
            cursor,
            organization_id,
            target_week_start=week_start,
            source_week_start=template_source,
            seed_sunday_from_saturday=False,
        )
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
    """Move this week's shifts to ``employer_affiliation``.

    Uses batch SQLs (not per-row profile saves) so the admin button does not
    hang / hit the browser timeout. Scheduled workers are migrated onto the
    target entity in the same call.
    """
    from backend.payroll_employer_affiliation import (
        _organization_slug,
        flags_from_employer_affiliation,
        normalize_shift_employer_affiliation,
    )
    from backend.payroll_schedule import ensure_worker_profile

    ensure_planned_weekly_schedule_table(cursor)
    org_slug = _organization_slug(conn, organization_id)
    aff = normalize_shift_employer_affiliation(employer_affiliation, organization_slug=org_slug)
    if not aff:
        return 0, "employer_affiliation must be washpro, washmate, veewash, or rinse_exclusive", []

    rows = list_week_entries(cursor, organization_id, week_start=week_start, conn=conn)
    if not rows:
        return 0, None, []

    user_ids = sorted({int(row.get("user_id") or 0) for row in rows if int(row.get("user_id") or 0) > 0})
    flags = flags_from_employer_affiliation(aff)
    for uid in user_ids:
        ensure_worker_profile(conn, int(organization_id), uid)
        cursor.execute(
            """
            UPDATE payroll_worker_profiles
            SET business_entity=%s,
                can_work_rinse=%s,
                can_work_drop_off=%s,
                can_work_both=%s
            WHERE organization_id=%s AND user_id=%s
            """,
            (
                aff,
                1 if flags.get("can_work_rinse") else 0,
                1 if flags.get("can_work_drop_off") else 0,
                1 if flags.get("can_work_both") else 0,
                int(organization_id),
                uid,
            ),
        )

    placeholders = ",".join(["%s"] * len(user_ids))
    cursor.execute(
        f"""
        UPDATE planned_weekly_schedule_entries
        SET employer_affiliation=%s
        WHERE organization_id=%s AND week_start=%s AND user_id IN ({placeholders})
        """,
        (aff, int(organization_id), week_start, *user_ids),
    )
    updated = int(getattr(cursor, "rowcount", 0) or 0)
    # Some connectors report 0 when values were already equal; fall back to row count.
    if updated <= 0:
        updated = len(rows)
    return updated, None, []


def build_week_payload(
    conn,
    cursor,
    organization_id: int,
    *,
    week_start: date,
    user_roles: Sequence[str] | None = None,
) -> dict[str, Any]:
    from backend.business_entity import entity_scope_payload
    from backend.payroll_employer_affiliation import (
        EMPLOYER_AFFILIATION_NONE,
        _organization_slug,
        employer_affiliation_from_flags,
    )
    from backend.weekly_schedule_display_settings import effective_weekly_schedule_view, apply_rinse_viewer_scope

    org_slug = _organization_slug(conn, organization_id)
    workers = _load_workers(conn, organization_id)
    workers_by_uid = _workers_index(workers)
    schedulable_uids = schedulable_worker_user_ids(conn, organization_id, workers)
    raw_entries = enrich_entries_with_employer_affiliation(
        list_week_entries(cursor, organization_id, week_start=week_start, conn=conn),
        workers_by_uid,
        organization_slug=org_slug,
    )
    # Affiliation=none must not participate in the week grid, even if stale rows remain.
    entries = [e for e in raw_entries if int(e.get("user_id") or 0) in schedulable_uids]
    excluded_user_ids = [
        uid
        for uid in list_excluded_user_ids(cursor, organization_id, week_start=week_start)
        if int(uid) in schedulable_uids
    ]
    excluded_set = set(excluded_user_ids)
    from backend.weekly_schedule_roles import list_role_catalog, role_groups_payload

    role_catalog = list_role_catalog(cursor, organization_id)
    totals = compute_schedule_totals(
        entries,
        workers_by_uid,
        excluded_user_ids=excluded_user_ids,
        task_roles=frozenset(r["code"] for r in role_catalog if not r.get("uses_time_slots", True)),
    )

    employee_rows = []
    for worker in workers:
        uid = int(worker.get("user_id") or 0)
        aff = employer_affiliation_from_flags(worker, organization_slug=org_slug)
        if aff == EMPLOYER_AFFILIATION_NONE:
            continue
        is_excluded = uid in excluded_set
        stats = totals["employee_totals"].get(uid) or {
            "user_id": uid,
            "total_hours": 0.0,
            "scheduled_days": 0,
            "estimated_cost": 0.0,
        }
        hour_parts = {name: float(stats.get(name) or 0.0) for name in _BREAKDOWN_TOTAL_KEYS}
        employee_rows.append(
            {
                "user_id": uid,
                "worker_profile_id": worker.get("worker_profile_id") or worker.get("id"),
                "display_name": worker.get("display_name") or worker.get("worker_name") or f"User {uid}",
                "default_hourly_rate": _worker_rate(worker),
                "can_work_rinse": bool(worker.get("can_work_rinse", True)),
                "can_work_drop_off": bool(worker.get("can_work_drop_off", True)),
                "can_work_both": bool(worker.get("can_work_both", True)),
                "employer_affiliation": aff,
                "business_entity": aff,
                "total_hours": stats["total_hours"],
                **hour_parts,
                "scheduled_days": stats["scheduled_days"],
                "estimated_cost": stats["estimated_cost"],
                "excluded": is_excluded,
            }
        )
    employee_rows.sort(key=lambda row: (row.get("display_name") or "").casefold())

    view = effective_weekly_schedule_view(cursor, organization_id, user_roles)

    from backend.planned_weekly_schedule_responsibilities import (
        filter_responsibilities_for_view,
        list_week_responsibilities,
    )
    from backend.weekly_schedule_template import schedule_template_payload

    responsibilities = filter_responsibilities_for_view(
        list_week_responsibilities(cursor, organization_id, week_start=week_start),
        allowed_user_ids=schedulable_uids,
    )

    payload = {
        "week_start": str(week_start),
        "day_labels": list(DAY_LABELS),
        "employees": employee_rows,
        "entries": entries,
        "daily_responsibilities": responsibilities,
        "role_catalog": role_catalog,
        "role_groups": role_groups_payload(cursor, organization_id),
        "totals": totals,
        "excluded_user_ids": excluded_user_ids,
        "display": view,
        "entity_scope": entity_scope_payload(organization_id, org_slug, user_roles),
        "schedule_template": schedule_template_payload(cursor, organization_id, week_start),
    }
    if view.get("lock_employer_tab"):
        return apply_rinse_viewer_scope(
            payload,
            hidden_roles=view.get("hidden_schedule_roles") or [],
        )
    return payload
