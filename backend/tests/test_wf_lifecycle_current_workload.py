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


def test_registry_stale_completion_review_helper_same_lifecycle_contradiction_only():
    """Historical registry ignored; Review only when same-lifecycle claim lacks evidence."""
    from backend.rinse_wf_current_workload import registry_stale_completion_review_bags

    cur = MagicMock()
    open_rows = [
        {
            "bag_id": "HIST",
            "order_instance_id": 1,
            "cycle_anchor_at": datetime(2026, 9, 1, 18, 0),
        },
        {
            "bag_id": "EVID",
            "order_instance_id": 2,
            "cycle_anchor_at": datetime(2026, 9, 1, 8, 0),
        },
        {
            "bag_id": "CONTRA",
            "order_instance_id": 3,
            "cycle_anchor_at": datetime(2026, 9, 1, 9, 0),
        },
    ]

    def _reg(_c, _o, bid):
        if bid == "HIST":
            return {
                "completion_status": "COMPLETED",
                "completed_at": datetime(2026, 9, 1, 15, 0),  # before OI
            }
        if bid == "EVID":
            return {
                "completion_status": "COMPLETED",
                "completed_at": datetime(2026, 9, 1, 12, 0),
            }
        if bid == "CONTRA":
            return {
                "completion_status": "COMPLETED",
                "completed_at": datetime(2026, 9, 1, 12, 0),
            }
        return None

    def _evidence(_c, _o, *, bag_id, cycle_anchor_at, lifecycle_end_exclusive=None, timeline=None):
        if bag_id == "EVID":
            return {
                "completed": True,
                "completion_at": datetime(2026, 9, 1, 12, 0),
                "completion_kind": "clean-rack",
                "via_clean_rack": True,
                "evidence_family": "v2",
            }
        return None

    with (
        patch(
            "backend.rinse_wf_current_workload._registry_row_for_bag",
            side_effect=_reg,
        ),
        patch(
            "backend.rinse_wf_current_workload._next_oi_cycle_anchor",
            return_value=None,
        ),
        patch(
            "backend.rinse_wf_current_workload.evaluate_oi_lifecycle_completion_evidence",
            side_effect=_evidence,
        ),
    ):
        out = registry_stale_completion_review_bags(
            cur, ORG, ["HIST", "EVID", "CONTRA"], open_oi_rows=open_rows
        )
    assert out == {"CONTRA"}


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


# --- A–F CW completion invariant regressions ---


def test_a_double_stv_clean_rack_same_oi_lifecycle():
    """STV A → STV B → production → Clean Rack completes same OI window."""
    from backend.rinse_wf_current_workload import evaluate_oi_lifecycle_completion_evidence

    anchor = datetime(2026, 9, 4, 4, 38)
    timeline = [
        {"purpose": "sent-to-vendor", "scanned_at_parsed": anchor, "rack": "Rinse Zipvan"},
        {
            "purpose": "sent-to-vendor",
            "scanned_at_parsed": datetime(2026, 9, 4, 6, 32),
            "rack": "VeeWash Dirty",
        },
        {"purpose": "weight-entry", "scanned_at_parsed": datetime(2026, 9, 4, 11, 16)},
        {"purpose": "garments-reviewed", "scanned_at_parsed": datetime(2026, 9, 4, 14, 22)},
        {
            "purpose": "move-bag Last Scan",
            "scanned_at_parsed": datetime(2026, 9, 4, 14, 24),
            "rack": "VeeWash Clean",
        },
    ]
    cur = MagicMock()
    ev = evaluate_oi_lifecycle_completion_evidence(
        cur,
        ORG,
        bag_id="005649CRSL",
        cycle_anchor_at=anchor,
        lifecycle_end_exclusive=None,
        timeline=timeline,
    )
    assert ev is not None
    assert ev["via_clean_rack"] is True
    assert ev["completion_at"] == datetime(2026, 9, 4, 14, 24)


