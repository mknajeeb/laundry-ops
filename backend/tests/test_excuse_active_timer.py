"""Excusal waits for an open timer to be ended with the recorded times."""

from datetime import datetime
import inspect

import pytest

from backend.cleaning_task_activity import (
    CleaningTaskError,
    _shared_partner_rows,
    build_verification_review_cards,
)
from backend.cleaning_task_dashboard_analytics import build_employee_report
from backend.cleaning_task_record_management import plan_participation_sessions
from backend.cleaning_task_shared_execution import (
    excuse_or_reassign_participant,
    item_acknowledgments_satisfied,
    participation_timer_is_active,
)


def test_not_started_and_closed_sessions_are_not_active_timers():
    assert participation_timer_is_active(None) is False
    assert participation_timer_is_active({"status": "completed", "started_at": "2026-11-05 09:00:00", "ended_at": "2026-11-05 09:18:00", "duration_seconds": 1080}) is False
    assert participation_timer_is_active({"status": "in_progress", "started_at": "2026-11-05 13:50:00", "ended_at": None, "duration_seconds": None}) is True


def test_active_timer_is_refused_before_any_excuse_write(monkeypatch):
    monkeypatch.setattr("backend.cleaning_task_shared_execution.ensure_shared_activity_schema", lambda _cursor: None)
    monkeypatch.setattr(
        "backend.cleaning_task_shared_execution.get_shared_session",
        lambda *_args, **_kwargs: {"id": 4, "participation_adjustments_json": "[]"},
    )
    monkeypatch.setattr(
        "backend.cleaning_task_shared_execution.open_participation_activity",
        lambda *_args, **_kwargs: {
            "id": 8,
            "status": "in_progress",
            "started_at": datetime(2026, 11, 5, 13, 50),
            "ended_at": None,
            "duration_seconds": None,
        },
    )

    class Cursor:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("an open timer must not be excused or rewritten")

    with pytest.raises(CleaningTaskError) as raised:
        excuse_or_reassign_participant(
            Cursor(),
            organization_id=3,
            actor_user_id=1,
            shared_session_id=4,
            employee_user_id=3,
            reason="Sam left mid-task",
        )
    assert raised.value.status == 409
    assert raised.value.payload["code"] == "active_timer"
    assert raised.value.payload["started_at"] == "2026-11-05 13:50:00"


def test_ending_the_recorded_session_uses_only_the_given_times():
    plan = plan_participation_sessions(
        "finished",
        [{"started_at": datetime(2026, 11, 5, 13, 50), "ended_at": datetime(2026, 11, 5, 14, 5)}],
    )
    assert plan["duration_seconds"] == 15 * 60
    assert plan["started_at"] == datetime(2026, 11, 5, 13, 50)
    assert plan["ended_at"] == datetime(2026, 11, 5, 14, 5)


def test_excuse_does_not_write_duration_or_acknowledgments():
    source = inspect.getsource(excuse_or_reassign_participant)
    assert "duration_seconds" not in source
    assert "participation_sessions_json" not in source


def test_excused_partner_is_not_working_and_remaining_acknowledgments_stay_required():
    rows = _shared_partner_rows(
        {
            "execution_mode": "shared",
            "user_ids": [2, 3],
            "members": [{"id": 10, "user_id": 2}, {"id": 11, "user_id": 3}],
        },
        2,
        {3: "Sam"},
        {11: {"status": "in_progress"}},
        {3},
    )
    assert rows == [
        {"user_id": 3, "name": "Sam", "state": "excused", "state_label": "Excused"},
    ]
    assert item_acknowledgments_satisfied(["excused"]) is False
    assert item_acknowledgments_satisfied(["completed", "excused"]) is True
    assert item_acknowledgments_satisfied(["pending", "excused"]) is False


def test_review_and_employee_report_call_an_ended_excused_person_excused():
    cards = build_verification_review_cards(
        [{"assignment_key": "g:None:None:grp", "role": "agroup_floor", "role_label": "Floor"}],
        assignments=[{"id": 11, "user_id": 3, "assignment_group_id": "grp", "role": "agroup_floor"}],
        activities=[],
        by_resp={11: {"id": 8, "status": "completed", "started_at": "2026-11-05 13:50:00", "ended_at": "2026-11-05 14:05:00", "parent_activity_id": None}},
        names={3: "Sam"},
        catalog={},
        excused_by_group={"grp": {3}},
    )
    person = cards[0]["participation"][0]
    assert person["participation_status"] == "excused"
    assert person["participation_label"] == "Excused"
    assert person["started_at"] == "2026-11-05 13:50:00"
    assert person["finished_at"] == "2026-11-05 14:05:00"
    assert cards[0]["overall_status"] != "in_progress"

    report = build_employee_report(
        [
            {
                "assignment_key": "g:1",
                "role_label": "Floor",
                "business_date": "2026-11-05",
                "verification_eligible": False,
                "verification_status": "not_required",
                "verification_label": "Not Required",
                "contributions": [
                    {
                        "employee_id": 3,
                        "employee_name": "Sam",
                        "participation_status": "excused",
                        "activity": {"started_at": "2026-11-05 13:50:00", "ended_at": "2026-11-05 14:05:00", "duration_seconds": 900},
                    }
                ],
            }
        ]
    )
    sam = report["employees"][0]
    assert sam["excused"] == 1
    assert sam["in_progress"] == 0
    assert sam["not_started"] == 0
    assert sam["activities"][0]["status"] == "excused"
    assert sam["activities"][0]["duration_seconds"] == 900
