"""Summary reconciliation tests for bag_des_v2."""

from backend.shift_capacity.service import run_shift_capacity
from backend.shift_capacity.validation import parse_clock_minutes


def _base(**overrides):
    payload = {
        "engine": "bag_des_v2",
        "mode": "full_run",
        "start_time": "7:00 AM",
        "target_time": "12:00 PM",
        "summary_interval_min": 30,
        "bag_count": 10,
        "avg_lbs_per_bag": 20,
        "batch_size": 5,
        "washer_count": 2,
        "dryer_count": 2,
        "washer_capacity_lb": 100,
        "dryer_capacity_lb": 100,
        "wash_cycle_min": 30,
        "dry_cycle_min": 35,
        "fold_rate_mode": "lbs_per_hour",
        "fold_lbs_per_hour": 40,
        "_skip_recommendations": True,
        "employees": [
            {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM"},
            {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM"},
            {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM"},
            {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 40},
            {"id": "F2", "name": "Folder 2", "primary_role": "folder", "start_time": "8:00 AM", "fold_lbs_per_hour": 40},
        ],
    }
    payload.update(overrides)
    return payload


def test_thirty_minute_summary_matches_bag_timestamps():
    result = run_shift_capacity(_base(summary_interval_min=30))
    assert result["time_summary"]
    for row in result["time_summary"]:
        t = row["time_min"]
        bags = result["bag_rows"]
        ready = sum(1 for b in bags if parse_clock_minutes(b["ready_to_fold"]) <= t)
        folded = sum(1 for b in bags if parse_clock_minutes(b["completed"]) <= t)
        assert row["ready_to_fold"] == ready
        assert row["folded"] == folded
        backlog = sum(
            1
            for b in bags
            if parse_clock_minutes(b["ready_to_fold"]) <= t and parse_clock_minutes(b["fold_start"]) > t
        )
        assert row["fold_backlog"] == backlog


def test_one_hour_summary_matches_bag_timestamps():
    result = run_shift_capacity(_base(summary_interval_min=60))
    assert result["time_summary"]
    assert all((row["time_min"] - result["time_summary"][0]["time_min"]) % 60 == 0 for row in result["time_summary"])
    for row in result["time_summary"]:
        t = row["time_min"]
        ready = sum(1 for b in result["bag_rows"] if parse_clock_minutes(b["ready_to_fold"]) <= t)
        assert row["bags_ready"] == ready


def test_ready_by_batch_cumulative_and_pounds():
    result = run_shift_capacity(_base())
    cum = 0
    cum_lbs = 0.0
    for batch in result["ready_to_fold_by_batch"]:
        cum += batch["bags"]
        cum_lbs += batch["pounds"]
        assert batch["cumulative_bags_ready"] == cum
        assert abs(batch["cumulative_pounds_ready"] - cum_lbs) < 1e-6
        assert set(batch["bag_ids"])


def test_summary_totals_reconcile_to_bag_detail():
    result = run_shift_capacity(_base())
    target = parse_clock_minutes("12:00 PM")
    bags_ready = sum(1 for b in result["bag_rows"] if parse_clock_minutes(b["ready_to_fold"]) <= target)
    bags_folded = sum(1 for b in result["bag_rows"] if parse_clock_minutes(b["completed"]) <= target)
    assert result["kpis"]["bags_ready_by_target"] == bags_ready
    assert result["kpis"]["bags_folded_by_target"] == bags_folded


def test_active_staffing_count_at_entry_boundaries():
    result = run_shift_capacity(_base())
    by_time = {row["time_min"]: row for row in result["staffing_summary"]}
    t_folder = parse_clock_minutes("8:00 AM")
    assert by_time[t_folder]["active_folders"] >= 2
    assert by_time[parse_clock_minutes("7:00 AM")]["active_folders"] == 1
