"""Tests for overtime split / OT-inclusive W-2 batch gross."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from backend.payroll_overtime import (
    compute_wage_with_overtime,
    resolve_overtime_rate,
    split_hours_for_overtime,
)


def test_split_hours_over_40_threshold():
    reg, ot = split_hours_for_overtime(48.65, threshold=40)
    assert float(reg) == 40.0
    assert float(ot) == 8.65


def test_split_hours_under_threshold_all_regular():
    reg, ot = split_hours_for_overtime(38.5, threshold=40)
    assert float(reg) == 38.5
    assert float(ot) == 0.0


def test_split_hours_disabled_keeps_all_regular():
    reg, ot = split_hours_for_overtime(50, threshold=40, enabled=False)
    assert float(reg) == 50.0
    assert float(ot) == 0.0


def test_resolve_ot_rate_defaults_to_1_5x():
    assert float(resolve_overtime_rate(17)) == 25.5


def test_resolve_ot_rate_uses_explicit():
    assert float(resolve_overtime_rate(17, explicit_ot_rate=30)) == 30.0


def test_compute_wage_matches_time_records_varun_case():
    # Time Records: Regular $680 + OT $220.57 = $900.58
    gross = compute_wage_with_overtime(40, 8.65, 17, 25.50)
    assert float(gross) == 900.58


def test_compute_wage_without_ot_rate_uses_multiplier():
    gross = compute_wage_with_overtime(40, 8.65, 17)
    assert float(gross) == 900.58


def test_w2_accrual_gross_includes_ot_premium():
    from backend.payroll_accrual import process_w2_line_accruals

    cursor = MagicMock()
    cursor.fetchone = MagicMock(return_value=None)
    cursor.fetchall = MagicMock(return_value=[])
    cursor.lastrowid = 1
    with patch("backend.payroll_accrual.fetch_payroll_tax_settings") as mock_settings:
        mock_settings.return_value = {"sick_leave_annual_cap_hours": 40}
        with patch("backend.payroll_accrual.get_ledger_ytd_totals") as mock_ytd:
            mock_ytd.return_value = {"accrued": Decimal("0"), "used": Decimal("0")}
            with patch("backend.payroll_accrual.get_sick_leave_balance") as mock_bal:
                mock_bal.return_value = {
                    "balance_hours": Decimal("5"),
                    "ytd_accrued_hours": Decimal("0"),
                    "ytd_used_hours": Decimal("0"),
                }
                with patch("backend.payroll_accrual.insert_ledger_entry"):
                    out = process_w2_line_accruals(
                        cursor,
                        1,
                        user_id=99,
                        batch_id=1,
                        line_id=10,
                        regular_hours=Decimal("40"),
                        ot_hours=Decimal("8.65"),
                        sick_hours_used=Decimal("0"),
                        hourly_rate=Decimal("17"),
                        ot_hourly_rate=Decimal("25.50"),
                        period_start="2026-07-06",
                        period_end="2026-07-12",
                    )
    assert float(out["gross_wages"]) == 900.58
    # Must not be flat (reg+ot)*rate = 827.05
    assert float(out["gross_wages"]) != 827.05
