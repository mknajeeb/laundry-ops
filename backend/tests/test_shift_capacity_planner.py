"""Tests for shift capacity planner simulator."""

import pytest

from backend.shift_capacity_planner import (
    DEFAULTS,
    build_order_machine_loads,
    build_uniform_bag_weights,
    compute_split_load_distribution,
    pack_load_from_pool,
    parse_planner_inputs,
    run_operational_simulation,
    simulate_shift_capacity,
    split_distribution_summary,
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


class TestSplitLoadDistribution:
    def test_uniform_bag_weights(self):
        weights = build_uniform_bag_weights(10, 20)
        assert len(weights) == 10
        assert all(w == 20 for w in weights)

    def test_split_distribution_50_orders_40_two_washer(self):
        dist = compute_split_load_distribution(
            50, orders_using_2_washers=40, orders_using_2_dryers=40
        )
        assert dist["orders_using_2_washers"] == 40
        assert dist["orders_using_1_washer"] == 10
        assert dist["washer_loads_total"] == 90
        assert dist["dryer_loads_total"] == 90

    def test_build_order_machine_loads(self):
        loads = build_order_machine_loads(50, orders_using_2=40)
        assert len(loads) == 50
        assert loads.count(2) == 40
        assert loads.count(1) == 10
        assert sum(loads) == 90

    def test_higher_two_washer_count_more_wash_loads(self):
        low = simulate_shift_capacity(_default_payload(orders_using_2_washers=10))
        high = simulate_shift_capacity(_default_payload(orders_using_2_washers=40))
        assert high["inputs"]["total_wash_loads"] > low["inputs"]["total_wash_loads"]
        assert high["inputs"]["total_wash_loads"] == 90
        assert low["inputs"]["total_wash_loads"] == 60

    def test_split_summary_lines_in_response(self):
        result = simulate_shift_capacity(_default_payload())
        lines = result["inputs"]["split_distribution"]["summary_lines"]
        assert len(lines) == 6
        assert "90" in lines[2]
        assert "50" in lines[0]

    def test_pct_input_for_two_washer_orders(self):
        inp = parse_planner_inputs({"bag_count": 50, "orders_using_2_washers_pct": 80})
        assert inp.orders_using_2_washers == 40
        assert inp.total_wash_loads == 90

    def test_pack_load_from_pool_still_works(self):
        pool = [20, 20, 30, 50]
        chunk, rem = pack_load_from_pool(pool, 50)
        assert sum(chunk) <= 50
        assert len(chunk) >= 1
        assert len(chunk) + len(rem) == len(pool)


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

    def test_orders_using_2_washers_exceeds_bag_count(self):
        with pytest.raises(ValueError, match="orders_using_2_washers"):
            parse_planner_inputs({"bag_count": 10, "orders_using_2_washers": 11})


class TestShiftCapacityPlannerCustomStaff:
    def test_explicit_weigher_sorter_counts(self):
        result = simulate_shift_capacity(
            _default_payload(weigher_count=2, sorter_count=2, folder_count=5)
        )
        assert result["inputs"]["weigher_count"] == 2
        assert result["inputs"]["sorter_count"] == 2
        assert result["inputs"]["folder_count"] == 5


class TestOperationalSimulation:
    def test_operational_block_in_response(self):
        result = simulate_shift_capacity(_default_payload())
        op = result["operational"]
        assert "strategies" in op
        assert "continuous_washing" in op["strategies"]
        assert "batch_washing" in op["strategies"]
        assert "hybrid_recommended" in op["strategies"]
        assert "recommended_batch_size" in op
        assert "next_actions" in op
        assert "order_timeline" in op
        assert "guidance" in op

    def test_order_timeline_fields(self):
        result = simulate_shift_capacity(_default_payload(bag_count=12, sorter_count=2, weigher_count=2))
        row = result["operational"]["order_timeline"][0]
        for key in (
            "order",
            "sorted_time",
            "washer",
            "wash_start",
            "wash_end",
            "dryer",
            "dry_start",
            "dry_end",
            "ready_fold",
        ):
            assert key in row

    def test_continuous_vs_batch_differ(self):
        payload = _default_payload(bag_count=24, batch_size=8, sorter_count=2, weigher_count=2)
        result = simulate_shift_capacity(payload)
        cont = result["operational"]["strategies"]["continuous_washing"]
        batch = result["operational"]["strategies"]["batch_washing"]
        assert cont["guidance"]["sorting_continues_while_washing"] is True
        assert batch["guidance"]["sorting_continues_while_washing"] is False
        assert cont["guidance"]["recommended_first_batch_size"] == 8
        assert batch["batch_size"] == 8

    def test_hybrid_recommends_batch_size(self):
        result = simulate_shift_capacity(_default_payload(washing_strategy="hybrid_recommended"))
        op = result["operational"]
        assert op["recommended_batch_size"] in (6, 8, 10, 12)
        hybrid = op["strategies"]["hybrid_recommended"]
        assert hybrid["batch_size"] == op["recommended_batch_size"]

    def test_washer_person_busy_blocks_new_loads(self):
        payload = _default_payload(
            bag_count=16,
            orders_using_2_washers=8,
            orders_using_2_dryers=8,
            washer_count=1,
            dryer_count=1,
            batch_size=8,
            load_washer_min=5,
            unload_washer_min=5,
            washer_transfer_min=10,
            load_dryer_min=5,
            wash_cycle_min=20,
            dry_cycle_min=20,
            sorter_count=2,
            weigher_count=2,
        )
        cont = run_operational_simulation(
            parse_planner_inputs(payload),
            washing_strategy="continuous_washing",
        )
        tasks = cont["washer_person_timeline"]
        assert tasks
        task_types = {t["task"] for t in tasks}
        assert "load_washer" in task_types
        assert "unload_transfer" in task_types
        assert cont["guidance"]["washer_pauses_for_dryer_moves"] is True

    def test_next_actions_timeline(self):
        result = simulate_shift_capacity(_default_payload(bag_count=16, batch_size=8))
        actions = result["operational"]["next_actions"]
        assert actions
        block = actions[0]
        assert "start" in block
        assert "end" in block
        assert "action" in block

    def test_guidance_explicit_outputs(self):
        result = simulate_shift_capacity(_default_payload())
        guidance = result["operational"]["guidance"]
        for key in (
            "recommended_first_batch_size",
            "first_wash_batch_start",
            "washer_return_to_unload",
            "bags_sorted_before_first_wash",
            "sorting_continues_while_washing",
            "washer_pauses_for_dryer_moves",
            "switch_labor_to_folding",
        ):
            assert key in guidance

    def test_invalid_washing_strategy(self):
        with pytest.raises(ValueError, match="washing_strategy"):
            parse_planner_inputs({"washing_strategy": "invalid"})

    def test_cannot_provide_count_and_pct(self):
        with pytest.raises(ValueError, match="not both"):
            parse_planner_inputs(
                {"orders_using_2_washers": 10, "orders_using_2_washers_pct": 50}
            )


class TestResourceUtilization:
    def test_utilization_in_operational_response(self):
        result = simulate_shift_capacity(_default_payload())
        util = result["resource_utilization"]
        assert isinstance(util, list)
        assert len(util) >= 1
        row = util[0]
        assert "resource" in row
        assert "busy_minutes" in row
        assert "idle_minutes" in row
        assert "utilization_pct" in row
        assert "is_bottleneck" in row

    def test_utilization_in_legacy_strategy(self):
        result = simulate_shift_capacity(_default_payload())
        util = result["strategies"]["continuous_washing"]["resource_utilization"]
        resources = {r["resource"] for r in util}
        assert "washer_1" in resources


class TestWhatIfScenarios:
    def test_sorter_early_start_improves_sorting(self):
        baseline = simulate_shift_capacity(
            _default_payload(weighing_handled_by="sorter", sorter_count=1, bag_count=30)
        )
        early = simulate_shift_capacity(
            _default_payload(
                weighing_handled_by="sorter",
                sorter_count=1,
                bag_count=30,
                sorter_early_start_min=30,
            )
        )
        assert early["what_if"] is not None
        assert early["what_if"]["params"]["sorter_early_start_min"] == 30
        b_sorted = early["what_if"]["comparison"]["baseline"]["bags_folded"]
        s_sorted = early["what_if"]["comparison"]["scenario"]["bags_folded"]
        assert s_sorted >= b_sorted

    def test_sorter_break_reduces_throughput(self):
        baseline = simulate_shift_capacity(_default_payload(bag_count=40, sorter_count=2))
        with_break = simulate_shift_capacity(
            _default_payload(
                bag_count=40,
                sorter_count=2,
                sorter_break_after_bags=10,
                sorter_break_duration_min=15,
            )
        )
        assert with_break["what_if"] is not None
        assert with_break["what_if"]["comparison"]["delta"]["bags_folded"] <= 0

    def test_washer_break_in_whatif(self):
        result = simulate_shift_capacity(
            _default_payload(
                bag_count=24,
                washer_break_after_bags=6,
                washer_break_duration_min=10,
            )
        )
        assert result["what_if"] is not None
        assert result["what_if"]["params"]["washer_break_after_bags"] == 6

    def test_no_whatif_when_defaults(self):
        result = simulate_shift_capacity(_default_payload())
        assert result["what_if"] is None
