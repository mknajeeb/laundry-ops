"""Hybrid staffing: one shared multi-role calendar, no authored switch times."""

from __future__ import annotations

from backend.shift_capacity.service import run_shift_capacity
from backend.shift_capacity.staffing_plan import parse_and_compile_staffing_plan
from backend.shift_capacity.timebase import parse_clock_seconds


def _plan(intervals, **overrides):
    payload = {
        "engine": "bag_des_v2",
        "management_mode": True,
        "mode": "full_run",
        "start_time": "9:00 AM",
        "target_time": "12:00 PM",
        "end_time": "12:00 PM",
        "planning_block_size_min": 60,
        "bag_count": 8,
        "batch_size": 2,
        "washer_count": 4,
        "dryer_count": 4,
        "weigh_sec_per_bag": 45,
        "sort_min_per_bag": 5,
        "load_washer_min": 3,
        "wash_cycle_min": 25,
        "load_dryer_min": 3,
        "dry_cycle_min": 40,
        "fold_min_per_bag": 6,
        "fold_rate_mode": "minutes_per_bag",
        "two_washer_split_pct": 0,
        "two_dryer_split_pct": 0,
        "_skip_recommendations": True,
        "staffing_plan": {"intervals": intervals},
    }
    payload.update(overrides)
    return payload


def _dedicated(**counts):
    start, end = "9:00 AM", "12:00 PM"
    return [
        {"role": role, "people": n, "start": start, "end": end, "mode": "base"}
        for role, n in counts.items()
        if n > 0
    ]


def _hybrid(hybrid_type, people=1, start="9:00 AM", end="12:00 PM"):
    return {
        "hybrid": hybrid_type,
        "people": people,
        "start": start,
        "end": end,
        "mode": "base",
    }


def _timeline_for(result, resource_id):
    for row in result.get("employee_timeline") or []:
        if row.get("resource_id") == resource_id:
            return row.get("intervals") or []
    return []


def _assert_no_overlap(intervals):
    ordered = sorted(intervals, key=lambda r: (r["start_sec"], r["end_sec"]))
    for i in range(len(ordered) - 1):
        assert ordered[i]["end_sec"] <= ordered[i + 1]["start_sec"], (
            f"overlapping labor on shared calendar: {ordered[i]} vs {ordered[i + 1]}"
        )


def test_weigh_wash_hybrid_compiles_to_one_resource():
    compiled = parse_and_compile_staffing_plan(
        {"intervals": [_hybrid("weigh_wash")]},
        plan_start_sec=parse_clock_seconds("9:00 AM"),
        plan_target_sec=parse_clock_seconds("12:00 PM"),
    )
    assert compiled.accepted
    assert len(compiled.employees) == 1
    emp = compiled.employees[0]
    assert emp.employee_id == "MGMT_HYBRID_WEIGH_WASH_001"
    assert emp.primary_role == "weigher"
    assert emp.qualified_roles == ["washer"]
    # Must not inflate dedicated role headcount.
    assert compiled.normalized_intervals == []


def test_weigh_wash_hybrid_performs_both_roles_without_overlap():
    intervals = _dedicated(sorter=1, dryer=1, folder=1) + [_hybrid("weigh_wash")]
    result = run_shift_capacity(_plan(intervals, bag_count=6, batch_size=2))
    assert result["simulation_valid"] is True

    compiled = result["staffing_plan"]["compiled_resources"]
    hybrid_ids = [c["id"] for c in compiled if c["id"].startswith("MGMT_HYBRID_WEIGH_WASH")]
    assert hybrid_ids == ["MGMT_HYBRID_WEIGH_WASH_001"]
    assert not any(c["id"].startswith("MGMT_WEIGH_") for c in compiled)
    assert not any(c["id"].startswith("MGMT_WASH_") for c in compiled)

    weighed_by = {r["weighed_by_employee_id"] for r in result["bag_rows"] if r.get("weigh_end")}
    washed_by = {
        r["washer_loaded_by_employee_id"] for r in result["bag_rows"] if r.get("washer_load_start")
    }
    assert weighed_by == {"MGMT_HYBRID_WEIGH_WASH_001"}
    assert washed_by == {"MGMT_HYBRID_WEIGH_WASH_001"}
    assert any(r.get("weigh_end") for r in result["bag_rows"])
    assert any(r.get("washer_load_start") for r in result["bag_rows"])

    timeline = _timeline_for(result, "MGMT_HYBRID_WEIGH_WASH_001")
    assert timeline
    tasks = {iv["task"] for iv in timeline}
    assert "weigh" in tasks
    assert "washer_load" in tasks or "wash" in tasks
    _assert_no_overlap(timeline)


def _max_concurrent_tasks(result, task_types):
    """Peak overlapping labor reservations across all employees for given tasks."""
    events = []
    for tl in result.get("employee_timeline") or []:
        for iv in tl.get("intervals") or []:
            if iv.get("task") not in task_types:
                continue
            events.append((iv["start_sec"], 1))
            events.append((iv["end_sec"], -1))
    events.sort(key=lambda x: (x[0], x[1]))
    cur = peak = 0
    for _, delta in events:
        cur += delta
        peak = max(peak, cur)
    return peak


