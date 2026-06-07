"""Tests for Payroll Management worker profile default values."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from backend.payroll_worker_defaults import (
    PAYROLL_DEFAULT_MAX_HOURS,
    PAYROLL_DEFAULT_OT_RATE,
    PAYROLL_DEFAULT_OT_THRESHOLD,
    PAYROLL_DEFAULT_REGULAR_RATE,
    apply_payroll_defaults_to_row,
    audit_custom_payroll_values,
    backfill_payroll_worker_defaults,
    field_needs_default,
    is_blank_rate,
    new_worker_payroll_defaults,
)


def test_existing_null_rate_gets_default():
    row = {"default_hourly_rate": None}
    out = apply_payroll_defaults_to_row(row)
    assert out["default_hourly_rate"] == PAYROLL_DEFAULT_REGULAR_RATE
    assert row["default_hourly_rate"] is None


def test_existing_null_ot_rate_gets_default():
    row = {"default_overtime_rate": None}
    out = apply_payroll_defaults_to_row(row)
    assert out["default_overtime_rate"] == PAYROLL_DEFAULT_OT_RATE


def test_existing_null_max_hours_gets_default():
    row = {"max_hours_per_week": None}
    out = apply_payroll_defaults_to_row(row)
    assert out["max_hours_per_week"] == PAYROLL_DEFAULT_MAX_HOURS


def test_existing_null_threshold_gets_default():
    row = {"overtime_threshold": None}
    out = apply_payroll_defaults_to_row(row)
    assert out["overtime_threshold"] == PAYROLL_DEFAULT_OT_THRESHOLD


def test_existing_custom_values_are_not_overwritten():
    row = {
        "default_hourly_rate": Decimal("22.00"),
        "default_overtime_rate": Decimal("33.00"),
        "max_hours_per_week": Decimal("35"),
        "overtime_threshold": Decimal("32"),
    }
    out = apply_payroll_defaults_to_row(row)
    assert out["default_hourly_rate"] == Decimal("22.00")
    assert out["default_overtime_rate"] == Decimal("33.00")
    assert out["max_hours_per_week"] == Decimal("35")
    assert out["overtime_threshold"] == Decimal("32")


def test_new_person_defaults():
    defaults = new_worker_payroll_defaults()
    assert defaults["default_hourly_rate"] == PAYROLL_DEFAULT_REGULAR_RATE
    assert defaults["default_overtime_rate"] == PAYROLL_DEFAULT_OT_RATE
    assert defaults["max_hours_per_week"] == PAYROLL_DEFAULT_MAX_HOURS
    assert defaults["overtime_threshold"] == PAYROLL_DEFAULT_OT_THRESHOLD


def test_new_person_uses_resolved_rate_when_present():
    defaults = new_worker_payroll_defaults(hourly_rate=Decimal("19.50"))
    assert defaults["default_hourly_rate"] == Decimal("19.50")
    assert defaults["default_overtime_rate"] == PAYROLL_DEFAULT_OT_RATE


def test_is_blank_rate_treats_zero_as_blank():
    assert is_blank_rate(0) is True
    assert is_blank_rate("") is True
    assert is_blank_rate(None) is True
    assert is_blank_rate("17.00") is False


def test_field_needs_default():
    assert field_needs_default("default_hourly_rate", None) is True
    assert field_needs_default("max_hours_per_week", None) is True
    assert field_needs_default("max_hours_per_week", 40) is False


def test_audit_custom_payroll_values_reports_custom_only():
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {
            "id": 1,
            "user_id": 10,
            "default_hourly_rate": Decimal("22.00"),
            "default_overtime_rate": None,
            "max_hours_per_week": None,
            "overtime_threshold": None,
        },
        {
            "id": 2,
            "user_id": 11,
            "default_hourly_rate": None,
            "default_overtime_rate": None,
            "max_hours_per_week": None,
            "overtime_threshold": None,
        },
    ]
    with patch("backend.payroll_worker_defaults.table_has_column", return_value=True):
        out = audit_custom_payroll_values(cursor, 1)
    assert out["custom_count"] == 1
    assert out["workers"][0]["user_id"] == 10
    assert out["workers"][0]["custom_fields"]["rate"] == 22.0


def test_backfill_only_updates_blank_fields():
    conn = MagicMock()
    dict_cursor = MagicMock()
    dict_cursor.fetchall.return_value = [
        {
            "id": 1,
            "user_id": 10,
            "default_hourly_rate": Decimal("22.00"),
            "default_overtime_rate": None,
            "max_hours_per_week": None,
            "overtime_threshold": None,
        },
    ]
    update_cursor = MagicMock()
    update_cursor.rowcount = 3

    def cursor_factory(dictionary=False):
        if dictionary:
            return dict_cursor
        return update_cursor

    conn.cursor.side_effect = cursor_factory

    with patch("backend.payroll_worker_defaults.table_has_column", return_value=True):
        out = backfill_payroll_worker_defaults(conn, 1)

    assert out["custom_values_preserved"] == 1
    assert out["updated_by_field"]["ot_rate"] == 3
    sql_calls = [str(c.args[0]) for c in update_cursor.execute.call_args_list]
    assert any("default_hourly_rate" in s and "<= 0" in s for s in sql_calls)
    assert any("default_overtime_rate" in s for s in sql_calls)


def test_form_default_values_for_blank_worker():
    """Mirrors frontend buildPayrollSetupFormDefaults for new/blank profiles."""
    out = apply_payroll_defaults_to_row({})
    assert float(out["default_hourly_rate"]) == 17.0
    assert float(out["default_overtime_rate"]) == 25.5
    assert float(out["max_hours_per_week"]) == 40.0
    assert float(out["overtime_threshold"]) == 30.0


def test_form_defaults_preserve_custom_values():
    out = apply_payroll_defaults_to_row(
        {
            "default_hourly_rate": Decimal("22.00"),
            "default_overtime_rate": Decimal("33.00"),
            "max_hours_per_week": Decimal("35"),
            "overtime_threshold": Decimal("32"),
        }
    )
    assert float(out["default_hourly_rate"]) == 22.0
    assert float(out["default_overtime_rate"]) == 33.0
    assert float(out["max_hours_per_week"]) == 35.0
    assert float(out["overtime_threshold"]) == 32.0
