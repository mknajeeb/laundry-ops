"""Employer-tax period reconciliation invariant (Evelin regression)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.payroll_payout_details import (
    expected_employer_taxes_for_period,
    sum_employer_taxes,
    validate_employer_taxes_for_period,
)

EVELIN_GROSS = 810.05
EVELIN_EXPECTED = {
    "er_ss": 50.22,
    "er_medicare": 11.75,
    "futa": 4.86,
    "suta": 32.61,
    "ny_reemploy": 0.0,
    "other": 0.0,
}
EVELIN_BAD = {
    "er_ss": 282.13,
    "er_medicare": 0.0,
    "futa": 27.3,
    "suta": 183.16,
    "ny_reemploy": 0.0,
    "other": 0.0,
}
_SETTINGS = {
    "employer_social_security_rate": 0.062,
    "employer_medicare_rate": 0.0145,
    "futa_rate": 0.006,
    "ny_suta_rate": 0.04025,
    "ny_reemployment_service_fund_rate": 0.0,
}


def _validate(details, *, expected=None, require_reconcile=False, settings=None):
    with patch(
        "backend.payroll_payout_details.expected_employer_taxes_for_period",
        return_value=expected if expected is not None else EVELIN_EXPECTED,
    ), patch(
        "backend.payroll_tax_settings.fetch_payroll_tax_settings",
        return_value=dict(settings or _SETTINGS),
    ):
        return validate_employer_taxes_for_period(
            MagicMock(),
            3,
            user_id=30,
            gross=EVELIN_GROSS,
            details={"employer_taxes": details},
            pay_period_start="2026-08-10",
            pay_frequency="weekly",
            worker_category="w2",
            require_reconcile=require_reconcile,
        )


def test_bad_er_ss_payload_rejected():
    err = _validate(EVELIN_BAD)
    assert err is not None
    assert "SS" in err
    assert "282.13" in err
    assert "50.22" in err


def test_bad_futa_suta_wage_base_rejected():
    """FUTA/SUTA on ~$4550 wage base while SS/Medicare look period-plausible."""
    bad = {
        "er_ss": 50.22,
        "er_medicare": 11.75,
        "futa": 27.3,
        "suta": 183.16,
        "ny_reemploy": 0.0,
        "other": 0.0,
    }
    err = _validate(bad)
    assert err is not None
    assert "FUTA" in err or "SUTA" in err


def test_missing_er_medicare_when_engine_expects_it_rejected():
    bad = {
        "er_ss": 50.22,
        "er_medicare": 0.0,
        "futa": 4.86,
        "suta": 32.61,
        "ny_reemploy": 0.0,
        "other": 0.0,
    }
    err = _validate(bad)
    assert err is not None
    assert "Medicare" in err
    assert "11.75" in err


def test_valid_engine_generated_payload_accepted():
    err = _validate(EVELIN_EXPECTED)
    assert err is None
    assert abs(sum_employer_taxes({"employer_taxes": EVELIN_EXPECTED}) - 99.44) < 0.01


def test_employer_tax_total_must_match_engine_sum():
    """Component fields look close but total is wrong → rejected."""
    # Force total mismatch via 'other' while individual FICA keys match.
    tampered = dict(EVELIN_EXPECTED)
    tampered["other"] = 50.0
    err = _validate(tampered)
    assert err is not None
    assert "total" in err.lower() or "other" in err.lower()


def test_finalize_requires_reconcile_even_when_employer_taxes_zero():
    err = _validate(
        {k: 0.0 for k in EVELIN_EXPECTED},
        require_reconcile=True,
    )
    assert err is not None


def test_draft_empty_employer_taxes_allowed_without_require_reconcile():
    err = _validate({k: 0.0 for k in EVELIN_EXPECTED}, require_reconcile=False)
    assert err is None


def test_suta_without_configured_rate_rejected():
    err = _validate(
        EVELIN_EXPECTED,
        expected={
            "er_ss": 50.22,
            "er_medicare": 11.75,
            "futa": 4.86,
            "suta": 0.0,
            "ny_reemploy": 0.0,
            "other": 0.0,
        },
        settings={
            "employer_social_security_rate": 0.062,
            "employer_medicare_rate": 0.0145,
            "futa_rate": 0.006,
            "ny_suta_rate": None,
        },
    )
    assert err is not None
    assert "SUTA" in err


def test_validate_skips_non_w2():
    err = validate_employer_taxes_for_period(
        MagicMock(),
        3,
        user_id=1,
        gross=100,
        details={"employer_taxes": EVELIN_BAD},
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

    ytd = get_w2_ytd_gross(_Conn(), 3, 30, 2026, before_period_start="2026-08-10")
    assert float(ytd) == 5312.84
    assert "pay_period_end <" in captured["sql"]
    assert captured["params"][-1] == "2026-08-10"


def test_expected_employer_taxes_maps_engine_keys():
    calc = {
        "tax_calc_status": "estimated",
        "employer_social_security": 50.22,
        "employer_medicare": 11.75,
        "futa_estimate": 4.86,
        "ny_suta_estimate": 32.61,
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
            MagicMock(),
            3,
            30,
            810.05,
            pay_period_start="2026-08-10",
            pay_frequency="weekly",
        )
    assert out["er_ss"] == 50.22
    assert out["er_medicare"] == 11.75
    assert out["futa"] == 4.86
    assert out["suta"] == 32.61
    assert abs(sum_employer_taxes({"employer_taxes": out}) - 99.44) < 0.01


def test_historical_line_487_after_repair_reconciled():
    """Live org-3 line 487 must reconcile to the engine after the Evelin repair."""
    from dotenv import load_dotenv

    load_dotenv()
    import mysql.connector
    from backend.db import _connection_kwargs
    from backend.payroll_payout_details import parse_line_payout_details

    try:
        conn = mysql.connector.connect(**_connection_kwargs())
    except Exception:
        return  # skip when DB unavailable
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT pbl.*, pb.pay_period_start, pb.worker_category
            FROM payout_batch_lines pbl
            JOIN payout_batches pb ON pb.id = pbl.batch_id
            WHERE pbl.id=487 AND pbl.batch_id=85 AND pbl.user_id=30
              AND pb.organization_id=3
            """
        )
        row = cur.fetchone()
        assert row is not None
        details = parse_line_payout_details(row)
        err = validate_employer_taxes_for_period(
            conn,
            3,
            user_id=30,
            gross=float(row["gross_amount"]),
            details=details,
            worker_name=str(row.get("worker_name_snapshot") or ""),
            pay_period_start=str(row.get("pay_period_start") or ""),
            pay_frequency="weekly",
            worker_category="w2",
            require_reconcile=True,
        )
        assert err is None, err
        assert abs(sum_employer_taxes(details) - 99.44) < 0.02
    finally:
        conn.close()


