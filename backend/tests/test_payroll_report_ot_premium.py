"""OT premium display helpers and payroll report presentation tests.

Does not change stored gross — only how OT is labeled for register/report/exports.
"""

from io import BytesIO
from unittest.mock import MagicMock, patch

from openpyxl import load_workbook

from backend.payroll_overtime import (
    compute_earnings_breakdown,
    compute_overtime_premium,
    compute_wage_with_overtime,
    earnings_breakdown_from_line,
)
from backend.payroll_report import (
    DATE_MATCH_RULE,
    build_payroll_report_html,
    build_payroll_report_xlsx,
    build_report_row,
)


def test_ot_premium_time_and_a_half_example():
    """$20/hr × 1 OT hour @ $30 → premium $10 (not $30)."""
    premium = compute_overtime_premium(1, 20, 30)
    assert float(premium) == 10.0
    premium_half = compute_overtime_premium(1, 20)  # default 1.5×
    assert float(premium_half) == 10.0


def test_no_overtime_premium_is_zero():
    assert float(compute_overtime_premium(0, 20, 30)) == 0.0
    br = compute_earnings_breakdown(regular_hours=40, ot_hours=0, regular_rate=20, gross_pay=800)
    assert float(br["ot_premium"]) == 0.0
    assert float(br["base_earnings"]) == 800.0
    assert float(br["gross_pay"]) == 800.0
    assert abs(br["base_earnings"] + br["ot_premium"] + br["other_earnings"] - br["gross_pay"]) < 0.01


def test_ot_hours_premium_and_reconciliation():
    # 40 reg + 5 OT @ $20 / $30
    gross = float(compute_wage_with_overtime(40, 5, 20, 30))
    assert gross == 950.0  # 800 + 150
    br = compute_earnings_breakdown(
        regular_hours=40, ot_hours=5, regular_rate=20, ot_rate=30, gross_pay=gross
    )
    assert float(br["base_earnings"]) == 900.0  # 45 × 20
    assert float(br["ot_premium"]) == 50.0  # 5 × 10
    assert float(br["other_earnings"]) == 0.0
    assert float(br["gross_pay"]) == 950.0
    assert abs(br["base_earnings"] + br["ot_premium"] + br["other_earnings"] - br["gross_pay"]) < 0.01


def test_different_regular_and_ot_rates():
    br = compute_earnings_breakdown(
        regular_hours=40, ot_hours=2, regular_rate=17, ot_rate=25.50, gross_pay=731.0
    )
    assert float(br["ot_premium"]) == 17.0  # 2 × 8.50
    assert float(br["base_earnings"]) == 714.0  # 42 × 17
    assert abs(br["base_earnings"] + br["ot_premium"] + br["other_earnings"] - br["gross_pay"]) < 0.01


def test_1099_time_and_a_half_after_40():
    """1099 contractor receiving 1.5× after 40 — same premium math."""
    br = compute_earnings_breakdown(
        regular_hours=40, ot_hours=8.65, regular_rate=17, ot_rate=25.50, gross_pay=900.58
    )
    assert float(br["ot_premium"]) == 73.53  # 8.65 × 8.50
    assert float(br["base_earnings"]) == 827.05  # 48.65 × 17
    assert abs(br["base_earnings"] + br["ot_premium"] + br["other_earnings"] - 900.58) < 0.02
    # Gross calculation itself unchanged
    assert float(compute_wage_with_overtime(40, 8.65, 17, 25.50)) == 900.58


def test_earnings_breakdown_from_line_matches_gross():
    line = {
        "approved_hours": 40,
        "ot_hours": 5,
        "rate": 20,
        "ot_rate": 30,
        "gross_amount": 950,
        "sick_pay_amount": 0,
        "bonus_tip_amount": 0,
        "reimbursement_amount": 0,
        "adjustments": 0,
    }
    br = earnings_breakdown_from_line(line)
    assert float(br["ot_premium"]) == 50.0
    assert abs(br["base_earnings"] + br["ot_premium"] + br["other_earnings"] - br["gross_pay"]) < 0.01


