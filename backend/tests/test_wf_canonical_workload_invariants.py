"""Invariant tests for lifecycle-based get_canonical_wf_workload."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_wf_canonical_workload import (
    LIFECYCLE_COMPLETED,
    LIFECYCLE_OPEN,
    assert_canonical_workload_invariants,
    get_canonical_wf_workload,
    get_wf_bag_lifecycle,
)

ORG = 3
D = date(2026, 8, 28)


def _oi(bag_id: str, *, completed_at=None, anchor=None):
    return {
        "order_instance_id": 1,
        "bag_id": bag_id,
        "service_type": "WF",
        "cycle_anchor_at": anchor or datetime(2026, 8, 27, 10, 0),
        "completed_at": completed_at,
    }


def _run(
    cur=None,
    *,
    open_rows=None,
    completed_rows=None,
    authoritative_hd=None,
    review_bags=None,
    conflict_bags=None,
):
    cur = cur or MagicMock()
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
            return_value=set(authoritative_hd or []),
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
        return get_canonical_wf_workload(cur, ORG, D)


def test_open_oi_beats_stale_registry_completion():
    """Registry COMPLETED must not complete/remove an open OI — conflict → Review."""
    wl = _run(open_rows=[_oi("BZ9A")], conflict_bags={"BZ9A"})
    assert "BZ9A" in wl["review"]
    assert "BZ9A" in wl["current_workload"]["open"]
    assert "BZ9A" not in wl["completed"]
    assert wl["counts"]["current_open"] == 1
    assert_canonical_workload_invariants(wl)


def test_terminal_registry_no_longer_removes_open_oi():
    """terminal_before_date is not applied; open OI stays in Current Workload."""
    wl = _run(open_rows=[_oi("TERM")])
    assert "TERM" in wl["pending"]
    assert_canonical_workload_invariants(wl)


def test_open_oi_persists_without_discovery_seeds():
    wl = _run(open_rows=[_oi("OPEN")])
    assert "OPEN" in wl["pending"]
    assert wl["missing_from_portal"] == frozenset()


def test_discovery_absence_never_creates_mfp():
    wl = _run(open_rows=[_oi("OPEN")])
    assert wl["missing_from_portal"] == frozenset()
    assert "OPEN" not in wl["review"]


def test_completed_on_date_separate_from_open():
    wl = _run(
        open_rows=[_oi("PEND")],
        completed_rows=[_oi("COMP", completed_at=datetime(2026, 8, 28, 14, 0))],
    )
    assert "COMP" in wl["completed"]
    assert "PEND" in wl["pending"]
    assert wl["counts"]["workload"] == 1  # open only
    assert_canonical_workload_invariants(wl)


def test_carryover_removed_from_authority():
    wl = _run(open_rows=[_oi("CARY", anchor=datetime(2026, 8, 27, 9, 0))])
    assert wl["carryover"] == frozenset()
    assert wl["bag_meta"]["CARY"]["new_or_carryover"] is None


def test_current_workload_not_daily_equation():
    wl = _run(
        open_rows=[_oi("PEND"), _oi("REVW")],
        completed_rows=[_oi("COMP", completed_at=datetime(2026, 8, 28, 12, 0))],
        review_bags={"REVW"},
    )
    assert wl["counts"]["workload"] == 2
    assert wl["counts"]["completed"] == 1
    assert wl["bag_ids"] == frozenset({"PEND", "REVW", "COMP"})
    assert_canonical_workload_invariants(wl)


def test_lifecycle_completed_is_terminal():
    cur = MagicMock()
    with patch(
        "backend.rinse_order_instances.get_latest_order_instance_for_bag",
        return_value=None,
    ), patch(
        "backend.rinse_bag_registry.get_registry_row",
        return_value={
            "completion_status": "COMPLETED",
            "completed_at": datetime(2026, 8, 20, 12, 0),
        },
    ):
        life = get_wf_bag_lifecycle(cur, ORG, "BAG1")
    assert life["lifecycle"] == LIFECYCLE_COMPLETED


def test_lifecycle_open_default():
    cur = MagicMock()
    with patch(
        "backend.rinse_order_instances.get_latest_order_instance_for_bag",
        return_value=None,
    ), patch("backend.rinse_bag_registry.get_registry_row", return_value=None):
        life = get_wf_bag_lifecycle(cur, ORG, "BAG1")
    assert life["lifecycle"] == LIFECYCLE_OPEN


def test_hd_evidence_excludes_wf_open():
    hd = "7M07HHS5BU"
    wl = _run(
        open_rows=[_oi(hd), _oi("WFKP")],
        authoritative_hd={hd},
    )
    assert hd not in wl["current_workload"]["open"]
    assert "WFKP" in wl["pending"]
    assert_canonical_workload_invariants(wl)


def test_authoritative_hd_intersection_empty():
    hd = "2QFDTDTULL"
    wl = _run(
        open_rows=[_oi(hd)],
        completed_rows=[_oi(hd, completed_at=datetime(2026, 8, 28, 12, 0))],
        authoritative_hd={hd},
    )
    assert wl["current_workload"]["open"] == frozenset()
    assert wl["completed"] == frozenset()
