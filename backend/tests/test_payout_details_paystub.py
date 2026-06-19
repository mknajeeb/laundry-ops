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
    confirm_accountant_payment,
    finalize_payout_details,
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
    """Scenario B: partial payment with withholding."""
    line = {"gross_amount": 1000}
    details = parse_line_payout_details(
        {
            "payout_details_json": {
                "employee_deductions": {"fit": 200},
                "settlement": {
                    "amount_paid": 600,
                    "amount_withheld": 100,
                    "outstanding_balance": 100,
                    "prior_unpaid_taxes": 0,
                },
            }
        }
    )
    totals = compute_line_totals(line, details)
    assert totals["net_pay"] == 800.0
    assert totals["amount_withheld"] == 100.0
    assert totals["outstanding_balance"] == 100.0


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
    ):
        from backend.payroll_payout_details import generate_payment_receipt_html

        html = generate_payment_receipt_html(conn, 1, 1, 10)
        assert "Payment Receipt" in html
        assert "Jane Doe" in html
        assert "E-100" in html
        assert "not a wage statement" in html
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
    ):
        from backend.payroll_payout_details import generate_paystub_html

        html = generate_paystub_html(conn, 1, 1, 10)
        assert "Federal Income Tax (FIT)" in html
        assert "Social Security" in html
        assert "Medicare" in html
        assert "State Tax" in html
        assert "Local Tax" in html
        assert "Other Deduction" in html
        assert "Prior Period Adjustment" in html
        assert "Total Deductions" in html
        assert "$0.00" in html
        assert "Net pay" in html
        assert "$800.00" in html


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

        html = generate_paystub_html(conn, 1, 1, 10)
        assert "Batch Note" in html
        assert "Payroll taxes were not withheld" in html
        assert "Employee Note" in html
        assert "Employee requested payment in cash" in html


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
    ):
        from backend.payroll_payout_details import generate_paystub_html

        html = generate_paystub_html(conn, 1, 1, 10)
        assert "VeeWash Official Paystub" in html
        assert "Cash Worker" in html
        assert "Employee Deductions" in html


def test_finalize_receipt_mode_requires_payment_fields():
    conn = MagicMock()
    enriched = {
        "document_mode": "payment_receipt",
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
