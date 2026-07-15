"""
Bag-level discrete-event Shift Capacity Planner simulation.

Machine cycle time and employee handling time are modeled separately.
Staffing is a timed employee roster (entry/exit), not anonymous role counts.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal

BatchLimitMode = Literal["bags", "pounds", "whichever_first"]
FoldRateMode = Literal["minutes_per_bag", "lbs_per_hour"]
SimMode = Literal["continue_from_time", "reoptimize_full"]


def _parse_clock_minutes(raw: Any, *, default: str = "7:00 AM") -> int:
    text = str(raw if raw is not None else default).strip().upper().replace(".", "")
    if not text:
        text = default.upper()
    am_pm = "AM" if "AM" in text else "PM" if "PM" in text else ""
    core = text.replace("AM", "").replace("PM", "").strip()
    if ":" in core:
        hh_s, mm_s = core.split(":", 1)
    else:
        hh_s, mm_s = core, "0"
    try:
        hh = int(hh_s)
        mm = int(mm_s)
    except ValueError:
        return _parse_clock_minutes(default)
    if am_pm == "PM" and hh != 12:
        hh += 12
    if am_pm == "AM" and hh == 12:
        hh = 0
    return hh * 60 + mm


def _label(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    m = int(minutes) % (24 * 60)
    hh = m // 60
    mm = m % 60
    am_pm = "AM" if hh < 12 else "PM"
    h12 = hh % 12
    if h12 == 0:
        h12 = 12
    return f"{h12}:{mm:02d} {am_pm}"


@dataclass
class EmployeeSpec:
    id: str
    name: str
    primary_role: str  # weigher|sorter|washer|folder|helper
    start_min: int
    end_min: int | None = None
    secondary_roles: list[str] = field(default_factory=list)
    weigh_min_per_bag: float | None = None
    sort_min_per_bag: float | None = None
    load_washer_min: float | None = None
    transfer_min: float | None = None
    load_dryer_min: float | None = None
    fold_min_per_bag: float | None = None
    fold_lbs_per_hour: float | None = None
    active: bool = True
    hourly_rate: float | None = None
    role_schedule: list[tuple[str, int, int]] = field(default_factory=list)


@dataclass
class BatchOverride:
    batch_number: int
    apply_scope: str = "this_batch_only"
    bag_ids: list[str] | None = None
    batch_size: int | None = None
    max_pounds: float | None = None
    washer_id: str | None = None
    dryer_id: str | None = None
    washer_person_id: str | None = None
    transfer_person_id: str | None = None
    dryer_load_person_id: str | None = None
    priority: int | None = None
    extra_helper_id: str | None = None
    sorter_helps_washer: bool | None = None
    folder_helps_washer: bool | None = None
    sorting_paused: bool | None = None
    planned_start_min: int | None = None
    strict_resource_lock: bool = False


@dataclass
class OrderSpec:
    order_number: str
    bag_count: int
    weights: list[float] = field(default_factory=list)
    total_weight: float | None = None
    two_washer: bool = False
    two_dryer: bool = False
    rush: bool = False
    required_complete_min: int | None = None


@dataclass
class BagState:
    bag_id: str
    order_number: str
    weight: float
    weight_estimated: bool = False
    rush: bool = False
    two_washer_order: bool = False
    two_dryer_order: bool = False
    batch_number: int | None = None
    # Timestamps (minutes from midnight)
    enter_min: int | None = None
    weigh_start: int | None = None
    weigh_end: int | None = None
    sort_start: int | None = None
    sort_end: int | None = None
    washer_id: str | None = None
    washer_load_start: int | None = None
    washer_load_end: int | None = None
    wash_start: int | None = None
    wash_end: int | None = None
    transfer_start: int | None = None
    transfer_end: int | None = None
    dryer_id: str | None = None
    dryer_load_start: int | None = None
    dryer_load_end: int | None = None
    dry_start: int | None = None
    dry_end: int | None = None
    dryer_unload_end: int | None = None
    ready_to_fold: int | None = None
    folder_id: str | None = None
    fold_start: int | None = None
    fold_end: int | None = None
    completed: int | None = None
    weighed_by: str | None = None
    sorted_by: str | None = None
    washer_loaded_by: str | None = None
    transferred_by: str | None = None
    dryer_loaded_by: str | None = None
    folded_by: str | None = None

    @property
    def wait_before_wash(self) -> int | None:
        if self.sort_end is None or self.washer_load_start is None:
            return None
        return max(0, self.washer_load_start - self.sort_end)

    @property
    def wait_before_dry(self) -> int | None:
        if self.transfer_end is None or self.dryer_load_start is None:
            return None
        return max(0, self.dryer_load_start - self.transfer_end)

    @property
    def wait_for_folder(self) -> int | None:
        if self.ready_to_fold is None or self.fold_start is None:
            return None
        return max(0, self.fold_start - self.ready_to_fold)

    @property
    def total_elapsed(self) -> int | None:
        if self.enter_min is None or self.completed is None:
            return None
        return self.completed - self.enter_min


@dataclass
class BatchState:
    batch_number: int
    bag_ids: list[str] = field(default_factory=list)
    order_numbers: list[str] = field(default_factory=list)
    total_bags: int = 0
    total_pounds: float = 0.0
    washer_id: str | None = None
    dryer_id: str | None = None
    washer_load_start: int | None = None
    washer_load_end: int | None = None
    wash_start: int | None = None
    wash_end: int | None = None
    transfer_start: int | None = None
    transfer_end: int | None = None
    dryer_load_start: int | None = None
    dryer_load_end: int | None = None
    dry_start: int | None = None
    dry_end: int | None = None
    ready_to_fold: int | None = None


@dataclass
class DesInputs:
    start_min: int
    target_min: int
    bag_count: int
    avg_lbs_per_bag: float
    bag_weights: list[float]
    washer_count: int
    dryer_count: int
    washer_capacity_lb: float
    dryer_capacity_lb: float
    batch_size: int
    batch_limit_mode: BatchLimitMode
    weigh_min_per_bag: float
    sort_min_per_bag: float
    load_washer_min: float
    unload_transfer_min: float
    wash_cycle_min: float
    load_dryer_min: float
    unload_dryer_min: float
    dry_cycle_min: float
    fold_rate_mode: FoldRateMode
    fold_min_per_bag: float
    fold_lbs_per_hour: float
    employees: list[EmployeeSpec]
    orders: list[OrderSpec]
    finish_in_progress_at_exit: bool = True
    sim_mode: SimMode = "reoptimize_full"
    continue_from_min: int | None = None
    batch_overrides: list[BatchOverride] = field(default_factory=list)


class ResourceCalendar:
    """Tracks busy intervals; free_at is exclusive end of latest task."""

    def __init__(self) -> None:
        self.free_at: dict[str, int] = {}
        self.intervals: dict[str, list[tuple[int, int, str]]] = {}

    def available_at(self, resource_id: str, t: int) -> bool:
        return self.free_at.get(resource_id, 0) <= t

    def next_free(self, resource_id: str) -> int:
        return int(self.free_at.get(resource_id, 0))

    def book(self, resource_id: str, start: int, end: int, label: str) -> None:
        if end < start:
            end = start
        self.free_at[resource_id] = end
        self.intervals.setdefault(resource_id, []).append((start, end, label))
        self.intervals[resource_id].sort()


def _default_employees(start_min: int, end_min: int | None, rates: dict[str, float]) -> list[EmployeeSpec]:
    end = end_min if end_min is not None else start_min + 8 * 60
    return [
        EmployeeSpec("E-WEIGH-1", "Weigher 1", "weigher", start_min, end),
        EmployeeSpec("E-SORT-1", "Sorter 1", "sorter", start_min, end),
        EmployeeSpec("E-WASH-1", "Washer 1", "washer", start_min, end),
        EmployeeSpec("E-FOLD-1", "Folder 1", "folder", start_min, end, fold_lbs_per_hour=rates.get("fold_lbs", 35)),
        EmployeeSpec("E-FOLD-2", "Folder 2", "folder", start_min + 60, end, fold_lbs_per_hour=rates.get("fold_lbs", 40)),
        EmployeeSpec("E-FOLD-3", "Folder 3", "folder", start_min + 150, end, fold_lbs_per_hour=rates.get("fold_lbs", 35)),
    ]


def _expand_orders(orders: list[OrderSpec], avg_lbs: float) -> list[BagState]:
    bags: list[BagState] = []
    for order in orders:
        n = max(1, int(order.bag_count))
        weights = list(order.weights or [])
        estimated = False
        if len(weights) < n:
            estimated = True
            if order.total_weight and order.total_weight > 0:
                each = float(order.total_weight) / n
                weights = [each] * n
            else:
                while len(weights) < n:
                    weights.append(float(avg_lbs))
        for i in range(n):
            bags.append(
                BagState(
                    bag_id=f"{order.order_number}-{i + 1}",
                    order_number=order.order_number,
                    weight=float(weights[i]),
                    weight_estimated=estimated or (not order.weights),
                    rush=bool(order.rush),
                    two_washer_order=bool(order.two_washer),
                    two_dryer_order=bool(order.two_dryer),
                )
            )
    return bags


def parse_des_inputs(data: dict[str, Any] | None) -> DesInputs:
    raw = dict(data or {})
    start_min = _parse_clock_minutes(raw.get("start_time"), default="7:00 AM")
    target_min = _parse_clock_minutes(raw.get("target_time"), default="12:00 PM")
    if target_min <= start_min:
        target_min = start_min + 5 * 60

    try:
        bag_count_raw = int(raw.get("bag_count") if raw.get("bag_count") is not None else 50)
    except (TypeError, ValueError) as exc:
        raise ValueError("bag_count must be a positive integer") from exc
    if bag_count_raw < 1:
        raise ValueError("bag_count must be >= 1")
    bag_count = bag_count_raw
    avg_lbs = float(raw.get("avg_lbs_per_bag") or 20)
    bag_weights = [float(x) for x in (raw.get("bag_weights") or []) if x is not None]
    while len(bag_weights) < bag_count:
        bag_weights.append(avg_lbs)
    bag_weights = bag_weights[:bag_count]

    batch_limit_mode = str(raw.get("batch_limit_mode") or "whichever_first").strip().lower()
    if batch_limit_mode not in ("bags", "pounds", "whichever_first"):
        batch_limit_mode = "whichever_first"

    fold_rate_mode = str(raw.get("fold_rate_mode") or "lbs_per_hour").strip().lower()
    if fold_rate_mode not in ("minutes_per_bag", "lbs_per_hour"):
        fold_rate_mode = "lbs_per_hour"

    employees: list[EmployeeSpec] = []
    for idx, row in enumerate(raw.get("employees") or []):
        if not isinstance(row, dict) or row.get("active") is False:
            continue
        role = str(row.get("primary_role") or "helper").strip().lower()
        emp_id = str(row.get("id") or f"E{idx + 1}")
        name = str(row.get("name") or f"{role.title()} {idx + 1}")
        start = _parse_clock_minutes(row.get("start_time"), default=_label(start_min) or "7:00 AM")
        end_raw = row.get("end_time")
        end = _parse_clock_minutes(end_raw, default=_label(start_min + 8 * 60) or "3:00 PM") if end_raw else None
        secondary = [
            str(r).strip().lower()
            for r in (row.get("secondary_roles") or row.get("allowed_secondary_roles") or [])
            if str(r).strip()
        ]
        role_schedule: list[tuple[str, int, int]] = []
        for window in row.get("role_schedule") or []:
            if not isinstance(window, dict) or not window.get("role"):
                continue
            role_schedule.append((
                str(window["role"]).strip().lower(),
                _parse_clock_minutes(window.get("start_time") or window.get("from"), default=_label(start) or "7:00 AM"),
                _parse_clock_minutes(window.get("end_time") or window.get("to"), default=_label(end or start + 8 * 60) or "3:00 PM"),
            ))
        role_schedule.sort(key=lambda item: item[1])
        for previous, current in zip(role_schedule, role_schedule[1:]):
            if current[1] < previous[2]:
                raise ValueError(f"Employee {emp_id} has overlapping role_schedule windows")
        # Role-relationship shortcuts from UI
        employees.append(
            EmployeeSpec(
                id=emp_id,
                name=name,
                primary_role=role,
                start_min=start,
                end_min=end,
                secondary_roles=secondary,
                weigh_min_per_bag=_maybe_float(row.get("weigh_min_per_bag")),
                sort_min_per_bag=_maybe_float(row.get("sort_min_per_bag")),
                load_washer_min=_maybe_float(row.get("load_washer_min")),
                transfer_min=_maybe_float(row.get("transfer_min") or row.get("unload_transfer_min")),
                load_dryer_min=_maybe_float(row.get("load_dryer_min")),
                fold_min_per_bag=_maybe_float(row.get("fold_min_per_bag")),
                fold_lbs_per_hour=_maybe_float(row.get("fold_lbs_per_hour")),
                active=True,
                hourly_rate=_maybe_float(row.get("hourly_rate")),
                role_schedule=role_schedule,
            )
        )

    def _merge_roles(primary_role: str, secondary_role: str) -> None:
        nonlocal employees
        primaries = [e for e in employees if e.primary_role == primary_role]
        secondaries = [e for e in employees if e.primary_role == secondary_role]
        if not primaries:
            return
        primary = primaries[0]
        if secondary_role not in primary.secondary_roles:
            primary.secondary_roles.append(secondary_role)
        if secondaries and secondaries[0].id != primary.id:
            employees = [e for e in employees if e.id != secondaries[0].id]

    def _flag(name: str) -> bool:
        return str(raw.get(name) or "").lower() in ("1", "true", "yes")

    if _flag("weigher_washer_same"):
        _merge_roles("weigher", "washer")
    if _flag("weigher_sorter_same"):
        _merge_roles("weigher", "sorter")
    if _flag("sorter_washer_same"):
        _merge_roles("sorter", "washer")
    if _flag("washer_folder_same"):
        _merge_roles("washer", "folder")

    if not employees:
        employees = _default_employees(
            start_min,
            start_min + 8 * 60,
            {"fold_lbs": float(raw.get("fold_lbs_per_hour") or 35)},
        )

    orders: list[OrderSpec] = []
    for idx, row in enumerate(raw.get("orders") or []):
        if not isinstance(row, dict):
            continue
        n = max(1, int(row.get("bag_count") or 1))
        weights = [float(x) for x in (row.get("weights") or []) if x is not None]
        orders.append(
            OrderSpec(
                order_number=str(row.get("order_number") or f"ORD-{idx + 1}"),
                bag_count=n,
                weights=weights,
                total_weight=_maybe_float(row.get("total_weight")),
                two_washer=bool(row.get("two_washer") or row.get("two_washer_order")),
                two_dryer=bool(row.get("two_dryer") or row.get("two_dryer_order")),
                rush=bool(row.get("rush")),
                required_complete_min=(
                    _parse_clock_minutes(row["required_complete_time"])
                    if row.get("required_complete_time")
                    else None
                ),
            )
        )

    if not orders:
        # Expand from bag_count / bag_weights as synthetic orders of size batch_size chunks
        remaining = bag_count
        order_idx = 1
        cursor = 0
        while remaining > 0:
            n = min(int(raw.get("batch_size") or 8), remaining)
            chunk = bag_weights[cursor : cursor + n]
            orders.append(
                OrderSpec(
                    order_number=f"ORD-{order_idx}",
                    bag_count=n,
                    weights=chunk,
                    total_weight=sum(chunk),
                )
            )
            remaining -= n
            cursor += n
            order_idx += 1

    overrides: list[BatchOverride] = []
    for row in raw.get("batch_overrides") or []:
        if not isinstance(row, dict):
            continue
        try:
            number = int(row.get("batch_number"))
        except (TypeError, ValueError) as exc:
            raise ValueError("batch_overrides.batch_number must be an integer") from exc
        if number < 1:
            raise ValueError("batch_overrides.batch_number must be >= 1")
        scope = str(row.get("apply_scope") or "this_batch_only")
        if scope not in ("this_batch_only", "from_this_batch"):
            raise ValueError("batch_overrides.apply_scope must be this_batch_only or from_this_batch")
        planned = row.get("planned_start_min")
        if planned is None and (row.get("planned_start_time") or row.get("planned_start")):
            planned = _parse_clock_minutes(row.get("planned_start_time") or row.get("planned_start"))
        overrides.append(BatchOverride(
            batch_number=number, apply_scope=scope,
            bag_ids=[str(x) for x in row["bag_ids"]] if isinstance(row.get("bag_ids"), list) else None,
            batch_size=int(row["batch_size"]) if row.get("batch_size") is not None else None,
            max_pounds=_maybe_float(row.get("max_pounds")),
            washer_id=str(row["washer_id"]) if row.get("washer_id") else None,
            dryer_id=str(row["dryer_id"]) if row.get("dryer_id") else None,
            washer_person_id=str(row["washer_person_id"]) if row.get("washer_person_id") else None,
            transfer_person_id=str(row["transfer_person_id"]) if row.get("transfer_person_id") else None,
            dryer_load_person_id=str(row["dryer_load_person_id"]) if row.get("dryer_load_person_id") else None,
            priority=int(row["priority"]) if row.get("priority") is not None else None,
            extra_helper_id=str(row["extra_helper_id"]) if row.get("extra_helper_id") else None,
            sorter_helps_washer=row.get("sorter_helps_washer"),
            folder_helps_washer=row.get("folder_helps_washer"),
            sorting_paused=row.get("sorting_paused"),
            planned_start_min=int(planned) if planned is not None else None,
            strict_resource_lock=bool(row.get("strict_resource_lock")),
        ))

    return DesInputs(
        start_min=start_min,
        target_min=target_min,
        bag_count=bag_count,
        avg_lbs_per_bag=avg_lbs,
        bag_weights=bag_weights,
        washer_count=max(1, int(raw.get("washer_count") or 4)),
        dryer_count=max(1, int(raw.get("dryer_count") or 4)),
        washer_capacity_lb=float(raw.get("washer_capacity_lb") or 80),
        dryer_capacity_lb=float(raw.get("dryer_capacity_lb") or 80),
        batch_size=max(1, int(raw.get("batch_size") or 8)),
        batch_limit_mode=batch_limit_mode,  # type: ignore[arg-type]
        weigh_min_per_bag=float(raw.get("weigh_min_per_bag") or 1),
        sort_min_per_bag=float(raw.get("sort_min_per_bag") or 5),
        load_washer_min=float(raw.get("load_washer_min") or raw.get("washer_loading_min") or 3),
        unload_transfer_min=float(
            raw.get("unload_transfer_min")
            or raw.get("washer_transfer_min")
            or raw.get("unload_washer_min")
            or 5
        ),
        wash_cycle_min=float(raw.get("wash_cycle_min") or 30),
        load_dryer_min=float(raw.get("load_dryer_min") or raw.get("dryer_loading_min") or 3),
        unload_dryer_min=float(raw.get("unload_dryer_min") or 0),
        dry_cycle_min=float(raw.get("dry_cycle_min") or 45),
        fold_rate_mode=fold_rate_mode,  # type: ignore[arg-type]
        fold_min_per_bag=float(raw.get("fold_min_per_bag") or 6),
        fold_lbs_per_hour=float(raw.get("fold_lbs_per_hour") or 35),
        employees=employees,
        orders=orders,
        finish_in_progress_at_exit=str(raw.get("exit_policy") or "finish_current").lower()
        != "hard_stop",
        sim_mode=(
            "continue_from_time"
            if str(raw.get("sim_mode") or "").lower() in ("continue_from_time", "continue")
            else "reoptimize_full"
        ),
        continue_from_min=(
            int(raw["continue_from_min"]) if raw.get("continue_from_min") is not None
            else _parse_clock_minutes(raw["continue_from_time"])
            if raw.get("continue_from_time")
            else None
        ),
        batch_overrides=overrides,
    )


def _maybe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _role_capable(emp: EmployeeSpec, role: str, t: int | None = None) -> bool:
    role = role.lower()
    if t is not None and emp.role_schedule:
        return any(window_role == role and start <= t < end for window_role, start, end in emp.role_schedule)
    return emp.primary_role == role or role in (emp.secondary_roles or [])


def _emp_rate(emp: EmployeeSpec, role: str, defaults: DesInputs) -> float:
    if role == "weigher":
        return float(emp.weigh_min_per_bag if emp.weigh_min_per_bag is not None else defaults.weigh_min_per_bag)
    if role == "sorter":
        return float(emp.sort_min_per_bag if emp.sort_min_per_bag is not None else defaults.sort_min_per_bag)
    if role == "load_washer":
        return float(emp.load_washer_min if emp.load_washer_min is not None else defaults.load_washer_min)
    if role == "transfer":
        return float(emp.transfer_min if emp.transfer_min is not None else defaults.unload_transfer_min)
    if role == "load_dryer":
        return float(emp.load_dryer_min if emp.load_dryer_min is not None else defaults.load_dryer_min)
    if role == "fold":
        if defaults.fold_rate_mode == "minutes_per_bag":
            return float(emp.fold_min_per_bag if emp.fold_min_per_bag is not None else defaults.fold_min_per_bag)
        lbs = float(emp.fold_lbs_per_hour if emp.fold_lbs_per_hour is not None else defaults.fold_lbs_per_hour)
        # placeholder; fold duration computed from bag weight
        return max(0.1, lbs)
    return 1.0


def _fold_duration_min(emp: EmployeeSpec, bag: BagState, defaults: DesInputs) -> float:
    if defaults.fold_rate_mode == "minutes_per_bag":
        return max(0.1, _emp_rate(emp, "fold", defaults))
    lbs_hr = float(emp.fold_lbs_per_hour if emp.fold_lbs_per_hour is not None else defaults.fold_lbs_per_hour)
    if lbs_hr <= 0:
        lbs_hr = 35.0
    return max(0.1, (bag.weight / lbs_hr) * 60.0)


def _employees_for_role(employees: list[EmployeeSpec], role: str, t: int) -> list[EmployeeSpec]:
    out = []
    for e in employees:
        if not e.active:
            continue
        if t < e.start_min:
            continue
        if e.end_min is not None and t >= e.end_min and not True:
            # availability checked at task start; allowing finish-current handled by caller
            pass
        if _role_capable(e, role, t):
            out.append(e)
    return out


def _can_start_task(emp: EmployeeSpec, t: int, duration: float, finish_current: bool) -> bool:
    if t < emp.start_min:
        return False
    if emp.end_min is None:
        return True
    if t >= emp.end_min:
        return False
    if finish_current:
        return True
    return t + int(duration) <= emp.end_min


def _book_employee(
    cal: ResourceCalendar,
    emp: EmployeeSpec,
    start: int,
    duration: float,
    label: str,
) -> tuple[int, int]:
    start = max(start, emp.start_min, cal.next_free(emp.id))
    end = start + max(1, int(round(duration)))
    cal.book(emp.id, start, end, label)
    return start, end


def _pick_earliest_employee(
    employees: list[EmployeeSpec],
    role: str,
    cal: ResourceCalendar,
    not_before: int,
    duration: float,
    finish_current: bool,
) -> tuple[EmployeeSpec | None, int]:
    best: EmployeeSpec | None = None
    best_t = 10**9
    for emp in employees:
        if not emp.active:
            continue
        t = max(not_before, emp.start_min, cal.next_free(emp.id))
        # A role window may begin after the initial candidate; find its next start.
        if not _role_capable(emp, role, t) and emp.role_schedule:
            starts = [start for window_role, start, end in emp.role_schedule if window_role == role and start >= t and start < end]
            if starts:
                t = min(starts)
        if not _role_capable(emp, role, t):
            continue
        if not _can_start_task(emp, t, duration, finish_current):
            continue
        if t < best_t:
            best_t = t
            best = emp
    return best, best_t


def _machine_ids(prefix: str, count: int) -> list[str]:
    return [f"{prefix}{i + 1}" for i in range(count)]


def _batch_fits(bags: list[BagState], next_bag: BagState, batch_size: int, cap_lb: float, mode: str) -> bool:
    n = len(bags) + 1
    lbs = sum(b.weight for b in bags) + next_bag.weight
    bag_ok = n <= batch_size
    lb_ok = lbs <= cap_lb + 1e-6
    if mode == "bags":
        return bag_ok
    if mode == "pounds":
        return lb_ok
    return bag_ok and lb_ok


def _split_bags_by_weight(bags: list[BagState], parts: int) -> list[list[BagState]]:
    """Greedy split preserving bag identity across machines (two-washer / two-dryer)."""
    if parts <= 1 or len(bags) <= 1:
        return [list(bags)]
    ordered = sorted(bags, key=lambda b: (-b.weight, b.bag_id))
    groups: list[list[BagState]] = [[] for _ in range(parts)]
    totals = [0.0] * parts
    for bag in ordered:
        idx = min(range(parts), key=lambda i: (totals[i], len(groups[i]), i))
        groups[idx].append(bag)
        totals[idx] += bag.weight
    return [g for g in groups if g]


def _effective_override(overrides: list[BatchOverride], batch_number: int) -> BatchOverride | None:
    """Last matching entry wins; an exact entry is more specific than cascading."""
    matched: BatchOverride | None = None
    for item in overrides:
        if item.apply_scope == "this_batch_only" and item.batch_number == batch_number:
            matched = item
        elif item.apply_scope == "from_this_batch" and item.batch_number <= batch_number:
            matched = item
    return matched


def _override_errors(inp: DesInputs, bag_ids: set[str], washers: list[str], dryers: list[str]) -> list[str]:
    errors: list[str] = []
    employees = {e.id: e for e in inp.employees}
    for override in inp.batch_overrides:
        if override.washer_id and override.washer_id not in washers:
            errors.append(f"Batch {override.batch_number} references unknown washer {override.washer_id}")
        if override.dryer_id and override.dryer_id not in dryers:
            errors.append(f"Batch {override.batch_number} references unknown dryer {override.dryer_id}")
        for person_id, role in (
            (override.washer_person_id, "washer"), (override.transfer_person_id, "washer"),
            (override.dryer_load_person_id, "washer"), (override.extra_helper_id, "washer"),
        ):
            if person_id and (person_id not in employees or not _role_capable(employees[person_id], role)):
                errors.append(f"Batch {override.batch_number} references unavailable {role} employee {person_id}")
        if override.bag_ids:
            unknown = sorted(set(override.bag_ids) - bag_ids)
            if unknown:
                errors.append(f"Batch {override.batch_number} references unknown bag(s): {', '.join(unknown)}")
    return errors


def merge_batch_override(inputs: dict[str, Any], override_dict: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with one batch override upserted or a batch reset."""
    out = dict(inputs or {})
    existing = [dict(row) for row in (out.get("batch_overrides") or []) if isinstance(row, dict)]
    reset = override_dict.get("reset_override") if isinstance(override_dict, dict) else None
    if isinstance(reset, dict) and reset.get("batch_number") is not None:
        number = int(reset["batch_number"])
        out["batch_overrides"] = [row for row in existing if int(row.get("batch_number", -1)) != number]
        return out
    number = int(override_dict["batch_number"])
    scope = str(override_dict.get("apply_scope") or "this_batch_only")
    existing = [row for row in existing if not (int(row.get("batch_number", -1)) == number and str(row.get("apply_scope") or "this_batch_only") == scope)]
    existing.append(dict(override_dict))
    out["batch_overrides"] = existing
    return out


