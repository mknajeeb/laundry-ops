"""Upstream work coverage for management staffing windows.

Post-DES only: derives eligible demand, used labor, and idle from the same
bag timestamps and employee calendars that produce POSITION. Never a second
capacity engine.
"""

from __future__ import annotations

from typing import Any

from backend.shift_capacity.staffing_plan import (
    HYBRID_ID_PREFIX,
    HYBRID_SPECS,
    MANAGEMENT_ROLES,
    ROLE_PREFIX,
    AuthoredInterval,
    _ready_sec_for_role,
)
from backend.shift_capacity.timebase import label_seconds

ROLE_LABOR_TASK = {
    "weigher": "weigh",
    "sorter": "sort",
    "washer": "washer_load",
    "dryer": "dryer_load",
    "folder": "fold",
}


def build_work_coverage(state: Any) -> list[dict[str, Any]]:
    """Return one coverage row per authored staffing interval (people > 0)."""
    if not getattr(state.inputs, "management_mode", False):
        return []
    plan = state.inputs.staffing_plan_data or {}
    authored_raw = plan.get("authored_intervals") or []
    if not authored_raw:
        return []

    authored = [_parse_authored(a) for a in authored_raw]
    authored = [a for a in authored if a.people > 0 and a.end_sec > a.start_sec]
    if not authored:
        return []

    employees = list(state.inputs.employees or [])
    calendars = state.employee_calendars or {}
    bags = list(state.bags or [])
    pt = state.inputs.processing_times
    load_sec = _load_sec_by_role(pt)

    rows: list[dict[str, Any]] = []
    for idx, interval in enumerate(authored):
        rows.append(
            _coverage_for_interval(
                interval,
                index=idx,
                authored_all=authored,
                employees=employees,
                calendars=calendars,
                bags=bags,
                load_sec=load_sec,
            )
        )
    return rows


def _parse_authored(raw: dict[str, Any]) -> AuthoredInterval:
    hybrid_type = raw.get("hybrid") or raw.get("hybrid_type")
    hybrid_type = str(hybrid_type).strip().lower() if hybrid_type else None
    if hybrid_type:
        role = HYBRID_SPECS.get(hybrid_type, ("weigher",))[0]
    else:
        role = str(raw.get("role") or "")
    return AuthoredInterval(
        role=role,
        people=int(raw["people"]),
        start_sec=int(raw["start_sec"]),
        end_sec=int(raw["end_sec"]),
        mode=str(raw.get("mode") or "base"),
        hybrid_type=hybrid_type,
    )


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
        prefix = HYBRID_ID_PREFIX[interval.hybrid_type]
        emps = sorted(
            [e for e in employees if str(e.employee_id).startswith(prefix)],
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
) -> int:
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
        done_before = _loads_completed_before(bag.bag_id, task, w0, calendars)
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
) -> bool:
    """True if bag has unfinished, unassigned labor for role ready at instant t."""
    ready = _ready_sec_for_role(bag, role)
    if ready is None or ready > t:
        return False
    task = ROLE_LABOR_TASK[role]
    if role in ("washer", "dryer"):
        n = _n_loads(bag, role)
        done = _loads_completed_before(bag.bag_id, task, t, calendars)
        if done >= n:
            return False
        # In-progress or already-booked future load on any calendar → claimed.
        for rows in calendars.values():
            for r in rows or []:
                if (getattr(r, "task_type", None) or getattr(r, "task", None)) != task:
                    continue
                if bag.bag_id not in (getattr(r, "bag_ids", None) or []):
                    continue
                if int(r.end) <= t:
                    continue
                # Reservation still open at or after t (in progress or future).
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
) -> bool:
    for bag in bags:
        for role in roles:
            if _bag_eligible_for_role_at(bag, role, t, calendars):
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


