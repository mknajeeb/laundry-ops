"""Lifecycle Current Workload vs selected-date Completed — authority tests."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_wf_canonical_workload import (
    assert_canonical_workload_invariants,
    get_canonical_wf_workload,
)
from backend.rinse_wf_current_workload import (
    REVIEW_REGISTRY_STALE_COMPLETED,
    get_current_wf_workload,
    get_selected_date_wf_completed,
    lifecycle_received_from_vendor_at,
    registry_stale_completion_review_bags,
)

ORG = 3
D1 = date(2026, 9, 1)
D2 = date(2026, 9, 2)


def _oi(bag_id: str, *, completed_at=None, anchor=None, oi_id=1):
    return {
        "order_instance_id": oi_id,
        "bag_id": bag_id,
        "service_type": "WF",
        "cycle_anchor_at": anchor or datetime(2026, 8, 31, 10, 0),
        "completed_at": completed_at,
        "completion_source": "scan" if completed_at else None,
    }


def _run(
    date_et=D2,
    *,
    open_rows=None,
    completed_rows=None,
    review_bags=None,
    conflict_bags=None,
    hd=None,
):
    cur = MagicMock()
    with (
        patch(
            "backend.rinse_order_instances.list_open_wf_order_instances",
            return_value=list(open_rows or []),
        ),
        patch(
            "backend.rinse_order_instances.list_order_instances_completed_on_date",
            return_value=list(completed_rows or []),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._authoritative_hd_bag_ids",
            return_value=set(hd or []),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._review_wf_bag_ids_from_cycles",
            return_value=set(review_bags or []),
        ),
        patch(
            "backend.rinse_wf_current_workload.registry_stale_completion_review_bags",
            return_value=set(conflict_bags or []),
        ),
        patch(
            "backend.rinse_wf_current_workload.lifecycle_received_from_vendor_at",
            return_value=None,
        ),
    ):
        return get_canonical_wf_workload(cur, ORG, date_et)


def test_current_workload_ignores_selected_date():
    open_rows = [_oi("OPENA"), _oi("OPENB"), _oi("OPENC")]
    wl1 = _run(D1, open_rows=open_rows, completed_rows=[_oi("COMPX", completed_at=datetime(2026, 9, 1, 12))])
    wl2 = _run(D2, open_rows=open_rows, completed_rows=[_oi("COMPY", completed_at=datetime(2026, 9, 2, 12))])
    assert wl1["counts"]["current_open"] == 3
    assert wl2["counts"]["current_open"] == 3
    assert set(wl1["pending"]) | set(wl1["review"]) == {"OPENA", "OPENB", "OPENC"}
    assert set(wl2["pending"]) | set(wl2["review"]) == {"OPENA", "OPENB", "OPENC"}
    assert wl1["completed"] == frozenset({"COMPX"})
    assert wl2["completed"] == frozenset({"COMPY"})
    assert wl1["counts"]["workload"] == 3
    assert wl2["counts"]["workload"] == 3
    assert_canonical_workload_invariants(wl1)
    assert_canonical_workload_invariants(wl2)


def test_registry_cannot_remove_open_oi_from_current_workload():
    """Stale registry COMPLETED must not drop an open OI; conflict → Review."""
    wl = _run(
        D2,
        open_rows=[_oi("STALE")],
        conflict_bags={"STALE"},
    )
    assert "STALE" in wl["current_workload"]["open"]
    assert "STALE" in wl["review"]
    assert "STALE" not in wl["pending"]
    assert "STALE" not in wl["completed"]
    item = next(i for i in wl["current_workload"]["items"] if i["bag_id"] == "STALE")
    assert REVIEW_REGISTRY_STALE_COMPLETED in item["review_reason_codes"]


def test_registry_completed_not_in_selected_date_completed():
    """Registry-only completion never seeds selected_date_completed."""
    wl = _run(D2, open_rows=[], completed_rows=[])
    assert wl["completed"] == frozenset()
    assert wl["selected_date_completed"]["completed"] == frozenset()


def test_reusable_bag_old_completion_does_not_close_new_open():
    # Old OI completed Aug 31 — not on D2 selected-date completed.
    wl = _run(
        D2,
        open_rows=[_oi("REUS", oi_id=2, anchor=datetime(2026, 9, 1, 8))],
        completed_rows=[],
    )
    assert "REUS" in wl["current_workload"]["open"]
    assert "REUS" not in wl["completed"]

    # Same open OI remains in Current Workload while prior OI reports on its completion day.
    wl_d1 = _run(
        D1,
        open_rows=[_oi("REUS", oi_id=2, anchor=datetime(2026, 9, 1, 8))],
        completed_rows=[
            _oi(
                "REUS",
                oi_id=1,
                completed_at=datetime(2026, 9, 1, 12),
                anchor=datetime(2026, 8, 28, 9),
            )
        ],
    )
    assert "REUS" in wl_d1["current_workload"]["open"]
    assert "REUS" in wl_d1["completed"]
    assert wl_d1["counts"]["workload"] == 1  # open only, not open+completed


def test_no_carry_forward_authority():
    wl = _run(
        D2,
        open_rows=[_oi("OLDB", anchor=datetime(2026, 8, 30, 9))],
    )
    assert wl["carryover"] == frozenset()
    assert wl["counts"]["carryover"] == 0
    assert "OLDB" in wl["pending"]


def test_registry_stale_completion_review_helper():
    cur = MagicMock()
    with (
        patch(
            "backend.rinse_wf_current_workload._registry_completed_open_bags",
            return_value={"BAG1", "BAG2"},
        ),
        patch(
            "backend.rinse_wf_current_workload._bags_with_valid_current_cycle_completion",
            return_value={"BAG2"},
        ),
    ):
        out = registry_stale_completion_review_bags(cur, ORG, ["BAG1", "BAG2", "BAG3"])
    assert out == {"BAG1"}


def test_lifecycle_received_from_vendor_not_lifetime_max():
    """Older lifecycle STV must not leak; multiple in-lifecycle STVs → latest."""
    cur = MagicMock()
    anchor = datetime(2026, 9, 1, 10, 0)
    in_lifecycle = datetime(2026, 9, 1, 10, 0)
    later_same = datetime(2026, 9, 1, 14, 0)
    next_oi_anchor = datetime(2026, 9, 2, 8, 0)
    cur.fetchall.return_value = [
        {"purpose": "sent-to-vendor", "scanned_at_parsed": in_lifecycle, "id": 2},
        {"purpose": "sent-to-vendor", "scanned_at_parsed": later_same, "id": 3},
        {"purpose": "weight-entry", "scanned_at_parsed": datetime(2026, 9, 1, 15), "id": 4},
        {"purpose": "sent-to-vendor", "scanned_at_parsed": next_oi_anchor, "id": 5},
    ]
    with patch("backend.rinse_wf_current_workload.table_exists", return_value=True):
        ts = lifecycle_received_from_vendor_at(
            cur,
            ORG,
            "REUS",
            anchor,
            lifecycle_end_exclusive=next_oi_anchor,
        )
    assert ts == later_same
