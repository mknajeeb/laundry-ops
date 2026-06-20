"""Tests for payout details, accountant confirmation, paystub workflow."""

from unittest.mock import MagicMock, patch

from backend.payroll_payout_details import (
    batch_ready_for_payout_details,
    can_confirm_accountant_payment,
    can_edit_payout_details,
    can_generate_paystub_for_line,
    can_generate_receipt_for_line,
    can_process_accountant_batch,
    can_view_accountant_queue,
    compute_line_totals,
    compute_tax_withheld_breakdown,
    confirm_accountant_payment,
    enrich_line_settlement_fields,
    finalize_payout_details,
    finalize_blockers,
    unfinalize_payout_details,
    is_accountant_batch_list_view,
    line_document_state,
    line_uses_payment_receipt,
    parse_line_payout_details,
    payout_workflow_state,
    receipt_required_for_line,
    set_batch_document_mode,
    sum_employee_deductions,
    sum_employer_taxes,
    update_payout_batch_details,
)


def test_sum_employee_deductions():
    details = {
        "employee_deductions": {
            "fit": 100,
            "ss": 50,
            "medicare": 10,
            "state": 20,
            "local": 5,
            "other1": 0,
            "other2": 0,
        }
    }
    assert sum_employee_deductions(details) == 185.0


def test_sum_employer_taxes():
    details = {
        "employer_taxes": {
            "er_ss": 50,
            "er_medicare": 10,
            "futa": 5,
            "suta": 15,
            "other": 0,
        }
    }
    assert sum_employer_taxes(details) == 80.0


def test_employer_cost_formula():
    line = {"gross_amount": 1000}
    details = parse_line_payout_details(
        {
            "payout_details_json": {
                "employer_taxes": {
                    "er_ss": 62,
                    "er_medicare": 14.5,
                    "futa": 6,
                    "suta": 40,
                    "other": 0,
                }
            }
        }
    )
    totals = compute_line_totals(line, details)
    assert totals["total_employer_taxes"] == 122.5
    assert totals["employer_cost"] == 1122.5


def test_settlement_scenario_a_full_payment():
    """Scenario A: full net paid, no withholding."""
    line = {"gross_amount": 800}
    details = parse_line_payout_details(
        {
            "payout_details_json": {
                "employee_deductions": {"fit": 80, "ss": 40, "medicare": 10},
                "settlement": {
                    "amount_paid": 670,
                    "amount_withheld": 0,
                    "outstanding_balance": 0,
                    "prior_unpaid_taxes": 0,
                },
            }
        }
    )
    totals = compute_line_totals(line, details)
    assert totals["net_pay"] == 670.0
    assert totals["amount_paid"] == 670.0
    assert totals["outstanding_balance"] == 0.0


def test_settlement_scenario_b_withheld():
    """Current-period withholding follows deductions; catch-up is separate."""
    line = {"gross_amount": 1000}
    details = parse_line_payout_details(
        {
            "gross_amount": 1000,
            "payout_details_json": {
                "employee_deductions": {"fit": 200},
                "settlement": {
                    "catch_up_withholding": 0,
                    "prior_unpaid_taxes": 0,
                },
            },
        }
    )
    totals = compute_line_totals(line, details)
    assert totals["net_pay"] == 800.0
    assert totals["amount_withheld"] == 200.0
    assert totals["amount_paid"] == 800.0
    assert totals["outstanding_balance"] == 0.0


def test_settlement_scenario_c_prior_unpaid_catchup():
    """Scenario C: prior unpaid taxes reduce net settlement."""
    line = {"gross_amount": 500}
    details = parse_line_payout_details(
        {
            "payout_details_json": {
                "employee_deductions": {"fit": 50},
                "settlement": {
                    "amount_paid": 400,
                    "amount_withheld": 0,
                    "outstanding_balance": 0,
                    "prior_unpaid_taxes": 50,
                },
            }
        }
    )
    totals = compute_line_totals(line, details)
    assert totals["prior_unpaid_taxes"] == 50.0
    assert totals["net_pay"] == 450.0


def test_payout_workflow_state_transitions():
    batch = {"status": "approved_for_payment"}
    wf = payout_workflow_state(batch)
    assert wf["awaiting_accountant_confirmation"] is True
    assert wf["can_edit_details"] is True
    assert wf["paystub_available"] is False

    batch2 = {
        "status": "approved_for_payment",
        "accountant_payment_confirmed_at": "2026-06-19",
    }
    wf2 = payout_workflow_state(batch2)
    assert wf2["can_edit_details"] is True
    assert wf2["awaiting_accountant_confirmation"] is False
    assert wf2["paystub_available"] is False

    batch3 = {
        "status": "paid",
        "accountant_payment_confirmed_at": "2026-06-19",
        "payout_details_finalized_at": "2026-06-20",
        "document_mode": "official_paystub",
    }
    wf3 = payout_workflow_state(batch3)
    assert wf3["paystub_available"] is True
    assert wf3["payment_receipt_available"] is False
    assert wf3["can_edit_details"] is False

    batch4 = {
        "status": "paid",
        "accountant_payment_confirmed_at": "2026-06-19",
        "payout_details_finalized_at": "2026-06-20",
        "document_mode": "payment_receipt",
    }
    wf4 = payout_workflow_state(batch4)
    assert wf4["paystub_available"] is False
    assert wf4["payment_receipt_available"] is True


