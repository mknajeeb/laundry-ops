"""Tests for folding date-range helpers."""

from datetime import date

import pytest

from backend.rinse_folding_period import (
    default_week_range,
    parse_folding_date_range,
    sql_date_column,
)


def test_default_week_range_monday_sunday():
    start, end = default_week_range(date(2026, 5, 14))  # Thursday
    assert start == date(2026, 5, 11)
    assert end == date(2026, 5, 17)


def test_parse_explicit_range_single_day():
    start, end, label = parse_folding_date_range(
        date_start=date(2026, 5, 1), date_end=date(2026, 5, 1)
    )
    assert start == end == date(2026, 5, 1)
    assert label == "today"


def test_parse_range_invalid_order():
    with pytest.raises(ValueError):
        parse_folding_date_range(date_start=date(2026, 5, 10), date_end=date(2026, 5, 1))


def test_sql_date_column_mapping():
    assert "p.work_date" in sql_date_column("folding_work_date")
    assert "r.date_clean" in sql_date_column("date_clean")
    assert "r.completed_at" in sql_date_column("completed_at")
