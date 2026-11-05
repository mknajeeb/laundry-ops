"""Schedule-role verification stays separate from account-role verification."""

from datetime import date

from backend.planned_weekly_schedule_responsibilities import _inactive_activity_group_assignment_error
from backend.cleaning_task_activity import (
    resolve_unassigned_schedule_verification,
    user_can_verify_activity,
    verification_schedule_date,
)
from backend.task_catalog import VERIFY_ROLE, VERIFY_SCHEDULE_ROLE
from backend.task_verification_policy import VerificationPolicyError, _normalize_policy_fields


def test_inactive_activity_group_cannot_be_selected_for_a_new_assignment(monkeypatch):
    monkeypatch.setattr(
        "backend.task_activity_groups.get_activity_group",
        lambda *args, **kwargs: {"name": "SMOKE TVP", "active": False},
    )
    blocked = _inactive_activity_group_assignment_error(
        None, 1, "agroup_smoke_tvp_tvp_smoke_35a98f05", already_assigned=False
    )
    assert blocked and "inactive" in blocked
    assert (
        _inactive_activity_group_assignment_error(
            None, 1, "agroup_smoke_tvp_tvp_smoke_35a98f05", already_assigned=True
        )
        is None
    )
    assert _inactive_activity_group_assignment_error(None, 1, "fold", already_assigned=False) is None


def test_next_day_uses_the_verification_date():
    closing = date(2026, 11, 5)
    opening = date(2026, 11, 6)
    assert verification_schedule_date("next_day", closing, opening) == opening
    assert verification_schedule_date("same_shift", closing, closing) == closing


def test_account_role_verification_still_uses_permission_roles(monkeypatch):
    monkeypatch.setattr(
        "backend.task_verification_policy.verifier_is_shared_co_participant",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "backend.cleaning_task_activity._task_meta_for_role",
        lambda *args, **kwargs: {},
    )
    activity = {
        "user_id": 2,
        "status": "pending_approval",
        "verification_method": VERIFY_ROLE,
        "verification_required": 1,
        "verifier_config": {"roles": ["MANAGER"]},
    }
    assert user_can_verify_activity(
        None,
        organization_id=3,
        activity=activity,
        verifier_user_id=4,
        verifier_roles=["MANAGER"],
        has_supervisor_review=False,
    )
    assert user_can_verify_activity(
        None,
        organization_id=3,
        activity=activity,
        verifier_user_id=9,
        verifier_roles=["EMPLOYEE"],
        has_supervisor_review=True,
    )


def test_schedule_role_allows_only_the_assigned_non_participant(monkeypatch):
    monkeypatch.setattr(
        "backend.task_verification_policy.verifier_is_shared_co_participant",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "backend.cleaning_task_activity.activity_participant_ids",
        lambda *args, **kwargs: {2},
    )
    monkeypatch.setattr(
        "backend.cleaning_task_activity.users_assigned_schedule_role",
        lambda *args, **kwargs: {4, 2},
    )
    monkeypatch.setattr(
        "backend.cleaning_task_activity._task_meta_for_role",
        lambda *args, **kwargs: {},
    )
    activity = {
        "user_id": 2,
        "status": "pending_approval",
        "verification_method": VERIFY_SCHEDULE_ROLE,
        "verification_timing": "next_day",
        "verification_required": 1,
        "business_date": date(2026, 11, 5),
        "verifier_config": {"schedule_role": "attendant"},
    }
    assert user_can_verify_activity(
        None,
        organization_id=3,
        activity=activity,
        verifier_user_id=4,
        has_supervisor_review=False,
        as_of=date(2026, 11, 6),
    )
    assert not user_can_verify_activity(
        None,
        organization_id=3,
        activity=activity,
        verifier_user_id=9,
        has_supervisor_review=True,
        as_of=date(2026, 11, 6),
    )
    assert not user_can_verify_activity(
        None,
        organization_id=3,
        activity=activity,
        verifier_user_id=2,
        has_supervisor_review=True,
        as_of=date(2026, 11, 6),
    )


