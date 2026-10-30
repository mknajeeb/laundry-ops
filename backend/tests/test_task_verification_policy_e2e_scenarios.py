"""Release scenarios for Task verification Phases 1–2 (isolated, no production I/O)."""

from __future__ import annotations

from datetime import date, datetime
from unittest import mock

import pytest

from backend.cleaning_task_activity import (
    STATUS_APPROVED,
    STATUS_PENDING_APPROVAL,
    STATUS_REJECTED,
    CleaningTaskError,
    approve_activity,
    assignment_is_verified,
    reject_activity,
    user_can_verify_activity,
    verification_status_from_subjects,
    VERIFICATION_PARTIAL,
    VERIFICATION_VERIFIED,
    VERIFICATION_WAITING,
)
from backend.task_catalog import VERIFY_NONE, VERIFY_SUPERVISOR
from backend.task_verification_policy import (
    get_global_verification_policy,
    resolve_verification_policy,
    snapshot_columns,
    upsert_global_verification_policy,
)


class _PolicyCursor:
    """Minimal in-memory cursor for policy + independence scenarios."""

    def __init__(self):
        self.org_settings = {}
        self.responsibilities = []
        self.activities = []
        self.events = []
        self._fetch = None
        self._fetchall = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        text = " ".join(str(sql).split()).lower()
        params = list(params or [])
        if text.startswith("create table") or text.startswith("alter table"):
            self._fetch = None
            self._fetchall = []
            return
        if "from task_verification_org_settings" in text:
            self._fetch = self.org_settings.get(int(params[0]))
            return
        if text.startswith("insert into task_verification_org_settings"):
            self.org_settings[int(params[0])] = {
                "organization_id": int(params[0]),
                "verification_required": params[1],
                "verification_method": params[2],
                "verification_timing": params[3],
                "verifier_config_json": params[4],
                "updated_by_user_id": params[5],
            }
            return
        if "from planned_weekly_schedule_responsibilities" in text:
            gid = params[1]
            self._fetchall = [
                r for r in self.responsibilities if str(r.get("assignment_group_id")) == str(gid)
            ]
            return
        if "from cleaning_task_activities" in text and "assignment_group_id" in text and "business_date" in text:
            gid, day = params[1], params[2]
            self._fetchall = [
                r
                for r in self.activities
                if str(r.get("assignment_group_id")) == str(gid)
                and str(r.get("business_date"))[:10] == str(day)[:10]
            ]
            return
        if "from cleaning_task_activities" in text and "and id = %s" in text:
            aid = int(params[1])
            self._fetch = next((a for a in self.activities if int(a["id"]) == aid), None)
            return
        if text.startswith("update cleaning_task_activities"):
            aid = int(params[-2])
            for a in self.activities:
                if int(a["id"]) == aid:
                    a["status"] = params[0]
                    a["approved_by_user_id"] = params[1]
                    a["approved_at"] = params[2]
                    if len(params) >= 6 and "rejection_reason" in text:
                        a["rejection_reason"] = params[3]
                    else:
                        a["rejection_reason"] = None
                    self.rowcount = 1
                    break
            return
        if text.startswith("insert into cleaning_task_activity_events"):
            self.events.append({"params": params})
            return
        self._fetch = None
        self._fetchall = []

    def fetchone(self):
        return self._fetch

    def fetchall(self):
        return list(self._fetchall)


@pytest.fixture
def policy_env():
    cur = _PolicyCursor()
    with mock.patch("backend.task_verification_policy.table_exists", return_value=True), mock.patch(
        "backend.task_verification_policy.table_has_column", return_value=True
    ), mock.patch("backend.task_verification_policy.invalidate_schema_cache"):
        yield cur


def test_new_group_inherits_global_supervisor(policy_env):
    cur = policy_env
    upsert_global_verification_policy(
        cur,
        3,
        {
            "verification_method": "supervisor",
            "verification_required": True,
            "verification_timing": "same_shift",
        },
    )
    group = {"verification_inherits": True}
    resolved = resolve_verification_policy(cur, 3, activity_group=group)
    assert resolved["verification_method"] == VERIFY_SUPERVISOR
    assert resolved["verification_required"] is True
    assert resolved["source"] == "global"
    snap = snapshot_columns(resolved)
    assert snap["verification_method"] == VERIFY_SUPERVISOR


