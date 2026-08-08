"""Hard invariants for the owner 5:00–6:00 Sort/Wash correctness scenario."""

from __future__ import annotations

from backend.shift_capacity.service import run_shift_capacity
from backend.shift_capacity.timebase import parse_clock_seconds


def _owner_payload(intervals, **overrides):
    payload = {
        "engine": "bag_des_v2",
        "management_mode": True,
        "mode": "full_run",
        "start_time": "5:00 AM",
        "target_time": "3:00 PM",
        "end_time": "3:00 PM",
        "planning_block_size_min": 60,
        "bag_count": 100,
        "batch_size": 8,
        "washer_count": 24,
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


def _claimed_ui_intervals():
    """Staffing as shown: Weigh 1 for hour; Sort +2 temp 5:30–6:00; Wash/Dry/Fold 0."""
    return [
        {
            "role": "weigher",
            "people": 1,
            "start": "5:00 AM",
            "end": "6:00 AM",
            "mode": "base",
        },
        {
            "role": "sorter",
            "people": 2,
            "start": "5:30 AM",
            "end": "6:00 AM",
            "mode": "additional",
        },
    ]


def test_owner_claimed_staffing_sort_cap_and_zero_wash():
    result = run_shift_capacity(_owner_payload(_claimed_ui_intervals()))
    assert result["simulation_valid"] is True
    assert result.get("inputs", {}).get("management_mode") is True or True

    compiled = (result.get("staffing_plan") or {}).get("compiled_resources") or []
    ids = [c["id"] for c in compiled]
    assert ids == ["MGMT_WEIGH_001", "MGMT_SORT_001", "MGMT_SORT_002"]
    assert not any(i.startswith("MGMT_WASH") for i in ids)
    assert not any(i.startswith("MGMT_DRY") for i in ids)
    assert not any(i.startswith("MGMT_FOLD") for i in ids)
    assert not any(i.startswith("__") for i in ids)

    b6 = next(b for b in result["block_positions"] if b["block_end"] == "6:00 AM")
    # 2 sorters × 30 min / 5 min/bag = 12
    assert b6["sorted_this_block"] <= 12
    assert b6["sorted_this_block"] == 12
    assert b6["sorted_total"] == 12
    assert b6["washed_this_block"] == 0
    assert b6["washed_total"] == 0
    assert b6["waiting_to_wash"] == 12

    t0 = parse_clock_seconds("5:00 AM")
    t1 = parse_clock_seconds("6:00 AM")
    sort_ends = []
    wash_starts = []
    for row in result["bag_rows"]:
        if row.get("sort_end"):
            sec = parse_clock_seconds(row["sort_end"])
            if t0 < sec <= t1:
                sort_ends.append(row)
        if row.get("washer_load_start") or row.get("wash_start"):
            for key in ("washer_load_start", "wash_start"):
                if row.get(key) and t0 < parse_clock_seconds(row[key]) <= t1:
                    wash_starts.append(row)
                    break

    assert len(sort_ends) == b6["sorted_this_block"]
    assert len(wash_starts) == 0
    assert all(row.get("wash_start") is None for row in result["bag_rows"])
    assert all(row.get("washer_load_start") is None for row in result["bag_rows"])


def test_hidden_mid_block_base_sorter_explains_eighteen():
    """BASE sorter 5:30–6:00 + ADDITIONAL +2 => 3 slots => 18 sorted (UI used to hide BASE)."""
    intervals = _claimed_ui_intervals() + [
        {
            "role": "sorter",
            "people": 1,
            "start": "5:30 AM",
            "end": "6:00 AM",
            "mode": "base",
        }
    ]
    result = run_shift_capacity(_owner_payload(intervals))
    compiled = (result.get("staffing_plan") or {}).get("compiled_resources") or []
    assert len([c for c in compiled if c["id"].startswith("MGMT_SORT")]) == 3
    b6 = next(b for b in result["block_positions"] if b["block_end"] == "6:00 AM")
    assert b6["sorted_this_block"] == 18
    assert b6["washed_this_block"] == 0


def test_block_position_deltas_match_bag_timestamps():
    result = run_shift_capacity(_owner_payload(_claimed_ui_intervals()))
    t0 = parse_clock_seconds("5:00 AM")
    t1 = parse_clock_seconds("6:00 AM")
    sort_ts = sum(
        1
        for row in result["bag_rows"]
        if row.get("sort_end") and t0 < parse_clock_seconds(row["sort_end"]) <= t1
    )
    wash_ts = sum(
        1
        for row in result["bag_rows"]
        if row.get("wash_end") and t0 < parse_clock_seconds(row["wash_end"]) <= t1
    )
    b6 = next(b for b in result["block_positions"] if b["block_end"] == "6:00 AM")
    assert b6["sorted_this_block"] == sort_ts
    assert b6["washed_this_block"] == wash_ts


def test_wash_staff_zero_never_starts_wash_even_with_many_machines():
    result = run_shift_capacity(
        _owner_payload(_claimed_ui_intervals(), washer_count=24, dryer_count=24)
    )
    assert all(row.get("washer_load_start") is None for row in result["bag_rows"])
    assert all(row.get("wash_start") is None for row in result["bag_rows"])
    b6 = next(b for b in result["block_positions"] if b["block_end"] == "6:00 AM")
    assert b6["washed_this_block"] == 0
    assert b6["waiting_to_wash"] == b6["sorted_total"]
