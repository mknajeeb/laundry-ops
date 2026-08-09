"""Hard parent-bag stage reconciliation at every planning-block boundary."""

from __future__ import annotations

from collections import defaultdict

from backend.shift_capacity.block_positions import parent_dry_complete, parent_wash_complete
from backend.shift_capacity.scheduler import run_scheduler
from backend.shift_capacity.service import run_shift_capacity
from backend.shift_capacity.timebase import parse_clock_seconds
from backend.shift_capacity.validation import parse_inputs


def _payload(intervals, **overrides):
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
        "dryer_count": 24,
        "weigh_sec_per_bag": 45,
        "sort_min_per_bag": 5,
        "load_washer_min": 3,
        "wash_cycle_min": 30,
        "load_dryer_min": 3,
        "dry_cycle_min": 40,
        "fold_min_per_bag": 30,
        "fold_rate_mode": "minutes_per_bag",
        "two_washer_split_pct": 80,
        "two_dryer_split_pct": 80,
        "_skip_recommendations": True,
        "staffing_plan": {"intervals": intervals},
    }
    payload.update(overrides)
    return payload


def _screenshot_style_intervals():
    return [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "9:00 AM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "5:00 AM", "end": "9:00 AM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "6:00 AM", "end": "6:45 AM", "mode": "additional"},
        {"role": "washer", "people": 1, "start": "5:00 AM", "end": "9:00 AM", "mode": "base"},
        {"role": "dryer", "people": 1, "start": "6:45 AM", "end": "9:00 AM", "mode": "additional"},
        # Fold staff = 0
    ]


def _assert_stage_equations(block: dict) -> None:
    """Parent-bag conservation at one checkpoint."""
    weigh = block["weighed_total"]
    sort = block["sorted_total"]
    wash = block["washed_total"]
    dry = block["dried_total"]
    fold = block["folded_total"]

    assert weigh == (
        block["waiting_to_sort"] + block.get("in_sort_labor", 0) + sort
    ), (
        f"{block['block_end']} WEIGH DONE: {weigh} != "
        f"{block['waiting_to_sort']}+{block.get('in_sort_labor', 0)}+{sort}"
    )
    assert sort == (
        block["waiting_to_wash"]
        + block.get("in_wash_labor", 0)
        + block.get("in_wash_cycle", 0)
        + wash
    ), (
        f"{block['block_end']} SORT DONE: {sort} != "
        f"wait_wash+labor+cycle+wash"
    )
    assert wash == (
        block["waiting_to_dry"]
        + block.get("in_dry_labor", 0)
        + block.get("in_dry_cycle", 0)
        + dry
    ), (
        f"{block['block_end']} WASH DONE: {wash} != "
        f"wait_dry+labor+cycle+dry ({block['waiting_to_dry']}+"
        f"{block.get('in_dry_labor', 0)}+{block.get('in_dry_cycle', 0)}+{dry})"
    )
    assert dry == (
        block["waiting_to_fold"] + block.get("in_fold_labor", 0) + fold
    ), (
        f"{block['block_end']} DRY DONE: {dry} != "
        f"{block['waiting_to_fold']}+{block.get('in_fold_labor', 0)}+{fold}"
    )


def test_stage_equations_hold_at_every_block_boundary():
    result = run_shift_capacity(_payload(_screenshot_style_intervals()))
    assert result["block_positions"]
    for block in result["block_positions"]:
        _assert_stage_equations(block)
        assert (block.get("reconciliation") or {}).get("ok") is True


def test_dry_done_equals_waiting_to_fold_when_fold_staff_zero():
    result = run_shift_capacity(_payload(_screenshot_style_intervals()))
    b8 = next(b for b in result["block_positions"] if b["block_end"] == "8:00 AM")
    assert b8["folded_total"] == 0
    assert b8.get("in_fold_labor", 0) == 0
    assert b8["dried_total"] == b8["waiting_to_fold"]
    # Production-like: if Dry DONE is positive with no fold staff, wait must match.
    if b8["dried_total"] >= 1:
        assert b8["waiting_to_fold"] == b8["dried_total"]


def test_ready_to_fold_requires_all_dryer_child_loads():
    """Partial dual dry must never mark parent Dry DONE / ready_to_fold."""
    intervals = [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "9:00 AM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "5:00 AM", "end": "9:00 AM", "mode": "base"},
        {"role": "washer", "people": 1, "start": "5:00 AM", "end": "9:00 AM", "mode": "base"},
        # Short Dry window forces leftover minutes that cannot fit a 2nd load.
        {"role": "dryer", "people": 1, "start": "6:45 AM", "end": "7:00 AM", "mode": "additional"},
    ]
    state = run_scheduler(
        parse_inputs(
            _payload(intervals, two_dryer_split_pct=100, _skip_recommendations=True)
        )
    )
    dry_loads: dict[str, int] = defaultdict(int)
    for rows in state.employee_calendars.values():
        for r in rows:
            if r.task_type == "dryer_load":
                for bid in r.bag_ids or []:
                    dry_loads[bid] += 1

    for bag in state.bags:
        if bag.requires_two_dryers and dry_loads.get(bag.bag_id, 0) == 1:
            assert bag.ready_to_fold is None, (
                f"{bag.bag_id} has ready_to_fold after only one dryer load"
            )
            assert not parent_dry_complete(bag, parse_clock_seconds("8:00 AM"))

    result = run_shift_capacity(
        _payload(intervals, two_dryer_split_pct=100)
    )
    for block in result["block_positions"]:
        _assert_stage_equations(block)


def test_wash_done_requires_all_washer_child_loads():
    intervals = [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
        {"role": "washer", "people": 1, "start": "5:00 AM", "end": "5:15 AM", "mode": "base"},
    ]
    state = run_scheduler(
        parse_inputs(
            _payload(intervals, two_washer_split_pct=100, bag_count=40, _skip_recommendations=True)
        )
    )
    wash_loads: dict[str, int] = defaultdict(int)
    for rows in state.employee_calendars.values():
        for r in rows:
            if r.task_type == "washer_load":
                for bid in r.bag_ids or []:
                    wash_loads[bid] += 1
    t = parse_clock_seconds("8:00 AM")
    for bag in state.bags:
        if bag.requires_two_washers and wash_loads.get(bag.bag_id, 0) == 1:
            assert bag.wash_end is None
            assert not parent_wash_complete(bag, t)


def test_seven_and_eight_am_equations_for_current_scenario():
    result = run_shift_capacity(_payload(_screenshot_style_intervals()))
    for end in ("7:00 AM", "8:00 AM"):
        block = next(b for b in result["block_positions"] if b["block_end"] == end)
        _assert_stage_equations(block)
        print(
            end,
            {
                "weigh": block["weighed_total"],
                "sort": block["sorted_total"],
                "wash": block["washed_total"],
                "dry": block["dried_total"],
                "wait_fold": block["waiting_to_fold"],
                "fold": block["folded_total"],
                "in_dry_cycle": block.get("in_dry_cycle"),
                "wait_dry": block["waiting_to_dry"],
            },
        )
