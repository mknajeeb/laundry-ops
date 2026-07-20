"""Phase 1 Payroll Reporting: official_pay_date membership and total payroll cost."""

from unittest.mock import MagicMock, patch

import pytest

from backend.payroll_report import (
    DATE_MATCH_RULE,
    build_report_row,
    date_match_rule_text,
    query_payroll_report,
)


def _line_raw(**overrides):
    base = {
        "batch_id": 1,
        "batch_name": "W2 cross-month",
        "worker_category": "w2",
        "pay_period_start": "2026-05-29",
        "pay_period_end": "2026-06-05",
        "batch_status": "paid",
        "payout_details_finalized_at": "2026-06-08",
        "official_pay_date": "2026-06-10",
        "line_id": 10,
        "user_id": 7,
        "worker_name_snapshot": "Ada",
        "approved_hours": 40,
        "ot_hours": 0,
        "rate": 20,
        "ot_rate": 0,
        "gross_amount": 800,
        "total_amount": 800,
        "gross_wages": 800,
        "sick_pay_amount": 0,
        "bonus_tip_amount": 0,
        "reimbursement_amount": 0,
        "adjustments": 0,
        "payment_status": "paid",
        "net_pay": 750,
        "payout_details_json": (
            '{"employee_deductions":{"fit":50},'
            '"employer_taxes":{"er_ss":49.60,"er_medicare":11.60}}'
        ),
    }
    base.update(overrides)
    return base


def test_monthly_paid_assigns_by_official_pay_date():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.fetchall.return_value = [_line_raw()]
    cursor.fetchone.return_value = {"cnt": 0}

    executed = []

    def capture_execute(sql, params=None):
        executed.append((sql, params))

    cursor.execute.side_effect = capture_execute

    with patch("backend.payroll_operations.ensure_payout_batches_tables"), patch(
        "backend.payroll_report.table_has_column", return_value=True
    ):
        report = query_payroll_report(
            conn, 3, report_type="monthly_paid", month=6, year=2026
        )

    assert report["report_type"] == "monthly_paid"
    assert report["count"] == 1
    assert report["rows"][0]["pay_date"] == "2026-06-10"
    assert report["rows"][0]["pay_period_start"] == "2026-05-29"
    main_sql = executed[0][0]
    assert "MONTH(pb.official_pay_date)" in main_sql
    assert "official_pay_date IS NOT NULL" in main_sql
    assert "month and year" in date_match_rule_text("monthly_paid").lower()


