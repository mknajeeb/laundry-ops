"""Delete payout batch — including after finalize / paid."""

from unittest.mock import MagicMock, patch

import pytest

from backend.payroll_operations import can_delete_payout_batch, delete_payout_batch


def test_can_delete_payout_batch_statuses():
    assert can_delete_payout_batch({"status": "draft"}) is True
    assert can_delete_payout_batch({"status": "hours_reviewed"}) is True
    assert can_delete_payout_batch({"status": "approved_for_payment"}) is True
    assert can_delete_payout_batch({"status": "paid"}) is True
    assert can_delete_payout_batch({"status": "closed"}) is True
    assert can_delete_payout_batch({"status": "sent_to_accountant"}) is False
    assert can_delete_payout_batch({"status": "accountant_reviewed"}) is False


def test_delete_blocks_finalized_paid_without_unlock():
    conn = MagicMock()
    with patch(
        "backend.payroll_operations.get_payout_batch",
        return_value={
            "id": 1,
            "status": "paid",
            "payout_details_finalized_at": "2026-08-01T12:00:00",
        },
    ):
        with pytest.raises(ValueError, match="Unfinalize"):
            delete_payout_batch(conn, 1, 1)


def test_delete_paid_after_unfinalize_without_unlock_flag():
    conn = MagicMock()
    c = MagicMock()
    c.rowcount = 1
    conn.cursor.return_value = c
    with patch(
        "backend.payroll_operations.get_payout_batch",
        return_value={
            "id": 2,
            "status": "paid",
            "payout_details_finalized_at": None,
        },
    ), patch(
        "backend.payroll_accrual.reverse_ledger_entries_for_batch",
    ) as rev:
        assert delete_payout_batch(conn, 1, 2) is True
        rev.assert_called_once_with(conn, 1, 2)
        conn.commit.assert_called()


def test_delete_finalized_paid_with_unlock():
    conn = MagicMock()
    c = MagicMock()
    c.rowcount = 1
    conn.cursor.return_value = c
    with patch(
        "backend.payroll_operations.get_payout_batch",
        return_value={
            "id": 3,
            "status": "paid",
            "payout_details_finalized_at": "2026-08-01T12:00:00",
        },
    ), patch(
        "backend.payroll_accrual.reverse_ledger_entries_for_batch",
    ) as rev:
        assert delete_payout_batch(conn, 1, 3, unlock_finalized=True) is True
        rev.assert_called_once()


def test_delete_still_blocks_sent_to_accountant():
    conn = MagicMock()
    with patch(
        "backend.payroll_operations.get_payout_batch",
        return_value={"id": 4, "status": "sent_to_accountant"},
    ):
        with pytest.raises(ValueError, match="draft or hours-reviewed"):
            delete_payout_batch(conn, 1, 4, unlock_finalized=True)
