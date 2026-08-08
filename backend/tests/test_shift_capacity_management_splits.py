"""Management-mode avg bag weight + deterministic 2-washer/2-dryer splits."""

from backend.shift_capacity.batch_builder import expand_bags
from backend.shift_capacity.service import run_shift_capacity
from backend.shift_capacity.split_loads import (
    DEFAULT_TWO_MACHINE_SPLIT_PCT,
    deterministic_two_machine_flags,
    parse_split_count,
    resolve_management_split_counts,
)
from backend.shift_capacity.timebase import parse_clock_seconds
from backend.shift_capacity.validation import parse_inputs


def _staffing(start="8:00 AM", end="5:00 PM"):
    return {
        "intervals": [
            {"role": role, "people": 2, "start": start, "end": end, "mode": "base"}
            for role in ("weigher", "sorter", "washer", "dryer", "folder")
        ]
    }


def _mgmt(**overrides):
    payload = {
        "engine": "bag_des_v2",
        "management_mode": True,
        "mode": "full_run",
        "start_time": "8:00 AM",
        "target_time": "3:00 PM",
        "end_time": "5:00 PM",
        "planning_block_size_min": 60,
        "bag_count": 50,
        "avg_lbs_per_bag": 20,
        "batch_size": 8,
        "washer_count": 4,
        "dryer_count": 4,
        "washer_capacity_lb": 80,
        "dryer_capacity_lb": 80,
        "wash_cycle_min": 30,
        "dry_cycle_min": 40,
        "sort_min_per_bag": 5,
        "load_washer_min": 3,
        "load_dryer_min": 3,
        "fold_rate_mode": "minutes_per_bag",
        "fold_min_per_bag": 6,
        "_skip_recommendations": True,
        "staffing_plan": _staffing(),
        "two_washer_split_pct": 0,
        "two_dryer_split_pct": 0,
    }
    payload.update(overrides)
    return payload


def test_parse_split_count_pct_and_bounds():
    assert parse_split_count(None, 80, bag_count=50, count_name="c", pct_name="p") == 40
    assert parse_split_count(None, 0, bag_count=50, count_name="c", pct_name="p") == 0
    assert parse_split_count(None, 100, bag_count=50, count_name="c", pct_name="p") == 50
    assert parse_split_count(None, 12.5, bag_count=50, count_name="c", pct_name="p") == 6
    try:
        parse_split_count(None, 101, bag_count=50, count_name="c", pct_name="p")
        assert False, "expected pct > 100 to fail"
    except ValueError as exc:
        assert "two_washer_split_pct" in str(exc) or "must be <= 100" in str(exc) or "p" in str(exc)


def test_deterministic_flags_first_n():
    flags = deterministic_two_machine_flags(50, 40)
    assert flags.count(True) == 40
    assert flags.count(False) == 10
    assert flags[:40] == [True] * 40
    assert flags[40:] == [False] * 10
    assert deterministic_two_machine_flags(50, 40) == flags


def test_default_management_split_is_validated_80_pct():
    wash_n, dry_n = resolve_management_split_counts({}, 50)
    assert wash_n == 40
    assert dry_n == 40
    assert DEFAULT_TWO_MACHINE_SPLIT_PCT == 80.0


def test_zero_percent_uses_single_machine_requirement():
    inp = parse_inputs(_mgmt(two_washer_split_pct=0, two_dryer_split_pct=0, bag_count=50))
    bags = expand_bags(inp)
    assert len(bags) == 50
    assert sum(1 for b in bags if b.requires_two_washers) == 0
    assert sum(1 for b in bags if b.requires_two_dryers) == 0
    result = run_shift_capacity(_mgmt(two_washer_split_pct=0, two_dryer_split_pct=0, bag_count=20))
    assert result["inputs"]["bag_count"] == 20
    assert result["inputs"]["bags_using_2_washers"] == 0
    assert all(not row["requires_two_washers"] for row in result["bag_rows"])


def test_hundred_percent_uses_double_machine_requirement():
    result = run_shift_capacity(
        _mgmt(
            bag_count=16,
            batch_size=8,
            two_washer_split_pct=100,
            two_dryer_split_pct=100,
            washer_count=4,
            dryer_count=4,
        )
    )
    assert len(result["bag_rows"]) == 16
    assert result["inputs"]["bags_using_2_washers"] == 16
    assert result["inputs"]["bags_using_2_dryers"] == 16
    assert all(row["requires_two_washers"] for row in result["bag_rows"])
    assert all(row["requires_two_dryers"] for row in result["bag_rows"])
    # Existing DES split: multi-bag batches with the flag occupy 2 washers (joined id).
    washers = {row["washer"] for row in result["bag_rows"] if row.get("washer")}
    assert any("+" in (w or "") for w in washers) or len(washers) >= 2


