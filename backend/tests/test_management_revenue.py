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


@patch("backend.management_revenue.build_account_revenue_day")
@patch("backend.management_revenue._load_entry_header")
@patch("backend.management_revenue._load_drc_lines_for_date")
@patch("backend.management_revenue.ensure_management_revenue_tables")
def test_build_revenue_day_shape(mock_ensure, mock_lines, mock_header, mock_account_day):
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    mock_header.return_value = {"id": 1, "status": "open"}
    mock_lines.return_value = {
        "revenue.self_service.cash": {"amount": 80},
        "revenue.self_service.card": {"amount": 20},
        "revenue.drop_off.cash": {"amount": 30},
        "revenue.drop_off.card": {"amount": 5},
    }
    mock_account_day.return_value = {
        "rinse": {
            "wf": {"enabled": False, "placeholder": True, "revenue": None},
            "hd": {"revenue": 450.0, "orders": 3, "read_only": True},
        },
        "non_rinse_revenue": {
            "self_service": {"cash": 80, "card": 20, "total": 100},
            "drop_off": {"cash": 30, "card": 5, "total": 35},
            "total": 135,
        },
        "non_rinse": {
            "self_service": {"cash": 80, "card": 20, "total": 100},
            "drop_off": {"cash": 30, "card": 5, "total": 35},
            "total": 135,
        },
        "dhs": {"accounts": [], "total": 0},
        "total_revenue": 585,
    }

    payload = build_revenue_day(cursor, 1, date(2026, 8, 19))
    assert payload["rinse"]["hd"]["revenue"] == 450.0
    assert payload["non_rinse_revenue"]["self_service"]["total"] == 100.0
    assert payload["cash_activity"]["net_cash_movement"] == 110.0


@patch("backend.management_revenue.build_revenue_day")
@patch("backend.management_revenue._log_audit")
@patch("backend.management_revenue._upsert_line")
@patch("backend.management_revenue._load_entry_lines")
@patch("backend.management_revenue.assert_entry_editable")
@patch("backend.management_revenue.ensure_daily_revenue_cost_tables")
@patch("backend.management_revenue.ensure_management_revenue_tables")
def test_save_non_rinse_writes_only_four_lines(
    mock_mgmt_tables,
    mock_drc_tables,
    mock_editable,
    mock_load_lines,
    mock_upsert,
    mock_audit,
    mock_build_day,
):
    from backend.management_revenue import save_non_rinse_revenue

    cursor = MagicMock()
    cursor.fetchone.return_value = {"id": 9, "status": "open"}
    mock_load_lines.return_value = {}
    mock_build_day.return_value = {"ok": True}

    with patch("backend.management_revenue.save_daily_entry", create=True) as mock_full_save:
        save_non_rinse_revenue(
            cursor,
            1,
            date(2026, 8, 19),
            {
                "self_service_cash": 11,
                "self_service_card": 22,
                "drop_off_cash": 33,
                "drop_off_card": 44,
            },
            user_id=7,
        )
        mock_full_save.assert_not_called()

    keys = [call.args[2] for call in mock_upsert.call_args_list]
    assert keys == [
        "revenue.self_service.cash",
        "revenue.self_service.card",
        "revenue.drop_off.cash",
        "revenue.drop_off.card",
    ]
    assert mock_upsert.call_count == 4
    mock_build_day.assert_called_once()


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


def test_create_cash_payout_requires_payout_date():
    from backend.management_revenue import create_cash_payout

    cursor = MagicMock()
    with patch("backend.management_revenue.ensure_management_revenue_tables"):
        try:
            create_cash_payout(cursor, 1, {"purpose": "Repair", "amount": 125})
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "Payout Date" in str(exc)


def test_line_amount_or_none_distinguishes_blank_and_zero():
    from backend.management_revenue_accounts import _line_amount_or_none

    assert _line_amount_or_none({}, "revenue.self_service.cash") is None
    assert _line_amount_or_none({"revenue.self_service.cash": {"amount": 0}}, "revenue.self_service.cash") == 0.0
    assert _line_amount_or_none({"revenue.self_service.cash": {"amount": 12.5}}, "revenue.self_service.cash") == 12.5


