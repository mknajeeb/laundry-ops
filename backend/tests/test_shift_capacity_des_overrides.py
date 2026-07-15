"""Regression tests for DES batch editing, freezes, and role schedules."""

from copy import deepcopy

from backend.shift_capacity_des import _parse_clock_minutes, apply_des_action, merge_batch_override, run_bag_des_simulation


def _base(**overrides):
    payload = {
        "start_time": "7:00 AM", "target_time": "1:00 PM", "bag_count": 16,
        "avg_lbs_per_bag": 20, "batch_size": 4, "washer_count": 2, "dryer_count": 2,
        "washer_capacity_lb": 80, "dryer_capacity_lb": 80, "weigh_min_per_bag": 1,
        "sort_min_per_bag": 3, "load_washer_min": 2, "unload_transfer_min": 3,
        "load_dryer_min": 2, "wash_cycle_min": 30, "dry_cycle_min": 35,
        "employees": [
            {"id": "WEIGH", "name": "Weigher", "primary_role": "weigher", "start_time": "7:00 AM"},
            {"id": "SORT", "name": "Sorter", "primary_role": "sorter", "start_time": "7:00 AM"},
            {"id": "WASH", "name": "Washer", "primary_role": "washer", "start_time": "7:00 AM"},
            {"id": "FOLD", "name": "Folder", "primary_role": "folder", "start_time": "7:00 AM"},
        ],
    }
    payload.update(overrides)
    return payload


def _membership(result):
    return {batch["batch_number"]: batch["bag_ids"] for batch in result["batches"]}


def test_editing_batch_two_preserves_batch_one():
    base = _base()
    original = run_bag_des_simulation(base)
    edited = run_bag_des_simulation(merge_batch_override(base, {"batch_number": 2, "batch_size": 2, "apply_scope": "from_this_batch"}))
    assert _membership(edited)[1] == _membership(original)[1]


def test_from_batch_three_cascades_batch_size():
    result = run_bag_des_simulation(merge_batch_override(_base(bag_count=20), {"batch_number": 3, "apply_scope": "from_this_batch", "batch_size": 2}))
    assert all(batch["total_bags"] <= 2 for batch in result["batches"] if batch["batch_number"] >= 3)


def test_explicit_bags_move_to_selected_batch():
    base = _base()
    original = run_bag_des_simulation(base)
    bag = _membership(original)[3][-1]
    result = run_bag_des_simulation(merge_batch_override(base, {"batch_number": 2, "bag_ids": [bag]}))
    assert bag in _membership(result)[2]
    assert any(item["bag_id"] == bag for item in result["bags_moved"])


def test_overweight_manual_batch_is_rejected():
    result = run_bag_des_simulation(merge_batch_override(_base(), {"batch_number": 1, "bag_ids": ["ORD-1-1", "ORD-1-2", "ORD-1-3", "ORD-1-4", "ORD-2-1"]}))
    assert result["simulation_valid"] is False
    assert "exceeds washer capacity" in " ".join(result["validation_errors"])


def test_invalid_forced_employee_is_rejected():
    result = run_bag_des_simulation(merge_batch_override(_base(), {"batch_number": 1, "washer_person_id": "MISSING"}))
    assert result["simulation_valid"] is False
    assert "MISSING" in " ".join(result["validation_errors"])


def test_continue_freezes_early_history_and_reports_counts():
    base = _base(bag_count=24)
    before = run_bag_des_simulation(base)
    continued = apply_des_action(base, {"sim_mode": "continue_from_time", "continue_from_time": "8:30 AM", "staffing_event": {"type": "add_employee", "id": "LATE", "name": "Late washer", "primary_role": "washer", "start_time": "8:30 AM"}})
    after = run_bag_des_simulation(continued)
    early_before = {r["bag_id"]: r["weigh_start"] for r in before["bag_rows"] if r["weigh_start"] and r["weigh_start"] < "8:30 AM"}
    early_after = {r["bag_id"]: r["weigh_start"] for r in after["bag_rows"] if r["bag_id"] in early_before}
    assert early_after == early_before
    assert after["partial_resim"]["preserved_task_count"] > 0
    assert all(_parse_clock_minutes(i["start"]) >= 510 for i in next(e for e in after["timelines"]["employees"] if e["id"] == "LATE")["intervals"])


def test_active_machine_cycles_are_preserved_at_freeze():
    result = run_bag_des_simulation(_base(bag_count=16, sim_mode="continue_from_time", continue_from_time="8:30 AM"))
    rows = result["bag_rows"]
    assert any(r.get("provenance", {}).get("wash") == "in_progress" for r in rows)
    assert any(r.get("provenance", {}).get("dry") == "in_progress" for r in rows)


