"""Management Rinse WF Review category split + light list helpers."""

from __future__ import annotations

from backend.management_rinse_wf_review import (
    CATEGORY_MISSING_PORTAL,
    CATEGORY_SPECIALTY,
    category_for_reason_codes,
    specialty_review_is_resolved,
    specialty_review_is_unresolved,
    split_review_categories,
    _specialty_qty_from_lines,
)


def test_category_specialty_bulk():
    assert category_for_reason_codes(["WF_BULK_WORKITEM_REVIEW"]) == CATEGORY_SPECIALTY


def test_category_missing_portal():
    assert (
        category_for_reason_codes(["DISAPPEARED_WITHOUT_COMPLETION"])
        == CATEGORY_MISSING_PORTAL
    )


def test_specialty_bulk_wins_over_disappeared():
    assert (
        category_for_reason_codes(
            ["DISAPPEARED_WITHOUT_COMPLETION", "WF_BULK_WORKITEM_REVIEW"]
        )
        == CATEGORY_SPECIALTY
    )


def test_other_review_reasons_route_to_specialty_queue():
    assert (
        category_for_reason_codes(["WF_ZERO_OR_MISSING_POST_WEIGHT"])
        == CATEGORY_SPECIALTY
    )
    assert category_for_reason_codes(["MANAGER_SENT_FOR_REVIEW"]) == CATEGORY_SPECIALTY


def test_split_no_double_count():
    headline = {
        "segments": {
            "wf": {
                "bag_ids": {
                    "review_required": ["BAGAAA01", "BAGBBB02", "BAGCCC03"],
                }
            }
        },
        "review_reasons_by_bag": {
            "BAGAAA01": ["WF_BULK_WORKITEM_REVIEW"],
            "BAGBBB02": ["DISAPPEARED_WITHOUT_COMPLETION"],
            "BAGCCC03": ["WF_ZERO_OR_MISSING_POST_WEIGHT"],
        },
        "review_by_reason": {
            "WF_BULK_WORKITEM_REVIEW": ["BAGAAA01"],
            "DISAPPEARED_WITHOUT_COMPLETION": ["BAGBBB02"],
            "WF_ZERO_OR_MISSING_POST_WEIGHT": ["BAGCCC03"],
        },
    }
    split = split_review_categories(headline)
    assert split["counts"]["review_required"] == 3
    assert split["counts"][CATEGORY_SPECIALTY] == 2
    assert split["counts"][CATEGORY_MISSING_PORTAL] == 1
    assert set(split[CATEGORY_SPECIALTY]) == {"BAGAAA01", "BAGCCC03"}
    assert set(split[CATEGORY_MISSING_PORTAL]) == {"BAGBBB02"}
    # No overlap.
    assert not (set(split[CATEGORY_SPECIALTY]) & set(split[CATEGORY_MISSING_PORTAL]))


def test_comforter_quantity_not_collapsed_to_boolean():
    info = _specialty_qty_from_lines(
        [{"workitem_name_snapshot": "Comforter", "quantity": 2}]
    )
    assert info["comforter_quantity"] == 2
    assert info["specialty_quantity"] == 2
    assert info["specialty_item_class"] == "comforter"


def test_a_completed_unresolved_specialty_remains_active():
    """A. completed + unresolved specialty → still active Specialty Review."""
    assert specialty_review_is_unresolved(["WF_BULK_WORKITEM_REVIEW"]) is True
    headline = {
        "segments": {
            "wf": {
                "bag_ids": {
                    # Bag is completed in segments — NOT in review_required.
                    "completed": ["DONEUNRES1"],
                    "review_required": [],
                }
            }
        },
        "review_reasons_by_bag": {
            "DONEUNRES1": ["WF_BULK_WORKITEM_REVIEW"],
        },
        "review_by_reason": {
            "WF_BULK_WORKITEM_REVIEW": ["DONEUNRES1"],
        },
    }
    split = split_review_categories(headline)
    assert "DONEUNRES1" in split[CATEGORY_SPECIALTY]
    assert split["counts"][CATEGORY_SPECIALTY] == 1


def test_b_completed_resolved_specialty_leaves_active():
    """B. completed + resolved specialty → leaves active Specialty Review."""
    assert specialty_review_is_resolved([]) is True
    assert specialty_review_is_resolved(
        ["WF_BULK_WORKITEM_REVIEW"], bulk_cleared=True
    ) is True
    headline = {
        "segments": {
            "wf": {
                "bag_ids": {
                    "completed": ["CTQG55K5XD"],
                    "review_required": [],
                }
            }
        },
        # Resolved: no specialty reasons remain.
        "review_reasons_by_bag": {},
        "review_by_reason": {},
    }
    split = split_review_categories(headline)
    assert "CTQG55K5XD" not in split[CATEGORY_SPECIALTY]
    assert split["counts"][CATEGORY_SPECIALTY] == 0


def test_c_not_completed_resolved_specialty_leaves_queue():
    """C. pending/not-completed + resolved specialty → leaves Specialty Items.

    Current workflow semantics (apply_manager_edit_day_bag_patch): clearing the
    last specialty reason without mark_completed moves the bag to pending (or
    completed if canonical completion already exists). Specialty Items membership
    follows reason resolution — empty specialty reasons ⇒ not in Specialty Items,
    independent of completed vs pending.
    """
    headline = {
        "segments": {
            "wf": {
                "bag_ids": {
                    "pending": ["PENDRESOL1"],
                    "review_required": [],
                    "completed": [],
                }
            }
        },
        "review_reasons_by_bag": {},
        "review_by_reason": {},
    }
    split = split_review_categories(headline)
    assert "PENDRESOL1" not in split[CATEGORY_SPECIALTY]
    assert split["counts"][CATEGORY_SPECIALTY] == 0
