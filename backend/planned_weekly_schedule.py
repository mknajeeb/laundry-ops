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
    "fold",
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


def ensure_planned_weekly_schedule_table(cursor) -> None:
    if table_exists(cursor, "planned_weekly_schedule_entries"):
        _ensure_role_column_width(cursor)
        _ensure_employer_affiliation_column(cursor)
        _ensure_role_assignments_column(cursor)
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


def _entry_interval_minutes(entry: Mapping[str, Any]) -> tuple[int, int, float] | None:
    """Return (start_min, end_min, hours) with overnight support, or None."""
    start = parse_time_value(entry.get("start_time"))
    end = parse_time_value(entry.get("end_time"))
    if not start or not end:
        return None
    start_min = start.hour * 60 + start.minute
    end_min = end.hour * 60 + end.minute
    if end_min <= start_min:
        end_min += 24 * 60
    break_min = max(0, int(entry.get("break_minutes") or 0))
    hours = max(0.0, (end_min - start_min - break_min) / 60.0)
    return start_min, end_min, hours


def _intervals_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _merge_interval_hours(intervals: Sequence[tuple[int, int]]) -> float:
    if not intervals:
        return 0.0
    sorted_iv = sorted(intervals, key=lambda item: (item[0], item[1]))
    merged = [[sorted_iv[0][0], sorted_iv[0][1]]]
    for start, end in sorted_iv[1:]:
        last = merged[-1]
        if start < last[1]:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return sum(max(0, end - start) / 60.0 for start, end in merged)


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


def scheduled_hours_by_user_day(entries: Sequence[Mapping[str, Any]]) -> dict[tuple[int, int], float]:
    """
    Paid scheduled hours per (user_id, day_of_week).
    Overlapping shifts for the same employee/day count their combined span once (largest break),
    so stacking role entries inside one shift never double-counts hours.
    """
    out: dict[tuple[int, int], float] = defaultdict(float)
    timed: dict[tuple[int, int], list[tuple[int, int, int, float]]] = defaultdict(list)
    for entry in entries or []:
        key = (int(entry.get("user_id") or 0), int(entry.get("day_of_week") or 0))
        raw_hours = entry.get("hours")
        hours = float(raw_hours) if raw_hours is not None else _shift_hours_for_entry(entry)
        interval = _entry_interval_minutes(entry) if hours > 0 else None
        if interval is None:
            out[key] += max(0.0, hours)
            continue
        start, end, _ = interval
        timed[key].append((start, end, max(0, int(entry.get("break_minutes") or 0)), hours))

    for key, items in timed.items():
        items.sort(key=lambda item: (item[0], item[1]))
        clusters: list[list[tuple[int, int, int, float]]] = []
        for item in items:
            if clusters and item[0] < max(c[1] for c in clusters[-1]):
                clusters[-1].append(item)
            else:
                clusters.append([item])
        for cluster in clusters:
            if len(cluster) == 1:
                out[key] += cluster[0][3]
                continue
            span = max(c[1] for c in cluster) - cluster[0][0]
            out[key] += max(0.0, (span - max(c[2] for c in cluster)) / 60.0)
    return {key: round(value, 2) for key, value in out.items()}


