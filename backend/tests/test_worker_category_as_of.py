"""Worker category must follow employment history as-of work date."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from backend.payroll_operations import (
    _session_work_date_et,
    worker_category_for_user,
)


UTC = ZoneInfo("UTC")


def _assignments_florentina():
    return [
        {
            "id": 2,
            "employment_category_id": 1,
            "effective_from": "2026-08-24",
            "effective_to": None,
            "worker_category": "w2",
            "code": "EC_W2",
            "name": "W-2",
        },
        {
            "id": 1,
            "employment_category_id": 3,
            "effective_from": "2026-07-27",
            "effective_to": "2026-08-23",
            "worker_category": "temp",
            "code": "EC_TEMP",
            "name": "Temp / One Time",
        },
    ]


def test_category_as_of_work_week_is_temp_after_w2_switch():
    conn = MagicMock()
    rows = _assignments_florentina()
    with patch(
        "backend.portal_system_users.is_portal_system_user",
        return_value=False,
    ):
        assert (
            worker_category_for_user(
                conn, 53, on=date(2026, 7, 30), assignments=rows
            )
            == "temp"
        )
        assert (
            worker_category_for_user(
                conn, 53, on=date(2026, 8, 2), assignments=rows
            )
            == "temp"
        )
        assert (
            worker_category_for_user(
                conn, 53, on=date(2026, 8, 24), assignments=rows
            )
            == "w2"
        )
        assert (
            worker_category_for_user(
                conn, 53, on=date(2026, 8, 29), assignments=rows
            )
            == "w2"
        )


def test_session_work_date_uses_eastern_calendar():
    # 2026-07-30 02:00 UTC = 2026-07-29 22:00 ET
    assert _session_work_date_et(datetime(2026, 7, 30, 2, 0, 0, tzinfo=UTC)) == date(
        2026, 7, 29
    )
    # Naive treated as UTC
    assert _session_work_date_et(datetime(2026, 7, 30, 14, 0, 0)) == date(2026, 7, 30)


def test_list_time_records_filters_temp_by_work_date_not_today():
    from backend.payroll_operations import list_time_records

    conn = MagicMock()
    c = MagicMock()
    conn.cursor.return_value = c
    c.fetchall.return_value = [
        {
            "id": 10,
            "user_id": 53,
            "clock_in_at": datetime(2026, 7, 30, 18, 0, 0),
            "clock_out_at": datetime(2026, 7, 30, 19, 0, 0),
            "status": "completed",
            "total_break_seconds": 0,
            "net_work_seconds": 3600,
            "manual_override": 0,
            "payroll_hours_approved": 1,
            "period_adjustment_remarks": None,
            "first_name": "Florentina",
            "last_name": "Llanto",
            "payroll_cycle_review_state": None,
        }
    ]

    with patch("backend.payroll_operations.payroll_profiles_active", return_value=True), patch(
        "backend.payroll_operations.ensure_payroll_hours_approved_column"
    ), patch("backend.payroll_operations.table_has_column", return_value=True), patch(
        "backend.payroll_operations.table_exists", return_value=False
    ), patch(
        "backend.payroll_workflow.resolve_worker_hourly_rate",
        return_value={
            "worker_category": "w2",
            "hourly_rate": 17.0,
            "rate_source": "user_rates",
            "rate_missing": False,
        },
    ), patch(
        "backend.payroll_operations.worker_category_for_user",
        side_effect=lambda conn, uid, *, on=None, assignments=None: (
            "temp" if on and on < date(2026, 8, 24) else "w2"
        ),
    ), patch(
        "backend.payroll_operations.time_record_status",
        return_value="approved",
    ):
        temp_items = list_time_records(
            conn, 1, from_date="2026-07-27", to_date="2026-08-02", worker_category="temp"
        )
        w2_items = list_time_records(
            conn, 1, from_date="2026-07-27", to_date="2026-08-02", worker_category="w2"
        )

    assert len(temp_items) == 1
    assert temp_items[0]["worker_category"] == "temp"
    assert temp_items[0]["worker_name"].startswith("Florentina")
    assert w2_items == []
