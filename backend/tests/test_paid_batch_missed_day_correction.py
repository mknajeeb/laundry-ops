"""Synthetic paid-batch correction accounting. No production rows."""

import json
from unittest.mock import MagicMock, patch

from backend.payroll_correction_settlement import (
    correction_balances,
    dashboard_slice,
    open_correction_ledger,
    record_additional_payment,
    stamp_settlement,
)
from backend.payroll_operations import (
    _restore_correction_ledgers,
    build_batch_from_time_records,
)
from backend.payroll_payout_details import (
    _render_paystub_html,
    compute_line_totals,
    parse_line_payout_details,
    reopen_paid_status_for_correction,
    sync_payment_recorded_for_paid_lines,
)
from backend.payroll_period_coverage import (
    iter_unbatched_eligible_records,
    load_effective_batch_coverage,
)
from backend.payroll_workflow import enrich_payout_batch


def _paid_details(amount=600.0, reference="ACH-600", pay_date="2026-09-18"):
    return {
        "employee_deductions": {"fit": 0, "ss": 0, "medicare": 0, "state": 0},
        "employer_taxes": {},
        "payment": {
            "date": pay_date,
            "method": "direct_deposit",
            "reference": reference,
            "check_number": "",
        },
        "settlement": {
            "amount_paid": amount,
            "amount_withheld": 0.0,
            "outstanding_balance": 0.0,
            "payment_recorded": "paid",
        },
        "tax_summary": {"current_period_taxes": 0.0},
    }


def _reopen_blob(amount=600.0):
    batch = {
        "id": 9001,
        "organization_id": 3,
        "status": "paid",
        "worker_category": "w2",
        "paid_at": "2026-09-18T16:00:00",
        "payout_details_finalized_at": "2026-09-18T15:00:00",
        "payout_details_finalized_by": 4,
        "payout_details_audit_json": json.dumps({"events": []}),
        "lines": [
            {
                "id": 77,
                "user_id": 7,
                "worker_name_snapshot": "Synthetic Worker",
                "payment_status": "paid",
                "payment_date": "2026-09-18",
                "payment_reference": "ACH-600",
                "gross_amount": amount,
                "total_amount": amount,
                "payout_details_json": json.dumps(_paid_details(amount)),
            }
        ],
    }
    conn = MagicMock()
    conn.cursor.return_value.rowcount = 1
    with patch("backend.payroll_payout_details.ensure_payout_details_columns"), patch(
        "backend.payroll_payout_details.get_payout_batch", return_value=batch
    ), patch(
        "backend.payroll_payout_details.get_payout_batch_details",
        return_value={"id": 9001},
    ):
        reopen_paid_status_for_correction(
            conn, 3, 9001, actor_id=4, reason="Missed day discovered"
        )
    batch_sql = None
    line_blob = None
    line_sql = None
    for call in conn.cursor.return_value.execute.call_args_list:
        sql = call.args[0]
        if "UPDATE payout_batches" in sql:
            batch_sql = sql
        if "UPDATE payout_batch_lines" in sql:
            line_blob = json.loads(call.args[1][0])
            line_sql = sql
    assert batch_sql and "correction_reopened_at=NOW()" in batch_sql
    if line_blob is None:
        raise AssertionError("line update missing")
    return line_blob, line_sql


def _cache():
    cache = MagicMock()
    cache.meta_for.return_value = {"employee_id": "E1"}
    cache.rate_info_for.return_value = {
        "worker_category_label": "W-2",
        "payment_method": None,
        "hourly_rate": 15,
        "rate_missing": False,
        "rate_source": "test",
    }
    cache.sick_for.return_value = {
        "balance_hours": 0,
        "ytd_accrued_hours": 0,
        "ytd_used_hours": 0,
    }
    return cache


def _summary_for(details, *, gross, batch_status="approved_for_payment"):
    batch = {
        "id": 9001,
        "status": batch_status,
        "worker_category": "w2",
        "worker_category_label": "W-2",
        "pay_period_start": "2026-09-07",
        "pay_period_end": "2026-09-13",
        "lines": [
            {
                "id": 77,
                "user_id": 7,
                "worker_name_snapshot": "Synthetic Worker",
                "payment_status": "approved_unpaid",
                "gross_amount": gross,
                "total_amount": gross,
                "rate": 15,
                "payout_details_json": json.dumps(details),
            }
        ],
    }
    with patch("backend.payroll_workflow.ensure_payout_batch_line_extensions"):
        out = enrich_payout_batch(MagicMock(), 3, batch, enrich_cache=_cache())
    return out["payroll_display"]["payroll_summary"], out["summary"]


