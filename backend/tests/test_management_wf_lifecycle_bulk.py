"""Parity + DDL guard for Management lifecycle bulk reads."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

from backend.management_wf_lifecycle_bulk import bulk_load_next_oi_anchors
from backend.rinse_wf_current_workload import (
    _next_oi_cycle_anchor,
    lifecycle_received_from_vendor_at,
)


def test_next_oi_anchor_does_not_ddl_when_ensure_schema_false_for_100_ois():
    cur = MagicMock()
    cur.fetchone.return_value = {"cycle_anchor_at": datetime(2026, 9, 2, 8, 0)}
    with patch(
        "backend.rinse_order_instances.ensure_rinse_order_instances_table"
    ) as ensure:
        for i in range(100):
            _next_oi_cycle_anchor(
                cur, 3, f"BAG{i:03d}X", datetime(2026, 9, 1, 8, 0), ensure_schema=False
            )
        ensure.assert_not_called()


def test_next_oi_anchor_default_still_ensures_each_call_for_scraper():
    cur = MagicMock()
    cur.fetchone.return_value = None
    with patch(
        "backend.rinse_order_instances.ensure_rinse_order_instances_table"
    ) as ensure:
        for _ in range(3):
            _next_oi_cycle_anchor(cur, 3, "BAGXXXX1", datetime(2026, 9, 1, 8, 0))
        assert ensure.call_count == 3


def test_bulk_next_anchors_match_single_bag_semantics():
    """In-memory next derivation matches ascending > anchor rule."""
    cur = MagicMock()

    def execute(sql, params=None):
        cur._last_sql = sql
        cur._last_params = params

    cur.execute.side_effect = execute
    # Two bags; B1 has anchors 8am and 2pm; query asks for next after 8am → 2pm
    cur.fetchall.return_value = [
        {"bag_id": "BAG1XXXX", "cycle_anchor_at": datetime(2026, 9, 1, 8, 0)},
        {"bag_id": "BAG1XXXX", "cycle_anchor_at": datetime(2026, 9, 1, 14, 0)},
        {"bag_id": "BAG2XXXX", "cycle_anchor_at": datetime(2026, 9, 1, 9, 0)},
    ]
    with patch("backend.management_wf_lifecycle_bulk.table_exists", return_value=True):
        out = bulk_load_next_oi_anchors(
            cur,
            3,
            [
                ("BAG1XXXX", datetime(2026, 9, 1, 8, 0)),
                ("BAG1XXXX", datetime(2026, 9, 1, 14, 0)),
                ("BAG2XXXX", datetime(2026, 9, 1, 9, 0)),
            ],
        )
    assert out[("BAG1XXXX", datetime(2026, 9, 1, 8, 0))] == datetime(2026, 9, 1, 14, 0)
    assert out[("BAG1XXXX", datetime(2026, 9, 1, 14, 0))] is None
    assert out[("BAG2XXXX", datetime(2026, 9, 1, 9, 0))] is None


def test_rfv_preloaded_rows_match_sql_path_filtering():
    anchor = datetime(2026, 9, 1, 8, 0)
    end = datetime(2026, 9, 2, 8, 0)
    rows = [
        {"purpose": "sent-to-vendor", "scanned_at_parsed": datetime(2026, 9, 1, 10, 0), "id": 1},
        {"purpose": "sent-to-vendor", "scanned_at_parsed": datetime(2026, 9, 1, 12, 0), "id": 2},
        {"purpose": "sent-to-vendor", "scanned_at_parsed": datetime(2026, 9, 2, 9, 0), "id": 3},  # outside
        {"purpose": "garments-reviewed", "scanned_at_parsed": datetime(2026, 9, 1, 11, 0), "id": 4},
    ]
    cur = MagicMock()
    ts = lifecycle_received_from_vendor_at(
        cur,
        3,
        "BAGX",
        anchor,
        lifecycle_end_exclusive=end,
        preloaded_rows=rows,
    )
    assert ts == datetime(2026, 9, 1, 12, 0)
    cur.execute.assert_not_called()
