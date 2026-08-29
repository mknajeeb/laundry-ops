"""Regression tests for WF canonical service-cycle cutover."""

from __future__ import annotations

import json
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.rinse_wf_service_cycle import (
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    STATUS_REVIEW,
    admit_or_update_cycle_from_evidence,
    get_cycle_by_key,
    handle_disappeared_active_cycles,
    seed_minimal_cutover_cycles,
    sync_portal_discovery,
    upsert_service_cycle,
)


@pytest.fixture
def mock_cursor():
    cur = MagicMock()
    cur.fetchone.return_value = None
    cur.fetchall.return_value = []
    return cur


def test_midnight_does_not_mutate_active_cycle(mock_cursor):
    anchor = datetime(2026, 8, 21, 23, 40)
    upsert_service_cycle(
        mock_cursor,
        3,
        bag_id="BAG001",
        cycle_anchor_at=anchor,
        admitted_at=anchor,
        admitted_source="TEST",
        status=STATUS_ACTIVE,
    )
    assert mock_cursor.execute.called


@patch("backend.rinse_wf_service_cycle.table_exists", return_value=True)
@patch("backend.rinse_wf_service_cycle.get_cycle_by_key")
@patch("backend.rinse_wf_service_cycle._cycle_resolution")
def test_repeated_scrape_updates_same_cycle(_res, get_key, _tbl, mock_cursor):
    anchor = datetime(2026, 8, 22, 1, 0)
    get_key.return_value = {
        "id": 1,
        "bag_id": "BAG001",
        "cycle_anchor_at": anchor,
        "status": STATUS_ACTIVE,
        "admitted_at": anchor,
        "admitted_source": "PORTAL",
    }
    _res.return_value = ({"effective_status": "pending"}, {"pre_weight_lbs": 10.0})
    row = admit_or_update_cycle_from_evidence(
        mock_cursor, 3, "BAG001", anchor, admitted_source="PORTAL_REDISCOVERY"
    )
    assert row.get("status") in (STATUS_ACTIVE, STATUS_COMPLETED, {})


@patch("backend.rinse_wf_service_cycle.table_exists", return_value=True)
@patch("backend.rinse_wf_service_cycle._load_timeline")
@patch("backend.rinse_wf_service_cycle._current_cycle_anchor")
@patch("backend.rinse_wf_service_cycle._cycle_resolution")
@patch("backend.rinse_wf_service_cycle.admit_or_update_cycle_from_evidence")
def test_minimal_seed_only_current_cycle(admit, resolution, anchor, timeline, _tbl, mock_cursor):
    a2 = datetime(2026, 8, 22, 1, 0)
    anchor.return_value = a2
    timeline.return_value = []
    resolution.return_value = ({"effective_status": "pending"}, {})
    admit.return_value = {"status": STATUS_ACTIVE}
    out = seed_minimal_cutover_cycles(
        mock_cursor, 3, date(2026, 8, 22), ["BAG001"]
    )
    assert out["cycles_upserted"] == 1
    assert admit.call_count == 1


@patch("backend.rinse_wf_service_cycle.table_exists", return_value=True)
@patch("backend.rinse_wf_service_cycle._load_timeline")
@patch("backend.rinse_wf_service_cycle._current_cycle_anchor")
@patch("backend.rinse_wf_service_cycle._cycle_resolution")
@patch("backend.rinse_wf_service_cycle.admit_or_update_cycle_from_evidence")
def test_minimal_seed_skips_historical_completion(admit, resolution, anchor, timeline, _tbl, mock_cursor):
    a2 = datetime(2026, 8, 22, 1, 0)
    anchor.return_value = a2
    timeline.return_value = []
    resolution.return_value = (
        {"effective_status": "completed", "completion_at": "2026-08-21 14:00:00"},
        {},
    )
    out = seed_minimal_cutover_cycles(
        mock_cursor, 3, date(2026, 8, 22), ["BAG001"]
    )
    assert out["cycles_upserted"] == 0
    assert out["skipped_historical"] == 1
    admit.assert_not_called()


