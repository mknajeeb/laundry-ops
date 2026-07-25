"""Step-1 KPI drill-down: each card opens only its own queue subset."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_veewash_step1_api import (
    _filter_bag_ids,
    build_drilldown,
    normalize_step1_queue_metric,
)

D1 = date(2026, 7, 24)


def _summary():
    return {
        "selected_date_et": D1.isoformat(),
        "segments": {
            "wf": {
                "bag_ids": {
                    "new_today": [f"WF{i:02d}" for i in range(1, 75)],
                    "carryover": [],
                    "completed": [f"WF{i:02d}" for i in range(1, 62)],
                    "pending": ["WF73", "WF74"],
                    "review_required": [f"WF{i:02d}" for i in range(62, 73)],
                }
            },
            "hd": {
                "bag_ids": {
                    "new_today": [f"HD{i:02d}" for i in range(1, 11)],
                    "carryover": [],
                    "completed": ["HD01"],
                    "pending": [f"HD{i:02d}" for i in range(2, 11)],
                    "review_required": [],
                }
            },
            "all": {
                "bag_ids": {
                    "new_today": [f"WF{i:02d}" for i in range(1, 75)]
                    + [f"HD{i:02d}" for i in range(1, 11)],
                    "carryover": [],
                    "completed": [f"WF{i:02d}" for i in range(1, 62)] + ["HD01"],
                    "pending": ["WF73", "WF74"] + [f"HD{i:02d}" for i in range(2, 11)],
                    "review_required": [f"WF{i:02d}" for i in range(62, 73)],
                }
            },
        },
        "review_by_reason": {},
        "shift_day": {"status": "OPEN"},
    }


def test_normalize_queue_aliases():
    assert normalize_step1_queue_metric("production_recorded") == "completed"
    assert normalize_step1_queue_metric("production_missing") == "pending"
    assert normalize_step1_queue_metric("all") == "active_workload"
    assert normalize_step1_queue_metric("comforter_orders") == "comforter_orders"
    assert normalize_step1_queue_metric("bath_mat_orders") == "bath_mat_orders"
    assert normalize_step1_queue_metric("rejected_orders") == "rejected_orders"
    assert normalize_step1_queue_metric("split_orders") == "split_orders"
    assert normalize_step1_queue_metric("bogus") == "review_required"


def test_wf_queue_counts_match_kpi_bags():
    s = _summary()
    assert len(_filter_bag_ids(s, metric="active_workload", service="wf", rush="all")) == 74
    assert len(_filter_bag_ids(s, metric="completed", service="wf", rush="all")) == 61
    assert len(_filter_bag_ids(s, metric="pending", service="wf", rush="all")) == 2
    assert len(_filter_bag_ids(s, metric="review_required", service="wf", rush="all")) == 11


def test_hd_queue_aliases_match_kpi_bags():
    s = _summary()
    assert len(_filter_bag_ids(s, metric="active_workload", service="hd", rush="all")) == 10
    assert len(_filter_bag_ids(s, metric="production_recorded", service="hd", rush="all")) == 1
    assert len(_filter_bag_ids(s, metric="production_missing", service="hd", rush="all")) == 9
    assert _filter_bag_ids(s, metric="review_required", service="hd", rush="all") == []


def test_wf_card_does_not_include_hd_bags():
    s = _summary()
    ids = _filter_bag_ids(s, metric="completed", service="wf", rush="all")
    assert all(b.startswith("WF") for b in ids)
    assert "HD01" not in ids


def test_missing_service_segment_does_not_fall_back_to_all():
    s = {"segments": {"all": {"bag_ids": {"completed": ["ALL1"]}}}}
    assert _filter_bag_ids(s, metric="completed", service="wf", rush="all") == []


def test_build_drilldown_pagination_total_equals_queue():
    cursor = MagicMock()
    summary = _summary()
    completed = summary["segments"]["wf"]["bag_ids"]["completed"]
    page_ids = completed[:25]

    def _snap(bid: str) -> dict:
        return {
            "bag_id": bid,
            "service_type": "WF",
            "effective_status": "completed",
            "bag_snapshot": {"bag_id": bid, "service_type": "WF", "outcome": "completed"},
        }

    with (
        patch(
            "backend.rinse_veewash_shift_day.get_day_headline",
            return_value={"status": "OPEN", "headline": summary},
        ),
        patch(
            "backend.rinse_veewash_shift_day.summary_from_day_record",
            return_value=summary,
        ),
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[_snap(b) for b in page_ids],
        ),
        patch("backend.rinse_bulk_workitems.load_bulk_workitem_scan_map", return_value={}),
        patch("backend.rinse_bulk_workitems.load_bag_bulk_lines", return_value={}),
        patch("backend.rinse_bulk_workitems.load_bulk_resolutions", return_value={}),
        patch("backend.rinse_bulk_workitems.list_workitems", return_value=[]),
    ):
        out = build_drilldown(
            cursor,
            3,
            selected_date_et=D1,
            metric="completed",
            service="wf",
            rush="all",
            page=1,
            page_size=25,
        )
    assert out["pagination"]["total"] == 61
    assert len(out["bags"]) == 25
    assert all(b["bag_id"].startswith("WF") for b in out["bags"])