def test_other_earnings_included_in_reconciliation():
    line = {
        "approved_hours": 40,
        "ot_hours": 0,
        "rate": 20,
        "gross_amount": 850,
        "sick_pay_amount": 50,
    }
    br = earnings_breakdown_from_line(line)
    assert float(br["base_earnings"]) == 800.0
    assert float(br["ot_premium"]) == 0.0
    assert float(br["other_earnings"]) == 50.0
    assert float(br["gross_pay"]) == 850.0


def test_report_row_ot_premium_and_labels():
    batch = {
        "id": 1,
        "batch_name": "W-2 week",
        "worker_category": "w2",
        "pay_period_start": "2026-07-06",
        "pay_period_end": "2026-07-12",
        "status": "approved_for_payment",
        "payout_details_finalized_at": "2026-07-13",
    }
    line = {
        "id": 10,
        "user_id": 99,
        "worker_name_snapshot": "Ada",
        "approved_hours": 40,
        "ot_hours": 1,
        "rate": 20,
        "ot_rate": 30,
        "gross_amount": 830,
        "payment_status": "paid",
        "payout_details_json": '{"payment":{"date":"2026-07-15"},"employee_deductions":{"fit":50}}',
    }
    row = build_report_row(batch, line)
    assert row["ot_premium"] == 10.0
    assert row["base_earnings"] == 820.0
    assert abs(row["base_earnings"] + row["ot_premium"] + row["other_earnings"] - row["gross_pay"]) < 0.01
    assert row["pay_date"] == "2026-07-15"
    assert "W-2" in row["employee_category"]


def test_excel_export_includes_totals_and_ot_premium():
    report = {
        "filters": {"all_history": True, "worker_category": "all"},
        "date_match_rule": DATE_MATCH_RULE,
        "rows": [
            {
                "employee_name": "Ada",
                "employee_category": "W-2 Employee",
                "payroll_period": "2026-07-06 – 2026-07-12",
                "pay_date": "2026-07-15",
                "regular_hours": 40,
                "ot_hours": 1,
                "base_earnings": 820,
                "ot_premium": 10,
                "other_earnings": 0,
                "gross_pay": 830,
                "employee_tax_deductions": 50,
                "other_deductions": 0,
                "net_pay": 780,
                "employer_taxes": 60,
                "payment_status": "Paid",
                "payroll_status": "Ready To Pay",
            }
        ],
        "totals": {
            "regular_hours": 40,
            "ot_hours": 1,
            "base_earnings": 820,
            "ot_premium": 10,
            "other_earnings": 0,
            "gross_pay": 830,
            "employee_tax_deductions": 50,
            "other_deductions": 0,
            "net_pay": 780,
            "employer_taxes": 60,
        },
    }
    data = build_payroll_report_xlsx(report)
    wb = load_workbook(BytesIO(data))
    ws = wb.active
    headers = [c.value for c in ws[5]]
    assert "OT premium" in headers
    assert "Regular/Base earnings" in headers
    # Find totals row
    found_total = False
    for row in ws.iter_rows(min_row=6, values_only=True):
        if row and row[0] == "Totals":
            found_total = True
            # ot_premium column index
            ot_idx = headers.index("OT premium")
            assert float(row[ot_idx]) == 10.0
            gross_idx = headers.index("Gross pay")
            assert float(row[gross_idx]) == 830.0
    assert found_total