def allocate_role_hours_by_day(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, float]]:
    """
    Allocate scheduled hours to wash/sort/fold/PT roles.
    Each role assignment counts over its own time range inside the shift (whole shift when no
    range is set); concurrent hour-tracked assignments split that time evenly, and the shift
    break is pro-rated so role hours never exceed the shift's paid hours.
    Overlapping same employee/day/role time across entries is merged (no double-count).
    """
    by_day: list[dict[str, float]] = [{role: 0.0 for role in HOUR_TRACKED_ROLES} for _ in range(7)]
    buckets: dict[tuple[int, int, str], list[dict[str, Any]]] = defaultdict(list)

    for entry in entries or []:
        uid = int(entry.get("user_id") or 0)
        dow = int(entry.get("day_of_week") or 0)
        if dow < 0 or dow > 6:
            continue
        assignments = [a for a in entry_role_assignments(entry) if a.get("role") in HOUR_TRACKED_ROLES]
        if not assignments:
            continue
        interval = _entry_interval_minutes(entry)
        if interval is None:
            segment_hours = float(entry.get("hours") or _shift_hours_for_entry(entry) or 0.0)
            if segment_hours <= 0:
                continue
            roles = list(dict.fromkeys(str(a["role"]) for a in assignments))
            for role in roles:
                buckets[(uid, dow, role)].append(
                    {"start": None, "end": None, "hours": segment_hours / len(roles), "direct": True}
                )
            continue

        shift_start, shift_end, paid_hours = interval
        wall = shift_end - shift_start
        if paid_hours <= 0 or wall <= 0:
            continue
        paid_ratio = paid_hours * 60.0 / wall
        ranges: list[tuple[str, int, int]] = []
        for assignment in assignments:
            role = str(assignment["role"])
            seg_start = _hm_minutes(assignment.get("start_time"))
            seg_end = _hm_minutes(assignment.get("end_time"))
            if assignment.get("full_shift", True) or seg_start is None or seg_end is None:
                ranges.append((role, shift_start, shift_end))
                continue
            start, end = _place_on_shift_timeline(seg_start, seg_end, shift_start)
            start, end = max(start, shift_start), min(end, shift_end)
            if end > start:
                ranges.append((role, start, end))
        bounds = sorted({point for _, start, end in ranges for point in (start, end)})
        for left, right in zip(bounds, bounds[1:]):
            active = sorted({role for role, start, end in ranges if start <= left and end >= right})
            if not active:
                continue
            share = (right - left) / 60.0 * paid_ratio / len(active)
            for role in active:
                buckets[(uid, dow, role)].append(
                    {"start": left, "end": right, "hours": share, "direct": False}
                )

    for (uid, dow, role), items in buckets.items():
        timed = [item for item in items if not item["direct"]]
        direct = [item for item in items if item["direct"]]
        hours = sum(float(item["hours"]) for item in direct)
        if timed:
            pairs = [(int(item["start"]), int(item["end"])) for item in timed]
            overlaps = any(
                _intervals_overlap(pairs[i], pairs[j])
                for i in range(len(pairs))
                for j in range(i + 1, len(pairs))
            )
            if overlaps:
                span = sum(end - start for start, end in pairs) / 60.0
                weight = sum(float(item["hours"]) for item in timed) / span if span > 0 else 1.0
                hours += _merge_interval_hours(pairs) * min(1.0, weight)
            else:
                hours += sum(float(item["hours"]) for item in timed)
        by_day[dow][role] = round(float(by_day[dow][role]) + hours, 1)

    return by_day


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
        }
        for dow in range(7)
    }
    employee_days: dict[int, set[int]] = defaultdict(set)
    included_entries: list[Mapping[str, Any]] = []

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
                "scheduled_days": 0,
                "estimated_cost": 0.0,
            }
        employee_days[uid].add(dow)

        day = day_totals.get(dow) or day_totals[dow]
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
            elif role == "pt_sorter":
                day["pt_sorter_count"] = int(day["pt_sorter_count"]) + 1
            elif role == "pt_washer":
                day["pt_washer_count"] = int(day["pt_washer_count"]) + 1
            elif role == "pt_folder":
                day["pt_folder_count"] = int(day["pt_folder_count"]) + 1
            elif role == "hd_operator":
                day["hd_operator_count"] = int(day["hd_operator_count"]) + 1
            elif role == "hd_folder":
                day["hd_folder_count"] = int(day["hd_folder_count"]) + 1
            elif role == "attendant":
                day["attendant_count"] = int(day["attendant_count"]) + 1
            elif role == "non_rinse_folder":
                day["non_rinse_folder_count"] = int(day["non_rinse_folder_count"]) + 1
            if role == "wash":
                day["operator_count"] = int(day["operator_count"]) + 1
            if role == "fold":
                day["folder_count"] = int(day["folder_count"]) + 1

    for (uid, dow), hours in scheduled_hours_by_user_day(included_entries).items():
        rate = _worker_rate(workers_by_user_id.get(uid))
        totals = employee_totals[uid]
        totals["total_hours"] = round(totals["total_hours"] + hours, 2)
        totals["estimated_cost"] = round(totals["estimated_cost"] + calc_cost(hours, rate), 2)
        day = day_totals.get(dow) or day_totals[dow % 7]
        day["total_hours"] = round(float(day["total_hours"]) + hours, 2)

    role_hours_by_day = allocate_role_hours_by_day(included_entries)
    for dow, role_hours in enumerate(role_hours_by_day):
        day = day_totals[dow]
        day["wash_hours"] = float(role_hours.get("wash") or 0.0)
        day["sort_hours"] = float(role_hours.get("sort") or 0.0)
        day["fold_hours"] = float(role_hours.get("fold") or 0.0)
        day["pt_washer_hours"] = float(role_hours.get("pt_washer") or 0.0)
        day["pt_sorter_hours"] = float(role_hours.get("pt_sorter") or 0.0)
        day["pt_folder_hours"] = float(role_hours.get("pt_folder") or 0.0)

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
               role_assignments
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
               role_assignments
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
        role_storage = roles_to_storage(list(dict.fromkeys(a["role"] for a in assignments)))
        if len(role_storage) > ROLE_STORAGE_MAX:
            return None, "too many roles on one shift"
        out["role"] = role_storage
        out["role_assignments"] = role_assignments_storage(assignments)
    return out, None


