"""Batch-level Send to Accountant routing vs Finance unlock."""

from unittest.mock import MagicMock, patch

from backend.payroll_status_display import (
    batch_ready_for_payout_details,
    can_finalize_payout_details,
    compute_primary_action,
    enrich_batch_payroll_display,
)
from backend.payroll_worker_categories import (
    batch_send_to_accountant_enabled,
    default_send_to_accountant_for_category,
)
from backend.payroll_workflow import _available_batch_actions


def test_category_defaults_for_send_to_accountant():
    assert default_send_to_accountant_for_category("w2") is True
    assert default_send_to_accountant_for_category("contractor_1099") is False
    assert default_send_to_accountant_for_category("temp") is False
    assert default_send_to_accountant_for_category("tryout") is False


def test_manual_override_per_batch():
    assert batch_send_to_accountant_enabled(
        {"worker_category": "contractor_1099", "send_to_accountant": 1}
    )
    assert not batch_send_to_accountant_enabled(
        {"worker_category": "w2", "send_to_accountant": 0}
    )


def test_same_week_batches_keep_independent_routing():
    w2 = {"id": 120, "worker_category": "w2", "send_to_accountant": 1, "status": "hours_reviewed"}
    evelyn = {
        "id": 122,
        "worker_category": "w2",
        "send_to_accountant": 1,
        "status": "hours_reviewed",
    }
    c1099 = {
        "id": 130,
        "worker_category": "contractor_1099",
        "send_to_accountant": 0,
        "status": "hours_reviewed",
    }
    temp = {
        "id": 131,
        "worker_category": "temp",
        "send_to_accountant": 0,
        "status": "hours_reviewed",
    }
    assert "send_to_accountant" in _available_batch_actions(w2)
    assert "send_to_accountant" in _available_batch_actions(evelyn)
    assert "send_to_accountant" not in _available_batch_actions(c1099)
    assert "send_to_accountant" not in _available_batch_actions(temp)

    # Manual override: 1099 can require accountant without changing other 1099s.
    c1099_yes = {**c1099, "send_to_accountant": 1}
    assert "send_to_accountant" in _available_batch_actions(c1099_yes)


def test_w2_default_shows_send_button_after_approve():
    batch = enrich_batch_payroll_display(
        {
            "status": "hours_reviewed",
            "worker_category": "w2",
            "send_to_accountant": 1,
            "total_payout_amount": 500,
        }
    )
    assert batch["payroll_display"]["send_to_accountant"] is True
    assert batch["payroll_display"]["primary_action"]["action"] == "send_to_accountant"


def test_w2_with_routing_off_skips_send_button():
    batch = enrich_batch_payroll_display(
        {
            "status": "hours_reviewed",
            "worker_category": "w2",
            "send_to_accountant": 0,
            "total_payout_amount": 500,
        }
    )
    assert batch["payroll_display"]["send_to_accountant"] is False
    assert batch["payroll_display"]["skips_accountant_review"] is True
    assert batch["payroll_display"]["primary_action"]["action"] == "enter_details"
    assert batch_ready_for_payout_details(batch)


def test_finance_not_blocked_on_legacy_sent_to_accountant():
    """Stranded sent_to_accountant rows must be Finance-ready without process_batch."""
    batch = {
        "status": "sent_to_accountant",
        "worker_category": "w2",
        "send_to_accountant": 1,
    }
    assert batch_ready_for_payout_details(batch)
    assert can_finalize_payout_details(batch)
    action = compute_primary_action(batch)
    assert action["action"] == "enter_details"
    assert action.get("disabled") is not True


def test_send_to_accountant_action_unlocks_finance_status():
    """Manager handoff writes approved_for_payment (no accountant click)."""
    from backend.payroll_workflow import apply_batch_workflow_action

    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    batch = {
        "id": 55,
        "status": "hours_reviewed",
        "worker_category": "w2",
        "send_to_accountant": 1,
        "lines": [{"id": 1, "user_id": 9}],
        "missing_rates": [],
        "missing_w4": [],
    }
    enriched = {**batch, "available_actions": ["send_to_accountant"]}
    after = {**batch, "status": "approved_for_payment"}
    with patch(
        "backend.payroll_workflow.get_payout_batch",
        side_effect=[batch, after],
    ), patch(
        "backend.payroll_workflow.enrich_payout_batch",
        side_effect=[enriched, after],
    ), patch("backend.payroll_workflow.backfill_batch_line_rates", return_value=False), patch(
        "backend.payroll_workflow.validate_batch_for_workflow"
    ), patch("backend.payroll_workflow.ensure_payout_batch_line_extensions"):
        out = apply_batch_workflow_action(
            conn, 1, 55, "send_to_accountant", actor_id=3
        )
    sql = " ".join(str(c.args[0]) for c in cursor.execute.call_args_list)
    assert "approved_for_payment" in sql
    assert "sent_to_accountant_at" in sql
    assert out["status"] == "approved_for_payment"
