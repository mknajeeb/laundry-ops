"""Release-candidate rules that do not need a database."""

from datetime import date

import pytest

from backend.cleaning_task_activity import CleaningTaskError, shift_boundary_reached, verification_queue_decision
from backend.cleaning_task_manual_completion import record_manual_completion
from backend.cleaning_task_shared_execution import (
    item_acknowledgments_satisfied,
    normalize_acknowledgment_mode,
    required_acknowledger_ids,
)
from backend.task_schema_prep import EXPECTED_COLUMNS


def test_acknowledgment_modes_stay_on_the_personal_check_model():
    assert normalize_acknowledgment_mode(None) == "any"
    assert normalize_acknowledgment_mode("each") == "each"
    assert required_acknowledger_ids(
        acknowledgment_mode="any",
        responsibility_mode="named",
        responsibility_user_ids=[2, 3],
        assigned_user_ids=[2, 3, 4],
    ) == []
    assert required_acknowledger_ids(
        acknowledgment_mode="each",
        responsibility_mode="named",
        responsibility_user_ids=[2, 9],
        assigned_user_ids=[2, 3],
    ) == [2]
    assert required_acknowledger_ids(
        acknowledgment_mode="each",
        responsibility_mode="team",
        responsibility_user_ids=[],
        assigned_user_ids=[2, 3],
    ) == [2, 3]


def test_excused_acknowledgment_does_not_count_as_completed_work():
    assert item_acknowledgments_satisfied(["completed", "excused"]) is True
    assert item_acknowledgments_satisfied(["excused", "excused"]) is False
    assert item_acknowledgments_satisfied(["pending", "excused"]) is False


def test_mysql_time_values_keep_hours_before_ten():
    from datetime import timedelta

    from backend.cleaning_task_activity import _minutes, _serialize_time

    assert _serialize_time(timedelta(hours=6)) == "06:00"
    assert _minutes(_serialize_time(timedelta(hours=6))) == 360
    assert _minutes(_serialize_time(timedelta(hours=23, minutes=59))) == 23 * 60 + 59


def test_later_shift_waits_for_the_scheduled_end_and_next_day_is_previous_shift():
    assert shift_boundary_reached(14 * 60, 5 * 60, 13 * 60) is True
    assert shift_boundary_reached(12 * 60, 5 * 60, 13 * 60) is False
    assert shift_boundary_reached(12 * 60, None, None) is False
    same_day = verification_queue_decision(
        timing="later_shift",
        business_date=date(2026, 11, 5),
        as_of=date(2026, 11, 5),
        now_minutes=10 * 60,
        shift_start_minutes=5 * 60,
        shift_end_minutes=13 * 60,
    )
    assert same_day["eligible"] is False
    later = verification_queue_decision(
        timing="later_shift",
        business_date=date(2026, 11, 5),
        as_of=date(2026, 11, 5),
        now_minutes=14 * 60,
        shift_start_minutes=5 * 60,
        shift_end_minutes=13 * 60,
    )
    assert later["eligible"] is True
    overdue = verification_queue_decision(
        timing="later_shift",
        business_date=date(2026, 11, 4),
        as_of=date(2026, 11, 5),
    )
    assert overdue["eligible"] is True
    assert overdue["verification_overdue"] is True
    assert overdue["queue_kind"] == "previous_shift"
    hidden = verification_queue_decision(
        timing="next_day",
        business_date=date(2026, 11, 5),
        as_of=date(2026, 11, 5),
    )
    assert hidden["eligible"] is False
    previous = verification_queue_decision(
        timing="next_day",
        business_date=date(2026, 11, 4),
        as_of=date(2026, 11, 5),
    )
    assert previous["queue_kind"] == "previous_shift"
    assert previous["verification_overdue"] is True


def test_manual_completion_refuses_item_acknowledgments_without_the_explicit_flag():
    with pytest.raises(CleaningTaskError):
        record_manual_completion(
            None,
            None,
            organization_id=1,
            supervisor_user_id=9,
            responsibility_id=1,
            employee_user_id=2,
            completed_at=None,
            reason="done outside the app",
            shared_item_completions=[{"task_code": "floor", "completed_by_user_id": 2}],
        )


def test_schema_expectation_does_not_add_a_participation_sessions_table():
    assert "participation_sessions" not in EXPECTED_COLUMNS
    assert "participation_sessions_json" in EXPECTED_COLUMNS["cleaning_task_activities"]
    assert "cleaning_task_shared_item_checks" in EXPECTED_COLUMNS
