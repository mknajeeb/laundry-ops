from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from backend.rinse_off_portal_scan_refresh import classify_portal_rows_against_db, scan_content_key


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
