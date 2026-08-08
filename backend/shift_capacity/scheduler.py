"""Core bag-level discrete-event scheduler.

All labor and machine work goes through ResourceCalendar.reserve_resource.
Summaries must be derived from the resulting Bag records — never calculated separately.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend.shift_capacity.batch_builder import build_batches, effective_override, expand_bags, split_bags_by_weight
from backend.shift_capacity.models import (
    Bag,
    Batch,
    ContinuationMeta,
    Provenance,
    SimulationInputs,
    SimulationState,
    Task,
    ValidationError,
    ValidationResult,
    new_id,
)
from backend.shift_capacity.resources import (
    OverlapError,
    ResourceCalendar,
    pick_employee,
    task_from_reservation,
)
from backend.shift_capacity.timebase import duration_sec, duration_sec_from_min
from backend.shift_capacity.validation import label_minutes, validate_inputs


STAGE_FIELDS = (
    ("weigh", "weigh_start", "weigh_end"),
    ("sort", "sort_start", "sort_end"),
    ("washer_load", "washer_load_start", "washer_load_end"),
    ("wash", "wash_start", "wash_end"),
    ("transfer", "transfer_start", "transfer_end"),
    ("dryer_load", "dryer_load_start", "dryer_load_end"),
    ("dry", "dry_start", "dry_end"),
    ("fold", "fold_start", "fold_end"),
)


def _dur(value_min: float) -> int:
    """Convert minute-based duration to seconds. Minimum 1s when value > 0."""
    sec = duration_sec_from_min(value_min)
    if float(value_min) > 0 and sec == 0:
        return 1
    return sec


def _weigh_duration_sec(emp: Any | None, inp: SimulationInputs) -> int:
    if emp is not None and emp.default_rates.weigh_min_per_bag is not None:
        return max(1, _dur(emp.default_rates.weigh_min_per_bag))
    return max(1, duration_sec(inp.processing_times.weigh_sec_per_bag))


def _emp_rate_min(emp: Any, kind: str, inp: SimulationInputs) -> float:
    rates = emp.default_rates
    defaults = inp.processing_times
    mapping = {
        "weigher": (rates.weigh_min_per_bag, defaults.weigh_min_per_bag),
        "sorter": (rates.sort_min_per_bag, defaults.sort_min_per_bag),
        "load_washer": (rates.load_washer_min, defaults.load_washer_min),
        "transfer": (rates.transfer_min, defaults.transfer_min),
        "load_dryer": (rates.load_dryer_min, defaults.load_dryer_min),
    }
    override, default = mapping[kind]
    return float(override if override is not None else default)


def _fold_duration_min(emp: Any, bag: Bag, inp: SimulationInputs) -> float:
    rates = emp.default_rates
    if inp.processing_times.fold_rate_mode == "minutes_per_bag":
        return float(rates.fold_min_per_bag if rates.fold_min_per_bag is not None else inp.processing_times.fold_min_per_bag)
    lbs_per_hour = float(
        rates.fold_lbs_per_hour if rates.fold_lbs_per_hour is not None else inp.processing_times.fold_lbs_per_hour
    )
    return max(0.1, (bag.weight_lb / max(1.0, lbs_per_hour)) * 60.0)


def _dry_labor_role(inp: SimulationInputs) -> str:
    return "dryer" if inp.management_mode else "washer"


def _book_employee(
    calendar: ResourceCalendar,
    emp: Any,
    earliest: int,
    duration_sec_val: int,
    *,
    task_type: str,
    bag_ids: list[str],
    batch_id: str | None = None,
    required_role: str | None = None,
    hard_start: int | None = None,
    provenance: Provenance = "recalculated",
) -> tuple[int, int, str]:
    dur = max(0, int(duration_sec_val))
    if hard_start is not None:
        start = int(hard_start)
        end = start + dur
        result = calendar.reserve_exact(
            emp.employee_id,
            start,
            end,
            resource_type="employee",
            task_type=task_type,
            bag_ids=bag_ids,
            batch_id=batch_id,
            required_role=required_role,
            provenance=provenance,
        )
    else:
        result = calendar.reserve_at_earliest_available(
            emp.employee_id,
            earliest,
            dur,
            resource_type="employee",
            task_type=task_type,
            bag_ids=bag_ids,
            batch_id=batch_id,
            required_role=required_role,
            provenance=provenance,
        )
    return result.start, result.end, result.task_id


def _book_synthetic_employee(
    calendar: ResourceCalendar,
    resource_id: str,
    earliest: int,
    duration_sec_val: int | float,
    *,
    task_type: str,
    bag_ids: list[str],
    hard: bool = False,
    management_mode: bool = False,
) -> tuple[int, int]:
    """Compat-only synthetic labor. Forbidden when management_mode is true."""
    if management_mode:
        raise RuntimeError(
            "synthetic labor is forbidden when management_mode=true "
            f"(attempted {resource_id!r} task={task_type!r})"
        )
    dur = max(0, int(round(float(duration_sec_val))))
    if hard:
        start = int(earliest)
        end = start + dur
        result = calendar.reserve_exact(
            resource_id, start, end, resource_type="employee", task_type=task_type, bag_ids=bag_ids
        )
    else:
        result = calendar.reserve_at_earliest_available(
            resource_id, earliest, dur, resource_type="employee", task_type=task_type, bag_ids=bag_ids
        )
    return result.start, result.end


def run_scheduler(
    inp: SimulationInputs,
    *,
    frozen: SimulationState | None = None,
    resume_from: int | None = None,
) -> SimulationState:
    validation = validate_inputs(inp)
    state = SimulationState(
        inputs=inp,
        scenario_id=inp.scenario_id or new_id("scn"),
        parent_scenario_id=inp.parent_scenario_id,
        mode=inp.mode,
        validation=validation,
    )
    if not validation.accepted:
        return state

    bags = expand_bags(inp)
    for bag in bags:
        bag.entry_time = inp.shift.start_min

    emp_cal = ResourceCalendar()
    machine_cal = ResourceCalendar()
    washers = [m.machine_id for m in inp.machines if m.kind == "washer"]
    dryers = [m.machine_id for m in inp.machines if m.kind == "dryer"]

    preserved_batches: list[Batch] = []
    skip_bag_ids: set[str] = set()
    continuation = ContinuationMeta()
    event_start = inp.shift.start_min

    if frozen is not None and resume_from is not None:
        event_start = resume_from
        bags, preserved_batches, skip_bag_ids, continuation = _install_freeze(
            bags, frozen, resume_from, emp_cal, machine_cal
        )
        continuation.event_queue_starts_at_min = resume_from
        continuation.history_frozen_through = label_minutes(resume_from)
        continuation.history_frozen_through_min = resume_from
        continuation.recalculated_from = label_minutes(resume_from)
        continuation.recalculated_from_min = resume_from

    # --- Weigh + Sort (only unfrozen stages) ---
    for bag in bags:
        if bag.weigh_start is not None and bag.weigh_start < (resume_from or -1):
            continue
        if resume_from is not None and bag.weigh_end is not None and bag.weigh_end <= resume_from:
            continue
        _schedule_weigh(bag, inp, emp_cal, not_before=max(bag.entry_time or event_start, event_start))

    for bag in bags:
        if bag.sort_start is not None and bag.sort_start < (resume_from or -1):
            continue
        if resume_from is not None and bag.sort_end is not None and bag.sort_end <= resume_from:
            continue
        _schedule_sort(bag, inp, emp_cal, not_before=max(bag.weigh_end or event_start, event_start))

    batches, batch_errors = build_batches(
        bags,
        inp,
        locked_batches=preserved_batches,
        skip_bag_ids=skip_bag_ids,
    )
    if batch_errors:
        state.validation = ValidationResult(accepted=False, errors=batch_errors)
        state.bags = bags
        state.batches = batches
        state.continuation = continuation
        return state

    bags_by_id = {b.bag_id: b for b in bags}
    force_errors: list[ValidationError] = []

    for batch in batches:
        if batch.provenance in ("preserved", "in_progress_preserved") and batch.wash_start is not None:
            if resume_from is not None and (batch.wash_start or 0) < resume_from:
                continue
        try:
            _process_batch(batch, bags_by_id, inp, emp_cal, machine_cal, washers, dryers, event_start=event_start)
        except OverlapError as exc:
            force_errors.append(exc.error)

    if force_errors:
        state.validation = ValidationResult(accepted=False, errors=force_errors)
        state.bags = bags
        state.batches = batches
        state.continuation = continuation
        state.employee_calendars = emp_cal.calendars
        state.machine_calendars = machine_cal.calendars
        return state

    # Fold
    ready_order = sorted(
        bags,
        key=lambda b: (b.ready_to_fold or 10**9, 0 if b.rush else 1, b.priority, b.bag_id),
    )
    for bag in ready_order:
        if bag.fold_start is not None and resume_from is not None and bag.fold_start < resume_from:
            continue
        _schedule_fold(bag, inp, emp_cal, not_before=max(bag.ready_to_fold or event_start, event_start))

    for bag in bags:
        bag.recompute_waits()
        _tag_provenance(bag, resume_from)

    if resume_from is not None:
        continuation.preserved_task_count = sum(
            1 for b in bags for stage, _, _ in STAGE_FIELDS if b.stage_provenance.get(stage) == "preserved"
        )
        continuation.in_progress_task_count = sum(
            1 for b in bags for stage, _, _ in STAGE_FIELDS if b.stage_provenance.get(stage) == "in_progress_preserved"
        )
        continuation.recalculated_task_count = sum(
            1 for b in bags for stage, _, _ in STAGE_FIELDS if b.stage_provenance.get(stage) == "recalculated"
        )
        continuation.preserved_batch_ids = [b.batch_id for b in batches if b.provenance in ("preserved", "in_progress_preserved")]
        continuation.recalculated_batch_ids = [b.batch_id for b in batches if b.provenance == "recalculated"]

    tasks: list[Task] = []
    for rid, rows in {**emp_cal.calendars, **machine_cal.calendars}.items():
        for res in rows:
            tasks.append(task_from_reservation(res, rid))

    overlaps = emp_cal.overlap_errors() + machine_cal.overlap_errors()
    if overlaps:
        state.validation = ValidationResult(
            accepted=False,
            errors=[ValidationError("OVERLAP", f"Overlap on {rid}", {"resource_id": rid}) for rid in overlaps],
        )

    if inp.management_mode:
        forbidden = [
            rid
            for rid in emp_cal.calendars
            if rid.startswith("__") or rid == "Unassigned"
        ]
        if forbidden:
            raise RuntimeError(
                "management_mode synthetic labor calendar leak: " + ", ".join(sorted(forbidden))
            )

    state.bags = bags
    state.batches = batches
    state.tasks = tasks
    state.employee_calendars = emp_cal.calendars
    state.machine_calendars = machine_cal.calendars
    state.continuation = continuation
    return state


def _schedule_weigh(bag: Bag, inp: SimulationInputs, emp_cal: ResourceCalendar, *, not_before: int) -> None:
    dur_sec = _weigh_duration_sec(None, inp)
    emp, t0 = pick_employee(
        inp.employees, "weigher", emp_cal, not_before, dur_sec, finish_current_exit=inp.finish_in_progress_at_exit
    )
    if emp is None:
        if inp.management_mode:
            return  # no synthetic labor — bag remains not_yet_weighed / waiting
        start, end = _book_synthetic_employee(
            emp_cal,
            "__weigh__",
            not_before,
            dur_sec,
            task_type="weigh",
            bag_ids=[bag.bag_id],
            management_mode=inp.management_mode,
        )
        bag.weigh_start, bag.weigh_end = start, end
        bag.weighed_by_employee_id = "Unassigned"
        return
    dur_sec = _weigh_duration_sec(emp, inp)
    start, end, _ = _book_employee(
        emp_cal, emp, t0, dur_sec, task_type="weigh", bag_ids=[bag.bag_id], required_role="weigher"
    )
    bag.weigh_start, bag.weigh_end = start, end
    bag.weighed_by_employee_id = emp.employee_id


def _schedule_sort(bag: Bag, inp: SimulationInputs, emp_cal: ResourceCalendar, *, not_before: int) -> None:
    if bag.weigh_end is None:
        return
    dur_sec = _dur(inp.processing_times.sort_min_per_bag)
    emp, t0 = pick_employee(
        inp.employees, "sorter", emp_cal, not_before, dur_sec, finish_current_exit=inp.finish_in_progress_at_exit
    )
    if emp is None:
        if inp.management_mode:
            return
        start, end = _book_synthetic_employee(
            emp_cal,
            "__sort__",
            not_before,
            dur_sec,
            task_type="sort",
            bag_ids=[bag.bag_id],
            management_mode=inp.management_mode,
        )
        bag.sort_start, bag.sort_end = start, end
        bag.sorted_by_employee_id = "Unassigned"
        return
    dur_sec = _dur(_emp_rate_min(emp, "sorter", inp))
    start, end, _ = _book_employee(
        emp_cal, emp, t0, dur_sec, task_type="sort", bag_ids=[bag.bag_id], required_role="sorter"
    )
    bag.sort_start, bag.sort_end = start, end
    bag.sorted_by_employee_id = emp.employee_id


def _schedule_fold(bag: Bag, inp: SimulationInputs, emp_cal: ResourceCalendar, *, not_before: int) -> None:
    if bag.ready_to_fold is None:
        return
    probe_min = (
        inp.processing_times.fold_min_per_bag
        if inp.processing_times.fold_rate_mode == "minutes_per_bag"
        else max(0.1, (bag.weight_lb / max(1.0, inp.processing_times.fold_lbs_per_hour)) * 60.0)
    )
    probe_sec = _dur(probe_min)
    emp, t0 = pick_employee(
        inp.employees, "folder", emp_cal, not_before, probe_sec, finish_current_exit=inp.finish_in_progress_at_exit
    )
    if emp is None:
        if inp.management_mode:
            return
        start, end = _book_synthetic_employee(
            emp_cal,
            "__fold__",
            not_before,
            probe_sec,
            task_type="fold",
            bag_ids=[bag.bag_id],
            management_mode=inp.management_mode,
        )
        bag.fold_start, bag.fold_end = start, end
        bag.folder_employee_id = "Unassigned"
        bag.folded_by_employee_id = "Unassigned"
        bag.completed_at = end
        return
    dur_sec = _dur(_fold_duration_min(emp, bag, inp))
    start, end, _ = _book_employee(
        emp_cal, emp, t0, dur_sec, task_type="fold", bag_ids=[bag.bag_id], required_role="folder"
    )
    bag.fold_start, bag.fold_end = start, end
    bag.folder_employee_id = emp.employee_id
    bag.folded_by_employee_id = emp.employee_id
    bag.completed_at = end


def _process_batch(
    batch: Batch,
    bags_by_id: dict[str, Bag],
    inp: SimulationInputs,
    emp_cal: ResourceCalendar,
    machine_cal: ResourceCalendar,
    washers: list[str],
    dryers: list[str],
    *,
    event_start: int,
) -> None:
    """Schedule wash/dry for a batch with atomic machine occupancy and rollback."""
    override = effective_override(inp.batch_overrides, batch.sequence)
    members = [bags_by_id[bid] for bid in batch.bag_ids]
    if any(b.sort_end is None for b in members):
        return
    ready_sort = max(b.sort_end or event_start for b in members)
    if override and override.earliest_start_min is not None:
        ready_sort = max(ready_sort, override.earliest_start_min)

    hard = bool(override and override.locked_start)

    split_wash = any(b.requires_two_washers for b in members) and len(members) >= 2 and len(washers) >= 2
    wash_groups = split_bags_by_weight(members, 2) if split_wash else [members]

    washer_ids_used: list[str] = []
    wash_failed = False
    for group in wash_groups:
        ok = _schedule_wash_group(
            group,
            batch=batch,
            inp=inp,
            emp_cal=emp_cal,
            machine_cal=machine_cal,
            washers=washers,
            ready_sort=ready_sort,
            override=override,
            hard=hard,
            washer_ids_used=washer_ids_used,
        )
        if not ok:
            if inp.management_mode:
                # Partial wash (e.g. 2-washer split group2 failed): still attempt
                # dry for bags that already finished wash. No synthetic washer.
                wash_failed = True
                break
            raise OverlapError(
                ValidationError(
                    "RESOURCE_OVERLAP",
                    f"Could not place wash group for batch {batch.sequence}",
                    {"batch_number": batch.sequence},
                )
            )

    washed_members = [b for b in members if b.wash_end is not None]
    if not washed_members:
        return  # all still waiting_to_wash

    batch.washer_id = "+".join(washer_ids_used)
    batch.washer_load_start = min(b.washer_load_start for b in washed_members)  # type: ignore[type-var]
    batch.washer_load_end = max(b.washer_load_end for b in washed_members)  # type: ignore[type-var]
    batch.wash_start = min(b.wash_start for b in washed_members)  # type: ignore[type-var]
    batch.wash_end = max(b.wash_end for b in washed_members)  # type: ignore[type-var]
    batch.transfer_start = min(b.transfer_start for b in washed_members)  # type: ignore[type-var]
    batch.transfer_end = max(b.transfer_end for b in washed_members)  # type: ignore[type-var]

    # Dry cohorts by wash/transfer readiness. Never hold early wash-split
    # finishers until a later sibling's wash_end (default 80% 2-washer split
    # previously set dryer_ready=max(batch) past the dry staff window).
    cohorts: dict[int, list] = {}
    for bag in washed_members:
        ready_key = int(
            (bag.transfer_end if bag.transfer_end is not None else bag.wash_end) or event_start
        )
        cohorts.setdefault(ready_key, []).append(bag)

    dry_groups: list[list] = []
    for ready_key in sorted(cohorts):
        cohort = cohorts[ready_key]
        split_dry = (
            any(b.requires_two_dryers for b in cohort)
            and len(cohort) >= 2
            and len(dryers) >= 2
        )
        if split_dry:
            dry_groups.extend(split_bags_by_weight(cohort, 2))
        else:
            dry_groups.append(cohort)

    dryer_ids_used: list[str] = []
    ready_times: list[int] = []

    for group in dry_groups:
        group_ready = max(
            (b.transfer_end if b.transfer_end is not None else b.wash_end) or event_start
            for b in group
        )
        ready = _schedule_dry_group(
            group,
            batch=batch,
            inp=inp,
            emp_cal=emp_cal,
            machine_cal=machine_cal,
            dryers=dryers,
            dryer_ready=int(group_ready),
            override=override,
            hard=hard,
            dryer_ids_used=dryer_ids_used,
        )
        if ready is None:
            if inp.management_mode:
                # Remaining washed bags stay waiting_to_dry; no synthetic dry labor.
                break
            raise OverlapError(
                ValidationError(
                    "RESOURCE_OVERLAP",
                    f"Could not place dry group for batch {batch.sequence}",
                    {"batch_number": batch.sequence},
                )
            )
        ready_times.append(ready)

    dried_members = [b for b in washed_members if b.dryer_load_start is not None]
    if dried_members:
        batch.dryer_id = "+".join(dryer_ids_used)
        batch.dryer_load_start = min(b.dryer_load_start for b in dried_members)  # type: ignore[type-var]
        batch.dryer_load_end = max(b.dryer_load_end for b in dried_members)  # type: ignore[type-var]
        batch.dry_start = min(b.dry_start for b in dried_members)  # type: ignore[type-var]
        batch.dry_end = max(b.dry_end for b in dried_members)  # type: ignore[type-var]
        batch.ready_to_fold = max(ready_times) if ready_times else batch.transfer_end
    if batch.provenance != "manual_override":
        batch.provenance = "recalculated"
    if wash_failed and inp.management_mode:
        return


def _schedule_wash_group(
    group: list[Bag],
    *,
    batch: Batch,
    inp: SimulationInputs,
    emp_cal: ResourceCalendar,
    machine_cal: ResourceCalendar,
    washers: list[str],
    ready_sort: int,
    override,
    hard: bool,
    washer_ids_used: list[str],
) -> bool:
    cycle = _dur(inp.processing_times.wash_cycle_min)
    load_dur_default_sec = _dur(inp.processing_times.load_washer_min)
    if not washers:
        return False

    if override and override.washer_id:
        washer_id = override.washer_id
    else:
        washer_id = min(
            washers,
            key=lambda w: machine_cal.next_free(w, resource_type="washer_machine", not_before=ready_sort),
        )

    # Search for a mutual start where machine can hold load_start → wash_end.
    probe = ready_sort
    if hard and override and override.earliest_start_min is not None:
        probe = override.earliest_start_min

    planned: list[tuple[Bag, Any, int, int, int]] | None = None
    load_start = load_end = wash_end = 0
    for _attempt in range(2048):
        machine_free = machine_cal.next_free(washer_id, resource_type="washer_machine", not_before=probe)
        if hard and override and override.earliest_start_min is not None:
            if machine_free > override.earliest_start_min:
                raise OverlapError(
                    ValidationError(
                        code="RESOURCE_OVERLAP",
                        message=f"Washer machine {washer_id} busy at locked start",
                        details={
                            "resource_type": "washer_machine",
                            "resource_id": washer_id,
                            "requested_start": override.earliest_start_min,
                            "available_start": machine_free,
                            "batch_number": batch.sequence,
                        },
                    )
                )
            machine_free = override.earliest_start_min

        cursor = machine_free
        trial: list[tuple[Bag, Any, int, int, int]] = []
        pending_emp: dict[str, list[tuple[int, int]]] = {}
        for bag in group:
            forced = override.washer_person_id if override else None
            emp, t0 = pick_employee(
                inp.employees,
                "washer",
                emp_cal,
                cursor,
                load_dur_default_sec,
                forced_id=forced,
                finish_current_exit=inp.finish_in_progress_at_exit,
            )
            if forced and emp is None:
                raise OverlapError(
                    ValidationError(
                        "EMPLOYEE_NOT_FOUND",
                        f"Forced washer person {forced} unavailable",
                        {"employee_id": forced, "batch_number": batch.sequence},
                    )
                )
            if emp is None and inp.management_mode:
                trial = []
                break
            dur_sec = _dur(_emp_rate_min(emp, "load_washer", inp)) if emp else load_dur_default_sec
            if hard and forced and emp is not None:
                # Hard employee assignment cannot silently wait past requested cursor.
                start = cursor
                end = start + dur_sec
                if not emp_cal.is_free(emp.employee_id, start, end, resource_type="employee"):
                    raise OverlapError(
                        ValidationError(
                            code="RESOURCE_OVERLAP",
                            message=f"Employee {emp.employee_id} busy at hard assignment time",
                            details={
                                "resource_type": "employee",
                                "resource_id": emp.employee_id,
                                "requested_start": cursor,
                                "requested_end": end,
                                "batch_number": batch.sequence,
                            },
                        )
                    )
            elif emp is not None:
                start, end = emp_cal.find_earliest_available(
                    emp.employee_id,
                    max(cursor, t0, machine_free),
                    dur_sec,
                    resource_type="employee",
                    pending=pending_emp.get(emp.employee_id),
                )
            else:
                start = max(cursor, machine_free)
                end = start + dur_sec
            if emp is not None:
                pending_emp.setdefault(emp.employee_id, []).append((start, end))
            trial.append((bag, emp, start, end, dur_sec))
            cursor = end

        if not trial:
            if inp.management_mode:
                return False
            probe = machine_free + 1
            continue
        load_start = trial[0][2]
        load_end = trial[-1][3]
        wash_end = load_end + cycle
        if machine_cal.is_free(washer_id, load_start, wash_end, resource_type="washer_machine"):
            planned = trial
            break
        if hard:
            raise OverlapError(
                ValidationError(
                    code="RESOURCE_OVERLAP",
                    message=f"Washer machine {washer_id} cannot cover load through wash",
                    details={
                        "resource_type": "washer_machine",
                        "resource_id": washer_id,
                        "requested_start": load_start,
                        "requested_end": wash_end,
                        "batch_number": batch.sequence,
                    },
                )
            )
        probe = machine_cal.next_free(washer_id, resource_type="washer_machine", not_before=load_start + 1)

    if planned is None:
        if inp.management_mode:
            return False
        raise OverlapError(
            ValidationError(
                code="RESOURCE_OVERLAP",
                message=f"Could not place wash group on {washer_id}",
                details={"resource_type": "washer_machine", "resource_id": washer_id, "batch_number": batch.sequence},
            )
        )

    emp_snap = emp_cal.checkpoint()
    mach_snap = machine_cal.checkpoint()
    try:
        # One atomic machine reservation: load_start → wash_end
        machine_cal.reserve_exact(
            washer_id,
            load_start,
            wash_end,
            resource_type="washer_machine",
            task_type="wash",
            bag_ids=[b.bag_id for b in group],
            batch_id=batch.batch_id,
        )
        for bag, emp, start, end, dur_sec in planned:
            if emp is None:
                if inp.management_mode:
                    emp_cal.restore(emp_snap)
                    machine_cal.restore(mach_snap)
                    return False
                _book_synthetic_employee(
                    emp_cal,
                    "__wash_load__",
                    start,
                    dur_sec,
                    task_type="washer_load",
                    bag_ids=[bag.bag_id],
                    hard=True,
                    management_mode=inp.management_mode,
                )
                bag.washer_loaded_by_employee_id = "Unassigned"
            else:
                _book_employee(
                    emp_cal,
                    emp,
                    start,
                    dur_sec,
                    task_type="washer_load",
                    bag_ids=[bag.bag_id],
                    batch_id=batch.batch_id,
                    required_role="washer",
                    hard_start=start,
                )
                bag.washer_loaded_by_employee_id = emp.employee_id
            bag.washer_id = washer_id
            bag.washer_load_start = start
            bag.washer_load_end = end
            bag.wash_start = load_end
            bag.wash_end = wash_end

        # Transfers after wash (compat path only). Management mode has transfer_min=0
        # so dryer handling lives entirely in dry labor time.
        skip_transfer = inp.management_mode or float(inp.processing_times.transfer_min or 0) <= 0
        xfer_cursor = wash_end
        for bag in group:
            if skip_transfer:
                bag.transfer_start = wash_end
                bag.transfer_end = wash_end
                bag.transferred_by_employee_id = None
                continue
            forced = override.transfer_person_id if override else None
            xfer_dur_sec = _dur(inp.processing_times.transfer_min)
            emp, t0 = pick_employee(
                inp.employees,
                "washer",
                emp_cal,
                xfer_cursor,
                xfer_dur_sec,
                forced_id=forced,
                finish_current_exit=inp.finish_in_progress_at_exit,
            )
            if hard and forced and emp is not None:
                if emp_cal.next_free(emp.employee_id, resource_type="employee", not_before=xfer_cursor) > xfer_cursor:
                    raise OverlapError(
                        ValidationError(
                            code="RESOURCE_OVERLAP",
                            message=f"Transfer employee {emp.employee_id} busy at hard time",
                            details={"resource_type": "employee", "resource_id": emp.employee_id},
                        )
                    )
            if emp is None:
                start, end = _book_synthetic_employee(
                    emp_cal,
                    "__xfer__",
                    xfer_cursor,
                    xfer_dur_sec,
                    task_type="transfer",
                    bag_ids=[bag.bag_id],
                    management_mode=inp.management_mode,
                )
                bag.transfer_start, bag.transfer_end = start, end
                bag.transferred_by_employee_id = "Unassigned"
            else:
                dur_sec = _dur(_emp_rate_min(emp, "transfer", inp))
                start, end, _ = _book_employee(
                    emp_cal,
                    emp,
                    t0 if not (hard and forced) else xfer_cursor,
                    dur_sec,
                    task_type="transfer",
                    bag_ids=[bag.bag_id],
                    batch_id=batch.batch_id,
                    required_role="washer",
                    hard_start=xfer_cursor if (hard and forced) else None,
                )
                bag.transfer_start, bag.transfer_end = start, end
                bag.transferred_by_employee_id = emp.employee_id
            xfer_cursor = bag.transfer_end  # type: ignore[assignment]
        washer_ids_used.append(washer_id)
        return True
    except Exception:
        emp_cal.restore(emp_snap)
        machine_cal.restore(mach_snap)
        raise


def _plan_dry_group_on_dryer(
    group: list[Bag],
    *,
    batch: Batch,
    inp: SimulationInputs,
    emp_cal: ResourceCalendar,
    machine_cal: ResourceCalendar,
    dryer_id: str,
    dryer_ready: int,
    override,
    hard: bool,
    cycle: int,
    unload: int,
    load_dur_default_sec: int,
    dry_role: str,
) -> tuple[list[tuple[Bag, Any, int, int, int]], int, int, int, int] | None:
    """Return (planned, load_start, load_end, dry_end, ready) or None if unschedulable."""
    probe = dryer_ready
    for _attempt in range(2048):
        machine_free = machine_cal.next_free(dryer_id, resource_type="dryer_machine", not_before=probe)
        cursor = machine_free
        trial: list[tuple[Bag, Any, int, int, int]] = []
        pending_emp: dict[str, list[tuple[int, int]]] = {}
        for bag in group:
            forced = override.dryer_load_person_id if override else None
            emp, t0 = pick_employee(
                inp.employees,
                dry_role,
                emp_cal,
                cursor,
                load_dur_default_sec,
                forced_id=forced,
                finish_current_exit=inp.finish_in_progress_at_exit,
            )
            if forced and emp is None:
                raise OverlapError(
                    ValidationError(
                        "EMPLOYEE_NOT_FOUND",
                        f"Forced dryer-load person {forced} unavailable",
                        {"employee_id": forced, "batch_number": batch.sequence},
                    )
                )
            if emp is None and inp.management_mode:
                return None
            dur_sec = _dur(_emp_rate_min(emp, "load_dryer", inp)) if emp else load_dur_default_sec
            if hard and forced and emp is not None:
                start = cursor
                end = start + dur_sec
                if not emp_cal.is_free(emp.employee_id, start, end, resource_type="employee"):
                    raise OverlapError(
                        ValidationError(
                            code="RESOURCE_OVERLAP",
                            message=f"Employee {emp.employee_id} busy at hard dryer-load time",
                            details={
                                "resource_type": "employee",
                                "resource_id": emp.employee_id,
                                "requested_start": start,
                                "requested_end": end,
                            },
                        )
                    )
            elif emp is not None:
                start, end = emp_cal.find_earliest_available(
                    emp.employee_id,
                    max(cursor, t0, machine_free),
                    dur_sec,
                    resource_type="employee",
                    pending=pending_emp.get(emp.employee_id),
                )
            else:
                start = max(cursor, machine_free)
                end = start + dur_sec
            if emp is not None:
                pending_emp.setdefault(emp.employee_id, []).append((start, end))
            trial.append((bag, emp, start, end, dur_sec))
            cursor = end

        if not trial:
            return None
        load_start = trial[0][2]
        load_end = trial[-1][3]
        dry_end = load_end + cycle
        ready = dry_end + unload
        machine_end = ready if unload else dry_end
        if machine_cal.is_free(dryer_id, load_start, machine_end, resource_type="dryer_machine"):
            return trial, load_start, load_end, dry_end, ready
        if hard:
            raise OverlapError(
                ValidationError(
                    code="RESOURCE_OVERLAP",
                    message=f"Dryer machine {dryer_id} cannot cover load through dry",
                    details={
                        "resource_type": "dryer_machine",
                        "resource_id": dryer_id,
                        "requested_start": load_start,
                        "requested_end": machine_end,
                    },
                )
            )
        probe = machine_cal.next_free(dryer_id, resource_type="dryer_machine", not_before=load_start + 1)
    return None


def _schedule_dry_group(
    group: list[Bag],
    *,
    batch: Batch,
    inp: SimulationInputs,
    emp_cal: ResourceCalendar,
    machine_cal: ResourceCalendar,
    dryers: list[str],
    dryer_ready: int,
    override,
    hard: bool,
    dryer_ids_used: list[str],
) -> int | None:
    cycle = _dur(inp.processing_times.dry_cycle_min)
    unload = _dur(inp.processing_times.unload_dryer_min)
    load_dur_default_sec = _dur(inp.processing_times.load_dryer_min)
    dry_role = _dry_labor_role(inp)
    if not dryers:
        return None

    # Evaluate every dryer and take the earliest feasible load (then dryer_id).
    # Selecting only by next_free(dryer_ready) stuck all work on D1 when a labor-
    # delayed booking left a phantom gap before the first reservation.
    if override and override.dryer_id:
        candidate_dryers = [override.dryer_id]
    else:
        candidate_dryers = sorted(dryers)

    best: tuple[int, str, list[tuple[Bag, Any, int, int, int]], int, int, int] | None = None
    for dryer_id in candidate_dryers:
        planned = _plan_dry_group_on_dryer(
            group,
            batch=batch,
            inp=inp,
            emp_cal=emp_cal,
            machine_cal=machine_cal,
            dryer_id=dryer_id,
            dryer_ready=dryer_ready,
            override=override,
            hard=hard,
            cycle=cycle,
            unload=unload,
            load_dur_default_sec=load_dur_default_sec,
            dry_role=dry_role,
        )
        if planned is None:
            continue
        trial, load_start, load_end, dry_end, ready = planned
        key = (load_start, dryer_id)
        if best is None or key < (best[0], best[1]):
            best = (load_start, dryer_id, trial, load_end, dry_end, ready)

    if best is None:
        if inp.management_mode:
            return None
        raise OverlapError(
            ValidationError(
                code="RESOURCE_OVERLAP",
                message="Could not place dry group on any dryer",
                details={"resource_type": "dryer_machine", "dryer_ids": list(dryers)},
            )
        )

    load_start, dryer_id, planned, load_end, dry_end, ready = best

    emp_snap = emp_cal.checkpoint()
    mach_snap = machine_cal.checkpoint()
    try:
        machine_end = ready if unload else dry_end
        machine_cal.reserve_exact(
            dryer_id,
            load_start,
            machine_end,
            resource_type="dryer_machine",
            task_type="dry",
            bag_ids=[b.bag_id for b in group],
            batch_id=batch.batch_id,
        )
        for bag, emp, start, end, dur_sec in planned:
            if emp is None:
                if inp.management_mode:
                    emp_cal.restore(emp_snap)
                    machine_cal.restore(mach_snap)
                    return None
                _book_synthetic_employee(
                    emp_cal,
                    "__dry_load__",
                    start,
                    dur_sec,
                    task_type="dryer_load",
                    bag_ids=[bag.bag_id],
                    hard=True,
                    management_mode=inp.management_mode,
                )
                bag.dryer_loaded_by_employee_id = "Unassigned"
            else:
                _book_employee(
                    emp_cal,
                    emp,
                    start,
                    dur_sec,
                    task_type="dryer_load",
                    bag_ids=[bag.bag_id],
                    batch_id=batch.batch_id,
                    required_role=dry_role,
                    hard_start=start,
                )
                bag.dryer_loaded_by_employee_id = emp.employee_id
            bag.dryer_id = dryer_id
            bag.dryer_load_start = start
            bag.dryer_load_end = end
            bag.dry_start = load_end
            bag.dry_end = dry_end
            if unload:
                bag.dryer_unload_start = dry_end
                bag.dryer_unload_end = ready
            else:
                bag.dryer_unload_end = dry_end
            bag.ready_to_fold = ready
        dryer_ids_used.append(dryer_id)
        return ready
    except Exception:
        emp_cal.restore(emp_snap)
        machine_cal.restore(mach_snap)
        raise



def _tag_provenance(bag: Bag, resume_from: int | None) -> None:
    if resume_from is None:
        for stage, _, _ in STAGE_FIELDS:
            bag.stage_provenance[stage] = "recalculated"
        return
    for stage, start_key, end_key in STAGE_FIELDS:
        start = getattr(bag, start_key)
        end = getattr(bag, end_key)
        if start is None:
            continue
        if start < resume_from:
            if end is not None and end > resume_from:
                bag.stage_provenance[stage] = "in_progress_preserved"
            else:
                bag.stage_provenance[stage] = "preserved"
        else:
            bag.stage_provenance[stage] = "recalculated"


def _install_freeze(
    bags: list[Bag],
    frozen: SimulationState,
    t: int,
    emp_cal: ResourceCalendar,
    machine_cal: ResourceCalendar,
) -> tuple[list[Bag], list[Batch], set[str], ContinuationMeta]:
    """Install frozen bag stages, calendars, and completed/in-progress batches."""
    frozen_by_id = {b.bag_id: b for b in frozen.bags}
    for bag in bags:
        old = frozen_by_id.get(bag.bag_id)
        if not old:
            continue
        for field_name in (
            "entry_time",
            "weigh_start",
            "weigh_end",
            "sort_start",
            "sort_end",
            "available_to_wash",
            "washer_load_start",
            "washer_load_end",
            "wash_start",
            "wash_end",
            "transfer_start",
            "transfer_end",
            "dryer_load_start",
            "dryer_load_end",
            "dry_start",
            "dry_end",
            "dryer_unload_start",
            "dryer_unload_end",
            "ready_to_fold",
            "fold_start",
            "fold_end",
            "completed_at",
            "weighed_by_employee_id",
            "sorted_by_employee_id",
            "washer_loaded_by_employee_id",
            "transferred_by_employee_id",
            "dryer_loaded_by_employee_id",
            "dryer_unloaded_by_employee_id",
            "folded_by_employee_id",
            "batch_id",
            "batch_sequence",
            "washer_id",
            "dryer_id",
            "folder_employee_id",
        ):
            setattr(bag, field_name, getattr(old, field_name))

        # Clear stages that have not started by T — those will be recalculated.
        for stage, start_key, end_key in STAGE_FIELDS:
            start = getattr(bag, start_key)
            if start is not None and start >= t:
                setattr(bag, start_key, None)
                setattr(bag, end_key, None)
                if stage == "weigh":
                    bag.weighed_by_employee_id = None
                elif stage == "sort":
                    bag.sorted_by_employee_id = None
                elif stage == "washer_load":
                    bag.washer_loaded_by_employee_id = None
                    bag.washer_id = None
                    bag.wash_start = bag.wash_end = None
                    bag.transfer_start = bag.transfer_end = None
                    bag.dryer_load_start = bag.dryer_load_end = None
                    bag.dry_start = bag.dry_end = None
                    bag.ready_to_fold = None
                    bag.dryer_id = None
                elif stage == "fold":
                    bag.fold_start = bag.fold_end = bag.completed_at = None
                    bag.folder_employee_id = bag.folded_by_employee_id = None

        # If wash hasn't started, unlock batch membership for future rebuild unless locked.
        if bag.wash_start is None or bag.wash_start >= t:
            if bag.batch_sequence is not None:
                # Keep membership if batch already started wash before T
                pass
            if bag.washer_load_start is None or bag.washer_load_start >= t:
                bag.batch_id = None
                bag.batch_sequence = None
                bag.available_to_wash = None

    for rid, rows in frozen.employee_calendars.items():
        for res in rows:
            if res.end <= t or res.start < t:
                kept = deepcopy(res)
                kept.provenance = "in_progress_preserved" if res.start < t < res.end else "preserved"
                kept.resource_type = getattr(kept, "resource_type", None) or "employee"
                kept.resource_id = getattr(kept, "resource_id", None) or rid
                if not getattr(kept, "reservation_id", None):
                    kept.reservation_id = f"frozen_{kept.task_id}"
                if kept.start >= t and kept.end > t and not (res.start < t):
                    continue
                if res.start >= t:
                    continue
                emp_cal.install_reservation(rid, kept)

    for rid, rows in frozen.machine_calendars.items():
        for res in rows:
            if res.start >= t:
                continue
            kept = deepcopy(res)
            kept.provenance = "in_progress_preserved" if res.start < t < res.end else "preserved"
            default_type = "dryer_machine" if str(rid).upper().startswith("D") else "washer_machine"
            kept.resource_type = getattr(kept, "resource_type", None) or default_type
            kept.resource_id = getattr(kept, "resource_id", None) or rid
            if not getattr(kept, "reservation_id", None):
                kept.reservation_id = f"frozen_{kept.task_id}"
            machine_cal.install_reservation(rid, kept)

    preserved_batches: list[Batch] = []
    skip: set[str] = set()
    for batch in frozen.batches:
        # Freeze batch if any machine work started before T
        if batch.washer_load_start is not None and batch.washer_load_start < t:
            kept = deepcopy(batch)
            kept.provenance = (
                "in_progress_preserved"
                if (batch.ready_to_fold or 0) > t
                else "preserved"
            )
            preserved_batches.append(kept)
            skip.update(kept.bag_ids)

    meta = ContinuationMeta(
        history_frozen_through=label_minutes(t),
        history_frozen_through_min=t,
        recalculated_from=label_minutes(t),
        recalculated_from_min=t,
        event_queue_starts_at_min=t,
    )
    return bags, preserved_batches, skip, meta
