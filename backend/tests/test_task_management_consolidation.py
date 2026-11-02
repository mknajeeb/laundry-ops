"""Intra-Day groups, append-only remarks, and calculated section verification."""

from __future__ import annotations

from datetime import datetime

from backend.end_of_day_closing_template import (
    PROPOSED_REMOVED_ROUTINE_CODES,
    end_of_day_closing_payload,
    proposed_end_of_day_closing_payload,
)
from backend.intra_day_activity_groups import (
    DRYER_ROLE,
    FLOOR_ROLE,
    LEGACY_COMBINED_ROLE,
    WASHER_ROLE,
    competing_new_assignment_error,
    intra_day_activity_group_payloads,
)
from backend.task_activity_remarks import append_remark, list_remarks_for_activity
from backend.task_section_verification import section_rollups


class _MemoryCursor:
    def __init__(self):
        self.rows = []
        self.lastrowid = 0
        self._fetch = None
        self.tables = set()

    def execute(self, sql, params=None):
        text = " ".join(str(sql).split()).lower()
        params = list(params or [])
        if "information_schema.tables" in text:
            self._fetch = {"ok": 1} if "task_activity_remarks" in self.tables else None
            return
        if text.startswith("create table"):
            self.tables.add("task_activity_remarks")
            self._fetch = None
            return
        if text.startswith("select id from task_activity_remarks"):
            org, activity_id, source = params
            self._fetch = next(
                (
                    row
                    for row in self.rows
                    if row["organization_id"] == org
                    and row["activity_id"] == activity_id
                    and row["legacy_source"] == source
                ),
                None,
            )
            return
        if text.startswith("select * from task_activity_remarks") and "assignment_group_id=%s" in text:
            org, group_id = params
            self._fetch = [
                row
                for row in self.rows
                if row["organization_id"] == org and row["assignment_group_id"] == group_id
            ]
            return
        if text.startswith("select * from task_activity_remarks"):
            org, activity_id = params
            self._fetch = [
                row
                for row in self.rows
                if row["organization_id"] == org and row["activity_id"] == activity_id
            ]
            return
        if text.startswith("insert into task_activity_remarks"):
            self.lastrowid += 1
            self.rows.append(
                {
                    "id": self.lastrowid,
                    "organization_id": params[0],
                    "activity_id": params[1],
                    "assignment_group_id": params[2],
                    "task_code": params[3],
                    "author_user_id": params[4],
                    "author_name": params[5],
                    "author_role": params[6],
                    "body": params[7],
                    "created_at": params[8],
                    "legacy_source": params[9],
                }
            )
            self._fetch = None
            return
        self._fetch = None

    def fetchone(self):
        if isinstance(self._fetch, list):
            return self._fetch[0] if self._fetch else None
        return self._fetch

    def fetchall(self):
        if isinstance(self._fetch, list):
            return self._fetch
        return []


def test_intra_day_payloads_reuse_existing_task_codes():
    payloads = intra_day_activity_group_payloads()
    assert [item["name"] for item in payloads] == [
        "Washer Cleaning",
        "Floor Sweeping",
        "Dryer Lint Cleaning",
    ]
    washer = payloads[0]
    assert [item["task_code"] for item in washer["items"]] == [
        "custom_check_washer_residue",
        "washer_cleaning",
    ]
    assert washer["items"][0]["section_label"] == "Machines"
    assert payloads[1]["items"][0]["section_label"] == "Floor Cleaning"
    assert payloads[1]["items"][0]["task_code"] == "floor_cleaning"
    assert payloads[2]["items"][0]["section_label"] == "Dryer Cleaning"
    assert payloads[2]["items"][0]["task_code"] == "lint_cleaning"
    assert all(item["instructions"] for group in payloads for item in group["items"])


def test_new_routine_assignment_uses_the_activity_group_once_it_is_active():
    catalog = {
        "lint_cleaning": {"name": "Dryer Lint Cleaning", "active": True},
        DRYER_ROLE: {"name": "Dryer Lint Cleaning", "active": True},
        "floor_cleaning": {"name": "Floor Brooming", "active": True},
        LEGACY_COMBINED_ROLE: {"name": "Floor & Washer", "active": True},
    }
    assert "activity group" in competing_new_assignment_error("lint_cleaning", catalog)
    assert competing_new_assignment_error("lint_cleaning", {"lint_cleaning": {"name": "Dryer Lint Cleaning", "active": True}}) is None
    full = {
        **catalog,
        WASHER_ROLE: {"name": "Washer Cleaning", "active": True},
        FLOOR_ROLE: {"name": "Floor Sweeping", "active": True},
    }
    assert "Washer Cleaning" in competing_new_assignment_error(LEGACY_COMBINED_ROLE, full)


