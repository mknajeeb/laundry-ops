"""Shift Capacity Planner — discrete-time shift simulator with bag-mix load sizing."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Literal

StrategyName = Literal["continuous_washing", "dryer_push"]
WeighingHandledBy = Literal["dedicated_weigher", "sorter", "washer"]
TRANSFER_MIN = 5
MILESTONE_CLOCKS = ("8:00 AM", "9:00 AM", "10:00 AM", "11:00 AM", "12:00 PM")

DEFAULTS: dict[str, Any] = {
    "start_time": "7:00 AM",
    "target_time": "12:00 PM",
    "bag_count": 50,
    "avg_lbs_per_bag": 20,
    "small_bag_pct": 40,
    "medium_bag_pct": 40,
    "large_bag_pct": 20,
    "small_bag_lb": 20,
    "medium_bag_lb": 30,
    "large_bag_lb": 50,
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
    "weighing_handled_by": "dedicated_weigher",
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


def _non_negative_int(value: Any, name: str) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if n < 0:
        raise ValueError(f"{name} must be >= 0")
    return n


def _positive_float(value: Any, name: str, *, minimum: float = 0.01) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if n < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return n


def _non_negative_float(value: Any, name: str) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if n < 0:
        raise ValueError(f"{name} must be >= 0")
    return n


def _parse_weighing_handled_by(raw: Any) -> WeighingHandledBy:
    value = str(raw or DEFAULTS["weighing_handled_by"]).strip().lower()
    aliases = {
        "dedicated": "dedicated_weigher",
        "dedicated_weigher": "dedicated_weigher",
        "weigher": "dedicated_weigher",
        "sorter": "sorter",
        "washer": "washer",
    }
    if value not in aliases:
        raise ValueError(
            "weighing_handled_by must be one of: dedicated_weigher, sorter, washer"
        )
    return aliases[value]  # type: ignore[return-value]


def build_bag_weight_list(
    bag_count: int,
    *,
    small_pct: float,
    medium_pct: float,
    large_pct: float,
    small_lb: float,
    medium_lb: float,
    large_lb: float,
) -> list[float]:
    total_pct = small_pct + medium_pct + large_pct
    if total_pct <= 0:
        raise ValueError("bag size mix percentages must sum to a positive value")
    small_pct /= total_pct
    medium_pct /= total_pct
    large_pct /= total_pct

    small_n = int(round(bag_count * small_pct))
    medium_n = int(round(bag_count * medium_pct))
    large_n = bag_count - small_n - medium_n
    if large_n < 0:
        large_n = 0
        medium_n = bag_count - small_n

    weights = [small_lb] * small_n + [medium_lb] * medium_n + [large_lb] * large_n
    while len(weights) < bag_count:
        weights.append(medium_lb)
    return weights[:bag_count]


def pack_load_from_pool(pool: list[float], capacity_lb: float) -> tuple[list[float], list[float]]:
    if not pool:
        return [], []
    load: list[float] = []
    total = 0.0
    idx = 0
    while idx < len(pool):
        w = pool[idx]
        if not load and w > capacity_lb:
            load = [w]
            idx += 1
            break
        if total + w <= capacity_lb + 1e-9:
            load.append(w)
            total += w
            idx += 1
        else:
            break
    if not load:
        load = [pool[0]]
        idx = 1
    return load, pool[idx:]


@dataclass
class PlannerInputs:
    start_min: int
    target_min: int
    bag_count: int
    avg_lbs_per_bag: float
    bag_weights: list[float]
    small_bag_pct: float
    medium_bag_pct: float
    large_bag_pct: float
    small_bag_lb: float
    medium_bag_lb: float
    large_bag_lb: float
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
    weighing_handled_by: WeighingHandledBy
    transfer_min: int
    dryer_push_wash_window_min: int

    @property
    def effective_sort_min_per_bag(self) -> float:
        if self.weighing_handled_by == "sorter":
            return self.sort_min_per_bag + self.weigh_min_per_bag
        return self.sort_min_per_bag

    @property
    def uses_dedicated_weigher(self) -> bool:
        return self.weighing_handled_by == "dedicated_weigher"

    @property
    def uses_washer_weighing(self) -> bool:
        return self.weighing_handled_by == "washer"

    def estimate_wash_loads(self) -> list[dict[str, Any]]:
        pool = list(self.bag_weights)
        loads: list[dict[str, Any]] = []
        bag_idx = 1
        while pool:
            chunk, pool = pack_load_from_pool(pool, self.washer_capacity_lb)
            loads.append(
                {
                    "bags": len(chunk),
                    "pounds": round(sum(chunk), 1),
                    "bag_start": bag_idx,
                    "bag_end": bag_idx + len(chunk) - 1,
                }
            )
            bag_idx += len(chunk)
        return loads

    @property
    def total_wash_loads(self) -> int:
        return len(self.estimate_wash_loads())

    @property
    def avg_bags_per_wash_load(self) -> float:
        loads = self.estimate_wash_loads()
        if not loads:
            return 0.0
        return sum(ld["bags"] for ld in loads) / len(loads)


@dataclass
class WashLoad:
    load_id: int
    washer_id: int
    bag_start: int
    bag_end: int
    bags: int
    pounds: float
    wash_start: int
    wash_end: int
    dry_start: int | None = None
    dry_end: int | None = None
    dryer_id: int | None = None


@dataclass
class SimState:
    minute: int
    weighed_count: int = 0
    sorted_count: int = 0
    next_bag_index: int = 1
    folded: float = 0.0
    incoming_bags: list[float] = field(default_factory=list)
    weigh_queue: list[float] = field(default_factory=list)
    sort_queue: list[float] = field(default_factory=list)
    sorted_pool: list[tuple[int, float]] = field(default_factory=list)
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
    small_pct = _non_negative_float(raw.get("small_bag_pct"), "small_bag_pct")
    medium_pct = _non_negative_float(raw.get("medium_bag_pct"), "medium_bag_pct")
    large_pct = _non_negative_float(raw.get("large_bag_pct"), "large_bag_pct")
    small_lb = _positive_float(raw.get("small_bag_lb"), "small_bag_lb")
    medium_lb = _positive_float(raw.get("medium_bag_lb"), "medium_bag_lb")
    large_lb = _positive_float(raw.get("large_bag_lb"), "large_bag_lb")

    bag_weights = build_bag_weight_list(
        bag_count,
        small_pct=small_pct,
        medium_pct=medium_pct,
        large_pct=large_pct,
        small_lb=small_lb,
        medium_lb=medium_lb,
        large_lb=large_lb,
    )

    washer_count = _positive_int(raw.get("washer_count"), "washer_count")
    dryer_count = _positive_int(raw.get("dryer_count"), "dryer_count")
    washer_cap = _positive_float(raw.get("washer_capacity_lb"), "washer_capacity_lb")
    dryer_cap = _positive_float(raw.get("dryer_capacity_lb"), "dryer_capacity_lb")
    wash_cycle = _positive_int(raw.get("wash_cycle_min"), "wash_cycle_min")
    dry_cycle = _positive_int(raw.get("dry_cycle_min"), "dry_cycle_min")
    weigh_min = _positive_float(raw.get("weigh_min_per_bag"), "weigh_min_per_bag")
    sort_min = _positive_float(raw.get("sort_min_per_bag"), "sort_min_per_bag")
    fold_min = _positive_float(raw.get("fold_min_per_bag"), "fold_min_per_bag")
    folder_count = _non_negative_int(raw.get("folder_count"), "folder_count")
    transfer_min = _non_negative_int(raw.get("transfer_min"), "transfer_min")
    push_window = _positive_int(raw.get("dryer_push_wash_window_min"), "dryer_push_wash_window_min")
    weighing_handled_by = _parse_weighing_handled_by(raw.get("weighing_handled_by"))

    window_min = target_min - start_min
    weigher_default = max(1, math.ceil(bag_count * weigh_min / window_min)) if weighing_handled_by == "dedicated_weigher" else 0
    sort_rate = sort_min + weigh_min if weighing_handled_by == "sorter" else sort_min
    sorter_default = max(1, math.ceil(bag_count * sort_rate / window_min))

    weigher_raw = raw.get("weigher_count")
    sorter_raw = raw.get("sorter_count")
    weigher_count = (
        _non_negative_int(weigher_raw, "weigher_count")
        if weigher_raw is not None and str(weigher_raw).strip() != ""
        else weigher_default
    )
    sorter_count = (
        _non_negative_int(sorter_raw, "sorter_count")
        if sorter_raw is not None and str(sorter_raw).strip() != ""
        else sorter_default
    )

    if weighing_handled_by != "dedicated_weigher":
        weigher_count = 0

    return PlannerInputs(
        start_min=start_min,
        target_min=target_min,
        bag_count=bag_count,
        avg_lbs_per_bag=avg_lbs,
        bag_weights=bag_weights,
        small_bag_pct=small_pct,
        medium_bag_pct=medium_pct,
        large_bag_pct=large_pct,
        small_bag_lb=small_lb,
        medium_bag_lb=medium_lb,
        large_bag_lb=large_lb,
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
        weighing_handled_by=weighing_handled_by,
        transfer_min=transfer_min,
        dryer_push_wash_window_min=push_window,
    )


def _init_state(inp: PlannerInputs) -> SimState:
    state = SimState(
        minute=inp.start_min,
        incoming_bags=list(inp.bag_weights),
        washer_free_at=[inp.start_min] * inp.washer_count,
        dryer_free_at=[inp.start_min] * inp.dryer_count,
    )
    if inp.uses_dedicated_weigher:
        state.weigh_queue = []
    else:
        state.sort_queue = list(inp.bag_weights)
        state.incoming_bags = []
    return state


def _bags_in_washer(state: SimState) -> int:
    return sum(
        ld.bags
        for ld in state.loads
        if ld.wash_start <= state.minute < ld.wash_end
    )


def _bags_washed_waiting(state: SimState) -> int:
    return sum(ld.bags for ld in state.waiting_dryer)


def _bags_in_dryer(state: SimState) -> int:
    return sum(
        ld.bags
        for ld in state.loads
        if ld.dry_start is not None and ld.dry_end is not None and ld.dry_start <= state.minute < ld.dry_end
    )


def _bags_dried_complete(state: SimState) -> int:
    dried = sum(
        ld.bags
        for ld in state.loads
        if ld.dry_end is not None and ld.dry_end <= state.minute
    )
    return dried


def _action_for_bottleneck(bottleneck: str, backlogs: dict[str, int]) -> str:
    actions = {
        "weighing": "Weighing behind — add weigher or shift weighing to sorter/washer",
        "sorting": "Sorter behind — add helper",
        "washing": "Washers idle — feed sorted bags faster",
        "waiting_dryer": "Dryers waiting — prioritize washer-to-dryer transfers",
        "drying": "Drying backlog — add dryer or extend dry window",
        "folding": "Folding behind — add folders",
        "none": "On track",
    }
    if bottleneck == "none":
        return actions["none"]
    backlog = backlogs.get(bottleneck, 0)
    if backlog <= 0:
        return "On track"
    return actions.get(bottleneck, "Review staffing")


def _snapshot(state: SimState, inp: PlannerInputs) -> dict[str, Any]:
    in_washer = _bags_in_washer(state)
    washed_waiting = _bags_washed_waiting(state)
    in_dryer = _bags_in_dryer(state)
    dried_complete = _bags_dried_complete(state)
    ready_fold = int(state.ready_for_fold + state.folded)

    weighed_backlog = len(state.incoming_bags) + len(state.weigh_queue)
    if inp.weighing_handled_by == "washer":
        weighed_backlog = max(0, inp.bag_count - state.weighed_count)

    backlogs = {
        "weighing": weighed_backlog,
        "sorting": len(state.sort_queue),
        "washing": len(state.sorted_pool),
        "waiting_dryer": washed_waiting,
        "drying": in_dryer,
        "folding": max(0, int(state.ready_for_fold)),
    }
    bottleneck = max(backlogs, key=backlogs.get) if any(backlogs.values()) else "none"

    return {
        "clock": _minutes_to_label(state.minute),
        "minute_offset": state.minute - inp.start_min,
        "bags_weighed": state.weighed_count,
        "bags_sorted": state.sorted_count,
        "bags_in_washer": in_washer,
        "bags_washed_complete": sum(ld.bags for ld in state.loads if ld.wash_end <= state.minute),
        "bags_in_dryer": in_dryer,
        "bags_dried_complete": dried_complete,
        "bags_ready_for_folding": min(inp.bag_count, ready_fold),
        "bags_folded": min(inp.bag_count, int(state.folded)),
        "bags_waiting_for_dryer": washed_waiting,
        "bottleneck": bottleneck,
        "action_needed": _action_for_bottleneck(bottleneck, backlogs),
        "backlogs": backlogs,
    }


def _step_weigh_sort(state: SimState, inp: PlannerInputs) -> None:
    if inp.uses_dedicated_weigher:
        if state.incoming_bags and inp.weigher_count > 0:
            state.weigh_remainder += inp.weigher_count / inp.weigh_min_per_bag
            while state.weigh_remainder >= 1 and state.incoming_bags:
                bag = state.incoming_bags.pop(0)
                state.weigh_queue.append(bag)
                state.weighed_count += 1
                state.weigh_remainder -= 1

    if state.weigh_queue and inp.uses_dedicated_weigher:
        while state.weigh_queue:
            state.sort_queue.append(state.weigh_queue.pop(0))

    if state.sort_queue and inp.sorter_count > 0:
        state.sort_remainder += inp.sorter_count / inp.effective_sort_min_per_bag
        while state.sort_remainder >= 1 and state.sort_queue:
            bag = state.sort_queue.pop(0)
            state.sorted_pool.append((state.next_bag_index, bag))
            state.next_bag_index += 1
            state.sorted_count += 1
            state.sort_remainder -= 1
            if inp.weighing_handled_by == "sorter":
                state.weighed_count += 1


def _can_start_wash(state: SimState, inp: PlannerInputs, strategy: StrategyName) -> bool:
    if state.pause_new_wash:
        return False
    if strategy == "dryer_push":
        elapsed = state.minute - inp.start_min
        if elapsed >= inp.dryer_push_wash_window_min and state.waiting_dryer:
            return False
    return True


def _washer_prep_minutes(inp: PlannerInputs, bag_count: int) -> int:
    if not inp.uses_washer_weighing:
        return 0
    return max(1, int(math.ceil(bag_count * inp.weigh_min_per_bag)))


def _start_wash_loads(state: SimState, inp: PlannerInputs, strategy: StrategyName) -> None:
    if not _can_start_wash(state, inp, strategy):
        if strategy == "dryer_push":
            elapsed = state.minute - inp.start_min
            if elapsed >= inp.dryer_push_wash_window_min and state.waiting_dryer:
                state.pause_new_wash = True
        return

    loads_started = len(state.loads)
    estimated_total = inp.total_wash_loads

    while loads_started < estimated_total and state.sorted_pool:
        weights = [w for _, w in state.sorted_pool]
        chunk_weights, remainder_weights = pack_load_from_pool(weights, inp.washer_capacity_lb)
        if not chunk_weights:
            break
        chunk_len = len(chunk_weights)
        chunk_entries = state.sorted_pool[:chunk_len]
        remainder_entries = state.sorted_pool[chunk_len:]
        slot_idx = min(range(len(state.washer_free_at)), key=lambda i: state.washer_free_at[i])
        free_at = state.washer_free_at[slot_idx]
        if free_at > state.minute:
            break
        prep = _washer_prep_minutes(inp, chunk_len)
        start = max(state.minute, free_at) + prep
        end = start + inp.wash_cycle_min
        bag_start = chunk_entries[0][0]
        bag_end = chunk_entries[-1][0]
        load = WashLoad(
            load_id=state.next_load_id,
            washer_id=slot_idx + 1,
            bag_start=bag_start,
            bag_end=bag_end,
            bags=chunk_len,
            pounds=round(sum(chunk_weights), 1),
            wash_start=start,
            wash_end=end,
        )
        state.next_load_id += 1
        state.loads.append(load)
        state.waiting_dryer.append(load)
        state.sorted_pool = remainder_entries
        state.washer_free_at[slot_idx] = end
        if inp.uses_washer_weighing:
            state.weighed_count += chunk_len
        loads_started += 1

    if (
        state.sorted_count >= inp.bag_count
        and state.sorted_pool
        and _can_start_wash(state, inp, strategy)
    ):
        slot_idx = min(range(len(state.washer_free_at)), key=lambda i: state.washer_free_at[i])
        free_at = state.washer_free_at[slot_idx]
        if free_at <= state.minute:
            chunk_entries = list(state.sorted_pool)
            chunk_weights = [w for _, w in chunk_entries]
            prep = _washer_prep_minutes(inp, len(chunk_entries))
            start = max(state.minute, free_at) + prep
            end = start + inp.wash_cycle_min
            load = WashLoad(
                load_id=state.next_load_id,
                washer_id=slot_idx + 1,
                bag_start=chunk_entries[0][0],
                bag_end=chunk_entries[-1][0],
                bags=len(chunk_entries),
                pounds=round(sum(chunk_weights), 1),
                wash_start=start,
                wash_end=end,
            )
            state.next_load_id += 1
            state.loads.append(load)
            state.waiting_dryer.append(load)
            state.sorted_pool = []
            state.washer_free_at[slot_idx] = end
            if inp.uses_washer_weighing:
                state.weighed_count += len(chunk_entries)


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
        load.dryer_id = slot_idx + 1
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


def _load_status_at(load: WashLoad, minute: int, *, stage: str) -> str:
    if stage == "washer":
        if minute < load.wash_start:
            return "waiting"
        if minute < load.wash_end:
            return "washing"
        if load.dry_start is None or minute < load.dry_start:
            return "ready_for_dryer"
        return "transferred"
    if stage == "dryer":
        if load.dry_start is None:
            return "waiting"
        if minute < load.dry_start:
            return "waiting"
        if minute < (load.dry_end or load.dry_start):
            return "drying"
        return "ready_to_fold"
    return "unknown"


def _build_washer_timeline(loads: list[WashLoad], inp: PlannerInputs) -> list[dict[str, Any]]:
    lanes: list[list[dict[str, Any]]] = [[] for _ in range(inp.washer_count)]
    end_minute = max((ld.wash_end for ld in loads), default=inp.start_min)
    for ld in loads:
        lanes[ld.washer_id - 1].append(
            {
                "load_id": ld.load_id,
                "label": (
                    f"Washer {ld.washer_id}: {_minutes_to_label(ld.wash_start)}-"
                    f"{_minutes_to_label(ld.wash_end)} | Bags {ld.bag_start}-{ld.bag_end} | "
                    f"{ld.pounds} lb"
                ),
                "washer_id": ld.washer_id,
                "start": _minutes_to_label(ld.wash_start),
                "end": _minutes_to_label(ld.wash_end),
                "bag_start": ld.bag_start,
                "bag_end": ld.bag_end,
                "bags": ld.bags,
                "pounds": ld.pounds,
                "status": _load_status_at(ld, end_minute, stage="washer"),
            }
        )
    return [
        {"washer_id": i + 1, "loads": lane}
        for i, lane in enumerate(lanes)
        if lane
    ]


def _build_dryer_timeline(loads: list[WashLoad], inp: PlannerInputs) -> list[dict[str, Any]]:
    lanes: list[list[dict[str, Any]]] = [[] for _ in range(inp.dryer_count)]
    end_minute = max((ld.dry_end or inp.start_min for ld in loads), default=inp.start_min)
    for ld in loads:
        if ld.dryer_id is None or ld.dry_start is None:
            continue
        lanes[ld.dryer_id - 1].append(
            {
                "load_id": ld.load_id,
                "label": (
                    f"Dryer {ld.dryer_id}: {_minutes_to_label(ld.dry_start)}-"
                    f"{_minutes_to_label(ld.dry_end or ld.dry_start)} | Bags {ld.bag_start}-{ld.bag_end} | "
                    f"{ld.pounds} lb"
                ),
                "dryer_id": ld.dryer_id,
                "start": _minutes_to_label(ld.dry_start),
                "end": _minutes_to_label(ld.dry_end) if ld.dry_end else None,
                "bag_start": ld.bag_start,
                "bag_end": ld.bag_end,
                "bags": ld.bags,
                "pounds": ld.pounds,
                "status": _load_status_at(ld, end_minute, stage="dryer"),
            }
        )
    return [
        {"dryer_id": i + 1, "loads": lane}
        for i, lane in enumerate(lanes)
        if lane
    ]


def _build_alerts(inp: PlannerInputs, milestones: dict[str, dict[str, Any]], final: dict[str, Any]) -> list[str]:
    alerts: list[str] = []
    seen: set[str] = set()

    def add(msg: str) -> None:
        if msg and msg not in seen:
            seen.add(msg)
            alerts.append(msg)

    if final["bottleneck"] != "none":
        add(final["action_needed"])

    target_snap = milestones.get(_minutes_to_label(inp.target_min))
    if target_snap and target_snap["bags_folded"] < inp.bag_count:
        short = inp.bag_count - target_snap["bags_folded"]
        add(f"Only {target_snap['bags_folded']}/{inp.bag_count} folded by target — {short} bags short")

    for clock in ("9:00 AM", "10:00 AM"):
        snap = milestones.get(clock)
        if snap and snap["bottleneck"] in {"sorting", "weighing", "waiting_dryer"}:
            add(f"By {clock}: {snap['action_needed']}")

    if inp.weighing_handled_by == "sorter":
        add("Weighing on sorters — sort capacity reduced by weigh time per bag")
    elif inp.weighing_handled_by == "washer":
        add("Weighing at washers — load starts delayed by weigh time per bag")

    loads = inp.estimate_wash_loads()
    if loads:
        sample = loads[0]
        add(
            f"Est. {len(loads)} wash loads · avg {inp.avg_bags_per_wash_load:.1f} bags/load "
            f"(first load: {sample['bags']} bags / {sample['pounds']} lb)"
        )

    return alerts[:6]


def run_simulation(inp: PlannerInputs, strategy: StrategyName) -> dict[str, Any]:
    state = _init_state(inp)
    milestone_mins = {_parse_clock_minutes(c, default=c): c for c in MILESTONE_CLOCKS}
    milestones: dict[str, dict[str, Any]] = {}
    max_minute = inp.start_min + (inp.target_min - inp.start_min) + inp.wash_cycle_min + inp.dry_cycle_min + 240
    first_ready_min: int | None = None
    all_wash_done_min: int | None = None
    all_dry_done_min: int | None = None
    all_folded_min: int | None = None

    for t in range(inp.start_min, max_minute + 1):
        state.minute = t
        _step_weigh_sort(state, inp)
        _resume_wash(state, strategy)
        _start_wash_loads(state, inp, strategy)
        _release_to_dryers(state, inp)
        _release_to_fold(state, inp)
        _step_fold(state, inp)

        washed_bags = sum(ld.bags for ld in state.loads if ld.wash_end <= t)
        dried_bags = sum(ld.bags for ld in state.loads if ld.dry_end is not None and ld.dry_end <= t)

        if first_ready_min is None and dried_bags > 0:
            first_ready_min = min(
                ld.dry_end for ld in state.loads if ld.dry_end is not None and ld.dry_end <= t
            )
        if all_wash_done_min is None and washed_bags >= inp.bag_count and not state.waiting_dryer:
            all_in_dryer_or_done = all(
                ld.dry_start is not None or ld.wash_end <= t for ld in state.loads
            )
            if all_in_dryer_or_done and len(state.loads) >= inp.total_wash_loads:
                all_wash_done_min = t
        if all_dry_done_min is None and dried_bags >= inp.bag_count:
            all_dry_done_min = t
        if state.folded >= inp.bag_count and all_folded_min is None:
            all_folded_min = t

        if t in milestone_mins:
            milestones[milestone_mins[t]] = _snapshot(state, inp)

        if t == inp.target_min:
            milestones.setdefault(_minutes_to_label(t), _snapshot(state, inp))

        if state.folded >= inp.bag_count and t >= inp.target_min:
            break

    final = _snapshot(state, inp)
    estimated_loads = inp.estimate_wash_loads()

    return {
        "strategy": strategy,
        "milestones": milestones,
        "milestone_rows": [
            {"time": clock, **milestones[clock]}
            for clock in sorted(
                milestones.keys(),
                key=lambda c: _parse_clock_minutes(c, default="12:00 PM"),
            )
        ],
        "final": final,
        "summary": {
            "first_bags_ready": _minutes_to_label(first_ready_min) if first_ready_min else None,
            "first_bags_ready_minute": first_ready_min,
            "all_washing_done": _minutes_to_label(all_wash_done_min) if all_wash_done_min else None,
            "all_drying_done": _minutes_to_label(all_dry_done_min) if all_dry_done_min else None,
            "all_folded": _minutes_to_label(all_folded_min) if all_folded_min else None,
            "bottleneck": final["bottleneck"],
            "total_wash_loads": inp.total_wash_loads,
            "avg_bags_per_wash_load": round(inp.avg_bags_per_wash_load, 2),
            "estimated_load_plan": estimated_loads[:8],
        },
        "washer_timeline": _build_washer_timeline(state.loads, inp),
        "dryer_timeline": _build_dryer_timeline(state.loads, inp),
        "alerts": _build_alerts(inp, milestones, final),
    }


def compute_staffing(inp: PlannerInputs) -> dict[str, Any]:
    window = inp.target_min - inp.start_min
    fold_window = max(60, window // 2)
    weigh_window = window if inp.uses_dedicated_weigher else 0
    suggested_weighers = (
        max(1, math.ceil(inp.bag_count * inp.weigh_min_per_bag / window))
        if inp.uses_dedicated_weigher
        else 0
    )
    sort_rate = inp.effective_sort_min_per_bag
    suggested_sorters = max(1, math.ceil(inp.bag_count * sort_rate / window))
    suggested_folders = max(1, math.ceil(inp.bag_count * inp.fold_min_per_bag / fold_window))
    helpers = 0
    avg_bags = max(1, inp.avg_bags_per_wash_load)
    wash_throughput = inp.washer_count * (window / inp.wash_cycle_min) * avg_bags
    if inp.bag_count > wash_throughput:
        helpers += 1
    dry_throughput = inp.dryer_count * (window / inp.dry_cycle_min) * avg_bags
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


def recommend_strategy(results: dict[str, dict[str, Any]], inp: PlannerInputs, staffing: dict[str, Any]) -> dict[str, Any]:
    cont = results["continuous_washing"]
    push = results["dryer_push"]
    cont_folded = cont["final"]["bags_folded"]
    push_folded = push["final"]["bags_folded"]
    cont_ready = cont["final"]["bags_ready_for_folding"]
    push_ready = push["final"]["bags_ready_for_folding"]

    if push_folded > cont_folded or (push_folded == cont_folded and push_ready > cont_ready):
        pick = "dryer_push"
        reason = "Dryer Push delivers more bags ready or folded by target time."
        chosen = push
    else:
        pick = "continuous_washing"
        reason = "Continuous Washing keeps the wash line full with steadier throughput."
        chosen = cont

    return {
        "recommended": pick,
        "label": "Continuous Washing" if pick == "continuous_washing" else "Dryer Push",
        "reason": reason,
        "start_time": _minutes_to_label(inp.start_min),
        "suggested_staff": {
            "weighers": staffing["weighers"],
            "sorters": staffing["sorters"],
            "folders": staffing["folders"],
            "washers": inp.washer_count,
            "dryers": inp.dryer_count,
        },
        "first_fold_ready": chosen["summary"]["first_bags_ready"],
        "all_washing_done": chosen["summary"]["all_washing_done"],
        "all_drying_done": chosen["summary"]["all_drying_done"],
        "all_folding_done": chosen["summary"]["all_folded"],
        "main_bottleneck": chosen["summary"]["bottleneck"],
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
    recommendation = recommend_strategy(strategies, inp, staffing)
    recommended_key = recommendation["recommended"]
    return {
        "inputs": {
            "start_time": _minutes_to_label(inp.start_min),
            "target_time": _minutes_to_label(inp.target_min),
            "bag_count": inp.bag_count,
            "avg_lbs_per_bag": inp.avg_lbs_per_bag,
            "small_bag_pct": inp.small_bag_pct,
            "medium_bag_pct": inp.medium_bag_pct,
            "large_bag_pct": inp.large_bag_pct,
            "small_bag_lb": inp.small_bag_lb,
            "medium_bag_lb": inp.medium_bag_lb,
            "large_bag_lb": inp.large_bag_lb,
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
            "weighing_handled_by": inp.weighing_handled_by,
            "total_wash_loads": inp.total_wash_loads,
            "avg_bags_per_wash_load": round(inp.avg_bags_per_wash_load, 2),
            "estimated_load_plan": inp.estimate_wash_loads()[:8],
        },
        "staffing": staffing,
        "strategies": strategies,
        "recommendation": recommendation,
        "active_strategy": strategies[recommended_key],
    }
