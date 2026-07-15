"""Tests for shift capacity planner simulator."""

import math

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
    # Legacy operational planner tests must stay on the pre-DES engine.
    data = {**DEFAULTS, "engine": "legacy", **overrides}
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
        result = simulate_shift_capacity(
            _default_payload(
                weighing_mode="separate_lane",
                weighing_handled_by="dedicated_weigher",
            )
        )
        assert result["inputs"]["weighing_mode"] == "separate_lane"
        assert result["inputs"]["weighing_handled_by"] == "dedicated_weigher"
        assert result["inputs"]["weigher_count"] >= 1
        assert result["staffing"]["weighers"] >= 1

    def test_sorter_weighing_reduces_sort_throughput(self):
        dedicated = simulate_shift_capacity(
            _default_payload(
                weighing_mode="separate_lane",
                weighing_handled_by="dedicated_weigher",
                weigher_count=3,
                sorter_count=3,
            )
        )
        sorter = simulate_shift_capacity(
            _default_payload(
                weighing_mode="during_sort",
                weighing_handled_by="sorter",
                sorter_count=3,
            )
        )
        assert sorter["inputs"]["weigher_count"] == 0
        assert sorter["inputs"]["weighing_mode"] == "during_sort"
        assert sorter["staffing"]["weighers"] == 0
        d_sorted = dedicated["strategies"]["continuous_washing"]["milestones"]["9:00 AM"]["bags_sorted"]
        s_sorted = sorter["strategies"]["continuous_washing"]["milestones"]["9:00 AM"]["bags_sorted"]
        assert s_sorted <= d_sorted

    def test_washer_upfront_weighing_delays_first_wash(self):
        dedicated = simulate_shift_capacity(
            _default_payload(
                weighing_mode="separate_lane",
                weighing_handled_by="dedicated_weigher",
                weigher_count=3,
                sorter_count=3,
            )
        )
        washer = simulate_shift_capacity(
            _default_payload(
                weighing_mode="upfront",
                weighing_handled_by="washer",
                sorter_count=3,
            )
        )
        d_lane = dedicated["strategies"]["continuous_washing"]["washer_timeline"][0]["loads"][0]
        w_lane = washer["strategies"]["continuous_washing"]["washer_timeline"][0]["loads"][0]
        assert w_lane["start"] >= d_lane["start"]
        assert washer["inputs"]["weighing_mode"] == "upfront"
        assert any("washer" in a.lower() for a in washer["strategies"]["continuous_washing"]["alerts"])

    def test_weighing_mode_definitions_in_operational(self):
        result = simulate_shift_capacity(_default_payload())
        op = result["operational"]
        assert "weighing_mode_definitions" in op
        assert "separate_lane" in op["weighing_mode_definitions"]
        assert "during_sort" in op["weighing_mode_definitions"]
        assert "upfront" in op["weighing_mode_definitions"]

    def test_legacy_handled_by_infers_mode(self):
        sorter = parse_planner_inputs({"weighing_handled_by": "sorter"})
        assert sorter.weighing_mode == "during_sort"
        washer = parse_planner_inputs({"weighing_handled_by": "washer"})
        assert washer.weighing_mode == "upfront"

    def test_batch_milestones_include_weigh_and_fold(self):
        result = simulate_shift_capacity(
            _default_payload(washing_strategy="batch_washing", batch_size=8)
        )
        first = result["operational"]["active_strategy"]["batch_milestone_rows"][0]
        assert "weigh_complete_at" in first
        assert "bags_weighed_before_wash" in first
        assert "fold_complete_at" in first


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

    def test_invalid_weighing_mode(self):
        with pytest.raises(ValueError, match="weighing_mode"):
            parse_planner_inputs({"weighing_mode": "invalid"})

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
        assert "batch_washing" in op["strategies"]
        assert "sort_while_drying" in op["strategies"]
        assert "strategy_definitions" in op
        assert "weighing_mode_definitions" in op
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

    def test_bag_availability_forecast_in_guidance(self):
        result = simulate_shift_capacity(
            _default_payload(bag_count=50, sorter_count=2, weigher_count=2, batch_size=8)
        )
        guidance = result["operational"]["strategies"]["sort_while_drying"]["guidance"]
        assert "additional_bags_by_next_batch" in guidance
        assert "next_wash_batch_start" in guidance
        assert "bags_sorted_at_first_wash" in guidance
        assert guidance["bags_sorted_at_first_wash"] >= 1
        assert guidance["additional_bags_by_next_batch"] >= 0
        if guidance["next_wash_batch_start"]:
            assert guidance["bags_sorted_by_next_batch"] >= guidance["bags_sorted_at_first_wash"]

    def test_batch_vs_sort_while_drying_differ(self):
        payload = _default_payload(bag_count=24, batch_size=8, sorter_count=2, weigher_count=2)
        result = simulate_shift_capacity(payload)
        sort_drying = result["operational"]["strategies"]["sort_while_drying"]
        batch = result["operational"]["strategies"]["batch_washing"]
        assert sort_drying["guidance"]["sorting_continues_while_washing"] is True
        assert batch["guidance"]["sorting_continues_while_washing"] is True
        assert batch["batch_milestone_rows"][0]["batch_mode"] is True
        assert sort_drying["batch_milestone_rows"][0]["batch_mode"] is False
        assert batch["batch_size"] == 8

    def test_batch_washing_sorter_does_not_pause(self):
        result = simulate_shift_capacity(
            _default_payload(
                bag_count=50,
                washing_strategy="batch_washing",
                batch_size=8,
                sorter_count=2,
                weigher_count=2,
            )
        )
        rows = result["operational"]["order_timeline"]
        from backend.shift_capacity_planner import _parse_clock_minutes

        t8 = _parse_clock_minutes(rows[7]["sorted_time"], default="7:00 AM")
        t9 = _parse_clock_minutes(rows[8]["sorted_time"], default="7:00 AM")
        assert t9 - t8 < 30, f"sorter paused: order 9 sorted {t9 - t8} min after order 8"
        alerts = result["operational"].get("bottleneck_alerts") or []
        assert not any("sorting paused" in a.lower() for a in alerts)
        assert result["operational"]["guidance"]["sorting_continues_while_washing"] is True

    def test_recommends_optimal_batch_size(self):
        result = simulate_shift_capacity(_default_payload(washing_strategy="batch_washing"))
        op = result["operational"]
        assert op["recommended_batch_size"] in (6, 8, 10, 12)

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
            washing_strategy="sort_while_drying",
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


