"""Scheduled scrape env injects WF+HD ship-window sources (not at_vendor)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.rinse_scheduled_scrape import ScrapePaths, _subprocess_env_for_vendor


def test_subprocess_env_injects_wf_hd_ship_window_urls():
    paths = ScrapePaths(
        run_dir=Path("/tmp/rinse-test-run"),
        portal_csv=Path("/tmp/rinse-test-run/portal.csv"),
        scan_tickets_csv=Path("/tmp/rinse-test-run/tickets.csv"),
        scan_events_csv=Path("/tmp/rinse-test-run/events.csv"),
        log_path=Path("/tmp/rinse-test-run/log.txt"),
    )
    with (
        patch(
            "backend.rinse_scheduled_scrape.rinse_scrape_env_for_organization",
            return_value=(
                "veewash",
                {
                    "RINSE_VENDOR": "veewash",
                    # Legacy Azure at_vendor must be overridden:
                    "RINSE_TICKETS_URL": "https://www.rinse.com/cleanertickets/?status=at_vendor&page=1",
                },
            ),
        ),
        patch(
            "backend.rinse_ship_window_tickets_urls.business_today",
            return_value=date(2026, 8, 30),
        ),
        patch("backend.rinse_scheduled_scrape.tenant_data_dir", return_value=Path("/data/t")),
        patch("backend.rinse_scheduled_scrape.tenant_script_dir", return_value=Path("/tmp/missing")),
        patch("backend.rinse_bag_export_runner.scraper_dir", return_value=Path("/tmp")),
    ):
        env = _subprocess_env_for_vendor(3, "veewash", paths)

    assert env["RINSE_FULL_TRAVERSE"] == "1"
    assert env["RINSE_PORTAL_EARLY_STOP"] == "0"
    assert env["RINSE_BLOCK_HEAVY_ASSETS"] == "1"
    assert env["RINSE_EXPAND_SETTLE_MS"] == "400"
    assert env["RINSE_VENDORINLINE_SETTLE_MS"] == "50"
    assert env["RINSE_FAST_COLLAPSE"] == "1"
    assert env["RINSE_TABLE_WHEEL_STEPS"] == "0"
    sources = json.loads(env["RINSE_TICKETS_SOURCE_URLS"])
    assert len(sources) == 2
    assert sources[0]["label"] == "wash_and_fold"
    assert sources[1]["label"] == "hang_dry"
    assert "service_types=wash_and_fold" in sources[0]["url"]
    assert "service_types=hang_dry" in sources[1]["url"]
    assert "status=any" in sources[0]["url"]
    assert "ship_to_vendor_date_start=2026-08-29" in sources[0]["url"]
    assert "ship_to_vendor_date_end=2026-08-30" in sources[0]["url"]
    assert "status=at_vendor" not in sources[0]["url"]
    assert "status=at_vendor" not in env["RINSE_TICKETS_URL"]
