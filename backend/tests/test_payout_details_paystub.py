"""Tests for payout details, accountant confirmation, paystub workflow."""

from unittest.mock import MagicMock, patch

from backend.payroll_payout_details import (
    can_confirm_accountant_payment,
    can_edit_payout_details,
    can_process_accountant_batch,
    can_view_accountant_queue,
    compute_line_totals,
    confirm_accountant_payment,
    finalize_payout_details,
    is_accountant_batch_list_view,
    parse_line_payout_details,
    payout_workflow_state,
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
    assert wf["paystub_available"] is False

    batch2 = {
        "status": "approved_for_payment",
        "accountant_payment_confirmed_at": "2026-06-19",
    }
    wf2 = payout_workflow_state(batch2)
    assert wf2["can_edit_details"] is True
    assert wf2["paystub_available"] is False

    batch3 = {
        "status": "paid",
        "accountant_payment_confirmed_at": "2026-06-19",
        "payout_details_finalized_at": "2026-06-20",
    }
    wf3 = payout_workflow_state(batch3)
    assert wf3["paystub_available"] is True
    assert wf3["can_edit_details"] is False


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


def test_finalize_requires_accountant_confirm():
    conn = MagicMock()
    with patch(
        "backend.payroll_payout_details.get_payout_batch",
        return_value={"id": 1, "status": "approved_for_payment"},
    ), patch(
        "backend.payroll_payout_details.ensure_payout_details_columns",
    ):
        try:
            finalize_payout_details(conn, 1, 1, actor_id=9)
            assert False, "expected ValueError"
        except ValueError as e:
            assert "accountant" in str(e).lower()


def test_update_details_blocks_before_finalize_lock():
    conn = MagicMock()
    with patch(
        "backend.payroll_payout_details.get_payout_batch",
        return_value={
            "id": 1,
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
