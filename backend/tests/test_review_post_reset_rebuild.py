"""Review queue rebuild after reset — specialty headline sync + drawer membership."""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

ORG = 3
DAY = date(2026, 8, 24)
SPECIALTY_BAGS = ["20UZTCOM4C", "4BKS43BJVM", "662ETTUK4S", "EZRTRBZGGJ"]


def _wf_headline(*, review_reasons=None, review_required=None, completed=None):
    completed = list(completed or SPECIALTY_BAGS)
    review_required = list(review_required or [])
    review_reasons = dict(review_reasons or {})
    for bid in SPECIALTY_BAGS:
        review_reasons.setdefault(bid, ["WF_BULK_WORKITEM_REVIEW"])
    by_reason: dict[str, list[str]] = {}
    for bid, codes in review_reasons.items():
        for code in codes:
            by_reason.setdefault(code, []).append(bid)
    return {
        "segments": {
            "wf": {
                "completed": len(completed),
                "pending": 43,
                "total_workload": 113,
                "active_workload": 113,
                "exceptions": {"review_required": len(review_required), "total": len(review_required)},
                "bag_ids": {
                    "completed": completed,
                    "pending": ["PEND1"] * 43,
                    "review_required": review_required,
                    "new_today": completed + review_required + (["PEND1"] * 43),
                },
            }
        },
        "review_reasons_by_bag": review_reasons,
        "review_by_reason": by_reason,
    }


def test_load_persisted_reasons_includes_completed_unresolved_specialty():
    from backend.rinse_veewash_shift_day import _load_persisted_review_reasons_by_bag

    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {
            "bag_id": "20UZTCOM4C",
            "review_reason_codes_json": '["WF_BULK_WORKITEM_REVIEW"]',
            "effective_status": "completed",
            "service_type": "WF",
        },
        {
            "bag_id": "HDONLY1",
            "review_reason_codes_json": '["HD_COMPLETION_DETAILS_MISSING"]',
            "effective_status": "review_required",
            "service_type": "HD",
        },
        {
            "bag_id": "MISSING1",
            "review_reason_codes_json": '["DISAPPEARED_WITHOUT_COMPLETION"]',
            "effective_status": "review_required",
            "service_type": "WF",
        },
        {
            "bag_id": "RESOLVED1",
            "review_reason_codes_json": "[]",
            "effective_status": "completed",
            "service_type": "WF",
        },
    ]
    out = _load_persisted_review_reasons_by_bag(cursor, ORG, DAY)
    assert out["20UZTCOM4C"] == ["WF_BULK_WORKITEM_REVIEW"]
    assert out["MISSING1"] == ["DISAPPEARED_WITHOUT_COMPLETION"]
    assert "HDONLY1" in out
    assert "RESOLVED1" not in out


def test_sync_headline_projects_specialty_from_completed_day_bags():
    from backend.rinse_veewash_shift_day import _sync_day_header_from_persisted_bags

    cursor = MagicMock()
    headline = _wf_headline(review_reasons={}, review_required=[], completed=SPECIALTY_BAGS)
    status_rows = {
        bid: {
            "effective_status": "completed",
            "service_type": "WF",
            "rush_status": "NON-RUSH",
        }
        for bid in SPECIALTY_BAGS
    }
    with patch(
        "backend.rinse_veewash_shift_day._load_day_bag_status_projection",
        return_value=status_rows,
    ), patch(
        "backend.rinse_veewash_shift_day._load_persisted_review_reasons_by_bag",
        return_value={bid: ["WF_BULK_WORKITEM_REVIEW"] for bid in SPECIALTY_BAGS},
    ), patch(
        "backend.rinse_veewash_shift_day._apply_day_bag_statuses_to_headline",
        side_effect=lambda h, _s: h,
    ):
        _sync_day_header_from_persisted_bags(
            cursor,
            ORG,
            DAY,
            summary=headline,
            workload={"review_reasons_by_bag": {}},
            next_status="OPEN",
            opened_at=None,
            now=__import__("datetime").datetime.utcnow(),
        )
    update = None
    for call in cursor.execute.call_args_list:
        sql = str(call.args[0]) if call.args else ""
        if "headline_json" in sql and "UPDATE" not in sql:
            update = json.loads(call.args[1][6])
            break
        if "headline_json = incoming.headline_json" in sql:
            update = json.loads(call.args[1][6])
    assert update is not None
    assert set(update.get("review_reasons_by_bag") or {}) >= set(SPECIALTY_BAGS)


def test_specialty_eligibility_from_headline():
    from backend.management_rinse_wf_review import (
        CATEGORY_SPECIALTY,
        split_review_categories,
    )

    split = split_review_categories(_wf_headline())
    assert split["counts"][CATEGORY_SPECIALTY] == 4
    assert set(split[CATEGORY_SPECIALTY]) == set(SPECIALTY_BAGS)


