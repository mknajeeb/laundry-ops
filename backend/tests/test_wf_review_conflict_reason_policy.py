"""WF Review / Edit Bag — conflict UX support + relaxed reason policy."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.daily_operations import POST_SOURCE_WEIGHT_ROLE_POST
from backend.daily_operations_wf_review import (
    _validate_save_payload,
    save_wf_review,
)
from backend.rinse_step1_edit_bag import (
    SYSTEM_ACTION_WORKITEMS_UPDATED,
    apply_unified_bag_edit,
    classify_edit_reason_requirements,
    resolve_edit_audit_reason,
)


DAY = date(2026, 7, 24)
ORG = 3
BAG = "BAG1"


def test_routine_workitem_save_no_reason_required_validation():
    errs = _validate_save_payload(
        {
            "items": [{"workitem_id": 1, "quantity": 2}],
        },
        current_post=10.0,
    )
    assert errs == []


def test_post_correction_without_reason_code_rejected():
    errs = _validate_save_payload(
        {
            "corrected_post_weight_lbs": 12.5,
            "items": [{"workitem_id": 1, "quantity": 1}],
        },
        current_post=10.0,
    )
    assert "post_correction_reason_code_required" in errs


def test_post_correction_other_requires_note():
    errs = _validate_save_payload(
        {
            "corrected_post_weight_lbs": 12.5,
            "reason_code": "OTHER",
            "items": [{"workitem_id": 1, "quantity": 1}],
        },
        current_post=10.0,
    )
    assert "reason_note_required_for_other" in errs


def test_post_correction_standard_code_without_note_ok():
    errs = _validate_save_payload(
        {
            "corrected_post_weight_lbs": 12.5,
            "reason_code": "POST_CORRECTION",
            "items": [{"workitem_id": 1, "quantity": 1}],
        },
        current_post=10.0,
    )
    assert errs == []


def test_accept_missing_requires_reason_code():
    errs = _validate_save_payload(
        {
            "accept_missing_post": True,
            "items": [{"workitem_id": 1, "quantity": 1}],
        },
        current_post=None,
    )
    assert "accepted_missing_post_reason_code_required" in errs


def test_stale_put_returns_409_with_current_version_and_no_overwrite():
    cursor = MagicMock()
    detail = {
        "ok": True,
        "bag": {"day_bag_id": 1},
        "post_weight": {
            "authoritative_post_weight_lbs": 10.0,
            "evidence_post_weight_lbs": 10.0,
            "authoritative_source": POST_SOURCE_WEIGHT_ROLE_POST,
            "scan_event_id": 1,
            "presence_run_id": None,
            "presence_run_row_id": None,
        },
        "workitems": {"lines": [], "resolution": None},
        "review": {"version": 2},
    }
    with patch("backend.daily_operations_wf_review.ensure_wf_review_tables"), patch(
        "backend.daily_operations_wf_review.get_wf_review_detail", return_value=detail
    ), patch(
        "backend.daily_operations_wf_review.get_wf_day_bag_revenue_row",
        return_value={"version": 5, "id": 9},
    ), patch("backend.rinse_bulk_workitems.save_bag_bulk_workitems") as wi:
        out = save_wf_review(
            cursor,
            ORG,
            DAY,
            BAG,
            {
                "version": 2,
                "items": [{"workitem_id": 1, "quantity": 1}],
            },
        )
    assert out["ok"] is False
    assert out["error"] == "conflict"
    assert out["status"] == 409
    assert out["current_version"] == 5
    assert out["current"] is detail
    wi.assert_not_called()
    assert cursor.execute.call_count == 0


def test_routine_wf_review_save_uses_system_audit_reason():
    cursor = MagicMock()
    detail = {
        "ok": True,
        "bag": {"day_bag_id": 1, "bag_id": BAG},
        "post_weight": {
            "authoritative_post_weight_lbs": 10.0,
            "evidence_post_weight_lbs": 10.0,
            "authoritative_source": POST_SOURCE_WEIGHT_ROLE_POST,
            "scan_event_id": 1,
            "presence_run_id": None,
            "presence_run_row_id": None,
        },
        "workitems": {"lines": [], "resolution": None},
        "review": {"version": 1},
    }
    day_out = {
        "kpis": {
            "wf_completed_pounds": 10,
            "wf_weight_revenue": 10,
            "missing_post_weights": 0,
            "outstanding_wf_workitem_reviews": 0,
        },
        "revenue": {"wf_weight_revenue": 10},
        "drilldowns": {"included_wf_bags": []},
    }
    with patch("backend.daily_operations_wf_review.ensure_wf_review_tables"), patch(
        "backend.daily_operations_wf_review.get_wf_review_detail", return_value={**detail, "ok": True}
    ), patch(
        "backend.daily_operations_wf_review.get_wf_day_bag_revenue_row",
        return_value={"version": 1, "id": 3},
    ), patch(
        "backend.rinse_bulk_workitems.save_bag_bulk_workitems",
        return_value={"ok": True, "items_total": 5},
    ) as wi, patch(
        "backend.daily_operations_wf_review.build_daily_operations_day", return_value=day_out
    ), patch(
        "backend.daily_operations_wf_review._recompute_estimated_allocations"
    ), patch("backend.rinse_veewash_step1_api._record_correction"):
        out = save_wf_review(
            cursor,
            ORG,
            DAY,
            BAG,
            {
                "version": 1,
                "items": [{"workitem_id": 1, "quantity": 2}],
            },
        )
    assert out["ok"] is True
    assert wi.call_args.kwargs.get("allow_system_audit_reason") is True
    # Audit insert should include system reason
    audit_calls = [
        c
        for c in cursor.execute.call_args_list
        if c.args and "INSERT INTO wf_day_bag_revenue_audits" in str(c.args[0])
    ]
    assert audit_calls
    assert "WORKITEMS_UPDATED" in str(audit_calls[0].args[1])


def test_edit_bag_classify_routine_vs_exceptional():
    before = {"pre_weight_lbs": 10.0, "post_weight_lbs": 12.0}
    routine = classify_edit_reason_requirements(
        {"bulk_items": [{"workitem_id": 1, "quantity": 1}], "post_weight_lbs": 12.0},
        before,
        outcome=None,
    )
    assert routine["reason_required"] is False
    assert routine["system_action"] == SYSTEM_ACTION_WORKITEMS_UPDATED

    exclude = classify_edit_reason_requirements(
        {"bulk_items": [{"workitem_id": 1, "quantity": 1}]},
        before,
        outcome="exclude",
    )
    assert exclude["reason_required"] is True
    assert exclude["suggested_reason_code"] == "EXCLUDE"

    post = classify_edit_reason_requirements(
        {"post_weight_lbs": 15.0},
        before,
        outcome="keep_review",
    )
    assert post["reason_required"] is True
    assert post["suggested_reason_code"] == "POST_CORRECTION"


def test_edit_bag_resolve_other_requires_note():
    before = {"pre_weight_lbs": 10.0, "post_weight_lbs": 12.0}
    bad = resolve_edit_audit_reason(
        reason=None,
        reason_code="OTHER",
        reason_note=None,
        draft={"post_weight_lbs": 15.0},
        before=before,
        outcome=None,
    )
    assert bad["ok"] is False
    assert bad["error"] == "reason_note_required_for_other"

    ok = resolve_edit_audit_reason(
        reason=None,
        reason_code="POST_CORRECTION",
        reason_note=None,
        draft={"post_weight_lbs": 15.0},
        before=before,
        outcome=None,
    )
    assert ok["ok"] is True
    assert ok["reason"].startswith("POST_CORRECTION")


def test_edit_bag_conflict_includes_current_version_and_skips_writes():
    stale_before = {
        "bag_id": BAG,
        "service_type": "WF",
        "rush_flag": "RUSH",
        "entry_at": None,
        "entry_source": None,
        "rack": None,
        "pre_weight_lbs": 10.0,
        "post_weight_lbs": None,
        "bulk_items": [],
        "no_chargeable": False,
        "no_charge_reason": None,
        "dashboard_status": "pending",
        "outcome": "pending",
        "completion_at": None,
        "completed_by": None,
        "updated_at": "2026-07-22T06:05:00",
    }
    cursor = MagicMock()
    with patch(
        "backend.rinse_step1_edit_bag.capture_bag_edit_state",
        return_value=stale_before,
    ), patch("backend.rinse_step1_edit_bag.ensure_step1_bag_edit_tables"):
        out = apply_unified_bag_edit(
            cursor,
            ORG,
            bag_id=BAG,
            selected_date_et=DAY,
            reason="",
            draft={"bulk_items": [{"workitem_id": 1, "quantity": 1}]},
            expected_updated_at="2026-07-22T06:00:00",
        )
    assert out["ok"] is False
    assert out["error"] == "conflict"
    assert out["status"] == 409
    assert out["current_version"] == "2026-07-22T06:05:00"
    assert out["latest"] is stale_before


def test_edit_bag_routine_save_without_reason_succeeds_system_audit():
    before = {
        "bag_id": BAG,
        "service_type": "WF",
        "rush_flag": "NON-RUSH",
        "entry_at": None,
        "entry_source": None,
        "rack": None,
        "pre_weight_lbs": 10.0,
        "post_weight_lbs": 11.0,
        "bulk_items": [],
        "no_chargeable": False,
        "no_charge_reason": None,
        "dashboard_status": "review_required",
        "outcome": "review_required",
        "completion_at": None,
        "completed_by": None,
        "updated_at": "2026-07-24T10:00:00",
    }
    after = dict(before)
    after["bulk_items"] = [{"workitem_id": 1, "quantity": 2, "name": "Comforter"}]
    cursor = MagicMock()
    cursor.lastrowid = 77
    with patch("backend.rinse_step1_edit_bag.ensure_step1_bag_edit_tables"), patch(
        "backend.rinse_step1_edit_bag.capture_bag_edit_state",
        side_effect=[before, after],
    ), patch(
        "backend.rinse_bulk_workitems.save_bag_bulk_workitems",
        return_value={"ok": True, "items_total": 20},
    ) as wi, patch(
        "backend.rinse_step1_edit_bag._apply_service_rush_update"
    ), patch(
        "backend.rinse_step1_edit_bag._apply_entry_correction"
    ), patch(
        "backend.rinse_step1_edit_bag._apply_weight_update"
    ):
        out = apply_unified_bag_edit(
            cursor,
            ORG,
            bag_id=BAG,
            selected_date_et=DAY,
            reason="",
            draft={
                "service_type": "WF",
                "rush_flag": "NON-RUSH",
                "pre_weight_lbs": 10.0,
                "post_weight_lbs": 11.0,
                "bulk_items": [{"workitem_id": 1, "quantity": 2}],
            },
            expected_updated_at="2026-07-24T10:00:00",
            outcome_action="keep_review",
        )
    assert out["ok"] is True
    assert wi.call_args.kwargs.get("allow_system_audit_reason") is True
    # Parent edit insert reason should be system action
    insert = next(
        c
        for c in cursor.execute.call_args_list
        if c.args and "INSERT INTO rinse_step1_bag_edits" in str(c.args[0])
    )
    assert SYSTEM_ACTION_WORKITEMS_UPDATED in str(insert.args[1])


def test_edit_bag_exclude_without_reason_code_rejected():
    before = {
        "bag_id": BAG,
        "service_type": "WF",
        "rush_flag": "NON-RUSH",
        "pre_weight_lbs": 10.0,
        "post_weight_lbs": 11.0,
        "bulk_items": [],
        "no_chargeable": False,
        "updated_at": "2026-07-24T10:00:00",
    }
    cursor = MagicMock()
    with patch("backend.rinse_step1_edit_bag.ensure_step1_bag_edit_tables"), patch(
        "backend.rinse_step1_edit_bag.capture_bag_edit_state", return_value=before
    ):
        out = apply_unified_bag_edit(
            cursor,
            ORG,
            bag_id=BAG,
            selected_date_et=DAY,
            reason="",
            draft={"bulk_items": [{"workitem_id": 1, "quantity": 1}]},
            expected_updated_at="2026-07-24T10:00:00",
            outcome_action="exclude",
        )
    assert out["ok"] is False
    assert out["error"] == "reason_code_required"