def test_can_confirm_accountant_payment_role():
    conn = MagicMock()
    with patch(
        "backend.payroll_payout_details.user_role_codes",
        return_value={"ACCOUNTANT"},
    ), patch(
        "backend.ta_routes.user_has_perm",
        return_value=True,
    ):
        assert can_confirm_accountant_payment(conn, 1) is True

    with patch(
        "backend.payroll_payout_details.user_role_codes",
        return_value={"ADMIN"},
    ), patch(
        "backend.ta_routes.user_has_perm",
        return_value=True,
    ):
        assert can_confirm_accountant_payment(conn, 1) is False


def test_can_view_accountant_queue_roles():
    conn = MagicMock()
    for role in ("ADMIN", "PAYROLL_ADMIN", "SUPER_ADMIN"):
        with patch(
            "backend.payroll_payout_details.user_role_codes",
            return_value={role},
        ):
            assert can_view_accountant_queue(conn, 1) is True

    with patch(
        "backend.payroll_payout_details.user_role_codes",
        return_value={"ACCOUNTANT"},
    ), patch(
        "backend.ta_routes.user_has_perm",
        return_value=True,
    ):
        assert can_view_accountant_queue(conn, 1) is True

    with patch(
        "backend.payroll_payout_details.user_role_codes",
        return_value={"EMPLOYEE"},
    ):
        assert can_view_accountant_queue(conn, 1) is False


def test_is_accountant_batch_list_view():
    conn = MagicMock()
    with patch(
        "backend.payroll_payout_details.user_role_codes",
        return_value={"ACCOUNTANT"},
    ):
        assert is_accountant_batch_list_view(conn, 1) is True

    with patch(
        "backend.payroll_payout_details.user_role_codes",
        return_value={"ACCOUNTANT", "ADMIN"},
    ):
        assert is_accountant_batch_list_view(conn, 1) is False

    with patch(
        "backend.payroll_payout_details.user_role_codes",
        return_value={"PAYROLL_ADMIN"},
    ):
        assert is_accountant_batch_list_view(conn, 1) is False


def test_can_process_accountant_batch_role():
    conn = MagicMock()
    with patch(
        "backend.payroll_payout_details.user_role_codes",
        return_value={"ACCOUNTANT"},
    ), patch(
        "backend.ta_routes.user_has_perm",
        return_value=True,
    ):
        assert can_process_accountant_batch(conn, 1) is True

    with patch(
        "backend.payroll_payout_details.user_role_codes",
        return_value={"ADMIN"},
    ):
        assert can_process_accountant_batch(conn, 1) is False


def test_can_edit_payout_details_admin():
    conn = MagicMock()
    with patch(
        "backend.payroll_payout_details.user_role_codes",
        return_value={"PAYROLL_ADMIN"},
    ):
        assert can_edit_payout_details(conn, 1) is True


def test_confirm_payment_blocks_wrong_status():
    conn = MagicMock()
    with patch(
        "backend.payroll_payout_details.get_payout_batch",
        return_value={"id": 1, "status": "draft"},
    ), patch(
        "backend.payroll_payout_details.ensure_payout_details_columns",
    ):
        try:
            confirm_accountant_payment(conn, 1, 1, actor_id=9)
            assert False, "expected ValueError"
        except ValueError as e:
            assert "approved for payment" in str(e).lower()


def test_can_edit_payout_details_super_admin():
    conn = MagicMock()
    with patch(
        "backend.payroll_payout_details.user_role_codes",
        return_value={"SUPER_ADMIN"},
    ):
        assert can_edit_payout_details(conn, 1) is True


def test_batch_ready_for_payout_details():
    assert batch_ready_for_payout_details({"status": "approved_for_payment"}) is True
    assert batch_ready_for_payout_details({"status": "draft"}) is False


def test_finalize_requires_approved_status():
    conn = MagicMock()
    with patch(
        "backend.payroll_payout_details.get_payout_batch",
        return_value={"id": 1, "status": "draft"},
    ), patch(
        "backend.payroll_payout_details.ensure_payout_details_columns",
    ):
        try:
            finalize_payout_details(conn, 1, 1, actor_id=9)
            assert False, "expected ValueError"
        except ValueError as e:
            assert "approved for payment" in str(e).lower()


def test_update_details_allowed_before_accountant_confirm():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.fetchone.side_effect = [
        (None,),
        None,
    ]
    with patch(
        "backend.payroll_payout_details.get_payout_batch",
        return_value={
            "id": 1,
            "status": "approved_for_payment",
            "payout_details_finalized_at": None,
            "accountant_payment_confirmed_at": None,
        },
    ), patch(
        "backend.payroll_payout_details.ensure_payout_details_columns",
    ), patch(
        "backend.payroll_payout_details.get_payout_batch_details",
        return_value={"id": 1, "lines": []},
    ):
        update_payout_batch_details(
            conn, 1, 1, {"batch_note": "note"}, actor_id=9
        )
        conn.commit.assert_called()


