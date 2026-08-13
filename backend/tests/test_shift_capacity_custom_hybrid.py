"""Custom hybrid staffing: arbitrary role sets, N shared calendars, legacy normalize."""

from __future__ import annotations

from backend.shift_capacity.service import run_shift_capacity
from backend.shift_capacity.staffing_plan import (
    canonicalize_hybrid_roles,
    hybrid_identity,
    parse_and_compile_staffing_plan,
)
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


def _roles_hybrid(roles, people=1, start="9:00 AM", end="12:00 PM", mode="hybrid"):
    return {
        "mode": mode,
        "roles": roles,
        "people": people,
        "start_time": start,
        "end_time": end,
    }


def _timeline_for(result, resource_id):
    for row in result.get("employee_timeline") or []:
        if row.get("resource_id") == resource_id:
            return row.get("intervals") or []
    return []


def _assert_no_overlap(intervals):
    ordered = sorted(intervals, key=lambda r: (r["start_sec"], r["end_sec"]))
    for i in range(len(ordered) - 1):
        assert ordered[i]["end_sec"] <= ordered[i + 1]["start_sec"]


def test_arbitrary_two_role_hybrid_sort_fold():
    compiled = parse_and_compile_staffing_plan(
        {"intervals": [_roles_hybrid(["sorter", "folder"])]},
        plan_start_sec=parse_clock_seconds("9:00 AM"),
        plan_target_sec=parse_clock_seconds("12:00 PM"),
    )
    assert compiled.accepted
    assert len(compiled.employees) == 1
    emp = compiled.employees[0]
    assert emp.employee_id == "MGMT_HYBRID_SORT_FOLD_001"
    assert emp.primary_role == "sorter"
    assert emp.qualified_roles == ["folder"]


def test_arbitrary_three_role_hybrid_sort_wash_dry():
    compiled = parse_and_compile_staffing_plan(
        {"intervals": [_roles_hybrid(["sorter", "washer", "dryer"])]},
        plan_start_sec=parse_clock_seconds("9:00 AM"),
        plan_target_sec=parse_clock_seconds("12:00 PM"),
    )
    assert compiled.accepted
    emp = compiled.employees[0]
    assert emp.employee_id == "MGMT_HYBRID_SORT_WASH_DRY_001"
    assert emp.primary_role == "sorter"
    assert set(emp.qualified_roles) == {"washer", "dryer"}


def test_wash_dry_roles_payload_compiles_like_legacy():
    compiled = parse_and_compile_staffing_plan(
        {"intervals": [_roles_hybrid(["washer", "dryer"])]},
        plan_start_sec=parse_clock_seconds("9:00 AM"),
        plan_target_sec=parse_clock_seconds("12:00 PM"),
    )
    assert compiled.accepted
    emp = compiled.employees[0]
    assert emp.employee_id == "MGMT_HYBRID_WASH_DRY_001"
    assert emp.primary_role == "washer"
    assert emp.qualified_roles == ["dryer"]
    assert compiled.as_dict()["authored_intervals"][0]["hybrid"] == "wash_dry"


def test_two_hybrid_people_create_two_shared_resources():
    compiled = parse_and_compile_staffing_plan(
        {"intervals": [_roles_hybrid(["washer", "dryer"], people=2)]},
        plan_start_sec=parse_clock_seconds("9:00 AM"),
        plan_target_sec=parse_clock_seconds("12:00 PM"),
    )
    assert compiled.accepted
    ids = [e.employee_id for e in compiled.employees]
    assert ids == ["MGMT_HYBRID_WASH_DRY_001", "MGMT_HYBRID_WASH_DRY_002"]
    for emp in compiled.employees:
        assert emp.primary_role == "washer"
        assert emp.qualified_roles == ["dryer"]


def test_custom_hybrid_no_overlapping_labor_on_shared_calendar():
    intervals = _dedicated(weigher=1, sorter=1, folder=1) + [
        _roles_hybrid(["washer", "dryer"])
    ]
    result = run_shift_capacity(_plan(intervals, bag_count=6, batch_size=2))
    assert result["simulation_valid"] is True
    timeline = _timeline_for(result, "MGMT_HYBRID_WASH_DRY_001")
    assert timeline
    _assert_no_overlap(timeline)


