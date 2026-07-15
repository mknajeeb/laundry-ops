"""Tests for washing chronology (read-only shift analysis timeline)."""

from datetime import date, datetime, timedelta

from backend.rinse_washing_chronology import (
    build_washing_chronology_summary,
    extract_washing_rows_from_events,
)


SELECTED = date(2026, 6, 18)


def _ev(purpose, at, *, rack="W24-30-VW", scan_index=1, ev_id=1, user="Alex", bag_id="BAG1"):
    return {
        "id": ev_id,
        "bag_id": bag_id,
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

    def test_start_cleaning_without_washer_rack_kept_as_inferred(self):
        events = [
            _ev("start-cleaning", datetime(2026, 6, 18, 10, 0), rack="Scale"),
        ]
        rows = extract_washing_rows_from_events(events)
        assert len(rows) == 1
        assert rows[0]["washer_rack"] == "Scale"
        assert rows[0]["confidence"] == "inferred"

    def test_CPFZXT2NMR_style_veewash_clean_start_cleaning_included(self):
        """Early wash starts at facility Clean (no W code) must still appear for operators."""
        events = [
            {
                "id": 1,
                "bag_id": "CPFZXT2NMR",
                "rack": "VeeWash Clean",
                "user_name": "Singh (VeeWash)",
                "purpose": "start-cleaning",
                "scanned_at_parsed": datetime(2026, 7, 14, 6, 10),
                "scan_index": 1,
            },
            {
                "id": 2,
                "bag_id": "CPFZXT2NMR",
                "rack": "VeeWash Clean",
                "user_name": "Singh (VeeWash)",
                "purpose": "washer-settings",
                "scanned_at_parsed": datetime(2026, 7, 14, 6, 12),
                "scan_index": 2,
            },
            {
                "id": 3,
                "bag_id": "1LRORUB2CC",
                "rack": "W25-30-VW",
                "user_name": "Singh (VeeWash)",
                "purpose": "start-cleaning",
                "scanned_at_parsed": datetime(2026, 7, 14, 6, 52),
                "scan_index": 1,
            },
        ]
        rows = extract_washing_rows_from_events(events)
        assert len(rows) == 2
        assert rows[0]["bag_id"] == "CPFZXT2NMR"
        assert rows[0]["washer_rack"] == "VeeWash Clean"
        assert rows[0]["confidence"] == "inferred"
        assert rows[0]["employee"] == "Singh (VeeWash)"
        assert rows[1]["bag_id"] == "1LRORUB2CC"
        assert rows[1]["confidence"] == "exact"
        summary = build_washing_chronology_summary(rows)
        assert summary["first_washer_load_et"] == datetime(2026, 7, 14, 6, 10)
        assert summary["unique_washers_used"] == 1
        assert summary["most_used_washer"] == "W25-30-VW"

    def test_start_cleaning_infers_w_rack_from_nearby_washer_settings(self):
        events = [
            _ev(
                "start-cleaning",
                datetime(2026, 6, 18, 10, 0),
                rack="VeeWash Clean",
                ev_id=1,
            ),
            {
                "id": 2,
                "bag_id": "BAG1",
                "rack": "W24-30-VW",
                "user_name": "Alex",
                "purpose": "washer-settings",
                "scanned_at_parsed": datetime(2026, 6, 18, 10, 2),
                "scan_index": 2,
            },
        ]
        rows = extract_washing_rows_from_events(events)
        assert len(rows) == 1
        assert rows[0]["washer_rack"] == "W24-30-VW"
        assert rows[0]["confidence"] == "inferred"

    def test_washer_settings_outside_window_not_inferred(self):
        events = [
            _ev(
                "start-cleaning",
                datetime(2026, 6, 18, 10, 0),
                rack="VeeWash Clean",
                ev_id=1,
            ),
            {
                "id": 2,
                "bag_id": "BAG1",
                "rack": "W24-30-VW",
                "user_name": "Alex",
                "purpose": "washer-settings",
                "scanned_at_parsed": datetime(2026, 6, 18, 10, 20),
                "scan_index": 2,
            },
        ]
        rows = extract_washing_rows_from_events(events)
        assert len(rows) == 1
        assert rows[0]["washer_rack"] == "VeeWash Clean"
        assert rows[0]["confidence"] == "inferred"

    def test_ready_washer_does_not_infer_machine(self):
        events = [
            _ev(
                "start-cleaning",
                datetime(2026, 6, 18, 10, 0),
                rack="VeeWash Clean",
                ev_id=1,
            ),
            {
                "id": 2,
                "bag_id": "BAG1",
                "rack": "W24-30-VW",
                "user_name": "Alex",
                "purpose": "ready-washer",
                "scanned_at_parsed": datetime(2026, 6, 18, 10, 2),
                "scan_index": 2,
            },
        ]
        rows = extract_washing_rows_from_events(events)
        assert len(rows) == 1
        assert rows[0]["washer_rack"] == "VeeWash Clean"

    def test_does_not_borrow_w_rack_from_later_start_cleaning_load(self):
        events = [
            _ev(
                "start-cleaning",
                datetime(2026, 6, 18, 10, 0),
                rack="VeeWash Clean",
                ev_id=1,
                bag_id="BAG1",
            ),
            _ev(
                "start-cleaning",
                datetime(2026, 6, 18, 10, 5),
                rack="VeeWash Clean",
                ev_id=2,
                scan_index=2,
                bag_id="BAG1",
            ),
            {
                "id": 3,
                "bag_id": "BAG1",
                "rack": "W25-30-VW",
                "user_name": "Alex",
                "purpose": "washer-settings",
                "scanned_at_parsed": datetime(2026, 6, 18, 10, 6),
                "scan_index": 3,
            },
        ]
        rows = extract_washing_rows_from_events(events)
        assert len(rows) == 2
        assert rows[0]["washer_rack"] == "VeeWash Clean"
        assert rows[0]["confidence"] == "inferred"
        assert rows[1]["washer_rack"] == "W25-30-VW"
        assert rows[1]["confidence"] == "inferred"

    def test_require_direct_washer_rack_excludes_veewash_clean(self):
        events = [
            _ev(
                "start-cleaning",
                datetime(2026, 6, 18, 10, 0),
                rack="VeeWash Clean",
                ev_id=1,
            ),
            _ev(
                "start-cleaning",
                datetime(2026, 6, 18, 10, 5),
                rack="W24-30-VW",
                ev_id=2,
                scan_index=2,
            ),
        ]
        rows = extract_washing_rows_from_events(
            events,
            require_direct_washer_rack=True,
        )
        assert len(rows) == 1
        assert rows[0]["washer_rack"] == "W24-30-VW"
        assert rows[0]["confidence"] == "exact"

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
        assert summary["total_washer_loads"] == 2
        assert summary["unique_bags_washed"] == 1
        assert summary["split_bags_washed"] == 1
        assert summary["single_bags_washed"] == 0
        assert summary["unique_bag_ids"] == 1
        assert summary["unique_washers_used"] == 2
        assert summary["most_used_washer"] in ("W24-30-VW", "W29-40-VW")
        assert summary["first_washer_load_et"] == datetime(2026, 6, 18, 9, 0)
        assert summary["last_washer_load_et"] == datetime(2026, 6, 18, 11, 0)

    def test_D6E0SRN9QV_split_load_same_timestamp_two_racks(self):
        """Split load: W26 and W25 start-cleaning at same timestamp → two rows."""
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
            },
            {
                "id": 2,
                "bag_id": "D6E0SRN9QV",
                "rack": "W25-30-VW",
                "last_location": "W26-30-VW",
                "user_name": "Jennifer",
                "purpose": "start-cleaning",
                "scanned_at_parsed": ts,
                "scan_index": 2,
            },
        ]
        rows = extract_washing_rows_from_events(events)
        assert len(rows) == 2
        assert {r["washer_rack"] for r in rows} == {"W26-30-VW", "W25-30-VW"}
        assert all(r["employee"] == "Jennifer" for r in rows)
        assert all(r["timestamp_et"] == ts for r in rows)

    def test_D6E0SRN9QV_duplicate_ingest_same_rack_collapses_to_one_row(self):
        """Eight duplicate ingest rows at same timestamp and rack → one row."""
        ts = datetime(2026, 6, 18, 7, 31)
        events = []
        for ev_id in range(1, 9):
            events.append(
                {
                    "id": ev_id,
                    "bag_id": "D6E0SRN9QV",
                    "rack": "W26-30-VW",
                    "last_location": "W25-30-VW",
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

    def test_duplicate_ingest_same_event_id_one_row(self):
        """Same scan event id repeated → one row."""
        ts = datetime(2026, 6, 18, 7, 31)
        events = [
            {
                "id": 42,
                "bag_id": "D6E0SRN9QV",
                "rack": "W26-30-VW",
                "user_name": "Jennifer",
                "purpose": "start-cleaning",
                "scanned_at_parsed": ts,
                "scan_index": 1,
            },
            {
                "id": 42,
                "bag_id": "D6E0SRN9QV",
                "rack": "W26-30-VW",
                "user_name": "Jennifer",
                "purpose": "start-cleaning",
                "scanned_at_parsed": ts,
                "scan_index": 1,
            },
        ]
        rows = extract_washing_rows_from_events(events)
        assert len(rows) == 1

    def test_D6E0SRN9QV_duplicate_ingest_alternating_racks_two_rows(self):
        """Eight duplicate ingest rows alternating W26/W25 at same timestamp → two rows."""
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
        assert len(rows) == 2
        assert {r["washer_rack"] for r in rows} == {"W26-30-VW", "W25-30-VW"}

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

    def test_same_timestamp_other_purpose_does_not_drop_start_cleaning(self):
        """ready-washer Last Scan at same bag+time must not steal the washer load row."""
        ts = datetime(2026, 6, 18, 7, 31)
        events = [
            {
                "id": 1,
                "bag_id": "D6E0SRN9QV",
                "rack": None,
                "user_name": "Jennifer (VeeWash)",
                "purpose": "ready-washer Last Scan",
                "scanned_at_parsed": ts,
                "scan_index": 1,
            },
            {
                "id": 2,
                "bag_id": "D6E0SRN9QV",
                "rack": "W26-30-VW",
                "user_name": "Jennifer (VeeWash)",
                "purpose": "start-cleaning",
                "scanned_at_parsed": ts,
                "scan_index": 2,
            },
        ]
        rows = extract_washing_rows_from_events(events)
        assert len(rows) == 1
        assert rows[0]["washer_rack"] == "W26-30-VW"
        assert rows[0]["employee"] == "Jennifer (VeeWash)"

    def test_many_start_cleaning_same_bag_capped_at_two(self):
        events = [
            _ev(
                "start-cleaning",
                datetime(2026, 6, 18, 7, 0) + timedelta(minutes=i),
                ev_id=i,
                user="Jennifer (VeeWash)",
            )
            for i in range(45)
        ]
        rows = extract_washing_rows_from_events(events)
        assert len(rows) == 2
        assert rows[0]["timestamp_et"] == datetime(2026, 6, 18, 7, 0)
        assert rows[1]["timestamp_et"] == datetime(2026, 6, 18, 7, 1)

    def test_three_start_cleaning_different_times_capped_at_two(self):
        events = [
            _ev("start-cleaning", datetime(2026, 6, 18, 8, 0), ev_id=1, rack="W24-30-VW"),
            _ev(
                "start-cleaning",
                datetime(2026, 6, 18, 9, 0),
                ev_id=2,
                scan_index=2,
                rack="W25-30-VW",
            ),
            _ev(
                "start-cleaning",
                datetime(2026, 6, 18, 10, 0),
                ev_id=3,
                scan_index=3,
                rack="W26-30-VW",
            ),
        ]
        rows = extract_washing_rows_from_events(events)
        assert len(rows) == 2
        assert [r["washer_rack"] for r in rows] == ["W24-30-VW", "W25-30-VW"]

    def test_forty_five_distinct_bags_one_start_cleaning_each(self):
        events = [
            {
                "id": i,
                "bag_id": f"BAG{i:03d}",
                "rack": "W24-30-VW",
                "user_name": "Jennifer (VeeWash)",
                "purpose": "start-cleaning",
                "scanned_at_parsed": datetime(2026, 6, 18, 7, 0) + timedelta(minutes=i),
                "scan_index": 1,
            }
            for i in range(45)
        ]
        rows = extract_washing_rows_from_events(events)
        assert len(rows) == 45
        assert len({r["bag_id"] for r in rows}) == 45
        summary = build_washing_chronology_summary(rows)
        assert summary["unique_bags_washed"] == 45
        assert summary["split_bags_washed"] == 0
        assert summary["single_bags_washed"] == 45
        assert summary["unique_bag_ids"] == 45
        assert summary["total_washer_loads"] == 45

    def test_summary_split_bags_count(self):
        rows = extract_washing_rows_from_events(
            [
                _ev("start-cleaning", datetime(2026, 6, 18, 9, 0), ev_id=1, rack="W24-30-VW"),
                _ev(
                    "start-cleaning",
                    datetime(2026, 6, 18, 9, 5),
                    ev_id=2,
                    scan_index=2,
                    rack="W25-30-VW",
                ),
                _ev(
                    "start-cleaning",
                    datetime(2026, 6, 18, 10, 0),
                    ev_id=3,
                    bag_id="BAG2",
                    rack="W26-30-VW",
                ),
            ]
        )
        summary = build_washing_chronology_summary(rows)
        assert summary["unique_bags_washed"] == 2
        assert summary["split_bags_washed"] == 1
        assert summary["single_bags_washed"] == 1
        assert summary["total_washer_loads"] == 3