def test_update_details_blocks_before_finalize_lock():
    conn = MagicMock()
    with patch(
        "backend.payroll_payout_details.get_payout_batch",
        return_value={
            "id": 1,
            "status": "approved_for_payment",
            "payout_details_finalized_at": "2026-06-19",
            "accountant_payment_confirmed_at": "2026-06-18",
        },
    ), patch(
        "backend.payroll_payout_details.ensure_payout_details_columns",
    ):
        try:
            update_payout_batch_details(
                conn, 1, 1, {"lines": [{"line_id": 1}]}, actor_id=9
            )
            assert False, "expected ValueError"
        except ValueError as e:
            assert "finalized" in str(e).lower()


def test_receipt_required_for_cash_only():
    cash = parse_line_payout_details(
        {"payout_details_json": {"payment": {"method": "cash"}}}
    )
    dd = parse_line_payout_details(
        {"payout_details_json": {"payment": {"method": "direct_deposit"}}}
    )
    zelle = parse_line_payout_details(
        {"payout_details_json": {"payment": {"method": "zelle"}}}
    )
    assert receipt_required_for_line(cash) is True
    assert receipt_required_for_line(dd) is False
    assert receipt_required_for_line(zelle) is False


def test_line_uses_payment_receipt_modes():
    batch_receipt = {"document_mode": "payment_receipt"}
    batch_paystub = {"document_mode": "official_paystub"}
    cash_details = parse_line_payout_details(
        {"payout_details_json": {"payment": {"method": "cash"}}}
    )
    dd_details = parse_line_payout_details(
        {"payout_details_json": {"payment": {"method": "direct_deposit"}}}
    )
    override_details = parse_line_payout_details(
        {
            "payout_details_json": {
                "payment": {"method": "direct_deposit"},
                "use_payment_receipt": True,
            }
        }
    )
    assert line_uses_payment_receipt(batch_receipt, dd_details) is True
    assert line_uses_payment_receipt(batch_paystub, cash_details) is False
    assert line_uses_payment_receipt(batch_paystub, override_details) is True
    assert line_uses_payment_receipt(batch_paystub, dd_details) is False


def test_document_availability_per_line():
    finalized_batch = {
        "document_mode": "official_paystub",
        "payout_details_finalized_at": "2026-06-20",
    }
    line = {"id": 1, "gross_amount": 500}
    cash_details = parse_line_payout_details(
        {"payout_details_json": {"payment": {"method": "cash"}}}
    )
    dd_details = parse_line_payout_details(
        {"payout_details_json": {"payment": {"method": "direct_deposit"}}}
    )
    check_details = parse_line_payout_details(
        {"payout_details_json": {"payment": {"method": "check"}}}
    )
    assert can_generate_paystub_for_line(finalized_batch, cash_details) is True
    assert can_generate_receipt_for_line(finalized_batch, cash_details) is True
    assert can_generate_paystub_for_line(finalized_batch, dd_details) is True
    assert can_generate_receipt_for_line(finalized_batch, dd_details) is False
    assert can_generate_receipt_for_line(finalized_batch, check_details) is True

    doc_cash = line_document_state(finalized_batch, line, cash_details)
    assert doc_cash["effective_type"] == "official_paystub"
    assert doc_cash["receipt_required"] is True
    assert doc_cash["paystub_available"] is True
    assert doc_cash["receipt_available"] is True


def test_payment_receipt_html_content():
    conn = MagicMock()
    batch = {
        "id": 1,
        "pay_period_start": "2026-06-01",
        "pay_period_end": "2026-06-14",
        "payout_details_finalized_at": "2026-06-20",
        "document_mode": "payment_receipt",
        "payout_details_finalized_by": 2,
        "accountant_payment_confirmed_by": 3,
        "lines": [
            {
                "id": 10,
                "user_id": 5,
                "worker_name_snapshot": "Jane Doe",
                "approved_hours": 40,
                "rate": 20,
                "gross_amount": 800,
                "payout_details": {
                    "payment": {
                        "date": "2026-06-15",
                        "method": "cash",
                        "reference": "REF-1",
                    },
                    "settlement": {"amount_paid": 800},
                },
                "payout_totals": {
                    "gross_pay": 800,
                    "amount_paid": 800,
                },
            }
        ],
    }
    with patch(
        "backend.payroll_payout_details.get_payout_batch_details",
        return_value=batch,
    ), patch(
        "backend.payroll_payout_details._user_display_meta",
        side_effect=lambda _c, uid: {
            "display_name": f"User {uid}",
            "employee_id": "E-100",
        },
    ), patch(
        "backend.payroll_payout_details._organization_print_branding",
        return_value={"company_name": "VeeWash", "logo_html": "<img src='data:image/png;base64,abc' />"},
    ):
        from backend.payroll_payout_details import generate_payment_receipt_html

        html = generate_payment_receipt_html(conn, 1, 1, 10)
        assert "Cash Payment Receipt" in html
        assert 'data:image/png;base64,' in html
        assert "Jane Doe" in html
        assert "VeeWash" in html
        assert "acknowledge receipt" in html
        assert "Net cash received" in html
        assert "Employee tax deductions" not in html
        assert "FIT" not in html


