"""Upstream work coverage for management staffing windows.

Post-DES only: derives eligible demand, used labor, and idle from the same
bag timestamps and employee calendars that produce POSITION. Never a second
capacity engine.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from typing import Any

from backend.shift_capacity.staffing_plan import (
    MANAGEMENT_ROLES,
    ROLE_PREFIX,
    AuthoredInterval,
    _ready_sec_for_role,
    authored_from_serialized,
    hybrid_id_prefix_for,
    employee_matches_hybrid_prefix,
    resolve_hybrid_roles,
)
from backend.shift_capacity.timebase import label_seconds

ROLE_LABOR_TASK = {
    "weigher": "weigh",
    "sorter": "sort",
    "washer": "washer_load",
    "dryer": "dryer_load",
    "folder": "fold",
}


class _LaborTaskIndex:
    """Precomputed bag×task labor reservations for coverage scans."""

    def __init__(self, calendars: dict[str, list[Any]]) -> None:
        ends: dict[tuple[str, str], list[int]] = defaultdict(list)
        spans: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
        for rows in calendars.values():
            for r in rows or []:
                task = getattr(r, "task_type", None) or getattr(r, "task", None)
                if not task:
                    continue
                start = int(r.start)
                end = int(r.end)
                for bag_id in getattr(r, "bag_ids", None) or []:
                    key = (str(bag_id), str(task))
                    ends[key].append(end)
                    spans[key].append((start, end))
        self._ends = {k: sorted(v) for k, v in ends.items()}
        self._spans = spans

    def loads_completed_before(self, bag_id: str, task: str, before_sec: int) -> int:
        ends = self._ends.get((bag_id, task))
        if not ends:
            return 0
        return bisect_right(ends, before_sec)

    def has_open_reservation_at(self, bag_id: str, task: str, t: int) -> bool:
        for start, end in self._spans.get((bag_id, task), []):
            if end <= t:
                continue
            if start >= t or start <= t < end:
                return True
        return False


def build_work_coverage(state: Any) -> list[dict[str, Any]]:
    """Return one coverage row per authored staffing interval (people > 0)."""
    if not getattr(state.inputs, "management_mode", False):
        return []
    plan = state.inputs.staffing_plan_data or {}
    authored_raw = plan.get("authored_intervals") or []
    if not authored_raw:
        return []

    authored = [authored_from_serialized(a) for a in authored_raw]
    authored = [a for a in authored if a.people > 0 and a.end_sec > a.start_sec]
    if not authored:
        return []

    employees = list(state.inputs.employees or [])
    calendars = state.employee_calendars or {}
    labor_index = _LaborTaskIndex(calendars)
    bags = list(state.bags or [])
    pt = state.inputs.processing_times
    load_sec = _load_sec_by_role(pt)
    machine_calendars = state.machine_calendars or {}
    machines = list(getattr(state.inputs, "machines", None) or [])
    washer_ids = [str(m.machine_id) for m in machines if getattr(m, "kind", None) == "washer" or str(getattr(m, "machine_id", "")).startswith("W")]
    dryer_ids = [str(m.machine_id) for m in machines if getattr(m, "kind", None) == "dryer" or str(getattr(m, "machine_id", "")).startswith("D")]
    if not washer_ids:
        n = int(getattr(state.inputs.shift, "washer_count", 0) or 0)
        washer_ids = [f"W{i}" for i in range(1, n + 1)]
    if not dryer_ids:
        n = int(getattr(state.inputs.shift, "dryer_count", 0) or 0)
        dryer_ids = [f"D{i}" for i in range(1, n + 1)]

    rows: list[dict[str, Any]] = []
    for idx, interval in enumerate(authored):
        rows.append(
            _coverage_for_interval(
                interval,
                index=idx,
                authored_all=authored,
                employees=employees,
                calendars=calendars,
                labor_index=labor_index,
                bags=bags,
                load_sec=load_sec,
                machine_calendars=machine_calendars,
                washer_ids=washer_ids,
                dryer_ids=dryer_ids,
            )
        )
    return rows


def _parse_authored(raw: dict[str, Any]) -> AuthoredInterval:
    """Deprecated wrapper — prefer authored_from_serialized."""
    return authored_from_serialized(raw)


def _load_sec_by_role(pt: Any) -> dict[str, int]:
    weigh = int(round(float(getattr(pt, "weigh_sec_per_bag", None) or (float(pt.weigh_min_per_bag) * 60))))
    return {
        "weigher": weigh,
        "sorter": int(round(float(pt.sort_min_per_bag) * 60)),
        "washer": int(round(float(pt.load_washer_min) * 60)),
        "dryer": int(round(float(pt.load_dryer_min) * 60)),
        "folder": int(round(float(pt.fold_min_per_bag) * 60)),
    }


def _n_loads(bag: Any, role: str) -> int:
    if role == "washer":
        return 2 if getattr(bag, "requires_two_washers", False) else 1
    if role == "dryer":
        return 2 if getattr(bag, "requires_two_dryers", False) else 1
    return 1


def _employee_ids_for_interval(
    interval: AuthoredInterval,
    *,
    authored_all: list[AuthoredInterval],
    employees: list[Any],
) -> list[str]:
    """Map authored people onto compiled MGMT_* slots (base = low ids, TEMP = high)."""
    w0, w1 = interval.start_sec, interval.end_sec
    if interval.hybrid_type:
        prefix = hybrid_id_prefix_for(interval.hybrid_type, interval.hybrid_roles)
        emps = sorted(
            [e for e in employees if employee_matches_hybrid_prefix(e.employee_id, prefix)],
            key=lambda e: e.employee_id,
        )
        overlapping = [e for e in emps if _emp_overlaps_window(e, w0, w1)]
        if interval.mode == "additional":
            chosen = overlapping[-interval.people :] if overlapping else []
        else:
            chosen = overlapping[: interval.people]
        return [e.employee_id for e in chosen]

    role = interval.role
    if role not in MANAGEMENT_ROLES:
        return []
    prefix = ROLE_PREFIX[role]
    emps = sorted(
        [
            e
            for e in employees
            if str(e.employee_id).startswith(prefix)
            and not str(e.employee_id).startswith("MGMT_HYBRID")
        ],
        key=lambda e: e.employee_id,
    )
    overlapping = [e for e in emps if _emp_overlaps_window(e, w0, w1)]
    if interval.mode == "additional":
        chosen = overlapping[-interval.people :] if overlapping else []
    else:
        chosen = overlapping[: interval.people]
    return [e.employee_id for e in chosen]


def _emp_overlaps_window(emp: Any, w0: int, w1: int) -> bool:
    for win in emp.schedule_windows or []:
        if win.end_min > w0 and win.start_min < w1:
            return True
    return False


def _staff_sec_for_employees(employee_ids: list[str], employees: list[Any], w0: int, w1: int) -> int:
    by_id = {e.employee_id: e for e in employees}
    total = 0
    for eid in employee_ids:
        emp = by_id.get(eid)
        if emp is None:
            continue
        for win in emp.schedule_windows or []:
            lo = max(int(win.start_min), w0)
            hi = min(int(win.end_min), w1)
            if hi > lo:
                total += hi - lo
    # Fallback: authored people × window when compile windows missing
    if total == 0 and employee_ids:
        total = len(employee_ids) * max(0, w1 - w0)
    return total


def _used_labor(
    employee_ids: list[str],
    calendars: dict[str, list[Any]],
    w0: int,
    w1: int,
    *,
    tasks: set[str] | None = None,
) -> tuple[int, dict[str, int]]:
    """Return (total_used_sec, per_task_sec) overlapping [w0, w1)."""
    used = 0
    by_task: dict[str, int] = {}
    id_set = set(employee_ids)
    for rid, rows in calendars.items():
        if rid not in id_set:
            continue
        for r in rows or []:
            task = getattr(r, "task_type", None) or getattr(r, "task", None)
            if tasks is not None and task not in tasks:
                continue
            lo = max(int(r.start), w0)
            hi = min(int(r.end), w1)
            if hi <= lo:
                continue
            dur = hi - lo
            used += dur
            by_task[str(task)] = by_task.get(str(task), 0) + dur
    return used, by_task


def _loads_completed_before(
    bag_id: str,
    task: str,
    before_sec: int,
    calendars: dict[str, list[Any]],
    *,
    labor_index: _LaborTaskIndex | None = None,
) -> int:
    if labor_index is not None:
        return labor_index.loads_completed_before(bag_id, task, before_sec)
    n = 0
    for rows in calendars.values():
        for r in rows or []:
            if (getattr(r, "task_type", None) or getattr(r, "task", None)) != task:
                continue
            if bag_id not in (getattr(r, "bag_ids", None) or []):
                continue
            if int(r.end) <= before_sec:
                n += 1
    return n


def _eligible_demand(
    bags: list[Any],
    *,
    role: str,
    w0: int,
    w1: int,
    load_sec: int,
    calendars: dict[str, list[Any]],
    labor_index: _LaborTaskIndex | None = None,
) -> tuple[int, int, int, int, int]:
    """Return available_sec, eligible_bags, physical_loads, at_start_bags, became_bags."""
    task = ROLE_LABOR_TASK[role]
    available = 0
    loads = 0
    bag_ids: list[str] = []
    at_start = 0
    became = 0
    for bag in bags:
        ready = _ready_sec_for_role(bag, role)
        if ready is None or ready >= w1:
            continue
        n = _n_loads(bag, role)
        done_before = _loads_completed_before(
            bag.bag_id, task, w0, calendars, labor_index=labor_index
        )
        rem = n - done_before
        if rem <= 0:
            continue
        bag_ids.append(bag.bag_id)
        loads += rem
        available += rem * load_sec
        if ready <= w0:
            at_start += 1
        else:
            became += 1
    return available, len(bag_ids), loads, at_start, became


def _busy_intervals_for_worker(
    calendars: dict[str, list[Any]],
    employee_id: str,
    w0: int,
    w1: int,
    *,
    tasks: set[str] | None,
) -> list[tuple[int, int]]:
    """Return merged busy [lo, hi) segments for one worker inside [w0, w1)."""
    segs: list[tuple[int, int]] = []
    for r in calendars.get(employee_id) or []:
        task = getattr(r, "task_type", None) or getattr(r, "task", None)
        if tasks is not None and task not in tasks:
            continue
        lo = max(int(r.start), w0)
        hi = min(int(r.end), w1)
        if hi > lo:
            segs.append((lo, hi))
    if not segs:
        return []
    segs.sort()
    merged: list[tuple[int, int]] = [segs[0]]
    for lo, hi in segs[1:]:
        prev_lo, prev_hi = merged[-1]
        if lo <= prev_hi:
            merged[-1] = (prev_lo, max(prev_hi, hi))
        else:
            merged.append((lo, hi))
    return merged


def _idle_gaps(busy: list[tuple[int, int]], w0: int, w1: int) -> list[tuple[int, int]]:
    gaps: list[tuple[int, int]] = []
    cursor = w0
    for lo, hi in busy:
        if lo > cursor:
            gaps.append((cursor, lo))
        cursor = max(cursor, hi)
    if cursor < w1:
        gaps.append((cursor, w1))
    return gaps


def _bag_eligible_for_role_at(
    bag: Any,
    role: str,
    t: int,
    calendars: dict[str, list[Any]],
    *,
    labor_index: _LaborTaskIndex | None = None,
) -> bool:
    """True if bag has unfinished, unassigned labor for role ready at instant t."""
    ready = _ready_sec_for_role(bag, role)
    if ready is None or ready > t:
        return False
    task = ROLE_LABOR_TASK[role]
    if role in ("washer", "dryer"):
        n = _n_loads(bag, role)
        done = _loads_completed_before(bag.bag_id, task, t, calendars, labor_index=labor_index)
        if done >= n:
            return False
        if labor_index is not None:
            if labor_index.has_open_reservation_at(bag.bag_id, task, t):
                return False
        else:
            # In-progress or already-booked future load on any calendar → claimed.
            for rows in calendars.values():
                for r in rows or []:
                    if (getattr(r, "task_type", None) or getattr(r, "task", None)) != task:
                        continue
                    if bag.bag_id not in (getattr(r, "bag_ids", None) or []):
                        continue
                    if int(r.end) <= t:
                        continue
                    if int(r.start) >= t or int(r.start) <= t < int(r.end):
                        return False
        return True

    # Single-shot stages: only unassigned ready bags count as eligible demand.
    start_attr = {
        "weigher": "weigh_start",
        "sorter": "sort_start",
        "folder": "fold_start",
    }[role]
    end_attr = {
        "weigher": "weigh_end",
        "sorter": "sort_end",
        "folder": "fold_end",
    }[role]
    if getattr(bag, end_attr, None) is not None and int(getattr(bag, end_attr)) <= t:
        return False
    if getattr(bag, start_attr, None) is not None:
        return False
    return True


def _has_eligible_work_at(
    bags: list[Any],
    roles: list[str],
    t: int,
    calendars: dict[str, list[Any]],
    *,
    labor_index: _LaborTaskIndex | None = None,
) -> bool:
    for bag in bags:
        for role in roles:
            if _bag_eligible_for_role_at(bag, role, t, calendars, labor_index=labor_index):
                return True
    return False


def _ready_event_times(
    bags: list[Any],
    roles: list[str],
    gap_lo: int,
    gap_hi: int,
) -> list[int]:
    times: set[int] = set()
    for bag in bags:
        for role in roles:
            ready = _ready_sec_for_role(bag, role)
            if ready is not None and gap_lo < int(ready) < gap_hi:
                times.add(int(ready))
    return sorted(times)


def _machine_busy_at(machine_calendars: dict[str, list[Any]], machine_id: str, t: int) -> bool:
    for r in machine_calendars.get(machine_id) or []:
        if int(r.start) <= t < int(r.end):
            return True
    return False


def _any_machine_free_at(
    machine_calendars: dict[str, list[Any]],
    machine_ids: list[str],
    t: int,
) -> bool:
    if not machine_ids:
        return True
    return any(not _machine_busy_at(machine_calendars, mid, t) for mid in machine_ids)


def _roles_need_machine(roles: list[str]) -> str | None:
    if "washer" in roles:
        return "washer"
    if "dryer" in roles:
        return "dryer"
    return None


def _classify_idle_gap(
    gap_lo: int,
    gap_hi: int,
    *,
    bags: list[Any],
    roles: list[str],
    calendars: dict[str, list[Any]],
    machine_calendars: dict[str, list[Any]] | None = None,
    washer_ids: list[str] | None = None,
    dryer_ids: list[str] | None = None,
    labor_index: _LaborTaskIndex | None = None,
) -> tuple[int, int, int]:
    """Split idle gap into (idle_no_eligible, unused_fit, machine_blocked) seconds."""
    if gap_hi <= gap_lo:
        return 0, 0, 0
    boundaries = [gap_lo, gap_hi] + _ready_event_times(bags, roles, gap_lo, gap_hi)
    boundaries = sorted(set(boundaries))
    idle_no = 0
    unused_fit = 0
    machine_blocked = 0
    machine_role = _roles_need_machine(roles)
    machine_ids = []
    if machine_role == "washer":
        machine_ids = list(washer_ids or [])
    elif machine_role == "dryer":
        machine_ids = list(dryer_ids or [])
    for i in range(len(boundaries) - 1):
        t0 = boundaries[i]
        t1 = boundaries[i + 1]
        if t1 <= t0:
            continue
        dur = t1 - t0
        if not _has_eligible_work_at(
            bags, roles, t0, calendars, labor_index=labor_index
        ):
            idle_no += dur
            continue
        if (
            machine_role
            and machine_calendars is not None
            and machine_ids
            and not _any_machine_free_at(machine_calendars, machine_ids, t0)
        ):
            machine_blocked += dur
        else:
            unused_fit += dur
    return idle_no, unused_fit, machine_blocked


def _classify_idle_from_calendars(
    employee_ids: list[str],
    *,
    calendars: dict[str, list[Any]],
    bags: list[Any],
    w0: int,
    w1: int,
    roles: list[str],
    tasks: set[str],
    staff_sec: int,
    used_sec: int,
    machine_calendars: dict[str, list[Any]] | None = None,
    washer_ids: list[str] | None = None,
    dryer_ids: list[str] | None = None,
    labor_index: _LaborTaskIndex | None = None,
) -> tuple[int, int, int, int]:
    """Per-worker idle classification, then sum.

    Returns (idle_sec, idle_no_eligible, unused_fit, machine_blocked).
    """
    idle_no_total = 0
    unused_fit_total = 0
    machine_blocked_total = 0
    for eid in employee_ids:
        busy = _busy_intervals_for_worker(calendars, eid, w0, w1, tasks=tasks)
        for gap_lo, gap_hi in _idle_gaps(busy, w0, w1):
            no_sec, fit_sec, blocked_sec = _classify_idle_gap(
                gap_lo,
                gap_hi,
                bags=bags,
                roles=roles,
                calendars=calendars,
                machine_calendars=machine_calendars,
                washer_ids=washer_ids,
                dryer_ids=dryer_ids,
                labor_index=labor_index,
            )
            idle_no_total += no_sec
            unused_fit_total += fit_sec
            machine_blocked_total += blocked_sec

    idle_sec = max(0, staff_sec - used_sec)
    classified = idle_no_total + unused_fit_total + machine_blocked_total
    if classified == 0 and idle_sec > 0:
        return idle_sec, idle_sec, 0, 0
    if classified != idle_sec and classified > 0:
        drift = idle_sec - classified
        if abs(drift) <= 1:
            if drift > 0:
                unused_fit_total += drift
            elif unused_fit_total >= -drift:
                unused_fit_total += drift
            elif machine_blocked_total >= -drift:
                machine_blocked_total += drift
            else:
                idle_no_total += drift
        else:
            idle_sec = classified
    return idle_sec, idle_no_total, unused_fit_total, machine_blocked_total


def _idle_breakdown(
    *,
    staff_sec: int,
    used_sec: int,
    available_sec: int,
) -> tuple[int, int, int]:
    """Legacy aggregate fallback — prefer _classify_idle_from_calendars."""
    idle = max(0, staff_sec - used_sec)
    idle_no_work = max(0, min(idle, staff_sec - available_sec))
    unused_fit = max(0, idle - idle_no_work)
    return idle, idle_no_work, unused_fit


def _status(
    staff_sec: int,
    used_sec: int,
    idle_no_work: int,
    unused_fit: int,
    machine_blocked: int = 0,
) -> str:
    if staff_sec <= 0:
        return "no_staff"
    # Fully utilized when DES used the whole staff window.
    if used_sec >= staff_sec - 1:
        return "fully_utilized"
    if idle_no_work > 0 and unused_fit == 0 and machine_blocked == 0:
        return "idle_waiting_for_work"
    if machine_blocked > 0 and idle_no_work == 0 and unused_fit == 0:
        return "machine_blocked"
    if idle_no_work > 0 and (unused_fit > 0 or machine_blocked > 0):
        return "partial_upstream_short"
    if unused_fit > 0 and machine_blocked == 0:
        return "work_not_fit"
    if machine_blocked > 0:
        return "machine_blocked"
    if idle_no_work > 0:
        return "idle_waiting_for_work"
    return "partial"


def _min2(sec: int | float) -> float:
    """Minutes with 2-decimal precision (preserve 2.25 / 7.75)."""
    return round(float(sec) / 60.0, 2)


def _coverage_for_interval(
    interval: AuthoredInterval,
    *,
    index: int,
    authored_all: list[AuthoredInterval],
    employees: list[Any],
    calendars: dict[str, list[Any]],
    labor_index: _LaborTaskIndex | None,
    bags: list[Any],
    load_sec: dict[str, int],
    machine_calendars: dict[str, list[Any]] | None = None,
    washer_ids: list[str] | None = None,
    dryer_ids: list[str] | None = None,
) -> dict[str, Any]:
    w0, w1 = interval.start_sec, interval.end_sec
    employee_ids = _employee_ids_for_interval(
        interval, authored_all=authored_all, employees=employees
    )
    staff_sec = _staff_sec_for_employees(employee_ids, employees, w0, w1)
    if staff_sec == 0:
        staff_sec = interval.people * max(0, w1 - w0)

    if interval.hybrid_type:
        roles = list(resolve_hybrid_roles(interval.hybrid_type, interval.hybrid_roles))
        tasks = {ROLE_LABOR_TASK[r] for r in roles}
        used_sec, by_task = _used_labor(employee_ids, calendars, w0, w1, tasks=tasks)
        available_sec, eligible_bags, physical_loads, at_start, became = _hybrid_eligible_demand(
            bags,
            roles=roles,
            w0=w0,
            w1=w1,
            load_sec=load_sec,
            calendars=calendars,
            labor_index=labor_index,
        )
        idle_sec, idle_no_work, unused_fit, machine_blocked = _classify_idle_from_calendars(
            employee_ids,
            calendars=calendars,
            bags=bags,
            w0=w0,
            w1=w1,
            roles=roles,
            tasks=tasks,
            staff_sec=staff_sec,
            used_sec=used_sec,
            machine_calendars=machine_calendars,
            washer_ids=washer_ids,
            dryer_ids=dryer_ids,
            labor_index=labor_index,
        )
        role_alloc = {
            r: round(by_task.get(ROLE_LABOR_TASK[r], 0) / 60.0, 2) for r in roles
        }
        role_alloc["idle"] = _min2(idle_sec)
        primary_role = None
        label_role = interval.hybrid_type
    else:
        role = interval.role
        roles = [role]
        task = ROLE_LABOR_TASK[role]
        tasks = {task}
        used_sec, _ = _used_labor(employee_ids, calendars, w0, w1, tasks=tasks)
        available_sec, eligible_bags, physical_loads, at_start, became = _eligible_demand(
            bags,
            role=role,
            w0=w0,
            w1=w1,
            load_sec=load_sec[role],
            calendars=calendars,
            labor_index=labor_index,
        )
        idle_sec, idle_no_work, unused_fit, machine_blocked = _classify_idle_from_calendars(
            employee_ids,
            calendars=calendars,
            bags=bags,
            w0=w0,
            w1=w1,
            roles=roles,
            tasks=tasks,
            staff_sec=staff_sec,
            used_sec=used_sec,
            machine_calendars=machine_calendars,
            washer_ids=washer_ids,
            dryer_ids=dryer_ids,
            labor_index=labor_index,
        )
        role_alloc = None
        primary_role = role
        label_role = role

    status = _status(staff_sec, used_sec, idle_no_work, unused_fit, machine_blocked)
    staff_min = _min2(staff_sec)
    available_min = _min2(available_sec)
    used_min = _min2(used_sec)
    idle_min = _min2(idle_sec)
    idle_no_min = _min2(idle_no_work)
    unused_fit_min = _min2(unused_fit)
    machine_blocked_min = _min2(machine_blocked)

    return {
        "index": index,
        "role": primary_role,
        "hybrid": interval.hybrid_type,
        "roles": list(resolve_hybrid_roles(interval.hybrid_type, interval.hybrid_roles))
        if interval.hybrid_type
        else ([primary_role] if primary_role else None),
        "mode": interval.mode,
        "people": interval.people,
        "start": label_seconds(w0),
        "end": label_seconds(w1),
        "start_sec": w0,
        "end_sec": w1,
        "resource_ids": employee_ids,
        "staff_min": staff_min,
        "available_work_min": available_min,
        "used_min": used_min,
        "idle_min": idle_min,
        "idle_no_eligible_work_min": idle_no_min,
        "unused_fit_min": unused_fit_min,
        "machine_blocked_min": machine_blocked_min,
        "eligible_bags": eligible_bags,
        "eligible_bags_at_start": at_start,
        "eligible_bags_became": became,
        "physical_loads_available": physical_loads,
        "status": status,
        "status_label": _status_label(status, idle_min),
        "role_allocation_min": role_alloc,
        "label_key": label_role,
        "summary": _summary_line(
            mode=interval.mode,
            role_key=label_role,
            people=interval.people,
            start=label_seconds(w0),
            end=label_seconds(w1),
            staff_min=staff_min,
            available_min=available_min,
            used_min=used_min,
            idle_min=idle_min,
            idle_no_min=idle_no_min,
            unused_fit_min=unused_fit_min,
            eligible_bags=eligible_bags,
            status=status,
            role_alloc=role_alloc,
            machine_blocked_min=machine_blocked_min,
        ),
    }


def _hybrid_eligible_demand(
    bags: list[Any],
    *,
    roles: list[str],
    w0: int,
    w1: int,
    load_sec: dict[str, int],
    calendars: dict[str, list[Any]],
    labor_index: _LaborTaskIndex | None = None,
) -> tuple[int, int, int, int, int]:
    """Union of unfinished work across hybrid roles without double-counting a bag's minutes.

    A bag contributes labor demand for the first qualified role that still has
    remaining loads in-window (workflow order).
    """
    available = 0
    loads = 0
    bag_count = 0
    at_start = 0
    became = 0
    for bag in bags:
        contributed = False
        bag_ready_for_count: int | None = None
        for role in roles:
            ready = _ready_sec_for_role(bag, role)
            if ready is None or ready >= w1:
                continue
            task = ROLE_LABOR_TASK[role]
            n = _n_loads(bag, role)
            done_before = _loads_completed_before(
            bag.bag_id, task, w0, calendars, labor_index=labor_index
        )
            rem = n - done_before
            if rem <= 0:
                continue
            available += rem * load_sec[role]
            loads += rem
            contributed = True
            bag_ready_for_count = ready
            break
        if contributed:
            bag_count += 1
            if bag_ready_for_count is not None and bag_ready_for_count <= w0:
                at_start += 1
            else:
                became += 1
    return available, bag_count, loads, at_start, became


def _status_label(status: str, idle_min: float) -> str:
    if status == "fully_utilized":
        return "FULLY UTILIZED"
    if status in ("idle_waiting_for_work", "partial_upstream_short"):
        idle_i = int(round(idle_min))
        return f"{idle_i} min likely idle"
    if status == "work_not_fit":
        idle_i = int(round(idle_min))
        return f"{idle_i} min unused (work not fit)"
    return status.replace("_", " ")


def _summary_line(
    *,
    mode: str,
    role_key: str,
    people: int,
    start: str,
    end: str,
    staff_min: float,
    available_min: float,
    used_min: float,
    idle_min: float,
    idle_no_min: float,
    unused_fit_min: float,
    eligible_bags: int,
    status: str,
    role_alloc: dict[str, float] | None,
    machine_blocked_min: float = 0,
) -> str:
    role_disp = {
        "weigher": "WEIGH",
        "sorter": "SORT",
        "washer": "WASH",
        "dryer": "DRY",
        "folder": "FOLD",
        "weigh_wash": "WEIGH/WASH",
        "wash_dry": "WASH/DRY",
        "weigh_wash_dry": "WEIGH/WASH/DRY",
    }.get(role_key, str(role_key).upper())
    if mode == "additional":
        head = f"TEMP +{people} {start}–{end}"
    else:
        head = f"{role_disp} {people} · {start}–{end}"

    used_i = _fmt_min(used_min)
    staff_i = _fmt_min(staff_min)
    idle_i = _fmt_min(idle_min)

    if role_alloc is not None:
        parts = [f"{staff_i} staff min"]
        for k, v in role_alloc.items():
            if k == "idle":
                continue
            short = {
                "weigher": "Weigh",
                "sorter": "Sort",
                "washer": "Wash",
                "dryer": "Dry",
                "folder": "Fold",
            }.get(k, k)
            if v > 0:
                parts.append(f"{short} {_fmt_min(v)}m")
        parts.append(f"Idle {_fmt_min(role_alloc.get('idle', idle_min))}m")
        return f"{head} · " + " · ".join(parts)

    util = int(round((used_min / staff_min) * 100)) if staff_min > 0 else 0
    reason_bits = []
    if idle_no_min > 0.005:
        reason_bits.append(f"{_fmt_min(idle_no_min)} waiting for work")
    if machine_blocked_min > 0.005:
        reason_bits.append(f"{_fmt_min(machine_blocked_min)} machine blocked")
    if unused_fit_min > 0.005:
        reason_bits.append(f"{_fmt_min(unused_fit_min)} remaining too short")
    reason = (" · " + " · ".join(reason_bits)) if reason_bits else ""
    return (
        f"{head} · Labor used {used_i}/{staff_i} min · "
        f"{idle_i} spare{reason}"
    )


def _fmt_min(v: float) -> str:
    if abs(v - round(v)) < 0.005:
        return str(int(round(v)))
    # Keep two decimals when needed (2.25), else one (4.5).
    rounded2 = round(v, 2)
    if abs(rounded2 * 10 - round(rounded2 * 10)) < 0.001:
        return f"{rounded2:.1f}"
    return f"{rounded2:.2f}"


def attach_work_coverage_to_blocks(
    block_rows: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Echo coverage rows that overlap each planning block under staffing."""
    for row in block_rows:
        b0 = int(row["block_start_sec"])
        b1 = int(row["block_end_sec"])
        matched = [
            c
            for c in coverage
            if int(c["start_sec"]) < b1 and int(c["end_sec"]) > b0
        ]
        staffing = row.get("staffing")
        if isinstance(staffing, dict):
            staffing = dict(staffing)
            staffing["work_coverage"] = matched
            row["staffing"] = staffing
        else:
            row["work_coverage"] = matched
    return block_rows
