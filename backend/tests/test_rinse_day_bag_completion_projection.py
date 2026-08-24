"""Tests for day-bag completion attribution normalization and scan backfill."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.rinse_day_bag_completion_projection import (
    apply_normalized_completion_fields,
    enrich_bags_completion_from_scans,
    normalize_completion_fields,
    reconcile_day_bag_completion_projection,
)


def test_normalize_completion_fields_reads_snapshot_aliases():
    ts, emp = normalize_completion_fields(
        {
            "bag_snapshot": {
                "canonical_completion_timestamp": "2026-08-24 09:40:00",
                "completed_by": "Veewash (Training Account 2)",
            }
        }
    )
    assert ts == "2026-08-24 09:40:00"
    assert emp == "Veewash (Training Account 2)"


def test_bag_rows_from_workload_maps_snapshot_completion_aliases():
    from backend.rinse_veewash_shift_day import _bag_rows_from_workload

    wl = {
        "rows": [
            {
                "bag_id": "BAG01",
                "service_type": "WF",
                "rush_flag": "NON-RUSH",
                "entry_class": "opening_new",
                "outcome": "completed",
                "canonical_completion_timestamp": datetime(2026, 8, 24, 9, 40),
                "completed_by": "Ada",
                "pre_weight_lbs": 10.0,
                "post_weight_lbs": 9.5,
            }
        ],
        "review_required": [],
    }
    summary = {"segments": {"all": {"bag_ids": {"review_required": []}}}}
    row = _bag_rows_from_workload(wl, summary)[0]
    assert row["canonical_completion_timestamp"] == datetime(2026, 8, 24, 9, 40)
    assert row["canonical_completion_employee"] == "Ada"


def test_enrich_bags_completion_from_scans_fills_missing_employee():
    bags = [
        {
            "bag_id": "BAG02",
            "service_type": "WF",
            "effective_status": "completed",
            "bag_snapshot": {"outcome": "completed"},
        }
    ]
    with patch(
        "backend.rinse_veewash_workload.load_canonical_completions_v2",
        return_value={
            "BAG02": {
                "completion_at": datetime(2026, 8, 24, 11, 0),
                "completed_by": "Angelica (Veewash)",
                "completion_source": "post_garments_reviewed_weight_entry",
            }
        },
    ):
        enrich_bags_completion_from_scans(MagicMock(), 3, date(2026, 8, 24), bags)
    assert bags[0]["canonical_completion_employee"] == "Angelica (Veewash)"
    assert bags[0]["canonical_completion_timestamp"] == datetime(2026, 8, 24, 11, 0)


def test_reconcile_is_idempotent_when_attribution_already_present():
    row = {
        "bag_id": "BAG03",
        "service_type": "WF",
        "effective_status": "completed",
        "canonical_completion_timestamp": datetime(2026, 8, 24, 8, 0),
        "canonical_completion_employee": "Tarannum (Veewash)",
        "pre_weight_lbs": 12.0,
        "bag_snapshot": {},
        "manager_edit_version": 0,
    }
    cursor = MagicMock()
    with (
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags",
            return_value=[row],
        ),
        patch(
            "backend.rinse_veewash_workload.load_canonical_completions_v2",
            return_value={},
        ),
    ):
        first = reconcile_day_bag_completion_projection(
            cursor, 3, date(2026, 8, 24)
        )
        second = reconcile_day_bag_completion_projection(
            cursor, 3, date(2026, 8, 24)
        )
    assert first["updated"] == 1
    assert second["updated"] == 1
    assert cursor.execute.call_count == 2


def test_completed_without_scan_evidence_stays_missing():
    bags = [
        {
            "bag_id": "BAG04",
            "service_type": "WF",
            "effective_status": "completed",
            "bag_snapshot": {},
        }
    ]
    with patch(
        "backend.rinse_veewash_workload.load_canonical_completions_v2",
        return_value={},
    ):
        enrich_bags_completion_from_scans(MagicMock(), 3, date(2026, 8, 24), bags)
    ts, emp = normalize_completion_fields(bags[0])
    assert ts is None
    assert emp is None


def test_apply_normalized_completion_fields_writes_snapshot():
    out = apply_normalized_completion_fields(
        {
            "bag_id": "BAG05",
            "completion_at": datetime(2026, 8, 24, 7, 0),
            "completed_by": "Gary Sanon",
            "bag_snapshot": {},
        }
    )
    assert out["canonical_completion_employee"] == "Gary Sanon"
    assert out["bag_snapshot"]["completed_by"] == "Gary Sanon"
    assert out["bag_snapshot"]["completion_at"] == "2026-08-24 07:00:00"
