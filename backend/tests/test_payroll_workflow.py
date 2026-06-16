"""Tests for payroll workflow helpers."""

from unittest.mock import MagicMock, patch

from backend.payroll_workflow import (
    _batch_payment_status,
    _line_payment_status_label,
    _mask_incomplete_w2_line_taxes,
    build_payroll_readiness,
    fetch_w4_compliance_summary,
    resolve_worker_hourly_rate,
    validate_batch_for_workflow,
)


def test_line_payment_status_label():
    assert _line_payment_status_label("paid") == "Paid"
    assert _line_payment_status_label("approved_unpaid") == "Approved — unpaid"


def test_batch_payment_status_partial():
    lines = [
        {"payment_status": "paid"},
        {"payment_status": "approved_unpaid"},
    ]
    assert _batch_payment_status(lines) == "partially_paid"


def test_validate_batch_blocks_missing_rates():
    batch = {
        "lines": [{"id": 1}],
        "missing_rates": [{"worker_name": "Jane Doe"}],
    }
    try:
        validate_batch_for_workflow(batch, "hours_reviewed")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "missing hourly rate" in str(e).lower()


def test_fetch_w4_compliance_empty():
    conn = MagicMock()
    with patch("backend.payroll_workflow.ensure_hr_extended_profiles_table"), patch(
        "backend.w2_payroll_tax_engine.fetch_employee_tax_profile",
        return_value={"w4_complete": False, "missing_fields": []},
    ):
        c = conn.cursor.return_value
        c.fetchone.return_value = {"work_json": "{}"}
        out = fetch_w4_compliance_summary(conn, 1, 1)
    assert out["w4_on_file"] is False
    assert out["tax_calc_status"] == "profile_incomplete"


def test_mask_incomplete_w2_line_taxes_clears_amounts():
    row = {
        "tax_calc_status": "profile_incomplete",
        "federal_withholding": 0,
        "net_pay": 0,
        "total_employee_taxes": 0,
    }
    _mask_incomplete_w2_line_taxes(row)
    assert row["federal_withholding"] is None
    assert row["net_pay"] is None
    assert row["total_employee_taxes"] is None


def test_build_payroll_readiness_w2_complete():
    batch = {"status": "hours_reviewed", "worker_category": "w2"}
    lines = [{"tax_calc_status": "estimated", "rate": 20}]
    items = build_payroll_readiness(batch, "w2", [], [], lines)
    keys = {i["key"] for i in items}
    assert keys == {
        "worker_type",
        "rate_present",
        "hours_reviewed",
        "w4_profile",
        "tax_estimate",
        "accountant_export",
        "paid_tracking",
    }
    assert all(i["ok"] for i in items if i["key"] != "paid_tracking" or i["ok"])


def test_build_payroll_readiness_temp_skips_tax_items():
    batch = {"status": "draft", "worker_category": "temp"}
    lines = [{"rate": 18, "total_amount": 100}]
    items = build_payroll_readiness(batch, "temp", [], [], lines)
    w4 = next(i for i in items if i["key"] == "w4_profile")
    tax = next(i for i in items if i["key"] == "tax_estimate")
    assert w4["ok"] is True
    assert tax["ok"] is True
    assert "tax engine does not run" in tax["detail"].lower()


def test_resolve_worker_hourly_rate_prefers_payroll_schedule():
    conn = MagicMock()
    with patch("backend.payroll_workflow.worker_category_for_user", return_value="w2"), patch(
        "backend.payroll_workflow.table_exists", return_value=True
    ), patch(
        "backend.payroll_workflow._contractor_json_from_hr", return_value=({}, None)
    ), patch("backend.payroll_workflow._latest_hourly_rate", return_value=15.0), patch(
        "backend.payroll_workflow.build_contractor_prefill", return_value={}
    ), patch(
        "backend.payroll_workflow._latest_payment_method_label", return_value=""
    ):
        c = conn.cursor.return_value
        c.fetchone.return_value = {"default_hourly_rate": 22.5}
        out = resolve_worker_hourly_rate(conn, 42, 1)
    assert out["hourly_rate"] == 22.5
    assert out["rate_source"] == "payroll_schedule"
    assert out["rate_missing"] is False
