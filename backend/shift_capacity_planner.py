"""Shift Capacity Planner — discrete-time shift simulator with split-load distribution."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal

StrategyName = Literal["continuous_washing", "dryer_push"]
WashingStrategy = Literal["batch_washing", "sort_while_drying"]
WeighingHandledBy = Literal["dedicated_weigher", "sorter", "washer"]
WeighingMode = Literal["upfront", "during_sort", "separate_lane"]
TRANSFER_MIN = 5
BATCH_SIZE_OPTIONS = (6, 8, 10, 12)
MILESTONE_INTERVAL_MIN = 30


def _milestone_minutes(start_min: int, target_min: int, *, interval: int = MILESTONE_INTERVAL_MIN) -> list[int]:
    """Clock times for milestone snapshots: start, every *interval* minutes, then target."""
    if target_min < start_min:
        return [start_min]
    times = [start_min]
    t = ((start_min + interval - 1) // interval) * interval
    if t <= start_min:
        t = start_min + interval
    while t < target_min:
        times.append(t)
        t += interval
    if times[-1] != target_min:
        times.append(target_min)
    return times

DEFAULTS: dict[str, Any] = {
    "start_time": "7:00 AM",
    "target_time": "12:00 PM",
    "bag_count": 50,
    "avg_lbs_per_bag": 20,
    "orders_using_2_washers": None,
    "orders_using_2_dryers": None,
    "sorter_early_start_min": 0,
    "sorter_break_after_bags": 0,
    "sorter_break_duration_min": 0,
    "washer_break_after_bags": 0,
    "washer_break_duration_min": 0,
    "washer_count": 4,
    "dryer_count": 4,
    "wash_cycle_min": 30,
    "dry_cycle_min": 45,
    "weigh_min_per_bag": 1,
    "sort_min_per_bag": 5,
    "fold_min_per_bag": 6,
    "folder_count": 3,
    "weigher_count": None,
    "sorter_count": None,
    "weighing_handled_by": "dedicated_weigher",
    "weighing_mode": "separate_lane",
    "transfer_min": TRANSFER_MIN,
    "dryer_push_wash_window_min": 45,
    "washing_strategy": "batch_washing",
    "batch_size": 8,
    "load_washer_min": 3,
    "unload_washer_min": 3,
    "load_dryer_min": 3,
    "unload_dryer_min": 2,
    "washer_transfer_min": TRANSFER_MIN,
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


WEIGHING_MODE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "separate_lane": {
        "label": "Separate weigh lane",
        "description": (
            "Dedicated weigher(s) on their own lane; weighed bags feed sorting "
            "continuously. Sorter and weigher are different people."
        ),
        "who_options": ["dedicated_weigher"],
    },
    "during_sort": {
        "label": "Weigh while sorting",
        "description": (
            "Sorter weighs each bag as part of sorting — same person, sort time "
            "includes weigh time per bag."
        ),
        "who_options": ["sorter"],
    },
    "upfront": {
        "label": "Weigh all at shift start",
        "description": (
            "All bags are weighed before any sorting begins. Washer can arrive "
            "early to weigh everything, or a weigher/sorter can do upfront weigh."
        ),
        "who_options": ["dedicated_weigher", "sorter", "washer"],
    },
}


STRATEGY_DEFINITIONS: dict[str, dict[str, str]] = {
    "batch_washing": {
        "label": "Batch Washing",
        "description": (
            "Sort a batch, then the washer person washes it, transfers to dryers, "
            "and loads dryers before the sorter starts the next batch. Matches one "
            "washer-person who cannot wash and load dryers at the same time."
        ),
    },
    "sort_while_drying": {
        "label": "Sort While Drying",
        "description": (
            "Sorter keeps sorting ahead while the washer person finishes wash → "
            "transfer → dryer loading for the previous batch. Use when sorting capacity "
            "can stay ahead without blocking dryer work."
        ),
    },
}


def _parse_washing_strategy(raw: Any) -> WashingStrategy:
    value = str(raw or DEFAULTS["washing_strategy"]).strip().lower()
    aliases = {
        "batch": "batch_washing",
        "batch_washing": "batch_washing",
        "sort_while_drying": "sort_while_drying",
        "sort_during_dry": "sort_while_drying",
        "sort_while_dry": "sort_while_drying",
        # Legacy API values — continuous/hybrid were misleading for one washer-person ops
        "continuous": "sort_while_drying",
        "continuous_washing": "sort_while_drying",
        "hybrid": "batch_washing",
        "hybrid_recommended": "batch_washing",
        "recommended": "batch_washing",
    }
    if value not in aliases:
        raise ValueError(
            "washing_strategy must be one of: batch_washing, sort_while_drying"
        )
    return aliases[value]  # type: ignore[return-value]


def _parse_batch_size(raw: Any) -> int:
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return int(DEFAULTS["batch_size"])
    try:
        n = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("batch_size must be an integer") from exc
    if n < 1:
        raise ValueError("batch_size must be >= 1")
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


def _parse_weighing_mode(raw: Any, handled_by: WeighingHandledBy) -> WeighingMode:
    if raw is not None and str(raw).strip():
        value = str(raw).strip().lower()
        aliases = {
            "upfront": "upfront",
            "upfront_all": "upfront",
            "weigh_all": "upfront",
            "during_sort": "during_sort",
            "weigh_during_sort": "during_sort",
            "while_sorting": "during_sort",
            "separate_lane": "separate_lane",
            "separate": "separate_lane",
            "dedicated_lane": "separate_lane",
        }
        if value not in aliases:
            raise ValueError(
                "weighing_mode must be one of: upfront, during_sort, separate_lane"
            )
        return aliases[value]  # type: ignore[return-value]
    if handled_by == "sorter":
        return "during_sort"
    if handled_by == "washer":
        return "upfront"
    return "separate_lane"


def _normalize_weighing_config(
    mode: WeighingMode, handled_by: WeighingHandledBy
) -> tuple[WeighingMode, WeighingHandledBy]:
    """Align mode and handler; sorter≠washer and mode constraints."""
    if mode == "during_sort":
        return mode, "sorter"
    if mode == "separate_lane":
        return mode, "dedicated_weigher"
    allowed = WEIGHING_MODE_DEFINITIONS["upfront"]["who_options"]
    if handled_by not in allowed:
        return mode, "dedicated_weigher"
    return mode, handled_by


def build_uniform_bag_weights(bag_count: int, avg_lb: float) -> list[float]:
    return [avg_lb] * bag_count


def _default_split_order_count(bag_count: int) -> int:
    """Default: 80% of orders use 2 machines (40 of 50 baseline)."""
    return min(bag_count, int(round(bag_count * 0.8)))


def _parse_split_order_count(
    raw_count: Any,
    raw_pct: Any,
    *,
    bag_count: int,
    count_name: str,
    pct_name: str,
    default_count: int | None = None,
) -> int:
    if default_count is None:
        default_count = _default_split_order_count(bag_count)
    has_count = raw_count is not None and str(raw_count).strip() != ""
    has_pct = raw_pct is not None and str(raw_pct).strip() != ""
    if has_count and has_pct:
        raise ValueError(f"Provide either {count_name} or {pct_name}, not both")
    if has_count:
        n = _non_negative_int(raw_count, count_name)
    elif has_pct:
        pct = _non_negative_float(raw_pct, pct_name)
        if pct > 100.0001:
            raise ValueError(f"{pct_name} must be <= 100")
        n = int(round(bag_count * pct / 100.0))
    else:
        n = default_count
    if n > bag_count:
        raise ValueError(f"{count_name} must be <= bag_count ({bag_count})")
    return n


def build_order_machine_loads(bag_count: int, *, orders_using_2: int) -> list[int]:
    """Per-order washer or dryer load count (1 or 2 machines)."""
    if orders_using_2 < 0 or orders_using_2 > bag_count:
        raise ValueError("orders_using_2 must be between 0 and bag_count")
    return [2] * orders_using_2 + [1] * (bag_count - orders_using_2)


def compute_split_load_distribution(
    bag_count: int,
    *,
    orders_using_2_washers: int,
    orders_using_2_dryers: int,
) -> dict[str, int]:
    orders_1_washer = bag_count - orders_using_2_washers
    orders_1_dryer = bag_count - orders_using_2_dryers
    washer_loads_total = orders_using_2_washers * 2 + orders_1_washer
    dryer_loads_total = orders_using_2_dryers * 2 + orders_1_dryer
    return {
        "orders_using_2_washers": orders_using_2_washers,
        "orders_using_1_washer": orders_1_washer,
        "orders_using_2_dryers": orders_using_2_dryers,
        "orders_using_1_dryer": orders_1_dryer,
        "washer_loads_total": washer_loads_total,
        "dryer_loads_total": dryer_loads_total,
    }


def split_distribution_summary(
    bag_count: int,
    *,
    orders_using_2_washers: int,
    orders_using_2_dryers: int,
    avg_lb: float,
) -> dict[str, Any]:
    dist = compute_split_load_distribution(
        bag_count,
        orders_using_2_washers=orders_using_2_washers,
        orders_using_2_dryers=orders_using_2_dryers,
    )
    order_washer_loads = build_order_machine_loads(
        bag_count, orders_using_2=orders_using_2_washers
    )
    order_dryer_loads = build_order_machine_loads(
        bag_count, orders_using_2=orders_using_2_dryers
    )
    dist["order_washer_loads_preview"] = order_washer_loads[:12]
    dist["order_dryer_loads_preview"] = order_dryer_loads[:12]
    dist["total_wash_loads"] = dist["washer_loads_total"]
    dist["total_dryer_loads"] = dist["dryer_loads_total"]
    dist["avg_lbs_per_washer_load"] = round(
        bag_count * avg_lb / max(1, dist["washer_loads_total"]), 1
    )
    dist["avg_lbs_per_dryer_load"] = round(
        bag_count * avg_lb / max(1, dist["dryer_loads_total"]), 1
    )
    dist["summary_lines"] = [
        (
            f"{orders_using_2_washers} of {bag_count} orders → 2 washers each "
            f"({orders_using_2_washers * 2} washer loads)"
        ),
        (
            f"{dist['orders_using_1_washer']} of {bag_count} orders → 1 washer each "
            f"({dist['orders_using_1_washer']} washer loads)"
        ),
        f"Total washer loads: {dist['washer_loads_total']}",
        (
            f"{orders_using_2_dryers} of {bag_count} orders → 2 dryers each "
            f"({orders_using_2_dryers * 2} dryer loads)"
        ),
        (
            f"{dist['orders_using_1_dryer']} of {bag_count} orders → 1 dryer each "
            f"({dist['orders_using_1_dryer']} dryer loads)"
        ),
        f"Total dryer loads: {dist['dryer_loads_total']}",
    ]
    return dist


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
    order_washer_loads: list[int]
    order_dryer_loads: list[int]
    orders_using_2_washers: int
    orders_using_2_dryers: int
    split_distribution: dict[str, Any]
    washer_count: int
    dryer_count: int
    wash_cycle_min: int
    dry_cycle_min: int
    weigh_min_per_bag: float
    sort_min_per_bag: float
    fold_min_per_bag: float
    folder_count: int
    weigher_count: int
    sorter_count: int
    weighing_handled_by: WeighingHandledBy
    weighing_mode: WeighingMode
    transfer_min: int
    dryer_push_wash_window_min: int
    washing_strategy: WashingStrategy
    batch_size: int
    load_washer_min: int
    unload_washer_min: int
    load_dryer_min: int
    unload_dryer_min: int
    washer_transfer_min: int
    sorter_early_start_min: int = 0
    sorter_break_after_bags: int = 0
    sorter_break_duration_min: int = 0
    washer_break_after_bags: int = 0
    washer_break_duration_min: int = 0

    @property
    def effective_sort_min_per_bag(self) -> float:
        if self.weighing_mode == "during_sort":
            return self.sort_min_per_bag + self.weigh_min_per_bag
        return self.sort_min_per_bag

    @property
    def uses_dedicated_weigher(self) -> bool:
        return self.weighing_mode == "separate_lane" or (
            self.weighing_mode == "upfront"
            and self.weighing_handled_by == "dedicated_weigher"
        )

    @property
    def uses_washer_weighing(self) -> bool:
        return False

    @property
    def needs_weigher_staff(self) -> bool:
        return self.uses_dedicated_weigher and self.weigher_count > 0

    def estimate_wash_loads(self) -> list[dict[str, Any]]:
        loads: list[dict[str, Any]] = []
        load_id = 1
        for order_idx, machine_count in enumerate(self.order_washer_loads, start=1):
            for split_idx in range(machine_count):
                loads.append(
                    {
                        "order": order_idx,
                        "bags": 1,
                        "pounds": round(self.avg_lbs_per_bag, 1),
                        "bag_start": order_idx,
                        "bag_end": order_idx,
                        "load_type": "two_washer_split" if machine_count == 2 else "single_washer",
                        "split_part": split_idx + 1 if machine_count > 1 else None,
                        "load_id": load_id,
                    }
                )
                load_id += 1
        return loads

    @property
    def total_wash_loads(self) -> int:
        return sum(self.order_washer_loads)

    @property
    def total_dryer_loads(self) -> int:
        return sum(self.order_dryer_loads)

    @property
    def avg_bags_per_wash_load(self) -> float:
        if self.total_wash_loads <= 0:
            return 0.0
        return self.bag_count / self.total_wash_loads

    @property
    def washer_cycle_orders(self) -> list[int]:
        cycles: list[int] = []
        for order_id, machine_count in enumerate(self.order_washer_loads, start=1):
            cycles.extend([order_id] * machine_count)
        return cycles


@dataclass
class WashLoad:
    load_id: int
    washer_id: int
    order_id: int
    bag_start: int
    bag_end: int
    bags: int
    pounds: float
    wash_start: int
    wash_end: int
    split_part: int | None = None
    dry_start: int | None = None
    dry_end: int | None = None
    dryer_id: int | None = None


@dataclass
class DryerJob:
    order_id: int
    bag_start: int
    bag_end: int
    bags: int
    pounds: float
    ready_at: int
    split_part: int | None = None
    wash_load_ids: list[int] = field(default_factory=list)


@dataclass
class DryCycle:
    cycle_id: int
    order_id: int
    bag_start: int
    bag_end: int
    bags: int
    pounds: float
    dry_start: int
    dry_end: int
    dryer_id: int
    split_part: int | None = None


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
    loads: list[WashLoad] = field(default_factory=list)
    dry_cycles: list[DryCycle] = field(default_factory=list)
    next_load_id: int = 1
    next_dry_cycle_id: int = 1
    pause_new_wash: bool = False
    weigh_remainder: float = 0.0
    sort_remainder: float = 0.0
    fold_remainder: float = 0.0
    next_wash_order: int = 0
    order_wash_finished: dict[int, int] = field(default_factory=dict)
    order_dryer_finished: dict[int, int] = field(default_factory=dict)
    orders_dryer_queued: set[int] = field(default_factory=set)
    pending_dryer_jobs: list[DryerJob] = field(default_factory=list)
    sorter_bags_since_break: int = 0
    sorter_on_break_until: int | None = None


def parse_planner_inputs(data: dict[str, Any] | None) -> PlannerInputs:
    raw = {**DEFAULTS, **(data or {})}
    start_min = _parse_clock_minutes(raw.get("start_time"), default=DEFAULTS["start_time"])
    target_min = _parse_clock_minutes(raw.get("target_time"), default=DEFAULTS["target_time"])
    if target_min <= start_min:
        raise ValueError("target_time must be after start_time")

    bag_count = _positive_int(raw.get("bag_count"), "bag_count")
    avg_lbs = _positive_float(raw.get("avg_lbs_per_bag"), "avg_lbs_per_bag")
    user_raw = data or {}

    orders_2_washers = _parse_split_order_count(
        user_raw.get("orders_using_2_washers"),
        user_raw.get("orders_using_2_washers_pct"),
        bag_count=bag_count,
        count_name="orders_using_2_washers",
        pct_name="orders_using_2_washers_pct",
    )
    orders_2_dryers = _parse_split_order_count(
        user_raw.get("orders_using_2_dryers"),
        user_raw.get("orders_using_2_dryers_pct"),
        bag_count=bag_count,
        count_name="orders_using_2_dryers",
        pct_name="orders_using_2_dryers_pct",
    )
    split_dist = split_distribution_summary(
        bag_count,
        orders_using_2_washers=orders_2_washers,
        orders_using_2_dryers=orders_2_dryers,
        avg_lb=avg_lbs,
    )
    order_washer_loads = build_order_machine_loads(
        bag_count, orders_using_2=orders_2_washers
    )
    order_dryer_loads = build_order_machine_loads(
        bag_count, orders_using_2=orders_2_dryers
    )
    bag_weights = build_uniform_bag_weights(bag_count, avg_lbs)
    wash_cycle = _positive_int(raw.get("wash_cycle_min"), "wash_cycle_min")
    dry_cycle = _positive_int(raw.get("dry_cycle_min"), "dry_cycle_min")
    weigh_min = _positive_float(raw.get("weigh_min_per_bag"), "weigh_min_per_bag")
    sort_min = _positive_float(raw.get("sort_min_per_bag"), "sort_min_per_bag")
    fold_min = _positive_float(raw.get("fold_min_per_bag"), "fold_min_per_bag")
    folder_count = _non_negative_int(raw.get("folder_count"), "folder_count")
    transfer_min = _non_negative_int(raw.get("transfer_min"), "transfer_min")
    push_window = _positive_int(raw.get("dryer_push_wash_window_min"), "dryer_push_wash_window_min")
    weighing_handled_by = _parse_weighing_handled_by(raw.get("weighing_handled_by"))
    weighing_mode_raw = raw.get("weighing_mode")
    weighing_mode = _parse_weighing_mode(weighing_mode_raw, weighing_handled_by)
    weighing_mode, weighing_handled_by = _normalize_weighing_config(
        weighing_mode, weighing_handled_by
    )
    washing_strategy = _parse_washing_strategy(raw.get("washing_strategy"))
    batch_size = _parse_batch_size(raw.get("batch_size"))
    load_washer_min = _non_negative_int(raw.get("load_washer_min"), "load_washer_min")
    unload_washer_min = _non_negative_int(raw.get("unload_washer_min"), "unload_washer_min")
    load_dryer_min = _non_negative_int(raw.get("load_dryer_min"), "load_dryer_min")
    unload_dryer_min = _non_negative_int(raw.get("unload_dryer_min"), "unload_dryer_min")
    washer_transfer_min = _non_negative_int(
        raw.get("washer_transfer_min") or raw.get("transfer_min"),
        "washer_transfer_min",
    )
    sorter_early_start_min = _non_negative_int(
        raw.get("sorter_early_start_min"), "sorter_early_start_min"
    )
    sorter_break_after_bags = _non_negative_int(
        raw.get("sorter_break_after_bags"), "sorter_break_after_bags"
    )
    sorter_break_duration_min = _non_negative_int(
        raw.get("sorter_break_duration_min"), "sorter_break_duration_min"
    )
    washer_break_after_bags = _non_negative_int(
        raw.get("washer_break_after_bags"), "washer_break_after_bags"
    )
    washer_break_duration_min = _non_negative_int(
        raw.get("washer_break_duration_min"), "washer_break_duration_min"
    )

    washer_count = _positive_int(raw.get("washer_count"), "washer_count")
    dryer_count = _positive_int(raw.get("dryer_count"), "dryer_count")

    window_min = target_min - start_min
    needs_weigher = weighing_mode == "separate_lane" or (
        weighing_mode == "upfront" and weighing_handled_by == "dedicated_weigher"
    )
    weigher_default = (
        max(1, math.ceil(bag_count * weigh_min / window_min)) if needs_weigher else 0
    )
    sort_rate = (
        sort_min + weigh_min if weighing_mode == "during_sort" else sort_min
    )
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

    if not needs_weigher:
        weigher_count = 0

    return PlannerInputs(
        start_min=start_min,
        target_min=target_min,
        bag_count=bag_count,
        avg_lbs_per_bag=avg_lbs,
        bag_weights=bag_weights,
        order_washer_loads=order_washer_loads,
        order_dryer_loads=order_dryer_loads,
        orders_using_2_washers=orders_2_washers,
        orders_using_2_dryers=orders_2_dryers,
        split_distribution=split_dist,
        washer_count=washer_count,
        dryer_count=dryer_count,
        wash_cycle_min=wash_cycle,
        dry_cycle_min=dry_cycle,
        weigh_min_per_bag=weigh_min,
        sort_min_per_bag=sort_min,
        fold_min_per_bag=fold_min,
        folder_count=folder_count,
        weigher_count=weigher_count,
        sorter_count=sorter_count,
        weighing_handled_by=weighing_handled_by,
        weighing_mode=weighing_mode,
        transfer_min=transfer_min,
        dryer_push_wash_window_min=push_window,
        washing_strategy=washing_strategy,
        batch_size=batch_size,
        load_washer_min=load_washer_min,
        unload_washer_min=unload_washer_min,
        load_dryer_min=load_dryer_min,
        unload_dryer_min=unload_dryer_min,
        washer_transfer_min=washer_transfer_min,
        sorter_early_start_min=sorter_early_start_min,
        sorter_break_after_bags=sorter_break_after_bags,
        sorter_break_duration_min=sorter_break_duration_min,
        washer_break_after_bags=washer_break_after_bags,
        washer_break_duration_min=washer_break_duration_min,
    )


def _init_state(inp: PlannerInputs) -> SimState:
    state = SimState(
        minute=inp.start_min,
        incoming_bags=list(inp.bag_weights),
        washer_free_at=[inp.start_min] * inp.washer_count,
        dryer_free_at=[inp.start_min] * inp.dryer_count,
    )
    if inp.weighing_mode in ("separate_lane", "upfront"):
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
    return sum(job.bags for job in state.pending_dryer_jobs)


def _bags_in_dryer(state: SimState) -> int:
    return sum(
        cycle.bags
        for cycle in state.dry_cycles
        if cycle.dry_start <= state.minute < cycle.dry_end
    )


def _bags_dried_complete(state: SimState, inp: PlannerInputs) -> int:
    dried = 0
    for order_id in range(1, inp.bag_count + 1):
        expected = inp.order_dryer_loads[order_id - 1]
        if state.order_dryer_finished.get(order_id, 0) >= expected:
            dried += 1
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
    dried_complete = _bags_dried_complete(state, inp)
    ready_fold = int(state.ready_for_fold + state.folded)

    weighed_backlog = len(state.incoming_bags) + len(state.weigh_queue)
    if inp.weighing_mode == "upfront":
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


def _sorter_can_work(state: SimState, inp: PlannerInputs) -> bool:
    if state.sorter_on_break_until is not None and state.minute < state.sorter_on_break_until:
        return False
    earliest = inp.start_min - inp.sorter_early_start_min
    return state.minute >= earliest


def _maybe_trigger_sorter_break(state: SimState, inp: PlannerInputs) -> None:
    if (
        inp.sorter_break_after_bags > 0
        and inp.sorter_break_duration_min > 0
        and state.sorter_bags_since_break >= inp.sorter_break_after_bags
    ):
        state.sorter_on_break_until = state.minute + inp.sorter_break_duration_min
        state.sorter_bags_since_break = 0


def _step_weigh_sort(state: SimState, inp: PlannerInputs) -> None:
    if inp.weighing_mode == "separate_lane":
        if state.incoming_bags and inp.weigher_count > 0 and state.minute >= inp.start_min:
            state.weigh_remainder += inp.weigher_count / inp.weigh_min_per_bag
            while state.weigh_remainder >= 1 and state.incoming_bags:
                bag = state.incoming_bags.pop(0)
                state.weigh_queue.append(bag)
                state.weighed_count += 1
                state.weigh_remainder -= 1

        if state.weigh_queue and inp.uses_dedicated_weigher:
            while state.weigh_queue:
                state.sort_queue.append(state.weigh_queue.pop(0))

    elif inp.weighing_mode == "upfront":
        if state.incoming_bags and state.minute >= inp.start_min:
            rate = _upfront_weigh_rate(inp)
            if rate > 0:
                state.weigh_remainder += rate
                while state.weigh_remainder >= 1 and state.incoming_bags:
                    bag = state.incoming_bags.pop(0)
                    state.sort_queue.append(bag)
                    state.weighed_count += 1
                    state.weigh_remainder -= 1

    sort_allowed = True
    if inp.weighing_mode == "upfront" and state.weighed_count < inp.bag_count:
        sort_allowed = False

    if (
        sort_allowed
        and state.sort_queue
        and inp.sorter_count > 0
        and _sorter_can_work(state, inp)
    ):
        state.sort_remainder += inp.sorter_count / inp.effective_sort_min_per_bag
        while state.sort_remainder >= 1 and state.sort_queue:
            bag = state.sort_queue.pop(0)
            state.sorted_pool.append((state.next_bag_index, bag))
            state.next_bag_index += 1
            state.sorted_count += 1
            state.sort_remainder -= 1
            state.sorter_bags_since_break += 1
            if inp.weighing_mode == "during_sort":
                state.weighed_count += 1
            _maybe_trigger_sorter_break(state, inp)
            if state.sorter_on_break_until is not None and state.minute < state.sorter_on_break_until:
                break


def _can_start_wash(state: SimState, inp: PlannerInputs, strategy: StrategyName) -> bool:
    if state.pause_new_wash:
        return False
    if strategy == "dryer_push":
        elapsed = state.minute - inp.start_min
        if elapsed >= inp.dryer_push_wash_window_min and state.pending_dryer_jobs:
            return False
    return True


def _washer_prep_minutes(inp: PlannerInputs, bag_count: int) -> int:
    if not inp.uses_washer_weighing:
        return 0
    return max(1, int(math.ceil(bag_count * inp.weigh_min_per_bag)))


def _take_next_wash_order(state: SimState, inp: PlannerInputs) -> tuple[int, float, int] | None:
    """Return (order_id, weight, washer_loads) when the next order is ready to wash."""
    if state.next_wash_order >= inp.bag_count:
        return None
    order_id = state.next_wash_order + 1
    if not state.sorted_pool or state.sorted_pool[0][0] != order_id:
        return None
    _, weight = state.sorted_pool.pop(0)
    washer_loads = inp.order_washer_loads[state.next_wash_order]
    state.next_wash_order += 1
    return order_id, weight, washer_loads


def _maybe_queue_dryer_jobs(state: SimState, inp: PlannerInputs, load: WashLoad) -> None:
    order_id = load.order_id
    state.order_wash_finished[order_id] = state.order_wash_finished.get(order_id, 0) + 1
    expected = inp.order_washer_loads[order_id - 1]
    if state.order_wash_finished[order_id] < expected or order_id in state.orders_dryer_queued:
        return
    state.orders_dryer_queued.add(order_id)
    order_loads = [ld for ld in state.loads if ld.order_id == order_id]
    ready_at = max(ld.wash_end for ld in order_loads) + inp.transfer_min
    dryer_count = inp.order_dryer_loads[order_id - 1]
    pounds = round(order_loads[0].pounds, 1)
    for part in range(1, dryer_count + 1):
        state.pending_dryer_jobs.append(
            DryerJob(
                order_id=order_id,
                bag_start=order_id,
                bag_end=order_id,
                bags=1,
                pounds=pounds,
                ready_at=ready_at,
                split_part=part if dryer_count > 1 else None,
                wash_load_ids=[ld.load_id for ld in order_loads],
            )
        )
    state.pending_dryer_jobs.sort(
        key=lambda job: (job.ready_at, job.order_id, job.split_part or 0)
    )


def _start_wash_loads(state: SimState, inp: PlannerInputs, strategy: StrategyName) -> None:
    if not _can_start_wash(state, inp, strategy):
        if strategy == "dryer_push":
            elapsed = state.minute - inp.start_min
            if elapsed >= inp.dryer_push_wash_window_min and state.pending_dryer_jobs:
                state.pause_new_wash = True
        return

    loads_started = len(state.loads)
    estimated_total = inp.total_wash_loads

    while loads_started < estimated_total:
        order_chunk = _take_next_wash_order(state, inp)
        if order_chunk is None:
            break
        order_id, weight, washer_loads = order_chunk
        chunk_entries = [(order_id, weight)]
        for split_part in range(1, washer_loads + 1):
            if loads_started >= estimated_total:
                break
            slot_idx = min(range(len(state.washer_free_at)), key=lambda i: state.washer_free_at[i])
            free_at = state.washer_free_at[slot_idx]
            if free_at > state.minute:
                state.sorted_pool = chunk_entries + state.sorted_pool
                state.next_wash_order -= 1
                return
            prep = _washer_prep_minutes(inp, 1) if split_part == 1 else 0
            start = max(state.minute, free_at) + prep
            end = start + inp.wash_cycle_min
            load = WashLoad(
                load_id=state.next_load_id,
                washer_id=slot_idx + 1,
                order_id=order_id,
                bag_start=order_id,
                bag_end=order_id,
                bags=1,
                pounds=round(weight, 1),
                wash_start=start,
                wash_end=end,
                split_part=split_part if washer_loads > 1 else None,
            )
            state.next_load_id += 1
            state.loads.append(load)
            state.washer_free_at[slot_idx] = end
            if inp.uses_washer_weighing and split_part == 1:
                state.weighed_count += 1
            loads_started += 1

    if (
        state.sorted_count >= inp.bag_count
        and state.sorted_pool
        and _can_start_wash(state, inp, strategy)
        and state.next_wash_order >= inp.bag_count
    ):
        slot_idx = min(range(len(state.washer_free_at)), key=lambda i: state.washer_free_at[i])
        free_at = state.washer_free_at[slot_idx]
        if free_at <= state.minute:
            chunk_entries = list(state.sorted_pool)
            oid, weight = chunk_entries[0]
            prep = _washer_prep_minutes(inp, 1)
            start = max(state.minute, free_at) + prep
            end = start + inp.wash_cycle_min
            load = WashLoad(
                load_id=state.next_load_id,
                washer_id=slot_idx + 1,
                order_id=oid,
                bag_start=oid,
                bag_end=oid,
                bags=1,
                pounds=round(weight, 1),
                wash_start=start,
                wash_end=end,
            )
            state.next_load_id += 1
            state.loads.append(load)
            state.sorted_pool = []
            state.washer_free_at[slot_idx] = end
            if inp.uses_washer_weighing:
                state.weighed_count += 1


def _release_to_dryers(state: SimState, inp: PlannerInputs) -> None:
    for load in state.loads:
        if load.wash_end == state.minute:
            _maybe_queue_dryer_jobs(state, inp, load)

    ready_jobs = [job for job in state.pending_dryer_jobs if job.ready_at <= state.minute]
    ready_jobs.sort(key=lambda job: (job.ready_at, job.order_id, job.split_part or 0))
    for job in list(ready_jobs):
        slot_idx = min(range(len(state.dryer_free_at)), key=lambda i: state.dryer_free_at[i])
        free_at = state.dryer_free_at[slot_idx]
        start = max(state.minute, free_at, job.ready_at)
        end = start + inp.dry_cycle_min
        cycle = DryCycle(
            cycle_id=state.next_dry_cycle_id,
            order_id=job.order_id,
            bag_start=job.bag_start,
            bag_end=job.bag_end,
            bags=job.bags,
            pounds=job.pounds,
            dry_start=start,
            dry_end=end,
            dryer_id=slot_idx + 1,
            split_part=job.split_part,
        )
        state.next_dry_cycle_id += 1
        state.dry_cycles.append(cycle)
        state.dryer_free_at[slot_idx] = end
        state.pending_dryer_jobs.remove(job)


def _release_to_fold(state: SimState, inp: PlannerInputs) -> None:
    for cycle in state.dry_cycles:
        if cycle.dry_end != state.minute:
            continue
        order_id = cycle.order_id
        state.order_dryer_finished[order_id] = state.order_dryer_finished.get(order_id, 0) + 1
        expected = inp.order_dryer_loads[order_id - 1]
        if state.order_dryer_finished[order_id] >= expected:
            state.ready_for_fold += 1


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
    if strategy == "dryer_push" and state.pause_new_wash and not state.pending_dryer_jobs:
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


def _build_dryer_timeline(dry_cycles: list[DryCycle], inp: PlannerInputs) -> list[dict[str, Any]]:
    lanes: list[list[dict[str, Any]]] = [[] for _ in range(inp.dryer_count)]
    end_minute = max((cycle.dry_end for cycle in dry_cycles), default=inp.start_min)
    for cycle in dry_cycles:
        lanes[cycle.dryer_id - 1].append(
            {
                "load_id": cycle.cycle_id,
                "label": (
                    f"Dryer {cycle.dryer_id}: {_minutes_to_label(cycle.dry_start)}-"
                    f"{_minutes_to_label(cycle.dry_end)} | Order {cycle.order_id} | "
                    f"{cycle.pounds} lb"
                ),
                "dryer_id": cycle.dryer_id,
                "start": _minutes_to_label(cycle.dry_start),
                "end": _minutes_to_label(cycle.dry_end),
                "bag_start": cycle.bag_start,
                "bag_end": cycle.bag_end,
                "bags": cycle.bags,
                "pounds": cycle.pounds,
                "order_id": cycle.order_id,
                "status": (
                    "drying"
                    if cycle.dry_start <= end_minute < cycle.dry_end
                    else "ready_to_fold"
                    if end_minute >= cycle.dry_end
                    else "waiting"
                ),
            }
        )
    return [
        {"dryer_id": i + 1, "loads": lane}
        for i, lane in enumerate(lanes)
        if lane
    ]


@dataclass
class ResourceSlot:
    busy_minutes: int = 0
    total_minutes: int = 0

    @property
    def idle_minutes(self) -> int:
        return max(0, self.total_minutes - self.busy_minutes)

    @property
    def utilization_pct(self) -> float:
        if self.total_minutes <= 0:
            return 0.0
        return round(100.0 * self.busy_minutes / self.total_minutes, 1)


class UtilizationTracker:
    def __init__(self, inp: PlannerInputs) -> None:
        self.slots: dict[str, ResourceSlot] = {}
        if inp.uses_dedicated_weigher and inp.weigher_count > 0:
            self.slots["weigher"] = ResourceSlot()
        if inp.sorter_count > 0:
            self.slots["sorter"] = ResourceSlot()
        self.slots["washer_person"] = ResourceSlot()
        if inp.folder_count > 0:
            self.slots["folders"] = ResourceSlot()
        for i in range(1, inp.washer_count + 1):
            self.slots[f"washer_{i}"] = ResourceSlot()
        for i in range(1, inp.dryer_count + 1):
            self.slots[f"dryer_{i}"] = ResourceSlot()

    def tick_legacy(self, state: SimState, inp: PlannerInputs) -> None:
        for slot in self.slots.values():
            slot.total_minutes += 1
        if inp.uses_dedicated_weigher and "weigher" in self.slots:
            if state.incoming_bags and state.minute >= inp.start_min:
                self.slots["weigher"].busy_minutes += 1
        if "sorter" in self.slots and _sorter_can_work(state, inp):
            if state.sort_queue or (
                inp.uses_dedicated_weigher and state.weigh_queue
            ) or (not inp.uses_dedicated_weigher and state.sort_queue):
                if state.sort_queue:
                    self.slots["sorter"].busy_minutes += 1
                elif state.sorter_on_break_until is None or state.minute >= state.sorter_on_break_until:
                    if state.sort_queue or (
                        inp.weighing_handled_by != "dedicated_weigher" and state.incoming_bags
                    ):
                        pass
        if "sorter" in self.slots:
            on_break = state.sorter_on_break_until is not None and state.minute < state.sorter_on_break_until
            sorting_active = state.sort_queue and _sorter_can_work(state, inp) and not on_break
            if sorting_active and state.sort_remainder > 0:
                self.slots["sorter"].busy_minutes += 1
        for i, free_at in enumerate(state.washer_free_at, start=1):
            key = f"washer_{i}"
            if key in self.slots:
                for ld in state.loads:
                    if ld.washer_id == i and ld.wash_start <= state.minute < ld.wash_end:
                        self.slots[key].busy_minutes += 1
                        break
        for i, free_at in enumerate(state.dryer_free_at, start=1):
            key = f"dryer_{i}"
            if key in self.slots:
                for cycle in state.dry_cycles:
                    if cycle.dryer_id == i and cycle.dry_start <= state.minute < cycle.dry_end:
                        self.slots[key].busy_minutes += 1
                        break
        if state.ready_for_fold > 0 and inp.folder_count > 0 and "folders" in self.slots:
            self.slots["folders"].busy_minutes += 1

    def tick_operational(self, state: OpSimState, inp: PlannerInputs) -> None:
        for slot in self.slots.values():
            slot.total_minutes += 1
        if inp.uses_dedicated_weigher and "weigher" in self.slots:
            if state.incoming_bags and state.minute >= inp.start_min:
                self.slots["weigher"].busy_minutes += 1
        if "sorter" in self.slots:
            on_break = state.sorter_on_break_until is not None and state.minute < state.sorter_on_break_until
            if state.sort_queue and _sorter_can_work_op(state, inp) and not on_break:
                self.slots["sorter"].busy_minutes += 1
        if state.washer_person_busy:
            self.slots["washer_person"].busy_minutes += 1
        for ld in state.loads:
            key = f"washer_{ld.washer_id}"
            if key in self.slots and ld.wash_start <= state.minute < ld.wash_end:
                self.slots[key].busy_minutes += 1
            if ld.dryer_id is not None and ld.dry_start is not None and ld.dry_end is not None:
                dkey = f"dryer_{ld.dryer_id}"
                if dkey in self.slots and ld.dry_start <= state.minute < ld.dry_end:
                    self.slots[dkey].busy_minutes += 1
        if state.ready_for_fold > 0 and inp.folder_count > 0 and "folders" in self.slots:
            self.slots["folders"].busy_minutes += 1

    def to_list(self) -> list[dict[str, Any]]:
        rows = []
        for name, slot in self.slots.items():
            idle_pct = round(100.0 - slot.utilization_pct, 1)
            rows.append(
                {
                    "resource": name,
                    "busy_minutes": slot.busy_minutes,
                    "idle_minutes": slot.idle_minutes,
                    "total_minutes": slot.total_minutes,
                    "utilization_pct": slot.utilization_pct,
                    "idle_pct": idle_pct,
                    "is_bottleneck": slot.utilization_pct >= 85,
                    "has_excess_idle": idle_pct >= 40 and slot.total_minutes >= 30,
                }
            )
        rows.sort(key=lambda r: (-r["utilization_pct"], r["resource"]))
        return rows

    def primary_bottleneck(self) -> str | None:
        busy = [r for r in self.to_list() if r["is_bottleneck"]]
        return busy[0]["resource"] if busy else None


def _sorter_can_work_op(state: OpSimState, inp: PlannerInputs) -> bool:
    if state.sorter_on_break_until is not None and state.minute < state.sorter_on_break_until:
        return False
    earliest = inp.start_min - inp.sorter_early_start_min
    return state.minute >= earliest


def _maybe_trigger_washer_break(state: OpSimState, inp: PlannerInputs) -> None:
    if (
        inp.washer_break_after_bags > 0
        and inp.washer_break_duration_min > 0
        and state.washer_bags_since_break >= inp.washer_break_after_bags
        and not state.washer_person_busy
    ):
        state.washer_on_break_until = state.minute + inp.washer_break_duration_min
        state.washer_bags_since_break = 0
        state.washer_person_free_at = state.washer_on_break_until


def _washer_person_available(state: OpSimState, inp: PlannerInputs) -> bool:
    if state.washer_on_break_until is not None and state.minute < state.washer_on_break_until:
        return False
    return not state.washer_person_busy and state.minute >= state.washer_person_free_at


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

    if inp.weighing_mode == "during_sort":
        add("Weighing on sorters — sort capacity reduced by weigh time per bag")
    elif inp.weighing_mode == "upfront" and inp.weighing_handled_by == "washer":
        add("Upfront weighing by washer person — sorting starts after all bags weighed")
    elif inp.weighing_mode == "upfront":
        add("Upfront weigh-all — sorting blocked until every bag is weighed")
    elif inp.weighing_mode == "separate_lane":
        add("Separate weigh lane — dedicated weigher feeds sorting continuously")

    for line in inp.split_distribution.get("summary_lines", []):
        add(line)

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
    util = UtilizationTracker(inp)
    milestone_mins = {
        t: _minutes_to_label(t) for t in _milestone_minutes(inp.start_min, inp.target_min)
    }
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
        util.tick_legacy(state, inp)

        washed_orders = len(
            {
                ld.order_id
                for ld in state.loads
                if ld.wash_end <= t
                and state.order_wash_finished.get(ld.order_id, 0)
                >= inp.order_washer_loads[ld.order_id - 1]
            }
        )
        dried_bags = _bags_dried_complete(state, inp)

        if first_ready_min is None and state.ready_for_fold > 0:
            first_ready_min = min(cycle.dry_end for cycle in state.dry_cycles)
        if (
            all_wash_done_min is None
            and len(state.loads) >= inp.total_wash_loads
            and washed_orders >= inp.bag_count
            and not state.pending_dryer_jobs
        ):
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
            "total_dryer_loads": inp.total_dryer_loads,
            "avg_bags_per_wash_load": round(inp.avg_bags_per_wash_load, 2),
            "estimated_load_plan": estimated_loads[:8],
        },
        "washer_timeline": _build_washer_timeline(state.loads, inp),
        "dryer_timeline": _build_dryer_timeline(state.dry_cycles, inp),
        "resource_utilization": util.to_list(),
        "utilization_bottleneck": util.primary_bottleneck(),
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


@dataclass
class OrderTrack:
    order_id: int
    weight_lb: float
    weigh_start: int | None = None
    weigh_end: int | None = None
    sort_start: int | None = None
    sort_end: int | None = None
    washer_id: int | None = None
    washer_load_id: int | None = None
    wash_start: int | None = None
    wash_end: int | None = None
    wait_before_dryer_end: int | None = None
    dryer_id: int | None = None
    dryer_load_id: int | None = None
    dry_start: int | None = None
    dry_end: int | None = None
    ready_to_fold: int | None = None
    fold_start: int | None = None
    fold_end: int | None = None
    completed: int | None = None


@dataclass
class OpLoad:
    load_id: int
    washer_id: int
    order_id: int
    bag_ids: list[int]
    pounds: float
    wash_start: int
    wash_end: int
    dryer_id: int | None = None
    dry_start: int | None = None
    dry_end: int | None = None
    wash_loaded_end: int | None = None
    transfer_end: int | None = None
    dryer_loaded_end: int | None = None
    dryer_split_part: int | None = None


@dataclass
class OpSimState:
    minute: int
    orders: list[OrderTrack]
    incoming_bags: list[float]
    weigh_queue: list[tuple[int, float]]
    sort_queue: list[tuple[int, float]]
    sorted_pool: list[tuple[int, float]]
    sorted_count: int = 0
    weighed_count: int = 0
    next_bag_index: int = 1
    weigh_remainder: float = 0.0
    sort_remainder: float = 0.0
    fold_remainder: float = 0.0
    folded: float = 0.0
    ready_for_fold: float = 0.0
    washer_free_at: list[int] = field(default_factory=list)
    dryer_free_at: list[int] = field(default_factory=list)
    loads: list[OpLoad] = field(default_factory=list)
    finished_wash_queue: list[OpLoad] = field(default_factory=list)
    next_load_id: int = 1
    washer_person_free_at: int = 0
    washer_person_busy: bool = False
    washer_person_task: str | None = None
    washer_person_task_end: int = 0
    washer_person_task_load_id: int | None = None
    pending_washer_tasks: list[tuple[str, int | None, int | None, int | None]] = field(
        default_factory=list
    )
    washer_person_log: list[dict[str, Any]] = field(default_factory=list)
    next_actions: list[dict[str, Any]] = field(default_factory=list)
    sorting_paused: bool = False
    batch_target: int = 0
    batch_sorted: int = 0
    batch_number: int = 1
    batch_wash_started: bool = False
    first_wash_start: int | None = None
    first_unload_return: int | None = None
    switch_to_folding_min: int | None = None
    sorting_continues: bool = True
    washer_pauses_for_moves: bool = False
    next_wash_cycle_idx: int = 0
    order_pool_consumed: set[int] = field(default_factory=set)
    orders_wash_weighed: set[int] = field(default_factory=set)
    order_wash_unloaded: dict[int, int] = field(default_factory=dict)
    order_dryer_scheduled: dict[int, int] = field(default_factory=dict)
    pending_dryer_jobs: list[DryerJob] = field(default_factory=list)
    sorter_bags_since_break: int = 0
    sorter_on_break_until: int | None = None
    washer_bags_since_break: int = 0
    washer_on_break_until: int | None = None


def _init_op_state(inp: PlannerInputs) -> OpSimState:
    orders = [
        OrderTrack(order_id=i + 1, weight_lb=inp.bag_weights[i])
        for i in range(inp.bag_count)
    ]
    state = OpSimState(
        minute=inp.start_min,
        orders=orders,
        incoming_bags=list(inp.bag_weights),
        weigh_queue=[],
        sort_queue=[],
        sorted_pool=[],
        washer_free_at=[inp.start_min] * inp.washer_count,
        dryer_free_at=[inp.start_min] * inp.dryer_count,
        washer_person_free_at=inp.start_min,
        batch_target=inp.batch_size,
    )
    if inp.uses_dedicated_weigher:
        state.incoming_bags = list(inp.bag_weights)
    elif inp.weighing_mode == "upfront":
        state.incoming_bags = list(inp.bag_weights)
    else:
        state.sort_queue = [(i + 1, inp.bag_weights[i]) for i in range(inp.bag_count)]
        state.incoming_bags = []
    return state


def _mark_order_weighed(order: OrderTrack, state: OpSimState, inp: PlannerInputs) -> None:
    weigh_end = state.minute
    weigh_start = max(inp.start_min, weigh_end - max(1, int(math.ceil(inp.weigh_min_per_bag))))
    order.weigh_start = weigh_start
    order.weigh_end = weigh_end
    state.weighed_count += 1


def _upfront_weigh_rate(inp: PlannerInputs) -> float:
    if inp.weighing_handled_by == "dedicated_weigher":
        return inp.weigher_count / inp.weigh_min_per_bag if inp.weigher_count > 0 else 0.0
    if inp.weighing_handled_by == "sorter":
        return inp.sorter_count / inp.weigh_min_per_bag if inp.sorter_count > 0 else 0.0
    return 1.0 / inp.weigh_min_per_bag


def _order_by_id(state: OpSimState, order_id: int) -> OrderTrack:
    return state.orders[order_id - 1]


def _add_next_action(
    state: OpSimState,
    start: int,
    end: int,
    action: str,
    *,
    category: str = "general",
) -> None:
    if end <= start:
        end = start + 1
    block = {
        "start": _minutes_to_label(start),
        "end": _minutes_to_label(end),
        "start_minute": start,
        "end_minute": end,
        "action": action,
        "category": category,
    }
    if state.next_actions and state.next_actions[-1]["action"] == action:
        prev = state.next_actions[-1]
        if prev["end_minute"] == start:
            prev["end"] = block["end"]
            prev["end_minute"] = end
            return
    state.next_actions.append(block)


def _log_washer_person(
    state: OpSimState,
    task: str,
    start: int,
    end: int,
    *,
    load_id: int | None = None,
    label: str = "",
) -> None:
    state.washer_person_log.append(
        {
            "task": task,
            "start": _minutes_to_label(start),
            "end": _minutes_to_label(end),
            "start_minute": start,
            "end_minute": end,
            "load_id": load_id,
            "label": label or task.replace("_", " "),
        }
    )


def _step_op_weigh_sort(state: OpSimState, inp: PlannerInputs, *, allow_sort: bool) -> None:
    if inp.uses_dedicated_weigher and state.incoming_bags and inp.weigher_count > 0 and state.minute >= inp.start_min:
        state.weigh_remainder += inp.weigher_count / inp.weigh_min_per_bag
        while state.weigh_remainder >= 1 and state.incoming_bags:
            weight = state.incoming_bags.pop(0)
            oid = state.next_bag_index
            state.next_bag_index += 1
            order = _order_by_id(state, oid)
            sort_start = state.minute
            weigh_end = state.minute
            weigh_start = max(inp.start_min, weigh_end - max(1, int(math.ceil(inp.weigh_min_per_bag))))
            order.weigh_start = weigh_start
            order.weigh_end = weigh_end
            order.sort_start = sort_start
            state.weigh_queue.append((oid, weight))
            state.weighed_count += 1
            state.weigh_remainder -= 1

    if state.weigh_queue and inp.uses_dedicated_weigher:
        while state.weigh_queue:
            oid, weight = state.weigh_queue.pop(0)
            order = _order_by_id(state, oid)
            if order.sort_start is None:
                order.sort_start = state.minute
            state.sort_queue.append((oid, weight))

    on_sorter_break = state.sorter_on_break_until is not None and state.minute < state.sorter_on_break_until
    if (
        allow_sort
        and state.sort_queue
        and inp.sorter_count > 0
        and not state.sorting_paused
        and _sorter_can_work_op(state, inp)
        and not on_sorter_break
    ):
        state.sort_remainder += inp.sorter_count / inp.effective_sort_min_per_bag
        while state.sort_remainder >= 1 and state.sort_queue:
            oid, weight = state.sort_queue.pop(0)
            order = _order_by_id(state, oid)
            if order.sort_start is None:
                order.sort_start = state.minute
            order.sort_end = state.minute
            state.sorted_pool.append((oid, weight))
            state.sorted_count += 1
            state.sort_remainder -= 1
            state.batch_sorted += 1
            state.sorter_bags_since_break += 1
            if inp.weighing_handled_by == "sorter":
                order.weigh_start = order.sort_start
                order.weigh_end = order.sort_end
                state.weighed_count += 1
            if inp.sorter_break_after_bags > 0 and state.sorter_bags_since_break >= inp.sorter_break_after_bags:
                state.sorter_on_break_until = state.minute + inp.sorter_break_duration_min
                state.sorter_bags_since_break = 0
                break
            if not state.sorting_continues and state.batch_sorted >= state.batch_target:
                state.sorting_paused = True
                break


def _washer_person_idle(state: OpSimState, inp: PlannerInputs) -> bool:
    return _washer_person_available(state, inp)


def _start_washer_person_task(
    state: OpSimState,
    inp: PlannerInputs,
    task: str,
    duration: int,
    *,
    load_id: int | None = None,
    label: str = "",
) -> None:
    start = max(state.minute, state.washer_person_free_at)
    end = start + max(1, duration)
    state.washer_person_busy = True
    state.washer_person_task = task
    state.washer_person_task_end = end
    state.washer_person_task_load_id = load_id
    state.washer_person_free_at = end
    _log_washer_person(state, task, start, end, load_id=load_id, label=label)


def _complete_washer_person_task(state: OpSimState, inp: PlannerInputs) -> None:
    if not state.washer_person_busy or state.minute < state.washer_person_task_end:
        return
    task = state.washer_person_task
    load_id = state.washer_person_task_load_id
    state.washer_person_busy = False
    state.washer_person_task = None
    state.washer_person_task_load_id = None

    load = next((ld for ld in state.loads if ld.load_id == load_id), None) if load_id else None

    if task == "load_washer" and load:
        load.wash_loaded_end = state.washer_person_task_end
        for oid in load.bag_ids:
            order = _order_by_id(state, oid)
            order.washer_id = load.washer_id
            order.washer_load_id = load.load_id
            order.wash_start = load.wash_start
            order.wash_end = load.wash_end
        if state.first_wash_start is None:
            state.first_wash_start = load.wash_start
            _add_next_action(
                state,
                load.wash_start - inp.load_washer_min,
                load.wash_start,
                f"Start wash batch {state.batch_number} ({len(load.bag_ids)} bags)",
                category="wash",
            )
    elif task == "unload_transfer" and load:
        load.transfer_end = state.washer_person_task_end
        order_id = load.order_id
        state.order_wash_unloaded[order_id] = state.order_wash_unloaded.get(order_id, 0) + 1
        for oid in load.bag_ids:
            order = _order_by_id(state, oid)
            order.wait_before_dryer_end = state.washer_person_task_end
        if state.first_unload_return is None:
            state.first_unload_return = state.washer_person_task_end
            _add_next_action(
                state,
                state.washer_person_task_end - inp.unload_washer_min - inp.washer_transfer_min,
                state.washer_person_task_end,
                f"Unload & move load {load.load_id} to dryers",
                category="transfer",
            )
        expected_wash = inp.order_washer_loads[order_id - 1]
        if state.order_wash_unloaded[order_id] >= expected_wash:
            ready_at = state.washer_person_task_end
            dryer_count = inp.order_dryer_loads[order_id - 1]
            for part in range(1, dryer_count + 1):
                state.pending_washer_tasks.append(("load_dryer", load.load_id, order_id, part))
        state.washer_pauses_for_moves = True
    elif task == "load_dryer" and load:
        load.dryer_loaded_end = state.washer_person_task_end
        for oid in load.bag_ids:
            order = _order_by_id(state, oid)
            order.dryer_id = load.dryer_id
            order.dryer_load_id = load.load_id
            order.dry_start = load.dry_start
            order.dry_end = load.dry_end
        _maybe_trigger_washer_break(state, inp)


def _schedule_washer_person(state: OpSimState, inp: PlannerInputs, *, batch_mode: bool) -> None:
    if state.washer_person_busy:
        return

    # Priority 1: load dryers for transferred loads
    while _washer_person_idle(state, inp) and state.pending_washer_tasks:
        task_name, load_id, order_id, split_part = state.pending_washer_tasks.pop(0)
        if task_name != "load_dryer":
            state.pending_washer_tasks.insert(0, (task_name, load_id, order_id, split_part))
            break
        load = next((ld for ld in state.loads if ld.load_id == load_id), None)
        if load is None:
            continue
        if load.dry_start is not None and (split_part or 1) <= 1:
            continue
        slot_idx = min(range(len(state.dryer_free_at)), key=lambda i: state.dryer_free_at[i])
        dryer_free = state.dryer_free_at[slot_idx]
        start_after_load = max(state.minute, state.washer_person_free_at, dryer_free)
        dry_start = start_after_load + inp.load_dryer_min
        dry_end = dry_start + inp.dry_cycle_min
        if split_part and split_part > 1:
            dry_load = OpLoad(
                load_id=state.next_load_id,
                washer_id=load.washer_id,
                order_id=load.order_id,
                bag_ids=list(load.bag_ids),
                pounds=load.pounds,
                wash_start=load.wash_start,
                wash_end=load.wash_end,
                dryer_split_part=split_part,
            )
            state.next_load_id += 1
            state.loads.append(dry_load)
            load = dry_load
        load.dryer_id = slot_idx + 1
        load.dry_start = dry_start
        load.dry_end = dry_end
        state.dryer_free_at[slot_idx] = dry_end
        _start_washer_person_task(
            state,
            inp,
            "load_dryer",
            inp.load_dryer_min,
            load_id=load.load_id,
            label=f"Load dryer D{load.dryer_id} · order {load.order_id}",
        )
        _add_next_action(
            state,
            start_after_load,
            start_after_load + inp.load_dryer_min,
            f"Load dryer D{load.dryer_id} · order {load.order_id}",
            category="dryer",
        )
        return

    # Priority 2: unload finished wash loads
    ready = [ld for ld in state.finished_wash_queue if ld.wash_end <= state.minute]
    ready.sort(key=lambda ld: ld.wash_end)
    if _washer_person_idle(state, inp) and ready:
        load = ready.pop(0)
        state.finished_wash_queue.remove(load)
        _start_washer_person_task(
            state,
            inp,
            "unload_transfer",
            inp.unload_washer_min + inp.washer_transfer_min,
            load_id=load.load_id,
            label=f"Unload W{load.washer_id} → transfer load {load.load_id}",
        )
        return

    # Priority 3: load washers from sorted pool
    if batch_mode and state.sorting_paused and state.batch_sorted < state.batch_target:
        return
    if batch_mode and not state.sorting_paused and state.batch_sorted < state.batch_target:
        return

    while _washer_person_idle(state, inp) and state.next_wash_cycle_idx < inp.total_wash_loads:
        if batch_mode and state.batch_wash_started and state.finished_wash_queue:
            return
        order_id = inp.washer_cycle_orders[state.next_wash_cycle_idx]
        if order_id not in state.order_pool_consumed:
            if not state.sorted_pool or state.sorted_pool[0][0] != order_id:
                break
            oid, weight = state.sorted_pool.pop(0)
            state.order_pool_consumed.add(order_id)
        else:
            oid = order_id
            weight = inp.avg_lbs_per_bag
        slot_idx = min(range(len(state.washer_free_at)), key=lambda i: state.washer_free_at[i])
        washer_free = state.washer_free_at[slot_idx]
        if washer_free > state.minute and not batch_mode:
            break
        prep = (
            max(0, int(math.ceil(inp.weigh_min_per_bag)))
            if inp.uses_washer_weighing and order_id not in state.orders_wash_weighed
            else 0
        )
        person_start = max(state.minute, state.washer_person_free_at, washer_free)
        wash_start = person_start + inp.load_washer_min + prep
        wash_end = wash_start + inp.wash_cycle_min
        bag_ids = [oid]
        load = OpLoad(
            load_id=state.next_load_id,
            washer_id=slot_idx + 1,
            order_id=order_id,
            bag_ids=bag_ids,
            pounds=round(weight, 1),
            wash_start=wash_start,
            wash_end=wash_end,
        )
        state.next_load_id += 1
        state.loads.append(load)
        state.washer_free_at[slot_idx] = wash_end
        state.batch_wash_started = True
        state.washer_bags_since_break += 1
        state.next_wash_cycle_idx += 1
        if inp.uses_washer_weighing and order_id not in state.orders_wash_weighed:
            state.weighed_count += 1
            state.orders_wash_weighed.add(order_id)
        _start_washer_person_task(
            state,
            inp,
            "load_washer",
            inp.load_washer_min + prep,
            load_id=load.load_id,
            label=f"Load washer W{load.washer_id} · order {order_id}",
        )
        if state.first_wash_start is None:
            bags_before = state.sorted_count - len(state.sorted_pool)
            _add_next_action(
                state,
                inp.start_min,
                person_start,
                f"Sort first {bags_before} bags",
                category="sort",
            )
        return


def _release_finished_wash(state: OpSimState) -> None:
    for load in state.loads:
        if load.wash_end == state.minute and load not in state.finished_wash_queue:
            if load.transfer_end is None:
                state.finished_wash_queue.append(load)


def _release_ready_fold(state: OpSimState, inp: PlannerInputs) -> None:
    for load in state.loads:
        if load.dry_end is not None and load.dry_end == state.minute:
            order_id = load.order_id
            state.order_dryer_scheduled[order_id] = state.order_dryer_scheduled.get(order_id, 0) + 1
            expected = inp.order_dryer_loads[order_id - 1]
            if state.order_dryer_scheduled[order_id] >= expected:
                order = _order_by_id(state, order_id)
                order.ready_to_fold = load.dry_end + inp.unload_dryer_min
                state.ready_for_fold += 1
                if state.switch_to_folding_min is None:
                    state.switch_to_folding_min = load.dry_end + inp.unload_dryer_min


def _step_op_fold(state: OpSimState, inp: PlannerInputs) -> None:
    if state.ready_for_fold <= 0 or inp.folder_count <= 0:
        return
    state.fold_remainder += inp.folder_count / inp.fold_min_per_bag
    take = min(state.ready_for_fold, state.fold_remainder)
    if take < 1:
        return
    whole = int(take)
    state.fold_remainder -= whole
    state.ready_for_fold -= whole
    state.folded += whole
    fold_end = state.minute
    fold_start = max(inp.start_min, fold_end - max(1, int(math.ceil(inp.fold_min_per_bag))))
    assigned = 0
    for order in state.orders:
        if order.ready_to_fold is not None and order.fold_end is None and order.ready_to_fold <= state.minute:
            if assigned >= whole:
                break
            order.fold_start = fold_start
            order.fold_end = fold_end
            order.completed = fold_end
            assigned += 1


def _maybe_advance_batch(state: OpSimState, inp: PlannerInputs, *, batch_mode: bool) -> None:
    if not batch_mode or not state.sorting_paused:
        return
    batch_bag_max = state.batch_number * state.batch_target
    batch_bag_min = batch_bag_max - state.batch_target + 1
    batch_order_ids = range(batch_bag_min, batch_bag_max + 1)
    wash_loads = [
        ld
        for ld in state.loads
        if ld.order_id in batch_order_ids and ld.dryer_split_part is None
    ]
    if not wash_loads:
        return
    all_transferred = all(ld.transfer_end is not None for ld in wash_loads)
    if not all_transferred:
        return
    if state.finished_wash_queue or state.pending_washer_tasks or state.washer_person_busy:
        return
    state.sorting_paused = False
    state.batch_sorted = 0
    state.batch_number += 1
    state.batch_wash_started = False
    _add_next_action(
        state,
        state.minute,
        state.minute + 5,
        f"Resume sorting · batch {state.batch_number}",
        category="sort",
    )


def _operational_max_minute(inp: PlannerInputs) -> int:
    """Run long enough to schedule and finish wash/dry for all split loads."""
    per_wash = (
        inp.load_washer_min
        + inp.wash_cycle_min
        + inp.unload_washer_min
        + inp.washer_transfer_min
        + inp.load_dryer_min
        + inp.dry_cycle_min
    )
    wash_horizon = inp.start_min + (
        inp.total_wash_loads * per_wash // max(1, inp.washer_count)
    )
    return max(inp.target_min + inp.dry_cycle_min + 120, wash_horizon + 240)


def _operational_pipeline_done(state: OpSimState, inp: PlannerInputs) -> bool:
    if state.sorted_count < inp.bag_count:
        return False
    if state.next_wash_cycle_idx < inp.total_wash_loads:
        return False
    if state.finished_wash_queue or state.pending_washer_tasks or state.washer_person_busy:
        return False
    pending_dry = any(ld.dry_start is None and ld.wash_end <= state.minute for ld in state.loads)
    return not pending_dry


def _build_order_timeline(state: OpSimState, inp: PlannerInputs) -> list[dict[str, Any]]:
    loads_by_order: dict[int, list[OpLoad]] = {}
    for ld in state.loads:
        loads_by_order.setdefault(ld.order_id, []).append(ld)

    rows: list[dict[str, Any]] = []
    for order in state.orders:
        order_loads = loads_by_order.get(order.order_id, [])
        wash_loads = sorted(
            [ld for ld in order_loads if ld.dryer_split_part is None],
            key=lambda ld: (ld.wash_start or 0, ld.load_id),
        )
        dry_loads = sorted(
            [ld for ld in order_loads if ld.dry_start is not None],
            key=lambda ld: (ld.dry_start or 0, ld.load_id),
        )
        washers = [f"W{ld.washer_id}" for ld in wash_loads]
        dryers = [f"D{ld.dryer_id}" for ld in dry_loads if ld.dryer_id]
        wash_segments = [
            f"{_minutes_to_label(ld.wash_start)}–{_minutes_to_label(ld.wash_end)}"
            for ld in wash_loads
            if ld.wash_start is not None and ld.wash_end is not None
        ]
        dry_segments = [
            f"{_minutes_to_label(ld.dry_start)}–{_minutes_to_label(ld.dry_end)}"
            for ld in dry_loads
            if ld.dry_start is not None and ld.dry_end is not None
        ]
        bottleneck = _order_bottleneck_stage(order, state.minute, inp)
        rows.append(
            {
                "order": order.order_id,
                "weight_lb": order.weight_lb,
                "weigh_start": _minutes_to_label(order.weigh_start) if order.weigh_start else None,
                "weigh_end": _minutes_to_label(order.weigh_end) if order.weigh_end else None,
                "sort_start": _minutes_to_label(order.sort_start) if order.sort_start else None,
                "sort_end": _minutes_to_label(order.sort_end) if order.sort_end else None,
                "sorted_time": _minutes_to_label(order.sort_end) if order.sort_end else None,
                "washer": " + ".join(washers) if washers else None,
                "washers": washers,
                "washer_load": order.washer_load_id,
                "wash_start": wash_segments[0].split("–")[0] if wash_segments else None,
                "wash_end": wash_segments[-1].split("–")[-1] if wash_segments else None,
                "wash_segments": wash_segments,
                "dryer": " + ".join(dryers) if dryers else None,
                "dryers": dryers,
                "dryer_load": order.dryer_load_id,
                "dry_start": dry_segments[0].split("–")[0] if dry_segments else None,
                "dry_end": dry_segments[-1].split("–")[-1] if dry_segments else None,
                "dry_segments": dry_segments,
                "ready_fold": _minutes_to_label(order.ready_to_fold) if order.ready_to_fold else None,
                "fold_start": _minutes_to_label(order.fold_start) if order.fold_start else None,
                "fold_end": _minutes_to_label(order.fold_end) if order.fold_end else None,
                "completed": _minutes_to_label(order.completed) if order.completed else None,
                "bottleneck": bottleneck,
            }
        )
    return rows


def _order_bottleneck_stage(order: OrderTrack, minute: int, inp: PlannerInputs) -> str:
    if order.completed is not None and order.completed <= minute:
        return "none"
    if order.fold_start is not None and order.fold_end is None:
        return "folding"
    if order.ready_to_fold is not None and order.ready_to_fold <= minute and order.fold_end is None:
        return "folding"
    if order.dry_start is not None and (order.dry_end is None or minute < order.dry_end):
        return "drying"
    if order.wait_before_dryer_end is not None and order.dry_start is None:
        return "waiting_dryer"
    if order.wash_start is not None and (order.wash_end is None or minute < order.wash_end):
        return "washing"
    if order.sort_end is None and order.sort_start is not None:
        return "sorting"
    if order.sort_end is None:
        return "sorting"
    if order.wash_start is None:
        return "washing"
    if order.dry_start is None:
        return "waiting_dryer"
    return "none"


def _build_op_washer_timeline(loads: list[OpLoad], inp: PlannerInputs) -> list[dict[str, Any]]:
    lanes: list[list[dict[str, Any]]] = [[] for _ in range(inp.washer_count)]
    for ld in loads:
        lanes[ld.washer_id - 1].append(
            {
                "load_id": ld.load_id,
                "label": (
                    f"W{ld.washer_id} L{ld.load_id}: "
                    f"{_minutes_to_label(ld.wash_start)}–{_minutes_to_label(ld.wash_end)} · "
                    f"Bags {ld.bag_ids[0]}–{ld.bag_ids[-1]}"
                ),
                "washer_id": ld.washer_id,
                "load_number": ld.load_id,
                "start": _minutes_to_label(ld.wash_start),
                "end": _minutes_to_label(ld.wash_end),
                "bag_start": ld.bag_ids[0],
                "bag_end": ld.bag_ids[-1],
                "bags": len(ld.bag_ids),
                "pounds": ld.pounds,
            }
        )
    return [{"washer_id": i + 1, "loads": lane} for i, lane in enumerate(lanes) if lane]


def _build_op_dryer_timeline(loads: list[OpLoad], inp: PlannerInputs) -> list[dict[str, Any]]:
    lanes: list[list[dict[str, Any]]] = [[] for _ in range(inp.dryer_count)]
    for ld in loads:
        if ld.dryer_id is None or ld.dry_start is None:
            continue
        lanes[ld.dryer_id - 1].append(
            {
                "load_id": ld.load_id,
                "label": (
                    f"D{ld.dryer_id} L{ld.load_id}: "
                    f"{_minutes_to_label(ld.dry_start)}–{_minutes_to_label(ld.dry_end or ld.dry_start)} · "
                    f"Bags {ld.bag_ids[0]}–{ld.bag_ids[-1]}"
                ),
                "dryer_id": ld.dryer_id,
                "load_number": ld.load_id,
                "start": _minutes_to_label(ld.dry_start),
                "end": _minutes_to_label(ld.dry_end) if ld.dry_end else None,
                "bag_start": ld.bag_ids[0],
                "bag_end": ld.bag_ids[-1],
                "bags": len(ld.bag_ids),
                "pounds": ld.pounds,
            }
        )
    return [{"dryer_id": i + 1, "loads": lane} for i, lane in enumerate(lanes) if lane]


def _build_op_bottleneck_alerts(state: OpSimState, inp: PlannerInputs) -> list[str]:
    alerts: list[str] = []
    if state.finished_wash_queue:
        alerts.append(
            f"{len(state.finished_wash_queue)} wash load(s) waiting — washer person unload/transfer"
        )
    if state.pending_washer_tasks:
        alerts.append(f"{len(state.pending_washer_tasks)} dryer load(s) queued for washer person")
    if len(state.sorted_pool) > inp.washer_count * 2 and state.washer_person_busy:
        alerts.append("Sorted backlog — washer person busy with transfers")
    if state.sorting_paused and state.batch_sorted >= state.batch_target:
        alerts.append(f"Batch {state.batch_number}: sorting paused at {state.batch_target} bags")
    waiting_dry = sum(
        1 for ld in state.loads if ld.dry_start is None and ld.wash_end <= state.minute
    )
    if waiting_dry >= inp.dryer_count:
        alerts.append(f"{waiting_dry} loads waiting for dryer — move faster")
    return alerts[:6]


def _build_bag_availability_forecast(state: OpSimState) -> dict[str, Any]:
    """Sorted-bag count delta between first wash start and the next batch wash start."""
    first_wash = state.first_wash_start
    batch_size = state.batch_target
    if first_wash is None or batch_size <= 0:
        return {}

    bags_at_first = sum(
        1 for o in state.orders if o.sort_end is not None and o.sort_end <= first_wash
    )

    next_batch_wash: int | None = None
    if batch_size < len(state.orders):
        next_order = state.orders[batch_size]
        next_batch_wash = next_order.wash_start

    if next_batch_wash is None:
        wash_starts = sorted({ld.wash_start for ld in state.loads if ld.wash_start is not None})
        if len(wash_starts) > batch_size:
            next_batch_wash = wash_starts[batch_size]

    bags_by_next: int | None = None
    additional: int | None = None
    if next_batch_wash is not None:
        bags_by_next = sum(
            1 for o in state.orders if o.sort_end is not None and o.sort_end <= next_batch_wash
        )
        additional = max(0, bags_by_next - bags_at_first)

    return {
        "next_wash_batch_start": _minutes_to_label(next_batch_wash) if next_batch_wash else None,
        "bags_sorted_at_first_wash": bags_at_first,
        "bags_sorted_by_next_batch": bags_by_next,
        "additional_bags_by_next_batch": additional,
        "forecast_batch_size": batch_size,
    }


def _build_op_guidance(state: OpSimState, inp: PlannerInputs, *, batch_mode: bool) -> dict[str, Any]:
    bags_before_first = 0
    if state.first_wash_start is not None:
        bags_before_first = sum(
            1 for o in state.orders if o.sort_end is not None and o.sort_end <= state.first_wash_start
        )
    guidance = {
        "recommended_first_batch_size": state.batch_target,
        "first_wash_batch_start": _minutes_to_label(state.first_wash_start)
        if state.first_wash_start
        else None,
        "washer_return_to_unload": _minutes_to_label(state.first_unload_return)
        if state.first_unload_return
        else None,
        "bags_sorted_before_first_wash": bags_before_first,
        "sorting_continues_while_washing": state.sorting_continues and not batch_mode,
        "washer_pauses_for_dryer_moves": state.washer_pauses_for_moves,
        "switch_labor_to_folding": _minutes_to_label(state.switch_to_folding_min)
        if state.switch_to_folding_min
        else None,
    }
    guidance.update(_build_bag_availability_forecast(state))
    return guidance


def _count_sorted_at(state: OpSimState, minute: int) -> int:
    return sum(1 for o in state.orders if o.sort_end is not None and o.sort_end <= minute)


def _count_sorted_available_at(state: OpSimState, minute: int) -> int:
    """Bags finished sorting and waiting for washer pickup (sorter lane → washer lane handoff)."""
    return sum(
        1
        for o in state.orders
        if o.sort_end is not None
        and o.sort_end <= minute
        and (o.wash_start is None or o.wash_start > minute)
    )


def _count_ready_to_fold_at(state: OpSimState, minute: int) -> int:
    return sum(
        1
        for o in state.orders
        if o.ready_to_fold is not None
        and o.ready_to_fold <= minute
        and (o.fold_end is None or o.fold_end > minute)
    )


def _count_folded_at(state: OpSimState, minute: int) -> int:
    return sum(1 for o in state.orders if o.fold_end is not None and o.fold_end <= minute)


def _batch_dryers_loaded_at(state: OpSimState, order_ids: set[int], minute: int) -> int:
    return sum(
        1
        for ld in state.loads
        if ld.order_id in order_ids and ld.dry_start is not None and ld.dry_start <= minute
    )


def _batch_pipeline_timing(
    batch_orders: list[OrderTrack],
    wash_start_min: int,
) -> dict[str, Any]:
    """Wash → dry → ready-to-fold timing for a batch (washer/dryer lane, separate from sorter)."""
    wash_ends = [o.wash_end for o in batch_orders if o.wash_end is not None]
    dry_starts = [o.dry_start for o in batch_orders if o.dry_start is not None]
    dry_ends = [o.dry_end for o in batch_orders if o.dry_end is not None]
    ready_times = [o.ready_to_fold for o in batch_orders if o.ready_to_fold is not None]

    wash_end_min = max(wash_ends) if wash_ends else wash_start_min
    dry_start_min = min(dry_starts) if dry_starts else None
    dry_end_min = max(dry_ends) if dry_ends else None
    first_ready_min = min(ready_times) if ready_times else None
    last_ready_min = max(ready_times) if ready_times else None

    wash_duration_min = max(0, wash_end_min - wash_start_min)
    dry_duration_min = (
        max(0, dry_end_min - dry_start_min) if dry_start_min is not None and dry_end_min is not None else None
    )
    time_to_ready_to_fold_min = (
        max(0, last_ready_min - wash_start_min) if last_ready_min is not None else None
    )
    wash_to_dry_gap_min = (
        max(0, dry_start_min - wash_end_min) if dry_start_min is not None else None
    )
    dry_to_ready_gap_min = (
        max(0, first_ready_min - dry_end_min)
        if first_ready_min is not None and dry_end_min is not None
        else None
    )

    return {
        "wash_start_minute": wash_start_min,
        "wash_end_minute": wash_end_min,
        "wash_duration_min": wash_duration_min,
        "dry_start_minute": dry_start_min,
        "dry_end_minute": dry_end_min,
        "dry_duration_min": dry_duration_min,
        "first_ready_to_fold_minute": first_ready_min,
        "last_ready_to_fold_minute": last_ready_min,
        "time_to_ready_to_fold_min": time_to_ready_to_fold_min,
        "wash_to_dry_gap_min": wash_to_dry_gap_min,
        "dry_to_ready_gap_min": dry_to_ready_gap_min,
    }


def _batch_wave_dryers_complete_minute(
    state: OpSimState, inp: PlannerInputs, order_ids: set[int]
) -> int | None:
    end_min = 0
    for oid in order_ids:
        expected = inp.order_dryer_loads[oid - 1]
        dry_loads = [
            ld
            for ld in state.loads
            if ld.order_id == oid and ld.dry_start is not None
        ]
        if len(dry_loads) < expected:
            return None
        end_min = max(end_min, max(ld.dry_start for ld in dry_loads))
    return end_min


def _batch_order_groups(
    state: OpSimState,
    inp: PlannerInputs,
    *,
    wave_size: int,
    batch_mode: bool,
) -> list[tuple[int, set[int]]]:
    """Return (wave_number, order_ids) groups for milestone rows."""
    wave_size = max(1, wave_size)
    if batch_mode:
        total_waves = math.ceil(inp.bag_count / wave_size)
        return [
            (
                wave,
                set(range((wave - 1) * wave_size + 1, min(wave * wave_size, inp.bag_count) + 1)),
            )
            for wave in range(1, total_waves + 1)
        ]

    order_wash_starts = [
        (order.wash_start, order.order_id)
        for order in state.orders
        if order.wash_start is not None
    ]
    order_wash_starts.sort(key=lambda item: (item[0], item[1]))
    groups: list[tuple[int, set[int]]] = []
    for idx in range(0, len(order_wash_starts), wave_size):
        chunk = order_wash_starts[idx : idx + wave_size]
        groups.append((len(groups) + 1, {oid for _, oid in chunk}))
    return groups


def _build_batch_milestone_rows(
    state: OpSimState,
    inp: PlannerInputs,
    *,
    wave_size: int,
    batch_mode: bool,
) -> list[dict[str, Any]]:
    """Operational milestones keyed to wash batches (explicit batch mode) or wash waves (continuous)."""
    wave_size = max(1, wave_size)
    rows: list[dict[str, Any]] = []

    for wave, order_ids in _batch_order_groups(
        state, inp, wave_size=wave_size, batch_mode=batch_mode
    ):
        if not order_ids:
            continue
        order_min = min(order_ids)
        order_max = max(order_ids)
        batch_orders = [state.orders[oid - 1] for oid in sorted(order_ids)]

        wash_starts = [o.wash_start for o in batch_orders if o.wash_start is not None]
        if not wash_starts:
            continue

        wash_start_min = min(wash_starts)
        wash_ends = [o.wash_end for o in batch_orders if o.wash_end is not None]
        wash_end_min = max(wash_ends) if wash_ends else wash_start_min

        before_wash_min = max(inp.start_min, wash_start_min - 1)
        at_wash_start_min = wash_start_min
        sorted_before_wash = _count_sorted_at(state, before_wash_min)
        sorted_available_at_start = _count_sorted_available_at(state, at_wash_start_min)
        ready_to_fold_at_start = _count_ready_to_fold_at(state, at_wash_start_min)
        batch_sorted_before_wash = sum(
            1 for o in batch_orders if o.sort_end is not None and o.sort_end <= before_wash_min
        )
        left_to_sort = max(0, inp.bag_count - sorted_before_wash)
        remaining_to_sort = left_to_sort

        pipeline = _batch_pipeline_timing(batch_orders, wash_start_min)

        batch_end_min = _batch_wave_dryers_complete_minute(state, inp, order_ids)
        if batch_end_min is None:
            transfer_ends = [
                ld.transfer_end
                for ld in state.loads
                if ld.order_id in order_ids
                and ld.dryer_split_part is None
                and ld.transfer_end is not None
            ]
            if transfer_ends and len(transfer_ends) >= sum(
                1 for oid in order_ids if inp.order_washer_loads[oid - 1] > 0
            ):
                batch_end_min = max(transfer_ends)
            else:
                batch_end_min = wash_end_min

        dryers_loaded = _batch_dryers_loaded_at(state, order_ids, batch_end_min)
        ready_at_end = _count_ready_to_fold_at(state, batch_end_min)
        folded_at_end = min(inp.bag_count, _count_folded_at(state, batch_end_min))

        dry_start_min = pipeline["dry_start_minute"]
        dry_end_min = pipeline["dry_end_minute"]
        last_ready_min = pipeline["last_ready_to_fold_minute"]

        rows.append(
            {
                "batch_number": wave,
                "order_range": f"{order_min}–{order_max}",
                "orders_in_batch": len(order_ids),
                "wave_size": wave_size,
                "batch_mode": batch_mode,
                # Batch start — sorter lane vs washer handoff
                "sorted_available_at_start": sorted_available_at_start,
                "ready_to_fold_at_start": ready_to_fold_at_start,
                "left_to_sort": left_to_sort,
                "remaining_to_sort_before_wash": remaining_to_sort,
                "sorted_in_batch_before_wash": batch_sorted_before_wash,
                "cumulative_sorted_before_wash": sorted_before_wash,
                # Washer/dryer pipeline timing (separate staff from sorter)
                "wash_start": _minutes_to_label(wash_start_min),
                "wash_end": _minutes_to_label(wash_end_min),
                "wash_start_minute": wash_start_min,
                "wash_end_minute": wash_end_min,
                "wash_duration_min": pipeline["wash_duration_min"],
                "dry_start": _minutes_to_label(dry_start_min) if dry_start_min is not None else None,
                "dry_end": _minutes_to_label(dry_end_min) if dry_end_min is not None else None,
                "dry_start_minute": dry_start_min,
                "dry_end_minute": dry_end_min,
                "dry_duration_min": pipeline["dry_duration_min"],
                "ready_to_fold_at": _minutes_to_label(last_ready_min) if last_ready_min is not None else None,
                "ready_to_fold_minute": last_ready_min,
                "time_to_ready_to_fold_min": pipeline["time_to_ready_to_fold_min"],
                "wash_to_dry_gap_min": pipeline["wash_to_dry_gap_min"],
                "dry_to_ready_gap_min": pipeline["dry_to_ready_gap_min"],
                # Batch end
                "batch_end": _minutes_to_label(batch_end_min),
                "batch_end_minute": batch_end_min,
                "batch_end_time": _minutes_to_label(batch_end_min),
                "dryers_loaded": dryers_loaded,
                "ready_to_fold_at_end": ready_at_end,
                "bags_ready_to_fold": ready_at_end,
                "folded_at_end": folded_at_end,
                "bags_folded": folded_at_end,
                "cumulative_ready_to_fold": ready_at_end + folded_at_end,
                "cumulative_folded": folded_at_end,
            }
        )

    return rows


def _op_milestone_snapshot(state: OpSimState, inp: PlannerInputs) -> dict[str, Any]:
    minute = state.minute
    in_wash = sum(
        1
        for ld in state.loads
        if ld.dryer_split_part is None
        and ld.wash_start is not None
        and ld.wash_end is not None
        and ld.wash_start <= minute < ld.wash_end
    )
    in_dry = sum(
        1
        for ld in state.loads
        if ld.dry_start is not None
        and ld.dry_end is not None
        and ld.dry_start <= minute < ld.dry_end
    )
    ready_to_fold = sum(
        1
        for o in state.orders
        if o.ready_to_fold is not None
        and o.ready_to_fold <= minute
        and (o.fold_end is None or o.fold_end > minute)
    )
    folded = min(inp.bag_count, int(state.folded))
    return {
        "clock": _minutes_to_label(minute),
        "minute_offset": minute - inp.start_min,
        "bags_in_washer": in_wash,
        "bags_in_dryer": in_dry,
        "bags_ready_to_fold": ready_to_fold,
        "bags_folded": folded,
    }


def run_operational_simulation(
    inp: PlannerInputs,
    *,
    washing_strategy: WashingStrategy,
    batch_size: int | None = None,
) -> dict[str, Any]:
    batch_mode = washing_strategy == "batch_washing"
    effective_batch = batch_size if batch_size is not None else inp.batch_size
    state = _init_op_state(inp)
    state.batch_target = effective_batch
    state.sorting_continues = not batch_mode
    util = UtilizationTracker(inp)
    milestone_times = set(_milestone_minutes(inp.start_min, inp.target_min))
    milestones: dict[str, dict[str, Any]] = {}

    max_minute = _operational_max_minute(inp)

    for t in range(inp.start_min, max_minute + 1):
        state.minute = t
        _complete_washer_person_task(state, inp)
        allow_sort = not batch_mode or not state.sorting_paused or state.batch_sorted < state.batch_target
        _step_op_weigh_sort(state, inp, allow_sort=allow_sort)
        _release_finished_wash(state)
        _schedule_washer_person(state, inp, batch_mode=batch_mode)
        _complete_washer_person_task(state, inp)
        _release_ready_fold(state, inp)
        _step_op_fold(state, inp)
        _maybe_advance_batch(state, inp, batch_mode=batch_mode)
        util.tick_operational(state, inp)

        if t in milestone_times:
            milestones[_minutes_to_label(t)] = _op_milestone_snapshot(state, inp)

        if t >= inp.target_min and state.folded >= inp.bag_count:
            break
        if t >= max_minute:
            break
        if t >= inp.target_min + 180 and _operational_pipeline_done(state, inp):
            break

    guidance = _build_op_guidance(state, inp, batch_mode=batch_mode)
    batch_milestone_rows = _build_batch_milestone_rows(
        state,
        inp,
        wave_size=effective_batch,
        batch_mode=batch_mode,
    )
    time_milestone_rows = [
        {"time": clock, **milestones[clock]}
        for clock in sorted(
            milestones.keys(),
            key=lambda c: _parse_clock_minutes(c, default="12:00 PM"),
        )
    ]
    return {
        "washing_strategy": washing_strategy,
        "batch_size": effective_batch,
        "guidance": guidance,
        "milestones": milestones,
        "batch_milestone_rows": batch_milestone_rows,
        "time_milestone_rows": time_milestone_rows,
        "milestone_rows": batch_milestone_rows,
        "next_actions": sorted(state.next_actions, key=lambda a: a["start_minute"]),
        "order_timeline": _build_order_timeline(state, inp),
        "washer_timeline": _build_op_washer_timeline(state.loads, inp),
        "dryer_timeline": _build_op_dryer_timeline(state.loads, inp),
        "washer_person_timeline": state.washer_person_log,
        "bottleneck_alerts": _build_op_bottleneck_alerts(state, inp),
        "resource_utilization": util.to_list(),
        "utilization_bottleneck": util.primary_bottleneck(),
        "summary": {
            "bags_sorted": state.sorted_count,
            "bags_folded": int(state.folded),
            "first_wash_start": guidance["first_wash_batch_start"],
            "first_unload_return": guidance["washer_return_to_unload"],
            "switch_to_folding": guidance["switch_labor_to_folding"],
            "sorting_continues_while_washing": guidance["sorting_continues_while_washing"],
            "washer_pauses_for_dryer_moves": guidance["washer_pauses_for_dryer_moves"],
        },
        "final": {
            "bags_sorted": state.sorted_count,
            "bags_folded": int(state.folded),
            "bags_ready_for_folding": int(state.ready_for_fold + state.folded),
        },
    }


def _pick_optimal_batch_size(inp: PlannerInputs) -> int:
    """Pick batch size maximizing folded bags at target for batch washing."""
    best_size = inp.batch_size
    best_score: tuple[int, int] = (-1, 999999)

    for size in BATCH_SIZE_OPTIONS:
        result = run_operational_simulation(
            inp,
            washing_strategy="batch_washing",
            batch_size=size,
        )
        folded = result["final"]["bags_folded"]
        first_ready = result["guidance"].get("switch_labor_to_folding")
        first_min = _parse_clock_minutes(first_ready, default="12:00 PM") if first_ready else 9999
        score = (folded, -first_min)
        if score > best_score:
            best_score = score
            best_size = size

    return best_size


def optimize_operational_strategy(inp: PlannerInputs, operational: dict[str, Any]) -> dict[str, Any]:
    """Rules-based optimizer: batch washing vs sort-while-drying across batch sizes."""
    staffing = compute_staffing(inp)
    target_label = _minutes_to_label(inp.target_min)

    def _target_folded(result: dict[str, Any]) -> int:
        ms = result.get("milestones", {})
        if target_label in ms:
            return int(ms[target_label].get("bags_folded", 0))
        return int(result["final"]["bags_folded"])

    candidates: list[tuple[str, int, dict[str, Any]]] = []
    comparisons: dict[str, Any] = {}
    for size in BATCH_SIZE_OPTIONS:
        for key in ("batch_washing", "sort_while_drying"):
            result = run_operational_simulation(inp, washing_strategy=key, batch_size=size)  # type: ignore[arg-type]
            candidates.append((key, size, result))
            comparisons[f"{key}_{size}"] = {
                "batch_size": size,
                "bags_folded_at_target": _target_folded(result),
                "bags_folded": result["final"]["bags_folded"],
                "bags_ready": result["final"]["bags_ready_for_folding"],
                "bottleneck": result.get("utilization_bottleneck"),
                "first_fold_ready": result["guidance"].get("switch_labor_to_folding"),
            }

    def _score(item: tuple[str, int, dict[str, Any]]) -> tuple[int, int, int, int, int]:
        key, _, result = item
        switch = result["guidance"].get("switch_labor_to_folding")
        switch_min = _parse_clock_minutes(switch, default="12:00 PM") if switch else 9999
        prefer_batch = 1 if key == "batch_washing" else 0
        return (
            _target_folded(result),
            int(result["final"]["bags_folded"]),
            int(result["final"]["bags_ready_for_folding"]),
            prefer_batch,
            -switch_min,
        )

    best_key, best_batch, best_result = max(candidates, key=_score)
    meta = STRATEGY_DEFINITIONS[best_key]
    reason = meta["description"]
    if best_key == "batch_washing":
        reason = f"{meta['description']} Optimizer picked batch size {best_batch}."
    else:
        reason = (
            f"{meta['description']} Optimizer picked batch size {best_batch} because sorting "
            "can stay ahead while the washer person handles dryer loading."
        )
    suggested_staff = {
        "weighers": max(staffing["weighers"], inp.weigher_count if inp.uses_dedicated_weigher else 0),
        "sorters": max(staffing["sorters"], inp.sorter_count),
        "folders": max(staffing["folders"], inp.folder_count),
        "washers": inp.washer_count,
        "dryers": inp.dryer_count,
    }
    bn = best_result.get("utilization_bottleneck") or "none"
    if bn == "folding" and suggested_staff["folders"] < staffing["folders"] + 1:
        suggested_staff["folders"] = staffing["folders"] + 1
    if bn.startswith("washer") and inp.washer_count < staffing.get("wash_dry_helpers", 0) + inp.washer_count:
        suggested_staff["washers"] = inp.washer_count + 1
    if bn.startswith("dryer") and inp.dryer_count < staffing.get("wash_dry_helpers", 0) + inp.dryer_count:
        suggested_staff["dryers"] = inp.dryer_count + 1

    return {
        "washing_strategy": best_key,
        "batch_size": best_batch,
        "label": meta["label"],
        "reason": reason,
        "expected_bags_folded_at_target": _target_folded(best_result),
        "expected_bags_folded_total": best_result["final"]["bags_folded"],
        "expected_bags_ready": best_result["final"]["bags_ready_for_folding"],
        "main_bottleneck": bn,
        "first_fold_ready": best_result["guidance"].get("switch_labor_to_folding"),
        "suggested_staff": suggested_staff,
        "comparisons": comparisons,
        "apply_inputs": {
            "washing_strategy": best_key,
            "batch_size": best_batch,
            "folder_count": suggested_staff["folders"],
            "sorter_count": suggested_staff["sorters"],
            "weigher_count": suggested_staff["weighers"] if inp.uses_dedicated_weigher else None,
            "washer_count": suggested_staff["washers"],
            "dryer_count": suggested_staff["dryers"],
        },
    }


def build_operational_plan(inp: PlannerInputs) -> dict[str, Any]:
    recommended_batch = _pick_optimal_batch_size(inp)
    batch = run_operational_simulation(
        inp,
        washing_strategy="batch_washing",
        batch_size=inp.batch_size,
    )
    sort_drying = run_operational_simulation(
        inp,
        washing_strategy="sort_while_drying",
        batch_size=inp.batch_size,
    )

    strategies = {
        "batch_washing": batch,
        "sort_while_drying": sort_drying,
    }

    selected = inp.washing_strategy
    active = strategies[selected]
    if selected == "batch_washing":
        active["guidance"]["recommended_first_batch_size"] = recommended_batch

    return {
        "washing_strategy": selected,
        "recommended_batch_size": recommended_batch,
        "strategy_definitions": STRATEGY_DEFINITIONS,
        "strategies": strategies,
        "active_strategy": active,
        "milestones": active.get("milestones", {}),
        "milestone_rows": active.get("milestone_rows", []),
        "batch_milestone_rows": active.get("batch_milestone_rows", []),
        "time_milestone_rows": active.get("time_milestone_rows", []),
        "guidance": active["guidance"],
        "next_actions": active["next_actions"],
        "order_timeline": active["order_timeline"],
        "washer_timeline": active["washer_timeline"],
        "dryer_timeline": active["dryer_timeline"],
        "washer_person_timeline": active["washer_person_timeline"],
        "bottleneck_alerts": active["bottleneck_alerts"],
        "resource_utilization": active.get("resource_utilization", []),
        "utilization_bottleneck": active.get("utilization_bottleneck"),
        "summary": active["summary"],
        "strategy_optimizer": optimize_operational_strategy(
            inp,
            {
                "strategies": strategies,
                "recommended_batch_size": recommended_batch,
            },
        ),
    }


def _has_whatif_scenario(inp: PlannerInputs) -> bool:
    return (
        inp.sorter_early_start_min > 0
        or inp.sorter_break_after_bags > 0
        or inp.washer_break_after_bags > 0
    )


def _build_whatif_comparison(
    baseline_op: dict[str, Any],
    scenario_op: dict[str, Any],
    baseline_rec: dict[str, Any],
    scenario_rec: dict[str, Any],
) -> dict[str, Any]:
    b_sum = baseline_op.get("summary", {})
    s_sum = scenario_op.get("summary", {})
    b_folded = int(b_sum.get("bags_folded", baseline_op.get("final", {}).get("bags_folded", 0)))
    s_folded = int(s_sum.get("bags_folded", scenario_op.get("final", {}).get("bags_folded", 0)))
    return {
        "baseline": {
            "bags_folded": b_folded,
            "first_wash_start": b_sum.get("first_wash_start"),
            "switch_to_folding": b_sum.get("switch_to_folding"),
            "bottleneck": baseline_rec.get("main_bottleneck"),
            "utilization_bottleneck": baseline_op.get("utilization_bottleneck"),
        },
        "scenario": {
            "bags_folded": s_folded,
            "first_wash_start": s_sum.get("first_wash_start"),
            "switch_to_folding": s_sum.get("switch_to_folding"),
            "bottleneck": scenario_rec.get("main_bottleneck"),
            "utilization_bottleneck": scenario_op.get("utilization_bottleneck"),
        },
        "delta": {
            "bags_folded": s_folded - b_folded,
            "first_wash_start": _delta_time_label(
                b_sum.get("first_wash_start"), s_sum.get("first_wash_start")
            ),
            "switch_to_folding": _delta_time_label(
                b_sum.get("switch_to_folding"), s_sum.get("switch_to_folding")
            ),
        },
    }


def _delta_time_label(baseline: str | None, scenario: str | None) -> str | None:
    if not baseline or not scenario:
        return None
    try:
        b = _parse_clock_minutes(baseline, default="12:00 PM")
        s = _parse_clock_minutes(scenario, default="12:00 PM")
        diff = s - b
        if diff == 0:
            return "0 min"
        sign = "+" if diff > 0 else ""
        return f"{sign}{diff} min"
    except ValueError:
        return None


def simulate_shift_capacity(data: dict[str, Any] | None) -> dict[str, Any]:
    inp = parse_planner_inputs(data)
    staffing = compute_staffing(inp)
    strategies = {
        "continuous_washing": run_simulation(inp, "continuous_washing"),
        "dryer_push": run_simulation(inp, "dryer_push"),
    }
    recommendation = recommend_strategy(strategies, inp, staffing)
    recommended_key = recommendation["recommended"]
    operational = build_operational_plan(inp)

    what_if: dict[str, Any] | None = None
    if _has_whatif_scenario(inp):
        baseline_inp = replace(
            inp,
            sorter_early_start_min=0,
            sorter_break_after_bags=0,
            sorter_break_duration_min=0,
            washer_break_after_bags=0,
            washer_break_duration_min=0,
        )
        baseline_strategies = {
            "continuous_washing": run_simulation(baseline_inp, "continuous_washing"),
            "dryer_push": run_simulation(baseline_inp, "dryer_push"),
        }
        baseline_rec = recommend_strategy(baseline_strategies, baseline_inp, compute_staffing(baseline_inp))
        baseline_op = build_operational_plan(baseline_inp)
        what_if = {
            "enabled": True,
            "params": {
                "sorter_early_start_min": inp.sorter_early_start_min,
                "sorter_break_after_bags": inp.sorter_break_after_bags,
                "sorter_break_duration_min": inp.sorter_break_duration_min,
                "washer_break_after_bags": inp.washer_break_after_bags,
                "washer_break_duration_min": inp.washer_break_duration_min,
            },
            "comparison": _build_whatif_comparison(
                baseline_op["active_strategy"],
                operational["active_strategy"],
                baseline_rec,
                recommendation,
            ),
            "baseline_operational_summary": baseline_op["summary"],
        }

    return {
        "inputs": {
            "start_time": _minutes_to_label(inp.start_min),
            "target_time": _minutes_to_label(inp.target_min),
            "bag_count": inp.bag_count,
            "avg_lbs_per_bag": inp.avg_lbs_per_bag,
            "orders_using_2_washers": inp.orders_using_2_washers,
            "orders_using_2_dryers": inp.orders_using_2_dryers,
            "split_distribution": inp.split_distribution,
            "sorter_early_start_min": inp.sorter_early_start_min,
            "sorter_break_after_bags": inp.sorter_break_after_bags,
            "sorter_break_duration_min": inp.sorter_break_duration_min,
            "washer_break_after_bags": inp.washer_break_after_bags,
            "washer_break_duration_min": inp.washer_break_duration_min,
            "washer_count": inp.washer_count,
            "dryer_count": inp.dryer_count,
            "wash_cycle_min": inp.wash_cycle_min,
            "dry_cycle_min": inp.dry_cycle_min,
            "weigh_min_per_bag": inp.weigh_min_per_bag,
            "sort_min_per_bag": inp.sort_min_per_bag,
            "fold_min_per_bag": inp.fold_min_per_bag,
            "folder_count": inp.folder_count,
            "weigher_count": inp.weigher_count,
            "sorter_count": inp.sorter_count,
            "weighing_handled_by": inp.weighing_handled_by,
            "washing_strategy": inp.washing_strategy,
            "batch_size": inp.batch_size,
            "load_washer_min": inp.load_washer_min,
            "unload_washer_min": inp.unload_washer_min,
            "load_dryer_min": inp.load_dryer_min,
            "unload_dryer_min": inp.unload_dryer_min,
            "washer_transfer_min": inp.washer_transfer_min,
            "total_wash_loads": inp.total_wash_loads,
            "total_dryer_loads": inp.total_dryer_loads,
            "avg_bags_per_wash_load": round(inp.avg_bags_per_wash_load, 2),
            "estimated_load_plan": inp.estimate_wash_loads()[:8],
        },
        "staffing": staffing,
        "strategies": strategies,
        "recommendation": recommendation,
        "active_strategy": strategies[recommended_key],
        "operational": operational,
        "resource_utilization": operational.get("resource_utilization", []),
        "utilization_bottleneck": operational.get("utilization_bottleneck"),
        "what_if": what_if,
    }
