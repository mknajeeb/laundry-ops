"""15-min checkpoint stage metrics: this_15 / total / waiting_next / in_process."""

from __future__ import annotations

from backend.shift_capacity.block_positions import bag_state_at, build_availability_checkpoints
from backend.shift_capacity.service import run_shift_capacity
from backend.shift_capacity.validation import parse_inputs
from backend.shift_capacity.scheduler import run_scheduler


def _payload(intervals, **overrides):
    payload = {
        "engine": "bag_des_v2",
        "management_mode": True,
        "mode": "full_run",
        "start_time": "5:00 AM",
        "target_time": "6:00 AM",
        "end_time": "6:00 AM",
        "planning_block_size_min": 60,
        "bag_count": 100,
        "batch_size": 8,
        "washer_count": 24,
        "dryer_count": 24,
        "weigh_sec_per_bag": 45,
        "sort_min_per_bag": 5,
        "load_washer_min": 3,
        "wash_cycle_min": 30,
        "load_dryer_min": 3,
        "dry_cycle_min": 40,
        "fold_min_per_bag": 6,
        "fold_rate_mode": "minutes_per_bag",
        "two_washer_split_pct": 80,
        "two_dryer_split_pct": 80,
        "_skip_recommendations": True,
        "staffing_plan": {"intervals": intervals},
    }
    payload.update(overrides)
    return payload


def _staffed():
    return [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
        {"role": "sorter", "people": 2, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
        {"role": "washer", "people": 1, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
        {"role": "dryer", "people": 1, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
    ]


def test_checkpoint_exposes_four_concepts_per_stage():
    result = run_shift_capacity(_payload(_staffed()))
    b6 = next(b for b in result["block_positions"] if b["block_end"] == "6:00 AM")
    assert len(b6["availability_checkpoints"]) == 4
    for cp in b6["availability_checkpoints"]:
        assert "stages" in cp
        assert set(cp["stages"]) == {"weigh", "sort", "wash", "dry", "fold"}
        for stage in cp["stage_list"]:
            assert "this_15_min" in stage
            assert "total_done" in stage
            assert "waiting_next" in stage
            assert "in_process" in stage
        assert cp["reconciliation"]["ok"] is True
        wash = cp["stages"]["wash"]
        assert wash["waiting_next_label"] == "Dry"
        assert wash["in_process"] >= (wash.get("in_labor", 0) or 0) + (wash.get("in_cycle", 0) or 0)
        fold = cp["stages"]["fold"]
        assert fold["is_terminal"] is True
        assert fold["waiting_next_label"] is None


def test_waiting_next_excludes_upstream_and_in_process():
    result = run_shift_capacity(_payload(_staffed()))
    state = run_scheduler(parse_inputs(_payload(_staffed())))
    b6 = next(b for b in result["block_positions"] if b["block_end"] == "6:00 AM")
    for cp in b6["availability_checkpoints"]:
        t = cp["time_sec"]
        # Sort waiting→Wash must equal bags with sort done and wash not started.
        expected = sum(
            1
            for bag in state.bags
            if bag.sort_end is not None
            and bag.sort_end <= t
            and (bag.washer_load_start is None or bag.washer_load_start > t)
        )
        assert cp["stages"]["sort"]["waiting_next"] == expected
        # Not-yet-weighed must not appear in sort waiting.
        not_weighed = sum(1 for bag in state.bags if bag_state_at(bag, t) == "not_yet_weighed")
        assert cp["stages"]["sort"]["waiting_next"] != not_weighed or not_weighed == 0


def test_this_15_equals_interval_completions():
    result = run_shift_capacity(_payload(_staffed()))
    b6 = next(b for b in result["block_positions"] if b["block_end"] == "6:00 AM")
    cps = b6["availability_checkpoints"]
    # Cumulative totals must be non-decreasing; this_15 sums toward end totals.
    assert cps[-1]["stages"]["weigh"]["total_done"] == sum(c["stages"]["weigh"]["this_15_min"] for c in cps)
    assert cps[-1]["stages"]["sort"]["total_done"] == sum(c["stages"]["sort"]["this_15_min"] for c in cps)


def test_no_staff_wash_keeps_in_process_zero_and_queue_builds():
    intervals = [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
        {"role": "washer", "people": 0, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
    ]
    # Explicit zero washer people is omitted from authored intervals — use no washer interval.
    intervals = [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
    ]
    result = run_shift_capacity(_payload(intervals, bag_count=40, washer_count=8))
    b6 = next(b for b in result["block_positions"] if b["block_end"] == "6:00 AM")
    end = b6["availability_checkpoints"][-1]
    assert end["stages"]["wash"]["total_done"] == 0
    assert end["stages"]["wash"]["in_process"] == 0
    assert end["stages"]["sort"]["waiting_next"] > 0


def test_labor_used_reconciles_for_staffed_hour():
    result = run_shift_capacity(_payload(_staffed()))
    sort = next(r for r in result["work_coverage"] if r.get("role") == "sorter")
    assert abs((sort["used_min"] + sort["idle_min"]) - sort["staff_min"]) < 0.02
    parts = (
        sort["idle_no_eligible_work_min"]
        + sort["unused_fit_min"]
        + float(sort.get("machine_blocked_min") or 0)
    )
    assert abs(parts - sort["idle_min"]) < 0.05
    # Math audit: Sort ~92% labor used (110/120), not a utilization claim of need.
    assert 90 <= round(100 * sort["used_min"] / sort["staff_min"]) <= 93
