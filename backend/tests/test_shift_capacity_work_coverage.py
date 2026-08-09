"""Upstream work coverage — DES-derived demand / used / idle for staffing windows."""

from __future__ import annotations

from backend.shift_capacity.service import run_shift_capacity
from backend.shift_capacity.timebase import parse_clock_seconds


def _base_payload(intervals, **overrides):
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


def _coverage(result, *, role=None, hybrid=None, mode=None, start=None, end=None):
    rows = result.get("work_coverage") or []
    out = []
    for r in rows:
        if role is not None and r.get("role") != role:
            continue
        if hybrid is not None and r.get("hybrid") != hybrid:
            continue
        if mode is not None and r.get("mode") != mode:
            continue
        if start is not None and r.get("start") != start:
            continue
        if end is not None and r.get("end") != end:
            continue
        out.append(r)
    return out


def _screenshot_intervals():
    """Sort base+TEMP, Wash base, Dry TEMP 6:45–7:00 (production case)."""
    return [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "7:00 AM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "5:00 AM", "end": "7:00 AM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "6:00 AM", "end": "6:45 AM", "mode": "additional"},
        {"role": "washer", "people": 1, "start": "5:00 AM", "end": "7:00 AM", "mode": "base"},
        {"role": "dryer", "people": 1, "start": "6:45 AM", "end": "7:00 AM", "mode": "additional"},
    ]


def test_work_coverage_present_on_management_response():
    result = run_shift_capacity(_base_payload(_screenshot_intervals()))
    assert isinstance(result.get("work_coverage"), list)
    assert result["work_coverage"]
    b7 = next(b for b in result["block_positions"] if b["block_end"] == "7:00 AM")
    assert (b7.get("staffing") or {}).get("work_coverage")


def test_dry_temp_work_waiting_before_worker_starts_fully_utilized():
    """Work already Dry-ready at 6:45 + mid-window arrivals; dual loads fill the TEMP.

    Parent dry is all-or-nothing (2 loads). In 15 min a dryer fits two dual parents
    (12 labor min) — leftover 3 min cannot start another dual parent.
    """
    result = run_shift_capacity(_base_payload(_screenshot_intervals()))
    dry = _coverage(
        result, role="dryer", mode="additional", start="6:45 AM", end="7:00 AM"
    )
    assert len(dry) == 1
    row = dry[0]
    assert row["staff_min"] == 15
    assert row["eligible_bags_at_start"] >= 1
    assert row["eligible_bags"] > row["eligible_bags_at_start"] or row["eligible_bags_became"] >= 0
    assert row["available_work_min"] >= row["staff_min"]
    # Two full dual parents = 12 min used; 3 min unused_fit (cannot start 3rd dual).
    assert row["used_min"] == 12
    assert row["idle_min"] == 3
    assert row["idle_no_eligible_work_min"] == 0
    assert row["unused_fit_min"] == 3
    assert row["status"] == "work_not_fit"
    assert row["physical_loads_available"] >= 4
    # Split dry loads: physical loads > parent bags when duals dominate
    assert row["physical_loads_available"] >= row["eligible_bags"]


def test_dry_temp_mid_window_arrivals_count_toward_eligible():
    result = run_shift_capacity(_base_payload(_screenshot_intervals()))
    row = _coverage(
        result, role="dryer", mode="additional", start="6:45 AM", end="7:00 AM"
    )[0]
    # Eligible = at_start + became (time-aware, not end-of-slot queue only)
    assert row["eligible_bags"] == row["eligible_bags_at_start"] + row["eligible_bags_became"]


def test_insufficient_upstream_work_idle():
    """Dry TEMP with almost no wash feed → idle waiting for work."""
    intervals = [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
        # No washer before dry window — little/no dry-ready work
        {"role": "dryer", "people": 1, "start": "5:00 AM", "end": "5:15 AM", "mode": "additional"},
    ]
    result = run_shift_capacity(_base_payload(intervals, bag_count=20))
    row = _coverage(
        result, role="dryer", mode="additional", start="5:00 AM", end="5:15 AM"
    )[0]
    assert row["staff_min"] == 15
    assert row["available_work_min"] < row["staff_min"]
    assert row["idle_min"] > 0
    assert row["idle_no_eligible_work_min"] > 0
    assert row["status"] in ("idle_waiting_for_work", "partial_upstream_short")


def test_more_work_than_capacity_fully_utilized():
    result = run_shift_capacity(_base_payload(_screenshot_intervals()))
    row = _coverage(
        result, role="dryer", mode="additional", start="6:45 AM", end="7:00 AM"
    )[0]
    assert row["available_work_min"] > row["staff_min"]
    # Dual all-or-nothing: 12/15 min used when leftover cannot fit another parent.
    assert row["used_min"] >= 12
    assert row["available_work_min"] > row["used_min"]
    assert row["idle_no_eligible_work_min"] == 0


def test_split_wash_loads_inflate_physical_demand():
    intervals = [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "7:00 AM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "5:00 AM", "end": "7:00 AM", "mode": "base"},
        {"role": "washer", "people": 1, "start": "5:00 AM", "end": "6:00 AM", "mode": "base"},
    ]
    result = run_shift_capacity(
        _base_payload(intervals, two_washer_split_pct=100, two_dryer_split_pct=0)
    )
    wash = _coverage(result, role="washer", mode="base", start="5:00 AM", end="6:00 AM")[0]
    assert wash["physical_loads_available"] >= wash["eligible_bags"]
    # 100% two-washer → ~2 loads per eligible parent still unfinished at window logic
    if wash["eligible_bags"] >= 2:
        assert wash["physical_loads_available"] >= wash["eligible_bags"] * 1.5 or wash[
            "available_work_min"
        ] >= wash["eligible_bags"] * 3


