"""Phase 2: management staffing-plan model for bag_des_v2."""

from backend.shift_capacity.service import run_shift_capacity
from backend.shift_capacity.staffing_plan import (
    AuthoredInterval,
    compile_employees,
    normalize_headcount,
    parse_and_compile_staffing_plan,
)
from backend.shift_capacity.timebase import parse_clock_seconds


def _plan(intervals, **overrides):
    payload = {
        "engine": "bag_des_v2",
        "management_mode": True,
        "start_time": "9:00 AM",
        "target_time": "12:00 PM",
        "planning_block_size_min": 60,
        "bag_count": 4,
        "two_washer_split_pct": 0,
        "two_dryer_split_pct": 0,
        "batch_size": 2,
        "washer_count": 2,
        "dryer_count": 2,
        "wash_cycle_min": 30,
        "dry_cycle_min": 40,
        "sort_min_per_bag": 5,
        "load_washer_min": 3,
        "load_dryer_min": 3,
        "fold_min_per_bag": 6,
        "_skip_recommendations": True,
        "staffing_plan": {"intervals": intervals},
    }
    payload.update(overrides)
    return payload


def _all_roles(start="9:00 AM", end="12:00 PM", **counts):
    base = {"weigher": 1, "sorter": 1, "washer": 1, "dryer": 1, "folder": 1}
    base.update(counts)
    return [
        {"role": r, "people": n, "start": start, "end": end, "mode": "base"}
        for r, n in base.items()
        if n > 0
    ]


def test_normalize_base_plus_additional_overlap():
    authored = [
        AuthoredInterval("sorter", 1, parse_clock_seconds("9:00 AM"), parse_clock_seconds("10:00 AM"), "base"),
        AuthoredInterval("sorter", 1, parse_clock_seconds("9:15 AM"), parse_clock_seconds("9:45 AM"), "additional"),
    ]
    segs = [s for s in normalize_headcount(authored) if s.role == "sorter"]
    assert [(s.start_sec, s.end_sec, s.people) for s in segs] == [
        (parse_clock_seconds("9:00 AM"), parse_clock_seconds("9:15 AM"), 1),
        (parse_clock_seconds("9:15 AM"), parse_clock_seconds("9:45 AM"), 2),
        (parse_clock_seconds("9:45 AM"), parse_clock_seconds("10:00 AM"), 1),
    ]


def test_normalize_multiple_overlapping_additional():
    authored = [
        AuthoredInterval("sorter", 1, parse_clock_seconds("9:00 AM"), parse_clock_seconds("10:00 AM"), "base"),
        AuthoredInterval("sorter", 1, parse_clock_seconds("9:15 AM"), parse_clock_seconds("9:45 AM"), "additional"),
        AuthoredInterval("sorter", 1, parse_clock_seconds("9:30 AM"), parse_clock_seconds("9:50 AM"), "additional"),
    ]
    segs = [s for s in normalize_headcount(authored) if s.role == "sorter"]
    got = [(s.start_sec, s.end_sec, s.people) for s in segs]
    assert got == [
        (parse_clock_seconds("9:00 AM"), parse_clock_seconds("9:15 AM"), 1),
        (parse_clock_seconds("9:15 AM"), parse_clock_seconds("9:30 AM"), 2),
        (parse_clock_seconds("9:30 AM"), parse_clock_seconds("9:45 AM"), 3),
        (parse_clock_seconds("9:45 AM"), parse_clock_seconds("9:50 AM"), 2),
        (parse_clock_seconds("9:50 AM"), parse_clock_seconds("10:00 AM"), 1),
    ]


def test_compile_stable_slot_identities_on_headcount_decrease():
    authored = [
        AuthoredInterval("sorter", 2, parse_clock_seconds("9:00 AM"), parse_clock_seconds("9:30 AM"), "base"),
        AuthoredInterval("sorter", 1, parse_clock_seconds("9:30 AM"), parse_clock_seconds("10:00 AM"), "base"),
    ]
    emps = compile_employees(normalize_headcount(authored))
    by_id = {e.employee_id: e for e in emps}
    assert "MGMT_SORT_001" in by_id
    assert "MGMT_SORT_002" in by_id
    # Slot 1 covers full 9–10; slot 2 only 9–9:30
    assert by_id["MGMT_SORT_001"].schedule_windows[0].start_min == parse_clock_seconds("9:00 AM")
    assert by_id["MGMT_SORT_001"].schedule_windows[0].end_min == parse_clock_seconds("10:00 AM")
    assert by_id["MGMT_SORT_002"].schedule_windows[0].end_min == parse_clock_seconds("9:30 AM")


