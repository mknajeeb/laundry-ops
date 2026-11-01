"""Shared checklist display, exclusive chart buckets, Sunday weeks, and remark privacy."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from backend.cleaning_task_activity import _stored_remark, _strip_rinse_management_fields
from backend.cleaning_task_dashboard_analytics import bucket_label, chart_status, stack_chart_buckets
from backend.rinse_folding_et import ET


def test_chart_statuses_are_mutually_exclusive_labels():
    assert chart_status({"status": "pending", "overall_status": "not_started", "contributions": []}) == "not_started"
    assert chart_status({
        "status": "overdue",
        "overall_status": "overdue",
        "completion_status": "not_started",
        "contributions": [],
    }) == "overdue"


def test_november_first_week_bucket_stays_on_the_sunday_through_dst():
    sunday = date(2026, 11, 1)
    assert sunday.weekday() == 6
    assert bucket_label(sunday, "weekly") == "2026-11-01"
    assert bucket_label(date(2026, 11, 7), "weekly") == "2026-11-01"
    assert bucket_label(sunday, "monthly") == "2026-11"
    first = datetime(2026, 11, 1, 1, 30, tzinfo=ET, fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=ET, fold=1)
    assert first.date() == second.date() == sunday
    assert first.utcoffset() != second.utcoffset()
    buckets = stack_chart_buckets(
        [
            {"business_date": "2026-11-01", "chart": {"not_started": 2, "verified": 0, "in_progress": 0, "pending_verification": 0, "overdue": 0, "needs_correction": 0}},
            {"business_date": "2026-11-02", "chart": {"not_started": 1, "verified": 0, "in_progress": 0, "pending_verification": 0, "overdue": 0, "needs_correction": 0}},
        ],
        "weekly",
    )
    assert buckets[0]["label"] == "2026-11-01"
    assert buckets[0]["not_started"] == 3


def test_shared_finish_and_verification_follow_the_checklist_flag():
    from backend.cleaning_task_activity import assignment_is_completed, assignment_is_verified
    from backend.cleaning_task_shared_execution import _shared_finish_allowed

    assert _shared_finish_allowed({"require_checklist_before_completion": None}, [{"required": True}], False) is False
    assert _shared_finish_allowed({"require_checklist_before_completion": False}, [{"required": True}], False) is True
    assert _shared_finish_allowed({"require_checklist_before_completion": True}, [{"required": True}], True) is True
    open_row = {
        "checklist_complete": False,
        "overall_status": "in_progress",
        "completion_status": "in_progress",
        "execution_mode": "shared",
        "contributions": [
            {"status": "completed", "participation_status": "finished"},
            {"status": "completed", "participation_status": "finished"},
        ],
    }
    assert assignment_is_completed(open_row) is False
    assert assignment_is_verified(open_row) is False


def test_rinse_strips_employee_and_supervisor_remarks():
    payload = {
        "employee_remark": {"text": "left the mop", "author_user_id": 36},
        "supervisor_remark": {"text": "looks good", "author_user_id": 15},
        "role_label": "Floor & Washer",
        "contributions": [
            {"employee_remark": {"text": "hidden"}, "employee_name": "Yesenia"},
        ],
    }
    cleaned = _strip_rinse_management_fields(payload)
    assert "employee_remark" not in cleaned
    assert "supervisor_remark" not in cleaned
    assert cleaned["role_label"] == "Floor & Washer"
    assert "employee_remark" not in cleaned["contributions"][0]
    assert cleaned["contributions"][0]["employee_name"] == "Yesenia"


def test_chart_buckets_do_not_double_count_one_assignment():
    rows = [
        {"status": "pending", "overall_status": "not_started", "contributions": []},
        {"status": "approved", "overall_status": "verified", "completion_status": "completed", "verification_status": "verified", "contributions": [{"status": "approved", "participation_status": "finished"}]},
    ]
    labels = [chart_status(row) for row in rows]
    assert labels[0] == "not_started"
    assert labels.count("verified") + labels.count("not_started") == len(rows)


def test_employee_remark_is_attached_without_replacing_completion_values():
    from datetime import datetime

    from backend.cleaning_task_activity import _with_employee_remark

    merged = _with_employee_remark(
        {"values": {"bags": 3}, "remarks": None},
        "Left the mop wet",
        36,
        datetime(2026, 11, 1, 9, 25, 38),
    )
    assert merged["values"]["bags"] == 3
    assert merged["employee_remark"]["text"] == "Left the mop wet"
    assert merged["employee_remark"]["author_user_id"] == 36
    assert merged["employee_remark"]["at"] == "2026-11-01 09:25:38"
    assert _with_employee_remark({"values": {}}, "  ", 36, datetime(2026, 11, 1, 9, 25)) == {"values": {}}


def test_stored_remark_keeps_author_and_time():
    remark = _stored_remark(
        {"employee_remark": {"text": "Done early", "author_user_id": 56, "at": "2026-11-01 09:25:38"}},
        "employee_remark",
    )
    assert remark["text"] == "Done early"
    assert remark["author_user_id"] == 56
    assert remark["at"].startswith("2026-11-01 09:25")
    assert _stored_remark({}, "employee_remark") is None
