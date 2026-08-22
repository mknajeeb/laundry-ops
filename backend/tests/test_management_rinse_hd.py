"""Pure-function regressions for Management Rinse HD wash→fold→entry→Complete."""

from __future__ import annotations

from datetime import date, datetime

from backend.management_rinse_hd import (
    STATUS_AWAITING_ENTRY,
    STATUS_COMPLETE,
    STATUS_PENDING_WASH,
    STATUS_WASHED,
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
        _ev("load-in", datetime(2026, 8, 14, 8, 0), eid=1),
        _ev("create-workitem-bulk", datetime(2026, 8, 14, 15, 20), user="Maria", eid=2),
        _ev("workitems-added", datetime(2026, 8, 14, 15, 20), eid=3),
        _ev("complete-cleaning", datetime(2026, 8, 15, 10, 15), user="Tarannum", eid=4),
        _ev("complete-cleaning Last Scan", datetime(2026, 8, 15, 10, 20), user="Tarannum", eid=5),
    ]
    state = resolve_order_state(
        events,
        service_hint="HD",
        production={"total_items": 8, "revenue": 42},
    )
    assert state["status"] == STATUS_AWAITING_ENTRY
    assert business_date_of(state["washed_at"]).isoformat() == "2026-08-14"
    assert business_date_of(state["folded_at"]).isoformat() == "2026-08-15"
    assert state["revenue_date_et"].isoformat() == "2026-08-15"
    assert order_visible_on_day(state, date(2026, 8, 15)) == STATUS_AWAITING_ENTRY
    assert state["status"] != STATUS_COMPLETE


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
