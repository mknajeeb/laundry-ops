"""Operations Planner v2 — recurrence, exceptions, and publication.

Planned rows stay in ``planned_weekly_schedule_entries``. This module decides
which weeks a manager's edit is allowed to change, and it never writes
attendance, punches, or payroll.

Business weeks are Monday–Sunday in America/New_York, matching
``weekly_schedule_week.current_schedule_monday``.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

from backend.business_time import business_now
from backend.weekly_schedule_week import current_schedule_monday, parse_schedule_date

SCOPES = ("this_week", "this_and_future", "future_only", "selected_weeks")
ACTIONS = ("upsert", "delete", "move", "copy")
LOCKED_STATUSES = ("approved", "published")
HORIZON_WEEKS = 16
BREAK_OVERLAP_CAP = 3

DAY_NAMES = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")


def empty_state() -> dict[str, Any]:
    return {
        "patterns": [],
        "exceptions": [],
        "weeks": {},
        "next_pattern_id": 1,
        "next_exception_id": 1,
        "audit": [],
    }


def _monday(raw: Any) -> date | None:
    parsed = parse_schedule_date(raw)
    if parsed is None:
        return None
    return parsed - timedelta(days=parsed.weekday())


def _iso(day: date) -> str:
    return day.isoformat()


def _as_monday_list(raw: Sequence[Any] | None) -> list[date]:
    found: list[date] = []
    seen: set[date] = set()
    for item in raw or []:
        monday = _monday(item)
        if monday is None or monday in seen:
            continue
        seen.add(monday)
        found.append(monday)
    return sorted(found)


def _hhmm(value: Any) -> str | None:
    text = str(value or "").strip()
    if len(text) < 4:
        return None
    if "T" in text:
        text = text.split("T", 1)[1]
    text = text[:5]
    if len(text) != 5 or text[2] != ":":
        return None
    try:
        hour = int(text[:2])
        minute = int(text[3:5])
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def clock_minutes(value: Any) -> int | None:
    text = _hhmm(value)
    if text is None:
        return None
    hour, minute = text.split(":")
    return int(hour) * 60 + int(minute)


def span_minutes(start: Any, end: Any) -> int | None:
    begin = clock_minutes(start)
    finish = clock_minutes(end)
    if begin is None or finish is None or begin == finish:
        return None
    if finish <= begin:
        finish += 24 * 60
    return finish - begin


def _interval(start: Any, end: Any) -> tuple[int, int] | None:
    begin = clock_minutes(start)
    length = span_minutes(start, end)
    if begin is None or length is None:
        return None
    return begin, begin + length


def _overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def normalize_shift(raw: Mapping[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    if raw is None:
        return None, "shift is required"
    start = _hhmm(raw.get("start_time"))
    end = _hhmm(raw.get("end_time"))
    if start is None or end is None:
        return None, "start_time and end_time must be HH:MM"
    window = _interval(start, end)
    if window is None:
        return None, "shift must have a duration"
    try:
        break_minutes = int(raw.get("break_minutes") or 0)
    except (TypeError, ValueError):
        return None, "break_minutes must be a number"
    if break_minutes < 0:
        return None, "break_minutes cannot be negative"

    slots: list[dict[str, Any]] = []
    for item in raw.get("break_slots") or []:
        if not isinstance(item, Mapping):
            return None, "break_slots must be objects"
        slot_start = _hhmm(item.get("start_time"))
        slot_end = _hhmm(item.get("end_time"))
        piece = _interval(slot_start, slot_end) if slot_start and slot_end else None
        if piece is None:
            return None, "each break needs a start and end"
        if piece[0] < window[0] or piece[1] > window[1]:
            return None, "breaks must sit inside the shift"
        timed = item.get("timed")
        if timed is None:
            timed = True
        slots.append(
            {
                "start_time": slot_start,
                "end_time": slot_end,
                "timed": bool(timed),
            }
        )
    timed_pieces = [_interval(slot["start_time"], slot["end_time"]) for slot in slots if slot["timed"]]
    for index, piece in enumerate(timed_pieces):
        if piece is None:
            continue
        for other in timed_pieces[index + 1 :]:
            if other is not None and _overlaps(piece, other):
                return None, "timed breaks cannot overlap"

    assignments: list[dict[str, str]] = []
    for item in raw.get("role_assignments") or []:
        if not isinstance(item, Mapping):
            return None, "role_assignments must be objects"
        role = str(item.get("role") or "").strip()
        role_start = _hhmm(item.get("start_time"))
        role_end = _hhmm(item.get("end_time"))
        piece = _interval(role_start, role_end) if role and role_start and role_end else None
        if piece is None:
            return None, "each role segment needs a role, start, and end"
        if piece[0] < window[0] or piece[1] > window[1]:
            return None, "role segments must sit inside the shift"
        assignments.append({"role": role, "start_time": role_start, "end_time": role_end})
    for index, item in enumerate(assignments):
        piece = _interval(item["start_time"], item["end_time"])
        if piece is None:
            continue
        for other in assignments[index + 1 :]:
            other_piece = _interval(other["start_time"], other["end_time"])
            if other_piece is not None and _overlaps(piece, other_piece):
                return None, "role segments cannot overlap for the same employee"

    role = str(raw.get("role") or (assignments[0]["role"] if assignments else "")).strip()
    if not role:
        return None, "a role is required"
    tasks = []
    for item in raw.get("tasks") or []:
        if isinstance(item, Mapping) and str(item.get("name") or item.get("role") or "").strip():
            tasks.append(
                {
                    "name": str(item.get("name") or item.get("role")).strip(),
                    "shared": bool(item.get("shared") or item.get("assignment_group_id")),
                    "category": str(item.get("category") or item.get("role") or "").strip(),
                }
            )
    return (
        {
            "start_time": start,
            "end_time": end,
            "break_minutes": break_minutes,
            "break_slots": slots,
            "role": role,
            "role_assignments": assignments,
            "tasks": tasks,
        },
        None,
    )


def shift_hours(shift: Mapping[str, Any] | None) -> dict[str, float]:
    if not shift:
        return {"gross": 0.0, "net": 0.0, "timed_break": 0.0}
    gross_min = span_minutes(shift.get("start_time"), shift.get("end_time")) or 0
    timed_min = 0
    slots = list(shift.get("break_slots") or [])
    for slot in slots:
        if slot.get("timed", True):
            timed_min += span_minutes(slot.get("start_time"), slot.get("end_time")) or 0
    if not slots:
        try:
            timed_min = max(0, int(shift.get("break_minutes") or 0))
        except (TypeError, ValueError):
            timed_min = 0
    net_min = max(0, gross_min - timed_min)
    return {
        "gross": round(gross_min / 60.0, 4),
        "net": round(net_min / 60.0, 4),
        "timed_break": round(timed_min / 60.0, 4),
    }


def _week_status(state: Mapping[str, Any], monday: date) -> dict[str, Any]:
    current = (state.get("weeks") or {}).get(_iso(monday))
    if not isinstance(current, Mapping):
        return {"status": "draft", "revision": 1, "published_snapshot": None, "published_revision": None}
    return {
        "status": str(current.get("status") or "draft"),
        "revision": int(current.get("revision") or 1),
        "published_snapshot": current.get("published_snapshot"),
        "published_revision": current.get("published_revision"),
    }


def _pattern_covers(pattern: Mapping[str, Any], monday: date) -> bool:
    start = pattern.get("effective_from")
    end = pattern.get("effective_until")
    if not isinstance(start, date) or start > monday:
        return False
    return end is None or (isinstance(end, date) and monday < end)


def active_pattern(
    state: Mapping[str, Any],
    user_id: int,
    day_of_week: int,
    monday: date,
) -> dict[str, Any] | None:
    chosen: dict[str, Any] | None = None
    for pattern in state.get("patterns") or []:
        if int(pattern.get("user_id") or 0) != int(user_id):
            continue
        if int(pattern.get("day_of_week") or -1) != int(day_of_week):
            continue
        if not _pattern_covers(pattern, monday):
            continue
        if chosen is None or pattern["effective_from"] >= chosen["effective_from"]:
            chosen = pattern
    return chosen


def find_exception(
    state: Mapping[str, Any],
    user_id: int,
    day_of_week: int,
    monday: date,
) -> dict[str, Any] | None:
    for row in state.get("exceptions") or []:
        if int(row.get("user_id") or 0) != int(user_id):
            continue
        if int(row.get("day_of_week") or -1) != int(day_of_week):
            continue
        if row.get("week_monday") == monday:
            return row
    return None


def cell_shift(
    state: Mapping[str, Any],
    user_id: int,
    day_of_week: int,
    monday: date,
) -> dict[str, Any] | None:
    row = find_exception(state, user_id, day_of_week, monday)
    if row is not None:
        if row.get("kind") == "deleted":
            return None
        shift = row.get("shift")
        return deepcopy(shift) if isinstance(shift, Mapping) else None
    pattern = active_pattern(state, user_id, day_of_week, monday)
    if pattern is None:
        return None
    shift = pattern.get("shift")
    return deepcopy(shift) if isinstance(shift, Mapping) else None


def target_weeks(
    *,
    scope: str,
    anchor: date,
    selected: Sequence[Any] | None,
    today: date,
    horizon_weeks: int = HORIZON_WEEKS,
) -> tuple[list[date] | None, str | None]:
    if scope not in SCOPES:
        return None, "choose how broadly to apply this change"
    floor = current_schedule_monday(today)
    anchor_monday = _monday(anchor)
    if anchor_monday is None:
        return None, "week must be a Monday"

    def span(start: date) -> list[date]:
        weeks: list[date] = []
        cursor = start
        for _ in range(max(1, int(horizon_weeks))):
            if cursor >= floor:
                weeks.append(cursor)
            cursor += timedelta(days=7)
        return weeks

    if scope == "this_week":
        weeks = [anchor_monday] if anchor_monday >= floor else []
    elif scope == "this_and_future":
        weeks = span(anchor_monday)
    elif scope == "future_only":
        weeks = span(anchor_monday + timedelta(days=7))
    else:
        weeks = [week for week in _as_monday_list(selected) if week >= floor]
    if not weeks:
        return None, "historical schedules, punches, and payroll cannot be changed"
    return weeks, None


def _ids(raw: Any, fallback: int | None = None) -> list[int]:
    values: list[int] = []
    source = raw if isinstance(raw, (list, tuple)) else ([] if raw is None else [raw])
    for item in source:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in values:
            values.append(number)
    if not values and fallback:
        values.append(int(fallback))
    return values


def _days(command: Mapping[str, Any]) -> list[int]:
    raw = command.get("days")
    source = raw if isinstance(raw, (list, tuple)) and raw else [command.get("day_of_week")]
    days: list[int] = []
    for item in source:
        try:
            day = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6 and day not in days:
            days.append(day)
    return days


def _pattern_start(scope: str, anchor: date) -> date | None:
    if scope == "this_and_future":
        return anchor
    if scope == "future_only":
        return anchor + timedelta(days=7)
    return None


def _retire_patterns(
    patterns: Sequence[Mapping[str, Any]],
    *,
    user_id: int,
    day_of_week: int,
    start: date,
) -> list[dict[str, Any]]:
    retired: list[dict[str, Any]] = []
    for pattern in patterns:
        row = dict(pattern)
        if int(row.get("user_id") or 0) == int(user_id) and int(row.get("day_of_week") or -1) == int(day_of_week):
            begin = row.get("effective_from")
            end = row.get("effective_until")
            if isinstance(begin, date) and begin >= start:
                row["effective_until"] = begin
            elif isinstance(begin, date) and (end is None or (isinstance(end, date) and end > start)):
                row["effective_until"] = start
        retired.append(row)
    return retired


def _put_exception(
    exceptions: list[dict[str, Any]],
    *,
    next_id: int,
    user_id: int,
    day_of_week: int,
    monday: date,
    kind: str,
    shift: Mapping[str, Any] | None,
) -> int:
    kept = [
        row
        for row in exceptions
        if not (
            int(row.get("user_id") or 0) == int(user_id)
            and int(row.get("day_of_week") or -1) == int(day_of_week)
            and row.get("week_monday") == monday
        )
    ]
    exceptions[:] = kept
    exceptions.append(
        {
            "id": next_id,
            "user_id": int(user_id),
            "day_of_week": int(day_of_week),
            "week_monday": monday,
            "kind": kind,
            "shift": deepcopy(dict(shift)) if isinstance(shift, Mapping) else None,
        }
    )
    return next_id + 1


def _drop_exception(
    exceptions: list[dict[str, Any]],
    *,
    user_id: int,
    day_of_week: int,
    monday: date,
) -> None:
    exceptions[:] = [
        row
        for row in exceptions
        if not (
            int(row.get("user_id") or 0) == int(user_id)
            and int(row.get("day_of_week") or -1) == int(day_of_week)
            and row.get("week_monday") == monday
        )
    ]


def plan_entry_write(
    existing: Sequence[Mapping[str, Any]],
    new_shift: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """One planned shift per employee per day. Never insert a second copy."""
    rows = [row for row in existing if isinstance(row, Mapping)]
    if len(rows) > 1:
        return {
            "ok": False,
            "error": "multiple shifts already exist for this employee and day",
        }
    if new_shift is None:
        if not rows:
            return {"ok": True, "action": "none"}
        return {"ok": True, "action": "delete", "entry_id": rows[0].get("id")}
    if not rows:
        return {"ok": True, "action": "create"}
    return {"ok": True, "action": "update", "entry_id": rows[0].get("id")}


def _known_users(state: Mapping[str, Any], extra: Sequence[int]) -> list[int]:
    found: list[int] = []
    for collection in (state.get("patterns") or [], state.get("exceptions") or []):
        for row in collection:
            try:
                user_id = int(row.get("user_id") or 0)
            except (TypeError, ValueError):
                continue
            if user_id > 0 and user_id not in found:
                found.append(user_id)
    for user_id in extra:
        if int(user_id) not in found:
            found.append(int(user_id))
    return found


def break_overlap_warnings(
    shifts: Sequence[tuple[int, Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Warn when more than three employees have overlapping timed breaks."""
    pieces: list[tuple[int, int, int]] = []
    for user_id, shift in shifts:
        for slot in shift.get("break_slots") or []:
            if not slot.get("timed", True):
                continue
            interval = _interval(slot.get("start_time"), slot.get("end_time"))
            if interval is not None:
                pieces.append((int(user_id), interval[0], interval[1]))
    warnings: list[dict[str, Any]] = []
    points = sorted({point for _, start, end in pieces for point in (start, end)})
    for left, right in zip(points, points[1:]):
        if right <= left:
            continue
        active = [user_id for user_id, start, end in pieces if start <= left and end >= right]
        unique = list(dict.fromkeys(active))
        if len(unique) > BREAK_OVERLAP_CAP:
            warnings.append(
                {
                    "start_minute": left,
                    "end_minute": right,
                    "count": len(unique),
                    "user_ids": unique,
                }
            )
    return warnings


