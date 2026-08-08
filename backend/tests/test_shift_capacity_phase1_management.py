"""Phase 1 engine foundations for management-mode Shift Capacity Planner."""

from backend.shift_capacity.block_positions import bag_state_at, position_at
from backend.shift_capacity.service import run_shift_capacity
from backend.shift_capacity.timebase import (
    label_seconds,
    parse_clock_seconds,
    planning_block_boundaries,
)
from backend.shift_capacity.validation import parse_inputs


def _full_day_staffing(start="8:00 AM", end="3:00 PM", **role_people):
    defaults = {"weigher": 1, "sorter": 1, "washer": 1, "dryer": 1, "folder": 1}
    defaults.update(role_people)
    return {
        "intervals": [
            {"role": role, "people": people, "start": start, "end": end, "mode": "base"}
            for role, people in defaults.items()
            if people > 0
        ]
    }


def _mgmt(**overrides):
    payload = {
        "engine": "bag_des_v2",
        "management_mode": True,
        "mode": "full_run",
        "start_time": "8:00 AM",
        "target_time": "12:00 PM",
        "planning_block_size_min": 60,
        "bag_count": 4,
        "avg_lbs_per_bag": 20,
        "batch_size": 2,
        "washer_count": 2,
        "dryer_count": 2,
        "wash_cycle_min": 30,
        "dry_cycle_min": 40,
        "sort_min_per_bag": 5,
        "load_washer_min": 3,
        "load_dryer_min": 4,
        "fold_rate_mode": "minutes_per_bag",
        "fold_min_per_bag": 6,
        "_skip_recommendations": True,
        "staffing_plan": _full_day_staffing(),
    }
    payload.update(overrides)
    return payload


def test_weigh_default_is_exactly_45_seconds():
    inp = parse_inputs(_mgmt())
    assert inp.processing_times.weigh_sec_per_bag == 45.0
    result = run_shift_capacity(_mgmt(bag_count=1, batch_size=1))
    row = result["bag_rows"][0]
    assert row["weigh_start"] == "8:00 AM"
    assert row["weigh_end"] == "8:00:45 AM"
    assert parse_clock_seconds(row["weigh_end"]) - parse_clock_seconds(row["weigh_start"]) == 45


def test_consecutive_weigh_operations_use_second_boundaries():
    result = run_shift_capacity(_mgmt(bag_count=3, batch_size=3, sort_min_per_bag=10))
    rows = sorted(result["bag_rows"], key=lambda r: parse_clock_seconds(r["weigh_start"]))
    assert rows[0]["weigh_start"] == "8:00 AM"
    assert rows[0]["weigh_end"] == "8:00:45 AM"
    assert rows[1]["weigh_start"] == "8:00:45 AM"
    assert rows[1]["weigh_end"] == "8:01:30 AM"
    assert rows[2]["weigh_start"] == "8:01:30 AM"


def test_whole_minute_durations_preserve_meaning():
    result = run_shift_capacity(
        _mgmt(
            bag_count=1,
            batch_size=1,
            weigh_sec_per_bag=60,
            load_washer_min=3,
            wash_cycle_min=30,
        )
    )
    row = result["bag_rows"][0]
    load_start = parse_clock_seconds(row["washer_load_start"])
    wash_end = parse_clock_seconds(row["wash_end"])
    assert parse_clock_seconds(row["washer_load_end"]) == parse_clock_seconds(row["wash_start"])
    assert wash_end - parse_clock_seconds(row["wash_start"]) == 30 * 60
    assert label_seconds(load_start + 3 * 60) == row["washer_load_end"]


def test_washer_availability_continuous_and_exact():
    result = run_shift_capacity(_mgmt(bag_count=2, batch_size=1, washer_count=1, weigh_sec_per_bag=60))
    rows = sorted(result["bag_rows"], key=lambda r: parse_clock_seconds(r["wash_start"]))
    assert parse_clock_seconds(rows[1]["washer_load_start"]) >= parse_clock_seconds(rows[0]["wash_end"])
    wid = rows[0]["washer"]
    ivs = next(m["intervals"] for m in result["machine_timeline"] if m["resource_id"] == wid)
    assert any(iv["end"] == rows[0]["wash_end"] for iv in ivs)


