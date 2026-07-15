"""All KPIs and summaries are derived from bag records."""

from __future__ import annotations

from typing import Any

from backend.shift_capacity.models import Bag, Batch, Employee, SimulationInputs, SimulationState
from backend.shift_capacity.resources import role_active_at
from backend.shift_capacity.validation import label_minutes


def compute_kpis(state: SimulationState) -> dict[str, Any]:
    bags = state.bags
    batches = state.batches
    target = state.inputs.shift.target_min
    start = state.inputs.shift.start_min

    ready = [b for b in bags if b.ready_to_fold is not None]
    folded = [b for b in bags if b.completed_at is not None]

    bags_ready = sum(1 for b in ready if b.ready_to_fold <= target)
    bags_folded = sum(1 for b in folded if b.completed_at <= target)
    lbs_ready = round(sum(b.weight_lb for b in ready if b.ready_to_fold <= target), 2)
    lbs_folded = round(sum(b.weight_lb for b in folded if b.completed_at <= target), 2)

    first_ready = min((b.ready_to_fold for b in ready), default=None)
    last_ready = max((b.ready_to_fold for b in ready), default=None)
    final_complete = max((b.completed_at for b in folded), default=None)

    backlog_series = _fold_backlog_series(bags, start, max(target, final_complete or target))
    max_backlog = max((n for _, n in backlog_series), default=0)
    max_backlog_time = next((t for t, n in backlog_series if n == max_backlog), None) if backlog_series else None

    def avg(vals: list[int | None]) -> float:
        clean = [v for v in vals if v is not None]
        return round(sum(clean) / len(clean), 1) if clean else 0.0

    window_end = max(final_complete or target, target)
    washer_util = _machine_util(state, "W", start, window_end)
    dryer_util = _machine_util(state, "D", start, window_end)
    washer_person_util = _role_util(state, "washer", start, window_end)
    sorter_util = _role_util(state, "sorter", start, window_end)
    folder_util = _role_util(state, "folder", start, window_end)

    candidates = [
        (washer_util, "Washer machines"),
        (dryer_util, "Dryer machines"),
        (washer_person_util, "Washer persons"),
        (sorter_util, "Sorters"),
        (folder_util, "Folders"),
    ]
    candidates.sort(reverse=True)
    primary = candidates[0][1] if candidates and candidates[0][0] > 0 else "none"
    secondary = candidates[1][1] if len(candidates) > 1 else "none"

    return {
        "bags_ready_by_target": bags_ready,
        "pounds_ready_by_target": lbs_ready,
        "bags_folded_by_target": bags_folded,
        "pounds_folded_by_target": lbs_folded,
        "first_bag_ready_time": label_minutes(first_ready),
        "first_batch_ready_time": label_minutes(batches[0].ready_to_fold) if batches else None,
        "last_batch_ready_time": label_minutes(batches[-1].ready_to_fold) if batches else None,
        "last_bag_ready_time": label_minutes(last_ready),
        "final_completion_time": label_minutes(final_complete),
        "maximum_fold_backlog": max_backlog,
        "time_of_maximum_backlog": label_minutes(max_backlog_time),
        "average_bag_wait_for_washer": avg([b.wait_for_washer_minutes for b in bags]),
        "average_bag_wait_for_dryer": avg([b.wait_for_dryer_minutes for b in bags]),
        "average_bag_wait_for_folder": avg([b.wait_for_folder_minutes for b in bags]),
        "washer_machine_utilization_pct": washer_util,
        "dryer_machine_utilization_pct": dryer_util,
        "washer_person_utilization_pct": washer_person_util,
        "sorter_utilization_pct": sorter_util,
        "folder_utilization_pct": folder_util,
        # Compat aliases used by existing UI
        "washer_utilization_pct": washer_util,
        "dryer_utilization_pct": dryer_util,
        "folder_utilization": folder_util,
        "primary_bottleneck": primary,
        "secondary_bottleneck": secondary,
        "avg_ready_wait_min": avg([b.wait_for_folder_minutes for b in bags]),
    }


