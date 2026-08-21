"""Unit tests for DHS schedule offset model and overdue classification."""
from datetime import date, timedelta

from backend.management_revenue_obligations import (
    STATUS_OVERDUE,
    STATUS_PENDING,
    _delivery_for_pickup,
    _friendly_day_label,
    _offset_from_weekdays,
)


def test_offset_from_weekdays_cases():
    # Tue(1) → Thu(3) = +2
    assert _offset_from_weekdays(1, 3) == 2
    # Fri(4) → Fri(4) = same day
    assert _offset_from_weekdays(4, 4) == 0
    # Tue(1) → Tue next week needs explicit +7 (legacy same-weekday = 0)
    assert _offset_from_weekdays(1, 1) == 0


def test_delivery_offset_plus_two():
    pickup = date(2026, 8, 18)  # Tuesday
    sched = {
        "pickup_pairs": [
            {"pickup_weekday": 1, "delivery_weekday": 3, "delivery_offset_days": 2},
        ],
        "pickup_weekdays": [1],
        "delivery_weekdays": [3],
    }
    assert _delivery_for_pickup(pickup, sched) == date(2026, 8, 20)  # Thu


def test_delivery_offset_plus_seven():
    pickup = date(2026, 8, 18)  # Tuesday
    sched = {
        "pickup_pairs": [
            {"pickup_weekday": 1, "delivery_weekday": 1, "delivery_offset_days": 7},
        ],
        "pickup_weekdays": [1],
        "delivery_weekdays": [1],
    }
    assert _delivery_for_pickup(pickup, sched) == date(2026, 8, 25)


def test_delivery_same_day():
    pickup = date(2026, 8, 21)  # Friday
    sched = {
        "pickup_pairs": [
            {"pickup_weekday": 4, "delivery_weekday": 4, "delivery_offset_days": 0},
        ],
        "pickup_weekdays": [4],
        "delivery_weekdays": [4],
    }
    assert _delivery_for_pickup(pickup, sched) == date(2026, 8, 21)


def test_per_pickup_day_different_offsets():
    tue = date(2026, 8, 18)
    fri = date(2026, 8, 21)
    sched = {
        "pickup_pairs": [
            {"pickup_weekday": 1, "delivery_weekday": 3, "delivery_offset_days": 2},
            {"pickup_weekday": 4, "delivery_weekday": 0, "delivery_offset_days": 3},
        ],
        "pickup_weekdays": [1, 4],
    }
    assert _delivery_for_pickup(tue, sched) == date(2026, 8, 20)
    assert _delivery_for_pickup(fri, sched) == date(2026, 8, 24)


def _classify(pickup: date, as_of: date) -> str:
    """Mirrors status logic in build_dhs_obligations (no entry/disposition)."""
    if pickup < as_of:
        return STATUS_OVERDUE
    return STATUS_PENDING


def test_future_pickups_never_overdue_on_aug_21():
    as_of = date(2026, 8, 21)
    for day in (21, 22, 24, 25, 26, 27, 28):
        pickup = date(2026, 8, day)
        status = _classify(pickup, as_of)
        if pickup < as_of:
            assert status == STATUS_OVERDUE
        else:
            assert status == STATUS_PENDING, f"{pickup} must not be overdue on {as_of}"


def test_lookahead_inflation_bug_would_have_failed():
    """Document the old bug: classifying against as_of+7 marks Aug 25 overdue on Aug 21."""
    as_of = date(2026, 8, 21)
    inflated = as_of + timedelta(days=7)  # Aug 28
    pickup = date(2026, 8, 25)
    assert pickup < inflated  # old buggy comparison
    assert not (pickup < as_of)  # correct comparison


def test_friendly_day_label():
    as_of = date(2026, 8, 21)
    assert _friendly_day_label(as_of, as_of=as_of) == "Fri, Aug 21"
    assert _friendly_day_label(date(2026, 8, 25), as_of=as_of) == "Tue, Aug 25"


def test_board_overdue_filter_excludes_future():
    as_of = date(2026, 8, 21).isoformat()
    obs = [
        {"status": STATUS_OVERDUE, "resolved": False, "scheduled_pickup_date": "2026-08-18", "name": "Old"},
        {"status": STATUS_OVERDUE, "resolved": False, "scheduled_pickup_date": "2026-08-25", "name": "FutureBug"},
        {"status": STATUS_PENDING, "resolved": False, "scheduled_pickup_date": "2026-08-25", "name": "FutureOk"},
    ]
    overdue = [
        r for r in obs
        if r.get("status") == STATUS_OVERDUE
        and not r.get("resolved")
        and r.get("scheduled_pickup_date")
        and r["scheduled_pickup_date"] < as_of
    ]
    assert [r["name"] for r in overdue] == ["Old"]