def test_group_level_override(policy_env):
    cur = policy_env
    upsert_global_verification_policy(
        cur, 3, {"verification_method": "supervisor", "verification_required": True}
    )
    group = {
        "verification_inherits": False,
        "verification_required": True,
        "verification_method": "employee",
        "verification_timing": "next_day",
        "verifier_config": {"user_ids": [99]},
    }
    resolved = resolve_verification_policy(cur, 3, activity_group=group)
    assert resolved["verification_method"] == "employee"
    assert resolved["verification_timing"] == "next_day"
    assert resolved["source"] == "activity_group"


def test_task_level_override_beats_group(policy_env):
    cur = policy_env
    group = {
        "verification_inherits": False,
        "verification_required": True,
        "verification_method": "employee",
        "verification_timing": "same_shift",
    }
    task = {
        "code": "lint_cleaning",
        "verification_inherits": False,
        "verification_required": False,
        "verification_method": VERIFY_NONE,
        "verification_timing": "same_shift",
    }
    resolved = resolve_verification_policy(
        cur, 3, activity_group=group, task_definition=task
    )
    assert resolved["verification_required"] is False
    assert resolved["verification_method"] == VERIFY_NONE
    assert resolved["source"] == "task"


def test_shared_assignment_solo_vs_multi_participant_ids(policy_env):
    cur = policy_env
    cur.responsibilities = [
        {"user_id": 53, "assignment_group_id": "solo-g"},
        {"user_id": 16, "assignment_group_id": "shared-g"},
        {"user_id": 51, "assignment_group_id": "shared-g"},
    ]
    from backend.task_verification_policy import shared_assignment_participant_user_ids

    solo = shared_assignment_participant_user_ids(
        cur, organization_id=3, assignment_group_id="solo-g", business_date=date(2026, 10, 30)
    )
    shared = shared_assignment_participant_user_ids(
        cur, organization_id=3, assignment_group_id="shared-g", business_date=date(2026, 10, 30)
    )
    assert solo == {53}
    assert shared == {16, 51}


def _pending(uid, aid, gid="shared-g"):
    return {
        "id": aid,
        "organization_id": 3,
        "user_id": uid,
        "status": STATUS_PENDING_APPROVAL,
        "assignment_group_id": gid,
        "business_date": date(2026, 10, 30),
        "role": "lint_cleaning",
        "verification_required": 1,
        "verification_method": "supervisor",
        "timing_mode": "anytime",
        "started_at": "2026-10-30 09:00:00",
    }


def test_pin_and_management_self_and_co_participant_blocked(policy_env):
    cur = policy_env
    cur.responsibilities = [
        {"user_id": 16, "assignment_group_id": "shared-g"},
        {"user_id": 51, "assignment_group_id": "shared-g"},
    ]
    cur.activities = [_pending(51, 80), _pending(16, 79)]

    # PIN-style auth check
    assert not user_can_verify_activity(
        cur, organization_id=3, activity=cur.activities[0], verifier_user_id=51, has_supervisor_review=True
    )
    assert not user_can_verify_activity(
        cur, organization_id=3, activity=cur.activities[0], verifier_user_id=16, has_supervisor_review=True
    )
    assert user_can_verify_activity(
        cur, organization_id=3, activity=cur.activities[0], verifier_user_id=15, has_supervisor_review=True
    )

    with mock.patch("backend.cleaning_task_activity._role_catalog", return_value={}), mock.patch(
        "backend.cleaning_task_activity.serialize_activity", side_effect=lambda r, catalog=None: dict(r)
    ), mock.patch(
        "backend.cleaning_task_activity.eastern_now_naive",
        return_value=datetime(2026, 10, 30, 12, 0, 0),
    ):
        with pytest.raises(CleaningTaskError) as self_exc:
            approve_activity(cur, organization_id=3, activity_id=80, supervisor_user_id=51)
        assert self_exc.value.status == 403

        with pytest.raises(CleaningTaskError) as co_exc:
            approve_activity(cur, organization_id=3, activity_id=80, supervisor_user_id=16)
        assert co_exc.value.status == 403
        assert cur.activities[0]["status"] == STATUS_PENDING_APPROVAL

        # Independent management/PIN supervisor
        out = approve_activity(cur, organization_id=3, activity_id=80, supervisor_user_id=15)
        assert cur.activities[0]["status"] == STATUS_APPROVED
        assert cur.activities[0]["approved_by_user_id"] == 15
        assert cur.events  # audited