def test_balances_match_the_required_formulas():
    under = correction_balances(720, 600)
    assert under["remaining_due"] == 120
    assert under["overpayment"] == 0
    assert under["amount_paid"] == 600
    over = correction_balances(480, 600)
    assert over["remaining_due"] == 0
    assert over["overpayment"] == 120
    same = correction_balances(600, 600)
    assert same["remaining_due"] == 0
    assert same["overpayment"] == 0


def test_a_underpayment_then_second_payment_keeps_both_events():
    blob, sql = _reopen_blob()
    assert "payment_status='approved_unpaid'" in sql
    settlement = blob["settlement"]
    assert settlement["correction_accounting"] is True
    assert settlement["cumulative_amount_paid"] == 600
    assert settlement["payment_history"][0]["reference"] == "ACH-600"
    assert settlement["payment_history"][0]["payment_date"] == "2026-09-18"
    assert settlement["payment_history"][0]["kind"] == "original"
    assert blob["payment"]["reference"] == ""

    settlement = stamp_settlement(settlement, 720)
    assert settlement["corrected_net"] == 720
    assert settlement["remaining_due"] == 120
    assert settlement["cumulative_amount_paid"] == 600

    paid = record_additional_payment(
        settlement, payment_date="2026-09-25", reference="ACH-120"
    )
    assert paid["cumulative_amount_paid"] == 720
    assert paid["remaining_due"] == 0
    assert paid["overpayment"] == 0
    assert len(paid["payment_history"]) == 2
    assert paid["payment_history"][0]["reference"] == "ACH-600"
    assert paid["payment_history"][0]["amount"] == 600
    assert paid["payment_history"][1]["reference"] == "ACH-120"
    assert paid["payment_history"][1]["amount"] == 120
    assert paid["payment_history"][1]["kind"] == "correction"

    again = record_additional_payment(
        paid, payment_date="2026-09-25", reference="ACH-120"
    )
    assert len(again["payment_history"]) == 2
    assert again["cumulative_amount_paid"] == 720


def test_b_no_monetary_change_has_nothing_due():
    blob, _sql = _reopen_blob()
    settlement = stamp_settlement(blob["settlement"], 600)
    assert settlement["remaining_due"] == 0
    assert settlement["overpayment"] == 0
    assert settlement["cumulative_amount_paid"] == 600
    paid = record_additional_payment(settlement, payment_date="2026-09-25", reference="NONE")
    assert len(paid["payment_history"]) == 1
    assert paid["payment_history"][0]["reference"] == "ACH-600"


def test_c_overpayment_is_represented_and_not_recovered():
    blob, _sql = _reopen_blob()
    settlement = stamp_settlement(blob["settlement"], 480)
    assert settlement["corrected_net"] == 480
    assert settlement["cumulative_amount_paid"] == 600
    assert settlement["remaining_due"] == 0
    assert settlement["overpayment"] == 120
    paid = record_additional_payment(settlement, payment_date="2026-09-25", reference="ACH-X")
    assert len(paid["payment_history"]) == 1
    assert paid["overpayment"] == 120
    assert paid["cumulative_amount_paid"] == 600