def test_full_block_staffing_interval():
    result = run_shift_capacity(_plan(_all_roles(), bag_count=2, batch_size=2))
    assert result["simulation_valid"] is True
    assert result["staffing_plan"]["normalized_intervals"]
    assert result["management_outcome"]["can_complete_under_plan"] is True


def test_exact_minute_interval_affects_timestamps():
    intervals = _all_roles(end="3:00 PM")
    # Extra sorter only 9:17–9:43
    intervals.append(
        {"role": "sorter", "people": 1, "start": "9:17 AM", "end": "9:43 AM", "mode": "additional"}
    )
    result = run_shift_capacity(_plan(intervals, bag_count=6, batch_size=2, sort_min_per_bag=5))
    # Two sorters must be active in that window
    resources = {r["id"]: r for r in result["staffing_plan"]["compiled_resources"]}
    assert "MGMT_SORT_002" in resources
    assert any(
        w["start"] == "9:17 AM" and w["end"] == "9:43 AM"
        for w in resources["MGMT_SORT_002"]["windows"]
    )


def test_interval_crossing_planning_block_boundary():
    intervals = [
        {"role": "weigher", "people": 1, "start": "9:00 AM", "end": "12:00 PM"},
        {"role": "sorter", "people": 1, "start": "9:40 AM", "end": "10:20 AM"},
        {"role": "washer", "people": 1, "start": "9:00 AM", "end": "12:00 PM"},
        {"role": "dryer", "people": 1, "start": "9:00 AM", "end": "12:00 PM"},
        {"role": "folder", "people": 1, "start": "9:00 AM", "end": "12:00 PM"},
    ]
    compiled = parse_and_compile_staffing_plan(
        {"intervals": intervals},
        plan_start_sec=parse_clock_seconds("9:00 AM"),
        plan_target_sec=parse_clock_seconds("12:00 PM"),
    )
    assert compiled.accepted
    sorter = [s for s in compiled.normalized_intervals if s.role == "sorter"]
    assert sorter[0].start_sec == parse_clock_seconds("9:40 AM")
    assert sorter[0].end_sec == parse_clock_seconds("10:20 AM")


def test_half_open_boundary_behavior():
    authored = [
        AuthoredInterval("washer", 1, parse_clock_seconds("9:00 AM"), parse_clock_seconds("9:15 AM"), "base"),
        AuthoredInterval("washer", 1, parse_clock_seconds("9:15 AM"), parse_clock_seconds("9:30 AM"), "base"),
    ]
    segs = normalize_headcount(authored)
    # Adjacent intervals must not double-count at the shared boundary
    assert all(s.people == 1 for s in segs if s.role == "washer")


def test_five_roles_compile_independently():
    compiled = parse_and_compile_staffing_plan(
        {"intervals": _all_roles()},
        plan_start_sec=parse_clock_seconds("9:00 AM"),
        plan_target_sec=parse_clock_seconds("12:00 PM"),
    )
    roles = {e.primary_role for e in compiled.employees}
    assert roles == {"weigher", "sorter", "washer", "dryer", "folder"}


def test_headcount_two_creates_two_simultaneous_resources():
    result = run_shift_capacity(
        _plan(_all_roles(sorter=2), bag_count=4, batch_size=2, sort_min_per_bag=5)
    )
    ids = {r["sorted_by_employee_id"] for r in result["bag_rows"]}
    assert "MGMT_SORT_001" in ids
    assert "MGMT_SORT_002" in ids


def test_zero_wash_staff_no_wash_starts():
    result = run_shift_capacity(_plan(_all_roles(washer=0), bag_count=4, batch_size=2))
    assert result["simulation_valid"] is True
    for row in result["bag_rows"]:
        assert row["washer_load_start"] is None
        assert row["wash_start"] is None
    # Sorted work should accumulate waiting to wash
    last = result["block_positions"][-1]
    assert last["waiting_to_wash"] == 4
    assert last["washed_total"] == 0
    assert result["management_outcome"]["completion_status"] == "stalled"
    assert result["management_outcome"]["projected_finish"] is None
    assert result["summary"]["final_completion_time"] is None


