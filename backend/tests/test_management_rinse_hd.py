"""Pure-function regressions for Management Rinse HD wash→fold→entry→Complete."""

from __future__ import annotations

from datetime import date, datetime

from backend.management_rinse_hd import (
    STATUS_AWAITING_ENTRY,
    STATUS_COMPLETE,
    STATUS_PENDING_WASH,
    STATUS_WASHED,
    _compact_order,
    business_date_of,
    derive_workflow_status,
    order_visible_on_day,
    resolve_order_state,
    select_hd_fold_event,
    select_hd_wash_event,
)


def _ev(purpose, at, user="Op", bag="ABC", eid=1):
    return {
        "id": eid,
        "bag_id": bag,
        "purpose": purpose,
        "scanned_at_parsed": at,
        "user_name": user,
    }


def test_compact_order_includes_customer_name():
    compact = _compact_order(
        {
            "bag_id": "9EH6X45CB0",
            "customer_name": "Ada Lovelace",
            "status": STATUS_AWAITING_ENTRY,
            "washed_by_name": "Maria",
            "folded_by_name": "Tarannum",
        }
    )
    assert compact["bag_id"] == "9EH6X45CB0"
    assert compact["customer_name"] == "Ada Lovelace"
    assert compact["washed_by_name"] == "Maria"
    assert compact["folded_by_name"] == "Tarannum"


def test_no_bulk_with_hd_hint_is_pending_wash():
    events = [
        _ev("load-in", datetime(2026, 8, 15, 8, 0), eid=1),
        _ev("workitems-added", datetime(2026, 8, 15, 9, 0), eid=2),
    ]
    assert select_hd_wash_event(events) is None
    state = resolve_order_state(events, service_hint="HD")
    assert state is not None
    assert state["status"] == STATUS_PENDING_WASH


def test_bulk_enters_washed_with_washer():
    events = [
        _ev("load-in", datetime(2026, 8, 15, 8, 0), eid=1),
        _ev("create-workitem-bulk", datetime(2026, 8, 15, 9, 0), user="Maria", eid=2),
        _ev("workitems-added", datetime(2026, 8, 15, 9, 0), eid=3),
    ]
    entry = select_hd_wash_event(events)
    assert entry["user_name"] == "Maria"
    state = resolve_order_state(events, service_hint="HD")
    assert state["status"] == STATUS_WASHED
    assert state["washed_by_name"] == "Maria"
    assert business_date_of(state["washed_at"]).isoformat() == "2026-08-15"


def test_zero_complete_cleaning_stays_washed():
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 15, 9, 0), eid=1),
        _ev("workitems-added", datetime(2026, 8, 15, 9, 0), eid=2),
    ]
    assert select_hd_fold_event(events, wash_at=events[0]["scanned_at_parsed"]) is None
    assert resolve_order_state(events, service_hint="HD")["status"] == STATUS_WASHED


def test_fold_moves_to_awaiting_entry():
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 15, 9, 0), user="Maria", eid=1),
        _ev("complete-cleaning", datetime(2026, 8, 15, 11, 0), user="Tarannum", eid=2),
    ]
    done = select_hd_fold_event(events, wash_at=events[0]["scanned_at_parsed"])
    assert done["user_name"] == "Tarannum"
    state = resolve_order_state(events, service_hint="HD")
    assert state["status"] == STATUS_AWAITING_ENTRY
    assert state["folded_by_name"] == "Tarannum"
    assert state["washed_by_name"] == "Maria"


def test_two_complete_cleaning_uses_second():
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 15, 9, 0), eid=1),
        _ev("complete-cleaning", datetime(2026, 8, 15, 11, 0), user="First", eid=2),
        _ev("complete-cleaning Last Scan", datetime(2026, 8, 15, 11, 30), user="Second", eid=3),
    ]
    done = select_hd_fold_event(events, wash_at=events[0]["scanned_at_parsed"])
    assert done["user_name"] == "Second"


def test_three_plus_complete_cleaning_still_second():
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 15, 9, 0), eid=1),
        _ev("complete-cleaning", datetime(2026, 8, 15, 11, 0), user="A", eid=2),
        _ev("complete-cleaning", datetime(2026, 8, 15, 11, 10), user="B", eid=3),
        _ev("complete-cleaning Last Scan", datetime(2026, 8, 15, 11, 20), user="C", eid=4),
    ]
    done = select_hd_fold_event(events, wash_at=events[0]["scanned_at_parsed"])
    assert done["user_name"] == "B"