def test_pdf_html_export_includes_totals_and_premium_note():
    report = {
        "filters": {
            "date_from": "2026-07-01",
            "date_to": "2026-07-31",
            "all_history": False,
            "worker_category": "all",
        },
        "date_match_rule": DATE_MATCH_RULE,
        "rows": [
            {
                "employee_name": "Bob",
                "employee_category": "1099 Contractor",
                "payroll_period": "2026-07-06 – 2026-07-12",
                "pay_date": "2026-07-14",
                "regular_hours": 40,
                "ot_hours": 2,
                "base_earnings": 840,
                "ot_premium": 20,
                "other_earnings": 0,
                "gross_pay": 860,
                "employee_tax_deductions": 0,
                "other_deductions": 0,
                "net_pay": 860,
                "employer_taxes": 0,
                "payment_status": "Pending",
                "payroll_status": "Draft",
            }
        ],
        "totals": {
            "regular_hours": 40,
            "ot_hours": 2,
            "base_earnings": 840,
            "ot_premium": 20,
            "other_earnings": 0,
            "gross_pay": 860,
            "employee_tax_deductions": 0,
            "other_deductions": 0,
            "net_pay": 860,
            "employer_taxes": 0,
        },
    }
    html = build_payroll_report_html(report)
    assert "OT Premium" in html or "OT premium" in html
    assert "$20.00" in html
    assert "Totals" in html
    assert "$860.00" in html
    assert "additional amount" in html.lower() or "regular hourly rate" in html.lower()


def test_register_gross_matches_payroll_record():
    """Register display gross equals stored line gross (no recalculation drift)."""
    line = {
        "approved_hours": 40,
        "ot_hours": 8.65,
        "rate": 17,
        "ot_rate": 25.50,
        "gross_amount": 900.58,
    }
    br = earnings_breakdown_from_line(line)
    assert float(br["gross_pay"]) == 900.58
    assert abs(br["base_earnings"] + br["ot_premium"] + br["other_earnings"] - 900.58) < 0.02


def test_date_range_rule_documented():
    assert "pay period" in DATE_MATCH_RULE.lower()
    assert "pay date" in DATE_MATCH_RULE.lower()


def test_ot_premium_edge_cases_never_negative():
    # Missing OT rate → time-and-a-half premium
    br = compute_earnings_breakdown(regular_hours=40, ot_hours=2, regular_rate=20, ot_rate=None, gross_pay=860)
    assert float(br["ot_premium"]) == 20.0
    assert br["ot_premium"] >= 0

    # OT rate equal to regular → premium 0
    br_eq = compute_earnings_breakdown(
        regular_hours=40, ot_hours=2, regular_rate=20, ot_rate=20, gross_pay=840
    )
    assert float(br_eq["ot_premium"]) == 0.0
    assert abs(br_eq["base_earnings"] + br_eq["ot_premium"] + br_eq["other_earnings"] - 840) < 0.01

    # OT rate lower than regular → premium 0, base uses actual OT wages
    br_low = compute_earnings_breakdown(
        regular_hours=40, ot_hours=10, regular_rate=20, ot_rate=15, gross_pay=950
    )
    assert float(br_low["ot_premium"]) == 0.0
    assert float(br_low["base_earnings"]) == 950.0
    assert abs(br_low["base_earnings"] + br_low["ot_premium"] + br_low["other_earnings"] - 950) < 0.01

    # Zero / negative OT hours
    assert float(compute_overtime_premium(0, 20, 30)) == 0.0
    assert float(compute_overtime_premium(-5, 20, 30)) == 0.0

    # Salaried / non-hourly
    br_sal = compute_earnings_breakdown(
        regular_hours=0, ot_hours=0, regular_rate=0, gross_pay=1200
    )
    assert float(br_sal["ot_premium"]) == 0.0
    assert float(br_sal["base_earnings"]) == 0.0
    assert float(br_sal["other_earnings"]) == 1200.0


