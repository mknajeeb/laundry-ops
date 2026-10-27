"""Checklist-level verification helpers."""

from __future__ import annotations

from datetime import date
from unittest import mock

from backend.cleaning_task_activity import STATUS_PENDING_APPROVAL
from backend.task_checklist import (
    CHECKLIST_PENDING,
    build_checklist_day_status,
)


class _FakeCursor:
    def __init__(self, activities=None, items=None, verification=None):
        self.activities = activities or []
        self.items = items or []
        self.verification = verification
        self._fetch = None
        self._fetchall = []

    def execute(self, sql, params=None):
        text = " ".join(str(sql).split()).lower()
        if "from task_checklist_items" in text:
            self._fetchall = self.items
            self._fetch = None
            return
        if "from cleaning_task_activities" in text:
            self._fetchall = self.activities
            self._fetch = None
            return
        if "from task_checklist_verifications" in text:
            self._fetch = self.verification
            self._fetchall = []
            return
        if "from users" in text:
            self._fetchall = [
                {"id": 5, "display_name": "Eve", "username": "eve"},
                {"id": 6, "display_name": "Mo", "username": "mo"},
            ]
            return
        self._fetch = None
        self._fetchall = []

    def fetchone(self):
        return self._fetch

    def fetchall(self):
        return list(self._fetchall)


def test_checklist_cannot_verify_when_incomplete():
    cursor = _FakeCursor(
        items=[
            {"id": 1, "checklist_id": 9, "task_code": "floor_cleaning", "display_order": 0, "required": 1},
            {"id": 2, "checklist_id": 9, "task_code": "lint_cleaning", "display_order": 10, "required": 1},
        ],
        activities=[
            {
                "id": 1,
                "organization_id": 3,
                "responsibility_id": 1,
                "user_id": 5,
                "role": "floor_cleaning",
                "status": STATUS_PENDING_APPROVAL,
                "business_date": date(2026, 10, 27),
                "timing_mode": "anytime",
            }
        ],
    )
    checklist = {
        "id": 9,
        "code": "eod",
        "name": "End of Day",
        "items": [
            {"task_code": "floor_cleaning", "required": True},
            {"task_code": "lint_cleaning", "required": True},
        ],
    }
    with mock.patch("backend.task_checklist._role_catalog", return_value={}), mock.patch(
        "backend.task_checklist.ensure_cleaning_task_activity_tables"
    ), mock.patch("backend.task_checklist.list_checklist_items", return_value=checklist["items"]):
        status = build_checklist_day_status(cursor, 3, checklist, date(2026, 10, 27))
    assert status["can_verify_all"] is False
    assert status["required_incomplete"] >= 1


def test_checklist_pending_when_all_required_complete():
    cursor = _FakeCursor(
        items=[
            {"id": 1, "checklist_id": 9, "task_code": "floor_cleaning", "display_order": 0, "required": 1},
        ],
        activities=[
            {
                "id": 1,
                "organization_id": 3,
                "responsibility_id": 1,
                "user_id": 5,
                "role": "floor_cleaning",
                "status": STATUS_PENDING_APPROVAL,
                "business_date": date(2026, 10, 27),
                "timing_mode": "anytime",
                "started_at": "2026-10-27 20:00:00",
                "ended_at": "2026-10-27 20:10:00",
                "duration_seconds": 600,
            }
        ],
    )
    checklist = {
        "id": 9,
        "code": "eod",
        "name": "End of Day",
        "items": [{"task_code": "floor_cleaning", "required": True}],
    }
    with mock.patch("backend.task_checklist._role_catalog", return_value={}), mock.patch(
        "backend.task_checklist.ensure_cleaning_task_activity_tables"
    ), mock.patch("backend.task_checklist.list_checklist_items", return_value=checklist["items"]):
        status = build_checklist_day_status(cursor, 3, checklist, date(2026, 10, 27))
    assert status["status"] == CHECKLIST_PENDING
    assert status["can_verify_all"] is True