def test_cross_day_wash_fold_revenue_on_fold_date():
    events = [
        _ev("load-in", datetime(2026, 8, 21, 8, 0), eid=1),
        _ev("create-workitem-bulk", datetime(2026, 8, 21, 15, 20), user="Maria", eid=2),
        _ev("workitems-added", datetime(2026, 8, 21, 15, 20), eid=3),
        _ev("complete-cleaning", datetime(2026, 8, 22, 10, 15), user="Tarannum", eid=4),
        _ev("complete-cleaning Last Scan", datetime(2026, 8, 22, 10, 20), user="Tarannum", eid=5),
    ]
    state = resolve_order_state(
        events,
        service_hint="HD",
        production={"total_items": 8, "revenue": 42},
        activation_date=date(2026, 8, 21),
    )
    assert state["status"] == STATUS_AWAITING_ENTRY
    assert business_date_of(state["washed_at"]).isoformat() == "2026-08-21"
    assert business_date_of(state["folded_at"]).isoformat() == "2026-08-22"
    assert state["revenue_date_et"].isoformat() == "2026-08-22"
    assert order_visible_on_day(state, date(2026, 8, 22)) == STATUS_AWAITING_ENTRY
    assert state["status"] != STATUS_COMPLETE


def test_activation_cutoff_ignores_pre_activation_wash_fold():
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 15, 9, 0), user="Old", eid=1),
        _ev("complete-cleaning", datetime(2026, 8, 15, 12, 0), user="OldFold", eid=2),
        _ev("workitems-added", datetime(2026, 8, 15, 9, 0), eid=3),
    ]
    state = resolve_order_state(
        events,
        service_hint="HD",
        activation_date=date(2026, 8, 21),
    )
    assert state is not None
    assert state["status"] == STATUS_PENDING_WASH
    assert state["washed_at"] is None
    assert state["folded_at"] is None
    assert order_visible_on_day(state, date(2026, 8, 20)) is None
    assert order_visible_on_day(state, date(2026, 8, 21)) == STATUS_PENDING_WASH


def test_explicit_complete_required():
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 15, 9, 0), eid=1),
        _ev("complete-cleaning", datetime(2026, 8, 15, 12, 0), user="Folder", eid=2),
    ]
    state = resolve_order_state(
        events,
        service_hint="HD",
        production={
            "total_items": 3,
            "revenue": 12,
            "management_completed_at": datetime(2026, 8, 15, 16, 0),
            "management_completed_by_name": "Manager",
            "workflow_status": "complete",
            "status": "COMPLETE",
        },
    )
    assert state["status"] == STATUS_COMPLETE


def test_draft_items_do_not_complete():
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 15, 9, 0), eid=1),
        _ev("complete-cleaning", datetime(2026, 8, 15, 12, 0), user="Folder", eid=2),
    ]
    state = resolve_order_state(
        events,
        service_hint="HD",
        production={"total_items": 3, "revenue": 12, "status": "PARTIALLY_RECORDED"},
    )
    assert state["status"] == STATUS_AWAITING_ENTRY


def test_derive_workflow_status_matrix():
    assert (
        derive_workflow_status(washed_at=None, folded_at=None, explicitly_complete=False)
        == STATUS_PENDING_WASH
    )
    assert (
        derive_workflow_status(
            washed_at=datetime(2026, 8, 15, 9),
            folded_at=None,
            explicitly_complete=False,
        )
        == STATUS_WASHED
    )
    assert (
        derive_workflow_status(
            washed_at=datetime(2026, 8, 15, 9),
            folded_at=datetime(2026, 8, 15, 11),
            explicitly_complete=False,
        )
        == STATUS_AWAITING_ENTRY
    )
    assert (
        derive_workflow_status(
            washed_at=datetime(2026, 8, 15, 9),
            folded_at=datetime(2026, 8, 15, 11),
            explicitly_complete=True,
        )
        == STATUS_COMPLETE
    )