def test_zero_dry_staff_no_dry_starts():
    result = run_shift_capacity(_plan(_all_roles(dryer=0), bag_count=2, batch_size=2))
    for row in result["bag_rows"]:
        assert row["wash_end"] is not None
        assert row["dryer_load_start"] is None
        assert row["ready_to_fold"] is None
    last = result["block_positions"][-1]
    assert last["waiting_to_dry"] == 2
    assert last["dried_total"] == 0
    assert result["management_outcome"]["can_complete_under_plan"] is False


def test_zero_fold_staff_no_completed_bags():
    result = run_shift_capacity(_plan(_all_roles(folder=0), bag_count=2, batch_size=2))
    for row in result["bag_rows"]:
        assert row["ready_to_fold"] is not None
        assert row["completed"] is None
    assert result["management_outcome"]["bags_completed"] == 0
    assert result["management_outcome"]["completion_status"] == "stalled"


def test_no_hidden_synthetic_labor_or_legacy_merge():
    result = run_shift_capacity(
        _plan(
            _all_roles(),
            bag_count=2,
            employees=[
                {
                    "id": "LEGACY",
                    "primary_role": "washer",
                    "secondary_roles": ["folder", "dryer"],
                    "start_time": "9:00 AM",
                }
            ],
            weigher_washer_same=True,
            sorter_washer_same=True,
        )
    )
    used = {
        r["weighed_by_employee_id"]
        for r in result["bag_rows"]
    } | {
        r["sorted_by_employee_id"]
        for r in result["bag_rows"]
    } | {
        r["washer_loaded_by_employee_id"]
        for r in result["bag_rows"]
    } | {
        r["dryer_loaded_by_employee_id"]
        for r in result["bag_rows"]
    } | {
        r["folded_by_employee_id"]
        for r in result["bag_rows"]
    }
    assert "LEGACY" not in used
    assert "Unassigned" not in used
    assert all(str(x).startswith("MGMT_") for x in used if x)


def test_staffing_ends_at_target_does_not_silently_extend():
    # Folders only until target; create more work than they can finish before 10:00.
    intervals = _all_roles(end="10:00 AM", folder=1)
    result = run_shift_capacity(
        _plan(
            intervals,
            start_time="9:00 AM",
            target_time="10:00 AM",
            bag_count=8,
            batch_size=2,
            fold_min_per_bag=10,
            sort_min_per_bag=1,
            load_washer_min=1,
            load_dryer_min=1,
            wash_cycle_min=5,
            dry_cycle_min=5,
            weigh_sec_per_bag=30,
        )
    )
    outcome = result["management_outcome"]
    # Either stalled (couldn't finish) or completed by/at target — never invent post-target finish
    if outcome["completion_status"] == "stalled":
        assert outcome["projected_finish"] is None
        assert result["summary"]["final_completion_time"] is None
    else:
        assert parse_clock_seconds(outcome["projected_finish"]) <= parse_clock_seconds("10:00 AM")


def test_incomplete_plan_truthful_queues_and_reconciliation():
    result = run_shift_capacity(_plan(_all_roles(washer=0), bag_count=6, batch_size=2))
    for row in result["block_positions"]:
        assert row["reconciliation"]["ok"] is True
        assert row["reconciliation"]["exclusive_state_sum"] == 6
    assert result["block_positions"][-1]["waiting_to_wash"] == 6


def test_blocks_30_45_60_independent_of_staffing_shape():
    intervals = _all_roles()
    intervals.append(
        {"role": "sorter", "people": 1, "start": "9:17 AM", "end": "10:43 AM", "mode": "additional"}
    )
    for size in (30, 45, 60):
        result = run_shift_capacity(
            _plan(intervals, planning_block_size_min=size, bag_count=2)
        )
        assert result["block_positions"]
        assert result["block_positions"][0]["staffing"]["roles"]["sorter"]["peak_people"] >= 1
        for row in result["block_positions"]:
            assert row["reconciliation"]["ok"] is True