def test_weigh_wash_hybrid_is_not_independent_dual_capacity():
    """1 hybrid ≠ 1 weigher + 1 washer: cannot run both roles at once."""
    hybrid_intervals = _dedicated(sorter=2, dryer=1, folder=1) + [_hybrid("weigh_wash")]
    dedicated_intervals = _dedicated(weigher=1, sorter=2, washer=1, dryer=1, folder=1)

    hybrid_result = run_shift_capacity(_plan(hybrid_intervals, bag_count=12, batch_size=2))
    dedicated_result = run_shift_capacity(_plan(dedicated_intervals, bag_count=12, batch_size=2))

    labor_tasks = {"weigh", "washer_load"}
    assert _max_concurrent_tasks(hybrid_result, labor_tasks) == 1
    assert _max_concurrent_tasks(dedicated_result, labor_tasks) >= 2

    timeline = _timeline_for(hybrid_result, "MGMT_HYBRID_WEIGH_WASH_001")
    _assert_no_overlap(timeline)
    # Compile identity: one shared slot, not MGMT_WEIGH + MGMT_WASH.
    ids = [c["id"] for c in hybrid_result["staffing_plan"]["compiled_resources"]]
    assert "MGMT_HYBRID_WEIGH_WASH_001" in ids
    assert not any(i.startswith("MGMT_WEIGH_") for i in ids)
    assert not any(i.startswith("MGMT_WASH_") for i in ids)


def test_wash_dry_hybrid_shared_calendar():
    intervals = _dedicated(weigher=1, sorter=1, folder=1) + [_hybrid("wash_dry")]
    result = run_shift_capacity(_plan(intervals, bag_count=6, batch_size=2))
    compiled = result["staffing_plan"]["compiled_resources"]
    assert any(c["id"] == "MGMT_HYBRID_WASH_DRY_001" for c in compiled)
    hybrid = next(c for c in compiled if c["id"] == "MGMT_HYBRID_WASH_DRY_001")
    assert hybrid["qualified_roles"] == ["dryer"]
    assert hybrid["role"] == "washer"

    washed = {
        r["washer_loaded_by_employee_id"] for r in result["bag_rows"] if r.get("washer_load_start")
    }
    dried = {
        r["dryer_loaded_by_employee_id"] for r in result["bag_rows"] if r.get("dryer_load_start")
    }
    assert "MGMT_HYBRID_WASH_DRY_001" in washed
    assert "MGMT_HYBRID_WASH_DRY_001" in dried
    _assert_no_overlap(_timeline_for(result, "MGMT_HYBRID_WASH_DRY_001"))


def test_weigh_wash_dry_hybrid_one_shared_resource():
    intervals = _dedicated(sorter=1, folder=1) + [_hybrid("weigh_wash_dry")]
    result = run_shift_capacity(_plan(intervals, bag_count=4, batch_size=2))
    compiled = result["staffing_plan"]["compiled_resources"]
    hybrid_ids = [c["id"] for c in compiled if "HYBRID" in c["id"]]
    assert hybrid_ids == ["MGMT_HYBRID_WEIGH_WASH_DRY_001"]
    hybrid = compiled[next(i for i, c in enumerate(compiled) if c["id"] == hybrid_ids[0])]
    assert set(hybrid["qualified_roles"]) == {"washer", "dryer"}
    assert hybrid["role"] == "weigher"

    emp = "MGMT_HYBRID_WEIGH_WASH_DRY_001"
    assert any(r.get("weighed_by_employee_id") == emp for r in result["bag_rows"])
    assert any(r.get("washer_loaded_by_employee_id") == emp for r in result["bag_rows"])
    assert any(r.get("dryer_loaded_by_employee_id") == emp for r in result["bag_rows"])
    _assert_no_overlap(_timeline_for(result, emp))


def test_dedicated_plus_hybrid_combine_correctly():
    intervals = _dedicated(weigher=1, sorter=1, washer=1, dryer=1, folder=1) + [
        _hybrid("weigh_wash")
    ]
    result = run_shift_capacity(_plan(intervals, bag_count=8, batch_size=2))
    compiled = {c["id"]: c for c in result["staffing_plan"]["compiled_resources"]}
    assert "MGMT_WEIGH_001" in compiled
    assert "MGMT_WASH_001" in compiled
    assert "MGMT_HYBRID_WEIGH_WASH_001" in compiled

    weighed = {r["weighed_by_employee_id"] for r in result["bag_rows"] if r.get("weigh_end")}
    # Dedicated and/or hybrid may weigh; both are legal capacity.
    assert weighed <= {"MGMT_WEIGH_001", "MGMT_HYBRID_WEIGH_WASH_001"}
    assert weighed  # someone weighed
    _assert_no_overlap(_timeline_for(result, "MGMT_HYBRID_WEIGH_WASH_001"))


