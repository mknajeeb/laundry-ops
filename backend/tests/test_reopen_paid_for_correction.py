"""Reopen paid status for correction — no production payroll rows."""

import json
from unittest.mock import MagicMock, patch

from backend.payroll_payout_details import (
    payout_workflow_state,
    reopen_paid_status_for_correction,
    sync_payment_recorded_for_paid_lines,
)
from backend.payroll_status_display import compute_display_status
from backend.payroll_worker_categories import line_payment_recorded


def _details(recorded="paid", fit=12.5):
    return {
        "employee_deductions": {"fit": fit, "ss": 6.2, "medicare": 1.45, "state": 4},
        "employer_taxes": {"ss": 6.2},
        "payment": {
            "date": "2026-08-29",
            "method": "check",
            "reference": "CHK-17",
            "check_number": "17",
        },
        "settlement": {
            "amount_paid": 80.0,
            "amount_withheld": 20.0,
            "payment_recorded": recorded,
        },
    }


def _line(line_id, name, *, status="paid", recorded="paid", fit=12.5):
    return {
        "id": line_id,
        "user_id": 100 + line_id,
        "worker_name_snapshot": name,
        "payment_status": status,
        "payment_date": "2026-08-29",
        "payment_reference": "CHK-17",
        "gross_amount": 100,
        "total_amount": 100,
        "federal_withholding": fit,
        "payout_details_json": json.dumps(_details(recorded, fit)),
    }


def _batch(lines, *, status="paid", audit=None, finalized="2026-08-30T01:00:00"):
    return {
        "id": 50,
        "organization_id": 3,
        "status": status,
        "worker_category": "w2",
        "paid_at": "2026-08-30T01:23:43",
        "payout_details_finalized_at": finalized,
        "payout_details_finalized_by": 9,
        "payout_details_audit_json": json.dumps({"events": audit or []}),
        "lines": lines,
        "document_mode": "official_paystub",
    }


def _run(batch, reason="Correct a missed deduction"):
    conn = MagicMock()
    cursor = conn.cursor.return_value
    cursor.rowcount = 1
    with patch("backend.payroll_payout_details.ensure_payout_details_columns"), patch(
        "backend.payroll_payout_details.get_payout_batch", return_value=batch
    ), patch(
        "backend.payroll_payout_details.get_payout_batch_details",
        return_value={"id": 50, "status": "approved_for_payment"},
    ):
        out = reopen_paid_status_for_correction(conn, 3, 50, actor_id=4, reason=reason)
    return conn, cursor, out


def _batch_update(cursor):
    for call in cursor.execute.call_args_list:
        sql = call.args[0]
        if "UPDATE payout_batches" in sql:
            return sql, call.args[1]
    raise AssertionError("batch update missing")


def _line_updates(cursor):
    found = []
    for call in cursor.execute.call_args_list:
        sql = call.args[0]
        if "UPDATE payout_batch_lines" in sql:
            found.append((sql, call.args[1]))
    return found


def test_reopen_fully_paid_reverses_every_paid_line_and_keeps_deductions():
    lines = [_line(1, "A"), _line(2, "B", fit=9)]
    conn, cursor, _out = _run(_batch(lines))
    sql, params = _batch_update(cursor)
    assert "status='approved_for_payment'" in sql
    assert "paid_at=NULL" in sql
    assert "payout_details_finalized_at=NULL" in sql
    audit = json.loads(params[0])
    event = audit["events"][-2]
    assert event["event"] == "payment_reversed_for_correction"
    assert event["actor_id"] == 4
    assert event["reason"] == "Correct a missed deduction"
    assert event["prior_batch_status"] == "paid"
    assert event["prior_paid_at"] == "2026-08-30T01:23:43"
    assert {row["line_id"] for row in event["lines"]} == {1, 2}
    assert event["lines"][0]["prior_payment_status"] == "paid"
    assert event["lines"][0]["prior_payment_date"] == "2026-08-29"
    assert event["lines"][0]["prior_payment_reference"] == "CHK-17"
    assert event["lines"][0]["prior_amount_paid"] == 80.0
    assert event["lines"][0]["prior_payment_recorded"] == "paid"
    assert audit["events"][-1]["event"] == "payout_details_unfinalized"
    updates = _line_updates(cursor)
    assert len(updates) == 2
    for _sql, line_params in updates:
        blob = json.loads(line_params[0])
        assert blob["settlement"]["payment_recorded"] == "unpaid"
        assert blob["employee_deductions"]["ss"] == 6.2
        assert blob["settlement"]["amount_withheld"] == 20.0
        assert blob["payment"]["date"] is None
        assert "payment_date=NULL" in _sql
        assert "payment_reference=NULL" in _sql
        assert "payment_status='approved_unpaid'" in _sql
    conn.commit.assert_called_once()