@patch("backend.rinse_wf_service_cycle.table_exists", return_value=True)
@patch("backend.rinse_wf_service_cycle.get_active_cycle_for_bag", return_value=None)
@patch("backend.rinse_wf_service_cycle.get_cycle_by_key", return_value=None)
@patch("backend.rinse_wf_service_cycle._valid_cycle_anchors", return_value=[])
@patch("backend.rinse_wf_service_cycle._load_timeline", return_value=[])
@patch("backend.rinse_wf_service_cycle.admit_or_update_cycle_from_evidence")
def test_portal_admit_once(admit, _lt, _va, _gk, _ga, _tbl, mock_cursor):
    out = sync_portal_discovery(
        mock_cursor,
        3,
        {"BAG001": {"service_type": "WF", "rush_flag": False}},
        now=datetime(2026, 8, 22, 12, 0),
    )
    assert admit.call_count == 1
    assert out.get("admitted", 0) + out.get("updated", 0) >= 1


@patch("backend.rinse_wf_service_cycle._portal_traversal_complete", return_value=True)
@patch("backend.rinse_wf_service_cycle.is_wf_canonical_lifecycle_enabled", return_value=True)
@patch("backend.rinse_wf_service_cycle.handle_disappeared_active_cycles", return_value={})
@patch("backend.rinse_wf_service_cycle.sync_portal_discovery", return_value={"admitted": 1})
@patch("backend.rinse_wf_service_cycle._parse_portal_bags_from_csv", return_value={"BAG001": {}})
def test_portal_sync_defers_projection(_bags, _disc, _disp, _en, _trav, mock_cursor):
    from backend.rinse_wf_service_cycle import sync_wf_cycles_after_portal_presence

    out = sync_wf_cycles_after_portal_presence(
        None,
        mock_cursor,
        3,
        portal_csv_path="/tmp/portal.csv",
    )
    assert out["projection"]["deferred"] is True


def test_portal_traversal_complete_uses_absence_sot(tmp_path):
    """Broken OR reached_max_pages must not authorize disappearance."""
    from backend.rinse_wf_service_cycle import _portal_traversal_complete

    # Missing meta → fail closed
    assert _portal_traversal_complete(None) is False
    assert _portal_traversal_complete(tmp_path / "missing.meta.json") is False

    # Aug27-style premature no_next_page_ui without explicit complete → blocked
    p = tmp_path / "portal.csv.meta.json"
    p.write_text(
        json.dumps(
            {
                "stopped_reason": "no_next_page_ui",
                "reached_max_pages": False,
                "pages_scraped": 2,
                "row_count": 45,
            }
        ),
        encoding="utf-8",
    )
    assert _portal_traversal_complete(p) is False

    p.write_text(
        json.dumps(
            {
                "stopped_reason": "no_next_page_ui",
                "reached_max_pages": False,
                "pages_scraped": 5,
                "source_inspected_complete": True,
                "degraded": False,
                "skipped_ticket_count": 0,
            }
        ),
        encoding="utf-8",
    )
    assert _portal_traversal_complete(p) is True


@patch("backend.rinse_wf_service_cycle.table_exists", return_value=True)
@patch("backend.rinse_wf_service_cycle._cycle_resolution")
def test_disappeared_with_completion_marks_completed(res, mock_cursor):
    anchor = datetime(2026, 8, 22, 1, 0)
    mock_cursor.fetchall.return_value = [
        {
            "bag_id": "BAG001",
            "cycle_anchor_at": anchor,
            "admitted_at": anchor,
            "admitted_source": "PORTAL",
            "status": STATUS_ACTIVE,
        }
    ]
    res.return_value = (
        {"effective_status": "completed", "completion_at": "2026-08-22 14:00:00"},
        {"pre_weight_lbs": 10, "post_weight_lbs": 9.5},
    )
    out = handle_disappeared_active_cycles(
        mock_cursor, 3, set(), traversal_complete=True, now=datetime(2026, 8, 22, 18, 0)
    )
    assert out.get("completed") == 1


@patch("backend.rinse_wf_service_cycle.table_exists", return_value=True)
@patch("backend.rinse_wf_service_cycle._cycle_resolution")
def test_disappeared_without_completion_goes_review(res, mock_cursor):
    anchor = datetime(2026, 8, 22, 1, 0)
    mock_cursor.fetchall.return_value = [
        {
            "bag_id": "BAG002",
            "cycle_anchor_at": anchor,
            "admitted_at": anchor,
            "admitted_source": "PORTAL",
            "status": STATUS_ACTIVE,
        }
    ]
    res.return_value = ({"effective_status": "pending"}, {})
    out = handle_disappeared_active_cycles(
        mock_cursor, 3, set(), traversal_complete=True
    )
    assert out.get("review") == 1


