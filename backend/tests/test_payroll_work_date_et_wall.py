"""Time Records work_date / payroll week follow the Eastern wall clock-in date.

``shift_sessions.clock_in_at`` is naive America/New_York wall time
(``eastern_now_naive``). Treating it as UTC shifted shifts that start before
04:00 EDT / 05:00 EST onto the previous day (and, on the payroll week's first
day, into the previous payroll week for overtime).
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from backend.payroll_operations import _session_work_date_et, list_time_records
from backend.payroll_overtime import aggregate_classified_batch_lines

UTC = ZoneInfo("UTC")


def _monday_week_bounds(_conn, d, _organization_id=1):
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


class _FakeLookup:
    def rate_for(self, uid):
        return {"worker_category": "w2", "hourly_rate": 17.0, "rate_source": "user_rates"}

    def category_for(self, uid, on=None):
        return "w2"


def _session(sid, clock_in, clock_out, *, user_id=61, first="Lily", last="Chen"):
    return {
        "id": sid,
        "user_id": user_id,
        "clock_in_at": clock_in,
        "clock_out_at": clock_out,
        "status": "completed",
        "total_break_seconds": 0,
        "net_work_seconds": int((clock_out - clock_in).total_seconds()),
        "manual_override": 0,
        "payroll_hours_approved": 1,
        "period_adjustment_remarks": None,
        "first_name": first,
        "last_name": last,
        "payroll_cycle_review_state": None,
    }


def _list(rows, segments=None, *, from_date="2026-10-05", to_date="2026-10-11"):
    conn = MagicMock()
    c = MagicMock()
    conn.cursor.return_value = c
    c.fetchall.side_effect = [rows, segments or []]
    with patch("backend.payroll_operations.payroll_profiles_active", return_value=True), patch(
        "backend.payroll_operations.ensure_payroll_hours_approved_column"
    ), patch("backend.payroll_operations.table_has_column", return_value=True), patch(
        "backend.payroll_operations.table_exists", return_value=segments is not None
    ), patch(
        "backend.payroll_list_lookup_cache.build_payroll_list_lookup_cache",
        return_value=_FakeLookup(),
    ), patch(
        "backend.payroll_identity.payroll_week_bounds", side_effect=_monday_week_bounds
    ), patch(
        "backend.payroll_week_ot.load_employee_week_ot_modes", return_value={}
    ), patch(
        "backend.payroll_time_record_breaks.attach_breaks_to_time_records"
    ):
        return list_time_records(conn, 3, from_date=from_date, to_date=to_date)


# Lily Chen, session 1737: 14 role segments, stored naive ET wall times.
_LILY_SEGMENT_BOUNDS = [
    ("03:56:00", "04:59:23"), ("04:59:23", "06:11:36"), ("06:11:36", "06:36:16"),
    ("06:36:16", "08:59:28"), ("08:59:28", "09:06:57"), ("09:06:57", "09:54:47"),
    ("09:54:47", "10:01:11"), ("10:01:11", "10:02:22"), ("10:02:22", "10:03:25"),
    ("10:03:25", "10:12:37"), ("10:12:37", "10:12:46"), ("10:12:46", "12:31:20"),
    ("12:31:20", "13:09:08"), ("13:09:08", "14:47:00"),
]


def _lily_segments():
    out = []
    for i, (s, e) in enumerate(_LILY_SEGMENT_BOUNDS):
        out.append(
            {
                "id": 1695 + i,
                "shift_session_id": 1737,
                "category_id": 1,
                "role_id": 1,
                "category_name_snapshot": "Rinse HD" if i % 2 == 0 else "Rinse WF",
                "role_name_snapshot": "Operator",
                "started_at": datetime.fromisoformat(f"2026-10-07 {s}"),
                "ended_at": datetime.fromisoformat(f"2026-10-07 {e}"),
                "change_source": "check_in" if i == 0 else "switch",
            }
        )
    return out


def test_lily_chen_oct7_0356_shift_displays_oct7_with_segments_preserved():
    ci = datetime(2026, 10, 7, 3, 56, 0)
    co = datetime(2026, 10, 7, 14, 47, 0)
    items = _list([_session(1737, ci, co)], _lily_segments())

    assert len(items) == 1
    rec = items[0]
    assert rec["work_date"] == "2026-10-07"
    assert rec["payroll_week_start"] == "2026-10-05"
    assert str(rec["clock_in_at"]).startswith("2026-10-07")
    assert str(rec["clock_in_at"])[11:16] == "03:56"
    assert str(rec["clock_out_at"])[11:16] == "14:47"
    assert rec["approved_hours"] == round(39060 / 3600, 2)
    segs = rec["role_segments"]
    assert len(segs) == 14
    for seg, (s, e) in zip(segs, _LILY_SEGMENT_BOUNDS):
        assert str(seg["started_at"]).startswith("2026-10-07")
        assert str(seg["started_at"])[11:19] == s
        assert str(seg["ended_at"])[11:19] == e
    # Parent row date == edit-modal date (modal shows clock_in_at's own date).
    assert str(rec["clock_in_at"]).replace("T", " ")[:10] == rec["work_date"]


@pytest.mark.parametrize(
    "clock_in, expected",
    [
        (datetime(2026, 10, 7, 0, 0, 0), date(2026, 10, 7)),
        (datetime(2026, 10, 7, 2, 0, 0), date(2026, 10, 7)),
        (datetime(2026, 10, 7, 3, 59, 59), date(2026, 10, 7)),
        (datetime(2026, 10, 7, 5, 0, 0), date(2026, 10, 7)),
        (datetime(2026, 1, 13, 2, 0, 0), date(2026, 1, 13)),
        (datetime(2026, 1, 13, 4, 30, 0), date(2026, 1, 13)),
        (datetime(2026, 1, 13, 5, 0, 0), date(2026, 1, 13)),
        (datetime(2026, 10, 7, 9, 0, 0), date(2026, 10, 7)),
        (datetime(2026, 10, 7, 23, 59, 59), date(2026, 10, 7)),
    ],
)
def test_naive_clock_in_is_eastern_wall_date(clock_in, expected):
    assert _session_work_date_et(clock_in) == expected


def test_early_morning_and_daytime_rows_keep_clock_in_date():
    rows = [
        _session(1, datetime(2026, 10, 8, 2, 0), datetime(2026, 10, 8, 10, 0)),
        _session(2, datetime(2026, 10, 9, 5, 0), datetime(2026, 10, 9, 13, 0)),
        _session(3, datetime(2026, 10, 10, 9, 0), datetime(2026, 10, 10, 17, 0)),
    ]
    items = {r["id"]: r for r in _list(rows)}
    assert items[1]["work_date"] == "2026-10-08"
    assert items[2]["work_date"] == "2026-10-09"
    assert items[3]["work_date"] == "2026-10-10"
    assert {r["payroll_week_start"] for r in items.values()} == {"2026-10-05"}


def test_overnight_shift_attributed_to_clock_in_date():
    # Same rule as payroll_calendar_date_for_cycle: the clock-in ET date owns the shift.
    rows = [_session(1306, datetime(2026, 9, 5, 22, 6, 14), datetime(2026, 9, 6, 7, 59, 10))]
    items = _list(rows, from_date="2026-08-31", to_date="2026-09-06")
    assert items[0]["work_date"] == "2026-09-05"
    assert items[0]["payroll_week_start"] == "2026-08-31"


def test_overnight_shift_crossing_into_new_payroll_week_stays_in_clock_in_week():
    rows = [_session(1, datetime(2026, 10, 11, 22, 0), datetime(2026, 10, 12, 6, 0))]
    items = _list(rows)
    assert items[0]["work_date"] == "2026-10-11"
    assert items[0]["payroll_week_start"] == "2026-10-05"


@pytest.mark.parametrize(
    "value, expected",
    [
        # Aware UTC converts to New York.
        (datetime(2026, 10, 7, 7, 56, tzinfo=UTC), date(2026, 10, 7)),
        (datetime(2026, 10, 7, 3, 56, tzinfo=UTC), date(2026, 10, 6)),
        # Spring forward 2026-03-08 (02:00 EST -> 03:00 EDT).
        (datetime(2026, 3, 8, 4, 30, tzinfo=UTC), date(2026, 3, 7)),  # 23:30 EST
        (datetime(2026, 3, 8, 6, 30, tzinfo=UTC), date(2026, 3, 8)),  # 01:30 EST
        (datetime(2026, 3, 8, 7, 30, tzinfo=UTC), date(2026, 3, 8)),  # 03:30 EDT
        # Fall back 2026-11-01 (02:00 EDT -> 01:00 EST).
        (datetime(2026, 11, 1, 3, 30, tzinfo=UTC), date(2026, 10, 31)),  # 23:30 EDT
        (datetime(2026, 11, 1, 5, 30, tzinfo=UTC), date(2026, 11, 1)),  # 01:30 EDT
        (datetime(2026, 11, 1, 6, 30, tzinfo=UTC), date(2026, 11, 1)),  # 01:30 EST
        # Naive ET wall values around DST stay on their own calendar day.
        (datetime(2026, 3, 8, 2, 30), date(2026, 3, 8)),  # nonexistent wall time
        (datetime(2026, 11, 1, 1, 30), date(2026, 11, 1)),  # ambiguous wall time
        (datetime(2026, 3, 8, 0, 15), date(2026, 3, 8)),
        (datetime(2026, 11, 1, 0, 15), date(2026, 11, 1)),
        # Serialized strings.
        ("2026-10-07 03:56:00", date(2026, 10, 7)),
        ("2026-10-07T03:56:00", date(2026, 10, 7)),
        ("2026-10-07T03:56:00-04:00", date(2026, 10, 7)),
        ("2026-10-07T07:56:00Z", date(2026, 10, 7)),
        ("2026-10-07T02:30:00Z", date(2026, 10, 6)),
        (None, None),
        ("", None),
    ],
)
def test_utc_to_new_york_conversion_including_dst(value, expected):
    assert _session_work_date_et(value) == expected


def _week_rows():
    """Varun Kumar Mongia W2, batch 52 (paid, week of 2026-07-06): 48.65 h, Monday 01:56 start."""
    spans = [
        (520, "2026-07-06 01:56:42", 37188),
        (528, "2026-07-07 02:05:38", 35280),
        (539, "2026-07-08 02:00:00", 35280),
        (573, "2026-07-10 02:00:00", 35280),
        (580, "2026-07-11 02:00:00", 32112),
    ]
    rows = []
    for sid, start, secs in spans:
        ci = datetime.fromisoformat(start)
        rows.append(
            _session(sid, ci, ci + timedelta(seconds=secs), user_id=26, first="Varun", last="Kumar Mongia")
        )
    return rows


def test_monday_early_shift_stays_in_its_payroll_week_for_overtime():
    rows = _week_rows()
    total_h = sum(r["net_work_seconds"] for r in rows) / 3600
    items = _list(rows, from_date="2026-07-06", to_date="2026-07-12")
    assert {r["payroll_week_start"] for r in items} == {"2026-07-06"}
    by_id = {r["id"]: r for r in items}
    assert by_id[520]["work_date"] == "2026-07-06"

    lines = aggregate_classified_batch_lines(
        items,
        batch_category="w2",
        threshold_hours=Decimal("40"),
        ot_enabled=True,
        week_ot_enabled={"2026-07-06": True},
    )
    assert len(lines) == 1
    line = lines[0]
    assert line["approved_hours"] == 40.0
    assert line["ot_hours"] == pytest.approx(round(total_h - 40, 2), abs=0.01)
    assert line["approved_hours"] + line["ot_hours"] == pytest.approx(round(total_h, 2), abs=0.01)
    assert sorted(line["session_ids"]) == [520, 528, 539, 573, 580]


def test_weekly_totals_unchanged_for_daytime_week():
    rows = [
        _session(100 + i, datetime(2026, 10, 5 + i, 9, 0), datetime(2026, 10, 5 + i, 17, 0), user_id=7)
        for i in range(5)
    ]
    items = _list(rows)
    assert [r["work_date"] for r in sorted(items, key=lambda r: r["id"])] == [
        "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09",
    ]
    lines = aggregate_classified_batch_lines(
        items, batch_category="w2", threshold_hours=Decimal("40"), ot_enabled=True,
        week_ot_enabled={"2026-10-05": True},
    )
    assert lines[0]["approved_hours"] == 40.0
    assert lines[0]["ot_hours"] == 0.0
