"""Lifecycle classification for DHS occurrence cards."""
from datetime import date

from backend.management_revenue_obligations import _dhs_lifecycle


def test_upcoming_before_pickup():
    as_of = date(2026, 8, 21)
    life = _dhs_lifecycle(date(2026, 8, 25), date(2026, 8, 27), as_of)
    assert life["lifecycle"] == "upcoming"
    assert life["lifecycle_label"] == "Upcoming"


def test_due_between_pickup_and_delivery():
    as_of = date(2026, 8, 21)
    # pickup Aug 18, delivery Aug 27 — yesterday pickup, future delivery
    life = _dhs_lifecycle(date(2026, 8, 18), date(2026, 8, 27), as_of)
    assert life["lifecycle"] == "due"
    assert life["lifecycle_label"] == "Due"


def test_pickup_today_in_due():
    as_of = date(2026, 8, 25)
    life = _dhs_lifecycle(date(2026, 8, 25), date(2026, 8, 27), as_of)
    assert life["lifecycle"] == "due"
    assert life["pickup_today"] is True
    assert life["lifecycle_label"] == "Pickup Today"


def test_delivery_today_in_due():
    as_of = date(2026, 8, 27)
    life = _dhs_lifecycle(date(2026, 8, 25), date(2026, 8, 27), as_of)
    assert life["lifecycle"] == "due"
    assert life["delivery_today"] is True
    assert life["lifecycle_label"] == "Delivery Today"


def test_same_day_pickup_delivery_today():
    as_of = date(2026, 8, 21)
    life = _dhs_lifecycle(date(2026, 8, 21), date(2026, 8, 21), as_of)
    assert life["lifecycle"] == "due"
    assert "Pickup Today" in life["lifecycle_label"]
    assert "Delivery Today" in life["lifecycle_label"]


def test_overdue_after_delivery():
    as_of = date(2026, 8, 21)
    life = _dhs_lifecycle(date(2026, 8, 18), date(2026, 8, 20), as_of)
    assert life["lifecycle"] == "overdue"
    assert life["lifecycle_label"] == "Overdue"


def test_not_overdue_when_delivery_tomorrow():
    as_of = date(2026, 8, 21)
    life = _dhs_lifecycle(date(2026, 8, 20), date(2026, 8, 22), as_of)
    assert life["lifecycle"] == "due"