def test_dryer_availability_continuous_and_exact():
    result = run_shift_capacity(_mgmt(bag_count=2, batch_size=1, dryer_count=1, weigh_sec_per_bag=60))
    rows = sorted(result["bag_rows"], key=lambda r: parse_clock_seconds(r["dry_start"]))
    assert parse_clock_seconds(rows[1]["dryer_load_start"]) >= parse_clock_seconds(rows[0]["dry_end"])


def test_dry_uses_dryer_labor_not_washer():
    result = run_shift_capacity(_mgmt(bag_count=2, batch_size=2))
    for row in result["bag_rows"]:
        assert str(row["dryer_loaded_by_employee_id"]).startswith("MGMT_DRY_")
        assert str(row["washer_loaded_by_employee_id"]).startswith("MGMT_WASH_")
        assert row["dryer_loaded_by_employee_id"] != row["washer_loaded_by_employee_id"]


def test_no_implicit_cross_role_in_management_mode():
    result = run_shift_capacity(
        _mgmt(
            weigher_washer_same=True,
            sorter_washer_same=True,
            washer_folder_same=True,
            # Legacy employees must be ignored when staffing_plan is present.
            employees=[
                {
                    "id": "MULTI",
                    "name": "Multi",
                    "primary_role": "sorter",
                    "secondary_roles": ["washer", "folder", "dryer"],
                    "start_time": "8:00 AM",
                }
            ],
        )
    )
    assert result["inputs"]["management_mode"] is True
    assert result["inputs"]["transfer_min"] == 0
    assert "MULTI" not in {r["washer_loaded_by_employee_id"] for r in result["bag_rows"]}
    assert "MULTI" not in {r["dryer_loaded_by_employee_id"] for r in result["bag_rows"]}
    assert "MULTI" not in {r["folded_by_employee_id"] for r in result["bag_rows"]}
    assert all(str(r["sorted_by_employee_id"]).startswith("MGMT_SORT_") for r in result["bag_rows"])


def test_planning_blocks_30_45_60_and_short_final():
    for size in (30, 45, 60):
        result = run_shift_capacity(
            _mgmt(
                planning_block_size_min=size,
                summary_interval_min=size,
                start_time="8:00 AM",
                target_time="10:00 AM",
            )
        )
        positions = result["block_positions"]
        assert positions
        assert positions[0]["block_start"] == "8:00 AM"
        assert positions[-1]["block_end"] == "10:00 AM"
        for row in positions:
            assert row["reconciliation"]["ok"] is True

    bounds = planning_block_boundaries(
        parse_clock_seconds("8:00 AM"),
        parse_clock_seconds("9:40 AM"),
        45,
    )
    assert bounds == [
        parse_clock_seconds("8:00 AM"),
        parse_clock_seconds("8:45 AM"),
        parse_clock_seconds("9:30 AM"),
        parse_clock_seconds("9:40 AM"),
    ]
    result = run_shift_capacity(
        _mgmt(
            planning_block_size_min=45,
            start_time="8:00 AM",
            target_time="9:40 AM",
            bag_count=2,
        )
    )
    assert result["block_positions"][-1]["is_short_final_block"] is True
    assert result["block_positions"][-1]["block_duration_min"] == 10


def test_exact_time_role_windows_are_honored():
    # Sorter available 8:00–8:15 and 8:30–10:00 via staffing intervals (gap 8:15–8:30).
    result = run_shift_capacity(
        _mgmt(
            bag_count=2,
            staffing_plan={
                "intervals": [
                    {"role": "weigher", "people": 1, "start": "8:00 AM", "end": "3:00 PM"},
                    {"role": "sorter", "people": 1, "start": "8:00 AM", "end": "8:15 AM"},
                    {"role": "sorter", "people": 1, "start": "8:30 AM", "end": "10:00 AM"},
                    {"role": "washer", "people": 1, "start": "8:00 AM", "end": "3:00 PM"},
                    {"role": "dryer", "people": 1, "start": "8:00 AM", "end": "3:00 PM"},
                    {"role": "folder", "people": 1, "start": "8:00 AM", "end": "3:00 PM"},
                ]
            },
        )
    )
    for row in result["bag_rows"]:
        start = parse_clock_seconds(row["sort_start"])
        assert not (parse_clock_seconds("8:15 AM") <= start < parse_clock_seconds("8:30 AM"))