def test_aug10_period_cost_correct_after_evelin_repair():
    from dotenv import load_dotenv

    load_dotenv()
    import mysql.connector
    from backend.db import _connection_kwargs
    from backend.payroll_report import build_report_row
    from backend.payroll_report_analytics import aggregate_period_metrics

    try:
        conn = mysql.connector.connect(**_connection_kwargs())
    except Exception:
        return
    try:
        cur = conn.cursor(dictionary=True)
        rows = []
        for bid in (85, 91, 108):
            cur.execute("SELECT * FROM payout_batches WHERE id=%s AND organization_id=3", (bid,))
            batch = cur.fetchone()
            assert batch is not None
            cur.execute("SELECT * FROM payout_batch_lines WHERE batch_id=%s", (bid,))
            for ln in cur.fetchall():
                rows.append(build_report_row(batch, ln, report_type="payroll_period"))
        m = aggregate_period_metrics(rows)
        assert abs(float(m["gross_pay"]) - 9284.31) < 0.01
        assert abs(float(m["total_hours"]) - 519.76) < 0.01
        # Evelin ER repair (−$393.15) + Varun FUTA wage-base reconcile (−$5.48)
        assert abs(float(m["total_payroll_cost"]) - 9681.20) < 0.05
        assert float(m["total_payroll_cost"]) < 9700.0
        assert float(m["total_payroll_cost"]) > 9675.0
    finally:
        conn.close()
