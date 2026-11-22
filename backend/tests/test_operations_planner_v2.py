"""Recurrence, publication, coverage, and access rules for Operations Planner v2."""

from __future__ import annotations

from datetime import date, timedelta

from backend.operations_planner_v2 import (
    approve_weeks,
    cell_shifts,
    plan_cell_scopes,
    break_overlap_warnings,
    cell_shift,
    commit_or_rollback,
    employee_module_visible,
    employee_schedule_view,
    employee_visible_snapshot,
    empty_state,
    hour_coverage,
    patterns_overlap,
    paystub_decision,
    plan_assignment_draft,
    plan_change,
    plan_entry_write,
    plan_task_links,
    span_minutes,
    publish_weeks,
    role_visible_to_rinse,
    shift_hours,
    target_weeks,
    verify_step_up_factors,
)
from backend.weekly_schedule_week import current_schedule_monday

TODAY = date(2026, 11, 11)  # Wednesday
ANCHOR = date(2026, 11, 9)  # Monday of that week
NEXT = ANCHOR + timedelta(days=7)


def _shift(**overrides):
    start = overrides.get("start_time", "08:00")
    end = overrides.get("end_time", "16:00")
    role = overrides.get("role", "fold")
    default_span = start == "08:00" and end == "16:00"
    payload = {
        "start_time": start,
        "end_time": end,
        "role": role,
        "break_minutes": 0,
        "break_slots": [{"start_time": "12:00", "end_time": "12:30", "timed": True}] if default_span else [],
        "role_assignments": (
            [
                {"role": "wash", "start_time": "08:00", "end_time": "12:00"},
                {"role": "fold", "start_time": "12:30", "end_time": "16:00"},
            ]
            if default_span
            else [{"role": role, "start_time": start, "end_time": end}]
        ),
    }
    payload.update(overrides)
    return payload


def _apply(state, **overrides):
    command = {
        "action": "upsert",
        "scope": "this_and_future",
        "anchor": ANCHOR,
        "today": TODAY,
        "user_id": 7,
        "day_of_week": 1,
        "shift": _shift(),
        "include_published": False,
        "replace_exceptions": True,
        "horizon_weeks": 6,
    }
    command.update(overrides)
    return plan_change(state, command)


def test_sunday_opens_the_following_monday():
    assert current_schedule_monday(date(2026, 11, 15)) == date(2026, 11, 16)


def test_historical_weeks_are_immutable():
    weeks, err = target_weeks(
        scope="this_week",
        anchor=date(2026, 11, 2),
        selected=None,
        today=TODAY,
    )
    assert weeks is None
    assert err


def test_scenario_a_recurring_pattern_exception_and_future_edit():
    created = _apply(empty_state())
    assert created["ok"] is True
    assert patterns_overlap(created["state"]) is False
    state = created["state"]
    assert cell_shift(state, 7, 1, ANCHOR)["start_time"] == "08:00"
    assert cell_shift(state, 7, 1, NEXT)["role"] == "fold"
    assert cell_shift(state, 7, 1, ANCHOR + timedelta(days=14))["start_time"] == "08:00"

    one_week = _apply(
        state,
        scope="this_week",
        shift=_shift(start_time="09:00", end_time="17:00"),
        include_published=False,
        replace_exceptions=True,
    )
    assert one_week["ok"] is True
    state = one_week["state"]
    assert cell_shift(state, 7, 1, ANCHOR)["start_time"] == "09:00"
    assert cell_shift(state, 7, 1, NEXT)["start_time"] == "08:00"

    future = _apply(
        state,
        scope="future_only",
        shift=_shift(start_time="07:00", end_time="15:00", role="wash"),
        include_published=False,
        replace_exceptions=True,
    )
    assert future["ok"] is True
    state = future["state"]
    assert cell_shift(state, 7, 1, ANCHOR)["start_time"] == "09:00"
    assert cell_shift(state, 7, 1, NEXT)["start_time"] == "07:00"
    assert patterns_overlap(state) is False


