"""Tests for washing chronology (read-only shift analysis timeline)."""

from datetime import date, datetime

from backend.rinse_washing_chronology import (
    build_washing_chronology_summary,
    extract_washing_rows_from_events,
)


SELECTED = date(2026, 6, 18)


def _ev(purpose, at, *, rack="W24-30-VW", scan_index=1, ev_id=1, user="Alex"):
    return {
        "id": ev_id,
        "bag_id": "BAG1",
        "rack": rack,
        "user_name": user,
        "purpose": purpose,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


class TestWashingChronologyRows:
    def test_start_cleaning_at_washer_is_one_row(self):
        events = [
            _ev("start-cleaning", datetime(2026, 6, 18, 10, 0), ev_id=1),
        ]
        rows = extract_washing_rows_from_events(events)
        assert len(rows) == 1
        assert rows[0]["washer_rack"] == "W24-30-VW"
        assert rows[0]["timestamp_et"] == datetime(2026, 6, 18, 10, 0)
        assert rows[0]["confidence"] == "exact"

    def test_split_order_two_rows_not_merged(self):
        events = [
            _ev("start-cleaning", datetime(2026, 6, 18, 10, 0), ev_id=1, scan_index=1),
            _ev(
                "start-cleaning",
                datetime(2026, 6, 18, 10, 5),
                ev_id=2,
                scan_index=2,
                rack="W29-40-VW",
            ),
        ]
        rows = extract_washing_rows_from_events(events)
        assert len(rows) == 2
        assert rows[0]["washer_rack"] == "W24-30-VW"
        assert rows[1]["washer_rack"] == "W29-40-VW"

    def test_start_cleaning_without_washer_rack_excluded(self):
        events = [
            _ev("start-cleaning", datetime(2026, 6, 18, 10, 0), rack="Scale"),
        ]
        rows = extract_washing_rows_from_events(events)
        assert rows == []

    def test_summary_counts(self):
        rows = extract_washing_rows_from_events(
            [
                _ev("start-cleaning", datetime(2026, 6, 18, 9, 0), ev_id=1),
                _ev(
                    "start-cleaning",
                    datetime(2026, 6, 18, 11, 0),
                    ev_id=2,
                    scan_index=2,
                    rack="W29-40-VW",
                ),
                _ev(
                    "start-cleaning",
                    datetime(2026, 6, 18, 12, 0),
                    ev_id=3,
                    scan_index=3,
                    rack="W29-40-VW",
                ),
            ]
        )
        summary = build_washing_chronology_summary(rows)
        assert summary["total_washer_loads"] == 3
        assert summary["unique_washers_used"] == 2
        assert summary["most_used_washer"] == "W29-40-VW"
        assert summary["first_washer_load_et"] == datetime(2026, 6, 18, 9, 0)
        assert summary["last_washer_load_et"] == datetime(2026, 6, 18, 12, 0)

    def test_D6E0SRN9QV_duplicate_ingest_collapses_to_one_row(self):
        """Jun 18 duplicate start-cleaning rows at same timestamp → one row, one rack."""
        ts = datetime(2026, 6, 18, 7, 31)
        events = []
        for ev_id in range(1, 9):
            rack = "W26-30-VW" if ev_id % 2 else "W25-30-VW"
            events.append(
                {
                    "id": ev_id,
                    "bag_id": "D6E0SRN9QV",
                    "rack": rack,
                    "last_location": "W25-30-VW" if rack == "W26-30-VW" else "W26-30-VW",
                    "user_name": "Jennifer",
                    "purpose": "start-cleaning",
                    "scanned_at_parsed": ts,
                    "scan_index": 1,
                }
            )
        rows = extract_washing_rows_from_events(events)
        assert len(rows) == 1
        assert rows[0]["washer_rack"] == "W26-30-VW"
        assert rows[0]["employee"] == "Jennifer"
        summary = build_washing_chronology_summary(rows)
        assert summary["total_washer_loads"] == 1

    def test_duplicate_same_rack_same_timestamp_one_row(self):
        ts = datetime(2026, 6, 18, 7, 35)
        events = [
            _ev(
                "start-cleaning",
                ts,
                ev_id=i,
                rack="W29-40-VW",
                user="Jennifer",
            )
            for i in range(1, 9)
        ]
        for ev in events:
            ev["bag_id"] = "1VMV2DUPUW"
            ev["last_location"] = "W28-20-VW"
        rows = extract_washing_rows_from_events(events)
        assert len(rows) == 1
        assert rows[0]["washer_rack"] == "W29-40-VW"
        assert rows[0]["bag_id"] == "1VMV2DUPUW"

    def test_conflicting_rack_fields_on_one_event_uses_rack_column(self):
        ts = datetime(2026, 6, 18, 7, 31)
        events = [
            {
                "id": 1,
                "bag_id": "D6E0SRN9QV",
                "rack": "W26-30-VW",
                "last_location": "W25-30-VW",
                "user_name": "Jennifer",
                "purpose": "start-cleaning",
                "scanned_at_parsed": ts,
                "scan_index": 1,
            }
        ]
        rows = extract_washing_rows_from_events(events)
        assert len(rows) == 1
        assert rows[0]["washer_rack"] == "W26-30-VW"