def test_b_historical_registry_not_review():
    from backend.rinse_wf_current_workload import registry_stale_completion_review_bags

    cur = MagicMock()
    open_oi = {
        "bag_id": "BUEKCP33J1",
        "order_instance_id": 3585,
        "cycle_anchor_at": datetime(2026, 9, 1, 18, 54, 58),
    }
    with (
        patch(
            "backend.rinse_wf_current_workload._registry_row_for_bag",
            return_value={
                "completion_status": "COMPLETED",
                "completed_at": datetime(2026, 9, 1, 15, 34),
            },
        ),
        patch(
            "backend.rinse_wf_current_workload._next_oi_cycle_anchor",
            return_value=None,
        ),
        patch(
            "backend.rinse_wf_current_workload.evaluate_oi_lifecycle_completion_evidence",
            return_value=None,
        ),
    ):
        out = registry_stale_completion_review_bags(
            cur, ORG, ["BUEKCP33J1"], open_oi_rows=[open_oi]
        )
    assert out == set()


def test_c_same_lifecycle_clean_rack_stamps_oi():
    from backend.rinse_order_instances import stamp_open_oi_from_lifecycle_completion_evidence

    oi = {
        "order_instance_id": 4204,
        "bag_id": "005649CRSL",
        "cycle_anchor_at": datetime(2026, 9, 4, 4, 38),
        "completed_at": None,
        "source_cycle_id": 99,
    }
    evidence = {
        "completed": True,
        "completion_at": datetime(2026, 9, 4, 14, 24),
        "completion_kind": "clean-rack",
        "completion_user": "Folder",
        "via_clean_rack": True,
        "evidence_family": "v2",
    }
    cur = MagicMock()
    with (
        patch(
            "backend.rinse_wf_current_workload._next_oi_cycle_anchor",
            return_value=None,
        ),
        patch(
            "backend.rinse_wf_service_cycle.get_cycle_by_key",
            return_value={"id": 99, "admitted_source": "SCAN_EVIDENCE_REFRESH"},
        ),
        patch(
            "backend.rinse_wf_service_cycle.upsert_service_cycle",
            return_value={
                "id": 99,
                "status": "COMPLETED",
                "cycle_anchor_at": oi["cycle_anchor_at"],
                "completed_at": evidence["completion_at"],
            },
        ) as upsert_cyc,
        patch(
            "backend.rinse_order_instances.upsert_order_instance_from_cycle",
            return_value={"order_instance_id": 4204, "completed_at": evidence["completion_at"]},
        ) as upsert_oi,
    ):
        out = stamp_open_oi_from_lifecycle_completion_evidence(
            cur, ORG, oi, evidence=evidence, dry_run=False
        )
    assert out["ok"] is True
    assert out["action"] == "stamp_oi_completed"
    assert out["stamped_oi"] == 4204
    assert upsert_cyc.called
    assert upsert_oi.called


def test_d_same_lifecycle_strong_qc_not_false_review():
    from backend.rinse_wf_current_workload import (
        evaluate_oi_lifecycle_completion_evidence,
        registry_stale_completion_review_bags,
    )

    anchor = datetime(2026, 9, 3, 23, 27)
    timeline = [
        {"purpose": "quality-control-completed", "scanned_at_parsed": anchor},
        {"purpose": "processed-by-vendor", "scanned_at_parsed": anchor},
        {"purpose": "received-from-vendor", "scanned_at_parsed": anchor},
        {"purpose": "sent-to-vendor", "scanned_at_parsed": anchor},
    ]
    cur = MagicMock()
    ev = evaluate_oi_lifecycle_completion_evidence(
        cur,
        ORG,
        bag_id="0FEVKTTNJO",
        cycle_anchor_at=anchor,
        timeline=timeline,
    )
    assert ev is not None
    assert ev["completion_kind"] == "quality-control-completed"

    open_oi = {
        "bag_id": "0FEVKTTNJO",
        "order_instance_id": 4187,
        "cycle_anchor_at": anchor,
    }
    with (
        patch(
            "backend.rinse_wf_current_workload._registry_row_for_bag",
            return_value={
                "completion_status": "COMPLETED",
                "completed_at": anchor,
            },
        ),
        patch(
            "backend.rinse_wf_current_workload._next_oi_cycle_anchor",
            return_value=None,
        ),
        patch(
            "backend.rinse_wf_current_workload.evaluate_oi_lifecycle_completion_evidence",
            return_value=ev,
        ),
    ):
        assert (
            registry_stale_completion_review_bags(
                cur, ORG, ["0FEVKTTNJO"], open_oi_rows=[open_oi]
            )
            == set()
        )