def _refresh_summary_from_bag_rows(result: dict[str, Any], target_min: int) -> None:
    """Recompute readiness / completion KPIs after freeze overlays mutate bag_rows."""
    rows = result.get("bag_rows") or []
    summary = result.setdefault("summary", {})

    def _ready_min(row: dict[str, Any]) -> int | None:
        return _parse_clock_minutes(row["ready_to_fold"]) if row.get("ready_to_fold") else None

    def _done_min(row: dict[str, Any]) -> int | None:
        return _parse_clock_minutes(row["completed"]) if row.get("completed") else None

    ready_by_target = 0
    folded_by_target = 0
    lbs_ready = 0.0
    lbs_folded = 0.0
    first_ready = None
    last_ready = None
    final_complete = None
    for row in rows:
        rmin = _ready_min(row)
        dmin = _done_min(row)
        w = float(row.get("weight") or 0)
        if rmin is not None:
            first_ready = rmin if first_ready is None else min(first_ready, rmin)
            last_ready = rmin if last_ready is None else max(last_ready, rmin)
            if rmin <= target_min:
                ready_by_target += 1
                lbs_ready += w
        if dmin is not None:
            final_complete = dmin if final_complete is None else max(final_complete, dmin)
            if dmin <= target_min:
                folded_by_target += 1
                lbs_folded += w
    summary["bags_ready_by_target"] = ready_by_target
    summary["bags_folded_by_target"] = folded_by_target
    summary["pounds_ready_by_target"] = round(lbs_ready, 2)
    summary["pounds_folded_by_target"] = round(lbs_folded, 2)
    summary["first_bag_ready_time"] = _label(first_ready)
    summary["last_bag_ready_time"] = _label(last_ready)
    summary["final_completion_time"] = _label(final_complete)