def test_excel_uses_numeric_and_date_cells():
    from datetime import date

    report = {
        "filters": {"date_from": "2026-07-01", "date_to": "2026-07-31"},
        "date_match_rule": DATE_MATCH_RULE,
        "rows": [
            {
                "employee_name": "Ada",
                "employee_category": "W-2 Employee",
                "payroll_period": "2026-07-06 – 2026-07-12",
                "pay_date": "2026-07-15",
                "regular_hours": 40,
                "ot_hours": 1,
                "base_earnings": 820.0,
                "ot_premium": 10.0,
                "other_earnings": 0.0,
                "gross_pay": 830.0,
                "employee_tax_deductions": 50.5,
                "other_deductions": 0.0,
                "net_pay": 779.5,
                "employer_taxes": 60.0,
                "payment_status": "Paid",
                "payroll_status": "Ready To Pay",
            }
        ],
        "totals": {
            "regular_hours": 40,
            "ot_hours": 1,
            "base_earnings": 820.0,
            "ot_premium": 10.0,
            "other_earnings": 0.0,
            "gross_pay": 830.0,
            "employee_tax_deductions": 50.5,
            "other_deductions": 0.0,
            "net_pay": 779.5,
            "employer_taxes": 60.0,
        },
    }
    data = build_payroll_report_xlsx(report)
    wb = load_workbook(BytesIO(data))
    ws = wb.active
    headers = [c.value for c in ws[5]]
    # Row 6 is first data row
    pay_date_idx = headers.index("Pay date") + 1
    gross_idx = headers.index("Gross pay") + 1
    ot_idx = headers.index("OT premium") + 1
    cell_date = ws.cell(row=6, column=pay_date_idx)
    cell_gross = ws.cell(row=6, column=gross_idx)
    cell_ot = ws.cell(row=6, column=ot_idx)
    assert isinstance(cell_date.value, date)
    assert isinstance(cell_gross.value, (int, float))
    assert not isinstance(cell_gross.value, str)
    assert float(cell_ot.value) == 10.0
    # Totals row matches filtered report totals
    assert float(ws.cell(row=7, column=gross_idx).value) == 830.0


def test_pdf_and_screen_totals_match_exactly():
    totals = {
        "regular_hours": 80.5,
        "ot_hours": 3.25,
        "base_earnings": 1670.0,
        "ot_premium": 32.5,
        "other_earnings": 10.0,
        "gross_pay": 1712.5,
        "employee_tax_deductions": 100.0,
        "other_deductions": 5.0,
        "net_pay": 1607.5,
        "employer_taxes": 80.0,
    }
    report = {
        "filters": {"date_from": "2026-07-01", "date_to": "2026-07-31"},
        "date_match_rule": DATE_MATCH_RULE,
        "rows": [],
        "totals": totals,
    }
    html = build_payroll_report_html(report)
    assert "thead" in html and "table-header-group" in html
    assert "page-break-inside: avoid" in html
    assert "tfoot" in html
    assert "$1,712.50" in html
    assert "$32.50" in html
    xlsx = build_payroll_report_xlsx({**report, "rows": []})
    wb = load_workbook(BytesIO(xlsx))
    ws = wb.active
    headers = [c.value for c in ws[5]]
    gross_idx = headers.index("Gross pay") + 1
    # totals appended after empty data
    assert float(ws.cell(row=6, column=gross_idx).value) == 1712.5


