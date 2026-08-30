"""Employer-tax period wage-base validation and Evelin-style regression."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.payroll_payout_details import (
    expected_employer_taxes_for_period,
    sum_employer_taxes,
    validate_employer_taxes_for_period,
)


def test_validate_rejects_employer_ss_on_wrong_wage_base():
    """Evelin-style: ER SS/FUTA/SUTA on ~$4550 while period gross is $810."""
    details = {
        "employer_taxes": {
            "er_ss": 282.13,
            "er_medicare": 0.0,
            "futa": 27.3,
            "suta": 183.16,
            "ny_reemploy": 0.0,
            "other": 0.0,
        }
    }
    expected = {
        "er_ss": 50.22,
        "er_medicare": 11.75,
        "futa": 4.86,
        "suta": 32.60,
        "ny_reemploy": 0.0,
        "other": 0.0,
    }
    with patch(
        "backend.payroll_payout_details.expected_employer_taxes_for_period",
        return_value=expected,
    ), patch(
        "backend.payroll_tax_settings.fetch_payroll_tax_settings",
        return_value={
            "employer_social_security_rate": 0.062,
            "employer_medicare_rate": 0.0145,
            "futa_rate": 0.006,
            "ny_suta_rate": 0.04025,
        },
    ):
        err = validate_employer_taxes_for_period(
            MagicMock(),
            3,
            user_id=30,
            gross=810.05,
            details=details,
            pay_period_start="2026-08-10",
            pay_frequency="weekly",
            worker_category="w2",
        )
    assert err is not None
    assert "SS" in err
    assert "50.22" in err


def test_validate_accepts_period_matching_employer_taxes():
    details = {
        "employer_taxes": {
            "er_ss": 50.22,
            "er_medicare": 11.75,
            "futa": 4.86,
            "suta": 32.60,
            "ny_reemploy": 0.0,
            "other": 0.0,
        }
    }
    expected = dict(details["employer_taxes"])
    with patch(
        "backend.payroll_payout_details.expected_employer_taxes_for_period",
        return_value=expected,
    ), patch(
        "backend.payroll_tax_settings.fetch_payroll_tax_settings",
        return_value={
            "employer_social_security_rate": 0.062,
            "employer_medicare_rate": 0.0145,
            "futa_rate": 0.006,
            "ny_suta_rate": 0.04025,
        },
    ):
        err = validate_employer_taxes_for_period(
            MagicMock(),
            3,
            user_id=30,
            gross=810.05,
            details=details,
            pay_period_start="2026-08-10",
            worker_category="w2",
        )
    assert err is None


def test_validate_skips_non_w2():
    details = {"employer_taxes": {"er_ss": 999, "er_medicare": 0, "futa": 0, "suta": 0}}
    err = validate_employer_taxes_for_period(
        MagicMock(),
        3,
        user_id=1,
        gross=100,
        details=details,
        worker_category="temp",
    )
    assert err is None


def test_ytd_as_of_excludes_current_and_later_periods():
    from backend.w2_payroll_tax_engine import get_w2_ytd_gross

    captured = {}

    class _Cur:
        def execute(self, sql, params=None):
            captured["sql"] = sql
            captured["params"] = params

        def fetchone(self):
            return {"ytd": 5312.84}

    class _Conn:
        def cursor(self, dictionary=False):
            return _Cur()

    ytd = get_w2_ytd_gross(
        _Conn(), 3, 30, 2026, before_period_start="2026-08-10"
    )
    assert float(ytd) == 5312.84
    assert "pay_period_end <" in captured["sql"]
    assert captured["params"][-1] == "2026-08-10"


def test_expected_employer_taxes_maps_engine_keys():
    calc = {
        "tax_calc_status": "estimated",
        "employer_social_security": 50.22,
        "employer_medicare": 11.75,
        "futa_estimate": 4.86,
        "ny_suta_estimate": 32.60,
        "ny_reemployment_estimate": 0.0,
        "employer_other_tax_estimate": 0.0,
    }
    with patch(
        "backend.w2_payroll_tax_engine.calculate_w2_line_taxes", return_value=calc
    ), patch(
        "backend.w2_payroll_tax_engine.fetch_payroll_tax_settings",
        return_value={},
    ):
        out = expected_employer_taxes_for_period(
            MagicMock(), 3, 30, 810.05, pay_period_start="2026-08-10", pay_frequency="weekly"
        )
    assert out["er_ss"] == 50.22
    assert out["er_medicare"] == 11.75
    assert out["futa"] == 4.86
    assert out["suta"] == 32.60
    assert abs(sum_employer_taxes({"employer_taxes": out}) - 99.43) < 0.01
