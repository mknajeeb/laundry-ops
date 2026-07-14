from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.rinse_at_vendor_module import AV_STATUS_COMPLETED, AV_STATUS_PENDING
from backend.rinse_off_portal_scan_refresh import (
    build_targeted_refresh_sync_summary,
    classify_portal_rows_against_db,
    off_portal_refresh_enabled,
    scan_content_key,
)


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *_args, **_kwargs):
        return None

    def fetchall(self):
        return self._rows


def test_scan_content_key_strips_last_scan_suffix():
    a = scan_content_key(
        bag_id="ABC",
        purpose="weight-entry Last Scan",
        time_scanned_raw="Sunday, June 14, 2026 9:17 AM",
        rack="VeeWash Dirty",
        user_name="Varun (VeeWash)",
    )
    b = scan_content_key(
        bag_id="ABC",
        purpose="weight-entry",
        time_scanned_raw="Sunday, June 14, 2026 9:17 AM",
        rack="VeeWash Dirty",
        user_name="Varun (VeeWash)",
    )
    assert a == b


def test_classify_portal_rows_against_db_skips_existing_content():
    cursor = _FakeCursor(
        [
            {
                "dedupe_key": "old-key",
                "bag_id": "ABC",
                "purpose": "weight-entry Last Scan",
                "time_scanned_raw": "Sunday, June 14, 2026 9:17 AM",
                "rack": "VeeWash Dirty",
                "user_name": "Varun (VeeWash)",
            }
        ]
    )
    portal_scans = [
        {
            "scan_index": 1,
            "rack": "VeeWash Dirty",
            "time_scanned": "Sunday, June 14, 2026 9:17 AM",
            "user": "Varun (VeeWash)",
            "purpose": "weight-entry",
            "last_scan": "Y",
        },
        {
            "scan_index": 2,
            "rack": "(None)",
            "time_scanned": "Sunday, June 14, 2026 3:52 PM",
            "user": "Evelin (VeeWash)",
            "purpose": "weight-entry",
            "last_scan": "",
        },
    ]
    with patch("backend.rinse_off_portal_scan_refresh.table_exists", return_value=True):
        out = classify_portal_rows_against_db(cursor, 3, "ABC", portal_scans)
    assert out["missing_row_count"] == 1
    assert out["already_present_count"] == 1
    df = pd.DataFrame(out["missing_rows"])
    assert len(df) == 1
    assert "3:52 PM" in df.iloc[0]["Time Scanned"]


def test_off_portal_refresh_enabled_defaults_true():
    with patch.dict("os.environ", {}, clear=True):
        assert off_portal_refresh_enabled() is True
    with patch.dict("os.environ", {"RINSE_OFF_PORTAL_SCAN_REFRESH_ENABLED": "0"}, clear=False):
        assert off_portal_refresh_enabled() is False


def test_build_targeted_refresh_sync_summary_counts_completion_flips():
    detail = {
        "dry_run": False,
        "bag_ids_requested": ["A", "B"],
        "bags_processed": 2,
        "events_inserted": 5,
        "lookup_failed": 0,
        "bags": [
            {
                "bag_id": "A",
                "status_before": AV_STATUS_PENDING,
                "status_after": AV_STATUS_COMPLETED,
            },
            {
                "bag_id": "B",
                "status_before": AV_STATUS_PENDING,
                "status_after": AV_STATUS_PENDING,
            },
        ],
    }
    summary = build_targeted_refresh_sync_summary(detail)
    assert summary["targeted_refresh_ran"] is True
    assert summary["targeted_bags_considered"] == 2
    assert summary["missing_scans_imported"] == 5
    assert summary["bags_completed_after_refresh"] == 1


def test_build_targeted_refresh_sync_summary_skipped_reason():
    summary = build_targeted_refresh_sync_summary(
        None, skipped_reason="RINSE_OFF_PORTAL_SCAN_REFRESH_ENABLED=0"
    )
    assert summary["targeted_refresh_ran"] is False
    assert summary["skipped_reason"] == "RINSE_OFF_PORTAL_SCAN_REFRESH_ENABLED=0"


def test_targeted_refresh_import_chain_includes_fold_block_helper():
    from backend.rinse_employee_completed_bags import _collect_employee_non_folding_scans
    from backend.rinse_scan_purpose import is_fold_block_non_folding_purpose

    assert is_fold_block_non_folding_purpose("fold-block", rack="A1") is False
    assert _collect_employee_non_folding_scans(
        "Alice",
        day_scans=[],
        completion_keys=set(),
        anchor_by_bag={},
        clock_in=None,
        clock_out=None,
    ) == []


def test_pending_row_has_complete_cleaning():
    from backend.rinse_off_portal_scan_refresh import _pending_row_has_complete_cleaning

    assert _pending_row_has_complete_cleaning(
        [{"purpose": "complete-cleaning"}, {"purpose": "weight-entry"}]
    )
    assert _pending_row_has_complete_cleaning(
        [{"purpose": "complete-cleaning Last Scan"}]
    )
    assert not _pending_row_has_complete_cleaning(
        [{"purpose": "start-cleaning"}, {"purpose": "weight-entry"}]
    )


def test_resolve_pending_near_complete_bag_ids_selects_complete_cleaning_pending():
    from datetime import date

    from backend.rinse_off_portal_scan_refresh import resolve_pending_near_complete_bag_ids

    av = {
        "rows": [
            {
                "bag_id": "NEAR1",
                "at_vendor_status": AV_STATUS_PENDING,
                "service_type": "WF",
                "rush_bucket": "RUSH",
            },
            {
                "bag_id": "EARLY1",
                "at_vendor_status": AV_STATUS_PENDING,
                "service_type": "WF",
                "rush_bucket": "RUSH",
            },
            {
                "bag_id": "DONE1",
                "at_vendor_status": AV_STATUS_COMPLETED,
                "service_type": "WF",
                "rush_bucket": "RUSH",
            },
        ]
    }
    events = {
        "NEAR1": [{"purpose": "complete-cleaning"}, {"purpose": "weight-entry"}],
        "EARLY1": [{"purpose": "start-cleaning"}, {"purpose": "weight-entry"}],
        "DONE1": [{"purpose": "complete-cleaning"}, {"purpose": "weight-entry"}],
    }
    with patch(
        "backend.rinse_at_vendor_module._load_at_vendor_scan_events_for_bags",
        return_value=events,
    ):
        out = resolve_pending_near_complete_bag_ids(
            MagicMock(),
            3,
            selected_date_et=date(2026, 7, 14),
            av_module=av,
        )
    assert out == ["NEAR1"]
