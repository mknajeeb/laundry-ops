"""Prove redundant post-scrape work is skipped without changing business outcomes."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_upload_finalize import finalize_rinse_after_batch_confirm
from backend.rinse_wf_service_cycle import finalize_wf_canonical_lifecycle_terminal


def test_publish_refresh_called_once_not_twice():
    cur = MagicMock()
    with patch(
        "backend.rinse_wf_service_cycle.is_wf_canonical_lifecycle_enabled",
        return_value=True,
    ), patch(
        "backend.rinse_wf_service_cycle._parse_portal_bags_from_csv",
        return_value={"BAG1": {"service_type": "WF"}, "BAG2": {}},
    ), patch(
        "backend.rinse_wf_service_cycle.refresh_canonical_cycles_from_evidence",
        return_value={"refreshed": 2, "scoped": True, "bag_count": 2},
    ) as refresh, patch(
        "backend.rinse_wf_service_cycle.sync_portal_discovery",
        return_value={"admitted": 1, "updated": 1},
    ) as discovery, patch(
        "backend.rinse_wf_service_cycle.handle_disappeared_active_cycles",
        return_value={"completed": 0, "review": 0},
    ) as disappear, patch(
        "backend.rinse_wf_service_cycle._portal_traversal_complete",
        return_value=True,
    ), patch(
        "backend.rinse_wf_service_cycle_compat.terminal_project_canonical_wf_day_snapshot",
        return_value={"ok": True},
    ):
        out = finalize_wf_canonical_lifecycle_terminal(
            cur,
            3,
            portal_csv_path="/tmp/portal.csv",
            shift_date_et=date(2026, 8, 30),
        )
    assert refresh.call_count == 1
    assert out["canonical_refresh_calls"] == 1
    discovery.assert_called_once()
    disappear.assert_called_once()
    # Refresh runs before portal mutations (same prior order, minus duplicate).
    assert refresh.call_args_list[0].kwargs.get("bag_ids") == {"BAG1", "BAG2"}


def test_finalize_skips_merge_when_draft_already_merged():
    cursor = MagicMock()
    prior = {
        "bags_merged": 104,
        "events_inserted": 2824,
        "bag_ids": ["AAAA1111", "BBBB2222"],
        "events_already_present": 10,
    }
    with patch(
        "backend.rinse_upload_finalize.load_upload_batch_scan_events_as_dataframe"
    ) as load_df, patch(
        "backend.rinse_upload_finalize.merge_scan_events_from_upload"
    ) as merge, patch(
        "backend.rinse_portal_absence_completion.process_bags_missing_from_latest_portal",
        return_value={
            "rejected_bag_ids": [],
            "completed_bag_ids": [],
            "needs_verification_count": 0,
            "needs_verification_bag_ids": [],
            "rejected_count": 0,
            "completed_count": 0,
            "full_snapshot": True,
        },
    ), patch(
        "backend.rinse_upload_finalize.apply_registry_from_accepted_portal_rows",
        return_value=2,
    ), patch(
        "backend.rinse_upload_finalize.recompute_completion_for_bags",
        return_value={"bags_recomputed": 2, "bags_completed": 0, "bags": []},
    ), patch(
        "backend.rinse_folding_registry.recompute_folding_after_upload",
        return_value={"ok": True, "bags": []},
    ), patch(
        "backend.rinse_folding_registry.folding_recompute_summary_for_response",
        return_value={},
    ), patch(
        "backend.rinse_upload_finalize.count_clean_rack_completed_bags",
        return_value=0,
    ):
        out = finalize_rinse_after_batch_confirm(
            cursor,
            3,
            5171,
            accepted_portal_rows=[{"ticket_id": "AAAA1111"}, {"ticket_id": "BBBB2222"}],
            prior_persistent_merge=prior,
        )
    load_df.assert_not_called()
    merge.assert_not_called()
    pm = out["persistent_merge"]
    assert pm.get("skipped_redundant_draft_merge") is True
    assert pm.get("draft_events_inserted") == 2824
    assert pm.get("events_inserted") == 0
    assert out["timings_sec"]["merge_skipped_redundant"] == 1.0
    assert "AAAA1111" in out["bag_ids"]


def test_finalize_still_merges_without_prior_draft_merge():
    """Manual UI confirm (no auto-scrape draft merge) must still merge."""
    import pandas as pd

    cursor = MagicMock()
    df = pd.DataFrame(
        [
            {
                "Bag ID": "CCCC3333",
                "Scan Index": "1",
                "Rack": "FOLDING",
                "Time Scanned": "Sunday, Aug 30, 2026 3:04 PM",
                "User": "Folder",
                "Purpose": "",
                "Last Location": "",
                "Last Scan": "",
            }
        ]
    )
    with patch(
        "backend.rinse_upload_finalize.load_upload_batch_scan_events_as_dataframe",
        return_value=df,
    ), patch(
        "backend.rinse_upload_finalize.merge_scan_events_from_upload",
        return_value={"bags_merged": 1, "events_inserted": 1, "bag_ids": ["CCCC3333"]},
    ) as merge, patch(
        "backend.rinse_portal_absence_completion.process_bags_missing_from_latest_portal",
        return_value={
            "rejected_bag_ids": [],
            "completed_bag_ids": [],
            "needs_verification_count": 0,
            "needs_verification_bag_ids": [],
            "rejected_count": 0,
            "completed_count": 0,
            "full_snapshot": True,
        },
    ), patch(
        "backend.rinse_upload_finalize.apply_registry_from_accepted_portal_rows",
        return_value=1,
    ), patch(
        "backend.rinse_upload_finalize.recompute_completion_for_bags",
        return_value={"bags_recomputed": 1, "bags_completed": 0, "bags": []},
    ), patch(
        "backend.rinse_folding_registry.recompute_folding_after_upload",
        return_value={"ok": True, "bags": []},
    ), patch(
        "backend.rinse_folding_registry.folding_recompute_summary_for_response",
        return_value={},
    ), patch(
        "backend.rinse_upload_finalize.count_clean_rack_completed_bags",
        return_value=0,
    ):
        out = finalize_rinse_after_batch_confirm(
            cursor,
            3,
            99,
            accepted_portal_rows=[{"ticket_id": "CCCC3333"}],
        )
    merge.assert_called_once()
    assert out["persistent_merge"].get("skipped_redundant_draft_merge") is not True
    assert out["timings_sec"]["merge_skipped_redundant"] == 0.0


def test_absence_fetch_returns_only_missing_draft_rows():
    from backend.rinse_portal_departure_completion import (
        fetch_draft_scan_rows_missing_from_persistent,
    )
    from backend.rinse_scan_event_identity import compute_scan_event_dedupe_key

    org = 3
    bid = "BAGABSENCE1"
    scanned = datetime(2026, 8, 30, 12, 0, 0)
    dk = compute_scan_event_dedupe_key(
        organization_id=org,
        bag_id=bid,
        rack="FOLDING",
        user_name="U",
        purpose="",
        time_scanned_raw="Sunday, Aug 30, 2026 12:00 PM",
        scanned_at_parsed=scanned,
    )
    existing = {
        bid: [
            {
                "dedupe_key": dk,
                "rack": "FOLDING",
                "user_name": "U",
                "purpose": "",
                "time_scanned_raw": "Sunday, Aug 30, 2026 12:00 PM",
                "scanned_at_parsed": scanned,
            }
        ]
    }
    light_rows = {
        bid: [
            {
                "id": 1,
                "upload_batch_id": 10,
                "bag_id": bid,
                "scan_index": 1,
                "rack": "FOLDING",
                "time_scanned_raw": "Sunday, Aug 30, 2026 12:00 PM",
                "scanned_at_parsed": scanned,
                "user_name": "U",
                "purpose": "",
                "last_location": "",
                "last_scan": "",
                "source_filename": "a.csv",
            },
            {
                "id": 2,
                "upload_batch_id": 10,
                "bag_id": bid,
                "scan_index": 2,
                "rack": "STV",
                "time_scanned_raw": "Sunday, Aug 30, 2026 1:00 PM",
                "scanned_at_parsed": datetime(2026, 8, 30, 13, 0, 0),
                "user_name": "U",
                "purpose": "",
                "last_location": "",
                "last_scan": "",
                "source_filename": "a.csv",
            },
        ]
    }
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {
            "id": 2,
            "upload_batch_id": 10,
            "bag_id": bid,
            "scan_index": 2,
            "rack": "STV",
            "time_scanned_raw": "Sunday, Aug 30, 2026 1:00 PM",
            "scanned_at_parsed": datetime(2026, 8, 30, 13, 0, 0),
            "user_name": "U",
            "purpose": "",
            "last_location": "",
            "last_scan": "",
            "source_filename": "a.csv",
            "raw_json": '{"x":1}',
        }
    ]
    with patch(
        "backend.rinse_portal_departure_completion.table_exists",
        return_value=True,
    ), patch(
        "backend.rinse_portal_departure_completion.fetch_upload_batch_scan_rows_for_bags",
        return_value=light_rows,
    ):
        by_bag, stats = fetch_draft_scan_rows_missing_from_persistent(
            cursor,
            org,
            [bid],
            up_to_batch_id=10,
            existing_events_by_bag=existing,
        )
    assert stats["draft_rows_examined"] == 2
    assert stats["draft_rows_missing"] == 1
    assert len(by_bag[bid]) == 1
    assert by_bag[bid][0]["id"] == 2
    assert by_bag[bid][0].get("raw_json") == '{"x":1}'
