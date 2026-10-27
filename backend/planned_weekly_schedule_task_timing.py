"""Timing for a weekly-schedule task assignment.

The mode is stored on the assignment. Relative modes stay linked to each
employee's current shift and timed break; they are not copied into a clock time,
and they never change the shift or the break.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

TIMING_ANYTIME = "anytime"
TIMING_SPECIFIC = "specific_time"
TIMING_UPON_ENTRY = "upon_entry"
TIMING_BEFORE_BREAK = "before_break"
TIMING_AFTER_BREAK = "after_break"
TIMING_BEFORE_EXIT = "before_exit"

TIMING_MODES = (
    TIMING_ANYTIME,
    TIMING_SPECIFIC,
    TIMING_UPON_ENTRY,
    TIMING_BEFORE_BREAK,
    TIMING_AFTER_BREAK,
    TIMING_BEFORE_EXIT,
)

TIMING_LABELS = {
    TIMING_ANYTIME: "Anytime",
    TIMING_SPECIFIC: "Specific Time",
    TIMING_UPON_ENTRY: "Upon Entry",
    TIMING_BEFORE_BREAK: "Before Break",
    TIMING_AFTER_BREAK: "After Break",
    TIMING_BEFORE_EXIT: "Before Exit",
}

_BREAK_MODES = frozenset({TIMING_BEFORE_BREAK, TIMING_AFTER_BREAK})
_DAY = 24 * 60


def clock_label(value: Any) -> str:
    text = str(value or "")[:5]
    try:
        hour, minute = int(text[:2]), int(text[3:5])
    except (TypeError, ValueError):
        return text
    suffix = "AM" if hour < 12 else "PM"
    return f"{hour % 12 or 12}:{minute:02d} {suffix}"


def _minutes(value: Any) -> int | None:
    text = str(value or "")[:5]
    if len(text) < 4 or ":" not in text:
        return None
    try:
        hour, minute = int(text[:2]), int(text[3:5])
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def normalize_timing(
    mode: Any,
    start_time: Any = None,
    *,
    default_mode: str = TIMING_ANYTIME,
) -> tuple[dict[str, Any] | None, str | None]:
    raw = default_mode if mode in (None, "") else str(mode).strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "specific": TIMING_SPECIFIC,
        "entry": TIMING_UPON_ENTRY,
        "uponentry": TIMING_UPON_ENTRY,
        "beforebreak": TIMING_BEFORE_BREAK,
        "afterbreak": TIMING_AFTER_BREAK,
        "beforeexit": TIMING_BEFORE_EXIT,
    }
    resolved = aliases.get(raw, raw)
    if resolved not in TIMING_MODES:
        return None, "timing must be Anytime, Specific Time, Upon Entry, Before Break, After Break, or Before Exit"
    if resolved != TIMING_SPECIFIC:
        return {"timing_mode": resolved, "start_time": None}, None
    start = _minutes(start_time)
    if start is None:
        return None, "start time is required for Specific Time"
    hour, minute = divmod(start, 60)
    return {"timing_mode": resolved, "start_time": f"{hour:02d}:{minute:02d}"}, None


def timing_display(mode: Any, start_time: Any = None) -> str:
    resolved = str(mode or TIMING_ANYTIME)
    if resolved == TIMING_ANYTIME:
        return ""
    if resolved == TIMING_SPECIFIC:
        return clock_label(start_time)
    return TIMING_LABELS.get(resolved, "")


def _span(start: int, end: int) -> tuple[int, int]:
    if end <= start:
        end += _DAY
    return start, end


def _on_shift(point: int, start: int, end: int) -> int | None:
    span_start, span_end = _span(start, end)
    mapped = point if point >= span_start else point + _DAY
    if span_start <= mapped < span_end:
        return mapped
    return None


def _in_window(mapped_point: int, shift_start: int, window_start: int, window_end: int) -> bool:
    # Place the window on the same extended day as the shift start.
    start, end = window_start, window_end
    if end <= start:
        end += _DAY
    if start < shift_start:
        start += _DAY
        end += _DAY
    return start <= mapped_point < end


def _shift_breaks(shift: Mapping[str, Any]) -> list[tuple[int, int]]:
    slots = shift.get("break_slots") or []
    out: list[tuple[int, int]] = []
    for slot in slots:
        if not isinstance(slot, Mapping):
            continue
        start = _minutes(slot.get("start_time"))
        end = _minutes(slot.get("end_time"))
        if start is None or end is None or start == end:
            continue
        out.append((start, end))
    return out


def _covering_shift(shifts: Sequence[Mapping[str, Any]], point: int) -> Mapping[str, Any] | None:
    for shift in shifts:
        start = _minutes(shift.get("start_time"))
        end = _minutes(shift.get("end_time"))
        if start is None or end is None:
            continue
        if _on_shift(point, start, end) is not None:
            return shift
    return None


def _during_break(shift: Mapping[str, Any], point: int) -> bool:
    start = _minutes(shift.get("start_time"))
    end = _minutes(shift.get("end_time"))
    if start is None or end is None:
        return False
    mapped = _on_shift(point, start, end)
    if mapped is None:
        return False
    return any(_in_window(mapped, start, b0, b1) for b0, b1 in _shift_breaks(shift))


def _earliest_start(shifts: Sequence[Mapping[str, Any]]) -> str | None:
    found: list[tuple[int, str]] = []
    for shift in shifts:
        start = _minutes(shift.get("start_time"))
        if start is None or not shift.get("start_time"):
            continue
        found.append((start, str(shift.get("start_time"))[:5]))
    if not found:
        return None
    return min(found)[1]


def _latest_end(shifts: Sequence[Mapping[str, Any]]) -> str | None:
    found: list[tuple[int, str]] = []
    for shift in shifts:
        start = _minutes(shift.get("start_time"))
        end = _minutes(shift.get("end_time"))
        if start is None or end is None:
            continue
        _span_start, span_end = _span(start, end)
        found.append((span_end, str(shift.get("end_time"))[:5]))
    if not found:
        return None
    return max(found)[1]


def _break_anchor(shifts: Sequence[Mapping[str, Any]], *, after: bool) -> str | None:
    found: list[tuple[int, str]] = []
    for shift in shifts:
        start = _minutes(shift.get("start_time"))
        if start is None:
            continue
        for b0, b1 in _shift_breaks(shift):
            anchor = b1 if after else b0
            placed = anchor if anchor >= start else anchor + _DAY
            clock = f"{(anchor // 60) % 24:02d}:{anchor % 60:02d}"
            found.append((placed, clock))
    if not found:
        return None
    return min(found)[1]


def _has_unscheduled_break(shifts: Sequence[Mapping[str, Any]]) -> bool:
    for shift in shifts:
        try:
            minutes = int(shift.get("unscheduled_break_minutes") or 0)
        except (TypeError, ValueError):
            minutes = 0
        if minutes > 0 and not _shift_breaks(shift):
            return True
    return False


def _has_timed_break(shifts: Sequence[Mapping[str, Any]]) -> bool:
    return any(_shift_breaks(shift) for shift in shifts)


def evaluate_task_timing(
    *,
    timing_mode: str,
    start_time: str | None,
    members: Sequence[Mapping[str, Any]],
) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)``.

    Errors block a Specific Time that an assigned employee is not working
    (no shift, or the time falls in their scheduled break). Relative modes
    stay saved and surface a warning when a shift or break is missing, or
    when a group does not share the same anchor.
    """
    mode = str(timing_mode or TIMING_ANYTIME)
    if mode == TIMING_ANYTIME or not members:
        return [], []
    label = TIMING_LABELS.get(mode, mode)
    errors: list[str] = []
    warnings: list[str] = []

    if mode == TIMING_SPECIFIC:
        point = _minutes(start_time)
        when = clock_label(start_time)
        if point is None:
            return ["start time is required for Specific Time"], []
        for member in members:
            name = str(member.get("name") or "Employee")
            shifts = list(member.get("shifts") or [])
            shift = _covering_shift(shifts, point)
            if shift is None:
                errors.append(f"{name} is not scheduled at {when}")
            elif _during_break(shift, point):
                errors.append(f"{name} is on a scheduled break at {when}")
        return errors, []

    anchors: list[tuple[str, str]] = []
    for member in members:
        name = str(member.get("name") or "Employee")
        shifts = list(member.get("shifts") or [])
        if mode == TIMING_UPON_ENTRY:
            anchor = _earliest_start(shifts)
            if anchor is None:
                warnings.append(f"{name} has no shift on this day, so Upon Entry has no start to follow")
            else:
                anchors.append((name, clock_label(anchor)))
        elif mode == TIMING_BEFORE_EXIT:
            anchor = _latest_end(shifts)
            if anchor is None:
                warnings.append(f"{name} has no shift on this day, so Before Exit has no end to follow")
            else:
                anchors.append((name, clock_label(anchor)))
        elif mode in _BREAK_MODES:
            if not _has_timed_break(shifts):
                if _has_unscheduled_break(shifts):
                    warnings.append(f"{name}'s break has no time, so {label} cannot be placed")
                else:
                    warnings.append(f"{name} has no scheduled break, so {label} cannot be placed")
            else:
                anchor = _break_anchor(shifts, after=mode == TIMING_AFTER_BREAK)
                if anchor:
                    anchors.append((name, clock_label(anchor)))
    distinct = {clock for _name, clock in anchors}
    if len(members) > 1 and len(distinct) > 1:
        detail = ", ".join(f"{name} {clock}" for name, clock in anchors)
        warnings.append(f"{label} differs across the group: {detail}")
    return errors, warnings
