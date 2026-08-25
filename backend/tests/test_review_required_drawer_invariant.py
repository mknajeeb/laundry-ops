"""Review Required headline must equal union of actionable Review drawer IDs."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from backend.management_rinse_wf_review import (
    CATEGORY_MANUAL_REVIEW,
    CATEGORY_MISSING_PORTAL,
    CATEGORY_SPECIALTY,
    CATEGORY_SPLIT_ORDER,
    build_management_review_list,
    compute_canonical_wf_review_membership,
    review_category_count_payload,
)
from backend.rinse_veewash_workload import (
    OUTCOME_COMPLETED,
    OUTCOME_REVIEW_REQUIRED,
    REASON_DISAPPEARED_WITHOUT_COMPLETION,
)
from backend.rinse_wf_service_cycle import REVIEW_MISSING_FROM_PORTAL

ORG = 3
DAY = date(2026, 8, 24)
BAG = "7A930TJ7W8"


def _completed_send_back_row():
    return {
        "bag_id": BAG,
        "effective_status": "review_required",
        "review_reason_codes": [
            REASON_DISAPPEARED_WITHOUT_COMPLETION,
            REVIEW_MISSING_FROM_PORTAL,
        ],
        "canonical_completion_status": "completed",
        "canonical_completion_timestamp": "2026-08-24 16:45:00",
        "canonical_completion_employee": "Folder One",
        "post_weight_lbs": "10.8000",
        "disposition": "COMPLETED",
        "service_type": "WF",
        "rush_status": "NON_RUSH",
        "bag_snapshot": {
            "keep_completed_while_in_review": True,
            "manual_review": {
                "active": False,
                "sent_back_at": "2026-08-24T21:52:11-04:00",
                "prior_reason_codes": [
                    REASON_DISAPPEARED_WITHOUT_COMPLETION,
                    REVIEW_MISSING_FROM_PORTAL,
                ],
            },
        },
        "manager_edit_version": 2,
    }


def _headline_with_review_bag():
    return {
        "segments": {
            "wf": {
                "completed": 112,
                "pending": 0,
                "total_workload": 113,
                "active_workload": 113,
                "exceptions": {"review_required": 1, "total": 1},
                "bag_ids": {
                    "completed": [],
                    "pending": [],
                    "review_required": [BAG],
                    "new_today": [BAG],
                    "carryover": [],
                },
            }
        },
        "review_reasons_by_bag": {
            BAG: [
                REASON_DISAPPEARED_WITHOUT_COMPLETION,
                REVIEW_MISSING_FROM_PORTAL,
            ]
        },
        "review_by_reason": {},
    }


@pytest.mark.integration_membership
def test_send_back_completed_bag_lands_in_manual_review_drawer():
    headline = _headline_with_review_bag()
    row = _completed_send_back_row()

    with (
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags",
            return_value=[row],
        ),
        patch(
            "backend.rinse_veewash_shift_day.get_day_record",
            return_value={"headline": headline, "status": "OPEN"},
        ),
        patch(
            "backend.rinse_veewash_shift_day.summary_from_day_record",
            return_value=headline,
        ),
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[row],
        ),
        patch(
            "backend.management_rinse_wf_review._canonical_review_weights",
            return_value={BAG: {"post_weight_lbs": 10.8, "post_weight_event_exists": True}},
        ),
        patch(
            "backend.management_rinse_wf_review._split_eval_as_of_day",
            return_value={},
        ),
        patch(
            "backend.management_rinse_wf_review.resolve_customer_names_for_bags",
            side_effect=lambda _c, _o, rs, **kwargs: rs,
        ),
    ):
        membership = compute_canonical_wf_review_membership(
            MagicMock(), ORG, DAY, headline=headline
        )
        counts = review_category_count_payload(
            headline, cursor=MagicMock(), organization_id=ORG, selected_date_et=DAY
        )
        all_drawer = build_management_review_list(
            MagicMock(), ORG, DAY, category="review_required"
        )
        manual_drawer = build_management_review_list(
            MagicMock(), ORG, DAY, category=CATEGORY_MANUAL_REVIEW
        )

    assert BAG in membership[CATEGORY_MANUAL_REVIEW]
    assert BAG not in membership[CATEGORY_MISSING_PORTAL]
    assert BAG not in membership[CATEGORY_SPECIALTY]
    assert counts["review_required"] == 1
    assert counts["manual_review"] == 1
    assert counts["missing_from_portal"] == 0

    union_ids = {b["bag_id"] for b in all_drawer.get("bags") or []}
    assert union_ids == {BAG}
    assert [b["bag_id"] for b in manual_drawer.get("bags") or []] == [BAG]


@pytest.mark.integration_membership
def test_headline_review_ids_equal_drawer_union():
    headline = _headline_with_review_bag()
    row = _completed_send_back_row()
    headline_ids = set(headline["segments"]["wf"]["bag_ids"]["review_required"])

    with (
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags",
            return_value=[row],
        ),
        patch(
            "backend.rinse_veewash_shift_day.get_day_record",
            return_value={"headline": headline},
        ),
        patch(
            "backend.rinse_veewash_shift_day.summary_from_day_record",
            return_value=headline,
        ),
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[row],
        ),
        patch(
            "backend.management_rinse_wf_review._canonical_review_weights",
            return_value={BAG: {"post_weight_lbs": 10.8, "post_weight_event_exists": True}},
        ),
        patch(
            "backend.management_rinse_wf_review._split_eval_as_of_day",
            return_value={},
        ),
        patch(
            "backend.management_rinse_wf_review.resolve_customer_names_for_bags",
            side_effect=lambda _c, _o, rs, **kwargs: rs,
        ),
    ):
        drawers = [
            build_management_review_list(MagicMock(), ORG, DAY, category=cat)
            for cat in (
                CATEGORY_SPECIALTY,
                CATEGORY_MISSING_PORTAL,
                CATEGORY_SPLIT_ORDER,
                CATEGORY_MANUAL_REVIEW,
            )
        ]

    union = {b["bag_id"] for d in drawers for b in d.get("bags") or []}
    assert headline_ids == union == {BAG}


def test_resolve_manual_review_removes_from_membership():
    headline = _headline_with_review_bag()
    row = _completed_send_back_row()
    resolved_row = dict(row)
    resolved_row["effective_status"] = OUTCOME_COMPLETED
    resolved_row["review_reason_codes"] = []
    resolved_headline = dict(headline)
    resolved_headline["segments"] = {
        "wf": {
            **headline["segments"]["wf"],
            "exceptions": {"review_required": 0, "total": 0},
            "bag_ids": {
                **headline["segments"]["wf"]["bag_ids"],
                "review_required": [],
                "completed": [BAG],
            },
        }
    }

    with patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=[row]):
        membership_before = compute_canonical_wf_review_membership(
            MagicMock(), ORG, DAY, headline=headline
        )
    with patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=[resolved_row]):
        membership_after = compute_canonical_wf_review_membership(
            MagicMock(), ORG, DAY, headline=resolved_headline
        )

    assert BAG in membership_before[CATEGORY_MANUAL_REVIEW]
    assert BAG not in membership_after.get(CATEGORY_MANUAL_REVIEW, [])
    assert BAG not in membership_after.get(CATEGORY_SPECIALTY, [])
    assert membership_after["counts"]["review_required"] == 0
