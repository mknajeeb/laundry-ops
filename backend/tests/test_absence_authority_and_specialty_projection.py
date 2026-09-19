"""Absence authority and completed-bag Specialty projection."""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from backend.management_rinse_wf_review import authoritative_wf_bulk_review_ids
from backend.rinse_cleaner_ticket_presence import (
    PORTAL_STATUS_AT_VENDOR,
    absence_deactivation_permitted,
    apply_presence_scrape,
)
from backend.rinse_scrape_completeness import (
    STATE_CONFIRMED,
    generation_identity_allows_absence,
)
from backend.rinse_veewash_review import expand_review_required
from backend.rinse_veewash_workload import REASON_WF_BULK_WORKITEM_REVIEW
from backend.rinse_wf_disappeared_from_portal import (
    _pick_first_establishing_from_candidates,
    qualify_disappeared_from_portal_bags,
)
from backend.tests.test_rinse_cleaner_ticket_presence import (
    TestPresenceApplyDryRun,
    _with_apply_patches,
)


def _ship_meta() -> dict:
    return {
        "source_mode": "ship_to_vendor_window",
        "absence_capable": False,
        "full_traverse": True,
        "stopped_reason": "no_next_page_ui",
        "pages_scraped": 7,
    }


def _absence_capable_meta() -> dict:
    return {
        "absence_capable": True,
        "source_inspected_complete": True,
        "stopped_reason": "no_next_page_ui",
        "full_traverse": True,
    }


def test_absence_capable_false_blocks_even_below_population_floor():
    permitted, reason, _detail = absence_deactivation_permitted(
        _ship_meta(),
        prior_active_ids={"A", "B"},
        seen_ids={"A"},
    )
    assert permitted is False
    assert reason == "absence_not_authoritative"


def test_zero_overlap_on_large_board_is_generation_discontinuity():
    prior = {f"OLD{i:03d}" for i in range(60)}
    seen = {f"NEW{i:03d}" for i in range(60)}
    allowed, detail = generation_identity_allows_absence(prior_ids=prior, seen_ids=seen)
    assert allowed is False
    assert detail["retained_fraction"] == 0.0
    permitted, reason, _detail = absence_deactivation_permitted(
        _absence_capable_meta(),
        prior_active_ids=prior,
        seen_ids=seen,
    )
    assert permitted is False
    assert reason == "generation_discontinuity"


def test_ordinary_small_departure_still_allowed():
    prior = {f"B{i:03d}" for i in range(140)}
    seen = set(prior)
    seen.remove("B000")
    seen.remove("B001")
    allowed, detail = generation_identity_allows_absence(prior_ids=prior, seen_ids=seen)
    assert allowed is True
    assert detail["retained_fraction"] > 0.95
    permitted, reason, _detail = absence_deactivation_permitted(
        _absence_capable_meta(),
        prior_active_ids=prior,
        seen_ids=seen,
    )
    assert permitted is True
    assert reason == ""


def test_small_board_is_not_gated_by_overlap():
    allowed, detail = generation_identity_allows_absence(
        prior_ids={"A", "B", "C"},
        seen_ids={"D"},
    )
    assert allowed is True
    assert detail["reason"] == "prior_below_floor"


@_with_apply_patches
def test_apply_ship_window_does_not_mark_missing():
    cursor = TestPresenceApplyDryRun()._mock_cursor_with_table()
    apply_presence_scrape(
        cursor,
        10,
        portal_status=PORTAL_STATUS_AT_VENDOR,
        rows=[{"bag_id": "KEEP"}, {"bag_id": "GONE"}],
        scrape_meta=_ship_meta(),
        dry_run=False,
    )
    stats = apply_presence_scrape(
        cursor,
        10,
        portal_status=PORTAL_STATUS_AT_VENDOR,
        rows=[{"bag_id": "KEEP"}],
        scrape_meta=_ship_meta(),
        mark_missing=True,
        dry_run=False,
    )
    assert stats.get("rows_missing") in (0, None)
    assert stats.get("mark_missing_skipped") is True
    assert cursor._store[(10, "GONE")]["active"] == 1