def test_selected_weeks_do_not_rewrite_the_pattern():
    created = _apply(empty_state())
    selected = _apply(
        created["state"],
        scope="selected_weeks",
        selected_weeks=[NEXT.isoformat(), (NEXT + timedelta(days=14)).isoformat()],
        shift=_shift(start_time="10:00", end_time="14:00"),
    )
    assert selected["ok"] is True
    state = selected["state"]
    assert cell_shift(state, 7, 1, ANCHOR)["start_time"] == "08:00"
    assert cell_shift(state, 7, 1, NEXT)["start_time"] == "10:00"
    assert cell_shift(state, 7, 1, NEXT + timedelta(days=7))["start_time"] == "08:00"


def test_published_week_requires_an_explicit_choice_then_a_new_draft():
    created = _apply(empty_state(), horizon_weeks=3)
    state = created["state"]
    approved = approve_weeks(state, [ANCHOR])
    published = publish_weeks(approved["state"], [ANCHOR], {ANCHOR.isoformat(): {"entries": [{"user_id": 7}]}})
    state = published["state"]
    blocked = _apply(state, shift=_shift(start_time="09:00", end_time="15:00"), include_published=None)
    assert blocked["ok"] is False
    assert blocked["code"] == "confirmation_required"
    assert "published" in blocked["questions"]
    assert ANCHOR.isoformat() in blocked["preview"]["approved_or_published_weeks"]
    assert blocked["preview"]["employees"][0]["user_id"] == 7

    skipped = _apply(state, shift=_shift(start_time="09:00", end_time="15:00"), include_published=False)
    assert skipped["ok"] is True
    assert cell_shift(skipped["state"], 7, 1, ANCHOR)["start_time"] == "08:00"
    assert cell_shift(skipped["state"], 7, 1, NEXT)["start_time"] == "09:00"
    assert employee_visible_snapshot(skipped["state"], ANCHOR)["entries"][0]["user_id"] == 7

    included = _apply(
        state,
        shift=_shift(start_time="09:00", end_time="15:00"),
        include_published=True,
        replace_exceptions=True,
    )
    assert included["ok"] is True
    assert ANCHOR.isoformat() in included["republish_required"]
    assert included["state"]["weeks"][ANCHOR.isoformat()]["status"] == "draft"
    assert included["state"]["weeks"][ANCHOR.isoformat()]["revision"] == 2
    visible = employee_visible_snapshot(included["state"], ANCHOR)
    assert visible["entries"][0]["user_id"] == 7
    assert cell_shift(included["state"], 7, 1, ANCHOR)["start_time"] == "09:00"


def test_future_exception_is_kept_until_the_manager_replaces_it():
    created = _apply(empty_state())
    exceptional = _apply(
        created["state"],
        scope="selected_weeks",
        selected_weeks=[NEXT.isoformat()],
        shift=_shift(start_time="11:00", end_time="15:00"),
    )
    blocked = _apply(
        exceptional["state"],
        shift=_shift(start_time="06:00", end_time="14:00"),
        replace_exceptions=None,
        include_published=False,
    )
    assert blocked["ok"] is False
    assert "exceptions" in blocked["questions"]
    kept = _apply(
        exceptional["state"],
        shift=_shift(start_time="06:00", end_time="14:00"),
        replace_exceptions=False,
        include_published=False,
    )
    assert cell_shift(kept["state"], 7, 1, NEXT)["start_time"] == "11:00"
    assert cell_shift(kept["state"], 7, 1, ANCHOR)["start_time"] == "06:00"


