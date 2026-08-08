"""Bag scheduling tests for bag_des_v2."""

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
        "batch_limit_mode": "whichever_first",
        "washer_count": 2,
        "dryer_count": 2,
        "washer_capacity_lb": 80,
        "dryer_capacity_lb": 80,
        "wash_cycle_min": 30,
        "dry_cycle_min": 40,
        "weigh_min_per_bag": 1,
        "sort_min_per_bag": 4,
        "load_washer_min": 2,
        "unload_transfer_min": 3,
        "load_dryer_min": 2,
        "unload_dryer_min": 0,
        "fold_rate_mode": "lbs_per_hour",
        "fold_lbs_per_hour": 40,
        "employees": [
            {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM", "end_time": "3:00 PM"},
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
        "_skip_recommendations": True,
    }
    payload.update(overrides)
    return payload


REQUIRED_STAGES = [
    "weigh_start",
    "weigh_end",
    "sort_start",
    "sort_end",
    "washer_load_start",
    "washer_load_end",
    "wash_start",
    "wash_end",
    "transfer_start",
    "transfer_end",
    "dryer_load_start",
    "dryer_load_end",
    "dry_start",
    "dry_end",
    "ready_to_fold",
    "fold_start",
    "fold_end",
    "completed",
]


def test_every_bag_receives_required_stage_timestamps():
    result = run_shift_capacity(_base())
    assert result["simulation_valid"] is True
    assert result["overlap_errors"] == []
    assert len(result["bag_rows"]) == 8
    for row in result["bag_rows"]:
        for key in REQUIRED_STAGES:
            assert row.get(key), f"{row['bag_id']} missing {key}"


def test_bag_stages_are_chronological():
    result = run_shift_capacity(_base())
    sequence = [
        "weigh_start",
        "weigh_end",
        "sort_start",
        "sort_end",
        "washer_load_start",
        "washer_load_end",
        "wash_start",
        "wash_end",
        "transfer_start",
        "transfer_end",
        "dryer_load_start",
        "dryer_load_end",
        "dry_start",
        "dry_end",
        "ready_to_fold",
        "fold_start",
        "fold_end",
        "completed",
    ]
    for row in result["bag_rows"]:
        mins = [parse_clock_minutes(row[k]) for k in sequence]
        assert mins == sorted(mins), row["bag_id"]


def test_handling_and_machine_times_remain_separate():
    result = run_shift_capacity(_base(bag_count=1, batch_size=1))
    row = result["bag_rows"][0]
    # Handling ends when the machine cycle begins; they are distinct resources.
    assert parse_clock_minutes(row["washer_load_end"]) == parse_clock_minutes(row["wash_start"])
    assert parse_clock_minutes(row["wash_end"]) == parse_clock_minutes(row["transfer_start"])
    assert parse_clock_minutes(row["dryer_load_end"]) == parse_clock_minutes(row["dry_start"])
    assert parse_clock_minutes(row["washer_load_start"]) <= parse_clock_minutes(row["wash_start"])


def test_bags_sharing_batch_retain_separate_records():
    result = run_shift_capacity(_base(bag_count=4, batch_size=4))
    batches = {row["batch"] for row in result["bag_rows"]}
    assert len(batches) == 1
    assert len(result["bag_rows"]) == 4
    assert len({row["bag_id"] for row in result["bag_rows"]}) == 4


def test_weight_based_folding_duration_is_correct():
    result = run_shift_capacity(
        _base(
            bag_count=1,
            batch_size=1,
            avg_lbs_per_bag=40,
            fold_rate_mode="lbs_per_hour",
            fold_lbs_per_hour=40,
            employees=[
                {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM"},
                {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM"},
                {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM"},
                {
                    "id": "F1",
                    "name": "Folder 1",
                    "primary_role": "folder",
                    "start_time": "7:00 AM",
                    "fold_lbs_per_hour": 40,
                },
            ],
        )
    )
    row = result["bag_rows"][0]
    fold_sec = parse_clock_minutes(row["fold_end"]) - parse_clock_minutes(row["fold_start"])
    assert fold_sec == 3600  # 40 lb / 40 lb/hr = 60 min = 3600 sec (seconds timebase)
