"""Core schemas for the bag-level DES engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

BatchLimitMode = Literal["bags", "pounds", "whichever_first"]
FoldRateMode = Literal["minutes_per_bag", "lbs_per_hour"]
ExitPolicy = Literal["finish_current_task", "stop_and_reassign"]
ApplyScope = Literal["this_batch_only", "from_this_batch", "all_future_unlocked"]
Provenance = Literal["preserved", "in_progress_preserved", "recalculated", "manual_override"]
SimMode = Literal[
    "full_run",
    "continue_from_time",
    "reoptimize_entire_shift",
    "apply_batch_override",
    "apply_recommendation",
    "undo",
]
ChangeType = Literal[
    "STAFF_INJECTION",
    "ROLE_SWITCH",
    "BATCH_OVERRIDE",
    "RECOMMENDATION_APPLIED",
    "INPUT_EDIT",
]


def new_id(prefix: str = "scn") -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


@dataclass
class EmployeeScheduleWindow:
    start_min: int
    end_min: int | None = None
    exit_policy: ExitPolicy = "finish_current_task"


@dataclass
class EmployeeRoleWindow:
    role: str
    start_min: int
    end_min: int


@dataclass
class EmployeeRates:
    weigh_min_per_bag: float | None = None
    sort_min_per_bag: float | None = None
    load_washer_min: float | None = None
    transfer_min: float | None = None
    load_dryer_min: float | None = None
    unload_dryer_min: float | None = None
    fold_min_per_bag: float | None = None
    fold_lbs_per_hour: float | None = None


@dataclass
class Employee:
    employee_id: str
    display_name: str
    primary_role: str
    qualified_roles: list[str] = field(default_factory=list)
    hourly_rate: float | None = None
    active: bool = True
    default_rates: EmployeeRates = field(default_factory=EmployeeRates)
    schedule_windows: list[EmployeeScheduleWindow] = field(default_factory=list)
    role_windows: list[EmployeeRoleWindow] = field(default_factory=list)

    def start_min(self) -> int:
        if self.schedule_windows:
            return min(w.start_min for w in self.schedule_windows)
        return 0

    def end_min(self) -> int | None:
        ends = [w.end_min for w in self.schedule_windows if w.end_min is not None]
        return max(ends) if ends else None

    def exit_policy(self) -> ExitPolicy:
        if self.schedule_windows:
            return self.schedule_windows[0].exit_policy
        return "finish_current_task"


@dataclass
class Machine:
    machine_id: str
    kind: Literal["washer", "dryer"]
    capacity_lb: float


@dataclass
class OrderBagInput:
    bag_id: str | None = None
    weight_lb: float | None = None
    priority: int = 100
    rush: bool = False
    manual_batch_lock: int | None = None


@dataclass
class Order:
    order_id: str
    bag_count: int
    total_weight_lb: float | None = None
    bag_weights: list[float] = field(default_factory=list)
    bags: list[OrderBagInput] = field(default_factory=list)
    rush: bool = False
    priority: int = 100
    required_by_min: int | None = None
    requires_two_washers: bool = False
    requires_two_dryers: bool = False
    allow_splitting: bool = True


@dataclass
class Bag:
    bag_id: str
    order_id: str
    sequence_in_order: int
    weight_lb: float
    weight_source: Literal["exact", "estimated"] = "estimated"
    priority: int = 100
    rush: bool = False
    requires_two_washers: bool = False
    requires_two_dryers: bool = False
    required_by: int | None = None
    batch_id: str | None = None
    batch_sequence: int | None = None
    washer_id: str | None = None
    dryer_id: str | None = None
    folder_employee_id: str | None = None
    manual_batch_lock: int | None = None

    entry_time: int | None = None
    weigh_start: int | None = None
    weigh_end: int | None = None
    sort_start: int | None = None
    sort_end: int | None = None
    available_to_wash: int | None = None
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
    dryer_unload_start: int | None = None
    dryer_unload_end: int | None = None
    ready_to_fold: int | None = None
    fold_start: int | None = None
    fold_end: int | None = None
    completed_at: int | None = None

    weighed_by_employee_id: str | None = None
    sorted_by_employee_id: str | None = None
    washer_loaded_by_employee_id: str | None = None
    transferred_by_employee_id: str | None = None
    dryer_loaded_by_employee_id: str | None = None
    dryer_unloaded_by_employee_id: str | None = None
    folded_by_employee_id: str | None = None

    wait_for_weigh_minutes: int | None = None
    wait_for_sort_minutes: int | None = None
    wait_for_batch_minutes: int | None = None
    wait_for_washer_minutes: int | None = None
    wait_for_transfer_minutes: int | None = None
    wait_for_dryer_minutes: int | None = None
    wait_for_folder_minutes: int | None = None
    total_elapsed_minutes: int | None = None

    stage_provenance: dict[str, Provenance] = field(default_factory=dict)

    def recompute_waits(self) -> None:
        def gap_min(a: int | None, b: int | None) -> int | None:
            """Gap in whole minutes (floor) for API compat; times are seconds."""
            if a is None or b is None:
                return None
            return max(0, (b - a) // 60)

        self.wait_for_weigh_minutes = gap_min(self.entry_time, self.weigh_start)
        self.wait_for_sort_minutes = gap_min(self.weigh_end, self.sort_start)
        self.wait_for_batch_minutes = gap_min(self.sort_end, self.available_to_wash)
        self.wait_for_washer_minutes = gap_min(self.available_to_wash or self.sort_end, self.washer_load_start)
        self.wait_for_transfer_minutes = gap_min(self.wash_end, self.transfer_start)
        self.wait_for_dryer_minutes = gap_min(self.transfer_end or self.wash_end, self.dryer_load_start)
        self.wait_for_folder_minutes = gap_min(self.ready_to_fold, self.fold_start)
        self.total_elapsed_minutes = gap_min(self.entry_time, self.completed_at)


@dataclass
class BatchOverride:
    batch_number: int
    apply_scope: ApplyScope = "this_batch_only"
    bag_ids: list[str] | None = None
    excluded_bag_ids: list[str] | None = None
    batch_size: int | None = None
    max_pounds: float | None = None
    washer_id: str | None = None
    dryer_id: str | None = None
    washer_person_id: str | None = None
    transfer_person_id: str | None = None
    dryer_load_person_id: str | None = None
    helper_employee_id: str | None = None
    priority: int | None = None
    earliest_start_min: int | None = None
    locked_start: bool = False
    pause_sorting: bool | None = None
    sorter_helps_washer: bool | None = None
    folder_helps_washer: bool | None = None
    locked: bool = False


@dataclass
class Batch:
    batch_id: str
    sequence: int
    bag_ids: list[str] = field(default_factory=list)
    order_ids: list[str] = field(default_factory=list)
    total_bags: int = 0
    total_weight_lb: float = 0.0
    washer_id: str | None = None
    dryer_id: str | None = None
    locked: bool = False
    override_source: str | None = None
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
    provenance: Provenance = "recalculated"


@dataclass
class Task:
    task_id: str
    task_type: str
    start_min: int
    end_min: int
    resource_id: str
    bag_ids: list[str] = field(default_factory=list)
    batch_id: str | None = None
    required_role: str | None = None
    provenance: Provenance = "recalculated"


@dataclass
class Reservation:
    reservation_id: str
    resource_id: str
    resource_type: str  # employee | washer_machine | dryer_machine
    start: int
    end: int
    task_id: str
    task_type: str
    bag_ids: list[str] = field(default_factory=list)
    batch_id: str | None = None
    provenance: Provenance = "recalculated"
    required_role: str | None = None
    hard_assignment: bool = False

    # Back-compat alias used by older call sites
    @property
    def employee_role(self) -> str | None:
        return self.required_role


@dataclass
class ProcessingTimes:
    # Minute-valued fields remain the API/compat inputs. Scheduler converts to seconds.
    weigh_min_per_bag: float = 1.0
    weigh_sec_per_bag: float = 60.0
    sort_min_per_bag: float = 5.0
    load_washer_min: float = 3.0
    wash_cycle_min: float = 30.0
    transfer_min: float = 5.0
    load_dryer_min: float = 3.0
    dry_cycle_min: float = 45.0
    unload_dryer_min: float = 0.0
    fold_rate_mode: FoldRateMode = "lbs_per_hour"
    fold_min_per_bag: float = 6.0
    fold_lbs_per_hour: float = 35.0


@dataclass
class ShiftConfig:
    # NOTE: start_min/target_min/end_min store *seconds from midnight* internally.
    start_min: int
    target_min: int
    end_min: int | None = None
    summary_interval_min: int = 30
    planning_block_size_min: int = 60
    washer_count: int = 1
    dryer_count: int = 1
    washer_capacity_lb: float = 80.0
    dryer_capacity_lb: float = 80.0
    avg_lbs_per_bag: float = 20.0
    bag_count: int = 0
    batch_size: int = 8
    batch_limit_mode: BatchLimitMode = "whichever_first"
    priority_first: bool = True
    order_preserving: bool = True


@dataclass
class SimulationInputs:
    mode: SimMode = "full_run"
    scenario_id: str | None = None
    parent_scenario_id: str | None = None
    continue_from_min: int | None = None  # seconds from midnight internally
    shift: ShiftConfig = field(default_factory=lambda: ShiftConfig(7 * 3600, 12 * 3600))
    processing_times: ProcessingTimes = field(default_factory=ProcessingTimes)
    employees: list[Employee] = field(default_factory=list)
    machines: list[Machine] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)
    bag_weights: list[float] = field(default_factory=list)
    batch_overrides: list[BatchOverride] = field(default_factory=list)
    strategy: dict[str, Any] = field(default_factory=dict)
    recommendation_action: dict[str, Any] | None = None
    change_type: ChangeType | None = None
    change_payload: dict[str, Any] | None = None
    # Compatibility flags from legacy payload
    weigher_washer_same: bool = False
    weigher_sorter_same: bool = False
    sorter_washer_same: bool = False
    washer_folder_same: bool = False
    finish_in_progress_at_exit: bool = True
    # Management planning mode: explicit staffing, Dry role, no transfer double-count
    management_mode: bool = False
    # Compiled management staffing plan metadata (for response echo / debugging)
    staffing_plan_data: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationError:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.details}


@dataclass
class ValidationResult:
    accepted: bool = True
    errors: list[ValidationError] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"accepted": self.accepted, "errors": [e.as_dict() for e in self.errors]}


@dataclass
class ContinuationMeta:
    history_frozen_through: str | None = None
    history_frozen_through_min: int | None = None
    recalculated_from: str | None = None
    recalculated_from_min: int | None = None
    preserved_task_count: int = 0
    in_progress_task_count: int = 0
    recalculated_task_count: int = 0
    preserved_batch_ids: list[str] = field(default_factory=list)
    recalculated_batch_ids: list[str] = field(default_factory=list)
    event_queue_starts_at_min: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "history_frozen_through": self.history_frozen_through,
            "history_frozen_through_min": self.history_frozen_through_min,
            "recalculated_from": self.recalculated_from,
            "recalculated_from_min": self.recalculated_from_min,
            "preserved_task_count": self.preserved_task_count,
            "in_progress_task_count": self.in_progress_task_count,
            "recalculated_task_count": self.recalculated_task_count,
            "preserved_batch_ids": list(self.preserved_batch_ids),
            "recalculated_batch_ids": list(self.recalculated_batch_ids),
            "event_queue_starts_at_min": self.event_queue_starts_at_min,
        }


@dataclass
class SimulationState:
    inputs: SimulationInputs
    bags: list[Bag] = field(default_factory=list)
    batches: list[Batch] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    employee_calendars: dict[str, list[Reservation]] = field(default_factory=dict)
    machine_calendars: dict[str, list[Reservation]] = field(default_factory=dict)
    continuation: ContinuationMeta = field(default_factory=ContinuationMeta)
    validation: ValidationResult = field(default_factory=ValidationResult)
    scenario_id: str = field(default_factory=lambda: new_id("scn"))
    parent_scenario_id: str | None = None
    mode: SimMode = "full_run"
