"""Intra-Day groups, append-only remarks, and calculated section verification."""

from __future__ import annotations

from datetime import datetime

from backend.end_of_day_closing_template import (
    PROPOSED_REMOVED_ROUTINE_CODES,
    end_of_day_closing_payload,
    proposed_end_of_day_closing_payload,
)
from backend.business_time import eastern_elapsed_seconds
from backend.dryer_lint_transition import preview_lily_dryer_lint
from backend.intra_day_activity_groups import (
    DRYER_ROLE,
    FLOOR_ROLE,
    LEGACY_COMBINED_ROLE,
    WASHER_ROLE,
    competing_new_assignment_error,
    intra_day_activity_group_payloads,
)
from backend.task_activity_remarks import (
    append_remark,
    et_wall_to_utc,
    list_remarks_for_activity,
    migrate_legacy_remarks,
)
from backend.cleaning_task_activity import (
    apply_shared_item_verification,
    verification_status_from_subjects,
)
from backend.task_section_verification import section_rollups


class _MemoryCursor:
    def __init__(self):
        self.rows = []
        self.activities = []
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
        if "from cleaning_task_activities" in text:
            org = params[0] if params else None
            self._fetch = [
                row
                for row in self.activities
                if org is None or row.get("organization_id") == org
            ]
            return
        if "author_role=%s and body=%s" in text:
            org, activity_id, role, body = params
            self._fetch = next(
                (
                    row
                    for row in self.rows
                    if row["organization_id"] == org
                    and row["activity_id"] == activity_id
                    and row["author_role"] == role
                    and row["body"] == body
                ),
                None,
            )
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
                    "created_at_utc": params[9] if len(params) > 10 else None,
                    "legacy_source": params[10] if len(params) > 10 else params[9],
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
        "backend.task_activity_remarks.remark_now",
        lambda: (datetime(2026, 11, 1, 21, 5, 0), datetime(2026, 11, 2, 2, 5, 0)),
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
    assert remark["created_at_utc"] == "2026-11-02 02:05:00"
    assert remark["created_at_label"] == "2026-11-01 21:05:00 ET (2026-11-02 02:05:00 UTC)"


def test_daylight_saving_transitions_are_not_invented():
    fallback = datetime(2026, 11, 1, 1, 30, 0)
    assert et_wall_to_utc(fallback) is None
    spring_gap = datetime(2026, 3, 8, 2, 30, 0)
    assert et_wall_to_utc(spring_gap) is None
    clear = et_wall_to_utc(datetime(2026, 11, 1, 12, 0, 0))
    assert clear == datetime(2026, 11, 1, 17, 0, 0)


def test_historical_remarks_stay_visible_and_migrate_once():
    cursor = _MemoryCursor()
    activity = {
        "id": 9,
        "organization_id": 3,
        "assignment_group_id": "old",
        "rejection_reason": "Redo the gasket",
        "completion_input_json": {
            "employee_remark": {"text": "Lint was heavy", "author_user_id": 8, "author_name": "Lily Chen", "at": "2026-11-01 01:30:00"},
            "supervisor_remark": {"text": "Checked the door", "author_user_id": 4, "at": "2026-10-31 18:00:00"},
        },
    }
    before = list_remarks_for_activity(cursor, 3, activity)
    assert [row["body"] for row in before] == ["Lint was heavy", "Checked the door"]
    assert before[0]["author_name"] == "Lily Chen"
    assert before[0]["created_at_utc"] is None
    assert before[1]["author_name"] is None
    assert before[1]["created_at_label"] == "2026-10-31 18:00:00 ET"
    unnamed = {
        "id": 10,
        "organization_id": 3,
        "completion_input_json": {"employee_remark": {"text": "No author recorded"}},
    }
    visible = list_remarks_for_activity(cursor, 3, unnamed)
    assert visible[0]["body"] == "No author recorded"
    assert visible[0]["author_user_id"] is None
    assert visible[0]["author_name"] is None
    assert visible[0]["created_at"] is None

    cursor.activities = [activity, unnamed]
    first = migrate_legacy_remarks(cursor, 3)
    second = migrate_legacy_remarks(cursor, 3)
    assert first["inserted"] == 2
    assert first["held_for_display"] == 1
    assert second["inserted"] == 0
    assert activity["rejection_reason"] == "Redo the gasket"
    stored = [row for row in cursor.rows if row["activity_id"] == 9]
    assert stored[0]["created_at_utc"] is None
    assert stored[1]["created_at_utc"] == datetime(2026, 10, 31, 22, 0, 0)


