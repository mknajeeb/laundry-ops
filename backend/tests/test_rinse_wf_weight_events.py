"""Tests for WF weight-event identity and completion."""

from __future__ import annotations

from datetime import datetime

from backend.rinse_wf_weight_events import (
    WF_POST_PROCESSING_WEIGHT_SIGNAL,
    derive_wf_clean_weight_fields,
    distinct_wf_weight_events,
    parse_weight_lbs_from_scan_event,
    wf_post_processing_weight_completion,
    wf_two_weight_completion,
)


def _ev(purpose: str, ts: datetime, **extra):
    row = {
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "scan_index": extra.get("scan_index", 1),
    }
    row.update(extra)
    return row


T0 = datetime(2026, 6, 14, 4, 0)
T1 = datetime(2026, 6, 14, 8, 0)
T2 = datetime(2026, 6, 14, 10, 0)
T3 = datetime(2026, 6, 14, 12, 0)
T4 = datetime(2026, 6, 14, 12, 5)


class TestParseWeightFromScanEvent:
    def test_weight_lbs_column(self):
        assert parse_weight_lbs_from_scan_event({"weight_lbs": 14.5}) == 14.5

    def test_raw_json_weight(self):
        ev = {"raw_json": {"Weight": "18.25"}}
        assert parse_weight_lbs_from_scan_event(ev) == 18.25

    def test_missing_weight_returns_none(self):
        assert parse_weight_lbs_from_scan_event({"purpose": "weight-entry"}) is None


class TestDistinctWfWeightEvents:
    def test_same_timestamp_duplicate_rows_collapse_without_weight(self):
        timeline = [
            _ev("sent-to-vendor", T0),
            _ev("weight-entry", T1, scan_index=1, id=1),
            _ev("weight-entry", T1, scan_index=2, id=2),
        ]
        out = distinct_wf_weight_events(timeline, anchor_ts=T0, as_of_end=T2)
        assert len(out) == 1

    def test_same_timestamp_different_weights_count_separately(self):
        timeline = [
            _ev("sent-to-vendor", T0),
            _ev("weight-entry", T1, scan_index=1, weight_lbs=20.0),
            _ev("weight-entry", T1, scan_index=2, weight_lbs=12.0),
        ]
        out = distinct_wf_weight_events(timeline, anchor_ts=T0, as_of_end=T2)
        assert len(out) == 2
        assert out[0].weight_lbs == 20.0
        assert out[1].weight_lbs == 12.0


class TestDeriveWfCleanWeightFields:
    def test_pre_clean_only_when_no_post_processing_weight(self):
        timeline = [
            _ev("sent-to-vendor", T0),
            _ev("weight-entry", T1, weight_lbs=20.0),
            _ev("add-photos", T2),
            _ev("complete-cleaning", T3),
        ]
        fields = derive_wf_clean_weight_fields(timeline, anchor_ts=T0, as_of_end=T3)
        assert fields["pre_clean_weight"] == 20.0
        assert fields["post_clean_weight"] is None
        assert fields["clean_weight_delta"] is None

    def test_pre_and_post_clean_weight(self):
        timeline = [
            _ev("sent-to-vendor", T0),
            _ev("weight-entry", T1, weight_lbs=20.0),
            _ev("add-photos", T2),
            _ev("weight-entry", T3, weight_lbs=12.0),
        ]
        fields = derive_wf_clean_weight_fields(timeline, anchor_ts=T0, as_of_end=T3)
        assert fields["pre_clean_weight"] == 20.0
        assert fields["post_clean_weight"] == 12.0
        assert fields["clean_weight_delta"] == 8.0


class TestWfPostProcessingWeightCompletion:
    def test_two_early_weights_then_processing_without_post_weight_incomplete(self):
        timeline = [
            _ev("sent-to-vendor", T0),
            _ev("weight-entry", T1, weight_lbs=20.0),
            _ev("weight-entry", T2, weight_lbs=19.0),
            _ev("add-photos", T3),
            _ev("complete-cleaning", T4),
        ]
        assert wf_post_processing_weight_completion(timeline, anchor_ts=T0, as_of_end=T4) is None

    def test_processing_then_final_weight_completes(self):
        timeline = [
            _ev("sent-to-vendor", T0),
            _ev("weight-entry", T1, weight_lbs=20.0),
            _ev("add-photos", T2),
            _ev("weight-entry", T3, weight_lbs=12.0),
        ]
        hit = wf_post_processing_weight_completion(timeline, anchor_ts=T0, as_of_end=T3)
        assert hit is not None
        assert hit.signal == WF_POST_PROCESSING_WEIGHT_SIGNAL
        assert hit.completion_ts == T3
        assert hit.second_weight_lbs == 12.0

    def test_complete_cleaning_then_weight_completes(self):
        timeline = [
            _ev("sent-to-vendor", T0),
            _ev("start-cleaning", T1),
            _ev("drying", T2),
            _ev("complete-cleaning", T3),
            _ev("weight-entry", T4, weight_lbs=15.0),
        ]
        hit = wf_post_processing_weight_completion(timeline, anchor_ts=T0, as_of_end=T4)
        assert hit is not None
        assert hit.completion_ts == T4

    def test_same_minute_post_weight_with_earlier_pre_clean_completes(self):
        """Regression: BARS9TT3I6 — final weight same minute as add-photos/processed-by-vendor."""
        tie = datetime(2026, 6, 18, 13, 59)
        pre = datetime(2026, 6, 18, 10, 51)
        timeline = [
            _ev("sent-to-vendor", T0),
            _ev("weight-entry", pre, weight_lbs=20.0),
            _ev("add-photos", datetime(2026, 6, 18, 11, 23)),
            _ev("complete-cleaning", datetime(2026, 6, 18, 13, 45)),
            _ev("add-photos", tie),
            _ev("weight-entry", tie, weight_lbs=12.0),
            _ev("processed-by-vendor", tie),
        ]
        hit = wf_post_processing_weight_completion(timeline, anchor_ts=T0, as_of_end=tie)
        assert hit is not None
        assert hit.completion_ts == tie
        assert hit.second_weight_lbs == 12.0

    def test_same_minute_only_weight_without_earlier_pre_clean_incomplete(self):
        timeline = [
            _ev("sent-to-vendor", T0),
            _ev("weight-entry", T1),
            _ev("add-photos", T1),
        ]
        assert wf_post_processing_weight_completion(timeline, anchor_ts=T0, as_of_end=T1) is None


class TestWfTwoWeightCompletion:
    def test_two_timestamps_complete(self):
        timeline = [
            _ev("sent-to-vendor", T0),
            _ev("weight-entry", T1, weight_lbs=20.0),
            _ev("weight-entry", T2, weight_lbs=12.0),
        ]
        hit = wf_two_weight_completion(timeline, anchor_ts=T0, as_of_end=T2)
        assert hit is not None
        assert hit.first_weight_lbs == 20.0
        assert hit.second_weight_lbs == 12.0
        assert hit.weight_delta == 8.0