def test_move_cannot_resize_and_does_not_duplicate():
    created = _apply(empty_state())
    resized = plan_change(
        created["state"],
        {
            "action": "move",
            "scope": "this_week",
            "anchor": ANCHOR,
            "today": TODAY,
            "user_id": 7,
            "day_of_week": 1,
            "shift": _shift(end_time="18:00"),
            "previous_shift": _shift(),
            "include_published": False,
            "replace_exceptions": True,
        },
    )
    assert resized["code"] == "resize_rejected"
    moved = plan_change(
        created["state"],
        {
            "action": "move",
            "scope": "this_week",
            "anchor": ANCHOR,
            "today": TODAY,
            "user_id": 7,
            "from_day_of_week": 1,
            "day_of_week": 2,
            "shift": _shift(start_time="09:00", end_time="17:00"),
            "previous_shift": _shift(),
            "include_published": False,
            "replace_exceptions": True,
        },
    )
    assert moved["ok"] is True
    assert cell_shift(moved["state"], 7, 1, ANCHOR) is None
    assert cell_shift(moved["state"], 7, 2, ANCHOR)["start_time"] == "09:00"
    assert cell_shift(moved["state"], 7, 1, NEXT)["start_time"] == "08:00"
    plans = {(row["user_id"], row["day_of_week"], row["week_monday"]) for row in moved["cell_plans"]}
    assert len(plans) == len(moved["cell_plans"])


def test_a_shift_set_keeps_both_halves_and_refuses_a_lost_id():
    from backend.operations_planner_v2 import plan_shift_set

    planned = plan_shift_set(
        [
            {
                "op": "update",
                "id": 5136,
                "user_id": 19,
                "day_of_week": 1,
                "shift": _shift(start_time="05:00", end_time="09:00", role="weigher,fold"),
            },
            {
                "op": "create",
                "user_id": 19,
                "day_of_week": 1,
                "shift": _shift(start_time="09:00", end_time="13:00", role="fold"),
            },
        ]
    )
    assert planned["ok"] is True
    assert [item["action"] for item in planned["decisions"]] == ["update", "create"]
    assert planned["decisions"][0]["entry_id"] == 5136
    assert "entry_id" not in planned["decisions"][1]
    missing = plan_shift_set(
        [{"op": "update", "id": 0, "user_id": 19, "day_of_week": 1, "shift": _shift()}]
    )
    assert missing["ok"] is False
    deleted = plan_shift_set([{"op": "delete", "id": 5216, "user_id": 38, "day_of_week": 3}])
    assert deleted["ok"] is True
    assert deleted["decisions"] == [{"action": "delete", "entry_id": 5216, "user_id": 38, "day_of_week": 3}]


def test_duplicate_entry_is_an_update_not_a_second_insert():
    decision = plan_entry_write([{"id": 4}], _shift())
    assert decision == {"ok": True, "action": "update", "entry_id": 4}
    blocked = plan_entry_write([{"id": 4}, {"id": 5}], _shift())
    assert blocked["ok"] is False


def test_overlapping_role_segments_are_rejected():
    result = _apply(
        empty_state(),
        shift=_shift(
            role_assignments=[
                {"role": "wash", "start_time": "08:00", "end_time": "12:00"},
                {"role": "fold", "start_time": "11:00", "end_time": "16:00"},
            ]
        ),
    )
    assert result["ok"] is False
    assert result["code"] == "invalid_shift"


def test_timed_break_reduces_available_coverage_not_scheduled_staff():
    fold = _shift()
    other = _shift(role="fold", break_slots=[{"start_time": "12:00", "end_time": "12:30", "timed": True}])
    third = _shift(role="sort", break_slots=[{"start_time": "12:00", "end_time": "12:45", "timed": True}])
    fourth = _shift(role="dry", break_slots=[{"start_time": "12:15", "end_time": "12:45", "timed": True}])
    noon = hour_coverage([(1, fold), (2, other), (3, third), (4, _shift(break_slots=[]))], hour=12)
    assert noon["scheduled_count"] == 4
    assert 4 in noon["available"]
    assert 1 in noon["on_break"]
    assert noon["available_count"] == 1
    warnings = break_overlap_warnings([(1, fold), (2, other), (3, third), (4, fourth)])
    assert warnings and warnings[0]["count"] >= 4
    hours = shift_hours(fold)
    assert hours["gross"] == 8
    assert hours["timed_break"] == 0.5
    assert hours["net"] == 7.5


def test_untimed_break_stays_available():
    shift = _shift(break_slots=[{"start_time": "12:00", "end_time": "12:30", "timed": False}])
    noon = hour_coverage([(8, shift)], hour=12)
    assert noon["available_count"] == 1
    assert noon["on_break"] == []
    assert shift_hours(shift)["net"] == 8


