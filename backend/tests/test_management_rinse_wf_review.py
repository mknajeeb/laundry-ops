"""Management Rinse WF Review category split + light list helpers."""

from __future__ import annotations

import pytest

from backend.management_rinse_wf_review import (
    CATEGORY_MISSING_PORTAL,
    CATEGORY_SPECIALTY,
    category_for_reason_codes,
    specialty_review_is_resolved,
    specialty_review_is_unresolved,
    split_review_categories,
    _specialty_qty_from_lines,
)


@pytest.fixture(autouse=True)
def _mock_canonical_membership_for_list(monkeypatch, request):
    """List tests use headline-shaped membership unless integration tests opt out."""
    if request.node.get_closest_marker("integration_membership"):
        yield
        return

    def _fake(cursor, organization_id, selected_date_et, *, headline=None):
        split = split_review_categories(headline)
        by_bag = (headline or {}).get("review_reasons_by_bag") or {}
        disposition = {}
        for bid, codes in by_bag.items():
            if specialty_review_is_unresolved(codes):
                disposition[bid] = CATEGORY_SPECIALTY
            elif category_for_reason_codes(codes) == CATEGORY_MISSING_PORTAL:
                disposition[bid] = CATEGORY_MISSING_PORTAL
            elif category_for_reason_codes(codes) is None:
                disposition[bid] = CATEGORY_UNKNOWN
        return {
            **split,
            "disposition": disposition,
            "excluded": [],
            "codes_by_bag": dict(by_bag),
        }

    monkeypatch.setattr(
        "backend.management_rinse_wf_review.compute_canonical_wf_review_membership",
        _fake,
    )
    yield


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


def test_a_hd_disappeared_not_on_wf_missing_portal():
    """A. HD + DISAPPEARED → not WF Missing From Portal (HD review only)."""
    headline = {
        "segments": {
            "wf": {
                "bag_ids": {
                    "review_required": [],
                    "pending": ["WFONLY01"],
                    "completed": [],
                }
            },
            "hd": {
                "bag_ids": {
                    "review_required": ["84GBGYG38M"],
                }
            },
        },
        "review_reasons_by_bag": {
            "84GBGYG38M": ["DISAPPEARED_WITHOUT_COMPLETION"],
        },
        "review_by_reason": {
            "DISAPPEARED_WITHOUT_COMPLETION": ["84GBGYG38M"],
        },
    }
    split = split_review_categories(headline)
    assert "84GBGYG38M" not in split[CATEGORY_MISSING_PORTAL]
    assert split["counts"][CATEGORY_MISSING_PORTAL] == 0
    assert split["counts"]["review_required"] == 0


def test_b_wf_disappeared_on_wf_missing_portal():
    """B. WF + DISAPPEARED → WF Missing From Portal."""
    headline = {
        "segments": {
            "wf": {
                "bag_ids": {
                    "review_required": ["WFMISS01"],
                    "pending": [],
                    "completed": [],
                }
            },
            "hd": {"bag_ids": {"review_required": []}},
        },
        "review_reasons_by_bag": {
            "WFMISS01": ["DISAPPEARED_WITHOUT_COMPLETION"],
        },
        "review_by_reason": {
            "DISAPPEARED_WITHOUT_COMPLETION": ["WFMISS01"],
        },
    }
    split = split_review_categories(headline)
    assert set(split[CATEGORY_MISSING_PORTAL]) == {"WFMISS01"}
    assert split["counts"][CATEGORY_MISSING_PORTAL] == 1


