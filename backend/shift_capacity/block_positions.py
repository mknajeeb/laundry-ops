"""Canonical end-of-block workflow positions derived from bag timestamps.

One derivation path only — never a second capacity calculator.
"""

from __future__ import annotations

from typing import Any

from backend.shift_capacity.models import Bag, SimulationState
from backend.shift_capacity.timebase import label_seconds, planning_block_boundaries, sec_to_min_int


def _machine_parts(machine_id: str | None) -> int:
    if not machine_id:
        return 0
    return len([p for p in str(machine_id).split("+") if p])


def parent_wash_complete(bag: Bag, t: int) -> bool:
    """True when the parent has fully finished all required washer child loads by t."""
    if bag.wash_end is None or bag.wash_end > t:
        return False
    need = 2 if bag.requires_two_washers else 1
    return _machine_parts(bag.washer_id) >= need


def parent_dry_complete(bag: Bag, t: int) -> bool:
    """True when the parent has fully finished all required dryer child loads by t.

    DRY DONE ≡ ready_to_fold and every required child load is present. A single
    child finishing must never count as parent Dry DONE / fold-eligible.
    """
    if bag.ready_to_fold is None or bag.ready_to_fold > t:
        return False
    need = 2 if bag.requires_two_dryers else 1
    return _machine_parts(bag.dryer_id) >= need


def bag_state_at(bag: Bag, t: int) -> str:
    """Return the mutually exclusive workflow state of a bag at exact time t."""
    # Labor / cycle intervals are half-open [start, end).
    if bag.completed_at is not None and bag.completed_at <= t:
        return "completed"

    if bag.fold_start is not None and bag.fold_end is not None and bag.fold_start <= t < bag.fold_end:
        return "in_fold_labor"

    # Fold queue only for parents that are fully Dry DONE.
    if parent_dry_complete(bag, t) and (bag.fold_start is None or bag.fold_start > t):
        return "waiting_to_fold"

    ready = bag.ready_to_fold
    # Dry cycle (+ optional unload) occupies until parent dry completion.
    if bag.dryer_load_start is not None and bag.dryer_load_end is not None and bag.dryer_load_start <= t < bag.dryer_load_end:
        return "in_dry_labor"
    if bag.dry_start is not None and ready is not None and bag.dry_start <= t < ready:
        return "in_dry_cycle"
    if bag.dry_start is not None and bag.dry_end is not None and ready is None and bag.dry_start <= t < bag.dry_end:
        return "in_dry_cycle"
    # Incomplete split: child cycle(s) finished but parent still needs another load.
    if (
        bag.dryer_load_start is not None
        and bag.dryer_load_start <= t
        and not parent_dry_complete(bag, t)
        and (bag.requires_two_dryers and _machine_parts(bag.dryer_id) < 2)
    ):
        return "waiting_to_dry"

    # Compat transfer labor (zero-length in management mode).
    if (
        bag.transfer_start is not None
        and bag.transfer_end is not None
        and bag.transfer_start < bag.transfer_end
        and bag.transfer_start <= t < bag.transfer_end
    ):
        return "in_transfer_labor"

    wash_done = parent_wash_complete(bag, t)
    dry_not_started = bag.dryer_load_start is None or bag.dryer_load_start > t
    if wash_done and dry_not_started:
        return "waiting_to_dry"

    if bag.washer_load_start is not None and bag.washer_load_end is not None and bag.washer_load_start <= t < bag.washer_load_end:
        return "in_wash_labor"
    if bag.wash_start is not None and bag.wash_end is not None and bag.wash_start <= t < bag.wash_end:
        return "in_wash_cycle"
    # Incomplete wash split after child cycle(s): still needs remaining wash labor.
    if (
        bag.washer_load_start is not None
        and bag.washer_load_start <= t
        and bag.requires_two_washers
        and _machine_parts(bag.washer_id) < 2
        and not parent_wash_complete(bag, t)
    ):
        return "waiting_to_wash"

    if bag.sort_end is not None and bag.sort_end <= t and (bag.washer_load_start is None or bag.washer_load_start > t):
        return "waiting_to_wash"

    if bag.sort_start is not None and bag.sort_end is not None and bag.sort_start <= t < bag.sort_end:
        return "in_sort_labor"

    if bag.weigh_end is not None and bag.weigh_end <= t and (bag.sort_start is None or bag.sort_start > t):
        return "waiting_to_sort"

    if bag.weigh_start is not None and bag.weigh_end is not None and bag.weigh_start <= t < bag.weigh_end:
        return "in_weigh_labor"

    return "not_yet_weighed"