def test_intermediate_percent_assigns_exact_deterministic_count():
    result = run_shift_capacity(
        _mgmt(
            bag_count=50,
            two_washer_split_pct=80,
            two_dryer_split_pct=0,
        )
    )
    assert result["inputs"]["bag_count"] == 50
    assert result["inputs"]["bags_using_2_washers"] == 40
    assert result["inputs"]["bags_using_2_dryers"] == 0
    flagged = [row["requires_two_washers"] for row in result["bag_rows"]]
    assert flagged.count(True) == 40
    # Deterministic order: first 40 bag ids in expansion order are flagged.
    bags = expand_bags(parse_inputs(_mgmt(bag_count=50, two_washer_split_pct=80, two_dryer_split_pct=0)))
    assert [b.requires_two_washers for b in bags].count(True) == 40
    assert all(b.requires_two_washers for b in bags[:40])
    assert not any(b.requires_two_washers for b in bags[40:])


def test_washer_and_dryer_percentages_are_independent():
    result = run_shift_capacity(
        _mgmt(
            bag_count=50,
            two_washer_split_pct=80,
            two_dryer_split_pct=20,
        )
    )
    assert result["inputs"]["bags_using_2_washers"] == 40
    assert result["inputs"]["bags_using_2_dryers"] == 10
    wash_only = sum(
        1
        for row in result["bag_rows"]
        if row["requires_two_washers"] and not row["requires_two_dryers"]
    )
    dry_only = sum(
        1
        for row in result["bag_rows"]
        if row["requires_two_dryers"] and not row["requires_two_washers"]
    )
    both = sum(
        1
        for row in result["bag_rows"]
        if row["requires_two_washers"] and row["requires_two_dryers"]
    )
    assert both == 10
    assert wash_only == 30
    assert dry_only == 0


def test_target_bag_count_and_block_position_totals_unchanged():
    result = run_shift_capacity(
        _mgmt(
            bag_count=50,
            two_washer_split_pct=80,
            two_dryer_split_pct=80,
        )
    )
    assert len(result["bag_rows"]) == 50
    assert result["inputs"]["bag_count"] == 50
    assert result["management_outcome"]["target_bags"] == 50
    blocks = result["block_positions"]
    assert blocks
    last = blocks[-1]
    assert last["weighed_total"] <= 50
    assert last["sorted_total"] <= 50
    assert last["washed_total"] <= 50
    assert last["dried_total"] <= 50
    folded = last.get("folded_total", last.get("completed_total", 0))
    assert folded <= 50
    # No duplicated workflow bags: totals never exceed target.
    for block in blocks:
        assert block["weighed_total"] <= 50
        assert block["sorted_total"] <= 50
        assert (block.get("folded_total") or block.get("completed_total") or 0) <= 50


def test_machine_contention_increases_with_washer_split():
    low = run_shift_capacity(
        _mgmt(
            bag_count=24,
            batch_size=8,
            washer_count=2,
            dryer_count=2,
            two_washer_split_pct=0,
            two_dryer_split_pct=0,
        )
    )
    high = run_shift_capacity(
        _mgmt(
            bag_count=24,
            batch_size=8,
            washer_count=2,
            dryer_count=2,
            two_washer_split_pct=100,
            two_dryer_split_pct=0,
        )
    )
    assert low["inputs"]["bags_using_2_washers"] == 0
    assert high["inputs"]["bags_using_2_washers"] == 24

    def _last_wash_end(result):
        return max(
            parse_clock_seconds(row["wash_end"])
            for row in result["bag_rows"]
            if row.get("wash_end")
        )

    def _wash_interval_count(result):
        total = 0
        for machine in result.get("machine_timeline") or []:
            if not str(machine.get("resource_id") or "").startswith("W"):
                continue
            total += len(machine.get("intervals") or [])
        return total

    # 100% split: each batch occupies both washers (more wash bookings, later finish).
    assert _wash_interval_count(high) > _wash_interval_count(low)
    assert _last_wash_end(high) > _last_wash_end(low)


def test_avg_bag_weight_reaches_des_capacity_batching():
    light = run_shift_capacity(
        _mgmt(
            bag_count=12,
            avg_lbs_per_bag=20,
            washer_capacity_lb=80,
            batch_size=8,
            batch_limit_mode="whichever_first",
            two_washer_split_pct=0,
            two_dryer_split_pct=0,
        )
    )
    heavy = run_shift_capacity(
        _mgmt(
            bag_count=12,
            avg_lbs_per_bag=40,
            washer_capacity_lb=80,
            batch_size=8,
            batch_limit_mode="whichever_first",
            two_washer_split_pct=0,
            two_dryer_split_pct=0,
        )
    )
    assert light["inputs"]["avg_lbs_per_bag"] == 20
    assert heavy["inputs"]["avg_lbs_per_bag"] == 40
    light_batches = {row["batch"] for row in light["bag_rows"]}
    heavy_batches = {row["batch"] for row in heavy["bag_rows"]}
    # 20 lb → up to 4 bags/batch by capacity; 40 lb → up to 2 bags/batch → more batches.
    assert len(heavy_batches) > len(light_batches)


def test_avg_lbs_must_be_positive():
    try:
        parse_inputs(_mgmt(avg_lbs_per_bag=0))
        assert False, "expected avg_lbs_per_bag=0 to fail"
    except ValueError as exc:
        assert "avg_lbs_per_bag" in str(exc)