def test_participation_duration_handles_midnight_and_daylight_saving():
    assert eastern_elapsed_seconds(datetime(2026, 11, 1, 10, 0, 0), datetime(2026, 11, 1, 10, 25, 0)) == 25 * 60
    assert eastern_elapsed_seconds(datetime(2026, 11, 1, 10, 10, 0), datetime(2026, 11, 1, 10, 40, 0)) == 30 * 60
    assert eastern_elapsed_seconds(datetime(2026, 11, 1, 23, 50, 0), datetime(2026, 11, 2, 0, 20, 0)) == 30 * 60
    # The fallback hour is repeated, so 12:30 AM to 3:00 AM is three and a half hours.
    assert eastern_elapsed_seconds(datetime(2026, 11, 1, 0, 30, 0), datetime(2026, 11, 1, 3, 0, 0)) == 12600
    # Spring forward removes 2:00–3:00 AM, so 1:30 AM to 3:30 AM is one hour.
    assert eastern_elapsed_seconds(datetime(2026, 3, 8, 1, 30, 0), datetime(2026, 3, 8, 3, 30, 0)) == 3600
    assert eastern_elapsed_seconds(datetime(2026, 11, 1, 1, 30, 0), datetime(2026, 11, 1, 1, 45, 0)) is None


def test_legacy_cache_is_not_copied_when_the_log_already_has_the_remark():
    cursor = _MemoryCursor()
    cursor.rows.append(
        {
            "id": 1,
            "organization_id": 3,
            "activity_id": 4,
            "assignment_group_id": "g",
            "task_code": None,
            "author_user_id": 1,
            "author_name": "VeeWash Admin",
            "author_role": "supervisor",
            "body": "Machines verified",
            "created_at": datetime(2026, 11, 1, 10, 46, 0),
            "created_at_utc": datetime(2026, 11, 1, 15, 46, 0),
            "legacy_source": None,
        }
    )
    activity = {
        "id": 4,
        "organization_id": 3,
        "assignment_group_id": "g",
        "completion_input_json": {
            "supervisor_remark": {
                "text": "Machines verified",
                "author_user_id": 1,
                "at": "2026-11-01 10:46:00",
            }
        },
    }
    cursor.activities = [activity]
    assert migrate_legacy_remarks(cursor, 3)["inserted"] == 0
    assert len(cursor.rows) == 1


def test_approved_shared_item_marks_the_section_verified():
    items = apply_shared_item_verification(
        [
            {
                "task_code": "custom_check_washer_residue",
                "status": "completed",
                "required": True,
                "verification_required": True,
                "verification_method": "supervisor",
                "section_label": "Machines",
                "child_activity_id": 4,
            },
            {
                "task_code": "washer_cleaning",
                "status": "completed",
                "required": True,
                "verification_required": True,
                "verification_method": "supervisor",
                "section_label": "Machines",
                "child_activity_id": 6,
            },
        ],
        [{"id": 4, "status": "approved"}, {"id": 6, "status": "approved"}],
    )
    assert verification_status_from_subjects(items) == "verified"
    assert section_rollups(items)[0]["status_label"] == "Verified"


def test_lily_dryer_lint_preview_converts_only_the_eight_sundays():
    rows = [
        {"id": 191, "employee_name": "Amna", "role": "lint_cleaning", "week_start": "2026-11-01", "day_of_week": 1, "timing_mode": "specific_time", "start_time": "08:30"},
        {"id": 7, "employee_name": "Lily Chen", "role": "lint_cleaning", "week_start": "2026-11-08", "day_of_week": 0, "timing_mode": "anytime"},
        {"id": 190, "employee_name": "Angelica", "role": "agroup_floor_washer", "week_start": "2026-11-08", "day_of_week": 0, "timing_mode": "anytime"},
    ]
    sundays = ["2026-11-15", "2026-11-22", "2026-11-29", "2026-12-06", "2026-12-13", "2026-12-20", "2026-12-27", "2027-01-03"]
    for index, day in enumerate(sundays, start=8):
        rows.append(
            {
                "id": index,
                "employee_name": "Lily Chen",
                "role": "lint_cleaning",
                "week_start": day,
                "day_of_week": 0,
                "timing_mode": "anytime",
            }
        )
    preview = preview_lily_dryer_lint(rows)
    assert preview["transition_date"] == "2026-11-09"
    assert [row["id"] for row in preview["converted"]] == list(range(8, 16))
    assert all(row["after_role"] == "agroup_dryer_lint" for row in preview["converted"])
    assert all(row["scheduled_time"] == "anytime" for row in preview["converted"])
    left = {row["id"]: row["scheduled_date"] for row in preview["untouched"]}
    assert left[191] == "2026-11-02"
    assert left[7] == "2026-11-08"
    assert left[190] == "2026-11-08"
    assert all(row["after_role"] == row["before_role"] for row in preview["untouched"])
