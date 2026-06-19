"""Tests for sorting chronology (read-only shift analysis timeline)."""

from datetime import date, datetime

from backend.rinse_bag_stage_bounds import gaming_events_from_records
from backend.rinse_sorting_chronology import (
    build_sorting_chronology_summary,
    chronology_rows_with_gaps,
    extract_sorting_sessions_for_bag,
    _duration_seconds,
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


def _anchored_sorting_day_events():
    """Sorting session on SELECTED with explicit cleaning start and add-photos end."""
    return [
        _ev("sent-to-vendor", datetime(2026, 6, 17, 8, 0), ev_id=1),
        _ev("cleaning", datetime(2026, 6, 18, 8, 50), ev_id=2, scan_index=2),
        _ev("weight-entry", datetime(2026, 6, 18, 9, 0), ev_id=3, scan_index=3),
        _ev("add-photos", datetime(2026, 6, 18, 9, 10), ev_id=4, scan_index=4),
        _ev("start-cleaning", datetime(2026, 6, 18, 9, 20), ev_id=5, scan_index=5),
    ]


class TestSortingChronologySessions:
    def test_chronology_sorting_by_timestamp(self):
        bag_a = extract_sorting_sessions_for_bag(
            "BAG-A",
            gaming_events_from_records(_anchored_sorting_day_events()),
            selected_date_et=SELECTED,
        )
        bag_b_events = [
            _ev("sent-to-vendor", datetime(2026, 6, 17, 8, 0), ev_id=1),
            _ev("cleaning", datetime(2026, 6, 18, 10, 0), ev_id=2, scan_index=2, user="Bob"),
            _ev("weight-entry", datetime(2026, 6, 18, 10, 5), ev_id=3, scan_index=3, user="Bob"),
            _ev("add-photos", datetime(2026, 6, 18, 10, 15), ev_id=4, scan_index=4, user="Bob"),
            _ev("start-cleaning", datetime(2026, 6, 18, 10, 30), ev_id=5, scan_index=5, user="Bob"),
        ]
        bag_b = extract_sorting_sessions_for_bag(
            "BAG-B",
            gaming_events_from_records(bag_b_events),
            selected_date_et=SELECTED,
        )
        rows = chronology_rows_with_gaps(bag_a + bag_b)
        assert len(rows) == 2
        assert rows[0]["bag_id"] == "BAG-A"
        assert rows[1]["bag_id"] == "BAG-B"
        assert rows[0]["index"] == 1
        assert rows[1]["index"] == 2

    def test_duration_calculation(self):
        sessions = extract_sorting_sessions_for_bag(
            "BAG1",
            gaming_events_from_records(_anchored_sorting_day_events()),
            selected_date_et=SELECTED,
        )
        assert len(sessions) == 1
        assert sessions[0]["duration_seconds"] == 1200  # cleaning 8:50 → add-photos 9:10

    def test_gap_calculation(self):
        sessions = [
            {
                "bag_id": "A",
                "sort_start_et": datetime(2026, 6, 18, 9, 0),
                "sort_end_et": datetime(2026, 6, 18, 9, 10),
                "duration_seconds": 600,
            },
            {
                "bag_id": "B",
                "sort_start_et": datetime(2026, 6, 18, 9, 30),
                "sort_end_et": datetime(2026, 6, 18, 9, 40),
                "duration_seconds": 600,
            },
        ]
        rows = chronology_rows_with_gaps(sessions)
        assert rows[0]["gap_until_next_seconds"] == 1200  # 20 min gap
        assert rows[0]["next_sort_start_et"] == datetime(2026, 6, 18, 9, 30)
        assert rows[1]["gap_until_next_seconds"] is None

    def test_same_time_start_end_duration_zero(self):
        at = datetime(2026, 6, 18, 9, 0)
        assert _duration_seconds(at, at) == 0
        sessions = extract_sorting_sessions_for_bag(
            "BAG1",
            gaming_events_from_records(_anchored_sorting_day_events()),
            selected_date_et=SELECTED,
        )
        assert sessions[0]["duration_seconds"] >= 0

    def test_empty_state(self):
        summary = build_sorting_chronology_summary([])
        assert summary["total_sessions"] == 0
        assert summary["total_sorting_seconds"] == 0
        assert summary["first_sort_start_et"] is None
        rows = chronology_rows_with_gaps([])
        assert rows == []

    def test_confidence_exact_when_cleaning_and_marker_end(self):
        sessions = extract_sorting_sessions_for_bag(
            "BAG1",
            gaming_events_from_records(_anchored_sorting_day_events()),
            selected_date_et=SELECTED,
        )
        assert sessions[0]["confidence"] == "exact"

    def test_confidence_inferred_when_start_is_weight(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 17, 8, 0), ev_id=1),
            _ev("weight-entry", datetime(2026, 6, 18, 9, 0), ev_id=2, scan_index=2),
            _ev("add-photos", datetime(2026, 6, 18, 9, 10), ev_id=3, scan_index=3),
            _ev("start-cleaning", datetime(2026, 6, 18, 9, 20), ev_id=4, scan_index=4),
        ]
        sessions = extract_sorting_sessions_for_bag(
            "BAG1",
            gaming_events_from_records(events),
            selected_date_et=SELECTED,
        )
        assert sessions[0]["confidence"] == "inferred"

    def test_one_session_when_multiple_weight_scans_before_add_photos(self):
        """Maria Jun 18 pattern: repeated scale scans must not duplicate rows."""
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
        sessions = extract_sorting_sessions_for_bag(
            "D6E0SRN9QV",
            events,
            selected_date_et=SELECTED,
        )
        assert len(sessions) == 1
        assert sessions[0]["employee"] == "Maria"
        assert sessions[0]["source"] == "cleaning → add-photos"
        assert sessions[0]["confidence"] == "exact"

    def test_one_session_when_multiple_weight_scans_end_at_create_issue(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 17, 6, 0), ev_id=1),
            _ev("cleaning", datetime(2026, 6, 18, 7, 10), ev_id=2, scan_index=2, user="Maria"),
        ]
        for idx, minute in enumerate((18, 19, 20, 21, 22), start=3):
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
                _ev("add-photos", datetime(2026, 6, 18, 7, 23), ev_id=8, scan_index=8, user="Maria"),
                _ev("create-issue", datetime(2026, 6, 18, 7, 28), ev_id=9, scan_index=9, user="Maria"),
                _ev("start-cleaning", datetime(2026, 6, 18, 7, 35), ev_id=10, scan_index=10, user="Maria"),
            ]
        )
        sessions = extract_sorting_sessions_for_bag(
            "1VMV2DUPUW",
            events,
            selected_date_et=SELECTED,
        )
        assert len(sessions) == 1
        assert sessions[0]["source"] == "cleaning → create-issue"
        assert sessions[0]["end_event_purpose"] == "create-issue"
