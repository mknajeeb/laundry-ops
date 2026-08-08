"""Dry must progress when explicit DRY staff exists and bags are waiting_to_dry."""

from __future__ import annotations

from backend.shift_capacity.service import run_shift_capacity
from backend.shift_capacity.timebase import parse_clock_seconds


def _payload(intervals, **overrides):
    payload = {
        "engine": "bag_des_v2",
        "management_mode": True,
        "mode": "full_run",
        "start_time": "5:00 AM",
        "target_time": "3:00 PM",
        "end_time": "3:00 PM",
        "planning_block_size_min": 60,
        "bag_count": 16,
        "batch_size": 2,
        "washer_count": 4,
        "dryer_count": 4,
        "weigh_sec_per_bag": 45,
        "sort_min_per_bag": 5,
        "load_washer_min": 3,
        "wash_cycle_min": 25,
        "load_dryer_min": 3,
        "dry_cycle_min": 40,
        "fold_min_per_bag": 30,
        "fold_rate_mode": "minutes_per_bag",
        "two_washer_split_pct": 0,
        "two_dryer_split_pct": 0,
        "_skip_recommendations": True,
        "staffing_plan": {"intervals": intervals},
    }
    payload.update(overrides)
    return payload


def test_waiting_to_dry_at_6_with_dry_staff_6_to_7_progresses():
    """Owner regression: 8 washed waiting at 6:00 + DRY=1 for 6–7 must enter Dry."""
    intervals = [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "7:00 AM", "mode": "base"},
        {"role": "sorter", "people": 2, "start": "5:00 AM", "end": "7:00 AM", "mode": "base"},
        {"role": "washer", "people": 2, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
        {"role": "dryer", "people": 1, "start": "6:00 AM", "end": "7:00 AM", "mode": "base"},
    ]
    # 24 washers so labor—not machine count—feeds bags into waiting_to_dry by 6:00.
    result = run_shift_capacity(_payload(intervals, bag_count=8, batch_size=2, washer_count=24, dryer_count=24))
    assert result["simulation_valid"] is True

    compiled = [c["id"] for c in result["staffing_plan"]["compiled_resources"]]
    assert "MGMT_DRY_001" in compiled
    assert not any(i.startswith("__") for i in compiled)

    t6 = parse_clock_seconds("6:00 AM")
    t7 = parse_clock_seconds("7:00 AM")
    b6 = next(b for b in result["block_positions"] if b["block_end"] == "6:00 AM")
    b7 = next(b for b in result["block_positions"] if b["block_end"] == "7:00 AM")

    assert b6["washed_total"] >= 8
    # Bags with dryer_load_start exactly at 6:00 leave waiting_to_dry at the boundary.
    assert b6["waiting_to_dry"] + b6.get("in_dry_cycle", 0) + b6.get("in_dry_labor", 0) >= 8
    assert b6["dried_total"] == 0

    washed = [r for r in result["bag_rows"] if r.get("wash_end") and parse_clock_seconds(r["wash_end"]) <= t6]
    assert len(washed) >= 8

    dry_loads = [
        r
        for r in washed
        if r.get("dryer_load_start") and t6 <= parse_clock_seconds(r["dryer_load_start"]) < t7
    ]
    assert len(dry_loads) >= 1
    assert all(r.get("dryer_loaded_by_employee_id") == "MGMT_DRY_001" for r in dry_loads)
    assert all(r.get("dry_start") for r in dry_loads)
    assert all(r.get("dryer_id") for r in dry_loads)
    assert not any(str(r.get("dryer_loaded_by_employee_id") or "").startswith("__") for r in dry_loads)

    # Cycle is 40 min: loads after ~6:20 may not finish by 7:00 — that is OK.
    # Bags that entered Dry must leave waiting_to_dry.
    assert b7["waiting_to_dry"] < b6["waiting_to_dry"]
    in_dry_or_done = b7.get("in_dry_cycle", 0) + b7["dried_total"]
    assert in_dry_or_done >= 1

    dried_ts = sum(
        1
        for r in result["bag_rows"]
        if r.get("ready_to_fold") and t6 < parse_clock_seconds(r["ready_to_fold"]) <= t7
    )
    assert b7["dried_this_block"] == dried_ts
    assert b7["dried_total"] == sum(
        1
        for r in result["bag_rows"]
        if r.get("ready_to_fold") and parse_clock_seconds(r["ready_to_fold"]) <= t7
    )


def test_default_80pct_washer_split_does_not_block_all_dry():
    """2-washer split must not wait for the late wash sibling before any Dry starts."""
    intervals = [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
        {"role": "sorter", "people": 3, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
        {"role": "washer", "people": 1, "start": "6:00 AM", "end": "7:00 AM", "mode": "base"},
        {"role": "dryer", "people": 1, "start": "6:00 AM", "end": "7:00 AM", "mode": "base"},
    ]
    result = run_shift_capacity(
        _payload(
            intervals,
            bag_count=16,
            batch_size=8,
            two_washer_split_pct=80,
            two_dryer_split_pct=0,
            washer_count=24,
            dryer_count=24,
        )
    )
    assert result["simulation_valid"] is True
    assert "MGMT_DRY_001" in [c["id"] for c in result["staffing_plan"]["compiled_resources"]]

    t7 = parse_clock_seconds("7:00 AM")
    washed_by_7 = [
        r
        for r in result["bag_rows"]
        if r.get("wash_end") and parse_clock_seconds(r["wash_end"]) <= t7
    ]
    assert washed_by_7
    dry_started = [r for r in washed_by_7 if r.get("dryer_load_start")]
    assert dry_started, "early wash-split parent must enter Dry as soon as parent wash completes"
    assert all(r.get("dryer_loaded_by_employee_id") == "MGMT_DRY_001" for r in dry_started)

    b7 = next(b for b in result["block_positions"] if b["block_end"] == "7:00 AM")
    assert b7["waiting_to_dry"] < b7["washed_total"] or b7.get("in_dry_cycle", 0) > 0


def test_late_dry_staff_uses_multiple_dryer_machines():
    """Wash before dry window must not pile every batch onto D1 only."""
    intervals = [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "7:00 AM", "mode": "base"},
        {"role": "sorter", "people": 2, "start": "5:00 AM", "end": "7:00 AM", "mode": "base"},
        {"role": "washer", "people": 2, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
        {"role": "dryer", "people": 1, "start": "6:00 AM", "end": "7:00 AM", "mode": "base"},
    ]
    result = run_shift_capacity(
        _payload(intervals, bag_count=16, batch_size=2, washer_count=24, dryer_count=4)
    )
    dry_started = [r for r in result["bag_rows"] if r.get("dryer_load_start")]
    assert dry_started
    dryer_ids = {r.get("dryer") or r.get("dryer_id") for r in dry_started}
    # Flatten joined parent dryer ids from dual loads.
    flat = {p for d in dryer_ids for p in str(d or "").split("+") if p}
    assert len(flat) >= 2, f"expected parallel dryers, got {dryer_ids}"
