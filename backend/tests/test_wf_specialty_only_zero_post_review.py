"""Regression: specialty-only WF orders may legitimately complete with POST=0."""

from __future__ import annotations

from datetime import date, datetime

from backend.management_rinse_wf_review import (
    REASON_SERVICE_CLASSIFICATION_MISMATCH,
    specialty_review_is_resolved,
    specialty_review_is_unresolved,
    strip_specialty_only_resolved_reasons,
    wf_specialty_only_zero_post_valid,
)
from backend.rinse_veewash_review import expand_review_required
from backend.rinse_veewash_workload import (
    REASON_WF_BULK_WORKITEM_REVIEW,
    REASON_WF_ZERO_OR_MISSING_POST_WEIGHT,
)


def _bulk_lines(*, comforter: int = 0, bath_mat: int = 0):
    lines = []
    if comforter:
        lines.append(
            {
                "workitem_id": 2,
                "workitem_name": "Comforter",
                "unit_price": 15.0,
                "quantity": comforter,
                "line_total": 15.0 * comforter,
            }
        )
    if bath_mat:
        lines.append(
            {
                "workitem_id": 1,
                "workitem_name": "Bath Mat",
                "unit_price": 4.0,
                "quantity": bath_mat,
                "line_total": 4.0 * bath_mat,
            }
        )
    return lines


def _bulk_res():
    return {"resolution_type": "items", "items_total": 45.0}


def test_normal_wf_post_zero_without_specialty_is_not_valid():
    assert wf_specialty_only_zero_post_valid(
        bulk_lines=[],
        bulk_resolution=None,
        post_weight_lbs=0.0,
    ) is False


def test_comforter_only_post_zero_is_valid_when_bulk_cleared():
    assert wf_specialty_only_zero_post_valid(
        bulk_lines=_bulk_lines(comforter=3),
        bulk_resolution=_bulk_res(),
        post_weight_lbs=0.0,
    )


def test_bath_mat_only_post_zero_is_valid():
    assert wf_specialty_only_zero_post_valid(
        bulk_lines=_bulk_lines(bath_mat=2),
        bulk_resolution={"resolution_type": "items", "items_total": 8.0},
        post_weight_lbs=0.0,
    )


def test_specialty_unresolved_without_bulk_explanation():
    assert specialty_review_is_unresolved(
        [REASON_WF_ZERO_OR_MISSING_POST_WEIGHT],
        bulk_cleared=False,
        bulk_lines=[],
        post_weight_lbs=0.0,
    )


def test_service_classification_mismatch_clears_when_specialty_only_zero_post():
    assert specialty_review_is_resolved(
        [REASON_SERVICE_CLASSIFICATION_MISMATCH],
        bulk_cleared=True,
        bulk_lines=_bulk_lines(comforter=3),
        bulk_resolution=_bulk_res(),
        post_weight_lbs=0.0,
    )


def test_strip_reasons_preserves_zero_post_numeric():
    codes = strip_specialty_only_resolved_reasons(
        [REASON_SERVICE_CLASSIFICATION_MISMATCH, REASON_WF_BULK_WORKITEM_REVIEW],
        bulk_lines=_bulk_lines(comforter=3),
        bulk_resolution=_bulk_res(),
        post_weight_lbs=0.0,
        bulk_cleared=True,
    )
    assert codes == []


def test_expand_review_drops_specialty_only_zero_post_bag():
    bag = "SPECX01"
    raw = {
        "new_today": [bag],
        "carryover": [],
        "completed_on_date": [bag],
        "pending_end_of_date": [],
        "review_required": [bag],
        "rows": [
            {
                "bag_id": bag,
                "service_type": "WF",
                "outcome": "review_required",
                "completion_at": datetime(2026, 8, 25, 13, 5),
                "completion_date": date(2026, 8, 25),
            }
        ],
        "review_reasons_by_bag": {bag: [REASON_SERVICE_CLASSIFICATION_MISMATCH]},
    }
    out = expand_review_required(
        raw,
        selected_date_et=date(2026, 8, 25),
        presence_by_bag={bag: {"service_type": "WF", "active": 0}},
        entry_by_bag={bag: {"entry_date": date(2026, 8, 25)}},
        weight_by_bag={
            bag: {
                "pre_weight_lbs": 12.3,
                "post_weight_lbs": 0.0,
                "post_weight_event_exists": True,
                "post_weight_value": 0.0,
                "weight_entry_count": 2,
            }
        },
        bulk_lines_by_bag={bag: _bulk_lines(comforter=3)},
        bulk_resolution_by_bag={bag: _bulk_res()},
    )
    assert bag not in (out.get("review_required") or [])
    assert REASON_SERVICE_CLASSIFICATION_MISMATCH not in (
        out.get("review_reasons_by_bag") or {}
    ).get(bag, [])


def test_post_weight_is_recorded_treats_zero_as_present():
    from backend.management_rinse_wf_review import post_weight_is_recorded

    assert post_weight_is_recorded(0.0) is True
    assert post_weight_is_recorded(None) is False
    assert post_weight_is_recorded(0.0, weight_info={"post_weight_event_exists": True, "post_weight_value": 0.0})
