"""Timed staffing and role-switch tests for bag_des_v2."""

from backend.shift_capacity.service import run_shift_capacity
from backend.shift_capacity.validation import parse_clock_minutes


def _base(**overrides):
    payload = {
        "engine": "bag_des_v2",
        "mode": "full_run",
        "start_time": "7:00 AM",
        "target_time": "12:00 PM",
        "bag_count": 8,
        "avg_lbs_per_bag": 20,
        "batch_size": 4,
        "washer_count": 2,
        "dryer_count": 2,
        "washer_capacity_lb": 80,
        "dryer_capacity_lb": 80,
        "wash_cycle_min": 25,
        "dry_cycle_min": 30,
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
            {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "end_time": "3:00 PM", "fold_lbs_per_hour": 40},
        ],
    }
    payload.update(overrides)
    return payload


def _employee_task_starts(result, employee_id):
    starts = []
    for row in result.get("employee_timeline") or []:
        if row.get("resource_id") != employee_id:
            continue
        for iv in row.get("intervals") or []:
            starts.append(parse_clock_minutes(iv["start"]))
    return starts


def test_sorter_entering_at_830_receives_no_earlier_tasks():
    result = run_shift_capacity(
        _base(
            bag_count=40,
            sort_min_per_bag=5,
            employees=[
                {"id": "WEIGH1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM"},
                {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM"},
                {"id": "S2", "name": "Sorter 2", "primary_role": "sorter", "start_time": "8:30 AM"},
                {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM"},
                {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 40},
            ],
        )
    )
    assert result["simulation_valid"] is True
    assert result["overlap_errors"] == []
    starts = _employee_task_starts(result, "S2")
    if not starts:
        starts = [
            parse_clock_minutes(row["sort_start"])
            for row in result["bag_rows"]
            if row.get("sorted_by_employee_id") == "S2"
        ]
    assert starts
    assert min(starts) >= parse_clock_minutes("8:30 AM")


def test_washer_entering_at_915_receives_no_earlier_tasks():
    result = run_shift_capacity(
        _base(
            employees=[
                {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM"},
                {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM"},
                {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM"},
                {"id": "H2", "name": "Washer 2", "primary_role": "washer", "start_time": "9:15 AM"},
                {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 40},
            ]
        )
    )
    starts = _employee_task_starts(result, "H2")
    if starts:
        assert min(starts) >= parse_clock_minutes("9:15 AM")


def test_folder_entering_at_1000_receives_no_earlier_bags():
    result = run_shift_capacity(
        _base(
            bag_count=6,
            employees=[
                {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM"},
                {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM"},
                {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM"},
                {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 40},
                {"id": "F4", "name": "Folder 4", "primary_role": "folder", "start_time": "10:00 AM", "fold_lbs_per_hour": 40},
            ],
        )
    )
    for row in result["bag_rows"]:
        if row.get("folded_by_employee_id") == "F4" or row.get("folder_employee_id") == "F4":
            assert parse_clock_minutes(row["fold_start"]) >= parse_clock_minutes("10:00 AM")


def test_shared_weigher_washer_has_no_overlap():
    result = run_shift_capacity(
        _base(
            weigher_washer_same=True,
            bag_count=6,
            washer_count=1,
            dryer_count=1,
            employees=[
                {
                    "id": "E1",
                    "name": "Maria",
                    "primary_role": "weigher",
                    "secondary_roles": ["washer"],
                    "start_time": "7:00 AM",
                    "end_time": "3:00 PM",
                },
                {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM"},
                {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 40},
            ],
        )
    )
    assert result["simulation_valid"] is True
    assert result["overlap_errors"] == []


def test_shared_sorter_washer_has_no_overlap():
    result = run_shift_capacity(
        _base(
            sorter_washer_same=True,
            bag_count=6,
            employees=[
                {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM"},
                {
                    "id": "E1",
                    "name": "Alex",
                    "primary_role": "sorter",
                    "secondary_roles": ["washer"],
                    "start_time": "7:00 AM",
                },
                {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 40},
            ],
        )
    )
    assert result["simulation_valid"] is True
    assert result["overlap_errors"] == []


def test_two_employees_same_role_work_in_parallel():
    result = run_shift_capacity(
        _base(
            bag_count=8,
            sort_min_per_bag=5,
            employees=[
                {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM"},
                {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM"},
                {"id": "S2", "name": "Sorter 2", "primary_role": "sorter", "start_time": "7:00 AM"},
                {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM"},
                {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 40},
            ],
        )
    )
    assert {"S1", "S2"} <= {row["sorted_by_employee_id"] for row in result["bag_rows"]}


def test_different_employee_rates_affect_output():
    fast = run_shift_capacity(
        _base(
            bag_count=4,
            employees=[
                {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM"},
                {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM", "sort_min_per_bag": 2},
                {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM"},
                {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 40},
            ],
        )
    )
    slow = run_shift_capacity(
        _base(
            bag_count=4,
            employees=[
                {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM"},
                {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM", "sort_min_per_bag": 8},
                {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM"},
                {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 40},
            ],
        )
    )
    assert parse_clock_minutes(fast["summary"]["final_completion_time"]) < parse_clock_minutes(
        slow["summary"]["final_completion_time"]
    )


def test_scheduled_sorter_to_washer_switch():
    result = run_shift_capacity(
        _base(
            bag_count=8,
            employees=[
                {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM"},
                {
                    "id": "M1",
                    "name": "Maria",
                    "primary_role": "sorter",
                    "secondary_roles": ["washer"],
                    "start_time": "7:00 AM",
                    "end_time": "3:00 PM",
                    "role_schedule": [
                        {"role": "sorter", "from": "7:00 AM", "to": "8:30 AM"},
                        {"role": "washer", "from": "8:30 AM", "to": "10:30 AM"},
                        {"role": "sorter", "from": "10:30 AM", "to": "2:00 PM"},
                    ],
                },
                {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM"},
                {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 40},
            ],
        )
    )
    assert result["simulation_valid"] is True
    switches = []
    for row in result["staffing_chart"]:
        switches.extend(row.get("role_switches") or [])
    assert any("Maria" in s for s in switches)


def test_overlapping_role_windows_rejected():
    result = run_shift_capacity(
        _base(
            employees=[
                {
                    "id": "M1",
                    "name": "Maria",
                    "primary_role": "sorter",
                    "secondary_roles": ["washer"],
                    "start_time": "7:00 AM",
                    "role_schedule": [
                        {"role": "sorter", "from": "7:00 AM", "to": "9:00 AM"},
                        {"role": "washer", "from": "8:30 AM", "to": "11:00 AM"},
                    ],
                },
                {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM"},
                {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM"},
                {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 40},
            ]
        )
    )
    assert result["simulation_valid"] is False
    assert result["validation"]["accepted"] is False
    assert any(
        "overlap" in (e.get("message") or "").lower() or e.get("code") == "INVALID_REQUEST"
        for e in result["validation"]["errors"]
    )