def test_paystub_html_zero_deductions():
    conn = MagicMock()
    batch = {
        "id": 1,
        "pay_period_start": "2026-06-01",
        "pay_period_end": "2026-06-14",
        "payout_details_finalized_at": "2026-06-20",
        "document_mode": "official_paystub",
        "lines": [
            {
                "id": 10,
                "user_id": 5,
                "worker_name_snapshot": "New Hire",
                "approved_hours": 40,
                "rate": 20,
                "gross_amount": 800,
                "payout_details": {
                    "employee_deductions": {
                        "fit": 0,
                        "ss": 0,
                        "medicare": 0,
                        "state": 0,
                        "local": 0,
                        "other1": 0,
                        "other2": 0,
                    },
                    "settlement": {"prior_period_adjustment": 0},
                    "payment": {"method": "direct_deposit", "date": "2026-06-15"},
                },
                "payout_totals": {
                    "gross_pay": 800,
                    "total_employee_deductions": 0,
                    "net_pay": 800,
                    "amount_paid": 800,
                    "amount_withheld": 0,
                    "outstanding_balance": 0,
                    "prior_unpaid_taxes": 0,
                    "total_employer_taxes": 0,
                    "employer_cost": 800,
                },
            }
        ],
    }
    with patch(
        "backend.payroll_payout_details.get_payout_batch_details",
        return_value=batch,
    ), patch(
        "backend.payroll_payout_details._organization_print_branding",
        return_value={
            "company_name": "VeeWash",
            "logo_html": "<img />",
            "address_line": "123 Main St",
            "contact_line": "phone",
        },
    ), patch(
        "backend.payroll_payout_details.fetch_finalized_paystub_ytd",
        return_value={
            "gross_pay": 400.0,
            "fit": 0.0,
            "ss": 0.0,
            "medicare": 0.0,
            "state": 0.0,
            "local": 0.0,
            "total_employee_deductions": 0.0,
            "net_pay": 400.0,
            "amount_paid": 400.0,
        },
    ):
        from backend.payroll_payout_details import generate_paystub_html

        emp = generate_paystub_html(conn, 1, 1, 10, copy_mode="employee")
        assert "EMPLOYEE COPY" in emp
        assert "Hours worked" in emp
        assert "YTD" in emp
        assert "$1,200.00" in emp or "$800.00" in emp
        assert "Earnings" in emp
        assert "Gross pay" in emp
        assert "Employee Taxes" in emp
        assert "Federal Income Tax" in emp
        assert "Social Security" in emp
        assert "Medicare" in emp
        assert "NY State Tax" in emp
        assert "NYC Local Tax" in emp
        assert "Total employee taxes" in emp
        assert "Net Pay" in emp
        assert "Amount paid to employee" in emp
        assert "$800.00" in emp
        assert "pay-summary" not in emp
        assert "ACTUAL PAID" not in emp
        assert "Employer Taxes" not in emp

        er = generate_paystub_html(conn, 1, 1, 10, copy_mode="employer")
        assert "EMPLOYER COPY" in er
        assert "Federal Income Tax" in er
        assert "Employer Taxes" in er
        assert "Tax Balances (Audit)" in er


def test_paystub_note_includes_period_tax_balance_when_gross_paid():
    conn = MagicMock()
    batch = {
        "id": 1,
        "pay_period_start": "2026-06-01",
        "pay_period_end": "2026-06-14",
        "payout_details_finalized_at": "2026-06-20",
        "document_mode": "official_paystub",
        "lines": [
            {
                "id": 10,
                "worker_name_snapshot": "Cash Worker",
                "approved_hours": 10,
                "rate": 11.9,
                "gross_amount": 119,
                "payout_details": {
                    "employee_deductions": {"fit": 4.21, "ss": 7.38, "medicare": 1.73},
                    "payment": {"method": "cash", "date": "2026-06-14"},
                    "settlement": {
                        "amount_paid": 119,
                        "amount_withheld": 0,
                        "paid_full_gross_without_withholding": True,
                        "tax_balance_owed": 13.32,
                    },
                    "tax_summary": {"tax_balance_owed": 13.32, "current_period_taxes": 13.32},
                },
                "payout_totals": {
                    "gross_pay": 119,
                    "total_employee_deductions": 13.32,
                    "net_pay": 105.68,
                    "amount_paid": 119,
                    "amount_withheld": 0,
                    "tax_balance_owed": 13.32,
                    "current_period_taxes": 13.32,
                },
            }
        ],
    }
    with patch(
        "backend.payroll_payout_details.get_payout_batch_details",
        return_value=batch,
    ):
        from backend.payroll_payout_details import generate_paystub_html

        html = generate_paystub_html(conn, 1, 1, 10, copy_mode="employee")
        assert "Estimated tax liability" in html
        assert "$13.32" in html
        assert "Estimated tax balance" in html
        assert "taxes were not withheld" not in html.lower()
        assert "Finalized" not in html


