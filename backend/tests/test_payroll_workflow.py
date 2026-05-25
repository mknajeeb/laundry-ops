"""Tests for payroll workflow helpers."""

from unittest.mock import MagicMock, patch

from backend.payroll_workflow import (
    _batch_payment_status,
    _line_payment_status_label,
    fetch_w4_compliance_summary,
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
    with patch("backend.payroll_workflow.ensure_hr_extended_profiles_table"):
        c = conn.cursor.return_value
        c.fetchone.return_value = {"work_json": "{}"}
        out = fetch_w4_compliance_summary(conn, 1)
    assert out["w4_on_file"] is False
    assert out["tax_calc_status"] == "pending"
