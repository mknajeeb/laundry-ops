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


def test_ot_premium_is_half_rate_for_time_and_a_half():
    from backend.payroll_overtime import compute_overtime_premium, compute_earnings_breakdown

    assert float(compute_overtime_premium(8.65, 17, 25.50)) == 73.53
    br = compute_earnings_breakdown(
        regular_hours=40, ot_hours=8.65, regular_rate=17, ot_rate=25.50, gross_pay=900.58
    )
    assert float(br["ot_premium"]) == 73.53
    assert abs(br["base_earnings"] + br["ot_premium"] + br["other_earnings"] - 900.58) < 0.02


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


def test_temp_and_1099_policy_keeps_ot_enabled_even_when_calendar_off():
    """Calendar defaults overtime_enabled=False for non-W2; batch gross must still OT."""
    from backend.payroll_overtime import resolve_batch_overtime_policy

    fake_bundle = {
        "categories": {
            "temp": {
                "overtime_enabled": False,
                "overtime_threshold_hours": 40,
                "overtime_multiplier": 1.5,
            },
            "contractor_1099": {
                "overtime_enabled": False,
                "overtime_threshold_hours": 40,
                "overtime_multiplier": 1.5,
            },
            "w2": {
                "overtime_enabled": True,
                "overtime_threshold_hours": 40,
                "overtime_multiplier": 1.5,
            },
        },
        "org_schedule_settings": {"overtime_threshold_hours": 40},
    }
    with patch(
        "backend.payroll_funding_forecast.get_calendar_settings",
        return_value=fake_bundle,
    ):
        for cat in ("temp", "contractor_1099", "w2"):
            policy = resolve_batch_overtime_policy(MagicMock(), 3, cat)
            assert policy["enabled"] is True, cat
            reg, ot = split_hours_for_overtime(
                48.65,
                threshold=policy["threshold_hours"],
                enabled=policy["enabled"],
            )
            assert float(reg) == 40.0
            assert float(ot) == 8.65
            gross = compute_wage_with_overtime(
                reg, ot, 17, resolve_overtime_rate(17, multiplier=policy["multiplier"])
            )
            assert float(gross) == 900.58


def test_temp_exactly_40_hours_has_no_overtime():
    reg, ot = split_hours_for_overtime(40, threshold=40)
    assert float(reg) == 40.0
    assert float(ot) == 0.0
    assert float(compute_wage_with_overtime(40, 0, 17)) == 680.0


def test_temp_47_02_hours_at_17_produces_expected_gross():
    """User example: 40 reg @ $17 + 7.02 OT @ $25.50 = $859.01."""
    from backend.payroll_overtime import (
        compute_contractor_invoice_earnings,
        compute_earnings_breakdown,
        compute_overtime_premium,
    )

    reg, ot = split_hours_for_overtime(47.02, threshold=40)
    assert float(reg) == 40.0
    assert float(ot) == 7.02
    ot_rate = resolve_overtime_rate(17)
    assert float(ot_rate) == 25.5
    gross = compute_wage_with_overtime(reg, ot, 17, ot_rate)
    assert float(gross) == 859.01
    # Register shows premium only.
    premium = compute_overtime_premium(ot, 17, ot_rate)
    assert float(premium) == 59.67
    br = compute_earnings_breakdown(
        regular_hours=reg, ot_hours=ot, regular_rate=17, ot_rate=ot_rate, gross_pay=gross
    )
    assert float(br["ot_premium"]) == 59.67
    assert abs(br["base_earnings"] + br["ot_premium"] + br["other_earnings"] - 859.01) < 0.02
    # Contractor invoice shows full OT earnings.
    inv = compute_contractor_invoice_earnings(
        {
            "approved_hours": float(reg),
            "ot_hours": float(ot),
            "rate": 17,
            "ot_rate": float(ot_rate),
            "gross_amount": float(gross),
        }
    )
    assert inv["regular_earnings"] == 680.0
    assert inv["overtime_earnings"] == 179.01
    assert inv["gross_pay"] == 859.01
    assert abs(inv["regular_earnings"] + inv["overtime_earnings"] + inv["other_earnings"] - 859.01) < 0.02


