"""Specialty drawer opens the qualifying order instance, not a bag-id guess."""

from datetime import date, datetime
from unittest.mock import MagicMock

from backend.management_rinse_wf_review import (
    _build_review_action_by_order_instance,
    match_specialty_order_instance,
    match_specialty_order_instance_window,
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


def test_reused_bag_window_follows_the_new_order_boundary_not_the_next_anchor():
    """A later order owns only scans after the admission boundary that opened it."""
    bag = "REUSE1"
    completed = datetime(2026, 9, 12, 8, 0)
    later = datetime(2026, 9, 18, 9, 0)
    boundary = datetime(2026, 9, 18, 6, 0)
    rows = [
        {
            "order_instance_id": 41,
            "bag_id": bag,
            "cycle_anchor_at": completed,
            "service_type": "WF",
        },
        {
            "order_instance_id": 88,
            "bag_id": bag,
            "cycle_anchor_at": later,
            "service_type": "WF",
        },
    ]
    evidence = datetime(2026, 9, 12, 11, 30)
    assert match_specialty_order_instance_window(rows, [evidence], [boundary]) == 41
    assert (
        match_specialty_order_instance_window(
            rows, [datetime(2026, 9, 18, 10, 0)], [boundary]
        )
        == 88
    )
    assert match_specialty_order_instance_window(rows, [datetime(2026, 9, 1, 1, 0)], [boundary]) is None
    assert (
        match_specialty_order_instance_window(
            [
                {"order_instance_id": 1, "cycle_anchor_at": completed, "service_type": "WF"},
                {"order_instance_id": 2, "cycle_anchor_at": completed, "service_type": "WF"},
            ],
            [evidence],
            [boundary],
        )
        is None
    )
    assert (
        match_specialty_order_instance_window(
            rows, [evidence, datetime(2026, 9, 18, 12, 0)], [boundary]
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
        "backend.management_rinse_wf_review.load_post_epoch_specialty_evidence",
        lambda *_a, **_k: {
            "REUSE1": {
                "count": 1,
                "first_at": OLD_ANCHOR,
                "cycle_anchor_at": OLD_ANCHOR,
                "order_instance_id": 10,
                "events": [],
            }
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


ZIPVAN = datetime(2026, 9, 18, 4, 36)
PLANT_STV = datetime(2026, 9, 18, 7, 3)
BULK = datetime(2026, 9, 18, 7, 18)
LATER_BOUNDARY = datetime(2026, 9, 18, 15, 0)
LATER_OI = datetime(2026, 9, 18, 16, 0)
LATER_BULK = datetime(2026, 9, 18, 16, 30)


def _wf(oid, anchor, *, service="WF"):
    return {
        "order_instance_id": oid,
        "cycle_anchor_at": anchor,
        "service_type": service,
    }


def test_plant_stv_without_new_order_boundary_resolves_to_existing_oi():
    """Zipvan STV, plant STV, bulk, completion — plant STV is not a new order."""
    from backend.rinse_order_instances import _NEW_ORDER_BOUNDARY_PURPOSES

    assert "sent-to-vendor" not in _NEW_ORDER_BOUNDARY_PURPOSES
    rows = [_wf(6187, ZIPVAN)]
    assert match_specialty_order_instance_window(rows, [BULK], []) == 6187
    assert match_specialty_order_instance_window(rows, [PLANT_STV, BULK], []) == 6187


def test_boundary_before_later_bulk_resolves_to_the_later_oi():
    rows = [_wf(6187, ZIPVAN), _wf(7001, LATER_OI)]
    assert (
        match_specialty_order_instance_window(rows, [LATER_BULK], [LATER_BOUNDARY])
        == 7001
    )
    assert (
        match_specialty_order_instance_window(rows, [BULK], [LATER_BOUNDARY]) == 6187
    )
    assert (
        match_specialty_order_instance_window(rows, [LATER_BULK], [LATER_BOUNDARY])
        != 6187
    )


def test_bulk_after_boundary_without_a_later_oi_fails_closed():
    rows = [_wf(6187, ZIPVAN)]
    assert (
        match_specialty_order_instance_window(rows, [LATER_BULK], [LATER_BOUNDARY])
        is None
    )


def test_ambiguous_lifecycle_ownership_fails_closed():
    rows = [_wf(6187, ZIPVAN), _wf(7001, LATER_OI)]
    assert match_specialty_order_instance_window(rows, [LATER_BULK], []) is None
    assert (
        match_specialty_order_instance_window(
            [_wf(1, ZIPVAN), _wf(2, ZIPVAN)],
            [BULK],
            [],
        )
        is None
    )


def test_hd_order_does_not_own_specialty_bulk():
    hd = [_wf(9, ZIPVAN, service="HD")]
    assert match_specialty_order_instance_window(hd, [BULK], []) is None
    mixed = [_wf(9, ZIPVAN, service="HD"), _wf(6187, ZIPVAN)]
    assert match_specialty_order_instance_window(mixed, [BULK], []) == 6187


def test_lifecycle_projection_is_deterministic():
    rows = [_wf(6187, ZIPVAN), _wf(7001, LATER_OI)]
    first = match_specialty_order_instance_window(rows, [BULK, BULK], [LATER_BOUNDARY])
    second = match_specialty_order_instance_window(
        list(reversed(rows)), [BULK, BULK], [LATER_BOUNDARY]
    )
    assert first == second == 6187


def test_pre_epoch_bulk_is_excluded_and_boundary_load_is_set_based(monkeypatch):
    epoch = datetime(2026, 9, 17, 22, 43, 16)
    monkeypatch.setattr(
        "backend.wf_ops_reset_epoch.get_wf_reset_epoch_at",
        lambda *_a, **_k: epoch,
    )
    monkeypatch.setattr(
        "backend.wf_ops_reset_epoch.epoch_scan_wall",
        lambda *_a, **_k: epoch,
    )
    monkeypatch.setattr("backend.ta_helpers.table_exists", lambda *_a, **_k: True)
    monkeypatch.setattr(
        "backend.rinse_order_instances.table_exists", lambda *_a, **_k: True
    )
    bound_calls = []

    def _bounds(_cursor, _org, bag_ids):
        bound_calls.append(list(bag_ids))
        return {bid: [] for bid in bag_ids}

    monkeypatch.setattr(
        "backend.rinse_order_instances.load_new_order_boundary_timestamps_for_bags",
        _bounds,
    )

    class Cur:
        def __init__(self):
            self.n = 0
            self._rows = []

        def execute(self, sql, _params=None):
            self.n += 1
            text = " ".join(str(sql).split())
            if "rinse_order_instances" in text:
                self._rows = [
                    {
                        "order_instance_id": 6187,
                        "bag_id": "KEEP1",
                        "cycle_anchor_at": ZIPVAN,
                        "service_type": "WF",
                    },
                    {
                        "order_instance_id": 9,
                        "bag_id": "HDAG1",
                        "cycle_anchor_at": ZIPVAN,
                        "service_type": "HD",
                    },
                ]
            else:
                self._rows = [
                    {
                        "id": 1,
                        "bag_id": "OLD1",
                        "purpose": "create-workitem-bulk",
                        "scanned_at_parsed": datetime(2026, 9, 17, 10, 0),
                        "user_name": "Pre",
                    },
                    {
                        "id": 2,
                        "bag_id": "KEEP1",
                        "purpose": "create-workitem-bulk",
                        "scanned_at_parsed": BULK,
                        "user_name": "Francis (Veewash)",
                    },
                    {
                        "id": 3,
                        "bag_id": "HDAG1",
                        "purpose": "create-workitem-bulk",
                        "scanned_at_parsed": BULK,
                        "user_name": "HD",
                    },
                ]

        def fetchall(self):
            return list(self._rows)

    from backend.management_rinse_wf_review import load_post_epoch_specialty_evidence

    cur = Cur()
    out = load_post_epoch_specialty_evidence(cur, 3, ["OLD1", "KEEP1", "HDAG1"])
    again = load_post_epoch_specialty_evidence(cur, 3, ["OLD1", "KEEP1", "HDAG1"])
    assert "OLD1" not in out
    assert out["KEEP1"]["order_instance_id"] == 6187
    assert out["HDAG1"]["order_instance_id"] is None
    assert out == again
    assert len(bound_calls) == 2
    assert bound_calls[0] == bound_calls[1]
    assert set(bound_calls[0]) == {"KEEP1", "HDAG1"}
    assert cur.n == 4
