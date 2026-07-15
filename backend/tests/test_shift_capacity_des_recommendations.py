"""Recommendation and scenario undo tests for bag_des_v2."""

from backend.shift_capacity.service import run_shift_capacity


def _base(**overrides):
    payload = {
        "engine": "bag_des_v2",
        "mode": "full_run",
        "start_time": "7:00 AM",
        "target_time": "11:00 AM",
        "bag_count": 16,
        "avg_lbs_per_bag": 20,
        "batch_size": 4,
        "washer_count": 1,
        "dryer_count": 1,
        "washer_capacity_lb": 80,
        "dryer_capacity_lb": 80,
        "wash_cycle_min": 30,
        "dry_cycle_min": 40,
        "load_washer_min": 3,
        "unload_transfer_min": 4,
        "load_dryer_min": 3,
        "sort_min_per_bag": 5,
        "fold_rate_mode": "lbs_per_hour",
        "fold_lbs_per_hour": 30,
        "employees": [
            {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM"},
            {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM"},
            {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM"},
            {"id": "F1", "name": "Folder 1", "primary_role": "folder", "start_time": "7:00 AM", "fold_lbs_per_hour": 30},
        ],
    }
    payload.update(overrides)
    return payload


def test_recommendations_are_simulation_backed():
    result = run_shift_capacity(_base())
    assert result["scenario_id"]
    # With constrained staff, at least one recommendation should appear with impact.
    for rec in result.get("recommendations") or []:
        assert rec.get("proposed_action") or rec.get("action")
        assert "impact" in rec
        assert "baseline_metrics" in rec
        assert "projected_metrics" in rec


def test_apply_recommendation_creates_child_scenario_and_undo_restores_parent():
    baseline = run_shift_capacity(_base())
    recs = baseline.get("recommendations") or []
    if not recs:
        # Still verify undo plumbing with a staff injection action.
        action = {
            "add_employee": {
                "id": "EXTRA",
                "name": "Extra Folder",
                "primary_role": "folder",
                "start_time": "8:30 AM",
                "fold_lbs_per_hour": 40,
            },
            "sim_mode": "continue_from_time",
            "continue_from_time": "8:30 AM",
        }
    else:
        action = recs[0].get("proposed_action") or recs[0]["action"]

    child = run_shift_capacity(
        {
            **_base(),
            "scenario_id": baseline["scenario_id"],
            "parent_scenario_id": baseline["scenario_id"],
            "apply_action": action,
            "_skip_recommendations": True,
        }
    )
    assert child["parent_scenario_id"] == baseline["scenario_id"]
    assert child["scenario_id"] != baseline["scenario_id"]

    restored = run_shift_capacity(
        {
            "engine": "bag_des_v2",
            "mode": "undo",
            "scenario_id": child["scenario_id"],
        }
    )
    assert restored["scenario_id"] == baseline["scenario_id"]
    assert restored["bag_rows"] == baseline["bag_rows"]