def test_prior_cycle_bulk_ignored_after_new_load_in():
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 1, 9, 0), user="Old", eid=1),
        _ev("complete-cleaning", datetime(2026, 8, 1, 12, 0), eid=2),
        _ev("complete-cleaning Last Scan", datetime(2026, 8, 1, 12, 5), eid=3),
        _ev("bag-picked-up", datetime(2026, 8, 14, 20, 0), eid=4),
        _ev("load-in", datetime(2026, 8, 14, 22, 0), eid=5),
        _ev("create-workitem-bulk", datetime(2026, 8, 15, 18, 0), user="NewOp", eid=6),
        _ev("workitems-added", datetime(2026, 8, 15, 18, 0), eid=7),
    ]
    entry = select_hd_wash_event(events)
    assert entry["user_name"] == "NewOp"
    assert select_hd_fold_event(events, wash_at=entry["scanned_at_parsed"]) is None


def test_durable_pending_stays_visible_after_admission_day():
    """Incomplete admitted pending_wash remains on later days until Complete."""
    state = {
        "bag_id": "DUR1",
        "status": STATUS_PENDING_WASH,
        "washed_at": None,
        "folded_at": None,
        "operations_date_et": date(2026, 8, 21),
    }
    assert order_visible_on_day(state, date(2026, 8, 21)) == STATUS_PENDING_WASH
    assert order_visible_on_day(state, date(2026, 8, 22)) == STATUS_PENDING_WASH
    assert order_visible_on_day(state, date(2026, 8, 20)) is None


def test_hd_service_hints_include_presence_discovery():
    from unittest.mock import MagicMock, patch

    from backend.management_rinse_hd import _load_hd_service_hints

    cursor = MagicMock()
    cursor.fetchall.return_value = []
    with patch("backend.management_rinse_hd.table_exists", return_value=True), patch(
        "backend.management_rinse_hd._load_hd_portal_bags_for_day",
        return_value={"HDPRES1"},
    ):
        hints = _load_hd_service_hints(cursor, 3, date(2026, 9, 1))
    assert hints == {"HDPRES1": "HD"}


def test_build_hd_day_admits_presence_discovered_bag():
    from unittest.mock import MagicMock, patch

    from backend.management_rinse_hd import build_rinse_hd_day

    cursor = MagicMock()
    with (
        patch("backend.management_rinse_hd.table_exists", return_value=True),
        patch("backend.management_rinse_hd.ensure_management_hd_columns"),
        patch(
            "backend.hd_workflow_extensions.hd_workflow_cutoff",
            return_value=(date(2026, 8, 21), None),
        ),
        patch(
            "backend.management_rinse_hd._load_hd_service_hints",
            return_value={"HDPRES2": "HD"},
        ),
        patch(
            "backend.management_rinse_hd.admit_discovered_hd_bags",
            return_value={"admitted_new": 1, "already_admitted": 0, "bag_ids": ["HDPRES2"]},
        ) as admit,
        patch("backend.management_rinse_hd._load_active_admitted_bag_ids", return_value=set()),
        patch("backend.management_rinse_hd._load_candidate_events_for_bags", return_value=[]),
        patch("backend.management_rinse_hd._load_production_by_bag", return_value={}),
        patch("backend.management_rinse_hd._load_user_maps", return_value={}),
        patch("backend.management_rinse_hd._load_hd_presence_meta", return_value={}),
    ):
        build_rinse_hd_day(cursor, 3, date(2026, 9, 1), status="all")
    admit.assert_called_once()
    assert "HDPRES2" in admit.call_args[0][3]