@_with_apply_patches
def test_apply_absence_capable_still_deactivates_one_bag():
    cursor = TestPresenceApplyDryRun()._mock_cursor_with_table()
    apply_presence_scrape(
        cursor,
        10,
        portal_status=PORTAL_STATUS_AT_VENDOR,
        rows=[{"bag_id": "KEEP"}, {"bag_id": "GONE"}],
        scrape_meta=_absence_capable_meta(),
        dry_run=False,
    )
    stats = apply_presence_scrape(
        cursor,
        10,
        portal_status=PORTAL_STATUS_AT_VENDOR,
        rows=[{"bag_id": "KEEP"}],
        scrape_meta=_absence_capable_meta(),
        mark_missing=True,
        dry_run=False,
    )
    assert stats["rows_missing"] == 1
    assert cursor._store[(10, "GONE")]["active"] == 0


def test_picker_skips_absence_incapable_run():
    picked = _pick_first_establishing_from_candidates(
        [
            {
                "id": 1,
                "status": "success",
                "rows_found": 141,
                "scrape_meta": {
                    **_ship_meta(),
                    "completeness_guard": {"allow_mark_missing": True},
                },
            },
            {
                "id": 2,
                "status": "success",
                "rows_found": 140,
                "scrape_meta": _absence_capable_meta(),
            },
        ],
        present_run_ids=set(),
    )
    assert picked is not None
    assert picked["id"] == 2


def test_absence_capable_open_oi_still_qualifies():
    oi = {
        "bag_id": "LEGIT",
        "order_instance_id": 1,
        "cycle_anchor_at": datetime(2026, 9, 18, 8, 0),
        "completed_at": None,
        "service_type": "WF",
    }
    with (
        patch(
            "backend.rinse_wf_disappeared_from_portal._load_inactive_presence_for_bags",
            return_value={"LEGIT": {"bag_id": "LEGIT", "active": 0}},
        ),
        patch(
            "backend.rinse_wf_disappeared_from_portal.build_disappearance_confirmation",
            return_value={
                "LEGIT": {
                    "state": STATE_CONFIRMED,
                    "trustworthy_absent_runs": 2,
                    "absent_run_ids": [9],
                }
            },
        ),
        patch(
            "backend.rinse_wf_disappeared_from_portal._last_present_run_ids",
            return_value={"LEGIT": 8},
        ),
        patch(
            "backend.rinse_wf_disappeared_from_portal._first_establishing_absence_runs_bulk",
            return_value={"LEGIT": {"id": 9, "scrape_meta": _absence_capable_meta()}},
        ),
    ):
        out = qualify_disappeared_from_portal_bags(MagicMock(), 3, [oi])
    assert "LEGIT" in out


def _expand_bulk(bag: str, *, completed: bool, service: str = "WF", wia: bool = False):
    shell = {
        "rows": [{"bag_id": bag, "service_type": service, "canonical_status": "completed" if completed else "pending"}],
        "new_today": [] if completed else [bag],
        "carryover": [],
        "completed_on_date": [bag] if completed else [],
        "pending_end_of_date": [] if completed else [bag],
        "review_required": [],
    }
    return expand_review_required(
        shell,
        selected_date_et=date(2026, 9, 18),
        presence_by_bag={
            bag: {"bag_id": bag, "service_type": service, "active": 1}
        },
        entry_by_bag={bag: {"entry_date": date(2026, 9, 18)}},
        wia_by_bag={bag: {"first_entry_at": datetime(2026, 9, 18, 9, 0)}} if wia else {},
        bulk_scan_by_bag={
            bag: {"count": 1, "first_at": datetime(2026, 9, 18, 8, 0), "events": []}
        },
    )