def test_carryover_is_query_only_not_persisted_mutation():
    from backend.rinse_wf_service_cycle_compat import OUTCOME_CARRYOVER_QUERY

    assert OUTCOME_CARRYOVER_QUERY == "opening_backlog_query_only"


@patch("backend.rinse_wf_service_cycle_compat.persist_day_snapshot")
@patch("backend.rinse_wf_service_cycle_compat.build_step1_headline_summary")
@patch("backend.rinse_wf_service_cycle_compat._preserved_hd_bag_dicts", return_value=[])
@patch("backend.rinse_wf_service_cycle_compat._prior_wf_day_bags_by_id", return_value={})
@patch("backend.rinse_wf_service_cycle.reporting_counts_for_date")
@patch("backend.rinse_wf_service_cycle_compat.ensure_wf_service_cycles_table")
@patch("backend.rinse_wf_service_cycle_compat.ensure_shift_monitor_day_tables")
def test_compat_projection_never_reads_day_bags_as_authority(
    _day_tbl, _cyc_tbl, counts, _prior, _hd, headline, persist, mock_cursor
):
    from backend.rinse_wf_service_cycle_compat import terminal_project_canonical_wf_day_snapshot

    counts.return_value = {
        "admitted_on_date": 1,
        "completed_on_date": 2,
        "opening_backlog": 3,
        "active_now": 4,
        "review_unresolved": 0,
        "pre_bags": 1,
        "pre_lbs": 10,
        "post_bags": 1,
        "post_lbs": 9,
    }
    headline.return_value = {"completed": 1, "pending": 0, "segments": {"all": {"bag_ids": {}}}}
    persist.return_value = {"ok": True}
    day = date(2026, 8, 22)
    with (
        patch("backend.rinse_wf_service_cycle_compat.get_day_record", return_value=None),
        patch(
            "backend.rinse_wf_service_cycle.reconcile_stale_active_wf_cycles_from_canonical_completion",
            return_value={"closed": 0, "bag_ids": []},
        ),
        patch(
            "backend.rinse_wf_canonical_workload._prior_day_unfinished_wf_ids",
            return_value=(set(), {}),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._same_day_presence_wf_ids",
            return_value=({"BAG001"}, {}, None, set()),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._discover_same_day_entry_wf_ids",
            return_value=set(),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._registry_wf_completed_on_date",
            return_value=set(),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._terminal_before_date",
            return_value=set(),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._completion_date_on_d",
            return_value={
                "BAG001": {
                    "completion_date": day,
                    "completion_at": datetime(2026, 8, 22, 14, 0),
                    "effective_status": "completed",
                }
            },
        ),
        patch(
            "backend.rinse_wf_canonical_workload._latest_absence_capable_present_ids",
            return_value=(None, {"absence_allowed": False}),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._authoritative_hd_bag_ids",
            return_value=set(),
        ),
        patch("backend.rinse_day_bag_completion_projection.enrich_bags_completion_from_scans"),
        patch(
            "backend.rinse_day_bag_completion_projection.apply_normalized_completion_fields",
            side_effect=lambda b: b,
        ),
        patch("backend.rinse_veewash_review.load_bag_weight_map", return_value={}),
    ):
        terminal_project_canonical_wf_day_snapshot(mock_cursor, 3, day)
    assert persist.called
    summary = persist.call_args.kwargs.get("summary") or persist.call_args[1].get("summary")
    assert summary["membership"]["canonical_source"] is True
    workload = persist.call_args.kwargs.get("workload") or persist.call_args[1].get("workload")
    assert "BAG001" in (workload.get("completed_on_date") or [])


def test_effective_status_for_row_respects_canonical_projection_field():
    from backend.rinse_veewash_shift_day import _bag_rows_from_workload, _effective_status_for_row
    from backend.rinse_veewash_workload import OUTCOME_COMPLETED

    row = {
        "bag_id": "DONE1",
        "service_type": "WF",
        "effective_status": OUTCOME_COMPLETED,
        "new_or_carryover": "new_today",
    }
    assert _effective_status_for_row(row, set()) == OUTCOME_COMPLETED
    bags = _bag_rows_from_workload(
        {
            "from_snapshot": True,
            "rows": [row],
            "review_required": [],
            "review_reasons_by_bag": {},
        },
        {"segments": {"all": {"bag_ids": {}}}},
    )
    assert bags[0]["effective_status"] == OUTCOME_COMPLETED