def test_paystub_html_shows_batch_and_employee_notes():
    conn = MagicMock()
    batch = {
        "id": 1,
        "pay_period_start": "2026-06-01",
        "pay_period_end": "2026-06-14",
        "payout_details_finalized_at": "2026-06-20",
        "document_mode": "official_paystub",
        "batch_note": "Payroll taxes were not withheld for this pay period.",
        "lines": [
            {
                "id": 10,
                "worker_name_snapshot": "Jane Doe",
                "approved_hours": 10,
                "rate": 20,
                "gross_amount": 200,
                "payout_details": {
                    "employee_note": "Employee requested payment in cash.",
                    "payment": {"method": "cash", "date": "2026-06-15"},
                    "settlement": {"amount_paid": 200, "prior_period_adjustment": 0},
                },
                "payout_totals": {
                    "gross_pay": 200,
                    "total_employee_deductions": 0,
                    "net_pay": 200,
                    "amount_paid": 200,
                    "amount_withheld": 0,
                    "outstanding_balance": 0,
                    "prior_unpaid_taxes": 0,
                    "total_employer_taxes": 0,
                    "employer_cost": 200,
                },
            }
        ],
    }
    with patch(
        "backend.payroll_payout_details.get_payout_batch_details",
        return_value=batch,
    ):
        from backend.payroll_payout_details import generate_paystub_html

        emp = generate_paystub_html(conn, 1, 1, 10, copy_mode="employee")
        assert "Payroll taxes were not withheld" not in emp
        assert "Employee requested payment in cash" not in emp

        er = generate_paystub_html(conn, 1, 1, 10, copy_mode="employer")
        assert "Batch Note" in er
        assert "Payroll taxes were not withheld" in er
        assert "Employee Note" in er
        assert "Employee requested payment in cash" in er


def test_paystub_html_available_for_cash_payment():
    conn = MagicMock()
    batch = {
        "id": 1,
        "pay_period_start": "2026-06-01",
        "pay_period_end": "2026-06-14",
        "payout_details_finalized_at": "2026-06-20",
        "document_mode": "official_paystub",
        "lines": [
            {
                "id": 10,
                "worker_name_snapshot": "Cash Worker",
                "approved_hours": 10,
                "rate": 20,
                "gross_amount": 200,
                "payout_details": {
                    "payment": {"method": "cash", "date": "2026-06-15"},
                    "settlement": {"amount_paid": 200, "prior_period_adjustment": 0},
                },
                "payout_totals": {
                    "gross_pay": 200,
                    "total_employee_deductions": 0,
                    "net_pay": 200,
                    "amount_paid": 200,
                    "amount_withheld": 0,
                    "outstanding_balance": 0,
                    "prior_unpaid_taxes": 0,
                    "total_employer_taxes": 0,
                    "employer_cost": 200,
                },
            }
        ],
    }
    with patch(
        "backend.payroll_payout_details.get_payout_batch_details",
        return_value=batch,
    ), patch(
        "backend.payroll_payout_details._organization_print_branding",
        return_value={
            "company_name": "VeeWash",
            "logo_html": "<img src='data:image/png;base64,abc' />",
            "address_line": "123 Main St",
            "contact_line": "(212) 555-0100 • www.veewash.com",
        },
    ):
        from backend.payroll_payout_details import generate_paystub_html

        html = generate_paystub_html(conn, 1, 1, 10, copy_mode="employee")
        assert "Employee Paystub" in html
        assert 'data:image/png;base64,' in html
        assert "VeeWash" in html
        assert "YTD" in html
        assert "col-ytd" in html
        assert "Cash Worker" in html
        assert "Cash Payment Acknowledgment" in html
        assert "acknowledge receipt of the cash payment shown above" in html
        assert "Manager / witness" in html
        assert "sig-line-large" in html
        assert "Employer Taxes" not in html
        assert "Finalized" not in html

        er = generate_paystub_html(conn, 1, 1, 10, copy_mode="employer")
        assert "Cash Receipt" not in er
        assert "Cash Payment Acknowledgment" not in er
        assert "Employer Taxes" in er
        assert "Finalized" in er

        dd_batch = dict(batch)
        dd_batch["lines"] = [{
            **batch["lines"][0],
            "payout_details": {
                **batch["lines"][0]["payout_details"],
                "payment": {"method": "direct_deposit", "date": "2026-06-15", "reference": "ACH123"},
            },
        }]
        with patch(
            "backend.payroll_payout_details.get_payout_batch_details",
            return_value=dd_batch,
        ):
            dd_html = generate_paystub_html(conn, 1, 1, 10, copy_mode="employee")
        assert "Cash Receipt" not in dd_html
        assert "Reference" not in dd_html
        assert "Direct Deposit" in dd_html