def test_completed_wf_bulk_enters_specialty_review():
    out = _expand_bulk("WF1", completed=True)
    assert REASON_WF_BULK_WORKITEM_REVIEW in (out["review_reasons_by_bag"].get("WF1") or [])
    again = expand_review_required(
        out,
        selected_date_et=date(2026, 9, 18),
        presence_by_bag={"WF1": {"bag_id": "WF1", "service_type": "WF", "active": 1}},
        entry_by_bag={"WF1": {"entry_date": date(2026, 9, 18)}},
        bulk_scan_by_bag={
            "WF1": {"count": 1, "first_at": datetime(2026, 9, 18, 8, 0), "events": []}
        },
    )
    assert again["review_reasons_by_bag"]["WF1"] == out["review_reasons_by_bag"]["WF1"]


def test_hd_bulk_does_not_enter_wf_specialty():
    out = _expand_bulk("HD1", completed=True, service="HD", wia=True)
    assert REASON_WF_BULK_WORKITEM_REVIEW not in (out["review_reasons_by_bag"].get("HD1") or [])


def test_pre_epoch_bulk_scan_is_excluded_and_query_is_batched():
    cursor = MagicMock()
    cursor.fetchall.return_value = [{"bag_id": "OLDBAG1"}, {"bag_id": "NEWBAG1"}]
    epoch = datetime(2026, 9, 18, 2, 43, 15, tzinfo=timezone.utc)
    scans = {
        "OLDBAG1": {
            "count": 1,
            "first_at": datetime(2026, 9, 17, 8, 0),
            "events": [{"scanned_at_parsed": datetime(2026, 9, 17, 8, 0)}],
        },
        "NEWBAG1": {
            "count": 1,
            "first_at": datetime(2026, 9, 18, 8, 0),
            "events": [{"scanned_at_parsed": datetime(2026, 9, 18, 8, 0)}],
        },
    }
    with (
        patch(
            "backend.ta_helpers.table_exists",
            return_value=True,
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bulk_workitem_scan_map",
            return_value=scans,
        ) as scan_load,
        patch(
            "backend.rinse_bulk_workitems.load_bag_bulk_lines",
            return_value={},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bulk_resolutions",
            return_value={},
        ),
        patch(
            "backend.wf_ops_reset_epoch.get_wf_reset_epoch_at",
            return_value=epoch,
        ),
    ):
        first = authoritative_wf_bulk_review_ids(cursor, 3, date(2026, 9, 18))
        second = authoritative_wf_bulk_review_ids(cursor, 3, date(2026, 9, 18))
    assert first == ["NEWBAG1"]
    assert second == first
    assert scan_load.call_count == 2
    assert cursor.execute.call_count == 2


def test_split_pending_excludes_unconfirmed_and_review():
    from backend.rinse_wf_presence_unconfirmed import split_pending_and_unconfirmed

    pending, unconfirmed = split_pending_and_unconfirmed(
        ["SEEN1", "GONE1", "REVW1", "GONE2"],
        review_ids=["REVW1"],
        latest_seen=["SEEN1"],
    )
    assert pending == {"SEEN1"}
    assert unconfirmed == {"GONE1", "GONE2"}
    assert pending & unconfirmed == set()
    assert "REVW1" not in pending and "REVW1" not in unconfirmed


