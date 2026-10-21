"""Supplemental payouts. Local calculations only — no production writes."""

from __future__ import annotations

import inspect
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.payroll_operations import (
    _planned_clock_payloads,
    build_batch_from_time_records,
    ensure_payout_batches_tables,
)
from backend.payroll_overtime import (
    aggregate_classified_batch_lines,
    compute_wage_with_overtime,
)
from backend.payroll_report import _sum_totals
from backend.payroll_report_analytics import employee_summaries_by_category
from backend.payroll_supplemental import (
    attached_session_ids,
    create_supplemental_payout_batch,
    eligibility_conflict,
    validate_batch_sessions_for_finalize,
)

GUIYING_SESSIONS = (
    (1242, 8.00, "2026-08-31T18:00:00"),
    (1264, 2.93, "2026-09-02T11:50:47"),
    (1278, 6.33, "2026-09-03T15:48:34"),
    (1282, 13.38, "2026-09-04T07:51:00"),
    (1304, 8.29, "2026-09-05T13:48:54"),
)
GUIYING_IDS = [sid for sid, _hours, _clock in GUIYING_SESSIONS]
ORIGINAL_PAID_BATCH_ID = 119
ORIGINAL_PAID_GROSS = Decimal("2988.82")


def _temp(sid, hours, clock, *, user_id=27, name="Guiying Lin", rate=17):
    return {
        "id": sid,
        "user_id": user_id,
        "worker_name": name,
        "approved_hours": hours,
        "worker_category": "temp",
        "profile_worker_category": "temp",
        "classification_source": "profile",
        "clock_in_at": clock,
        "resolved_hourly_rate": rate,
        "hourly_rate": rate,
        "profile_hourly_rate": rate,
        "payroll_week_start": "2026-08-31",
    }


def _guiying_records():
    return [_temp(sid, hours, clock) for sid, hours, clock in GUIYING_SESSIONS]


def _line_from_aggregate(records, **kwargs):
    lines = aggregate_classified_batch_lines(
        records,
        batch_category="temp",
        threshold_hours=40,
        ot_enabled=True,
        **kwargs,
    )
    return lines


def test_guiying_historical_week_is_regular_pay_only():
    lines = _line_from_aggregate(_guiying_records())
    assert len(lines) == 1
    line = lines[0]
    assert line["session_ids"] == GUIYING_IDS
    assert line["approved_hours"] == 38.93
    assert line["ot_hours"] == 0.0
    assert line["rate"] == 17.0
    assert compute_wage_with_overtime(38.93, 0, 17) == Decimal("661.81")


def test_already_paid_hours_stay_in_the_overtime_walk():
    records = [
        _temp(1, 30, "2026-08-31T08:00:00"),
        _temp(2, 20, "2026-09-01T08:00:00"),
    ]
    lines = _line_from_aggregate(records, omit_session_ids={1})
    assert len(lines) == 1
    assert lines[0]["session_ids"] == [2]
    assert lines[0]["approved_hours"] == 10.0
    assert lines[0]["ot_hours"] == 10.0


def test_repeated_request_omits_sessions_already_on_a_batch():
    first = _line_from_aggregate(_guiying_records())
    second = _line_from_aggregate(_guiying_records(), omit_session_ids=set(GUIYING_IDS))
    assert first[0]["session_ids"] == GUIYING_IDS
    assert second == []


def test_attached_session_lookup_reads_other_batches_only():
    class Cur:
        def __init__(self):
            self.sql = ""
            self.params = None

        def execute(self, sql, params):
            self.sql = sql
            self.params = params

        def fetchall(self):
            return [
                {"source_shift_session_ids": "[1242, 1264]"},
                {"source_shift_session_ids": [1278]},
            ]

    class Conn:
        def __init__(self):
            self.cur = Cur()

        def cursor(self, dictionary=False):
            return self.cur

    conn = Conn()
    found = attached_session_ids(conn, 3, except_batch_id=501)
    assert found == {1242, 1264, 1278}
    assert "INNER JOIN payout_batches" in conn.cur.sql
    assert "pb.id <> %s" in conn.cur.sql
    assert conn.cur.params == [3, 501]
    assert ORIGINAL_PAID_BATCH_ID not in conn.cur.params


