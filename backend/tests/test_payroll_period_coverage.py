"""Historical period completeness: eligible work must be on effective batches."""

from __future__ import annotations

from unittest.mock import patch

from backend.payroll_period_coverage import (
    iter_unbatched_eligible_records,
    period_completeness_status,
    period_eligible_work_fully_batched,
)
from backend.payroll_report_analytics import (
    build_period_comparison_entries,
    period_batches_are_complete,
)


def _rec(sid, uid, cat, hours):
    return {
        "id": sid,
        "user_id": uid,
        "worker_category": cat,
        "approved_hours": hours,
        "worker_name": f"User {uid}",
    }


def test_aug10_without_temp_is_incomplete():
    """W2+1099 terminal but 153.43 Temp-eligible clocks unbatched → Incomplete."""
    approved = [
        _rec(1, 26, "w2", 40.0),
        _rec(2, 19, "contractor_1099", 40.0),
        _rec(10, 16, "temp", 37.14),
        _rec(11, 27, "temp", 42.40),
        _rec(12, 36, "temp", 51.95),
        _rec(13, 53, "temp", 21.94),
    ]
    # Only W2 + 1099 sessions on effective batches
    covered_sessions = {1, 2}
    covered_user_cats = {(26, "w2"), (19, "contractor_1099")}

    with patch(
        "backend.payroll_period_coverage.list_eligible_approved_session_facts",
        return_value=approved,
    ):
        unbatched = iter_unbatched_eligible_records(
            object(),
            3,
            "2026-08-10",
            "2026-08-16",
            covered_sessions=covered_sessions,
            covered_user_cats=covered_user_cats,
        )
    hours = round(sum(float(r["approved_hours"]) for r in unbatched), 2)
    assert hours == 153.43
    assert len(unbatched) == 4

    with patch(
        "backend.payroll_period_coverage.iter_unbatched_eligible_records",
        return_value=unbatched,
    ):
        st = period_completeness_status(
            object(),
            3,
            "2026-08-10",
            "2026-08-16",
            batches_terminal=True,
        )
    assert st["is_complete"] is False
    assert st["completeness_status"] == "incomplete"
    assert st["completeness_label"] == "Incomplete / payroll pending"
    assert st["unbatched_eligible_hours"] == 153.43


def test_aug10_with_temp_is_complete():
    """After TEMP-015, all eligible sessions represented → Complete; totals unchanged."""
    approved = [
        _rec(1, 26, "w2", 40.0),
        _rec(2, 19, "contractor_1099", 40.0),
        _rec(10, 16, "temp", 37.14),
        _rec(11, 27, "temp", 42.40),
        _rec(12, 36, "temp", 51.95),
        _rec(13, 53, "temp", 21.94),
    ]
    covered_sessions = {1, 2, 10, 11, 12, 13}
    covered_user_cats = {
        (26, "w2"),
        (19, "contractor_1099"),
        (16, "temp"),
        (27, "temp"),
        (36, "temp"),
        (53, "temp"),
    }
    with patch(
        "backend.payroll_period_coverage.load_effective_batch_coverage",
        return_value=(covered_sessions, covered_user_cats),
    ), patch(
        "backend.payroll_period_coverage.list_eligible_approved_session_facts",
        return_value=approved,
    ):
        assert period_eligible_work_fully_batched(object(), 3, "2026-08-10", "2026-08-16")

    with patch(
        "backend.payroll_period_coverage.iter_unbatched_eligible_records",
        return_value=[],
    ):
        st = period_completeness_status(
            object(), 3, "2026-08-10", "2026-08-16", batches_terminal=True
        )
    assert st["is_complete"] is True
    assert st["completeness_status"] == "complete"
    assert st["completeness_label"] == "Complete"

    entries = build_period_comparison_entries(
        {("2026-08-10", "2026-08-16"): []},
        [("2026-08-10", "2026-08-16")],
        completeness_by_period={
            ("2026-08-10", "2026-08-16"): st,
        },
    )
    assert entries[0]["is_complete"] is True
    assert entries[0]["completeness_status"] == "complete"
    assert "gross_pay" in entries[0]