def test_reject_and_request_correction_independent_only(policy_env):
    cur = policy_env
    cur.responsibilities = [
        {"user_id": 16, "assignment_group_id": "shared-g"},
        {"user_id": 51, "assignment_group_id": "shared-g"},
    ]
    cur.activities = [_pending(51, 80)]
    with mock.patch("backend.cleaning_task_activity._role_catalog", return_value={}), mock.patch(
        "backend.cleaning_task_activity.serialize_activity", side_effect=lambda r, catalog=None: dict(r)
    ), mock.patch(
        "backend.cleaning_task_activity.eastern_now_naive",
        return_value=datetime(2026, 10, 30, 12, 0, 0),
    ):
        with pytest.raises(CleaningTaskError):
            reject_activity(
                cur, organization_id=3, activity_id=80, supervisor_user_id=16, reason="Needs redo"
            )
        out = reject_activity(
            cur, organization_id=3, activity_id=80, supervisor_user_id=15, reason="Needs redo"
        )
        assert cur.activities[0]["status"] == STATUS_REJECTED
        assert cur.activities[0]["rejection_reason"] == "Needs redo"


def test_group_verified_only_when_all_required_items_approved():
    waiting = verification_status_from_subjects(
        [
            {"status": STATUS_APPROVED, "verification_required": True, "verification_method": "supervisor"},
            {"status": STATUS_PENDING_APPROVAL, "verification_required": True, "verification_method": "supervisor"},
        ]
    )
    assert waiting == VERIFICATION_PARTIAL

    verified = verification_status_from_subjects(
        [
            {"status": STATUS_APPROVED, "verification_required": True, "verification_method": "supervisor"},
            {"status": STATUS_APPROVED, "verification_required": True, "verification_method": "supervisor"},
        ]
    )
    assert verified == VERIFICATION_VERIFIED

    row = {
        "completion_status": "completed",
        "contributions": [
            {
                "status": "approved",
                "group_items": [
                    {
                        "status": STATUS_APPROVED,
                        "verification_required": True,
                        "verification_method": "supervisor",
                    },
                    {
                        "status": STATUS_PENDING_APPROVAL,
                        "verification_required": True,
                        "verification_method": "supervisor",
                    },
                ],
            }
        ],
    }
    assert assignment_is_verified(row) is False

    row["contributions"][0]["group_items"][1]["status"] = STATUS_APPROVED
    assert assignment_is_verified(row) is True


def test_historical_snapshot_not_rewritten_by_later_global_change(policy_env):
    cur = policy_env
    upsert_global_verification_policy(
        cur, 3, {"verification_method": "supervisor", "verification_required": True}
    )
    snap_at_start = snapshot_columns(resolve_verification_policy(cur, 3, task_definition={
        "code": "lint_cleaning",
        "verification_inherits": True,
    }))
    # Later config change
    upsert_global_verification_policy(
        cur, 3, {"verification_method": "none", "verification_required": False}
    )
    # Historical activity retains snapshotted columns
    historical = {
        "id": 79,
        "user_id": 16,
        "status": STATUS_PENDING_APPROVAL,
        "verification_required": snap_at_start["verification_required"],
        "verification_method": snap_at_start["verification_method"],
        "assignment_group_id": None,
    }
    assert historical["verification_method"] == VERIFY_SUPERVISOR
    assert historical["status"] == STATUS_PENDING_APPROVAL
    # New resolution would be none, but activity row unchanged
    new_policy = resolve_verification_policy(cur, 3, task_definition={
        "code": "lint_cleaning",
        "verification_inherits": True,
    })
    assert new_policy["verification_method"] == VERIFY_NONE
    assert historical["verification_method"] != new_policy["verification_method"]
