"""Cleaning / Tasks activity: exclusivity, approval, and self-approve block."""

from __future__ import annotations

from datetime import date, datetime
from unittest import mock

import pytest

from backend.cleaning_task_activity import (
    STATUS_APPROVED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING_APPROVAL,
    STATUS_REJECTED,
    CleaningTaskError,
    approve_activity,
    complete_task,
    ensure_cleaning_task_activity_tables,
    get_open_activity,
    reject_activity,
    start_task,
)


class _FakeCursor:
    def __init__(self):
        self.rows = {}
        self.tables = set()
        self.lastrowid = 0
        self._fetch = None
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        text = " ".join(str(sql).split()).lower()
        if text.startswith("create table"):
            if "cleaning_task_activities" in text:
                self.tables.add("cleaning_task_activities")
            if "cleaning_task_activity_events" in text:
                self.tables.add("cleaning_task_activity_events")
            self._fetch = None
            return
        if "from cleaning_task_activities" in text and "status = %s" in text:
            uid = int(params[1])
            open_rows = [
                r
                for r in self.rows.get("activities", [])
                if int(r["user_id"]) == uid and r["status"] == STATUS_IN_PROGRESS
            ]
            self._fetch = open_rows[-1] if open_rows else None
            return
        if "from cleaning_task_activities" in text and "and id = %s" in text:
            aid = int(params[1])
            self._fetch = next((r for r in self.rows.get("activities", []) if int(r["id"]) == aid), None)
            return
        if text.startswith("insert into cleaning_task_activities"):
            self.lastrowid = len(self.rows.setdefault("activities", [])) + 1
            cols = [
                "organization_id",
                "responsibility_id",
                "assignment_group_id",
                "user_id",
                "shift_session_id",
                "business_date",
                "role",
                "timing_mode",
                "planned_start_time",
                "status",
                "started_at",
                "paused_category_id",
                "paused_role_id",
                "category_code",
                "completion_type",
                "timer_enabled",
                "verification_required",
                "verification_method",
                "verification_timing",
                "checklist_id",
            ]
            row = {"id": self.lastrowid}
            for i, col in enumerate(cols):
                if i < len(params or ()):
                    row[col] = params[i]
            self.rows["activities"].append(row)
            self._fetch = None
            return
        if text.startswith("update cleaning_task_activities"):
            # last two params are id, org
            aid = int(params[-2])
            row = next(r for r in self.rows["activities"] if int(r["id"]) == aid)
            status = params[0]
            row["status"] = status
            if status in (STATUS_PENDING_APPROVAL, "completed"):
                row["ended_at"] = params[1]
                row["duration_seconds"] = params[2]
                if len(params) >= 6:
                    row["completion_input_json"] = params[3]
            elif status == STATUS_APPROVED:
                row["approved_by_user_id"] = params[1]
                row["approved_at"] = params[2]
                row["rejection_reason"] = None
            elif status == STATUS_REJECTED:
                row["approved_by_user_id"] = params[1]
                row["approved_at"] = params[2]
                row["rejection_reason"] = params[3]
            self._fetch = None
            return
        if text.startswith("insert into cleaning_task_activity_events"):
            self.rows.setdefault("events", []).append({"sql": sql, "params": params})
            self._fetch = None
            return
        self._fetch = None

    def fetchone(self):
        return self._fetch

    def fetchall(self):
        if isinstance(self._fetch, list):
            return self._fetch
        return []


def test_historical_start_does_not_close_production_role():
    """Supervisor backfill for a prior business date must not pause production roles."""
    cursor = _FakeCursor()
    ensure_cleaning_task_activity_tables(cursor)
    conn = mock.Mock()
    assignment = {
        "id": 10,
        "role": "lint_cleaning",
        "timing_mode": "anytime",
        "start_time": None,
        "assignment_group_id": "abc",
        "user_ids": [5],
        "user_id": 5,
    }
    with mock.patch(
        "backend.cleaning_task_activity._day_responsibilities", return_value=[assignment]
    ), mock.patch(
        "backend.cleaning_task_activity._activities_for_day", return_value=[]
    ), mock.patch(
        "backend.cleaning_task_activity._role_catalog",
        return_value={"lint_cleaning": {"name": "Lint Cleaning"}},
    ), mock.patch(
        "backend.cleaning_task_activity.business_today", return_value=date(2026, 10, 28)
    ), mock.patch(
        "backend.cleaning_task_activity.eastern_now_naive",
        return_value=datetime(2026, 10, 28, 15, 0, 0),
    ), mock.patch(
        "backend.task_verification_policy.resolve_verification_policy",
        return_value={
            "verification_required": True,
            "verification_method": "supervisor",
            "verification_timing": "same_shift",
            "verifier_config": {},
        },
    ), mock.patch(
        "backend.task_verification_policy.snapshot_columns",
        return_value={
            "verification_required": 1,
            "verification_method": "supervisor",
            "verification_timing": "same_shift",
            "verifier_config": {},
        },
    ), mock.patch(
        "backend.ta_routes.get_open_break", return_value=None
    ), mock.patch(
        "backend.shift_job_tracking.get_open_job_segment",
        return_value={"category_id": 1, "role_id": 2},
    ) as get_seg, mock.patch(
        "backend.shift_job_tracking.close_open_job_segment"
    ) as close_seg:
        started = start_task(
            conn,
            cursor,
            organization_id=3,
            user_id=5,
            responsibility_id=10,
            shift_session_id=99,  # must be ignored for historical day
            business_date=date(2026, 10, 26),
        )
    assert started["status"] == STATUS_IN_PROGRESS
    assert started.get("shift_session_id") is None
    assert started.get("paused_role_id") is None
    assert str(started.get("business_date"))[:10] == "2026-10-26"
    get_seg.assert_not_called()
    close_seg.assert_not_called()