def test_approval_change_blocks_finalize_match():
    stored = [
        {
            "source_type": "clock_records",
            "user_id": 27,
            "approved_hours": 38.93,
            "ot_hours": 0,
            "rate": 17,
            "source_shift_session_ids": GUIYING_IDS,
        }
    ]
    expected = _line_from_aggregate(_guiying_records())
    assert eligibility_conflict(expected, stored) is None
    unapproved = _line_from_aggregate(
        [rec for rec in _guiying_records() if rec["id"] != 1242]
    )
    assert eligibility_conflict(unapproved, stored)
    changed_rate = [{**expected[0], "rate": 18}]
    assert eligibility_conflict(changed_rate, stored)


def test_finalize_refuses_a_session_already_on_another_batch():
    batch = {
        "id": 501,
        "status": "approved_for_payment",
        "lines": [
            {
                "source_type": "clock_records",
                "source_shift_session_ids": [1242],
            }
        ],
    }
    conn = MagicMock()
    paid = {"id": ORIGINAL_PAID_BATCH_ID, "status": "paid", "total_gross_amount": ORIGINAL_PAID_GROSS}
    with patch(
        "backend.payroll_supplemental.attached_session_ids",
        return_value=set(GUIYING_IDS),
    ):
        with pytest.raises(ValueError, match="already on another payout batch"):
            validate_batch_sessions_for_finalize(conn, 3, batch)
    assert paid == {
        "id": ORIGINAL_PAID_BATCH_ID,
        "status": "paid",
        "total_gross_amount": ORIGINAL_PAID_GROSS,
    }
    for call in conn.method_calls:
        assert "UPDATE" not in str(call)


def test_finalize_revalidates_a_supplemental_after_approval_is_removed():
    batch = {
        "id": 501,
        "supplemental_for_user_id": 27,
        "worker_category": "temp",
        "pay_period_start": "2026-08-31",
        "pay_period_end": "2026-09-06",
        "lines": [
            {
                "source_type": "clock_records",
                "user_id": 27,
                "approved_hours": 38.93,
                "ot_hours": 0,
                "rate": 17,
                "source_shift_session_ids": GUIYING_IDS,
            }
        ],
    }
    with patch(
        "backend.payroll_supplemental.attached_session_ids", return_value=set()
    ), patch(
        "backend.payroll_operations.list_time_records", return_value=[]
    ), patch(
        "backend.payroll_operations._planned_clock_payloads", return_value=[]
    ):
        with pytest.raises(ValueError, match="no longer matches"):
            validate_batch_sessions_for_finalize(MagicMock(), 3, batch)


def _supplemental_body(**extra):
    body = {
        "supplemental_for_user_id": 27,
        "worker_category": "temp",
        "pay_period_start": "2026-08-31",
        "pay_period_end": "2026-09-06",
        "status": "paid",
        "batch_name": "TEMP-2026-018",
    }
    body.update(extra)
    return body


def test_empty_repeat_deletes_only_the_new_draft():
    conn = MagicMock()
    cur = MagicMock()
    cur.lastrowid = 501
    conn.cursor.return_value = cur
    with patch("backend.payroll_operations.ensure_payout_batches_tables"), patch(
        "backend.ta_helpers.table_has_column", return_value=True
    ), patch(
        "backend.payroll_operations.build_batch_from_time_records",
        side_effect=ValueError("No approved time records"),
    ), patch("backend.payroll_operations.delete_payout_batch") as delete:
        with pytest.raises(ValueError, match="not included again"):
            create_supplemental_payout_batch(
                conn, 3, _supplemental_body(), created_by=15
            )
    delete.assert_called_once_with(conn, 3, 501)
    sql, params = cur.execute.call_args[0]
    assert "INSERT INTO payout_batches" in sql
    assert "draft" in params
    assert "paid" not in params
    assert 27 in params
    assert "TEMP-SUPP-2026-08-31-U27" in params
    assert "TEMP-2026-018" not in params
    assert ORIGINAL_PAID_BATCH_ID not in params


