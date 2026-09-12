"""Regression: DISAPPEARED_FROM_PORTAL qualification + CW Review overlay."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_scrape_completeness import (
    STATE_CONFIRMED,
    STATE_PENDING_CONFIRMATION,
)
from backend.rinse_wf_disappeared_from_portal import (
    REASON_DISAPPEARED_FROM_PORTAL,
    qualify_disappeared_from_portal_bags,
    ship_window_bounds_from_meta,
    stv_still_in_source_window,
)


def _oi(bag_id: str, *, anchor: datetime, oid: int = 1) -> dict:
    return {
        "bag_id": bag_id,
        "order_instance_id": oid,
        "cycle_anchor_at": anchor,
        "completed_at": None,
        "service_type": "WF",
        "customer_name": "Test Customer",
    }


def test_ship_window_bounds_from_meta():
    meta = {
        "tickets_sources": [
            {
                "label": "wash_and_fold",
                "service_types": "wash_and_fold",
                "ship_to_vendor_date_start": "2026-09-09",
                "ship_to_vendor_date_end": "2026-09-10",
            }
        ]
    }
    assert ship_window_bounds_from_meta(meta) == (
        date(2026, 9, 9),
        date(2026, 9, 10),
    )


def test_stv_in_window_qualifies():
    meta = {
        "source_mode": "ship_to_vendor_window",
        "absence_capable": False,
        "tickets_sources": [
            {
                "label": "wash_and_fold",
                "ship_to_vendor_date_start": "2026-09-09",
                "ship_to_vendor_date_end": "2026-09-10",
            }
        ],
    }
    assert stv_still_in_source_window(
        cycle_anchor_at=datetime(2026, 9, 9, 22, 4),
        scrape_meta=meta,
    )


def test_d_window_rolloff_does_not_qualify():
    """Bag STV outside the absence-run ship window → no false disappearance."""
    meta = {
        "source_mode": "ship_to_vendor_window",
        "absence_capable": False,
        "tickets_sources": [
            {
                "label": "wash_and_fold",
                "ship_to_vendor_date_start": "2026-09-11",
                "ship_to_vendor_date_end": "2026-09-12",
            }
        ],
    }
    assert not stv_still_in_source_window(
        cycle_anchor_at=datetime(2026, 9, 9, 22, 4),
        scrape_meta=meta,
    )


def test_a_confirmed_in_window_open_oi_qualifies():
    """Previously present + authoritative successful disappearance + open OI."""
    anchor = datetime(2026, 9, 9, 22, 4)
    oi = _oi("9B5V934T45", anchor=anchor, oid=4942)
    cursor = MagicMock()

    with (
        patch(
            "backend.rinse_wf_disappeared_from_portal._load_inactive_presence_for_bags",
            return_value={
                "9B5V934T45": {
                    "bag_id": "9B5V934T45",
                    "active": 0,
                    "first_seen_at": datetime(2026, 9, 10, 2, 5),
                    "last_seen_at": datetime(2026, 9, 10, 2, 44),
                    "customer_name": "Shengyu Bai",
                }
            },
        ),
        patch(
            "backend.rinse_wf_disappeared_from_portal.build_disappearance_confirmation",
            return_value={
                "9B5V934T45": {
                    "state": STATE_CONFIRMED,
                    "trustworthy_absent_runs": 2,
                    "absent_run_ids": [7204, 7203],
                }
            },
        ),
        patch(
            "backend.rinse_wf_disappeared_from_portal._last_present_run_ids",
            return_value={"9B5V934T45": 7202},
        ),
        patch(
            "backend.rinse_wf_disappeared_from_portal._first_establishing_absence_runs_bulk",
            return_value={
                "9B5V934T45": {
                    "id": 7203,
                    "scrape_meta": {
                        "source_mode": "ship_to_vendor_window",
                        "absence_capable": False,
                        "tickets_sources": [
                            {
                                "label": "wash_and_fold",
                                "ship_to_vendor_date_start": "2026-09-09",
                                "ship_to_vendor_date_end": "2026-09-10",
                            }
                        ],
                    },
                }
            },
        ),
    ):
        out = qualify_disappeared_from_portal_bags(cursor, 3, [oi])
    assert "9B5V934T45" in out
    assert out["9B5V934T45"]["reason_code"] == REASON_DISAPPEARED_FROM_PORTAL
    assert out["9B5V934T45"]["last_present_run_id"] == 7202
    assert out["9B5V934T45"]["first_absent_run_id"] == 7203


def test_b_scrape_failure_no_transition():
    """Failed/anomalous runs never confirm disappearance → no qualify."""
    oi = _oi("BAGFAIL", anchor=datetime(2026, 9, 9, 12, 0))
    with (
        patch(
            "backend.rinse_wf_disappeared_from_portal._load_inactive_presence_for_bags",
            return_value={
                "BAGFAIL": {
                    "bag_id": "BAGFAIL",
                    "active": 0,
                    "first_seen_at": datetime(2026, 9, 9, 1, 0),
                    "last_seen_at": datetime(2026, 9, 9, 1, 0),
                }
            },
        ),
        patch(
            "backend.rinse_wf_disappeared_from_portal.build_disappearance_confirmation",
            return_value={
                "BAGFAIL": {
                    "state": STATE_PENDING_CONFIRMATION,
                    "trustworthy_absent_runs": 0,
                    "absent_run_ids": [],
                }
            },
        ),
    ):
        out = qualify_disappeared_from_portal_bags(MagicMock(), 3, [oi])
    assert out == {}


def test_c_partial_non_authoritative_no_transition():
    """Pending confirmation (single absence / untrusted) → no Review transition."""
    oi = _oi("BAGPART", anchor=datetime(2026, 9, 9, 12, 0))
    with (
        patch(
            "backend.rinse_wf_disappeared_from_portal._load_inactive_presence_for_bags",
            return_value={
                "BAGPART": {
                    "bag_id": "BAGPART",
                    "active": 0,
                    "first_seen_at": datetime(2026, 9, 9, 1, 0),
                    "last_seen_at": datetime(2026, 9, 9, 1, 0),
                }
            },
        ),
        patch(
            "backend.rinse_wf_disappeared_from_portal.build_disappearance_confirmation",
            return_value={
                "BAGPART": {
                    "state": STATE_PENDING_CONFIRMATION,
                    "trustworthy_absent_runs": 1,
                    "absent_run_ids": [99],
                }
            },
        ),
    ):
        assert qualify_disappeared_from_portal_bags(MagicMock(), 3, [oi]) == {}


def test_d_rolloff_confirmed_but_outside_window_no_qualify():
    oi = _oi("BAGROLL", anchor=datetime(2026, 9, 1, 10, 0))
    with (
        patch(
            "backend.rinse_wf_disappeared_from_portal._load_inactive_presence_for_bags",
            return_value={
                "BAGROLL": {
                    "bag_id": "BAGROLL",
                    "active": 0,
                    "first_seen_at": datetime(2026, 9, 1, 1, 0),
                    "last_seen_at": datetime(2026, 9, 1, 1, 0),
                }
            },
        ),
        patch(
            "backend.rinse_wf_disappeared_from_portal.build_disappearance_confirmation",
            return_value={
                "BAGROLL": {
                    "state": STATE_CONFIRMED,
                    "trustworthy_absent_runs": 5,
                    "absent_run_ids": [50, 49],
                }
            },
        ),
        patch(
            "backend.rinse_wf_disappeared_from_portal._last_present_run_ids",
            return_value={"BAGROLL": 40},
        ),
        patch(
            "backend.rinse_wf_disappeared_from_portal._first_establishing_absence_runs_bulk",
            return_value={
                "BAGROLL": {
                    "id": 49,
                    "scrape_meta": {
                        "source_mode": "ship_to_vendor_window",
                        "tickets_sources": [
                            {
                                "label": "wash_and_fold",
                                "ship_to_vendor_date_start": "2026-09-11",
                                "ship_to_vendor_date_end": "2026-09-12",
                            }
                        ],
                    },
                }
            },
        ),
    ):
        assert qualify_disappeared_from_portal_bags(MagicMock(), 3, [oi]) == {}


def test_e_still_present_stays_normal():
    oi = _oi("BAGHERE", anchor=datetime(2026, 9, 9, 12, 0))
    with patch(
        "backend.rinse_wf_disappeared_from_portal._load_inactive_presence_for_bags",
        return_value={},
    ):
        assert qualify_disappeared_from_portal_bags(MagicMock(), 3, [oi]) == {}


def test_f_already_completed_no_review_resurrection():
    oi = {
        **_oi("BAGDONE", anchor=datetime(2026, 9, 9, 12, 0)),
        "completed_at": datetime(2026, 9, 10, 15, 0),
    }
    with patch(
        "backend.rinse_wf_disappeared_from_portal._load_inactive_presence_for_bags",
        return_value={
            "BAGDONE": {
                "bag_id": "BAGDONE",
                "active": 0,
                "first_seen_at": datetime(2026, 9, 9, 1, 0),
                "last_seen_at": datetime(2026, 9, 9, 1, 0),
            }
        },
    ) as inactive:
        out = qualify_disappeared_from_portal_bags(MagicMock(), 3, [oi])
    assert out == {}
    inactive.assert_not_called()


def test_cw_moves_qualified_bag_to_review():
    from backend.rinse_wf_current_workload import get_current_wf_workload

    anchor = datetime(2026, 9, 9, 22, 4)
    open_row = _oi("9B5V934T45", anchor=anchor, oid=4942)
    cursor = MagicMock()

    with (
        patch(
            "backend.rinse_order_instances.list_open_wf_order_instances",
            return_value=[open_row],
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
            return_value=set(),
        ),
        patch(
            "backend.rinse_wf_current_workload.lifecycle_received_from_vendor_at",
            return_value=None,
        ),
        patch(
            "backend.management_wf_review_cache.get_qualified_disappeared_from_portal",
            return_value={
                "9B5V934T45": {
                    "bag_id": "9B5V934T45",
                    "reason_code": REASON_DISAPPEARED_FROM_PORTAL,
                    "reason_label": "Disappeared From Portal",
                    "last_seen_at": datetime(2026, 9, 10, 2, 44),
                    "last_present_run_id": 7202,
                    "first_absent_run_id": 7203,
                    "customer_name": "Shengyu Bai",
                }
            },
        ),
    ):
        wl = get_current_wf_workload(cursor, 3)

    assert "9B5V934T45" in wl["review"]
    assert "9B5V934T45" not in wl["pending"]
    item = next(i for i in wl["items"] if i["bag_id"] == "9B5V934T45")
    assert item["status"] == "review_required"
    assert REASON_DISAPPEARED_FROM_PORTAL in item["review_reason_codes"]


def test_g_missing_portal_category_includes_new_reason():
    from backend.management_rinse_wf_review import (
        CATEGORY_MISSING_PORTAL,
        category_for_reason_codes,
        _short_reason,
    )

    assert (
        category_for_reason_codes([REASON_DISAPPEARED_FROM_PORTAL])
        == CATEGORY_MISSING_PORTAL
    )
    assert (
        _short_reason([REASON_DISAPPEARED_FROM_PORTAL], CATEGORY_MISSING_PORTAL)
        == "Disappeared From Portal"
    )
    # Existing reasons unchanged
    assert (
        category_for_reason_codes(["DISAPPEARED_WITHOUT_COMPLETION"])
        == CATEGORY_MISSING_PORTAL
    )


def test_h_manager_exclude_closes_oi_keeps_row():
    from backend.rinse_wf_disappeared_from_portal import (
        apply_manager_exclude_to_open_wf_lifecycle,
    )

    cursor = MagicMock()
    cursor.fetchone.return_value = None
    with (
        patch(
            "backend.rinse_wf_service_cycle.get_active_cycle_for_bag",
            return_value={
                "bag_id": "9B5V934T45",
                "cycle_anchor_at": datetime(2026, 9, 9, 22, 4),
                "admitted_at": datetime(2026, 9, 10, 2, 7),
                "admitted_source": "PORTAL_DISCOVERY",
                "status": "ACTIVE",
            },
        ),
        patch("backend.rinse_wf_service_cycle.upsert_service_cycle") as upsert,
        patch(
            "backend.rinse_order_instances.list_order_instances_for_bag",
            return_value=[
                {
                    "order_instance_id": 4942,
                    "bag_id": "9B5V934T45",
                    "completed_at": None,
                }
            ],
        ),
    ):
        out = apply_manager_exclude_to_open_wf_lifecycle(
            cursor, 3, "9B5V934T45", resolved_by="Manager"
        )
    assert out["cycle_resolved"] is True
    assert out["ois_closed"] == 1
    upsert.assert_called_once()
    assert upsert.call_args.kwargs["status"] == "RESOLVED_OTHER"
    # UPDATE OI — does not DELETE
    assert any(
        "UPDATE" in str(c.args[0]) and "rinse_order_instances" in str(c.args[0]).lower()
        or "UPDATE" in str(c.args[0])
        for c in cursor.execute.call_args_list
    )
    assert not any("DELETE" in str(c.args[0]).upper() for c in cursor.execute.call_args_list)


def test_i_present_bag_unchanged_in_cw_pending():
    from backend.rinse_wf_current_workload import get_current_wf_workload

    open_row = _oi("LEGIT1", anchor=datetime(2026, 9, 12, 10, 0), oid=99)
    with (
        patch(
            "backend.rinse_order_instances.list_open_wf_order_instances",
            return_value=[open_row],
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
            return_value=set(),
        ),
        patch(
            "backend.rinse_wf_current_workload.lifecycle_received_from_vendor_at",
            return_value=None,
        ),
        patch(
            "backend.management_wf_review_cache.get_qualified_disappeared_from_portal",
            return_value={},
        ),
    ):
        wl = get_current_wf_workload(MagicMock(), 3)
    assert "LEGIT1" in wl["pending"]
    assert "LEGIT1" not in wl["review"]
