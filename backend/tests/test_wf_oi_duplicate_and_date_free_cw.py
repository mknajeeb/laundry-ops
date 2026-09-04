"""Regressions: date-free CW evidence + same-lifecycle OI identity."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_order_instances import (
    ensure_open_order_instance_for_new_active_cycle,
    heal_same_lifecycle_portal_orphan_ois,
    upsert_order_instance_from_cycle,
)
from backend.rinse_wf_canonical_workload import get_canonical_wf_workload
from backend.rinse_wf_current_workload import (
    REVIEW_REGISTRY_STALE_COMPLETED,
    get_current_wf_workload,
    registry_stale_completion_review_bags,
)
from backend.rinse_wf_service_cycle import (
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    sync_portal_discovery,
)

ORG = 3
SEP2 = date(2026, 9, 2)
SEP3 = date(2026, 9, 3)


def _norm_cw(wl: dict) -> dict:
    items = sorted(
        wl.get("items") or [],
        key=lambda x: (int(x.get("order_instance_id") or 0), x.get("bag_id") or ""),
    )
    return {
        "open_oi_ids": [int(i["order_instance_id"]) for i in items if i.get("order_instance_id")],
        "pending_oi_ids": [
            int(i["order_instance_id"])
            for i in items
            if i.get("status") == "pending" and i.get("order_instance_id")
        ],
        "review_oi_ids": [
            int(i["order_instance_id"])
            for i in items
            if i.get("status") == "review_required" and i.get("order_instance_id")
        ],
        "review_reason_codes": {
            int(i["order_instance_id"]): list(i.get("review_reason_codes") or [])
            for i in items
            if i.get("status") == "review_required"
        },
        "open_bags": sorted(wl.get("open") or []),
        "pending_bags": sorted(wl.get("pending") or []),
        "review_bags": sorted(wl.get("review") or []),
        "counts": dict(wl.get("counts") or {}),
    }


def test_a_current_workload_date_independent_normalized():
    open_rows = [
        {
            "order_instance_id": 10,
            "bag_id": "OPENA",
            "cycle_anchor_at": datetime(2026, 9, 1, 8, 0),
            "completed_at": None,
        },
        {
            "order_instance_id": 11,
            "bag_id": "REVX",
            "cycle_anchor_at": datetime(2026, 9, 1, 9, 0),
            "completed_at": None,
        },
    ]
    cur = MagicMock()
    with (
        patch(
            "backend.rinse_order_instances.list_open_wf_order_instances",
            return_value=open_rows,
        ),
        patch(
            "backend.rinse_wf_canonical_workload._authoritative_hd_bag_ids",
            return_value=set(),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._review_wf_bag_ids_from_cycles",
            return_value=set(),
        ),
        patch(
            "backend.rinse_wf_current_workload.registry_stale_completion_review_bags",
            return_value={"REVX"},
        ),
        patch(
            "backend.rinse_wf_current_workload.lifecycle_received_from_vendor_at",
            return_value=None,
        ),
        patch(
            "backend.rinse_order_instances.list_order_instances_completed_on_date",
            side_effect=lambda *a, **k: (
                [
                    {
                        "order_instance_id": 99,
                        "bag_id": "COMPD",
                        "completed_at": datetime(2026, 9, 2, 12),
                    }
                ]
                if (a[2] if len(a) > 2 else k.get("date_et")) == SEP2
                else [
                    {
                        "order_instance_id": 100,
                        "bag_id": "COMPE",
                        "completed_at": datetime(2026, 9, 3, 12),
                    }
                ]
            ),
        ),
    ):
        wl2 = get_canonical_wf_workload(cur, ORG, SEP2)
        wl3 = get_canonical_wf_workload(cur, ORG, SEP3)
    n2 = _norm_cw(wl2["current_workload"])
    n3 = _norm_cw(wl3["current_workload"])
    assert n2 == n3
    assert wl2["completed"] != wl3["completed"]


def test_b_portal_presence_does_not_fork_when_active_exists():
    cur = MagicMock()
    now = datetime(2026, 9, 3, 3, 17, 16)
    active_anchor = datetime(2026, 9, 3, 0, 13)
    active = {
        "bag_id": "7CPSUFHKUG",
        "cycle_anchor_at": active_anchor,
        "status": STATUS_ACTIVE,
        "admitted_source": "SCAN_EVIDENCE_REFRESH",
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
            ORG,
            {"7CPSUFHKUG": {"service_type": "WF"}},
            now=now,
            evidence_refreshed_bag_ids={"7CPSUFHKUG"},
        )
    touch.assert_called_once()
    admit.assert_not_called()
    assert out["admitted"] == 0
    assert out["metadata_only"] == 1


def test_c_reusable_bag_still_creates_oi_after_completed_with_boundary():
    prior = {
        "order_instance_id": 1,
        "bag_id": "REUSE1",
        "service_type": "WF",
        "cycle_anchor_at": datetime(2026, 8, 20, 1, 0),
        "completed_at": datetime(2026, 8, 20, 15, 0),
    }
    active = {
        "id": 100,
        "bag_id": "REUSE1",
        "service_type": "WF",
        "status": "ACTIVE",
        "cycle_anchor_at": datetime(2026, 8, 30, 22, 0),
        "completed_at": None,
    }
    created = {**active, "order_instance_id": 55, "completed_at": None}
    cur = MagicMock()
    with patch(
        "backend.rinse_order_instances.get_order_instance_by_cycle_key",
        return_value=None,
    ), patch(
        "backend.rinse_order_instances.get_latest_order_instance_for_bag",
        return_value=prior,
    ), patch(
        "backend.rinse_order_instances.has_authoritative_new_order_boundary_after",
        return_value=True,
    ), patch(
        "backend.rinse_order_instances.upsert_order_instance_from_cycle",
        return_value=created,
    ) as upsert:
        out = ensure_open_order_instance_for_new_active_cycle(cur, ORG, active)
    assert out is created
    upsert.assert_called_once()


def test_d_completion_stamps_cycle_owning_oi_not_max_id():
    """Completing STV cycle rebinds/stamps portal orphan — does not insert MAX id."""
    portal_oi = {
        "order_instance_id": 4034,
        "organization_id": ORG,
        "bag_id": "7CPSUFHKUG",
        "service_type": "WF",
        "cycle_anchor_at": datetime(2026, 9, 3, 3, 17, 16),
        "completed_at": None,
        "source_cycle_id": 2263346,
    }
    stv_cycle = {
        "id": 2267171,
        "bag_id": "7CPSUFHKUG",
        "service_type": "WF",
        "status": "COMPLETED",
        "cycle_anchor_at": datetime(2026, 9, 3, 0, 13),
        "completed_at": datetime(2026, 9, 3, 13, 13),
        "completion_source": "post_garments_reviewed_weight_entry",
    }
    cur = MagicMock()
    stamped = {
        **portal_oi,
        "cycle_anchor_at": stv_cycle["cycle_anchor_at"],
        "completed_at": stv_cycle["completed_at"],
        "order_instance_id": 4034,
    }
    with patch(
        "backend.rinse_order_instances.ensure_rinse_order_instances_table",
    ), patch(
        "backend.rinse_order_instances.get_order_instance_by_source_cycle_id",
        return_value=None,
    ), patch(
        "backend.rinse_order_instances.get_order_instance_by_cycle_key",
        return_value=None,
    ), patch(
        "backend.rinse_order_instances.list_order_instances_for_bag",
        return_value=[portal_oi],
    ), patch(
        "backend.rinse_order_instances._maybe_rebind_open_portal_oi_to_stv_cycle",
        return_value={**portal_oi, "cycle_anchor_at": stv_cycle["cycle_anchor_at"]},
    ), patch(
        "backend.rinse_order_instances.get_order_instance_by_id",
        return_value=stamped,
    ):
        out = upsert_order_instance_from_cycle(cur, ORG, stv_cycle)
    assert out["order_instance_id"] == 4034
    assert out["completed_at"] == stv_cycle["completed_at"]
    # No INSERT into order_instances
    insert_sqls = [
        c.args[0]
        for c in cur.execute.call_args_list
        if c.args and "INSERT INTO rinse_order_instances" in str(c.args[0])
    ]
    assert insert_sqls == []


def test_e_genuine_stale_registry_still_review():
    open_oi = {
        "order_instance_id": 3585,
        "bag_id": "BUEKCP33J1",
        "cycle_anchor_at": datetime(2026, 9, 1, 18, 54, 58),
        "completed_at": None,
    }
    cur = MagicMock()
    with patch(
        "backend.rinse_wf_current_workload._registry_completed_open_bags",
        return_value={"BUEKCP33J1"},
    ), patch(
        "backend.rinse_wf_current_workload._oi_has_valid_lifecycle_completion",
        return_value=False,
    ):
        conflict = registry_stale_completion_review_bags(
            cur,
            ORG,
            ["BUEKCP33J1"],
            open_oi_rows=[open_oi],
            as_of_date_et=SEP2,
        )
    assert conflict == {"BUEKCP33J1"}


def test_heal_deletes_only_proven_portal_orphans():
    cur = MagicMock()
    report = {
        "dry_run": False,
        "candidates": [],
        "healed": [{"bag_id": "7CPSUFHKUG", "orphan_oi": 4034}],
        "ambiguous": [],
        "skipped_genuine_review": [],
    }
    with patch(
        "backend.rinse_order_instances.heal_same_lifecycle_portal_orphan_ois",
        return_value=report,
    ) as heal:
        out = heal(cur, ORG, dry_run=False)
    assert out["healed"][0]["orphan_oi"] == 4034