def hour_coverage(
    shifts: Sequence[tuple[int, Mapping[str, Any]]],
    *,
    hour: int,
) -> dict[str, Any]:
    """Scheduled staff stay scheduled on break. Timed breaks leave the available count."""
    begin = int(hour) * 60
    end = begin + 60
    window = (begin, end)
    scheduled: list[int] = []
    on_break: list[int] = []
    for user_id, shift in shifts:
        interval = _interval(shift.get("start_time"), shift.get("end_time"))
        if interval is None or not _overlaps(interval, window):
            continue
        scheduled.append(int(user_id))
        timed = False
        for slot in shift.get("break_slots") or []:
            if not slot.get("timed", True):
                continue
            piece = _interval(slot.get("start_time"), slot.get("end_time"))
            if piece is not None and _overlaps(piece, window):
                timed = True
                break
        if timed:
            on_break.append(int(user_id))
    available = [user_id for user_id in scheduled if user_id not in on_break]
    return {
        "hour": int(hour),
        "scheduled": scheduled,
        "on_break": on_break,
        "available": available,
        "scheduled_count": len(scheduled),
        "available_count": len(available),
    }


def _describe_shift(shift: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not shift:
        return None
    hours = shift_hours(shift)
    return {
        "start_time": shift.get("start_time"),
        "end_time": shift.get("end_time"),
        "role": shift.get("role"),
        "roles": [item.get("role") for item in shift.get("role_assignments") or []] or [shift.get("role")],
        "breaks": list(shift.get("break_slots") or []),
        "tasks": list(shift.get("tasks") or []),
        "gross_hours": hours["gross"],
        "net_hours": hours["net"],
    }


def employee_schedule_view(snapshot: Mapping[str, Any] | None, user_id: int) -> dict[str, Any] | None:
    """Drop every other employee's rows before a PIN response leaves the server."""
    if not isinstance(snapshot, Mapping):
        return None
    uid = int(user_id)

    def own(rows: Any) -> list[dict[str, Any]]:
        kept = []
        for row in rows or []:
            if isinstance(row, Mapping) and int(row.get("user_id") or 0) == uid:
                kept.append(deepcopy(dict(row)))
        return kept

    return {
        "week_start": snapshot.get("week_start"),
        "entries": own(snapshot.get("entries")),
        "responsibilities": own(
            snapshot.get("responsibilities") or snapshot.get("daily_responsibilities")
        ),
    }


def employee_visible_snapshot(state: Mapping[str, Any], monday: date) -> dict[str, Any] | None:
    """Employees see the latest published snapshot, including while a newer draft exists."""
    status = _week_status(state, monday)
    snapshot = status.get("published_snapshot")
    if not isinstance(snapshot, Mapping):
        return None
    return deepcopy(dict(snapshot))


def employee_module_visible(
    *,
    pilot_enabled: bool,
    employee_enabled: bool,
    published_snapshot: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not pilot_enabled or not employee_enabled:
        return {"visible": False, "reason": "disabled"}
    if not published_snapshot:
        return {"visible": False, "reason": "unpublished"}
    return {"visible": True, "reason": "published", "schedule": deepcopy(dict(published_snapshot))}


def paystub_decision(
    *,
    module_enabled: bool,
    employee_enabled: bool,
    worker_category: str | None,
    step_up_ok: bool,
    second_factor_on_file: bool,
    document_available: bool,
) -> str:
    """Return ``ok`` only for a verified W-2 employee with a real payroll document."""
    if not module_enabled:
        return "module_disabled"
    if not employee_enabled:
        return "employee_disabled"
    if str(worker_category or "").strip().lower() != "w2":
        return "not_w2"
    if not second_factor_on_file:
        return "second_factor_unavailable"
    if not step_up_ok:
        return "step_up_required"
    if not document_available:
        return "no_authoritative_document"
    return "ok"


def verify_step_up_factors(
    *,
    pin_ok: bool,
    dob_supplied: date | None,
    dob_on_file: date | None,
) -> tuple[bool, str]:
    if dob_on_file is None:
        return False, "second_factor_unavailable"
    if not pin_ok or dob_supplied != dob_on_file:
        return False, "verification_failed"
    return True, "ok"


def role_visible_to_rinse(
    role: str,
    *,
    show_on_rinse_dashboard: bool,
    hidden_by_labor_policy: Sequence[str],
) -> bool:
    """A planner toggle cannot reveal a role labor policy already hides."""
    hidden = {str(item).strip() for item in hidden_by_labor_policy if str(item).strip()}
    if role in hidden:
        return False
    return bool(show_on_rinse_dashboard)


def plan_change(state: Mapping[str, Any], command: Mapping[str, Any]) -> dict[str, Any]:
    """Pure schedule change. Returns a new state and the cells to materialize."""
    action = str(command.get("action") or "").strip()
    scope = str(command.get("scope") or "").strip()
    if action not in ACTIONS:
        return {"ok": False, "code": "invalid_action", "error": "unsupported schedule action"}
    today = parse_schedule_date(command.get("today"))
    anchor = _monday(command.get("anchor"))
    if today is None or anchor is None:
        return {"ok": False, "code": "invalid_date", "error": "a business date and week are required"}
    days = _days(command)
    if not days:
        return {"ok": False, "code": "invalid_day", "error": "day_of_week must be 0-6"}
    source_user = _ids(command.get("user_id"))
    if action == "copy":
        targets = _ids(command.get("user_ids"), source_user[0] if source_user else None)
    else:
        targets = _ids(command.get("user_ids"), source_user[0] if source_user else None)
        if not source_user:
            source_user = targets[:1]
    if not targets:
        return {"ok": False, "code": "invalid_employee", "error": "an employee is required"}
    if action == "move" and len(targets) != 1:
        return {"ok": False, "code": "invalid_move", "error": "move one employee at a time"}

    shift: dict[str, Any] | None = None
    if action != "delete":
        shift, shift_err = normalize_shift(command.get("shift"))
        if shift_err:
            return {"ok": False, "code": "invalid_shift", "error": shift_err}
    if action == "move":
        if not isinstance(command.get("previous_shift"), Mapping):
            return {"ok": False, "code": "invalid_shift", "error": "move needs the current shift"}
        previous, prev_err = normalize_shift(command.get("previous_shift"))
        if prev_err or shift is None or previous is None:
            return {"ok": False, "code": "invalid_shift", "error": prev_err or "move needs the current shift"}
        if span_minutes(previous["start_time"], previous["end_time"]) != span_minutes(
            shift["start_time"], shift["end_time"]
        ):
            return {"ok": False, "code": "resize_rejected", "error": "moving a shift cannot change its length"}

    weeks, week_err = target_weeks(
        scope=scope,
        anchor=anchor,
        selected=command.get("selected_weeks"),
        today=today,
        horizon_weeks=int(command.get("horizon_weeks") or HORIZON_WEEKS),
    )
    if week_err or weeks is None:
        return {"ok": False, "code": "immutable_history", "error": week_err}

    from_day = command.get("from_day_of_week", command.get("from_day"))
    try:
        source_day = int(from_day) if from_day is not None else days[0]
    except (TypeError, ValueError):
        source_day = days[0]
    from_user = int(command.get("from_user_id") or 0) or (source_user[0] if source_user else targets[0])

    draft = deepcopy(dict(state))
    draft.setdefault("patterns", [])
    draft.setdefault("exceptions", [])
    draft.setdefault("weeks", {})
    draft.setdefault("audit", [])
    next_pattern = int(draft.get("next_pattern_id") or 1)
    next_exception = int(draft.get("next_exception_id") or 1)

    locked: list[str] = []
    exception_weeks: list[str] = []
    for week in weeks:
        status = _week_status(draft, week)
        if status["status"] in LOCKED_STATUSES:
            locked.append(_iso(week))
        if scope in ("this_and_future", "future_only") and week != anchor:
            watched = [(user_id, day) for user_id in targets for day in days]
            if action == "move":
                watched.append((from_user, source_day))
            for user_id, day in watched:
                if find_exception(draft, user_id, day, week) is not None:
                    exception_weeks.append(_iso(week))
                    break
    locked = list(dict.fromkeys(locked))
    exception_weeks = list(dict.fromkeys(exception_weeks))

    include_published = command.get("include_published")
    replace_exceptions = command.get("replace_exceptions")
    questions: list[str] = []
    if locked and include_published is None:
        questions.append("published")
    if exception_weeks and replace_exceptions is None:
        questions.append("exceptions")
    preview_people = []
    for user_id in targets:
        preview_people.append(
            {
                "user_id": int(user_id),
                "days": [
                    {
                        "day_of_week": day,
                        "day_name": DAY_NAMES[day],
                        "shift": _describe_shift(shift),
                    }
                    for day in days
                ],
            }
        )
    preview = {
        "scope": scope,
        "action": action,
        "dates": [_iso(week) for week in weeks],
        "employees": preview_people,
        "approved_or_published_weeks": locked,
        "exception_weeks": exception_weeks,
        "shift": _describe_shift(shift),
    }
    if questions:
        return {
            "ok": False,
            "code": "confirmation_required",
            "questions": questions,
            "preview": preview,
            "error": "confirm the weeks this change should update",
        }

    write_weeks = list(weeks)
    frozen_weeks: list[date] = []
    if locked and include_published is False:
        frozen_weeks.extend(week for week in write_weeks if _iso(week) in locked)
        write_weeks = [week for week in write_weeks if _iso(week) not in locked]
    if exception_weeks and replace_exceptions is False:
        frozen_weeks.extend(week for week in write_weeks if _iso(week) in exception_weeks)
        write_weeks = [week for week in write_weeks if _iso(week) not in exception_weeks]
    frozen_weeks = sorted(set(frozen_weeks))
    if not write_weeks and not frozen_weeks:
        return {"ok": False, "code": "nothing_to_apply", "error": "no editable weeks were selected", "preview": preview}

    pattern_start = _pattern_start(scope, anchor)
    cell_plans: list[dict[str, Any]] = []

    def freeze(user_id: int, day: int, week: date) -> None:
        nonlocal next_exception
        current = cell_shift(draft, user_id, day, week)
        kind = "deleted" if current is None else "override"
        next_exception = _put_exception(
            draft["exceptions"],
            next_id=next_exception,
            user_id=user_id,
            day_of_week=day,
            monday=week,
            kind=kind,
            shift=current,
        )

    for week in frozen_weeks:
        for user_id in targets:
            for day in days:
                freeze(user_id, day, week)
        if action == "move":
            freeze(from_user, source_day, week)

    if pattern_start is not None and action in ("upsert", "move", "copy", "delete"):
        for user_id in targets:
            for day in days:
                draft["patterns"] = _retire_patterns(
                    draft["patterns"], user_id=user_id, day_of_week=day, start=pattern_start
                )
                if action != "delete" and shift is not None:
                    draft["patterns"].append(
                        {
                            "id": next_pattern,
                            "user_id": int(user_id),
                            "day_of_week": int(day),
                            "effective_from": pattern_start,
                            "effective_until": None,
                            "shift": deepcopy(shift),
                        }
                    )
                    next_pattern += 1
        if action == "move" and (from_user != targets[0] or source_day != days[0]):
            draft["patterns"] = _retire_patterns(
                draft["patterns"], user_id=from_user, day_of_week=source_day, start=pattern_start
            )

    for week in write_weeks:
        for user_id in targets:
            for day in days:
                if scope in ("this_week", "selected_weeks"):
                    next_exception = _put_exception(
                        draft["exceptions"],
                        next_id=next_exception,
                        user_id=user_id,
                        day_of_week=day,
                        monday=week,
                        kind="deleted" if action == "delete" else "override",
                        shift=None if action == "delete" else shift,
                    )
                else:
                    _drop_exception(draft["exceptions"], user_id=user_id, day_of_week=day, monday=week)
                cell_plans.append(
                    {
                        "week_monday": _iso(week),
                        "user_id": int(user_id),
                        "day_of_week": int(day),
                        "shift": cell_shift(draft, user_id, day, week),
                    }
                )
        if action == "move" and (from_user != targets[0] or source_day != days[0]):
            if scope in ("this_week", "selected_weeks"):
                next_exception = _put_exception(
                    draft["exceptions"],
                    next_id=next_exception,
                    user_id=from_user,
                    day_of_week=source_day,
                    monday=week,
                    kind="deleted",
                    shift=None,
                )
            else:
                _drop_exception(
                    draft["exceptions"], user_id=from_user, day_of_week=source_day, monday=week
                )
            cell_plans.append(
                {
                    "week_monday": _iso(week),
                    "user_id": int(from_user),
                    "day_of_week": int(source_day),
                    "shift": cell_shift(draft, from_user, source_day, week),
                }
            )
        status = _week_status(draft, week)
        if status["status"] in LOCKED_STATUSES:
            status = {
                **status,
                "status": "draft",
                "revision": int(status["revision"]) + 1,
            }
        draft["weeks"][_iso(week)] = status

    warnings = []
    users = _known_users(draft, targets)
    for week in write_weeks:
        for day in days:
            day_shifts = []
            for user_id in users:
                planned = cell_shift(draft, user_id, day, week)
                if planned is not None:
                    day_shifts.append((user_id, planned))
            for warning in break_overlap_warnings(day_shifts):
                warning["week_monday"] = _iso(week)
                warning["day_of_week"] = day
                warnings.append(warning)

    draft["next_pattern_id"] = next_pattern
    draft["next_exception_id"] = next_exception
    audit = {
        "action": action,
        "scope": scope,
        "anchor": _iso(anchor),
        "user_ids": [int(user_id) for user_id in targets],
        "days": days,
        "write_weeks": [_iso(week) for week in write_weeks],
        "frozen_weeks": [_iso(week) for week in frozen_weeks],
        "include_published": include_published,
        "replace_exceptions": replace_exceptions,
        "at": business_now().isoformat(timespec="seconds"),
    }
    draft["audit"] = list(draft.get("audit") or []) + [audit]
    republish = [
        _iso(week)
        for week in write_weeks
        if _week_status(state, week)["status"] in LOCKED_STATUSES
    ]
    return {
        "ok": True,
        "code": "applied",
        "state": draft,
        "preview": preview,
        "cell_plans": cell_plans,
        "write_weeks": [_iso(week) for week in write_weeks],
        "frozen_weeks": [_iso(week) for week in frozen_weeks],
        "republish_required": republish,
        "warnings": warnings,
        "audit": audit,
    }


def approve_weeks(state: Mapping[str, Any], weeks: Sequence[Any]) -> dict[str, Any]:
    draft = deepcopy(dict(state))
    changed: list[str] = []
    for raw in weeks:
        monday = _monday(raw)
        if monday is None:
            return {"ok": False, "error": "week must be a Monday"}
        status = _week_status(draft, monday)
        if status["status"] == "approved":
            changed.append(_iso(monday))
            continue
        if status["status"] != "draft":
            return {"ok": False, "error": f"{_iso(monday)} must be a draft before approval"}
        draft["weeks"][_iso(monday)] = {**status, "status": "approved"}
        changed.append(_iso(monday))
    return {"ok": True, "state": draft, "weeks": changed}


def publish_weeks(
    state: Mapping[str, Any],
    weeks: Sequence[Any],
    snapshots: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    draft = deepcopy(dict(state))
    changed: list[str] = []
    for raw in weeks:
        monday = _monday(raw)
        if monday is None:
            return {"ok": False, "error": "week must be a Monday"}
        key = _iso(monday)
        status = _week_status(draft, monday)
        if status["status"] != "approved":
            return {"ok": False, "error": f"{key} must be approved before publication"}
        snapshot = snapshots.get(key)
        if not isinstance(snapshot, Mapping):
            return {"ok": False, "error": f"{key} has no schedule snapshot to publish"}
        draft["weeks"][key] = {
            **status,
            "status": "published",
            "published_snapshot": deepcopy(dict(snapshot)),
            "published_revision": status["revision"],
        }
        changed.append(key)
    return {"ok": True, "state": draft, "weeks": changed}


def patterns_overlap(state: Mapping[str, Any]) -> bool:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for pattern in state.get("patterns") or []:
        end = pattern.get("effective_until")
        start = pattern.get("effective_from")
        if not isinstance(start, date):
            return True
        if isinstance(end, date) and end <= start:
            continue
        key = (int(pattern.get("user_id") or 0), int(pattern.get("day_of_week") or -1))
        grouped.setdefault(key, []).append(pattern)
    for rows in grouped.values():
        rows.sort(key=lambda row: row["effective_from"])
        for left, right in zip(rows, rows[1:]):
            left_end = left.get("effective_until")
            if left_end is None or right["effective_from"] < left_end:
                return True
    return False