def test_publish_requires_approval_and_hides_drafts_from_employees():
    state = empty_state()
    blocked = publish_weeks(state, [ANCHOR], {ANCHOR.isoformat(): {"entries": []}})
    assert blocked["ok"] is False
    approved = approve_weeks(state, [ANCHOR])
    published = publish_weeks(approved["state"], [ANCHOR], {ANCHOR.isoformat(): {"entries": [{"user_id": 7}]}})
    assert published["state"]["weeks"][ANCHOR.isoformat()]["status"] == "published"
    hidden = employee_module_visible(pilot_enabled=True, employee_enabled=False, published_snapshot={"entries": []})
    assert hidden["visible"] is False
    shown = employee_module_visible(
        pilot_enabled=True,
        employee_enabled=True,
        published_snapshot=employee_visible_snapshot(published["state"], ANCHOR),
    )
    assert shown["visible"] is True
    unpublished = employee_module_visible(pilot_enabled=True, employee_enabled=True, published_snapshot=None)
    assert unpublished["reason"] == "unpublished"


def test_paystub_gate_and_step_up():
    assert (
        paystub_decision(
            module_enabled=False,
            employee_enabled=True,
            worker_category="w2",
            step_up_ok=True,
            second_factor_on_file=True,
            document_available=True,
        )
        == "module_disabled"
    )
    assert (
        paystub_decision(
            module_enabled=True,
            employee_enabled=True,
            worker_category="contractor_1099",
            step_up_ok=True,
            second_factor_on_file=True,
            document_available=True,
        )
        == "not_w2"
    )
    assert (
        paystub_decision(
            module_enabled=True,
            employee_enabled=True,
            worker_category="w2",
            step_up_ok=True,
            second_factor_on_file=True,
            document_available=False,
        )
        == "no_authoritative_document"
    )
    ok, reason = verify_step_up_factors(pin_ok=True, dob_supplied=None, dob_on_file=None)
    assert ok is False and reason == "second_factor_unavailable"
    ok, reason = verify_step_up_factors(
        pin_ok=True, dob_supplied=date(1990, 1, 2), dob_on_file=date(1990, 1, 1)
    )
    assert ok is False and reason == "verification_failed"
    ok, reason = verify_step_up_factors(
        pin_ok=True, dob_supplied=date(1990, 1, 1), dob_on_file=date(1990, 1, 1)
    )
    assert ok is True


def test_role_toggle_cannot_override_labor_policy():
    assert role_visible_to_rinse("fold", show_on_rinse_dashboard=True, hidden_by_labor_policy=["fold"]) is False
    assert role_visible_to_rinse("fold", show_on_rinse_dashboard=False, hidden_by_labor_policy=[]) is False
    assert role_visible_to_rinse("fold", show_on_rinse_dashboard=True, hidden_by_labor_policy=[]) is True


def test_employee_schedule_view_drops_coworkers():
    view = employee_schedule_view(
        {
            "week_start": "2026-11-09",
            "entries": [{"user_id": 7, "role": "fold"}, {"user_id": 8, "role": "wash"}],
            "daily_responsibilities": [{"user_id": 8, "role": "task"}],
        },
        7,
    )
    assert view is not None
    assert [row["user_id"] for row in view["entries"]] == [7]
    assert view["responsibilities"] == []
    missing = plan_change(empty_state(), {"action": "upsert", "today": TODAY, "anchor": ANCHOR})
    assert missing["ok"] is False
    created = _apply(empty_state())
    removed = plan_change(
        created["state"],
        {
            "action": "delete",
            "scope": "future_only",
            "anchor": ANCHOR,
            "today": TODAY,
            "user_id": 7,
            "day_of_week": 1,
            "include_published": False,
            "replace_exceptions": True,
            "horizon_weeks": 4,
        },
    )
    assert removed["ok"] is True
    assert cell_shift(removed["state"], 7, 1, ANCHOR)["start_time"] == "08:00"
    assert cell_shift(removed["state"], 7, 1, NEXT) is None


