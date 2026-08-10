"""Read-only 15-min availability_checkpoints on block_positions (no DES changes)."""

from __future__ import annotations

from backend.shift_capacity.block_positions import (
    _checkpoint_times,
    bag_state_at,
    build_availability_checkpoints,
)
from backend.shift_capacity.service import run_shift_capacity
from backend.shift_capacity.timebase import parse_clock_seconds


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


def test_checkpoint_counts_for_block_sizes():
    w0 = parse_clock_seconds("5:00 AM")
    assert len(_checkpoint_times(w0, w0 + 30 * 60)) == 2
    assert len(_checkpoint_times(w0, w0 + 45 * 60)) == 3
    assert len(_checkpoint_times(w0, w0 + 60 * 60)) == 4
    # Short final: 20 min → one mid mark? 5:00+15=5:15 < 5:20, then end → 2
    assert len(_checkpoint_times(w0, w0 + 20 * 60)) == 2
    # Very short 10 min → only end
    assert _checkpoint_times(w0, w0 + 10 * 60) == [w0 + 10 * 60]


def test_60min_slot_exposes_four_checkpoints_on_block_positions():
    result = run_shift_capacity(_payload(_staffed()))
    b6 = next(b for b in result["block_positions"] if b["block_end"] == "6:00 AM")
    cps = b6["availability_checkpoints"]
    assert len(cps) == 4
    assert [c["time"] for c in cps] == ["5:15 AM", "5:30 AM", "5:45 AM", "6:00 AM"]
    for c in cps:
        assert "available_to_sort" in c
        assert "newly_available_to_sort" in c
        assert "in_wash_cycle" in c
        assert "weighed_total" in c
        assert "sorted_total" in c
        assert "washed_total" in c
        assert "dried_total" in c
        assert "folded_total" in c
        assert c["waiting_to_weigh"] == c["not_yet_weighed"]
        assert c["waiting_to_sort"] == c["available_to_sort"]


def test_30_and_45_min_checkpoint_counts():
    # 30-min blocks over a full hour: each block exposes 2 checkpoints.
    intervals_60 = [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
    ]
    r30 = run_shift_capacity(_payload(intervals_60, planning_block_size_min=30, bag_count=40))
    assert all(len(b["availability_checkpoints"]) == 2 for b in r30["block_positions"])

    # Staffing must stay within the shortened plan window.
    intervals_45 = [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "5:45 AM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "5:00 AM", "end": "5:45 AM", "mode": "base"},
    ]
    r45 = run_shift_capacity(
        _payload(
            intervals_45,
            planning_block_size_min=45,
            target_time="5:45 AM",
            end_time="5:45 AM",
            bag_count=40,
        )
    )
    assert len(r45["block_positions"][0]["availability_checkpoints"]) == 3


def test_available_is_point_in_time_waiting_queue():
    result = run_shift_capacity(_payload(_staffed()))
    from backend.shift_capacity.validation import parse_inputs
    from backend.shift_capacity.scheduler import run_scheduler

    state = run_scheduler(parse_inputs(_payload(_staffed())))
    b6 = next(b for b in result["block_positions"] if b["block_end"] == "6:00 AM")
    for cp in b6["availability_checkpoints"]:
        t = cp["time_sec"]
        waiting_sort = sum(1 for bag in state.bags if bag_state_at(bag, t) == "waiting_to_sort")
        waiting_wash = sum(1 for bag in state.bags if bag_state_at(bag, t) == "waiting_to_wash")
        assert cp["available_to_sort"] == waiting_sort
        assert cp["available_to_wash"] == waiting_wash


def test_newly_available_from_timestamps_not_availability_delta():
    result = run_shift_capacity(_payload(_staffed()))
    b6 = next(b for b in result["block_positions"] if b["block_end"] == "6:00 AM")
    cps = b6["availability_checkpoints"]
    # With 2 sorters consuming, newly weigh-ready can exceed Δ waiting_to_sort.
    found_divergence = False
    prev_avail = 0
    for cp in cps:
        delta = cp["available_to_sort"] - prev_avail
        if cp["newly_available_to_sort"] != delta:
            found_divergence = True
            break
        prev_avail = cp["available_to_sort"]
    assert found_divergence, "newly_available must not equal availability delta when work is consumed"

    # Explicit: first quarter newly sort ≈ weigher throughput (~20), available lower.
    assert cps[0]["newly_available_to_sort"] >= cps[0]["available_to_sort"]


def test_build_availability_checkpoints_direct_short_slot():
    # Empty bags → zeros but correct times
    w0 = parse_clock_seconds("9:00 AM")
    w1 = w0 + 20 * 60
    rows = build_availability_checkpoints([], block_start=w0, block_end=w1)
    assert len(rows) == 2
    assert rows[-1]["time_sec"] == w1
    assert rows[0]["available_to_sort"] == 0
