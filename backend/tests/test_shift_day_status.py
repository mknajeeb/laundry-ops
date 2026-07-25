"""Shift Monitor day status state machine (NOT_STARTED → OPEN → READY_TO_CLOSE)."""

from __future__ import annotations

from backend.rinse_veewash_shift_day import (
    STATUS_CLOSED,
    STATUS_NOT_STARTED,
    STATUS_OPEN,
    STATUS_READY_TO_CLOSE,
    STATUS_REOPENED,
    count_admitted_operational_workload,
    derive_shift_day_status,
)


def _summary(
    *,
    opening=0,
    added=0,
    excluded_carryin=0,
    total=None,
    active=None,
    new_today=None,
    completed=0,
    pending=0,
    review=0,
    bag_ids=None,
):
    total = opening + added if total is None else total
    active = total if active is None else active
    new_today = opening + added if new_today is None else new_today
    bags = bag_ids or {
        "new_today": [f"B{i}" for i in range(new_today)],
        "completed": [f"C{i}" for i in range(completed)] if completed and not new_today else [],
        "pending": [],
        "review_required": [],
        "carryover": [],
    }
    return {
        "active_workload": active,
        "total_workload": total,
        "completed": completed,
        "pending": pending,
        "new_today": new_today,
        "exceptions": {"review_required": review},
        "membership": {
            "opening_scrape_admit_count": opening,
            "added_during_day_count": added,
            "baseline_count": opening,
            "added_later_count": added,
            "excluded_prior_day_carryin_count": excluded_carryin,
            "total_count": opening + added,
        },
        "segments": {
            "all": {
                "active_workload": active,
                "total_workload": total,
                "completed": completed,
                "pending": pending,
                "new_today": new_today,
                "exceptions": {"review_required": review},
                "bag_ids": bags,
            },
            "wf": {
                "new_today": new_today,
                "completed": completed,
                "pending": pending,
                "exceptions": {"review_required": review},
                "bag_ids": bags,
            },
            "hd": {
                "new_today": 0,
                "completed": 0,
                "pending": 0,
                "exceptions": {"review_required": 0},
                "bag_ids": {"new_today": [], "completed": [], "pending": [], "review_required": []},
            },
        },
    }


def test_empty_day_is_not_started():
    s = _summary(opening=0, added=0, total=0, active=0, new_today=0, pending=0, review=0)
    assert derive_shift_day_status(s) == STATUS_NOT_STARTED
    assert count_admitted_operational_workload(s) == 0


def test_empty_day_with_excluded_carryins_still_not_started():
    s = _summary(
        opening=0,
        added=0,
        excluded_carryin=12,
        total=0,
        active=0,
        new_today=0,
        pending=0,
        review=0,
        bag_ids={"new_today": [], "completed": [], "pending": [], "review_required": [], "carryover": []},
    )
    assert s["membership"]["excluded_prior_day_carryin_count"] == 12
    assert count_admitted_operational_workload(s) == 0
    assert derive_shift_day_status(s) == STATUS_NOT_STARTED
    # Pending/review cleared with no work must not become READY_TO_CLOSE.
    assert derive_shift_day_status(s, current_status=STATUS_READY_TO_CLOSE) == STATUS_NOT_STARTED


def test_first_admitted_bag_opens_shift():
    s = _summary(opening=1, added=0, pending=1, review=0)
    assert derive_shift_day_status(s) == STATUS_OPEN
    s2 = _summary(opening=0, added=1, pending=0, review=1)
    assert derive_shift_day_status(s2) == STATUS_OPEN


def test_pending_cleared_but_no_work_remains_not_started():
    s = _summary(opening=0, added=0, total=0, pending=0, review=0)
    assert derive_shift_day_status(s, current_status=STATUS_OPEN) == STATUS_NOT_STARTED


def test_work_done_pending_and_review_zero_ready_to_close():
    s = _summary(
        opening=10,
        added=2,
        completed=12,
        pending=0,
        review=0,
        total=12,
        active=12,
        new_today=12,
        bag_ids={
            "new_today": [f"B{i}" for i in range(12)],
            "completed": [f"B{i}" for i in range(12)],
            "pending": [],
            "review_required": [],
            "carryover": [],
        },
    )
    assert derive_shift_day_status(s) == STATUS_READY_TO_CLOSE


def test_closed_status_not_auto_overridden():
    s = _summary(opening=5, added=0, pending=0, review=0)
    assert derive_shift_day_status(s, current_status=STATUS_CLOSED) == STATUS_CLOSED


def test_reopened_with_reviews_stays_reopened():
    s = _summary(opening=5, added=0, pending=0, review=2)
    assert derive_shift_day_status(s, current_status=STATUS_REOPENED) == STATUS_REOPENED


def test_reopened_cleared_becomes_ready_to_close():
    s = _summary(opening=5, added=0, pending=0, review=0, completed=5, total=5, active=5, new_today=5)
    assert derive_shift_day_status(s, current_status=STATUS_REOPENED) == STATUS_READY_TO_CLOSE


def test_prior_day_carryins_do_not_count_as_admitted():
    s = _summary(
        opening=0,
        added=0,
        excluded_carryin=12,
        total=0,
        active=0,
        new_today=0,
        bag_ids={"new_today": [], "completed": [], "pending": [], "review_required": [], "carryover": []},
    )
    # Even if someone stuffed carryover bag ids, admitted-today helper ignores carryover bucket.
    s["segments"]["all"]["bag_ids"]["carryover"] = [f"OLD{i}" for i in range(12)]
    assert count_admitted_operational_workload(s) == 0
    assert derive_shift_day_status(s) == STATUS_NOT_STARTED


def test_close_rejects_not_started_day():
    from unittest.mock import MagicMock, patch

    from backend.rinse_veewash_shift_day import close_shift_day

    cursor = MagicMock()
    summary = _summary(opening=0, added=0, total=0, pending=0, review=0)
    day = {"status": STATUS_NOT_STARTED}
    with patch(
        "backend.rinse_veewash_shift_day.build_or_load_step1_for_date",
        return_value=({}, summary, day),
    ):
        out = close_shift_day(
            cursor,
            3,
            __import__("datetime").date(2026, 7, 25),
            actor_user_id=1,
            actor_display_name="Admin",
        )
    assert out["ok"] is False
    assert out["error"] == "shift_not_started"
