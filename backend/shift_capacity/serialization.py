"""API response formatting with provenance and UI-ready timelines."""

from __future__ import annotations

from typing import Any

from backend.shift_capacity.models import Bag, SimulationState
from backend.shift_capacity.summaries import compute_kpis, ready_by_batch, staffing_summary, time_summary
from backend.shift_capacity.validation import label_minutes


def serialize_bag(bag: Bag, emp_names: dict[str, str]) -> dict[str, Any]:
    def name(emp_id: str | None) -> str | None:
        if not emp_id:
            return None
        return emp_names.get(emp_id, emp_id)

    return {
        "order": bag.order_id,
        "order_id": bag.order_id,
        "bag_id": bag.bag_id,
        "sequence_in_order": bag.sequence_in_order,
        "weight": bag.weight_lb,
        "weight_lb": bag.weight_lb,
        "weight_source": bag.weight_source,
        "weight_estimated": bag.weight_source == "estimated",
        "priority": bag.priority,
        "rush": bag.rush,
        "batch": bag.batch_sequence,
        "batch_id": bag.batch_id,
        "weigh_start": label_minutes(bag.weigh_start),
        "weigh_end": label_minutes(bag.weigh_end),
        "sort_start": label_minutes(bag.sort_start),
        "sort_end": label_minutes(bag.sort_end),
        "available_to_wash": label_minutes(bag.available_to_wash or bag.sort_end),
        "washer": bag.washer_id,
        "washer_id": bag.washer_id,
        "washer_load_start": label_minutes(bag.washer_load_start),
        "washer_load_end": label_minutes(bag.washer_load_end),
        "wash_start": label_minutes(bag.wash_start),
        "wash_end": label_minutes(bag.wash_end),
        "transfer_start": label_minutes(bag.transfer_start),
        "transfer_end": label_minutes(bag.transfer_end),
        "dryer": bag.dryer_id,
        "dryer_id": bag.dryer_id,
        "dryer_load_start": label_minutes(bag.dryer_load_start),
        "dryer_load_end": label_minutes(bag.dryer_load_end),
        "dry_start": label_minutes(bag.dry_start),
        "dry_end": label_minutes(bag.dry_end),
        "dryer_unload_start": label_minutes(bag.dryer_unload_start),
        "dryer_unload_end": label_minutes(bag.dryer_unload_end),
        "ready_to_fold": label_minutes(bag.ready_to_fold),
        "folder": name(bag.folded_by_employee_id),
        "folder_employee_id": bag.folder_employee_id,
        "fold_start": label_minutes(bag.fold_start),
        "fold_end": label_minutes(bag.fold_end),
        "completed": label_minutes(bag.completed_at),
        "completed_at": label_minutes(bag.completed_at),
        "waiting_before_wash": bag.wait_for_washer_minutes,
        "waiting_before_dry": bag.wait_for_dryer_minutes,
        "waiting_for_folder": bag.wait_for_folder_minutes,
        "wait_for_weigh_minutes": bag.wait_for_weigh_minutes,
        "wait_for_sort_minutes": bag.wait_for_sort_minutes,
        "wait_for_batch_minutes": bag.wait_for_batch_minutes,
        "wait_for_washer_minutes": bag.wait_for_washer_minutes,
        "wait_for_transfer_minutes": bag.wait_for_transfer_minutes,
        "wait_for_dryer_minutes": bag.wait_for_dryer_minutes,
        "wait_for_folder_minutes": bag.wait_for_folder_minutes,
        "total_elapsed": bag.total_elapsed_minutes,
        "total_elapsed_minutes": bag.total_elapsed_minutes,
        "weighed_by": name(bag.weighed_by_employee_id),
        "sorted_by": name(bag.sorted_by_employee_id),
        "washer_loaded_by": name(bag.washer_loaded_by_employee_id),
        "transferred_by": name(bag.transferred_by_employee_id),
        "dryer_loaded_by": name(bag.dryer_loaded_by_employee_id),
        "dryer_unloaded_by": name(bag.dryer_unloaded_by_employee_id),
        "folded_by": name(bag.folded_by_employee_id),
        "weighed_by_employee_id": bag.weighed_by_employee_id,
        "sorted_by_employee_id": bag.sorted_by_employee_id,
        "washer_loaded_by_employee_id": bag.washer_loaded_by_employee_id,
        "transferred_by_employee_id": bag.transferred_by_employee_id,
        "dryer_loaded_by_employee_id": bag.dryer_loaded_by_employee_id,
        "dryer_unloaded_by_employee_id": bag.dryer_unloaded_by_employee_id,
        "folded_by_employee_id": bag.folded_by_employee_id,
        "provenance": dict(bag.stage_provenance),
    }


