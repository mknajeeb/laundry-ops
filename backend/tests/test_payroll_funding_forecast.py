"""Tests for payroll funding forecast."""

from datetime import date

from backend.payroll_funding_forecast import (
    build_funding_forecast,
    payment_date_for_week,
    _entry_in_forecast,
)


def test_payment_date_saturday_in_mon_sun_week():
    week_start = date(2026, 6, 8)  # Monday
    cal = {"work_week_start_day": 0, "payment_day_of_week": 5, "payment_lag_days": 0}
    pay = payment_date_for_week(week_start, cal)
    assert pay.weekday() == 5  # Saturday
    assert pay == date(2026, 6, 13)


def test_entry_in_forecast_respects_draft_published():
    assert _entry_in_forecast({"status": "scheduled", "publish_status": "draft"}, include_draft=True, include_published=True)
    assert not _entry_in_forecast({"status": "scheduled", "publish_status": "draft"}, include_draft=False, include_published=True)
    assert not _entry_in_forecast({"status": "cancelled", "publish_status": "published"}, include_draft=True, include_published=True)
    assert not _entry_in_forecast({"status": "replaced", "publish_status": "published"}, include_draft=True, include_published=True)


def test_build_funding_forecast_from_entries_override():
    conn = None
    entries = [
        {
            "worker_profile_id": 1,
            "work_date": "2026-06-09",
            "scheduled_hours": 8,
            "hourly_rate_snapshot": 20,
            "estimated_cost": 160,
            "status": "scheduled",
            "publish_status": "published",
            "worker_category_snapshot": "w2",
            "shift_name": "Morning",
            "role_name": "Operator",
            "work_stream_name": "Rinse",
            "worker_name": "Ana",
        },
        {
            "worker_profile_id": 2,
            "work_date": "2026-06-09",
            "scheduled_hours": 8,
            "hourly_rate_snapshot": 25,
            "estimated_cost": 200,
            "status": "scheduled",
            "publish_status": "draft",
            "worker_category_snapshot": "contractor_1099",
            "shift_name": "Morning",
            "role_name": "Folder",
            "work_stream_name": "Drop Off",
            "worker_name": "Bob",
        },
        {
            "worker_profile_id": 1,
            "work_date": "2026-06-10",
            "scheduled_hours": 8,
            "hourly_rate_snapshot": 20,
            "estimated_cost": 160,
            "status": "cancelled",
            "publish_status": "published",
            "worker_category_snapshot": "w2",
        },
    ]

    class FakeCursor:
        def execute(self, *args, **kwargs):
            pass

        def fetchall(self):
            return []

        def fetchone(self):
            return None

    class FakeConn:
        def cursor(self, dictionary=False):
            return FakeCursor()

    # Patch DB-heavy helpers
    import backend.payroll_funding_forecast as pff

    orig_get_cal = pff.get_calendar_settings
    orig_get_org = pff.get_org_schedule_settings
    pff.get_calendar_settings = lambda conn, oid: {
        "categories": {
            "default": {
                "work_week_start_day": 0,
                "payment_day_of_week": 5,
                "overtime_enabled": True,
                "overtime_threshold_hours": 40,
                "include_draft_schedule_in_forecast": True,
                "include_published_schedule_in_forecast": True,
            },
            "w2": {"overtime_enabled": True, "overtime_threshold_hours": 40},
            "contractor_1099": {"overtime_enabled": False},
        },
        "org_schedule_settings": {"overtime_threshold_hours": 40, "heavy_hours_threshold": 35, "underused_hours_threshold": 15},
    }
    pff.get_org_schedule_settings = lambda conn, oid: {
        "week_starts_on": 0,
        "overtime_threshold_hours": 40,
        "payment_day_of_week": 5,
    }
    pff.seed_schedule_defaults = lambda cursor, oid: None

    try:
        out = build_funding_forecast(
            FakeConn(),
            1,
            as_of_date="2026-06-09",
            entries_override=entries,
        )
    finally:
        pff.get_calendar_settings = orig_get_cal
        pff.get_org_schedule_settings = orig_get_org

    assert out["total_projected_cost"] == 360.0
    assert out["published_cost"] == 160.0
    assert out["draft_cost"] == 200.0
    assert out["category_breakdown"]["w2"]["cost"] == 160.0
    assert out["category_breakdown"]["contractor_1099"]["cost"] == 200.0
    assert out["estimated"] is True