def test_queue_and_throughput_semantics():
    result = run_shift_capacity(_mgmt(bag_count=6, batch_size=2, planning_block_size_min=60))
    assert result["simulation_valid"] is True
    from backend.shift_capacity.scheduler import run_scheduler
    from backend.shift_capacity.validation import parse_inputs as _pi

    state = run_scheduler(_pi(_mgmt(bag_count=6, batch_size=2)))
    t = state.inputs.shift.start_min + 30 * 60
    pos = position_at(state.bags, t, prev_t=state.inputs.shift.start_min, target_bags=6)
    assert pos["waiting_to_wash"] == sum(1 for b in state.bags if bag_state_at(b, t) == "waiting_to_wash")
    assert pos["waiting_to_sort"] == sum(1 for b in state.bags if bag_state_at(b, t) == "waiting_to_sort")
    assert pos["waiting_to_dry"] == sum(1 for b in state.bags if bag_state_at(b, t) == "waiting_to_dry")
    assert pos["waiting_to_fold"] == sum(1 for b in state.bags if bag_state_at(b, t) == "waiting_to_fold")
    for b in state.bags:
        st = bag_state_at(b, t)
        if st in ("in_wash_labor", "in_wash_cycle"):
            assert st != "waiting_to_wash"
        if st in ("in_dry_labor", "in_dry_cycle"):
            assert st != "waiting_to_dry"
    assert pos["weighed_total"] == sum(1 for b in state.bags if b.weigh_end is not None and b.weigh_end <= t)
    assert pos["washed_total"] == sum(1 for b in state.bags if b.wash_end is not None and b.wash_end <= t)
    assert pos["dried_total"] == sum(1 for b in state.bags if b.ready_to_fold is not None and b.ready_to_fold <= t)


def test_reconciliation_equals_target_at_every_checkpoint():
    result = run_shift_capacity(
        _mgmt(
            bag_count=8,
            batch_size=2,
            planning_block_size_min=45,
            start_time="8:00 AM",
            target_time="11:00 AM",
        )
    )
    assert result["block_positions"]
    for row in result["block_positions"]:
        assert row["reconciliation"]["ok"] is True
        assert row["reconciliation"]["exclusive_state_sum"] == 8
        assert row["reconciliation"]["target_bags"] == 8


def test_final_completion_from_des_not_block_math():
    result = run_shift_capacity(_mgmt(bag_count=4, batch_size=2))
    final = result["summary"]["final_completion_time"]
    bag_final = max(parse_clock_seconds(r["completed"]) for r in result["bag_rows"])
    assert parse_clock_seconds(final) == bag_final
    last_folded = result["block_positions"][-1]["folded_total"]
    assert last_folded <= 4


def test_no_standalone_transfer_double_count_in_management_mode():
    result = run_shift_capacity(_mgmt(bag_count=1, batch_size=1))
    row = result["bag_rows"][0]
    assert result["inputs"]["transfer_min"] == 0
    assert row["transfer_start"] == row["transfer_end"]
    assert row["transfer_start"] == row["wash_end"]
    assert parse_clock_seconds(row["dryer_load_start"]) >= parse_clock_seconds(row["wash_end"])
    assert parse_clock_seconds(row["dryer_load_start"]) - parse_clock_seconds(row["wash_end"]) < 5 * 60


def test_compat_path_still_allows_transfer_and_washer_as_dry():
    result = run_shift_capacity(
        {
            "engine": "bag_des_v2",
            "management_mode": False,
            "start_time": "8:00 AM",
            "target_time": "12:00 PM",
            "bag_count": 1,
            "batch_size": 1,
            "weigh_min_per_bag": 1,
            "unload_transfer_min": 5,
            "load_dryer_min": 3,
            "wash_cycle_min": 30,
            "dry_cycle_min": 40,
            "_skip_recommendations": True,
            "employees": [
                {"id": "WEIGH1", "name": "Weigh 1", "primary_role": "weigher", "start_time": "8:00 AM"},
                {"id": "SORT1", "name": "Sort 1", "primary_role": "sorter", "start_time": "8:00 AM"},
                {"id": "WASH1", "name": "Wash 1", "primary_role": "washer", "start_time": "8:00 AM"},
                {"id": "FOLD1", "name": "Fold 1", "primary_role": "folder", "start_time": "8:00 AM", "fold_lbs_per_hour": 40},
            ],
        }
    )
    row = result["bag_rows"][0]
    assert parse_clock_seconds(row["transfer_end"]) - parse_clock_seconds(row["transfer_start"]) == 5 * 60
    assert row["dryer_loaded_by_employee_id"] == "WASH1"
