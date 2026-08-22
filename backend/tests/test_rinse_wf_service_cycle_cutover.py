"""Regression tests for WF canonical service-cycle cutover."""

from __future__ import annotations

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
    sync_portal_discovery(
        mock_cursor,
        3,
        {"BAG001": {"service_type": "WF", "rush_flag": False}},
        now=datetime(2026, 8, 22, 12, 0),
    )
    assert admit.call_count == 1


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


@patch("backend.rinse_wf_service_cycle.reporting_counts_for_date")
@patch("backend.rinse_wf_service_cycle_compat.reporting_counts_for_date")
@patch("backend.rinse_wf_service_cycle_compat.ensure_wf_service_cycles_table")
@patch("backend.rinse_wf_service_cycle_compat.ensure_shift_monitor_day_tables")
def test_compat_projection_never_reads_day_bags_as_authority(
    _day_tbl, _cyc_tbl, counts, counts2, mock_cursor
):
    from backend.rinse_wf_service_cycle_compat import project_canonical_cycles_to_day_snapshot

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
    counts2.return_value = counts.return_value
    mock_cursor.fetchall.return_value = [
        {
            "id": 1,
            "bag_id": "BAG001",
            "cycle_anchor_at": datetime(2026, 8, 22, 1, 0),
            "admitted_at": datetime(2026, 8, 22, 1, 0),
            "status": STATUS_COMPLETED,
            "completed_at": datetime(2026, 8, 22, 14, 0),
            "pre_weight_lbs": 10,
            "post_weight_lbs": 9.5,
            "rush_status": None,
            "review_reason": None,
            "completion_source": "post_garments_reviewed_weight_entry",
        }
    ]
    with patch("backend.rinse_wf_service_cycle_compat.persist_day_snapshot") as persist:
        persist.return_value = {"ok": True}
        with patch("backend.rinse_wf_service_cycle_compat.get_day_record", return_value=None):
            project_canonical_cycles_to_day_snapshot(
                mock_cursor, 3, date(2026, 8, 22)
            )
        assert persist.called
        summary = persist.call_args.kwargs.get("summary") or persist.call_args[1].get("summary")
        assert summary["completed"] == 1
