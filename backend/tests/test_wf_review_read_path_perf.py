"""WF Review / Step-1 drawer reads must not rebuild or N+1."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_employee_completed_bags import _enrich_credited_bag_weights
from backend.rinse_veewash_step1_api import build_drilldown

D1 = date(2026, 7, 23)


def _summary(*, review_ids=None):
    review_ids = review_ids or ["BAG00", "BAG01"]
    return {
        "selected_date_et": D1.isoformat(),
        "segments": {
            "all": {
                "bag_ids": {
                    "new_today": review_ids + ["BAG99"],
                    "carryover": [],
                    "completed": [],
                    "pending": ["BAG99"],
                    "review_required": list(review_ids),
                }
            },
            "wf_rush": {
                "bag_ids": {
                    "review_required": list(review_ids),
                    "new_today": list(review_ids),
                }
            },
        },
        "review_by_reason": {"WF_ZERO_OR_MISSING_POST_WEIGHT": list(review_ids)},
        "review_reasons_by_bag": {
            bid: ["WF_ZERO_OR_MISSING_POST_WEIGHT"] for bid in review_ids
        },
        "shift_day": {"status": "OPEN"},
    }


def _snap(bid: str) -> dict:
    return {
        "bag_id": bid,
        "service_type": "WF",
        "rush_status": "RUSH",
        "new_or_carryover": "new_today",
        "effective_status": "review_required",
        "pre_weight_lbs": 12.5,
        "post_weight_lbs": None,
        "review_reason_codes": ["WF_ZERO_OR_MISSING_POST_WEIGHT"],
        "bag_snapshot": {
            "bag_id": bid,
            "customer_name": f"Cust {bid}",
            "service_type": "WF",
            "rush_flag": "RUSH",
            "outcome": "review_required",
            "entry_class": "new_today",
            "pre_weight_lbs": 12.5,
            "reason_codes": ["WF_ZERO_OR_MISSING_POST_WEIGHT"],
        },
        "updated_at": "2026-07-23T12:00:00",
    }


def test_queue_get_does_not_persist_or_rebuild_day():
    cursor = MagicMock()
    summary = _summary()
    with (
        patch(
            "backend.rinse_veewash_shift_day.get_day_headline",
            return_value={"status": "OPEN", "headline": summary},
        ),
        patch("backend.rinse_veewash_shift_day.summary_from_day_record", return_value=summary),
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[_snap("BAG00"), _snap("BAG01")],
        ),
        patch("backend.rinse_veewash_step1_api.build_step1_payload") as rebuild,
        patch("backend.rinse_bulk_workitems.list_workitems", return_value=[]),
        patch(
            "backend.rinse_scan_freshness.freshness_from_day_and_presence",
            return_value={"ok": True},
        ),
    ):
        out = build_drilldown(
            cursor,
            3,
            selected_date_et=D1,
            metric="review_required",
            page=1,
            page_size=25,
            include_details=False,
        )
    rebuild.assert_not_called()
    assert [b["bag_id"] for b in out["bags"]] == ["BAG00", "BAG01"]
    assert out["pagination"]["total"] == 2
    for bag in out["bags"]:
        assert bag.get("scans") == []
        assert bag.get("bulk_workitems") == []
        assert bag.get("corrections") == []


def test_detail_get_does_not_persist_or_rebuild_day():
    cursor = MagicMock()
    summary = _summary()
    with (
        patch(
            "backend.rinse_veewash_shift_day.get_day_headline",
            return_value={"status": "OPEN", "headline": summary},
        ),
        patch("backend.rinse_veewash_shift_day.summary_from_day_record", return_value=summary),
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[_snap("BAG00")],
        ),
        patch("backend.rinse_veewash_step1_api.build_step1_payload") as rebuild,
        patch("backend.rinse_bulk_workitems.load_bulk_workitem_scan_map", return_value={}),
        patch("backend.rinse_bulk_workitems.load_bag_bulk_lines", return_value={}),
        patch("backend.rinse_bulk_workitems.load_bulk_resolutions", return_value={}),
        patch("backend.rinse_bulk_workitems.list_workitems", return_value=[]),
        patch("backend.rinse_bulk_workitems.load_bag_bulk_audits", return_value=[]),
        patch("backend.rinse_veewash_step1_api.load_scans_for_bags", return_value={"BAG00": []}),
        patch(
            "backend.rinse_scan_freshness.freshness_from_day_and_presence",
            return_value={"ok": True},
        ),
        patch("backend.rinse_veewash_step1_api.table_exists", return_value=False),
    ):
        out = build_drilldown(
            cursor,
            3,
            selected_date_et=D1,
            metric="review_required",
            bag_id="BAG00",
            include_details=True,
            page=1,
            page_size=1,
        )
    rebuild.assert_not_called()
    assert len(out["bags"]) == 1
    assert out["bags"][0]["bag_id"] == "BAG00"


def test_missing_snapshot_does_not_rebuild():
    cursor = MagicMock()
    with (
        patch("backend.rinse_veewash_shift_day.get_day_headline", return_value=None),
        patch("backend.rinse_veewash_shift_day.summary_from_day_record", return_value=None),
        patch("backend.rinse_veewash_step1_api.build_step1_payload") as rebuild,
    ):
        out = build_drilldown(
            cursor,
            3,
            selected_date_et=D1,
            metric="review_required",
            include_details=False,
        )
    rebuild.assert_not_called()
    assert out["bags"] == []
    assert out.get("snapshot_missing") is True


def test_queue_returns_only_matching_review_rows():
    cursor = MagicMock()
    summary = _summary(review_ids=["BAG00"])
    with (
        patch(
            "backend.rinse_veewash_shift_day.get_day_headline",
            return_value={"status": "OPEN", "headline": summary},
        ),
        patch("backend.rinse_veewash_shift_day.summary_from_day_record", return_value=summary),
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[_snap("BAG00")],
        ) as load_page,
        patch(
            "backend.rinse_scan_freshness.freshness_from_day_and_presence",
            return_value={"ok": True},
        ),
    ):
        out = build_drilldown(
            cursor,
            3,
            selected_date_et=D1,
            metric="review_required",
            include_details=False,
        )
    assert load_page.call_args.args[3] == ["BAG00"]
    assert [b["bag_id"] for b in out["bags"]] == ["BAG00"]


def test_enrich_credited_weights_does_not_call_per_bag_resolvers():
    cursor = MagicMock()
    bags = [
        {
            "bag_id": f"BAG{i:02d}",
            "service_type": "WF",
            "completed_lbs": 20.0,
            "weight_lbs": 20.0,
            "pre_weight_lbs": 21.0,
            "post_weight_lbs": 19.5,
        }
        for i in range(5)
    ]
    workload = [
        {
            "bag_id": f"BAG{i:02d}",
            "service_type": "WF",
            "pre_weight_lbs": 21.0,
            "post_weight_lbs": 19.5,
        }
        for i in range(5)
    ]
    with (
        patch(
            "backend.rinse_workload_bag_weight.finalize_completed_bag_weight_fields"
        ),
        patch(
            "backend.rinse_workload_bag_weight.load_weight_repair_sources_for_bags",
            return_value={},
        ),
        patch("backend.daily_operations.resolve_authoritative_post_weight") as auth,
        patch("backend.daily_operations.resolve_evidence_post_weight") as post,
        patch("backend.daily_operations.resolve_evidence_pre_weight") as pre,
    ):
        _enrich_credited_bag_weights(
            bags,
            cursor=cursor,
            organization_id=3,
            workload_rows=workload,
            events_by_bag={},
            registry_meta={},
            selected_date_et=D1,
            as_of_end=None,
        )
    auth.assert_not_called()
    post.assert_not_called()
    pre.assert_not_called()
    for bag in bags:
        assert bag["credited_weight_lbs"] == 21.0
        assert bag["output_weight_lbs"] == 19.5
        assert bag["missing_production_credit_weight"] is False