def _count_completed_between(bags: list[Bag], attr: str, start_exclusive: int, end_inclusive: int) -> int:
    n = 0
    for bag in bags:
        ts = getattr(bag, attr)
        if ts is not None and start_exclusive < ts <= end_inclusive:
            n += 1
    return n


def _count_completed_by(bags: list[Bag], attr: str, t: int) -> int:
    return sum(1 for bag in bags if (getattr(bag, attr) is not None and getattr(bag, attr) <= t))


def _count_parent_wash_between(bags: list[Bag], start_exclusive: int, end_inclusive: int) -> int:
    n = 0
    for bag in bags:
        if bag.wash_end is None:
            continue
        if start_exclusive < bag.wash_end <= end_inclusive and parent_wash_complete(bag, end_inclusive):
            n += 1
    return n


def _count_parent_dry_between(bags: list[Bag], start_exclusive: int, end_inclusive: int) -> int:
    n = 0
    for bag in bags:
        if bag.ready_to_fold is None:
            continue
        if start_exclusive < bag.ready_to_fold <= end_inclusive and parent_dry_complete(bag, end_inclusive):
            n += 1
    return n


def _checkpoint_times(block_start: int, block_end: int) -> list[int]:
    """15-minute marks after start through end (always includes block_end)."""
    step = 15 * 60
    times: list[int] = []
    t = block_start + step
    while t < block_end:
        times.append(t)
        t += step
    times.append(block_end)
    return times


def _state_counts_at(bags: list[Bag], t: int) -> dict[str, int]:
    counts: dict[str, int] = {
        "not_yet_weighed": 0,
        "in_weigh_labor": 0,
        "waiting_to_sort": 0,
        "in_sort_labor": 0,
        "waiting_to_wash": 0,
        "in_wash_labor": 0,
        "in_wash_cycle": 0,
        "in_transfer_labor": 0,
        "waiting_to_dry": 0,
        "in_dry_labor": 0,
        "in_dry_cycle": 0,
        "waiting_to_fold": 0,
        "in_fold_labor": 0,
        "completed": 0,
    }
    for bag in bags:
        counts[bag_state_at(bag, t)] += 1
    return counts


def _wash_started(bag: Bag, t: int) -> bool:
    return bag.washer_load_start is not None and bag.washer_load_start <= t


def _dry_started(bag: Bag, t: int) -> bool:
    return bag.dryer_load_start is not None and bag.dryer_load_start <= t


def _stage_metrics_at(bags: list[Bag], t: int, prev: int) -> dict[str, dict[str, Any]]:
    """Canonical per-stage snapshot at checkpoint t (prev → t interval).

    this_15_min: completed S in (prev, t]
    total_done: completed S by t
    waiting_next: completed S, next stage not started
    in_process: started S, not completed S
    """
    counts = _state_counts_at(bags, t)

    weigh_done = _count_completed_by(bags, "weigh_end", t)
    sort_done = _count_completed_by(bags, "sort_end", t)
    wash_done = sum(1 for b in bags if parent_wash_complete(b, t))
    dry_done = sum(1 for b in bags if parent_dry_complete(b, t))
    fold_done = _count_completed_by(bags, "completed_at", t)

    # Waiting→next: completed this stage, next not started (never upstream bags).
    weigh_waiting_next = sum(
        1
        for b in bags
        if b.weigh_end is not None
        and b.weigh_end <= t
        and (b.sort_start is None or b.sort_start > t)
    )
    sort_waiting_next = sum(
        1
        for b in bags
        if b.sort_end is not None
        and b.sort_end <= t
        and (b.washer_load_start is None or b.washer_load_start > t)
    )
    wash_waiting_next = sum(
        1
        for b in bags
        if parent_wash_complete(b, t) and not _dry_started(b, t)
    )
    dry_waiting_next = sum(
        1
        for b in bags
        if parent_dry_complete(b, t) and (b.fold_start is None or b.fold_start > t)
    )

    wash_in_process = sum(
        1
        for b in bags
        if _wash_started(b, t) and not parent_wash_complete(b, t)
    )
    dry_in_process = sum(
        1
        for b in bags
        if _dry_started(b, t) and not parent_dry_complete(b, t)
    )

    return {
        "weigh": {
            "id": "weigh",
            "title": "WEIGH",
            "this_15_min": _count_completed_between(bags, "weigh_end", prev, t),
            "total_done": weigh_done,
            "waiting_next": weigh_waiting_next,
            "waiting_next_label": "Sort",
            "in_process": counts["in_weigh_labor"],
            "is_terminal": False,
        },
        "sort": {
            "id": "sort",
            "title": "SORT",
            "this_15_min": _count_completed_between(bags, "sort_end", prev, t),
            "total_done": sort_done,
            "waiting_next": sort_waiting_next,
            "waiting_next_label": "Wash",
            "in_process": counts["in_sort_labor"],
            "is_terminal": False,
        },
        "wash": {
            "id": "wash",
            "title": "WASH",
            "this_15_min": _count_parent_wash_between(bags, prev, t),
            "total_done": wash_done,
            "waiting_next": wash_waiting_next,
            "waiting_next_label": "Dry",
            "in_process": wash_in_process,
            "in_labor": counts["in_wash_labor"],
            "in_cycle": counts["in_wash_cycle"],
            "is_terminal": False,
        },
        "dry": {
            "id": "dry",
            "title": "DRY",
            "this_15_min": _count_parent_dry_between(bags, prev, t),
            "total_done": dry_done,
            "waiting_next": dry_waiting_next,
            "waiting_next_label": "Fold",
            "in_process": dry_in_process,
            "in_labor": counts["in_dry_labor"],
            "in_cycle": counts["in_dry_cycle"],
            "is_terminal": False,
        },
        "fold": {
            "id": "fold",
            "title": "FOLD",
            "this_15_min": _count_completed_between(bags, "completed_at", prev, t),
            "total_done": fold_done,
            "waiting_next": 0,
            "waiting_next_label": None,
            "in_process": counts["in_fold_labor"],
            "is_terminal": True,
            "terminal_completed": fold_done,
        },
    }


