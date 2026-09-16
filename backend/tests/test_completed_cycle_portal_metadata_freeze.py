"""Bag-scoped portal discovery must not overwrite a completed WF cycle.

Proven race: portal presence lands before the next lifecycle's scans. The
latest known anchor is still the completed cycle. EDD/Rush/portal_last_seen
on that cycle must stay frozen. A later sent-to-vendor still admits a new
lifecycle and may receive the current portal row.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.order_display_id import format_order_display_id
from backend.rinse_wf_service_cycle import (
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    admit_or_update_cycle_from_evidence,
    apply_manager_review_resolution_to_canonical_cycle,
    sync_portal_discovery,
)

ORG = 3
BAG = "BV81JQIRUU"
ANCHOR_A = datetime(2026, 9, 7, 1, 17)
ANCHOR_B = datetime(2026, 9, 16, 0, 12)
SEEN_A = datetime(2026, 9, 7, 12, 26)
NOW_BEFORE_SCANS = datetime(2026, 9, 16, 3, 5, 39)
NOW_AFTER_SCANS = datetime(2026, 9, 16, 3, 8, 2)
PORTAL_B = {
    "service_type": "WF",
    "rush_flag": "NON-RUSH",
    "estimated_delivery_date": date(2026, 9, 16),
}


def _completed_a() -> dict:
    return {
        "id": 2517150,
        "organization_id": ORG,
        "bag_id": BAG,
        "cycle_anchor_at": ANCHOR_A,
        "admitted_at": datetime(2026, 9, 7, 5, 26, 14),
        "admitted_source": "SCAN_EVIDENCE_REFRESH",
        "status": STATUS_COMPLETED,
        "completed_at": datetime(2026, 9, 7, 8, 26),
        "completion_source": "same_minute_post_after_review_sequence",
        "rush_status": "RUSH",
        "estimated_delivery_date": date(2026, 9, 7),
        "pre_weight_lbs": 13.5,
        "post_weight_lbs": None,
        "portal_last_seen_at": SEEN_A,
    }


class _Store:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, datetime], dict] = {}
        self.anchors: list[datetime] = [ANCHOR_A]
        self.upserts: list[dict] = []

    def seed(self, row: dict) -> None:
        self.rows[(row["bag_id"], row["cycle_anchor_at"])] = dict(row)

    def get(self, bag: str, anchor: datetime):
        row = self.rows.get((bag, anchor))
        return dict(row) if row else None

    def active(self, bag: str):
        open_rows = [
            row
            for (bid, _), row in self.rows.items()
            if bid == bag and row.get("status") in ("ACTIVE", "REVIEW")
        ]
        if not open_rows:
            return None
        return dict(max(open_rows, key=lambda r: r["cycle_anchor_at"]))


def _resolution(*_args, **_kwargs):
    return (
        {"effective_status": "pending", "completion_at": None, "completion_source": None},
        {"pre_weight_lbs": 13.5, "post_weight_lbs": None},
    )


def _bind(store: _Store):
    def get_cycle(_cursor, _org, bag, anchor):
        return store.get(bag, anchor)

    def get_active(_cursor, _org, bag):
        return store.active(bag)

    def anchors(_timeline):
        return list(store.anchors)

    def upsert(_cursor, _org, **kwargs):
        store.upserts.append(dict(kwargs))
        key = (kwargs["bag_id"], kwargs["cycle_anchor_at"])
        prev = store.rows.get(key, {})
        row = {
            **prev,
            **kwargs,
            "id": prev.get("id") or (3055965 if kwargs["cycle_anchor_at"] == ANCHOR_B else 2517150),
        }
        store.rows[key] = row
        return dict(row)

    return get_cycle, get_active, anchors, upsert


def _sync(store: _Store, now: datetime, portal: dict | None = None):
    cur = MagicMock()
    cur.rowcount = 0
    get_cycle, get_active, anchors, upsert = _bind(store)
    with patch(
        "backend.rinse_wf_service_cycle.get_cycle_by_key", side_effect=get_cycle
    ), patch(
        "backend.rinse_wf_service_cycle.get_active_cycle_for_bag", side_effect=get_active
    ), patch(
        "backend.rinse_wf_service_cycle._load_timeline", return_value=[{"purpose": "sent-to-vendor"}]
    ), patch(
        "backend.rinse_wf_service_cycle._valid_cycle_anchors", side_effect=anchors
    ), patch(
        "backend.rinse_wf_service_cycle._cycle_resolution", side_effect=_resolution
    ), patch(
        "backend.rinse_wf_service_cycle.upsert_service_cycle", side_effect=upsert
    ), patch(
        "backend.rinse_wf_service_cycle.ensure_wf_service_cycles_table"
    ):
        return sync_portal_discovery(
            cur,
            ORG,
            {BAG: dict(portal or PORTAL_B)},
            now=now,
        )


def test_oi_4544_race_does_not_copy_later_portal_onto_completed_cycle():
    """Portal row for lifecycle B arrives before B's scans. A stays Sep 7 / RUSH."""
    store = _Store()
    store.seed(_completed_a())

    first = _sync(store, NOW_BEFORE_SCANS)
    second = _sync(store, NOW_BEFORE_SCANS)
    held = store.get(BAG, ANCHOR_A)

    assert first["admitted"] == 0
    assert first["updated"] == 0
    assert first["skipped_completed_portal"] == 1
    assert second["skipped_completed_portal"] == 1
    assert store.upserts == []
    assert held["estimated_delivery_date"] == date(2026, 9, 7)
    assert held["rush_status"] == "RUSH"
    assert held["portal_last_seen_at"] == SEEN_A
    assert held["completion_source"] == "same_minute_post_after_review_sequence"
    assert held["post_weight_lbs"] is None
    assert (BAG, ANCHOR_B) not in store.rows


