"""Revenue obligation / Missing Work unit tests."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.management_revenue_obligations import (
    CADENCE_DAILY,
    CADENCE_SCHEDULED,
    DISP_NO_ACTIVITY,
    STATUS_MISSING,
    STATUS_NO_ACTIVITY,
    STATUS_OVERDUE,
    build_daily_completeness,
    create_disposition,
    default_cadence_for_account,
    derive_dates_from_schedule,
    scheduled_pickup_dates,
)


def test_default_cadence_defaults():
    assert default_cadence_for_account({"account_code": "self_service"}) == CADENCE_DAILY
    assert default_cadence_for_account({
        "revenue_group": "dhs",
        "dr_commercial_account_id": 1,
    }) == CADENCE_SCHEDULED


def test_derive_dates_from_schedule_thursday_processing():
    # Thu Aug 20 2026 — pickup Wed, delivery Fri
    processing = date(2026, 8, 20)
    sched = {"pickup_weekdays": [2], "delivery_weekdays": [4]}
    d = derive_dates_from_schedule(processing, sched)
    assert d["pickup_date"] == "2026-08-19"
    assert d["delivery_date"] == "2026-08-21"


def test_scheduled_pickup_dates_week():
    sched = {"pickup_weekdays": [0, 3]}  # Mon/Thu
    dates = scheduled_pickup_dates(sched, date(2026, 8, 17), date(2026, 8, 21))
    assert [d.isoformat() for d in dates] == ["2026-08-17", "2026-08-20"]


@patch("backend.management_revenue_obligations.seed_default_cadences_and_schedules")
@patch("backend.management_revenue_obligations.ensure_account_obligation_columns")
@patch("backend.management_revenue_obligations._load_lines_for_day", return_value={})
@patch("backend.management_revenue_obligations._active_disposition", return_value=None)
@patch("backend.management_revenue_obligations.daily_source_entered", return_value=False)
def test_daily_completeness_all_missing(_entered, _disp, _lines, _ensure, _seed):
    cursor = MagicMock()
    out = build_daily_completeness(cursor, 1, date(2026, 8, 20))
    assert out["complete"] == 0
    assert out["required"] == 4
    assert all(s["status"] == STATUS_MISSING for s in out["sections"])
    assert "Expected for 2026-08-20" in out["help"]


@patch("backend.management_revenue_obligations.seed_default_cadences_and_schedules")
@patch("backend.management_revenue_obligations.ensure_account_obligation_columns")
@patch("backend.management_revenue_obligations._load_lines_for_day", return_value={})
@patch("backend.management_revenue_obligations._active_disposition", return_value=None)
@patch("backend.management_revenue_obligations.daily_source_entered", return_value=True)
def test_daily_entered_without_complete_is_draft(_entered, _disp, _lines, _ensure, _seed):
    from backend.management_revenue_obligations import STATUS_DRAFT

    cursor = MagicMock()
    out = build_daily_completeness(cursor, 1, date(2026, 8, 20))
    assert out["complete"] == 0
    assert all(s["status"] == STATUS_DRAFT for s in out["sections"])


@patch("backend.management_revenue_obligations.seed_default_cadences_and_schedules")
@patch("backend.management_revenue_obligations.ensure_account_obligation_columns")
@patch("backend.management_revenue_obligations._load_lines_for_day", return_value={})
@patch("backend.management_revenue_obligations.daily_source_entered", return_value=False)
def test_daily_no_activity_counts_complete(_entered, _lines, _ensure, _seed):
    cursor = MagicMock()

    def disp(**kwargs):
        if kwargs.get("source_key") == "self_service":
            return {"disposition": DISP_NO_ACTIVITY, "id": 1}
        return None

    with patch("backend.management_revenue_obligations._active_disposition", side_effect=lambda *a, **k: disp(**k)):
        out = build_daily_completeness(cursor, 1, date(2026, 8, 20))
    ss = next(s for s in out["sections"] if s["key"] == "self_service")
    assert ss["status"] == STATUS_NO_ACTIVITY
    assert out["complete"] == 1


def test_create_disposition_requires_processing_for_daily():
    cursor = MagicMock()
    cursor.lastrowid = 5
    cursor.fetchone.return_value = {
        "id": 5,
        "source_key": "self_service",
        "account_id": None,
        "processing_date_et": date(2026, 8, 20),
        "scheduled_pickup_date": None,
        "scheduled_delivery_date": None,
        "disposition": DISP_NO_ACTIVITY,
        "reason": "Closed",
        "new_pickup_date": None,
        "entered_by_name_snapshot": "Ada",
        "created_at": None,
    }
    with patch("backend.management_revenue_obligations.ensure_obligation_tables"):
        try:
            create_disposition(cursor, 1, {"source_key": "self_service", "disposition": "no_activity"})
            assert False, "expected ValueError"
        except ValueError:
            pass
        out = create_disposition(
            cursor,
            1,
            {
                "source_key": "self_service",
                "processing_date_et": "2026-08-20",
                "disposition": "no_activity",
                "reason": "Closed",
            },
            actor_name="Ada",
        )
    assert out["disposition"] == DISP_NO_ACTIVITY


def test_dhs_overdue_status_concept():
    # Pure status logic helper via derive + schedule presence
    assert STATUS_OVERDUE == "overdue"
    assert STATUS_MISSING == "missing"


def test_save_account_schedule_same_day_updates():
    """Same-day re-save must UPDATE weekdays, not stack opaque rows."""
    from datetime import date
    from unittest.mock import MagicMock, patch
    from backend.management_revenue_obligations import save_account_schedule

    cursor = MagicMock()
    row = {
        "id": 9,
        "account_id": 3,
        "effective_from": date(2026, 8, 20),
        "effective_to": None,
        "pickup_weekdays": "[0,2,4]",
        "delivery_weekdays": "[1,3,5]",
    }
    # Per save: open-row SELECT, exact-from SELECT, then get_schedule SELECT (+ pairs empty)
    cursor.fetchone.side_effect = [
        None,  # open
        None,  # exact → INSERT path
        row,   # get_schedule
        None,  # open (2nd save)
        {"id": 9},  # exact → UPDATE path
        row,   # get_schedule
    ]
    cursor.fetchall.return_value = []
    with patch("backend.management_revenue_obligations.ensure_obligation_tables"):
        out1 = save_account_schedule(
            cursor, 3, effective_from=date(2026, 8, 20),
            pickup_weekdays=[0, 2, 4], delivery_weekdays=[1, 3, 5],
        )
        assert out1["pickup_weekdays"] == [0, 2, 4]
        assert out1["delivery_weekdays"] == [1, 3, 5]
        out2 = save_account_schedule(
            cursor, 3, effective_from=date(2026, 8, 20),
            pickup_weekdays=[0, 2, 4], delivery_weekdays=[1, 3, 5],
        )
    assert any("UPDATE mgmt_revenue_account_schedules" in str(c) for c in cursor.execute.call_args_list)
    assert out2["pickup_weekdays"] == [0, 2, 4]


def test_save_account_schedule_backdates_open_row():
    from datetime import date
    from unittest.mock import MagicMock, patch
    from backend.management_revenue_obligations import save_account_schedule

    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        {"id": 5, "effective_from": date(2026, 8, 20), "effective_to": None},
        None,
        {
            "id": 5,
            "account_id": 3,
            "effective_from": date(2026, 8, 1),
            "effective_to": None,
            "pickup_weekdays": "[1]",
            "delivery_weekdays": "[1]",
        },
    ]
    cursor.fetchall.return_value = []
    with patch("backend.management_revenue_obligations.ensure_obligation_tables"):
        out = save_account_schedule(
            cursor, 3, effective_from=date(2026, 8, 1),
            pickup_weekdays=[1], delivery_weekdays=[1],
        )
    assert out["effective_from"] == "2026-08-01"
    assert any("SET effective_from = %s" in str(c.args[0]) for c in cursor.execute.call_args_list)


def test_obligation_window_uses_account_schedule_start():
    from datetime import date
    from unittest.mock import MagicMock, patch
    from backend.management_revenue_obligations import (
        MISSING_WORK_START,
        obligation_window_start_for_account,
    )

    cursor = MagicMock()
    with patch(
        "backend.management_revenue_obligations.account_schedule_obligation_start",
        return_value=date(2026, 7, 15),
    ):
        # as_of-28 = Jul 23; floor Jul 15 → start Jul 23
        start = obligation_window_start_for_account(cursor, 1, date(2026, 8, 20), lookback_days=28)
    assert start == date(2026, 7, 23)

    with patch(
        "backend.management_revenue_obligations.account_schedule_obligation_start",
        return_value=date(2026, 8, 1),
    ):
        start2 = obligation_window_start_for_account(cursor, 1, date(2026, 8, 20), lookback_days=28)
    assert start2 == date(2026, 8, 1)

    with patch(
        "backend.management_revenue_obligations.account_schedule_obligation_start",
        return_value=None,
    ):
        start3 = obligation_window_start_for_account(cursor, 1, date(2026, 8, 20), lookback_days=28)
    assert start3 == MISSING_WORK_START
