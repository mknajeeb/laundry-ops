"""Specialty drawer opens the qualifying order instance, not a bag-id guess."""

from datetime import date, datetime
from unittest.mock import MagicMock

from backend.management_rinse_wf_review import (
    _build_review_action_by_order_instance,
    match_specialty_order_instance,
)

DAY = date(2026, 9, 19)
OLD_ANCHOR = datetime(2026, 9, 18, 8, 0)
NEW_ANCHOR = datetime(2026, 9, 19, 9, 0)


def test_match_uses_the_evidence_cycle_not_a_newer_open_order():
    rows = [
        {"order_instance_id": 10, "cycle_anchor_at": OLD_ANCHOR},
        {"order_instance_id": 99, "cycle_anchor_at": NEW_ANCHOR},
    ]
    assert match_specialty_order_instance(rows, OLD_ANCHOR) == 10
    assert match_specialty_order_instance(rows, NEW_ANCHOR) == 99
    assert match_specialty_order_instance(rows, datetime(2026, 9, 17, 1, 0)) is None
    assert (
        match_specialty_order_instance(
            [
                {"order_instance_id": 1, "cycle_anchor_at": OLD_ANCHOR},
                {"order_instance_id": 2, "cycle_anchor_at": OLD_ANCHOR},
            ],
            OLD_ANCHOR,
        )
        is None
    )


def _oi(oid, anchor, *, completed_at, org=3, bag="REUSE1"):
    return {
        "order_instance_id": oid,
        "organization_id": org,
        "bag_id": bag,
        "service_type": "WF",
        "cycle_anchor_at": anchor,
        "completed_at": completed_at,
        "completed_by_employee_name": "Folder",
        "source_cycle_id": None,
    }


def _patch_action(monkeypatch, rows, qualifier):
    monkeypatch.setattr(
        "backend.rinse_order_instances.get_order_instance_by_id",
        lambda _cursor, oid: rows.get(int(oid)),
    )
    monkeypatch.setattr(
        "backend.management_rinse_wf_review.load_specialty_qualifying_order_instances",
        lambda *_a, **_k: qualifier,
    )
    seen = {}

    def _weights(*_a, **kwargs):
        seen["anchor"] = kwargs.get("cycle_anchor_override")
        return {
            "pre_weight_lbs": 12.5,
            "post_weight_lbs": 9.0,
            "post_weight_value": 9.0,
        }

    monkeypatch.setattr(
        "backend.rinse_current_cycle_weight.resolve_bag_weight_info_canonical",
        _weights,
    )
    monkeypatch.setattr(
        "backend.rinse_bulk_workitems.load_bulk_workitem_scan_map",
        lambda *_a, **_k: {
            "REUSE1": {"count": 1, "first_at": OLD_ANCHOR, "cycle_anchor_at": OLD_ANCHOR}
        },
    )
    monkeypatch.setattr(
        "backend.rinse_bulk_workitems.load_bag_bulk_lines",
        lambda *_a, **_k: {},
    )
    monkeypatch.setattr(
        "backend.rinse_bulk_workitems.load_bulk_resolutions",
        lambda *_a, **_k: {},
    )
    monkeypatch.setattr(
        "backend.rinse_bulk_workitems.list_workitems",
        lambda *_a, **_k: [{"id": 1, "name": "Comforter"}],
    )
    monkeypatch.setattr(
        "backend.management_rinse_wf_review.resolve_customer_names_for_bags",
        lambda *_a, **_k: [{"bag_id": "REUSE1", "customer_name": "Customer A"}],
    )
    monkeypatch.setattr(
        "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("day bag lookup")),
    )
    return seen


def test_completed_specialty_oi_opens_without_a_day_bag(monkeypatch):
    rows = {10: _oi(10, OLD_ANCHOR, completed_at=datetime(2026, 9, 18, 15, 0))}
    seen = _patch_action(monkeypatch, rows, {"REUSE1": 10})
    out = _build_review_action_by_order_instance(MagicMock(), 3, DAY, "REUSE1", 10)
    assert out["ok"] is True
    assert out["bag"]["order_instance_id"] == 10
    assert out["bag"]["customer_name"] == "Customer A"
    assert out["bag"]["pre_weight_lbs"] == 12.5
    assert out["bag"]["post_weight_lbs"] == 9.0
    assert out["_meta"]["source"] == "order_instance_primary_key"
    assert out["_meta"]["day_bag_present"] is False
    assert seen["anchor"] == OLD_ANCHOR
    assert out["bag"]["order_display_id"]


def test_reused_bag_rejects_the_newer_open_order(monkeypatch):
    rows = {
        10: _oi(10, OLD_ANCHOR, completed_at=datetime(2026, 9, 18, 15, 0)),
        99: _oi(99, NEW_ANCHOR, completed_at=None),
    }
    _patch_action(monkeypatch, rows, {"REUSE1": 10})
    opened = _build_review_action_by_order_instance(MagicMock(), 3, DAY, "REUSE1", 10)
    rejected = _build_review_action_by_order_instance(MagicMock(), 3, DAY, "REUSE1", 99)
    wrong_org = _build_review_action_by_order_instance(MagicMock(), 9, DAY, "REUSE1", 10)
    wrong_bag = _build_review_action_by_order_instance(MagicMock(), 3, DAY, "OTHER", 10)
    assert opened["ok"] is True
    assert opened["bag"]["order_instance_id"] == 10
    assert rejected == {"ok": False, "error": "order_instance_invalid", "bag_id": "REUSE1"}
    assert wrong_org["ok"] is False
    assert wrong_bag["ok"] is False
