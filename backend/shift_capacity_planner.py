"""Shift Capacity Planner — discrete-time shift playbook simulator."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Literal

StrategyName = Literal["continuous_washing", "dryer_push"]
TRANSFER_MIN = 5
MILESTONE_CLOCKS = ("8:00 AM", "9:00 AM", "10:00 AM", "11:00 AM", "12:00 PM")

DEFAULTS: dict[str, Any] = {
    "start_time": "7:00 AM",
    "target_time": "12:00 PM",
    "bag_count": 50,
    "avg_lbs_per_bag": 20,
    "washer_count": 4,
    "dryer_count": 4,
    "washer_capacity_lb": 50,
    "dryer_capacity_lb": 50,
    "wash_cycle_min": 30,
    "dry_cycle_min": 45,
    "weigh_min_per_bag": 1,
    "sort_min_per_bag": 5,
    "fold_min_per_bag": 6,
    "folder_count": 3,
    "weigher_count": None,
    "sorter_count": None,
    "transfer_min": TRANSFER_MIN,
    "dryer_push_wash_window_min": 45,
}


def _parse_clock_minutes(raw: Any, *, default: str) -> int:
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        raw = default
    text = str(raw).strip().upper()
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?$", text.replace(".", ""))
    if not m:
        raise ValueError(f"Invalid time: {raw!r}")
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridiem = m.group(3)
    if meridiem == "PM" and hour != 12:
        hour += 12
    elif meridiem == "AM" and hour == 12:
        hour = 0
    if minute >= 60 or hour >= 24:
        raise ValueError(f"Invalid time: {raw!r}")
    return hour * 60 + minute


def _minutes_to_label(minutes: int) -> str:
    h = (minutes // 60) % 24
    m = minutes % 60
    mer = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {mer}"


def _positive_int(value: Any, name: str, *, minimum: int = 1) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if n < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return n


def _positive_float(value: Any, name: str, *, minimum: float = 0.01) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if n < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return n


@dataclass
class PlannerInputs:
    start_min: int
    target_min: int
    bag_count: int
    avg_lbs_per_bag: float
    washer_count: int
    dryer_count: int
    washer_capacity_lb: float
    dryer_capacity_lb: float
    wash_cycle_min: int
    dry_cycle_min: int
    weigh_min_per_bag: float
    sort_min_per_bag: float
    fold_min_per_bag: float
    folder_count: int
    weigher_count: int
    sorter_count: int
    transfer_min: int
    dryer_push_wash_window_min: int

    @property
    def bags_per_wash_load(self) -> int:
        return max(1, int(math.floor(self.washer_capacity_lb / self.avg_lbs_per_bag)))

    @property
    def bags_per_dry_load(self) -> int:
        return max(1, int(math.floor(self.dryer_capacity_lb / self.avg_lbs_per_bag)))

    @property
    def total_wash_loads(self) -> int:
        return int(math.ceil(self.bag_count / self.bags_per_wash_load))


@dataclass
class WashLoad:
    load_id: int
    bags: int
    wash_start: int
    wash_end: int
    dry_start: int | None = None
    dry_end: int | None = None


@dataclass
class SimState:
    minute: int
    weighed: float = 0.0
    sorted_bags: float = 0.0
    folded: float = 0.0
    sort_queue: float = 0.0
    sorted_pool: float = 0.0
    ready_for_fold: float = 0.0
    washer_free_at: list[int] = field(default_factory=list)
    dryer_free_at: list[int] = field(default_factory=list)
    waiting_dryer: list[WashLoad] = field(default_factory=list)
    loads: list[WashLoad] = field(default_factory=list)
    next_load_id: int = 1
    pause_new_wash: bool = False
    weigh_remainder: float = 0.0
    sort_remainder: float = 0.0
    fold_remainder: float = 0.0


def parse_planner_inputs(data: dict[str, Any] | None) -> PlannerInputs:
    raw = {**DEFAULTS, **(data or {})}
    start_min = _parse_clock_minutes(raw.get("start_time"), default=DEFAULTS["start_time"])
    target_min = _parse_clock_minutes(raw.get("target_time"), default=DEFAULTS["target_time"])
    if target_min <= start_min:
        raise ValueError("target_time must be after start_time")

    bag_count = _positive_int(raw.get("bag_count"), "bag_count")
    avg_lbs = _positive_float(raw.get("avg_lbs_per_bag"), "avg_lbs_per_bag")
    washer_count = _positive_int(raw.get("washer_count"), "washer_count")
    dryer_count = _positive_int(raw.get("dryer_count"), "dryer_count")
    washer_cap = _positive_float(raw.get("washer_capacity_lb"), "washer_capacity_lb")
    dryer_cap = _positive_float(raw.get("dryer_capacity_lb"), "dryer_capacity_lb")
    wash_cycle = _positive_int(raw.get("wash_cycle_min"), "wash_cycle_min")
    dry_cycle = _positive_int(raw.get("dry_cycle_min"), "dry_cycle_min")
    weigh_min = _positive_float(raw.get("weigh_min_per_bag"), "weigh_min_per_bag")
    sort_min = _positive_float(raw.get("sort_min_per_bag"), "sort_min_per_bag")
    fold_min = _positive_float(raw.get("fold_min_per_bag"), "fold_min_per_bag")
    folder_count = _positive_int(raw.get("folder_count"), "folder_count", minimum=0)
    transfer_min = _positive_int(raw.get("transfer_min"), "transfer_min", minimum=0)
    push_window = _positive_int(raw.get("dryer_push_wash_window_min"), "dryer_push_wash_window_min")

    window_min = target_min - start_min
    weigher_default = max(1, math.ceil(bag_count * weigh_min / window_min))
    sorter_default = max(1, math.ceil(bag_count * sort_min / window_min))

    weigher_raw = raw.get("weigher_count")
    sorter_raw = raw.get("sorter_count")
    weigher_count = (
        _positive_int(weigher_raw, "weigher_count", minimum=0)
        if weigher_raw is not None and str(weigher_raw).strip() != ""
        else weigher_default
    )
    sorter_count = (
        _positive_int(sorter_raw, "sorter_count", minimum=0)
        if sorter_raw is not None and str(sorter_raw).strip() != ""
        else sorter_default
    )

    return PlannerInputs(
        start_min=start_min,
        target_min=target_min,
        bag_count=bag_count,
        avg_lbs_per_bag=avg_lbs,
        washer_count=washer_count,
        dryer_count=dryer_count,
        washer_capacity_lb=washer_cap,
        dryer_capacity_lb=dryer_cap,
        wash_cycle_min=wash_cycle,
        dry_cycle_min=dry_cycle,
        weigh_min_per_bag=weigh_min,
        sort_min_per_bag=sort_min,
        fold_min_per_bag=fold_min,
        folder_count=folder_count,
        weigher_count=weigher_count,
        sorter_count=sorter_count,
        transfer_min=transfer_min,
        dryer_push_wash_window_min=push_window,
    )


def _init_state(inp: PlannerInputs) -> SimState:
    return SimState(
        minute=inp.start_min,
        washer_free_at=[inp.start_min] * inp.washer_count,
        dryer_free_at=[inp.start_min] * inp.dryer_count,
    )


def _snapshot(state: SimState, inp: PlannerInputs) -> dict[str, Any]:
    waiting_dryer_bags = sum(ld.bags for ld in state.waiting_dryer)
    drying_bags = sum(
        ld.bags
        for ld in state.loads
        if ld.dry_start is not None and ld.dry_end is not None and ld.dry_start <= state.minute < ld.dry_end
    )
    loads_started = len(state.loads)
    loads_wash_done = sum(1 for ld in state.loads if ld.wash_end <= state.minute)
    loads_dry_started = sum(1 for ld in state.loads if ld.dry_start is not None and ld.dry_start <= state.minute)
    loads_dry_done = sum(1 for ld in state.loads if ld.dry_end is not None and ld.dry_end <= state.minute)

    backlogs = {
        "weighing": max(0, inp.bag_count - int(state.weighed)),
        "sorting": max(0, int(state.weighed) - int(state.sorted_bags)),
        "washing": int(state.sorted_pool),
        "waiting_dryer": waiting_dryer_bags,
        "drying": drying_bags,
        "folding": max(0, int(state.ready_for_fold)),
    }
    bottleneck = max(backlogs, key=backlogs.get) if any(backlogs.values()) else "none"

    return {
        "clock": _minutes_to_label(state.minute),
        "minute_offset": state.minute - inp.start_min,
        "bags_weighed": min(inp.bag_count, int(state.weighed)),
        "bags_sorted": min(inp.bag_count, int(state.sorted_bags)),
        "washer_loads_started": loads_started,
        "washer_loads_completed": loads_wash_done,
        "dryer_loads_started": loads_dry_started,
        "dryer_loads_completed": loads_dry_done,
        "bags_ready_for_folding": min(inp.bag_count, int(state.ready_for_fold + state.folded)),
        "bags_folded": min(inp.bag_count, int(state.folded)),
        "bags_waiting_for_dryer": waiting_dryer_bags,
        "bottleneck": bottleneck,
        "backlogs": backlogs,
    }


def _step_weigh_sort(state: SimState, inp: PlannerInputs) -> None:
    if state.weighed < inp.bag_count and inp.weigher_count > 0:
        state.weigh_remainder += inp.weigher_count / inp.weigh_min_per_bag
        take = min(inp.bag_count - state.weighed, state.weigh_remainder)
        if take >= 1:
            whole = int(take)
            state.weigh_remainder -= whole
            state.weighed += whole
            state.sort_queue += whole

    if state.sort_queue > 0 and inp.sorter_count > 0:
        state.sort_remainder += inp.sorter_count / inp.sort_min_per_bag
        take = min(state.sort_queue, state.sort_remainder)
        if take >= 1:
            whole = int(take)
            state.sort_remainder -= whole
            state.sort_queue -= whole
            state.sorted_bags += whole
            state.sorted_pool += whole


def _can_start_wash(state: SimState, inp: PlannerInputs, strategy: StrategyName) -> bool:
    if state.pause_new_wash:
        return False
    if strategy == "dryer_push":
        elapsed = state.minute - inp.start_min
        if elapsed >= inp.dryer_push_wash_window_min and state.waiting_dryer:
            return False
    return True


def _start_wash_loads(state: SimState, inp: PlannerInputs, strategy: StrategyName) -> None:
    if not _can_start_wash(state, inp, strategy):
        if strategy == "dryer_push":
            elapsed = state.minute - inp.start_min
            if elapsed >= inp.dryer_push_wash_window_min and state.waiting_dryer:
                state.pause_new_wash = True
        return

    bags_per_load = inp.bags_per_wash_load
    loads_remaining = inp.total_wash_loads - len(state.loads)

    while loads_remaining > 0 and state.sorted_pool >= bags_per_load:
        slot_idx = min(range(len(state.washer_free_at)), key=lambda i: state.washer_free_at[i])
        free_at = state.washer_free_at[slot_idx]
        if free_at > state.minute:
            break
        bags = min(bags_per_load, int(state.sorted_pool))
        start = max(state.minute, free_at)
        end = start + inp.wash_cycle_min
        load = WashLoad(load_id=state.next_load_id, bags=bags, wash_start=start, wash_end=end)
        state.next_load_id += 1
        state.loads.append(load)
        state.waiting_dryer.append(load)
        state.sorted_pool -= bags
        state.washer_free_at[slot_idx] = end
        loads_remaining -= 1

    # Final partial load when all bags sorted
    if (
        loads_remaining > 0
        and int(state.sorted_bags) >= inp.bag_count
        and state.sorted_pool > 0
        and _can_start_wash(state, inp, strategy)
    ):
        slot_idx = min(range(len(state.washer_free_at)), key=lambda i: state.washer_free_at[i])
        free_at = state.washer_free_at[slot_idx]
        if free_at <= state.minute:
            bags = int(state.sorted_pool)
            start = max(state.minute, free_at)
            end = start + inp.wash_cycle_min
            load = WashLoad(load_id=state.next_load_id, bags=bags, wash_start=start, wash_end=end)
            state.next_load_id += 1
            state.loads.append(load)
            state.waiting_dryer.append(load)
            state.sorted_pool = 0
            state.washer_free_at[slot_idx] = end


def _release_to_dryers(state: SimState, inp: PlannerInputs) -> None:
    ready = [ld for ld in state.waiting_dryer if ld.wash_end + inp.transfer_min <= state.minute]
    ready.sort(key=lambda ld: ld.wash_end)
    for load in ready:
        slot_idx = min(range(len(state.dryer_free_at)), key=lambda i: state.dryer_free_at[i])
        free_at = state.dryer_free_at[slot_idx]
        start = max(state.minute, free_at, load.wash_end + inp.transfer_min)
        end = start + inp.dry_cycle_min
        load.dry_start = start
        load.dry_end = end
        state.waiting_dryer.remove(load)
        state.dryer_free_at[slot_idx] = end


def _release_to_fold(state: SimState, inp: PlannerInputs) -> None:
    for load in state.loads:
        if load.dry_end is not None and load.dry_end == state.minute:
            state.ready_for_fold += load.bags


def _step_fold(state: SimState, inp: PlannerInputs) -> None:
    if state.ready_for_fold <= 0 or inp.folder_count <= 0:
        return
    state.fold_remainder += inp.folder_count / inp.fold_min_per_bag
    take = min(state.ready_for_fold, state.fold_remainder)
    if take >= 1:
        whole = int(take)
        state.fold_remainder -= whole
        state.ready_for_fold -= whole
        state.folded += whole


def _resume_wash(state: SimState, strategy: StrategyName) -> None:
    if strategy == "dryer_push" and state.pause_new_wash and not state.waiting_dryer:
        state.pause_new_wash = False


def run_simulation(inp: PlannerInputs, strategy: StrategyName) -> dict[str, Any]:
    state = _init_state(inp)
    milestone_mins = {_parse_clock_minutes(c, default=c): c for c in MILESTONE_CLOCKS}
    milestones: dict[str, dict[str, Any]] = {}
    max_minute = inp.start_min + (inp.target_min - inp.start_min) + inp.wash_cycle_min + inp.dry_cycle_min + 180
    first_ready_min: int | None = None
    all_ready_min: int | None = None
    all_folded_min: int | None = None
    ready_at: dict[int, int] = {}

    for t in range(inp.start_min, max_minute + 1):
        state.minute = t
        _step_weigh_sort(state, inp)
        _resume_wash(state, strategy)
        _start_wash_loads(state, inp, strategy)
        _release_to_dryers(state, inp)
        _release_to_fold(state, inp)
        _step_fold(state, inp)

        dried_now = sum(ld.bags for ld in state.loads if ld.dry_end is not None and ld.dry_end <= t)
        if first_ready_min is None and dried_now > 0:
            first_ready_min = next(ld.dry_end for ld in sorted(state.loads, key=lambda x: x.dry_end or 10**9) if ld.dry_end)
        if dried_now >= inp.bag_count and all_ready_min is None:
            all_ready_min = t
        if state.folded >= inp.bag_count and all_folded_min is None:
            all_folded_min = t

        if t in milestone_mins:
            snap = _snapshot(state, inp)
            milestones[milestone_mins[t]] = snap
            ready_at[t // 60] = snap["bags_ready_for_folding"]

        if t == inp.target_min:
            milestones.setdefault(_minutes_to_label(t), _snapshot(state, inp))

        if state.folded >= inp.bag_count and t >= inp.target_min:
            break

    final = _snapshot(state, inp)

    return {
        "strategy": strategy,
        "milestones": milestones,
        "final": final,
        "summary": {
            "first_bags_ready": _minutes_to_label(first_ready_min) if first_ready_min else None,
            "first_bags_ready_minute": first_ready_min,
            "ready_by_9_am": milestones.get("9:00 AM", {}).get("bags_ready_for_folding", ready_at.get(9, 0)),
            "ready_by_10_am": milestones.get("10:00 AM", {}).get("bags_ready_for_folding", ready_at.get(10, 0)),
            "all_ready": _minutes_to_label(all_ready_min) if all_ready_min else None,
            "all_folded": _minutes_to_label(all_folded_min) if all_folded_min else None,
            "bottleneck": final["bottleneck"],
            "total_wash_loads": inp.total_wash_loads,
            "bags_per_wash_load": inp.bags_per_wash_load,
        },
        "machine_lanes": _build_machine_lanes(state.loads, inp),
        "playbook": _build_playbook(strategy, inp, milestones, final),
    }


def _build_machine_lanes(loads: list[WashLoad], inp: PlannerInputs, limit: int = 6) -> dict[str, Any]:
    washers = [
        {
            "load_id": ld.load_id,
            "bags": ld.bags,
            "start": _minutes_to_label(ld.wash_start),
            "end": _minutes_to_label(ld.wash_end),
        }
        for ld in loads[:limit]
    ]
    dryers = [
        {
            "load_id": ld.load_id,
            "bags": ld.bags,
            "start": _minutes_to_label(ld.dry_start),
            "end": _minutes_to_label(ld.dry_end) if ld.dry_end else None,
        }
        for ld in loads[:limit]
        if ld.dry_start is not None
    ]
    return {"washers": washers, "dryers": dryers, "bags_per_load": inp.bags_per_wash_load}


def _build_playbook(
    strategy: StrategyName,
    inp: PlannerInputs,
    milestones: dict[str, dict[str, Any]],
    final: dict[str, Any],
) -> list[str]:
    name = "Continuous Washing" if strategy == "continuous_washing" else "Dryer Push"
    lines = [
        f"Shift playbook — {name} ({inp.bag_count} bags from {_minutes_to_label(inp.start_min)}).",
        (
            f"Suggested staffing: {inp.weigher_count} weighers, {inp.sorter_count} sorters, "
            f"{inp.folder_count} folders, {inp.washer_count} washers, {inp.dryer_count} dryers."
        ),
    ]
    order = sorted(
        milestones.keys(),
        key=lambda c: _parse_clock_minutes(c, default="12:00 PM"),
    )
    for clock in order:
        m = milestones[clock]
        lines.append(
            f"By {clock}: weighed {m['bags_weighed']}, sorted {m['bags_sorted']}, "
            f"wash started {m['washer_loads_started']}/done {m['washer_loads_completed']}, "
            f"dry started {m['dryer_loads_started']}/done {m['dryer_loads_completed']}, "
            f"ready to fold {m['bags_ready_for_folding']}, folded {m['bags_folded']} "
            f"(bottleneck: {m['bottleneck']})."
        )
    lines.append(
        f"At target ({_minutes_to_label(inp.target_min)}): "
        f"{final['bags_ready_for_folding']} bags ready, {final['bags_folded']} folded; "
        f"bottleneck remains {final['bottleneck']}."
    )
    if strategy == "dryer_push":
        lines.append(
            f"Dryer Push pauses new washer loads after {inp.dryer_push_wash_window_min} min "
            "until the dryer queue clears."
        )
    return lines


def compute_staffing(inp: PlannerInputs) -> dict[str, Any]:
    window = inp.target_min - inp.start_min
    fold_window = max(60, window // 2)
    suggested_weighers = max(1, math.ceil(inp.bag_count * inp.weigh_min_per_bag / window))
    suggested_sorters = max(1, math.ceil(inp.bag_count * inp.sort_min_per_bag / window))
    suggested_folders = max(1, math.ceil(inp.bag_count * inp.fold_min_per_bag / fold_window))
    helpers = 0
    wash_throughput = inp.washer_count * (window / inp.wash_cycle_min) * inp.bags_per_wash_load
    if inp.bag_count > wash_throughput:
        helpers += 1
    dry_throughput = inp.dryer_count * (window / inp.dry_cycle_min) * inp.bags_per_dry_load
    if inp.bag_count > dry_throughput:
        helpers += 1
    return {
        "weighers": suggested_weighers,
        "sorters": suggested_sorters,
        "folders": suggested_folders,
        "wash_dry_helpers": helpers,
        "using_weighers": inp.weigher_count,
        "using_sorters": inp.sorter_count,
        "using_folders": inp.folder_count,
    }


def recommend_strategy(results: dict[str, dict[str, Any]], inp: PlannerInputs) -> dict[str, Any]:
    cont = results["continuous_washing"]
    push = results["dryer_push"]
    cont_folded = cont["final"]["bags_folded"]
    push_folded = push["final"]["bags_folded"]
    cont_ready = cont["final"]["bags_ready_for_folding"]
    push_ready = push["final"]["bags_ready_for_folding"]

    if push_folded > cont_folded or (push_folded == cont_folded and push_ready > cont_ready):
        pick = "dryer_push"
        reason = "Dryer Push delivers more bags ready or folded by target time."
    else:
        pick = "continuous_washing"
        reason = "Continuous Washing keeps the wash line full with steadier throughput."

    return {
        "recommended": pick,
        "label": "Continuous Washing" if pick == "continuous_washing" else "Dryer Push",
        "reason": reason,
        "comparison": {
            "continuous_washing": {
                "folded": cont_folded,
                "ready": cont_ready,
                "bottleneck": cont["final"]["bottleneck"],
            },
            "dryer_push": {
                "folded": push_folded,
                "ready": push_ready,
                "bottleneck": push["final"]["bottleneck"],
            },
        },
    }


def simulate_shift_capacity(data: dict[str, Any] | None) -> dict[str, Any]:
    inp = parse_planner_inputs(data)
    staffing = compute_staffing(inp)
    strategies = {
        "continuous_washing": run_simulation(inp, "continuous_washing"),
        "dryer_push": run_simulation(inp, "dryer_push"),
    }
    recommendation = recommend_strategy(strategies, inp)
    return {
        "inputs": {
            "start_time": _minutes_to_label(inp.start_min),
            "target_time": _minutes_to_label(inp.target_min),
            "bag_count": inp.bag_count,
            "avg_lbs_per_bag": inp.avg_lbs_per_bag,
            "washer_count": inp.washer_count,
            "dryer_count": inp.dryer_count,
            "washer_capacity_lb": inp.washer_capacity_lb,
            "dryer_capacity_lb": inp.dryer_capacity_lb,
            "wash_cycle_min": inp.wash_cycle_min,
            "dry_cycle_min": inp.dry_cycle_min,
            "weigh_min_per_bag": inp.weigh_min_per_bag,
            "sort_min_per_bag": inp.sort_min_per_bag,
            "fold_min_per_bag": inp.fold_min_per_bag,
            "folder_count": inp.folder_count,
            "weigher_count": inp.weigher_count,
            "sorter_count": inp.sorter_count,
            "bags_per_wash_load": inp.bags_per_wash_load,
            "total_wash_loads": inp.total_wash_loads,
        },
        "staffing": staffing,
        "strategies": strategies,
        "recommendation": recommendation,
    }