def test_reject_invalid_people_zero_and_unknown_role():
    # people=0 is omitted (not capacity), plan remains valid/empty.
    zero = parse_and_compile_staffing_plan(
        {"intervals": [{"role": "sorter", "people": 0, "start": "9:00 AM", "end": "10:00 AM"}]},
        plan_start_sec=parse_clock_seconds("9:00 AM"),
        plan_target_sec=parse_clock_seconds("12:00 PM"),
        plan_end_sec=parse_clock_seconds("5:00 PM"),
    )
    assert zero.accepted
    assert zero.authored == []
    assert zero.employees == []
    bad_role = parse_and_compile_staffing_plan(
        {"intervals": [{"role": "manager", "people": 1, "start": "9:00 AM", "end": "10:00 AM"}]},
        plan_start_sec=parse_clock_seconds("9:00 AM"),
        plan_target_sec=parse_clock_seconds("12:00 PM"),
        plan_end_sec=parse_clock_seconds("5:00 PM"),
    )
    assert not bad_role.accepted


def test_api_rejects_invalid_staffing_plan():
    result = run_shift_capacity(
        _plan([{"role": "sorter", "people": -1, "start": "9:00 AM", "end": "10:00 AM"}])
    )
    assert result["simulation_valid"] is False or result.get("validation", {}).get("accepted") is False


def test_block_staffing_echo_for_ui():
    intervals = [
        {"role": "weigher", "people": 1, "start": "9:00 AM", "end": "10:00 AM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "9:00 AM", "end": "10:00 AM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "9:15 AM", "end": "9:45 AM", "mode": "additional"},
        {"role": "washer", "people": 1, "start": "9:00 AM", "end": "10:00 AM", "mode": "base"},
        {"role": "dryer", "people": 1, "start": "9:00 AM", "end": "10:00 AM", "mode": "base"},
        {"role": "folder", "people": 2, "start": "9:00 AM", "end": "10:00 AM", "mode": "base"},
    ]
    result = run_shift_capacity(_plan(intervals, target_time="10:00 AM", bag_count=1, batch_size=1))
    block = result["block_positions"][0]["staffing"]
    assert block["roles"]["sorter"]["people_at_block_start"] == 1
    assert block["roles"]["sorter"]["peak_people"] == 2
    assert block["roles"]["sorter"]["additional"]
    assert block["roles"]["folder"]["people_at_block_start"] == 2


def test_reject_overlapping_base_same_role():
    compiled = parse_and_compile_staffing_plan(
        {
            "intervals": [
                {"role": "sorter", "people": 1, "start": "9:00 AM", "end": "10:00 AM", "mode": "base"},
                {"role": "sorter", "people": 1, "start": "9:30 AM", "end": "10:30 AM", "mode": "base"},
            ]
        },
        plan_start_sec=parse_clock_seconds("9:00 AM"),
        plan_target_sec=parse_clock_seconds("12:00 PM"),
        plan_end_sec=parse_clock_seconds("5:00 PM"),
    )
    assert not compiled.accepted
    assert any(e.code == "STAFFING_BASE_OVERLAP" for e in compiled.errors)


def test_allow_overlapping_additional_and_base_plus_additional():
    compiled = parse_and_compile_staffing_plan(
        {
            "intervals": [
                {"role": "sorter", "people": 2, "start": "9:00 AM", "end": "12:00 PM", "mode": "base"},
                {"role": "sorter", "people": 1, "start": "10:15 AM", "end": "10:45 AM", "mode": "additional"},
                {"role": "sorter", "people": 1, "start": "10:30 AM", "end": "11:00 AM", "mode": "additional"},
            ]
        },
        plan_start_sec=parse_clock_seconds("9:00 AM"),
        plan_target_sec=parse_clock_seconds("12:00 PM"),
        plan_end_sec=parse_clock_seconds("5:00 PM"),
    )
    assert compiled.accepted
    segs = [s for s in compiled.normalized_intervals if s.role == "sorter"]
    got = [(s.start_sec, s.end_sec, s.people) for s in segs]
    assert got == [
        (parse_clock_seconds("9:00 AM"), parse_clock_seconds("10:15 AM"), 2),
        (parse_clock_seconds("10:15 AM"), parse_clock_seconds("10:30 AM"), 3),
        (parse_clock_seconds("10:30 AM"), parse_clock_seconds("10:45 AM"), 4),
        (parse_clock_seconds("10:45 AM"), parse_clock_seconds("11:00 AM"), 3),
        (parse_clock_seconds("11:00 AM"), parse_clock_seconds("12:00 PM"), 2),
    ]
    by_id = {e.employee_id: e for e in compiled.employees}
    assert by_id["MGMT_SORT_001"].schedule_windows[0].end_min == parse_clock_seconds("12:00 PM")
    assert by_id["MGMT_SORT_002"].schedule_windows[0].end_min == parse_clock_seconds("12:00 PM")
    assert by_id["MGMT_SORT_003"].schedule_windows[0].start_min == parse_clock_seconds("10:15 AM")
    assert by_id["MGMT_SORT_003"].schedule_windows[0].end_min == parse_clock_seconds("11:00 AM")
    assert by_id["MGMT_SORT_004"].schedule_windows[0].start_min == parse_clock_seconds("10:30 AM")
    assert by_id["MGMT_SORT_004"].schedule_windows[0].end_min == parse_clock_seconds("10:45 AM")


