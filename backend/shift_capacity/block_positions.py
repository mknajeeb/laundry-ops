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

    state_counts: dict[str, int] = {
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
        state_counts[bag_state_at(bag, t)] += 1

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
        rows.append(row)
    return rows