def test_c_empty_wf_review_required_ignores_hd_review_by_reason():
    """C. Empty WF review_required + HD in review_by_reason → WF queues empty."""
    headline = {
        "segments": {
            "wf": {
                "bag_ids": {
                    "review_required": [],
                    "pending": ["WFPEND01"],
                    "completed": ["WFCOMP01"],
                }
            },
            "hd": {
                "bag_ids": {
                    "review_required": ["HDREV01", "HDREV02"],
                }
            },
        },
        "review_reasons_by_bag": {
            "HDREV01": ["DISAPPEARED_WITHOUT_COMPLETION"],
            "HDREV02": ["DISAPPEARED_WITHOUT_COMPLETION"],
        },
        "review_by_reason": {
            "DISAPPEARED_WITHOUT_COMPLETION": ["HDREV01", "HDREV02"],
        },
    }
    split = split_review_categories(headline)
    assert split[CATEGORY_MISSING_PORTAL] == []
    assert split[CATEGORY_SPECIALTY] == []
    assert split["counts"]["review_required"] == 0


def test_d_mixed_wf_hd_review_by_reason_service_isolated():
    """D. Mixed WF/HD review_by_reason → WF tab receives WF only."""
    headline = {
        "segments": {
            "wf": {
                "bag_ids": {
                    "review_required": ["WFMISS01"],
                    "pending": [],
                    "completed": ["WFSPEC01"],
                }
            },
            "hd": {
                "bag_ids": {
                    "review_required": ["HDMISS01"],
                }
            },
        },
        "review_reasons_by_bag": {
            "WFMISS01": ["DISAPPEARED_WITHOUT_COMPLETION"],
            "HDMISS01": ["DISAPPEARED_WITHOUT_COMPLETION"],
            "WFSPEC01": ["WF_BULK_WORKITEM_REVIEW"],
            "HDSPEC01": ["WF_BULK_WORKITEM_REVIEW"],
        },
        "review_by_reason": {
            "DISAPPEARED_WITHOUT_COMPLETION": ["WFMISS01", "HDMISS01"],
            "WF_BULK_WORKITEM_REVIEW": ["WFSPEC01", "HDSPEC01"],
        },
    }
    split = split_review_categories(headline)
    wf_review = set(split[CATEGORY_MISSING_PORTAL]) | set(split[CATEGORY_SPECIALTY])
    assert wf_review == {"WFMISS01", "WFSPEC01"}
    assert "HDMISS01" not in wf_review
    assert "HDSPEC01" not in wf_review
    # Authoritative HD IDs must not intersect WF review queues.
    hd_ids = {"HDMISS01", "HDSPEC01"}
    assert wf_review.isdisjoint(hd_ids)


def test_e_wf_missing_portal_list_workflow_still_works():
    """E. Existing WF Missing From Portal list path still returns the WF bag."""
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
        "service_type": "WF",
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
        patch(
            "backend.management_rinse_wf_review._canonical_review_weights",
            return_value={
                "BAGMISS01": {
                    "pre_weight_lbs": 12.5,
                    "pre_weight_event_id": 99,
                    "post_weight_lbs": None,
                }
            },
        ),
        patch("backend.rinse_bulk_workitems.load_bag_bulk_lines", return_value={}) as bulk,
        patch("backend.rinse_bulk_workitems.load_bulk_resolutions", return_value={}),
        patch("backend.rinse_veewash_step1_api.load_scans_for_bags") as scans,
    ):
        out = build_management_review_list(
            MagicMock(),
            3,
            date(2026, 8, 17),
            category="missing_from_portal",
        )
    scans.assert_not_called()
    bulk.assert_called_once()
    assert out["ok"] is True
    assert out["bags"][0]["bag_id"] == "BAGMISS01"
    assert out["bags"][0]["has_missing_portal"] is True


