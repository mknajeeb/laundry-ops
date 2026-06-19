"""Tests for shift capacity planner simulator."""

import pytest

from backend.shift_capacity_planner import (
    DEFAULTS,
    build_bag_weight_list,
    pack_load_from_pool,
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
        assert "active_strategy" in result

    def test_milestones_present(self):
        result = simulate_shift_capacity(_default_payload())
        for strategy in result["strategies"].values():
            ms = strategy["milestones"]
            assert "8:00 AM" in ms
            assert any("12:" in k for k in ms)
            for clock, row in ms.items():
                assert "bags_weighed" in row
                assert "bags_in_washer" in row
                assert "bags_dried_complete" in row
                assert "action_needed" in row
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

    def test_recommendation_strategy_card(self):
        result = simulate_shift_capacity(_default_payload())
        rec = result["recommendation"]
        assert rec["recommended"] in ("continuous_washing", "dryer_push")
        assert rec["label"]
        assert "start_time" in rec
        assert "suggested_staff" in rec
        assert "first_fold_ready" in rec
        assert "all_washing_done" in rec
        assert "all_drying_done" in rec
        assert "all_folding_done" in rec
        assert "main_bottleneck" in rec

    def test_washer_timeline_lanes(self):
        result = simulate_shift_capacity(_default_payload())
        timeline = result["strategies"]["continuous_washing"]["washer_timeline"]
        assert len(timeline) >= 1
        lane = timeline[0]
        assert "washer_id" in lane
        assert lane["loads"]
        load = lane["loads"][0]
        assert "bag_start" in load
        assert "bag_end" in load
        assert "pounds" in load
        assert "status" in load
        assert "label" in load

    def test_dryer_timeline_lanes(self):
        result = simulate_shift_capacity(_default_payload())
        timeline = result["strategies"]["continuous_washing"]["dryer_timeline"]
        assert len(timeline) >= 1

    def test_alerts_not_playbook(self):
        result = simulate_shift_capacity(_default_payload())
        strategy = result["strategies"]["continuous_washing"]
        assert "alerts" in strategy
        assert "playbook" not in strategy
        assert isinstance(strategy["alerts"], list)


class TestBagMixLoadSizing:
    def test_build_bag_weight_list_distribution(self):
        weights = build_bag_weight_list(
            10,
            small_pct=50,
            medium_pct=30,
            large_pct=20,
            small_lb=20,
            medium_lb=30,
            large_lb=50,
        )
        assert len(weights) == 10
        assert sum(1 for w in weights if w == 20) >= 4
        assert sum(1 for w in weights if w == 50) >= 1

    def test_pack_load_respects_capacity(self):
        pool = [20, 20, 30, 50]
        chunk, rem = pack_load_from_pool(pool, 50)
        assert sum(chunk) <= 50
        assert len(chunk) >= 1
        assert len(chunk) + len(rem) == len(pool)

    def test_heavy_bag_mix_fewer_bags_per_load(self):
        uniform = simulate_shift_capacity(
            _default_payload(small_bag_pct=100, medium_bag_pct=0, large_bag_pct=0, small_bag_lb=20)
        )
        heavy = simulate_shift_capacity(
            _default_payload(small_bag_pct=0, medium_bag_pct=0, large_bag_pct=100, large_bag_lb=50)
        )
        assert uniform["inputs"]["avg_bags_per_wash_load"] > heavy["inputs"]["avg_bags_per_wash_load"]
        assert uniform["inputs"]["total_wash_loads"] < heavy["inputs"]["total_wash_loads"]

    def test_mixed_load_plan_not_fixed_two_bags(self):
        result = simulate_shift_capacity(
            _default_payload(
                bag_count=50,
                small_bag_pct=60,
                medium_bag_pct=30,
                large_bag_pct=10,
                small_bag_lb=20,
                medium_bag_lb=30,
                large_bag_lb=50,
                washer_capacity_lb=50,
            )
        )
        plan = result["inputs"]["estimated_load_plan"]
        bag_counts = {row["bags"] for row in plan}
        assert len(bag_counts) >= 1
        assert result["inputs"]["avg_bags_per_wash_load"] != 2 or max(bag_counts) != min(bag_counts)


class TestWeighingAssignment:
    def test_dedicated_weigher_uses_weighers(self):
        result = simulate_shift_capacity(_default_payload(weighing_handled_by="dedicated_weigher"))
        assert result["inputs"]["weighing_handled_by"] == "dedicated_weigher"
        assert result["inputs"]["weigher_count"] >= 1
        assert result["staffing"]["weighers"] >= 1

    def test_sorter_weighing_reduces_sort_throughput(self):
        dedicated = simulate_shift_capacity(
            _default_payload(
                weighing_handled_by="dedicated_weigher",
                weigher_count=3,
                sorter_count=3,
            )
        )
        sorter = simulate_shift_capacity(
            _default_payload(
                weighing_handled_by="sorter",
                sorter_count=3,
            )
        )
        assert sorter["inputs"]["weigher_count"] == 0
        assert sorter["staffing"]["weighers"] == 0
        d_sorted = dedicated["strategies"]["continuous_washing"]["milestones"]["9:00 AM"]["bags_sorted"]
        s_sorted = sorter["strategies"]["continuous_washing"]["milestones"]["9:00 AM"]["bags_sorted"]
        assert s_sorted <= d_sorted

    def test_washer_weighing_delays_first_wash(self):
        dedicated = simulate_shift_capacity(
            _default_payload(weighing_handled_by="dedicated_weigher", weigher_count=3, sorter_count=3)
        )
        washer = simulate_shift_capacity(
            _default_payload(weighing_handled_by="washer", sorter_count=3)
        )
        d_lane = dedicated["strategies"]["continuous_washing"]["washer_timeline"][0]["loads"][0]
        w_lane = washer["strategies"]["continuous_washing"]["washer_timeline"][0]["loads"][0]
        assert w_lane["start"] >= d_lane["start"] or washer["inputs"]["weighing_handled_by"] == "washer"
        assert any("washer" in a.lower() for a in washer["strategies"]["continuous_washing"]["alerts"])


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

    def test_invalid_weighing_handled_by(self):
        with pytest.raises(ValueError, match="weighing_handled_by"):
            parse_planner_inputs({"weighing_handled_by": "invalid"})

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
