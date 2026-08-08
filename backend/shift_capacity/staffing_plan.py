"""Management staffing-plan normalization and compilation into Employee calendars.

Authoring may use BASE + ADDITIONAL intervals. The scheduler source of truth is
canonical effective-headcount segments (people summed over overlaps).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.shift_capacity.models import (
    Employee,
    EmployeeScheduleWindow,
    ValidationError,
)
from backend.shift_capacity.timebase import label_seconds, parse_clock_seconds
from backend.shift_capacity.validation import _normalize_role

MANAGEMENT_ROLES = ("weigher", "sorter", "washer", "dryer", "folder")
ROLE_PREFIX = {
    "weigher": "MGMT_WEIGH",
    "sorter": "MGMT_SORT",
    "washer": "MGMT_WASH",
    "dryer": "MGMT_DRY",
    "folder": "MGMT_FOLD",
}


@dataclass
class AuthoredInterval:
    role: str
    people: int
    start_sec: int
    end_sec: int
    mode: str = "base"  # base | additional (authoring metadata only)


@dataclass
class CanonicalSegment:
    role: str
    start_sec: int
    end_sec: int
    people: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "start": label_seconds(self.start_sec),
            "end": label_seconds(self.end_sec),
            "start_sec": self.start_sec,
            "end_sec": self.end_sec,
            "people": self.people,
        }


@dataclass
class StaffingPlanResult:
    authored: list[AuthoredInterval] = field(default_factory=list)
    normalized_intervals: list[CanonicalSegment] = field(default_factory=list)
    employees: list[Employee] = field(default_factory=list)
    errors: list[ValidationError] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "authored_intervals": [
                {
                    "role": a.role,
                    "people": a.people,
                    "start": label_seconds(a.start_sec),
                    "end": label_seconds(a.end_sec),
                    "start_sec": a.start_sec,
                    "end_sec": a.end_sec,
                    "mode": a.mode,
                }
                for a in self.authored
            ],
            "normalized_intervals": [s.as_dict() for s in self.normalized_intervals],
            "compiled_resources": [
                {
                    "id": e.employee_id,
                    "role": e.primary_role,
                    "windows": [
                        {
                            "start": label_seconds(w.start_min),
                            "end": label_seconds(w.end_min),
                            "start_sec": w.start_min,
                            "end_sec": w.end_min,
                        }
                        for w in e.schedule_windows
                    ],
                }
                for e in self.employees
            ],
        }


def parse_and_compile_staffing_plan(
    raw_plan: Any,
    *,
    plan_start_sec: int,
    plan_target_sec: int,
    plan_end_sec: int | None = None,
) -> StaffingPlanResult:
    """Validate, normalize, and compile a management staffing_plan."""
    result = StaffingPlanResult()
    if raw_plan is None:
        return result
    if not isinstance(raw_plan, dict):
        result.errors.append(
            ValidationError("STAFFING_PLAN_INVALID", "staffing_plan must be an object")
        )
        return result

    rows = raw_plan.get("intervals")
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        result.errors.append(
            ValidationError("STAFFING_PLAN_INVALID", "staffing_plan.intervals must be a list")
        )
        return result

    # Staffing may extend past target when explicitly authored, but must stay
    # within the shift/plan horizon (end). Target alone is not the hard clamp.
    horizon_end = int(plan_end_sec if plan_end_sec is not None else max(plan_target_sec, plan_start_sec))

    authored: list[AuthoredInterval] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            result.errors.append(
                ValidationError(
                    "STAFFING_INTERVAL_INVALID",
                    f"intervals[{idx}] must be an object",
                    {"index": idx},
                )
            )
            continue
        role = _normalize_role(str(row.get("role") or ""))
        if role not in MANAGEMENT_ROLES:
            result.errors.append(
                ValidationError(
                    "STAFFING_ROLE_INVALID",
                    f"Unknown role {row.get('role')!r}",
                    {"index": idx, "role": row.get("role")},
                )
            )
            continue

        raw_people = row.get("people")
        if isinstance(raw_people, float) and not float(raw_people).is_integer():
            result.errors.append(
                ValidationError(
                    "STAFFING_PEOPLE_INVALID",
                    "people must be a whole number (fractional headcount rejected)",
                    {"index": idx, "people": raw_people},
                )
            )
            continue
        try:
            people = int(raw_people)
        except (TypeError, ValueError):
            result.errors.append(
                ValidationError(
                    "STAFFING_PEOPLE_INVALID",
                    "people must be a positive integer",
                    {"index": idx},
                )
            )
            continue
        if people < 0:
            result.errors.append(
                ValidationError(
                    "STAFFING_PEOPLE_INVALID",
                    "people must be >= 0",
                    {"index": idx, "people": people},
                )
            )
            continue
        if people == 0:
            # Zero headcount is not capacity: drop the authored row.
            continue

        try:
            start_sec = _parse_bound(row.get("start") or row.get("start_time"), field="start")
            end_sec = _parse_bound(row.get("end") or row.get("end_time"), field="end")
        except ValueError as exc:
            result.errors.append(
                ValidationError("STAFFING_TIME_INVALID", str(exc), {"index": idx})
            )
            continue
        if end_sec <= start_sec:
            result.errors.append(
                ValidationError(
                    "STAFFING_INTERVAL_INVALID",
                    "end must be after start",
                    {"index": idx, "start": label_seconds(start_sec), "end": label_seconds(end_sec)},
                )
            )
            continue
        if start_sec < plan_start_sec or end_sec > horizon_end:
            result.errors.append(
                ValidationError(
                    "STAFFING_OUT_OF_BOUNDS",
                    "staffing interval is outside plan/shift boundaries",
                    {
                        "index": idx,
                        "start": label_seconds(start_sec),
                        "end": label_seconds(end_sec),
                        "plan_start": label_seconds(plan_start_sec),
                        "plan_end": label_seconds(horizon_end),
                    },
                )
            )
            continue

        mode = str(row.get("mode") or "base").strip().lower()
        if mode not in ("base", "additional"):
            result.errors.append(
                ValidationError(
                    "STAFFING_MODE_INVALID",
                    "mode must be 'base' or 'additional' when provided",
                    {"index": idx, "mode": row.get("mode")},
                )
            )
            continue

        authored.append(
            AuthoredInterval(
                role=role,
                people=people,
                start_sec=start_sec,
                end_sec=end_sec,
                mode=mode,
            )
        )

    if result.errors:
        return result

    # Reject overlapping BASE intervals for the same role (half-open).
    for role in MANAGEMENT_ROLES:
        bases = [a for a in authored if a.role == role and a.mode == "base"]
        for i in range(len(bases)):
            for j in range(i + 1, len(bases)):
                a, b = bases[i], bases[j]
                if a.start_sec < b.end_sec and b.start_sec < a.end_sec:
                    result.errors.append(
                        ValidationError(
                            "STAFFING_BASE_OVERLAP",
                            f"Overlapping BASE intervals for role {role}",
                            {
                                "role": role,
                                "a": {
                                    "start": label_seconds(a.start_sec),
                                    "end": label_seconds(a.end_sec),
                                },
                                "b": {
                                    "start": label_seconds(b.start_sec),
                                    "end": label_seconds(b.end_sec),
                                },
                            },
                        )
                    )
    if result.errors:
        return result

    result.authored = authored
    result.normalized_intervals = normalize_headcount(authored)
    result.employees = compile_employees(result.normalized_intervals)
    return result


def normalize_headcount(authored: list[AuthoredInterval]) -> list[CanonicalSegment]:
    """Sum overlapping authored intervals into canonical [start, end) segments."""
    by_role: dict[str, list[AuthoredInterval]] = {r: [] for r in MANAGEMENT_ROLES}
    for item in authored:
        by_role[item.role].append(item)

    segments: list[CanonicalSegment] = []
    for role in MANAGEMENT_ROLES:
        items = by_role[role]
        if not items:
            continue
        bounds = sorted({t for it in items for t in (it.start_sec, it.end_sec)})
        for i in range(len(bounds) - 1):
            a, b = bounds[i], bounds[i + 1]
            if a >= b:
                continue
            # Half-open coverage: interval covers [start, end)
            people = sum(it.people for it in items if it.start_sec <= a < it.end_sec)
            if people > 0:
                segments.append(CanonicalSegment(role=role, start_sec=a, end_sec=b, people=people))
    return segments


def compile_employees(segments: list[CanonicalSegment]) -> list[Employee]:
    """Compile canonical headcount into stable anonymous Employee slots.

    Strategy: for each role, create slots 001..max_people. During each segment
    with people=k, slots 1..k are active. Contiguous active ranges merge into
    schedule windows so SORT_001 prefers the longest continuous coverage.
    """
    employees: list[Employee] = []
    for role in MANAGEMENT_ROLES:
        role_segments = [s for s in segments if s.role == role]
        if not role_segments:
            continue
        max_people = max(s.people for s in role_segments)
        # slot_id -> list of [start, end) active ranges
        slot_ranges: list[list[tuple[int, int]]] = [[] for _ in range(max_people)]
        for seg in sorted(role_segments, key=lambda s: s.start_sec):
            for slot in range(seg.people):
                slot_ranges[slot].append((seg.start_sec, seg.end_sec))

        for slot_idx, ranges in enumerate(slot_ranges):
            if not ranges:
                continue
            merged = _merge_ranges(ranges)
            emp_id = f"{ROLE_PREFIX[role]}_{slot_idx + 1:03d}"
            employees.append(
                Employee(
                    employee_id=emp_id,
                    display_name=emp_id,
                    primary_role=role,
                    qualified_roles=[],
                    active=True,
                    schedule_windows=[
                        EmployeeScheduleWindow(
                            start_min=start,
                            end_min=end,
                            exit_policy="stop_and_reassign",
                        )
                        for start, end in merged
                    ],
                )
            )
    return employees


def block_staffing_view(
    authored: list[AuthoredInterval],
    normalized: list[CanonicalSegment],
    *,
    block_start_sec: int,
    block_end_sec: int,
) -> dict[str, Any]:
    """Authoring-friendly staffing summary for a planning block [start, end)."""
    roles: dict[str, Any] = {}
    for role in MANAGEMENT_ROLES:
        # Base = authored base intervals overlapping the block
        base_items = [
            a
            for a in authored
            if a.role == role and a.mode == "base" and a.start_sec < block_end_sec and a.end_sec > block_start_sec
        ]
        additional_items = [
            a
            for a in authored
            if a.role == role
            and a.mode == "additional"
            and a.start_sec < block_end_sec
            and a.end_sec > block_start_sec
        ]
        # Effective headcount samples within the block from normalized segments
        effective = [
            s.as_dict()
            for s in normalized
            if s.role == role and s.start_sec < block_end_sec and s.end_sec > block_start_sec
        ]
        # Peak people in block
        peak = max((s.people for s in normalized if s.role == role and s.start_sec < block_end_sec and s.end_sec > block_start_sec), default=0)
        # Headcount at block start
        at_start = 0
        for s in normalized:
            if s.role == role and s.start_sec <= block_start_sec < s.end_sec:
                at_start = s.people
                break
        roles[role] = {
            "people_at_block_start": at_start,
            "peak_people": peak,
            "base": [
                {
                    "people": a.people,
                    "start": label_seconds(a.start_sec),
                    "end": label_seconds(a.end_sec),
                }
                for a in base_items
            ],
            "additional": [
                {
                    "people": a.people,
                    "start": label_seconds(a.start_sec),
                    "end": label_seconds(a.end_sec),
                }
                for a in additional_items
            ],
            "effective_segments": effective,
        }
    return {
        "block_start": label_seconds(block_start_sec),
        "block_end": label_seconds(block_end_sec),
        "block_start_sec": block_start_sec,
        "block_end_sec": block_end_sec,
        "roles": roles,
    }


def _parse_bound(raw: Any, *, field: str) -> int:
    if raw is None or raw == "":
        raise ValueError(f"{field} is required")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        # seconds if large; minutes if small (compat with numeric APIs)
        v = int(raw)
        return v if v > 24 * 60 else v * 60
    text = str(raw).strip()
    if not text:
        raise ValueError(f"{field} is required")
    return parse_clock_seconds(text)


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


# Waiting states that require explicit labor capacity to progress.
_BLOCKED_STATE_ROLE = {
    "not_yet_weighed": "weigher",
    "waiting_to_sort": "sorter",
    "waiting_to_wash": "washer",
    "waiting_to_dry": "dryer",
    "waiting_to_fold": "folder",
}


def _role_has_capacity_after(employees: list[Employee], role: str, after_sec: int) -> bool:
    """True if any explicit employee window for role remains after after_sec."""
    for emp in employees:
        if emp.primary_role != role:
            continue
        for win in emp.schedule_windows:
            # Half-open: capacity exists if window still open after after_sec
            # or starts later.
            if win.end_min > after_sec and win.start_min < win.end_min:
                return True
    return False


def _ready_sec_for_role(bag: Any, role: str) -> int | None:
    if role == "weigher":
        return bag.entry_time
    if role == "sorter":
        return bag.weigh_end
    if role == "washer":
        return bag.available_to_wash if bag.available_to_wash is not None else bag.sort_end
    if role == "dryer":
        return bag.transfer_end if bag.transfer_end is not None else bag.wash_end
    if role == "folder":
        return bag.ready_to_fold
    return None


def compute_staffing_deficits(state: Any) -> list[dict[str, Any]]:
    """Telemetry-only unmet labor demand. Never creates capacity."""
    from backend.shift_capacity.block_positions import bag_state_at

    if not getattr(state.inputs, "management_mode", False):
        return []

    bags = list(state.bags or [])
    if not bags:
        return []

    # Evaluate at the latest known operational instant under the plan.
    timestamps = [state.inputs.shift.target_min, state.inputs.shift.end_min]
    for bag in bags:
        for attr in (
            "entry_time",
            "weigh_end",
            "sort_end",
            "wash_end",
            "ready_to_fold",
            "completed_at",
        ):
            v = getattr(bag, attr, None)
            if v is not None:
                timestamps.append(int(v))
    t_eval = max(timestamps)

    # Group incomplete bags by blocking role.
    grouped: dict[str, list[Any]] = {}
    ready_by_role: dict[str, list[int]] = {}
    for bag in bags:
        if bag.completed_at is not None:
            continue
        state_name = bag_state_at(bag, t_eval)
        role = _BLOCKED_STATE_ROLE.get(state_name)
        if role is None:
            continue
        grouped.setdefault(role, []).append(bag)
        ready = _ready_sec_for_role(bag, role)
        if ready is not None:
            ready_by_role.setdefault(role, []).append(int(ready))

    deficits: list[dict[str, Any]] = []
    employees = list(state.inputs.employees or [])
    for role in MANAGEMENT_ROLES:
        blocked = grouped.get(role) or []
        if not blocked:
            continue
        first_ready = min(ready_by_role.get(role) or [t_eval])
        # Incomplete bags at plan end: no capacity after ready, or capacity
        # existed but was exhausted / insufficient to clear the queue.
        has_capacity_after = _role_has_capacity_after(employees, role, first_ready)
        reason = "CAPACITY_EXHAUSTED" if has_capacity_after else "NO_STAFF_AVAILABLE"

        bag_ids = [b.bag_id for b in blocked]
        deficits.append(
            {
                "role": role,
                "start_sec": first_ready,
                "start_time": label_seconds(first_ready),
                "blocked_bags": len(blocked),
                "required_process": role,
                "reason": reason,
                "details": {"bag_ids": bag_ids[:24]},
            }
        )
    return deficits


def first_blocking_role(deficits: list[dict[str, Any]]) -> str | None:
    if not deficits:
        return None
    ordered = sorted(deficits, key=lambda d: (d.get("start_sec") or 0, d.get("role") or ""))
    return ordered[0].get("role")