def build_availability_checkpoints(
    bags: list[Bag],
    *,
    block_start: int,
    block_end: int,
    target_bags: int | None = None,
) -> list[dict[str, Any]]:
    """15-min operational checkpoints with per-stage this/total/waiting/in-process.

    Also keeps legacy waiting/total keys for older consumers.
    """
    times = _checkpoint_times(block_start, block_end)
    target = target_bags if target_bags is not None else len(bags)
    rows: list[dict[str, Any]] = []
    prev = block_start
    for t in times:
        counts = _state_counts_at(bags, t)
        stages = _stage_metrics_at(bags, t, prev)
        exclusive_sum = sum(counts.values())
        rows.append(
            {
                "time": label_seconds(t),
                "time_sec": t,
                "stages": stages,
                "stage_list": [stages[k] for k in ("weigh", "sort", "wash", "dry", "fold")],
                "weighed_total": stages["weigh"]["total_done"],
                "sorted_total": stages["sort"]["total_done"],
                "washed_total": stages["wash"]["total_done"],
                "dried_total": stages["dry"]["total_done"],
                "folded_total": stages["fold"]["total_done"],
                "weighed_this_15": stages["weigh"]["this_15_min"],
                "sorted_this_15": stages["sort"]["this_15_min"],
                "washed_this_15": stages["wash"]["this_15_min"],
                "dried_this_15": stages["dry"]["this_15_min"],
                "folded_this_15": stages["fold"]["this_15_min"],
                "not_yet_weighed": counts["not_yet_weighed"],
                "waiting_to_weigh": counts["not_yet_weighed"],
                "available_to_sort": counts["waiting_to_sort"],
                "waiting_to_sort": counts["waiting_to_sort"],
                "newly_available_to_sort": _count_completed_between(bags, "weigh_end", prev, t),
                "available_to_wash": counts["waiting_to_wash"],
                "waiting_to_wash": counts["waiting_to_wash"],
                "newly_available_to_wash": _count_completed_between(bags, "sort_end", prev, t),
                "available_to_dry": counts["waiting_to_dry"],
                "waiting_to_dry": counts["waiting_to_dry"],
                "newly_available_to_dry": _count_parent_wash_between(bags, prev, t),
                "available_to_fold": counts["waiting_to_fold"],
                "waiting_to_fold": counts["waiting_to_fold"],
                "newly_available_to_fold": _count_parent_dry_between(bags, prev, t),
                "in_weigh_labor": counts["in_weigh_labor"],
                "in_sort_labor": counts["in_sort_labor"],
                "in_wash_labor": counts["in_wash_labor"],
                "in_wash_cycle": counts["in_wash_cycle"],
                "in_dry_labor": counts["in_dry_labor"],
                "in_dry_cycle": counts["in_dry_cycle"],
                "in_fold_labor": counts["in_fold_labor"],
                "reconciliation": {
                    "exclusive_state_sum": exclusive_sum,
                    "target_bags": target,
                    "ok": exclusive_sum == target,
                    "states": counts,
                },
            }
        )
        prev = t
    return rows