def test_later_effective_pattern_is_kept_unless_the_manager_replaces_it():
    first = _apply(empty_state())
    later = ANCHOR + timedelta(days=28)
    second = _apply(
        first["state"],
        anchor=later,
        today=later,
        shift=_shift(start_time="10:00", end_time="18:00"),
        replace_later_patterns=False,
    )
    asked = _apply(second["state"], shift=_shift(start_time="09:00", end_time="17:00"))
    assert asked["code"] == "confirmation_required"
    assert "later_patterns" in asked["questions"]
    kept = _apply(
        second["state"],
        shift=_shift(start_time="09:00", end_time="17:00"),
        replace_later_patterns=False,
    )
    assert cell_shift(kept["state"], 7, 1, ANCHOR)["start_time"] == "09:00"
    assert cell_shift(kept["state"], 7, 1, later)["start_time"] == "10:00"
    replaced = _apply(
        second["state"],
        shift=_shift(start_time="07:00", end_time="15:00"),
        replace_later_patterns=True,
    )
    assert cell_shift(replaced["state"], 7, 1, later)["start_time"] == "07:00"


def test_selected_weeks_are_full_weeks_and_skip_the_gap():
    base = _apply(empty_state())
    gap = ANCHOR + timedelta(days=14)
    far = ANCHOR + timedelta(days=21)
    picked = _apply(
        base["state"],
        scope="selected_weeks",
        selected_weeks=[NEXT.isoformat(), far.isoformat()],
        shift=_shift(start_time="09:00", end_time="15:00"),
    )
    assert picked["ok"] is True
    assert picked["preview"]["week_meaning"].startswith("Each date is the Monday")
    assert cell_shift(picked["state"], 7, 1, NEXT)["start_time"] == "09:00"
    assert cell_shift(picked["state"], 7, 1, gap)["start_time"] == "08:00"
    assert cell_shift(picked["state"], 7, 1, far)["start_time"] == "09:00"


def test_cross_year_week_and_dst_wall_clock():
    anchor = date(2026, 12, 28)
    result = _apply(empty_state(), anchor=anchor, today=date(2026, 12, 30), scope="this_week")
    assert result["write_weeks"] == ["2026-12-28"]
    assert cell_shift(result["state"], 7, 1, anchor)["start_time"] == "08:00"
    assert span_minutes("01:30", "04:30") == 180


def test_employment_end_does_not_schedule_later_weeks():
    result = _apply(empty_state(), employment_end="2026-11-20")
    assert "2026-11-23" not in result["write_weeks"]
    assert cell_shift(result["state"], 7, 1, date(2026, 11, 23)) is None
    assert cell_shift(result["state"], 7, 1, date(2026, 11, 16))["start_time"] == "08:00"


def test_planning_does_not_mutate_the_supplied_state():
    state = empty_state()
    snapshot = {"patterns": list(state["patterns"]), "exceptions": list(state["exceptions"])}
    _apply(state)
    assert state["patterns"] == snapshot["patterns"]
    assert state["exceptions"] == snapshot["exceptions"]


def test_task_completion_history_is_not_part_of_a_schedule_edit():
    existing = [
        {"id": 1, "role": "floor_reset", "activity_status": "completed", "assignment_group_id": "g1"},
        {"id": 2, "role": "trash", "activity_status": "", "assignment_group_id": "g2"},
    ]
    plan = plan_task_links(existing, [{"role": "trash", "name": "Trash"}])
    assert [row["id"] for row in plan["preserved_history"]] == [1]
    assert plan["remove"] == []
    assert plan_task_links(existing, None)["unchanged"] is True
    kept = plan_task_links(existing, [{"role": "trash"}, {"role": "floor_reset"}])
    assert kept["add"] == []
    assert {row["id"] for row in kept["keep"]} == {1, 2}


