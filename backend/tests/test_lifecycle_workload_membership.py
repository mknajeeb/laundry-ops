"""Lifecycle-based WF/HD workload membership — frozen architecture regression tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from backend.management_rinse_hd import (
    STATUS_COMPLETE,
    STATUS_PENDING_WASH,
    _load_hd_discovery_bag_ids,
    build_rinse_hd_day,
)
from backend.rinse_wf_canonical_workload import (
    get_canonical_wf_workload,
)
from backend.rinse_wf_service_cycle import STATUS_REVIEW

ORG = 3
D1 = date(2026, 8, 31)
D2 = date(2026, 9, 1)
D3 = date(2026, 9, 2)


def _oi_row(bag_id: str, *, completed_at=None, anchor=None, oi_id=1):
    return {
        "order_instance_id": oi_id,
        "bag_id": bag_id,
        "service_type": "WF",
        "cycle_anchor_at": anchor or datetime(2026, 8, 31, 10, 0),
        "completed_at": completed_at,
        "completion_source": "scan" if completed_at else None,
    }


def _run_wf(
    cur=None,
    date_et=D2,
    *,
    open_rows=None,
    completed_rows=None,
    terminal=None,
    hd=None,
    review_bags=None,
):
    cur = cur or MagicMock()
    open_rows = open_rows or []
    completed_rows = completed_rows or []
    with (
        patch(
            "backend.rinse_order_instances.list_open_wf_order_instances",
            return_value=open_rows,
        ),
        patch(
            "backend.rinse_order_instances.list_order_instances_completed_on_date",
            return_value=completed_rows,
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
            return_value=set(),
        ),
        patch(
            "backend.rinse_wf_current_workload.lifecycle_received_from_vendor_at",
            return_value=None,
        ),
    ):
        return get_canonical_wf_workload(cur, ORG, date_et)


def test_wf_persistence_across_days_absent_from_discovery():
    """Discovered D1, absent D2 discovery window — still current workload D2."""
    wl = _run_wf(
        date_et=D2,
        open_rows=[_oi_row("WFKE", anchor=datetime(2026, 8, 31, 9, 0))],
    )
    assert "WFKE" in wl["pending"]
    assert wl["missing_from_portal"] == frozenset()
    assert "WFKE" not in wl["completed"]


def test_wf_completion_leaves_open_and_reports_on_completion_day():
    """Open D1 → completes D3 → removed from open → completed on D3."""
    wl_open = _run_wf(
        date_et=D2,
        open_rows=[_oi_row("DON3", anchor=datetime(2026, 8, 31, 9, 0))],
    )
    assert "DON3" in wl_open["pending"]

    wl_done = _run_wf(
        date_et=D3,
        open_rows=[],
        completed_rows=[
            _oi_row(
                "DON3",
                completed_at=datetime(2026, 9, 2, 15, 0),
                anchor=datetime(2026, 8, 31, 9, 0),
            )
        ],
    )
    assert "DON3" not in wl_done["pending"]
    assert "DON3" in wl_done["completed"]


def test_wf_no_date_resurrection_for_completed():
    """Completed D1 must not appear in current open workload on D2."""
    wl = _run_wf(
        date_et=D2,
        open_rows=[],
        completed_rows=[
            _oi_row(
                "OLD1",
                completed_at=datetime(2026, 8, 31, 12, 0),
                anchor=datetime(2026, 8, 30, 9, 0),
            )
        ],
    )
    assert "OLD1" not in wl["pending"]
    assert "OLD1" not in wl["review"]
    assert "OLD1" in wl["completed"]


def test_wf_reusable_bag_new_instance_in_open_after_prior_complete():
    """OI-A completed → boundary → OI-B open → OI-B in current workload only."""
    wl = _run_wf(
        date_et=D2,
        open_rows=[
            _oi_row(
                "REUS",
                oi_id=2,
                anchor=datetime(2026, 9, 1, 8, 0),
            )
        ],
        completed_rows=[
            _oi_row(
                "REUS",
                oi_id=1,
                completed_at=datetime(2026, 8, 31, 18, 0),
                anchor=datetime(2026, 8, 28, 9, 0),
            )
        ],
    )
    assert "REUS" in wl["pending"]
    assert "REUS" in wl["completed"]


def test_wf_discovery_absence_does_not_create_mfp():
    """Open OI outside STV window stays open; discovery absence never marks MFP."""
    wl = _run_wf(
        date_et=D2,
        open_rows=[_oi_row("OUTW")],
        review_bags=[],
    )
    assert "OUTW" in wl["pending"]
    assert wl["missing_from_portal"] == frozenset()
    assert "OUTW" not in wl["review"]


def test_wf_unknown_weight_does_not_remove_from_workload():
    """?? LBS metadata must not drop an open order from workload."""
    wl = _run_wf(
        date_et=D2,
        open_rows=[_oi_row("WGHT")],
    )
    assert "WGHT" in wl["pending"]


def test_hd_discovery_bag_ids_from_active_presence_not_date():
    cur = MagicMock()
    cur.fetchall.side_effect = [
        [{"bag_id": "HD1", "service_type": "hang_dry"}],
        [],
    ]
    with patch("backend.management_rinse_hd.table_exists", return_value=True):
        ids = _load_hd_discovery_bag_ids(cur, ORG)
    assert ids == {"HD1"}


def test_hd_persistence_when_absent_from_day_hints():
    """HD discovered D1, incomplete, absent D2 shift hints — still HD workload."""
    from backend.management_rinse_hd import (
        WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED,
    )

    cur = MagicMock()
    prod = {
        "HDP1": {
            "bag_id": "HDP1",
            "workflow_status": STATUS_PENDING_WASH,
            "operations_date_et": D1,
            "version": 1,
            "admitted_at": datetime(2026, 8, 31, 8, 0),
        }
    }
    with (
        patch("backend.management_rinse_hd.table_exists", return_value=True),
        patch("backend.management_rinse_hd.ensure_management_hd_columns"),
        patch(
            "backend.hd_workflow_extensions.hd_workflow_cutoff",
            return_value=(date(2026, 8, 21), None),
        ),
        patch("backend.management_rinse_hd._load_hd_service_hints", return_value={}),
        patch(
            "backend.management_rinse_hd._load_hd_discovery_bag_ids",
            return_value=set(),
        ),
        patch(
            "backend.management_rinse_hd.admit_discovered_hd_bags",
            return_value={"admitted_new": 0, "already_admitted": 0, "bag_ids": []},
        ),
        patch(
            "backend.management_rinse_hd._load_active_admitted_bag_ids",
            return_value={"HDP1"},
        ),
        patch("backend.management_rinse_hd._load_candidate_events_for_bags", return_value=[]),
        patch("backend.management_rinse_hd._load_production_by_bag", return_value=prod),
        patch("backend.management_rinse_hd._load_user_maps", return_value={}),
        patch("backend.management_rinse_hd._load_hd_presence_meta", return_value={}),
        patch(
            "backend.management_rinse_hd_review.compute_canonical_hd_missing_membership",
            return_value={},
        ),
        patch(
            "backend.management_rinse_hd_review.enrich_hd_order_with_review",
            side_effect=lambda o, _m: o,
        ),
        patch(
            "backend.management_rinse_hd_review.load_hd_latest_source_portal_context",
            return_value={},
        ),
    ):
        day = build_rinse_hd_day(cur, ORG, D2, status="all")
    bag_ids = {o["bag_id"] for o in day["orders"]}
    assert "HDP1" in bag_ids


def test_wf_review_from_cycle_not_discovery_absence():
    wl = _run_wf(
        date_et=D2,
        open_rows=[_oi_row("REV1")],
        review_bags={"REV1"},
    )
    assert "REV1" in wl["review"]
    assert wl["missing_from_portal"] == frozenset()