def test_successful_supplemental_stays_draft_and_is_audited():
    conn = MagicMock()
    cur = MagicMock()
    cur.lastrowid = 501
    conn.cursor.return_value = cur
    built = {
        "id": 501,
        "batch_name": "TEMP-SUPP-2026-08-31-U27",
        "status": "draft",
        "paid_at": None,
        "lines": [
            {
                "user_id": 27,
                "source_shift_session_ids": GUIYING_IDS,
                "gross_amount": 661.81,
            }
        ],
    }
    with patch("backend.payroll_operations.ensure_payout_batches_tables"), patch(
        "backend.ta_helpers.table_has_column", return_value=True
    ), patch(
        "backend.payroll_operations.build_batch_from_time_records", return_value=built
    ) as build, patch("backend.ta_routes.write_audit") as audit:
        row = create_supplemental_payout_batch(conn, 3, _supplemental_body(), created_by=15)
    assert row["status"] == "draft"
    assert row["paid_at"] is None
    assert build.call_args.kwargs["allow_empty"] is False
    assert audit.call_args.args[4] == "supplemental_batch_created"
    assert audit.call_args.kwargs["new"]["status"] == "draft"
    assert audit.call_args.kwargs["new"]["session_ids"] == GUIYING_IDS
    assert ORIGINAL_PAID_BATCH_ID not in audit.call_args.kwargs["new"].values()


def test_build_skips_sessions_already_on_another_batch_and_other_employees():
    records = _guiying_records() + [
        _temp(999, 37.36, "2026-08-31T09:00:00", user_id=16, name="Francis Arita")
    ]
    batch = {
        "id": 501,
        "status": "draft",
        "worker_category": "temp",
        "supplemental_for_user_id": 27,
        "pay_period_start": "2026-08-31",
        "pay_period_end": "2026-09-06",
    }
    captured = {}

    def _add(_conn, _org, batch_id, body):
        captured["batch_id"] = batch_id
        captured["body"] = body
        return {"id": 88}

    conn = MagicMock()
    with patch(
        "backend.payroll_operations._fetch_payout_batch_core", return_value=batch
    ), patch(
        "backend.payroll_operations.list_time_records", return_value=records
    ), patch(
        "backend.payroll_supplemental.attached_session_ids", return_value={999}
    ), patch(
        "backend.payroll_operations.add_payout_batch_line", side_effect=_add
    ), patch(
        "backend.payroll_classification.write_line_classification_provenance"
    ), patch(
        "backend.payroll_workflow.resolve_rate_for_batch_line", return_value=17
    ), patch(
        "backend.payroll_overtime.resolve_batch_overtime_policy",
        return_value={"enabled": True, "threshold_hours": 40, "multiplier": 1.5},
    ), patch(
        "backend.payroll_workflow.recalculate_w2_batch_taxes"
    ), patch(
        "backend.payroll_operations.get_payout_batch",
        return_value={"id": 501, "status": "draft"},
    ):
        build_batch_from_time_records(
            conn, 3, 501, from_date="2026-08-31", to_date="2026-09-06"
        )
    assert captured["batch_id"] == 501
    assert captured["body"]["source_shift_session_ids"] == GUIYING_IDS
    assert captured["body"]["user_id"] == 27
    assert captured["body"]["ot_hours"] == 0.0
    assert captured["body"]["approved_hours"] == 38.93
    assert captured["body"].get("payment_status") is None
    for call in conn.cursor.return_value.execute.call_args_list:
        params = call.args[1] if len(call.args) > 1 else ()
        assert ORIGINAL_PAID_BATCH_ID not in params


def test_refresh_of_already_batched_employee_does_not_reinclude_sessions():
    batch = {
        "id": 700,
        "status": "draft",
        "worker_category": "temp",
        "pay_period_start": "2026-08-31",
        "pay_period_end": "2026-09-06",
    }
    conn = MagicMock()
    with patch(
        "backend.payroll_operations._fetch_payout_batch_core", return_value=batch
    ), patch(
        "backend.payroll_operations.list_time_records", return_value=_guiying_records()
    ), patch(
        "backend.payroll_supplemental.attached_session_ids",
        return_value=set(GUIYING_IDS),
    ), patch(
        "backend.payroll_operations.add_payout_batch_line"
    ) as add, patch(
        "backend.payroll_workflow.resolve_rate_for_batch_line", return_value=17
    ), patch(
        "backend.payroll_overtime.resolve_batch_overtime_policy",
        return_value={"enabled": True, "threshold_hours": 40, "multiplier": 1.5},
    ):
        with pytest.raises(ValueError, match="Approve hours"):
            build_batch_from_time_records(
                conn, 3, 700, from_date="2026-08-31", to_date="2026-09-06"
            )
    add.assert_not_called()