def run_bag_des_simulation(data: dict[str, Any] | None, _disable_partial: bool = False) -> dict[str, Any]:
    inp = parse_des_inputs(data)
    bags = _expand_orders(inp.orders, inp.avg_lbs_per_bag)
    # Preserve bag_count expectation when orders derived from bag_count
    if len(bags) != inp.bag_count and not (data or {}).get("orders"):
        bags = [
            BagState(
                bag_id=f"BAG-{i + 1}",
                order_number=f"ORD-{(i // max(1, inp.batch_size)) + 1}",
                weight=float(inp.bag_weights[i] if i < len(inp.bag_weights) else inp.avg_lbs_per_bag),
                weight_estimated=not bool((data or {}).get("bag_weights")),
            )
            for i in range(inp.bag_count)
        ]

    # Rush first, then order
    bags.sort(key=lambda b: (0 if b.rush else 1, b.order_number, b.bag_id))

    emp_cal = ResourceCalendar()
    washer_cal = ResourceCalendar()
    dryer_cal = ResourceCalendar()
    washers = _machine_ids("W", inp.washer_count)
    dryers = _machine_ids("D", inp.dryer_count)
    validation_errors = _override_errors(inp, {b.bag_id for b in bags}, washers, dryers)
    if validation_errors:
        result = _build_des_payload(inp, bags, [], emp_cal, washer_cal, dryer_cal, washers, dryers)
        result.update({"simulation_valid": False, "validation_errors": validation_errors, "bags_moved": []})
        return result

    for bag in bags:
        bag.enter_min = inp.start_min

    # --- Weigh ---
    for bag in bags:
        dur = inp.weigh_min_per_bag
        emp, t0 = _pick_earliest_employee(
            inp.employees, "weigher", emp_cal, bag.enter_min or inp.start_min, dur, inp.finish_in_progress_at_exit
        )
        if emp is None:
            # fall back: invent temporary weigher capacity as unbounded delay
            t0 = max(bag.enter_min or inp.start_min, emp_cal.next_free("__weigh__"))
            emp_cal.book("__weigh__", t0, t0 + max(1, int(round(dur))), "weigh")
            bag.weigh_start, bag.weigh_end = t0, t0 + max(1, int(round(dur)))
            bag.weighed_by = "Unassigned"
        else:
            dur = _emp_rate(emp, "weigher", inp)
            bag.weigh_start, bag.weigh_end = _book_employee(emp_cal, emp, t0, dur, f"weigh {bag.bag_id}")
            bag.weighed_by = emp.name

    # --- Sort ---
    for bag in bags:
        not_before = bag.weigh_end or inp.start_min
        dur = inp.sort_min_per_bag
        emp, t0 = _pick_earliest_employee(
            inp.employees, "sorter", emp_cal, not_before, dur, inp.finish_in_progress_at_exit
        )
        if emp is None:
            t0 = max(not_before, emp_cal.next_free("__sort__"))
            end = t0 + max(1, int(round(dur)))
            emp_cal.book("__sort__", t0, end, "sort")
            bag.sort_start, bag.sort_end = t0, end
            bag.sorted_by = "Unassigned"
        else:
            dur = _emp_rate(emp, "sorter", inp)
            bag.sort_start, bag.sort_end = _book_employee(emp_cal, emp, t0, dur, f"sort {bag.bag_id}")
            bag.sorted_by = emp.name

    # --- Batch construction from sorted bags ---
    sorted_bags = sorted(bags, key=lambda b: (b.sort_end or 0, b.bag_id))
    batches: list[BatchState] = []
    baseline_membership: dict[str, int] = {}
    queue = list(sorted_bags)
    batch_num = 1
    while queue:
        group: list[BagState] = []
        override = _effective_override(inp.batch_overrides, batch_num)
        # Preserve unrestricted membership before the first edited batch.
        explicit_ids = override.bag_ids if override and override.apply_scope == "this_batch_only" else None
        if explicit_ids:
            wanted = set(explicit_ids)
            group = [bag for bag in queue if bag.bag_id in wanted]
            queue = [bag for bag in queue if bag.bag_id not in wanted]
            if not group:
                validation_errors.append(f"Batch {batch_num} has no selected bags")
                break
        effective_size = override.batch_size if override and override.batch_size else inp.batch_size
        effective_cap = override.max_pounds if override and override.max_pounds is not None else inp.washer_capacity_lb
        # Prefer starting when first bag is sorted
        while queue:
            candidate = queue[0]
            if explicit_ids:
                break
            if group and not _batch_fits(group, candidate, effective_size, effective_cap, inp.batch_limit_mode):
                break
            # Also enforce dryer capacity when single dryer path
            trial_lbs = sum(b.weight for b in group) + candidate.weight
            if trial_lbs > inp.dryer_capacity_lb + 1e-6 and group:
                break
            group.append(queue.pop(0))
            # Stop early if pound limit hit exactly under whichever_first
            if inp.batch_limit_mode in ("pounds", "whichever_first"):
                if sum(b.weight for b in group) >= effective_cap - 1e-6:
                    break
            if len(group) >= effective_size and inp.batch_limit_mode in ("bags", "whichever_first"):
                break
        if not group:
            break
        batch = BatchState(
            batch_number=batch_num,
            bag_ids=[b.bag_id for b in group],
            order_numbers=sorted({b.order_number for b in group}),
            total_bags=len(group),
            total_pounds=round(sum(b.weight for b in group), 2),
        )
        for b in group:
            b.batch_number = batch_num
            baseline_membership.setdefault(b.bag_id, batch_num)
        batches.append(batch)
        batch_num += 1

    for batch in batches:
        override = _effective_override(inp.batch_overrides, batch.batch_number)
        cap = override.max_pounds if override and override.max_pounds is not None else inp.washer_capacity_lb
        if batch.total_pounds > cap + 1e-6:
            validation_errors.append(
                f"Batch {batch.batch_number} exceeds washer capacity ({batch.total_pounds:.1f} lb > {cap:.1f} lb)"
            )
    if validation_errors:
        result = _build_des_payload(inp, bags, batches, emp_cal, washer_cal, dryer_cal, washers, dryers)
        result.update({"simulation_valid": False, "validation_errors": validation_errors, "bags_moved": []})
        return result

    bag_by_id = {b.bag_id: b for b in bags}
    strict_lock_errors: list[str] = []

    # --- Process each batch through wash/dry ---
    for batch in batches:
        override = _effective_override(inp.batch_overrides, batch.batch_number)
        members = [bag_by_id[bid] for bid in batch.bag_ids]
        ready_sort = max(b.sort_end or inp.start_min for b in members)
        split_wash = any(b.two_washer_order for b in members) and len(members) >= 2 and len(washers) >= 2
        wash_groups = _split_bags_by_weight(members, 2) if split_wash else [members]

        wash_ready_ends: list[int] = []
        washer_ids_used: list[str] = []
        for group in wash_groups:
            washer_id = override.washer_id if override and override.washer_id else min(washers, key=lambda w: max(ready_sort, washer_cal.next_free(w)))
            planned = override.planned_start_min if override else None
            washer_free = max(ready_sort, washer_cal.next_free(washer_id), planned or 0)
            if override and override.strict_resource_lock and planned is not None and washer_free != planned:
                strict_lock_errors.append(f"Batch {batch.batch_number} cannot start exactly at {_label(planned)}; washer {washer_id} is busy or not ready")
            load_cursor = washer_free
            for b in group:
                forced_id = override.washer_person_id if override else None
                emp = next((e for e in inp.employees if e.id == forced_id), None) if forced_id else None
                t0 = max(load_cursor, emp.start_min, emp_cal.next_free(emp.id)) if emp else 0
                if not forced_id:
                    emp, t0 = _pick_earliest_employee(
                        inp.employees, "washer", emp_cal, load_cursor, inp.load_washer_min, inp.finish_in_progress_at_exit,
                    )
                if emp is None:
                    t0 = max(load_cursor, emp_cal.next_free("__wash_load__"))
                    end = t0 + max(1, int(round(inp.load_washer_min)))
                    emp_cal.book("__wash_load__", t0, end, "load washer")
                    b.washer_load_start, b.washer_load_end = t0, end
                    b.washer_loaded_by = "Unassigned"
                else:
                    dur = _emp_rate(emp, "load_washer", inp)
                    b.washer_load_start, b.washer_load_end = _book_employee(
                        emp_cal, emp, t0, dur, f"load washer {b.bag_id}"
                    )
                    b.washer_loaded_by = emp.name
                b.washer_id = washer_id
                load_cursor = b.washer_load_end

            load_end = max(b.washer_load_end for b in group)  # type: ignore[type-var]
            wash_start = load_end
            wash_end = wash_start + max(1, int(round(inp.wash_cycle_min)))
            load_start = min(b.washer_load_start for b in group)  # type: ignore[type-var]
            washer_cal.book(washer_id, load_start, wash_end, f"batch {batch.batch_number}")
            for b in group:
                b.wash_start = wash_start
                b.wash_end = wash_end

            xfer_cursor = wash_end
            for b in group:
                forced_id = override.transfer_person_id if override else None
                emp = next((e for e in inp.employees if e.id == forced_id), None) if forced_id else None
                t0 = max(xfer_cursor, emp.start_min, emp_cal.next_free(emp.id)) if emp else 0
                if not forced_id:
                    emp, t0 = _pick_earliest_employee(
                        inp.employees, "washer", emp_cal, xfer_cursor, inp.unload_transfer_min, inp.finish_in_progress_at_exit,
                    )
                if emp is None:
                    t0 = max(xfer_cursor, emp_cal.next_free("__xfer__"))
                    end = t0 + max(1, int(round(inp.unload_transfer_min)))
                    emp_cal.book("__xfer__", t0, end, "transfer")
                    b.transfer_start, b.transfer_end = t0, end
                    b.transferred_by = "Unassigned"
                else:
                    dur = _emp_rate(emp, "transfer", inp)
                    b.transfer_start, b.transfer_end = _book_employee(
                        emp_cal, emp, t0, dur, f"transfer {b.bag_id}"
                    )
                    b.transferred_by = emp.name
                xfer_cursor = b.transfer_end
            wash_ready_ends.append(max(b.transfer_end for b in group))  # type: ignore[arg-type]
            washer_ids_used.append(washer_id)

        batch.washer_id = "+".join(washer_ids_used)
        batch.washer_load_start = min(b.washer_load_start for b in members)  # type: ignore[type-var]
        batch.washer_load_end = max(b.washer_load_end for b in members)  # type: ignore[type-var]
        batch.wash_start = min(b.wash_start for b in members)  # type: ignore[type-var]
        batch.wash_end = max(b.wash_end for b in members)  # type: ignore[type-var]
        batch.transfer_start = min(b.transfer_start for b in members)  # type: ignore[type-var]
        batch.transfer_end = max(b.transfer_end for b in members)  # type: ignore[type-var]

        dryer_ready = batch.transfer_end
        split_dry = any(b.two_dryer_order for b in members) and len(members) >= 2 and len(dryers) >= 2
        dry_groups = _split_bags_by_weight(members, 2) if split_dry else [members]
        dryer_ids_used: list[str] = []
        ready_times: list[int] = []
        for group in dry_groups:
            dryer_id = override.dryer_id if override and override.dryer_id else min(dryers, key=lambda d: max(dryer_ready, dryer_cal.next_free(d)))
            dryer_free = max(dryer_ready, dryer_cal.next_free(dryer_id))
            load_cursor = dryer_free
            for b in group:
                forced_id = override.dryer_load_person_id if override else None
                emp = next((e for e in inp.employees if e.id == forced_id), None) if forced_id else None
                t0 = max(load_cursor, emp.start_min, emp_cal.next_free(emp.id)) if emp else 0
                if not forced_id:
                    emp, t0 = _pick_earliest_employee(
                        inp.employees, "washer", emp_cal, load_cursor, inp.load_dryer_min, inp.finish_in_progress_at_exit,
                    )
                if emp is None:
                    t0 = max(load_cursor, emp_cal.next_free("__dry_load__"))
                    end = t0 + max(1, int(round(inp.load_dryer_min)))
                    emp_cal.book("__dry_load__", t0, end, "load dryer")
                    b.dryer_load_start, b.dryer_load_end = t0, end
                    b.dryer_loaded_by = "Unassigned"
                else:
                    dur = _emp_rate(emp, "load_dryer", inp)
                    b.dryer_load_start, b.dryer_load_end = _book_employee(
                        emp_cal, emp, t0, dur, f"load dryer {b.bag_id}"
                    )
                    b.dryer_loaded_by = emp.name
                b.dryer_id = dryer_id
                load_cursor = b.dryer_load_end

            load_start = min(b.dryer_load_start for b in group)  # type: ignore[type-var]
            load_end = max(b.dryer_load_end for b in group)  # type: ignore[type-var]
            dry_start = load_end
            dry_end = dry_start + max(1, int(round(inp.dry_cycle_min)))
            unload = max(0, int(round(inp.unload_dryer_min)))
            ready = dry_end + unload
            dryer_cal.book(dryer_id, load_start, ready, f"batch {batch.batch_number}")
            for b in group:
                b.dry_start = dry_start
                b.dry_end = dry_end
                b.dryer_unload_end = ready if unload else dry_end
                b.ready_to_fold = ready
            dryer_ids_used.append(dryer_id)
            ready_times.append(ready)

        batch.dryer_id = "+".join(dryer_ids_used)
        batch.dryer_load_start = min(b.dryer_load_start for b in members)  # type: ignore[type-var]
        batch.dryer_load_end = max(b.dryer_load_end for b in members)  # type: ignore[type-var]
        batch.dry_start = min(b.dry_start for b in members)  # type: ignore[type-var]
        batch.dry_end = max(b.dry_end for b in members)  # type: ignore[type-var]
        batch.ready_to_fold = max(ready_times) if ready_times else dryer_ready

    # --- Fold ---
    ready_order = sorted(bags, key=lambda b: (b.ready_to_fold or 10**9, 0 if b.rush else 1, b.bag_id))
    for bag in ready_order:
        not_before = bag.ready_to_fold or inp.start_min
        # Estimate duration using default folder rate for pickup
        probe_dur = (
            inp.fold_min_per_bag
            if inp.fold_rate_mode == "minutes_per_bag"
            else max(0.1, (bag.weight / max(1.0, inp.fold_lbs_per_hour)) * 60.0)
        )
        emp, t0 = _pick_earliest_employee(
            inp.employees, "folder", emp_cal, not_before, probe_dur, inp.finish_in_progress_at_exit
        )
        if emp is None:
            t0 = max(not_before, emp_cal.next_free("__fold__"))
            end = t0 + max(1, int(round(probe_dur)))
            emp_cal.book("__fold__", t0, end, "fold")
            bag.fold_start, bag.fold_end = t0, end
            bag.folder_id = "Unassigned"
            bag.folded_by = "Unassigned"
        else:
            dur = _fold_duration_min(emp, bag, inp)
            bag.fold_start, bag.fold_end = _book_employee(emp_cal, emp, t0, dur, f"fold {bag.bag_id}")
            bag.folder_id = emp.id
            bag.folded_by = emp.name
        bag.completed = bag.fold_end

    result = _build_des_payload(inp, bags, batches, emp_cal, washer_cal, dryer_cal, washers, dryers)
    if strict_lock_errors:
        result["simulation_valid"] = False
        result["validation_errors"] = strict_lock_errors
    if inp.sim_mode == "continue_from_time" and inp.continue_from_min is not None and not _disable_partial:
        # Produce a history-only run without people introduced at the freeze.  We
        # deliberately preserve every task that started before T (including a
        # machine cycle that continues across T), then use the current run for
        # work that begins at/after T.
        frozen_input = dict(data or {})
        frozen_input["sim_mode"] = "reoptimize_full"
        frozen_input.pop("continue_from_time", None)
        frozen_input.pop("continue_from_min", None)
        frozen_input["employees"] = [
            dict(e) for e in (data or {}).get("employees", [])
            if _parse_clock_minutes(e.get("start_time"), default=_label(inp.start_min) or "7:00 AM") < inp.continue_from_min
        ]
        history = run_bag_des_simulation(frozen_input, _disable_partial=True)
        history_rows = {row["bag_id"]: row for row in history["bag_rows"]}
        stage_pairs = {
            "weigh": ("weigh_start", "weigh_end"), "sort": ("sort_start", "sort_end"),
            "washer_load": ("washer_load_start", "washer_load_end"), "wash": ("wash_start", "wash_end"),
            "transfer": ("transfer_start", "transfer_end"), "dryer_load": ("dryer_load_start", "dryer_load_end"),
            "dry": ("dry_start", "dry_end"), "fold": ("fold_start", "fold_end"),
        }
        preserved = recalculated = in_progress = 0
        for row in result["bag_rows"]:
            old = history_rows.get(row["bag_id"], {})
            provenance: dict[str, str] = {}
            for stage, (start_key, end_key) in stage_pairs.items():
                old_start = _parse_clock_minutes(old[start_key]) if old.get(start_key) else None
                old_end = _parse_clock_minutes(old[end_key]) if old.get(end_key) else None
                if old_start is not None and old_start < inp.continue_from_min:
                    for key in (start_key, end_key):
                        row[key] = old.get(key)
                    if stage == "washer_load":
                        row["washer"] = old.get("washer")
                        row["washer_loaded_by"] = old.get("washer_loaded_by")
                    elif stage == "dryer_load":
                        row["dryer"] = old.get("dryer")
                        row["dryer_loaded_by"] = old.get("dryer_loaded_by")
                    elif stage == "fold":
                        row["folder"] = old.get("folder")
                        row["folded_by"] = old.get("folded_by")
                    tag = "in_progress" if old_end is not None and old_end > inp.continue_from_min else "preserved"
                    provenance[stage] = tag
                    if tag == "in_progress":
                        in_progress += 1
                    else:
                        preserved += 1
                elif row.get(start_key):
                    provenance[stage] = "recalculated"
                    recalculated += 1
            row["provenance"] = provenance
        result["partial_resim"] = {
            "history_frozen_through": _label(inp.continue_from_min),
            "history_frozen_through_min": inp.continue_from_min,
            "recalculated_from": _label(inp.continue_from_min),
            "recalculated_from_min": inp.continue_from_min,
            "preserved_task_count": preserved,
            "recalculated_task_count": recalculated,
            "in_progress_task_count": in_progress,
        }
        _refresh_summary_from_bag_rows(result, inp.target_min)
    if inp.batch_overrides and not _disable_partial:
        baseline_input = dict(data or {})
        baseline_input.pop("batch_overrides", None)
        baseline = run_bag_des_simulation(baseline_input, _disable_partial=True)
        before = {row["bag_id"]: row.get("batch") for row in baseline["bag_rows"]}
        moved = [
            {"bag_id": row["bag_id"], "from_batch": before.get(row["bag_id"]), "to_batch": row.get("batch")}
            for row in result["bag_rows"] if before.get(row["bag_id"]) != row.get("batch")
        ]
        result["bags_moved"] = moved
        result["override_impact"] = {
            "baseline_final_completion_time": baseline["summary"]["final_completion_time"],
            "final_completion_time": result["summary"]["final_completion_time"],
            "bags_moved": len(moved),
        }
    return result