def test_temp_hybrid_partial_slot_interval():
    intervals = _dedicated(weigher=1, sorter=1, folder=1) + [
        {
            "roles": ["washer", "dryer"],
            "people": 1,
            "start": "9:30 AM",
            "end": "10:00 AM",
            "mode": "additional",
        }
    ]
    compiled = parse_and_compile_staffing_plan(
        {"intervals": intervals},
        plan_start_sec=parse_clock_seconds("9:00 AM"),
        plan_target_sec=parse_clock_seconds("12:00 PM"),
    )
    assert compiled.accepted
    emp = next(e for e in compiled.employees if e.employee_id.startswith("MGMT_HYBRID_"))
    assert emp.employee_id == "MGMT_HYBRID_WASH_DRY_001"
    wins = emp.schedule_windows
    assert len(wins) == 1
    assert wins[0].start_min == parse_clock_seconds("9:30 AM")
    assert wins[0].end_min == parse_clock_seconds("10:00 AM")


def test_fewer_than_two_roles_rejected():
    compiled = parse_and_compile_staffing_plan(
        {"intervals": [_roles_hybrid(["washer"])]},
        plan_start_sec=parse_clock_seconds("9:00 AM"),
        plan_target_sec=parse_clock_seconds("12:00 PM"),
    )
    assert not compiled.accepted
    assert any(e.code == "STAFFING_HYBRID_INVALID" for e in compiled.errors)


def test_legacy_fixed_hybrid_payload_normalized():
    for legacy, roles in (
        ("weigh_wash", ("weigher", "washer")),
        ("wash_dry", ("washer", "dryer")),
        ("weigh_wash_dry", ("weigher", "washer", "dryer")),
    ):
        compiled = parse_and_compile_staffing_plan(
            {
                "intervals": [
                    {
                        "hybrid": legacy,
                        "people": 1,
                        "start": "9:00 AM",
                        "end": "12:00 PM",
                        "mode": "base",
                    }
                ]
            },
            plan_start_sec=parse_clock_seconds("9:00 AM"),
            plan_target_sec=parse_clock_seconds("12:00 PM"),
        )
        assert compiled.accepted, compiled.errors
        authored = compiled.as_dict()["authored_intervals"][0]
        assert authored["hybrid"] == legacy
        assert tuple(authored["roles"]) == roles
        emp = compiled.employees[0]
        assert emp.primary_role == roles[0]
        assert emp.qualified_roles == list(roles[1:])


def test_role_allocation_minutes_reconcile_for_custom_hybrid():
    intervals = _dedicated(weigher=1, sorter=1, folder=1) + [
        _roles_hybrid(["washer", "dryer"])
    ]
    result = run_shift_capacity(_plan(intervals, bag_count=6, batch_size=2))
    rows = [
        r
        for r in (result.get("work_coverage") or [])
        if r.get("hybrid") == "wash_dry"
    ]
    assert rows
    row = rows[0]
    alloc = row["role_allocation_min"]
    used_roles = float(alloc.get("washer", 0)) + float(alloc.get("dryer", 0))
    assert abs(used_roles + float(alloc.get("idle", 0)) - row["staff_min"]) < 0.25
    assert set(row.get("roles") or []) == {"washer", "dryer"}


def test_canonicalize_orders_workflow_and_identity_matches_legacy():
    roles = canonicalize_hybrid_roles(["dryer", "washer", "washer"])
    assert roles == ("washer", "dryer")
    key, prefix = hybrid_identity(roles)
    assert key == "wash_dry"
    assert prefix == "MGMT_HYBRID_WASH_DRY"


def test_sort_fold_hybrid_runs_both_roles():
    intervals = _dedicated(weigher=1, washer=1, dryer=1) + [
        _roles_hybrid(["sorter", "folder"])
    ]
    result = run_shift_capacity(_plan(intervals, bag_count=4, batch_size=2))
    emp = "MGMT_HYBRID_SORT_FOLD_001"
    assert any(r.get("sorted_by_employee_id") == emp for r in result["bag_rows"])
    assert any(r.get("folded_by_employee_id") == emp for r in result["bag_rows"])
    _assert_no_overlap(_timeline_for(result, emp))