def test_missing_from_portal_requires_review_required_segment():
    from backend.management_rinse_wf_review import (
        CATEGORY_MISSING_PORTAL,
        split_review_categories,
    )

    headline = _wf_headline(review_required=["MISS1"], review_reasons={"MISS1": ["DISAPPEARED_WITHOUT_COMPLETION"]})
    split = split_review_categories(headline)
    assert "MISS1" in split[CATEGORY_MISSING_PORTAL]
    assert split["counts"][CATEGORY_MISSING_PORTAL] == 1


def test_split_review_independent_of_operational_splits():
    from backend.management_rinse_wf_review import CATEGORY_SPLIT_ORDER, split_review_categories

    headline = _wf_headline()
    headline["specialty_metrics"] = {
        "wf": {"split_review": {"count": 0, "order_ids": []}, "split_orders": {"count": 12}}
    }
    split = split_review_categories(headline)
    assert split["counts"][CATEGORY_SPLIT_ORDER] == 0


def test_create_issue_reject_not_in_review_queues():
    from backend.management_rinse_wf_review import split_review_categories

    headline = _wf_headline(
        review_reasons={"REJ1": []},
        completed=SPECIALTY_BAGS + ["REJ1"],
    )
    split = split_review_categories(headline)
    assert "REJ1" not in split["specialty_items"]
    assert "REJ1" not in split["missing_from_portal"]


def test_resolved_specialty_does_not_resurrect():
    from backend.management_rinse_wf_review import (
        CATEGORY_SPECIALTY,
        specialty_review_is_resolved,
        split_review_categories,
    )

    assert specialty_review_is_resolved(["WF_BULK_WORKITEM_REVIEW"], bulk_cleared=True)
    headline = {
        "segments": {
            "wf": {
                "bag_ids": {"completed": ["DONE1"], "review_required": []},
            }
        },
        "review_reasons_by_bag": {},
        "review_by_reason": {},
    }
    split = split_review_categories(headline)
    assert split["counts"][CATEGORY_SPECIALTY] == 0


def test_drawer_discovers_specialty_when_headline_empty():
    from backend.management_rinse_wf_review import build_management_review_list

    cursor = MagicMock()
    empty_headline = {
        "segments": {"wf": {"bag_ids": {"completed": [], "review_required": []}}},
        "review_reasons_by_bag": {},
        "review_by_reason": {},
    }
    day = {"headline": empty_headline, "workload_meta": {}}
    day_rows = [
        {
            "bag_id": bid,
            "effective_status": "completed",
            "service_type": "WF",
            "review_reason_codes": ["WF_BULK_WORKITEM_REVIEW"],
            "rush_status": "NON-RUSH",
            "bag_snapshot": {},
        }
        for bid in SPECIALTY_BAGS[:2]
    ]
    with patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        return_value=day,
    ), patch(
        "backend.rinse_veewash_shift_day.summary_from_day_record",
        return_value=day["headline"],
    ), patch(
        "backend.rinse_veewash_shift_day.load_day_bags",
        return_value=day_rows,
    ), patch(
        "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
        return_value=day_rows,
    ), patch(
        "backend.management_rinse_wf_review._canonical_review_weights",
        return_value={},
    ), patch(
        "backend.rinse_bulk_workitems.load_bag_bulk_lines",
        return_value={},
    ):
        out = build_management_review_list(cursor, ORG, DAY, category="specialty_items")
    assert len(out.get("bags") or []) == 2
    assert (out.get("counts") or {}).get("specialty_items") == 2


def test_headline_count_matches_drawer_membership():
    from backend.management_rinse_wf_review import (
        build_management_review_list,
        review_category_count_payload,
    )

    headline = _wf_headline()
    counts = review_category_count_payload(headline)
    cursor = MagicMock()
    rows = [
        {
            "bag_id": bid,
            "effective_status": "completed",
            "service_type": "WF",
            "review_reason_codes": ["WF_BULK_WORKITEM_REVIEW"],
            "rush_status": "NON-RUSH",
            "bag_snapshot": {},
        }
        for bid in SPECIALTY_BAGS
    ]
    with patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        return_value={"headline": headline},
    ), patch(
        "backend.rinse_veewash_shift_day.summary_from_day_record",
        return_value=headline,
    ), patch(
        "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
        return_value=rows,
    ), patch(
        "backend.management_rinse_wf_review._canonical_review_weights",
        return_value={},
    ), patch(
        "backend.rinse_bulk_workitems.load_bag_bulk_lines",
        return_value={},
    ):
        lst = build_management_review_list(cursor, ORG, DAY, category="specialty_items")
    assert counts["specialty_items"] == len(lst.get("bags") or [])


def test_idempotent_reconcile_twice_same_counts():
    from backend.rinse_veewash_shift_day import _load_persisted_review_reasons_by_bag

    cursor = MagicMock()
    rows = [
        {
            "bag_id": bid,
            "review_reason_codes_json": '["WF_BULK_WORKITEM_REVIEW"]',
            "effective_status": "completed",
            "service_type": "WF",
        }
        for bid in SPECIALTY_BAGS
    ]
    cursor.fetchall.return_value = rows
    first = _load_persisted_review_reasons_by_bag(cursor, ORG, DAY)
    second = _load_persisted_review_reasons_by_bag(cursor, ORG, DAY)
    assert first == second
    assert len(first) == 4
