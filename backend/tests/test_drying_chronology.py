"""Tests for drying chronology (read-only shift analysis timeline)."""

from datetime import datetime

from backend.rinse_drying_chronology import (
    build_drying_chronology_summary,
    extract_drying_rows_from_events,
)


def _ev(purpose, at, *, rack="D4-50-VW", scan_index=1, ev_id=1, user="Alex"):
    return {
        "id": ev_id,
        "bag_id": "BAG1",
        "rack": rack,
        "user_name": user,
        "purpose": purpose,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


class TestDryingChronologyRows:
    def test_drying_at_dryer_is_one_row(self):
        events = [_ev("drying", datetime(2026, 6, 18, 14, 0))]
        rows = extract_drying_rows_from_events(events)
        assert len(rows) == 1
        assert rows[0]["dryer_rack"] == "D4-50-VW"
        assert rows[0]["confidence"] == "exact"

    def test_two_drying_scans_two_rows(self):
        events = [
            _ev("drying", datetime(2026, 6, 18, 14, 0), ev_id=1, scan_index=1),
            _ev(
                "drying",
                datetime(2026, 6, 18, 15, 0),
                ev_id=2,
                scan_index=2,
                rack="D8-35-VW",
            ),
        ]
        rows = extract_drying_rows_from_events(events)
        assert len(rows) == 2

    def test_drying_without_dryer_rack_excluded(self):
        events = [_ev("drying", datetime(2026, 6, 18, 14, 0), rack="CLEAN")]
        rows = extract_drying_rows_from_events(events)
        assert rows == []

    def test_summary_most_used(self):
        rows = extract_drying_rows_from_events(
            [
                _ev("drying", datetime(2026, 6, 18, 14, 0), ev_id=1),
                _ev("drying", datetime(2026, 6, 18, 15, 0), ev_id=2, scan_index=2),
            ]
        )
        summary = build_drying_chronology_summary(rows)
        assert summary["total_drying_scans"] == 2
        assert summary["most_used_dryer"] == "D4-50-VW"
