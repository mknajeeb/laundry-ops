"""Scrape summary logging (Phase E)."""

from __future__ import annotations

from datetime import datetime

from backend.jobs.run_scheduled_rinse_scrape import _scrape_summary_for_result


class _R:
    organization_id = 3
    run_id = 99
    status = "success"
    portal_rows_count = 120
    scan_events_count = 40
    batch_id = 7
    error_message = None
    started_at = datetime(2026, 9, 17, 12, 0, 0)
    finished_at = datetime(2026, 9, 17, 12, 7, 30)
    detail = {
        "changed_count": 3,
        "new_count": 1,
        "removed_count": 0,
        "lifecycle": {"changed_count": 2},
        "query_budget": {"selects": 10},
    }


def test_scrape_summary_shape():
    s = _scrape_summary_for_result(_R(), schedule_detail={"mode": "ACTIVE", "tick_key": "2026-09-17 12:00"})
    assert s["event"] == "SCRAPE_SUMMARY"
    assert s["run_id"] == 99
    assert s["duration_seconds"] == 450.0
    assert s["portal_rows_count"] == 120
    assert s["changed_count"] == 3
    assert s["lifecycle_changes"] == 2
    assert s["mode"] == "ACTIVE"
    assert s["result"] == "success"