def test_hd_day_bag_dropped_from_wf_missing_list_even_if_headline_leaks():
    """List heal drops explicit HD day-bag rows from WF Missing From Portal."""
    from datetime import date
    from unittest.mock import MagicMock, patch

    from backend.management_rinse_wf_review import build_management_review_list

    # Simulate a leaked headline ID that should still be blocked by day_bag service.
    headline = {
        "segments": {
            "wf": {"bag_ids": {"review_required": ["84GBGYG38M"]}},
        },
        "review_reasons_by_bag": {
            "84GBGYG38M": ["DISAPPEARED_WITHOUT_COMPLETION"],
        },
        "review_by_reason": {
            "DISAPPEARED_WITHOUT_COMPLETION": ["84GBGYG38M"],
        },
    }
    row = {
        "bag_id": "84GBGYG38M",
        "service_type": "HD",
        "effective_status": "review_required",
        "review_reason_codes": ["DISAPPEARED_WITHOUT_COMPLETION"],
        "bag_snapshot": {"rush_flag": "RUSH"},
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
        patch("backend.rinse_bulk_workitems.load_bag_bulk_lines"),
        patch("backend.rinse_veewash_step1_api.load_scans_for_bags"),
    ):
        out = build_management_review_list(
            MagicMock(),
            3,
            date(2026, 8, 17),
            category="missing_from_portal",
        )
    assert out["ok"] is True
    assert out["bags"] == []
    assert out["pagination"]["total"] == 0
    assert out["counts"].get("missing_from_portal") == 0


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
        "service_type": "WF",
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
        patch(
            "backend.management_rinse_wf_review._canonical_review_weights",
            return_value={
                "BAGMISS01": {
                    "pre_weight_lbs": 12.5,
                    "pre_weight_event_id": 99,
                    "post_weight_lbs": None,
                }
            },
        ),
        patch("backend.rinse_bulk_workitems.load_bag_bulk_lines", return_value={}) as bulk,
        patch("backend.rinse_bulk_workitems.load_bulk_resolutions", return_value={}),
        patch("backend.rinse_veewash_step1_api.load_scans_for_bags") as scans,
    ):
        out = build_management_review_list(
            MagicMock(),
            3,
            date(2026, 8, 17),
            category="missing_from_portal",
        )
    scans.assert_not_called()
    bulk.assert_called_once()
    assert out["ok"] is True
    assert out["_meta"]["scans_loaded"] is False
    assert out["_meta"]["action_metadata"] is False
    bag = out["bags"][0]
    assert bag["bag_id"] == "BAGMISS01"
    assert bag["pre_weight_lbs"] == 12.5
    assert bag["has_missing_portal"] is True
    assert bag["has_specialty_bulk"] is False
    assert "scans" not in bag


def test_review_list_clears_stale_snap_pre_when_resolver_has_no_pre():
    from datetime import date
    from unittest.mock import MagicMock, patch

    from backend.management_rinse_wf_review import _merge_review_weight_fields, build_management_review_list

    bag = {"pre_weight_lbs": 13.1, "post_weight_lbs": 13.1}
    _merge_review_weight_fields(
        bag,
        {
            "pre_weight_lbs": None,
            "pre_weight_event_id": None,
            "post_weight_lbs": 13.1,
            "post_weight_event_id": 99,
            "post_weight_event_exists": True,
        },
    )
    assert bag["pre_weight_lbs"] is None
    assert bag["evidence_pre_weight_lbs"] is None
    assert bag["post_weight_lbs"] == 13.1

    headline = {
        "segments": {"wf": {"bag_ids": {"review_required": ["0WMBKDYLS0"]}}},
        "review_reasons_by_bag": {"0WMBKDYLS0": ["DISAPPEARED_WITHOUT_COMPLETION"]},
        "review_by_reason": {"DISAPPEARED_WITHOUT_COMPLETION": ["0WMBKDYLS0"]},
    }
    row = {
        "bag_id": "0WMBKDYLS0",
        "service_type": "WF",
        "effective_status": "review_required",
        "review_reason_codes": ["DISAPPEARED_WITHOUT_COMPLETION"],
        "pre_weight_lbs": 13.1,
        "post_weight_lbs": None,
        "canonical_completion_timestamp": None,
        "manager_edit_version": 0,
        "updated_at": "2026-08-22T12:00:00",
        "bag_snapshot": {
            "customer_name": "Test",
            "rush_flag": "NON-RUSH",
            "pre_weight_lbs": 13.1,
            "post_weight_lbs": None,
        },
    }
    with (
        patch("backend.rinse_veewash_shift_day.get_day_record", return_value={"headline": headline}),
        patch("backend.rinse_veewash_shift_day.summary_from_day_record", return_value=headline),
        patch("backend.rinse_veewash_shift_day.load_day_bags_by_ids", return_value=[row]),
        patch(
            "backend.management_rinse_wf_review._canonical_review_weights",
            return_value={
                "0WMBKDYLS0": {
                    "pre_weight_lbs": None,
                    "pre_weight_event_id": None,
                    "post_weight_lbs": 13.1,
                    "post_weight_event_id": 99,
                    "post_weight_event_exists": True,
                }
            },
        ),
        patch("backend.rinse_bulk_workitems.load_bag_bulk_lines"),
    ):
        out = build_management_review_list(
            MagicMock(),
            3,
            date(2026, 8, 22),
            category="missing_from_portal",
        )
    bag_out = out["bags"][0]
    assert bag_out["pre_weight_lbs"] is None
    assert bag_out["evidence_pre_weight_lbs"] is None
    assert bag_out["post_weight_lbs"] == 13.1


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
    assert out["bag"]["has_specialty_bulk"] is False
    assert out["bag"]["bulk_review_cleared"] is True
    assert out["bag"]["bulk_review_unresolved"] is False
    assert out["bag"]["manager_edit_version"] == 2
    assert out["active_bulk_workitems"] == catalog
    assert out["bag"]["bulk_workitems"] == lines


