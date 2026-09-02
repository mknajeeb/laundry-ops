"""Invariant tests for lifecycle-based get_canonical_wf_workload."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.rinse_wf_canonical_workload import (
    LIFECYCLE_COMPLETED,
    LIFECYCLE_OPEN,
    OUTCOME_CARRYOVER,
    assert_canonical_workload_invariants,
    get_canonical_wf_workload,
    get_wf_bag_lifecycle,
)
from backend.rinse_veewash_workload import (
    OUTCOME_COMPLETED,
    OUTCOME_PENDING,
    OUTCOME_REVIEW_REQUIRED,
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


def _wl_patches(
    *,
    open_rows=None,
    completed_rows=None,
    terminal=None,
    legacy_completed=None,
    authoritative_hd=None,
    review_bags=None,
):
    open_rows = list(open_rows or [])
    completed_rows = list(completed_rows or [])
    legacy_completed = dict(legacy_completed or {})

    return (
        patch(
            "backend.rinse_order_instances.list_open_wf_order_instances",
            return_value=open_rows,
        ),
        patch(
            "backend.rinse_order_instances.list_order_instances_completed_on_date",
            return_value=completed_rows,
        ),
        patch(
            "backend.rinse_wf_canonical_workload._completion_date_on_d",
            return_value=legacy_completed,
        ),
        patch(
            "backend.rinse_wf_canonical_workload._terminal_before_date",
            return_value=set(terminal or []),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._authoritative_hd_bag_ids",
            return_value=set(authoritative_hd or []),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._review_wf_bag_ids_from_cycles",
            return_value=set(review_bags or []),
        ),
    )


def _run(cur=None, **kwargs):
    cur = cur or MagicMock()
    patches = _wl_patches(**kwargs)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        return get_canonical_wf_workload(cur, ORG, D)


def test_open_oi_beats_stale_registry_completion():
    """Registry COMPLETED must not complete a bag that still has an open OI."""
    wl = _run(
        open_rows=[_oi("BZ9A")],
        legacy_completed={
            "BZ9A": {
                "completion_date": D,
                "effective_status": "completed",
                "completion_source": "registry",
            }
        },
    )
    assert "BZ9A" in wl["pending"]
    assert "BZ9A" not in wl["completed"]
    assert wl["counts"]["current_open"] == 1
    assert_canonical_workload_invariants(wl)


def test_terminal_registry_excludes_from_open():
    wl = _run(
        open_rows=[_oi("TERM")],
        terminal={"TERM"},
    )
    assert "TERM" not in wl["bag_ids"]
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
        completed_rows=[
            _oi("COMP", completed_at=datetime(2026, 8, 28, 14, 0)),
        ],
    )
    assert "COMP" in wl["completed"]
    assert "PEND" in wl["pending"]
    assert_canonical_workload_invariants(wl)


def test_carryover_metadata_from_oi_anchor():
    wl = _run(open_rows=[_oi("CARY", anchor=datetime(2026, 8, 27, 9, 0))])
    assert "CARY" in wl["carryover"]
    assert wl["bag_meta"]["CARY"]["new_or_carryover"] == OUTCOME_CARRYOVER


def test_workload_union_pending_review_completed():
    wl = _run(
        open_rows=[_oi("PEND"), _oi("REVW")],
        completed_rows=[_oi("COMP", completed_at=datetime(2026, 8, 28, 12, 0))],
        review_bags={"REVW"},
    )
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
    assert hd not in wl["bag_ids"]
    assert "WFKP" in wl["bag_ids"]
    assert_canonical_workload_invariants(wl)


def test_authoritative_hd_intersection_empty():
    hd = "2QFDTDTULL"
    wl = _run(
        open_rows=[_oi(hd)],
        completed_rows=[_oi(hd, completed_at=datetime(2026, 8, 28, 12, 0))],
        authoritative_hd={hd},
    )
    assert wl["bag_ids"] == frozenset()
    assert_canonical_workload_invariants(wl)
