"""Management staffing-plan normalization and compilation into Employee calendars.

Authoring may use BASE + ADDITIONAL intervals. The scheduler source of truth is
canonical effective-headcount segments (people summed over overlaps).
"""

from __future__ import annotations

import re
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

# Legacy fixed hybrid keys → ordered qualified roles (first = primary_role).
# Custom hybrids use roles[] and normalize into the same compile path.
LEGACY_HYBRID_SPECS: dict[str, tuple[str, ...]] = {
    "weigh_wash": ("weigher", "washer"),
    "wash_dry": ("washer", "dryer"),
    "weigh_wash_dry": ("weigher", "washer", "dryer"),
}
# Backward-compat alias used by older imports / tests.
HYBRID_SPECS = LEGACY_HYBRID_SPECS
HYBRID_ID_PREFIX = {
    "weigh_wash": "MGMT_HYBRID_WEIGH_WASH",
    "wash_dry": "MGMT_HYBRID_WASH_DRY",
    "weigh_wash_dry": "MGMT_HYBRID_WEIGH_WASH_DRY",
}
ROLE_ID_SHORT = {
    "weigher": "WEIGH",
    "sorter": "SORT",
    "washer": "WASH",
    "dryer": "DRY",
    "folder": "FOLD",
}


def canonicalize_hybrid_roles(raw_roles: Any) -> tuple[str, ...]:
    """Dedupe and order roles by workflow; require at least two management roles."""
    if not isinstance(raw_roles, (list, tuple)):
        raise ValueError("hybrid roles must be a list")
    seen: set[str] = set()
    for item in raw_roles:
        role = _normalize_role(str(item or ""))
        if role not in MANAGEMENT_ROLES:
            raise ValueError(f"Unknown hybrid role {item!r}")
        seen.add(role)
    ordered = tuple(r for r in MANAGEMENT_ROLES if r in seen)
    if len(ordered) < 2:
        raise ValueError("hybrid requires at least two roles")
    return ordered


def hybrid_identity(
    roles: tuple[str, ...],
    *,
    legacy_hint: str | None = None,
) -> tuple[str, str]:
    """Return (hybrid_type_key, employee_id_prefix). Prefer legacy keys when roles match."""
    if (
        legacy_hint
        and legacy_hint in LEGACY_HYBRID_SPECS
        and LEGACY_HYBRID_SPECS[legacy_hint] == roles
    ):
        return legacy_hint, HYBRID_ID_PREFIX[legacy_hint]
    for legacy_key, legacy_roles in LEGACY_HYBRID_SPECS.items():
        if legacy_roles == roles:
            return legacy_key, HYBRID_ID_PREFIX[legacy_key]
    key = "+".join(roles)
    prefix = "MGMT_HYBRID_" + "_".join(ROLE_ID_SHORT[r] for r in roles)
    return key, prefix


