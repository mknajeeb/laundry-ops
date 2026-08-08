"""Typed resource calendars with no-overlap enforcement (Phase 1).

Resource identity is always (resource_type, resource_id). Never infer type from ID prefix.
Intervals are half-open: [start, end).
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from backend.shift_capacity.models import Employee, Provenance, Reservation, Task, ValidationError

ResourceType = Literal["employee", "washer_machine", "dryer_machine"]
ResourceKey = tuple[str, str]


def intervals_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    """Half-open overlap: [a,b) overlaps [c,d) iff a < d and c < b."""
    return start_a < end_b and start_b < end_a


class OverlapError(Exception):
    def __init__(self, error: ValidationError):
        super().__init__(error.message)
        self.error = error


@dataclass
class ReserveResult:
    start: int
    end: int
    task_id: str
    reservation: Reservation


class ResourceCalendar:
    """Keyed by (resource_type, resource_id). Overlaps are never silently repaired."""

    def __init__(self) -> None:
        self._data: dict[ResourceKey, list[Reservation]] = {}
        self._seq = 0

    # --- Compat views used by serialization / state ---
    @property
    def calendars(self) -> dict[str, list[Reservation]]:
        """Map resource_id → reservations (type implied by which calendar owns the key)."""
        out: dict[str, list[Reservation]] = {}
        for (_rtype, rid), rows in self._data.items():
            out.setdefault(rid, [])
            out[rid].extend(rows)
            out[rid].sort(key=lambda r: (r.start, r.end))
        return out

    def reservations(self, resource_id: str, resource_type: ResourceType | None = None) -> list[Reservation]:
        if resource_type is not None:
            return list(self._data.get((resource_type, resource_id), []))
        rows: list[Reservation] = []
        for (rtype, rid), items in self._data.items():
            if rid == resource_id:
                rows.extend(items)
        return sorted(rows, key=lambda r: (r.start, r.end))

    def checkpoint(self) -> dict[ResourceKey, list[Reservation]]:
        return deepcopy(self._data)

    def restore(self, snapshot: dict[ResourceKey, list[Reservation]]) -> None:
        self._data = deepcopy(snapshot)

    def next_free(
        self,
        resource_id: str,
        *,
        resource_type: ResourceType,
        not_before: int = 0,
    ) -> int:
        busy = sorted(self._data.get((resource_type, resource_id), []), key=lambda r: r.start)
        t = int(not_before)
        for res in busy:
            if res.end <= t:
                continue
            if res.start > t:
                return t
            t = max(t, res.end)
        return t

    def is_free(
        self,
        resource_id: str,
        start: int,
        end: int,
        *,
        resource_type: ResourceType,
        excluding_reservation_id: str | None = None,
    ) -> bool:
        for res in self._data.get((resource_type, resource_id), []):
            if excluding_reservation_id and res.reservation_id == excluding_reservation_id:
                continue
            if intervals_overlap(start, end, res.start, res.end):
                return False
        return True

    def find_earliest_available(
        self,
        resource_id: str,
        earliest_start: int,
        duration: int,
        *,
        resource_type: ResourceType,
        pending: list[tuple[int, int]] | None = None,
    ) -> tuple[int, int]:
        """Return earliest [start, end) that fits full duration with no overlap.

        `next_free` alone is not enough: a 1-minute hole before a busy block must not
        be accepted for a 2-minute task.
        """
        dur = max(0, int(duration))
        t = int(earliest_start)
        if dur == 0:
            start = self.next_free(resource_id, resource_type=resource_type, not_before=t)
            return start, start

        busy = list(self._data.get((resource_type, resource_id), []))
        for p_start, p_end in pending or []:
            busy.append(
                Reservation(
                    reservation_id=f"pending_{p_start}_{p_end}",
                    resource_id=resource_id,
                    resource_type=resource_type,
                    start=int(p_start),
                    end=int(p_end),
                    task_id="pending",
                    task_type="pending",
                )
            )
        busy.sort(key=lambda r: r.start)

        # Seconds timebase can require many jumps across short reservations.
        for _ in range(10_000):
            start = t
            for res in busy:
                if res.end <= start:
                    continue
                if res.start > start:
                    break
                start = max(start, res.end)
            end = start + dur
            overlaps = [r for r in busy if intervals_overlap(start, end, r.start, r.end)]
            if not overlaps:
                return start, end
            t = max(r.end for r in overlaps)
        # Degenerate fallback — caller / reserve will assert.
        start = self.next_free(resource_id, resource_type=resource_type, not_before=int(earliest_start))
        return start, start + dur

    def reserve_at_earliest_available(
        self,
        resource_id: str,
        earliest_start: int,
        duration: int,
        *,
        resource_type: ResourceType,
        task_type: str,
        bag_ids: list[str] | None = None,
        batch_id: str | None = None,
        required_role: str | None = None,
        provenance: Provenance = "recalculated",
        task_id: str | None = None,
    ) -> ReserveResult:
        start, end = self.find_earliest_available(
            resource_id, earliest_start, duration, resource_type=resource_type
        )
        return self._commit(
            resource_id=resource_id,
            resource_type=resource_type,
            start=start,
            end=end,
            task_type=task_type,
            bag_ids=bag_ids,
            batch_id=batch_id,
            required_role=required_role,
            provenance=provenance,
            task_id=task_id,
            hard_assignment=False,
        )

    def reserve_exact(
        self,
        resource_id: str,
        start: int,
        end: int,
        *,
        resource_type: ResourceType,
        task_type: str,
        bag_ids: list[str] | None = None,
        batch_id: str | None = None,
        required_role: str | None = None,
        provenance: Provenance = "recalculated",
        task_id: str | None = None,
    ) -> ReserveResult:
        start_i, end_i = int(start), int(end)
        if end_i < start_i:
            end_i = start_i
        self._assert_free(resource_id, start_i, end_i, resource_type=resource_type)
        return self._commit(
            resource_id=resource_id,
            resource_type=resource_type,
            start=start_i,
            end=end_i,
            task_type=task_type,
            bag_ids=bag_ids,
            batch_id=batch_id,
            required_role=required_role,
            provenance=provenance,
            task_id=task_id,
            hard_assignment=True,
        )

    def reserve_resource(
        self,
        resource_id: str,
        earliest_start: int,
        duration: int,
        *,
        resource_type: ResourceType = "employee",
        task_type: str,
        bag_ids: list[str] | None = None,
        batch_id: str | None = None,
        required_role: str | None = None,
        hard_start: int | None = None,
        hard_end: int | None = None,
        provenance: Provenance = "recalculated",
        task_id: str | None = None,
        allow_overlap_check_only: bool = False,
    ) -> ReserveResult:
        """Compat wrapper: hard_start → reserve_exact; else reserve_at_earliest_available."""
        if hard_start is not None:
            start = int(hard_start)
            end = start + max(0, int(duration))
            if hard_end is not None and end > hard_end:
                raise OverlapError(
                    ValidationError(
                        code="HARD_END_VIOLATION",
                        message=f"Resource {resource_id} cannot finish by hard end",
                        details={"resource_id": resource_id, "resource_type": resource_type, "hard_end": hard_end},
                    )
                )
            if allow_overlap_check_only:
                self._assert_free(resource_id, start, end, resource_type=resource_type)
                tid = task_id or self._new_task_id(task_type)
                return ReserveResult(
                    start=start,
                    end=end,
                    task_id=tid,
                    reservation=Reservation(
                        reservation_id=f"chk_{tid}",
                        resource_id=resource_id,
                        resource_type=resource_type,
                        start=start,
                        end=end,
                        task_id=tid,
                        task_type=task_type,
                    ),
                )
            return self.reserve_exact(
                resource_id,
                start,
                end,
                resource_type=resource_type,
                task_type=task_type,
                bag_ids=bag_ids,
                batch_id=batch_id,
                required_role=required_role,
                provenance=provenance,
                task_id=task_id,
            )
        return self.reserve_at_earliest_available(
            resource_id,
            earliest_start,
            duration,
            resource_type=resource_type,
            task_type=task_type,
            bag_ids=bag_ids,
            batch_id=batch_id,
            required_role=required_role,
            provenance=provenance,
            task_id=task_id,
        )

    def install_reservation(self, resource_id: str, reservation: Reservation) -> None:
        rtype: ResourceType = reservation.resource_type  # type: ignore[assignment]
        if rtype not in ("employee", "washer_machine", "dryer_machine"):
            rtype = "employee"
        self._assert_free(
            resource_id,
            reservation.start,
            reservation.end,
            resource_type=rtype,
            excluding_reservation_id=reservation.reservation_id,
        )
        key = (rtype, resource_id)
        existing = [r for r in self._data.get(key, []) if r.reservation_id != reservation.reservation_id]
        existing.append(reservation)
        existing.sort(key=lambda r: (r.start, r.end))
        self._data[key] = existing

    def clear_from(self, resource_id: str, t: int, *, keep_in_progress: bool = True, resource_type: ResourceType | None = None) -> list[Reservation]:
        removed: list[Reservation] = []
        keys = list(self._data)
        for key in keys:
            rtype, rid = key
            if rid != resource_id:
                continue
            if resource_type is not None and rtype != resource_type:
                continue
            kept: list[Reservation] = []
            for res in self._data.get(key, []):
                if res.end <= t:
                    kept.append(res)
                elif keep_in_progress and res.start < t < res.end:
                    kept.append(res)
                else:
                    removed.append(res)
            self._data[key] = kept
        return removed

    def overlap_errors(self) -> list[str]:
        bad: list[str] = []
        for (rtype, rid), rows in self._data.items():
            ordered = sorted(rows, key=lambda r: r.start)
            for i in range(1, len(ordered)):
                if intervals_overlap(ordered[i - 1].start, ordered[i - 1].end, ordered[i].start, ordered[i].end):
                    bad.append(f"{rtype}:{rid}")
                    break
        return bad

    def _commit(
        self,
        *,
        resource_id: str,
        resource_type: ResourceType,
        start: int,
        end: int,
        task_type: str,
        bag_ids: list[str] | None,
        batch_id: str | None,
        required_role: str | None,
        provenance: Provenance,
        task_id: str | None,
        hard_assignment: bool,
    ) -> ReserveResult:
        self._assert_free(resource_id, start, end, resource_type=resource_type)
        tid = task_id or self._new_task_id(task_type)
        reservation = Reservation(
            reservation_id=f"res_{tid}",
            resource_id=resource_id,
            resource_type=resource_type,
            start=start,
            end=end,
            task_id=tid,
            task_type=task_type,
            bag_ids=list(bag_ids or []),
            batch_id=batch_id,
            provenance=provenance,
            required_role=required_role,
            hard_assignment=hard_assignment,
        )
        key = (resource_type, resource_id)
        self._data.setdefault(key, []).append(reservation)
        self._data[key].sort(key=lambda r: (r.start, r.end))
        return ReserveResult(start=start, end=end, task_id=tid, reservation=reservation)

    def _new_task_id(self, task_type: str) -> str:
        self._seq += 1
        return f"task_{task_type}_{self._seq}_{uuid4().hex[:6]}"

    def _assert_free(
        self,
        resource_id: str,
        start: int,
        end: int,
        *,
        resource_type: ResourceType,
        excluding_reservation_id: str | None = None,
    ) -> None:
        for res in self._data.get((resource_type, resource_id), []):
            if excluding_reservation_id and res.reservation_id == excluding_reservation_id:
                continue
            if intervals_overlap(start, end, res.start, res.end):
                code = "RESOURCE_OVERLAP"
                raise OverlapError(
                    ValidationError(
                        code=code,
                        message=f"Resource {resource_type}:{resource_id} overlaps existing task {res.task_id}",
                        details={
                            "code": code,
                            "resource_type": resource_type,
                            "resource_id": resource_id,
                            "requested_start": start,
                            "requested_end": end,
                            "conflicting_reservation_id": res.reservation_id,
                            "conflicting_task_id": res.task_id,
                            "conflict_start": res.start,
                            "conflict_end": res.end,
                        },
                    )
                )


def _norm_role(role: str) -> str:
    role = (role or "").strip().lower()
    if role in ("dry", "dryer_person", "dryer-person"):
        return "dryer"
    if role in ("weigh",):
        return "weigher"
    if role in ("sort",):
        return "sorter"
    if role in ("wash", "washer_person"):
        return "washer"
    if role in ("fold",):
        return "folder"
    return role


def role_active_at(emp: Employee, role: str, t: int) -> bool:
    if not emp.active:
        return False
    on_shift = False
    for window in emp.schedule_windows:
        end = window.end_min if window.end_min is not None else 10**9
        if window.start_min <= t < end:
            on_shift = True
            break
    if not on_shift:
        return False

    role = _norm_role(role)
    if emp.role_windows:
        for rw in emp.role_windows:
            if _norm_role(rw.role) == role and rw.start_min <= t < rw.end_min:
                return True
        return False

    qualified = {_norm_role(emp.primary_role), *[_norm_role(r) for r in emp.qualified_roles]}
    return role in qualified


def earliest_entry(emp: Employee) -> int:
    return emp.start_min()


def pick_employee(
    employees: list[Employee],
    role: str,
    calendar: ResourceCalendar,
    earliest: int,
    duration: int,
    *,
    forced_id: str | None = None,
    finish_current_exit: bool = True,
) -> tuple[Employee | None, int]:
    """Pick the employee who can start the role task soonest without overlap."""
    candidates: list[tuple[int, Employee]] = []
    pool = employees
    if forced_id:
        pool = [e for e in employees if e.employee_id == forced_id]
        if not pool:
            return None, earliest

    for emp in pool:
        if not emp.active:
            continue
        entry = earliest_entry(emp)
        probe = max(int(earliest), entry)
        attempts = 0
        while attempts < 512:
            if role_active_at(emp, role, probe):
                end_limit = emp.end_min()
                if end_limit is not None and probe >= end_limit:
                    break
                start, end = calendar.find_earliest_available(
                    emp.employee_id,
                    probe,
                    max(0, int(duration)),
                    resource_type="employee",
                )
                if not role_active_at(emp, role, start):
                    next_role_start = _next_role_start(emp, role, start)
                    if next_role_start is None:
                        break
                    probe = max(next_role_start, start)
                    attempts += 1
                    continue
                if end_limit is not None and start >= end_limit:
                    break
                if end_limit is not None and not finish_current_exit and end > end_limit:
                    break
                candidates.append((start, emp))
                break
            next_role_start = _next_role_start(emp, role, probe)
            if next_role_start is None:
                break
            probe = next_role_start
            attempts += 1

    if not candidates:
        return None, earliest
    candidates.sort(key=lambda item: (item[0], item[1].employee_id))
    start, emp = candidates[0]
    return emp, start


def _next_role_start(emp: Employee, role: str, after: int) -> int | None:
    role = _norm_role(role)
    if emp.role_windows:
        starts = [rw.start_min for rw in emp.role_windows if _norm_role(rw.role) == role and rw.end_min > after]
        future = [s for s in starts if s >= after]
        return min(future) if future else None
    # Jump to the next schedule window start after `after` (supports gapped slots).
    next_windows = sorted(
        w.start_min for w in emp.schedule_windows if w.start_min > after
    )
    if next_windows:
        return next_windows[0]
    if after < earliest_entry(emp):
        return earliest_entry(emp)
    return None


def task_from_reservation(res: Reservation, resource_id: str | None = None) -> Task:
    return Task(
        task_id=res.task_id,
        task_type=res.task_type,
        start_min=res.start,
        end_min=res.end,
        resource_id=resource_id or res.resource_id,
        bag_ids=list(res.bag_ids),
        batch_id=res.batch_id,
        required_role=res.required_role,
        provenance=res.provenance,
    )
