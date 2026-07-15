"""Batch construction and override rejection tests for bag_des_v2."""

from backend.shift_capacity.service import merge_batch_override, run_shift_capacity


def _base(**overrides):
    payload = {
        "engine": "bag_des_v2",
        "mode": "full_run",
        "start_time": "7:00 AM",
        "target_time": "12:00 PM",
        "bag_count": 12,
        "avg_lbs_per_bag": 20,
        "batch_size": 8,
        "batch_limit_mode": "whichever_first",
        "washer_count": 2,
        "dryer_count": 2,
        "washer_capacity_lb": 80,
        "dryer_capacity_lb": 80,
        "wash_cycle_min": 30,
        "dry_cycle_min": 40,
        "weigh_min_per_bag": 1,
        "sort_min_per_bag": 3,
        "load_washer_min": 2,
        "unload_transfer_min": 2,
        "load_dryer_min": 2,
        "fold_rate_mode": "lbs_per_hour",
        "fold_lbs_per_hour": 40,
        "_skip_recommendations": True,
        "employees": [
            {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM"},
            {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM"},
            {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM"},
            {"id": "H2", "name": "Washer 2", "primary_role": "washer", "start_time": "7:00 AM"},
            {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 40},
        ],
    }
    payload.update(overrides)
    return payload


def test_bag_count_limit_reached_first():
    result = run_shift_capacity(_base(batch_size=3, washer_capacity_lb=500, avg_lbs_per_bag=10, bag_count=9))
    assert result["ready_to_fold_by_batch"][0]["bags"] == 3


def test_weight_capacity_reached_first():
    result = run_shift_capacity(_base(batch_size=8, washer_capacity_lb=80, avg_lbs_per_bag=20, bag_count=12))
    assert result["ready_to_fold_by_batch"][0]["bags"] == 4
    assert result["ready_to_fold_by_batch"][0]["pounds"] <= 80 + 1e-6


def test_overweight_manual_batch_is_rejected():
    result = run_shift_capacity(
        merge_batch_override(
            _base(bag_count=8, batch_size=4),
            {
                "batch_number": 1,
                "bag_ids": ["ORD-1-1", "ORD-1-2", "ORD-1-3", "ORD-1-4", "ORD-2-1"],
                "apply_scope": "this_batch_only",
            },
        )
    )
    assert result["simulation_valid"] is False
    assert result["validation"]["accepted"] is False
    codes = {e["code"] for e in result["validation"]["errors"]}
    assert "OVERWEIGHT_BATCH" in codes


def test_apply_from_batch_three_preserves_batches_one_and_two():
    base = _base(bag_count=20, batch_size=4)
    original = run_shift_capacity(base)
    edited = run_shift_capacity(
        merge_batch_override(base, {"batch_number": 3, "batch_size": 2, "apply_scope": "from_this_batch"})
    )
    assert original["ready_to_fold_by_batch"][0]["bag_ids"] == edited["ready_to_fold_by_batch"][0]["bag_ids"]
    assert original["ready_to_fold_by_batch"][1]["bag_ids"] == edited["ready_to_fold_by_batch"][1]["bag_ids"]


def test_manual_bag_move_changes_only_affected_future_batches():
    base = _base(bag_count=12, batch_size=4)
    original = run_shift_capacity(base)
    b2 = original["ready_to_fold_by_batch"][1]["bag_ids"][0]
    result = run_shift_capacity(
        merge_batch_override(base, {"batch_number": 2, "bag_ids": [b2], "apply_scope": "this_batch_only"})
    )
    assert original["ready_to_fold_by_batch"][0]["bag_ids"] == result["ready_to_fold_by_batch"][0]["bag_ids"]
    assert b2 in result["ready_to_fold_by_batch"][1]["bag_ids"]
    moved = {m["bag_id"] for m in result.get("bags_moved") or []}
    assert b2 in moved or result["ready_to_fold_by_batch"][1]["bags"] == 1


def test_employee_not_found_override_rejected():
    result = run_shift_capacity(
        merge_batch_override(_base(bag_count=4), {"batch_number": 1, "washer_person_id": "MISSING"})
    )
    assert result["simulation_valid"] is False
    codes = {e["code"] for e in result["validation"]["errors"]}
    assert "EMPLOYEE_NOT_FOUND" in codes


def test_locked_start_machine_busy_rejected():
    result = run_shift_capacity(
        merge_batch_override(
            _base(bag_count=8, batch_size=4, washer_count=1),
            {
                "batch_number": 2,
                "washer_id": "W1",
                "planned_start_time": "7:00 AM",
                "strict_resource_lock": True,
                "apply_scope": "this_batch_only",
            },
        )
    )
    # Batch 2 cannot hard-lock W1 at shift start while batch 1 still needs it.
    assert result["simulation_valid"] is False or result["validation"]["accepted"] is False