def test_review_action_metadata_zero_scans_empty_optional_records():
    """Fresh-start purge: no scan rows must not block action metadata."""
    from datetime import date
    from unittest.mock import MagicMock, patch

    from backend.management_rinse_wf_review import build_management_review_action

    row = {
        "bag_id": "EZRTRBZGGJ",
        "effective_status": "review_required",
        "review_reason_codes": ["WF_BULK_WORKITEM_REVIEW"],
        "post_weight_lbs": None,
        "manager_edit_version": 0,
        "updated_at": "2026-08-24T12:00:00",
        "bag_snapshot": {
            "customer_name": "Halle Briede",
            "rush_flag": "NON-RUSH",
        },
    }
    with (
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[row],
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bag_bulk_lines",
            return_value={"EZRTRBZGGJ": []},
        ),
        patch(
            "backend.rinse_bulk_workitems.load_bulk_resolutions",
            return_value={},
        ),
        patch(
            "backend.rinse_bulk_workitems.list_workitems",
            return_value=[{"id": 1, "name": "Bath Mat", "current_unit_price": 4.0}],
        ),
        patch(
            "backend.management_rinse_wf_review._canonical_review_weights",
            return_value={"EZRTRBZGGJ": {}},
        ),
    ):
        out = build_management_review_action(
            MagicMock(),
            3,
            date(2026, 8, 24),
            "EZRTRBZGGJ",
        )
    assert out["ok"] is True
    assert out["bag"]["bag_id"] == "EZRTRBZGGJ"
    assert out["bag"]["_detailsLoaded"] is True
    assert out["_meta"]["scans_loaded"] is False
    assert out["bag"]["bulk_workitems"] == []


def test_review_detail_zero_scans_returns_core_bag():
    """Modal/detail path must return bag core when scan history is empty."""
    from datetime import date
    from unittest.mock import MagicMock, patch

    from backend.management_rinse_wf_review import build_management_review_detail

    bag = {
        "bag_id": "EZRTRBZGGJ",
        "customer_name": "Halle Briede",
        "reason_codes": ["WF_BULK_WORKITEM_REVIEW"],
        "bulk_workitems": [],
        "scans": [],
    }
    with patch(
        "backend.rinse_veewash_step1_api.build_drilldown",
        return_value={
            "bags": [bag],
            "active_bulk_workitems": [],
            "timing_ms": 1.2,
        },
    ):
        out = build_management_review_detail(
            MagicMock(),
            3,
            date(2026, 8, 24),
            "EZRTRBZGGJ",
            include_scans=False,
        )
    assert out["ok"] is True
    assert out["bag"]["bag_id"] == "EZRTRBZGGJ"
    assert out["bag"]["_detailsLoaded"] is True
    assert out["_meta"]["scans_loaded"] is False


