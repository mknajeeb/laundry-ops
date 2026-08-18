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


def test_specialty_membership_shared_helper_matches_split():
    headline = {
        "segments": {
            "wf": {
                "bag_ids": {
                    "review_required": ["BAGAAA01", "BAGBBB02"],
                }
            }
        },
        "review_reasons_by_bag": {
            "BAGAAA01": ["WF_BULK_WORKITEM_REVIEW"],
            "BAGBBB02": ["DISAPPEARED_WITHOUT_COMPLETION"],
        },
        "review_by_reason": {
            "WF_BULK_WORKITEM_REVIEW": ["BAGAAA01"],
            "DISAPPEARED_WITHOUT_COMPLETION": ["BAGBBB02"],
        },
    }
    from backend.management_rinse_wf_review import (
        review_category_count_payload,
        specialty_review_membership_ids,
    )

    assert specialty_review_membership_ids(headline) == ["BAGAAA01"]
    counts = review_category_count_payload(headline)
    assert counts["specialty_items"] == 1
    assert counts["missing_from_portal"] == 1
    assert counts["specialty_items"] == len(specialty_review_membership_ids(headline))


def test_review_detail_defaults_scans_off():
    """Modal core must not require include_scans=True (progressive load)."""
    import inspect

    from backend.management_rinse_wf_review import build_management_review_detail

    params = inspect.signature(build_management_review_detail).parameters
    assert "include_scans" in params
    assert params["include_scans"].default is False


def test_drawer_section_flags_allow_both():
    from backend.management_rinse_wf_review import review_drawer_section_flags

    both = review_drawer_section_flags(
        ["WF_BULK_WORKITEM_REVIEW", "DISAPPEARED_WITHOUT_COMPLETION"]
    )
    assert both["has_specialty_bulk"] is True
    assert both["has_missing_portal"] is True
    missing_only = review_drawer_section_flags(["DISAPPEARED_WITHOUT_COMPLETION"])
    assert missing_only["has_missing_portal"] is True
    assert missing_only["has_specialty_bulk"] is False
    weight_only = review_drawer_section_flags(["WF_ZERO_OR_MISSING_POST_WEIGHT"])
    assert weight_only["has_specialty_bulk"] is False
    assert weight_only["has_missing_portal"] is False


def test_review_list_is_summary_only_no_scans():
    from datetime import date
    from unittest.mock import MagicMock, patch

    from backend.management_rinse_wf_review import build_management_review_list

    headline = {
        "segments": {"wf": {"bag_ids": {"review_required": ["BAGMISS01"]}}},
        "review_reasons_by_bag": {
            "BAGMISS01": ["DISAPPEARED_WITHOUT_COMPLETION"],
        },
        "review_by_reason": {
            "DISAPPEARED_WITHOUT_COMPLETION": ["BAGMISS01"],
        },
    }
    row = {
        "bag_id": "BAGMISS01",
        "effective_status": "review_required",
        "review_reason_codes": ["DISAPPEARED_WITHOUT_COMPLETION"],
        "pre_weight_lbs": 12.5,
        "post_weight_lbs": None,
        "canonical_completion_employee": None,
        "canonical_completion_timestamp": None,
        "manager_edit_version": 0,
        "updated_at": "2026-08-17T12:00:00",
        "bag_snapshot": {
            "customer_name": "Ada",
            "rush_flag": "RUSH",
            "pre_weight_lbs": 12.5,
            "reason_codes": ["DISAPPEARED_WITHOUT_COMPLETION"],
        },
    }
    with (
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
        patch("backend.rinse_bulk_workitems.load_bag_bulk_lines") as bulk,
        patch("backend.rinse_veewash_step1_api.load_scans_for_bags") as scans,
    ):
        out = build_management_review_list(
            MagicMock(),
            3,
            date(2026, 8, 17),
            category="missing_from_portal",
        )
    scans.assert_not_called()
    bulk.assert_not_called()
    assert out["ok"] is True
    assert out["_meta"]["scans_loaded"] is False
    assert out["_meta"]["action_metadata"] is False
    bag = out["bags"][0]
    assert bag["bag_id"] == "BAGMISS01"
    assert bag["pre_weight_lbs"] == 12.5
    assert bag["has_missing_portal"] is True
    assert bag["has_specialty_bulk"] is False
    assert "scans" not in bag


def test_review_action_metadata_loads_no_scans():
    from datetime import date
    from unittest.mock import MagicMock, patch

    from backend.management_rinse_wf_review import build_management_review_action

    row = {
        "bag_id": "BAGSPEC01",
        "effective_status": "review_required",
        "review_reason_codes": ["WF_BULK_WORKITEM_REVIEW"],
        "pre_weight_lbs": 10,
        "post_weight_lbs": 9,
        "canonical_completion_employee": "Ada",
        "canonical_completion_timestamp": "2026-08-17 10:00:00",
        "manager_edit_version": 2,
        "updated_at": "2026-08-17T12:00:00",
        "bag_snapshot": {
            "customer_name": "Ada",
            "rush_flag": "NON-RUSH",
            "pre_weight_lbs": 10,
            "post_weight_lbs": 9,
            "completed_by": "Ada",
        },
    }
    lines = [
        {
            "workitem_id": 1,
            "workitem_name": "Bath Mat",
            "quantity": 2,
            "unit_price": 4.0,
            "line_total": 8.0,
        }
    ]
    catalog = [{"id": 1, "name": "Bath Mat", "current_unit_price": 4.0}]
    with (
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[row],
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bag_bulk_lines",
            return_value={"BAGSPEC01": lines},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bulk_resolutions",
            return_value={},
        ),
        patch(
            "backend.rinse_bulk_workitems.list_workitems",
            return_value=catalog,
        ),
        patch("backend.rinse_veewash_step1_api.load_scans_for_bags") as scans,
        patch("backend.rinse_veewash_step1_api.build_drilldown") as drill,
    ):
        out = build_management_review_action(
            MagicMock(),
            3,
            date(2026, 8, 17),
            "BAGSPEC01",
        )
    scans.assert_not_called()
    drill.assert_not_called()
    assert out["ok"] is True
    assert out["_meta"]["scans_loaded"] is False
    assert out["_meta"]["action_metadata"] is True
    assert out["bag"]["_detailsLoaded"] is True
    assert out["bag"]["has_specialty_bulk"] is True
    assert out["bag"]["manager_edit_version"] == 2
    assert out["active_bulk_workitems"] == catalog
    assert out["bag"]["bulk_workitems"] == lines
