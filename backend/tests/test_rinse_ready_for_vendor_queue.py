"""Ready for Vendor snapshot queue — rush/service normalization."""

from __future__ import annotations

from datetime import date, datetime, time

from backend.rinse_processing_settings import (
    DEFAULT_RFV_RUSH_CUTOFF,
    parse_rfv_rush_cutoff_time_et,
    resolve_rfv_rush_cutoff_setting,
)
from backend.rinse_ready_for_vendor_queue import (
    RFV_NON_RUSH,
    RFV_RUSH,
    RFV_UNKNOWN,
    classify_rfv_rush_bucket,
    normalize_rfv_presence_row,
)

CUTOFF = time(7, 0)
BEFORE_CUTOFF_SCRAPE = datetime(2026, 6, 11, 6, 0)
AFTER_CUTOFF_SCRAPE = datetime(2026, 6, 11, 8, 0)


class TestRfvCutoffSetting:
    def test_default_parse(self):
        parsed = parse_rfv_rush_cutoff_time_et(DEFAULT_RFV_RUSH_CUTOFF)
        assert parsed == ("07:00", time(7, 0))

    def test_invalid_returns_none(self):
        assert parse_rfv_rush_cutoff_time_et("25:99") is None

    def test_resolve_defaults_when_missing(self, monkeypatch):
        monkeypatch.setattr("backend.rinse_processing_settings.table_exists", lambda c: True)
        monkeypatch.setattr("backend.rinse_processing_settings._get_setting", lambda c, o, k: None)
        out = resolve_rfv_rush_cutoff_setting(object(), 1)
        assert out["rfv_rush_cutoff_time_et"] == "07:00"
        assert out["rfv_rush_cutoff_source"] == "default"

    def test_resolve_uses_settings_value(self, monkeypatch):
        monkeypatch.setattr("backend.rinse_processing_settings.table_exists", lambda c: True)
        monkeypatch.setattr("backend.rinse_processing_settings._get_setting", lambda c, o, k: "17:00")
        out = resolve_rfv_rush_cutoff_setting(object(), 1)
        assert out["rfv_rush_cutoff_time_et"] == "17:00"
        assert out["rfv_rush_cutoff_source"] == "settings"

    def test_resolve_invalid_stored_falls_back(self, monkeypatch):
        monkeypatch.setattr("backend.rinse_processing_settings.table_exists", lambda c: True)
        monkeypatch.setattr("backend.rinse_processing_settings._get_setting", lambda c, o, k: "bad")
        out = resolve_rfv_rush_cutoff_setting(object(), 1)
        assert out["rfv_rush_cutoff_time_et"] == "07:00"
        assert out["rfv_rush_cutoff_source"] == "default"
        assert out["rfv_rush_cutoff_invalid_stored"] is True


class TestClassifyRfvRushBucket:
    def test_today_label_is_rush(self):
        bucket, reason = classify_rfv_rush_bucket(
            has_today=True,
            estimated_delivery_date_et=date(2026, 6, 13),
            scrape_time_et=BEFORE_CUTOFF_SCRAPE,
            cutoff_time=CUTOFF,
        )
        assert bucket == RFV_RUSH
        assert "TODAY" in reason

    def test_past_due_is_rush(self):
        bucket, reason = classify_rfv_rush_bucket(
            has_today=False,
            estimated_delivery_date_et=date(2026, 6, 10),
            scrape_time_et=BEFORE_CUTOFF_SCRAPE,
            cutoff_time=CUTOFF,
        )
        assert bucket == RFV_RUSH
        assert "past due" in reason

    def test_before_cutoff_same_day_is_rush(self):
        bucket, _ = classify_rfv_rush_bucket(
            has_today=False,
            estimated_delivery_date_et=date(2026, 6, 11),
            scrape_time_et=BEFORE_CUTOFF_SCRAPE,
            cutoff_time=CUTOFF,
        )
        assert bucket == RFV_RUSH

    def test_before_cutoff_tomorrow_is_non_rush(self):
        bucket, reason = classify_rfv_rush_bucket(
            has_today=False,
            estimated_delivery_date_et=date(2026, 6, 12),
            scrape_time_et=BEFORE_CUTOFF_SCRAPE,
            cutoff_time=CUTOFF,
        )
        assert bucket == RFV_NON_RUSH
        assert "after scrape date" in reason

    def test_after_cutoff_tomorrow_is_rush(self):
        bucket, reason = classify_rfv_rush_bucket(
            has_today=False,
            estimated_delivery_date_et=date(2026, 6, 12),
            scrape_time_et=AFTER_CUTOFF_SCRAPE,
            cutoff_time=CUTOFF,
        )
        assert bucket == RFV_RUSH
        assert "at/after cutoff" in reason

    def test_after_cutoff_day_after_tomorrow_is_non_rush(self):
        bucket, _ = classify_rfv_rush_bucket(
            has_today=False,
            estimated_delivery_date_et=date(2026, 6, 13),
            scrape_time_et=AFTER_CUTOFF_SCRAPE,
            cutoff_time=CUTOFF,
        )
        assert bucket == RFV_NON_RUSH

    def test_after_cutoff_today_still_rush(self):
        bucket, _ = classify_rfv_rush_bucket(
            has_today=False,
            estimated_delivery_date_et=date(2026, 6, 11),
            scrape_time_et=AFTER_CUTOFF_SCRAPE,
            cutoff_time=CUTOFF,
        )
        assert bucket == RFV_RUSH

    def test_missing_date_unknown_without_today(self):
        bucket, reason = classify_rfv_rush_bucket(
            has_today=False,
            estimated_delivery_date_et=None,
            scrape_time_et=BEFORE_CUTOFF_SCRAPE,
            cutoff_time=CUTOFF,
        )
        assert bucket == RFV_UNKNOWN
        assert "missing or invalid" in reason