def resolve_hybrid_roles(
    hybrid_type: str | None,
    hybrid_roles: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    if hybrid_roles:
        return tuple(hybrid_roles)
    if hybrid_type and hybrid_type in LEGACY_HYBRID_SPECS:
        return LEGACY_HYBRID_SPECS[hybrid_type]
    if hybrid_type and "+" in hybrid_type:
        return canonicalize_hybrid_roles(hybrid_type.split("+"))
    raise KeyError(hybrid_type or "hybrid")


def hybrid_id_prefix_for(
    hybrid_type: str | None,
    hybrid_roles: tuple[str, ...] | None = None,
) -> str:
    if hybrid_type and hybrid_type in HYBRID_ID_PREFIX:
        return HYBRID_ID_PREFIX[hybrid_type]
    roles = resolve_hybrid_roles(hybrid_type, hybrid_roles)
    _, prefix = hybrid_identity(roles, legacy_hint=hybrid_type)
    return prefix


def employee_matches_hybrid_prefix(employee_id: str, prefix: str) -> bool:
    """True when id is exactly ``{prefix}_NNN`` (avoids WEIGH_WASH vs WEIGH_WASH_DRY)."""
    return bool(re.match(rf"^{re.escape(prefix)}_\d{{3}}$", str(employee_id)))


def authored_from_serialized(raw: dict[str, Any]) -> AuthoredInterval:
    """Rebuild AuthoredInterval from staffing_plan authored_intervals dict."""
    roles_raw = raw.get("roles")
    hybrid_raw = raw.get("hybrid") or raw.get("hybrid_type")
    hybrid_type = str(hybrid_raw).strip().lower() if hybrid_raw else None
    hybrid_roles: tuple[str, ...] | None = None
    if roles_raw is not None:
        hybrid_roles = canonicalize_hybrid_roles(roles_raw)
        hybrid_type, _ = hybrid_identity(hybrid_roles, legacy_hint=hybrid_type)
    elif hybrid_type:
        hybrid_roles = resolve_hybrid_roles(hybrid_type, None)
    if hybrid_type:
        role = hybrid_roles[0] if hybrid_roles else "weigher"
    else:
        role = str(raw.get("role") or "")
    return AuthoredInterval(
        role=role,
        people=int(raw["people"]),
        start_sec=int(raw["start_sec"]),
        end_sec=int(raw["end_sec"]),
        mode=str(raw.get("mode") or "base"),
        hybrid_type=hybrid_type,
        hybrid_roles=hybrid_roles,
    )


@dataclass
class AuthoredInterval:
    role: str
    people: int
    start_sec: int
    end_sec: int
    mode: str = "base"  # base | additional (authoring metadata only)
    hybrid_type: str | None = None  # identity key; when set, dedicated role unused
    hybrid_roles: tuple[str, ...] | None = None  # ordered qualified roles for custom hybrids


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
                    "role": a.role if a.hybrid_type is None else None,
                    "hybrid": a.hybrid_type,
                    "roles": list(a.hybrid_roles) if a.hybrid_roles else (
                        list(LEGACY_HYBRID_SPECS[a.hybrid_type])
                        if a.hybrid_type in LEGACY_HYBRID_SPECS
                        else None
                    ),
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
                    "qualified_roles": list(e.qualified_roles),
                    "hybrid_type": _hybrid_type_for_employee(e),
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

        hybrid_raw = row.get("hybrid") or row.get("hybrid_type")
        roles_raw = row.get("roles")
        mode_hint = str(row.get("mode") or "base").strip().lower()
        hybrid_type: str | None = None
        hybrid_roles: tuple[str, ...] | None = None

        if roles_raw is not None or mode_hint == "hybrid" or hybrid_raw:
            if roles_raw is not None:
                try:
                    hybrid_roles = canonicalize_hybrid_roles(roles_raw)
                except ValueError as exc:
                    result.errors.append(
                        ValidationError(
                            "STAFFING_HYBRID_INVALID",
                            str(exc),
                            {"index": idx, "roles": roles_raw},
                        )
                    )
                    continue
                legacy_hint = str(hybrid_raw).strip().lower() if hybrid_raw else None
                hybrid_type, _ = hybrid_identity(hybrid_roles, legacy_hint=legacy_hint)
            elif hybrid_raw:
                hybrid_type = str(hybrid_raw).strip().lower()
                try:
                    if hybrid_type in LEGACY_HYBRID_SPECS:
                        hybrid_roles = LEGACY_HYBRID_SPECS[hybrid_type]
                    elif "+" in hybrid_type:
                        hybrid_roles = canonicalize_hybrid_roles(hybrid_type.split("+"))
                        hybrid_type, _ = hybrid_identity(hybrid_roles)
                    else:
                        raise ValueError(f"Unknown hybrid type {hybrid_raw!r}")
                except (ValueError, KeyError) as exc:
                    result.errors.append(
                        ValidationError(
                            "STAFFING_HYBRID_INVALID",
                            str(exc),
                            {"index": idx, "hybrid": hybrid_raw},
                        )
                    )
                    continue
            else:
                result.errors.append(
                    ValidationError(
                        "STAFFING_HYBRID_INVALID",
                        "hybrid mode requires roles (at least two)",
                        {"index": idx},
                    )
                )
                continue
            role = hybrid_roles[0]
        else:
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
            start_sec = _parse_bound(
                row.get("start") or row.get("start_time"), field="start"
            )
            end_sec = _parse_bound(
                row.get("end") or row.get("end_time"), field="end"
            )
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

        mode = mode_hint
        if hybrid_type is not None and mode == "hybrid":
            mode = "base"
        if mode not in ("base", "additional"):
            result.errors.append(
                ValidationError(
                    "STAFFING_MODE_INVALID",
                    "mode must be 'base', 'additional', or 'hybrid' when provided",
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
                hybrid_type=hybrid_type,
                hybrid_roles=hybrid_roles,
            )
        )

    if result.errors:
        return result

    # Reject overlapping BASE intervals for the same dedicated role (half-open).
    for role in MANAGEMENT_ROLES:
        bases = [
            a
            for a in authored
            if a.hybrid_type is None and a.role == role and a.mode == "base"
        ]
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
    # Reject overlapping BASE for the same hybrid identity (role set).
    hybrid_types = sorted({a.hybrid_type for a in authored if a.hybrid_type})
    for hybrid_type in hybrid_types:
        bases = [
            a
            for a in authored
            if a.hybrid_type == hybrid_type and a.mode == "base"
        ]
        for i in range(len(bases)):
            for j in range(i + 1, len(bases)):
                a, b = bases[i], bases[j]
                if a.start_sec < b.end_sec and b.start_sec < a.end_sec:
                    result.errors.append(
                        ValidationError(
                            "STAFFING_HYBRID_BASE_OVERLAP",
                            f"Overlapping BASE intervals for hybrid {hybrid_type}",
                            {
                                "hybrid": hybrid_type,
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
    dedicated = [a for a in authored if a.hybrid_type is None]
    hybrids = [a for a in authored if a.hybrid_type is not None]
    result.normalized_intervals = normalize_headcount(dedicated)
    result.employees = compile_employees(result.normalized_intervals)
    result.employees.extend(compile_hybrid_employees(hybrids))
    return result


def normalize_headcount(authored: list[AuthoredInterval]) -> list[CanonicalSegment]:
    """Sum overlapping authored intervals into canonical [start, end) segments.

    Hybrid authored rows are excluded — they compile to multi-role employees
    separately and must not inflate dedicated role headcount.
    """
    by_role: dict[str, list[AuthoredInterval]] = {r: [] for r in MANAGEMENT_ROLES}
    for item in authored:
        if item.hybrid_type is not None:
            continue
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


def compile_hybrid_employees(authored_hybrids: list[AuthoredInterval]) -> list[Employee]:
    """Compile hybrid headcount into one shared multi-role calendar per slot.

    Scheduling reuse (documented): pick_employee selects the eligible employee
    who can start soonest; ties break by employee_id ascending. Hybrids share
    that rule with dedicated MGMT_* slots — no separate optimizer.
    """
    employees: list[Employee] = []
    by_type: dict[str, list[AuthoredInterval]] = {}
    roles_by_type: dict[str, tuple[str, ...]] = {}
    for item in authored_hybrids:
        if not item.hybrid_type:
            continue
        by_type.setdefault(item.hybrid_type, []).append(item)
        if item.hybrid_type not in roles_by_type:
            roles_by_type[item.hybrid_type] = resolve_hybrid_roles(
                item.hybrid_type, item.hybrid_roles
            )

    for hybrid_type in sorted(by_type.keys()):
        items = by_type[hybrid_type]
        roles = roles_by_type[hybrid_type]
        # Normalize hybrid headcount the same way as a single pseudo-role.
        bounds = sorted({t for it in items for t in (it.start_sec, it.end_sec)})
        segments: list[tuple[int, int, int]] = []
        for i in range(len(bounds) - 1):
            a, b = bounds[i], bounds[i + 1]
            if a >= b:
                continue
            people = sum(it.people for it in items if it.start_sec <= a < it.end_sec)
            if people > 0:
                segments.append((a, b, people))
        if not segments:
            continue
        max_people = max(p for _, _, p in segments)
        slot_ranges: list[list[tuple[int, int]]] = [[] for _ in range(max_people)]
        for start, end, people in sorted(segments, key=lambda s: s[0]):
            for slot in range(people):
                slot_ranges[slot].append((start, end))
        primary = roles[0]
        qualified = list(roles[1:])
        prefix = hybrid_id_prefix_for(hybrid_type, roles)
        for slot_idx, ranges in enumerate(slot_ranges):
            if not ranges:
                continue
            merged = _merge_ranges(ranges)
            emp_id = f"{prefix}_{slot_idx + 1:03d}"
            employees.append(
                Employee(
                    employee_id=emp_id,
                    display_name=emp_id,
                    primary_role=primary,
                    qualified_roles=qualified,
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


def _hybrid_type_for_employee(emp: Employee) -> str | None:
    if not emp.qualified_roles:
        return None
    # Prefer longest matching legacy prefix to avoid WEIGH_WASH vs WEIGH_WASH_DRY.
    best: tuple[int, str] | None = None
    for ht, prefix in HYBRID_ID_PREFIX.items():
        if employee_matches_hybrid_prefix(emp.employee_id, prefix):
            cand = (len(prefix), ht)
            if best is None or cand[0] > best[0]:
                best = cand
    if best:
        return best[1]
    roles = tuple(r for r in MANAGEMENT_ROLES if r in ((emp.primary_role,) + tuple(emp.qualified_roles)))
    if len(roles) < 2:
        roles = (emp.primary_role,) + tuple(emp.qualified_roles)
    key, _prefix = hybrid_identity(roles)
    return key

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
        # Dedicated only — hybrids use primary_role for compile IDs but are not
        # dedicated weigh/wash/dry headcount.
        base_items = [
            a
            for a in authored
            if a.hybrid_type is None
            and a.role == role
            and a.mode == "base"
            and a.start_sec < block_end_sec
            and a.end_sec > block_start_sec
        ]
        additional_items = [
            a
            for a in authored
            if a.hybrid_type is None
            and a.role == role
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
    hybrids: dict[str, Any] = {}
    hybrid_types = sorted({a.hybrid_type for a in authored if a.hybrid_type})
    for hybrid_type in hybrid_types:
        items = [
            a
            for a in authored
            if a.hybrid_type == hybrid_type
            and a.start_sec < block_end_sec
            and a.end_sec > block_start_sec
        ]
        at_start = 0
        peak = 0
        roles_for_type: tuple[str, ...] = ()
        for a in items:
            if not roles_for_type:
                roles_for_type = resolve_hybrid_roles(a.hybrid_type, a.hybrid_roles)
            if a.mode == "base" and a.start_sec <= block_start_sec < a.end_sec:
                at_start = max(at_start, a.people)
            if a.start_sec < block_end_sec and a.end_sec > block_start_sec:
                peak = max(peak, a.people)
        if not roles_for_type:
            try:
                roles_for_type = resolve_hybrid_roles(hybrid_type, None)
            except KeyError:
                roles_for_type = ()
        hybrids[hybrid_type] = {
            "people_at_block_start": at_start,
            "peak_people": peak,
            "qualified_roles": list(roles_for_type),
            "base": [
                {
                    "people": a.people,
                    "start": label_seconds(a.start_sec),
                    "end": label_seconds(a.end_sec),
                    "roles": list(resolve_hybrid_roles(a.hybrid_type, a.hybrid_roles)),
                }
                for a in items
                if a.mode == "base"
            ],
            "additional": [
                {
                    "people": a.people,
                    "start": label_seconds(a.start_sec),
                    "end": label_seconds(a.end_sec),
                    "roles": list(resolve_hybrid_roles(a.hybrid_type, a.hybrid_roles)),
                }
                for a in items
                if a.mode == "additional"
            ],
        }
    return {
        "block_start": label_seconds(block_start_sec),
        "block_end": label_seconds(block_end_sec),
        "block_start_sec": block_start_sec,
        "block_end_sec": block_end_sec,
        "roles": roles,
        "hybrids": hybrids,
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
    """True if any explicit employee window for role remains after after_sec.

    Includes hybrid MGMT resources whose qualified_roles cover ``role``
    (shared calendar; not a second independent headcount).
    """
    from backend.shift_capacity.resources import role_active_at

    for emp in employees:
        for win in emp.schedule_windows:
            if win.end_min <= after_sec or win.start_min >= win.end_min:
                continue
            # Probe at the later of after_sec and window start (half-open).
            probe = max(after_sec, win.start_min)
            if probe >= win.end_min:
                continue
            if role_active_at(emp, role, probe):
                return True
            # Window starts later than after_sec — still future capacity.
            if win.start_min > after_sec and role_active_at(emp, role, win.start_min):
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