def test_review_detail_error_shape():
    from datetime import date
    from unittest.mock import MagicMock, patch

    from backend.management_rinse_wf_review import build_management_review_detail

    with patch(
        "backend.rinse_veewash_step1_api.build_drilldown",
        return_value={"bags": []},
    ):
        out = build_management_review_detail(
            MagicMock(),
            3,
            date(2026, 8, 24),
            "MISSING01",
        )
    assert out["ok"] is False
    assert out["error"] == "bag_not_found"


@pytest.mark.integration_membership
def test_split_order_list_filters_persisted_ids_with_as_of_day_cutoff():
    """Persisted split_review polluted by D+1 must not list bags as-of D."""
    from datetime import date
    from unittest.mock import MagicMock, patch

    from backend.management_rinse_wf_review import build_management_review_list
    from backend.rinse_wf_canonical_split import STATE_PENDING, STATE_REVIEW_REQUIRED

    headline = {
        "segments": {
            "wf": {
                "bag_ids": {
                    "pending": ["3WXRM6SYAR", "6IU2WPCXNL"],
                    "carried_forward": [],
                }
            }
        },
        "specialty_metrics": {
            "wf": {
                "split_review": {
                    "count": 2,
                    "order_ids": ["3WXRM6SYAR", "6IU2WPCXNL"],
                    "orders": [
                        {"bag_id": "3WXRM6SYAR"},
                        {"bag_id": "6IU2WPCXNL"},
                    ],
                }
            }
        },
    }
    # As-of D both bags are PENDING (D+1 evidence truncated away).
    as_of_evals = {
        "3WXRM6SYAR": {"state": STATE_PENDING},
        "6IU2WPCXNL": {"state": STATE_PENDING},
    }
    with (
        patch(
            "backend.rinse_veewash_shift_day.get_day_record",
            return_value={"headline": headline, "status": "CLOSED"},
        ),
        patch(
            "backend.rinse_veewash_shift_day.summary_from_day_record",
            return_value=headline,
        ),
        patch(
            "backend.management_rinse_wf_review._split_eval_as_of_day",
            return_value=as_of_evals,
        ) as eval_as_of,
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[],
        ),
    ):
        out = build_management_review_list(
            MagicMock(),
            3,
            date(2026, 8, 17),
            category="split_order_review",
        )
    eval_as_of.assert_called()
    assert out["ok"] is True
    assert out["bags"] == []
    assert out["pagination"]["total"] == 0
    # Sanity: if as-of said REVIEW, they would remain.
    as_of_evals["3WXRM6SYAR"] = {"state": STATE_REVIEW_REQUIRED}
    with (
        patch(
            "backend.rinse_veewash_shift_day.get_day_record",
            return_value={"headline": headline, "status": "CLOSED"},
        ),
        patch(
            "backend.rinse_veewash_shift_day.summary_from_day_record",
            return_value=headline,
        ),
        patch(
            "backend.management_rinse_wf_review._split_eval_as_of_day",
            return_value=as_of_evals,
        ),
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[
                {
                    "bag_id": "3WXRM6SYAR",
                    "service_type": "WF",
                    "effective_status": "carried_forward",
                    "bag_snapshot": {},
                    "review_reason_codes": [],
                    "manager_edit_version": 0,
                }
            ],
        ),
    ):
        out2 = build_management_review_list(
            MagicMock(),
            3,
            date(2026, 8, 17),
            category="split_order_review",
        )
    assert out2["pagination"]["total"] == 1
    assert out2["bags"][0]["bag_id"] == "3WXRM6SYAR"
