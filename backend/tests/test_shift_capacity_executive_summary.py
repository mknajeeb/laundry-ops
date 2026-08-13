"""Management executive summary: labor once per hybrid, queue bottleneck, status."""

from __future__ import annotations

from backend.shift_capacity.service import run_shift_capacity


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


def test_executive_summary_present_and_labor_from_work_coverage():
    intervals = _dedicated(weigher=1, sorter=1, washer=1, dryer=1, folder=1)
    result = run_shift_capacity(_plan(intervals, bag_count=6, batch_size=2))
    exe = result.get("management_executive_summary")
    assert exe is not None
    assert exe["target_bags"] == 6
    assert exe["staff_hours"] > 0
    assert exe["productive_hours"] >= 0
    assert exe["productive_hours"] <= exe["staff_hours"] + 0.05
    assert exe["peak_staff"] >= 1
    assert "bottleneck" in exe
    assert exe["bottleneck"].get("stage_label") != "Washer machines"
    # Must not use util-based primary_bottleneck wording
    assert "persons" not in str(exe["bottleneck"]).lower()


def test_hybrid_staff_hours_count_once():
    intervals = _dedicated(sorter=1, folder=1) + [
        {
            "mode": "hybrid",
            "roles": ["weigher", "washer", "dryer"],
            "people": 1,
            "start_time": "9:00 AM",
            "end_time": "12:00 PM",
        }
    ]
    result = run_shift_capacity(_plan(intervals, bag_count=4, batch_size=2))
    exe = result["management_executive_summary"]
    hybrid_rows = [
        r
        for r in (result.get("work_coverage") or [])
        if r.get("hybrid") or len(r.get("roles") or []) >= 2
    ]
    hybrid_staff = sum(float(r.get("staff_min") or 0) for r in hybrid_rows) / 60.0
    # One hybrid person × 3h window ≈ 3.0 staff hours (not 9 = 3 roles × 3h)
    assert abs(hybrid_staff - 3.0) < 0.05
    by_role = {r["role"]: r for r in exe["labor_by_role"]}
    assert "hybrid" in by_role
    assert abs(by_role["hybrid"]["staff_hours"] - hybrid_staff) < 0.05
    # Total staffed = sorter 3h + folder 3h + hybrid 3h (hybrid once)
    assert abs(exe["staff_hours"] - 9.0) < 0.05
    # Peak staff includes dedicated sorter + folder + 1 hybrid = at least 3 when all windows open
    assert exe["peak_staff"] >= 3


def test_two_hybrid_people_peak_counts_two():
    intervals = [
        {
            "mode": "hybrid",
            "roles": ["washer", "dryer"],
            "people": 2,
            "start_time": "9:00 AM",
            "end_time": "12:00 PM",
        }
    ]
    result = run_shift_capacity(_plan(intervals, bag_count=2, batch_size=2))
    exe = result["management_executive_summary"]
    assert exe["peak_staff"] == 2
    assert abs(exe["staff_hours"] - 6.0) < 0.05  # 2 people × 3 hours


def test_stalled_bottleneck_uses_blocking_role():
    result = run_shift_capacity(_plan([
        {"role": "weigher", "people": 1, "start": "9:00 AM", "end": "12:00 PM", "mode": "base"},
    ], bag_count=4))
    exe = result["management_executive_summary"]
    assert exe["completion_status"] == "stalled"
    assert exe["tone"] == "danger"
    assert "STALLED" in exe["status_label"]
    assert exe["bottleneck"]["stage_label"] in {"SORT", "WASH", "DRY", "FOLD", "WEIGH"}
    assert exe["projected_finish"] is None


def test_compare_snapshot_fields_present():
    intervals = _dedicated(weigher=1, sorter=1, washer=1, dryer=1, folder=1)
    result = run_shift_capacity(_plan(intervals, bag_count=4, batch_size=2))
    compare = result["management_executive_summary"]["compare"]
    for key in (
        "projected_finish",
        "completed_by_target",
        "target_bags",
        "staff_hours",
        "productive_hours",
        "peak_staff",
        "labor_min_per_bag",
        "bottleneck_stage",
        "status_label",
    ):
        assert key in compare
