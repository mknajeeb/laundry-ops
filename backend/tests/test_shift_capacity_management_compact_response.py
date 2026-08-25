"""Management simulate API returns a compact payload without duplicate DES surface."""

import json

from backend.shift_capacity_planner import simulate_shift_capacity


def _mgmt_payload(**overrides):
    payload = {
        "engine": "bag_des_v2",
        "management_mode": True,
        "mode": "full_run",
        "start_time": "5:00 AM",
        "target_time": "4:00 PM",
        "end_time": "4:00 PM",
        "planning_block_size_min": 60,
        "bag_count": 40,
        "avg_lbs_per_bag": 20,
        "two_washer_split_pct": 50,
        "two_dryer_split_pct": 20,
        "washer_count": 28,
        "dryer_count": 28,
        "batch_size": 8,
        "weigh_sec_per_bag": 45,
        "sort_min_per_bag": 5,
        "load_washer_min": 2,
        "wash_cycle_min": 23,
        "load_dryer_min": 0,
        "dry_cycle_min": 40,
        "fold_min_per_bag": 30,
        "fold_rate_mode": "minutes_per_bag",
        "_skip_recommendations": True,
        "staffing_plan": {
            "intervals": [
                {"role": "weigher", "people": 2, "start": "5:00 AM", "end": "4:00 PM", "mode": "base"},
                {"role": "sorter", "people": 2, "start": "5:00 AM", "end": "4:00 PM", "mode": "base"},
                {"role": "washer", "people": 4, "start": "5:00 AM", "end": "4:00 PM", "mode": "base"},
                {"role": "dryer", "people": 4, "start": "5:00 AM", "end": "4:00 PM", "mode": "base"},
                {"role": "folder", "people": 4, "start": "5:00 AM", "end": "4:00 PM", "mode": "base"},
            ],
        },
    }
    payload.update(overrides)
    return payload


def test_management_simulate_omits_heavy_duplicate_fields():
    result = simulate_shift_capacity(_mgmt_payload())
    assert result.get("simulation_valid") is True
    assert "des" not in result
    assert result.get("bag_rows") in (None, [])
    assert result.get("bags") in (None, [])
    assert result.get("employee_timeline") in (None, [])
    assert result.get("machine_timeline") in (None, [])
    assert result.get("timelines") in (None, {})
    assert result.get("operational") in (None, {})
    assert isinstance(result.get("block_positions"), list)
    assert len(result.get("block_positions") or []) > 0
    assert isinstance(result.get("work_coverage"), list)


def test_management_simulate_response_under_one_megabyte():
    result = simulate_shift_capacity(_mgmt_payload(bag_count=180))
    encoded = json.dumps(result)
    assert len(encoded) < 1_000_000