def test_1099_uses_same_overtime_rule_as_temp():
    reg, ot = split_hours_for_overtime(47.02)
    gross = compute_wage_with_overtime(reg, ot, 17)
    assert float(gross) == 859.01


def test_custom_ot_multiplier_is_respected():
    ot_rate = resolve_overtime_rate(17, multiplier=2.0)
    assert float(ot_rate) == 34.0
    gross = compute_wage_with_overtime(40, 5, 17, ot_rate)
    assert float(gross) == 850.0  # 680 + 170


def test_contractor_invoice_reconciles_to_stored_gross_without_inventing_ot():
    """Historical underpayment: hours>40 all at regular — receipt must match stored flat gross."""
    from backend.payroll_overtime import compute_contractor_invoice_earnings

    inv = compute_contractor_invoice_earnings(
        {
            "approved_hours": 47.02,
            "ot_hours": 0,
            "rate": 17,
            "gross_amount": 799.34,
        }
    )
    assert inv["overtime_earnings"] == 0.0
    assert inv["regular_earnings"] == 799.34
    assert inv["gross_pay"] == 799.34


def test_batch_allows_contractor_overtime_autosplit_gates_paid_history():
    from backend.payroll_overtime import batch_allows_contractor_overtime_autosplit

    assert batch_allows_contractor_overtime_autosplit(
        {"worker_category": "temp", "status": "draft"}
    )
    assert batch_allows_contractor_overtime_autosplit(
        {"worker_category": "contractor_1099", "status": "hours_reviewed"}
    )
    assert not batch_allows_contractor_overtime_autosplit(
        {"worker_category": "temp", "status": "paid"}
    )
    assert not batch_allows_contractor_overtime_autosplit(
        {
            "worker_category": "temp",
            "status": "draft",
            "payout_details_finalized_at": "2026-07-01",
        }
    )
    assert not batch_allows_contractor_overtime_autosplit(
        {"worker_category": "w2", "status": "draft"}
    )


def test_compute_payout_line_amounts_autosplits_temp_draft():
    from backend.payroll_operations import _compute_payout_line_amounts

    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    batch = {"worker_category": "temp", "status": "draft", "pay_period_start": "2026-06-01", "pay_period_end": "2026-06-07"}
    with patch("backend.payroll_workflow.ensure_payout_batch_line_extensions"), patch(
        "backend.payroll_overtime.resolve_batch_overtime_policy",
        return_value={"enabled": True, "threshold_hours": 40.0, "multiplier": 1.5},
    ):
        out = _compute_payout_line_amounts(
            conn,
            3,
            batch,
            {"approved_hours": 47.02, "ot_hours": 0, "rate": 17, "adjustments": 0},
        )
    assert float(out["approved_hours"]) == 40.0
    assert float(out["ot_hours"]) == 7.02
    assert float(out["ot_rate"]) == 25.5
    assert float(out["gross_amount"]) == 859.01


def test_compute_payout_line_amounts_does_not_autosplit_paid_batch():
    from backend.payroll_operations import _compute_payout_line_amounts

    conn = MagicMock()
    conn.cursor.return_value = MagicMock()
    batch = {"worker_category": "temp", "status": "paid", "pay_period_start": "2026-06-01", "pay_period_end": "2026-06-07"}
    with patch("backend.payroll_workflow.ensure_payout_batch_line_extensions"):
        out = _compute_payout_line_amounts(
            conn,
            3,
            batch,
            {"approved_hours": 47.02, "ot_hours": 0, "rate": 17, "adjustments": 0},
        )
    assert float(out["approved_hours"]) == 47.02
    assert float(out["ot_hours"]) == 0.0
    assert float(out["gross_amount"]) == 799.34