def test_hybrid_cannot_perform_sort_or_fold():
    # Only weigh/wash hybrid — no sorter/folder dedicated.
    result = run_shift_capacity(_plan([_hybrid("weigh_wash")], bag_count=4, batch_size=2))
    compiled = result["staffing_plan"]["compiled_resources"]
    assert [c["id"] for c in compiled] == ["MGMT_HYBRID_WEIGH_WASH_001"]

    assert any(r.get("weigh_end") for r in result["bag_rows"])
    assert all(r.get("sort_end") is None for r in result["bag_rows"])
    assert all(r.get("fold_end") is None for r in result["bag_rows"])
    assert all(r.get("sorted_by_employee_id") in (None, "Unassigned") for r in result["bag_rows"])
    assert all(r.get("folded_by_employee_id") in (None, "Unassigned") for r in result["bag_rows"])

    timeline = _timeline_for(result, "MGMT_HYBRID_WEIGH_WASH_001")
    assert all(iv["task"] not in ("sort", "fold") for iv in timeline)


def test_machines_remain_separate_from_hybrid_labor():
    """Hybrid is employee labor; wash/dry still require machine calendars."""
    intervals = _dedicated(sorter=1, dryer=1, folder=1) + [_hybrid("weigh_wash")]
    result = run_shift_capacity(_plan(intervals, bag_count=4, batch_size=2, washer_count=2))
    assert result["simulation_valid"] is True
    hybrid_id = "MGMT_HYBRID_WEIGH_WASH_001"
    emp_ids = {tl["resource_id"] for tl in result.get("employee_timeline") or []}
    machine_ids = {tl["resource_id"] for tl in result.get("machine_timeline") or []}
    assert hybrid_id in emp_ids
    assert hybrid_id not in machine_ids
    assert any(mid.startswith("W") for mid in machine_ids)
    # Wash cycle time is on machines, not on the hybrid person calendar.
    hybrid_tasks = {iv["task"] for iv in _timeline_for(result, hybrid_id)}
    assert "wash_cycle" not in hybrid_tasks
    machine_tasks = {
        iv["task"]
        for tl in result.get("machine_timeline") or []
        for iv in tl.get("intervals") or []
    }
    assert any("wash" in t for t in machine_tasks)


def test_no_synthetic_labor_with_hybrid_only_upstream():
    result = run_shift_capacity(_plan([_hybrid("weigh_wash")], bag_count=4))
    ids = [c["id"] for c in result["staffing_plan"]["compiled_resources"]]
    assert ids == ["MGMT_HYBRID_WEIGH_WASH_001"]
    assert not any(i.startswith("__") for i in ids)
    for row in result["bag_rows"]:
        for key in (
            "weighed_by_employee_id",
            "sorted_by_employee_id",
            "washer_loaded_by_employee_id",
            "folded_by_employee_id",
        ):
            val = row.get(key)
            if val and val != "Unassigned":
                assert not str(val).startswith("__")


def test_block_positions_reconcile_with_bag_timestamps():
    intervals = _dedicated(sorter=1, dryer=1, folder=1) + [_hybrid("weigh_wash")]
    result = run_shift_capacity(_plan(intervals, bag_count=6, batch_size=2))
    for block in result["block_positions"]:
        t0 = parse_clock_seconds(block["block_start"])
        t1 = parse_clock_seconds(block["block_end"])
        weighed = sum(
            1
            for r in result["bag_rows"]
            if r.get("weigh_end") and t0 < parse_clock_seconds(r["weigh_end"]) <= t1
        )
        washed = sum(
            1
            for r in result["bag_rows"]
            if r.get("wash_end") and t0 < parse_clock_seconds(r["wash_end"]) <= t1
        )
        assert block["weighed_this_block"] == weighed
        assert block["washed_this_block"] == washed


def test_block_staffing_view_exposes_hybrids_not_dedicated_roles():
    intervals = _dedicated(sorter=1) + [_hybrid("weigh_wash")]
    result = run_shift_capacity(_plan(intervals, bag_count=2, batch_size=2))
    block = result["block_positions"][0]
    staffing = block["staffing"]
    assert staffing["roles"]["weigher"]["people_at_block_start"] == 0
    assert staffing["roles"]["washer"]["people_at_block_start"] == 0
    assert staffing["hybrids"]["weigh_wash"]["people_at_block_start"] == 1
    assert staffing["hybrids"]["weigh_wash"]["qualified_roles"] == ["weigher", "washer"]


def test_hybrid_scenario_is_deterministic():
    intervals = _dedicated(sorter=1, dryer=1, folder=1) + [_hybrid("weigh_wash")]
    payload = _plan(intervals, bag_count=8, batch_size=2)
    a = run_shift_capacity(payload)
    b = run_shift_capacity(payload)

    def fingerprint(result):
        return [
            (
                r.get("bag_id"),
                r.get("weigh_start"),
                r.get("weigh_end"),
                r.get("weighed_by_employee_id"),
                r.get("sort_start"),
                r.get("sort_end"),
                r.get("washer_load_start"),
                r.get("washer_loaded_by_employee_id"),
                r.get("wash_end"),
                r.get("dryer_load_start"),
                r.get("fold_end"),
            )
            for r in result["bag_rows"]
        ]

    assert fingerprint(a) == fingerprint(b)
    assert a["block_positions"] == b["block_positions"]
