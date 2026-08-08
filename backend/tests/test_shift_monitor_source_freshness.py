"""Shift Monitor operator source-data freshness watermarks (not Stage-B calc time)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from backend.rinse_scan_freshness import (
    build_operator_source_freshness_watermarks,
    build_scan_data_freshness,
)
from backend.rinse_scan_time import json_safe_rinse

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def test_operator_watermark_scan_older_than_portal():
    """Portal 1:42 PM + scans 1:09 PM → Data current through = 1:09 PM ET."""
    out = build_operator_source_freshness_watermarks(
        most_recent_persisted_scan_at=datetime(2026, 8, 8, 13, 9, 0),  # ET wall
        last_portal_scrape_at=datetime(2026, 8, 8, 17, 42, 11),  # UTC → 13:42 ET
        shift_last_sync_at=datetime(2026, 8, 8, 17, 48, 29),  # UTC → 13:48 ET
    )
    assert out["source_freshness_available"] is True
    assert out["scan_data_through_et"] == "2026-08-08T13:09:00-04:00"
    assert out["portal_data_through_et"] == "2026-08-08T13:42:11-04:00"
    assert out["operator_data_current_through_et"] == "2026-08-08T13:09:00-04:00"
    assert out["calculated_at_et"] == "2026-08-08T13:48:29-04:00"


def test_operator_watermark_portal_older_than_scan():
    """Portal 1:42 PM + scans 1:46 PM → Data current through = 1:42 PM ET."""
    out = build_operator_source_freshness_watermarks(
        most_recent_persisted_scan_at=datetime(2026, 8, 8, 13, 46, 0),  # ET wall
        last_portal_scrape_at=datetime(2026, 8, 8, 17, 42, 11),  # UTC → 13:42 ET
    )
    assert out["source_freshness_available"] is True
    assert out["operator_data_current_through_et"] == "2026-08-08T13:42:11-04:00"


def test_manual_recalc_does_not_move_source_watermark():
    """Recalc at 1:48 PM with unchanged portal/scan → watermark still 1:09 PM."""
    before = build_operator_source_freshness_watermarks(
        most_recent_persisted_scan_at=datetime(2026, 8, 8, 13, 9, 0),
        last_portal_scrape_at=datetime(2026, 8, 8, 17, 42, 11),
        shift_last_sync_at=datetime(2026, 8, 8, 17, 42, 27),
    )
    after = build_operator_source_freshness_watermarks(
        most_recent_persisted_scan_at=datetime(2026, 8, 8, 13, 9, 0),
        last_portal_scrape_at=datetime(2026, 8, 8, 17, 42, 11),
        shift_last_sync_at=datetime(2026, 8, 8, 17, 48, 29),
    )
    assert before["operator_data_current_through_et"] == after["operator_data_current_through_et"]
    assert after["operator_data_current_through_et"] == "2026-08-08T13:09:00-04:00"
    assert after["calculated_at_et"] == "2026-08-08T13:48:29-04:00"
    assert before["calculated_at_et"] != after["calculated_at_et"]


def test_stage_b_utc_string_serializes_to_et():
    """UTC 17:48 Stage-B string → 13:48 America/New_York."""
    payload = {
        "step1_refreshed_at": "2026-08-08 17:48:29.550773",
        "finished_at": "2026-08-08 17:48:29",
        "last_sync_at": datetime(2026, 8, 8, 17, 48, 29),
    }
    out = json_safe_rinse(payload)
    assert out["step1_refreshed_at"] == "2026-08-08T13:48:29-04:00"
    assert out["finished_at"] == "2026-08-08T13:48:29-04:00"
    assert out["last_sync_at"] == "2026-08-08T13:48:29-04:00"


def test_no_future_operator_watermark_vs_source_times():
    """Operator watermark must not exceed either source stream (and not use calc time)."""
    out = build_operator_source_freshness_watermarks(
        most_recent_persisted_scan_at=datetime(2026, 8, 8, 13, 9, 0),
        last_portal_scrape_at=datetime(2026, 8, 8, 17, 42, 11),
        shift_last_sync_at=datetime(2026, 8, 8, 17, 48, 29),
    )
    current = datetime.fromisoformat(out["operator_data_current_through_et"])
    portal = datetime.fromisoformat(out["portal_data_through_et"])
    scan = datetime.fromisoformat(out["scan_data_through_et"])
    calculated = datetime.fromisoformat(out["calculated_at_et"])
    assert current <= portal
    assert current <= scan
    assert current < calculated
    # Must not surface UTC wall 17:48 as the operator watermark.
    assert "17:48" not in out["operator_data_current_through_et"]


def test_missing_watermark_unavailable():
    missing_scan = build_operator_source_freshness_watermarks(
        most_recent_persisted_scan_at=None,
        last_portal_scrape_at=datetime(2026, 8, 8, 17, 42, 11),
    )
    assert missing_scan["source_freshness_available"] is False
    assert missing_scan["operator_data_current_through_et"] is None
    assert missing_scan["portal_data_through_et"] == "2026-08-08T13:42:11-04:00"

    missing_portal = build_operator_source_freshness_watermarks(
        most_recent_persisted_scan_at=datetime(2026, 8, 8, 13, 9, 0),
        last_portal_scrape_at=None,
    )
    assert missing_portal["source_freshness_available"] is False
    assert missing_portal["operator_data_current_through_et"] is None


def test_build_scan_data_freshness_includes_operator_watermarks():
    payload = build_scan_data_freshness(
        selected_date_et=date(2026, 8, 8),
        shift_last_sync_at=datetime(2026, 8, 8, 17, 48, 29),
        most_recent_persisted_scan_at=datetime(2026, 8, 8, 13, 9, 0),
        last_portal_scrape_at=datetime(2026, 8, 8, 17, 42, 11),
    )
    assert payload["selected_date_et"] == "2026-08-08"
    assert payload["operator_data_current_through_et"] == "2026-08-08T13:09:00-04:00"
    assert payload["source_freshness_available"] is True
    # Today/Yesterday date semantics: selected_date_et unchanged passthrough.
    safe = json_safe_rinse(payload)
    assert safe["selected_date_et"] == "2026-08-08"
    assert safe["operator_data_current_through_et"] == "2026-08-08T13:09:00-04:00"
    assert safe["last_portal_scrape_at"] == "2026-08-08T13:42:11-04:00"
    assert safe["most_recent_persisted_scan_at"] == "2026-08-08T13:09:00-04:00"
