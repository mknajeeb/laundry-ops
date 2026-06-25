"""Tests for sorting chronology (read-only shift analysis timeline)."""

from datetime import date, datetime, timedelta

from backend.rinse_bag_stage_bounds import gaming_events_from_records
from backend.rinse_sorting_chronology import (
    build_sorting_chronology_summary,
    chronology_rows_with_gaps,
    extract_sorting_sessions_for_bag,
    _cap_sessions_by_employee_busy_periods,
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

    def test_one_session_when_duplicate_add_photos_rows_same_timestamp(self):
        """Repeated add-photos scan rows for one cycle must not duplicate chronology rows."""
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
        for dup in range(4):
            events.append(
                _ev(
                    "add-photos",
                    datetime(2026, 6, 18, 7, 17),
                    ev_id=100 + dup,
                    scan_index=8 + dup,
                    user="Maria",
                )
            )
        events.append(
            _ev("start-cleaning", datetime(2026, 6, 18, 7, 30), ev_id=200, scan_index=20, user="Maria")
        )
        sessions = extract_sorting_sessions_for_bag(
            "D6E0SRN9QV",
            events,
            selected_date_et=SELECTED,
        )
        assert len(sessions) == 1
        assert sessions[0]["employee"] == "Maria"

    def test_86CK96LI6E_cross_employee_weight_not_sort_start(self):
        """Jennifer weight early + Maria add-photos later must not span 90+ minutes."""
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 17, 6, 0), ev_id=1),
            _ev(
                "weight-entry",
                datetime(2026, 6, 18, 7, 47),
                ev_id=2,
                scan_index=2,
                user="Jennifer",
            ),
            _ev(
                "add-photos",
                datetime(2026, 6, 18, 9, 19),
                ev_id=3,
                scan_index=3,
                user="Maria",
            ),
            _ev(
                "start-cleaning",
                datetime(2026, 6, 18, 10, 31),
                ev_id=4,
                scan_index=4,
                user="Jennifer",
            ),
        ]
        sessions = extract_sorting_sessions_for_bag(
            "86CK96LI6E",
            events,
            selected_date_et=SELECTED,
        )
        assert len(sessions) == 1
        assert sessions[0]["employee"] == "Maria"
        assert sessions[0]["sort_start_et"] == datetime(2026, 6, 18, 9, 19)
        assert sessions[0]["sort_end_et"] == datetime(2026, 6, 18, 9, 19)
        assert sessions[0]["duration_seconds"] == 0

    def test_86CK96LI6E_inter_session_cap_when_maria_sorted_other_bags(self):
        """Maria sorting other bags between Jennifer weigh and Maria add-photos caps duration."""
        bag_ids = ["BAG6", "BAG7", "BAG8", "BAG9", "BAG10", "BAG11"]
        events_by_bag: dict[str, list[dict]] = {}
        base = datetime(2026, 6, 18, 7, 48)
        for idx, bag_id in enumerate(bag_ids):
            start = base + timedelta(minutes=idx * 10)
            end = start + timedelta(minutes=8)
            events_by_bag[bag_id] = [
                _ev("sent-to-vendor", datetime(2026, 6, 17, 6, 0), ev_id=idx * 10 + 1),
                _ev("cleaning", start, ev_id=idx * 10 + 2, scan_index=2, user="Maria"),
                _ev(
                    "weight-entry",
                    start + timedelta(minutes=1),
                    ev_id=idx * 10 + 3,
                    scan_index=3,
                    user="Maria",
                ),
                _ev("add-photos", end, ev_id=idx * 10 + 4, scan_index=4, user="Maria"),
                _ev(
                    "start-cleaning",
                    end + timedelta(minutes=1),
                    ev_id=idx * 10 + 5,
                    scan_index=5,
                    user="Maria",
                ),
            ]

        heavy_events = [
            _ev("sent-to-vendor", datetime(2026, 6, 17, 6, 0), ev_id=100),
            _ev(
                "weight-entry",
                datetime(2026, 6, 18, 7, 47),
                ev_id=101,
                scan_index=2,
                user="Jennifer",
            ),
            _ev(
                "add-photos",
                datetime(2026, 6, 18, 9, 19),
                ev_id=102,
                scan_index=3,
                user="Maria",
            ),
            _ev(
                "start-cleaning",
                datetime(2026, 6, 18, 10, 31),
                ev_id=103,
                scan_index=4,
                user="Jennifer",
            ),
        ]

        all_sessions: list[dict] = []
        for bag_id, events in events_by_bag.items():
            all_sessions.extend(
                extract_sorting_sessions_for_bag(
                    bag_id,
                    events,
                    selected_date_et=SELECTED,
                )
            )
        all_sessions.extend(
            extract_sorting_sessions_for_bag(
                "86CK96LI6E",
                heavy_events,
                selected_date_et=SELECTED,
            )
        )

        capped = _cap_sessions_by_employee_busy_periods(all_sessions)
        heavy = next(s for s in capped if s["bag_id"] == "86CK96LI6E")
        last_maria_end = max(
            s["sort_end_et"]
            for s in capped
            if s.get("employee") == "Maria" and s["bag_id"] != "86CK96LI6E"
        )

        assert heavy["employee"] == "Maria"
        assert heavy["sort_start_et"] >= last_maria_end
        assert heavy["sort_end_et"] == datetime(2026, 6, 18, 9, 19)
        assert heavy["duration_seconds"] == _duration_seconds(
            heavy["sort_start_et"], heavy["sort_end_et"]
        )
        assert heavy["duration_seconds"] < 92 * 60

    def test_COXWJMCCPH_ready_washer_does_not_extend_sort_end(self):
        """Maria 8:21 start; end at split-load/create-issue, not 8:47 ready-washer."""
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 17, 6, 0), ev_id=1),
            _ev("cleaning", datetime(2026, 6, 18, 8, 21), ev_id=2, scan_index=2, user="Maria"),
            _ev("weight-entry", datetime(2026, 6, 18, 8, 22), ev_id=3, scan_index=3, user="Maria"),
            _ev("add-photos", datetime(2026, 6, 18, 8, 24), ev_id=4, scan_index=4, user="Maria"),
            _ev("split-load", datetime(2026, 6, 18, 8, 25), ev_id=5, scan_index=5, user="Maria"),
            _ev("create-issue", datetime(2026, 6, 18, 8, 26), ev_id=6, scan_index=6, user="Maria"),
            _ev("ready-washer", datetime(2026, 6, 18, 8, 47), ev_id=7, scan_index=7, user="Maria"),
            _ev("start-cleaning", datetime(2026, 6, 18, 8, 50), ev_id=8, scan_index=8, user="Maria"),
        ]
        sessions = extract_sorting_sessions_for_bag(
            "COXWJMCCPH",
            events,
            selected_date_et=SELECTED,
        )
        assert len(sessions) == 1
        assert sessions[0]["employee"] == "Maria"
        assert sessions[0]["sort_start_et"] == datetime(2026, 6, 18, 8, 21)
        assert sessions[0]["sort_end_et"] == datetime(2026, 6, 18, 8, 26)
        assert sessions[0]["end_event_purpose"] == "create-issue"
        assert sessions[0]["duration_seconds"] == 300

    def test_697BP084AA_ignores_jennifer_add_photos_after_wash_before_create_issue(self):
        """Maria 7:10 add-photos ends sort; start-cleaning before create-issue blocks Jennifer 51m row."""
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 17, 6, 0), ev_id=1),
            _ev(
                "cleaning",
                datetime(2026, 6, 18, 7, 0),
                ev_id=2,
                scan_index=2,
                user="Maria (Veewash)",
            ),
            _ev(
                "weight-entry",
                datetime(2026, 6, 18, 7, 5),
                ev_id=3,
                scan_index=3,
                user="Maria (Veewash)",
            ),
            _ev(
                "add-photos",
                datetime(2026, 6, 18, 7, 10),
                ev_id=4,
                scan_index=4,
                user="Maria (Veewash)",
            ),
            _ev(
                "start-cleaning",
                datetime(2026, 6, 18, 7, 12),
                ev_id=5,
                scan_index=5,
                user="Maria (Veewash)",
            ),
            _ev(
                "create-issue",
                datetime(2026, 6, 18, 7, 15),
                ev_id=6,
                scan_index=6,
                user="Maria (Veewash)",
            ),
            _ev(
                "cleaning",
                datetime(2026, 6, 18, 7, 16),
                ev_id=7,
                scan_index=7,
                user="Jennifer (VeeWash)",
            ),
            _ev(
                "add-photos",
                datetime(2026, 6, 18, 8, 7),
                ev_id=8,
                scan_index=8,
                user="Jennifer (VeeWash)",
            ),
        ]
        sessions = extract_sorting_sessions_for_bag(
            "697BP084AA",
            events,
            selected_date_et=SELECTED,
        )
        assert len(sessions) == 1
        assert sessions[0]["employee"] == "Maria (Veewash)"
        assert sessions[0]["sort_start_et"] == datetime(2026, 6, 18, 7, 0)
        assert sessions[0]["sort_end_et"] == datetime(2026, 6, 18, 7, 15)
        assert sessions[0]["duration_seconds"] == 15 * 60
        assert sessions[0]["source"] == "cleaning → create-issue"

    def test_D6E0SRN9QV_ignores_jennifer_add_photos_after_wash_setup(self):
        """Maria 7:17–7:18 exact; Jennifer 7:31 washer add-photos must not create a row."""
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
                _ev("add-photos", datetime(2026, 6, 18, 7, 18), ev_id=9, scan_index=9, user="Maria"),
                _ev("start-cleaning", datetime(2026, 6, 18, 7, 30), ev_id=10, scan_index=10, user="Maria"),
                _ev(
                    "weight-entry",
                    datetime(2026, 6, 18, 7, 30),
                    ev_id=11,
                    scan_index=11,
                    user="Jennifer",
                ),
                _ev(
                    "add-photos",
                    datetime(2026, 6, 18, 7, 31),
                    ev_id=12,
                    scan_index=12,
                    user="Jennifer",
                ),
            ]
        )
        sessions = extract_sorting_sessions_for_bag(
            "D6E0SRN9QV",
            events,
            selected_date_et=SELECTED,
        )
        assert len(sessions) == 1
        assert sessions[0]["employee"] == "Maria"
        assert sessions[0]["sort_start_et"] == datetime(2026, 6, 18, 7, 10)
        assert sessions[0]["sort_end_et"] == datetime(2026, 6, 18, 7, 17)

    def test_1VMV2DUPUW_ignores_jennifer_add_photos_after_create_issue(self):
        """Maria 7:20–7:28 only; Jennifer washer add-photos at 7:35 must not appear."""
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 17, 6, 0), ev_id=1),
            _ev("cleaning", datetime(2026, 6, 18, 7, 20), ev_id=2, scan_index=2, user="Maria"),
        ]
        for idx, minute in enumerate((21, 22, 23), start=3):
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
                _ev("add-photos", datetime(2026, 6, 18, 7, 23), ev_id=6, scan_index=6, user="Maria"),
                _ev("create-issue", datetime(2026, 6, 18, 7, 28), ev_id=7, scan_index=7, user="Maria"),
                _ev("start-cleaning", datetime(2026, 6, 18, 7, 35), ev_id=8, scan_index=8, user="Maria"),
                _ev(
                    "weight-entry",
                    datetime(2026, 6, 18, 7, 35),
                    ev_id=9,
                    scan_index=9,
                    user="Jennifer",
                ),
                _ev(
                    "add-photos",
                    datetime(2026, 6, 18, 7, 36),
                    ev_id=10,
                    scan_index=10,
                    user="Jennifer",
                ),
            ]
        )
        sessions = extract_sorting_sessions_for_bag(
            "1VMV2DUPUW",
            events,
            selected_date_et=SELECTED,
        )
        assert len(sessions) == 1
        assert sessions[0]["employee"] == "Maria"
        assert sessions[0]["sort_start_et"] == datetime(2026, 6, 18, 7, 20)
        assert sessions[0]["sort_end_et"] == datetime(2026, 6, 18, 7, 28)

    def test_COXWJMCCPH_ignores_jennifer_add_photos_after_ready_washer(self):
        """Maria 8:21–8:26 only; Jennifer add-photos after ready-washer must not appear."""
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 17, 6, 0), ev_id=1),
            _ev("cleaning", datetime(2026, 6, 18, 8, 21), ev_id=2, scan_index=2, user="Maria"),
            _ev("weight-entry", datetime(2026, 6, 18, 8, 22), ev_id=3, scan_index=3, user="Maria"),
            _ev("add-photos", datetime(2026, 6, 18, 8, 24), ev_id=4, scan_index=4, user="Maria"),
            _ev("split-load", datetime(2026, 6, 18, 8, 25), ev_id=5, scan_index=5, user="Maria"),
            _ev("create-issue", datetime(2026, 6, 18, 8, 26), ev_id=6, scan_index=6, user="Maria"),
            _ev("ready-washer", datetime(2026, 6, 18, 8, 47), ev_id=7, scan_index=7, user="Maria"),
            _ev(
                "weight-entry",
                datetime(2026, 6, 18, 8, 47),
                ev_id=8,
                scan_index=8,
                user="Jennifer",
            ),
            _ev(
                "add-photos",
                datetime(2026, 6, 18, 8, 48),
                ev_id=9,
                scan_index=9,
                user="Jennifer",
            ),
            _ev("start-cleaning", datetime(2026, 6, 18, 8, 50), ev_id=10, scan_index=10, user="Maria"),
        ]
        sessions = extract_sorting_sessions_for_bag(
            "COXWJMCCPH",
            events,
            selected_date_et=SELECTED,
        )
        assert len(sessions) == 1
        assert sessions[0]["employee"] == "Maria"
        assert sessions[0]["sort_start_et"] == datetime(2026, 6, 18, 8, 21)
        assert sessions[0]["sort_end_et"] == datetime(2026, 6, 18, 8, 26)

    def test_BZABOG8NPP_wash_handoff_add_photos_credits_weigh_operator(self):
        """Francis sorted/weighed; Joshua add-photos bundled with start-cleaning is wash handoff."""
        at = datetime
        events = [
            _ev("sent-to-vendor", at(2026, 6, 24, 4, 33), ev_id=1, user="Melissa"),
            _ev("weight-entry", at(2026, 6, 24, 9, 43), ev_id=2, scan_index=10, user="Francis (Veewash)"),
            _ev("cleaning", at(2026, 6, 24, 9, 43), ev_id=3, scan_index=11, user="Francis (Veewash)"),
            _ev("cleaning", at(2026, 6, 24, 10, 43), ev_id=4, scan_index=9, user="Francis (Veewash)"),
            _ev("start-cleaning", at(2026, 6, 24, 11, 11), ev_id=5, scan_index=3, user="Joshua (Veewash)"),
            _ev("ready-washer", at(2026, 6, 24, 11, 11), ev_id=6, scan_index=5, user="Joshua (Veewash)"),
            _ev("add-photos", at(2026, 6, 24, 11, 11), ev_id=7, scan_index=6, user="Joshua (Veewash)"),
        ]
        sessions = extract_sorting_sessions_for_bag(
            "BZABOG8NPP",
            events,
            selected_date_et=date(2026, 6, 24),
        )
        assert len(sessions) == 1
        assert sessions[0]["employee"] == "Francis (Veewash)"
        assert sessions[0]["sort_start_et"] == at(2026, 6, 24, 9, 43)
        assert sessions[0]["sort_end_et"] == at(2026, 6, 24, 10, 43)
        assert sessions[0]["duration_seconds"] == 3600