def test_reject_fractional_and_out_of_bounds():
    frac = parse_and_compile_staffing_plan(
        {"intervals": [{"role": "sorter", "people": 1.5, "start": "9:00 AM", "end": "10:00 AM"}]},
        plan_start_sec=parse_clock_seconds("9:00 AM"),
        plan_target_sec=parse_clock_seconds("12:00 PM"),
        plan_end_sec=parse_clock_seconds("5:00 PM"),
    )
    assert not frac.accepted
    oob = parse_and_compile_staffing_plan(
        {"intervals": [{"role": "sorter", "people": 1, "start": "8:00 AM", "end": "10:00 AM"}]},
        plan_start_sec=parse_clock_seconds("9:00 AM"),
        plan_target_sec=parse_clock_seconds("12:00 PM"),
        plan_end_sec=parse_clock_seconds("5:00 PM"),
    )
    assert not oob.accepted
    assert any(e.code == "STAFFING_OUT_OF_BOUNDS" for e in oob.errors)


def test_zero_wash_no_synthetic_reservation():
    result = run_shift_capacity(_plan(_all_roles(washer=0), bag_count=4, batch_size=2))
    assert "Unassigned" not in str(result.get("timelines", {}))
    for rid in (result.get("timelines") or {}).get("employees", {}):
        assert not str(rid).startswith("__")
        assert rid != "Unassigned"
    for row in result["bag_rows"]:
        assert row["washer_loaded_by_employee_id"] in (None, "")
        assert row["wash_start"] is None
    deficits = result["staffing_deficits"]
    assert any(d["role"] == "washer" and d["reason"] == "NO_STAFF_AVAILABLE" for d in deficits)
    assert result["management_outcome"]["first_blocking_role"] == "washer"