def test_e_reusable_bag_lifecycle_a_does_not_affect_b():
    from backend.rinse_wf_current_workload import (
        evaluate_oi_lifecycle_completion_evidence,
        registry_stale_completion_review_bags,
    )

    # Lifecycle A completed; lifecycle B open later — historical registry ignored.
    a_anchor = datetime(2026, 8, 20, 8, 0)
    a_done = datetime(2026, 8, 20, 14, 0)
    b_anchor = datetime(2026, 9, 1, 9, 0)
    timeline = [
        {"purpose": "sent-to-vendor", "scanned_at_parsed": a_anchor},
        {
            "purpose": "move-bag Last Scan",
            "scanned_at_parsed": a_done,
            "rack": "VeeWash Clean",
        },
        {"purpose": "sent-to-vendor", "scanned_at_parsed": b_anchor},
        {"purpose": "weight-entry", "scanned_at_parsed": datetime(2026, 9, 1, 10, 0)},
    ]
    cur = MagicMock()
    # Evidence for B only looks inside B window — no clean rack yet.
    ev_b = evaluate_oi_lifecycle_completion_evidence(
        cur,
        ORG,
        bag_id="REUS",
        cycle_anchor_at=b_anchor,
        lifecycle_end_exclusive=None,
        timeline=timeline,
    )
    assert ev_b is None

    open_b = {
        "bag_id": "REUS",
        "order_instance_id": 2,
        "cycle_anchor_at": b_anchor,
    }
    with (
        patch(
            "backend.rinse_wf_current_workload._registry_row_for_bag",
            return_value={
                "completion_status": "COMPLETED",
                "completed_at": a_done,  # sticky from lifecycle A
            },
        ),
        patch(
            "backend.rinse_wf_current_workload._next_oi_cycle_anchor",
            return_value=None,
        ),
        patch(
            "backend.rinse_wf_current_workload.evaluate_oi_lifecycle_completion_evidence",
            return_value=None,
        ),
    ):
        assert (
            registry_stale_completion_review_bags(
                cur, ORG, ["REUS"], open_oi_rows=[open_b]
            )
            == set()
        )


def test_f_true_same_lifecycle_ambiguity_remains_review():
    from backend.rinse_wf_current_workload import registry_stale_completion_review_bags

    cur = MagicMock()
    open_oi = {
        "bag_id": "AMBIG",
        "order_instance_id": 9,
        "cycle_anchor_at": datetime(2026, 9, 4, 8, 0),
    }
    with (
        patch(
            "backend.rinse_wf_current_workload._registry_row_for_bag",
            return_value={
                "completion_status": "COMPLETED",
                "completed_at": datetime(2026, 9, 4, 12, 0),  # inside OI window
            },
        ),
        patch(
            "backend.rinse_wf_current_workload._next_oi_cycle_anchor",
            return_value=None,
        ),
        patch(
            "backend.rinse_wf_current_workload.evaluate_oi_lifecycle_completion_evidence",
            return_value=None,  # no canonical/v2 evidence
        ),
    ):
        out = registry_stale_completion_review_bags(
            cur, ORG, ["AMBIG"], open_oi_rows=[open_oi]
        )
    assert out == {"AMBIG"}
