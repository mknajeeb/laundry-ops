"""Tests for display-only At Vendor pending explanations."""

from __future__ import annotations

from datetime import datetime

from backend.rinse_at_vendor_pending_explanation import (
    derive_pending_explanation,
    summarize_rush_pending_why,
)


def _ev(purpose: str, ts: str, **extra) -> dict:
    return {"purpose": purpose, "scanned_at_parsed": datetime.fromisoformat(ts), **extra}


class TestDerivePendingExplanation:
    def test_wf_missing_weight_entry(self):
        out = derive_pending_explanation(
            service_type="WF",
            events=[_ev("sent-to-vendor", "2026-06-14 04:50:00")],
            anchor_ts=datetime(2026, 6, 14, 4, 50),
            as_of_end=datetime(2026, 6, 14, 23, 59, 59),
        )
        assert out["pending_why_key"] == "missing_weight_entry"

    def test_wf_same_ts_weight_dupes(self):
        anchor = datetime(2026, 6, 14, 4, 50)
        events = [
            _ev("sent-to-vendor", "2026-06-14 04:50:00"),
            _ev("weight-entry Last Scan", "2026-06-14 09:16:00"),
            _ev("weight-entry", "2026-06-14 09:16:00"),
            _ev("cleaning", "2026-06-14 13:07:00"),
        ]
        out = derive_pending_explanation(
            service_type="WF",
            events=events,
            anchor_ts=anchor,
            as_of_end=datetime(2026, 6, 14, 23, 59, 59),
        )
        assert out["pending_why_key"] == "same_ts_weight_dupes"
        assert "same_ts_weight_dupes" in out["pending_why_summary_keys"]

    def test_wf_cleaning_started_not_completed(self):
        anchor = datetime(2026, 6, 14, 4, 49)
        events = [
            _ev("sent-to-vendor", "2026-06-14 04:49:00"),
            _ev("weight-entry Last Scan", "2026-06-14 09:17:00"),
            _ev("cleaning", "2026-06-14 09:17:00"),
            _ev("cleaning", "2026-06-14 10:25:00"),
        ]
        out = derive_pending_explanation(
            service_type="WF",
            events=events,
            anchor_ts=anchor,
            as_of_end=datetime(2026, 6, 14, 23, 59, 59),
        )
        assert out["pending_why_key"] == "cleaning_started_not_completed"
        assert "missing_complete_cleaning" in out["pending_why_summary_keys"]

    def test_wf_weight_once_no_completion(self):
        anchor = datetime(2026, 6, 14, 4, 49)
        events = [
            _ev("sent-to-vendor", "2026-06-14 04:49:00"),
            _ev("weight-entry Last Scan", "2026-06-14 09:37:00"),
        ]
        out = derive_pending_explanation(
            service_type="WF",
            events=events,
            anchor_ts=anchor,
            as_of_end=datetime(2026, 6, 14, 23, 59, 59),
        )
        assert out["pending_why_key"] == "weight_once_no_completion"

    def test_hd_missing_second_add_photos(self):
        anchor = datetime(2026, 6, 11, 4, 27)
        events = [
            _ev("sent-to-vendor", "2026-06-11 04:27:00"),
            _ev("add-photos", "2026-06-12 18:30:00"),
        ]
        out = derive_pending_explanation(
            service_type="HD",
            events=events,
            anchor_ts=anchor,
            as_of_end=datetime(2026, 6, 14, 23, 59, 59),
        )
        assert out["pending_why_key"] == "hd_missing_second_add_photos"

    def test_hd_issue_interruption(self):
        anchor = datetime(2026, 6, 11, 4, 23)
        events = [
            _ev("sent-to-vendor", "2026-06-11 04:23:00"),
            _ev("add-photos", "2026-06-12 17:01:00"),
            _ev("create-workitem-bulk Last Scan", "2026-06-12 17:04:00"),
        ]
        out = derive_pending_explanation(
            service_type="HD",
            events=events,
            anchor_ts=anchor,
            as_of_end=datetime(2026, 6, 14, 23, 59, 59),
        )
        assert out["pending_why_key"] == "hd_issue_interruption"


class TestSummarizeRushPendingWhy:
    def test_aggregates_rush_pending_rows(self):
        rows = [
            {
                "rush_bucket": "RUSH",
                "at_vendor_status": "Pending",
                "pending_why_summary_keys": ["same_ts_weight_dupes", "missing_complete_cleaning"],
            },
            {
                "rush_bucket": "RUSH",
                "at_vendor_status": "Pending",
                "pending_why_summary_keys": ["missing_second_weight", "missing_complete_cleaning"],
            },
            {
                "rush_bucket": "NON_RUSH",
                "at_vendor_status": "Pending",
                "pending_why_summary_keys": ["missing_second_weight"],
            },
        ]
        summary = summarize_rush_pending_why(rows)
        assert summary["total_rush_pending"] == 2
        assert summary["same_ts_weight_dupes"] == 1
        assert summary["missing_complete_cleaning"] == 2
        assert summary["missing_second_weight"] == 1