def test_wash_staff_begins_later_waits_then_resumes():
    intervals = [
        {"role": "weigher", "people": 1, "start": "9:00 AM", "end": "12:00 PM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "9:00 AM", "end": "12:00 PM", "mode": "base"},
        {"role": "washer", "people": 1, "start": "10:00 AM", "end": "12:00 PM", "mode": "base"},
        {"role": "dryer", "people": 1, "start": "9:00 AM", "end": "3:00 PM", "mode": "base"},
        {"role": "folder", "people": 1, "start": "9:00 AM", "end": "3:00 PM", "mode": "base"},
    ]
    result = run_shift_capacity(
        _plan(
            intervals,
            bag_count=2,
            batch_size=2,
            end_time="3:00 PM",
            target_time="3:00 PM",
            sort_min_per_bag=1,
            load_washer_min=3,
            wash_cycle_min=5,
            dry_cycle_min=5,
            fold_min_per_bag=2,
        )
    )
    assert result["simulation_valid"] is True
    wash_starts = [parse_clock_seconds(r["washer_load_start"]) for r in result["bag_rows"]]
    assert all(t >= parse_clock_seconds("10:00 AM") for t in wash_starts)
    assert result["management_outcome"]["can_complete_under_plan"] is True
    assert all(r["completed"] is not None for r in result["bag_rows"])


def test_wash_staff_ends_no_new_ops_outside_window():
    intervals = [
        {"role": "weigher", "people": 1, "start": "9:00 AM", "end": "12:00 PM", "mode": "base"},
        {"role": "sorter", "people": 1, "start": "9:00 AM", "end": "12:00 PM", "mode": "base"},
        {"role": "washer", "people": 1, "start": "9:00 AM", "end": "9:20 AM", "mode": "base"},
        {"role": "dryer", "people": 1, "start": "9:00 AM", "end": "12:00 PM", "mode": "base"},
        {"role": "folder", "people": 1, "start": "9:00 AM", "end": "12:00 PM", "mode": "base"},
    ]
    result = run_shift_capacity(
        _plan(
            intervals,
            bag_count=6,
            batch_size=2,
            sort_min_per_bag=1,
            load_washer_min=3,
            wash_cycle_min=5,
        )
    )
    for row in result["bag_rows"]:
        if row["washer_load_start"] is None:
            continue
        start = parse_clock_seconds(row["washer_load_start"])
        end = parse_clock_seconds(row["washer_load_end"])
        assert start >= parse_clock_seconds("9:00 AM")
        assert end <= parse_clock_seconds("9:20 AM")


def test_empty_staffing_plan_zero_progress_no_defaults():
    result = run_shift_capacity(_plan([], bag_count=4, batch_size=2))
    assert result["simulation_valid"] is True
    assert result["staffing_plan"]["compiled_resources"] == []
    for row in result["bag_rows"]:
        assert row["weigh_start"] is None
        assert row["wash_start"] is None
        assert row["completed"] is None
    assert "Unassigned" not in {
        row.get("weighed_by_employee_id") for row in result["bag_rows"]
    }
    last = result["block_positions"][-1]
    assert last["not_yet_weighed"] == 4
    assert last["reconciliation"]["ok"] is True
    assert result["management_outcome"]["completion_status"] == "stalled"
    assert result["summary"]["final_completion_time"] is None
    assert any(d["role"] == "weigher" for d in result["staffing_deficits"])


def test_stalled_plan_outcome_not_fabricated():
    result = run_shift_capacity(_plan(_all_roles(dryer=0), bag_count=2, batch_size=2))
    outcome = result["management_outcome"]
    assert outcome["completion_status"] == "stalled"
    assert outcome["can_complete_under_plan"] is False
    assert outcome["projected_finish"] is None
    assert outcome["first_blocking_role"] == "dryer"
    assert result["summary"]["final_completion_time"] is None


def test_incomplete_by_target_with_explicit_post_target_staff():
    # Finish after noon is allowed only because staffing is authored past target.
    intervals = _all_roles(end="3:00 PM")
    result = run_shift_capacity(
        _plan(
            intervals,
            start_time="9:00 AM",
            target_time="10:00 AM",
            end_time="3:00 PM",
            bag_count=4,
            batch_size=2,
            sort_min_per_bag=5,
            fold_min_per_bag=8,
            wash_cycle_min=30,
            dry_cycle_min=40,
        )
    )
    outcome = result["management_outcome"]
    if outcome["can_complete_under_plan"]:
        assert outcome["completion_status"] in ("completed", "incomplete_by_target")
        if outcome["completion_status"] == "incomplete_by_target":
            assert parse_clock_seconds(outcome["projected_finish"]) > parse_clock_seconds("10:00 AM")
            assert result["summary"]["final_completion_time"] is not None


def test_staffing_not_extrapolated_after_authored_end():
    intervals = _all_roles(end="10:00 AM")
    result = run_shift_capacity(
        _plan(
            intervals,
            start_time="9:00 AM",
            target_time="12:00 PM",
            end_time="12:00 PM",
            bag_count=8,
            batch_size=2,
            fold_min_per_bag=10,
        )
    )
    # No employee window may end after authored 10:00.
    for res in result["staffing_plan"]["compiled_resources"]:
        for win in res["windows"]:
            assert parse_clock_seconds(win["end"]) <= parse_clock_seconds("10:00 AM")
    if result["management_outcome"]["completion_status"] == "stalled":
        assert result["summary"]["final_completion_time"] is None


def test_machines_without_wash_staff_yield_zero_wash_starts():
    """4 washers + WASH staff 0 => washed_total 0; waiting_to_wash builds."""
    intervals = [
        {"role": "weigher", "people": 1, "start": "9:00 AM", "end": "12:00 PM"},
        {"role": "sorter", "people": 1, "start": "9:00 AM", "end": "12:00 PM"},
        {"role": "dryer", "people": 1, "start": "9:00 AM", "end": "12:00 PM"},
        {"role": "folder", "people": 1, "start": "9:00 AM", "end": "12:00 PM"},
    ]
    result = run_shift_capacity(
        _plan(intervals, bag_count=4, batch_size=2, washer_count=4, dryer_count=4)
    )
    last = result["block_positions"][-1]
    assert last["washed_total"] == 0
    assert last["waiting_to_wash"] == 4
    assert all(row["wash_start"] is None for row in result["bag_rows"])


def test_wash_staff_added_later_allows_wash_only_after_window():
    intervals = [
        {"role": "weigher", "people": 1, "start": "9:00 AM", "end": "12:00 PM"},
        {"role": "sorter", "people": 1, "start": "9:00 AM", "end": "12:00 PM"},
        {"role": "washer", "people": 1, "start": "10:00 AM", "end": "12:00 PM"},
        {"role": "dryer", "people": 1, "start": "9:00 AM", "end": "12:00 PM"},
        {"role": "folder", "people": 1, "start": "9:00 AM", "end": "12:00 PM"},
    ]
    result = run_shift_capacity(
        _plan(intervals, bag_count=2, batch_size=2, washer_count=4, dryer_count=4)
    )
    wash_starts = [
        parse_clock_seconds(row["wash_start"])
        for row in result["bag_rows"]
        if row.get("wash_start")
    ]
    assert wash_starts
    assert all(t >= parse_clock_seconds("10:00 AM") for t in wash_starts)
    # First block end (10:00): wash may still be zero or just starting; later blocks advance.
    by_end = {b["block_end"]: b for b in result["block_positions"]}
    assert by_end["12:00 PM"]["washed_total"] >= 1


def test_dry_advances_then_fold_after_fold_staff_added():
    """Dry DONE advances with Fold=0; waiting_to_fold builds; later Fold staff completes bags."""
    target = 4
    # Phase 1: no Fold staff
    no_fold = [
        {"role": "weigher", "people": 2, "start": "9:00 AM", "end": "3:00 PM"},
        {"role": "sorter", "people": 2, "start": "9:00 AM", "end": "3:00 PM"},
        {"role": "washer", "people": 2, "start": "9:00 AM", "end": "3:00 PM"},
        {"role": "dryer", "people": 2, "start": "9:00 AM", "end": "3:00 PM"},
    ]
    stalled = run_shift_capacity(
        _plan(
            no_fold,
            bag_count=target,
            batch_size=2,
            start_time="9:00 AM",
            target_time="3:00 PM",
            end_time="3:00 PM",
            washer_count=4,
            dryer_count=4,
            wash_cycle_min=20,
            dry_cycle_min=20,
            sort_min_per_bag=2,
            fold_min_per_bag=4,
        )
    )
    last = stalled["block_positions"][-1]
    assert last["washed_total"] >= 1
    assert last["dried_total"] >= 1
    assert last["waiting_to_fold"] >= 1
    assert (last.get("folded_total") or last.get("completed_total") or 0) == 0
    assert stalled["management_outcome"]["completion_status"] == "stalled"
    assert stalled["summary"]["final_completion_time"] is None

    # Phase 2: Fold staff from 11:00 onward
    with_fold = no_fold + [
        {"role": "folder", "people": 2, "start": "11:00 AM", "end": "3:00 PM"},
    ]
    finished = run_shift_capacity(
        _plan(
            with_fold,
            bag_count=target,
            batch_size=2,
            start_time="9:00 AM",
            target_time="3:00 PM",
            end_time="3:00 PM",
            washer_count=4,
            dryer_count=4,
            wash_cycle_min=20,
            dry_cycle_min=20,
            sort_min_per_bag=2,
            fold_min_per_bag=4,
        )
    )
    last2 = finished["block_positions"][-1]
    folded = last2.get("folded_total") or last2.get("completed_total") or 0
    assert last2["dried_total"] >= folded
    assert folded >= 1
    # Target reconciliation for display: remaining = target - folded
    assert target - folded >= 0
    # Fold cannot start before authored fold window.
    for row in finished["bag_rows"]:
        if row.get("fold_start"):
            assert parse_clock_seconds(row["fold_start"]) >= parse_clock_seconds("11:00 AM")
