"""Business Time Contract — required risk fixes (cycle Z, presence ET bounds)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from backend.rinse_cycle_boundary import _event_ts
from backend.rinse_scan_freshness import freshness_from_day_and_presence
from backend.rinse_upload_batch_retention import et_date_range_to_utc_bounds

ET = ZoneInfo("America/New_York")
UTC = timezone.utc


def test_event_ts_zulu_converts_to_et_wall_not_stripped_digits():
    """UTC 04:30Z on Aug 9 is still Aug 8 evening ET — must not become 04:30 ET."""
    # 2026-08-09 03:30:00 UTC = 2026-08-08 23:30:00 EDT
    out = _event_ts({"scanned_at_parsed": "2026-08-09T03:30:00Z"})
    assert out == datetime(2026, 8, 8, 23, 30, 0)
    assert out.tzinfo is None


def test_event_ts_naive_iso_remains_et_wall():
    out = _event_ts({"scanned_at_parsed": "2026-08-08 15:00:00"})
    assert out == datetime(2026, 8, 8, 15, 0, 0)


def test_event_ts_aware_utc_datetime_to_et_wall():
    aware = datetime(2026, 8, 9, 3, 30, 0, tzinfo=UTC)
    out = _event_ts({"timestamp": aware})
    assert out == datetime(2026, 8, 8, 23, 30, 0)


def test_et_date_bounds_cover_late_evening_et_as_next_utc_calendar_day():
    """11:45 PM ET on Aug 8 is Aug 9 03:45 UTC — must fall inside Aug 8 ET bounds."""
    start_utc, end_utc = et_date_range_to_utc_bounds(date(2026, 8, 8), date(2026, 8, 8))
    late_et_as_utc = datetime(2026, 8, 8, 23, 45, 0, tzinfo=ET).astimezone(UTC).replace(
        tzinfo=None
    )
    assert start_utc <= late_et_as_utc <= end_utc
    # And that UTC stamp is on the next UTC calendar date:
    assert late_et_as_utc.date() == date(2026, 8, 9)


def test_historical_presence_filter_uses_utc_bounds_not_bare_et_date():
    cursor = MagicMock()

    def _exists(_c, name):
        return name in ("rinse_bag_scan_events", "rinse_cleaner_ticket_presence_runs")

    # MAX(scanned_at_parsed) then presence finished_at
    cursor.fetchone.side_effect = [
        {"mx": datetime(2026, 8, 8, 12, 0, 0)},
        {"finished_at": datetime(2026, 8, 9, 3, 45, 0)},
    ]

    with (
        patch(
            "backend.ta_helpers.table_exists",
            side_effect=_exists,
        ),
        patch(
            "backend.rinse_veewash_workload.today_et",
            return_value=date(2026, 8, 10),
        ),
    ):
        freshness_from_day_and_presence(
            cursor,
            3,
            date(2026, 8, 8),
            day_meta={"last_sync_at": datetime(2026, 8, 8, 20, 0, 0)},
        )

    # Second execute is the presence query — assert UTC bounds args
    presence_call = None
    for args, kwargs in cursor.execute.call_args_list:
        sql = args[0] if args else ""
        if "rinse_cleaner_ticket_presence_runs" in sql and "finished_at >=" in sql:
            presence_call = args
            break
    assert presence_call is not None
    org, start_utc, end_utc = presence_call[1]
    assert org == 3
    expect_start, expect_end = et_date_range_to_utc_bounds(date(2026, 8, 8), date(2026, 8, 8))
    assert start_utc == expect_start
    assert end_utc == expect_end
    # Must NOT pass bare date(2026,8,8) as the upper bound sentinel
    assert not isinstance(end_utc, date) or isinstance(end_utc, datetime)
    assert isinstance(end_utc, datetime)