class TestNormalizeRfvPresenceRow:
    def test_today_in_delivery_text(self):
        row = {
            "bag_id": "B1",
            "customer_name": "Alice",
            "estimated_delivery_date": "2026-06-12",
            "service_type": "WF",
            "raw_row_json": {"estimated_delivery_text": "Thu 06/11/2026 TODAY"},
        }
        out = normalize_rfv_presence_row(
            row, scrape_time_et=BEFORE_CUTOFF_SCRAPE, cutoff_time=CUTOFF
        )
        assert out["rush_bucket"] == RFV_RUSH
        assert out["has_today_label"] is True
        assert out["service_bucket"] == "WF"
        assert out["rfv_rush_cutoff_time_et"] == "07:00"
        assert "ready_for_vendor" in out["drilldown_tags"]

    def test_unknown_service_not_defaulted_to_wf(self):
        row = {
            "bag_id": "B2",
            "customer_name": "Bob",
            "estimated_delivery_date": "2026-06-11",
            "service_type": "",
            "raw_row_json": {},
        }
        out = normalize_rfv_presence_row(
            row, scrape_time_et=BEFORE_CUTOFF_SCRAPE, cutoff_time=CUTOFF
        )
        assert out["service_bucket"] == RFV_UNKNOWN
        assert out["rush_bucket"] == RFV_RUSH

    def test_today_not_read_from_customer_name(self):
        row = {
            "bag_id": "B3",
            "customer_name": "TODAY special",
            "estimated_delivery_date": "2026-06-12",
            "service_type": "WF",
            "raw_row_json": {"estimated_delivery_text": "Fri 06/12/2026"},
        }
        out = normalize_rfv_presence_row(
            row, scrape_time_et=BEFORE_CUTOFF_SCRAPE, cutoff_time=CUTOFF
        )
        assert out["has_today_label"] is False
        assert out["rush_bucket"] == RFV_NON_RUSH


class TestRfvCards:
    def test_unknown_review_card_included(self):
        from backend.rinse_ready_for_vendor_queue import _build_rfv_cards

        section = {
            "live": True,
            "total": 2,
            "rush_total": 1,
            "nonrush_total": 0,
            "wf_total": 1,
            "hd_total": 0,
            "rush_wf": 1,
            "rush_hd": 0,
            "nonrush_wf": 0,
            "nonrush_hd": 0,
            "unknown_needs_review": 1,
        }
        rows = [
            {"bag_id": "A", "drilldown_tags": ["ready_for_vendor", "rfv_rush_wf"]},
            {"bag_id": "B", "drilldown_tags": ["ready_for_vendor", "rfv_unknown_needs_review"]},
        ]
        labels = [c["label"] for c in _build_rfv_cards(section, rows)]
        assert "Unknown Review" in labels