def test_schedule_role_requires_an_explicit_role():
    try:
        _normalize_policy_fields(
            verification_required=True,
            verification_method="schedule_role",
            verification_timing="next_day",
            verifier_config={},
        )
    except VerificationPolicyError as exc:
        assert "schedule role" in exc.message
    else:
        raise AssertionError("missing schedule role was accepted")
    saved = _normalize_policy_fields(
        verification_required=True,
        verification_method="schedule_role",
        verification_timing="next_day",
        verifier_config={"schedule_role": "Attendant", "roles": ["MANAGER"]},
    )
    assert saved["verification_method"] == "schedule_role"
    assert saved["verifier_config"]["schedule_role"] == "attendant"
    assert saved["verifier_config"]["roles"] == ["MANAGER"]


def test_unassigned_resolution_requires_a_reason_and_refuses_when_someone_is_eligible(monkeypatch):
    monkeypatch.setattr(
        "backend.cleaning_task_activity.get_activity",
        lambda cursor, org, activity_id: {
            "id": activity_id,
            "user_id": 2,
            "status": "pending_approval",
            "verification_method": "schedule_role",
            "verification_timing": "next_day",
            "business_date": date(2026, 11, 5),
            "role": "agroup_closing",
            "verifier_config": {"schedule_role": "attendant"},
        },
    )
    monkeypatch.setattr(
        "backend.cleaning_task_activity.assert_independent_verifier",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "backend.cleaning_task_activity.users_assigned_schedule_role",
        lambda *args, **kwargs: {4},
    )
    monkeypatch.setattr(
        "backend.cleaning_task_activity.activity_participant_ids",
        lambda *args, **kwargs: {2},
    )
    monkeypatch.setattr(
        "backend.cleaning_task_activity._task_meta_for_role",
        lambda *args, **kwargs: {},
    )
    try:
        resolve_unassigned_schedule_verification(
            None,
            organization_id=3,
            activity_id=8,
            manager_user_id=5,
            reason="no",
            as_of=date(2026, 11, 6),
            has_supervisor_review=True,
        )
    except Exception as exc:
        assert getattr(exc, "status", None) == 400
    else:
        raise AssertionError("short reason was accepted")
    try:
        resolve_unassigned_schedule_verification(
            None,
            organization_id=3,
            activity_id=8,
            manager_user_id=5,
            reason="Opening attendant is assigned",
            as_of=date(2026, 11, 6),
            has_supervisor_review=True,
        )
    except Exception as exc:
        assert getattr(exc, "status", None) == 409
    else:
        raise AssertionError("resolution bypassed an eligible verifier")


def test_resolution_records_an_audit_event_when_nobody_is_eligible(monkeypatch):
    events = []
    monkeypatch.setattr(
        "backend.cleaning_task_activity.get_activity",
        lambda cursor, org, activity_id: {
            "id": activity_id,
            "user_id": 2,
            "status": "pending_approval",
            "verification_method": "schedule_role",
            "verification_timing": "next_day",
            "business_date": date(2026, 11, 5),
            "role": "agroup_closing",
            "verifier_config": {"schedule_role": "attendant"},
        },
    )
    monkeypatch.setattr(
        "backend.cleaning_task_activity.assert_independent_verifier",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "backend.cleaning_task_activity.users_assigned_schedule_role",
        lambda *args, **kwargs: set(),
    )
    monkeypatch.setattr(
        "backend.cleaning_task_activity.activity_participant_ids",
        lambda *args, **kwargs: {2},
    )
    monkeypatch.setattr(
        "backend.cleaning_task_activity._task_meta_for_role",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        "backend.cleaning_task_activity.approve_activity",
        lambda cursor, **kwargs: {"id": kwargs["activity_id"], "status": "approved", "business_date": "2026-11-05"},
    )
    monkeypatch.setattr(
        "backend.cleaning_task_activity._record_event",
        lambda cursor, **kwargs: events.append(kwargs),
    )
    approved = resolve_unassigned_schedule_verification(
        None,
        organization_id=3,
        activity_id=8,
        manager_user_id=5,
        reason="No opening employee is scheduled",
        as_of=date(2026, 11, 6),
        has_supervisor_review=True,
    )
    assert approved["status"] == "approved"
    assert approved["business_date"] == "2026-11-05"
    assert events[0]["event_type"] == "schedule_verifier_unassigned_resolved"
    assert events[0]["payload"]["schedule_role"] == "attendant"
    assert events[0]["payload"]["verification_date"] == "2026-11-06"
    assert events[0]["payload"]["original_business_date"] == "2026-11-05"