def test_nuclear_delete_marks_period_incomplete():
    """Delete one category batch while eligible work remains → Incomplete."""
    approved = [
        _rec(1, 26, "w2", 40.0),
        _rec(10, 16, "temp", 37.14),
    ]
    # After nuclear-delete Temp batch: only W2 covered
    covered_sessions = {1}
    covered_user_cats = {(26, "w2")}
    with patch(
        "backend.payroll_period_coverage.list_eligible_approved_session_facts",
        return_value=approved,
    ):
        unbatched = iter_unbatched_eligible_records(
            object(),
            3,
            "2026-08-10",
            "2026-08-16",
            covered_sessions=covered_sessions,
            covered_user_cats=covered_user_cats,
        )
    assert len(unbatched) == 1
    assert unbatched[0]["worker_category"] == "temp"

    with patch(
        "backend.payroll_period_coverage.iter_unbatched_eligible_records",
        return_value=unbatched,
    ):
        st = period_completeness_status(
            object(), 3, "2026-08-10", "2026-08-16", batches_terminal=True
        )
    assert st["is_complete"] is False
    assert st["completeness_label"] == "Incomplete / payroll pending"


def test_recreate_batch_returns_complete():
    """Recreate equivalent category batch → Complete again."""
    approved = [
        _rec(1, 26, "w2", 40.0),
        _rec(10, 16, "temp", 37.14),
    ]
    covered_sessions = {1, 10}
    covered_user_cats = {(26, "w2"), (16, "temp")}
    with patch(
        "backend.payroll_period_coverage.load_effective_batch_coverage",
        return_value=(covered_sessions, covered_user_cats),
    ), patch(
        "backend.payroll_period_coverage.list_eligible_approved_session_facts",
        return_value=approved,
    ):
        assert period_eligible_work_fully_batched(object(), 3, "2026-08-10", "2026-08-16")

    with patch(
        "backend.payroll_period_coverage.iter_unbatched_eligible_records",
        return_value=[],
    ):
        st = period_completeness_status(
            object(), 3, "2026-08-10", "2026-08-16", batches_terminal=True
        )
    assert st["is_complete"] is True
    assert st["completeness_status"] == "complete"


def test_batch_terminal_alone_still_true_without_coverage_check():
    """Legacy batch-status helper unchanged (coverage is a separate gate)."""
    assert period_batches_are_complete(
        [
            {
                "pay_period_start": "2026-08-10",
                "pay_period_end": "2026-08-16",
                "worker_category": "w2",
                "status": "paid",
            },
            {
                "pay_period_start": "2026-08-10",
                "pay_period_end": "2026-08-16",
                "worker_category": "contractor_1099",
                "status": "paid",
            },
        ]
    )


def test_incomplete_entry_keeps_partial_totals_visible():
    """Incomplete flag does not suppress showing current partial batch metrics."""
    from backend.payroll_report import build_report_row

    line = {
        "id": 1,
        "user_id": 26,
        "worker_name_snapshot": "W2 Worker",
        "approved_hours": 170.15,
        "ot_hours": 15.11,
        "rate": 17.0,
        "ot_rate": 25.5,
        "gross_amount": 3277.86,
        "total_amount": 3277.86,
        "gross_wages": 3277.86,
        "sick_pay_amount": 0,
        "bonus_tip_amount": 0,
        "reimbursement_amount": 0,
        "adjustments": 0,
        "payment_status": "paid",
        "net_pay": 2628.33,
        "payout_details": {
            "settlement": {
                "amount_paid": 2628.33,
                "amount_withheld": 649.53,
                "outstanding_balance": 0,
                "paid_full_gross_without_withholding": False,
            },
            "employer_taxes": {"employer_social_security": 200},
        },
    }
    batch = {
        "id": 85,
        "batch_name": "W2-2025-015",
        "worker_category": "w2",
        "pay_period_start": "2026-08-10",
        "pay_period_end": "2026-08-16",
        "status": "paid",
        "official_pay_date": "2026-08-19",
        "payout_details_finalized_at": "2026-08-19T06:22:37",
    }
    row = build_report_row(batch, line, report_type="payroll_period")
    entries = build_period_comparison_entries(
        {("2026-08-10", "2026-08-16"): [row]},
        [("2026-08-10", "2026-08-16")],
        completeness_by_period={
            ("2026-08-10", "2026-08-16"): {
                "is_complete": False,
                "completeness_status": "incomplete",
                "completeness_label": "Incomplete / payroll pending",
                "unbatched_eligible_hours": 153.43,
                "unbatched_eligible_count": 4,
            }
        },
    )
    e = entries[0]
    assert e["is_complete"] is False
    assert e["completeness_label"] == "Incomplete / payroll pending"
    assert e["unbatched_eligible_hours"] == 153.43
    assert float(e["total_hours"]) > 0
    assert float(e["gross_pay"]) > 0