def test_assignment_draft_keeps_completed_history_and_shared_groups():
    existing = [
        {
            "id": 9,
            "user_id": 19,
            "day_of_week": 1,
            "role": "floor_reset",
            "activity_status": "completed",
            "assignment_group_id": "shared-1",
        },
        {
            "id": 10,
            "user_id": 38,
            "day_of_week": 1,
            "role": "floor_reset",
            "activity_status": "",
            "assignment_group_id": "shared-1",
        },
    ]
    dropped = plan_assignment_draft(existing, [{"user_id": 61, "day_of_week": 1, "role": "trash"}])
    assert [row["id"] for row in dropped["preserved_history"]] == [9]
    assert [row["id"] for row in dropped["remove"]] == [10]
    assert dropped["add"][0]["role"] == "trash"
    kept = plan_assignment_draft(existing, None)
    assert kept["unchanged"] is True
    assert [row["id"] for row in kept["keep"]] == [9, 10]


def test_planner_segments_do_not_store_a_combined_gap_as_the_first_role():
    from backend.operations_planner_v2_store import planner_shift_assignments
    from backend.planned_weekly_schedule import role_assignments_storage

    maria = planner_shift_assignments(
        {
            "role": "fold,attendant",
            "role_assignments": [{"role": "attendant", "start_time": "14:00", "end_time": "16:00"}],
        }
    )
    assert [item["role"] for item in maria] == ["fold", "attendant"]
    assert maria[0]["full_shift"] is True
    assert maria[1]["full_shift"] is False
    stored = role_assignments_storage(maria)
    assert stored is not None
    assert "fold" not in stored
    assert "14:00" in stored
    plain = planner_shift_assignments({"role": "fold", "role_assignments": []})
    assert plain == [{"role": "fold", "full_shift": True}]
    assert role_assignments_storage(plain) is None


def test_blank_staffing_requirement_is_not_stored_as_zero():
    from backend.operations_planner_v2_store import StaffingRequirementError, normalize_staffing_requirement

    try:
        normalize_staffing_requirement({"role": "wash", "day_of_week": 1, "start_time": "05:00", "end_time": "13:00", "required_headcount": ""})
    except StaffingRequirementError as exc:
        assert "not zero" in str(exc)
    else:
        raise AssertionError("blank headcount was accepted")
    stored = normalize_staffing_requirement(
        {"role": "wash", "day_of_week": 1, "start_time": "05:00", "end_time": "13:00", "required_headcount": 0}
    )
    assert stored["required_headcount"] == 0
    assert stored["day_of_week"] == 1


def test_overlapping_staffing_intervals_are_rejected_before_save():
    from backend.operations_planner_v2_store import (
        StaffingRequirementError,
        reject_overlapping_staffing_requirements,
    )

    touching = [
        {"role": "fold", "day_of_week": 1, "start_time": "08:00", "end_time": "12:00"},
        {"role": "fold", "day_of_week": 1, "start_time": "12:00", "end_time": "16:00"},
    ]
    reject_overlapping_staffing_requirements(touching)
    different_roles = [
        {"role": "fold", "day_of_week": 1, "start_time": "08:00", "end_time": "12:00"},
        {"role": "wash", "day_of_week": 1, "start_time": "08:00", "end_time": "12:00"},
    ]
    reject_overlapping_staffing_requirements(different_roles)
    try:
        reject_overlapping_staffing_requirements(
            [
                {"role": "fold", "day_of_week": None, "start_time": "09:00", "end_time": "12:00"},
                {"role": "fold", "day_of_week": 1, "start_time": "11:00", "end_time": "13:00"},
            ]
        )
    except StaffingRequirementError as exc:
        assert "Overlapping" in str(exc)
    else:
        raise AssertionError("an every-day interval was allowed to cover a Monday interval")


def test_missing_planner_tables_are_reported_without_create():
    from backend.operations_planner_v2_store import PlannerSchemaNotApplied, require_schema, schema_status

    class MissingCursor:
        def execute(self, *_args, **_kwargs):
            return None

        def fetchone(self):
            return None

    status = schema_status(MissingCursor())
    assert status["ready"] is False
    assert "ops_planner_role_hours" in status["missing"]
    try:
        require_schema(MissingCursor())
    except PlannerSchemaNotApplied as exc:
        assert exc.missing
    else:
        raise AssertionError("missing tables must stop the request")


def test_a_failed_bulk_save_rolls_back_every_cell():
    written = []

    def work():
        written.append("first-employee")
        written.append("second-employee")
        raise ValueError("second employee failed")

    outcome = commit_or_rollback(work, lambda: written.append("commit"), lambda: written.clear())
    assert outcome["ok"] is False
    assert outcome["rolled_back"] is True
    assert written == []


