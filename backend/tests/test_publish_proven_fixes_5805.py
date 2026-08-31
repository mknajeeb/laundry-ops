"""Regression tests for run-5805 proven publish / SM / absence fixes."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_portal_departure_completion import (
    fetch_draft_scan_rows_missing_from_persistent,
)
from backend.rinse_scan_event_identity import compute_scan_event_dedupe_key
from backend.rinse_step1_scrape_refresh import refresh_step1_after_scrape
from backend.rinse_veewash_shift_day import (
    _canonical_terminal_projection_succeeded,
    backfill_day_from_live,
)
from backend.rinse_wf_service_cycle import (
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    STATUS_RESOLVED_OTHER,
    finalize_wf_canonical_lifecycle_terminal,
    refresh_canonical_cycles_from_evidence,
    supersede_stale_portal_discovery_active_duplicates,
    sync_portal_discovery,
)


def test_canonical_projection_success_when_day_record_returned():
    day = {"status": "OPEN", "last_sync_at": datetime(2026, 8, 31, 0, 53, 4)}
    assert _canonical_terminal_projection_succeeded(day, day) is True
    assert _canonical_terminal_projection_succeeded({"ok": True}, day) is True
    assert _canonical_terminal_projection_succeeded({"ok": False}, day) is False
    assert _canonical_terminal_projection_succeeded({}, None) is False


def test_backfill_day_from_live_ok_when_projection_returns_day_record():
    cur = MagicMock()
    day = {"status": "OPEN", "last_sync_at": datetime(2026, 8, 31, 0, 53, 4)}
    with patch(
        "backend.rinse_wf_service_cycle.is_wf_canonical_lifecycle_enabled",
        return_value=True,
    ), patch(
        "backend.rinse_wf_service_cycle_compat.terminal_project_canonical_wf_day_snapshot",
        return_value=day,
    ), patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        return_value=day,
    ), patch(
        "backend.rinse_veewash_shift_day.summary_from_day_record",
        return_value={"segments": {"wf": {"completed": 1, "pending": 0}}},
    ), patch(
        "backend.rinse_veewash_shift_day.load_day_bags",
        return_value=[{"bag_id": "BAG1"}],
    ), patch(
        "backend.rinse_veewash_shift_day.get_step1_activation_date",
        return_value=date(2026, 7, 23),
    ), patch(
        "backend.rinse_veewash_shift_day._step1_cutover_date",
        return_value=date(2026, 7, 23),
    ):
        out = backfill_day_from_live(cur, 3, date(2026, 8, 30), force=True)
    assert out["ok"] is True
    assert out["persisted"] is True


def test_step1_refresh_success_after_canonical_backfill_day_record():
    conn = MagicMock()
    cur = MagicMock()
    day = {"status": "OPEN", "last_sync_at": datetime(2026, 8, 31, 0, 53, 4)}
    with patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        return_value={"status": "OPEN"},
    ), patch(
        "backend.rinse_veewash_shift_day.today_et",
        return_value=date(2026, 8, 30),
    ), patch(
        "backend.rinse_scan_chronology_gate.evaluate_step1_rebuild_gate",
        return_value={"deferred": False, "allow_persist": True, "gate_decision": "allow"},
    ), patch(
        "backend.rinse_step1_evidence_gate.resolve_batch_id_for_stage_b",
        return_value=5176,
    ), patch(
        "backend.rinse_step1_evidence_gate.fetch_projection_deferred_bag_ids",
        return_value=[],
    ), patch(
        "backend.rinse_veewash_shift_day.backfill_day_from_live",
        return_value={
            "ok": True,
            "day": day,
            "bag_count": 96,
            "summary_totals": {"active": 94, "completed": 94, "pending": 0},
        },
    ), patch(
        "backend.rinse_step1_scrape_refresh.verify_step1_snapshot_freshness",
        return_value={"fresh": True, "reason": "ok"},
    ), patch(
        "backend.rinse_step1_scrape_refresh._persist_day_meta_diagnostics",
    ), patch(
        "backend.rinse_step1_scrape_refresh.record_evidence_import_pending",
        return_value=1,
    ), patch(
        "backend.rinse_step1_scrape_refresh._update_refresh_row",
    ):
        out = refresh_step1_after_scrape(
            conn,
            cur,
            organization_id=3,
            operations_date_et=date(2026, 8, 30),
            import_batch_id=5176,
            scrape_run_id=5805,
        )
    assert out["ok"] is True
    assert out["step1_refresh_status"] == "SUCCESS"
    assert out.get("error") is None


def test_repeated_portal_discovery_reuses_portal_only_active():
    cur = MagicMock()
    now = datetime(2026, 8, 30, 20, 0, 0)
    active_anchor = datetime(2026, 8, 30, 18, 0, 0)
    active = {
        "bag_id": "BAGPORT1",
        "cycle_anchor_at": active_anchor,
        "status": STATUS_ACTIVE,
        "admitted_source": "PORTAL_DISCOVERY",
    }
    with patch(
        "backend.rinse_wf_service_cycle._load_timeline",
        return_value=[],
    ), patch(
        "backend.rinse_wf_service_cycle._valid_cycle_anchors",
        return_value=[],
    ), patch(
        "backend.rinse_wf_service_cycle.get_active_cycle_for_bag",
        return_value=active,
    ), patch(
        "backend.rinse_wf_service_cycle._update_portal_cycle_metadata",
        return_value=True,
    ) as touch, patch(
        "backend.rinse_wf_service_cycle.admit_or_update_cycle_from_evidence",
    ) as admit:
        out = sync_portal_discovery(
            cur,
            3,
            {"BAGPORT1": {"service_type": "WF"}},
            now=now,
            evidence_refreshed_bag_ids={"BAGPORT1"},
        )
    touch.assert_called_once()
    admit.assert_not_called()
    assert out["metadata_only"] == 1
    assert out["admitted"] == 0


def test_completed_lifecycle_plus_new_stv_still_admits_new_cycle():
    cur = MagicMock()
    now = datetime(2026, 8, 30, 20, 0, 0)
    old_anchor = datetime(2026, 8, 28, 10, 0, 0)
    new_anchor = datetime(2026, 8, 30, 8, 0, 0)
    active = {
        "bag_id": "REUSEBAG1",
        "cycle_anchor_at": old_anchor,
        "status": STATUS_COMPLETED,
        "admitted_source": "SCAN_EVIDENCE_REFRESH",
    }
    with patch(
        "backend.rinse_wf_service_cycle._load_timeline",
        return_value=[{"purpose": "sent-to-vendor", "scanned_at_parsed": new_anchor}],
    ), patch(
        "backend.rinse_wf_service_cycle._valid_cycle_anchors",
        return_value=[new_anchor],
    ), patch(
        "backend.rinse_wf_service_cycle.get_active_cycle_for_bag",
        return_value=active,
    ), patch(
        "backend.rinse_wf_service_cycle.admit_or_update_cycle_from_evidence",
    ) as admit, patch(
        "backend.rinse_wf_service_cycle._update_portal_cycle_metadata",
        return_value=False,
    ):
        out = sync_portal_discovery(
            cur,
            3,
            {"REUSEBAG1": {"service_type": "WF"}},
            now=now,
        )
    admit.assert_called_once()
    assert admit.call_args.args[3] == new_anchor
    assert out["admitted"] == 1


def test_scoped_refresh_uses_latest_active_per_bag_sql():
    cur = MagicMock()
    cur.fetchall.return_value = [
        {"bag_id": "BAGA", "cycle_anchor_at": datetime(2026, 8, 30, 12, 0)},
    ]
    with patch(
        "backend.rinse_wf_service_cycle.ensure_wf_service_cycles_table"
    ), patch(
        "backend.rinse_wf_service_cycle.admit_or_update_cycle_from_evidence",
    ) as admit:
        out = refresh_canonical_cycles_from_evidence(
            cur, 3, date(2026, 8, 30), bag_ids={"BAGA", "BAGB"}
        )
    sql = cur.execute.call_args[0][0]
    assert "MAX(cycle_anchor_at)" in sql
    assert "UNION" in sql
    assert out["refreshed"] == 1
    admit.assert_called_once()


def test_publish_passes_evidence_refreshed_bags_to_discovery():
    cur = MagicMock()
    with patch(
        "backend.rinse_wf_service_cycle.is_wf_canonical_lifecycle_enabled",
        return_value=True,
    ), patch(
        "backend.rinse_wf_service_cycle._parse_portal_bags_from_csv",
        return_value={"BAG1": {}, "BAG2": {}},
    ), patch(
        "backend.rinse_wf_service_cycle.refresh_canonical_cycles_from_evidence",
        return_value={"refreshed": 2, "scoped": True, "bag_count": 2},
    ), patch(
        "backend.rinse_wf_service_cycle.sync_portal_discovery",
        return_value={"admitted": 0, "updated": 0, "metadata_only": 2},
    ) as discovery, patch(
        "backend.rinse_wf_service_cycle.handle_disappeared_active_cycles",
        return_value={},
    ), patch(
        "backend.rinse_wf_service_cycle._portal_traversal_complete",
        return_value=True,
    ), patch(
        "backend.rinse_wf_service_cycle_compat.terminal_project_canonical_wf_day_snapshot",
        return_value={"status": "OPEN", "last_sync_at": datetime.utcnow()},
    ):
        finalize_wf_canonical_lifecycle_terminal(
            cur,
            3,
            portal_csv_path="/tmp/portal.csv",
            shift_date_et=date(2026, 8, 30),
        )
    assert discovery.call_args.kwargs.get("evidence_refreshed_bag_ids") == {
        "BAG1",
        "BAG2",
    }


def test_absence_fetch_uses_indexed_bag_scoped_draft_load():
    """Draft fetch uses exact bag_id (idx_ubse_bag), not anti-join full scan."""
    from backend.rinse_portal_departure_completion import (
        fetch_draft_scan_rows_missing_from_persistent,
    )
    from backend.rinse_scan_event_identity import compute_scan_event_dedupe_key

    org = 3
    bid = "BAGABS2"
    scanned = datetime(2026, 8, 30, 12, 0, 0)
    missing_scanned = datetime(2026, 8, 30, 13, 0, 0)
    dk_present = compute_scan_event_dedupe_key(
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
                "dedupe_key": dk_present,
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
                "id": 99,
                "upload_batch_id": 10,
                "bag_id": bid,
                "scan_index": 2,
                "rack": "STV",
                "time_scanned_raw": "Sunday, Aug 30, 2026 1:00 PM",
                "scanned_at_parsed": missing_scanned,
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
            **light_rows[bid][1],
            "raw_json": '{"x":1}',
        }
    ]
    with patch(
        "backend.rinse_portal_departure_completion.table_exists",
        return_value=True,
    ), patch(
        "backend.rinse_portal_departure_completion.fetch_upload_batch_scan_rows_for_bags",
        return_value=light_rows,
    ) as fetch_light:
        by_bag, stats = fetch_draft_scan_rows_missing_from_persistent(
            cursor,
            org,
            [bid],
            up_to_batch_id=10,
            existing_events_by_bag=existing,
        )
    fetch_light.assert_called_once()
    assert fetch_light.call_args.kwargs.get("include_raw_json") is False
    assert stats["draft_rows_examined"] == 2
    assert stats["draft_rows_missing"] == 1
    assert len(by_bag[bid]) == 1
    assert by_bag[bid][0]["id"] == 99


def test_supersede_skips_ambiguous_multiple_stv_active():
    cur = MagicMock()
    anchor_a = datetime(2026, 8, 28, 8, 0)
    anchor_b = datetime(2026, 8, 30, 8, 0)
    cur.fetchall.side_effect = [
        [{"bag_id": "AMBIG1"}],
        [
            {
                "id": 1,
                "bag_id": "AMBIG1",
                "cycle_anchor_at": anchor_a,
                "status": STATUS_ACTIVE,
                "admitted_source": "PORTAL_DISCOVERY",
            },
            {
                "id": 2,
                "bag_id": "AMBIG1",
                "cycle_anchor_at": anchor_b,
                "status": STATUS_ACTIVE,
                "admitted_source": "PORTAL_DISCOVERY",
            },
        ],
    ]
    with patch(
        "backend.rinse_wf_service_cycle._load_timeline",
        return_value=[{"purpose": "sent-to-vendor"}],
    ), patch(
        "backend.rinse_wf_service_cycle._valid_cycle_anchors",
        return_value=[anchor_a, anchor_b],
    ), patch(
        "backend.rinse_wf_service_cycle.ensure_wf_service_cycles_table",
    ):
        report = supersede_stale_portal_discovery_active_duplicates(
            cur, 3, bag_ids=["AMBIG1"], dry_run=True
        )
    assert report["rows_superseded"] == 0
    assert report["ambiguous_bags"]


def test_supersede_marks_stale_portal_only_duplicate_resolved_other():
    cur = MagicMock()
    old = datetime(2026, 8, 30, 18, 0)
    new = datetime(2026, 8, 30, 20, 0)
    cur.fetchall.side_effect = [
        [{"bag_id": "DUPBAG1"}],
        [
            {
                "id": 10,
                "bag_id": "DUPBAG1",
                "cycle_anchor_at": old,
                "status": STATUS_ACTIVE,
                "admitted_source": "PORTAL_DISCOVERY",
            },
            {
                "id": 11,
                "bag_id": "DUPBAG1",
                "cycle_anchor_at": new,
                "status": STATUS_ACTIVE,
                "admitted_source": "PORTAL_DISCOVERY",
            },
        ],
    ]
    with patch(
        "backend.rinse_wf_service_cycle._load_timeline",
        return_value=[],
    ), patch(
        "backend.rinse_wf_service_cycle._valid_cycle_anchors",
        return_value=[],
    ), patch(
        "backend.rinse_wf_service_cycle.ensure_wf_service_cycles_table",
    ):
        report = supersede_stale_portal_discovery_active_duplicates(
            cur, 3, bag_ids=["DUPBAG1"], dry_run=False
        )
    assert report["rows_superseded"] == 1
    update_sql = cur.execute.call_args_list[-1][0][0]
    assert "UPDATE rinse_wf_service_cycles" in update_sql
    assert cur.execute.call_args_list[-1][0][1][0] == STATUS_RESOLVED_OTHER