def test_d_repeated_reopen_keeps_cumulative_history():
    blob, _sql = _reopen_blob()
    settlement = record_additional_payment(
        stamp_settlement(blob["settlement"], 720),
        payment_date="2026-09-25",
        reference="ACH-120",
    )
    settlement["payment_recorded"] = "paid"
    stored = _paid_details()
    stored["settlement"] = settlement
    stored["payment"] = {"date": "2026-09-25", "method": "direct_deposit", "reference": "ACH-120"}
    batch = {
        "id": 9001,
        "organization_id": 3,
        "status": "paid",
        "worker_category": "w2",
        "paid_at": "2026-09-25T12:00:00",
        "payout_details_finalized_at": "2026-09-25T11:00:00",
        "payout_details_audit_json": json.dumps(
            {"events": [{"event": "payment_reversed_for_correction", "lines": []}]}
        ),
        "lines": [
            {
                "id": 77,
                "user_id": 7,
                "payment_status": "paid",
                "payment_date": "2026-09-25",
                "payment_reference": "ACH-120",
                "gross_amount": 720,
                "total_amount": 720,
                "payout_details_json": json.dumps(stored),
            }
        ],
    }
    conn = MagicMock()
    conn.cursor.return_value.rowcount = 1
    with patch("backend.payroll_payout_details.ensure_payout_details_columns"), patch(
        "backend.payroll_payout_details.get_payout_batch", return_value=batch
    ), patch(
        "backend.payroll_payout_details.get_payout_batch_details", return_value={"id": 9001}
    ):
        reopen_paid_status_for_correction(
            conn, 3, 9001, actor_id=4, reason="Second correction"
        )
    written = None
    for call in conn.cursor.return_value.execute.call_args_list:
        if "UPDATE payout_batch_lines" in call.args[0]:
            written = json.loads(call.args[1][0])
    history = written["settlement"]["payment_history"]
    assert [row["reference"] for row in history] == ["ACH-600", "ACH-120"]
    assert written["settlement"]["cumulative_amount_paid"] == 720
    assert sum(row["amount"] for row in history) == 720
    later = stamp_settlement(written["settlement"], 800)
    assert later["remaining_due"] == 80
    assert later["cumulative_amount_paid"] == 720
    assert [row["reference"] for row in later["payment_history"]] == ["ACH-600", "ACH-120"]


def test_e_refresh_adds_the_missing_day_to_the_same_batch_and_keeps_paid_cash():
    batch = {
        "id": 9001,
        "organization_id": 3,
        "status": "approved_for_payment",
        "correction_reopened_at": "2026-09-20 15:00:00",
        "worker_category": "w2",
        "pay_period_start": "2026-09-07",
        "pay_period_end": "2026-09-13",
    }
    records = []
    for sid, day in enumerate((7, 8, 9, 10, 11), start=1):
        records.append(
            {
                "id": sid,
                "user_id": 7,
                "worker_name": "Synthetic Worker",
                "worker_category": "w2",
                "profile_worker_category": "w2",
                "classification_source": "profile",
                "approved_hours": 9,
                "clock_in_at": f"2026-09-{day:02d}T08:00:00",
                "work_date": f"2026-09-{day:02d}",
            }
        )
    captured = {}

    def _add(_conn, _org, batch_id, body):
        captured["batch_id"] = batch_id
        captured["body"] = body
        return {"id": 88}

    ledger = {
        "correction_accounting": True,
        "cumulative_amount_paid": 600.0,
        "payment_history": [
            {
                "amount": 600.0,
                "payment_date": "2026-09-18",
                "reference": "ACH-600",
                "kind": "original",
            }
        ],
    }
    with patch(
        "backend.payroll_operations._fetch_payout_batch_core", return_value=batch
    ), patch(
        "backend.payroll_operations.list_time_records", return_value=records
    ), patch(
        "backend.payroll_operations._load_correction_ledgers", return_value={7: ledger}
    ), patch(
        "backend.payroll_operations.add_payout_batch_line", side_effect=_add
    ), patch(
        "backend.payroll_classification.write_line_classification_provenance"
    ), patch(
        "backend.payroll_workflow.resolve_rate_for_batch_line", return_value=20
    ), patch(
        "backend.payroll_overtime.resolve_batch_overtime_policy",
        return_value={"enabled": True, "threshold_hours": 40, "multiplier": 1.5},
    ), patch(
        "backend.payroll_workflow.recalculate_w2_batch_taxes"
    ), patch(
        "backend.payroll_operations._restore_correction_ledgers"
    ) as restore, patch(
        "backend.payroll_operations.get_payout_batch", return_value={"id": 9001}
    ):
        build_batch_from_time_records(
            MagicMock(),
            3,
            9001,
            from_date="2026-09-07",
            to_date="2026-09-13",
        )
    assert captured["batch_id"] == 9001
    assert 5 in captured["body"]["source_shift_session_ids"]
    assert captured["body"]["ot_hours"] == 5.0
    assert captured["body"]["approved_hours"] == 40.0
    restore.assert_called_once()
    assert restore.call_args.args[2] == 9001
    assert restore.call_args.args[3][7]["cumulative_amount_paid"] == 600

    conn = MagicMock()
    select_cur = MagicMock()
    update_cur = MagicMock()

    def _cursor(*_args, **kwargs):
        if kwargs.get("dictionary"):
            return select_cur
        return update_cur

    conn.cursor.side_effect = _cursor
    select_cur.fetchall.return_value = [
        {
            "id": 88,
            "user_id": 7,
            "gross_amount": 720,
            "total_amount": 720,
            "payout_details_json": "{}",
        }
    ]
    _restore_correction_ledgers(conn, 3, 9001, {7: ledger})
    written = None
    for call in update_cur.execute.call_args_list:
        if "UPDATE payout_batch_lines" in call.args[0]:
            written = json.loads(call.args[1][0])
    settlement = written["settlement"]
    assert settlement["corrected_net"] == 720
    assert settlement["cumulative_amount_paid"] == 600
    assert settlement["remaining_due"] == 120
    assert settlement["payment_history"][0]["reference"] == "ACH-600"