def test_planner_does_not_create_the_task_table():
    from backend.operations_planner_v2_store import _sync_cell_tasks

    class Recording:
        def __init__(self):
            self.sql = []

        def execute(self, sql, *_args, **_kwargs):
            self.sql.append(str(sql))

        def fetchone(self):
            return None

    cursor = Recording()
    try:
        _sync_cell_tasks(None, cursor, 1, storage_week=ANCHOR, user_id=7, day_of_week=1, tasks=[{"role": "trash"}])
    except ValueError as exc:
        assert "will not create it" in str(exc)
    else:
        raise AssertionError("missing task table must stop the save")
    assert not any("CREATE TABLE" in sql.upper() for sql in cursor.sql)


def test_a_busy_planner_lock_is_not_treated_as_free():
    from backend.operations_planner_v2_store import acquire_lock

    class Busy:
        def execute(self, *_args, **_kwargs):
            return None

        def fetchone(self):
            return {"locked": 0}

    assert acquire_lock(Busy(), 4) is False


def test_repeating_scope_keeps_two_shifts_on_one_day():
    accepted = plan_cell_scopes(
        empty_state(),
        {
            "scope": "this_and_future",
            "anchor": ANCHOR,
            "today": TODAY,
            "include_published": False,
            "replace_exceptions": True,
            "horizon_weeks": 4,
            "cells": [
                {
                    "user_id": 7,
                    "day_of_week": 1,
                    "shifts": [_shift(), _shift(start_time="17:00", end_time="21:00", role="sort")],
                }
            ],
        },
    )
    assert accepted["ok"] is True
    later = cell_shifts(accepted["state"], 7, 1, NEXT)
    assert [item["start_time"] for item in later] == ["08:00", "17:00"]
    assert accepted["cell_plans"][0]["shifts"][1]["role"] == "sort"

    accepted = plan_cell_scopes(
        empty_state(),
        {
            "scope": "this_and_future",
            "anchor": ANCHOR,
            "today": TODAY,
            "include_published": False,
            "replace_exceptions": True,
            "horizon_weeks": 4,
            "cells": [{"user_id": 7, "day_of_week": 1, "shift": _shift()}],
        },
    )
    assert accepted["ok"] is True
    assert cell_shift(accepted["state"], 7, 1, NEXT)["start_time"] == "08:00"
    assert "2026-11-09" in accepted["preview"]["dates"]


def test_new_task_is_stored_on_the_schedule_week_not_the_display_monday(monkeypatch):
    """Monday Nov 23 is shown as that date and stored on Sunday Nov 22.

    Inserting the task on Nov 23 makes the week reload miss it, which is the
    production 'task list does not match' failure.
    """
    from backend.operations_planner_v2_store import add_assignments

    monkeypatch.setattr("backend.operations_planner_v2_store.table_exists", lambda _cursor, _table: True)
    monkeypatch.setattr(
        "backend.planned_weekly_schedule_responsibilities.ensure_responsibilities_table",
        lambda _cursor: None,
    )

    class Cursor:
        def __init__(self):
            self.calls = []
            self.lastrowid = 286

        def execute(self, sql, params=None):
            self.calls.append((" ".join(str(sql).split()), params))

        def fetchall(self):
            return []

        def fetchone(self):
            return None

    cursor = Cursor()
    result = add_assignments(
        cursor,
        3,
        date(2026, 11, 23),
        [{
            "user_id": 38,
            "day_of_week": 1,
            "role": "agroup_washer_and_floor_cleaning",
            "timing_mode": "specific_time",
            "start_time": "20:08",
            "end_time": "21:00",
        }],
    )
    inserts = [params for sql, params in cursor.calls if sql.startswith("INSERT INTO")]
    assert result["inserted"] == 1
    assert inserts[0][1] == date(2026, 11, 22)
    assert inserts[0][3] == 1
    assert inserts[0][8] == "20:08"
    assert inserts[0][9] == "21:00"