def _load_role_catalog_index(cursor, organization_id: int) -> dict[str, dict[str, Any]]:
    from backend.weekly_schedule_roles import catalog_index, list_role_catalog

    return catalog_index(list_role_catalog(cursor, organization_id))


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
            role, start_time, end_time, break_minutes, employer_affiliation,
            role_assignments
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
            employer_affiliation=%s, role_assignments=%s
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
    }
    if existing.get("employer_affiliation"):
        duplicate_data["employer_affiliation"] = existing["employer_affiliation"]
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
                payload.get("role_assignments"),
            )
        )
    cursor.executemany(
        """
        INSERT INTO planned_weekly_schedule_entries (
            organization_id, week_start, user_id, day_of_week,
            role, start_time, end_time, break_minutes, employer_affiliation,
            role_assignments
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
    workers = _load_workers(conn, oid)
    # Affiliation=none workers must never be resurrected by cascade / carry-forward,
    # even when stale planned rows still exist on the source week.
    valid_user_ids = schedulable_worker_user_ids(conn, oid, workers)

    source_entries = list_week_entries(cursor, oid, week_start=source_week_start)
    source_exclusions = list_excluded_user_ids(cursor, oid, week_start=source_week_start)

    payloads: list[dict[str, Any]] = []
    skipped_entries = 0
    source_has_sunday = False
    for entry in source_entries:
        uid = int(entry.get("user_id") or 0)
        if uid not in valid_user_ids:
            skipped_entries += 1
            continue
        dow = int(entry.get("day_of_week") or 0)
        if dow == 0:
            source_has_sunday = True
        payloads.append(
            {
                "user_id": uid,
                "day_of_week": dow,
                "role": entry.get("role"),
                "start_time": entry["start_time"],
                "end_time": entry["end_time"],
                "break_minutes": entry.get("break_minutes", 0),
                "employer_affiliation": entry.get("employer_affiliation"),
                "role_assignments": role_assignments_storage(entry_role_assignments(entry)),
            }
        )

    # When cascading near week-end, the source Sunday column is often still empty
    # (that calendar Sunday is already in the past). Seed target Sunday from source
    # Saturday so tomorrow shows up in Team Status after a cascade.
    if not source_has_sunday:
        for entry in source_entries:
            if int(entry.get("day_of_week") or -1) != 6:
                continue
            uid = int(entry.get("user_id") or 0)
            if uid not in valid_user_ids:
                continue
            payloads.append(
                {
                    "user_id": uid,
                    "day_of_week": 0,
                    "role": entry.get("role"),
                    "start_time": entry["start_time"],
                    "end_time": entry["end_time"],
                    "break_minutes": entry.get("break_minutes", 0),
                    "employer_affiliation": entry.get("employer_affiliation"),
                    "role_assignments": role_assignments_storage(entry_role_assignments(entry)),
                }
            )

    entries_copied = 0
    if payloads:
        _bulk_insert_week_entries(cursor, oid, week_start=target_week_start, payloads=payloads)
        entries_copied = len(payloads)

    from backend.planned_weekly_schedule_responsibilities import copy_week_responsibilities

    responsibilities_copied = copy_week_responsibilities(
        cursor,
        oid,
        source_week_start=source_week_start,
        target_week_start=target_week_start,
        valid_user_ids=valid_user_ids,
        seed_sunday_from_saturday=not source_has_sunday,
    )

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
        "responsibilities_copied": responsibilities_copied,
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
    totals = compute_schedule_totals(
        entries,
        workers_by_uid,
        excluded_user_ids=excluded_user_ids,
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
    from backend.weekly_schedule_roles import list_role_catalog, role_groups_payload

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
        "role_catalog": list_role_catalog(cursor, organization_id),
        "role_groups": role_groups_payload(),
        "totals": totals,
        "excluded_user_ids": excluded_user_ids,
        "display": view,
        "entity_scope": entity_scope_payload(organization_id, org_slug, user_roles),
    }
    if view.get("lock_employer_tab"):
        return apply_rinse_viewer_scope(
            payload,
            hidden_roles=view.get("hidden_schedule_roles") or [],
        )
    return payload