def test_supplemental_plan_keeps_one_employee_when_nothing_is_omitted():
    records = _guiying_records() + [
        _temp(999, 37.36, "2026-08-31T09:00:00", user_id=16, name="Francis Arita")
    ]
    batch = {"worker_category": "temp", "supplemental_for_user_id": 27}
    with patch(
        "backend.payroll_workflow.resolve_rate_for_batch_line", return_value=17
    ), patch(
        "backend.payroll_session_rate.resolve_session_hourly_rate",
        return_value=(Decimal("17"), "profile", None),
    ), patch(
        "backend.payroll_overtime.resolve_batch_overtime_policy",
        return_value={"enabled": True, "threshold_hours": 40, "multiplier": 1.5},
    ):
        planned = _planned_clock_payloads(
            MagicMock(), 3, batch, records, omit_session_ids=set()
        )
    assert len(planned) == 1
    assert planned[0]["user_id"] == 27
    assert planned[0]["session_ids"] == GUIYING_IDS


def test_analysis_adds_the_supplemental_once():
    paid = [
        ("Florentina Llanto", 53, 457.64),
        ("Francis Arita", 16, 635.12),
        ("Jassi Paaji", 60, 496.02),
        ("Tahira Yousuf", 62, 374.00),
        ("Yesenia Yesenia", 36, 1026.04),
    ]
    rows = [
        {
            "user_id": uid,
            "employee_name": name,
            "worker_category": "temp",
            "gross_pay": gross,
            "regular_hours": 1,
            "ot_hours": 0,
            "is_supplemental": False,
        }
        for name, uid, gross in paid
    ]
    rows.append(
        {
            "user_id": 27,
            "employee_name": "Guiying Lin",
            "worker_category": "temp",
            "gross_pay": 661.81,
            "regular_hours": 38.93,
            "ot_hours": 0,
            "is_supplemental": True,
        }
    )
    totals = _sum_totals(rows)
    assert totals["gross_pay"] == 3650.63
    assert float(ORIGINAL_PAID_GROSS) + 661.81 == 3650.63
    summaries = employee_summaries_by_category(rows)["temp"]
    assert len(summaries) == 6
    guiying = next(row for row in summaries if row["user_id"] == 27)
    assert guiying["is_supplemental"] is True
    assert guiying["includes_supplemental"] is True
    assert guiying["gross_pay"] == 661.81
    assert all(row["is_supplemental"] is False for row in summaries if row["user_id"] != 27)
    assert round(sum(row["gross_pay"] for row in summaries), 2) == 3650.63


def test_create_refuses_before_the_schema_migration():
    conn = MagicMock()
    with patch("backend.payroll_operations.ensure_payout_batches_tables"), patch(
        "backend.ta_helpers.table_has_column", return_value=False
    ), patch("backend.payroll_operations.build_batch_from_time_records") as build:
        with pytest.raises(ValueError, match="payout_batch_supplemental_v1.sql"):
            create_supplemental_payout_batch(conn, 3, _supplemental_body(), created_by=15)
    build.assert_not_called()
    executed = " ".join(str(call.args[0]) for call in conn.cursor.return_value.execute.call_args_list)
    assert "INSERT INTO payout_batches" not in executed


def test_schema_migration_is_additive_and_runtime_requests_do_not_alter():
    sql_path = (
        Path(__file__).resolve().parents[1] / "sql" / "payout_batch_supplemental_v1.sql"
    )
    raw = sql_path.read_text(encoding="utf-8")
    executable = "\n".join(
        line for line in raw.splitlines() if not line.strip().startswith("--")
    ).lower()
    assert "add column supplemental_for_user_id int null" in executable
    assert "add column supplemental_reason varchar(500) null" in executable
    assert "information_schema.columns" in executable
    for forbidden in ("update ", "delete ", "drop ", "shift_sessions", "payroll_payments"):
        assert forbidden not in executable
    source = inspect.getsource(ensure_payout_batches_tables)
    assert "ADD COLUMN supplemental_for_user_id" not in source
    assert "ADD COLUMN supplemental_reason" not in source