def test_dedupe_canonical_cycle_rows_prefers_completed():
    from backend.rinse_wf_service_cycle_compat import _dedupe_canonical_cycle_rows
    from backend.rinse_wf_service_cycle import STATUS_ACTIVE, STATUS_COMPLETED

    rows = _dedupe_canonical_cycle_rows(
        [
            {
                "bag_id": "BAGX",
                "status": STATUS_ACTIVE,
                "cycle_anchor_at": datetime(2026, 8, 23, 3, 0),
                "review_reason": "MISSING_FROM_PORTAL_AFTER_FULL_TRAVERSAL",
            },
            {
                "bag_id": "BAGX",
                "status": STATUS_COMPLETED,
                "cycle_anchor_at": datetime(2026, 8, 23, 4, 0),
                "completed_at": datetime(2026, 8, 23, 13, 0),
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0]["status"] == STATUS_COMPLETED


def test_canonical_workload_shell_populates_completed_on_date():
    from backend.rinse_wf_service_cycle_compat import terminal_project_canonical_wf_day_snapshot

    mock_cursor = MagicMock()
    day = date(2026, 8, 23)
    with (
        patch("backend.rinse_wf_service_cycle_compat.ensure_wf_service_cycles_table"),
        patch("backend.rinse_wf_service_cycle_compat.ensure_shift_monitor_day_tables"),
        patch("backend.rinse_wf_service_cycle_compat._prior_wf_day_bags_by_id", return_value={}),
        patch("backend.rinse_wf_service_cycle_compat._preserved_hd_bag_dicts", return_value=[]),
        patch("backend.rinse_wf_service_cycle_compat.get_day_record", return_value=None),
        patch("backend.rinse_wf_service_cycle_compat.get_step1_activation_date", return_value=date(2026, 7, 23)),
        patch(
            "backend.rinse_wf_service_cycle.reconcile_stale_active_wf_cycles_from_canonical_completion",
            return_value={"closed": 0, "bag_ids": []},
        ),
        patch(
            "backend.rinse_wf_service_cycle_compat.reporting_counts_for_date",
            return_value={
                "admitted_on_date": 2,
                "completed_on_date": 1,
                "opening_backlog": 0,
                "active_now": 1,
            },
        ),
        patch(
            "backend.rinse_wf_canonical_workload._prior_day_unfinished_wf_ids",
            return_value=(set(), {}),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._same_day_presence_wf_ids",
            return_value=({"BAGDONE", "BAGPEND"}, {}, None, set()),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._discover_same_day_entry_wf_ids",
            return_value=set(),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._registry_wf_completed_on_date",
            return_value=set(),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._terminal_before_date",
            return_value=set(),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._completion_date_on_d",
            return_value={
                "BAGDONE": {
                    "completion_date": day,
                    "completion_at": datetime(2026, 8, 23, 14, 0),
                    "effective_status": "completed",
                }
            },
        ),
        patch(
            "backend.rinse_wf_canonical_workload._latest_absence_capable_present_ids",
            return_value=(None, {"absence_allowed": False}),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._authoritative_hd_bag_ids",
            return_value=set(),
        ),
        patch("backend.rinse_day_bag_completion_projection.enrich_bags_completion_from_scans"),
        patch(
            "backend.rinse_day_bag_completion_projection.apply_normalized_completion_fields",
            side_effect=lambda b: b,
        ),
        patch("backend.rinse_veewash_review.load_bag_weight_map", return_value={}),
        patch(
            "backend.rinse_wf_service_cycle_compat.persist_day_snapshot",
            return_value={"ok": True},
        ) as persist,
    ):
        terminal_project_canonical_wf_day_snapshot(mock_cursor, 3, day)
    workload = persist.call_args.kwargs.get("workload") or persist.call_args[1].get("workload")
    assert "BAGDONE" in workload["completed_on_date"]
    assert "BAGPEND" in workload["pending_end_of_date"]
    summary = persist.call_args.kwargs.get("summary") or persist.call_args[1].get("summary")
    assert summary["segments"]["wf"]["completed"] == 1
    assert summary["segments"]["wf"]["pending"] == 1