@_with_apply_patches
def test_run_8583_to_8584_zero_overlap_ship_window_leaves_board_and_unconfirmed():
    """Reproduce presence run 8583 → 8584: ~same row count, zero overlap,
    full_traverse=true, absence_capable=false.

    Old board must not be marked absent. Seen new-generation bags may be
    admitted. Prior open OIs project as Presence Unconfirmed, not Missing.
    """
    from backend.rinse_wf_presence_unconfirmed import split_pending_and_unconfirmed

    cursor = TestPresenceApplyDryRun()._mock_cursor_with_table()
    prior = [f"OLD{i:03d}" for i in range(60)]
    new = [f"NEW{i:03d}" for i in range(59)]
    apply_presence_scrape(
        cursor,
        10,
        portal_status=PORTAL_STATUS_AT_VENDOR,
        rows=[{"bag_id": bid} for bid in prior],
        scrape_meta=_absence_capable_meta(),
        dry_run=False,
    )
    stats = apply_presence_scrape(
        cursor,
        10,
        portal_status=PORTAL_STATUS_AT_VENDOR,
        rows=[{"bag_id": bid} for bid in new],
        scrape_meta=_ship_meta(),
        mark_missing=True,
        dry_run=False,
    )
    assert stats.get("mark_missing_skipped") is True
    assert stats.get("mark_missing_skip_reason") == "absence_not_authoritative"
    assert stats.get("rows_missing") in (0, None)
    for bid in prior:
        assert cursor._store[(10, bid)]["active"] == 1
    for bid in new:
        assert cursor._store[(10, bid)]["active"] == 1

    open_ois = list(prior) + ["NEW000"]
    review = set()  # no mass Missing
    pending, unconfirmed = split_pending_and_unconfirmed(
        open_ois,
        review_ids=review,
        latest_seen=new,
    )
    assert pending == {"NEW000"}
    assert unconfirmed == set(prior)
    assert pending & unconfirmed == set()
    assert not any(bid in review for bid in prior)


@_with_apply_patches
def test_absence_capable_recovery_after_ship_window_discontinuity():
    """After a ship-window zero-overlap scrape, a later absence-capable scrape
    may deactivate the prior board and admit the recovery generation.
    """
    from backend.rinse_wf_presence_unconfirmed import split_pending_and_unconfirmed

    cursor = TestPresenceApplyDryRun()._mock_cursor_with_table()
    prior = [f"OLD{i:03d}" for i in range(60)]
    mid = [f"MID{i:03d}" for i in range(59)]
    apply_presence_scrape(
        cursor,
        10,
        portal_status=PORTAL_STATUS_AT_VENDOR,
        rows=[{"bag_id": bid} for bid in prior],
        scrape_meta=_absence_capable_meta(),
        dry_run=False,
    )
    apply_presence_scrape(
        cursor,
        10,
        portal_status=PORTAL_STATUS_AT_VENDOR,
        rows=[{"bag_id": bid} for bid in mid],
        scrape_meta=_ship_meta(),
        mark_missing=True,
        dry_run=False,
    )
    # Identity prior is the preceding snapshot (mid), not the union of
    # still-active OLD+MID. retained(mid∩recovery)/|mid| is ~0, so a naive
    # mid→recovery compare would block. Use a recovery that retains the mid
    # board almost entirely and drops only the unresolved OLD generation that
    # was never on mid — i.e. recovery ≈ mid with one ordinary departure.
    recovery_board = list(mid)
    recovery_board.remove("MID000")
    stats = apply_presence_scrape(
        cursor,
        10,
        portal_status=PORTAL_STATUS_AT_VENDOR,
        rows=[{"bag_id": bid} for bid in recovery_board],
        scrape_meta=_absence_capable_meta(),
        mark_missing=True,
        dry_run=False,
    )
    assert stats.get("mark_missing_skipped") in (None, False)
    assert cursor._store[(10, "MID000")]["active"] == 0
    # OLD bags were never on the mid snapshot; absence-capable recovery vs
    # preceding mid board may deactivate them because they are still active.
    for bid in prior:
        assert cursor._store[(10, bid)]["active"] == 0
    for bid in recovery_board:
        assert cursor._store[(10, bid)]["active"] == 1

    open_ois = list(prior) + ["MID001", "MID000"]
    # MID000 is authoritatively absent → Review/Missing in real path.
    review = {"MID000"}
    pending, unconfirmed = split_pending_and_unconfirmed(
        open_ois,
        review_ids=review,
        latest_seen=recovery_board,
    )
    assert pending == {"MID001"}
    assert "MID000" not in pending and "MID000" not in unconfirmed
    # After authoritative deactivation, unresolved OLD bags that are still
    # open and not Missing stay Presence Unconfirmed (not Pending).
    assert set(prior) == unconfirmed
    assert pending & unconfirmed == set()