def position_at(bags: list[Bag], t: int, *, prev_t: int | None = None, target_bags: int | None = None) -> dict[str, Any]:
    prev = prev_t if prev_t is not None else t
    target = target_bags if target_bags is not None else len(bags)

    # WASHED / DRIED are parent-complete only (all required child loads finished).
    this_block = {
        "weighed_this_block": _count_completed_between(bags, "weigh_end", prev, t),
        "sorted_this_block": _count_completed_between(bags, "sort_end", prev, t),
        "washed_this_block": _count_parent_wash_between(bags, prev, t),
        "dried_this_block": _count_parent_dry_between(bags, prev, t),
        "folded_this_block": _count_completed_between(bags, "completed_at", prev, t),
    }
    totals = {
        "weighed_total": _count_completed_by(bags, "weigh_end", t),
        "sorted_total": _count_completed_by(bags, "sort_end", t),
        "washed_total": sum(1 for b in bags if parent_wash_complete(b, t)),
        "dried_total": sum(1 for b in bags if parent_dry_complete(b, t)),
        "folded_total": _count_completed_by(bags, "completed_at", t),
    }

    state_counts = _state_counts_at(bags, t)

    waiting = {
        "waiting_to_sort": state_counts["waiting_to_sort"],
        "waiting_to_wash": state_counts["waiting_to_wash"],
        "waiting_to_dry": state_counts["waiting_to_dry"],
        "waiting_to_fold": state_counts["waiting_to_fold"],
    }
    detail = {
        "not_yet_weighed": state_counts["not_yet_weighed"],
        "in_weigh_labor": state_counts["in_weigh_labor"],
        "in_sort_labor": state_counts["in_sort_labor"],
        "in_wash_labor": state_counts["in_wash_labor"],
        "in_wash_cycle": state_counts["in_wash_cycle"],
        "in_transfer_labor": state_counts["in_transfer_labor"],
        "in_dry_labor": state_counts["in_dry_labor"],
        "in_dry_cycle": state_counts["in_dry_cycle"],
        "in_fold_labor": state_counts["in_fold_labor"],
        "completed": state_counts["completed"],
    }

    exclusive_sum = sum(state_counts.values())
    return {
        "time": label_seconds(t),
        "time_sec": t,
        "time_min": sec_to_min_int(t),
        "prev_time": label_seconds(prev),
        "prev_time_sec": prev,
        "target_bags": target,
        "this_block": this_block,
        "totals": totals,
        "waiting": waiting,
        "detail": detail,
        "reconciliation": {
            "exclusive_state_sum": exclusive_sum,
            "target_bags": target,
            "ok": exclusive_sum == target,
            "states": state_counts,
        },
        # Flat convenience keys for management UI / tests
        **this_block,
        **totals,
        **waiting,
        **detail,
    }


def build_block_positions(state: SimulationState) -> list[dict[str, Any]]:
    start = state.inputs.shift.start_min
    target = state.inputs.shift.target_min
    block_min = state.inputs.shift.planning_block_size_min or state.inputs.shift.summary_interval_min or 60
    bounds = planning_block_boundaries(start, target, block_min)
    bags = state.bags
    target_bags = state.inputs.shift.bag_count or len(bags)
    rows: list[dict[str, Any]] = []
    for i in range(1, len(bounds)):
        block_start = bounds[i - 1]
        block_end = bounds[i]
        row = position_at(bags, block_end, prev_t=block_start, target_bags=target_bags)
        row["block_index"] = i
        row["block_start"] = label_seconds(block_start)
        row["block_start_sec"] = block_start
        row["block_end"] = label_seconds(block_end)
        row["block_end_sec"] = block_end
        row["block_duration_min"] = round((block_end - block_start) / 60.0, 4)
        row["is_short_final_block"] = (block_end - block_start) < (block_min * 60) and block_end == target
        row["availability_checkpoints"] = build_availability_checkpoints(
            bags, block_start=block_start, block_end=block_end, target_bags=target_bags
        )
        rows.append(row)
    return rows
