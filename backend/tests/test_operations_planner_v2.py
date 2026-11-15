"""Recurrence, publication, coverage, and access rules for Operations Planner v2."""

from __future__ import annotations

from datetime import date, timedelta

from backend.operations_planner_v2 import (
    approve_weeks,
    break_overlap_warnings,
    cell_shift,
    employee_module_visible,
    employee_schedule_view,
    employee_visible_snapshot,
    empty_state,
    hour_coverage,
    patterns_overlap,
    paystub_decision,
    plan_change,
    plan_entry_write,
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
        "tasks": [{"name": "Floor reset", "shared": False, "category": "cleaning"}],
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
