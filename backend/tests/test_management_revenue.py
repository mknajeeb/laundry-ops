"""Management Revenue — unit tests (no live DB)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from backend.management_revenue import (
    _cash_revenue_from_lines,
    _period_bounds,
    build_cash_activity,
    build_revenue_day,
)


def test_period_bounds_week_month_custom():
    ref = date(2026, 8, 19)  # Wednesday
    assert _period_bounds("today", ref) == (ref, ref)
    week_start, week_end = _period_bounds("week", ref)
    assert week_start == date(2026, 8, 17)
    assert week_end == date(2026, 8, 23)
    month_start, month_end = _period_bounds("month", ref)
    assert month_start == date(2026, 8, 1)
    assert month_end == date(2026, 8, 31)
    assert _period_bounds("custom", ref, date(2026, 8, 1), date(2026, 8, 10)) == (
        date(2026, 8, 1),
        date(2026, 8, 10),
    )


def test_cash_revenue_from_lines():
    lines = {
        "revenue.self_service.cash": {"amount": 100},
        "revenue.self_service.card": {"amount": 50},
        "revenue.drop_off.cash": {"amount": 25},
        "revenue.drop_off.card": {"amount": 10},
    }
    cash = _cash_revenue_from_lines(lines)
    assert cash["self_service_cash"] == 100.0
    assert cash["drop_off_cash"] == 25.0
    assert cash["total_cash_revenue"] == 125.0
    assert cash["self_service_total"] == 150.0


@patch("backend.management_revenue.compute_hd_day_revenue_totals")
@patch("backend.management_revenue.get_daily_entry")
@patch("backend.management_revenue._load_drc_lines_for_date")
@patch("backend.management_revenue.ensure_management_revenue_tables")
def test_build_revenue_day_shape(mock_ensure, mock_lines, mock_entry, mock_hd):
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    mock_hd.return_value = {"complete": 3, "complete_hd_revenue": Decimal("450.00")}
    mock_entry.return_value = {"entry": {"id": 1, "status": "open"}}
    mock_lines.return_value = {
        "revenue.self_service.cash": {"amount": 80},
        "revenue.self_service.card": {"amount": 20},
        "revenue.drop_off.cash": {"amount": 30},
        "revenue.drop_off.card": {"amount": 5},
    }

    payload = build_revenue_day(cursor, 1, date(2026, 8, 19))
    assert payload["rinse"]["wf"]["placeholder"] is True
    assert payload["rinse"]["hd"]["revenue"] == 450.0
    assert payload["rinse"]["hd"]["read_only"] is True
    assert payload["non_rinse"]["self_service"]["total"] == 100.0
    assert payload["cash_activity"]["net_cash_movement"] == 110.0


@patch("backend.management_revenue._load_drc_lines_for_date")
@patch("backend.management_revenue.ensure_management_revenue_tables")
def test_build_cash_activity_aggregates(mock_ensure, mock_lines):
    cursor = MagicMock()

    def lines_for_day(_cursor, _org, day):
        if day == date(2026, 8, 18):
            return {
                "revenue.self_service.cash": {"amount": 10},
                "revenue.drop_off.cash": {"amount": 5},
            }
        return {
            "revenue.self_service.cash": {"amount": 20},
            "revenue.drop_off.cash": {"amount": 8},
        }

    mock_lines.side_effect = lines_for_day

    def fetchone_side_effect():
        calls = [{"paid": 3}, {"paid": 2}]

        def _fetchone():
            return calls.pop(0) if calls else {"paid": 0}

        return _fetchone

    cursor.fetchone.side_effect = fetchone_side_effect()

    activity = build_cash_activity(cursor, 1, "custom", date(2026, 8, 19), date(2026, 8, 18), date(2026, 8, 19))
    assert activity["self_service_cash"] == 30.0
    assert activity["drop_off_cash"] == 13.0
    assert activity["total_cash_revenue"] == 43.0
    assert activity["cash_paid_out"] == 5.0
    assert activity["net_cash_movement"] == 38.0
    assert len(activity["daily"]) == 2
