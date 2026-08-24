"""Tests for HD fresh start, exclude/restore/delete, delivery dates."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.hd_workflow_extensions import (
    STATUS_EXCLUDED,
    attach_delivery_dates,
    exclude_hd_order,
    on_or_after_workflow_cutoff,
    permanent_delete_hd_orders,
    restore_hd_order,
)
from backend.management_rinse_hd import (
    STATUS_AWAITING_ENTRY,
    STATUS_PENDING_WASH,
    STATUS_WASHED,
    resolve_order_state,
)


def _ev(purpose, at, user="Op", bag="HD001", eid=1):
    return {
        "id": eid,
        "bag_id": bag,
        "purpose": purpose,
        "scanned_at_parsed": at,
        "user_name": user,
    }


def test_on_or_after_workflow_cutoff_respects_fresh_start_at():
    fresh = datetime(2026, 8, 22, 18, 0, 0)
    assert on_or_after_workflow_cutoff(
        datetime(2026, 8, 22, 17, 59, 0),
        date(2026, 8, 22),
        fresh_start_at=fresh,
    ) is False
    assert on_or_after_workflow_cutoff(
        datetime(2026, 8, 22, 18, 0, 0),
        date(2026, 8, 22),
        fresh_start_at=fresh,
    ) is True


def test_pre_cutover_wash_does_not_advance_after_fresh_start():
    fresh = datetime(2026, 8, 22, 18, 0, 0)
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 22, 9, 0), eid=2),
        _ev("complete-cleaning", datetime(2026, 8, 22, 10, 0), eid=3),
    ]
    state = resolve_order_state(
        events,
        service_hint="HD",
        activation_date=date(2026, 8, 22),
        fresh_start_at=fresh,
    )
    assert state is not None
    assert state["status"] == STATUS_PENDING_WASH
    assert state["washed_at"] is None
    assert state["folded_at"] is None


def test_post_cutover_wash_advances_normally():
    fresh = datetime(2026, 8, 22, 8, 0, 0)
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 22, 9, 0), eid=2),
    ]
    state = resolve_order_state(
        events,
        service_hint="HD",
        activation_date=date(2026, 8, 22),
        fresh_start_at=fresh,
    )
    assert state["status"] == STATUS_WASHED


def test_post_cutover_wash_and_fold_advances_to_awaiting_entry():
    fresh = datetime(2026, 8, 22, 8, 0, 0)
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 22, 9, 0), eid=2),
        _ev("complete-cleaning", datetime(2026, 8, 22, 10, 0), eid=3),
    ]
    state = resolve_order_state(
        events,
        service_hint="HD",
        activation_date=date(2026, 8, 22),
        fresh_start_at=fresh,
    )
    assert state["status"] == STATUS_AWAITING_ENTRY


def test_attach_delivery_dates_sets_field():
    cursor = MagicMock()
    with patch(
        "backend.hd_workflow_extensions._load_delivery_dates_for_bags",
        return_value={"HD001": date(2026, 8, 23)},
    ):
        out = attach_delivery_dates(cursor, 3, [{"bag_id": "HD001"}])
    assert out[0]["delivery_date_et"] == "2026-08-23"


def test_exclude_restore_idempotent_no_duplicate_row():
    cursor = MagicMock(dictionary=True)
    prod = {
        "id": 10,
        "bag_id": "HD001",
        "workflow_status": STATUS_PENDING_WASH,
        "version": 1,
    }
    with (
        patch("backend.hd_workflow_extensions._load_production_by_bag", return_value={"HD001": prod}),
        patch("backend.hd_workflow_extensions.hd_workflow_cutoff", return_value=(date(2026, 8, 22), datetime(2026, 8, 22, 18))),
        patch("backend.hd_workflow_extensions._load_candidate_events_for_bags", return_value=[]),
        patch("backend.hd_workflow_extensions.resolve_order_state", return_value={"status": STATUS_PENDING_WASH}),
    ):
        first = exclude_hd_order(cursor, 3, "HD001", actor_user_id=1, actor_name="Mgr")
        assert first["ok"] is True
        prod_excluded = {**prod, "workflow_status": STATUS_EXCLUDED}
        second = exclude_hd_order(cursor, 3, "HD001", actor_user_id=1, actor_name="Mgr")
        with patch("backend.hd_workflow_extensions._load_production_by_bag", return_value={"HD001": prod_excluded}):
            second = exclude_hd_order(cursor, 3, "HD001", actor_user_id=1, actor_name="Mgr")
        assert second.get("already_excluded") is True


def test_restore_returns_pending_when_no_post_cutover_evidence():
    cursor = MagicMock(dictionary=True)
    prod = {"id": 11, "bag_id": "HD002", "workflow_status": STATUS_EXCLUDED, "version": 2}
    with (
        patch("backend.hd_workflow_extensions._load_production_by_bag", side_effect=[
            {"HD002": prod},
            {"HD002": {**prod, "workflow_status": STATUS_PENDING_WASH}},
        ]),
        patch("backend.hd_workflow_extensions.hd_workflow_cutoff", return_value=(date(2026, 8, 22), datetime(2026, 8, 22, 18))),
        patch("backend.hd_workflow_extensions._load_candidate_events_for_bags", return_value=[]),
        patch("backend.hd_workflow_extensions._load_user_maps", return_value={}),
        patch("backend.hd_workflow_extensions._persist_scan_state_for_admitted", return_value=None),
        patch(
            "backend.hd_workflow_extensions.resolve_order_state",
            return_value={"status": STATUS_PENDING_WASH, "bag_id": "HD002"},
        ),
    ):
        out = restore_hd_order(cursor, 3, "HD002", actor_user_id=1)
    assert out["ok"] is True
    assert out["restored_status"] == STATUS_PENDING_WASH


def test_build_rinse_hd_day_skips_quarantined_portal_hints():
    from unittest.mock import MagicMock, patch

    from backend.management_rinse_hd import (
        WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED,
        build_rinse_hd_day,
    )

    cursor = MagicMock()
    quarantined = {
        "id": 1,
        "bag_id": "OLD1",
        "workflow_status": WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED,
        "operations_date_et": date(2026, 8, 22),
        "version": 1,
    }
    retained = {
        "id": 2,
        "bag_id": "KEEP1",
        "workflow_status": STATUS_PENDING_WASH,
        "operations_date_et": date(2026, 8, 22),
        "version": 1,
    }
    with (
        patch("backend.hd_workflow_extensions.hd_workflow_cutoff", return_value=(date(2026, 8, 22), datetime(2026, 8, 22, 18))),
        patch("backend.management_rinse_hd._load_hd_service_hints", return_value={"OLD1": "HD", "KEEP1": "HD"}),
        patch("backend.management_rinse_hd.admit_discovered_hd_bags", return_value={"admitted_new": 0, "already_admitted": 0, "skipped_quarantined": 1, "bag_ids": ["KEEP1"]}),
        patch("backend.management_rinse_hd._load_active_admitted_bag_ids", return_value=set()),
        patch("backend.management_rinse_hd._load_candidate_events_for_bags", return_value=[]),
        patch("backend.management_rinse_hd._load_production_by_bag", return_value={"OLD1": quarantined, "KEEP1": retained}),
        patch("backend.management_rinse_hd._load_user_maps", return_value={}),
        patch("backend.management_rinse_hd._batch_user_names", return_value={}),
        patch("backend.management_rinse_hd_review.load_hd_latest_source_portal_context", return_value={
            "traversal_complete": True,
            "portal_bag_ids": {"KEEP1"},
            "presence_run_id": 1,
            "finished_at": None,
            "reason": None,
            "snapshot_by_bag": {},
        }),
        patch("backend.management_rinse_hd._load_hd_presence_meta", return_value={}),
        patch("backend.hd_workflow_extensions.build_excluded_hd_orders", return_value=[]),
        patch("backend.hd_workflow_extensions.attach_delivery_dates", side_effect=lambda _c, _o, orders: orders),
        patch("backend.management_rinse_hd.resolve_order_state", side_effect=lambda *a, **k: {"bag_id": k.get("production", {}).get("bag_id") or "KEEP1", "status": STATUS_PENDING_WASH}),
    ):
        out = build_rinse_hd_day(cursor, 3, date(2026, 8, 22), status="all")
    assert out["summary"]["pending_wash"] == 1
    bag_ids = {o.get("bag_id") for o in out.get("orders") or []}
    assert "OLD1" not in bag_ids
    assert "KEEP1" in bag_ids


    from unittest.mock import MagicMock, patch

    from backend.management_rinse_hd import (
        WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED,
        admit_discovered_hd_bags,
    )

    cursor = MagicMock()
    quarantined = {
        "id": 42,
        "bag_id": "OLD1",
        "workflow_status": WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED,
    }
    with patch("backend.management_rinse_hd.ensure_management_hd_columns"), patch(
        "backend.management_rinse_hd._load_production_by_bag",
        return_value={"OLD1": quarantined},
    ):
        out = admit_discovered_hd_bags(cursor, 3, date(2026, 8, 22), ["OLD1"])

    assert out["admitted_new"] == 0
    assert out["already_admitted"] == 0
    assert out["skipped_quarantined"] == 1
    assert out["bag_ids"] == []
    cursor.execute.assert_not_called()


def test_permanent_delete_uses_production_fact_id_column():
    cursor = MagicMock(dictionary=True)
    cursor.fetchall.return_value = [{"id": 99, "bag_id": "HD003"}]
    cursor.rowcount = 1
    with (
        patch("backend.hd_workflow_extensions.table_exists", return_value=True),
        patch("backend.hd_workflow_extensions.table_has_column", return_value=True),
    ):
        out = permanent_delete_hd_orders(cursor, 3, ["HD003"])
    assert out["ok"] is True
    audit_delete = cursor.execute.call_args_list[-2][0][0]
    assert "production_fact_id" in audit_delete
    assert "production_id" not in audit_delete.replace("production_fact_id", "")


def test_permanent_delete_only_excluded_and_not_scans():
    cursor = MagicMock(dictionary=True)
    cursor.fetchall.return_value = [{"id": 99, "bag_id": "HD003"}]
    cursor.rowcount = 1
    with patch("backend.hd_workflow_extensions.table_exists", return_value=True):
        out = permanent_delete_hd_orders(cursor, 3, ["HD003"])
    assert out["ok"] is True
    assert out["deleted"] == 1
    assert out["shared_scans_deleted"] is False
    assert "DELETE FROM hd_day_bag_production" in cursor.execute.call_args_list[-1][0][0]
