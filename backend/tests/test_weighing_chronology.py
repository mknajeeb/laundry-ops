"""Tests for weighing chronology (read-only shift analysis timeline)."""

from datetime import date, datetime

from backend.rinse_bag_stage_bounds import gaming_events_from_records
from backend.rinse_weighing_chronology import (
    build_weighing_chronology_summary,
    chronology_rows_with_gaps,
    extract_weighing_sessions_for_bag,
)


SELECTED = date(2026, 6, 18)


def _ev(purpose, at, *, scan_index=1, ev_id=1, user="Alex"):
    return {
        "id": ev_id,
        "rack": "Scale",
        "user_name": user,
        "purpose": purpose,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


def _anchored_weighing_day_events():
    return [
        _ev("sent-to-vendor", datetime(2026, 6, 17, 8, 0), ev_id=1),
        _ev("cleaning", datetime(2026, 6, 18, 8, 50), ev_id=2, scan_index=2),
        _ev("weight-entry", datetime(2026, 6, 18, 9, 0), ev_id=3, scan_index=3),
        _ev("add-photos", datetime(2026, 6, 18, 9, 10), ev_id=4, scan_index=4),
        _ev("start-cleaning", datetime(2026, 6, 18, 9, 20), ev_id=5, scan_index=5),
    ]


class TestWeighingChronologySessions:
    def test_cleaning_before_weight_gives_start(self):
        sessions = extract_weighing_sessions_for_bag(
            "BAG1",
            gaming_events_from_records(_anchored_weighing_day_events()),
            selected_date_et=SELECTED,
        )
        assert len(sessions) == 1
        assert sessions[0]["weigh_start_et"] == datetime(2026, 6, 18, 8, 50)
        assert sessions[0]["weigh_end_et"] == datetime(2026, 6, 18, 9, 0)
        assert sessions[0]["confidence"] == "exact"

    def test_first_weight_entry_is_end(self):
        sessions = extract_weighing_sessions_for_bag(
            "BAG1",
            gaming_events_from_records(_anchored_weighing_day_events()),
            selected_date_et=SELECTED,
        )
        assert sessions[0]["weigh_end_et"] == datetime(2026, 6, 18, 9, 0)
        assert sessions[0]["end_event_purpose"] == "weight-entry"

    def test_no_cleaning_fallback_zero_duration(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 17, 8, 0), ev_id=1),
            _ev("weight-entry", datetime(2026, 6, 18, 9, 0), ev_id=2, scan_index=2),
            _ev("add-photos", datetime(2026, 6, 18, 9, 10), ev_id=3, scan_index=3),
        ]
        sessions = extract_weighing_sessions_for_bag(
            "BAG1",
            events,
            selected_date_et=SELECTED,
        )
        assert len(sessions) == 1
        assert sessions[0]["weigh_start_et"] == datetime(2026, 6, 18, 9, 0)
        assert sessions[0]["weigh_end_et"] == datetime(2026, 6, 18, 9, 0)
        assert sessions[0]["duration_seconds"] == 0
        assert sessions[0]["confidence"] == "inferred"

    def test_later_sorting_washing_scans_do_not_extend_weighing(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 17, 8, 0), ev_id=1),
            _ev("cleaning", datetime(2026, 6, 18, 8, 50), ev_id=2, scan_index=2),
            _ev("weight-entry", datetime(2026, 6, 18, 9, 0), ev_id=3, scan_index=3),
            _ev("add-photos", datetime(2026, 6, 18, 9, 10), ev_id=4, scan_index=4),
            _ev("split-load", datetime(2026, 6, 18, 9, 12), ev_id=5, scan_index=5),
            _ev("ready-washer", datetime(2026, 6, 18, 9, 47), ev_id=6, scan_index=6),
            _ev("start-cleaning", datetime(2026, 6, 18, 10, 0), ev_id=7, scan_index=7),
        ]
        sessions = extract_weighing_sessions_for_bag(
            "BAG1",
            events,
            selected_date_et=SELECTED,
        )
        assert len(sessions) == 1
        assert sessions[0]["weigh_end_et"] == datetime(2026, 6, 18, 9, 0)
        assert sessions[0]["duration_seconds"] == 600

    def test_multiple_weight_scans_one_session_first_weight_is_end(self):
        """Repeated scale scans must not duplicate rows; end at first weight."""
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 17, 6, 0), ev_id=1),
            _ev("cleaning", datetime(2026, 6, 18, 7, 10), ev_id=2, scan_index=2, user="Maria"),
        ]
        for idx, minute in enumerate((11, 12, 13, 14, 15), start=3):
            events.append(
                _ev(
                    "weight-entry",
                    datetime(2026, 6, 18, 7, minute),
                    ev_id=idx,
                    scan_index=idx,
                    user="Maria",
                )
            )
        events.extend(
            [
                _ev("add-photos", datetime(2026, 6, 18, 7, 17), ev_id=8, scan_index=8, user="Maria"),
                _ev("start-cleaning", datetime(2026, 6, 18, 7, 30), ev_id=9, scan_index=9, user="Maria"),
            ]
        )
        sessions = extract_weighing_sessions_for_bag(
            "D6E0SRN9QV",
            events,
            selected_date_et=SELECTED,
        )
        assert len(sessions) == 1
        assert sessions[0]["weigh_end_et"] == datetime(2026, 6, 18, 7, 11)
        assert sessions[0]["duration_seconds"] == 60

    def test_gap_calculation(self):
        sessions = [
            {
                "bag_id": "A",
                "weigh_start_et": datetime(2026, 6, 18, 9, 0),
                "weigh_end_et": datetime(2026, 6, 18, 9, 5),
                "duration_seconds": 300,
            },
            {
                "bag_id": "B",
                "weigh_start_et": datetime(2026, 6, 18, 9, 30),
                "weigh_end_et": datetime(2026, 6, 18, 9, 35),
                "duration_seconds": 300,
            },
        ]
        rows = chronology_rows_with_gaps(sessions)
        assert rows[0]["gap_until_next_seconds"] == 1500
        assert rows[0]["next_weigh_start_et"] == datetime(2026, 6, 18, 9, 30)

    def test_empty_state(self):
        summary = build_weighing_chronology_summary([])
        assert summary["total_sessions"] == 0
        assert summary["total_weighing_seconds"] == 0
        assert summary["first_weigh_start_et"] is None
