"""Phase 3 record management + Rinse eligibility (unit, no live DB)."""

from __future__ import annotations

from datetime import datetime

import pytest

from backend.cleaning_task_activity import (
    COMPLETION_COMPLETED,
    COMPLETION_IN_PROGRESS,
    apply_rinse_task_dashboard_scope,
    completion_status_from_members,
)
from backend.cleaning_task_record_management import (
    activity_is_rinse_eligible,
    activity_is_voided,
    activity_has_manual_touch,
)


def test_rinse_eligible_pin_only():
    assert activity_is_rinse_eligible(
        {"completion_source": "pin", "times_manual": 0, "voided_at": None}
    )
    assert not activity_is_rinse_eligible({"completion_source": "manual"})
    assert not activity_is_rinse_eligible({"completion_source": "corrected"})
    assert not activity_is_rinse_eligible(
        {"completion_source": "pin", "times_manual": 1}
    )
    assert not activity_is_rinse_eligible(
        {"completion_source": "pin", "voided_at": datetime(2026, 10, 30, 12, 0, 0)}
    )
    assert not activity_is_rinse_eligible(
        {"completion_source": "pin", "superseded_by_activity_id": 99}
    )


def test_void_and_manual_helpers():
    assert activity_is_voided({"voided_at": "2026-10-30 12:00:00"})
    assert not activity_is_voided({"voided_at": None})
    assert activity_has_manual_touch({"completion_source": "manual"})
    assert activity_has_manual_touch({"times_manual": 1, "completion_source": "pin"})
    assert not activity_has_manual_touch({"completion_source": "pin", "times_manual": 0})


def test_rinse_scope_drops_activity_log_and_manual_assignments():
    payload = {
        "metrics": {"total_assigned": 2, "time_spent_seconds": 500},
        "durations": [{"seconds": 12}],
        "activity_log": [{"id": 1, "role": "lint_cleaning"}],
        "shared_assignments": [
            {
                "assignment_key": "g:manual",
                "has_manual_completion": True,
                "completion_status": "completed",
                "verification_status": "not_required",
                "contributions": [
                    {
                        "status": "completed",
                        "activity": {"completion_source": "manual", "id": 1},
                    }
                ],
            },
            {
                "assignment_key": "g:pin",
                "has_manual_completion": False,
                "completion_status": "completed",
                "verification_status": "verified",
                "contributions": [
                    {
                        "status": "approved",
                        "activity": {
                            "id": 2,
                            "completion_source": "pin",
                            "times_manual": 0,
                            "duration_seconds": 40,
                            "manual_reason": "should strip",
                        },
                    }
                ],
            },
        ],
        "queue": {"pending": []},
    }
    out = apply_rinse_task_dashboard_scope(payload)
    assert out["activity_log"] == []
    assert out["durations"] == []
    assert out["read_only"] is True
    assert out["can_manual_complete"] is False
    assert "queue" not in out
    assert len(out["shared_assignments"]) == 1
    assert out["shared_assignments"][0]["assignment_key"] == "g:pin"
    assert out["metrics"]["total_assigned"] == 1
    assert "time_spent_seconds" not in out["metrics"]
    contrib = out["shared_assignments"][0]["contributions"][0]
    act = contrib.get("activity") or {}
    assert "duration_seconds" not in act
    assert "manual_reason" not in act


def test_completion_members_finished():
    assert (
        completion_status_from_members(["completed", "approved"])
        == COMPLETION_COMPLETED
    )
    assert (
        completion_status_from_members(["completed", "in_progress"])
        == COMPLETION_IN_PROGRESS
    )


def test_shared_checklist_rollup_keeps_in_progress_when_items_pending():
    """Floor & Washer style: finished timers + pending shared checklist ⇒ In Progress."""
    from backend.cleaning_task_activity import (
        DISPLAY_COMPLETED,
        DISPLAY_IN_PROGRESS,
        apply_shared_checklist_to_assignment_status,
    )

    complete, _, completion, rollup = apply_shared_checklist_to_assignment_status(
        [{"required": True, "status": "pending"}, {"required": True, "status": "pending"}],
        completion_status=COMPLETION_COMPLETED,
        rollup=DISPLAY_COMPLETED,
        member_statuses=[DISPLAY_COMPLETED, DISPLAY_COMPLETED],
    )
    assert complete is False
    assert completion == COMPLETION_IN_PROGRESS
    assert rollup == DISPLAY_IN_PROGRESS


def test_duration_recalc_and_end_before_start():
    from backend.cleaning_task_record_management import _recalc_duration
    from datetime import datetime

    start = datetime(2026, 10, 30, 9, 0, 0)
    end = datetime(2026, 10, 30, 9, 32, 0)
    assert _recalc_duration(start, end) == 32 * 60
    assert _recalc_duration(end, start) == 0  # clamped; update_activity_record rejects end < start