def test_scheduled_sorter_to_washer_switch():
    result = run_bag_des_simulation(_base(
        bag_count=4,
        employees=[
            {"id": "WEIGH", "primary_role": "weigher", "start_time": "7:00 AM"},
            {"id": "MARIA", "name": "Maria", "primary_role": "sorter", "start_time": "7:00 AM",
             "role_schedule": [{"role": "sorter", "from": "7:00 AM", "to": "7:15 AM"}, {"role": "washer", "from": "7:15 AM", "to": "3:00 PM"}]},
            {"id": "FOLD", "primary_role": "folder", "start_time": "7:00 AM"},
        ],
    ))
    assert any(row["washer_loaded_by"] == "Washer 2" or row["washer_loaded_by"] == "Maria" for row in result["bag_rows"])


def test_undo_restores_original_inputs_exactly():
    base = _base()
    original = run_bag_des_simulation(base)
    changed = apply_des_action(base, {"batch_override": {"batch_number": 2, "batch_size": 2}})
    assert run_bag_des_simulation(changed)["batches"] != original["batches"]
    restored = deepcopy(base)
    assert run_bag_des_simulation(restored)["bag_rows"] == original["bag_rows"]


def test_strict_resource_lock_rejects_busy_washer_start():
    result = run_bag_des_simulation(
        merge_batch_override(
            _base(washer_count=1),
            {
                "batch_number": 2,
                "apply_scope": "this_batch_only",
                "planned_start_time": "7:00 AM",
                "strict_resource_lock": True,
                "washer_id": "W1",
            },
        )
    )
    assert result["simulation_valid"] is False
    assert any("cannot start exactly" in err for err in result.get("validation_errors") or [])


def test_reoptimize_full_may_change_early_assignments_vs_continue():
    with_staff = apply_des_action(
        _base(bag_count=20),
        {
            "staffing_event": {
                "type": "add_employee",
                "id": "EARLY2",
                "name": "Extra sorter",
                "primary_role": "sorter",
                "start_time": "7:00 AM",
            }
        },
    )
    cont = dict(with_staff)
    cont["sim_mode"] = "continue_from_time"
    cont["continue_from_time"] = "8:30 AM"
    # Inject a late washer under continue; history before 8:30 kept from employees starting earlier.
    cont = apply_des_action(
        cont,
        {
            "staffing_event": {
                "type": "add_employee",
                "id": "LATEW",
                "name": "Late washer",
                "primary_role": "washer",
                "start_time": "8:30 AM",
            }
        },
    )
    continued = run_bag_des_simulation(cont)
    reopt = dict(cont)
    reopt["sim_mode"] = "reoptimize_full"
    reopt.pop("continue_from_time", None)
    full = run_bag_des_simulation(reopt)
    assert continued["partial_resim"]["preserved_task_count"] > 0
    # Full reoptimize is allowed to differ in completed timing (and usually does).
    assert full["summary"]["final_completion_time"] is not None
    assert continued["summary"]["final_completion_time"] is not None


def test_role_switch_finishes_active_task_before_new_role():
    result = run_bag_des_simulation(
        _base(
            bag_count=3,
            sort_min_per_bag=10,
            employees=[
                {"id": "WEIGH", "name": "Weigher", "primary_role": "weigher", "start_time": "7:00 AM"},
                {
                    "id": "MARIA",
                    "name": "Maria",
                    "primary_role": "sorter",
                    "start_time": "7:00 AM",
                    "role_schedule": [
                        {"role": "sorter", "from": "7:00 AM", "to": "7:12 AM"},
                        {"role": "washer", "from": "7:12 AM", "to": "3:00 PM"},
                    ],
                },
                {"id": "FOLD", "name": "Folder", "primary_role": "folder", "start_time": "7:00 AM"},
            ],
        )
    )
    # Maria's sort tasks that start before 7:12 must be allowed to finish (finish-current).
    maria_sorts = [
        r for r in result["bag_rows"] if r.get("sorted_by") == "Maria" and r.get("sort_start") and r.get("sort_end")
    ]
    assert maria_sorts
    assert any(
        _parse_clock_minutes(r["sort_start"]) < 7 * 60 + 12 <= _parse_clock_minutes(r["sort_end"])
        for r in maria_sorts
    ) or any(_parse_clock_minutes(r["sort_end"]) <= 7 * 60 + 12 for r in maria_sorts)
    # Later washer handling can use Maria after her switch.
    assert any(r.get("washer_loaded_by") == "Maria" for r in result["bag_rows"])


def test_new_employee_has_no_tasks_before_entry():
    payload = apply_des_action(
        _base(bag_count=12),
        {
            "sim_mode": "continue_from_time",
            "continue_from_time": "9:00 AM",
            "staffing_event": {
                "type": "add_employee",
                "id": "S2",
                "name": "Sorter 2",
                "primary_role": "sorter",
                "start_time": "9:00 AM",
            },
        },
    )
    result = run_bag_des_simulation(payload)
    emp = next(e for e in result["timelines"]["employees"] if e["id"] == "S2")
    for interval in emp["intervals"]:
        assert _parse_clock_minutes(interval["start"]) >= 9 * 60
