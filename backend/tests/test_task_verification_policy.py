"""Phase 1–2: independent verification + global/group/task policy hierarchy."""

from __future__ import annotations

from datetime import date
from unittest import mock

import pytest

from backend.cleaning_task_activity import (
    STATUS_PENDING_APPROVAL,
    CleaningTaskError,
    approve_activity,
    assert_independent_verifier,
    reject_activity,
    user_can_verify_activity,
)
from backend.task_catalog import VERIFY_NONE, VERIFY_SUPERVISOR
from backend.task_verification_policy import (
    DEFAULT_GLOBAL_POLICY,
    get_global_verification_policy,
    resolve_verification_policy,
    snapshot_columns,
    upsert_global_verification_policy,
    verifier_is_shared_co_participant,
)


class _MemCursor:
    def __init__(self):
        self.tables = set()
        self.org_settings = {}
        self.responsibilities = []
        self.activities = []
        self.columns = set()
        self._fetch = None
        self._fetchall = []
        self.executed = []
        self.lastrowid = 0
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        text = " ".join(str(sql).split()).lower()
        if text.startswith("create table"):
            if "task_verification_org_settings" in text:
                self.tables.add("task_verification_org_settings")
            self._fetch = None
            self._fetchall = []
            return
        if text.startswith("alter table"):
            self.columns.add(text)
            return
        if "from task_verification_org_settings" in text and "where organization_id" in text:
            oid = int(params[0])
            self._fetch = self.org_settings.get(oid)
            self._fetchall = []
            return
        if text.startswith("insert into task_verification_org_settings"):
            oid = int(params[0])
            self.org_settings[oid] = {
                "organization_id": oid,
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
            self._fetch = None
            return
        if "from cleaning_task_activities" in text and "assignment_group_id" in text:
            gid, day = params[1], params[2]
            self._fetchall = [
                r
                for r in self.activities
                if str(r.get("assignment_group_id")) == str(gid)
                and str(r.get("business_date"))[:10] == str(day)[:10]
            ]
            self._fetch = None
            return
        if "from cleaning_task_activities" in text and "and id = %s" in text:
            aid = int(params[1])
            self._fetch = next((a for a in self.activities if int(a["id"]) == aid), None)
            return
        if text.startswith("update cleaning_task_activities"):
            aid = int(params[-2]) if "rejection_reason" in text else int(params[-2])
            # params end with activity_id, organization_id
            aid = int(params[-2])
            for a in self.activities:
                if int(a["id"]) == aid:
                    a["status"] = params[0]
                    a["approved_by_user_id"] = params[1]
                    a["approved_at"] = params[2]
                    if "rejection_reason" in text:
                        a["rejection_reason"] = params[3]
                    self.rowcount = 1
                    break
            return
        if text.startswith("insert into cleaning_task_activity_events"):
            return
        self._fetch = None
        self._fetchall = []

    def fetchone(self):
        return self._fetch

    def fetchall(self):
        return list(self._fetchall)


def test_global_default_is_supervisor_required():
    cur = _MemCursor()
    with mock.patch("backend.task_verification_policy.table_exists", return_value=False), mock.patch(
        "backend.task_verification_policy.table_has_column", return_value=False
    ), mock.patch("backend.task_verification_policy.invalidate_schema_cache"):
        policy = get_global_verification_policy(cur, 3)
    assert policy["verification_required"] is True
    assert policy["verification_method"] == VERIFY_SUPERVISOR
    assert policy["is_default"] is True


def test_upsert_global_and_resolve_task_inherit():
    cur = _MemCursor()
    with mock.patch("backend.task_verification_policy.table_exists", return_value=True), mock.patch(
        "backend.task_verification_policy.table_has_column", return_value=True
    ), mock.patch("backend.task_verification_policy.invalidate_schema_cache"):
        upsert_global_verification_policy(
            cur,
            3,
            {
                "verification_method": "supervisor",
                "verification_required": True,
                "verification_timing": "later_shift",
            },
        )
        task = {
            "code": "lint_cleaning",
            "verification_inherits": True,
            "verification_required": False,
            "verification_method": VERIFY_NONE,
        }
        resolved = resolve_verification_policy(cur, 3, task_definition=task)
    assert resolved["verification_method"] == VERIFY_SUPERVISOR
    assert resolved["verification_timing"] == "later_shift"
    assert resolved["source"] == "global"


def test_group_override_then_task_override():
    cur = _MemCursor()
    with mock.patch("backend.task_verification_policy.table_exists", return_value=True), mock.patch(
        "backend.task_verification_policy.table_has_column", return_value=True
    ), mock.patch("backend.task_verification_policy.invalidate_schema_cache"):
        group = {
            "verification_inherits": False,
            "verification_required": True,
            "verification_method": "employee",
            "verification_timing": "same_shift",
            "verifier_config_json": "{}",
        }
        task = {
            "code": "floor_cleaning",
            "verification_inherits": False,
            "verification_required": True,
            "verification_method": "supervisor",
            "verification_timing": "next_day",
            "verifier_config": {},
        }
        mid = resolve_verification_policy(cur, 3, activity_group=group, task_definition={
            "code": "floor_cleaning",
            "verification_inherits": True,
        })
        assert mid["verification_method"] == "employee"
        assert mid["source"] == "activity_group"
        top = resolve_verification_policy(cur, 3, activity_group=group, task_definition=task)
        assert top["verification_method"] == "supervisor"
        assert top["verification_timing"] == "next_day"
        assert top["source"] == "task"


def test_explicit_none_only_via_override():
    cur = _MemCursor()
    with mock.patch("backend.task_verification_policy.table_exists", return_value=True), mock.patch(
        "backend.task_verification_policy.table_has_column", return_value=True
    ), mock.patch("backend.task_verification_policy.invalidate_schema_cache"):
        upsert_global_verification_policy(
            cur, 3, {"verification_method": "none", "verification_required": False}
        )
        g = get_global_verification_policy(cur, 3)
    assert g["verification_required"] is False
    assert g["verification_method"] == VERIFY_NONE


def test_snapshot_columns_preserve_effective_policy():
    snap = snapshot_columns(
        {
            "verification_required": True,
            "verification_method": "supervisor",
            "verification_timing": "next_day",
        }
    )
    assert snap["verification_required"] == 1
    assert snap["verification_method"] == "supervisor"
    assert snap["verification_timing"] == "next_day"


def test_co_participant_blocked_even_with_supervisor_review():
    cur = _MemCursor()
    cur.responsibilities = [
        {"user_id": 16, "assignment_group_id": "shared-1"},
        {"user_id": 51, "assignment_group_id": "shared-1"},
    ]
    activity = {
        "id": 80,
        "user_id": 51,
        "status": STATUS_PENDING_APPROVAL,
        "assignment_group_id": "shared-1",
        "business_date": date(2026, 10, 30),
        "role": "lint_cleaning",
        "verification_required": 1,
        "verification_method": "supervisor",
    }
    assert verifier_is_shared_co_participant(
        cur, organization_id=3, activity=activity, verifier_user_id=16
    )
    assert not user_can_verify_activity(
        cur,
        organization_id=3,
        activity=activity,
        verifier_user_id=16,
        has_supervisor_review=True,
    )
    # Independent supervisor may verify.
    assert user_can_verify_activity(
        cur,
        organization_id=3,
        activity=activity,
        verifier_user_id=99,
        has_supervisor_review=True,
    )


def test_self_verify_blocked():
    activity = {
        "id": 79,
        "user_id": 16,
        "status": STATUS_PENDING_APPROVAL,
        "assignment_group_id": None,
        "verification_required": 1,
        "verification_method": "supervisor",
    }
    assert not user_can_verify_activity(
        cur := _MemCursor(),
        organization_id=3,
        activity=activity,
        verifier_user_id=16,
        has_supervisor_review=True,
    )


def test_approve_rejects_co_participant():
    cur = _MemCursor()
    cur.responsibilities = [
        {"user_id": 16, "assignment_group_id": "g"},
        {"user_id": 51, "assignment_group_id": "g"},
    ]
    cur.activities = [
        {
            "id": 80,
            "organization_id": 3,
            "user_id": 51,
            "status": STATUS_PENDING_APPROVAL,
            "assignment_group_id": "g",
            "business_date": date(2026, 10, 30),
            "role": "lint_cleaning",
            "verification_required": 1,
            "verification_method": "supervisor",
            "timing_mode": "anytime",
        }
    ]
    with mock.patch("backend.cleaning_task_activity._role_catalog", return_value={}), mock.patch(
        "backend.cleaning_task_activity.serialize_activity", side_effect=lambda r, catalog=None: dict(r)
    ), mock.patch("backend.cleaning_task_activity.eastern_now_naive", return_value=date.today()):
        with pytest.raises(CleaningTaskError) as exc:
            approve_activity(cur, organization_id=3, activity_id=80, supervisor_user_id=16)
    assert exc.value.status == 403
    assert "shared assignment" in exc.value.message.lower() or "independent" in exc.value.message.lower()
    # Historical row remains pending — approve did not mutate status before raising... 
    # assert runs before update, so status still pending
    assert cur.activities[0]["status"] == STATUS_PENDING_APPROVAL


def test_reject_rejects_co_participant():
    cur = _MemCursor()
    cur.responsibilities = [
        {"user_id": 16, "assignment_group_id": "g"},
        {"user_id": 51, "assignment_group_id": "g"},
    ]
    cur.activities = [
        {
            "id": 80,
            "organization_id": 3,
            "user_id": 51,
            "status": STATUS_PENDING_APPROVAL,
            "assignment_group_id": "g",
            "business_date": date(2026, 10, 30),
            "role": "lint_cleaning",
            "verification_required": 1,
            "verification_method": "supervisor",
            "timing_mode": "anytime",
        }
    ]
    with mock.patch("backend.cleaning_task_activity._role_catalog", return_value={}):
        with pytest.raises(CleaningTaskError) as exc:
            reject_activity(
                cur,
                organization_id=3,
                activity_id=80,
                supervisor_user_id=16,
                reason="Needs redo",
            )
    assert exc.value.status == 403


def test_independent_supervisor_can_approve():
    cur = _MemCursor()
    cur.responsibilities = [
        {"user_id": 16, "assignment_group_id": "g"},
        {"user_id": 51, "assignment_group_id": "g"},
    ]
    cur.activities = [
        {
            "id": 79,
            "organization_id": 3,
            "user_id": 16,
            "status": STATUS_PENDING_APPROVAL,
            "assignment_group_id": "g",
            "business_date": date(2026, 10, 30),
            "role": "lint_cleaning",
            "verification_required": 1,
            "verification_method": "supervisor",
            "timing_mode": "anytime",
            "started_at": "2026-10-30 09:43:51",
        }
    ]
    with mock.patch("backend.cleaning_task_activity._role_catalog", return_value={}), mock.patch(
        "backend.cleaning_task_activity.serialize_activity", side_effect=lambda r, catalog=None: dict(r)
    ), mock.patch(
        "backend.cleaning_task_activity.eastern_now_naive",
        return_value=__import__("datetime").datetime(2026, 10, 30, 12, 0, 0),
    ):
        out = approve_activity(cur, organization_id=3, activity_id=79, supervisor_user_id=15)
    assert cur.activities[0]["status"] != STATUS_PENDING_APPROVAL or out is not None
    assert cur.activities[0]["approved_by_user_id"] == 15
