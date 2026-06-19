"""Tests for shift capacity planner simulator."""

import pytest

from backend.shift_capacity_planner import (
    DEFAULTS,
    parse_planner_inputs,
    simulate_shift_capacity,
)


def _default_payload(**overrides):
    data = {**DEFAULTS, **overrides}
    return {k: v for k, v in data.items() if v is not None}


class TestShiftCapacityPlannerDefaults:
    def test_50_bag_simulation_runs(self):
        result = simulate_shift_capacity(_default_payload())
        assert result["inputs"]["bag_count"] == 50
        assert "continuous_washing" in result["strategies"]
        assert "dryer_push" in result["strategies"]

    def test_milestones_present(self):
        result = simulate_shift_capacity(_default_payload())
        for strategy in result["strategies"].values():
            ms = strategy["milestones"]
            assert "8:00 AM" in ms
            assert "12:00 PM" in ms or "12:00 PM" in ms or any("12:" in k for k in ms)
            for clock, row in ms.items():
                assert "bags_weighed" in row
                assert "bottleneck" in row

    def test_both_strategies_differ_or_match(self):
        result = simulate_shift_capacity(_default_payload())
        cont = result["strategies"]["continuous_washing"]["final"]
        push = result["strategies"]["dryer_push"]["final"]
        assert cont["bags_weighed"] == 50
        assert push["bags_weighed"] == 50

    def test_staffing_heuristics(self):
        result = simulate_shift_capacity(_default_payload())
        staffing = result["staffing"]
        assert staffing["weighers"] >= 1
        assert staffing["sorters"] >= 1
        assert staffing["folders"] >= 1
        assert staffing["using_weighers"] >= 1

    def test_bottleneck_identified(self):
        result = simulate_shift_capacity(_default_payload())
        bn = result["strategies"]["continuous_washing"]["final"]["bottleneck"]
        assert bn in {"weighing", "sorting", "washing", "waiting_dryer", "drying", "folding", "none"}

    def test_recommendation(self):
        result = simulate_shift_capacity(_default_payload())
        assert result["recommendation"]["recommended"] in ("continuous_washing", "dryer_push")
        assert result["recommendation"]["label"]

    def test_machine_lanes(self):
        result = simulate_shift_capacity(_default_payload())
        lanes = result["strategies"]["continuous_washing"]["machine_lanes"]
        assert "washers" in lanes
        assert len(lanes["washers"]) >= 1

    def test_playbook_lines(self):
        result = simulate_shift_capacity(_default_payload())
        book = result["strategies"]["continuous_washing"]["playbook"]
        assert len(book) >= 3
        assert any("Shift playbook" in line for line in book)


class TestShiftCapacityPlannerInvalid:
    def test_invalid_bag_count(self):
        with pytest.raises(ValueError, match="bag_count"):
            parse_planner_inputs({"bag_count": 0})

    def test_target_before_start(self):
        with pytest.raises(ValueError, match="target_time"):
            parse_planner_inputs({"start_time": "12:00 PM", "target_time": "7:00 AM"})

    def test_invalid_time(self):
        with pytest.raises(ValueError, match="Invalid time"):
            parse_planner_inputs({"start_time": "not-a-time"})

    def test_simulate_invalid_returns_via_route_logic(self):
        with pytest.raises(ValueError):
            simulate_shift_capacity({"bag_count": -1})


class TestShiftCapacityPlannerCustomStaff:
    def test_explicit_weigher_sorter_counts(self):
        result = simulate_shift_capacity(
            _default_payload(weigher_count=2, sorter_count=2, folder_count=5)
        )
        assert result["inputs"]["weigher_count"] == 2
        assert result["inputs"]["sorter_count"] == 2
        assert result["inputs"]["folder_count"] == 5
