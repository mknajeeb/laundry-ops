"""Monday–Sunday schedule weeks keep each stored shift on its calendar date."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from backend.weekly_schedule_week import (
    current_schedule_monday,
    display_monday_for_storage,
    resolve_schedule_write,
    row_in_display_week,
    schedule_monday_containing,
    storage_week_for_dow,
)

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def test_sunday_november_first_belongs_to_the_previous_monday_week():
    sunday = date(2026, 11, 1)
    assert sunday.weekday() == 6
    assert schedule_monday_containing(sunday) == date(2026, 10, 26)
    assert current_schedule_monday(sunday) == date(2026, 11, 2)
    assert schedule_monday_containing(date(2026, 11, 2)) == date(2026, 11, 2)
    assert current_schedule_monday(date(2026, 11, 2)) == date(2026, 11, 2)
    assert current_schedule_monday(date(2026, 11, 7)) == date(2026, 11, 2)
    assert current_schedule_monday(date(2026, 11, 8)) == date(2026, 11, 9)


def test_display_week_reads_two_storage_sundays_without_moving_dates():
    shown = date(2026, 11, 2)
    assert storage_week_for_dow(shown, 1) == date(2026, 11, 1)
    assert storage_week_for_dow(shown, 6) == date(2026, 11, 1)
    assert storage_week_for_dow(shown, 0) == date(2026, 11, 8)

    sunday_nov_1 = {"week_start": date(2026, 11, 1), "day_of_week": 0}
    monday_nov_2 = {"week_start": date(2026, 11, 1), "day_of_week": 1}
    sunday_nov_8 = {"week_start": date(2026, 11, 8), "day_of_week": 0}

    assert display_monday_for_storage(date(2026, 11, 1), 0) == date(2026, 10, 26)
    assert display_monday_for_storage(date(2026, 11, 1), 1) == date(2026, 11, 2)
    assert not row_in_display_week(sunday_nov_1, shown)
    assert row_in_display_week(sunday_nov_1, date(2026, 10, 26))
    assert row_in_display_week(monday_nov_2, shown)
    assert row_in_display_week(sunday_nov_8, shown)
    # The calendar date is still storage Sunday plus the stored weekday index.
    assert date(2026, 11, 1) + timedelta(days=0) == date(2026, 11, 1)
    assert date(2026, 11, 1) + timedelta(days=1) == date(2026, 11, 2)


def test_monday_request_stores_sunday_on_the_displayed_sunday():
    monday, storage = resolve_schedule_write("2026-11-02", 0)
    assert monday == date(2026, 11, 2)
    assert storage == date(2026, 11, 8)
    monday, storage = resolve_schedule_write("2026-11-02", 1)
    assert storage == date(2026, 11, 1)
    # A legacy Sunday key still writes every day onto that stored week.
    monday, storage = resolve_schedule_write("2026-11-01", 1)
    assert storage == date(2026, 11, 1)
    assert monday == date(2026, 11, 2)


def test_week_boundary_uses_eastern_dates_across_daylight_saving():
    # 2026-11-02 00:30 UTC is still Sunday evening in New York, after the fallback.
    still_sunday = datetime(2026, 11, 2, 0, 30, tzinfo=UTC).astimezone(ET).date()
    assert still_sunday == date(2026, 11, 1)
    assert schedule_monday_containing(still_sunday) == date(2026, 10, 26)
    assert current_schedule_monday(still_sunday) == date(2026, 11, 2)

    monday_et = datetime(2026, 11, 2, 5, 30, tzinfo=UTC).astimezone(ET).date()
    assert monday_et == date(2026, 11, 2)
    assert current_schedule_monday(monday_et) == date(2026, 11, 2)

    # 2026-03-08 is the spring-forward Sunday. 06:30 UTC is 2:30 AM EDT.
    spring = datetime(2026, 3, 8, 6, 30, tzinfo=UTC).astimezone(ET).date()
    assert spring == date(2026, 3, 8)
    assert spring.weekday() == 6
    assert schedule_monday_containing(spring) == date(2026, 3, 2)
    assert current_schedule_monday(spring) == date(2026, 3, 9)
