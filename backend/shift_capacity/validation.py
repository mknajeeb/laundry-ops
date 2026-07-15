"""Clock parsing, input parsing, and validation."""

from __future__ import annotations

from typing import Any

from backend.shift_capacity.models import (
    BatchOverride,
    Employee,
    EmployeeRates,
    EmployeeRoleWindow,
    EmployeeScheduleWindow,
    Machine,
    Order,
    OrderBagInput,
    ProcessingTimes,
    ShiftConfig,
    SimulationInputs,
    ValidationError,
    ValidationResult,
)


def parse_clock_minutes(raw: Any, *, default: str = "7:00 AM") -> int:
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
        return parse_clock_minutes(default)
    if am_pm == "PM" and hh != 12:
        hh += 12
    if am_pm == "AM" and hh == 12:
        hh = 0
    return hh * 60 + mm


def label_minutes(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    m = int(minutes) % (24 * 60)
    hh = m // 60
    mm = m % 60
    am_pm = "AM" if hh < 12 else "PM"
    h12 = hh % 12 or 12
    return f"{h12}:{mm:02d} {am_pm}"


def _maybe_float(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _maybe_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _exit_policy(raw: Any) -> str:
    text = str(raw or "finish_current_task").strip().lower()
    if text in ("finish_current", "finish_current_task", "finish"):
        return "finish_current_task"
    if text in ("stop_and_reassign", "hard_stop", "stop"):
        return "stop_and_reassign"
    return "finish_current_task"


def _normalize_mode(raw: Any) -> str:
    text = str(raw or "full_run").strip().lower()
    aliases = {
        "full": "full_run",
        "reoptimize_full": "reoptimize_entire_shift",
        "reoptimize": "reoptimize_entire_shift",
        "continue": "continue_from_time",
        "override": "apply_batch_override",
        "recommend": "apply_recommendation",
    }
    return aliases.get(text, text)


def parse_inputs(data: dict[str, Any] | None) -> SimulationInputs:
    raw = dict(data or {})
    nested_shift = raw.get("shift") if isinstance(raw.get("shift"), dict) else {}
    nested_times = raw.get("processing_times") if isinstance(raw.get("processing_times"), dict) else {}
    nested_strategy = raw.get("strategy") if isinstance(raw.get("strategy"), dict) else {}

    start_min = parse_clock_minutes(
        nested_shift.get("start_time") or raw.get("start_time"), default="7:00 AM"
    )
    target_min = parse_clock_minutes(
        nested_shift.get("target_time") or raw.get("target_time"), default="12:00 PM"
    )
    if target_min <= start_min:
        target_min = start_min + 5 * 60
    end_raw = nested_shift.get("end_time") or raw.get("end_time")
    end_min = parse_clock_minutes(end_raw, default=label_minutes(start_min + 8 * 60) or "3:00 PM") if end_raw else start_min + 8 * 60

    summary_interval = int(nested_shift.get("summary_interval_min") or raw.get("summary_interval_min") or 30)
    if summary_interval not in (30, 60):
        summary_interval = 30

    bag_count = max(1, int(raw.get("bag_count") or nested_shift.get("bag_count") or 1))
    avg_lbs = float(raw.get("avg_lbs_per_bag") or nested_shift.get("avg_lbs_per_bag") or 20)
    bag_weights = [float(x) for x in (raw.get("bag_weights") or []) if x is not None]

    shift = ShiftConfig(
        start_min=start_min,
        target_min=target_min,
        end_min=end_min,
        summary_interval_min=summary_interval,
        washer_count=max(1, int(nested_shift.get("washer_count") or raw.get("washer_count") or 1)),
        dryer_count=max(1, int(nested_shift.get("dryer_count") or raw.get("dryer_count") or 1)),
        washer_capacity_lb=float(nested_shift.get("washer_capacity_lb") or raw.get("washer_capacity_lb") or 80),
        dryer_capacity_lb=float(nested_shift.get("dryer_capacity_lb") or raw.get("dryer_capacity_lb") or 80),
        avg_lbs_per_bag=avg_lbs,
        bag_count=bag_count,
        batch_size=max(1, int(nested_shift.get("batch_size") or raw.get("batch_size") or nested_strategy.get("batch_size") or 8)),
        batch_limit_mode=str(  # type: ignore[arg-type]
            nested_shift.get("batch_limit_mode")
            or raw.get("batch_limit_mode")
            or nested_strategy.get("batch_limit_mode")
            or "whichever_first"
        ).strip().lower()
        if str(
            nested_shift.get("batch_limit_mode")
            or raw.get("batch_limit_mode")
            or nested_strategy.get("batch_limit_mode")
            or "whichever_first"
        ).strip().lower()
        in ("bags", "pounds", "whichever_first")
        else "whichever_first",
        priority_first=bool(nested_strategy.get("priority_first", True)),
        order_preserving=bool(nested_strategy.get("order_preserving", True)),
    )

    times = ProcessingTimes(
        weigh_min_per_bag=float(nested_times.get("weigh_min_per_bag") or raw.get("weigh_min_per_bag") or 1),
        sort_min_per_bag=float(nested_times.get("sort_min_per_bag") or raw.get("sort_min_per_bag") or 5),
        load_washer_min=float(nested_times.get("load_washer_min") or raw.get("load_washer_min") or 3),
        wash_cycle_min=float(nested_times.get("wash_cycle_min") or raw.get("wash_cycle_min") or 30),
        transfer_min=float(
            nested_times.get("transfer_min")
            or nested_times.get("unload_transfer_min")
            or raw.get("unload_transfer_min")
            or raw.get("transfer_min")
            or 5
        ),
        load_dryer_min=float(nested_times.get("load_dryer_min") or raw.get("load_dryer_min") or 3),
        dry_cycle_min=float(nested_times.get("dry_cycle_min") or raw.get("dry_cycle_min") or 45),
        unload_dryer_min=float(nested_times.get("unload_dryer_min") or raw.get("unload_dryer_min") or 0),
        fold_rate_mode=str(  # type: ignore[arg-type]
            nested_times.get("fold_rate_mode") or raw.get("fold_rate_mode") or "lbs_per_hour"
        ).strip().lower()
        if str(nested_times.get("fold_rate_mode") or raw.get("fold_rate_mode") or "lbs_per_hour").strip().lower()
        in ("minutes_per_bag", "lbs_per_hour")
        else "lbs_per_hour",
        fold_min_per_bag=float(nested_times.get("fold_min_per_bag") or raw.get("fold_min_per_bag") or 6),
        fold_lbs_per_hour=float(nested_times.get("fold_lbs_per_hour") or raw.get("fold_lbs_per_hour") or 35),
    )

    employees = _parse_employees(raw.get("employees") or [], start_min=start_min, end_min=end_min)
    employees = _apply_shared_role_flags(employees, raw)

    if not employees:
        employees = _default_employees(start_min, end_min, times.fold_lbs_per_hour)

    machines: list[Machine] = []
    for row in raw.get("machines") or []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "").lower()
        if kind not in ("washer", "dryer"):
            continue
        machines.append(
            Machine(
                machine_id=str(row.get("machine_id") or row.get("id")),
                kind=kind,  # type: ignore[arg-type]
                capacity_lb=float(row.get("capacity_lb") or (shift.washer_capacity_lb if kind == "washer" else shift.dryer_capacity_lb)),
            )
        )
    if not machines:
        machines = [
            *[Machine(f"W{i}", "washer", shift.washer_capacity_lb) for i in range(1, shift.washer_count + 1)],
            *[Machine(f"D{i}", "dryer", shift.dryer_capacity_lb) for i in range(1, shift.dryer_count + 1)],
        ]

    orders = _parse_orders(raw.get("orders") or [])
    if not orders:
        orders = _synthetic_orders(bag_count, bag_weights, avg_lbs, shift.batch_size)

    overrides = _parse_overrides(raw.get("batch_overrides") or [])

    mode = _normalize_mode(raw.get("mode") or raw.get("sim_mode") or "full_run")
    continue_from = None
    if raw.get("continue_from_time") is not None or raw.get("continue_from_min") is not None:
        continue_from = (
            int(raw["continue_from_min"])
            if raw.get("continue_from_min") is not None
            else parse_clock_minutes(raw.get("continue_from_time"))
        )
        if mode == "full_run":
            mode = "continue_from_time"

    exit_policy = _exit_policy(raw.get("exit_policy"))
    finish = exit_policy == "finish_current_task"

    return SimulationInputs(
        mode=mode,  # type: ignore[arg-type]
        scenario_id=raw.get("scenario_id"),
        parent_scenario_id=raw.get("parent_scenario_id"),
        continue_from_min=continue_from,
        shift=shift,
        processing_times=times,
        employees=employees,
        machines=machines,
        orders=orders,
        bag_weights=bag_weights,
        batch_overrides=overrides,
        strategy=dict(nested_strategy),
        recommendation_action=raw.get("recommendation_action") if isinstance(raw.get("recommendation_action"), dict) else None,
        change_type=raw.get("change_type"),  # type: ignore[arg-type]
        change_payload=raw.get("change_payload") if isinstance(raw.get("change_payload"), dict) else None,
        weigher_washer_same=_flag(raw, "weigher_washer_same"),
        weigher_sorter_same=_flag(raw, "weigher_sorter_same"),
        sorter_washer_same=_flag(raw, "sorter_washer_same"),
        washer_folder_same=_flag(raw, "washer_folder_same"),
        finish_in_progress_at_exit=finish,
        raw=raw,
    )


def validate_inputs(inp: SimulationInputs) -> ValidationResult:
    errors: list[ValidationError] = []
    if inp.shift.washer_capacity_lb <= 0 or inp.shift.dryer_capacity_lb <= 0:
        errors.append(ValidationError("CAPACITY_INVALID", "Machine capacities must be positive"))
    if inp.shift.batch_size < 1:
        errors.append(ValidationError("BATCH_SIZE_INVALID", "batch_size must be >= 1"))

    seen_emp: set[str] = set()
    for emp in inp.employees:
        if emp.employee_id in seen_emp:
            errors.append(ValidationError("DUPLICATE_EMPLOYEE", f"Duplicate employee_id {emp.employee_id}", {"employee_id": emp.employee_id}))
        seen_emp.add(emp.employee_id)
        # Overlapping role windows
        windows = sorted(emp.role_windows, key=lambda w: w.start_min)
        for prev, cur in zip(windows, windows[1:]):
            if cur.start_min < prev.end_min:
                errors.append(
                    ValidationError(
                        "ROLE_WINDOW_OVERLAP",
                        f"Employee {emp.employee_id} has overlapping role windows",
                        {"employee_id": emp.employee_id},
                    )
                )
        for rw in emp.role_windows:
            qualified = {emp.primary_role.lower(), *[r.lower() for r in emp.qualified_roles]}
            if rw.role not in qualified and rw.role != emp.primary_role.lower():
                # Auto-qualify roles present in schedule to avoid silent failures when UI lists them
                emp.qualified_roles.append(rw.role)
            if rw.role not in {emp.primary_role.lower(), *[r.lower() for r in emp.qualified_roles]}:
                errors.append(
                    ValidationError(
                        "UNQUALIFIED_ROLE",
                        f"Employee {emp.employee_id} is not qualified for role {rw.role}",
                        {"employee_id": emp.employee_id, "role": rw.role},
                    )
                )

    return ValidationResult(accepted=not errors, errors=errors)


def validate_batch_override(
    override: BatchOverride,
    *,
    bags_by_id: dict[str, Any],
    employees: list[Employee],
    washers: list[str],
    dryers: list[str],
    washer_capacity: float,
    frozen_through: int | None = None,
) -> ValidationResult:
    errors: list[ValidationError] = []
    if override.bag_ids:
        missing = [bid for bid in override.bag_ids if bid not in bags_by_id]
        if missing:
            errors.append(ValidationError("BAG_OMISSION", "Override references unknown bags", {"bag_ids": missing}))
        lbs = sum(float(bags_by_id[bid].weight_lb) for bid in override.bag_ids if bid in bags_by_id)
        cap = override.max_pounds if override.max_pounds is not None else washer_capacity
        if lbs > cap + 1e-6:
            errors.append(
                ValidationError(
                    "OVERWEIGHT_BATCH",
                    f"Manual batch exceeds capacity ({lbs:.1f} > {cap:.1f})",
                    {"total_weight_lb": lbs, "capacity_lb": cap},
                )
            )
    emp_by_id = {e.employee_id: e for e in employees}
    for role, person_id in (
        ("washer", override.washer_person_id),
        ("washer", override.transfer_person_id),
        ("washer", override.dryer_load_person_id),
        ("helper", override.helper_employee_id),
    ):
        if not person_id:
            continue
        emp = emp_by_id.get(person_id)
        if emp is None:
            errors.append(
                ValidationError(
                    "EMPLOYEE_NOT_FOUND",
                    f"Forced {role} employee {person_id} not found",
                    {"employee_id": person_id, "role": role},
                )
            )
            continue
        qualified = {emp.primary_role.lower(), *[r.lower() for r in emp.qualified_roles]}
        needed = "washer" if role == "washer" else "helper"
        if role == "washer" and "washer" not in qualified and "helper" not in qualified:
            errors.append(
                ValidationError(
                    "EMPLOYEE_UNQUALIFIED",
                    f"Employee {person_id} is not qualified for washer tasks",
                    {"employee_id": person_id},
                )
            )
        if frozen_through is not None and override.earliest_start_min is not None and override.earliest_start_min < frozen_through:
            errors.append(
                ValidationError(
                    "FROZEN_HISTORY_CONFLICT",
                    "Override earliest start conflicts with frozen history",
                    {"earliest_start_min": override.earliest_start_min, "frozen_through": frozen_through},
                )
            )
    if override.washer_id and override.washer_id not in washers:
        errors.append(ValidationError("MACHINE_NOT_FOUND", f"Washer {override.washer_id} not found", {"washer_id": override.washer_id}))
    if override.dryer_id and override.dryer_id not in dryers:
        errors.append(ValidationError("MACHINE_NOT_FOUND", f"Dryer {override.dryer_id} not found", {"dryer_id": override.dryer_id}))
    return ValidationResult(accepted=not errors, errors=errors)


def _flag(raw: dict[str, Any], name: str) -> bool:
    return str(raw.get(name) or "").lower() in ("1", "true", "yes")


def _parse_employees(rows: list[Any], *, start_min: int, end_min: int) -> list[Employee]:
    employees: list[Employee] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("active") is False:
            continue
        emp_id = str(row.get("employee_id") or row.get("id") or f"E{idx + 1}")
        role = str(row.get("primary_role") or "helper").strip().lower()
        name = str(row.get("display_name") or row.get("name") or f"{role.title()} {idx + 1}")
        start = parse_clock_minutes(row.get("start_time"), default=label_minutes(start_min) or "7:00 AM")
        end_raw = row.get("end_time")
        end = parse_clock_minutes(end_raw, default=label_minutes(end_min) or "3:00 PM") if end_raw else end_min
        secondary = [
            str(r).strip().lower()
            for r in (row.get("qualified_roles") or row.get("secondary_roles") or row.get("allowed_secondary_roles") or [])
            if str(r).strip()
        ]
        role_windows: list[EmployeeRoleWindow] = []
        for window in row.get("role_windows") or row.get("role_schedule") or []:
            if not isinstance(window, dict) or not window.get("role"):
                continue
            role_windows.append(
                EmployeeRoleWindow(
                    role=str(window["role"]).strip().lower(),
                    start_min=parse_clock_minutes(
                        window.get("start_time") or window.get("from"),
                        default=label_minutes(start) or "7:00 AM",
                    ),
                    end_min=parse_clock_minutes(
                        window.get("end_time") or window.get("to"),
                        default=label_minutes(end) or "3:00 PM",
                    ),
                )
            )
        role_windows.sort(key=lambda w: w.start_min)
        # Reject overlaps early
        for prev, cur in zip(role_windows, role_windows[1:]):
            if cur.start_min < prev.end_min:
                raise ValueError(f"Employee {emp_id} has overlapping role_schedule windows")

        rates = EmployeeRates(
            weigh_min_per_bag=_maybe_float(row.get("weigh_min_per_bag")),
            sort_min_per_bag=_maybe_float(row.get("sort_min_per_bag")),
            load_washer_min=_maybe_float(row.get("load_washer_min")),
            transfer_min=_maybe_float(row.get("transfer_min") or row.get("unload_transfer_min")),
            load_dryer_min=_maybe_float(row.get("load_dryer_min")),
            unload_dryer_min=_maybe_float(row.get("unload_dryer_min")),
            fold_min_per_bag=_maybe_float(row.get("fold_min_per_bag")),
            fold_lbs_per_hour=_maybe_float(row.get("fold_lbs_per_hour")),
        )
        employees.append(
            Employee(
                employee_id=emp_id,
                display_name=name,
                primary_role=role,
                qualified_roles=secondary,
                hourly_rate=_maybe_float(row.get("hourly_rate")),
                active=True,
                default_rates=rates,
                schedule_windows=[
                    EmployeeScheduleWindow(
                        start_min=start,
                        end_min=end,
                        exit_policy=_exit_policy(row.get("exit_policy")),  # type: ignore[arg-type]
                    )
                ],
                role_windows=role_windows,
            )
        )
    return employees


def _apply_shared_role_flags(employees: list[Employee], raw: dict[str, Any]) -> list[Employee]:
    def merge(primary_role: str, secondary_role: str) -> None:
        nonlocal employees
        primaries = [e for e in employees if e.primary_role == primary_role]
        secondaries = [e for e in employees if e.primary_role == secondary_role]
        if not primaries:
            return
        primary = primaries[0]
        if secondary_role not in primary.qualified_roles:
            primary.qualified_roles.append(secondary_role)
        if secondaries and secondaries[0].employee_id != primary.employee_id:
            employees = [e for e in employees if e.employee_id != secondaries[0].employee_id]

    if _flag(raw, "weigher_washer_same"):
        merge("weigher", "washer")
    if _flag(raw, "weigher_sorter_same"):
        merge("weigher", "sorter")
    if _flag(raw, "sorter_washer_same"):
        merge("sorter", "washer")
    if _flag(raw, "washer_folder_same"):
        merge("washer", "folder")
    return employees


def _default_employees(start_min: int, end_min: int, fold_lbs: float) -> list[Employee]:
    def emp(eid: str, name: str, role: str, start: int, **rates: Any) -> Employee:
        return Employee(
            employee_id=eid,
            display_name=name,
            primary_role=role,
            schedule_windows=[EmployeeScheduleWindow(start_min=start, end_min=end_min)],
            default_rates=EmployeeRates(**rates),
        )

    return [
        emp("E-WEIGH-1", "Weigher 1", "weigher", start_min),
        emp("E-SORT-1", "Sorter 1", "sorter", start_min),
        emp("E-WASH-1", "Washer 1", "washer", start_min),
        emp("E-FOLD-1", "Folder 1", "folder", start_min, fold_lbs_per_hour=fold_lbs),
        emp("E-FOLD-2", "Folder 2", "folder", start_min + 60, fold_lbs_per_hour=max(fold_lbs, 40)),
        emp("E-FOLD-3", "Folder 3", "folder", start_min + 150, fold_lbs_per_hour=fold_lbs),
    ]


def _parse_orders(rows: list[Any]) -> list[Order]:
    orders: list[Order] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        n = max(1, int(row.get("bag_count") or 1))
        weights = [float(x) for x in (row.get("weights") or row.get("bag_weights") or []) if x is not None]
        bag_rows: list[OrderBagInput] = []
        for bag_row in row.get("bags") or []:
            if not isinstance(bag_row, dict):
                continue
            bag_rows.append(
                OrderBagInput(
                    bag_id=str(bag_row["bag_id"]) if bag_row.get("bag_id") else None,
                    weight_lb=_maybe_float(bag_row.get("weight") or bag_row.get("weight_lb")),
                    priority=int(bag_row.get("priority") or row.get("priority") or 100),
                    rush=bool(bag_row.get("rush", row.get("rush"))),
                    manual_batch_lock=_maybe_int(bag_row.get("manual_batch_lock")),
                )
            )
        orders.append(
            Order(
                order_id=str(row.get("order_id") or row.get("order_number") or f"ORD-{idx + 1}"),
                bag_count=n,
                total_weight_lb=_maybe_float(row.get("total_weight") or row.get("total_weight_lb")),
                bag_weights=weights,
                bags=bag_rows,
                rush=bool(row.get("rush")),
                priority=int(row.get("priority") or 100),
                required_by_min=(
                    parse_clock_minutes(row["required_complete_time"])
                    if row.get("required_complete_time") or row.get("required_by")
                    else None
                ),
                requires_two_washers=bool(row.get("two_washer") or row.get("requires_two_washers")),
                requires_two_dryers=bool(row.get("two_dryer") or row.get("requires_two_dryers")),
                allow_splitting=bool(row.get("allow_splitting", True)),
            )
        )
    return orders


def _synthetic_orders(bag_count: int, bag_weights: list[float], avg_lbs: float, batch_size: int) -> list[Order]:
    weights = list(bag_weights)
    while len(weights) < bag_count:
        weights.append(avg_lbs)
    weights = weights[:bag_count]
    orders: list[Order] = []
    remaining = bag_count
    cursor = 0
    order_idx = 1
    while remaining > 0:
        n = min(batch_size, remaining)
        chunk = weights[cursor : cursor + n]
        orders.append(
            Order(
                order_id=f"ORD-{order_idx}",
                bag_count=n,
                bag_weights=chunk,
                total_weight_lb=sum(chunk),
            )
        )
        remaining -= n
        cursor += n
        order_idx += 1
    return orders


def _parse_overrides(rows: list[Any]) -> list[BatchOverride]:
    overrides: list[BatchOverride] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        number = int(row.get("batch_number") or row.get("sequence") or 0)
        if number < 1:
            raise ValueError("batch_overrides.batch_number must be >= 1")
        scope = str(row.get("apply_scope") or "this_batch_only").strip().lower()
        if scope in ("this_batch_and_following", "from_this_batch_onward"):
            scope = "from_this_batch"
        if scope not in ("this_batch_only", "from_this_batch", "all_future_unlocked"):
            raise ValueError("batch_overrides.apply_scope must be this_batch_only, from_this_batch, or all_future_unlocked")
        earliest = None
        if row.get("earliest_start") or row.get("planned_start_time") or row.get("planned_start_min") is not None:
            earliest = (
                int(row["planned_start_min"])
                if row.get("planned_start_min") is not None
                else parse_clock_minutes(row.get("earliest_start") or row.get("planned_start_time"))
            )
        overrides.append(
            BatchOverride(
                batch_number=number,
                apply_scope=scope,  # type: ignore[arg-type]
                bag_ids=[str(x) for x in (row.get("bag_ids") or [])] or None,
                excluded_bag_ids=[str(x) for x in (row.get("excluded_bag_ids") or [])] or None,
                batch_size=_maybe_int(row.get("batch_size")),
                max_pounds=_maybe_float(row.get("max_pounds")),
                washer_id=str(row["washer_id"]) if row.get("washer_id") else None,
                dryer_id=str(row["dryer_id"]) if row.get("dryer_id") else None,
                washer_person_id=str(row["washer_person_id"]) if row.get("washer_person_id") else None,
                transfer_person_id=str(row["transfer_person_id"]) if row.get("transfer_person_id") else None,
                dryer_load_person_id=str(row["dryer_load_person_id"]) if row.get("dryer_load_person_id") else None,
                helper_employee_id=str(row.get("helper_employee_id") or row.get("extra_helper_id") or "") or None,
                priority=_maybe_int(row.get("priority")),
                earliest_start_min=earliest,
                locked_start=bool(row.get("locked_start") or row.get("strict_resource_lock")),
                pause_sorting=row.get("pause_sorting") if row.get("pause_sorting") is not None else row.get("sorting_paused"),
                sorter_helps_washer=row.get("sorter_helps_washer"),
                folder_helps_washer=row.get("folder_helps_washer"),
                locked=bool(row.get("locked")),
            )
        )
    return overrides