def _no_overlap(intervals: list[tuple[int, int, str]]) -> bool:
    ordered = sorted(intervals, key=lambda x: x[0])
    for i in range(1, len(ordered)):
        if ordered[i][0] < ordered[i - 1][1]:
            return False
    return True


def _utilization(intervals: list[tuple[int, int, str]], window_start: int, window_end: int) -> float:
    if window_end <= window_start:
        return 0.0
    busy = 0
    for a, b, _ in intervals:
        lo = max(a, window_start)
        hi = min(b, window_end)
        if hi > lo:
            busy += hi - lo
    return round(100.0 * busy / (window_end - window_start), 1)


def _build_des_payload(
    inp: DesInputs,
    bags: list[BagState],
    batches: list[BatchState],
    emp_cal: ResourceCalendar,
    washer_cal: ResourceCalendar,
    dryer_cal: ResourceCalendar,
    washers: list[str],
    dryers: list[str],
) -> dict[str, Any]:
    target = inp.target_min
    window_end = max(
        [b.completed or 0 for b in bags]
        + [inp.target_min, inp.start_min + 1]
    )

    ready_by_target = sum(1 for b in bags if b.ready_to_fold is not None and b.ready_to_fold <= target)
    folded_by_target = sum(1 for b in bags if b.completed is not None and b.completed <= target)
    lbs_ready = round(sum(b.weight for b in bags if b.ready_to_fold is not None and b.ready_to_fold <= target), 2)
    lbs_folded = round(sum(b.weight for b in bags if b.completed is not None and b.completed <= target), 2)

    cum = 0
    ready_by_batch = []
    for batch in batches:
        cum += batch.total_bags
        ready_by_batch.append(
            {
                "batch_number": batch.batch_number,
                "bags": batch.total_bags,
                "pounds": batch.total_pounds,
                "ready_to_fold": _label(batch.ready_to_fold),
                "ready_to_fold_min": batch.ready_to_fold,
                "cumulative_bags_ready": cum,
                "washer_id": batch.washer_id,
                "dryer_id": batch.dryer_id,
                "bag_ids": batch.bag_ids,
                "order_numbers": batch.order_numbers,
                "wash_start": _label(batch.wash_start),
                "wash_end": _label(batch.wash_end),
                "dry_start": _label(batch.dry_start),
                "dry_end": _label(batch.dry_end),
            }
        )

    # 30-minute availability
    intervals_30 = []
    t = (inp.start_min // 30) * 30
    while t <= max(window_end, target):
        ready_n = sum(1 for b in bags if b.ready_to_fold is not None and b.ready_to_fold <= t)
        folded_n = sum(1 for b in bags if b.completed is not None and b.completed <= t)
        intervals_30.append(
            {
                "time": _label(t),
                "time_min": t,
                "bags_ready": ready_n,
                "bags_folded": folded_n,
                "pounds_ready": round(
                    sum(b.weight for b in bags if b.ready_to_fold is not None and b.ready_to_fold <= t), 2
                ),
                "pounds_folded": round(
                    sum(b.weight for b in bags if b.completed is not None and b.completed <= t), 2
                ),
            }
        )
        t += 30

    bag_rows = []
    for b in bags:
        bag_rows.append(
            {
                "order": b.order_number,
                "bag_id": b.bag_id,
                "weight": b.weight,
                "weight_estimated": b.weight_estimated,
                "batch": b.batch_number,
                "rush": b.rush,
                "weigh_start": _label(b.weigh_start),
                "weigh_end": _label(b.weigh_end),
                "sort_start": _label(b.sort_start),
                "sort_end": _label(b.sort_end),
                "washer": b.washer_id,
                "washer_load_start": _label(b.washer_load_start),
                "washer_load_end": _label(b.washer_load_end),
                "wash_start": _label(b.wash_start),
                "wash_end": _label(b.wash_end),
                "transfer_start": _label(b.transfer_start),
                "transfer_end": _label(b.transfer_end),
                "dryer": b.dryer_id,
                "dryer_load_start": _label(b.dryer_load_start),
                "dryer_load_end": _label(b.dryer_load_end),
                "dry_start": _label(b.dry_start),
                "dry_end": _label(b.dry_end),
                "ready_to_fold": _label(b.ready_to_fold),
                "folder": b.folded_by,
                "fold_start": _label(b.fold_start),
                "fold_end": _label(b.fold_end),
                "completed": _label(b.completed),
                "waiting_before_wash": b.wait_before_wash,
                "waiting_before_dry": b.wait_before_dry,
                "waiting_for_folder": b.wait_for_folder,
                "total_elapsed": b.total_elapsed,
                "weighed_by": b.weighed_by,
                "sorted_by": b.sorted_by,
                "washer_loaded_by": b.washer_loaded_by,
                "transferred_by": b.transferred_by,
                "dryer_loaded_by": b.dryer_loaded_by,
                "folded_by": b.folded_by,
            }
        )

    # Staffing chart by role at events
    event_times = sorted(
        {
            inp.start_min,
            *[e.start_min for e in inp.employees],
            *[e.end_min for e in inp.employees if e.end_min is not None],
            *[point for e in inp.employees for _, start, end in e.role_schedule for point in (start, end)],
            target,
        }
    )
    staffing_chart = []
    for t in event_times:
        switches = []
        for e in inp.employees:
            for role, start, end in e.role_schedule:
                if start == t:
                    switches.append(f"{e.name} → {role}")
                if end == t:
                    switches.append(f"{e.name} leaves {role}")
        staffing_chart.append(
            {
                "time": _label(t),
                "time_min": t,
                "weighers": sum(1 for e in inp.employees if e.active and e.start_min <= t and (e.end_min is None or t < e.end_min) and _role_capable(e, "weigher", t)),
                "sorters": sum(1 for e in inp.employees if e.active and e.start_min <= t and (e.end_min is None or t < e.end_min) and _role_capable(e, "sorter", t)),
                "washer_persons": sum(1 for e in inp.employees if e.active and e.start_min <= t and (e.end_min is None or t < e.end_min) and _role_capable(e, "washer", t)),
                "folders": sum(1 for e in inp.employees if e.active and e.start_min <= t and (e.end_min is None or t < e.end_min) and _role_capable(e, "folder", t)),
                "role_switches": switches,
            }
        )

    washer_util = [
        {"id": w, "utilization_pct": _utilization(washer_cal.intervals.get(w, []), inp.start_min, window_end)}
        for w in washers
    ]
    dryer_util = [
        {"id": d, "utilization_pct": _utilization(dryer_cal.intervals.get(d, []), inp.start_min, window_end)}
        for d in dryers
    ]
    emp_util = [
        {
            "id": e.id,
            "name": e.name,
            "role": e.primary_role,
            "utilization_pct": _utilization(emp_cal.intervals.get(e.id, []), max(inp.start_min, e.start_min), window_end),
            "intervals": [
                {"start": _label(a), "end": _label(b), "label": lab}
                for a, b, lab in emp_cal.intervals.get(e.id, [])
            ],
        }
        for e in inp.employees
        if e.active
    ]

    waits_folder = [b.wait_for_folder for b in bags if b.wait_for_folder is not None]
    avg_ready_wait = round(sum(waits_folder) / len(waits_folder), 1) if waits_folder else 0.0

    # Bottlenecks: highest employee util role, highest machine util
    primary = "none"
    if emp_util:
        top_emp = max(emp_util, key=lambda r: r["utilization_pct"])
        top_wash = max(washer_util, key=lambda r: r["utilization_pct"]) if washer_util else None
        top_dry = max(dryer_util, key=lambda r: r["utilization_pct"]) if dryer_util else None
        candidates = [
            (top_emp["utilization_pct"], f"Employee ({top_emp['name']})", "employee"),
        ]
        if top_wash:
            candidates.append((top_wash["utilization_pct"], f"Washer machine ({top_wash['id']})", "washer"))
        if top_dry:
            candidates.append((top_dry["utilization_pct"], f"Dryer machine ({top_dry['id']})", "dryer"))
        candidates.sort(reverse=True)
        primary = candidates[0][1]
        secondary = candidates[1][1] if len(candidates) > 1 else "none"
    else:
        secondary = "none"

    # Overlap validation
    overlap_errors = []
    for rid, ivals in {**emp_cal.intervals, **washer_cal.intervals, **dryer_cal.intervals}.items():
        if not _no_overlap(ivals):
            overlap_errors.append(rid)

    recommendations = _build_recommendations(inp, bags, batches, emp_util, avg_ready_wait)

    first_ready = min((b.ready_to_fold for b in bags if b.ready_to_fold is not None), default=None)
    last_ready = max((b.ready_to_fold for b in bags if b.ready_to_fold is not None), default=None)
    final_complete = max((b.completed for b in bags if b.completed is not None), default=None)

    return {
        "engine": "bag_des",
        "simulation_valid": len(overlap_errors) == 0,
        "overlap_errors": overlap_errors,
        "inputs": {
            "start_time": _label(inp.start_min),
            "target_time": _label(inp.target_min),
            "bag_count": len(bags),
            "avg_lbs_per_bag": inp.avg_lbs_per_bag,
            "washer_count": inp.washer_count,
            "dryer_count": inp.dryer_count,
            "washer_capacity_lb": inp.washer_capacity_lb,
            "dryer_capacity_lb": inp.dryer_capacity_lb,
            "batch_size": inp.batch_size,
            "batch_limit_mode": inp.batch_limit_mode,
            "wash_cycle_min": inp.wash_cycle_min,
            "dry_cycle_min": inp.dry_cycle_min,
            "load_washer_min": inp.load_washer_min,
            "unload_transfer_min": inp.unload_transfer_min,
            "load_dryer_min": inp.load_dryer_min,
            "unload_dryer_min": inp.unload_dryer_min,
            "fold_rate_mode": inp.fold_rate_mode,
            "fold_min_per_bag": inp.fold_min_per_bag,
            "fold_lbs_per_hour": inp.fold_lbs_per_hour,
            "employee_count": len(inp.employees),
            "order_count": len({b.order_number for b in bags}),
            "batch_overrides": [asdict(item) for item in inp.batch_overrides],
        },
        "summary": {
            "bags_ready_by_target": ready_by_target,
            "pounds_ready_by_target": lbs_ready,
            "bags_folded_by_target": folded_by_target,
            "pounds_folded_by_target": lbs_folded,
            "first_batch_ready_time": _label(batches[0].ready_to_fold) if batches else None,
            "last_batch_ready_time": _label(batches[-1].ready_to_fold) if batches else None,
            "first_bag_ready_time": _label(first_ready),
            "last_bag_ready_time": _label(last_ready),
            "final_completion_time": _label(final_complete),
            "washer_utilization_pct": round(
                sum(u["utilization_pct"] for u in washer_util) / max(1, len(washer_util)), 1
            ),
            "dryer_utilization_pct": round(
                sum(u["utilization_pct"] for u in dryer_util) / max(1, len(dryer_util)), 1
            ),
            "folder_utilization_pct": round(
                sum(u["utilization_pct"] for u in emp_util if u["role"] == "folder")
                / max(1, sum(1 for u in emp_util if u["role"] == "folder")),
                1,
            ),
            "washer_person_utilization_pct": (
                round(
                    sum(
                        u["utilization_pct"]
                        for u in emp_util
                        if u["role"] == "washer"
                        or any(
                            e.id == u["id"] and _role_capable(e, "washer")
                            for e in inp.employees
                        )
                    )
                    / max(
                        1,
                        sum(
                            1
                            for e in inp.employees
                            if e.active and _role_capable(e, "washer")
                        ),
                    ),
                    1,
                )
            ),
            "employee_handling_utilization_pct": round(
                sum(u["utilization_pct"] for u in emp_util) / max(1, len(emp_util)), 1
            ),
            "avg_ready_bag_wait_for_folder_min": avg_ready_wait,
            "primary_bottleneck": primary,
            "secondary_bottleneck": secondary,
        },
        "ready_to_fold_by_batch": ready_by_batch,
        "availability_30min": intervals_30,
        "bag_rows": bag_rows,
        "batches": [asdict(b) for b in batches],
        "batch_edit_payload": {
            "overrides": [asdict(item) for item in inp.batch_overrides],
            "reset_supported": True,
        },
        "staffing_chart": staffing_chart,
        "employees": [
            {
                "id": e.id,
                "name": e.name,
                "primary_role": e.primary_role,
                "start_time": _label(e.start_min),
                "end_time": _label(e.end_min),
                "secondary_roles": e.secondary_roles,
                "role_schedule": [
                    {"role": role, "start_time": _label(start), "end_time": _label(end)}
                    for role, start, end in e.role_schedule
                ],
            }
            for e in inp.employees
        ],
        "resource_utilization": {
            "washers": washer_util,
            "dryers": dryer_util,
            "employees": emp_util,
        },
        "timelines": {
            "employees": emp_util,
            "washers": [
                {
                    "id": w,
                    "intervals": [
                        {"start": _label(a), "end": _label(b), "label": lab}
                        for a, b, lab in washer_cal.intervals.get(w, [])
                    ],
                }
                for w in washers
            ],
            "dryers": [
                {
                    "id": d,
                    "intervals": [
                        {"start": _label(a), "end": _label(b), "label": lab}
                        for a, b, lab in dryer_cal.intervals.get(d, [])
                    ],
                }
                for d in dryers
            ],
        },
        "recommendations": recommendations,
    }


def _build_recommendations(
    inp: DesInputs,
    bags: list[BagState],
    batches: list[BatchState],
    emp_util: list[dict[str, Any]],
    avg_ready_wait: float,
) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []

    # Capacity vs batch size
    avg = inp.avg_lbs_per_bag or 20
    max_bags_by_lb = max(1, int(inp.washer_capacity_lb // avg)) if avg > 0 else inp.batch_size
    if inp.batch_size > max_bags_by_lb:
        recs.append(
            {
                "id": "cap-batch-size",
                "severity": "batch_capacity",
                "title": "Batch size exceeds washer pound capacity",
                "detail": (
                    f"Current {inp.batch_size}-bag batches at ~{avg:g} lb/bag need "
                    f"{inp.batch_size * avg:g} lb, but washer capacity is {inp.washer_capacity_lb:g} lb. "
                    f"Recommended batch size: {max_bags_by_lb} bags."
                ),
                "actions": [
                    {
                        "id": "use_recommended_batch_all",
                        "label": f"Use {max_bags_by_lb} Bags for All Batches",
                        "patch": {"batch_size": max_bags_by_lb, "batch_limit_mode": "whichever_first"},
                    },
                    {
                        "id": "raise_washer_capacity",
                        "label": "Assign Larger Washer Capacity",
                        "patch": {"washer_capacity_lb": inp.batch_size * avg},
                    },
                ],
            }
        )

    # Folder activity
    if avg_ready_wait >= 15:
        folders = [e for e in inp.employees if e.primary_role == "folder"]
        late = [e for e in folders if e.start_min > inp.start_min + 60]
        if late:
            e0 = late[0]
            new_start = max(inp.start_min, e0.start_min - 30)
            recs.append(
                {
                    "id": "folder-earlier",
                    "severity": "folding",
                    "title": f"{e0.name} starts after bags are already waiting",
                    "detail": (
                        f"Average ready-bag wait for a folder is {avg_ready_wait} min. "
                        f"Starting {e0.name} at {_label(new_start)} is projected to reduce queueing."
                    ),
                    "actions": [
                        {
                            "id": "start_folder_earlier",
                            "label": f"Start {e0.name} at {_label(new_start)}",
                            "patch": {
                                "staffing_event": {
                                    "type": "update_employee",
                                    "employee_id": e0.id,
                                    "start_time": _label(new_start),
                                }
                            },
                        },
                        {
                            "id": "add_temp_folder",
                            "label": f"Add Temporary Folder at {_label(new_start)}",
                            "patch": {
                                "staffing_event": {
                                    "type": "add_employee",
                                    "name": "Temp Folder",
                                    "primary_role": "folder",
                                    "start_time": _label(new_start),
                                    "fold_lbs_per_hour": inp.fold_lbs_per_hour,
                                }
                            },
                        },
                    ],
                }
            )

    # Washer person bottleneck
    washers = [u for u in emp_util if u.get("role") == "washer"]
    if washers:
        top = max(washers, key=lambda u: u["utilization_pct"])
        if top["utilization_pct"] >= 90:
            inject_at = inp.start_min + 90
            recs.append(
                {
                    "id": "add-washer-person",
                    "severity": "washer_labor",
                    "title": "Washer person is saturated",
                    "detail": (
                        f"{top['name']} utilization is {top['utilization_pct']}%. "
                        f"Adding one washer person at {_label(inject_at)} can relieve loading/transfer delays."
                    ),
                    "actions": [
                        {
                            "id": "add_washer_at",
                            "label": f"Add Washer at {_label(inject_at)}",
                            "patch": {
                                "staffing_event": {
                                    "type": "add_employee",
                                    "name": "Washer 2",
                                    "primary_role": "washer",
                                    "start_time": _label(inject_at),
                                },
                                "sim_mode": "continue_from_time",
                                "continue_from_time": _label(inject_at),
                            },
                        }
                    ],
                }
            )

    return recs


def apply_des_action(base_inputs: dict[str, Any], action_patch: dict[str, Any]) -> dict[str, Any]:
    """Apply a recommendation / staffing action patch onto inputs and return new inputs."""
    out = dict(base_inputs or {})
    if not action_patch:
        return out
    if "reset_override" in action_patch:
        out = merge_batch_override(out, {"reset_override": action_patch["reset_override"]})
    if "batch_override" in action_patch and isinstance(action_patch["batch_override"], dict):
        out = merge_batch_override(out, action_patch["batch_override"])
    for key, value in action_patch.items():
        if key in ("reset_override", "batch_override"):
            continue
        if key == "staffing_event" and isinstance(value, dict):
            employees = [dict(e) for e in (out.get("employees") or [])]
            ev = value
            if ev.get("type") == "add_employee":
                employees.append(
                    {
                        "id": ev.get("id") or f"E-NEW-{len(employees) + 1}",
                        "name": ev.get("name") or "New staff",
                        "primary_role": ev.get("primary_role") or "helper",
                        "start_time": ev.get("start_time") or out.get("start_time"),
                        "end_time": ev.get("end_time"),
                        "secondary_roles": ev.get("secondary_roles") or [],
                        "fold_lbs_per_hour": ev.get("fold_lbs_per_hour"),
                        "active": True,
                    }
                )
            elif ev.get("type") == "update_employee":
                for e in employees:
                    if e.get("id") == ev.get("employee_id") or e.get("name") == ev.get("name"):
                        if ev.get("start_time"):
                            e["start_time"] = ev["start_time"]
                        if ev.get("end_time") is not None:
                            e["end_time"] = ev["end_time"]
                        if ev.get("primary_role"):
                            e["primary_role"] = ev["primary_role"]
                        if "secondary_roles" in ev:
                            e["secondary_roles"] = ev["secondary_roles"]
            out["employees"] = employees
        elif key in ("sim_mode", "continue_from_time"):
            out[key] = value
        else:
            out[key] = value
    return out
