"""Shared-assignment review cards and employee-vs-activity metrics."""

from backend.cleaning_task_activity import (
    CleaningTaskError,
    apply_rinse_task_dashboard_scope,
    approve_activity_ids,
    build_verification_review_cards,
    employee_participation_counts,
    reject_activity_ids,
)
from backend.planned_weekly_schedule_responsibilities import assignment_key


def _member(responsibility_id, user_id):
    return {
        "id": responsibility_id,
        "user_id": user_id,
        "role": "agroup_floor_washer",
        "assignment_group_id": "floor-group",
        "week_start": "2026-10-26",
        "day_of_week": 5,
        "timing_label": "9:00 AM",
    }


def _parent(activity_id, responsibility_id, user_id, status="completed"):
    return {
        "id": activity_id,
        "responsibility_id": responsibility_id,
        "user_id": user_id,
        "role": "agroup_floor_washer",
        "status": status,
        "parent_activity_id": None,
        "activity_kind": "group",
        "assignment_group_id": "floor-group",
        "started_at": "2026-10-31 09:05:00",
        "ended_at": "2026-10-31 09:36:00",
    }


def _child(activity_id, parent_id, user_id, role, status="pending_approval"):
    return {
        "id": activity_id,
        "parent_activity_id": parent_id,
        "user_id": user_id,
        "role": role,
        "status": status,
        "activity_kind": "group_item",
        "assignment_group_id": "floor-group",
        "started_at": "2026-10-31 09:35:55",
        "ended_at": "2026-10-31 09:35:55",
        "duration_seconds": None,
    }


def _pending_entry(member):
    return {
        "assignment_key": assignment_key(member),
        "responsibility_id": member["id"],
        "employee_id": member["user_id"],
        "employee_name": "Maria Perez" if member["user_id"] == 31 else "Rocio",
        "activity_group_label": "Floor & Washer",
        "timing_label": "9:00 AM",
        "role": "custom_check_washer_residue",
        "activity": {"id": 1, "status": "pending_approval"},
    }


TEMPLATES = {
    "agroup_floor_washer": [
        {"task_code": "custom_check_washer_residue", "required": True},
        {"task_code": "floor_cleaning", "required": True},
    ]
}
NAMES = {31: "Maria Perez", 57: "Rocio"}


def _cards(children, parents, members):
    by_resp = {int(parent["responsibility_id"]): parent for parent in parents}
    return build_verification_review_cards(
        [_pending_entry(member) for member in members],
        assignments=members,
        activities=[*parents, *children],
        by_resp=by_resp,
        names=NAMES,
        catalog={},
        templates_by_role=TEMPLATES,
    )


def test_two_employees_and_two_items_are_one_card():
    maria = _member(184, 31)
    rocio = _member(181, 57)
    parents = [_parent(96, 184, 31), _parent(95, 181, 57)]
    children = [
        _child(99, 96, 31, "custom_check_washer_residue"),
        _child(100, 96, 31, "floor_cleaning"),
        _child(97, 95, 57, "custom_check_washer_residue"),
        _child(98, 95, 57, "floor_cleaning"),
    ]
    cards = _cards(children, parents, [maria, rocio])
    assert len(cards) == 1
    card = cards[0]
    assert card["role_label"] == "Floor & Washer"
    assert card["pending_activity_ids"] == [99, 100, 97, 98]
    assert card["can_approve_all"] is True
    assert card["overall_status"] == "pending_verification"
    assert [row["participation_label"] for row in card["participation"]] == ["Finished", "Finished"]
    assert len(card["checklist"]) == 2
    assert all(item["checked_off"] for item in card["checklist"])
    assert len(card["checklist"][0]["records"]) == 2


def test_unfinished_partner_blocks_approval():
    maria = _member(184, 31)
    rocio = _member(181, 57)
    parents = [_parent(96, 184, 31)]
    children = [
        _child(99, 96, 31, "custom_check_washer_residue"),
        _child(100, 96, 31, "floor_cleaning"),
    ]
    card = _cards(children, parents, [maria, rocio])[0]
    assert card["participation"][1]["participation_status"] == "not_started"
    assert card["can_approve_all"] is False
    assert card["overall_status"] == "in_progress"
    assert "not all finished" in card["block_reason"]


