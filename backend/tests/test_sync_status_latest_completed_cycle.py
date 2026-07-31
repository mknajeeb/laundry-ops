"""Sync-status UI: latest_attempt vs latest_completed_cycle."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

from backend.rinse_presence_sync_status import (
    build_at_vendor_sync_status,
    build_rinse_sync_cycle_status,
)


def _row(
    *,
    rid,
    status,
    started,
    finished=None,
    error=None,
    batch_id=None,
    result=None,
):
    return {
        "id": rid,
        "status": status,
        "started_at": started,
        "finished_at": finished or started,
        "error_message": error,
        "imported_batch_id": batch_id,
        "portal_rows_count": 106 if batch_id else None,
        "scan_events_count": 200 if batch_id else None,
        "result_json": json.dumps(result) if isinstance(result, dict) else result,
        "duration_seconds": 100,
        "run_type": "scheduled",
    }


COMPLETED_RESULT = {
    "sync_cycle": {
        "sync_cycle_id": 3299,
        "cycle_status": "success",
        "at_vendor_status": "success",
        "at_vendor_ran": True,
        "at_vendor_run_id": 3801,
        "at_vendor_started_at": "2026-07-31T15:00:29",
        "at_vendor_completed_at": "2026-07-31T15:49:15",
    },
    "at_vendor_presence_sync": {"run_id": 3801, "status": "success"},
    "targeted_pending_scan_refresh": {
        "targeted_refresh_ran": True,
        "targeted_bags_considered": 40,
        "targeted_bags_refreshed": 40,
    },
    "step1_day_refresh": {
        "step1_refresh_status": "DEFERRED",
        "reason": "import_coverage_incomplete",
        "deferred": True,
        "persisted": False,
    },
}


def test_latest_attempt_skipped_prior_cycle_successful_primary_panel():
    cursor = MagicMock()
    skipped = _row(
        rid=3300,
        status="skipped",
        started=datetime(2026, 7, 31, 15, 30, 29),
        error="ALREADY_RUNNING",
    )
    completed = _row(
        rid=3299,
        status="success",
        started=datetime(2026, 7, 31, 15, 0, 29),
        finished=datetime(2026, 7, 31, 15, 49, 15),
        batch_id=3173,
        result=COMPLETED_RESULT,
    )
    cursor.fetchall.return_value = [skipped, completed]
    with patch(
        "backend.rinse_presence_sync_status.table_exists", return_value=True
    ), patch(
        "backend.rinse_presence_sync_status.build_at_vendor_sync_status",
        return_value={
            "freshness": {"portal_pulled_at_et": "Jul 31, 11:11 AM ET"},
            "last_refreshed_at_et": "Jul 31, 11:49 AM ET",
            "message": "At Vendor Sync: Jul 31, 11:49 AM ET",
            "status": "success",
        },
    ), patch(
        "backend.rinse_presence_sync_status._latest_success_presence_run",
        return_value=None,
    ), patch(
        "backend.rinse_presence_scrape.rfv_feature_active",
        return_value=False,
    ):
        cycle = build_rinse_sync_cycle_status(cursor, 3)

    assert cycle["latest_attempt"]["run_id"] == 3300
    assert cycle["latest_attempt"]["status"] == "skipped"
    assert cycle["latest_attempt"]["skip_reason"] == "ALREADY_RUNNING"
    assert cycle["latest_completed_cycle"]["run_id"] == 3299
    assert cycle["latest_completed_cycle"]["scan_import_batch_id"] == 3173
    assert cycle["latest_completed_cycle"]["portal_presence_run_id"] == 3801
    assert cycle["sync_cycle_id"] == 3299
    assert cycle["cycle_status"] == "success"
    assert cycle["at_vendor_status"] == "success"
    assert cycle["latest_attempt_informational"] is True
    assert "previous sync was still running" in cycle["latest_attempt_message"]
    assert cycle["targeted_pending_scan_refresh"]["targeted_refresh_ran"] is True


def test_no_successful_cycle_panel_blank():
    cursor = MagicMock()
    skipped = _row(
        rid=1,
        status="skipped",
        started=datetime(2026, 7, 31, 12, 0, 0),
        error="ALREADY_RUNNING",
    )
    cursor.fetchall.return_value = [skipped]
    with patch(
        "backend.rinse_presence_sync_status.table_exists", return_value=True
    ):
        cycle = build_rinse_sync_cycle_status(cursor, 3)

    assert cycle["latest_attempt"]["status"] == "skipped"
    assert cycle["latest_completed_cycle"] is None
    assert cycle["sync_cycle_id"] is None
    assert cycle["cycle_status"] is None


def test_at_vendor_status_uses_last_success_when_tip_skipped():
    cursor = MagicMock()
    tip = _row(
        rid=3300,
        status="skipped",
        started=datetime(2026, 7, 31, 15, 30, 29),
        error="ALREADY_RUNNING",
    )
    success = _row(
        rid=3299,
        status="success",
        started=datetime(2026, 7, 31, 15, 0, 29),
        finished=datetime(2026, 7, 31, 15, 49, 15),
        batch_id=3173,
    )

    def _fetchone():
        # first call latest, second last success
        if not hasattr(_fetchone, "n"):
            _fetchone.n = 0
        _fetchone.n += 1
        return tip if _fetchone.n == 1 else success

    cursor.fetchone.side_effect = _fetchone
    with patch(
        "backend.rinse_presence_sync_status.table_exists", return_value=True
    ), patch(
        "backend.rinse_scrape_status.build_scrape_run_batch_detail",
        return_value={
            "scrape_finished_at": "2026-07-31 15:49:15",
            "data_last_updated_at": "2026-07-31 15:49:15",
            "portal_rows_count": 106,
            "scan_events_count": 2147,
            "scrape_duration_seconds": 2926,
        },
    ), patch(
        "backend.rinse_scrape_status._fetch_upload_batch_row",
        return_value={"batch_id": 3173},
    ), patch(
        "backend.rinse_presence_sync_status._portal_pulled_at_from_batch",
        return_value=datetime(2026, 7, 31, 15, 11, 14),
    ), patch(
        "backend.rinse_presence_sync_status._latest_success_presence_run",
        return_value=None,
    ):
        av = build_at_vendor_sync_status(cursor, 3)

    assert av["status"] == "success"
    assert av["imported_batch_id"] == 3173
    assert av["tip_status"] == "skipped"
    assert av["latest_attempt"]["status"] == "skipped"
    assert "skipped" not in (av["message"] or "").lower()
    assert av["freshness"]["imported_batch_id"] == 3173