def test_refresh_refused_unless_explicitly_reopened_for_correction():
    refused = {
        "id": 12,
        "status": "approved_for_payment",
        "worker_category": "w2",
        "correction_reopened_at": None,
    }
    with patch(
        "backend.payroll_operations._fetch_payout_batch_core", return_value=refused
    ):
        try:
            build_batch_from_time_records(
                MagicMock(), 3, 12, from_date="2026-09-07", to_date="2026-09-13"
            )
            assert False, "expected refresh refusal"
        except ValueError as exc:
            assert "reopened for correction" in str(exc)


def test_f_missing_session_cannot_be_paid_on_another_batch():
    cur = MagicMock()
    cur.fetchall.return_value = [
        {
            "id": 9001,
            "status": "approved_for_payment",
            "correction_reopened_at": "2026-09-20 15:00:00",
            "worker_category": "w2",
            "user_id": 7,
            "payout_details_finalized_at": None,
            "source_shift_session_ids": [1, 2, 3, 4],
        },
        {
            "id": 44,
            "status": "approved_for_payment",
            "correction_reopened_at": None,
            "worker_category": "w2",
            "user_id": 8,
            "payout_details_finalized_at": None,
            "source_shift_session_ids": [9],
        },
    ]
    conn = MagicMock()
    conn.cursor.return_value = cur
    with patch("backend.ta_helpers.table_has_column", return_value=True):
        sessions, cats = load_effective_batch_coverage(conn, 3, "2026-09-07", "2026-09-13")
    assert (7, "w2") in cats
    assert (8, "w2") not in cats
    assert 1 in sessions
    missed = {
        "id": 5,
        "user_id": 7,
        "worker_category": "w2",
        "approved_hours": 8,
    }
    unbatched = iter_unbatched_eligible_records(
        conn,
        3,
        "2026-09-07",
        "2026-09-13",
        covered_sessions=sessions,
        covered_user_cats=cats,
        eligible_records=[missed],
    )
    assert unbatched == []


def test_dashboard_uses_settlement_amounts_not_binary_status():
    blob, _sql = _reopen_blob()
    under = dict(blob)
    under["settlement"] = stamp_settlement(blob["settlement"], 720)
    summary, raw = _summary_for(under, gross=720)
    assert summary["net_payroll"] == 720
    assert summary["paid_amount"] == 600
    assert summary["outstanding_amount"] == 120
    assert summary["overpayment_amount"] == 0
    assert raw["paid_amount"] + raw["unpaid_amount"] == 720
    assert raw["gross_total"] == 720

    settled = record_additional_payment(
        under["settlement"], payment_date="2026-09-25", reference="ACH-120"
    )
    under["settlement"] = settled
    summary, _raw = _summary_for(under, gross=720, batch_status="paid")
    assert summary["net_payroll"] == 720
    assert summary["paid_amount"] == 720
    assert summary["outstanding_amount"] == 0

    over = dict(blob)
    over["settlement"] = stamp_settlement(blob["settlement"], 480)
    summary, raw = _summary_for(over, gross=480)
    assert summary["net_payroll"] == 480
    assert summary["paid_amount"] == 600
    assert summary["outstanding_amount"] == 0
    assert summary["overpayment_amount"] == 120
    assert raw["paid_amount"] + raw["unpaid_amount"] != 1080


