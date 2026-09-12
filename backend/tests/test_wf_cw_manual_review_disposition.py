"""WF Pending → Manual Review soft disposition (no lifecycle mutation)."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.management_rinse_wf_review import (
    CATEGORY_MANUAL_REVIEW,
    CATEGORY_MISSING_PORTAL,
    CATEGORY_SPECIALTY,
    MANUAL_REVIEW_REASONS,
    SPECIALTY_ITEMS_REASONS,
    build_management_review_action,
    category_for_reason_codes,
    merge_cw_manual_overrides_into_review_membership,
)
from backend.management_wf_cw_controls import (
    OVERRIDE_MANUAL_REVIEW,
    apply_cw_manager_overlay,
    resolve_manual_cw_review,
)
from backend.rinse_veewash_workload import (
    OUTCOME_PENDING,
    OUTCOME_REVIEW_REQUIRED,
    REASON_DISAPPEARED_FROM_PORTAL,
    REASON_MANAGER_SENT_FOR_REVIEW,
)

ORG = 3
DAY = date(2026, 9, 12)


def test_manager_sent_not_in_specialty_reasons():
    assert REASON_MANAGER_SENT_FOR_REVIEW not in SPECIALTY_ITEMS_REASONS
    assert REASON_MANAGER_SENT_FOR_REVIEW in MANUAL_REVIEW_REASONS
    assert category_for_reason_codes([REASON_MANAGER_SENT_FOR_REVIEW]) == CATEGORY_MANUAL_REVIEW
    assert category_for_reason_codes(["WF_BULK_WORKITEM_REVIEW"]) == CATEGORY_SPECIALTY


def test_category_manual_after_specialty_and_split():
    assert (
        category_for_reason_codes(
            [REASON_MANAGER_SENT_FOR_REVIEW, "WF_ZERO_OR_MISSING_POST_WEIGHT"]
        )
        == CATEGORY_SPECIALTY
    )
    assert (
        category_for_reason_codes(
            [REASON_MANAGER_SENT_FOR_REVIEW, "MULTIPLE_WASHERS_WITHOUT_SPLIT_MARKER"]
        )
        == "split_order_review"
    )
    assert (
        category_for_reason_codes(
            [REASON_DISAPPEARED_FROM_PORTAL, REASON_MANAGER_SENT_FOR_REVIEW]
        )
        == CATEGORY_MISSING_PORTAL
    )


def test_apply_overlay_send_to_review_creates_manual():
    wl = {
        "pending": frozenset({"BAG1"}),
        "review": frozenset(),
        "open": frozenset({"BAG1"}),
        "counts": {"pending": 1, "review": 0, "open": 1},
        "items": [
            {
                "bag_id": "BAG1",
                "status": OUTCOME_PENDING,
                "review_reason_codes": [],
                "customer_name": "Pat",
            }
        ],
    }
    overrides = {
        "BAG1": {
            "bag_id": "BAG1",
            "override_type": OVERRIDE_MANUAL_REVIEW,
            "active": True,
            "reason_code": REASON_MANAGER_SENT_FOR_REVIEW,
            "reason_text": "Need manager look",
            "actor_display_name": "Jen",
            "created_at_et": datetime(2026, 9, 12, 12, 0),
        }
    }
    out = apply_cw_manager_overlay(wl, overrides)
    assert "BAG1" in out["review"]
    assert "BAG1" not in out["pending"]
    item = out["items"][0]
    assert item["status"] == OUTCOME_REVIEW_REQUIRED
    assert item["review_origin"] == "manual"
    assert REASON_MANAGER_SENT_FOR_REVIEW in item["review_reason_codes"]
    assert item["manual_review_reason"] == "Need manager look"


def test_merge_cw_manual_overrides_into_membership():
    membership = {
        CATEGORY_SPECIALTY: ["SPECBAG"],
        CATEGORY_MISSING_PORTAL: [],
        "split_order_review": [],
        CATEGORY_MANUAL_REVIEW: [],
        "unknown_review": [],
        "counts": {},
        "disposition": {"SPECBAG": CATEGORY_SPECIALTY},
        "codes_by_bag": {"SPECBAG": ["WF_BULK_WORKITEM_REVIEW"]},
        "reason_category_map": {},
        "precedence": "",
        "employee_performance_hint": {},
    }
    with patch(
        "backend.management_wf_cw_controls.bulk_load_active_cw_overrides",
        return_value={
            "MANBAG01": {
                "bag_id": "MANBAG01",
                "override_type": OVERRIDE_MANUAL_REVIEW,
                "active": True,
                "reason_text": "Check bag",
                "reason_code": REASON_MANAGER_SENT_FOR_REVIEW,
            },
            "SPECBAG": {
                "bag_id": "SPECBAG",
                "override_type": OVERRIDE_MANUAL_REVIEW,
                "active": True,
                "reason_text": "Also manual",
            },
        },
    ):
        out = merge_cw_manual_overrides_into_review_membership(
            MagicMock(), ORG, membership
        )
    assert "MANBAG01" in out[CATEGORY_MANUAL_REVIEW]
    assert "SPECBAG" not in out[CATEGORY_MANUAL_REVIEW]
    assert out["disposition"]["MANBAG01"] == CATEGORY_MANUAL_REVIEW
    assert REASON_MANAGER_SENT_FOR_REVIEW in out["codes_by_bag"]["MANBAG01"]
    assert "SPECBAG" in out["_cw_override_meta"]


def test_action_preserves_dfp_when_day_bag_codes_empty():
    row = {
        "bag_id": "DFPBAG01",
        "effective_status": "review_required",
        "review_reason_codes": [],
        "bag_snapshot": {"customer_name": "Ada", "reason_codes": []},
        "manager_edit_version": 0,
    }
    membership = {
        "codes_by_bag": {"DFPBAG01": [REASON_DISAPPEARED_FROM_PORTAL]},
        "_cw_override_meta": {},
        "disposition": {"DFPBAG01": CATEGORY_MISSING_PORTAL},
    }
    with (
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[row],
        ),
        patch(
            "backend.management_wf_review_cache.get_canonical_wf_review_membership_cached",
            return_value=membership,
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bag_bulk_lines",
            return_value={},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bulk_resolutions",
            return_value={},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bulk_workitem_scan_map",
            return_value={},
        ),
        patch(
            "backend.management_rinse_wf_review._canonical_review_weights",
            return_value={},
        ),
        patch(
            "backend.management_rinse_wf_review.resolve_customer_names_for_bags",
            side_effect=lambda *_a, **_k: [{"bag_id": "DFPBAG01", "customer_name": "Ada"}],
        ),
        patch(
            "backend.management_rinse_wf_review._single_bag_dfp_qualified",
            return_value=True,
        ),
    ):
        out = build_management_review_action(MagicMock(), ORG, DAY, "DFPBAG01")
    assert out["ok"] is True
    bag = out["bag"]
    assert REASON_DISAPPEARED_FROM_PORTAL in bag["reason_codes"]
    assert bag["category"] == CATEGORY_MISSING_PORTAL
    assert bag["has_missing_portal"] is True
    assert "return_pending" not in bag["allowed_actions"]
    assert "complete" in bag["allowed_actions"]


def test_action_uses_cw_override_when_day_bag_empty():
    row = {
        "bag_id": "MANBAG02",
        "effective_status": "pending",
        "review_reason_codes": [],
        "bag_snapshot": {},
        "manager_edit_version": 1,
    }
    with (
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[row],
        ),
        patch(
            "backend.management_wf_review_cache.get_canonical_wf_review_membership_cached",
            return_value={"codes_by_bag": {}, "_cw_override_meta": {}},
        ),
        patch(
            "backend.management_wf_cw_controls.bulk_load_active_cw_overrides",
            return_value={
                "MANBAG02": {
                    "bag_id": "MANBAG02",
                    "override_type": OVERRIDE_MANUAL_REVIEW,
                    "active": True,
                    "reason_text": "Manager note here",
                    "reason_code": REASON_MANAGER_SENT_FOR_REVIEW,
                    "actor_display_name": "Jen",
                }
            },
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bag_bulk_lines",
            return_value={},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bulk_resolutions",
            return_value={},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bulk_workitem_scan_map",
            return_value={},
        ),
        patch(
            "backend.management_rinse_wf_review._canonical_review_weights",
            return_value={},
        ),
        patch(
            "backend.management_rinse_wf_review.resolve_customer_names_for_bags",
            side_effect=lambda *_a, **_k: [{"bag_id": "MANBAG02", "customer_name": None}],
        ),
        patch(
            "backend.management_rinse_wf_review._single_bag_dfp_qualified",
            return_value=False,
        ),
    ):
        out = build_management_review_action(MagicMock(), ORG, DAY, "MANBAG02")
    bag = out["bag"]
    assert bag["category"] == CATEGORY_MANUAL_REVIEW
    assert bag["manual_review_reason"] == "Manager note here"
    assert "return_pending" in bag["allowed_actions"]
    assert REASON_MANAGER_SENT_FOR_REVIEW in bag["reason_codes"]


def test_return_pending_clears_manual_only():
    cursor = MagicMock()
    with (
        patch(
            "backend.management_wf_cw_controls.bulk_load_active_cw_overrides",
            return_value={
                "MANBAG03": {
                    "bag_id": "MANBAG03",
                    "override_type": OVERRIDE_MANUAL_REVIEW,
                    "active": True,
                    "reason_text": "x",
                }
            },
        ),
        patch(
            "backend.management_rinse_wf_review._single_bag_dfp_qualified",
            return_value=False,
        ),
        patch(
            "backend.management_wf_cw_controls.clear_cw_override",
            return_value={"ok": True, "bag_id": "MANBAG03", "cleared": True},
        ) as clear_mock,
        patch("backend.rinse_veewash_step1_api._record_correction"),
        patch(
            "backend.rinse_veewash_step1_api._clear_management_today_after_specialty_mutation"
        ),
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[],
        ),
    ):
        out = resolve_manual_cw_review(
            cursor, ORG, bag_id="MANBAG03", selected_date_et=DAY
        )
    assert out["ok"] is True
    assert out["action"] == "resolve_manual_review"
    clear_mock.assert_called_once()
    kwargs = clear_mock.call_args.kwargs
    assert kwargs.get("only_types") == [OVERRIDE_MANUAL_REVIEW]


def test_dfp_still_qualifies_blocks_return_pending():
    cursor = MagicMock()
    with (
        patch(
            "backend.management_wf_cw_controls.bulk_load_active_cw_overrides",
            return_value={
                "DFPBAG02": {
                    "bag_id": "DFPBAG02",
                    "override_type": OVERRIDE_MANUAL_REVIEW,
                    "active": True,
                    "reason_text": "x",
                }
            },
        ),
        patch(
            "backend.management_rinse_wf_review._single_bag_dfp_qualified",
            return_value=True,
        ),
        patch("backend.management_wf_cw_controls.clear_cw_override") as clear_mock,
    ):
        out = resolve_manual_cw_review(
            cursor, ORG, bag_id="DFPBAG02", selected_date_et=DAY
        )
    assert out["ok"] is False
    assert out["error"] == "still_disappeared_from_portal"
    clear_mock.assert_not_called()
