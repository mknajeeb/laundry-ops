"""Tests for dynamic ET ship-window Cleaner Tickets source URLs."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from backend.rinse_ship_window_tickets_urls import (
    SERVICE_TYPE_HD,
    SERVICE_TYPE_WF,
    build_scheduled_wf_hd_source_urls,
    build_ship_window_tickets_url,
    ship_to_vendor_window_et,
)


def test_ship_window_yesterday_today_et():
    start, end = ship_to_vendor_window_et(today_et=date(2026, 8, 30))
    assert start == date(2026, 8, 29)
    assert end == date(2026, 8, 30)


def test_ship_window_rolls_with_business_today():
    with patch("backend.rinse_ship_window_tickets_urls.business_today", return_value=date(2026, 9, 1)):
        start, end = ship_to_vendor_window_et()
    assert start == date(2026, 8, 31)
    assert end == date(2026, 9, 1)


def test_build_wf_url_status_any_and_service_type():
    url = build_ship_window_tickets_url(
        service_types=SERVICE_TYPE_WF,
        date_start=date(2026, 8, 29),
        date_end=date(2026, 8, 30),
    )
    q = parse_qs(urlparse(url).query, keep_blank_values=True)
    assert q["status"] == ["any"]
    assert q["service_types"] == ["wash_and_fold"]
    assert q["ship_to_vendor_date_start"] == ["2026-08-29"]
    assert q["ship_to_vendor_date_end"] == ["2026-08-30"]
    assert "at_vendor" not in url


def test_build_hd_url_hang_dry():
    url = build_ship_window_tickets_url(
        service_types=SERVICE_TYPE_HD,
        date_start=date(2026, 8, 29),
        date_end=date(2026, 8, 30),
    )
    q = parse_qs(urlparse(url).query, keep_blank_values=True)
    assert q["service_types"] == ["hang_dry"]
    assert q["status"] == ["any"]


def test_scheduled_sources_pair_order_and_dates():
    sources = build_scheduled_wf_hd_source_urls(today_et=date(2026, 8, 30))
    assert len(sources) == 2
    assert sources[0]["label"] == "wash_and_fold"
    assert sources[1]["label"] == "hang_dry"
    assert sources[0]["ship_to_vendor_date_start"] == "2026-08-29"
    assert sources[0]["ship_to_vendor_date_end"] == "2026-08-30"
    assert "service_types=wash_and_fold" in sources[0]["url"]
    assert "service_types=hang_dry" in sources[1]["url"]
    assert "status=any" in sources[0]["url"]
    assert "status=at_vendor" not in sources[0]["url"]