def test_historical_paid_batch_without_reopen_is_unchanged():
    details = _paid_details()
    assert dashboard_slice(details) is None
    summary, raw = _summary_for(details, gross=600, batch_status="paid")
    line = {
        "payment_status": "paid",
        "total_amount": 600,
        "payout_details_json": json.dumps(details),
    }
    parsed = parse_line_payout_details(line)
    assert "correction_accounting" not in parsed["settlement"] or not parsed["settlement"].get(
        "correction_accounting"
    )
    assert summary["paid_amount"] == 600
    assert summary["outstanding_amount"] == 0
    assert float(summary["overpayment_amount"] or 0) == 0
    assert raw["gross_total"] == 600
    totals = compute_line_totals(
        {"gross_amount": 600, "total_amount": 600}, details
    )
    assert totals["correction_accounting"] is False
    assert totals["amount_paid"] == 600


def test_paystub_distinguishes_corrected_net_from_payments():
    blob, _sql = _reopen_blob()
    details = dict(blob)
    details["settlement"] = stamp_settlement(blob["settlement"], 720)
    details["payment"] = {"method": "direct_deposit", "date": None, "reference": ""}
    line = {
        "worker_name_snapshot": "Synthetic Worker",
        "approved_hours": 40,
        "rate": 18,
        "gross_amount": 720,
        "total_amount": 720,
    }
    batch = {
        "status": "approved_for_payment",
        "worker_category": "w2",
        "pay_period_start": "2026-09-07",
        "pay_period_end": "2026-09-13",
        "document_mode": "official_paystub",
    }
    totals = compute_line_totals(line, details)
    html = _render_paystub_html(batch, line, details, totals, preview=True)
    assert "Corrected net" in html
    assert "Previously paid" in html
    assert "Additional amount due" in html
    assert "ACH-600" in html
    assert "$720.00" in html
    assert "$600.00" in html
    assert "$120.00" in html
    assert "Amount received" not in html

    details["settlement"] = record_additional_payment(
        details["settlement"], payment_date="2026-09-25", reference="ACH-120"
    )
    totals = compute_line_totals(line, details)
    html = _render_paystub_html(batch, line, details, totals, preview=True)
    assert "ACH-600" in html
    assert "ACH-120" in html
    assert html.count("ACH-600") >= 1

    details["settlement"] = stamp_settlement(open_correction_ledger(
        {"amount_paid": 600, "outstanding_balance": 0, "payment_recorded": "paid"},
        amount_paid=600,
        payment_date="2026-09-18",
        reference="ACH-600",
    ), 480)
    line["gross_amount"] = 480
    line["total_amount"] = 480
    totals = compute_line_totals(line, details)
    html = _render_paystub_html(batch, line, details, totals, preview=True)
    assert "Overpayment" in html
    assert "$480.00" in html
    assert "$120.00" in html
    assert "not withheld" not in html.lower()


def test_sync_appends_only_the_remainder():
    blob, _sql = _reopen_blob()
    details = dict(blob)
    details["settlement"] = stamp_settlement(blob["settlement"], 720)
    details["settlement"]["payment_recorded"] = "unpaid"
    conn = MagicMock()
    conn.cursor.return_value.fetchall.return_value = [
        {
            "id": 77,
            "payment_status": "paid",
            "payment_date": "2026-09-25",
            "payment_reference": "ACH-120",
            "payout_details_json": json.dumps(details),
        }
    ]
    sync_payment_recorded_for_paid_lines(
        conn, 3, 9001, payment_date="2026-09-25", payment_reference="ACH-120"
    )
    written = None
    for call in conn.cursor.return_value.execute.call_args_list:
        if "UPDATE payout_batch_lines" in call.args[0]:
            written = json.loads(call.args[1][0])
    history = written["settlement"]["payment_history"]
    assert [row["reference"] for row in history] == ["ACH-600", "ACH-120"]
    assert written["settlement"]["cumulative_amount_paid"] == 720
    assert written["settlement"]["remaining_due"] == 0
    assert written["settlement"]["payment_recorded"] == "paid"