def test_new_boundary_admits_next_lifecycle_without_rewriting_completed():
    store = _Store()
    store.seed(_completed_a())
    _sync(store, NOW_BEFORE_SCANS)
    store.anchors = [ANCHOR_A, ANCHOR_B]

    out = _sync(store, NOW_AFTER_SCANS)
    again = _sync(store, datetime(2026, 9, 16, 4, 21, 6))
    cycle_a = store.get(BAG, ANCHOR_A)
    cycle_b = store.get(BAG, ANCHOR_B)

    assert out["admitted"] == 1
    assert cycle_b is not None
    assert cycle_b["status"] == STATUS_ACTIVE
    assert cycle_b["estimated_delivery_date"] == date(2026, 9, 16)
    assert cycle_b["rush_status"] == "NON-RUSH"
    assert cycle_b["admitted_source"] == "PORTAL_DISCOVERY"
    assert cycle_a["estimated_delivery_date"] == date(2026, 9, 7)
    assert cycle_a["rush_status"] == "RUSH"
    assert cycle_a["portal_last_seen_at"] == SEEN_A
    assert cycle_a["status"] == STATUS_COMPLETED
    assert again["admitted"] == 0
    assert store.get(BAG, ANCHOR_A)["estimated_delivery_date"] == date(2026, 9, 7)
    written_a = [
        row for row in store.upserts if row["cycle_anchor_at"] == ANCHOR_A
    ]
    assert written_a == []


def test_completed_admit_ignores_bag_scoped_portal_even_if_called_directly():
    store = _Store()
    store.seed(_completed_a())
    get_cycle, _active, _anchors, upsert = _bind(store)
    cur = MagicMock()
    with patch(
        "backend.rinse_wf_service_cycle.get_cycle_by_key", side_effect=get_cycle
    ), patch(
        "backend.rinse_wf_service_cycle._cycle_resolution", side_effect=_resolution
    ), patch(
        "backend.rinse_wf_service_cycle.upsert_service_cycle", side_effect=upsert
    ), patch(
        "backend.rinse_wf_service_cycle.ensure_wf_service_cycles_table"
    ):
        admit_or_update_cycle_from_evidence(
            cur,
            ORG,
            BAG,
            ANCHOR_A,
            portal_meta={
                **PORTAL_B,
                "last_seen_at": NOW_BEFORE_SCANS,
            },
        )
    written = store.upserts[-1]
    assert written["estimated_delivery_date"] == date(2026, 9, 7)
    assert written["rush_status"] == "RUSH"
    assert written["portal_last_seen_at"] == SEEN_A
    assert written["completion_source"] == "same_minute_post_after_review_sequence"
    assert written["pre_weight_lbs"] == 13.5
    assert written["post_weight_lbs"] is None
    assert written["status"] == STATUS_COMPLETED


