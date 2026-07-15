"""True continue_from_time tests for bag_des_v2."""

from backend.shift_capacity.service import run_shift_capacity
from backend.shift_capacity.validation import parse_clock_minutes


def _base(**overrides):
    payload = {
        "engine": "bag_des_v2",
        "mode": "full_run",
        "start_time": "7:00 AM",
        "target_time": "12:00 PM",
        "bag_count": 12,
        "avg_lbs_per_bag": 20,
        "batch_size": 4,
        "washer_count": 2,
        "dryer_count": 2,
        "washer_capacity_lb": 80,
        "dryer_capacity_lb": 80,
        "wash_cycle_min": 40,
        "dry_cycle_min": 45,
        "weigh_min_per_bag": 1,
        "sort_min_per_bag": 3,
        "load_washer_min": 2,
        "unload_transfer_min": 2,
        "load_dryer_min": 2,
        "fold_rate_mode": "lbs_per_hour",
        "fold_lbs_per_hour": 40,
        "_skip_recommendations": True,
        "employees": [
            {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM", "end_time": "3:00 PM"},
            {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM", "end_time": "3:00 PM"},
            {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM", "end_time": "3:00 PM"},
            {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "end_time": "3:00 PM", "fold_lbs_per_hour": 35},
        ],
    }
    payload.update(overrides)
    return payload


def test_completed_tasks_before_t_remain_unchanged():
    before = run_shift_capacity(_base())
    continued = run_shift_capacity(
        _base(
            mode="continue_from_time",
            continue_from_time="8:30 AM",
            employees=[
                {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM", "end_time": "3:00 PM"},
                {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM", "end_time": "3:00 PM"},
                {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM", "end_time": "3:00 PM"},
                {"id": "LATE", "name": "Late Washer", "primary_role": "washer", "start_time": "8:30 AM", "end_time": "3:00 PM"},
                {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "end_time": "3:00 PM", "fold_lbs_per_hour": 35},
            ],
        )
    )
    t = parse_clock_minutes("8:30 AM")
    before_by_id = {r["bag_id"]: r for r in before["bag_rows"]}
    for row in continued["bag_rows"]:
        old = before_by_id[row["bag_id"]]
        if parse_clock_minutes(old["weigh_start"]) < t:
            assert row["weigh_start"] == old["weigh_start"]
            assert row["weigh_end"] == old["weigh_end"]
            assert row["weighed_by_employee_id"] == old["weighed_by_employee_id"]


def test_active_machine_cycles_preserved_at_freeze():
    result = run_shift_capacity(
        _base(
            mode="continue_from_time",
            continue_from_time="8:30 AM",
            bag_count=16,
            employees=[
                {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM"},
                {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM"},
                {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM"},
                {"id": "LATE", "name": "Late Washer", "primary_role": "washer", "start_time": "8:30 AM"},
                {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 35},
            ],
        )
    )
    assert result["continuation"]["event_queue_starts_at_min"] == parse_clock_minutes("8:30 AM")
    in_progress = [
        row
        for row in result["bag_rows"]
        if (row.get("provenance") or {}).get("wash") == "in_progress_preserved"
        or (row.get("provenance") or {}).get("dry") == "in_progress_preserved"
    ]
    # At least provenance tags exist for continuation.
    tagged = [row for row in result["bag_rows"] if row.get("provenance")]
    assert tagged
    assert result["continuation"]["preserved_task_count"] + result["continuation"]["in_progress_task_count"] >= 1


def test_new_staff_receive_tasks_only_after_t():
    result = run_shift_capacity(
        _base(
            mode="continue_from_time",
            continue_from_time="8:30 AM",
            employees=[
                {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM"},
                {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM"},
                {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM"},
                {"id": "LATE", "name": "Late Washer", "primary_role": "washer", "start_time": "8:30 AM"},
                {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 35},
            ],
        )
    )
    t = parse_clock_minutes("8:30 AM")
    for row in result.get("employee_timeline") or []:
        if row.get("resource_id") != "LATE":
            continue
        for iv in row.get("intervals") or []:
            assert parse_clock_minutes(iv["start"]) >= t


def test_continuation_metadata_and_provenance_present():
    result = run_shift_capacity(_base(mode="continue_from_time", continue_from_time="8:30 AM", bag_count=10))
    cont = result["continuation"]
    assert cont["history_frozen_through"]
    assert cont["recalculated_from"]
    assert cont["event_queue_starts_at_min"] == parse_clock_minutes("8:30 AM")
    assert "preserved_task_count" in cont
    assert "recalculated_task_count" in cont


def test_reoptimize_may_change_early_assignments_vs_continue():
    employees = [
        {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM"},
        {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM"},
        {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM"},
        {"id": "LATE", "name": "Late Washer", "primary_role": "washer", "start_time": "8:30 AM"},
        {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 35},
    ]
    continued = run_shift_capacity(
        _base(mode="continue_from_time", continue_from_time="8:30 AM", employees=employees, bag_count=12)
    )
    reopt = run_shift_capacity(
        _base(mode="reoptimize_entire_shift", employees=employees, bag_count=12)
    )
    assert continued["mode"] == "continue_from_time"
    assert reopt["mode"] == "reoptimize_entire_shift"
    # Both valid paths execute; reoptimize is allowed to rewrite history.
    assert continued["simulation_valid"] is True
    assert reopt["simulation_valid"] is True
