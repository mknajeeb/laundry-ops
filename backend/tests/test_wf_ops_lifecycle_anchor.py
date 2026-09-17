"""Baseline cycle anchors after a WF clean reset.

A trusted-baseline bag has no post-epoch sent-to-vendor scan yet. Its anchor must
be the reset epoch (naive ET wall, the same convention as an STV anchor) and not
``now_utc`` — order-instance identity is ``(org, bag_id, service_type,
cycle_anchor_at)``, so a wall-clock anchor would fork a second OI on every scrape.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.wf_ops_reset_epoch import (
    invalidate_wf_reset_epoch_cache,
    set_wf_reset_epoch_at,
)

ORG = 3
BAG = "WFBAG1"
# 2026-09-15 12:00:00 UTC == 2026-09-15 08:00:00 America/New_York (EDT)
EPOCH_UTC = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
EPOCH_ET_WALL = datetime(2026, 9, 15, 8, 0, 0)

STATUS_ACTIVE = "ACTIVE"


class _Cursor:
    """system_settings + rinse_bag_scan_events, MySQL-style parameters."""

    def __init__(self, events: list[dict] | None = None) -> None:
        self.store: dict[tuple[int, str], str] = {}
        self.events = list(events or [])
        self._last: list[dict] = []

    def execute(self, sql, params=None):
        norm = " ".join(str(sql).split()).lower()
        params = tuple(params or ())
        if "from rinse_bag_scan_events" in norm:
            rows = [e for e in self.events if e["bag_id"] == params[1]]
            if len(params) > 2:
                rows = [e for e in rows if e["scanned_at_parsed"] >= params[2]]
            self._last = rows
            return
        if "select svalue from system_settings" in norm:
            val = self.store.get((int(params[0]), params[1]))
            self._last = [{"svalue": val}] if val is not None else []
            return
        if "insert into system_settings" in norm:
            self.store[(int(params[0]), params[1])] = params[2]
            self._last = []
            return
        self._last = []

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return list(self._last)


class _CycleStore:
    """Enough of rinse_wf_service_cycles to observe anchor identity."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, datetime], dict] = {}
        self.admits: list[datetime] = []

    def get_by_key(self, _cursor, _org, bag_id, anchor):
        return self.rows.get((bag_id, anchor))

    def get_active(self, _cursor, _org, bag_id):
        open_rows = [
            r
            for (bag, _a), r in self.rows.items()
            if bag == bag_id and r["status"] == STATUS_ACTIVE
        ]
        if not open_rows:
            return None
        return max(open_rows, key=lambda r: r["cycle_anchor_at"])

    def admit(self, _cursor, org, bag_id, anchor, **kwargs):
        self.admits.append(anchor)
        row = self.rows.setdefault(
            (bag_id, anchor),
            {
                "organization_id": org,
                "bag_id": bag_id,
                "cycle_anchor_at": anchor,
                "status": STATUS_ACTIVE,
                "admitted_source": kwargs.get("admitted_source") or "PORTAL_DISCOVERY",
            },
        )
        return row

    def order_instance_keys(self) -> set[tuple[int, str, str, datetime]]:
        return {
            (r["organization_id"], r["bag_id"], "WF", r["cycle_anchor_at"])
            for r in self.rows.values()
        }


@pytest.fixture()
def cycles(monkeypatch):
    from backend import rinse_wf_service_cycle as module

    store = _CycleStore()
    monkeypatch.setattr("backend.wf_ops_reset_epoch.table_exists", lambda *_: True)
    monkeypatch.setattr(
        "backend.wf_ops_reset_epoch.table_has_column", lambda *_: True
    )
    monkeypatch.setattr(module, "table_exists", lambda *_: True)
    monkeypatch.setattr(module, "ensure_wf_service_cycles_table", lambda _c: None)
    monkeypatch.setattr(module, "get_cycle_by_key", store.get_by_key)
    monkeypatch.setattr(module, "get_active_cycle_for_bag", store.get_active)
    monkeypatch.setattr(module, "admit_or_update_cycle_from_evidence", store.admit)
    monkeypatch.setattr(
        module, "_update_portal_cycle_metadata", lambda *_a, **_k: True
    )
    invalidate_wf_reset_epoch_cache()
    yield module, store
    invalidate_wf_reset_epoch_cache()