def test_start_complete_and_supervisor_approve_flow():
    cursor = _FakeCursor()
    ensure_cleaning_task_activity_tables(cursor)
    conn = mock.Mock()

    assignment = {
        "id": 10,
        "role": "lint_cleaning",
        "timing_mode": "anytime",
        "start_time": None,
        "assignment_group_id": "abc",
        "user_ids": [5],
        "user_id": 5,
    }

    with mock.patch(
        "backend.cleaning_task_activity._day_responsibilities", return_value=[assignment]
    ), mock.patch(
        "backend.cleaning_task_activity._activities_for_day", return_value=[]
    ), mock.patch(
        "backend.cleaning_task_activity._role_catalog", return_value={"lint_cleaning": {"name": "Lint Cleaning"}}
    ), mock.patch(
        "backend.cleaning_task_activity.business_today", return_value=date(2026, 10, 27)
    ), mock.patch(
        "backend.cleaning_task_activity.eastern_now_naive", return_value=datetime(2026, 10, 27, 9, 0, 0)
    ), mock.patch(
        "backend.task_verification_policy.resolve_verification_policy",
        return_value={
            "verification_required": True,
            "verification_method": "supervisor",
            "verification_timing": "same_shift",
            "verifier_config": {},
        },
    ), mock.patch(
        "backend.task_verification_policy.snapshot_columns",
        return_value={
            "verification_required": 1,
            "verification_method": "supervisor",
            "verification_timing": "same_shift",
            "verifier_config": {},
        },
    ), mock.patch(
        "backend.cleaning_task_activity.get_open_break", create=True
    ), mock.patch(
        "backend.ta_routes.get_open_break", return_value=None
    ), mock.patch(
        "backend.shift_job_tracking.get_open_job_segment", return_value={"category_id": 1, "role_id": 2}
    ), mock.patch(
        "backend.shift_job_tracking.close_open_job_segment"
    ) as close_seg:
        started = start_task(
            conn,
            cursor,
            organization_id=3,
            user_id=5,
            responsibility_id=10,
            shift_session_id=99,
        )
        assert started["status"] == STATUS_IN_PROGRESS
        assert started["paused_role_id"] == 2
        close_seg.assert_called_once()
        assert get_open_activity(cursor, 3, 5) is not None

        with mock.patch(
            "backend.cleaning_task_activity.eastern_now_naive",
            return_value=datetime(2026, 10, 27, 9, 12, 0),
        ), mock.patch(
            "backend.cleaning_task_activity._role_catalog",
            return_value={"lint_cleaning": {"name": "Lint Cleaning"}},
        ):
            done = complete_task(conn, cursor, organization_id=3, user_id=5, activity_id=started["id"])
        assert done["status"] == STATUS_PENDING_APPROVAL
        assert done["duration_seconds"] == 12 * 60
        assert "resume_work" in [o["id"] for o in done["next_options"]]

        with pytest.raises(CleaningTaskError) as self_approve:
            approve_activity(
                cursor, organization_id=3, activity_id=started["id"], supervisor_user_id=5
            )
        assert self_approve.value.status == 403

        approved = approve_activity(
            cursor, organization_id=3, activity_id=started["id"], supervisor_user_id=7
        )
        assert approved["status"] == STATUS_APPROVED
        assert approved["approved_by_user_id"] == 7


def test_reject_requires_reason_and_blocks_self():
    cursor = _FakeCursor()
    ensure_cleaning_task_activity_tables(cursor)
    cursor.rows["activities"] = [
        {
            "id": 1,
            "organization_id": 3,
            "responsibility_id": 10,
            "assignment_group_id": None,
            "user_id": 5,
            "shift_session_id": 1,
            "business_date": date(2026, 10, 27),
            "role": "floor_cleaning",
            "timing_mode": "anytime",
            "planned_start_time": None,
            "status": STATUS_PENDING_APPROVAL,
            "started_at": datetime(2026, 10, 27, 8, 0, 0),
            "ended_at": datetime(2026, 10, 27, 8, 10, 0),
            "duration_seconds": 600,
            "paused_category_id": None,
            "paused_role_id": None,
            "approved_by_user_id": None,
            "approved_at": None,
            "rejection_reason": None,
        }
    ]
    with mock.patch(
        "backend.cleaning_task_activity._role_catalog",
        return_value={"floor_cleaning": {"name": "Floor Cleaning"}},
    ), mock.patch(
        "backend.cleaning_task_activity.eastern_now_naive",
        return_value=datetime(2026, 10, 27, 10, 0, 0),
    ):
        with pytest.raises(CleaningTaskError):
            reject_activity(
                cursor,
                organization_id=3,
                activity_id=1,
                supervisor_user_id=7,
                reason="no",
            )
        with pytest.raises(CleaningTaskError) as exc:
            reject_activity(
                cursor,
                organization_id=3,
                activity_id=1,
                supervisor_user_id=5,
                reason="Missed corners",
            )
        assert exc.value.status == 403
        out = reject_activity(
            cursor,
            organization_id=3,
            activity_id=1,
            supervisor_user_id=7,
            reason="Missed corners",
        )
        assert out["status"] == STATUS_REJECTED
        assert out["rejection_reason"] == "Missed corners"