class TestRepeatTripSortingCycleBoundaries:
    """Regression: repeat-trip bags must not stretch sorting across vendor cycles."""

    def test_DJMFG1YEH7_latest_vendor_cycle_only_on_selected_day(self):
        """Francis Jun 17 sort must not appear on Jun 25; Maria 9:33→9:39 only."""
        at = datetime
        events = [
            _ev("sent-to-vendor", at(2026, 6, 17, 4, 30), ev_id=1, user="Melissa"),
            _ev(
                "cleaning",
                at(2026, 6, 17, 9, 0),
                ev_id=2,
                scan_index=2,
                user="Francis (Veewash)",
            ),
            _ev(
                "weight-entry",
                at(2026, 6, 17, 9, 5),
                ev_id=3,
                scan_index=3,
                user="Francis (Veewash)",
            ),
            _ev(
                "add-photos",
                at(2026, 6, 17, 9, 43),
                ev_id=4,
                scan_index=4,
                user="Francis (Veewash)",
            ),
            _ev(
                "start-cleaning",
                at(2026, 6, 17, 10, 43),
                ev_id=5,
                scan_index=5,
                user="Joshua (Veewash)",
            ),
            _ev("sent-to-vendor", at(2026, 6, 22, 4, 22), ev_id=10, user="Melissa"),
            _ev("weight-entry", at(2026, 6, 22, 7, 52), ev_id=11, scan_index=11, user="Maria"),
            _ev("add-photos", at(2026, 6, 22, 17, 4), ev_id=12, scan_index=12, user="Maria"),
            _ev("sent-to-vendor", at(2026, 6, 25, 5, 9), ev_id=20, user="Melissa"),
            _ev(
                "cleaning",
                at(2026, 6, 25, 9, 33),
                ev_id=21,
                scan_index=21,
                user="Maria (Veewash)",
            ),
            _ev(
                "weight-entry",
                at(2026, 6, 25, 9, 33),
                ev_id=22,
                scan_index=22,
                user="Maria (Veewash)",
            ),
            _ev(
                "add-photos",
                at(2026, 6, 25, 9, 38),
                ev_id=23,
                scan_index=23,
                user="Maria (Veewash)",
            ),
            _ev(
                "split-load",
                at(2026, 6, 25, 9, 39),
                ev_id=24,
                scan_index=24,
                user="Maria (Veewash)",
            ),
            _ev(
                "start-cleaning",
                at(2026, 6, 25, 10, 0),
                ev_id=25,
                scan_index=25,
                user="Joshua (Veewash)",
            ),
        ]
        jun25 = extract_sorting_sessions_for_bag(
            "DJMFG1YEH7",
            events,
            selected_date_et=date(2026, 6, 25),
        )
        assert len(jun25) == 1
        assert jun25[0]["employee"] == "Maria (Veewash)"
        assert jun25[0]["sort_start_et"] == at(2026, 6, 25, 9, 33)
        assert jun25[0]["sort_end_et"] == at(2026, 6, 25, 9, 39)
        assert jun25[0]["duration_seconds"] == 360
        assert not any("Francis" in str(s.get("employee") or "") for s in jun25)

        jun17_only = events[:5]
        jun17 = extract_sorting_sessions_for_bag(
            "DJMFG1YEH7",
            jun17_only,
            selected_date_et=date(2026, 6, 17),
        )
        assert len(jun17) == 1
        assert "Francis" in str(jun17[0]["employee"])
        assert jun17[0]["duration_seconds"] < 3 * 3600

    def test_sorting_end_capped_at_wash_handoff_not_later_cycle(self):
        """add-photos bundled with start-cleaning ends sort; later cycle add-photos ignored."""
        at = datetime
        events = [
            _ev("sent-to-vendor", at(2026, 6, 17, 4, 0), ev_id=1),
            _ev("cleaning", at(2026, 6, 17, 8, 0), ev_id=2, scan_index=2, user="Francis"),
            _ev("weight-entry", at(2026, 6, 17, 8, 5), ev_id=3, scan_index=3, user="Francis"),
            _ev("add-photos", at(2026, 6, 17, 8, 10), ev_id=4, scan_index=4, user="Francis"),
            _ev("start-cleaning", at(2026, 6, 17, 8, 10), ev_id=5, scan_index=5, user="Joshua"),
            _ev("sent-to-vendor", at(2026, 6, 25, 5, 9), ev_id=20),
            _ev("cleaning", at(2026, 6, 25, 9, 33), ev_id=21, scan_index=21, user="Maria"),
            _ev("weight-entry", at(2026, 6, 25, 9, 33), ev_id=22, scan_index=22, user="Maria"),
            _ev("add-photos", at(2026, 6, 25, 9, 39), ev_id=23, scan_index=23, user="Maria"),
        ]
        sessions = extract_sorting_sessions_for_bag(
            "REPEAT1",
            events,
            selected_date_et=date(2026, 6, 25),
        )
        assert len(sessions) == 1
        assert sessions[0]["employee"] == "Maria"
        assert sessions[0]["duration_seconds"] <= 6 * 60

    def test_lifecycle_anchor_uses_latest_sent_to_vendor(self):
        from backend.rinse_bag_stage_bounds import lifecycle_anchor

        at = datetime
        tl = gaming_events_from_records(
            [
                _ev("sent-to-vendor", at(2026, 6, 17, 4, 0), ev_id=1),
                _ev("add-photos", at(2026, 6, 17, 9, 0), ev_id=2, scan_index=2),
                _ev("sent-to-vendor", at(2026, 6, 25, 5, 9), ev_id=3, scan_index=3),
            ]
        )
        anchor_ts, _ = lifecycle_anchor(tl)
        assert anchor_ts == at(2026, 6, 25, 5, 9)
