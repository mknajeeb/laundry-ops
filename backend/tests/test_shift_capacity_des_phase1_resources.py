"""Phase 1: resource typing, atomic machine occupancy, no-overlap stress tests."""

from backend.shift_capacity.resources import ResourceCalendar, intervals_overlap
from backend.shift_capacity.service import merge_batch_override, run_shift_capacity
from backend.shift_capacity.validation import parse_clock_minutes


def _base(**overrides):
    payload = {
        "engine": "bag_des_v2",
        "mode": "full_run",
        "start_time": "7:00 AM",
        "target_time": "12:00 PM",
        "bag_count": 16,
        "avg_lbs_per_bag": 20,
        "batch_size": 4,
        "washer_count": 2,
        "dryer_count": 2,
        "washer_capacity_lb": 80,
        "dryer_capacity_lb": 80,
        "wash_cycle_min": 30,
        "dry_cycle_min": 40,
        "weigh_min_per_bag": 1,
        "sort_min_per_bag": 5,
        "load_washer_min": 2,
        "unload_transfer_min": 2,
        "load_dryer_min": 2,
        "fold_rate_mode": "lbs_per_hour",
        "fold_lbs_per_hour": 40,
        "_skip_recommendations": True,
        "employees": [
            {"id": "WEIGH1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM", "end_time": "3:00 PM"},
            {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM", "end_time": "3:00 PM"},
            {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM", "end_time": "3:00 PM"},
            {
                "id": "F1",
                "name": "Folder 1",
                "primary_role": "folder",
                "start_time": "7:00 AM",
                "end_time": "3:00 PM",
                "fold_lbs_per_hour": 40,
            },
        ],
    }
    payload.update(overrides)
    return payload


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
    starts = [
        parse_clock_minutes(row["sort_start"])
        for row in result["bag_rows"]
        if row.get("sorted_by_employee_id") == "S2"
    ]
    assert starts
    assert min(starts) >= parse_clock_minutes("8:30 AM")


def test_40_bag_run_has_no_machine_overlap():
    result = run_shift_capacity(_base(bag_count=40))
    assert result["simulation_valid"] is True
    assert result["overlap_errors"] == []


def test_80_bag_run_has_no_machine_overlap():
    result = run_shift_capacity(
        _base(
            bag_count=80,
            washer_count=3,
            dryer_count=3,
            employees=[
                {"id": "WEIGH1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM"},
                {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM"},
                {"id": "S2", "name": "Sorter 2", "primary_role": "sorter", "start_time": "8:00 AM"},
                {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM"},
                {"id": "H2", "name": "Washer 2", "primary_role": "washer", "start_time": "8:30 AM"},
                {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 40},
                {"id": "F2", "name": "Folder 2", "primary_role": "folder", "start_time": "8:00 AM", "fold_lbs_per_hour": 40},
            ],
        )
    )
    assert result["simulation_valid"] is True
    assert result["overlap_errors"] == []


def test_employee_named_w1_is_not_classified_as_machine():
    result = run_shift_capacity(
        _base(
            bag_count=8,
            employees=[
                {"id": "W1", "name": "Person W1", "primary_role": "weigher", "start_time": "7:00 AM"},
                {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM"},
                {"id": "H1", "name": "Washer Person", "primary_role": "washer", "start_time": "7:00 AM"},
                {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 40},
            ],
        )
    )
    assert result["simulation_valid"] is True
    assert result["overlap_errors"] == []
    # Employee W1 should appear on employee timeline, not machine occupancy errors as machine W1 confusion
    emp_ids = {row["resource_id"] for row in result.get("employee_timeline") or []}
    assert "W1" in emp_ids


def test_back_to_back_machine_reservations_are_allowed():
    cal = ResourceCalendar()
    cal.reserve_exact("W1", 100, 120, resource_type="washer_machine", task_type="wash", bag_ids=["a"])
    cal.reserve_exact("W1", 120, 140, resource_type="washer_machine", task_type="wash", bag_ids=["b"])
    assert cal.overlap_errors() == []


def test_overlapping_machine_reservations_are_rejected():
    cal = ResourceCalendar()
    cal.reserve_exact("W1", 100, 130, resource_type="washer_machine", task_type="wash", bag_ids=["a"])
    try:
        cal.reserve_exact("W1", 120, 140, resource_type="washer_machine", task_type="wash", bag_ids=["b"])
        assert False, "expected overlap"
    except Exception as exc:
        assert "RESOURCE_OVERLAP" in str(exc) or getattr(exc, "error", None)


def test_intervals_half_open():
    assert intervals_overlap(100, 105, 105, 110) is False
    assert intervals_overlap(100, 106, 105, 110) is True


def test_earliest_available_skips_short_gaps():
    cal = ResourceCalendar()
    # Busy [499, 501); a 1-minute hole at 498 must not accept a 2-minute task.
    cal.reserve_exact("E1", 499, 501, resource_type="employee", task_type="transfer", bag_ids=["x"])
    start, end = cal.find_earliest_available("E1", 498, 2, resource_type="employee")
    assert start == 501
    assert end == 503
    result = cal.reserve_at_earliest_available(
        "E1", 498, 2, resource_type="employee", task_type="dryer_load", bag_ids=["y"]
    )
    assert result.start == 501
    assert result.end == 503
    assert cal.overlap_errors() == []


def test_hard_employee_assignment_does_not_silently_wait():
    # Force same washer person onto two overlapping locked starts → reject
    base = _base(bag_count=8, batch_size=4, washer_count=1)
    first = run_shift_capacity(base)
    assert first["simulation_valid"] is True
    # Lock batch 2 to start exactly when batch 1 wash occupies the only washer person hard.
    result = run_shift_capacity(
        merge_batch_override(
            base,
            {
                "batch_number": 2,
                "washer_person_id": "H1",
                "planned_start_time": "7:00 AM",
                "strict_resource_lock": True,
                "apply_scope": "this_batch_only",
            },
        )
    )
    assert result["simulation_valid"] is False
    codes = {e.get("code") for e in (result.get("validation") or {}).get("errors") or []}
    assert "RESOURCE_OVERLAP" in codes or "MACHINE_OVERLAP" in codes or result["validation"]["accepted"] is False


def test_hard_machine_assignment_does_not_silently_wait():
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
    assert result["simulation_valid"] is False


def test_atomic_booking_rolls_back_on_failure():
    cal = ResourceCalendar()
    snap = cal.checkpoint()
    cal.reserve_exact("W1", 0, 10, resource_type="washer_machine", task_type="wash")
    try:
        cal.reserve_exact("W1", 5, 15, resource_type="washer_machine", task_type="wash")
    except Exception:
        cal.restore(snap)
    assert cal.reservations("W1", resource_type="washer_machine") == []


def test_washer_machine_reserved_from_load_start_through_wash_end():
    result = run_shift_capacity(_base(bag_count=4, batch_size=4, washer_count=1))
    assert result["simulation_valid"] is True
    row = result["bag_rows"][0]
    load_start = parse_clock_minutes(row["washer_load_start"])
    wash_end = parse_clock_minutes(row["wash_end"])
    machine_ivs = []
    for m in result.get("machine_timeline") or []:
        if m.get("resource_id") == row["washer"]:
            machine_ivs.extend(m.get("intervals") or [])
    assert machine_ivs
    cover = [
        iv
        for iv in machine_ivs
        if parse_clock_minutes(iv["start"]) <= load_start and parse_clock_minutes(iv["end"]) >= wash_end
    ]
    assert cover, "machine occupancy must span load_start through wash_end"


def test_dryer_machine_reserved_from_load_start_through_dry_end():
    result = run_shift_capacity(_base(bag_count=4, batch_size=4, dryer_count=1))
    assert result["simulation_valid"] is True
    row = result["bag_rows"][0]
    load_start = parse_clock_minutes(row["dryer_load_start"])
    dry_end = parse_clock_minutes(row["dry_end"])
    machine_ivs = []
    for m in result.get("machine_timeline") or []:
        if m.get("resource_id") == row["dryer"]:
            machine_ivs.extend(m.get("intervals") or [])
    assert machine_ivs
    cover = [
        iv
        for iv in machine_ivs
        if parse_clock_minutes(iv["start"]) <= load_start and parse_clock_minutes(iv["end"]) >= dry_end
    ]
    assert cover


def test_shared_role_employee_no_overlap_under_load():
    result = run_shift_capacity(
        _base(
            bag_count=24,
            weigher_washer_same=True,
            washer_count=2,
            dryer_count=2,
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