def test_incomplete_checklist_blocks_approval():
    maria = _member(184, 31)
    rocio = _member(181, 57)
    parents = [_parent(96, 184, 31), _parent(95, 181, 57)]
    children = [
        _child(99, 96, 31, "custom_check_washer_residue"),
        _child(100, 96, 31, "floor_cleaning"),
        _child(97, 95, 57, "custom_check_washer_residue"),
    ]
    card = _cards(children, parents, [maria, rocio])[0]
    assert card["can_approve_all"] is False
    assert "checklist" in card["block_reason"]


def test_rejected_item_blocks_overall_verification():
    maria = _member(184, 31)
    rocio = _member(181, 57)
    parents = [_parent(96, 184, 31), _parent(95, 181, 57)]
    children = [
        _child(99, 96, 31, "custom_check_washer_residue", status="rejected"),
        _child(100, 96, 31, "floor_cleaning"),
        _child(97, 95, 57, "custom_check_washer_residue"),
        _child(98, 95, 57, "floor_cleaning"),
    ]
    card = _cards(children, parents, [maria, rocio])[0]
    assert card["overall_status"] == "needs_correction"
    assert card["can_approve_all"] is False


def test_employee_counts_are_not_assignment_counts():
    assigned, started = employee_participation_counts(
        [
            {
                "completion_status": "completed",
                "contributions": [
                    {"participation_status": "finished"},
                    {"participation_status": "finished"},
                ],
            }
        ]
    )
    assert assigned == 2
    assert started == 2


def test_repeated_approval_does_not_verify_twice(monkeypatch):
    calls = []
    store = {
        97: {"id": 97, "status": "pending_approval", "user_id": 57, "assignment_group_id": None},
    }

    def fake_get(cursor, org, activity_id):
        return dict(store[int(activity_id)])

    def fake_approve(cursor, *, organization_id, activity_id, supervisor_user_id):
        calls.append(int(activity_id))
        store[int(activity_id)]["status"] = "approved"
        return {"id": int(activity_id), "status": "approved"}

    monkeypatch.setattr("backend.cleaning_task_activity.get_activity", fake_get)
    monkeypatch.setattr("backend.cleaning_task_activity.approve_activity", fake_approve)
    monkeypatch.setattr("backend.cleaning_task_activity._role_catalog", lambda cursor, org: {})
    monkeypatch.setattr(
        "backend.cleaning_task_activity.serialize_activity",
        lambda row, catalog=None: {"id": row["id"], "status": row["status"]},
    )
    first = approve_activity_ids(
        None, organization_id=3, activity_ids=[97, 97], supervisor_user_id=15, approve_all=False
    )
    second = approve_activity_ids(
        None, organization_id=3, activity_ids=[97], supervisor_user_id=15, approve_all=False
    )
    assert calls == [97]
    assert first[0]["status"] == "approved"
    assert second[0]["status"] == "approved"


def test_rinse_counts_employees_and_hides_labor_and_audit():
    out = apply_rinse_task_dashboard_scope(
        {
            "shared_assignments": [
                {
                    "completion_status": "completed",
                    "verification_status": "verified",
                    "overall_status": "verified",
                    "checklist_complete": True,
                    "contributions": [
                        {
                            "participation_status": "finished",
                            "status": "approved",
                            "activity": {
                                "id": 1,
                                "completion_source": "pin",
                                "duration_seconds": 100,
                                "status": "approved",
                            },
                        },
                        {
                            "participation_status": "finished",
                            "status": "approved",
                            "activity": {
                                "id": 2,
                                "completion_source": "pin",
                                "duration_seconds": 90,
                                "status": "approved",
                            },
                        },
                    ],
                }
            ],
            "activity_log": [{"id": 1, "completion_source": "corrected"}],
            "metrics": {},
        }
    )
    assert out["metrics"]["employees_assigned"] == 2
    assert out["metrics"]["employees_started"] == 2
    assert out["metrics"]["completed_activities"] == 1
    assert out["metrics"]["verified_activities"] == 1
    assert out["metrics"]["total_assigned"] == 1
    assert out["activity_log"] == []
    assert out["durations"] == []
    assert "duration_seconds" not in out["shared_assignments"][0]["contributions"][0]["activity"]


def test_needs_redo_requires_a_reason():
    try:
        reject_activity_ids(
            None, organization_id=3, activity_ids=[97], supervisor_user_id=15, reason="no"
        )
    except CleaningTaskError as exc:
        assert exc.status == 400
    else:
        raise AssertionError("short reason was accepted")