def test_date_range_match_does_not_duplicate_line():
    """Pay period overlap AND pay date in range → still one row per line_id."""
    from backend.payroll_report import query_payroll_report

    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    # Same line returned once from SQL (normal case); filter matches both rules
    cursor.fetchall.return_value = [
        {
            "batch_id": 1,
            "batch_name": "W2",
            "worker_category": "w2",
            "pay_period_start": "2026-07-06",
            "pay_period_end": "2026-07-12",
            "batch_status": "paid",
            "payout_details_finalized_at": "2026-07-13",
            "line_id": 99,
            "user_id": 5,
            "worker_name_snapshot": "Eve",
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
            "net_pay": 800,
            "payout_details_json": '{"payment":{"date":"2026-07-10"}}',
        },
        # Simulate accidental duplicate SQL row for same line_id
        {
            "batch_id": 1,
            "batch_name": "W2",
            "worker_category": "w2",
            "pay_period_start": "2026-07-06",
            "pay_period_end": "2026-07-12",
            "batch_status": "paid",
            "payout_details_finalized_at": "2026-07-13",
            "line_id": 99,
            "user_id": 5,
            "worker_name_snapshot": "Eve",
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
            "net_pay": 800,
            "payout_details_json": '{"payment":{"date":"2026-07-10"}}',
        },
    ]
    with patch("backend.payroll_operations.ensure_payout_batches_tables"), patch(
        "backend.payroll_report.table_has_column", return_value=True
    ):
        report = query_payroll_report(
            conn, 3, date_from="2026-07-06", date_to="2026-07-12"
        )
    assert report["count"] == 1
    assert len(report["rows"]) == 1


def test_query_payroll_report_filters_periods_and_categories():
    """Smoke-test query assembly with a mocked cursor."""
    from backend.payroll_report import query_payroll_report

    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.fetchall.return_value = [
        {
            "batch_id": 1,
            "batch_name": "1099",
            "worker_category": "contractor_1099",
            "pay_period_start": "2026-07-06",
            "pay_period_end": "2026-07-12",
            "batch_status": "hours_reviewed",
            "payout_details_finalized_at": None,
            "line_id": 2,
            "user_id": 5,
            "worker_name_snapshot": "Cara",
            "approved_hours": 40,
            "ot_hours": 4,
            "rate": 20,
            "ot_rate": 30,
            "gross_amount": 920,
            "total_amount": 920,
            "gross_wages": 920,
            "sick_pay_amount": 0,
            "bonus_tip_amount": 0,
            "reimbursement_amount": 0,
            "adjustments": 0,
            "payment_status": "pending",
            "net_pay": 920,
            "payout_details_json": None,
        },
        {
            "batch_id": 2,
            "batch_name": "W2 other week",
            "worker_category": "w2",
            "pay_period_start": "2026-06-29",
            "pay_period_end": "2026-07-05",
            "batch_status": "paid",
            "payout_details_finalized_at": "2026-07-06",
            "line_id": 3,
            "user_id": 6,
            "worker_name_snapshot": "Dan",
            "approved_hours": 40,
            "ot_hours": 0,
            "rate": 18,
            "ot_rate": 0,
            "gross_amount": 720,
            "total_amount": 720,
            "gross_wages": 720,
            "sick_pay_amount": 0,
            "bonus_tip_amount": 0,
            "reimbursement_amount": 0,
            "adjustments": 0,
            "payment_status": "paid",
            "net_pay": 700,
            "payout_details_json": '{"payment":{"date":"2026-07-08"}}',
        },
    ]
    with patch("backend.payroll_operations.ensure_payout_batches_tables"), patch(
        "backend.payroll_report.table_has_column", return_value=True
    ):
        # Multi-period: only first period pair requested
        multi = query_payroll_report(
            conn,
            3,
            period_starts=["2026-07-06"],
            period_ends=["2026-07-12"],
        )
        # SQL filter applied; mock still returns both — exercise builder
        assert "rows" in multi
        assert multi["date_match_rule"]

        # Custom date range covering pay date of second row
        cursor.fetchall.return_value = cursor.fetchall.return_value  # same data
        ranged = query_payroll_report(
            conn,
            3,
            date_from="2026-07-07",
            date_to="2026-07-10",
        )
        # Only Dan has pay_date 2026-07-08 in range; Cara period overlaps Jul 7–10 too
        names = {r["employee_name"] for r in ranged["rows"]}
        assert "Cara" in names or "Dan" in names
        for r in ranged["rows"]:
            assert abs(
                r["base_earnings"] + r["ot_premium"] + r["other_earnings"] - r["gross_pay"]
            ) < 0.02
