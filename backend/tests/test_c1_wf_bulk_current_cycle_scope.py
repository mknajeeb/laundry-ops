"""C1 — WF_BULK_WORKITEM_REVIEW uses current-cycle bulk evidence only."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock

from backend.rinse_bulk_workitems import (
    REASON_WF_BULK_WORKITEM_REVIEW,
    RESOLUTION_ITEMS,
    RESOLUTION_NO_CHARGE,
    _bulk_event_in_cycle_window,
    bag_bulk_review_cleared,
    load_bulk_workitem_scan_map,
)
from backend.rinse_cycle_boundary import current_cycle_event_window, resolve_current_cycle
from backend.rinse_veewash_review import expand_review_required
from backend.rinse_veewash_workload import classify_veewash_workload

D_AUG8 = date(2026, 8, 8)
D_AUG1 = date(2026, 8, 1)


def _ev(ts: datetime, purpose: str, *, bag_id: str = "BAG1", eid: int = 1, user: str = "Op"):
    return {
        "id": eid,
        "bag_id": bag_id,
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "user_name": user,
        "rack": "VeeWash Dirty" if purpose == "sent-to-vendor" else None,
    }


def _aug8_cycle_timeline(*, with_current_bulk: bool = False, cross_midnight: bool = False):
    """Reusable multi-cycle timeline: prior Aug 1 bulk + Aug 8 facility cycle."""
    rows = [
        _ev(datetime(2026, 8, 1, 6, 38), "sent-to-vendor", eid=10),
        _ev(datetime(2026, 8, 1, 9, 2), "weight-entry", eid=11),
        _ev(datetime(2026, 8, 1, 11, 20), "create-workitem-bulk", eid=1832105, user="Francis"),
        _ev(datetime(2026, 8, 1, 13, 39), "garments-reviewed", eid=12),
        _ev(datetime(2026, 8, 1, 13, 40), "weight-entry", eid=13),
    ]
    if cross_midnight:
        # Prior evening send — cycle crosses ET midnight into Aug 8.
        rows.append(_ev(datetime(2026, 8, 7, 22, 0), "sent-to-vendor", eid=20, user="Driver"))
        rows.append(_ev(datetime(2026, 8, 8, 0, 30), "move-bag", eid=21))
        anchor = datetime(2026, 8, 7, 22, 0)
    else:
        rows.append(_ev(datetime(2026, 8, 8, 7, 6), "sent-to-vendor", eid=30))
        anchor = datetime(2026, 8, 8, 7, 6)
    rows.extend(
        [
            _ev(datetime(2026, 8, 8, 9, 53), "weight-entry", eid=31, user="Francis"),
            _ev(datetime(2026, 8, 8, 13, 2), "garments-reviewed", eid=32, user="Maria"),
            _ev(datetime(2026, 8, 8, 13, 4), "weight-entry", eid=33, user="Maria"),
        ]
    )
    if with_current_bulk:
        rows.insert(
            -2,
            _ev(datetime(2026, 8, 8, 10, 15), "create-workitem-bulk", eid=99, user="Francis"),
        )
    return rows, anchor


def test_window_helper_matches_resolve_current_cycle_anchor():
    timeline, anchor = _aug8_cycle_timeline()
    cycle = resolve_current_cycle(timeline, selected_date_et=D_AUG8)
    start, end = current_cycle_event_window(timeline, selected_date_et=D_AUG8)
    assert cycle.cycle_anchor_at == anchor
    assert start == cycle.cycle_anchor_at
    assert end is None  # open cycle
    assert _bulk_event_in_cycle_window(
        datetime(2026, 8, 1, 11, 20), cycle_start=start, cycle_end_exclusive=end
    ) is False
    assert _bulk_event_in_cycle_window(
        datetime(2026, 8, 8, 10, 15), cycle_start=start, cycle_end_exclusive=end
    ) is True


def test_prior_cycle_bulk_excluded_from_scan_map():
    """1. Prior-cycle bulk + no current-cycle bulk → map empty → no WF bulk review."""
    timeline, _ = _aug8_cycle_timeline(with_current_bulk=False)
    bag = "23MQL2K3F7"
    for ev in timeline:
        ev["bag_id"] = bag

    bulk_rows = [ev for ev in timeline if "bulk" in str(ev["purpose"])]
    assert len(bulk_rows) == 1
    assert bulk_rows[0]["id"] == 1832105

    cursor = MagicMock()
    # First query: bulk purposes; second: full timeline for bags with bulk.
    cursor.fetchall.side_effect = [bulk_rows, timeline]
    cursor.execute = MagicMock()

    out = load_bulk_workitem_scan_map(
        cursor, 3, [bag], selected_date_et=D_AUG8
    )
    assert out.get(bag) is None or int((out.get(bag) or {}).get("count") or 0) == 0

    presence = {
        bag: {
            "active": 1,
            "service_type": "WF",
            "rush_flag": "RUSH",
            "portal_status": "at_vendor",
        }
    }
    entry = {
        bag: {
            "first_entry_at": datetime(2026, 8, 8, 7, 6),
            "entry_date": D_AUG8,
            "entry_source": "facility_dirty_scan",
        }
    }
    raw = classify_veewash_workload(
        selected_date_et=D_AUG8,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag={
            bag: {
                "completion_at": datetime(2026, 8, 8, 13, 4),
                "completion_date": D_AUG8,
                "completed_by": "Maria",
            }
        },
    )
    expanded = expand_review_required(
        raw,
        selected_date_et=D_AUG8,
        presence_by_bag=presence,
        entry_by_bag=entry,
        bulk_scan_by_bag=out,
    )
    assert bag not in (expanded.get("review_required") or [])
    assert REASON_WF_BULK_WORKITEM_REVIEW not in (
        (expanded.get("review_reasons_by_bag") or {}).get(bag) or []
    )
    assert bag in (expanded.get("completed_on_date") or [])


def test_current_cycle_bulk_unresolved_still_reviews():
    """2. Current-cycle bulk scan unresolved → WF bulk review remains."""
    timeline, _ = _aug8_cycle_timeline(with_current_bulk=True)
    bag = "CURBULK1"
    for ev in timeline:
        ev["bag_id"] = bag
    bulk_rows = [ev for ev in timeline if "bulk" in str(ev["purpose"])]
    cursor = MagicMock()
    cursor.fetchall.side_effect = [bulk_rows, timeline]

    out = load_bulk_workitem_scan_map(
        cursor, 3, [bag], selected_date_et=D_AUG8
    )
    assert int(out[bag]["count"]) == 1
    assert out[bag]["events"][0]["id"] == 99
    # Historical prior-cycle bulk must not be the counted event.
    assert all(e.get("id") != 1832105 for e in out[bag]["events"])

    presence = {
        bag: {
            "active": 1,
            "service_type": "WF",
            "rush_flag": "NON_RUSH",
            "portal_status": "at_vendor",
        }
    }
    entry = {
        bag: {
            "first_entry_at": datetime(2026, 8, 8, 7, 6),
            "entry_date": D_AUG8,
            "entry_source": "facility_dirty_scan",
        }
    }
    raw = classify_veewash_workload(
        selected_date_et=D_AUG8,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag={
            bag: {
                "completion_at": datetime(2026, 8, 8, 13, 4),
                "completion_date": D_AUG8,
                "completed_by": "Maria",
            }
        },
    )
    expanded = expand_review_required(
        raw,
        selected_date_et=D_AUG8,
        presence_by_bag=presence,
        entry_by_bag=entry,
        bulk_scan_by_bag=out,
    )
    assert bag in expanded["review_required"]
    assert REASON_WF_BULK_WORKITEM_REVIEW in expanded["review_reasons_by_bag"][bag]


def test_current_cycle_quantity_unresolved_keeps_review():
    """3. Current-cycle bulk workitem quantity unresolved → review remains."""
    assert bag_bulk_review_cleared(None, []) is False
    assert (
        bag_bulk_review_cleared(
            {"resolution_type": RESOLUTION_ITEMS},
            [{"quantity": 0}],
        )
        is False
    )


def test_current_cycle_resolution_clears_review():
    """4. Current-cycle resolution clears review per existing contract."""
    assert bag_bulk_review_cleared(
        {"resolution_type": RESOLUTION_ITEMS},
        [{"quantity": 2, "line_total": 8}],
    )
    assert bag_bulk_review_cleared(
        {"resolution_type": RESOLUTION_NO_CHARGE, "no_charge_reason": "customer"},
        [],
    )


def test_historical_bulk_row_not_deleted_from_source_list():
    """5. Historical bulk scan remains in chronology source list (filter only)."""
    timeline, start = _aug8_cycle_timeline()
    hist = [ev for ev in timeline if ev.get("id") == 1832105]
    assert len(hist) == 1
    assert hist[0]["scanned_at_parsed"] == datetime(2026, 8, 1, 11, 20)
    # Window filter excludes it; timeline still contains it.
    assert _bulk_event_in_cycle_window(
        hist[0]["scanned_at_parsed"],
        cycle_start=start,
        cycle_end_exclusive=None,
    ) is False


def test_same_bag_cycles_evaluated_independently():
    """6. Same bag reused across cycles — Aug 1 vs Aug 8 evaluated independently."""
    timeline, _ = _aug8_cycle_timeline(with_current_bulk=False)
    bag = "REUSE1"
    for ev in timeline:
        ev["bag_id"] = bag
    bulk_rows = [ev for ev in timeline if "bulk" in str(ev["purpose"])]

    # Aug 1 selected day: prior cycle's bulk is in-window.
    cursor_aug1 = MagicMock()
    cursor_aug1.fetchall.side_effect = [bulk_rows, timeline]
    map_aug1 = load_bulk_workitem_scan_map(
        cursor_aug1, 3, [bag], selected_date_et=D_AUG1
    )
    assert int(map_aug1[bag]["count"]) == 1
    assert map_aug1[bag]["events"][0]["id"] == 1832105

    # Aug 8 selected day: same lifetime row ignored.
    cursor_aug8 = MagicMock()
    cursor_aug8.fetchall.side_effect = [bulk_rows, timeline]
    map_aug8 = load_bulk_workitem_scan_map(
        cursor_aug8, 3, [bag], selected_date_et=D_AUG8
    )
    assert not map_aug8.get(bag)


def test_cycle_crossing_et_midnight_not_same_date_filter():
    """7. Cycle may cross ET midnight — do not use same-date filtering."""
    timeline, anchor = _aug8_cycle_timeline(cross_midnight=True, with_current_bulk=True)
    start, end = current_cycle_event_window(timeline, selected_date_et=D_AUG8)
    assert start == anchor
    assert start.date() == date(2026, 8, 7)  # prior evening
    # Bulk on Aug 8 morning is still in-cycle despite different calendar day from anchor.
    assert _bulk_event_in_cycle_window(
        datetime(2026, 8, 8, 10, 15),
        cycle_start=start,
        cycle_end_exclusive=end,
    )
    # Aug 1 bulk still out of window.
    assert not _bulk_event_in_cycle_window(
        datetime(2026, 8, 1, 11, 20),
        cycle_start=start,
        cycle_end_exclusive=end,
    )


def test_next_cycle_bound_excludes_later_trip_bulk():
    """Bulk after a later sent-to-vendor belongs to the next cycle, not this one."""
    timeline = [
        _ev(datetime(2026, 8, 8, 7, 6), "sent-to-vendor", eid=1),
        _ev(datetime(2026, 8, 8, 9, 0), "weight-entry", eid=2),
        _ev(datetime(2026, 8, 8, 10, 0), "create-workitem-bulk", eid=3),
        _ev(datetime(2026, 8, 8, 12, 0), "garments-reviewed", eid=4),
        _ev(datetime(2026, 8, 8, 12, 5), "weight-entry", eid=5),
        # Second trip same day
        _ev(datetime(2026, 8, 8, 16, 0), "sent-to-vendor", eid=6),
        _ev(datetime(2026, 8, 8, 17, 0), "create-workitem-bulk", eid=7),
    ]
    # Without as_of / with latest STV as anchor, selected day uses latest STV (16:00).
    start, end = current_cycle_event_window(timeline, selected_date_et=D_AUG8)
    assert start == datetime(2026, 8, 8, 16, 0)
    assert _bulk_event_in_cycle_window(
        datetime(2026, 8, 8, 17, 0), cycle_start=start, cycle_end_exclusive=end
    )
    assert not _bulk_event_in_cycle_window(
        datetime(2026, 8, 8, 10, 0), cycle_start=start, cycle_end_exclusive=end
    )
