"""Manual Review override retirement on Complete + defensive membership merge."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_step1_edit_bag import apply_unified_bag_edit


ORG = 3
DAY = date(2026, 9, 13)
BAG = "A78ADJBT8M"


def test_mark_completed_clears_manual_review_override():
    before = {
        "bag_id": BAG,
        "manager_edit_version": 0,
        "updated_at": None,
        "dashboard_status": None,
        "service_type": "WF",
        "rush_flag": "NON-RUSH",
        "bulk_items": [],
        "pre_weight_lbs": 10.0,
        "post_weight_lbs": 9.0,
        "completed_by": None,
        "completion_at": None,
        "no_chargeable": False,
    }
    cursor = MagicMock()
    cursor.rowcount = 0
    cursor.lastrowid = 11
    with patch(
        "backend.rinse_step1_edit_bag.ensure_step1_bag_edit_tables"
    ), patch(
        "backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"
    ), patch(
        "backend.rinse_step1_edit_bag.capture_bag_edit_state",
        return_value=dict(before),
    ), patch(
        "backend.rinse_step1_edit_bag.validate_edit_draft",
        return_value=[],
    ), patch(
        "backend.rinse_operator_manual_correction.apply_operator_approved_manual_completion",
        return_value={"ok": True},
    ), patch(
        "backend.rinse_wf_service_cycle.apply_manager_review_resolution_to_canonical_cycle"
    ), patch(
        "backend.management_wf_cw_controls.clear_cw_override",
        return_value={"ok": True, "cleared": True},
    ) as clear_ov, patch(
        "backend.rinse_veewash_step1_api._record_correction"
    ), patch(
        "backend.rinse_veewash_shift_day.apply_manager_edit_day_bag_patch",
        return_value={"ok": True, "skipped": "no_day_bag"},
    ), patch(
        "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
        return_value=[],
    ), patch(
        "backend.rinse_bulk_workitems.bag_bulk_review_cleared",
        return_value=True,
    ), patch(
        "backend.rinse_bulk_workitems.load_bulk_workitem_scan_map",
        return_value={},
    ):
        out = apply_unified_bag_edit(
            cursor,
            ORG,
            bag_id=BAG,
            selected_date_et=DAY,
            reason="complete",
            draft={
                "service_type": "WF",
                "completed_by": "Mgr",
                "completion_at": "2026-09-13T12:00:00",
                "post_weight_lbs": 9.0,
            },
            expected_manager_edit_version=0,
            outcome_action="mark_completed",
            reason_code="MARK_COMPLETED",
            reason_note="complete",
            actor_display_name="Mgr",
        )
    assert out["ok"] is True, out
    clear_ov.assert_called_once()
    kwargs = clear_ov.call_args.kwargs
    assert kwargs.get("bag_id") == BAG
    assert "manual_review" in (kwargs.get("only_types") or [])