def _portal_bags() -> dict[str, dict]:
    return {BAG: {"service_type": "WF", "rush_flag": None, "estimated_delivery_date": None}}


def _stv(ts: datetime) -> dict:
    return {
        "bag_id": BAG,
        "rack": "VeeWash Dirty",
        "purpose": "sent-to-vendor",
        "scanned_at_parsed": ts,
        "user_name": "Driver",
        "scan_index": 1,
        "id": 1,
    }


def test_baseline_bag_anchors_on_the_epoch_not_wall_clock(cycles):
    module, store = cycles
    cur = _Cursor(events=[_stv(datetime(2026, 9, 14, 10, 0))])  # pre-epoch only
    set_wf_reset_epoch_at(cur, ORG, EPOCH_UTC)

    out = module.sync_portal_discovery(
        cur, ORG, _portal_bags(), now=datetime(2026, 9, 16, 14, 5, 0)
    )
    assert out["admitted"] == 1
    assert store.admits == [EPOCH_ET_WALL]


def test_second_scrape_reuses_the_baseline_anchor_no_duplicate_oi(cycles):
    module, store = cycles
    cur = _Cursor(events=[_stv(datetime(2026, 9, 14, 10, 0))])
    set_wf_reset_epoch_at(cur, ORG, EPOCH_UTC)

    module.sync_portal_discovery(
        cur, ORG, _portal_bags(), now=datetime(2026, 9, 16, 14, 5, 0)
    )
    second = module.sync_portal_discovery(
        cur, ORG, _portal_bags(), now=datetime(2026, 9, 16, 14, 35, 0)
    )

    assert second["admitted"] == 0
    assert len(store.rows) == 1
    assert store.order_instance_keys() == {(ORG, BAG, "WF", EPOCH_ET_WALL)}


def test_baseline_anchor_is_stable_even_if_the_cycle_row_is_lost(cycles):
    """Anchor determinism, not row reuse, is what blocks a forked order instance."""
    module, store = cycles
    cur = _Cursor()
    set_wf_reset_epoch_at(cur, ORG, EPOCH_UTC)

    module.sync_portal_discovery(
        cur, ORG, _portal_bags(), now=datetime(2026, 9, 16, 14, 5, 0)
    )
    store.rows.clear()  # cycle row disappeared between scrapes
    module.sync_portal_discovery(
        cur, ORG, _portal_bags(), now=datetime(2026, 9, 16, 21, 45, 0)
    )

    assert store.admits == [EPOCH_ET_WALL, EPOCH_ET_WALL]
    assert store.order_instance_keys() == {(ORG, BAG, "WF", EPOCH_ET_WALL)}


def test_post_epoch_stv_wins_over_the_baseline_anchor(cycles):
    module, store = cycles
    stv_after = datetime(2026, 9, 16, 9, 30)
    cur = _Cursor(events=[_stv(datetime(2026, 9, 14, 10, 0)), _stv(stv_after)])
    set_wf_reset_epoch_at(cur, ORG, EPOCH_UTC)

    module.sync_portal_discovery(
        cur, ORG, _portal_bags(), now=datetime(2026, 9, 16, 14, 5, 0)
    )
    assert store.admits and store.admits[-1] == stv_after
    assert store.order_instance_keys() == {(ORG, BAG, "WF", stv_after)}


def test_without_an_epoch_behaviour_is_unchanged(cycles):
    module, store = cycles
    cur = _Cursor()
    now = datetime(2026, 9, 16, 14, 5, 0)

    module.sync_portal_discovery(cur, ORG, _portal_bags(), now=now)
    assert store.admits == [now]