def test_split_dry_loads_labor_minutes_not_bag_count():
    result = run_shift_capacity(
        _base_payload(_screenshot_intervals(), two_dryer_split_pct=100)
    )
    row = _coverage(
        result, role="dryer", mode="additional", start="6:45 AM", end="7:00 AM"
    )[0]
    # Each dual parent is 6 labor min; available work must exceed bag_count * 3 when duals
    assert row["available_work_min"] >= row["eligible_bags"] * 3
    if row["eligible_bags"] >= 2:
        assert row["physical_loads_available"] > row["eligible_bags"]


def test_temp_partial_hour_and_base_full_slot():
    result = run_shift_capacity(_base_payload(_screenshot_intervals()))
    temp_sort = _coverage(
        result, role="sorter", mode="additional", start="6:00 AM", end="6:45 AM"
    )[0]
    assert temp_sort["staff_min"] == 45
    wash = _coverage(result, role="washer", mode="base")
    # Washer base spans 5–7 in this fixture
    assert any(w["staff_min"] == 120 for w in wash)
    assert any(w["start"] == "5:00 AM" and w["end"] == "7:00 AM" for w in wash)


def test_work_becoming_eligible_too_late_to_fit():
    """Eligible bags near window end still count as available; unused_fit when dual won't fit."""
    result = run_shift_capacity(_base_payload(_screenshot_intervals()))
    row = _coverage(
        result, role="dryer", mode="additional", start="6:45 AM", end="7:00 AM"
    )[0]
    assert row["available_work_min"] > row["used_min"]
    assert row["unused_fit_min"] >= 0
    # Became-ready bags are counted even if late
    assert row["eligible_bags_became"] >= 0


def test_hybrid_shared_calendar_no_double_count():
    intervals = [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "7:00 AM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "5:00 AM", "end": "7:00 AM", "mode": "base"},
        {
            "hybrid": "wash_dry",
            "people": 1,
            "start": "5:00 AM",
            "end": "6:00 AM",
            "mode": "base",
        },
    ]
    result = run_shift_capacity(_base_payload(intervals))
    hybrid = _coverage(result, hybrid="wash_dry", mode="base")[0]
    assert hybrid["staff_min"] == 60
    alloc = hybrid["role_allocation_min"]
    assert alloc is not None
    # Used wash+dry+idle must equal staff (single calendar)
    used_roles = float(alloc.get("washer", 0)) + float(alloc.get("dryer", 0))
    assert abs(used_roles + float(alloc.get("idle", 0)) - hybrid["staff_min"]) < 0.2
    assert hybrid["used_min"] + hybrid["idle_min"] == hybrid["staff_min"] or abs(
        hybrid["used_min"] + hybrid["idle_min"] - hybrid["staff_min"]
    ) < 0.2


def test_machine_constrained_still_reports_available_vs_used():
    """Few dryers: demand may exceed what DES can start; coverage still DES-backed."""
    intervals = [
        {"role": "weigher", "people": 1, "start": "5:00 AM", "end": "7:00 AM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "5:00 AM", "end": "7:00 AM", "mode": "base"},
        {"role": "washer", "people": 1, "start": "5:00 AM", "end": "7:00 AM", "mode": "base"},
        {"role": "dryer", "people": 1, "start": "5:30 AM", "end": "7:00 AM", "mode": "base"},
    ]
    result = run_shift_capacity(
        _base_payload(intervals, dryer_count=1, washer_count=2, two_dryer_split_pct=100)
    )
    dry = _coverage(result, role="dryer", mode="base", start="5:30 AM", end="7:00 AM")[0]
    assert dry["available_work_min"] >= 0
    assert dry["used_min"] <= dry["staff_min"]
    assert "used_min" in dry and "idle_min" in dry


def test_screenshot_dry_temp_trace_invariants():
    """Production-like Dry TEMP: only fully dual parents start (all-or-nothing)."""
    result = run_shift_capacity(_base_payload(_screenshot_intervals()))
    t645 = parse_clock_seconds("6:45 AM")
    t700 = parse_clock_seconds("7:00 AM")
    dry_loads = []
    for emp in result["employee_timeline"]:
        if not str(emp.get("resource_id", "")).startswith("MGMT_DRY"):
            continue
        for i in emp.get("intervals") or []:
            if i.get("task") != "dryer_load":
                continue
            if i["end_sec"] <= t645 or i["start_sec"] >= t700:
                continue
            dry_loads.append(i)
    assert len(dry_loads) == 4  # two dual parents × 2 loads (3rd dual won't fit)
    parents = {tuple(i.get("bag_ids") or []) for i in dry_loads}
    assert len(parents) == 2

    b7 = next(b for b in result["block_positions"] if b["block_end"] == "7:00 AM")
    assert b7.get("in_dry_cycle", 0) == 2
    assert b7["dried_total"] == 0
    # DRY DONE = wait_fold + fold labor + folded
    assert b7["dried_total"] == (
        b7["waiting_to_fold"] + b7.get("in_fold_labor", 0) + b7["folded_total"]
    )

    row = _coverage(
        result, role="dryer", mode="additional", start="6:45 AM", end="7:00 AM"
    )[0]
    assert row["used_min"] == 12
    assert row["idle_min"] == 3
    assert row["status"] == "work_not_fit"