def test_paystub_ytd_only_prior_pay_periods_in_year():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.fetchall.return_value = []

    from backend.payroll_payout_details import fetch_finalized_paystub_ytd

    ytd = fetch_finalized_paystub_ytd(
        conn,
        3,
        42,
        2026,
        "2026-05-17",
        current_batch_id=5,
        exclude_line_id=100,
    )
    assert ytd["gross_pay"] == 0.0
    sql = cursor.execute.call_args[0][0]
    assert "worker_category = 'w2'" in sql
    assert "pay_period_end <" in sql
    assert "YEAR(pb.pay_period_end)" in sql


def test_paystub_employee_tax_balance_hidden_when_checkbox_off():
    conn = MagicMock()
    batch = {
        "id": 1,
        "pay_period_start": "2026-06-01",
        "pay_period_end": "2026-06-14",
        "payout_details_finalized_at": "2026-06-20",
        "document_mode": "official_paystub",
        "lines": [
            {
                "id": 10,
                "worker_name_snapshot": "Worker",
                "approved_hours": 10,
                "rate": 20,
                "gross_amount": 200,
                "payout_details": {
                    "employee_deductions": {"fit": 10},
                    "show_tax_payment_section": False,
                    "payment": {"method": "direct_deposit", "date": "2026-06-14"},
                    "settlement": {
                        "amount_paid": 190,
                        "paid_full_gross_without_withholding": True,
                        "tax_balance_owed": 10,
                    },
                    "tax_summary": {"tax_balance_owed": 10, "current_period_taxes": 10},
                },
                "payout_totals": {
                    "gross_pay": 200,
                    "total_employee_deductions": 10,
                    "net_pay": 190,
                    "amount_paid": 200,
                    "tax_balance_owed": 10,
                    "current_period_taxes": 10,
                    "remaining_tax_balance": 10,
                    "paid_full_gross_without_withholding": True,
                },
            }
        ],
    }
    with patch(
        "backend.payroll_payout_details.get_payout_batch_details",
        return_value=batch,
    ):
        from backend.payroll_payout_details import generate_paystub_html

        html = generate_paystub_html(conn, 1, 1, 10, copy_mode="employee")
        assert "Tax Balance" not in html
        assert "Estimated tax balance" not in html


def test_paystub_employee_tax_balance_catchup_flow():
    conn = MagicMock()
    batch = {
        "id": 6,
        "pay_period_start": "2026-06-15",
        "pay_period_end": "2026-06-21",
        "payout_details_finalized_at": "2026-06-22",
        "document_mode": "official_paystub",
        "lines": [
            {
                "id": 10,
                "worker_name_snapshot": "Worker",
                "approved_hours": 10,
                "rate": 20,
                "gross_amount": 200,
                "payout_details": {
                    "employee_deductions": {"fit": 25},
                    "payment": {"method": "direct_deposit", "date": "2026-06-21"},
                    "settlement": {
                        "amount_paid": 135,
                        "amount_withheld": 65,
                        "prior_unpaid_taxes": 80,
                        "catch_up_withholding": 40,
                    },
                },
                "payout_totals": {
                    "gross_pay": 200,
                    "total_employee_deductions": 25,
                    "net_pay": 135,
                    "amount_paid": 135,
                    "amount_withheld": 65,
                    "prior_tax_balance": 80,
                    "catch_up_withholding": 40,
                    "remaining_tax_balance": 40,
                    "current_period_taxes": 25,
                    "tax_balance_owed": 0,
                },
            }
        ],
    }
    with patch(
        "backend.payroll_payout_details.get_payout_batch_details",
        return_value=batch,
    ):
        from backend.payroll_payout_details import generate_paystub_html

        html = generate_paystub_html(conn, 1, 6, 10, copy_mode="employee")
        assert "This period estimated tax" in html
        assert "Prior tax balance" in html
        assert "Total estimated liability" in html
        assert "Catch-up collected" in html
        assert "Remaining balance" in html
        assert "$80.00" in html
        assert "$40.00" in html


def test_apply_carryover_prior_tax_balance_from_finalized_line():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.fetchone.return_value = {
        "payout_details_json": {
            "tax_summary": {"remaining_balance": 30.0},
            "settlement": {"tax_balance_owed": 30.0},
        }
    }
    from backend.payroll_payout_details import apply_carryover_prior_tax_balance, parse_line_payout_details

    line = {"gross_amount": 200, "user_id": 5}
    details = parse_line_payout_details(
        {
            "payout_details_json": {
                "employee_deductions": {"fit": 20},
                "settlement": {"prior_unpaid_taxes": 0, "catch_up_withholding": 10},
            }
        }
    )
    out = apply_carryover_prior_tax_balance(conn, 1, 99, line, details)
    assert out["settlement"]["prior_unpaid_taxes"] == 30.0
    assert out["tax_summary"]["remaining_balance"] == 20.0