def test_midnight_boundary_duration():
    from backend.cleaning_task_record_management import _recalc_duration
    from datetime import datetime

    start = datetime(2026, 10, 30, 23, 50, 0)
    end = datetime(2026, 10, 31, 0, 10, 0)
    assert _recalc_duration(start, end) == 20 * 60


def test_update_record_snapshots_business_date_and_leaves_other_systems_alone(monkeypatch):
    """Editing times must not 500 when business_date is a date, and must audit before/after.

    Production activity edits failed in _snapshot because date.isoformat() rejects sep.
    That happened before the UPDATE, so the activity row was left unchanged.
    """
    import json
    from datetime import date, datetime

    from backend import cleaning_task_record_management as rm

    before_row = {
        "id": 94,
        "organization_id": 3,
        "user_id": 56,
        "role": "lint_cleaning",
        "business_date": date(2026, 10, 31),
        "status": "approved",
        "started_at": datetime(2026, 10, 31, 9, 2, 52),
        "ended_at": datetime(2026, 10, 31, 9, 17, 43),
        "duration_seconds": 891,
        "completion_source": "pin",
        "times_manual": 0,
        "recorded_by_user_id": None,
        "manual_reason": None,
        "approved_by_user_id": 15,
        "approved_at": datetime(2026, 10, 31, 11, 58, 42),
        "activity_kind": "standalone",
        "verification_required": 1,
        "verification_method": "supervisor",
    }
    after_row = dict(before_row)
    after_row.update(
        {
            "started_at": datetime(2026, 10, 31, 9, 2, 0),
            "ended_at": datetime(2026, 10, 31, 9, 18, 0),
            "duration_seconds": 16 * 60,
            "business_date": date(2026, 10, 31),
            "completion_source": "corrected",
            "times_manual": 1,
            "recorded_by_user_id": 15,
            "manual_reason": "Test",
        }
    )
    seen = {"n": 0}

    def fake_get_activity(_cursor, _org, _activity_id):
        seen["n"] += 1
        return before_row if seen["n"] == 1 else after_row

    class Conn:
        def __init__(self):
            self.commits = 0

        def commit(self):
            self.commits += 1

    class Cur:
        def __init__(self):
            self.statements = []

        def execute(self, sql, params=None):
            self.statements.append((" ".join(str(sql).split()), params))

    monkeypatch.setattr(rm, "ensure_record_management_schema", lambda _cursor: None)
    monkeypatch.setattr(rm, "get_activity", fake_get_activity)
    monkeypatch.setattr(rm, "table_has_column", lambda *_args, **_kwargs: True)
    conn = Conn()
    cur = Cur()
    result = rm.update_activity_record(
        conn,
        cur,
        organization_id=3,
        editor_user_id=15,
        activity_id=94,
        reason="Test",
        started_at="2026-10-31T09:02:00",
        ended_at="2026-10-31T09:18:00",
        business_date="2026-10-31",
    )
    assert conn.commits == 1
    assert result["started_at"].startswith("2026-10-31 09:02:00")
    assert result["ended_at"].startswith("2026-10-31 09:18:00")
    assert result["business_date"] == "2026-10-31"
    assert result["completion_source"] == "corrected"
    assert result["status"] == "approved"
    assert result["approved_by_user_id"] == 15

    sql_text = "\n".join(sql for sql, _params in cur.statements).lower()
    assert "update cleaning_task_activities" in sql_text
    assert "insert into cleaning_task_completion_revisions" in sql_text
    assert "payroll" not in sql_text
    assert "attendance" not in sql_text
    assert "punch" not in sql_text
    update_sql, update_params = next(
        item for item in cur.statements if item[0].lower().startswith("update cleaning_task_activities")
    )
    assert "approved_by_user_id" not in update_sql.lower()
    assert "status=%s" not in update_sql.lower()
    assert update_params[0] == datetime(2026, 10, 31, 9, 2, 0)
    assert update_params[1] == datetime(2026, 10, 31, 9, 18, 0)
    assert update_params[2] == 16 * 60
    assert update_params[3] == date(2026, 10, 31)

    _rev_sql, rev_params = next(
        item
        for item in cur.statements
        if "cleaning_task_completion_revisions" in item[0].lower()
    )
    before = json.loads(rev_params[6])
    after = json.loads(rev_params[7])
    assert rev_params[3] == "correction"
    assert rev_params[4] == "Test"
    assert before["business_date"] == "2026-10-31"
    assert before["started_at"] == "2026-10-31 09:02:52"
    assert before["ended_at"] == "2026-10-31 09:17:43"
    assert before["status"] == "approved"
    assert after["started_at"] == "2026-10-31 09:02:00"
    assert after["ended_at"] == "2026-10-31 09:18:00"
    assert after["business_date"] == "2026-10-31"
    assert after["completion_source"] == "corrected"