@patch("backend.management_revenue.build_revenue_day")
@patch("backend.management_revenue._log_audit")
@patch("backend.management_revenue._upsert_line")
@patch("backend.management_revenue._load_entry_lines")
@patch("backend.management_revenue.assert_entry_editable")
@patch("backend.management_revenue.ensure_daily_revenue_cost_tables")
@patch("backend.management_revenue.ensure_management_revenue_tables")
def test_save_non_rinse_skips_blank_fields(
    mock_mgmt_tables,
    mock_drc_tables,
    mock_editable,
    mock_load_lines,
    mock_upsert,
    mock_audit,
    mock_build_day,
):
    from backend.management_revenue import save_non_rinse_revenue

    cursor = MagicMock()
    cursor.fetchone.return_value = {"id": 9, "status": "open"}
    mock_load_lines.return_value = {}
    mock_build_day.return_value = {"ok": True}

    save_non_rinse_revenue(
        cursor,
        1,
        date(2026, 8, 19),
        {
            "self_service_cash": 11,
            "self_service_card": "",
            "drop_off_cash": None,
        },
        user_id=7,
    )
    keys = [call.args[2] for call in mock_upsert.call_args_list]
    assert keys == ["revenue.self_service.cash"]


def test_period_bounds_yesterday_and_previous():
    ref = date(2026, 8, 20)
    assert _period_bounds("yesterday", ref) == (date(2026, 8, 19), date(2026, 8, 19))
    pw_s, pw_e = _period_bounds("previous_week", ref)
    assert pw_s == date(2026, 8, 10)
    assert pw_e == date(2026, 8, 16)
    pm_s, pm_e = _period_bounds("previous_month", ref)
    assert pm_s == date(2026, 7, 1)
    assert pm_e == date(2026, 7, 31)


def test_create_cash_payout_requires_business_date():
    from backend.management_revenue import create_cash_payout

    cursor = MagicMock()
    with patch("backend.management_revenue.ensure_management_revenue_tables"):
        try:
            create_cash_payout(cursor, 1, {"purpose": "Repair", "amount": 10})
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "Payout Date" in str(exc)


def test_create_cash_payout_accepts_backdate():
    from backend.management_revenue import create_cash_payout

    cursor = MagicMock()
    cursor.lastrowid = 9
    cursor.fetchone.return_value = {
        "id": 9,
        "payout_date_et": date(2026, 8, 19),
        "purpose": "Repair",
        "amount": Decimal("12.50"),
        "note": None,
        "entered_by_name_snapshot": "Ada",
        "entered_by_user_id": 1,
        "created_at": None,
        "updated_at": None,
    }
    with patch("backend.management_revenue.ensure_management_revenue_tables"), patch(
        "backend.management_revenue._log_payout_audit"
    ):
        out = create_cash_payout(
            cursor,
            1,
            {"payout_business_date": "2026-08-19", "purpose": "Repair", "amount": 12.5},
            user_id=1,
            actor_name="Ada",
        )
    assert out["payout_business_date"] == "2026-08-19"
    assert out["amount"] == 12.5


def test_save_dhs_does_not_invent_processing_date():
    from backend.management_revenue_accounts import save_dhs_account_revenue

    cursor = MagicMock()
    acct = {
        "id": 10,
        "revenue_group": "dhs",
        "revenue_mode": "calculated",
        "allow_override": True,
        "use_pickup_date": False,
        "use_processing_date": True,
        "use_delivery_date": False,
        "dr_commercial_account_id": 44,
        "pricing": {"pricing_method": "flat_lb", "rate_per_unit": 1.0},
    }
    with patch("backend.management_revenue_accounts.list_accounts", return_value=[acct]), patch(
        "backend.management_revenue_accounts._ensure_entry_id", return_value=1
    ), patch(
        "backend.management_revenue_accounts._load_entry_lines", return_value={}
    ), patch(
        "backend.management_revenue_accounts.upsert_entry_line"
    ) as upsert, patch(
        "backend.management_revenue.build_revenue_day", return_value={"ok": True}
    ):
        save_dhs_account_revenue(
            cursor,
            1,
            date(2026, 8, 20),
            [{
                "account_id": 10,
                "dr_commercial_account_id": 44,
                "volume": 10,
                "processing_date": None,
            }],
            user_id=1,
        )
    # Snapshot must not invent entry_date when client omitted processing_date
    snap = None
    for call in upsert.call_args_list:
        kwargs = call.kwargs
        if kwargs.get("rate_snapshot") and kwargs["rate_snapshot"].get("line") != "pounds":
            snap = kwargs["rate_snapshot"]
    assert snap is not None
    assert snap.get("processing_date") is None
