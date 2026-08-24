"""Regression: Management Rinse HD Missing From Portal review membership."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.management_rinse_hd import (
    STATUS_AWAITING_ENTRY,
    STATUS_COMPLETE,
    STATUS_MISSING_FROM_PORTAL,
    STATUS_PENDING_WASH,
    STATUS_WASHED,
    build_rinse_hd_day,
)
from backend.management_rinse_hd_review import (
    CATEGORY_MISSING_FROM_PORTAL,
    HD_REVIEW_REASON_MISSING_FROM_PORTAL,
    compute_canonical_hd_missing_membership,
    enrich_hd_order_with_review,
    format_hd_customer_name,
    hd_review_disposition_for_order,
    load_hd_latest_source_portal_context,
)


def _portal_ctx(*bag_ids: str, traversal_complete: bool = True) -> dict:
    return {
        "traversal_complete": traversal_complete,
        "portal_bag_ids": set(bag_ids),
        "presence_run_id": 99,
        "finished_at": datetime(2026, 8, 24, 22, 0),
        "reason": None,
        "snapshot_by_bag": {},
    }


def test_pending_wash_disappears_to_missing_review():
    display, ctx = hd_review_disposition_for_order(
        workflow_status=STATUS_PENDING_WASH,
        explicitly_complete=False,
        bag_id="P1",
        portal_context=_portal_ctx(),
    )
    assert display == STATUS_MISSING_FROM_PORTAL
    assert ctx["review_reason"] == HD_REVIEW_REASON_MISSING_FROM_PORTAL
    assert ctx["prior_hd_status"] == STATUS_PENDING_WASH


def test_awaiting_fold_disappears_to_missing_review():
    display, _ctx = hd_review_disposition_for_order(
        workflow_status=STATUS_WASHED,
        explicitly_complete=False,
        bag_id="W1",
        portal_context=_portal_ctx(),
    )
    assert display == STATUS_MISSING_FROM_PORTAL


def test_awaiting_entry_disappears_to_missing_review():
    display, _ctx = hd_review_disposition_for_order(
        workflow_status=STATUS_AWAITING_ENTRY,
        explicitly_complete=False,
        bag_id="E1",
        portal_context=_portal_ctx(),
    )
    assert display == STATUS_MISSING_FROM_PORTAL


def test_completed_then_disappears_no_review():
    display, ctx = hd_review_disposition_for_order(
        workflow_status=STATUS_COMPLETE,
        explicitly_complete=True,
        bag_id="C1",
        portal_context=_portal_ctx(),
    )
    assert display == STATUS_COMPLETE
    assert ctx["review_reason"] is None


def test_reappears_in_source_clears_missing_review():
    membership_absent = compute_canonical_hd_missing_membership(
        [{"bag_id": "R1", "workflow_status": STATUS_WASHED, "explicitly_complete": False}],
        _portal_ctx(),
    )
    assert membership_absent["missing_from_portal"] == ["R1"]

    membership_present = compute_canonical_hd_missing_membership(
        [{"bag_id": "R1", "workflow_status": STATUS_WASHED, "explicitly_complete": False}],
        _portal_ctx("R1"),
    )
    assert membership_present["missing_from_portal"] == []
    assert membership_present["disposition"]["R1"] == STATUS_WASHED


def test_headline_missing_count_equals_drawer_membership():
    orders = [
        {"bag_id": "A1", "workflow_status": STATUS_WASHED, "explicitly_complete": False},
        {"bag_id": "A2", "workflow_status": STATUS_AWAITING_ENTRY, "explicitly_complete": False},
        {"bag_id": "A3", "workflow_status": STATUS_PENDING_WASH, "explicitly_complete": False},
    ]
    membership = compute_canonical_hd_missing_membership(orders, _portal_ctx("A3"))
    assert membership["counts"][CATEGORY_MISSING_FROM_PORTAL] == 2
    assert set(membership[CATEGORY_MISSING_FROM_PORTAL]) == {"A1", "A2"}


def test_missing_bag_not_in_normal_queue_bucket():
    activation = date(2026, 8, 24)
    production = {
        "W1": {
            "bag_id": "W1",
            "workflow_status": STATUS_WASHED,
            "washed_at": datetime(2026, 8, 24, 9, 0),
            "operations_date_et": activation,
        },
    }

    def resolve(_events, service_hint=None, production=None, **_kw):
        return {
            "bag_id": "W1",
            "status": STATUS_WASHED,
            "washed_at": datetime(2026, 8, 24, 9, 0),
            "folded_at": None,
            "operations_date_et": activation,
        }

    cursor = MagicMock()
    with (
        patch("backend.hd_workflow_extensions.hd_workflow_cutoff", return_value=(activation, None)),
        patch("backend.management_rinse_hd._load_hd_service_hints", return_value={"W1": "HD"}),
        patch(
            "backend.management_rinse_hd.admit_discovered_hd_bags",
            return_value={"admitted_new": 0, "already_admitted": 0, "bag_ids": ["W1"]},
        ),
        patch("backend.management_rinse_hd._load_active_admitted_bag_ids", return_value={"W1"}),
        patch("backend.management_rinse_hd._load_candidate_events_for_bags", return_value=[]),
        patch("backend.management_rinse_hd._load_production_by_bag", return_value=production),
        patch("backend.management_rinse_hd._load_user_maps", return_value={}),
        patch("backend.management_rinse_hd._batch_user_names", return_value={}),
        patch(
            "backend.management_rinse_hd_review.load_hd_latest_source_portal_context",
            return_value=_portal_ctx(),
        ),
        patch("backend.management_rinse_hd._load_hd_presence_meta", return_value={}),
        patch("backend.hd_workflow_extensions.build_excluded_hd_orders", return_value=[]),
        patch("backend.hd_workflow_extensions.attach_delivery_dates", side_effect=lambda _c, _o, orders: orders),
        patch("backend.management_rinse_hd.resolve_order_state", side_effect=resolve),
    ):
        day = build_rinse_hd_day(cursor, 3, activation, status="all")

    assert day["counts"]["awaiting_fold"] == 0
    assert day["counts"]["missing_from_portal"] == 1
    assert day["orders"][0]["status"] == STATUS_MISSING_FROM_PORTAL
    assert day["orders"][0]["prior_hd_status"] == STATUS_WASHED


def test_customer_name_resolves_or_shows_unavailable():
    assert format_hd_customer_name({"customer_name": "Ada Lovelace"}) == "Ada Lovelace"
    assert format_hd_customer_name({"customer_name": ""}) == "Customer unavailable"
    assert format_hd_customer_name(None) == "Customer unavailable"


def test_partial_traversal_does_not_flag_missing():
    display, _ctx = hd_review_disposition_for_order(
        workflow_status=STATUS_WASHED,
        explicitly_complete=False,
        bag_id="W1",
        portal_context=_portal_ctx(traversal_complete=False),
    )
    assert display == STATUS_WASHED


def test_enrich_preserves_prior_state_for_review_row():
    row = enrich_hd_order_with_review(
        {"bag_id": "X1", "status": STATUS_WASHED, "workflow_status": STATUS_WASHED},
        compute_canonical_hd_missing_membership(
            [{"bag_id": "X1", "workflow_status": STATUS_WASHED, "explicitly_complete": False}],
            _portal_ctx(),
        ),
    )
    assert row["status"] == STATUS_MISSING_FROM_PORTAL
    assert row["prior_hd_status"] == STATUS_WASHED
    assert row["workflow_status"] == STATUS_WASHED


def test_completed_bag_does_not_resurrect_into_review():
    membership = compute_canonical_hd_missing_membership(
        [
            {
                "bag_id": "DONE1",
                "workflow_status": STATUS_COMPLETE,
                "explicitly_complete": True,
                "completion_at": datetime(2026, 8, 24, 16, 0),
            }
        ],
        _portal_ctx(),
    )
    assert membership["missing_from_portal"] == []
    assert membership["disposition"]["DONE1"] == STATUS_COMPLETE


def test_load_hd_latest_source_portal_context_filters_hd_only():
    cursor = MagicMock()
    run = {"id": 12, "status": "success", "finished_at": datetime(2026, 8, 24, 22, 0)}
    snapshot = {
        "HD1": {"service_type": "HD"},
        "WF1": {"service_type": "WF"},
    }
    with (
        patch(
            "backend.rinse_shift_monitor_baseline.latest_clean_at_vendor_presence_scrape",
            return_value=run,
        ),
        patch(
            "backend.rinse_shift_monitor_baseline._is_successful_presence_run",
            return_value=True,
        ),
        patch(
            "backend.rinse_shift_monitor_baseline.is_contaminated_presence_run",
            return_value=False,
        ),
        patch(
            "backend.rinse_cleaner_ticket_presence.load_presence_run_snapshot_by_bag",
            return_value=snapshot,
        ),
        patch("backend.management_rinse_hd_review.table_exists", return_value=True),
    ):
        ctx = load_hd_latest_source_portal_context(cursor, 3)
    assert ctx["traversal_complete"] is True
    assert ctx["portal_bag_ids"] == {"HD1"}