def _classify_idle_gap(
    gap_lo: int,
    gap_hi: int,
    *,
    bags: list[Any],
    roles: list[str],
    calendars: dict[str, list[Any]],
) -> tuple[int, int]:
    """Split one idle gap into (idle_no_eligible_sec, unused_fit_sec) via DES readiness."""
    if gap_hi <= gap_lo:
        return 0, 0
    boundaries = [gap_lo, gap_hi] + _ready_event_times(bags, roles, gap_lo, gap_hi)
    boundaries = sorted(set(boundaries))
    idle_no = 0
    unused_fit = 0
    for i in range(len(boundaries) - 1):
        t0 = boundaries[i]
        t1 = boundaries[i + 1]
        if t1 <= t0:
            continue
        if _has_eligible_work_at(bags, roles, t0, calendars):
            unused_fit += t1 - t0
        else:
            idle_no += t1 - t0
    return idle_no, unused_fit


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
) -> tuple[int, int, int]:
    """Per-worker idle classification, then sum.

    idle_no_eligible_work: worker free and no eligible upstream work.
    unused_fit: worker free while eligible work existed (typically end-fragment
    under finish_in_progress_at_exit=False).

    Does NOT use aggregated staff vs cumulative available_work_min.
    """
    idle_no_total = 0
    unused_fit_total = 0
    for eid in employee_ids:
        busy = _busy_intervals_for_worker(calendars, eid, w0, w1, tasks=tasks)
        for gap_lo, gap_hi in _idle_gaps(busy, w0, w1):
            no_sec, fit_sec = _classify_idle_gap(
                gap_lo, gap_hi, bags=bags, roles=roles, calendars=calendars
            )
            idle_no_total += no_sec
            unused_fit_total += fit_sec

    idle_sec = max(0, staff_sec - used_sec)
    classified = idle_no_total + unused_fit_total
    # Guard: classified idle should match calendar spare within the window.
    # If calendars are empty but staff exists, treat all spare as no-eligible.
    if classified == 0 and idle_sec > 0:
        return idle_sec, idle_sec, 0
    if classified != idle_sec and classified > 0:
        # Prefer calendar classification; scale only if tiny float/clip drift.
        drift = idle_sec - classified
        if abs(drift) <= 1:
            if drift > 0:
                unused_fit_total += drift
            elif unused_fit_total >= -drift:
                unused_fit_total += drift
            else:
                idle_no_total += drift
        else:
            # Trust calendars: recompute idle from classification.
            idle_sec = classified
    return idle_sec, idle_no_total, unused_fit_total


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


def _status(staff_sec: int, used_sec: int, idle_no_work: int, unused_fit: int) -> str:
    if staff_sec <= 0:
        return "no_staff"
    # Fully utilized when DES used the whole staff window.
    if used_sec >= staff_sec - 1:
        return "fully_utilized"
    if idle_no_work > 0 and unused_fit == 0:
        return "idle_waiting_for_work"
    if idle_no_work > 0 and unused_fit > 0:
        return "partial_upstream_short"
    if unused_fit > 0:
        return "work_not_fit"
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
    bags: list[Any],
    load_sec: dict[str, int],
) -> dict[str, Any]:
    w0, w1 = interval.start_sec, interval.end_sec
    employee_ids = _employee_ids_for_interval(
        interval, authored_all=authored_all, employees=employees
    )
    staff_sec = _staff_sec_for_employees(employee_ids, employees, w0, w1)
    if staff_sec == 0:
        staff_sec = interval.people * max(0, w1 - w0)

    if interval.hybrid_type:
        roles = list(HYBRID_SPECS[interval.hybrid_type])
        tasks = {ROLE_LABOR_TASK[r] for r in roles}
        used_sec, by_task = _used_labor(employee_ids, calendars, w0, w1, tasks=tasks)
        available_sec, eligible_bags, physical_loads, at_start, became = _hybrid_eligible_demand(
            bags,
            roles=roles,
            w0=w0,
            w1=w1,
            load_sec=load_sec,
            calendars=calendars,
        )
        idle_sec, idle_no_work, unused_fit = _classify_idle_from_calendars(
            employee_ids,
            calendars=calendars,
            bags=bags,
            w0=w0,
            w1=w1,
            roles=roles,
            tasks=tasks,
            staff_sec=staff_sec,
            used_sec=used_sec,
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
        )
        idle_sec, idle_no_work, unused_fit = _classify_idle_from_calendars(
            employee_ids,
            calendars=calendars,
            bags=bags,
            w0=w0,
            w1=w1,
            roles=roles,
            tasks=tasks,
            staff_sec=staff_sec,
            used_sec=used_sec,
        )
        role_alloc = None
        primary_role = role
        label_role = role

    status = _status(staff_sec, used_sec, idle_no_work, unused_fit)
    staff_min = _min2(staff_sec)
    available_min = _min2(available_sec)
    used_min = _min2(used_sec)
    idle_min = _min2(idle_sec)
    idle_no_min = _min2(idle_no_work)
    unused_fit_min = _min2(unused_fit)

    return {
        "index": index,
        "role": primary_role,
        "hybrid": interval.hybrid_type,
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
            done_before = _loads_completed_before(bag.bag_id, task, w0, calendars)
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
        reason_bits.append(f"{_fmt_min(idle_no_min)} waiting")
    if unused_fit_min > 0.005:
        reason_bits.append(f"{_fmt_min(unused_fit_min)} unused_fit")
    reason = (" · " + " · ".join(reason_bits)) if reason_bits else ""
    return (
        f"{head} · {used_i} of {staff_i} productive · {util}% · "
        f"{idle_i} unused{reason} · {_status_label(status, idle_min)}"
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
