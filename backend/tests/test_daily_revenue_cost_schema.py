"""Unit tests for daily revenue & cost schema helpers."""

from datetime import date

import pytest

from backend.daily_revenue_cost_schema import (
    assert_no_overlapping_schedules,
    schedules_overlap,
    WORKFLOW_TRANSITIONS,
)


def test_schedules_overlap_open_ended():
    assert schedules_overlap(date(2026, 1, 1), None, date(2025, 6, 1), date(2026, 12, 31))


def test_schedules_no_overlap_adjacent():
    assert not schedules_overlap(date(2026, 1, 1), date(2026, 3, 31), date(2026, 4, 1), None)


def test_workflow_transition_map():
    assert WORKFLOW_TRANSITIONS["lock"] == ("open", "locked")
    assert WORKFLOW_TRANSITIONS["reopen"] == ("rejected", "open")


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=None):
        return self

    def fetchall(self):
        return self._rows


def test_close_schedule_before_sets_day_prior():
    from unittest.mock import MagicMock

    from backend.daily_revenue_cost_schema import close_schedule_before

    cursor = MagicMock()
    close_date = close_schedule_before(
        cursor,
        table="dr_cost_schedules",
        id_column="id",
        schedule_id=5,
        new_effective_from=date(2026, 8, 1),
    )
    assert close_date == date(2026, 7, 31)
    cursor.execute.assert_called_once()


def test_overlap_detection_raises():
    rows = [{"id": 10, "effective_from": date(2026, 1, 1), "effective_to": None}]
    cursor = FakeCursor(rows)
    with pytest.raises(ValueError, match="Overlapping"):
        assert_no_overlapping_schedules(
            cursor,
            table="dr_commercial_pricing_schedules",
            scope_column="commercial_account_id",
            scope_id=1,
            effective_from=date(2026, 6, 1),
        )