def test_admit_discovered_writes_pending_and_is_idempotent():
    from unittest.mock import MagicMock, patch

    from backend.management_rinse_hd import admit_discovered_hd_bags

    cursor = MagicMock()
    # First call: no existing row → create. Second: existing row → already admitted.
    existing_row = {
        "id": 9,
        "bag_id": "NEW1",
        "workflow_status": STATUS_PENDING_WASH,
        "operations_date_et": date(2026, 8, 21),
        "admitted_at": datetime(2026, 8, 21, 8, 0),
    }

    with patch("backend.management_rinse_hd.ensure_management_hd_columns"), patch(
        "backend.management_rinse_hd.table_exists", return_value=True
    ), patch(
        "backend.management_rinse_hd.table_has_column", return_value=True
    ), patch(
        "backend.management_rinse_hd._load_production_by_bag",
        side_effect=[{}, {"NEW1": existing_row}, {"NEW1": existing_row}],
    ):
        first = admit_discovered_hd_bags(cursor, 3, date(2026, 8, 21), ["NEW1"])
        second = admit_discovered_hd_bags(cursor, 3, date(2026, 8, 21), ["NEW1"])

    assert first["admitted_new"] == 1
    assert first["bag_ids"] == ["NEW1"]
    assert second["admitted_new"] == 0
    assert second["already_admitted"] == 1
    assert cursor.execute.called


def test_active_admitted_includes_incomplete_without_selected_day_match():
    from unittest.mock import MagicMock, patch

    from backend.management_rinse_hd import _load_active_admitted_bag_ids

    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {
            "bag_id": "KEEP1",
            "workflow_status": STATUS_PENDING_WASH,
            "management_completed_at": None,
            "operations_date_et": date(2026, 8, 21),
            "washed_at": None,
            "folded_at": None,
        },
        {
            "bag_id": "DONE1",
            "workflow_status": STATUS_COMPLETE,
            "management_completed_at": datetime(2026, 8, 21, 18, 0),
            "operations_date_et": date(2026, 8, 21),
            "washed_at": datetime(2026, 8, 21, 10, 0),
            "folded_at": datetime(2026, 8, 21, 12, 0),
        },
    ]
    with patch("backend.management_rinse_hd.ensure_management_hd_columns"), patch(
        "backend.management_rinse_hd.table_exists", return_value=True
    ):
        # Next day: incomplete KEEP1 still active; complete DONE1 not on Aug 22.
        ids = _load_active_admitted_bag_ids(cursor, 3, date(2026, 8, 22))
    assert "KEEP1" in ids
    assert "DONE1" not in ids


def test_hd_performance_credits_wash_fold_not_complete_date():
    """Wash/fold performance uses operation timestamps, never Complete/revenue-entry date."""
    from unittest.mock import MagicMock, patch

    from backend.management_hd_performance import build_hd_employee_performance

    washed_at = datetime(2026, 8, 21, 10, 0)
    folded_at = datetime(2026, 8, 22, 11, 0)
    row = {
        "bag_id": "HD1",
        "washed_by_user_id": 10,
        "washed_by_name_snapshot": "Maria",
        "washed_at": washed_at,
        "folded_by_user_id": 20,
        "folded_by_name_snapshot": "Tarannum",
        "folded_at": folded_at,
        "total_items": 8,
        "revenue": 42.0,
        "operations_date_et": date(2026, 8, 22),
        "workflow_status": "COMPLETE",
        "status": "COMPLETE",
    }
    cursor = MagicMock()
    cursor.fetchall.return_value = [row]

    with patch("backend.management_hd_performance.table_exists", return_value=True), patch(
        "backend.management_hd_performance.ensure_management_hd_columns"
    ), patch(
        "backend.management_hd_performance._batch_user_names",
        return_value={10: "Maria", 20: "Tarannum"},
    ):
        wash_day = build_hd_employee_performance(cursor, 3, date(2026, 8, 21))
        fold_day = build_hd_employee_performance(cursor, 3, date(2026, 8, 22))
        complete_only = build_hd_employee_performance(cursor, 3, date(2026, 8, 23))
        pre_activation = build_hd_employee_performance(cursor, 3, date(2026, 8, 15))

    wash_by = {e["user_id"]: e for e in wash_day["employees"]}
    assert wash_by[10]["wash_count"] == 1
    assert wash_by[10]["fold_count"] == 0
    assert wash_by[10]["wash_bags"][0]["bag_id"] == "HD1"
    assert 20 not in wash_by

    fold_by = {e["user_id"]: e for e in fold_day["employees"]}
    assert fold_by[20]["fold_count"] == 1
    assert fold_by[20]["wash_count"] == 0
    assert fold_by[20]["items_on_fold"] == 8
    assert fold_by[20]["revenue_on_fold"] == 42.0
    assert 10 not in fold_by

    assert complete_only["employees"] == []
    assert pre_activation["employees"] == []