def test_unfinalize_clears_finalized_timestamp():
    conn = MagicMock()
    finalized_batch = {
        "id": 1,
        "status": "paid",
        "worker_category": "w2",
        "payout_details_finalized_at": "2026-06-20",
        "payout_details_audit_json": None,
    }
    with patch(
        "backend.payroll_payout_details.get_payout_batch",
        return_value=finalized_batch,
    ), patch(
        "backend.payroll_payout_details.ensure_payout_details_columns",
    ), patch(
        "backend.payroll_payout_details.get_payout_batch_details",
        side_effect=[
            finalized_batch,
            {"id": 1, "payout_details_finalized_at": None},
        ],
    ):
        unfinalize_payout_details(conn, 1, 1, actor_id=9)
        conn.commit.assert_called()


def test_finalize_blockers_clear_when_pay_period_can_default_cash_date():
    batch = {
        "status": "approved_for_payment",
        "worker_category": "w2",
        "document_mode": "official_paystub",
        "pay_period_start": "2026-05-11",
        "pay_period_end": "2026-05-17",
        "lines": [
            {
                "id": 10,
                "worker_name_snapshot": "Alec",
                "gross_amount": 119,
                "payout_details": {
                    "payment": {"method": "cash"},
                    "settlement": {"amount_paid": 119},
                },
            }
        ],
    }
    assert finalize_blockers(batch, batch["lines"]) == []


def test_finalize_receipt_mode_requires_payment_fields():
    conn = MagicMock()
    enriched = {
        "document_mode": "payment_receipt",
        "worker_category": "w2",
        "status": "approved_for_payment",
        "lines": [
            {
                "worker_name_snapshot": "Jane",
                "payout_details": {
                    "payment": {"method": "cash"},
                    "settlement": {"amount_paid": 0},
                },
            }
        ],
    }
    with patch(
        "backend.payroll_payout_details.get_payout_batch",
        return_value={"id": 1, "status": "approved_for_payment", "accountant_payment_confirmed_at": "x"},
    ), patch(
        "backend.payroll_payout_details.ensure_payout_details_columns",
    ), patch(
        "backend.payroll_payout_details.get_payout_batch_details",
        return_value=enriched,
    ):
        try:
            finalize_payout_details(conn, 1, 1, actor_id=9)
            assert False, "expected ValueError"
        except ValueError as e:
            assert "amount paid" in str(e).lower() or "payment date" in str(e).lower()


def test_set_document_mode_blocks_after_finalize():
    conn = MagicMock()
    with patch(
        "backend.payroll_payout_details.get_payout_batch",
        return_value={
            "id": 1,
            "status": "approved_for_payment",
            "accountant_payment_confirmed_at": "x",
            "payout_details_finalized_at": "y",
        },
    ), patch(
        "backend.payroll_payout_details.ensure_payout_details_columns",
    ):
        try:
            set_batch_document_mode(
                conn, 1, 1, "payment_receipt", actor_id=9
            )
            assert False, "expected ValueError"
        except ValueError as e:
            assert "finalize" in str(e).lower()


def test_paystub_preview_before_finalize():
    conn = MagicMock()
    batch = {
        "id": 1,
        "status": "approved_for_payment",
        "pay_period_start": "2026-06-01",
        "pay_period_end": "2026-06-07",
        "document_mode": "official_paystub",
        "lines": [
            {
                "id": 10,
                "user_id": 5,
                "worker_name_snapshot": "Jane",
                "gross_amount": 500,
                "approved_hours": 10,
                "rate": 50,
                "payout_details_json": {
                    "employee_deductions": {"fit": 20, "ss": 30, "medicare": 7},
                    "payment": {"method": "cash"},
                },
            }
        ],
    }
    with patch(
        "backend.payroll_payout_details.get_payout_batch_details",
        return_value=batch,
    ):
        from backend.payroll_payout_details import generate_paystub_html

        html = generate_paystub_html(conn, 1, 1, 10, preview=True)
        assert "Jane" in html
        assert "PREVIEW" in html


def test_paystub_blocked_until_finalized():
    conn = MagicMock()
    with patch(
        "backend.payroll_payout_details.get_payout_batch_details",
        return_value={"id": 1, "payout_details_finalized_at": None},
    ):
        from backend.payroll_payout_details import generate_paystub_html

        try:
            generate_paystub_html(conn, 1, 1, 1)
            assert False, "expected ValueError"
        except ValueError as e:
            assert "finalized" in str(e).lower()


def test_employer_payroll_packet_combines_records():
    conn = MagicMock()
    batch = {
        "id": 1,
        "batch_name": "W2-2026-006",
        "pay_period_start": "2026-06-01",
        "pay_period_end": "2026-06-07",
        "payout_details_finalized_at": "2026-06-20",
        "document_mode": "official_paystub",
        "lines": [
            {
                "id": 10,
                "worker_name_snapshot": "Jane",
                "approved_hours": 10,
                "rate": 20,
                "gross_amount": 200,
                "payout_details": {
                    "payment": {"method": "direct_deposit", "date": "2026-06-15"},
                    "settlement": {"amount_paid": 200},
                },
                "payout_totals": {
                    "gross_pay": 200,
                    "total_employee_deductions": 0,
                    "net_pay": 200,
                    "amount_paid": 200,
                    "amount_withheld": 0,
                    "total_employer_taxes": 10,
                    "employer_cost": 210,
                },
            }
        ],
    }
    with patch(
        "backend.payroll_payout_details.get_payout_batch_details",
        return_value=batch,
    ):
        from backend.payroll_payout_details import generate_employer_payroll_packet_html

        html = generate_employer_payroll_packet_html(conn, 1, 1)
        assert "Employer Payroll Packet" in html
        assert "EMPLOYER COPY" in html
        assert "Pay Register" in html
        assert "Jane" in html


