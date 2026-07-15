"""API contract tests for bag_des_v2."""

from backend.shift_capacity_planner import simulate_shift_capacity


def _base(**overrides):
    payload = {
        "start_time": "7:00 AM",
        "target_time": "12:00 PM",
        "bag_count": 6,
        "avg_lbs_per_bag": 20,
        "batch_size": 3,
        "washer_count": 1,
        "dryer_count": 1,
        "wash_cycle_min": 20,
        "dry_cycle_min": 25,
        "fold_lbs_per_hour": 40,
        "_skip_recommendations": True,
        "employees": [
            {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM"},
            {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM"},
            {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM"},
            {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 40},
        ],
    }
    payload.update(overrides)
    return payload


def test_bag_des_v2_is_default():
    result = simulate_shift_capacity(_base())
    assert result["engine"] == "bag_des_v2"
    assert result["scenario_id"]
    assert result["overlap_errors"] == []


def test_legacy_bag_des_remains_selectable():
    result = simulate_shift_capacity(_base(engine="bag_des"))
    assert result["engine"] == "bag_des"


def test_invalid_requests_return_structured_errors():
    result = simulate_shift_capacity(
        _base(
            batch_overrides=[
                {
                    "batch_number": 1,
                    "bag_ids": ["ORD-1-1", "ORD-1-2", "ORD-1-3", "ORD-1-4", "ORD-2-1"],
                    "apply_scope": "this_batch_only",
                }
            ]
        )
    )
    assert result["simulation_valid"] is False
    assert result["validation"]["accepted"] is False
    assert result["validation"]["errors"]


def test_successful_responses_contain_no_overlap_errors():
    result = simulate_shift_capacity(_base())
    assert result["simulation_valid"] is True
    assert result["overlap_errors"] == []


def test_scenario_ids_returned():
    result = simulate_shift_capacity(_base())
    assert result["scenario_id"].startswith("scn_")
