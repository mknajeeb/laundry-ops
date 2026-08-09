"""Wash/Dry must be work-conserving at physical-load level (management mode)."""

from __future__ import annotations

from backend.shift_capacity.resources import ResourceCalendar
from backend.shift_capacity.service import run_shift_capacity
from backend.shift_capacity.timebase import parse_clock_seconds


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
        "wash_cycle_min": 25,
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


def _owner_5_to_6_intervals():
    return [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
        {"role": "washer", "people": 1, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
        {"role": "dryer", "people": 1, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
        {"role": "folder", "people": 0, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
    ]


def _labor_windows(result, employee_prefix: str, task_type: str, t0: int, t1: int):
    rows = []
    for emp in result.get("employee_timeline") or []:
        emp_id = str(emp.get("resource_id") or "")
        if not emp_id.startswith(employee_prefix):
            continue
        for res in emp.get("intervals") or []:
            if res.get("task") != task_type and res.get("task_type") != task_type:
                continue
            start = res.get("start_sec")
            end = res.get("end_sec")
            if start is None:
                start = parse_clock_seconds(res["start"])
            if end is None:
                end = parse_clock_seconds(res["end"])
            if end <= t0 or start >= t1:
                continue
            rows.append((max(start, t0), min(end, t1), emp_id, res))
    rows.sort()
    return rows


def _idle_seconds(windows, t0: int, t1: int) -> int:
    if not windows:
        return t1 - t0
    busy = 0
    cur_s, cur_e = windows[0][0], windows[0][1]
    for s, e, *_ in windows[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            busy += cur_e - cur_s
            cur_s, cur_e = s, e
    busy += cur_e - cur_s
    return max(0, (t1 - t0) - busy)


def test_split_wash_parent_two_3min_labor_reservations_and_worker_free_between():
    intervals = [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
        {"role": "sorter", "people": 2, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
        {"role": "washer", "people": 1, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
        {"role": "dryer", "people": 1, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
    ]
    result = run_shift_capacity(
        _payload(intervals, bag_count=1, batch_size=1, two_washer_split_pct=100, two_dryer_split_pct=0)
    )
    assert result["simulation_valid"] is True
    row = result["bag_rows"][0]
    assert row["requires_two_washers"] is True
    assert "+" in (row.get("washer") or "")
    washers = (row.get("washer") or "").split("+")
    assert len(washers) == 2
    assert washers[0] != washers[1]

    t0 = parse_clock_seconds("5:00 AM")
    t1 = parse_clock_seconds("8:00 AM")
    loads = _labor_windows(result, "MGMT_WASH", "washer_load", t0, t1)
    assert len(loads) == 2
    assert all(e - s == 3 * 60 for s, e, *_ in loads)
    # Worker free immediately after each 3-min reservation (contiguous, no cycle hold).
    assert loads[1][0] == loads[0][1]
    # Parent DONE waits for both child cycles.
    wash_end = parse_clock_seconds(row["wash_end"])
    load2_end = loads[1][1]
    assert wash_end == load2_end + 25 * 60


def test_split_dry_parent_two_3min_labor_reservations():
    intervals = [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
        {"role": "sorter", "people": 2, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
        {"role": "washer", "people": 1, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
        {"role": "dryer", "people": 1, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
    ]
    result = run_shift_capacity(
        _payload(intervals, bag_count=1, batch_size=1, two_washer_split_pct=0, two_dryer_split_pct=100)
    )
    assert result["simulation_valid"] is True
    row = result["bag_rows"][0]
    assert row["requires_two_dryers"] is True
    assert "+" in (row.get("dryer") or "")
    t0 = parse_clock_seconds("5:00 AM")
    t1 = parse_clock_seconds("8:00 AM")
    loads = _labor_windows(result, "MGMT_DRY", "dryer_load", t0, t1)
    assert len(loads) == 2
    assert all(e - s == 3 * 60 for s, e, *_ in loads)
    assert loads[1][0] == loads[0][1]
    ready = parse_clock_seconds(row["ready_to_fold"])
    assert ready == loads[1][1] + 40 * 60


def test_worker_starts_next_parent_while_earlier_machines_cycle():
    intervals = [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
        {"role": "sorter", "people": 4, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
        {"role": "washer", "people": 1, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
        {"role": "dryer", "people": 0, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
    ]
    result = run_shift_capacity(
        _payload(
            intervals,
            bag_count=4,
            batch_size=1,
            two_washer_split_pct=100,
            two_dryer_split_pct=0,
            sort_min_per_bag=1,
        )
    )
    assert result["simulation_valid"] is True
    rows = sorted(result["bag_rows"], key=lambda r: parse_clock_seconds(r["washer_load_start"]))
    # First parent uses two washers; second parent load starts while first cycles.
    assert "+" in (rows[0].get("washer") or "")
    p0_load_end = parse_clock_seconds(rows[0]["washer_load_end"])
    p0_wash_end = parse_clock_seconds(rows[0]["wash_end"])
    p1_load_start = parse_clock_seconds(rows[1]["washer_load_start"])
    assert p1_load_start == p0_load_end
    assert p1_load_start < p0_wash_end


def test_multiple_split_parents_concurrent_wash_and_dry_cycles():
    intervals = [
        {"role": "weigher", "people": 2, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
        {"role": "sorter", "people": 4, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
        {"role": "washer", "people": 1, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
        {"role": "dryer", "people": 1, "start": "5:00 AM", "end": "8:00 AM", "mode": "base"},
    ]
    result = run_shift_capacity(
        _payload(
            intervals,
            bag_count=6,
            batch_size=1,
            two_washer_split_pct=100,
            two_dryer_split_pct=100,
            sort_min_per_bag=1,
        )
    )
    assert result["simulation_valid"] is True
    t = parse_clock_seconds("5:55 AM")
    in_wash = 0
    in_dry = 0
    for row in result["bag_rows"]:
        ws = parse_clock_seconds(row["wash_start"]) if row.get("wash_start") else None
        we = parse_clock_seconds(row["wash_end"]) if row.get("wash_end") else None
        ds = parse_clock_seconds(row["dry_start"]) if row.get("dry_start") else None
        de = parse_clock_seconds(row["ready_to_fold"]) if row.get("ready_to_fold") else None
        if ws is not None and we is not None and ws <= t < we:
            in_wash += 1
        if ds is not None and de is not None and ds <= t < de:
            in_dry += 1
    assert in_wash >= 2
    assert in_dry >= 2


def test_owner_5_to_6_scenario_labor_not_machines_limits_and_no_avoidable_idle():
    result = run_shift_capacity(_payload(_owner_5_to_6_intervals(), bag_count=100))
    assert result["simulation_valid"] is True
    assert result["inputs"]["bag_count"] == 100

    t5 = parse_clock_seconds("5:00 AM")
    t6 = parse_clock_seconds("6:00 AM")
    b6 = next(b for b in result["block_positions"] if b["block_end"] == "6:00 AM")

    wash_starts = [
        r
        for r in result["bag_rows"]
        if r.get("washer_load_start") and t5 <= parse_clock_seconds(r["washer_load_start"]) < t6
    ]
    wash_done = [r for r in result["bag_rows"] if r.get("wash_end") and parse_clock_seconds(r["wash_end"]) <= t6]
    dry_starts = [
        r
        for r in result["bag_rows"]
        if r.get("dryer_load_start") and t5 <= parse_clock_seconds(r["dryer_load_start"]) < t6
    ]
    dry_done = [
        r for r in result["bag_rows"] if r.get("ready_to_fold") and parse_clock_seconds(r["ready_to_fold"]) <= t6
    ]

    assert len(wash_starts) >= 9  # ~11 theoretical; allow sort feed lag
    assert b6["washed_total"] == len(wash_done)
    assert b6.get("in_wash_cycle", 0) >= 1
    # Dry begins at first wash completion; dual parents are all-or-nothing (2×3 min).
    assert len(dry_starts) >= 3
    assert b6["dried_total"] == len(dry_done) == 0  # 40-min cycle
    assert b6.get("in_dry_cycle", 0) >= 3
    # Parent Dry DONE never exceeds fold pipeline with zero fold staff.
    assert b6["dried_total"] == (
        b6["waiting_to_fold"] + b6.get("in_fold_labor", 0) + b6["folded_total"]
    )

    wash_labor = _labor_windows(result, "MGMT_WASH", "washer_load", t5, t6)
    dry_labor = _labor_windows(result, "MGMT_DRY", "dryer_load", t5, t6)
    assert wash_labor
    assert dry_labor
    # Each reservation is exactly load labor (3 min), never cycle.
    assert all(e - s == 3 * 60 for s, e, *_ in wash_labor)
    assert all(e - s == 3 * 60 for s, e, *_ in dry_labor)

    wash_idle = _idle_seconds(wash_labor, t5, t6)
    dry_idle = _idle_seconds(dry_labor, t5, t6)
    # Sort feeds ~11 bags/hr; wash should stay busy after first sorted bag arrives.
    # Allow only the unavoidable pre-first-sort idle (~weigh+first sort).
    assert wash_idle <= 12 * 60
    # Dry waits until first parent wash completes (~load + wash cycle), then dual-packs.
    # Trailing <6 min cannot start another dual parent (all-or-nothing).
    assert dry_idle <= 45 * 60
    # After first dry load starts, dual packing continues while full parents fit.
    assert dry_labor[-1][1] >= t6 - 6 * 60

    # Machine count is not the limiter: many distinct washers/dryers used.
    wash_machines = {r.get("washer") for r in wash_starts if r.get("washer")}
    dry_machines = {r.get("dryer") for r in dry_starts if r.get("dryer")}
    assert len({p for w in wash_machines for p in str(w).split("+")}) >= 8
    assert len({p for d in dry_machines for p in str(d).split("+")}) >= 6

    recon = b6.get("reconciliation") or {}
    assert recon.get("ok") is True
    assert recon.get("exclusive_state_sum") == 100
    assert b6.get("in_wash_cycle", 0) == (b6.get("detail") or {}).get("in_wash_cycle", b6.get("in_wash_cycle", 0))
    assert b6.get("in_dry_cycle", 0) == (b6.get("detail") or {}).get("in_dry_cycle", b6.get("in_dry_cycle", 0))


def test_block_positions_reconciliation_holds_for_owner_scenario():
    result = run_shift_capacity(_payload(_owner_5_to_6_intervals(), bag_count=100))
    for block in result["block_positions"]:
        recon = block.get("reconciliation") or {}
        assert recon.get("ok") is True
        assert recon.get("exclusive_state_sum") == 100
        assert block.get("in_wash_cycle", 0) >= 0
        assert block.get("in_dry_cycle", 0) >= 0