def test_compute_tax_withheld_breakdown_includes_all_components():
    details = parse_line_payout_details(
        {
            "payout_details_json": {
                "employee_deductions": {
                    "fit": 100,
                    "ss": 50,
                    "medicare": 10,
                    "state": 20,
                    "local": 5,
                    "other1": 3,
                    "other2": 2,
                },
                "settlement": {"prior_period_adjustment": 15},
            }
        }
    )
    breakdown = compute_tax_withheld_breakdown(details)
    assert breakdown["federal_income_tax"] == 100.0
    assert breakdown["social_security"] == 50.0
    assert breakdown["medicare"] == 10.0
    assert breakdown["state_tax"] == 20.0
    assert breakdown["local_tax"] == 5.0
    assert breakdown["other_deduction"] == 5.0
    assert breakdown["prior_period_adjustment"] == 15.0
    assert breakdown["total_employee_taxes"] == 190.0
    assert breakdown["actual_tax_withheld"] == 0.0
    assert breakdown["total_tax_withheld"] == 0.0


def test_enrich_line_settlement_fields_pending_before_finalize():
    line = {"id": 1, "gross_amount": 1000}
    batch = {"payout_details_finalized_at": None}
    row = enrich_line_settlement_fields(line, batch)
    assert row["payout_details_finalized"] is False
    assert row["net_paid"] is None
    assert row["tax_withheld"] is None
    assert row["tax_withheld_breakdown"] is None


def test_enrich_line_settlement_fields_after_finalize():
    line = {
        "id": 1,
        "gross_amount": 1000,
        "payout_details_json": {
            "employee_deductions": {"fit": 80, "ss": 40, "medicare": 10},
            "payment": {"date": "2026-06-01", "method": "direct_deposit"},
            "settlement": {"amount_paid": 870, "prior_period_adjustment": 0},
        },
    }
    batch = {"payout_details_finalized_at": "2026-06-02T12:00:00"}
    row = enrich_line_settlement_fields(line, batch)
    assert row["payout_details_finalized"] is True
    assert row["net_paid"] == 870.0
    assert row["tax_withheld"] == 130.0
    assert row["tax_liability"] == 130.0
    assert row["payment_date"] == "2026-06-01"
    assert row["payment_method_label"] == "Direct Deposit"


def test_user_display_meta_without_employee_id_column():
    conn = MagicMock()
    with patch("backend.payroll_payout_details.table_has_column", return_value=False):
        c = conn.cursor.return_value
        c.fetchone.return_value = {
            "display_name": "Jane Doe",
            "username": "jane",
        }
        from backend.payroll_payout_details import _user_display_meta

        meta = _user_display_meta(conn, 42)
    assert meta == {"display_name": "Jane Doe", "employee_id": ""}
    sql = c.execute.call_args[0][0]
    assert "employee_id" not in sql


def test_enrich_payout_batch_without_employee_id_column():
    conn = MagicMock()
    batch = {
        "worker_category": "w2",
        "status": "accountant_reviewed",
        "lines": [
            {
                "id": 1,
                "user_id": 42,
                "worker_name_snapshot": "Jane Doe",
                "payment_status": "approved_unpaid",
                "gross_amount": 800,
                "total_amount": 800,
                "rate": 20,
            }
        ],
    }
    with patch("backend.payroll_workflow.ensure_payout_batch_line_extensions"), patch(
        "backend.payroll_payout_details.table_has_column", return_value=False
    ), patch(
        "backend.payroll_payout_details._user_display_meta",
        return_value={"display_name": "Jane Doe", "employee_id": ""},
    ), patch(
        "backend.payroll_workflow.resolve_worker_hourly_rate",
        return_value={
            "worker_category_label": "W-2",
            "payment_method": "",
            "rate_missing": False,
            "hourly_rate": 20,
            "rate_source": "payroll_schedule",
        },
    ), patch(
        "backend.w2_payroll_tax_engine.fetch_employee_tax_profile",
        return_value={"w4_complete": True, "missing_fields": []},
    ), patch(
        "backend.payroll_workflow.fetch_w4_compliance_summary",
        return_value={"w4_on_file": True, "tax_calc_status": "estimated"},
    ), patch(
        "backend.payroll_accrual.get_sick_leave_balance",
        return_value={"balance_hours": 0},
    ):
        from backend.payroll_workflow import enrich_payout_batch

        out = enrich_payout_batch(conn, 1, batch)
    assert out["lines"][0]["employee_id"] == ""
    assert out["lines"][0]["worker_name_snapshot"] == "Jane Doe"