def test_explicit_cycle_scope_can_still_set_completed_metadata():
    store = _Store()
    store.seed(_completed_a())
    get_cycle, _active, _anchors, upsert = _bind(store)
    cur = MagicMock()
    with patch(
        "backend.rinse_wf_service_cycle.get_cycle_by_key", side_effect=get_cycle
    ), patch(
        "backend.rinse_wf_service_cycle._cycle_resolution", side_effect=_resolution
    ), patch(
        "backend.rinse_wf_service_cycle.upsert_service_cycle", side_effect=upsert
    ):
        admit_or_update_cycle_from_evidence(
            cur,
            ORG,
            BAG,
            ANCHOR_A,
            portal_meta={"rush_flag": "NON-RUSH", "estimated_delivery_date": date(2026, 9, 8)},
            portal_metadata_scope="cycle",
        )
    written = store.upserts[-1]
    assert written["estimated_delivery_date"] == date(2026, 9, 8)
    assert written["rush_status"] == "NON-RUSH"


def test_active_cycle_still_receives_current_portal_metadata():
    store = _Store()
    store.seed(_completed_a())
    store.seed(
        {
            **_completed_a(),
            "id": 3055965,
            "cycle_anchor_at": ANCHOR_B,
            "status": STATUS_ACTIVE,
            "completed_at": None,
            "completion_source": None,
            "rush_status": None,
            "estimated_delivery_date": None,
            "portal_last_seen_at": None,
            "admitted_source": "PORTAL_DISCOVERY",
        }
    )
    store.anchors = [ANCHOR_A, ANCHOR_B]
    out = _sync(store, NOW_AFTER_SCANS)
    cycle_b = store.get(BAG, ANCHOR_B)
    cycle_a = store.get(BAG, ANCHOR_A)
    assert out["updated"] == 1
    assert cycle_b["estimated_delivery_date"] == date(2026, 9, 16)
    assert cycle_b["rush_status"] == "NON-RUSH"
    assert cycle_a["estimated_delivery_date"] == date(2026, 9, 7)
    assert cycle_a["rush_status"] == "RUSH"
    assert cycle_a["portal_last_seen_at"] == SEEN_A


def test_manager_resolution_keeps_cycle_owned_edd_and_rush():
    cycle = {
        **_completed_a(),
        "status": STATUS_ACTIVE,
        "completed_at": None,
        "completion_source": None,
    }
    cur = MagicMock()
    with patch(
        "backend.rinse_wf_service_cycle.is_wf_canonical_lifecycle_enabled",
        return_value=True,
    ), patch(
        "backend.rinse_wf_service_cycle.get_active_cycle_for_bag",
        return_value=cycle,
    ), patch(
        "backend.rinse_wf_service_cycle._cycle_resolution",
        return_value=({"effective_status": "completed"}, {"pre_weight_lbs": 13.5, "post_weight_lbs": 13.1}),
    ), patch(
        "backend.rinse_wf_service_cycle.upsert_service_cycle",
        return_value=cycle,
    ) as upsert, patch(
        "backend.rinse_wf_service_cycle.ensure_wf_service_cycles_table"
    ):
        apply_manager_review_resolution_to_canonical_cycle(
            cur,
            ORG,
            BAG,
            completed_at=datetime(2026, 9, 7, 8, 26),
            resolved_by="manager",
        )
    kwargs = upsert.call_args.kwargs
    assert kwargs["estimated_delivery_date"] == date(2026, 9, 7)
    assert kwargs["rush_status"] == "RUSH"
    assert kwargs["completion_source"] == "manager_correct_completion"
    assert kwargs["post_weight_lbs"] == 13.1


def test_display_id_convention_unchanged():
    assert (
        format_order_display_id(BAG, 4544, estimated_delivery_date=date(2026, 9, 7))
        == "BV81JQIRUU-OI-09072026"
    )
    assert (
        format_order_display_id(BAG, 5875, estimated_delivery_date=date(2026, 9, 16))
        == "BV81JQIRUU-OI-09162026"
    )
