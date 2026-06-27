"""Tests for post-processing weight chronology extraction."""

from datetime import datetime

from backend.rinse_post_processing_weight_chronology import (
    extract_post_processing_weight_rows_from_events,
)
from backend.rinse_wf_weight_events import WF_POST_PROCESSING_WEIGHT_SIGNAL

T0 = datetime(2026, 6, 26, 8, 0)
T1 = datetime(2026, 6, 26, 8, 30)
T2 = datetime(2026, 6, 26, 9, 0)
T3 = datetime(2026, 6, 26, 10, 0)
T4 = datetime(2026, 6, 26, 10, 30)


def _ev(purpose: str, ts: datetime, *, user: str = "Tarannum", ev_id: int = 1) -> dict:
    return {
        "id": ev_id,
        "bag_id": "ABC123",
        "purpose": purpose,
        "user_name": user,
        "scanned_at_parsed": ts,
    }


class TestPostProcessingWeightChronology:
    def test_extracts_post_processing_weight_on_day(self):
        events = [
            _ev("sent-to-vendor", T0, ev_id=1),
            _ev("cleaning", T1, ev_id=2),
            _ev("weight-entry", T2, ev_id=3),
            _ev("complete-cleaning", T3, ev_id=4),
            _ev("weight-entry", T4, ev_id=5),
        ]
        day_start = datetime(2026, 6, 26, 0, 0)
        day_end = datetime(2026, 6, 26, 23, 59, 59)
        rows = extract_post_processing_weight_rows_from_events(
            events, day_start=day_start, day_end=day_end
        )
        assert len(rows) == 1
        assert rows[0]["bag_id"] == "ABC123"
        assert rows[0]["employee"] == "Tarannum"
        assert rows[0]["timestamp_et"] == T4
        assert rows[0]["event_purpose"] == WF_POST_PROCESSING_WEIGHT_SIGNAL

    def test_ignores_completion_outside_day(self):
        events = [
            _ev("sent-to-vendor", T0, ev_id=1),
            _ev("cleaning", T1, ev_id=2),
            _ev("weight-entry", T2, ev_id=3),
            _ev("complete-cleaning", T3, ev_id=4),
            _ev("weight-entry", T4, ev_id=5),
        ]
        day_start = datetime(2026, 6, 25, 0, 0)
        day_end = datetime(2026, 6, 25, 23, 59, 59)
        rows = extract_post_processing_weight_rows_from_events(
            events, day_start=day_start, day_end=day_end
        )
        assert rows == []
