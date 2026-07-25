"""Post-scrape Step-1 day snapshot refresh keeps Completed/Pending queues current."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_scheduled_scrape import (
    _combined_cycle_needs_step1_refresh,
    _refresh_open_step1_day_after_scrape,
)
from backend.rinse_veewash_shift_day import STATUS_CLOSED, STATUS_OPEN


def test_post_scrape_refreshes_open_step1_day():
    conn = MagicMock()
    cursor = MagicMock()
    log = MagicMock()
    day = date(2026, 7, 25)
    with patch("backend.rinse_scheduled_scrape._today_et", return_value=day), patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        return_value={"status": STATUS_OPEN},
    ), patch(
        "backend.rinse_veewash_shift_day.backfill_day_from_live",
        return_value={"ok": True, "day": {"status": STATUS_OPEN}},
    ) as backfill:
        out = _refresh_open_step1_day_after_scrape(
            conn, cursor, org_id=3, log=log
        )
    assert out["ok"] is True
    assert out["shift_date_et"] == "2026-07-25"
    backfill.assert_called_once_with(cursor, 3, day, force=True)
    conn.commit.assert_called()


def test_post_scrape_skips_closed_step1_day():
    conn = MagicMock()
    cursor = MagicMock()
    log = MagicMock()
    day = date(2026, 7, 24)
    with patch("backend.rinse_scheduled_scrape._today_et", return_value=day), patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        return_value={"status": STATUS_CLOSED},
    ), patch(
        "backend.rinse_veewash_shift_day.backfill_day_from_live"
    ) as backfill:
        out = _refresh_open_step1_day_after_scrape(
            conn, cursor, org_id=3, log=log
        )
    assert out["skipped"] is True
    assert out["reason"] == "day_closed"
    backfill.assert_not_called()


def test_post_scrape_refresh_failure_is_non_fatal():
    conn = MagicMock()
    cursor = MagicMock()
    log = MagicMock()
    with patch("backend.rinse_scheduled_scrape._today_et", return_value=date(2026, 7, 25)), patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        side_effect=RuntimeError("db down"),
    ):
        out = _refresh_open_step1_day_after_scrape(
            conn, cursor, org_id=3, log=log
        )
    assert out["ok"] is False
    assert "db down" in out["error"]


def test_combined_cycle_needs_step1_refresh_when_import_omits_it():
    assert (
        _combined_cycle_needs_step1_refresh(
            dry_run=False,
            status="success",
            detail={"confirm": {}, "targeted_pending_scan_refresh": {}},
        )
        is True
    )
    assert (
        _combined_cycle_needs_step1_refresh(
            dry_run=False,
            status="success",
            detail={"step1_day_refresh": {"ok": True}},
        )
        is False
    )
    assert (
        _combined_cycle_needs_step1_refresh(
            dry_run=True, status="success", detail={}
        )
        is False
    )
