"""Regression: Management Rinse HD stage counts == queue membership."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.management_rinse_hd import (
    ATTR_SOURCE_MANAGER,
    ATTR_SOURCE_SCAN,
    STATUS_AWAITING_ENTRY,
    STATUS_AWAITING_FOLD,
    STATUS_COMPLETE,
    STATUS_MISSING_FROM_PORTAL,
    STATUS_PENDING_WASH,
    STATUS_WASHED,
    build_rinse_hd_day,
    build_rinse_hd_summary,
    classify_hd_portal_bucket,
    derive_workflow_status,
)


def _stage_counts_match_queue(day_payload: dict) -> None:
    counts = day_payload.get("counts") or {}
    summary = day_payload.get("summary") or {}
    for key, summary_key in (
        ("pending_wash", "pending_wash"),
        ("awaiting_fold", "awaiting_fold"),
        ("awaiting_entry", "awaiting_entry"),
        ("complete", "complete"),
        ("missing_from_portal", "missing_from_portal"),
        ("excluded", "excluded"),
    ):
        assert int(counts.get(key) or 0) == int(summary.get(summary_key) or 0), key

    orders = day_payload.get("orders") or []
    if (day_payload.get("_meta") or {}).get("order_count") == len(orders):
        by_status: dict[str, int] = {}
        for row in orders:
            st = str(row.get("status") or "")
            by_status[st] = by_status.get(st, 0) + 1
        assert by_status.get(STATUS_PENDING_WASH, 0) == int(counts.get(STATUS_PENDING_WASH) or 0)
        assert by_status.get(STATUS_AWAITING_ENTRY, 0) == int(counts.get(STATUS_AWAITING_ENTRY) or 0)
        assert by_status.get(STATUS_COMPLETE, 0) == int(counts.get(STATUS_COMPLETE) or 0)
        assert by_status.get(STATUS_MISSING_FROM_PORTAL, 0) == int(
            counts.get(STATUS_MISSING_FROM_PORTAL) or 0
        )
        fold_n = by_status.get(STATUS_AWAITING_FOLD, 0) + by_status.get(STATUS_WASHED, 0)
        assert fold_n == int(counts.get(STATUS_AWAITING_FOLD) or 0)


def _day_builder_setup(
    *,
    portal_bags: set[str],
    production: dict,
    resolve_side_effect,
):
    cursor = MagicMock()
    activation = date(2026, 8, 21)

    def _fake_day(cursor, org, selected, status=None):
        with (
            patch("backend.hd_workflow_extensions.hd_workflow_cutoff", return_value=(activation, None)),
            patch("backend.management_rinse_hd._load_hd_service_hints", return_value={b: "HD" for b in portal_bags}),
            patch(
                "backend.management_rinse_hd.admit_discovered_hd_bags",
                return_value={"admitted_new": 0, "already_admitted": 0, "bag_ids": list(portal_bags)},
            ),
            patch("backend.management_rinse_hd._load_active_admitted_bag_ids", return_value=set(production.keys())),
            patch("backend.management_rinse_hd._load_candidate_events_for_bags", return_value=[]),
            patch("backend.management_rinse_hd._load_production_by_bag", return_value=production),
            patch("backend.management_rinse_hd._load_user_maps", return_value={}),
            patch("backend.management_rinse_hd._batch_user_names", return_value={}),
            patch("backend.management_rinse_hd._load_hd_portal_bags_for_day", return_value=portal_bags),
            patch("backend.management_rinse_hd._load_hd_presence_meta", return_value={}),
            patch("backend.hd_workflow_extensions.build_excluded_hd_orders", return_value=[]),
            patch("backend.hd_workflow_extensions.attach_delivery_dates", side_effect=lambda _c, _o, orders: orders),
            patch("backend.management_rinse_hd.resolve_order_state", side_effect=resolve_side_effect),
        ):
            out = build_rinse_hd_day(cursor, org, selected, status=status or "all")
        out["_cursor"] = cursor
        out["_org"] = org
        return out

    return _fake_day, cursor


def test_summary_stage_counts_match_day_builder():
    activation = date(2026, 8, 24)
    production = {
        "P1": {"bag_id": "P1", "workflow_status": STATUS_PENDING_WASH, "operations_date_et": activation},
        "W1": {
            "bag_id": "W1",
            "workflow_status": STATUS_WASHED,
            "washed_at": datetime(2026, 8, 24, 9, 0),
            "operations_date_et": activation,
        },
    }

    def resolve(_events, service_hint=None, production=None, **_kw):
        bid = (production or {}).get("bag_id")
        if bid == "W1":
            return {
                "bag_id": "W1",
                "status": STATUS_WASHED,
                "washed_at": datetime(2026, 8, 24, 9, 0),
                "folded_at": None,
                "operations_date_et": activation,
            }
        return {
            "bag_id": "P1",
            "status": STATUS_PENDING_WASH,
            "washed_at": None,
            "folded_at": None,
            "operations_date_et": activation,
        }

    fake_day, cursor = _day_builder_setup(
        portal_bags={"P1", "W1"},
        production=production,
        resolve_side_effect=resolve,
    )
    day = fake_day(cursor, 3, activation, "all")
    _stage_counts_match_queue(day)

    with (
        patch("backend.management_rinse_hd.build_rinse_hd_day", return_value=day),
        patch("backend.management_rinse_hd.table_exists", return_value=True),
        patch("backend.management_rinse_hd.ensure_management_hd_columns"),
    ):
        cursor.fetchone.return_value = {
            "washed_in_range": 1,
            "folded_in_range": 0,
            "items_n": 0,
            "revenue_n": 0,
        }
        summary = build_rinse_hd_summary(
            cursor, 3, start_et=activation, end_et=activation, snapshot_date_et=activation
        )
    assert summary["pending_wash"] == day["summary"]["pending_wash"]
    assert summary["awaiting_fold"] == day["summary"]["awaiting_fold"]
    assert summary["stage_source"] == "build_rinse_hd_day"


def test_no_wash_evidence_pending_wash():
    assert (
        derive_workflow_status(washed_at=None, folded_at=None, explicitly_complete=False)
        == STATUS_PENDING_WASH
    )


def test_wash_only_awaiting_fold():
    washed = datetime(2026, 8, 24, 9, 0)
    assert (
        derive_workflow_status(washed_at=washed, folded_at=None, explicitly_complete=False)
        == STATUS_WASHED
    )


def test_wash_and_fold_awaiting_entry():
    washed = datetime(2026, 8, 24, 9, 0)
    folded = datetime(2026, 8, 24, 11, 0)
    assert (
        derive_workflow_status(washed_at=washed, folded_at=folded, explicitly_complete=False)
        == STATUS_AWAITING_ENTRY
    )


def test_terminal_evidence_complete():
    washed = datetime(2026, 8, 24, 9, 0)
    folded = datetime(2026, 8, 24, 11, 0)
    assert (
        derive_workflow_status(washed_at=washed, folded_at=folded, explicitly_complete=True)
        == STATUS_COMPLETE
    )


def test_pre_processing_disappearance_missing_from_portal():
    assert (
        classify_hd_portal_bucket(
            workflow_status=STATUS_PENDING_WASH,
            explicitly_complete=False,
            on_latest_portal=False,
        )
        == STATUS_MISSING_FROM_PORTAL
    )


def test_wash_stage_disappearance_missing_from_portal():
    assert (
        classify_hd_portal_bucket(
            workflow_status=STATUS_WASHED,
            explicitly_complete=False,
            on_latest_portal=False,
            washed_attribution_source=ATTR_SOURCE_SCAN,
        )
        == STATUS_MISSING_FROM_PORTAL
    )


def test_post_completion_disappearance_not_missing():
    assert (
        classify_hd_portal_bucket(
            workflow_status=STATUS_COMPLETE,
            explicitly_complete=True,
            on_latest_portal=False,
        )
        == STATUS_COMPLETE
    )


def test_manual_wash_preserves_awaiting_fold_when_off_portal():
    assert (
        classify_hd_portal_bucket(
            workflow_status=STATUS_WASHED,
            explicitly_complete=False,
            on_latest_portal=False,
            washed_attribution_source=ATTR_SOURCE_MANAGER,
        )
        == STATUS_WASHED
    )


def test_manual_fold_preserves_awaiting_entry_when_off_portal():
    assert (
        classify_hd_portal_bucket(
            workflow_status=STATUS_AWAITING_ENTRY,
            explicitly_complete=False,
            on_latest_portal=False,
            folded_attribution_source=ATTR_SOURCE_MANAGER,
        )
        == STATUS_AWAITING_ENTRY
    )


def test_folded_awaiting_entry_stays_when_off_portal_without_manager_flag():
    assert (
        classify_hd_portal_bucket(
            workflow_status=STATUS_AWAITING_ENTRY,
            explicitly_complete=False,
            on_latest_portal=False,
            washed_attribution_source=ATTR_SOURCE_SCAN,
            folded_attribution_source=ATTR_SOURCE_SCAN,
        )
        == STATUS_AWAITING_ENTRY
    )


def test_no_bag_in_two_primary_stages():
    activation = date(2026, 8, 24)
    production = {
        "A": {"bag_id": "A", "workflow_status": STATUS_PENDING_WASH, "operations_date_et": activation},
        "B": {
            "bag_id": "B",
            "workflow_status": STATUS_WASHED,
            "washed_at": datetime(2026, 8, 24, 8, 0),
            "operations_date_et": activation,
        },
        "C": {
            "bag_id": "C",
            "workflow_status": STATUS_AWAITING_ENTRY,
            "washed_at": datetime(2026, 8, 24, 8, 0),
            "folded_at": datetime(2026, 8, 24, 10, 0),
            "operations_date_et": activation,
        },
    }

    def resolve(_events, service_hint=None, production=None, **_kw):
        bid = (production or {}).get("bag_id")
        if bid == "B":
            return {
                "bag_id": "B",
                "status": STATUS_WASHED,
                "washed_at": datetime(2026, 8, 24, 8, 0),
                "folded_at": None,
                "operations_date_et": activation,
            }
        if bid == "C":
            return {
                "bag_id": "C",
                "status": STATUS_AWAITING_ENTRY,
                "washed_at": datetime(2026, 8, 24, 8, 0),
                "folded_at": datetime(2026, 8, 24, 10, 0),
                "operations_date_et": activation,
            }
        return {
            "bag_id": "A",
            "status": STATUS_PENDING_WASH,
            "washed_at": None,
            "folded_at": None,
            "operations_date_et": activation,
        }

    fake_day, cursor = _day_builder_setup(
        portal_bags={"A", "B", "C"},
        production=production,
        resolve_side_effect=resolve,
    )
    day = fake_day(cursor, 3, activation, "all")
    seen: set[str] = set()
    for status in (
        STATUS_PENDING_WASH,
        STATUS_WASHED,
        STATUS_AWAITING_ENTRY,
        STATUS_COMPLETE,
        STATUS_MISSING_FROM_PORTAL,
    ):
        for row in day.get("orders") or []:
            if row.get("status") != status:
                continue
            bid = row.get("bag_id")
            assert bid not in seen, bid
            seen.add(bid)


def test_summary_union_equals_population_plus_excluded():
    activation = date(2026, 8, 24)
    production = {
        "OPEN1": {"bag_id": "OPEN1", "workflow_status": STATUS_PENDING_WASH, "operations_date_et": activation},
    }

    def resolve(_events, service_hint=None, production=None, **_kw):
        return {
            "bag_id": (production or {}).get("bag_id"),
            "status": STATUS_PENDING_WASH,
            "washed_at": None,
            "folded_at": None,
            "operations_date_et": activation,
        }

    fake_day, cursor = _day_builder_setup(
        portal_bags={"OPEN1"},
        production=production,
        resolve_side_effect=resolve,
    )

    with patch("backend.hd_workflow_extensions.build_excluded_hd_orders", return_value=[{"bag_id": "EX1", "status": "excluded"}]):
        day = fake_day(cursor, 3, activation, "all")

    summary = day["summary"]
    union = (
        int(summary.get("pending_wash") or 0)
        + int(summary.get("awaiting_fold") or 0)
        + int(summary.get("awaiting_entry") or 0)
        + int(summary.get("complete") or 0)
        + int(summary.get("missing_from_portal") or 0)
        + int(summary.get("excluded") or 0)
    )
    assert union == int(summary.get("admitted_total") or 0) + int(summary.get("excluded") or 0)