def serialize_state(
    state: SimulationState,
    *,
    recommendations: list[dict[str, Any]] | None = None,
    bags_moved: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    emp_names = {e.employee_id: e.display_name for e in state.inputs.employees}
    emp_names["Unassigned"] = "Unassigned"
    kpis = compute_kpis(state)
    interval = state.inputs.shift.summary_interval_min
    bags = [serialize_bag(b, emp_names) for b in state.bags]
    batches = ready_by_batch(state)
    time_rows = time_summary(state, interval)
    staff_rows = staffing_summary(state)

    employee_timeline = []
    for rid, rows in state.employee_calendars.items():
        employee_timeline.append(
            {
                "resource_id": rid,
                "name": emp_names.get(rid, rid),
                "intervals": [
                    {
                        "start": label_minutes(r.start),
                        "end": label_minutes(r.end),
                        "start_min": r.start,
                        "end_min": r.end,
                        "task": r.task_type,
                        "task_id": r.task_id,
                        "bag_ids": list(r.bag_ids),
                        "batch_id": r.batch_id,
                        "provenance": r.provenance,
                        "label": r.task_type,
                    }
                    for r in rows
                ],
            }
        )

    machine_timeline = []
    for rid, rows in state.machine_calendars.items():
        machine_timeline.append(
            {
                "resource_id": rid,
                "intervals": [
                    {
                        "start": label_minutes(r.start),
                        "end": label_minutes(r.end),
                        "start_min": r.start,
                        "end_min": r.end,
                        "task": r.task_type,
                        "task_id": r.task_id,
                        "bag_ids": list(r.bag_ids),
                        "batch_id": r.batch_id,
                        "provenance": r.provenance,
                        "label": r.task_type,
                    }
                    for r in rows
                ],
            }
        )

    overlap_errors = []
    if not state.validation.accepted:
        overlap_errors = [
            e.details.get("resource_id") or e.code
            for e in state.validation.errors
            if e.code in ("OVERLAP", "EMPLOYEE_OVERLAP", "MACHINE_OVERLAP", "RESOURCE_OVERLAP")
        ]

    validation_errors = [e.message for e in state.validation.errors]

    return {
        "engine": "bag_des_v2",
        "scenario_id": state.scenario_id,
        "parent_scenario_id": state.parent_scenario_id,
        "mode": state.mode,
        "validation": state.validation.as_dict(),
        "continuation": state.continuation.as_dict(),
        "partial_resim": state.continuation.as_dict(),
        "kpis": kpis,
        "summary": kpis,
        "bags": bags,
        "bag_rows": bags,
        "batches": [
            {
                "batch_number": b.sequence,
                "batch_id": b.batch_id,
                "bag_ids": list(b.bag_ids),
                "order_ids": list(b.order_ids),
                "total_bags": b.total_bags,
                "total_weight_lb": b.total_weight_lb,
                "washer_id": b.washer_id,
                "dryer_id": b.dryer_id,
                "locked": b.locked,
                "override_source": b.override_source,
                "washer_load_start": label_minutes(b.washer_load_start),
                "washer_load_end": label_minutes(b.washer_load_end),
                "wash_start": label_minutes(b.wash_start),
                "wash_end": label_minutes(b.wash_end),
                "transfer_start": label_minutes(b.transfer_start),
                "transfer_end": label_minutes(b.transfer_end),
                "dryer_load_start": label_minutes(b.dryer_load_start),
                "dryer_load_end": label_minutes(b.dryer_load_end),
                "dry_start": label_minutes(b.dry_start),
                "dry_end": label_minutes(b.dry_end),
                "ready_to_fold": label_minutes(b.ready_to_fold),
                "provenance": b.provenance,
            }
            for b in state.batches
        ],
        "ready_to_fold_by_batch": batches,
        "time_summary": time_rows,
        "availability_30min": time_rows if interval == 30 else time_summary(state, 30),
        "staffing_summary": staff_rows,
        "staffing_chart": staff_rows,
        "employee_timeline": employee_timeline,
        "machine_timeline": machine_timeline,
        "timelines": {
            "employees": {
                rid: [
                    {
                        "start": label_minutes(r.start),
                        "end": label_minutes(r.end),
                        "label": r.task_type,
                        "provenance": r.provenance,
                        "bag_ids": list(r.bag_ids),
                        "batch_id": r.batch_id,
                    }
                    for r in rows
                ]
                for rid, rows in state.employee_calendars.items()
            },
            "washers": {
                rid: [
                    {
                        "start": label_minutes(r.start),
                        "end": label_minutes(r.end),
                        "label": r.task_type,
                        "provenance": r.provenance,
                        "bag_ids": list(r.bag_ids),
                        "batch_id": r.batch_id,
                    }
                    for r in rows
                ]
                for rid, rows in state.machine_calendars.items()
                if rid.startswith("W")
            },
            "dryers": {
                rid: [
                    {
                        "start": label_minutes(r.start),
                        "end": label_minutes(r.end),
                        "label": r.task_type,
                        "provenance": r.provenance,
                        "bag_ids": list(r.bag_ids),
                        "batch_id": r.batch_id,
                    }
                    for r in rows
                ]
                for rid, rows in state.machine_calendars.items()
                if rid.startswith("D")
            },
        },
        "recommendations": recommendations or [],
        "overlap_errors": overlap_errors if not state.validation.accepted else [],
        "simulation_valid": state.validation.accepted and not overlap_errors,
        "validation_errors": validation_errors,
        "bags_moved": bags_moved or [],
        "employees": [
            {
                "id": e.employee_id,
                "employee_id": e.employee_id,
                "name": e.display_name,
                "display_name": e.display_name,
                "primary_role": e.primary_role,
                "qualified_roles": list(e.qualified_roles),
                "start_time": label_minutes(e.start_min()),
                "end_time": label_minutes(e.end_min()),
                "hourly_rate": e.hourly_rate,
                "role_schedule": [
                    {
                        "role": rw.role,
                        "from": label_minutes(rw.start_min),
                        "to": label_minutes(rw.end_min),
                        "start_time": label_minutes(rw.start_min),
                        "end_time": label_minutes(rw.end_min),
                    }
                    for rw in e.role_windows
                ],
            }
            for e in state.inputs.employees
        ],
        "resource_utilization": {
            "washers": [
                {"id": rid, "utilization_pct": _util(rows, state.inputs.shift.start_min, state.inputs.shift.target_min)}
                for rid, rows in state.machine_calendars.items()
                if rid.startswith("W")
            ],
            "dryers": [
                {"id": rid, "utilization_pct": _util(rows, state.inputs.shift.start_min, state.inputs.shift.target_min)}
                for rid, rows in state.machine_calendars.items()
                if rid.startswith("D")
            ],
        },
        "inputs": {
            "start_time": label_minutes(state.inputs.shift.start_min),
            "target_time": label_minutes(state.inputs.shift.target_min),
            "bag_count": len(state.bags),
            "avg_lbs_per_bag": state.inputs.shift.avg_lbs_per_bag,
            "washer_count": state.inputs.shift.washer_count,
            "dryer_count": state.inputs.shift.dryer_count,
            "washer_capacity_lb": state.inputs.shift.washer_capacity_lb,
            "dryer_capacity_lb": state.inputs.shift.dryer_capacity_lb,
            "batch_size": state.inputs.shift.batch_size,
            "batch_limit_mode": state.inputs.shift.batch_limit_mode,
            "summary_interval_min": state.inputs.shift.summary_interval_min,
            "wash_cycle_min": state.inputs.processing_times.wash_cycle_min,
            "dry_cycle_min": state.inputs.processing_times.dry_cycle_min,
            "load_washer_min": state.inputs.processing_times.load_washer_min,
            "unload_transfer_min": state.inputs.processing_times.transfer_min,
            "load_dryer_min": state.inputs.processing_times.load_dryer_min,
            "unload_dryer_min": state.inputs.processing_times.unload_dryer_min,
            "fold_rate_mode": state.inputs.processing_times.fold_rate_mode,
            "fold_min_per_bag": state.inputs.processing_times.fold_min_per_bag,
            "fold_lbs_per_hour": state.inputs.processing_times.fold_lbs_per_hour,
            "employee_count": len(state.inputs.employees),
            "order_count": len({b.order_id for b in state.bags}),
            "batch_overrides": [
                {
                    "batch_number": o.batch_number,
                    "apply_scope": o.apply_scope,
                    "bag_ids": o.bag_ids,
                    "batch_size": o.batch_size,
                    "max_pounds": o.max_pounds,
                }
                for o in state.inputs.batch_overrides
            ],
        },
        "batch_edit_payload": {
            "batches": batches,
            "employees": [
                {"id": e.employee_id, "name": e.display_name, "primary_role": e.primary_role}
                for e in state.inputs.employees
            ],
            "washers": [m.machine_id for m in state.inputs.machines if m.kind == "washer"],
            "dryers": [m.machine_id for m in state.inputs.machines if m.kind == "dryer"],
        },
    }


def _util(rows, start: int, end: int) -> float:
    if end <= start:
        return 0.0
    busy = 0
    for r in rows:
        lo = max(r.start, start)
        hi = min(r.end, end)
        if hi > lo:
            busy += hi - lo
    return round(100.0 * busy / (end - start), 1)
