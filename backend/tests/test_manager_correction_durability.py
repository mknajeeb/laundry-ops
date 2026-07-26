"""Manager PRE / completion corrections must survive day rebuild loaders."""

from __future__ import annotations

import json
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_veewash_review import load_bag_weight_map
from backend.rinse_veewash_workload import load_canonical_completions_v2


def _cursor_for_weight(*, scans, corrections):
    cursor = MagicMock()

    def execute(sql, params=None):
        s = " ".join(str(sql).split()).lower()
        if "from rinse_bag_scan_events" in s:
            cursor._result = list(scans)
        elif "from rinse_step1_corrections" in s:
            cursor._result = list(corrections)
        else:
            cursor._result = []

    cursor.execute.side_effect = execute
    cursor.fetchall.side_effect = lambda: list(getattr(cursor, "_result", []) or [])
    return cursor


def test_load_bag_weight_map_applies_corrected_pre_without_post():
    cursor = _cursor_for_weight(
        scans=[
            {
                "bag_id": "BAG1",
                "weight_lbs": None,
                "purpose": "weight-entry",
                "scanned_at_parsed": datetime(2026, 7, 26, 10, 0, 0),
                "user_name": "Varun",
                "id": 1,
            }
        ],
        corrections=[
            {
                "bag_id": "BAG1",
                "new_values": json.dumps(
                    {
                        "pre_weight_lbs": 17.0,
                        "post_weight_lbs": None,
                        "corrected_pre_weight_lbs": 17.0,
                    }
                ),
                "created_at": datetime(2026, 7, 26, 12, 0, 0),
                "id": 9,
            }
        ],
    )
    with patch("backend.ta_helpers.table_exists", return_value=True), patch(
        "backend.ta_helpers.table_has_column", return_value=False
    ):
        out = load_bag_weight_map(cursor, 3, ["BAG1"])

    assert out["BAG1"]["pre_weight_lbs"] == 17.0
    assert out["BAG1"]["corrected_pre_weight_lbs"] == 17.0
    assert out["BAG1"].get("corrected_post_weight_lbs") is None


def test_load_bag_weight_map_legacy_post_only_still_overrides_post():
    cursor = _cursor_for_weight(
        scans=[
            {
                "bag_id": "BAG1",
                "weight_lbs": 10.0,
                "purpose": "weight-entry",
                "scanned_at_parsed": datetime(2026, 7, 26, 10, 0, 0),
                "user_name": "A",
                "id": 1,
            },
            {
                "bag_id": "BAG1",
                "weight_lbs": 11.0,
                "purpose": "weight-entry",
                "scanned_at_parsed": datetime(2026, 7, 26, 11, 0, 0),
                "user_name": "A",
                "id": 2,
            },
        ],
        corrections=[
            {
                "bag_id": "BAG1",
                "new_values": json.dumps({"post_weight_lbs": 22.5}),
                "created_at": datetime(2026, 7, 26, 12, 0, 0),
                "id": 9,
            }
        ],
    )
    with patch("backend.ta_helpers.table_exists", return_value=True), patch(
        "backend.ta_helpers.table_has_column", return_value=False
    ):
        out = load_bag_weight_map(cursor, 3, ["BAG1"])

    assert out["BAG1"]["pre_weight_lbs"] == 10.0
    assert out["BAG1"]["post_weight_lbs"] == 22.5
    assert out["BAG1"]["corrected_post_weight_lbs"] == 22.5


def test_load_canonical_completions_prefers_manager_correct_completion():
    cursor = MagicMock()

    def execute(sql, params=None):
        s = " ".join(str(sql).split()).lower()
        if "from rinse_bag_scan_events" in s:
            cursor._result = [
                {
                    "bag_id": "BAG1",
                    "rack": "VeeWash Dirty",
                    "purpose": "entry",
                    "scanned_at_parsed": datetime(2026, 7, 26, 8, 0, 0),
                    "user_name": "Varun (VeeWash)",
                    "weight_lbs": None,
                },
                {
                    "bag_id": "BAG1",
                    "rack": "VeeWash Clean",
                    "purpose": "processing",
                    "scanned_at_parsed": datetime(2026, 7, 26, 12, 0, 0),
                    "user_name": "Varun (VeeWash)",
                    "weight_lbs": None,
                },
            ]
        elif "from rinse_step1_corrections" in s:
            cursor._result = [
                {
                    "bag_id": "BAG1",
                    "new_values": json.dumps(
                        {
                            "completed_by": "Ms Chen",
                            "completion_at": "2026-07-26T12:00:00",
                        }
                    ),
                    "created_at": datetime(2026, 7, 26, 13, 0, 0),
                    "id": 3,
                }
            ]
        else:
            cursor._result = []

    cursor.execute.side_effect = execute
    cursor.fetchall.side_effect = lambda: list(getattr(cursor, "_result", []) or [])

    with patch("backend.rinse_veewash_workload.table_exists", return_value=True):
        out = load_canonical_completions_v2(cursor, 3, ["BAG1"])

    assert out["BAG1"]["completed_by"] == "Ms Chen"
    assert out["BAG1"]["completion_source"] == "manager_correct_completion"
    assert out["BAG1"]["completion_date"] == date(2026, 7, 26)


def test_load_canonical_completions_applies_manager_override_without_scan_completion():
    """Manager employee correction must stick even when scan completion is absent."""
    cursor = MagicMock()

    def execute(sql, params=None):
        s = " ".join(str(sql).split()).lower()
        if "from rinse_bag_scan_events" in s:
            cursor._result = []
        elif "from rinse_step1_corrections" in s:
            cursor._result = [
                {
                    "bag_id": "BAG1",
                    "new_values": json.dumps(
                        {
                            "completed_by": "Mrs Chen (VeeWash)",
                            "completion_at": "2026-07-26T12:00:00",
                        }
                    ),
                    "created_at": datetime(2026, 7, 26, 13, 0, 0),
                    "id": 3,
                }
            ]
        else:
            cursor._result = []

    cursor.execute.side_effect = execute
    cursor.fetchall.side_effect = lambda: list(getattr(cursor, "_result", []) or [])

    with patch("backend.rinse_veewash_workload.table_exists", return_value=True):
        out = load_canonical_completions_v2(cursor, 3, ["BAG1"])

    assert out["BAG1"]["completed_by"] == "Mrs Chen (VeeWash)"
    assert out["BAG1"]["completion_source"] == "manager_correct_completion"