def test_cross_month_period_june_pay_date_belongs_to_june():
    """Period May 29–Jun 5 with official_pay_date Jun 10 → fully June monthly report."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.fetchall.return_value = [_line_raw(official_pay_date="2026-06-10")]
    cursor.fetchone.return_value = {"cnt": 2}

    with patch("backend.payroll_operations.ensure_payout_batches_tables"), patch(
        "backend.payroll_report.table_has_column", return_value=True
    ):
        june = query_payroll_report(conn, 3, month=6, year=2026)

    assert june["report_type"] == "monthly_paid"
    assert june["count"] == 1
    assert june["rows"][0]["pay_date"] == "2026-06-10"
    assert june["rows"][0]["pay_period_start"] == "2026-05-29"
    assert june["excluded_missing_pay_date_count"] == 2

    # May monthly SQL asks for month=5; empty result set means not in May
    executed = []
    cursor.execute.side_effect = lambda sql, params=None: executed.append(
        (sql, list(params or []))
    )
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = {"cnt": 2}
    with patch("backend.payroll_operations.ensure_payout_batches_tables"), patch(
        "backend.payroll_report.table_has_column", return_value=True
    ):
        may_empty = query_payroll_report(conn, 3, month=5, year=2026)
    assert may_empty["count"] == 0
    assert executed[0][1][2:4] == [5, 2026]


def test_finalize_blocked_without_pay_date():
    from backend.payroll_payout_details import finalize_payout_details

    conn = MagicMock()
    with patch(
        "backend.payroll_payout_details.ensure_payout_details_columns",
    ), patch(
        "backend.payroll_payout_details.get_payout_batch",
        return_value={
            "id": 1,
            "status": "approved_for_payment",
            "payout_details_finalized_at": None,
            "official_pay_date": None,
        },
    ):
        with pytest.raises(ValueError, match="Official Pay Date"):
            finalize_payout_details(
                conn, 1, 1, actor_id=9, official_pay_date=None, confirm_pay_date=True
            )


def test_missing_official_pay_date_flagged_and_excluded_from_monthly():
    batch = {
        "id": 1,
        "batch_name": "Legacy",
        "worker_category": "w2",
        "pay_period_start": "2026-06-01",
        "pay_period_end": "2026-06-07",
        "status": "paid",
        "payout_details_finalized_at": "2026-06-08",
        "official_pay_date": None,
    }
    line = {
        "id": 1,
        "user_id": 1,
        "worker_name_snapshot": "Missing",
        "approved_hours": 40,
        "ot_hours": 0,
        "rate": 20,
        "gross_amount": 800,
        "payment_status": "paid",
        "payout_details_json": '{"payment":{"date":"2026-06-07"}}',
    }
    row = build_report_row(batch, line)
    assert row["pay_date"] == ""
    assert row["pay_date_missing"] is True
    assert row["pay_date_display"] == "Pay Date Missing"
    # JSON payment.date / period end must not become reporting pay_date
    assert row["pay_date"] != "2026-06-07"

    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    # Monthly SQL excludes NULL official_pay_date — mock returns empty
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = {"cnt": 3}
    with patch("backend.payroll_operations.ensure_payout_batches_tables"), patch(
        "backend.payroll_report.table_has_column", return_value=True
    ):
        report = query_payroll_report(conn, 3, report_type="monthly_paid", month=6, year=2026)
    assert report["count"] == 0
    assert report["excluded_missing_pay_date_count"] == 3


def test_set_official_pay_date_creates_audit_with_reason():
    from backend.payroll_payout_details import set_official_pay_date

    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    batch = {
        "id": 1,
        "organization_id": 1,
        "status": "paid",
        "payout_details_finalized_at": "2026-06-08",
        "official_pay_date": None,
        "payout_details_audit_json": None,
    }
    details = {**batch, "lines": []}

    with patch(
        "backend.payroll_payout_details.ensure_payout_details_columns",
    ), patch(
        "backend.payroll_payout_details.get_payout_batch",
        return_value=batch,
    ), patch(
        "backend.payroll_payout_details.get_payout_batch_details",
        return_value=details,
    ):
        set_official_pay_date(
            conn,
            1,
            1,
            actor_id=42,
            official_pay_date="2026-06-10",
            reason="Finance confirmed actual payday",
        )

    assert cursor.execute.called
    sql, params = cursor.execute.call_args[0]
    assert "official_pay_date=%s" in sql.replace(" ", "")
    assert params[0] == "2026-06-10"
    audit_json = params[1]
    assert "Finance confirmed actual payday" in audit_json
    assert "official_pay_date_set" in audit_json
    assert "2026-06-10" in audit_json


def test_total_payroll_cost_gross_plus_employer_taxes():
    batch = {
        "id": 1,
        "batch_name": "W2",
        "worker_category": "w2",
        "pay_period_start": "2026-07-06",
        "pay_period_end": "2026-07-12",
        "status": "paid",
        "official_pay_date": "2026-07-15",
    }
    line = {
        "id": 1,
        "user_id": 1,
        "worker_name_snapshot": "W2 Emp",
        "approved_hours": 40,
        "ot_hours": 0,
        "rate": 20,
        "gross_amount": 800,
        "payment_status": "paid",
        "payout_details_json": (
            '{"employer_taxes":{"er_ss":49.60,"er_medicare":11.60},'
            '"employee_deductions":{"fit":100}}'
        ),
    }
    row = build_report_row(batch, line)
    assert row["gross_pay"] == 800.0
    assert row["employer_taxes"] == 61.2
    assert row["employee_tax_deductions"] == 100.0
    # Employee withholding is not added on top of gross for total payroll cost
    assert row["total_payroll_cost"] == 861.2


def test_1099_no_employer_tax_total_equals_gross():
    batch = {
        "id": 2,
        "batch_name": "1099",
        "worker_category": "contractor_1099",
        "pay_period_start": "2026-07-06",
        "pay_period_end": "2026-07-12",
        "status": "paid",
        "official_pay_date": "2026-07-14",
    }
    line = {
        "id": 2,
        "user_id": 2,
        "worker_name_snapshot": "Contractor",
        "approved_hours": 40,
        "ot_hours": 0,
        "rate": 25,
        "gross_amount": 1000,
        "payment_status": "paid",
        "payout_details_json": "{}",
    }
    row = build_report_row(batch, line)
    assert row["employer_taxes"] == 0.0
    assert row["total_payroll_cost"] == row["gross_pay"] == 1000.0


def test_custom_range_pay_date_vs_period_overlap():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    # Period Jun 29–Jul 5; official pay date Jul 8
    cursor.fetchall.return_value = [
        _line_raw(
            batch_id=2,
            line_id=3,
            pay_period_start="2026-06-29",
            pay_period_end="2026-07-05",
            official_pay_date="2026-07-08",
            worker_name_snapshot="Dan",
        )
    ]

    with patch("backend.payroll_operations.ensure_payout_batches_tables"), patch(
        "backend.payroll_report.table_has_column", return_value=True
    ):
        by_pay = query_payroll_report(
            conn,
            3,
            date_from="2026-07-01",
            date_to="2026-07-07",
            date_basis="pay_date",
        )
        by_period = query_payroll_report(
            conn,
            3,
            date_from="2026-07-01",
            date_to="2026-07-07",
            date_basis="period_overlap",
        )

    assert by_pay["report_type"] == "custom_range"
    assert by_pay["count"] == 0  # pay date Jul 8 outside Jul 1–7
    assert "overlap" not in by_pay["date_match_rule"].lower()
    assert DATE_MATCH_RULE in (by_pay["date_match_rule"], DATE_MATCH_RULE)

    assert by_period["count"] == 1  # period overlaps early July
    assert "overlap" in by_period["date_match_rule"].lower()


def test_no_period_end_fallback_in_report_pay_date():
    batch = {
        "id": 9,
        "batch_name": "No OPD",
        "worker_category": "w2",
        "pay_period_start": "2026-07-06",
        "pay_period_end": "2026-07-12",
        "status": "paid",
        "payout_details_finalized_at": "2026-07-13",
        # intentionally no official_pay_date
    }
    line = {
        "id": 9,
        "user_id": 9,
        "worker_name_snapshot": "NoFallback",
        "approved_hours": 40,
        "ot_hours": 0,
        "rate": 20,
        "gross_amount": 800,
        "payment_status": "paid",
        "payout_details_json": '{"payment":{"date":"2026-07-12"}}',
    }
    row = build_report_row(batch, line)
    assert row["pay_date"] == ""
    assert row["official_pay_date"] == ""
    assert row["pay_date_missing"] is True
    assert row["pay_date_display"] == "Pay Date Missing"
    assert row["pay_date"] != row["pay_period_end"]
