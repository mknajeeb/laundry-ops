"""Publish-stage evidence refresh must stay scoped to scrape portal bags."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_wf_service_cycle import (
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    STATUS_REVIEW,
    finalize_wf_canonical_lifecycle_terminal,
    refresh_canonical_cycles_from_evidence,
)


def test_refresh_with_bag_ids_adds_in_clause_and_skips_empty_scope():
    cur = MagicMock()
    with patch("backend.rinse_wf_service_cycle.ensure_wf_service_cycles_table"):
        out = refresh_canonical_cycles_from_evidence(
            cur, 3, date(2026, 8, 30), bag_ids=set()
        )
    assert out["refreshed"] == 0
    assert out["scoped"] is True
    assert out["bag_count"] == 0
    cur.execute.assert_not_called()


def test_refresh_with_bag_ids_scopes_sql():
    cur = MagicMock()
    cur.fetchall.return_value = [
        {"bag_id": "ABCDEF12", "cycle_anchor_at": datetime(2026, 8, 30, 8, 0)},
    ]
    with patch(
        "backend.rinse_wf_service_cycle.admit_or_update_cycle_from_evidence"
    ) as admit, patch(
        "backend.rinse_wf_service_cycle.ensure_wf_service_cycles_table"
    ):
        out = refresh_canonical_cycles_from_evidence(
            cur, 3, date(2026, 8, 30), bag_ids={"ABCDEF12", "BBBCCC12"}
        )
    assert out["refreshed"] == 1
    assert out["scoped"] is True
    assert out["bag_count"] == 2
    sql = cur.execute.call_args[0][0]
    params = cur.execute.call_args[0][1]
    assert "bag_id IN" in sql
    assert "ABCDEF12" in params and "BBBCCC12" in params
    assert STATUS_ACTIVE in params and STATUS_REVIEW in params and STATUS_COMPLETED in params
    admit.assert_called_once()


def test_terminal_finalize_passes_portal_bag_scope():
    cur = MagicMock()
    with patch(
        "backend.rinse_wf_service_cycle.is_wf_canonical_lifecycle_enabled",
        return_value=True,
    ), patch(
        "backend.rinse_wf_service_cycle._parse_portal_bags_from_csv",
        return_value={"BAG1": {}, "BAG2": {}},
    ), patch(
        "backend.rinse_wf_service_cycle.refresh_canonical_cycles_from_evidence",
        return_value={"refreshed": 2, "scoped": True},
    ) as refresh, patch(
        "backend.rinse_wf_service_cycle.sync_portal_discovery",
        return_value={},
    ), patch(
        "backend.rinse_wf_service_cycle.handle_disappeared_active_cycles",
        return_value={},
    ), patch(
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
    assert out["ok"] is True
    assert refresh.call_count == 2
    for call in refresh.call_args_list:
        assert call.kwargs.get("bag_ids") == {"BAG1", "BAG2"}