def ready_by_batch(state: SimulationState) -> list[dict[str, Any]]:
    rows = []
    cum_bags = 0
    cum_lbs = 0.0
    for batch in state.batches:
        cum_bags += batch.total_bags
        cum_lbs += batch.total_weight_lb
        rows.append(
            {
                "batch_number": batch.sequence,
                "batch_id": batch.batch_id,
                "bags": batch.total_bags,
                "pounds": batch.total_weight_lb,
                "washer_id": batch.washer_id,
                "dryer_id": batch.dryer_id,
                "wash_start": label_minutes(batch.wash_start),
                "ready_to_fold": label_minutes(batch.ready_to_fold),
                "ready_to_fold_min": batch.ready_to_fold,
                "cumulative_bags_ready": cum_bags,
                "cumulative_pounds_ready": round(cum_lbs, 2),
                "bag_ids": list(batch.bag_ids),
                "order_numbers": list(batch.order_ids),
                "order_ids": list(batch.order_ids),
                "locked": batch.locked,
                "provenance": batch.provenance,
            }
        )
    return rows


def time_summary(state: SimulationState, interval_min: int | None = None) -> list[dict[str, Any]]:
    interval = interval_min or state.inputs.shift.summary_interval_min or 30
    bags = state.bags
    start = state.inputs.shift.start_min
    end = max(
        [state.inputs.shift.target_min]
        + [b.completed_at or 0 for b in bags]
        + [b.ready_to_fold or 0 for b in bags]
    )
    t = (start // interval) * interval
    rows = []
    while t <= end:
        rows.append(_interval_row(bags, state.inputs.employees, t))
        t += interval
    return rows


def staffing_summary(state: SimulationState) -> list[dict[str, Any]]:
    employees = state.inputs.employees
    times = sorted(
        {
            state.inputs.shift.start_min,
            state.inputs.shift.target_min,
            *[e.start_min() for e in employees],
            *[e.end_min() for e in employees if e.end_min() is not None],
            *[rw.start_min for e in employees for rw in e.role_windows],
            *[rw.end_min for e in employees for rw in e.role_windows],
        }
    )
    rows = []
    for t in times:
        switches = []
        for emp in employees:
            for rw in emp.role_windows:
                if rw.start_min == t:
                    switches.append(f"{emp.display_name} → {rw.role}")
                if rw.end_min == t:
                    switches.append(f"{emp.display_name} leaves {rw.role}")
        rows.append(
            {
                "time": label_minutes(t),
                "time_min": t,
                "active_weighers": sum(1 for e in employees if role_active_at(e, "weigher", t)),
                "active_sorters": sum(1 for e in employees if role_active_at(e, "sorter", t)),
                "active_washer_persons": sum(1 for e in employees if role_active_at(e, "washer", t)),
                "active_folders": sum(1 for e in employees if role_active_at(e, "folder", t)),
                # Compat keys
                "weighers": sum(1 for e in employees if role_active_at(e, "weigher", t)),
                "sorters": sum(1 for e in employees if role_active_at(e, "sorter", t)),
                "washer_persons": sum(1 for e in employees if role_active_at(e, "washer", t)),
                "folders": sum(1 for e in employees if role_active_at(e, "folder", t)),
                "role_switches": switches,
            }
        )
    return rows


def _interval_row(bags: list[Bag], employees: list[Employee], t: int) -> dict[str, Any]:
    def count(pred) -> int:
        return sum(1 for b in bags if pred(b))

    ready_n = count(lambda b: b.ready_to_fold is not None and b.ready_to_fold <= t)
    folded_n = count(lambda b: b.completed_at is not None and b.completed_at <= t)
    ready_lbs = round(sum(b.weight_lb for b in bags if b.ready_to_fold is not None and b.ready_to_fold <= t), 2)
    folded_lbs = round(sum(b.weight_lb for b in bags if b.completed_at is not None and b.completed_at <= t), 2)

    return {
        "time": label_minutes(t),
        "time_min": t,
        "entered": count(lambda b: b.entry_time is not None and b.entry_time <= t),
        "weighed": count(lambda b: b.weigh_end is not None and b.weigh_end <= t),
        "sorted": count(lambda b: b.sort_end is not None and b.sort_end <= t),
        "waiting_to_wash": count(
            lambda b: b.sort_end is not None
            and b.sort_end <= t
            and (b.washer_load_start is None or b.washer_load_start > t)
        ),
        "washer_loading": count(
            lambda b: b.washer_load_start is not None
            and b.washer_load_end is not None
            and b.washer_load_start <= t < b.washer_load_end
        ),
        "in_wash": count(
            lambda b: b.wash_start is not None and b.wash_end is not None and b.wash_start <= t < b.wash_end
        ),
        "waiting_for_dryer": count(
            lambda b: b.wash_end is not None
            and b.wash_end <= t
            and (b.dryer_load_start is None or b.dryer_load_start > t)
        ),
        "dryer_loading": count(
            lambda b: b.dryer_load_start is not None
            and b.dryer_load_end is not None
            and b.dryer_load_start <= t < b.dryer_load_end
        ),
        "in_dryer": count(
            lambda b: b.dry_start is not None and b.dry_end is not None and b.dry_start <= t < b.dry_end
        ),
        "ready_to_fold": ready_n,
        "folding": count(
            lambda b: b.fold_start is not None and b.fold_end is not None and b.fold_start <= t < b.fold_end
        ),
        "folded": folded_n,
        "fold_backlog": count(
            lambda b: b.ready_to_fold is not None
            and b.ready_to_fold <= t
            and (b.fold_start is None or b.fold_start > t)
        ),
        "cumulative_bags_ready": ready_n,
        "cumulative_pounds_ready": ready_lbs,
        "cumulative_bags_folded": folded_n,
        "cumulative_pounds_folded": folded_lbs,
        # Compat aliases
        "bags_ready": ready_n,
        "bags_folded": folded_n,
        "pounds_ready": ready_lbs,
        "pounds_folded": folded_lbs,
        "active_weighers": sum(1 for e in employees if role_active_at(e, "weigher", t)),
        "active_sorters": sum(1 for e in employees if role_active_at(e, "sorter", t)),
        "active_washer_persons": sum(1 for e in employees if role_active_at(e, "washer", t)),
        "active_folders": sum(1 for e in employees if role_active_at(e, "folder", t)),
    }


def _fold_backlog_series(bags: list[Bag], start: int, end: int) -> list[tuple[int, int]]:
    points = sorted(
        {
            start,
            end,
            *[b.ready_to_fold for b in bags if b.ready_to_fold is not None],
            *[b.fold_start for b in bags if b.fold_start is not None],
        }
    )
    series = []
    for t in points:
        n = sum(
            1
            for b in bags
            if b.ready_to_fold is not None and b.ready_to_fold <= t and (b.fold_start is None or b.fold_start > t)
        )
        series.append((t, n))
    return series


def _util_from_intervals(intervals: list[tuple[int, int]], start: int, end: int) -> float:
    if end <= start:
        return 0.0
    busy = 0
    for a, b in intervals:
        lo = max(a, start)
        hi = min(b, end)
        if hi > lo:
            busy += hi - lo
    return round(100.0 * busy / (end - start), 1)


def _machine_util(state: SimulationState, prefix: str, start: int, end: int) -> float:
    vals = []
    for rid, rows in state.machine_calendars.items():
        if not rid.startswith(prefix):
            continue
        vals.append(_util_from_intervals([(r.start, r.end) for r in rows], start, end))
    return round(sum(vals) / len(vals), 1) if vals else 0.0


def _role_util(state: SimulationState, role: str, start: int, end: int) -> float:
    emp_ids = {
        e.employee_id
        for e in state.inputs.employees
        if e.primary_role == role or role in [r.lower() for r in e.qualified_roles]
    }
    vals = []
    for rid, rows in state.employee_calendars.items():
        if rid not in emp_ids:
            continue
        vals.append(_util_from_intervals([(r.start, r.end) for r in rows], start, end))
    return round(sum(vals) / len(vals), 1) if vals else 0.0