class TestPlannerBugFixes:
    def test_all_orders_get_dry_times(self):
        result = simulate_shift_capacity(
            _default_payload(bag_count=50, orders_using_2_washers=40, washing_strategy="sort_while_drying")
        )
        rows = result["operational"]["order_timeline"]
        assert len(rows) == 50
        assert all(r["sorted_time"] for r in rows)
        assert all(r["dry_start"] for r in rows), "every order should have dryer pipeline times"
        assert all(r["wash_start"] for r in rows)

    def test_multi_machine_display_on_split_orders(self):
        result = simulate_shift_capacity(_default_payload(bag_count=50, orders_using_2_washers=40))
        row = result["operational"]["order_timeline"][0]
        assert " + " in (row["washer"] or "")
        assert len(row["washers"]) >= 2
        assert len(row["wash_segments"]) >= 2
        assert len(row["dryers"]) >= 1

    def test_batch_mode_sorts_all_orders(self):
        result = simulate_shift_capacity(
            _default_payload(bag_count=50, washing_strategy="batch_washing", batch_size=8)
        )
        rows = result["operational"]["order_timeline"]
        assert sum(1 for r in rows if r["sorted_time"]) == 50
        assert sum(1 for r in rows if r["wash_start"]) > 8

    def test_operational_batch_milestones(self):
        result = simulate_shift_capacity(
            _default_payload(washing_strategy="batch_washing", batch_size=8)
        )
        op = result["operational"]["active_strategy"]
        batch_rows = op["batch_milestone_rows"]
        assert len(batch_rows) >= 1
        first = batch_rows[0]
        assert first["batch_number"] == 1
        assert first["order_range"] == "1–8"
        assert first["orders_in_batch"] == 8
        assert "sorted_available_at_start" in first
        assert "ready_to_fold_at_start" in first
        assert "left_to_sort" in first
        assert "remaining_to_sort_before_wash" in first
        assert first["left_to_sort"] == first["remaining_to_sort_before_wash"]
        assert "wash_start" in first
        assert "wash_end" in first
        assert "wash_duration_min" in first
        assert "dry_start" in first
        assert "dry_duration_min" in first
        assert "time_to_ready_to_fold_min" in first
        assert "batch_end" in first
        assert "batch_end_time" in first
        assert "dryers_loaded" in first
        assert "ready_to_fold_at_end" in first
        assert "bags_ready_to_fold" in first
        assert "folded_at_end" in first
        assert "bags_folded" in first
        assert op["milestone_rows"] == batch_rows
        ms = op["milestones"]
        assert "7:00 AM" in ms
        assert "12:00 PM" in ms
        assert "bags_in_washer" in ms["12:00 PM"]

    def test_batch_mode_milestone_first_batch_sorted(self):
        result = simulate_shift_capacity(
            _default_payload(bag_count=50, washing_strategy="batch_washing", batch_size=8)
        )
        op = result["operational"]["active_strategy"]
        first = op["batch_milestone_rows"][0]
        assert first["sorted_in_batch_before_wash"] == 8
        assert first["sorted_available_at_start"] >= 1
        assert first["ready_to_fold_at_start"] == 0
        assert first["left_to_sort"] <= 42

    def test_batch_milestone_ready_to_fold_at_start_carryover(self):
        result = simulate_shift_capacity(
            _default_payload(bag_count=50, washing_strategy="batch_washing", batch_size=8)
        )
        rows = result["operational"]["active_strategy"]["batch_milestone_rows"]
        assert len(rows) >= 2
        assert rows[0]["ready_to_fold_at_start"] == 0
        assert rows[1]["ready_to_fold_at_start"] >= rows[0]["ready_to_fold_at_end"]

    def test_batch_milestone_pipeline_timing_positive(self):
        result = simulate_shift_capacity(
            _default_payload(bag_count=50, washing_strategy="batch_washing", batch_size=8)
        )
        first = result["operational"]["active_strategy"]["batch_milestone_rows"][0]
        assert first["wash_duration_min"] > 0
        assert first["dry_duration_min"] is not None
        assert first["time_to_ready_to_fold_min"] is not None
        assert first["time_to_ready_to_fold_min"] >= first["wash_duration_min"]

    def test_sorter_and_washer_person_separate_utilization(self):
        result = simulate_shift_capacity(
            _default_payload(bag_count=50, washing_strategy="batch_washing", batch_size=8)
        )
        util = result["operational"]["active_strategy"]["resource_utilization"]
        resources = {row["resource"] for row in util}
        assert "sorter" in resources
        assert "washer_person" in resources
        sorter = next(r for r in util if r["resource"] == "sorter")
        washer_person = next(r for r in util if r["resource"] == "washer_person")
        assert sorter["busy_minutes"] > 0
        assert washer_person["busy_minutes"] > 0

    def test_sort_while_drying_wash_waves(self):
        result = simulate_shift_capacity(
            _default_payload(bag_count=50, washing_strategy="sort_while_drying", batch_size=8)
        )
        op = result["operational"]["active_strategy"]
        rows = op["batch_milestone_rows"]
        assert len(rows) == math.ceil(50 / 8)
        assert rows[0]["batch_mode"] is False
        assert rows[0]["orders_in_batch"] == 8
        assert rows[1]["orders_in_batch"] == 8

    def test_operational_time_milestones_30_min_buckets(self):
        result = simulate_shift_capacity(_default_payload())
        op = result["operational"]["active_strategy"]
        time_rows = op["time_milestone_rows"]
        clocks = {row["time"] for row in time_rows}
        assert "7:00 AM" in clocks
        assert "7:30 AM" in clocks
        assert "12:00 PM" in clocks
        snap = next(row for row in time_rows if row["time"] == "12:00 PM")
        assert "bags_in_washer" in snap
        assert "bags_in_dryer" in snap
        assert "bags_ready_to_fold" in snap
        assert "bags_folded" in snap
        assert "bags_weighed" in snap
        assert "bags_sorted" in snap
        assert "sorted_surplus_before_next_batch" in snap
        assert "bottleneck" in snap
        assert "suggested_action" in snap

    def test_decision_pack_present(self):
        result = simulate_shift_capacity(_default_payload())
        pack = result["operational"]["decision_pack"]
        assert pack["decision_summary"]["total_bags"] == 50
        assert isinstance(pack["action_plan"], list)
        assert pack["batch_command_center"]
        assert pack["next_batch_decision"]

    def test_folder_count_affects_timing(self):
        low = simulate_shift_capacity(_default_payload(folder_count=1))
        high = simulate_shift_capacity(_default_payload(folder_count=5))
        assert low["operational"]["time_milestone_rows"] != high["operational"]["time_milestone_rows"]

    def test_sorter_helps_washer_changes_timing(self):
        none = simulate_shift_capacity(_default_payload(helper_rule="none"))
        helped = simulate_shift_capacity(_default_payload(helper_rule="sorter_helps_washer"))
        none_rows = none["operational"]["time_milestone_rows"]
        helped_rows = helped["operational"]["time_milestone_rows"]
        assert none_rows != helped_rows or (
            none["operational"]["decision_summary"]["folded_by_target"]
            != helped["operational"]["decision_summary"]["folded_by_target"]
        )

    def test_washer_person_count_affects_timing(self):
        one = simulate_shift_capacity(_default_payload(washer_person_count=1))
        two = simulate_shift_capacity(_default_payload(washer_person_count=2))
        one_finish = one["operational"]["decision_summary"].get("estimated_finish_time")
        two_finish = two["operational"]["decision_summary"].get("estimated_finish_time")
        one_folded = one["operational"]["decision_summary"]["folded_by_target"]
        two_folded = two["operational"]["decision_summary"]["folded_by_target"]
        assert two_folded >= one_folded or two_finish != one_finish

    def test_batch_override_from_batch_changes_scenario(self):
        base = simulate_shift_capacity(_default_payload())
        override = simulate_shift_capacity(
            _default_payload(
                batch_overrides=[
                    {
                        "batch_number": 2,
                        "apply_scope": "from_this_batch",
                        "extra_folders": 1,
                    }
                ],
            )
        )
        base_cmp = base["operational"].get("scenario_comparisons") or []
        with_scenarios = simulate_shift_capacity(
            _default_payload(include_scenario_comparisons=True)
        )
        comparisons = with_scenarios["operational"]["scenario_comparisons"]
        assert comparisons
        assert comparisons[0]["scenario"] == "Current"
        folder_row = next(r for r in comparisons if "+1 folder" in r["scenario"])
        assert folder_row["folded_by_target"] >= comparisons[0]["folded_by_target"]
        assert override["operational"]["decision_summary"]["folded_by_target"] >= base[
            "operational"
        ]["decision_summary"]["folded_by_target"]

    def test_batch_override_from_batch_two_affects_batch_two_timing(self):
        """Overrides scoped from batch 2 must apply while batch 2 wash is running."""
        payload = _default_payload(
            start_time="7:00 AM",
            target_time="12:00 PM",
            bag_count=50,
            orders_using_2_washers=40,
            orders_using_2_dryers=10,
            washer_count=4,
            dryer_count=4,
            wash_cycle_min=30,
            dry_cycle_min=45,
            sort_min_per_bag=5,
            fold_min_per_bag=6,
            folder_count=3,
            sorter_count=1,
            weigher_count=1,
            washer_person_count=1,
            batch_size=8,
            helper_rule="none",
            washing_strategy="batch_washing",
        )

        def batch_two(result):
            rows = result["operational"]["decision_pack"]["batch_command_center"]
            return next(b for b in rows if b["batch_number"] == 2)

        base_b2 = batch_two(simulate_shift_capacity(payload))
        sorter_b2 = batch_two(
            simulate_shift_capacity(
                {
                    **payload,
                    "batch_overrides": [
                        {
                            "batch_number": 2,
                            "apply_scope": "from_this_batch",
                            "sorter_helps_washer": True,
                        }
                    ],
                }
            )
        )
        folder_b2 = batch_two(
            simulate_shift_capacity(
                {
                    **payload,
                    "batch_overrides": [
                        {
                            "batch_number": 2,
                            "apply_scope": "from_this_batch",
                            "extra_folders": 1,
                        }
                    ],
                }
            )
        )
        assert sorter_b2["batch_end"] != base_b2["batch_end"] or sorter_b2["wash_end"] != base_b2[
            "wash_end"
        ]
        assert folder_b2["fold_complete_at"] != base_b2["fold_complete_at"]

    def test_command_board_has_batch_and_resource_timelines(self):
        result = simulate_shift_capacity(
            _default_payload(
                start_time="7:00 AM",
                target_time="12:00 PM",
                bag_count=50,
                orders_using_2_washers=40,
                orders_using_2_dryers=10,
                washer_count=4,
                dryer_count=4,
                folder_count=3,
                sorter_count=1,
                weigher_count=1,
                washer_person_count=1,
                batch_size=8,
                washing_strategy="batch_washing",
            )
        )
        board = result["operational"]["command_board"]
        assert board["simulation_valid"] is True
        assert len(board["batch_timeline"]) >= 6
        assert board["summary"]["folded_by_target"] >= 1
        assert board["summary"]["bottleneck"] not in (None, "", "none")
        assert board["resource_timeline"]["cells"]["sorter"]

    def test_legacy_washing_strategy_aliases(self):
        batch = parse_planner_inputs({"washing_strategy": "hybrid_recommended"})
        assert batch.washing_strategy == "batch_washing"
        sort_drying = parse_planner_inputs({"washing_strategy": "continuous_washing"})
        assert sort_drying.washing_strategy == "sort_while_drying"

    def test_strategy_optimizer_prefers_batch_washing(self):
        result = simulate_shift_capacity(_default_payload())
        opt = result["operational"]["strategy_optimizer"]
        assert opt["washing_strategy"] == "batch_washing"
        assert opt["batch_size"] in (6, 8, 10, 12)
        assert "apply_inputs" in opt
        assert "expected_bags_folded_at_target" in opt
        assert "comparisons" in opt

    def test_order_timeline_bottleneck_field(self):
        result = simulate_shift_capacity(_default_payload(bag_count=20))
        row = result["operational"]["order_timeline"][0]
        assert "bottleneck" in row

    def test_load_dryer_completion_updates_order(self):
        inp = parse_planner_inputs(_default_payload(bag_count=8, orders_using_2_dryers=4))
        cont = run_operational_simulation(inp, washing_strategy="sort_while_drying")
        assert any(r["dry_start"] for r in cont["order_timeline"])
        assert cont["dryer_timeline"]