def test_remarks_append_and_keep_each_author():
    cursor = _MemoryCursor()
    activity = {
        "id": 10,
        "assignment_group_id": "shared-1",
        "completion_input_json": {
            "employee_remark": {
                "text": "Left the mop out",
                "author_user_id": 36,
                "author_name": "Yesenia",
                "at": "2026-11-01 09:25:38",
            }
        },
    }
    first = append_remark(
        cursor,
        organization_id=3,
        activity=activity,
        author_user_id=36,
        author_name="Yesenia",
        author_role="employee",
        body="Residue is still in washer 4",
    )
    second = append_remark(
        cursor,
        organization_id=3,
        activity=activity,
        author_user_id=56,
        author_name="Gabriela",
        author_role="employee",
        body="I wiped washer 4",
        task_code="washer_cleaning",
    )
    listed = list_remarks_for_activity(cursor, 3, activity)
    bodies = [row["body"] for row in listed]
    assert "Left the mop out" in bodies
    assert first["body"] in bodies
    assert second["body"] in bodies
    assert listed[0]["body"] == "Left the mop out"
    assert listed[0]["author_name"] == "Yesenia"
    assert second["task_code"] == "washer_cleaning"
    assert second["author_user_id"] == 56
    again = append_remark(
        cursor,
        organization_id=3,
        activity=activity,
        author_user_id=15,
        author_name="Supervisor",
        author_role="supervisor",
        body="Check washer 4 again tomorrow",
    )
    listed = list_remarks_for_activity(cursor, 3, activity)
    assert [row["body"] for row in listed].count("Left the mop out") == 1
    assert listed[-1]["body"] == again["body"]
    assert all("ET" in (row["created_at_label"] or "") for row in listed if row["created_at"])


def test_legacy_remark_is_visible_before_it_is_copied():
    cursor = _MemoryCursor()
    activity = {
        "id": 4,
        "completion_input": {
            "supervisor_remark": {
                "text": "Looks good",
                "author_user_id": 15,
                "at": "2026-11-01 18:00:00",
            }
        },
    }
    listed = list_remarks_for_activity(cursor, 3, activity)
    assert listed[0]["body"] == "Looks good"
    assert listed[0]["author_role"] == "supervisor"
    assert listed[0]["id"] is None


def test_section_status_follows_required_items():
    items = [
        {"section_label": "Machines", "section_order": 10, "required": True, "status": "approved"},
        {
            "section_label": "Machines",
            "section_order": 10,
            "required": True,
            "status": "pending_approval",
            "child_activity_id": 9,
        },
        {"section_label": "Machines", "section_order": 10, "required": False, "status": "pending"},
    ]
    pending = section_rollups(items)[0]
    assert pending["status_label"] == "Pending Verification"
    assert pending["pending_activity_ids"] == [9]

    items[1]["status"] = "rejected"
    assert section_rollups(items)[0]["status_label"] == "Needs Correction"

    items[1]["status"] = "pending"
    assert section_rollups(items)[0]["status_label"] == "In Progress"

    items[1]["status"] = "approved"
    assert section_rollups(items)[0]["status_label"] == "Verified"


def test_proposed_end_of_day_removes_routine_duplicates_without_changing_the_editor_template():
    current = end_of_day_closing_payload()
    proposed = proposed_end_of_day_closing_payload()
    current_codes = {item["task_code"] for item in current["items"]}
    proposed_codes = {item["task_code"] for item in proposed["items"]}
    assert PROPOSED_REMOVED_ROUTINE_CODES <= current_codes
    assert not (PROPOSED_REMOVED_ROUTINE_CODES & proposed_codes)
    assert "eod_hot_water" in proposed_codes
    assert "eod_mop" in proposed_codes
    assert proposed["proposal_only"] is True
    assert "eod_dryer_lint" in current_codes


def test_remark_timestamp_uses_the_supplied_eastern_wall_clock(monkeypatch):
    cursor = _MemoryCursor()
    monkeypatch.setattr(
        "backend.task_activity_remarks.eastern_now_naive",
        lambda: datetime(2026, 11, 1, 21, 5, 0),
    )
    remark = append_remark(
        cursor,
        organization_id=3,
        activity={"id": 1, "assignment_group_id": "g"},
        author_user_id=2,
        author_name="Ana",
        author_role="employee",
        body="Starting the dryers",
    )
    assert remark["created_at"] == "2026-11-01 21:05:00"
    assert remark["created_at_label"] == "2026-11-01 21:05:00 ET"
