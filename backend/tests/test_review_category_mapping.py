"""Regression tests for WF Review category mapping and membership."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from backend.management_rinse_wf_review import (
    CATEGORY_MISSING_PORTAL,
    CATEGORY_SPECIALTY,
    CATEGORY_SPLIT_ORDER,
    CATEGORY_UNKNOWN,
    REVIEW_CUSTOMER_UNAVAILABLE,
    category_for_reason_codes,
    missing_portal_review_is_eligible,
    persist_canonical_wf_review_on_headline,
    review_customer_display_name,
    specialty_review_is_unresolved,
    split_review_categories,
)
from backend.rinse_wf_canonical_split import STATE_REVIEW_REQUIRED
from backend.rinse_wf_service_cycle import REVIEW_MISSING_FROM_PORTAL
from backend.rinse_veewash_workload import (
    REASON_DISAPPEARED_WITHOUT_COMPLETION,
    REASON_WF_BULK_WORKITEM_REVIEW,
)

ORG = 3
DAY = date(2026, 8, 24)


def test_wf_bulk_unresolved_maps_specialty():
    assert category_for_reason_codes([REASON_WF_BULK_WORKITEM_REVIEW]) == CATEGORY_SPECIALTY
    assert specialty_review_is_unresolved([REASON_WF_BULK_WORKITEM_REVIEW], bulk_cleared=False)


def test_wf_bulk_cleared_not_specialty():
    assert specialty_review_is_unresolved(
        [REASON_WF_BULK_WORKITEM_REVIEW], bulk_cleared=True
    ) is False


def test_traversal_code_maps_missing_not_specialty():
    assert category_for_reason_codes([REVIEW_MISSING_FROM_PORTAL]) == CATEGORY_MISSING_PORTAL
    assert specialty_review_is_unresolved([REVIEW_MISSING_FROM_PORTAL]) is False


def test_disappeared_pre_completion_missing_portal():
    assert missing_portal_review_is_eligible(
        [REASON_DISAPPEARED_WITHOUT_COMPLETION],
        row={"effective_status": "review_required"},
    )


def test_disappeared_after_valid_completion_not_review():
    assert (
        missing_portal_review_is_eligible(
            [REVIEW_MISSING_FROM_PORTAL],
            row={
                "effective_status": "completed",
                "canonical_completion_timestamp": "2026-08-24T15:00:00",
                "post_weight_lbs": 12.5,
            },
        )
        is False
    )


def test_unknown_reason_not_specialty():
    assert category_for_reason_codes(["TOTALLY_UNKNOWN_CODE"]) is None
    assert specialty_review_is_unresolved(["TOTALLY_UNKNOWN_CODE"]) is False
    split = split_review_categories(
        {
            "segments": {"wf": {"bag_ids": {"review_required": ["BAGX"]}}},
            "review_reasons_by_bag": {"BAGX": ["TOTALLY_UNKNOWN_CODE"]},
        }
    )
    assert split[CATEGORY_SPECIALTY] == []
    assert "BAGX" in split[CATEGORY_UNKNOWN]


def test_headline_membership_union_counts():
    membership = {
        CATEGORY_SPECIALTY: ["S1"],
        CATEGORY_MISSING_PORTAL: ["M1"],
        CATEGORY_SPLIT_ORDER: ["P1"],
        CATEGORY_UNKNOWN: [],
    }
    split = split_review_categories({}, membership=membership)
    assert split["counts"]["review_required"] == 3


def test_persist_canonical_headline_union():
    hl = persist_canonical_wf_review_on_headline(
        {"segments": {"wf": {"bag_ids": {}, "exceptions": {}}}},
        {
            CATEGORY_SPECIALTY: ["S1"],
            CATEGORY_MISSING_PORTAL: [],
            CATEGORY_SPLIT_ORDER: ["P1"],
            "codes_by_bag": {"S1": [REASON_WF_BULK_WORKITEM_REVIEW]},
        },
    )
    assert hl["review_reasons_by_bag"] == {"S1": [REASON_WF_BULK_WORKITEM_REVIEW]}
    assert set(hl["segments"]["wf"]["bag_ids"]["review_required"]) == {"S1", "P1"}
    assert hl["specialty_metrics"]["wf"]["split_review"]["order_ids"] == ["P1"]


def test_customer_name_fallback():
    assert review_customer_display_name(None, "—", "") == REVIEW_CUSTOMER_UNAVAILABLE
    assert review_customer_display_name("Jane Doe") == "Jane Doe"


def test_resolved_bulk_not_in_specialty_membership():
    headline = {
        "segments": {
            "wf": {
                "bag_ids": {
                    "review_required": [],
                    "completed": ["B1"],
                }
            }
        },
        "review_reasons_by_bag": {},
        "review_by_reason": {},
    }
    split = split_review_categories(headline)
    assert split[CATEGORY_SPECIALTY] == []


@patch("backend.management_rinse_wf_review.compute_canonical_wf_review_membership")
def test_review_list_uses_canonical_membership(mock_compute):
    from backend.management_rinse_wf_review import build_management_review_list

    mock_compute.return_value = {
        CATEGORY_SPECIALTY: ["BULK1"],
        CATEGORY_MISSING_PORTAL: [],
        CATEGORY_SPLIT_ORDER: [],
        CATEGORY_UNKNOWN: [],
        "counts": {
            CATEGORY_SPECIALTY: 1,
            CATEGORY_MISSING_PORTAL: 0,
            CATEGORY_SPLIT_ORDER: 0,
            CATEGORY_UNKNOWN: 0,
            "review_required": 1,
        },
        "codes_by_bag": {"BULK1": [REASON_WF_BULK_WORKITEM_REVIEW]},
    }
    headline = {"segments": {"wf": {"bag_ids": {}}}}
    row = {
        "bag_id": "BULK1",
        "service_type": "WF",
        "effective_status": "pending",
        "review_reason_codes": [REASON_WF_BULK_WORKITEM_REVIEW],
        "bag_snapshot": {"customer_name": "Ada Lovelace", "rush_flag": "NON-RUSH"},
        "manager_edit_version": 0,
    }
    def _fill_names(_c, _o, rows, **kwargs):
        for r in rows:
            r["customer_name"] = "Ada Lovelace"
        return rows

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
        patch(
            "backend.management_rinse_wf_review._canonical_review_weights",
            return_value={},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bag_bulk_lines",
            return_value={"BULK1": [{"quantity": 1, "name": "Comforter"}]},
        ),
        patch(
            "backend.management_rinse_wf_review.resolve_customer_names_for_bags",
            side_effect=_fill_names,
        ),
    ):
        out = build_management_review_list(
            MagicMock(), ORG, DAY, category=CATEGORY_SPECIALTY
        )
    assert out["bags"][0]["bag_id"] == "BULK1"
    assert out["bags"][0]["customer_name"] == "Ada Lovelace"
    assert out["counts"]["review_required"] == out["counts"][CATEGORY_SPECIALTY]


def _membership_payload(**overrides):
    codes_by_bag = dict(overrides.pop("codes_by_bag", {}) or {})
    excluded = list(overrides.pop("excluded", []) or [])
    base = {
        CATEGORY_SPECIALTY: [],
        CATEGORY_MISSING_PORTAL: [],
        CATEGORY_SPLIT_ORDER: [],
        CATEGORY_UNKNOWN: [],
        "counts": {
            CATEGORY_SPECIALTY: 0,
            CATEGORY_MISSING_PORTAL: 0,
            CATEGORY_SPLIT_ORDER: 0,
            CATEGORY_UNKNOWN: 0,
            "review_required": 0,
        },
        "codes_by_bag": codes_by_bag,
        "disposition": {},
        "excluded": excluded,
    }
    base.update(overrides)
    out = split_review_categories({}, membership=base)
    out["codes_by_bag"] = codes_by_bag
    out["excluded"] = excluded
    return out


@patch("backend.management_rinse_wf_review.compute_canonical_wf_review_membership")
def test_missing_eligible_counted_in_headline_and_drawer(mock_compute):
    from backend.management_rinse_wf_review import (
        build_management_review_list,
        review_category_count_payload,
    )

    membership = _membership_payload(
        **{
            CATEGORY_MISSING_PORTAL: ["MISS1"],
            "codes_by_bag": {"MISS1": [REVIEW_MISSING_FROM_PORTAL]},
        }
    )
    mock_compute.return_value = membership
    headline = {"segments": {"wf": {"bag_ids": {}}}}
    row = {
        "bag_id": "MISS1",
        "service_type": "WF",
        "effective_status": "review_required",
        "review_reason_codes": [REVIEW_MISSING_FROM_PORTAL],
        "bag_snapshot": {},
        "manager_edit_version": 0,
    }
    with (
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
            return_value={},
        ),
        patch(
            "backend.management_rinse_wf_review.resolve_customer_names_for_bags",
            side_effect=lambda _c, _o, rows, **kwargs: rows,
        ),
    ):
        counts = review_category_count_payload(
            headline, cursor=MagicMock(), organization_id=ORG, selected_date_et=DAY
        )
        drawer = build_management_review_list(
            MagicMock(), ORG, DAY, category=CATEGORY_MISSING_PORTAL
        )
    assert counts["missing_from_portal"] == 1
    assert counts["review_required"] == 1
    assert [b["bag_id"] for b in drawer["bags"]] == ["MISS1"]
    assert drawer["counts"]["review_required"] == 1


@patch("backend.management_rinse_wf_review.compute_canonical_wf_review_membership")
def test_completed_departure_excluded_from_headline_and_drawer(mock_compute):
    from backend.management_rinse_wf_review import (
        build_management_review_list,
        review_category_count_payload,
    )

    mock_compute.return_value = _membership_payload()
    headline = {"segments": {"wf": {"bag_ids": {}}}}
    with (
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
            return_value=[],
        ),
    ):
        counts = review_category_count_payload(
            headline, cursor=MagicMock(), organization_id=ORG, selected_date_et=DAY
        )
        drawer = build_management_review_list(
            MagicMock(), ORG, DAY, category=CATEGORY_MISSING_PORTAL
        )
    assert counts["missing_from_portal"] == 0
    assert counts["review_required"] == 0
    assert drawer["bags"] == []
    assert drawer["counts"]["review_required"] == 0


@patch("backend.management_rinse_wf_review.compute_canonical_wf_review_membership")
def test_stale_missing_not_in_headline_when_canonical_excludes(mock_compute):
    from backend.management_rinse_wf_review import (
        build_management_review_list,
        review_category_count_payload,
    )

    mock_compute.return_value = _membership_payload(
        excluded=["STALE1"],
        codes_by_bag={"STALE1": [REVIEW_MISSING_FROM_PORTAL]},
    )
    headline = {
        "segments": {"wf": {"bag_ids": {"review_required": ["STALE1"]}}},
        "review_reasons_by_bag": {"STALE1": [REVIEW_MISSING_FROM_PORTAL]},
    }
    with (
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
            return_value=[],
        ),
    ):
        counts = review_category_count_payload(
            headline, cursor=MagicMock(), organization_id=ORG, selected_date_et=DAY
        )
        drawer = build_management_review_list(
            MagicMock(), ORG, DAY, category=CATEGORY_MISSING_PORTAL
        )
    assert counts["missing_from_portal"] == 0
    assert drawer["bags"] == []


@patch("backend.management_rinse_wf_review.compute_canonical_wf_review_membership")
def test_review_union_deduplicates_across_categories(mock_compute):
    from backend.management_rinse_wf_review import build_management_review_list

    membership = _membership_payload(
        **{
            CATEGORY_SPECIALTY: ["SPEC1"],
            CATEGORY_MISSING_PORTAL: ["MISS1"],
            CATEGORY_SPLIT_ORDER: ["SPLT1"],
            "codes_by_bag": {
                "SPEC1": [REASON_WF_BULK_WORKITEM_REVIEW],
                "MISS1": [REVIEW_MISSING_FROM_PORTAL],
                "SPLT1": ["SPLIT_MARKED_BUT_SECOND_WASHER_NOT_FOUND"],
            },
        }
    )
    mock_compute.return_value = membership
    headline = {"segments": {"wf": {"bag_ids": {}}}}
    rows = [
        {
            "bag_id": bid,
            "service_type": "WF",
            "effective_status": "review_required",
            "review_reason_codes": membership["codes_by_bag"][bid],
            "bag_snapshot": {},
            "manager_edit_version": 0,
        }
        for bid in ("SPEC1", "MISS1", "SPLT1")
    ]

    def _load(_c, _o, _d, ids, **kwargs):
        want = {str(i).upper() for i in ids}
        return [r for r in rows if r["bag_id"] in want]

    with (
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
            side_effect=_load,
        ),
        patch(
            "backend.management_rinse_wf_review._canonical_review_weights",
            return_value={},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bag_bulk_lines",
            return_value={"SPEC1": [{"quantity": 1}]},
        ),
        patch(
            "backend.management_rinse_wf_review._split_eval_as_of_day",
            return_value={"SPLT1": {"state": STATE_REVIEW_REQUIRED}},
        ),
        patch(
            "backend.management_rinse_wf_review.resolve_customer_names_for_bags",
            side_effect=lambda _c, _o, rs, **kwargs: rs,
        ),
    ):
        spec = build_management_review_list(
            MagicMock(), ORG, DAY, category=CATEGORY_SPECIALTY
        )
        miss = build_management_review_list(
            MagicMock(), ORG, DAY, category=CATEGORY_MISSING_PORTAL
        )
        split = build_management_review_list(
            MagicMock(), ORG, DAY, category=CATEGORY_SPLIT_ORDER
        )
    union = {
        b["bag_id"] for b in spec["bags"] + miss["bags"] + split["bags"]
    }
    assert union == {"SPEC1", "MISS1", "SPLT1"}
    assert spec["counts"]["review_required"] == 3
    assert miss["counts"]["review_required"] == 3
    assert split["counts"]["review_required"] == 3


@patch("backend.management_rinse_wf_review.compute_canonical_wf_review_membership")
def test_multiple_reason_codes_do_not_double_count_headline(mock_compute):
    from backend.management_rinse_wf_review import review_category_count_payload

    mock_compute.return_value = _membership_payload(
        **{
            CATEGORY_MISSING_PORTAL: ["MISS1"],
            "codes_by_bag": {
                "MISS1": [
                    REVIEW_MISSING_FROM_PORTAL,
                    REASON_DISAPPEARED_WITHOUT_COMPLETION,
                ]
            },
        }
    )
    headline = {"segments": {"wf": {"bag_ids": {}}}}
    with patch(
        "backend.rinse_veewash_shift_day.summary_from_day_record",
        return_value=headline,
    ):
        counts = review_category_count_payload(
            headline, cursor=MagicMock(), organization_id=ORG, selected_date_et=DAY
        )
    assert counts["missing_from_portal"] == 1
    assert counts["review_required"] == 1


@patch("backend.management_rinse_wf_review.compute_canonical_wf_review_membership")
def test_headline_count_equals_drawer_union(mock_compute):
    from backend.management_rinse_wf_review import (
        build_management_review_list,
        review_category_count_payload,
    )

    membership = _membership_payload(
        **{
            CATEGORY_SPECIALTY: ["SPEC1"],
            CATEGORY_MISSING_PORTAL: ["MISS1", "MISS2"],
            CATEGORY_SPLIT_ORDER: ["SPLT1"],
            "codes_by_bag": {
                "SPEC1": [REASON_WF_BULK_WORKITEM_REVIEW],
                "MISS1": [REVIEW_MISSING_FROM_PORTAL],
                "MISS2": [REVIEW_MISSING_FROM_PORTAL],
                "SPLT1": ["SPLIT_MARKED_BUT_SECOND_WASHER_NOT_FOUND"],
            },
        }
    )
    mock_compute.return_value = membership
    headline = {"segments": {"wf": {"bag_ids": {}}}}
    rows = [
        {
            "bag_id": bid,
            "service_type": "WF",
            "effective_status": "review_required",
            "review_reason_codes": membership["codes_by_bag"][bid],
            "bag_snapshot": {},
            "manager_edit_version": 0,
        }
        for bid in ("SPEC1", "MISS1", "MISS2", "SPLT1")
    ]

    def _load(_c, _o, _d, ids, **kwargs):
        want = {str(i).upper() for i in ids}
        return [r for r in rows if r["bag_id"] in want]

    with (
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
            side_effect=_load,
        ),
        patch(
            "backend.management_rinse_wf_review._canonical_review_weights",
            return_value={},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bag_bulk_lines",
            return_value={"SPEC1": [{"quantity": 1}]},
        ),
        patch(
            "backend.management_rinse_wf_review._split_eval_as_of_day",
            return_value={"SPLT1": {"state": STATE_REVIEW_REQUIRED}},
        ),
        patch(
            "backend.management_rinse_wf_review.resolve_customer_names_for_bags",
            side_effect=lambda _c, _o, rs, **kwargs: rs,
        ),
    ):
        counts = review_category_count_payload(
            headline, cursor=MagicMock(), organization_id=ORG, selected_date_et=DAY
        )
        drawers = [
            build_management_review_list(
                MagicMock(), ORG, DAY, category=cat
            )
            for cat in (
                CATEGORY_SPECIALTY,
                CATEGORY_MISSING_PORTAL,
                CATEGORY_SPLIT_ORDER,
            )
        ]
    union = {b["bag_id"] for d in drawers for b in d["bags"]}
    assert counts["review_required"] == len(union) == 4
    for d in drawers:
        assert d["counts"]["review_required"] == 4


def test_persist_canonical_projection_matches_union():
    membership = {
        CATEGORY_SPECIALTY: ["SPEC1"],
        CATEGORY_MISSING_PORTAL: ["MISS1"],
        CATEGORY_SPLIT_ORDER: ["SPLT1"],
        CATEGORY_UNKNOWN: [],
        "codes_by_bag": {
            "SPEC1": [REASON_WF_BULK_WORKITEM_REVIEW],
            "MISS1": [REVIEW_MISSING_FROM_PORTAL],
        },
    }
    hl = persist_canonical_wf_review_on_headline(
        {"segments": {"wf": {"bag_ids": {}, "exceptions": {}}}},
        membership,
    )
    split = split_review_categories(hl, membership=membership)
    assert split["counts"]["review_required"] == 3
    assert set(hl["segments"]["wf"]["bag_ids"]["review_required"]) == {"SPEC1", "MISS1", "SPLT1"}
    assert hl["segments"]["wf"]["exceptions"]["review_required"] == 3
