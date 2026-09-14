"""Review Exclude soft concurrency — material vs harmless lock conflicts."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_step1_edit_bag import (
    OUTCOME_EXCLUDE,
    OUTCOME_MARK_COMPLETED,
    _soft_resolve_review_mutation_conflict,
    apply_unified_bag_edit,
)

ORG = 3
DAY = date(2026, 9, 13)
BAG = "C1PI050KEU"


def test_soft_resolve_exclude_refreshes_lock_when_oi_still_open():
    cursor = MagicMock()
    with patch(
        "backend.rinse_step1_edit_bag._open_wf_order_instances",
        return_value=[{"order_instance_id": 3587, "completed_at": None}],
    ):
        out = _soft_resolve_review_mutation_conflict(
            cursor,
            ORG,
            BAG,
            selected_date_et=DAY,
            outcome=OUTCOME_EXCLUDE,
            before={"manager_edit_version": 2},
            current_version=2,
        )
    assert out.get("refresh_lock") is True
    assert out["current_version"] == 2


def test_soft_resolve_exclude_idempotent_when_no_open_oi():
    cursor = MagicMock()
    with patch(
        "backend.rinse_step1_edit_bag._open_wf_order_instances",
        return_value=[],
    ), patch(
        "backend.rinse_step1_edit_bag.capture_bag_edit_state",
        return_value={"bag_id": BAG, "dashboard_status": "excluded"},
    ):
        out = _soft_resolve_review_mutation_conflict(
            cursor,
            ORG,
            BAG,
            selected_date_et=DAY,
            outcome=OUTCOME_EXCLUDE,
            before={"manager_edit_version": 0},
            current_version=0,
        )
    assert out["ok"] is True
    assert out.get("already_excluded") is True


def test_soft_resolve_complete_rejects_when_already_completed():
    cursor = MagicMock()
    with patch(
        "backend.rinse_step1_edit_bag._open_wf_order_instances",
        return_value=[],
    ):
        out = _soft_resolve_review_mutation_conflict(
            cursor,
            ORG,
            BAG,
            selected_date_et=DAY,
            outcome=OUTCOME_MARK_COMPLETED,
            before={"dashboard_status": "completed"},
            current_version=1,
        )
    assert out["ok"] is False
    assert out["error"] == "order_completed_while_reviewing"


def test_soft_resolve_exclude_dfp_cleared_returns_no_longer_in_review():
    cursor = MagicMock()
    with patch(
        "backend.rinse_step1_edit_bag._open_wf_order_instances",
        return_value=[{"order_instance_id": 1, "completed_at": None}],
    ):
        out = _soft_resolve_review_mutation_conflict(
            cursor,
            ORG,
            BAG,
            selected_date_et=DAY,
            outcome=OUTCOME_EXCLUDE,
            before={
                "updated_at": "2026-09-13T12:00:00",
                "effective_status": "pending",
                "review_reason_codes": [],
            },
            current_version=4,
        )
    assert out["ok"] is False
    assert out["error"] == "no_longer_in_review"


def test_soft_resolve_complete_true_conflict_when_completion_fields_changed():
    cursor = MagicMock()
    with patch(
        "backend.rinse_step1_edit_bag._open_wf_order_instances",
        return_value=[{"order_instance_id": 1, "completed_at": None}],
    ):
        out = _soft_resolve_review_mutation_conflict(
            cursor,
            ORG,
            BAG,
            selected_date_et=DAY,
            outcome=OUTCOME_MARK_COMPLETED,
            before={
                "completed_by": "Alice",
                "completion_at": "2026-09-13T10:00:00",
                "post_weight_lbs": 10.0,
            },
            current_version=5,
            draft={
                "completed_by": "Bob",
                "completion_at": "2026-09-13T10:00:00",
                "post_weight_lbs": 10.0,
            },
        )
    assert out["ok"] is False
    assert out["error"] == "conflict"


def test_soft_resolve_complete_refreshes_when_filling_empty_completion():
    cursor = MagicMock()
    with patch(
        "backend.rinse_step1_edit_bag._open_wf_order_instances",
        return_value=[{"order_instance_id": 1, "completed_at": None}],
    ):
        out = _soft_resolve_review_mutation_conflict(
            cursor,
            ORG,
            BAG,
            selected_date_et=DAY,
            outcome=OUTCOME_MARK_COMPLETED,
            before={
                "completed_by": None,
                "completion_at": None,
                "post_weight_lbs": None,
            },
            current_version=5,
            draft={
                "completed_by": "Bob",
                "completion_at": "2026-09-13T10:00:00",
                "post_weight_lbs": 12.0,
            },
        )
    assert out.get("refresh_lock") is True


def test_exclude_without_day_bag_does_not_false_conflict():
    """Regression: DFP open OI with no selected-date day_bag used to 409 conflict."""
    cursor = MagicMock()
    before = {
        "bag_id": BAG,
        "manager_edit_version": 0,
        "updated_at": None,
        "dashboard_status": None,
        "service_type": "WF",
        "rush_flag": "NON-RUSH",
        "bulk_items": [],
        "pre_weight_lbs": None,
        "post_weight_lbs": None,
        "completed_by": None,
        "completion_at": None,
        "no_chargeable": False,
        "no_charge_reason": None,
    }

    def _capture(*_a, **_k):
        return dict(before)

    with patch(
        "backend.rinse_step1_edit_bag.ensure_step1_bag_edit_tables"
    ), patch(
        "backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"
    ), patch(
        "backend.rinse_step1_edit_bag.capture_bag_edit_state",
        side_effect=_capture,
    ), patch(
        "backend.rinse_step1_edit_bag.validate_edit_draft",
        return_value=[],
    ), patch(
        "backend.rinse_wf_disappeared_from_portal.apply_manager_exclude_to_open_wf_lifecycle",
        return_value={"ois_closed": 1, "cycle_resolved": True},
    ), patch(
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
    ):
        cursor.lastrowid = 99
        cursor.rowcount = 0  # day_bag version bump hits nothing
        out = apply_unified_bag_edit(
            cursor,
            ORG,
            bag_id=BAG,
            selected_date_et=DAY,
            reason="Disappeared From Portal — manager exclude",
            draft={"service_type": "WF", "rush_flag": "NON-RUSH"},
            expected_manager_edit_version=0,
            outcome_action="exclude",
            reason_code="EXTRA_OR_DUPLICATE_BAG",
            reason_note="Disappeared From Portal — manager exclude",
            actor_display_name="mgr",
        )
    assert out["ok"] is True, out
    # Must not have returned conflict from 0-row version bump.
    assert out.get("error") != "conflict"
    # Audit insert still attempted.
    assert any(
        "INSERT INTO rinse_step1_bag_edits" in str(c.args[0])
        for c in cursor.execute.call_args_list
        if c.args
    )


def test_exclude_stale_version_refreshes_instead_of_hard_conflict():
    cursor = MagicMock()
    before = {
        "bag_id": BAG,
        "manager_edit_version": 3,
        "updated_at": "2026-09-13T12:00:00",
        "dashboard_status": "review_required",
        "service_type": "WF",
        "rush_flag": "NON-RUSH",
        "bulk_items": [],
        "pre_weight_lbs": 10.0,
        "post_weight_lbs": 9.0,
        "completed_by": None,
        "completion_at": None,
        "no_chargeable": False,
        "no_charge_reason": None,
        "review_reason_codes": ["DISAPPEARED_FROM_PORTAL"],
    }

    with patch(
        "backend.rinse_step1_edit_bag.ensure_step1_bag_edit_tables"
    ), patch(
        "backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"
    ), patch(
        "backend.rinse_step1_edit_bag.capture_bag_edit_state",
        return_value=dict(before),
    ), patch(
        "backend.rinse_step1_edit_bag._open_wf_order_instances",
        return_value=[{"order_instance_id": 1, "completed_at": None}],
    ), patch(
        "backend.rinse_step1_edit_bag.validate_edit_draft",
        return_value=[],
    ), patch(
        "backend.rinse_wf_disappeared_from_portal.apply_manager_exclude_to_open_wf_lifecycle",
        return_value={"ois_closed": 1},
    ), patch(
        "backend.rinse_veewash_step1_api._record_correction"
    ), patch(
        "backend.rinse_veewash_shift_day.apply_manager_edit_day_bag_patch",
        return_value={"ok": True},
    ), patch(
        "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
        return_value=[{"effective_status": "review_required", "review_reason_codes": []}],
    ), patch(
        "backend.rinse_bulk_workitems.bag_bulk_review_cleared",
        return_value=True,
    ):
        # First version bump succeeds after soft refresh uses current_version=3.
        cursor.rowcount = 1
        cursor.lastrowid = 42
        out = apply_unified_bag_edit(
            cursor,
            ORG,
            bag_id=BAG,
            selected_date_et=DAY,
            reason="exclude",
            draft={"service_type": "WF"},
            expected_manager_edit_version=0,  # stale drawer token
            outcome_action="exclude",
            reason_code="EXTRA_OR_DUPLICATE_BAG",
            reason_note="exclude",
        )
    assert out["ok"] is True, out


def test_exclude_ignores_harmless_cache_generation_token_drift():
    """Review cache generation / scrape metadata must not block Exclude."""
    cursor = MagicMock()
    before = {
        "bag_id": BAG,
        "manager_edit_version": 7,
        "updated_at": "2026-09-13T12:00:00",
        "dashboard_status": "review_required",
        "effective_status": "review_required",
        "service_type": "WF",
        "rush_flag": "NON-RUSH",
        "bulk_items": [],
        "pre_weight_lbs": 36.2,
        "post_weight_lbs": 35.8,
        "completed_by": None,
        "completion_at": None,
        "no_chargeable": False,
        "review_reason_codes": ["DISAPPEARED_FROM_PORTAL"],
        "review_cache_generation": 99,
        "last_seen_at": "2026-09-13T11:00:00",
    }
    with patch(
        "backend.rinse_step1_edit_bag.ensure_step1_bag_edit_tables"
    ), patch(
        "backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"
    ), patch(
        "backend.rinse_step1_edit_bag.capture_bag_edit_state",
        return_value=dict(before),
    ), patch(
        "backend.rinse_step1_edit_bag._open_wf_order_instances",
        return_value=[{"order_instance_id": 3587, "completed_at": None}],
    ), patch(
        "backend.rinse_step1_edit_bag.validate_edit_draft",
        return_value=[],
    ), patch(
        "backend.rinse_wf_disappeared_from_portal.apply_manager_exclude_to_open_wf_lifecycle",
        return_value={"ois_closed": 1},
    ) as exclude_fn, patch(
        "backend.rinse_veewash_step1_api._record_correction"
    ), patch(
        "backend.rinse_veewash_shift_day.apply_manager_edit_day_bag_patch",
        return_value={"ok": True},
    ), patch(
        "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
        return_value=[dict(before)],
    ), patch(
        "backend.rinse_bulk_workitems.bag_bulk_review_cleared",
        return_value=True,
    ):
        cursor.rowcount = 1
        cursor.lastrowid = 7
        out = apply_unified_bag_edit(
            cursor,
            ORG,
            bag_id=BAG,
            selected_date_et=DAY,
            reason="exclude",
            draft={"service_type": "WF"},
            expected_manager_edit_version=1,  # stale vs current 7
            outcome_action="exclude",
            reason_code="EXTRA_OR_DUPLICATE_BAG",
            reason_note="exclude",
        )
    assert out["ok"] is True, out
    exclude_fn.assert_called_once()
    assert any(
        "INSERT INTO rinse_step1_bag_edits" in str(c.args[0])
        for c in cursor.execute.call_args_list
        if c.args
    )


def test_exclude_does_not_rebuild_full_review_membership_in_mutation():
    """Synchronous Exclude must stay a small mutation (no full DFP/membership rebuild)."""
    cursor = MagicMock()
    before = {
        "bag_id": BAG,
        "manager_edit_version": 0,
        "updated_at": None,
        "dashboard_status": None,
        "service_type": "WF",
        "rush_flag": "NON-RUSH",
        "bulk_items": [],
        "pre_weight_lbs": None,
        "post_weight_lbs": None,
        "completed_by": None,
        "completion_at": None,
        "no_chargeable": False,
    }
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
        "backend.rinse_wf_disappeared_from_portal.apply_manager_exclude_to_open_wf_lifecycle",
        return_value={"ois_closed": 1},
    ), patch(
        "backend.rinse_veewash_step1_api._record_correction"
    ), patch(
        "backend.rinse_veewash_shift_day.apply_manager_edit_day_bag_patch",
        return_value={"ok": True, "skipped": "no_day_bag"},
    ) as patch_day, patch(
        "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
        return_value=[],
    ), patch(
        "backend.rinse_bulk_workitems.bag_bulk_review_cleared",
        return_value=True,
    ), patch(
        "backend.rinse_wf_disappeared_from_portal.qualify_disappeared_from_portal_bags",
    ) as full_dfp, patch(
        "backend.management_rinse_wf_review.enrich_review_counts_by_rush",
    ) as rebuild:
        cursor.rowcount = 0
        cursor.lastrowid = 1
        out = apply_unified_bag_edit(
            cursor,
            ORG,
            bag_id=BAG,
            selected_date_et=DAY,
            reason="exclude",
            draft={"service_type": "WF"},
            expected_manager_edit_version=0,
            outcome_action="exclude",
            reason_code="EXTRA_OR_DUPLICATE_BAG",
            reason_note="exclude",
        )
    assert out["ok"] is True, out
    full_dfp.assert_not_called()
    rebuild.assert_not_called()
    patch_day.assert_called_once()
