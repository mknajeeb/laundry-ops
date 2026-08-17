"""P0.4 — one incomplete bag must not freeze all Stage-B projection.

Modeled on production batch 3621 (scrape 4121, org 3, 2026-08-17 ET):
many safe bags + a few incoming_max_older_than_existing anomalies.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.rinse_bag_registry import merge_scan_events_from_upload
from backend.rinse_scan_chronology_gate import evaluate_timeline_replace_decision
from backend.rinse_step1_evidence_gate import (
    GATE_COMPLETE,
    GATE_INCOMPLETE,
    evaluate_durable_evidence_gate,
    merge_flags_indicate_incomplete,
    record_evidence_gate_from_merge,
)
from backend.rinse_step1_scrape_refresh import STATUS_SUCCESS, refresh_step1_after_scrape
from backend.tests.test_durable_incomplete_batch_stageb_gate import (
    DAY,
    _GateCursor,
    _day_meta,
    _refresh_patches,
)


def test_max_older_is_bag_deferred_not_thinner():
    older = evaluate_timeline_replace_decision(
        existing_max=datetime(2026, 8, 17, 14, 10),
        existing_n=40,
        incoming_max=datetime(2026, 8, 17, 12, 0),
        incoming_n=40,
    )
    assert older["preserve"] is True
    assert older.get("incomplete") is True
    assert older.get("projection_eligible") is False
    assert "incoming_max_older_than_existing" in older["reasons"]

    thinner = evaluate_timeline_replace_decision(
        existing_max=datetime(2026, 8, 17, 12, 0),
        existing_n=40,
        incoming_max=datetime(2026, 8, 17, 14, 10),
        incoming_n=9,
    )
    assert thinner["preserve"] is True
    assert thinner.get("incomplete") is not True
    assert thinner.get("projection_eligible") is True
    assert "incoming_materially_thinner" in thinner["reasons"]


def test_merge_flags_selective_is_not_global_incomplete():
    merge = {
        "import_incomplete": False,
        "stage_b_global_incomplete": False,
        "bags_projection_deferred": ["ANOMALY1"],
        "bags_projection_eligible": ["SAFE1", "SAFE2"],
    }
    assert merge_flags_indicate_incomplete(merge) is False

    all_bad = {
        "import_incomplete": True,
        "stage_b_global_incomplete": True,
        "bags_projection_deferred": ["ANOMALY1"],
        "bags_projection_eligible": [],
    }
    assert merge_flags_indicate_incomplete(all_bad) is True


def _merge_patches_multi(stack: ExitStack, bounds: dict):
    stack.enter_context(patch("backend.rinse_bag_registry.ensure_rinse_bag_tables"))
    stack.enter_context(
        patch("backend.rinse_bag_registry.ensure_rinse_bag_scan_events_dedupe_schema")
    )
    stack.enter_context(
        patch(
            "backend.rinse_bag_operational_owner.filter_bag_ids_for_operational_write",
            side_effect=lambda _c, _o, ids, **_k: (list(ids), []),
        )
    )
    stack.enter_context(
        patch(
            "backend.rinse_bag_registry.delete_persistent_scan_events_for_bags",
            return_value=0,
        )
    )
    stack.enter_context(
        patch(
            "backend.rinse_bag_registry.upsert_scan_event_row",
            return_value="inserted",
        )
    )
    stack.enter_context(
        patch(
            "backend.rinse_bag_registry._persistent_scan_bounds_for_bags",
            return_value=bounds,
        )
    )
    stack.enter_context(
        patch(
            "backend.rinse_bag_registry._persistent_completion_stage_counts",
            return_value={bid: 0 for bid in bounds},
        )
    )


def test_batch_3621_style_merge_projects_safe_defers_anomaly():
    """Many safe + one max_older → selective, not global incomplete."""
    rows = []
    # Safe replace bag (incoming richer / equal)
    rows.append(
        {
            "Bag ID": "3RIJ7IBJ16",
            "Scan Index": "1",
            "Rack": "CLEAN",
            "Time Scanned": "Monday, August 17, 2026 2:10 PM",
            "User": "A",
            "Purpose": "weight-entry",
            "Last Location": "",
            "Last Scan": "",
        }
    )
    # Safe thinner preserve
    for i in range(3):
        rows.append(
            {
                "Bag ID": "5KFCFB0TN8",
                "Scan Index": str(i + 1),
                "Rack": "CLEAN",
                "Time Scanned": f"Monday, August 17, 2026 {10 + i}:00 AM",
                "User": "A",
                "Purpose": "weight-entry",
                "Last Location": "",
                "Last Scan": "",
            }
        )
    # Anomalous: incoming max older than existing
    rows.append(
        {
            "Bag ID": "5PGOA1KTZ0",
            "Scan Index": "1",
            "Rack": "CLEAN",
            "Time Scanned": "Monday, August 17, 2026 9:00 AM",
            "User": "A",
            "Purpose": "weight-entry",
            "Last Location": "",
            "Last Scan": "",
        }
    )
    df = pd.DataFrame(rows)
    bounds = {
        "3RIJ7IBJ16": (datetime(2026, 8, 17, 10, 0), 1),
        "5KFCFB0TN8": (datetime(2026, 8, 17, 12, 0), 40),
        "5PGOA1KTZ0": (datetime(2026, 8, 17, 14, 10), 20),
    }
    cursor = MagicMock()

    def _parse(raw: str):
        if "2:10 PM" in raw:
            return datetime(2026, 8, 17, 14, 10)
        if "9:00 AM" in raw:
            return datetime(2026, 8, 17, 9, 0)
        if "10:00 AM" in raw:
            return datetime(2026, 8, 17, 10, 0)
        if "11:00 AM" in raw:
            return datetime(2026, 8, 17, 11, 0)
        if "12:00" in raw or "12:00 PM" in raw:
            return datetime(2026, 8, 17, 12, 0)
        return datetime(2026, 8, 17, 10, 0)

    with ExitStack() as stack:
        _merge_patches_multi(stack, bounds)
        stack.enter_context(
            patch("backend.rinse_bag_registry.parse_rinse_scanned_at", side_effect=_parse)
        )
        out = merge_scan_events_from_upload(
            cursor, 3, 3621, df, "batch_3621.csv", replace_existing=True
        )

    assert "3RIJ7IBJ16" in out["bags_projection_eligible"]
    assert "5KFCFB0TN8" in out["bags_projection_eligible"]
    assert out["bags_projection_deferred"] == ["5PGOA1KTZ0"]
    assert out["bags_projection_deferred_reasons"]["5PGOA1KTZ0"] == [
        "incoming_max_older_than_existing"
    ]
    assert out["import_incomplete"] is False
    assert out["stage_b_global_incomplete"] is False
    assert out["timeline_replacement_deferred"] is False
    assert merge_flags_indicate_incomplete(out) is False


def test_selective_merge_records_complete_gate_with_deferred_ids():
    cur = _GateCursor()
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        recorded = record_evidence_gate_from_merge(
            cur,
            organization_id=3,
            import_batch_id=3621,
            scrape_run_id=4121,
            merge={
                "import_incomplete": False,
                "stage_b_global_incomplete": False,
                "bags_projection_deferred": ["5PGOA1KTZ0", "CTQG55K5XD"],
                "bags_projection_eligible": ["3RIJ7IBJ16", "5KFCFB0TN8", "SAFE99"],
                "bags_projection_deferred_reasons": {
                    "5PGOA1KTZ0": ["incoming_max_older_than_existing"],
                    "CTQG55K5XD": ["incoming_max_older_than_existing"],
                },
            },
        )
        tip = evaluate_durable_evidence_gate(cur, 3, import_batch_id=3621)
    assert recorded["gate_status"] == GATE_COMPLETE
    assert recorded["allow_persist"] is True
    assert tip["allow_persist"] is True
    assert tip["blocking"] is False
    assert set(tip["projection_deferred_bag_ids"]) == {"5PGOA1KTZ0", "CTQG55K5XD"}


def test_selective_batch_stage_b_rebuilds_not_global_zero():
    """Safe bags project; deferred list retained; day_bags_rebuilt > 0."""
    conn = MagicMock()
    cursor = _GateCursor()
    day_meta = _day_meta()
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        record_evidence_gate_from_merge(
            cursor,
            organization_id=3,
            import_batch_id=3621,
            scrape_run_id=4121,
            merge={
                "import_incomplete": False,
                "stage_b_global_incomplete": False,
                "bags_projection_deferred": ["5PGOA1KTZ0"],
                "bags_projection_eligible": ["3RIJ7IBJ16", "5KFCFB0TN8"],
            },
        )
        patches = _refresh_patches(day_meta)
        with patches[0], patch(
            "backend.rinse_veewash_shift_day.backfill_day_from_live",
            return_value={
                "ok": True,
                "day": day_meta,
                "bag_count": 93,
                "summary_totals": {
                    "completed": 58,
                    "pending": 3,
                    "review_required": 1,
                },
                "projection_deferred_bag_ids": ["5PGOA1KTZ0"],
                "projection_deferred_count": 1,
            },
        ) as backfill, patches[2], patches[3], patches[4], patches[5], patches[6], patches[
            7
        ], patches[8], patch(
            "backend.rinse_step1_scrape_refresh.verify_step1_snapshot_freshness",
            return_value={"fresh": True, "reason": "ok"},
        ), patch(
            "backend.management_today.clear_management_today_cache"
        ) as clear_cache:
            out = refresh_step1_after_scrape(
                conn,
                cursor,
                organization_id=3,
                operations_date_et=DAY,
                import_batch_id=3621,
                scrape_run_id=4121,
            )
    assert out.get("deferred") is not True
    assert out["ok"] is True
    assert out["step1_refresh_status"] == STATUS_SUCCESS
    assert int(out.get("day_bags_rebuilt") or 0) == 93
    assert out["projection_deferred_bag_ids"] == ["5PGOA1KTZ0"]
    assert out["projection_selective"] is True
    backfill.assert_called_once()
    kwargs = backfill.call_args.kwargs
    assert kwargs.get("projection_deferred_bag_ids") == ["5PGOA1KTZ0"]
    clear_cache.assert_called()


def test_all_deferred_still_global_incomplete():
    cur = _GateCursor()
    with patch("backend.rinse_step1_evidence_gate.table_exists", return_value=True):
        recorded = record_evidence_gate_from_merge(
            cur,
            organization_id=3,
            import_batch_id=9999,
            merge={
                "import_incomplete": True,
                "stage_b_global_incomplete": True,
                "bags_projection_deferred": ["ONLY_BAD"],
                "bags_projection_eligible": [],
            },
        )
        tip = evaluate_durable_evidence_gate(cur, 3, import_batch_id=9999)
    assert recorded["gate_status"] == GATE_INCOMPLETE
    assert tip["blocking"] is True
    assert tip["allow_persist"] is False