def test_reopen_leaves_explicitly_unpaid_lines_untouched():
    lines = [_line(1, "Paid"), _line(2, "Already", status="unpaid", recorded="unpaid")]
    _conn, cursor, _out = _run(_batch(lines))
    _sql, params = _batch_update(cursor)
    event = json.loads(params[0])["events"][-2]
    assert [row["line_id"] for row in event["lines"]] == [1]
    assert len(_line_updates(cursor)) == 1


def test_second_reopen_does_not_append_another_reversal():
    audit = [
        {
            "event": "payment_reversed_for_correction",
            "actor_id": 4,
            "reason": "first",
            "lines": [],
        }
    ]
    batch = _batch([], status="approved_for_payment", audit=audit, finalized=None)
    conn = MagicMock()
    with patch("backend.payroll_payout_details.ensure_payout_details_columns"), patch(
        "backend.payroll_payout_details.get_payout_batch", return_value=batch
    ), patch(
        "backend.payroll_payout_details.get_payout_batch_details",
        return_value={"id": 50, "status": "approved_for_payment", "payroll_display": {"display_status": "ready_for_payroll"}},
    ) as details:
        reopen_paid_status_for_correction(conn, 3, 50, actor_id=4, reason="again please")
    details.assert_called_once()
    conn.commit.assert_not_called()
    conn.cursor.return_value.execute.assert_not_called()


def test_reopen_clears_official_documents_and_paid_headline():
    after = {
        "status": "approved_for_payment",
        "worker_category": "w2",
        "document_mode": "official_paystub",
        "payout_details_finalized_at": None,
        "lines": [],
    }
    state = payout_workflow_state(after)
    assert state["paystub_available"] is False
    assert state["can_reopen_paid_for_correction"] is False
    assert compute_display_status(after) == "ready_for_payroll"
    assert compute_display_status(after) != "paid"


def test_mark_paid_after_reversal_records_payment_again():
    """approved_unpaid is eligible for mark_paid; payment_recorded must follow."""
    assert "approved_unpaid" not in ("paid", "unpaid")
    conn = MagicMock()
    cursor = conn.cursor.return_value
    cursor.fetchall.return_value = [
        {
            "id": 1,
            "payment_status": "paid",
            "payout_details_json": json.dumps(_details("unpaid")),
        }
    ]
    sync_payment_recorded_for_paid_lines(conn, 3, 50)
    written = None
    for call in cursor.execute.call_args_list:
        if "UPDATE payout_batch_lines" in call.args[0]:
            written = json.loads(call.args[1][0])
    assert written["settlement"]["payment_recorded"] == "paid"
    assert written["employee_deductions"]["fit"] == 12.5
    recorded = line_payment_recorded(
        {"payment_status": "paid"},
        written,
        {"status": "paid"},
    )
    assert recorded == "paid"


def test_reason_required_and_unpaid_batch_rejected():
    conn = MagicMock()
    with patch("backend.payroll_payout_details.ensure_payout_details_columns"):
        try:
            reopen_paid_status_for_correction(conn, 3, 50, actor_id=1, reason="no")
            assert False, "expected reason error"
        except ValueError as exc:
            assert "reason" in str(exc).lower()
    with patch("backend.payroll_payout_details.ensure_payout_details_columns"), patch(
        "backend.payroll_payout_details.get_payout_batch",
        return_value=_batch([], status="approved_for_payment", finalized=None),
    ):
        try:
            reopen_paid_status_for_correction(conn, 3, 50, actor_id=1, reason="not paid")
            assert False, "expected status error"
        except ValueError as exc:
            assert "paid" in str(exc).lower()
