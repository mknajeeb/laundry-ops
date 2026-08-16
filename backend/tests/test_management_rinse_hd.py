"""Pure-function regressions for Management Rinse HD entry/completion rules."""

from __future__ import annotations

from datetime import datetime

from backend.management_rinse_hd import (
    COMPLETION_SOURCE_MANAGEMENT,
    COMPLETION_SOURCE_SCAN,
    business_date_of,
    order_visible_on_day,
    resolve_order_state,
    select_hd_completion_event,
    select_hd_processing_entry,
)


def _ev(purpose, at, user="Op", bag="ABC", eid=1):
    return {
        "id": eid,
        "bag_id": bag,
        "purpose": purpose,
        "scanned_at_parsed": at,
        "user_name": user,
    }


def test_no_bulk_means_not_in_queue():
    events = [
        _ev("load-in", datetime(2026, 8, 15, 8, 0), eid=1),
        _ev("workitems-added", datetime(2026, 8, 15, 9, 0), eid=2),
        _ev("complete-cleaning", datetime(2026, 8, 15, 10, 0), eid=3),
    ]
    assert select_hd_processing_entry(events) is None
    assert resolve_order_state(events, service_hint="HD") is None


def test_bulk_enters_queue_and_captures_operator():
    events = [
        _ev("load-in", datetime(2026, 8, 15, 8, 0), eid=1),
        _ev("create-workitem-bulk", datetime(2026, 8, 15, 9, 0), user="Maria", eid=2),
        _ev("workitems-added", datetime(2026, 8, 15, 9, 0), eid=3),
    ]
    entry = select_hd_processing_entry(events)
    assert entry["user_name"] == "Maria"
    state = resolve_order_state(events, service_hint="HD")
    assert state["status"] == "open"
    assert state["start_operator"] == "Maria"


def test_zero_complete_cleaning_stays_open():
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 15, 9, 0), eid=1),
        _ev("workitems-added", datetime(2026, 8, 15, 9, 0), eid=2),
    ]
    assert select_hd_completion_event(events, entry_at=events[0]["scanned_at_parsed"]) is None
    assert resolve_order_state(events, service_hint="HD")["status"] == "open"


def test_one_complete_cleaning_uses_first():
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 15, 9, 0), eid=1),
        _ev("complete-cleaning", datetime(2026, 8, 15, 11, 0), user="Folder1", eid=2),
    ]
    done = select_hd_completion_event(events, entry_at=events[0]["scanned_at_parsed"])
    assert done["user_name"] == "Folder1"
    state = resolve_order_state(events, service_hint="HD")
    assert state["completion_source"] == COMPLETION_SOURCE_SCAN
    assert state["completion_operator"] == "Folder1"


def test_two_complete_cleaning_uses_second():
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 15, 9, 0), eid=1),
        _ev("complete-cleaning", datetime(2026, 8, 15, 11, 0), user="First", eid=2),
        _ev("complete-cleaning Last Scan", datetime(2026, 8, 15, 11, 30), user="Second", eid=3),
    ]
    done = select_hd_completion_event(events, entry_at=events[0]["scanned_at_parsed"])
    assert done["user_name"] == "Second"


def test_three_plus_complete_cleaning_still_second():
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 15, 9, 0), eid=1),
        _ev("complete-cleaning", datetime(2026, 8, 15, 11, 0), user="A", eid=2),
        _ev("complete-cleaning", datetime(2026, 8, 15, 11, 10), user="B", eid=3),
        _ev("complete-cleaning Last Scan", datetime(2026, 8, 15, 11, 20), user="C", eid=4),
    ]
    done = select_hd_completion_event(events, entry_at=events[0]["scanned_at_parsed"])
    assert done["user_name"] == "B"


def test_cross_day_attribution_open_monday_complete_tuesday():
    events = [
        _ev("load-in", datetime(2026, 8, 14, 8, 0), eid=1),
        _ev("create-workitem-bulk", datetime(2026, 8, 14, 15, 20), user="Op", eid=2),
        _ev("workitems-added", datetime(2026, 8, 14, 15, 20), eid=3),
        _ev("complete-cleaning", datetime(2026, 8, 15, 10, 15), user="Folder", eid=4),
        _ev("complete-cleaning Last Scan", datetime(2026, 8, 15, 10, 20), user="Folder", eid=5),
    ]
    state = resolve_order_state(
        events,
        service_hint="HD",
        production={"total_items": 8, "revenue": 42},
    )
    assert business_date_of(state["started_at"]).isoformat() == "2026-08-14"
    assert business_date_of(state["completion_at"]).isoformat() == "2026-08-15"
    assert order_visible_on_day(state, business_date_of(state["started_at"])) == "open"
    assert order_visible_on_day(state, business_date_of(state["completion_at"])) == "completed"
    # Monday open view must not count Tuesday completion
    monday = dict(state)
    assert order_visible_on_day(monday, business_date_of(state["started_at"])) == "open"


def test_management_override_when_no_source_completion():
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 15, 9, 0), eid=1),
        _ev("workitems-added", datetime(2026, 8, 15, 9, 0), eid=2),
    ]
    state = resolve_order_state(
        events,
        service_hint="HD",
        production={
            "management_completed_at": datetime(2026, 8, 15, 16, 0),
            "management_completed_by_name": "Manager",
            "total_items": 3,
            "revenue": 12,
        },
    )
    assert state["status"] == "completed"
    assert state["completion_source"] == COMPLETION_SOURCE_MANAGEMENT
    assert state["completion_operator"] == "Manager"


def test_source_completion_beats_management_override():
    events = [
        _ev("create-workitem-bulk", datetime(2026, 8, 15, 9, 0), eid=1),
        _ev("complete-cleaning", datetime(2026, 8, 15, 12, 0), user="SourceFolder", eid=2),
    ]
    state = resolve_order_state(
        events,
        service_hint="HD",
        production={
            "management_completed_at": datetime(2026, 8, 15, 11, 0),
            "management_completed_by_name": "Manager",
        },
    )
    assert state["completion_source"] == COMPLETION_SOURCE_SCAN
    assert state["completion_operator"] == "SourceFolder"


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
    entry = select_hd_processing_entry(events)
    assert entry["user_name"] == "NewOp"
    assert select_hd_completion_event(events, entry_at=entry["scanned_at_parsed"]) is None
